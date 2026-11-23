# Luminara Browser — Production Roadmap (`/loop` Review-Gated)

**Status:** 47/47 tasks complete (`v2.x` 10/10 + `v3.0.0` 100x Track 7/7 + Deep Re-Audit Loop 10/10 + `v3.1.0` Perplexity REA Suite 7/7 + `v3.1.0` Production Hardening Loop 4/4 + `v3.1.0` Native Win32 Desktop Application Loop 4/4 + `v4.0.0` Warm Atelier × PiBot Fusion Loop 5/5)  
**Current Phase:** `v4.0.0` Warm Atelier Precision × Calm Spatial OS + PiBot Multi-Bot Teams Release Ready (Native `luminara-shell` 3-Zone Spatial OS, Rust Win32 Host, Team Hub APIs, 21/21 REA Gates, Wheel, Portable, Cloudflare & 4-Root Skills Green)

Every task must complete **1. Build → 2. Review (Code, Security, Design Tokens) → 3. Test End-to-End (empty/loading/error/success + automated suite) → 4. Fix** before marking `- [x]`.

---

## Tasks

- [x] **TASK-001**: Establish synchronized Design System (`docs/design.md` + `docs/design.html`) with perceptual `oklch()` + `light-dark()` tokens, WCAG 2.2 AA contrast (`>= 4.5:1`), Concentric Radius Law, and `tabular-nums`.
- [x] **TASK-002**: Harden Backend, CDP Concurrency & Portability (`forge/http_base.py`, `cdp_client.py`, `extractor.py`, `agent_engine.py`, `agent_server.py`, `studio.py`, `portable.py`, `downloads.py`, `patcher.py`, `domsub.py`, `pruner.py`, `customizer.py`, `packager.py`, `verifier_agentic.py`).
- [x] **TASK-003**: Upgrade Frontend UX, Accessibility (`H1–H50`), Real Sortable Table, RFC 4180 Export, DOM XSS Elimination & MV3 Copilot Extension (`luminara_ui.py`, `luminara_workspace_ui.py`, `forge/ui/index.html`, launchers).
- [x] **TASK-004**: Implement & Execute Live A/B Experiments (`AB-01`..`AB-04`) and Production Security/QA Regression Suite (`forge/ab_benchmark.py`, `tests/test_production_hardening_and_ab.py`, `docs/ab-benchmark-results.md`).
- [x] **TASK-005**: Package for GitHub Push & Cloudflare Edge Deployment (`.gitignore`, `pyproject.toml`, `LICENSE`, `THIRD_PARTY_NOTICES.md`, `README.md`, `.github/workflows/{ci,release-windows}.yml`, `wrangler.toml`, `cloudflare/src/worker.js`, `cloudflare/public/index.html`, `docs/launch-checklist.md`).
- [x] **TASK-006**: Package, Static-Audit (`LOW` risk, `0` findings), and Promote `luminara-browser` Skill + Run Initial Audit.
- [x] **TASK-007**: Harden Core Engine Security, AST Sandbox, DPAPI Vault, Single-Socket Frame/Dialog CDP & Egress Redaction (`F-01`..`F-07`, `F-10`..`F-14`).
- [x] **TASK-008**: Wire Zero-LLM Domain Playbook Replay, Prompt-Fence Escaping, Trajectory Compression & Thermo-Nuclear Server Compaction (`F-08`, `F-09`, `F-15`, `F-16`).
- [x] **TASK-009**: Synchronize `v3.0.0` Full-Stack UI Tokens, Rebuild Portable Distribution, Harden GitHub CI & Update Cloudflare Edge Worker (`20` MCP tools, `7` resources).
- [x] **TASK-010**: Upgrade Secret-Safe `luminara_ctl.py` CLI, Promote Audited Skill to Dual Main Roots, Validate Cloudflare Bundle & Complete Final Independent Double-Check Audit.

---

## Tasks (v3.0 — 100x Chromium Engine Upgrade)

- [x] **TASK-101**: Upstream `chromium/chromium` Blobless Sparse Checkout (`vendor/chromium-src`, `<150 MB` on disk), Version Provenance Auditor & Zero-Fuzz Patch Verifier (`forge/chromium_src.py`).
- [x] **TASK-102–103**: Windows DPAPI + PBKDF2-HMAC-SHA256 Origin-Bound AEAD Encrypted Vault (`forge/luminara_crypto.py`, `forge/luminara_security.py`), Chromium `os_crypt` enabled by default (`forge/models.py`), Ephemeral Session Tokens & Cryptographically Signed `LUM-*` Receipts.
- [x] **TASK-104–105**: Persistent Multiplexed Browser-Level CDP Pipe (`forge/cdp_mux.py` — `<1.5ms` RTT, zero `F12` DevTools collisions, live event ring buffer) + Native Blink `AXTree` / Shadow-DOM / OOPIF Perception & Compositor Hardware Input (`forge/perception.py`).
- [x] **TASK-106–107**: W3C WebMCP (`navigator.modelContext`) Runtime & Declarative `<form toolname>` Auto-Compiler (`forge/webmcp.py`) + Network Mutation Firewall (`Fetch.enable` Savepoint Diff Preview, `forge/mutation_firewall.py`).
- [x] **TASK-108–110**: Zero-Cold-Start Offline-First MV3 New Tab Override (`luminara-newtab`) + `Alt+K` Command Palette (`forge/portable.py`), SQLite WAL+FTS5 Cross-Tab Knowledge Graph & Tab Hibernation Freezer (`forge/knowledge_graph.py`), and Privacy Shield v3 (`forge/shield_compiler.py` — 30k-rule DNR + query-param strip + eTLD+1 deterministic farbling).
- [x] **TASK-111–112**: 4 Zero-Fuzz Native C++ Chromium Patches (`chromium-forge/patches/luminara/*.patch` verified against real `vendor/chromium-src/`), Full 16-Stage Checkpointed `x64`/`arm64` PGO+ThinLTO Cloud Compiler (`forge/customizer.py`), and Opt-In Zero-Telemetry Cryptographic Update Verifier (`forge/updater.py`).
- [x] **TASK-113–114**: Automated 100x Head-to-Head Benchmark Suite (`forge/benchmark_100x.py`, `BM-01`..`BM-06`), 20-Tool MCP v2 Server (`forge/agent_tools_100x.py`), Full Regression Suite (`tests/test_luminara_100x_engine.py`), and Synchronized Architecture & Skill Docs.

---

## Tasks (v3.0.0 — Final Deep Re-Audit & Zero-Defect Loop)

- [x] **TASK-011**: Core Engine, Unified-Namespace Pipeline Sandbox, Async-Event CDP Mux, WebMCP Form-SSRF Guard, At-Rest Redacted SQLite Knowledge Graph & Bounded Session Signer.
- [x] **TASK-012**: Agent Daemon Thermo-Nuclear Compaction, Strict Non-Null Input Validation, 100x `TabLease`/Human-Approval Guards, Live-Tab Playbook URL Resolution & Robust LLM JSON Parsing.
- [x] **TASK-013**: Forge Studio Crash Fix, MV3 `Alt+K` Background Opener, `#lum_token` Passport Auth, Interactive Vault/Playbooks UI, Full Copilot Side Panel Controls & Zero-Competitor Clean-Room Scrub.
- [x] **TASK-014**: CLI Parity (`workspaces --action index/search`), Cross-OS GitHub CI/Release Hardening, Cloudflare Dynamic Repo Sync, Dual-Root Skill Promotion & Final Independent Sign-Off.
- [x] **TASK-015**: Adversarial Core Engine Pass — Public `0x`/`01` Domain Fix, Non-Extension Tab Targeting, `contenteditable`/`<select>`/Visible-Gate DOM Fixes, `otpauth://` + Shadow-DOM Vault, f-String OOM Guard, Playbook/Goal Hardening & Valid-JSON Unicode FTS5.
- [x] **TASK-016**: Adversarial Packaging, MV3 & Out-of-Repo Skill Pass — Non-Editable `pip install .` Support, `sign-manifest` CLI, DNR Domain Sanitizer, `Alt+K` Keystroke Isolation, `~/.luminara-browser` Key Mirror, Test Socket Cleanup & Final Sign-Off.
- [x] **TASK-017**: WHATWG `GURL` SSRF Parity, Scoped RFC 8259 HTTP, `LuminaraRedactor`/`LuminaraVault` Precision & Runtime `sys.settrace` AST Sandbox Guard.
- [x] **TASK-018**: Multiplexed CDP Detach/Crash Cleanup, Perception/WebMCP Schema Validation, CJK/Workspace Integrity & Thermo-Nuclear Server Decomposition (`mcp_specs.py`).
- [x] **TASK-019**: Thermo-Nuclear UI Decomposition (`luminara_copilot_ext.py`), Human Vault `+ Add Credential` & Mutation Firewall `Approve`/`Reject` UI, Active-Tab Copilot & WCAG 2.2 AA `5.05:1` Craft.
- [x] **TASK-020**: Release ZIP Secret Scrubbing (`--release`), `Quote-WinArg`/`-LiteralPath` Launcher, Pinned Chromium SHA-256, PEP 639 Non-Editable Wheel, 3-Root Skill Sync & Final CEO Sign-Off.

---

## Tasks (v3.1.0 — Perplexity AI REA Reverse-Engineering & Clean-Room Suite)

- [x] **TASK-201**: REA v6.5.0 Antigravity MCP Registration (`mcp_config.json`), Gitignored `_rea_targets/perplexity/` Staging & Deterministic Evidence Harvester (`forge/rea_harvester.py`, `chromium-forge/rea_perplexity_evidence.json`).
- [x] **TASK-202**: Clean-Room `SPACE` + `codescythe` Architecture Pattern Ratchet (`forge/arch_ratchet.py` — `<1,000` line ceiling, `dependencies=[]`, L10→L50 layer guard, two-set dead-code reachability) & Monotonic `lease_epoch` Fencing (`forge/knowledge_graph.py`).
- [x] **TASK-203**: Clean-Room `numbat` Partitioned Behavioral Sequence Correlator, `PAUSED_SEQUENCE_BLOCK` Runtime Guard & `LUM-SIG-V2` Signed `CASE-*.zip` Forensic Casebundle Builder/Verifier (`forge/sequence_guard.py`).
- [x] **TASK-204**: Clean-Room `rules_web_e2e` Hermetic `Fetch.enable` Declared-Origin Network Lock & Pure-Stdlib RFC 2083 PNG Scanline Pixel-Diff Visual Regression Engine (`forge/vrt_isolation.py`).
- [x] **TASK-205**: Clean-Room `perplexity-py` + `search_evals` + `pplx-kernels` Fenced Web Monitors, CAS `expected_revision` Playbook Revisions, Exact `Decimal` `CostLedger` Search Eval Harness (`forge/monitors_eval.py`) & MoE All-to-All NVSHMEM Topology Auditor (`forge/kernel_spec_audit.py`).
- [x] **TASK-206**: Full-Stack `v3.1.0` Surface Integration — 28-Tool / 9-Resource MCP v2 (`forge/agent_tools_v31.py`, `forge/mcp_specs.py`, `forge/agent_server.py`), Zero-XSS `/workspace` Telemetry Cockpit (`forge/luminara_telemetry_ui.py`), Secret-Safe `luminara_ctl.py` CLI & Cloudflare Edge Worker (`cloudflare/src/worker.js`).
- [x] **TASK-207**: REA Stage 7 Verification (`OBL-15`..`OBL-21` in `forge/verifier_perplexity.py`), Zero-Warning Full-Stack Regression Suite (`tests/test_perplexity_rea_v31.py`) & Synchronized Architecture Docs.

---

## Tasks (v3.1.0 — Principal Multi-Agent Production Hardening & Release Loop)

- [x] **TASK-301**: Core CDP Mux `Fetch` Hook Coordinator (`cdp_mux.py`, `cdp_client.py`), VRT + Mutation Firewall Cooperative Interception (`vrt_isolation.py`, `mutation_firewall.py`), Persistent Anti-Spoof `SequenceGuard` Latch (`sequence_guard.py`), AST `.replace`/`.join` & Lease-Safe Playbook Replay (`luminara_automation.py`), and Unified Human-UI-Key Auth (`agent_tools_v31.py`, `agent_server.py`).
- [x] **TASK-302**: Real `rea-agents@6.5.0` 12-Evidence Ledger across 7/7 Perplexity Targets (`rea_harvester.py`, `forge/rea_evidence/*.json`), Release-Scrubbed Copilot `ui_key=""` (`luminara_copilot_ext.py`), Decomposed Honest Search Eval & SSRF-Pinned Monitors (`monitors_eval.py`, `search_eval_runner.py`), and Out-of-Repo Wheel `arch_ratchet` (`0` unreferenced exports).
- [x] **TASK-303**: Full `/workspace` Telemetry Cockpit Controls (Monitor Run/Delete/Diff, CAS Rollback, Signed `.zip` Casebundle Download/Verify, VRT Baseline/Compare/Lock, Honest `SKIPPED (No API Key)` Scorecard), WCAG 2.2 AA `3.1:1` Control Borders, Focus Trap/Roving Tablist, and MV3 `3.1.0` Parity.
- [x] **TASK-304**: Complete 28-Tool `luminara_ctl.py` CLI (`outline`, `wait`, `screenshot`, `schedule`, `--human-auth`, `valid: false` exit `1`), 4-Root Main Skill Byte-Identical Sync, Hardened GitHub CI/Release Workflows, Expanded Regression Suite (`tests/test_perplexity_rea_v31.py`), and Independent CEO Release Gate Sign-Off.

---

## Tasks (v3.1.0 — Industry-Grade Native Win32 Desktop Application & Release Loop)

- [x] **TASK-401**: Native Zero-Dependency Rust Win32 Desktop Supervisor (`desktop/` → `LuminaraBrowser.exe` — `WINDOWS_GUI`, `Luminara.Browser.Desktop`, `PerMonitorV2` DPI, `JobObject` orphan-free lifecycle, `Mutex+Condvar` WAL-safe shutdown, SDDL-locked user-SID Named Pipe single-instance routing, and `Shell_NotifyIconW` v4 System Tray).
- [x] **TASK-402**: Zero-UAC Per-User Windows Installer & Uninstaller (`forge/desktop_build.py`, `forge/desktop_installer.py`, `forge/exe_icon.py` — `%LOCALAPPDATA%\Programs\Luminara Browser` separated from `%LOCALAPPDATA%\Luminara Browser\{User Data,AgentData,Logs}`, STA/MTA-safe COM `.lnk` shortcuts, HKCU Apps & Features + `luminara://` protocol, read-only upgrade & shell-free deferred cleanup).
- [x] **TASK-403**: Thermo-Nuclear Agent Server Compaction (`forge/agent_tools_core.py`, `forge/agent_server.py` `621`L, `forge/agent_desktop.py`), `_last_actor` Human Takeover Preemption (`forge/cdp_client.py`, `forge/presence.py`), Studio `X-Luminara-UI-Key` Guard (`forge/studio.py`), and `H1–H50` Studio UI Craft (`forge/ui/index.html`).
- [x] **TASK-404**: Cloudflare Edge Desktop Discovery (`cloudflare/src/worker.js`, `cloudflare/public/index.html`), `luminara_ctl.py` (`desktop-status`, `takeover --human-auth`) + 4-Root Byte-Identical Skill Sync, Hardened GitHub CI/Release ZIP Scrub Gates, and Independent CEO Double-Check Sign-Off.

---

## Tasks (v4.0.0 — Warm Atelier Precision × Calm Spatial OS & PiBot Multi-Agent Fusion)

- [x] **TASK-501**: Synchronized Warm Atelier Precision Design System (`docs/design.md` + `docs/design.html` v4.0.0 — Warm Alabaster `#FAF9F6` / Deep Obsidian `#141519`, adaptive Light/Dark modes, WCAG 2.2 AA contrast `#117A5E`/`#3CD0A3`, Concentric Radius Law `20px`/`16px`/`10px`/`999px`, ambient per-Bot color washes).
- [x] **TASK-502**: Luminara v4 Team Hub Backend (`forge/agent_team_hub.py` + `forge/agent_server.py` — AEAD-encrypted `outputs/llm_config.json`, Ollama `/api/tags` prober, PiBot-enriched teams `Pi`/`Remy`/`Dana`/`Research Team`, fenced live tab chat, unified Approval Inbox, password-safe Teach Mode recorder, tab focus, and Cross-Tab Live Lens).
- [x] **TASK-503**: Luminara v4 Native Desktop Shell (`luminara-shell/` + `Launch-Luminara-v4.cmd` — React 19 + Electron `BaseWindow` + isolated 60/120fps `WebContentsView` tabs, working private omnibox, interactive 90+ tracker Privacy Shield, Mutation Firewall Approval Cards, encrypted `LocalStore`, `BotBrain`, and 5-stage `npm run smoke` E2E gate).
- [x] **TASK-504**: Warm Atelier Chromium Surfaces (`forge/luminara_ui.py`, `forge/luminara_workspace_ui.py`, `forge/luminara_telemetry_ui.py`, `forge/luminara_copilot_ext.py`, `forge/portable.py` — Warm Atelier `luminara-theme` extension, Interactive Shield v3 popup, Calm Home working omnibox, Copilot Team Hub Drawer, and 7-surface `--release` `UI_KEY` scrub).
- [x] **TASK-505**: `v4.0.0` Version Parity, Deployment & 4-Root Skill Sync (`.gitignore`, `.github/workflows/{ci,release-windows}.yml` with Node 22 + `luminara-shell` gates & 7-surface release zip audit, `pyproject.toml`, `desktop/{Cargo.toml,luminara.manifest}`, `forge/mcp_specs.py`, Warm Atelier Cloudflare Edge Worker/Portal `wrangler.toml`/`cloudflare/**`, 7-command secret-safe `luminara_ctl.py` + 4-root SHA-256 skill sync, and synchronized v4 docs).
