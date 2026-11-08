"""Unit 4.3 — Testing, Debugging and Logging (with Lab 4.3)."""

from nbformat import NotebookNode

from nb_builder import code, md, predict_cells

UNIT_SETUP_SOURCE = r'''
import ast
import contextlib
import functools
import importlib.util
import inspect
import io
import json
import linecache
import logging
import logging.config
import logging.handlers
import os
import queue
import re
import shlex
import shutil
import subprocess
import sys
import textwrap
import time
import types
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from unittest import mock

REPO_ROOT = find_repo_root()
scratch_dir = REPO_ROOT / "notebooks" / "_scratch"  # git-ignored
UNIT43_DIR = scratch_dir / "unit43"
UNIT43_DIR.mkdir(parents=True, exist_ok=True)
VENV_BIN = Path(sys.executable).parent
PYTHON_HOME = Path(sys.base_prefix)
PAISE = Decimal("0.01")


def tool_env(**overrides: str) -> dict[str, str]:
    """Environment for child tools: plain output, scratch caches, no personal git/IPython config."""
    dropped = ("UV_", "PIP_", "VIRTUAL_ENV", "PYTHONPATH", "PYTEST_", "COV", "PYTHONBREAKPOINT")
    inherited = {key: value for key, value in os.environ.items() if not key.startswith(dropped)}
    return {
        **inherited,
        "NO_COLOR": "1",
        "PY_COLORS": "0",
        "PYTHON_COLORS": "0",
        "COLUMNS": "80",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PRE_COMMIT_HOME": str(UNIT43_DIR / "pre-commit-cache"),
        "IPYTHONDIR": str(UNIT43_DIR / "ipython-profile"),
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CEILING_DIRECTORIES": str(scratch_dir),
        "GIT_AUTHOR_NAME": "Course Demo",
        "GIT_AUTHOR_EMAIL": "demo@example.com",
        "GIT_COMMITTER_NAME": "Course Demo",
        "GIT_COMMITTER_EMAIL": "demo@example.com",
        **overrides,
    }


TIMING = re.compile(r"\b(in|after) \d+(\.\d+)?(ms|s|µs)\b")
ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
ADDRESS = re.compile(r" at 0x[0-9a-f]+")


def tidy(text: str) -> str:
    """Show paths as <scratch>, <repo>, <python> or ~, timings as <time>, addresses as 0x..."""
    for folder, label in (
        (UNIT43_DIR, "<scratch>"),
        (REPO_ROOT, "<repo>"),
        (PYTHON_HOME, "<python>"),
        (Path.home(), "~"),
    ):
        text = text.replace(str(folder), label)
    return ADDRESS.sub(" at 0x...", ANSI_ESCAPE.sub("", TIMING.sub(r"\1 <time>", text)))


def run_tool(
    *command: str,
    cwd: Path = UNIT43_DIR,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
    merged: bool = False,
    timeout: int = 300,
) -> tuple[int, str]:
    """Run a CLI tool in a child process; return (exit code, tidied stdout + stderr).

    merged=True interleaves stderr with stdout in the order they were written.
    """
    name = command[0]
    found = sys.executable if name == "python" else str(VENV_BIN / name)
    if not Path(found).exists():
        found = shutil.which(name)
    if found is None:
        return 127, f"SKIP: {name} is not installed on this machine"
    completed = subprocess.run(
        [found, *command[1:]],
        cwd=cwd,
        env={**(env or tool_env()), **({"PYTHONUNBUFFERED": "1"} if merged else {})},
        input=input_text,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT if merged else subprocess.PIPE,
        text=True,
        timeout=timeout,
    )
    return completed.returncode, tidy((completed.stdout + (completed.stderr or "")).rstrip())


def shell(
    *command: str,
    cwd: Path = UNIT43_DIR,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
    merged: bool = False,
    keep: str | None = None,
    max_lines: int | None = None,
) -> None:
    """Print `[folder]$ command` and the tool's real output (only lines matching keep, if given)."""
    exit_code, output = run_tool(*command, cwd=cwd, env=env, input_text=input_text, merged=merged)
    print(f"[{tidy(str(cwd))}]$ {shlex.join(command)}")
    lines = output.splitlines()
    if keep is not None:
        lines = [line for line in lines if re.search(keep, line)]
    if max_lines is not None and len(lines) > max_lines:
        lines = [*lines[:max_lines], f"... ({len(lines) - max_lines} more lines)"]
    if lines:
        print(textwrap.indent("\n".join(lines), "  ", lambda line: True))
    if exit_code:
        print(f"  (exit code {exit_code})")


def fresh_dir(name: str) -> Path:
    """An empty folder <scratch>/<name>, recreated on every run."""
    folder = UNIT43_DIR / name
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    return folder


def write_files(root: Path, files: dict[str, str]) -> Path:
    """Write relative path -> text (dedented) under root; return root."""
    for relative_path, text in files.items():
        target = root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(textwrap.dedent(text).lstrip("\n"))
    return root


def show_file(path: Path) -> None:
    """Print a text file with a header line."""
    print(f"--- {path.name} ---\n{tidy(path.read_text().rstrip())}")


PYTEST_CONFIG = """
[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
"""


def project(name: str, files: dict[str, str]) -> Path:
    """A fresh scratch test project: pyproject.toml (pytest config) plus the given files."""
    return write_files(fresh_dir(name), {"pyproject.toml": PYTEST_CONFIG, **files})


def run_pytest(root: Path, *arguments: str, **shell_options: object) -> None:
    """Run the real pytest in root (a child process) and print its output."""
    shell("pytest", *arguments, cwd=root, merged=True, **shell_options)


class FrozenClock(logging.Filter):
    """Demo-only filter: stamp every record with one fixed UTC time so outputs never change."""

    def __init__(self, moment: datetime = datetime(2026, 11, 7, 9, 30, tzinfo=UTC)) -> None:
        super().__init__()
        self.timestamp = moment.timestamp()

    def filter(self, record: logging.LogRecord) -> bool:
        record.created, record.msecs = self.timestamp, 0.0
        return True


def source_of(obj: object) -> str:
    """Source code of a function or class, also for classes defined in a notebook cell."""
    try:
        return textwrap.dedent(inspect.getsource(obj))
    except OSError, TypeError:
        if not isinstance(obj, type):
            raise
    for member in vars(obj).values():
        member = getattr(member, "__func__", None) or getattr(member, "fget", None) or member
        code_object = getattr(inspect.unwrap(member), "__code__", None)
        lines = linecache.getlines(code_object.co_filename) if code_object else []
        if lines:
            start = obj.__firstlineno__ - 1
            while start > 0 and lines[start - 1].lstrip().startswith("@"):
                start -= 1
            return textwrap.dedent("".join(inspect.getblock(lines[start:])))
    raise OSError(f"source of {obj.__name__} not found")


def raised_message(thunk: Callable[[], object]) -> str:
    """Call thunk and return "ErrorName: message" for the exception it raised, or "no error"."""
    try:
        thunk()
    except Exception as error:
        return f"{type(error).__name__}: {error}"
    return "no error"


for tool in ("pytest", "coverage", "pre-commit", "ruff"):
    exit_code, version = run_tool(tool, "--version")
    print(f"{tool}: {version.splitlines()[0] if version else 'not installed'}")
for package in ("pytest_cov", "hypothesis"):
    found = importlib.util.find_spec(package) is not None
    print(f"{package}: {'installed' if found else 'not installed; its cells print a skip message'}")
'''

SHOP_SOURCE = r'''
MONEY_MODULE = """
    \"\"\"The shared Money value type (Lab 2.4, exercise 1; Phase 2 Project, Step 1).\"\"\"

    from __future__ import annotations

    import functools
    from decimal import ROUND_HALF_UP, Decimal

    PAISE = Decimal("0.01")


    class CurrencyMismatchError(ValueError):
        \"\"\"Two Money values in different currencies were combined or compared.\"\"\"


    @functools.total_ordering
    class Money:
        __slots__ = ("_amount", "_currency")

        def __init__(self, amount: Decimal | int | str, currency: str = "INR") -> None:
            if isinstance(amount, float):
                raise TypeError("amount must be Decimal, int or str, not float")
            if not (len(currency) == 3 and currency.isalpha() and currency.isupper()):
                raise ValueError(f"invalid currency code: {currency!r}")
            self._amount = Decimal(amount).quantize(PAISE, rounding=ROUND_HALF_UP)
            self._currency = currency

        @property
        def amount(self) -> Decimal:
            return self._amount

        @property
        def currency(self) -> str:
            return self._currency

        def __repr__(self) -> str:
            return f"Money({str(self._amount)!r}, {self._currency!r})"

        def __str__(self) -> str:
            return f"{self._currency} {self._amount:,.2f}"

        def _same_currency(self, other: Money) -> None:
            if other._currency != self._currency:
                raise CurrencyMismatchError(
                    f"currency mismatch: {self._currency} vs {other._currency}"
                )

        def __eq__(self, other: object) -> bool:
            if not isinstance(other, Money):
                return NotImplemented
            return (self._amount, self._currency) == (other._amount, other._currency)

        def __hash__(self) -> int:
            return hash((self._amount, self._currency))

        def __lt__(self, other: object) -> bool:
            if not isinstance(other, Money):
                return NotImplemented
            self._same_currency(other)
            return self._amount < other._amount

        def __add__(self, other: object) -> Money:
            if not isinstance(other, Money):
                return NotImplemented
            self._same_currency(other)
            return Money(self._amount + other._amount, self._currency)

        def __radd__(self, other: object) -> Money:
            if isinstance(other, int) and not isinstance(other, bool) and other == 0:
                return self  # sum() starts from 0
            return NotImplemented

        def __sub__(self, other: object) -> Money:
            if not isinstance(other, Money):
                return NotImplemented
            self._same_currency(other)
            return Money(self._amount - other._amount, self._currency)

        def __mul__(self, factor: object) -> Money:
            if isinstance(factor, bool) or not isinstance(factor, (int, Decimal)):
                return NotImplemented
            return Money(self._amount * factor, self._currency)

        __rmul__ = __mul__

        def __neg__(self) -> Money:
            return Money(-self._amount, self._currency)

        def __bool__(self) -> bool:
            return bool(self._amount)
"""

BILLING_MODULE = """
    \"\"\"split_bill from Lab 1.3.\"\"\"

    from decimal import ROUND_HALF_UP, Decimal

    PAISE = Decimal("0.01")


    def split_bill(total_amount: str, people_count: int) -> list[Decimal]:
        \"\"\"Split a rupee amount into people_count parts, exact to the paisa.\"\"\"
        if people_count < 1:
            raise ValueError(f"people_count must be at least 1, got {people_count}")
        total_in_paise = int(Decimal(total_amount).quantize(PAISE, rounding=ROUND_HALF_UP) * 100)
        base_share_in_paise, leftover_paise = divmod(total_in_paise, people_count)
        return [
            (Decimal(base_share_in_paise + (1 if index < leftover_paise else 0)) / 100).quantize(
                PAISE
            )
            for index in range(people_count)
        ]
"""


def shop_files(*modules: str) -> dict[str, str]:
    """Files of a small `shop` package with the requested modules ("money", "billing")."""
    sources = {"money": MONEY_MODULE, "billing": BILLING_MODULE}
    return {"shop/__init__.py": "", **{f"shop/{name}.py": sources[name] for name in modules}}


print(f"{sorted(shop_files('money', 'billing'))=}")
'''


def _overview_cells() -> list[NotebookNode]:
    """Unit opener and setup."""
    return [
        md(
            """
            ## Unit 4.3 — Testing, Debugging and Logging

            **Objectives**

            - Choose what to test at which level (unit, integration, end to end) and write
              tests in the Arrange-Act-Assert shape.
            - Write and run pytest tests: discovery, plain `assert`, `pytest.raises`,
              `pytest.approx`, the everyday CLI flags.
            - Share setup with fixtures (scopes, teardown, `conftest.py`, factories, the
              built-in `tmp_path`, `monkeypatch`, `capsys` and `caplog`).
            - Generate cases with `parametrize` and Hypothesis; control runs with markers.
            - Replace collaborators with mocks, stubs and fakes, patch in the right place, and
              control time.
            - Measure line and branch coverage and know what it does not tell you.
            - Debug with `breakpoint()`, pdb, post-mortem and `faulthandler`.
            - Configure logging properly (`dictConfig`, handlers, formatters, filters, JSON) and
              follow the rules for libraries.
            - Gate every commit and pull request with ruff, pre-commit and CI.

            **JS bridge: Jest / Vitest → pytest**

            | Jest / Vitest | pytest / Python | The difference that bites |
            | --- | --- | --- |
            | `test("adds", () => {...})`, `it(...)` | `def test_adds(): ...` in `test_*.py` | Found by **naming convention**; no registration call |
            | `describe("Cart", ...)` | a module, or a `class TestCart:` | Test classes have no `__init__` and no base class |
            | `expect(total).toBe(3)` | `assert total == 3` | Plain `assert`; pytest **rewrites** it to explain failures |
            | `expect(fn).toThrow(/bad/)` | `with pytest.raises(ValueError, match="bad"):` | A context manager, not a callback |
            | `toBeCloseTo(0.3)` | `== pytest.approx(0.3)` | Works on lists and dicts too |
            | `beforeEach` / `afterEach` | fixtures (`yield` for teardown) | Injected **by parameter name** |
            | `test.each([...])` | `@pytest.mark.parametrize` | Each case is a separate test with an id |
            | `test.skip`, `test.failing` | `@pytest.mark.skip`, `@pytest.mark.xfail` | `skipif(condition, reason=...)` too |
            | `jest.fn()`, `vi.fn()` | `unittest.mock.Mock()` | Attributes appear on access; use `autospec` |
            | `jest.mock("./rates")` | `mock.patch("shop.checkout.fetch_rate")` | Patch **where the name is looked up** |
            | `jest.useFakeTimers()` | inject a clock (or `monkeypatch`) | `datetime.now` cannot be patched directly |
            | `--coverage` | `pytest --cov` (pytest-cov) | `--cov-branch` for branch coverage |
            | fast-check | Hypothesis | Same idea: properties + shrinking |
            | `-t "name"` | `-k "name"` | `-k` takes a boolean expression |
            | `console.log` | `logging` (`print` only in scripts) | Configure once at the entry point |
            | `debugger;` statement | `breakpoint()` | Disable with `PYTHONBREAKPOINT=0` |
            | ESLint + Prettier, husky | ruff (lint + format), pre-commit | One tool replaces several |

            **How the tool demos run.** Tests live in files, so each demo writes a tiny project
            to `notebooks/_scratch/unit43/<name>/` with `project(name, files)` and runs the
            **real pytest** (or coverage, pdb, pre-commit, ruff) in a child process with
            `run_pytest(root, *flags)`, printing its output. A fresh interpreter per run means no
            stale imports. Paths are shown as `<scratch>`, `<python>` (the interpreter's
            install folder) or `~`, and durations as `<time>`.
            """
        ),
        code(UNIT_SETUP_SOURCE),
        md(
            """
            **The code under test.** Most demos test a small `shop` package written into each
            scratch project: `shop/money.py` holds the shared `Money` value type from Phase 2
            (Decimal amounts rounded half-up to the paisa, currency checks, `+ - *`, `sum()`
            support, ordering) and `shop/billing.py` holds `split_bill` from Lab 1.3. Lab 4.3
            adds an exchange-rate client and the Phase 2 inventory model.
            `shop_files("money", "billing")` returns the files to write.
            """
        ),
        code(SHOP_SOURCE),
    ]


def _strategy_cells() -> list[NotebookNode]:
    """4.3.1 Testing strategy."""
    return [
        md(
            """
            ### 4.3.1 Testing strategy

            **The test pyramid.** Many fast, isolated tests at the bottom; fewer slower tests
            that wire real parts together; a handful of end-to-end tests at the top. The shape
            is about **cost and feedback**: a unit test runs in microseconds and points at one
            function; an end-to-end failure says "something is broken" after seconds or
            minutes.

            ```mermaid
            flowchart TB
                E2E["End-to-end: a few<br/>real HTTP + DB + browser"] --> INT
                INT["Integration: some<br/>service + real SQLite, API + test client"] --> UNIT
                UNIT["Unit: many<br/>pure functions, one class, collaborators replaced"]
            ```

            <details><summary>ASCII version</summary>

            ```text
                    /\\        end-to-end   (few, slow, broad)
                   /  \\
                  /----\\      integration  (some)
                 /      \\
                /--------\\    unit         (many, fast, precise)
            ```

            </details>

            | Level | What it exercises | Example in this course | Speed | When it fails, you learn |
            | --- | --- | --- | --- | --- |
            | Unit | One function or class; collaborators replaced or trivial | `Money("0.125") == Money("0.13")` | µs | exactly which rule broke |
            | Integration | Several real parts together (service + repository, app + DB) | `InventoryService` with an SQLite repository | ms | the parts disagree (SQL, wiring, serialization) |
            | End-to-end | The deployed system through its real interface | `POST /orders` on a running FastAPI app (Phase 6) | s | the system is broken for users |

            > **Note:** the "testing trophy" (Kent C. Dodds) puts more weight on integration
            > tests. Both agree on the important part: most tests should be fast and
            > deterministic, and each level should test what only it can.
            """
        ),
        md(
            """
            **Arrange-Act-Assert (AAA).** Every test has three parts, in this order, separated
            by a blank line: set up the inputs (*arrange*), do **one** thing (*act*), check the
            outcome (*assert*). A pytest test is just a function, so the kernel can call it
            directly; a passing test returns `None`, a failing one raises `AssertionError`.
            """
        ),
        code(
            r'''
            def apply_coupon(total_in_paise: int, percent: int) -> int:
                """Take percent off a total (integer paise, rounded down in the customer's favour)."""
                return total_in_paise - total_in_paise * percent // 100


            def test_coupon_takes_the_percentage_off_the_total() -> None:
                """AAA: one behaviour, one act, explicit expected values."""
                # Arrange
                total_in_paise, percent = 67_900, 10

                # Act
                payable = apply_coupon(total_in_paise, percent)

                # Assert
                assert payable == 61_110


            print(f"{test_coupon_takes_the_percentage_off_the_total()=}  (None: passed)")
            '''
        ),
        md(
            """
            **What makes a test good** (the same in Jest and pytest):

            | Property | Means | Smell when missing |
            | --- | --- | --- |
            | Fast | milliseconds, so you run it on every save | people stop running the suite |
            | Isolated | no shared state; any order, in parallel | passes alone, fails in the suite |
            | Deterministic | same result every run (seeded, fixed clock, no network) | "flaky" reruns |
            | Behaviour-focused | checks what the caller sees, not private details | refactors break tests |
            | Readable | the name states the rule; the failure says what broke | `test_1`, `test_money_works` |

            The first real run: a project with one module and one test file. Note the header
            (Python, pytest and plugin versions, `rootdir`, the config file), one character per
            test (`.` pass, `F` fail, `E` error, `s` skip, `x` xfail), and the summary line.
            """
        ),
        code(
            r'''
            first_run = project(
                "first_run",
                {
                    **shop_files("billing"),
                    "tests/test_billing.py": """
                        from decimal import Decimal

                        from shop.billing import split_bill


                        def test_even_split():
                            assert split_bill("90", 3) == [Decimal("30.00")] * 3


                        def test_leftover_goes_to_first_people():
                            assert split_bill("100", 3) == [
                                Decimal("33.34"), Decimal("33.33"), Decimal("33.33")
                            ]
                    """,
                },
            )
            show_file(first_run / "pyproject.toml")
            run_pytest(first_run)
            '''
        ),
    ]


def _fundamentals_cells() -> list[NotebookNode]:
    """4.3.2 pytest fundamentals."""
    return [
        md(
            """
            ### 4.3.2 pytest fundamentals

            **Discovery.** pytest collects tests by convention; no registration, no imports of
            a test framework needed for simple tests.

            | Rule | Default | Configure with |
            | --- | --- | --- |
            | Where to look | the `testpaths` folders, else the current folder, recursively | `testpaths = ["tests"]` |
            | Test files | `test_*.py` or `*_test.py` | `python_files` |
            | Test classes | `Test*` classes **without** an `__init__` | `python_classes` |
            | Test functions/methods | `test_*` | `python_functions` |
            | Root folder | the folder of the config file (`pyproject.toml`, `pytest.ini`, …) | `--rootdir` |
            | Import path | `pythonpath = ["."]` puts the project root on `sys.path` | `--import-mode` |

            > **Note:** `python -m pytest` also adds the current folder to `sys.path`; the plain
            > `pytest` command does not. Set `pythonpath` in the config so both behave alike.

            `--collect-only -q` lists what pytest would run, without running it. `helpers.py`,
            the class with an `__init__`, and `check_total` are not collected:
            """
        ),
        code(
            r'''
            discovery = project(
                "discovery",
                {
                    "tests/test_cart.py": """
                        def test_empty_cart_total_is_zero():
                            assert sum([]) == 0


                        def check_total():  # not test_*: ignored
                            assert False


                        class TestDiscounts:
                            def test_member_discount(self):
                                assert round(100 * 0.9) == 90


                        class TestWithInit:  # has __init__: pytest warns and skips it
                            def __init__(self):
                                self.rate = 0.9

                            def test_never_collected(self):
                                assert False
                    """,
                    "tests/orders_test.py": "def test_order_id_is_text():\n    assert str(42) == '42'\n",
                    "tests/helpers.py": "def test_looks_like_a_test():\n    assert False\n",
                },
            )
            run_pytest(discovery, "--collect-only", "-q")
            '''
        ),
        md(
            """
            **Assertion rewriting.** pytest uses plain `assert`, yet a failure shows the values
            involved, a diff for lists, dicts and strings, and the sub-expressions. It does this
            by **rewriting the `assert` statements of test modules** when importing them (an
            import hook, Unit 3.3). Jest needs `expect(...).toEqual(...)` to get the same
            report.
            """
        ),
        code(
            r'''
            rewriting = project(
                "rewriting",
                {
                    "tests/test_reports.py": """
                        def test_order_summary():
                            expected = {"sku": "TEA-500", "quantity": 3, "status": "paid"}
                            actual = {"sku": "TEA-500", "quantity": 2, "status": "paid"}
                            assert actual == expected


                        def test_skus():
                            assert ["TEA-500", "MUG-02", "JAR-750"] == ["TEA-500", "MUG-03", "JAR-750"]


                        def test_function_result():
                            def tax(amount):
                                return amount * 18 // 100

                            assert tax(250) == 46
                    """,
                },
            )
            run_pytest(rewriting, "-q", "--no-header", "--tb=short")
            '''
        ),
        md(
            """
            **Under the hood: the rewritten `assert`.** pytest's import hook calls
            `rewrite_asserts` on the module's AST before compiling it. Running it by hand on a
            one-line test shows what the interpreter actually executes: the comparison is
            stored in temporaries, and on failure pytest formats each value with `saferepr`.
            The `@py_…` names are deliberately invalid identifiers, so they can never clash with
            your own names.
            """
        ),
        code(
            r"""
            from _pytest.assertion.rewrite import rewrite_asserts  # pytest internals: may change

            test_source = "def test_total():\n    total = 1 + 1\n    assert total == 3\n"
            syntax_tree = ast.parse(test_source)
            rewrite_asserts(syntax_tree, test_source.encode())
            rewritten = ast.unparse(syntax_tree)
            print("\n".join(line[:110] for line in rewritten.splitlines()))
            """
        ),
        md(
            """
            > **Warning:** `python -O` strips every `assert` statement. That is fine for tests
            > (pytest never runs with `-O`) but it is why production code must not use `assert`
            > for validation: raise `ValueError` instead.

            **`pytest.raises`** checks that a block raises an exception of a type (or a
            subclass). `match=` is a regular expression searched in `str(error)`, and the
            `ExceptionInfo` object gives you the exception afterwards for more checks. pytest's
            helpers also work outside pytest, so the kernel can try them directly:
            """
        ),
        code(
            r"""
            import pytest

            with pytest.raises(ValueError, match=r"at least 1, got 0") as error_info:
                raise ValueError("people_count must be at least 1, got 0")
            print(f"{error_info.type.__name__=}, {str(error_info.value)=}")

            try:
                with pytest.raises(ValueError):
                    int("42")  # no exception: the check itself fails
            except BaseException as failure:  # pytest's Failed derives from BaseException
                print(f"{type(failure).__name__}: {failure}")
            """
        ),
        md(
            """
            The same checks as a test file. `pytest.raises` also accepts a tuple of types, and
            `ExceptionInfo.group_contains` checks exception groups (Unit 1.14). The failing
            test shows the report when the message does not match:
            """
        ),
        code(
            r'''
            raises_demo = project(
                "raises_demo",
                {
                    **shop_files("money", "billing"),
                    "tests/test_errors.py": """
                        import pytest

                        from shop.billing import split_bill
                        from shop.money import CurrencyMismatchError, Money


                        def test_zero_people_is_rejected():
                            with pytest.raises(ValueError, match="at least 1"):
                                split_bill("100", 0)


                        def test_currency_mismatch_is_a_value_error():
                            with pytest.raises(ValueError) as error_info:
                                Money(1, "INR") + Money(1, "USD")
                            assert error_info.type is CurrencyMismatchError
                            assert "INR vs USD" in str(error_info.value)


                        def test_float_message():
                            with pytest.raises(TypeError, match="no floats allowed"):
                                Money(0.1)
                    """,
                },
            )
            run_pytest(raises_demo, "-q", "--no-header", "--tb=line")
            '''
        ),
        md(
            """
            **`pytest.approx`** compares floats with a tolerance (default: relative `1e-6`, or
            absolute `1e-12` near zero), like Jest's `toBeCloseTo`, and also works element-wise
            for sequences and dict values. Use `rel=` or `abs=` to set the tolerance. For money,
            use `Decimal` and exact comparisons instead.
            """
        ),
        code(
            r"""
            print(f"{0.1 + 0.2 == 0.3=}")
            print(f"{0.1 + 0.2 == pytest.approx(0.3)=}")
            print(f"{[0.1 + 0.2, 0.2 + 0.4] == pytest.approx([0.3, 0.6])=}")
            print(f"{ {'tax': 18.000001} == pytest.approx({'tax': 18.0})=}")
            print(f"{101 == pytest.approx(100, rel=0.05)=}, {101 == pytest.approx(100, abs=0.5)=}")
            print(f"{pytest.approx(0.3)!r}")
            """
        ),
        *predict_cells(
            """
            import pytest

            print(0.1 + 0.2 == pytest.approx(0.3), [0.1 + 0.2] == [0.3], 1e-13 == pytest.approx(0))
            """,
            """
            `True False True`. `approx` applies a tolerance; the plain list comparison uses
            exact `==` on the floats inside (`0.30000000000000004 != 0.3`). Near zero a relative
            tolerance is useless (any percentage of 0 is 0), so `approx` also has an absolute
            tolerance of `1e-12`, which `1e-13` is within.
            """,
            """
            print(0.1 + 0.2 == pytest.approx(0.3), [0.1 + 0.2] == [0.3], 1e-13 == pytest.approx(0))
            """,
        ),
        md(
            """
            **Everyday CLI flags.** One demo project with five tests (one of them failing, one
            that prints) is used for each flag below.

            | Flag | Meaning | Jest / Vitest |
            | --- | --- | --- |
            | `-k "expr"` | run tests whose names match a boolean expression (`and`, `or`, `not`) | `-t` |
            | `-x` | stop at the first failure (`--maxfail=N` for N) | `--bail` |
            | `-v` / `-q` | one line per test / minimal output | `--verbose` |
            | `--lf` | rerun only the tests that failed last time (`--ff`: failed first) | `--onlyFailures` |
            | `-s` | do not capture `print` output (same as `--capture=no`) | (prints always shown) |
            | `--tb=short\\|line\\|no` | traceback style | |
            | `-ra` | summary of everything that did not pass | |
            | `--durations=5` | the five slowest tests | |
            """
        ),
        code(
            r'''
            flags_demo = project(
                "flags_demo",
                {
                    "tests/test_checkout.py": """
                        def test_cart_total():
                            assert 240 * 2 + 199 == 679


                        def test_cart_total_with_coupon():
                            assert 679 - 50 == 629


                        def test_invoice_rounding():
                            assert round(2.675, 2) == 2.68  # fails: 2.675 is stored as 2.67499...


                        def test_shipping_is_free_above_500():
                            print("debug: checking the free-shipping rule")
                            assert 679 > 500


                        def test_invoice_number_format():
                            assert f"INV-{7:05d}" == "INV-00007"
                    """,
                },
            )
            run_pytest(flags_demo, "-q", "--no-header", "--tb=no")
            '''
        ),
        md(
            """
            `-k` selects tests by name with a boolean expression: `coupon or shipping` matches
            two tests, `not total` deselects the two with "total" in their names.
            """
        ),
        code(
            r"""
            run_pytest(flags_demo, "-q", "--no-header", "--tb=no", "-k", "coupon or shipping")
            run_pytest(flags_demo, "-q", "--no-header", "--tb=no", "-k", "not total")
            """
        ),
        md(
            """
            `-x` stops at the first failure (useful with a long suite), and `-v` prints one line
            per test with its **node id** (`file::Class::test[params]`), which you can paste
            back on the command line to run a single test.
            """
        ),
        code(
            r"""
            run_pytest(flags_demo, "-x", "-q", "--no-header", "--tb=no")
            run_pytest(flags_demo, "-v", "--no-header", "--tb=no")
            """
        ),
        md(
            """
            `--lf` ("last failed") reads `.pytest_cache/`, which the previous run wrote, and
            runs only the tests that failed then. In a red-green loop you fix, rerun `--lf`, and
            finally run everything.
            """
        ),
        code(
            r"""
            run_pytest(flags_demo, "--lf", "-q", "--no-header", "--tb=no")
            print(f"{sorted(path.name for path in (flags_demo / '.pytest_cache' / 'v' / 'cache').iterdir())=}")
            """
        ),
        md(
            """
            **Output capture.** pytest captures `print` output and shows it only for failing
            tests, so passing tests stay quiet. `-s` turns capturing off (handy with print
            debugging or `breakpoint()`); `-rP` shows captured output of passing tests in the
            summary instead.
            """
        ),
        code(
            r"""
            run_pytest(flags_demo, "-q", "--no-header", "-k", "shipping")
            run_pytest(flags_demo, "-q", "--no-header", "-k", "shipping", "-s")
            """
        ),
        md(
            """
            **Running pytest from a notebook.** Three options:

            | Option | How | Trade-off |
            | --- | --- | --- |
            | Child process (this course) | `subprocess.run(["pytest", ...])` | Fresh interpreter every run, exactly like CI; tests must live in files |
            | In the kernel | `pytest.main([...])` returns an exit code | Fast, but test modules and the code under test stay in `sys.modules`: **edits are not picked up** |
            | `ipytest` (third party) | `%%ipytest` cell magic runs tests defined in cells | Convenient for teaching; not used here |

            The trap of `pytest.main`: the kernel imports `pricing.py` once. After the file
            changes, a second `pytest.main` still sees the old function, because Python caches
            modules (Unit 3.3). The cell cleans up `sys.modules` and `sys.path` afterwards.
            """
        ),
        code(
            r"""
            in_kernel = project(
                "in_kernel",
                {
                    "pricing.py": "def with_gst(amount):\n    return amount * 118 // 100\n",
                    "tests/test_pricing.py": (
                        "from pricing import with_gst\n\n\ndef test_gst():\n    assert with_gst(100) == 118\n"
                    ),
                },
            )
            path_before, modules_before = list(sys.path), set(sys.modules)
            arguments = [
                str(in_kernel),
                "-q",
                "-p",
                "no:cacheprovider",
                "--capture=sys",
                "--rootdir",
                str(in_kernel),
            ]
            with contextlib.redirect_stdout(io.StringIO()):
                first_exit = pytest.main(arguments)
            (in_kernel / "pricing.py").write_text(
                "def with_gst(amount):\n    return amount * 112 // 100  # bug\n"
            )
            with contextlib.redirect_stdout(io.StringIO()):
                second_exit = pytest.main(arguments)
            print(f"{first_exit!r}, {second_exit!r}  (the bug is invisible: pricing was cached)")
            print(f"{'pricing' in sys.modules=}")
            for name in set(sys.modules) - modules_before:
                if name in ("pricing", "test_pricing") or name.startswith("tests"):
                    del sys.modules[name]
            sys.path[:] = path_before
            print(f"after clean-up: {'pricing' in sys.modules=}")
            """
        ),
        md(
            """
            The same edited project in a child process catches the bug at once, which is why
            every demo in this unit runs pytest that way:
            """
        ),
        code(
            r"""
            run_pytest(in_kernel, "-q", "--no-header", "--tb=line", "-p", "no:cacheprovider")
            """
        ),
    ]


def _fixture_cells() -> list[NotebookNode]:
    """4.3.3 Fixtures."""
    return [
        md(
            """
            ### 4.3.3 Fixtures

            A **fixture** is a function decorated with `@pytest.fixture` that provides a value
            to tests. A test asks for it by **naming it as a parameter**; pytest calls the
            fixture, passes the result in, and (for `yield` fixtures) cleans up afterwards.
            Compared with Jest's `beforeEach`, fixtures are explicit (you see what each test
            uses), composable (fixtures can request other fixtures) and lazy (only the fixtures
            a test asks for run).
            """
        ),
        code(
            r'''
            fixture_basics = project(
                "fixture_basics",
                {
                    **shop_files("money"),
                    "tests/test_basket.py": """
                        import pytest

                        from shop.money import Money


                        @pytest.fixture
                        def basket():
                            return [Money("240"), Money("199"), Money("49.50")]


                        @pytest.fixture
                        def basket_total(basket):  # a fixture using another fixture
                            return sum(basket)


                        def test_total(basket_total):
                            assert basket_total == Money("488.50")


                        def test_each_test_gets_a_fresh_basket(basket):
                            basket.append(Money(1))
                            assert len(basket) == 4
                    """,
                },
            )
            run_pytest(fixture_basics, "-v", "--no-header")
            '''
        ),
        md(
            """
            **Scopes.** By default a fixture runs once per test (`scope="function"`). Wider
            scopes share one instance: `"class"`, `"module"`, `"package"`, `"session"` (the whole
            run). Use wide scopes for expensive, read-only resources (a database engine, a
            parsed catalogue) and keep anything a test mutates function-scoped.
            `--setup-show` prints every SETUP and TEARDOWN with its scope letter (S, M, C, F), so
            you can watch the sharing:
            """
        ),
        code(
            r'''
            scopes = project(
                "scopes",
                {
                    "tests/test_scopes.py": """
                        import pytest


                        @pytest.fixture(scope="session")
                        def catalogue():
                            return {"TEA-500": 240, "MUG-02": 199}


                        @pytest.fixture(scope="module")
                        def price_list(catalogue):
                            return sorted(catalogue.values())


                        @pytest.fixture
                        def cart():
                            return []


                        def test_cheapest(price_list):
                            assert price_list[0] == 199


                        def test_add(cart, catalogue):
                            cart.append(catalogue["TEA-500"])
                            assert cart == [240]


                        def test_cart_starts_empty(cart):
                            assert cart == []
                    """,
                },
            )
            run_pytest(scopes, "--setup-show", "-q", "--no-header")
            '''
        ),
        md(
            """
            **`yield` fixtures: setup and teardown in one place.** Code before `yield` is setup,
            the yielded value goes to the test, code after `yield` is teardown and runs **even
            when the test fails** (like a context manager's `finally`, Unit 1.14). Here an
            in-memory SQLite connection is created, filled, handed over and closed;
            `request.addfinalizer(...)` is the older callback style.
            """
        ),
        code(
            r'''
            teardown = project(
                "teardown",
                {
                    "tests/test_orders_db.py": """
                        import sqlite3

                        import pytest


                        @pytest.fixture
                        def orders_db():
                            connection = sqlite3.connect(":memory:")
                            connection.execute("CREATE TABLE orders (id INTEGER, total INTEGER)")
                            connection.executemany("INSERT INTO orders VALUES (?, ?)", [(1, 679), (2, 240)])
                            print("\\nsetup: database ready")
                            yield connection
                            connection.close()
                            print("teardown: database closed")


                        def test_order_count(orders_db):
                            assert orders_db.execute("SELECT COUNT(*) FROM orders").fetchone() == (2,)


                        def test_failing_test_still_tears_down(orders_db):
                            assert orders_db.execute("SELECT SUM(total) FROM orders").fetchone() == (0,)
                    """,
                },
            )
            run_pytest(teardown, "-q", "--no-header", "-s", "--tb=line")
            '''
        ),
        md(
            """
            **`conftest.py`: sharing fixtures.** Fixtures defined in a `conftest.py` are
            available to every test in that folder and below, **without importing** them.
            Conftests nest: a fixture in `tests/api/conftest.py` overrides one with the same
            name from `tests/conftest.py` for the tests under `tests/api/`. `pytest --fixtures`
            lists every fixture a test could use, with its docstring and where it is defined.
            """
        ),
        code(
            r'''
            conftest_demo = project(
                "conftest_demo",
                {
                    "tests/conftest.py": """
                        import pytest


                        @pytest.fixture
                        def currency():
                            \"\"\"Default currency for tests.\"\"\"
                            return "INR"


                        @pytest.fixture
                        def customer():
                            \"\"\"A sample customer record.\"\"\"
                            return {"name": "Asha", "city": "Pune"}
                    """,
                    "tests/test_shop.py": """
                        def test_default_currency(currency, customer):
                            assert (currency, customer["city"]) == ("INR", "Pune")
                    """,
                    "tests/api/conftest.py": """
                        import pytest


                        @pytest.fixture
                        def currency():
                            \"\"\"The public API reports prices in USD.\"\"\"
                            return "USD"
                    """,
                    "tests/api/test_api.py": """
                        def test_api_currency(currency, customer):
                            assert (currency, customer["name"]) == ("USD", "Asha")
                    """,
                },
            )
            run_pytest(conftest_demo, "-v", "--no-header")
            run_pytest(
                conftest_demo,
                "--fixtures",
                "-q",
                "tests/api",
                keep=r"conftest|currency|customer|INR|USD|sample",
            )
            '''
        ),
        md(
            """
            **`autouse=True`** applies a fixture to every test in its scope without the tests
            asking for it. Use it sparingly, for things every test needs and nobody should
            forget: resetting global state, seeding `random`, blocking the network. Here it
            seeds `random` before each test, so both tests see the same "random" order:
            """
        ),
        code(
            r'''
            autouse_demo = project(
                "autouse_demo",
                {
                    "tests/conftest.py": """
                        import random

                        import pytest


                        @pytest.fixture(autouse=True)
                        def seeded_random():
                            random.seed(42)
                    """,
                    "tests/test_draw.py": """
                        import random


                        def test_lucky_draw():
                            assert random.sample(["Asha", "Ravi", "Meera", "John"], 2) == ["Asha", "John"]


                        def test_same_draw_again():
                            assert random.randint(1, 100) == 82
                    """,
                },
            )
            run_pytest(autouse_demo, "-q", "--no-header")
            '''
        ),
        md(
            """
            Both tests hard-code "random" results and pass on every run: the autouse fixture
            re-seeds `random` before *each* test, so the second test does not depend on how many
            numbers the first one drew. The values are the same on every machine for a given
            Python version (the Mersenne Twister algorithm is fixed; `sample`'s use of it could
            change between versions).

            **Factory fixtures.** When a test needs *several* objects, or needs to choose their
            details, a fixture can return a **function** that builds them. The factory can track
            what it made and clean it up after the test.
            """
        ),
        code(
            r'''
            factory_demo = project(
                "factory_demo",
                {
                    **shop_files("money"),
                    "tests/test_factory.py": """
                        import pytest

                        from shop.money import Money


                        @pytest.fixture
                        def make_order():
                            created = []

                            def build(*prices, customer="Asha"):
                                order = {"id": len(created) + 1, "customer": customer,
                                         "lines": [Money(price) for price in prices]}
                                created.append(order)
                                return order

                            yield build
                            print(f"\\nteardown: {len(created)} orders cleaned up")


                        def test_two_orders(make_order):
                            first = make_order("240", "199")
                            second = make_order("49.50", customer="Ravi")
                            assert (first["id"], second["id"]) == (1, 2)
                            assert sum(first["lines"]) == Money("439")
                    """,
                },
            )
            run_pytest(factory_demo, "-q", "--no-header", "-s")
            '''
        ),
        md(
            """
            **Built-in fixtures.** pytest ships fixtures for the most common needs:

            | Fixture | Gives you | Typical use |
            | --- | --- | --- |
            | `tmp_path` | a fresh `pathlib.Path` folder per test (`tmp_path_factory` for wider scopes) | code that reads or writes files |
            | `monkeypatch` | `setattr`, `setenv`, `delenv`, `setitem`, `chdir`, `syspath_prepend`, all undone after the test | replace a function, set an environment variable |
            | `capsys` | `readouterr()` → `(out, err)` of what the test printed | testing CLI output |
            | `caplog` | `records`, `record_tuples`, `messages`, `text`, `set_level`, `at_level` | asserting on log messages |

            `tmp_path` gives each test its own empty folder under the system temp directory;
            pytest keeps the last three runs for inspection.
            """
        ),
        code(
            r'''
            tmp_path_demo = project(
                "tmp_path_demo",
                {
                    "shop/report.py": """
                        from pathlib import Path


                        def write_report(folder: Path, totals: dict[str, int]) -> Path:
                            path = folder / "report.csv"
                            rows = "".join(f"{sku},{total}\\n" for sku, total in totals.items())
                            path.write_text("sku,total\\n" + rows)
                            return path
                    """,
                    "shop/__init__.py": "",
                    "tests/test_report.py": """
                        from shop.report import write_report


                        def test_write_report(tmp_path):
                            path = write_report(tmp_path, {"TEA-500": 480, "MUG-02": 199})
                            assert path.read_text().splitlines() == ["sku,total", "TEA-500,480", "MUG-02,199"]
                            assert [item.name for item in tmp_path.iterdir()] == ["report.csv"]
                    """,
                },
            )
            run_pytest(tmp_path_demo, "-q", "--no-header")
            '''
        ),
        md(
            """
            `monkeypatch` changes something for one test and **undoes it automatically**:
            environment variables, attributes of modules or objects, dict items, the working
            folder. Here it sets `SHOP_CURRENCY` and replaces the slow `fetch_rate` function with
            a lambda (note the *target*: the module where `price_in` looks the name up, more in
            4.3.5).
            """
        ),
        code(
            r'''
            monkeypatch_demo = project(
                "monkeypatch_demo",
                {
                    "shop/__init__.py": "",
                    "shop/pricing.py": """
                        import os
                        import time


                        def fetch_rate(currency: str) -> float:
                            time.sleep(5)  # pretend this calls a slow web service
                            raise ConnectionError("no network in tests")


                        def price_in(amount_in_inr: float) -> str:
                            currency = os.environ.get("SHOP_CURRENCY", "INR")
                            if currency == "INR":
                                return f"INR {amount_in_inr:.2f}"
                            return f"{currency} {amount_in_inr * fetch_rate(currency):.2f}"
                    """,
                    "tests/test_pricing.py": """
                        import os

                        from shop import pricing


                        def test_default_currency(monkeypatch):
                            monkeypatch.delenv("SHOP_CURRENCY", raising=False)
                            assert pricing.price_in(100) == "INR 100.00"


                        def test_usd_with_fake_rate(monkeypatch):
                            monkeypatch.setenv("SHOP_CURRENCY", "USD")
                            monkeypatch.setattr(pricing, "fetch_rate", lambda currency: 0.012)
                            assert pricing.price_in(100) == "USD 1.20"


                        def test_patches_were_undone():
                            assert "SHOP_CURRENCY" not in os.environ
                            assert pricing.fetch_rate.__name__ == "fetch_rate"
                    """,
                },
            )
            run_pytest(monkeypatch_demo, "-v", "--no-header")
            '''
        ),
        md(
            """
            `capsys` captures what the code under test prints, so a CLI's output can be
            asserted exactly. `readouterr()` returns everything printed since the last call and
            resets the buffer. (`capfd` does the same at the file-descriptor level, for output
            from C extensions and child processes.)
            """
        ),
        code(
            r'''
            capsys_demo = project(
                "capsys_demo",
                {
                    "tests/test_cli_output.py": """
                        import sys


                        def print_receipt(lines):
                            for name, price in lines:
                                print(f"{name:<10}{price:>8.2f}")
                            if not lines:
                                print("empty cart", file=sys.stderr)


                        def test_receipt(capsys):
                            print_receipt([("Tea", 240), ("Mug", 199)])
                            captured = capsys.readouterr()
                            assert captured.out == "Tea         240.00\\nMug         199.00\\n"
                            assert captured.err == ""


                        def test_empty_cart_warns_on_stderr(capsys):
                            print_receipt([])
                            assert capsys.readouterr() == ("", "empty cart\\n")
                    """,
                },
            )
            run_pytest(capsys_demo, "-q", "--no-header")
            '''
        ),
        md(
            """
            `caplog` captures log records (4.3.9) emitted during the test.
            `record_tuples` gives `(logger name, level number, message)` triples, which are
            easy to compare; `caplog.set_level(...)` or `with caplog.at_level(...)` lowers the
            threshold so DEBUG and INFO records are captured too.
            """
        ),
        code(
            r'''
            caplog_demo = project(
                "caplog_demo",
                {
                    "tests/test_logging.py": """
                        import logging

                        logger = logging.getLogger("shop.orders")


                        def cancel_order(order_id, paid):
                            logger.info("cancelling order %s", order_id)
                            if paid:
                                logger.warning("order %s was paid: refund needed", order_id)


                        def test_paid_order_logs_a_warning(caplog):
                            cancel_order(7, paid=True)
                            assert caplog.record_tuples == [
                                ("shop.orders", logging.WARNING, "order 7 was paid: refund needed")
                            ]


                        def test_info_is_captured_when_enabled(caplog):
                            with caplog.at_level(logging.INFO, logger="shop.orders"):
                                cancel_order(8, paid=False)
                            assert caplog.messages == ["cancelling order 8"]
                    """,
                },
            )
            run_pytest(caplog_demo, "-q", "--no-header")
            '''
        ),
        md(
            """
            Why did the first test see only the warning? Its logger has no level, so the root
            logger's default `WARNING` applies and the INFO record is never created (4.3.9).
            `at_level` lowers it for the second test.
            """
        ),
    ]


def _parametrize_cells() -> list[NotebookNode]:
    """4.3.4 Parametrization and markers."""
    return [
        md(
            """
            ### 4.3.4 Parametrization and markers

            **`@pytest.mark.parametrize`** runs one test function once per case, like Jest's
            `test.each`. Each case becomes a separate test with its own id, pass/fail and
            `-k` selection. Give **ids** so failures read well: with `ids=[...]`, with
            `pytest.param(..., id="...")`, or with an `ids=` function. Without them pytest
            builds ids from the values (`0.125-0.13`) or, for objects, from the parameter names
            (`amount0`).
            """
        ),
        code(
            r'''
            parametrize_demo = project(
                "parametrize_demo",
                {
                    **shop_files("money"),
                    "tests/test_money_rounding.py": """
                        from decimal import Decimal

                        import pytest

                        from shop.money import Money


                        @pytest.mark.parametrize(
                            ("raw_amount", "expected"),
                            [("0.125", "0.13"), ("0.124", "0.12"), ("-0.125", "-0.13"), ("7", "7.00")],
                            ids=["half-up", "below-half", "negative", "whole-rupees"],
                        )
                        def test_rounds_half_up_to_paise(raw_amount, expected):
                            assert Money(raw_amount).amount == Decimal(expected)


                        @pytest.mark.parametrize(
                            ("left", "right", "expected"),
                            [
                                pytest.param(Money("240"), Money("199"), Money("439"), id="rupees"),
                                pytest.param(Money("0.10"), Money("0.20"), Money("0.30"), id="paise-exact"),
                                (Money("1"), Money("-1"), Money("0")),
                            ],
                        )
                        def test_addition(left, right, expected):
                            assert left + right == expected
                    """,
                },
            )
            run_pytest(parametrize_demo, "-v", "--no-header")
            '''
        ),
        md(
            """
            Two more forms: an **`ids` function** that turns each value into an id, and
            **stacked** `parametrize` decorators, which run the cartesian product (here 3
            currencies × 2 amounts = 6 tests). `-k` can then pick cases by id.
            """
        ),
        code(
            r'''
            stacked_demo = project(
                "stacked_demo",
                {
                    **shop_files("money"),
                    "tests/test_currencies.py": """
                        import pytest

                        from shop.money import Money


                        @pytest.mark.parametrize("currency", ["INR", "USD", "EUR"])
                        @pytest.mark.parametrize(
                            "amount", ["0.01", "999999.99"], ids=lambda value: f"amt{value}"
                        )
                        def test_round_trip_through_str(amount, currency):
                            assert str(Money(amount, currency)).startswith(currency + " ")
                    """,
                },
            )
            run_pytest(stacked_demo, "-v", "--no-header")
            run_pytest(stacked_demo, "-v", "--no-header", "-k", "USD and amt0.01")
            '''
        ),
        md(
            """
            **Built-in markers** change how a test runs:

            | Marker | Effect | Use for |
            | --- | --- | --- |
            | `@pytest.mark.skip(reason=...)` | never runs; reported as `s` | a test that cannot run yet |
            | `pytest.skip("...")` inside a test | stops it as skipped at run time | conditions known only at run time |
            | `@pytest.mark.skipif(condition, reason=...)` | skips when the condition is true | OS, Python version, missing optional package |
            | `pytest.importorskip("module")` | skips the test or module when an import fails | optional dependencies |
            | `@pytest.mark.xfail(reason=..., strict=True, raises=...)` | expected failure: `x` when it fails, `X` (XPASS) when it passes; `strict=True` turns XPASS into a failure | known bugs with a ticket |

            `-ra` prints the reason for every test that did not simply pass:
            """
        ),
        code(
            r'''
            markers_demo = project(
                "markers_demo",
                {
                    "tests/test_markers.py": """
                        import sys

                        import pytest


                        @pytest.mark.skip(reason="payment sandbox not set up yet")
                        def test_card_payment():
                            ...


                        @pytest.mark.skipif(sys.platform == "win32", reason="POSIX file permissions")
                        def test_report_is_private():
                            assert True


                        @pytest.mark.skipif(sys.version_info < (3, 14), reason="needs uuid7 (3.14+)")
                        def test_order_ids_are_time_ordered():
                            import uuid
                            assert uuid.uuid7().version == 7


                        def test_needs_optional_package():
                            pytest.importorskip("shop_pdf_export", reason="optional PDF plug-in not installed")


                        @pytest.mark.xfail(reason="BUG-142: float rounding", raises=AssertionError)
                        def test_known_bug():
                            assert round(2.675, 2) == 2.68


                        @pytest.mark.xfail(reason="fixed already?", strict=True)
                        def test_fixed_bug():
                            assert round(2.5) == 2
                    """,
                },
            )
            run_pytest(markers_demo, "-ra", "-q", "--no-header")
            '''
        ),
        md(
            """
            The last test passed although it was marked `xfail(strict=True)`, so pytest reports
            it as a failure ("XPASS(strict)"): the bug it documented is gone and the marker
            should be removed. (`round(2.5) == 2` because Python rounds halves to even, Unit
            1.3.)

            **Custom markers** label tests so you can select them with `-m`, like tags.
            Register them in the config (`markers = [...]`) and run with `--strict-markers`, so
            a typo such as `@pytest.mark.solw` is an error instead of a silently ignored label.
            """
        ),
        code(
            r'''
            custom_markers = project(
                "custom_markers",
                {
                    "pyproject.toml": """
                        [tool.pytest.ini_options]
                        pythonpath = ["."]
                        testpaths = ["tests"]
                        addopts = "--strict-markers"
                        markers = [
                            "slow: takes more than a second",
                            "integration: needs a real database",
                        ]
                    """,
                    "tests/test_suite.py": """
                        import pytest


                        def test_fast_rule():
                            assert 1 + 1 == 2


                        @pytest.mark.slow
                        def test_full_catalogue_import():
                            assert sum(range(10_000)) == 49_995_000


                        @pytest.mark.integration
                        @pytest.mark.slow
                        def test_orders_table():
                            assert True
                    """,
                },
            )
            run_pytest(custom_markers, "-m", "not slow", "-q", "--no-header")
            run_pytest(custom_markers, "-m", "integration or not slow", "-v", "--no-header")
            run_pytest(custom_markers, "--markers", keep=r"^@pytest\.mark\.(slow|integration)")
            '''
        ),
        md("With `--strict-markers`, a misspelt marker stops collection with a clear error:"),
        code(
            r"""
            (custom_markers / "tests" / "test_typo.py").write_text(
                "import pytest\n\n\n@pytest.mark.solw\ndef test_typo():\n    assert True\n"
            )
            run_pytest(custom_markers, "-q", "--no-header", keep=r"solw|error|Error")
            """
        ),
    ]


def _double_cells() -> list[NotebookNode]:
    """4.3.5 Test doubles."""
    return [
        md(
            """
            ### 4.3.5 Test doubles

            A **test double** stands in for a real collaborator (an HTTP API, a mailer, the
            clock, a database) so a unit test is fast, deterministic and focused. The names
            come from Gerard Meszaros's *xUnit Test Patterns*:

            | Double | What it is | Checks | Example |
            | --- | --- | --- | --- |
            | Dummy | passed but never used | nothing | `None` for an unused logger argument |
            | Stub | returns canned answers | the **result** of the code under test | `rates.get` always returns `83.12` |
            | Fake | a working, simplified implementation | the result (state) | `InMemoryInventoryRepository` instead of PostgreSQL |
            | Spy | a real or stub object that records calls | calls, after the fact | `Mock(wraps=real_mailer)` |
            | Mock | pre-programmed with expected calls, verified | the **interaction** | "`send` was called once with this address" |

            In Python, `unittest.mock` provides one flexible class (`Mock`) that serves as stub,
            spy or mock depending on how you use it, much like `jest.fn()`. Fakes you write
            yourself. The rows below each get a demo.

            | API | What it does |
            | --- | --- |
            | `Mock()` | any attribute or call returns another `Mock`; records every call |
            | `MagicMock()` | `Mock` plus the magic methods (`len`, iteration, `with`, `[]`) |
            | `AsyncMock()` | calling it returns an awaitable (*New in 3.8*) |
            | `side_effect` | raise an exception, return successive values, or call a function |
            | call assertions | `assert_called_once_with`, `assert_any_call`, `assert_has_calls`, `call_args_list`, `call_count`, `assert_not_called` |
            | `patch(target)` | replace a name **where it is looked up**, then restore it |
            | `autospec` | the double has the real object's signature and attributes |

            #### `Mock`

            Every attribute you touch and every call you make on a `Mock` returns another
            `Mock`, and every call is recorded. `return_value` makes it a stub. The danger:
            a misspelt method name "works" too, so a test can pass while checking nothing.
            """
        ),
        code(
            r"""
            mailer = mock.Mock()
            mailer.send.return_value = "queued"

            result = mailer.send("asha@example.com", subject="Order 7 shipped")
            print(f"{result=}")
            print(f"{mailer.send.call_args=}")
            print(f"{mailer.send.call_count=}, {mailer.method_calls=}")
            print(f"{type(mailer.sned('typo')).__name__=}  (a typo silently returns a Mock)")
            print(raised_message(lambda: mailer.assert_called_once()))
            print(raised_message(lambda: mailer.asert_called_once()))  # misspelt assert*: caught
            """
        ),
        *predict_cells(
            """
            from unittest import mock

            client = mock.Mock()
            print(client.get is client.get, client() is client(), client.get() is client.post())
            """,
            """
            `True True False`. A child attribute is created on first access and then cached, so
            `client.get` is the same object every time. Every call returns the mock's single
            `return_value` (itself a `Mock`, created on the first call), so `client()` is always
            the same object. `client.get()` and `client.post()` are calls on two different
            children, each with its own `return_value`.
            """,
            """
            client = mock.Mock()
            print(client.get is client.get, client() is client(), client.get() is client.post())
            """,
        ),
        md(
            """
            `Mock` protects only against misspelt `assert…` names (`asert`, `assret`,
            `assrt`…), which raise `AttributeError` since Python 3.5; any other typo goes
            unnoticed. `autospec` (below) fixes that properly.

            #### `MagicMock`

            `MagicMock` also configures the **magic methods**, so it can stand in for a
            container, an iterator or a context manager. Set their return values through the
            dunder names.
            """
        ),
        code(
            r"""
            connection = mock.MagicMock()
            connection.__len__.return_value = 3
            connection.__iter__.return_value = iter(["TEA-500", "MUG-02", "JAR-750"])
            connection.__getitem__.side_effect = lambda sku: {"TEA-500": 240}.get(sku, 0)
            connection.__enter__.return_value = connection

            with connection as open_connection:
                print(f"{len(open_connection)=}, {list(open_connection)=}, {open_connection['TEA-500']=}")
            print(f"{connection.__exit__.called=}, {bool(connection)=}")
            print(raised_message(lambda: len(mock.Mock())))
            """
        ),
        md(
            """
            #### `AsyncMock`

            For `async def` collaborators (Phase 5–6: HTTP clients, database drivers), calling
            an `AsyncMock` returns a coroutine, and there are await-specific assertions
            (`assert_awaited_once_with`). `patch` creates an `AsyncMock` automatically when the
            target is an async function. The kernel already runs an event loop, so the cell can
            use `await` at top level.
            """
        ),
        code(
            r'''
            async def notify_customer(client, order_id: int) -> str:
                """Post a notification and return its status."""
                response = await client.post("/notifications", json={"order_id": order_id})
                return response["status"]


            http_client = mock.AsyncMock()
            http_client.post.return_value = {"status": "sent"}
            status = await notify_customer(http_client, 7)
            print(f"{status=}")
            http_client.post.assert_awaited_once_with("/notifications", json={"order_id": 7})
            print(f"{http_client.post.await_count=}, {inspect.iscoroutinefunction(http_client.post)=}")
            '''
        ),
        md(
            """
            #### `side_effect`

            `side_effect` overrides `return_value` and has three forms: an **exception**
            (class or instance) to raise, an **iterable** of results returned one per call
            (exceptions in it are raised), or a **function** called with the same arguments,
            whose result is returned. The iterable form is how you test retry logic.
            """
        ),
        code(
            r"""
            failing = mock.Mock(side_effect=ConnectionError("rates service down"))
            print(raised_message(failing))

            flaky = mock.Mock(side_effect=[TimeoutError("slow"), TimeoutError("slow"), 83.12])
            for attempt in range(1, 4):
                print(f"attempt {attempt}: {raised_message(flaky) if attempt < 3 else flaky()}")
            print(raised_message(flaky))  # the iterable is used up

            lookup = mock.Mock(side_effect=lambda currency: {"USD": 83.12, "EUR": 90.4}[currency])
            print(f"{lookup('EUR')=}, {raised_message(lambda: lookup('JPY'))}")
            """
        ),
        md(
            """
            #### Call assertions

            A mock records every call in `call_args_list` (and every call on it *and its
            children* in `mock_calls`). The assertion helpers compare against `mock.call(...)`
            objects; `mock.ANY` matches anything. `reset_mock()` clears the record between
            phases of a test.
            """
        ),
        code(
            r"""
            audit = mock.Mock()
            audit.log("order created", order_id=7)
            audit.log("payment received", order_id=7, amount=679)
            audit.flush()

            audit.log.assert_called_with("payment received", order_id=7, amount=679)  # the last call
            audit.log.assert_any_call("order created", order_id=7)
            audit.log.assert_has_calls(
                [
                    mock.call("order created", order_id=7),
                    mock.call("payment received", order_id=7, amount=mock.ANY),
                ]
            )
            print(f"{audit.log.call_count=}")
            print(f"{audit.log.call_args_list=}")
            print(f"{audit.mock_calls=}")
            print(raised_message(lambda: audit.log.assert_called_once_with("order created", order_id=7)))
            audit.reset_mock()
            audit.log.assert_not_called()
            print(f"after reset: {audit.log.call_count=}")
            """
        ),
        md(
            r"""
            #### `patch`: replace a name where it is looked up

            `mock.patch("package.module.name")` replaces an attribute for the duration of a
            `with` block, a decorated function or a test, and then restores it. The rule that
            trips everyone up: **patch the name in the module that uses it**, not where it is
            defined. `from shop_rates import fetch_rate` copies the reference into
            `shop_checkout`'s namespace at import time, so patching `shop_rates.fetch_rate`
            afterwards changes a name `shop_checkout` never looks at again.

            The two modules are created in memory for the demo (`types.ModuleType` registered in
            `sys.modules`) and removed afterwards.
            """
        ),
        code(
            r"""
            rates_module = types.ModuleType("shop_rates")
            exec(
                "def fetch_rate(currency):\n    raise ConnectionError('real network call')\n",
                rates_module.__dict__,
            )
            sys.modules["shop_rates"] = rates_module

            checkout_module = types.ModuleType("shop_checkout")
            exec(
                "from shop_rates import fetch_rate\n\n"
                "def total_in(currency, amount_in_inr):\n"
                "    return round(amount_in_inr / fetch_rate(currency), 2)\n",
                checkout_module.__dict__,
            )
            sys.modules["shop_checkout"] = checkout_module

            with mock.patch("shop_rates.fetch_rate", return_value=83.0):
                print(f"patched where defined: {raised_message(lambda: checkout_module.total_in('USD', 830))}")
            with mock.patch("shop_checkout.fetch_rate", return_value=83.0) as fake_rate:
                print(f"patched where used:    {checkout_module.total_in('USD', 830)=}")
                fake_rate.assert_called_once_with("USD")
            print(f"restored: {checkout_module.fetch_rate is rates_module.fetch_rate=}")
            """
        ),
        md(
            """
            `patch` has several forms: a **decorator** (the mock arrives as an extra argument),
            `patch.object(obj, "attribute")` when you hold the object, and
            `patch.dict(mapping, values, clear=...)` for dicts such as `os.environ`. All of
            them restore the original, even when the code raises.
            """
        ),
        code(
            r'''
            @mock.patch("shop_checkout.fetch_rate", return_value=90.0)
            def check_eur_total(fake_rate: mock.Mock) -> float:
                """A decorated function receives the mock as its last argument."""
                return checkout_module.total_in("EUR", 900)


            print(f"{check_eur_total()=}")
            with mock.patch.object(checkout_module, "fetch_rate", side_effect=TimeoutError("slow")):
                print(raised_message(lambda: checkout_module.total_in("USD", 100)))
            with mock.patch.dict(os.environ, {"SHOP_CURRENCY": "USD"}):
                print(f"inside:  {os.environ['SHOP_CURRENCY']=}")
            print(f"outside: {os.environ.get('SHOP_CURRENCY')=}")
            for module_name in ("shop_rates", "shop_checkout"):
                del sys.modules[module_name]
            '''
        ),
        md(
            """
            #### `autospec`

            A plain `Mock` accepts any arguments, so a test keeps passing after the real
            signature changes. `mock.create_autospec(real)` (or `patch(..., autospec=True)`)
            builds a double with the **real signature and attributes**: wrong arguments raise
            `TypeError`, unknown attributes raise `AttributeError`. `spec_set=True` also refuses
            setting attributes the real object does not have. Prefer autospec for every mock of
            your own code.
            """
        ),
        code(
            r'''
            class Mailer:
                """The real collaborator."""

                def send(self, to: str, subject: str, *, body: str = "") -> str:
                    raise ConnectionError("SMTP server not available in tests")


            loose = mock.Mock()
            loose.send("asha@example.com")  # missing subject: accepted
            loose.sendd("typo")  # misspelt method: accepted

            strict = mock.create_autospec(Mailer, instance=True)
            print(raised_message(lambda: strict.send("asha@example.com")))
            print(raised_message(lambda: strict.sendd("typo")))
            strict.send("asha@example.com", "Order shipped")
            strict.send.assert_called_once_with("asha@example.com", subject="Order shipped")
            print("assert_called_once_with matched a positional call with a keyword expectation")
            '''
        ),
        md(
            """
            The last line shows a second benefit: an autospecced mock **binds calls to the real
            signature**, so `send("a", "b")` and `send("a", subject="b")` count as the same
            call.

            #### Fakes vs stubs vs mocks, side by side

            One service, three tests. `PriceAlerter` checks a product's price and e-mails
            subscribers when it drops. The **stub** gives a canned price; the **fake** is a
            working in-memory price store; the **mock** verifies the e-mail interaction.
            Prefer stubs and fakes (they test *outcomes*) and use mocks for interactions that
            *are* the outcome, such as "an e-mail was sent".
            """
        ),
        code(
            r'''
            class InMemoryPriceStore:
                """A fake: a real, simple implementation of the price-store interface."""

                def __init__(self) -> None:
                    self._prices: dict[str, int] = {}

                def save(self, sku: str, price: int) -> None:
                    self._prices[sku] = price

                def latest(self, sku: str) -> int:
                    return self._prices[sku]


            class PriceAlerter:
                def __init__(self, store, mailer) -> None:
                    self.store, self.mailer = store, mailer

                def check(self, sku: str, old_price: int, subscribers: list[str]) -> bool:
                    new_price = self.store.latest(sku)
                    if new_price >= old_price:
                        return False
                    for address in subscribers:
                        self.mailer.send(address, f"{sku} is now {new_price}")
                    return True


            stub_store = mock.Mock(latest=mock.Mock(return_value=199))  # stub
            print(f"stub:  {PriceAlerter(stub_store, mock.Mock()).check('MUG-02', 249, [])=}")

            fake_store = InMemoryPriceStore()  # fake
            fake_store.save("MUG-02", 259)
            print(f"fake:  {PriceAlerter(fake_store, mock.Mock()).check('MUG-02', 249, [])=}")

            mock_mailer = mock.create_autospec(Mailer, instance=True)  # mock
            PriceAlerter(stub_store, mock_mailer).check("MUG-02", 249, ["asha@example.com"])
            mock_mailer.send.assert_called_once_with("asha@example.com", "MUG-02 is now 199")
            print(f"mock:  {mock_mailer.send.call_args=}")
            '''
        ),
        md(
            """
            #### Freezing time

            Code that calls `datetime.now()` or `time.time()` gives a different answer every
            run. The options, best first:

            1. **Inject a clock**: take `clock: Callable[[], datetime] = lambda: datetime.now(UTC)`
               as a parameter (the Phase 2 `InventoryService` does this). Tests pass a lambda.
            2. **Patch the name in your module** with `monkeypatch` or `mock.patch`, for
               example replace `shop.hours.datetime` with a subclass whose `now()` is fixed.
            3. **A library** such as `time-machine` or `freezegun` (third party, not installed
               here) patches the clock functions everywhere.

            You cannot patch `datetime.datetime.now` itself: `datetime` is a built-in
            (immutable) type, so assigning to its attributes raises `TypeError`.
            """
        ),
        code(
            r'''
            def is_happy_hour(clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> bool:
                """Happy hour is 16:00-18:00 IST, which is 10:30-12:30 UTC."""
                now = clock()
                return (10, 30) <= (now.hour, now.minute) < (12, 30)


            print(f"{is_happy_hour(lambda: datetime(2026, 11, 7, 11, 0, tzinfo=UTC))=}")
            print(f"{is_happy_hour(lambda: datetime(2026, 11, 7, 13, 0, tzinfo=UTC))=}")
            print(raised_message(lambda: setattr(datetime, "now", lambda tz=None: None)))
            '''
        ),
        md(
            """
            Option 2 in a test file: the module does `from datetime import datetime`, so the
            test patches **`shop.hours.datetime`** (where the name is looked up) with a
            subclass that overrides the `now` classmethod.
            """
        ),
        code(
            r'''
            frozen_time = project(
                "frozen_time",
                {
                    "shop/__init__.py": "",
                    "shop/hours.py": """
                        from datetime import UTC, datetime


                        def greeting() -> str:
                            hour = datetime.now(UTC).hour
                            return "Good morning" if hour < 12 else "Good afternoon"
                    """,
                    "tests/test_hours.py": """
                        from datetime import UTC, datetime

                        from shop import hours


                        class MorningClock(datetime):
                            @classmethod
                            def now(cls, tz=None):
                                return datetime(2026, 11, 7, 9, 30, tzinfo=tz or UTC)


                        def test_morning_greeting(monkeypatch):
                            monkeypatch.setattr(hours, "datetime", MorningClock)
                            assert hours.greeting() == "Good morning"
                    """,
                },
            )
            run_pytest(frozen_time, "-q", "--no-header")
            '''
        ),
    ]


def _coverage_cells() -> list[NotebookNode]:
    """4.3.6 Coverage."""
    return [
        md(
            """
            ### 4.3.6 Coverage

            **Coverage** measures which code your tests executed. `pytest-cov` runs
            `coverage.py` around pytest: `--cov=shop` selects what to measure,
            `--cov-report=term-missing` lists the line numbers never run.

            | Kind | Counts | Misses |
            | --- | --- | --- |
            | **Line** (statement) coverage | each line executed at least once | an `if` with no `else` whose condition was never false |
            | **Branch** coverage (`--cov-branch`) | each possible jump taken (both outcomes of every `if`, loop entered and skipped) | fewer things: it is the stricter measure |

            One test for a member discount executes every line, so line coverage says 100%.
            The non-member path (the `if` being false) never ran, and branch coverage reports
            it as the partial branch `2->4` (line 2 never jumped straight to line 4):
            """
        ),
        code(
            r'''
            if importlib.util.find_spec("pytest_cov") is None:
                print("SKIP: pytest-cov is not installed (uv add --dev pytest-cov)")
            else:
                coverage_demo = project(
                    "coverage_demo",
                    {
                        "shop/__init__.py": "",
                        "shop/discounts.py": """
                            def member_price(total_in_paise: int, is_member: bool) -> int:
                                if is_member:
                                    total_in_paise = total_in_paise * 90 // 100
                                return total_in_paise
                        """,
                        "tests/test_discounts.py": """
                            from shop.discounts import member_price


                            def test_member_gets_ten_percent_off():
                                assert member_price(10_000, is_member=True) == 9_000
                        """,
                    },
                )
                run_pytest(coverage_demo, "-q", "--no-header", "--cov=shop", "--cov-report=term-missing")
                run_pytest(
                    coverage_demo,
                    "-q",
                    "--no-header",
                    "--cov=shop",
                    "--cov-branch",
                    "--cov-report=term-missing",
                )
            '''
        ),
        md(
            """
            **Thresholds.** `--cov-fail-under=90` (or `fail_under` in the config) makes the run
            fail when total coverage drops below the number, which is how CI enforces it. Keep
            the settings in `pyproject.toml` so every developer and CI measure the same way:
            `[tool.coverage.run]` (`branch`, `source`) and `[tool.coverage.report]`
            (`fail_under`, `show_missing`, `exclude_also` for lines that should never count,
            such as `if TYPE_CHECKING:`). A `# pragma: no cover` comment excludes one line or
            block.
            """
        ),
        code(
            r'''
            if importlib.util.find_spec("pytest_cov") is not None:
                (coverage_demo / "pyproject.toml").write_text(
                    textwrap.dedent("""
                    [tool.pytest.ini_options]
                    pythonpath = ["."]
                    testpaths = ["tests"]
                    addopts = "--cov=shop --cov-report=term-missing"

                    [tool.coverage.run]
                    branch = true

                    [tool.coverage.report]
                    fail_under = 90
                    exclude_also = ["if TYPE_CHECKING:", "raise NotImplementedError"]
                """)
                )
                run_pytest(coverage_demo, "-q", "--no-header")  # the test passes, the run fails
            '''
        ),
        md(
            """
            **The limits of coverage.** Coverage tells you what was **executed**, not what was
            **checked**. A test without a meaningful assertion reaches 100% while the code is
            wrong. It also cannot see code that *should* exist (an unhandled case), and one
            input per branch says nothing about boundaries. Use coverage to find untested
            code, not as proof of quality; a very high target tends to produce tests like the
            one below. **Mutation testing** (tools such as `mutmut` or `cosmic-ray`) asks the
            better question, "would a test fail if this line were wrong?", by planting small
            bugs; Lab 4.3 checks your tests that way.
            """
        ),
        code(
            r'''
            if importlib.util.find_spec("pytest_cov") is not None:
                useless = project(
                    "useless_coverage",
                    {
                        "shop/__init__.py": "",
                        "shop/gst.py": """
                            def with_gst(amount_in_paise: int) -> int:
                                return amount_in_paise * 112 // 100  # bug: GST is 18%
                        """,
                        "tests/test_gst.py": """
                            from shop.gst import with_gst


                            def test_with_gst_runs():
                                with_gst(10_000)  # executes every line, checks nothing
                        """,
                    },
                )
                run_pytest(useless, "-q", "--no-header", "--cov=shop", "--cov-branch", "--cov-report=term")
            '''
        ),
        md(
            """
            **Under the hood: how coverage sees lines.** Since Python 3.12 the interpreter
            offers `sys.monitoring` (PEP 669): a tool registers for events such as `LINE` on
            chosen code objects and pays nothing elsewhere. coverage.py uses it on 3.14+ (the
            `SysMonitor` core); older versions used `sys.settrace`. A ten-line coverage tool
            for one function:
            """
        ),
        code(
            r"""
            def shipping_fee(total_in_paise: int, express: bool) -> int:
                if express:
                    return 9_900
                if total_in_paise >= 50_000:
                    return 0
                return 4_900


            monitoring = sys.monitoring
            TOOL = monitoring.COVERAGE_ID
            executed_lines: set[int] = set()
            monitoring.use_tool_id(TOOL, "mini-coverage")
            monitoring.register_callback(
                TOOL, monitoring.events.LINE, lambda code, line: executed_lines.add(line)
            )
            monitoring.set_local_events(TOOL, shipping_fee.__code__, monitoring.events.LINE)
            shipping_fee(60_000, express=False)
            monitoring.set_local_events(TOOL, shipping_fee.__code__, 0)
            monitoring.free_tool_id(TOOL)

            first_line = shipping_fee.__code__.co_firstlineno
            body_lines = range(first_line + 1, first_line + 6)
            print(f"executed body lines: {sorted(line - first_line for line in executed_lines)}")
            print(
                f"never executed:      "
                f"{[line - first_line for line in body_lines if line not in executed_lines]}"
            )
            """
        ),
        md("coverage.py reports which measurement core it uses with `--debug=sys`:"),
        code(
            r"""
            if importlib.util.find_spec("pytest_cov") is not None:
                shell(
                    "coverage",
                    "run",
                    "--debug=sys",
                    "-m",
                    "pytest",
                    "-q",
                    "-p",
                    "no:cacheprovider",
                    cwd=useless,
                    keep=r"^\s+(core|coverage_version|CTracer):",
                )
            """
        ),
    ]


def _hypothesis_cells() -> list[NotebookNode]:
    """4.3.7 Property-based testing."""
    return [
        md(
            """
            ### 4.3.7 Property-based testing

            An example-based test checks the cases you thought of. A **property-based** test
            states a rule that must hold for *every* input ("the shares always add up to the
            total") and lets a library generate hundreds of inputs, including the nasty ones
            (empty lists, zero, huge numbers, odd Unicode). **Hypothesis** is the Python
            library (fast-check is the JavaScript equivalent). Two ideas make it work:

            1. **Strategies** describe how to generate values: `st.integers(min_value=1)`,
               `st.lists(st.text())`, and combinators to build your own types.
            2. **Shrinking**: when a property fails, Hypothesis simplifies the failing input
               step by step and reports the **smallest** example that still fails.

            | Strategy | Generates |
            | --- | --- |
            | `st.integers(min_value, max_value)`, `st.floats(allow_nan=False)`, `st.decimals(places=2)` | numbers |
            | `st.text(alphabet, min_size, max_size)`, `st.from_regex(r"[A-Z]{3}-\\d{3}", fullmatch=True)` | strings |
            | `st.booleans()`, `st.none()`, `st.just(x)`, `st.sampled_from([...])` | fixed choices |
            | `st.lists(s, min_size, max_size, unique)`, `st.tuples(a, b)`, `st.dictionaries(k, v)` | collections |
            | `st.datetimes(timezones=st.timezones())`, `st.dates()` | dates and times |
            | `st.builds(Cls, field=...)`, `st.from_type(Cls)` | your classes |
            | `s.map(f)`, `s.filter(pred)`, `st.one_of(a, b)`, `@st.composite` | combinators |

            A `@given` test is an ordinary function, so the kernel can call it. With
            `derandomize=True` the "random" inputs are the same on every run, which keeps this
            notebook's output stable. Note how Hypothesis starts with the simplest values:
            """
        ),
        code(
            r"""
            if importlib.util.find_spec("hypothesis") is None:
                print("SKIP: hypothesis is not installed (uv add --dev hypothesis)")
            else:
                from hypothesis import example, find, given, settings
                from hypothesis import strategies as st

                generated: list[list[int]] = []

                @settings(derandomize=True, max_examples=8, database=None)
                @given(st.lists(st.integers(min_value=-5, max_value=5), max_size=4))
                def record_examples(values: list[int]) -> None:
                    generated.append(values)

                record_examples()
                print(*generated, sep="\n")
            """
        ),
        md(
            """
            **Building strategies for your own data.** `@st.composite` receives a `draw`
            function and can make later choices depend on earlier ones; `.map` transforms
            values; `st.builds` calls a constructor with generated arguments. Here: order lines
            with valid SKUs, positive quantities and prices in paise.
            """
        ),
        code(
            r"""
            if importlib.util.find_spec("hypothesis") is not None:
                skus = st.from_regex(r"[A-Z]{3}-[0-9]{3}", fullmatch=True)

                @st.composite
                def order_lines(draw: st.DrawFn) -> tuple[str, int, Decimal]:
                    sku = draw(skus)
                    quantity = draw(st.integers(min_value=1, max_value=10))
                    price = draw(
                        st.integers(min_value=1, max_value=500_000).map(lambda paise: Decimal(paise) / 100)
                    )
                    return sku, quantity, price

                drawn_lines: list[tuple[str, int, Decimal]] = []

                @settings(derandomize=True, max_examples=5, database=None)
                @given(order_lines())
                def record_lines(line: tuple[str, int, Decimal]) -> None:
                    drawn_lines.append(line)

                record_lines()
                print(*drawn_lines, sep="\n")
            """
        ),
        md(
            """
            **Properties of `split_bill`**, run with pytest. A `conftest.py` registers a
            Hypothesis *profile* (deterministic, no example database) so the demo is
            reproducible; in a real project you would keep the database, which replays past
            failures first. Each `@given` test runs 100 generated examples by default;
            `--hypothesis-show-statistics` reports what happened.
            """
        ),
        code(
            r'''
            HYPOTHESIS_CONFTEST = """
                from hypothesis import settings

                settings.register_profile("course", derandomize=True, database=None, deadline=None)
                settings.load_profile("course")
            """
            SPLIT_BILL_PROPERTIES = """
                from decimal import Decimal

                from hypothesis import given
                from hypothesis import strategies as st

                from shop.billing import split_bill

                amounts = st.decimals(min_value=0, max_value=100_000, places=2).map(str)
                people = st.integers(min_value=1, max_value=50)


                @given(amounts, people)
                def test_shares_add_up_to_the_total(total_amount, people_count):
                    assert sum(split_bill(total_amount, people_count)) == Decimal(total_amount)


                @given(amounts, people)
                def test_shares_differ_by_at_most_one_paisa(total_amount, people_count):
                    shares = split_bill(total_amount, people_count)
                    assert len(shares) == people_count
                    assert max(shares) - min(shares) <= Decimal("0.01")
            """
            if importlib.util.find_spec("hypothesis") is not None:
                properties = project(
                    "properties",
                    {
                        **shop_files("billing"),
                        "tests/conftest.py": HYPOTHESIS_CONFTEST,
                        "tests/test_split_bill_properties.py": SPLIT_BILL_PROPERTIES,
                    },
                )
                run_pytest(
                    properties,
                    "-q",
                    "--no-header",
                    "--hypothesis-show-statistics",
                    keep=r"passed|test_|examples|Stopped",
                )
            '''
        ),
        md(
            """
            **Shrinking in action.** A plausible-looking `split_bill` that divides with floats
            and rounds each share. Hypothesis finds totals where the rounded shares no longer
            add up, then shrinks the failing input to a minimal one: the smallest total and
            number of people that still break the rule. That example is your new regression
            test (pin it with `@example(...)`).
            """
        ),
        code(
            r'''
            FLOAT_SPLIT_BILL = """
                from decimal import Decimal


                def split_bill(total_amount: str, people_count: int) -> list[Decimal]:
                    share = round(float(total_amount) / people_count, 2)
                    return [Decimal(str(share))] * people_count
            """
            if importlib.util.find_spec("hypothesis") is not None:
                write_files(properties, {"shop/billing.py": FLOAT_SPLIT_BILL})
                run_pytest(
                    properties,
                    "-q",
                    "--no-header",
                    "--tb=short",
                    keep=r"Falsifying|total_amount=|people_count=|^E  |passed|failed",
                )
            '''
        ),
        md(
            """
            `find(strategy, condition)` exposes shrinking directly: it searches for any value
            that satisfies the condition, then shrinks it. The first list found with a sum
            over 100 might be long and messy; the reported one is minimal. `assume(...)`
            discards inputs inside a test, and `@example(...)` always runs a specific case in
            addition to the generated ones.
            """
        ),
        code(
            r"""
            if importlib.util.find_spec("hypothesis") is not None:
                quiet = settings(derandomize=True, database=None)
                print(f"{find(st.lists(st.integers()), lambda values: sum(values) > 100, settings=quiet)=}")
                print(f"{find(st.text(), lambda text: len(text.encode()) > len(text), settings=quiet)=}")
                print(f"{find(st.integers(), lambda number: number * number > 1_000, settings=quiet)=}")

                @settings(derandomize=True, database=None, max_examples=50)
                @example(total_amount="0.01", people_count=3)  # always tried first
                @given(st.decimals(min_value=0, max_value=1_000, places=2).map(str), st.integers(1, 9))
                def property_shares_are_never_negative(total_amount: str, people_count: int) -> None:
                    total_in_paise = int(Decimal(total_amount) * 100)
                    base, leftover = divmod(total_in_paise, people_count)
                    assert base >= 0 and 0 <= leftover < people_count

                property_shares_are_never_negative()
                print("property held for the pinned example and 50 generated ones")
            """
        ),
    ]


def _debugging_cells() -> list[NotebookNode]:
    """4.3.8 Debugging."""
    return [
        md(
            """
            ### 4.3.8 Debugging

            **`breakpoint()`** (Python 3.7+) is Python's `debugger;` statement: it calls
            `sys.breakpointhook()`, which by default starts **pdb**, the debugger in the
            standard library, at that line. The environment variable `PYTHONBREAKPOINT`
            chooses what happens instead:

            | `PYTHONBREAKPOINT` | `breakpoint()` does |
            | --- | --- |
            | unset or empty | `pdb.set_trace()` |
            | `0` | nothing (leave stray breakpoints in CI without hanging it) |
            | `module.function` | imports and calls it, e.g. `ipdb.set_trace`, `pudb.set_trace`, `debugpy.breakpoint` |

            pdb is interactive, and this notebook runs unattended, so the demos start pdb in a
            child process and **feed it commands on standard input**. pdb does not echo
            input, so `pdb_session` prints each command after its `(Pdb)` prompt, as you
            would see it in a terminal.
            """
        ),
        code(
            r'''
            def pdb_session(
                *command: str, commands: list[str], cwd: Path, env: dict[str, str] | None = None
            ) -> None:
                """Run command (which starts pdb) with commands on stdin; print the transcript."""
                completed = subprocess.run(
                    [sys.executable if command[0] == "python" else str(VENV_BIN / command[0]), *command[1:]],
                    cwd=cwd,
                    env={**(env or tool_env()), "PYTHONUNBUFFERED": "1"},
                    input="\n".join(commands) + "\n",
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=120,
                )
                pieces = tidy(completed.stdout).split("(Pdb) ")
                transcript = [pieces[0].rstrip()] if pieces[0].strip() else []
                for index, piece in enumerate(pieces[1:]):
                    transcript.append(f"(Pdb) {commands[index] if index < len(commands) else '<end of input>'}")
                    if piece.strip():
                        transcript.append(piece.rstrip())
                print(f"[{tidy(str(cwd))}]$ {shlex.join(command)}   # stdin: {commands}")
                print(textwrap.indent("\n".join(transcript), "  ", lambda line: True))


            debug_demo = write_files(
                fresh_dir("debug_demo"),
                {
                    "cart.py": """
                    def line_total(price, quantity):
                        subtotal = price * quantity
                        breakpoint()
                        return subtotal


                    def cart_total(lines):
                        total = 0
                        for price, quantity in lines:
                            total += line_total(price, quantity)
                        return total


                    print(cart_total([(240, 2), (12, "3")]))
                """,
                },
            )
            print("cart.py written; line 14 passes one quantity as a string")
            '''
        ),
        md(
            """
            The script stops at `breakpoint()` on every call of `line_total`. The session
            prints the arguments, shows the call stack (`w`) and the whole function (`ll`),
            steps one line (`n`), continues (`c`) to the second call, and finds the bug: the
            quantity `"3"` is a string, so `12 * "3"` repeated the string instead of
            multiplying, and adding that string to the running total fails.
            """
        ),
        code(
            r"""
            pdb_session(
                "python",
                "cart.py",
                cwd=debug_demo,
                commands=[
                    "p price, quantity",
                    "w",
                    "ll",
                    "n",
                    "p subtotal",
                    "c",
                    "p price, quantity",
                    "p subtotal",
                    "c",
                ],
            )
            """
        ),
        md(
            """
            `PYTHONBREAKPOINT=0` disables every `breakpoint()` call, and
            `PYTHONBREAKPOINT=module.function` replaces pdb with any callable. Here a small
            hook prints the caller's local variables instead of stopping, a poor man's
            logpoint:
            """
        ),
        code(
            r'''
            write_files(
                debug_demo,
                {
                    "show_locals.py": """
                    import sys


                    def report():
                        caller = sys._getframe(1)
                        print(f"breakpoint in {caller.f_code.co_name}: {caller.f_locals}")
                """,
                },
            )
            shell("python", "cart.py", cwd=debug_demo, env=tool_env(PYTHONBREAKPOINT="0"), keep=r"^\d|Error")
            shell(
                "python",
                "cart.py",
                cwd=debug_demo,
                env=tool_env(PYTHONBREAKPOINT="show_locals.report", PYTHONPATH=str(debug_demo)),
                keep=r"breakpoint in|^\d|Error",
            )
            '''
        ),
        md(
            """
            In the kernel the same mechanism is visible: `breakpoint()` simply calls
            `sys.breakpointhook()`. The default hook (always kept in `sys.__breakpointhook__`)
            reads `PYTHONBREAKPOINT` and normally calls `pdb.set_trace()`; tools can install
            their own, and in Jupyter ipykernel may do so for its debugger, so the first value
            below depends on the frontend. Swapping the hook temporarily makes `breakpoint()`
            harmless here:
            """
        ),
        code(
            r"""
            print(f"{sys.breakpointhook is sys.__breakpointhook__=}, {sys.__breakpointhook__!r}")
            calls: list[str] = []
            sys.breakpointhook = lambda *args, **kwargs: calls.append(sys._getframe(1).f_code.co_name)
            try:

                def checkout() -> None:
                    breakpoint()

                checkout()
            finally:
                sys.breakpointhook = sys.__breakpointhook__
            print(f"{calls=}")
            """
        ),
        md(
            """
            **pdb commands.** Short forms in brackets; anything that is not a command is
            evaluated as Python in the current frame (prefix with `!` when it clashes with a
            command name, e.g. `!n = 3`).

            | Command | Does | Command | Does |
            | --- | --- | --- | --- |
            | `n`(ext) | run the current line, stepping **over** calls | `s`(tep) | step **into** a call |
            | `c`(ontinue) | run to the next breakpoint | `r`(eturn) | run until the current function returns |
            | `unt`(il) `N` | run until line N (or past a loop) | `j`(ump) `N` | set the next line to run |
            | `l`(ist), `ll` | source around the line / whole function | `w`(here), `bt` | the call stack |
            | `u`(p), `d`(own) | move between stack frames | `p expr`, `pp expr` | print / pretty-print |
            | `b`(reak) `file:line`, `b func` | set a breakpoint (`b` alone lists them) | `tbreak` | one-shot breakpoint |
            | `b N, condition` / `condition N expr` | conditional breakpoint | `cl`(ear) `N` | delete breakpoint N |
            | `display expr` | print expr whenever it changes | `interact` | a Python REPL in the current frame |
            | `a`(rgs) | the current function's arguments | `q`(uit) | stop the program |

            A session that never calls `breakpoint()`: `python -m pdb script.py` stops before
            the first line, then sets a **conditional breakpoint** inside the loop, uses
            `display`, steps **into** a call with `s`, returns with `r`, and moves **up** the
            stack to inspect the caller.
            """
        ),
        code(
            r'''
            write_files(
                debug_demo,
                {
                    "invoice.py": """
                    def gst(amount_in_paise):
                        return amount_in_paise * 18 // 100


                    def invoice_total(lines):
                        total = 0
                        for sku, amount in lines:
                            total += amount + gst(amount)
                        return total


                    print(invoice_total([("TEA-500", 24000), ("MUG-02", 19900), ("JAR-750", 35000)]))
                """,
                },
            )
            pdb_session(
                "python",
                "-m",
                "pdb",
                "invoice.py",
                cwd=debug_demo,
                commands=[
                    "b 8, sku == 'MUG-02'",
                    "c",
                    "display total",
                    "a",
                    "s",
                    "ll",
                    "r",
                    "u",
                    "p sku, amount",
                    "d",
                    "n",
                    "cl 1",
                    "c",
                ],
            )
            '''
        ),
        md(
            """
            **Post-mortem debugging** opens the debugger at the frame where an exception was
            raised, *after* the crash, with all local variables intact:

            | Where | How |
            | --- | --- |
            | Any script | `python -m pdb script.py`: after an uncaught exception pdb enters post-mortem mode |
            | REPL / your own code | `pdb.pm()` (uses `sys.last_exc`, set by the REPL after an error) or `pdb.post_mortem(exception)` |
            | IPython / Jupyter | `%debug` right after the failing cell (`%pdb on` starts it automatically) |
            | pytest | `pytest --pdb` (post-mortem on each failure), `pytest --trace` (stop at the start of each test) |

            `python -m pdb` on a crashing script: `c` runs it, the exception puts pdb in
            post-mortem mode at the failing line, and the values explain the crash.
            """
        ),
        code(
            r'''
            write_files(
                debug_demo,
                {
                    "average.py": """
                    def average_order_value(totals):
                        return sum(totals) / len(totals)


                    daily_totals = {"Mon": [679, 240], "Tue": []}
                    for day, totals in daily_totals.items():
                        print(day, average_order_value(totals))
                """,
                },
            )
            pdb_session(
                "python",
                "-m",
                "pdb",
                "average.py",
                cwd=debug_demo,
                commands=["c", "p totals", "u", "p day", "q"],
            )
            '''
        ),
        md(
            """
            `pdb.pm()` in your own code: the REPL stores the last uncaught exception in
            `sys.last_exc` (*New in 3.12*; `sys.last_traceback` before), and `pm()` opens it. A
            script can do the same in its top-level error handler:
            """
        ),
        code(
            r'''
            write_files(
                debug_demo,
                {
                    "report_job.py": """
                    import pdb
                    import sys


                    def parse_quantity(text):
                        return int(text)


                    try:
                        quantities = [parse_quantity(text) for text in ["3", "2", "two"]]
                    except ValueError as error:
                        sys.last_exc = error  # what the interactive REPL does for you
                        pdb.pm()
                """,
                },
            )
            pdb_session("python", "report_job.py", cwd=debug_demo, commands=["p text", "w", "q"])
            '''
        ),
        md(
            """
            **`%debug` in IPython and Jupyter.** Run it in the cell after an exception to open
            `ipdb` (pdb with IPython's colours and completion) at the failing frame. It needs an
            interactive frontend, so this notebook shows it in an IPython child process with
            the input piped in (the prompt is `ipdb>` instead of `(Pdb)`; IPython's profile
            and history go to a scratch folder):
            """
        ),
        code(
            r"""
            ipython_input = (
                "def average(values):\n    return sum(values) / len(values)\n\n"
                "average([])\n%debug\np values\nq\nexit\n"
            )
            print(f"piped into ipython: {ipython_input.splitlines()}")
            exit_code, ipython_output = run_tool(
                "ipython",
                "--simple-prompt",
                "--no-banner",
                "--colors=NoColor",
                input_text=ipython_input,
                cwd=debug_demo,
            )
            for line in ipython_output.splitlines():
                if re.search(r"ZeroDivisionError|ipdb>|---->|^> ", line):
                    print(f"  {line}")
            print("(after each ipdb> prompt comes the output of the next piped command: `p values` printed [])")
            """
        ),
        md(
            """
            **`pytest --pdb`** drops into post-mortem pdb on the first failing test, with the
            test's locals available (pytest turns output capture off while pdb runs).
            `pytest --trace` instead stops at the first line of every selected test.
            """
        ),
        code(
            r'''
            pdb_test_project = project(
                "pdb_test",
                {
                    **shop_files("billing"),
                    "tests/test_bill.py": """
                        from decimal import Decimal

                        from shop.billing import split_bill


                        def test_three_way_split():
                            shares = split_bill("10", 3)
                            assert shares == [Decimal("3.33")] * 3
                    """,
                },
            )
            pdb_session(
                "pytest",
                "-q",
                "--no-header",
                "-p",
                "no:cacheprovider",
                "--pdb",
                cwd=pdb_test_project,
                commands=["p shares", "p sum(shares)", "c"],
            )
            '''
        ),
        md(
            """
            **IDE debuggers** do the same with a GUI: click in the gutter to set breakpoints,
            hover to inspect variables, and use the call-stack and watch panels. VS Code's
            Python extension and PyCharm both offer **conditional breakpoints**, **logpoints**
            (print a message without stopping or editing code), "just my code" stepping, and
            attaching to a running process. VS Code (and Jupyter's own debugger) use
            **debugpy**, which ipykernel installs; a minimal `.vscode/launch.json` entry:

            ```json
            {
              "name": "Debug tests",
              "type": "debugpy",
              "request": "launch",
              "module": "pytest",
              "args": ["-x", "tests/test_bill.py"],
              "justMyCode": true
            }
            ```

            *New in 3.14:* `python -m pdb -p PID` attaches pdb to an already running Python
            process (PEP 768), no restart needed.
            """
        ),
        code(
            r"""
            for module_name in ("debugpy",):
                if importlib.util.find_spec(module_name) is None:
                    print(f"{module_name}: not installed")
                else:
                    print(
                        f"{module_name}: {importlib.metadata.version(module_name)} (installed with ipykernel)"
                    )
            """
        ),
        md(
            """
            **`faulthandler`** prints the Python traceback when the interpreter itself crashes
            (a segmentation fault in a C extension, an abort) or hangs, cases where a normal
            traceback never appears. Enable it with `python -X faulthandler`,
            `PYTHONFAULTHANDLER=1` or `faulthandler.enable()`; pytest enables it automatically.
            The child process below reads memory address 0 through `ctypes` to crash on
            purpose. *New in 3.14:* the report also includes the C stack, which is long and
            machine-specific, so only the Python part is printed.
            """
        ),
        code(
            r"""
            write_files(
                debug_demo,
                {
                    "crash.py": (
                        "import ctypes\n\n\ndef read_config():\n"
                        "    return ctypes.string_at(0)\n\n\nread_config()\n"
                    )
                },
            )
            completed = subprocess.run(
                [sys.executable, "-X", "faulthandler", "crash.py"],
                cwd=debug_demo,
                capture_output=True,
                text=True,
                env=tool_env(),
            )
            python_part = tidy(completed.stderr).split("Current thread's C stack")[0]
            print(re.sub(r"0x[0-9a-f]+", "0x...", python_part).rstrip())
            print(
                f"exit code: {completed.returncode} "
                f"(negative = killed by signal {-completed.returncode}, SIGSEGV)"
            )
            """
        ),
        md(
            """
            For **hangs**, `faulthandler.dump_traceback_later(seconds, exit=True)` dumps every
            thread's stack if the program is still running after the timeout, showing *where*
            it is stuck (here, a loop waiting for a lock that never frees):
            """
        ),
        code(
            r'''
            write_files(
                debug_demo,
                {
                    "hang.py": """
                    import faulthandler
                    import time


                    def wait_for_payment_lock():
                        while True:
                            time.sleep(0.1)


                    faulthandler.dump_traceback_later(1, exit=True)
                    wait_for_payment_lock()
                """,
                },
            )
            completed = subprocess.run(
                [sys.executable, "hang.py"],
                cwd=debug_demo,
                capture_output=True,
                text=True,
                env=tool_env(),
                timeout=30,
            )
            print(re.sub(r"0x[0-9a-f]+", "0x...", tidy(completed.stderr)).rstrip())
            print(f"exit code: {completed.returncode}")
            '''
        ),
    ]


def _logging_cells() -> list[NotebookNode]:
    """4.3.9 Logging architecture."""
    return [
        md(
            """
            ### 4.3.9 Logging architecture

            Unit 1.14 used `logging` for error reporting; this section covers how it is put
            together and configured. Four kinds of object cooperate:

            | Object | Role | Created with |
            | --- | --- | --- |
            | **Logger** | the API your code calls (`logger.info(...)`); named, arranged in a dotted hierarchy | `logging.getLogger(__name__)` |
            | **Handler** | sends records somewhere: console, file, queue, network | `StreamHandler()`, `RotatingFileHandler(...)` |
            | **Formatter** | turns a record into text (or JSON) | `Formatter("%(levelname)s %(message)s")` |
            | **Filter** | drops or enriches records; attach to a logger or a handler | `Filter` subclass or any callable |

            ```mermaid
            flowchart LR
                CALL["logger.info(...)"] --> LVL{"logger level<br/>enabled?"}
                LVL -- no --> DROP["dropped<br/>(cheap)"]
                LVL -- yes --> REC["LogRecord"] --> LF["logger filters"] --> H1["each handler:<br/>level, filters, formatter"]
                H1 --> OUT["stream / file / queue"]
                REC --> PROP{"propagate?"}
                PROP -- yes --> PARENT["parent logger's handlers<br/>... up to root"]
            ```

            <details><summary>ASCII version</summary>

            ```text
            logger.info() -> level check -> LogRecord -> logger filters -> handlers (level, filters, formatter) -> output
                                                       \\-> propagate -> parent's handlers -> ... -> root's handlers
            ```

            </details>

            **The logger hierarchy.** Logger names are dotted paths, normally the module's
            `__name__`, so `shop.orders.api` is a child of `shop.orders`, which is a child of
            `shop`, whose parent is the **root** logger. `getLogger` returns the same object for
            the same name. The helper below resets the demo loggers so cells can be rerun.
            """
        ),
        code(
            r'''
            def reset_loggers(*names: str) -> None:
                """Remove handlers and filters and restore defaults for the given loggers."""
                for name in names:
                    logger = logging.getLogger(name)
                    for handler in logger.handlers[:]:
                        logger.removeHandler(handler)
                        handler.close()
                    logger.filters.clear()
                    logger.setLevel(logging.NOTSET)
                    logger.propagate, logger.disabled = True, False


            DEMO_LOGGERS = ("shop", "shop.orders", "shop.orders.api", "shop.payments", "shop.audit")
            reset_loggers(*DEMO_LOGGERS)
            api_logger = logging.getLogger("shop.orders.api")
            chain, node = [], api_logger
            while node is not None:
                chain.append(node.name)
                node = node.parent
            print(f"{' -> '.join(chain)}")
            print(f"{logging.getLogger('shop.orders.api') is api_logger=}")
            print(f"{logging.getLogger().name=}, {logging.getLevelName(logging.getLogger().level)=}")
            '''
        ),
        md(
            """
            **Under the hood: a `LogRecord`.** Every enabled call creates a `LogRecord` whose
            attributes are what formatters can show (`%(name)s`, `%(lineno)d`, …). `vars()`
            lists them; `extra={...}` adds your own keys as attributes. The message is stored
            unformatted (`msg` + `args`) and only merged by `getMessage()` when a handler needs
            it.
            """
        ),
        code(
            r"""
            record = api_logger.makeRecord(
                "shop.orders.api",
                logging.WARNING,
                "orders.py",
                42,
                "order %s is %d days late",
                (7, 3),
                None,
                func="check_delays",
                extra={"order_id": 7},
            )
            stable_keys = [
                "name",
                "levelname",
                "levelno",
                "pathname",
                "lineno",
                "funcName",
                "msg",
                "args",
                "order_id",
            ]
            print({key: vars(record)[key] for key in stable_keys})
            print(f"{record.getMessage()=}")
            print(f"{sorted(set(vars(record)) - set(stable_keys))=}")
            """
        ),
        md(
            """
            **Levels.** Each level is a number; a record passes when its level is at least the
            threshold. There are **two thresholds**: the logger's (checked first, before a
            record even exists) and each handler's. A logger with level `NOTSET` (0) uses its
            nearest ancestor's level, its *effective level*; the root logger defaults to
            `WARNING`.

            | Level | Number | Use for |
            | --- | --- | --- |
            | `DEBUG` | 10 | details for diagnosing problems |
            | `INFO` | 20 | confirmation that things work ("order 7 shipped") |
            | `WARNING` | 30 | something unexpected, the program carries on (default threshold) |
            | `ERROR` | 40 | an operation failed |
            | `CRITICAL` | 50 | the program may not be able to continue |
            """
        ),
        code(
            r"""
            reset_loggers(*DEMO_LOGGERS)
            shop_logger = logging.getLogger("shop")
            console = logging.StreamHandler(sys.stdout)
            console.setFormatter(logging.Formatter("%(levelname)-8s %(name)s: %(message)s"))
            console.setLevel(logging.INFO)  # handler threshold
            shop_logger.addHandler(console)
            shop_logger.setLevel(logging.DEBUG)  # logger threshold
            shop_logger.propagate = False

            orders_logger = logging.getLogger("shop.orders")
            print(
                f"{orders_logger.level=} (NOTSET), {logging.getLevelName(orders_logger.getEffectiveLevel())=}"
            )
            orders_logger.debug("cart recalculated")  # passes the logger, blocked by the handler
            orders_logger.info("order %s placed", 7)
            orders_logger.warning("order %s has no delivery slot", 7)
            print(f"{orders_logger.isEnabledFor(logging.DEBUG)=}")
            """
        ),
        *predict_cells(
            """
            # a fresh script, logging never configured
            import logging

            logger = logging.getLogger("shop.orders")
            logger.info("order 7 placed")
            logger.warning("order 7 has no delivery slot")
            logger.error("order %s failed", 8)
            """,
            """
            Only two lines, on **stderr**, with no level or logger name:
            `order 7 has no delivery slot` and `order 8 failed`. Nothing configured the root
            logger, so its default level `WARNING` drops the INFO record, and records that
            find no handler go to `logging.lastResort`, a stderr handler with level WARNING and
            the bare `%(message)s` format. `basicConfig()` (or `dictConfig`) replaces this.
            """,
            """
            script = (
                "import logging\\n"
                "logger = logging.getLogger('shop.orders')\\n"
                "logger.info('order 7 placed')\\n"
                "logger.warning('order 7 has no delivery slot')\\n"
                "logger.error('order %s failed', 8)\\n"
            )
            completed = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
            print(f"{completed.stdout=}")
            print(f"{completed.stderr=}")
            """,
        ),
        md(
            """
            **Handlers.** The standard library has handlers for most destinations
            (`logging.handlers`): `StreamHandler` (console), `FileHandler`,
            `RotatingFileHandler` (by size), `TimedRotatingFileHandler` (by time),
            `WatchedFileHandler` (works with external logrotate), `QueueHandler`, `SysLogHandler`,
            `SMTPHandler`, `HTTPHandler`, `MemoryHandler`. Three of them in detail.

            **`StreamHandler`** writes to a stream, `sys.stderr` by default. Console logs
            usually go to stderr so they do not mix with a program's real output on stdout;
            this notebook passes `sys.stdout` so the output appears inline.
            """
        ),
        code(
            r"""
            reset_loggers(*DEMO_LOGGERS)
            stream_target = io.StringIO()
            to_stderr_like = logging.StreamHandler(stream_target)
            to_stderr_like.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
            payments_logger = logging.getLogger("shop.payments")
            payments_logger.addHandler(to_stderr_like)
            payments_logger.propagate = False
            payments_logger.error("card declined for order %s", 7)
            print(f"{logging.StreamHandler().stream is sys.stderr=}")
            print(f"captured: {stream_target.getvalue()!r}")
            """
        ),
        md(
            """
            **`RotatingFileHandler`** starts a new file when the current one would exceed
            `maxBytes`, keeping `backupCount` old files (`shop.log.1` is the newest backup).
            Without rotation, a long-running service fills the disk. The demo uses a tiny limit
            to force rotation.
            """
        ),
        code(
            r"""
            reset_loggers(*DEMO_LOGGERS)
            log_folder = fresh_dir("rotating_logs")
            rotating = logging.handlers.RotatingFileHandler(
                log_folder / "shop.log", maxBytes=120, backupCount=2, encoding="utf-8"
            )
            rotating.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
            audit_logger = logging.getLogger("shop.audit")
            audit_logger.addHandler(rotating)
            audit_logger.setLevel(logging.INFO)
            audit_logger.propagate = False
            for order_id in range(1, 9):
                audit_logger.info("order %s shipped to warehouse PNQ1", order_id)
            reset_loggers("shop.audit")
            for path in sorted(log_folder.iterdir()):
                print(f"{path.name:<11} {path.read_text().splitlines()}")
            """
        ),
        md(
            """
            **`QueueHandler` + `QueueListener`.** Writing to a file or the network inside a
            request handler makes the request wait for slow I/O. A `QueueHandler` only puts the
            record on a queue (fast); a `QueueListener` thread takes records off the queue and
            passes them to the real handlers. This is the recommended setup for web servers and
            for asyncio code. Since 3.12, `dictConfig` can build the pair for you
            (`"class": "logging.handlers.QueueHandler"` with a `"handlers"` list).
            """
        ),
        code(
            r"""
            reset_loggers(*DEMO_LOGGERS)
            log_queue: queue.Queue[logging.LogRecord] = queue.Queue()
            slow_console = logging.StreamHandler(sys.stdout)
            slow_console.setFormatter(logging.Formatter("[%(threadName)s] %(levelname)s %(message)s"))
            listener = logging.handlers.QueueListener(log_queue, slow_console)

            orders_logger = logging.getLogger("shop.orders")
            orders_logger.addHandler(logging.handlers.QueueHandler(log_queue))
            orders_logger.setLevel(logging.INFO)
            orders_logger.propagate = False

            listener.start()
            orders_logger.info("order 7 placed")  # returns immediately; the listener writes
            orders_logger.warning("order 8 payment pending")
            listener.stop()  # flushes the queue and joins the thread
            print(f"{log_queue.empty()=}")
            """
        ),
        md(
            """
            **Formatters.** A format string picks record attributes. `%`-style is the default;
            `style="{"` allows `{levelname:<8}`. `datefmt` formats `%(asctime)s` with
            `time.strftime` codes, and `converter = time.gmtime` makes timestamps UTC instead of
            the machine's local time (do this on servers). Every timestamp in this section comes
            from the `FrozenClock` filter defined in the unit setup, which stamps each record
            with 2026-11-07 09:30:00 UTC so the output never changes.

            | Attribute | Example |
            | --- | --- |
            | `%(asctime)s` | `2026-11-07T09:30:00Z` (with `datefmt`) |
            | `%(levelname)s` / `%(levelno)d` | `INFO` / `20` |
            | `%(name)s` | `shop.orders` |
            | `%(message)s` | the merged message |
            | `%(module)s`, `%(funcName)s`, `%(lineno)d` | where the call happened |
            | `%(process)d`, `%(thread)d`, `%(threadName)s`, `%(taskName)s` (3.12) | concurrency context |
            """
        ),
        code(
            r"""
            reset_loggers(*DEMO_LOGGERS)
            timestamped = logging.StreamHandler(sys.stdout)
            utc_formatter = logging.Formatter(
                "%(asctime)s %(levelname)-7s %(name)s %(funcName)s:%(lineno)d %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%SZ",
            )
            utc_formatter.converter = time.gmtime
            timestamped.setFormatter(utc_formatter)
            timestamped.addFilter(FrozenClock())

            brace_handler = logging.StreamHandler(sys.stdout)
            brace_handler.setFormatter(logging.Formatter("{levelname:<7} | {name:>12} | {message}", style="{"))

            orders_logger = logging.getLogger("shop.orders")
            orders_logger.handlers[:] = [timestamped, brace_handler]
            orders_logger.propagate = False


            def ship_order(order_id: int) -> None:
                orders_logger.warning("order %s shipped late", order_id)


            ship_order(7)
            """
        ),
        md(
            """
            **Filters** decide per record whether it passes, and may **add attributes** to it.
            A filter is a `logging.Filter` subclass or any callable taking a record; on a
            logger it applies to records created by that logger, on a handler to everything the
            handler receives. Two typical filters: one adds the current request id (from a
            `contextvars.ContextVar`, which is how web apps attach request context), the other
            drops noisy health-check messages.
            """
        ),
        code(
            r"""
            import contextvars

            request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


            class RequestIdFilter(logging.Filter):
                def filter(self, record: logging.LogRecord) -> bool:
                    record.request_id = request_id.get()
                    return True


            def drop_health_checks(record: logging.LogRecord) -> bool:
                return "/health" not in record.getMessage()


            reset_loggers(*DEMO_LOGGERS)
            request_handler = logging.StreamHandler(sys.stdout)
            request_handler.setFormatter(logging.Formatter("[%(request_id)s] %(levelname)s %(message)s"))
            request_handler.addFilter(RequestIdFilter())
            request_handler.addFilter(drop_health_checks)
            api_logger = logging.getLogger("shop.orders.api")
            api_logger.addHandler(request_handler)
            api_logger.setLevel(logging.INFO)
            api_logger.propagate = False

            api_logger.info("GET /health 200")
            token = request_id.set("req-7f3a")
            api_logger.info("POST /orders 201")
            request_id.reset(token)
            api_logger.info("GET /products 200")
            """
        ),
        md(
            """
            **Propagation.** After a logger's own handlers run, the record is passed to the
            parent's handlers, and so on up to the root (the logger levels of ancestors are
            *not* checked again). That is why you normally attach handlers **only to the root**
            (or one top-level application logger) and let module loggers propagate. Attaching a
            handler to both a child and an ancestor prints every record twice;
            `propagate = False` stops the climb.
            """
        ),
        code(
            r"""
            reset_loggers(*DEMO_LOGGERS)
            for logger_name in ("shop", "shop.orders"):
                handler = logging.StreamHandler(sys.stdout)
                handler.setFormatter(logging.Formatter(f"via {logger_name!r:<14} %(name)s: %(message)s"))
                logging.getLogger(logger_name).addHandler(handler)
            logging.getLogger("shop").propagate = False  # keep the demo away from the root logger
            logging.getLogger("shop").setLevel(logging.INFO)

            logging.getLogger("shop.orders").info("order 7 placed (printed twice)")
            logging.getLogger("shop.orders").propagate = False
            logging.getLogger("shop.orders").info("order 8 placed (printed once)")
            logging.getLogger("shop.payments").info("payment captured (no own handler: the parent prints it)")
            """
        ),
        md(
            """
            **`dictConfig`**: configure everything from one dictionary, once, at the
            application's entry point (`main()`, the ASGI app factory), never at import time.
            The dict can come from a TOML, YAML or JSON file. Keys: `version: 1` (required),
            `formatters`, `filters`, `handlers` (each names its formatter, filters and level),
            `loggers`, `root`. `"()"` gives a factory (your own class) instead of a built-in
            one; `"ext://sys.stdout"` refers to an object by import path.
            """
        ),
        code(
            r"""
            class UtcFormatter(logging.Formatter):
                converter = time.gmtime  # timestamps in UTC, whatever the server's time zone


            reset_loggers(*DEMO_LOGGERS)
            LOGGING_CONFIG = {
                "version": 1,
                "disable_existing_loggers": False,
                "formatters": {
                    "console": {
                        "()": UtcFormatter,
                        "fmt": "%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                        "datefmt": "%H:%M:%S",
                    },
                },
                "filters": {
                    "frozen_clock": {"()": FrozenClock},  # demo only: stable timestamps
                    "request_id": {"()": RequestIdFilter},
                },
                "handlers": {
                    "console": {
                        "class": "logging.StreamHandler",
                        "stream": "ext://sys.stdout",
                        "formatter": "console",
                        "filters": ["frozen_clock", "request_id"],
                        "level": "INFO",
                    },
                },
                "loggers": {
                    "shop": {"handlers": ["console"], "level": "DEBUG", "propagate": False},
                    "shop.payments": {"level": "WARNING"},
                },
            }
            logging.config.dictConfig(LOGGING_CONFIG)
            logging.getLogger("shop.orders").info("order 7 placed")
            logging.getLogger("shop.payments").info("payment authorised (below WARNING: dropped)")
            logging.getLogger("shop.payments").warning("payment retry 2/3")
            console_handler = logging.getHandlerByName("console")  # New in 3.12
            print(
                f"{type(console_handler).__name__}, {console_handler.name=}, "
                f"{logging.getLevelName(console_handler.level)=}"
            )
            """
        ),
        md(
            """
            > **Warning:** `disable_existing_loggers` defaults to **`True`**: every logger that
            > already exists when `dictConfig` runs, and is not named in the config, is
            > silently disabled. Modules create their loggers at import time, so importing your
            > code *before* configuring logging and forgetting this flag loses their messages.
            > A child process shows it:
            """
        ),
        code(
            r'''
            write_files(
                fresh_dir("disable_existing"),
                {
                    "app.py": """
                    import logging
                    import logging.config

                    inventory_logger = logging.getLogger("shop.inventory")  # created at import time

                    for disable in (True, False):
                        logging.config.dictConfig({
                            "version": 1,
                            "disable_existing_loggers": disable,
                            "handlers": {
                                "out": {"class": "logging.StreamHandler", "stream": "ext://sys.stdout"}
                            },
                            "root": {"handlers": ["out"], "level": "INFO"},
                        })
                        print(f"disable_existing_loggers={disable}: logging...")
                        inventory_logger.warning("stock for TEA-500 is low")
                """,
                },
            )
            shell("python", "app.py", cwd=UNIT43_DIR / "disable_existing")
            '''
        ),
        md(
            """
            **Rules for libraries.** A library (anything other people import) must not
            configure logging: no `basicConfig`, no handlers on the root, no levels. It creates
            module loggers and, by convention, adds a `NullHandler` to its top-level logger.
            The **application** decides where logs go.

            Why `NullHandler`: when a record finds no handler anywhere in the hierarchy,
            `logging` falls back to `logging.lastResort`, which prints WARNING and above to
            stderr. A `NullHandler` counts as a handler, so the library stays silent until the
            application configures logging, and then its records propagate to the
            application's handlers as usual.
            """
        ),
        code(
            r'''
            write_files(
                fresh_dir("library_rules"),
                {
                    "rupee_tools/__init__.py": """
                    import logging

                    logger = logging.getLogger(__name__)


                    def parse_amount(text):
                        if "," in text:
                            logger.warning("ignoring thousands separators in %r", text)
                        return int(text.replace(",", ""))
                """,
                    "rupee_tools_quiet/__init__.py": """
                    import logging

                    logger = logging.getLogger(__name__)
                    logger.addHandler(logging.NullHandler())  # the library convention


                    def parse_amount(text):
                        if "," in text:
                            logger.warning("ignoring thousands separators in %r", text)
                        return int(text.replace(",", ""))
                """,
                    "app.py": """
                    import logging
                    import sys

                    import rupee_tools
                    import rupee_tools_quiet

                    print("app has not configured logging:")
                    rupee_tools.parse_amount("1,200")        # lastResort prints to stderr
                    rupee_tools_quiet.parse_amount("1,200")  # silent
                    logging.basicConfig(stream=sys.stdout, format="  app handler: %(name)s %(message)s")
                    print("app configured logging:")
                    rupee_tools_quiet.parse_amount("2,400")  # now reaches the app's handler
                """,
                },
            )
            shell("python", "app.py", cwd=UNIT43_DIR / "library_rules", merged=True)
            '''
        ),
        md(
            """
            **`logger.exception(...)`** logs at ERROR level **with the current traceback**
            appended; call it only inside an `except` block. For other levels pass
            `exc_info=True` (`logger.warning("...", exc_info=True)`), and `stack_info=True` adds
            the current call stack even without an exception. Never `print(error)` in a
            handler: the traceback is the most useful part. (Run in a child process so the
            traceback shows stable file paths.)
            """
        ),
        code(
            r'''
            write_files(
                fresh_dir("exception_logging"),
                {
                    "worker.py": """
                    import logging
                    import sys

                    logging.basicConfig(
                        stream=sys.stdout, level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
                    )
                    logger = logging.getLogger("shop.worker")


                    def charge(order_id, amount):
                        return amount / 0  # payment gateway bug


                    for order_id in (7, 8):
                        try:
                            charge(order_id, 679)
                        except ZeroDivisionError:
                            logger.exception("charging order %s failed", order_id)
                            break
                """,
                },
            )
            shell("python", "worker.py", cwd=UNIT43_DIR / "exception_logging")
            '''
        ),
        md(
            """
            **Lazy `%s` formatting.** Pass arguments separately, `logger.debug("total %s",
            total)`, instead of an f-string. The message is only built if a handler will
            actually emit the record, so disabled DEBUG calls cost almost nothing, and log
            aggregators can group records by their constant template. With an f-string, the
            formatting (and every `__str__`/`__repr__` call in it) happens before `logging`
            even checks the level. For genuinely expensive data, guard with
            `logger.isEnabledFor(logging.DEBUG)`. (ruff's `G004` rule flags f-strings in
            logging calls.)
            """
        ),
        code(
            r'''
            class ExpensiveReport:
                """Counts how often it is rendered."""

                renders = 0

                def __str__(self) -> str:
                    ExpensiveReport.renders += 1
                    return "<1 MB of stock data>"


            reset_loggers(*DEMO_LOGGERS)
            lazy_logger = logging.getLogger("shop.orders")
            lazy_logger.setLevel(logging.INFO)  # DEBUG is disabled
            lazy_logger.addHandler(logging.NullHandler())
            report = ExpensiveReport()

            for _ in range(1_000):
                lazy_logger.debug("stock report: %s", report)
            print(f"lazy %s style: {ExpensiveReport.renders} renders")
            for _ in range(1_000):
                lazy_logger.debug(f"stock report: {report}")  # noqa: G004 (the anti-pattern)
            print(f"f-string:      {ExpensiveReport.renders} renders")
            '''
        ),
        md(
            """
            **`LoggerAdapter`** wraps a logger and adds the same context to every record, for
            example the order being processed, without repeating `extra=` on each call.
            Override `process()` for custom behaviour. *New in 3.13:* `merge_extra=True` merges
            a call's own `extra=` with the adapter's instead of discarding it.
            """
        ),
        code(
            r"""
            reset_loggers(*DEMO_LOGGERS)
            context_handler = logging.StreamHandler(sys.stdout)
            context_handler.setFormatter(logging.Formatter("order=%(order_id)s %(levelname)s %(message)s"))
            orders_logger = logging.getLogger("shop.orders")
            orders_logger.addHandler(context_handler)
            orders_logger.setLevel(logging.INFO)
            orders_logger.propagate = False

            order_log = logging.LoggerAdapter(orders_logger, {"order_id": 7})
            order_log.info("payment captured")
            order_log.warning("courier not assigned")

            if sys.version_info >= (3, 13):
                context_handler.setFormatter(logging.Formatter("order=%(order_id)s step=%(step)s %(message)s"))
                merged = logging.LoggerAdapter(orders_logger, {"order_id": 8}, merge_extra=True)
                merged.info("packed", extra={"step": "warehouse"})
            """
        ),
        md(
            """
            **JSON logs.** In production, logs are read by machines (Loki, Elasticsearch,
            CloudWatch), so each record is written as one JSON object per line with
            consistent keys, and context goes into fields rather than the message text. A
            formatter only has to return a string, so a JSON formatter is a few lines; libraries
            such as `python-json-logger` and `structlog` (Phase 6) add more. Lab 4.3 builds a
            complete one with `dictConfig`.
            """
        ),
        code(
            r'''
            class MinimalJsonFormatter(logging.Formatter):
                """One JSON object per record: time, level, logger, message and selected extras."""

                EXTRA_KEYS = ("order_id", "request_id")

                def format(self, record: logging.LogRecord) -> str:
                    payload = {
                        "time": datetime.fromtimestamp(record.created, UTC).isoformat(),
                        "level": record.levelname,
                        "logger": record.name,
                        "message": record.getMessage(),
                    }
                    payload |= {key: getattr(record, key) for key in self.EXTRA_KEYS if hasattr(record, key)}
                    return json.dumps(payload)


            reset_loggers(*DEMO_LOGGERS)
            json_handler = logging.StreamHandler(sys.stdout)
            json_handler.setFormatter(MinimalJsonFormatter())
            json_handler.addFilter(FrozenClock())
            orders_logger = logging.getLogger("shop.orders")
            orders_logger.addHandler(json_handler)
            orders_logger.propagate = False
            orders_logger.warning("order %s shipped late", 7, extra={"order_id": 7})
            reset_loggers(*DEMO_LOGGERS)
            '''
        ),
    ]


def _quality_gate_cells() -> list[NotebookNode]:
    """4.3.10 Quality gates."""
    return [
        md(
            """
            ### 4.3.10 Quality gates

            A **quality gate** is an automatic check that code must pass before it is merged:
            locally before each commit (pre-commit), and again on every push and pull request
            (CI). The usual Python gate: **ruff** (lint + format), a **type checker** (Unit 4.2),
            and **pytest with a coverage threshold**.

            **ruff** is a linter and formatter in one binary (written in Rust), replacing
            flake8, isort, pyupgrade, black and dozens of plugins. Rules are grouped by prefix;
            this course enables `E, W, F, I, UP, B`.

            | Prefix | Origin | Catches |
            | --- | --- | --- |
            | `E`, `W` | pycodestyle | style errors and warnings (whitespace, line length) |
            | `F` | Pyflakes | unused imports and variables, undefined names, real bugs |
            | `I` | isort | import order |
            | `UP` | pyupgrade | outdated syntax for your `target-version` |
            | `B` | flake8-bugbear | likely bugs: mutable defaults, `except:` without type, loop-variable closures |
            | `SIM`, `RET`, `PL` | flake8-simplify, flake8-return, Pylint | simplifications, return style, many checks |
            | `S` | flake8-bandit | security smells: `shell=True`, `pickle`, hard-coded passwords |
            | `G`, `LOG` | flake8-logging-format, flake8-logging | f-strings in logging calls, misuse of `logging` |
            | `RUF` | ruff's own | ambiguous Unicode characters, unused `noqa`, … |

            A file with typical problems, checked with the course rules plus `S` and `G`:
            """
        ),
        code(
            r'''
            lint_demo = write_files(
                fresh_dir("lint_demo"),
                {
                    "pyproject.toml": """
                    [tool.ruff]
                    line-length = 100
                    target-version = "py315"

                    [tool.ruff.lint]
                    select = ["E", "W", "F", "I", "UP", "B", "S", "G"]
                """,
                    "orders.py": """
                    import sys, os
                    import logging
                    import subprocess
                    from typing import List, Optional

                    logger = logging.getLogger(__name__)


                    def add_line(sku: str, lines: List[str] = []) -> Optional[List[str]]:
                        lines.append(sku)
                        logger.info(f"added {sku}")
                        return lines


                    def archive(name: str) -> None:
                        try:
                            subprocess.run(f"tar czf {name}.tgz orders/", shell=True)
                        except:
                            pass
                """,
                },
            )
            shell("ruff", "check", "--output-format=concise", ".", cwd=lint_demo)
            '''
        ),
        md(
            """
            `ruff rule CODE` explains any rule. `--fix` applies the safe automatic fixes
            (import sorting, unused imports, modern syntax); `--statistics` summarizes what is
            left. Bugs such as the mutable default (`B006`) and `shell=True` (`S602`) still need
            a human.
            """
        ),
        code(
            r"""
            shell("ruff", "rule", "B006", cwd=lint_demo, max_lines=12)
            shell("ruff", "check", "--fix", "--statistics", ".", cwd=lint_demo)
            """
        ),
        md(
            """
            `ruff format` is the formatter (Black-compatible): it rewrites layout, never
            behaviour. `--diff` shows what it would change, `--check` only reports (for CI).
            """
        ),
        code(
            r"""
            write_files(
                lint_demo,
                {
                    "cart.py": (
                        "def total( prices ):\n    return sum( [ p*1.18 for p in prices ] )\n"
                        "TAX_RATES={'GST':18,'cess':1}\n"
                    )
                },
            )
            shell("ruff", "format", "--diff", "cart.py", cwd=lint_demo)
            shell("ruff", "format", "--check", ".", cwd=lint_demo)
            """
        ),
        md(
            """
            **pre-commit** runs checks on the files you are committing, from a git hook, and
            blocks the commit if one fails (husky + lint-staged in the JavaScript world). Hooks
            are listed in `.pre-commit-config.yaml`. Normally each hook comes from a git
            repository pinned to a tag, which pre-commit downloads into its cache once:

            ```yaml
            repos:
              - repo: https://github.com/astral-sh/ruff-pre-commit
                rev: v0.17.3
                hooks:
                  - id: ruff-check
                    args: [--fix]
                  - id: ruff-format
            ```

            That needs the network, so the demo uses **local hooks** (`repo: local`,
            `language: system`) that run the ruff already installed in the course
            environment. A scratch git repository, then `pre-commit install` writes the hook
            into `.git/hooks/pre-commit`:
            """
        ),
        code(
            r'''
            HOOK_ENV = tool_env(PATH=f"{VENV_BIN}{os.pathsep}{os.environ['PATH']}")
            hooks_repo = write_files(
                fresh_dir("precommit_demo"),
                {
                    ".pre-commit-config.yaml": """
                    repos:
                      - repo: local
                        hooks:
                          - id: ruff-check
                            name: ruff check
                            entry: ruff check --fix
                            language: system
                            types: [python]
                          - id: ruff-format
                            name: ruff format
                            entry: ruff format
                            language: system
                            types: [python]
                """,
                    "pyproject.toml": '[tool.ruff.lint]\nselect = ["E", "F", "I", "UP", "B"]\n',
                    "shop.py": "import os\nimport sys\ndef discount( total ):\n  return total==None\n",
                },
            )
            for command in (("git", "init", "-q", "-b", "main"), ("pre-commit", "install")):
                shell(*command, cwd=hooks_repo, env=HOOK_ENV)
            '''
        ),
        md(
            """
            The first commit attempt fails: ruff fixed the unused imports and the formatting
            (pre-commit reports "files were modified by this hook"), but `== None` (`E711`) has
            no safe automatic fix. The commit is blocked until the file is fixed and staged
            again.
            """
        ),
        code(
            r"""
            shell("git", "add", "-A", cwd=hooks_repo, env=HOOK_ENV)
            shell("git", "commit", "-q", "-m", "Add discount rule", cwd=hooks_repo, env=HOOK_ENV)
            show_file(hooks_repo / "shop.py")
            """
        ),
        md("After fixing the comparison by hand, the hooks pass and the commit goes through:"),
        code(
            r"""
            (hooks_repo / "shop.py").write_text(
                (hooks_repo / "shop.py").read_text().replace("total == None", "total is None")
            )
            shell("git", "add", "-A", cwd=hooks_repo, env=HOOK_ENV)
            shell("git", "commit", "-m", "Add discount rule", cwd=hooks_repo, env=HOOK_ENV)
            shell("pre-commit", "run", "--all-files", cwd=hooks_repo, env=HOOK_ENV)
            """
        ),
        md(
            """
            **CI with GitHub Actions.** pre-commit can be skipped (`git commit --no-verify`), so
            the same checks run again on GitHub for every push and pull request, on a clean
            machine. A workflow is a YAML file in `.github/workflows/`. This one installs uv,
            syncs the locked environment, and runs lint, format check, type check and tests
            with a coverage threshold on two Python versions. Branch protection then requires
            the job to pass before merging.
            """
        ),
        code(
            r'''
            CI_WORKFLOW = """
                name: CI

                on:
                  push:
                    branches: [main]
                  pull_request:

                jobs:
                  quality:
                    runs-on: ubuntu-latest
                    strategy:
                      matrix:
                        python-version: ["3.14", "3.15"]
                    steps:
                      - uses: actions/checkout@v5
                      - uses: astral-sh/setup-uv@v7
                        with:
                          python-version: ${{ matrix.python-version }}
                      - run: uv sync --locked
                      - run: uv run ruff check .
                      - run: uv run ruff format --check .
                      - run: uv run mypy src
                      - run: uv run pytest --cov=shop --cov-branch --cov-fail-under=90
            """
            ci_project = write_files(fresh_dir("ci_demo"), {".github/workflows/ci.yml": CI_WORKFLOW})
            if importlib.util.find_spec("yaml") is None:
                print("SKIP: PyYAML is not installed, so the workflow is not parsed")
            else:
                import yaml

                workflow = yaml.safe_load((ci_project / ".github" / "workflows" / "ci.yml").read_text())
                quality_job = workflow["jobs"]["quality"]
                print(f"triggers: {list(workflow[True])}  (YAML 1.1 reads the key 'on' as True)")
                print(f"matrix:   {quality_job['strategy']['matrix']}")
                for step in quality_job["steps"]:
                    print(f"  step: {step.get('uses') or step.get('run')}")
            '''
        ),
        md(
            """
            The quirk in the output is real: PyYAML follows YAML 1.1, where `on` means `True`,
            so the trigger key is parsed as the boolean (GitHub's own parser treats it as the
            string). You cannot run GitHub's runners locally (the third-party `act` tool
            imitates them with Docker), but you can run the same steps. A tiny "local CI" runs
            the workflow's `run:` commands (minus `uv sync` and the `mypy src` step, which need
            a full project) against the coverage demo project from 4.3.6:
            """
        ),
        code(
            r"""
            print(f"act installed: {shutil.which('act') is not None}")
            if importlib.util.find_spec("pytest_cov") is not None:
                local_ci = [
                    ("ruff", "check", "."),
                    ("ruff", "format", "--check", "."),
                    (
                        "pytest",
                        "-q",
                        "--no-header",
                        "-p",
                        "no:cacheprovider",
                        "--cov=shop",
                        "--cov-branch",
                        "--cov-fail-under=80",
                    ),
                ]
                for step in local_ci:
                    exit_code, output = run_tool(*step, cwd=coverage_demo)
                    status = "PASS" if exit_code == 0 else f"FAIL (exit {exit_code})"
                    print(f"{status:<14} {shlex.join(step)}")
                    if exit_code:
                        print(textwrap.indent("\n".join(output.splitlines()[-6:]), "    "))
            """
        ),
    ]


LAB_CODE_SOURCE = r'''
RATES_MODULE = """
    \"\"\"Exchange rates from an HTTP service; the HTTP client is injected.\"\"\"

    from decimal import Decimal


    class RateLookupError(Exception):
        \"\"\"The rate service failed or returned something unusable.\"\"\"


    class ExchangeRateClient:
        def __init__(self, http, base_url: str = "https://rates.example.com/v1") -> None:
            self.http = http  # anything with .get(url, *, params, timeout) -> response
            self.base_url = base_url.rstrip("/")

        def rate(self, base: str, quote: str) -> Decimal:
            \"\"\"How many units of quote one unit of base buys.\"\"\"
            response = self.http.get(
                f"{self.base_url}/latest", params={"base": base, "symbols": quote}, timeout=5.0
            )
            if response.status_code != 200:
                raise RateLookupError(f"rate service returned HTTP {response.status_code}")
            try:
                return Decimal(str(response.json()["rates"][quote]))
            except (KeyError, TypeError) as error:
                raise RateLookupError(f"no {quote} rate in the response") from error

        def convert(self, amount: Decimal, base: str, quote: str) -> Decimal:
            \"\"\"amount in base currency -> quote currency, rounded to 2 places.\"\"\"
            if base == quote:
                return amount
            return (amount * self.rate(base, quote)).quantize(Decimal("0.01"))
"""

INVENTORY_MODULE = """
    \"\"\"The Phase 2 inventory domain model (Phase 2 Project, Steps 2-8).\"\"\"

    from __future__ import annotations

    import re
    from collections import defaultdict
    from collections.abc import Callable, Iterator
    from dataclasses import dataclass
    from datetime import datetime
    from enum import StrEnum, auto
    from typing import Any, Protocol, runtime_checkable

    from shop.money import Money

    SKU_PATTERN = re.compile(r"[A-Z]{2,5}-\\d{2,4}")


    @dataclass(frozen=True, slots=True)
    class Product:
        sku: str
        name: str
        unit_price: Money
        reorder_level: int = 5

        def __post_init__(self) -> None:
            if not SKU_PATTERN.fullmatch(self.sku):
                raise ValueError(f"invalid SKU {self.sku!r}: expected e.g. 'TEA-500'")
            if not self.name.strip():
                raise ValueError("product name is required")
            if not isinstance(self.unit_price, Money) or self.unit_price.amount <= 0:
                raise ValueError("unit_price must be a positive Money")
            if self.reorder_level < 0:
                raise ValueError("reorder_level must be >= 0")


    class MovementType(StrEnum):
        RECEIVED = auto()
        SHIPPED = auto()
        RETURNED = auto()
        ADJUSTED = auto()

        @property
        def direction(self) -> int:
            match self:
                case MovementType.RECEIVED | MovementType.RETURNED:
                    return 1
                case MovementType.SHIPPED:
                    return -1
                case _:
                    return 0


    @dataclass(frozen=True, slots=True)
    class StockMovement:
        warehouse_code: str
        sku: str
        movement_type: MovementType
        quantity: int
        occurred_at: datetime
        note: str = ""

        def __post_init__(self) -> None:
            if self.movement_type is MovementType.ADJUSTED:
                if self.quantity == 0:
                    raise ValueError("an adjustment must change the quantity")
            elif self.quantity <= 0:
                raise ValueError(f"{self.movement_type} quantity must be positive")

        @property
        def delta(self) -> int:
            if self.movement_type is MovementType.ADJUSTED:
                return self.quantity
            return self.quantity * self.movement_type.direction


    class InventoryError(Exception):
        error_code = "inventory_error"

        def to_dict(self) -> dict[str, str]:
            return {"error": self.error_code, "message": str(self)}


    class UnknownWarehouseError(InventoryError, LookupError):
        error_code = "unknown_warehouse"

        def __init__(self, warehouse_code: str) -> None:
            super().__init__(f"no warehouse with code {warehouse_code!r}")
            self.warehouse_code = warehouse_code


    class UnknownProductError(InventoryError, LookupError):
        error_code = "unknown_product"

        def __init__(self, sku: str, warehouse_code: str) -> None:
            super().__init__(f"{sku} is not stocked in {warehouse_code}")
            self.sku, self.warehouse_code = sku, warehouse_code


    class DuplicateProductError(InventoryError, ValueError):
        error_code = "duplicate_product"

        def __init__(self, sku: str, warehouse_code: str) -> None:
            super().__init__(f"{sku} is already stocked in {warehouse_code}")
            self.sku, self.warehouse_code = sku, warehouse_code


    class InsufficientStockError(InventoryError):
        error_code = "insufficient_stock"

        def __init__(self, sku: str, available: int, requested: int) -> None:
            super().__init__(f"not enough {sku}: {available} available, {requested} requested")
            self.sku, self.available, self.requested = sku, available, requested


    class Warehouse:
        def __init__(self, code: str, city: str) -> None:
            self.code, self.city = code, city
            self._products: dict[str, Product] = {}
            self._quantities: dict[str, int] = {}

        def __repr__(self) -> str:
            return f"Warehouse({self.code!r}, {self.city!r}, products={len(self)})"

        def __eq__(self, other: object) -> bool:
            return self.code == other.code if isinstance(other, Warehouse) else NotImplemented

        def __hash__(self) -> int:
            return hash(self.code)

        def __len__(self) -> int:
            return len(self._products)

        def __contains__(self, item: object) -> bool:
            sku = item.sku if isinstance(item, Product) else item
            return sku in self._products

        def __getitem__(self, sku: str) -> int:
            if sku not in self._products:
                raise UnknownProductError(sku, self.code)
            return self._quantities[sku]

        def __iter__(self) -> Iterator[Product]:
            return iter(sorted(self._products.values(), key=lambda product: product.sku))

        def __bool__(self) -> bool:
            return any(self._quantities.values())

        def product(self, sku: str) -> Product:
            if sku not in self._products:
                raise UnknownProductError(sku, self.code)
            return self._products[sku]

        def add_product(self, product: Product) -> None:
            if product.sku in self._products:
                raise DuplicateProductError(product.sku, self.code)
            self._products[product.sku] = product
            self._quantities[product.sku] = 0

        def apply(self, movement: StockMovement) -> int:
            available = self[movement.sku]
            if available + movement.delta < 0:
                raise InsufficientStockError(movement.sku, available, -movement.delta)
            self._quantities[movement.sku] = available + movement.delta
            return self._quantities[movement.sku]

        def stock_value(self) -> Money:
            return sum((product.unit_price * self[product.sku] for product in self), Money(0))

        def low_stock(self) -> list[Product]:
            return [product for product in self if self[product.sku] <= product.reorder_level]


    @runtime_checkable
    class InventoryRepository(Protocol):
        def get_warehouse(self, code: str) -> Warehouse: ...
        def save_warehouse(self, warehouse: Warehouse) -> None: ...
        def list_warehouses(self) -> list[Warehouse]: ...
        def record_movement(self, movement: StockMovement) -> None: ...
        def movements(self, *, sku: str | None = None) -> list[StockMovement]: ...


    class InMemoryInventoryRepository:
        def __init__(self) -> None:
            self._warehouses: dict[str, Warehouse] = {}
            self._movements: list[StockMovement] = []

        def get_warehouse(self, code: str) -> Warehouse:
            try:
                return self._warehouses[code]
            except KeyError:
                raise UnknownWarehouseError(code) from None

        def save_warehouse(self, warehouse: Warehouse) -> None:
            self._warehouses[warehouse.code] = warehouse

        def list_warehouses(self) -> list[Warehouse]:
            return sorted(self._warehouses.values(), key=lambda warehouse: warehouse.code)

        def record_movement(self, movement: StockMovement) -> None:
            self._movements.append(movement)

        def movements(self, *, sku: str | None = None) -> list[StockMovement]:
            return [movement for movement in self._movements if sku is None or movement.sku == sku]


    @dataclass(frozen=True)
    class StockChanged:
        warehouse_code: str
        sku: str
        old_quantity: int
        new_quantity: int
        movement_type: MovementType


    @dataclass(frozen=True)
    class LowStockAlert:
        warehouse_code: str
        sku: str
        quantity: int
        reorder_level: int


    class EventBus:
        def __init__(self) -> None:
            self._handlers: defaultdict[type, list[Callable[[Any], None]]] = defaultdict(list)

        def subscribe(self, event_type: type, handler: Callable[[Any], None]) -> None:
            self._handlers[event_type].append(handler)

        def publish(self, event: object) -> int:
            handlers = self._handlers.get(type(event), [])
            for handler in handlers:
                handler(event)
            return len(handlers)


    class InventoryService:
        def __init__(
            self,
            repository: InventoryRepository,
            events: EventBus,
            clock: Callable[[], datetime] = datetime.now,
        ) -> None:
            self.repository, self.events, self.clock = repository, events, clock

        def open_warehouse(self, code: str, city: str) -> Warehouse:
            warehouse = Warehouse(code, city)
            self.repository.save_warehouse(warehouse)
            return warehouse

        def register_product(self, warehouse_code: str, product: Product) -> None:
            warehouse = self.repository.get_warehouse(warehouse_code)
            warehouse.add_product(product)
            self.repository.save_warehouse(warehouse)

        def receive(self, warehouse_code: str, sku: str, quantity: int, note: str = "") -> int:
            return self._record(warehouse_code, sku, MovementType.RECEIVED, quantity, note)

        def ship(self, warehouse_code: str, sku: str, quantity: int, note: str = "") -> int:
            return self._record(warehouse_code, sku, MovementType.SHIPPED, quantity, note)

        def accept_return(
            self, warehouse_code: str, sku: str, quantity: int, note: str = ""
        ) -> int:
            return self._record(warehouse_code, sku, MovementType.RETURNED, quantity, note)

        def adjust(self, warehouse_code: str, sku: str, change: int, note: str) -> int:
            return self._record(warehouse_code, sku, MovementType.ADJUSTED, change, note)

        def transfer(self, from_code: str, to_code: str, sku: str, quantity: int) -> None:
            source = self.repository.get_warehouse(from_code)
            destination = self.repository.get_warehouse(to_code)
            if source[sku] < quantity:
                raise InsufficientStockError(sku, source[sku], quantity)
            if sku not in destination:
                self.register_product(to_code, source.product(sku))
            self.ship(from_code, sku, quantity, note=f"transfer to {to_code}")
            self.receive(to_code, sku, quantity, note=f"transfer from {from_code}")

        def total_value(self) -> Money:
            return sum(
                (warehouse.stock_value() for warehouse in self.repository.list_warehouses()),
                Money(0),
            )

        def stock_report(self, warehouse_code: str) -> list[str]:
            warehouse = self.repository.get_warehouse(warehouse_code)
            lines = [f"{warehouse.code} ({warehouse.city})"]
            for product in warehouse:
                flag = "  LOW" if product in warehouse.low_stock() else ""
                lines.append(f"{product.sku:<9}{warehouse[product.sku]:>5}{flag}")
            lines.append(f"total {warehouse.stock_value()}")
            return lines

        def _record(
            self,
            warehouse_code: str,
            sku: str,
            movement_type: MovementType,
            quantity: int,
            note: str,
        ) -> int:
            warehouse = self.repository.get_warehouse(warehouse_code)
            old_quantity = warehouse[sku]
            movement = StockMovement(
                warehouse_code, sku, movement_type, quantity, self.clock(), note
            )
            new_quantity = warehouse.apply(movement)
            self.repository.record_movement(movement)
            self.repository.save_warehouse(warehouse)
            self.events.publish(
                StockChanged(warehouse_code, sku, old_quantity, new_quantity, movement_type)
            )
            reorder_level = warehouse.product(sku).reorder_level
            if old_quantity > reorder_level >= new_quantity:
                self.events.publish(LowStockAlert(warehouse_code, sku, new_quantity, reorder_level))
            return new_quantity
"""

LAB_MODULES = {
    "shop/__init__.py": "",
    "shop/money.py": MONEY_MODULE,
    "shop/billing.py": BILLING_MODULE,
    "shop/rates.py": RATES_MODULE,
    "shop/inventory.py": INVENTORY_MODULE,
}
LAB43_DIR = find_repo_root() / "notebooks" / "_scratch" / "unit43" / "lab"
LAB_SHOP_DIR = LAB43_DIR / "shop_src"
for relative_path, module_source in LAB_MODULES.items():
    target = LAB_SHOP_DIR / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(textwrap.dedent(module_source).lstrip("\n"))
if str(LAB_SHOP_DIR) not in sys.path:
    sys.path.insert(0, str(LAB_SHOP_DIR))  # lab only: lets you import the shop package here too

from shop.billing import split_bill  # noqa: E402
from shop.inventory import (  # noqa: E402
    EventBus,
    InMemoryInventoryRepository,
    InsufficientStockError,
    InventoryService,
    LowStockAlert,
    MovementType,
    Product,
    StockMovement,
    UnknownProductError,
    UnknownWarehouseError,
    Warehouse,
)
from shop.money import CurrencyMismatchError, Money  # noqa: E402
from shop.rates import ExchangeRateClient, RateLookupError  # noqa: E402

LAB_NAMES = (
    EventBus,
    InMemoryInventoryRepository,
    InsufficientStockError,
    InventoryService,
    LowStockAlert,
)
LAB_NAMES += (
    MovementType,
    Product,
    StockMovement,
    UnknownProductError,
    UnknownWarehouseError,
    Warehouse,
)
LAB_NAMES += (CurrencyMismatchError, Money, ExchangeRateClient, RateLookupError, split_bill)
print(f"shop package at <scratch>/lab/shop_src: {sorted(LAB_MODULES)}")
print(f"imported into the kernel: {', '.join(obj.__name__ for obj in LAB_NAMES)}")
print(f"{split_bill('100', 3)=}")
'''

LAB_RUNNER_SOURCE = r'''
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass

import pytest

LAB_TEST_PRELUDE = """
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from unittest import mock

import pytest
from hypothesis import assume, example, given, settings
from hypothesis import strategies as st

from shop.billing import split_bill
from shop.inventory import (
    DuplicateProductError, EventBus, InMemoryInventoryRepository, InsufficientStockError,
    InventoryError, InventoryRepository, InventoryService, LowStockAlert, MovementType, Product,
    StockChanged, StockMovement, UnknownProductError, UnknownWarehouseError, Warehouse,
)
from shop.money import CurrencyMismatchError, Money
from shop.rates import ExchangeRateClient, RateLookupError
"""
LAB_CONFTEST = """
from hypothesis import settings

settings.register_profile("lab", derandomize=True, database=None, deadline=None)
settings.load_profile("lab")
"""
LAB_PYPROJECT = """
[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
"""


@dataclass(frozen=True)
class LabRun:
    """Outcome of one pytest run: test name -> "passed" / "failed" / "skipped", plus coverage."""

    outcomes: dict[str, str]
    coverage_percent: float | None
    output: str

    @property
    def green(self) -> bool:
        """At least one test ran and nothing failed or errored."""
        return bool(self.outcomes) and set(self.outcomes.values()) <= {"passed"}


def lab_test_source(objects: list[object]) -> str:
    """The prelude followed by the source of each test or fixture function (never raises)."""
    try:
        return LAB_TEST_PRELUDE + "\n\n" + "\n\n".join(source_of(obj) for obj in objects)
    except (OSError, TypeError) as error:
        return (
            LAB_TEST_PRELUDE
            + f"\n\ndef test_source_unavailable():\n    raise RuntimeError({str(error)!r})\n"
        )


def run_lab_tests(
    test_source: str,
    conftest_source: str = "",
    mutation: tuple[str, str, str] | None = None,
    coverage_target: str | None = None,
) -> LabRun:
    """Run test_source with pytest in a child process against the shop package (or a mutant)."""
    return _cached_lab_run(test_source, conftest_source, mutation, coverage_target)


@functools.cache
def _cached_lab_run(
    test_source: str,
    conftest_source: str,
    mutation: tuple[str, str, str] | None,
    coverage_target: str | None,
) -> LabRun:
    """The run behind run_lab_tests; identical runs are done once."""
    modules = dict(LAB_MODULES)
    if mutation is not None:
        path, old, new = mutation
        if old not in modules[path]:
            raise ValueError(f"mutation target not found in {path}: {old!r}")
        modules[path] = modules[path].replace(old, new)
    root = LAB43_DIR / "run"
    shutil.rmtree(root, ignore_errors=True)
    files = {**modules, "pyproject.toml": LAB_PYPROJECT, "tests/test_lab.py": test_source}
    files["tests/conftest.py"] = LAB_CONFTEST + "\n" + conftest_source
    for relative_path, text in files.items():
        (root / relative_path).parent.mkdir(parents=True, exist_ok=True)
        (root / relative_path).write_text(
            textwrap.dedent(text).lstrip("\n") if relative_path.startswith("shop") else text
        )
    command = [
        str(Path(sys.executable).parent / "pytest"),
        "-q",
        "-p",
        "no:cacheprovider",
        "--junit-xml=report.xml",
    ]
    if coverage_target:
        command += [f"--cov={coverage_target}", "--cov-branch", "--cov-report=json:coverage.json"]
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("PYTEST_", "PYTHONPATH", "COV"))
    }
    completed = subprocess.run(
        command,
        cwd=root,
        capture_output=True,
        text=True,
        timeout=600,
        env={**environment, "NO_COLOR": "1", "PY_COLORS": "0", "PYTHONDONTWRITEBYTECODE": "1"},
    )
    outcomes: dict[str, str] = {}
    if (root / "report.xml").exists():
        for case in ElementTree.parse(root / "report.xml").getroot().iter("testcase"):
            failed = case.find("failure") is not None or case.find("error") is not None
            skipped = case.find("skipped") is not None
            outcomes[case.get("name", "?")] = (
                "failed" if failed else "skipped" if skipped else "passed"
            )
    coverage_percent = None
    if coverage_target and (root / "coverage.json").exists():
        report = json.loads((root / "coverage.json").read_text())
        coverage_percent = round(report["totals"]["percent_covered"], 1)
    return LabRun(outcomes, coverage_percent, completed.stdout + completed.stderr)


def catches(test_source: str, mutation: tuple[str, str, str], conftest_source: str = "") -> bool:
    """True if the tests pass on the real shop package and fail on the mutant."""
    return (
        run_lab_tests(test_source, conftest_source).green
        and not run_lab_tests(test_source, conftest_source, mutation).green
    )


print("lab runner ready: run_lab_tests(source), catches(source, mutation)")
'''


def _lab_intro_cells() -> list[NotebookNode]:
    """Lab 4.3 introduction, code under test and runner."""
    return [
        md(
            """
            ### Lab 4.3

            Seven exercises. In exercises 1–4 and 7 you write **tests**, so the checks test
            your tests: each check cell takes the source of your test functions
            (`source_of`), adds the imports listed below, runs them with the real pytest in a
            child process against the `shop` package, and then against **mutants**, copies of
            the package with one small bug planted. A good suite passes on the real code and
            fails on every mutant ("catches" it). Exercise 5 runs in the kernel; exercise 6
            runs pdb.

            Every lab test file starts with these imports, so your tests can use the names
            directly: `pytest`, `mock` (from `unittest`), `Decimal`, `datetime`, `Callable`,
            Hypothesis's `given`, `example`, `assume`, `settings` and `st`, and from `shop`:
            `Money`, `CurrencyMismatchError`, `split_bill`, `ExchangeRateClient`,
            `RateLookupError` and every name of the inventory model (`Product`, `Warehouse`,
            `StockMovement`, `MovementType`, `InMemoryInventoryRepository`, `EventBus`,
            `InventoryService`, `LowStockAlert`, `StockChanged`, the `…Error` classes).
            Hypothesis runs deterministically (a fixed profile). Until you finish, the checks
            print FAIL; that is expected.

            **The code under test.** The next cell writes the `shop` package to
            `notebooks/_scratch/unit43/lab/shop_src/` and, for the lab only, puts that folder
            on `sys.path` so you can also try things in the kernel. `shop.rates` is new: an
            exchange-rate client that receives its HTTP client from outside (dependency
            injection), so tests can pass a mock. `shop.inventory` is the Phase 2 inventory
            model.
            """
        ),
        code(LAB_CODE_SOURCE),
        md(
            """
            **The lab runner.** `run_lab_tests(source, conftest, mutation, coverage_target)`
            runs a test file and returns a `LabRun` (outcome per test, coverage percent, raw
            output); results are cached by content, so each distinct run happens once.
            `catches(source, mutation)` is True when the tests pass on the real package and
            fail on the mutant. A mutation is `(file, old text, new text)`.
            """
        ),
        code(LAB_RUNNER_SOURCE),
    ]


def _lab_exercise_cells() -> list[NotebookNode]:
    """Lab 4.3 exercises 1–4."""
    return [
        md(
            """
            #### Exercise 1 — parametrized tests for `Money`

            Turn the three stubs into real tests of the shared `Money` type.
            `test_money_rounding` and `test_money_arithmetic` must each be parametrized with
            **at least 4 cases and readable ids** (`ids=[...]` or `pytest.param(..., id=...)`);
            `test_money_rejects_bad_input` uses `pytest.raises`. Change the signatures as
            needed. The suite must pass on the real `Money` and catch four planted bugs:
            rounding half-even instead of half-up, a missing currency check in `+`, float
            amounts accepted, and subtraction computed the wrong way round.
            """
        ),
        code(
            r'''
            def test_money_rounding() -> None:
                """Parametrize: raw amount text -> expected Decimal amount (4+ cases, with ids)."""
                raise NotImplementedError


            def test_money_arithmetic() -> None:
                """Parametrize: + and - on Money values -> expected Money (4+ cases, with ids)."""
                raise NotImplementedError


            def test_money_rejects_bad_input() -> None:
                """pytest.raises: float amounts (TypeError), mixed currencies (CurrencyMismatchError)."""
                raise NotImplementedError


            MONEY_TESTS = [test_money_rounding, test_money_arithmetic, test_money_rejects_bad_input]
            '''
        ),
        md("Check exercise 1:"),
        code(
            r'''
            def parametrized_with_ids(test: object, minimum_cases: int = 4) -> bool:
                """Does test carry a parametrize mark with enough cases, each with a readable id?"""
                for mark in getattr(test, "pytestmark", []):
                    if mark.name != "parametrize" or len(mark.args) < 2:
                        continue
                    cases = list(mark.args[1])
                    explicit_ids = "ids" in mark.kwargs or all(getattr(case, "id", None) for case in cases)
                    if len(cases) >= minimum_cases and explicit_ids:
                        return True
                return False


            MONEY_MUTANTS = {
                "half-even rounding": ("shop/money.py", "rounding=ROUND_HALF_UP", 'rounding="ROUND_HALF_EVEN"'),
                "no currency check": ("shop/money.py", "if other._currency != self._currency:", "if False:"),
                "floats accepted": ("shop/money.py", "if isinstance(amount, float):", "if False:"),
                "reversed subtraction": (
                    "shop/money.py",
                    "Money(self._amount - other._amount",
                    "Money(other._amount - self._amount",
                ),
            }
            money_source = lab_test_source(MONEY_TESTS)
            run_checks(
                [
                    ("tests pass on the real Money", lambda: run_lab_tests(money_source).green, True),
                    (
                        "test_money_rounding: 4+ cases with ids",
                        lambda: parametrized_with_ids(MONEY_TESTS[0]),
                        True,
                    ),
                    (
                        "test_money_arithmetic: 4+ cases with ids",
                        lambda: parametrized_with_ids(MONEY_TESTS[1]),
                        True,
                    ),
                    *[
                        (f"catches: {name}", lambda mutation=mutation: catches(money_source, mutation), True)
                        for name, mutation in MONEY_MUTANTS.items()
                    ],
                ]
            )
            '''
        ),
        md(
            """
            #### Exercise 2 — repository fixtures

            Write four fixtures for testing the inventory service. The check puts them in a
            `conftest.py` and runs its own hidden tests that use them:

            | Fixture | Scope | Provides |
            | --- | --- | --- |
            | `catalogue` | session | `dict[str, Product]`: `TEA-500` (₹240, reorder level 10), `MUG-02` (₹199, 5), `JAR-750` (₹350, 3) |
            | `repository(catalogue)` | function | a fresh `InMemoryInventoryRepository` with warehouses `PNQ1` (Pune) and `BLR1` (Bengaluru), each carrying every catalogue product with zero stock |
            | `clock` | function | a callable that always returns `datetime(2026, 11, 7, 9, 30)` |
            | `make_service(repository, clock)` | function | a **factory**: `make_service(stock=None)` returns an `InventoryService` on that repository and clock with a new `EventBus`, after receiving each `{sku: quantity}` of `stock` into `PNQ1` |
            """
        ),
        code(
            r'''
            @pytest.fixture(scope="session")
            def catalogue() -> dict[str, Product]:
                """TEA-500 (240, reorder 10), MUG-02 (199, reorder 5), JAR-750 (350, reorder 3)."""
                raise NotImplementedError


            @pytest.fixture
            def repository(catalogue: dict[str, Product]) -> InMemoryInventoryRepository:
                """PNQ1 (Pune) and BLR1 (Bengaluru), each carrying every product, zero stock."""
                raise NotImplementedError


            @pytest.fixture
            def clock() -> Callable[[], datetime]:
                """Always returns datetime(2026, 11, 7, 9, 30)."""
                raise NotImplementedError


            @pytest.fixture
            def make_service(
                repository: InMemoryInventoryRepository, clock: Callable[[], datetime]
            ) -> Callable[..., InventoryService]:
                """Factory: make_service(stock=None) -> InventoryService, stock received into PNQ1."""
                raise NotImplementedError


            INVENTORY_FIXTURES = [catalogue, repository, clock, make_service]
            '''
        ),
        md("Check exercise 2 (each line is one hidden test that uses your fixtures):"),
        code(
            r'''
            FIXTURE_CHECKS = textwrap.dedent("""
            SEEN_CATALOGUES = []


            def test_catalogue_contents(catalogue):
                assert sorted(catalogue) == ["JAR-750", "MUG-02", "TEA-500"]
                tea = catalogue["TEA-500"]
                assert (tea.unit_price, tea.reorder_level) == (Money("240"), 10)
                mug, jar = catalogue["MUG-02"], catalogue["JAR-750"]
                assert (mug.unit_price, jar.reorder_level) == (Money("199"), 3)
                SEEN_CATALOGUES.append(catalogue)


            def test_catalogue_is_session_scoped(catalogue):
                assert SEEN_CATALOGUES and SEEN_CATALOGUES[0] is catalogue


            def test_repository_warehouses(repository):
                places = [(w.code, w.city) for w in repository.list_warehouses()]
                assert places == [("BLR1", "Bengaluru"), ("PNQ1", "Pune")]
                assert all(len(w) == 3 and not w for w in repository.list_warehouses())


            def test_clock_is_fixed(clock):
                assert clock() == datetime(2026, 11, 7, 9, 30) == clock()


            def test_make_service_receives_stock(make_service, clock):
                service = make_service({"TEA-500": 40, "MUG-02": 6})
                pune = service.repository.get_warehouse("PNQ1")
                assert (pune["TEA-500"], pune["MUG-02"], pune["JAR-750"]) == (40, 6, 0)
                assert {movement.occurred_at for movement in service.repository.movements()} == {clock()}


            def test_isolation_part_1(make_service):
                service = make_service({"TEA-500": 5})
                service.ship("PNQ1", "TEA-500", 2)
                assert service.repository.get_warehouse("PNQ1")["TEA-500"] == 3


            def test_isolation_part_2(repository):
                assert repository.get_warehouse("PNQ1")["TEA-500"] == 0 and repository.movements() == []


            def test_factory_shares_the_repository(make_service, repository):
                first, second = make_service({"TEA-500": 40}), make_service({"TEA-500": 2})
                assert first.repository is repository is second.repository
                assert repository.get_warehouse("PNQ1")["TEA-500"] == 42


            def test_each_service_has_its_own_event_bus(make_service):
                first, second = make_service(), make_service()
                alerts = []
                first.events.subscribe(LowStockAlert, alerts.append)
                first.receive("PNQ1", "MUG-02", 6)
                first.ship("PNQ1", "MUG-02", 2)
                assert first.events is not second.events
                assert [(alert.sku, alert.quantity) for alert in alerts] == [("MUG-02", 4)]
            """)  # dedent: the solutions file runs this cell inside a function


            def fixture_outcome(test_name: str) -> str | None:
                """Outcome of one hidden test run against the learner's fixtures."""
                return run_lab_tests(
                    LAB_TEST_PRELUDE + FIXTURE_CHECKS, lab_test_source(INVENTORY_FIXTURES)
                ).outcomes.get(test_name)


            run_checks(
                [
                    (
                        name.removeprefix("test_").replace("_", " "),
                        lambda name=name: fixture_outcome(name),
                        "passed",
                    )
                    for name in re.findall(r"^def (test_\w+)", FIXTURE_CHECKS, re.MULTILINE)
                ]
            )
            '''
        ),
        md(
            """
            #### Exercise 3 — mock an HTTP client

            `ExchangeRateClient` (in `shop.rates`, imported above) calls
            `http.get(url, params=..., timeout=...)` on an injected client and expects a
            response with `.status_code` and `.json()`. The real service answers JSON such as
            `{"rates": {"USD": 0.012}}` (rates are JSON **numbers**). Write tests that use
            `unittest.mock` doubles (no network) and pass on the real client, and that catch
            these planted bugs:

            - the request is sent without `timeout=5.0`, or with the wrong query parameters
              (it must be `params={"base": ..., "symbols": ...}` to `<base_url>/latest`);
            - the rate is converted with `Decimal(float)` (`Decimal(0.012)` is not `0.012`);
            - a non-200 response is not rejected **before reading the body** (assert that
              `.json()` was not called and `RateLookupError` was raised);
            - `convert` calls the service even when `base == quote`.

            Put all your test functions in `RATE_TESTS`.
            """
        ),
        code(
            r"""
            def test_rate_is_parsed_exactly() -> None:
                raise NotImplementedError


            def test_rate_request_is_well_formed() -> None:
                raise NotImplementedError


            def test_http_error_is_rejected_before_reading_the_body() -> None:
                raise NotImplementedError


            def test_same_currency_conversion_skips_the_service() -> None:
                raise NotImplementedError


            RATE_TESTS = [
                test_rate_is_parsed_exactly,
                test_rate_request_is_well_formed,
                test_http_error_is_rejected_before_reading_the_body,
                test_same_currency_conversion_skips_the_service,
            ]
            """
        ),
        md("Check exercise 3:"),
        code(
            r"""
            RATE_MUTANTS = {
                "missing timeout": ("shop/rates.py", ", timeout=5.0\n", "\n"),
                "wrong query parameter": ("shop/rates.py", '"symbols": quote', '"symbol": quote'),
                "Decimal(float)": (
                    "shop/rates.py",
                    'Decimal(str(response.json()["rates"][quote]))',
                    'Decimal(response.json()["rates"][quote])',
                ),
                "no status check": ("shop/rates.py", "if response.status_code != 200:", "if False:"),
                "service called for same currency": ("shop/rates.py", "if base == quote:", "if False:"),
            }
            rate_source = lab_test_source(RATE_TESTS)
            run_checks(
                [
                    ("tests pass on the real client", lambda: run_lab_tests(rate_source).green, True),
                    (
                        "tests use unittest.mock",
                        lambda: bool(re.search(r"\bmock\.|Mock\(|patch", "".join(map(source_of, RATE_TESTS)))),
                        True,
                    ),
                    *[
                        (f"catches: {name}", lambda mutation=mutation: catches(rate_source, mutation), True)
                        for name, mutation in RATE_MUTANTS.items()
                    ],
                ]
            )
            """
        ),
        md(
            """
            #### Exercise 4 — Hypothesis tests for `split_bill`

            Write **property-based** tests (each decorated with `@given`) for `split_bill` from
            `shop.billing`. Generate totals as strings with two decimal places (for example
            `st.decimals(min_value=0, max_value=100_000, places=2).map(str)`) and 1–50
            people. State these properties:

            1. there are exactly `people_count` shares;
            2. the shares add up **exactly** to the total;
            3. no two shares differ by more than one paisa;
            4. the shares never increase from first to last (the leftover paise go to the
               first people);
            5. `people_count < 1` raises `ValueError` (generate zero and negative counts).

            The check runs them on the real function and on four mutants: the leftover goes to
            the last people, the leftover is dropped, zero people are not rejected, and the
            total is converted with `float`.
            """
        ),
        code(
            r"""
            def test_share_count() -> None:
                raise NotImplementedError


            def test_shares_add_up_exactly() -> None:
                raise NotImplementedError


            def test_shares_differ_by_at_most_one_paisa() -> None:
                raise NotImplementedError


            def test_shares_never_increase() -> None:
                raise NotImplementedError


            def test_invalid_people_count_is_rejected() -> None:
                raise NotImplementedError


            SPLIT_BILL_TESTS = [
                test_share_count,
                test_shares_add_up_exactly,
                test_shares_differ_by_at_most_one_paisa,
                test_shares_never_increase,
                test_invalid_people_count_is_rejected,
            ]
            """
        ),
        md("Check exercise 4:"),
        code(
            r"""
            BILL_MUTANTS = {
                "leftover to the last people": (
                    "shop/billing.py",
                    "(1 if index < leftover_paise else 0)",
                    "(1 if index >= people_count - leftover_paise else 0)",
                ),
                "leftover dropped": ("shop/billing.py", "(1 if index < leftover_paise else 0)", "0"),
                "zero people accepted": ("shop/billing.py", "if people_count < 1:", "if people_count < 0:"),
                "float conversion": (
                    "shop/billing.py",
                    "int(Decimal(total_amount).quantize(PAISE, rounding=ROUND_HALF_UP) * 100)",
                    "int(float(total_amount) * 100)",
                ),
            }
            bill_source = lab_test_source(SPLIT_BILL_TESTS)
            hypothesis_ready = importlib.util.find_spec("hypothesis") is not None
            if not hypothesis_ready:
                print("SKIP: hypothesis is not installed (uv add --dev hypothesis)")
            run_checks(
                [
                    (
                        "every test uses @given",
                        lambda: all(getattr(test, "is_hypothesis_test", False) for test in SPLIT_BILL_TESTS),
                        True,
                    ),
                    ("tests pass on the real split_bill", lambda: run_lab_tests(bill_source).green, True),
                    *[
                        (f"catches: {name}", lambda mutation=mutation: catches(bill_source, mutation), True)
                        for name, mutation in BILL_MUTANTS.items()
                    ],
                ]
            )
            """
        ),
    ]


def _lab_logging_debugging_cells() -> list[NotebookNode]:
    """Lab 4.3 exercises 5–7."""
    return [
        md(
            """
            #### Exercise 5 — a `dictConfig` with JSON output

            1. `JsonFormatter.format(record)` returns **one line** of JSON with the keys
               `time` (the record's creation time in UTC, ISO 8601, e.g.
               `2026-11-07T09:30:00.123456+00:00`), `level`, `logger`, `message` (the merged
               message), every attribute added with `extra=...` (anything not a standard
               `LogRecord` attribute), and `exception` (the formatted traceback, via
               `self.formatException`) only when the record carries exception info.
            2. `build_logging_config(stream)` returns a `dictConfig` dictionary: version 1,
               existing loggers kept enabled, a formatter using `JsonFormatter` (through the
               `"()"` key), one `StreamHandler` writing to `stream` at level `INFO` with a
               filter that drops records whose message contains `/health`, the logger `shop`
               at `DEBUG` using that handler without propagating, and `shop.payments` at
               `WARNING`.

            The check applies your config, logs six records through `shop.orders` and
            `shop.payments`, and expects exactly three JSON lines. Afterwards it removes the
            handlers again.
            """
        ),
        code(
            r'''
            from typing import IO


            class JsonFormatter(logging.Formatter):
                """Format each record as one line of JSON."""

                def format(self, record: logging.LogRecord) -> str:
                    raise NotImplementedError


            def build_logging_config(stream: IO[str]) -> dict[str, object]:
                """A dictConfig dict: JSON lines to stream for the shop loggers."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 5:"),
        code(
            r'''
            def json_log_lines() -> list[dict[str, object]]:
                """Apply the learner's config, emit six records, return the parsed JSON lines."""
                stream = io.StringIO()
                logging.config.dictConfig(build_logging_config(stream))
                orders, payments = logging.getLogger("shop.orders"), logging.getLogger("shop.payments")
                try:
                    orders.debug("cart recalculated")
                    orders.info("order %s placed", 7, extra={"order_id": 7, "customer": "Asha"})
                    orders.info("GET /health 200")
                    payments.info("payment authorised")
                    payments.warning("payment retry %d/3", 2)
                    try:
                        _ = 1 / 0
                    except ZeroDivisionError:
                        orders.exception("charging order %s failed", 8)
                finally:
                    for name in ("shop", "shop.orders", "shop.payments"):
                        logger = logging.getLogger(name)
                        for handler in logger.handlers[:]:
                            logger.removeHandler(handler)
                        logger.setLevel(logging.NOTSET)
                        logger.propagate = True
                return [json.loads(line) for line in stream.getvalue().splitlines()]


            STANDARD_KEYS = set(vars(logging.makeLogRecord({}))) - {"message"}
            UTC_ISO = r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?\+00:00"
            run_checks(
                [
                    (
                        "three lines (DEBUG, /health and payments INFO dropped)",
                        lambda: len(json_log_lines()),
                        3,
                    ),
                    (
                        "line 1 fields",
                        lambda: {key: json_log_lines()[0].get(key) for key in ("level", "logger", "message")},
                        {"level": "INFO", "logger": "shop.orders", "message": "order 7 placed"},
                    ),
                    (
                        "line 1 extras",
                        lambda: (json_log_lines()[0].get("order_id"), json_log_lines()[0].get("customer")),
                        (7, "Asha"),
                    ),
                    (
                        "time is UTC ISO 8601",
                        lambda: all(
                            re.fullmatch(UTC_ISO, str(line.get("time"))) is not None
                            for line in json_log_lines()
                        ),
                        True,
                    ),
                    (
                        "no standard attributes leak",
                        lambda: sorted(STANDARD_KEYS & set(json_log_lines()[0])),
                        [],
                    ),
                    ("no exception key without exc_info", lambda: "exception" in json_log_lines()[0], False),
                    (
                        "line 2 from shop.payments",
                        lambda: (
                            json_log_lines()[1].get("logger"),
                            json_log_lines()[1].get("message"),
                            json_log_lines()[1].get("level"),
                        ),
                        ("shop.payments", "payment retry 2/3", "WARNING"),
                    ),
                    (
                        "line 3 has the traceback",
                        lambda: (
                            json_log_lines()[2].get("level"),
                            "ZeroDivisionError" in str(json_log_lines()[2].get("exception")),
                        ),
                        ("ERROR", True),
                    ),
                ]
            )
            '''
        ),
        md(
            """
            #### Exercise 6 — a pdb debugging walkthrough

            `coupon.py` (written by the next cell) should print `61110`: two teas at ₹240 and a
            mug at ₹199 are 67,900 paise, minus 10% for the `DIWALI10` coupon. It prints `0`.
            Find the bug **with pdb**, not by reading:

            1. `coupon_debug_commands()` returns the commands of your session. They are fed to
               `python -m pdb coupon.py`, which stops before line 1. Your session must stop
               inside `apply_coupon`, print `percent` (10) and, after the next line has run,
               `discount`, and show the call stack (`w`).
            2. `coupon_bug_report()` returns `(line number of the bug, the corrected line)`.
               The check replaces that line and runs the script, which must print `61110`.

            The transcript of your session is printed below the checks.
            """
        ),
        code(
            r'''
            COUPON_SCRIPT = """
            COUPONS = {"DIWALI10": 10, "FLAT5": 5}


            def apply_coupon(total_paise, coupon):
                percent = COUPONS.get(coupon, 0)
                discount = total_paise * percent // 10
                return total_paise - discount


            def checkout(cart, coupon):
                total = sum(price * quantity for price, quantity in cart)
                return apply_coupon(total, coupon)


            print(checkout([(24000, 2), (19900, 1)], "DIWALI10"))
            """
            COUPON_DIR = LAB43_DIR / "coupon"
            COUPON_DIR.mkdir(parents=True, exist_ok=True)
            (COUPON_DIR / "coupon.py").write_text(textwrap.dedent(COUPON_SCRIPT).lstrip("\n"))
            for number, line in enumerate((COUPON_DIR / "coupon.py").read_text().splitlines(), start=1):
                print(f"{number:>2}  {line}")


            def coupon_debug_commands() -> list[str]:
                """The pdb commands of your session, in order."""
                raise NotImplementedError


            def coupon_bug_report() -> tuple[int, str]:
                """(line number of the bug, the corrected line)."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 6:"),
        code(
            r'''
            def lab_pdb_session(commands: list[str]) -> list[tuple[str, str]]:
                """Run `python -m pdb coupon.py` with commands; return (command, its output) pairs."""
                completed = subprocess.run(
                    [sys.executable, "-m", "pdb", "coupon.py"],
                    cwd=COUPON_DIR,
                    input="\n".join(commands) + "\n",
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=60,
                    env={**os.environ, "PYTHON_COLORS": "0", "NO_COLOR": "1"},
                )
                transcript = completed.stdout.replace(str(COUPON_DIR), "<lab>").replace(
                    sys.base_prefix, "<python>"
                )
                pieces = transcript.split("(Pdb) ")
                return [
                    (command, pieces[index + 1] if index + 1 < len(pieces) else "")
                    for index, command in enumerate(commands)
                ]


            def run_fixed_coupon(line_number: int, fixed_line: str) -> str:
                """Replace one line of coupon.py (keeping its indentation) and run the result."""
                lines = (COUPON_DIR / "coupon.py").read_text().splitlines()
                original = lines[line_number - 1]
                lines[line_number - 1] = original[: len(original) - len(original.lstrip())] + fixed_line.strip()
                (COUPON_DIR / "coupon_fixed.py").write_text("\n".join(lines) + "\n")
                completed = subprocess.run(
                    [sys.executable, "coupon_fixed.py"],
                    cwd=COUPON_DIR,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                return (completed.stdout + completed.stderr).strip()


            def printed(session: list[tuple[str, str]], name: str, value: str) -> bool:
                """Did a p/pp/display command mentioning name print value?"""
                return any(
                    re.match(rf"(p|pp|print|display)\b.*\b{name}\b", command.strip())
                    and re.search(rf"\b{value}\b", output)
                    for command, output in session
                )


            run_checks(
                [
                    (
                        "stopped inside apply_coupon",
                        lambda: any(
                            "apply_coupon()" in output for _, output in lab_pdb_session(coupon_debug_commands())
                        ),
                        True,
                    ),
                    (
                        "printed percent (10)",
                        lambda: printed(lab_pdb_session(coupon_debug_commands()), "percent", "10"),
                        True,
                    ),
                    (
                        "printed discount (67900)",
                        lambda: printed(lab_pdb_session(coupon_debug_commands()), "discount", "67900"),
                        True,
                    ),
                    (
                        "showed the call stack",
                        lambda: any(
                            command.strip() in {"w", "where", "bt"} and "checkout()" in output
                            for command, output in lab_pdb_session(coupon_debug_commands())
                        ),
                        True,
                    ),
                    ("bug line", lambda: coupon_bug_report()[0], 6),
                    ("fixed script prints 61110", lambda: run_fixed_coupon(*coupon_bug_report()), "61110"),
                ]
            )
            try:
                for command, output in lab_pdb_session(coupon_debug_commands()):
                    print(
                        f"(Pdb) {command}\n{textwrap.indent(output.rstrip(), '      ')}"
                        if output.strip()
                        else f"(Pdb) {command}"
                    )
            except Exception as error:  # the transcript must never stop Run All
                print(f"(no session yet: {type(error).__name__})")
            '''
        ),
        md(
            """
            #### Exercise 7 — a 90%+ coverage suite for the Phase 2 model

            Write a test suite for `shop/inventory.py` (the Phase 2 model: `Product`,
            `StockMovement`, `Warehouse`, the repository, `EventBus` and `InventoryService`).
            Put every test function in `INVENTORY_TESTS`; you may include fixtures (for example
            your exercise 2 fixtures, which pytest will find in the same file). Requirements:
            at least 8 tests, all passing, **branch coverage of at least 90%** of
            `shop/inventory.py`, and the suite must catch two mutants: a low-stock alert sent on
            *every* sale at or below the reorder level (instead of only when the level is
            crossed), and adjustments that ignore their sign.
            """
        ),
        code(
            r"""
            def test_inventory_placeholder() -> None:
                raise NotImplementedError


            INVENTORY_TESTS = [test_inventory_placeholder]
            """
        ),
        md(
            "Check exercise 7 (this runs pytest with `--cov-branch` a few times; allow some seconds):"
        ),
        code(
            r"""
            INVENTORY_MUTANTS = {
                "alert on every low sale": (
                    "shop/inventory.py",
                    "if old_quantity > reorder_level >= new_quantity:",
                    "if reorder_level >= new_quantity:",
                ),
                "adjustment sign ignored": (
                    "shop/inventory.py",
                    "if self.movement_type is MovementType.ADJUSTED:\n                return self.quantity",
                    "if self.movement_type is MovementType.ADJUSTED:\n"
                    "                return abs(self.quantity)",
                ),
            }
            inventory_source = lab_test_source(INVENTORY_TESTS)


            def inventory_coverage_run() -> LabRun:
                return run_lab_tests(inventory_source, coverage_target="shop.inventory")


            run_checks(
                [
                    (
                        "at least 8 tests",
                        lambda: (
                            len(
                                [
                                    test
                                    for test in INVENTORY_TESTS
                                    if getattr(test, "__name__", "").startswith("test_")
                                ]
                            )
                            >= 8
                        ),
                        True,
                    ),
                    ("all tests pass", lambda: inventory_coverage_run().green, True),
                    (
                        "branch coverage >= 90%",
                        lambda: (inventory_coverage_run().coverage_percent or 0) >= 90,
                        True,
                    ),
                    *[
                        (
                            f"catches: {name}",
                            lambda mutation=mutation: catches(inventory_source, mutation),
                            True,
                        )
                        for name, mutation in INVENTORY_MUTANTS.items()
                    ],
                ]
            )
            try:
                print(f"branch coverage of shop/inventory.py: {inventory_coverage_run().coverage_percent}%")
            except Exception as error:  # never stop Run All
                print(f"coverage not measured: {type(error).__name__}")
            """
        ),
    ]


def _recap_cells() -> list[NotebookNode]:
    """Recap for Unit 4.3."""
    return [
        md(
            """
            ### Recap — Unit 4.3

            | Concept | One-line takeaway | Jest / JS equivalent |
            | --- | --- | --- |
            | Test pyramid, AAA | Many fast unit tests, fewer integration, few end-to-end; arrange, act once, assert | same |
            | pytest basics | `test_*` functions, plain `assert` (rewritten), `pytest.raises`, `pytest.approx`, `-k -x -v --lf -s` | `test`, `expect`, `toThrow`, `toBeCloseTo` |
            | Fixtures | Injected by parameter name; scopes; `yield` teardown; `conftest.py`; factories; `tmp_path`, `monkeypatch`, `capsys`, `caplog` | `beforeEach`/`afterEach` |
            | Parametrize, markers | One function, many cases with ids; `skip`, `skipif`, `xfail(strict=True)`, registered custom markers + `-m` | `test.each`, `test.skip`, tags |
            | Test doubles | Stubs and fakes check outcomes, mocks check interactions; `patch` where looked up; always `autospec`; inject clocks | `jest.fn`, `jest.mock`, fake timers |
            | Coverage | Branch coverage over line coverage; enforce a threshold; coverage shows execution, not verification | `--coverage` |
            | Hypothesis | Properties over generated inputs; failures shrink to minimal examples; pin them with `@example` | fast-check |
            | Debugging | `breakpoint()` + pdb commands, `PYTHONBREAKPOINT`, post-mortem (`python -m pdb`, `pdb.pm`, `%debug`, `--pdb`), `faulthandler` | `debugger;`, Chrome DevTools |
            | Logging | `getLogger(__name__)` everywhere, configure once with `dictConfig`; handlers, formatters, filters, propagation; `NullHandler` in libraries; lazy `%s`; JSON in production | `console.log`, pino, winston |
            | Quality gates | ruff (lint + format), pre-commit locally, the same checks in CI on every push | ESLint + Prettier, husky, GitHub Actions |

            **Further reading**

            - [`unittest.mock`](https://docs.python.org/3/library/unittest.mock.html),
              [`pdb`](https://docs.python.org/3/library/pdb.html),
              [`faulthandler`](https://docs.python.org/3/library/faulthandler.html),
              [`sys.monitoring`](https://docs.python.org/3/library/sys.monitoring.html)
            - [`logging`](https://docs.python.org/3/library/logging.html),
              [`logging.config`](https://docs.python.org/3/library/logging.config.html),
              [`logging.handlers`](https://docs.python.org/3/library/logging.handlers.html),
              [Logging HOWTO](https://docs.python.org/3/howto/logging.html),
              [Logging Cookbook](https://docs.python.org/3/howto/logging-cookbook.html)
            - [pytest documentation](https://docs.pytest.org/),
              [coverage.py](https://coverage.readthedocs.io/),
              [pytest-cov](https://pytest-cov.readthedocs.io/),
              [Hypothesis](https://hypothesis.readthedocs.io/)
            - [ruff rules](https://docs.astral.sh/ruff/rules/), [pre-commit](https://pre-commit.com/),
              [GitHub Actions for Python](https://docs.github.com/en/actions/use-cases-and-examples/building-and-testing/building-and-testing-python)
            - [PEP 282](https://peps.python.org/pep-0282/) (logging),
              [PEP 391](https://peps.python.org/pep-0391/) (`dictConfig`),
              [PEP 553](https://peps.python.org/pep-0553/) (`breakpoint()`),
              [PEP 669](https://peps.python.org/pep-0669/) (`sys.monitoring`),
              [PEP 768](https://peps.python.org/pep-0768/) (remote debugging)
            """
        ),
    ]


def cells() -> list[NotebookNode]:
    """Return the cells for Unit 4.3 and Lab 4.3."""
    return [
        *_overview_cells(),
        *_strategy_cells(),
        *_fundamentals_cells(),
        *_fixture_cells(),
        *_parametrize_cells(),
        *_double_cells(),
        *_coverage_cells(),
        *_hypothesis_cells(),
        *_debugging_cells(),
        *_logging_cells(),
        *_quality_gate_cells(),
        *_lab_intro_cells(),
        *_lab_exercise_cells(),
        *_lab_logging_debugging_cells(),
        *_recap_cells(),
    ]
