# Luminara Browser (`v4.0.0`)

**Warm Atelier Precision × Calm Spatial OS — Privacy-hardened Ungoogled-Chromium (patch track `157.0.8103.78-1.1` · portable binary base `157.0.8103.50-1.1`) fused with PiBot Multi-Bot Teams for simultaneous Human + AI Agent co-browsing.**

Luminara Browser v4.0.0 combines **134 Ungoogled-Chromium C++ privacy & Windows patches + 4 Zero-Fuzz Luminara C++ Engine Patches** (`.void0` domain trap, `luminara://` WebUI, `URLLoaderThrottle` hooks, `SidePanelCoordinator`, deterministic eTLD+1 farbling, zero Google telemetry), a **Luminara v4 Native Desktop Shell** (`luminara-shell/` — 3-Zone Spatial OS with adaptive Warm Atelier Light/Dark themes, 60/120fps `WebContentsView` tabs, working private omnibox, and interactive Privacy Shield), a **zero-dependency Python stdlib Agent Daemon** (`127.0.0.1:8796`) with **PiBot Multi-Bot Teams & Team Hub** (`Pi`, `Remy`, `Dana`, `Research Team`), **Persistent Multiplexed CDP Bus (`<1.5ms` RTT, zero `F12` lockouts)**, **Blink `AXTree` + Shadow-DOM + OOPIF Perception**, **W3C WebMCP (`navigator.modelContext`)**, **Network Mutation Firewall (`Fetch.enable` Savepoints)**, **Numbat Behavioral Sequence Guard (`CASE-*.zip`)**, **Hermetic Declared-Origin PNG VRT**, **Fenced Web Monitors & CAS Playbooks**, **Windows DPAPI + AEAD Encrypted Vault**, **SQLite WAL+FTS5 Workspaces + Tab Hibernation**, **Interactive Privacy Shield v3**, **Offline-First `<8ms` Warm Atelier MV3 Calm Home + `Alt+K` Palette**, and a **28-Tool / 9-Resource MCP v2 Server**.

---

## Quickstart (Windows x64 Desktop Application)

1. **Launch Luminara Browser v4 Native Desktop Shell (Warm Atelier 3-Zone Spatial OS)**:
   Double-click `Launch-Luminara-v4.cmd` — installs/builds `luminara-shell/` on first run and boots the 3-Zone Spatial OS (collapsible Space & Bot Rail, native 60/120fps Chromium `WebContentsView` stage with working private omnibox and interactive Privacy Shield, and Right Contextual Team Drawer with PiBot Multi-Bot Teams, Approval Inbox, Teach Recorder, and Cross-Tab Live Lens).
2. **Launch Portable / Per-User Ungoogled-Chromium Host (Native Zero-Console Win32 Supervisor)**:
   Double-click `Launch-Luminara-Browser.cmd` (or `chromium-forge\dist\luminara-browser-win64\LuminaraBrowser.exe`) — launches with zero terminal flash, Win32 Job-Object daemon supervision & crash auto-restart, Windows System Tray status & handoff/firewall alerts, Warm Atelier theme + Interactive Shield popup + MV3 Copilot Side Panel, and single-instance URL/`luminara://` routing.
   *(On a fresh clone, run `cd chromium-forge && python -m forge build-portable` to unpack Chromium `157.0.8103.50-1.1` and compile `LuminaraBrowser.exe`.)*
3. **Optional Per-User Windows Installation (Zero UAC, Portable Mode Preserved)**:
   Run `Install-Luminara-Browser.cmd` inside `dist\luminara-browser-win64\` (or `python -m forge install-desktop`) to install into `%LOCALAPPDATA%\Programs\Luminara Browser` with Start Menu & Desktop `.lnk` shortcuts (`AppUserModelID: Luminara.Browser.Desktop`), Windows *Apps & Features* uninstaller, and `luminara://` protocol registration while keeping user profile data separate in `%LOCALAPPDATA%\Luminara Browser`.
4. **Launch Forge Customization Studio**:
   Double-click `Launch-Forge-Studio.cmd` (`http://127.0.0.1:8795`).
5. **Connect Any MCP v2 AI Agent (`2025-06-18`) or v4 Team Hub Client**:
   Point any MCP v2 client or autonomous agent runtime to:
   - **MCP JSON-RPC**: `POST http://127.0.0.1:8796/api/agent/mcp`
   - **v4 Team Hub REST**: `http://127.0.0.1:8796/api/agent/{llm/config,llm/ollama,teams,chat,inbox,teach,tabs/focus,lens/compare}`
   - **Agent Discovery**: `GET http://127.0.0.1:8796/.well-known/agent.json` & `GET http://127.0.0.1:8796/llms.txt`

---

## Verified Quality, Security & Live A/B Benchmarks

| Gate / Experiment | Result | Key Verified Metric |
| :--- | :---: | :--- |
| **REA Reconstruction Ledger (`OBL-01`..`OBL-21`)** | **21 / 21 PASS** | 108 Core + 26 Windows + 4 Luminara C++ patches, 7 Perplexity AI clean-room engines, 28-tool MCP v2, SHA-256 + HMAC chain |
| **100x Engine Suite (`BM-01`..`BM-06`)** | **6 / 6 PASS** | **`0.118 ms` Mux CDP RTT** (`9.94x`), **`-95.4%` WebMCP tokens**, DPAPI/AEAD Vault, `Fetch` Firewall, `85%` Tab Freeze |
| **A/B Production Suite (`AB-01`..`AB-08`)** | **8 / 8 PASS** | **`4.5x` parallel**, **`-96.8%` SoM tokens**, `320px` reflow, Multi-LLM failover, DPAPI Vault, AST Sandbox, Playbooks, Redactor |
| **v4 Native Shell Smoke (`luminara-shell/`)** | **5 / 5 PASS** | 0 `.innerHTML`, all TS/TSX `< 450`L, 90+ tracker Privacy Shield, Mutation Firewall redaction, encrypted `LocalStore`, `BotBrain` + real Electron `BaseWindow` boot |

### Security & Co-Browsing Guarantees
- **Loopback DNS-Rebinding & CSRF Protection**: Both `:8795` and `:8796` validate `Host`, reject cross-site & unkeyed `Origin: null` sandboxed iframes, enforce `Content-Type: application/json` on `POST`, and guard human-only routes (`llm/config`, `inbox`, `teach` start/stop, `desktop/takeover`, `shutdown`) with `X-Luminara-UI-Key`.
- **Encrypted Local AI Provider Keys**: LLM API keys (`ollama`, `openrouter`, `gemini`, `anthropic`, `openai`, `custom`) are AEAD-encrypted at rest (`outputs/llm_config.json` via `luminara_crypto` / `safeStorage` in `luminara-shell`) and automatically registered in `LuminaraRedactor` so keys never appear in logs, prompts, or UI responses.
- **Legitimate Human-in-the-Loop Co-Browsing (`PAUSED_HUMAN_HANDOFF`)**: Zero anti-bot or CAPTCHA bypass code. Whenever a login, 2FA, payment, or verification gate appears, the agent releases its `TabLease` and pauses cleanly so the human completes it directly in the shared browser tab.
- **Cryptographic Action Accountability**: Every mutation writes a hash-chained `LUM-<unix_ms>-<sha256[:10]>` receipt signed with `LUM-SIG-V2` (`lum-hmac256:...`) and verified via `GET /api/agent/ledger/verify`.

---

## Developer Verification & Cloud Deployment

```powershell
# 1. Run strict unit, security, PowerShell AST, upstream C++ patch, REA & 100x benchmark suite (zero warnings)
cd chromium-forge
python -m forge build-portable   # unpacks cached Chromium 157.0.8103.50-1.1 portable runtime on a fresh clone
python -m forge verify-arch
python -W error -m unittest discover -s tests -v
python -m forge verify-upstream-patches
python -m forge verify-rea       # use --static-only on Linux/CI without chrome.exe
python -m forge benchmark
python -m forge benchmark-100x

# 2. Verify Luminara v4 Native Desktop Shell (TypeScript strict check, build & Electron smoke)
cd ..\luminara-shell
npm ci
npm run typecheck
npm run build
npm run smoke

# 3. Deploy Cloudflare Edge Portal & Agent Discovery Worker
cd ..
npx wrangler deploy
```

See [docs/architecture-100x.md](docs/architecture-100x.md), [docs/benchmark-100x-results.md](docs/benchmark-100x-results.md), [docs/launch-checklist.md](docs/launch-checklist.md), [docs/design.md](docs/design.md), [docs/product-roadmap.md](docs/product-roadmap.md), and [docs/ab-benchmark-results.md](docs/ab-benchmark-results.md) for production operations.
