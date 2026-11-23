"""MV3 Team Side Panel Extension, PNG Icon Generator & Interactive Fuzzy Command Palette (`forge/luminara_copilot_ext.py`)."""

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
      --bg-0: light-dark(#FAF9F6, #141519); --bg-rail: light-dark(#F3F1EC, #1A1C22);
      --bg-1: light-dark(#FFFFFF, #1F2229); --bg-2: light-dark(#ECEAE3, #282C35);
      --ink-0: light-dark(#1C1E24, #F6F5F0); --ink-1: light-dark(#555A66, #B5BAC6); --ink-2: light-dark(#5A5F6B, #8F96A5);
      --accent: light-dark(#117A5E, #3CD0A3); --accent-ink: light-dark(#FFFFFF, #081C15);
      --bot-remy: #16A095; --bot-dana: #2E7CF6; --bot-pi: #7C4DFF;
      --amber: light-dark(#8F5906, #F2B649); --warn: var(--amber);
      --danger: light-dark(#BA2D2D, #F06E6E); --danger-ink: light-dark(#FFFFFF, #1B0909);
      --hairline: light-dark(#E4E2DB, #2C303A); --border-control: light-dark(#8C8980, #676E82);
      --specular: inset 0 1px 0 0 rgba(255, 255, 255, 0.08);
      --card-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.08), 0 14px 34px -16px rgba(0, 0, 0, 0.45);
      --r-shell: 20px; --r-card: 16px; --r-control: 10px; --r-pill: 999px;
      --ease-out: cubic-bezier(0.16, 1, 0.3, 1);
      --font-sans: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      --font-mono: 'JetBrains Mono', 'Cascadia Code', Consolas, monospace;
    }
    @media (prefers-color-scheme: light) {
      :root:not([data-theme="dark"]) {
        --specular: 0 1px 2px rgba(28, 30, 36, 0.05);
        --card-shadow: 0 1px 2px rgba(28, 30, 36, 0.05), 0 10px 28px -14px rgba(28, 30, 36, 0.14);
      }
    }
    :root[data-theme="light"] {
      color-scheme: light; --specular: 0 1px 2px rgba(28, 30, 36, 0.05);
      --card-shadow: 0 1px 2px rgba(28, 30, 36, 0.05), 0 10px 28px -14px rgba(28, 30, 36, 0.14);
    }
    :root[data-theme="dark"] {
      color-scheme: dark; --specular: inset 0 1px 0 0 rgba(255, 255, 255, 0.08);
      --card-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.08), 0 14px 34px -16px rgba(0, 0, 0, 0.45);
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    :focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
    .sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }"""


def make_solid_emerald_png(size: int) -> bytes:
    """Generate a valid RGBA PNG icon (`#117A5E` rounded badge on `#141519`) in pure Python stdlib."""
    rows: list[bytes] = []
    pad = max(1, size // 8)
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            inside = pad <= x < (size - pad) and pad <= y < (size - pad)
            row.extend((17, 122, 94, 255) if inside else (20, 21, 25, 255))
        rows.append(bytes(row))

    def _chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack("!I", len(data)) + tag + data + struct.pack("!I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack("!IIBBBBB", size, size, 8, 6, 0, 0, 0)
    idat = zlib.compress(b"".join(rows), level=9)
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", idat) + _chunk(b"IEND", b"")


def build_palette_js(search_url: str, agent_port: int = 8796) -> str:
    """Build Shadow-DOM isolated `Alt+K` / `Ctrl+Shift+K` Interactive Fuzzy Command Palette."""
    search_tpl_json = _js_json(search_url)
    return f"""(() => {{
  if (window.__luminaraCmdPalette) return;
  window.__luminaraCmdPalette = true;
  const SEARCH_TPL = {search_tpl_json};
  const DAEMON_BASE = 'http://127.0.0.1:{agent_port}';
  let hostEl = null, prevFocus = null, liveTabs = [];

  function close() {{
    if (hostEl) {{ hostEl.remove(); hostEl = null; }}
    if (prevFocus && typeof prevFocus.focus === 'function') {{ try {{ prevFocus.focus(); }} catch (_e) {{}} }}
    prevFocus = null;
  }}
  function isLoopbackPage() {{
    return /^https?:$/i.test(location.protocol) && /^(127\\.0\\.0\\.1|localhost|\\[::1\\])$/i.test(location.hostname);
  }}
  function daemonCall(path, body, timeoutMs = 4000) {{
    if (typeof chrome !== 'undefined' && chrome.runtime && typeof chrome.runtime.sendMessage === 'function') {{
      return new Promise((resolve) => {{
        try {{
          chrome.runtime.sendMessage({{ luminaraApi: {{ path, body, timeoutMs }} }}, (resp) => {{
            if (chrome.runtime && chrome.runtime.lastError) {{ resolve(null); return; }}
            resolve(resp && resp.ok ? resp.data : null);
          }});
        }} catch (_e) {{ resolve(null); }}
      }});
    }}
    if (!isLoopbackPage()) return Promise.resolve(null);
    const isPost = body !== undefined, headers = {{}};
    if (typeof UI_KEY === 'string' && UI_KEY) headers['X-Luminara-UI-Key'] = UI_KEY;
    if (isPost) headers['Content-Type'] = 'application/json';
    return fetch(DAEMON_BASE + path, {{
      method: isPost ? 'POST' : 'GET', headers,
      body: isPost ? JSON.stringify(body) : undefined,
      signal: AbortSignal.timeout(timeoutMs),
    }}).then(r => (r.ok ? r.json().catch(() => null) : null)).catch(() => null);
  }}
  function openInternalPage(file, fallbackPath) {{
    const fb = () => {{
      if (location.protocol === 'file:' && location.pathname.includes('luminara_pages/')) window.open('./' + file, '_blank');
      else if (isLoopbackPage()) window.open(location.protocol + '//' + location.hostname + ':{agent_port}' + fallbackPath, '_blank');
      else window.open(DAEMON_BASE + fallbackPath, '_blank');
    }};
    try {{
      if (typeof chrome !== 'undefined' && chrome.runtime && typeof chrome.runtime.sendMessage === 'function') {{
        chrome.runtime.sendMessage({{ luminaraOpenPage: file }}, () => {{
          if (chrome.runtime && chrome.runtime.lastError) fb();
        }});
        return;
      }}
    }} catch (_e) {{}}
    fb();
  }}
  function fuzzyScore(text, query) {{
    if (!query) return 1;
    const t = String(text || '').toLowerCase(), q = String(query || '').toLowerCase().trim();
    if (!q) return 1;
    if (t === q) return 100;
    if (t.startsWith(q)) return 85;
    if (t.includes(q)) return 70;
    let ti = 0, streak = 0;
    for (let qi = 0; qi < q.length; qi++) {{
      const idx = t.indexOf(q[qi], ti);
      if (idx < 0) return 0;
      if (idx === ti) streak++;
      ti = idx + 1;
    }}
    return 25 + streak * 3;
  }}
  function isLikelyUrl(q) {{
    if (/^https?:\\/\\//i.test(q)) return q;
    if (!/\\s/.test(q) && /^(localhost|127\\.0\\.0\\.1|\\[::1\\])(:\\d+)?(\\/.*)?$/i.test(q)) return 'http://' + q;
    if (!/\\s/.test(q) && /^[a-z0-9-]+(\\.[a-z0-9-]+)+(:\\d+)?(\\/.*)?$/i.test(q)) return 'https://' + q;
    return '';
  }}
  function quickCommands() {{
    return [
      {{ group: 'Quick Commands', title: 'Calm Home', meta: '/newtab', keys: 'home newtab start', run: () => openInternalPage('newtab.html', '/newtab') }},
      {{ group: 'Quick Commands', title: 'Live Lens', meta: '/workspace', keys: 'workspace lens compare table', run: () => openInternalPage('workspace.html#view=comparison', '/workspace#view=comparison') }},
      {{ group: 'Quick Commands', title: 'Inbox & Approvals', meta: '/inbox', keys: 'inbox approvals handoff needs you', run: () => openInternalPage('newtab.html#inbox', '/newtab#inbox') }},
      {{ group: 'Quick Commands', title: 'Routines', meta: '/routines', keys: 'routines schedules tasks', run: () => openInternalPage('newtab.html#routines', '/newtab#routines') }},
      {{ group: 'Quick Commands', title: 'Developer Telemetry', meta: '/telemetry', keys: 'developer telemetry cockpit monitors vrt', run: () => openInternalPage('workspace.html#view=telemetry', '/workspace#view=telemetry') }},
      {{ group: 'Quick Commands', title: 'Compare Open Tabs', meta: 'Live Lens', keys: 'compare open tabs matrix lens', run: () => {{
        daemonCall('/api/agent/lens/compare', {{}}, 15000)
          .then(res => res || daemonCall('/api/agent/genui', {{}}, 15000))
          .finally(() => openInternalPage('workspace.html#view=comparison', '/workspace#view=comparison'));
      }} }},
    ];
  }}

  function open() {{
    const existing = document.getElementById('__luminara_cmd_palette');
    if (hostEl || existing) {{ close(); if (existing && existing !== hostEl) existing.remove(); return; }}
    prevFocus = document.activeElement;
    hostEl = document.createElement('div');
    hostEl.id = '__luminara_cmd_palette';
    const dt = document.documentElement.getAttribute('data-theme');
    if (dt === 'light' || dt === 'dark') hostEl.setAttribute('data-theme', dt);
    hostEl.style.cssText = 'all:initial;position:fixed;inset:0;z-index:2147483647;';
    const root = hostEl.attachShadow ? hostEl.attachShadow({{ mode: 'open' }}) : hostEl;
    const style = document.createElement('style');
    style.textContent = [
      ':host{{color-scheme:dark light;}}',
      ':host([data-theme="light"]){{color-scheme:light;}}',
      ':host([data-theme="dark"]){{color-scheme:dark;}}',
      '.bg{{position:fixed;inset:0;background:rgba(14,15,19,0.56);backdrop-filter:blur(10px);display:grid;place-items:start center;padding:12vh 14px 14px;font-family:"Inter",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;}}',
      '.shell{{width:min(580px,100%);background:light-dark(#FAF9F6,#1F2229);color:light-dark(#1C1E24,#F6F5F0);border:1px solid light-dark(#E4E2DB,#2C303A);border-radius:20px;padding:10px;box-shadow:inset 0 1px 0 rgba(255,255,255,0.08),0 28px 64px -18px rgba(0,0,0,0.55);display:grid;gap:8px;}}',
      '.inp{{width:100%;box-sizing:border-box;background:light-dark(#FFFFFF,#141519);color:inherit;border:1px solid light-dark(#8C8980,#676E82);border-radius:10px;padding:11px 14px;font-size:14.5px;outline:none;}}',
      '.inp:focus{{border-color:light-dark(#117A5E,#3CD0A3);}}',
      '.list{{max-height:min(340px,48vh);overflow-y:auto;display:grid;gap:3px;padding:2px 0;}}',
      '.grp{{font:600 10.5px/1.2 "JetBrains Mono",Consolas,monospace;letter-spacing:0.08em;text-transform:uppercase;color:light-dark(#5A5F6B,#8F96A5);padding:6px 10px 3px;}}',
      '.item{{width:100%;border:1px solid transparent;background:transparent;color:inherit;border-radius:10px;padding:9px 11px;display:flex;align-items:center;justify-content:space-between;gap:10px;cursor:pointer;text-align:left;font:500 13.5px/1.3 inherit;}}',
      '.item:hover,.item.active{{background:light-dark(#ECEAE3,#282C35);border-color:light-dark(#117A5E,#3CD0A3);}}',
      '.ttl{{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0;}}',
      '.meta{{flex-shrink:0;font:500 11.5px/1.2 "JetBrains Mono",Consolas,monospace;color:light-dark(#5A5F6B,#8F96A5);max-width:44%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}}',
      '.foot{{display:flex;justify-content:space-between;gap:8px;padding:4px 8px 2px;font:500 11px/1.2 "JetBrains Mono",Consolas,monospace;color:light-dark(#5A5F6B,#8F96A5);}}'
    ].join('\\n');

    const overlay = document.createElement('div');
    overlay.className = 'bg';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.setAttribute('aria-label', 'Luminara Command Palette');
    overlay.tabIndex = -1;
    const shell = document.createElement('div'); shell.className = 'shell';
    const inp = document.createElement('input');
    inp.className = 'inp'; inp.type = 'text'; inp.autocomplete = 'off';
    inp.setAttribute('aria-label', 'Search commands, open tabs, URLs, or ask your team');
    inp.placeholder = 'Jump to tab, run command, enter URL, or ask your team...';
    const listEl = document.createElement('div'); listEl.className = 'list'; listEl.setAttribute('role', 'listbox');
    const foot = document.createElement('div'); foot.className = 'foot';
    const fL = document.createElement('span'); fL.textContent = '↑↓ navigate · ↵ run · Esc close';
    const fR = document.createElement('span'); fR.textContent = 'Alt+K';
    foot.append(fL, fR);

    let items = [], activeIdx = 0;
    function buildItems(rawQ) {{
      const q = (rawQ || '').trim(), scored = [];
      for (const c of quickCommands()) {{
        const s = Math.max(fuzzyScore(c.title, q), fuzzyScore(c.meta, q), fuzzyScore(c.keys, q));
        if (s > 0) scored.push({{ ...c, score: s }});
      }}
      for (const t of liveTabs) {{
        const host = (() => {{ try {{ return new URL(t.url).hostname; }} catch (_e) {{ return t.url || ''; }} }})();
        const s = Math.max(fuzzyScore(t.title || host, q), fuzzyScore(host, q));
        if (s > 0) scored.push({{
          group: 'Open Tabs', title: (t.title || host || 'Tab').slice(0, 64), meta: host, score: s,
          run: () => {{ daemonCall('/api/agent/tabs/focus', {{ target_id: t.target_id }}, 3000); }}
        }});
      }}
      scored.sort((a, b) => b.score - a.score);
      const out = scored.slice(0, 10);
      if (q) {{
        const u = isLikelyUrl(q);
        if (u) out.unshift({{ group: 'Navigate', title: 'Open ' + u, meta: 'URL', run: () => {{ location.href = u; }} }});
        out.push({{ group: 'Search & Team', title: 'Search privately: "' + q + '"', meta: 'Search', run: () => {{ location.href = SEARCH_TPL.replace('{{searchTerms}}', encodeURIComponent(q)); }} }});
        out.push({{ group: 'Search & Team', title: 'Ask Team: "' + q + '"', meta: 'Team', run: () => {{
          const enc = encodeURIComponent(q.slice(0, 800));
          openInternalPage('newtab.html#ask=' + enc, '/newtab#ask=' + enc);
        }} }});
      }}
      return out;
    }}
    function updateActive() {{
      listEl.querySelectorAll('.item').forEach((b, i) => {{
        const on = i === activeIdx;
        b.classList.toggle('active', on);
        b.setAttribute('aria-selected', String(on));
        if (on && b.scrollIntoView) b.scrollIntoView({{ block: 'nearest' }});
      }});
    }}
    function renderList() {{
      items = buildItems(inp.value);
      if (activeIdx >= items.length) activeIdx = Math.max(0, items.length - 1);
      listEl.replaceChildren();
      let lastGrp = '';
      items.forEach((it, idx) => {{
        if (it.group !== lastGrp) {{
          lastGrp = it.group;
          const g = document.createElement('div'); g.className = 'grp'; g.textContent = it.group; listEl.appendChild(g);
        }}
        const btn = document.createElement('button');
        btn.type = 'button'; btn.className = 'item' + (idx === activeIdx ? ' active' : '');
        btn.setAttribute('role', 'option'); btn.setAttribute('aria-selected', String(idx === activeIdx));
        const tS = document.createElement('span'); tS.className = 'ttl'; tS.textContent = it.title;
        const mS = document.createElement('span'); mS.className = 'meta'; mS.textContent = it.meta || '';
        btn.append(tS, mS);
        btn.addEventListener('mouseenter', () => {{ activeIdx = idx; updateActive(); }});
        btn.addEventListener('click', () => {{ close(); it.run(); }});
        listEl.appendChild(btn);
      }});
    }}

    for (const evName of ['keydown', 'keyup', 'keypress']) inp.addEventListener(evName, (ev) => ev.stopPropagation());
    inp.addEventListener('input', () => {{ activeIdx = 0; renderList(); }});
    overlay.addEventListener('keydown', (e) => {{
      if (e.key === 'Escape') {{ e.preventDefault(); close(); }}
      if (e.key === 'Tab') {{ e.preventDefault(); inp.focus(); }}
    }});
    inp.addEventListener('keydown', (e) => {{
      if (e.key === 'Escape') {{ e.preventDefault(); close(); return; }}
      if (e.key === 'Tab') {{ e.preventDefault(); inp.focus(); return; }}
      if (e.key === 'ArrowDown' && items.length) {{ e.preventDefault(); activeIdx = (activeIdx + 1) % items.length; updateActive(); return; }}
      if (e.key === 'ArrowUp' && items.length) {{ e.preventDefault(); activeIdx = (activeIdx - 1 + items.length) % items.length; updateActive(); return; }}
      if (e.key === 'Enter') {{ e.preventDefault(); const chosen = items[activeIdx]; close(); if (chosen) chosen.run(); }}
    }});

    shell.append(inp, listEl, foot);
    overlay.appendChild(shell);
    overlay.addEventListener('click', (e) => {{ if (e.target === overlay) close(); }});
    root.append(style, overlay);
    document.documentElement.appendChild(hostEl);
    renderList();
    inp.focus();

    daemonCall('/api/agent/tabs', undefined, 2000).then((d) => {{
      if (!d || !Array.isArray(d.tabs)) return;
      liveTabs = d.tabs.filter((t) => !/^(chrome(-extension)?:\\/\\/|devtools:\\/\\/|about:)/i.test(String(t.url || '')));
      if (hostEl) renderList();
    }});
  }}

  window.__luminaraOpenPalette = open;
  window.addEventListener('keydown', (e) => {{
    const k = (e.key || '').toLowerCase();
    if ((e.altKey && k === 'k') || ((e.ctrlKey || e.metaKey) && e.shiftKey && k === 'k')) {{
      e.preventDefault(); e.stopPropagation(); open();
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
    """Write the built-in MV3 `luminara-copilot` Conversational Team Side Panel extension."""
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
        "name": f"{profile.brand_name} Team Side Panel",
        "version": "4.0.0",
        "description": "Conversational AI Team Side Panel (Research Team, Pi, Remy, Dana) with plain-English approvals, Teach-It-Once skills, and Live Lens.",
        "permissions": ["sidePanel", "tabs"],
        "host_permissions": [f"{daemon_base}/*"],
        "icons": {"16": "icons/icon16.png", "48": "icons/icon48.png", "128": "icons/icon128.png"},
        "content_security_policy": {"extension_pages": "script-src 'self'; object-src 'none'; base-uri 'none';"},
        "background": {"service_worker": "background.js"},
        "action": {
            "default_title": f"Open {profile.brand_name} Team Side Panel (Alt+L)",
            "default_icon": {"16": "icons/icon16.png", "48": "icons/icon48.png"},
        },
        "commands": {
            "open-team-panel": {
                "suggested_key": {"default": "Alt+L"},
                "description": "Open Luminara Team Side Panel",
            }
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
if (chrome.commands && chrome.commands.onCommand) {
  chrome.commands.onCommand.addListener((command, tab) => {
    if (command === 'open-team-panel' && tab && tab.id && chrome.sidePanel && chrome.sidePanel.open) {
      chrome.sidePanel.open({ tabId: tab.id }).catch(() => {});
    }
  });
}
"""
    (ext_dir / "background.js").write_text(background_js, encoding=ENCODING, newline="\n")

    brand_esc = html.escape(profile.brand_name)
    sidepanel_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="color-scheme" content="dark light" />
  <link rel="icon" type="image/png" href="icons/icon48.png" />
  <title>{brand_esc} — Team</title>
  <style>
{SHARED_UI_TOKENS_CSS}
    :root {{ --bot-wash: var(--accent); }}
    body {{ min-height:100dvh; display:flex; flex-direction:column; gap:10px; padding:12px; color:var(--ink-0); font:400 13.5px/1.5 var(--font-sans); -webkit-font-smoothing:antialiased; background:radial-gradient(460px 190px at 50% -12%, color-mix(in srgb, var(--bot-wash) 14%, transparent), transparent 72%), var(--bg-0); }}
    .panel-head,.composer {{ background:var(--bg-1); border:1px solid var(--hairline); box-shadow:var(--card-shadow); border-radius:var(--r-card); padding:11px; display:grid; gap:9px; }}
    .top-row,.mode-row,.composer-foot {{ display:flex; align-items:center; justify-content:space-between; gap:8px; flex-wrap:wrap; }}
    .brand-row {{ display:flex; align-items:center; gap:8px; font-weight:600; font-size:13.5px; letter-spacing:-0.015em; }}
    .status-pill {{ display:inline-flex; align-items:center; gap:6px; padding:3px 9px; border-radius:var(--r-pill); background:var(--bg-2); color:var(--ink-1); font-size:11.5px; font-weight:500; }}
    .dot,.bot-swatch {{ width:7px; height:7px; border-radius:50%; flex-shrink:0; }}
    .dot {{ background:var(--accent); }} .dot.offline {{ background:var(--warn); }}
    .bot-bar,.chips,.btn-row {{ display:flex; gap:6px; flex-wrap:wrap; }}
    .bot-pill,.chip {{ min-height:29px; padding:5px 10px; border-radius:var(--r-pill); border:1px solid var(--hairline); background:var(--bg-2); color:var(--ink-1); font:500 12px/1.2 var(--font-sans); cursor:pointer; display:inline-flex; align-items:center; gap:6px; transition:border-color 140ms var(--ease-out), transform 120ms var(--ease-out); }}
    .chip {{ background:var(--bg-1); }} .chip.recording {{ border-color:var(--danger); color:var(--danger); font-weight:600; }}
    .bot-pill:hover,.chip:hover:not(:disabled) {{ border-color:var(--accent); color:var(--ink-0); transform:translateY(-1px); }}
    .bot-pill.active {{ background:var(--bg-1); color:var(--ink-0); border-color:var(--bot-wash); font-weight:600; }}
    .seg {{ display:inline-flex; padding:2px; border-radius:var(--r-control); background:var(--bg-2); border:1px solid var(--hairline); gap:2px; }}
    .seg button {{ min-height:26px; border:0; background:transparent; color:var(--ink-1); padding:4px 9px; border-radius:8px; font:500 12px/1.2 var(--font-sans); cursor:pointer; }}
    .seg button.active {{ background:var(--bg-1); color:var(--ink-0); font-weight:600; box-shadow:var(--specular); }}
    .inbox-stack {{ display:none; gap:8px; }} .inbox-stack.visible {{ display:grid; }}
    .approval-card {{ background:var(--bg-1); border:1px solid color-mix(in srgb, var(--warn) 48%, var(--hairline)); border-left:3px solid var(--warn); border-radius:var(--r-card); padding:11px; display:grid; gap:7px; }}
    .approval-title {{ font-weight:600; font-size:13px; }} .approval-desc {{ font-size:12.5px; color:var(--ink-1); overflow-wrap:anywhere; }}
    .why-box {{ font-size:12px; color:var(--ink-2); }} .why-box summary {{ cursor:pointer; font-weight:500; color:var(--ink-1); }}
    .why-body {{ margin-top:6px; padding:8px; border-radius:var(--r-control); background:var(--bg-2); font-family:var(--font-mono); font-size:11px; overflow-wrap:anywhere; }}
    .btn {{ min-height:31px; padding:6px 12px; border-radius:var(--r-control); border:1px solid var(--border-control); background:var(--bg-1); color:var(--ink-0); font:500 12.5px/1.2 var(--font-sans); cursor:pointer; transition:transform 120ms var(--ease-out), border-color 140ms var(--ease-out); }}
    .btn:hover:not(:disabled) {{ border-color:var(--accent); transform:translateY(-1px); }} .btn:active:not(:disabled) {{ transform:scale(0.97); }}
    .btn:disabled,.chip:disabled {{ opacity:0.46; cursor:wait; }}
    .btn.primary {{ background:var(--accent); border-color:var(--accent); color:var(--accent-ink); font-weight:600; }}
    .btn.stop {{ background:var(--danger); border-color:var(--danger); color:var(--danger-ink); font-weight:600; }}
    .btn.subtle {{ background:var(--bg-2); border-color:var(--hairline); font-size:12px; padding:5px 10px; min-height:28px; }}
    .timeline {{ flex:1 1 auto; overflow-y:auto; display:flex; flex-direction:column; gap:10px; padding:2px 1px; min-height:135px; }}
    .bubble {{ max-width:96%; border-radius:var(--r-card); padding:10px 12px; display:grid; gap:6px; border:1px solid var(--hairline); background:var(--bg-1); box-shadow:var(--specular); font-size:13.5px; line-height:1.5; overflow-wrap:anywhere; }}
    .bubble.user {{ align-self:flex-end; background:var(--bg-2); }} .bubble.err {{ border-color:color-mix(in srgb, var(--danger) 55%, var(--hairline)); }}
    .bubble-head {{ display:flex; align-items:center; justify-content:space-between; gap:8px; font-size:11.5px; color:var(--ink-2); }}
    .bubble-who {{ display:inline-flex; align-items:center; gap:6px; font-weight:600; color:var(--ink-1); }}
    .bubble-body {{ white-space:pre-wrap; }}
    .plan-list {{ padding-left:18px; display:grid; gap:4px; font-size:12.5px; color:var(--ink-1); }}
    .receipt-pill summary {{ display:inline-flex; align-items:center; gap:5px; list-style:none; cursor:pointer; padding:3px 9px; border-radius:var(--r-pill); background:var(--bg-2); color:var(--ink-1); font:500 11px/1.2 var(--font-mono); font-variant-numeric:tabular-nums; }}
    .receipt-body {{ margin-top:6px; padding:8px 10px; border-radius:var(--r-control); background:var(--bg-2); color:var(--ink-1); font-size:12px; display:grid; gap:4px; }}
    .composer textarea {{ width:100%; resize:none; background:var(--bg-0); color:var(--ink-0); border:1px solid var(--border-control); border-radius:var(--r-control); padding:9px 11px; font:400 13.5px/1.45 var(--font-sans); min-height:52px; }}
    details.power-drawer {{ background:var(--bg-1); border:1px solid var(--hairline); border-radius:var(--r-card); padding:9px 12px; }}
    details.power-drawer summary {{ cursor:pointer; font-size:12px; font-weight:600; color:var(--ink-2); user-select:none; }}
    .power-grid {{ margin-top:9px; display:grid; grid-template-columns:repeat(2, minmax(0, 1fr)); gap:6px; }}
    @media (prefers-reduced-motion: reduce) {{ *, *::before, *::after {{ transition:none !important; animation:none !important; }} }}
  </style>
</head>
<body>
  <header class="panel-head">
    <div class="top-row">
      <div class="brand-row">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <rect x="2" y="2" width="20" height="20" rx="6" stroke="currentColor" stroke-width="1.8" opacity="0.35"/>
          <path d="M12 5.5L17.5 12L12 18.5L6.5 12L12 5.5Z" fill="var(--accent)"/>
        </svg>
        <span>{brand_esc} Team</span>
      </div>
      <div class="status-pill" id="connState" role="status" aria-live="polite"><span class="dot" id="connDot"></span><span id="connText">Connecting...</span></div>
    </div>
    <div class="bot-bar" role="tablist" aria-label="Choose assistant or team">
      <button type="button" class="bot-pill active" role="tab" aria-selected="true" data-bot="team-research"><span class="bot-swatch" style="background:var(--accent);"></span>Research Team</button>
      <button type="button" class="bot-pill" role="tab" aria-selected="false" data-bot="pi"><span class="bot-swatch" style="background:var(--bot-pi);"></span>Pi</button>
      <button type="button" class="bot-pill" role="tab" aria-selected="false" data-bot="remy"><span class="bot-swatch" style="background:var(--bot-remy);"></span>Remy</button>
      <button type="button" class="bot-pill" role="tab" aria-selected="false" data-bot="dana"><span class="bot-swatch" style="background:var(--bot-dana);"></span>Dana</button>
    </div>
    <div class="mode-row">
      <div class="seg" role="radiogroup" aria-label="Execution mode">
        <button type="button" class="active" data-mode="execute" aria-checked="true" role="radio">Execute</button>
        <button type="button" data-mode="plan" aria-checked="false" role="radio">Plan</button>
      </div>
      <div class="seg" role="radiogroup" aria-label="Theme">
        <button type="button" class="active" data-theme-pick="system" aria-checked="true" role="radio">Auto</button>
        <button type="button" data-theme-pick="light" aria-checked="false" role="radio">Light</button>
        <button type="button" data-theme-pick="dark" aria-checked="false" role="radio">Dark</button>
      </div>
    </div>
  </header>

  <div class="chips" aria-label="Quick actions">
    <button type="button" class="chip" id="chipSummarize">Summarize page</button>
    <button type="button" class="chip" id="chipCompare">Compare open tabs</button>
    <button type="button" class="chip" id="chipTeach">Teach skill</button>
    <button type="button" class="chip" id="chipWatch">Watch for changes</button>
    <button type="button" class="chip" id="btnTakeoverTop">Take over</button>
  </div>

  <section class="inbox-stack" id="inboxStack" aria-label="Items needing your approval"></section>
  <main class="timeline" id="chatTimeline" aria-live="polite"></main>

  <form class="composer" id="chatForm">
    <label class="sr-only" for="chatInput">Message your team</label>
    <textarea id="chatInput" rows="2" placeholder="Ask about this page, compare tabs, or describe a task..."></textarea>
    <div class="composer-foot">
      <span style="font-size:11.5px;color:var(--ink-2);" id="modeHint">Execute mode · Acts with your approval</span>
      <button type="submit" class="btn primary" id="btnSend">Send ↵</button>
    </div>
  </form>

  <details class="power-drawer">
    <summary>Power Tools</summary>
    <div class="power-grid">
      <button type="button" class="btn subtle" id="btnSnap">Index DOM</button>
      <button type="button" class="btn subtle" id="btnExtractMd">Extract Markdown</button>
      <button type="button" class="btn subtle" id="btnOpenWs">Live Lens</button>
      <button type="button" class="btn subtle" id="btnOpenTele">Developer Telemetry</button>
      <button type="button" class="btn subtle" id="btnVerifyLedger">Verify Ledger</button>
      <button type="button" class="btn subtle" id="btnAcceptDlg">Accept Dialog</button>
      <button type="button" class="btn subtle" id="btnDismissDlg">Dismiss Dialog</button>
      <button type="button" class="btn subtle" id="btnClear">Clear Overlay</button>
    </div>
  </details>
  <script src="sidepanel.js"></script>
</body>
</html>
"""
    (ext_dir / "sidepanel.html").write_text(sidepanel_html, encoding=ENCODING, newline="\n")

    sidepanel_js = f"""const DAEMON = {_js_json(daemon_base)};
const WORKSPACE_URL = {_js_json(resolved_ws_url)};
const SLUG = {_js_json(profile.slug)};
const UI_KEY = {_js_json(ui_key)};
const KEY_SETTINGS = 'luminara_browser:settings';
const BOTS = {{
  'team-research': {{ label: 'Research Team', color: 'var(--accent)', agentId: 'bot:team-research' }},
  pi: {{ label: 'Pi', color: 'var(--bot-pi)', agentId: 'bot:pi' }},
  remy: {{ label: 'Remy', color: 'var(--bot-remy)', agentId: 'bot:remy' }},
  dana: {{ label: 'Dana', color: 'var(--bot-dana)', agentId: 'bot:dana' }},
}};
let activeBot = 'team-research', activeMode = 'execute', activeAbort = null, teachRecording = false;
const timelineEl = document.getElementById('chatTimeline');
const connDot = document.getElementById('connDot');
const connText = document.getElementById('connText');
const inboxStack = document.getElementById('inboxStack');
const chatInput = document.getElementById('chatInput');
const btnSend = document.getElementById('btnSend');
const chipTeach = document.getElementById('chipTeach');

function el(tag, cls, text) {{
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = String(text);
  return n;
}}
function mkBtn(cls, txt, fn) {{
  const b = el('button', cls, txt); b.type = 'button'; b.onclick = fn; return b;
}}
function applyTheme(mode) {{
  const m = (mode === 'light' || mode === 'dark') ? mode : 'system';
  if (m === 'system') document.documentElement.removeAttribute('data-theme');
  else document.documentElement.setAttribute('data-theme', m);
  document.querySelectorAll('[data-theme-pick]').forEach(b => {{
    const on = b.getAttribute('data-theme-pick') === m;
    b.classList.toggle('active', on);
    b.setAttribute('aria-checked', String(on));
  }});
}}
function initTheme() {{
  try {{ applyTheme((JSON.parse(localStorage.getItem(KEY_SETTINGS) || '{{}}').theme) || 'system'); }} catch (_e) {{ applyTheme('system'); }}
  document.querySelectorAll('[data-theme-pick]').forEach(b => b.addEventListener('click', () => {{
    const m = b.getAttribute('data-theme-pick') || 'system';
    try {{ const s = JSON.parse(localStorage.getItem(KEY_SETTINGS) || '{{}}'); s.theme = m; localStorage.setItem(KEY_SETTINGS, JSON.stringify(s)); }} catch (_e) {{}}
    applyTheme(m);
  }}));
  window.addEventListener('storage', ev => {{
    if (ev.key === KEY_SETTINGS) {{
      try {{ applyTheme((JSON.parse(ev.newValue || '{{}}').theme) || 'system'); }} catch (_e) {{}}
    }}
  }});
}}
function humanError(err) {{
  if (!err) return 'Something went wrong.';
  if (err.status === 401 || err.status === 403) return 'Local authorization required — relaunch Luminara Browser to refresh your local key.';
  if (err.status === 502) return 'Browser tab is busy or reloading — wait a moment and try again.';
  if (err.status === 0 || /failed to fetch|networkerror/i.test(String(err.message || ''))) return 'Luminara daemon is offline — launch via Luminara Browser.';
  return err.message || String(err);
}}
async function callDaemon(path, body, timeoutMs = 20000, customSignal = null) {{
  const isPost = body !== undefined, headers = {{}};
  if (UI_KEY) headers['X-Luminara-UI-Key'] = UI_KEY;
  if (isPost) headers['Content-Type'] = 'application/json';
  let r;
  try {{
    r = await fetch(DAEMON + path, {{
      method: isPost ? 'POST' : 'GET', headers,
      body: isPost ? JSON.stringify(body) : undefined,
      signal: customSignal || AbortSignal.timeout(timeoutMs),
    }});
  }} catch (netErr) {{
    if (netErr && netErr.name === 'AbortError') throw netErr;
    const e = new Error('Daemon unreachable'); e.status = 0; throw e;
  }}
  const data = await r.json().catch(() => ({{}}));
  if (!r.ok) {{ const err = new Error(data.error || ('Request failed (' + r.status + ')')); err.status = r.status; throw err; }}
  return data;
}}
async function resolveActiveTargetId() {{
  try {{
    if (!chrome.tabs || !chrome.tabs.query) return undefined;
    const [active] = await chrome.tabs.query({{ active: true, lastFocusedWindow: true }});
    if (!active || !active.url || /^(chrome(-extension)?:|devtools:|about:)/i.test(active.url)) return undefined;
    const tb = await callDaemon('/api/agent/tabs', undefined, 2500);
    const hit = (tb.tabs || []).find(t => t.url === active.url) || (tb.tabs || []).find(t => active.title && t.title === active.title);
    return hit ? hit.target_id : undefined;
  }} catch (_e) {{ return undefined; }}
}}
async function openAuthenticatedWorkspace(view = 'comparison') {{
  let targetUrl = WORKSPACE_URL;
  const hashParts = view ? ['view=' + encodeURIComponent(view)] : [];
  try {{
    const tokRes = await callDaemon('/api/agent/session-token', {{ scope: 'ui', ttl_sec: 900 }}, 4000);
    if (tokRes && tokRes.token) hashParts.push('lum_tok=' + encodeURIComponent(tokRes.token));
  }} catch (_e) {{}}
  if (hashParts.length) targetUrl += '#' + hashParts.join('&');
  if (chrome.tabs) chrome.tabs.create({{ url: targetUrl }});
}}
function openSetupHome() {{
  if (chrome.tabs) chrome.tabs.create({{ url: DAEMON + '/newtab#setup' }});
}}
function addBubble(opts) {{
  const role = opts.role || 'bot', botMeta = BOTS[opts.bot || activeBot] || BOTS['team-research'];
  const card = el('article', 'bubble ' + (role === 'user' ? 'user' : '') + (opts.error ? ' err' : ''));
  const head = el('div', 'bubble-head'), who = el('span', 'bubble-who');
  if (role !== 'user') {{ const sw = el('span', 'bot-swatch'); sw.style.background = opts.error ? 'var(--danger)' : botMeta.color; who.appendChild(sw); }}
  who.appendChild(document.createTextNode(role === 'user' ? 'You' : (opts.sender || botMeta.label)));
  head.append(who, el('span', '', new Date().toLocaleTimeString([], {{ hour: '2-digit', minute: '2-digit' }})));
  const bodyText = String(opts.text || '');
  card.append(head, el('div', 'bubble-body', bodyText));

  if (Array.isArray(opts.planSteps) && opts.planSteps.length) {{
    const ol = el('ol', 'plan-list');
    opts.planSteps.forEach(s => ol.appendChild(el('li', '', s)));
    card.appendChild(ol);
    if (opts.promptText) {{
      const execRow = el('div', 'btn-row');
      execRow.appendChild(mkBtn('btn primary', 'Execute this plan', () => sendPrompt(opts.promptText, 'execute')));
      card.appendChild(execRow);
    }}
  }}
  if (opts.needsSetup) {{
    const setupRow = el('div', 'btn-row');
    setupRow.appendChild(mkBtn('btn primary', 'Connect AI Provider →', openSetupHome));
    card.appendChild(setupRow);
  }}
  if (opts.receipt) {{
    const det = el('details', 'receipt-pill');
    const bits = ['Work receipt', opts.receipt.duration, opts.receipt.source].filter(Boolean);
    det.appendChild(el('summary', '', '✓ ' + bits.join(' · ')));
    const rBody = el('div', 'receipt-body');
    if (opts.receipt.summary) rBody.appendChild(el('div', '', opts.receipt.summary));
    if (opts.receipt.details) rBody.appendChild(el('div', '', opts.receipt.details));
    if (opts.receipt.id) rBody.appendChild(el('div', '', 'Reference: ' + opts.receipt.id));
    if (opts.receipt.openLens) rBody.appendChild(mkBtn('btn subtle', 'Open in Live Lens →', () => openAuthenticatedWorkspace('comparison')));
    det.appendChild(rBody);
    card.appendChild(det);
  }}
  if (role !== 'user' && !opts.ephemeral) {{
    const footRow = el('div', 'btn-row');
    const copyB = mkBtn('btn subtle', 'Copy', async () => {{
      try {{ await navigator.clipboard.writeText(bodyText); copyB.textContent = 'Copied ✓'; setTimeout(() => {{ copyB.textContent = 'Copy'; }}, 1500); }} catch (_e) {{}}
    }});
    footRow.appendChild(copyB);
    if (opts.retryFn) footRow.appendChild(mkBtn('btn subtle', opts.error ? 'Retry' : 'Regenerate', opts.retryFn));
    card.appendChild(footRow);
  }}
  timelineEl.appendChild(card);
  timelineEl.scrollTop = timelineEl.scrollHeight;
  return card;
}}
function clipText(s) {{
  const t = String(s || '').trim();
  return t.length > 1400 ? (t.slice(0, 1400) + '…') : t;
}}
function formatPlainReply(res, fallback) {{
  if (!res || typeof res !== 'object') return fallback || 'Done.';
  for (const k of ['reply', 'answer', 'message', 'summary', 'formatted']) {{
    if (typeof res[k] === 'string' && res[k].trim()) return clipText(res[k]);
  }}
  if (res.status === 'PAUSED_HUMAN_HANDOFF') return 'Paused at a sign-in or verification step. Complete it in the tab, then click Resume Agent above.';
  if (res.status === 'COMPLETED') {{ const n = Array.isArray(res.steps) ? res.steps.length : 0; return n ? ('Finished in ' + n + ' step' + (n === 1 ? '' : 's') + '.') : 'Task completed.'; }}
  return (res.receipt && res.receipt.summary) || fallback || 'Done.';
}}
function makeReceipt(res, t0, src) {{
  const wr = (res && res.work_receipt) || null, rec = (res && res.receipt) || null;
  const dur = (wr && typeof wr.duration_ms === 'number') ? (Math.max(0.1, wr.duration_ms / 1000).toFixed(1) + 's') : (Math.max(0.1, (Date.now() - t0) / 1000).toFixed(1) + 's');
  const detailParts = [];
  if (wr && typeof wr.tabs_read === 'number') detailParts.push(wr.tabs_read + ' tab(s) read');
  if (wr && wr.provider) detailParts.push('Provider: ' + wr.provider);
  if (wr && Array.isArray(wr.webmcp_tools) && wr.webmcp_tools.length) detailParts.push('WebMCP: ' + wr.webmcp_tools.join(', '));
  return {{
    duration: dur,
    source: (wr && wr.provider) || (res && (res.bot_name || res.provider)) || src || BOTS[activeBot].label,
    summary: (rec && rec.summary) || (res && res.status ? ('Status: ' + res.status) : 'Verified local action'),
    details: detailParts.join(' · '),
    id: (rec && rec.receipt_id) || '',
    openLens: Boolean(res && res.generative_ui),
  }};
}}
function renderInbox(items) {{
  inboxStack.replaceChildren();
  inboxStack.classList.toggle('visible', Boolean(items && items.length));
  (items || []).forEach(it => {{
    const card = el('article', 'approval-card');
    card.appendChild(el('div', 'approval-title', it.title || 'Needs your approval'));
    if (it.diff_preview || it.summary) card.appendChild(el('div', 'approval-desc', it.diff_preview || it.summary));
    const why = el('details', 'why-box');
    why.append(el('summary', '', 'Why am I asked?'), el('div', 'why-body', it.why || it.reason || 'Luminara pauses before sensitive changes or sign-in walls.'));
    card.appendChild(why);
    const acts = el('div', 'btn-row');
    const actInbox = async (action, label) => {{
      try {{
        const res = await callDaemon('/api/agent/inbox', {{ id: it.id, kind: it.kind, raw_id: it.raw_id, domain: it.domain, action }}, 35000);
        addBubble({{ text: label, receipt: makeReceipt(res, Date.now() - 200, 'Inbox') }});
        await refreshState();
      }} catch (err) {{ addBubble({{ text: humanError(err), error: true }}); }}
    }};
    if (it.kind === 'handoff') {{
      acts.append(mkBtn('btn', 'Dismiss', () => actInbox('deny', 'Dismissed handoff.')), mkBtn('btn primary', 'Resume Agent', () => actInbox('resume', 'Resumed where the assistant left off.')));
    }} else if (it.kind === 'sequence') {{
      acts.appendChild(mkBtn('btn primary', 'Clear Block', () => actInbox('clear', 'Cleared security pause.')));
    }} else {{
      acts.append(
        mkBtn('btn', 'Deny', () => actInbox('deny', 'Blocked that request — nothing was sent.')),
        mkBtn('btn primary', 'Allow once', () => actInbox('allow_once', 'Allowed once and resumed.')),
        mkBtn('btn', 'Always for site', () => actInbox('allow_site', 'Allowed for ' + (it.domain || 'this site') + '.'))
      );
    }}
    card.appendChild(acts);
    inboxStack.appendChild(card);
  }});
}}
function syncTeachBtn() {{
  chipTeach.textContent = teachRecording ? 'Save skill ■' : 'Teach skill';
  chipTeach.classList.toggle('recording', teachRecording);
}}
async function hydrateTeach() {{
  try {{
    const res = await callDaemon('/api/agent/teach', {{ action: 'list' }}, 2500);
    teachRecording = Boolean(res && res.recording);
    syncTeachBtn();
  }} catch (_e) {{}}
}}
async function refreshState() {{
  try {{
    const [st, inboxRes] = await Promise.all([
      callDaemon('/api/agent/status', undefined, 2500),
      callDaemon('/api/agent/inbox', undefined, 2000).catch(() => null),
    ]);
    connDot.classList.remove('offline');
    const n = Number(st.open_tabs || 0);
    connText.textContent = st.cdp_connected ? ('Ready · ' + n + ' tab' + (n === 1 ? '' : 's')) : 'Connected · Waiting for tab';
    if (inboxRes && Array.isArray(inboxRes.items)) {{
      renderInbox(inboxRes.items);
    }} else {{
      const fb = [];
      (st.active_handoffs || []).forEach(h => fb.push({{ id: 'handoff:' + h.run_id, raw_id: h.run_id, kind: 'handoff', title: 'Action needed on page', diff_preview: h.goal || h.url || '', why: 'Paused at ' + (h.gate_type || 'verification') + '.' }}));
      (st.pending_mutations || []).forEach(m => fb.push({{ id: 'mut:' + m.mutation_id, raw_id: m.mutation_id, kind: 'mutation', title: 'Approve ' + (m.method || 'write') + ' request', diff_preview: m.url || '', why: 'Network Mutation Firewall paused this request.' }}));
      renderInbox(fb);
    }}
  }} catch (err) {{
    connDot.classList.add('offline');
    connText.textContent = (err && (err.status === 401 || err.status === 403)) ? 'Auth required' : 'Offline';
  }}
}}
async function sendPrompt(rawText, overrideMode = null) {{
  const text = (rawText || '').trim();
  if (!text) return;
  const effMode = overrideMode || activeMode;
  addBubble({{ role: 'user', text }});
  const ctrl = new AbortController(); activeAbort = ctrl;
  btnSend.textContent = 'STOP ■'; btnSend.classList.replace('primary', 'stop');
  const botMeta = BOTS[activeBot] || BOTS['team-research'];
  const thinking = addBubble({{ text: botMeta.label + ' is working on that...', bot: activeBot, ephemeral: true }});
  const t0 = Date.now();
  try {{
    const target_id = await resolveActiveTargetId();
    let res;
    if (text.startsWith('/goal ')) {{
      res = await callDaemon('/api/agent/goal', {{ goal: text.slice(6).trim(), target_id, agent_id: botMeta.agentId }}, 35000, ctrl.signal);
    }} else {{
      try {{
        res = await callDaemon('/api/agent/chat', {{
          message: text, bot_id: activeBot, mode: effMode, target_id,
          include_open_tabs: activeBot === 'team-research' || activeBot === 'remy',
        }}, 35000, ctrl.signal);
      }} catch (chatErr) {{
        if (chatErr && chatErr.status === 404) res = await callDaemon('/api/agent/goal', {{ goal: text, target_id, agent_id: botMeta.agentId }}, 35000, ctrl.signal);
        else throw chatErr;
      }}
    }}
    thinking.remove();
    addBubble({{
      bot: activeBot,
      sender: (res && res.bot_name) || botMeta.label,
      text: formatPlainReply(res, 'Done.'),
      needsSetup: Boolean(res && res.needs_setup),
      planSteps: (res && Array.isArray(res.plan_steps)) ? res.plan_steps : [],
      promptText: text,
      receipt: makeReceipt(res, t0, botMeta.label),
      retryFn: () => sendPrompt(text, effMode),
    }});
    await refreshState();
  }} catch (err) {{
    thinking.remove();
    if (err && err.name === 'AbortError') addBubble({{ text: 'Stopped. You have full control of the tab.', ephemeral: true }});
    else addBubble({{ text: humanError(err), error: true, retryFn: () => sendPrompt(text, effMode) }});
  }} finally {{
    if (activeAbort === ctrl) {{ activeAbort = null; btnSend.textContent = 'Send ↵'; btnSend.classList.replace('stop', 'primary'); }}
  }}
}}

document.querySelectorAll('.bot-pill').forEach(btn => btn.addEventListener('click', () => {{
  activeBot = btn.getAttribute('data-bot') || 'team-research';
  document.querySelectorAll('.bot-pill').forEach(b => {{ const on = b === btn; b.classList.toggle('active', on); b.setAttribute('aria-selected', String(on)); }});
  document.documentElement.style.setProperty('--bot-wash', (BOTS[activeBot] || BOTS['team-research']).color);
}}));
document.querySelectorAll('[data-mode]').forEach(btn => btn.addEventListener('click', () => {{
  activeMode = btn.getAttribute('data-mode') || 'execute';
  document.querySelectorAll('[data-mode]').forEach(b => {{ const on = b === btn; b.classList.toggle('active', on); b.setAttribute('aria-checked', String(on)); }});
  document.getElementById('modeHint').textContent = activeMode === 'plan' ? 'Plan mode · Outlines steps before acting' : 'Execute mode · Acts with your approval';
}}));
document.getElementById('chatForm').addEventListener('submit', e => {{
  e.preventDefault();
  if (activeAbort) {{ activeAbort.abort(); activeAbort = null; callDaemon('/api/agent/act', {{ action: 'human_takeover' }}).catch(() => {{}}); return; }}
  const msg = chatInput.value.trim();
  if (!msg) {{ chatInput.focus(); return; }}
  chatInput.value = '';
  sendPrompt(msg);
}});
chatInput.addEventListener('keydown', e => {{ if (e.key === 'Enter' && !e.shiftKey) {{ e.preventDefault(); document.getElementById('chatForm').requestSubmit(); }} }});

function wireAbortableChip(id, label, fn) {{
  const b = document.getElementById(id);
  let chipCtrl = null;
  b.onclick = async () => {{
    if (chipCtrl) {{ chipCtrl.abort(); chipCtrl = null; b.textContent = label; return; }}
    chipCtrl = new AbortController(); const orig = b.textContent; b.textContent = 'STOP ■'; const t0 = Date.now();
    try {{ const msg = await fn(t0, chipCtrl.signal); if (msg) addBubble(msg); }}
    catch (err) {{ if (!err || err.name !== 'AbortError') addBubble({{ text: humanError(err), error: true }}); }}
    finally {{ chipCtrl = null; b.textContent = orig; }}
  }};
}}
document.getElementById('chipSummarize').onclick = () => sendPrompt('Summarize the active page in clear bullet points.');
wireAbortableChip('chipCompare', 'Compare open tabs', async (t0, sig) => {{
  let res;
  try {{ res = await callDaemon('/api/agent/lens/compare', {{}}, 25000, sig); }}
  catch (err) {{ if (err && err.status === 404) res = await callDaemon('/api/agent/genui', {{ target_id: await resolveActiveTargetId() }}, 25000, sig); else throw err; }}
  await openAuthenticatedWorkspace('comparison');
  const c = (res && res.generative_ui && res.generative_ui.entity_count) || 0;
  return {{ text: c ? ('Built a Live Lens comparison with ' + c + ' items.') : 'Opened Live Lens for your open tabs.', receipt: makeReceipt(res, t0, 'Live Lens') }};
}});
chipTeach.onclick = async () => {{
  chipTeach.disabled = true; const t0 = Date.now();
  try {{
    const target_id = await resolveActiveTargetId();
    if (!teachRecording) {{
      const [active] = (chrome.tabs && chrome.tabs.query) ? await chrome.tabs.query({{ active: true, lastFocusedWindow: true }}) : [];
      const res = await callDaemon('/api/agent/teach', {{ action: 'start', name: (active && active.title) || 'Recorded Workflow', target_id }}, 15000);
      teachRecording = Boolean(res && res.recording !== false);
      syncTeachBtn();
      addBubble({{ text: 'Recording started. Click or type the steps on this page, then press Save skill ■.', receipt: makeReceipt(res, t0, 'Teach skill') }});
    }} else {{
      try {{
        const res = await callDaemon('/api/agent/teach', {{ action: 'stop', target_id }}, 15000);
        const pbName = (res && res.playbook && (res.playbook.goal_example || res.playbook.playbook_id)) || 'Recorded Workflow';
        const cnt = Number((res && res.step_count) || 0);
        addBubble({{ text: 'Saved skill "' + pbName + '" with ' + cnt + ' step' + (cnt === 1 ? '' : 's') + '.', receipt: makeReceipt(res, t0, 'Teach skill') }});
      }} finally {{
        teachRecording = false;
        syncTeachBtn();
      }}
    }}
  }} catch (err) {{ addBubble({{ text: humanError(err), error: true }}); }}
  finally {{ chipTeach.disabled = false; }}
}};
wireAbortableChip('chipWatch', 'Watch for changes', async (t0, sig) => {{
  const [active] = (chrome.tabs && chrome.tabs.query) ? await chrome.tabs.query({{ active: true, lastFocusedWindow: true }}) : [];
  if (!active || !active.url || !/^https?:\\/\\//i.test(active.url)) throw new Error('Open a website tab first to watch it for changes.');
  const res = await callDaemon('/api/agent/monitors', {{ action: 'create', name: active.title || active.url, target_url: active.url, agent_id: BOTS[activeBot].agentId }}, 15000, sig);
  return {{ text: 'Now watching "' + (active.title || active.url) + '" for changes.', receipt: makeReceipt(res, t0, 'Change Watch') }};
}});

function runBtn(id, fn) {{
  const b = document.getElementById(id);
  b.onclick = async () => {{
    b.disabled = true; const t0 = Date.now();
    try {{ const msg = await fn(t0); if (msg) addBubble(msg); }}
    catch (err) {{ addBubble({{ text: humanError(err), error: true }}); }}
    finally {{ b.disabled = false; }}
  }};
}}
runBtn('btnTakeoverTop', async (t0) => ({{ text: 'You have full control of this tab.', receipt: makeReceipt(await callDaemon('/api/agent/act', {{ target_id: await resolveActiveTargetId(), action: 'human_takeover' }}), t0, 'Takeover') }}));
runBtn('btnSnap', async (t0) => {{
  const res = await callDaemon('/api/agent/snapshot', {{ target_id: await resolveActiveTargetId(), show_badges: true, include_frames: true, agent_id: 'sidepanel-copilot' }});
  const n = (res && res.snapshot && Array.isArray(res.snapshot.elements)) ? res.snapshot.elements.length : 0;
  return {{ text: 'Highlighted ' + n + ' interactive elements on the page.', receipt: makeReceipt(res, t0, 'DOM Index') }};
}});
runBtn('btnExtractMd', async (t0) => {{
  const res = await callDaemon('/api/agent/extract', {{ target_id: await resolveActiveTargetId(), format: 'md' }});
  return {{ text: formatPlainReply(res, 'Extracted page content.'), receipt: makeReceipt(res, t0, 'Extractor') }};
}});
runBtn('btnOpenWs', async () => {{ await openAuthenticatedWorkspace('comparison'); return null; }});
runBtn('btnOpenTele', async () => {{ await openAuthenticatedWorkspace('telemetry'); return null; }});
runBtn('btnVerifyLedger', async (t0) => {{
  const res = await callDaemon('/api/agent/ledger/verify');
  return {{ text: res.valid ? ('Action ledger verified across ' + (res.checked_count || 0) + ' entries.') : 'Ledger check reported integrity warnings.', error: !res.valid, receipt: makeReceipt(res, t0, 'Ledger') }};
}});
runBtn('btnAcceptDlg', async (t0) => ({{ text: 'Accepted page dialog.', receipt: makeReceipt(await callDaemon('/api/agent/dialog', {{ target_id: await resolveActiveTargetId(), action: 'accept', agent_id: 'sidepanel-copilot' }}), t0, 'Dialog') }}));
runBtn('btnDismissDlg', async (t0) => ({{ text: 'Dismissed page dialog.', receipt: makeReceipt(await callDaemon('/api/agent/dialog', {{ target_id: await resolveActiveTargetId(), action: 'dismiss', agent_id: 'sidepanel-copilot' }}), t0, 'Dialog') }}));
runBtn('btnClear', async (t0) => ({{ text: 'Cleared on-page overlays.', receipt: makeReceipt(await callDaemon('/api/agent/act', {{ target_id: await resolveActiveTargetId(), action: 'clear_hud' }}), t0, 'Overlay') }}));

initTheme();
addBubble({{ bot: 'team-research', text: 'Welcome. Pick a teammate above or ask a question about the page you are reading.', ephemeral: true }});
hydrateTeach();
refreshState();
setInterval(refreshState, 4000);
"""
    (ext_dir / "sidepanel.js").write_text(sidepanel_js, encoding=ENCODING, newline="\n")
