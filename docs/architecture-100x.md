# Luminara Browser v3.0 — 100x Engine Architecture (`docs/architecture-100x.md`)

Luminara Browser v3.0 closes every security, latency, perception, and build gap vs. upstream `chromium/chromium` while introducing first-party primitives Google Chrome cannot ship due to ad/telemetry conflicts.

```mermaid
flowchart TB
    subgraph Upstream["Phase 0 & 5: Chromium Source + 16-Stage Cloud Compiler"]
        Sparse["vendor/chromium-src (Blobless Sparse Checkout <150 MB)"]
        Patches["chromium-forge/patches/luminara/ (4 Zero-Fuzz C++ Patches)"]
        CloudCI["16-Stage Checkpointed x64/arm64 PGO+ThinLTO Workflow"]
    end

    subgraph Runtime["Phase 1–4: Luminara v3.0 Agentic & Privacy Kernel (:8796)"]
        Crypto["luminara_crypto.py (Windows DPAPI + PBKDF2 AEAD + Ephemeral HMAC)"]
        Mux["cdp_mux.py (Single Browser WS + Flat Sessions + Event Ring Buffer)"]
        AX["perception.py (Blink AXTree + Shadow-DOM + OOPIF + Hardware Input)"]
        WebMCP["webmcp.py (W3C navigator.modelContext + Declarative Form Compiler)"]
        MutFW["mutation_firewall.py (Fetch.enable POST/PUT/PATCH/DELETE Savepoints)"]
        KG["knowledge_graph.py (SQLite WAL+FTS5 Workspaces + Tab Hibernation)"]
        Shield["shield_compiler.py (DNR Trackers + Param Scrub + eTLD+1 Farbling)"]
    end

    Sparse --> Patches --> CloudCI
    Crypto <--> Mux
    Mux --> AX & WebMCP & MutFW
    AX & WebMCP & MutFW <--> KG
    Shield --> Runtime
```

## Module Map (All Files `< 1,000` Lines, Zero Third-Party Python Dependencies)

| Module | Responsibility |
| :--- | :--- |
| `chromium-forge/forge/chromium_src.py` | Blobless sparse checkout (`<150 MB`), upstream patch dry-run & version provenance audit |
| `chromium-forge/forge/luminara_crypto.py` | Windows DPAPI (`CryptProtectData`), pure-stdlib HKDF+CTR+HMAC AEAD, ephemeral session tokens, ledger signatures |
| `chromium-forge/forge/luminara_security.py` | AEAD-encrypted origin-pinned `LuminaraVault` (auto-migrates legacy plaintext) & binary-safe `LuminaraRedactor` |
| `chromium-forge/forge/cdp_mux.py` | Persistent browser-level multiplexed CDP WebSocket (`<1.5ms` RTT, zero `F12` lockouts, OOPIF flat sessions, event bus) |
| `chromium-forge/forge/perception.py` | Native Blink `AXTree` + open Shadow-DOM piercing + OOPIF indexing + compositor hardware mouse/keyboard input |
| `chromium-forge/forge/webmcp.py` | W3C WebMCP (`navigator.modelContext`) bootstrap + declarative `<form toolname>` / semantic form compiler |
| `chromium-forge/forge/mutation_firewall.py` | `Fetch.enable` savepoint interceptor pausing `POST`/`PUT`/`PATCH`/`DELETE` with secret-scrubbed diff preview |
| `chromium-forge/forge/knowledge_graph.py` | SQLite WAL + FTS5 cross-tab knowledge graph, named Workspaces, and `Page.setWebLifecycleState('frozen')` tab hibernation |
| `chromium-forge/forge/shield_compiler.py` | Privacy Shield v3 (DNR tracker + query-param strip compiler up to 30k rules + eTLD+1 deterministic farbling) |
| `chromium-forge/forge/updater.py` | Zero-telemetry opt-in cryptographic release manifest & SHA-256 artifact verifier |
| `chromium-forge/forge/benchmark_100x.py` | Automated `BM-01`..`BM-06` 100x engine benchmark suite |
| `chromium-forge/patches/luminara/*.patch` | 4 zero-fuzz native C++ Chromium patches (`luminara://` WebUI, `URLLoaderThrottle` hooks, `SidePanelCoordinator`, farbling switches) |
