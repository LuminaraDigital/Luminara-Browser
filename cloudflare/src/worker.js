/**
 * Luminara Browser — Cloudflare Edge Worker & Agent Discovery Router
 * Serves /api/health, /api/mcp-spec, /.well-known/agent.json, /llms.txt, /llms-full.txt, /robots.txt,
 * and static Precision Dark portal assets with strict security headers.
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
];

function withSecurityHeaders(res, extra = {}) {
  const headers = new Headers(res.headers);
  headers.set(
    "Content-Security-Policy",
    "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self' http://127.0.0.1:8796 http://localhost:8796; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
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
  return withSecurityHeaders(
    new Response(JSON.stringify(payload, null, 2), {
      status,
      headers: { "Content-Type": "application/json; charset=utf-8" },
    }),
    extraHeaders
  );
}

function textResponse(body, contentType = "text/plain; charset=utf-8", status = 200, extraHeaders = {}) {
  return withSecurityHeaders(
    new Response(body, {
      status,
      headers: { "Content-Type": contentType },
    }),
    extraHeaders
  );
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;
    const version = env.APP_VERSION || "2.1.0";
    const chromiumBase = env.CHROMIUM_BASE || "157.0.8103.78-1.1";
    const repo = env.GITHUB_REPO || "https://github.com/luminara-digital/luminara-browser";
    const localMcp = env.LOCAL_MCP_ENDPOINT || "http://127.0.0.1:8796/api/agent/mcp";

    if (request.method === "OPTIONS") {
      return withSecurityHeaders(new Response(null, { status: 204 }), {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, OPTIONS",
      });
    }

    if (path === "/api/health") {
      return jsonResponse({
        status: "ok",
        service: "luminara-browser-edge",
        version,
        chromium_base: chromiumBase,
        colo: request.cf?.colo || "local",
        ts: new Date().toISOString(),
      });
    }

    if (path === "/api/mcp-spec") {
      return jsonResponse(
        {
          protocolVersion: MCP_PROTOCOL_VERSION,
          local_endpoint: localMcp,
          cdp_target: "http://127.0.0.1:9229",
          hitl_handoff_state: "PAUSED_HUMAN_HANDOFF",
          untrusted_dom_fencing: "<untrusted_page_data>",
          receipt_format: "LUM-<unix_ms>-<sha256[:10]>",
          tools: MCP_TOOLS,
          resources: [
            "luminara://tabs/live",
            "luminara://ledger/recent",
            "luminara://ledger/verify",
          ],
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
          chromium_base: chromiumBase,
          repository: repo,
          local_daemon: "http://127.0.0.1:8796",
          mcp_endpoint: localMcp,
          mcp_protocol_version: MCP_PROTOCOL_VERSION,
          auth_scheme: "Loopback Host+UI-Key + Optional Bearer LUMINARA_AGENT_TOKEN",
          hitl_handoff_state: "PAUSED_HUMAN_HANDOFF",
          receipt_prefix: "LUM-",
          tools: MCP_TOOLS,
        },
        200,
        { "Access-Control-Allow-Origin": "*" }
      );
    }

    if (path === "/llms.txt" || path === "/llms-full.txt") {
      const baseDoc = [
        "# Luminara Browser",
        `> Privacy-hardened Ungoogled-Chromium ${chromiumBase} desktop browser built for simultaneous Human + AI Agent co-browsing via Loopback CDP (:9229) and MCP v2 (:8796).`,
        "",
        "## Core Capabilities",
        "- Zero Google Telemetry: `.void0` domain substitution + `trk:` protocol sink + fingerprint noise.",
        "- Simultaneous Co-Browsing: Humans and external AI agents (Claude Code, Antigravity, Hermes, Cursor) share live tabs via `TabLeaseManager` with 1-click Human Takeover.",
        "- Set-of-Marks `[1..N]` DOM Indexing: Deterministic CSS selectors + `<untrusted_page_data>` prompt-injection fencing (`96.7%` token reduction).",
        "- Parallel BulkEngine & Generative UI Studio: Per-domain adaptive concurrency (`4.5x+` speedup), sortable comparison matrices, and 50-slot Undo/Redo.",
        "- Safe HITL Co-Browsing: Login, 2FA, payment, and verification walls pause cleanly (`PAUSED_HUMAN_HANDOFF`) for human completion.",
        "- Cryptographic Accountability: Hash-chained SHA-256 `LUM-*` action receipts (`/api/agent/ledger/verify`).",
        "",
        "## Quickstart & Endpoints",
        `- Repository & Releases: ${repo}`,
        `- Local MCP v2 JSON-RPC (${MCP_PROTOCOL_VERSION}): POST ${localMcp}`,
        "- Local Forge Studio: http://127.0.0.1:8795",
        "- Edge Agent Manifest: /.well-known/agent.json",
        "- Edge MCP Spec: /api/mcp-spec",
      ];
      if (path === "/llms-full.txt") {
        baseDoc.push(
          "",
          "## MCP v2 Tool Inventory",
          ...MCP_TOOLS.map((t) => `- \`${t}\``),
          "",
          "## CLI Commands",
          "- `luminara-forge build-portable`",
          "- `luminara-forge agent-daemon --port 8796 --cdp-port 9229`",
          "- `luminara-forge verify-rea` (14/14 REA Reconstruction Gate)",
          "- `luminara-forge benchmark` (AB-01..AB-04 Live Benchmark Suite)"
        );
      }
      return textResponse(baseDoc.join("\n") + "\n", "text/markdown; charset=utf-8", 200, {
        "Access-Control-Allow-Origin": "*",
      });
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
        `Sitemap: ${url.origin}/llms.txt`,
        "",
      ].join("\n");
      return textResponse(robots);
    }

    if (env.ASSETS && typeof env.ASSETS.fetch === "function") {
      const assetRes = await env.ASSETS.fetch(request);
      return withSecurityHeaders(assetRes);
    }

    return jsonResponse({ error: "Not found" }, 404);
  },
};
