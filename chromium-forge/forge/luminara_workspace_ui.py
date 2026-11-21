"""Clean-room Generative UI Workspace Generator (`forge/luminara_workspace_ui.py`).

Production upgrades:
- Zero dynamic `.innerHTML` (full DOM XSS immunity across `SummaryBar` KPIs and `TableView`).
- Real interactive column sorting (`aria-sort` + natural numeric `Intl.Collator`) in `Sortable Table`.
- Unified `getVisibleEntities()` shared across `ComparisonView`, `Sortable Table`, `SummaryBar`, and RFC 4180 CSV/JSON/MD Export.
- Input-safe `Ctrl+Z` / `Ctrl+Shift+Z` / `Ctrl+Y` 50-slot `CommandHistory` + cross-origin `/api/agent/genui/sync`.
- Automatic hydration from `GET /api/agent/genui/latest` (`hadLocalGenUi` + `Math.max(generated_at, updated_at)`) + Passport Token bar.
"""

from __future__ import annotations

import html

from .luminara_copilot_ext import (
    _js_json,
    build_palette_js,
    make_solid_emerald_png,
    write_copilot_extension,
)
from .luminara_logo3d import get_logo_favicon_data_uri
from .luminara_telemetry_ui import build_telemetry_cockpit_css, build_telemetry_cockpit_js
from .models import ForkProfile

ENCODING = "utf-8"


def build_luminara_workspace_html(
    profile: ForkProfile,
    newtab_uri: str = "./newtab.html",
    agent_port: int = 8796,
    ui_key: str = "",
) -> str:
    """Clean-room Generative UI Studio (`SummaryBar`, `ComparisonView`, `Sortable Table`, `StackView`, 50-slot Undo/Redo)."""
    brand_esc = html.escape(profile.brand_name)
    daemon_base = f"http://127.0.0.1:{agent_port}"
    palette_iife = build_palette_js(profile.resolved_search_engine().search_url, agent_port=agent_port)
    tele_css = build_telemetry_cockpit_css()
    tele_js = build_telemetry_cockpit_js()
    favicon_uri = get_logo_favicon_data_uri()

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="color-scheme" content="dark light" />
  <link rel="icon" type="image/png" href="{favicon_uri}" />
  <title>{brand_esc} — Generative UI Workspace</title>
  <style>
    :root {{
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
      --font-mono: 'JetBrains Mono', Consolas, monospace;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    :focus-visible {{ outline: 2px solid var(--accent); outline-offset: 2px; }}
    body {{
      min-height: 100dvh; background: var(--bg-0); color: var(--ink-0);
      font-family: var(--font-sans); padding: clamp(0.85rem, 2.5vw, 2rem);
      display: grid; gap: 16px; align-content: start;
    }}
    header, .toolbar, .auth-bar, .kpi-bar, .status-line, main {{ max-width: 1280px; width: 100%; margin: 0 auto; min-width: 0; }}
    header {{ display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; }}
    .toolbar, .auth-bar {{
      background: var(--bg-1); border: 1px solid var(--hairline); box-shadow: var(--specular);
      border-radius: 16px; padding: 12px; display: flex; justify-content: space-between; flex-wrap: wrap; gap: 10px; align-items: center;
    }}
    .auth-bar {{ display: none; border-color: color-mix(in oklch, var(--amber) 50%, transparent); }}
    .auth-bar.visible {{ display: flex; }}
    .btn {{
      min-height: 32px;
      padding: 8px 13px; border-radius: 10px; border: 1px solid var(--border-control);
      background: var(--bg-2); color: var(--ink-0); font-family: var(--font-mono);
      font-size: 11px; cursor: pointer; text-decoration: none; display: inline-flex; align-items: center;
    }}
    .btn.active {{ border-color: var(--accent); color: var(--accent); }}
    .btn:disabled {{ opacity: 0.45; cursor: not-allowed; }}
    .search-box {{
      min-height: 32px; width: 185px; max-width: 100%;
      background: var(--bg-2); border: 1px solid var(--border-control); border-radius: 10px;
      color: var(--ink-0); font-family: var(--font-mono); font-size: 11.5px; text-align: left; padding: 6px 10px;
    }}
    .status-line {{ font-family: var(--font-mono); font-size: 11.5px; color: var(--ink-2); }}
    .status-line.err {{ color: var(--danger); }}
    .kpi-bar {{
      display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 170px), 1fr)); gap: 12px;
    }}
    .kpi-card {{
      background: var(--bg-1); border: 1px solid var(--hairline); box-shadow: var(--specular);
      border-radius: 14px; padding: 14px; font-variant-numeric: tabular-nums; min-width: 0;
    }}
    .kpi-label {{ font-family: var(--font-mono); font-size: 11px; color: var(--ink-2); text-transform: uppercase; }}
    .kpi-val {{ font-size: 24px; font-weight: 700; margin-top: 4px; color: var(--accent); }}
    .grid-cards {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 280px), 1fr)); gap: 14px; }}
    .ent-card {{
      background: var(--bg-1); border: 1px solid var(--hairline); box-shadow: var(--specular);
      border-radius: 16px; padding: 16px; display: grid; gap: 10px; min-width: 0;
    }}
    .ent-title {{ font-size: 16px; font-weight: 600; overflow-wrap: anywhere; }}
    .attr-row {{
      display: flex; justify-content: space-between; align-items: center; gap: 8px;
      padding: 6px 8px; border-radius: 8px; background: var(--bg-2); font-size: 12px; min-width: 0;
    }}
    .attr-val {{
      flex: 1 1 90px; min-width: 0; min-height: 26px;
      background: transparent; border: 1px solid transparent; color: var(--ink-0);
      font-family: var(--font-mono); font-size: 12px; text-align: right; padding: 3px 6px; border-radius: 6px;
      font-variant-numeric: tabular-nums;
    }}
    .attr-val:focus {{ border-color: var(--accent); background: var(--bg-0); }}
    .table-wrap {{ width: 100%; overflow-x: auto; border-radius: 14px; border: 1px solid var(--hairline); }}
    table {{ width: 100%; border-collapse: collapse; background: var(--bg-1); font-variant-numeric: tabular-nums; }}
    th, td {{ padding: 10px 12px; border-bottom: 1px solid var(--hairline); text-align: left; font-size: 13px; }}
    th {{ background: var(--bg-2); padding: 0; }}
    .th-sort {{
      width: 100%; padding: 10px 12px; background: transparent; border: 0; cursor: pointer;
      display: flex; justify-content: space-between; align-items: center; gap: 6px;
      font-family: var(--font-mono); font-size: 11px; text-transform: uppercase; color: var(--ink-2);
    }}
    .th-sort:hover {{ color: var(--accent); }}
    {tele_css}
    @media (prefers-reduced-motion: reduce) {{
      *, *::before, *::after {{ transition: none !important; animation: none !important; }}
    }}
  </style>
</head>
<body>
  <header>
    <div>
      <div style="font-family:var(--font-mono);font-size:11px;color:var(--accent);letter-spacing:0.11em;">GENERATIVE UI WORKSPACE · 50-SLOT COMMAND HISTORY</div>
      <h1 id="wsTitle" style="font-size:clamp(1.35rem,2.4vw,1.75rem);letter-spacing:-0.03em;">Extracted Entity Studio</h1>
    </div>
    <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
      <a class="btn" href="{html.escape(newtab_uri)}">← Command Deck</a>
      <button class="btn" type="button" id="btnCaptureActive">Capture Live Tab</button>
    </div>
  </header>

  <form class="auth-bar" id="wsAuthBar">
    <label class="status-line" for="wsPassportInput">Agent Passport or Human UI Key required by daemon:</label>
    <div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center;">
      <input class="search-box" id="wsPassportInput" type="password" placeholder="Enter Token or 64-hex UI Key" autocomplete="off" />
      <button class="btn active" type="submit">Authenticate ↵</button>
    </div>
  </form>

  <div class="toolbar">
    <div style="display:flex;gap:6px;flex-wrap:wrap;" role="tablist" aria-label="Workspace Layout Mode" id="wsTabList">
      <button class="btn active" type="button" role="tab" aria-selected="true" data-view="comparison">Comparison Cards</button>
      <button class="btn" type="button" role="tab" aria-selected="false" data-view="table">Sortable Table</button>
      <button class="btn" type="button" role="tab" aria-selected="false" data-view="stack">Stack Inspector</button>
      <button class="btn" type="button" role="tab" aria-selected="false" data-view="telemetry">Telemetry Cockpit</button>
    </div>
    <div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center;" id="entityToolsGroup">
      <input class="search-box" id="wsSearch" type="search" placeholder="Filter entities..." aria-label="Filter workspace entities" />
      <button class="btn" type="button" id="btnUndo" disabled>↶ Undo (Ctrl+Z)</button>
      <button class="btn" type="button" id="btnRedo" disabled>↷ Redo (Ctrl+Y)</button>
      <button class="btn" type="button" data-dl="json">Export JSON</button>
      <button class="btn" type="button" data-dl="csv">Export CSV</button>
      <button class="btn" type="button" data-dl="md">Export Markdown</button>
    </div>
  </div>

  <div class="status-line" id="wsStatus" role="status" aria-live="polite">Ready · Click any cell to edit with 50-slot Undo/Redo, or switch to Sortable Table to sort columns.</div>
  <section class="kpi-bar" id="kpiBar" aria-label="Key Metric Summary"></section>
  <main id="viewContainer"></main>

  <script>
    const DAEMON = (/^https?:$/i.test(location.protocol) && /^(127\\.0\\.0\\.1|localhost|\\[::1\\])$/i.test(location.hostname))
      ? location.origin
      : {_js_json(daemon_base)};
    const UI_KEY = {_js_json(ui_key)};
    const KEY_GENUI = 'luminara_browser:genui_payload';
    const KEY_HIST = 'luminara_browser:command_history';
    const KEY_SETTINGS = 'luminara_browser:settings';
    const KEY_SS = 'luminara_browser:session_tok';
    const KEY_VIEW = 'luminara_browser:telemetry_tab';
    const MAX_HISTORY = 50;
    const collator = new Intl.Collator(undefined, {{ numeric: true, sensitivity: 'base' }});
    const hadLocalGenUi = (() => {{
      try {{ return Boolean(localStorage.getItem(KEY_GENUI)); }} catch (_e) {{ return false; }}
    }})();

    const hashRaw = location.hash || '';
    const hashViewMatch = hashRaw.match(/(?:^#|&)view=([^&]+)/);
    let state = loadInitialState();
    let currentView = (() => {{
      if (hashViewMatch) return decodeURIComponent(hashViewMatch[1]);
      try {{ return localStorage.getItem(KEY_VIEW) || state.recommended_view || 'comparison'; }} catch (_e) {{ return state.recommended_view || 'comparison'; }}
    }})();
    let sortCol = null;
    let sortAsc = true;
    let searchFilter = '';
    let undoStack = [];
    let redoStack = [];
    let captureAbort = null;
    {tele_js}

    function el(tag, cls, text) {{
      const n = document.createElement(tag);
      if (cls) n.className = cls;
      if (text !== undefined) n.textContent = String(text);
      return n;
    }}

    let sessionTok = (() => {{
      const m = hashRaw.match(/(?:^#|&)lum_tok(?:en)?=([^&]+)/);
      if (m) {{
        const tok = decodeURIComponent(m[1]);
        try {{
          sessionStorage.setItem(KEY_SS, tok);
          history.replaceState(null, '', location.pathname + location.search);
        }} catch (_e) {{}}
        return tok;
      }}
      if (hashViewMatch) {{
        try {{ history.replaceState(null, '', location.pathname + location.search); }} catch (_e) {{}}
      }}
      try {{ return sessionStorage.getItem(KEY_SS) || ''; }} catch (_e) {{ return ''; }}
    }})();

    function apiHeaders(isJson) {{
      const h = {{}};
      const uiAuth = UI_KEY || sessionTok;
      if (uiAuth) h['X-Luminara-UI-Key'] = uiAuth;
      if (agentSessionTok) {{
        h['Authorization'] = 'Bearer ' + agentSessionTok;
      }} else {{
        try {{
          const s = JSON.parse(localStorage.getItem(KEY_SETTINGS) || '{{}}');
          if (s && s.passportToken) h['Authorization'] = 'Bearer ' + String(s.passportToken).trim();
        }} catch (_e) {{}}
      }}
      if (isJson) h['Content-Type'] = 'application/json';
      return h;
    }}

    let agentSessionTok = '';
    async function exchangePassportSession(forceRefresh = false) {{
      if (/^[0-9a-f]{{64}}$/i.test(sessionTok)) return;
      const hdrs = apiHeaders(true);
      if (!hdrs['X-Luminara-UI-Key'] && !hdrs['Authorization']) return;
      if (!forceRefresh && (UI_KEY || sessionTok || agentSessionTok)) return;
      try {{
        const wantScope = Boolean(hdrs['X-Luminara-UI-Key']) ? 'ui' : 'agent';
        const r = await fetch(DAEMON + '/api/agent/session-token', {{
          method: 'POST',
          headers: hdrs,
          body: JSON.stringify({{ scope: wantScope, ttl_sec: 900 }}),
          signal: AbortSignal.timeout(4000)
        }});
        if (r.ok) {{
          const d = await r.json();
          if (d && d.token && wantScope === 'ui') {{
            sessionTok = d.token;
            try {{ sessionStorage.setItem(KEY_SS, sessionTok); }} catch (_e) {{}}
          }} else if (d && d.token && wantScope === 'agent') {{
            agentSessionTok = d.token;
          }}
        }}
      }} catch (_e) {{}}
    }}

    function loadInitialState() {{
      try {{
        const raw = localStorage.getItem(KEY_GENUI);
        if (raw) return JSON.parse(raw);
      }} catch (_e) {{}}
      return {{
        title: 'Luminara Sample Benchmark Workspace',
        entity_count: 3,
        recommended_view: 'comparison',
        summary_bar: {{ metric_name: 'Latency (ms)', count: 3, min: 18, max: 64, avg: 38.0, spread_pct: 121.1 }},
        entities: [
          {{ id: 'ent_001', public_identifier: 'Luminara Browser 157 (Loopback CDP)', attributes: [
            {{ name: 'Latency (ms)', value: '18', widget: 'number', editable: true }},
            {{ name: 'Google Telemetry', value: '0 requests', widget: 'short_text', editable: true }},
            {{ name: 'Co-Browsing', value: 'Human + MCP v2 Shared Window', widget: 'short_text', editable: true }}
          ]}},
          {{ id: 'ent_002', public_identifier: 'Cloud-Wrapper Agent Browser (Baseline)', attributes: [
            {{ name: 'Latency (ms)', value: '32', widget: 'number', editable: true }},
            {{ name: 'Google Telemetry', value: 'Proprietary Cloud', widget: 'short_text', editable: true }},
            {{ name: 'Co-Browsing', value: 'Built-in Assistant Only', widget: 'short_text', editable: true }}
          ]}},
          {{ id: 'ent_003', public_identifier: 'Legacy Webview Prototype (Baseline)', attributes: [
            {{ name: 'Latency (ms)', value: '64', widget: 'number', editable: true }},
            {{ name: 'Google Telemetry', value: 'Unfiltered', widget: 'short_text', editable: true }},
            {{ name: 'Co-Browsing', value: 'None', widget: 'short_text', editable: true }}
          ]}}
        ]
      }};
    }}

    function syncViewTabs() {{
      document.querySelectorAll('[data-view]').forEach(b => {{
        const active = b.getAttribute('data-view') === currentView;
        b.classList.toggle('active', active);
        b.setAttribute('aria-selected', String(active));
      }});
    }}

    function persistState(syncRemote = false) {{
      try {{
        localStorage.setItem(KEY_GENUI, JSON.stringify(state));
        localStorage.setItem(KEY_HIST, JSON.stringify({{ undoDepth: undoStack.length, redoDepth: redoStack.length }}));
      }} catch (_e) {{}}
      document.getElementById('btnUndo').disabled = undoStack.length === 0;
      document.getElementById('btnRedo').disabled = redoStack.length === 0;
      if (syncRemote) {{
        fetch(DAEMON + '/api/agent/genui/sync', {{
          method: 'POST',
          headers: apiHeaders(true),
          body: JSON.stringify({{ generative_ui: state }})
        }}).catch(() => {{}});
      }}
    }}

    function parseMetricNum(s) {{
      const m = String(s ?? '').trim().match(/^(?:[$€£¥]|AUD|USD)?\\s*(-?\\d[\\d,]*(?:\\.\\d+)?)\\s*%?$/i);
      return m ? Number(m[1].replace(/,/g, '')) : Number.NaN;
    }}

    function recomputeSummaryBar() {{
      if (!state.summary_bar) return;
      const m = state.summary_bar.metric_name;
      const nums = [];
      (state.entities || []).forEach(e => {{
        const a = (e.attributes || []).find(x => x.name === m);
        if (a) {{
          const parsed = parseMetricNum(a.value);
          if (!Number.isNaN(parsed)) nums.push(parsed);
        }}
      }});
      if (nums.length) {{
        const minV = Math.min(...nums);
        const maxV = Math.max(...nums);
        const avg = nums.reduce((s, v) => s + v, 0) / nums.length;
        state.summary_bar.count = nums.length;
        state.summary_bar.min = Math.round(minV * 100) / 100;
        state.summary_bar.max = Math.round(maxV * 100) / 100;
        state.summary_bar.avg = Math.round(avg * 100) / 100;
        state.summary_bar.spread_pct = avg ? Math.round(((maxV - minV) / avg) * 1000) / 10 : 0.0;
      }}
    }}

    function executeEdit(entId, attrName, newVal) {{
      const ent = state.entities.find(e => e.id === entId);
      if (!ent) return;
      const attr = ent.attributes.find(a => a.name === attrName);
      if (!attr || String(attr.value) === String(newVal)) return;
      const prevVal = attr.value;
      undoStack.push({{ entId, attrName, prevVal, newVal }});
      if (undoStack.length > MAX_HISTORY) undoStack.shift();
      redoStack = [];
      attr.value = newVal;
      state.updated_at = Date.now();
      recomputeSummaryBar();
      persistState(true);
      render();
    }}

    function undo() {{
      const cmd = undoStack.pop();
      if (!cmd) return;
      redoStack.push(cmd);
      const ent = state.entities.find(e => e.id === cmd.entId);
      if (ent) {{
        const attr = ent.attributes.find(a => a.name === cmd.attrName);
        if (attr) attr.value = cmd.prevVal;
      }}
      state.updated_at = Date.now();
      recomputeSummaryBar();
      persistState(true);
      render();
    }}

    function redo() {{
      const cmd = redoStack.pop();
      if (!cmd) return;
      undoStack.push(cmd);
      const ent = state.entities.find(e => e.id === cmd.entId);
      if (ent) {{
        const attr = ent.attributes.find(a => a.name === cmd.attrName);
        if (attr) attr.value = cmd.newVal;
      }}
      state.updated_at = Date.now();
      recomputeSummaryBar();
      persistState(true);
      render();
    }}

    function allColumns() {{
      return Array.from(new Set((state.entities || []).flatMap(e => (e.attributes || []).filter(a => a.widget !== 'meta').map(a => a.name))));
    }}

    function getVisibleEntities() {{
      const allEntities = state.entities || [];
      const needle = searchFilter.trim().toLowerCase();
      const filtered = needle
        ? allEntities.filter(e => String(e.public_identifier || '').toLowerCase().includes(needle)
            || (e.attributes || []).some(a => String(a.value ?? '').toLowerCase().includes(needle) || String(a.name || '').toLowerCase().includes(needle)))
        : [...allEntities];
      if (sortCol) {{
        const valOf = e => sortCol === '__entity'
          ? (e.public_identifier ?? '')
          : ((e.attributes || []).find(a => a.name === sortCol)?.value ?? '');
        filtered.sort((a, b) => {{
          const sa = String(valOf(a));
          const sbVal = String(valOf(b));
          const na = parseMetricNum(sa);
          const nb = parseMetricNum(sbVal);
          const cmp = (!Number.isNaN(na) && !Number.isNaN(nb)) ? (na - nb) : collator.compare(sa, sbVal);
          return (sortAsc ? 1 : -1) * cmp;
        }});
      }}
      return filtered;
    }}

    function render() {{
      syncViewTabs();
      try {{ localStorage.setItem(KEY_VIEW, currentView); }} catch (_e) {{}}
      const entGroup = document.getElementById('entityToolsGroup');
      if (entGroup) entGroup.style.display = currentView === 'telemetry' ? 'none' : 'flex';
      document.getElementById('wsTitle').textContent = currentView === 'telemetry' ? 'REA Security & Evaluation Cockpit' : (state.title || 'Generative UI Workspace');
      const allEntities = state.entities || [];
      const entities = getVisibleEntities();
      const kpi = document.getElementById('kpiBar');
      kpi.replaceChildren();

      const root = document.getElementById('viewContainer');
      root.replaceChildren();

      if (currentView === 'telemetry') {{
        const seqSnap = (teleSnapshot && teleSnapshot.seq) || {{}};
        const vrtSnap = (teleSnapshot && teleSnapshot.vrt) || {{}};
        const monCount = ((teleSnapshot && teleSnapshot.monitors) || []).length;
        const teleKpis = [
          ['Active Chain Blocks', teleSnapshot ? ((seqSnap.active_blocks || []).length) : '—'],
          ['Fenced Monitors', teleSnapshot ? monCount : '—'],
          ['VRT Baselines', teleSnapshot ? ((vrtSnap.baselines || []).length) : '—'],
          ['Blocked Egress', teleSnapshot ? (vrtSnap.blocked_egress_count || 0) : '—']
        ];
        teleKpis.forEach(([label, val]) => {{
          const d = el('div', 'kpi-card');
          d.append(el('div', 'kpi-label', label), el('div', 'kpi-val', val));
          kpi.appendChild(d);
        }});
        renderTelemetryInto(root);
        if (!teleSnapshot && !teleLoading && !teleError) fetchTelemetryBundle(false);
        return;
      }}

      const sb = state.summary_bar;
      let kpis = [['Entities', entities.length]];
      if (sb) {{
        const m = sb.metric_name;
        const vNums = entities.map(e => parseMetricNum((e.attributes || []).find(x => x.name === m)?.value)).filter(n => !Number.isNaN(n));
        if (vNums.length) {{
          const minV = Math.round(Math.min(...vNums) * 100) / 100;
          const maxV = Math.round(Math.max(...vNums) * 100) / 100;
          const avgV = Math.round((vNums.reduce((s, v) => s + v, 0) / vNums.length) * 100) / 100;
          kpis = [['Entities', entities.length], [m + ' (Min)', minV], [m + ' (Avg)', avgV], [m + ' (Max)', maxV]];
        }} else {{
          kpis = [['Entities', entities.length], [m + ' (Min)', sb.min], [m + ' (Avg)', sb.avg], [m + ' (Max)', sb.max]];
        }}
      }}
      kpis.forEach(([label, val]) => {{
        const d = el('div', 'kpi-card');
        d.append(el('div', 'kpi-label', label), el('div', 'kpi-val', val));
        kpi.appendChild(d);
      }});

      if (!allEntities.length) {{
        const empty = el('div', 'ent-card');
        empty.append(
          el('div', 'ent-title', 'No entities in workspace yet'),
          el('div', 'status-line', 'Click "Capture Live Tab" above or run a Bulk Extract from the Command Deck.')
        );
        root.appendChild(empty);
        return;
      }}
      if (!entities.length) {{
        const noMatch = el('div', 'ent-card');
        noMatch.append(
          el('div', 'ent-title', 'No matching entities'),
          el('div', 'status-line', 'Clear or refine the search filter above to view all ' + allEntities.length + ' workspace entities.')
        );
        root.appendChild(noMatch);
        return;
      }}

      if (currentView === 'table') {{
        const cols = allColumns();
        const wrap = el('div', 'table-wrap');
        const tbl = document.createElement('table');
        const thead = document.createElement('thead');
        const headTr = document.createElement('tr');

        ['__entity', ...cols].forEach(colKey => {{
          const th = document.createElement('th');
          const active = sortCol === colKey;
          th.setAttribute('aria-sort', active ? (sortAsc ? 'ascending' : 'descending') : 'none');
          const btn = el('button', 'th-sort');
          btn.type = 'button';
          const lbl = colKey === '__entity' ? 'Entity' : colKey;
          btn.append(el('span', '', lbl), el('span', '', active ? (sortAsc ? '▲' : '▼') : '⇅'));
          btn.onclick = () => {{
            sortAsc = active ? !sortAsc : true;
            sortCol = colKey;
            render();
          }};
          th.appendChild(btn);
          headTr.appendChild(th);
        }});
        thead.appendChild(headTr);

        const tbody = document.createElement('tbody');
        entities.forEach(e => {{
          const tr = document.createElement('tr');
          const map = Object.fromEntries((e.attributes || []).map(a => [a.name, a]));
          const tdEnt = document.createElement('td');
          tdEnt.appendChild(el('strong', '', e.public_identifier ?? ''));
          tr.appendChild(tdEnt);
          cols.forEach(c => {{
            const td = document.createElement('td');
            const attrObj = map[c];
            if (attrObj && attrObj.editable !== false) {{
              const inp = el('input', 'attr-val');
              inp.type = 'text';
              inp.value = String(attrObj.value ?? '');
              inp.setAttribute('aria-label', (e.public_identifier || e.id) + ' ' + c);
              inp.onchange = () => executeEdit(e.id, c, inp.value);
              td.appendChild(inp);
            }} else {{
              td.textContent = String(attrObj ? (attrObj.value ?? '') : '');
            }}
            tr.appendChild(td);
          }});
          tbody.appendChild(tr);
        }});
        tbl.append(thead, tbody);
        wrap.appendChild(tbl);
        root.appendChild(wrap);
        return;
      }}

      const grid = el('div', 'grid-cards');
      if (currentView === 'stack') grid.style.gridTemplateColumns = '1fr';

      entities.forEach(ent => {{
        const card = el('article', 'ent-card');
        card.appendChild(el('div', 'ent-title', ent.public_identifier || ent.id));

        (ent.attributes || []).filter(a => a.widget !== 'meta').forEach((attr, idx) => {{
          const row = el('div', 'attr-row');
          const inputId = `attr_${{ent.id}}_${{idx}}`;
          const lbl = el('label', '', attr.name);
          lbl.setAttribute('for', inputId);
          lbl.style.color = 'var(--ink-2)';
          const inp = el('input', 'attr-val');
          inp.id = inputId;
          inp.type = 'text';
          if (attr.widget === 'number' || attr.widget === 'currency' || attr.widget === 'percentage') {{
            inp.setAttribute('inputmode', 'decimal');
          }}
          if (attr.editable === false) inp.readOnly = true;
          inp.value = attr.value ?? '';
          inp.onchange = () => executeEdit(ent.id, attr.name, inp.value);
          row.append(lbl, inp);
          card.appendChild(row);
        }});
        grid.appendChild(card);
      }});
      root.appendChild(grid);
    }}

    const tabBtns = Array.from(document.querySelectorAll('[data-view]'));
    tabBtns.forEach((btn, idx) => {{
      btn.addEventListener('click', () => {{
        currentView = btn.getAttribute('data-view');
        render();
      }});
      btn.addEventListener('keydown', e => {{
        if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
        e.preventDefault();
        const nextIdx = (idx + (e.key === 'ArrowRight' ? 1 : tabBtns.length - 1)) % tabBtns.length;
        tabBtns[nextIdx].focus();
        tabBtns[nextIdx].click();
      }});
    }});

    document.getElementById('btnUndo').onclick = undo;
    document.getElementById('btnRedo').onclick = redo;
    window.addEventListener('keydown', e => {{
      if (e.target && e.target.matches && e.target.matches('input, textarea, select')) return;
      if (!(e.ctrlKey || e.metaKey)) return;
      const k = (e.key || '').toLowerCase();
      if (k === 'z' && !e.shiftKey) {{ e.preventDefault(); undo(); }}
      else if (k === 'y' || (k === 'z' && e.shiftKey)) {{ e.preventDefault(); redo(); }}
    }});

    document.getElementById('btnCaptureActive').onclick = async () => {{
      const btn = document.getElementById('btnCaptureActive');
      const stEl = document.getElementById('wsStatus');
      if (captureAbort) {{
        captureAbort.abort();
        captureAbort = null;
        return;
      }}
      const ctrl = new AbortController();
      captureAbort = ctrl;
      btn.textContent = 'STOP ■';
      stEl.classList.remove('err');
      stEl.textContent = 'Capturing structured entities from live browser tab...';
      try {{
        await exchangePassportSession();
        const r = await fetch(DAEMON + '/api/agent/genui', {{
          method: 'POST',
          headers: apiHeaders(true),
          body: '{{}}',
          signal: ctrl.signal
        }});
        if (r.status === 401) document.getElementById('wsAuthBar').classList.add('visible');
        const d = await r.json().catch(() => ({{}}));
        if (!r.ok) throw new Error(d.error || ('HTTP ' + r.status));
        if (d.generative_ui) {{
          state = d.generative_ui;
          currentView = state.recommended_view || 'comparison';
          undoStack = []; redoStack = [];
          persistState();
          render();
          stEl.textContent = `Captured ${{state.entity_count}} entities (${{d.receipt ? d.receipt.receipt_id : 'OK'}}).`;
        }}
      }} catch (err) {{
        if (err && err.name === 'AbortError') {{
          stEl.textContent = 'Capture cancelled by user.';
        }} else {{
          stEl.classList.add('err');
          stEl.textContent = 'Capture failed: ' + (err.message || String(err)) + ' — Ensure Luminara Browser + Agent Daemon are running and retry.';
        }}
      }} finally {{
        if (captureAbort === ctrl) captureAbort = null;
        btn.disabled = false;
        btn.textContent = 'Capture Live Tab';
      }}
    }};

    async function hydrateFromDaemon(force = false) {{
      try {{
        await exchangePassportSession();
        const r = await fetch(DAEMON + '/api/agent/genui/latest', {{
          headers: apiHeaders(false),
          signal: AbortSignal.timeout(2200)
        }});
        if (r.status === 401) {{
          document.getElementById('wsAuthBar').classList.add('visible');
          return;
        }}
        if (r.ok) {{
          document.getElementById('wsAuthBar').classList.remove('visible');
          const d = await r.json();
          const remote = d.generative_ui;
          const localTs = Math.max(Number(state.generated_at || 0), Number(state.updated_at || 0));
          const remoteTs = Math.max(Number((remote && remote.generated_at) || 0), Number((remote && remote.updated_at) || 0));
          if (remote && remote.entities && remote.entities.length && (force || !hadLocalGenUi || remoteTs > localTs)) {{
            state = remote;
            if (currentView !== 'telemetry') {{
              currentView = state.recommended_view || currentView;
            }}
            persistState();
            render();
          }}
        }}
      }} catch (_e) {{}}
    }}

    document.getElementById('wsAuthBar').addEventListener('submit', async e => {{
      e.preventDefault();
      const val = document.getElementById('wsPassportInput').value.trim();
      if (!val) return;
      if (/^[0-9a-f]{{64}}$/i.test(val) || val.startsWith('lum2.ui.')) {{
        sessionTok = val;
        try {{ sessionStorage.setItem(KEY_SS, val); }} catch (_e) {{}}
      }} else {{
        agentSessionTok = '';
        try {{
          const cur = JSON.parse(localStorage.getItem(KEY_SETTINGS) || '{{}}');
          cur.passportToken = val;
          localStorage.setItem(KEY_SETTINGS, JSON.stringify(cur));
        }} catch (_e) {{}}
        await exchangePassportSession(true);
      }}
      document.getElementById('wsPassportInput').value = '';
      if (currentView === 'telemetry') await fetchTelemetryBundle(false);
      else await hydrateFromDaemon(true);
    }});

    document.querySelectorAll('[data-dl]').forEach(btn => {{
      btn.addEventListener('click', () => {{
        const fmt = btn.getAttribute('data-dl');
        const cols = ['entity', ...allColumns()];
        const visible = getVisibleEntities();
        const rows = visible.map(e => Object.fromEntries([
          ['entity', e.public_identifier ?? ''],
          ...(e.attributes || []).filter(a => a.widget !== 'meta').map(a => [a.name, a.value ?? ''])
        ]));
        const csvCell = v => {{
          let s = String(v ?? '');
          if (/^[=+\\-@\\t\\r]/.test(s)) s = "'" + s;
          return /[",\\r\\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
        }};
        const mdCell = v => String(v ?? '').replace(/\\|/g, '\\\\|').replace(/\\r?\\n/g, ' ');

        let content = '';
        let mime = 'text/plain;charset=utf-8';
        if (fmt === 'json') {{
          content = JSON.stringify(rows, null, 2);
          mime = 'application/json;charset=utf-8';
        }} else if (fmt === 'csv') {{
          content = '\\uFEFF' + [cols.map(csvCell).join(','), ...rows.map(r => cols.map(c => csvCell(r[c])).join(','))].join('\\r\\n');
          mime = 'text/csv;charset=utf-8';
        }} else {{
          content = [
            '| ' + cols.map(mdCell).join(' | ') + ' |',
            '| ' + cols.map(() => '---').join(' | ') + ' |',
            ...rows.map(r => '| ' + cols.map(c => mdCell(r[c])).join(' | ') + ' |')
          ].join('\\n');
          mime = 'text/markdown;charset=utf-8';
        }}
        const blob = new Blob([content], {{ type: mime }});
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `luminara-workspace.${{fmt}}`;
        a.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      }});
    }});

    const wsSearchEl = document.getElementById('wsSearch');
    if (wsSearchEl) {{
      wsSearchEl.addEventListener('input', () => {{
        searchFilter = wsSearchEl.value || '';
        render();
      }});
    }}

    persistState();
    render();
    hydrateFromDaemon(false);
    {palette_iife}
  </script>
</body>
</html>
"""


__all__ = [
    "build_luminara_workspace_html",
    "make_solid_emerald_png",
    "write_copilot_extension",
]
