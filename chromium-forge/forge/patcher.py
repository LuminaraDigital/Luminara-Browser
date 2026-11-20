"""Clean-room OBL-03 implementation: Quilt series parser, unified diff validator, applier & merger.

Fixes upstream bugs & limitations discovered via REA static analysis:
- Bug #6 (`devutils/check_patch_files.py:89`): Normalizes all patch paths with `.as_posix()` so
  Windows hosts do not report 108 false-positive "unused patch" errors.
- Parses `#` comments even when indented with leading whitespace (`line.strip().startswith('#')`).
- Provides BOTH external GNU `patch` (`C:\\Program Files\\Git\\usr\\bin\\patch.exe`) execution AND a
  zero-dependency pure-Python zero-fuzz unified diff applier + reverser + in-memory simulator.
- Exposes `reverse=True` (`revert`) directly, which upstream `utils/patches.py` implemented in library
  code (`line 106`) but omitted from its CLI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import re
import shutil
import subprocess

ENCODING = "utf-8"
_HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@dataclass
class DiffHunk:
    orig_start: int
    orig_count: int
    new_start: int
    new_count: int
    lines: list[str]  # Raw hunk body lines starting with ' ', '+', or '-'


@dataclass
class FilePatch:
    orig_path: str  # POSIX path stripped of a/ or /dev/null
    new_path: str   # POSIX path stripped of b/ or /dev/null
    hunks: list[DiffHunk] = field(default_factory=list)

    @property
    def is_added(self) -> bool:
        return self.orig_path == "/dev/null"

    @property
    def is_deleted(self) -> bool:
        return self.new_path == "/dev/null"

    @property
    def target_relpath(self) -> str:
        return self.orig_path if self.is_deleted else self.new_path


def _strip_p1(header_token: str) -> str:
    token = header_token.split("\t", 1)[0].strip()
    if token == "/dev/null":
        return "/dev/null"
    if token.startswith(("a/", "b/")):
        return token[2:]
    parts = token.replace("\\", "/").split("/", 1)
    return parts[1] if len(parts) == 2 else parts[0]


def parse_unified_diff(patch_text: str, source_name: str = "<patch>") -> list[FilePatch]:
    """Parse a `-p1` unified diff and strictly verify hunk line counts (zero malformed hunks)."""
    raw_lines = patch_text.splitlines()
    file_patches: list[FilePatch] = []
    idx = 0
    total = len(raw_lines)

    while idx < total:
        line = raw_lines[idx]
        if line.startswith("--- ") and (idx + 1 < total) and raw_lines[idx + 1].startswith("+++ "):
            orig_p = _strip_p1(line[4:])
            new_p = _strip_p1(raw_lines[idx + 1][4:])
            fp = FilePatch(orig_path=orig_p, new_path=new_p)
            idx += 2
            while idx < total and raw_lines[idx].startswith("@@ "):
                match = _HUNK_HEADER_RE.match(raw_lines[idx])
                if not match:
                    raise ValueError(f"{source_name}:{idx + 1}: Malformed hunk header: {raw_lines[idx]!r}")
                o_start = int(match.group(1))
                o_count = int(match.group(2)) if match.group(2) is not None else 1
                n_start = int(match.group(3))
                n_count = int(match.group(4)) if match.group(4) is not None else 1
                idx += 1

                body: list[str] = []
                seen_orig = 0
                seen_new = 0
                while idx < total and (seen_orig < o_count or seen_new < n_count):
                    hline = raw_lines[idx]
                    if hline.startswith("\\ No newline at end of file"):
                        idx += 1
                        continue
                    if hline == "":
                        # Empty context line lacking leading space in stripped editors
                        body.append(" ")
                        seen_orig += 1
                        seen_new += 1
                    elif hline[0] == " ":
                        body.append(hline)
                        seen_orig += 1
                        seen_new += 1
                    elif hline[0] == "-":
                        body.append(hline)
                        seen_orig += 1
                    elif hline[0] == "+":
                        body.append(hline)
                        seen_new += 1
                    else:
                        break
                    idx += 1
                if idx < total and raw_lines[idx].startswith("\\ No newline at end of file"):
                    idx += 1
                if seen_orig != o_count or seen_new != n_count:
                    raise ValueError(
                        f"{source_name}: Hunk line-count mismatch in {fp.target_relpath} "
                        f"(expected -{o_count}/+{n_count}, got -{seen_orig}/+{seen_new})"
                    )
                fp.hunks.append(DiffHunk(o_start, o_count, n_start, n_count, body))
            if not fp.hunks:
                raise ValueError(f"{source_name}: File header for {fp.target_relpath} has zero hunks")
            file_patches.append(fp)
        else:
            idx += 1

    if not file_patches:
        raise ValueError(f"{source_name}: Contains zero unified diff file entries")
    return file_patches


def parse_series_file(series_path: Path) -> list[str]:
    """Parse a GNU Quilt `series` file into clean POSIX relative patch paths."""
    if not series_path.exists():
        raise FileNotFoundError(f"Missing series file: {series_path}")
    entries: list[str] = []
    for raw in series_path.read_text(encoding=ENCODING).splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        patch_rel = stripped.split(" #", 1)[0].strip().replace("\\", "/")
        if patch_rel:
            entries.append(patch_rel)
    return entries


@dataclass
class PatchAuditReport:
    total_series_entries: int
    parsed_files_count: int
    total_hunks_count: int
    duplicates: list[str]
    missing_patches: list[str]
    unused_patches: list[str]
    parse_errors: list[str]

    @property
    def ok(self) -> bool:
        return not (self.duplicates or self.missing_patches or self.unused_patches or self.parse_errors)


def audit_patch_directory(patches_dir: Path) -> PatchAuditReport:
    """Validate `patches/series`, hunk counts, duplicates, and orphaned `.patch` files (Windows-safe)."""
    series_entries = parse_series_file(patches_dir / "series")
    seen: set[str] = set()
    duplicates: list[str] = []
    for entry in series_entries:
        if entry in seen:
            duplicates.append(entry)
        seen.add(entry)

    missing: list[str] = []
    parse_errors: list[str] = []
    parsed_files_count = 0
    total_hunks = 0

    for entry in series_entries:
        pfile = patches_dir / Path(entry)
        if not pfile.exists():
            missing.append(entry)
            continue
        try:
            text = pfile.read_text(encoding=ENCODING)
            fpatches = parse_unified_diff(text, source_name=entry)
            parsed_files_count += len(fpatches)
            total_hunks += sum(len(fp.hunks) for fp in fpatches)
        except Exception as exc:  # noqa: BLE001
            parse_errors.append(f"{entry}: {exc}")

    on_disk: set[str] = set()
    for node in patches_dir.rglob("*"):
        if node.is_dir():
            continue
        rel_posix = node.relative_to(patches_dir).as_posix()
        if rel_posix == "series" or node.suffix.lower() == ".md":
            continue
        on_disk.add(rel_posix)

    unused = sorted(on_disk - seen)
    return PatchAuditReport(
        total_series_entries=len(series_entries),
        parsed_files_count=parsed_files_count,
        total_hunks_count=total_hunks,
        duplicates=duplicates,
        missing_patches=missing,
        unused_patches=unused,
        parse_errors=parse_errors,
    )


def find_patch_binary(explicit_path: Path | None = None) -> str | None:
    """Locate modern GNU `patch` (preferring Git for Windows `usr/bin/patch.exe` over broken Strawberry Perl `patch.exe` 2.5.9)."""
    if explicit_path is not None and explicit_path.exists():
        return str(explicit_path)
    env_bin = os.environ.get("PATCH_BIN")
    if env_bin and (Path(env_bin).exists() or shutil.which(env_bin)):
        return env_bin
    if os.name == "nt":
        git_bin = shutil.which("git")
        if git_bin:
            git_root = Path(git_bin).resolve().parent.parent
            candidate = git_root / "usr" / "bin" / "patch.exe"
            if candidate.exists():
                return str(candidate)
        win_git_patch = Path(r"C:\Program Files\Git\usr\bin\patch.exe")
        if win_git_patch.exists():
            return str(win_git_patch)
    on_path = shutil.which("patch")
    if on_path and "strawberry" not in on_path.lower():
        return on_path
    return None


def apply_patch_in_memory(
    files_map: dict[str, list[str]],
    patch_text: str,
    reverse: bool = False,
    source_name: str = "<patch>",
) -> None:
    """Zero-fuzz unified diff applier/reverser operating on in-memory line lists."""
    fpatches = parse_unified_diff(patch_text, source_name=source_name)
    if reverse:
        fpatches = list(reversed(fpatches))

    for fp in fpatches:
        adding = fp.is_deleted if reverse else fp.is_added
        deleting = fp.is_added if reverse else fp.is_deleted
        rel = fp.target_relpath

        if adding:
            if rel in files_map:
                raise RuntimeError(f"{source_name}: Cannot create already-existing file {rel}")
            new_lines: list[str] = []
            for hunk in fp.hunks:
                for hline in hunk.lines:
                    tag, payload = hline[0], hline[1:]
                    if (not reverse and tag in ("+", " ")) or (reverse and tag in ("-", " ")):
                        new_lines.append(payload)
            files_map[rel] = new_lines
            continue

        if rel not in files_map:
            raise FileNotFoundError(f"{source_name}: Target file missing for patch: {rel}")

        current = list(files_map[rel])
        if deleting:
            del files_map[rel]
            continue

        offset = 0
        for hunk in fp.hunks:
            start_line = (hunk.new_start if reverse else hunk.orig_start) - 1 + offset
            cursor = start_line
            replacement: list[str] = []
            for hline in hunk.lines:
                tag, payload = hline[0], hline[1:]
                expect_match = tag in (" ", "+" if reverse else "-")
                emit_line = tag in (" ", "-" if reverse else "+")
                if expect_match:
                    if cursor < 0 or cursor >= len(current) or current[cursor] != payload:
                        actual = current[cursor] if 0 <= cursor < len(current) else "<EOF>"
                        raise RuntimeError(
                            f"{source_name}: Zero-fuzz mismatch in {rel} at line {cursor + 1}: "
                            f"expected {payload!r}, found {actual!r}"
                        )
                    cursor += 1
                if emit_line:
                    replacement.append(payload)
            orig_span = cursor - start_line
            current[start_line:cursor] = replacement
            offset += len(replacement) - orig_span

        files_map[rel] = current


def apply_patch_series(
    source_tree: Path,
    patches_dirs: list[Path],
    reverse: bool = False,
    prefer_python_engine: bool = False,
    patch_bin: Path | None = None,
) -> int:
    """Apply or revert one or more Quilt `patches/` directories against `source_tree`."""
    ordered_patch_files: list[tuple[str, Path]] = []
    for pdir in patches_dirs:
        for rel in parse_series_file(pdir / "series"):
            ordered_patch_files.append((rel, (pdir / Path(rel)).resolve()))

    if reverse:
        ordered_patch_files.reverse()

    resolved_bin = None if prefer_python_engine else find_patch_binary(patch_bin)
    if resolved_bin:
        flag = "--reverse" if reverse else "--forward"
        for _rel, ppath in ordered_patch_files:
            cmd = [
                resolved_bin,
                "-p1",
                "--ignore-whitespace",
                "-i",
                str(ppath),
                "-d",
                str(source_tree),
                "--no-backup-if-mismatch",
                flag,
            ]
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return len(ordered_patch_files)

    # Pure-Python deterministic fallback (works even on minimal hosts without GNU patch)
    from .http_base import safe_join

    root = source_tree.resolve()
    for rel_name, ppath in ordered_patch_files:
        patch_text = ppath.read_text(encoding=ENCODING)
        fpatches = parse_unified_diff(patch_text, source_name=rel_name)
        touched_rels = {fp.target_relpath for fp in fpatches}
        files_map: dict[str, list[str]] = {}
        line_endings: dict[str, str] = {}

        for trel in touched_rels:
            disk_path = safe_join(root, trel)
            if disk_path.exists():
                raw = disk_path.read_bytes()
                line_endings[trel] = "\r\n" if b"\r\n" in raw else "\n"
                files_map[trel] = raw.decode(ENCODING).splitlines()

        apply_patch_in_memory(files_map, patch_text, reverse=reverse, source_name=rel_name)

        for trel in touched_rels:
            disk_path = safe_join(root, trel)
            if trel not in files_map:
                disk_path.unlink(missing_ok=True)
            else:
                eol = line_endings.get(trel, "\n")
                disk_path.parent.mkdir(parents=True, exist_ok=True)
                content = eol.join(files_map[trel]) + (eol if files_map[trel] else "")
                disk_path.write_bytes(content.encode(ENCODING))

    return len(ordered_patch_files)


def merge_patch_directories(destination: Path, sources: list[Path], prepend: bool = False) -> int:
    """Merge multiple Quilt `patches/` directories while preventing relative path collisions."""
    from .http_base import safe_join

    existing_entries: list[str] = []
    if destination.exists():
        if not prepend:
            raise FileExistsError(f"Destination patch directory already exists: {destination}")
        existing_entries = parse_series_file(destination / "series")

    merged_entries: list[str] = []
    seen = set(existing_entries)
    for src in sources:
        for rel in parse_series_file(src / "series"):
            if rel in seen:
                raise FileExistsError(f"Conflicting patch relative path during merge: {rel}")
            seen.add(rel)
            merged_entries.append(rel)
            target_file = safe_join(destination, rel)
            target_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(safe_join(src, rel), target_file)

    final_series = merged_entries + existing_entries
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "series").write_text("\n".join(final_series) + "\n", encoding=ENCODING, newline="\n")
    return len(final_series)
