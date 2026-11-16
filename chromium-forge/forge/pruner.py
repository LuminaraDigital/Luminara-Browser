"""Clean-room OBL-02 implementation: Binary pruning & source-tree list scanner.

Fixes upstream bugs discovered via REA static analysis:
- Bug #1 (`utils/prune_binaries.py:196`): Uses `.as_posix()` when matching `KEEP_FILES` so Windows
  backslashes never delete required `.mojom`/`.tq`/`.html` files inside `CONTINGENT_PATHS`.
- Bug #2 (`utils/prune_binaries.py:230`): Checks `(source_tree / cpath).exists()` rather than CWD.
- Supports `idempotent=True` mode while preserving strict missing-file detection when `idempotent=False`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import stat

ENCODING = "utf-8"

# Preserved 1:1 from `utils/prune_binaries.py:155-162`
KEEP_FILES = frozenset(
    {
        "chrome/test/data/webui/i18n_process_css_test.html",
        "chrome/test/data/webui/mojo/foobar.mojom",
        "v8/test/torque/test-torque.tq",
    }
)
KEEP_SUFFIXES = (".gn", ".gni", ".grd", ".grdp", ".isolate", ".pydeps")

CONTINGENT_PATHS = (
    "apps/test/data",
    "ash/webui/projector_app/test",
    "base/tracing/test/data",
    "chrome/browser/autofill/automated_tests",
    "chrome/browser/load_library_perf_test.cc",
    "chrome/browser/media/router/providers/cast",
    "chrome/browser/resources/chromeos",
    "chrome/test/chromedriver/test",
    "chrome/test/data",
    "components/test/data",
    "content/test/data",
    "courgette/testdata",
    "extensions/common/api/declarative_net_request/flat",
    "media/test/data",
    "native_client_sdk",
    "net/data",
    "remoting",
    "testing/libfuzzer/fuzzers/wasm_corpus",
    "third_party/blink/perf_tests",
    "third_party/blink/web_tests",
    "third_party/catapult/tracing/test_data",
    "third_party/hunspell_dictionaries",
    "third_party/icu/source/data",
    "third_party/ots/test",
    "third_party/perfetto/test/data",
    "third_party/protobuf/benchmarks",
    "third_party/sqlite/src/test",
    "third_party/test_fonts",
    "tools/perf/page_sets",
    "ui/webui/resources/cr_components/help_bubble",
    "v8/test",
)

# Byte-translation table matching `devutils/update_lists.py:137`
_TEXT_BYTES = bytearray({7, 8, 9, 10, 12, 13, 27} | set(range(0x20, 0x100)) - {0x7F})

DOMAIN_INCLUDE_SUFFIXES = frozenset(
    {
        ".h", ".hh", ".hpp", ".hxx", ".cc", ".cpp", ".cxx", ".c", ".m", ".mm",
        ".idl", ".mojom", ".proto", ".gn", ".gni", ".grd", ".grdp", ".xtb",
        ".py", ".js", ".mjs", ".ts", ".mts", ".html", ".htm", ".css", ".json",
        ".xml", ".svg", ".policy", ".cnf", ".conf", ".cfg", ".ini", ".sh",
    }
)

DOMAIN_EXCLUDE_PREFIXES = (
    "components/url_formatter/spoof_checks/top_domains/",
    "net/http/transport_security_state_static",
    "third_party/search_engines_data/resources/definitions/prepopulated_engines.json",
    "tools/gn/",
    "tools/licenses/licenses.py",
)

PRUNING_SAFE_TEXT_SUFFIXES = DOMAIN_INCLUDE_SUFFIXES | {
    ".md", ".txt", ".rst", ".patch", ".diff", ".cmake", ".toml", ".yaml", ".yml",
}


def _force_writable_unlink(path: Path) -> None:
    try:
        path.unlink()
    except PermissionError:
        path.chmod(stat.S_IWRITE | stat.S_IREAD)
        path.unlink()


def _force_writable_rmdir(path: Path) -> None:
    try:
        path.rmdir()
    except PermissionError:
        path.chmod(stat.S_IWRITE | stat.S_IREAD)
        path.rmdir()
    except OSError:
        pass


def _cleanup_empty_ancestors(path: Path, stop_root: Path) -> None:
    parent = path.parent
    stop_resolved = stop_root.resolve()
    while parent.exists() and parent.resolve() != stop_resolved:
        try:
            next(parent.iterdir())
            break
        except StopIteration:
            _force_writable_rmdir(parent)
            parent = parent.parent


@dataclass
class PruneReport:
    removed_listed: int
    removed_contingent: int
    removed_pycache: int
    missing_files: list[str]


def prune_source_tree(
    source_tree: Path,
    pruning_entries: list[str],
    keep_contingent_paths: bool = False,
    idempotent: bool = False,
) -> PruneReport:
    """Remove `__pycache__`, contingent test/binary subtrees, and `pruning.list` entries."""
    if not source_tree.exists():
        raise FileNotFoundError(f"Source tree does not exist: {source_tree}")

    root = source_tree.resolve()
    removed_pycache = 0
    for pycache_file in list(root.rglob("__pycache__/*")):
        if pycache_file.is_file() or pycache_file.is_symlink():
            _force_writable_unlink(pycache_file)
            removed_pycache += 1
            _cleanup_empty_ancestors(pycache_file, root)

    removed_contingent = 0
    if not keep_contingent_paths:
        for rel_contingent in CONTINGENT_PATHS:
            target = root / Path(rel_contingent)
            if not target.exists() and not target.is_symlink():
                continue
            if target.is_file() or target.is_symlink():
                rel_posix = target.relative_to(root).as_posix()
                if rel_posix not in KEEP_FILES and not rel_posix.endswith(KEEP_SUFFIXES):
                    _force_writable_unlink(target)
                    removed_contingent += 1
                    _cleanup_empty_ancestors(target, root)
                continue

            # Walk bottom-up so empty directories collapse cleanly while keeping KEEP_FILES
            nodes = sorted(target.rglob("*"), key=lambda p: len(p.parts), reverse=True)
            for node in nodes:
                rel_posix = node.relative_to(root).as_posix()
                if node.is_dir() and not node.is_symlink():
                    _force_writable_rmdir(node)
                elif rel_posix not in KEEP_FILES and not rel_posix.endswith(KEEP_SUFFIXES):
                    _force_writable_unlink(node)
                    removed_contingent += 1
            _force_writable_rmdir(target)

    from .http_base import safe_join

    removed_listed = 0
    missing: list[str] = []
    for raw_line in pruning_entries:
        rel = raw_line.strip()
        if not rel:
            continue
        file_path = safe_join(root, rel)
        if file_path.exists() or file_path.is_symlink():
            _force_writable_unlink(file_path)
            removed_listed += 1
            _cleanup_empty_ancestors(file_path, root)
        elif not idempotent:
            missing.append(Path(rel).as_posix())

    return PruneReport(
        removed_listed=removed_listed,
        removed_contingent=removed_contingent,
        removed_pycache=removed_pycache,
        missing_files=missing,
    )


def is_binary_file(path: Path, sample_size: int = 8192) -> bool:
    """Detect binary files using the upstream non-text byte translation check."""
    with path.open("rb") as handle:
        chunk = handle.read(sample_size)
    if not chunk:
        return False
    return bool(chunk.translate(None, _TEXT_BYTES))


def scan_source_lists(
    source_tree: Path,
    combined_domain_regex,
) -> tuple[list[str], list[str]]:
    """Scan an unpatched source tree to generate `(pruning_list, domain_substitution_list)`."""
    root = source_tree.resolve()
    contingent_prefixes = tuple(f"{p}/" for p in CONTINGENT_PATHS)
    pruning_set: set[str] = set()
    domsub_set: set[str] = set()

    for node in root.rglob("*"):
        if node.is_dir() or node.is_symlink():
            continue
        rel_posix = node.relative_to(root).as_posix()
        if rel_posix in CONTINGENT_PATHS or rel_posix.startswith(contingent_prefixes):
            continue
        if "/__pycache__/" in f"/{rel_posix}" or rel_posix.startswith(".git/"):
            continue

        suffix = node.suffix.lower()
        if suffix not in PRUNING_SAFE_TEXT_SUFFIXES and is_binary_file(node):
            pruning_set.add(rel_posix)
            continue

        if node.name.startswith("LICENSE") or rel_posix.startswith(DOMAIN_EXCLUDE_PREFIXES):
            continue
        if suffix in DOMAIN_INCLUDE_SUFFIXES:
            raw = node.read_bytes()
            text = None
            for enc in ("utf-8", "iso-8859-1"):
                try:
                    text = raw.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue
            if text and combined_domain_regex.search(text):
                domsub_set.add(rel_posix)

    return sorted(pruning_set), sorted(domsub_set)
