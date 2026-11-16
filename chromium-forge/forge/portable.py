"""Instant Working Portable Luminara Browser Assembler (`forge/portable.py`).

Production-hardened portable bundler:
- Zero hardcoded build-host `C:\\Users\\...` paths in `.cmd`, `.ps1`, `newtab.html`, `workspace.html`, or MV3 extensions!
- Bundles lightweight pure-stdlib `forge/` into `dist/<slug>-win64/Agent/forge` + resolves `$PSScriptRoot` / `%~dp0`
  dynamically at runtime so moving the folder to any drive or PC works immediately.
- Fixes PowerShell backtick-quote `ParserError` (`& $chrome @argList @args`) and quotes every `.cmd` switch safely.
- Generates PNG extension icons (`16`/`48`/`128`) and explicit MV3 `content_security_policy` on both extensions.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
import shutil
import socket
import struct
import subprocess
import time
import zipfile

from .cdp_client import CDPBridge
from .downloads import extract_archive
from .http_base import ensure_local_ui_key
from .luminara_ui import (
    build_luminara_newtab_html,
    build_luminara_workspace_html,
    write_copilot_extension,
)
from .luminara_workspace_ui import make_solid_emerald_png
from .models import ForkProfile

ENCODING = "utf-8"


def _detect_zip_root_prefix(zip_path: Path) -> str | None:
    with zipfile.ZipFile(zip_path, "r") as zf:
        roots = {name.split("/", 1)[0] for name in zf.namelist() if "/" in name}
        if len(roots) == 1:
            return next(iter(roots))
    return None


def _build_initial_preferences(profile: ForkProfile, ntp_url: str) -> dict[str, object]:
    return {
        "homepage": ntp_url,
        "homepage_is_newtabpage": True,
        "browser": {
            "show_home_button": True,
            "check_default_browser": False,
            "clear_data_on_exit": profile.clear_data_on_exit,
        },
        "bookmark_bar": {"show_on_all_tabs": True},
        "sync_promo": {"show_on_first_run_allowed": False},
        "signin": {"allowed": False, "allowed_on_next_startup": False},
        "search": {"suggest_enabled": False},
        "alternate_error_pages": {"enabled": False},
        "autofill": {"profile_enabled": False, "credit_card_enabled": False},
        "credentials_enable_service": False,
        "credentials_enable_autosignin": False,
        "download": {"prompt_for_download": True},
        "enable_do_not_track": True,
        "webrtc": {
            "ip_handling_policy": (
                "disable_non_proxied_udp" if profile.disable_webrtc_leak else "default"
            )
        },
        "distribution": {
            "import_bookmarks": False,
            "import_history": False,
            "import_home_page": False,
            "import_search_engine": False,
            "make_chrome_default": False,
            "make_chrome_default_for_user": False,
            "suppress_first_run_bubble": True,
            "do_not_create_any_shortcuts": True,
            "do_not_launch_chrome": True,
            "do_not_register_for_update_launch": True,
            "show_welcome_page": False,
            "skip_first_run_ui": True,
        },
        "first_run_tabs": [ntp_url],
    }


def _write_shield_extension(ext_dir: Path, profile: ForkProfile) -> None:
    """Create MV3 companion extension enforcing custom domain trap blocks at runtime."""
    ext_dir.mkdir(parents=True, exist_ok=True)
    icons_dir = ext_dir / "icons"
    icons_dir.mkdir(parents=True, exist_ok=True)
    for px in (16, 48, 128):
        (icons_dir / f"icon{px}.png").write_bytes(make_solid_emerald_png(px))

    rules = [
        {
            "id": 1,
            "priority": 1,
            "action": {"type": "block"},
            "condition": {
                "urlFilter": f"||{profile.trap_tld}^",
                "resourceTypes": [
                    "main_frame", "sub_frame", "script", "xmlhttprequest", "image", "ping", "other"
                ],
            },
        }
    ]
    for idx, dom in enumerate(profile.extra_blocked_domains, start=2):
        clean = dom.strip().lower()
        if clean:
            rules.append(
                {
                    "id": idx,
                    "priority": 1,
                    "action": {"type": "block"},
                    "condition": {
                        "urlFilter": f"||{clean}^",
                        "resourceTypes": [
                            "main_frame", "sub_frame", "script", "xmlhttprequest", "image", "ping", "other"
                        ],
                    },
                }
            )

    (ext_dir / "rules.json").write_text(json.dumps(rules, indent=2) + "\n", encoding=ENCODING, newline="\n")
    manifest = {
        "manifest_version": 3,
        "name": f"{profile.brand_name} Privacy Shield",
        "version": f"2.1.{profile.fork_revision}",
        "description": f"Runtime domain trap (.{profile.trap_tld}) & zero-Google telemetry firewall.",
        "permissions": ["declarativeNetRequest"],
        "icons": {"16": "icons/icon16.png", "48": "icons/icon48.png", "128": "icons/icon128.png"},
        "content_security_policy": {
            "extension_pages": "script-src 'self'; object-src 'none'; base-uri 'none';"
        },
        "declarative_net_request": {
            "rule_resources": [{"id": "forge_trap_rules", "enabled": True, "path": "rules.json"}]
        },
        "action": {
            "default_title": f"{profile.brand_name} Shield",
            "default_popup": "popup.html",
            "default_icon": {"16": "icons/icon16.png", "48": "icons/icon48.png"},
        },
    }
    (ext_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding=ENCODING, newline="\n")
    popup = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Shield</title><style>
body {{ width: 260px; margin: 0; padding: 14px; background: #14161b; color: #f1f3f8; font: 12px/1.45 Consolas, monospace; }}
.tag {{ color: #10b981; font-weight: bold; margin-bottom: 6px; }}
.muted {{ color: #9ea8ba; font-size: 11px; }}
</style></head><body>
<div class="tag">● {html.escape(profile.brand_name)} Shield</div>
<div>Trap TLD: <b>.{html.escape(profile.trap_tld)}</b></div>
<div>Active DNR Rules: <b>{len(rules)}</b></div>
<div class="muted" style="margin-top:8px;">Search: {html.escape(profile.resolved_search_engine().name)} · CDP :{profile.cdp_port}</div>
</body></html>
"""
    (ext_dir / "popup.html").write_text(popup, encoding=ENCODING, newline="\n")


def inspect_pe_machine_header(exe_path: Path) -> dict[str, object]:
    """Read PE COFF header directly from bytes (`confidence: 'observed'`)."""
    with exe_path.open("rb") as handle:
        mz = handle.read(64)
        if len(mz) < 64 or mz[:2] != b"MZ":
            raise ValueError(f"{exe_path} is not a valid Windows MZ/PE executable")
        pe_offset = struct.unpack_from("<I", mz, 0x3C)[0]
        handle.seek(pe_offset)
        pe_hdr = handle.read(24)
        if pe_hdr[:4] != b"PE\x00\x00":
            raise ValueError(f"{exe_path} lacks PE\\0\\0 signature")
        machine, sections, timestamp = struct.unpack_from("<HHI", pe_hdr, 4)
    arch_map = {0x8664: "x64", 0x014C: "x86", 0xAA64: "arm64"}
    return {
        "valid_pe": True,
        "machine_hex": f"0x{machine:04x}",
        "architecture": arch_map.get(machine, "unknown"),
        "sections": sections,
        "coff_timestamp": timestamp,
        "size_bytes": exe_path.stat().st_size,
    }


def _seed_or_extract_chromium_runtime(portable_zip: Path, dist_root: Path, app_dir: Path) -> None:
    chrome_exe = app_dir / "chrome.exe"
    if chrome_exe.exists():
        return
    if dist_root.exists():
        for sibling in dist_root.iterdir():
            sib_app = sibling / "App"
            if sib_app != app_dir and (sib_app / "chrome.exe").exists():
                shutil.copytree(sib_app, app_dir, dirs_exist_ok=True)
                return
    if not portable_zip.exists():
        raise FileNotFoundError(f"Portable archive not found: {portable_zip}")
    prefix = _detect_zip_root_prefix(portable_zip)
    extract_archive(portable_zip, app_dir, strip_leading_dirs=prefix)


def _bundle_portable_agent_runtime(forge_root: Path, target_dir: Path, profile: ForkProfile, ui_key: str) -> Path:
    """Copy pure-stdlib `forge/` (~180 KB) into `target_dir/Agent/` so the portable folder runs standalone anywhere."""
    agent_dir = target_dir / "Agent"
    src_pkg = forge_root / "forge"
    dst_pkg = agent_dir / "forge"
    if dst_pkg.exists():
        shutil.rmtree(dst_pkg)
    shutil.copytree(src_pkg, dst_pkg, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    profile.save(agent_dir / "fork.json")
    out_dir = agent_dir / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "local_ui_key.txt").write_text(ui_key + "\n", encoding=ENCODING, newline="\n")
    return agent_dir


def assemble_portable_distribution(
    portable_zip: Path,
    profile: ForkProfile,
    dist_root: Path,
) -> dict[str, object]:
    """Assemble a 100% relocatable, dual Human + AI Agent `Luminara Browser` Windows x64 distribution."""
    profile.validate()
    forge_root = Path(__file__).resolve().parent.parent
    ui_key = ensure_local_ui_key(forge_root)

    target_dir = (dist_root / f"{profile.slug}-win64").resolve()
    app_dir = target_dir / "App"
    profile_dir = target_dir / "Profile"
    chrome_exe = app_dir / "chrome.exe"

    _seed_or_extract_chromium_runtime(portable_zip, dist_root, app_dir)
    if not chrome_exe.exists():
        raise FileNotFoundError(f"chrome.exe missing after runtime preparation in {app_dir}")

    _bundle_portable_agent_runtime(forge_root, target_dir, profile, ui_key)

    pages_dir = app_dir / "luminara_pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    newtab_file = pages_dir / "newtab.html"
    workspace_file = pages_dir / "workspace.html"

    # Relative `./workspace.html` <-> `./newtab.html` links never break when the folder moves!
    newtab_html = build_luminara_newtab_html(
        profile,
        workspace_uri="./workspace.html",
        agent_port=profile.agent_port,
        cdp_port=profile.cdp_port,
        ui_key=ui_key,
    )
    workspace_html = build_luminara_workspace_html(
        profile,
        newtab_uri="./newtab.html",
        agent_port=profile.agent_port,
        ui_key=ui_key,
    )
    newtab_file.write_text(newtab_html, encoding=ENCODING, newline="\n")
    workspace_file.write_text(workspace_html, encoding=ENCODING, newline="\n")

    # Backward-compatible copy in `forge_ntp/` with proper relative path `../luminara_pages/workspace.html`
    ntp_dir = app_dir / "forge_ntp"
    ntp_dir.mkdir(parents=True, exist_ok=True)
    compat_ntp_html = build_luminara_newtab_html(
        profile,
        workspace_uri="../luminara_pages/workspace.html",
        agent_port=profile.agent_port,
        cdp_port=profile.cdp_port,
        ui_key=ui_key,
    )
    (ntp_dir / "index.html").write_text(compat_ntp_html, encoding=ENCODING, newline="\n")

    shield_dir = app_dir / "extensions" / "forge-shield"
    copilot_dir = app_dir / "extensions" / "luminara-copilot"
    _write_shield_extension(shield_dir, profile)
    write_copilot_extension(
        copilot_dir,
        profile,
        workspace_uri=f"http://127.0.0.1:{profile.agent_port}/workspace",
        agent_port=profile.agent_port,
        ui_key=ui_key,
    )

    # Preferences use loopback http://127.0.0.1:<agent_port>/newtab when co-browsing is enabled (100% path-independent!)
    default_home_url = (
        f"http://127.0.0.1:{profile.agent_port}/newtab"
        if profile.enable_agent_cobrowsing
        else "about:blank"
    )
    prefs_payload = json.dumps(_build_initial_preferences(profile, default_home_url), indent=2) + "\n"
    (app_dir / "initial_preferences").write_text(prefs_payload, encoding=ENCODING, newline="\n")
    (app_dir / "master_preferences").write_text(prefs_payload, encoding=ENCODING, newline="\n")

    profile_dir.mkdir(parents=True, exist_ok=True)
    switches = list(profile.runtime_switches())
    if profile.enable_agent_cobrowsing:
        switches.extend(
            [
                f"--remote-debugging-port={profile.cdp_port}",
                f"--remote-allow-origins=http://127.0.0.1:{profile.agent_port}",
            ]
        )

    # Valid PowerShell launcher (`Launch-<slug>.ps1`) — zero hardcoded machine paths & valid AST syntax!
    ps_switches_lines = ",\n  ".join("'" + sw.replace("'", "''") + "'" for sw in switches)
    ps1_launcher = target_dir / f"Launch-{profile.slug}.ps1"
    ps1_body = f"""$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$agentWorkDir = if (Test-Path (Join-Path $root '..\\..\\forge\\__main__.py')) {{
  (Resolve-Path (Join-Path $root '..\\..')).Path
}} else {{
  Join-Path $root 'Agent'
}}

$pyCmd = Get-Command pythonw -ErrorAction SilentlyContinue
if (-not $pyCmd) {{ $pyCmd = Get-Command python -ErrorAction SilentlyContinue }}

# First-run per-installation CSPRNG UI key rotation (ensures public Release .zip installs never share a key!)
$initMarker = Join-Path $root 'Profile\\.ui_key_initialized'
$keyFile = Join-Path $agentWorkDir 'outputs\\local_ui_key.txt'
if (-not (Test-Path $initMarker) -and (Test-Path $keyFile)) {{
  $oldKey = (Get-Content -Raw $keyFile).Trim()
  $bytes = New-Object byte[] 32
  $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
  $rng.GetBytes($bytes)
  $rng.Dispose()
  $newKey = ($bytes | ForEach-Object {{ $_.ToString('x2') }}) -join ''
  if ($oldKey.Length -ge 32 -and $newKey.Length -eq 64) {{
    [System.IO.File]::WriteAllText($keyFile, ($newKey + "`n"), [System.Text.UTF8Encoding]::new($false))
    foreach ($rel in @('App\\luminara_pages\\newtab.html', 'App\\luminara_pages\\workspace.html', 'App\\forge_ntp\\index.html', 'App\\extensions\\luminara-copilot\\sidepanel.js')) {{
      $p = Join-Path $root $rel
      if (Test-Path $p) {{
        $updated = [System.IO.File]::ReadAllText($p, [System.Text.Encoding]::UTF8).Replace($oldKey, $newKey)
        [System.IO.File]::WriteAllText($p, $updated, [System.Text.UTF8Encoding]::new($false))
      }}
    }}
  }}
  New-Item -ItemType Directory -Force -Path (Join-Path $root 'Profile') | Out-Null
  [System.IO.File]::WriteAllText($initMarker, "ok`n", [System.Text.UTF8Encoding]::new($false))
}}

$ntpUrl = ([Uri](Join-Path $root 'App\\luminara_pages\\newtab.html')).AbsoluteUri
if ({'$true' if profile.enable_agent_cobrowsing else '$false'} -and $pyCmd) {{
  $listening = Get-NetTCPConnection -LocalPort {profile.agent_port} -State Listen -ErrorAction SilentlyContinue
  if (-not $listening) {{
    Start-Process -WindowStyle Hidden -FilePath $pyCmd.Source -WorkingDirectory $agentWorkDir -ArgumentList @('-m', 'forge', 'agent-daemon', '--port', '{profile.agent_port}', '--cdp-port', '{profile.cdp_port}')
    for ($i = 0; $i -lt 20; $i++) {{
      if (Get-NetTCPConnection -LocalPort {profile.agent_port} -State Listen -ErrorAction SilentlyContinue) {{ break }}
      Start-Sleep -Milliseconds 100
    }}
  }}
  if (Get-NetTCPConnection -LocalPort {profile.agent_port} -State Listen -ErrorAction SilentlyContinue) {{
    $ntpUrl = 'http://127.0.0.1:{profile.agent_port}/newtab'
  }}
}}

$extShield = Join-Path $root 'App\\extensions\\forge-shield'
$extCopilot = Join-Path $root 'App\\extensions\\luminara-copilot'
$chrome = Join-Path $root 'App\\chrome.exe'
$argList = @(
  ("--user-data-dir=" + (Join-Path $root 'Profile')),
  ("--custom-ntp=" + $ntpUrl),
  ("--load-extension=" + $extShield + "," + $extCopilot),
  {ps_switches_lines},
  $ntpUrl
) + $args

# Quote whitespace-containing arguments for Windows PowerShell 5.1 Start-Process compatibility
$quotedArgs = $argList | ForEach-Object {{
  if ($_ -match '\\s') {{ '"' + ($_ -replace '"', '\\"') + '"' }} else {{ $_ }}
}}
Start-Process -FilePath $chrome -ArgumentList $quotedArgs
"""
    ps1_launcher.write_text(ps1_body, encoding=ENCODING, newline="\n")

    # `.cmd` delegates cleanly to `.ps1` (resolving all paths relative to `%~dp0` with zero quote/space bugs!)
    cmd_launcher = target_dir / f"Launch-{profile.slug}.cmd"
    cmd_body = "\r\n".join(
        [
            "@echo off",
            "setlocal",
            f'powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Launch-{profile.slug}.ps1" %*',
            "",
        ]
    )
    cmd_launcher.write_bytes(cmd_body.encode(ENCODING))

    pe_info = inspect_pe_machine_header(chrome_exe)
    return {
        "dist_dir": str(target_dir),
        "chrome_exe": str(chrome_exe),
        "cmd_launcher": str(cmd_launcher),
        "ps1_launcher": str(ps1_launcher),
        "ntp_file": str(newtab_file),
        "ntp_url": newtab_file.resolve().as_uri(),
        "workspace_file": str(workspace_file),
        "workspace_url": workspace_file.resolve().as_uri(),
        "shield_extension": str(shield_dir),
        "copilot_extension": str(copilot_dir),
        "cdp_port": profile.cdp_port,
        "agent_port": profile.agent_port,
        "pe_evidence": pe_info,
    }


def smoke_test_portable_headless(chrome_exe: Path, ntp_file: Path, work_dir: Path) -> dict[str, object]:
    """Verify real `chrome.exe` renders Luminara's Agentic Command Deck via headless loopback CDP."""
    tmp_profile = work_dir / "smoke_profile"
    tmp_profile.mkdir(parents=True, exist_ok=True)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = int(s.getsockname()[1])

    proc = subprocess.Popen(
        [
            str(chrome_exe),
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            f"--remote-debugging-port={port}",
            "--remote-allow-origins=*",
            f"--user-data-dir={tmp_profile}",
            ntp_file.resolve().as_uri(),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    cdp = CDPBridge("127.0.0.1", port)
    dom = ""
    try:
        deadline = time.time() + 10.0
        while time.time() < deadline and not cdp.is_alive():
            time.sleep(0.12)
        time.sleep(0.35)
        val = cdp.evaluate_js(None, "document.documentElement ? document.documentElement.outerHTML : ''")
        dom = val if isinstance(val, str) else ""
    finally:
        proc.kill()
        proc.wait(timeout=5)

    return {
        "exit_code": 0 if dom else 1,
        "dom_length": len(dom),
        "rendered_custom_ntp": ("Zero Google Telemetry" in dom) or ("omniForm" in dom) or ("searchForm" in dom),
    }
