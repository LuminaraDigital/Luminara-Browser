"""Zero-dependency Hardened HTTP Control Plane for Luminara Browser Forge Studio (`forge/studio.py`)."""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from typing import Any
from urllib.parse import urlparse

from .customizer import compile_fork_overlay
from .desktop_build import DESKTOP_EXE_NAME, build_desktop_host
from .desktop_installer import get_desktop_status, install_desktop_app, uninstall_desktop_app
from .http_base import LoopbackHTTPServer, LoopbackJSONHandler, ensure_local_ui_key
from .models import ForkProfile, SEARCH_ENGINE_PRESETS
from .portable import assemble_portable_distribution
from .verifier import run_rea_verification_suite

ENCODING = "utf-8"

HOST_MUTATING_STUDIO_ROUTES = frozenset(
    {
        "/api/build-portable",
        "/api/build-desktop",
        "/api/install-desktop",
        "/api/uninstall-desktop",
        "/api/launch-browser",
    }
)


def _port_is_listening(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.4):
            return True
    except OSError:
        return False


def make_studio_handler(
    forge_root: Path,
    upstream_core_repo: Path,
    upstream_win_repo: Path,
    *,
    install_dir: Path | None = None,
    user_data_root: Path | None = None,
    start_menu_dir: Path | None = None,
    desktop_dir: Path | None = None,
    registry_backend: Any | None = None,
):
    forge_root = forge_root.resolve()
    ui_html_path = Path(__file__).resolve().parent / "ui" / "index.html"
    profile_path = forge_root / "fork.json"
    overlay_dir = forge_root / "overlay"
    dist_root = forge_root / "dist"
    default_cache_zip = forge_root / "cache" / "ungoogled-chromium_157.0.8103.50-1.1_windows_x64.zip"
    ui_key = ensure_local_ui_key(forge_root)

    def _resolve_cache_zip() -> Path:
        if default_cache_zip.exists():
            return default_cache_zip
        zips = sorted((forge_root / "cache").glob("ungoogled-chromium_*_windows_*.zip"))
        return zips[-1] if zips else default_cache_zip

    def _current_profile() -> ForkProfile:
        if profile_path.exists():
            return ForkProfile.load(profile_path)
        default = ForkProfile()
        default.save(profile_path)
        return default

    def _status_payload() -> dict[str, Any]:
        return get_desktop_status(
            forge_root,
            install_dir=install_dir,
            registry_backend=registry_backend,
        )

    def _read_overlay_artifacts(prof: ForkProfile) -> dict[str, str]:
        if not (upstream_core_repo / "patches").is_dir() or not upstream_win_repo.is_dir():
            note = "# Upstream ungoogled-chromium patch tree not present in standalone mode (pass --core-repo / --windows-repo)."
            return {
                "branding_patch": note,
                "search_patch": note,
                "network_trap_patch": note,
                "domain_regex": note,
                "args_gn": note,
                "cloud_workflow": note,
            }
        paths = compile_fork_overlay(prof, upstream_core_repo, upstream_win_repo, overlay_dir)
        return {
            "branding_patch": paths["branding_patch"].read_text(encoding=ENCODING),
            "search_patch": paths["search_patch"].read_text(encoding=ENCODING),
            "network_trap_patch": "\n".join(
                paths["network_trap_patch"].read_text(encoding=ENCODING).splitlines()[:80]
            ),
            "domain_regex": paths["domain_regex"].read_text(encoding=ENCODING),
            "args_gn": paths["args_gn"].read_text(encoding=ENCODING),
            "cloud_workflow": paths["cloud_workflow"].read_text(encoding=ENCODING),
        }

    class StudioRequestHandler(LoopbackJSONHandler):
        local_ui_key = ui_key
        allow_extension_origins = False
        forge_root_dir = forge_root

        def do_GET(self) -> None:  # noqa: N802
            if not self.check_loopback_security(is_post=False):
                return
            try:
                parsed = urlparse(self.path)
                if parsed.path in ("/", "/index.html"):
                    self.send_text(ui_html_path.read_text(encoding=ENCODING), content_type="text/html; charset=utf-8")
                    return

                if parsed.path == "/api/state":
                    prof = _current_profile()
                    artifacts = _read_overlay_artifacts(prof)
                    report_path = forge_root / "rea_verification_report.json"
                    rea_report = None
                    if report_path.exists():
                        try:
                            rea_report = json.loads(report_path.read_text(encoding=ENCODING))
                        except json.JSONDecodeError:
                            rea_report = None
                    portable_exe = dist_root / f"{prof.slug}-win64" / "App" / "chrome.exe"
                    cz = _resolve_cache_zip()
                    self.send_json(
                        {
                            "ui_key": ensure_local_ui_key(forge_root),
                            "profile": prof.to_dict(),
                            "presets": {k: v.name for k, v in SEARCH_ENGINE_PRESETS.items()},
                            "artifacts": artifacts,
                            "rea_report": rea_report,
                            "portable_status": {
                                "zip_cached": cz.exists(),
                                "zip_size_mb": round(cz.stat().st_size / 1_048_576, 1)
                                if cz.exists()
                                else 0,
                                "built": portable_exe.exists(),
                                "dist_dir": str((dist_root / f"{prof.slug}-win64").resolve()),
                            },
                            "desktop_status": _status_payload(),
                        }
                    )
                    return

                self.send_json({"error": "Not found"}, status=404)
            except Exception as exc:  # noqa: BLE001
                self.send_json({"ok": False, "error": str(exc)}, status=400)

        def do_POST(self) -> None:  # noqa: N802
            if not self.check_loopback_security(is_post=True):
                return
            parsed = urlparse(self.path)
            try:
                data = self.read_json_dict()
                if parsed.path in HOST_MUTATING_STUDIO_ROUTES:
                    if not self._has_valid_ui_key((self.headers.get("X-Luminara-UI-Key") or "").strip()):
                        self.send_json(
                            {"ok": False, "error": f"{parsed.path} requires Studio UI authorization (X-Luminara-UI-Key)"},
                            status=403,
                        )
                        return

                if parsed.path == "/api/compile":
                    allowed = {f.name for f in ForkProfile.__dataclass_fields__.values()}
                    merged_fields = {**_current_profile().to_dict(), **{k: v for k, v in data.items() if k in allowed}}
                    prof = ForkProfile(**merged_fields)
                    prof.save(profile_path)
                    artifacts = _read_overlay_artifacts(prof)
                    self.send_json({"ok": True, "profile": prof.to_dict(), "artifacts": artifacts})
                    return

                if parsed.path == "/api/verify":
                    prof = _current_profile()
                    report = run_rea_verification_suite(
                        upstream_core_repo, upstream_win_repo, forge_root, prof
                    )
                    self.send_json({"ok": True, "rea_report": report})
                    return

                if parsed.path == "/api/build-portable":
                    prof = _current_profile()
                    result = assemble_portable_distribution(_resolve_cache_zip(), prof, dist_root, forge_root=forge_root)
                    self.send_json({"ok": True, "result": result, "desktop_status": _status_payload()})
                    return

                if parsed.path == "/api/build-desktop":
                    prof = _current_profile()
                    dest = (dist_root / f"{prof.slug}-win64").resolve()
                    result = build_desktop_host(forge_root, dest_dir=dest, release=True)
                    self.send_json({"ok": True, "result": result, "desktop_status": _status_payload()})
                    return

                if parsed.path == "/api/install-desktop":
                    prof = _current_profile()
                    src = Path(str(data["source_dir"])).resolve() if data.get("source_dir") else (dist_root / f"{prof.slug}-win64").resolve()
                    if not (src / "App" / "chrome.exe").is_file():
                        assemble_portable_distribution(_resolve_cache_zip(), prof, dist_root, forge_root=forge_root)
                    result = install_desktop_app(
                        src,
                        forge_root=forge_root,
                        install_dir=install_dir,
                        user_data_root=user_data_root,
                        start_menu_dir=start_menu_dir,
                        desktop_dir=desktop_dir,
                        create_desktop_shortcut=bool(data.get("create_desktop_shortcut", True)),
                        create_start_menu=bool(data.get("create_start_menu", True)),
                        dry_run=bool(data.get("dry_run", False)),
                        registry_backend=registry_backend,
                    )
                    self.send_json({"ok": True, "result": result, "desktop_status": _status_payload()})
                    return

                if parsed.path == "/api/uninstall-desktop":
                    result = uninstall_desktop_app(
                        install_dir=install_dir,
                        user_data_root=user_data_root,
                        start_menu_dir=start_menu_dir,
                        desktop_dir=desktop_dir,
                        purge_data=bool(data.get("purge_data", False)),
                        dry_run=bool(data.get("dry_run", False)),
                        registry_backend=registry_backend,
                    )
                    self.send_json({"ok": True, "result": result, "desktop_status": _status_payload()})
                    return

                if parsed.path == "/api/launch-browser":
                    prof = _current_profile()
                    cz = _resolve_cache_zip()
                    dist_dir = (dist_root / f"{prof.slug}-win64").resolve()
                    chrome_exe = dist_dir / "App" / "chrome.exe"
                    assemble_portable_distribution(cz, prof, dist_root, forge_root=forge_root)

                    creation_flags = (
                        getattr(subprocess, "DETACHED_PROCESS", 0)
                        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                        if os.name == "nt"
                        else 0
                    )
                    native_host = dist_dir / DESKTOP_EXE_NAME
                    if os.name == "nt" and native_host.is_file():
                        subprocess.Popen([str(native_host)], cwd=str(dist_dir), creationflags=creation_flags, close_fds=True)
                        self.send_json({"ok": True, "launched": str(native_host), "cdp_port": prof.cdp_port, "mode": "native_desktop_host"})
                        return

                    if prof.enable_agent_cobrowsing and not _port_is_listening(prof.agent_port):
                        subprocess.Popen(
                            [
                                sys.executable,
                                "-m",
                                "forge",
                                "agent-daemon",
                                "--forge-root",
                                str(forge_root),
                                "--port",
                                str(prof.agent_port),
                                "--cdp-port",
                                str(prof.cdp_port),
                            ],
                            cwd=str(forge_root),
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            creationflags=creation_flags,
                            close_fds=True,
                        )
                        for _ in range(20):
                            if _port_is_listening(prof.agent_port):
                                break
                            time.sleep(0.1)

                    ext_paths = [str(dist_dir / "App" / "extensions" / "forge-shield")]
                    ext_names = ("luminara-copilot", "luminara-newtab", "luminara-theme") if prof.enable_agent_cobrowsing else ("luminara-newtab", "luminara-theme")
                    for ext_name in ext_names:
                        ext_candidate = dist_dir / "App" / "extensions" / ext_name
                        if ext_candidate.exists():
                            ext_paths.append(str(ext_candidate))
                    default_home = "chrome://newtab" if prof.enable_agent_cobrowsing else "about:blank"
                    extra_cdp = (
                        [
                            f"--remote-debugging-port={prof.cdp_port}",
                            f"--remote-allow-origins=http://127.0.0.1:{prof.agent_port}",
                        ]
                        if prof.enable_agent_cobrowsing
                        else []
                    )
                    cmd = [
                        str(chrome_exe),
                        f"--user-data-dir={dist_dir / 'Profile'}",
                        f"--load-extension={','.join(ext_paths)}",
                        *prof.runtime_switches(),
                        *extra_cdp,
                        default_home,
                    ]
                    subprocess.Popen(cmd, creationflags=creation_flags, close_fds=True)
                    self.send_json({"ok": True, "launched": str(chrome_exe), "cdp_port": prof.cdp_port})
                    return

                self.send_json({"error": "Unknown endpoint"}, status=404)
            except Exception as exc:  # noqa: BLE001
                self.send_json({"ok": False, "error": str(exc)}, status=400)

    return StudioRequestHandler


def run_studio_server(
    forge_root: Path,
    upstream_core_repo: Path,
    upstream_win_repo: Path,
    host: str = "127.0.0.1",
    port: int = 8795,
) -> None:
    handler_cls = make_studio_handler(forge_root, upstream_core_repo, upstream_win_repo)
    server = LoopbackHTTPServer((host, port), handler_cls)
    print(f"Luminara Browser Forge Studio listening on http://{host}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
