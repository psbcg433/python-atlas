# Unit 1.14 — Exceptions and Context Managers

[← Previous](unit-1-13-iterators-generators-and-itertools.md) · [Index](README.md) · [Next →](project-log-analyzer.md)

Errors in Python are ordinary objects arranged in a class hierarchy, and the
`except` clause picks them out by class. This unit walks through that hierarchy,
every path through `try` / `except` / `else` / `finally`, chaining, notes and
exception groups, and then the other half of resource safety: the `with`
statement, context managers and the `contextlib` toolbox, finishing with how
CPython compiles both into bytecode.

## What you will learn

- Read the exception hierarchy and predict which `except` clause catches what.
- Trace every path through `try` / `except` / `else` / `finally`, including the
  3.14 syntax and warning changes.
- Raise, re-raise and chain exceptions so tracebacks tell the whole story.
- Design a custom exception hierarchy that maps to HTTP status codes.
- Raise and handle several errors at once with exception groups and `except*`.
- Choose between EAFP and LBYL with measurements, and log exceptions correctly.
- Write context managers as classes and with `contextlib`, and see both in
  bytecode.

> **Note:** all examples ran on Python 3.15. Output lines longer than 80
> characters are wrapped onto the next line and indented by two spaces so they
> fit a phone screen; nothing is elided unless an `…` is shown.

## JavaScript → Python bridge

| JavaScript | Python | The difference that bites |
| --- | --- | --- |
| `throw value` | `raise SomeError(...)` | Only `BaseException` objects can be raised |
| `catch (e)` | `except SomeError as error:` | Python filters by class |
| — | `else:` | Runs only if `try` raised nothing |
| `finally` | `finally` | `return` in it now warns (3.14) |
| `new Error(m, { cause })` | `raise New(m) from old` | Python also records implicit context |
| `AggregateError` | `ExceptionGroup` | `except*` handles each subgroup |
| `using` / `try…finally` | `with resource:` | `__exit__` sees and may suppress the error |
| `console.error(err)` | `logger.exception(msg)` | Logs message and traceback at ERROR |

A bare `except:` in Python is the closest thing to a JavaScript `catch (e)`,
and it is a trap: it also catches Ctrl+C and `sys.exit()` (1.14.2).

The examples use a few small helpers defined in the unit's setup cell.
`raised_error_name(thunk)` calls a function and returns the name of the
exception it raised, and `compile_error(source)` compiles source code without
running it, to show `SyntaxError` messages.

```python
def raised_error_name(thunk: Callable[[], object]) -> str:
    """Call thunk and return the name of the exception it raised."""
    try:
        thunk()
    except Exception as error:
        return type(error).__name__
    return "no error"


def compile_error(source: str) -> str:
    """Compile source; return "SyntaxError: <message>" or "compiles"."""
    try:
        compile(source, "<demo>", "exec")
    except SyntaxError as error:
        return f"SyntaxError: {error.msg}"
    return "compiles"
```

The setup also defines `scratch_dir`, a git-ignored folder that the file demos
write into.

## 1.14.1 The exception hierarchy

Every exception in Python is an instance of a class that derives from
**`BaseException`**. That is a hard rule enforced by the interpreter: where
JavaScript lets you `throw "a string"` or `throw 42`, Python only accepts
objects whose class has `BaseException` somewhere in its ancestry. In CPython
each exception is a C struct (`PyBaseExceptionObject`) with slots for the
constructor arguments, the traceback, the notes and the two chaining links you
will meet in 1.14.3, so every exception carries the same machinery no matter
which class it is.

Directly under `BaseException` sit a few classes that are *not errors* at all
but control signals, plus **`Exception`**, the base of everything you normally
handle:

| Class | Raised by | Caught by `except Exception`? |
| --- | --- | --- |
| `SystemExit` | `sys.exit()` | No: the program asked to stop |
| `KeyboardInterrupt` | Ctrl+C | No: the user asked to stop |
| `GeneratorExit` | `generator.close()` | No: a generator is shutting down |
| `BaseExceptionGroup` | several errors at once | Only its `ExceptionGroup` subclass |
| `Exception` | every ordinary error | Yes |

So `except Exception:` is the widest net that still lets the program be
stopped. Custom exceptions should derive from `Exception` (or one of its
subclasses), never directly from `BaseException`. `GeneratorExit` was covered
with `generator.close()` in Unit 1.13; exception groups get their own section
in 1.14.6.

The key built-in exceptions form this tree (a selection; the real tree is
printed further down):

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

The practical consequence: `except Exception` lets `sys.exit()` and Ctrl+C
through. The function below raises an error inside a `try` that has an
`except Exception` clause first and an `except BaseException` clause second,
and reports which one caught it.

```python
def catches_with_exception_clause(error: BaseException) -> bool:
    """Raise error inside try / except Exception; report if it caught it."""
    try:
        raise error
    except Exception:
        return True
    except BaseException:
        return False


for raised in (
    ValueError("bad"),
    KeyError("sku"),
    SystemExit(1),
    KeyboardInterrupt(),
):
    print(
        f"{type(raised).__name__:<18} caught by except Exception: "
        f"{catches_with_exception_clause(raised)}"
    )
```

```text
ValueError         caught by except Exception: True
KeyError           caught by except Exception: True
SystemExit         caught by except Exception: False
KeyboardInterrupt  caught by except Exception: False
```

### Under the hood: `__mro__` and what `except` matches

`except SomeClass:` matches when `isinstance(error, SomeClass)` would be true,
that is, when `SomeClass` appears anywhere in the error's **method resolution
order** (`type(error).__mro__`, Unit 1.11). In CPython the `CHECK_EXC_MATCH`
bytecode instruction (you will see it in 1.14.12) calls
`PyErr_GivenExceptionMatches`, which walks exactly that tuple. So
`except OSError:` catches `FileNotFoundError`, and `except LookupError:`
catches both `KeyError` and `IndexError`. Catching a parent class is how you
handle a whole family of errors with one clause.

```python
print(" -> ".join(cls.__name__ for cls in FileNotFoundError.__mro__))
print(" -> ".join(cls.__name__ for cls in KeyError.__mro__))
print(" -> ".join(cls.__name__ for cls in ExceptionGroup.__mro__))

try:
    Path("no-such-file.txt").read_text(encoding="utf-8")
except OSError as error:
    print(f"except OSError caught {type(error).__name__}: errno={error.errno}")
```

```text
FileNotFoundError -> OSError -> Exception -> BaseException -> object
KeyError -> LookupError -> Exception -> BaseException -> object
ExceptionGroup -> BaseExceptionGroup -> Exception -> BaseException -> object
except OSError caught FileNotFoundError: errno=2
```

Note that `ExceptionGroup` has two parents: it is a `BaseExceptionGroup` *and*
an `Exception`, which is why `except Exception` can catch it.

The tree above is a selection. The next example builds the real tree of
built-in exceptions from the `builtins` module, two levels deep, using each
class's `__subclasses__()` method. The exact list grows slowly between
versions.

```python
BUILTIN_EXCEPTIONS = {
    value
    for value in vars(builtins).values()
    if isinstance(value, type) and issubclass(value, BaseException)
}


def exception_tree(
    root: type[BaseException], depth: int, max_depth: int
) -> Iterator[str]:
    """Yield indented names of the built-in subclasses of root."""
    yield "    " * depth + root.__name__
    if depth == max_depth:
        return
    children = [
        cls for cls in root.__subclasses__() if cls in BUILTIN_EXCEPTIONS
    ]
    for child in sorted(children, key=lambda cls: cls.__name__):
        yield from exception_tree(child, depth + 1, max_depth)


print(f"{len(BUILTIN_EXCEPTIONS)} built-in exception classes")
top_level = list(exception_tree(BaseException, 0, 1))
print("Under BaseException:", ", ".join(n.strip() for n in top_level[1:]))
print("\n".join(line for line in exception_tree(Exception, 0, 1)))
```

```text
70 built-in exception classes
Under BaseException: BaseExceptionGroup, Exception, GeneratorExit,
  KeyboardInterrupt, SystemExit
Exception
    ArithmeticError
    AssertionError
    AttributeError
    BufferError
    EOFError
    ExceptionGroup
    ImportError
    LookupError
    MemoryError
    NameError
    OSError
    ReferenceError
    RuntimeError
    StopAsyncIteration
    StopIteration
    SyntaxError
    SystemError
    TypeError
    ValueError
    Warning
```

(The count of 70 includes the warning categories, which are exception classes
too: 1.14.11.)

### Key points

| Point | Detail |
| --- | --- |
| Root class | Everything raisable derives from `BaseException` |
| Handle errors | Catch `Exception` or narrower |
| Not errors | `SystemExit`, `KeyboardInterrupt`, `GeneratorExit` |
| Matching | `except C` matches if `C` is in `type(error).__mro__` |
| Families | `OSError`, `LookupError`, `ArithmeticError` group related errors |

## 1.14.2 `try` / `except` / `else` / `finally`

The full statement has four parts. The `try` body is the code being guarded.
Each `except` clause names the classes it handles. The **`else`** clause runs
only if the `try` body finished without raising, and **`finally`** runs
**always**, on every way out of the statement: normal completion, a handled
error, an unhandled error, a `return`, a `break` or a `continue`. JavaScript
has `try` / `catch` / `finally` but no `else`.

| Path | Runs, in order | Afterwards |
| --- | --- | --- |
| No exception | try → else → finally | continues |
| Error matched | try → except → finally | continues |
| Error not matched | try → finally | error propagates |
| Error in `except` | try → except → finally | new error propagates |
| Error in `else` | try → else → finally | propagates, not caught here |
| `return` in `try` | try → finally | function returns |
| `break` / `continue` | try → finally | the loop jump happens |

Two rows deserve a comment. When the handler itself raises, the **new**
exception is the one that propagates, and it carries the old one in its
`__context__` attribute (1.14.3). When the `else` block raises, this
statement's own `except` clauses do **not** see the error. That is the whole
point of `else`: code placed there is not protected by the `except` clauses,
so you do not accidentally catch errors from lines you never meant to guard.
Keep the `try` body to the one operation that can fail in the expected way,
and move the follow-up work into `else`.

The function below walks the first five paths and records which blocks run.

```python
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
            raise RuntimeError("handler failed")
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
```

```text
no error           try -> else -> finally -> after
error handled      try -> except -> finally -> after
error not matched  try -> finally -> propagated KeyError
error in except    try -> except -> finally -> propagated RuntimeError
error in else      try -> else -> finally -> propagated TypeError
```

The last two rows of the table: `finally` runs even when the `try` body leaves
through `return` or `break`. For a `return`, the return value is computed
first, then `finally` runs, then the function actually returns.

```python
def price_with_audit(audit_log: list[str]) -> int:
    """Return from inside try; finally still runs first."""
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
```

```text
price_with_audit(audit_log)=499, audit_log=['computing price',
  'finally after return']
loop_log=['finally for attempt 0', 'finally for attempt 1']
```

### Multiple clauses

Clauses are tested top to bottom and the **first match wins**; the rest are
skipped. Put the most specific classes first. A broad clause placed early
silently shadows the specific ones below it, and Python does not warn you.
In JavaScript you would write an `if (e instanceof KeyError) … else if …`
chain inside one `catch`; Python's clauses are that chain, built into the
syntax.

```python
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
    """The broad clause comes first, so the KeyError clause never runs."""
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
```

```text
classify_failure(lambda: stock['coffee'])='KeyError clause'
classify_failure(lambda: [][0])='LookupError clause'
classify_failure(lambda: int('four'))='Exception clause (ValueError)'
classify_failure_wrong_order(lambda: stock['coffee'])='LookupError clause'
```

### Tuples of classes

One clause can handle several classes with a parenthesized tuple. With
`as error` you can still branch on the actual type inside the block.

```python
def first_item_name(order: dict[str, list[str]]) -> str:
    """Handle a missing key and an empty list in one clause."""
    try:
        return order["items"][0]
    except (KeyError, IndexError) as error:
        return f"no items ({type(error).__name__})"


print(first_item_name({"items": ["rice"]}))
print(first_item_name({}))
print(first_item_name({"items": []}))
```

```text
rice
no items (KeyError)
no items (IndexError)
```

### Unparenthesized `except A, B:` (3.14)

*New in 3.14* (PEP 758). The parentheses may now be dropped, **but only
without `as`**. The history explains the restriction: in Python 2,
`except A, B:` meant "catch `A` and bind it to the name `B`", so the form was
a syntax error for all of Python 3 until 3.14, to avoid silently changing the
meaning of old code.

```python
except KeyError, IndexError:          # 3.14+: fine
except (KeyError, IndexError) as e:   # needs parentheses with `as`
```

The example runs the new form through `exec` inside a version guard, so older
interpreters can still parse the file, and shows the error when `as` is
added.

```python
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

print(
    compile_error(
        "try:\n    pass\nexcept KeyError, IndexError as error:\n    pass"
    )
)
```

```text
3.14 syntax: caught without parentheses
SyntaxError: multiple exception types must be parenthesized when using 'as'
```

### `as error` is deleted at the end of the clause

In JavaScript, `catch (e)` scopes `e` to the catch block. Python has no block
scope (Unit 1.9), so it does something blunter: when an `except … as error`
block ends, the compiler inserts `del error`. The reason is memory. The
exception holds its traceback, the traceback holds the frame, and the frame
holds the local variable `error`: a reference cycle that would keep every
local variable of the function alive until the cycle collector runs. To keep
the exception, bind it to another name inside the block.

```python
try:
    int("twelve")
except ValueError as conversion_error:
    kept_error = conversion_error
    print(f"inside:  {'conversion_error' in globals()=}")
print(f"after:   {'conversion_error' in globals()=}")
print(f"kept:    {kept_error!r}")
```

```text
inside:  'conversion_error' in globals()=True
after:   'conversion_error' in globals()=False
kept:    ValueError("invalid literal for int() with base 10: 'twelve'")
```

> **Warning:** if a variable called `error` existed *before* the `try`, it is
> gone after an `except … as error` block runs. Use a distinct name.

### Bare `except:` dangers

`except:` with no class is the same as `except BaseException:`. It catches
`SystemExit` and `KeyboardInterrupt`, so the program cannot be stopped, and it
hides typos (`NameError`, `AttributeError`) as if they were expected failures.
If you truly must catch everything (a top-level crash reporter), catch
`BaseException` explicitly and **re-raise**.

```python
def shutdown_service() -> str:
    """Ask the interpreter to exit, but a bare except swallows it."""
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
```

```text
sys.exit() was swallowed; the program keeps running
crash reporter saw SystemExit
SystemExit still propagated, code=3
```

### `return` in `finally` (3.14 warning)

*Changed in 3.14* (PEP 765). A `return`, `break` or `continue` inside
`finally` silently discards any exception in flight and any earlier return
value. JavaScript behaves the same way and linters flag it there too
(`no-unsafe-finally`). Since 3.14 the Python compiler itself emits a
`SyntaxWarning`. The example compiles such a function from a string, so the
warning can be captured and printed, then calls it: the `ZeroDivisionError`
vanishes.

```python
SWALLOWING_SOURCE = """
def average_price(total: int, count: int) -> float | str:
    try:
        return total / count
    finally:
        return "finally won"
"""

with warnings.catch_warnings(record=True) as compile_warnings:
    warnings.simplefilter("always")
    swallowing_code = compile(
        inspect.cleandoc(SWALLOWING_SOURCE), "<demo>", "exec"
    )
for caught_warning in compile_warnings:
    print(f"{caught_warning.category.__name__}: {caught_warning.message}")

demo_namespace: dict[str, Any] = {}
exec(swallowing_code, demo_namespace)
print(
    f"{demo_namespace['average_price'](100, 0)=}  (ZeroDivisionError lost)"
)
```

```text
SyntaxWarning: 'return' in a 'finally' block
demo_namespace['average_price'](100, 0)='finally won'  (ZeroDivisionError
  lost)
```

### Predict the output

```python
def apply_coupons() -> list[str]:
    applied = ["SAVE10"]
    try:
        return applied
    finally:
        applied.append("FREESHIP")


print(apply_coupons())
```

<details><summary>Answer</summary>

```text
['SAVE10', 'FREESHIP']
```

The `return` evaluates `applied` (a reference to the list) before `finally`
runs; `finally` then mutates that same list. Returning an `int` the same way
would be unaffected, because rebinding is not mutation (Unit 1.2).

</details>

### Key points

| Point | Detail |
| --- | --- |
| `else` | Runs only when `try` raised nothing; not guarded |
| `finally` | Runs on every exit, after the return value is computed |
| Clause order | First match wins; specific before broad |
| `except A, B:` | 3.14+, only without `as` |
| `as error` | Deleted after the block to break a reference cycle |
| Bare `except:` | Catches `SystemExit` too; avoid |
| `return` in `finally` | Discards errors; `SyntaxWarning` since 3.14 |

## 1.14.3 Raising and chaining

`raise` throws an exception. Its operand is either an instance or a class; a
class is instantiated with no arguments. Inside an `except` block, `raise`
alone re-raises the exception being handled, and `raise … from …` connects a
new exception to the one that caused it.

| Form | Meaning |
| --- | --- |
| `raise ValueError("msg")` | Raise a new instance |
| `raise ValueError` | The class is instantiated with no arguments |
| `raise` (inside `except`) | Re-raise the current exception, traceback intact |
| `raise New(...) from original` | Explicit chaining: sets `__cause__` |
| `raise New(...)` inside `except` | Implicit chaining: sets `__context__` |
| `raise New(...) from None` | Hide the context from the traceback |

Only instances or subclasses of `BaseException` can be raised; anything else
is itself a `TypeError`.

```python
def raise_value(value: object) -> None:
    """Raise whatever is passed in."""
    raise value  # type: ignore[misc]


for candidate in (ValueError("negative quantity"), ValueError, "just a string"):
    try:
        raise_value(candidate)
    except Exception as error:
        print(f"{candidate!r:<36} -> {type(error).__name__}: {error}")
```

```text
ValueError('negative quantity')      -> ValueError: negative quantity
<class 'ValueError'>                 -> ValueError:
'just a string'                      -> TypeError: exceptions must derive
  from BaseException
```

### Bare re-raise

Inside an `except` block, a plain `raise` re-raises the current exception with
its original traceback. That is how you add a side effect (logging, a metric,
a rollback) without changing what the caller sees. Outside an `except` block
there is nothing to re-raise, and you get a `RuntimeError`. Under the hood
CPython keeps the "exception currently being handled" on the thread state;
`sys.exception()` (3.11+) returns it, and bare `raise` re-raises it.

```python
failed_charges: list[str] = []


def charge_card(card_number: str) -> None:
    """Record the failure, then let the original error continue."""
    try:
        int(card_number)
    except ValueError:
        failed_charges.append(card_number)
        raise


print(f"{raised_error_name(lambda: charge_card('4111-x'))=}")
print(f"{failed_charges=}")


def reraise_with_nothing_active() -> None:
    """A bare raise with no exception being handled."""
    raise


try:
    reraise_with_nothing_active()
except RuntimeError as error:
    print(f"RuntimeError: {error}")
```

```text
raised_error_name(lambda: charge_card('4111-x'))='ValueError'
failed_charges=['4111-x']
RuntimeError: No active exception to reraise
```

> **Note:** the notebook prints the first two lines as one line; they are
> split here to fit the screen.

### Explicit chaining with `from`

When you translate a low-level error into a domain error, chain it:
`raise LookupError(...) from error` stores the original in `__cause__`, and the
printed traceback shows both, joined by *"The above exception was the direct
cause of the following exception"*. This is the same idea as JavaScript's
`new Error(message, { cause })` (ES2022), except that Python's traceback
printer understands the link and prints the whole chain for you.

The helper `chain_lines(error)` keeps only the unindented lines of the
formatted traceback (the exception lines and the joining sentences); the
indented `File …` lines contain machine-specific paths.

```python
def chain_lines(error: BaseException) -> list[str]:
    """Return the unindented lines of the full traceback (no file paths)."""
    formatted = "".join(traceback.format_exception(error))
    return [
        line
        for line in formatted.splitlines()
        if line and not line[0].isspace()
    ]


CATALOG = {"TEA-500G": 249}


def unit_price(sku: str) -> int:
    """Translate KeyError into a domain-level LookupError."""
    try:
        return CATALOG[sku]
    except KeyError as error:
        raise LookupError(f"unknown SKU {sku!r}") from error


try:
    unit_price("SOAP-3PK")
except LookupError as error:
    print(f"{error.__cause__=}")
    print("\n".join(chain_lines(error)))
```

```text
error.__cause__=KeyError('SOAP-3PK')
Traceback (most recent call last):
KeyError: 'SOAP-3PK'
The above exception was the direct cause of the following exception:
Traceback (most recent call last):
LookupError: unknown SKU 'SOAP-3PK'
```

### Implicit chaining with `__context__`

JavaScript has no equivalent of this one. Raising inside an `except` block
without `from` still records the exception being handled, in `__context__`,
and the traceback says *"During handling of the above exception, another
exception occurred"*. CPython sets `__context__` automatically at the moment
the new exception is raised, from the thread's "currently handled" slot. The
message usually signals a bug in the handler itself, here a `TypeError`.

```python
def parse_discount(text: str) -> int:
    """The handler itself fails, so the second error carries the first."""
    try:
        return int(text)
    except ValueError:
        return len(None)  # type: ignore[arg-type]  (bug in the handler)


try:
    parse_discount("ten")
except TypeError as error:
    print(f"{error.__cause__=}, {error.__context__=}")
    print("\n".join(chain_lines(error)))
```

```text
error.__cause__=None, error.__context__=ValueError("invalid literal for
  int() with base 10: 'ten'")
Traceback (most recent call last):
ValueError: invalid literal for int() with base 10: 'ten'
During handling of the above exception, another exception occurred:
Traceback (most recent call last):
TypeError: object of type 'NoneType' has no len()
```

### Hiding the context with `from None`

`from None` hides the context when it is noise to the caller, an
implementation detail they should not have to read. Note that `__context__` is
still stored; `__suppress_context__ = True` only tells the traceback printer
not to show it.

```python
def environment_name(settings: dict[str, str]) -> str:
    """Raise a clean error; the internal KeyError is hidden."""
    try:
        return settings["APP_ENV"]
    except KeyError:
        raise RuntimeError("APP_ENV is not configured") from None


try:
    environment_name({})
except RuntimeError as error:
    print(f"{error.__cause__=}, {error.__context__=}")
    print(f"{error.__suppress_context__=}")
    print("\n".join(chain_lines(error)))
```

```text
error.__cause__=None, error.__context__=KeyError('APP_ENV')
error.__suppress_context__=True
Traceback (most recent call last):
RuntimeError: APP_ENV is not configured
```

> **Note:** the notebook prints the first two lines on one line; they are
> split into two `print` calls here to fit the screen.

### Predict the output

```python
try:
    try:
        raise ValueError("payment declined")
    finally:
        raise RuntimeError("cleanup failed")
except Exception as error:
    print(type(error).__name__, "|", type(error.__context__).__name__)
```

<details><summary>Answer</summary>

```text
RuntimeError | ValueError
```

An exception raised in `finally` replaces the one in flight; the original
survives only as `__context__`. That is why cleanup code should not raise.

</details>

### Key points

| Point | Detail |
| --- | --- |
| `raise` alone | Re-raises the handled error, traceback intact |
| `from error` | Sets `__cause__`: "direct cause" |
| Raise in `except` | Sets `__context__`: "during handling" |
| `from None` | Sets `__suppress_context__`; context still stored |
| `raise "text"` | `TypeError`: must derive from `BaseException` |

## 1.14.4 Exception objects

An exception is an ordinary object: you can create one without raising it,
store it in a list, pass it to a function and inspect its attributes. That is
quite different from JavaScript, where the useful information lives mostly in
the `message` string and the `stack` string. Python keeps structured data: the
constructor arguments, a linked list of traceback objects that point at real
frames, the chaining links and a list of notes.

### Reference: attributes and helpers

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `args` | Constructor arguments | `ValueError("bad", 3).args` | `('bad', 3)` |
| `str(error)` | `args[0]` if one arg | `str(ValueError("bad"))` | `'bad'` |
| `__traceback__` | First traceback entry | `type(e.__traceback__).__name__` | `'traceback'` |
| `tb_next` | Next entry inward | `e.__traceback__.tb_next` | entry or `None` |

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `__cause__` | Set by `from` | `error.__cause__` | `KeyError('SOAP-3PK')` |
| `__context__` | Set automatically | `error.__context__` | `KeyError('APP_ENV')` |
| `__suppress_context__` | Set by `from None` | `error.__suppress_context__` | `True` |

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `add_note(text)` | Append a note (3.11+) | `e.add_note("row 3")` | `None` |
| `__notes__` | List of notes | `e.__notes__` | `['row 3']` |
| `format_exception` | Full traceback text | `traceback.format_exception(e)` | list of `str` |
| `format_exception_only` | Last lines only | `format_exception_only(KeyError("sku"))` | `["KeyError: 'sku'\n"]` |

The chaining attributes were covered in 1.14.3. The others get a closer look
below.

### `args` and built-in extras

`args` is the tuple of constructor arguments. `str(error)` is `args[0]` when
there is exactly one argument, otherwise `str(args)`. Some built-ins add
attributes on top: `OSError` splits its arguments into `errno`, `strerror` and
`filename`. `KeyError` uses the `repr` of the key as its message, which is why
it prints with quotes.

```python
single = ValueError("quantity must be positive")
several = ValueError("quantity must be positive", -3)
print(f"{single.args=}, {str(single)=}")
print(f"{several.args=}, {str(several)=}")
print(f"{str(KeyError('sku'))=}  (repr of the key)")

try:
    open(scratch_dir / "no-such-report.txt", encoding="utf-8")
except OSError as error:
    print(f"{error.errno=}, {error.strerror=}")
    print(f"{error.filename.endswith('report.txt')=}")
```

```text
single.args=('quantity must be positive',), str(single)='quantity must be
  positive'
several.args=('quantity must be positive', -3), str(several)="('quantity
  must be positive', -3)"
str(KeyError('sku'))="'sku'"  (repr of the key)
error.errno=2, error.strerror='No such file or directory'
error.filename.endswith('report.txt')=True
```

### `__traceback__`

`__traceback__` is a chain of `traceback` objects linked by `tb_next`. Each one
points at a frame (`tb_frame`) and a line number (`tb_lineno`), which is
exactly what the printed traceback lists. CPython adds one entry each time the
exception unwinds out of a frame, so walking the chain shows the call path
from where the exception was caught down to where it was raised. Because the
entries hold real frames, an exception kept alive also keeps those frames and
all their local variables alive: the reason for the `del error` in 1.14.2.

```python
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
```

```text
<module> -> load_cart -> parse_cart_row
```

### `add_note`

*New in 3.11* (PEP 678). `add_note(text)` attaches context without changing
the exception type or message: which row of a file, which request, which
retry attempt. Notes are stored in the `__notes__` list and printed under the
message. Before notes existed, the usual trick was to catch and raise a new
exception just to add a sentence, which changed the type the caller saw.

```python
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
    print("\n".join(chain_lines(error)))
```

```text
error.__notes__=["while importing row 3: '1,299'", 'hint: prices are whole
  rupees']
Traceback (most recent call last):
ValueError: invalid literal for int() with base 10: '1,299'
while importing row 3: '1,299'
hint: prices are whole rupees
```

### `traceback.format_exception`

`traceback.format_exception(error)` (the single-argument form exists since
3.10) returns the same text the interpreter would print, as a list of strings
that each end in a newline. Use it to put tracebacks in log records or error
reports. `traceback.format_exception_only` gives only the final line(s): the
message plus notes. The frame lines contain file paths, so the example prints
only the first line, the line count and the last lines.

```python
try:
    import_price_rows(["10", "ten"])
except ValueError as error:
    full_lines = "".join(traceback.format_exception(error)).splitlines()
    print(f"first line: {full_lines[0]}")
    print(f"{len(full_lines)} lines in total; last three:")
    print("\n".join(full_lines[-3:]))
    print(f"{traceback.format_exception_only(error)=}")
```

```text
first line: Traceback (most recent call last):
10 lines in total; last three:
ValueError: invalid literal for int() with base 10: 'ten'
while importing row 2: 'ten'
hint: prices are whole rupees
traceback.format_exception_only(error)=["ValueError: invalid literal for
  int() with base 10: 'ten'\n", "while importing row 2: 'ten'\n", 'hint:
  prices are whole rupees\n']
```

### Key points

| Point | Detail |
| --- | --- |
| `args` | Tuple of constructor arguments |
| `__traceback__` | Linked entries: `tb_frame`, `tb_lineno`, `tb_next` |
| Notes | `add_note` adds context, keeps type and message |
| Formatting | `traceback.format_exception(error)` gives the text |
| Memory | Tracebacks keep frames and locals alive |

## 1.14.5 Custom exception hierarchies

An application defines **one base class** for its own errors, then specific
subclasses. Callers can catch everything from your code with `except
AppError`, or one case precisely. Each class carries what a handler needs as
attributes, here an HTTP status code and a stable machine-readable
`error_code`. In JavaScript you would write `class AppError extends Error`;
the Python version is the same idea, plus two things JavaScript cannot do:
`except` filters by class for you, and multiple inheritance lets one error
belong to two families at once.

| Class | Also a | HTTP status | Extra attributes |
| --- | --- | --- | --- |
| `AppError` | `Exception` | 500 | `message`, `details` |
| `ValidationError` | `ValueError` | 422 | `field` |
| `NotFoundError` | `LookupError` | 404 | `resource`, `resource_id` |

Inheriting from a matching built-in as well,
`ValidationError(AppError, ValueError)`, keeps older `except ValueError` code
working. Class-level defaults (`status_code`, `error_code`) mean subclasses
only override what differs, and `super().__init__(message)` makes sure
`args` and `str(error)` behave like any other exception.

```python
class AppError(Exception):
    """Base class for all errors raised by the shop application."""

    status_code = 500
    error_code = "internal_error"

    def __init__(
        self, message: str, *, details: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready error body."""
        return {
            "error": self.error_code,
            "message": self.message,
            **self.details,
        }


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
        super().__init__(
            f"{resource} {resource_id!r} not found",
            details={"resource": resource},
        )
        self.resource = resource
        self.resource_id = resource_id
```

One handler at the edge of the application turns any `AppError` into a status
code and a body; anything else becomes a generic 500, so internal details do
not leak to clients. This is the shape of FastAPI exception handlers in
Phase 6.

```python
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
```

```text
(200, {'name': 'Masala tea', 'price': 249})
(422, {'error': 'validation_error', 'message': 'product_id must be
  positive', 'field': 'product_id'})
(404, {'error': 'not_found', 'message': 'product 999 not found', 'resource':
  'product'})
```

Because of the second base class, the same exceptions are caught by built-in
categories too, and `isinstance` checks follow the MRO:

```python
missing = NotFoundError("order", 42)
print(" -> ".join(cls.__name__ for cls in NotFoundError.__mro__))
print(f"{isinstance(missing, LookupError)=}, {missing.status_code=}")
print(f"{missing.resource_id=}")
print(f"{raised_error_name(lambda: get_product(-1))=}")
try:
    get_product(-1)
except ValueError as error:
    print(f"plain except ValueError still works: {error}")
```

```text
NotFoundError -> AppError -> LookupError -> Exception -> BaseException -> object
isinstance(missing, LookupError)=True, missing.status_code=404
missing.resource_id=42
raised_error_name(lambda: get_product(-1))='ValidationError'
plain except ValueError still works: product_id must be positive
```

> **Note:** the notebook prints the second and third lines as one; the
> `print` is split here to fit the screen.

> **Warning:** derive custom errors from `Exception`, not `BaseException`.
> A `BaseException` subclass slips past every `except Exception` handler,
> including the generic 500 above.

### Key points

| Point | Detail |
| --- | --- |
| One base | `AppError` lets callers catch all app errors |
| Attributes | Carry status codes and fields, not just text |
| Mixins | `(AppError, ValueError)` keeps old handlers working |
| Edge handler | Map `AppError` to responses; hide the rest |
| `super().__init__` | Keeps `args` and `str()` correct |

## 1.14.6 Exception groups

*New in 3.11* (PEP 654). Some operations fail in several independent ways at
once: validating a form, running tasks concurrently (`asyncio.TaskGroup`,
Phase 5), retrying several hosts. Raising only the first failure throws the
others away. An **`ExceptionGroup(message, exceptions)`** bundles them into
one raisable object, and groups can be nested. JavaScript's `AggregateError`
(from `Promise.any`) is the closest relative, but JavaScript has no syntax to
handle its members by type; Python adds `except*`.

| Class | Can contain |
| --- | --- |
| `ExceptionGroup` | Only `Exception` subclasses (it is an `Exception`) |
| `BaseExceptionGroup` | Any `BaseException` |

Constructing a `BaseExceptionGroup` with only `Exception`s actually returns an
`ExceptionGroup`, and putting a `KeyboardInterrupt` into an `ExceptionGroup`
is a `TypeError`.

```python
nightly_failures = ExceptionGroup(
    "nightly jobs failed",
    [
        ConnectionError("payments API unreachable"),
        ValueError("bad row in inventory.csv"),
        ExceptionGroup(
            "email batch", [TimeoutError("smtp 1"), TimeoutError("smtp 2")]
        ),
    ],
)
print(f"{nightly_failures.message=}")
print(f"{len(nightly_failures.exceptions)=}")
print(f"{str(nightly_failures)=}")
print(f"{type(BaseExceptionGroup('m', [ValueError()])).__name__=}")
print(
    raised_error_name(lambda: ExceptionGroup("m", [KeyboardInterrupt()]))
)
```

```text
nightly_failures.message='nightly jobs failed'
len(nightly_failures.exceptions)=3
str(nightly_failures)='nightly jobs failed (3 sub-exceptions)'
type(BaseExceptionGroup('m', [ValueError()])).__name__='ExceptionGroup'
TypeError
```

> **Note:** the notebook's last line is
> `raised_error_name(lambda: ExceptionGroup('m', [KeyboardInterrupt()]))='TypeError'`;
> the self-documenting `=` is dropped here to keep the line short.

### `except*`

`except*` handles groups. Each `except* SomeError` clause receives a
**subgroup** with all matching leaves (nesting preserved) and runs at most
once. Clauses are tried in order, and each one takes its matches out of what
is left; leaves that no clause handles are **re-raised** in a new group. A
plain exception that reaches `except*` is wrapped in a group first. So unlike
`except`, several `except*` clauses can run for one `try`.

`check_services()` fails four ways. The `except*` handlers deal with the
network problems, and the `ValueError` propagates out to the outer `try`.

```python
def check_services() -> None:
    """Collect every health-check failure instead of stopping at one."""
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
        print(
            f"reconnect later: {[str(e) for e in network_group.exceptions]}"
        )
    except* TimeoutError as slow_group:
        print(
            f"{len(slow_group.exceptions)} timeouts: "
            f"{[e.__notes__[0] for e in slow_group.exceptions]}"
        )
except ExceptionGroup as leftover:
    print(f"re-raised: {leftover.message!r} with {leftover.exceptions!r}")
```

```text
reconnect later: ['refused']
2 timeouts: ['service: search', 'service: email']
re-raised: 'health check failed' with (ValueError('missing API key'),)
```

Rules that differ from `except`: a plain exception is wrapped; `except` and
`except*` cannot be mixed on one `try`; `return`, `break` and `continue` are
not allowed in an `except*` block, because the unhandled remainder still has
to be re-raised after all clauses run.

```python
try:
    raise ValueError("single error")
except* ValueError as wrapped_group:
    print(f"{wrapped_group!r}")

print(
    compile_error(
        "try:\n    pass\nexcept* ValueError:\n    pass\n"
        "except TypeError:\n    pass"
    )
)
print(
    compile_error(
        "def f():\n    try:\n        pass\n"
        "    except* ValueError:\n        return 1"
    )
)
```

```text
ExceptionGroup('', (ValueError('single error'),))
SyntaxError: cannot have both 'except' and 'except*' on the same 'try'
SyntaxError: 'break', 'continue' and 'return' cannot appear in an except*
  block
```

### `split` and `subgroup`

`split` and `subgroup` are what `except*` uses underneath, and you can call
them directly. Both take an exception class (or tuple of classes), or a
predicate function called on every leaf, and both preserve the nesting.

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `message` | The group's text | `group.message` | `'g'` |
| `exceptions` | Direct members | `group.exceptions` | tuple of errors |
| `subgroup(cond)` | Matching leaves | `group.subgroup(KeyError)` | group or `None` |
| `split(cond)` | Match and rest | `group.split(KeyError)` | `(match, rest)` |

For `group = ExceptionGroup("g", [KeyError("a"), ValueError("b")])`,
`group.subgroup(KeyError)` is `ExceptionGroup('g', [KeyError('a')])`, and
`group.split(KeyError)` returns that same group paired with
`ExceptionGroup('g', [ValueError('b')])`. Either half of `split` is `None`
when it would be empty. On the nested `nightly_failures` group:

```python
timeouts = nightly_failures.subgroup(TimeoutError)
print(f"{timeouts!r}")

network_part, other_part = nightly_failures.split(
    (ConnectionError, TimeoutError)
)
print(f"{network_part.exceptions=}")
print(f"{other_part.exceptions=}")

mentions_smtp = nightly_failures.subgroup(lambda leaf: "smtp" in str(leaf))
print(f"{mentions_smtp!r}")
print(f"{nightly_failures.subgroup(KeyError)=}")
```

```text
ExceptionGroup('nightly jobs failed', [ExceptionGroup('email batch',
  [TimeoutError('smtp 1'), TimeoutError('smtp 2')])])
network_part.exceptions=(ConnectionError('payments API unreachable'),
  ExceptionGroup('email batch', [TimeoutError('smtp 1'), TimeoutError('smtp
  2')]))
other_part.exceptions=(ValueError('bad row in inventory.csv'),)
ExceptionGroup('nightly jobs failed', [ExceptionGroup('email batch',
  [TimeoutError('smtp 1'), TimeoutError('smtp 2')])])
nightly_failures.subgroup(KeyError)=None
```

### Key points

| Point | Detail |
| --- | --- |
| Purpose | Report several independent failures at once |
| `except*` | Each clause gets a subgroup; several can run |
| Leftovers | Unhandled leaves are re-raised as a group |
| Restrictions | No mixing with `except`; no `return` inside |
| Tools | `subgroup` and `split` filter by class or predicate |

## 1.14.7 EAFP vs LBYL

Unit 1.9.6 previewed the two styles with `parse_quantity_lbyl` and
`parse_quantity_eafp`. LBYL checks that an operation will succeed before
doing it; EAFP just does it and handles the failure.

| Style | Shape | Python's default? |
| --- | --- | --- |
| LBYL, *look before you leap* | `if can_do(x): do(x)` | No |
| EAFP, *easier to ask forgiveness* | `try: do(x)` / `except` | Yes |

JavaScript code leans towards LBYL (`if (key in obj)`, optional chaining),
partly because `catch` cannot filter by type. Python leans towards EAFP, and
the reasons are correctness and, since 3.11, cost.

### TOCTOU races

**TOCTOU** means *time of check to time of use*. With LBYL, the world can
change between the check and the use: another process deletes the file,
another thread pops the key. The check passed, and the use still fails. The
demo simulates the other process with an `on_gap` callback that deletes the
file between the two steps.

```python
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
```

```text
read_stock_lbyl: check passed, then FileNotFoundError
read_stock_eafp: None
```

### Zero-cost `try` (3.11), measured

*Changed in 3.11.* Older CPython executed a `SETUP_FINALLY` instruction on
entry to every `try`, pushing a block onto a per-frame block stack. Since
3.11, the compiler records the protected ranges in a side **exception table**
(shown in 1.14.12), so entering a `try` costs nothing at all; only actually
*raising* is expensive: creating the exception object and its traceback,
unwinding, and matching clauses.

The measurement: a dict lookup with and without a surrounding `try`, then the
miss case handled by `except KeyError` versus `dict.get`.

```python
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
    best = min(
        timeit.repeat(
            functools.partial(candidate, menu), number=CALLS, repeat=5
        )
    )
    print(f"{candidate.__name__:<17} {best / CALLS * 1e9:6.1f} ns per call")
```

```text
lookup_plain        56.6 ns per call
lookup_in_try       41.3 ns per call
miss_with_except   152.4 ns per call
miss_with_get       51.0 ns per call
```

> **Note:** timings vary by machine and by run; only the ratios matter. The
> first two lines are equal within measurement noise (here the `try` version
> even came out faster), which is the zero-cost entry. The raised-and-caught
> miss is about three times slower than `get`.

### When LBYL is better

| Situation | Prefer | Why |
| --- | --- | --- |
| Failure is rare | EAFP | `try` is free; a check runs every time |
| Failure is common | LBYL / `get` / `in` | Raising costs far more |
| Resource can change | EAFP | No TOCTOU gap |
| Side effects | LBYL | Validate before the first write |
| User-facing message | LBYL | The check knows which rule failed |

The side-effect row in code: charging a card and then discovering the stock is
short leaves the system half-updated, so check first.

```python
def place_order(
    stock: dict[str, int], charges: list[int], sku: str, quantity: int
) -> str:
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
```

```text
rejected: only 2 tea left [] {'tea': 2}
placed [60] {'tea': 0}
```

### Key points

| Point | Detail |
| --- | --- |
| EAFP | Python's default; no race between check and use |
| TOCTOU | A passed check can be stale by the time of use |
| Cost | Entering `try` is free (3.11+); raising is not |
| Common misses | Use `get`, `in` or a check |
| Side effects | Validate everything before the first write |

## 1.14.8 Logging exceptions

Inside an `except` block, **`logger.exception(message)`** logs at `ERROR`
level and appends the full traceback; it is shorthand for
`logger.error(message, exc_info=True)`. Call it only while an exception is
being handled, because it reads the current exception from the thread state.
Pass values as `%s` arguments instead of an f-string: the `logging` module
formats the message only if the record is actually emitted, so a filtered-out
debug message costs almost nothing. JavaScript's `console.error(err)` prints
`err.stack`; Python's logger additionally routes the record through levels,
handlers and formatters (Phase 4 covers the configuration).

The demo sends the logger's output to an in-memory stream so it can print the
interesting lines; the traceback frame lines contain machine-specific paths.

```python
log_stream = io.StringIO()
payments_logger = logging.getLogger("shop.payments")
payments_logger.handlers.clear()
stream_handler = logging.StreamHandler(log_stream)
stream_handler.setFormatter(
    logging.Formatter("%(levelname)s %(name)s: %(message)s")
)
payments_logger.addHandler(stream_handler)
payments_logger.setLevel(logging.INFO)
payments_logger.propagate = False


def capture_payment(order_id: int, amount_text: str) -> int:
    """Log the failure with its traceback, then re-raise for the caller."""
    try:
        return int(amount_text)
    except ValueError:
        payments_logger.exception(
            "could not capture payment for order %s", order_id
        )
        raise


print(f"{raised_error_name(lambda: capture_payment(42, '49x'))=}")
logged_lines = log_stream.getvalue().splitlines()
print(f"{len(logged_lines)} log lines; first two and last:")
print("\n".join([*logged_lines[:2], logged_lines[-1]]))
```

```text
raised_error_name(lambda: capture_payment(42, '49x'))='ValueError'
5 log lines; first two and last:
ERROR shop.payments: could not capture payment for order 42
Traceback (most recent call last):
ValueError: invalid literal for int() with base 10: '49x'
```

### Never swallow errors

Every `except` must do one of three things: handle the failure fully (fall
back to a value the caller expects), translate it (`raise … from`), or record
it and re-raise. The anti-patterns:

| Anti-pattern | What goes wrong |
| --- | --- |
| `except Exception: pass` | Bugs disappear silently |
| `except Exception: return None` | "No result" looks like "broken" |
| Log and continue | The program runs on with bad state |
| `except` around a big block | Catches errors you never meant to guard |

The example shows the first one hiding a real bug: a misspelled method name
raises `AttributeError`, which the broad handler turns into a plausible
default.

```python
def shipping_fee_swallowed(order: dict[str, Any]) -> int:
    """Bug: .uper() is a typo, but the broad except hides it."""
    try:
        city = order["city"]
        return 0 if city.uper() == "PUNE" else 50  # type: ignore[attr-defined]
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
```

```text
shipping_fee_swallowed({'city': 'Pune'})=50  (wrong, and no error)
shipping_fee({'city': 'Pune'})=0
shipping_fee({})=50
```

Notice how the correct version also uses the `else`-style layout from 1.14.2:
the `try` guards only the dictionary lookup, and the comparison runs outside
it, where a typo would surface immediately.

### Key points

| Point | Detail |
| --- | --- |
| `logger.exception` | ERROR level plus traceback; only inside `except` |
| `%s` arguments | Formatted only if the record is emitted |
| Three options | Handle, translate, or record and re-raise |
| Narrow `try` | Guard only the line that can fail as expected |

## 1.14.9 The `with` statement

`with EXPRESSION as name:` works with any **context manager**: an object with
two special methods. `__enter__` runs on entry and its return value is bound
to `name`; `__exit__` runs on **every** exit from the block, normal or not,
and is told whether an exception is in flight. That makes `with` the
structured way to write "acquire, use, always release": files, locks,
database transactions, temporary settings. The JavaScript equivalent is a
hand-written `try { … } finally { resource.close() }`, or the newer `using`
declaration with `Symbol.dispose` from the TC39 explicit-resource-management
proposal. The Python version has one extra power: `__exit__` sees the
exception and can choose to suppress it.

| Method | Called | Receives | Returns |
| --- | --- | --- | --- |
| `__enter__(self)` | On entry | — | Value bound by `as` |
| `__exit__(self, t, e, tb)` | On every exit | `None`×3 or error info | Truthy suppresses |

The manager below prints what `__exit__` receives on a normal exit and on an
error.

```python
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
        print(
            f"__exit__({exc_type=}, {exc=}, "
            f"traceback given: {tb is not None})"
        )
        return False


with ExitInspector() as bound_value:
    print(f"body: {bound_value=}")
try:
    with ExitInspector():
        raise ValueError("body failed")
except ValueError as error:
    print(f"propagated: {error!r}")
```

```text
__enter__ called
body: bound_value='value bound by as'
__exit__(exc_type=None, exc=None, traceback given: False)
__enter__ called
__exit__(exc_type=<class 'ValueError'>, exc=ValueError('body failed'),
  traceback given: True)
propagated: ValueError('body failed')
```

### Suppression by returning `True`

If `__exit__` returns a truthy value, the exception is discarded and execution
continues after the `with` block. Use this deliberately and narrowly; the
class below suppresses only the listed exception classes, a hand-written
version of `contextlib.suppress` (1.14.10).

```python
class IgnoreErrors:
    """Suppress only the listed exception classes."""

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
```

```text
continued after a suppressed KeyError
raised_error_name(convert_inside_ignore)='ValueError'
```

> **Warning:** returning a truthy value by accident (for example a non-empty
> list, or `self`) swallows every error raised in the block. Annotate
> `__exit__` as returning `bool` or `None` and return `False` or nothing
> unless suppression is the point.

### The desugared form

PEP 343 defines `with` as shorthand for roughly the code below. Like every
special method, `__enter__` and `__exit__` are looked up on the **type**, not
the instance, and `__exit__` is fetched *before* `__enter__` is called:

```python
manager = EXPRESSION
enter = type(manager).__enter__      # looked up on the type
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

Running this expansion by hand with `ExitInspector` prints the same lines as
the real `with` above:

```python
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
```

```text
__enter__ called
body: entered_value='value bound by as'
__exit__(exc_type=<class 'ValueError'>, exc=ValueError('body failed'),
  traceback given: True)
would re-raise: ValueError('body failed')
```

Notice two consequences of the expansion. If `__enter__` raises, the `try`
has not started, so `__exit__` is *not* called. And the body's `return`,
`break` and `continue` all pass through the `else`-equivalent path, so
`__exit__(None, None, None)` runs for them too.

### Multiple managers

`with A() as a, B() as b:` is the same as nesting two `with` statements:
managers are entered left to right and exited **right to left** (LIFO).
Since 3.10 the list can be wrapped in parentheses across lines. If entering
the second manager fails, the first one is still exited, because by then the
first `with` is already active.

```python
class Tracked:
    """Log enter/exit; optionally fail on enter."""

    def __init__(
        self, name: str, events: list[str], fail_on_enter: bool = False
    ) -> None:
        self.name, self.events = name, events
        self.fail_on_enter = fail_on_enter

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
    with (
        Tracked("database", events),
        Tracked("cache", events, fail_on_enter=True),
    ):
        events.append("body")
except OSError as error:
    events.append(f"caught {error}")
print(events)
```

```text
['enter database', 'enter cache', 'body uses database and cache', 'exit
  cache', 'exit database']
['enter database', 'exit database', 'caught cannot open cache']
```

### Example: `Timer`

A timing context manager measures a block, not a whole function (the `@timer`
decorator from 1.12.3 times calls). `__exit__` reports even when the block
raises, and does not suppress. Lab 1.14 asks for a richer `StopwatchTimer`;
the Phase 1 project times its run with this `Timer`.

```python
class Timer:
    """Time a with block and report "<label> took <ms> ms"."""

    def __init__(
        self, label: str, report: Callable[[str], object] = print
    ) -> None:
        self.label = label
        self.report = report
        self.elapsed_seconds = 0.0

    def __enter__(self) -> Timer:
        self._started = time.perf_counter()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.elapsed_seconds = time.perf_counter() - self._started
        self.report(f"{self.label} took {self.elapsed_seconds * 1000:.2f} ms")
```

Using it, including on a failing block:

```python
with Timer("sum of squares") as squares_timer:
    total = sum(number * number for number in range(200_000))
print(f"{total=}, {squares_timer.elapsed_seconds > 0=}")

try:
    with Timer("failing block"):
        raise ConnectionError("upstream down")
except ConnectionError as error:
    print(f"still reported, then propagated: {error!r}")
```

```text
sum of squares took 10.93 ms
total=2666646666700000, squares_timer.elapsed_seconds > 0=True
failing block took 0.00 ms
still reported, then propagated: ConnectionError('upstream down')
```

> **Note:** the durations vary by machine and by run.

### Example: `DatabaseTransaction`

The classic use: commit if the block succeeds, roll back if it raises, and
let the exception continue. The demo uses an in-memory SQLite database (in
the standard library, no server needed). A `CHECK` constraint makes an
overdraft fail halfway through a transfer, and the rollback undoes the first
`UPDATE`.

```python
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
bank.execute(
    "CREATE TABLE accounts "
    "(name TEXT PRIMARY KEY, balance INTEGER CHECK (balance >= 0))"
)
inserted = bank.executemany(
    "INSERT INTO accounts VALUES (?, ?)", [("asha", 500), ("ravi", 100)]
)
print(f"{inserted.rowcount} accounts created")
```

```text
2 accounts created
```

A transfer that succeeds, then one that overdraws `ravi`:

```python
def transfer(
    connection: sqlite3.Connection, source: str, target: str, amount: int
) -> str:
    """Move money inside one transaction."""
    try:
        with DatabaseTransaction(connection) as cursor:
            cursor.execute(
                "UPDATE accounts SET balance = balance + ? WHERE name = ?",
                (amount, target),
            )
            cursor.execute(
                "UPDATE accounts SET balance = balance - ? WHERE name = ?",
                (amount, source),
            )
    except sqlite3.IntegrityError as error:
        return f"rolled back ({error})"
    return "committed"


def balances(connection: sqlite3.Connection) -> dict[str, int]:
    """Current balances by name."""
    return dict(
        connection.execute("SELECT name, balance FROM accounts ORDER BY name")
    )


print(transfer(bank, "asha", "ravi", 200), balances(bank))
print(transfer(bank, "ravi", "asha", 1_000), balances(bank))
```

```text
committed {'asha': 300, 'ravi': 300}
rolled back (CHECK constraint failed: balance >= 0) {'asha': 300, 'ravi':
  300}
```

> **Note:** a `sqlite3.Connection` is itself a context manager, but its
> `__exit__` commits or rolls back and does **not close** the connection. Use
> `contextlib.closing(connection)` (1.14.10) to close it.

### Key points

| Point | Detail |
| --- | --- |
| Protocol | `__enter__` on entry, `__exit__` on every exit |
| `__exit__` args | `None`×3, or type, value, traceback |
| Suppress | Return truthy from `__exit__`; do it narrowly |
| Lookup | Both methods are looked up on the type |
| Several managers | Entered left to right, exited LIFO |

## 1.14.10 `contextlib`

The standard library's toolbox for context managers. Writing a class with
`__enter__` and `__exit__` every time is verbose, and many cleanup patterns
are the same everywhere; `contextlib` packages them.

### Reference: one-resource helpers

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `@contextmanager` | Generator → manager | `with tag("b") as t:` | `t == "b"` |
| `suppress(*errors)` | Ignore listed errors | `with suppress(KeyError): {}["x"]` | no error |
| `closing(thing)` | Call `close()` on exit | `with closing(client) as c:` | `c.closed` is `True` |
| `redirect_stdout(s)` | Capture `print` | `with redirect_stdout(buf): print("hi")` | `buf` holds `'hi\n'` |

### Reference: composing helpers

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `nullcontext(value)` | Do nothing | `with nullcontext(5) as v:` | `v == 5` |
| `chdir(path)` | Change cwd, restore (3.11+) | `with chdir("/tmp"):` | `Path.cwd()` is `/tmp` |
| `ExitStack()` | Many managers, LIFO | `stack.callback(print, "bye")` | prints `bye` on exit |
| `AbstractContextManager` | ABC, default `__enter__` | `class A(AbstractContextManager):` | `__enter__` returns self |

(`tag` in the first row is a small `@contextmanager` generator that yields its
argument, and `client` is any object with a `close()` method.) Each row gets a
full example below.

### `@contextmanager`

`@contextmanager` turns a generator function with exactly one `yield` into a
context manager. The code before `yield` is the `__enter__`, the yielded value
is bound by `as`, and the code after `yield` is the `__exit__`. Under the
hood the decorator returns a `_GeneratorContextManager` object: its
`__enter__` calls `next()` on the generator, and its `__exit__` either calls
`next()` again (normal exit, expecting `StopIteration`) or **throws the
exception into the generator at the `yield`** with `generator.throw()` (Unit
1.13). That second path is why cleanup must sit in `finally`: otherwise the
exception propagates out of the `yield` and the cleanup line never runs.

The demo leases a connection from a pool; the unsafe version leaks it on an
error.

```python
@contextmanager
def leased_connection_unsafe(pool: list[str]) -> Iterator[str]:
    """Bug: no try/finally, so an exception skips the return to the pool."""
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
```

```text
leased_connection_unsafe  pool after an error: ['conn-1']
leased_connection         pool after an error: ['conn-1', 'conn-2']
```

> **Warning:** a `@contextmanager` generator without `try` / `finally` around
> its `yield` skips its cleanup whenever the body raises. Always wrap the
> `yield`.

A `@contextmanager` object also works as a **decorator** (it is a
`ContextDecorator`): each call of the decorated function runs inside a fresh
`with`.

```python
shared_pool = ["conn-1"]


@leased_connection(shared_pool)
def nightly_report() -> str:
    """Runs while a connection is leased from shared_pool."""
    return f"pool during the call: {shared_pool}"


print(nightly_report())
print(f"pool after the call: {shared_pool}")
```

```text
pool during the call: []
pool after the call: ['conn-1']
```

### `suppress`

`with suppress(FileNotFoundError):` replaces a `try` / `except …: pass`. Use
it only when ignoring the error is truly the intent. (For files specifically,
`Path.unlink(missing_ok=True)` does the same.) Note in the demo that the
`continue` inside the block skips the second `print` only when no error
occurred; when the error is suppressed, execution resumes after the `with`.

```python
temporary_report = scratch_dir / "unit_1_14_temp_report.txt"
temporary_report.write_text("draft", encoding="utf-8")
for attempt in (1, 2):
    with suppress(FileNotFoundError):
        temporary_report.unlink()
        print(f"attempt {attempt}: deleted")
        continue
    print(f"attempt {attempt}: already gone, FileNotFoundError suppressed")
```

```text
attempt 1: deleted
attempt 2: already gone, FileNotFoundError suppressed
```

### `closing`

For an object that has `close()` but is not a context manager (older APIs,
some third-party clients), `closing(thing)` returns `thing` from `__enter__`
and calls `thing.close()` on exit.

```python
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
```

```text
printed 'ORDER-42'
printer.closed=True
raised_error_name(use_without_closing)='TypeError'
```

### `redirect_stdout`

`redirect_stdout(stream)` temporarily points `sys.stdout` at another stream,
so everything `print` writes is captured. `redirect_stderr` does the same for
`sys.stderr`.

```python
def noisy_import_step() -> int:
    """Prints progress as a side effect."""
    print("importing 3 rows")
    print("done")
    return 3


captured_output = io.StringIO()
with redirect_stdout(captured_output):
    imported_count = noisy_import_step()
print(f"{imported_count=}, {captured_output.getvalue()=}")
```

```text
imported_count=3, captured_output.getvalue()='importing 3 rows\ndone\n'
```

> **Warning:** `redirect_stdout` replaces a process-wide global, so it is not
> safe across threads: output from other threads is captured too.

### `nullcontext`

A manager that does nothing and returns its argument. It removes an `if` when
a resource is sometimes managed and sometimes not, for example "accept a path
(open and close it) or an already-open stream (leave it open)".

```python
def count_lines(source: Path | io.StringIO) -> int:
    """Open a path ourselves, or use a caller-owned stream as is."""
    manager = (
        source.open(encoding="utf-8")
        if isinstance(source, Path)
        else nullcontext(source)
    )
    with manager as stream:
        return sum(1 for _ in stream)


lines_path = scratch_dir / "unit_1_14_lines.txt"
lines_path.write_text("a\nb\nc\n", encoding="utf-8")
caller_stream = io.StringIO("x\ny\n")
print(f"{count_lines(lines_path)=}, {count_lines(caller_stream)=}")
print(f"{caller_stream.closed=}")
with nullcontext(42) as answer:
    print(f"{answer=}")
```

```text
count_lines(lines_path)=3, count_lines(caller_stream)=2
caller_stream.closed=False
answer=42
```

> **Note:** the notebook prints the first two lines on one line; the `print`
> is split here to fit the screen.

### `chdir`

*New in 3.11.* `chdir(path)` changes the process working directory for the
block and always changes it back. Like `redirect_stdout` it changes
process-wide state, so avoid it in threaded or async code; prefer passing
absolute paths.

```python
directory_before = Path.cwd()
with chdir(scratch_dir):
    print(f"inside:  cwd name = {Path.cwd().name}")
    print(f"{Path('unit_1_14_lines.txt').exists()=}  (relative to the new cwd)")
print(f"after:   restored = {Path.cwd() == directory_before}")
```

```text
inside:  cwd name = _scratch
Path('unit_1_14_lines.txt').exists()=True  (relative to the new cwd)
after:   restored = True
```

### `ExitStack`

`ExitStack` is for a number of managers known only at run time.
`enter_context(manager)` enters one and schedules its exit;
`callback(function, *args)` schedules any cleanup function. Internally it
keeps a stack (a `deque`) of exit callbacks, and when the stack itself exits
it pops and runs them in reverse order, even after an error, passing the
exception from one to the next exactly as nested `with` statements would.

```python
cleanup_log: list[str] = []
with ExitStack() as stack:
    for name in ("orders", "payments", "audit"):
        stack.enter_context(Tracked(name, cleanup_log))
    stack.callback(cleanup_log.append, "callback: flush metrics")
    cleanup_log.append("body runs")
print(cleanup_log)
```

```text
['enter orders', 'enter payments', 'enter audit', 'body runs', 'callback:
  flush metrics', 'exit audit', 'exit payments', 'exit orders']
```

`pop_all()` moves the pending cleanups to a new stack. That is the pattern
for "acquire everything, and only keep it if all acquisitions succeed": if
any acquisition fails, the `with` unwinds the ones already entered; if all
succeed, `pop_all()` hands them to the caller, who closes them later.

```python
def acquire_all(names: list[str], events: list[str]) -> ExitStack:
    """Enter every manager; if one fails, the entered ones are exited."""
    with ExitStack() as stack:
        for name in names:
            stack.enter_context(
                Tracked(name, events, fail_on_enter=(name == "broken"))
            )
        return stack.pop_all()


events = []
kept_open = acquire_all(["orders", "payments"], events)
print(f"after acquire: {events}")
kept_open.close()
print(f"after close:   {events}")

events = []
failure = raised_error_name(lambda: acquire_all(["orders", "broken"], events))
print(f"{failure=}, {events=}")
```

```text
after acquire: ['enter orders', 'enter payments']
after close:   ['enter orders', 'enter payments', 'exit payments', 'exit
  orders']
failure='OSError', events=['enter orders', 'exit orders']
```

> **Note:** the notebook prints the last line as
> `raised_error_name(lambda: acquire_all(['orders', 'broken'], events))='OSError', …`;
> the call is stored in `failure` here to keep the line short.

### `AbstractContextManager`

Subclassing `AbstractContextManager` gives a default `__enter__` that returns
`self`, so a class-based manager only writes `__exit__`. It is also an ABC
with a structural `__subclasshook__` (Unit 1.11): any class that has both
methods counts as a context manager for `isinstance`, inheritance or not.

```python
class AuditScope(AbstractContextManager):
    """Only __exit__ is written; __enter__ comes from the ABC."""

    def __init__(self) -> None:
        self.entries: list[str] = []

    def __exit__(self, *exc_info: object) -> None:
        self.entries.append("scope closed")


with AuditScope() as scope:
    scope.entries.append("work")
print(f"{scope.entries=}")
print(f"{isinstance(Timer('x'), AbstractContextManager)=}  (structural)")
print(f"{isinstance(LegacyPrinterClient(), AbstractContextManager)=}")
```

```text
scope.entries=['work', 'scope closed']
isinstance(Timer('x'), AbstractContextManager)=True  (structural)
isinstance(LegacyPrinterClient(), AbstractContextManager)=False
```

> **Note:** the notebook's second line ends with
> `(structural, no inheritance)`; it is shortened here. `Timer` does not
> inherit from the ABC, yet `isinstance` is `True`.

### Key points

| Point | Detail |
| --- | --- |
| `@contextmanager` | Setup, `yield`, cleanup in `finally` |
| Also a decorator | Each call runs inside a fresh `with` |
| `suppress` / `closing` | Replace common `try` boilerplate |
| Global state | `redirect_stdout` and `chdir` are not thread-safe |
| `ExitStack` | Dynamic number of managers; `pop_all` to keep them |
| ABC | `AbstractContextManager` checks structurally |

## 1.14.11 `assert` and `warnings`

### `assert` and `-O`

`assert condition, message` raises `AssertionError(message)` when the
condition is false. It is for **internal invariants** ("this can never happen
if my code is right"), never for validating input. The reason is that running
Python with **`-O`** sets the constant `__debug__` to `False`, and the
compiler then **removes every assert statement** from the bytecode; the
condition is not even evaluated. (`-OO` also strips docstrings.) JavaScript's
`console.assert` only logs and never throws, so neither language's assert is
a substitute for real validation.

The demo runs the same script in child interpreters with and without `-O`.
`PYTHON_COLORS=0` turns off the coloured tracebacks of 3.13+.

```python
CHILD_ENV = {**os.environ, "PYTHON_COLORS": "0"}
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
    output = completed.stdout or completed.stderr
    last_line = output.strip().splitlines()[-1]
    label = " ".join(flags) or "(no -O)"
    print(f"python {label:<8} exit={completed.returncode}  {last_line}")
```

```text
python (no -O)  exit=1  AssertionError: arithmetic invariant broken
python -O       exit=0  assert was stripped; __debug__ = False
```

A classic trap: `assert (condition, "message")` asserts a non-empty
**tuple**, which is always true. The compiler warns with a `SyntaxWarning`.

```python
with warnings.catch_warnings(record=True) as assert_warnings:
    warnings.simplefilter("always")
    compile("assert (1 == 2, 'never fails')", "<demo>", "exec")
print([f"{w.category.__name__}: {w.message}" for w in assert_warnings])
```

```text
['SyntaxWarning: assertion is always true, perhaps remove parentheses?']
```

### `warnings.warn`

`warnings.warn(message, category, stacklevel)` reports something the caller
should fix without stopping the program. Warning categories are exception
classes (subclasses of `Warning`), which is what makes escalating them to
errors possible. `stacklevel=2` blames the caller's line instead of the line
inside your function, so the reported location is the code that needs
changing.

| Category | Shown by default? | Use for |
| --- | --- | --- |
| `UserWarning` | Yes | General "you probably didn't mean this" |
| `DeprecationWarning` | Only from `__main__` | API going away, for developers |
| `FutureWarning` | Yes | Behaviour will change, for end users |
| `RuntimeWarning` | Yes | Dubious runtime situations |
| `SyntaxWarning` | Yes | Dubious syntax (compile time) |

`UserWarning` is the default category. The demo records warnings with
`catch_warnings(record=True)` so the output is deterministic.

```python
def legacy_price_in_rupees(price_in_paise: int) -> float:
    """Old API: warn callers, keep working."""
    warnings.warn(
        "use price_in_paise / 100 with Decimal",
        DeprecationWarning,
        stacklevel=2,
    )
    return price_in_paise / 100


with warnings.catch_warnings(record=True) as recorded:
    warnings.simplefilter("always")
    print(f"{legacy_price_in_rupees(24_900)=}")
for recorded_warning in recorded:
    print(f"{recorded_warning.category.__name__}: {recorded_warning.message}")
```

```text
legacy_price_in_rupees(24_900)=249.0
DeprecationWarning: use price_in_paise / 100 with Decimal
```

### Filters

**Filters** decide what happens to each warning. `warnings.simplefilter(action,
category)` and `warnings.filterwarnings(action, message=regex, category=…,
module=regex)` add filters to the front of the `warnings.filters` list, and
the first matching filter wins. The same filters can be set from outside with
`-W action::Category` or the `PYTHONWARNINGS` environment variable.

| Action | Effect |
| --- | --- |
| `"default"` | Show once per location |
| `"always"` | Show every time |
| `"once"` | Show once per message, anywhere |
| `"module"` | Show once per module |
| `"ignore"` | Never show |
| `"error"` | Raise the warning as an exception |

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `warn` | Emit a warning | `warn("old", DeprecationWarning)` | recorded or shown |
| `simplefilter` | Filter by category | `simplefilter("error", RuntimeWarning)` | filter added |
| `filterwarnings` | Filter by regex too | `filterwarnings("ignore", message="rounding")` | filter added |
| `catch_warnings` | Save and restore filters | `with catch_warnings(record=True) as w:` | `w` is a list |

Here a message filter hides one of two warnings:

```python
def noisy_conversion() -> None:
    """Emit two different warnings."""
    warnings.warn("rounding to whole rupees", UserWarning, stacklevel=2)
    warnings.warn(
        "legacy currency code INR-OLD", DeprecationWarning, stacklevel=2
    )


with warnings.catch_warnings(record=True) as kept:
    warnings.simplefilter("always")
    warnings.filterwarnings(
        "ignore", message="rounding", category=UserWarning
    )
    noisy_conversion()
    noisy_conversion()
print([str(w.message) for w in kept])
```

```text
['legacy currency code INR-OLD', 'legacy currency code INR-OLD']
```

### `catch_warnings`

`catch_warnings()` saves the filter list on entry and restores it on exit, so
changes made inside never leak. `record=True` collects `WarningMessage`
objects in a list instead of printing them.

```python
filters_before = len(warnings.filters)
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    warnings.filterwarnings("error", category=RuntimeWarning)
    print(f"inside:  {len(warnings.filters) - filters_before} filters added")
print(f"after:   {len(warnings.filters) == filters_before=}")
```

```text
inside:  2 filters added
after:   len(warnings.filters) == filters_before=True
```

### Escalating to errors

The `"error"` action turns a warning into an exception. That is how test
suites make sure no deprecated API is used (`pytest -W error`, Phase 4).
First in-process with a filter, then for a whole child interpreter with `-W`:

```python
with warnings.catch_warnings():
    warnings.simplefilter("error", DeprecationWarning)
    try:
        legacy_price_in_rupees(100)
    except DeprecationWarning as error:
        print(f"raised as an exception: {type(error).__name__}: {error}")

WARN_SCRIPT = (
    "import warnings\n"
    "warnings.warn('old checkout API', DeprecationWarning)\n"
    "print('continued')"
)
for flags in ([], ["-W", "error::DeprecationWarning"]):
    completed = subprocess.run(
        [sys.executable, *flags, "-c", WARN_SCRIPT],
        capture_output=True,
        text=True,
        check=False,
        env=CHILD_ENV,
    )
    outcome = (
        completed.stdout.strip()
        or completed.stderr.strip().splitlines()[-1]
    )
    label = " ".join(flags) or "(default)"
    print(f"{label:<28} exit={completed.returncode}  {outcome}")
```

```text
raised as an exception: DeprecationWarning: use price_in_paise / 100 with
  Decimal
(default)                    exit=0  continued
-W error::DeprecationWarning exit=1  DeprecationWarning: old checkout API
```

### Key points

| Point | Detail |
| --- | --- |
| `assert` | Internal invariants only; removed by `-O` |
| Tuple trap | `assert (cond, msg)` is always true |
| `warn` | Use `stacklevel=2` to blame the caller |
| Filters | First match wins; `-W` and `PYTHONWARNINGS` too |
| `catch_warnings` | Restores filters; `record=True` collects |
| `"error"` | Turns warnings into exceptions (tests) |

## 1.14.12 Under the hood

### The exception table

Since 3.11 there is no bytecode instruction that "enters" a `try`. Instead,
each code object carries an **exception table**: *if an exception is raised
between instruction offsets `start` and `end`, jump to `target` with the
value stack cut to `depth`*. When an exception occurs, the interpreter looks
up the current instruction offset in that table; if no entry covers it, the
frame is unwound and the search continues in the caller. `dis` prints the
table after the instructions as `ExceptionTable:`, with `L` labels.
Instruction names change between versions; the structure is the point.

What to notice in the listing:

- the `try` body (`L1` to `L2`) has no setup instruction at all: that is the
  zero-cost entry measured in 1.14.7;
- `PUSH_EXC_INFO`, `CHECK_EXC_MATCH` and `POP_JUMP_IF_FALSE` implement
  `except ValueError` (an `isinstance`-style test, 1.14.1);
- the handler ends with `STORE_FAST` / `DELETE_FAST` of `error`: the hidden
  `del error` from 1.14.2;
- `RERAISE` re-raises when no clause matches.

```python
def parse_quantity(text: str) -> int:
    """try / except with an as-name."""
    try:
        return int(text)
    except ValueError as error:
        print(error)
        return 0


dis.dis(parse_quantity)
```

```text
   1           RESUME                   0

   3           NOP

   4   L1:     LOAD_GLOBAL              1 (int + NULL)
               LOAD_FAST_BORROW         0 (text)
               CALL                     1
       L2:     RETURN_VALUE

  --   L3:     PUSH_EXC_INFO

   5           LOAD_GLOBAL              2 (ValueError)
               CHECK_EXC_MATCH
               POP_JUMP_IF_FALSE       23 (to L7)
               NOT_TAKEN
               STORE_FAST               1 (error)

   6   L4:     LOAD_GLOBAL              5 (print + NULL)
               LOAD_FAST                1 (error)
               CALL                     1
               POP_TOP

   7   L5:     POP_EXCEPT
               LOAD_COMMON_CONSTANT     7 (None)
               STORE_FAST               1 (error)
               DELETE_FAST              1 (error)
               LOAD_SMALL_INT           0
               RETURN_VALUE

  --   L6:     LOAD_COMMON_CONSTANT     7 (None)
               STORE_FAST               1 (error)
               DELETE_FAST              1 (error)
               RERAISE                  1

   5   L7:     RERAISE                  0

  --   L8:     COPY                     3
               POP_EXCEPT
               RERAISE                  1
ExceptionTable:
  L1 to L2 -> L3 [0]
  L3 to L4 -> L8 [1] lasti
  L4 to L5 -> L6 [1] lasti
  L6 to L8 -> L8 [1] lasti
```

Read the table from the top: an error in the `try` body (`L1`–`L2`) jumps to
the handler at `L3` with an empty stack (`[0]`). The other three entries
protect the handler itself: if the `print(error)` raises, `L6` still deletes
`error` before re-raising, and `L8` restores the previous "currently handled"
exception. `lasti` means the offset of the failing instruction is pushed too,
so a re-raise keeps the original traceback line.

The same table is available as data: `dis.Bytecode(...).exception_entries`
lists the entries (offsets in bytes), and the raw, compactly encoded table
lives in `co_exceptiontable`.

```python
for entry in dis.Bytecode(parse_quantity).exception_entries:
    print(
        f"offsets {entry.start:>3}-{entry.end:<3} -> handler "
        f"{entry.target:>3}  depth={entry.depth} lasti={entry.lasti}"
    )
print(f"{len(parse_quantity.__code__.co_exceptiontable)=} bytes")
```

```text
offsets   6-26  -> handler  28  depth=0 lasti=False
offsets  28-50  -> handler  94  depth=1 lasti=True
offsets  50-72  -> handler  84  depth=1 lasti=True
offsets  84-94  -> handler  94  depth=1 lasti=True
len(parse_quantity.__code__.co_exceptiontable)=16 bytes
```

### `with` bytecode

In 3.14+, `LOAD_SPECIAL` looks up `__enter__` and `__exit__` on the **type**
(3.11 to 3.13 used a single `BEFORE_WITH` instruction). The body is covered by
an exception-table entry whose handler runs `WITH_EXCEPT_START`, which calls
`__exit__(type, value, traceback)`, and then tests the result with `TO_BOOL`:
truthy means suppress (`POP_JUMP_IF_TRUE` skips the `RERAISE`). On the normal
path, `__exit__(None, None, None)` is a plain `CALL` with three `None`s. This
is the desugared form of 1.14.9, compiled.

```python
def first_line(path: Path) -> str:
    """A with statement around a file."""
    with path.open(encoding="utf-8") as stream:
        return stream.readline()


dis.dis(first_line)
```

```text
   1           RESUME                   0

   3           LOAD_FAST_BORROW         0 (path)
               LOAD_ATTR                1 (open + NULL|self)
               LOAD_CONST               1 ('utf-8')
               LOAD_CONST               2 (('encoding',))
               CALL_KW                  1
               COPY                     1
               LOAD_SPECIAL             1 (__exit__)
               SWAP                     2
               SWAP                     3
               LOAD_SPECIAL             0 (__enter__)
               CALL                     0
       L1:     STORE_FAST               1 (stream)

   4           LOAD_FAST_BORROW         1 (stream)
               LOAD_ATTR                3 (readline + NULL|self)
               CALL                     0

   3   L2:     SWAP                     3
               SWAP                     2
               LOAD_COMMON_CONSTANT     7 (None)
               LOAD_COMMON_CONSTANT     7 (None)
               LOAD_COMMON_CONSTANT     7 (None)
               CALL                     3
               POP_TOP
               RETURN_VALUE
       L3:     PUSH_EXC_INFO
               WITH_EXCEPT_START
               TO_BOOL
               POP_JUMP_IF_TRUE         2 (to L4)
               NOT_TAKEN
               RERAISE                  2
       L4:     POP_TOP
       L5:     POP_EXCEPT
               POP_TOP
               POP_TOP
               POP_TOP
               LOAD_COMMON_CONSTANT     7 (None)
               RETURN_VALUE

  --   L6:     COPY                     3
               POP_EXCEPT
               RERAISE                  1
ExceptionTable:
  L1 to L2 -> L3 [2] lasti
  L3 to L5 -> L6 [4] lasti
```

Notice the order: `__exit__` is loaded *before* `__enter__` is called, exactly
as in the desugared form, so an object whose type lacks `__exit__` fails
before its `__enter__` ever runs. Also note that the `return
stream.readline()` value is kept on the stack while `__exit__` runs, which is
the bytecode behind "the return value is computed first, then cleanup runs".

### Key points

| Point | Detail |
| --- | --- |
| Exception table | Maps offset ranges to handlers; no setup opcode |
| `CHECK_EXC_MATCH` | The `isinstance`-style test of `except` |
| Hidden `del` | `STORE_FAST None` + `DELETE_FAST` of the `as` name |
| `LOAD_SPECIAL` | Fetches `__exit__`, then `__enter__`, from the type |
| `WITH_EXCEPT_START` | Calls `__exit__` with the error; `TO_BOOL` decides |

## Lab 1.14

Six exercises. In the notebook each one has a stub that raises
`NotImplementedError` and a check cell built on `run_checks`, which prints
`PASS` or `FAIL` per case and a total. Two extra helpers appear in the
checks: `caught_error(thunk)` returns the exception a call raises (or
`None`), and `error_report(thunk)` turns it into a tuple of
(type name, message, notes, cause type name).

### Exercise 1 — `parse_age(text)` with notes and chaining

Return the age as an `int` after stripping whitespace.

- Not a whole number (`int()` fails): raise
  `ValueError(f"invalid age: {text!r}")` **chained** from the original error
  (so `__cause__` is set), with the note
  `"age must be a whole number, e.g. 42"`.
- Outside 0–150: raise `ValueError(f"age out of range: {age}")` with the note
  `"age must be between 0 and 150"` and no cause.

| Check | Call | Expected |
| --- | --- | --- |
| plain | `parse_age("42")` | `42` |
| whitespace | `parse_age(" 7 ")` | `7` |
| bounds | `"0"` and `"150"` | `(0, 150)` |
| not a number | `parse_age("abc")` | message, note, cause `ValueError` |
| decimal | `parse_age("4.5")` | `"invalid age: '4.5'"` |
| too large | `parse_age("200")` | range note, cause `NoneType` |
| negative | `parse_age("-1")` | `"age out of range: -1"` |

**Hints.** Build the new exception first, call `add_note` on it, then
`raise new_error from error`. Do the range check *outside* the `try`, so the
range error has no `__context__` either.

<details><summary>Solution</summary>

```python
AGE_NOT_A_NUMBER_NOTE = "age must be a whole number, e.g. 42"
AGE_RANGE_NOTE = "age must be between 0 and 150"


def parse_age(text: str) -> int:
    """Parse an age in years, with helpful notes on failure."""
    try:
        age = int(text.strip())
    except ValueError as error:
        invalid = ValueError(f"invalid age: {text!r}")
        invalid.add_note(AGE_NOT_A_NUMBER_NOTE)
        raise invalid from error
    if not 0 <= age <= 150:
        out_of_range = ValueError(f"age out of range: {age}")
        out_of_range.add_note(AGE_RANGE_NOTE)
        raise out_of_range
    return age
```

</details>

### Exercise 2 — `load_config(path)` converting errors with `from`

Read a JSON file (UTF-8) and return the resulting `dict`. Convert every
failure into the given `ConfigError` (a plain `Exception` subclass), chained
with `from`:

| Failure | Message | `__cause__` |
| --- | --- | --- |
| File missing | `config file not found: {name}` | `FileNotFoundError` |
| Invalid JSON | `invalid JSON in {name} at line {n}` | `JSONDecodeError` |
| Not an object | `config must be a JSON object, got {type}` | `None` |

Here `{name}` is `path.name`, `{n}` is the decode error's `lineno`, and
`{type}` is the type name of the parsed value (for example `list`).

| Check | File content | Expected |
| --- | --- | --- |
| loads | `{"debug": true, "port": 8000}` | the dict |
| missing | (no file) | `ConfigError`, cause `FileNotFoundError` |
| invalid JSON | `{"debug": true,` newline `"port": }` | "at line 2", cause `JSONDecodeError` |
| not an object | `[1, 2]` | "got list", cause `NoneType` |

**Hints.** Use two separate `try` blocks, one for reading and one for parsing,
so each catches only its own failure. `json.JSONDecodeError` is a subclass of
`ValueError` and carries `lineno`.

<details><summary>Solution</summary>

```python
class ConfigError(Exception):
    """Raised when a configuration file cannot be loaded."""


def load_config(path: Path) -> dict[str, Any]:
    """Load a JSON object from path, raising ConfigError on any failure."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise ConfigError(f"config file not found: {path.name}") from error
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise ConfigError(
            f"invalid JSON in {path.name} at line {error.lineno}"
        ) from error
    if not isinstance(data, dict):
        raise ConfigError(
            f"config must be a JSON object, got {type(data).__name__}"
        )
    return data
```

</details>

### Exercise 3 — a `StopwatchTimer` context-manager class

`StopwatchTimer(clock=time.perf_counter)`, where `clock` returns seconds as a
float:

- `__enter__` records the start time and returns the stopwatch; entering one
  that is already running raises `RuntimeError`. Entering it again later
  starts over (laps cleared).
- `__exit__` records the stop time and never suppresses exceptions.
- `elapsed` (a property): `0.0` before the first start; `clock() - start`
  while running; `stop - start` afterwards (it no longer changes).
- `running`: `True` only inside the block.
- `lap()`: seconds since the previous lap (or the start); appends it to the
  `laps` list and returns it; `RuntimeError` if not running.

The checks inject `fake_clock(*readings)`, a clock that returns the given
readings one per call, so every duration is exact.

| Check | Clock readings | Expected |
| --- | --- | --- |
| returns self | `0` | `__enter__()` returns the stopwatch |
| before start | real clock | `(0.0, False, [])` |
| laps and total | `0, 1, 3, 6` | `([1.0, 2.0], 6.0)` |
| elapsed while running | `10, 14, 15` | `(True, 4.0, False, 5.0)` |
| error propagates | `0, 2.5` | `("ValueError", 2.5)` |
| lap when stopped | real clock | `RuntimeError` |
| nested enter | `0, 1, 2, 3` | `RuntimeError` |
| real clock | `sleep(0.01)` | elapsed ≥ 0.01 |

**Hints.** Keep `_started` and `_stopped` as `float | None`. The property
picks its end point from `running`. `__exit__` can take `*exc_info` and
return `None`, which is falsy, so nothing is suppressed.

<details><summary>Solution</summary>

```python
class StopwatchTimer:
    """Context-manager stopwatch with laps and an injectable clock."""

    def __init__(self, clock: Callable[[], float] = time.perf_counter) -> None:
        self.clock = clock
        self.running = False
        self.laps: list[float] = []
        self._started: float | None = None
        self._stopped: float | None = None
        self._last_lap: float = 0.0

    def __enter__(self) -> StopwatchTimer:
        if self.running:
            raise RuntimeError("stopwatch is already running")
        self._started = self._last_lap = self.clock()
        self._stopped = None
        self.laps = []
        self.running = True
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._stopped = self.clock()
        self.running = False

    @property
    def elapsed(self) -> float:
        """Seconds since the start: live while running, frozen after."""
        if self._started is None:
            return 0.0
        end = self.clock() if self.running else self._stopped
        assert end is not None
        return end - self._started

    def lap(self) -> float:
        """Record and return the seconds since the previous lap."""
        if not self.running:
            raise RuntimeError("stopwatch is not running")
        now = self.clock()
        lap_seconds = now - self._last_lap
        self._last_lap = now
        self.laps.append(lap_seconds)
        return lap_seconds
```

The `assert end is not None` is an internal invariant (1.14.11): once
`_started` is set and the stopwatch is not running, `_stopped` has been set by
`__exit__`. It exists for the type checker, not for input validation.

</details>

### Exercise 4 — `temporary_env(**variables)` with `@contextmanager`

Set environment variables (`os.environ`) for the duration of a `with` block.
A value of `None` means "unset this variable inside the block". On exit,
**even after an exception**, restore exactly the previous state: variables
that existed get their old value back, variables that did not exist are
removed. Yield nothing.

| Check | Scenario | Expected |
| --- | --- | --- |
| set inside, removed after | `LAB_1_14_MODE="test"` | `("test", None)` |
| existing restored | override, then unset | `("eu-west-1", None, "ap-south-1")` |
| restored after an error | body raises | `("RuntimeError", None)` |
| built with `@contextmanager` | `__wrapped__` is a generator function | `True` |

**Hints.** Record `os.environ.get(name)` for every name *before* changing
anything. Put both the changes and the `yield` inside one `try`, and restore
in `finally`.

<details><summary>Solution</summary>

```python
@contextlib.contextmanager
def temporary_env(**variables: str | None) -> Iterator[None]:
    """Temporarily set (or unset, with None) environment variables."""
    previous = {name: os.environ.get(name) for name in variables}
    try:
        for name, value in variables.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        yield
    finally:
        for name, old_value in previous.items():
            if old_value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = old_value
```

</details>

### Exercise 5 — `open_many(paths)` with `ExitStack`

A `@contextmanager` that opens every path and yields the list of open file
objects, in order. Use one `ExitStack`: every file must be closed when the
block exits (also after an error), and if opening the *k*-th file fails, the
files already opened are closed before the error propagates. `opener` opens
one path; it defaults to `open(path, encoding="utf-8")` (the checks pass a
recording opener that remembers every file it opened).

| Check | Scenario | Expected |
| --- | --- | --- |
| reads and closes | three part files | contents, all closed |
| failed open closes the others | third path missing | `("FileNotFoundError", 2, True)` |
| closed after a body error | body raises `KeyError` | `("KeyError", True)` |
| default opener | no opener given | `["part 1"]` |
| no paths | empty list | `[]` |

**Hints.** Yield from *inside* the `with ExitStack()` block. A list
comprehension over `stack.enter_context(open_one(path))` opens and registers
each file; if one `open` fails, the stack unwinds the ones already entered.

<details><summary>Solution</summary>

```python
def open_utf8(path: Path) -> IO[str]:
    """Default opener for open_many."""
    return open(path, encoding="utf-8")  # closed by the caller's ExitStack


@contextlib.contextmanager
def open_many(
    paths: Iterable[Path],
    opener: Callable[[Path], IO[str]] | None = None,
) -> Iterator[list[IO[str]]]:
    """Open all paths; close all of them on exit."""
    open_one = opener or open_utf8
    with contextlib.ExitStack() as stack:
        yield [stack.enter_context(open_one(path)) for path in paths]
```

</details>

### Exercise 6 — `validate_records` and `except*`

**`validate_records(records)`** checks every field of every record and
collects **all** problems instead of stopping at the first:

| Field | Rule | Error |
| --- | --- | --- |
| Missing field | `name`, `age`, `email` required | `KeyError(field_name)` |
| `name` | Non-blank `str` | `ValueError` (non-empty string) |
| `age` | `int`, not `bool`, 0–150 | `ValueError` (integer 0–150) |
| `email` | `str` containing `@` | `ValueError` (must contain `@`) |

The exact messages are `"name must be a non-empty string"`,
`"age must be an integer between 0 and 150"` and `"email must contain '@'"`.
Check the fields in the order name, age, email. Add the note
`f"record {index}"` (0-based) to each error. If there are errors, raise
`ExceptionGroup("invalid records", errors)`; otherwise return the same
`records` list.

**`summarize_validation(records)`** calls it and handles the group with
**`except*`**: `except* KeyError` builds `"missing"` entries
`f"{note}: {field_name}"`, and `except* ValueError` builds `"invalid"` entries
`f"{note}: {message}"`. Return `{"missing": [...], "invalid": [...]}` (empty
lists when everything is valid).

The sample data:

```python
sample_signups = [
    {"name": "Asha", "age": 31, "email": "asha@example.com"},
    {"name": "  ", "age": 200, "email": "ravi@example.com"},
    {"name": "Meena", "email": "meena.example.com"},
    {"name": "John", "age": True, "email": "john@example.com"},
]
valid_signups = sample_signups[:1]
```

| Check | Expected |
| --- | --- |
| valid returns the same list | `True` (identity) |
| group of every problem | 5 leaves, first note `record 1`, 1 `KeyError` |
| summary | 1 missing, 4 invalid (below) |
| summary of valid records | both lists empty |
| empty input | `[]` |

The expected summary for `sample_signups`:

```python
{
    "missing": ["record 2: age"],
    "invalid": [
        "record 1: name must be a non-empty string",
        "record 1: age must be an integer between 0 and 150",
        "record 2: email must contain '@'",
        "record 3: age must be an integer between 0 and 150",
    ],
}
```

**Hints.** `True` is an `int` (Unit 1.3), so exclude `bool` explicitly. A
`KeyError`'s field name is `error.args[0]`, not `str(error)` (which adds
quotes, 1.14.4). Initialise the summary dict before the `try`, because the
`except*` blocks cannot `return`.

<details><summary>Solution</summary>

```python
REQUIRED_SIGNUP_FIELDS = ("name", "age", "email")


def record_errors(record: dict[str, Any]) -> list[Exception]:
    """Every problem with one record, in field order."""
    errors: list[Exception] = []
    for field_name in REQUIRED_SIGNUP_FIELDS:
        if field_name not in record:
            errors.append(KeyError(field_name))
            continue
        value = record[field_name]
        if field_name == "name" and not (
            isinstance(value, str) and value.strip()
        ):
            errors.append(ValueError("name must be a non-empty string"))
        elif field_name == "age" and not (
            isinstance(value, int)
            and not isinstance(value, bool)
            and 0 <= value <= 150
        ):
            errors.append(
                ValueError("age must be an integer between 0 and 150")
            )
        elif field_name == "email" and not (
            isinstance(value, str) and "@" in value
        ):
            errors.append(ValueError("email must contain '@'"))
    return errors


def validate_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return records unchanged, or raise an ExceptionGroup of problems."""
    all_errors: list[Exception] = []
    for index, record in enumerate(records):
        for error in record_errors(record):
            error.add_note(f"record {index}")
            all_errors.append(error)
    if all_errors:
        raise ExceptionGroup("invalid records", all_errors)
    return records


def summarize_validation(
    records: list[dict[str, Any]],
) -> dict[str, list[str]]:
    """Handle the ExceptionGroup with except* and summarize it."""
    summary: dict[str, list[str]] = {"missing": [], "invalid": []}
    try:
        validate_records(records)
    except* KeyError as missing_group:
        summary["missing"] = [
            f"{e.__notes__[0]}: {e.args[0]}" for e in missing_group.exceptions
        ]
    except* ValueError as invalid_group:
        summary["invalid"] = [
            f"{e.__notes__[0]}: {e}" for e in invalid_group.exceptions
        ]
    return summary
```

</details>

With the reference solutions in place, every check passes. The output for
Exercise 6, for example:

```text
PASS  valid returns the same list
PASS  group of every problem
PASS  summary
PASS  summary of valid records
PASS  empty input
5/5 checks passed
```

## Recap

| Concept | Takeaway | JavaScript equivalent |
| --- | --- | --- |
| Hierarchy | Catch `Exception`; exit signals are not errors | `Error` subclasses |
| Matching | `except C` if `C` in `__mro__`; first wins | `instanceof` in `catch` |
| `else` / `finally` | `else` if no error; `finally` always | `finally` |
| 3.14 changes | `except A, B:`; `return` in `finally` warns | — |
| `as error` | Deleted after the clause | Block-scoped `catch (e)` |
| Chaining | `from` → `__cause__`; implicit `__context__` | `{ cause }` option |
| Exception objects | `args`, `__traceback__`, `add_note` | `err.stack` |
| Custom hierarchy | One `AppError`; subclasses carry status codes | `extends Error` |
| Exception groups | `ExceptionGroup`, `except*`, `split` | `AggregateError` |
| EAFP vs LBYL | `try` is free since 3.11; raising is not | — |
| Logging | `logger.exception` in `except`; never swallow | `console.error(err)` |
| `with` | `__enter__` / `__exit__`; truthy suppresses | `using`, `try/finally` |
| `contextlib` | `@contextmanager` + `finally`, `ExitStack` | — |
| `assert` / `warnings` | Asserts vanish under `-O`; warnings filterable | `console.assert` / `warn` |
| Bytecode | Exception table; `LOAD_SPECIAL`, `WITH_EXCEPT_START` | — |

## Further reading

- [Tutorial: errors and exceptions](https://docs.python.org/3/tutorial/errors.html)
- [Built-in exceptions](https://docs.python.org/3/library/exceptions.html)
- [The `try` statement](https://docs.python.org/3/reference/compound_stmts.html#the-try-statement)
- [`traceback`](https://docs.python.org/3/library/traceback.html)
- [`logging`](https://docs.python.org/3/library/logging.html) and the
  [Logging HOWTO](https://docs.python.org/3/howto/logging.html)
- [The `with` statement](https://docs.python.org/3/reference/compound_stmts.html#the-with-statement)
- [Context manager types](https://docs.python.org/3/library/stdtypes.html#typecontextmanager)
- [`contextlib`](https://docs.python.org/3/library/contextlib.html)
- [`warnings`](https://docs.python.org/3/library/warnings.html)
- [The `assert` statement](https://docs.python.org/3/reference/simple_stmts.html#the-assert-statement)
- [`dis`](https://docs.python.org/3/library/dis.html)
- [PEP 343 — The `with` statement](https://peps.python.org/pep-0343/)
- [PEP 3134 — Exception chaining](https://peps.python.org/pep-3134/)
- [PEP 654 — Exception groups and `except*`](https://peps.python.org/pep-0654/)
- [PEP 678 — Enriching exceptions with notes](https://peps.python.org/pep-0678/)
- [PEP 758 — `except` without parentheses](https://peps.python.org/pep-0758/)
- [PEP 765 — Disallow `return`/`break`/`continue` that exit `finally`](https://peps.python.org/pep-0765/)

[← Previous](unit-1-13-iterators-generators-and-itertools.md) · [Index](README.md) · [Next →](project-log-analyzer.md)
