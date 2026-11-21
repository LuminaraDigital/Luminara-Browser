"""REA v6.5.0 Perplexity Suite Harvester & Deterministic Evidence Ledger (`forge/rea_harvester.py`).

Executes `rea-agents@6.5.0` CLI operations (`import-reference-source`, `inspect-go-binary`,
`inspect-rust-binary`, `inspect-pe-resources`, `inspect-binary-layout`, `inspect-artifact`,
and `analyze-javascript-application`) against the 7 staged `perplexityai/*` targets in
`_rea_targets/perplexity/` without polluting git tracking or runtime Python dependencies.

Maintains strict REA epistemic separation (`observed`, `derived`, `inferred`, `unknown`) and
writes a compact, secret-scrubbed summary to `chromium-forge/rea_perplexity_evidence.json`.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import time
from typing import Any
import zipfile

from .luminara_security import DEFAULT_REDACTOR

ENCODING = "utf-8"
REA_PACKAGE_SPEC = "rea-agents@6.5.0"

PERPLEXITY_TARGETS: tuple[dict[str, Any], ...] = (
    {
        "repo": "perplexityai/SPACE",
        "slug": "SPACE",
        "obligation_id": "OBL-16",
        "route": "source_control_plane_and_nextjs_ui",
        "js_subpath": "ui",
        "js_source_paths": ["package.json", "next.config.js"],
        "key_anchors": ["ARCHITECTURE.toml", "Cargo.toml", "crates/l20_domain/state/reconciliation"],
    },
    {
        "repo": "perplexityai/codescythe",
        "slug": "codescythe",
        "obligation_id": "OBL-17",
        "route": "rust_napi_binary_and_js_wrapper",
        "js_subpath": "packages/codescythe",
        "js_source_paths": ["package.json", "index.ts", "bin/codescythe.ts"],
        "release_pe": "codescythe-windows-amd64.exe",
        "release_elf": "codescythe-linux-amd64",
        "key_anchors": ["ARCHITECTURE.md", "codescythe.schema.json", "crates/codescythe"],
    },
    {
        "repo": "perplexityai/numbat",
        "slug": "numbat",
        "obligation_id": "OBL-15",
        "route": "go_binary_and_sequence_casebundle_engine",
        "release_archive": "numbat_0.3.0_windows_amd64.zip",
        "release_pe": "numbat_win64/numbat.exe",
        "release_elf": "numbat_linux64/numbat",
        "key_anchors": ["go.mod", "internal/sequence/sequence.go", "internal/casebundle/build.go", "rules"],
    },
    {
        "repo": "perplexityai/rules_web_e2e",
        "slug": "rules_web_e2e",
        "obligation_id": "OBL-18",
        "route": "typescript_graph_and_release_tarball",
        "js_subpath": ".",
        "js_source_paths": [
            "package.json",
            "runtime/visuals.ts",
            "runtime/isolation.ts",
            "runtime/declared-inputs-hook.ts",
            "worker/supervisor.ts",
        ],
        "release_archive": "rules_web_e2e-v3.10.2.tar.gz",
        "key_anchors": ["MODULE.bazel", "runtime/visuals.ts", "runtime/isolation.ts", "worker/supervisor.ts"],
    },
    {
        "repo": "perplexityai/perplexity-py",
        "slug": "perplexity-py",
        "obligation_id": "OBL-19",
        "route": "stainless_sdk_wire_contract",
        "key_anchors": [".stats.yml", "api.md", "src/perplexity/resources/browser/sessions.py", "src/perplexity/resources/skills/skills.py"],
    },
    {
        "repo": "perplexityai/search_evals",
        "slug": "search_evals",
        "obligation_id": "OBL-20",
        "route": "eval_control_plane_and_cost_ledger",
        "key_anchors": ["systems.toml", "search_evals/costs.py", "search_evals/runner.py", "search_evals/suites/graders.py"],
    },
    {
        "repo": "perplexityai/pplx-kernels",
        "slug": "pplx-kernels",
        "obligation_id": "OBL-21",
        "route": "cuda_nvshmem_all_to_all_topology",
        "key_anchors": ["src/pplx_kernels/all_to_all.py", "csrc/all_to_all/intranode_dispatch.cu", "csrc/all_to_all/internode_dispatch.cu", "csrc/core/atomic.cuh"],
    },
)


def resolve_rea_launcher() -> list[str] | None:
    """Locate a cached `rea` v6.5.0 binary or fall back to `npx -y rea-agents@6.5.0`."""
    direct = shutil.which("rea")
    if direct:
        return [direct]
    local_app = os.environ.get("LOCALAPPDATA") or ""
    if local_app:
        npx_root = Path(local_app) / "npm-cache" / "_npx"
        if npx_root.is_dir():
            ext = "rea.cmd" if os.name == "nt" else "rea"
            for candidate in sorted(npx_root.glob(f"*/node_modules/.bin/{ext}")):
                pkg_json = candidate.parent.parent / "rea-agents" / "package.json"
                if candidate.is_file() and pkg_json.is_file():
                    try:
                        if json.loads(pkg_json.read_text(encoding=ENCODING)).get("version") == "6.5.0":
                            return [str(candidate)]
                    except Exception:  # noqa: BLE001
                        continue
    npx = shutil.which("npx.cmd" if os.name == "nt" else "npx") or shutil.which("npx")
    if npx:
        return [npx, "-y", REA_PACKAGE_SPEC]
    return None


def _run_rea_json(
    launcher: list[str],
    args: list[str],
    *,
    reference_roots: list[str] | None = None,
    timeout: float = 90.0,
) -> tuple[bool, dict[str, Any]]:
    """Invoke REA CLI with `REA_REFERENCE_ROOTS_JSON` and strict stdout/stderr separation."""
    cmd = [*launcher, *args, "--format", "json"]
    env = dict(os.environ)
    if reference_roots:
        env["REA_REFERENCE_ROOTS_JSON"] = json.dumps(reference_roots)
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            text=True,
            encoding=ENCODING,
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, {"code": "EXEC_ERROR", "message": str(exc)}

    raw = (proc.stdout or "").strip()
    if not raw:
        return False, {"code": f"EXIT_{proc.returncode}", "message": (proc.stderr or "").strip()[:400]}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        lines = [ln.strip() for ln in raw.splitlines() if ln.strip().startswith("{")]
        if not lines:
            return False, {"code": "INVALID_JSON", "message": raw[:300]}
        parsed = json.loads(lines[-1])
    if not isinstance(parsed, dict):
        return False, {"value": parsed}
    has_ev = bool(parsed.get("evidence_id"))
    has_ref_summary = proc.returncode == 0 and (
        parsed.get("schema") in ("HistoricalSourceSummary", "HistoricalSourceGraph")
        or isinstance(parsed.get("manifest"), dict)
    )
    return (has_ev or has_ref_summary), parsed


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(65536):
            h.update(chunk)
    return h.hexdigest()


def _rel_display(path: Path, base: Path) -> str:
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return path.name


def harvest_perplexity_rea_evidence(
    forge_root: Path,
    *,
    staging_root: Path | None = None,
    write_committed_summary: bool = True,
) -> dict[str, Any]:
    """Run REA v6.5.0 forensic & source-reference probes across all 7 Perplexity AI targets."""
    started = time.time()
    repo_root = forge_root.parent
    stg = (staging_root or (repo_root / "_rea_targets" / "perplexity")).resolve()
    releases_dir = stg / "_releases"
    raw_out_dir = forge_root / "outputs" / "rea_perplexity"
    raw_out_dir.mkdir(parents=True, exist_ok=True)
    summary_path = forge_root / "rea_perplexity_evidence.json"
    pkg_summary_path = Path(__file__).resolve().parent / "rea_evidence" / "rea_perplexity_evidence.json"

    if not stg.is_dir():
        for cand_summary in (summary_path, pkg_summary_path):
            if cand_summary.is_file():
                cached = json.loads(cand_summary.read_text(encoding=ENCODING))
                cached["source_mode"] = "committed_evidence_snapshot"
                return cached

    launcher = resolve_rea_launcher()
    ref_roots = [str(stg)]
    host_platform = f"{platform.system().lower()}-{platform.machine().lower()}"
    target_records: list[dict[str, Any]] = []
    residual_unknowns: list[dict[str, Any]] = []

    for spec in PERPLEXITY_TARGETS:
        slug = spec["slug"]
        repo_dir = stg / slug
        entry: dict[str, Any] = {
            "repo": spec["repo"],
            "slug": slug,
            "obligation_id": spec["obligation_id"],
            "route": spec["route"],
            "present": repo_dir.is_dir(),
            "observed_anchors": {},
            "rea_evidence": [],
        }
        if repo_dir.is_dir():
            for anchor in spec["key_anchors"]:
                ap = repo_dir / anchor
                if ap.is_file():
                    entry["observed_anchors"][anchor] = {
                        "kind": "file",
                        "bytes": ap.stat().st_size,
                        "sha256": _sha256_file(ap),
                    }
                elif ap.is_dir():
                    file_count = sum(1 for p in ap.rglob("*") if p.is_file())
                    entry["observed_anchors"][anchor] = {"kind": "directory", "file_count": file_count}

        if launcher and repo_dir.is_dir():
            ok_ref, ref_ev = _run_rea_json(
                launcher,
                ["import-reference-source", str(repo_dir), "--detail", "summary", "--outline-depth", "2"],
                reference_roots=ref_roots,
                timeout=60.0,
            )
            if ok_ref:
                (raw_out_dir / f"{slug}_ref_source.json").write_text(json.dumps(ref_ev), encoding=ENCODING)
                norm = ref_ev.get("normalized_result") or {}
                manifest_obj = ref_ev.get("manifest") if isinstance(ref_ev.get("manifest"), dict) else {}
                ev_id = str(
                    ref_ev.get("evidence_id")
                    or manifest_obj.get("manifest_id")
                    or manifest_obj.get("tree_sha256")
                    or f"ref_manifest_{slug}"
                )
                entry["rea_evidence"].append(
                    {
                        "operation": "import_reference_source",
                        "evidence_id": ev_id,
                        "confidence": ref_ev.get("confidence", "observed"),
                        "authority": ref_ev.get("authority", "historical-reference"),
                        "file_count": ref_ev.get("entry_count") or norm.get("file_count") or norm.get("total_files"),
                    }
                )
            else:
                residual_unknowns.append(
                    {
                        "id": f"RU-REF-{slug.upper()}",
                        "target": spec["repo"],
                        "confidence": "unknown",
                        "reason": str(ref_ev.get("message") or ref_ev.get("code") or "import-reference-source unavailable"),
                        "authority_required": "Host filesystem without symlink/reparse barriers for REA reference import",
                    }
                )

            if "js_subpath" in spec:
                js_root = (repo_dir / spec["js_subpath"]).resolve()
                if js_root.is_dir():
                    js_args = ["analyze-javascript-application", str(js_root)]
                    for sp in spec.get("js_source_paths", []):
                        if (js_root / sp).is_file():
                            js_args.extend(["--source-path", sp])
                    ok_js, js_ev = _run_rea_json(launcher, js_args, timeout=90.0)
                    if ok_js:
                        (raw_out_dir / f"{slug}_js_app.json").write_text(json.dumps(js_ev), encoding=ENCODING)
                        entry["rea_evidence"].append(
                            {
                                "operation": "analyze_javascript_application",
                                "evidence_id": js_ev["evidence_id"],
                                "confidence": js_ev.get("confidence", "observed"),
                                "authority": js_ev.get("authority", "shipped-artifact"),
                                "selected_sources": spec.get("js_source_paths", []),
                            }
                        )

            if not entry["rea_evidence"] and entry["observed_anchors"]:
                anchor_zip = raw_out_dir / f"{slug}_reference_anchors.zip"
                with zipfile.ZipFile(anchor_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                    for anchor in spec["key_anchors"]:
                        ap = repo_dir / anchor
                        if ap.is_file():
                            zf.writestr(anchor, ap.read_bytes())
                ok_az, az_ev = _run_rea_json(launcher, ["inspect-artifact", str(anchor_zip)], timeout=45.0)
                if ok_az:
                    entry["rea_evidence"].append(
                        {
                            "operation": "inspect_artifact",
                            "artifact": f"{slug}_reference_anchors.zip",
                            "evidence_id": az_ev["evidence_id"],
                            "confidence": az_ev.get("confidence", "observed"),
                            "authority": "historical-reference-anchors",
                        }
                    )

        if launcher and releases_dir.is_dir():
            if "release_archive" in spec:
                arc_path = releases_dir / spec["release_archive"]
                if arc_path.is_file():
                    ok_arc, arc_ev = _run_rea_json(launcher, ["inspect-artifact", str(arc_path)], timeout=60.0)
                    if ok_arc:
                        entry["rea_evidence"].append(
                            {
                                "operation": "inspect_artifact",
                                "artifact": _rel_display(arc_path, stg),
                                "sha256": _sha256_file(arc_path),
                                "evidence_id": arc_ev["evidence_id"],
                                "confidence": arc_ev.get("confidence", "observed"),
                            }
                        )

            if "release_pe" in spec:
                pe_path = releases_dir / spec["release_pe"]
                if pe_path.is_file():
                    pe_op = "inspect-go-binary" if slug == "numbat" else "inspect-rust-binary"
                    ok_bin, bin_ev = _run_rea_json(launcher, [pe_op, str(pe_path)], timeout=45.0)
                    if ok_bin:
                        norm_b = bin_ev.get("normalized_result") or {}
                        meta_summary: dict[str, Any] = {
                            "operation": bin_ev.get("operation", pe_op.replace("-", "_")),
                            "artifact": _rel_display(pe_path, stg),
                            "sha256": _sha256_file(pe_path),
                            "evidence_id": bin_ev["evidence_id"],
                            "confidence": bin_ev.get("confidence", "observed"),
                        }
                        if slug == "numbat":
                            binfo = norm_b.get("build_info") or {}
                            mod = binfo.get("module") or {}
                            meta_summary["go_version"] = binfo.get("go_version")
                            meta_summary["dependency_count"] = len(mod.get("dependencies") or [])
                        else:
                            meta_summary["auditable_metadata_present"] = norm_b.get("auditable_metadata") is not None
                            rc = (norm_b.get("rustc_commit") or {}).get("hashes") or []
                            meta_summary["inferred_rustc_commit"] = rc[0]["hash"] if rc else None
                        entry["rea_evidence"].append(meta_summary)

                    ok_pe, pe_res = _run_rea_json(launcher, ["inspect-pe-resources", str(pe_path)], timeout=45.0)
                    if ok_pe:
                        entry["rea_evidence"].append(
                            {
                                "operation": "inspect_pe_resources",
                                "artifact": _rel_display(pe_path, stg),
                                "evidence_id": pe_res["evidence_id"],
                                "confidence": pe_res.get("confidence", "observed"),
                            }
                        )

            if "release_elf" in spec:
                elf_path = releases_dir / spec["release_elf"]
                if elf_path.is_file():
                    ok_elf, elf_ev = _run_rea_json(launcher, ["inspect-binary-layout", str(elf_path)], timeout=45.0)
                    if ok_elf:
                        entry["rea_evidence"].append(
                            {
                                "operation": "inspect_binary_layout",
                                "artifact": _rel_display(elf_path, stg),
                                "evidence_id": elf_ev["evidence_id"],
                                "confidence": elf_ev.get("confidence", "observed"),
                            }
                        )
                    else:
                        residual_unknowns.append(
                            {
                                "id": f"RU-ELF-{slug.upper()}",
                                "target": spec["repo"],
                                "confidence": "unknown",
                                "reason": str(elf_ev.get("message") or "pwntools-elf requires Linux x64 host"),
                                "authority_required": "Linux x64 pwntools-elf or Ghidra 12.1.x provider",
                            }
                        )

        target_records.append(entry)

    residual_unknowns.extend(
        [
            {
                "id": "RU-PPLX-OPENAPI-BUCKET",
                "target": "perplexityai/perplexity-py",
                "confidence": "unknown",
                "reason": "Upstream .stats.yml GCS bucket (stainless-sdk-openapi-specs) is non-public (NoSuchBucket); local api.md and generated/api.py provide observed SDK ground truth.",
                "authority_required": "Perplexity internal Stainless OpenAPI bucket access",
            },
            {
                "id": "RU-PPLX-CUDA-SASS",
                "target": "perplexityai/pplx-kernels",
                "confidence": "unknown",
                "reason": "Device .nv_fatbin SASS/PTX instructions are not compiled or decompiled on non-CUDA Windows hosts; host C++/Python dispatch/combine invariants are statically verified.",
                "authority_required": "Linux CUDA + NVSHMEM build host with nvdisasm / Ghidra",
            },
        ]
    )

    payload: dict[str, Any] = {
        "schema": "luminara.rea.perplexity.v1",
        "rea_package": REA_PACKAGE_SPEC,
        "host_platform": host_platform,
        "source_mode": "live_rea_harvest",
        "target_count": len(target_records),
        "targets_present": sum(1 for t in target_records if t["present"]),
        "total_evidence_records": sum(len(t["rea_evidence"]) for t in target_records),
        "elapsed_ms": round((time.time() - started) * 1000, 1),
        "targets": DEFAULT_REDACTOR.redact_payload(target_records),
        "residual_unknowns": residual_unknowns,
    }
    if write_committed_summary:
        serialized = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        summary_path.write_text(serialized, encoding=ENCODING, newline="\n")
        pkg_summary_path.parent.mkdir(parents=True, exist_ok=True)
        pkg_summary_path.write_text(serialized, encoding=ENCODING, newline="\n")
    return payload
