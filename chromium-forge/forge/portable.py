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
import re
import shutil
import socket
import struct
import subprocess
import time
import zipfile

from .cdp_client import CDPBridge, terminate_browser_process, wait_for_cdp_page_ready
from .downloads import extract_archive
from .http_base import atomic_write_private, ensure_local_ui_key
from .luminara_copilot_ext import build_palette_js, make_solid_emerald_png, write_copilot_extension
from .luminara_ui import (
    build_luminara_newtab_html,
    build_luminara_workspace_html,
)
from .models import ForkProfile
from .shield_compiler import build_deterministic_farbling_js, compile_dnr_shield_rules
from .webmcp import WEBMCP_BOOTSTRAP_JS

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
    """Create MV3 Privacy Shield v3 extension (DNR tracker/query-param scrubber + deterministic farbling + WebMCP)."""
    ext_dir.mkdir(parents=True, exist_ok=True)
    from .luminara_logo3d import write_extension_icons

    write_extension_icons(ext_dir)

    rules = compile_dnr_shield_rules(profile)
    (ext_dir / "rules.json").write_text(json.dumps(rules, indent=2) + "\n", encoding=ENCODING, newline="\n")
    (ext_dir / "farble.js").write_text(build_deterministic_farbling_js(), encoding=ENCODING, newline="\n")
    (ext_dir / "webmcp_bootstrap.js").write_text(WEBMCP_BOOTSTRAP_JS, encoding=ENCODING, newline="\n")

    content_scripts: list[dict[str, object]] = []
    if getattr(profile, "enable_shield_v3", True):
        content_scripts.append(
            {
                "matches": ["http://*/*", "https://*/*"],
                "js": ["farble.js"],
                "run_at": "document_start",
                "world": "MAIN",
            }
        )
    if getattr(profile, "enable_webmcp", True):
        content_scripts.append(
            {
                "matches": ["http://*/*", "https://*/*"],
                "js": ["webmcp_bootstrap.js"],
                "run_at": "document_start",
                "world": "MAIN",
            }
        )

    manifest: dict[str, object] = {
        "manifest_version": 3,
        "name": f"{profile.brand_name} Privacy Shield v3",
        "version": "3.1.0",
        "description": f"Tracker/query-param DNR firewall (.{profile.trap_tld}), eTLD+1 deterministic farbling & W3C WebMCP.",
        "permissions": ["declarativeNetRequest", "declarativeNetRequestWithHostAccess"],
        "host_permissions": ["<all_urls>"],
        "icons": {"16": "icons/icon16.png", "48": "icons/icon48.png", "128": "icons/icon128.png"},
        "content_security_policy": {
            "extension_pages": "script-src 'self'; object-src 'none'; base-uri 'none';"
        },
        "declarative_net_request": {
            "rule_resources": [{"id": "forge_trap_rules", "enabled": True, "path": "rules.json"}]
        },
        **({"content_scripts": content_scripts} if content_scripts else {}),
        "action": {
            "default_title": f"{profile.brand_name} Shield v3",
            "default_popup": "popup.html",
            "default_icon": {"16": "icons/icon16.png", "48": "icons/icon48.png"},
        },
    }
    (ext_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding=ENCODING, newline="\n")
    popup = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="color-scheme" content="dark light"><title>Shield v3</title><style>
:root {{
  color-scheme: dark light;
  --bg: light-dark(oklch(0.985 0.004 255), oklch(0.145 0.012 255));
  --ink: light-dark(oklch(0.16 0.015 255), oklch(0.96 0.006 255));
  --muted: light-dark(oklch(0.45 0.018 255), oklch(0.71 0.015 255));
  --accent: light-dark(oklch(0.47 0.14 162), oklch(0.75 0.16 162));
}}
body {{ width: 280px; margin: 0; padding: 14px; background: var(--bg); color: var(--ink); font: 12px/1.45 Consolas, monospace; font-variant-numeric: tabular-nums; }}
.tag {{ color: var(--accent); font-weight: bold; margin-bottom: 6px; }}
.muted {{ color: var(--muted); font-size: 11px; }}
</style></head><body>
<div class="tag">● {html.escape(profile.brand_name)} Shield v3</div>
<div>Trap TLD: <b>.{html.escape(profile.trap_tld)}</b></div>
<div>Active DNR Rules: <b>{len(rules)}</b> (Trackers + Param Scrub)</div>
<div>Deterministic Farbling: <b>{"ON" if getattr(profile, "enable_shield_v3", True) else "OFF"}</b></div>
<div>W3C WebMCP Runtime: <b>{"ON" if getattr(profile, "enable_webmcp", True) else "OFF"}</b></div>
<div class="muted" style="margin-top:8px;">Search: {html.escape(profile.resolved_search_engine().name)} · CDP :{profile.cdp_port}</div>
</body></html>
"""
    (ext_dir / "popup.html").write_text(popup, encoding=ENCODING, newline="\n")


def _extract_inline_script_for_mv3(
    html_doc: str,
    js_filename: str,
    extra_scripts: tuple[str, ...] = (),
) -> tuple[str, str]:
    """Split inline `<script>...</script>` out of HTML into an external `.js` file for MV3 CSP `script-src 'self'`."""
    scripts: list[str] = []

    def _repl(match: re.Match[str]) -> str:
        body = match.group(1).strip()
        if body:
            scripts.append(body)
        return ""

    stripped = re.sub(r"<script\b[^>]*>([\s\S]*?)</script>", _repl, html_doc, flags=re.IGNORECASE)
    script_tags = [*(f'<script src="{js_filename}" defer></script>' for _ in (1,) if scripts), *(f'<script src="{s}" defer></script>' for s in extra_scripts)]
    if script_tags:
        joined_tags = "\n".join(script_tags)
        if "</body>" in stripped:
            stripped = stripped.replace("</body>", f"{joined_tags}\n</body>", 1)
        else:
            stripped = stripped + "\n" + joined_tags + "\n"
    return stripped, "\n\n".join(scripts) + ("\n" if scripts else "")


def _write_offline_newtab_extension(
    ext_dir: Path,
    profile: ForkProfile,
    newtab_html: str,
    workspace_html: str,
) -> None:
    """Create `< 8 ms` offline-first MV3 New Tab Override (`chrome_url_overrides.newtab`) + Alt+K Command Palette."""
    ext_dir.mkdir(parents=True, exist_ok=True)
    from .luminara_logo3d import write_extension_icons

    write_extension_icons(ext_dir)

    ntp_clean, ntp_js = _extract_inline_script_for_mv3(newtab_html, "newtab.js")
    ws_clean, ws_js = _extract_inline_script_for_mv3(workspace_html, "workspace.js")
    (ext_dir / "newtab.html").write_text(ntp_clean, encoding=ENCODING, newline="\n")
    (ext_dir / "newtab.js").write_text(ntp_js, encoding=ENCODING, newline="\n")
    (ext_dir / "workspace.html").write_text(ws_clean, encoding=ENCODING, newline="\n")
    (ext_dir / "workspace.js").write_text(ws_js, encoding=ENCODING, newline="\n")

    newtab_bg_js = """chrome.runtime.onMessage.addListener((msg) => {
  if (msg && typeof msg.luminaraOpenPage === 'string') {
    const allowed = ['workspace.html', 'workspace.html#view=telemetry', 'newtab.html'];
    if (allowed.includes(msg.luminaraOpenPage)) {
      chrome.tabs.create({ url: chrome.runtime.getURL(msg.luminaraOpenPage) });
    }
  }
});
"""
    (ext_dir / "newtab_bg.js").write_text(newtab_bg_js, encoding=ENCODING, newline="\n")
    palette_js = build_palette_js(profile.resolved_search_engine().search_url, agent_port=profile.agent_port) + "\n"
    (ext_dir / "palette.js").write_text(palette_js, encoding=ENCODING, newline="\n")
    manifest = {
        "manifest_version": 3,
        "name": f"{profile.brand_name} Command Deck & Palette",
        "version": "3.1.0",
        "description": "Zero-cold-start offline-first New Tab Command Deck + Alt+K / Ctrl+Shift+K Command Palette.",
        "chrome_url_overrides": {"newtab": "newtab.html"},
        "background": {"service_worker": "newtab_bg.js"},
        "permissions": ["storage"],
        "host_permissions": [f"http://127.0.0.1:{profile.agent_port}/*"],
        "icons": {"16": "icons/icon16.png", "48": "icons/icon48.png", "128": "icons/icon128.png"},
        "content_security_policy": {
            "extension_pages": "script-src 'self'; object-src 'none'; base-uri 'none';"
        },
        "content_scripts": [
            {
                "matches": ["http://*/*", "https://*/*"],
                "js": ["palette.js"],
                "run_at": "document_idle",
            }
        ],
    }
    (ext_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding=ENCODING, newline="\n")


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


def _bundle_portable_agent_runtime(
    forge_root: Path,
    target_dir: Path,
    profile: ForkProfile,
    ui_key: str,
    *,
    release_scrub: bool = False,
) -> Path:
    """Copy pure-stdlib `forge/` (~180 KB) into `target_dir/Agent/` so the portable folder runs standalone anywhere."""
    _ = forge_root
    agent_dir = target_dir / "Agent"
    src_pkg = Path(__file__).resolve().parent
    dst_pkg = agent_dir / "forge"
    if dst_pkg.exists():
        shutil.rmtree(dst_pkg)
    shutil.copytree(src_pkg, dst_pkg, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "luminara-logo.png"))
    profile.save(agent_dir / "fork.json")
    out_dir = agent_dir / "outputs"
    if release_scrub and out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if ui_key and not release_scrub:
        atomic_write_private(out_dir / "local_ui_key.txt", ui_key + "\n")
    return agent_dir


def assemble_portable_distribution(
    portable_zip: Path,
    profile: ForkProfile,
    dist_root: Path,
    *,
    forge_root: Path | None = None,
    release_scrub: bool = False,
) -> dict[str, object]:
    """Assemble a 100% relocatable, dual Human + AI Agent `Luminara Browser` Windows x64 distribution."""
    profile.validate()
    pkg_parent = Path(__file__).resolve().parent.parent
    if forge_root is not None:
        resolved_forge = forge_root.resolve()
    elif (pkg_parent / "fork.json").is_file() or (pkg_parent / "patches" / "luminara").is_dir():
        resolved_forge = pkg_parent
    else:
        resolved_forge = dist_root.resolve().parent
    ui_key = "" if release_scrub else ensure_local_ui_key(resolved_forge)

    target_dir = (dist_root / f"{profile.slug}-win64").resolve()
    app_dir = target_dir / "App"
    profile_dir = target_dir / "Profile"
    chrome_exe = app_dir / "chrome.exe"

    _seed_or_extract_chromium_runtime(portable_zip, dist_root, app_dir)
    if not chrome_exe.exists():
        raise FileNotFoundError(f"chrome.exe missing after runtime preparation in {app_dir}")

    _bundle_portable_agent_runtime(resolved_forge, target_dir, profile, ui_key, release_scrub=release_scrub)

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
    newtab_ext_dir = app_dir / "extensions" / "luminara-newtab"
    _write_shield_extension(shield_dir, profile)
    _write_offline_newtab_extension(newtab_ext_dir, profile, newtab_html, workspace_html)
    write_copilot_extension(
        copilot_dir,
        profile,
        workspace_uri=f"http://127.0.0.1:{profile.agent_port}/workspace",
        agent_port=profile.agent_port,
        ui_key=ui_key,
    )

    # Preferences use offline-first `chrome://newtab` when co-browsing is enabled (unifying origin with Ctrl+T!)
    default_home_url = "chrome://newtab" if profile.enable_agent_cobrowsing else "about:blank"
    prefs_payload = json.dumps(_build_initial_preferences(profile, default_home_url), indent=2) + "\n"
    (app_dir / "initial_preferences").write_text(prefs_payload, encoding=ENCODING, newline="\n")
    (app_dir / "master_preferences").write_text(prefs_payload, encoding=ENCODING, newline="\n")

    if release_scrub and profile_dir.exists():
        shutil.rmtree(profile_dir)
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
    cobrowse_ps = "$true" if profile.enable_agent_cobrowsing else "$false"
    ps1_launcher = target_dir / f"Launch-{profile.slug}.ps1"
    ps1_body = f"""$ErrorActionPreference = 'Stop'
function Quote-WinArg([string]$a) {{
  if ($a -eq '') {{ return '""' }}
  if ($a -notmatch '[\\s"]') {{ return $a }}
  return '"' + ([regex]::Replace($a, '(\\\\*)(")', '$1$1\\"') -replace '(\\\\+)$', '$1$1') + '"'
}}

$root = $PSScriptRoot
$devMain = Join-Path $root '..\\..\\forge\\__main__.py'
$agentWorkDir = if (Test-Path -LiteralPath $devMain) {{
  (Resolve-Path -LiteralPath (Join-Path $root '..\\..')).Path
}} else {{
  Join-Path $root 'Agent'
}}

$pyCmd = $null
foreach ($venvRel in @('..\\.venv\\Scripts\\pythonw.exe', '..\\.venv\\Scripts\\python.exe', '.venv\\Scripts\\pythonw.exe', '.venv\\Scripts\\python.exe')) {{
  $cand = Join-Path $agentWorkDir $venvRel
  if (Test-Path -LiteralPath $cand) {{ $pyCmd = [pscustomobject]@{{ Source = (Resolve-Path -LiteralPath $cand).Path }}; break }}
}}
if (-not $pyCmd) {{
  $pyCmd = Get-Command pythonw, python -ErrorAction SilentlyContinue | Where-Object {{ $_.Source -and ($_.Source -notlike '*\\WindowsApps\\*') }} | Select-Object -First 1
}}

# First-run per-installation CSPRNG UI key rotation (preserving existing signed ledger keys) + every-launch sync
$initMarker = Join-Path $root 'Profile\\.ui_key_initialized'
$keyFile = Join-Path $agentWorkDir 'outputs\\local_ui_key.txt'
$ledgerFile = Join-Path $agentWorkDir 'outputs\\action_ledger.jsonl'
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $keyFile) | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $root 'Profile') | Out-Null
if (-not (Test-Path -LiteralPath $keyFile) -or (-not (Test-Path -LiteralPath $initMarker) -and -not (Test-Path -LiteralPath $ledgerFile))) {{
  $bytes = New-Object byte[] 32
  $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
  $rng.GetBytes($bytes)
  $rng.Dispose()
  $genKey = ($bytes | ForEach-Object {{ $_.ToString('x2') }}) -join ''
  [System.IO.File]::WriteAllText($keyFile, ($genKey + "`n"), [System.Text.UTF8Encoding]::new($false))
}}
if (-not (Test-Path -LiteralPath $initMarker)) {{
  [System.IO.File]::WriteAllText($initMarker, "ok`n", [System.Text.UTF8Encoding]::new($false))
}}
$activeKey = (Get-Content -Raw -LiteralPath $keyFile).Trim()
if ($activeKey.Length -ge 32) {{
  $bundledKeyFile = Join-Path $root 'Agent\\outputs\\local_ui_key.txt'
  if ((Split-Path -Parent $bundledKeyFile) -ne (Split-Path -Parent $keyFile) -and (Test-Path -LiteralPath (Split-Path -Parent $bundledKeyFile))) {{
    [System.IO.File]::WriteAllText($bundledKeyFile, ($activeKey + "`n"), [System.Text.UTF8Encoding]::new($false))
  }}
  $homeLumDir = Join-Path $HOME '.luminara-browser'
  New-Item -ItemType Directory -Force -Path $homeLumDir | Out-Null
  [System.IO.File]::WriteAllText((Join-Path $homeLumDir 'local_ui_key.txt'), ($activeKey + "`n"), [System.Text.UTF8Encoding]::new($false))
  $jsSafeKey = $activeKey.Replace('\\', '\\\\').Replace('"', '\\"')
  $rxSafeKey = $jsSafeKey.Replace('$', '$$')
  foreach ($rel in @('App\\luminara_pages\\newtab.html', 'App\\luminara_pages\\workspace.html', 'App\\forge_ntp\\index.html', 'App\\extensions\\luminara-copilot\\sidepanel.js', 'App\\extensions\\luminara-newtab\\newtab.js', 'App\\extensions\\luminara-newtab\\workspace.js')) {{
    $p = Join-Path $root $rel
    if (Test-Path -LiteralPath $p) {{
      $rawTxt = [System.IO.File]::ReadAllText($p, [System.Text.Encoding]::UTF8)
      $synced = [regex]::Replace($rawTxt, 'const UI_KEY = "[^"]*";', ('const UI_KEY = "' + $rxSafeKey + '";'))
      if ($synced -ne $rawTxt) {{
        [System.IO.File]::WriteAllText($p, $synced, [System.Text.UTF8Encoding]::new($false))
      }}
    }}
  }}
}}

# Per-session CSPRNG rotation for Privacy Shield v3 farbling seed (prevents static cross-restart fingerprint!)
$farbleFile = Join-Path $root 'App\\extensions\\forge-shield\\farble.js'
if (Test-Path -LiteralPath $farbleFile) {{
  $sBytes = New-Object byte[] 16
  $sRng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
  $sRng.GetBytes($sBytes)
  $sRng.Dispose()
  $sHex = ($sBytes | ForEach-Object {{ $_.ToString('x2') }}) -join ''
  $fRaw = [System.IO.File]::ReadAllText($farbleFile, [System.Text.Encoding]::UTF8)
  $fUpdated = [regex]::Replace($fRaw, 'const SESSION_KEY = "[^"]+";', ('const SESSION_KEY = "' + $sHex + '";'))
  [System.IO.File]::WriteAllText($farbleFile, $fUpdated, [System.Text.UTF8Encoding]::new($false))
}}

if ({cobrowse_ps} -and $pyCmd) {{
  $listening = Get-NetTCPConnection -LocalPort {profile.agent_port} -State Listen -ErrorAction SilentlyContinue
  if (-not $listening) {{
    $daemonArgs = @('-m', 'forge', 'agent-daemon', '--forge-root', $agentWorkDir, '--port', '{profile.agent_port}', '--cdp-port', '{profile.cdp_port}') | ForEach-Object {{ Quote-WinArg $_ }}
    Start-Process -WindowStyle Hidden -FilePath $pyCmd.Source -WorkingDirectory $agentWorkDir -ArgumentList $daemonArgs
    for ($i = 0; $i -lt 20; $i++) {{
      if (Get-NetTCPConnection -LocalPort {profile.agent_port} -State Listen -ErrorAction SilentlyContinue) {{ break }}
      Start-Sleep -Milliseconds 100
    }}
  }}
}}

$extShield = Join-Path $root 'App\\extensions\\forge-shield'
$extCopilot = Join-Path $root 'App\\extensions\\luminara-copilot'
$extNewtab = Join-Path $root 'App\\extensions\\luminara-newtab'
$extList = if ({cobrowse_ps}) {{ @($extShield, $extCopilot, $extNewtab) -join ',' }} else {{ @($extShield, $extNewtab) -join ',' }}
$chrome = Join-Path $root 'App\\chrome.exe'
$argList = @(
  ("--user-data-dir=" + (Join-Path $root 'Profile')),
  ("--load-extension=" + $extList),
  {ps_switches_lines},
  "{default_home_url}"
) + $args

$quotedArgs = $argList | ForEach-Object {{ Quote-WinArg $_ }}
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
        "newtab_extension": str(newtab_ext_dir),
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
        if wait_for_cdp_page_ready(cdp, "Boolean(document.getElementById('omniForm') || document.body)", timeout=20.0):
            val = cdp.evaluate_js(None, "document.documentElement ? document.documentElement.outerHTML : ''")
            dom = val if isinstance(val, str) else ""
    finally:
        cdp.close()
        terminate_browser_process(proc)

    return {
        "exit_code": 0 if dom else 1,
        "dom_length": len(dom),
        "rendered_custom_ntp": ("Zero Google Telemetry" in dom) or ("omniForm" in dom) or ("searchForm" in dom),
    }
