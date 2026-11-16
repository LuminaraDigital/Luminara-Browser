# Luminara Browser (`v2.1.0`)

**Privacy-hardened Ungoogled-Chromium `157.0.8103.78` built for simultaneous Human + AI Agent co-browsing.**

Luminara Browser combines **134 Ungoogled-Chromium C++ privacy & Windows patches** (`.void0` domain trap + `trk:` protocol sink, zero Google telemetry) with a **zero-dependency Python stdlib Agent Daemon** (`127.0.0.1:8796`), **RFC 6455 Loopback CDP Bridge** (`127.0.0.1:9229`), **MV3 Side Panel Copilot**, **Comet Command Deck**, and **50-slot Undo/Redo Generative UI Studio**.

---

## Quickstart (Windows x64 Desktop)

1. **Launch Luminara Browser + Agent Daemon**:
   Double-click `Launch-Luminara-Browser.cmd` (or run `python -m forge build-portable` inside `chromium-forge/` if building from a fresh clone).
2. **Launch Forge Customization Studio**:
   Double-click `Launch-Forge-Studio.cmd` (`http://127.0.0.1:8795`).
3. **Connect Any External AI Agent (MCP v2 `2025-06-18`)**:
   Point Claude Code, Antigravity, Hermes Agent, or Cursor to:
   - **MCP JSON-RPC**: `POST http://127.0.0.1:8796/api/agent/mcp`
   - **Agent Discovery**: `GET http://127.0.0.1:8796/.well-known/agent.json` & `GET http://127.0.0.1:8796/llms.txt`

---

## Verified Quality, Security & Live A/B Benchmarks

| Gate / Experiment | Result | Key Verified Metric |
| :--- | :---: | :--- |
| **REA Reconstruction Ledger (`OBL-01`..`OBL-14`)** | **14 / 14 PASS** | 108 Core + 26 Windows patches, live CDP, MCP v2, SHA-256 chain |
| **AB-01: Multi-Tab Research Throughput** | **PASS** | **`4.54x`–`5.23x` faster** per-domain parallel vs sequential (`8/8` fault-isolated) |
| **AB-02: Set-of-Marks Context & Injection Defense** | **PASS** | **`-96.7%` prompt tokens** (`79` vs `2,417`) & **`0%`** hidden CSS injection leak |
| **AB-03: Sortable Matrix UX & `320px` Reflow** | **PASS** | **`1`-click `O(1)` sort** vs `6` card scans & **`0px`** overflow at `320px` |
| **AB-04: Multi-LLM Cascading Failover** | **PASS** | **`100%` completion** (`Gemini -> Anthropic -> OpenAI/Ollama -> Zero-Key Heuristic`) |

### Security & Co-Browsing Guarantees
- **Loopback DNS-Rebinding & CSRF Protection**: Both `:8795` and `:8796` validate `Host`, reject cross-site & unkeyed `Origin: null` sandboxed iframes, and enforce `Content-Type: application/json` on `POST`.
- **Legitimate Human-in-the-Loop Co-Browsing (`PAUSED_HUMAN_HANDOFF`)**: Zero anti-bot or CAPTCHA bypass code. Whenever a login, 2FA, payment, or verification gate appears, the agent releases its `TabLease` and pauses cleanly so the human completes it directly in the shared browser tab.
- **Cryptographic Action Accountability**: Every mutation writes a hash-chained `LUM-<unix_ms>-<sha256[:10]>` receipt verified via `GET /api/agent/ledger/verify`.

---

## Developer Verification & Cloud Deployment

```powershell
# Run strict unit, security, PowerShell AST & A/B test suite (zero warnings allowed)
cd chromium-forge
python -W error -m unittest discover -s tests -v
python -m forge verify-rea
python -m forge benchmark

# Deploy Cloudflare Edge Portal & Agent Discovery Worker
cd ..
npx wrangler deploy
```

See [docs/launch-checklist.md](docs/launch-checklist.md), [docs/design.md](docs/design.md), and [docs/ab-benchmark-results.md](docs/ab-benchmark-results.md) for production operations.
