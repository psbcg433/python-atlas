"""Turn a Locust CSV run into the results section of LOAD_TEST.md.

    uv run python load/report.py --stats load/results/live_stats.csv --section live \
        --host https://<NOTES_HOST> --users 50 --duration 2m --prometheus http://127.0.0.1:9090

Reads <prefix>_stats.csv (written by locust --csv <prefix>), optionally asks Prometheus for
the server-side 95th percentile over the same window, checks the targets, and replaces the text
between <!-- results:<section>:start --> and <!-- results:<section>:end --> in LOAD_TEST.md.
"""

import argparse
import csv
import json
import re
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

P95_TARGET_MS = 200
MAX_FAILURE_RATIO = 0.01
MIN_THROUGHPUT_RPS = 100
SERVER_P95_QUERY = (
    "histogram_quantile(0.95, sum by (le) "
    "(rate(notes_http_request_duration_seconds_bucket{{route=~'/api/.*'}}[{window}])))"
)
COLUMNS = ("Requests", "Failures", "req/s", "p50 ms", "p95 ms", "p99 ms", "max ms")


def read_stats(stats_csv: Path) -> dict[str, dict[str, str]]:
    """Locust's rows keyed by "METHOD name" (GET and POST of one URL are separate rows) and
    "Aggregated" for the total."""
    with stats_csv.open(newline="") as stats_file:
        rows = list(csv.DictReader(stats_file))
    return {
        "Aggregated" if row["Name"] == "Aggregated" else f"{row['Type']} {row['Name']}": row
        for row in rows
    }


def endpoint_label(key: str) -> str:
    """Format a row key: GET /api/v1/notes becomes GET `/api/v1/notes`."""
    method, _, path = key.partition(" ")
    return f"{method} `{path}`"


def endpoint_row(label: str, row: dict[str, str]) -> str:
    """One markdown table row."""
    cells = (
        row["Request Count"],
        row["Failure Count"],
        f"{float(row['Requests/s']):.1f}",
        row["50%"],
        row["95%"],
        row["99%"],
        f"{float(row['Max Response Time']):.0f}",
    )
    return f"| {label} | " + " | ".join(cells) + " |"


def server_p95_ms(prometheus_url: str, window_seconds: int) -> float | None:
    """The 95th percentile measured inside the API (no network), or None when unavailable."""
    query = SERVER_P95_QUERY.format(window=f"{window_seconds}s")
    url = f"{prometheus_url}/api/v1/query?" + urllib.parse.urlencode({"query": query})
    try:
        with urllib.request.urlopen(url, timeout=5) as reply:
            result = json.load(reply)["data"]["result"]
        value = float(result[0]["value"][1]) * 1000 if result else None
    except OSError, ValueError, KeyError, IndexError:
        return None
    return None if value is None or value != value else value  # NaN: no samples


def verdict(passed: bool) -> str:
    """PASS or FAIL in bold."""
    return "**PASS**" if passed else "**FAIL**"


def build_section(stats: dict[str, dict[str, str]], args: argparse.Namespace) -> str:
    """The markdown that goes between the section markers."""
    total_key = "Aggregated"
    total = stats[total_key]
    requests_made, failures = int(total["Request Count"]), int(total["Failure Count"])
    failure_ratio = failures / requests_made if requests_made else 1.0
    client_p95, throughput = float(total["95%"]), float(total["Requests/s"])
    started = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"Run at {started} against `{args.host}`: {args.users} users, spawn rate "
        f"{args.spawn_rate}/s, {args.duration}.",
        "",
        "| Endpoint | " + " | ".join(COLUMNS) + " |",
        "| --- | " + " | ".join("---:" for _ in COLUMNS) + " |",
        *[endpoint_row(endpoint_label(key), row) for key, row in stats.items() if key != total_key],
        endpoint_row("**All requests**", total),
        "",
        "| Target | Measured | Verdict |",
        "| --- | ---: | --- |",
        f"| p95 latency (client side) < {P95_TARGET_MS} ms | {client_p95:.0f} ms | "
        f"{verdict(client_p95 < P95_TARGET_MS)} |",
        f"| failed requests < {MAX_FAILURE_RATIO:.0%} | {failure_ratio:.2%} | "
        f"{verdict(failure_ratio < MAX_FAILURE_RATIO)} |",
        f"| throughput >= {MIN_THROUGHPUT_RPS} req/s | {throughput:.0f} req/s | "
        f"{verdict(throughput >= MIN_THROUGHPUT_RPS)} |",
    ]
    if args.prometheus:
        server_p95 = server_p95_ms(args.prometheus, args.window)
        measured = "not available" if server_p95 is None else f"{server_p95:.0f} ms"
        passed = server_p95 is not None and server_p95 < P95_TARGET_MS
        lines.append(
            f"| p95 latency (server side, Prometheus) < {P95_TARGET_MS} ms | {measured} | "
            f"{verdict(passed) if server_p95 is not None else '—'} |"
        )
    return "\n".join(lines)


def replace_section(document: str, section: str, body: str) -> str:
    """Swap the text between the section's start and end markers."""
    pattern = re.compile(
        rf"(<!-- results:{section}:start -->\n).*?(\n<!-- results:{section}:end -->)", re.S
    )
    if not pattern.search(document):
        raise SystemExit(f"markers for section {section!r} not found")
    return pattern.sub(lambda match: match[1] + body + match[2], document)


def parse_arguments() -> argparse.Namespace:
    """Command-line options."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stats", type=Path, required=True, help="<prefix>_stats.csv")
    parser.add_argument("--section", choices=("local", "live"), required=True)
    parser.add_argument("--host", required=True)
    parser.add_argument("--users", type=int, required=True)
    parser.add_argument("--spawn-rate", type=int, default=10)
    parser.add_argument("--duration", required=True, help="as given to locust -t, e.g. 2m")
    parser.add_argument("--prometheus", help="e.g. http://127.0.0.1:9090 (an SSH tunnel)")
    parser.add_argument("--window", type=int, default=120, help="seconds for the server p95")
    parser.add_argument("--report", type=Path, default=Path(__file__).parents[1] / "LOAD_TEST.md")
    return parser.parse_args()


def main() -> None:
    """Fill one results section of LOAD_TEST.md and print it."""
    args = parse_arguments()
    body = build_section(read_stats(args.stats), args)
    args.report.write_text(replace_section(args.report.read_text(), args.section, body))
    print(body)


if __name__ == "__main__":
    main()
