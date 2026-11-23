"""Per-User Windows Desktop Installer, Uninstaller, Shortcuts & Registry Manager (`forge/desktop_installer.py`).

Industry-grade zero-UAC Windows installation architecture:
- Installs binaries into `%LOCALAPPDATA%\\Programs\\Luminara Browser` while separating persistent
  user profile & agent data into `%LOCALAPPDATA%\\Luminara Browser\\{User Data,AgentData,Logs}`
  so upgrades never wipe bookmarks, vault secrets, playbooks, or ledgers.
- Preserves 100% Portable mode whenever launched without `install_manifest.json` (`mode: "installed"`).
- Creates native `.lnk` Start Menu & Desktop shortcuts via Win32 COM (`IShellLinkW` + `IPropertyStore`
  setting `System.AppUserModel.ID = "Luminara.Browser.Desktop"`) safely across STA and MTA threads.
- Registers Windows Apps & Features (`HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\LuminaraBrowser`)
  plus optional Default Browser capabilities and `luminara://` custom URI protocol handler.
"""

from __future__ import annotations

import ctypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import threading
from typing import Any

from .desktop_build import DESKTOP_EXE_NAME, _atomic_copy_exe, inspect_pe_desktop_binary, stage_prebuilt_desktop_host
from .mcp_specs import APP_VERSION
from .models import ForkProfile

ENCODING = "utf-8"
APP_USER_MODEL_ID = "Luminara.Browser.Desktop"
PRODUCT_NAME = "Luminara Browser"
PUBLISHER_NAME = "Luminara Engineering"
UNINSTALL_SUBKEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\LuminaraBrowser"
CLIENT_SUBKEY = r"Software\Clients\StartMenuInternet\LuminaraBrowser"
REGISTERED_APPS_SUBKEY = r"Software\RegisteredApplications"
PROGID_HTML = "LuminaraHTML"
PROTOCOL_SCHEME = "luminara"
INSTALL_MANIFEST_NAME = "install_manifest.json"
RPC_E_CHANGED_MODE_SIGNED = -2147417850


def _rmtree_force(path: Path) -> None:
    """Remove `path` recursively, clearing read-only attributes without deprecated rmtree args."""
    if not path.exists():
        return

    def _clear_ro(fn: Any, target: str, _exc: Any) -> None:
        try:
            os.chmod(target, stat.S_IWRITE)
        except OSError:
            pass
        fn(target)

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_clear_ro)
    else:
        shutil.rmtree(path, onerror=_clear_ro)


def _copy2_force(src_file: str | os.PathLike[str], dst_file: str | os.PathLike[str]) -> str:
    """Copy `src_file` to `dst_file`, clearing read-only attributes on existing destination files first."""
    dst_path = Path(dst_file)
    if dst_path.exists():
        try:
            os.chmod(dst_path, stat.S_IWRITE)
        except OSError:
            pass
    return shutil.copy2(src_file, dst_file)


class WinRegBackend:
    """Thin HKCU registry adapter (abstracted so tests can supply an isolated in-memory mock)."""

    def set_values(self, subkey: str, values: dict[str, str | int]) -> None:
        if os.name != "nt":
            return
        import winreg

        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, subkey, 0, winreg.KEY_SET_VALUE) as key:
            for name, val in values.items():
                if isinstance(val, int):
                    winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, val)
                else:
                    winreg.SetValueEx(key, name, 0, winreg.REG_SZ, str(val))

    def get_value(self, subkey: str, name: str) -> str | int | None:
        if os.name != "nt":
            return None
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, subkey, 0, winreg.KEY_QUERY_VALUE) as key:
                val, _ = winreg.QueryValueEx(key, name)
                return val
        except OSError:
            return None

    def delete_value(self, subkey: str, name: str) -> None:
        if os.name != "nt":
            return
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, subkey, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, name)
        except OSError:
            pass

    def delete_tree(self, subkey: str) -> None:
        if os.name != "nt":
            return
        import winreg

        def _rec(path: str) -> None:
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_ALL_ACCESS) as key:
                    while True:
                        try:
                            child = winreg.EnumKey(key, 0)
                        except OSError:
                            break
                        _rec(f"{path}\\{child}")
            except OSError:
                return
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
            except OSError:
                pass

        _rec(subkey)


def default_install_dir() -> Path:
    local_app = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    return (local_app / "Programs" / PRODUCT_NAME).resolve()


def default_user_data_root() -> Path:
    local_app = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    return (local_app / PRODUCT_NAME).resolve()


def default_start_menu_dir() -> Path:
    app_data = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
    return (app_data / "Microsoft" / "Windows" / "Start Menu" / "Programs").resolve()


def default_desktop_dir() -> Path:
    return (Path.home() / "Desktop").resolve()


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def from_parts(cls, d1: int, d2: int, d3: int, d4: bytes) -> "_GUID":
        return cls(d1, d2, d3, (ctypes.c_ubyte * 8)(*d4))


class _PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", _GUID), ("pid", ctypes.c_uint32)]


class _PROPVARIANT_LPWSTR(ctypes.Structure):
    _fields_ = [
        ("vt", ctypes.c_uint16),
        ("wReserved1", ctypes.c_uint16),
        ("wReserved2", ctypes.c_uint16),
        ("wReserved3", ctypes.c_uint16),
        ("pwszVal", ctypes.c_wchar_p),
        ("_pad", ctypes.c_uint64),
    ]


def _com_vtable_fn(obj_ptr: int, index: int, restype: Any, *argtypes: Any) -> Any:
    vtable = ctypes.cast(obj_ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    fn_addr = vtable[index]
    return ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(fn_addr)


def create_windows_shortcut(
    lnk_path: Path,
    target_exe: Path,
    *,
    icon_path: Path | None = None,
    arguments: str = "",
    description: str = "Luminara Browser — Privacy-Hardened Agentic Chromium",
    app_user_model_id: str = APP_USER_MODEL_ID,
) -> Path:
    """Create a Windows `.lnk` shortcut with explicit `System.AppUserModel.ID` via COM (STA & MTA safe)."""
    lnk_path.parent.mkdir(parents=True, exist_ok=True)
    if lnk_path.exists():
        try:
            os.chmod(lnk_path, stat.S_IWRITE)
        except OSError:
            pass
    if os.name != "nt":
        lnk_path.write_text(f"[Shortcut]\nTarget={target_exe}\nAppUserModelID={app_user_model_id}\n", encoding=ENCODING)
        return lnk_path

    ole32 = ctypes.OleDLL("ole32")
    ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    ole32.CoCreateInstance.argtypes = [
        ctypes.POINTER(_GUID),
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(_GUID),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    ole32.CoUninitialize.argtypes = []
    ole32.CoUninitialize.restype = None

    clsid_shell_link = _GUID.from_parts(0x00021401, 0x0000, 0x0000, b"\xC0\x00\x00\x00\x00\x00\x00\x46")
    iid_ishell_link_w = _GUID.from_parts(0x000214F9, 0x0000, 0x0000, b"\xC0\x00\x00\x00\x00\x00\x00\x46")
    iid_iproperty_store = _GUID.from_parts(0x886D8EEB, 0x8CF2, 0x4446, b"\x8D\x02\xCD\xBA\x1D\xBD\xCF\x99")
    iid_ipersist_file = _GUID.from_parts(0x0000010B, 0x0000, 0x0000, b"\xC0\x00\x00\x00\x00\x00\x00\x46")
    pkey_aumid = _PROPERTYKEY(
        _GUID.from_parts(0x9F4C2855, 0x9F79, 0x4B39, b"\xA8\xD0\xE1\xD4\x2D\xE1\xD5\xF3"),
        5,
    )

    try:
        co_init_hr = ole32.CoInitializeEx(None, 0x2)  # COINIT_APARTMENTTHREADED
        need_uninit = co_init_hr in (0, 1)
    except OSError as exc:
        if getattr(exc, "winerror", None) in (RPC_E_CHANGED_MODE_SIGNED, 0x80010106):
            need_uninit = False
        else:
            raise

    sl_ptr = ctypes.c_void_p()
    ps_ptr = ctypes.c_void_p()
    pf_ptr = ctypes.c_void_p()
    try:
        ole32.CoCreateInstance(
            ctypes.byref(clsid_shell_link),
            None,
            1,  # CLSCTX_INPROC_SERVER
            ctypes.byref(iid_ishell_link_w),
            ctypes.byref(sl_ptr),
        )
        sl = sl_ptr.value
        if not sl:
            raise OSError("CoCreateInstance(IShellLinkW) returned NULL")
        _com_vtable_fn(sl, 20, ctypes.HRESULT, ctypes.c_wchar_p)(sl, str(target_exe.resolve()))  # SetPath
        _com_vtable_fn(sl, 9, ctypes.HRESULT, ctypes.c_wchar_p)(sl, str(target_exe.resolve().parent))  # SetWorkingDirectory
        if arguments:
            _com_vtable_fn(sl, 11, ctypes.HRESULT, ctypes.c_wchar_p)(sl, arguments)  # SetArguments
        if description:
            _com_vtable_fn(sl, 7, ctypes.HRESULT, ctypes.c_wchar_p)(sl, description)  # SetDescription
        ico = str((icon_path or target_exe).resolve())
        _com_vtable_fn(sl, 17, ctypes.HRESULT, ctypes.c_wchar_p, ctypes.c_int)(sl, ico, 0)  # SetIconLocation

        qi = _com_vtable_fn(sl, 0, ctypes.HRESULT, ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p))
        if app_user_model_id:
            qi(sl, ctypes.byref(iid_iproperty_store), ctypes.byref(ps_ptr))
            ps = ps_ptr.value
            if not ps:
                raise OSError("QueryInterface(IPropertyStore) returned NULL")
            buf = ctypes.create_unicode_buffer(app_user_model_id)
            pv = _PROPVARIANT_LPWSTR(vt=31, pwszVal=ctypes.cast(buf, ctypes.c_wchar_p))  # VT_LPWSTR
            _com_vtable_fn(
                ps,
                6,
                ctypes.HRESULT,
                ctypes.POINTER(_PROPERTYKEY),
                ctypes.POINTER(_PROPVARIANT_LPWSTR),
            )(ps, ctypes.byref(pkey_aumid), ctypes.byref(pv))  # SetValue
            _com_vtable_fn(ps, 7, ctypes.HRESULT)(ps)  # Commit

        qi(sl, ctypes.byref(iid_ipersist_file), ctypes.byref(pf_ptr))
        pf = pf_ptr.value
        if not pf:
            raise OSError("QueryInterface(IPersistFile) returned NULL")
        _com_vtable_fn(pf, 6, ctypes.HRESULT, ctypes.c_wchar_p, ctypes.c_int)(pf, str(lnk_path.resolve()), 1)  # Save
    finally:
        for ptr in (pf_ptr, ps_ptr, sl_ptr):
            if ptr.value:
                _com_vtable_fn(ptr.value, 2, ctypes.c_uint32)(ptr.value)  # Release
        if need_uninit:
            ole32.CoUninitialize()
    return lnk_path


def _dir_size_kb(root: Path) -> int:
    total = 0
    if not root.exists():
        return 0
    for p in root.rglob("*"):
        if p.is_file():
            try:
                total += p.stat().st_size
            except OSError:
                pass
    return max(1, total // 1024)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def register_os_integration(
    install_dir: Path,
    exe_path: Path,
    *,
    app_version: str = APP_VERSION,
    estimated_kb: int = 0,
    register_browser_protocols: bool = True,
    registry_backend: Any | None = None,
) -> list[str]:
    """Register Luminara Browser in HKCU Apps & Features, Default Apps Capabilities, and `luminara://`."""
    reg = registry_backend or WinRegBackend()
    written_keys: list[str] = []
    exe_str = str(exe_path.resolve())
    inst_str = str(install_dir.resolve())

    reg.set_values(
        UNINSTALL_SUBKEY,
        {
            "DisplayName": PRODUCT_NAME,
            "DisplayVersion": app_version,
            "Publisher": PUBLISHER_NAME,
            "DisplayIcon": f"{exe_str},0",
            "InstallLocation": inst_str,
            "UninstallString": f'"{exe_str}" --uninstall',
            "QuietUninstallString": f'"{exe_str}" --uninstall --quiet',
            "EstimatedSize": max(1, int(estimated_kb)),
            "NoModify": 1,
            "NoRepair": 1,
        },
    )
    written_keys.append(UNINSTALL_SUBKEY)

    if register_browser_protocols:
        proto_key = f"Software\\Classes\\{PROTOCOL_SCHEME}"
        reg.set_values(proto_key, {"": f"URL:{PRODUCT_NAME} Protocol", "URL Protocol": ""})
        reg.set_values(f"{proto_key}\\DefaultIcon", {"": f"{exe_str},0"})
        reg.set_values(f"{proto_key}\\shell\\open\\command", {"": f'"{exe_str}" "%1"'})
        written_keys.append(proto_key)

        html_key = f"Software\\Classes\\{PROGID_HTML}"
        reg.set_values(html_key, {"": f"{PRODUCT_NAME} HTML Document", "AppUserModelID": APP_USER_MODEL_ID})
        reg.set_values(f"{html_key}\\DefaultIcon", {"": f"{exe_str},0"})
        reg.set_values(f"{html_key}\\shell\\open\\command", {"": f'"{exe_str}" "%1"'})
        written_keys.append(html_key)

        reg.set_values(CLIENT_SUBKEY, {"": PRODUCT_NAME})
        reg.set_values(f"{CLIENT_SUBKEY}\\DefaultIcon", {"": f"{exe_str},0"})
        reg.set_values(f"{CLIENT_SUBKEY}\\shell\\open\\command", {"": f'"{exe_str}"'})
        reg.set_values(
            f"{CLIENT_SUBKEY}\\Capabilities",
            {
                "ApplicationName": PRODUCT_NAME,
                "ApplicationDescription": "Privacy-hardened Ungoogled-Chromium engineered for Human + AI Agent co-browsing.",
                "ApplicationIcon": f"{exe_str},0",
            },
        )
        reg.set_values(
            f"{CLIENT_SUBKEY}\\Capabilities\\URLAssociations",
            {"http": PROGID_HTML, "https": PROGID_HTML, PROTOCOL_SCHEME: PROGID_HTML},
        )
        reg.set_values(
            f"{CLIENT_SUBKEY}\\Capabilities\\FileAssociations",
            {".html": PROGID_HTML, ".htm": PROGID_HTML, ".xhtml": PROGID_HTML, ".pdf": PROGID_HTML, ".svg": PROGID_HTML, ".webp": PROGID_HTML},
        )
        reg.set_values(REGISTERED_APPS_SUBKEY, {"LuminaraBrowser": f"{CLIENT_SUBKEY}\\Capabilities"})
        written_keys.extend([CLIENT_SUBKEY, REGISTERED_APPS_SUBKEY])

    return written_keys


def unregister_os_integration(*, registry_backend: Any | None = None) -> list[str]:
    """Remove all HKCU Apps & Features, Default Apps, and `luminara://` registrations."""
    reg = registry_backend or WinRegBackend()
    removed = [
        UNINSTALL_SUBKEY,
        CLIENT_SUBKEY,
        f"Software\\Classes\\{PROGID_HTML}",
        f"Software\\Classes\\{PROTOCOL_SCHEME}",
    ]
    for sub in removed:
        reg.delete_tree(sub)
    reg.delete_value(REGISTERED_APPS_SUBKEY, "LuminaraBrowser")
    return removed


def _best_effort_quit_running_host(exe_path: Path) -> None:
    if os.name != "nt" or not exe_path.is_file():
        return
    try:
        pe = inspect_pe_desktop_binary(exe_path)
        if not pe.get("valid_pe"):
            return
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.run(
            [str(exe_path), "--quit"],
            capture_output=True,
            timeout=5.0,
            creationflags=flags,
            check=False,
        )
    except Exception:  # noqa: BLE001
        pass


def install_desktop_app(
    source_dir: Path,
    *,
    forge_root: Path | None = None,
    install_dir: Path | None = None,
    user_data_root: Path | None = None,
    start_menu_dir: Path | None = None,
    desktop_dir: Path | None = None,
    create_start_menu: bool = True,
    create_desktop_shortcut: bool = True,
    register_os: bool = True,
    register_browser_protocols: bool = True,
    dry_run: bool = False,
    app_version: str = APP_VERSION,
    registry_backend: Any | None = None,
) -> dict[str, Any]:
    """Perform a clean per-user Windows installation preserving existing user data."""
    src = source_dir.resolve()
    if not (src / "App" / "chrome.exe").is_file():
        raise FileNotFoundError(f"Portable Chromium runtime not found in {src / 'App'}")

    src_host = src / DESKTOP_EXE_NAME
    if not src_host.is_file() and forge_root is not None:
        staged = stage_prebuilt_desktop_host(forge_root, src, auto_build=True)
        if staged is not None:
            src_host = staged
    if not src_host.is_file():
        raise FileNotFoundError(
            f"Native desktop host {DESKTOP_EXE_NAME} missing in {src}; use the release bundle or run `python -m forge build-desktop` from a repo checkout"
        )

    dst = (install_dir or default_install_dir()).resolve()
    if src != dst and (dst.is_relative_to(src) or src.is_relative_to(dst)):
        raise ValueError(f"Overlapping source ({src}) and install ({dst}) directories are not permitted")

    data_root = (user_data_root or default_user_data_root()).resolve()
    profile_dir = data_root / "User Data"
    agent_data_dir = data_root / "AgentData"
    sm_dir = (start_menu_dir or default_start_menu_dir()).resolve()
    dt_dir = (desktop_dir or default_desktop_dir()).resolve()
    dst_exe = dst / DESKTOP_EXE_NAME

    planned_shortcuts: list[Path] = []
    if create_start_menu:
        planned_shortcuts.append(sm_dir / f"{PRODUCT_NAME}.lnk")
    if create_desktop_shortcut:
        planned_shortcuts.append(dt_dir / f"{PRODUCT_NAME}.lnk")

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "source_dir": str(src),
            "install_dir": str(dst),
            "exe_path": str(dst_exe),
            "profile_dir": str(profile_dir),
            "agent_data_dir": str(agent_data_dir),
            "shortcuts": [str(p) for p in planned_shortcuts],
            "register_os": register_os,
            "register_browser_protocols": register_browser_protocols,
        }

    _best_effort_quit_running_host(dst_exe)
    dst.mkdir(parents=True, exist_ok=True)
    profile_dir.mkdir(parents=True, exist_ok=True)
    agent_data_dir.mkdir(parents=True, exist_ok=True)
    (data_root / "Logs").mkdir(parents=True, exist_ok=True)

    if src != dst:
        _atomic_copy_exe(src_host, dst_exe)
        for sub in ("App", "Agent", "Runtime"):
            s_sub = src / sub
            if s_sub.is_dir():
                d_sub = dst / sub
                if sub == "Agent" and d_sub.is_dir():
                    _rmtree_force(d_sub)
                shutil.copytree(s_sub, d_sub, dirs_exist_ok=True, copy_function=_copy2_force)
        for shim in src.glob("Launch-*.cmd"):
            _copy2_force(shim, dst / shim.name)
        for ps1 in src.glob("Launch-*.ps1"):
            _copy2_force(ps1, dst / ps1.name)

    src_fork = dst / "Agent" / "fork.json"
    dst_fork = agent_data_dir / "fork.json"
    if src_fork.is_file() and not dst_fork.is_file():
        shutil.copy2(src_fork, dst_fork)

    created_shortcuts: list[str] = []
    for lnk in planned_shortcuts:
        create_windows_shortcut(lnk, dst_exe, icon_path=dst_exe, app_user_model_id=APP_USER_MODEL_ID)
        created_shortcuts.append(str(lnk))

    est_kb = _dir_size_kb(dst)
    reg_keys: list[str] = []
    if register_os:
        reg_keys = register_os_integration(
            dst,
            dst_exe,
            app_version=app_version,
            estimated_kb=est_kb,
            register_browser_protocols=register_browser_protocols,
            registry_backend=registry_backend,
        )

    manifest = {
        "mode": "installed",
        "app_name": PRODUCT_NAME,
        "app_version": app_version,
        "app_user_model_id": APP_USER_MODEL_ID,
        "install_dir": str(dst),
        "exe_path": str(dst_exe),
        "exe_sha256": _sha256_file(dst_exe),
        "profile_dir": str(profile_dir),
        "agent_data_dir": str(agent_data_dir),
        "shortcuts": created_shortcuts,
        "registered_os": register_os,
        "installed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    (dst / INSTALL_MANIFEST_NAME).write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding=ENCODING,
        newline="\n",
    )

    return {
        "ok": True,
        "dry_run": False,
        "manifest": manifest,
        "estimated_size_kb": est_kb,
        "registry_keys": reg_keys,
    }


def _schedule_deferred_dir_cleanup(target_dir: Path) -> bool:
    """When uninstalling from an exe inside `install_dir`, reap locked files via shell-free `sys.argv[1]`."""
    if os.name != "nt":
        return False
    resolved = target_dir.resolve()
    if len(resolved.parts) <= 3 or resolved in (Path.home().resolve(), default_user_data_root()):
        return False
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    script = (
        "import os, shutil, stat, sys, time\n"
        "p = sys.argv[1]\n"
        "def _rw(fn, q, *_): os.chmod(q, stat.S_IWRITE); fn(q)\n"
        "kw = {'onexc': _rw} if sys.version_info >= (3, 12) else {'onerror': _rw}\n"
        "for _ in range(10):\n"
        "    time.sleep(0.5)\n"
        "    if not os.path.isdir(p): break\n"
        "    try: shutil.rmtree(p, **kw); break\n"
        "    except OSError: pass\n"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", script, str(resolved)],
        cwd=os.environ.get("TEMP") or str(Path.home()),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
        close_fds=True,
    )
    threading.Thread(target=proc.wait, daemon=True).start()
    return True


def uninstall_desktop_app(
    *,
    install_dir: Path | None = None,
    user_data_root: Path | None = None,
    start_menu_dir: Path | None = None,
    desktop_dir: Path | None = None,
    purge_data: bool = False,
    unregister_os: bool = True,
    dry_run: bool = False,
    registry_backend: Any | None = None,
) -> dict[str, Any]:
    """Cleanly remove per-user installation, shortcuts, and HKCU registry keys (optionally purging user data)."""
    dst = (install_dir or default_install_dir()).resolve()
    data_root = (user_data_root or default_user_data_root()).resolve()
    sm_lnk = (start_menu_dir or default_start_menu_dir()).resolve() / f"{PRODUCT_NAME}.lnk"
    dt_lnk = (desktop_dir or default_desktop_dir()).resolve() / f"{PRODUCT_NAME}.lnk"

    shortcuts_to_remove = [sm_lnk, dt_lnk]
    manifest_file = dst / INSTALL_MANIFEST_NAME
    if manifest_file.is_file():
        try:
            m = json.loads(manifest_file.read_text(encoding=ENCODING))
            for s in m.get("shortcuts") or []:
                p = Path(str(s))
                if p not in shortcuts_to_remove:
                    shortcuts_to_remove.append(p)
        except (OSError, ValueError):
            pass

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "install_dir": str(dst),
            "would_remove_shortcuts": [str(p) for p in shortcuts_to_remove if p.exists()],
            "would_unregister_os": unregister_os,
            "would_purge_data": purge_data,
            "user_data_root": str(data_root),
        }

    _best_effort_quit_running_host(dst / DESKTOP_EXE_NAME)

    removed_shortcuts: list[str] = []
    for lnk in shortcuts_to_remove:
        if lnk.is_file():
            try:
                os.chmod(lnk, stat.S_IWRITE)
                lnk.unlink()
                removed_shortcuts.append(str(lnk))
            except OSError:
                pass

    removed_reg: list[str] = []
    if unregister_os:
        removed_reg = unregister_os_integration(registry_backend=registry_backend)

    deferred_cleanup = False
    removed_install_dir = False
    if dst.is_dir():
        try:
            _rmtree_force(dst)
            removed_install_dir = True
        except OSError:
            deferred_cleanup = _schedule_deferred_dir_cleanup(dst)

    removed_data = False
    if purge_data and data_root.is_dir():
        try:
            _rmtree_force(data_root)
        except OSError:
            pass
        removed_data = not data_root.exists()

    return {
        "ok": True,
        "dry_run": False,
        "install_dir": str(dst),
        "removed_install_dir": removed_install_dir,
        "deferred_cleanup": deferred_cleanup,
        "removed_shortcuts": removed_shortcuts,
        "removed_registry_keys": removed_reg,
        "purged_user_data": removed_data,
    }


def get_desktop_status(
    forge_root: Path,
    *,
    install_dir: Path | None = None,
    registry_backend: Any | None = None,
) -> dict[str, Any]:
    """Return full diagnostic status for portable & per-user installed Luminara Desktop App."""
    reg = registry_backend or WinRegBackend()
    resolved_forge = forge_root.resolve()
    prof_path = resolved_forge / "fork.json"
    prof = ForkProfile.load(prof_path) if prof_path.is_file() else ForkProfile()

    inst_dir = (install_dir or default_install_dir()).resolve()
    inst_manifest_path = inst_dir / INSTALL_MANIFEST_NAME
    inst_manifest: dict[str, Any] | None = None
    if inst_manifest_path.is_file():
        try:
            inst_manifest = json.loads(inst_manifest_path.read_text(encoding=ENCODING))
        except (OSError, ValueError):
            inst_manifest = None

    portable_dir = (resolved_forge / "dist" / f"{prof.slug}-win64").resolve()
    portable_exe = portable_dir / DESKTOP_EXE_NAME
    installed_exe = inst_dir / DESKTOP_EXE_NAME

    return {
        "ok": True,
        "app_version": APP_VERSION,
        "app_user_model_id": APP_USER_MODEL_ID,
        "portable": {
            "dist_dir": str(portable_dir),
            "chrome_present": (portable_dir / "App" / "chrome.exe").is_file(),
            "native_host": inspect_pe_desktop_binary(portable_exe),
        },
        "installed": {
            "is_installed": inst_manifest is not None and installed_exe.is_file(),
            "install_dir": str(inst_dir),
            "native_host": inspect_pe_desktop_binary(installed_exe),
            "apps_and_features_registered": reg.get_value(UNINSTALL_SUBKEY, "DisplayName") is not None,
            "protocol_registered": reg.get_value(f"Software\\Classes\\{PROTOCOL_SCHEME}", "URL Protocol") is not None,
            "manifest": inst_manifest,
        },
    }


__all__ = [
    "APP_USER_MODEL_ID",
    "INSTALL_MANIFEST_NAME",
    "UNINSTALL_SUBKEY",
    "WinRegBackend",
    "_schedule_deferred_dir_cleanup",
    "create_windows_shortcut",
    "default_desktop_dir",
    "default_install_dir",
    "default_start_menu_dir",
    "default_user_data_root",
    "get_desktop_status",
    "install_desktop_app",
    "register_os_integration",
    "uninstall_desktop_app",
    "unregister_os_integration",
]
