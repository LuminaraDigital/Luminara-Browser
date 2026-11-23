"""Brand a Windows PE (`chrome.exe`) with the Luminara app icon via kernel32 `UpdateResource` (`forge/exe_icon.py`).

Chromium loads its window/taskbar icon from the exe's `RT_GROUP_ICON` resources, so every existing icon group is
re-pointed at `ui/luminara.ico` and the stock `RT_ICON` images are dropped. Pure stdlib (`ctypes`), Windows only.
"""

from __future__ import annotations

import contextlib
import ctypes
import os
from pathlib import Path
import secrets
import shutil
import stat
import struct

RT_ICON = 3
RT_GROUP_ICON = 14
LUMINARA_ICO = Path(__file__).resolve().parent / "ui" / "luminara.ico"

ResourceName = int | str


def parse_ico(data: bytes) -> list[tuple[bytes, bytes]]:
    """Split an `.ico` file into `(12-byte GRPICONDIRENTRY prefix, image bytes)` pairs."""
    if len(data) < 6:
        raise ValueError("not a Windows .ico file (truncated header)")
    reserved, kind, count = struct.unpack_from("<HHH", data, 0)
    if reserved != 0 or kind != 1 or count == 0 or len(data) < 6 + 16 * count:
        raise ValueError("not a Windows .ico file")
    entries = []
    for i in range(count):
        w, h, colors, res, planes, bpp, size, offset = struct.unpack_from("<BBBBHHII", data, 6 + 16 * i)
        if size == 0:
            raise ValueError(f"empty .ico image #{i}")
        image = data[offset : offset + size]
        if len(image) != size:
            raise ValueError(f"truncated .ico image #{i}")
        entries.append((struct.pack("<BBBBHHI", w, h, colors, res, planes, bpp, size), image))
    return entries


def build_group_icon(entries: list[tuple[bytes, bytes]], first_id: int) -> bytes:
    """Encode an `RT_GROUP_ICON` directory whose images are `RT_ICON` ids `first_id..first_id+n-1`."""
    header = struct.pack("<HHH", 0, 1, len(entries))
    return header + b"".join(meta + struct.pack("<H", first_id + i) for i, (meta, _) in enumerate(entries))


def _kernel32() -> ctypes.WinDLL:
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    vp = ctypes.c_void_p
    k32.LoadLibraryExW.argtypes, k32.LoadLibraryExW.restype = [wintypes.LPCWSTR, wintypes.HANDLE, wintypes.DWORD], vp
    k32.FreeLibrary.argtypes = [vp]
    k32.EnumResourceNamesW.argtypes = [vp, vp, vp, vp]
    k32.EnumResourceLanguagesW.argtypes = [vp, vp, vp, vp, vp]
    k32.FindResourceExW.argtypes, k32.FindResourceExW.restype = [vp, vp, vp, wintypes.WORD], vp
    k32.LoadResource.argtypes, k32.LoadResource.restype = [vp, vp], vp
    k32.LockResource.argtypes, k32.LockResource.restype = [vp], vp
    k32.SizeofResource.argtypes, k32.SizeofResource.restype = [vp, vp], wintypes.DWORD
    k32.BeginUpdateResourceW.argtypes, k32.BeginUpdateResourceW.restype = [wintypes.LPCWSTR, wintypes.BOOL], vp
    k32.UpdateResourceW.argtypes = [vp, vp, vp, wintypes.WORD, vp, wintypes.DWORD]
    k32.EndUpdateResourceW.argtypes = [vp, wintypes.BOOL]
    return k32


def _decode_name(ptr: int | None) -> ResourceName:
    value = ptr or 0
    return value if value <= 0xFFFF else ctypes.wstring_at(value)


def read_resources(exe: Path, rtype: int) -> dict[tuple[ResourceName, int], bytes]:
    """Return `{(name, language): data}` for every resource of `rtype` in `exe`."""
    from ctypes import wintypes

    k32 = _kernel32()
    module = k32.LoadLibraryExW(str(exe), None, 0x2 | 0x20)  # LOAD_LIBRARY_AS_DATAFILE | AS_IMAGE_RESOURCE
    if not module:
        raise ctypes.WinError(ctypes.get_last_error())
    found: dict[tuple[ResourceName, int], bytes] = {}
    name_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
    lang_proc = ctypes.WINFUNCTYPE(
        wintypes.BOOL, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.WORD, ctypes.c_void_p
    )

    def on_lang(_mod, _type, name_ptr, lang, _param):  # noqa: ANN001 - Win32 callback signature
        res = k32.FindResourceExW(module, rtype, name_ptr, lang)
        if not res:
            return True
        size = k32.SizeofResource(module, res)
        loaded = k32.LoadResource(module, res)
        ptr = k32.LockResource(loaded) if loaded else None
        if ptr and size > 0:
            found[(_decode_name(name_ptr), lang)] = ctypes.string_at(ptr, size)
        return True

    def on_name(_mod, _type, name_ptr, _param):  # noqa: ANN001 - Win32 callback signature
        k32.EnumResourceLanguagesW(module, rtype, name_ptr, lang_cb, None)
        return True

    lang_cb, name_cb = lang_proc(on_lang), name_proc(on_name)
    try:
        k32.EnumResourceNamesW(module, rtype, name_cb, None)  # FALSE + ERROR_RESOURCE_TYPE_NOT_FOUND when absent
    finally:
        k32.FreeLibrary(module)
    return found


def embed_app_icon(exe: Path, ico: Path = LUMINARA_ICO) -> int:
    """Replace every icon group in `exe` with `ico`; returns how many groups were re-branded (0 = none). Idempotent.

    Antivirus scanners (e.g. McAfee `mc-fw-host.exe`) keep a no-write-share handle on recently run exes, which
    breaks in-place `EndUpdateResource` and `MoveFileEx` over the target, but still allows renaming it. So the
    branded copy is built beside `exe`, the original is renamed aside, and the copy is moved into place.
    """
    if not ico.is_file():
        return 0
    for old_tmp in (*exe.parent.glob(f"{exe.name}.stock*"), *exe.parent.glob(f"{exe.name}.branding*")):
        with contextlib.suppress(OSError):
            os.chmod(old_tmp, stat.S_IWRITE)
            old_tmp.unlink()

    groups = read_resources(exe, RT_GROUP_ICON)
    if not groups:
        return 0  # stub binaries carry no icons to brand
    entries = parse_ico(ico.read_bytes())
    expected_group = build_group_icon(entries, first_id=1)
    if all(data == expected_group for data in groups.values()):
        old_icons = read_resources(exe, RT_ICON)
        lang = next(iter(groups))[1]
        if len(old_icons) == len(entries) and all(
            old_icons.get((i, lang)) == img for i, (_, img) in enumerate(entries, start=1)
        ):
            return len(groups)

    suffix = f"{os.getpid()}.{secrets.token_hex(3)}"
    work = exe.with_name(f"{exe.name}.branding.{suffix}")
    stale = exe.with_name(f"{exe.name}.stock.{suffix}")
    shutil.copy2(exe, work)
    try:
        os.chmod(work, stat.S_IWRITE)
        count = _rewrite_icons(work, entries)
        os.replace(exe, stale)
        try:
            os.replace(work, exe)
        except OSError:
            os.replace(stale, exe)
            raise
    finally:
        with contextlib.suppress(OSError):
            work.unlink()
    with contextlib.suppress(OSError):
        os.chmod(stale, stat.S_IWRITE)
        stale.unlink()  # may stay delete-pending until the scanner lets go; harmless
    return count


def _rewrite_icons(exe: Path, entries: list[tuple[bytes, bytes]]) -> int:
    groups = read_resources(exe, RT_GROUP_ICON)
    old_icons = read_resources(exe, RT_ICON)
    lang = next(iter(groups))[1]
    group_data = build_group_icon(entries, first_id=1)

    k32 = _kernel32()
    handle = k32.BeginUpdateResourceW(str(exe), False)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    committed = False
    try:
        for rtype, existing in ((RT_ICON, old_icons), (RT_GROUP_ICON, groups)):
            for name, res_lang in existing:
                if not k32.UpdateResourceW(handle, rtype, name, res_lang, None, 0):
                    raise ctypes.WinError(ctypes.get_last_error())
        for i, (_, image) in enumerate(entries, start=1):
            if not k32.UpdateResourceW(handle, RT_ICON, i, lang, image, len(image)):
                raise ctypes.WinError(ctypes.get_last_error())
        for name, res_lang in groups:
            if not k32.UpdateResourceW(handle, RT_GROUP_ICON, name, res_lang, group_data, len(group_data)):
                raise ctypes.WinError(ctypes.get_last_error())
        if not k32.EndUpdateResourceW(handle, False):
            raise ctypes.WinError(ctypes.get_last_error())
        committed = True
    finally:
        if not committed:
            k32.EndUpdateResourceW(handle, True)  # discard partial edits, leave exe untouched
    return len(groups)


__all__ = ["LUMINARA_ICO", "build_group_icon", "embed_app_icon", "parse_ico", "read_resources"]
