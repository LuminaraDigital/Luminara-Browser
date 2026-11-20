"""Clean-room Generative UI Workspace & MV3 SidePanel Copilot Generator (`forge/luminara_workspace_ui.py`).

Production upgrades:
- Zero dynamic `.innerHTML` (full DOM XSS immunity across `SummaryBar` KPIs and `TableView`).
- Real interactive column sorting (`aria-sort` + natural numeric `Intl.Collator`) in `Sortable Table`.
- RFC 4180 CSV quoting + UTF-8 BOM (`\\uFEFF`) + formula-injection guard + pipe-safe Markdown + `URL.revokeObjectURL`.
- Input-safe `Ctrl+Z` / `Ctrl+Shift+Z` / `Ctrl+Y` 50-slot `CommandHistory`.
- Automatic hydration from `GET /api/agent/genui/latest` so Copilot `Page -> GenUI` (`http://127.0.0.1:8796/workspace`)
  opens populated with zero cross-origin `localStorage` loss!
- MV3 `luminara-copilot` includes generated PNG icons (`16`/`48`/`128`), explicit CSP, top-level + `onStartup`
  `sidePanel.setPanelBehavior`, and `runAction` error/loading states.
"""

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


def build_luminara_workspace_html(
    profile: ForkProfile,
    newtab_uri: str = "./newtab.html",
    agent_port: int = 8796,
    ui_key: str = "",
) -> str:
    """Clean-room Generative UI Studio (`SummaryBar`, `ComparisonView`, `Sortable Table`, `StackView`, 50-slot Undo/Redo)."""
    brand_esc = html.escape(profile.brand_name)
    daemon_base = f"http://127.0.0.1:{agent_port}"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="color-scheme" content="dark light" />
  <title>{brand_esc} — Generative UI Workspace</title>
  <style>
    :root {{
      color-scheme: dark light;
      --bg-0: light-dark(oklch(0.975 0.005 255), oklch(0.115 0.012 255));
      --bg-1: light-dark(oklch(0.95 0.007 255), oklch(0.15 0.013 255));
      --bg-2: light-dark(oklch(0.915 0.009 255), oklch(0.19 0.015 255));
      --ink-0: light-dark(oklch(0.15 0.015 255), oklch(0.965 0.005 255));
      --ink-1: light-dark(oklch(0.34 0.015 255), oklch(0.78 0.012 255));
      --ink-2: light-dark(oklch(0.44 0.015 255), oklch(0.67 0.012 255));
      --accent: light-dark(oklch(0.48 0.15 162), oklch(0.75 0.16 162));
      --danger: light-dark(oklch(0.50 0.19 26), oklch(0.68 0.18 25));
      --hairline: light-dark(oklch(0.15 0.01 255 / 0.12), oklch(1 0 0 / 0.09));
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
    header, .toolbar, .kpi-bar, .status-line, main {{ max-width: 1280px; width: 100%; margin: 0 auto; min-width: 0; }}
    header {{ display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; }}
    .toolbar {{
      background: var(--bg-1); border: 1px solid var(--hairline); box-shadow: var(--specular);
      border-radius: 16px; padding: 12px; display: flex; justify-content: space-between; flex-wrap: wrap; gap: 10px;
    }}
    .btn {{
      min-height: 32px;
      padding: 8px 13px; border-radius: 10px; border: 1px solid var(--hairline);
      background: var(--bg-2); color: var(--ink-0); font-family: var(--font-mono);
      font-size: 11px; cursor: pointer; text-decoration: none; display: inline-flex; align-items: center;
    }}
    .btn.active {{ border-color: var(--accent); color: var(--accent); }}
    .btn:disabled {{ opacity: 0.45; cursor: not-allowed; }}
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
      flex: 1 1 90px; min-width: 0;
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
    @media (prefers-reduced-motion: reduce) {{
      *, *::before, *::after {{ transition: none !important; animation: none !important; }}
    }}
  </style>
</head>
<body>
  <header>
    <div>
      <div style="font-family:var(--font-mono);font-size:11px;color:var(--accent);letter-spacing:0.1em;">GENERATIVE UI WORKSPACE · 50-SLOT COMMAND HISTORY</div>
      <h1 id="wsTitle" style="font-size:clamp(1.35rem,2.4vw,1.75rem);letter-spacing:-0.03em;">Extracted Entity Studio</h1>
    </div>
    <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
      <a class="btn" href="{html.escape(newtab_uri)}">← Command Deck</a>
      <button class="btn" type="button" id="btnCaptureActive">Capture Live Tab</button>
    </div>
  </header>

  <div class="toolbar">
    <div style="display:flex;gap:6px;flex-wrap:wrap;" role="tablist" aria-label="Workspace Layout Mode">
      <button class="btn active" type="button" role="tab" aria-selected="true" data-view="comparison">Comparison Cards</button>
      <button class="btn" type="button" role="tab" aria-selected="false" data-view="table">Sortable Table</button>
      <button class="btn" type="button" role="tab" aria-selected="false" data-view="stack">Stack Inspector</button>
    </div>
    <div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center;">
      <input class="attr-val" id="wsSearch" type="search" placeholder="Filter entities..." aria-label="Filter workspace entities" style="width:170px;" />
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
    const DAEMON = {_js_json(daemon_base)};
    const UI_KEY = {_js_json(ui_key)};
    const KEY_GENUI = 'luminara_browser:genui_payload';
    const KEY_HIST = 'luminara_browser:command_history';
    const MAX_HISTORY = 50;
    const collator = new Intl.Collator(undefined, {{ numeric: true, sensitivity: 'base' }});

    let state = loadInitialState();
    let currentView = state.recommended_view || 'comparison';
    let sortCol = null;
    let sortAsc = true;
    let searchFilter = '';
    let undoStack = [];
    let redoStack = [];

    function el(tag, cls, text) {{
      const n = document.createElement(tag);
      if (cls) n.className = cls;
      if (text !== undefined) n.textContent = String(text);
      return n;
    }}

    const SESSION_TOK = (() => {{
      const KEY_SS = 'luminara_browser:session_tok';
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

    function apiHeaders(isJson) {{
      const h = {{}};
      const uiAuth = UI_KEY || SESSION_TOK;
      if (uiAuth) h['X-Luminara-UI-Key'] = uiAuth;
      try {{
        const s = JSON.parse(localStorage.getItem('luminara_browser:settings') || '{{}}');
        if (s && s.passportToken) h['Authorization'] = 'Bearer ' + String(s.passportToken).trim();
      }} catch (_e) {{}}
      if (isJson) h['Content-Type'] = 'application/json';
      return h;
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

    function persistState() {{
      localStorage.setItem(KEY_GENUI, JSON.stringify(state));
      localStorage.setItem(KEY_HIST, JSON.stringify({{ undoDepth: undoStack.length, redoDepth: redoStack.length }}));
      document.getElementById('btnUndo').disabled = undoStack.length === 0;
      document.getElementById('btnRedo').disabled = redoStack.length === 0;
    }}

    function parseMetricNum(s) {{
      const m = String(s ?? '').trim().match(/^(?:[$€£¥]|AUD|USD)?\\s*(-?\\d[\\d,]*(?:\\.\\d+)?)\\s*%?$/i);
      return m ? Number(m[1].replace(/,/g, '')) : Number.NaN;
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
      persistState();
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
      persistState();
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
      persistState();
      render();
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

    function allColumns() {{
      return Array.from(new Set((state.entities || []).flatMap(e => (e.attributes || []).filter(a => a.widget !== 'meta').map(a => a.name))));
    }}

    function render() {{
      syncViewTabs();
      document.getElementById('wsTitle').textContent = state.title || 'Generative UI Workspace';
      const allEntities = state.entities || [];
      const needle = searchFilter.trim().toLowerCase();
      const entities = needle
        ? allEntities.filter(e => String(e.public_identifier || '').toLowerCase().includes(needle)
            || (e.attributes || []).some(a => String(a.value ?? '').toLowerCase().includes(needle) || String(a.name || '').toLowerCase().includes(needle)))
        : allEntities;
      const kpi = document.getElementById('kpiBar');
      kpi.replaceChildren();
      const sb = state.summary_bar;
      const kpis = sb ? [
        ['Entities', entities.length],
        [sb.metric_name + ' (Min)', sb.min],
        [sb.metric_name + ' (Avg)', sb.avg],
        [sb.metric_name + ' (Max)', sb.max]
      ] : [['Entities', entities.length]];
      kpis.forEach(([label, val]) => {{
        const d = el('div', 'kpi-card');
        d.append(el('div', 'kpi-label', label), el('div', 'kpi-val', val));
        kpi.appendChild(d);
      }});

      const root = document.getElementById('viewContainer');
      root.replaceChildren();

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

        const sorted = [...entities];
        if (sortCol) {{
          const valOf = e => sortCol === '__entity'
            ? (e.public_identifier ?? '')
            : ((e.attributes || []).find(a => a.name === sortCol)?.value ?? '');
          sorted.sort((a, b) => {{
            const sa = String(valOf(a));
            const sbVal = String(valOf(b));
            const na = parseMetricNum(sa);
            const nb = parseMetricNum(sbVal);
            const cmp = (!Number.isNaN(na) && !Number.isNaN(nb)) ? (na - nb) : collator.compare(sa, sbVal);
            return (sortAsc ? 1 : -1) * cmp;
          }});
        }}

        const tbody = document.createElement('tbody');
        sorted.forEach(e => {{
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

    document.querySelectorAll('[data-view]').forEach(btn => {{
      btn.addEventListener('click', () => {{
        currentView = btn.getAttribute('data-view');
        render();
      }});
    }});

    document.getElementById('btnUndo').onclick = undo;
    document.getElementById('btnRedo').onclick = redo;
    window.addEventListener('keydown', e => {{
      if (e.target && e.target.matches && e.target.matches('input, textarea, select')) return;
      if (!(e.ctrlKey || e.metaKey)) return;
      const k = e.key.toLowerCase();
      if (k === 'z' && !e.shiftKey) {{ e.preventDefault(); undo(); }}
      else if (k === 'y' || (k === 'z' && e.shiftKey)) {{ e.preventDefault(); redo(); }}
    }});

    document.getElementById('btnCaptureActive').onclick = async () => {{
      const btn = document.getElementById('btnCaptureActive');
      const stEl = document.getElementById('wsStatus');
      btn.disabled = true;
      btn.textContent = 'Capturing...';
      stEl.classList.remove('err');
      stEl.textContent = 'Capturing structured entities from live browser tab...';
      try {{
        const r = await fetch(DAEMON + '/api/agent/genui', {{
          method: 'POST',
          headers: apiHeaders(true),
          body: '{{}}',
          signal: AbortSignal.timeout(12000)
        }});
        const d = await r.json().catch(() => ({{}}));
        if (!r.ok) throw new Error(d.error || ('HTTP ' + r.status));
        if (d.generative_ui) {{
          state = d.generative_ui;
          currentView = state.recommended_view || currentView;
          undoStack = []; redoStack = [];
          persistState();
          render();
          stEl.textContent = `Captured ${{state.entity_count}} entities (${{d.receipt ? d.receipt.receipt_id : 'OK'}}).`;
        }}
      }} catch (err) {{
        stEl.classList.add('err');
        stEl.textContent = 'Capture failed: ' + (err.message || String(err)) + ' — Ensure Luminara Browser + Agent Daemon are running and retry.';
      }} finally {{
        btn.disabled = false;
        btn.textContent = 'Capture Live Tab';
      }}
    }};

    // Hydrate automatically from Agent Daemon only when a newer GenUI snapshot exists (supports Copilot SidePanel -> Workspace without overwriting user edits!)
    (async () => {{
      try {{
        const r = await fetch(DAEMON + '/api/agent/genui/latest', {{
          headers: apiHeaders(false),
          signal: AbortSignal.timeout(1800)
        }});
        if (r.ok) {{
          const d = await r.json();
          const remote = d.generative_ui;
          const localTs = Math.max(Number(state.generated_at || 0), Number(state.updated_at || 0));
          const remoteTs = Number((remote && remote.generated_at) || 0);
          if (remote && remote.entities && remote.entities.length && (remoteTs > localTs || !localStorage.getItem(KEY_GENUI))) {{
            state = remote;
            currentView = state.recommended_view || currentView;
            persistState();
            render();
          }}
        }}
      }} catch (_e) {{}}
    }})();

    document.querySelectorAll('[data-dl]').forEach(btn => {{
      btn.addEventListener('click', () => {{
        const fmt = btn.getAttribute('data-dl');
        const cols = ['entity', ...allColumns()];
        const rows = (state.entities || []).map(e => Object.fromEntries([
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
  </script>
</body>
</html>
"""


def write_copilot_extension(
    ext_dir: Path,
    profile: ForkProfile,
    workspace_uri: str = "",
    agent_port: int = 8796,
    ui_key: str = "",
) -> None:
    """Write the built-in MV3 `luminara-copilot` Chrome Side Panel co-browsing extension."""
    ext_dir.mkdir(parents=True, exist_ok=True)
    if not ui_key:
        for anc in ext_dir.resolve().parents:
            if (anc / "forge" / "__init__.py").exists() or (anc / "outputs").exists():
                try:
                    from .http_base import ensure_local_ui_key

                    ui_key = ensure_local_ui_key(anc)
                except Exception:  # noqa: BLE001
                    pass
                break
    icons_dir = ext_dir / "icons"
    icons_dir.mkdir(parents=True, exist_ok=True)
    for px in (16, 48, 128):
        (icons_dir / f"icon{px}.png").write_bytes(make_solid_emerald_png(px))

    daemon_base = f"http://127.0.0.1:{agent_port}"
    resolved_ws_url = workspace_uri if workspace_uri.startswith("http") else f"{daemon_base}/workspace"

    manifest = {
        "manifest_version": 3,
        "name": f"{profile.brand_name} Agent Copilot",
        "version": "3.0.0",
        "description": "Simultaneous Human + AI Co-Browsing Side Panel: Set-of-Marks DOM HUD, Dialog Supervisor, Generative UI, and Human Takeover.",
        "permissions": ["sidePanel", "tabs", "activeTab", "storage"],
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
  <title>{html.escape(profile.brand_name)} Copilot</title>
  <style>
    :root {{
      color-scheme: dark light;
      --bg-0: light-dark(oklch(0.985 0.004 255), oklch(0.12 0.01 255));
      --bg-1: light-dark(oklch(0.96 0.006 255), oklch(0.16 0.012 255));
      --bg-2: light-dark(oklch(0.93 0.008 255), oklch(0.19 0.015 255));
      --ink-0: light-dark(oklch(0.16 0.015 255), oklch(0.96 0.005 255));
      --ink-1: light-dark(oklch(0.35 0.018 255), oklch(0.84 0.012 255));
      --hairline: light-dark(oklch(0.18 0.015 255 / 0.14), oklch(1 0 0 / 0.12));
      --accent: light-dark(oklch(0.47 0.14 162), oklch(0.75 0.16 162));
      --warn: light-dark(oklch(0.52 0.15 65), oklch(0.82 0.14 75));
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
      border-radius: 12px; padding: 12px; display: grid; gap: 8px; min-width: 0;
    }}
    .kicker {{ font: 600 10px/1.2 Consolas, monospace; letter-spacing: 0.09em; text-transform: uppercase; color: var(--accent); }}
    button {{
      min-height: 32px;
      padding: 8px 10px; border-radius: 8px; border: 1px solid var(--hairline);
      background: var(--bg-2); color: var(--ink-0); font: 600 11px Consolas, monospace; cursor: pointer;
    }}
    button:disabled {{ opacity: 0.5; cursor: wait; }}
    button.primary {{ border-color: color-mix(in oklch, var(--accent) 55%, transparent); background: color-mix(in oklch, var(--accent) 16%, transparent); }}
    button.warn {{ border-color: color-mix(in oklch, var(--warn) 55%, transparent); color: var(--warn); }}
    textarea {{
      width: 100%; background: var(--bg-0);
      border: 1px solid var(--hairline); border-radius: 8px; color: var(--ink-0); padding: 8px; font-size: 12px;
    }}
    pre {{
      margin: 0; max-height: 220px; overflow: auto; background: var(--bg-0);
      padding: 8px; border-radius: 8px; font: 11px/1.35 Consolas, monospace; color: var(--ink-1); white-space: pre-wrap; overflow-wrap: anywhere;
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
      <button id="btnVerifyLedger" type="button">Verify Ledger</button>
      <button id="btnAcceptDlg" type="button">Accept Dialog</button>
      <button id="btnDismissDlg" type="button">Dismiss Dialog</button>
      <button id="btnClear" type="button">Clear HUD</button>
      <button id="btnTakeover" type="button" class="warn">Human Takeover</button>
      <button id="btnResumeHandoff" type="button" class="warn" style="display:none;">Resume Handoff ↻</button>
    </div>
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

async function openAuthenticatedWorkspace() {{
  let targetUrl = WORKSPACE_URL;
  try {{
    const tokRes = await callDaemon('/api/agent/session-token', {{ scope: 'ui', ttl_sec: 900 }});
    if (tokRes && tokRes.token) targetUrl = WORKSPACE_URL + '#lum_tok=' + encodeURIComponent(tokRes.token);
  }} catch (_e) {{}}
  if (chrome.tabs) chrome.tabs.create({{ url: targetUrl }});
}}

async function ping() {{
  try {{
    const st = await callDaemon('/api/agent/status', undefined, 2500);
    connEl.textContent = `Daemon LIVE · ${{st.open_tabs}} shared tab(s) · CDP ${{st.cdp_connected ? 'OK' : 'wait'}}`;
    const handoffs = st.active_handoffs || [];
    pendingHandoffRunId = handoffs.length ? handoffs[0].run_id : null;
    const btnRes = document.getElementById('btnResumeHandoff');
    if (btnRes) btnRes.style.display = pendingHandoffRunId ? 'inline-block' : 'none';
  }} catch (_e) {{
    connEl.textContent = 'Daemon offline — launch via Launch-' + SLUG + '.cmd';
  }}
}}

const btnSnap = document.getElementById('btnSnap');
btnSnap.onclick = () => runAction(btnSnap, 'Indexing...', async () => {{
  const res = await callDaemon('/api/agent/snapshot', {{ show_badges: true, include_frames: true, agent_id: 'sidepanel-copilot' }});
  logEl.textContent = JSON.stringify(res, null, 2);
}});

const btnRefreshTabs = document.getElementById('btnRefreshTabs');
btnRefreshTabs.onclick = () => runAction(btnRefreshTabs, 'Refreshing...', async () => {{
  const res = await callDaemon('/api/agent/tabs');
  logEl.textContent = JSON.stringify(res, null, 2);
}});

const btnExtractMd = document.getElementById('btnExtractMd');
btnExtractMd.onclick = () => runAction(btnExtractMd, 'Extracting...', async () => {{
  const res = await callDaemon('/api/agent/extract', {{ format: 'md' }});
  logEl.textContent = res.formatted || JSON.stringify(res, null, 2);
}});

const btnOpenWs = document.getElementById('btnOpenWs');
btnOpenWs.onclick = () => runAction(btnOpenWs, 'Opening...', async () => {{
  await openAuthenticatedWorkspace();
}});

const btnVerifyLedger = document.getElementById('btnVerifyLedger');
btnVerifyLedger.onclick = () => runAction(btnVerifyLedger, 'Verifying...', async () => {{
  const res = await callDaemon('/api/agent/ledger/verify');
  logEl.textContent = JSON.stringify(res, null, 2);
}});

const btnAcceptDlg = document.getElementById('btnAcceptDlg');
btnAcceptDlg.onclick = () => runAction(btnAcceptDlg, 'Accepting...', async () => {{
  const res = await callDaemon('/api/agent/dialog', {{ action: 'accept', agent_id: 'sidepanel-copilot' }});
  logEl.textContent = JSON.stringify(res, null, 2);
}});

const btnDismissDlg = document.getElementById('btnDismissDlg');
btnDismissDlg.onclick = () => runAction(btnDismissDlg, 'Dismissing...', async () => {{
  const res = await callDaemon('/api/agent/dialog', {{ action: 'dismiss', agent_id: 'sidepanel-copilot' }});
  logEl.textContent = JSON.stringify(res, null, 2);
}});

const btnClear = document.getElementById('btnClear');
btnClear.onclick = () => runAction(btnClear, 'Clearing...', async () => {{
  const res = await callDaemon('/api/agent/act', {{ action: 'clear_hud' }});
  logEl.textContent = JSON.stringify(res, null, 2);
}});

const btnTakeover = document.getElementById('btnTakeover');
btnTakeover.onclick = () => runAction(btnTakeover, 'Preempting...', async () => {{
  const res = await callDaemon('/api/agent/act', {{ action: 'human_takeover' }});
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
  const res = await callDaemon('/api/agent/genui', {{}});
  logEl.textContent = `Synthesized ${{res.generative_ui ? res.generative_ui.entity_count : 0}} entities.\\nReceipt: ${{res.receipt ? res.receipt.receipt_id : ''}}`;
  await openAuthenticatedWorkspace();
}});

const btnRunGoal = document.getElementById('btnRunGoal');
let activeGoalAbort = null;
btnRunGoal.onclick = async () => {{
  if (activeGoalAbort) {{
    activeGoalAbort.abort();
    activeGoalAbort = null;
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
  activeGoalAbort = new AbortController();
  btnRunGoal.textContent = 'STOP ■';
  logEl.textContent = 'Executing perceive -> decide -> act...';
  try {{
    const res = await callDaemon('/api/agent/goal', {{ goal, agent_id: 'sidepanel-copilot' }}, 35000, activeGoalAbort.signal);
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
    activeGoalAbort = null;
    btnRunGoal.textContent = orig;
  }}
}};

ping();
setInterval(ping, 4000);
"""
    (ext_dir / "sidepanel.js").write_text(sidepanel_js, encoding=ENCODING, newline="\n")
