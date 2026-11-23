# Blueprint — BrowserOS capabilities, rebuilt for Luminara

Source snapshot: `browseros-ai/BrowserOS` @ `8ba3fa2` (AGPL-3.0). Everything below was learned by
reading source; nothing was run, so target behaviour is **INFERRED from source** unless noted.
Luminara's versions are original code (MIT). Evidence paths are in `Evidence_Ledger.md`.

## Where each system is stronger

| Area | BrowserOS | Luminara today |
|---|---|---|
| Element identity | Refs stable per document, recovered after re-render | **Built in tranche 1** (was per-snapshot indices) |
| "What changed?" | Outline diff after every action | **Built in tranche 1** (had none) |
| Waiting | DOM-mutation settle, no fixed sleeps | **Built in tranches 1–2**: tool, and the goal loop after scroll/click/type |
| Injection defence | Per-call nonce fence on page text | **Built in tranche 1** for outline output; older tools still use a static tag |
| Scheduled tasks | Daily/hourly via extension alarms | **Built in tranche 1** (interval/daily, human-gated) |
| Screenshot tool | MCP tool | **Built in tranche 1** (was REST only) |
| Tabs/windows/groups, bookmarks, history | Custom CDP domains patched into Chromium | Missing; needs C++ patches or the side-panel extension |
| Takeover | Input shield + overlay + heartbeat, refuse-once guard | **Built in tranche 2** (was lease preemption and a HUD pill) |
| Code-mode `run` tool | Sandboxed JS SDK | Has an equivalent: AST-checked Python pipeline |
| Learned automations | Per-host helpers, verified flows with commit step | Has playbooks; no verify gates or commit marking |
| Connectors / external MCP | Hosted connector service + custom MCP client | Missing (server only) |
| LLM loop | Tool-calling, 13 providers, token-aware compaction | One JSON action per step, 4 providers, step-count compaction |
| Mutation firewall, hash-chained signed ledger, model-blind vault with TOTP, FTS5 knowledge store | Not found in target | **Luminara only** |
| Build: patch store | ~425 per-file patches, feature map, doctor, converge tool | Quilt series, 4 scaffolding patches |
| Agent sidecar | Browser launches, health-checks, updates it | Started separately by launcher script |

## Tranche 1 — built and tested

| Part | File | What it does |
|---|---|---|
| Stable-ref outline | `chromium-forge/forge/perception_refs.py` | Accessibility tree as indented lines; controls get `[ref=eN]` that persists within a document |
| Outline diff | same | Lines added/removed since the last read; a new document returns the full outline |
| Settle | same | Waits for load + quiet DOM; a navigation mid-wait counts as activity |
| Untrusted fence | same | Wraps page text in markers with a fresh nonce per call |
| Scheduled goals | `chromium-forge/forge/scheduler.py` | Interval or daily tasks, persisted, run through the normal goal runner |
| Tools | `chromium-forge/forge/agent_tools_flow.py` | `browser_outline`, `browser_wait`, `browser_screenshot`, `browser_schedule` |
| Tests | `chromium-forge/tests/test_luminara_flow_tools.py` | 14 tests, no live browser needed |

Deliberate differences from the target:

- Creating, enabling or force-running a schedule over MCP needs the human UI key. An agent that read a
  hostile page must not be able to install a recurring job.
- Refs are only inherited from a control that has vanished, so two live controls can never share one.

Not verified: none of tranche 1 has run against a live Chromium. The tests use a mocked CDP bridge.

## Tranche 2 — built and tested (including against headless Chromium)

| Part | File | What it does |
|---|---|---|
| Presence shield | `chromium-forge/forge/presence.py` | Banner naming the agent; the person's clicks and keys are held between agent actions; "Take over" button or Escape hands the tab back; clears itself 20 s after the agent's last action |
| Refuse-once guard | `TabLeaseManager` in `chromium-forge/forge/cdp_client.py` | After a takeover, the interrupted agent's next page-changing call on that tab fails once with a clear message, then proceeds |
| Goal loop | `chromium-forge/forge/agent_engine.py` | Settles instead of sleeping; a takeover mid-run ends the goal as `STOPPED_HUMAN_TAKEOVER` |
| Tests | `chromium-forge/tests/test_luminara_presence.py` | 3 unit tests + 1 live test |

Deliberate differences from the target:

- The shield runs in the page's own script world, not an isolated one. A page can therefore remove it or
  fake a takeover, but both only unblock the person or stop the agent, so the failure direction is safe.
- Only the agent that was actually interrupted is refused. Refusing every agent broke the existing
  takeover-then-act obligation (OBL-09/10).
- While the agent's 1.5 s action window is open the person's input also passes.

## Next tranches (ordered by value per effort)

1. **Feed the outline diff to the planner** instead of a fresh 40-element snapshot each step. (M)
2. **Shield heartbeat for long goals** — refresh while the model is thinking, so a slow model does not let
   the shield lapse after 20 s. (S)
3. **Browser-state tools without C++** — bookmarks, history, tab groups, windows through the existing MV3
   side-panel extension (`chrome.bookmarks`, `chrome.history`, `chrome.tabGroups`, `chrome.windows`),
   bridged to the daemon. (M)
4. **More act kinds on refs** — press, hover, select, check, drag, upload, download, fill-many. (M)
5. **Large-output spill** — outputs over a budget go to a file with an inline excerpt and a
   `browser_read_output` tool. (S)
6. **Sensitive-call classifier** — tag vault and payment calls so the ledger redacts and screenshots are
   suppressed until the document changes; mask card-number-shaped values in outlines. (S)
7. **Playbook verify gates** — require N successful examples, mark the committing step, return a
   handover packet saying whether the commit already happened. (M)
8. **External MCP client** — let the goal runner call user-configured MCP servers. (M)
9. **Tool-calling LLM loop with token-aware compaction.** (L)
10. **Build tooling** — per-file feature-tagged patch store with a dry-run doctor; composed build plan
    with `--show-plan`, `--from`, env preflight. (M each)
11. **C++ tranche** — custom CDP domains for tabs/windows/groups with tab↔target mapping, a
    never-steal-focus pref, browser-supervised daemon launch with health checks. (L, needs full builds)

## Things in the target that should not be carried over

- The MCP proxy binds all interfaces; keep Luminara on loopback.
- The "extension is debugging this browser" warning is suppressed for every extension.
- Hosted, licence-gated pieces (decision model, CAPTCHA solving, connector auth) have no local source to learn from.

## Open unknowns

- How the target's persona/memory file is loaded (constant found, loader not traced).
- Workflow/graph mode: only a screenshot exists in the docs; no implementation found.
- Whether the upstream ungoogled patch set is applied in the target (its common series file is empty).
