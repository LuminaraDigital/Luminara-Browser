# Evidence Ledger — BrowserOS @ `8ba3fa2`

Tags: **OBSERVED** = read directly in the named file. **INFERRED** = concluded from source without
running it. **UNKNOWN** = looked for, not found. Paths are relative to the target checkout.
Nothing was executed, so every runtime behaviour is at best INFERRED.

## Phase 2 — scope

| Finding | Tag | Source |
|---|---|---|
| Licence is AGPL-3.0 | OBSERVED | `LICENSE` |
| Chromium pin 155.0.8059.26 | OBSERVED | `packages/browseros/CHROMIUM_VERSION` |
| Two product generations in one repo: built-in chat agent (TypeScript) and "neo" server for external agents (Rust) | OBSERVED | `packages/browseros-agent/apps/*`, `crates/*` |

## Phase 3 — perception and action

| Finding | Tag | Source (`packages/browseros-agent/crates/browseros-core/src/`) |
|---|---|---|
| Snapshot is an indented accessibility outline with `[ref=eN]` | OBSERVED | `snapshot/render.rs` |
| Refs are stable per document (frame + loader identity), recovered by role/name/position | OBSERVED | `snapshot/refs.rs` |
| Names are quoted so page text cannot forge a ref line | OBSERVED | `snapshot/render.rs` |
| Line diff with context; URL change returns full snapshot | OBSERVED | `snapshot/diff.rs` |
| Unreadable frames are reported as unknown, not removed | OBSERVED | `snapshot/coverage.rs` |
| Settle uses an in-page mutation counter installed and read in one call | OBSERVED | `settle.rs` |
| Settle does not cross iframe or shadow boundaries | OBSERVED (documented gap) | `settle.rs` |
| Click waits for two matching geometry observations, falls back once | OBSERVED | `input/click.rs` |
| Non-semantic clickables found via DOM snapshot, without page JS | OBSERVED | `observer/clickable.rs` |

## Phase 3 — tools, agent loop, safety

| Finding | Tag | Source (`packages/browseros-agent/`) |
|---|---|---|
| 22 base tools + up to 8 conditional | OBSERVED | `crates/browseros-mcp/src/tools/mod.rs`, `apps/claw-server/src/api/mcp/service.rs` |
| Classic agent: 17 browser + 7 filesystem + 2 nudge tools | OBSERVED | `packages/browser-mcp/src/tools/registry.ts`, `apps/server/src/tools/filesystem` |
| Page output fenced with per-call nonce | OBSERVED | `crates/browseros-mcp/src/trust_boundary.rs` |
| Working overlay with heartbeat, input shield, 20 s quiet grace | OBSERVED | `apps/claw-server/src/services/page_hold/mod.rs`, `crates/browseros-core/src/overlay.rs` |
| After takeover the next page-changing call is refused once | OBSERVED | `apps/claw-server/src/api/mcp/guards/person_control.rs` |
| Scheduled tasks run from extension alarms, daily/hourly | OBSERVED | `apps/app/entrypoints/background/scheduledJobRuns.ts`, `docs/browseros/features/scheduled-tasks.mdx` |
| Compaction prunes tool exchanges then oldest messages | OBSERVED | `apps/server/src/agent/compaction.ts` |
| Per-host helper files and flows with verify gates | OBSERVED | `apps/claw-server/src/services/helpers.rs`, `flow/verify.rs` |
| Persona/memory file loading | UNKNOWN | constant only, `packages/shared/src/constants/paths.ts` |
| Workflow/graph mode | UNKNOWN | image only in `docs/browseros/features/workflow/` |
| General tool rate limiter | UNKNOWN | not found |

## Phase 3 — Chromium patches and build

| Finding | Tag | Source (`packages/browseros/`) |
|---|---|---|
| ~425 per-file patches grouped by a feature map | OBSERVED | `chromium_patches/`, `.features.yaml` |
| Custom CDP domains: tabs, windows, tab groups, bookmarks, history, credentials | OBSERVED | `chromium_patches/third_party/blink/public/devtools_protocol/domains/*.pdl` |
| Browser launches and health-checks the agent server, ports stored in prefs | OBSERVED | `chromium_patches/chrome/browser/browseros/server/` |
| MCP proxy binds all interfaces | OBSERVED | `.../server/browseros_server_proxy.cc` |
| Debugger warning suppressed for all extensions | OBSERVED | `chromium_patches/.../debugger_api.cc` |
| Build plan composed by a pure function, with show-plan/skip/from | OBSERVED | `bos_build/core/planner.py` |
| Core ungoogled patch set not applied | INFERRED | `series_patches/series` is empty |

## What was acted on

Tranche 1 in `Blueprint.md`: stable refs, outline diff, settle, nonce fence, scheduled goals, four MCP tools.
The first six rows of "perception and action" and the scheduled-tasks row are the evidence behind it.
