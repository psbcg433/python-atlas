"""Seeded synthetic access logs, with deliberately malformed lines, for demos and tests."""

import datetime as dt
import gzip
import io
import logging
import math
import random
import re
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TextIO

from log_analyzer.models import AccessRecord
from log_analyzer.parsing import format_access_line

logger = logging.getLogger(__name__)

ENDPOINTS = [  # (method, path template, weight, typical latency in ms)
    ("GET", "/api/products", 30, 40),
    ("GET", "/api/products/{id}", 25, 25),
    ("POST", "/api/cart/items", 12, 60),
    ("GET", "/api/orders/{id}", 10, 80),
    ("GET", "/health", 10, 2),
    ("POST", "/api/checkout", 6, 250),
    ("DELETE", "/api/cart/items/{id}", 4, 30),
    ("PUT", "/api/users/{id}/address", 3, 90),
]
STATUS_WEIGHTS = {
    200: 800,
    201: 50,
    204: 20,
    304: 30,
    400: 30,
    401: 10,
    404: 30,
    429: 10,
    500: 10,
    502: 5,
    503: 5,
}
MALFORMED_KINDS = ("truncated", "garbage", "unknown method", "status out of range")
GARBAGE_LINES = ("-", "<html>502 Bad Gateway</html>", "Connection reset by peer", "GET /")
START_TIME = dt.datetime(2026, 11, 6, 9, 0, 0)


def well_formed_line(rng: random.Random, timestamp: dt.datetime) -> str:
    """One valid access-log line drawn from the weighted tables."""
    weights = [endpoint[2] for endpoint in ENDPOINTS]
    method, template, _, typical_ms = rng.choices(ENDPOINTS, weights=weights)[0]
    path = template.replace("{id}", str(rng.randint(1, 5_000)))
    if template == "/api/products" and rng.random() < 0.3:
        path += f"?page={rng.randint(2, 9)}"
    status = rng.choices(list(STATUS_WEIGHTS), weights=list(STATUS_WEIGHTS.values()))[0]
    latency_ms = max(1, round(rng.lognormvariate(math.log(typical_ms), 0.6)))
    if status >= 500:
        latency_ms *= 5
    client_ip = f"10.0.{rng.randint(0, 3)}.{rng.randint(1, 254)}"
    stamp = timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")
    return format_access_line(AccessRecord(stamp, client_ip, method, path, status, latency_ms))


def break_line(rng: random.Random, line: str, kind: str) -> str:
    """Damage a valid line in one of the ``MALFORMED_KINDS`` ways."""
    match kind:
        case "truncated":
            return line[: rng.randint(10, len(line) - 6)]
        case "garbage":
            return rng.choice(GARBAGE_LINES)
        case "unknown method":
            return re.sub(r'"[A-Z]+ ', f'"{rng.choice(["FETCH", "BREW"])} ', line, count=1)
        case "status out of range":
            return re.sub(r'" \d{3} ', f'" {rng.choice(["000", "999"])} ', line, count=1)
        case _:
            raise ValueError(f"unknown kind: {kind!r}")


@contextmanager
def open_for_writing(path: Path) -> Iterator[TextIO]:
    """Open ``path`` for text writing; ``.gz`` paths get reproducible gzip output.

    The gzip header normally stores the file name and the current time, so compressing the
    same text twice gives different bytes. Writing through ``GzipFile(filename="", mtime=0)``
    keeps the output identical for identical input.
    """
    if path.suffix == ".gz":
        with (
            path.open("wb") as raw_file,
            gzip.GzipFile(filename="", mode="wb", fileobj=raw_file, mtime=0) as compressed,
            io.TextIOWrapper(compressed, encoding="utf-8", newline="\n") as text_file,
        ):
            yield text_file
    else:
        with path.open("w", encoding="utf-8", newline="\n") as text_file:
            yield text_file


def write_synthetic_log(
    path: Path, line_count: int, *, seed: int = 42, malformed_rate: float = 0.02
) -> Counter[str]:
    """Write ``line_count`` lines to ``path``; return how many of each malformed kind it wrote.

    The generator uses its own ``random.Random(seed)``, so the same arguments always give the
    same file. A ``.gz`` suffix writes gzip-compressed output.
    """
    if line_count < 0:
        raise ValueError(f"line_count must be >= 0, got {line_count}")
    if not 0 <= malformed_rate <= 1:
        raise ValueError(f"malformed_rate must be between 0 and 1, got {malformed_rate}")
    rng = random.Random(seed)
    timestamp = START_TIME
    injected: Counter[str] = Counter()
    with open_for_writing(path) as log_file:
        for _ in range(line_count):
            timestamp += dt.timedelta(milliseconds=rng.randint(100, 1_500))
            line = well_formed_line(rng, timestamp)
            if rng.random() < malformed_rate:
                kind = rng.choice(MALFORMED_KINDS)
                injected[kind] += 1
                line = break_line(rng, line, kind)
            log_file.write(line + "\n")
    logger.info("wrote %d lines to %s (seed %d)", line_count, path, seed)
    return injected
