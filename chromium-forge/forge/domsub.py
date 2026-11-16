"""Clean-room OBL-04 implementation: Regex domain substitution & atomic CRC32 revert cache.

Preserves 1:1 upstream invariants (`utils/domain_substitution.py:27-313`):
- `#`-delimited `<regex>#<replacement>` pairs compiled with Python `re`.
- Dual-encoding (`UTF-8`, `ISO-8859-1`) byte-level roundtrip preserving CRLF/LF line endings.
- `+1s` (`+1_000_000_000` ns) `os.utime` shift on `apply` and `-1s` on `revert` so Ninja build
  graphs remain monotonic during substitution and clean upon restoration.
- Backup archive layout: `orig/<relative_path>` + `cache_index.list` (`<path>|<crc32_08x>`).
- Pre-flight atomic CRC32 integrity verification before mutating a single file during `revert`.

Fixes upstream bugs:
- Bug #4 (`domain_substitution.py:209`): Supports `.tar`, `.tar.gz`/`.tgz`, `.tar.bz2`, `.tar.xz`
  without crashing on unsupported `compresslevel=1` in `lzma` or `w:tar`.
- Bug #3 (`domain_substitution.py:287`): Extracts revert archives purely in Python without crashing
  on missing Windows 7-Zip HKLM registry entries.
- Explicit UTF-8 encoding and `\n` newlines on standalone `sh`/`perl` script generation.
"""

from __future__ import annotations

from dataclasses import dataclass
import io
import os
from pathlib import Path
import re
import stat
import tarfile
import tempfile
import zlib

ENCODING = "utf-8"
TREE_ENCODINGS = ("utf-8", "iso-8859-1")
PATTERN_DELIM = "#"
INDEX_FILENAME = "cache_index.list"
INDEX_DELIM = "|"
ONE_SECOND_NS = 1_000_000_000


@dataclass(frozen=True)
class RegexRule:
    pattern: re.Pattern[str]
    replacement: str
    raw_pattern: str


class DomainRegexSet:
    """Compiled `#`-delimited domain substitution regex set."""

    def __init__(self, lines: list[str]) -> None:
        rules: list[RegexRule] = []
        raw_patterns: list[str] = []
        for idx, raw_line in enumerate(lines, start=1):
            if not raw_line:
                continue
            if raw_line.count(PATTERN_DELIM) != 1:
                raise ValueError(
                    f"domain_regex line {idx} must contain exactly one '#' delimiter: {raw_line!r}"
                )
            pat_str, repl_str = raw_line.split(PATTERN_DELIM)
            if not pat_str or not repl_str:
                raise ValueError(f"domain_regex line {idx} has empty pattern or replacement")
            rules.append(RegexRule(pattern=re.compile(pat_str), replacement=repl_str, raw_pattern=pat_str))
            raw_patterns.append(f"(?:{pat_str})")
        if not rules:
            raise ValueError("domain_regex list contains zero rules")
        self.rules = tuple(rules)
        self.combined_search = re.compile("|".join(raw_patterns))

    @classmethod
    def from_file(cls, path: Path) -> "DomainRegexSet":
        return cls(path.read_text(encoding=ENCODING).splitlines())

    def substitute_text(self, content: str) -> tuple[str, int]:
        total_subs = 0
        current = content
        for rule in self.rules:
            current, count = rule.pattern.subn(rule.replacement, current)
            total_subs += count
        return current, total_subs


def retarget_domain_regex_tld(lines: list[str], new_tld: str, old_tld: str = "qjz9zk") -> list[str]:
    """Rewrite `domain_regex.list` rules to terminate at `.<new_tld>` instead of `.<old_tld>`."""
    retargeted: list[str] = []
    suffix = f".{old_tld}"
    replacement_suffix = f".{new_tld}"
    for line in lines:
        if not line:
            continue
        pat, repl = line.split(PATTERN_DELIM, 1)
        if repl.endswith(suffix):
            repl = repl[: -len(suffix)] + replacement_suffix
        retargeted.append(f"{pat}{PATTERN_DELIM}{repl}")
    return retargeted


def _tar_write_kwargs(cache_path: Path) -> tuple[str, dict[str, int]]:
    name = cache_path.name.lower()
    if name.endswith((".tar.gz", ".tgz")):
        return "w:gz", {"compresslevel": 1}
    if name.endswith((".tar.bz2", ".tbz2")):
        return "w:bz2", {"compresslevel": 1}
    if name.endswith((".tar.xz", ".txz")):
        return "w:xz", {}
    if name.endswith(".tar"):
        return "w", {}
    raise ValueError(f"Unsupported domain substitution cache archive suffix: {cache_path.name}")


def _tar_read_mode(cache_path: Path) -> str:
    name = cache_path.name.lower()
    if name.endswith((".tar.gz", ".tgz")):
        return "r:gz"
    if name.endswith((".tar.bz2", ".tbz2")):
        return "r:bz2"
    if name.endswith((".tar.xz", ".txz")):
        return "r:xz"
    if name.endswith(".tar"):
        return "r:"
    raise ValueError(f"Unsupported domain substitution cache archive suffix: {cache_path.name}")


def _ensure_writable(path: Path) -> None:
    if not os.access(path, os.W_OK):
        path.chmod(path.stat().st_mode | stat.S_IWUSR)


@dataclass
class DomSubReport:
    scanned_files: int
    modified_files: int
    total_replacements: int
    skipped_missing: int


def apply_domain_substitution(
    regex_set: DomainRegexSet,
    file_list: list[str],
    source_tree: Path,
    cache_archive: Path | None = None,
) -> DomSubReport:
    """Apply regex domain substitution in-place with optional atomic CRC32 revert archive."""
    if cache_archive is not None and cache_archive.exists():
        raise FileExistsError(f"Domain substitution cache already exists: {cache_archive}")

    root = source_tree.resolve()
    if not root.exists():
        raise FileNotFoundError(f"Source tree not found: {root}")

    tar_handle: tarfile.TarFile | None = None
    index_lines: list[str] = []
    scanned = 0
    modified = 0
    replacements = 0
    skipped = 0

    try:
        if cache_archive is not None:
            cache_archive.parent.mkdir(parents=True, exist_ok=True)
            mode, kwargs = _tar_write_kwargs(cache_archive)
            tar_handle = tarfile.open(str(cache_archive), mode, **kwargs)  # type: ignore[arg-type]

        from .http_base import safe_join

        for raw_rel in file_list:
            rel = raw_rel.strip()
            if not rel:
                continue
            if INDEX_DELIM in rel:
                raise ValueError(f"File path must not contain {INDEX_DELIM!r}: {rel}")

            rel_posix = Path(rel).as_posix()
            target = safe_join(root, rel_posix)
            if not target.exists() or target.is_symlink():
                skipped += 1
                continue

            scanned += 1
            orig_stat = target.stat()
            orig_bytes = target.read_bytes()

            decoded_text: str | None = None
            matched_enc = "utf-8"
            for enc in TREE_ENCODINGS:
                try:
                    decoded_text = orig_bytes.decode(enc)
                    matched_enc = enc
                    break
                except UnicodeDecodeError:
                    continue
            assert decoded_text is not None  # ISO-8859-1 is total over 0x00..0xFF

            new_text, count = regex_set.substitute_text(decoded_text)
            if count == 0:
                continue

            new_bytes = new_text.encode(matched_enc)
            _ensure_writable(target)
            with target.open("r+b") as handle:
                handle.seek(0)
                handle.write(new_bytes)
                handle.truncate()
            os.utime(
                target,
                ns=(orig_stat.st_atime_ns + ONE_SECOND_NS, orig_stat.st_mtime_ns + ONE_SECOND_NS),
            )

            modified += 1
            replacements += count

            if tar_handle is not None:
                crc_hex = f"{zlib.crc32(new_bytes):08x}"
                index_lines.append(f"{rel_posix}{INDEX_DELIM}{crc_hex}")
                info = tarfile.TarInfo(name=f"orig/{rel_posix}")
                info.size = len(orig_bytes)
                info.mtime = int(orig_stat.st_mtime)
                tar_handle.addfile(info, io.BytesIO(orig_bytes))

        if tar_handle is not None:
            index_bytes = ("\n".join(index_lines) + ("\n" if index_lines else "")).encode(ENCODING)
            idx_info = tarfile.TarInfo(name=INDEX_FILENAME)
            idx_info.size = len(index_bytes)
            tar_handle.addfile(idx_info, io.BytesIO(index_bytes))
    except Exception:
        if tar_handle is not None:
            tar_handle.close()
            tar_handle = None
        if cache_archive is not None and cache_archive.exists():
            cache_archive.unlink(missing_ok=True)
        raise
    finally:
        if tar_handle is not None:
            tar_handle.close()

    return DomSubReport(
        scanned_files=scanned,
        modified_files=modified,
        total_replacements=replacements,
        skipped_missing=skipped,
    )


def revert_domain_substitution(cache_archive: Path, source_tree: Path) -> int:
    """Verify CRC32 integrity of all substituted files first, then atomically restore originals."""
    if not cache_archive.exists():
        raise FileNotFoundError(f"Domain substitution cache missing: {cache_archive}")
    root = source_tree.resolve()
    if not root.exists():
        raise FileNotFoundError(f"Source tree missing: {root}")

    with tempfile.TemporaryDirectory(prefix="domsubcache_files_", dir=str(root)) as tmp_str:
        extract_root = Path(tmp_str)
        with tarfile.open(str(cache_archive), _tar_read_mode(cache_archive)) as tf:
            for member in tf.getmembers():
                if ".." in member.name.split("/") or member.name.startswith("/"):
                    raise ValueError(f"Unsafe archive member in domsub cache: {member.name}")
                tf.extract(member, path=str(extract_root), filter="data")

        index_file = extract_root / INDEX_FILENAME
        if not index_file.exists():
            raise KeyError(f"Corrupt domain substitution cache: missing {INDEX_FILENAME}")

        entries: list[tuple[str, int]] = []
        seen_paths: set[str] = set()
        for line in index_file.read_text(encoding=ENCODING).splitlines():
            if not line.strip():
                continue
            if line.count(INDEX_DELIM) != 1:
                raise KeyError(f"Malformed index entry: {line!r}")
            rel_posix, hex_crc = line.split(INDEX_DELIM)
            if rel_posix in seen_paths:
                raise KeyError(f"Duplicate path in {INDEX_FILENAME}: {rel_posix}")
            seen_paths.add(rel_posix)
            entries.append((rel_posix, int(hex_crc, 16)))

        # Pre-flight atomic integrity gate: verify ALL files before mutating ANY file!
        from .http_base import safe_join

        for rel_posix, expected_crc in entries:
            live_file = safe_join(root, rel_posix)
            backup_file = safe_join(extract_root / "orig", rel_posix)
            if not live_file.exists():
                raise KeyError(f"Substituted file deleted since apply: {rel_posix}")
            if not backup_file.exists():
                raise KeyError(f"Backup payload missing in cache archive: orig/{rel_posix}")
            actual_crc = zlib.crc32(live_file.read_bytes())
            if actual_crc != expected_crc:
                raise KeyError(
                    f"CRC32 integrity mismatch on {rel_posix}: file was modified after substitution "
                    f"(expected {expected_crc:08x}, found {actual_crc:08x})"
                )

        # Atomic same-filesystem replacement + exact pre-apply nanosecond timestamp restoration
        for rel_posix, _ in entries:
            live_file = safe_join(root, rel_posix)
            backup_file = safe_join(extract_root / "orig", rel_posix)
            post_stat = live_file.stat()
            _ensure_writable(live_file)
            backup_file.replace(live_file)
            os.utime(
                live_file,
                ns=(post_stat.st_atime_ns - ONE_SECOND_NS, post_stat.st_mtime_ns - ONE_SECOND_NS),
            )

    cache_archive.unlink()
    return len(entries)


def generate_standalone_domsub_script(
    regex_lines: list[str],
    file_list: list[str],
    output_script: Path,
    backup_mode: str = "tar",
) -> None:
    """Generate a POSIX `#!/bin/sh -e` + `perl` standalone domain substitution script (`LF` endings)."""
    if backup_mode not in ("tar", "quilt", "none"):
        raise ValueError(f"Unsupported backup_mode: {backup_mode}")
    if output_script.exists():
        raise FileExistsError(f"Output script already exists: {output_script}")

    perl_exprs: list[str] = []
    for line in regex_lines:
        if not line:
            continue
        converted = re.sub(r"\\g<(\d+)>", r"${\1}", line)
        perl_exprs.append(f"s#{converted}#g;")

    clean_files = [f.strip() for f in file_list if f.strip()]
    files_heredoc = "\n".join(clean_files)
    perl_prog = "".join(perl_exprs).replace("'", "'\\''")

    lines = ["#!/bin/sh -e", ""]
    if backup_mode == "tar":
        lines.extend(
            [
                "tar cf domain-substitution.orig.tar --verbatim-files-from --files-from=- << 'EOF_FILES'",
                files_heredoc,
                "EOF_FILES",
                "",
            ]
        )
    elif backup_mode == "quilt":
        lines.extend(
            [
                "mkdir -p .pc/domain-substitution.VIRTUAL.patch",
                "tar cf - --verbatim-files-from --files-from=- << 'EOF_FILES' | tar xf - -C .pc/domain-substitution.VIRTUAL.patch",
                files_heredoc,
                "EOF_FILES",
                "echo domain-substitution.VIRTUAL.patch >> .pc/applied-patches",
                "",
            ]
        )

    lines.extend(
        [
            "tr '\\n' '\\0' << 'EOF_FILES' | xargs -0 perl -0777 -C0 -pwi -e '" + perl_prog + "'",
            files_heredoc,
            "EOF_FILES",
            "",
        ]
    )
    output_script.parent.mkdir(parents=True, exist_ok=True)
    output_script.write_text("\n".join(lines), encoding=ENCODING, newline="\n")
