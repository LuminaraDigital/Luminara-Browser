"""Unified CLI entrypoint for Luminara Browser / Chromium Forge (`python -m forge`)."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys

from .ab_benchmark import run_ab_benchmark_suite
from .agent_server import run_agent_daemon
from .benchmark_100x import run_100x_benchmark_suite
from .chromium_src import (
    audit_version_provenance,
    ensure_sparse_chromium_checkout,
    verify_patches_against_upstream,
)
from .customizer import compile_fork_overlay
from .models import ForkProfile
from .patcher import audit_patch_directory
from .portable import assemble_portable_distribution
from .studio import run_studio_server
from .updater import load_manifest_source, verify_release_manifest
from .verifier import run_rea_verification_suite

ENCODING = "utf-8"


def _default_paths() -> tuple[Path, Path, Path]:
    forge_root = Path(__file__).resolve().parent.parent
    studio_root = forge_root.parent
    core_repo = studio_root / "ungoogled-chromium"
    win_repo = studio_root / "ungoogled-chromium-windows"
    return forge_root, core_repo, win_repo


def export_windows_overlay(profile: ForkProfile, core_repo: Path, win_repo: Path, forge_root: Path | None = None) -> dict[str, str]:
    """Inject compiled fork patches, domain_regex.list, and flags directly into a Windows build tree."""
    resolved_forge = forge_root or Path(__file__).resolve().parent.parent
    compiled = compile_fork_overlay(profile, core_repo, win_repo, resolved_forge / "overlay")
    target_core = win_repo / "ungoogled-chromium"
    if not (target_core / "patches").exists():
        shutil.copytree(core_repo, target_core, dirs_exist_ok=True)

    shutil.copy2(
        compiled["branding_patch"],
        target_core / "patches" / "extra" / "ungoogled-chromium" / "add-extra-channel-info.patch",
    )
    shutil.copy2(
        compiled["search_patch"],
        target_core / "patches" / "core" / "ungoogled-chromium" / "replace-google-search-engine-with-nosearch.patch",
    )
    shutil.copy2(
        compiled["network_trap_patch"],
        target_core / "patches" / "core" / "ungoogled-chromium" / "block-trk-and-subdomains.patch",
    )
    shutil.copy2(compiled["domain_regex"], target_core / "domain_regex.list")

    luminara_patches_src = resolved_forge / "patches" / "luminara"
    if luminara_patches_src.exists():
        dst_lum = target_core / "patches" / "extra" / "luminara"
        dst_lum.mkdir(parents=True, exist_ok=True)
        series_file = target_core / "patches" / "series"
        existing_series = series_file.read_text(encoding=ENCODING).splitlines() if series_file.exists() else []
        appended = False
        for pf in sorted(luminara_patches_src.glob("*.patch")):
            shutil.copy2(pf, dst_lum / pf.name)
            rel_entry = f"extra/luminara/{pf.name}"
            if rel_entry not in existing_series:
                existing_series.append(rel_entry)
                appended = True
        if appended and series_file.exists():
            series_file.write_text("\n".join(existing_series) + "\n", encoding=ENCODING, newline="\n")

    return {k: str(v) for k, v in compiled.items()}


def main(argv: list[str] | None = None) -> int:
    forge_root, default_core, default_win = _default_paths()
    parser = argparse.ArgumentParser(
        prog="forge",
        description="Luminara Browser Forge — Clean-room Ungoogled-Chromium & 20-Tool MCP v2 Co-Browsing Engine",
    )
    parser.add_argument("--core-repo", type=Path, default=default_core)
    parser.add_argument("--windows-repo", type=Path, default=default_win)
    parser.add_argument("--profile", type=Path, default=forge_root / "fork.json")

    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Create or update fork.json profile and compile custom overlay")
    p_init.add_argument("--brand", default="Luminara Browser")
    p_init.add_argument("--slug", default="luminara-browser")
    p_init.add_argument("--trap-tld", default="void0")
    p_init.add_argument("--search", default="duckduckgo")

    sub.add_parser("audit-patches", help="Audit all upstream core and Windows Quilt patch series")
    sub.add_parser("compile-overlay", help="Compile fork.json into unified diffs, domain_regex.list, and args.gn")
    p_rea = sub.add_parser("verify-rea", help="Run all 14 REA Reconstruction Obligation verification checks")
    p_rea.add_argument("--static-only", action="store_true", help="Run static OBL-01..07 checks without requiring prebuilt chrome.exe")

    p_bench = sub.add_parser("benchmark", help="Run live AB-01..AB-08 production A/B benchmarks")
    p_bench.add_argument("--out-json", type=Path, default=forge_root / "outputs" / "ab_results.json")
    p_bench.add_argument("--out-md", type=Path, default=forge_root.parent / "docs" / "ab-benchmark-results.md")

    p_port = sub.add_parser("build-portable", help="Build a working portable Luminara Browser Windows x64 app")
    p_port.add_argument(
        "--zip",
        type=Path,
        default=forge_root / "cache" / "ungoogled-chromium_157.0.8103.50-1.1_windows_x64.zip",
    )

    sub.add_parser("export-windows-overlay", help="Apply compiled fork overlay onto ungoogled-chromium-windows")

    p_studio = sub.add_parser("studio", help="Launch the interactive Luminara Browser Forge Studio Web UI")
    p_studio.add_argument("--host", default="127.0.0.1")
    p_studio.add_argument("--port", type=int, default=8795)

    p_agent = sub.add_parser("agent-daemon", help="Launch the Luminara Agent Daemon (REST + MCP v2 + CDP Bridge)")
    p_agent.add_argument("--host", default="127.0.0.1")
    p_agent.add_argument("--port", type=int, default=8796)
    p_agent.add_argument("--cdp-port", type=int, default=9229)

    p_sparse = sub.add_parser("sync-chromium-sparse", help="Blobless sparse checkout of upstream chromium/chromium (<150 MB)")
    p_sparse.add_argument("--dest", type=Path, default=forge_root.parent / "vendor" / "chromium-src")
    p_sparse.add_argument("--tag", default=None)

    p_up = sub.add_parser("verify-upstream-patches", help="Verify Luminara C++ patches & version provenance against vendor/chromium-src")
    p_up.add_argument("--chromium-src", type=Path, default=forge_root.parent / "vendor" / "chromium-src")

    p_b100 = sub.add_parser("benchmark-100x", help="Run Luminara v3.0 100x Engine Benchmarks (BM-01..BM-06)")
    p_b100.add_argument("--out-json", type=Path, default=forge_root / "outputs" / "benchmark_100x.json")
    p_b100.add_argument("--out-md", type=Path, default=forge_root.parent / "docs" / "benchmark-100x-results.md")

    p_upd = sub.add_parser("check-updates", help="Opt-in cryptographic release manifest verifier (zero background pings)")
    p_upd.add_argument("--manifest", required=True, help="Local JSON path or explicit HTTPS release manifest URL")
    p_upd.add_argument("--artifact", type=Path, default=None)
    p_upd.add_argument("--signing-key-hex", default=None, help="Hex HMAC signing key (or set LUMINARA_RELEASE_KEY_HEX)")
    p_upd.add_argument("--allow-unsigned", action="store_true", help="Allow schema/SHA-256 verification without HMAC signature")

    args = parser.parse_args(argv)

    if args.command == "init":
        prof = ForkProfile(
            brand_name=args.brand,
            slug=args.slug,
            channel_tag=f"{args.slug}-agentic",
            trap_tld=args.trap_tld,
            default_search=args.search,
        )
        prof.save(args.profile)
        out = compile_fork_overlay(prof, args.core_repo, args.windows_repo, forge_root / "overlay")
        print(json.dumps({"saved_profile": str(args.profile), "compiled": {k: str(v) for k, v in out.items()}}, indent=2))
        return 0

    prof = ForkProfile.load(args.profile) if args.profile.exists() else ForkProfile()

    if args.command == "audit-patches":
        core_rep = audit_patch_directory(args.core_repo / "patches")
        win_rep = audit_patch_directory(args.windows_repo / "patches")
        print(
            json.dumps(
                {
                    "core": core_rep.__dict__,
                    "windows": win_rep.__dict__,
                    "ok": core_rep.ok and win_rep.ok,
                },
                indent=2,
            )
        )
        return 0 if (core_rep.ok and win_rep.ok) else 1

    if args.command == "compile-overlay":
        out = compile_fork_overlay(prof, args.core_repo, args.windows_repo, forge_root / "overlay")
        print(json.dumps({k: str(v) for k, v in out.items()}, indent=2))
        return 0

    if args.command == "verify-rea":
        report = run_rea_verification_suite(
            args.core_repo,
            args.windows_repo,
            forge_root,
            prof,
            static_only=bool(args.static_only),
        )
        print(json.dumps(report, indent=2))
        return 0 if report["all_obligations_passed"] else 1

    if args.command == "benchmark":
        bench = run_ab_benchmark_suite(forge_root, out_json=args.out_json, out_markdown=args.out_md)
        print(json.dumps(bench, indent=2))
        return 0 if bench["all_passed"] else 1

    if args.command == "build-portable":
        res = assemble_portable_distribution(args.zip, prof, forge_root / "dist")
        print(json.dumps(res, indent=2))
        return 0

    if args.command == "export-windows-overlay":
        exported = export_windows_overlay(prof, args.core_repo, args.windows_repo, forge_root=forge_root)
        print(json.dumps(exported, indent=2))
        return 0

    if args.command == "studio":
        run_studio_server(forge_root, args.core_repo, args.windows_repo, host=args.host, port=args.port)
        return 0

    if args.command == "agent-daemon":
        run_agent_daemon(forge_root, host=args.host, port=args.port, cdp_port=args.cdp_port)
        return 0

    if args.command == "sync-chromium-sparse":
        out = ensure_sparse_chromium_checkout(args.dest, tag=args.tag)
        print(json.dumps(out, indent=2))
        return 0 if out["ok"] else 1

    if args.command == "verify-upstream-patches":
        patch_rep = verify_patches_against_upstream(forge_root / "patches" / "luminara", args.chromium_src)
        prov_rep = audit_version_provenance(prof, args.core_repo, forge_root / "cache", args.chromium_src)
        combined = {"patches": patch_rep, "provenance": prov_rep, "ok": patch_rep["ok"]}
        print(json.dumps(combined, indent=2))
        return 0 if combined["ok"] else 1

    if args.command == "benchmark-100x":
        rep = run_100x_benchmark_suite(out_json=args.out_json, out_md=args.out_md)
        print(json.dumps(rep, indent=2))
        return 0 if rep["all_passed"] else 1

    if args.command == "check-updates":
        manifest = load_manifest_source(args.manifest)
        key_hex = (args.signing_key_hex or os.environ.get("LUMINARA_RELEASE_KEY_HEX") or "").strip()
        sig_key = bytes.fromhex(key_hex) if key_hex else None
        res = verify_release_manifest(
            manifest,
            signing_key=sig_key,
            allow_unsigned=bool(args.allow_unsigned),
            artifact_path=args.artifact,
        )
        print(json.dumps(res, indent=2))
        return 0 if res["valid"] else 1

    return 1


if __name__ == "__main__":
    sys.exit(main())
