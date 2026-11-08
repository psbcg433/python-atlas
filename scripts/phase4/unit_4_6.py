"""Unit 4.6 — Essential Third-Party Libraries (with Lab 4.6)."""

from nbformat import NotebookNode

from nb_builder import code, md, predict_cells

SHOP_API_SOURCE = r'''
import http.server
import json
import random
import threading
import time
import urllib.parse

SHOP_API_PORT = 18046  # fixed so outputs (URLs in messages) are stable; falls back to any free port


def demo_orders() -> list[dict[str, object]]:
    """40 seeded orders as an API would return them, with 3 invalid records planted."""
    generator = random.Random(46)
    cities = ["Pune", "Mumbai", "Bengaluru", "Hubli & Dharwad"]
    prices = {"TEA-500": "240.00", "MUG-02": "199.00", "JAR-750": "350.50", "KETTLE-9": "899.00"}
    orders: list[dict[str, object]] = []
    for order_id in range(1, 41):
        sku = generator.choice(sorted(prices))
        orders.append(
            {
                "order_id": order_id,
                "customer": f"customer-{order_id:03d}",
                "city": generator.choice(cities),
                "sku": sku,
                "quantity": generator.randint(1, 5),
                "unit_price": prices[sku],
                "placed_at": f"2026-11-{generator.randint(1, 7):02d}"
                f"T{generator.randint(9, 20):02d}:00:00+05:30",
            }
        )
    orders[6]["quantity"] = -2  # invalid: not positive
    del orders[17]["city"]  # invalid: missing field
    orders[29]["unit_price"] = "two hundred"  # invalid: not a number
    return orders


PRODUCTS_HTML = """<!doctype html>
<html><head><title>Chai Corner - Products</title></head>
<body>
  <h1>Products</h1>
  <ul id="catalogue">
    <li class="product" data-sku="TEA-500">
      <a href="/products/tea-500">Masala tea 500 g</a> <span class="price">₹240.00</span>
    </li>
    <li class="product" data-sku="MUG-02">
      <a href="/products/mug-02">Steel mug</a> <span class="price">₹199.00</span>
    </li>
    <li class="product sold-out" data-sku="JAR-750">
      <a href="/products/jar-750">Pickle jar 750 ml</a> <span class="price">₹350.50</span>
    </li>
  </ul>
  <p class="note">Prices include GST &amp; free delivery above ₹500.</p>
</body></html>
"""
ROBOTS_TXT = "User-agent: *\nDisallow: /admin/\nCrawl-delay: 1\n\nUser-agent: BadBot\nDisallow: /\n"


class ShopAPIHandler(http.server.BaseHTTPRequestHandler):
    """A tiny local HTTP API used by every HTTP demo (no external network)."""

    protocol_version = "HTTP/1.1"  # keep-alive, so clients can reuse connections
    hits: dict[str, int] = {}
    connections = 0

    def setup(self) -> None:
        type(self).connections += 1  # one per TCP connection, not per request
        super().setup()

    def log_message(self, format: str, *args: object) -> None:  # keep the notebook quiet
        pass

    def _send(self, status: int, body: object, content_type: str = "application/json") -> None:
        data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
        try:
            self.send_response(status)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except BrokenPipeError, ConnectionResetError:  # the client gave up (a timeout demo)
            self.close_connection = True

    def _count(self, key: str) -> int:
        self.hits[key] = self.hits.get(key, 0) + 1
        return self.hits[key]

    def do_GET(self) -> None:
        url = urllib.parse.urlsplit(self.path)
        query = dict(urllib.parse.parse_qsl(url.query))
        parts = url.path.strip("/").split("/")
        fail_first = int(query.get("fail", 0))
        if url.path == "/rates":
            base = query.get("base", "INR")
            self._send(
                200,
                {
                    "base": base,
                    "date": "2026-11-07",
                    "rates": {"USD": 0.012, "EUR": 0.011, "GBP": 0.0094},
                },
            )
        elif url.path == "/orders":
            if "key" in query and self._count(query["key"]) <= fail_first:
                self._send(503, {"error": "service busy, try again"})
            else:
                self._send(200, demo_orders())
        elif parts[0] == "flaky" and len(parts) == 2:
            attempt = self._count(parts[1])
            if attempt <= fail_first:
                self._send(503, {"error": "busy", "attempt": attempt})
            else:
                self._send(200, {"ok": True, "attempt": attempt})
        elif url.path == "/hits":
            self._send(
                200, {"key": query.get("key"), "hits": self.hits.get(query.get("key", ""), 0)}
            )
        elif url.path == "/connections":
            self._send(200, {"connections": type(self).connections})
        elif url.path == "/reset":
            self.hits.clear()
            self._send(200, {"reset": True})
        elif url.path == "/slow":
            time.sleep(float(query.get("seconds", "2")))
            self._send(200, {"slow": True})
        elif parts[0] == "status" and len(parts) == 2:
            self._send(int(parts[1]), {"status": int(parts[1])})
        elif url.path == "/headers":
            self._send(
                200,
                {
                    name.lower(): value
                    for name, value in self.headers.items()
                    if name.lower() in ("user-agent", "x-request-id", "authorization")
                },
            )
        elif url.path == "/products.html":
            self._send(200, PRODUCTS_HTML, "text/html")
        elif url.path == "/robots.txt":
            self._send(200, ROBOTS_TXT, "text/plain")
        else:
            self._send(404, {"error": f"no route {url.path}"})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length) or b"null")
        self._send(201 if self.path == "/orders" else 200, {"received": payload})


def start_shop_api() -> str:
    """Start the local API once (in a daemon thread) and return its base URL."""
    server = globals().get("_SHOP_API_SERVER")
    if server is None:
        try:
            server = http.server.ThreadingHTTPServer(("127.0.0.1", SHOP_API_PORT), ShopAPIHandler)
        except OSError:
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), ShopAPIHandler)
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        globals()["_SHOP_API_SERVER"] = server
    return f"http://127.0.0.1:{server.server_address[1]}"
'''

UNIT_SETUP_SOURCE = r'''
import asyncio
import contextlib
import importlib.metadata
import importlib.util
import inspect
import io
import os
import re
import shutil
import subprocess
import sys
import textwrap
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest import mock

REPO_ROOT = find_repo_root()
scratch_dir = REPO_ROOT / "notebooks" / "_scratch"  # git-ignored
UNIT46_DIR = scratch_dir / "unit46"
UNIT46_DIR.mkdir(parents=True, exist_ok=True)
FIXED_MOMENT = datetime(2026, 11, 7, 9, 30, tzinfo=UTC)
SHOP_API = start_shop_api()


def tidy(text: str) -> str:
    """Show absolute paths as <scratch>, <repo>, <site-packages> or ~."""
    site_packages = Path(inspect.getfile(importlib.metadata)).parent.parent
    for folder, label in ((UNIT46_DIR, "<scratch>"), (REPO_ROOT, "<repo>"), (Path.home(), "~")):
        text = text.replace(str(folder), label)
    return re.sub(r" at 0x[0-9a-f]+", " at 0x...", text.replace(str(site_packages), "<stdlib>"))


def raised_message(thunk: Callable[[], object]) -> str:
    """Call thunk and return "ErrorName: message" for the exception it raised, or "no error"."""
    try:
        thunk()
    except Exception as error:
        return tidy(f"{type(error).__name__}: {error}")
    return "no error"


def installed(module_name: str, package: str | None = None) -> bool:
    """True if module_name can be imported; otherwise print a skip message."""
    if importlib.util.find_spec(module_name) is not None:
        return True
    print(f"SKIP: {package or module_name} is not installed")
    return False


print(f"local shop API: {SHOP_API}")
for package in (
    "requests",
    "httpx",
    "tenacity",
    "pydantic",
    "pydantic-settings",
    "python-dotenv",
    "typer",
    "rich",
    "python-dateutil",
    "orjson",
    "numpy",
    "pandas",
    "polars",
    "beautifulsoup4",
    "lxml",
    "jinja2",
    "pillow",
    "boto3",
    "loguru",
    "attrs",
    "more-itertools",
    "cachetools",
):
    try:
        version = importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        version = "not installed (its cells print a skip message)"
    print(f"  {package:<18} {version}")
'''


def _overview_cells() -> list[NotebookNode]:
    """Unit opener and setup."""
    return [
        md(
            """
            ## Unit 4.6 — Essential Third-Party Libraries

            **Objectives**

            - Evaluate a library before depending on it.
            - Call HTTP APIs with `requests` and `httpx` (sync and async) and make them
              resilient with timeouts and `tenacity` retries.
            - Validate untrusted data and configuration with Pydantic, `pydantic-settings` and
              `python-dotenv`.
            - Build command-line apps with `typer` and `rich`.
            - Parse dates with `python-dateutil`; serialize fast with `orjson`.
            - Analyse tabular data with NumPy, pandas and Polars, and know when to use which.
            - Scrape HTML politely with BeautifulSoup and `lxml`.
            - Render HTML and e-mail with Jinja2; process images with Pillow; talk to S3 with
              `boto3`.
            - Know the developer utilities `loguru`, `attrs`, `more-itertools` and `cachetools`.

            **JS bridge: npm packages → PyPI packages**

            | npm | PyPI | Note |
            | --- | --- | --- |
            | `axios`, `fetch` | `requests` (sync), `httpx` (sync + async) | Python HTTP calls **block** unless you use `httpx.AsyncClient` |
            | `p-retry`, `axios-retry` | `tenacity` | Decorator-based retry policies |
            | `zod` | `pydantic` | Models are classes with type hints |
            | `dotenv` | `python-dotenv`, `pydantic-settings` | Settings are typed and validated |
            | `commander`, `yargs`, `chalk`, `ora` | `typer`, `click`, `rich` | |
            | `date-fns`, `dayjs` | `python-dateutil` (+ stdlib `datetime`) | |
            | `lodash` (arrays) | `numpy`, `more-itertools` | |
            | `danfo.js`, `arquero` | `pandas`, `polars` | Python's data ecosystem is far larger |
            | `cheerio`, `jsdom` | `beautifulsoup4`, `lxml` | |
            | `nunjucks`, `handlebars` | `jinja2` | Nunjucks was modelled on Jinja2 |
            | `sharp` | `pillow` | |
            | `@aws-sdk/client-s3` | `boto3` | |
            | `pino`, `winston` | `loguru` (or stdlib `logging`) | |
            | `lru-cache` | `cachetools`, `functools.lru_cache` | |

            **No external network.** Every HTTP demo talks to a tiny API that the setup cell
            starts on `127.0.0.1` in a background thread (`SHOP_API`): exchange rates, orders
            (with three invalid records planted), a "flaky" endpoint that fails the first N
            requests, a slow endpoint, an HTML page and a `robots.txt`. S3 calls are stubbed.
            Outputs are deterministic except timings, which the markdown points out.

            **The local shop API.** The next cell defines the server: a
            `BaseHTTPRequestHandler` subclass with a few routes, served by
            `ThreadingHTTPServer` in a daemon thread on a fixed port (18046, falling back to
            any free port). The setup cell after it starts the server and prints versions.
            """
        ),
        code(SHOP_API_SOURCE),
        md(
            "Unit setup: imports, scratch folder, the API's base URL (`SHOP_API`) and package versions."
        ),
        code(UNIT_SETUP_SOURCE),
    ]


def _choosing_cells() -> list[NotebookNode]:
    """4.6.1 Choosing a library."""
    return [
        md(
            """
            ### 4.6.1 Choosing a library

            Every dependency is code you ship, update and answer for. Check before you add:

            | Question | Where to look | Warning signs |
            | --- | --- | --- |
            | Is it maintained? | release history on PyPI, recent commits, open/closed issues and PRs, number of maintainers | no release in 2+ years, issues ignored, one maintainer who left |
            | Is it used? | download stats (pypistats.org, libraries.io), dependents on GitHub | a fork or a typo-squatting name (Unit 4.1) |
            | Is it typed? | a `py.typed` marker (PEP 561) or stubs on typeshed | `Any` everywhere in your code |
            | Licence? | `License-Expression` / classifiers in the metadata | GPL/AGPL in a closed product, no licence at all |
            | Known vulnerabilities? | `pip-audit` (Unit 4.1), GitHub/OSV advisories | open advisories without fixes |
            | How heavy? | its dependency tree, wheel size, compiled parts, Python-version support | pulls in dozens of packages for one function |
            | Can you read it? | the docs **and the source** | magic you cannot debug |

            Much of this is in the installed package's metadata. A small report for packages
            this unit uses (download stats and advisories need the network, so they are not
            shown here):
            """
        ),
        code(
            r'''
            from importlib.metadata import distribution, requires

            from packaging.requirements import Requirement


            def dependency_tree(package: str, seen: set[str] | None = None) -> set[str]:
                """All runtime dependencies of an installed package (extras and markers ignored)."""
                seen = set() if seen is None else seen
                for requirement_text in requires(package) or []:
                    requirement = Requirement(requirement_text)
                    if requirement.marker and not requirement.marker.evaluate({"extra": ""}):
                        continue
                    name = requirement.name.lower()
                    if name not in seen:
                        seen.add(name)
                        with contextlib.suppress(importlib.metadata.PackageNotFoundError):
                            dependency_tree(name, seen)
                return seen


            print(
                f"{'package':<12}{'version':<10}{'licence':<26}"
                f"{'typed':<7}{'deps':>5}{'all':>5}  requires-python"
            )
            for package in ("requests", "httpx", "tenacity", "pydantic", "polars", "pandas", "boto3"):
                metadata = distribution(package).metadata
                classifiers = [
                    value.rsplit(" :: ", 1)[-1]
                    for value in metadata.get_all("Classifier") or []
                    if value.startswith("License ::")
                ]
                licence = (
                    metadata.get("License-Expression")
                    or (classifiers or [(metadata.get("License") or "?").splitlines()[0]])[0]
                )
                typed = any(str(file).endswith("py.typed") for file in distribution(package).files or [])
                direct = [text for text in requires(package) or [] if "extra ==" not in text]
                print(
                    f"{package:<12}{metadata['Version']:<10}{licence[:24]:<26}{str(typed):<7}{len(direct):>5}"
                    f"{len(dependency_tree(package)):>5}  {metadata.get('Requires-Python')}"
                )
            '''
        ),
        md(
            """
            **Reading the source** is the fastest way to answer "what does this actually do?".
            `inspect.getsource` works on any pure-Python library; here it shows that
            `requests.get` is a two-line wrapper that builds a throwaway `Session` for every
            call (one reason to use a `Session` yourself, 4.6.2):
            """
        ),
        code(
            r"""
            import requests

            print(tidy(inspect.getsourcefile(requests.get)))
            get_lines = inspect.getsource(requests.get).splitlines()
            print(f"{get_lines[0]}\n    ...docstring...\n{get_lines[-1]}")
            print("\n".join(inspect.getsource(requests.api.request).splitlines()[-3:]))
            """
        ),
    ]


def _http_cells() -> list[NotebookNode]:
    """4.6.2 HTTP and resilience."""
    return [
        md(
            """
            ### 4.6.2 HTTP and resilience

            **`requests`** is the classic synchronous HTTP library. Three habits matter more
            than any API detail:

            1. **Always pass `timeout=`.** The default is *no timeout*: a stalled server hangs
               your program forever. Use `(connect, read)` seconds.
            2. **Call `raise_for_status()`.** A 404 or 500 is a normal response, not an
               exception, until you ask.
            3. **Use a `Session`** for repeated calls: it reuses TCP connections (much faster),
               and keeps headers, cookies and auth in one place.
            """
        ),
        code(
            r"""
            response = requests.get(f"{SHOP_API}/rates", params={"base": "INR"}, timeout=(3.05, 10))
            print(f"{response.status_code=}, {response.headers['Content-Type']=}")
            print(f"{response.url=}")
            print(f"{response.json()=}")
            missing = requests.get(f"{SHOP_API}/status/404", timeout=5)
            print(f"{missing.ok=}, {missing.status_code=}  (no exception yet)")
            print(raised_message(missing.raise_for_status))
            print(raised_message(lambda: requests.get(f"{SHOP_API}/slow", params={"seconds": 2}, timeout=0.2)))
            """
        ),
        md(
            """
            A `Session` with default headers (user agent, auth token) for every request, and a
            context manager that closes its connection pool. Connection reuse is the main speed
            win: across the internet every new connection costs a TCP and TLS handshake (tens to
            hundreds of milliseconds). The local server counts TCP connections, which shows the
            reuse directly: twenty requests through a session use one connection, twenty
            `requests.get` calls use twenty.
            """
        ),
        code(
            r'''
            def connections_opened(make_calls: Callable[[], None]) -> int:
                """TCP connections the server accepted while make_calls ran."""
                before = requests.get(f"{SHOP_API}/connections", timeout=5).json()["connections"]
                make_calls()
                after = requests.get(f"{SHOP_API}/connections", timeout=5).json()["connections"]
                return after - before - 1  # the second check opened one connection itself


            def twenty_with_session() -> None:
                with requests.Session() as session:
                    session.headers.update(
                        {"User-Agent": "chai-corner-reports/1.0", "Authorization": "Bearer demo-token"}
                    )
                    print(f"{session.get(f'{SHOP_API}/headers', timeout=5).json()=}")
                    for _ in range(19):
                        session.get(f"{SHOP_API}/rates", timeout=5).raise_for_status()


            reused = connections_opened(twenty_with_session)
            fresh = connections_opened(
                lambda: [requests.get(f"{SHOP_API}/rates", timeout=5).raise_for_status() for _ in range(20)]
            )
            print(f"20 requests: {reused} connection(s) with a Session, {fresh} without")
            created = requests.post(f"{SHOP_API}/orders", json={"sku": "TEA-500", "quantity": 2}, timeout=5)
            print(f"POST: {created.status_code=}, {created.json()=}")
            '''
        ),
        md(
            """
            **`httpx`** has a `requests`-like API plus: **async** support, HTTP/2, strict
            timeouts by default (5 s), and pluggable transports for testing. The recommended
            pattern is **one shared `Client`** for the whole application (connection pool,
            base URL, default headers and timeouts), created once and closed at shutdown, not
            a new client per request.
            """
        ),
        code(
            r"""
            import httpx

            with httpx.Client(
                base_url=SHOP_API,
                timeout=httpx.Timeout(5.0, connect=2.0),
                headers={"User-Agent": "chai-corner/1.0"},
            ) as client:
                rates = client.get("/rates", params={"base": "INR"})
                rates.raise_for_status()
                print(f"{rates.status_code=}, {rates.json()['rates']=}")
                print(f"{rates.http_version=}, {rates.elapsed.total_seconds() < 1=}")
                print(raised_message(lambda: client.get("/status/503").raise_for_status()).splitlines()[0])
                print(raised_message(lambda: client.get("/slow", params={"seconds": 2}, timeout=0.2)))
            print(f"{httpx.Timeout(5.0)=}  (requests has no default timeout at all)")
            """
        ),
        md(
            """
            **Async httpx.** An `AsyncClient` lets one thread wait for many requests at once
            (Phase 5 explains the event loop). Five calls to the slow endpoint, each taking
            0.3 s, finish in about 0.3 s together instead of 1.5 s one after another. The kernel
            already runs an event loop, so the cell can `await` at top level.
            """
        ),
        code(
            r"""
            async def fetch_all(paths: list[str]) -> list[dict[str, object]]:
                async with httpx.AsyncClient(base_url=SHOP_API, timeout=5) as client:
                    responses = await asyncio.gather(*(client.get(path) for path in paths))
                    return [response.raise_for_status().json() for response in responses]


            started = time.perf_counter()
            results = await fetch_all(["/slow?seconds=0.3"] * 5)
            elapsed = time.perf_counter() - started
            print(f"{len(results)} responses in {elapsed:.1f} s (concurrent; sequential would be ~1.5 s)")
            """
        ),
        md(
            """
            **Testing without a server: `httpx.MockTransport`.** A transport is the layer that
            actually sends bytes; a mock transport is a function that receives the `Request`
            and returns a `Response`. Code under test keeps using a normal `Client`.
            """
        ),
        code(
            r"""
            def fake_rates_service(request: httpx.Request) -> httpx.Response:
                if request.url.path != "/rates":
                    return httpx.Response(404, json={"error": "not found"})
                return httpx.Response(
                    200, json={"rates": {"USD": 0.012}, "asked_for": request.url.params["base"]}
                )


            with httpx.Client(
                transport=httpx.MockTransport(fake_rates_service), base_url="https://rates.example.com"
            ) as fake_client:
                print(f"{fake_client.get('/rates', params={'base': 'INR'}).json()=}")
                print(f"{fake_client.get('/nope').status_code=}")
            """
        ),
        md(
            """
            **`tenacity`: retry policies.** Networks fail transiently (timeouts, 502/503
            responses, dropped connections). Retrying blindly makes outages worse, so a policy
            states **what** to retry (`retry=`), **how long to wait** between attempts
            (`wait=`, usually exponential backoff with jitter, so thousands of clients do not
            retry in lockstep), and **when to stop** (`stop=`). `reraise=True` raises the last
            real error instead of tenacity's `RetryError`. Waits are tiny here so the demo is
            fast; real values are seconds.

            | Building block | Examples |
            | --- | --- |
            | stop | `stop_after_attempt(5)`, `stop_after_delay(30)`, combine with `\\|` |
            | wait | `wait_fixed(1)`, `wait_exponential(multiplier=0.5, max=10)`, `wait_random_exponential(...)` (jitter) |
            | retry | `retry_if_exception_type(...)`, `retry_if_result(predicate)`, `retry_if_exception(predicate)` |
            | hooks | `before_sleep=before_sleep_log(logger, logging.WARNING)`, `after=` |
            """
        ),
        code(
            r'''
            from tenacity import (
                RetryError,
                retry,
                retry_if_exception,
                stop_after_attempt,
                wait_exponential,
            )


            def is_transient(error: BaseException) -> bool:
                """Retry timeouts, connection errors and 5xx responses; never 4xx."""
                if isinstance(error, httpx.HTTPStatusError):
                    return error.response.status_code >= 500
                return isinstance(error, httpx.TransportError)


            attempts_log: list[str] = []


            @retry(
                retry=retry_if_exception(is_transient),
                stop=stop_after_attempt(4),
                wait=wait_exponential(multiplier=0.01, max=0.05),
                before_sleep=lambda state: attempts_log.append(
                    f"attempt {state.attempt_number} failed: {state.outcome.exception().response.status_code}"
                ),
                reraise=True,
            )
            def get_json(client: httpx.Client, path: str) -> dict[str, object]:
                return client.get(path).raise_for_status().json()


            with httpx.Client(base_url=SHOP_API, timeout=5) as client:
                client.get("/reset")
                print(f"{get_json(client, '/flaky/demo-a?fail=2')=}")
                print(f"{attempts_log=}")
                print(raised_message(lambda: get_json(client, "/flaky/demo-b?fail=10")).splitlines()[0])
                print(f"{client.get('/hits', params={'key': 'demo-b'}).json()=}  (gave up after 4)")
                print(
                    raised_message(lambda: get_json(client, "/status/404")).splitlines()[0]
                    + "  (4xx: not retried)"
                )
                print(f"{get_json.statistics['attempt_number']=}  (statistics of the last call)")
            '''
        ),
        md(
            """
            The same policy as an object (`Retrying`), retrying on a **result** instead of an
            exception (poll until a job is ready), with a time-based stop:
            """
        ),
        code(
            r"""
            from tenacity import Retrying, retry_if_result, stop_after_delay, wait_fixed

            job_states = iter(["queued", "running", "running", "done"])
            poller = Retrying(
                retry=retry_if_result(lambda state: state != "done"),
                wait=wait_fixed(0.01),
                stop=stop_after_delay(2),
            )
            print(f"{poller(lambda: next(job_states))=}, attempts: {poller.statistics['attempt_number']}")
            print(
                raised_message(
                    lambda: Retrying(stop=stop_after_attempt(2), retry=retry_if_result(lambda value: True))(
                        lambda: "never done"
                    )
                )
            )
            print(f"{RetryError.__mro__[1].__name__=}")
            """
        ),
    ]


def _validation_cells() -> list[NotebookNode]:
    """4.6.3 Validation and configuration."""
    return [
        md(
            """
            ### 4.6.3 Validation and configuration

            **Pydantic v2** turns untrusted data (an API response, a config file, user input)
            into typed objects, or tells you exactly what is wrong. Unit 4.2.13 showed it reads
            type hints at run time; here it is used outside any web framework. Models declare
            fields with hints and `Field` constraints; validation **coerces** compatible input
            (`"3"` → `3` in the default lax mode) and collects every error.
            """
        ),
        code(
            r"""
            from typing import Annotated

            from pydantic import (
                AwareDatetime,
                BaseModel,
                ConfigDict,
                Field,
                PositiveInt,
                TypeAdapter,
                ValidationError,
                field_validator,
            )


            class ApiOrder(BaseModel):
                model_config = ConfigDict(frozen=True, extra="ignore")

                order_id: PositiveInt
                customer: str
                city: str
                sku: Annotated[str, Field(pattern=r"^[A-Z]{2,6}-\d{1,4}$")]
                quantity: PositiveInt
                unit_price: Annotated[Decimal, Field(gt=0, max_digits=8, decimal_places=2)]
                placed_at: AwareDatetime

                @field_validator("city")
                @classmethod
                def city_is_title_case(cls, value: str) -> str:
                    return value.strip()


            raw_orders = httpx.get(f"{SHOP_API}/orders", timeout=5).json()
            first = ApiOrder.model_validate(raw_orders[0])
            print(repr(first))
            print(f"{first.unit_price * first.quantity=}, {first.placed_at.utcoffset()=}")
            """
        ),
        md(
            """
            **Validating a whole API response.** `TypeAdapter(list[ApiOrder])` validates a list
            in one go; a `ValidationError` lists every problem with its location
            (`[index, field]`), message and type. Validating record by record instead keeps the
            good ones and reports the bad ones, the usual choice for imports.
            """
        ),
        code(
            r"""
            print(
                raised_message(lambda: TypeAdapter(list[ApiOrder]).validate_python(raw_orders)).splitlines()[0]
            )
            valid_orders, problems = [], []
            for index, record in enumerate(raw_orders):
                try:
                    valid_orders.append(ApiOrder.model_validate(record))
                except ValidationError as error:
                    problems.extend(
                        f"record {index}: {'.'.join(map(str, issue['loc']))}: {issue['msg']}"
                        for issue in error.errors()
                    )
            print(f"{len(valid_orders)} valid, {len(problems)} problems:")
            print(textwrap.indent("\n".join(problems), "  "))
            print(f"{first.model_dump(mode='json')}")
            """
        ),
        md(
            """
            **Config files.** The same models validate configuration loaded from TOML, YAML or
            JSON, so a typo or a wrong type fails at startup with a clear message instead of
            deep inside the program. `strict=True` turns off coercion where it would hide
            mistakes.
            """
        ),
        code(
            r"""
            import tomllib


            class WarehouseConfig(BaseModel):
                code: Annotated[str, Field(min_length=4, max_length=4)]
                capacity: PositiveInt


            class ShopConfig(BaseModel):
                model_config = ConfigDict(extra="forbid")

                store_name: str
                gst_percent: Annotated[int, Field(ge=0, le=28)]
                currency: str = "INR"
                warehouses: list[WarehouseConfig]
                debug: Annotated[bool, Field(strict=True)] = False


            good_toml = (
                'store_name = "Pune Central"\ngst_percent = 18\n'
                '[[warehouses]]\ncode = "PNQ1"\ncapacity = 5000\n'
            )
            print(repr(ShopConfig.model_validate(tomllib.loads(good_toml))))
            bad_toml = (
                'store_name = "Pune"\ngst_percent = 45\ndebug = "yes"\nwarehose = []\n'
                '[[warehouses]]\ncode = "PNQ"\ncapacity = 0\n'
            )
            try:
                ShopConfig.model_validate(tomllib.loads(bad_toml))
            except ValidationError as error:
                for issue in error.errors():
                    print(f"  {'.'.join(map(str, issue['loc'])):<22} {issue['msg']}")
            """
        ),
        md(
            """
            **`pydantic-settings`** reads settings from **environment variables** (and `.env`
            files, secrets folders, CLI arguments), validates them with the same machinery, and
            gives you one typed object, the twelve-factor way of configuring an app. Field
            `api_base_url` is read from `SHOP_API_BASE_URL` because of `env_prefix`; nested
            values use a delimiter; `SecretStr` hides secrets in reprs and logs.
            """
        ),
        code(
            r"""
            from pydantic import SecretStr
            from pydantic_settings import BaseSettings, SettingsConfigDict


            class AppSettings(BaseSettings):
                model_config = SettingsConfigDict(env_prefix="SHOP_", env_file=None)

                api_base_url: str = "http://127.0.0.1:8000"
                request_timeout_seconds: float = 5.0
                max_retries: Annotated[int, Field(ge=0, le=10)] = 3
                api_token: SecretStr
                debug: bool = False


            environment = {
                "SHOP_API_BASE_URL": SHOP_API,
                "SHOP_MAX_RETRIES": "5",
                "SHOP_API_TOKEN": "tok_demo_123",
                "SHOP_DEBUG": "true",
            }
            with mock.patch.dict(os.environ, environment):
                settings = AppSettings()
            print(repr(settings))
            print(f"{settings.max_retries=} (int from a string), {settings.api_token.get_secret_value()=}")
            with mock.patch.dict(os.environ, {"SHOP_MAX_RETRIES": "50"}, clear=False):
                error_lines = raised_message(lambda: AppSettings()).splitlines()
            print("\n".join(line for line in error_lines if "further information" not in line))
            """
        ),
        md(
            """
            **`.env` files and `python-dotenv`.** A `.env` file holds local development
            settings (never commit real secrets; the course's `.gitignore` excludes `.env`).
            `dotenv_values` parses one into a dict without touching the environment;
            `load_dotenv` copies the values into `os.environ` and by default does **not**
            override variables that are already set, so real environment variables win.
            `pydantic-settings` reads the same files with `env_file=`.
            """
        ),
        code(
            r"""
            from dotenv import dotenv_values, load_dotenv

            env_file = UNIT46_DIR / "demo.env"
            env_file.write_text(
                "# local development only\nSHOP_API_TOKEN=tok_from_dotenv\nSHOP_MAX_RETRIES=2\n"
                'SHOP_API_BASE_URL="http://localhost:9000"  # quoted\n',
                encoding="utf-8",
            )
            print(f"{dotenv_values(env_file)=}")
            with mock.patch.dict(os.environ, {"SHOP_MAX_RETRIES": "7"}):
                load_dotenv(env_file)  # does not override SHOP_MAX_RETRIES=7
                print(f"{os.environ['SHOP_MAX_RETRIES']=}, {os.environ['SHOP_API_TOKEN']=}")
                print(f"{AppSettings(_env_file=env_file).max_retries=}  (environment beats the file)")
            print(f"after the block: {'SHOP_API_TOKEN' in os.environ=}")
            """
        ),
        *predict_cells(
            """
            from pydantic import BaseModel

            class Line(BaseModel):
                quantity: int

            print(Line(quantity="3").quantity + 1, Line.model_validate({"quantity": 3.0}).quantity)
            """,
            """
            `4 3`. In the default **lax** mode Pydantic coerces `"3"` to `3` and the float `3.0`
            (which has no fractional part) to the int `3`; `3.5` or `"three"` would fail. Use
            `ConfigDict(strict=True)` or `Field(strict=True)` to reject anything that is not
            already an `int`.
            """,
            """
            class Line(BaseModel):
                quantity: int


            print(Line(quantity="3").quantity + 1, Line.model_validate({"quantity": 3.0}).quantity)
            print(raised_message(lambda: Line(quantity=3.5)).splitlines()[2].strip())
            """,
        ),
    ]


def _cli_cells() -> list[NotebookNode]:
    """4.6.4 Command-line apps."""
    return [
        md(
            """
            ### 4.6.4 Command-line apps

            **`typer`** builds a CLI from **type hints**, the same idea as FastAPI: parameters
            without defaults become arguments, parameters with defaults become `--options`,
            `bool` options become flags, and `--help` is generated from the docstrings.
            `typer.testing.CliRunner` invokes the app in-process and captures its output,
            which is how CLIs are tested. (Compare the hand-written `argparse` version in Unit
            4.4.8.)
            """
        ),
        code(
            r'''
            import typer
            from typer.testing import CliRunner

            shopctl = typer.Typer(help="Chai Corner admin tool.", add_completion=False, rich_markup_mode=None)


            @shopctl.command()
            def restock(sku: str, quantity: int = 1, dry_run: bool = False) -> None:
                """Add stock for SKU."""
                verb = "would add" if dry_run else "added"
                typer.echo(f"{verb} {quantity} x {sku}")


            @shopctl.command()
            def rates(base: str = typer.Option("INR", help="Currency to convert from.")) -> None:
                """Show exchange rates from the shop API."""
                for currency, rate in (
                    httpx.get(f"{SHOP_API}/rates", params={"base": base}, timeout=5).json()["rates"].items()
                ):
                    typer.echo(f"1 {base} = {rate} {currency}")


            runner = CliRunner()
            plain = {"NO_COLOR": "1", "TERM": "dumb", "COLUMNS": "80"}
            for arguments in (
                ["restock", "TEA-500", "--quantity", "24", "--dry-run"],
                ["rates"],
                ["restock", "TEA-500", "--quantity", "many"],
            ):
                result = runner.invoke(shopctl, arguments, env=plain, prog_name="shopctl")
                print(f"$ shopctl {' '.join(arguments)}   (exit {result.exit_code})")
                print(textwrap.indent(result.output.rstrip(), "  "))
            '''
        ),
        md("The generated help for one command (rich draws the boxes):"),
        code(
            r"""
            print(runner.invoke(shopctl, ["restock", "--help"], env=plain, prog_name="shopctl").output)
            """
        ),
        md(
            """
            **`click`** is the library typer is built on: commands and options are declared with
            decorators instead of type hints, and it is still common in existing code (Flask's
            CLI, many tools). Recent typer releases ship their own copy of click inside
            `typer` (`typer._click`), so a standalone `click` package is only installed if
            something else needs it. `click` is not an Appendix A package; the cell checks
            first.

            ```python
            import click

            @click.command()
            @click.argument("sku")
            @click.option("--quantity", default=1, type=int, help="Units to add.")
            @click.option("--dry-run", is_flag=True)
            def restock(sku: str, quantity: int, dry_run: bool) -> None:
                click.echo(f"{'would add' if dry_run else 'added'} {quantity} x {sku}")
            ```
            """
        ),
        code(
            r"""
            print(f"typer's bundled click: {importlib.util.find_spec('typer._click') is not None}")
            if installed("click", "click (not an Appendix A package; typer bundles its own copy)"):
                import click

                @click.command()
                @click.argument("sku")
                @click.option("--quantity", default=1, type=int)
                def click_restock(sku: str, quantity: int) -> None:
                    click.echo(f"added {quantity} x {sku}")

                print(click.testing.CliRunner().invoke(click_restock, ["TEA-500", "--quantity", "3"]).output)
            """
        ),
        md(
            """
            **`rich`** renders tables, progress bars, syntax-highlighted tracebacks and
            coloured logs in the terminal. A `Console(file=..., color_system=None)` writes plain
            text to any file, which keeps this notebook's output deterministic (in a real
            terminal you just use `rich.print` or `Console()`). **Tables:**
            """
        ),
        code(
            r'''
            from rich.console import Console
            from rich.table import Table


            def plain_console(width: int = 80) -> Console:
                """A rich Console that writes plain text (no colours) to a buffer."""
                return Console(
                    file=io.StringIO(),
                    width=width,
                    color_system=None,
                    force_terminal=False,
                    force_jupyter=False,
                )


            table = Table(title="Low stock", show_lines=False)
            table.add_column("SKU", style="bold")
            table.add_column("Product")
            table.add_column("Qty", justify="right")
            table.add_column("Value (INR)", justify="right")
            for sku, product, quantity, price in [
                ("MUG-02", "Steel mug", 3, Decimal("199")),
                ("JAR-750", "Pickle jar 750 ml", 1, Decimal("350.50")),
            ]:
                table.add_row(sku, product, str(quantity), f"{quantity * price:,.2f}")
            console = plain_console()
            console.print(table)
            print(console.file.getvalue())
            '''
        ),
        md(
            """
            **Progress bars** (`rich.progress.track` or `Progress` for several tasks) show
            work as it happens; in a non-terminal they print only the final state. **Logging
            handler:** `RichHandler` formats stdlib `logging` records with levels, times and
            paths (the options below switch time and path off for stable output).
            """
        ),
        code(
            r"""
            import logging

            from rich.logging import RichHandler
            from rich.progress import track

            console = plain_console()
            processed = sum(
                1 for _ in track(range(250), description="Importing orders", console=console, transient=False)
            )
            print(f"{processed=}")
            print(console.file.getvalue().strip().splitlines()[-1])

            console = plain_console()
            rich_logger = logging.getLogger("unit46.rich")
            rich_logger.handlers[:] = [RichHandler(console=console, show_time=False, show_path=False)]
            rich_logger.propagate = False
            rich_logger.warning("stock for %s is low (%d left)", "MUG-02", 3)
            rich_logger.error("payment gateway timed out")
            print(console.file.getvalue())
            rich_logger.handlers.clear()
            """
        ),
        md(
            """
            **Pretty tracebacks.** `rich.traceback.install()` replaces the default exception
            hook for a whole program; `console.print_exception()` renders the current exception
            with the surrounding source lines (and local variables with `show_locals=True`). It
            runs here in a small script in a child process, so the frames and paths are clean:
            """
        ),
        code(
            r'''
            trace_script = UNIT46_DIR / "rich_traceback_demo.py"
            trace_script.write_text(
                textwrap.dedent("""
                from decimal import Decimal

                from rich.console import Console


                def apply_discount(total, percent):
                    return total * (100 - percent) / 100 / 0  # bug


                console = Console(color_system=None, width=150)
                try:
                    apply_discount(Decimal("679.00"), 10)
                except ArithmeticError:
                    console.print_exception(show_locals=True, width=150)
            """),
                encoding="utf-8",
            )
            completed = subprocess.run(
                [sys.executable, str(trace_script)],
                capture_output=True,
                text=True,
                timeout=60,
                env={**os.environ, "NO_COLOR": "1"},
            )
            long_name, short_name = str(trace_script), "<scratch>/rich_traceback_demo.py"
            pad = " " * (len(long_name) - len(short_name))  # keep rich's box borders aligned
            print(
                re.sub(
                    re.escape(long_name) + r"(:\d+ in \S+)",
                    lambda found: short_name + found.group(1) + pad,
                    completed.stdout,
                ).rstrip()
            )
            '''
        ),
    ]


def _date_json_cells() -> list[NotebookNode]:
    """4.6.5 Dates and serialization."""
    return [
        md(
            """
            ### 4.6.5 Dates and serialization

            **`python-dateutil`** fills two gaps in `datetime`. `parser.parse` reads almost any
            human-written date without a format string (`dayfirst=True` for Indian/European
            `07/11/2026`; `fuzzy=True` skips surrounding words). Beware: `dayfirst=True` also
            swaps the parts of an ISO date such as `2026-11-07`, so apply it only to input
            known to be day-first. Use it at the edges for messy
            input; for data you control, `datetime.fromisoformat` is stricter and faster.
            """
        ),
        code(
            r"""
            from dateutil import parser as date_parser
            from dateutil import tz

            for text in (
                "7 November 2026 3pm",
                "Sat, 07 Nov 2026 09:30:00 GMT",
                "Nov 7 2026 15:00 IST",
                "2026-11-07T15:00:00+05:30",
            ):
                parsed = date_parser.parse(text, tzinfos={"IST": tz.gettz("Asia/Kolkata")})
                print(f"  {text!r:<34} -> {parsed.isoformat()}")
            print(f"{date_parser.parse('07/11/2026')=}  (default is month first!)")
            print(f"{date_parser.parse('07/11/2026', dayfirst=True)=}")
            print(
                f"{date_parser.parse('2026-11-07', dayfirst=True)=}"
                "  (dayfirst even flips ISO dates: use fromisoformat)"
            )
            print(f"{date_parser.parse('Order placed on 7th Nov 2026 at 9:30', fuzzy=True)=}")
            print(raised_message(lambda: date_parser.parse("next Diwali")))
            """
        ),
        md(
            """
            **`relativedelta`** does calendar arithmetic that `timedelta` cannot: "one month
            later" (clamped to the end of shorter months), "last day of the month", ages and
            subscription renewals. `rrule` generates recurring dates (every second Tuesday,
            the last working day of each month).
            """
        ),
        code(
            r"""
            from dateutil.relativedelta import FR, relativedelta
            from dateutil.rrule import MONTHLY, rrule

            print(f"{date(2026, 1, 31) + relativedelta(months=1)=}  (clamped to Feb 28)")
            print(f"{date(2026, 11, 7) + relativedelta(months=+1, day=31)=}  (last day of next month)")
            print(f"{relativedelta(date(2026, 11, 7), date(1990, 2, 14))=}")
            print(f"{relativedelta(date(2026, 11, 7), date(1990, 2, 14)).years=} years old")
            print(f"{date(2026, 11, 7) + relativedelta(weekday=FR(+1))=}  (next Friday)")
            payroll = rrule(
                MONTHLY, count=3, bysetpos=-1, byweekday=(0, 1, 2, 3, 4), dtstart=datetime(2026, 11, 1)
            )
            print(f"last working day of the next 3 months: {[run.date().isoformat() for run in payroll]}")
            """
        ),
        *predict_cells(
            """
            from datetime import date, timedelta
            from dateutil.relativedelta import relativedelta

            start = date(2026, 1, 31)
            print(start + relativedelta(months=1), start + timedelta(days=30))
            """,
            """
            `2026-02-28 2026-03-02`. `relativedelta(months=1)` moves to the same day of the next
            month and clamps to its last day (February 2026 has 28 days). `timedelta` only
            knows fixed durations: 30 days after 31 January is 2 March.
            """,
            """
            start = date(2026, 1, 31)
            print(start + relativedelta(months=1), start + timedelta(days=30))
            """,
        ),
        md(
            """
            **`orjson`** is a JSON library written in Rust, often 5–10× faster than `json`. It
            returns **bytes**, serializes `datetime`, `date`, `UUID`, dataclasses, enums and
            NumPy arrays natively, and takes options as bit flags. It does not serialize
            `Decimal` by default (pass `default=`). Use it when JSON is a hot path (APIs, log
            pipelines); FastAPI can use it too.
            """
        ),
        code(
            r"""
            import dataclasses
            import uuid

            import orjson


            @dataclasses.dataclass
            class Shipment:
                shipment_id: uuid.UUID
                dispatched_at: datetime
                weights_kg: list[float]
                declared_value: Decimal


            shipment = Shipment(uuid.UUID(int=46), FIXED_MOMENT, [1.5, 0.25], Decimal("679.00"))
            print(raised_message(lambda: orjson.dumps(shipment)))
            encoded = orjson.dumps(shipment, default=str)
            print(f"{encoded=}")
            print(
                orjson.dumps(
                    {"b": 1, "a": {"z": 2, 10: "non-str key"}},
                    option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS | orjson.OPT_NON_STR_KEYS,
                ).decode()
            )
            print(f"{orjson.loads(encoded)['dispatched_at']=}")
            """
        ),
        md(
            """
            A rough speed comparison on 2,000 orders (timings vary by machine; the ratio is the
            point). **`msgspec`**, another fast library, validates while decoding into typed
            `Struct` classes, like a much faster, stricter Pydantic for serialization. It is
            not an Appendix A package, so its cell checks first.
            """
        ),
        code(
            r"""
            import json
            import timeit

            big_payload = [dict(order, placed_at=FIXED_MOMENT.isoformat()) for order in raw_orders * 50]
            stdlib_seconds = min(timeit.repeat(lambda: json.loads(json.dumps(big_payload)), number=5, repeat=3))
            orjson_seconds = min(
                timeit.repeat(lambda: orjson.loads(orjson.dumps(big_payload)), number=5, repeat=3)
            )
            print(
                f"{len(big_payload)} records round trip: json {stdlib_seconds * 200:.1f} ms, "
                f"orjson {orjson_seconds * 200:.1f} ms, speed-up ~{stdlib_seconds / orjson_seconds:.0f}x"
            )
            if installed("msgspec", "msgspec (not an Appendix A package)"):
                import msgspec

                class Rate(msgspec.Struct):
                    base: str
                    rates: dict[str, float]

                print(msgspec.json.decode(b'{"base": "INR", "rates": {"USD": 0.012}}', type=Rate))
            """
        ),
    ]


def _data_cells() -> list[NotebookNode]:
    """4.6.6 Data analysis."""
    return [
        md(
            """
            ### 4.6.6 Data analysis

            **NumPy** provides the `ndarray`: a block of same-typed numbers with vectorized
            operations implemented in C. Arithmetic applies element-wise without Python loops,
            **broadcasting** stretches smaller arrays to match, boolean masks select elements,
            and reductions (`sum`, `mean`, `max`) run at C speed. pandas, Polars, scikit-learn
            and PyTorch all build on the same idea.
            """
        ),
        code(
            r"""
            import numpy as np

            quantities = np.array([2, 1, 3, 5, 1, 4])
            unit_prices = np.array([240.0, 199.0, 350.5, 240.0, 899.0, 199.0])
            line_totals = quantities * unit_prices  # element-wise
            print(f"{line_totals=}")
            print(f"{line_totals.sum()=}, {line_totals.mean()=:.2f}, {line_totals.max()=}")
            print(f"{line_totals[line_totals > 700]=}  (boolean mask)")
            with_gst = line_totals[:, np.newaxis] * np.array([1.05, 1.12, 1.18])  # broadcasting: 6x1 * 3 -> 6x3
            print(f"{with_gst.shape=}\n{with_gst.round(2)[:2]}")
            print(f"{np.arange(12).reshape(3, 4).sum(axis=0)=}, {quantities.dtype=}, {unit_prices.dtype=}")
            """
        ),
        md(
            """
            **Under the hood: why arrays are fast and small.** A Python list of floats is an
            array of pointers to separate `float` objects (24 bytes each plus the pointer); a
            NumPy array stores the raw 8-byte values contiguously. Seeded random numbers come
            from a `Generator` (`np.random.default_rng(seed)`).
            """
        ),
        code(
            r"""
            rng = np.random.default_rng(46)
            daily_orders = rng.poisson(lam=40, size=1_000_000)
            as_list = daily_orders.tolist()
            list_bytes = sys.getsizeof(as_list) + sum(sys.getsizeof(value) for value in as_list[:1000]) * 1000
            print(
                f"{daily_orders.nbytes / 1e6:.1f} MB as int64 array "
                f"vs ~{list_bytes / 1e6:.0f} MB as a list of ints"
            )
            print(f"{daily_orders[:8]=}, {daily_orders.mean()=:.3f}")
            started = time.perf_counter()
            numpy_total = int(daily_orders.sum())
            numpy_ms = (time.perf_counter() - started) * 1000
            started = time.perf_counter()
            python_total = sum(as_list)
            python_ms = (time.perf_counter() - started) * 1000
            print(
                f"sum: numpy {numpy_ms:.2f} ms, Python {python_ms:.1f} ms, "
                f"equal: {numpy_total == python_total}  (timings vary)"
            )
            """
        ),
        md(
            """
            **pandas** is the long-established DataFrame library: labelled columns, an index,
            rich time-series support and the widest ecosystem (plotting, Excel, SQL,
            statistics). The usual cycle: read, filter, group-by, join, write. The data is the
            seeded order list from the local API, saved as CSV.
            """
        ),
        code(
            r"""
            import pandas as pd

            orders_csv = UNIT46_DIR / "orders.csv"
            pd.DataFrame([order for order in raw_orders if "city" in order]).to_csv(orders_csv, index=False)
            orders = pd.read_csv(orders_csv, parse_dates=["placed_at"])
            orders = orders[
                pd.to_numeric(orders["unit_price"], errors="coerce").notna() & (orders["quantity"] > 0)
            ].copy()
            orders["unit_price"] = orders["unit_price"].astype(float)
            orders["revenue"] = orders["quantity"] * orders["unit_price"]
            print(orders[["order_id", "city", "sku", "quantity", "revenue"]].head(4).to_string(index=False))
            by_city = (
                orders.groupby("city")
                .agg(orders=("order_id", "count"), units=("quantity", "sum"), revenue=("revenue", "sum"))
                .sort_values("revenue", ascending=False)
            )
            print(by_city.round(2))
            """
        ),
        md(
            """
            A join with a product table, a filter on dates, and writing the result. Parquet
            (a compressed, typed, columnar file format) needs the `pyarrow` engine in pandas,
            which is not an Appendix A package, so that step checks first; CSV always works.
            """
        ),
        code(
            r"""
            products = pd.DataFrame(
                {
                    "sku": ["TEA-500", "MUG-02", "JAR-750", "KETTLE-9"],
                    "category": ["tea", "kitchen", "pantry", "kitchen"],
                }
            )
            enriched = orders.merge(products, on="sku", how="left", validate="many_to_one")
            first_week = enriched[enriched["placed_at"].dt.day <= 3]
            print(first_week.groupby("category")["revenue"].sum().round(2).to_dict())
            enriched.to_csv(UNIT46_DIR / "orders_enriched.csv", index=False)
            if installed("pyarrow", "pyarrow (pandas' Parquet engine; not an Appendix A package)"):
                enriched.to_parquet(UNIT46_DIR / "orders_enriched_pandas.parquet")
                print("written with pandas + pyarrow")
            """
        ),
        md(
            """
            **Polars** is a newer DataFrame library written in Rust: multi-threaded, strict
            about types, with an expression API (`pl.col(...)`) and a **lazy** mode that
            optimizes the whole query before running it, like a database. It reads and writes
            Parquet natively. The same analysis:
            """
        ),
        code(
            r"""
            import polars as pl

            pl.Config.set_tbl_formatting("ASCII_MARKDOWN")
            pl.Config.set_tbl_hide_dataframe_shape(True)
            frame = pl.read_csv(orders_csv, try_parse_dates=True)
            clean = (
                frame.with_columns(pl.col("unit_price").cast(pl.Float64, strict=False))
                .filter(pl.col("unit_price").is_not_null() & (pl.col("quantity") > 0))
                .with_columns((pl.col("quantity") * pl.col("unit_price")).alias("revenue"))
            )
            summary = (
                clean.group_by("city")
                .agg(
                    pl.len().alias("orders"),
                    pl.col("quantity").sum().alias("units"),
                    pl.col("revenue").sum().round(2).alias("revenue"),
                )
                .sort("revenue", descending=True)
            )
            print(summary)
            """
        ),
        md(
            """
            Lazy mode (`scan_csv` … `collect()`) builds a plan first; `explain()` shows that the
            filter was pushed down into the CSV scan and only the needed columns are read.
            Then a join and a Parquet round trip:
            """
        ),
        code(
            r"""
            plan = (
                pl.scan_csv(orders_csv)
                .filter(pl.col("quantity") > 3)
                .group_by("sku")
                .agg(pl.col("quantity").sum())
                .sort("sku")
            )
            print("\n".join(plan.explain().splitlines()[-3:]))
            print(plan.collect())
            product_frame = pl.DataFrame(
                {"sku": products["sku"].tolist(), "category": products["category"].tolist()}
            )
            joined = clean.join(product_frame, on="sku", how="left")
            parquet_path = UNIT46_DIR / "orders.parquet"
            joined.write_parquet(parquet_path)
            print(
                f"{parquet_path.stat().st_size} bytes of Parquet, {pl.read_parquet(parquet_path).shape=}, "
                f"columns: {pl.read_parquet(parquet_path).columns[-3:]}"
            )
            """
        ),
        md(
            """
            **When to use which**

            | Use | When |
            | --- | --- |
            | Plain Python / `csv` / `statistics` | a few thousand rows, simple aggregates, no dependency wanted |
            | NumPy | numeric arrays, matrices, vectorized maths, the base for scientific code |
            | pandas | interactive analysis, time series, the widest ecosystem (plotting, Excel, statsmodels, scikit-learn), existing code |
            | Polars | larger-than-comfortable data, pipelines that must be fast and type-strict, lazy queries, multi-core machines |
            | a database (SQLite, DuckDB, PostgreSQL) | data that outlives the process, concurrent writers, joins across many large tables |
            """
        ),
    ]


def _scraping_cells() -> list[NotebookNode]:
    """4.6.7 Parsing and scraping."""
    return [
        md(
            """
            ### 4.6.7 Parsing and scraping

            **BeautifulSoup** parses HTML (even broken HTML) into a tree you can search with
            CSS selectors (`select`, `select_one`) or by tag and attributes (`find`,
            `find_all`). Pass a parser explicitly: `"html.parser"` (built in) or `"lxml"`
            (faster). The page comes from the local shop API.
            """
        ),
        code(
            r"""
            from bs4 import BeautifulSoup

            page = httpx.get(f"{SHOP_API}/products.html", timeout=5)
            soup = BeautifulSoup(page.text, "lxml")
            print(f"{soup.title.string=}")
            for item in soup.select("ul#catalogue li.product"):
                link = item.find("a")
                price = Decimal(item.select_one(".price").get_text().lstrip("₹"))
                sold_out = "sold-out" in item["class"]
                print(
                    f"  {item['data-sku']:<9} {link.get_text():<20} {price:>7} "
                    f"{link['href']:<20} sold out: {sold_out}"
                )
            print(f"{soup.select_one('p.note').get_text(strip=True)=}  (entities decoded)")
            """
        ),
        md(
            """
            **`lxml`** is a fast C-based parser for XML and HTML with full **XPath**. Use it
            directly for XML (feeds, sitemaps, SOAP) or when BeautifulSoup is too slow.
            """
        ),
        code(
            r'''
            from lxml import etree
            from lxml import html as lxml_html

            tree = lxml_html.fromstring(page.text)
            print(f"{tree.xpath('//li[contains(@class, \"product\")]/@data-sku')=}")
            print(f"{tree.xpath('//li[not(contains(@class, \"sold-out\"))]/a/text()')=}")
            sitemap = b"""<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
              <url><loc>https://chai.example.com/products/tea-500</loc><lastmod>2026-11-01</lastmod></url>
              <url><loc>https://chai.example.com/products/mug-02</loc><lastmod>2026-11-05</lastmod></url>
            </urlset>"""
            root = etree.fromstring(sitemap)
            namespaces = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
            entries = [
                (
                    url.findtext("sm:loc", namespaces=namespaces),
                    url.findtext("sm:lastmod", namespaces=namespaces),
                )
                for url in root.xpath("//sm:url", namespaces=namespaces)
            ]
            print(f"{entries=}")
            print(
                "changed after 3 Nov: "
                f"{[location for location, modified in entries if modified > '2026-11-03']}"
            )
            print(
                f"{root.xpath('//sm:url[sm:lastmod > \"2026-11-03\"]', namespaces=namespaces)=}"
                "  (XPath 1.0 compares strings as numbers)"
            )
            '''
        ),
        md(
            """
            **Scraping politely and legally.** Prefer an official API. If you scrape: read the
            site's terms; obey **`robots.txt`** (the standard library's `urllib.robotparser`
            reads it); identify yourself with a descriptive `User-Agent`; **rate-limit**
            (honour `Crawl-delay`, never hammer a server, back off on 429/503); cache pages you
            already fetched; and never collect personal data you have no right to.
            """
        ),
        code(
            r"""
            from urllib import robotparser

            robots = robotparser.RobotFileParser()
            robots.parse(httpx.get(f"{SHOP_API}/robots.txt", timeout=5).text.splitlines())
            for agent, path in [
                ("chai-corner-bot", "/products.html"),
                ("chai-corner-bot", "/admin/orders"),
                ("BadBot", "/products.html"),
            ]:
                print(f"  {agent:<16} {path:<16} allowed: {robots.can_fetch(agent, f'{SHOP_API}{path}')}")
            print(f"{robots.crawl_delay('chai-corner-bot')=} seconds")
            """
        ),
        md(
            """
            A minimal **rate limiter**: remember when the last request was sent and sleep until
            the minimum interval has passed (`time.monotonic`, never the wall clock). The demo
            uses 0.2 s instead of the site's 1 s crawl delay to stay quick; the elapsed time
            shows the spacing was enforced.
            """
        ),
        code(
            r'''
            class Throttle:
                """Allow at most one call per min_interval seconds."""

                def __init__(self, min_interval: float) -> None:
                    self.min_interval = min_interval
                    self.last_call = -float("inf")

                def wait(self) -> None:
                    pause = self.last_call + self.min_interval - time.monotonic()
                    if pause > 0:
                        time.sleep(pause)
                    self.last_call = time.monotonic()


            throttle = Throttle(min_interval=0.2)
            started = time.monotonic()
            with httpx.Client(
                base_url=SHOP_API,
                headers={"User-Agent": "chai-corner-bot/1.0 (+mailto:dev@chai.example.com)"},
                timeout=5,
            ) as polite_client:
                for path in ("/products.html", "/rates", "/robots.txt", "/rates"):
                    throttle.wait()
                    polite_client.get(path).raise_for_status()
            print(f"4 requests took {time.monotonic() - started:.1f} s (at least 3 x 0.2 s)")
            '''
        ),
    ]


def _template_cells() -> list[NotebookNode]:
    """4.6.8 Templating."""
    return [
        md(
            """
            ### 4.6.8 Templating

            **Jinja2** renders text from templates: `{{ expression }}` outputs a value,
            `{% statement %}` runs control flow, `{# comment #}` is ignored. An `Environment`
            holds the configuration: where templates come from (a `FileSystemLoader` in real
            projects, a `DictLoader` here), **autoescaping** for HTML, and `StrictUndefined`
            so a misspelt variable is an error instead of an empty string.
            """
        ),
        code(
            r'''
            from jinja2 import DictLoader, Environment, StrictUndefined, select_autoescape


            def inr(amount: object) -> str:
                """Custom filter: 1234.5 -> '₹1,234.50'."""
                return f"₹{Decimal(str(amount)):,.2f}"


            TEMPLATES = {
                "base.html": (
                    "<html><head><title>{% block title %}Chai Corner{% endblock %}</title></head>\n"
                    "<body>\n{% block content %}{% endblock %}\n"
                    "<footer>Generated {{ generated_at.strftime('%Y-%m-%d %H:%M %Z') }}</footer>\n"
                    "</body></html>"
                ),
                "orders.html": (
                    "{% extends 'base.html' %}\n"
                    "{% block title %}Orders for {{ city }}{% endblock %}\n"
                    "{% block content %}<h1>{{ city | upper }}: {{ orders | length }} orders</h1>\n<ul>\n"
                    "{% for order in orders %}  <li class=\"{{ loop.cycle('odd', 'even') }}\">"
                    "#{{ loop.index }} {{ order.customer }}: {{ order.total | inr }}"
                    "{% if order.total > 1000 %} (big){% endif %}</li>\n"
                    "{% else %}  <li>No orders</li>\n{% endfor %}</ul>\n"
                    "<p>Tags: {{ tags | join(', ') | default('none', true) }}</p>{% endblock %}"
                ),
                "receipt.txt": (
                    "Dear {{ customer }},\nThank you for order #{{ order_id }} ({{ total | inr }}).\n"
                    "{% for line in lines %}- {{ line.quantity }} x {{ line.sku }}\n{% endfor %}"
                ),
            }
            template_env = Environment(
                loader=DictLoader(TEMPLATES), autoescape=select_autoescape(["html"]), undefined=StrictUndefined
            )
            template_env.filters["inr"] = inr
            print(f"{sorted(template_env.list_templates())=}")
            '''
        ),
        md(
            """
            **Variables, loops, filters and inheritance** in one page: `orders.html` *extends*
            `base.html` and fills its blocks; `loop.index` and `loop.cycle` come from the `for`
            loop, `{% else %}` handles an empty list; `upper`, `length`, `join`, `default` are
            built-in filters and `inr` is ours.
            """
        ),
        code(
            r"""
            orders_for_page = [
                {"customer": "Asha", "total": Decimal("679.00")},
                {"customer": "Ravi", "total": Decimal("1798.50")},
            ]
            print(
                template_env.get_template("orders.html").render(
                    city="Pune", orders=orders_for_page, tags=["gift"], generated_at=FIXED_MOMENT
                )
            )
            print("---")
            print(
                template_env.get_template("orders.html")
                .render(city="Mumbai", orders=[], tags=[], generated_at=FIXED_MOMENT)
                .split("<body>")[1]
            )
            """
        ),
        md(
            """
            **Autoescaping.** In HTML templates every `{{ value }}` is HTML-escaped, so data
            such as a customer name containing `<script>` is displayed, not executed (the
            defence against cross-site scripting). Mark a value `|safe` (or `Markup`) only when
            you produced the HTML yourself. Text templates (e-mails, `.txt`) are not escaped:
            `select_autoescape(["html"])` decides by file extension.
            """
        ),
        code(
            r"""
            hostile = [{"customer": "<script>alert('hi')</script> & Co", "total": Decimal("10")}]
            rendered = template_env.get_template("orders.html").render(
                city="Pune", orders=hostile, tags=["<b>vip</b>"], generated_at=FIXED_MOMENT
            )
            print([line for line in rendered.splitlines() if "<li" in line or "Tags" in line])
            print(
                template_env.get_template("receipt.txt").render(
                    customer="Asha & family",
                    order_id=7,
                    total=Decimal("679"),
                    lines=[{"quantity": 2, "sku": "TEA-500"}],
                )
            )
            print(raised_message(lambda: template_env.get_template("receipt.txt").render(customer="Asha")))
            print(
                f"{template_env.from_string('{{ name }}').render(name='<b>') = }"
                "  (strings are escaped too: select_autoescape's default_for_string)"
            )
            """
        ),
        *predict_cells(
            """
            from jinja2 import Environment

            print(Environment().from_string("Hi {{ name }}").render(name="<b>Asha</b>"))
            print(Environment(autoescape=True).from_string("Hi {{ name }}").render(name="<b>Asha</b>"))
            """,
            """
            `Hi <b>Asha</b>` then `Hi &lt;b&gt;Asha&lt;/b&gt;`. A bare `Environment()` does
            **not** autoescape (Jinja2 is also used for non-HTML text), so templates rendering
            HTML from user data are vulnerable unless you turn escaping on, ideally with
            `select_autoescape(...)` as in the cells above.
            """,
            """
            print(Environment().from_string("Hi {{ name }}").render(name="<b>Asha</b>"))
            print(Environment(autoescape=True).from_string("Hi {{ name }}").render(name="<b>Asha</b>"))
            """,
        ),
    ]


def _image_cloud_cells() -> list[NotebookNode]:
    """4.6.9 Files, images and cloud storage."""
    return [
        md(
            """
            ### 4.6.9 Files, images and cloud storage

            **Pillow** (the maintained fork of PIL) opens, edits and saves images. Typical
            jobs: product thumbnails, converting uploads to a standard format, stripping or
            honouring EXIF orientation (`ImageOps.exif_transpose`). `resize` sets an exact size;
            `thumbnail` shrinks **in place** keeping the aspect ratio. The image is drawn here,
            so the demo needs no files.
            """
        ),
        code(
            r"""
            from PIL import Image, ImageDraw, features

            banner = Image.new("RGB", (1200, 600), (250, 240, 225))
            draw = ImageDraw.Draw(banner)
            for stripe in range(0, 1200, 100):
                draw.rectangle([stripe, 0, stripe + 50, 600], fill=(230, 120, 30))
            draw.ellipse([450, 150, 750, 450], fill=(120, 60, 20))
            images_dir = UNIT46_DIR / "images"
            images_dir.mkdir(exist_ok=True)
            banner.save(images_dir / "banner.png")
            with Image.open(images_dir / "banner.png") as opened:
                print(f"{opened.format=}, {opened.size=}, {opened.mode=}")
            resized = banner.resize((600, 300))
            thumbnail = banner.copy()
            thumbnail.thumbnail((256, 256))  # in place, keeps 2:1
            print(f"{resized.size=}, {thumbnail.size=}")
            """
        ),
        md(
            """
            **Formats.** The extension (or `format=`) picks the encoder. JPEG is lossy and has
            no alpha channel (convert `RGBA` to `RGB` first); PNG is lossless; WebP does both.
            File sizes below depend on the Pillow and codec versions.
            """
        ),
        code(
            r"""
            thumbnail.save(images_dir / "thumb.png", optimize=True)
            thumbnail.convert("RGB").save(images_dir / "thumb.jpg", quality=85)
            if features.check("webp"):
                thumbnail.save(images_dir / "thumb.webp", quality=80)
            for path in sorted(images_dir.glob("thumb.*")):
                with Image.open(path) as image:
                    print(f"  {path.name:<11} {image.format:<5} {image.size} {path.stat().st_size:>6} bytes")
            transparent = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
            print(raised_message(lambda: transparent.save(io.BytesIO(), format="JPEG")))
            """
        ),
        md(
            """
            **`boto3`** is the AWS SDK; S3-compatible services (MinIO, Cloudflare R2,
            DigitalOcean Spaces) work with the same client and an `endpoint_url`. The three
            everyday operations: **upload** (`put_object`, or `upload_file` for large files
            with multipart), **download** (`get_object`, `download_file`) and **presigned
            URLs**, which let a browser upload or download one object directly for a limited
            time without your credentials.

            No real bucket is used. A presigned URL is computed locally (no network). Upload
            and download go through botocore's **`Stubber`**, which checks the request
            parameters and returns canned responses: the standard way to unit-test AWS code.
            Fake credentials, and empty config files so nothing is read from `~/.aws`.
            """
        ),
        code(
            r"""
            import urllib.parse

            import boto3
            from botocore.config import Config

            aws_isolation = {"AWS_CONFIG_FILE": os.devnull, "AWS_SHARED_CREDENTIALS_FILE": os.devnull}
            with mock.patch.dict(os.environ, aws_isolation):
                s3 = boto3.client(
                    "s3",
                    region_name="ap-south-1",
                    aws_access_key_id="AKIAEXAMPLEEXAMPLE",
                    aws_secret_access_key="example-secret-not-real",
                    config=Config(signature_version="s3v4"),
                )
            download_url = s3.generate_presigned_url(
                "get_object", Params={"Bucket": "chai-reports", "Key": "2026/11/report.html"}, ExpiresIn=900
            )
            parts = urllib.parse.urlsplit(download_url)
            query = urllib.parse.parse_qs(parts.query)
            print(f"{parts.netloc=}, {parts.path=}")
            print(f"query keys: {sorted(query)}")
            print(
                f"{query['X-Amz-Expires']=}, {query['X-Amz-Algorithm']=}  (date and signature change with time)"
            )
            """
        ),
        md(
            "Upload, list and download against the stub; `assert_no_pending_responses` proves every expected call happened:"
        ),
        code(
            r"""
            from botocore.response import StreamingBody
            from botocore.stub import ANY, Stubber

            report_bytes = b"<html>November report</html>"
            with Stubber(s3) as stubber:
                stubber.add_response(
                    "put_object",
                    {"ETag": '"abc123"'},
                    {
                        "Bucket": "chai-reports",
                        "Key": "2026/11/report.html",
                        "Body": ANY,
                        "ContentType": "text/html",
                    },
                )
                stubber.add_response(
                    "list_objects_v2",
                    {"KeyCount": 1, "Contents": [{"Key": "2026/11/report.html", "Size": len(report_bytes)}]},
                    {"Bucket": "chai-reports", "Prefix": "2026/11/"},
                )
                stubber.add_response(
                    "get_object",
                    {
                        "Body": StreamingBody(io.BytesIO(report_bytes), len(report_bytes)),
                        "ContentLength": len(report_bytes),
                    },
                    {"Bucket": "chai-reports", "Key": "2026/11/report.html"},
                )

                upload = s3.put_object(
                    Bucket="chai-reports", Key="2026/11/report.html", Body=report_bytes, ContentType="text/html"
                )
                listing = s3.list_objects_v2(Bucket="chai-reports", Prefix="2026/11/")
                downloaded = s3.get_object(Bucket="chai-reports", Key="2026/11/report.html")["Body"].read()
                stubber.assert_no_pending_responses()
            print(f"{upload['ETag']=}, {[item['Key'] for item in listing['Contents']]=}, {downloaded=}")
            with Stubber(s3) as stubber:
                stubber.add_client_error("get_object", service_error_code="NoSuchKey", http_status_code=404)
                print(raised_message(lambda: s3.get_object(Bucket="chai-reports", Key="missing.html")))
            """
        ),
    ]


def _utility_cells() -> list[NotebookNode]:
    """4.6.10 Developer utilities."""
    return [
        md(
            """
            ### 4.6.10 Developer utilities

            **`loguru` vs stdlib `logging`.** loguru gives one ready-made `logger` with a
            readable default format, `{}`-style messages, easy file sinks with rotation and
            retention, context binding and exception catching, all without handlers, formatters
            and `dictConfig` (Unit 4.3.9).

            | | stdlib `logging` | `loguru` |
            | --- | --- | --- |
            | Setup | `getLogger(__name__)` + handlers/formatters/`dictConfig` | `logger.add(sink, format=..., level=...)` |
            | Context | `extra=`, `LoggerAdapter`, filters | `logger.bind(order_id=7)`, `contextualize()` |
            | Files | `RotatingFileHandler` | `logger.add("app.log", rotation="10 MB", retention="7 days")` |
            | Ecosystem | every library logs through it | an extra dependency; intercept stdlib logs with a handler |
            | Libraries | the right choice | do not use in a library you publish |
            """
        ),
        code(
            r"""
            from loguru import logger as loguru_logger

            loguru_logger.remove()  # drop the default stderr sink
            sink_id = loguru_logger.add(
                sys.stdout,
                format="{level: <8} | {function}:{line} | {message} | {extra}",
                colorize=False,
                backtrace=False,
                diagnose=False,
            )


            def ship(order_id: int) -> None:
                log = loguru_logger.bind(order_id=order_id)
                log.info("packing {} items", 3)
                log.warning("courier slot missing")


            ship(7)
            try:
                Decimal("679") / 0
            except ArithmeticError:
                loguru_logger.opt(exception=False).error("charging failed")
            loguru_logger.remove(sink_id)
            """
        ),
        md(
            """
            **`attrs`** is the library `dataclasses` was modelled on, and still does more:
            validators and converters on fields, `__slots__` by default (`@define`), frozen
            classes with `evolve`, and keyword-only or private-attribute handling. Choose
            `dataclasses` for plain records, `attrs` when you need validation without
            Pydantic's parsing.
            """
        ),
        code(
            r"""
            import attrs


            @attrs.define(frozen=True)
            class StockLevel:
                sku: str = attrs.field(validator=attrs.validators.matches_re(r"[A-Z]{2,6}-\d{1,4}"))
                quantity: int = attrs.field(converter=int, validator=attrs.validators.ge(0))
                reorder_level: int = 5

                @property
                def is_low(self) -> bool:
                    return self.quantity <= self.reorder_level


            level = StockLevel("TEA-500", "12")  # converter: "12" -> 12
            print(f"{level=}, {level.is_low=}")
            print(f"{attrs.evolve(level, quantity=3).is_low=}, {attrs.asdict(level)=}")
            try:
                StockLevel("tea", 1)
            except ValueError as error:
                print(f"ValueError: {error.args[0]}")  # attrs adds the attribute and validator as extra args
            print(raised_message(lambda: StockLevel("TEA-500", -1)))
            print(f"{hasattr(level, '__dict__')=}  (slotted)")
            """
        ),
        md(
            """
            **`more-itertools`** collects the iteration recipes from the `itertools` docs and
            many more, tested and named: batching, windows, partitioning, "exactly one"
            checks, de-duplication preserving order.
            """
        ),
        code(
            r"""
            import more_itertools as mit

            skus = ["TEA-500", "MUG-02", "TEA-500", "JAR-750", "KETTLE-9", "MUG-02", "SPOON-1"]
            print(f"{list(mit.chunked(skus, 3))=}")
            print(f"{list(mit.windowed([42, 38, 51, 47], 2))=}")
            print(f"{list(mit.unique_everseen(skus))=}")
            cheap, expensive = mit.partition(lambda price: price >= 300, [240, 199, 350, 899, 60])
            print(f"{list(cheap)=}, {list(expensive)=}")
            print(f"{mit.first([], default='none')=}, {mit.one(['only'])=}")
            print(raised_message(lambda: mit.one(["a", "b"])))
            print(f"{list(mit.pairwise('ABC'))=}, {mit.ilen(x for x in range(10) if x % 3 == 0)=}")
            """
        ),
        md(
            """
            **`cachetools`** adds cache types the standard library lacks: `TTLCache` (entries
            expire after `ttl` seconds), `LRUCache`, `LFUCache`, and a `@cached` decorator that
            takes any of them (plus a `lock` for threads). `functools.lru_cache` has no
            expiry, which is wrong for data that changes, such as exchange rates. A fake timer
            makes expiry visible without waiting.
            """
        ),
        code(
            r"""
            from cachetools import LRUCache, TTLCache, cached

            fake_now = [0.0]
            rate_lookups: list[str] = []


            @cached(cache=TTLCache(maxsize=100, ttl=60, timer=lambda: fake_now[0]))
            def exchange_rate(currency: str) -> float:
                rate_lookups.append(currency)
                return httpx.get(f"{SHOP_API}/rates", timeout=5).json()["rates"][currency]


            print(f"{exchange_rate('USD')=}, {exchange_rate('USD')=}, lookups: {rate_lookups}")
            fake_now[0] += 61  # a minute later: expired
            print(f"{exchange_rate('USD')=}, lookups: {rate_lookups}")

            recent = LRUCache(maxsize=2)
            recent["TEA-500"], recent["MUG-02"] = 240, 199
            recent["TEA-500"]  # touch: now most recent
            recent["JAR-750"] = 350  # evicts the least recently used
            print(f"{sorted(recent)=}")
            """
        ),
    ]


LAB_SETUP_SOURCE = r"""
import httpx
import polars as pl
import tenacity  # noqa: F401  (use tenacity.retry(...), tenacity.stop_after_attempt(...), ...)
import typer
from jinja2 import Environment, select_autoescape
from pydantic import AwareDatetime, BaseModel, Field, PositiveInt, ValidationError
from rich.console import Console
from rich.table import Table

LAB46_DIR = find_repo_root() / "notebooks" / "_scratch" / "unit46" / "lab"
LAB46_DIR.mkdir(parents=True, exist_ok=True)
LAB_API = start_shop_api()
print(f"lab API: {LAB_API}; lab files go to {LAB46_DIR.relative_to(find_repo_root()).as_posix()}/")
"""


def _lab_cells() -> list[NotebookNode]:
    """Lab 4.6."""
    return [
        md(
            """
            ### Lab 4.6

            One exercise in six parts that together form a small reporting tool. The lab setup
            cell imports what you need and makes sure the local shop API is running
            (`LAB_API`). Until you finish, the checks print FAIL; that is expected.

            #### Exercise 1 — a `typer` + `rich` CLI: `httpx` + `tenacity` → Pydantic → Polars → `rich` table → Jinja2 report

            1. **`fetch_orders(client, path="/orders")`** GETs `path` with the given
               `httpx.Client` and returns the decoded JSON list. Decorate it with
               `tenacity.retry(...)` (the setup imports the module as `tenacity`):
               retry only transient failures (HTTP 5xx and `httpx.TransportError`, never 4xx),
               at most **4 attempts**, exponential backoff with tiny waits (e.g.
               `wait_exponential(multiplier=0.01, max=0.05)`), and `reraise=True`.
            2. **`OrderRecord`**, a Pydantic model: `order_id` and `quantity` positive ints,
               `customer`, `city`, `sku` strings, `unit_price` a `Decimal` greater than 0,
               `placed_at` a timezone-aware datetime.
            3. **`validate_orders(raw)`** returns `(valid_records, problems)`, where each problem
               is a string starting `"record {index}:"` (index in `raw`), one per invalid
               record.
            4. **`summarize(records)`** returns a Polars DataFrame with exactly the columns
               `city`, `orders`, `units`, `revenue` (float, rounded to 2 places), one row per
               city, sorted by revenue (highest first).
            5. **`build_table(summary)`** returns a `rich.table.Table` titled
               `"Revenue by city"` with columns `City`, `Orders`, `Units`, `Revenue (INR)` and one
               row per city (revenue formatted like `12,345.50`).
            6. **`render_report(summary, generated_at)`** returns an HTML page rendered with
               Jinja2 **with autoescaping on**: a `<table>` with a header row and one `<tr>` per
               city, and the text `Generated 2026-11-07 09:30 UTC` (format
               `%Y-%m-%d %H:%M %Z`).
            7. **`app`**, a `typer.Typer()` with one command taking `--base-url` (required),
               `--path` (default `/orders`) and `--output` (default `report.html`): fetch,
               validate, summarize, print the rich table, write the report, then print
               `"{valid} valid orders, {rejected} rejected; report written to {output name}"`.
               On an HTTP error print a line starting `error:` and exit with code 1.
            """
        ),
        code(LAB_SETUP_SOURCE),
        md("The stubs (the order follows the numbered parts above):"),
        code(
            r'''
            def fetch_orders(client: httpx.Client, path: str = "/orders") -> list[dict[str, object]]:
                """GET path and return the JSON list (retried by tenacity)."""
                raise NotImplementedError


            class OrderRecord(BaseModel):
                """One validated order."""


            def validate_orders(raw: list[dict[str, object]]) -> tuple[list[OrderRecord], list[str]]:
                """(valid records, one 'record {index}: ...' message per invalid record)."""
                raise NotImplementedError


            def summarize(records: list[OrderRecord]) -> pl.DataFrame:
                """city, orders, units, revenue; sorted by revenue, highest first."""
                raise NotImplementedError


            def build_table(summary: pl.DataFrame) -> Table:
                """A rich table titled 'Revenue by city'."""
                raise NotImplementedError


            def render_report(summary: pl.DataFrame, generated_at: datetime) -> str:
                """An autoescaped Jinja2 HTML report."""
                raise NotImplementedError


            app = typer.Typer(add_completion=False)
            '''
        ),
        md("Check exercise 1 (it calls your code against the local API several times):"),
        code(
            r"""
            from typer.testing import CliRunner


            def hits(key: str) -> int:
                return httpx.get(f"{LAB_API}/hits", params={"key": key}, timeout=5).json()["hits"]


            def fetch_story(key: str, fail: int) -> tuple[str, int]:
                with httpx.Client(base_url=LAB_API, timeout=5) as client:
                    client.get("/reset")
                    try:
                        outcome = str(len(fetch_orders(client, f"/orders?key={key}&fail={fail}")))
                    except httpx.HTTPStatusError as error:
                        outcome = f"HTTPStatusError {error.response.status_code}"
                return outcome, hits(key)


            def not_found_story() -> str:
                with httpx.Client(base_url=LAB_API, timeout=5) as client:
                    started = time.monotonic()
                    try:
                        fetch_orders(client, "/status/404")
                    except httpx.HTTPStatusError as error:
                        return f"{error.response.status_code} fast={time.monotonic() - started < 0.5}"
                return "no error"


            LAB_RAW = demo_orders()
            VALID_RAW = [record for index, record in enumerate(LAB_RAW) if index not in (6, 17, 29)]
            EXPECTED_REVENUE = {}
            for record in VALID_RAW:
                EXPECTED_REVENUE[record["city"]] = EXPECTED_REVENUE.get(record["city"], Decimal(0)) + record[
                    "quantity"
                ] * Decimal(record["unit_price"])
            EXPECTED_ORDER = sorted(EXPECTED_REVENUE, key=lambda city: -EXPECTED_REVENUE[city])


            def lab_summary() -> pl.DataFrame:
                return summarize(validate_orders(LAB_RAW)[0])


            def table_facts() -> tuple[object, ...]:
                table = build_table(lab_summary())
                return table.title, [str(column.header) for column in table.columns], table.row_count


            def report_facts() -> tuple[object, ...]:
                html = render_report(lab_summary(), datetime(2026, 11, 7, 9, 30, tzinfo=UTC))
                return (
                    html.count("<tr"),
                    "Hubli &amp; Dharwad" in html,
                    "Hubli & Dharwad" in html,
                    "Generated 2026-11-07 09:30 UTC" in html,
                )


            def cli_story(path: str) -> tuple[int, bool, bool, bool]:
                output = LAB46_DIR / "report.html"
                output.unlink(missing_ok=True)
                httpx.get(f"{LAB_API}/reset", timeout=5)
                result = CliRunner().invoke(
                    app,
                    ["--base-url", LAB_API, "--path", path, "--output", str(output)],
                    env={"COLUMNS": "100", "NO_COLOR": "1"},
                )
                text = result.output
                return (
                    result.exit_code,
                    "Revenue by city" in text,
                    "37 valid orders, 3 rejected; report written to report.html" in text,
                    output.exists(),
                )


            run_checks(
                [
                    ("fetch: 2 failures then success", lambda: fetch_story("lab-ok", 2), ("40", 3)),
                    (
                        "fetch: gives up after 4 attempts",
                        lambda: fetch_story("lab-down", 9),
                        ("HTTPStatusError 503", 4),
                    ),
                    ("fetch: 404 is not retried", not_found_story, "404 fast=True"),
                    ("validate: 37 valid", lambda: len(validate_orders(LAB_RAW)[0]), 37),
                    (
                        "validate: problems name records 6, 17, 29",
                        lambda: [problem.split(":")[0] for problem in validate_orders(LAB_RAW)[1]],
                        ["record 6", "record 17", "record 29"],
                    ),
                    (
                        "OrderRecord types",
                        lambda: (
                            type(validate_orders(LAB_RAW)[0][0].unit_price).__name__,
                            validate_orders(LAB_RAW)[0][0].placed_at.utcoffset() is not None,
                        ),
                        ("Decimal", True),
                    ),
                    ("summary columns", lambda: lab_summary().columns, ["city", "orders", "units", "revenue"]),
                    (
                        "summary order and revenue",
                        lambda: [(row["city"], row["revenue"]) for row in lab_summary().iter_rows(named=True)],
                        [(city, float(round(EXPECTED_REVENUE[city], 2))) for city in EXPECTED_ORDER],
                    ),
                    (
                        "summary counts",
                        lambda: (lab_summary()["orders"].sum(), lab_summary()["units"].sum()),
                        (37, sum(record["quantity"] for record in VALID_RAW)),
                    ),
                    (
                        "rich table",
                        table_facts,
                        ("Revenue by city", ["City", "Orders", "Units", "Revenue (INR)"], len(EXPECTED_ORDER)),
                    ),
                    (
                        "report: rows, escaping, timestamp",
                        report_facts,
                        (len(EXPECTED_ORDER) + 1, True, False, True),
                    ),
                    ("CLI success", lambda: cli_story("/orders"), (0, True, True, True)),
                    ("CLI HTTP error -> exit 1", lambda: cli_story("/status/404")[0], 1),
                ]
            )
            """
        ),
    ]


def _recap_cells() -> list[NotebookNode]:
    """Recap for Unit 4.6."""
    return [
        md(
            """
            ### Recap — Unit 4.6

            | Concept | One-line takeaway | JS equivalent |
            | --- | --- | --- |
            | Choosing a library | Check maintenance, usage, `py.typed`, licence, advisories, dependency weight; read the source | npm trends, Snyk |
            | HTTP | `requests` or `httpx`; always a timeout and `raise_for_status()`; one shared client/session; `AsyncClient` for concurrency; `MockTransport` for tests | `axios`, `fetch` |
            | Resilience | `tenacity`: retry only transient errors, exponential backoff + jitter, a stop condition, `reraise=True` | `p-retry` |
            | Validation | Pydantic models for API data and config; per-record validation for imports; `pydantic-settings` + `.env` for settings | `zod`, `dotenv` |
            | CLIs | `typer` (hints) on top of `click`; `rich` tables, progress, logging, tracebacks | `commander`, `chalk` |
            | Dates, JSON | `dateutil.parser`, `relativedelta`, `rrule`; `orjson` for speed (bytes; `default=` for Decimal) | `date-fns`, `fast-json-stringify` |
            | Data | NumPy arrays; pandas for ecosystem and exploration; Polars for speed and lazy queries; Parquet for storage | `danfo.js` |
            | Scraping | BeautifulSoup/lxml; obey robots.txt, identify yourself, rate-limit | `cheerio` |
            | Templating | Jinja2 with autoescaping and `StrictUndefined`; inheritance and filters | `nunjucks` |
            | Images, S3 | Pillow `thumbnail`/formats; `boto3` put/get/presigned URLs, tested with `Stubber` | `sharp`, AWS SDK |
            | Utilities | `loguru` for apps (not libraries), `attrs`, `more-itertools`, `cachetools` TTL caches | `pino`, `lodash`, `lru-cache` |

            **Further reading**

            - [requests](https://requests.readthedocs.io/), [HTTPX](https://www.python-httpx.org/),
              [Tenacity](https://tenacity.readthedocs.io/)
            - [Pydantic](https://docs.pydantic.dev/), [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/),
              [python-dotenv](https://saurabh-kumar.com/python-dotenv/)
            - [Typer](https://typer.tiangolo.com/), [Click](https://click.palletsprojects.com/), [Rich](https://rich.readthedocs.io/)
            - [dateutil](https://dateutil.readthedocs.io/), [orjson](https://github.com/ijl/orjson), [msgspec](https://jcristharif.com/msgspec/)
            - [NumPy](https://numpy.org/doc/stable/user/absolute_beginners.html), [pandas](https://pandas.pydata.org/docs/user_guide/10min.html),
              [Polars](https://docs.pola.rs/user-guide/)
            - [Beautiful Soup](https://www.crummy.com/software/BeautifulSoup/bs4/doc/), [lxml](https://lxml.de/),
              [`urllib.robotparser`](https://docs.python.org/3/library/urllib.robotparser.html)
            - [Jinja](https://jinja.palletsprojects.com/), [Pillow](https://pillow.readthedocs.io/),
              [Boto3 S3 guide](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/s3.html),
              [botocore Stubber](https://botocore.amazonaws.com/v1/documentation/api/latest/reference/stubber.html)
            - [loguru](https://loguru.readthedocs.io/), [attrs](https://www.attrs.org/),
              [more-itertools](https://more-itertools.readthedocs.io/), [cachetools](https://cachetools.readthedocs.io/)
            - [PEP 561](https://peps.python.org/pep-0561/) (`py.typed`), [PEP 517](https://peps.python.org/pep-0517/)
            """
        ),
    ]


def cells() -> list[NotebookNode]:
    """Return the cells for Unit 4.6 and Lab 4.6."""
    return [
        *_overview_cells(),
        *_choosing_cells(),
        *_http_cells(),
        *_validation_cells(),
        *_cli_cells(),
        *_date_json_cells(),
        *_data_cells(),
        *_scraping_cells(),
        *_template_cells(),
        *_image_cloud_cells(),
        *_utility_cells(),
        *_lab_cells(),
        *_recap_cells(),
    ]
