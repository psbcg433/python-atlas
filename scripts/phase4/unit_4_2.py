"""Unit 4.2 — The Type System (Python's TypeScript) (with Lab 4.2)."""

from nbformat import NotebookNode

from nb_builder import code, md, predict_cells

UNIT_SETUP_SOURCE = r'''
import annotationlib
import functools
import importlib.util
import inspect
import json
import linecache
import os
import re
import subprocess
import sys
import textwrap
import time
import typing
from collections.abc import Callable, Iterable, Mapping, Sequence  # noqa: F401  (lab hints use them)
from dataclasses import dataclass, field, fields
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Annotated, Literal

REPO_ROOT = find_repo_root()
scratch_dir = REPO_ROOT / "notebooks" / "_scratch"  # git-ignored
UNIT42_DIR = scratch_dir / "unit42"
UNIT42_DIR.mkdir(parents=True, exist_ok=True)
VENV_BIN = Path(sys.executable).parent
CHECKER_ENV = {
    **os.environ,
    "NO_COLOR": "1",
    "FORCE_COLOR": "0",
    "MYPY_FORCE_COLOR": "0",
    "PYTHON_COLORS": "0",
}
ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
PAISE = Decimal("0.01")


def write_demo(source: str, name: str, header: str = "") -> Path:
    """Write dedented source to <scratch>/<name>.py and return the path."""
    path = UNIT42_DIR / f"{name}.py"
    path.write_text(header + textwrap.dedent(source).lstrip("\n"))
    return path


def run_mypy(
    source: str, *, name: str = "demo", strict: bool = False, options: tuple[str, ...] = ()
) -> list[str]:
    """Type-check source with mypy in a child process; return its diagnostics, one per line."""
    mypy = VENV_BIN / "mypy"
    if not mypy.exists():
        return ["SKIP: mypy is not installed (uv add --dev mypy)"]
    path = write_demo(source, name)
    command = [
        str(mypy),
        "--no-error-summary",
        "--no-color-output",
        "--no-pretty",
        "--cache-dir",
        str(UNIT42_DIR / ".mypy_cache"),
        *(["--strict"] if strict else []),
        *options,
        path.name,
    ]
    completed = subprocess.run(
        command, cwd=UNIT42_DIR, capture_output=True, text=True, env=CHECKER_ENV, timeout=300
    )
    return (completed.stdout + completed.stderr).strip().splitlines()


def run_pyright(source: str, *, name: str = "demo", strict: bool = False) -> list[str]:
    """Type-check source with pyright (JSON output) in a child process; one line per finding."""
    pyright = VENV_BIN / "pyright"
    if not pyright.exists():
        return ["SKIP: pyright is not installed (uv add --dev pyright)"]
    path = write_demo(source, name, "# pyright: strict\n" if strict else "")
    completed = subprocess.run(
        [str(pyright), "--outputjson", "--pythonpath", sys.executable, path.name],
        cwd=UNIT42_DIR,
        capture_output=True,
        text=True,
        env=CHECKER_ENV,
        timeout=300,
    )
    try:
        report = json.loads(completed.stdout)
    except ValueError:
        return [
            f"SKIP: pyright did not run: {(completed.stderr or completed.stdout).strip()[:120]}"
        ]
    findings = []
    for diagnostic in report["generalDiagnostics"]:
        line_number = diagnostic["range"]["start"]["line"] + 1 - (1 if strict else 0)
        message = " ".join(part.strip() for part in diagnostic["message"].splitlines()[:2])
        rule = f"  [{diagnostic['rule']}]" if diagnostic.get("rule") else ""
        findings.append(f"{path.name}:{line_number}: {diagnostic['severity']}: {message}{rule}")
    return findings


def check(
    source: str,
    *,
    name: str = "demo",
    strict: bool = False,
    checkers: tuple[str, ...] = ("mypy", "pyright"),
) -> None:
    """Print what each checker reports for source (line numbers count from its first line)."""
    for checker in checkers:
        runner = run_mypy if checker == "mypy" else run_pyright
        findings = runner(source, name=name, strict=strict)
        print(f"{checker}{' (strict)' if strict else ''}:")
        print(textwrap.indent("\n".join(findings) or "no issues", "  "))


def source_of(obj: object) -> str:
    """Source code of a function or class, also for classes defined in a notebook cell."""
    try:
        return textwrap.dedent(inspect.getsource(obj))
    except OSError, TypeError:
        if not isinstance(obj, type):
            raise
    # inspect cannot find the file of a notebook class; use the file of one of its functions
    for member in vars(obj).values():
        member = getattr(member, "__func__", None) or getattr(member, "fget", None) or member
        code_object = getattr(inspect.unwrap(member), "__code__", None)
        lines = linecache.getlines(code_object.co_filename) if code_object else []
        if lines:
            start = obj.__firstlineno__ - 1
            while start > 0 and lines[start - 1].lstrip().startswith("@"):
                start -= 1
            return textwrap.dedent("".join(inspect.getblock(lines[start:])))
    # no functions (e.g. an exception class with only a docstring): search the cached cell sources
    header = re.compile(rf"\s*class\s+{obj.__name__}\b")
    for _size, _mtime, lines, _name in reversed(list(linecache.cache.values())):
        if len(lines) >= obj.__firstlineno__ and header.match(lines[obj.__firstlineno__ - 1]):
            return textwrap.dedent("".join(inspect.getblock(lines[obj.__firstlineno__ - 1 :])))
    raise OSError(f"source of {obj.__name__} not found")


LAB_PRELUDE = """
import functools
import typing
import re
import time
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Any, Literal, Self, cast, get_type_hints, overload, reveal_type

PAISE = Decimal("0.01")
"""


@functools.cache
def mypy_report(source: str, strict: bool = True) -> tuple[str, ...]:
    """mypy's lines for LAB_PRELUDE + source (cached: identical source is checked once)."""
    return tuple(run_mypy(LAB_PRELUDE + "\n\n" + source, name="lab_check", strict=strict))


def mypy_errors(*objects: object, strict: bool = True, extra: str = "") -> list[str]:
    """Error lines (no notes) mypy reports for the source of objects, plus extra code."""
    source = "\n\n".join([*(source_of(obj) for obj in objects), textwrap.dedent(extra)])
    return [
        line.split(": error: ", 1)[1] for line in mypy_report(source, strict) if ": error: " in line
    ]


def revealed_types(*objects: object, extra: str = "") -> list[str]:
    """The types mypy reveals for reveal_type(...) calls in extra (after the objects' source)."""
    source = "\n\n".join([*(source_of(obj) for obj in objects), textwrap.dedent(extra)])
    return re.findall(r'Revealed type is "([^"]+)"', "\n".join(mypy_report(source, True)))


def raised_error_name(thunk: Callable[[], object]) -> str:
    """Call thunk and return the name of the exception it raised, or "no error"."""
    try:
        thunk()
    except Exception as error:
        return type(error).__name__
    return "no error"


def raised_message(thunk: Callable[[], object]) -> str:
    """Call thunk and return "ErrorName: message" for the exception it raised, or "no error"."""
    try:
        thunk()
    except Exception as error:
        return f"{type(error).__name__}: {error}"
    return "no error"


for tool in ("mypy", "pyright"):
    found = VENV_BIN / tool
    if found.exists():
        version = subprocess.run([str(found), "--version"], capture_output=True, text=True).stdout
        print(f"{tool}: {version.strip()}")
    else:
        print(f"{tool}: not installed; checker cells will print a skip message")
'''


def _overview_cells() -> list[NotebookNode]:
    """Unit opener and setup."""
    return [
        md(
            """
            ## Unit 4.2 — The Type System (Python's TypeScript)

            **Objectives**

            - Explain gradual typing: what a type checker checks, what the interpreter ignores,
              and why Python classes are nominal while Protocols are structural.
            - Annotate variables, parameters, returns, class and constant attributes, and know
              when annotations are evaluated (*Changed in 3.14*).
            - Use collection, union, literal, `TypedDict`, `NewType`, `Self` and generic types;
              narrow unions so the checker can prove your code safe.
            - Type callables and decorators precisely (`ParamSpec`, `Concatenate`, `@overload`)
              and write your own narrowing functions (`TypeIs`).
            - Read type hints at run time (`Annotated`, `get_type_hints`) the way Pydantic and
              FastAPI do.
            - Run mypy and pyright in strict mode, configure them, and adopt them gradually.

            **TS bridge: Python's TypeScript**

            | TypeScript | Python | The difference that bites |
            | --- | --- | --- |
            | `tsc` (part of the toolchain) | mypy, pyright (separate tools) | **Python never refuses to run** badly typed code; the interpreter ignores hints |
            | Types erased at compile time | Annotations kept at run time as objects | Libraries (Pydantic, FastAPI, dataclasses) read them |
            | `let total: number = 0` | `total: int = 0` | `int` and `float` are different types (an `int` is accepted where `float` is expected) |
            | `string \\| null` (`strictNullChecks`) | `str \\| None` | Same idea; mypy always treats `None` strictly |
            | `any` | `Any` | Same: disables checking |
            | `unknown` | `object` | Must narrow before use |
            | `value as Product` | `cast(Product, value)` | Neither checks anything at run time |
            | `// @ts-expect-error` | `# type: ignore[code]` | Give the error code so other errors still show |
            | Structural typing everywhere | **Nominal** classes, structural `Protocol`s | A class with the right shape is *not* accepted unless you use a Protocol |
            | `interface Address { city: string; pin?: string }` | `class Address(TypedDict)` with `NotRequired` | `TypedDict` is only for dicts |
            | `"GET" \\| "POST"` | `Literal["GET", "POST"]` | Same |
            | `function first<T>(xs: T[]): T` | `def first[T](items: Sequence[T]) -> T` | PEP 695 syntax (3.12) |
            | `value is Product` (type predicate) | `-> TypeIs[Product]` | 3.13 |
            | `never` | `Never` / `NoReturn` | Same |
            | `readonly` | `Final`, `ReadOnly`, frozen dataclasses | Checked statically only |
            | `.d.ts`, DefinitelyTyped | `.pyi` stubs, typeshed, `types-*` packages | Same idea |
            | `"strict": true` in `tsconfig.json` | `mypy --strict`, pyright `strict` | Configure in `pyproject.toml` |

            **How the checker demos run.** The interpreter does not check types, so demos that
            show checker errors write a small file to `notebooks/_scratch/unit42/` and run the
            real mypy and/or pyright on it in a child process: `check(source)` prints both
            outputs. Line numbers count from the first line of the source string. Error codes
            in brackets (`[arg-type]`, `[reportArgumentType]`) are what you put in an ignore
            comment or search for in the docs.
            """
        ),
        code(UNIT_SETUP_SOURCE),
    ]


def _gradual_cells() -> list[NotebookNode]:
    """4.2.1 Gradual typing."""
    return [
        md(
            """
            ### 4.2.1 Gradual typing

            **PEP 484** (2014) defined the type-hint syntax and its meaning, but left checking to
            external tools. Three facts follow:

            1. **The interpreter ignores hints.** It stores them and moves on; a badly typed
               call runs (and maybe fails later, or silently does the wrong thing).
            2. **Static checkers** (mypy, pyright, and newer ones such as `ty` and Pyrefly)
               read the source without running it and report what cannot be proven safe.
            3. **Typing is gradual.** Unannotated code is treated as `Any`, so typed and untyped
               code mix freely and you can add hints one module at a time, like `allowJs` and
               `// @ts-check` in a JavaScript project moving to TypeScript.

            The interpreter runs this badly typed call without complaint:
            """
        ),
        code(
            r'''
            def label(sku: str, quantity: int) -> str:
                """Return a shelf label such as "3 x TEA-500"."""
                return f"{quantity} x {sku}"


            print(f"{label('TEA-500', 3)=}")
            print(f"{label(3, 'TEA-500')=}  (wrong order: runs anyway, wrong answer)")
            print(f"{label.__annotations__=}")
            '''
        ),
        md(
            "mypy, given the same code as a file, reports both swapped arguments before anything runs:"
        ),
        code(
            r'''
            check(
                """
                def label(sku: str, quantity: int) -> str:
                    return f"{quantity} x {sku}"

                label(3, "TEA-500")
                """,
                checkers=("mypy",),
            )
            '''
        ),
        md(
            """
            **Gradual means unannotated code is not checked (by default).** mypy skips the
            bodies of functions without annotations and treats their results as `Any`.
            `--strict` (or `--check-untyped-defs`) turns that off. pyright *infers* types inside
            unannotated functions, so it finds more even in its default mode.
            """
        ),
        code(
            r'''
            UNTYPED = """
            def legacy_total(items):
                return sum(item.price for item in items) + "INR"   # str + number: a bug

            def report(prices: list[float]) -> str:
                return legacy_total(prices)                        # Any: accepted silently
            """
            check(UNTYPED, name="untyped", checkers=("mypy",))
            check(UNTYPED, name="untyped", strict=True, checkers=("mypy",))
            check(UNTYPED, name="untyped", checkers=("pyright",))
            '''
        ),
        md(
            """
            **Nominal vs structural typing.** TypeScript is *structural*: any value with the
            right shape fits an interface or class type. Python classes are *nominal*: a
            parameter typed `Duck` accepts `Duck` and its subclasses only. For structural typing
            you opt in with a `typing.Protocol` (Unit 2.3.3).

            ```typescript
            class Duck  { quack(): string { return "Quack"; } }
            class Robot { quack(): string { return "Beep";  } }
            function makeNoise(duck: Duck) { return duck.quack(); }
            makeNoise(new Robot());   // OK in TypeScript: same shape
            ```
            """
        ),
        code(
            r'''
            check(
                """
                from typing import Protocol

                class Duck:
                    def quack(self) -> str:
                        return "Quack"

                class Robot:                      # same shape, unrelated class
                    def quack(self) -> str:
                        return "Beep"

                class Quacker(Protocol):          # structural: anything with quack() -> str
                    def quack(self) -> str: ...

                def make_noise(duck: Duck) -> str:
                    return duck.quack()

                def make_any_noise(quacker: Quacker) -> str:
                    return quacker.quack()

                make_noise(Robot())               # nominal: rejected
                make_any_noise(Robot())           # structural: accepted
                """,
                name="nominal",
                checkers=("mypy",),
            )
            '''
        ),
        *predict_cells(
            """
            def double(value: int) -> int:
                return value * 2

            print(double("ab"), double([0]))
            """,
            """
            `abab [0, 0]`. The interpreter never checks hints, and `*` works for strings and
            lists. mypy would report both calls (`[arg-type]`); at run time you only find out
            when the wrong result causes trouble somewhere else.
            """,
            """
            def double(value: int) -> int:
                return value * 2


            print(double("ab"), double([0]))
            """,
        ),
    ]


def _annotation_syntax_cells() -> list[NotebookNode]:
    """4.2.2 Annotation syntax."""
    return [
        md(
            """
            ### 4.2.2 Annotation syntax

            | Where | Syntax | TypeScript |
            | --- | --- | --- |
            | Variable | `retries: int = 3` | `let retries: number = 3` |
            | Declaration only | `customer_name: str` (no value: **no variable is created**) | `let customerName: string;` |
            | Parameter, default | `def ship(weight_kg: float, express: bool = False)` | `(weightKg: number, express = false)` |
            | `*args`, `**kwargs` | `*skus: str`, `**options: int` (type of **each** item) | `...skus: string[]` |
            | Return | `-> Decimal`, `-> None` | `: Decimal`, `: void` |
            | Class attribute shared by all instances | `TAX_RATE: ClassVar[Decimal]` | `static TAX_RATE: Decimal` |
            | Constant | `MAX_RETRIES: Final = 3` | `const MAX_RETRIES = 3` |
            """
        ),
        code(
            r'''
            retries: int = 3


            class CheckoutSettings:
                currency: str = "INR"
                customer_name: str  # annotation only: recorded, but no attribute is created


            def running_total() -> int:
                total: int  # annotation only: no local variable yet
                return total  # noqa: F821  (deliberate: no value was assigned)


            def ship(*skus: str, express: bool = False, **weights_kg: float) -> None:
                """Each sku is a str; each keyword argument value is a float."""


            print(f"{retries=}  {CheckoutSettings.__annotations__=}")
            print(f"{hasattr(CheckoutSettings, 'customer_name')=}")
            print(f"{raised_message(running_total)=}")
            print(f"{inspect.signature(ship)=}")
            print(f"{ship.__annotations__=}")
            '''
        ),
        md(
            """
            **`ClassVar` and `Final`.** `ClassVar` marks an attribute that belongs to the class,
            not to instances; dataclasses leave `ClassVar` fields out of `__init__`. `Final`
            marks a name that must not be re-bound (with no type given, the checker infers it
            from the value). Neither is enforced at run time:
            """
        ),
        code(
            r"""
            from typing import ClassVar, Final

            MAX_RETRIES: Final = 3


            @dataclass
            class InvoiceLine:
                TAX_RATE: ClassVar[Decimal] = Decimal("0.18")  # class-level, not a field
                description: str
                amount: Decimal


            line = InvoiceLine("Tea", Decimal("100"))
            print(f"{[f.name for f in fields(InvoiceLine)]=}  (TAX_RATE is not a field)")
            MAX_RETRIES = 5  # the interpreter allows it; the checker below does not
            print(f"{MAX_RETRIES=}")
            """
        ),
        code(
            r'''
            check(
                """
                from dataclasses import dataclass
                from decimal import Decimal
                from typing import ClassVar, Final

                MAX_RETRIES: Final = 3
                MAX_RETRIES = 5

                @dataclass
                class InvoiceLine:
                    TAX_RATE: ClassVar[Decimal] = Decimal("0.18")
                    description: str
                    amount: Decimal

                line = InvoiceLine("Tea", Decimal("100"))
                line.TAX_RATE = Decimal("0.05")
                """,
                name="classvar_final",
                checkers=("mypy",),
            )
            '''
        ),
        md(
            """
            **Deferred evaluation of annotations (PEP 649 / PEP 749, *Changed in 3.14*).** Until
            3.13, annotations were evaluated when the `def` or `class` statement ran, so a class
            could not mention a class defined later without quoting it (`"Customer"`) or using
            `from __future__ import annotations`. Since 3.14 the compiler stores annotations in
            a generated `__annotate__` function and evaluates them **only when someone asks**.
            Forward references just work, and modules that never read their annotations do not
            pay for them.
            """
        ),
        code(
            r"""
            class Order:
                customer: Customer  # defined further down: fine in 3.14+

                def ship_to(self) -> Address: ...


            print(f"{Order.__annotate__=}")
            print(f"{raised_message(lambda: Order.__annotations__)=}  (Customer does not exist yet)")
            """
        ),
        md(
            """
            The new standard-library module **`annotationlib`** (*New in 3.14*) reads
            annotations in three formats, so tools can cope with names that do not exist yet:

            | `Format` | Result for `customer: Customer` before `Customer` exists |
            | --- | --- |
            | `VALUE` (what `__annotations__` uses) | raises `NameError` |
            | `FORWARDREF` | real objects where possible, `ForwardRef('Customer')` otherwise |
            | `STRING` | the source text: `'Customer'` |
            """
        ),
        code(
            r"""
            from annotationlib import Format, get_annotations

            print(f"{get_annotations(Order, format=Format.FORWARDREF)=}")
            print(f"{get_annotations(Order, format=Format.STRING)=}")
            print(f"{get_annotations(Order.ship_to, format=Format.STRING)=}")


            class Customer:
                name: str


            print(f"{get_annotations(Order, format=Format.VALUE)=}  (now it resolves)")
            """
        ),
        md(
            """
            > **Note:** `from __future__ import annotations` (PEP 563, stringified annotations)
            > is no longer needed on 3.14+ and is expected to be deprecated. Libraries that read
            > annotations should call `annotationlib.get_annotations()` or
            > `typing.get_type_hints()` rather than touching `__annotations__` directly.
            """
        ),
    ]


def _collection_cells() -> list[NotebookNode]:
    """4.2.3 Collection types."""
    return [
        md(
            """
            ### 4.2.3 Collection types

            Built-in collections are generic since 3.9: subscript them with the element type.

            | Python | Means | TypeScript |
            | --- | --- | --- |
            | `list[int]` | list of ints | `number[]` |
            | `dict[str, list[User]]` | str keys, values are lists of `User` | `Record<string, User[]>` |
            | `set[str]`, `frozenset[str]` | sets of str | `Set<string>` |
            | `tuple[int, str]` | **exactly two** items: an int then a str | `[number, string]` |
            | `tuple[int, ...]` | **any number** of ints | `readonly number[]` |
            | `tuple[()]` | the empty tuple | `[]` |

            `typing.List`, `typing.Dict` and friends are deprecated aliases; ruff's `UP006`
            rewrites them. At run time, `list[int]` is a `types.GenericAlias` that remembers its
            arguments, but `isinstance` cannot check element types:
            """
        ),
        code(
            r"""
            @dataclass
            class User:
                name: str


            team_members: dict[str, list[User]] = {"backend": [User("Asha")], "frontend": []}
            alias = dict[str, list[User]]
            print(f"{type(alias).__name__=}  {typing.get_origin(alias)=}  {typing.get_args(alias)=}")
            print(f"{raised_message(lambda: isinstance(team_members, dict[str, list[User]]))=}")
            print(f"{typing.get_args(tuple[int, str])=}  {typing.get_args(tuple[int, ...])=}")
            """
        ),
        md("The checker does track element types and tuple lengths:"),
        code(
            r'''
            check(
                """
                from dataclasses import dataclass

                @dataclass
                class User:
                    name: str

                point: tuple[int, int] = (1, 2, 3)
                scores: tuple[int, ...] = (90, 85, 77)
                team_members: dict[str, list[User]] = {"backend": [User("Asha")]}
                team_members["frontend"] = User("Ravi")
                team_members["qa"].append("Meena")
                """,
                name="collections_demo",
                checkers=("mypy",),
            )
            '''
        ),
        md(
            """
            **Accept abstract types, return concrete ones.** A parameter typed `list[float]`
            rejects tuples, sets and generators even when the function only loops over it.
            Type parameters with the *least* you need from `collections.abc` and return a
            concrete type so callers get every method:

            | You only… | Accept | Accepts |
            | --- | --- | --- |
            | loop once | `Iterable[T]` | list, tuple, set, dict keys, generators, files |
            | need `len`, `in` and repeated loops | `Collection[T]` | list, tuple, set, dict views |
            | index or slice, read-only | `Sequence[T]` | list, tuple, str, range |
            | read a mapping | `Mapping[K, V]` | dict, `MappingProxyType`, `ChainMap` |
            | change it in place | `MutableSequence[T]`, `MutableMapping[K, V]` | list / dict |
            """
        ),
        code(
            r'''
            check(
                """
                from collections.abc import Iterable

                def total_strict(prices: list[float]) -> float:
                    return sum(prices)

                def total(prices: Iterable[float]) -> float:
                    return sum(prices)

                def prices_with_gst(prices: Iterable[float]) -> list[float]:
                    return [round(price * 1.18, 2) for price in prices]   # concrete result

                total_strict((10.0, 20.0))
                total((10.0, 20.0))
                total({10.0, 20.0})
                total(price for price in [10.0, 20.0])
                prices_with_gst((100.0,)).append(5.0)                     # list methods available
                """,
                name="abstract_params",
                checkers=("mypy",),
            )
            '''
        ),
        md("And at run time the `Iterable` version really does accept all of them:"),
        code(
            r'''
            def total(prices: Iterable[float]) -> float:
                """Sum any iterable of prices."""
                return sum(prices)


            print(total([10.0, 20.0]), total((10.0, 20.0)), total({10.0, 20.0}), total(p for p in [10.0, 20.0]))
            print(total({"tea": 120.5, "rice": 80.0}.values()))
            '''
        ),
    ]


def _union_cells() -> list[NotebookNode]:
    """4.2.4 Unions and narrowing."""
    return [
        md(
            """
            ### 4.2.4 Unions and narrowing

            `X | Y` (PEP 604, 3.10) means "an `X` or a `Y`"; `X | None` replaces
            `Optional[X]`. A union is only safe to use after **narrowing**: a check the checker
            understands, after which it knows the more precise type in each branch. These are
            the same ideas as TypeScript's control-flow analysis:

            | Python check | TypeScript equivalent | Narrows `str \\| None` / `int \\| str` to |
            | --- | --- | --- |
            | `if name is None: return` / `if name is not None:` | `if (name === null)` | `str` after the check |
            | `if isinstance(value, int):` | `typeof value === "number"` | `int` inside, `str` in `else` |
            | `match value:` + `case int():` | `switch` on `typeof` | per `case` |
            | `if name:` (truthiness) | `if (name)` | `str` (but `""` is excluded too) |
            | early `return` / `raise` / `continue` | same | the rest of the block |
            | `assert name is not None` | `name!` (non-null assertion) | `str` (checked at run time unless `-O`) |

            First the bug: `find_customer` may return `None`, and the caller forgets. Both
            checkers catch it.
            """
        ),
        code(
            r'''
            UNNARROWED = """
            def find_customer(customer_id: int) -> str | None:
                return {1: "Asha", 2: "Ravi"}.get(customer_id)

            def greeting(customer_id: int) -> str:
                name = find_customer(customer_id)
                return "Hello, " + name.upper()
            """
            check(UNNARROWED, name="unnarrowed")
            '''
        ),
        md(
            "At run time the bug only appears for a missing id, which is why the checker is worth having:"
        ),
        code(
            r'''
            def find_customer(customer_id: int) -> str | None:
                """Customer name, or None if unknown."""
                return {1: "Asha", 2: "Ravi"}.get(customer_id)


            def greeting(customer_id: int) -> str:
                """Unsafe: forgets that find_customer can return None."""
                name = find_customer(customer_id)
                return "Hello, " + name.upper()


            print(f"{greeting(1)=}")
            print(f"{raised_message(lambda: greeting(99))=}")
            '''
        ),
        md(
            """
            Three ways to narrow, each proven safe by both checkers. `reveal_type(x)` is a
            checker instruction: it prints the type the checker inferred at that point
            (mypy: `note: Revealed type is ...`, pyright: `information: Type of ...`).
            """
        ),
        code(
            r'''
            check(
                """
                def find_customer(customer_id: int) -> str | None:
                    return {1: "Asha", 2: "Ravi"}.get(customer_id)

                def greeting_is_none(customer_id: int) -> str:
                    name = find_customer(customer_id)
                    if name is None:
                        return "Hello, guest"
                    reveal_type(name)
                    return "Hello, " + name.upper()

                def describe(value: int | str) -> str:
                    if isinstance(value, int):
                        reveal_type(value)
                        return f"{value:,}"
                    reveal_type(value)
                    return value.strip()

                def describe_match(value: int | str | None) -> str:
                    match value:
                        case int():
                            return f"{value:,}"
                        case str():
                            return value.strip()
                        case None:
                            return "-"
                """,
                name="narrowed",
            )
            '''
        ),
        md(
            """
            **`Never`, `NoReturn` and `assert_never`.** `Never` (alias `NoReturn`, the
            conventional spelling for return types) is the empty type, TypeScript's `never`:

            - A function that always raises returns `NoReturn`; code after a call to it is
              unreachable, so it narrows like a `return`.
            - After every possibility of a union has been handled, the remaining type is
              `Never`. Passing the value to `assert_never()` (whose parameter is `Never`) makes
              the checker prove the `match` is **exhaustive**: add a new option and forget to
              handle it, and you get an error at that line.
            """
        ),
        code(
            r'''
            EXHAUSTIVE = """
            from typing import Literal, NoReturn, assert_never

            type Speed = Literal["standard", "express", "same_day"]   # "same_day" was just added

            def fail(message: str) -> NoReturn:
                raise ValueError(message)

            def delivery_days(speed: Speed) -> int:
                match speed:
                    case "standard":
                        return 5
                    case "express":
                        return 2
                    case _:
                        assert_never(speed)          # same_day is not handled

            def parse_days(text: str | None) -> int:
                if text is None:
                    fail("missing value")
                return int(text)                    # text is str here: fail() never returns
            """
            check(EXHAUSTIVE, name="exhaustive")
            '''
        ),
        md(
            """
            At run time `assert_never` raises `AssertionError`, a safety net for values the
            checker could not see (data from JSON, for example):
            """
        ),
        code(
            r'''
            from typing import Literal, Never, NoReturn, assert_never

            type Speed = Literal["standard", "express"]


            def delivery_days(speed: Speed) -> int:
                """Days to deliver; exhaustive over Speed."""
                match speed:
                    case "standard":
                        return 5
                    case "express":
                        return 2
                    case _:
                        assert_never(speed)


            print(f"{delivery_days('express')=}")
            print(f"{raised_message(lambda: delivery_days('drone'))=}")
            print(f"{NoReturn!r} vs {Never!r}: different objects at run time, the same type to checkers")
            '''
        ),
    ]


def _escape_hatch_cells() -> list[NotebookNode]:
    """4.2.5 Escape hatches."""
    return [
        md(
            """
            ### 4.2.5 Escape hatches

            | Hatch | Effect | TypeScript | Use it when |
            | --- | --- | --- | --- |
            | `Any` | Everything is allowed, in both directions; checking is off for that value | `any` | Truly dynamic data you will validate elsewhere; gradual migration |
            | `object` | Anything can be passed in, but **nothing** can be done with it until you narrow | `unknown` | "I accept anything" parameters (logging, serializers) |
            | `cast(T, value)` | Tells the checker "trust me, this is a `T`"; does nothing at run time | `value as T` | After a check the checker cannot follow |
            | `# type: ignore[code]` | Silences one error code on one line | `// @ts-expect-error` | Checker bugs, untyped third-party code |
            """
        ),
        code(
            r'''
            check(
                """
                import json
                from typing import Any, cast

                def log_any(value: Any) -> None:
                    print(value.upper())        # Any: no error, may crash at run time

                def log_object(value: object) -> None:
                    print(value.upper())        # object: error until narrowed

                def log_narrowed(value: object) -> None:
                    if isinstance(value, str):
                        print(value.upper())

                config = cast(dict[str, int], json.loads('{"retries": 3}'))
                reveal_type(json.loads("{}"))
                reveal_type(config)
                """,
                name="any_object",
                checkers=("mypy",),
            )
            '''
        ),
        md(
            """
            `cast` is a lie the interpreter does not check: it returns its argument unchanged.
            If the data does not match, the error appears later, far from the cause. Prefer
            narrowing with `isinstance` or validating with a library such as Pydantic
            (4.2.11).
            """
        ),
        code(
            r"""
            from typing import cast

            port = cast(int, "8080")  # the checker now believes port is an int
            print(f"{port=}  {type(port).__name__=}")
            print(f"{raised_message(lambda: port + 1)=}")
            """
        ),
        md(
            """
            **`# type: ignore[code]`.** Always give the error code: a bare `# type: ignore`
            hides every error on the line, including ones you introduce later. With
            `--warn-unused-ignores` mypy reports ignores that no longer suppress anything, and
            `--enable-error-code ignore-without-code` rejects bare ones (both are in `--strict`
            or recommended with it). pyright's own form is `# pyright: ignore[ruleName]`.
            """
        ),
        code(
            r'''
            check(
                """
                def parse_port(text: str) -> int:
                    return int(text)

                a: int = parse_port(8080)  # type: ignore[arg-type]
                b: int = parse_port(8080)  # type: ignore[assignment]
                c: int = parse_port("80")  # type: ignore[arg-type]
                d: int = parse_port(8080)  # type: ignore
                """,
                name="ignores",
                checkers=("mypy",),
            )
            STRICT_IGNORES = ("--warn-unused-ignores", "--enable-error-code", "ignore-without-code")
            print("mypy --warn-unused-ignores --enable-error-code ignore-without-code:")
            for finding in run_mypy(
                (UNIT42_DIR / "ignores.py").read_text(), name="ignores", options=STRICT_IGNORES
            ):
                print(f"  {finding}")
            '''
        ),
    ]


def _precise_type_cells() -> list[NotebookNode]:
    """4.2.6 Precise types."""
    return [
        md(
            """
            ### 4.2.6 Precise types

            | Type | Means | TypeScript |
            | --- | --- | --- |
            | `Literal["GET", "POST"]` | Only these exact values | `"GET" \\| "POST"` |
            | `LiteralString` | A `str` built only from literals in the source (no user input) | none (a "template literal" brand) |
            | `Final` | Never re-bound; with no type given, infers a literal type | `const` |
            | `NewType("UserId", int)` | A distinct type for the checker, a plain `int` at run time | branded types (`number & {__brand: "UserId"}`) |
            | `Self` | "The class of the current instance" (subclasses included) | `this` type |

            **`Literal` and `LiteralString`.** `LiteralString` (PEP 675) protects APIs such as
            SQL execution: only strings written in the source, or combined from such strings,
            are accepted, so an f-string with user input is rejected. pyright implements it;
            mypy currently treats `LiteralString` as plain `str`, a real difference between the
            two checkers:
            """
        ),
        code(
            r'''
            check(
                """
                from typing import Literal, LiteralString

                type Method = Literal["GET", "POST", "DELETE"]

                def request(method: Method, path: str) -> str:
                    return f"{method} {path}"

                def run_query(sql: LiteralString) -> None:
                    print(sql)

                request("GET", "/orders")
                request("PATCH", "/orders")

                def find_orders(customer: str) -> None:
                    run_query("SELECT * FROM orders WHERE customer = %s")      # literal: OK
                    run_query(f"SELECT * FROM orders WHERE customer = '{customer}'")
                """,
                name="literals",
            )
            '''
        ),
        md(
            """
            **`Final` infers literal types.** `TIMEOUT: Final = 30` has the type `Literal[30]`
            where it is used, so it can feed a `Literal`-typed parameter:
            """
        ),
        code(
            r'''
            check(
                """
                from typing import Final, Literal

                DEFAULT_PAGE_SIZE: Final = 20
                page_size = 20

                def fetch(size: Literal[10, 20, 50]) -> None: ...

                fetch(DEFAULT_PAGE_SIZE)     # Literal[20]: OK
                fetch(page_size)             # int: could be anything
                reveal_type(DEFAULT_PAGE_SIZE)
                """,
                name="final_literal",
                checkers=("mypy",),
            )
            '''
        ),
        md(
            """
            **`NewType` and `Self`.** `NewType` creates a distinct type for the checker (so a
            `UserId` cannot be passed where an `OrderId` is expected) at zero run-time cost: the
            "class" is an identity function. `Self` (3.11) types fluent APIs and alternative
            constructors so subclasses get their own type back.
            """
        ),
        code(
            r'''
            from typing import NewType, Self

            UserId = NewType("UserId", int)
            OrderId = NewType("OrderId", int)
            user_id = UserId(42)
            print(f"{user_id=}  {type(user_id).__name__=}  {user_id == 42=}  {UserId=}")


            class QueryBuilder:
                """Fluent builder: every method returns the builder itself."""

                def __init__(self) -> None:
                    self.conditions: list[str] = []

                def where(self, condition: str) -> Self:
                    self.conditions.append(condition)
                    return self


            class OrderQuery(QueryBuilder):
                def unpaid(self) -> Self:
                    return self.where("paid = false")


            query = OrderQuery().where("city = 'Pune'").unpaid()  # where() returned OrderQuery
            print(f"{type(query).__name__=}  {query.conditions=}")
            '''
        ),
        code(
            r'''
            check(
                """
                from typing import NewType, Self

                UserId = NewType("UserId", int)
                OrderId = NewType("OrderId", int)

                def cancel_order(order_id: OrderId) -> None: ...

                cancel_order(UserId(42))
                cancel_order(42)
                cancel_order(OrderId(42))

                class QueryBuilder:
                    def where(self, condition: str) -> Self:
                        return self

                class OrderQuery(QueryBuilder):
                    def unpaid(self) -> Self:
                        return self.where("paid = false")

                reveal_type(OrderQuery().where("city = 'Pune'"))
                """,
                name="newtype_self",
                checkers=("mypy",),
            )
            '''
        ),
        md(
            """
            **`TypedDict`** types dictionaries with a fixed set of string keys, such as JSON
            payloads. It is TypeScript's `interface` for objects that stay plain dicts:

            | Python | TypeScript |
            | --- | --- |
            | `class Address(TypedDict):` + `city: str` | `interface Address { city: string }` |
            | `pin: NotRequired[str]` | `pin?: string` |
            | `class Patch(TypedDict, total=False):` + `name: Required[str]` | all optional except `name` |
            | `sku: ReadOnly[str]` (PEP 705, *New in 3.13*) | `readonly sku: string` |
            | `def create(**fields: Unpack[ProductFields])` (PEP 692) | `function create(fields: ProductFields)` |

            At run time a `TypedDict` *is* a `dict`: no validation, no class instance. The
            class only records which keys are required, optional and read-only.
            """
        ),
        code(
            r'''
            from typing import NotRequired, ReadOnly, Required, TypedDict, Unpack


            class Address(TypedDict):
                city: str
                pin: NotRequired[str]


            class ProductPatch(TypedDict, total=False):
                sku: Required[ReadOnly[str]]
                name: str
                price: Decimal


            def update_product(**changes: Unpack[ProductPatch]) -> dict[str, object]:
                """Apply a partial update; keyword arguments are checked against ProductPatch."""
                return dict(changes)


            home: Address = {"city": "Pune"}
            print(f"{home=}  {type(home).__name__=}")
            print(f"{Address.__required_keys__=}  {Address.__optional_keys__=}")
            print(f"{ProductPatch.__required_keys__=}  {ProductPatch.__readonly_keys__=}")
            print(f"{update_product(sku='TEA-500', price=Decimal('120.50'))=}")
            '''
        ),
        md("The checker enforces the keys, their types, read-only keys and the `**kwargs` names:"),
        code(
            r'''
            check(
                """
                from decimal import Decimal
                from typing import NotRequired, ReadOnly, Required, TypedDict, Unpack

                class Address(TypedDict):
                    city: str
                    pin: NotRequired[str]

                class ProductPatch(TypedDict, total=False):
                    sku: Required[ReadOnly[str]]
                    name: str
                    price: Decimal

                def update_product(**changes: Unpack[ProductPatch]) -> None: ...

                office: Address = {"pin": "411001"}                   # city missing
                shop: Address = {"city": "Pune", "zip": "411001"}     # unknown key
                patch: ProductPatch = {"sku": "TEA-500", "name": "Tea"}
                patch["sku"] = "TEA-1KG"                             # read-only
                update_product(sku="TEA-500", colour="green")        # unknown keyword
                update_product(price=99)                             # sku missing, int is not Decimal
                """,
                name="typed_dicts",
                checkers=("mypy",),
            )
            '''
        ),
    ]


def _generic_cells() -> list[NotebookNode]:
    """4.2.7 Generics."""
    return [
        md(
            """
            ### 4.2.7 Generics

            **PEP 695 syntax** (3.12) declares type parameters in square brackets right after
            the name, like TypeScript's angle brackets:

            | Python 3.12+ | TypeScript |
            | --- | --- |
            | `def first[T](items: Sequence[T]) -> T:` | `function first<T>(items: T[]): T` |
            | `class Stack[T]:` | `class Stack<T>` |
            | `type Pair[T] = tuple[T, T]` | `type Pair<T> = [T, T]` |
            | `[T: Hashable]` (bound) | `<T extends Hashable>` |
            | `[T: (int, float)]` (constraints) | `<T extends number \\| bigint>`, roughly |
            | `[T = str]` (default, PEP 696, 3.13) | `<T = string>` |

            Type parameters are real objects at run time, available as `__type_params__`:
            """
        ),
        code(
            r'''
            def first[T](items: Sequence[T]) -> T:
                """The first item; the result has the element type of the sequence."""
                return items[0]


            class Stack[T]:
                """A last-in, first-out stack of T."""

                def __init__(self) -> None:
                    self._items: list[T] = []

                def push(self, item: T) -> None:
                    self._items.append(item)


            type Pair[T] = tuple[T, T]

            print(f"{first.__type_params__=}  {Stack.__type_params__=}")
            print(f"{Stack[int]=}  {typing.get_args(Stack[int])=}")
            print(f"{type(Pair).__name__=}  {Pair.__value__=}  {Pair[float]=}")
            '''
        ),
        md(
            """
            `type` aliases are evaluated lazily (`__value__` is computed on first access), so
            they can be **recursive**: the classic JSON type needs no quotes.
            """
        ),
        code(
            r'''
            type Json = dict[str, Json] | list[Json] | str | int | float | bool | None


            def count_leaves(value: Json) -> int:
                """Number of non-container values in a JSON document."""
                if isinstance(value, dict):
                    return sum(count_leaves(item) for item in value.values())
                if isinstance(value, list):
                    return sum(count_leaves(item) for item in value)
                return 1


            print(f"{count_leaves({'order': {'id': 7, 'lines': [1, 2, {'sku': 'TEA'}]}, 'paid': True})=}")
            print(f"{Json.__value__=}")
            '''
        ),
        md(
            """
            **Bounds vs constraints, and defaults.** A *bound* `[T: Base]` accepts `Base` or any
            subtype and keeps the exact type (`bool` stays `bool`). *Constraints*
            `[T: (int, str)]` mean `T` is exactly one of the listed types (a `bool` is solved
            as `int`). A *default* (PEP 696, *New in 3.13*) is used when the parameter is not
            given, which is how `Generator[int]` can omit its other two parameters.
            """
        ),
        code(
            r'''
            check(
                """
                from collections.abc import Hashable, Sequence

                def bounded[T: int](value: T) -> T:
                    return value

                def constrained[T: (int, str)](value: T) -> T:
                    return value

                def dedupe[T: Hashable](items: Sequence[T]) -> list[T]:
                    return list(dict.fromkeys(items))

                class Page[T = dict[str, object]]:
                    def __init__(self, items: list[T]) -> None:
                        self.items = items

                def plain_page() -> Page:
                    return Page([])

                reveal_type(bounded(True))
                reveal_type(constrained(True))
                reveal_type(dedupe(["a", "b", "a"]))
                dedupe([[1], [2]])
                reveal_type(plain_page().items)
                """,
                name="bounds",
                checkers=("mypy",),
            )
            '''
        ),
        code(
            r'''
            class Page[T = dict[str, object]]:
                """A page of results; items default to JSON-like dicts."""


            (page_param,) = Page.__type_params__
            print(f"{page_param.has_default()=}  {page_param.__default__=}")


            def dedupe[T: typing.Hashable](items: Sequence[T]) -> list[T]:
                """Drop repeated items, keeping the first of each."""
                return list(dict.fromkeys(items))


            (dedupe_param,) = dedupe.__type_params__
            print(f"{dedupe_param.__bound__=}  {dedupe([3, 1, 3, 2, 1])=}")
            '''
        ),
        md(
            """
            **Variance** answers: if `bool` is a subtype of `int`, is `Box[bool]` a subtype of
            `Box[int]`?

            | Variance | Rule | Examples | Why |
            | --- | --- | --- | --- |
            | Covariant | `Box[bool]` **is** a `Box[int]` | `Sequence`, `tuple`, `frozenset`, `Mapping` values, read-only classes | You can only *read* `int`s out of it |
            | Invariant | No relation | `list`, `dict`, `set`, mutable classes | Someone could *write* an `int` into your list of `bool`s |
            | Contravariant | `Handler[int]` **is** a `Handler[bool]` | `Callable` parameters, write-only sinks | Something that handles any `int` can handle a `bool` |

            TypeScript checks method parameters *bivariantly* (unsound on purpose); Python
            checkers are strict here. With PEP 695 syntax the checker **infers** variance from
            how the class uses `T`.
            """
        ),
        code(
            r'''
            check(
                """
                from collections.abc import Sequence
                from dataclasses import dataclass

                def average(values: list[float]) -> float:
                    return sum(values) / len(values)

                def average_ro(values: Sequence[float]) -> float:
                    return sum(values) / len(values)

                flags: list[bool] = [True, False]
                ints: list[int] = [1, 2, 3]
                average(ints)          # list is invariant
                average_ro(ints)       # Sequence is covariant

                @dataclass(frozen=True)
                class ReadOnlyBox[T]:  # only reads T: inferred covariant
                    item: T

                class Box[T]:          # reads and writes T: inferred invariant
                    def __init__(self, item: T) -> None:
                        self.item = item

                def open_int_box(box: ReadOnlyBox[int]) -> int:
                    return box.item

                def open_mutable(box: Box[int]) -> int:
                    return box.item

                open_int_box(ReadOnlyBox(True))
                bool_box: Box[bool] = Box(True)
                open_mutable(bool_box)
                """,
                name="variance",
                checkers=("mypy",),
            )
            '''
        ),
        md(
            """
            **The old `TypeVar` syntax** is what you will read in most existing code (and still
            write when supporting Python ≤ 3.11). Same meaning, more ceremony: the type variable
            is a module-level object, classes inherit from `Generic[T]`, and variance must be
            declared by hand. ruff's `UP046`/`UP047` rewrite it to PEP 695 syntax for
            `target-version = "py312"` and later, hence the `noqa` comments.
            """
        ),
        code(
            r'''
            from typing import Generic, TypeVar

            T = TypeVar("T")
            T_co = TypeVar("T_co", covariant=True)
            Number = TypeVar("Number", int, float)  # constraints
            AnyStr_ = TypeVar("AnyStr_", bound=str | bytes)  # bound


            class OldBox(Generic[T]):  # noqa: UP046
                def __init__(self, item: T) -> None:
                    self.item = item


            def old_first(items: Sequence[T]) -> T:  # noqa: UP047
                """Same as first[T], old spelling."""
                return items[0]


            print(f"{OldBox.__parameters__=}  {OldBox[int]=}")
            print(f"{T_co.__covariant__=}  {Number.__constraints__=}  {AnyStr_.__bound__=}")
            new_param = Stack.__type_params__[0]
            print(f"PEP 695 parameter: {new_param!r}, infer variance: {new_param.__infer_variance__}")
            '''
        ),
    ]


def _callable_cells() -> list[NotebookNode]:
    """4.2.8 Callable types."""
    return [
        md(
            """
            ### 4.2.8 Callable types

            | Python | TypeScript |
            | --- | --- |
            | `Callable[[int, str], bool]` | `(a: number, b: string) => boolean` |
            | `Callable[..., Decimal]` | `(...args: any[]) => Decimal` |
            | `Callable[[], None]` | `() => void` |
            | callback `Protocol` with `__call__` | call signature in an interface: `{ (amount: Decimal): Decimal }` |

            `Callable` cannot describe keyword names, defaults or overloads. For those, write a
            **callback Protocol**: a Protocol whose `__call__` has the exact signature.
            """
        ),
        code(
            r'''
            check(
                """
                from collections.abc import Callable
                from decimal import Decimal
                from typing import Protocol

                class PriceRule(Protocol):
                    def __call__(self, amount: Decimal, *, tier: str = "basic") -> Decimal: ...

                def ten_percent_off(amount: Decimal, *, tier: str = "basic") -> Decimal:
                    return amount * Decimal("0.9")

                def wrong_keyword(amount: Decimal, *, level: str = "basic") -> Decimal:
                    return amount

                def simple(amount: Decimal) -> Decimal:
                    return amount

                def apply(rule: PriceRule, amount: Decimal) -> Decimal:
                    return rule(amount, tier="gold")

                def apply_simple(rule: Callable[[Decimal], Decimal], amount: Decimal) -> Decimal:
                    return rule(amount)

                apply(ten_percent_off, Decimal("100"))
                apply(wrong_keyword, Decimal("100"))
                apply(simple, Decimal("100"))
                apply_simple(simple, Decimal("100"))
                apply_simple(len, Decimal("100"))
                """,
                name="callables",
                checkers=("mypy",),
            )
            '''
        ),
        md(
            """
            **`ParamSpec`: decorators that keep the signature.** A decorator typed with
            `Callable[..., Any]` erases what it wraps: callers lose argument checking and the
            return type becomes `Any`. `[**P, R]` captures the wrapped function's parameters as
            `P` and its return type as `R`, so the wrapper keeps both (Unit 1.12 used this
            spelling already).
            """
        ),
        code(
            r'''
            check(
                """
                import functools
                from collections.abc import Callable
                from typing import Any

                def logged_loose(func: Callable[..., Any]) -> Callable[..., Any]:
                    def wrapper(*args: Any, **kwargs: Any) -> Any:
                        return func(*args, **kwargs)
                    return wrapper

                def logged[**P, R](func: Callable[P, R]) -> Callable[P, R]:
                    @functools.wraps(func)
                    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                        print(f"calling {func.__name__}")
                        return func(*args, **kwargs)
                    return wrapper

                @logged_loose
                def price_loose(sku: str, quantity: int = 1) -> float:
                    return 10.0 * quantity

                @logged
                def price(sku: str, quantity: int = 1) -> float:
                    return 10.0 * quantity

                price_loose(42)            # not caught
                price(42)                  # caught
                reveal_type(price)
                reveal_type(price_loose("TEA"))
                """,
                name="paramspec",
                checkers=("mypy",),
            )
            '''
        ),
        md(
            """
            **`Concatenate`** describes a decorator that **adds or removes** leading
            parameters. A classic case is dependency injection: the decorated function takes a
            connection as its first parameter, and the wrapper supplies it, so callers do not.
            Decorator *factories* (decorators with arguments) just add one more layer:
            `def retry(times: int) -> Callable[[Callable[P, R]], Callable[P, R]]`, which is
            Lab 4.2 exercise 3.
            """
        ),
        code(
            r'''
            from typing import Concatenate


            class Connection:
                def execute(self, sql: str) -> list[tuple[object, ...]]:
                    return [(sql.split()[-1], 1)]


            def with_connection[**P, R](func: Callable[Concatenate[Connection, P], R]) -> Callable[P, R]:
                """Supply a fresh Connection as the first argument."""

                @functools.wraps(func)
                def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                    return func(Connection(), *args, **kwargs)

                return wrapper


            @with_connection
            def count_orders(connection: Connection, city: str) -> int:
                return len(connection.execute(f"SELECT 1 FROM orders WHERE city = {city}"))


            print(f"{count_orders('Pune')=}  {inspect.signature(count_orders)=}")
            '''
        ),
        md(
            """
            Note that `inspect.signature` (which follows `__wrapped__`) still shows the original
            parameters; only the checker knows the connection parameter was removed. mypy
            agrees with the run-time behaviour:
            """
        ),
        code(
            r'''
            check(
                """
                import functools
                from collections.abc import Callable
                from typing import Concatenate

                class Connection: ...

                def with_connection[**P, R](func: Callable[Concatenate[Connection, P], R]) -> Callable[P, R]:
                    @functools.wraps(func)
                    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                        return func(Connection(), *args, **kwargs)
                    return wrapper

                @with_connection
                def count_orders(connection: Connection, city: str) -> int:
                    return 1

                reveal_type(count_orders)
                count_orders("Pune")
                count_orders(Connection(), "Pune")
                """,
                name="concatenate",
                checkers=("mypy",),
            )
            '''
        ),
        md(
            """
            **`@overload`** declares several signatures for one function when the return type
            depends on the argument types (TypeScript function overloads). The `@overload`
            stubs are for the checker only; the last, undecorated definition is the real
            implementation. `typing.get_overloads()` (3.11) lists them at run time.
            """
        ),
        code(
            r'''
            from typing import get_overloads, overload


            @overload
            def parse_amount(raw: str) -> Decimal: ...
            @overload
            def parse_amount(raw: None) -> None: ...
            def parse_amount(raw: str | None) -> Decimal | None:
                """Parse "1,234.50" into Decimal; None stays None."""
                return None if raw is None else Decimal(raw.replace(",", ""))


            print(f"{parse_amount('1,234.50')=}  {parse_amount(None)=}")
            print(f"{len(get_overloads(parse_amount))=}")
            check(
                """
                from decimal import Decimal
                from typing import overload

                @overload
                def parse_amount(raw: str) -> Decimal: ...
                @overload
                def parse_amount(raw: None) -> None: ...
                def parse_amount(raw: str | None) -> Decimal | None:
                    return None if raw is None else Decimal(raw.replace(",", ""))

                reveal_type(parse_amount("1,234.50"))
                reveal_type(parse_amount(None))
                parse_amount(12)
                """,
                name="overloads",
                checkers=("mypy",),
            )
            '''
        ),
    ]


def _class_typing_cells() -> list[NotebookNode]:
    """4.2.9 Class typing."""
    return [
        md(
            """
            ### 4.2.9 Class typing

            | Tool | Means | TypeScript |
            | --- | --- | --- |
            | `type[Product]` | The class `Product` itself (or a subclass), not an instance | `typeof Product` / `new () => Product` |
            | `@override` (PEP 698, 3.12) | "This method overrides a base method"; error if it does not | `override` keyword |
            | `@final` on a class | Must not be subclassed | none (`sealed` in C#) |
            | `@final` on a method | Must not be overridden | none |
            | `class Repository[T](Protocol)` | A generic structural interface | `interface Repository<T>` |

            At run time `@override` and `@final` only set a marker attribute (`__override__`,
            `__final__`); the checker enforces them.
            """
        ),
        code(
            r'''
            from typing import final, override


            class Model:
                def describe(self) -> str:
                    return f"{type(self).__name__} stored in {type(self).__name__.lower()}s"


            class Product(Model):
                @override
                def describe(self) -> str:
                    return "Product stored in the catalogue"


            def create[M: Model](model_class: type[M]) -> M:
                """Instantiate any Model subclass; the result has that subclass's type."""
                return model_class()


            @final
            class Money: ...


            print(f"{create(Product).describe()=}  {create(Model).describe()=}")
            print(f"{Product.describe.__override__=}  {Money.__final__=}")
            '''
        ),
        md("A generic Protocol plus the class-typing errors the checker reports:"),
        code(
            r'''
            check(
                """
                from typing import Protocol, final, override

                class Repository[T](Protocol):
                    def get(self, key: str) -> T | None: ...
                    def add(self, key: str, item: T) -> None: ...

                class InMemoryRepository[T]:
                    def __init__(self) -> None:
                        self._items: dict[str, T] = {}
                    def get(self, key: str) -> T | None:
                        return self._items.get(key)
                    def add(self, key: str, item: T) -> None:
                        self._items[key] = item

                def restock(repository: Repository[int], sku: str) -> None:
                    repository.add(sku, (repository.get(sku) or 0) + 10)

                restock(InMemoryRepository[int](), "TEA-500")
                restock(InMemoryRepository[str](), "TEA-500")

                class Shipment:
                    def cost(self) -> int:
                        return 50
                    @final
                    def tracking_id(self) -> str:
                        return "TRK-1"

                class Express(Shipment):
                    @override
                    def costs(self) -> int:       # typo: overrides nothing
                        return 120
                    def tracking_id(self) -> str:  # overrides a final method
                        return "EXP-1"

                @final
                class Money: ...

                class Rupees(Money): ...

                def build(kind: type[Shipment]) -> Shipment:
                    return kind()

                build(Express)
                build(Money)
                """,
                name="class_typing",
                checkers=("mypy",),
            )
            '''
        ),
    ]


def _custom_narrowing_cells() -> list[NotebookNode]:
    """4.2.10 Custom narrowing."""
    return [
        md(
            """
            ### 4.2.10 Custom narrowing

            When a check is too complex for the checker to follow, write a function that
            returns `bool` and tell the checker what `True` means:

            | | `TypeGuard[T]` (PEP 647, 3.10) | `TypeIs[T]` (PEP 742, *New in 3.13*) |
            | --- | --- | --- |
            | Narrows when `True` | to `T` | to `T` (intersected with the input type) |
            | Narrows when `False` | no | **yes**: to "input type minus `T`" |
            | `T` must be a subtype of the input type | no (can narrow `list[object]` to `list[str]`) | yes |
            | TypeScript | | `function isProduct(x: unknown): x is Product` |

            Prefer `TypeIs`; use `TypeGuard` only for narrowing to a non-subtype, typically a
            container whose element type you checked.
            """
        ),
        code(
            r'''
            from typing import TypeGuard, TypeIs


            def is_str_list(values: list[object]) -> TypeGuard[list[str]]:
                """True if every item is a str."""
                return all(isinstance(value, str) for value in values)


            def is_decimal(value: object) -> TypeIs[Decimal]:
                """True if value is a Decimal."""
                return isinstance(value, Decimal)


            print(f"{is_str_list(['a', 'b'])=}  {is_str_list(['a', 1])=}  {is_decimal(Decimal('1'))=}")
            check(
                """
                from decimal import Decimal
                from typing import TypeGuard, TypeIs

                def is_str_list(values: list[object]) -> TypeGuard[list[str]]:
                    return all(isinstance(value, str) for value in values)

                def is_decimal(value: object) -> TypeIs[Decimal]:
                    return isinstance(value, Decimal)

                def handle(values: list[object], amount: Decimal | float) -> None:
                    if is_str_list(values):
                        reveal_type(values)
                    if is_decimal(amount):
                        reveal_type(amount)
                    else:
                        reveal_type(amount)     # TypeIs also narrows the else branch
                """,
                name="type_is",
                checkers=("mypy",),
            )
            '''
        ),
        md(
            """
            **Discriminated (tagged) unions.** Give every member of a union a field with a
            different `Literal` value; checking that field narrows to one member. This is
            exactly TypeScript's tagged union (`type Event = {kind: "paid", …} | {kind: …}`),
            and it combines with `match` and `assert_never` for exhaustiveness. It works with
            dataclasses, `TypedDict`s and Pydantic models.
            """
        ),
        code(
            r'''
            @dataclass(frozen=True)
            class Paid:
                order_id: int
                amount: Decimal
                kind: Literal["paid"] = "paid"


            @dataclass(frozen=True)
            class Refunded:
                order_id: int
                reason: str
                kind: Literal["refunded"] = "refunded"


            type PaymentEvent = Paid | Refunded


            def describe_event(event: PaymentEvent) -> str:
                """One line per event; exhaustive over the tag."""
                match event.kind:
                    case "paid":
                        return f"order {event.order_id}: paid INR {event.amount}"
                    case "refunded":
                        return f"order {event.order_id}: refunded ({event.reason})"


            for event in (Paid(7, Decimal("499")), Refunded(8, "damaged")):
                print(describe_event(event))
            '''
        ),
        code(
            r'''
            check(
                """
                from dataclasses import dataclass
                from typing import Literal, TypedDict, assert_never

                class CardPayment(TypedDict):
                    method: Literal["card"]
                    last4: str

                class UpiPayment(TypedDict):
                    method: Literal["upi"]
                    vpa: str

                class CashPayment(TypedDict):
                    method: Literal["cash"]

                type Payment = CardPayment | UpiPayment | CashPayment

                def receipt_line(payment: Payment) -> str:
                    if payment["method"] == "card":
                        reveal_type(payment)
                        return f"card ending {payment['last4']}"
                    if payment["method"] == "upi":
                        return f"UPI {payment['vpa']}"
                    reveal_type(payment)
                    return payment["vpa"]            # a cash payment has no vpa
                """,
                name="tagged_unions",
                checkers=("mypy",),
            )
            '''
        ),
    ]


def _annotated_cells() -> list[NotebookNode]:
    """4.2.11 Annotated and runtime introspection."""
    return [
        md(
            """
            ### 4.2.11 `Annotated` and runtime introspection

            `Annotated[T, metadata, ...]` (PEP 593) attaches arbitrary objects to a type. The
            **checker sees only `T`**; libraries read the metadata at run time. This is how
            Pydantic expresses constraints (`Annotated[int, Field(gt=0)]`) and how FastAPI
            declares where a parameter comes from (`Annotated[str, Query(max_length=50)]`,
            `Annotated[Session, Depends(get_session)]`, Phase 6). TypeScript has no run-time
            types at all, which is why JS libraries such as Zod define schemas as values
            instead.

            | Function | Returns |
            | --- | --- |
            | `typing.get_type_hints(obj)` | Evaluated hints, `Annotated` **stripped** |
            | `typing.get_type_hints(obj, include_extras=True)` | Evaluated hints with `Annotated` kept |
            | `typing.get_origin(tp)` | The unsubscripted form: `list` for `list[int]`, `Annotated` for `Annotated[...]`, `types.UnionType` for `X \\| Y` |
            | `typing.get_args(tp)` | The arguments: `(int,)`, `(int, Range(0, 150))`, … |
            """
        ),
        code(
            r"""
            from typing import Annotated, get_args, get_origin, get_type_hints


            @dataclass(frozen=True)
            class Range:
                minimum: int
                maximum: int


            @dataclass
            class Signup:
                name: Annotated[str, "display name"]
                age: Annotated[int, Range(18, 120)]
                referral: str | None = None


            print(f"{get_type_hints(Signup)=}")
            hints = get_type_hints(Signup, include_extras=True)
            print(f"{hints['age']=}")
            print(f"{get_origin(hints['age']) is Annotated=}  {get_args(hints['age'])=}")
            print(f"{hints['age'].__metadata__=}")
            print(f"{get_origin(hints['referral'])=}  {get_args(hints['referral'])=}")
            """
        ),
        md(
            """
            **Under the hood: a mini validator.** Reading the metadata is all a framework does
            before deciding what to check. Lab 4.2 exercise 7 builds a complete one; this cell
            only walks a function's parameters:
            """
        ),
        code(
            r'''
            def constraints_of(function: Callable[..., object]) -> dict[str, list[object]]:
                """Parameter name -> metadata objects found in Annotated hints."""
                found: dict[str, list[object]] = {}
                for name, hint in get_type_hints(function, include_extras=True).items():
                    if get_origin(hint) is Annotated:
                        found[name] = list(hint.__metadata__)
                return found


            def register(name: Annotated[str, "1-40 chars"], age: Annotated[int, Range(18, 120)]) -> None:
                """Register a customer (the metadata is for a framework to enforce)."""


            print(constraints_of(register))
            print(f"{inspect.signature(register).parameters['age'].annotation=}")
            '''
        ),
        md(
            """
            **Pydantic** turns hints plus `Annotated` metadata into a validator and parser
            (Unit 4.6 and Phase 6 go deeper). Constraints from `Field(...)` and from the
            `annotated-types` library (`Gt`, `Len`, …) both work:
            """
        ),
        code(
            r"""
            if importlib.util.find_spec("pydantic") is None:
                print("SKIP: pydantic is not installed (uv add pydantic)")
            else:
                from annotated_types import Len
                from pydantic import BaseModel, Field, ValidationError

                class SignupModel(BaseModel):
                    name: Annotated[str, Len(1, 40)]
                    age: Annotated[int, Field(ge=18, le=120)]
                    referral: str | None = None

                print(SignupModel(name="Asha", age="31"))  # "31" is parsed to 31
                try:
                    SignupModel(name="", age=12)
                except ValidationError as error:
                    for problem in error.errors():
                        print(f"  {problem['loc'][0]}: {problem['msg']}")
            """
        ),
        md(
            """
            FastAPI (Phase 6) reads the same structure to wire HTTP requests to functions:

            ```python
            from typing import Annotated
            from fastapi import Depends, FastAPI, Query

            app = FastAPI()

            @app.get("/orders")
            def list_orders(
                city: Annotated[str, Query(max_length=40)],          # from ?city=...
                session: Annotated[Session, Depends(get_session)],   # injected
            ) -> list[Order]: ...
            ```
            """
        ),
        *predict_cells(
            """
            from typing import Annotated, get_type_hints

            def ship(weight: Annotated[float, "kg"]) -> None: ...

            print(get_type_hints(ship))
            print(ship.__annotations__["weight"] == Annotated[float, "kg"])
            """,
            """
            `{'weight': <class 'float'>, 'return': <class 'NoneType'>}` then `True`.
            `get_type_hints` strips `Annotated` unless you pass `include_extras=True`, and it
            turns the `None` return annotation into `NoneType`. `__annotations__` holds the raw
            objects, and `Annotated` aliases compare equal when their type and metadata match.
            """,
            """
            from typing import Annotated, get_type_hints


            def ship(weight: Annotated[float, "kg"]) -> None: ...


            print(get_type_hints(ship))
            print(ship.__annotations__["weight"] == Annotated[float, "kg"])
            """,
        ),
    ]


def _running_checker_cells() -> list[NotebookNode]:
    """4.2.12 Running checkers."""
    return [
        md(
            """
            ### 4.2.12 Running checkers

            | | mypy | pyright |
            | --- | --- | --- |
            | Written in | Python (compiled with mypyc) | TypeScript (runs on Node.js; powers VS Code's Pylance) |
            | Install | `uv add --dev mypy` | `uv add --dev pyright` (downloads Node if needed) |
            | Default mode | Skips unannotated functions | Checks everything, infers inside untyped code |
            | Strict mode | `--strict` or `strict = true` | `typeCheckingMode = "strict"` or `# pyright: strict` |
            | Config | `[tool.mypy]` (+ `[[tool.mypy.overrides]]`) | `[tool.pyright]` or `pyrightconfig.json` |
            | Plugins | Yes (Django, Pydantic, SQLAlchemy) | No (relies on standard typing features) |
            | TypeScript equivalent | `tsc --noEmit` with `"strict": true` in `tsconfig.json` | the same, and pyright is what VS Code runs as you type (like the TS language server) |

            `--strict` is a bundle of flags; mypy lists them in its help:
            """
        ),
        code(
            r"""
            help_text = subprocess.run(
                [str(VENV_BIN / "mypy"), "--help"], capture_output=True, text=True, env=CHECKER_ENV
            ).stdout
            help_text = ANSI_ESCAPE.sub("", help_text)  # Python 3.14+ argparse can colour its help
            strict_help = re.search(r"--strict\s+(.*?)(?=\n  --)", help_text, flags=re.S)
            print(textwrap.fill(" ".join(strict_help[1].split()), width=96) if strict_help else "not found")
            """
        ),
        md(
            """
            **Configuration in `pyproject.toml`.** A realistic setup for a project that is
            partly typed: strict everywhere, except a legacy package that is excluded for now.
            Both checkers run from the project folder and read the same file.
            """
        ),
        code(
            r'''
            typed_shop = UNIT42_DIR / "typed-shop"
            files = {
                "pyproject.toml": """
                    [tool.mypy]
                    strict = true
                    files = ["src"]
                    mypy_path = "src"
                    warn_unreachable = true

                    [[tool.mypy.overrides]]
                    module = ["legacy", "legacy.*"]
                    ignore_errors = true                  # gradual adoption: not checked yet

                    [tool.pyright]
                    include = ["src"]
                    exclude = ["src/legacy"]
                    typeCheckingMode = "strict"
                    pythonVersion = "3.15"
                """,
                "src/shop/__init__.py": "",
                "src/shop/pricing.py": """
                    from decimal import Decimal

                    def with_gst(amount: Decimal, rate: Decimal = Decimal("0.18")) -> Decimal:
                        return amount * (1 + rate)

                    def total(amounts: list[Decimal]) -> Decimal:
                        return sum(amounts, Decimal(0))

                    def bad_total(amounts):                  # untyped: strict mode rejects it
                        return sum(amounts)
                """,
                "src/legacy/__init__.py": "",
                "src/legacy/report.py": "def make_report(rows):\n    return '\\n'.join(rows) + 1\n",
            }
            for relative_path, text in files.items():
                (typed_shop / relative_path).parent.mkdir(parents=True, exist_ok=True)
                (typed_shop / relative_path).write_text(textwrap.dedent(text).lstrip("\n"))
            for command in (["mypy", "--cache-dir", "../.mypy_cache"], ["pyright"]):
                result = subprocess.run(
                    [str(VENV_BIN / command[0]), *command[1:]],
                    cwd=typed_shop,
                    capture_output=True,
                    text=True,
                    env=CHECKER_ENV,
                )
                print(
                    f"$ {command[0]}\n"
                    + textwrap.indent(
                        ANSI_ESCAPE.sub("", result.stdout).replace(str(typed_shop), "<project>").strip(), "  "
                    )
                )
            '''
        ),
        md(
            """
            **`reveal_type` at run time.** Besides being a checker instruction,
            `typing.reveal_type` (3.11) is a real function: it prints the *run-time* type to
            stderr and returns its argument unchanged, so you can leave it in while debugging
            and run the code. (Remove it afterwards; ruff and the checkers flag it.)
            """
        ),
        code(
            r"""
            import contextlib
            import io

            captured = io.StringIO()
            with contextlib.redirect_stderr(captured):
                returned = typing.reveal_type([1, 2, 3])
            print(f"{returned=}  stderr: {captured.getvalue().strip()!r}")
            """
        ),
        md(
            """
            **Stubs and `py.typed`.** A checker needs types for every library you import:

            | Source of types | Example |
            | --- | --- |
            | Inline hints in a package that ships a **`py.typed`** marker file (PEP 561) | pydantic, httpx, rich |
            | Stub files (`.pyi`: signatures only, bodies are `...`) bundled in **typeshed** | the standard library; mypy and pyright ship it |
            | A separate stub package `types-<name>` or `<name>-stubs` | `types-requests`, `pandas-stubs` |
            | Your own stubs in a folder on `mypy_path` / pyright's `stubPath` | private untyped code |

            Without `py.typed`, an installed package's inline hints are **ignored**, as the next
            demo shows. It installs a tiny untyped package into a scratch virtual environment
            and points mypy at that environment's interpreter.
            """
        ),
        code(
            r'''
            stub_demo = UNIT42_DIR / "stub-demo"
            env_dir = stub_demo / "venv"
            if not env_dir.exists():
                subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(env_dir)], check=True)
            site_packages = next(env_dir.glob("lib/python3*/site-packages"))
            package_dir = site_packages / "rupee_tools"
            package_dir.mkdir(exist_ok=True)
            (package_dir / "__init__.py").write_text(
                "def to_paise(amount: float) -> int:\n    return round(amount * 100)\n"
            )
            (package_dir / "py.typed").unlink(missing_ok=True)
            APP = """
            from rupee_tools import to_paise

            reveal_type(to_paise(12.5))
            to_paise("12.50")
            """
            ENV_OPTION = ("--python-executable", str(env_dir / "bin" / "python"))
            print("without py.typed:", *run_mypy(APP, name="stub_app", options=ENV_OPTION), sep="\n  ")
            (package_dir / "py.typed").write_text("")
            print("with py.typed:", *run_mypy(APP, name="stub_app", options=ENV_OPTION), sep="\n  ")
            '''
        ),
        md(
            """
            When you cannot change the package, write a **stub** instead: a `.pyi` file with the
            same module path, found through `mypy_path`. mypy's `stubgen` drafts one from the
            source (here with `py.typed` removed again, so only the stub provides types):
            """
        ),
        code(
            r"""
            (package_dir / "py.typed").unlink()
            stubs_dir = stub_demo / "stubs"
            subprocess.run(
                [str(VENV_BIN / "stubgen"), str(package_dir / "__init__.py"), "-o", str(stubs_dir)],
                capture_output=True,
                text=True,
                check=True,
            )
            stub_file = next(stubs_dir.rglob("*.pyi"))
            print(f"stub written to: stubs/{stub_file.relative_to(stubs_dir).as_posix()}")
            print(f"--- {stub_file.name} (generated by stubgen) ---\n{stub_file.read_text().strip()}")
            stub_env = {**CHECKER_ENV, "MYPYPATH": str(stubs_dir)}
            completed = subprocess.run(
                [
                    str(VENV_BIN / "mypy"),
                    "--no-error-summary",
                    "--cache-dir",
                    ".mypy_cache",
                    *ENV_OPTION,
                    "stub_app.py",
                ],
                cwd=UNIT42_DIR,
                capture_output=True,
                text=True,
                env=stub_env,
            )
            print("with the stub on MYPYPATH:", *completed.stdout.strip().splitlines(), sep="\n  ")
            """
        ),
        md(
            """
            **Gradual adoption.** Nobody types a large codebase in one go. A path that works:

            1. Add mypy (or pyright) to CI in its **default** mode, fix what it finds, keep it
               green.
            2. Turn on `strict = true` globally and list every not-yet-clean module in a
               `[[tool.mypy.overrides]]` block with `ignore_errors = true` (as in the config
               demo above). New modules are strict from day one.
            3. Remove modules from the override list one at a time (a *ratchet*: the list may
               only shrink). Count errors per module to pick the cheapest next target.
            4. Type the boundaries first: public functions, data models, I/O. Inference does the
               rest inside function bodies.
            5. Keep `warn_unused_ignores` on so stale `# type: ignore` comments disappear.

            A ratchet in a few lines: count mypy errors per file of the `typed-shop` project
            when everything (legacy included) is checked strictly.
            """
        ),
        code(
            r"""
            from collections import Counter

            all_strict = subprocess.run(
                [
                    str(VENV_BIN / "mypy"),
                    "--strict",
                    "--no-error-summary",
                    "--cache-dir",
                    "../.mypy_cache",
                    "src",
                ],
                cwd=typed_shop,
                capture_output=True,
                text=True,
                env=CHECKER_ENV,
            )
            per_file = Counter(
                line.split(":")[0] for line in all_strict.stdout.splitlines() if ": error:" in line
            )
            for path, error_count in per_file.most_common():
                print(f"{error_count:>3} errors  {path}")
            """
        ),
    ]


def _lab_hint_cells() -> list[NotebookNode]:
    """Lab 4.2 exercises 1–4."""
    return [
        md(
            """
            ### Lab 4.2

            Seven exercises. For the stubs, replace `raise NotImplementedError`. Exercises 1, 5
            and 6 are different: the code already works but is untyped or badly typed, and you
            **fix its types in place**. Every check cell runs mypy (`--strict` unless stated)
            on the source of your code, which it gets with `source_of(...)`, and also tests the
            behaviour. The checker prelude imports `Callable`, `Iterable`, `Iterator`,
            `Mapping`, `Sequence` (from `collections.abc`), `dataclass`, `field`, `Decimal`,
            `ROUND_HALF_UP`, `Annotated`, `Any`, `Literal`, `Self`, `cast`, `overload` and
            `get_type_hints`, so use those names. Until you finish, the checks print FAIL; that
            is expected.

            #### Exercise 1 — add precise hints to 10 functions

            Annotate the functions in the next cell (change nothing else) so that
            `mypy --strict` reports no errors and the hints are exactly these (spaces do not
            matter; `T` is a PEP 695 type parameter):

            | Function | Hints |
            | --- | --- |
            | `count_words` | `(text: str) -> dict[str, int]` |
            | `average` | `(values: Iterable[float]) -> float` |
            | `find_user` | `(users: Mapping[int, str], user_id: int) -> str \\| None` |
            | `pair_up` | `(names: Sequence[str], scores: Sequence[int]) -> list[tuple[str, int]]` |
            | `parse_point` | `(text: str) -> tuple[float, float]` |
            | `chunk[T]` | `(items: Sequence[T], size: int) -> list[list[T]]` |
            | `merge_settings` | `(defaults: Mapping[str, object], overrides: Mapping[str, object]) -> dict[str, object]` |
            | `first_or_default[T]` | `(items: Iterable[T], default: T) -> T` |
            | `apply_twice[T]` | `(func: Callable[[T], T], value: T) -> T` |
            | `status_text` | `(code: int) -> Literal["ok", "client error", "server error", "unknown"]` |
            """
        ),
        code(
            r"""
            def count_words(text):
                words = text.lower().split()
                counts = dict.fromkeys(words, 0)
                for word in words:
                    counts[word] += 1
                return counts


            def average(values):
                total = 0.0
                count = 0
                for value in values:
                    total += value
                    count += 1
                return total / count if count else 0.0


            def find_user(users, user_id):
                return users.get(user_id)


            def pair_up(names, scores):
                return list(zip(names, scores, strict=True))


            def parse_point(text):
                x_text, y_text = text.split(",")
                return float(x_text), float(y_text)


            def chunk(items, size):
                return [list(items[start : start + size]) for start in range(0, len(items), size)]


            def merge_settings(defaults, overrides):
                return {**defaults, **overrides}


            def first_or_default(items, default):
                for item in items:
                    return item
                return default


            def apply_twice(func, value):
                return func(func(value))


            def status_text(code):
                if 200 <= code < 300:
                    return "ok"
                if 400 <= code < 500:
                    return "client error"
                if 500 <= code < 600:
                    return "server error"
                return "unknown"
            """
        ),
        md("Run the checks."),
        code(
            r'''
            HINT_FUNCTIONS = [
                count_words,
                average,
                find_user,
                pair_up,
                parse_point,
                chunk,
                merge_settings,
                first_or_default,
                apply_twice,
                status_text,
            ]
            EXPECTED_HINTS = {
                "count_words": {"text": "str", "return": "dict[str, int]"},
                "average": {"values": "Iterable[float]", "return": "float"},
                "find_user": {"users": "Mapping[int, str]", "user_id": "int", "return": "str | None"},
                "pair_up": {
                    "names": "Sequence[str]",
                    "scores": "Sequence[int]",
                    "return": "list[tuple[str, int]]",
                },
                "parse_point": {"text": "str", "return": "tuple[float, float]"},
                "chunk": {"items": "Sequence[T]", "size": "int", "return": "list[list[T]]"},
                "merge_settings": {
                    "defaults": "Mapping[str, object]",
                    "overrides": "Mapping[str, object]",
                    "return": "dict[str, object]",
                },
                "first_or_default": {"items": "Iterable[T]", "default": "T", "return": "T"},
                "apply_twice": {"func": "Callable[[T], T]", "value": "T", "return": "T"},
                "status_text": {
                    "code": "int",
                    "return": 'Literal["ok", "client error", "server error", "unknown"]',
                },
            }


            def hint_strings(function: Callable[..., object]) -> dict[str, str]:
                """The annotations as written in the source, without spaces."""
                written = annotationlib.get_annotations(function, format=annotationlib.Format.STRING)
                return {name: text.replace(" ", "").replace("'", '"') for name, text in written.items()}


            run_checks(
                [
                    *(
                        (
                            f"hints of {function.__name__}",
                            lambda function=function: hint_strings(function),
                            {
                                name: text.replace(" ", "")
                                for name, text in EXPECTED_HINTS[function.__name__].items()
                            },
                        )
                        for function in HINT_FUNCTIONS
                    ),
                    ("mypy --strict is clean", lambda: mypy_errors(*HINT_FUNCTIONS), []),
                    (
                        "behaviour unchanged",
                        lambda: (
                            count_words("a b a"),
                            chunk([1, 2, 3], 2),
                            status_text(404),
                            first_or_default([], 7),
                            apply_twice(lambda n: n * 3, 2),
                        ),
                        ({"a": 2, "b": 1}, [[1, 2], [3]], "client error", 7, 18),
                    ),
                ]
            )
            '''
        ),
        md(
            """
            #### Exercise 2 — generic `Stack[T]` and `Result[T, E]`

            Implement the classes below using PEP 695 syntax (keep the signatures):

            - `Stack[T]`: `push`, `pop` (raises `IndexError("pop from empty stack")` when
              empty), `peek` (`None` when empty), `__len__`, `is_empty`.
            - `Ok[T]` and `Err[E]`: frozen dataclasses holding `value` / `error`, with
              `is_ok()` and `unwrap()`. `Err.unwrap()` raises
              `ValueError(f"unwrap on Err: {self.error!r}")`. `Result[T, E]` is their union
              (given).
            - `safe_divide(a, b)` returns `Ok(a / b)` or `Err("division by zero")`.

            The checks also ask mypy what `Stack[int]().pop()` and `safe_divide(1, 2)` are, and
            expect an error for `Stack[int]().push("tea")`.
            """
        ),
        code(
            r'''
            class Stack[T]:
                """A last-in, first-out stack."""

                def __init__(self) -> None:
                    self._items: list[T] = []

                def push(self, item: T) -> None:
                    raise NotImplementedError("Lab 4.2 exercise 2: Stack.push")

                def pop(self) -> T:
                    raise NotImplementedError("Lab 4.2 exercise 2: Stack.pop")

                def peek(self) -> T | None:
                    raise NotImplementedError("Lab 4.2 exercise 2: Stack.peek")

                def __len__(self) -> int:
                    raise NotImplementedError("Lab 4.2 exercise 2: Stack.__len__")

                def is_empty(self) -> bool:
                    raise NotImplementedError("Lab 4.2 exercise 2: Stack.is_empty")


            @dataclass(frozen=True)
            class Ok[T]:
                value: T

                def is_ok(self) -> bool:
                    raise NotImplementedError("Lab 4.2 exercise 2: Ok.is_ok")

                def unwrap(self) -> T:
                    raise NotImplementedError("Lab 4.2 exercise 2: Ok.unwrap")


            @dataclass(frozen=True)
            class Err[E]:
                error: E

                def is_ok(self) -> bool:
                    raise NotImplementedError("Lab 4.2 exercise 2: Err.is_ok")

                def unwrap(self) -> typing.Never:
                    raise NotImplementedError("Lab 4.2 exercise 2: Err.unwrap")


            type Result[T, E] = Ok[T] | Err[E]


            def safe_divide(a: float, b: float) -> Result[float, str]:
                """Ok(a / b), or Err("division by zero")."""
                raise NotImplementedError("Lab 4.2 exercise 2: safe_divide")
            '''
        ),
        md("Run the checks."),
        code(
            r'''
            GENERIC_USAGE = """
            type Result[T, E] = Ok[T] | Err[E]

            reveal_type(Stack[int]().pop())
            reveal_type(safe_divide(1, 2))
            Stack[int]().push("tea")
            """


            def stack_trace() -> list[object]:
                stack = Stack[str]()
                stack.push("tea")
                stack.push("rice")
                return [len(stack), stack.peek(), stack.pop(), stack.pop(), stack.is_empty(), stack.peek()]


            def generic_errors() -> list[str]:
                errors = mypy_errors(Stack, Ok, Err, safe_divide, extra=GENERIC_USAGE)
                return [error.split("  [")[-1] for error in errors]


            run_checks(
                [
                    ("Stack behaviour", stack_trace, [2, "rice", "rice", "tea", True, None]),
                    (
                        "pop on empty",
                        lambda: raised_message(lambda: Stack[int]().pop()),
                        "IndexError: pop from empty stack",
                    ),
                    ("Ok", lambda: (Ok(5).is_ok(), Ok(5).unwrap()), (True, 5)),
                    (
                        "Err",
                        lambda: (Err("boom").is_ok(), raised_message(lambda: Err("boom").unwrap())),
                        (False, "ValueError: unwrap on Err: 'boom'"),
                    ),
                    (
                        "safe_divide",
                        lambda: (safe_divide(1, 4), safe_divide(1, 0)),
                        (Ok(0.25), Err("division by zero")),
                    ),
                    (
                        "PEP 695 parameters",
                        lambda: (
                            [p.__name__ for p in Stack.__type_params__],
                            [p.__name__ for p in Result.__type_params__],
                        ),
                        (["T"], ["T", "E"]),
                    ),
                    (
                        "mypy: types revealed",
                        lambda: revealed_types(Stack, Ok, Err, safe_divide, extra=GENERIC_USAGE)[:2],
                        ["int", "lab_check.Ok[float] | lab_check.Err[str]"],
                    ),
                    ("mypy: only the push('tea') error", generic_errors, ["arg-type]"]),
                ]
            )
            '''
        ),
        md(
            """
            #### Exercise 3 — a typed `@retry` with `ParamSpec`

            Write the decorator factory `retry(times=3, *, exceptions=(Exception,), delay=0.0,
            sleep=time.sleep)`, a simpler cousin of Unit 1.12's `retry`:

            - Call the function up to `times` times; return the first successful result.
            - After a failure with one of `exceptions`, call `sleep(delay)` before the next
              attempt (not after the last); re-raise the last error when attempts run out.
              Other exceptions propagate at once.
            - Keep the wrapped function's metadata (`functools.wraps`) **and its signature for
              the checker**: use `[**P, R]` so `mypy --strict` accepts your decorator, keeps
              the parameters of the decorated function and rejects a badly typed call.
            """
        ),
        code(
            r'''
            def retry[**P, R](
                times: int = 3,
                *,
                exceptions: tuple[type[Exception], ...] = (Exception,),
                delay: float = 0.0,
                sleep: Callable[[float], None] = time.sleep,
            ) -> Callable[[Callable[P, R]], Callable[P, R]]:
                """Retry the decorated function up to `times` times on the given exceptions."""
                raise NotImplementedError("Lab 4.2 exercise 3: write retry")
            '''
        ),
        md("Run the checks. `flaky(n)` returns a function that fails `n` times, then succeeds."),
        code(
            r'''
            SERVICE_DOWN = ConnectionError("down")


            def flaky(failures: int, error: Exception = SERVICE_DOWN) -> Callable[[str], str]:
                """A function that raises `error` for its first `failures` calls."""
                calls = {"count": 0}

                def fetch(sku: str) -> str:
                    calls["count"] += 1
                    if calls["count"] <= failures:
                        raise error
                    return f"{sku} after {calls['count']} calls"

                return fetch


            def retry_run(
                failures: int, times: int, error: Exception = SERVICE_DOWN
            ) -> tuple[str, list[float]]:
                """Decorate flaky(failures, error); return (result or "Error: message", recorded sleeps)."""
                sleeps: list[float] = []
                decorate = retry(times, exceptions=(ConnectionError,), delay=0.5, sleep=sleeps.append)
                decorated = decorate(flaky(failures, error))
                try:
                    outcome = decorated("TEA")
                except Exception as caught:
                    outcome = f"{type(caught).__name__}: {caught}"
                return outcome, sleeps


            RETRY_USAGE = """
            @retry(3, exceptions=(ConnectionError,))
            def fetch_price(sku: str, quantity: int = 1) -> Decimal:
                return Decimal("10") * quantity

            reveal_type(fetch_price)
            fetch_price("TEA", 2)
            fetch_price(42)
            """

            run_checks(
                [
                    ("succeeds on the 3rd call", lambda: retry_run(2, 3), ("TEA after 3 calls", [0.5, 0.5])),
                    ("gives up after times", lambda: retry_run(5, 3), ("ConnectionError: down", [0.5, 0.5])),
                    ("other errors propagate", lambda: retry_run(5, 3, KeyError("x")), ("KeyError: 'x'", [])),
                    ("keeps metadata", lambda: retry()(flaky(0)).__name__, "fetch"),
                    (
                        "mypy: signature kept",
                        lambda: revealed_types(retry, extra=RETRY_USAGE),
                        ["def (sku: str, quantity: int =) -> decimal.Decimal"],
                    ),
                    (
                        "mypy: bad call rejected, nothing else",
                        lambda: [e.split("  [")[-1] for e in mypy_errors(retry, extra=RETRY_USAGE)],
                        ["arg-type]"],
                    ),
                ]
            )
            '''
        ),
        md(
            """
            #### Exercise 4 — an `@overload`ed `parse_value`

            `parse_value(text, kind="str")` converts text according to `kind`:

            | Call | Returns | Checker type |
            | --- | --- | --- |
            | `parse_value("42", "int")` | `42` | `int` |
            | `parse_value("2.5", "float")` | `2.5` | `float` |
            | `parse_value("yes", "bool")` | `True` (`"true"`, `"yes"`, `"1"` → `True`; `"false"`, `"no"`, `"0"` → `False`, case-insensitive; anything else `ValueError`) | `bool` |
            | `parse_value(" tea ")` | `"tea"` (stripped) | `str` |

            Write four `@overload` signatures using `Literal` kinds (`"str"` is the default),
            then the implementation. Any other `kind` must be a checker error. Keep everything
            inside the function: the check sends only the overloads and the implementation to
            mypy, not module-level constants.
            """
        ),
        code(
            r'''
            def parse_value(text: str, kind: str = "str") -> object:
                """Convert text to str, int, float or bool according to kind."""
                raise NotImplementedError("Lab 4.2 exercise 4: overloads + implementation")
            '''
        ),
        md("Run the checks."),
        code(
            r'''
            OVERLOAD_USAGE = """
            reveal_type(parse_value("42", "int"))
            reveal_type(parse_value("2.5", "float"))
            reveal_type(parse_value("yes", "bool"))
            reveal_type(parse_value(" tea "))
            parse_value("2026-11-07", "date")
            """


            def overload_source() -> str:
                """The overloads and the implementation: source of the whole cell block."""
                return (
                    "\n".join(source_of(f) for f in typing.get_overloads(parse_value))
                    + "\n"
                    + source_of(parse_value)
                )


            run_checks(
                [
                    ("int", lambda: parse_value("42", "int"), 42),
                    ("float", lambda: parse_value("2.5", "float"), 2.5),
                    (
                        "bool",
                        lambda: [parse_value(t, "bool") for t in ("Yes", "TRUE", "1", "no", "False", "0")],
                        [True, True, True, False, False, False],
                    ),
                    ("bad bool", lambda: raised_error_name(lambda: parse_value("maybe", "bool")), "ValueError"),
                    ("str (default)", lambda: parse_value(" tea "), "tea"),
                    ("four overloads", lambda: len(typing.get_overloads(parse_value)), 4),
                    (
                        "mypy: types",
                        lambda: re.findall(
                            r'Revealed type is "([^"]+)"',
                            "\n".join(mypy_report(overload_source() + textwrap.dedent(OVERLOAD_USAGE))),
                        ),
                        ["int", "float", "bool", "str"],
                    ),
                    (
                        "mypy: unknown kind rejected",
                        lambda: [
                            line.split("  [")[-1]
                            for line in mypy_report(overload_source() + textwrap.dedent(OVERLOAD_USAGE))
                            if ": error:" in line
                        ],
                        ["call-overload]"],
                    ),
                ]
            )
            '''
        ),
    ]


def _lab_fix_cells() -> list[NotebookNode]:
    """Lab 4.2 exercises 5–7."""
    return [
        md(
            """
            #### Exercise 5 — fix 8 mypy errors in a provided module

            The next cell is a small order-report module. It is annotated, but mypy (default
            mode) reports **8 errors**, and some of them are real bugs. Fix the code in place
            until mypy reports nothing **and** the behaviour checks pass:

            - `parse_line("TEA,2,120.50")` → `LineItem("TEA", 2, Decimal("120.50"))`
            - `find_item` returns `None` for an unknown SKU (fix the annotation, not the
              behaviour); `quantity_of` returns `0` for an unknown SKU
            - `order_total` returns a `Decimal`; `describe` returns `"TEA x 2"`
            - `totals_by_sku` maps each SKU to its line total (a `Decimal`)
            - `sample_item()` returns a `LineItem` for `"RICE"`, quantity 1, price `80`
            - `cheapest` returns the **SKU** of the item with the lowest unit price

            Fixing one error can reveal another (a function that now returns `X | None`
            makes its callers narrow); keep going until mypy is silent.

            The cell after it shows the 8 errors for the code as given.
            """
        ),
        code(
            r"""
            @dataclass
            class LineItem:
                sku: str
                quantity: int
                unit_price: Decimal

                def total(self) -> Decimal:
                    return self.quantity * self.unit_price


            def parse_line(raw: str) -> LineItem:
                sku, quantity, price = raw.split(",")
                return LineItem(sku, quantity, Decimal(price))


            def find_item(items: list[LineItem], sku: str) -> LineItem:
                for item in items:
                    if item.sku == sku:
                        return item
                return None


            def quantity_of(items: list[LineItem], sku: str) -> int:
                return find_item(items, sku).quantity


            def order_total(items: list[LineItem]) -> Decimal:
                total = 0
                for item in items:
                    total += item.total()
                return total


            def describe(item: LineItem) -> str:
                return item.sku + " x " + item.quantity


            def totals_by_sku(items: list[LineItem]) -> dict[str, int]:
                totals: dict[str, int] = {}
                for item in items:
                    totals[item.sku] = item.total()
                return totals


            def sample_item() -> LineItem:
                return LineItem(sku="RICE", quantity=1, price=Decimal("80"))


            def cheapest(items: list[LineItem]) -> str:
                return min(items, key=lambda item: item.unit_price)
            """
        ),
        md("The errors as they stand (this cell is information, not a check):"),
        code(
            r"""
            ORDER_REPORT = [
                LineItem,
                parse_line,
                find_item,
                quantity_of,
                order_total,
                describe,
                totals_by_sku,
                sample_item,
                cheapest,
            ]
            for error in mypy_errors(*ORDER_REPORT, strict=False):
                print(error)
            """
        ),
        md("Run the checks."),
        code(
            r"""
            SAMPLE_LINES = [parse_line("TEA,2,120.50"), parse_line("RICE,1,80")]

            run_checks(
                [
                    ("mypy is clean", lambda: mypy_errors(*ORDER_REPORT, strict=False), []),
                    ("parse_line", lambda: parse_line("TEA,2,120.50"), LineItem("TEA", 2, Decimal("120.50"))),
                    ("find_item missing", lambda: find_item(SAMPLE_LINES, "SALT"), None),
                    (
                        "quantity_of",
                        lambda: (quantity_of(SAMPLE_LINES, "TEA"), quantity_of(SAMPLE_LINES, "SALT")),
                        (2, 0),
                    ),
                    ("order_total", lambda: order_total(SAMPLE_LINES), Decimal("321.00")),
                    ("order_total type", lambda: type(order_total([])).__name__, "Decimal"),
                    ("describe", lambda: describe(SAMPLE_LINES[0]), "TEA x 2"),
                    (
                        "totals_by_sku",
                        lambda: totals_by_sku(SAMPLE_LINES),
                        {"TEA": Decimal("241.00"), "RICE": Decimal("80")},
                    ),
                    ("sample_item", sample_item, LineItem("RICE", 1, Decimal("80"))),
                    ("cheapest", lambda: cheapest(SAMPLE_LINES), "RICE"),
                ]
            )
            """
        ),
        md(
            """
            #### Exercise 6 — type the Phase 2 model to pass `--strict`

            Below is a condensed, **untyped** copy of the Phase 2 inventory model: `Money`
            (Lab 2.4), `Product` and `Warehouse` (Phase 2 Project). Add annotations (you may
            also add attribute annotations or turn `Product` into a dataclass) until
            `mypy --strict` reports nothing. The behaviour must not change.

            Hints: `__eq__` takes `other: object`; binary dunders may return `NotImplemented`
            while being annotated `-> Money`; empty dict attributes need their type.
            """
        ),
        code(
            r'''
            class CurrencyMismatchError(ValueError):
                """Two Money values in different currencies were combined."""


            class Money:
                __slots__ = ("_amount", "_currency")

                def __init__(self, amount, currency="INR"):
                    if isinstance(amount, float):
                        raise TypeError("amount must be Decimal, int or str, not float")
                    self._amount = Decimal(amount).quantize(PAISE, rounding=ROUND_HALF_UP)
                    self._currency = currency

                @property
                def amount(self):
                    return self._amount

                @property
                def currency(self):
                    return self._currency

                def __repr__(self):
                    return f"Money({str(self._amount)!r}, {self._currency!r})"

                def __eq__(self, other):
                    if not isinstance(other, Money):
                        return NotImplemented
                    return (self._amount, self._currency) == (other._amount, other._currency)

                def __hash__(self):
                    return hash((self._amount, self._currency))

                def __add__(self, other):
                    if not isinstance(other, Money):
                        return NotImplemented
                    if other._currency != self._currency:
                        raise CurrencyMismatchError(f"{self._currency} vs {other._currency}")
                    return Money(self._amount + other._amount, self._currency)

                def __mul__(self, factor):
                    if isinstance(factor, bool) or not isinstance(factor, (int, Decimal)):
                        return NotImplemented
                    return Money(self._amount * factor, self._currency)


            class InsufficientStockError(Exception):
                def __init__(self, sku, available, requested):
                    super().__init__(f"not enough {sku}: {available} available, {requested} requested")
                    self.sku, self.available, self.requested = sku, available, requested


            class Product:
                def __init__(self, sku, name, unit_price):
                    self.sku, self.name, self.unit_price = sku, name, unit_price

                def __repr__(self):
                    return f"Product({self.sku!r}, {self.name!r}, {self.unit_price!r})"


            class Warehouse:
                def __init__(self, code):
                    self.code = code
                    self._products = {}
                    self._quantities = {}

                def add_product(self, product):
                    self._products[product.sku] = product
                    self._quantities[product.sku] = 0

                def receive(self, sku, quantity):
                    self._quantities[sku] += quantity
                    return self._quantities[sku]

                def ship(self, sku, quantity):
                    available = self._quantities[sku]
                    if quantity > available:
                        raise InsufficientStockError(sku, available, quantity)
                    self._quantities[sku] = available - quantity
                    return self._quantities[sku]

                def stock_value(self):
                    return sum(
                        (product.unit_price * self._quantities[sku] for sku, product in self._products.items()),
                        Money(0),
                    )
            '''
        ),
        md("Run the checks."),
        code(
            r"""
            INVENTORY_MODEL = [CurrencyMismatchError, Money, InsufficientStockError, Product, Warehouse]


            def warehouse_story() -> tuple[object, ...]:
                pune = Warehouse("PNQ")
                pune.add_product(Product("TEA-500", "Assam tea", Money("120.50")))
                pune.add_product(Product("RICE-1K", "Basmati", Money(80)))
                received = pune.receive("TEA-500", 10)
                pune.receive("RICE-1K", 5)
                left = pune.ship("TEA-500", 4)
                shortage = raised_message(lambda: pune.ship("RICE-1K", 9))
                return received, left, shortage, pune.stock_value()


            run_checks(
                [
                    ("mypy --strict is clean", lambda: mypy_errors(*INVENTORY_MODEL), []),
                    (
                        "Money arithmetic",
                        lambda: (Money("10.005") + Money(5), Money(3) * 2),
                        (Money("15.01"), Money("6.00")),
                    ),
                    (
                        "currency mismatch",
                        lambda: raised_error_name(lambda: Money(1) + Money(1, "USD")),
                        "CurrencyMismatchError",
                    ),
                    ("float rejected", lambda: raised_error_name(lambda: Money(1.5)), "TypeError"),
                    ("NotImplemented path", lambda: raised_error_name(lambda: Money(1) + 1), "TypeError"),
                    (
                        "warehouse story",
                        warehouse_story,
                        (
                            10,
                            6,
                            "InsufficientStockError: not enough RICE-1K: 5 available, 9 requested",
                            Money("1123.00"),
                        ),
                    ),
                ]
            )
            """
        ),
        md(
            """
            #### Exercise 7 — an `Annotated`-driven runtime validator

            Write `validate(instance)` for dataclass instances. For every field, read the hint
            with `get_type_hints(type(instance), include_extras=True)` and return a list of
            error messages (empty when valid), in field order:

            | Situation | Message |
            | --- | --- |
            | The value is not an instance of the field's base type (for `Annotated[int, …]` the base is `int`; `bool` is **not** accepted as `int`) | `"age: expected int, got str"` (then skip that field's constraints) |
            | `Range(minimum, maximum)` violated | `"age: 200 is not between 0 and 150"` |
            | `MaxLength(limit)` violated | `"name: longer than 20 characters"` |
            | `Pattern(regex)` does not `fullmatch` | `"email: does not match [^@]+@[^@]+"` |

            Fields whose hint is not `Annotated` only get the type check (and only for plain
            classes such as `str`; skip hints like `list[str]` or `str | None`).
            """
        ),
        code(
            r'''
            @dataclass(frozen=True)
            class Range:
                minimum: int
                maximum: int


            @dataclass(frozen=True)
            class MaxLength:
                limit: int


            @dataclass(frozen=True)
            class Pattern:
                regex: str


            def validate(instance: object) -> list[str]:
                """Error messages for a dataclass instance, driven by Annotated metadata."""
                raise NotImplementedError("Lab 4.2 exercise 7: write validate")
            '''
        ),
        md("Run the checks."),
        code(
            r"""
            @dataclass
            class CustomerForm:
                name: Annotated[str, MaxLength(20)]
                age: Annotated[int, Range(0, 150)]
                email: Annotated[str, Pattern(r"[^@]+@[^@]+"), MaxLength(40)]
                city: str
                tags: list[str] = field(default_factory=list)


            run_checks(
                [
                    ("valid", lambda: validate(CustomerForm("Asha", 31, "asha@example.com", "Pune")), []),
                    (
                        "range",
                        lambda: validate(CustomerForm("Asha", 200, "asha@example.com", "Pune")),
                        ["age: 200 is not between 0 and 150"],
                    ),
                    (
                        "length and pattern",
                        lambda: validate(CustomerForm("A" * 21, 31, "not-an-email", "Pune")),
                        ["name: longer than 20 characters", "email: does not match [^@]+@[^@]+"],
                    ),
                    (
                        "wrong types",
                        lambda: validate(CustomerForm("Asha", "31", "a@b", 42)),
                        ["age: expected int, got str", "city: expected str, got int"],
                    ),
                    (
                        "bool is not int",
                        lambda: validate(CustomerForm("Asha", True, "a@b", "Pune")),
                        ["age: expected int, got bool"],
                    ),
                    (
                        "several constraints",
                        lambda: validate(CustomerForm("Asha", 31, "x" * 41 + "@b", "Pune")),
                        ["email: longer than 40 characters"],
                    ),
                    (
                        "generic hints skipped",
                        lambda: validate(CustomerForm("Asha", 31, "a@b", "Pune", tags="oops")),
                        [],
                    ),
                ]
            )
            """
        ),
    ]


def _recap_cells() -> list[NotebookNode]:
    """Recap for Unit 4.2."""
    return [
        md(
            """
            ### Recap — Unit 4.2

            | Concept | One-line takeaway | TypeScript equivalent |
            | --- | --- | --- |
            | Gradual typing | Hints are checked by tools, ignored by the interpreter; untyped code is `Any` | `allowJs`, `// @ts-check` |
            | Nominal vs structural | Classes are nominal; `Protocol` opts into structural typing | everything is structural |
            | Annotation syntax | `x: int`, `-> T`, `ClassVar`, `Final`; lazy since 3.14 (`annotationlib`) | `: number`, `static`, `const` |
            | Collections | `list[int]`, `dict[str, list[User]]`, `tuple[int, str]` vs `tuple[int, ...]`; accept abc, return concrete | `number[]`, `Record`, tuples |
            | Unions | `X \\| None`, narrow with `is None`, `isinstance`, `match`; `assert_never` for exhaustiveness | control-flow narrowing, `never` |
            | Escape hatches | `Any` off, `object` safe, `cast` lies, `# type: ignore[code]` | `any`, `unknown`, `as`, `@ts-expect-error` |
            | Precise types | `Literal`, `LiteralString`, `Final`, `NewType`, `Self`, `TypedDict` | literal types, brands, `this`, interfaces |
            | Generics | `def f[T]`, `class C[T]`, `type A[T] = ...`; bounds, constraints, defaults; variance inferred | `<T extends …= …>` |
            | Callables | `Callable`, callback Protocols, `ParamSpec`, `Concatenate`, `@overload` | function types, overloads |
            | Class typing | `type[T]`, `@override`, `@final`, generic Protocols | `typeof C`, `override` |
            | Custom narrowing | `TypeIs` (both branches) over `TypeGuard`; tagged unions | `x is T`, discriminated unions |
            | `Annotated` | Metadata for run-time libraries; read with `get_type_hints(include_extras=True)` | (none: Zod schemas) |
            | Checkers | mypy / pyright strict, `pyproject.toml` config, `py.typed`, stubs, ratchet adoption | `tsc --strict`, `.d.ts` |

            **Further reading**

            - [`typing`](https://docs.python.org/3/library/typing.html),
              [`annotationlib`](https://docs.python.org/3/library/annotationlib.html),
              [`collections.abc`](https://docs.python.org/3/library/collections.abc.html),
              [Annotations best practices](https://docs.python.org/3/howto/annotations.html)
            - [Typing specification](https://typing.python.org/en/latest/spec/) and
              [typing guides](https://typing.python.org/en/latest/guides/)
            - [mypy documentation](https://mypy.readthedocs.io/),
              [pyright documentation](https://microsoft.github.io/pyright/),
              [typeshed](https://github.com/python/typeshed)
            - [PEP 484](https://peps.python.org/pep-0484/), [PEP 561](https://peps.python.org/pep-0561/),
              [PEP 593](https://peps.python.org/pep-0593/), [PEP 604](https://peps.python.org/pep-0604/),
              [PEP 612](https://peps.python.org/pep-0612/), [PEP 647](https://peps.python.org/pep-0647/),
              [PEP 649](https://peps.python.org/pep-0649/), [PEP 675](https://peps.python.org/pep-0675/),
              [PEP 692](https://peps.python.org/pep-0692/), [PEP 695](https://peps.python.org/pep-0695/),
              [PEP 696](https://peps.python.org/pep-0696/), [PEP 698](https://peps.python.org/pep-0698/),
              [PEP 705](https://peps.python.org/pep-0705/), [PEP 742](https://peps.python.org/pep-0742/),
              [PEP 749](https://peps.python.org/pep-0749/)
            """
        ),
    ]


def cells() -> list[NotebookNode]:
    """Return the cells for Unit 4.2 and Lab 4.2."""
    return [
        *_overview_cells(),
        *_gradual_cells(),
        *_annotation_syntax_cells(),
        *_collection_cells(),
        *_union_cells(),
        *_escape_hatch_cells(),
        *_precise_type_cells(),
        *_generic_cells(),
        *_callable_cells(),
        *_class_typing_cells(),
        *_custom_narrowing_cells(),
        *_annotated_cells(),
        *_running_checker_cells(),
        *_lab_hint_cells(),
        *_lab_fix_cells(),
        *_recap_cells(),
    ]
