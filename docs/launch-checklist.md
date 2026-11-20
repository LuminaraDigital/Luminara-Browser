# Luminara Browser — Production Launch Checklist

**Product:** Luminara Browser (`v3.0.0`) — Privacy-hardened Ungoogled-Chromium 157 Windows desktop browser + Local 20-Tool MCP v2 Agent Daemon (`chromium-forge/`) + Cloudflare Edge Portal (`cloudflare/`) + Reusable AI Agent Skill (`skills/luminara-browser/`).  
**Estimated Total Time:** ~35 minutes  
**Estimated Monthly Cost:** **$0/month** (GitHub Free + Cloudflare Workers Free tier; optional custom domain ~$10/year).

### Legend
- 🧑 **You** — Needs your personal account login, identity, or final approval click.
- 🤖 **Agent** — Copy-paste the prompt into your coding agent to execute automatically.
- 🤝 **Together** — The agent prepares and verifies everything; you complete one login or confirmation step.

---

## Phase 1: Pre-Push Binary, Security & Test Gate (3 min)

- [x] 🤖 **Step 1.1 — Run full Zero-Warning Unit, Live Chromium E2E, Upstream C++ Patch (`4/4`), 100x Engine (`6/6`), REA (`14/14`), & A/B (`4/4`) Gate (2 min)**
  Verifies that zero large binary archives (`.zip`/`.exe`/`.dll`, which GitHub rejects over 100 MB) or encrypted vault files are tracked by Git, and that all security, PowerShell syntax, 100x engine, and A/B benchmarks pass.
  > `"Run python -W error -m unittest discover -s tests -v, python -m forge verify-upstream-patches, python -m forge verify-rea, python -m forge benchmark, and python -m forge benchmark-100x inside chromium-forge, and verify git status excludes dist/, cache/, vendor/, and outputs/."`
  **You'll know it worked when:** All unit & live Chromium E2E tests print `OK`, `AB-01..AB-04` and `BM-01..BM-06` report `PASS`, and `git status` lists zero `.exe` or `.zip` files.

---

## Phase 2: Push Source & Trigger Automated Windows Release on GitHub (10 min, $0/mo)

- [ ] 🧑 **Step 2.1 — Create a new GitHub repository (3 min)**
  Go to `https://github.com/new`, name the repository `luminara-browser`, choose **Public** (free unlimited GitHub Actions minutes for open-source repos) or **Private**, leave *"Add a README"* unchecked (we already have one), and click **Create repository**.
  **You'll know it worked when:** GitHub shows an empty repository page with a `https://github.com/<your-org>/luminara-browser.git` URL.

- [ ] 🤝 **Step 2.2 — Push `main` branch and tag `v3.0.0` to build the downloadable Windows zip (7 min)**
  A **Git tag** (a version marker like `v3.0.0`) automatically triggers `.github/workflows/release-windows.yml`, which assembles `Luminara-Browser-win64-portable.zip` and its **SHA-256 checksum** (a cryptographic fingerprint proving the download wasn't tampered with) on GitHub's cloud servers.
  > `"Connect my GitHub remote https://github.com/<your-org>/luminara-browser.git, push main, and push tag v3.0.0."`
  **You'll know it worked when:** The **Actions** tab on GitHub turns green on both `Luminara Browser CI & Security Gate` and `Build & Publish Portable Windows x64 Release`, and `Releases` lists `Luminara-Browser-win64-portable.zip` + `SHA256SUMS.txt`.

---

## Phase 3: Deploy Portal & Agent Discovery to Cloudflare Edge (10 min, $0/mo)

- [ ] 🧑 **Step 3.1 — Sign in to Cloudflare Wrangler CLI (3 min)**
  **Cloudflare Workers** hosts your public landing page, `/llms.txt`, and `/.well-known/agent.json` globally at the edge for $0/month. Run `npx wrangler login` in a terminal and click **Allow** in the browser tab that opens.
  **You'll know it worked when:** The terminal prints `Successfully logged in.`

- [ ] 🤖 **Step 3.2 — Update `GITHUB_REPO` in `wrangler.toml` and deploy live (2 min)**
  > `"Set GITHUB_REPO in wrangler.toml to my GitHub URL, run npx wrangler deploy, and verify /api/health, /llms.txt, and /.well-known/agent.json."`
  **You'll know it worked when:** Wrangler outputs your live `https://luminara-browser.<subdomain>.workers.dev` URL and `/api/health` returns `{"status": "ok"}` with **CSP** (*Content Security Policy*, browser headers that block script injection) and **HSTS** (*HTTP Strict Transport Security*, forcing encrypted HTTPS).

- [ ] 🧑 **Step 3.3 — (Optional) Connect a custom domain (~5 min, ~$10/yr)**
  In the Cloudflare Dashboard → **Workers & Pages** → `luminara-browser` → **Settings → Domains & Routes**, click **Add → Custom Domain** (e.g., `browser.luminara.ai`). Cloudflare configures **DNS** (the internet's address book mapping your domain name to Cloudflare's servers) and HTTPS certificates automatically.
  **You'll know it worked when:** Visiting `https://browser.luminara.ai` loads the Luminara Browser portal with a valid padlock icon.

---

## Phase 4: Optional AI Provider Keys & Multi-User Hardening (5 min)

- [ ] 🧑 **Step 4.1 — Configure optional cloud/local LLM keys via environment variables (3 min)**
  Luminara Browser works out of the box with **zero API keys** using its deterministic heuristic planner. To enable cloud or local LLM reasoning for complex goals, set an **environment variable** (a secret setting stored in Windows outside your code—never paste API keys into source files or Git):
  - Google Gemini: `setx GEMINI_API_KEY "your-key"`
  - Anthropic Claude: `setx ANTHROPIC_API_KEY "your-key"`
  - OpenAI / Local Ollama: `setx LUMINARA_LLM_BASE_URL "http://127.0.0.1:11434/v1"`
  **You'll know it worked when:** Running an Autonomous Agent Goal in the Command Deck shows `Provider: gemini` (or `anthropic` / `openai_compat`).

- [ ] 🧑 **Step 4.2 — (Optional, Multi-User PCs) Require an Agent Passport Token (2 min)**
  On shared workstations, set `setx LUMINARA_AGENT_TOKEN "a-long-random-secret"` so external local scripts must pass `Authorization: Bearer <token>` to `:8796` (built-in Luminara tabs continue authenticating automatically via `outputs/local_ui_key.txt`).
  **You'll know it worked when:** Unauthenticated `curl http://127.0.0.1:8796/api/agent/status` returns `401 Unauthorized`.

---

## Phase 5: End-to-End Customer & Agent Smoke Test (5 min)

- [ ] 🤝 **Step 5.1 — Walk the real Human + AI Co-Browsing flow (5 min)**
  1. Double-click `Launch-Luminara-Browser.cmd` on your Desktop.
  2. Open the **Luminara Agent Copilot** Side Panel from the toolbar icon and click **Index `[1..N]` DOM** on any webpage.
  3. Click **Page → GenUI** and sort columns in **Sortable Table**, then export CSV.
  4. Ask your connected MCP v2 agent: *"Use the `luminara-browser` skill to check my live browser tabs and verify the `LUM-*` receipt ledger."*
  **You'll know it worked when:** Both you and your AI agent see the exact same live tabs and `GET /api/agent/ledger/verify` returns `{"valid": true}`.
