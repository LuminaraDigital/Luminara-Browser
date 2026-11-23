"""End-to-end verification of the Luminara Browser Native Desktop Application (`tests/test_desktop_app.py`).

Covers:
1. Native Rust Win32 `LuminaraBrowser.exe` PE32+ GUI subsystem (`2`), icon, version info, PerMonitorV2 manifest, and CLI output.
2. Pure-stdlib Win32 COM `.lnk` shortcut creation with embedded `System.AppUserModel.ID`.
3. Per-user Installer -> Upgrade (user data preserved) -> Uninstall (user data preserved) -> Uninstall (`--purge-data`)
   using isolated temp directories and an in-memory registry backend (zero host OS mutation).
4. Live Agent Daemon `/api/agent/desktop/status`, `/api/agent/desktop/takeover`, and `/api/agent/shutdown`
   including strict `X-Luminara-UI-Key` enforcement (`403` without key).
5. Live native `LuminaraBrowser.exe` supervision + single-instance Named Pipe IPC (`--quit`) + zero-orphan exit.
"""

from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import shutil
import socket
import stat
import struct
import subprocess
import tempfile
import threading
import time
import unittest
from unittest import mock
import urllib.error
import urllib.request

from forge.agent_desktop import build_desktop_heartbeat, initiate_graceful_shutdown, trigger_desktop_takeover
from forge.agent_server import LuminaraAgentRuntime, create_agent_http_server
from forge.cdp_client import PersonControlError
from forge.cli import main as forge_cli_main
from forge.desktop_build import (
    DESKTOP_EXE_NAME,
    _atomic_copy_exe,
    build_desktop_host,
    find_desktop_crate_dir,
    inspect_pe_desktop_binary,
)
from forge.desktop_installer import (
    APP_USER_MODEL_ID,
    INSTALL_MANIFEST_NAME,
    UNINSTALL_SUBKEY,
    WinRegBackend,
    _schedule_deferred_dir_cleanup,
    create_windows_shortcut,
    default_desktop_dir,
    default_install_dir,
    default_start_menu_dir,
    default_user_data_root,
    get_desktop_status,
    install_desktop_app,
    register_os_integration,
    uninstall_desktop_app,
    unregister_os_integration,
)
from forge.http_base import LoopbackHTTPServer
from forge.models import ForkProfile
from forge.studio import make_studio_handler

FORGE_ROOT = Path(__file__).resolve().parent.parent


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _http_req(
    method: str,
    url: str,
    body: dict[str, object] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, object]]:
    hdrs = dict(headers or {})
    data = None
    if body is not None:
        hdrs["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        raw = err.read().decode("utf-8", errors="replace")
        return err.code, json.loads(raw) if raw.startswith("{") else {"error": raw}


class _MockRegistry:
    """Isolated in-memory HKCU registry mock so tests never touch the developer's Windows Registry."""

    def __init__(self) -> None:
        self.store: dict[str, dict[str, str | int]] = {}

    def set_values(self, subkey: str, values: dict[str, str | int]) -> None:
        bucket = self.store.setdefault(subkey.lower(), {})
        for k, v in values.items():
            bucket[k] = v

    def get_value(self, subkey: str, name: str) -> str | int | None:
        return self.store.get(subkey.lower(), {}).get(name)

    def delete_value(self, subkey: str, name: str) -> None:
        bucket = self.store.get(subkey.lower())
        if bucket is not None:
            bucket.pop(name, None)

    def delete_tree(self, subkey: str) -> None:
        low = subkey.lower()
        prefix = low + "\\"
        for k in [k for k in self.store if k == low or k.startswith(prefix)]:
            del self.store[k]


class TestDesktopApplication(unittest.TestCase):
    def test_default_path_helpers_and_registry_roundtrip(self) -> None:
        self.assertEqual(default_install_dir().name, "Luminara Browser")
        self.assertEqual(default_user_data_root().name, "Luminara Browser")
        self.assertTrue(str(default_start_menu_dir()).endswith("Programs"))
        self.assertEqual(default_desktop_dir().name, "Desktop")
        self.assertIsInstance(WinRegBackend(), WinRegBackend)

        reg = _MockRegistry()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            inst = Path(tmp) / "Install"
            exe = inst / DESKTOP_EXE_NAME
            inst.mkdir(parents=True)
            exe.write_bytes(b"MZ" + b"\x00" * 128)
            written = register_os_integration(inst, exe, estimated_kb=512, registry_backend=reg)
            self.assertIn(UNINSTALL_SUBKEY, written)
            self.assertEqual(reg.get_value(UNINSTALL_SUBKEY, "DisplayName"), "Luminara Browser")
            self.assertEqual(reg.get_value("Software\\Classes\\luminara", "URL Protocol"), "")
            self.assertIn("--uninstall --quiet", str(reg.get_value(UNINSTALL_SUBKEY, "QuietUninstallString")))
            unregister_os_integration(registry_backend=reg)
            self.assertIsNone(reg.get_value(UNINSTALL_SUBKEY, "DisplayName"))
            self.assertIsNone(reg.get_value("Software\\Classes\\luminara", "URL Protocol"))
            self.assertIsNone(reg.get_value("Software\\RegisteredApplications", "LuminaraBrowser"))

    def test_create_windows_shortcut_with_app_user_model_id(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            target = root / DESKTOP_EXE_NAME
            target.write_bytes(b"MZ")
            lnk = root / "StartMenu" / "Luminara Browser.lnk"
            created = create_windows_shortcut(lnk, target, app_user_model_id=APP_USER_MODEL_ID)
            self.assertTrue(created.is_file())
            raw = created.read_bytes()
            if os.name == "nt":
                # Standard MS-SHLLINK magic header (HeaderSize = 0x0000004C) + embedded UTF-16LE AUMID
                self.assertEqual(raw[:4], b"\x4c\x00\x00\x00")
                self.assertIn(APP_USER_MODEL_ID.encode("utf-16le"), raw)
            else:
                self.assertIn(APP_USER_MODEL_ID.encode("utf-8"), raw)

    def test_per_user_install_upgrade_and_uninstall_lifecycle(self) -> None:
        reg = _MockRegistry()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            src = root / "portable_src"
            (src / "App").mkdir(parents=True)
            (src / "Agent" / "forge").mkdir(parents=True)
            (src / "App" / "chrome.exe").write_bytes(b"MZ")
            (src / DESKTOP_EXE_NAME).write_bytes(b"MZ")
            ForkProfile().save(src / "Agent" / "fork.json")
            (src / "Launch-luminara-browser.cmd").write_text("@echo off\r\n", encoding="utf-8")

            inst_dir = root / "LocalAppData" / "Programs" / "Luminara Browser"
            data_root = root / "LocalAppData" / "Luminara Browser"
            sm_dir = root / "StartMenu"
            dt_dir = root / "Desktop"

            # 1. Dry-run creates nothing
            dry = install_desktop_app(
                src,
                install_dir=inst_dir,
                user_data_root=data_root,
                start_menu_dir=sm_dir,
                desktop_dir=dt_dir,
                dry_run=True,
                registry_backend=reg,
            )
            self.assertTrue(dry["ok"] and dry["dry_run"])
            self.assertFalse(inst_dir.exists())

            # 2. Real per-user install
            res = install_desktop_app(
                src,
                install_dir=inst_dir,
                user_data_root=data_root,
                start_menu_dir=sm_dir,
                desktop_dir=dt_dir,
                registry_backend=reg,
            )
            self.assertTrue(res["ok"])
            self.assertTrue((inst_dir / DESKTOP_EXE_NAME).is_file())
            self.assertTrue((inst_dir / INSTALL_MANIFEST_NAME).is_file())
            self.assertTrue((sm_dir / "Luminara Browser.lnk").is_file())
            self.assertTrue((dt_dir / "Luminara Browser.lnk").is_file())
            self.assertEqual(reg.get_value(UNINSTALL_SUBKEY, "DisplayName"), "Luminara Browser")

            # Verify status inspection reflects installed state
            st = get_desktop_status(FORGE_ROOT, install_dir=inst_dir, registry_backend=reg)
            self.assertTrue(st["installed"]["is_installed"])
            self.assertTrue(st["installed"]["apps_and_features_registered"])
            self.assertTrue(st["installed"]["protocol_registered"])

            # 3. Seed user profile & vault data, then upgrade -> user data MUST survive intact
            bookmarks = data_root / "User Data" / "Bookmarks"
            bookmarks.write_text('{"roots":{"bookmark_bar":"preserved"}}', encoding="utf-8")
            vault_marker = data_root / "AgentData" / "outputs" / "vault.json"
            vault_marker.parent.mkdir(parents=True, exist_ok=True)
            vault_marker.write_text('{"entries":[]}', encoding="utf-8")

            upg = install_desktop_app(
                src,
                install_dir=inst_dir,
                user_data_root=data_root,
                start_menu_dir=sm_dir,
                desktop_dir=dt_dir,
                app_version="3.2.1",
                registry_backend=reg,
            )
            self.assertEqual(upg["manifest"]["app_version"], "3.2.1")
            self.assertTrue(bookmarks.is_file())
            self.assertTrue(vault_marker.is_file())

            # 4. Uninstall preserving user data
            un_keep = uninstall_desktop_app(
                install_dir=inst_dir,
                user_data_root=data_root,
                start_menu_dir=sm_dir,
                desktop_dir=dt_dir,
                purge_data=False,
                registry_backend=reg,
            )
            self.assertTrue(un_keep["ok"])
            self.assertFalse(inst_dir.exists())
            self.assertFalse((sm_dir / "Luminara Browser.lnk").exists())
            self.assertFalse((dt_dir / "Luminara Browser.lnk").exists())
            self.assertIsNone(reg.get_value(UNINSTALL_SUBKEY, "DisplayName"))
            self.assertTrue(bookmarks.is_file())
            self.assertFalse(un_keep["purged_user_data"])

            # 5. Reinstall & uninstall with purge_data=True -> removes user data too
            install_desktop_app(
                src,
                install_dir=inst_dir,
                user_data_root=data_root,
                start_menu_dir=sm_dir,
                desktop_dir=dt_dir,
                registry_backend=reg,
            )
            un_purge = uninstall_desktop_app(
                install_dir=inst_dir,
                user_data_root=data_root,
                start_menu_dir=sm_dir,
                desktop_dir=dt_dir,
                purge_data=True,
                registry_backend=reg,
            )
            self.assertTrue(un_purge["purged_user_data"])
            self.assertFalse(data_root.exists())

    def test_daemon_desktop_heartbeat_takeover_and_graceful_shutdown(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            ForkProfile().save(root / "fork.json")
            agent_port = _free_port()
            cdp_port = _free_port()
            rt = LuminaraAgentRuntime(forge_root=root, cdp_host="127.0.0.1", cdp_port=cdp_port)
            rt.cdp.leases.acquire("tab-alpha", "agent-x", ttl_sec=60.0, purpose="test")
            rt.cdp.leases.acquire("tab-beta", "agent-y", ttl_sec=60.0, purpose="test")

            srv = create_agent_http_server(rt, host="127.0.0.1", port=agent_port)
            t = threading.Thread(target=srv.serve_forever, daemon=True)
            t.start()
            base = f"http://127.0.0.1:{agent_port}"
            ui_hdr = {"X-Luminara-UI-Key": rt.local_ui_key}
            try:
                # Heartbeat reports active leases accurately
                st_code, hb = _http_req("GET", f"{base}/api/agent/desktop/status", headers=ui_hdr)
                self.assertEqual(st_code, 200)
                self.assertTrue(hb["ok"])
                self.assertEqual(hb["active_leases_count"], 2)
                self.assertGreater(int(hb["daemon_pid"]), 0)

                # Unauthenticated takeover & shutdown are strictly rejected (403)
                code_no_auth_to, _ = _http_req("POST", f"{base}/api/agent/desktop/takeover", {})
                self.assertEqual(code_no_auth_to, 403)
                code_no_auth_sd, _ = _http_req("POST", f"{base}/api/agent/shutdown", {})
                self.assertEqual(code_no_auth_sd, 403)

                # Direct helper unit checks
                direct_hb = build_desktop_heartbeat(rt, time.time() - 5.0)
                self.assertEqual(direct_hb["active_leases_count"], 2)

                # Authenticated takeover preempts all leases
                code_to, to_res = _http_req("POST", f"{base}/api/agent/desktop/takeover", {}, headers=ui_hdr)
                self.assertEqual(code_to, 200)
                self.assertEqual(to_res["preempted_count"], 2)
                self.assertEqual(rt.cdp.leases.list_active(), [])

                # Direct trigger_desktop_takeover when empty returns 0 cleanly
                self.assertEqual(trigger_desktop_takeover(rt)["preempted_count"], 0)

                # Authenticated shutdown cleanly stops server thread
                code_sd, sd_res = _http_req("POST", f"{base}/api/agent/shutdown", {"close_browser": False}, headers=ui_hdr)
                self.assertEqual(code_sd, 200)
                self.assertTrue(sd_res["shutting_down"])
                t.join(timeout=3.0)
                self.assertFalse(t.is_alive(), "Agent server thread failed to stop cleanly on /api/agent/shutdown")
            finally:
                initiate_graceful_shutdown(rt, srv)
                t.join(timeout=3.0)
                srv.server_close()

    @unittest.skipUnless(os.name == "nt" and shutil.which("cargo"), "Requires Windows with Rust toolchain")
    def test_compiled_native_desktop_host_pe_cli_and_live_ipc_shutdown(self) -> None:
        crate_dir = find_desktop_crate_dir(FORGE_ROOT)
        self.assertIsNotNone(crate_dir)
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            stage_dir = Path(tmp) / "stage"
            built = build_desktop_host(FORGE_ROOT, dest_dir=stage_dir, release=True)
            self.assertTrue(built["ok"])
            exe = stage_dir / DESKTOP_EXE_NAME
            pe = inspect_pe_desktop_binary(exe)
            self.assertTrue(pe["valid_pe"])
            self.assertEqual(pe["architecture"], "x64")
            self.assertTrue(pe["is_windows_gui"], "LuminaraBrowser.exe must be WINDOWS_GUI (zero console flash)")
            self.assertTrue(pe["has_icon_group"])
            self.assertTrue(pe["has_version_info"])
            self.assertTrue(pe["version_mentions_luminara"])
            self.assertTrue(pe["has_manifest"])
            self.assertTrue(pe["manifest_per_monitor_v2"])
            self.assertTrue(pe["manifest_as_invoker"])

            ver_proc = subprocess.run([str(exe), "--version"], capture_output=True, text=True, timeout=10, check=True)
            self.assertIn("Luminara Browser Desktop Host", ver_proc.stdout)

            diag_proc = subprocess.run([str(exe), "--diagnostics"], capture_output=True, text=True, timeout=10, check=True)
            diag = json.loads(diag_proc.stdout)
            self.assertEqual(diag["app_user_model_id"], APP_USER_MODEL_ID)
            self.assertEqual(diag["mode"], "portable")

            # CLI dry-run smoke test
            rc = forge_cli_main(["--forge-root", str(FORGE_ROOT), "desktop-status"])
            self.assertEqual(rc, 0)

            # Live native supervisor + single-instance Named Pipe IPC (`--quit`) + zero-orphan exit test
            real_chrome = FORGE_ROOT / "dist" / "luminara-browser-win64" / "App" / "chrome.exe"
            if real_chrome.is_file():
                bundle = Path(tmp) / "live_bundle"
                app_dir = bundle / "App"
                app_dir.mkdir(parents=True)
                (bundle / "Agent").mkdir(parents=True)
                shutil.copy2(exe, bundle / DESKTOP_EXE_NAME)
                # Hardlink read-only Chromium runtime binaries (0 disk bytes, leaves real dist/App untouched!)
                for item in real_chrome.parent.iterdir():
                    if item.is_file():
                        try:
                            os.link(item, app_dir / item.name)
                        except OSError:
                            shutil.copy2(item, app_dir / item.name)
                if (real_chrome.parent / "locales").is_dir():
                    subprocess.run(
                        ["cmd.exe", "/c", "mklink", "/J", str(app_dir / "locales"), str(real_chrome.parent / "locales")],
                        capture_output=True,
                        check=True,
                    )
                shutil.copytree(
                    FORGE_ROOT / "forge",
                    bundle / "Agent" / "forge",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
                )
                ep_agent = _free_port()
                ep_cdp = _free_port()
                prof = ForkProfile(
                    agent_port=ep_agent,
                    cdp_port=ep_cdp,
                    extra_cli_switches=["--headless=new", "--disable-gpu"],
                )
                prof.save(bundle / "Agent" / "fork.json")

                iso_env = {**os.environ, "USERPROFILE": str(Path(tmp) / "fake_home")}
                (Path(tmp) / "fake_home").mkdir(parents=True, exist_ok=True)
                primary = subprocess.Popen([str(bundle / DESKTOP_EXE_NAME), "--portable", "--no-tray"], env=iso_env)
                try:
                    # Wait for supervised Agent Daemon + headless Chromium CDP readiness
                    ready_hb: dict[str, object] = {}
                    deadline = time.time() + 20.0
                    while time.time() < deadline:
                        try:
                            key_path = bundle / "Agent" / "outputs" / "local_ui_key.txt"
                            key_val = key_path.read_text(encoding="utf-8").strip() if key_path.is_file() else ""
                            code, hb = _http_req(
                                "GET",
                                f"http://127.0.0.1:{ep_agent}/api/agent/desktop/status",
                                headers={"X-Luminara-UI-Key": key_val} if key_val else {},
                            )
                            if code == 200 and hb.get("cdp_connected"):
                                ready_hb = hb
                                break
                        except Exception:  # noqa: BLE001
                            pass
                        time.sleep(0.25)

                    self.assertTrue(ready_hb.get("ok"), "Supervised Agent Daemon failed to come online")
                    self.assertTrue(ready_hb.get("cdp_connected"), "Supervised headless Chromium failed to connect CDP")
                    self.assertTrue((bundle / "Logs" / "host.log").is_file())
                    self.assertTrue((bundle / "Logs" / "daemon.log").is_file())

                    # Send --quit via secondary LuminaraBrowser.exe over Named Pipe IPC!
                    sec = subprocess.run(
                        [str(bundle / DESKTOP_EXE_NAME), "--portable", "--quit"],
                        env=iso_env,
                        capture_output=True,
                        timeout=10,
                        check=False,
                    )
                    self.assertEqual(sec.returncode, 0)
                    primary.wait(timeout=12)
                    self.assertEqual(primary.returncode, 0)

                    # Verify zero orphan daemon remains listening on ep_agent
                    time.sleep(0.4)
                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                        probe.settimeout(0.5)
                        err = probe.connect_ex(("127.0.0.1", ep_agent))
                        self.assertNotEqual(err, 0, "Orphan Agent Daemon still listening after --quit!")
                finally:
                    if primary.poll() is None:
                        primary.terminate()
                        primary.wait(timeout=5)
                    if (app_dir / "locales").exists():
                        subprocess.run(["cmd.exe", "/c", "rmdir", str(app_dir / "locales")], capture_output=True, check=False)

    def test_pe_header_edge_cases_and_atomic_copy(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            self.assertFalse(inspect_pe_desktop_binary(root / "missing.exe")["present"])

            bad_mz = root / "bad_mz.exe"
            bad_mz.write_bytes(b"NOPE")
            self.assertEqual(inspect_pe_desktop_binary(bad_mz)["error"], "Missing MZ header")

            no_pe = root / "no_pe.exe"
            buf = bytearray(128)
            buf[:2] = b"MZ"
            struct.pack_into("<I", buf, 0x3C, 64)
            no_pe.write_bytes(bytes(buf))
            self.assertEqual(inspect_pe_desktop_binary(no_pe)["error"], "Missing PE signature")

            trunc_opt = root / "trunc_opt.exe"
            buf2 = bytearray(100)
            buf2[:2] = b"MZ"
            struct.pack_into("<I", buf2, 0x3C, 64)
            buf2[64:68] = b"PE\x00\x00"
            struct.pack_into("<HHIIIHH", buf2, 68, 0x8664, 1, 0, 0, 0, 240, 0)
            trunc_opt.write_bytes(bytes(buf2))
            self.assertEqual(inspect_pe_desktop_binary(trunc_opt)["error"], "Truncated optional header")

            src_bin = root / "src.exe"
            dst_bin = root / "nested" / "dst.exe"
            src_bin.write_bytes(b"MZ-PAYLOAD-V1")
            _atomic_copy_exe(src_bin, dst_bin)
            self.assertEqual(dst_bin.read_bytes(), b"MZ-PAYLOAD-V1")
            src_bin.write_bytes(b"MZ-PAYLOAD-V2")
            _atomic_copy_exe(src_bin, dst_bin)
            self.assertEqual(dst_bin.read_bytes(), b"MZ-PAYLOAD-V2")

    def test_mta_thread_shortcut_and_installer_hardening_edges(self) -> None:
        reg = _MockRegistry()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            target = root / DESKTOP_EXE_NAME
            target.write_bytes(b"MZ")
            lnk = root / "MTA" / "Luminara Browser.lnk"

            # Verify shortcut creation inside an MTA-initialized worker thread + read-only overwrite
            err_holder: list[Exception] = []

            def _mta_worker() -> None:
                uninit = False
                if os.name == "nt":
                    hr = ctypes.windll.ole32.CoInitializeEx(None, 0x0)  # COINIT_MULTITHREADED
                    uninit = hr >= 0
                try:
                    create_windows_shortcut(lnk, target, app_user_model_id=APP_USER_MODEL_ID)
                    os.chmod(lnk, stat.S_IREAD)
                    create_windows_shortcut(lnk, target, app_user_model_id=APP_USER_MODEL_ID)
                except Exception as exc:  # noqa: BLE001
                    err_holder.append(exc)
                finally:
                    if uninit:
                        ctypes.windll.ole32.CoUninitialize()

            t = threading.Thread(target=_mta_worker)
            t.start()
            t.join(timeout=10.0)
            self.assertEqual(err_holder, [])
            self.assertTrue(lnk.is_file())
            os.chmod(lnk, stat.S_IWRITE)

            # Overlapping source/install paths must raise ValueError; in-place src == dst succeeds
            src = root / "portable_bundle"
            (src / "App").mkdir(parents=True)
            (src / "Agent" / "forge").mkdir(parents=True)
            ro_dll = src / "App" / "chrome.exe"
            ro_dll.write_bytes(b"MZ")
            os.chmod(ro_dll, stat.S_IREAD)
            (src / DESKTOP_EXE_NAME).write_bytes(b"MZ")
            ForkProfile(slug="custom-fork").save(src / "Agent" / "fork.json")
            ForkProfile(slug="custom-fork").save(root / "fork.json")

            with self.assertRaises(ValueError):
                install_desktop_app(src, install_dir=src / "SubInstall", registry_backend=reg)

            inplace = install_desktop_app(
                src,
                install_dir=src,
                user_data_root=root / "InplaceData",
                create_desktop_shortcut=False,
                create_start_menu=False,
                register_os=False,
                registry_backend=reg,
            )
            self.assertTrue(inplace["ok"])

            # Install + upgrade + dry-run uninstall + purge uninstall with read-only files
            inst_dir = root / "InstalledApp"
            data_root = root / "InstalledData"
            install_desktop_app(
                src,
                install_dir=inst_dir,
                user_data_root=data_root,
                create_desktop_shortcut=False,
                create_start_menu=False,
                registry_backend=reg,
            )
            os.chmod(inst_dir / "App" / "chrome.exe", stat.S_IREAD)
            ro_pref = data_root / "User Data" / "Preferences"
            ro_pref.write_text("{}", encoding="utf-8")
            os.chmod(ro_pref, stat.S_IREAD)

            # Custom ForkProfile slug reflected in get_desktop_status
            st = get_desktop_status(root, install_dir=inst_dir, registry_backend=reg)
            self.assertTrue(str(st["portable"]["dist_dir"]).endswith("custom-fork-win64"))

            # Upgrade overwrites read-only App/chrome.exe without PermissionError
            install_desktop_app(
                src,
                install_dir=inst_dir,
                user_data_root=data_root,
                app_version="4.0.0",
                create_desktop_shortcut=False,
                create_start_menu=False,
                registry_backend=reg,
            )

            dry_un = uninstall_desktop_app(
                install_dir=inst_dir,
                user_data_root=data_root,
                dry_run=True,
                purge_data=True,
                registry_backend=reg,
            )
            self.assertTrue(dry_un["dry_run"] and inst_dir.is_dir())

            real_un = uninstall_desktop_app(
                install_dir=inst_dir,
                user_data_root=data_root,
                purge_data=True,
                registry_backend=reg,
            )
            self.assertTrue(real_un["removed_install_dir"] and real_un["purged_user_data"])
            os.chmod(ro_dll, stat.S_IWRITE)

            # Deferred cleanup refuses shallow paths and safely removes deep path containing '&' and '%TEMP%'
            self.assertFalse(_schedule_deferred_dir_cleanup(Path(root.anchor) / "LuminaraShallow"))
            tricky = root / "deep" / "sub" / "Dir & %TEMP% Test"
            tricky.mkdir(parents=True)
            (tricky / "file.txt").write_text("x", encoding="utf-8")
            if os.name == "nt":
                self.assertTrue(_schedule_deferred_dir_cleanup(tricky))
                deadline = time.time() + 5.0
                while tricky.exists() and time.time() < deadline:
                    time.sleep(0.2)
                self.assertFalse(tricky.exists())

    def test_unleased_last_actor_takeover_alert_precedence_and_passport_auth(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            ForkProfile().save(root / "fork.json")
            rt = LuminaraAgentRuntime(forge_root=root, cdp_host="127.0.0.1", cdp_port=_free_port())
            try:
                # 1. Unleased agent checks tab -> human takeover preempts _last_actor -> next check raises PersonControlError once
                rt.cdp.leases.check_allowed("tab-unleased", "agent-fast")
                to_res = trigger_desktop_takeover(rt)
                self.assertIn("tab-unleased", to_res["preempted_tabs"])
                with self.assertRaises(PersonControlError):
                    rt.cdp.leases.check_allowed("tab-unleased", "agent-fast")
                # Cleared after single notification
                rt.cdp.leases.check_allowed("tab-unleased", "agent-fast")

                # 2. Alert precedence (handoff > sequence > mutation) + secret redaction
                with (
                    mock.patch.object(
                        rt.goals,
                        "list_handoffs",
                        return_value=[{"run_id": "r1", "reason": "Bearer sk-proj-1234567890abcdefghijklmnop"}],
                    ),
                    mock.patch.object(rt.sequence_guard, "status", return_value={"active_blocks": [{"rule_id": "seq-1"}]}),
                    mock.patch.object(
                        rt.mutation_firewall,
                        "list_pending",
                        return_value=[{"request_id": "m1", "method": "POST", "url": "https://example.com/pay"}],
                    ),
                ):
                    hb1 = build_desktop_heartbeat(rt, time.time() - 2.0)
                    self.assertEqual(hb1["alert_id"], "handoff:r1")
                    self.assertNotIn("sk-proj-1234567890", hb1["alert_body"])

                with (
                    mock.patch.object(rt.goals, "list_handoffs", return_value=[]),
                    mock.patch.object(rt.sequence_guard, "status", return_value={"active_blocks": [{"rule_id": "seq-1"}]}),
                    mock.patch.object(
                        rt.mutation_firewall,
                        "list_pending",
                        return_value=[{"request_id": "m1", "method": "POST", "url": "https://example.com/pay"}],
                    ),
                ):
                    hb2 = build_desktop_heartbeat(rt, time.time() - 2.0)
                    self.assertEqual(hb2["alert_id"], "seq:seq-1:1")

                with (
                    mock.patch.object(rt.goals, "list_handoffs", return_value=[]),
                    mock.patch.object(rt.sequence_guard, "status", return_value={"active_blocks": []}),
                    mock.patch.object(
                        rt.mutation_firewall,
                        "list_pending",
                        return_value=[{"request_id": "m1", "method": "POST", "url": "https://example.com/pay"}],
                    ),
                ):
                    hb3 = build_desktop_heartbeat(rt, time.time() - 2.0)
                    self.assertEqual(hb3["alert_id"], "mutation:m1")

                # 3. Passport Mode: Bearer token can read desktop/status, NEVER trigger takeover or shutdown!
                port = _free_port()
                with mock.patch.dict(os.environ, {"LUMINARA_AGENT_TOKEN": "passport-secret-xyz"}):
                    rt_pass = LuminaraAgentRuntime(forge_root=root, cdp_host="127.0.0.1", cdp_port=_free_port())
                    srv = create_agent_http_server(rt_pass, host="127.0.0.1", port=port)
                    th = threading.Thread(target=srv.serve_forever, daemon=True)
                    th.start()
                    base = f"http://127.0.0.1:{port}"
                    bearer = {"Authorization": "Bearer passport-secret-xyz"}
                    ui_hdr = {"X-Luminara-UI-Key": rt_pass.local_ui_key}
                    try:
                        c_unauth, _ = _http_req("GET", f"{base}/api/agent/desktop/status")
                        self.assertEqual(c_unauth, 401)
                        c_bearer_st, _ = _http_req("GET", f"{base}/api/agent/desktop/status", headers=bearer)
                        self.assertEqual(c_bearer_st, 200)
                        c_ui_st, _ = _http_req("GET", f"{base}/api/agent/desktop/status", headers=ui_hdr)
                        self.assertEqual(c_ui_st, 200)
                        c_bearer_to, _ = _http_req("POST", f"{base}/api/agent/desktop/takeover", {}, headers=bearer)
                        self.assertEqual(c_bearer_to, 403)
                        c_bearer_sd, _ = _http_req("POST", f"{base}/api/agent/shutdown", {}, headers=bearer)
                        self.assertEqual(c_bearer_sd, 403)
                    finally:
                        srv.shutdown()
                        th.join(timeout=3.0)
                        srv.server_close()
                        rt_pass.close()
            finally:
                rt.close()

    def test_studio_desktop_routes_csrf_and_ui_key_enforcement(self) -> None:
        reg = _MockRegistry()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            forge_dir = root / "forge_state"
            forge_dir.mkdir(parents=True)
            ForkProfile().save(forge_dir / "fork.json")
            dist_src = forge_dir / "dist" / "luminara-browser-win64"
            (dist_src / "App").mkdir(parents=True)
            (dist_src / "Agent" / "forge").mkdir(parents=True)
            (dist_src / "App" / "chrome.exe").write_bytes(b"MZ")
            (dist_src / DESKTOP_EXE_NAME).write_bytes(b"MZ")
            ForkProfile().save(dist_src / "Agent" / "fork.json")

            inst_dir = root / "StudioInstall"
            data_dir = root / "StudioData"
            sm_dir = root / "StudioStartMenu"
            dt_dir = root / "StudioDesktop"

            port = _free_port()
            handler = make_studio_handler(
                forge_dir,
                root / "missing_core",
                root / "missing_win",
                install_dir=inst_dir,
                user_data_root=data_dir,
                start_menu_dir=sm_dir,
                desktop_dir=dt_dir,
                registry_backend=reg,
            )
            srv = LoopbackHTTPServer(("127.0.0.1", port), handler)
            th = threading.Thread(target=srv.serve_forever, daemon=True)
            th.start()
            base = f"http://127.0.0.1:{port}"
            try:
                st_code, state = _http_req("GET", f"{base}/api/state")
                self.assertEqual(st_code, 200)
                ui_key = str(state.get("ui_key") or "")
                self.assertTrue(len(ui_key) >= 32)
                self.assertFalse(state["desktop_status"]["installed"]["is_installed"])

                # Missing UI key -> 403
                c_no_key, _ = _http_req("POST", f"{base}/api/install-desktop", {})
                self.assertEqual(c_no_key, 403)
                c_no_key_un, _ = _http_req("POST", f"{base}/api/uninstall-desktop", {})
                self.assertEqual(c_no_key_un, 403)

                # Cross-port unkeyed localhost Origin & cross-site Origin (even with UI key) -> 403
                c_cross_port, _ = _http_req(
                    "POST",
                    f"{base}/api/compile",
                    {},
                    headers={"Origin": "http://127.0.0.1:3000"},
                )
                self.assertEqual(c_cross_port, 403)
                c_evil_origin, _ = _http_req(
                    "POST",
                    f"{base}/api/install-desktop",
                    {},
                    headers={"X-Luminara-UI-Key": ui_key, "Origin": "https://evil.example"},
                )
                self.assertEqual(c_evil_origin, 403)

                # Valid UI key + matching/absent Origin -> 200 install & uninstall
                c_ok, inst_res = _http_req(
                    "POST",
                    f"{base}/api/install-desktop",
                    {"create_desktop_shortcut": False, "create_start_menu": False},
                    headers={"X-Luminara-UI-Key": ui_key, "Origin": base},
                )
                self.assertEqual(c_ok, 200)
                self.assertTrue(inst_res["desktop_status"]["installed"]["is_installed"])

                c_un_ok, un_res = _http_req(
                    "POST",
                    f"{base}/api/uninstall-desktop",
                    {"purge_data": True},
                    headers={"X-Luminara-UI-Key": ui_key},
                )
                self.assertEqual(c_un_ok, 200)
                self.assertFalse(un_res["desktop_status"]["installed"]["is_installed"])
            finally:
                srv.shutdown()
                th.join(timeout=3.0)
                srv.server_close()

    def test_cloudflare_worker_and_portal_desktop_contracts(self) -> None:
        repo_root = FORGE_ROOT.parent
        worker_js = (repo_root / "cloudflare" / "src" / "worker.js").read_text(encoding="utf-8")
        portal_html = (repo_root / "cloudflare" / "public" / "index.html").read_text(encoding="utf-8")
        for token in (
            '"LuminaraBrowser.exe"',
            '"Luminara.Browser.Desktop"',
            '"/api/agent/desktop/status"',
            '"/api/agent/desktop/takeover"',
            '"/api/agent/shutdown"',
            "luminara-forge install-desktop",
        ):
            self.assertIn(token, worker_js)
        self.assertIn("LuminaraBrowser.exe", portal_html)
        self.assertNotIn(".innerHTML", portal_html)
        self.assertNotIn("<script>", portal_html)


if __name__ == "__main__":
    unittest.main()
