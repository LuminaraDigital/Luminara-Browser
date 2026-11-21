"""MV3 SidePanel Copilot Extension, PNG Icon Generator & Shadow-DOM Command Palette (`forge/luminara_copilot_ext.py`)."""

from __future__ import annotations

import html
import json
from pathlib import Path
import struct
import zlib

from .models import ForkProfile

ENCODING = "utf-8"


def _js_json(val: object) -> str:
    return json.dumps(val, ensure_ascii=False).replace("</", "<\\/")


SHARED_UI_TOKENS_CSS = """    :root {
      color-scheme: dark light;
      --bg-0: light-dark(oklch(0.975 0.005 255), oklch(0.115 0.012 255));
      --bg-1: light-dark(oklch(0.95 0.007 255), oklch(0.15 0.013 255));
      --bg-2: light-dark(oklch(0.915 0.009 255), oklch(0.188 0.015 255));
      --ink-0: light-dark(oklch(0.15 0.015 255), oklch(0.965 0.005 255));
      --ink-1: light-dark(oklch(0.34 0.015 255), oklch(0.78 0.012 255));
      --ink-2: light-dark(oklch(0.44 0.015 255), oklch(0.67 0.012 255));
      --accent: light-dark(oklch(0.45 0.15 162), oklch(0.75 0.16 162));
      --amber: light-dark(oklch(0.48 0.14 72), oklch(0.79 0.15 78));
      --danger: light-dark(oklch(0.50 0.19 26), oklch(0.68 0.18 25));
      --hairline: light-dark(oklch(0.15 0.01 255 / 0.12), oklch(1 0 0 / 0.09));
      --border-control: light-dark(oklch(0.15 0.01 255 / 0.34), oklch(1 0 0 / 0.28));
      --specular: inset 0 1px 0 0 oklch(1 0 0 / 0.1);
      --font-sans: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      --font-mono: 'JetBrains Mono', 'Cascadia Code', Consolas, monospace;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    :focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
    .sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }"""


def make_solid_emerald_png(size: int) -> bytes:
    """Generate a valid RGBA PNG icon (`#10b981` rounded badge on `#0f131a`) in pure Python stdlib."""
    rows: list[bytes] = []
    pad = max(1, size // 8)
    for y in range(size):
        row = bytearray([0])  # Filter type 0 (None)
        for x in range(size):
            inside = pad <= x < (size - pad) and pad <= y < (size - pad)
            if inside:
                row.extend((16, 185, 129, 255))
            else:
                row.extend((15, 19, 26, 255))
        rows.append(bytes(row))

    def _chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack("!I", len(data)) + tag + data + struct.pack("!I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack("!IIBBBBB", size, size, 8, 6, 0, 0, 0)
    idat = zlib.compress(b"".join(rows), level=9)
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", idat) + _chunk(b"IEND", b"")


def build_palette_js(search_url: str, agent_port: int = 8796) -> str:
    """Build Shadow-DOM isolated `Alt+K` / `Ctrl+Shift+K` Command Palette script (works on MV3, HTTP & file://)."""
    search_tpl_json = _js_json(search_url)
    return f"""(() => {{
  if (window.__luminaraCmdPalette) return;
  window.__luminaraCmdPalette = true;
  const SEARCH_TPL = {search_tpl_json};
  let hostEl = null;
  let prevFocus = null;
  function close() {{
    if (hostEl) {{ hostEl.remove(); hostEl = null; }}
    if (prevFocus && typeof prevFocus.focus === 'function') {{
      try {{ prevFocus.focus(); }} catch (_e) {{}}
    }}
    prevFocus = null;
  }}
  function openInternalPage(file, fallbackPath) {{
    const fallbackOpen = () => {{
      if (location.protocol === 'file:' && location.pathname.includes('luminara_pages/')) {{
        window.open('./' + file, '_blank');
      }} else if (/^https?:$/i.test(location.protocol) && /^(127\\.0\\.0\\.1|localhost|\\[::1\\])$/i.test(location.hostname)) {{
        window.open(location.protocol + '//' + location.hostname + ':{agent_port}' + fallbackPath, '_blank');
      }} else {{
        window.open('http://127.0.0.1:{agent_port}' + fallbackPath, '_blank');
      }}
    }};
    try {{
      if (typeof chrome !== 'undefined' && chrome.runtime && typeof chrome.runtime.sendMessage === 'function') {{
        const p = chrome.runtime.sendMessage({{ luminaraOpenPage: file }});
        if (p && typeof p.catch === 'function') p.catch(fallbackOpen);
        return;
      }}
    }} catch (_e) {{}}
    fallbackOpen();
  }}
  function open() {{
    if (hostEl) {{ close(); return; }}
    prevFocus = document.activeElement;
    hostEl = document.createElement('div');
    hostEl.id = '__luminara_cmd_palette';
    hostEl.style.cssText = 'position:fixed;inset:0;z-index:2147483647;';
    const root = hostEl.attachShadow ? hostEl.attachShadow({{ mode: 'open' }}) : hostEl;
    const overlay = document.createElement('div');
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.setAttribute('aria-label', 'Luminara Command Palette');
    overlay.tabIndex = -1;
    overlay.style.cssText = 'color-scheme:dark light;position:fixed;inset:0;background:oklch(0.08 0.01 255 / 0.58);backdrop-filter:blur(8px);display:grid;place-items:start center;padding-top:14vh;font-family:Inter,-apple-system,Segoe UI,sans-serif;';
    const box = document.createElement('div');
    box.style.cssText = 'width:min(560px,92vw);background:light-dark(oklch(0.95 0.007 255),oklch(0.15 0.013 255));color:light-dark(oklch(0.15 0.015 255),oklch(0.965 0.005 255));border:1px solid light-dark(oklch(0.45 0.15 162 / 0.45),oklch(0.75 0.16 162 / 0.45));border-radius:16px;padding:12px;box-shadow:0 24px 60px oklch(0 0 0 / 0.45);';
    const inp = document.createElement('input');
    inp.setAttribute('aria-label', 'Command or URL');
    inp.placeholder = 'Luminara Command Palette — URL, search, or /workspace, /telemetry, /newtab (Esc to close)';
    inp.style.cssText = 'width:100%;box-sizing:border-box;background:light-dark(oklch(0.915 0.009 255),oklch(0.115 0.012 255));color:inherit;border:1px solid light-dark(oklch(0.15 0.01 255 / 0.34),oklch(1 0 0 / 0.28));border-radius:10px;padding:10px 12px;font-size:14px;outline:2px solid light-dark(oklch(0.45 0.15 162),oklch(0.75 0.16 162));outline-offset:2px;';
    for (const evName of ['keydown', 'keyup', 'keypress']) {{
      inp.addEventListener(evName, (ev) => ev.stopPropagation());
    }}
    overlay.addEventListener('keydown', (e) => {{
      if (e.key === 'Escape') {{ e.preventDefault(); close(); }}
      if (e.key === 'Tab') {{ e.preventDefault(); inp.focus(); }}
    }});
    inp.addEventListener('keydown', (e) => {{
      if (e.key === 'Escape') {{ e.preventDefault(); close(); return; }}
      if (e.key === 'Tab') {{ e.preventDefault(); inp.focus(); return; }}
      if (e.key === 'Enter') {{
        e.preventDefault();
        const q = inp.value.trim();
        close();
        if (!q) return;
        if (q === '/workspace') openInternalPage('workspace.html', '/workspace');
        else if (q === '/telemetry') openInternalPage('workspace.html#view=telemetry', '/workspace#view=telemetry');
        else if (q === '/newtab') openInternalPage('newtab.html', '/newtab');
        else if (/^https?:\\/\\//i.test(q)) location.href = q;
        else if (!/\\s/.test(q) && /^(localhost|127\\.0\\.0\\.1|\\[::1\\])(:\\d+)?(\\/.*)?$/i.test(q)) location.href = 'http://' + q;
        else if (!/\\s/.test(q) && /^[a-z0-9-]+(\\.[a-z0-9-]+)+(:\\d+)?(\\/.*)?$/i.test(q)) location.href = 'https://' + q;
        else location.href = SEARCH_TPL.replace('{{searchTerms}}', encodeURIComponent(q));
      }}
    }});
    box.appendChild(inp);
    overlay.appendChild(box);
    overlay.addEventListener('click', (e) => {{ if (e.target === overlay) close(); }});
    root.appendChild(overlay);
    document.documentElement.appendChild(hostEl);
    inp.focus();
  }}
  window.addEventListener('keydown', (e) => {{
    const k = (e.key || '').toLowerCase();
    if ((e.altKey && k === 'k') || ((e.ctrlKey || e.metaKey) && e.shiftKey && k === 'k')) {{
      e.preventDefault();
      e.stopPropagation();
      open();
    }}
  }}, true);
}})();
"""


def write_copilot_extension(
    ext_dir: Path,
    profile: ForkProfile,
    workspace_uri: str = "",
    agent_port: int = 8796,
    ui_key: str | None = None,
) -> None:
    """Write the built-in MV3 `luminara-copilot` Chrome Side Panel co-browsing extension."""
    ext_dir.mkdir(parents=True, exist_ok=True)
    if ui_key is None:
        ui_key = ""
        for anc in ext_dir.resolve().parents:
            if (anc / "forge" / "__init__.py").exists() or (anc / "outputs").exists():
                try:
                    from .http_base import ensure_local_ui_key

                    ui_key = ensure_local_ui_key(anc)
                except Exception:  # noqa: BLE001
                    pass
                break
    from .luminara_logo3d import write_extension_icons

    write_extension_icons(ext_dir)

    daemon_base = f"http://127.0.0.1:{agent_port}"
    resolved_ws_url = workspace_uri if workspace_uri.startswith("http") else f"{daemon_base}/workspace"

    manifest = {
        "manifest_version": 3,
        "name": f"{profile.brand_name} Agent Copilot",
        "version": "3.1.0",
        "description": "Simultaneous Human + AI Co-Browsing Side Panel: Set-of-Marks DOM HUD, Mutation Firewall, Dialog Supervisor, Generative UI, and Human Takeover.",
        "permissions": ["sidePanel", "tabs"],
        "host_permissions": [f"{daemon_base}/*"],
        "icons": {"16": "icons/icon16.png", "48": "icons/icon48.png", "128": "icons/icon128.png"},
        "content_security_policy": {
            "extension_pages": "script-src 'self'; object-src 'none'; base-uri 'none';"
        },
        "background": {"service_worker": "background.js"},
        "action": {
            "default_title": f"Open {profile.brand_name} Copilot",
            "default_icon": {"16": "icons/icon16.png", "48": "icons/icon48.png"},
        },
        "side_panel": {"default_path": "sidepanel.html"},
    }
    (ext_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding=ENCODING, newline="\n")

    background_js = """function enableSidePanelOnClick() {
  if (chrome.sidePanel && chrome.sidePanel.setPanelBehavior) {
    chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});
  }
}
enableSidePanelOnClick();
chrome.runtime.onInstalled.addListener(enableSidePanelOnClick);
chrome.runtime.onStartup.addListener(enableSidePanelOnClick);
"""
    (ext_dir / "background.js").write_text(background_js, encoding=ENCODING, newline="\n")

    sidepanel_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="color-scheme" content="dark light" />
  <link rel="icon" type="image/png" href="icons/icon48.png" />
  <title>{html.escape(profile.brand_name)} Copilot</title>
  <style>
    :root {{
      color-scheme: dark light;
      --bg-0: light-dark(oklch(0.975 0.005 255), oklch(0.115 0.012 255));
      --bg-1: light-dark(oklch(0.95 0.007 255), oklch(0.15 0.013 255));
      --bg-2: light-dark(oklch(0.915 0.009 255), oklch(0.188 0.015 255));
      --ink-0: light-dark(oklch(0.15 0.015 255), oklch(0.965 0.005 255));
      --ink-1: light-dark(oklch(0.34 0.015 255), oklch(0.78 0.012 255));
      --hairline: light-dark(oklch(0.15 0.01 255 / 0.12), oklch(1 0 0 / 0.09));
      --border-control: light-dark(oklch(0.15 0.01 255 / 0.34), oklch(1 0 0 / 0.28));
      --accent: light-dark(oklch(0.45 0.15 162), oklch(0.75 0.16 162));
      --warn: light-dark(oklch(0.48 0.14 72), oklch(0.79 0.15 78));
      --danger: light-dark(oklch(0.50 0.19 26), oklch(0.68 0.18 25));
    }}
    * {{ box-sizing: border-box; }}
    :focus-visible {{ outline: 2px solid var(--accent); outline-offset: 2px; }}
    body {{
      margin: 0; padding: 12px; background: var(--bg-0); color: var(--ink-0);
      font: 12px/1.45 -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      display: grid; gap: 12px; font-variant-numeric: tabular-nums;
    }}
    .card {{
      background: var(--bg-1); border: 1px solid var(--hairline);
      border-radius: 14px; padding: 12px; display: grid; gap: 8px; min-width: 0;
    }}
    .kicker {{ font: 600 10px/1.2 Consolas, monospace; letter-spacing: 0.09em; text-transform: uppercase; color: var(--accent); }}
    button {{
      min-height: 32px;
      padding: 8px 10px; border-radius: 8px; border: 1px solid var(--border-control);
      background: var(--bg-2); color: var(--ink-0); font: 600 11px Consolas, monospace; cursor: pointer;
    }}
    button:disabled {{ opacity: 0.5; cursor: wait; }}
    button.primary {{ border-color: color-mix(in oklch, var(--accent) 55%, transparent); background: color-mix(in oklch, var(--accent) 16%, transparent); }}
    button.warn {{ border-color: color-mix(in oklch, var(--warn) 55%, transparent); color: var(--warn); }}
    button.danger {{ border-color: color-mix(in oklch, var(--danger) 55%, transparent); color: var(--danger); }}
    textarea {{
      width: 100%; background: var(--bg-0);
      border: 1px solid var(--border-control); border-radius: 8px; color: var(--ink-0); padding: 8px; font-size: 12px;
    }}
    pre {{
      margin: 0; max-height: 220px; overflow: auto; background: var(--bg-0);
      padding: 8px; border-radius: 8px; font: 11px/1.35 Consolas, monospace; color: var(--ink-1); white-space: pre-wrap; overflow-wrap: anywhere;
    }}
    .mut-row {{
      display: grid; gap: 6px; padding: 8px; border-radius: 8px; background: var(--bg-2); border: 1px solid color-mix(in oklch, var(--warn) 45%, transparent);
    }}
  </style>
</head>
<body>
  <div class="card">
    <div class="kicker">● {html.escape(profile.brand_name)} Co-Presence</div>
    <div id="connState" role="status" aria-live="polite">Connecting to Agent Daemon (:{agent_port})...</div>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,115px),1fr));gap:6px;">
      <button id="btnSnap" type="button" class="primary">Index [1..N] DOM</button>
      <button id="btnRefreshTabs" type="button">Refresh Tabs</button>
      <button id="btnExtractMd" type="button">Extract Markdown</button>
      <button id="btnGenUi" type="button">Page → GenUI</button>
      <button id="btnOpenWs" type="button">Open Workspace</button>
      <button id="btnOpenTele" type="button">Telemetry Cockpit</button>
      <button id="btnWatchPage" type="button">Watch Tab URL</button>
      <button id="btnVerifyLedger" type="button">Verify Ledger</button>
      <button id="btnAcceptDlg" type="button">Accept Dialog</button>
      <button id="btnDismissDlg" type="button">Dismiss Dialog</button>
      <button id="btnClear" type="button">Clear HUD</button>
      <button id="btnTakeover" type="button" class="warn">Human Takeover</button>
      <button id="btnResumeHandoff" type="button" class="warn" style="display:none;">Resume Handoff ↻</button>
    </div>
  </div>

  <div class="card" id="mutationCard" style="display:none;">
    <div class="kicker" style="color:var(--warn);">⚠ Network Mutation Firewall Savepoints</div>
    <div id="mutationList" style="display:grid;gap:6px;"></div>
  </div>

  <div class="card">
    <label class="kicker" for="goalBox">Autonomous Tab Goal</label>
    <textarea id="goalBox" rows="3" placeholder="e.g. Type 'Quantum' and click Apply Filter..."></textarea>
    <button id="btnRunGoal" type="button" class="primary">Run Goal on Live Window ↵</button>
  </div>

  <div class="card">
    <div class="kicker">Live Telemetry &amp; LUM-* Receipt</div>
    <pre id="outLog" role="status" aria-live="polite">Ready. Human + AI share this window simultaneously.</pre>
  </div>

  <script src="sidepanel.js"></script>
</body>
</html>
"""
    (ext_dir / "sidepanel.html").write_text(sidepanel_html, encoding=ENCODING, newline="\n")

    sidepanel_js = f"""const DAEMON = {_js_json(daemon_base)};
const WORKSPACE_URL = {_js_json(resolved_ws_url)};
const SLUG = {_js_json(profile.slug)};
const UI_KEY = {_js_json(ui_key)};
const logEl = document.getElementById('outLog');
const connEl = document.getElementById('connState');

async function callDaemon(path, body, timeoutMs = 15000, customSignal = null) {{
  const isPost = body !== undefined;
  const headers = {{}};
  if (UI_KEY) headers['X-Luminara-UI-Key'] = UI_KEY;
  if (isPost) headers['Content-Type'] = 'application/json';
  const r = await fetch(DAEMON + path, {{
    method: isPost ? 'POST' : 'GET',
    headers,
    body: isPost ? JSON.stringify(body) : undefined,
    signal: customSignal || AbortSignal.timeout(timeoutMs)
  }});
  const data = await r.json().catch(() => ({{}}));
  if (!r.ok) throw new Error(data.error || ('HTTP ' + r.status));
  return data;
}}

async function resolveActiveTargetId() {{
  try {{
    if (!chrome.tabs || !chrome.tabs.query) return undefined;
    const [active] = await chrome.tabs.query({{ active: true, lastFocusedWindow: true }});
    if (!active || !active.url || /^(chrome(-extension)?:|devtools:|about:)/i.test(active.url)) return undefined;
    const tb = await callDaemon('/api/agent/tabs', undefined, 2500);
    const hit = (tb.tabs || []).find(t => t.url === active.url)
      || (tb.tabs || []).find(t => active.title && t.title === active.title);
    return hit ? hit.target_id : undefined;
  }} catch (_e) {{
    return undefined;
  }}
}}

async function runAction(btn, busyText, fn) {{
  const orig = btn.textContent;
  btn.disabled = true;
  btn.textContent = busyText;
  try {{
    await fn();
  }} catch (err) {{
    logEl.textContent = 'Error: ' + (err.message || String(err)) + '\\nEnsure Launch-' + SLUG + '.cmd is running.';
  }} finally {{
    btn.disabled = false;
    btn.textContent = orig;
  }}
}}

let pendingHandoffRunId = null;

async function openAuthenticatedWorkspace(view = '') {{
  let targetUrl = WORKSPACE_URL;
  const hashParts = [];
  if (view) hashParts.push('view=' + encodeURIComponent(view));
  try {{
    const tokRes = await callDaemon('/api/agent/session-token', {{ scope: 'ui', ttl_sec: 900 }});
    if (tokRes && tokRes.token) hashParts.push('lum_tok=' + encodeURIComponent(tokRes.token));
  }} catch (_e) {{}}
  if (hashParts.length) targetUrl += '#' + hashParts.join('&');
  if (chrome.tabs) chrome.tabs.create({{ url: targetUrl }});
}}

function renderPendingMutations(pending) {{
  const card = document.getElementById('mutationCard');
  const box = document.getElementById('mutationList');
  if (!card || !box) return;
  box.replaceChildren();
  if (!pending || !pending.length) {{
    card.style.display = 'none';
    return;
  }}
  card.style.display = 'grid';
  pending.forEach(m => {{
    const row = document.createElement('div');
    row.className = 'mut-row';
    const info = document.createElement('div');
    info.style.overflowWrap = 'anywhere';
    info.textContent = `[${{m.risk_level || 'MEDIUM'}}] ${{m.method}} ${{m.url}}`;
    const acts = document.createElement('div');
    acts.style.cssText = 'display:flex;gap:6px;';
    const bApp = document.createElement('button');
    bApp.type = 'button';
    bApp.className = 'primary';
    bApp.textContent = 'Approve ✓';
    bApp.onclick = () => runAction(bApp, 'Approving...', async () => {{
      const res = await callDaemon('/api/agent/mutations', {{ action: 'approve', mutation_id: m.mutation_id }});
      logEl.textContent = JSON.stringify(res, null, 2);
      await ping();
    }});
    const bRej = document.createElement('button');
    bRej.type = 'button';
    bRej.className = 'danger';
    bRej.textContent = 'Reject ✕';
    bRej.onclick = () => runAction(bRej, 'Rejecting...', async () => {{
      const res = await callDaemon('/api/agent/mutations', {{ action: 'reject', mutation_id: m.mutation_id }});
      logEl.textContent = JSON.stringify(res, null, 2);
      await ping();
    }});
    acts.append(bApp, bRej);
    row.append(info, acts);
    box.appendChild(row);
  }});
}}

async function ping() {{
  try {{
    const [st, seq] = await Promise.all([
      callDaemon('/api/agent/status', undefined, 2500),
      callDaemon('/api/agent/sequences', undefined, 2500).catch(() => ({{ active_blocks: [] }}))
    ]);
    const blkCnt = (seq.active_blocks || []).length;
    connEl.textContent = `Daemon LIVE · ${{st.open_tabs}} tab(s) · CDP ${{st.cdp_connected ? 'OK' : 'wait'}}${{blkCnt ? ' · ⚠ ' + blkCnt + ' Seq Block' : ''}}`;
    const handoffs = st.active_handoffs || [];
    pendingHandoffRunId = handoffs.length ? handoffs[0].run_id : null;
    const btnRes = document.getElementById('btnResumeHandoff');
    if (btnRes) btnRes.style.display = pendingHandoffRunId ? 'inline-block' : 'none';
    renderPendingMutations(st.pending_mutations || []);
  }} catch (_e) {{
    connEl.textContent = 'Daemon offline — launch via Launch-' + SLUG + '.cmd';
  }}
}}

const btnSnap = document.getElementById('btnSnap');
btnSnap.onclick = () => runAction(btnSnap, 'Indexing...', async () => {{
  const target_id = await resolveActiveTargetId();
  const res = await callDaemon('/api/agent/snapshot', {{ target_id, show_badges: true, include_frames: true, agent_id: 'sidepanel-copilot' }});
  logEl.textContent = JSON.stringify(res, null, 2);
}});

const btnRefreshTabs = document.getElementById('btnRefreshTabs');
btnRefreshTabs.onclick = () => runAction(btnRefreshTabs, 'Refreshing...', async () => {{
  const res = await callDaemon('/api/agent/tabs');
  logEl.textContent = JSON.stringify(res, null, 2);
}});

const btnExtractMd = document.getElementById('btnExtractMd');
btnExtractMd.onclick = () => runAction(btnExtractMd, 'Extracting...', async () => {{
  const target_id = await resolveActiveTargetId();
  const res = await callDaemon('/api/agent/extract', {{ target_id, format: 'md' }});
  logEl.textContent = res.formatted || JSON.stringify(res, null, 2);
}});

const btnOpenWs = document.getElementById('btnOpenWs');
btnOpenWs.onclick = () => runAction(btnOpenWs, 'Opening...', async () => {{
  await openAuthenticatedWorkspace();
}});

const btnOpenTele = document.getElementById('btnOpenTele');
btnOpenTele.onclick = () => runAction(btnOpenTele, 'Opening...', async () => {{
  await openAuthenticatedWorkspace('telemetry');
}});

const btnWatchPage = document.getElementById('btnWatchPage');
btnWatchPage.onclick = () => runAction(btnWatchPage, 'Watching...', async () => {{
  const [active] = (chrome.tabs && chrome.tabs.query) ? await chrome.tabs.query({{ active: true, lastFocusedWindow: true }}) : [];
  if (!active || !active.url || !/^https?:\\/\\//i.test(active.url)) throw new Error('Focus an http(s) tab to create a Web Monitor.');
  const res = await callDaemon('/api/agent/monitors', {{ action: 'create', name: active.title || active.url, target_url: active.url, agent_id: 'sidepanel-copilot' }});
  logEl.textContent = 'Created Web Monitor:\\n' + JSON.stringify(res, null, 2);
}});

const btnVerifyLedger = document.getElementById('btnVerifyLedger');
btnVerifyLedger.onclick = () => runAction(btnVerifyLedger, 'Verifying...', async () => {{
  const res = await callDaemon('/api/agent/ledger/verify');
  logEl.textContent = JSON.stringify(res, null, 2);
}});

const btnAcceptDlg = document.getElementById('btnAcceptDlg');
btnAcceptDlg.onclick = () => runAction(btnAcceptDlg, 'Accepting...', async () => {{
  const target_id = await resolveActiveTargetId();
  const res = await callDaemon('/api/agent/dialog', {{ target_id, action: 'accept', agent_id: 'sidepanel-copilot' }});
  logEl.textContent = JSON.stringify(res, null, 2);
}});

const btnDismissDlg = document.getElementById('btnDismissDlg');
btnDismissDlg.onclick = () => runAction(btnDismissDlg, 'Dismissing...', async () => {{
  const target_id = await resolveActiveTargetId();
  const res = await callDaemon('/api/agent/dialog', {{ target_id, action: 'dismiss', agent_id: 'sidepanel-copilot' }});
  logEl.textContent = JSON.stringify(res, null, 2);
}});

const btnClear = document.getElementById('btnClear');
btnClear.onclick = () => runAction(btnClear, 'Clearing...', async () => {{
  const target_id = await resolveActiveTargetId();
  const res = await callDaemon('/api/agent/act', {{ target_id, action: 'clear_hud' }});
  logEl.textContent = JSON.stringify(res, null, 2);
}});

const btnTakeover = document.getElementById('btnTakeover');
btnTakeover.onclick = () => runAction(btnTakeover, 'Preempting...', async () => {{
  const target_id = await resolveActiveTargetId();
  const res = await callDaemon('/api/agent/act', {{ target_id, action: 'human_takeover' }});
  logEl.textContent = 'Human preempted lease:\\n' + JSON.stringify(res, null, 2);
}});

const btnResumeHandoff = document.getElementById('btnResumeHandoff');
btnResumeHandoff.onclick = () => runAction(btnResumeHandoff, 'Resuming...', async () => {{
  if (!pendingHandoffRunId) {{
    logEl.textContent = 'No active PAUSED_HUMAN_HANDOFF run to resume.';
    return;
  }}
  const res = await callDaemon('/api/agent/handoff/resume', {{ run_id: pendingHandoffRunId }}, 35000);
  logEl.textContent = JSON.stringify(res, null, 2);
  await ping();
}});

const btnGenUi = document.getElementById('btnGenUi');
btnGenUi.onclick = () => runAction(btnGenUi, 'Capturing...', async () => {{
  const target_id = await resolveActiveTargetId();
  const res = await callDaemon('/api/agent/genui', {{ target_id }});
  logEl.textContent = `Synthesized ${{res.generative_ui ? res.generative_ui.entity_count : 0}} entities.\\nReceipt: ${{res.receipt ? res.receipt.receipt_id : ''}}`;
  await openAuthenticatedWorkspace();
}});

const btnRunGoal = document.getElementById('btnRunGoal');
let activeGoalAbort = null;
btnRunGoal.onclick = async () => {{
  if (activeGoalAbort) {{
    activeGoalAbort.abort();
    activeGoalAbort = null;
    callDaemon('/api/agent/act', {{ action: 'human_takeover' }}).catch(() => {{}});
    logEl.textContent = 'Goal cancelled by user.';
    return;
  }}
  const goalBox = document.getElementById('goalBox');
  const goal = goalBox.value.trim();
  if (!goal) {{
    goalBox.focus();
    logEl.textContent = 'Enter a goal instruction above before clicking Run Goal.';
    return;
  }}
  const orig = btnRunGoal.textContent;
  const runCtrl = new AbortController();
  activeGoalAbort = runCtrl;
  btnRunGoal.textContent = 'STOP ■';
  logEl.textContent = 'Executing perceive -> decide -> act...';
  try {{
    const target_id = await resolveActiveTargetId();
    const res = await callDaemon('/api/agent/goal', {{ goal, target_id, agent_id: 'sidepanel-copilot' }}, 35000, runCtrl.signal);
    if (res && res.status === 'PAUSED_HUMAN_HANDOFF' && res.run_id) {{
      pendingHandoffRunId = res.run_id;
      btnResumeHandoff.style.display = 'inline-block';
    }}
    logEl.textContent = JSON.stringify(res, null, 2);
  }} catch (err) {{
    if (err && err.name !== 'AbortError') {{
      logEl.textContent = 'Error: ' + (err.message || String(err));
    }}
  }} finally {{
    if (activeGoalAbort === runCtrl) {{
      activeGoalAbort = null;
      btnRunGoal.textContent = orig;
    }}
  }}
}};

ping();
setInterval(ping, 4000);
"""
    (ext_dir / "sidepanel.js").write_text(sidepanel_js, encoding=ENCODING, newline="\n")
