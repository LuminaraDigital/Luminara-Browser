"""Clean-room OBL-08 & OBL-09 UI Generator (`forge/luminara_ui.py`).

Production-hardened Luminara Command Deck (`newtab.html`):
- Zero dynamic `.innerHTML` (eliminates `file://` & loopback DOM XSS).
- Safe JSON script serialization (`</` -> `<\\/`) and `X-Luminara-UI-Key` header for local `file://` auth.
- Full `light-dark()` OKLCH token palette (`docs/design.md`), WCAG 2.2 AA contrast, `:focus-visible`, and `320px` reflow.
- All 4 async states (`empty`, `loading` with `STOP ■` `AbortController`, `error` with Retry, `success`) + accessible `<label>`s.
"""

from __future__ import annotations

import html

from .luminara_copilot_ext import SHARED_UI_TOKENS_CSS, _js_json, build_palette_js, write_copilot_extension
from .luminara_logo3d import (
    LOGO_3D_CSS,
    build_logo_3d_hero_badge_html,
    build_logo_3d_js,
    build_logo_3d_splash_html,
)
from .luminara_workspace_ui import build_luminara_workspace_html
from .models import ForkProfile

ENCODING = "utf-8"


def build_luminara_newtab_html(
    profile: ForkProfile,
    workspace_uri: str = "./workspace.html",
    agent_port: int = 8796,
    cdp_port: int = 9229,
    ui_key: str = "",
) -> str:
    engine = profile.resolved_search_engine()
    brand_esc = html.escape(profile.brand_name)
    eng_esc = html.escape(engine.name)
    daemon_base = f"http://127.0.0.1:{agent_port}"
    palette_iife = build_palette_js(engine.search_url, agent_port=agent_port)
    logo_splash_html = build_logo_3d_splash_html(profile.brand_name, profile.chromium_version, agent_port, cdp_port)
    logo_hero_badge_html = build_logo_3d_hero_badge_html(profile.brand_name)
    logo_3d_js = build_logo_3d_js()

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="color-scheme" content="dark light" />
  <title>{brand_esc} — Agentic Command Deck</title>
  <style>
{SHARED_UI_TOKENS_CSS}
    body {{
      min-height: 100dvh; color: var(--ink-0); font-family: var(--font-sans);
      background: radial-gradient(920px 420px at 50% -5%, color-mix(in oklch, var(--accent) 10%, transparent), transparent 70%), var(--bg-0);
      padding: clamp(0.85rem, 2.4vw, 2rem); display: flex; flex-direction: column; gap: 20px; -webkit-font-smoothing: antialiased;
    }}
    header, footer {{
      max-width: 1240px; width: 100%; margin: 0 auto; display: flex; justify-content: space-between;
      align-items: center; flex-wrap: wrap; gap: 12px; font-family: var(--font-mono); font-size: 12px; color: var(--ink-2); font-variant-numeric: tabular-nums;
    }}
    .pill {{
      display: inline-flex; align-items: center; gap: 8px; min-width: 0; padding: 6px 12px; border-radius: 999px;
      background: var(--bg-1); border: 1px solid var(--hairline); box-shadow: var(--specular); color: var(--ink-1); font-size: 11px; letter-spacing: 0.07em; text-transform: uppercase;
    }}
    .dot {{ width: 7px; height: 7px; flex-shrink: 0; border-radius: 50%; background: var(--accent); box-shadow: 0 0 9px var(--accent); }}
    .dot.offline {{ background: var(--amber); box-shadow: 0 0 9px var(--amber); }}
    .nav-actions, .mode-bar, .subtabs, .todo-form {{ display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }}
    .btn-ghost {{
      min-height: 30px; min-width: 30px; padding: 6px 12px; border-radius: 10px; border: 1px solid var(--border-control);
      background: var(--bg-1); color: var(--ink-0); text-decoration: none; font-family: var(--font-mono); font-size: 11px;
      cursor: pointer; display: inline-flex; align-items: center; justify-content: center;
      transition: border-color 150ms cubic-bezier(0.16, 1, 0.3, 1), transform 120ms ease;
    }}
    .btn-ghost:hover:not(:disabled) {{ border-color: var(--accent); transform: translateY(-1px); }}
    .btn-ghost.active {{ border-color: var(--accent); color: var(--accent); background: var(--bg-2); }}
    .btn-ghost:disabled {{ opacity: 0.5; cursor: wait; }}
    main {{ max-width: 1240px; width: 100%; margin: 0 auto; display: grid; gap: 18px; flex: 1; min-width: 0; }}
    .hero {{ display: flex; justify-content: space-between; align-items: flex-end; flex-wrap: wrap; gap: 12px; }}
    .kicker {{ font-family: var(--font-mono); font-size: 11px; letter-spacing: 0.11em; text-transform: uppercase; color: var(--accent); margin-bottom: 6px; }}
    h1 {{ font-size: clamp(1.75rem, 3.5vw, 2.8rem); letter-spacing: -0.04em; line-height: 1.05; text-wrap: balance; }}
    .omnibox {{
      background: var(--bg-1); border: 1px solid var(--hairline); box-shadow: var(--specular), 0 18px 42px oklch(0 0 0 / 0.2);
      border-radius: 20px; padding: 10px; display: grid; gap: 10px; min-width: 0;
    }}
    .mode-tab {{
      min-height: 32px; padding: 6px 12px; border-radius: 10px; border: 1px solid transparent;
      background: transparent; color: var(--ink-1); font-family: var(--font-mono); font-size: 11px; letter-spacing: 0.06em; text-transform: uppercase; cursor: pointer;
    }}
    .mode-tab.active {{ background: var(--bg-2); color: var(--accent); border-color: color-mix(in oklch, var(--accent) 45%, transparent); }}
    .omni-row {{ display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }}
    .omni-input {{ flex: 1 1 220px; min-width: 0; background: var(--bg-2); border: 1px solid var(--border-control); border-radius: 10px; color: var(--ink-0); font-size: 15px; padding: 11px 14px; }}
    .btn-primary {{
      min-height: 42px; padding: 10px 18px; border-radius: 10px; border: 1px solid var(--accent);
      background: color-mix(in oklch, var(--accent) 18%, transparent); color: var(--ink-0); font-family: var(--font-mono); font-size: 12px; font-weight: 600; cursor: pointer; white-space: nowrap;
    }}
    .btn-primary.stop {{ border-color: var(--danger); background: color-mix(in oklch, var(--danger) 20%, transparent); }}
    .handoff-banner {{
      display: none; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; padding: 12px 16px; border-radius: 14px;
      background: color-mix(in oklch, var(--amber) 15%, transparent); border: 1px solid color-mix(in oklch, var(--amber) 50%, transparent); color: var(--ink-0); font-size: 13px;
    }}
    .handoff-banner.visible {{ display: flex; }}
    .bento {{ display: grid; grid-template-columns: repeat(12, 1fr); gap: 14px; min-width: 0; }}
    .card {{ background: var(--bg-1); border: 1px solid var(--hairline); box-shadow: var(--specular); border-radius: 16px; padding: 16px; display: flex; flex-direction: column; gap: 12px; min-width: 0; }}
    .span-7 {{ grid-column: span 7; }}
    .span-5 {{ grid-column: span 5; }}
    @media (max-width: 900px) {{ .span-7, .span-5 {{ grid-column: span 12; }} }}
    .card-head {{ display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; }}
    .card-title {{ font-family: var(--font-mono); font-size: 11px; letter-spacing: 0.1em; text-transform: uppercase; color: var(--ink-2); }}
    .list-scroll {{ display: grid; gap: 8px; max-height: 240px; overflow-y: auto; min-width: 0; }}
    .row-item {{ display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; padding: 9px 11px; border-radius: 10px; background: var(--bg-2); border: 1px solid var(--hairline); font-size: 13px; min-width: 0; }}
    .mono, code {{ font-family: var(--font-mono); font-size: 11px; color: var(--ink-2); font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }}
    .lease-tag {{ font-family: var(--font-mono); font-size: 10px; padding: 3px 8px; border-radius: 999px; background: color-mix(in oklch, var(--accent) 18%, transparent); color: var(--accent); }}
    .todo-input {{ flex: 1 1 140px; min-width: 0; background: var(--bg-2); border: 1px solid var(--border-control); border-radius: 10px; padding: 8px 10px; color: var(--ink-0); font-size: 13px; }}
    .todo-select {{ background: var(--bg-2); border: 1px solid var(--border-control); border-radius: 10px; padding: 8px; color: var(--ink-1); font-family: var(--font-mono); font-size: 11px; }}
    .progress-track {{ height: 5px; background: var(--bg-2); border-radius: 999px; overflow: hidden; }}
    .progress-fill {{ height: 100%; background: var(--accent); width: 0%; transition: width 220ms cubic-bezier(0.16, 1, 0.3, 1); }}
    .todo-done {{ text-decoration: line-through; color: var(--ink-2); }}
    .prio-high {{ color: var(--danger); }} .prio-medium {{ color: var(--amber); }} .prio-low {{ color: var(--accent); }}
    .toast-tray {{ position: fixed; right: 16px; bottom: 16px; z-index: 9999; display: grid; gap: 8px; max-width: min(360px, calc(100vw - 32px)); }}
    .toast {{ background: var(--bg-2); border: 1px solid var(--accent); box-shadow: 0 14px 32px oklch(0 0 0 / 0.35); border-radius: 12px; padding: 10px 14px; font-size: 12px; color: var(--ink-0); display: flex; justify-content: space-between; align-items: center; gap: 10px; }}
{LOGO_3D_CSS}
    @media (prefers-reduced-motion: reduce) {{ *, *::before, *::after {{ transition: none !important; animation: none !important; }} }}
  </style>
</head>
<body>
{logo_splash_html}
  <header>
    <div class="pill">
      <span class="dot" id="daemonDot"></span>
      <span id="daemonLabel">{brand_esc} · Zero Google Telemetry · Checking Agent Daemon...</span>
    </div>
    <div class="nav-actions">
      <button class="btn-ghost" type="button" id="btnReplayIntro">◈ 3D Emblem</button>
      <a class="btn-ghost" href="{html.escape(workspace_uri)}">✦ Generative UI Studio</a>
      <button class="btn-ghost" type="button" id="btnCopyMcp">Copy MCP Endpoint</button>
      <span id="clock">--:--:--</span>
    </div>
  </header>

  <main>
    <div class="hero">
      <div class="hero-brand-wrap">
        {logo_hero_badge_html}
        <div>
          <div class="kicker">CHROMIUM {html.escape(profile.chromium_version)} · CDP :{cdp_port} · MCP v2 :{agent_port} · TRAP .{html.escape(profile.trap_tld)}</div>
          <h1 id="greetingTitle">{brand_esc}</h1>
        </div>
      </div>
      <div class="mono">Simultaneous Human + AI Co-Browsing Active</div>
    </div>

    <div class="handoff-banner" id="handoffBanner" role="status" aria-live="polite">
      <div>
        <strong>PAUSED_HUMAN_HANDOFF:</strong>
        <span id="handoffText">An agent paused at a login/verification gate in a shared tab.</span>
      </div>
      <button class="btn-primary" type="button" id="btnResumeHandoff">Resume Agent ↵</button>
    </div>

    <div class="handoff-banner" id="mutationBanner" role="status" aria-live="polite">
      <div style="min-width:0;overflow-wrap:anywhere;">
        <strong>PAUSED_MUTATION_APPROVAL:</strong>
        <span id="mutationText">Network Mutation Firewall intercepted a mutating HTTP request.</span>
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;">
        <button class="btn-primary" type="button" id="btnApproveMutation">Approve ✓</button>
        <button class="btn-primary stop" type="button" id="btnRejectMutation">Reject ✕</button>
      </div>
    </div>

    <form class="omnibox" id="omniForm">
      <div class="mode-bar" role="tablist" aria-label="Omnibox Execution Mode">
        <button class="mode-tab active" type="button" role="tab" aria-selected="true" data-mode="search">🔍 Private Search ({eng_esc})</button>
        <button class="mode-tab" type="button" role="tab" aria-selected="false" data-mode="goal">🤖 Autonomous Agent Goal</button>
        <button class="mode-tab" type="button" role="tab" aria-selected="false" data-mode="bulk">⚡ Parallel Bulk Extract (URLs)</button>
      </div>
      <div class="omni-row">
        <label class="sr-only" for="omniInput">Search query, URL, or agent instruction</label>
        <input class="omni-input" id="omniInput" type="text" placeholder="Search privately, enter a URL, or switch to 🤖 Agent Goal..." autofocus autocomplete="off" />
        <button class="btn-primary" type="submit" id="omniSubmit">LAUNCH ↵</button>
      </div>
      <div class="mono" id="omniStatus" role="status" aria-live="polite">Zero Google telemetry · Human cursor &amp; keyboard always override agent leases.</div>
    </form>

    <div class="bento">
      <section class="card span-7" aria-labelledby="tabsCardHead">
        <div class="card-head">
          <span class="card-title" id="tabsCardHead">Live Co-Browsing Tabs &amp; Active Agent Leases (<span id="tabCount">0</span>)</span>
          <button class="btn-ghost" type="button" id="btnRefreshDaemon">Sync Live CDP</button>
        </div>
        <div class="list-scroll" id="liveTabsList">
          <div class="row-item"><span class="mono">Connecting to Agent Daemon (<code>:{agent_port}</code>)...</span></div>
        </div>

        <div class="card-head" style="margin-top: 6px;">
          <span class="card-title">Verifiable Action Ledger (<code>LUM-*</code> SHA-256 Chain)</span>
          <span class="mono" id="receiptCount">0 receipts</span>
        </div>
        <div class="list-scroll" id="receiptsList">
          <div class="row-item"><span class="mono">No <code>LUM-*</code> receipts recorded yet.</span></div>
        </div>
      </section>

      <section class="card span-5" aria-labelledby="workspaceCardHead">
        <div class="card-head">
          <span class="card-title" id="workspaceCardHead">Luminara Workspace &amp; Agent Memory</span>
          <div class="subtabs" role="tablist" aria-label="Luminara Workspace Panes">
            <button class="btn-ghost active" type="button" role="tab" aria-selected="true" data-pane="todos">Tasks</button>
            <button class="btn-ghost" type="button" role="tab" aria-selected="false" data-pane="vault">Vault &amp; Playbooks</button>
            <button class="btn-ghost" type="button" role="tab" aria-selected="false" data-pane="settings">Settings</button>
            <button class="btn-ghost" type="button" role="tab" aria-selected="false" data-pane="mcp">MCP Connect</button>
          </div>
        </div>

        <div id="pane-todos" style="display:grid; gap:10px;">
          <form class="todo-form" id="todoForm">
            <label class="sr-only" for="todoInput">New task description</label>
            <input class="todo-input" id="todoInput" type="text" placeholder="Add human or agent co-browsing task..." />
            <label class="sr-only" for="todoPrio">Task priority</label>
            <select class="todo-select" id="todoPrio">
              <option value="high">HIGH</option>
              <option value="medium" selected>MED</option>
              <option value="low">LOW</option>
            </select>
            <button class="btn-ghost" type="submit" id="btnAddTodo">Add</button>
          </form>
          <div class="progress-track" aria-label="Task completion progress"><div class="progress-fill" id="todoProgress"></div></div>
          <div class="list-scroll" id="todoList"></div>
        </div>

        <div id="pane-settings" style="display:none; gap:10px;">
          <label class="row-item" for="cfgOperator">
            <span>Operator Display Name</span>
            <input class="todo-input" id="cfgOperator" style="max-width:160px;" autocomplete="nickname" placeholder="Luminara" />
          </label>
          <label class="row-item" for="cfgShowHud">
            <span>Show <code>[1..N]</code> Set-of-Marks HUD on Agent Snapshots</span>
            <input type="checkbox" id="cfgShowHud" checked />
          </label>
          <label class="row-item" for="cfgPassport">
            <span>Agent Passport Token (optional)</span>
            <input class="todo-input" type="password" id="cfgPassport" style="max-width:160px;" autocomplete="off" placeholder="Bearer token" />
          </label>
          <div class="row-item">
            <span>Active Ungoogled Switches</span>
            <span class="mono" id="swCountBadge">0</span>
          </div>
          <button class="btn-primary" type="button" id="btnSaveSettings">Save Preferences</button>
        </div>

        <div id="pane-vault" style="display:none; gap:8px;">
          <div class="row-item">
            <span class="mono" id="vaultSummaryLbl">Loading DPAPI Vault &amp; Domain Playbooks...</span>
            <div style="display:flex;gap:6px;flex-wrap:wrap;">
              <button class="btn-ghost" type="button" id="btnToggleVaultForm">+ Add Credential</button>
              <button class="btn-ghost" type="button" id="btnSyncVault">Refresh</button>
            </div>
          </div>
          <form id="vaultRegForm" style="display:none; gap:6px; padding:10px; border-radius:10px; background:var(--bg-2); border:1px solid var(--hairline);">
            <label class="sr-only" for="vltOrigin">Vault origin URL</label>
            <input class="todo-input" id="vltOrigin" type="url" placeholder="Origin (e.g. https://portal.example.com)" required />
            <div style="display:flex;gap:6px;flex-wrap:wrap;">
              <label class="sr-only" for="vltUser">Vault username</label>
              <input class="todo-input" id="vltUser" type="text" placeholder="Username / Email" autocomplete="off" />
              <label class="sr-only" for="vltId">Vault handle ID</label>
              <input class="todo-input" id="vltId" type="text" placeholder="Handle ID (optional)" autocomplete="off" />
            </div>
            <div style="display:flex;gap:6px;flex-wrap:wrap;">
              <label class="sr-only" for="vltPass">Vault password</label>
              <input class="todo-input" id="vltPass" type="password" placeholder="Password (DPAPI/AEAD sealed)" autocomplete="new-password" />
              <label class="sr-only" for="vltTotp">Vault TOTP secret</label>
              <input class="todo-input" id="vltTotp" type="password" placeholder="Base32 / otpauth:// TOTP (optional)" autocomplete="off" />
            </div>
            <button class="btn-primary" type="submit">Seal Origin-Bound Credential</button>
          </form>
          <div class="list-scroll" id="vaultPlaybookList">
            <div class="row-item"><span class="mono">Syncing origin-pinned handles...</span></div>
          </div>
        </div>

        <div id="pane-mcp" style="display:none; gap:8px;">
          <div class="row-item" style="display:block;">
            <div class="mono" style="margin-bottom:4px;">MCP v2 JSON-RPC (<code>2025-06-18</code> · 28 Tools · 9 Resources)</div>
            <code>POST {daemon_base}/api/agent/mcp</code>
          </div>
          <div class="row-item" style="display:block;">
            <div class="mono" style="margin-bottom:4px;">Agent Discovery &amp; LLMs Manifest</div>
            <code>GET {daemon_base}/llms.txt</code><br />
            <code>GET {daemon_base}/.well-known/agent.json</code>
          </div>
          <div class="mono">Compatible with any standard MCP v2 (<code>2025-06-18</code>) agent client.</div>
        </div>
      </section>
    </div>
  </main>

  <footer>
    <span>TRAP SINK: *.{html.escape(profile.trap_tld)} → {html.escape(profile.trap_scheme)}:// → ERR_BLOCKED_BY_CLIENT</span>
    <span>LOCAL STORAGE NAMESPACE: <code>luminara_browser:*</code></span>
  </footer>

  <div class="toast-tray" id="toastTray" aria-live="polite"></div>

  <script>
    const DAEMON = (/^https?:$/i.test(location.protocol) && /^(127\\.0\\.0\\.1|localhost|\\[::1\\])$/i.test(location.hostname))
      ? location.origin
      : {_js_json(daemon_base)};
    const BRAND = {_js_json(profile.brand_name)};
    const SLUG = {_js_json(profile.slug)};
    const SEARCH_TPL = {_js_json(engine.search_url)};
    const SWITCHES = {_js_json(profile.runtime_switches())};
    const WORKSPACE_URI = {_js_json(workspace_uri)};
    const UI_KEY = {_js_json(ui_key)};
    const COBROWSE_ENABLED = {_js_json(bool(profile.enable_agent_cobrowsing))};
    const KEY_TODOS = 'luminara_browser:todos';
    const KEY_SETTINGS = 'luminara_browser:settings';
    const KEY_GENUI = 'luminara_browser:genui_payload';
    const KEY_SS = 'luminara_browser:session_tok';

    let omniMode = 'search';
    let activeHandoffRunId = null;
    let activeMutationId = null;
    let activeAbort = null;

    function el(tag, cls, text) {{
      const node = document.createElement(tag);
      if (cls) node.className = cls;
      if (text !== undefined) node.textContent = String(text);
      return node;
    }}

    let sessionTok = (() => {{
      const m = (location.hash || '').match(/(?:^#|&)lum_tok(?:en)?=([^&]+)/);
      if (m) {{
        const tok = decodeURIComponent(m[1]);
        try {{
          sessionStorage.setItem(KEY_SS, tok);
          history.replaceState(null, '', location.pathname + location.search);
        }} catch (_e) {{}}
        return tok;
      }}
      try {{ return sessionStorage.getItem(KEY_SS) || ''; }} catch (_e) {{ return ''; }}
    }})();

    let agentSessionTok = '';
    function apiHeaders(isJson) {{
      const h = {{}};
      const uiAuth = UI_KEY || sessionTok;
      if (uiAuth) h['X-Luminara-UI-Key'] = uiAuth;
      const passport = agentSessionTok || (loadSettings().passportToken || '').trim();
      if (passport) h['Authorization'] = 'Bearer ' + passport;
      if (isJson) h['Content-Type'] = 'application/json';
      return h;
    }}

    async function exchangePassportSession() {{
      if (UI_KEY || sessionTok || agentSessionTok || !(loadSettings().passportToken || '').trim()) return;
      try {{
        const r = await fetch(DAEMON + '/api/agent/session-token', {{
          method: 'POST',
          headers: apiHeaders(true),
          body: JSON.stringify({{ scope: 'agent', ttl_sec: 900 }}),
          signal: AbortSignal.timeout(4000)
        }});
        if (r.ok) {{
          const d = await r.json();
          if (d && d.token) agentSessionTok = d.token;
        }}
      }} catch (_e) {{}}
    }}

    async function apiFetch(path, body, signal) {{
      const isPost = body !== undefined;
      const res = await fetch(DAEMON + path, {{
        method: isPost ? 'POST' : 'GET',
        headers: apiHeaders(isPost),
        body: isPost ? JSON.stringify(body) : undefined,
        signal: signal || AbortSignal.timeout(15000)
      }});
      const data = await res.json().catch(() => ({{}}));
      if (!res.ok) throw new Error(data.error || ('HTTP ' + res.status));
      return data;
    }}

    function notify(msg) {{
      const tray = document.getElementById('toastTray');
      const box = el('div', 'toast');
      const close = el('button', 'btn-ghost', '×');
      close.type = 'button';
      close.setAttribute('aria-label', 'Dismiss notification');
      close.onclick = () => box.remove();
      box.append(el('span', '', msg), close);
      tray.appendChild(box);
      setTimeout(() => box.remove(), 4800);
    }}

    function loadSettings() {{
      try {{ return JSON.parse(localStorage.getItem(KEY_SETTINGS) || '{{}}'); }}
      catch (_e) {{ return {{}}; }}
    }}
    function safeSetLS(k, v) {{
      try {{ localStorage.setItem(k, v); }} catch (_e) {{}}
    }}
    function applySettings() {{
      const s = loadSettings();
      document.getElementById('cfgOperator').value = s.operator || 'Luminara Operator';
      document.getElementById('cfgShowHud').checked = s.showHud !== false;
      const pEl = document.getElementById('cfgPassport');
      if (pEl) pEl.value = s.passportToken || '';
      document.getElementById('swCountBadge').textContent = SWITCHES.length + ' active';
      if (s.operator) {{
        document.getElementById('greetingTitle').textContent = BRAND + ' · ' + s.operator;
      }}
    }}
    document.getElementById('btnSaveSettings').addEventListener('click', async () => {{
      const pEl = document.getElementById('cfgPassport');
      const s = {{
        operator: document.getElementById('cfgOperator').value.trim() || 'Luminara Operator',
        showHud: document.getElementById('cfgShowHud').checked,
        passportToken: pEl ? pEl.value.trim() : ''
      }};
      safeSetLS(KEY_SETTINGS, JSON.stringify(s));
      applySettings();
      await exchangePassportSession();
      syncDaemon();
      notify('Saved workspace settings.');
    }});

    document.querySelectorAll('[data-pane]').forEach(btn => {{
      btn.addEventListener('click', () => {{
        const target = btn.getAttribute('data-pane');
        document.querySelectorAll('[data-pane]').forEach(b => {{
          const active = b === btn;
          b.classList.toggle('active', active);
          b.setAttribute('aria-selected', String(active));
        }});
        ['todos', 'vault', 'settings', 'mcp'].forEach(p => {{
          document.getElementById('pane-' + p).style.display = (p === target) ? 'grid' : 'none';
        }});
        if (target === 'vault') syncVaultAndPlaybooks();
      }});
    }});

    function getTodos() {{
      try {{
        const raw = localStorage.getItem(KEY_TODOS);
        if (raw) return JSON.parse(raw);
      }} catch (_e) {{}}
      const seed = [
        {{ id: 't1', text: 'Index live tab with [1..N] Set-of-Marks Copilot', prio: 'high', done: false }},
        {{ id: 't2', text: 'Synthesize Generative UI sortable matrix from multi-URL bulk run', prio: 'medium', done: false }}
      ];
      safeSetLS(KEY_TODOS, JSON.stringify(seed));
      return seed;
    }}
    function saveTodos(list) {{
      safeSetLS(KEY_TODOS, JSON.stringify(list));
      renderTodos();
    }}
    function renderTodos() {{
      const list = getTodos();
      const doneCount = list.filter(t => t.done).length;
      const pct = list.length ? Math.round((doneCount / list.length) * 100) : 0;
      document.getElementById('todoProgress').style.width = pct + '%';
      const box = document.getElementById('todoList');
      box.replaceChildren();
      if (!list.length) {{
        const empty = el('div', 'row-item');
        empty.appendChild(el('span', 'mono', 'All tasks cleared — add a co-browsing goal above.'));
        box.appendChild(empty);
        return;
      }}
      list.forEach(item => {{
        const row = el('div', 'row-item');
        const left = el('label');
        left.style.cssText = 'display:flex;align-items:center;gap:8px;cursor:pointer;flex:1;min-width:0;';
        const cb = document.createElement('input');
        cb.type = 'checkbox';
        cb.checked = Boolean(item.done);
        cb.onchange = () => {{ item.done = cb.checked; saveTodos(list); }};
        const txt = el('span', item.done ? 'todo-done' : '', item.text);
        left.append(cb, txt);

        const right = el('div');
        right.style.cssText = 'display:flex;align-items:center;gap:6px;';
        const pr = el('span', 'mono prio-' + (item.prio || 'medium'), (item.prio || 'med').toUpperCase());
        const del = el('button', 'btn-ghost', '×');
        del.type = 'button';
        del.setAttribute('aria-label', 'Delete task ' + item.text);
        del.onclick = () => saveTodos(list.filter(x => x.id !== item.id));
        right.append(pr, del);
        row.append(left, right);
        box.appendChild(row);
      }});
    }}
    document.getElementById('todoForm').addEventListener('submit', e => {{
      e.preventDefault();
      const inp = document.getElementById('todoInput');
      const val = inp.value.trim();
      if (!val) return;
      const list = getTodos();
      list.unshift({{ id: 't_' + Date.now(), text: val, prio: document.getElementById('todoPrio').value, done: false }});
      inp.value = '';
      saveTodos(list);
      notify('Task added to Luminara Workspace.');
    }});

    async function syncVaultAndPlaybooks() {{
      const sumLbl = document.getElementById('vaultSummaryLbl');
      const vBox = document.getElementById('vaultPlaybookList');
      const btn = document.getElementById('btnSyncVault');
      btn.disabled = true;
      sumLbl.textContent = 'Syncing Vault & Playbooks...';
      try {{
        const [vRes, pRes] = await Promise.all([apiFetch('/api/agent/vault'), apiFetch('/api/agent/playbooks')]);
        const entries = vRes.entries || [];
        const pbs = pRes.playbooks || [];
        sumLbl.textContent = `${{entries.length}} Vault handle(s) · ${{pbs.length}} Playbook(s)`;
        vBox.replaceChildren();
        if (!entries.length && !pbs.length) {{
          const emptyRow = el('div', 'row-item');
          emptyRow.appendChild(el('span', 'mono', 'No vault handles or learned playbooks yet.'));
          vBox.appendChild(emptyRow);
        }} else {{
          entries.forEach(en => {{
            const r = el('div', 'row-item');
            const left = el('div');
            left.style.cssText = 'display:grid;min-width:0;';
            left.append(el('strong', '', '🔐 ' + (en.vault_id || '')), el('span', 'mono', en.origin || ''));
            const acts = el('div');
            acts.style.cssText = 'display:flex;gap:4px;align-items:center;flex-wrap:wrap;';
            const bFill = el('button', 'btn-ghost', 'Fill');
            bFill.type = 'button';
            bFill.onclick = async () => {{
              try {{
                const res = await apiFetch('/api/agent/vault', {{ action: 'fill', vault_id: en.vault_id }});
                notify('Filled ' + ((res.filled_fields || []).join(', ') || 'handle'));
              }} catch (err) {{ notify('Vault fill failed: ' + err.message); }}
            }};
            acts.appendChild(bFill);
            if (en.has_totp) {{
              const bOtp = el('button', 'btn-ghost', 'TOTP');
              bOtp.type = 'button';
              bOtp.onclick = async () => {{
                try {{
                  await apiFetch('/api/agent/vault', {{ action: 'enter_totp', vault_id: en.vault_id }});
                  notify('Injected 6-digit TOTP for ' + en.vault_id);
                }} catch (err) {{ notify('TOTP failed: ' + err.message); }}
              }};
              acts.appendChild(bOtp);
            }}
            const bDel = el('button', 'btn-ghost', '×');
            bDel.type = 'button';
            bDel.setAttribute('aria-label', 'Delete vault entry ' + en.vault_id);
            bDel.onclick = async () => {{
              try {{
                await apiFetch('/api/agent/vault', {{ action: 'delete', vault_id: en.vault_id }});
                notify('Deleted vault handle ' + en.vault_id);
                syncVaultAndPlaybooks();
              }} catch (err) {{ notify('Delete failed: ' + err.message); }}
            }};
            acts.appendChild(bDel);
            r.append(left, acts);
            vBox.appendChild(r);
          }});
          pbs.forEach(pb => {{
            const r = el('div', 'row-item');
            const left = el('div');
            left.style.cssText = 'display:grid;min-width:0;';
            left.append(el('strong', '', '⚡ ' + (pb.domain || '')), el('span', 'mono', (pb.goal_example || pb.goal || pb.playbook_id || '') + ' (' + (pb.steps ? pb.steps.length : 0) + ' steps)'));
            const acts = el('div');
            acts.style.cssText = 'display:flex;gap:4px;align-items:center;';
            const bRep = el('button', 'btn-ghost', 'Replay');
            bRep.type = 'button';
            bRep.onclick = async () => {{
              try {{
                const res = await apiFetch('/api/agent/playbooks', {{ action: 'replay', playbook_id: pb.playbook_id }});
                if (res && res.generative_ui) safeSetLS(KEY_GENUI, JSON.stringify(res.generative_ui));
                notify('Playbook ' + (res.status || 'COMPLETED'));
              }} catch (err) {{ notify('Replay failed: ' + err.message); }}
            }};
            const bDel = el('button', 'btn-ghost', '×');
            bDel.type = 'button';
            bDel.setAttribute('aria-label', 'Delete playbook ' + pb.playbook_id);
            bDel.onclick = async () => {{
              try {{
                await apiFetch('/api/agent/playbooks', {{ action: 'delete', playbook_id: pb.playbook_id }});
                notify('Deleted playbook ' + pb.playbook_id);
                syncVaultAndPlaybooks();
              }} catch (err) {{ notify('Delete failed: ' + err.message); }}
            }};
            acts.append(bRep, bDel);
            r.append(left, acts);
            vBox.appendChild(r);
          }});
        }}
      }} catch (_err) {{
        sumLbl.textContent = 'Daemon offline — unable to load Vault & Playbooks.';
        vBox.replaceChildren();
        const errR = el('div', 'row-item');
        const retryB = el('button', 'btn-ghost', 'Retry');
        retryB.type = 'button';
        retryB.onclick = syncVaultAndPlaybooks;
        errR.append(el('span', 'mono', 'Connect Agent Daemon then retry.'), retryB);
        vBox.appendChild(errR);
      }} finally {{
        btn.disabled = false;
      }}
    }}
    document.getElementById('btnSyncVault').addEventListener('click', syncVaultAndPlaybooks);
    document.getElementById('btnToggleVaultForm').addEventListener('click', () => {{
      const f = document.getElementById('vaultRegForm');
      f.style.display = f.style.display === 'none' ? 'grid' : 'none';
    }});
    document.getElementById('vaultRegForm').addEventListener('submit', async e => {{
      e.preventDefault();
      const origin = document.getElementById('vltOrigin').value.trim();
      const username = document.getElementById('vltUser').value.trim();
      const vault_id = document.getElementById('vltId').value.trim() || undefined;
      const password = document.getElementById('vltPass').value;
      const totp_secret = document.getElementById('vltTotp').value.trim();
      if (!password && !totp_secret) {{
        notify('Provide at least a password or TOTP secret.');
        return;
      }}
      try {{
        const res = await apiFetch('/api/agent/vault', {{ action: 'register', origin, username, vault_id, password, totp_secret }});
        document.getElementById('vltPass').value = '';
        document.getElementById('vltTotp').value = '';
        document.getElementById('vaultRegForm').style.display = 'none';
        notify('Sealed credential handle ' + (res.entry ? res.entry.vault_id : ''));
        syncVaultAndPlaybooks();
      }} catch (err) {{ notify('Vault registration failed: ' + err.message); }}
    }});

    const placeholders = {{
      search: 'Search privately or enter any URL...',
      goal: 'Describe an autonomous browser goal (e.g., "Type \\\'Quantum\\\' and click Apply Filter")...',
      bulk: 'Paste comma- or space-separated URLs for parallel background tab extraction...'
    }};
    document.querySelectorAll('.mode-tab').forEach(btn => {{
      btn.addEventListener('click', () => {{
        document.querySelectorAll('.mode-tab').forEach(b => {{
          const active = b === btn;
          b.classList.toggle('active', active);
          b.setAttribute('aria-selected', String(active));
        }});
        omniMode = btn.getAttribute('data-mode');
        document.getElementById('omniInput').placeholder = placeholders[omniMode];
      }});
    }});

    document.getElementById('omniForm').addEventListener('submit', async e => {{
      e.preventDefault();
      const submitBtn = document.getElementById('omniSubmit');
      const statusEl = document.getElementById('omniStatus');

      if (activeAbort) {{
        activeAbort.abort();
        activeAbort = null;
        apiFetch('/api/agent/act', {{ action: 'human_takeover' }}).catch(() => {{}});
        submitBtn.textContent = 'LAUNCH ↵';
        submitBtn.classList.remove('stop');
        statusEl.textContent = 'Execution aborted by operator.';
        return;
      }}

      const val = document.getElementById('omniInput').value.trim();
      if (!val) return;

      if (omniMode === 'search') {{
        if (/^(https?:\\/\\/|file:\\/\\/|about:)/i.test(val)) {{
          window.location.href = val;
        }} else if (/^(localhost|127\\.0\\.0\\.1|\\[::1\\])(:\\d+)?(\\/.*)?$/i.test(val) && !val.includes(' ')) {{
          window.location.href = 'http://' + val;
        }} else if (/^[a-z0-9-]+(\\.[a-z0-9-]+)+(:\\d+)?(\\/.*)?$/i.test(val) && !val.includes(' ')) {{
          window.location.href = 'https://' + val;
        }} else {{
          window.location.href = SEARCH_TPL.replace('{{searchTerms}}', encodeURIComponent(val));
        }}
        return;
      }}

      const runCtrl = new AbortController();
      activeAbort = runCtrl;
      submitBtn.textContent = 'STOP ■';
      submitBtn.classList.add('stop');

      try {{
        if (omniMode === 'goal') {{
          statusEl.textContent = 'Running autonomous perceive-decide-act loop (click STOP ■ to abort)...';
          const data = await apiFetch('/api/agent/goal', {{ goal: val, show_badges: loadSettings().showHud !== false, agent_id: 'omnibox-autopilot' }}, runCtrl.signal);
          if (data.generative_ui) safeSetLS(KEY_GENUI, JSON.stringify(data.generative_ui));
          const rid = data.receipt ? data.receipt.receipt_id : 'n/a';
          statusEl.textContent = `Status: ${{data.status}} · Provider: ${{data.provider || 'heuristic'}} · Receipt: ${{rid}}`;
          notify('Goal ' + data.status);
          syncDaemon();
        }} else if (omniMode === 'bulk') {{
          const urls = val.split(/[\\s,]+/).filter(Boolean);
          statusEl.textContent = `Running parallel BulkEngine across ${{urls.length}} URL(s)...`;
          const data = await apiFetch('/api/agent/bulk', {{ urls, concurrency: 4 }}, runCtrl.signal);
          if (data.generative_ui) safeSetLS(KEY_GENUI, JSON.stringify(data.generative_ui));
          const rid = data.receipt ? data.receipt.receipt_id : 'n/a';
          statusEl.textContent = `Extracted ${{data.row_count || 0}} rows (${{rid}}) — Opening Generative UI Studio...`;
          notify(`Extracted ${{data.row_count || 0}} rows!`);
          setTimeout(() => {{ window.location.href = WORKSPACE_URI; }}, 550);
        }}
      }} catch (err) {{
        if (err && err.name === 'AbortError') return;
        statusEl.textContent = 'Action failed: ' + (err.message || String(err)) + ' — Verify Agent Daemon is online and retry.';
      }} finally {{
        if (activeAbort === runCtrl) {{
          activeAbort = null;
          submitBtn.textContent = 'LAUNCH ↵';
          submitBtn.classList.remove('stop');
        }}
      }}
    }});

    async function syncDaemon() {{
      const dot = document.getElementById('daemonDot');
      const lbl = document.getElementById('daemonLabel');
      const refreshBtn = document.getElementById('btnRefreshDaemon');
      if (!COBROWSE_ENABLED) {{
        dot.classList.add('offline');
        lbl.textContent = `${{BRAND}} · Zero Google Telemetry · Standalone Privacy Mode`;
        const tBox = document.getElementById('liveTabsList');
        tBox.replaceChildren();
        const r = el('div', 'row-item');
        r.appendChild(el('span', 'mono', 'Agent co-browsing is disabled in ForkProfile.'));
        tBox.appendChild(r);
        return;
      }}
      refreshBtn.disabled = true;
      try {{
        await exchangePassportSession();
        const [st, tb] = await Promise.all([
          apiFetch('/api/agent/status', undefined, AbortSignal.timeout(2200)),
          apiFetch('/api/agent/tabs', undefined, AbortSignal.timeout(2200))
        ]);
        dot.classList.remove('offline');
        lbl.textContent = `${{BRAND}} · CDP ${{st.cdp_connected ? 'LIVE' : 'STANDBY'}} · MCP v2 READY`;

        const banner = document.getElementById('handoffBanner');
        if (st.active_handoffs && st.active_handoffs.length > 0) {{
          const h = st.active_handoffs[0];
          activeHandoffRunId = h.run_id;
          document.getElementById('handoffText').textContent = `${{h.gate_type}} on ${{h.url}} (Goal: ${{h.goal}})`;
          banner.classList.add('visible');
        }} else {{
          activeHandoffRunId = null;
          banner.classList.remove('visible');
        }}

        const mutBanner = document.getElementById('mutationBanner');
        const pendMuts = st.pending_mutations || [];
        if (pendMuts.length > 0) {{
          const m = pendMuts[0];
          activeMutationId = m.mutation_id;
          document.getElementById('mutationText').textContent = `[${{m.risk_level || 'MEDIUM'}}] ${{m.method}} ${{m.url}} (${{pendMuts.length}} queued)`;
          mutBanner.classList.add('visible');
        }} else {{
          activeMutationId = null;
          mutBanner.classList.remove('visible');
        }}

        const tabs = (tb.tabs || []).filter(t => {{
          const u = String(t.url || '');
          return !/^(chrome(-extension)?:\\/\\/|devtools:\\/\\/|about:)/i.test(u) && !/\\/(newtab|workspace)(\\.html)?([?#]|$)/i.test(u);
        }});
        document.getElementById('tabCount').textContent = String(tabs.length);
        const tBox = document.getElementById('liveTabsList');
        tBox.replaceChildren();
        if (!tabs.length) {{
          const emptyRow = el('div', 'row-item');
          emptyRow.appendChild(el('span', 'mono', st.cdp_connected ? 'No shared web tabs open — launch a URL in the omnibox above.' : 'CDP standby — launch browser via Launch-' + SLUG + '.cmd for live tab sync.'));
          tBox.appendChild(emptyRow);
        }} else {{
          tabs.forEach(t => {{
            const row = el('div', 'row-item');
            const left = el('div');
            left.style.cssText = 'min-width:0;overflow-wrap:anywhere;';
            left.append(
              el('div', '', (t.title || 'Untitled Tab').slice(0, 60)),
              el('div', 'mono', (t.url || '').slice(0, 72))
            );
            const right = el('div');
            right.style.cssText = 'display:flex;gap:6px;align-items:center;flex-wrap:wrap;';
            if (t.lease) {{
              right.appendChild(el('span', 'lease-tag', 'LEASED: ' + t.lease.agent_id));
              const takeBtn = el('button', 'btn-ghost', 'Takeover');
              takeBtn.type = 'button';
              takeBtn.onclick = async () => {{
                takeBtn.disabled = true;
                try {{
                  await apiFetch('/api/agent/act', {{ action: 'human_takeover', target_id: t.target_id }});
                  notify('Human preempted agent lease.');
                  syncDaemon();
                }} catch (err) {{ notify('Takeover error: ' + err.message); }}
                finally {{ takeBtn.disabled = false; }}
              }};
              right.appendChild(takeBtn);
            }} else {{
              const genBtn = el('button', 'btn-ghost', '→ GenUI');
              genBtn.type = 'button';
              genBtn.onclick = async () => {{
                genBtn.disabled = true;
                genBtn.textContent = 'Capturing...';
                try {{
                  const d = await apiFetch('/api/agent/genui', {{ target_id: t.target_id }});
                  if (d.generative_ui) {{
                    safeSetLS(KEY_GENUI, JSON.stringify(d.generative_ui));
                    window.location.href = WORKSPACE_URI;
                  }}
                }} catch (err) {{
                  notify('GenUI capture failed: ' + err.message);
                  genBtn.disabled = false;
                  genBtn.textContent = '→ GenUI';
                }}
              }};
              right.appendChild(genBtn);
            }}
            row.append(left, right);
            tBox.appendChild(row);
          }});
        }}

        const recs = st.recent_receipts || [];
        document.getElementById('receiptCount').textContent = recs.length + ' recent';
        const rBox = document.getElementById('receiptsList');
        rBox.replaceChildren();
        if (!recs.length) {{
          const emptyRc = el('div', 'row-item');
          emptyRc.appendChild(el('span', 'mono', 'No LUM-* receipts yet — run a Snapshot, Goal, or Bulk Extract.'));
          rBox.appendChild(emptyRc);
        }} else {{
          recs.forEach(rc => {{
            const row = el('div', 'row-item');
            const leftRc = el('div');
            leftRc.style.minWidth = '0';
            leftRc.append(el('strong', '', rc.action || ''), document.createTextNode(' · ' + (rc.summary || '')));
            row.append(leftRc, el('span', 'mono', rc.receipt_id || ''));
            rBox.appendChild(row);
          }});
        }}
        if (window.__luminaraSplashNotifyDaemon) window.__luminaraSplashNotifyDaemon(true, st);
      }} catch (_e) {{
        if (window.__luminaraSplashNotifyDaemon) window.__luminaraSplashNotifyDaemon(false, null);
        dot.classList.add('offline');
        lbl.textContent = `${{BRAND}} · Offline Vault Mode`;
        const tBox = document.getElementById('liveTabsList');
        tBox.replaceChildren();
        const errRow = el('div', 'row-item');
        errRow.append(
          el('span', 'mono', 'Agent Daemon unreachable on ' + DAEMON + '. Start Launch-' + SLUG + '.cmd then retry.'),
          (() => {{
            const retry = el('button', 'btn-ghost', 'Retry');
            retry.type = 'button';
            retry.onclick = syncDaemon;
            return retry;
          }})()
        );
        tBox.appendChild(errRow);
      }} finally {{
        refreshBtn.disabled = false;
      }}
    }}

    document.getElementById('btnResumeHandoff').addEventListener('click', async e => {{
      if (!activeHandoffRunId) return;
      const btn = e.currentTarget;
      btn.disabled = true;
      btn.textContent = 'Resuming...';
      try {{
        const res = await apiFetch('/api/agent/handoff/resume', {{ run_id: activeHandoffRunId }}, AbortSignal.timeout(35000));
        if (res && res.generative_ui) safeSetLS(KEY_GENUI, JSON.stringify(res.generative_ui));
        notify('Resumed agent goal after human handoff.');
        syncDaemon();
      }} catch (err) {{ notify('Resume failed: ' + err.message); }}
      finally {{ btn.disabled = false; btn.textContent = 'Resume Agent ↵'; }}
    }});
    async function resolveBannerMutation(decision) {{
      if (!activeMutationId) return;
      try {{
        await exchangePassportSession();
        await apiFetch('/api/agent/mutations', {{ action: decision, mutation_id: activeMutationId }});
        notify('Mutation ' + decision + 'd.');
        syncDaemon();
      }} catch (err) {{ notify('Mutation action failed: ' + err.message); }}
    }}
    document.getElementById('btnApproveMutation').addEventListener('click', () => resolveBannerMutation('approve'));
    document.getElementById('btnRejectMutation').addEventListener('click', () => resolveBannerMutation('reject'));
    document.getElementById('btnRefreshDaemon').addEventListener('click', syncDaemon);
    document.getElementById('btnCopyMcp').addEventListener('click', async () => {{
      try {{
        await navigator.clipboard.writeText(DAEMON + '/api/agent/mcp');
        notify('Copied MCP v2 endpoint to clipboard.');
      }} catch (_e) {{ notify('MCP endpoint: ' + DAEMON + '/api/agent/mcp'); }}
    }});

    document.querySelectorAll('[role="tablist"]').forEach(list => {{
      const tabs = Array.from(list.querySelectorAll('[role="tab"]'));
      tabs.forEach((t, i) => t.addEventListener('keydown', e => {{
        if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
        e.preventDefault();
        const nxt = tabs[(i + (e.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length];
        nxt.focus();
        nxt.click();
      }}));
    }});
    {logo_3d_js}
    applySettings();
    renderTodos();
    syncDaemon();
    if (COBROWSE_ENABLED) setInterval(syncDaemon, 5000);
    setInterval(() => {{ document.getElementById('clock').textContent = new Date().toLocaleTimeString(); }}, 1000);
    {palette_iife}
  </script>
</body>
</html>
"""


__all__ = [
    "build_luminara_newtab_html",
    "build_luminara_workspace_html",
    "write_copilot_extension",
]
