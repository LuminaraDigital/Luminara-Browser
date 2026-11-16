"""Clean-room OBL-07 implementation: Chromium `FILES.cfg` parser & deterministic archive packager.

Preserves 1:1 upstream invariants (`utils/filescfg.py:22-95` & `ungoogled-chromium-windows/package.py`):
- Safely parses `FILES.cfg` via AST literal evaluation (eliminating raw `exec()` risk!).
- Includes only entries where `'official' in entry['buildtype']` and matching `cpu_arch` (`64bit`/`32bit`/`arm`).
- Excludes `.pdb` debug symbols and caller-supplied excluded filenames (`mini_installer.exe`, `setup.exe`, etc.).
- Supports deterministic archive timestamps (`LASTCHANGE.committime`) for reproducible `.zip` and `.tar.xz` outputs.
"""

from __future__ import annotations

import ast
from pathlib import Path
import tarfile
import time
import zipfile

ENCODING = "utf-8"


def parse_files_cfg(cfg_path: Path) -> list[dict]:
    """Parse Chromium `FILES.cfg` safely via `ast` without unrestricted `exec()`."""
    if not cfg_path.exists():
        raise FileNotFoundError(f"FILES.cfg not found: {cfg_path}")
    source = cfg_path.read_text(encoding=ENCODING)
    tree = ast.parse(source, filename=str(cfg_path))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "FILES":
                    value = ast.literal_eval(node.value)
                    if not isinstance(value, (list, tuple)):
                        raise ValueError("FILES in FILES.cfg must be a list or tuple")
                    return list(value)
    raise ValueError(f"No FILES assignment found in {cfg_path}")


def collect_official_outputs(
    cfg_path: Path,
    build_outputs_dir: Path,
    cpu_arch: str = "64bit",
    excluded_relpaths: set[str] | None = None,
) -> list[Path]:
    """Yield sorted relative paths inside `build_outputs_dir` matching `FILES.cfg` official rules."""
    if not build_outputs_dir.exists():
        raise FileNotFoundError(f"Build outputs directory missing: {build_outputs_dir}")

    excluded = {Path(p).as_posix() for p in (excluded_relpaths or set())}
    specs = parse_files_cfg(cfg_path)
    root = build_outputs_dir.resolve()
    matched: dict[str, Path] = {}

    for spec in specs:
        if "official" not in spec.get("buildtype", ()):
            continue
        arch_list = spec.get("arch")
        if arch_list is not None and cpu_arch not in arch_list:
            continue
        pattern = spec["filename"]
        for candidate in root.glob(pattern):
            if candidate.is_dir() or candidate.suffix.lower() == ".pdb":
                continue
            rel = candidate.relative_to(root)
            if rel.as_posix() in excluded:
                continue
            matched[rel.as_posix()] = rel

    return [matched[k] for k in sorted(matched)]


def create_portable_archive(
    relative_files: list[Path],
    build_outputs_dir: Path,
    output_archive: Path,
    archive_prefix: str = "",
    deterministic_timestamp: int | None = None,
) -> Path:
    """Package `relative_files` into a deterministic `.zip` or `.tar.{gz,bz2,xz}`."""
    output_archive.parent.mkdir(parents=True, exist_ok=True)
    root = build_outputs_dir.resolve()
    prefix = archive_prefix.strip("/")

    if output_archive.suffix.lower() == ".zip":
        import shutil

        clamped_ts = max(315532800, deterministic_timestamp) if deterministic_timestamp is not None else None
        zip_dt = time.gmtime(clamped_ts)[:6] if clamped_ts is not None else (2026, 1, 1, 0, 0, 0)
        with zipfile.ZipFile(output_archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for rel in relative_files:
                src = root / rel
                arcname = f"{prefix}/{rel.as_posix()}" if prefix else rel.as_posix()
                zinfo = zipfile.ZipInfo(filename=arcname, date_time=zip_dt)
                zinfo.compress_type = zipfile.ZIP_DEFLATED
                zinfo.external_attr = (src.stat().st_mode & 0xFFFF) << 16
                with src.open("rb") as src_fh, zf.open(zinfo, "w") as dst_fh:
                    shutil.copyfileobj(src_fh, dst_fh, length=1024 * 1024)
        return output_archive

    name = output_archive.name.lower()
    mode = (
        "w:xz"
        if name.endswith(".tar.xz")
        else "w:bz2"
        if name.endswith((".tar.bz2", ".tbz2"))
        else "w:gz"
        if name.endswith((".tar.gz", ".tgz"))
        else "w"
    )
    with tarfile.open(str(output_archive), mode) as tf:
        for rel in relative_files:
            src = root / rel
            arcname = f"{prefix}/{rel.as_posix()}" if prefix else rel.as_posix()
            tinfo = tf.gettarinfo(str(src), arcname=arcname)
            if deterministic_timestamp is not None:
                tinfo.mtime = deterministic_timestamp
            with src.open("rb") as handle:
                tf.addfile(tinfo, handle)
    return output_archive
