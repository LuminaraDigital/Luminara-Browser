"""Calm Spatial Home Generator (`forge/luminara_ui.py`).

Luminara Browser v4 Instant-Open Home (`newtab.html`):
- Instant `<50ms` launch: crisp `<1 KB` geometric SVG emblem, zero blocking startup splash, zero idle GPU drain.
- Mathematically verified WCAG 2.2 AA `docs/design.md` v4 Warm Atelier Precision palette with Light / Dark / Auto sync.
- Re-openable 60-Second Onboarding Card (Local Ollama auto-detect + encrypted API key via `/api/agent/llm/config`).
- Universal Intent Bar (`bot_id` + `team-research`), Speed Dial with Undo toast, Unified Single-Source Inbox (`POST /api/agent/inbox`),
  Live Tabs (focus/freeze/wake/close), Routines & Tasks, and collapsed Developer Mode Drawer.
- Zero raw HTML string injection anywhere (strict `document.createElement` + `textContent`).
"""

from __future__ import annotations

import html

from .luminara_copilot_ext import SHARED_UI_TOKENS_CSS, _js_json, build_palette_js, write_copilot_extension
from .luminara_logo3d import (
    LOGO_3D_CSS,
    build_logo_3d_hero_badge_html,
    build_logo_3d_js,
    build_logo_3d_splash_html,
    get_logo_favicon_data_uri,
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
    favicon_uri = get_logo_favicon_data_uri()

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="color-scheme" content="dark light" />
  <link rel="icon" type="image/png" href="{favicon_uri}" />
  <title>{brand_esc}</title>
  <style>
{SHARED_UI_TOKENS_CSS}
    body {{ min-height:100dvh; color:var(--ink-0); font:400 14px/1.55 var(--font-sans); padding:clamp(14px,2.5vw,28px); display:flex; flex-direction:column; gap:20px; -webkit-font-smoothing:antialiased; background:radial-gradient(760px 320px at 50% -6%, color-mix(in srgb, var(--accent) 11%, transparent), transparent 72%), var(--bg-0); }}
    header,main,footer {{ max-width:780px; width:100%; margin:0 auto; min-width:0; }}
    header,.card-head,.omni-pills,footer {{ display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px; }}
    .brand-mark {{ display:inline-flex; align-items:center; gap:9px; font-weight:600; font-size:14px; letter-spacing:-0.015em; }}
    .status-chip {{ display:inline-flex; align-items:center; gap:6px; padding:4px 10px; border-radius:var(--r-pill); background:var(--bg-1); border:1px solid var(--hairline); font-size:12px; color:var(--ink-1); }}
    .dot {{ width:7px; height:7px; border-radius:50%; background:var(--accent); flex-shrink:0; }} .dot.offline {{ background:var(--warn); }}
    .top-controls,.pill-group,.omni-row {{ display:flex; align-items:center; gap:6px; flex-wrap:wrap; }}
    .theme-seg {{ display:inline-flex; padding:2px; border-radius:var(--r-control); background:var(--bg-rail); border:1px solid var(--hairline); gap:2px; }}
    .theme-seg button {{ min-height:26px; border:0; background:transparent; color:var(--ink-1); padding:4px 9px; border-radius:8px; font:500 12px/1.2 var(--font-sans); cursor:pointer; }}
    .theme-seg button.active {{ background:var(--bg-1); color:var(--ink-0); font-weight:600; box-shadow:var(--specular); }}
    .btn {{ min-height:32px; padding:6px 12px; border-radius:var(--r-control); border:1px solid var(--border-control); background:var(--bg-1); color:var(--ink-0); text-decoration:none; font:500 12.5px/1.2 var(--font-sans); cursor:pointer; display:inline-flex; align-items:center; justify-content:center; gap:6px; transition:border-color 150ms var(--ease-out), transform 120ms var(--ease-out); }}
    .btn:hover:not(:disabled) {{ border-color:var(--accent); transform:translateY(-1px); }} .btn:active:not(:disabled) {{ transform:scale(0.97); }} .btn:disabled {{ opacity:0.45; cursor:wait; }}
    .btn.primary {{ background:var(--accent); border-color:var(--accent); color:var(--accent-ink); font-weight:600; }}
    .btn.stop {{ background:var(--danger); border-color:var(--danger); color:var(--danger-ink); font-weight:600; }}
    .btn.subtle {{ background:var(--bg-2); border-color:var(--hairline); font-size:12px; min-height:28px; padding:5px 10px; }}
    .mono {{ font-family:var(--font-mono); font-size:12px; color:var(--ink-2); font-variant-numeric:tabular-nums; overflow-wrap:anywhere; }}
    main {{ display:grid; gap:18px; flex:1; align-content:start; }}
    .card {{ background:var(--bg-1); border:1px solid var(--hairline); box-shadow:var(--card-shadow); border-radius:var(--r-card); padding:16px; display:grid; gap:12px; min-width:0; }}
    .card-title {{ font-size:14px; font-weight:600; letter-spacing:-0.015em; }}
    .hero-stage {{ display:grid; gap:14px; padding-top:clamp(8px,3vh,24px); }}
    h1 {{ font-size:clamp(1.75rem,3.6vw,2.25rem); font-weight:600; letter-spacing:-0.035em; line-height:1.08; text-wrap:balance; }}
    .omni-shell {{ background:var(--bg-1); border:1px solid var(--hairline); box-shadow:var(--card-shadow); border-radius:var(--r-shell); padding:10px; display:grid; gap:8px; min-width:0; }}
    .omni-input {{ flex:1 1 220px; min-width:0; min-height:44px; background:var(--bg-0); border:1px solid var(--border-control); border-radius:var(--r-control); color:var(--ink-0); font:400 15px/1.4 var(--font-sans); padding:10px 14px; }}
    .mode-pill {{ min-height:28px; padding:4px 11px; border-radius:var(--r-pill); border:1px solid var(--hairline); background:var(--bg-2); color:var(--ink-1); font:500 12px/1.2 var(--font-sans); cursor:pointer; }}
    .mode-pill.active {{ border-color:var(--accent); color:var(--accent); background:var(--bg-1); font-weight:600; }}
    .reply-card,.onboard-card {{ display:none; border-left:3px solid var(--accent); }} .reply-card.visible,.onboard-card.visible {{ display:grid; }}
    .field-stack {{ display:grid; gap:4px; flex:1 1 150px; min-width:0; }}
    .field-lbl {{ font-size:11.5px; font-weight:500; color:var(--ink-1); }}
    .field-err {{ font-size:11.5px; color:var(--danger); min-height:15px; }}
    .dial-grid {{ display:grid; grid-template-columns:repeat(auto-fill, minmax(min(100%, 148px), 1fr)); gap:10px; }}
    .dial-tile {{ display:flex; align-items:center; gap:8px; padding:8px 8px 8px 10px; border-radius:var(--r-control); background:var(--bg-1); border:1px solid var(--hairline); color:var(--ink-0); text-decoration:none; min-width:0; box-shadow:var(--specular); transition:border-color 140ms var(--ease-out), transform 120ms var(--ease-out); }}
    .dial-tile:hover {{ border-color:var(--accent); transform:translateY(-1px); }}
    .dial-badge {{ width:28px; height:28px; border-radius:8px; background:var(--bg-2); color:var(--accent); display:grid; place-items:center; font:600 12px/1 var(--font-mono); flex-shrink:0; }}
    .dial-label {{ font-size:13px; font-weight:500; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; flex:1; min-width:0; }}
    .dial-del {{ min-width:24px; min-height:24px; display:grid; place-items:center; border:0; background:transparent; color:var(--ink-2); cursor:pointer; font-size:14px; border-radius:6px; flex-shrink:0; }}
    .dial-del:hover {{ color:var(--danger); background:var(--bg-2); }}
    .inbox-section {{ display:none; gap:10px; }} .inbox-section.visible {{ display:grid; }}
    .approval-card {{ background:var(--bg-1); border:1px solid color-mix(in srgb, var(--warn) 48%, var(--hairline)); border-left:3px solid var(--warn); border-radius:var(--r-card); padding:14px 16px; display:grid; gap:8px; }}
    .handoff-banner {{ display:none; }} .handoff-banner.visible {{ display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:10px; }}
    .list-scroll {{ display:grid; gap:8px; max-height:250px; overflow-y:auto; min-width:0; }}
    .row-item {{ display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px; padding:9px 12px; border-radius:var(--r-control); background:var(--bg-2); border:1px solid var(--hairline); font-size:13px; min-width:0; }}
    .skel {{ height:40px; border-radius:var(--r-control); background:var(--bg-2); border:1px solid var(--hairline); opacity:0.65; }}
    .tab-link {{ background:transparent; border:0; color:var(--ink-0); text-align:left; cursor:pointer; flex:1 1 160px; min-width:0; font:inherit; padding:0; display:grid; gap:2px; }}
    .tab-link:hover .tab-title {{ color:var(--accent); }} .tab-title {{ font-weight:500; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
    .cols-2 {{ display:grid; grid-template-columns:repeat(2, minmax(0, 1fr)); gap:14px; }}
    @media (max-width: 680px) {{ .cols-2 {{ grid-template-columns:minmax(0, 1fr); }} }}
    .inp-sm {{ width:100%; min-width:0; min-height:34px; background:var(--bg-0); border:1px solid var(--border-control); border-radius:var(--r-control); padding:6px 10px; color:var(--ink-0); font:400 13px/1.3 var(--font-sans); }}
    .progress-track {{ height:4px; background:var(--bg-2); border-radius:var(--r-pill); overflow:hidden; }}
    .progress-fill {{ height:100%; width:100%; background:var(--accent); transform-origin:left center; transform:scaleX(0); transition:transform 220ms var(--ease-out); }}
    .todo-done {{ text-decoration:line-through; color:var(--ink-2); }}
    .prio-high {{ color:var(--danger); }} .prio-medium {{ color:var(--warn); }} .prio-low {{ color:var(--accent); }}
    details.dev-drawer {{ background:var(--bg-1); border:1px solid var(--hairline); border-radius:var(--r-card); padding:12px 16px; }}
    details.dev-drawer summary {{ cursor:pointer; font-weight:600; font-size:13px; color:var(--ink-2); user-select:none; }}
    .dev-body {{ margin-top:14px; display:grid; gap:14px; }}
    .toast-tray {{ position:fixed; right:16px; bottom:16px; z-index:9999; display:grid; gap:8px; max-width:min(380px, calc(100vw - 32px)); }}
    .toast {{ background:var(--bg-1); border:1px solid var(--accent); box-shadow:var(--card-shadow); border-radius:var(--r-control); padding:10px 14px; font-size:12.5px; color:var(--ink-0); display:flex; justify-content:space-between; align-items:center; gap:10px; }}
    footer {{ font-size:12px; color:var(--ink-2); padding-top:8px; }}
{LOGO_3D_CSS}
    @media (prefers-reduced-motion: reduce) {{ *, *::before, *::after {{ transition:none !important; animation:none !important; }} }}
  </style>
</head>
<body>
{logo_splash_html}
  <template id="lumHero3dTpl">{logo_hero_badge_html}</template>

  <header>
    <div class="brand-mark">
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <rect x="2" y="2" width="20" height="20" rx="6" stroke="currentColor" stroke-width="1.6" opacity="0.32"/>
        <path d="M12 5.2L17.6 12L12 18.8L6.4 12L12 5.2Z" fill="var(--accent)"/>
      </svg>
      <span>{brand_esc}</span>
      <span class="status-chip"><span class="dot" id="daemonDot"></span><span id="daemonLabel">Connecting...</span></span>
    </div>
    <div class="top-controls">
      <div class="theme-seg" role="radiogroup" aria-label="Color theme">
        <button type="button" data-theme-pick="system" role="radio" aria-checked="true" class="active">Auto</button>
        <button type="button" data-theme-pick="light" role="radio" aria-checked="false">Light</button>
        <button type="button" data-theme-pick="dark" role="radio" aria-checked="false">Dark</button>
      </div>
      <button class="btn subtle" type="button" id="btnOpenAiSetup">AI Provider</button>
      <a class="btn subtle" href="{html.escape(workspace_uri)}#view=comparison">Live Lens</a>
      <button class="btn subtle mono" type="button" id="btnOpenPalette" title="Open Command Palette">Alt+K</button>
      <span class="mono" id="clock">--:--</span>
    </div>
  </header>

  <main>
    <section class="card onboard-card" id="onboardingCard" aria-labelledby="onboardTitle">
      <div class="card-head">
        <div>
          <div class="card-title" id="onboardTitle">AI Provider Setup</div>
          <div style="font-size:12.5px;color:var(--ink-1);">Pick a local Ollama model or save an encrypted API key. Everything stays on your device.</div>
        </div>
        <button type="button" class="btn subtle" id="btnDismissOnboard">Close</button>
      </div>
      <div id="ollamaDetectRow" style="display:flex;gap:6px;flex-wrap:wrap;align-items:center;">
        <span style="font-size:12px;color:var(--ink-2);" id="ollamaStatusText">Checking local Ollama models...</span>
      </div>
      <form id="onboardLlmForm" style="display:flex;gap:10px;flex-wrap:wrap;align-items:flex-start;" novalidate>
        <div class="field-stack" style="flex:0 1 150px;">
          <label class="field-lbl" for="obProvider">Provider</label>
          <select class="inp-sm" id="obProvider">
            <option value="ollama">Local Ollama</option>
            <option value="openrouter">OpenRouter</option>
            <option value="gemini">Google Gemini</option>
            <option value="anthropic">Claude (Anthropic)</option>
            <option value="openai">OpenAI</option>
          </select>
        </div>
        <div class="field-stack">
          <label class="field-lbl" for="obModel">Model (optional)</label>
          <input class="inp-sm" id="obModel" type="text" placeholder="e.g. llama3.2" autocomplete="off" />
        </div>
        <div class="field-stack" id="obApiKeyWrap" style="display:none;">
          <label class="field-lbl" for="obApiKey">API Key (encrypted locally)</label>
          <input class="inp-sm" id="obApiKey" type="password" placeholder="Paste key..." autocomplete="off" disabled />
          <div class="field-err" id="obApiKeyErr"></div>
        </div>
        <div style="padding-top:20px;">
          <button type="submit" class="btn" id="btnSaveLlm">Save Provider</button>
        </div>
      </form>
      <div style="font-size:12px;color:var(--ink-2);" id="onboardMsg" role="status" aria-live="polite"></div>
    </section>

    <section class="hero-stage" aria-label="Intent bar">
      <h1 id="greetingTitle">Good day</h1>
      <form class="omni-shell" id="omniForm">
        <div class="omni-row">
          <label class="sr-only" for="omniInput">Search the web, enter a website, or ask your AI team</label>
          <input class="omni-input" id="omniInput" type="text" placeholder="Search privately ({eng_esc}), open a site, or ask your team..." autofocus autocomplete="off" />
          <button class="btn primary" type="submit" id="omniSubmit" style="min-height:44px;padding:10px 18px;">Go ↵</button>
        </div>
        <div class="omni-pills">
          <div class="pill-group" role="tablist" aria-label="Intent mode">
            <button type="button" class="mode-pill active" role="tab" aria-selected="true" data-mode="auto">Smart Auto</button>
            <button type="button" class="mode-pill" role="tab" aria-selected="false" data-mode="team">Ask Team</button>
            <button type="button" class="mode-pill" role="tab" aria-selected="false" data-mode="bulk">Compare URLs</button>
          </div>
          <span style="font-size:12px;color:var(--ink-2);" id="omniStatus" role="status" aria-live="polite">Private search · Local-first team</span>
        </div>
      </form>

      <article class="card reply-card" id="teamReplyCard" aria-live="polite">
        <div class="card-head">
          <span class="card-title" id="teamReplySender">Research Team</span>
          <div style="display:flex;gap:6px;">
            <button type="button" class="btn subtle" id="btnReplySetup" style="display:none;">Connect AI Provider →</button>
            <button type="button" class="btn subtle" id="btnCloseReply">Dismiss</button>
          </div>
        </div>
        <div id="teamReplyText" style="white-space:pre-wrap;"></div>
        <details id="teamReplyReceipt" style="display:none;font-size:12px;color:var(--ink-2);">
          <summary style="cursor:pointer;" id="teamReplyReceiptSummary">Work receipt</summary>
          <div id="teamReplyReceiptBody" class="mono" style="margin-top:6px;"></div>
        </details>
      </article>
    </section>

    <section aria-label="Pinned favorites">
      <div class="card-head" style="margin-bottom:8px;">
        <span class="card-title">Speed Dial</span>
        <button type="button" class="btn subtle" id="btnToggleDialForm">+ Pin site</button>
      </div>
      <form id="dialForm" style="display:none;gap:10px;flex-wrap:wrap;align-items:flex-start;margin-bottom:10px;" class="card" novalidate>
        <div class="field-stack">
          <label class="field-lbl" for="dialName">Site Name</label>
          <input class="inp-sm" id="dialName" type="text" placeholder="Wikipedia" required />
          <div class="field-err" id="dialNameErr"></div>
        </div>
        <div class="field-stack">
          <label class="field-lbl" for="dialUrl">Website URL</label>
          <input class="inp-sm" id="dialUrl" type="text" placeholder="wikipedia.org" required />
          <div class="field-err" id="dialUrlErr"></div>
        </div>
        <div style="padding-top:20px;"><button type="submit" class="btn">Save Pin</button></div>
      </form>
      <div class="dial-grid" id="speedDialGrid"></div>
    </section>

    <section class="inbox-section" id="inboxSection" aria-labelledby="inboxHeading">
      <div class="card-head"><span class="card-title" id="inboxHeading">Needs You</span><span style="font-size:12px;color:var(--ink-2);" id="inboxCount"></span></div>
      <div id="inboxList" style="display:grid;gap:8px;"></div>
      <div class="approval-card handoff-banner" id="handoffBanner" role="status" aria-live="polite">
        <div><strong>Your turn on this page</strong><div id="handoffText" style="font-size:12.5px;color:var(--ink-1);">Paused at a sign-in or verification step.</div></div>
        <button class="btn primary" type="button" id="btnResumeHandoff">Resume Agent ↵</button>
      </div>
      <div class="approval-card handoff-banner" id="mutationBanner" role="status" aria-live="polite">
        <div style="min-width:0;overflow-wrap:anywhere;"><strong>Approval needed before sending changes</strong><div id="mutationText" style="font-size:12.5px;color:var(--ink-1);">An assistant paused before modifying a website.</div></div>
        <div style="display:flex;gap:6px;flex-wrap:wrap;">
          <button class="btn" type="button" id="btnRejectMutation">Deny</button>
          <button class="btn primary" type="button" id="btnApproveMutation">Allow once</button>
        </div>
      </div>
    </section>

    <section class="card" id="tabsSection" aria-labelledby="tabsCardHead">
      <div class="card-head">
        <span class="card-title" id="tabsCardHead">Spaces &amp; Live Tabs (<span id="tabCount">0</span>)</span>
        <div style="display:flex;gap:6px;flex-wrap:wrap;">
          <button class="btn" type="button" id="btnCompareLens">Compare in Live Lens</button>
          <button class="btn subtle" type="button" id="btnRefreshDaemon">Refresh</button>
        </div>
      </div>
      <div class="list-scroll" id="liveTabsList"><div class="skel"></div><div class="skel"></div></div>
    </section>

    <section class="cols-2" id="routinesSection" aria-label="Tasks and routines">
      <div class="card">
        <div class="card-head"><span class="card-title">Tasks</span><span class="mono" id="todoPct">0%</span></div>
        <form style="display:flex;gap:6px;flex-wrap:wrap;" id="todoForm">
          <label class="sr-only" for="todoInput">Add a task</label>
          <input class="inp-sm" id="todoInput" type="text" style="flex:1 1 130px;width:auto;" placeholder="Add a personal or research task..." />
          <label class="sr-only" for="todoPrio">Priority</label>
          <select class="inp-sm" id="todoPrio" style="flex:0 0 auto;width:auto;"><option value="high">High</option><option value="medium" selected>Med</option><option value="low">Low</option></select>
          <button class="btn subtle" type="submit" id="btnAddTodo">Add</button>
        </form>
        <div class="progress-track" aria-label="Task progress"><div class="progress-fill" id="todoProgress"></div></div>
        <div class="list-scroll" id="todoList"></div>
      </div>

      <div class="card">
        <div class="card-head"><span class="card-title">Scheduled Routines</span><button type="button" class="btn subtle" id="btnSyncSchedules">Refresh</button></div>
        <div class="list-scroll" id="schedulesList"><div class="row-item"><span style="color:var(--ink-2);">No scheduled routines yet.</span></div></div>
      </div>
    </section>

    <details class="dev-drawer" id="devDrawer">
      <summary>Developer Mode · MCP, Action Ledger, Vault &amp; Advanced Settings</summary>
      <div class="dev-body">
        <div class="row-item">
          <div style="min-width:0;"><div style="font-weight:600;font-size:13px;">MCP v2 Endpoint &amp; Discovery</div><div class="mono">POST {daemon_base}/api/agent/mcp</div></div>
          <div style="display:flex;gap:6px;flex-wrap:wrap;">
            <button class="btn subtle" type="button" id="btnCopyMcp">Copy MCP Endpoint</button>
            <button class="btn subtle" type="button" id="btnReplayIntro">Preview 3D Emblem</button>
          </div>
        </div>
        <div style="display:grid;gap:8px;">
          <div class="card-head"><span class="card-title">Verifiable Action Ledger (<code>LUM-*</code>)</span><span class="mono" id="receiptCount">0 recent</span></div>
          <div class="list-scroll" id="receiptsList"><div class="row-item"><span class="mono">No receipts recorded yet.</span></div></div>
        </div>
        <div style="display:grid;gap:8px;">
          <div class="card-head">
            <span class="card-title">Encrypted Vault &amp; Learned Playbooks</span>
            <div style="display:flex;gap:6px;flex-wrap:wrap;"><button class="btn subtle" type="button" id="btnToggleVaultForm">+ Add Credential</button><button class="btn subtle" type="button" id="btnSyncVault">Refresh</button></div>
          </div>
          <div class="mono" id="vaultSummaryLbl">Open to load Vault &amp; Playbooks.</div>
          <form id="vaultRegForm" style="display:none;gap:8px;padding:12px;border-radius:10px;background:var(--bg-2);border:1px solid var(--hairline);" novalidate>
            <div class="field-stack"><label class="field-lbl" for="vltOrigin">Origin URL</label><input class="inp-sm" id="vltOrigin" type="url" placeholder="https://portal.example.com" required /><div class="field-err" id="vltOriginErr"></div></div>
            <div style="display:flex;gap:8px;flex-wrap:wrap;">
              <div class="field-stack"><label class="field-lbl" for="vltUser">Username / Email</label><input class="inp-sm" id="vltUser" type="text" placeholder="alice@example.com" autocomplete="off" /></div>
              <div class="field-stack"><label class="field-lbl" for="vltId">Handle ID (optional)</label><input class="inp-sm" id="vltId" type="text" placeholder="portal_main" autocomplete="off" /></div>
            </div>
            <div style="display:flex;gap:8px;flex-wrap:wrap;">
              <div class="field-stack"><label class="field-lbl" for="vltPass">Password (DPAPI/AEAD sealed)</label><input class="inp-sm" id="vltPass" type="password" placeholder="Password" autocomplete="new-password" /></div>
              <div class="field-stack"><label class="field-lbl" for="vltTotp">TOTP Secret (optional)</label><input class="inp-sm" id="vltTotp" type="password" placeholder="Base32 or otpauth://" autocomplete="off" /></div>
            </div>
            <button class="btn" type="submit" style="justify-self:start;">Seal Origin-Bound Credential</button>
          </form>
          <div class="list-scroll" id="vaultPlaybookList"></div>
        </div>
        <div style="display:grid;gap:8px;">
          <div class="card-head"><span class="card-title">Operator &amp; Co-Browsing Settings</span><button class="btn subtle" type="button" id="btnDevAiSetup">Configure AI Provider</button></div>
          <label class="row-item" for="cfgOperator"><span>Display Name</span><input class="inp-sm" id="cfgOperator" style="max-width:200px;" autocomplete="nickname" placeholder="Optional greeting name" /></label>
          <label class="row-item" for="cfgShowHud"><span>Show interactive target labels during agent runs</span><input type="checkbox" id="cfgShowHud" checked /></label>
          <label class="row-item" for="cfgPassport"><span>Agent Passport Token (optional)</span><input class="inp-sm" type="password" id="cfgPassport" style="max-width:200px;" autocomplete="off" placeholder="Bearer token" /></label>
          <div class="row-item"><span>Privacy Switches Active</span><span class="mono" id="swCountBadge">0</span></div>
          <button class="btn" type="button" id="btnSaveSettings" style="justify-self:start;">Save Settings</button>
        </div>
      </div>
    </details>
  </main>

  <footer>
    <span>{brand_esc} · Private by default · Zero Google Telemetry</span>
    <span class="mono">Alt+K Command Palette · Alt+L Team Panel</span>
  </footer>
  <div class="toast-tray" id="toastTray" aria-live="polite"></div>

  <script>
    const DAEMON = (/^https?:$/i.test(location.protocol) && /^(127\\.0\\.0\\.1|localhost|\\[::1\\])$/i.test(location.hostname)) ? location.origin : {_js_json(daemon_base)};
    const BRAND = {_js_json(profile.brand_name)}, SLUG = {_js_json(profile.slug)}, SEARCH_TPL = {_js_json(engine.search_url)};
    const SWITCHES = {_js_json(profile.runtime_switches())}, WORKSPACE_URI = {_js_json(workspace_uri)};
    const UI_KEY = {_js_json(ui_key)};
    const COBROWSE_ENABLED = {_js_json(bool(profile.enable_agent_cobrowsing))};
    const KEY_TODOS = 'luminara_browser:todos', KEY_SETTINGS = 'luminara_browser:settings', KEY_DIAL = 'luminara_browser:speed_dial', KEY_GENUI = 'luminara_browser:genui_payload', KEY_SS = 'luminara_browser:session_tok';

    try {{ sessionStorage.setItem('luminara_splash_seen', '1'); }} catch (_e) {{}}
    try {{ if (typeof chrome !== 'undefined' && chrome.storage && chrome.storage.session) chrome.storage.session.set({{ luminara_splash_seen: true }}); }} catch (_e) {{}}

    let omniMode = 'auto', activeHandoffRunId = null, activeMutationId = null, activeAbort = null, __lum3dBooted = false, agentSessionTok = '', forceShowInbox = false;
    const el = (tag, cls, text) => {{ const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = String(text); return n; }};
    const mkBtn = (cls, text, fn) => {{ const b = el('button', cls, text); b.type = 'button'; b.onclick = fn; return b; }};
    const INITIAL_HASH = location.hash || '';
    let sessionTok = (() => {{
      const m = INITIAL_HASH.match(/(?:^#|&)lum_tok(?:en)?=([^&]+)/);
      if (m) {{
        const tok = decodeURIComponent(m[1]);
        try {{ sessionStorage.setItem(KEY_SS, tok); history.replaceState(null, '', location.pathname + location.search); }} catch (_e) {{}}
        return tok;
      }}
      try {{ return sessionStorage.getItem(KEY_SS) || ''; }} catch (_e) {{ return ''; }}
    }})();

    function loadSettings() {{ try {{ return JSON.parse(localStorage.getItem(KEY_SETTINGS) || '{{}}'); }} catch (_e) {{ return {{}}; }} }}
    function safeSetLS(k, v) {{ try {{ localStorage.setItem(k, v); }} catch (_e) {{}} }}
    function saveSettingsPatch(p) {{ const n = Object.assign({{}}, loadSettings(), p); safeSetLS(KEY_SETTINGS, JSON.stringify(n)); return n; }}
    function apiHeaders(isJson) {{
      const h = {{}}, uiAuth = UI_KEY || sessionTok, passport = agentSessionTok || (loadSettings().passportToken || '').trim();
      if (uiAuth) h['X-Luminara-UI-Key'] = uiAuth;
      if (passport) h['Authorization'] = 'Bearer ' + passport;
      if (isJson) h['Content-Type'] = 'application/json';
      return h;
    }}
    async function exchangePassportSession() {{
      if (UI_KEY || sessionTok || agentSessionTok || !(loadSettings().passportToken || '').trim()) return;
      try {{
        const r = await fetch(DAEMON + '/api/agent/session-token', {{ method: 'POST', headers: apiHeaders(true), body: JSON.stringify({{ scope: 'agent', ttl_sec: 900 }}), signal: AbortSignal.timeout(4000) }});
        if (r.ok) {{ const d = await r.json(); if (d && d.token) agentSessionTok = d.token; }}
      }} catch (_e) {{}}
    }}
    function humanError(err) {{
      if (!err) return 'Action failed.';
      if (err.status === 401 || err.status === 403) return 'Local authorization required — open via Luminara launcher to sync your local key.';
      if (err.status === 502) return 'Browser tab is reloading or unavailable — retry in a moment.';
      if (err.status === 0 || /failed to fetch|networkerror/i.test(String(err.message || ''))) return 'Luminara daemon is offline — launch via Luminara Browser.';
      return err.message || String(err);
    }}
    async function apiFetch(path, body, signal) {{
      const isPost = body !== undefined;
      let res;
      try {{
        res = await fetch(DAEMON + path, {{ method: isPost ? 'POST' : 'GET', headers: apiHeaders(isPost), body: isPost ? JSON.stringify(body) : undefined, signal: signal || AbortSignal.timeout(15000) }});
      }} catch (netErr) {{
        if (netErr && netErr.name === 'AbortError') throw netErr;
        const e = new Error('Daemon offline'); e.status = 0; throw e;
      }}
      const data = await res.json().catch(() => ({{}}));
      if (!res.ok) {{ const err = new Error(data.error || ('HTTP ' + res.status)); err.status = res.status; throw err; }}
      return data;
    }}
    function notify(msg, undoFn) {{
      const tray = document.getElementById('toastTray'), box = el('div', 'toast'), acts = el('div');
      acts.style.cssText = 'display:flex;gap:6px;align-items:center;';
      if (typeof undoFn === 'function') acts.appendChild(mkBtn('btn subtle', 'Undo', () => {{ undoFn(); box.remove(); }}));
      const close = mkBtn('btn subtle', '×', () => box.remove()); close.setAttribute('aria-label', 'Dismiss notification');
      acts.appendChild(close); box.append(el('span', '', msg), acts); tray.appendChild(box);
      setTimeout(() => box.remove(), undoFn ? 6500 : 4500);
    }}
    function applyTheme(mode) {{
      const m = (mode === 'light' || mode === 'dark') ? mode : 'system';
      if (m === 'system') document.documentElement.removeAttribute('data-theme'); else document.documentElement.setAttribute('data-theme', m);
      document.querySelectorAll('[data-theme-pick]').forEach(b => {{ const on = b.getAttribute('data-theme-pick') === m; b.classList.toggle('active', on); b.setAttribute('aria-checked', String(on)); }});
    }}
    function applySettings() {{
      const s = loadSettings();
      applyTheme(s.theme || 'system');
      document.getElementById('cfgOperator').value = s.operator || '';
      document.getElementById('cfgShowHud').checked = s.showHud !== false;
      const pEl = document.getElementById('cfgPassport'); if (pEl) pEl.value = s.passportToken || '';
      document.getElementById('swCountBadge').textContent = SWITCHES.length + ' active';
      const hr = new Date().getHours(), part = hr < 12 ? 'Good morning' : (hr < 18 ? 'Good afternoon' : 'Good evening');
      const name = (s.operator || '').trim();
      document.getElementById('greetingTitle').textContent = name ? (part + ', ' + name) : part;
    }}
    document.querySelectorAll('[data-theme-pick]').forEach(btn => btn.addEventListener('click', () => {{ const m = btn.getAttribute('data-theme-pick') || 'system'; saveSettingsPatch({{ theme: m }}); applyTheme(m); }}));
    window.addEventListener('storage', ev => {{
      if (ev.key === KEY_SETTINGS) {{ try {{ applyTheme((JSON.parse(ev.newValue || '{{}}').theme) || 'system'); }} catch (_e) {{}} }}
    }});
    document.getElementById('btnSaveSettings').addEventListener('click', async () => {{
      const pEl = document.getElementById('cfgPassport');
      saveSettingsPatch({{ operator: document.getElementById('cfgOperator').value.trim(), showHud: document.getElementById('cfgShowHud').checked, passportToken: pEl ? pEl.value.trim() : '' }});
      applySettings(); await exchangePassportSession(); syncDaemon(); notify('Settings saved.');
    }});

    // === Re-openable AI Provider / Onboarding Card ===
    function syncProviderFields() {{
      const isOllama = document.getElementById('obProvider').value === 'ollama';
      const wrap = document.getElementById('obApiKeyWrap'), keyInp = document.getElementById('obApiKey');
      wrap.style.display = isOllama ? 'none' : 'grid';
      keyInp.disabled = isOllama;
      if (isOllama) document.getElementById('obApiKeyErr').textContent = '';
    }}
    document.getElementById('obProvider').addEventListener('change', syncProviderFields);
    document.getElementById('obApiKey').addEventListener('blur', () => {{
      const isOllama = document.getElementById('obProvider').value === 'ollama', val = document.getElementById('obApiKey').value.trim();
      document.getElementById('obApiKeyErr').textContent = (!isOllama && !val && !document.getElementById('obApiKey').placeholder.includes('••••')) ? 'API key is required for this provider.' : '';
    }});
    async function syncOnboarding(forceOpen = false) {{
      const card = document.getElementById('onboardingCard');
      if (!forceOpen && loadSettings().onboardingDismissed) {{ card.classList.remove('visible'); return; }}
      try {{
        const cfg = await apiFetch('/api/agent/llm/config', undefined, AbortSignal.timeout(2200));
        if (cfg && cfg.provider) document.getElementById('obProvider').value = cfg.provider;
        if (cfg && cfg.model) document.getElementById('obModel').value = cfg.model;
        if (cfg && cfg.masked_key) document.getElementById('obApiKey').placeholder = 'Saved (' + cfg.masked_key + ') — leave blank to keep';
        syncProviderFields();
        const models = (cfg && ((cfg.ollama && cfg.ollama.models) || cfg.ollama_models || cfg.local_models)) || [];
        const row = document.getElementById('ollamaDetectRow'); row.replaceChildren();
        if (models.length) {{
          row.appendChild(el('span', '', 'Local Ollama models:'));
          models.slice(0, 5).forEach(m => {{
            const name = typeof m === 'string' ? m : (m.name || m.model || ''); if (!name) return;
            const b = mkBtn('btn subtle', 'Use ' + name, async () => {{
              b.disabled = true;
              try {{ await apiFetch('/api/agent/llm/config', {{ provider: 'ollama', model: name }}); saveSettingsPatch({{ onboardingDismissed: true }}); card.classList.remove('visible'); notify('Connected local model ' + name + '.'); }}
              catch (err) {{ document.getElementById('onboardMsg').textContent = humanError(err); }}
              finally {{ b.disabled = false; }}
            }});
            row.appendChild(b);
          }});
        }} else row.appendChild(el('span', '', 'No local Ollama models detected — pick a cloud provider below or close to browse privately.'));
        if (!forceOpen && cfg && cfg.configured) {{ card.classList.remove('visible'); return; }}
        card.classList.add('visible');
      }} catch (_e) {{
        syncProviderFields();
        if (forceOpen || !loadSettings().onboardingDismissed) card.classList.add('visible');
        const txt = document.getElementById('ollamaStatusText'); if (txt) txt.textContent = 'Connect Ollama or save an encrypted API key once Luminara is running.';
      }}
    }}
    document.getElementById('btnOpenAiSetup').addEventListener('click', () => {{ syncOnboarding(true); document.getElementById('onboardingCard').scrollIntoView({{ behavior: 'smooth', block: 'nearest' }}); }});
    document.getElementById('btnDevAiSetup').addEventListener('click', () => {{ syncOnboarding(true); document.getElementById('onboardingCard').scrollIntoView({{ behavior: 'smooth', block: 'nearest' }}); }});
    document.getElementById('btnDismissOnboard').addEventListener('click', () => {{ saveSettingsPatch({{ onboardingDismissed: true }}); document.getElementById('onboardingCard').classList.remove('visible'); }});
    document.getElementById('onboardLlmForm').addEventListener('submit', async e => {{
      e.preventDefault();
      const provider = document.getElementById('obProvider').value, model = document.getElementById('obModel').value.trim(), api_key = document.getElementById('obApiKey').value.trim();
      const msgEl = document.getElementById('onboardMsg'), btn = document.getElementById('btnSaveLlm'), errEl = document.getElementById('obApiKeyErr');
      if (provider !== 'ollama' && !api_key && !document.getElementById('obApiKey').placeholder.includes('••••')) {{
        errEl.textContent = 'Enter an API key for ' + provider + '.'; return;
      }}
      errEl.textContent = ''; btn.disabled = true; msgEl.textContent = 'Saving encrypted configuration...';
      try {{
        const payload = {{ provider, model: model || undefined }};
        if (provider !== 'ollama' && api_key) payload.api_key = api_key;
        await apiFetch('/api/agent/llm/config', payload);
        document.getElementById('obApiKey').value = ''; saveSettingsPatch({{ onboardingDismissed: true }});
        document.getElementById('onboardingCard').classList.remove('visible'); notify('AI provider saved (' + provider + ').');
      }} catch (err) {{ msgEl.textContent = humanError(err); }}
      finally {{ btn.disabled = false; }}
    }});

    // === Speed Dial (auto https:// + onBlur validation + Undo toast) ===
    function normalizeHttpUrl(raw) {{
      const s = String(raw || '').trim();
      if (!s) return '';
      if (/^https?:\\/\\//i.test(s)) return s;
      if (/^[a-z0-9-]+(\\.[a-z0-9-]+)+(:\\d+)?(\\/.*)?$/i.test(s)) return 'https://' + s;
      return '';
    }}
    function getDial() {{
      try {{ const raw = localStorage.getItem(KEY_DIAL); if (raw) return JSON.parse(raw); }} catch (_e) {{}}
      const seed = [{{ id: 'd1', name: 'DuckDuckGo', url: 'https://duckduckgo.com' }}, {{ id: 'd2', name: 'Wikipedia', url: 'https://en.wikipedia.org' }}, {{ id: 'd3', name: 'GitHub', url: 'https://github.com' }}, {{ id: 'd4', name: 'Hacker News', url: 'https://news.ycombinator.com' }}];
      safeSetLS(KEY_DIAL, JSON.stringify(seed)); return seed;
    }}
    function renderDial() {{
      const grid = document.getElementById('speedDialGrid'), items = getDial();
      grid.replaceChildren();
      items.forEach(item => {{
        const tile = document.createElement('a'); tile.className = 'dial-tile'; tile.href = item.url;
        const del = mkBtn('dial-del', '×', ev => {{
          ev.preventDefault(); ev.stopPropagation();
          const prev = items.slice();
          safeSetLS(KEY_DIAL, JSON.stringify(items.filter(x => x.id !== item.id))); renderDial();
          notify('Removed ' + (item.name || 'pin') + '.', () => {{ safeSetLS(KEY_DIAL, JSON.stringify(prev)); renderDial(); }});
        }});
        del.setAttribute('aria-label', 'Remove ' + (item.name || item.url));
        tile.append(el('span', 'dial-badge', (item.name || '?').slice(0, 2).toUpperCase()), el('span', 'dial-label', item.name || item.url), del);
        grid.appendChild(tile);
      }});
    }}
    document.getElementById('btnToggleDialForm').addEventListener('click', () => {{ const f = document.getElementById('dialForm'); f.style.display = f.style.display === 'none' ? 'flex' : 'none'; }});
    document.getElementById('dialName').addEventListener('blur', () => {{ document.getElementById('dialNameErr').textContent = document.getElementById('dialName').value.trim() ? '' : 'Enter a short name.'; }});
    document.getElementById('dialUrl').addEventListener('blur', () => {{ const v = document.getElementById('dialUrl').value.trim(); document.getElementById('dialUrlErr').textContent = (!v || normalizeHttpUrl(v)) ? '' : 'Enter a valid domain or https:// URL.'; }});
    document.getElementById('dialForm').addEventListener('submit', e => {{
      e.preventDefault();
      const name = document.getElementById('dialName').value.trim(), url = normalizeHttpUrl(document.getElementById('dialUrl').value);
      document.getElementById('dialNameErr').textContent = name ? '' : 'Enter a short name.';
      document.getElementById('dialUrlErr').textContent = url ? '' : 'Enter a valid domain or https:// URL.';
      if (!name || !url) return;
      const items = getDial(); items.push({{ id: 'd_' + Date.now(), name, url }}); safeSetLS(KEY_DIAL, JSON.stringify(items));
      document.getElementById('dialName').value = ''; document.getElementById('dialUrl').value = ''; document.getElementById('dialForm').style.display = 'none'; renderDial();
    }});

    // === Tasks (luminara_browser:todos + scaleX progress + Undo toast) ===
    function getTodos() {{ try {{ const raw = localStorage.getItem(KEY_TODOS); if (raw) return JSON.parse(raw); }} catch (_e) {{}} return []; }}
    function saveTodos(list) {{ safeSetLS(KEY_TODOS, JSON.stringify(list)); renderTodos(); }}
    function renderTodos() {{
      const list = getTodos(), ratio = list.length ? (list.filter(t => t.done).length / list.length) : 0;
      document.getElementById('todoProgress').style.transform = 'scaleX(' + ratio.toFixed(4) + ')';
      document.getElementById('todoPct').textContent = Math.round(ratio * 100) + '%';
      const box = document.getElementById('todoList'); box.replaceChildren();
      if (!list.length) {{ const e = el('div', 'row-item'); e.appendChild(el('span', '', 'No tasks yet — add one above.')); box.appendChild(e); return; }}
      list.forEach(item => {{
        const row = el('div', 'row-item'), left = el('label'); left.style.cssText = 'display:flex;align-items:center;gap:8px;cursor:pointer;flex:1;min-width:0;';
        const cb = document.createElement('input'); cb.type = 'checkbox'; cb.checked = Boolean(item.done); cb.onchange = () => {{ item.done = cb.checked; saveTodos(list); }};
        left.append(cb, el('span', item.done ? 'todo-done' : '', item.text));
        const right = el('div'); right.style.cssText = 'display:flex;align-items:center;gap:6px;';
        const del = mkBtn('btn subtle', '×', () => {{
          const prev = list.slice();
          saveTodos(list.filter(x => x.id !== item.id));
          notify('Deleted task.', () => saveTodos(prev));
        }});
        del.setAttribute('aria-label', 'Delete task ' + item.text);
        right.append(el('span', 'mono prio-' + (item.prio || 'medium'), (item.prio || 'med').toUpperCase()), del);
        row.append(left, right); box.appendChild(row);
      }});
    }}
    document.getElementById('todoForm').addEventListener('submit', e => {{
      e.preventDefault();
      const inp = document.getElementById('todoInput'), val = inp.value.trim(); if (!val) return;
      const list = getTodos(); list.unshift({{ id: 't_' + Date.now(), text: val, prio: document.getElementById('todoPrio').value, done: false }});
      inp.value = ''; saveTodos(list); notify('Task added.');
    }});

    // === Scheduled Routines (tk.id || tk.task_id, tk.schedule || tk) ===
    async function syncSchedules() {{
      const box = document.getElementById('schedulesList');
      try {{
        const res = await apiFetch('/api/agent/schedules', undefined, AbortSignal.timeout(2500));
        const tasks = (res && (res.tasks || res.schedules)) || []; box.replaceChildren();
        if (!tasks.length) {{ const r = el('div', 'row-item'); r.appendChild(el('span', '', 'No scheduled routines yet.')); box.appendChild(r); return; }}
        tasks.forEach(tk => {{
          const tid = tk.id || tk.task_id || '';
          const sch = tk.schedule || tk;
          const cad = sch.every_min ? (' · every ' + sch.every_min + 'm') : (sch.at ? (' · daily ' + sch.at) : '');
          const row = el('div', 'row-item'), left = el('div'); left.style.cssText = 'display:grid;min-width:0;flex:1;';
          left.append(el('strong', '', (tk.goal || tk.name || tid || 'Routine').slice(0, 56)), el('span', 'mono', (tk.enabled === false ? 'Paused' : 'Active') + cad));
          const runB = mkBtn('btn subtle', 'Run', async () => {{
            runB.disabled = true;
            try {{ await apiFetch('/api/agent/schedule', {{ action: 'run_now', task_id: tid }}); notify('Routine started.'); }}
            catch (err) {{ notify(humanError(err)); }}
            finally {{ runB.disabled = false; }}
          }});
          row.append(left, runB); box.appendChild(row);
        }});
      }} catch (_e) {{ box.replaceChildren(); const r = el('div', 'row-item'); r.appendChild(el('span', '', 'Routines sync when Luminara is connected.')); box.appendChild(r); }}
    }}
    document.getElementById('btnSyncSchedules').addEventListener('click', syncSchedules);

    // === Universal Intent Bar (bot_id + team-research) ===
    const placeholders = {{ auto: 'Search privately ({eng_esc}), open a site, or ask your team...', team: 'Ask your team to summarize, compare tabs, or complete a task...', bulk: 'Paste 2+ URLs or domains (comma or space separated) to compare...' }};
    function setOmniMode(mode) {{
      omniMode = mode || 'auto';
      document.querySelectorAll('.mode-pill').forEach(b => {{
        const on = b.getAttribute('data-mode') === omniMode;
        b.classList.toggle('active', on);
        b.setAttribute('aria-selected', String(on));
      }});
      document.getElementById('omniInput').placeholder = placeholders[omniMode] || placeholders.auto;
    }}
    document.querySelectorAll('.mode-pill').forEach(btn => btn.addEventListener('click', () => setOmniMode(btn.getAttribute('data-mode'))));
    const isLikelyTeamTask = q => /^@(team|pi|remy|dana)\\b/i.test(q) || /^(summarize|compare|find|research|check|extract|plan|draft|explain|analyze|help|watch|book|open and|what |how |why )/i.test(q);
    function showTeamReply(sender, text, receipt, needsSetup) {{
      document.getElementById('teamReplySender').textContent = sender || 'Research Team';
      document.getElementById('teamReplyText').textContent = text || 'Done.';
      document.getElementById('btnReplySetup').style.display = needsSetup ? 'inline-flex' : 'none';
      const det = document.getElementById('teamReplyReceipt');
      if (receipt) {{ det.style.display = 'block'; document.getElementById('teamReplyReceiptSummary').textContent = '✓ Work receipt · ' + (receipt.duration || 'local'); document.getElementById('teamReplyReceiptBody').textContent = receipt.summary || ''; }}
      else det.style.display = 'none';
      document.getElementById('teamReplyCard').classList.add('visible');
    }}
    document.getElementById('btnCloseReply').addEventListener('click', () => document.getElementById('teamReplyCard').classList.remove('visible'));
    document.getElementById('btnReplySetup').addEventListener('click', () => syncOnboarding(true));

    document.getElementById('omniForm').addEventListener('submit', async e => {{
      e.preventDefault();
      const submitBtn = document.getElementById('omniSubmit'), statusEl = document.getElementById('omniStatus');
      if (activeAbort) {{
        activeAbort.abort(); activeAbort = null; apiFetch('/api/agent/act', {{ action: 'human_takeover' }}).catch(() => {{}});
        submitBtn.textContent = 'Go ↵'; submitBtn.classList.replace('stop', 'primary'); statusEl.textContent = 'Stopped. You are in control.'; return;
      }}
      const val = document.getElementById('omniInput').value.trim(); if (!val) return;
      if (omniMode === 'auto') {{
        if (/^(https?:\\/\\/|file:\\/\\/|about:)/i.test(val)) {{ window.location.href = val; return; }}
        if (/^(localhost|127\\.0\\.0\\.1|\\[::1\\])(:\\d+)?(\\/.*)?$/i.test(val) && !val.includes(' ')) {{ window.location.href = 'http://' + val; return; }}
        if (/^[a-z0-9-]+(\\.[a-z0-9-]+)+(:\\d+)?(\\/.*)?$/i.test(val) && !val.includes(' ')) {{ window.location.href = 'https://' + val; return; }}
        if (!isLikelyTeamTask(val)) {{ window.location.href = SEARCH_TPL.replace('{{searchTerms}}', encodeURIComponent(val)); return; }}
      }}
      const runCtrl = new AbortController(); activeAbort = runCtrl;
      submitBtn.textContent = 'STOP ■'; submitBtn.classList.replace('primary', 'stop'); const t0 = Date.now();
      try {{
        if (omniMode === 'bulk') {{
          const urls = val.split(/[\\s,]+/).map(normalizeHttpUrl).filter(Boolean);
          if (!urls.length) throw new Error('Enter one or more valid domains or http(s):// URLs.');
          statusEl.textContent = 'Comparing ' + urls.length + ' page(s) in Live Lens...';
          const data = await apiFetch('/api/agent/bulk', {{ urls, concurrency: 4 }}, runCtrl.signal);
          if (data.generative_ui) safeSetLS(KEY_GENUI, JSON.stringify(data.generative_ui));
          statusEl.textContent = 'Extracted ' + (data.row_count || 0) + ' items — opening Live Lens...';
          setTimeout(() => {{ window.location.href = WORKSPACE_URI + '#view=comparison'; }}, 450);
        }} else {{
          const bm = val.match(/^@(team|pi|remy|dana)\\s+([\\s\\S]+)$/i);
          const rawBot = bm ? bm[1].toLowerCase() : 'team';
          const bot_id = rawBot === 'team' ? 'team-research' : rawBot;
          const prompt = bm ? bm[2].trim() : val;
          statusEl.textContent = 'Asking your team...';
          let data;
          try {{ data = await apiFetch('/api/agent/chat', {{ message: prompt, bot_id, mode: 'execute', include_open_tabs: bot_id === 'team-research' || bot_id === 'remy' }}, runCtrl.signal); }}
          catch (chatErr) {{ if (chatErr && chatErr.status === 404) data = await apiFetch('/api/agent/goal', {{ goal: prompt, show_badges: loadSettings().showHud !== false, agent_id: 'home-team' }}, runCtrl.signal); else throw chatErr; }}
          if (data && data.generative_ui) safeSetLS(KEY_GENUI, JSON.stringify(data.generative_ui));
          const wr = data && data.work_receipt;
          const secs = (wr && typeof wr.duration_ms === 'number') ? (Math.max(0.1, wr.duration_ms / 1000).toFixed(1) + 's') : (Math.max(0.1, (Date.now() - t0) / 1000).toFixed(1) + 's');
          const replyTxt = (data && (data.reply || data.answer || data.message || data.summary)) || (data && data.status === 'PAUSED_HUMAN_HANDOFF' ? 'Paused for your sign-in or confirmation. Check Needs You below.' : 'Task completed.');
          const sumBits = [];
          if (wr && typeof wr.tabs_read === 'number') sumBits.push(wr.tabs_read + ' tab(s) read');
          if (wr && wr.provider) sumBits.push('Provider: ' + wr.provider);
          if (data && data.receipt && data.receipt.summary) sumBits.push(data.receipt.summary);
          showTeamReply((data && data.bot_name) || 'Research Team', replyTxt, {{ duration: secs, summary: sumBits.join(' · ') || 'Verified local action' }}, Boolean(data && data.needs_setup));
          statusEl.textContent = 'Ready · Completed in ' + secs; syncDaemon();
        }}
      }} catch (err) {{ if (err && err.name !== 'AbortError') statusEl.textContent = humanError(err); }}
      finally {{ if (activeAbort === runCtrl) {{ activeAbort = null; submitBtn.textContent = 'Go ↵'; submitBtn.classList.replace('stop', 'primary'); }} }}
    }});

    // === Single-Source Unified Plain-English Inbox (POST /api/agent/inbox) ===
    function renderUnifiedInbox(items) {{
      const sec = document.getElementById('inboxSection'), list = document.getElementById('inboxList');
      list.replaceChildren();
      document.getElementById('handoffBanner').classList.remove('visible');
      document.getElementById('mutationBanner').classList.remove('visible');
      if (!items.length && forceShowInbox) {{
        const okRow = el('div', 'row-item');
        okRow.appendChild(el('span', '', 'All caught up — nothing needs your approval right now.'));
        list.appendChild(okRow);
      }}
      items.forEach(it => {{
        const card = el('article', 'approval-card');
        card.appendChild(el('strong', '', it.title || 'Needs your confirmation'));
        if (it.diff_preview || it.summary) card.appendChild(el('div', '', it.diff_preview || it.summary));
        const why = el('details'); why.style.cssText = 'font-size:12px;color:var(--ink-2);';
        why.append(el('summary', '', 'Why am I asked?'), el('div', 'mono', it.why || it.reason || 'Luminara asks before changing external websites or crossing sign-in walls.'));
        card.appendChild(why);
        const acts = el('div'); acts.style.cssText = 'display:flex;gap:6px;flex-wrap:wrap;';
        const runInbox = async (action, okMsg) => {{
          try {{ await apiFetch('/api/agent/inbox', {{ id: it.id, kind: it.kind, raw_id: it.raw_id, domain: it.domain, action }}, AbortSignal.timeout(35000)); notify(okMsg); syncDaemon(); }}
          catch (err) {{ notify(humanError(err)); }}
        }};
        if (it.kind === 'handoff') {{
          acts.append(mkBtn('btn', 'Dismiss', () => runInbox('deny', 'Dismissed handoff.')), mkBtn('btn primary', 'Resume Agent', () => runInbox('resume', 'Resumed agent.')));
        }} else if (it.kind === 'sequence') {{
          acts.appendChild(mkBtn('btn primary', 'Clear Block', () => runInbox('clear', 'Cleared security pause.')));
        }} else {{
          acts.append(
            mkBtn('btn', 'Deny', () => runInbox('deny', 'Blocked request.')),
            mkBtn('btn primary', 'Allow once', () => runInbox('allow_once', 'Allowed once.')),
            mkBtn('btn', 'Always for site', () => runInbox('allow_site', 'Allowed for ' + (it.domain || 'this site') + '.'))
          );
        }}
        card.appendChild(acts); list.appendChild(card);
      }});
      sec.classList.toggle('visible', items.length > 0 || forceShowInbox);
      document.getElementById('inboxCount').textContent = items.length ? (items.length + ' waiting') : '';
    }}

    async function syncDaemon() {{
      const dot = document.getElementById('daemonDot'), lbl = document.getElementById('daemonLabel'), refreshBtn = document.getElementById('btnRefreshDaemon');
      if (!COBROWSE_ENABLED) {{ dot.classList.add('offline'); lbl.textContent = 'Private Mode'; return; }}
      refreshBtn.disabled = true;
      try {{
        await exchangePassportSession();
        const [st, tb, inboxRes] = await Promise.all([
          apiFetch('/api/agent/status', undefined, AbortSignal.timeout(2200)),
          apiFetch('/api/agent/tabs', undefined, AbortSignal.timeout(2200)),
          apiFetch('/api/agent/inbox', undefined, AbortSignal.timeout(1800)).catch(() => null),
        ]);
        dot.classList.remove('offline'); lbl.textContent = st.cdp_connected ? 'Ready' : 'Standby';
        if (inboxRes && Array.isArray(inboxRes.items)) {{
          activeHandoffRunId = null; activeMutationId = null;
          renderUnifiedInbox(inboxRes.items);
        }} else {{
          const handoffs = st.active_handoffs || [], pendMuts = st.pending_mutations || [];
          activeHandoffRunId = handoffs.length ? handoffs[0].run_id : null;
          activeMutationId = pendMuts.length ? pendMuts[0].mutation_id : null;
          if (activeHandoffRunId) document.getElementById('handoffText').textContent = 'Paused on ' + (handoffs[0].url || 'active tab') + ' for ' + (handoffs[0].gate_type || 'sign-in') + '.';
          if (activeMutationId) document.getElementById('mutationText').textContent = (pendMuts[0].method || 'POST') + ' to ' + (pendMuts[0].url || 'site');
          document.getElementById('handoffBanner').classList.toggle('visible', Boolean(activeHandoffRunId));
          document.getElementById('mutationBanner').classList.toggle('visible', Boolean(activeMutationId));
          document.getElementById('inboxSection').classList.toggle('visible', Boolean(activeHandoffRunId) || Boolean(activeMutationId) || forceShowInbox);
        }}

        const tabs = (tb.tabs || []).filter(t => {{ const u = String(t.url || ''); return !/^(chrome(-extension)?:\\/\\/|devtools:\\/\\/|about:)/i.test(u) && !/\\/(newtab|workspace)(\\.html)?([?#]|$)/i.test(u); }});
        document.getElementById('tabCount').textContent = String(tabs.length);
        const tBox = document.getElementById('liveTabsList'); tBox.replaceChildren();
        if (!tabs.length) {{ const e = el('div', 'row-item'); e.appendChild(el('span', '', 'No web tabs open yet — search or pick a pinned site above.')); tBox.appendChild(e); }}
        else tabs.forEach(t => {{
          const row = el('div', 'row-item'), focusBtn = el('button', 'tab-link'); focusBtn.type = 'button';
          focusBtn.append(el('span', 'tab-title', (t.title || 'Untitled Tab').slice(0, 62)), el('span', 'mono', (t.url || '').slice(0, 70)));
          focusBtn.onclick = async () => {{ try {{ await apiFetch('/api/agent/tabs/focus', {{ target_id: t.target_id }}); }} catch (_e) {{ if (t.url && /^https?:\\/\\//i.test(t.url)) window.open(t.url, '_blank'); }} }};
          const acts = el('div'); acts.style.cssText = 'display:flex;gap:5px;align-items:center;flex-wrap:wrap;';
          if (t.lease) acts.append(el('span', 'mono', 'Working: ' + t.lease.agent_id), mkBtn('btn subtle', 'Take over', async () => {{ await apiFetch('/api/agent/act', {{ action: 'human_takeover', target_id: t.target_id }}).catch(() => {{}}); notify('You took control.'); syncDaemon(); }}));
          const hibBtn = mkBtn('btn subtle', t.frozen ? 'Wake' : 'Sleep', async () => {{
            hibBtn.disabled = true;
            try {{ await apiFetch('/api/agent/hibernate', {{ action: t.frozen ? 'wake' : 'freeze', target_id: t.target_id }}); notify(t.frozen ? 'Tab awakened.' : 'Tab put to sleep.'); syncDaemon(); }}
            catch (err) {{ notify(humanError(err)); }}
            finally {{ hibBtn.disabled = false; }}
          }});
          const clsBtn = mkBtn('btn subtle', '×', async () => {{ clsBtn.disabled = true; try {{ await apiFetch('/api/agent/close', {{ target_id: t.target_id }}); syncDaemon(); }} catch (err) {{ notify(humanError(err)); clsBtn.disabled = false; }} }});
          clsBtn.setAttribute('aria-label', 'Close tab ' + (t.title || ''));
          acts.append(hibBtn, clsBtn); row.append(focusBtn, acts); tBox.appendChild(row);
        }});

        const recs = st.recent_receipts || []; document.getElementById('receiptCount').textContent = recs.length + ' recent';
        const rBox = document.getElementById('receiptsList'); rBox.replaceChildren();
        if (!recs.length) {{ const er = el('div', 'row-item'); er.appendChild(el('span', 'mono', 'No receipts recorded yet.')); rBox.appendChild(er); }}
        else recs.forEach(rc => {{
          const row = el('div', 'row-item'), l = el('div'); l.style.minWidth = '0';
          l.append(el('strong', '', rc.action || ''), document.createTextNode(' · ' + (rc.summary || '')));
          row.append(l, el('span', 'mono', rc.receipt_id || '')); rBox.appendChild(row);
        }});
      }} catch (err) {{
        dot.classList.add('offline');
        lbl.textContent = (err && (err.status === 401 || err.status === 403)) ? 'Auth required' : 'Offline';
        const tBox = document.getElementById('liveTabsList'); tBox.replaceChildren();
        const errRow = el('div', 'row-item'); errRow.append(el('span', '', humanError(err)), mkBtn('btn subtle', 'Retry', syncDaemon)); tBox.appendChild(errRow);
      }} finally {{ refreshBtn.disabled = false; }}
    }}

    document.getElementById('btnCompareLens').addEventListener('click', async e => {{
      const btn = e.currentTarget; btn.disabled = true; btn.textContent = 'Comparing...';
      try {{
        let res;
        try {{ res = await apiFetch('/api/agent/lens/compare', {{}}, AbortSignal.timeout(25000)); }}
        catch (err) {{ if (err && err.status === 404) res = await apiFetch('/api/agent/genui', {{}}, AbortSignal.timeout(25000)); else throw err; }}
        if (res && res.generative_ui) safeSetLS(KEY_GENUI, JSON.stringify(res.generative_ui));
        window.location.href = WORKSPACE_URI + '#view=comparison';
      }} catch (err) {{ notify(humanError(err)); btn.disabled = false; btn.textContent = 'Compare in Live Lens'; }}
    }});

    async function syncVaultAndPlaybooks() {{
      const sumLbl = document.getElementById('vaultSummaryLbl'), vBox = document.getElementById('vaultPlaybookList'), btn = document.getElementById('btnSyncVault');
      btn.disabled = true; sumLbl.textContent = 'Syncing Vault & Playbooks...';
      try {{
        const [vRes, pRes] = await Promise.all([apiFetch('/api/agent/vault'), apiFetch('/api/agent/playbooks')]);
        const entries = vRes.entries || [], pbs = pRes.playbooks || [];
        sumLbl.textContent = entries.length + ' Vault handle(s) · ' + pbs.length + ' Playbook(s)'; vBox.replaceChildren();
        if (!entries.length && !pbs.length) {{ const er = el('div', 'row-item'); er.appendChild(el('span', 'mono', 'No vault handles or learned playbooks yet.')); vBox.appendChild(er); }}
        else {{
          entries.forEach(en => {{
            const r = el('div', 'row-item'), left = el('div'), acts = el('div'); left.style.cssText = 'display:grid;min-width:0;'; acts.style.cssText = 'display:flex;gap:4px;';
            left.append(el('strong', '', en.vault_id || ''), el('span', 'mono', en.origin || ''));
            acts.appendChild(mkBtn('btn subtle', 'Fill', async () => {{ try {{ const res = await apiFetch('/api/agent/vault', {{ action: 'fill', vault_id: en.vault_id }}); notify('Filled ' + ((res.filled_fields || []).join(', ') || 'handle')); }} catch (err) {{ notify(humanError(err)); }} }}));
            if (en.has_totp) acts.appendChild(mkBtn('btn subtle', 'TOTP', async () => {{ try {{ await apiFetch('/api/agent/vault', {{ action: 'enter_totp', vault_id: en.vault_id }}); notify('Entered 6-digit TOTP.'); }} catch (err) {{ notify(humanError(err)); }} }}));
            acts.appendChild(mkBtn('btn subtle', '×', async () => {{ try {{ await apiFetch('/api/agent/vault', {{ action: 'delete', vault_id: en.vault_id }}); syncVaultAndPlaybooks(); }} catch (err) {{ notify(humanError(err)); }} }}));
            r.append(left, acts); vBox.appendChild(r);
          }});
          pbs.forEach(pb => {{
            const r = el('div', 'row-item'), left = el('div'), acts = el('div'); left.style.cssText = 'display:grid;min-width:0;'; acts.style.cssText = 'display:flex;gap:4px;';
            left.append(el('strong', '', pb.domain || 'Playbook'), el('span', 'mono', (pb.goal_example || pb.playbook_id || '') + ' (' + (pb.steps ? pb.steps.length : 0) + ' steps)'));
            acts.append(
              mkBtn('btn subtle', 'Replay', async () => {{ try {{ const res = await apiFetch('/api/agent/playbooks', {{ action: 'replay', playbook_id: pb.playbook_id }}); if (res && res.generative_ui) safeSetLS(KEY_GENUI, JSON.stringify(res.generative_ui)); notify('Playbook ' + (res.status || 'COMPLETED')); }} catch (err) {{ notify(humanError(err)); }} }}),
              mkBtn('btn subtle', '×', async () => {{ try {{ await apiFetch('/api/agent/playbooks', {{ action: 'delete', playbook_id: pb.playbook_id }}); syncVaultAndPlaybooks(); }} catch (err) {{ notify(humanError(err)); }} }})
            );
            r.append(left, acts); vBox.appendChild(r);
          }});
        }}
      }} catch (err) {{ sumLbl.textContent = humanError(err); }}
      finally {{ btn.disabled = false; }}
    }}
    document.getElementById('devDrawer').addEventListener('toggle', e => {{ if (e.currentTarget.open) syncVaultAndPlaybooks(); }});
    document.getElementById('btnSyncVault').addEventListener('click', syncVaultAndPlaybooks);
    document.getElementById('btnToggleVaultForm').addEventListener('click', () => {{ const f = document.getElementById('vaultRegForm'); f.style.display = f.style.display === 'none' ? 'grid' : 'none'; }});
    document.getElementById('vltOrigin').addEventListener('blur', () => {{ const v = document.getElementById('vltOrigin').value.trim(); document.getElementById('vltOriginErr').textContent = (v && !/^https?:\\/\\//i.test(v)) ? 'Origin must start with http:// or https://.' : ''; }});
    document.getElementById('vaultRegForm').addEventListener('submit', async e => {{
      e.preventDefault();
      const origin = document.getElementById('vltOrigin').value.trim(), username = document.getElementById('vltUser').value.trim(), vault_id = document.getElementById('vltId').value.trim() || undefined;
      const password = document.getElementById('vltPass').value, totp_secret = document.getElementById('vltTotp').value.trim();
      if (!/^https?:\\/\\//i.test(origin)) {{ document.getElementById('vltOriginErr').textContent = 'Enter a valid http(s):// origin.'; return; }}
      if (!password && !totp_secret) {{ notify('Provide a password or TOTP secret.'); return; }}
      try {{
        const res = await apiFetch('/api/agent/vault', {{ action: 'register', origin, username, vault_id, password, totp_secret }});
        document.getElementById('vltPass').value = ''; document.getElementById('vltTotp').value = ''; document.getElementById('vaultRegForm').style.display = 'none';
        notify('Sealed handle ' + (res.entry ? res.entry.vault_id : '')); syncVaultAndPlaybooks();
      }} catch (err) {{ notify(humanError(err)); }}
    }});

    document.getElementById('btnResumeHandoff').addEventListener('click', async e => {{
      if (!activeHandoffRunId) return;
      const btn = e.currentTarget; btn.disabled = true; btn.textContent = 'Resuming...';
      try {{ const res = await apiFetch('/api/agent/handoff/resume', {{ run_id: activeHandoffRunId }}, AbortSignal.timeout(35000)); if (res && res.generative_ui) safeSetLS(KEY_GENUI, JSON.stringify(res.generative_ui)); notify('Resumed.'); syncDaemon(); }}
      catch (err) {{ notify(humanError(err)); }}
      finally {{ btn.disabled = false; btn.textContent = 'Resume Agent ↵'; }}
    }});
    async function resolveBannerMutation(decision) {{
      if (!activeMutationId) return;
      try {{ await exchangePassportSession(); await apiFetch('/api/agent/mutations', {{ action: decision, mutation_id: activeMutationId }}); notify(decision === 'approve' ? 'Allowed once.' : 'Blocked request.'); syncDaemon(); }}
      catch (err) {{ notify(humanError(err)); }}
    }}
    document.getElementById('btnApproveMutation').addEventListener('click', () => resolveBannerMutation('approve'));
    document.getElementById('btnRejectMutation').addEventListener('click', () => resolveBannerMutation('reject'));
    document.getElementById('btnRefreshDaemon').addEventListener('click', syncDaemon);
    document.getElementById('btnCopyMcp').addEventListener('click', async () => {{ try {{ await navigator.clipboard.writeText(DAEMON + '/api/agent/mcp'); notify('Copied MCP endpoint.'); }} catch (_e) {{ notify('MCP endpoint: ' + DAEMON + '/api/agent/mcp'); }} }});
    document.getElementById('btnOpenPalette').addEventListener('click', () => {{ if (typeof window.__luminaraOpenPalette === 'function') window.__luminaraOpenPalette(); }});

    // Arrow-key roving navigation on tablists & radiogroups
    document.querySelectorAll('[role="tablist"], [role="radiogroup"]').forEach(grp => {{
      const kids = Array.from(grp.querySelectorAll('[role="tab"], [role="radio"]'));
      kids.forEach((k, idx) => k.addEventListener('keydown', e => {{
        if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
        e.preventDefault();
        const nxt = kids[(idx + (e.key === 'ArrowRight' ? 1 : kids.length - 1)) % kids.length];
        nxt.focus(); nxt.click();
      }}));
    }});

    function openLuminara3DEmblem() {{
      if (!__lum3dBooted) {{
        __lum3dBooted = true;
        try {{ sessionStorage.setItem('luminara_splash_seen', '1'); }} catch (_e) {{}}
        (function() {{
{logo_3d_js}
        }})();
      }}
      if (window.__luminaraLogo3D && window.__luminaraLogo3D.openSplash !== openLuminara3DEmblem) window.__luminaraLogo3D.openSplash();
    }}
    window.__luminaraLogo3D = {{
      openSplash: openLuminara3DEmblem,
      closeSplash: () => {{ const sp = document.getElementById('luminaraSplash'); if (sp) sp.classList.add('hidden'); }}
    }};
    document.getElementById('btnReplayIntro').addEventListener('click', openLuminara3DEmblem, {{ once: true }});

    function handleHashRoute(hashStr) {{
      const h = hashStr || '';
      const askMatch = h.match(/(?:^#|&)ask=([^&]+)/);
      if (askMatch) {{
        const q = decodeURIComponent(askMatch[1]), inp = document.getElementById('omniInput');
        if (inp && q) {{ inp.value = q; setOmniMode('team'); document.getElementById('omniForm').requestSubmit(); }}
        return;
      }}
      if (/(?:^#|&)inbox(?:$|&)/i.test(h)) {{
        forceShowInbox = true;
        document.getElementById('inboxSection').classList.add('visible');
        document.getElementById('inboxSection').scrollIntoView({{ behavior: 'smooth', block: 'start' }});
        syncDaemon();
      }} else if (/(?:^#|&)routines(?:$|&)/i.test(h)) {{
        document.getElementById('routinesSection').scrollIntoView({{ behavior: 'smooth', block: 'start' }});
      }} else if (/(?:^#|&)setup(?:$|&)/i.test(h)) {{
        syncOnboarding(true);
        document.getElementById('onboardingCard').scrollIntoView({{ behavior: 'smooth', block: 'start' }});
      }}
    }}
    window.addEventListener('hashchange', () => handleHashRoute(location.hash));

    applySettings(); syncProviderFields(); renderDial(); renderTodos(); syncOnboarding(false); syncDaemon(); syncSchedules();
    handleHashRoute(INITIAL_HASH);
    if (COBROWSE_ENABLED) setInterval(syncDaemon, 5000);
    const updateClock = () => {{ document.getElementById('clock').textContent = new Date().toLocaleTimeString([], {{ hour: '2-digit', minute: '2-digit' }}); }};
    updateClock(); setInterval(updateClock, 15000);
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
