# log-analyzer-psbcg433

Analyze web-server access logs, plain text or gzip-compressed, from the command line or from
Python. Get a summary report (status codes, busiest endpoints, p95 latency, malformed lines),
or export every parsed request to **CSV**, **JSON** or **SQLite**.

- Reads `.gz` logs transparently. Compression is detected from the file's content, not its name.
- Streams the file: one line in memory at a time while parsing and exporting.
- Never stops on a bad line. Malformed lines are counted, reported and, in SQLite exports,
  stored in their own table.
- No runtime dependencies (standard library only), typed (`py.typed`), Python 3.12+.

## Install

The package is published to **TestPyPI**. It has no dependencies, so the TestPyPI index alone
is enough:

```bash
# as a command-line tool, in its own isolated environment
uv tool install --index-url https://test.pypi.org/simple/ log-analyzer-psbcg433

# or into the current environment
pip install --index-url https://test.pypi.org/simple/ log-analyzer-psbcg433
```

From a checkout of the repository:

```bash
uv tool install ./projects/log-analyzer
```

The distribution is called `log-analyzer-psbcg433`; the import package is `log_analyzer` and
the command is `log-analyzer` (`python -m log_analyzer` works too).

## Log format

One request per line:

```text
2026-11-06T09:00:00Z 10.0.2.17 "GET /api/products/381 HTTP/1.1" 200 23ms
timestamp            client IP  method path              protocol  status latency
```

A line is **malformed** if it does not have this shape (`unrecognized format`), uses an unknown
HTTP method (`unknown method`) or has a status outside 100–599 (`status out of range`).

## Usage

```text
usage: log-analyzer [-h] [--version] [-v | -q] [--log-file LOG_FILE]
                    COMMAND ...

positional arguments:
  COMMAND
    generate           write a seeded synthetic access log
    report             print a summary report
    export             export parsed records to CSV, JSON or SQLite
    validate           exit 1 if any line is malformed

options:
  -v, --verbose        log more on stderr (-v, -vv)
  -q, --quiet          log only errors
  --log-file LOG_FILE  also write DEBUG logs to this file
```

Global options (`-v`, `-q`, `--log-file`) go **before** the command. Logs are written to
stderr, so stdout carries only the command's output and can be piped.

### Generate a sample log

```console
$ log-analyzer generate access.log.gz -n 20000
wrote 20,000 lines to access.log.gz (431 malformed: garbage 100, status out of range 110, truncated 116, unknown method 105)
```

The same `--seed` (default 42) always produces the same file, byte for byte, even when
compressed.

### Report

```console
$ log-analyzer report access.log.gz --top 3
WARNING log_analyzer.analysis: 431 of 20000 lines in access.log.gz are malformed (2.2%)
=====================ACCESS LOG REPORT======================
Lines read                                            20,000
Records parsed                                        19,569
Malformed lines                                          431
Overall p95 latency (ms)                                 225
Status codes -----------------------------------------------
Status  Class                        Requests          Share
200     success                        15,690          80.2%
...
Top endpoints ----------------------------------------------
Endpoint                               Requests       p95 ms
GET /api/products                         5,904          120
GET /api/products/{id}                    4,798           74
POST /api/cart/items                      2,417          181
...
```

`--format json` prints the same facts as a JSON document (`lines_read`, `records_parsed`,
`malformed_lines`, `p95_latency_ms`, `status_counts`, `top_endpoints`, `malformed_by_reason`).
Endpoints are normalized: `/api/orders/42?expand=items` counts as `GET /api/orders/{id}`.

### Export

The format comes from the output's extension (`.csv`, `.json`, `.db`, `.sqlite`, `.sqlite3`)
or from `--format`. An existing output file is replaced.

```console
$ log-analyzer -q export access.log.gz records.csv
exported 19,569 records to records.csv (csv); 431 malformed lines skipped
$ head -2 records.csv
timestamp,client_ip,method,path,endpoint,status,latency_ms
2026-11-06T09:00:01Z,10.0.0.152,GET,/api/products?page=4,GET /api/products,200,216

$ log-analyzer -q export access.log.gz records.db
exported 19,569 records to records.db (sqlite); 431 malformed lines stored in table 'malformed'
$ sqlite3 records.db "SELECT endpoint, COUNT(*) FROM records WHERE status >= 500
                      GROUP BY endpoint ORDER BY 2 DESC LIMIT 2"
GET /api/products|112
GET /api/products/{id}|88
```

| Format | Contents |
| --- | --- |
| CSV | header + one row per record: `timestamp, client_ip, method, path, endpoint, status, latency_ms` |
| JSON | an array of record objects with the same keys |
| SQLite | table `records` (same columns, indexed on `endpoint` and `status`) and table `malformed` (`line_number`, `reason`, `line`) |

### Validate

```console
$ log-analyzer validate access.log.gz --show 2
access.log.gz: FAILED, 431 malformed lines
  line 64: unrecognized format: '-'
  line 127: status out of range: '2026-11-06T09:01:46Z 10.0.2.31 "GET /api/products '
  ... and 429 more
$ echo $?
1
```

### Exit status

| Code | Meaning |
| --- | --- |
| 0 | success |
| 1 | `validate` found malformed lines |
| 2 | bad arguments, missing or unreadable file (for example a truncated `.gz`), unknown export format |

## Library use

```python
from pathlib import Path

from log_analyzer import analyze_access_log, render_report, top_endpoints

summary, malformed = analyze_access_log(Path("access.log.gz"))
print(summary.record_count, len(malformed))
print(top_endpoints(summary, 3))
print(render_report(summary, malformed))

# strict mode: every malformed line at once, as an ExceptionGroup
try:
    analyze_access_log(Path("access.log.gz"), strict=True)
except* ValueError as group:
    print(f"{len(group.exceptions)} malformed lines")
```

The package logs through `logging.getLogger("log_analyzer")` and never configures logging
itself (it only adds a `NullHandler`), so it stays silent inside your application until you
configure logging.

## Development

```bash
cd projects/log-analyzer
uv sync                       # creates .venv from uv.lock (dev tools included)
uv run ruff check .
uv run ruff format --check .
uv run mypy --strict          # src and tests (strict is also set in pyproject.toml)
uv run pytest                 # tests + coverage; fails under 90%
uv build                      # sdist + wheel in dist/
```

Set `HYPOTHESIS_PROFILE=ci` for derandomized (reproducible) property tests; CI does.

## Releasing

Pushing a tag `log-analyzer-vX.Y.Z` runs the GitHub Actions workflow
`.github/workflows/log-analyzer.yml`: tests on Python 3.12–3.15, a build, a check that the tag
matches the version in `pyproject.toml`, then a publish to TestPyPI through **trusted
publishing** (OIDC, no API token stored anywhere).
