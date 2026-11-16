# Luminara Browser MCP v2 Protocol Reference (`2025-06-18`)

Endpoint: `POST http://127.0.0.1:8796/api/agent/mcp`  
Content-Type: `application/json`

## 1. Initialize Handshake

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "initialize",
  "params": {}
}
```

## 2. Call `browser_snapshot` (Set-of-Marks `[1..N]` Indexing)

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/call",
  "params": {
    "name": "browser_snapshot",
    "arguments": {
      "show_badges": true,
      "agent_id": "antigravity-agent"
    }
  }
}
```

## 3. Call `browser_bulk_extract` (Parallel Per-Domain Multi-Tab Scrape)

```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "tools/call",
  "params": {
    "name": "browser_bulk_extract",
    "arguments": {
      "urls": ["https://example.com", "https://www.iana.org/domains/reserved"],
      "concurrency": 4,
      "format": "md"
    }
  }
}
```

## 4. Read Verifiable Ledger Chain Resource

```json
{
  "jsonrpc": "2.0",
  "id": 4,
  "method": "resources/read",
  "params": {
    "uri": "luminara://ledger/verify"
  }
}
```
