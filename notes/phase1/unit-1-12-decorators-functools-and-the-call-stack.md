# Unit 1.12 — Decorators, functools and the Call Stack

[← Previous](unit-1-11-scope-namespaces-and-closures.md) · [Index](README.md) · [Next →](unit-1-13-iterators-generators-and-itertools.md)

Decorators are the point where Python's "functions are objects" and "closures
remember their environment" (Units 1.10 and 1.11) turn into an everyday tool:
logging, retries, caching, permission checks and web routes are all written as
decorators. This unit takes decorators apart, then covers the two standard
library modules that live next to them (`functools` and `operator`), and finishes
by looking at what a function call really is in CPython: a frame object on a
call stack, which you can inspect, walk, overflow and introspect.

## What you will learn

- Why `@decorator` is exactly `f = decorator(f)`, run once at definition time
  (which usually means import time), and how stacked decorators are ordered.
- How to write a correct wrapper with `*args, **kwargs`, keep metadata with
  `functools.wraps`, and reach the original through `__wrapped__`.
- How decorator factories (`@retry(times=3)`) and optional-argument decorators
  (`@timer` and `@timer(unit="ms")`) are built.
- Where a decorator can keep state, and why a class-based decorator breaks on
  methods until it gets a `__get__`.
- Class decorators, and a gallery of production-style decorators, ending with
  how `@app.get("/users")` works in a web framework.
- The key tools of `functools` (`partial`, `cache`, `lru_cache`,
  `cached_property`, `reduce`, `singledispatch`, `total_ordering`,
  `update_wrapper`) and of `operator` (`itemgetter`, `attrgetter`,
  `methodcaller`, operator functions).
- Frame objects, `sys._getframe`, `inspect.stack`, `traceback.extract_stack`,
  the recursion limit, and explicit-stack rewrites.
- `inspect.signature`, `bind` and `apply_defaults`, and a tiny dependency
  injector that shows the core idea behind FastAPI.

## JavaScript → Python bridge

JavaScript developers already know the idea behind decorators: a higher-order
function that takes a function and returns a new one. Python gives that pattern
a dedicated syntax and a set of standard helpers. The table lists the closest
equivalents and the difference that usually surprises people.

| JavaScript | Python | The difference that bites |
| --- | --- | --- |
| `withLogging(fn)` | `@log_calls` | `@` applies it once, at definition time |
| TC39 / TS decorators | Python decorators | Work on any function or class, no build step |
| Lost `fn.name` | `functools.wraps` | Without it, name, doc and signature are lost |
| `fn.bind(null, x)` | `functools.partial(fn, x)` | `partial` can also fix keyword arguments |
| lodash `memoize` | `cache`, `lru_cache` | Built in, with stats; args must be hashable |
| `obj => obj.price` | `attrgetter("price")` | Faster, picklable, dotted paths |
| `new Error().stack` | `traceback.extract_stack()` | Structured records, real frames with locals |
| `app.get("/users", h)` | `@app.get("/users")` | The decorator registers and returns the function |

> **Note:** TypeScript's `experimentalDecorators` and the TC39 decorators
> proposal only decorate classes and class members, and they need a compiler or
> a recent engine. Python decorators have been part of the language since 2.4
> (functions, PEP 318) and 3.0 (classes, PEP 3129), and they decorate plain
> module-level functions too.

### Setup used by the examples

Every example in this unit runs after this setup block. `raised_error_name`
calls a zero-argument function (a *thunk*) and returns the name of the exception
it raised, which keeps error demos to one line.

```python
import contextlib
import datetime as dt
import functools
import gc
import inspect
import io
import operator
import re
import sys
import time
import timeit
import traceback
import types
import warnings
import weakref
from collections.abc import Callable
from decimal import Decimal
from typing import Any, NamedTuple


def raised_error_name(thunk: Callable[[], object]) -> str:
    """Call thunk and return the name of the exception it raised."""
    try:
        thunk()
    except Exception as error:
        return type(error).__name__
    return "no error"


print(f"{sys.version_info[:2]=}")
```

```text
sys.version_info[:2]=(3, 15)
```

## 1.12.1 Decorator mechanics

A **decorator** is any callable that takes a function and returns something to
bind in its place. Usually that "something" is a new function that wraps the
original, but it can be the original function itself (registration decorators
do this), an instance of a class, or anything else. The `@` line is pure syntax
sugar. These two spellings compile to the same thing:

```python
@announce
def greet(): ...


# is exactly the same as

def greet(): ...


greet = announce(greet)
```

The important consequence is timing. The decorator runs **once, when the `def`
statement runs**, not when the function is called. A `def` is an executable
statement in Python (Unit 1.10): it builds a function object and binds it to a
name. With a decorator, CPython builds the function object, calls the decorator
with it, and binds the *return value* of the decorator to the name. In the
bytecode, that is a `CALL` of the decorator on the freshly made function,
followed by `STORE_NAME`; the undecorated function is never bound to `greet` at
all.

The next example writes `announce`, which prints when it is applied and returns
the function unchanged, then shows that applying it by hand does exactly the
same thing.

```python
def announce(func: Callable[..., Any]) -> Callable[..., Any]:
    """Print when applied; return the function unchanged."""
    print(f"  announce applied to {func.__name__}")
    return func


print("before the def")


@announce
def greet(name: str) -> str:
    """Return a greeting."""
    return f"namaste, {name}"


print("after the def, before any call")
print(f"{greet('asha')=}")


def greet_manually(name: str) -> str:
    """Same function, decorated by hand."""
    return f"namaste, {name}"


greet_manually = announce(greet_manually)
```

```text
before the def
  announce applied to greet
after the def, before any call
greet('asha')='namaste, asha'
  announce applied to greet_manually
```

### Import-time execution

Because decorators run when the `def` runs, and a module's top-level `def`
statements run when the module is first imported, decorators execute **at import
time**. Frameworks depend on this. Importing a module full of `@app.get(...)`
handlers is what registers the routes; nobody has to call the handlers first.
The next example runs a small module from a string (`exec` stands in for
`import`) and shows the registration happening before any handler is called.

```python
handler_module_source = """
registered_handlers = []

def handler(func):
    registered_handlers.append(func.__name__)
    print(f"  registering {func.__name__} at import time")
    return func

@handler
def list_orders():
    return []

@handler
def create_order():
    return {}
"""
module_namespace: dict[str, Any] = {}
exec(handler_module_source, module_namespace)
registered = module_namespace["registered_handlers"]
print(f"{registered=}  (no handler was called)")
```

```text
  registering list_orders at import time
  registering create_order at import time
registered=['list_orders', 'create_order']  (no handler was called)
```

> **Warning:** Import-time execution cuts both ways. A decorator that does slow
> work (opens a database connection, reads a config file, makes a network call)
> makes every `import` of the module slow, and a decorator that raises makes the
> import fail. Keep decorator bodies cheap and push the real work into the
> wrapper, which only runs when the function is called.

### Stacking order

You can put several decorators on one function. The one **closest to the `def`
is applied first** (bottom-up), so the top decorator produces the outermost
wrapper. At call time the wrappers therefore **run top-down**: the outermost
wrapper starts first and calls inward.

```python
@bold
@italic
def headline(): ...


# is the same as

headline = bold(italic(headline))
```

The sequence of events for one call looks like this:

```text
definition time (bottom-up):  italic(headline) -> then bold(that)

call time (top-down):
  Caller -> bold wrapper -> italic wrapper -> headline()
  Caller <- "<b><i>Sale</i></b>" <- "<i>Sale</i>" <- "Sale"
```

The example prints at both moments so you can see the two orders.

```python
def bold(func: Callable[[], str]) -> Callable[[], str]:
    """Wrap the result in <b> tags."""
    print("  applying bold")

    def bold_wrapper() -> str:
        print("  bold wrapper runs")
        return f"<b>{func()}</b>"

    return bold_wrapper


def italic(func: Callable[[], str]) -> Callable[[], str]:
    """Wrap the result in <i> tags."""
    print("  applying italic")

    def italic_wrapper() -> str:
        print("  italic wrapper runs")
        return f"<i>{func()}</i>"

    return italic_wrapper


@bold
@italic
def headline() -> str:
    return "Sale"


print(f"{headline()=}")
```

```text
  applying italic
  applying bold
  bold wrapper runs
  italic wrapper runs
headline()='<b><i>Sale</i></b>'
```

This is the same as nesting function calls in JavaScript,
`bold(italic(headline))`: the inner call happens first, and the result is
wrapped by the outer one. Order matters whenever decorators interact. For
example, a `@timer` placed above `@retry` measures all attempts together, while
placed below it measures each attempt separately.

### Predict the output

```python
@italic
@bold
def banner():
    return "Diwali offers"


print(banner())
```

<details><summary>Answer</summary>

First, at definition time, `applying bold` then `applying italic` (bottom-up,
`bold` is closest to the `def`). Then the call prints `italic wrapper runs`,
`bold wrapper runs` (top-down) and the result `<i><b>Diwali offers</b></i>`.
Swapping the decorators swaps the nesting.

```python
@italic
@bold
def banner() -> str:
    return "Diwali offers"


print(banner())
```

```text
  applying bold
  applying italic
  italic wrapper runs
  bold wrapper runs
<i><b>Diwali offers</b></i>
```

</details>

### Key points

| Idea | Takeaway |
| --- | --- |
| `@d` above `def f` | Means `f = d(f)` |
| When it runs | Once, when the `def` runs (import time) |
| Stacking | Applied bottom-up, wrappers run top-down |
| Return value | Whatever `d` returns is bound to the name |

## 1.12.2 Writing decorators

The standard decorator has a fixed shape. An outer function receives `func`. It
defines an inner **wrapper** that accepts any arguments (`*args, **kwargs`),
does something before and/or after calling `func(*args, **kwargs)`, and
**returns the result**. The outer function returns the wrapper. The wrapper is a
closure (Unit 1.11): it keeps a reference to `func` in a cell, so every call can
reach the original. It is the forwarding wrapper from Unit 1.10.4
(`call_logged`), packaged so it is applied once at definition time.

```text
log_calls(func)                  <- runs once, at definition time
 └─ def wrapper(*args, **kwargs) <- runs on every call
       before work
       result = func(*args, **kwargs)
       after work
       return result
 └─ return wrapper
```

The first attempt below works, but it has a flaw: the decorated function now
reports the *wrapper's* name, docstring and signature, because the name
`add_gst` is bound to the wrapper function object.

```python
def log_calls_naive(func: Callable[..., Any]) -> Callable[..., Any]:
    """Log every call (without functools.wraps)."""

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        print(f"  calling {func.__name__}{args}")
        return func(*args, **kwargs)

    return wrapper


@log_calls_naive
def add_gst(amount: float, rate_percent: float = 18) -> float:
    """Return amount with GST added."""
    return round(amount * (100 + rate_percent) / 100, 2)


print(f"{add_gst(500)=}")
print(f"{add_gst.__name__=}, {add_gst.__doc__=}")
print(f"signature: {inspect.signature(add_gst)}")
```

```text
  calling add_gst(500,)
add_gst(500)=590.0
add_gst.__name__='wrapper', add_gst.__doc__=None
signature: (*args: Any, **kwargs: Any) -> Any
```

Losing this metadata is more than cosmetic. Tracebacks, loggers, `help()`,
documentation generators, test runners and frameworks such as FastAPI all read
`__name__`, `__doc__` and the signature. A FastAPI handler whose signature has
become `(*args, **kwargs)` no longer tells the framework which query parameters
it accepts.

### `functools.wraps` and `__wrapped__`

`functools.wraps(func)` fixes that. It is itself a decorator (a factory, in
fact: it takes `func` and returns a decorator) that you apply to the wrapper. It
copies the attributes listed in `functools.WRAPPER_ASSIGNMENTS`, merges the
wrapped function's `__dict__` into the wrapper's, and sets
`wrapper.__wrapped__ = func`. `inspect.signature` follows `__wrapped__`, so
tools see the real signature. Always use it.

```python
def log_calls_wrapped(func: Callable[..., Any]) -> Callable[..., Any]:
    """Log every call, keeping the wrapped function's metadata."""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        print(f"  calling {func.__name__}{args}")
        return func(*args, **kwargs)

    return wrapper


@log_calls_wrapped
def add_gst(amount: float, rate_percent: float = 18) -> float:
    """Return amount with GST added."""
    return round(amount * (100 + rate_percent) / 100, 2)


print(f"{add_gst.__name__=}")
print(f"{add_gst.__doc__=}")
print(f"signature: {inspect.signature(add_gst)}")
print(", ".join(functools.WRAPPER_ASSIGNMENTS))
```

```text
add_gst.__name__='add_gst'
add_gst.__doc__='Return amount with GST added.'
signature: (amount: float, rate_percent: float = 18) -> float
__module__, __name__, __qualname__, __doc__, __annotate__, __type_params__
```

> **Note:** *Changed in 3.14:* `WRAPPER_ASSIGNMENTS` lists `__annotate__`
> instead of `__annotations__`, because annotations are now evaluated lazily
> (PEP 649 and PEP 749). The effect for you is the same: annotations survive the
> wrapping.

`__wrapped__` gives access to the original, undecorated function, for example
to test it without the logging. `inspect.unwrap` follows a whole chain of
`__wrapped__` links, which matters when several decorators are stacked.

```python
original_add_gst = add_gst.__wrapped__
print(f"{original_add_gst(1000, 5)=}  (no log line: wrapper bypassed)")
print(f"{inspect.unwrap(add_gst) is original_add_gst=}")
```

```text
original_add_gst(1000, 5)=1050.0  (no log line: wrapper bypassed)
inspect.unwrap(add_gst) is original_add_gst=True
```

### Returning results

The most common decorator bug is forgetting `return` in the wrapper. Every
decorated function then returns `None`, and Python raises no error, because a
function without a `return` statement returning `None` is perfectly legal.

```python
def log_calls_broken(func: Callable[..., Any]) -> Callable[..., Any]:
    """Bug: the wrapper calls func but does not return its result."""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        func(*args, **kwargs)

    return wrapper


@log_calls_broken
def order_total(prices: list[int]) -> int:
    """Return the sum of prices."""
    return sum(prices)


print(f"{order_total([249, 640])=}  (the result is lost)")
```

```text
order_total([249, 640])=None  (the result is lost)
```

> **Warning:** A related bug is forgetting to `return wrapper` from the
> decorator itself. Then the decorated name is bound to `None`, and the first
> call fails with `TypeError: 'NoneType' object is not callable`.

### Typed decorators

*New in 3.12:* the type-parameter syntax of PEP 695, combined with the
`ParamSpec` of PEP 612, lets a type checker keep the wrapped function's exact
signature. The decorator is generic over a parameter specification `**P` and a
return type `R`. Type checking is covered in Phase 4; at run time the behaviour
is identical to the untyped version.

```python
def traced[**P, R](func: Callable[P, R]) -> Callable[P, R]:
    """Log calls; type checkers keep func's parameters and return type."""

    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        result = func(*args, **kwargs)
        print(f"  {func.__name__} -> {result!r}")
        return result

    return wrapper


@traced
def delivery_days(pincode: str, express: bool = False) -> int:
    """Return the delivery estimate in days."""
    return 1 if express else 4


delivery_days("560001", express=True)
print(f"{traced.__type_params__=}")
```

```text
  delivery_days -> 1
traced.__type_params__=(P, R)
```

### Key points

| Idea | Takeaway |
| --- | --- |
| Wrapper signature | `*args, **kwargs` forwards any call |
| `functools.wraps` | Copies name, doc, annotations; sets `__wrapped__` |
| `__wrapped__` | The original function; `inspect.unwrap` follows it |
| Missing `return` | Silent `None` results |
| `[**P, R]` | Typed decorators keep the signature for checkers |

## 1.12.3 Decorator factories

To configure a decorator, as in `@retry(times=3)`, you add one more level: a
**factory** that takes the options and returns the decorator. The expression
after the `@` is evaluated first (that is the factory call), and its result is
then applied to the function. *Changed in 3.9:* PEP 614 allows any expression
after `@`, so `@routes["users"].get` or `@factory(options)(more)` are all legal.

| Level | Called with | Returns |
| --- | --- | --- |
| `retry(times=3)` | the options | `decorator` |
| `decorator(func)` | the function, once | `wrapper` |
| `wrapper(*args)` | call arguments, every call | the result |

`@retry(times=3)` therefore means `fetch = retry(times=3)(fetch)`. The three
nested functions form two layers of closures: `decorator` closes over `times`,
and `wrapper` closes over both `times` and `func`. This first version retries on
any exception and re-raises the last one when the attempts run out. The gallery
in 1.12.6 adds backoff and an exception filter.

```python
type Decorator = Callable[[Callable[..., Any]], Callable[..., Any]]


def retry_simple(times: int = 3) -> Decorator:
    """Return a decorator that calls func up to times times."""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            for attempt in range(1, times + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as error:
                    print(f"  attempt {attempt} failed: {error}")
                    if attempt == times:
                        raise

        return wrapper

    return decorator
```

> **Note:** The `type Decorator = …` line is a type alias (*New in 3.12*,
> PEP 695). It only shortens the return annotation so the line fits; the
> notebook spells the full `Callable[...]` type out.

The next example decorates a flaky function that fails twice before succeeding,
then one that always fails. The bare `raise` inside `except` re-raises the
exception currently being handled, with its original traceback.

```python
flaky_call_count = 0


@retry_simple(times=3)
def fetch_exchange_rate() -> float:
    """Fail on the first two calls, then succeed."""
    global flaky_call_count
    flaky_call_count += 1
    if flaky_call_count < 3:
        raise ConnectionError(f"timeout #{flaky_call_count}")
    return 83.25


@retry_simple(times=2)
def fetch_from_dead_server() -> float:
    """Always fails."""
    raise ConnectionError("connection refused")


print(f"{fetch_exchange_rate()=}")
print(f"dead server: {raised_error_name(fetch_from_dead_server)}")
```

```text
  attempt 1 failed: timeout #1
  attempt 2 failed: timeout #2
fetch_exchange_rate()=83.25
  attempt 1 failed: connection refused
  attempt 2 failed: connection refused
dead server: ConnectionError
```

> **Warning:** Writing `@retry_simple` without the parentheses is a classic
> mistake. Python then calls `retry_simple(fetch_exchange_rate)`, so `times` is
> the function, and the name ends up bound to `decorator` instead of a wrapper.
> The optional-argument pattern below makes both spellings work.

### Optional-argument decorators

Sometimes both `@timer` and `@timer(unit="s")` should work. The trick is to make
the function parameter **positional-only and optional**, and every option
**keyword-only**:

- `@timer`: Python calls `timer(func)`, so `func` is given, and `timer`
  decorates it directly.
- `@timer(unit="s")`: the call has no function, so `func is None`, and `timer`
  returns the decorator, which Python then applies to the function.

Because the options are keyword-only, there is no way to confuse an option with
the function. `timer` below is a **shared helper**: the gallery (1.12.6) and the
Phase 1 project reuse it. `report` lets the caller send the message somewhere
other than `print`, such as a logger or a list.

```python
TIME_UNITS = {"s": 1.0, "ms": 1_000.0, "us": 1_000_000.0}


def timer(
    func: Callable[..., Any] | None = None,
    /,
    *,
    unit: str = "ms",
    report: Callable[[str], object] = print,
) -> Callable[..., Any]:
    """Report how long each call takes. Use as @timer or @timer(unit="s")."""
    if unit not in TIME_UNITS:
        raise ValueError(
            f"unit must be one of {sorted(TIME_UNITS)}, got {unit!r}"
        )

    def decorator(target: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(target)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            started = time.perf_counter()
            try:
                return target(*args, **kwargs)
            finally:
                elapsed = (time.perf_counter() - started) * TIME_UNITS[unit]
                report(f"{target.__qualname__} took {elapsed:.3f} {unit}")

        return wrapper

    return decorator if func is None else decorator(func)
```

Both forms in action. The `try` / `finally` in the wrapper means the time is
reported even when the function raises. The unit check happens in `timer`
itself, so a bad unit fails at definition time, not on the first call.

```python
@timer
def build_report(row_count: int) -> int:
    """Sum some squares."""
    return sum(row * row for row in range(row_count))


@timer(unit="us")
def lookup_price(sku: str) -> int:
    """A fast dictionary lookup."""
    return {"TEA-500G": 249}.get(sku, 0)


print(f"{build_report(200_000)=}")
print(f"{lookup_price('TEA-500G')=}")
print(f"{build_report.__name__=}")
print(f"unknown unit: {raised_error_name(lambda: timer(unit='h'))}")
```

```text
build_report took 5.701 ms
build_report(200_000)=2666646666700000
lookup_price took 1.045 us
lookup_price('TEA-500G')=249
build_report.__name__='build_report'
unknown unit: ValueError
```

> **Note:** The timings come from one run on one machine. They vary on every
> run.

### Key points

| Idea | Takeaway |
| --- | --- |
| Factory | Options → decorator → wrapper (three levels) |
| `@retry(times=3)` | Means `f = retry(times=3)(f)` |
| Optional arguments | `func=None, /, *, options` |
| Validate options early | Raise in the factory, at definition time |

## 1.12.4 Stateful and class-based decorators

A decorator can remember things between calls: how often a function ran, its
last result, a cache, a rate-limit window. Because the decorator runs once and
the wrapper runs many times, the state must live somewhere that outlives a
single call. There are three natural places.

| Where | How | Good for |
| --- | --- | --- |
| Function attribute | `wrapper.last_result = …` | State callers can read |
| Closure variable | `nonlocal` in the wrapper | Private state |
| Instance attribute | A class with `__call__` | Rich state, helper methods |

### Function attributes

The wrapper is a function object, and function objects have a `__dict__`, so
they can carry arbitrary attributes (Unit 1.10.1). Callers read them directly
from the decorated name. This is the Python version of attaching a property to
a function in JavaScript (`fn.lastResult = …`).

```python
def remember_last_result(func: Callable[..., Any]) -> Callable[..., Any]:
    """Store the most recent result on the wrapper as last_result."""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        wrapper.last_result = func(*args, **kwargs)
        return wrapper.last_result

    wrapper.last_result = None
    return wrapper


@remember_last_result
def shipping_fee(weight_kg: float) -> int:
    """Return the fee in rupees."""
    return 49 if weight_kg <= 1 else 99


shipping_fee(0.5)
shipping_fee(3.0)
print(f"{shipping_fee.last_result=}")
```

```text
shipping_fee.last_result=99
```

Inside the wrapper, the name `wrapper` is a free variable that refers to the
wrapper itself (it is defined in the enclosing scope), so the function can
update its own attribute.

### Closure variables

`run_once` keeps a private flag and a cached result in the enclosing scope and
updates them with `nonlocal` (Unit 1.11). The first call runs the function;
later calls return the same result without running it again. This is useful for
expensive one-time setup. `co_freevars` lists the cell variables the wrapper
closes over.

```python
def run_once(func: Callable[..., Any]) -> Callable[..., Any]:
    """Call func the first time only; afterwards return the first result."""
    has_run = False
    first_result: Any = None

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        nonlocal has_run, first_result
        if not has_run:
            first_result = func(*args, **kwargs)
            has_run = True
        return first_result

    return wrapper


@run_once
def load_settings() -> dict[str, str]:
    """Pretend to read a settings file."""
    print("  reading settings (only once)")
    return {"currency": "INR"}


print(load_settings(), load_settings())
print(f"{load_settings.__code__.co_freevars=}")
```

```text
  reading settings (only once)
{'currency': 'INR'} {'currency': 'INR'}
load_settings.__code__.co_freevars=('first_result', 'func', 'has_run')
```

> **Note:** `load_settings.__code__` is the *wrapper's* code object.
> `functools.wraps` copies names and docs, not code, so the free variables you
> see are those of the wrapper.

### Class-based decorators

A class whose instances are callable (it defines `__call__`) can also be a
decorator: `CallHistory(func)` builds an instance, and that instance replaces
the function. The state lives in ordinary instance attributes, and the class can
offer helper methods. `functools.update_wrapper(self, func)` copies the
metadata onto the instance, exactly as `wraps` does for a wrapper function.

```python
class CallHistory:
    """Decorator that records the arguments of every call."""

    def __init__(self, func: Callable[..., Any]) -> None:
        functools.update_wrapper(self, func)
        self.func = func
        self.history: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.history.append((args, kwargs))
        return self.func(*args, **kwargs)


@CallHistory
def apply_coupon(total: int, code: str) -> int:
    """Take 10% off with any coupon."""
    return total * 9 // 10


apply_coupon(1000, "DIWALI")
apply_coupon(500, code="NEWUSER")
print(f"{apply_coupon.history=}")
print(f"{type(apply_coupon).__name__=}, {apply_coupon.__name__=}")
```

```text
apply_coupon.history=[((1000, 'DIWALI'), {}), ((500,), {'code': 'NEWUSER'})]
type(apply_coupon).__name__='CallHistory', apply_coupon.__name__='apply_coupon'
```

### The method trap

Put the same class-based decorator on a **method** and calls break. To see why,
you need one piece of Phase 2 early: how `self` gets bound. Plain functions
have a `__get__` method, which makes them *descriptors*. When you write
`cart.add`, Python finds `add` in the class `__dict__`, sees it has `__get__`,
and calls `add.__get__(cart, Cart)`. That returns a *bound method* which
inserts `cart` as the first argument. A `CallHistory` instance has no
`__get__`, so `cart.add` returns the plain instance and `self` is never passed.

```text
cart.add  ->  Cart.__dict__["add"]
              function?          -> has __get__ -> bound method (self = cart)
              CallHistory object -> no __get__  -> returned as is, no self
```

```python
class Cart:
    """A cart whose add method uses the class-based decorator."""

    def __init__(self) -> None:
        self.items: list[str] = []

    @CallHistory
    def add(self, sku: str) -> int:
        self.items.append(sku)
        return len(self.items)


shopping_cart = Cart()
try:
    shopping_cart.add("TEA-500G")
except TypeError as error:
    print(f"{type(error).__name__}: {error}")
print(f"{hasattr(Cart.__dict__['add'], '__get__')=}")
```

```text
TypeError: Cart.add() missing 1 required positional argument: 'sku'
hasattr(Cart.__dict__['add'], '__get__')=False
```

The error message is confusing on purpose: `"TEA-500G"` arrived as `self`, so
Python reports `sku` as missing. In JavaScript the analogous bug is a method
that loses `this` when it is passed around unbound.

### The `__get__` fix

Give the decorator class a `__get__` that returns a bound method,
`types.MethodType(self, instance)`, when it is accessed through an instance.
`MethodType` packages a callable and an object so that calling it prepends the
object to the arguments, which is exactly what a function's own `__get__` does.
Plain function decorators never have this problem: their wrapper is a function,
which already has `__get__`.

```python
class MethodSafeCallHistory(CallHistory):
    """CallHistory that also works on methods."""

    def __get__(self, instance: object, owner: type | None = None) -> Any:
        if instance is None:  # accessed on the class: the decorator itself
            return self
        return types.MethodType(self, instance)


class SafeCart:
    """Same cart, method-safe decorator."""

    def __init__(self) -> None:
        self.items: list[str] = []

    @MethodSafeCallHistory
    def add(self, sku: str) -> int:
        self.items.append(sku)
        return len(self.items)


safe_cart = SafeCart()
print(f"{safe_cart.add('TEA-500G')=}, {safe_cart.add('RICE-5KG')=}")
print(f"{len(SafeCart.add.history)=}")
```

```text
safe_cart.add('TEA-500G')=1, safe_cart.add('RICE-5KG')=2
len(SafeCart.add.history)=2
```

> **Note:** The history lives on the one decorator instance, which is shared by
> every `SafeCart`. That is usually what you want for call statistics, but it
> means the state is per *class*, not per object.

### Key points

| Idea | Takeaway |
| --- | --- |
| Function attribute | Public state on the wrapper |
| Closure + `nonlocal` | Private state |
| Class with `__call__` | Rich state; use `update_wrapper` |
| Method trap | Instances lack `__get__`, so no `self` |
| Fix | `__get__` returning `types.MethodType(self, instance)` |

## 1.12.5 Decorating methods and classes

### Methods

A function decorator works on methods unchanged. The decorator runs while the
class body executes, and it returns a plain function, which is then stored in
the class `__dict__`. Because it is a function, it becomes a bound method on
attribute access, and `self` simply arrives as the first positional argument.
A decorator that needs `self` can name it explicitly, as `audit` does.

```python
def audit(func: Callable[..., Any]) -> Callable[..., Any]:
    """Log the class name and method name of each call."""

    @functools.wraps(func)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        print(f"  audit: {type(self).__name__}.{func.__name__}{args}")
        return func(self, *args, **kwargs)

    return wrapper


class Inventory:
    """Stock levels keyed by SKU."""

    def __init__(self) -> None:
        self.stock: dict[str, int] = {}

    @audit
    def receive(self, sku: str, quantity: int) -> int:
        self.stock[sku] = self.stock.get(sku, 0) + quantity
        return self.stock[sku]


warehouse = Inventory()
print(f"{warehouse.receive('TEA-500G', 40)=}")
```

```text
  audit: Inventory.receive('TEA-500G', 40)
warehouse.receive('TEA-500G', 40)=40
```

### Class decorators for registration

`@decorator` above a `class` statement means `Cls = decorator(Cls)`. The
decorator receives the **finished** class object, after the class body has run,
so it can read or modify its attributes. The most common use is
**registration**: collect classes in a registry so they can be looked up by
name later (serializers, plugins, ORM models, command handlers, payment
providers). The factory form takes the registry key. Unlike a metaclass
(Phase 2), a class decorator is not inherited: subclasses are not registered
unless they are decorated too.

```python
PAYMENT_PROVIDERS: dict[str, type] = {}


def payment_provider(name: str) -> Callable[[type], type]:
    """Class decorator factory: register the class under name."""

    def decorator(cls: type) -> type:
        PAYMENT_PROVIDERS[name] = cls
        cls.provider_name = name
        return cls  # the class itself, unchanged apart from the attribute

    return decorator


@payment_provider("upi")
class UpiPayment:
    def charge(self, amount: int) -> str:
        return f"UPI collect request for ₹{amount}"


@payment_provider("card")
class CardPayment:
    def charge(self, amount: int) -> str:
        return f"card charged ₹{amount}"


print(f"{sorted(PAYMENT_PROVIDERS)=}")
print(PAYMENT_PROVIDERS["upi"]().charge(499), f"{UpiPayment.provider_name=}")
```

```text
sorted(PAYMENT_PROVIDERS)=['card', 'upi']
UPI collect request for ₹499 UpiPayment.provider_name='upi'
```

### Class decorators that add behaviour

A class decorator can also **add behaviour**, for example a `__repr__` built
from the instance attributes. `@dataclass` (Phase 2) is the standard library's
big example of a class decorator that generates methods (`__init__`,
`__repr__`, `__eq__` and more) from the class body.

```python
def add_repr(cls: type) -> type:
    """Give cls a __repr__ listing its instance attributes."""

    def __repr__(self: Any) -> str:
        fields = ", ".join(
            f"{name}={value!r}" for name, value in vars(self).items()
        )
        return f"{type(self).__name__}({fields})"

    cls.__repr__ = __repr__
    return cls


@add_repr
class Customer:
    def __init__(self, name: str, city: str) -> None:
        self.name = name
        self.city = city


print(Customer("Asha", "Pune"))
```

```text
Customer(name='Asha', city='Pune')
```

> **Warning:** A class decorator must return the class (or a replacement). If it
> forgets the `return cls`, the class name is bound to `None`.

### Key points

| Idea | Takeaway |
| --- | --- |
| Function decorator on a method | Works as is; `self` is `args[0]` |
| `@d` above `class C` | Means `C = d(C)`, after the body runs |
| Registration | Store the class in a dict, return it unchanged |
| Adding methods | Assign onto the class; `@dataclass` is the big example |

## 1.12.6 Real-world decorator gallery

This section collects decorators you will meet (or write) in real code. Each is
short, but each follows the rules from the earlier sections: `functools.wraps`,
return the result, never swallow exceptions, and put configuration in a
factory.

| Decorator | Kind | What it does |
| --- | --- | --- |
| `timer` | optional-arg | Report each call's duration |
| `retry` | factory | Backoff, only listed exceptions |
| `log_calls` | plain | Log arguments and result or error |
| `require_role` | factory | Refuse unless the user has a role |
| `validate_types` | factory | Check argument types given explicitly |
| `register` | factory | Add the function to a registry |
| `deprecated` | factory | Warn on every call |
| `memoize` | plain | Cache results by arguments |
| `App.get` | method factory | Register a route (how FastAPI works) |

### `timer`

Reused from 1.12.3. Here `report` collects the messages in a list instead of
printing, as a logger would.

```python
timing_log: list[str] = []


@timer(unit="ms", report=timing_log.append)
def render_invoice(line_count: int) -> str:
    """Build a long invoice string."""
    return "\n".join(f"line {number}" for number in range(line_count))


render_invoice(10_000)
render_invoice(50_000)
first_name = timing_log[0].split(" took ")[0]
print(f"{len(timing_log)=}, first entry starts with: {first_name!r}")
```

```text
len(timing_log)=2, first entry starts with: 'render_invoice'
```

### `retry` with backoff and an exception filter

This is the production version of 1.12.3's `retry_simple`, and a **shared
helper** the Phase 1 project reuses. It adds three things:

- Only exceptions listed in `exceptions` are retried. Anything else, such as a
  `ValueError` that signals a bug, propagates at once. Retrying a bug only
  makes it slower.
- Between attempts it sleeps `first_delay * backoff ** (attempt - 1)` seconds
  (exponential backoff), so a struggling service gets time to recover.
- `sleep` is a parameter, so tests can record the delays instead of waiting.
  This is dependency injection in its simplest form.

`except exceptions:` works because `except` accepts a tuple of exception
classes.

```python
def retry(
    times: int = 3,
    *,
    exceptions: tuple[type[Exception], ...] = (Exception,),
    first_delay: float = 0.1,
    backoff: float = 2.0,
    sleep: Callable[[float], object] = time.sleep,
) -> Decorator:
    """Retry on listed exceptions, sleeping first_delay * backoff**n."""
    if times < 1:
        raise ValueError("times must be at least 1")

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            for attempt in range(1, times + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions:
                    if attempt == times:
                        raise
                    sleep(first_delay * backoff ** (attempt - 1))
            raise AssertionError("unreachable")

        return wrapper

    return decorator
```

The next example records the delays (`sleep=recorded_delays.append`): 0.1 s,
0.2 s and 0.4 s before the fourth attempt succeeds. A `ValueError` is not in
the filter, so it is raised after a single attempt and no delay is recorded.

```python
recorded_delays: list[float] = []
gateway_attempts: list[int] = []


@retry(
    times=5,
    exceptions=(ConnectionError, TimeoutError),
    sleep=recorded_delays.append,
)
def call_payment_gateway(amount: int) -> str:
    """Time out three times, then succeed."""
    gateway_attempts.append(amount)
    if len(gateway_attempts) <= 3:
        raise TimeoutError("gateway timeout")
    return f"paid ₹{amount}"


@retry(times=5, exceptions=(ConnectionError,), sleep=recorded_delays.append)
def parse_amount(text: str) -> int:
    """A bug, not a network problem: must not be retried."""
    return int(text)


print(f"{call_payment_gateway(499)=}, {len(gateway_attempts)=}")
print(f"{recorded_delays=}")
parse_error = raised_error_name(lambda: parse_amount("abc"))
print(f"parse_amount('abc'): {parse_error}, {recorded_delays=}")
```

```text
call_payment_gateway(499)='paid ₹499', len(gateway_attempts)=4
recorded_delays=[0.1, 0.2, 0.4]
parse_amount('abc'): ValueError, recorded_delays=[0.1, 0.2, 0.4]
```

### `log_calls`

Logs the arguments and the result, or the exception. When the function raises,
the wrapper logs and then re-raises with a bare `raise`: a logging decorator
must never swallow errors.

```python
def log_calls(func: Callable[..., Any]) -> Callable[..., Any]:
    """Print each call with its arguments, then its result or exception."""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        arguments = [repr(arg) for arg in args] + [
            f"{key}={value!r}" for key, value in kwargs.items()
        ]
        call_text = f"{func.__name__}({', '.join(arguments)})"
        try:
            result = func(*args, **kwargs)
        except Exception as error:
            print(f"  {call_text} raised {type(error).__name__}: {error}")
            raise
        print(f"  {call_text} -> {result!r}")
        return result

    return wrapper


@log_calls
def divide_bill(total: int, people: int) -> float:
    return total / people


divide_bill(1200, people=4)
print(f"by zero: {raised_error_name(lambda: divide_bill(1200, 0))}")
```

```text
  divide_bill(1200, people=4) -> 300.0
  divide_bill(1200, 0) raised ZeroDivisionError: division by zero
by zero: ZeroDivisionError
```

### `require_role`

An authorization guard. The decorated function takes a `user` keyword
argument, and the wrapper raises `PermissionError` unless the user has the
required role. Note how the wrapper declares `user` as a keyword-only parameter
of its own, so it can inspect it before forwarding. Phase 6 does the same job
with FastAPI dependencies.

```python
def require_role(role: str) -> Decorator:
    """Refuse the call unless kwargs['user'] has role in its roles."""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapper(*args: Any, user: dict[str, Any], **kwargs: Any) -> Any:
            if role not in user.get("roles", ()):
                raise PermissionError(f"{user['name']} needs role {role!r}")
            return func(*args, user=user, **kwargs)

        return wrapper

    return decorator


@require_role("admin")
def refund_order(order_id: int, *, user: dict[str, Any]) -> str:
    return f"order {order_id} refunded by {user['name']}"


print(refund_order(1042, user={"name": "Meena", "roles": ["admin"]}))
try:
    refund_order(1042, user={"name": "Ravi", "roles": ["support"]})
except PermissionError as error:
    print(f"{type(error).__name__}: {error}")
```

```text
order 1042 refunded by Meena
PermissionError: Ravi needs role 'admin'
```

### `validate_types`

The expected types are passed to the factory **explicitly**, as in
`@validate_types(quantity=int)`. The signature is computed once, at decoration
time; on each call, `signature.bind(*args, **kwargs)` maps positional and
keyword arguments to parameter names, so both call styles are checked. (Lab
1.12 builds `validate_arguments`, which reads the types from the annotations
instead; section 1.12.11 covers `bind` in detail.)

```python
def validate_types(**expected_types: type) -> Decorator:
    """Raise TypeError when a named argument is not of its expected type."""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        signature = inspect.signature(func)

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            bound = signature.bind(*args, **kwargs)
            for name, expected_type in expected_types.items():
                value = bound.arguments.get(name)
                if name in bound.arguments and not isinstance(
                    value, expected_type
                ):
                    actual = type(value).__name__
                    raise TypeError(
                        f"{name} must be {expected_type.__name__}, "
                        f"got {actual}"
                    )
            return func(*args, **kwargs)

        return wrapper

    return decorator


@validate_types(sku=str, quantity=int)
def reserve_stock(sku: str, quantity: int) -> str:
    return f"reserved {quantity} x {sku}"


print(reserve_stock("TEA-500G", quantity=3))
bad_call = raised_error_name(lambda: reserve_stock("TEA-500G", "3"))
print(f"quantity '3': {bad_call}")
```

```text
reserved 3 x TEA-500G
quantity '3': TypeError
```

### `register`

A function registry. The decorator stores the function under a key and returns
it **unchanged**, so it can still be called directly and there is no wrapper
overhead. This is the plugin pattern: here, report exporters chosen by format
name at run time, the Python version of a JavaScript object map of handlers.

```python
EXPORTERS: dict[str, Callable[[list[dict[str, Any]]], str]] = {}


def register(format_name: str) -> Decorator:
    """Store the decorated function in EXPORTERS under format_name."""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        EXPORTERS[format_name] = func
        return func

    return decorator


@register("csv")
def export_csv(rows: list[dict[str, Any]]) -> str:
    return "\n".join(
        ",".join(str(value) for value in row.values()) for row in rows
    )


@register("tsv")
def export_tsv(rows: list[dict[str, Any]]) -> str:
    return "\n".join(
        "\t".join(str(value) for value in row.values()) for row in rows
    )


sales_rows = [{"sku": "TEA-500G", "units": 3}, {"sku": "RICE-5KG", "units": 1}]
print(f"{sorted(EXPORTERS)=}")
print(EXPORTERS["csv"](sales_rows))
```

```text
sorted(EXPORTERS)=['csv', 'tsv']
TEA-500G,3
RICE-5KG,1
```

### `deprecated`

Warn callers that a function is going away. `warnings.warn(message,
DeprecationWarning, stacklevel=2)` attributes the warning to the **caller's**
line rather than to the wrapper (level 1 is the wrapper, level 2 its caller).
The example captures the warnings with `warnings.catch_warnings(record=True)`
so they can be printed; `simplefilter("always")` makes sure none is
suppressed, since `DeprecationWarning` is hidden by default outside `__main__`
and test runners.

```python
def deprecated(reason: str) -> Decorator:
    """Emit a DeprecationWarning with reason on every call."""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            message = f"{func.__name__} is deprecated: {reason}"
            warnings.warn(message, DeprecationWarning, stacklevel=2)
            return func(*args, **kwargs)

        return wrapper

    return decorator


@deprecated("use calculate_tax() instead")
def compute_vat(amount: int) -> float:
    return amount * 0.18


with warnings.catch_warnings(record=True) as caught_warnings:
    warnings.simplefilter("always")
    compute_vat(100)
for caught in caught_warnings:
    print(f"{caught.category.__name__}: {caught.message}")
```

```text
DeprecationWarning: compute_vat is deprecated: use calculate_tax() instead
```

The standard library now has its own: `warnings.deprecated` (*New in 3.13*,
PEP 702) warns at run time **and** tells type checkers to flag every use. It
also sets `__deprecated__` on the function.

```python
if sys.version_info >= (3, 13):

    @warnings.deprecated("use calculate_tax() instead")
    def compute_sales_tax(amount: int) -> float:
        return amount * 0.18

    with warnings.catch_warnings(record=True) as caught_warnings:
        warnings.simplefilter("always")
        compute_sales_tax(100)
    print([caught.category.__name__ for caught in caught_warnings])
    print(f"{compute_sales_tax.__deprecated__=}")
else:
    print("warnings.deprecated needs Python 3.13; skipped")
```

```text
['DeprecationWarning']
compute_sales_tax.__deprecated__='use calculate_tax() instead'
```

### `memoize`

Cache results in a dict keyed by the arguments. Repeated calls with the same
arguments skip the work. Because the recursive calls inside `ways_to_pay` look
up the *global* name `ways_to_pay`, which is now the wrapper, they hit the
cache too: that is what turns an exponential algorithm into a fast one. This is
what `functools.cache` does (1.12.7, with a C implementation and statistics);
writing it once shows there is no magic.

```python
def memoize(func: Callable[..., Any]) -> Callable[..., Any]:
    """Cache results by positional arguments (which must be hashable)."""
    results_by_args: dict[tuple[Any, ...], Any] = {}

    @functools.wraps(func)
    def wrapper(*args: Any) -> Any:
        if args not in results_by_args:
            results_by_args[args] = func(*args)
        return results_by_args[args]

    wrapper.cache = results_by_args
    return wrapper


@memoize
def ways_to_pay(amount: int, coins: tuple[int, ...] = (1, 2, 5, 10)) -> int:
    """Count the ways to make amount from coins (exponential, uncached)."""
    if amount == 0:
        return 1
    if amount < 0 or not coins:
        return 0
    return ways_to_pay(amount - coins[0], coins) + ways_to_pay(
        amount, coins[1:]
    )


print(f"{ways_to_pay(200)=}, {len(ways_to_pay.cache)=} cached results")
```

```text
ways_to_pay(200)=15211, len(ways_to_pay.cache)=1018 cached results
```

> **Note:** This `memoize` only supports positional arguments, and the
> default `coins` is not part of the key when it is omitted. `ways_to_pay(200)`
> and `ways_to_pay(200, (1, 2, 5, 10))` are cached separately. `functools.cache`
> handles keyword arguments too, but it has the same "different spelling,
> different key" behaviour.

### How `@app.get("/users")` works

A web framework's route decorator is a **registration decorator factory
implemented as a method**. `app.get(path)` returns a decorator; the decorator
stores `(method, path) → handler` in the app's route table and returns the
handler unchanged. Dispatching a request is then a dictionary lookup. In
Express you pass the handler as an argument (`app.get("/users", handler)`); in
Python the decorator does the same registration, and the handler keeps its own
name. This version matches exact paths only; Lab 1.12 adds path parameters
like `/users/{user_id}`.

```python
type Handler = Callable[[], Any]


class App:
    """A tiny web app: a route table filled by decorators."""

    def __init__(self) -> None:
        self.routes: dict[tuple[str, str], Handler] = {}

    def route(self, method: str, path: str) -> Callable[[Handler], Handler]:
        def decorator(handler: Handler) -> Handler:
            self.routes[(method, path)] = handler
            return handler

        return decorator

    def get(self, path: str) -> Callable[[Handler], Handler]:
        return self.route("GET", path)

    def handle(self, method: str, path: str) -> tuple[int, Any]:
        handler = self.routes.get((method, path))
        if handler is None:
            return (404, {"detail": "Not Found"})
        return (200, handler())
```

Register two handlers and dispatch a few requests. The routes exist as soon as
the `def` statements have run.

```python
app = App()


@app.get("/users")
def list_users() -> list[str]:
    return ["asha", "ravi"]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


print(f"{list(app.routes)=}")
print(app.handle("GET", "/users"), app.handle("GET", "/health"))
print(app.handle("GET", "/admin"))
print(f"{list_users()=}  (still callable directly)")
```

```text
list(app.routes)=[('GET', '/users'), ('GET', '/health')]
(200, ['asha', 'ravi']) (200, {'status': 'ok'})
(404, {'detail': 'Not Found'})
list_users()=['asha', 'ravi']  (still callable directly)
```

```text
@app.get("/users")          step 1: app.get("/users") -> decorator
def list_users(): ...       step 2: decorator(list_users)
                                    routes[("GET", "/users")] = list_users
                                    return list_users (unchanged)
request GET /users          step 3: routes[("GET", "/users")]() -> response
```

### Key points

| Idea | Takeaway |
| --- | --- |
| Retry filters | Retry transient errors only; bugs propagate |
| Injected `sleep` | Makes timing code testable |
| Logging | Log, then re-raise; never swallow |
| Registration | Store and return unchanged |
| `stacklevel=2` | Points a warning at the caller |
| `@app.get(path)` | A method that is a registration factory |

## 1.12.7 `functools`

`functools` is the standard library's toolbox for working with functions as
values: building new functions from old ones, caching them, dispatching on
types and copying metadata. Most of it is implemented in C (`_functools`), so
these tools are faster than hand-written equivalents.

### Method reference: partial application

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `partial` | Freeze some arguments | `partial(int, base=2)("101")` | `5` |
| `Placeholder` | Keep a positional slot open | `partial(divmod, Placeholder, 7)(50)` | `(7, 1)` |
| `partialmethod` | `partial` for class bodies | `partialmethod(set_status, "shipped")` | method |

### Method reference: caching

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `cache` | Unbounded memoization | `fibonacci(90)` | `2880067194370816120` |
| `lru_cache` | Bounded, evicts least recent | `@lru_cache(maxsize=2)` | max 2 entries |
| `.cache_info()` | Hits, misses, sizes | `exchange_rate.cache_info().hits` | `1` |
| `.cache_clear()` | Empty the cache | `f.cache_clear()` | `None` |
| `cached_property` | Compute attribute once | `weekly_report.total` | `2630` |

### Method reference: other tools

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `reduce` | Fold into one value | `reduce(operator.add, [1, 2, 3], 0)` | `6` |
| `singledispatch` | Choose by first arg type | `format_amount(125000)` | `'₹125,000'` |
| `.register` | Add a type's version | `@format_amount.register` | registered |
| `total_ordering` | Fill in `<=`, `>`, `>=` | `Version("3.15.1") >= Version("3.9.0")` | `True` |
| `update_wrapper` | Copy metadata onto a wrapper | `update_wrapper(wrapper, func)` | `wrapper` |
| `wraps` | `update_wrapper` as a decorator | `@wraps(func)` | metadata kept |

JavaScript has `bind` and `Array.prototype.reduce` built in, and leaves the
rest to libraries such as lodash. Python ships all of them.

### `partial`

`functools.partial(func, *args, **kwargs)` returns a callable with some
arguments fixed. Calling it with more arguments appends them to the frozen
positional ones and merges the keywords (later keywords win). Unlike
JavaScript's `bind`, it does not fix a `this`, and it can freeze **keyword**
arguments, which is often the more readable choice. It keeps `.func`, `.args`
and `.keywords` for introspection, and it can be pickled.

```python
def price_with_tax(
    amount: float, rate_percent: float, *, round_to: int = 2
) -> float:
    """Return amount plus tax."""
    return round(amount * (100 + rate_percent) / 100, round_to)


with_gst = functools.partial(price_with_tax, rate_percent=18)
whole_rupees = functools.partial(price_with_tax, round_to=0)
print(f"{with_gst(499)=}, {whole_rupees(499, 5)=}")
print(f"{with_gst.func.__name__=}")
print(f"{with_gst.args=}, {with_gst.keywords=}")
```

```text
with_gst(499)=588.82, whole_rupees(499, 5)=524.0
with_gst.func.__name__='price_with_tax'
with_gst.args=(), with_gst.keywords={'rate_percent': 18}
```

> **Warning:** A frozen keyword argument can still be overridden, but a frozen
> keyword that is followed by a positional argument for the same parameter
> fails. `with_gst(499, 5)` raises `TypeError` (multiple values for
> `rate_percent`), because 5 is passed positionally into the slot that the
> keyword already fills.

*New in 3.14:* `functools.Placeholder` reserves a positional slot, so you can
fix a **later** positional argument and leave an earlier one open. Before 3.14
this needed a `lambda`.

```python
if sys.version_info >= (3, 14):
    boxes_of_seven = functools.partial(divmod, functools.Placeholder, 7)
    print(f"{boxes_of_seven(50)=}  (full boxes, leftover items)")
else:
    print("functools.Placeholder needs Python 3.14; skipped")
```

```text
boxes_of_seven(50)=(7, 1)  (full boxes, leftover items)
```

### `partialmethod`

`partial` objects are not descriptors (they have no `__get__`, the same issue
as the method trap in 1.12.4), so a `partial` stored in a class body does not
receive `self`. `partialmethod` is the descriptor version: on attribute access
it binds `self` first and then applies the frozen arguments.

```python
class Order:
    """An order whose status helpers are partial methods."""

    def __init__(self) -> None:
        self.status = "new"

    def set_status(self, status: str) -> str:
        self.status = status
        return status

    mark_shipped = functools.partialmethod(set_status, "shipped")
    mark_cancelled = functools.partialmethod(set_status, "cancelled")


festival_order = Order()
print(f"{festival_order.mark_shipped()=}, {festival_order.status=}")
```

```text
festival_order.mark_shipped()='shipped', festival_order.status='shipped'
```

### `cache`

`@functools.cache` (*New in 3.9*) is an unbounded memoizer, the same as
`lru_cache(maxsize=None)`. With no size limit it does not need to track usage
order, so it is a plain dict lookup in C: the fastest option when the set of
distinct arguments is small or bounded. The recursive calls go through the
cached name, exactly as with `memoize` in 1.12.6, so `fibonacci(90)` needs only
91 real computations.

```python
@functools.cache
def fibonacci(position: int) -> int:
    """Return the position-th Fibonacci number (exponential uncached)."""
    if position < 2:
        return position
    return fibonacci(position - 1) + fibonacci(position - 2)


print(f"{fibonacci(90)=}")
print(f"{fibonacci.cache_info()=}")
```

```text
fibonacci(90)=2880067194370816120
fibonacci.cache_info()=CacheInfo(hits=88, misses=91, maxsize=None, currsize=91)
```

### `lru_cache`, `cache_info` and `cache_clear`

`@functools.lru_cache(maxsize=N)` keeps at most `N` results and evicts the
**least recently used** one when it is full. Internally it is a dict plus a
doubly linked list that records usage order; a hit moves the entry to the
"most recent" end. `cache_info()` reports hits, misses, the limit and the
current size; `cache_clear()` empties the cache and resets the statistics.
Trace the example: `USD` and `EUR` miss, the second `USD` hits, `GBP` evicts
`EUR` (the least recently used), so the last `EUR` misses again.

```python
@functools.lru_cache(maxsize=2)
def exchange_rate(currency: str) -> float:
    """Pretend to call a rate service."""
    print(f"  fetching {currency}")
    return {"USD": 83.2, "EUR": 90.1, "GBP": 105.4}[currency]


for currency in ["USD", "EUR", "USD", "GBP", "EUR"]:
    exchange_rate(currency)
print(f"{exchange_rate.cache_info()=}")
exchange_rate.cache_clear()
print(f"after cache_clear: {exchange_rate.cache_info()}")
```

```text
  fetching USD
  fetching EUR
  fetching GBP
  fetching EUR
exchange_rate.cache_info()=CacheInfo(hits=1, misses=4, maxsize=2, currsize=2)
after cache_clear: CacheInfo(hits=0, misses=0, maxsize=2, currsize=0)
```

### Hashable arguments

The arguments become a dict key, so they must be **hashable** (Unit 1.7): a
list argument raises `TypeError`. Pass a tuple (or a `frozenset`) instead. This
is the same rule as for dict keys and set members.

```python
@functools.lru_cache(maxsize=128)
def basket_total(prices: tuple[int, ...]) -> int:
    """Sum a basket given as a tuple."""
    return sum(prices)


print(f"{basket_total((249, 640))=}")
try:
    basket_total([249, 640])
except TypeError as error:
    print(f"{type(error).__name__}: {error}")
```

```text
basket_total((249, 640))=889
TypeError: unhashable type: 'list'
```

> **Warning:** Cached results are shared. If a cached function returns a
> mutable object (a list or a dict) and a caller mutates it, every later caller
> gets the mutated object. Return tuples, frozensets or copies from cached
> functions.

### Memory risk on methods

`lru_cache` on a method caches `self` as part of every key. The cache belongs
to the function stored on the class, so it keeps **every instance alive** as
long as its entries remain, even after your code has dropped all references.
The `weakref` below shows the object surviving `del` until the cache is
cleared. Linters flag this pattern (ruff rule B019). Prefer `cached_property`,
a cache keyed by plain values outside the class, or a per-instance cache.

```python
class QuoteService:
    """Caches quotes with lru_cache on a method (risky)."""

    @functools.lru_cache(maxsize=None)  # noqa: B019, UP033 (the leak)
    def quote(self, sku: str) -> int:
        return len(sku) * 100


quote_service = QuoteService()
service_ref = weakref.ref(quote_service)
quote_service.quote("TEA-500G")
del quote_service
gc.collect()
print(f"after del: still alive = {service_ref() is not None}")
QuoteService.quote.cache_clear()
gc.collect()
print(f"after cache_clear: still alive = {service_ref() is not None}")
```

```text
after del: still alive = True
after cache_clear: still alive = False
```

### `cached_property`

`cached_property` computes an attribute on first access and stores the result
in the instance `__dict__` under the same name. Because it is a *non-data*
descriptor (Phase 2), the instance dict then wins on later lookups, so later
accesses are ordinary attribute reads with no function call at all. Delete the
attribute to force a recompute. It avoids the method-cache leak above because
the cached value lives on the instance and dies with it.

```python
class SalesReport:
    """A report whose total is expensive to compute."""

    def __init__(self, amounts: list[int]) -> None:
        self.amounts = amounts

    @functools.cached_property
    def total(self) -> int:
        print("  computing total")
        return sum(self.amounts)


weekly_report = SalesReport([1200, 450, 980])
print(weekly_report.total, weekly_report.total)
print(f"{'total' in vars(weekly_report)=}")
del weekly_report.total
print(weekly_report.total)
```

```text
  computing total
2630 2630
'total' in vars(weekly_report)=True
  computing total
2630
```

> **Note:** `cached_property` needs a writable instance `__dict__`, so it does
> not work on classes that use `__slots__` without a `__dict__` slot.

### `reduce`

`functools.reduce(func, iterable, initial)` folds a sequence into one value,
like JavaScript's `array.reduce` (with the argument order reversed: the
function comes first). Pass `initial` so empty input works; without it, an
empty iterable raises `TypeError`, just as `[].reduce(fn)` throws in
JavaScript. *Changed in 3.14:* `initial` may be given by keyword. Prefer `sum`,
`max`, `math.prod` or a loop when they fit: they read better.

```python
discount_steps = [0.9, 0.95, 0.98]  # three successive discounts
final_factor = functools.reduce(operator.mul, discount_steps, 1.0)
print(
    f"{final_factor=:.4f}, "
    f"price after discounts: {round(1000 * final_factor, 2)}"
)
print(f"{functools.reduce(operator.add, [], 0)=}  (initial covers empty)")
empty_error = raised_error_name(lambda: functools.reduce(operator.add, []))
print(f"empty without initial: {empty_error}")
```

```text
final_factor=0.8379, price after discounts: 837.9
functools.reduce(operator.add, [], 0)=0  (initial covers empty)
empty without initial: TypeError
```

### `singledispatch`

`singledispatch` turns a function into a **generic function**: the
implementation is chosen by the type of the **first** argument. Register
implementations with `@func.register`, which reads the type from the first
parameter's annotation (or takes it as an argument, `@func.register(int)`).
Dispatch walks the argument type's MRO, so a subclass uses the nearest
registered base class: `bool` is a subclass of `int`, so `True` is formatted by
the `int` version. JavaScript has no built-in equivalent; you would write a
`typeof` / `instanceof` chain.

```python
@functools.singledispatch
def format_amount(amount: object) -> str:
    """Fallback for unsupported types."""
    raise TypeError(f"cannot format {type(amount).__name__}")


@format_amount.register
def _(amount: int) -> str:
    return f"₹{amount:,}"


@format_amount.register
def _(amount: Decimal) -> str:
    return f"₹{amount:,.2f}"


print(
    format_amount(125000),
    format_amount(Decimal("999.5")),
    format_amount(True),
)
print(f"str: {raised_error_name(lambda: format_amount('12'))}")
registered_types = sorted(cls.__name__ for cls in format_amount.registry)
print(f"{registered_types=}")
```

```text
₹125,000 ₹999.50 ₹1
str: TypeError
registered_types=['Decimal', 'int', 'object']
```

> **Note:** For methods, use `functools.singledispatchmethod`, which dispatches
> on the first argument *after* `self`.

### `total_ordering`

Define `__eq__` and **one** of `__lt__`, `__le__`, `__gt__`, `__ge__`; the
class decorator `total_ordering` adds the other three, derived from the two you
wrote. (Phase 2 covers the comparison methods; dataclasses can do this with
`order=True`.) The derived methods are a little slower than hand-written ones,
because each one calls your methods.

```python
@functools.total_ordering
class Version:
    """A release version compared by its numbers."""

    def __init__(self, text: str) -> None:
        self.numbers = tuple(int(part) for part in text.split("."))

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Version) and self.numbers == other.numbers

    def __lt__(self, other: Version) -> bool:
        return self.numbers < other.numbers


print(f"{Version('3.15.1') >= Version('3.9.0')=}")
print(f"{Version('3.12.0') > Version('3.12.1')=}")
added = [
    name for name in ("__le__", "__gt__", "__ge__") if name in vars(Version)
]
print(f"added: {added}")
```

```text
Version('3.15.1') >= Version('3.9.0')=True
Version('3.12.0') > Version('3.12.1')=False
added: ['__le__', '__gt__', '__ge__']
```

The first line is a nice example of why comparing tuples of ints beats
comparing strings: `"3.15.1" >= "3.9.0"` is `False` as text, because `"1"` sorts
before `"9"`.

### `update_wrapper`

`functools.wraps(func)` is shorthand for
`functools.update_wrapper(wrapper, func)`, written as a decorator. Call
`update_wrapper` directly when the wrapper is not a `def` you can decorate: an
instance (as in `CallHistory`, 1.12.4) or a function built elsewhere.

```python
def apply_festival_discount(price: int) -> int:
    """Take 15% off for the festival."""
    return price * 85 // 100


def generic_wrapper(*args: Any, **kwargs: Any) -> Any:
    return apply_festival_discount(*args, **kwargs)


print(f"before: {generic_wrapper.__name__=}")
functools.update_wrapper(generic_wrapper, apply_festival_discount)
print(f"after:  {generic_wrapper.__name__=}")
print(f"after:  {generic_wrapper.__doc__=}")
print(f"{generic_wrapper.__wrapped__ is apply_festival_discount=}")
print(f"{generic_wrapper(1000)=}")
```

```text
before: generic_wrapper.__name__='generic_wrapper'
after:  generic_wrapper.__name__='apply_festival_discount'
after:  generic_wrapper.__doc__='Take 15% off for the festival.'
generic_wrapper.__wrapped__ is apply_festival_discount=True
generic_wrapper(1000)=850
```

### Key points

| Tool | Takeaway |
| --- | --- |
| `partial` | Freeze positional or keyword arguments |
| `cache` / `lru_cache` | Memoize; hashable args; stats and clear |
| Methods + `lru_cache` | Keeps instances alive; prefer `cached_property` |
| `reduce` | Always pass `initial` |
| `singledispatch` | Dispatch on the first argument's type, via MRO |
| `total_ordering` | `__eq__` + one comparison gives all six |
| `update_wrapper` | `wraps` for non-`def` wrappers |

## 1.12.8 `operator`

The `operator` module exposes Python's operators and lookups as functions,
ready to pass as `key=`, to `map` and `reduce`, or to store in dispatch tables
(Unit 1.10.6). Each function maps directly onto the same C slot the operator
uses, so `operator.add(a, b)` does exactly what `a + b` does, including calling
`__add__` and `__radd__` on your own classes.

### Method reference: getters and callers

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `itemgetter(key)` | `lambda row: row[key]` | `itemgetter("price")({"price": 249})` | `249` |
| `itemgetter(a, b)` | Several items as a tuple | `itemgetter(0, 2)("abc")` | `('a', 'c')` |
| `attrgetter(name)` | `lambda obj: obj.name` | `attrgetter("real")(3 + 4j)` | `3.0` |
| `attrgetter("a.b")` | Follows dotted paths | `attrgetter("customer.name")(p)` | `'Ravi'` |
| `methodcaller(m, *a)` | `lambda obj: obj.m(*a)` | `methodcaller("strip", "-")("--tea--")` | `'tea'` |

### Method reference: operator functions

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `add` | `a + b` | `operator.add(249, 640)` | `889` |
| `sub` | `a - b` | `operator.sub(10, 3)` | `7` |
| `mul` | `a * b` | `operator.mul(3, 249)` | `747` |
| `truediv` | `a / b` | `operator.truediv(7, 2)` | `3.5` |
| `floordiv` | `a // b` | `operator.floordiv(7, 2)` | `3` |
| `mod` | `a % b` | `operator.mod(7, 2)` | `1` |
| `neg` | `-a` | `operator.neg(50)` | `-50` |

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `lt` | `a < b` | `operator.lt(162, 249)` | `True` |
| `eq` | `a == b` | `operator.eq(3, 3.0)` | `True` |
| `contains` | `b in a` | `operator.contains(["tea"], "tea")` | `True` |
| `truth` | `bool(a)` | `operator.truth([])` | `False` |
| `not_` | `not a` | `operator.not_(0)` | `True` |
| `getitem` | `a[b]` | `operator.getitem({"sku": "TEA"}, "sku")` | `'TEA'` |
| `call` | `f(*args)` (*New in 3.11*) | `operator.call(max, 3, 9, 4)` | `9` |

> **Note:** `operator.contains(a, b)` takes the container **first**, the
> reverse of how `b in a` reads.

### `itemgetter`

`itemgetter("price")` builds a function that subscripts its argument. With one
key it returns the item; with several it returns a tuple, which is handy for
picking fields or building a multi-level sort key.

```python
products = [
    {"sku": "TEA-500G", "price": 249, "rating": 4.5},
    {"sku": "RICE-5KG", "price": 640, "rating": 4.1},
    {"sku": "SOAP-3PK", "price": 162, "rating": 4.5},
]
by_price = sorted(products, key=operator.itemgetter("price"))
print([product["sku"] for product in by_price])
get_sku_and_price = operator.itemgetter("sku", "price")
print([get_sku_and_price(product) for product in products])
```

```text
['SOAP-3PK', 'TEA-500G', 'RICE-5KG']
[('TEA-500G', 249), ('RICE-5KG', 640), ('SOAP-3PK', 162)]
```

### `attrgetter` (with dotted paths)

`attrgetter("customer.city")` follows the dots, like `obj.customer.city`.
Several names give a tuple, which makes a multi-level sort key: here, by city
first and then by amount within a city.

```python
class Buyer(NamedTuple):
    name: str
    city: str


class Purchase(NamedTuple):
    order_id: int
    customer: Buyer
    amount: int


purchases = [
    Purchase(3, Buyer("Ravi", "Pune"), 640),
    Purchase(1, Buyer("Asha", "Delhi"), 249),
    Purchase(2, Buyer("Meena", "Pune"), 162),
]
by_city_then_amount = sorted(
    purchases, key=operator.attrgetter("customer.city", "amount")
)
print([purchase.order_id for purchase in by_city_then_amount])
print(f"{operator.attrgetter('customer.name')(purchases[0])=}")
```

```text
[1, 2, 3]
operator.attrgetter('customer.name')(purchases[0])='Ravi'
```

### `methodcaller`

`methodcaller(name, *args)` builds a function that calls `obj.name(*args)` on
whatever it receives. The method is looked up on each object at call time, so
it works across different types that share a method name.

```python
raw_codes = ["--tea--", "-rice-", "soap---"]
strip_dashes = operator.methodcaller("strip", "-")
print(list(map(strip_dashes, raw_codes)))
print(list(map(operator.methodcaller("upper"), raw_codes)))
```

```text
['tea', 'rice', 'soap']
['--TEA--', '-RICE-', 'SOAP---']
```

### Operator functions

Every operator has a function: arithmetic (`add`, `mul`, `truediv`, `neg`),
comparison (`lt`, `eq`), membership (`contains`), truth (`truth`, `not_`),
indexing (`getitem`) and calling (`call`, *New in 3.11*). The last line pairs
two lists with `map(..., strict=True)` (*New in 3.14*, Unit 1.9.4), which
raises if the lists have different lengths.

```python
print(f"{operator.add(249, 640)=}, {operator.mul(3, 249)=}")
print(f"{operator.neg(50)=}, {operator.lt(162, 249)=}")
print(f"{operator.contains(['tea', 'rice'], 'tea')=}")
print(f"{operator.truth([])=}, {operator.getitem({'sku': 'TEA'}, 'sku')=}")
print(f"{operator.call(max, 3, 9, 4)=}")
line_totals = list(map(operator.mul, [249, 640], [2, 1], strict=True))
print(f"{line_totals=}")
```

```text
operator.add(249, 640)=889, operator.mul(3, 249)=747
operator.neg(50)=-50, operator.lt(162, 249)=True
operator.contains(['tea', 'rice'], 'tea')=True
operator.truth([])=False, operator.getitem({'sku': 'TEA'}, 'sku')='TEA'
operator.call(max, 3, 9, 4)=9
line_totals=[498, 640]
```

### Speed vs `lambda`

`itemgetter` and `attrgetter` are implemented in C, so they are usually faster
than the equivalent `lambda` as a sort key: `sorted` calls the key once per
item, and calling a C function skips building a Python frame. They can also be
pickled, unlike a `lambda`, which matters when you send work to other processes
with `multiprocessing` (Phase 5).

```python
many_rows = [(index % 97, index) for index in range(50_000)]
lambda_seconds = min(
    timeit.repeat(
        lambda: sorted(many_rows, key=lambda row: row[0]),
        number=10,
        repeat=5,
    )
)
getter_seconds = min(
    timeit.repeat(
        lambda: sorted(many_rows, key=operator.itemgetter(0)),
        number=10,
        repeat=5,
    )
)
print(
    f"lambda key: {lambda_seconds * 1000:.1f} ms, "
    f"itemgetter: {getter_seconds * 1000:.1f} ms"
)
speed_up = lambda_seconds / getter_seconds
print(f"itemgetter speed-up: {speed_up:.2f}x  (varies by machine)")
```

```text
lambda key: 22.4 ms, itemgetter: 15.8 ms
itemgetter speed-up: 1.41x  (varies by machine)
```

> **Note:** These timings are from one run of the notebook. They vary by
> machine and Python version; the direction (getter faster) is what matters.

### Key points

| Tool | Takeaway |
| --- | --- |
| `itemgetter` | `row[key]` as a function; several keys give a tuple |
| `attrgetter` | `obj.attr`, with dotted paths |
| `methodcaller` | `obj.method(*args)` as a function |
| Operator functions | `+`, `<`, `in`, `[]` as callables |
| vs `lambda` | Usually faster and picklable |

## 1.12.9 Frames and the call stack

Every function call creates a **frame**: the running state of one call. A frame
holds the code being run, the local variables, the evaluation stack of the
bytecode interpreter, the current instruction, and a link to the caller's
frame. Following those links gives the **call stack**. Since 3.11, CPython
keeps these frames in a compact internal structure on a per-thread stack and
only creates a full Python **frame object** when something asks for one (a
traceback, a debugger, `sys._getframe`). That lazy creation is one reason
function calls got much cheaper in 3.11.

```text
call stack while checkout() runs  (newest on top)

  +-----------------------------+
  | checkout   cart_total=889   |  <- sys._getframe()
  +-----------------------------+
  | place_order                 |  <- its f_back
  +-----------------------------+
  | <module>                    |  <- f_back.f_back
  +-----------------------------+
  (frames of whatever started the program, then None)
```

### Method reference: frame attributes and stack tools

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `f_code` | The code object | `frame.f_code.co_name` | `'checkout'` |
| `f_locals` | Locals (write-through proxy) | `frame.f_locals["cart_total"]` | `889` |
| `f_back` | The caller's frame | `frame.f_back.f_code.co_name` | `'place_order'` |
| `f_lineno` | Line now executing | `frame.f_lineno` | `7` |
| `f_globals` | The module namespace | `frame.f_globals is globals()` | `True` |

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `sys._getframe()` | Current frame | `sys._getframe().f_code.co_name` | `'checkout'` |
| `sys._getframe(1)` | Caller's frame | `sys._getframe(1).f_code.co_name` | `'place_order'` |
| `inspect.stack()` | `FrameInfo` list, innermost first | `inspect.stack()[0].function` | `'checkout'` |
| `traceback.extract_stack()` | `FrameSummary` list, outermost first | `extract_stack()[-1].name` | `'checkout'` |

The `f_locals` attribute is a `FrameLocalsProxy` (*New in 3.13*, PEP 667).
`sys._getframe()` returns the current frame; the leading underscore marks it as
CPython specific, but it is widely used (logging uses it to find the caller).
`sys._getframe(1)` returns the caller's frame.

```python
def checkout(cart_total: int) -> None:
    """Inspect the current frame and its caller."""
    current_frame = sys._getframe()
    print(f"  {current_frame.f_code.co_name=}")
    print(f"  {sorted(current_frame.f_locals)=}")
    print(f"  {current_frame.f_locals['cart_total']=}")
    print(f"  {current_frame.f_lineno=} (line inside this block)")
    print(f"  {current_frame.f_back.f_code.co_name=}")
    print(f"  {type(current_frame.f_locals).__name__=}")
    print(f"  {current_frame.f_globals is globals()=}")


def place_order() -> None:
    """Caller of checkout."""
    checkout(cart_total=889)


place_order()
```

```text
  current_frame.f_code.co_name='checkout'
  sorted(current_frame.f_locals)=['cart_total', 'current_frame']
  current_frame.f_locals['cart_total']=889
  current_frame.f_lineno=7 (line inside this block)
  current_frame.f_back.f_code.co_name='place_order'
  type(current_frame.f_locals).__name__='FrameLocalsProxy'
  current_frame.f_globals is globals()=True
```

### `f_locals` is write-through

Since 3.13 (PEP 667), `frame.f_locals` inside a function is a **write-through
proxy**: assigning through it changes the real local variable. Contrast
`locals()`, which returns a snapshot (Unit 1.11.1). Debuggers rely on this
when you change a variable at a breakpoint. Before 3.13 the behaviour was
inconsistent, and writes were often silently lost.

```python
def adjust_through_frame() -> int:
    """Change a local through the frame's f_locals proxy."""
    discount_percent = 10
    sys._getframe().f_locals["discount_percent"] = 25
    return discount_percent


print(f"{adjust_through_frame()=}")
```

```text
adjust_through_frame()=25
```

### Walking the stack with `f_back`

Following `f_back` walks up the stack, from the newest frame toward the oldest.
The next example walks from three levels deep. The walk stops after four frames
because the frames below the top-level code belong to whatever ran it (Jupyter,
or the interpreter's startup code).

```python
def level_three() -> list[str]:
    """Walk up the stack through f_back."""
    names = []
    frame = sys._getframe()
    while frame is not None and len(names) < 4:
        names.append(frame.f_code.co_name)
        frame = frame.f_back
    return names


def level_two() -> list[str]:
    return level_three()


def level_one() -> list[str]:
    return level_two()


print(level_one())
```

```text
['level_three', 'level_two', 'level_one', '<module>']
```

> **Warning:** Holding a reference to a frame keeps all its local variables
> alive, and a frame stored in one of its own locals creates a reference cycle.
> Use frames briefly, or `del` them when done.

### `inspect.stack()`

`inspect.stack()` returns a list of `FrameInfo` records (frame, filename, line
number, function name, source lines) from the current frame outward. It is much
slower than `sys._getframe`, because it reads source lines from disk for every
frame. Pass `context=0` if you do not need the source.

```python
def who_called_me() -> list[str]:
    """Return function name and line of the innermost frames."""
    return [f"{info.function}:{info.lineno}" for info in inspect.stack()[:3]]


def handle_request() -> list[str]:
    return who_called_me()


print(handle_request())
print(f"{type(inspect.stack()[0]).__name__=}")
```

```text
['who_called_me:3', 'handle_request:7', '<module>:10']
type(inspect.stack()[0]).__name__='FrameInfo'
```

The line numbers count from the first line of the code block.

### `traceback.extract_stack()`

`traceback.extract_stack()` returns lightweight `FrameSummary` records
(filename, line number, name, source line), **outermost first**, without
keeping the frames alive. It is what you would log. A traceback printed after
an exception has the same shape, which is why Python tracebacks read "most
recent call last".

```python
def record_stack() -> list[str]:
    """Return the innermost three stack entries, outermost first."""
    innermost = traceback.extract_stack()[-3:]
    return [f"{summary.name}:{summary.line}" for summary in innermost]


def process_payment() -> list[str]:
    return record_stack()


for entry in process_payment():
    print(f"  {entry}")
```

```text
  <module>:for entry in process_payment():
  process_payment:return record_stack()
  record_stack:innermost = traceback.extract_stack()[-3:]
```

### JS bridge: execution contexts and the call stack

The JavaScript model you know maps one to one onto Python's. The big practical
difference is that Python gives you the stack as **live objects** you can
inspect and even modify, where JavaScript gives you a formatted string.

| JavaScript | Python |
| --- | --- |
| Execution context | Frame object |
| Call stack | Chain of frames via `f_back` |
| Lexical environment | `f_locals` (+ cells for closures) |
| Global execution context | `<module>` frame and `f_globals` |
| `new Error().stack` (string) | `traceback.extract_stack()` (records) |
| `RangeError: Maximum call stack…` | `RecursionError` (1.12.10) |

### Key points

| Idea | Takeaway |
| --- | --- |
| Frame | State of one call: code, locals, line, caller |
| `sys._getframe(n)` | Fast access to the current or nth caller frame |
| `f_locals` | Write-through proxy since 3.13 |
| `inspect.stack()` | Rich but slow (reads source) |
| `extract_stack()` | Light records, outermost first, for logging |

## 1.12.10 Recursion limits

Each Python-level call adds a frame. CPython limits the depth with a counter,
`sys.getrecursionlimit()` (default 1000), and raises `RecursionError` when the
limit is exceeded, instead of letting the process crash. In JavaScript the
limit is set by the engine's stack size (often around ten thousand frames) and
you get `RangeError: Maximum call stack size exceeded`; Python's limit is lower
on purpose, and you can read and change it.

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `sys.getrecursionlimit()` | Read the limit | `sys.getrecursionlimit()` | `1000` |
| `sys.setrecursionlimit(n)` | Change the limit | `sys.setrecursionlimit(6_000)` | `None` |
| `RecursionError` | Raised past the limit | `nesting_depth(5_000)` | raises |

```python
def nesting_depth(levels: int) -> int:
    """Recurse levels times."""
    return 0 if levels == 0 else 1 + nesting_depth(levels - 1)


print(f"{sys.getrecursionlimit()=}")
print(f"{nesting_depth(900)=}")
try:
    nesting_depth(5_000)
except RecursionError as error:
    print(f"{type(error).__name__}: {error}")
```

```text
sys.getrecursionlimit()=1000
nesting_depth(900)=900
RecursionError: maximum recursion depth exceeded
```

`RecursionError` is a subclass of `RuntimeError`, so it can be caught like any
other exception, and the interpreter stays usable afterwards.

### No tail-call optimization

Even when the recursive call is the very last thing a function does (a *tail
call*), CPython keeps every frame. Guido van Rossum rejected tail-call
optimization because it would make tracebacks incomplete, and he considered
complete tracebacks more important. (JavaScript's ES2015 specification requires
proper tail calls, but only Safari's engine implements them, so in practice the
two languages behave the same.) A tail-recursive loop over 5 000 items still
fails.

```python
def sum_tail_recursive(
    numbers: list[int], index: int = 0, running_total: int = 0
) -> int:
    """Tail-recursive sum: the recursive call is the last operation."""
    if index == len(numbers):
        return running_total
    return sum_tail_recursive(
        numbers, index + 1, running_total + numbers[index]
    )


print(f"{sum_tail_recursive(list(range(500)))=}")
long_list_error = raised_error_name(
    lambda: sum_tail_recursive(list(range(5_000)))
)
print(f"5 000 items: {long_list_error}")
```

```text
sum_tail_recursive(list(range(500)))=124750
5 000 items: RecursionError
```

### Raising the limit

`sys.setrecursionlimit(n)` raises the limit. It is a blunt tool. Since 3.11 a
call from Python code to a Python function no longer uses the C stack, but
calls that pass through C code (built-ins, many dunder methods, some library
code) still do, and a limit far above what the real stack can hold can crash
the interpreter instead of raising. Change it temporarily and restore it in a
`finally`.

```python
original_limit = sys.getrecursionlimit()
try:
    sys.setrecursionlimit(6_000)
    print(f"{nesting_depth(5_000)=} with limit {sys.getrecursionlimit()}")
finally:
    sys.setrecursionlimit(original_limit)
print(f"restored: {sys.getrecursionlimit()=}")
```

```text
nesting_depth(5_000)=5000 with limit 6000
restored: sys.getrecursionlimit()=1000
```

### Explicit-stack rewrites

The robust fix is to replace the call stack with a **list used as a stack**
(Unit 1.6.13): push the work still to do, then pop and process until the list
is empty. The list lives on the heap, so it can hold millions of entries. Any
recursive traversal can be rewritten this way; the order of visits may change
(here the children are processed last-in, first-out), which does not matter for
a sum.

The next example builds a category tree 10 000 levels deep (with a loop, not
recursion), where the recursive sum fails and the explicit-stack version
succeeds.

```python
def nested_total_recursive(node: int | list[Any]) -> int:
    """Sum all ints in a nested list, recursively."""
    if isinstance(node, int):
        return node
    return sum(nested_total_recursive(child) for child in node)


def nested_total_iterative(root: int | list[Any]) -> int:
    """Same result with an explicit stack: no recursion limit."""
    total, pending = 0, [root]
    while pending:
        node = pending.pop()
        if isinstance(node, int):
            total += node
        else:
            pending.extend(node)
    return total


deep_tree: list[Any] = [1]
for _ in range(10_000):
    deep_tree = [1, deep_tree]
recursive_error = raised_error_name(lambda: nested_total_recursive(deep_tree))
print(f"recursive: {recursive_error}")
print(f"{nested_total_iterative(deep_tree)=}")
```

```text
recursive: RecursionError
nested_total_iterative(deep_tree)=10001
```

```text
pending (a list used as a stack)

start:   [tree]
pop tree -> push its children:  [1, subtree]
pop subtree -> push children:   [1, 1, subtree2]
pop subtree2 ...                (one list grows, no frames are added)
```

### Key points

| Idea | Takeaway |
| --- | --- |
| Default limit | About 1000 Python frames |
| `RecursionError` | Raised, catchable, process survives |
| Tail calls | Never optimized in CPython |
| `setrecursionlimit` | Temporary, restore in `finally` |
| Deep data | Rewrite with an explicit list stack |

## 1.12.11 Introspecting callables

`inspect.signature(func)` returns a `Signature` object: an ordered mapping of
parameter names to `Parameter` objects, plus the return annotation. Each
`Parameter` has a `name`, a `kind` (positional-only, positional-or-keyword,
`*args`, keyword-only, `**kwargs`), a `default` and an `annotation`;
`Parameter.empty` marks a missing default or annotation. This is the structured
form of everything you wrote on the `def` line. JavaScript offers only
`fn.length` (the count of parameters before the first default) and the source
text from `fn.toString()`.

### Method reference: `inspect.signature`

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `signature(f)` | Build a `Signature` | `inspect.signature(sample)` | `(a, b=2, *, c)` |
| `.parameters` | Name → `Parameter` | `list(sig.parameters)` | `['a', 'b', 'c']` |
| `.return_annotation` | Return annotation | `signature(f2).return_annotation` | `<class 'str'>` |
| `Parameter.kind` | How it is passed | `params["c"].kind.name` | `'KEYWORD_ONLY'` |
| `Parameter.default` | Default value | `params["b"].default` | `2` |
| `Parameter.annotation` | Annotation | `params["a"].annotation` | `<class 'inspect._empty'>` |
| `Parameter.empty` | "Nothing given" marker | `params["a"].default is empty` | `True` |

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `.bind(*a, **kw)` | Map a call to names | `sig.bind(1, c=3).arguments` | `{'a': 1, 'c': 3}` |
| `.bind_partial` | Like `bind`, allows missing | `sig.bind_partial(1).arguments` | `{'a': 1}` |
| `.apply_defaults()` | Fill in defaults | `bound.arguments` afterwards | `{'a': 1, 'b': 2, 'c': 3}` |
| `.args` | Positional part | `bound.args` | `(1, 2)` |
| `.kwargs` | Keyword part | `bound.kwargs` | `{'c': 3}` |

The examples in these tables use `def sample(a, b=2, *, c): ...`,
`def f2(x: int) -> str: ...`, `sig = inspect.signature(sample)`,
`params = sig.parameters`, `empty = inspect.Parameter.empty`, and
`bound = sig.bind(1, c=3)`.

### `Signature` and `Parameter`

```python
def create_shipment(
    order_id: int,
    /,
    city: str,
    express: bool = False,
    *,
    insured_value: float = 0.0,
) -> str:
    """Create a shipment."""
    return f"{order_id} to {city}"


shipment_signature = inspect.signature(create_shipment)
print(shipment_signature)
empty = inspect.Parameter.empty
for parameter in shipment_signature.parameters.values():
    default = "—" if parameter.default is empty else repr(parameter.default)
    annotation_name = parameter.annotation.__name__
    print(
        f"  {parameter.name:14} {parameter.kind.name:22} "
        f"default={default:6} {annotation_name=}"
    )
print(f"{shipment_signature.return_annotation=}")
```

```text
(order_id: int, /, city: str, express: bool = False, *, insured_value: float
= 0.0) -> str
  order_id       POSITIONAL_ONLY        default=—      annotation_name='int'
  city           POSITIONAL_OR_KEYWORD  default=—      annotation_name='str'
  express        POSITIONAL_OR_KEYWORD  default=False  annotation_name='bool'
  insured_value  KEYWORD_ONLY           default=0.0    annotation_name='float'
shipment_signature.return_annotation=<class 'str'>
```

> **Note:** The first output line is one line when printed; it is wrapped here
> to fit the page.

### `bind` and `apply_defaults`

`bind` maps call arguments to parameter names **without calling** the
function, applying exactly the same rules as a real call, and raises
`TypeError` for a call that would be invalid. `apply_defaults` then fills in the
parameters that were not given. The resulting `BoundArguments` offers
`.arguments` (a dict by name) and `.args` / `.kwargs`, ready to pass on with
`func(*bound.args, **bound.kwargs)`. Frameworks use this to validate and
inspect calls before making them.

```python
bound_call = shipment_signature.bind(1042, "Pune", insured_value=5000.0)
print(f"{bound_call.arguments=}")
bound_call.apply_defaults()
print("after apply_defaults:")
print(bound_call.arguments)
print(f"{bound_call.args=}")
print(f"{bound_call.kwargs=}")
missing_city = raised_error_name(lambda: shipment_signature.bind(1042))
print(f"missing city: {missing_city}")
by_name_error = raised_error_name(
    lambda: shipment_signature.bind(order_id=1, city="Goa")
)
print(f"order_id by name: {by_name_error}  (positional-only)")
```

```text
bound_call.arguments={'order_id': 1042, 'city': 'Pune', 'insured_value': 5000.0}
after apply_defaults:
{'order_id': 1042, 'city': 'Pune', 'express': False, 'insured_value': 5000.0}
bound_call.args=(1042, 'Pune', False)
bound_call.kwargs={'insured_value': 5000.0}
missing city: TypeError
order_id by name: TypeError  (positional-only)
```

### A tiny dependency injector

FastAPI reads a handler's signature and supplies each parameter itself: path
and query values, the request body, a database session. The core idea fits in
one function. Look at each parameter's **annotation**, find a provider
registered for that type, call it, and pass the result in. Explicit arguments
win, and parameters with defaults may be left out.

```python
class Settings:
    """Application settings."""

    currency = "INR"


class Database:
    """A fake database connection."""

    def __init__(self, url: str) -> None:
        self.url = url

    def count_orders(self) -> int:
        return 42


def inject(
    func: Callable[..., Any],
    providers: dict[type, Callable[[], Any]],
    **explicit: Any,
) -> Any:
    """Call func, building arguments from explicit values or providers."""
    arguments: dict[str, Any] = {}
    for name, parameter in inspect.signature(func).parameters.items():
        if name in explicit:
            arguments[name] = explicit[name]
        elif parameter.annotation in providers:
            arguments[name] = providers[parameter.annotation]()
        elif parameter.default is inspect.Parameter.empty:
            raise TypeError(f"cannot provide parameter {name!r}")
    return func(**arguments)
```

The handler below only declares what it needs; `inject` supplies it. In a test
you register a different `Database` provider, and the handler code does not
change: that is the whole appeal of dependency injection.

```python
app_providers: dict[type, Callable[[], Any]] = {
    Settings: Settings,
    Database: lambda: Database("sqlite:///shop.db"),
}


def order_dashboard(
    db: Database, settings: Settings, title: str = "Orders"
) -> str:
    """A handler that declares its dependencies as annotated parameters."""
    return (
        f"{title}: {db.count_orders()} orders, "
        f"currency {settings.currency}, db={db.url}"
    )


print(inject(order_dashboard, app_providers))
print(inject(order_dashboard, app_providers, title="Today"))
test_providers = {
    **app_providers,
    Database: lambda: Database("sqlite:///:memory:"),
}
print(inject(order_dashboard, test_providers))
```

```text
Orders: 42 orders, currency INR, db=sqlite:///shop.db
Today: 42 orders, currency INR, db=sqlite:///shop.db
Orders: 42 orders, currency INR, db=sqlite:///:memory:
```

```text
inject(order_dashboard, providers)
  signature: (db: Database, settings: Settings, title: str = "Orders")
    db       -> annotation Database -> providers[Database]() -> Database(...)
    settings -> annotation Settings -> providers[Settings]() -> Settings()
    title    -> no provider, has default -> left out
  call: order_dashboard(db=..., settings=...)
```

### Key points

| Idea | Takeaway |
| --- | --- |
| `inspect.signature` | Parameters with kind, default, annotation |
| `Parameter.empty` | Marks "no default" / "no annotation" |
| `bind` | Validates a call without making it |
| `apply_defaults` | Fills missing parameters from defaults |
| Dependency injection | Annotation → provider → argument |

## Lab 1.12

Seven exercises that rebuild the unit's main tools from memory. In the
notebook, each exercise has a stub that raises `NotImplementedError` and a check
cell built on the shared `run_checks` helper, which prints `PASS` or `FAIL` for
every case and a final count. Until you implement a stub the checks print
`FAIL`; that is expected. Exercises 1 and 2 rebuild `timer` and `retry` with
extra hooks for testing; try to write them without scrolling back up.

Two helpers are used by the checks:

```python
def fake_clock(*readings: float) -> Callable[[], float]:
    """Return a clock that returns readings one by one."""
    reading_iterator = iter(readings)
    return lambda: next(reading_iterator)


def captured_stdout(thunk: Callable[[], object]) -> tuple[object, str]:
    """Run thunk and return (its result, what it printed)."""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = thunk()
    return result, buffer.getvalue()
```

`fake_clock(10.0, 10.25)` returns a function that returns `10.0` on its first
call and `10.25` on its second, so a timing test always measures exactly 0.25 s.
Injecting the clock is the same trick as injecting `sleep` into `retry`.

### Exercise 1 — `@timer` with optional arguments

Write
`timer(func=None, /, *, unit="ms", clock=time.perf_counter, report=print)`:

- it works both as `@timer` and as `@timer(unit="s", ...)`;
- `unit` is `"s"`, `"ms"` or `"us"`; anything else raises `ValueError`
  **when `timer(...)` is called**;
- each call reads `clock()` before and after, calls
  `report(f"{func.__name__} took {elapsed:.2f} {unit}")`, then returns the
  result;
- it keeps the function's metadata (`__name__`, `__wrapped__`).

| Check | Call | Expected |
| --- | --- | --- |
| Options form | `@timer(unit="ms", clock=fake_clock(10.0, 10.25), …)` | `300`, `["brew_chai took 250.00 ms"]` |
| Bare form | `timer(pack_order)()` | `"packed"`, prints `pack_order took N.NN ms` |
| Seconds | `timer(unit="s", clock=fake_clock(1.0, 3.5))(len)("ab")` | prints `len took 2.50 s` |
| Bad unit | `timer(unit="hours")` | `ValueError` |
| Metadata | `timer(len).__wrapped__ is len` | `True` |

Hints: reuse the `func is None` test from 1.12.3; validate `unit` before
defining the inner decorator; multiply the elapsed seconds by a factor looked
up in a dict.

<details><summary>Solution</summary>

```python
TIMER_UNITS = {"s": 1.0, "ms": 1_000.0, "us": 1_000_000.0}


def timer(
    func: Callable[..., Any] | None = None,
    /,
    *,
    unit: str = "ms",
    clock: Callable[[], float] = time.perf_counter,
    report: Callable[[str], object] = print,
) -> Callable[..., Any]:
    """Report each call's duration.

    Use as @timer or @timer(unit=..., clock=..., report=...).
    """
    if unit not in TIMER_UNITS:
        raise ValueError(
            f"unit must be one of {sorted(TIMER_UNITS)}, got {unit!r}"
        )

    def decorator(target: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(target)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            started = clock()
            result = target(*args, **kwargs)
            elapsed = (clock() - started) * TIMER_UNITS[unit]
            report(f"{target.__name__} took {elapsed:.2f} {unit}")
            return result

        return wrapper

    return decorator if func is None else decorator(func)
```

</details>

### Exercise 2 — `@retry(times, exceptions, backoff_factor)`

Write
`retry(times=3, exceptions=(Exception,), backoff_factor=0.0, *, sleep=time.sleep)`:

- call the function up to `times` times in total;
- when it raises one of `exceptions` and attempts remain, call
  `sleep(backoff_factor * 2 ** (attempt - 1))` (attempt counts from 1), then
  retry;
- after the last attempt, re-raise the last exception;
- other exceptions propagate immediately, with no retry;
- `times < 1` raises `ValueError` when `retry(...)` is called;
- use `functools.wraps`.

The checks use `flaky(failures, error)`, which builds a function that raises
`error` for its first `failures` calls and then returns `"ok"`, recording each
call in `.calls`. Every check retries on `ConnectionError` only, with
`backoff_factor=0.5`, and records the delays instead of sleeping.

| Check | Setup | Expected (result, calls, delays) |
| --- | --- | --- |
| Third attempt succeeds | 2 failures, `times=3` | `("ok", 3, [0.5, 1.0])` |
| Gives up | 5 failures, `times=3` | `("ConnectionError", 3, [0.5, 1.0])` |
| Not retried | `KeyError`, `times=3` | `("KeyError", 1, [])` |
| First try ok | 0 failures | `("ok", 1, [])` |
| Bad `times` | `retry(0)` | `ValueError` |
| Metadata | `retry(2)(flaky(…)).__name__` | `"unreliable"` |

Hints: `except exceptions:` accepts a tuple; use a bare `raise` on the last
attempt; validate `times` in the factory, not in the wrapper.

<details><summary>Solution</summary>

```python
def retry(
    times: int = 3,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
    backoff_factor: float = 0.0,
    *,
    sleep: Callable[[float], object] = time.sleep,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Retry, sleeping backoff_factor * 2 ** (attempt - 1) in between."""
    if times < 1:
        raise ValueError("times must be at least 1")

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            for attempt in range(1, times + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions:
                    if attempt == times:
                        raise
                    sleep(backoff_factor * 2 ** (attempt - 1))
            raise AssertionError("unreachable")

        return wrapper

    return decorator
```

</details>

### Exercise 3 — `@count_calls`

Write `count_calls(func)`: the wrapper has a `call_count` attribute that starts
at 0 and goes up by one on **every** call, even when the function raises. Each
decorated function has its own count. Keep the metadata.

| Check | Scenario | Expected |
| --- | --- | --- |
| Counting | `ping()` twice, `fail()` once (raises) | start `0`, `ping` `2`, `fail` `1`, name `"ping"` |
| Result | `count_calls(max)(3, 9)` | `9` |

Hints: a function attribute (1.12.4) is the simplest place for the count;
increment it *before* calling `func`, so a raising call is still counted.

<details><summary>Solution</summary>

```python
def count_calls(func: Callable[..., Any]) -> Callable[..., Any]:
    """Count every call in wrapper.call_count."""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        wrapper.call_count += 1
        return func(*args, **kwargs)

    wrapper.call_count = 0
    return wrapper
```

</details>

### Exercise 4 — `@validate_arguments` using `inspect.signature`

Write `validate_arguments(func)`. On each call, bind the arguments with
`inspect.signature(func).bind(*args, **kwargs)` and apply the defaults. For
every parameter whose annotation is a **class** (`isinstance(annotation,
type)`), check the value with `isinstance`. Parameters without an annotation,
or with a non-class annotation such as `list[int]` or `int | None`, are not
checked. On a mismatch raise
`TypeError(f"{name} must be {annotation.__name__}, got {type(value).__name__}")`.
An invalid call (a missing argument) raises `TypeError` from `bind`.

> **Warning:** The "no annotation" marker `inspect.Parameter.empty` is itself a
> class, so `isinstance(annotation, type)` is `True` for it. Test for it first,
> or every unannotated parameter fails the check.

The checks decorate
`add_item(sku: str, quantity: int = 1, *, note: str = "", tags: list[str] | None = None, extra=None)`.

| Check | Call | Expected |
| --- | --- | --- |
| Valid | `add_item("TEA", 2)` | `"2 x TEA"` |
| Defaults | `add_item("TEA")` | `"1 x TEA"` |
| Bad positional | `add_item("TEA", "2")` | `"quantity must be int, got str"` |
| Bad keyword-only | `add_item("TEA", note=5)` | `"note must be str, got int"` |
| Unchecked | `add_item("TEA", tags="x", extra=object())` | `"1 x TEA"` |
| Missing argument | `add_item()` | `TypeError` |
| Metadata | `add_item.__name__` | `"add_item"` |

Hints: compute the signature once, outside the wrapper; iterate over
`bound.arguments.items()` and look each parameter up in
`signature.parameters`.

<details><summary>Solution</summary>

```python
def validate_arguments(func: Callable[..., Any]) -> Callable[..., Any]:
    """Check annotated argument types on every call."""
    signature = inspect.signature(func)

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        bound = signature.bind(*args, **kwargs)
        bound.apply_defaults()
        for name, value in bound.arguments.items():
            annotation = signature.parameters[name].annotation
            if annotation is inspect.Parameter.empty or not isinstance(
                annotation, type
            ):
                continue  # Parameter.empty is itself a class: test it first
            if not isinstance(value, annotation):
                raise TypeError(
                    f"{name} must be {annotation.__name__}, "
                    f"got {type(value).__name__}"
                )
        return func(*args, **kwargs)

    return wrapper
```

</details>

### Exercise 5 — `serialize()` with `singledispatch`

Write a generic function `serialize(value)` that converts a value into
something `json.dumps` accepts. Use `@functools.singledispatch` and one
`register` per row, with no `isinstance` chain.

| Input type | Output |
| --- | --- |
| `str`, `int`, `float`, `bool`, `None` | Unchanged |
| `Decimal` | `str(value)` |
| `dt.date`, `dt.datetime` | `value.isoformat()` |
| `list`, `tuple` | A list, each item serialized |
| `set`, `frozenset` | A **sorted** list of serialized items |
| `dict` | `str(key)` keys, serialized values |
| Anything else | `TypeError("cannot serialize <type>")` |

| Check | Call | Expected |
| --- | --- | --- |
| `Decimal` | `serialize(Decimal("249.50"))` | `"249.50"` |
| `datetime` | `serialize(dt.datetime(2026, 11, 5, 9, 30))` | `"2026-11-05T09:30:00"` |
| Set | `serialize({3, 1, 2})` | `[1, 2, 3]` |
| Dict keys | `serialize({1: Decimal("1.5")})` | `{"1": "1.5"}` |
| Nested order | a dict with a date, Decimal, tuple, set | all converted |
| Unsupported | `serialize(object())` | `TypeError` |
| Uses dispatch | `Decimal in serialize.registry` | `True` |

Hints: the base function (registered for `object`) is the fallback, so it
raises the `TypeError`; register `type(None)` for `None`; `bool` is a subclass
of `int` and `datetime` a subclass of `date`, so they need no registration of
their own; `register` can be stacked to share one implementation between
several types.

<details><summary>Solution</summary>

```python
@functools.singledispatch
def serialize(value: object) -> Any:
    """Convert value into JSON-compatible data."""
    raise TypeError(f"cannot serialize {type(value).__name__}")


@serialize.register(str)
@serialize.register(int)
@serialize.register(float)
@serialize.register(type(None))
def _(value: object) -> object:
    return value  # bool is a subclass of int, so it lands here too


@serialize.register
def _(value: Decimal) -> str:
    return str(value)


@serialize.register
def _(value: dt.date) -> str:
    return value.isoformat()  # covers dt.datetime, a subclass of dt.date


@serialize.register(list)
@serialize.register(tuple)
def _(value: list[Any] | tuple[Any, ...]) -> list[Any]:
    return [serialize(item) for item in value]


@serialize.register(set)
@serialize.register(frozenset)
def _(value: set[Any] | frozenset[Any]) -> list[Any]:
    return sorted(serialize(item) for item in value)


@serialize.register
def _(value: dict) -> dict[str, Any]:
    return {str(key): serialize(item) for key, item in value.items()}
```

</details>

### Exercise 6 — `call_with_params(func, params)`

`params` is a dict of **strings**, as values arrive in a URL query string. Call
`func` with them, converted by the parameters' annotations:

- for each parameter of `func`: if its name is in `params`, convert the string
  with the annotation when it is `int`, `float` or `bool` (`"true"`, `"1"`,
  `"yes"` → `True`; `"false"`, `"0"`, `"no"` → `False`, case-insensitive;
  anything else raises `ValueError`), otherwise pass the string through;
- if the name is missing and the parameter has a default, leave it out;
- if it is missing and has no default, raise
  `TypeError(f"missing required parameter: {name}")`;
- keys in `params` that are not parameters are ignored.

The checks call
`search_products(query: str, page: int = 1, max_price: float = 1e9, in_stock: bool = False)`,
which returns its four arguments as a tuple.

| Check | `params` | Expected |
| --- | --- | --- |
| Converts | `query="tea", page="2", max_price="499.5", in_stock="Yes"` | `("tea", 2, 499.5, True)` |
| Defaults | `query="rice"` | `("rice", 1, 1e9, False)` |
| Extra keys | `query="x", utm_source="ad"` | `("x", 1, 1e9, False)` |
| Bool false | `in_stock="0"` | `False` |
| Missing | `page="2"` only | `"missing required parameter: query"` |
| Bad int | `page="two"` | `ValueError` |
| Bad bool | `in_stock="maybe"` | `ValueError` |

Hints: `bool("false")` is `True` (any non-empty string is truthy), so `bool`
needs its own word lists; `int("two")` already raises `ValueError` for you.

<details><summary>Solution</summary>

```python
TRUE_WORDS = frozenset({"true", "1", "yes"})
FALSE_WORDS = frozenset({"false", "0", "no"})


def convert_param(text: str, annotation: object) -> object:
    """Convert a query-string value by annotation (int, float, bool)."""
    if annotation is bool:
        lowered = text.lower()
        if lowered in TRUE_WORDS:
            return True
        if lowered in FALSE_WORDS:
            return False
        raise ValueError(f"not a boolean: {text!r}")
    if annotation in (int, float):
        return annotation(text)
    return text


def call_with_params(func: Callable[..., Any], params: dict[str, str]) -> Any:
    """Call func with string params converted by its annotations."""
    arguments: dict[str, Any] = {}
    for name, parameter in inspect.signature(func).parameters.items():
        if name in params:
            arguments[name] = convert_param(params[name], parameter.annotation)
        elif parameter.default is inspect.Parameter.empty:
            raise TypeError(f"missing required parameter: {name}")
    return func(**arguments)
```

</details>

### Exercise 7 — a mini router with typed path parameters

Write a `Router` class:

- `router.get(path_template)` and `router.post(path_template)` are decorator
  factories that register the handler and **return it unchanged**;
- a template is split on `/`; a segment like `{user_id}` captures that part of
  the path, and other segments must match exactly;
- `router.dispatch(method, path)` finds the **first** registered route whose
  method and segments match, converts each captured value with the handler
  parameter's annotation (`int`, `float` or `str`), and returns
  `handler(**captured)`;
- a route whose conversion fails (`"/users/abc"` for an `int`) does not match;
- when nothing matches, raise `LookupError(f"no route for {method} {path}")`.

The checks register four routes: `GET /health`, `GET /users/{user_id}`,
`GET /users/{user_id}/orders/{order_code}` and `POST /users/{user_id}`.

| Check | Request | Expected |
| --- | --- | --- |
| Literal route | `GET /health` | `{"status": "ok"}` |
| Typed param | `GET /users/42` | `{"user_id": 42, "type": "int"}` |
| Two params | `GET /users/7/orders/A-19` | `(7, "A-19")` |
| Method matters | `POST /users/7` | `"updated 7"` |
| Bad conversion | `GET /users/abc` | `LookupError` |
| Unknown path | `GET /admin` | `LookupError` |
| Segment count | `GET /users/7/x` | `LookupError` |
| Returns handler | `Router().get("/x")(handler) is handler` | `True` |

Hints: store routes in a list, not a dict, because "first match wins" needs an
order and templates are not exact keys; compare segment counts first; read the
annotations with `inspect.signature(handler).parameters`; return `None` from a
helper to mean "no match".

<details><summary>Solution</summary>

```python
type Decorator = Callable[[Callable[..., Any]], Callable[..., Any]]

PATH_CONVERTERS: dict[object, Callable[[str], object]] = {
    int: int,
    float: float,
    str: str,
}


class Router:
    """Register handlers with @router.get / @router.post; dispatch paths."""

    def __init__(self) -> None:
        self.routes: list[tuple[str, list[str], Callable[..., Any]]] = []

    def route(self, method: str, path_template: str) -> Decorator:
        """Return a decorator that registers a handler for the route."""

        def decorator(handler: Callable[..., Any]) -> Callable[..., Any]:
            segments = path_template.strip("/").split("/")
            self.routes.append((method, segments, handler))
            return handler

        return decorator

    def get(self, path_template: str) -> Decorator:
        return self.route("GET", path_template)

    def post(self, path_template: str) -> Decorator:
        return self.route("POST", path_template)

    @staticmethod
    def match(
        template_segments: list[str],
        path_segments: list[str],
        handler: Callable[..., Any],
    ) -> dict[str, object] | None:
        """Return the converted path parameters, or None if no match."""
        if len(template_segments) != len(path_segments):
            return None
        parameters = inspect.signature(handler).parameters
        captured: dict[str, object] = {}
        for template_segment, path_segment in zip(
            template_segments, path_segments, strict=True
        ):
            if template_segment.startswith("{") and template_segment.endswith(
                "}"
            ):
                name = template_segment[1:-1]
                converter = PATH_CONVERTERS.get(
                    parameters[name].annotation, str
                )
                try:
                    captured[name] = converter(path_segment)
                except ValueError:
                    return None
            elif template_segment != path_segment:
                return None
        return captured

    def dispatch(self, method: str, path: str) -> Any:
        """Call the first matching handler with typed path parameters."""
        path_segments = path.strip("/").split("/")
        for route_method, template_segments, handler in self.routes:
            if route_method != method:
                continue
            captured = self.match(template_segments, path_segments, handler)
            if captured is not None:
                return handler(**captured)
        raise LookupError(f"no route for {method} {path}")
```

</details>

With the reference solutions in place, every check cell reports a full pass,
for example for Exercise 7:

```text
PASS  literal route
PASS  typed param
PASS  two params
PASS  method matters
PASS  conversion failure is 404
PASS  unknown path
PASS  segment count matters
PASS  decorator returns handler
8/8 checks passed
```

## Recap

| Concept | Takeaway | JavaScript equivalent |
| --- | --- | --- |
| `@decorator` | `f = decorator(f)` at def time | Higher-order call |
| Import time | Decorators run on import | Module top-level code |
| Stacking | Applied bottom-up, run top-down | `a(b(fn))` |
| Wrapper | `*args, **kwargs`, return result | Rest/spread wrapper |
| `functools.wraps` | Keeps name, doc, signature | None built in |
| `__wrapped__` | Reach the original function | None |
| Factory | Options → decorator → wrapper | Decorator factory |
| Optional args | `func=None, /, *, options` | None |
| State | Attribute, closure or `__call__` | Closure state |
| Method trap | Class decorators need `__get__` | Lost `this` |
| Class decorator | `C = d(C)`; registries, `@dataclass` | Class decorators |
| Gallery | timer, retry, log, roles, register | Express middleware |
| `@app.get(path)` | Registers and returns the handler | `app.get(path, h)` |
| `partial` | Freeze arguments, even keywords | `fn.bind(null, x)` |
| `cache` / `lru_cache` | Memoize; hashable args; stats | lodash `memoize` |
| `cached_property` | Compute once per instance | Lazy getter |
| `reduce` | Fold; pass `initial` | `array.reduce` |
| `singledispatch` | Dispatch on first arg type | `instanceof` chain |
| `total_ordering` | Two methods give all six | None |
| `operator` | Getters and operators as functions | Arrow functions |
| Frames | `f_code`, `f_locals`, `f_back`, `f_lineno` | Execution contexts |
| Stack views | `inspect.stack`, `extract_stack` | `new Error().stack` |
| Recursion | Limit ~1000, no tail calls | `RangeError` |
| Explicit stack | A list replaces deep recursion | Same technique |
| `inspect.signature` | Parameters, `bind`, defaults | `fn.length` (less) |
| Dependency injection | Annotation → provider → argument | NestJS / Angular DI |

## Further reading

- [Glossary: decorator](https://docs.python.org/3/glossary.html#term-decorator)
- [Function definitions (decorators)](https://docs.python.org/3/reference/compound_stmts.html#function-definitions)
- [Class definitions](https://docs.python.org/3/reference/compound_stmts.html#class-definitions)
- [`functools`](https://docs.python.org/3/library/functools.html)
- [`operator`](https://docs.python.org/3/library/operator.html)
- [`inspect`](https://docs.python.org/3/library/inspect.html)
- [`traceback`](https://docs.python.org/3/library/traceback.html)
- [`warnings.deprecated`](https://docs.python.org/3/library/warnings.html#warnings.deprecated)
- [`sys._getframe`](https://docs.python.org/3/library/sys.html#sys._getframe)
- [`sys.setrecursionlimit`](https://docs.python.org/3/library/sys.html#sys.setrecursionlimit)
- [Frame objects](https://docs.python.org/3/reference/datamodel.html#frame-objects)
- [PEP 318 — Decorators for functions and methods](https://peps.python.org/pep-0318/)
- [PEP 3129 — Class decorators](https://peps.python.org/pep-3129/)
- [PEP 614 — Relaxing grammar restrictions on decorators](https://peps.python.org/pep-0614/)
- [PEP 443 — Single-dispatch generic functions](https://peps.python.org/pep-0443/)
- [PEP 362 — Function signature object](https://peps.python.org/pep-0362/)
- [PEP 612 — Parameter specification variables](https://peps.python.org/pep-0612/)
- [PEP 667 — Consistent views of namespaces](https://peps.python.org/pep-0667/)
- [PEP 702 — Marking deprecations using the type system](https://peps.python.org/pep-0702/)

[← Previous](unit-1-11-scope-namespaces-and-closures.md) · [Index](README.md) · [Next →](unit-1-13-iterators-generators-and-itertools.md)
