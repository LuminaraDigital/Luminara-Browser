# Luminara Browser v3.0 — 100x Benchmark Results

**Result:** `6 / 6 PASS`

| Benchmark | Status | Verified Metric |
| :--- | :---: | :--- |
| **BM-01: Persistent Multiplexed CDP Pipe vs. One-Shot WebSocket RTT** | **PASS** | Mux p50 `0.085 ms` vs One-Shot `14.661 ms` (`171.68x` faster) |
| **BM-02: DPAPI / AEAD Origin-Bound Encrypted Vault** | **PASS** | `dpapi` encryption, `0` plaintext bytes on disk, AAD tamper rejected |
| **BM-03: W3C WebMCP Schema vs. Raw DOM Token Footprint** | **PASS** | `-95.38%` tokens (`49` vs `1061`) |
| **BM-04: Network Mutation Firewall Savepoint & Secret Scrubbing** | **PASS** | Risk `HIGH`, secrets scrubbed=`True`, status=`REJECTED` |
| **BM-05: Privacy Shield v3 (DNR Rules + Query Scrubber + Deterministic Farbling)** | **PASS** | `72` DNR rules, 100% param scrub, deterministic eTLD+1 farbling |
| **BM-06: SQLite FTS5 Knowledge Graph + Background Tab Hibernation** | **PASS** | FTS5 `1.32 ms` (`10` hits), `85%` idle tab freeze |
