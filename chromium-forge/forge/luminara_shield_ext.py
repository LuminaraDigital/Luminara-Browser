"""MV3 Privacy Shield v3 Extension Generator (`forge/luminara_shield_ext.py`).

Decomposed from `portable.py` to keep both modules concise and strictly under the 1,000-line ceiling:
- Compiles static DNR tracker/query-param scrubbing rules (`rules.json`), deterministic farbling (`farble.js`),
  and W3C WebMCP bootstrap (`webmcp_bootstrap.js`).
- Generates an interactive Warm Atelier Precision popup (`popup.html` + `popup.js`, zero raw HTML injection,
  strict MV3 CSP) with collision-free `allowAllRequests` per-site Pause/Resume and live Mutation Firewall control.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

from .luminara_copilot_ext import SHARED_UI_TOKENS_CSS, _js_json
from .luminara_logo3d import write_extension_icons
from .models import ForkProfile
from .shield_compiler import build_deterministic_farbling_js, compile_dnr_shield_rules
from .webmcp import WEBMCP_BOOTSTRAP_JS

ENCODING = "utf-8"


def write_shield_extension(ext_dir: Path, profile: ForkProfile, ui_key: str = "") -> None:
    """Create MV3 Privacy Shield v3 extension (DNR firewall, per-site pause, farbling, WebMCP, Mutation Firewall)."""
    ext_dir.mkdir(parents=True, exist_ok=True)
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
        "version": "4.0.0",
        "description": f"Interactive tracker/param DNR firewall (.{profile.trap_tld}), deterministic farbling, W3C WebMCP & Mutation Firewall.",
        "permissions": ["declarativeNetRequest", "declarativeNetRequestWithHostAccess", "storage", "tabs"],
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
            "default_title": f"{profile.brand_name} Privacy Shield v3",
            "default_popup": "popup.html",
            "default_icon": {"16": "icons/icon16.png", "48": "icons/icon48.png"},
        },
    }
    (ext_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding=ENCODING, newline="\n")

    webmcp_on = bool(getattr(profile, "enable_webmcp", True))
    farble_on = bool(getattr(profile, "enable_shield_v3", True))
    daemon_base = f"http://127.0.0.1:{profile.agent_port}"
    popup_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="color-scheme" content="dark light" />
  <title>{html.escape(profile.brand_name)} Privacy Shield v3</title>
  <style>
{SHARED_UI_TOKENS_CSS}
    body {{ width:320px; padding:14px; background:var(--bg-0); color:var(--ink-0); font:400 13px/1.45 var(--font-sans); display:grid; gap:10px; }}
    .head,.row {{ display:flex; align-items:center; justify-content:space-between; gap:8px; }}
    .brand {{ display:inline-flex; align-items:center; gap:8px; font-weight:600; font-size:13.5px; }}
    .badge {{ padding:3px 9px; border-radius:var(--r-pill); font:600 11px/1.2 var(--font-mono); background:var(--bg-2); color:var(--accent); }}
    .badge.paused {{ color:var(--warn); }}
    .card {{ background:var(--bg-1); border:1px solid var(--hairline); border-radius:var(--r-card); padding:12px; display:grid; gap:9px; box-shadow:var(--specular); }}
    .domain {{ font-family:var(--font-mono); font-size:12px; color:var(--ink-0); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:185px; }}
    .muted {{ font-size:12px; color:var(--ink-2); }}
    .mono {{ font-family:var(--font-mono); font-size:11.5px; font-variant-numeric:tabular-nums; color:var(--ink-1); }}
    .btn {{ min-height:32px; padding:6px 11px; border-radius:var(--r-control); border:1px solid var(--border-control); background:var(--bg-1); color:var(--ink-0); font:500 12.5px/1.2 var(--font-sans); cursor:pointer; }}
    .btn:hover:not(:disabled) {{ border-color:var(--accent); }}
    .btn:disabled {{ opacity:0.46; cursor:not-allowed; }}
    .btn.primary {{ background:var(--accent); border-color:var(--accent); color:var(--accent-ink); font-weight:600; }}
    .btn.subtle {{ background:var(--bg-2); border-color:var(--hairline); font-size:12px; }}
    .grid-2 {{ display:grid; grid-template-columns:1fr 1fr; gap:6px; }}
  </style>
</head>
<body>
  <div class="head">
    <div class="brand">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path d="M12 3L19 6V12C19 16.5 16 20 12 21C8 20 5 16.5 5 12V6L12 3Z" fill="var(--accent)"/>
      </svg>
      <span>Privacy Shield v3</span>
    </div>
    <span class="badge" id="shieldBadge">Active</span>
  </div>

  <section class="card" aria-label="Current site protection">
    <div class="row">
      <div>
        <div class="muted">Active site</div>
        <div class="domain" id="siteDomain">Checking tab...</div>
      </div>
      <button type="button" class="btn primary" id="btnToggleSite" disabled>Pause Shield</button>
    </div>
    <div class="row"><span class="muted">Tracker &amp; param rules</span><span class="mono" id="rulesCount">{len(rules)} active</span></div>
    <div class="row"><span class="muted">Fingerprint defense</span><span class="mono">{"Active" if farble_on else "Off"}</span></div>
    <div class="row"><span class="muted">W3C WebMCP tools</span><span class="mono" id="webmcpStatus">{"Active" if webmcp_on else "Off"}</span></div>
  </section>

  <section class="card" aria-label="Mutation Firewall">
    <div class="row">
      <div>
        <div style="font-weight:600;font-size:12.5px;">Mutation Firewall</div>
        <div class="muted" id="mutState">Checking daemon...</div>
      </div>
      <button type="button" class="btn subtle" id="btnToggleMut" disabled>Enable</button>
    </div>
  </section>

  <div class="grid-2">
    <button type="button" class="btn subtle" id="btnOpenTeam">Team Panel (Alt+L)</button>
    <button type="button" class="btn subtle" id="btnOpenHome">Calm Home</button>
  </div>
  <div class="muted" id="shieldMsg" role="status" aria-live="polite"></div>
  <script src="popup.js" defer></script>
</body>
</html>
"""
    (ext_dir / "popup.html").write_text(popup_html, encoding=ENCODING, newline="\n")

    popup_js = f"""const DAEMON = {_js_json(daemon_base)};
const UI_KEY = {_js_json(ui_key)};
const RULE_COUNT = {len(rules)};
const STORE_KEY = 'luminara_shield_paused_domains';
let currentDomain = '';
let sitePaused = false;
let mutEnabled = false;
let guardedTargets = [];

const siteEl = document.getElementById('siteDomain');
const badgeEl = document.getElementById('shieldBadge');
const rulesEl = document.getElementById('rulesCount');
const btnSite = document.getElementById('btnToggleSite');
const mutStateEl = document.getElementById('mutState');
const btnMut = document.getElementById('btnToggleMut');
const msgEl = document.getElementById('shieldMsg');

function apiHeaders(isJson) {{
  const h = {{}};
  if (UI_KEY) h['X-Luminara-UI-Key'] = UI_KEY;
  if (isJson) h['Content-Type'] = 'application/json';
  return h;
}}

async function allocateRuleId(existingMap) {{
  const used = new Set(Object.values(existingMap || {{}}).map(Number).filter(Number.isFinite));
  if (chrome.declarativeNetRequest && chrome.declarativeNetRequest.getDynamicRules) {{
    try {{
      const dynamic = await chrome.declarativeNetRequest.getDynamicRules();
      (dynamic || []).forEach(r => used.add(Number(r.id)));
    }} catch (_e) {{}}
  }}
  let rid = 50000;
  while (used.has(rid)) rid++;
  return rid;
}}

function renderSiteState() {{
  if (!currentDomain) {{
    siteEl.textContent = 'Browser page';
    badgeEl.textContent = 'Active';
    badgeEl.classList.remove('paused');
    rulesEl.textContent = RULE_COUNT + ' active';
    btnSite.disabled = true;
    btnSite.textContent = 'Protected';
    return;
  }}
  siteEl.textContent = currentDomain;
  badgeEl.textContent = sitePaused ? 'Paused' : 'Active';
  badgeEl.classList.toggle('paused', sitePaused);
  rulesEl.textContent = sitePaused ? 'Paused on this site' : (RULE_COUNT + ' active');
  btnSite.disabled = false;
  btnSite.textContent = sitePaused ? 'Resume Shield' : 'Pause Shield';
  btnSite.classList.toggle('primary', sitePaused);
}}

async function loadSiteState() {{
  try {{
    const [tab] = await chrome.tabs.query({{ active: true, currentWindow: true }});
    if (tab && tab.url && /^https?:\\/\\//i.test(tab.url)) currentDomain = new URL(tab.url).hostname;
  }} catch (_e) {{}}
  if (currentDomain && chrome.storage && chrome.storage.local) {{
    try {{
      const saved = await chrome.storage.local.get(STORE_KEY);
      const map = (saved && saved[STORE_KEY]) || {{}};
      sitePaused = Boolean(map[currentDomain]);
    }} catch (_e) {{}}
  }}
  renderSiteState();
}}

btnSite.addEventListener('click', async () => {{
  if (!currentDomain) return;
  btnSite.disabled = true;
  try {{
    const saved = (chrome.storage && chrome.storage.local) ? await chrome.storage.local.get(STORE_KEY) : {{}};
    const map = Object.assign({{}}, (saved && saved[STORE_KEY]) || {{}});
    if (sitePaused) {{
      const removeIds = [];
      if (map[currentDomain]) removeIds.push(Number(map[currentDomain]));
      if (chrome.declarativeNetRequest && chrome.declarativeNetRequest.getDynamicRules) {{
        const dyn = await chrome.declarativeNetRequest.getDynamicRules();
        (dyn || []).forEach(r => {{
          const doms = (r.condition && r.condition.requestDomains) || [];
          if (doms.includes(currentDomain) && !removeIds.includes(r.id)) removeIds.push(r.id);
        }});
      }}
      if (removeIds.length) await chrome.declarativeNetRequest.updateDynamicRules({{ removeRuleIds: removeIds }});
      delete map[currentDomain];
      sitePaused = false;
      msgEl.textContent = 'Shield resumed on ' + currentDomain + '.';
    }} else {{
      const rid = await allocateRuleId(map);
      await chrome.declarativeNetRequest.updateDynamicRules({{
        removeRuleIds: [rid],
        addRules: [{{
          id: rid,
          priority: 1000,
          action: {{ type: 'allowAllRequests' }},
          condition: {{ requestDomains: [currentDomain], resourceTypes: ['main_frame', 'sub_frame'] }}
        }}]
      }});
      map[currentDomain] = rid;
      sitePaused = true;
      msgEl.textContent = 'Shield paused on ' + currentDomain + '.';
    }}
    if (chrome.storage && chrome.storage.local) await chrome.storage.local.set({{ [STORE_KEY]: map }});
  }} catch (err) {{
    msgEl.textContent = 'Could not update shield: ' + (err.message || String(err));
  }} finally {{ renderSiteState(); }}
}});

async function resolveActiveTargetId() {{
  try {{
    const [tab] = await chrome.tabs.query({{ active: true, currentWindow: true }});
    if (!tab || !tab.url || !/^https?:\\/\\//i.test(tab.url)) return undefined;
    const r = await fetch(DAEMON + '/api/agent/tabs', {{ headers: apiHeaders(false), signal: AbortSignal.timeout(2200) }});
    if (!r.ok) return undefined;
    const d = await r.json();
    const hit = (d.tabs || []).find(t => t.url === tab.url) || (d.tabs || []).find(t => tab.title && t.title === tab.title);
    return hit ? hit.target_id : undefined;
  }} catch (_e) {{ return undefined; }}
}}

async function syncMutationState() {{
  try {{
    const r = await fetch(DAEMON + '/api/agent/mutations', {{ headers: apiHeaders(false), signal: AbortSignal.timeout(2000) }});
    if (r.status === 401 || r.status === 403) {{
      mutStateEl.textContent = 'Local authorization required';
      btnMut.disabled = true;
      return;
    }}
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const d = await r.json();
    guardedTargets = Array.isArray(d.guarded_targets) ? d.guarded_targets : [];
    mutEnabled = Boolean(d.enabled || guardedTargets.length > 0);
    mutStateEl.textContent = mutEnabled ? ('Guarding ' + Math.max(1, guardedTargets.length) + ' active tab(s)') : 'Off (guard POST/PUT/DELETE)';
    btnMut.textContent = mutEnabled ? 'Disable' : 'Enable';
    btnMut.disabled = false;
  }} catch (_e) {{
    mutStateEl.textContent = 'Daemon offline';
    btnMut.disabled = true;
  }}
}}

btnMut.addEventListener('click', async () => {{
  btnMut.disabled = true;
  try {{
    if (mutEnabled) {{
      const targets = guardedTargets.length ? guardedTargets.slice() : [undefined];
      for (const tid of targets) {{
        const payload = tid ? {{ action: 'disable', target_id: tid, agent_id: 'shield-popup' }} : {{ action: 'disable', agent_id: 'shield-popup' }};
        const r = await fetch(DAEMON + '/api/agent/mutations', {{ method: 'POST', headers: apiHeaders(true), body: JSON.stringify(payload), signal: AbortSignal.timeout(4000) }});
        const d = await r.json().catch(() => ({{}}));
        if (!r.ok) throw new Error(d.error || ('HTTP ' + r.status));
      }}
      msgEl.textContent = 'Mutation Firewall disabled.';
    }} else {{
      const target_id = await resolveActiveTargetId();
      const payload = target_id ? {{ action: 'enable', target_id, agent_id: 'shield-popup' }} : {{ action: 'enable', agent_id: 'shield-popup' }};
      const r = await fetch(DAEMON + '/api/agent/mutations', {{ method: 'POST', headers: apiHeaders(true), body: JSON.stringify(payload), signal: AbortSignal.timeout(4000) }});
      const d = await r.json().catch(() => ({{}}));
      if (!r.ok) throw new Error(d.error || ('HTTP ' + r.status));
      msgEl.textContent = 'Mutation Firewall enabled.';
    }}
    await syncMutationState();
  }} catch (err) {{
    msgEl.textContent = 'Firewall error: ' + (err.message || String(err));
    btnMut.disabled = false;
  }}
}});

document.getElementById('btnOpenTeam').addEventListener('click', () => {{
  if (chrome.tabs) chrome.tabs.create({{ url: 'chrome://newtab' }});
  msgEl.textContent = 'Tip: Press Alt+L anytime to open the Team Side Panel.';
}});
document.getElementById('btnOpenHome').addEventListener('click', () => {{
  if (chrome.tabs) chrome.tabs.create({{ url: 'chrome://newtab' }});
}});

loadSiteState();
syncMutationState();
"""
    (ext_dir / "popup.js").write_text(popup_js, encoding=ENCODING, newline="\n")


__all__ = ["write_shield_extension"]
