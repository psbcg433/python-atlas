# Sales report benchmark

- Rows: **1,000,000**, seed 42, 3 run(s) per step (best and median shown), each run in a fresh process; measured 2026-11-17
- Python 3.15.1 (default (GIL) build), NumPy 2.5.4, Linux x86_64, 16 CPUs
- Simulated store API: 40 calls x 0.050 s each
- Peak memory is the highest peak RSS of the runs; Python + NumPy imports alone: 35.5 MiB

| Step | Change | Time (best) | Time (median) | Peak memory | Reason |
| --- | --- | --- | --- | --- | --- |
| 0 | Baseline: `slow_report.py` | 7.235 s | 7.316 s | 469.2 MiB | nested loops, repeated scans, 1M dicts, float money, string `+=`, 40 sequential API calls |
| 1 | One pass with dict accumulators | 3.730 s (1.9x faster) | 3.879 s (1.9x faster) | 470.4 MiB (1.0x less) | O(groups x rows) nested loops and repeated scans become one O(rows) pass |
| 2 | Lean tuple rows, integer paise, `join` | 2.374 s (3.0x faster) | 2.389 s (3.1x faster) | 131.4 MiB (3.6x less) | no per-row dicts, strings or floats: fewer allocations, exact money |
| 3 | Stream chunks, no list of all rows | 2.348 s (3.1x faster) | 2.362 s (3.1x faster) | 53.4 MiB (8.8x less) | only one 100k-row chunk alive at a time: peak memory stops growing with rows |
| 4 | Concurrent store lookups (thread pool) | 0.415 s (17.4x faster) | 0.426 s (17.2x faster) | 54.4 MiB (8.6x less) | 40 x 50 ms waits overlap each other and the CPU work (`sleep`, like socket I/O, releases the GIL) |
| 5 | Vectorize grouping with NumPy `np.add.at` | 0.078 s (92.7x faster) | 0.079 s (92.2x faster) | 48.6 MiB (9.7x less) | per-row Python bytecode replaced by C loops over int64 columns |

**Result: 92.7x faster and 9.7x less peak memory** (best runs, step 0 -> step 5; 92.2x faster by median); target >= 10x faster and >= 3x less memory: met.

Reports identical across all steps and runs: yes (SHA-256 `edc9a13246dff7e5...`).

**Run-to-run variation.** Spread of the 3 runs, (slowest - fastest) / median: step 0 7%, step 1 6%, step 2 1%, step 3 1%, step 4 3%, step 5 3%.

Wall times move with CPU frequency scaling, other load and cache state. The relative
spread is largest for the shortest steps, where a few milliseconds of noise are a big
share, and separate sessions on the same machine can differ by tens of percent for
every step, the baseline included. The best run is the least disturbed one and the
median a typical one; the targets are judged on the best runs, with the median ratio
printed next to them. Read the speedup as an order of magnitude.

`tests/test_reports.py::test_store_lookups_overlap` asserts that the final version with
40 simulated 50 ms store calls finishes in under 0.5 s, against 2 s if the calls ran
one after another. The threshold is deliberately loose: the overlapped calls take
about 50 ms, so only a regression to sequential calls (or a badly overloaded machine)
can fail it.
