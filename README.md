# Luminara Browser (`v3.1.0`)

**Privacy-hardened Ungoogled-Chromium (`157`–`160` patch track) engineered for 100x Human + AI Agent co-browsing.**

Luminara Browser combines **134 Ungoogled-Chromium C++ privacy & Windows patches + 4 Zero-Fuzz Luminara C++ Engine Patches** (`.void0` domain trap, `luminara://` WebUI, `URLLoaderThrottle` hooks, `SidePanelCoordinator`, deterministic eTLD+1 farbling, zero Google telemetry) with a **zero-dependency Python stdlib Agent Daemon** (`127.0.0.1:8796`), **Persistent Multiplexed CDP Bus (`<1.5ms` RTT, zero `F12` lockouts)**, **Blink `AXTree` + Shadow-DOM + OOPIF Perception**, **W3C WebMCP (`navigator.modelContext`)**, **Network Mutation Firewall (`Fetch.enable` Savepoints)**, **Numbat Behavioral Sequence Guard (`CASE-*.zip`)**, **Hermetic Declared-Origin PNG VRT**, **Fenced Web Monitors & CAS Playbooks**, **Windows DPAPI + AEAD Encrypted Vault**, **SQLite WAL+FTS5 Workspaces + Tab Hibernation**, **Privacy Shield v3**, **Offline-First `<8ms` MV3 Command Deck + `Alt+K` Palette**, and a **28-Tool / 9-Resource MCP v2 Server**.

---

## Quickstart (Windows x64 Desktop)

1. **Launch Luminara Browser + Agent Daemon**:
   Double-click `Launch-Luminara-Browser.cmd` (or run `python -m forge build-portable` inside `chromium-forge/` if building from a fresh clone).
2. **Launch Forge Customization Studio**:
   Double-click `Launch-Forge-Studio.cmd` (`http://127.0.0.1:8795`).
3. **Connect Any MCP v2 AI Agent (`2025-06-18`)**:
   Point any MCP v2 client or autonomous agent runtime to:
   - **MCP JSON-RPC**: `POST http://127.0.0.1:8796/api/agent/mcp`
   - **Agent Discovery**: `GET http://127.0.0.1:8796/.well-known/agent.json` & `GET http://127.0.0.1:8796/llms.txt`

---

## Verified Quality, Security & Live A/B Benchmarks

| Gate / Experiment | Result | Key Verified Metric |
| :--- | :---: | :--- |
| **REA Reconstruction Ledger (`OBL-01`..`OBL-21`)** | **21 / 21 PASS** | 108 Core + 26 Windows + 4 Luminara C++ patches, 7 Perplexity AI clean-room engines, 28-tool MCP v2, SHA-256 + HMAC chain |
| **100x Engine Suite (`BM-01`..`BM-06`)** | **6 / 6 PASS** | **`0.118 ms` Mux CDP RTT** (`9.94x`), **`-95.4%` WebMCP tokens**, DPAPI/AEAD Vault, `Fetch` Firewall, `85%` Tab Freeze |
| **A/B Production Suite (`AB-01`..`AB-08`)** | **8 / 8 PASS** | **`4.5x` parallel**, **`-96.8%` SoM tokens**, `320px` reflow, Multi-LLM failover, DPAPI Vault, AST Sandbox, Playbooks, Redactor |

### Security & Co-Browsing Guarantees
- **Loopback DNS-Rebinding & CSRF Protection**: Both `:8795` and `:8796` validate `Host`, reject cross-site & unkeyed `Origin: null` sandboxed iframes, and enforce `Content-Type: application/json` on `POST`.
- **Legitimate Human-in-the-Loop Co-Browsing (`PAUSED_HUMAN_HANDOFF`)**: Zero anti-bot or CAPTCHA bypass code. Whenever a login, 2FA, payment, or verification gate appears, the agent releases its `TabLease` and pauses cleanly so the human completes it directly in the shared browser tab.
- **Cryptographic Action Accountability**: Every mutation writes a hash-chained `LUM-<unix_ms>-<sha256[:10]>` receipt signed with `LUM-SIG-V2` (`lum-hmac256:...`) and verified via `GET /api/agent/ledger/verify`.

---

## Developer Verification & Cloud Deployment

```powershell
# Run strict unit, security, PowerShell AST, upstream C++ patch, REA & 100x benchmark suite (zero warnings)
cd chromium-forge
python -m forge build-portable   # unpacks cached Chromium 157 portable runtime on a fresh clone
python -W error -m unittest discover -s tests -v
python -m forge verify-upstream-patches
python -m forge verify-rea       # use --static-only on Linux/CI without chrome.exe
python -m forge benchmark
python -m forge benchmark-100x

# Deploy Cloudflare Edge Portal & Agent Discovery Worker
cd ..
npx wrangler deploy
```

See [docs/architecture-100x.md](docs/architecture-100x.md), [docs/benchmark-100x-results.md](docs/benchmark-100x-results.md), [docs/launch-checklist.md](docs/launch-checklist.md), [docs/design.md](docs/design.md), and [docs/ab-benchmark-results.md](docs/ab-benchmark-results.md) for production operations.
