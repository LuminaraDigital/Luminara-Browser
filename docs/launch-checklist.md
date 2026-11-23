# Luminara Browser — Production Launch Checklist

**Product:** Luminara Browser (`v4.0.0`) — Warm Atelier Precision × Calm Spatial OS Desktop Browser (`Launch-Luminara-v4.cmd` / `luminara-shell/`) + Privacy-hardened Ungoogled-Chromium 157 Windows desktop host (`LuminaraBrowser.exe` Native Rust Win32 GUI Supervisor + Zero-UAC Per-User Setup; patch track `157.0.8103.78-1.1` / portable base `157.0.8103.50-1.1`) + Local 28-Tool / 9-Resource MCP v2 & PiBot Team Hub Agent Daemon (`chromium-forge/`) + Cloudflare Edge Portal (`cloudflare/`) + Reusable AI Agent Skill (`skills/luminara-browser/`).  
**Estimated Total Time:** ~35 minutes  
**Estimated Monthly Cost:** **$0/month** (GitHub Free + Cloudflare Workers Free tier; optional custom domain ~$10/year).

### Legend
- 🧑 **You** — Needs your personal account login, identity, or final approval click.
- 🤖 **Agent** — Copy-paste the prompt into your coding agent to execute automatically.
- 🤝 **Together** — The agent prepares and verifies everything; you complete one login or confirmation step.

---

## Phase 1: Pre-Push Binary, Security, Shell & Test Gate (4 min)

- [x] 🤖 **Step 1.1 — Run full Zero-Warning Arch Ratchet, Unit, Live Chromium E2E, Luminara v4 Shell Smoke, Upstream C++ Patch (`4/4`), 100x Engine (`6/6`), REA (`21/21`), & A/B (`8/8`) Gate (4 min)**
  Verifies that zero large binary archives (`.zip`/`.exe`/`.dll`, which GitHub rejects over 100 MB), `node_modules/`, or encrypted vault/LLM config files (`llm_config.json`, `luminara-v4-config.json`, `luminara-v4-state.json`) are tracked by Git, and that all Python, Rust, TypeScript, Electron smoke, 100x engine, and A/B benchmarks pass.
  > `"Run python -m forge verify-arch, python -W error -m unittest discover -s tests -v, python -m forge verify-upstream-patches, python -m forge verify-rea, python -m forge benchmark, and python -m forge benchmark-100x inside chromium-forge; run npm ci && npm run typecheck && npm run build && npm run smoke inside luminara-shell; and verify git status excludes dist/, cache/, _rea_targets/, vendor/, node_modules/, and outputs/."`
  **You'll know it worked when:** All unit & live Chromium E2E tests print `OK`, `luminara-shell` prints `ALL CHECKS PASSED`, `AB-01..AB-08` and `BM-01..BM-06` report `PASS`, and `git status` lists zero `.exe`, `.zip`, or secret config files.

---

## Phase 2: Push Source & Trigger Automated Windows Release on GitHub (10 min, $0/mo)

- [ ] 🧑 **Step 2.1 — Create a new GitHub repository (3 min)**
  Go to `https://github.com/new`, name the repository `luminara-browser`, choose **Public** (free unlimited GitHub Actions minutes for open-source repos) or **Private**, leave *"Add a README"* unchecked (we already have one), and click **Create repository**.
  **You'll know it worked when:** GitHub shows an empty repository page with a `https://github.com/<your-org>/luminara-browser.git` URL.

- [ ] 🤝 **Step 2.2 — Push `main` branch and tag `v4.0.0` to build the downloadable Windows zip (7 min)**
  A **Git tag** (a version marker like `v4.0.0`) automatically triggers `.github/workflows/release-windows.yml`, which assembles `Luminara-Browser-win64-portable.zip`, audits all 7 `UI_KEY` scrub surfaces + `luminara-theme/manifest.json` + secret exclusions, and publishes its **SHA-256 checksum** and signed release manifest on GitHub's cloud servers.
  > `"Connect my GitHub remote https://github.com/<your-org>/luminara-browser.git, push main, and push tag v4.0.0."`
  **You'll know it worked when:** The **Actions** tab on GitHub turns green on both `Luminara Browser CI & Security Gate` and `Build & Publish Portable Windows x64 Release`, and `Releases` lists `Luminara-Browser-win64-portable.zip` + `SHA256SUMS.txt` + `release-manifest.json`.

---

## Phase 3: Deploy Portal & Agent Discovery to Cloudflare Edge (10 min, $0/mo)

- [ ] 🧑 **Step 3.1 — Sign in to Cloudflare Wrangler CLI (3 min)**
  **Cloudflare Workers** hosts your Warm Atelier Precision landing page, `/llms.txt`, `/llms-full.txt`, `/api/mcp-spec`, and `/.well-known/agent.json` globally at the edge for $0/month. Run `npx wrangler login` in a terminal and click **Allow** in the browser tab that opens.
  **You'll know it worked when:** The terminal prints `Successfully logged in.`

- [ ] 🤖 **Step 3.2 — Update `GITHUB_REPO` in `wrangler.toml` and deploy live (2 min)**
  > `"Set GITHUB_REPO in wrangler.toml to my GitHub URL, run npx wrangler deploy, and verify /api/health, /llms.txt, and /.well-known/agent.json."`
  **You'll know it worked when:** Wrangler outputs your live `https://luminara-browser.<subdomain>.workers.dev` URL and `/api/health` returns `{"status": "ok", "version": "4.0.0"}` with **CSP** (*Content Security Policy*) and **HSTS** (*HTTP Strict Transport Security*).

- [ ] 🧑 **Step 3.3 — (Optional) Connect a custom domain (~5 min, ~$10/yr)**
  In the Cloudflare Dashboard → **Workers & Pages** → `luminara-browser` → **Settings → Domains & Routes**, click **Add → Custom Domain** (e.g., `browser.luminara.ai`). Cloudflare configures **DNS** and HTTPS certificates automatically.
  **You'll know it worked when:** Visiting `https://browser.luminara.ai` loads the Luminara Browser v4 portal with a valid padlock icon.

---

## Phase 4: Optional AI Provider Keys & Multi-User Hardening (5 min)

- [ ] 🧑 **Step 4.1 — Connect local Ollama or AEAD-encrypted AI provider keys (3 min)**
  Luminara Browser v4 works out of the box with **zero API keys** (graceful local summaries & deterministic heuristic planner). To unlock full PiBot Multi-Bot Team reasoning (`Pi`, `Remy`, `Dana`, `Research Team`), either open **Settings → AI Provider** in `Launch-Luminara-v4.cmd` / Calm Home or configure via the secret-safe CLI (keys are AEAD-encrypted at rest in `outputs/llm_config.json` and never committed to Git):
  - Local Ollama (zero cloud keys): `python skills/luminara-browser/scripts/luminara_ctl.py llm-config --action set --provider ollama --model llama3.2 --human-auth`
  - Cloud API key via env var: `python skills/luminara-browser/scripts/luminara_ctl.py llm-config --action set --provider openrouter --model anthropic/claude-3.5-sonnet --api-key-env OPENROUTER_API_KEY --human-auth`
  - Or standard environment variables (`GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `LUMINARA_LLM_BASE_URL`).
  **You'll know it worked when:** `llm-config --action get` returns `"configured": true` with only a masked key preview.

- [ ] 🧑 **Step 4.2 — (Optional, Multi-User PCs) Require an Agent Passport Token (2 min)**
  On shared workstations, set `setx LUMINARA_AGENT_TOKEN "a-long-random-secret"` so external local scripts must pass `Authorization: Bearer <token>` to `:8796` (built-in Luminara tabs continue authenticating automatically via `outputs/local_ui_key.txt`).
  **You'll know it worked when:** Unauthenticated `curl http://127.0.0.1:8796/api/agent/status` returns `401 Unauthorized`.

---

## Phase 5: End-to-End Customer & Agent Smoke Test (5 min)

- [ ] 🤝 **Step 5.1 — Walk the real v4 Spatial Shell, PiBot Team Hub & Desktop Supervisor flow (5 min)**
  1. Launch `Launch-Luminara-v4.cmd` and verify the Warm Atelier Light/Dark 3-Zone Spatial OS opens with working private omnibox search, interactive Privacy Shield toggle, and PiBot bots (`Pi`, `Remy`, `Dana`, `Research Team`) in the right drawer.
  2. Launch `LuminaraBrowser.exe` (via Start Menu/Desktop shortcut after running `Install-Luminara-Browser.cmd`, or double-click `Launch-Luminara-Browser.cmd` for Portable mode) and verify the Windows System Tray icon appears with zero console flash and Warm Atelier theme applied.
  3. Open the **Luminara Agent Copilot** Side Panel from the toolbar icon, run a **Live Lens** cross-tab comparison (`lens-compare`), and review any pending Approval Inbox items.
  4. Ask your connected MCP v2 agent: *"Use the `luminara-browser` skill to list my live tabs and PiBot teams, check the desktop supervisor heartbeat, and verify the `LUM-*` receipt ledger."*
  **You'll know it worked when:** Both you and your AI agent see the exact same live tabs, `GET /api/agent/teams` returns all 4 built-in bots, `GET /api/agent/desktop/status` reports `cdp_connected: true`, and `GET /api/agent/ledger/verify` returns `{"valid": true}`.
