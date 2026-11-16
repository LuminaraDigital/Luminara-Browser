# Luminara Browser — Live A/B Benchmark Results

- **Overall Gate**: `4/4 PASSED` (`2734.0 ms`)

| Exp ID | Experiment | Variant A (Control) | Variant B (Luminara Default) | Key Measured Delta | Status |
| :--- | :--- | :--- | :--- | :--- | :---: |
| **AB-01** | Multi-Tab Research Throughput | `1062.0 ms` (Sequential) | `234.0 ms` (Per-Domain Parallel) | **`4.54x` speedup**, `8/8` fault-isolated | **PASS** |
| **AB-02** | Set-of-Marks Token & Injection Safety | `2417` tokens (leaked=`True`) | `79` tokens (leaked=`False`) | **`-96.7%` tokens**, `0%` hidden injection leak | **PASS** |
| **AB-03** | Synthesis UX & `320px` Reflow | `6` card scans (`O(N)`) | `1` click sort (`O(1)`) | Top=`EdgeNova`, `320px` overflow=`0px` | **PASS** |
| **AB-04** | Multi-LLM Failover & Zero-Key Cold Start | `0.0%` completion | `100.0%` completion | **`0.0 ms`** avg failover across 4 fault modes | **PASS** |
