# Luminara Browser — Live A/B Benchmark Results (`v3.0.0`)

- **Overall Gate**: `8/8 PASSED` (`6907.0 ms`)

| Exp ID | Experiment | Variant A (Control) | Variant B (Luminara `v3.0.0`) | Key Measured Delta | Status |
| :--- | :--- | :--- | :--- | :--- | :---: |
| **AB-01** | Multi-Tab Research Throughput | `1125.0 ms` (Sequential) | `235.0 ms` (Per-Domain Parallel) | **`4.79x` speedup**, `8/8` fault-isolated | **PASS** |
| **AB-02** | Set-of-Marks Token & Injection Safety | `2457` tokens (leaked=`True`) | `79` tokens (leaked=`False`) | **`-96.8%` tokens**, `0%` hidden injection leak | **PASS** |
| **AB-03** | Synthesis UX & `320px` Reflow | `6` card scans (`O(N)`) | `1` click sort (`O(1)`) | Top=`EdgeNova`, `320px` overflow=`0px` | **PASS** |
| **AB-04** | Multi-LLM Failover & Zero-Key Cold Start | `0.0%` completion | `100.0%` completion | **`0.0 ms`** avg failover across 4 fault modes | **PASS** |
| **AB-05** | CDP Command Transport Latency | `2.121 ms` (One-Shot WS) | `0.297 ms` (`MultiplexedCDPPool`) | **`7.15x` faster** p50 RTT | **PASS** |
| **AB-06** | Page Tool Discovery & Execution | `1061` tokens (Raw DOM) | `49` tokens (W3C WebMCP) | **`-95.38%` tokens**, 1-call schema invoke | **PASS** |
| **AB-07** | Mutation & Secret Isolation | Plaintext disk + unguarded `DELETE` | `dpapi` AEAD + `Fetch` Savepoint | **`0` plaintext bytes**, AAD tamper + secret scrub verified | **PASS** |
| **AB-08** | Cross-Tab Recall & Tab Hibernation | `20` unfrozen tabs + linear scan | `17` frozen + SQLite FTS5 | **`85%` tab freeze**, `3.466 ms` FTS5 recall | **PASS** |
