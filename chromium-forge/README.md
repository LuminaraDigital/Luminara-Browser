# Luminara Browser Forge (`ungoogled-chromium` Clean-Room Engine & Customizer)

Clean-room Python 3.11+ customization forge and agentic browser runtime for `ungoogled-software/ungoogled-chromium` (Chromium `157.0.8103.78`) and `ungoogled-software/ungoogled-chromium-windows`, verified against the **14-Obligation REA Gate** and **100x Benchmark Suite**.

## Quick Start

```powershell
cd chromium-forge

# 1. Create/update your custom fork profile & compile C++/GN overlay
python -m forge init --brand "Luminara Browser" --slug "luminara-browser" --trap-tld "void0" --search "duckduckgo"

# 2. Build an immediately runnable customized Windows x64 portable browser (<30s)
python -m forge build-portable

# 3. Launch your customized browser + Agent Daemon directly
.\dist\luminara-browser-win64\Launch-luminara-browser.cmd

# 4. Run the REA 14-Obligation Verification Gate + Strict Unit/Security Tests
python -W error -m unittest discover -s tests -v
python -m forge verify-rea

# 5. Open the interactive Forge Studio Cockpit (http://127.0.0.1:8795)
python -m forge studio
```

## Two Ways to Build & Customize

| Mode | Speed & Disk | What Gets Customized | Command |
| :--- | :--- | :--- | :--- |
| **Mode A: Instant Portable Distribution** | ~15s · ~500 MB | Offline New Tab Command Deck, Generative UI Studio, Privacy Shield v3 (`.void0` DNR + eTLD+1 farbling + W3C WebMCP), MV3 Side Panel Copilot, Windows DPAPI/AEAD Vault, and 20-Tool MCP v2 Agent Daemon (`:8796`) | `python -m forge build-portable` |
| **Mode B: Full C++ Source Compilation** | ~16–30h · ~150 GB (or GitHub Actions) | Compile-time `14,266` binary pruning, `108` core + `26` Windows Quilt `-p1` patches + `4` Luminara C++ engine patches, C++ `URLRequest` `.<trap_tld>` -> `trk:` sink, `prepopulated_engines.json` ID-1 replacement, sorted `args.gn`, signed `.zip` | `python -m forge export-windows-overlay` |

## Architecture (`forge/`)

- `forge/models.py` — Typed `ForkProfile` & privacy search presets (`duckduckgo`, `brave`, `startpage`, `searxng`, `kagi`, `nosearch`, or `custom`).
- `forge/cdp_client.py` & `forge/cdp_mux.py` — Pure-stdlib RFC 6455 WebSocket + `MultiplexedCDPPool` (`<1.5ms` RTT), `TabLeaseManager`, SSRF guards, OOPIF/frame routing, and native JS dialog policy.
- `forge/luminara_crypto.py` & `forge/luminara_security.py` — Windows DPAPI + AEAD (`HKDF-SHA256-CTR-HMAC`) origin-pinned Model-Blind Vault, RFC 6238 TOTP, `EphemeralSessionSigner`, and `LuminaraRedactor`.
- `forge/luminara_automation.py` — Self-improving `PlaybookMemory` (zero-LLM replay + SHA-256 verification), `TrajectoryCompressor`, and AST-sandboxed `PipelineSandboxRunner`.
- `forge/perception.py`, `forge/webmcp.py`, `forge/mutation_firewall.py`, `forge/knowledge_graph.py` — Blink `AXTree` + Shadow-DOM perception, W3C WebMCP (`navigator.modelContext`), `Fetch.enable` savepoints, and SQLite WAL + FTS5 workspaces.
- `forge/agent_engine.py`, `forge/agent_server.py`, `forge/agent_tools_100x.py` — Hash-chained + HMAC-signed `ActionLedger` (`LUM-*`), `BulkEngine`, `AgentGoalRunner`, and 20-Tool MCP v2 + REST daemon (`127.0.0.1:8796`).
- `forge/studio.py` & `forge/ui/index.html` — Local Forge Customization Cockpit (`127.0.0.1:8795`).
