# Luminara Browser MCP v2 & v4 Team Hub Protocol Reference (`2025-06-18` · `v4.0.0`)

Endpoint: `POST http://127.0.0.1:8796/api/agent/mcp`  
Content-Type: `application/json`  
Optional Auth Header (when `LUMINARA_AGENT_TOKEN` is configured): `Authorization: Bearer <token>`  
Human-Only Mutations Header (`llm/config`, `inbox`, `teach` start/stop, `desktop/takeover`, `shutdown`): `X-Luminara-UI-Key: <local_ui_key>`

## 1. Initialize Handshake

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "initialize",
  "params": {}
}
```

## 2. Call `browser_snapshot` (Set-of-Marks `[1..N]` Across Main Doc & Frames)

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/call",
  "params": {
    "name": "browser_snapshot",
    "arguments": {
      "show_badges": true,
      "include_frames": true,
      "agent_id": "luminara-agent"
    }
  }
}
```

## 3. Call `browser_dialog` (Native JS Dialog Supervisor)

```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "tools/call",
  "params": {
    "name": "browser_dialog",
    "arguments": {
      "action": "accept",
      "prompt_text": "confirmed"
    }
  }
}
```

## 4. Call `browser_vault` (Origin-Pinned Model-Blind Fill + RFC 6238 TOTP)

```json
{
  "jsonrpc": "2.0",
  "id": 4,
  "method": "tools/call",
  "params": {
    "name": "browser_vault",
    "arguments": {
      "action": "fill",
      "vault_id": "portal_prod",
      "agent_id": "luminara-agent"
    }
  }
}
```

## 5. Call `browser_exec_pipeline` (Single-Turn AST-Sandboxed Workflow)

```json
{
  "jsonrpc": "2.0",
  "id": 5,
  "method": "tools/call",
  "params": {
    "name": "browser_exec_pipeline",
    "arguments": {
      "script": "s = luminara.snapshot(include_frames=True)\next = luminara.extract(fmt='json')\nluminara.emit({'elements': len(s['snapshot']['elements']), 'rows': len(ext['extracted']['rows'])})",
      "max_calls": 10
    }
  }
}
```

## 6. Call `browser_playbooks` (Zero-LLM Domain Playbook Replay)

```json
{
  "jsonrpc": "2.0",
  "id": 6,
  "method": "tools/call",
  "params": {
    "name": "browser_playbooks",
    "arguments": {
      "action": "replay",
      "goal": "Export monthly billing CSV",
      "agent_id": "luminara-agent"
    }
  }
}
```

## 7. Call `browser_perception_axtree` (Blink AXTree + Shadow-DOM + Compositor Input)

```json
{
  "jsonrpc": "2.0",
  "id": 7,
  "method": "tools/call",
  "params": {
    "name": "browser_perception_axtree",
    "arguments": {
      "action": "snapshot"
    }
  }
}
```

## 8. Call `webmcp_list_tools` & `webmcp_call_tool` (W3C WebMCP `navigator.modelContext`)

```json
{
  "jsonrpc": "2.0",
  "id": 8,
  "method": "tools/call",
  "params": {
    "name": "webmcp_list_tools",
    "arguments": {}
  }
}
```

```json
{
  "jsonrpc": "2.0",
  "id": 9,
  "method": "tools/call",
  "params": {
    "name": "webmcp_call_tool",
    "arguments": {
      "tool_name": "search_flights",
      "arguments": { "origin": "SYD", "dest": "SFO" }
    }
  }
}
```

## 9. Call `browser_mutation_guard` (Network Mutation Firewall Savepoints)

```json
{
  "jsonrpc": "2.0",
  "id": 10,
  "method": "tools/call",
  "params": {
    "name": "browser_mutation_guard",
    "arguments": {
      "action": "enable",
      "url_pattern": "*"
    }
  }
}
```

## 10. Call `browser_workspace` & `browser_hibernate_tabs` (FTS5 Knowledge & Tab Freeze)

```json
{
  "jsonrpc": "2.0",
  "id": 11,
  "method": "tools/call",
  "params": {
    "name": "browser_workspace",
    "arguments": {
      "action": "search",
      "workspace_id": "research",
      "query": "GPU 24GB"
    }
  }
}
```

```json
{
  "jsonrpc": "2.0",
  "id": 12,
  "method": "tools/call",
  "params": {
    "name": "browser_hibernate_tabs",
    "arguments": {
      "action": "hibernate",
      "min_idle_sec": 60,
      "dry_run": true
    }
  }
}
```

## 11. Call `browser_bulk_extract` (Parallel Per-Domain Multi-Tab Scrape)

```json
{
  "jsonrpc": "2.0",
  "id": 13,
  "method": "tools/call",
  "params": {
    "name": "browser_bulk_extract",
    "arguments": {
      "urls": ["https://example.com", "https://www.iana.org/domains/reserved"],
      "concurrency": 4,
      "format": "md",
      "workspace_id": "research"
    }
  }
}
```

## 12. Call `browser_sequence_guard`, `browser_vrt_isolation`, `browser_monitors` & `browser_search_eval`

```json
{
  "jsonrpc": "2.0",
  "id": 14,
  "method": "tools/call",
  "params": {
    "name": "browser_sequence_guard",
    "arguments": { "action": "export_casebundle" }
  }
}
```

```json
{
  "jsonrpc": "2.0",
  "id": 15,
  "method": "tools/call",
  "params": {
    "name": "browser_vrt_isolation",
    "arguments": {
      "action": "lock_origins",
      "declared_origins": ["https://app.example.org"]
    }
  }
}
```

```json
{
  "jsonrpc": "2.0",
  "id": 16,
  "method": "tools/call",
  "params": {
    "name": "browser_monitors",
    "arguments": {
      "action": "create",
      "name": "Pricing Watch",
      "target_url": "https://example.org/pricing",
      "extract_selector": "body"
    }
  }
}
```

```json
{
  "jsonrpc": "2.0",
  "id": 17,
  "method": "tools/call",
  "params": {
    "name": "browser_search_eval",
    "arguments": {
      "action": "run_suite",
      "suite": "extraction",
      "providers": ["luminara", "perplexity"]
    }
  }
}
```

## 13. Read MCP v2 Resources (`luminara://*`)

Available URIs:
- `luminara://tabs/live`
- `luminara://ledger/recent`
- `luminara://ledger/verify`
- `luminara://vault/entries`
- `luminara://playbooks/list`
- `luminara://workspaces/list`
- `luminara://mutations/status`
- `luminara://security/sequences`
- `luminara://monitors/runs`

```json
{
  "jsonrpc": "2.0",
  "id": 18,
  "method": "resources/read",
  "params": {
    "uri": "luminara://ledger/verify"
  }
}
```

## 14. Luminara v4 Team Hub REST Endpoints (`127.0.0.1:8796`)

Backed by `forge/agent_team_hub.py` and wired into the redesigned Chromium Calm Home / `Alt+L` Team Side Panel / `Alt+K` Command Palette (`LuminaraBrowser.exe` / `Launch-Luminara-Browser.cmd`) and `luminara_ctl.py` (while `Launch-Luminara-v4.cmd` provides the standalone Electron 35 `luminara-shell/` desktop shell with its own native `WebContentsView` + IPC runtime):

- `GET /api/agent/llm/config?probe=1|0` — Returns public LLM configuration summary (`provider`, `model`, `base_url`, `has_api_key`, `masked_key`, `ollama`, `configured`; zero plaintext keys).
- `POST /api/agent/llm/config` *(Human-only: requires `X-Luminara-UI-Key`)* — Seals provider/model/base_url/API key via HKDF+CTR+HMAC AEAD (`outputs/llm_config.json`) or clears stored key (`clear_api_key: true`). Supported providers: `ollama`, `openrouter`, `gemini`, `anthropic`, `openai`, `custom`.
- `GET /api/agent/llm/ollama?base_url=http://127.0.0.1:11434` — Probes a local Ollama daemon (`/api/tags`) and returns `{running, models}`.
- `GET /api/agent/teams` — Lists built-in PiBot Multi-Bot Teams (`pi`, `remy`, `dana`, `team-research`).
- `POST /api/agent/chat` — Sends a live-tab-grounded prompt to a named bot (`bot_id`, `message`, `mode: "execute"|"plan"`, `target_id`, `include_open_tabs`). Wraps untrusted DOM inside `<<LUMINARA_UNTRUSTED_PAGE>>` fences, falls back gracefully when no LLM is configured, and emits a signed `LUM-*` receipt.
- `GET /api/agent/inbox` — Aggregates pending Network Mutation Firewall savepoints (`mut:*`), `PAUSED_HUMAN_HANDOFF` runs (`handoff:*`), and `PAUSED_SEQUENCE_BLOCK` alerts (`seq:*`).
- `POST /api/agent/inbox` *(Human-only: requires `X-Luminara-UI-Key`)* — Resolves an inbox item (`action`: `deny`, `allow_once`, `allow_site`, `resume`, or `clear`) and emits a signed `LUM-*` receipt.
- `POST /api/agent/teach` — Manages Teach Mode workflow recording (`action: "list"`; `action: "start"` and `action: "stop"` require `X-Luminara-UI-Key`). Records non-password clicks/inputs/selects into `PlaybookMemory`.
- `POST /api/agent/tabs/focus` — Focuses a live browser tab by `target_id` via `Target.activateTarget` / `Page.bringToFront`.
- `POST /api/agent/lens/compare` — Extracts and compares up to 5 open tabs (`max_tabs`, optional `target_ids`, `workspace_id`, `title`) into Generative UI + SQLite FTS5 Knowledge Graph with a signed `LUM-*` receipt.

## 15. Native Desktop Host Lifecycle REST Endpoints (`127.0.0.1:8796`)

Used by the native Rust Win32 GUI supervisor (`LuminaraBrowser.exe` · `Luminara.Browser.Desktop`), `Launch-Luminara-Browser.cmd`, and `luminara_ctl.py`:

- `GET /api/agent/desktop/status` — Returns redacted desktop heartbeat (`cdp_connected`, `open_tabs`, `active_leases_count`, `pending_handoffs_count`, `pending_mutations_count`, `sequence_blocks_count`, and deduplicated `alert_id` / `alert_title` / `alert_body` with `handoff > sequence > mutation` precedence).
- `POST /api/agent/desktop/takeover` *(Human-only: requires `X-Luminara-UI-Key`)* — Immediately preempts all leased and recently active unleased agent tabs, clears in-page Presence/HUD overlays, and emits a signed `LUM-*` receipt.
- `POST /api/agent/shutdown` *(Human-only: requires `X-Luminara-UI-Key`)* — Closes runtime subsystems, checkpoints SQLite WAL stores (`knowledge_graph.sqlite3`, `monitors_eval.sqlite3`), and stops the HTTP server cleanly.
