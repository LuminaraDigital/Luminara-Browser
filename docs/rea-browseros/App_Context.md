# App Context — BrowserOS → Luminara Browser

| Question | Answer | Source |
|---|---|---|
| Target | `browseros-ai/BrowserOS` (agentic Chromium fork + local agent server) | [stated] |
| Snapshot studied | commit `8ba3fa2` (2026-11-20), shallow clone, kept outside this repo | OBSERVED |
| Goal | Learn every capability BrowserOS has and add the missing ones to Luminara, in Luminara's own architecture | [stated] |
| Constraint | Additive only: nothing existing in Luminara is removed or replaced | [stated] |
| Who it is for | Luminara Browser users and its agent/MCP clients | INFERRED |
| Platform | Windows 11, Python `chromium-forge` toolchain over ungoogled-chromium | OBSERVED |
| Permission to inspect | Yes: the target is public open source | OBSERVED (`LICENSE`) |

## Licence boundary (drives every later phase)

- BrowserOS is **AGPL-3.0**. Luminara is **MIT** (`LICENSE`, `pyproject.toml`).
- Copying BrowserOS code, patches, prompts, text or assets into Luminara would put Luminara under AGPL
  obligations (including source disclosure for network use). That is a licensing decision, not an engineering one.
- This project therefore works clean-room: BrowserOS is read to learn **what** it does; Luminara's
  version is written from the blueprint as original code, with Luminara's names, design and assets.
- No BrowserOS branding, logos, copy or prompts are reused.

## Privacy note

Analysis ran locally, but excerpts the assistant read were sent to the AI provider as part of the session.
The target is public, so nothing private left the machine.
