# Luminara Browser MCP v2 Protocol Reference (`2025-06-18` · `v3.0.0`)

Endpoint: `POST http://127.0.0.1:8796/api/agent/mcp`  
Content-Type: `application/json`  
Optional Auth Header (when `LUMINARA_AGENT_TOKEN` is configured): `Authorization: Bearer <token>`

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

## 12. Read MCP v2 Resources (`luminara://*`)

Available URIs:
- `luminara://tabs/live`
- `luminara://ledger/recent`
- `luminara://ledger/verify`
- `luminara://vault/entries`
- `luminara://playbooks/list`
- `luminara://workspaces/list`
- `luminara://mutations/status`

```json
{
  "jsonrpc": "2.0",
  "id": 14,
  "method": "resources/read",
  "params": {
    "uri": "luminara://ledger/verify"
  }
}
```
