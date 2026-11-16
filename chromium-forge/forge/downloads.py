"""Clean-room OBL-01 implementation: downloads.ini parser, multi-hash verifier, and safe unpacker.

Fixes upstream bugs discovered via REA static analysis:
- Bug #3 (`utils/_extraction.py:29-40`): Catches Windows registry `FileNotFoundError` when 7-Zip is
  absent in HKLM and falls back cleanly to streaming Python `tarfile` / `zipfile`.
- Bug #4 (`utils/_extraction.py:165`): Maps `.tar`, `.tgz`, `.tar.gz`, `.tar.bz2`, and `.tar.xz`
  to valid `tarfile` streaming modes without invalid `compresslevel` flags.
- Bug #5 (`utils/downloads.py:67,405`): Rejects `..` path traversal in `output_path` and
  `strip_leading_dirs`, and enforces hash verification prior to `unpack`.
"""

from __future__ import annotations

import configparser
from dataclasses import dataclass, field
import hashlib
import os
from pathlib import Path, PurePosixPath
import shutil
import ssl
import subprocess
import tarfile
import urllib.request
import zipfile

ENCODING = "utf-8"
ALLOWED_EXTRACTORS = frozenset({"tar", "7z", "winrar", "zip"})
ALLOWED_HASHES = ("md5", "sha1", "sha256", "sha512")
ALLOWED_KEYS = frozenset(
    {
        "url",
        "download_filename",
        "output_path",
        "version",
        "strip_leading_dirs",
        "extractor",
        "hash_url",
        *ALLOWED_HASHES,
    }
)


class SchemaValidationError(ValueError):
    """Raised when downloads.ini violates schema or path boundary invariants."""


class HashMismatchError(RuntimeError):
    """Raised when a downloaded file fails cryptographic digest verification."""


def _validate_safe_relpath(raw: str, field_name: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise SchemaValidationError(f"{field_name} must be a non-empty string")
    candidate = Path(raw)
    if candidate.is_absolute() or (candidate.drive != ""):
        raise SchemaValidationError(f"{field_name} must be relative, got {raw!r}")
    parts = PurePosixPath(raw.replace("\\", "/")).parts
    if ".." in parts:
        raise SchemaValidationError(f"{field_name} must not contain '..' traversal: {raw!r}")
    return raw


@dataclass(frozen=True)
class DownloadEntry:
    section: str
    url: str
    download_filename: str
    output_path: str
    version: str | None = None
    strip_leading_dirs: str | None = None
    extractor: str = "tar"
    hashes: dict[str, str] = field(default_factory=dict)
    hash_url: tuple[str, str, str] | None = None


def parse_downloads_ini(ini_paths: list[Path], chromium_version: str) -> list[DownloadEntry]:
    """Parse, interpolate, merge, validate, and sort `downloads.ini` files."""
    if not ini_paths:
        raise SchemaValidationError("At least one downloads.ini path is required")

    parser = configparser.ConfigParser(defaults={"_chromium_version": chromium_version})
    for path in ini_paths:
        if not path.exists():
            raise FileNotFoundError(f"INI file not found: {path}")
        with path.open("r", encoding=ENCODING) as handle:
            parser.read_file(handle, source=str(path))

    entries: list[DownloadEntry] = []
    for section in parser.sections():
        items = {k: v for k, v in parser.items(section) if k != "_chromium_version"}
        unknown = set(items) - ALLOWED_KEYS
        if unknown:
            raise SchemaValidationError(f"[{section}] contains unknown keys: {sorted(unknown)}")

        for req in ("url", "download_filename", "output_path"):
            if req not in items or not items[req].strip():
                raise SchemaValidationError(f"[{section}] missing required non-empty key: {req!r}")

        _validate_safe_relpath(items["output_path"], f"[{section}].output_path")
        _validate_safe_relpath(items["download_filename"], f"[{section}].download_filename")

        strip_dirs = items.get("strip_leading_dirs")
        if strip_dirs is not None:
            _validate_safe_relpath(strip_dirs, f"[{section}].strip_leading_dirs")

        extractor = items.get("extractor", "tar")
        if extractor not in ALLOWED_EXTRACTORS:
            raise SchemaValidationError(f"[{section}] invalid extractor {extractor!r}")

        hashes = {h: items[h].strip().lower() for h in ALLOWED_HASHES if h in items and items[h].strip()}

        parsed_hash_url: tuple[str, str, str] | None = None
        if "hash_url" in items:
            raw_hu = items["hash_url"]
            if raw_hu.count("|") != 2:
                raise SchemaValidationError(f"[{section}] invalid hash_url format: {raw_hu!r}")
            scheme, hash_filename, h_url = raw_hu.split("|")
            if scheme != "chromium" or not hash_filename or not h_url:
                raise SchemaValidationError(f"[{section}] unsupported hash_url: {raw_hu!r}")
            _validate_safe_relpath(hash_filename, f"[{section}].hash_url.filename")
            parsed_hash_url = (scheme, hash_filename, h_url)

        entries.append(
            DownloadEntry(
                section=section,
                url=items["url"].strip(),
                download_filename=items["download_filename"].strip(),
                output_path=items["output_path"].strip(),
                version=items.get("version"),
                strip_leading_dirs=strip_dirs,
                extractor=extractor,
                hashes=hashes,
                hash_url=parsed_hash_url,
            )
        )

    # Upstream invariant (`utils/downloads.py:152-155`): sort by normalized output_path
    return sorted(entries, key=lambda e: str(Path(e.output_path)))


def parse_chromium_hashes_file(hashes_text: str) -> dict[str, str]:
    """Parse Chromium `.hashes` file (`<algo>  <hexdigest>  <filename>`)."""
    digests: dict[str, str] = {}
    for raw_line in hashes_text.splitlines():
        line = raw_line.strip().lower()
        if not line:
            continue
        parts = line.split("  ")
        if len(parts) < 2:
            raise ValueError(f"Malformed Chromium .hashes line: {raw_line!r}")
        algo, hex_digest = parts[0].strip(), parts[1].strip()
        if algo in hashlib.algorithms_available:
            digests[algo] = hex_digest
    return digests


def compute_file_digest(path: Path, algorithm: str) -> str:
    hasher = hashlib.new(algorithm)
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            hasher.update(chunk)
    return hasher.hexdigest().lower()


def verify_cached_downloads(entries: list[DownloadEntry], cache_dir: Path) -> None:
    """Verify every cached archive against inline hashes and/or `.hashes` files."""
    for entry in entries:
        archive_path = cache_dir / entry.download_filename
        if not archive_path.exists():
            raise FileNotFoundError(f"Cached download missing for [{entry.section}]: {archive_path}")

        expected = dict(entry.hashes)
        if entry.hash_url is not None:
            _, hash_filename, _ = entry.hash_url
            hash_path = cache_dir / hash_filename
            if not hash_path.exists():
                raise FileNotFoundError(f"Cached .hashes file missing: {hash_path}")
            expected.update(parse_chromium_hashes_file(hash_path.read_text(encoding=ENCODING)))

        for algo, expected_hex in expected.items():
            actual_hex = compute_file_digest(archive_path, algo)
            if actual_hex != expected_hex.lower():
                raise HashMismatchError(
                    f"[{entry.section}] {algo} mismatch on {archive_path.name}: "
                    f"expected {expected_hex}, got {actual_hex}"
                )


def retrieve_downloads(
    entries: list[DownloadEntry],
    cache_dir: Path,
    disable_ssl_verify: bool = False,
) -> None:
    """Download missing archives atomically via `.partial` files and verify hashes."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    curl_bin = shutil.which("curl.exe") or shutil.which("curl")

    def _fetch(url: str, destination: Path) -> None:
        if destination.exists():
            return
        partial = destination.with_name(destination.name + ".partial")
        if curl_bin:
            cmd = [curl_bin, "-fL", "--retry", "3", "-C", "-", "-o", str(partial), url]
            if disable_ssl_verify:
                cmd.insert(1, "-k")
            subprocess.run(cmd, check=True)
        else:
            ctx = ssl._create_unverified_context() if disable_ssl_verify else None
            req = urllib.request.Request(url, headers={"User-Agent": "chromium-forge/1.0"})
            with urllib.request.urlopen(req, context=ctx) as resp, partial.open("wb") as out:
                shutil.copyfileobj(resp, out)
        partial.replace(destination)

    for entry in entries:
        _fetch(entry.url, cache_dir / entry.download_filename)
        if entry.hash_url is not None:
            _, hash_filename, hash_url = entry.hash_url
            _fetch(hash_url, cache_dir / hash_filename)

    verify_cached_downloads(entries, cache_dir)


def _find_7z_binary() -> str | None:
    """Locate 7z safely on Windows/POSIX without crashing when HKLM key is absent."""
    direct = shutil.which("7z") or shutil.which("7za")
    if direct:
        return direct
    if os.name == "nt":
        try:
            import winreg

            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    with winreg.OpenKey(
                        hive, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\7zFM.exe"
                    ) as key:
                        install_dir = winreg.QueryValueEx(key, "Path")[0]
                        candidate = Path(install_dir) / "7z.exe"
                        if candidate.exists():
                            return str(candidate)
                except OSError:
                    continue
        except ImportError:
            pass
        for fallback in (Path(r"C:\Program Files\7-Zip\7z.exe"), Path(r"C:\Program Files (x86)\7-Zip\7z.exe")):
            if fallback.exists():
                return str(fallback)
    return None


def _tar_stream_mode(archive_path: Path) -> str:
    name = archive_path.name.lower()
    if name.endswith((".tar.gz", ".tgz")):
        return "r|gz"
    if name.endswith((".tar.bz2", ".tbz2")):
        return "r|bz2"
    if name.endswith((".tar.xz", ".txz")):
        return "r|xz"
    if name.endswith(".tar"):
        return "r|"
    raise ValueError(f"Unsupported tar archive extension: {archive_path.name}")


def _can_create_symlinks(probe_dir: Path) -> bool:
    probe = probe_dir / ".forge_symlink_probe"
    try:
        os.symlink("target", probe)
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def extract_archive(
    archive_path: Path,
    destination_dir: Path,
    strip_leading_dirs: str | None = None,
) -> None:
    """Extract `.zip` or `.tar*` safely without OOM or HKLM registry crashes."""
    destination_dir.mkdir(parents=True, exist_ok=True)
    dest_resolved = destination_dir.resolve()
    strip_posix = PurePosixPath(strip_leading_dirs) if strip_leading_dirs else None

    if archive_path.suffix.lower() == ".zip":
        from .http_base import SafePathError, safe_join

        with zipfile.ZipFile(archive_path, "r") as zf:
            for info in zf.infolist():
                member_posix = PurePosixPath(info.filename.replace("\\", "/"))
                if member_posix.is_absolute() or ".." in member_posix.parts:
                    raise SchemaValidationError(f"Unsafe zip member path: {info.filename}")
                if strip_posix is not None:
                    try:
                        member_posix = member_posix.relative_to(strip_posix)
                    except ValueError:
                        continue
                if not member_posix.parts:
                    continue
                try:
                    target = safe_join(dest_resolved, *member_posix.parts)
                except SafePathError as exc:
                    raise SchemaValidationError(f"Unsafe zip member path: {info.filename}") from exc
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(info, "r") as src, target.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
        return

    if archive_path.name.lower().endswith(".7z.exe") or archive_path.suffix.lower() == ".7z":
        sevenz = _find_7z_binary()
        if not sevenz:
            raise RuntimeError(f"7-Zip is required to unpack {archive_path.name}, but 7z was not found.")
        if strip_posix is None:
            subprocess.run([sevenz, "x", "-y", "-aoa", f"-o{dest_resolved}", str(archive_path)], check=True)
        else:
            import tempfile

            with tempfile.TemporaryDirectory(dir=str(dest_resolved.parent)) as tmp_7z:
                subprocess.run([sevenz, "x", "-y", "-aoa", f"-o{tmp_7z}", str(archive_path)], check=True)
                stripped_src = Path(tmp_7z).joinpath(*strip_posix.parts)
                if stripped_src.exists():
                    shutil.copytree(stripped_src, dest_resolved, dirs_exist_ok=True)
        return

    # Streaming pure-Python tar extractor (O(1) member memory via custom list)
    from .http_base import SafePathError, safe_join

    class _NoCacheMembers(list):
        def append(self, _item: object) -> None:
            return None

    symlinks_ok = _can_create_symlinks(dest_resolved)
    mode = _tar_stream_mode(archive_path)
    with tarfile.open(str(archive_path), mode) as tf:
        tf.members = _NoCacheMembers()  # type: ignore[assignment]
        for member in tf:
            member_posix = PurePosixPath(member.name.replace("\\", "/"))
            if member_posix.is_absolute() or ".." in member_posix.parts:
                raise SchemaValidationError(f"Unsafe tar member: {member.name}")
            if strip_posix is not None:
                try:
                    member_posix = member_posix.relative_to(strip_posix)
                except ValueError:
                    continue
            if not member_posix.parts:
                continue
            try:
                target = safe_join(dest_resolved, *member_posix.parts)
            except SafePathError as exc:
                raise SchemaValidationError(f"Unsafe tar member: {member.name}") from exc
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.issym():
                resolved_sym = (target.parent / member.linkname).resolve()
                if resolved_sym != dest_resolved and not resolved_sym.is_relative_to(dest_resolved):
                    raise SchemaValidationError(f"Unsafe tar symlink escape: {member.name} -> {member.linkname}")
                if symlinks_ok:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.unlink(missing_ok=True)
                    os.symlink(member.linkname, target)
            elif member.islnk():
                link_posix = PurePosixPath(member.linkname.replace("\\", "/"))
                if strip_posix is not None:
                    try:
                        link_posix = link_posix.relative_to(strip_posix)
                    except ValueError:
                        continue
                try:
                    link_target = safe_join(dest_resolved, *link_posix.parts)
                except SafePathError as exc:
                    raise SchemaValidationError(f"Unsafe tar hardlink: {member.linkname}") from exc
                if link_target.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.unlink(missing_ok=True)
                    shutil.copy2(link_target, target)
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                extracted = tf.extractfile(member)
                if extracted is not None:
                    with extracted, target.open("wb") as out:
                        shutil.copyfileobj(extracted, out)


def unpack_downloads(
    entries: list[DownloadEntry],
    cache_dir: Path,
    source_tree: Path,
    verify_hashes: bool = True,
) -> None:
    """Verify hashes first (fixing upstream doc/code bug) and unpack in sorted path order."""
    from .http_base import safe_join

    if verify_hashes:
        verify_cached_downloads(entries, cache_dir)
    source_tree.mkdir(parents=True, exist_ok=True)
    for entry in entries:
        target_dir = safe_join(source_tree, entry.output_path) if entry.output_path not in ("./", ".") else source_tree.resolve()
        extract_archive(
            cache_dir / entry.download_filename,
            target_dir,
            strip_leading_dirs=entry.strip_leading_dirs,
        )
