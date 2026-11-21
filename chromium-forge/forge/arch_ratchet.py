"""Clean-room Architecture Pattern Ratchet & Dead-Symbol Gate (`forge/arch_ratchet.py`).

Synthesizes two Perplexity AI engineering systems into pure Python stdlib:
1. `perplexityai/SPACE` (`ARCHITECTURE.toml` / `cargo arch` pattern ratchet):
   - Enforces the strict `< 1,000`-line file ceiling across all `forge/*.py`, `forge/ui/*.html`,
     and `cloudflare/` sources.
   - Enforces `pyproject.toml` `dependencies = []` and verifies zero non-stdlib runtime imports.
   - Enforces clean layer boundaries (L10 foundation modules `models`, `luminara_crypto`,
     `http_base`, `action_ledger` never import L50 server/UI modules).
   - Enforces zero dynamic `.innerHTML` assignment across generated browser surfaces.
2. `perplexityai/codescythe` (`ARCHITECTURE.md` two-set dead-code analyzer):
   - Set 1 (`file_reachability`): BFS import graph from configured entry modules across
     `forge/*.py` and `tests/test_*.py` to guarantee zero unreachable dead Python modules.
   - Set 2 (`export_usage`): Tracks top-level exported classes/functions in `forge/*.py` against
     cross-module AST references with a ratcheted zero-growth cap (`no_raised_caps`).
"""

from __future__ import annotations

import ast
from collections import deque
from pathlib import Path
import re
import sys
import tomllib
from typing import Any

ENCODING = "utf-8"
MAX_FILE_LINES = 1000

L10_FOUNDATION_MODULES = frozenset({"models", "luminara_crypto", "http_base", "action_ledger"})
L10_ALLOWED_DEPS = L10_FOUNDATION_MODULES | {"luminara_security"}

STDLIB_MODULE_NAMES: frozenset[str] = frozenset(sys.stdlib_module_names) | frozenset({"forge", "__future__"})

_INNER_HTML_ASSIGN_RE = re.compile(r"\.innerHTML\s*=")


def _count_lines(path: Path) -> int:
    text = path.read_text(encoding=ENCODING, errors="replace")
    return len(text.splitlines())


def _resolve_forge_import(current_mod: str, node: ast.AST, known_mods: set[str]) -> set[str]:
    targets: set[str] = set()
    if isinstance(node, ast.Import):
        for alias in node.names:
            parts = alias.name.split(".")
            if parts[0] == "forge" and len(parts) >= 2 and parts[1] in known_mods:
                targets.add(parts[1])
    elif isinstance(node, ast.ImportFrom):
        mod = node.module or ""
        if node.level >= 1:
            if mod and mod.split(".")[0] in known_mods:
                targets.add(mod.split(".")[0])
            else:
                for alias in node.names:
                    if alias.name in known_mods:
                        targets.add(alias.name)
        elif mod == "forge":
            for alias in node.names:
                if alias.name in known_mods:
                    targets.add(alias.name)
        elif mod.startswith("forge."):
            sub = mod.split(".")[1]
            if sub in known_mods:
                targets.add(sub)
    targets.discard(current_mod)
    return targets


def _extract_external_roots(tree: ast.AST) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def _extract_module_exports(tree: ast.Module) -> set[str]:
    explicit_all: set[str] | None = None
    defined: set[str] = set()
    for stmt in tree.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not stmt.name.startswith("_"):
                defined.add(stmt.name)
        elif isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                if isinstance(target, ast.Name):
                    if target.id == "__all__" and isinstance(stmt.value, (ast.List, ast.Tuple, ast.Set)):
                        explicit_all = {
                            elt.value
                            for elt in stmt.value.elts
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                        }
                    elif not target.id.startswith("_") and target.id.isupper():
                        defined.add(target.id)
    return explicit_all if explicit_all is not None else defined


def _collect_identifier_references(tree: ast.AST) -> set[str]:
    refs: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            refs.add(node.id)
        elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
            refs.add(node.attr)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                refs.add(alias.name)
    return refs


def _audit_cloudflare_tree(repo_root: Path) -> list[str]:
    """Verify JS/HTML file reachability across `cloudflare/` from `wrangler.toml` entrypoints."""
    cf_dir = repo_root / "cloudflare"
    wrangler_path = repo_root / "wrangler.toml"
    if not cf_dir.is_dir() or not wrangler_path.is_file():
        return []
    w_cfg = tomllib.loads(wrangler_path.read_text(encoding=ENCODING))
    all_cf = {
        p.resolve().relative_to(repo_root.resolve()).as_posix(): p.resolve()
        for ext in ("*.js", "*.html")
        for p in cf_dir.rglob(ext)
    }
    reachable: set[str] = set()
    q: deque[Path] = deque()
    main_rel = str(w_cfg.get("main") or "").strip().lstrip("./")
    if main_rel in all_cf:
        reachable.add(main_rel)
        q.append(all_cf[main_rel])
    assets_dir = str((w_cfg.get("assets") or {}).get("directory") or "").strip().lstrip("./")
    pub_index = f"{assets_dir}/index.html" if assets_dir else "cloudflare/public/index.html"
    if pub_index in all_cf:
        reachable.add(pub_index)
        q.append(all_cf[pub_index])

    ref_re = re.compile(r"""(?:from\s+|import\s+|src=)["']([^"']+\.(?:js|html))["']""")
    while q:
        cur = q.popleft()
        txt = cur.read_text(encoding=ENCODING, errors="replace")
        for m in ref_re.finditer(txt):
            raw_ref = m.group(1).split("?", 1)[0].split("#", 1)[0]
            cand = ((repo_root / assets_dir / raw_ref.lstrip("/")) if raw_ref.startswith("/") else (cur.parent / raw_ref)).resolve()
            if cand.is_relative_to(repo_root.resolve()):
                rel = cand.relative_to(repo_root.resolve()).as_posix()
                if rel in all_cf and rel not in reachable:
                    reachable.add(rel)
                    q.append(all_cf[rel])
    return sorted(set(all_cf.keys()) - reachable)


def run_architecture_ratchet(
    forge_root: Path,
    *,
    max_lines: int = MAX_FILE_LINES,
    max_unreferenced_exports_cap: int = 2,
) -> dict[str, Any]:
    """Execute SPACE pattern-ratchet + Codescythe two-set reachability analysis."""
    resolved_forge = forge_root.resolve()
    repo_root = resolved_forge.parent
    pkg_dir = (resolved_forge / "forge") if (resolved_forge / "forge").is_dir() else Path(__file__).resolve().parent
    tests_dir = resolved_forge / "tests"
    cf_dir = repo_root / "cloudflare"
    pyproject_path = repo_root / "pyproject.toml"

    line_violations: list[dict[str, Any]] = []
    xss_violations: list[str] = []
    scan_files: list[Path] = sorted(pkg_dir.glob("*.py"))
    html_js_surfaces: list[Path] = []
    if (pkg_dir / "ui").is_dir():
        ui_html = sorted((pkg_dir / "ui").glob("*.html"))
        scan_files.extend(ui_html)
        html_js_surfaces.extend(ui_html)
    if cf_dir.is_dir():
        for ext in ("*.js", "*.html"):
            found_cf = sorted(cf_dir.rglob(ext))
            scan_files.extend(found_cf)
            html_js_surfaces.extend(found_cf)

    for surf in html_js_surfaces:
        if _INNER_HTML_ASSIGN_RE.search(surf.read_text(encoding=ENCODING, errors="replace")):
            rel_s = surf.relative_to(repo_root).as_posix() if surf.is_relative_to(repo_root) else surf.name
            xss_violations.append(rel_s)

    max_observed_lines = 0
    largest_file = ""
    for fpath in scan_files:
        lc = _count_lines(fpath)
        rel = fpath.relative_to(repo_root).as_posix() if fpath.is_relative_to(repo_root) else fpath.name
        if lc > max_observed_lines:
            max_observed_lines = lc
            largest_file = rel
        if lc > max_lines:
            line_violations.append({"file": rel, "lines": lc, "ceiling": max_lines})

    # 1. pyproject.toml dependencies = [] purity check
    declared_deps: list[str] = []
    if pyproject_path.is_file():
        py_cfg = tomllib.loads(pyproject_path.read_text(encoding=ENCODING))
        declared_deps = list((py_cfg.get("project") or {}).get("dependencies") or [])

    # 2. Parse all forge/*.py ASTs + build import graph + check stdlib & layer boundaries
    py_files = {p.stem: p for p in sorted(pkg_dir.glob("*.py"))}
    known_mods = set(py_files.keys())
    ast_map: dict[str, ast.Module] = {}
    import_edges: dict[str, set[str]] = {}
    non_stdlib_imports: list[dict[str, Any]] = []
    layer_violations: list[dict[str, str]] = []

    for mod_name, fpath in py_files.items():
        src = fpath.read_text(encoding=ENCODING)
        if mod_name in ("luminara_ui", "luminara_workspace_ui", "luminara_telemetry_ui", "luminara_copilot_ext"):
            if _INNER_HTML_ASSIGN_RE.search(src):
                xss_violations.append(f"forge/{fpath.name}")
        tree = ast.parse(src, filename=str(fpath))
        ast_map[mod_name] = tree
        edges: set[str] = set()
        for node in ast.walk(tree):
            edges |= _resolve_forge_import(mod_name, node, known_mods)
        import_edges[mod_name] = edges

        ext_roots = _extract_external_roots(tree) - STDLIB_MODULE_NAMES - known_mods
        if ext_roots:
            non_stdlib_imports.append({"module": mod_name, "imports": sorted(ext_roots)})

        if mod_name in L10_FOUNDATION_MODULES:
            forbidden = sorted(edges - L10_ALLOWED_DEPS)
            for bad in forbidden:
                layer_violations.append(
                    {
                        "from_l10": mod_name,
                        "to_upper": bad,
                        "rule": "SPACE L10_foundation -> upper-layer dependency prohibited",
                    }
                )

    # 3. Codescythe Set 1: File Reachability BFS from entrypoints (`__init__`, `__main__`, `cli`) + test suite + cloudflare
    entry_seeds: set[str] = {"__init__", "__main__", "cli"} & known_mods
    test_refs: set[str] = set()
    if tests_dir.is_dir():
        for tf in sorted(tests_dir.glob("test_*.py")):
            ttree = ast.parse(tf.read_text(encoding=ENCODING), filename=str(tf))
            for node in ast.walk(ttree):
                entry_seeds |= _resolve_forge_import("__test__", node, known_mods)
            test_refs |= _collect_identifier_references(ttree)

    reachable_mods: set[str] = set(entry_seeds)
    queue: deque[str] = deque(sorted(entry_seeds))
    while queue:
        cur = queue.popleft()
        for nxt in sorted(import_edges.get(cur, ())):
            if nxt not in reachable_mods:
                reachable_mods.add(nxt)
                queue.append(nxt)

    unreachable_files = sorted(known_mods - reachable_mods) + _audit_cloudflare_tree(repo_root)

    # 4. Codescythe Set 2: Export Usage across reachable modules + tests
    global_refs: set[str] = set(test_refs)
    per_mod_exports: dict[str, set[str]] = {}
    for mod_name in reachable_mods:
        tree = ast_map[mod_name]
        per_mod_exports[mod_name] = _extract_module_exports(tree)
        global_refs |= _collect_identifier_references(tree)

    unreferenced_exports: list[str] = []
    for mod_name, exports in sorted(per_mod_exports.items()):
        if mod_name in ("__init__", "__main__"):
            continue
        for sym in sorted(exports):
            if sym not in global_refs:
                unreferenced_exports.append(f"forge.{mod_name}:{sym}")

    ok = (
        bool(py_files)
        and not line_violations
        and not declared_deps
        and not non_stdlib_imports
        and not layer_violations
        and not xss_violations
        and not unreachable_files
        and len(unreferenced_exports) <= max_unreferenced_exports_cap
    )
    return {
        "ok": ok,
        "ceiling_lines": max_lines,
        "max_observed_lines": max_observed_lines,
        "largest_file": largest_file,
        "scanned_file_count": len(scan_files),
        "forge_module_count": len(known_mods),
        "reachable_module_count": len(reachable_mods),
        "unreachable_files": unreachable_files,
        "unreferenced_exports": unreferenced_exports,
        "unreferenced_exports_cap": max_unreferenced_exports_cap,
        "declared_runtime_dependencies": declared_deps,
        "non_stdlib_imports": non_stdlib_imports,
        "layer_violations": layer_violations,
        "xss_violations": xss_violations,
        "line_violations": line_violations,
    }
