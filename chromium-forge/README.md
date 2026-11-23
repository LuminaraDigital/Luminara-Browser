# Luminara Browser Forge v4.0.0 (`ungoogled-chromium` Clean-Room Engine & Customizer)

Clean-room Python 3.11+ customization forge, native Rust Win32 Desktop Supervisor (`LuminaraBrowser.exe`), PiBot Multi-Bot Team Hub (`forge/agent_team_hub.py`), and 28-Tool MCP v2 agentic browser runtime for `ungoogled-software/ungoogled-chromium` (Chromium patch track `157.0.8103.78-1.1` · portable binary base `157.0.8103.50-1.1`) and `ungoogled-software/ungoogled-chromium-windows`, verified against the **21-Obligation REA Gate** and **100x Benchmark Suite**. Pairs with the Warm Atelier 3-Zone Spatial Desktop Shell in `../luminara-shell/` (`Launch-Luminara-v4.cmd`).

## Quick Start

```powershell
cd chromium-forge

# 1. Create/update your custom fork profile & compile C++/GN overlay
python -m forge init --brand "Luminara Browser" --slug "luminara-browser" --trap-tld "void0" --search "duckduckgo"

# 2. Build an immediately runnable customized Windows x64 portable browser + LuminaraBrowser.exe (<30s)
python -m forge build-portable

# 3. Launch Portable mode, Luminara v4 Spatial Shell, OR install Per-User into %LOCALAPPDATA%\Programs\Luminara Browser (zero UAC)
.\dist\luminara-browser-win64\LuminaraBrowser.exe
..\Launch-Luminara-v4.cmd
python -m forge install-desktop

# 4. Run Architecture Ratchet, Strict Unit/Security Suite & 21-Obligation REA Gate
python -m forge verify-arch
python -W error -m unittest discover -s tests -v
python -m forge verify-rea

# 5. Open the interactive Forge Studio Cockpit (http://127.0.0.1:8795)
python -m forge studio
```

## Two Ways to Build & Customize

| Mode | Speed & Disk | What Gets Customized | Command |
| :--- | :--- | :--- | :--- |
| **Mode A: Instant Desktop Distribution** | ~15s · ~500 MB | Native `LuminaraBrowser.exe` Win32 GUI Supervisor (`JobObject` + Tray v4 + Named Pipe IPC), Zero-UAC Per-User Installer, Warm Atelier Offline Calm Home + working private omnibox, Generative UI Studio, Interactive Privacy Shield v3, Warm Atelier Theme (`luminara-theme`), MV3 Side Panel Copilot, Windows DPAPI/AEAD Vault, PiBot Multi-Bot Team Hub, and 28-Tool / 9-Resource MCP v2 Agent Daemon (`:8796`) | `python -m forge build-portable` |
| **Mode B: Full C++ Source Compilation** | ~16–30h · ~150 GB (or GitHub Actions) | Compile-time `14,266` binary pruning, `108` core + `26` Windows Quilt `-p1` patches + `4` Luminara C++ engine patches (`157.0.8103.78-1.1`), C++ `URLRequest` `.<trap_tld>` -> `trk:` sink, `prepopulated_engines.json` ID-1 replacement, sorted `args.gn`, signed `.zip` | `python -m forge export-windows-overlay` |

## Architecture (`forge/`)

- `forge/models.py` — Typed `ForkProfile` & privacy search presets (`duckduckgo`, `brave`, `startpage`, `searxng`, `kagi`, `nosearch`, or `custom`).
- `forge/cdp_client.py` & `forge/cdp_mux.py` — Pure-stdlib RFC 6455 WebSocket + `MultiplexedCDPPool` (`<1.5ms` RTT), `TabLeaseManager`, SSRF guards, OOPIF/frame routing, and native JS dialog policy.
- `forge/luminara_crypto.py` & `forge/luminara_security.py` — Windows DPAPI + AEAD (`HKDF-SHA256-CTR-HMAC`) origin-pinned Model-Blind Vault, RFC 6238 TOTP, `EphemeralSessionSigner`, and `LuminaraRedactor`.
- `forge/luminara_automation.py` — Self-improving `PlaybookMemory` (zero-LLM replay + SHA-256 verification), `TrajectoryCompressor`, and AST-sandboxed `PipelineSandboxRunner`.
- `forge/perception.py`, `forge/webmcp.py`, `forge/mutation_firewall.py`, `forge/knowledge_graph.py` — Blink `AXTree` + Shadow-DOM perception, W3C WebMCP (`navigator.modelContext`), `Fetch.enable` savepoints, and SQLite WAL + FTS5 workspaces.
- `forge/agent_team_hub.py` — Luminara v4 Team Hub: AEAD-encrypted LLM config (`ollama`, `openrouter`, `gemini`, `anthropic`, `openai`, `custom`), PiBot Multi-Bot Teams (`Pi`, `Remy`, `Dana`, `Research Team`), live tab-grounded chat, unified Approval Inbox, Teach Mode recorder, tab focus, and Cross-Tab Live Lens.
- `forge/agent_engine.py`, `forge/agent_server.py`, `forge/mcp_specs.py`, `forge/agent_tools_core.py`, `forge/agent_tools_100x.py`, `forge/agent_tools_v31.py`, `forge/agent_desktop.py` — Hash-chained + HMAC-signed `ActionLedger` (`LUM-*`), `BulkEngine`, `AgentGoalRunner`, desktop supervisor heartbeat/takeover/shutdown, and 28-Tool / 9-Resource MCP v2 + REST daemon (`127.0.0.1:8796`).
- `forge/luminara_ui.py`, `forge/luminara_workspace_ui.py`, `forge/luminara_telemetry_ui.py`, `forge/luminara_copilot_ext.py`, `forge/portable.py` — Warm Atelier Light/Dark UI surfaces, Interactive Privacy Shield v3 popup, Warm Atelier Chromium theme, MV3 Side Panel Copilot, and `--release` secret-scrubbed portable packaging.
- `forge/studio.py` & `forge/ui/index.html` — Local Forge Customization Cockpit (`127.0.0.1:8795`).
