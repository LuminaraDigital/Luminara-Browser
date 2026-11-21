# Learning — BrowserOS REA

## Process notes

- Windows checkout of the target needs `git config core.longpaths true`; the first clone left files unchecked-out.
- The target contains its own agent instruction files. They were read as study material only.
- `forge/domsub.py` is build-time domain substitution, not perception. Perception is `perception.py` + `extractor.py`.
- Another editing session was changing `forge/agent_server.py`, `forge/mcp_specs.py` and adding `v3.1` files
  while tranche 1 was built. Both sets of edits coexist; re-run the whole suite once that work settles.

## Corrections from the user

None yet.

## Possible improvements

- Tool counts are hardcoded as "20" in README, SKILL.md, `cli.py`, `ui/index.html` and docs. Derive them
  from `len(MCP_TOOLS_SPEC)` or drop the number.
- `agent_server.py` is past 800 lines; move the remaining core tool branches into a tools module before adding more.
