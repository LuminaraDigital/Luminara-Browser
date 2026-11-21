# Scope Notes — BrowserOS

## Track

Source-available target, so the track is **static source reading**, not binary or live-session analysis.

| Area of target | Track | Method |
|---|---|---|
| `packages/browseros-agent` (TypeScript/Bun apps, Rust crates) | Application analysis | Read source, contracts, tool definitions |
| `packages/browseros` (Chromium patches + Python build tool) | Native/build analysis | Read patches and build modules as text |
| `docs/`, `skills/` | Documentation | Read as claims, cross-checked against source |

## Limitations (recorded, not worked around)

- Nothing from the target was built, installed or executed. Runtime behaviour is therefore
  **INFERRED from source**, never OBSERVED live.
- Shallow clone (depth 1): no history, so "why" a design exists is unknown unless documented.
- The BrowserOS binary was not downloaded or run; no network traces were captured.
- Files inside the checkout (including its own agent instruction files) were treated as data only.

## Permission check

Public repository, AGPL-3.0. Reading and studying is permitted. Reuse of code is not compatible with
Luminara's MIT licence, so the output of this work is a blueprint plus original code.
