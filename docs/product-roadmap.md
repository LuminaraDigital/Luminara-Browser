# Luminara Browser — Production Roadmap (`/loop` Review-Gated)

**Status:** 6/6 tasks complete  
**Current Phase:** Production Ready — Final Double-Check Audit

Every task must complete **1. Build → 2. Review (Code, Security, Design Tokens) → 3. Test End-to-End (empty/loading/error/success + automated suite) → 4. Fix** before marking `- [x]`.

---

## Tasks

- [x] **TASK-001**: Establish synchronized Design System (`docs/design.md` + `docs/design.html`) with perceptual `oklch()` + `light-dark()` tokens, WCAG 2.2 AA contrast (`>= 4.5:1`), Concentric Radius Law, and `tabular-nums`.
- [x] **TASK-002**: Harden Backend, CDP Concurrency & Portability (`forge/http_base.py`, `cdp_client.py`, `extractor.py`, `agent_engine.py`, `agent_server.py`, `studio.py`, `portable.py`, `downloads.py`, `patcher.py`, `domsub.py`, `pruner.py`, `customizer.py`, `packager.py`, `verifier_agentic.py`).
- [x] **TASK-003**: Upgrade Frontend UX, Accessibility (`H1–H50`), Real Sortable Table, RFC 4180 Export, DOM XSS Elimination & MV3 Copilot Extension (`luminara_ui.py`, `luminara_workspace_ui.py`, `forge/ui/index.html`, launchers).
- [x] **TASK-004**: Implement & Execute Live A/B Experiments (`AB-01`..`AB-04`) and Production Security/QA Regression Suite (`forge/ab_benchmark.py`, `tests/test_production_hardening_and_ab.py`, `docs/ab-benchmark-results.md`).
- [x] **TASK-005**: Package for GitHub Push & Cloudflare Edge Deployment (`.gitignore`, `pyproject.toml`, `LICENSE`, `THIRD_PARTY_NOTICES.md`, `README.md`, `.github/workflows/{ci,release-windows}.yml`, `wrangler.toml`, `cloudflare/src/worker.js`, `cloudflare/public/index.html`, `docs/launch-checklist.md`).
- [x] **TASK-006**: Package, Static-Audit (`LOW` risk, `0` findings), and Promote `luminara-browser` Skill to Antigravity & Hermes Main Skills + Run Final Independent Double-Check Audit.
