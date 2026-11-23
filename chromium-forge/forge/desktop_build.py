"""Native Rust Win32 Desktop Host Builder & PE Verifier (`forge/desktop_build.py`).

Compiles `desktop/` (`LuminaraBrowser.exe` — zero-dependency Rust Win32 GUI supervisor) and verifies:
- Valid x64 Windows PE32+ executable with `Subsystem = WINDOWS_GUI (2)` (zero console flash).
- Embedded `RT_GROUP_ICON` (`luminara.ico`), `RT_VERSION` (`Luminara Browser`), and `RT_MANIFEST` (`PerMonitorV2`).
"""

from __future__ import annotations

import contextlib
import hashlib
import os
from pathlib import Path
import shutil
import struct
import subprocess
from typing import Any

from .exe_icon import RT_GROUP_ICON, read_resources

DESKTOP_EXE_NAME = "LuminaraBrowser.exe"
RT_VERSION = 16
RT_MANIFEST = 24
PE_SUBSYSTEM_WINDOWS_GUI = 2


def _atomic_copy_exe(src_exe: Path, dst_exe: Path) -> Path:
    """Copy `src_exe` over `dst_exe` using stage + `.old` rename-aside (AV / open-handle resilient)."""
    dst_exe.parent.mkdir(parents=True, exist_ok=True)
    work = dst_exe.with_name(dst_exe.name + ".staging")
    old = dst_exe.with_name(dst_exe.name + ".old")
    shutil.copy2(src_exe, work)
    try:
        with contextlib.suppress(OSError):
            old.unlink()
        if dst_exe.exists():
            try:
                os.replace(work, dst_exe)
                return dst_exe
            except OSError:
                os.replace(dst_exe, old)
                try:
                    os.replace(work, dst_exe)
                except OSError:
                    os.replace(old, dst_exe)
                    raise
        else:
            os.replace(work, dst_exe)
    finally:
        with contextlib.suppress(OSError):
            work.unlink()
        with contextlib.suppress(OSError):
            old.unlink()
    return dst_exe


def find_desktop_crate_dir(forge_root: Path) -> Path | None:
    """Locate `<repo_root>/desktop/Cargo.toml` relative to `forge_root` or package root."""
    candidates = [
        forge_root.resolve().parent / "desktop",
        Path(__file__).resolve().parent.parent.parent / "desktop",
    ]
    for cand in candidates:
        if (cand / "Cargo.toml").is_file():
            return cand.resolve()
    return None


def inspect_pe_desktop_binary(exe_path: Path) -> dict[str, Any]:
    """Inspect PE32+ header, GUI subsystem flag, SHA-256, and Win32 icon/version/manifest resources."""
    if not exe_path.is_file():
        return {"present": False, "valid_pe": False, "path": str(exe_path)}

    raw_bytes = exe_path.read_bytes()
    if len(raw_bytes) < 64 or raw_bytes[:2] != b"MZ":
        return {"present": True, "valid_pe": False, "error": "Missing MZ header", "path": str(exe_path)}

    pe_off = struct.unpack_from("<I", raw_bytes, 0x3C)[0]
    if pe_off + 24 > len(raw_bytes) or raw_bytes[pe_off : pe_off + 4] != b"PE\x00\x00":
        return {"present": True, "valid_pe": False, "error": "Missing PE signature", "path": str(exe_path)}

    machine, sections, _ts, _sym, _nsym, opt_size, _chars = struct.unpack_from("<HHIIIHH", raw_bytes, pe_off + 4)
    opt_off = pe_off + 24
    if opt_off + opt_size > len(raw_bytes):
        return {"present": True, "valid_pe": False, "error": "Truncated optional header", "path": str(exe_path)}
    opt_magic = struct.unpack_from("<H", raw_bytes, opt_off)[0] if opt_size >= 2 else 0
    subsystem = struct.unpack_from("<H", raw_bytes, opt_off + 68)[0] if opt_size >= 70 else 0
    arch_map = {0x8664: "x64", 0x014C: "x86", 0xAA64: "arm64"}

    info: dict[str, Any] = {
        "present": True,
        "path": str(exe_path.resolve()),
        "valid_pe": True,
        "architecture": arch_map.get(machine, "unknown"),
        "machine_hex": f"0x{machine:04x}",
        "pe_format": "PE32+" if opt_magic == 0x20B else "PE32",
        "sections": sections,
        "subsystem": subsystem,
        "is_windows_gui": subsystem == PE_SUBSYSTEM_WINDOWS_GUI,
        "size_bytes": len(raw_bytes),
        "sha256": hashlib.sha256(raw_bytes).hexdigest(),
    }

    if os.name == "nt":
        try:
            icons = read_resources(exe_path, RT_GROUP_ICON)
            versions = read_resources(exe_path, RT_VERSION)
            manifests = read_resources(exe_path, RT_MANIFEST)
            manifest_xml = b"".join(manifests.values()).decode("utf-8", errors="replace")
            ver_blob = b"".join(versions.values())
            info.update(
                {
                    "has_icon_group": bool(icons),
                    "icon_group_count": len(icons),
                    "has_version_info": bool(versions),
                    "version_mentions_luminara": "Luminara Browser".encode("utf-16le") in ver_blob,
                    "has_manifest": bool(manifests),
                    "manifest_per_monitor_v2": "PerMonitorV2" in manifest_xml,
                    "manifest_as_invoker": "asInvoker" in manifest_xml,
                }
            )
        except OSError as exc:
            info["resource_inspect_error"] = str(exc)

    return info


def build_desktop_host(
    forge_root: Path,
    *,
    dest_dir: Path | None = None,
    release: bool = True,
) -> dict[str, Any]:
    """Compile `desktop/` via Cargo and optionally stage `LuminaraBrowser.exe` into `dest_dir`."""
    crate_dir = find_desktop_crate_dir(forge_root)
    if crate_dir is None:
        raise FileNotFoundError("Native desktop Rust crate not found (expected desktop/Cargo.toml)")

    cargo = shutil.which("cargo")
    if not cargo:
        raise FileNotFoundError("Rust toolchain `cargo` not found on PATH")

    cmd = [cargo, "build", "--manifest-path", str(crate_dir / "Cargo.toml")]
    if release:
        cmd.append("--release")

    proc = subprocess.run(cmd, cwd=str(crate_dir), capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"cargo build failed (exit {proc.returncode}): {proc.stderr.strip() or proc.stdout.strip()}")

    profile_dir = "release" if release else "debug"
    built_exe = crate_dir / "target" / profile_dir / DESKTOP_EXE_NAME
    if not built_exe.is_file():
        raise FileNotFoundError(f"Expected compiled binary missing: {built_exe}")

    staged_path: Path | None = None
    if dest_dir is not None:
        staged_path = _atomic_copy_exe(built_exe, dest_dir / DESKTOP_EXE_NAME)

    target_exe = staged_path or built_exe
    pe_info = inspect_pe_desktop_binary(target_exe)
    return {
        "ok": bool(pe_info.get("valid_pe") and pe_info.get("is_windows_gui")),
        "built_exe": str(built_exe),
        "staged_exe": str(staged_path) if staged_path else "",
        "pe_info": pe_info,
    }


def stage_prebuilt_desktop_host(
    forge_root: Path,
    dest_dir: Path,
    *,
    auto_build: bool = True,
) -> Path | None:
    """Copy prebuilt `LuminaraBrowser.exe` into `dest_dir` (auto-compiling on Windows if `cargo` exists)."""
    if os.name != "nt":
        return None
    crate_dir = find_desktop_crate_dir(forge_root)
    if crate_dir is None:
        return None

    built_exe = crate_dir / "target" / "release" / DESKTOP_EXE_NAME
    if not built_exe.is_file() and auto_build and shutil.which("cargo"):
        build_desktop_host(forge_root, dest_dir=dest_dir, release=True)
        return dest_dir / DESKTOP_EXE_NAME

    if built_exe.is_file():
        return _atomic_copy_exe(built_exe, dest_dir / DESKTOP_EXE_NAME)
    return None


__all__ = [
    "DESKTOP_EXE_NAME",
    "_atomic_copy_exe",
    "build_desktop_host",
    "find_desktop_crate_dir",
    "inspect_pe_desktop_binary",
    "stage_prebuilt_desktop_host",
]
