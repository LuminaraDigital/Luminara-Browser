/**
 * Luminara Browser v4.0.0 — Cloudflare Edge Worker & Agent Discovery Router
 * Serves /api/health, /api/mcp-spec, /.well-known/agent.json, /llms.txt, /llms-full.txt, /robots.txt,
 * and static Warm Atelier Precision portal assets with strict security headers.
 */

const MCP_PROTOCOL_VERSION = "2025-06-18";

const MCP_TOOLS = [
  "browser_list_tabs",
  "browser_open_tab",
  "browser_close_tab",
  "browser_snapshot",
  "browser_act",
  "browser_extract_structured",
  "browser_generative_ui",
  "browser_run_goal",
  "browser_bulk_extract",
  "browser_handoff_resume",
  "browser_dialog",
  "browser_vault",
  "browser_exec_pipeline",
  "browser_playbooks",
  "browser_perception_axtree",
  "webmcp_list_tools",
  "webmcp_call_tool",
  "browser_mutation_guard",
  "browser_workspace",
  "browser_hibernate_tabs",
  "browser_outline",
  "browser_wait",
  "browser_screenshot",
  "browser_schedule",
  "browser_sequence_guard",
  "browser_vrt_isolation",
  "browser_monitors",
  "browser_search_eval",
];

const MCP_RESOURCES = [
  "luminara://tabs/live",
  "luminara://ledger/recent",
  "luminara://ledger/verify",
  "luminara://vault/entries",
  "luminara://playbooks/list",
  "luminara://workspaces/list",
  "luminara://mutations/status",
  "luminara://security/sequences",
  "luminara://monitors/runs",
];

const V4_TEAM_HUB_ENDPOINTS = [
  "/api/agent/llm/config",
  "/api/agent/llm/ollama",
  "/api/agent/teams",
  "/api/agent/chat",
  "/api/agent/inbox",
  "/api/agent/teach",
  "/api/agent/tabs/focus",
  "/api/agent/lens/compare",
];

const DESKTOP_LIFECYCLE_ENDPOINTS = [
  "/api/agent/desktop/status",
  "/api/agent/desktop/takeover",
  "/api/agent/shutdown",
];

const BUILTIN_BOTS = [
  { id: "pi", name: "Pi", role: "General Assistant" },
  { id: "remy", name: "Remy", role: "Web Researcher" },
  { id: "dana", name: "Dana", role: "Data & Memory Analyst" },
  { id: "team-research", name: "Research Team", role: "Multi-Bot Coordinator" },
];

function withSecurityHeaders(res, extra = {}) {
  const headers = new Headers(res.headers);
  headers.set(
    "Content-Security-Policy",
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
  );
  headers.set("X-Content-Type-Options", "nosniff");
  headers.set("X-Frame-Options", "DENY");
  headers.set("Strict-Transport-Security", "max-age=63072000; includeSubDomains; preload");
  headers.set("Referrer-Policy", "strict-origin-when-cross-origin");
  headers.set(
    "Permissions-Policy",
    "accelerometer=(), camera=(), geolocation=(), gyroscope=(), microphone=(), payment=(), usb=()"
  );
  for (const [k, v] of Object.entries(extra)) {
    headers.set(k, v);
  }
  return new Response(res.body, {
    status: res.status,
    statusText: res.statusText,
    headers,
  });
}

function jsonResponse(payload, status = 200, extraHeaders = {}) {
  const raw = JSON.stringify(payload, null, 2);
  return withSecurityHeaders(
    new Response(raw, {
      status,
      headers: {
        "Content-Type": "application/json; charset=utf-8",
        "Content-Length": String(new TextEncoder().encode(raw).byteLength),
      },
    }),
    extraHeaders
  );
}

function textResponse(body, contentType = "text/plain; charset=utf-8", status = 200, extraHeaders = {}) {
  return withSecurityHeaders(
    new Response(body, {
      status,
      headers: {
        "Content-Type": contentType,
        "Content-Length": String(new TextEncoder().encode(body).byteLength),
      },
    }),
    extraHeaders
  );
}

export default {
  async fetch(request, env) {
    const res = await this._route(request, env);
    if (request.method === "HEAD" && res.body !== null) {
      return new Response(null, { status: res.status, statusText: res.statusText, headers: res.headers });
    }
    return res;
  },

  async _route(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;
    const version = env.APP_VERSION || "4.0.0";
    const chromiumPatchTrack = env.CHROMIUM_BASE || "157.0.8103.78-1.1";
    const portableBinaryBase = env.PORTABLE_BINARY_BASE || "157.0.8103.50-1.1";
    const repo = env.GITHUB_REPO || "https://github.com/LuminaraDigital/Luminara-Browser";
    const localMcp = env.LOCAL_MCP_ENDPOINT || "http://127.0.0.1:8796/api/agent/mcp";

    if (request.method === "OPTIONS") {
      return withSecurityHeaders(new Response(null, { status: 204 }), {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Accept",
        "Access-Control-Max-Age": "86400",
      });
    }

    if (request.method !== "GET" && request.method !== "HEAD") {
      return jsonResponse({ error: "method_not_allowed" }, 405, { Allow: "GET, HEAD, OPTIONS" });
    }

    if (path === "/favicon.ico") {
      if (env.ASSETS && typeof env.ASSETS.fetch === "function") {
        const iconReq = new Request(new URL("/icon48.png", url.origin), { method: request.method });
        const iconRes = await env.ASSETS.fetch(iconReq);
        if (iconRes.ok) {
          return withSecurityHeaders(iconRes, { "Cache-Control": "public, max-age=86400" });
        }
      }
      return jsonResponse({ error: "Not found", path }, 404);
    }

    if (path === "/api/health") {
      return jsonResponse(
        {
          status: "ok",
          service: "luminara-browser-edge",
          version,
          chromium_base: chromiumPatchTrack,
          chromium_patch_track: chromiumPatchTrack,
          portable_binary_base: portableBinaryBase,
          mcp_tool_count: MCP_TOOLS.length,
          mcp_resource_count: MCP_RESOURCES.length,
          team_hub_endpoint_count: V4_TEAM_HUB_ENDPOINTS.length,
          builtin_bot_count: BUILTIN_BOTS.length,
          v4_desktop_shell: "Launch-Luminara-v4.cmd",
          desktop_host: "LuminaraBrowser.exe",
          app_user_model_id: "Luminara.Browser.Desktop",
          install_modes: ["v4-desktop-shell", "portable", "per-user-hkcu"],
          colo: request.cf?.colo || "local",
          ts: new Date().toISOString(),
        },
        200,
        { "Access-Control-Allow-Origin": "*" }
      );
    }

    if (path === "/api/mcp-spec") {
      return jsonResponse(
        {
          protocolVersion: MCP_PROTOCOL_VERSION,
          version,
          chromium_patch_track: chromiumPatchTrack,
          portable_binary_base: portableBinaryBase,
          local_endpoint: localMcp,
          cdp_target: "http://127.0.0.1:9229",
          v4_desktop_shell: "Launch-Luminara-v4.cmd",
          desktop_host: "LuminaraBrowser.exe",
          app_user_model_id: "Luminara.Browser.Desktop",
          desktop_lifecycle_endpoints: DESKTOP_LIFECYCLE_ENDPOINTS,
          v4_team_hub_endpoints: V4_TEAM_HUB_ENDPOINTS,
          builtin_bots: BUILTIN_BOTS,
          hitl_handoff_state: "PAUSED_HUMAN_HANDOFF",
          untrusted_dom_fencing: "<untrusted_page_data>",
          receipt_format: "LUM-<unix_ms>-<sha256[:10]>",
          receipt_signature_scheme: "LUM-SIG-V2 (lum-hmac256)",
          tools: MCP_TOOLS,
          resources: MCP_RESOURCES,
        },
        200,
        { "Access-Control-Allow-Origin": "*" }
      );
    }

    if (path === "/.well-known/agent.json") {
      return jsonResponse(
        {
          name: "Luminara Browser",
          slug: "luminara-browser",
          version,
          chromium_base: chromiumPatchTrack,
          chromium_patch_track: chromiumPatchTrack,
          portable_binary_base: portableBinaryBase,
          repository: repo,
          v4_desktop_shell: "Launch-Luminara-v4.cmd",
          desktop_host: "LuminaraBrowser.exe",
          app_user_model_id: "Luminara.Browser.Desktop",
          install_modes: ["v4-desktop-shell", "portable", "per-user-hkcu"],
          local_daemon: "http://127.0.0.1:8796",
          mcp_endpoint: localMcp,
          mcp_protocol_version: MCP_PROTOCOL_VERSION,
          desktop_lifecycle_endpoints: DESKTOP_LIFECYCLE_ENDPOINTS,
          v4_team_hub_endpoints: V4_TEAM_HUB_ENDPOINTS,
          builtin_bots: BUILTIN_BOTS,
          auth_scheme: "Loopback Host+UI-Key + Optional Bearer LUMINARA_AGENT_TOKEN",
          hitl_handoff_state: "PAUSED_HUMAN_HANDOFF",
          receipt_prefix: "LUM-",
          receipt_signature_scheme: "LUM-SIG-V2 (lum-hmac256)",
          tools: MCP_TOOLS,
          resources: MCP_RESOURCES,
        },
        200,
        { "Access-Control-Allow-Origin": "*" }
      );
    }

    if (path === "/llms.txt" || path === "/llms-full.txt") {
      const baseDoc = [
        `# Luminara Browser v${version}`,
        `> Privacy-hardened Ungoogled-Chromium (patch track ${chromiumPatchTrack} · portable binary base ${portableBinaryBase}) fused with the Luminara v4 Warm Atelier Native Desktop Shell (\`Launch-Luminara-v4.cmd\`) and PiBot Multi-Bot Teams for simultaneous Human + AI Agent co-browsing via Multiplexed Loopback CDP (:9229) and ${MCP_TOOLS.length}-Tool MCP v2 (:8796).`,
        "",
        "## Core Capabilities",
        "- Warm Atelier Precision v4 Native Desktop Shell (`Launch-Luminara-v4.cmd` / `luminara-shell/`): 3-Zone Spatial OS with adaptive Light/Dark modes, 60/120fps `WebContentsView` tabs, working private omnibox, interactive Privacy Shield, and isolated Spaces.",
        "- PiBot Multi-Bot Teams & Team Hub (`forge/agent_team_hub.py`): Built-in `Pi` (General Assistant), `Remy` (Web Researcher), `Dana` (Data & Memory Analyst), and `Research Team` coordinator with encrypted local LLM config (Ollama, OpenRouter, Gemini, Anthropic, OpenAI, Custom), Approval Inbox, Teach Recorder, and Cross-Tab Live Lens.",
        "- Zero Google Telemetry & Interactive Privacy Shield v3: `.void0` domain trap + `trk:` protocol sink + 30k DNR tracker rules + query-param stripping + eTLD+1 deterministic farbling.",
        "- Simultaneous Co-Browsing: Humans and MCP v2 AI agents share live tabs via `TabLeaseManager` + `MultiplexedCDPPool` (`<1.5ms` RTT) with 1-click Human Takeover.",
        "- Hybrid Perception & Iframe/Dialog Supervision: Blink `AXTree` + Shadow-DOM + OOPIF traversal + Set-of-Marks `[1..N]` indexing + stable `[ref=eN]` outline + non-blocking JS Dialog Supervisor.",
        "- Origin-Pinned DPAPI/AEAD Model-Blind Vault: Injects credentials & RFC 6238 TOTP codes over loopback CDP after synchronous origin verification without exposing secrets to prompts or logs.",
        "- Zero-Context AST Pipeline Sandbox & Self-Improving CAS Playbooks: Multi-step Python/declarative pipelines in 1 turn + zero-LLM replay + `expected_revision` rollback.",
        "- W3C WebMCP, Numbat Sequence Guard & Hermetic VRT: Structured `navigator.modelContext` tools + `Fetch.enable` savepoint approval + multi-step exfil chain blocking (`CASE-*.zip`) + declared-origin PNG visual regression.",
        "- Fenced Web Monitors, Multi-Provider Search Eval & SQLite FTS5 Workspaces: `lease_epoch` monitors, exact `Decimal` CostLedger, `4.5x+` parallel throughput, tab hibernation, and 50-slot Undo/Redo.",
        "- Cryptographic Accountability & Binary-Safe Redaction: Hash-chained + HMAC-signed `LUM-*` receipts (`/api/agent/ledger/verify`) scrubbed via `LuminaraRedactor`.",
        "- Native Win32 Desktop Host (`LuminaraBrowser.exe`): Zero-console Rust GUI supervisor (`Luminara.Browser.Desktop`), Win32 Job-Object orphan-free lifecycle, System Tray takeover/firewall alerts, SDDL-locked Named Pipe single-instance routing, and zero-UAC per-user Windows installer (`%LOCALAPPDATA%\\Programs\\Luminara Browser`).",
        "",
        "## Quickstart & Endpoints",
        `- Repository & Releases: ${repo}`,
        "- Luminara v4 Desktop Shell: `Launch-Luminara-v4.cmd` (`luminara-shell/`)",
        "- Portable / Per-User Chromium Host: `LuminaraBrowser.exe` / `Launch-Luminara-Browser.cmd`",
        `- Local MCP v2 JSON-RPC (${MCP_PROTOCOL_VERSION}): POST ${localMcp}`,
        "- Local v4 Team Hub REST: " + V4_TEAM_HUB_ENDPOINTS.join(" · "),
        "- Local Desktop Heartbeat & Human Takeover: GET /api/agent/desktop/status · POST /api/agent/desktop/takeover · POST /api/agent/shutdown",
        "- Local Forge Studio: http://127.0.0.1:8795",
        "- Edge Agent Manifest: /.well-known/agent.json",
        "- Edge MCP Spec: /api/mcp-spec",
      ];
      if (path === "/llms-full.txt") {
        baseDoc.push(
          "",
          `## PiBot Built-in Multi-Bot Teams (${BUILTIN_BOTS.length})`,
          ...BUILTIN_BOTS.map((b) => `- \`${b.id}\` (${b.name}): ${b.role}`),
          "",
          `## v4 Team Hub REST Endpoints (${V4_TEAM_HUB_ENDPOINTS.length})`,
          ...V4_TEAM_HUB_ENDPOINTS.map((ep) => `- \`${ep}\``),
          "",
          `## MCP v2 Tool Inventory (${MCP_TOOLS.length} Tools)`,
          ...MCP_TOOLS.map((t) => `- \`${t}\``),
          "",
          `## MCP v2 Resource Inventory (${MCP_RESOURCES.length} Resources)`,
          ...MCP_RESOURCES.map((r) => `- \`${r}\``),
          "",
          "## CLI Commands",
          "- `Launch-Luminara-v4.cmd` (Start Luminara v4 Native Spatial Desktop Shell)",
          "- `luminara-forge build-portable`",
          "- `luminara-forge build-desktop`",
          "- `luminara-forge install-desktop`",
          "- `luminara-forge uninstall-desktop`",
          "- `luminara-forge desktop-status`",
          "- `luminara-forge agent-daemon --port 8796 --cdp-port 9229`",
          "- `luminara-forge verify-arch` (SPACE + Codescythe Architecture Ratchet)",
          "- `luminara-forge verify-upstream-patches` (Zero-fuzz C++ patch gate)",
          "- `luminara-forge verify-rea` (21/21 REA Reconstruction Gate)",
          "- `luminara-forge benchmark` (AB-01..AB-08 Live A/B Suite)",
          "- `luminara-forge benchmark-100x` (BM-01..BM-06 100x Engine Suite)"
        );
      }
      return textResponse(baseDoc.join("\n") + "\n", "text/markdown; charset=utf-8", 200, {
        "Access-Control-Allow-Origin": "*",
      });
    }

    if (path === "/sitemap.xml") {
      const xml = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
        `  <url><loc>${url.origin}/</loc></url>`,
        `  <url><loc>${url.origin}/llms.txt</loc></url>`,
        `  <url><loc>${url.origin}/llms-full.txt</loc></url>`,
        "</urlset>",
      ].join("\n");
      return textResponse(xml, "application/xml; charset=utf-8");
    }

    if (path === "/robots.txt") {
      const robots = [
        "User-agent: *",
        "Allow: /",
        "",
        "User-agent: GPTBot",
        "Allow: /",
        "",
        "User-agent: ClaudeBot",
        "Allow: /",
        "",
        "User-agent: PerplexityBot",
        "Allow: /",
        "",
        "User-agent: Bytespider",
        "Disallow: /",
        "",
        `Sitemap: ${url.origin}/sitemap.xml`,
        "",
      ].join("\n");
      return textResponse(robots);
    }

    // Never fall through to SPA index.html for unknown /api/* endpoints
    if (path.startsWith("/api/")) {
      return jsonResponse({ error: "Not found", path }, 404);
    }

    if (env.ASSETS && typeof env.ASSETS.fetch === "function") {
      const assetRes = await env.ASSETS.fetch(request);
      if (assetRes.status === 404) {
        return jsonResponse({ error: "Not found", path }, 404);
      }
      return withSecurityHeaders(assetRes);
    }

    return jsonResponse({ error: "Not found" }, 404);
  },
};
