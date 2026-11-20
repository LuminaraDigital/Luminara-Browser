# Luminara Browser — Production Roadmap (`/loop` Review-Gated)

**Status:** 21/21 tasks complete (`v2.x` 10/10 + `v3.0.0` 100x Track 7/7 + Deep Re-Audit Loop 4/4)  
**Current Phase:** Officially Production & Deployment Ready (`v3.0.0` — `SHIP` Signed Off)

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
