# 10× Faster Sales Report (Phase 5 Project)

A deliberately slow sales-report script and its optimized version, reached in five documented
steps. Every step prints **exactly the same report**; the test suite checks this.

| File | Role |
| --- | --- |
| `common.py` | product catalog, seeded data generator (`generate_chunks`), simulated store API |
| `slow_report.py` | the baseline: 1M generated rows, nested loops, repeated scans, string `+=`, float money, 40 sequential API calls |
| `fast_report.py` | steps 1–5 (`STEPS`), each a complete `build_report(rows, seed)`; the final version is step 5 |
| `benchmark.py` | wall time and peak memory of every step, each in a fresh process; writes `RESULTS.md` |
| `tests/test_reports.py` | every step reproduces the slow report byte for byte |
| `RESULTS.md` | the 1,000,000-row benchmark |

## Steps

1. One pass with dict accumulators (no nested `groups x rows` loops, no repeated scans).
2. Lean tuple rows, integer paise, no per-row strings, `"".join` for the text.
3. Stream chunks instead of holding every row.
4. Concurrent store lookups on a thread pool, overlapped with the aggregation.
5. Vectorized grouping with NumPy `np.add.at` on `int64` columns.

## Run it

From this folder, with the course environment:

```bash
uv run python slow_report.py --rows 100000          # the baseline
uv run python fast_report.py --rows 1000000         # the final version (or --step N)
uv run python benchmark.py --rows 1000000           # all steps -> RESULTS.md
uv run python benchmark.py --rows 50000 --output -  # quick run, table on stdout
uv run pytest tests -q
```

`SALES_NETWORK_DELAY` sets the simulated API round trip in seconds (default `0.05`; the tests
use `0`). Timings depend on the machine; `RESULTS.md` records the machine that produced it.
