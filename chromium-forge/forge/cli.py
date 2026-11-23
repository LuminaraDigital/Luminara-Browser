"""Unified CLI entrypoint for Luminara Browser / Chromium Forge (`python -m forge`)."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

from .ab_benchmark import run_ab_benchmark_suite
from .agent_server import APP_VERSION, run_agent_daemon
from .arch_ratchet import run_architecture_ratchet
from .benchmark_100x import run_100x_benchmark_suite
from .chromium_src import (
    audit_version_provenance,
    ensure_sparse_chromium_checkout,
    verify_patches_against_upstream,
)
from .customizer import compile_fork_overlay
from .desktop_build import build_desktop_host
from .desktop_installer import get_desktop_status, install_desktop_app, uninstall_desktop_app
from .models import ForkProfile
from .monitors_eval import MonitorEvalEngine
from .patcher import audit_patch_directory
from .portable import assemble_portable_distribution
from .rea_harvester import harvest_perplexity_rea_evidence
from .studio import run_studio_server
from .updater import canonical_manifest_bytes, load_manifest_source, sign_release_manifest, verify_release_manifest
from .verifier import run_rea_verification_suite

ENCODING = "utf-8"


def _resolve_forge_root() -> Path:
    env_root = (os.environ.get("LUMINARA_FORGE_ROOT") or "").strip()
    if env_root:
        return Path(env_root).expanduser().resolve()
    pkg_parent = Path(__file__).resolve().parent.parent
    if (pkg_parent / "fork.json").is_file() or (pkg_parent / "patches" / "luminara").is_dir():
        return pkg_parent
    cwd = Path.cwd().resolve()
    if (cwd / "chromium-forge" / "fork.json").is_file():
        return cwd / "chromium-forge"
    if (cwd / "fork.json").is_file():
        return cwd
    return (Path.home() / ".luminara-browser").resolve()


def _default_paths(forge_root: Path | None = None) -> tuple[Path, Path, Path]:
    resolved_forge = (forge_root or _resolve_forge_root()).resolve()
    studio_root = resolved_forge.parent
    core_repo = studio_root / "ungoogled-chromium"
    win_repo = studio_root / "ungoogled-chromium-windows"
    return resolved_forge, core_repo, win_repo


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
    init_forge, default_core, default_win = _default_paths()

    sub_common = argparse.ArgumentParser(add_help=False)
    sub_common.add_argument("--forge-root", type=Path, default=argparse.SUPPRESS)
    sub_common.add_argument("--core-repo", type=Path, default=argparse.SUPPRESS)
    sub_common.add_argument("--windows-repo", type=Path, default=argparse.SUPPRESS)
    sub_common.add_argument("--profile", type=Path, default=argparse.SUPPRESS)

    parser = argparse.ArgumentParser(
        prog="forge",
        description="Luminara Browser Forge v4.0.0 — Clean-room Ungoogled-Chromium, PiBot Teams & 28-Tool MCP v2 Co-Browsing Engine",
    )
    parser.add_argument("--forge-root", type=Path, default=None)
    parser.add_argument("--core-repo", type=Path, default=None)
    parser.add_argument("--windows-repo", type=Path, default=None)
    parser.add_argument("--profile", type=Path, default=None)

    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", parents=[sub_common], help="Create or update fork.json profile and compile custom overlay")
    p_init.add_argument("--brand", default="Luminara Browser")
    p_init.add_argument("--slug", default="luminara-browser")
    p_init.add_argument("--trap-tld", default="void0")
    p_init.add_argument("--search", default="duckduckgo")

    sub.add_parser("audit-patches", parents=[sub_common], help="Audit all upstream core and Windows Quilt patch series")
    sub.add_parser("compile-overlay", parents=[sub_common], help="Compile fork.json into unified diffs, domain_regex.list, and args.gn")
    p_rea = sub.add_parser("verify-rea", parents=[sub_common], help="Run all 21 REA Reconstruction Obligation verification checks")
    p_rea.add_argument("--static-only", action="store_true", help="Run static OBL-01..07 and OBL-15..21 checks without requiring prebuilt chrome.exe")

    p_bench = sub.add_parser("benchmark", parents=[sub_common], help="Run live AB-01..AB-08 production A/B benchmarks")
    p_bench.add_argument("--out-json", type=Path, default=None)
    p_bench.add_argument("--out-md", type=Path, default=None)

    p_port = sub.add_parser("build-portable", parents=[sub_common], help="Build a working portable Luminara Browser Windows x64 app")
    p_port.add_argument("--zip", type=Path, default=None)
    p_port.add_argument("--release", action="store_true", help="Scrub build-host UI keys and runtime outputs for clean public release ZIP packaging")

    sub.add_parser("export-windows-overlay", parents=[sub_common], help="Apply compiled fork overlay onto ungoogled-chromium-windows")

    p_studio = sub.add_parser("studio", parents=[sub_common], help="Launch the interactive Luminara Browser Forge Studio Web UI")
    p_studio.add_argument("--host", default="127.0.0.1")
    p_studio.add_argument("--port", type=int, default=8795)

    p_agent = sub.add_parser("agent-daemon", parents=[sub_common], help="Launch the Luminara Agent Daemon (REST + MCP v2 + CDP Bridge)")
    p_agent.add_argument("--host", default="127.0.0.1")
    p_agent.add_argument("--port", type=int, default=8796)
    p_agent.add_argument("--cdp-port", type=int, default=9229)

    p_sparse = sub.add_parser("sync-chromium-sparse", parents=[sub_common], help="Blobless sparse checkout of upstream chromium/chromium (<150 MB)")
    p_sparse.add_argument("--dest", type=Path, default=None)
    p_sparse.add_argument("--tag", default=None)

    p_up = sub.add_parser("verify-upstream-patches", parents=[sub_common], help="Verify Luminara C++ patches & version provenance against vendor/chromium-src")
    p_up.add_argument("--chromium-src", type=Path, default=None)

    p_b100 = sub.add_parser("benchmark-100x", parents=[sub_common], help="Run Luminara v3.0 100x Engine Benchmarks (BM-01..BM-06)")
    p_b100.add_argument("--out-json", type=Path, default=None)
    p_b100.add_argument("--out-md", type=Path, default=None)

    p_sign = sub.add_parser("sign-manifest", parents=[sub_common], help="Generate and optionally HMAC-sign a cryptographic release-manifest.json")
    p_sign.add_argument("--version", default=None)
    p_sign.add_argument("--chromium-version", default=None)
    p_sign.add_argument("--portable-binary-base", default="157.0.8103.50-1.1")
    p_sign.add_argument("--artifact-name", required=True)
    p_sign.add_argument("--artifact-sha256", required=True)
    p_sign.add_argument("--out", type=Path, required=True)
    p_sign.add_argument("--signing-key-hex", default=None)

    p_upd = sub.add_parser("check-updates", parents=[sub_common], help="Opt-in cryptographic release manifest verifier (zero background pings)")
    p_upd.add_argument("--manifest", required=True, help="Local JSON path or explicit HTTPS release manifest URL")
    p_upd.add_argument("--artifact", type=Path, default=None)
    p_upd.add_argument("--signing-key-hex", default=None, help="Hex HMAC signing key (or set LUMINARA_RELEASE_KEY_HEX)")
    p_upd.add_argument("--allow-unsigned", action="store_true", help="Allow schema/SHA-256 verification without HMAC signature")

    p_harv = sub.add_parser("harvest-rea", parents=[sub_common], help="Harvest REA v6.5.0 Evidence across staged Perplexity AI repositories")
    p_harv.add_argument("--staging-root", type=Path, default=None)

    sub.add_parser("verify-arch", parents=[sub_common], help="Run SPACE pattern-ratchet (<1,000L, zero-dep, layer guard) + Codescythe dead-code gate")

    p_eval = sub.add_parser("eval-search", parents=[sub_common], help="Run multi-provider Search/Extraction Eval Suite with Decimal CostLedger")
    p_eval.add_argument("--suite", default="extraction")
    p_eval.add_argument("--providers", default="luminara,perplexity,gemini")

    p_bdesk = sub.add_parser("build-desktop", parents=[sub_common], help="Compile native Rust Win32 LuminaraBrowser.exe host & verify PE/resources")
    p_bdesk.add_argument("--debug", action="store_true", help="Build debug profile instead of optimized release")
    p_bdesk.add_argument("--dest", type=Path, default=None, help="Directory to stage LuminaraBrowser.exe (defaults to dist/<slug>-win64)")

    p_inst = sub.add_parser("install-desktop", parents=[sub_common], help="Install Luminara Browser per-user (%LOCALAPPDATA%, Start Menu, Desktop, Apps & Features)")
    p_inst.add_argument("--source-dir", type=Path, default=None, help="Portable dist directory containing App/chrome.exe & LuminaraBrowser.exe")
    p_inst.add_argument("--install-dir", type=Path, default=None, help="Override per-user install directory")
    p_inst.add_argument("--no-start-menu", action="store_true")
    p_inst.add_argument("--no-desktop-shortcut", action="store_true")
    p_inst.add_argument("--no-register-os", action="store_true")
    p_inst.add_argument("--no-register-browser", action="store_true")
    p_inst.add_argument("--dry-run", action="store_true")

    p_uninst = sub.add_parser("uninstall-desktop", parents=[sub_common], help="Uninstall Luminara Browser, shortcuts, and Apps & Features registry entries")
    p_uninst.add_argument("--install-dir", type=Path, default=None)
    p_uninst.add_argument("--purge-data", action="store_true", help="Also delete %LOCALAPPDATA%\\Luminara Browser profile, vault, and logs")
    p_uninst.add_argument("--no-unregister-os", action="store_true")
    p_uninst.add_argument("--dry-run", action="store_true")

    p_dstat = sub.add_parser("desktop-status", parents=[sub_common], help="Inspect portable & installed LuminaraBrowser.exe PE, shortcuts, and registry state")
    p_dstat.add_argument("--install-dir", type=Path, default=None)

    args = parser.parse_args(argv)
    forge_root, def_core_for_root, def_win_for_root = _default_paths(args.forge_root or init_forge)
    core_repo = (args.core_repo or def_core_for_root).resolve()
    win_repo = (args.windows_repo or def_win_for_root).resolve()
    profile_path = (args.profile or (forge_root / "fork.json")).resolve()
    in_repo_layout = (forge_root.parent / "ungoogled-chromium").is_dir()

    if args.command == "init":
        prof = ForkProfile(
            brand_name=args.brand,
            slug=args.slug,
            channel_tag=f"{args.slug}-agentic",
            trap_tld=args.trap_tld,
            default_search=args.search,
        )
        prof.save(profile_path)
        compiled_map: dict[str, str] = {}
        if core_repo.is_dir() and win_repo.is_dir():
            out = compile_fork_overlay(prof, core_repo, win_repo, forge_root / "overlay")
            compiled_map = {k: str(v) for k, v in out.items()}
        print(json.dumps({"saved_profile": str(profile_path), "compiled": compiled_map}, indent=2))
        return 0

    prof = ForkProfile.load(profile_path) if profile_path.exists() else ForkProfile()

    if args.command == "audit-patches":
        core_rep = audit_patch_directory(core_repo / "patches")
        win_rep = audit_patch_directory(win_repo / "patches")
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
        out = compile_fork_overlay(prof, core_repo, win_repo, forge_root / "overlay")
        print(json.dumps({k: str(v) for k, v in out.items()}, indent=2))
        return 0

    if args.command == "verify-rea":
        report = run_rea_verification_suite(
            core_repo,
            win_repo,
            forge_root,
            prof,
            static_only=bool(args.static_only),
        )
        print(json.dumps(report, indent=2))
        return 0 if report["all_obligations_passed"] else 1

    if args.command == "benchmark":
        out_json = args.out_json or (forge_root / "outputs" / "ab_results.json")
        default_md = (forge_root.parent / "docs" / "ab-benchmark-results.md") if in_repo_layout else (forge_root / "outputs" / "ab-benchmark-results.md")
        out_md = args.out_md or default_md
        bench = run_ab_benchmark_suite(forge_root, out_json=out_json, out_markdown=out_md)
        print(json.dumps(bench, indent=2))
        return 0 if bench["all_passed"] else 1

    if args.command == "build-portable":
        zip_path = args.zip
        if zip_path is None:
            default_zip = forge_root / "cache" / "ungoogled-chromium_157.0.8103.50-1.1_windows_x64.zip"
            if default_zip.exists():
                zip_path = default_zip
            else:
                zips = sorted((forge_root / "cache").glob("ungoogled-chromium_*_windows_*.zip"))
                zip_path = zips[-1] if zips else default_zip
        res = assemble_portable_distribution(
            zip_path,
            prof,
            forge_root / "dist",
            forge_root=forge_root,
            release_scrub=bool(args.release),
        )
        print(json.dumps(res, indent=2))
        return 0

    if args.command == "export-windows-overlay":
        exported = export_windows_overlay(prof, core_repo, win_repo, forge_root=forge_root)
        print(json.dumps(exported, indent=2))
        return 0

    if args.command == "studio":
        run_studio_server(forge_root, core_repo, win_repo, host=args.host, port=args.port)
        return 0

    if args.command == "agent-daemon":
        run_agent_daemon(forge_root, host=args.host, port=args.port, cdp_port=args.cdp_port)
        return 0

    if args.command == "sync-chromium-sparse":
        default_dest = (forge_root.parent / "vendor" / "chromium-src") if in_repo_layout else (forge_root / "vendor" / "chromium-src")
        dest = args.dest or default_dest
        out = ensure_sparse_chromium_checkout(dest, tag=args.tag)
        print(json.dumps(out, indent=2))
        return 0 if out["ok"] else 1

    if args.command == "verify-upstream-patches":
        default_csrc = (forge_root.parent / "vendor" / "chromium-src") if in_repo_layout else (forge_root / "vendor" / "chromium-src")
        csrc = args.chromium_src or default_csrc
        patches_dir = forge_root / "patches" / "luminara"
        if not patches_dir.is_dir():
            pkg_patches = Path(__file__).resolve().parent / "patches" / "luminara"
            if pkg_patches.is_dir():
                patches_dir = pkg_patches
        patch_rep = verify_patches_against_upstream(patches_dir, csrc)
        prov_rep = audit_version_provenance(prof, core_repo, forge_root / "cache", csrc)
        combined = {"patches": patch_rep, "provenance": prov_rep, "ok": patch_rep["ok"]}
        print(json.dumps(combined, indent=2))
        return 0 if combined["ok"] else 1

    if args.command == "benchmark-100x":
        out_json = args.out_json or (forge_root / "outputs" / "benchmark_100x.json")
        default_md = (forge_root.parent / "docs" / "benchmark-100x-results.md") if in_repo_layout else (forge_root / "outputs" / "benchmark-100x-results.md")
        out_md = args.out_md or default_md
        rep = run_100x_benchmark_suite(out_json=out_json, out_md=out_md)
        print(json.dumps(rep, indent=2))
        return 0 if rep["all_passed"] else 1

    if args.command == "sign-manifest":
        ref = (args.version or os.environ.get("GITHUB_REF_NAME") or "").strip().lstrip("v")
        ver = ref if (ref and ref[0].isdigit()) else APP_VERSION
        chrom_ver = args.chromium_version or f"{prof.chromium_version}-1.1"
        base_manifest = {
            "version": ver,
            "chromium_version": chrom_ver,
            "portable_binary_base": args.portable_binary_base,
            "artifact_name": args.artifact_name,
            "artifact_sha256": args.artifact_sha256.strip().lower(),
        }
        key_hex = (args.signing_key_hex or os.environ.get("LUMINARA_RELEASE_KEY_HEX") or "").strip()
        if key_hex:
            sig_key = bytes.fromhex(key_hex)
            signed = sign_release_manifest(base_manifest, sig_key)
        else:
            signed = {
                **base_manifest,
                "manifest_sha256": hashlib.sha256(canonical_manifest_bytes(base_manifest)).hexdigest(),
            }
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(signed, indent=2) + "\n", encoding=ENCODING, newline="\n")
        print(json.dumps({"out": str(args.out), "signed": bool(key_hex), "version": ver}, indent=2))
        return 0

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

    if args.command == "harvest-rea":
        rep = harvest_perplexity_rea_evidence(forge_root, staging_root=args.staging_root)
        print(json.dumps(rep, indent=2))
        ok_harvest = rep["target_count"] == 7 and all(bool(t.get("rea_evidence")) for t in rep.get("targets", []))
        return 0 if ok_harvest else 1

    if args.command == "verify-arch":
        rep = run_architecture_ratchet(forge_root)
        print(json.dumps(rep, indent=2))
        return 0 if rep["ok"] else 1

    if args.command == "eval-search":
        provs = [p.strip() for p in str(args.providers).split(",") if p.strip()]
        eng = MonitorEvalEngine(forge_root / "outputs" / "monitors_eval.sqlite3")
        rep = eng.run_search_eval_suite(suite=args.suite, providers=provs)
        print(json.dumps(rep, indent=2))
        return 0 if rep["ok"] else 1

    if args.command == "build-desktop":
        dest = args.dest if args.dest is not None else (forge_root / "dist" / f"{prof.slug}-win64")
        rep = build_desktop_host(forge_root, dest_dir=dest, release=not bool(args.debug))
        print(json.dumps(rep, indent=2))
        return 0 if rep["ok"] else 1

    if args.command == "install-desktop":
        src = args.source_dir if args.source_dir is not None else (forge_root / "dist" / f"{prof.slug}-win64")
        rep = install_desktop_app(
            src,
            forge_root=forge_root,
            install_dir=args.install_dir,
            create_start_menu=not bool(args.no_start_menu),
            create_desktop_shortcut=not bool(args.no_desktop_shortcut),
            register_os=not bool(args.no_register_os),
            register_browser_protocols=not bool(args.no_register_browser),
            dry_run=bool(args.dry_run),
        )
        print(json.dumps(rep, indent=2))
        return 0 if rep["ok"] else 1

    if args.command == "uninstall-desktop":
        rep = uninstall_desktop_app(
            install_dir=args.install_dir,
            purge_data=bool(args.purge_data),
            unregister_os=not bool(args.no_unregister_os),
            dry_run=bool(args.dry_run),
        )
        print(json.dumps(rep, indent=2))
        return 0 if rep["ok"] else 1

    if args.command == "desktop-status":
        rep = get_desktop_status(forge_root, install_dir=args.install_dir)
        print(json.dumps(rep, indent=2))
        return 0 if rep["ok"] else 1

    return 1


if __name__ == "__main__":
    sys.exit(main())
