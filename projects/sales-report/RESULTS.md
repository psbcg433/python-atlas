# Sales report benchmark

- Rows: **1,000,000**, seed 42, best of 1 run(s) per step, each step in a fresh process; measured 2026-11-17
- Python 3.15.1 (default (GIL) build), NumPy 2.5.4, Linux x86_64, 16 CPUs
- Simulated store API: 40 calls x 0.050 s each
- Peak memory is the process's peak RSS; Python + NumPy imports alone: 35.6 MiB

| Step | Change | Time | Peak memory | Reason |
| --- | --- | --- | --- | --- |
| 0 | Baseline: `slow_report.py` | 12.149 s | 469.3 MiB | nested loops, repeated scans, 1M dicts, float money, string `+=`, 40 sequential API calls |
| 1 | One pass with dict accumulators | 5.467 s (2.2x faster) | 469.7 MiB (1.0x less) | O(groups x rows) nested loops and repeated scans become one O(rows) pass |
| 2 | Lean tuple rows, integer paise, `join` | 2.731 s (4.4x faster) | 131.0 MiB (3.6x less) | no per-row dicts, strings or floats: fewer allocations, exact money |
| 3 | Stream chunks, no list of all rows | 2.690 s (4.5x faster) | 53.2 MiB (8.8x less) | only one 100k-row chunk alive at a time: peak memory stops growing with rows |
| 4 | Concurrent store lookups (thread pool) | 0.683 s (17.8x faster) | 54.4 MiB (8.6x less) | 40 x 50 ms waits overlap each other and the CPU work (`sleep`, like socket I/O, releases the GIL) |
| 5 | Vectorize grouping with NumPy `np.add.at` | 0.095 s (128.3x faster) | 48.1 MiB (9.8x less) | per-row Python bytecode replaced by C loops over int64 columns |

**Result: 128.3x faster and 9.8x less peak memory** (step 0 -> step 5); target >= 10x faster and >= 3x less memory: met.

Reports identical across all steps: yes (SHA-256 `edc9a13246dff7e5...`).
