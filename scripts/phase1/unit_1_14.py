"""Unit 1.14 — Exceptions and Context Managers (with Lab 1.14)."""

from nbformat import NotebookNode

from nb_builder import code, md, predict_cells

UNIT_SETUP_SOURCE = '''
import builtins
import dis
import functools
import inspect
import io
import json  # noqa: F401 (Lab 1.14)
import logging
import os
import sqlite3
import subprocess
import sys
import time
import timeit
import traceback
import warnings
from collections.abc import Callable, Iterable, Iterator
from contextlib import (
    AbstractContextManager,
    ExitStack,
    chdir,
    closing,
    contextmanager,
    nullcontext,
    redirect_stdout,
    suppress,
)
from pathlib import Path
from types import TracebackType
from typing import IO, Any


def raised_error_name(thunk: Callable[[], object]) -> str:
    """Call thunk and return the name of the exception it raised, or "no error"."""
    try:
        thunk()
    except Exception as error:
        return type(error).__name__
    return "no error"


def compile_error(source: str) -> str:
    """Compile source without running it; return "SyntaxError: <message>" or "compiles"."""
    try:
        compile(source, "<demo>", "exec")
    except SyntaxError as error:
        return f"SyntaxError: {error.msg}"
    return "compiles"


def find_repo_root(start: Path | None = None) -> Path:
    """Walk up from start (default: the working directory) to the folder holding pyproject.toml."""
    current = (start or Path.cwd()).resolve()
    for folder in (current, *current.parents):
        if (folder / "pyproject.toml").exists():
            return folder
    raise FileNotFoundError("pyproject.toml not found above the working directory")


scratch_dir = find_repo_root() / "notebooks" / "_scratch"
scratch_dir.mkdir(parents=True, exist_ok=True)
print(f"{sys.version_info[:2]=}")
'''


def _overview_cells() -> list[NotebookNode]:
    """Unit opener and setup."""
    return [
        md(
            """
            ## Unit 1.14 — Exceptions and Context Managers

            **Objectives**

            - Read the exception hierarchy and predict which `except` clause catches what.
            - Trace every path through `try` / `except` / `else` / `finally`, including the 3.14
              syntax and warning changes.
            - Raise, re-raise and chain exceptions so tracebacks tell the whole story.
            - Design a custom exception hierarchy that maps to HTTP status codes.
            - Raise and handle several errors at once with exception groups and `except*`.
            - Choose between EAFP and LBYL with measurements, and log exceptions correctly.
            - Write context managers as classes and with `contextlib`, and see both in bytecode.

            **JS bridge**

            | JavaScript concept | Python equivalent | The difference that bites |
            | --- | --- | --- |
            | `throw value` | `raise ExceptionInstance` | Only `BaseException` subclasses can be raised; `throw "text"` has no equivalent |
            | `catch (e)` (catches everything) | `except SomeError as error:` | Python filters by class; a bare `except:` also catches Ctrl+C and `sys.exit` |
            | — | `else:` clause | Runs only when the `try` body raised nothing |
            | `finally` | `finally` | Same, and a `return` in `finally` now warns (3.14) |
            | `new Error(msg, { cause })` | `raise New(...) from original` | Python also records the *implicit* context automatically |
            | `AggregateError` | `ExceptionGroup` + `except*` | `except*` handles each matching subgroup, re-raises the rest |
            | `try { } finally { res.close() }` / `using` (TC39) | `with resource:` | The manager's `__exit__` sees the exception and may suppress it |
            | `console.error(err)` | `logger.exception("message")` | Logs the message **and** the traceback, at ERROR level |

            The next cell is this unit's setup (`scratch_dir` is the git-ignored folder used by
            file demos).
            """
        ),
        code(UNIT_SETUP_SOURCE),
    ]


def _hierarchy_cells() -> list[NotebookNode]:
    """1.14.1 The exception hierarchy."""
    return [
        md(
            """
            ### 1.14.1 The exception hierarchy

            Every exception is an instance of a class that derives from **`BaseException`**.
            Directly under it sit a few classes that are *not errors* but control signals, and
            **`Exception`**, the base of everything you normally handle:

            | Class | Raised by | Should `except Exception` catch it? |
            | --- | --- | --- |
            | `SystemExit` | `sys.exit()` | No: the program asked to stop |
            | `KeyboardInterrupt` | Ctrl+C | No: the user asked to stop |
            | `GeneratorExit` | `generator.close()` (Unit 1.13.7) | No: the generator is being shut down |
            | `BaseExceptionGroup` | several errors at once (1.14.6) | Only its `ExceptionGroup` subclass |
            | `Exception` | every ordinary error | Yes |

            So `except Exception:` is the widest net that still lets the program be stopped.
            Custom exceptions should derive from `Exception` (or a subclass), never directly from
            `BaseException`.

            ```mermaid
            graph TD
                BaseException --> SystemExit
                BaseException --> KeyboardInterrupt
                BaseException --> GeneratorExit
                BaseException --> BaseExceptionGroup
                BaseException --> Exception
                BaseExceptionGroup --> ExceptionGroup
                Exception --> ExceptionGroup
                Exception --> ArithmeticError --> ZeroDivisionError
                Exception --> LookupError --> KeyError
                LookupError --> IndexError
                Exception --> OSError --> FileNotFoundError
                OSError --> PermissionError
                OSError --> ConnectionError
                OSError --> TimeoutError
                Exception --> ValueError --> UnicodeError
                Exception --> TypeError
                Exception --> AttributeError
                Exception --> NameError --> UnboundLocalError
                Exception --> RuntimeError --> RecursionError
                RuntimeError --> NotImplementedError
                Exception --> StopIteration
                Exception --> ImportError --> ModuleNotFoundError
                Exception --> Warning --> DeprecationWarning
            ```

            <details><summary>ASCII fallback</summary>

            ```text
            BaseException
            ├── SystemExit
            ├── KeyboardInterrupt
            ├── GeneratorExit
            ├── BaseExceptionGroup
            │   └── ExceptionGroup        (also an Exception)
            └── Exception
                ├── ArithmeticError ── ZeroDivisionError, OverflowError
                ├── LookupError ────── KeyError, IndexError
                ├── OSError ────────── FileNotFoundError, PermissionError,
                │                      ConnectionError, TimeoutError, …
                ├── ValueError ─────── UnicodeError (UnicodeDecodeError, …)
                ├── TypeError, AttributeError
                ├── NameError ──────── UnboundLocalError
                ├── RuntimeError ───── RecursionError, NotImplementedError
                ├── StopIteration, ImportError ── ModuleNotFoundError
                └── Warning ────────── DeprecationWarning, UserWarning, …
            ```

            </details>

            The cell below shows the practical consequence: `except Exception` lets `sys.exit()`
            and Ctrl+C through.
            """
        ),
        code(
            '''
            def catches_with_exception_clause(error: BaseException) -> bool:
                """Raise error inside try / except Exception; report whether the clause caught it."""
                try:
                    raise error
                except Exception:
                    return True
                except BaseException:
                    return False


            for raised in (ValueError("bad"), KeyError("sku"), SystemExit(1), KeyboardInterrupt()):
                print(
                    f"{type(raised).__name__:<18} caught by except Exception: "
                    f"{catches_with_exception_clause(raised)}"
                )
            '''
        ),
        md(
            """
            #### Under the hood: `__mro__` and what `except` matches

            `except SomeClass:` matches when `isinstance(error, SomeClass)` is true, that is when
            `SomeClass` appears anywhere in the error's **method resolution order**
            (`type(error).__mro__`). So `except OSError:` catches `FileNotFoundError`, and
            `except LookupError:` catches both `KeyError` and `IndexError`.
            """
        ),
        code(
            """
            print(" -> ".join(cls.__name__ for cls in FileNotFoundError.__mro__))
            print(" -> ".join(cls.__name__ for cls in KeyError.__mro__))
            print(" -> ".join(cls.__name__ for cls in ExceptionGroup.__mro__))

            try:
                Path("no-such-file.txt").read_text(encoding="utf-8")
            except OSError as error:
                print(f"except OSError caught {type(error).__name__}: errno={error.errno}")
            """
        ),
        md(
            """
            The tree in the diagram is a selection. The next cell builds the real tree of
            built-in exceptions from `builtins`, two levels below `Exception`, using
            `__subclasses__()`. The exact list grows slowly between versions.
            """
        ),
        code(
            '''
            BUILTIN_EXCEPTIONS = {
                value
                for value in vars(builtins).values()
                if isinstance(value, type) and issubclass(value, BaseException)
            }


            def exception_tree(root: type[BaseException], depth: int, max_depth: int) -> Iterator[str]:
                """Yield indented names of the built-in subclasses of root, depth first."""
                yield "    " * depth + root.__name__
                if depth == max_depth:
                    return
                children = [cls for cls in root.__subclasses__() if cls in BUILTIN_EXCEPTIONS]
                for child in sorted(children, key=lambda cls: cls.__name__):
                    yield from exception_tree(child, depth + 1, max_depth)


            print(f"{len(BUILTIN_EXCEPTIONS)} built-in exception classes (warnings included)")
            top_level = list(exception_tree(BaseException, 0, 1))
            print("Under BaseException:", ", ".join(name.strip() for name in top_level[1:]))
            print("\\n".join(line for line in exception_tree(Exception, 0, 1)))
            '''
        ),
    ]


def _try_statement_cells() -> list[NotebookNode]:
    """1.14.2 try / except / else / finally."""
    return [
        md(
            """
            ### 1.14.2 `try` / `except` / `else` / `finally`

            The full statement has four parts. `else` runs only if the `try` body raised nothing;
            `finally` runs **always**, on every way out.

            | Path | Runs, in order | Afterwards |
            | --- | --- | --- |
            | No exception | `try` → `else` → `finally` | continues after the statement |
            | Exception matched by an `except` | `try` (up to the error) → that `except` → `finally` | continues after the statement |
            | Exception not matched | `try` (up to the error) → `finally` | the exception propagates |
            | Exception raised inside `except` | `try` → `except` (up to the new error) → `finally` | the **new** exception propagates; `__context__` is the old one |
            | Exception raised inside `else` | `try` → `else` (up to the error) → `finally` | propagates: this statement's `except` clauses do **not** see it |
            | `return` in `try` | `try` (return value evaluated) → `finally` | the function returns that value |
            | `break` / `continue` in `try` | `try` → `finally` | the loop jump happens |

            Why `else`? Code placed there is not protected by the `except` clauses, so you do not
            accidentally catch errors from code you did not mean to guard. The next cell walks
            the first five paths and records each step.
            """
        ),
        code(
            '''
            def checkout_steps(scenario: str, steps: list[str]) -> None:
                """Append the name of each block that runs for the given scenario."""
                try:
                    steps.append("try")
                    if scenario in ("error handled", "error in except"):
                        raise ValueError("bad quantity")
                    if scenario == "error not matched":
                        raise KeyError("sku")
                except ValueError:
                    steps.append("except")
                    if scenario == "error in except":
                        raise RuntimeError("handler failed")  # noqa: B904 (implicit chaining demo)
                else:
                    steps.append("else")
                    if scenario == "error in else":
                        raise TypeError("else failed")
                finally:
                    steps.append("finally")
                steps.append("after")


            for scenario in (
                "no error",
                "error handled",
                "error not matched",
                "error in except",
                "error in else",
            ):
                recorded_steps: list[str] = []
                try:
                    checkout_steps(scenario, recorded_steps)
                except Exception as error:
                    recorded_steps.append(f"propagated {type(error).__name__}")
                print(f"{scenario:<18} {' -> '.join(recorded_steps)}")
            '''
        ),
        md(
            """
            The last two rows of the table: `finally` runs even when `try` leaves through
            `return` or `break`. The return value is computed first, then `finally` runs, then
            the function actually returns.
            """
        ),
        code(
            '''
            def price_with_audit(audit_log: list[str]) -> int:
                """Return from inside try; finally still runs before the caller gets the value."""
                try:
                    audit_log.append("computing price")
                    return 499
                finally:
                    audit_log.append("finally after return")


            audit_log: list[str] = []
            print(f"{price_with_audit(audit_log)=}, {audit_log=}")

            loop_log: list[str] = []
            for attempt in range(3):
                try:
                    if attempt == 1:
                        break
                finally:
                    loop_log.append(f"finally for attempt {attempt}")
            print(f"{loop_log=}")
            '''
        ),
        md(
            """
            **Multiple clauses.** Clauses are tested top to bottom and the **first match wins**;
            the rest are skipped. Put the most specific classes first. A broad clause placed
            early silently shadows the specific ones below it (Python does not warn).
            """
        ),
        code(
            '''
            def classify_failure(thunk: Callable[[], object]) -> str:
                """Specific clauses first, broad ones last."""
                try:
                    thunk()
                except KeyError:
                    return "KeyError clause"
                except LookupError:
                    return "LookupError clause"
                except Exception as error:
                    return f"Exception clause ({type(error).__name__})"
                return "no error"


            def classify_failure_wrong_order(thunk: Callable[[], object]) -> str:
                """The broad clause comes first, so the KeyError clause can never run."""
                try:
                    thunk()
                except LookupError:
                    return "LookupError clause"
                except KeyError:
                    return "KeyError clause (unreachable)"
                return "no error"


            stock = {"tea": 4}
            print(f"{classify_failure(lambda: stock['coffee'])=}")
            print(f"{classify_failure(lambda: [][0])=}")
            print(f"{classify_failure(lambda: int('four'))=}")
            print(f"{classify_failure_wrong_order(lambda: stock['coffee'])=}")
            '''
        ),
        md(
            """
            **Tuples.** One clause can handle several classes with a parenthesized tuple; with
            `as error` you then branch on the type if needed.
            """
        ),
        code(
            '''
            def first_item_name(order: dict[str, list[str]]) -> str:
                """Handle a missing key and an empty list in one clause."""
                try:
                    return order["items"][0]
                except (KeyError, IndexError) as error:
                    return f"no items ({type(error).__name__})"


            print(first_item_name({"items": ["rice"]}))
            print(first_item_name({}))
            print(first_item_name({"items": []}))
            '''
        ),
        md(
            """
            **Unparenthesized `except A, B:`** (*New in 3.14*, PEP 758). The parentheses may now
            be dropped, **but only without `as`**. In Python 2, `except A, B:` meant "catch `A`
            and bind it to the name `B`", which is why it was a syntax error until 3.14.

            ```python
            except KeyError, IndexError:          # 3.14+: fine
            except (KeyError, IndexError) as e:   # needs parentheses with `as`
            ```

            The cell runs the new form through `exec` inside a version guard, so older kernels can
            still parse the cell.
            """
        ),
        code(
            '''
            NEW_EXCEPT_SOURCE = """
            try:
                {}["missing"]
            except KeyError, IndexError:
                print("3.14 syntax: caught without parentheses")
            """

            if sys.version_info >= (3, 14):
                exec(inspect.cleandoc(NEW_EXCEPT_SOURCE))
            else:
                print("Skipped: unparenthesized except needs Python 3.14+")

            print(compile_error("try:\\n    pass\\nexcept KeyError, IndexError as error:\\n    pass"))
            '''
        ),
        md(
            """
            **`as error` is deleted at the end of the clause.** Python runs `del error` when the
            `except` block ends, because the exception holds its traceback, the traceback holds
            the frame, and the frame holds `error`: a reference cycle that would keep every local
            variable alive. To keep the exception, bind it to another name inside the block.
            """
        ),
        code(
            """
            try:
                int("twelve")
            except ValueError as conversion_error:
                kept_error = conversion_error
                print(f"inside:  {'conversion_error' in globals()=}")
            print(f"after:   {'conversion_error' in globals()=}")
            print(f"kept:    {kept_error!r}")
            """
        ),
        md(
            """
            **Bare `except:` dangers.** `except:` with no class is the same as
            `except BaseException:`. It catches `SystemExit` and `KeyboardInterrupt`, so a
            program cannot be stopped, and it hides typos (`NameError`) as if they were expected
            failures. If you truly must catch everything (a top-level crash reporter), catch
            `BaseException` explicitly and **re-raise**.
            """
        ),
        code(
            '''
            def shutdown_service() -> str:
                """Ask the interpreter to exit, but a bare except swallows the request."""
                try:
                    sys.exit(0)
                except:  # noqa: E722 (the trap being demonstrated)
                    return "sys.exit() was swallowed; the program keeps running"


            def report_crash_and_reraise(thunk: Callable[[], object]) -> str:
                """The acceptable pattern: catch everything, record it, re-raise."""
                try:
                    thunk()
                except BaseException as error:
                    print(f"crash reporter saw {type(error).__name__}")
                    raise
                return "no error"


            print(shutdown_service())
            try:
                report_crash_and_reraise(lambda: sys.exit(3))
            except SystemExit as exit_request:
                print(f"SystemExit still propagated, code={exit_request.code}")
            '''
        ),
        md(
            """
            **`return` in `finally`** (*Changed in 3.14*, PEP 765). A `return`, `break` or
            `continue` inside `finally` silently discards any exception in flight and any earlier
            return value. Since 3.14 the compiler emits a `SyntaxWarning`. The cell compiles such
            a function from a string (so the warning is captured, not printed by the notebook),
            then calls it: the `ZeroDivisionError` vanishes.
            """
        ),
        code(
            '''
            SWALLOWING_SOURCE = """
            def average_price(total: int, count: int) -> float | str:
                try:
                    return total / count
                finally:
                    return "finally won"
            """

            with warnings.catch_warnings(record=True) as compile_warnings:
                warnings.simplefilter("always")
                swallowing_code = compile(inspect.cleandoc(SWALLOWING_SOURCE), "<demo>", "exec")
            for caught_warning in compile_warnings:
                print(f"{caught_warning.category.__name__}: {caught_warning.message}")

            demo_namespace: dict[str, Any] = {}
            exec(swallowing_code, demo_namespace)
            print(f"{demo_namespace['average_price'](100, 0)=}  (ZeroDivisionError lost)")
            '''
        ),
        md("#### Predict the output"),
        *predict_cells(
            snippet="""
            def apply_coupons() -> list[str]:
                applied = ["SAVE10"]
                try:
                    return applied
                finally:
                    applied.append("FREESHIP")


            print(apply_coupons())
            """,
            answer="""
            `['SAVE10', 'FREESHIP']`. The `return` evaluates `applied` (a reference to the list)
            before `finally` runs; `finally` then mutates that same list. Returning an `int` the
            same way would be unaffected, because rebinding is not mutation (Unit 1.2).
            """,
            proof='''
            def apply_coupons() -> list[str]:
                """Return a list that finally mutates."""
                applied = ["SAVE10"]
                try:
                    return applied
                finally:
                    applied.append("FREESHIP")


            print(apply_coupons())
            ''',
        ),
    ]


def _raising_cells() -> list[NotebookNode]:
    """1.14.3 Raising and chaining."""
    return [
        md(
            """
            ### 1.14.3 Raising and chaining

            | Form | Meaning |
            | --- | --- |
            | `raise ValueError("msg")` | raise a new instance |
            | `raise ValueError` | the class is instantiated with no arguments |
            | `raise` (inside `except`) | re-raise the exception being handled, traceback intact |
            | `raise New(...) from original` | explicit chaining: sets `__cause__` |
            | `raise New(...)` inside `except` | implicit chaining: sets `__context__` automatically |
            | `raise New(...) from None` | hide the context (`__suppress_context__ = True`) |

            Only instances or subclasses of `BaseException` can be raised; anything else is a
            `TypeError`.
            """
        ),
        code(
            '''
            def raise_value(value: object) -> None:
                """Raise whatever is passed in."""
                raise value  # type: ignore[misc]


            for candidate in (ValueError("negative quantity"), ValueError, "just a string"):
                try:
                    raise_value(candidate)
                except Exception as error:
                    print(f"{candidate!r:<36} -> {type(error).__name__}: {error}")
            '''
        ),
        md(
            """
            **Bare re-raise.** Inside an `except` block, a plain `raise` re-raises the current
            exception with its original traceback, which is how you add a side effect (logging,
            a metric, a rollback) without changing what the caller sees. Outside an `except`
            block there is nothing to re-raise.
            """
        ),
        code(
            '''
            failed_charges: list[str] = []


            def charge_card(card_number: str) -> None:
                """Record the failure, then let the original error continue."""
                try:
                    int(card_number)
                except ValueError:
                    failed_charges.append(card_number)
                    raise


            print(f"{raised_error_name(lambda: charge_card('4111-x'))=}, {failed_charges=}")


            def reraise_with_nothing_active() -> None:
                """A bare raise with no exception being handled."""
                raise


            try:
                reraise_with_nothing_active()
            except RuntimeError as error:
                print(f"RuntimeError: {error}")
            '''
        ),
        md(
            """
            **Explicit chaining with `from`.** When you translate a low-level error into a
            domain error, chain it: `raise LookupError(...) from error` stores the original in
            `__cause__`, and the traceback shows both, joined by *"The above exception was the
            direct cause of the following exception"*.

            `chain_lines(error)` keeps only the unindented lines of the formatted traceback (the
            exception lines and the joining sentences); the indented `File …` lines contain
            machine-specific paths.
            """
        ),
        code(
            '''
            def chain_lines(error: BaseException) -> list[str]:
                """Return the unindented lines of the full traceback (no file paths)."""
                formatted = "".join(traceback.format_exception(error))
                return [line for line in formatted.splitlines() if line and not line[0].isspace()]


            CATALOG = {"TEA-500G": 249}


            def unit_price(sku: str) -> int:
                """Translate KeyError into a domain-level LookupError, keeping the cause."""
                try:
                    return CATALOG[sku]
                except KeyError as error:
                    raise LookupError(f"unknown SKU {sku!r}") from error


            try:
                unit_price("SOAP-3PK")
            except LookupError as error:
                print(f"{error.__cause__=}")
                print("\\n".join(chain_lines(error)))
            '''
        ),
        md(
            """
            **Implicit chaining.** Raising inside an `except` block without `from` still records
            the exception being handled, in `__context__`, and the traceback says *"During
            handling of the above exception, another exception occurred"*. This usually signals a
            bug in the handler itself, here a typo-like `TypeError`.
            """
        ),
        code(
            '''
            def parse_discount(text: str) -> int:
                """The handler itself fails, so the second error carries the first as context."""
                try:
                    return int(text)
                except ValueError:
                    return len(None)  # type: ignore[arg-type]  (bug in the handler)


            try:
                parse_discount("ten")
            except TypeError as error:
                print(f"{error.__cause__=}, {error.__context__=}")
                print("\\n".join(chain_lines(error)))
            '''
        ),
        md(
            """
            **`from None`** hides the context when it is noise to the caller (an implementation
            detail). Note that `__context__` is still stored; `__suppress_context__ = True` only
            tells the traceback printer not to show it.
            """
        ),
        code(
            '''
            def environment_name(settings: dict[str, str]) -> str:
                """Raise a clean error; the internal KeyError is hidden from the traceback."""
                try:
                    return settings["APP_ENV"]
                except KeyError:
                    raise RuntimeError("APP_ENV is not configured") from None


            try:
                environment_name({})
            except RuntimeError as error:
                print(f"{error.__cause__=}, {error.__context__=}, {error.__suppress_context__=}")
                print("\\n".join(chain_lines(error)))
            '''
        ),
        md("#### Predict the output"),
        *predict_cells(
            snippet="""
            try:
                try:
                    raise ValueError("payment declined")
                finally:
                    raise RuntimeError("cleanup failed")
            except Exception as error:
                print(type(error).__name__, "|", type(error.__context__).__name__)
            """,
            answer="""
            `RuntimeError | ValueError`. An exception raised in `finally` replaces the one in
            flight; the original survives only as `__context__`. That is why cleanup code should
            not raise.
            """,
            proof="""
            try:
                try:
                    raise ValueError("payment declined")
                finally:
                    raise RuntimeError("cleanup failed")
            except Exception as error:
                print(type(error).__name__, "|", type(error.__context__).__name__)
            """,
        ),
    ]


def _exception_object_cells() -> list[NotebookNode]:
    """1.14.4 Exception objects."""
    return [
        md(
            """
            ### 1.14.4 Exception objects

            An exception is an ordinary object. The attributes worth knowing:

            | Attribute / function | What it holds |
            | --- | --- |
            | `args` | the tuple of constructor arguments; `str(error)` is `args[0]` if there is one argument, else `str(args)` |
            | `__traceback__` | linked list of traceback entries (frame + line), most recent last |
            | `__cause__`, `__context__`, `__suppress_context__` | chaining (1.14.3) |
            | `add_note(text)` / `__notes__` | extra lines shown after the message (*New in 3.11*, PEP 678) |
            | `traceback.format_exception(error)` | the full printed traceback as a list of strings |

            **`args`** first. Some built-ins add attributes on top: `OSError` splits its
            arguments into `errno`, `strerror` and `filename`. `KeyError` uses the `repr` of the
            key as its message, which is why it prints with quotes.
            """
        ),
        code(
            """
            single = ValueError("quantity must be positive")
            several = ValueError("quantity must be positive", -3)
            print(f"{single.args=}, {str(single)=}")
            print(f"{several.args=}, {str(several)=}")
            print(f"{str(KeyError('sku'))=}  (repr of the key)")

            try:
                open(scratch_dir / "no-such-report.txt", encoding="utf-8")
            except OSError as error:
                print(f"{error.errno=}, {error.strerror=}, {error.filename.endswith('report.txt')=}")
            """
        ),
        md(
            """
            **`__traceback__`** is a chain of `traceback` objects linked by `tb_next`. Each one
            points at a frame (`tb_frame`) and a line number (`tb_lineno`), which is exactly what
            the printed traceback lists. Walking it shows the call path from where the exception
            was caught down to where it was raised.
            """
        ),
        code(
            '''
            def load_cart(cart_id: int) -> dict[str, int]:
                """Fails two calls deep."""
                return parse_cart_row("rice,two")


            def parse_cart_row(row: str) -> dict[str, int]:
                """Raise ValueError on a bad quantity."""
                sku, quantity = row.split(",")
                return {sku: int(quantity)}


            try:
                load_cart(7)
            except ValueError as error:
                frame_names = []
                traceback_entry: TracebackType | None = error.__traceback__
                while traceback_entry is not None:
                    frame_names.append(traceback_entry.tb_frame.f_code.co_name)
                    traceback_entry = traceback_entry.tb_next
                print(" -> ".join(frame_names))
            '''
        ),
        md(
            """
            **`add_note`** (*New in 3.11*, PEP 678) attaches context without changing the
            exception type or message: which row of a file, which request, which retry attempt.
            Notes are stored in `__notes__` and printed under the message.
            """
        ),
        code(
            '''
            def import_price_rows(rows: list[str]) -> list[int]:
                """Parse prices; on failure, note which row broke and re-raise."""
                prices = []
                for row_number, row in enumerate(rows, start=1):
                    try:
                        prices.append(int(row))
                    except ValueError as error:
                        error.add_note(f"while importing row {row_number}: {row!r}")
                        error.add_note("hint: prices are whole rupees")
                        raise
                return prices


            try:
                import_price_rows(["249", "640", "1,299"])
            except ValueError as error:
                print(f"{error.__notes__=}")
                print("\\n".join(chain_lines(error)))
            '''
        ),
        md(
            """
            **`traceback.format_exception(error)`** (single-argument form since 3.10) returns the
            same text the interpreter would print, as a list of strings ending in newlines. Use it
            to put tracebacks in log records or API error reports. `format_exception_only` gives
            only the final line(s), message plus notes. The frame lines contain file paths, so
            the cell prints only the first line, the line count and the last lines.
            """
        ),
        code(
            """
            try:
                import_price_rows(["10", "ten"])
            except ValueError as error:
                full_lines = "".join(traceback.format_exception(error)).splitlines()
                print(f"first line: {full_lines[0]}")
                print(f"{len(full_lines)} lines in total; last three:")
                print("\\n".join(full_lines[-3:]))
                print(f"{traceback.format_exception_only(error)=}")
            """
        ),
    ]


def _custom_hierarchy_cells() -> list[NotebookNode]:
    """1.14.5 Custom exception hierarchies."""
    return [
        md(
            """
            ### 1.14.5 Custom exception hierarchies

            An application defines **one base class** for its own errors, then specific
            subclasses. Callers can catch everything from your code with `except AppError`, or one
            case precisely. Each class carries what a handler needs as attributes, here the HTTP
            status code and a stable machine-readable `error_code`.

            | Class | Also a | HTTP status | Extra attributes |
            | --- | --- | --- | --- |
            | `AppError` | `Exception` | 500 | `message`, `details` |
            | `ValidationError` | `ValueError` | 422 | `field` |
            | `NotFoundError` | `LookupError` | 404 | `resource`, `resource_id` |

            Inheriting from a matching built-in as well (`ValidationError(AppError, ValueError)`)
            keeps older `except ValueError` code working. Class-level defaults mean subclasses
            only override what differs.
            """
        ),
        code(
            '''
            class AppError(Exception):
                """Base class for all errors raised by the shop application."""

                status_code = 500
                error_code = "internal_error"

                def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
                    super().__init__(message)
                    self.message = message
                    self.details = details or {}

                def to_dict(self) -> dict[str, Any]:
                    """Return a JSON-ready error body."""
                    return {"error": self.error_code, "message": self.message, **self.details}


            class ValidationError(AppError, ValueError):
                """Client sent a value that breaks a rule."""

                status_code = 422
                error_code = "validation_error"

                def __init__(self, field: str, message: str) -> None:
                    super().__init__(message, details={"field": field})
                    self.field = field


            class NotFoundError(AppError, LookupError):
                """A requested resource does not exist."""

                status_code = 404
                error_code = "not_found"

                def __init__(self, resource: str, resource_id: object) -> None:
                    super().__init__(f"{resource} {resource_id!r} not found", details={"resource": resource})
                    self.resource = resource
                    self.resource_id = resource_id
            '''
        ),
        md(
            """
            One handler at the edge of the application turns any `AppError` into a status code
            and body; anything else becomes a generic 500 so internal details do not leak. This is
            the shape of FastAPI exception handlers in Phase 6.
            """
        ),
        code(
            '''
            PRODUCTS = {101: {"name": "Masala tea", "price": 249}}


            def get_product(product_id: int) -> dict[str, Any]:
                """Raise domain errors instead of returning error codes."""
                if product_id <= 0:
                    raise ValidationError("product_id", "product_id must be positive")
                if product_id not in PRODUCTS:
                    raise NotFoundError("product", product_id)
                return PRODUCTS[product_id]


            def handle_request(product_id: int) -> tuple[int, dict[str, Any]]:
                """Map exceptions to (status, body), as a web framework would."""
                try:
                    return 200, get_product(product_id)
                except AppError as error:
                    return error.status_code, error.to_dict()
                except Exception:
                    return 500, {"error": "internal_error", "message": "unexpected error"}


            for requested_id in (101, 0, 999):
                print(handle_request(requested_id))
            '''
        ),
        md(
            """
            Because of the second base class, the same exceptions are caught by built-in
            categories too, and `isinstance` checks follow the MRO:
            """
        ),
        code(
            """
            missing = NotFoundError("order", 42)
            print(" -> ".join(cls.__name__ for cls in NotFoundError.__mro__))
            print(f"{isinstance(missing, LookupError)=}, {missing.status_code=}, {missing.resource_id=}")
            print(f"{raised_error_name(lambda: get_product(-1))=}")
            try:
                get_product(-1)
            except ValueError as error:
                print(f"plain except ValueError still works: {error}")
            """
        ),
    ]


def _exception_group_cells() -> list[NotebookNode]:
    """1.14.6 Exception groups."""
    return [
        md(
            """
            ### 1.14.6 Exception groups

            *New in 3.11* (PEP 654). Some operations fail in several independent ways at once:
            validating a form, running tasks concurrently (`asyncio.TaskGroup`, Phase 5),
            retrying several hosts. An **`ExceptionGroup(message, exceptions)`** bundles them into
            one raisable object. Groups can be nested.

            | Class | Can contain |
            | --- | --- |
            | `ExceptionGroup` | only `Exception` subclasses (it is itself an `Exception`) |
            | `BaseExceptionGroup` | any `BaseException`; constructing it with only `Exception`s actually returns an `ExceptionGroup` |
            """
        ),
        code(
            """
            nightly_failures = ExceptionGroup(
                "nightly jobs failed",
                [
                    ConnectionError("payments API unreachable"),
                    ValueError("bad row in inventory.csv"),
                    ExceptionGroup("email batch", [TimeoutError("smtp 1"), TimeoutError("smtp 2")]),
                ],
            )
            print(f"{nightly_failures.message=}")
            print(f"{len(nightly_failures.exceptions)=}")
            print(f"{str(nightly_failures)=}")
            print(f"{type(BaseExceptionGroup('m', [ValueError()])).__name__=}")
            print(f"{raised_error_name(lambda: ExceptionGroup('m', [KeyboardInterrupt()]))=}")
            """
        ),
        md(
            """
            **`except*`** handles groups. Each `except* SomeError` clause receives a **subgroup**
            with all matching leaves (nesting preserved) and runs at most once. Clauses are tried
            in order; leaves no clause handles are **re-raised** in a new group. A plain
            exception that reaches `except*` is wrapped in a group first.

            `check_services()` fails three ways; the `except*` handlers deal with network
            problems, and the `ValueError` propagates out to the outer `try`.
            """
        ),
        code(
            '''
            def check_services() -> None:
                """Collect every health-check failure instead of stopping at the first."""
                failures: list[Exception] = []
                for service, problem in [
                    ("payments", ConnectionError("refused")),
                    ("search", TimeoutError("5 s")),
                    ("config", ValueError("missing API key")),
                    ("email", TimeoutError("10 s")),
                ]:
                    problem.add_note(f"service: {service}")
                    failures.append(problem)
                raise ExceptionGroup("health check failed", failures)


            try:
                try:
                    check_services()
                except* ConnectionError as network_group:
                    print(f"reconnect later: {[str(e) for e in network_group.exceptions]}")
                except* TimeoutError as slow_group:
                    print(
                        f"{len(slow_group.exceptions)} timeouts: "
                        f"{[e.__notes__[0] for e in slow_group.exceptions]}"
                    )
            except ExceptionGroup as leftover:
                print(f"re-raised: {leftover.message!r} with {leftover.exceptions!r}")
            '''
        ),
        md(
            """
            Rules that differ from `except`: a plain exception is wrapped; `except` and `except*`
            cannot be mixed on one `try`; `return`, `break` and `continue` are not allowed in an
            `except*` block (the remainder still has to be re-raised).
            """
        ),
        code(
            """
            try:
                raise ValueError("single error")
            except* ValueError as wrapped_group:
                print(f"{wrapped_group!r}")

            print(compile_error("try:\\n    pass\\nexcept* ValueError:\\n    pass\\nexcept TypeError:\\n    pass"))
            print(compile_error("def f():\\n    try:\\n        pass\\n    except* ValueError:\\n        return 1"))
            """
        ),
        md(
            """
            **`split` and `subgroup`** are what `except*` uses underneath, and you can call them
            directly. Both take an exception class (or tuple), or a predicate function called on
            every leaf, and preserve the nesting.

            | Method | Returns |
            | --- | --- |
            | `group.subgroup(condition)` | a group of the matching leaves, or `None` |
            | `group.split(condition)` | `(matching_group_or_None, rest_group_or_None)` |
            """
        ),
        code(
            """
            timeouts = nightly_failures.subgroup(TimeoutError)
            print(f"{timeouts!r}")

            network_part, other_part = nightly_failures.split((ConnectionError, TimeoutError))
            print(f"{network_part.exceptions=}")
            print(f"{other_part.exceptions=}")

            mentions_smtp = nightly_failures.subgroup(lambda leaf: "smtp" in str(leaf))
            print(f"{mentions_smtp!r}")
            print(f"{nightly_failures.subgroup(KeyError)=}")
            """
        ),
    ]


def _eafp_cells() -> list[NotebookNode]:
    """1.14.7 EAFP vs LBYL."""
    return [
        md(
            """
            ### 1.14.7 EAFP vs LBYL

            Unit 1.9.6 previewed the two styles with `parse_quantity_lbyl` / `parse_quantity_eafp`:

            | Style | Shape | Python's default? |
            | --- | --- | --- |
            | LBYL, *look before you leap* | `if can_do(x): do(x)` | no |
            | EAFP, *easier to ask forgiveness than permission* | `try: do(x)` / `except Failure:` | yes |

            **TOCTOU races** (time of check to time of use). With LBYL, the world can change
            between the check and the use: another process deletes the file, another thread pops
            the key. The check passed, the use still fails. The demo simulates the other process
            with an `on_gap` callback that deletes the file between the two steps.
            """
        ),
        code(
            '''
            def read_stock_lbyl(path: Path, on_gap: Callable[[], object]) -> str | None:
                """Check, then use. on_gap stands for whatever happens in between."""
                if path.exists():
                    on_gap()
                    return path.read_text(encoding="utf-8")
                return None


            def read_stock_eafp(path: Path, on_gap: Callable[[], object]) -> str | None:
                """Just try; there is no gap between a check and a use."""
                on_gap()
                try:
                    return path.read_text(encoding="utf-8")
                except FileNotFoundError:
                    return None


            stock_path = scratch_dir / "unit_1_14_stock.txt"
            for reader in (read_stock_lbyl, read_stock_eafp):
                stock_path.write_text("tea=4", encoding="utf-8")
                try:
                    print(f"{reader.__name__}: {reader(stock_path, stock_path.unlink)!r}")
                except FileNotFoundError as error:
                    print(f"{reader.__name__}: check passed, then {type(error).__name__}")
            '''
        ),
        md(
            """
            **Zero-cost `try`** (*Changed in 3.11*). Older CPython executed a `SETUP_FINALLY`
            instruction on entry to every `try`. Since 3.11, the compiler records the protected
            ranges in a side **exception table** (shown in 1.14.12), so entering a `try` costs
            nothing; only actually *raising* is expensive (creating the exception object and
            traceback, unwinding, matching clauses).

            The measurement: a dict lookup with and without a surrounding `try`, then the miss
            case handled by `except KeyError` versus `dict.get`. Timings vary by machine; the
            ratios are what matter.
            """
        ),
        code(
            '''
            menu = {"tea": 30, "coffee": 60}


            def lookup_plain(prices: dict[str, int]) -> int:
                """No try at all."""
                return prices["tea"]


            def lookup_in_try(prices: dict[str, int]) -> int:
                """Same lookup inside a try that never fires."""
                try:
                    return prices["tea"]
                except KeyError:
                    return 0


            def miss_with_except(prices: dict[str, int]) -> int:
                """The key is missing: an exception is raised and caught every call."""
                try:
                    return prices["juice"]
                except KeyError:
                    return 0


            def miss_with_get(prices: dict[str, int]) -> int:
                """The key is missing: get returns the default, no exception."""
                return prices.get("juice", 0)


            CALLS = 200_000
            for candidate in (lookup_plain, lookup_in_try, miss_with_except, miss_with_get):
                best = min(timeit.repeat(functools.partial(candidate, menu), number=CALLS, repeat=5))
                print(f"{candidate.__name__:<17} {best / CALLS * 1e9:6.1f} ns per call")
            '''
        ),
        md(
            """
            The first two lines are about equal (zero-cost entry); the raised-and-caught miss is
            several times slower than `get`. That gives the rule for **when LBYL is better**:

            | Situation | Prefer | Why |
            | --- | --- | --- |
            | Failure is rare | EAFP | the `try` is free, the check would run every time |
            | Failure is common (a miss on most calls) | LBYL / `get` / `in` | raising costs far more than a check |
            | The resource can change underneath you (files, shared state) | EAFP | no TOCTOU gap |
            | The operation has side effects that cannot be undone halfway | LBYL | validate everything **before** the first write |
            | You need a helpful message for a user | LBYL | the check knows which rule failed |

            The side-effect row in code: charging and then discovering the stock is short leaves
            the system half-updated, so check first.
            """
        ),
        code(
            '''
            def place_order(stock: dict[str, int], charges: list[int], sku: str, quantity: int) -> str:
                """Validate before any side effect; then charge and reserve."""
                if stock.get(sku, 0) < quantity:
                    return f"rejected: only {stock.get(sku, 0)} {sku} left"
                charges.append(quantity * 30)
                stock[sku] -= quantity
                return "placed"


            warehouse = {"tea": 2}
            card_charges: list[int] = []
            print(place_order(warehouse, card_charges, "tea", 5), card_charges, warehouse)
            print(place_order(warehouse, card_charges, "tea", 2), card_charges, warehouse)
            '''
        ),
    ]


def _logging_cells() -> list[NotebookNode]:
    """1.14.8 Logging exceptions."""
    return [
        md(
            """
            ### 1.14.8 Logging exceptions

            Inside an `except` block, **`logger.exception(message)`** logs at `ERROR` level and
            appends the full traceback (it is `logger.error(message, exc_info=True)`). Call it
            only while an exception is being handled. Pass values as `%s` arguments instead of an
            f-string: the message is formatted only if the record is actually emitted.

            The demo sends the logger's output to an in-memory stream so the cell can print the
            interesting lines (the traceback frames contain machine-specific paths). Phase 4
            covers logging configuration properly.
            """
        ),
        code(
            '''
            log_stream = io.StringIO()
            payments_logger = logging.getLogger("shop.payments")
            payments_logger.handlers.clear()
            stream_handler = logging.StreamHandler(log_stream)
            stream_handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
            payments_logger.addHandler(stream_handler)
            payments_logger.setLevel(logging.INFO)
            payments_logger.propagate = False


            def capture_payment(order_id: int, amount_text: str) -> int:
                """Log the failure with its traceback, then re-raise for the caller."""
                try:
                    return int(amount_text)
                except ValueError:
                    payments_logger.exception("could not capture payment for order %s", order_id)
                    raise


            print(f"{raised_error_name(lambda: capture_payment(42, '49x'))=}")
            logged_lines = log_stream.getvalue().splitlines()
            print(f"{len(logged_lines)} log lines; first two and last:")
            print("\\n".join([*logged_lines[:2], logged_lines[-1]]))
            '''
        ),
        md(
            """
            **Never swallow errors.** Every `except` must do one of: handle the failure fully
            (fall back to a value the caller expects), translate it (`raise … from`), or record
            it and re-raise. The anti-patterns:

            | Anti-pattern | What goes wrong |
            | --- | --- |
            | `except Exception: pass` | bugs (typos, wrong types) disappear silently |
            | `except Exception: return None` | the caller cannot tell "no result" from "broken" |
            | log and continue, when the caller needs to know | the program carries on with bad state |
            | `except` around a large block | catches errors from lines you never meant to guard |

            The cell shows the first one hiding a real bug: a misspelled attribute raises
            `AttributeError`, which the broad handler turns into a plausible default.
            """
        ),
        code(
            '''
            def shipping_fee_swallowed(order: dict[str, Any]) -> int:
                """Bug: .uper() is a typo, but the broad except hides it."""
                try:
                    return 0 if order["city"].uper() == "PUNE" else 50  # type: ignore[attr-defined]
                except Exception:
                    return 50


            def shipping_fee(order: dict[str, Any]) -> int:
                """Catch only the failure you expect: a missing city."""
                try:
                    city = order["city"]
                except KeyError:
                    return 50
                return 0 if city.upper() == "PUNE" else 50


            print(f"{shipping_fee_swallowed({'city': 'Pune'})=}  (wrong, and no error)")
            print(f"{shipping_fee({'city': 'Pune'})=}")
            print(f"{shipping_fee({})=}")
            '''
        ),
    ]


def _with_statement_cells() -> list[NotebookNode]:
    """1.14.9 The with statement."""
    return [
        md(
            """
            ### 1.14.9 The `with` statement

            `with EXPRESSION as name:` works with any **context manager**: an object with two
            methods.

            | Method | Called | Receives | Returns |
            | --- | --- | --- | --- |
            | `__enter__(self)` | on entry | — | the value bound to `name` (often `self`) |
            | `__exit__(self, exc_type, exc, tb)` | on every exit | `None, None, None`, or the exception details | truthy to **suppress** the exception |

            The manager below prints what `__exit__` receives on a normal exit and on an error.
            """
        ),
        code(
            '''
            class ExitInspector:
                """Show the arguments __exit__ receives."""

                def __enter__(self) -> str:
                    print("__enter__ called")
                    return "value bound by as"

                def __exit__(
                    self,
                    exc_type: type[BaseException] | None,
                    exc: BaseException | None,
                    tb: TracebackType | None,
                ) -> bool:
                    print(f"__exit__({exc_type=}, {exc=}, traceback given: {tb is not None})")
                    return False


            with ExitInspector() as bound_value:
                print(f"body: {bound_value=}")
            try:
                with ExitInspector():
                    raise ValueError("body failed")
            except ValueError as error:
                print(f"propagated: {error!r}")
            '''
        ),
        md(
            """
            **Suppression by returning `True`.** If `__exit__` returns a truthy value, the
            exception is discarded and execution continues after the `with` block. Use this
            deliberately and narrowly (here: only the listed classes). Returning truthy by accident
            (for example returning a non-empty list) swallows every error.
            """
        ),
        code(
            '''
            class IgnoreErrors:
                """Suppress only the listed exception classes (a hand-written contextlib.suppress)."""

                def __init__(self, *error_types: type[Exception]) -> None:
                    self.error_types = error_types

                def __enter__(self) -> None:
                    return None

                def __exit__(
                    self,
                    exc_type: type[BaseException] | None,
                    exc: BaseException | None,
                    tb: TracebackType | None,
                ) -> bool:
                    return exc_type is not None and issubclass(exc_type, self.error_types)


            with IgnoreErrors(KeyError):
                {}["missing"]
                print("not reached")
            print("continued after a suppressed KeyError")


            def convert_inside_ignore() -> int:
                """A ValueError is not in the list, so it is not suppressed."""
                with IgnoreErrors(KeyError):
                    return int("x")
                return 0


            print(f"{raised_error_name(convert_inside_ignore)=}")
            '''
        ),
        md(
            """
            **The desugared form** (PEP 343). `with` is shorthand for roughly the code below;
            like every special method, `__enter__` and `__exit__` are looked up on the type:

            ```python
            manager = EXPRESSION
            enter = type(manager).__enter__      # looked up on the type, like other dunders
            exit_ = type(manager).__exit__
            value = enter(manager)
            try:
                name = value
                BODY
            except BaseException as error:
                if not exit_(manager, type(error), error, error.__traceback__):
                    raise                         # not suppressed
            else:
                exit_(manager, None, None, None)
            ```

            The cell runs this expansion by hand with `ExitInspector` and prints the same lines as
            the real `with` above.
            """
        ),
        code(
            """
            manager = ExitInspector()
            enter_method = type(manager).__enter__
            exit_method = type(manager).__exit__
            entered_value = enter_method(manager)
            try:
                print(f"body: {entered_value=}")
                raise ValueError("body failed")
            except BaseException as error:
                if not exit_method(manager, type(error), error, error.__traceback__):
                    print(f"would re-raise: {error!r}")
            else:
                exit_method(manager, None, None, None)
            """
        ),
        md(
            """
            **Multiple managers.** `with A() as a, B() as b:` is the same as nesting: entered left
            to right, exited **right to left** (LIFO). Since 3.10 the list can be wrapped in
            parentheses across lines. If entering the second manager fails, the first one is
            still exited.
            """
        ),
        code(
            '''
            class Tracked:
                """Log enter/exit; optionally fail on enter."""

                def __init__(self, name: str, events: list[str], fail_on_enter: bool = False) -> None:
                    self.name, self.events, self.fail_on_enter = name, events, fail_on_enter

                def __enter__(self) -> Tracked:
                    if self.fail_on_enter:
                        raise OSError(f"cannot open {self.name}")
                    self.events.append(f"enter {self.name}")
                    return self

                def __exit__(self, *exc_info: object) -> None:
                    self.events.append(f"exit {self.name}")


            events: list[str] = []
            with (
                Tracked("database", events) as database,
                Tracked("cache", events) as cache,
            ):
                events.append(f"body uses {database.name} and {cache.name}")
            print(events)

            events = []
            try:
                with Tracked("database", events), Tracked("cache", events, fail_on_enter=True):
                    events.append("body")
            except OSError as error:
                events.append(f"caught {error}")
            print(events)
            '''
        ),
        md(
            """
            #### Example: `Timer`

            A timing context manager measures a block, not a whole function (the `@timer`
            decorator from 1.12.3 times calls). `__exit__` reports even when the block raises,
            and does not suppress. Lab 1.14 asks for a richer `StopwatchTimer`; the Phase 1
            Project times its run with this `Timer`.
            """
        ),
        code(
            '''
            class Timer:
                """Time a with block and report "<label> took <ms> ms"."""

                def __init__(self, label: str, report: Callable[[str], object] = print) -> None:
                    self.label = label
                    self.report = report
                    self.elapsed_seconds = 0.0

                def __enter__(self) -> Timer:
                    self._started = time.perf_counter()
                    return self

                def __exit__(self, *exc_info: object) -> None:
                    self.elapsed_seconds = time.perf_counter() - self._started
                    self.report(f"{self.label} took {self.elapsed_seconds * 1000:.2f} ms")
            '''
        ),
        md("Using it, including on a failing block (durations vary by machine):"),
        code(
            """
            with Timer("sum of squares") as squares_timer:
                total = sum(number * number for number in range(200_000))
            print(f"{total=}, {squares_timer.elapsed_seconds > 0=}")

            try:
                with Timer("failing block"):
                    raise ConnectionError("upstream down")
            except ConnectionError as error:
                print(f"still reported, then propagated: {error!r}")
            """
        ),
        md(
            """
            #### Example: `DatabaseTransaction`

            The classic use: commit if the block succeeds, roll back if it raises, and let the
            exception continue. The demo uses an in-memory SQLite database (standard library, no
            server). A `CHECK` constraint makes an overdraft fail halfway through a transfer; the
            rollback undoes the first `UPDATE`.
            """
        ),
        code(
            '''
            class DatabaseTransaction:
                """Commit on success, roll back on any exception (never suppress)."""

                def __init__(self, connection: sqlite3.Connection) -> None:
                    self.connection = connection

                def __enter__(self) -> sqlite3.Cursor:
                    self.connection.execute("BEGIN")
                    return self.connection.cursor()

                def __exit__(
                    self,
                    exc_type: type[BaseException] | None,
                    exc: BaseException | None,
                    tb: TracebackType | None,
                ) -> bool:
                    if exc_type is None:
                        self.connection.commit()
                    else:
                        self.connection.rollback()
                    return False


            bank = sqlite3.connect(":memory:", isolation_level=None)
            bank.execute("CREATE TABLE accounts (name TEXT PRIMARY KEY, balance INTEGER CHECK (balance >= 0))")
            inserted = bank.executemany("INSERT INTO accounts VALUES (?, ?)", [("asha", 500), ("ravi", 100)])
            print(f"{inserted.rowcount} accounts created")
            '''
        ),
        md("A transfer that succeeds, then one that overdraws `ravi`:"),
        code(
            '''
            def transfer(connection: sqlite3.Connection, source: str, target: str, amount: int) -> str:
                """Move money inside one transaction."""
                try:
                    with DatabaseTransaction(connection) as cursor:
                        cursor.execute(
                            "UPDATE accounts SET balance = balance + ? WHERE name = ?", (amount, target)
                        )
                        cursor.execute(
                            "UPDATE accounts SET balance = balance - ? WHERE name = ?", (amount, source)
                        )
                except sqlite3.IntegrityError as error:
                    return f"rolled back ({error})"
                return "committed"


            def balances(connection: sqlite3.Connection) -> dict[str, int]:
                """Current balances by name."""
                return dict(connection.execute("SELECT name, balance FROM accounts ORDER BY name"))


            print(transfer(bank, "asha", "ravi", 200), balances(bank))
            print(transfer(bank, "ravi", "asha", 1_000), balances(bank))
            '''
        ),
        md(
            """
            > **Note:** a `sqlite3.Connection` is itself a context manager, but its `__exit__`
            > commits or rolls back and does **not close** the connection. Use
            > `contextlib.closing(connection)` (1.14.10) to close it.
            """
        ),
    ]


def _contextlib_cells() -> list[NotebookNode]:
    """1.14.10 contextlib."""
    return [
        md(
            """
            ### 1.14.10 `contextlib`

            The standard library's toolbox for context managers. Each row gets a demo below.

            | API | What it does | Typical use |
            | --- | --- | --- |
            | `@contextmanager` | turns a one-`yield` generator into a context manager | most hand-written managers |
            | `suppress(*errors)` | ignores the listed exceptions | "delete if present" |
            | `closing(thing)` | calls `thing.close()` on exit | objects with `close()` but no `with` support |
            | `redirect_stdout(stream)` | sends `print` output to another stream | capturing output in tests |
            | `nullcontext(value)` | does nothing, returns `value` | "maybe a manager" code paths |
            | `chdir(path)` | changes the working directory, restores it on exit (*New in 3.11*) | scripts, tests |
            | `ExitStack()` | enters a variable number of managers and callbacks, unwinds them LIFO | "open N things" |
            | `AbstractContextManager` | ABC with a default `__enter__` returning `self` | class-based managers, `isinstance` checks |

            #### `@contextmanager`

            The code before `yield` is `__enter__`, the yielded value is bound by `as`, the code
            after `yield` is `__exit__`. If the body raises, the exception is **thrown into the
            generator at the `yield`**, so cleanup must sit in `finally`, or it is skipped. The
            demo leases a connection from a pool; the unsafe version leaks it on an error.
            """
        ),
        code(
            '''
            @contextmanager
            def leased_connection_unsafe(pool: list[str]) -> Iterator[str]:
                """Bug: no try/finally, so an exception in the body skips the return to the pool."""
                connection = pool.pop()
                yield connection
                pool.append(connection)


            @contextmanager
            def leased_connection(pool: list[str]) -> Iterator[str]:
                """Return the connection to the pool on every exit."""
                connection = pool.pop()
                try:
                    yield connection
                finally:
                    pool.append(connection)


            for lease in (leased_connection_unsafe, leased_connection):
                pool = ["conn-1", "conn-2"]
                with suppress(RuntimeError), lease(pool) as connection:
                    raise RuntimeError(f"query failed on {connection}")
                print(f"{lease.__name__:<25} pool after an error: {pool}")
            '''
        ),
        md(
            """
            A `@contextmanager` object also works as a **decorator** (it is a
            `ContextDecorator`): each call of the decorated function runs inside a fresh `with`.
            """
        ),
        code(
            '''
            shared_pool = ["conn-1"]


            @leased_connection(shared_pool)
            def nightly_report() -> str:
                """Runs while a connection is leased from shared_pool."""
                return f"pool during the call: {shared_pool}"


            print(nightly_report())
            print(f"pool after the call: {shared_pool}")
            '''
        ),
        md(
            """
            #### `suppress`

            `with suppress(FileNotFoundError):` replaces a `try` / `except …: pass`. Use it only
            when ignoring the error is truly the intent. (For files specifically,
            `Path.unlink(missing_ok=True)` does the same.)
            """
        ),
        code(
            """
            temporary_report = scratch_dir / "unit_1_14_temp_report.txt"
            temporary_report.write_text("draft", encoding="utf-8")
            for attempt in (1, 2):
                with suppress(FileNotFoundError):
                    temporary_report.unlink()
                    print(f"attempt {attempt}: deleted")
                    continue
                print(f"attempt {attempt}: already gone, FileNotFoundError suppressed")
            """
        ),
        md(
            """
            #### `closing`

            For an object that has `close()` but is not a context manager (older APIs, some
            third-party clients), `closing(thing)` returns `thing` from `__enter__` and calls
            `thing.close()` on exit.
            """
        ),
        code(
            '''
            class LegacyPrinterClient:
                """Has close() but no __enter__/__exit__."""

                def __init__(self) -> None:
                    self.closed = False

                def print_label(self, text: str) -> str:
                    return f"printed {text!r}"

                def close(self) -> None:
                    self.closed = True


            with closing(LegacyPrinterClient()) as printer:
                print(printer.print_label("ORDER-42"))
            print(f"{printer.closed=}")


            def use_without_closing() -> None:
                """A plain with fails: the class has no __enter__/__exit__."""
                with LegacyPrinterClient():  # type: ignore[attr-defined]
                    pass


            print(f"{raised_error_name(use_without_closing)=}")
            '''
        ),
        md(
            """
            #### `redirect_stdout`

            Temporarily points `sys.stdout` at another stream, so everything `print` writes is
            captured. `redirect_stderr` does the same for `sys.stderr`. It changes global state,
            so it is not safe across threads.
            """
        ),
        code(
            '''
            def noisy_import_step() -> int:
                """Prints progress as a side effect."""
                print("importing 3 rows")
                print("done")
                return 3


            captured_output = io.StringIO()
            with redirect_stdout(captured_output):
                imported_count = noisy_import_step()
            print(f"{imported_count=}, {captured_output.getvalue()=}")
            '''
        ),
        md(
            """
            #### `nullcontext`

            A manager that does nothing and returns its argument. It removes an `if` when a
            resource is sometimes managed and sometimes not, for example "accept a path (open and
            close it) or an already-open stream (leave it open)".
            """
        ),
        code(
            '''
            def count_lines(source: Path | io.StringIO) -> int:
                """Open a path ourselves, or use a caller-owned stream without closing it."""
                manager = source.open(encoding="utf-8") if isinstance(source, Path) else nullcontext(source)
                with manager as stream:
                    return sum(1 for _ in stream)


            lines_path = scratch_dir / "unit_1_14_lines.txt"
            lines_path.write_text("a\\nb\\nc\\n", encoding="utf-8")
            caller_stream = io.StringIO("x\\ny\\n")
            print(f"{count_lines(lines_path)=}, {count_lines(caller_stream)=}, {caller_stream.closed=}")
            with nullcontext(42) as answer:
                print(f"{answer=}")
            '''
        ),
        md(
            """
            #### `chdir`

            *New in 3.11.* Changes the process working directory for the block and always changes
            it back. Like `redirect_stdout` it changes process-wide state, so avoid it in threaded
            or async code; prefer passing absolute paths.
            """
        ),
        code(
            """
            directory_before = Path.cwd()
            with chdir(scratch_dir):
                print(f"inside:  cwd name = {Path.cwd().name}")
                print(f"{Path('unit_1_14_lines.txt').exists()=}  (relative to the new cwd)")
            print(f"after:   restored = {Path.cwd() == directory_before}")
            """
        ),
        md(
            """
            #### `ExitStack`

            For a number of managers known only at run time. `enter_context(manager)` enters one
            and schedules its exit; `callback(function, *args)` schedules any cleanup function;
            everything unwinds in reverse order when the stack exits, even after an error.
            `pop_all()` moves the pending cleanups to a new stack: the pattern for "acquire
            everything, and only keep it if all acquisitions succeed".
            """
        ),
        code(
            """
            cleanup_log: list[str] = []
            with ExitStack() as stack:
                for name in ("orders", "payments", "audit"):
                    stack.enter_context(Tracked(name, cleanup_log))
                stack.callback(cleanup_log.append, "callback: flush metrics")
                cleanup_log.append("body runs")
            print(cleanup_log)
            """
        ),
        md("`pop_all()`: keep the acquired managers open past the `with`, then close them later."),
        code(
            '''
            def acquire_all(names: list[str], events: list[str]) -> ExitStack:
                """Enter every manager; if one fails, the ones already entered are exited."""
                with ExitStack() as stack:
                    for name in names:
                        stack.enter_context(Tracked(name, events, fail_on_enter=(name == "broken")))
                    return stack.pop_all()


            events = []
            kept_open = acquire_all(["orders", "payments"], events)
            print(f"after acquire: {events}")
            kept_open.close()
            print(f"after close:   {events}")

            events = []
            print(f"{raised_error_name(lambda: acquire_all(['orders', 'broken'], events))=}, {events=}")
            '''
        ),
        md(
            """
            #### `AbstractContextManager`

            Subclassing it gives a default `__enter__` that returns `self`, so a class-based
            manager only writes `__exit__`. It is also an ABC with a structural
            `__subclasshook__`: any class with both methods counts as a context manager for
            `isinstance`, inheritance or not.
            """
        ),
        code(
            '''
            class AuditScope(AbstractContextManager):
                """Only __exit__ is written; __enter__ comes from the ABC."""

                def __init__(self) -> None:
                    self.entries: list[str] = []

                def __exit__(self, *exc_info: object) -> None:
                    self.entries.append("scope closed")


            with AuditScope() as scope:
                scope.entries.append("work")
            print(f"{scope.entries=}")
            print(f"{isinstance(Timer('x'), AbstractContextManager)=}  (structural, no inheritance)")
            print(f"{isinstance(LegacyPrinterClient(), AbstractContextManager)=}")
            '''
        ),
    ]


def _assert_warnings_cells() -> list[NotebookNode]:
    """1.14.11 assert and warnings."""
    return [
        md(
            """
            ### 1.14.11 `assert` and `warnings`

            `assert condition, message` raises `AssertionError(message)` when the condition is
            false. It is for **internal invariants** ("this can never happen if my code is
            right"), never for validating input: running Python with **`-O`** sets `__debug__` to
            `False` and the compiler **removes every assert**. The cell runs the same script in
            child interpreters with and without `-O`.
            """
        ),
        code(
            r"""
            CHILD_ENV = {**os.environ, "PYTHON_COLORS": "0"}  # plain tracebacks (3.13+ colours them)
            ASSERT_SCRIPT = (
                "assert 1 + 1 == 3, 'arithmetic invariant broken'\n"
                "print('assert was stripped; __debug__ =', __debug__)"
            )
            for flags in ([], ["-O"]):
                completed = subprocess.run(
                    [sys.executable, *flags, "-c", ASSERT_SCRIPT],
                    capture_output=True,
                    text=True,
                    check=False,
                    env=CHILD_ENV,
                )
                last_line = (completed.stdout or completed.stderr).strip().splitlines()[-1]
                print(f"python {' '.join(flags) or '(no -O)':<8} exit={completed.returncode}  {last_line}")
            """
        ),
        md(
            """
            A classic trap: `assert (condition, "message")` asserts a non-empty **tuple**, which
            is always true. The compiler warns (`SyntaxWarning`).
            """
        ),
        code(
            """
            with warnings.catch_warnings(record=True) as assert_warnings:
                warnings.simplefilter("always")
                compile("assert (1 == 2, 'never fails')", "<demo>", "exec")
            print([f"{w.category.__name__}: {w.message}" for w in assert_warnings])
            """
        ),
        md(
            """
            **`warnings.warn(message, category, stacklevel)`** reports something the caller
            should fix without stopping the program. `stacklevel=2` blames the caller's line
            instead of the line inside your function.

            | Category | Shown by default? | Use for |
            | --- | --- | --- |
            | `UserWarning` (default) | yes | general "you probably didn't mean this" |
            | `DeprecationWarning` | only when triggered from `__main__` | API going away, for developers |
            | `FutureWarning` | yes | behaviour will change, for end users |
            | `RuntimeWarning` | yes | dubious runtime situations |
            | `SyntaxWarning` | yes | dubious syntax (compile time) |

            The demo records warnings with `catch_warnings(record=True)` so the output is
            deterministic.
            """
        ),
        code(
            '''
            def legacy_price_in_rupees(price_in_paise: int) -> float:
                """Old API: warn callers, keep working."""
                warnings.warn("use price_in_paise / 100 with Decimal", DeprecationWarning, stacklevel=2)
                return price_in_paise / 100


            with warnings.catch_warnings(record=True) as recorded:
                warnings.simplefilter("always")
                print(f"{legacy_price_in_rupees(24_900)=}")
            for recorded_warning in recorded:
                print(f"{recorded_warning.category.__name__}: {recorded_warning.message}")
            '''
        ),
        md(
            """
            **Filters** decide what happens to each warning. `warnings.simplefilter(action,
            category)` and `warnings.filterwarnings(action, message=regex, category=…,
            module=regex)` add filters; the first matching filter wins. The same filters can be
            set from outside with `-W action::Category` or `PYTHONWARNINGS`.

            | Action | Effect |
            | --- | --- |
            | `"default"` | show once per location |
            | `"always"` | show every time |
            | `"once"` | show once per message, anywhere |
            | `"module"` | show once per module |
            | `"ignore"` | never show |
            | `"error"` | raise the warning as an exception |
            """
        ),
        code(
            '''
            def noisy_conversion() -> None:
                """Emit two different warnings."""
                warnings.warn("rounding to whole rupees", UserWarning, stacklevel=2)
                warnings.warn("legacy currency code INR-OLD", DeprecationWarning, stacklevel=2)


            with warnings.catch_warnings(record=True) as kept:
                warnings.simplefilter("always")
                warnings.filterwarnings("ignore", message="rounding", category=UserWarning)
                noisy_conversion()
                noisy_conversion()
            print([str(w.message) for w in kept])
            '''
        ),
        md(
            """
            **`catch_warnings()`** saves the filter list and restores it on exit, so changes made
            inside never leak. `record=True` collects `WarningMessage` objects instead of printing.
            """
        ),
        code(
            """
            filters_before = len(warnings.filters)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                warnings.filterwarnings("error", category=RuntimeWarning)
                print(f"inside:  {len(warnings.filters) - filters_before} filters added")
            print(f"after:   {len(warnings.filters) == filters_before=}")
            """
        ),
        md(
            """
            **Escalating to errors.** The `"error"` action turns a warning into an exception,
            which is how test suites make sure no deprecated API is used (`pytest -W error`,
            Phase 4). In-process with a filter, then for a whole child interpreter with `-W`:
            """
        ),
        code(
            r"""
            with warnings.catch_warnings():
                warnings.simplefilter("error", DeprecationWarning)
                try:
                    legacy_price_in_rupees(100)
                except DeprecationWarning as error:
                    print(f"raised as an exception: {type(error).__name__}: {error}")

            WARN_SCRIPT = (
                "import warnings\nwarnings.warn('old checkout API', DeprecationWarning)\nprint('continued')"
            )
            for flags in ([], ["-W", "error::DeprecationWarning"]):
                completed = subprocess.run(
                    [sys.executable, *flags, "-c", WARN_SCRIPT],
                    capture_output=True,
                    text=True,
                    check=False,
                    env=CHILD_ENV,
                )
                outcome = completed.stdout.strip() or completed.stderr.strip().splitlines()[-1]
                print(f"{' '.join(flags) or '(default)':<28} exit={completed.returncode}  {outcome}")
            """
        ),
    ]


def _under_the_hood_cells() -> list[NotebookNode]:
    """1.14.12 Under the hood."""
    return [
        md(
            """
            ### 1.14.12 Under the hood

            **The exception table.** Since 3.11 there is no instruction that "enters" a `try`.
            Instead, each code object carries an exception table: *if an exception is raised
            between instruction offsets `start` and `end`, jump to `target` with the value stack
            cut to `depth`*. `dis` prints it after the instructions as `ExceptionTable:`, with
            `L` labels. Instruction names change between versions; the structure is the point.

            What to notice in the listing:

            - the `try` body (`L1` to `L2`) has no setup instruction at all: that is the
              zero-cost entry measured in 1.14.7;
            - `PUSH_EXC_INFO`, `CHECK_EXC_MATCH` and `POP_JUMP_IF_FALSE` implement
              `except ValueError` (an `isinstance`-style test, 1.14.1);
            - the handler ends with `STORE_FAST` / `DELETE_FAST` of `error`: the hidden
              `del error` from 1.14.2;
            - `RERAISE` re-raises when no clause matches.
            """
        ),
        code(
            '''
            def parse_quantity(text: str) -> int:
                """try / except with an as-name."""
                try:
                    return int(text)
                except ValueError as error:
                    print(error)
                    return 0


            dis.dis(parse_quantity)
            '''
        ),
        md(
            """
            The same table as data: `dis.Bytecode(...).exception_entries` lists the entries
            (offsets in bytes), and the raw encoded table lives in `co_exceptiontable`.
            """
        ),
        code(
            """
            for entry in dis.Bytecode(parse_quantity).exception_entries:
                print(
                    f"offsets {entry.start:>3}-{entry.end:<3} -> handler {entry.target:>3}  "
                    f"depth={entry.depth} lasti={entry.lasti}"
                )
            print(f"{len(parse_quantity.__code__.co_exceptiontable)=} bytes")
            """
        ),
        md(
            """
            **`with` bytecode.** In 3.14+, `LOAD_SPECIAL` looks up `__enter__` and `__exit__` on
            the **type** (3.11–3.13 used `BEFORE_WITH`). The body is covered by an exception-table
            entry whose handler runs `WITH_EXCEPT_START`, which calls `__exit__(type, value,
            traceback)` and then tests the result with `TO_BOOL`: truthy means suppress. On the
            normal path, `__exit__(None, None, None)` is a plain `CALL` with three `None`s.
            """
        ),
        code(
            '''
            def first_line(path: Path) -> str:
                """A with statement around a file."""
                with path.open(encoding="utf-8") as stream:
                    return stream.readline()


            dis.dis(first_line)
            '''
        ),
    ]


def _lab_cells() -> list[NotebookNode]:
    """Lab 1.14."""
    return [
        md(
            """
            ### Lab 1.14

            Six exercises. For each, replace the `raise NotImplementedError` in the stub, then
            run the check cell. Until then the checks print FAIL; that is expected.

            #### Exercise 1 — `parse_age(text)` with notes and chaining

            Return the age as an `int` after stripping whitespace.

            - Not a whole number (`int()` fails): raise
              `ValueError(f"invalid age: {text!r}")` **chained** from the original error
              (`__cause__`), with the note `"age must be a whole number, e.g. 42"`.
            - Outside 0–150: raise `ValueError(f"age out of range: {age}")` with the note
              `"age must be between 0 and 150"` and no cause.
            """
        ),
        code(
            '''
            def parse_age(text: str) -> int:
                """Parse an age in years, with helpful notes on failure."""
                raise NotImplementedError("Lab 1.14: implement parse_age()")
            '''
        ),
        md(
            """
            Run the checks. `caught_error(thunk)` returns the exception a call raises (or `None`),
            so the checks can look at its message, notes and cause.
            """
        ),
        code(
            '''
            def caught_error(thunk: Callable[[], object]) -> BaseException | None:
                """Return the exception thunk raises, or None."""
                try:
                    thunk()
                except BaseException as error:
                    return error
                return None


            def error_report(thunk: Callable[[], object]) -> tuple[str, str, list[str], str]:
                """(type, message, notes, cause type) of the raised exception."""
                error = caught_error(thunk)
                return (
                    type(error).__name__,
                    str(error),
                    getattr(error, "__notes__", []),
                    type(error.__cause__).__name__ if error is not None else "",
                )


            run_checks(
                [
                    ("plain", lambda: parse_age("42"), 42),
                    ("whitespace", lambda: parse_age(" 7 "), 7),
                    ("bounds", lambda: (parse_age("0"), parse_age("150")), (0, 150)),
                    (
                        "not a number",
                        lambda: error_report(lambda: parse_age("abc")),
                        (
                            "ValueError",
                            "invalid age: 'abc'",
                            ["age must be a whole number, e.g. 42"],
                            "ValueError",
                        ),
                    ),
                    ("decimal", lambda: error_report(lambda: parse_age("4.5"))[1], "invalid age: '4.5'"),
                    (
                        "too large",
                        lambda: error_report(lambda: parse_age("200")),
                        ("ValueError", "age out of range: 200", ["age must be between 0 and 150"], "NoneType"),
                    ),
                    ("negative", lambda: error_report(lambda: parse_age("-1"))[1], "age out of range: -1"),
                ]
            )
            '''
        ),
        md(
            """
            #### Exercise 2 — `load_config(path)` converting errors with `from`

            Read a JSON file (UTF-8) and return the resulting `dict`. Convert every failure into
            the given `ConfigError`, chained with `from`:

            | Failure | Message | `__cause__` |
            | --- | --- | --- |
            | file missing | `f"config file not found: {path.name}"` | the `FileNotFoundError` |
            | invalid JSON | `f"invalid JSON in {path.name} at line {lineno}"` | the `json.JSONDecodeError` (it has `.lineno`) |
            | top level is not an object | `f"config must be a JSON object, got {type_name}"` | `None` |
            """
        ),
        code(
            '''
            class ConfigError(Exception):
                """Raised when a configuration file cannot be loaded."""


            def load_config(path: Path) -> dict[str, Any]:
                """Load a JSON object from path, raising ConfigError on any failure."""
                raise NotImplementedError("Lab 1.14: implement load_config()")
            '''
        ),
        md("Run the checks. The cell writes three small files to `scratch_dir`."),
        code(
            """
            good_config = scratch_dir / "lab_1_14_good.json"
            good_config.write_text('{"debug": true, "port": 8000}', encoding="utf-8")
            broken_config = scratch_dir / "lab_1_14_broken.json"
            broken_config.write_text('{"debug": true,\\n "port": }', encoding="utf-8")
            list_config = scratch_dir / "lab_1_14_list.json"
            list_config.write_text("[1, 2]", encoding="utf-8")
            missing_config = scratch_dir / "lab_1_14_missing.json"
            run_checks(
                [
                    ("loads", lambda: load_config(good_config), {"debug": True, "port": 8000}),
                    (
                        "missing",
                        lambda: error_report(lambda: load_config(missing_config)),
                        (
                            "ConfigError",
                            "config file not found: lab_1_14_missing.json",
                            [],
                            "FileNotFoundError",
                        ),
                    ),
                    (
                        "invalid JSON",
                        lambda: error_report(lambda: load_config(broken_config)),
                        (
                            "ConfigError",
                            "invalid JSON in lab_1_14_broken.json at line 2",
                            [],
                            "JSONDecodeError",
                        ),
                    ),
                    (
                        "not an object",
                        lambda: error_report(lambda: load_config(list_config)),
                        ("ConfigError", "config must be a JSON object, got list", [], "NoneType"),
                    ),
                ]
            )
            """
        ),
        md(
            """
            #### Exercise 3 — a `StopwatchTimer` context-manager class

            `StopwatchTimer(clock=time.perf_counter)`, where `clock` returns seconds as a float:

            - `__enter__` records the start time and returns the stopwatch; entering one that is
              already running raises `RuntimeError`. Entering it again later starts over (laps
              cleared).
            - `__exit__` records the stop time and never suppresses exceptions.
            - `elapsed` (a property): `0.0` before the first start; `clock() - start` while
              running; `stop - start` afterwards (it no longer changes).
            - `running`: `True` only inside the block.
            - `lap()`: seconds since the previous lap (or the start); appends it to the `laps`
              list and returns it; `RuntimeError` if not running.
            """
        ),
        code(
            '''
            class StopwatchTimer:
                """Context-manager stopwatch with laps and an injectable clock."""

                def __init__(self, clock: Callable[[], float] = time.perf_counter) -> None:
                    raise NotImplementedError("Lab 1.14: implement StopwatchTimer")
            '''
        ),
        md(
            """
            Run the checks. `fake_clock(*readings)` returns the given readings one per call, so
            every duration is exact.
            """
        ),
        code(
            '''
            def fake_clock(*readings: float) -> Callable[[], float]:
                """A clock that returns the given readings in order."""
                remaining = list(readings)
                return lambda: remaining.pop(0)


            def stopwatch_laps() -> tuple[list[float], float]:
                """Readings: enter 0, lap 1, lap 3, exit 6."""
                with StopwatchTimer(clock=fake_clock(0.0, 1.0, 3.0, 6.0)) as stopwatch:
                    stopwatch.lap()
                    stopwatch.lap()
                return stopwatch.laps, stopwatch.elapsed


            def stopwatch_while_running() -> tuple[bool, float, bool, float]:
                """Readings: enter 10, elapsed read 14, exit 15."""
                stopwatch = StopwatchTimer(clock=fake_clock(10.0, 14.0, 15.0))
                with stopwatch:
                    during = (stopwatch.running, stopwatch.elapsed)
                return (*during, stopwatch.running, stopwatch.elapsed)


            def stopwatch_on_error() -> tuple[str, float]:
                """The body raises; the time is still recorded and the error propagates."""
                stopwatch = StopwatchTimer(clock=fake_clock(0.0, 2.5))

                def failing_block() -> None:
                    with stopwatch:
                        raise ValueError("body failed")

                return raised_error_name(failing_block), stopwatch.elapsed


            def stopwatch_nested() -> str:
                """Entering a running stopwatch must fail."""
                stopwatch = StopwatchTimer(clock=fake_clock(0.0, 1.0, 2.0, 3.0))
                with stopwatch:
                    return raised_error_name(lambda: stopwatch.__enter__())


            def stopwatch_real_clock() -> bool:
                """The default clock measures real time."""
                with StopwatchTimer() as stopwatch:
                    time.sleep(0.01)
                return stopwatch.elapsed >= 0.01


            run_checks(
                [
                    (
                        "returns self",
                        lambda: (lambda s: s.__enter__() is s)(StopwatchTimer(fake_clock(0.0))),
                        True,
                    ),
                    (
                        "before start",
                        lambda: (lambda s: (s.elapsed, s.running, s.laps))(StopwatchTimer()),
                        (0.0, False, []),
                    ),
                    ("laps and total", stopwatch_laps, ([1.0, 2.0], 6.0)),
                    ("elapsed while running, frozen after", stopwatch_while_running, (True, 4.0, False, 5.0)),
                    ("error propagates, time recorded", stopwatch_on_error, ("ValueError", 2.5)),
                    (
                        "lap when stopped",
                        lambda: raised_error_name(lambda: StopwatchTimer().lap()),
                        "RuntimeError",
                    ),
                    ("nested enter", stopwatch_nested, "RuntimeError"),
                    ("real clock", stopwatch_real_clock, True),
                ]
            )
            '''
        ),
        md(
            """
            #### Exercise 4 — `temporary_env(**variables)` with `@contextmanager`

            Set environment variables (`os.environ`) for the duration of a `with` block. A value
            of `None` means "unset this variable inside the block". On exit, **even after an
            exception**, restore exactly the previous state: variables that existed get their old
            value back, variables that did not exist are removed. Yield nothing. (The last check
            only looks at the structure, so it already passes on the stub.)
            """
        ),
        code(
            '''
            @contextmanager
            def temporary_env(**variables: str | None) -> Iterator[None]:
                """Temporarily set (or unset, with None) environment variables."""
                raise NotImplementedError("Lab 1.14: implement temporary_env()")
                yield
            '''
        ),
        md("Run the checks. They use two variable names that are removed first."),
        code(
            '''
            for variable_name in ("LAB_1_14_MODE", "LAB_1_14_REGION"):
                os.environ.pop(variable_name, None)


            def env_inside_and_after() -> tuple[str | None, str | None]:
                """Value inside the block, then after it."""
                with temporary_env(LAB_1_14_MODE="test"):
                    inside = os.environ.get("LAB_1_14_MODE")
                return inside, os.environ.get("LAB_1_14_MODE")


            def env_restores_existing() -> tuple[str | None, str | None, str | None]:
                """An existing variable: overridden, unset, then restored."""
                os.environ["LAB_1_14_REGION"] = "ap-south-1"
                try:
                    with temporary_env(LAB_1_14_REGION="eu-west-1"):
                        overridden = os.environ.get("LAB_1_14_REGION")
                    with temporary_env(LAB_1_14_REGION=None):
                        unset = os.environ.get("LAB_1_14_REGION")
                    return overridden, unset, os.environ.get("LAB_1_14_REGION")
                finally:
                    os.environ.pop("LAB_1_14_REGION", None)


            def env_after_error() -> tuple[str, str | None]:
                """The block raises; the variable must still be removed."""

                def failing_block() -> None:
                    with temporary_env(LAB_1_14_MODE="broken"):
                        raise RuntimeError("body failed")

                return raised_error_name(failing_block), os.environ.get("LAB_1_14_MODE")


            run_checks(
                [
                    ("set inside, removed after", env_inside_and_after, ("test", None)),
                    ("existing restored", env_restores_existing, ("eu-west-1", None, "ap-south-1")),
                    ("restored after an error", env_after_error, ("RuntimeError", None)),
                    (
                        "built with @contextmanager",
                        lambda: inspect.isgeneratorfunction(getattr(temporary_env, "__wrapped__", None)),
                        True,
                    ),
                ]
            )
            '''
        ),
        md(
            """
            #### Exercise 5 — `open_many(paths)` with `ExitStack`

            A `@contextmanager` that opens every path and yields the list of open file objects, in
            order. Use one `ExitStack`: every file must be closed when the block exits (also after
            an error), and if opening the *k*-th file fails, the files already opened are closed
            before the error propagates. `opener` opens one path; it defaults to
            `open(path, encoding="utf-8")` (the checks pass a recording opener).
            """
        ),
        code(
            '''
            @contextmanager
            def open_many(
                paths: Iterable[Path],
                opener: Callable[[Path], IO[str]] | None = None,
            ) -> Iterator[list[IO[str]]]:
                """Open all paths; close all of them on exit."""
                raise NotImplementedError("Lab 1.14: implement open_many()")
                yield []
            '''
        ),
        md("Run the checks. The cell writes three small files."),
        code(
            '''
            part_paths = []
            for part_number in (1, 2, 3):
                part_path = scratch_dir / f"lab_1_14_part_{part_number}.txt"
                part_path.write_text(f"part {part_number}\\n", encoding="utf-8")
                part_paths.append(part_path)


            def make_recording_opener() -> tuple[Callable[[Path], IO[str]], list[IO[str]]]:
                """An opener that remembers every file it opened."""
                opened: list[IO[str]] = []

                def recording_opener(path: Path) -> IO[str]:
                    stream = open(path, encoding="utf-8")  # closed by open_many
                    opened.append(stream)
                    return stream

                return recording_opener, opened


            def read_all_parts() -> tuple[list[str], bool]:
                """Read every part; afterwards all files must be closed."""
                opener, opened = make_recording_opener()
                with open_many(part_paths, opener) as streams:
                    contents = [stream.read().strip() for stream in streams]
                return contents, all(stream.closed for stream in opened)


            def partial_failure() -> tuple[str, int, bool]:
                """The third path is missing: the two opened files must be closed."""
                opener, opened = make_recording_opener()
                paths = [*part_paths[:2], scratch_dir / "lab_1_14_missing_part.txt"]

                def open_them() -> None:
                    with open_many(paths, opener):
                        pass

                return raised_error_name(open_them), len(opened), all(s.closed for s in opened)


            def closed_after_body_error() -> tuple[str, bool]:
                """The body raises: files are closed and the error propagates."""
                opener, opened = make_recording_opener()

                def failing_block() -> None:
                    with open_many(part_paths, opener):
                        raise KeyError("body failed")

                return raised_error_name(failing_block), all(s.closed for s in opened)


            def no_paths() -> list[IO[str]]:
                """An empty iterable yields an empty list."""
                with open_many([]) as streams:
                    return streams


            def default_opener() -> list[str]:
                """Without an opener, files are opened as UTF-8 text."""
                with open_many(part_paths[:1]) as streams:
                    return [stream.read().strip() for stream in streams]


            run_checks(
                [
                    ("reads and closes", read_all_parts, (["part 1", "part 2", "part 3"], True)),
                    ("failed open closes the others", partial_failure, ("FileNotFoundError", 2, True)),
                    ("closed after a body error", closed_after_body_error, ("KeyError", True)),
                    ("default opener", default_opener, ["part 1"]),
                    ("no paths", no_paths, []),
                ]
            )
            '''
        ),
        md(
            """
            #### Exercise 6 — `validate_records` raising an `ExceptionGroup`, handled with `except*`

            **`validate_records(records)`** checks every field of every record and collects
            **all** problems instead of stopping at the first:

            | Field | Rule | Error |
            | --- | --- | --- |
            | missing field | `name`, `age` and `email` are required | `KeyError(field_name)` |
            | `name` | a `str` that is not blank | `ValueError("name must be a non-empty string")` |
            | `age` | an `int` (not a `bool`) between 0 and 150 | `ValueError("age must be an integer between 0 and 150")` |
            | `email` | a `str` containing `@` | `ValueError("email must contain '@'")` |

            Check the fields in the order name, age, email. Add the note `f"record {index}"`
            (0-based) to each error. If there are errors, raise
            `ExceptionGroup("invalid records", errors)`; otherwise return the same `records` list.

            **`summarize_validation(records)`** calls it and handles the group with **`except*`**:
            `except* KeyError` builds `"missing"` entries `f"{note}: {field_name}"`, and
            `except* ValueError` builds `"invalid"` entries `f"{note}: {message}"`. Return
            `{"missing": [...], "invalid": [...]}` (empty lists when everything is valid).
            """
        ),
        code(
            '''
            def validate_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
                """Return records unchanged, or raise an ExceptionGroup of every problem."""
                raise NotImplementedError("Lab 1.14: implement validate_records()")


            def summarize_validation(records: list[dict[str, Any]]) -> dict[str, list[str]]:
                """Handle the ExceptionGroup with except* and summarize it."""
                raise NotImplementedError("Lab 1.14: implement summarize_validation()")
            '''
        ),
        md("Run the checks."),
        code(
            '''
            sample_signups = [
                {"name": "Asha", "age": 31, "email": "asha@example.com"},
                {"name": "  ", "age": 200, "email": "ravi@example.com"},
                {"name": "Meena", "email": "meena.example.com"},
                {"name": "John", "age": True, "email": "john@example.com"},
            ]
            valid_signups = sample_signups[:1]


            def group_shape(thunk: Callable[[], object]) -> tuple[str, str, int, list[str], int]:
                """(type, message, leaf count, first leaf's notes, KeyError count)."""
                error = caught_error(thunk)
                if not isinstance(error, ExceptionGroup):
                    return (type(error).__name__, str(error), 0, [], 0)
                missing_group = error.subgroup(KeyError)
                return (
                    type(error).__name__,
                    error.message,
                    len(error.exceptions),
                    error.exceptions[0].__notes__,
                    len(missing_group.exceptions) if missing_group else 0,
                )


            run_checks(
                [
                    (
                        "valid returns the same list",
                        lambda: validate_records(valid_signups) is valid_signups,
                        True,
                    ),
                    (
                        "group of every problem",
                        lambda: group_shape(lambda: validate_records(sample_signups)),
                        ("ExceptionGroup", "invalid records", 5, ["record 1"], 1),
                    ),
                    (
                        "summary",
                        lambda: summarize_validation(sample_signups),
                        {
                            "missing": ["record 2: age"],
                            "invalid": [
                                "record 1: name must be a non-empty string",
                                "record 1: age must be an integer between 0 and 150",
                                "record 2: email must contain '@'",
                                "record 3: age must be an integer between 0 and 150",
                            ],
                        },
                    ),
                    (
                        "summary of valid records",
                        lambda: summarize_validation(valid_signups),
                        {"missing": [], "invalid": []},
                    ),
                    ("empty input", lambda: validate_records([]), []),
                ]
            )
            '''
        ),
    ]


def _recap_cells() -> list[NotebookNode]:
    """Recap for Unit 1.14."""
    return [
        md(
            """
            ### Recap — Unit 1.14

            | Concept | One-line takeaway | JS equivalent |
            | --- | --- | --- |
            | Hierarchy | Catch `Exception` subclasses; `SystemExit` / `KeyboardInterrupt` are not errors | `Error` subclasses |
            | Matching | `except C` matches when `C` is in the error's `__mro__`; first matching clause wins | `instanceof` checks in `catch` |
            | `else` / `finally` | `else` only without an exception; `finally` on every exit | `finally` |
            | 3.14 changes | `except A, B:` without parentheses; `return` in `finally` warns | — |
            | `as error` | deleted after the clause (breaks the traceback cycle) | block-scoped `catch (e)` |
            | Chaining | `from` sets `__cause__`, raising in `except` sets `__context__`, `from None` hides it | `new Error(msg, { cause })` |
            | Exception objects | `args`, `__traceback__`, `add_note`, `traceback.format_exception` | `err.stack` |
            | Custom hierarchy | One `AppError` base, subclasses carry status codes and fields | `class AppError extends Error` |
            | Exception groups | `ExceptionGroup` + `except*`, `split`, `subgroup` | `AggregateError` |
            | EAFP vs LBYL | `try` is free since 3.11, raising is not; LBYL for common misses and side effects | — |
            | Logging | `logger.exception` inside `except`; never swallow errors | `console.error(err)` |
            | `with` | `__enter__` / `__exit__`, truthy return suppresses, exits LIFO | `try/finally`, `using` (TC39) |
            | `contextlib` | `@contextmanager` + `finally`, `suppress`, `closing`, `ExitStack`, … | — |
            | `assert` / `warnings` | asserts vanish under `-O`; warnings are filterable, can be made errors | `console.assert`, `console.warn` |
            | Bytecode | Exception table instead of setup opcodes; `LOAD_SPECIAL` + `WITH_EXCEPT_START` for `with` | — |

            **Further reading**

            - [Tutorial: errors and exceptions](https://docs.python.org/3/tutorial/errors.html),
              [built-in exceptions](https://docs.python.org/3/library/exceptions.html),
              [the `try` statement](https://docs.python.org/3/reference/compound_stmts.html#the-try-statement)
            - [`traceback`](https://docs.python.org/3/library/traceback.html),
              [`logging`](https://docs.python.org/3/library/logging.html),
              [Logging HOWTO](https://docs.python.org/3/howto/logging.html)
            - [The `with` statement](https://docs.python.org/3/reference/compound_stmts.html#the-with-statement),
              [context manager types](https://docs.python.org/3/library/stdtypes.html#typecontextmanager),
              [`contextlib`](https://docs.python.org/3/library/contextlib.html)
            - [`warnings`](https://docs.python.org/3/library/warnings.html),
              [the `assert` statement](https://docs.python.org/3/reference/simple_stmts.html#the-assert-statement),
              [`dis`](https://docs.python.org/3/library/dis.html)
            - [PEP 343 — The `with` statement](https://peps.python.org/pep-0343/),
              [PEP 3134 — Exception chaining](https://peps.python.org/pep-3134/),
              [PEP 654 — Exception groups and `except*`](https://peps.python.org/pep-0654/),
              [PEP 678 — Notes](https://peps.python.org/pep-0678/)
            - [PEP 758 — `except` without parentheses](https://peps.python.org/pep-0758/),
              [PEP 765 — Disallow `return`/`break`/`continue` that exit `finally`](https://peps.python.org/pep-0765/)
            """
        ),
    ]


def cells() -> list[NotebookNode]:
    """Return the cells for Unit 1.14 and Lab 1.14."""
    return [
        *_overview_cells(),
        *_hierarchy_cells(),
        *_try_statement_cells(),
        *_raising_cells(),
        *_exception_object_cells(),
        *_custom_hierarchy_cells(),
        *_exception_group_cells(),
        *_eafp_cells(),
        *_logging_cells(),
        *_with_statement_cells(),
        *_contextlib_cells(),
        *_assert_warnings_cells(),
        *_under_the_hood_cells(),
        *_lab_cells(),
        *_recap_cells(),
    ]
