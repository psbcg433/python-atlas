"""Unit 1.12 — Decorators, functools and the Call Stack (with Lab 1.12)."""

from nbformat import NotebookNode

from nb_builder import code, md, predict_cells

UNIT_SETUP_SOURCE = '''
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


def show_size(label: str, obj: object) -> None:
    """Print the shallow size in bytes, the type and the id of an object."""
    print(f"{label}: {sys.getsizeof(obj)} bytes, type={type(obj).__name__}, id={id(obj)}")


def raised_error_name(thunk: Callable[[], object]) -> str:
    """Call thunk and return the name of the exception it raised, or "no error"."""
    try:
        thunk()
    except Exception as error:
        return type(error).__name__
    return "no error"


print(f"{sys.version_info[:2]=}")
'''


def _overview_cells() -> list[NotebookNode]:
    """Unit opener and setup."""
    return [
        md(
            """
            ## Unit 1.12 — Decorators, functools and the Call Stack

            **Objectives**

            - Explain that `@decorator` is `f = decorator(f)` run at definition time, and
              predict the order of stacked decorators.
            - Write decorators that keep the wrapped function's metadata (`functools.wraps`),
              take arguments (factories), keep state, and work on methods.
            - Read and reuse a gallery of real-world decorators (`timer`, `retry`, `log_calls`,
              `memoize`, registration), and see how `@app.get("/users")` works.
            - Use the key `functools` and `operator` tools.
            - Walk the call stack through frame objects, and rewrite deep recursion with an
              explicit stack.
            - Introspect callables with `inspect.signature` and build a tiny dependency injector.

            **JS bridge**

            | JavaScript concept | Python equivalent | The difference that bites |
            | --- | --- | --- |
            | Higher-order function `withLogging(fn)` | decorator `@log_calls` | `@` syntax applies it once, at definition time |
            | TC39 / TypeScript decorators | Python decorators | Python's work on any function or class, with no build step |
            | Lost `fn.name` after wrapping | `functools.wraps` | Without it, `__name__`, `__doc__` and the signature are lost |
            | `fn.bind(null, x)` | `functools.partial(fn, x)` | `partial` can also fix keyword arguments |
            | Memoize helpers (lodash) | `functools.cache`, `lru_cache` | Built in, with stats; arguments must be hashable |
            | `obj => obj.price` | `operator.attrgetter("price")` | Faster, picklable, supports dotted paths |
            | `new Error().stack` | `traceback.extract_stack()`, `inspect.stack()` | Real frame objects with locals |
            | Express `app.get("/users", handler)` | `@app.get("/users")` | The decorator registers the function and returns it |

            The next cell is this unit's setup.
            """
        ),
        code(UNIT_SETUP_SOURCE),
    ]


def _mechanics_cells() -> list[NotebookNode]:
    """1.12.1 Decorator mechanics."""
    return [
        md(
            """
            ### 1.12.1 Decorator mechanics

            A **decorator** is any callable that takes a function and returns something to bind
            in its place (usually a new function). The `@` line is pure syntax sugar:

            ```python
            @announce                     def greet(): ...
            def greet(): ...         ≡    greet = announce(greet)
            ```

            The decorator runs **once, when the `def` statement runs**, not when the function is
            called. The next cell writes `announce`, which prints when it is applied and returns
            the function unchanged, then shows the manual form does exactly the same.
            """
        ),
        code(
            '''
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
            '''
        ),
        md(
            """
            **Import-time execution.** Because decorators run when the `def` runs, and a module's
            top-level `def`s run when the module is imported, decorators execute **at import
            time**. Frameworks rely on this: importing a module full of `@app.get(...)` handlers
            is what registers the routes. The next cell runs a small module from a string
            (`exec` stands in for `import`) and shows the registration happening before any
            handler is called.
            """
        ),
        code(
            '''
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
            print(f"{module_namespace['registered_handlers']=}  (no handler was called)")
            '''
        ),
        md(
            """
            **Stacking order.** With several decorators, the one **closest to the `def` is applied
            first** (bottom-up), so the outermost wrapper is the top one, and at call time the
            wrappers **run top-down**:

            ```python
            @bold
            @italic
            def headline(): ...      ≡    headline = bold(italic(headline))
            ```

            ```mermaid
            sequenceDiagram
                participant Caller
                participant bold as bold wrapper
                participant italic as italic wrapper
                participant headline as headline()
                Caller->>bold: headline()
                bold->>italic: call inner
                italic->>headline: call inner
                headline-->>italic: "Sale"
                italic-->>bold: "<i>Sale</i>"
                bold-->>Caller: "<b><i>Sale</i></b>"
            ```

            <details><summary>ASCII fallback</summary>

            ```text
            definition time (bottom-up):  italic(headline) -> then bold(that)
            call time (top-down):
              Caller -> bold wrapper -> italic wrapper -> headline()
              Caller <- "<b><i>Sale</i></b>" <- "<i>Sale</i>" <- "Sale"
            ```

            </details>
            """
        ),
        code(
            '''
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
            '''
        ),
        *predict_cells(
            snippet="""
            @italic
            @bold
            def banner():
                return "Diwali offers"

            print(banner())
            """,
            answer="""
            First, at definition time, `applying bold` then `applying italic` (bottom-up). Then
            the call prints `italic wrapper runs`, `bold wrapper runs` (top-down) and the result
            `<i><b>Diwali offers</b></i>`. Swapping the decorators swaps the nesting.
            """,
            proof="""
            @italic
            @bold
            def banner() -> str:
                return "Diwali offers"


            print(banner())
            """,
        ),
    ]


def _writing_cells() -> list[NotebookNode]:
    """1.12.2 Writing decorators."""
    return [
        md(
            """
            ### 1.12.2 Writing decorators

            The standard shape: an outer function receives `func`, defines a **wrapper** that
            accepts any arguments (`*args, **kwargs`), does something before and/or after calling
            `func(*args, **kwargs)`, and **returns the result**. It is the forwarding wrapper from
            Unit 1.10.4 (`call_logged`), packaged so it applies once at definition time.

            The first attempt below works but has a flaw: the decorated function now reports
            the wrapper's name, docstring and signature.
            """
        ),
        code(
            '''
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
            print(f"{inspect.signature(add_gst)=}")
            '''
        ),
        md(
            """
            **`functools.wraps`** fixes that. It is itself a decorator, applied to the wrapper,
            that copies the attributes listed in `functools.WRAPPER_ASSIGNMENTS` (on 3.14+:
            `__module__`, `__name__`, `__qualname__`, `__doc__`, `__annotate__`,
            `__type_params__`), merges `__dict__`, and sets `wrapper.__wrapped__ = func`.
            `inspect.signature` follows `__wrapped__`, so tools (and FastAPI) see the real
            signature. Always use it.
            """
        ),
        code(
            '''
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


            print(f"{add_gst.__name__=}, {add_gst.__doc__=}")
            print(f"{inspect.signature(add_gst)=}")
            print(f"{functools.WRAPPER_ASSIGNMENTS=}")
            '''
        ),
        md(
            """
            **`__wrapped__`** gives access to the original, undecorated function, for example to
            test it without the logging. `inspect.unwrap` follows a whole chain of
            `__wrapped__` links.
            """
        ),
        code(
            """
            original_add_gst = add_gst.__wrapped__
            print(f"{original_add_gst(1000, 5)=}  (no log line: the wrapper is bypassed)")
            print(f"{inspect.unwrap(add_gst) is original_add_gst=}")
            """
        ),
        md(
            """
            **Returning results.** The most common decorator bug is forgetting `return` in the
            wrapper: every decorated function then returns `None`. Python raises no error.
            """
        ),
        code(
            '''
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
            '''
        ),
        md(
            """
            **Typed decorators** (*New in 3.12* syntax, PEP 695 and PEP 612). A type checker can
            keep the wrapped function's exact signature if the decorator is generic over a
            `ParamSpec` (`**P`) and a return type `R`. Type checking is covered in Phase 4; the
            runtime behaviour is identical.
            """
        ),
        code(
            '''
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
            '''
        ),
    ]


def _factory_cells() -> list[NotebookNode]:
    """1.12.3 Decorator factories."""
    return [
        md(
            """
            ### 1.12.3 Decorator factories

            To configure a decorator (`@retry(times=3)`), add one more level: a **factory**
            that takes the options and returns the decorator.

            | Level | Called with | Returns |
            | --- | --- | --- |
            | `retry(times=3)` | the options | `decorator` |
            | `decorator(func)` | the function (at definition time) | `wrapper` |
            | `wrapper(*args, **kwargs)` | the call arguments (every call) | the result |

            `@retry(times=3)` therefore means `fetch = retry(times=3)(fetch)`. This first version
            retries on any exception and re-raises the last one when the attempts run out. The
            gallery in 1.12.6 adds backoff and an exception filter.
            """
        ),
        code(
            '''
            def retry_simple(times: int = 3) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
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
            '''
        ),
        md(
            """
            The next cell decorates a flaky function that fails twice before succeeding, then
            one that always fails.
            """
        ),
        code(
            '''
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
            '''
        ),
        md(
            """
            **Optional-argument decorators.** Sometimes both `@timer` and `@timer(unit="s")`
            should work. Make the function positional-only and optional, the options
            keyword-only:

            - `@timer`: Python calls `timer(func)`, so `func` is given → decorate it directly.
            - `@timer(unit="s")`: the call has no function, so `func is None` → return the
              decorator, which Python then applies to the function.

            `timer` below is a **shared helper**: the gallery (1.12.6) and the Phase 1 project
            reuse it. `report` lets the caller send the message somewhere other than `print`.
            Timings vary by machine.
            """
        ),
        code(
            '''
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
                    raise ValueError(f"unit must be one of {sorted(TIME_UNITS)}, got {unit!r}")

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
            '''
        ),
        md(
            """
            Both forms in action. The `try` / `finally` in the wrapper means the time is reported
            even when the function raises.
            """
        ),
        code(
            '''
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
            print(f"{build_report.__name__=}, unknown unit: {raised_error_name(lambda: timer(unit='h'))}")
            '''
        ),
    ]


def _stateful_cells() -> list[NotebookNode]:
    """1.12.4 Stateful and class-based decorators."""
    return [
        md(
            """
            ### 1.12.4 Stateful and class-based decorators

            A decorator can remember things between calls. Three places to keep the state:

            | Where | How | Good for |
            | --- | --- | --- |
            | Function attribute | `wrapper.last_result = …` | state the caller should be able to read |
            | Closure variable | `nonlocal` in the wrapper | private state |
            | Instance attribute | a class with `__call__` | richer state and helper methods |

            **Function attribute.** The wrapper is a function object, so it can carry attributes
            (Unit 1.10.1). Callers read them directly.
            """
        ),
        code(
            '''
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
            '''
        ),
        md(
            """
            **Closure variable.** `run_once` keeps a private flag and cached result with
            `nonlocal`: the first call runs the function, later calls return the same result.
            Useful for expensive one-time setup.
            """
        ),
        code(
            '''
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
            '''
        ),
        md(
            """
            **Class-based decorator.** A class whose instances are callable (`__call__`) can be a
            decorator: `CallHistory(func)` builds an instance that replaces the function.
            `functools.update_wrapper(self, func)` copies the metadata, as `wraps` does for
            functions.
            """
        ),
        code(
            '''
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
            '''
        ),
        md(
            """
            **The method trap.** Put the same class-based decorator on a **method** and calls
            break. Functions become bound methods because they have a `__get__` method (they are
            *descriptors*, Phase 2): `cart.add` calls `add.__get__(cart, Cart)`, which fixes
            `self`. A `CallHistory` instance has no `__get__`, so `cart.add` returns the plain
            instance and `self` is never passed.
            """
        ),
        code(
            '''
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
            '''
        ),
        md(
            """
            **The `__get__` fix.** Give the decorator class a `__get__` that returns a bound
            method (`types.MethodType(self, instance)`) when accessed through an instance. Plain
            function decorators never have this problem: their wrapper is a function, which
            already has `__get__`.
            """
        ),
        code(
            '''
            class MethodSafeCallHistory(CallHistory):
                """CallHistory that also works on methods."""

                def __get__(self, instance: object, owner: type | None = None) -> Any:
                    if instance is None:  # accessed on the class: return the decorator itself
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
            '''
        ),
    ]


def _methods_classes_cells() -> list[NotebookNode]:
    """1.12.5 Decorating methods and classes."""
    return [
        md(
            """
            ### 1.12.5 Decorating methods and classes

            **Methods.** A function decorator works on methods unchanged: the wrapper is a plain
            function, so it becomes a bound method, and `self` simply arrives as `args[0]`.
            """
        ),
        code(
            '''
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
            '''
        ),
        md(
            """
            **Class decorators.** `@decorator` above a `class` statement means
            `Cls = decorator(Cls)`: the decorator receives the finished class. The most common
            use is **registration**: collect classes in a registry so they can be looked up by
            name later (serializers, plugins, ORM models, command handlers). The factory form
            takes the registry key.
            """
        ),
        code(
            '''
            PAYMENT_PROVIDERS: dict[str, type] = {}


            def payment_provider(name: str) -> Callable[[type], type]:
                """Class decorator factory: register the class under name."""

                def decorator(cls: type) -> type:
                    PAYMENT_PROVIDERS[name] = cls
                    cls.provider_name = name
                    return cls  # return the class itself, unchanged apart from the attribute

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
            '''
        ),
        md(
            """
            A class decorator can also **add behaviour**, for example a `__repr__` built from the
            instance attributes. `@dataclass` (Phase 2) is the standard library's big example of
            a class decorator that generates methods.
            """
        ),
        code(
            '''
            def add_repr(cls: type) -> type:
                """Give cls a __repr__ listing its instance attributes."""

                def __repr__(self: Any) -> str:
                    fields = ", ".join(f"{name}={value!r}" for name, value in vars(self).items())
                    return f"{type(self).__name__}({fields})"

                cls.__repr__ = __repr__
                return cls


            @add_repr
            class Customer:
                def __init__(self, name: str, city: str) -> None:
                    self.name = name
                    self.city = city


            print(Customer("Asha", "Pune"))
            '''
        ),
    ]


def _gallery_cells() -> list[NotebookNode]:
    """1.12.6 Real-world decorator gallery."""
    return [
        md(
            """
            ### 1.12.6 Real-world decorator gallery

            | Decorator | Kind | What it does |
            | --- | --- | --- |
            | `timer` | optional-argument | report the duration of each call (defined in 1.12.3) |
            | `retry` | factory | retry with exponential backoff, only on listed exceptions |
            | `log_calls` | plain | log arguments and the result (or the exception) |
            | `require_role` | factory | refuse the call unless the user has a role |
            | `validate_types` | factory | check argument types given explicitly |
            | `register` | factory | add the function to a registry |
            | `deprecated` | factory | warn on every call |
            | `memoize` | plain | cache results by arguments |
            | `App.get` | method factory | register a route handler (how FastAPI works) |

            #### `timer`

            Reused from 1.12.3. Here `report` collects the messages in a list instead of printing,
            as a logger would. Timings vary by machine.
            """
        ),
        code(
            '''
            timing_log: list[str] = []


            @timer(unit="ms", report=timing_log.append)
            def render_invoice(line_count: int) -> str:
                """Build a long invoice string."""
                return "\\n".join(f"line {number}" for number in range(line_count))


            render_invoice(10_000)
            render_invoice(50_000)
            print(f"{len(timing_log)=}, first entry starts with: {timing_log[0].split(' took ')[0]!r}")
            '''
        ),
        md(
            """
            #### `retry` with backoff and an exception filter

            The production version of 1.12.3's `retry_simple`, and a **shared helper** the
            Phase 1 project reuses:

            - only exceptions listed in `exceptions` are retried; anything else (a bug, such as
              `ValueError`) propagates at once;
            - between attempts it sleeps `first_delay * backoff ** (attempt - 1)` seconds
              (exponential backoff), so a struggling service gets time to recover;
            - `sleep` is a parameter so tests (and this notebook) can record the delays instead of
              waiting.
            """
        ),
        code(
            '''
            def retry(
                times: int = 3,
                *,
                exceptions: tuple[type[Exception], ...] = (Exception,),
                first_delay: float = 0.1,
                backoff: float = 2.0,
                sleep: Callable[[float], object] = time.sleep,
            ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
                """Retry on the listed exceptions, sleeping first_delay * backoff**n in between."""
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
            '''
        ),
        md(
            """
            The next cell records the delays (`sleep=recorded_delays.append`): 0.1 s, 0.2 s,
            0.4 s before the fourth attempt succeeds. A `ValueError` is not in the filter, so it
            is raised after a single attempt.
            """
        ),
        code(
            '''
            recorded_delays: list[float] = []
            gateway_attempts: list[int] = []


            @retry(times=5, exceptions=(ConnectionError, TimeoutError), sleep=recorded_delays.append)
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


            print(f"{call_payment_gateway(499)=}, {len(gateway_attempts)=}, {recorded_delays=}")
            print(f"parse_amount('abc'): {raised_error_name(lambda: parse_amount('abc'))}, {recorded_delays=}")
            '''
        ),
        md(
            """
            #### `log_calls`

            Logs the arguments and the result, or the exception (and re-raises it: a logging
            decorator must never swallow errors).
            """
        ),
        code(
            '''
            def log_calls(func: Callable[..., Any]) -> Callable[..., Any]:
                """Print each call with its arguments, then its result or exception."""

                @functools.wraps(func)
                def wrapper(*args: Any, **kwargs: Any) -> Any:
                    arguments = [repr(arg) for arg in args] + [f"{k}={v!r}" for k, v in kwargs.items()]
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
            '''
        ),
        md(
            """
            #### `require_role`

            An authorization guard: the decorated function takes a `user` keyword argument, and
            the wrapper raises `PermissionError` unless the user has the required role. Phase 6
            does this with FastAPI dependencies.
            """
        ),
        code(
            '''
            def require_role(role: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
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
            '''
        ),
        md(
            """
            #### `validate_types`

            The expected types are passed to the factory **explicitly**
            (`@validate_types(quantity=int)`). `inspect.signature(func).bind(...)` maps the
            positional and keyword arguments to parameter names, so both call styles are checked.
            (Lab 1.12 builds `validate_arguments`, which reads the types from the annotations
            instead.)
            """
        ),
        code(
            '''
            def validate_types(**expected_types: type) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
                """Raise TypeError when a named argument is not of its expected type."""

                def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
                    signature = inspect.signature(func)

                    @functools.wraps(func)
                    def wrapper(*args: Any, **kwargs: Any) -> Any:
                        bound = signature.bind(*args, **kwargs)
                        for name, expected_type in expected_types.items():
                            if name in bound.arguments and not isinstance(bound.arguments[name], expected_type):
                                actual = type(bound.arguments[name]).__name__
                                raise TypeError(f"{name} must be {expected_type.__name__}, got {actual}")
                        return func(*args, **kwargs)

                    return wrapper

                return decorator


            @validate_types(sku=str, quantity=int)
            def reserve_stock(sku: str, quantity: int) -> str:
                return f"reserved {quantity} x {sku}"


            print(reserve_stock("TEA-500G", quantity=3))
            print(f"quantity '3': {raised_error_name(lambda: reserve_stock('TEA-500G', '3'))}")
            '''
        ),
        md(
            """
            #### `register`

            A function registry: the decorator stores the function under a key and returns it
            **unchanged**, so it can still be called directly. This is the plugin pattern (here,
            report exporters chosen by format name at run time).
            """
        ),
        code(
            '''
            EXPORTERS: dict[str, Callable[[list[dict[str, Any]]], str]] = {}


            def register(format_name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
                """Store the decorated function in EXPORTERS under format_name."""

                def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
                    EXPORTERS[format_name] = func
                    return func

                return decorator


            @register("csv")
            def export_csv(rows: list[dict[str, Any]]) -> str:
                return "\\n".join(",".join(str(value) for value in row.values()) for row in rows)


            @register("tsv")
            def export_tsv(rows: list[dict[str, Any]]) -> str:
                return "\\n".join("\\t".join(str(value) for value in row.values()) for row in rows)


            sales_rows = [{"sku": "TEA-500G", "units": 3}, {"sku": "RICE-5KG", "units": 1}]
            print(f"{sorted(EXPORTERS)=}")
            print(EXPORTERS["csv"](sales_rows))
            '''
        ),
        md(
            """
            #### `deprecated`

            Warn callers that a function is going away. `warnings.warn(..., DeprecationWarning,
            stacklevel=2)` points the warning at the **caller's** line. The cell captures the
            warnings with `warnings.catch_warnings(record=True)` so they can be printed.
            """
        ),
        code(
            '''
            def deprecated(reason: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
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
            print([f"{w.category.__name__}: {w.message}" for w in caught_warnings])
            '''
        ),
        md(
            """
            The standard library has its own: `warnings.deprecated` (*New in 3.13*, PEP 702)
            warns at run time **and** tells type checkers to flag every use. It also sets
            `__deprecated__` on the function.
            """
        ),
        code(
            """
            if sys.version_info >= (3, 13):

                @warnings.deprecated("use calculate_tax() instead")
                def compute_sales_tax(amount: int) -> float:
                    return amount * 0.18

                with warnings.catch_warnings(record=True) as caught_warnings:
                    warnings.simplefilter("always")
                    compute_sales_tax(100)
                print([w.category.__name__ for w in caught_warnings], f"{compute_sales_tax.__deprecated__=}")
            else:
                print("warnings.deprecated needs Python 3.13; skipped")
            """
        ),
        md(
            """
            #### `memoize`

            Cache results in a dict keyed by the arguments. Repeated calls with the same
            arguments skip the work. This is what `functools.cache` does (1.12.7, with a C
            implementation and statistics); writing it once shows there is no magic.
            """
        ),
        code(
            '''
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
                """Count the ways to make amount from coins (exponential without a cache)."""
                if amount == 0:
                    return 1
                if amount < 0 or not coins:
                    return 0
                return ways_to_pay(amount - coins[0], coins) + ways_to_pay(amount, coins[1:])


            print(f"{ways_to_pay(200)=}, {len(ways_to_pay.cache)=} cached results")
            '''
        ),
        md(
            """
            #### How `@app.get("/users")` works

            A web framework's route decorator is a **registration decorator factory implemented as
            a method**: `app.get(path)` returns a decorator that stores `(method, path) → handler`
            in the app's route table and returns the handler unchanged. Dispatching a request is
            then a dictionary lookup. This version matches exact paths only; Lab 1.12 adds path
            parameters like `/users/{user_id}`.
            """
        ),
        code(
            '''
            class App:
                """A tiny web app: a route table filled by decorators."""

                def __init__(self) -> None:
                    self.routes: dict[tuple[str, str], Callable[[], Any]] = {}

                def route(self, method: str, path: str) -> Callable[[Callable[[], Any]], Callable[[], Any]]:
                    def decorator(handler: Callable[[], Any]) -> Callable[[], Any]:
                        self.routes[(method, path)] = handler
                        return handler

                    return decorator

                def get(self, path: str) -> Callable[[Callable[[], Any]], Callable[[], Any]]:
                    return self.route("GET", path)

                def handle(self, method: str, path: str) -> tuple[int, Any]:
                    handler = self.routes.get((method, path))
                    return (404, {"detail": "Not Found"}) if handler is None else (200, handler())
            '''
        ),
        md("Register two handlers and dispatch a few requests."),
        code(
            """
            app = App()


            @app.get("/users")
            def list_users() -> list[str]:
                return ["asha", "ravi"]


            @app.get("/health")
            def health() -> dict[str, str]:
                return {"status": "ok"}


            print(f"{list(app.routes)=}")
            print(app.handle("GET", "/users"), app.handle("GET", "/health"), app.handle("GET", "/admin"))
            print(f"{list_users()=}  (still callable directly)")
            """
        ),
    ]


def _functools_cells() -> list[NotebookNode]:
    """1.12.7 functools."""
    return [
        md(
            """
            ### 1.12.7 `functools`

            | Tool | What it does | JS equivalent |
            | --- | --- | --- |
            | `partial(func, *args, **kwargs)` | freeze some arguments | `func.bind(null, a)` |
            | `partialmethod` | `partial` for methods defined in a class body | — |
            | `cache` | unbounded memoization | lodash `memoize` |
            | `lru_cache(maxsize=128)` | bounded memoization with stats (`cache_info`, `cache_clear`) | — |
            | `cached_property` | compute an attribute once per instance | lazy getter |
            | `reduce(func, iterable, initial)` | fold a sequence into one value | `array.reduce` |
            | `singledispatch` | choose an implementation by the first argument's type | — |
            | `total_ordering` | fill in `<=`, `>`, `>=` from `==` and `<` | — |
            | `update_wrapper` / `wraps` | copy metadata onto a wrapper | — |

            #### `partial`

            `functools.partial(func, *args, **kwargs)` returns a callable with some arguments
            fixed. It keeps `.func`, `.args` and `.keywords` for introspection.
            """
        ),
        code(
            '''
            def price_with_tax(amount: float, rate_percent: float, *, round_to: int = 2) -> float:
                """Return amount plus tax."""
                return round(amount * (100 + rate_percent) / 100, round_to)


            with_gst = functools.partial(price_with_tax, rate_percent=18)
            whole_rupees = functools.partial(price_with_tax, round_to=0)
            print(f"{with_gst(499)=}, {whole_rupees(499, 5)=}")
            print(f"{with_gst.func.__name__=}, {with_gst.args=}, {with_gst.keywords=}")
            '''
        ),
        md(
            """
            `functools.Placeholder` (*New in 3.14*) reserves a positional slot, so you can fix a
            **later** positional argument and leave an earlier one open.
            """
        ),
        code(
            """
            if sys.version_info >= (3, 14):
                boxes_of_seven = functools.partial(divmod, functools.Placeholder, 7)
                print(f"{boxes_of_seven(50)=}  (full boxes, leftover items)")
            else:
                print("functools.Placeholder needs Python 3.14; skipped")
            """
        ),
        md(
            """
            #### `partialmethod`

            `partial` objects are not descriptors, so they do not receive `self` when stored in a
            class body. `partialmethod` is the version that works as a method.
            """
        ),
        code(
            '''
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
            '''
        ),
        md(
            """
            #### `cache`

            `@functools.cache` is an unbounded memoizer (the same as `lru_cache(maxsize=None)`):
            a plain dict lookup in C, the fastest option when the set of arguments is small.
            """
        ),
        code(
            '''
            @functools.cache
            def fibonacci(position: int) -> int:
                """Return the position-th Fibonacci number (exponential without the cache)."""
                return position if position < 2 else fibonacci(position - 1) + fibonacci(position - 2)


            print(f"{fibonacci(90)=}")
            print(f"{fibonacci.cache_info()=}")
            '''
        ),
        md(
            """
            #### `lru_cache`

            `@functools.lru_cache(maxsize=N)` keeps at most `N` results and evicts the **least
            recently used** one. `cache_info()` reports hits, misses and the current size;
            `cache_clear()` empties it.
            """
        ),
        code(
            '''
            @functools.lru_cache(maxsize=2)
            def exchange_rate(currency: str) -> float:
                """Pretend to call a rate service."""
                print(f"  fetching {currency}")
                return {"USD": 83.2, "EUR": 90.1, "GBP": 105.4}[currency]


            for currency in ["USD", "EUR", "USD", "GBP", "EUR"]:
                exchange_rate(currency)
            print(f"{exchange_rate.cache_info()=}")
            exchange_rate.cache_clear()
            print(f"after cache_clear: {exchange_rate.cache_info()=}")
            '''
        ),
        md(
            """
            **Hashable arguments.** The arguments become a dict key, so they must be hashable:
            a list argument raises `TypeError`. Pass a tuple (or a `frozenset`) instead.
            """
        ),
        code(
            '''
            @functools.lru_cache(maxsize=128)
            def basket_total(prices: tuple[int, ...]) -> int:
                """Sum a basket given as a tuple."""
                return sum(prices)


            print(f"{basket_total((249, 640))=}")
            try:
                basket_total([249, 640])
            except TypeError as error:
                print(f"{type(error).__name__}: {error}")
            '''
        ),
        md(
            """
            **Memory risk on methods.** `lru_cache` on a method caches `self` as part of every
            key. The cache belongs to the class, so it keeps **every instance alive** as long as
            its entries remain, even after your code has dropped all references. The `weakref`
            below shows the object surviving `del` until the cache is cleared. Prefer
            `cached_property`, a cache keyed by plain values outside the class, or a per-instance
            cache.
            """
        ),
        code(
            '''
            class QuoteService:
                """Caches quotes with lru_cache on a method (risky)."""

                @functools.lru_cache(maxsize=None)  # noqa: B019, UP033 (the leak is the point)
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
            '''
        ),
        md(
            """
            #### `cached_property`

            Computes an attribute on first access and stores it in the instance `__dict__`;
            later accesses are ordinary attribute reads. Delete the attribute to recompute. It
            avoids the method-cache leak above because the cache lives on the instance.
            """
        ),
        code(
            '''
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
            '''
        ),
        md(
            """
            #### `reduce`

            `functools.reduce(func, iterable, initial)` folds a sequence into one value, like
            JavaScript's `array.reduce`. Pass `initial` so empty input works (*Changed in 3.14*:
            `initial` may be given by keyword). Prefer `sum`, `max`, `math.prod` or a loop when
            they fit: they read better.
            """
        ),
        code(
            """
            discount_steps = [0.9, 0.95, 0.98]  # three successive discounts
            final_factor = functools.reduce(operator.mul, discount_steps, 1.0)
            print(f"{final_factor=:.4f}, price after discounts: {round(1000 * final_factor, 2)}")
            print(f"{functools.reduce(operator.add, [], 0)=}  (initial covers empty input)")
            print(f"empty without initial: {raised_error_name(lambda: functools.reduce(operator.add, []))}")
            """
        ),
        md(
            """
            #### `singledispatch`

            Turns a function into a **generic function**: the implementation is chosen by the type
            of the first argument. Register implementations with `@func.register` and a type
            annotation. Subclasses use the nearest registered base class (`bool` → `int`).
            """
        ),
        code(
            '''
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


            print(format_amount(125000), format_amount(Decimal("999.5")), format_amount(True))
            print(f"str: {raised_error_name(lambda: format_amount('12'))}")
            print(f"{sorted(cls.__name__ for cls in format_amount.registry)=}")
            '''
        ),
        md(
            """
            #### `total_ordering`

            Define `__eq__` and **one** of `__lt__`, `__le__`, `__gt__`, `__ge__`; the class
            decorator `total_ordering` adds the other three. (Phase 2 covers the comparison
            methods; dataclasses can do this with `order=True`.)
            """
        ),
        code(
            '''
            @functools.total_ordering
            class Version:
                """A release version compared by its numbers."""

                def __init__(self, text: str) -> None:
                    self.numbers = tuple(int(part) for part in text.split("."))

                def __eq__(self, other: object) -> bool:
                    return isinstance(other, Version) and self.numbers == other.numbers

                def __lt__(self, other: Version) -> bool:
                    return self.numbers < other.numbers


            print(f"{Version('3.15.1') >= Version('3.9.0')=}, {Version('3.12.0') > Version('3.12.1')=}")
            print(f"added: {[name for name in ('__le__', '__gt__', '__ge__') if name in vars(Version)]}")
            '''
        ),
        md(
            """
            #### `update_wrapper`

            `functools.wraps(func)` is shorthand for `functools.update_wrapper(wrapper, func)`.
            Call `update_wrapper` directly when the wrapper is not a `def` you can decorate,
            for example an instance (as in `CallHistory`, 1.12.4) or a function built elsewhere.
            """
        ),
        code(
            '''
            def apply_festival_discount(price: int) -> int:
                """Take 15% off for the festival."""
                return price * 85 // 100


            def generic_wrapper(*args: Any, **kwargs: Any) -> Any:
                return apply_festival_discount(*args, **kwargs)


            print(f"before: {generic_wrapper.__name__=}")
            functools.update_wrapper(generic_wrapper, apply_festival_discount)
            print(f"after:  {generic_wrapper.__name__=}, {generic_wrapper.__doc__=}")
            print(f"{generic_wrapper.__wrapped__ is apply_festival_discount=}, {generic_wrapper(1000)=}")
            '''
        ),
    ]


def _operator_cells() -> list[NotebookNode]:
    """1.12.8 operator."""
    return [
        md(
            """
            ### 1.12.8 `operator`

            The `operator` module exposes Python's operators and lookups as functions, ready to
            pass as `key=` or to `map`, `reduce` and dispatch tables (Unit 1.10.6).

            | Tool | Builds a function equivalent to | Typical use |
            | --- | --- | --- |
            | `itemgetter("price")` | `lambda row: row["price"]` | sort dicts / tuples |
            | `itemgetter(0, 2)` | `lambda row: (row[0], row[2])` | pick several fields |
            | `attrgetter("customer.city")` | `lambda obj: obj.customer.city` | sort objects, dotted paths |
            | `methodcaller("strip", "-")` | `lambda obj: obj.strip("-")` | call a method on each item |
            | `add`, `mul`, `neg`, `contains`, `truth`, … | the matching operator | `reduce`, dispatch tables |

            #### `itemgetter`
            """
        ),
        code(
            """
            products = [
                {"sku": "TEA-500G", "price": 249, "rating": 4.5},
                {"sku": "RICE-5KG", "price": 640, "rating": 4.1},
                {"sku": "SOAP-3PK", "price": 162, "rating": 4.5},
            ]
            by_price = sorted(products, key=operator.itemgetter("price"))
            print([product["sku"] for product in by_price])
            get_sku_and_price = operator.itemgetter("sku", "price")
            print([get_sku_and_price(product) for product in products])
            """
        ),
        md(
            """
            #### `attrgetter` (with dotted paths)

            `attrgetter("customer.city")` follows the dots, like `obj.customer.city`. Several
            names give a tuple, which makes a multi-level sort key.
            """
        ),
        code(
            """
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
            by_city_then_amount = sorted(purchases, key=operator.attrgetter("customer.city", "amount"))
            print([purchase.order_id for purchase in by_city_then_amount])
            print(f"{operator.attrgetter('customer.name')(purchases[0])=}")
            """
        ),
        md(
            """
            #### `methodcaller`

            `methodcaller(name, *args)` builds a function that calls `obj.name(*args)` on whatever
            it receives.
            """
        ),
        code(
            """
            raw_codes = ["--tea--", "-rice-", "soap---"]
            strip_dashes = operator.methodcaller("strip", "-")
            print(list(map(strip_dashes, raw_codes)))
            print(list(map(operator.methodcaller("upper"), raw_codes)))
            """
        ),
        md(
            """
            #### Operator functions

            Every operator has a function: arithmetic (`add`, `mul`, `truediv`, `neg`),
            comparison (`lt`, `eq`), membership (`contains`), truth (`truth`, `not_`), indexing
            (`getitem`) and calling (`call`, *New in 3.11*). The last line pairs two lists
            with `map(..., strict=True)` (*New in 3.14*, Unit 1.9.4).
            """
        ),
        code(
            """
            print(f"{operator.add(249, 640)=}, {operator.mul(3, 249)=}, {operator.neg(50)=}")
            print(f"{operator.lt(162, 249)=}, {operator.contains(['tea', 'rice'], 'tea')=}")
            print(f"{operator.truth([])=}, {operator.getitem({'sku': 'TEA'}, 'sku')=}")
            print(f"{operator.call(max, 3, 9, 4)=}")
            print(f"{list(map(operator.mul, [249, 640], [2, 1], strict=True))=}  (line totals)")
            """
        ),
        md(
            """
            **Speed vs `lambda`.** `itemgetter` / `attrgetter` are implemented in C, so they are
            usually faster than the equivalent `lambda` as a sort key, and they can be pickled
            (useful with multiprocessing, Phase 5). Timings vary by machine and version.
            """
        ),
        code(
            """
            many_rows = [(index % 97, index) for index in range(50_000)]
            lambda_seconds = min(
                timeit.repeat(lambda: sorted(many_rows, key=lambda row: row[0]), number=10, repeat=5)
            )
            getter_seconds = min(
                timeit.repeat(lambda: sorted(many_rows, key=operator.itemgetter(0)), number=10, repeat=5)
            )
            print(f"lambda key: {lambda_seconds * 1000:.1f} ms, itemgetter: {getter_seconds * 1000:.1f} ms")
            print(f"itemgetter speed-up: {lambda_seconds / getter_seconds:.2f}x  (varies by machine)")
            """
        ),
    ]


def _frame_cells() -> list[NotebookNode]:
    """1.12.9 Frames and the call stack."""
    return [
        md(
            """
            ### 1.12.9 Frames and the call stack

            Every function call creates a **frame object**: the running state of one call.
            Frames link to their caller, forming the call stack.

            | Attribute | Holds |
            | --- | --- |
            | `f_code` | the code object being run (`co_name`, `co_filename`, …) |
            | `f_locals` | the local variables (a write-through `FrameLocalsProxy`, *New in 3.13*) |
            | `f_back` | the caller's frame (`None` at the bottom) |
            | `f_lineno` | the line currently executing |
            | `f_globals` | the module namespace |

            `sys._getframe()` returns the current frame (the underscore marks it as CPython
            specific, but it is widely used); `sys._getframe(1)` the caller's.
            """
        ),
        code(
            '''
            def checkout(cart_total: int) -> None:
                """Inspect the current frame and its caller."""
                current_frame = sys._getframe()
                print(f"  {current_frame.f_code.co_name=}")
                print(f"  {sorted(current_frame.f_locals)=}, {current_frame.f_locals['cart_total']=}")
                print(f"  {current_frame.f_lineno=} (line inside this cell)")
                print(f"  {current_frame.f_back.f_code.co_name=}")
                print(f"  {type(current_frame.f_locals).__name__=}")


            def place_order() -> None:
                """Caller of checkout."""
                checkout(cart_total=889)


            place_order()
            '''
        ),
        md(
            """
            Since 3.13 (PEP 667), `frame.f_locals` inside a function is a **write-through proxy**:
            assigning through it changes the real local variable. (Contrast `locals()`, which is
            a snapshot, Unit 1.11.1.) Debuggers rely on this.
            """
        ),
        code(
            '''
            def adjust_through_frame() -> int:
                """Change a local through the frame's f_locals proxy."""
                discount_percent = 10
                sys._getframe().f_locals["discount_percent"] = 25
                return discount_percent


            print(f"{adjust_through_frame()=}")
            '''
        ),
        md(
            """
            Following `f_back` walks up the stack. The next cell walks three levels and prints the
            function names (the frames below this cell belong to Jupyter, so the walk stops after
            four).
            """
        ),
        code(
            '''
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
            '''
        ),
        md(
            """
            **`inspect.stack()`** returns a list of `FrameInfo` records (frame, filename, line
            number, function name, source line) from the current frame outward. It is slower
            than `sys._getframe` because it reads source lines.
            """
        ),
        code(
            '''
            def who_called_me() -> list[str]:
                """Return function name and line of the innermost frames."""
                return [f"{info.function}:{info.lineno}" for info in inspect.stack()[:3]]


            def handle_request() -> list[str]:
                return who_called_me()


            print(handle_request())
            print(f"{type(inspect.stack()[0]).__name__=}")
            '''
        ),
        md(
            """
            **`traceback.extract_stack()`** returns lightweight `FrameSummary` records
            (filename, line number, name, source line), **outermost first**, without keeping the
            frames alive. It is what you would log; a traceback printed after an exception has
            the same shape.
            """
        ),
        code(
            '''
            def record_stack() -> list[str]:
                """Return the innermost three stack entries, outermost first."""
                return [f"{summary.name}:{summary.line}" for summary in traceback.extract_stack()[-3:]]


            def process_payment() -> list[str]:
                return record_stack()


            for entry in process_payment():
                print(f"  {entry}")
            '''
        ),
        md(
            """
            **JS bridge: execution contexts.** The ideas map one to one:

            | JavaScript | Python |
            | --- | --- |
            | execution context | frame object |
            | call stack | chain of frames via `f_back` |
            | lexical environment / variable environment | `f_locals` (+ cells for closures) |
            | global execution context | the module frame (`<module>`) and `f_globals` |
            | `new Error().stack` (a string) | `traceback.extract_stack()` (structured records) |
            | `RangeError: Maximum call stack size exceeded` | `RecursionError` (1.12.10) |
            """
        ),
    ]


def _recursion_cells() -> list[NotebookNode]:
    """1.12.10 Recursion limits."""
    return [
        md(
            """
            ### 1.12.10 Recursion limits

            Each Python-level call adds a frame. CPython limits the depth with a counter,
            `sys.getrecursionlimit()` (default 1000), and raises `RecursionError` when it is
            exceeded, instead of crashing the process.
            """
        ),
        code(
            '''
            def nesting_depth(levels: int) -> int:
                """Recurse levels times."""
                return 0 if levels == 0 else 1 + nesting_depth(levels - 1)


            print(f"{sys.getrecursionlimit()=}")
            print(f"{nesting_depth(900)=}")
            try:
                nesting_depth(5_000)
            except RecursionError as error:
                print(f"{type(error).__name__}: {error}")
            '''
        ),
        md(
            """
            **No tail-call optimization.** Even when the recursive call is the very last thing a
            function does (a tail call), CPython keeps every frame: tracebacks stay complete,
            which Guido van Rossum considered more important. A tail-recursive loop over 5 000
            items still fails.
            """
        ),
        code(
            '''
            def sum_tail_recursive(numbers: list[int], index: int = 0, running_total: int = 0) -> int:
                """Tail-recursive sum: the recursive call is the last operation."""
                if index == len(numbers):
                    return running_total
                return sum_tail_recursive(numbers, index + 1, running_total + numbers[index])


            print(f"{sum_tail_recursive(list(range(500)))=}")
            print(f"5 000 items: {raised_error_name(lambda: sum_tail_recursive(list(range(5_000))))}")
            '''
        ),
        md(
            """
            `sys.setrecursionlimit(n)` raises the limit. It is a blunt tool: each frame also uses
            C stack in some paths, and a limit far above what the C stack can hold can crash the
            interpreter instead of raising. Change it temporarily and restore it.
            """
        ),
        code(
            """
            original_limit = sys.getrecursionlimit()
            try:
                sys.setrecursionlimit(6_000)
                print(f"{nesting_depth(5_000)=} with limit {sys.getrecursionlimit()}")
            finally:
                sys.setrecursionlimit(original_limit)
            print(f"restored: {sys.getrecursionlimit()=}")
            """
        ),
        md(
            """
            **Explicit-stack rewrites.** The robust fix is to replace the call stack with a
            **list used as a stack** (1.6.13): push the work still to do, pop and process until
            empty. The next cell builds a category tree 10 000 levels deep (by loop, not
            recursion), where the recursive sum fails and the explicit-stack version succeeds.
            """
        ),
        code(
            '''
            def nested_total_recursive(node: int | list[Any]) -> int:
                """Sum all ints in a nested list, recursively."""
                return node if isinstance(node, int) else sum(nested_total_recursive(child) for child in node)


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
            print(f"recursive: {raised_error_name(lambda: nested_total_recursive(deep_tree))}")
            print(f"{nested_total_iterative(deep_tree)=}")
            '''
        ),
    ]


def _introspection_cells() -> list[NotebookNode]:
    """1.12.11 Introspecting callables."""
    return [
        md(
            """
            ### 1.12.11 Introspecting callables

            `inspect.signature(func)` returns a `Signature`: an ordered mapping of `Parameter`
            objects. Each parameter has a `name`, `kind`, `default` and `annotation`;
            `Parameter.empty` marks a missing default or annotation.
            """
        ),
        code(
            '''
            def create_shipment(
                order_id: int, /, city: str, express: bool = False, *, insured_value: float = 0.0
            ) -> str:
                """Create a shipment."""
                return f"{order_id} to {city}"


            shipment_signature = inspect.signature(create_shipment)
            print(f"{shipment_signature=}")
            for parameter in shipment_signature.parameters.values():
                default = "—" if parameter.default is inspect.Parameter.empty else repr(parameter.default)
                annotation_name = parameter.annotation.__name__
                print(f"  {parameter.name:14} {parameter.kind.name:22} default={default:6} {annotation_name=}")
            print(f"{shipment_signature.return_annotation=}")
            '''
        ),
        md(
            """
            **`bind`** maps call arguments to parameter names **without calling** the function,
            exactly as a real call would, and raises `TypeError` for an invalid call.
            **`apply_defaults`** then fills in the parameters that were not given. Frameworks use
            this to validate and inspect calls.
            """
        ),
        code(
            """
            bound_call = shipment_signature.bind(1042, "Pune", insured_value=5000.0)
            print(f"{bound_call.arguments=}")
            bound_call.apply_defaults()
            print(f"after apply_defaults: {bound_call.arguments=}")
            print(f"{bound_call.args=}, {bound_call.kwargs=}")
            print(f"missing city: {raised_error_name(lambda: shipment_signature.bind(1042))}")
            by_name_error = raised_error_name(lambda: shipment_signature.bind(order_id=1, city="Goa"))
            print(f"order_id by name: {by_name_error}  (positional-only)")
            """
        ),
        md(
            """
            **A tiny dependency injector.** FastAPI reads a handler's signature and supplies each
            parameter itself. The core idea fits in one function: look at each parameter's
            **annotation**, find a provider registered for that type, call it, and pass the
            result in. Explicit arguments win; parameters with defaults may be left out.
            """
        ),
        code(
            '''
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
                func: Callable[..., Any], providers: dict[type, Callable[[], Any]], **explicit: Any
            ) -> Any:
                """Call func, building each argument from explicit values or providers by annotation."""
                arguments: dict[str, Any] = {}
                for name, parameter in inspect.signature(func).parameters.items():
                    if name in explicit:
                        arguments[name] = explicit[name]
                    elif parameter.annotation in providers:
                        arguments[name] = providers[parameter.annotation]()
                    elif parameter.default is inspect.Parameter.empty:
                        raise TypeError(f"cannot provide parameter {name!r}")
                return func(**arguments)
            '''
        ),
        md(
            """
            The handler below only declares what it needs; `inject` supplies it. In a test you
            would register a different `Database` provider: that is the whole appeal of
            dependency injection.
            """
        ),
        code(
            '''
            app_providers: dict[type, Callable[[], Any]] = {
                Settings: Settings,
                Database: lambda: Database("sqlite:///shop.db"),
            }


            def order_dashboard(db: Database, settings: Settings, title: str = "Orders") -> str:
                """A handler that declares its dependencies as annotated parameters."""
                return f"{title}: {db.count_orders()} orders, currency {settings.currency}, db={db.url}"


            print(inject(order_dashboard, app_providers))
            print(inject(order_dashboard, app_providers, title="Today"))
            test_providers = {**app_providers, Database: lambda: Database("sqlite:///:memory:")}
            print(inject(order_dashboard, test_providers))
            '''
        ),
    ]


def _lab_cells() -> list[NotebookNode]:
    """Lab 1.12."""
    return [
        md(
            """
            ### Lab 1.12

            Seven exercises. For each, replace the `raise NotImplementedError` in the stub, then
            run the check cell. Until then the checks print FAIL; that is expected.

            > **Note:** exercises 1 and 2 rebuild `timer` and `retry` from 1.12.3 / 1.12.6 with
            > extra hooks for testing. Write them without scrolling back up. The stubs replace
            > the demo versions in this notebook's namespace; later units re-define what they
            > need.

            The next cell defines the check helpers used below: `fake_clock(*readings)` returns a
            clock function that returns the given readings one per call.
            """
        ),
        code(
            '''
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
            '''
        ),
        md(
            """
            #### Exercise 1 — `@timer` with optional arguments

            Write `timer(func=None, /, *, unit="ms", clock=time.perf_counter, report=print)`:

            - works both as `@timer` and as `@timer(unit="s", ...)`;
            - `unit` is `"s"`, `"ms"` or `"us"`; anything else raises `ValueError` **when
              `timer(...)` is called**;
            - each call reads `clock()` before and after, and calls
              `report(f"{func.__name__} took {elapsed:.2f} {unit}")`, then returns the result;
            - keeps the function's metadata (`__name__`, `__wrapped__`).
            """
        ),
        code(
            '''
            def timer(
                func: Callable[..., Any] | None = None,
                /,
                *,
                unit: str = "ms",
                clock: Callable[[], float] = time.perf_counter,
                report: Callable[[str], object] = print,
            ) -> Callable[..., Any]:
                """Report each call's duration. Use as @timer or @timer(unit=..., clock=..., report=...)."""
                raise NotImplementedError("Lab 1.12: implement timer()")
            '''
        ),
        md("Run the checks."),
        code(
            '''
            def timer_with_options() -> tuple[int, list[str]]:
                """@timer(...) with a fake clock: 10.0 s → 10.25 s."""
                messages: list[str] = []

                @timer(unit="ms", clock=fake_clock(10.0, 10.25), report=messages.append)
                def brew_chai(cups: int) -> int:
                    return cups * 150

                return brew_chai(2), messages


            def timer_bare() -> tuple[object, bool, str]:
                """Bare @timer: real clock, printed message."""

                def pack_order() -> str:
                    """Pack it."""
                    return "packed"

                result, printed = captured_stdout(lambda: timer(pack_order)())
                return (
                    result,
                    bool(re.fullmatch(r"pack_order took \\d+\\.\\d{2} ms\\n", printed)),
                    timer(pack_order).__name__,
                )


            run_checks(
                [
                    ("@timer(...) result and message", timer_with_options, (300, ["brew_chai took 250.00 ms"])),
                    ("bare @timer", timer_bare, ("packed", True, "pack_order")),
                    (
                        "seconds",
                        lambda: captured_stdout(lambda: timer(unit="s", clock=fake_clock(1.0, 3.5))(len)("ab"))[
                            1
                        ],
                        "len took 2.50 s\\n",
                    ),
                    ("bad unit", lambda: raised_error_name(lambda: timer(unit="hours")), "ValueError"),
                    ("__wrapped__", lambda: timer(len).__wrapped__ is len, True),
                ]
            )
            '''
        ),
        md(
            """
            #### Exercise 2 — `@retry(times, exceptions, backoff_factor)`

            Write `retry(times=3, exceptions=(Exception,), backoff_factor=0.0, *, sleep=time.sleep)`:

            - call the function up to `times` times in total;
            - when it raises one of `exceptions` and attempts remain, call
              `sleep(backoff_factor * 2 ** (attempt - 1))` (attempt counts from 1), then retry;
            - after the last attempt, re-raise the last exception;
            - other exceptions propagate immediately, with no retry;
            - `times < 1` raises `ValueError` when `retry(...)` is called;
            - use `functools.wraps`.
            """
        ),
        code(
            '''
            def retry(
                times: int = 3,
                exceptions: tuple[type[BaseException], ...] = (Exception,),
                backoff_factor: float = 0.0,
                *,
                sleep: Callable[[float], object] = time.sleep,
            ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
                """Retry on exceptions with exponential backoff."""
                raise NotImplementedError("Lab 1.12: implement retry()")
            '''
        ),
        md(
            """
            Run the checks. `flaky(failures, error)` builds a function that raises `error` for its
            first `failures` calls and then returns `"ok"`; it records each call in `.calls`.
            """
        ),
        code(
            '''
            def flaky(failures: int, error: Exception) -> Callable[[], str]:
                """Return a function that fails failures times, then returns "ok"."""
                calls: list[int] = []

                def unreliable() -> str:
                    calls.append(len(calls) + 1)
                    if len(calls) <= failures:
                        raise error
                    return "ok"

                unreliable.calls = calls
                return unreliable


            def retry_trace(failures: int, times: int, error: Exception) -> tuple[str, int, list[float]]:
                """Return (result or exception name, number of calls, recorded delays)."""
                delays: list[float] = []
                target = flaky(failures, error)
                decorated = retry(times, (ConnectionError,), 0.5, sleep=delays.append)(target)
                outcome = raised_error_name(decorated)
                return ("ok" if outcome == "no error" else outcome), len(target.calls), delays


            run_checks(
                [
                    (
                        "succeeds on third attempt",
                        lambda: retry_trace(2, 3, ConnectionError()),
                        ("ok", 3, [0.5, 1.0]),
                    ),
                    (
                        "gives up and re-raises",
                        lambda: retry_trace(5, 3, ConnectionError()),
                        ("ConnectionError", 3, [0.5, 1.0]),
                    ),
                    (
                        "other exceptions not retried",
                        lambda: retry_trace(5, 3, KeyError("x")),
                        ("KeyError", 1, []),
                    ),
                    ("first try ok", lambda: retry_trace(0, 3, ConnectionError()), ("ok", 1, [])),
                    ("times 0", lambda: raised_error_name(lambda: retry(0)), "ValueError"),
                    ("wraps", lambda: retry(2)(flaky(0, ValueError())).__name__, "unreliable"),
                ]
            )
            '''
        ),
        md(
            """
            #### Exercise 3 — `@count_calls`

            Write `count_calls(func)`: the wrapper has a `call_count` attribute that starts at 0
            and goes up by one on **every** call, even when the function raises. Each decorated
            function has its own count. Keep the metadata.
            """
        ),
        code(
            '''
            def count_calls(func: Callable[..., Any]) -> Callable[..., Any]:
                """Count every call in wrapper.call_count."""
                raise NotImplementedError("Lab 1.12: implement count_calls()")
            '''
        ),
        md("Run the checks."),
        code(
            '''
            def count_calls_trace() -> tuple[int, int, int, str]:
                """Count calls on two functions, one of which raises."""

                @count_calls
                def ping() -> str:
                    return "pong"

                @count_calls
                def fail() -> None:
                    raise RuntimeError("boom")

                start = ping.call_count
                ping()
                ping()
                raised_error_name(fail)
                return start, ping.call_count, fail.call_count, ping.__name__


            run_checks(
                [
                    ("counts, raising calls included", count_calls_trace, (0, 2, 1, "ping")),
                    ("returns the result", lambda: count_calls(max)(3, 9), 9),
                ]
            )
            '''
        ),
        md(
            """
            #### Exercise 4 — `@validate_arguments` using `inspect.signature`

            Write `validate_arguments(func)`: on each call, bind the arguments with
            `inspect.signature(func).bind(*args, **kwargs)` and apply the defaults. For every
            parameter whose annotation is a **class** (`isinstance(annotation, type)`), check the
            value with `isinstance`; parameters without an annotation, or with a non-class
            annotation (such as `list[int]` or `int | None`), are not checked. Careful: the
            "no annotation" marker `inspect.Parameter.empty` is itself a class. On a mismatch
            raise `TypeError(f"{name} must be {annotation.__name__}, got {type(value).__name__}")`.
            An invalid call (missing argument) raises `TypeError` from `bind`.
            """
        ),
        code(
            '''
            def validate_arguments(func: Callable[..., Any]) -> Callable[..., Any]:
                """Check annotated argument types on every call."""
                raise NotImplementedError("Lab 1.12: implement validate_arguments()")
            '''
        ),
        md("Run the checks."),
        code(
            '''
            def make_add_item() -> Callable[..., Any]:
                """A decorated function with checked and unchecked parameters."""

                @validate_arguments
                def add_item(
                    sku: str, quantity: int = 1, *, note: str = "", tags: list[str] | None = None, extra=None
                ) -> str:
                    return f"{quantity} x {sku}"

                return add_item


            def type_error_message(thunk: Callable[[], object]) -> str:
                """Return the TypeError message thunk raises, or 'no error'."""
                try:
                    thunk()
                except TypeError as error:
                    return str(error)
                return "no error"


            run_checks(
                [
                    ("valid call", lambda: make_add_item()("TEA", 2), "2 x TEA"),
                    ("defaults pass", lambda: make_add_item()("TEA"), "1 x TEA"),
                    (
                        "bad positional",
                        lambda: type_error_message(lambda: make_add_item()("TEA", "2")),
                        "quantity must be int, got str",
                    ),
                    (
                        "bad keyword-only",
                        lambda: type_error_message(lambda: make_add_item()("TEA", note=5)),
                        "note must be str, got int",
                    ),
                    (
                        "unchecked annotations",
                        lambda: make_add_item()("TEA", tags="x", extra=object()),
                        "1 x TEA",
                    ),
                    ("missing argument", lambda: raised_error_name(lambda: make_add_item()()), "TypeError"),
                    ("keeps name", lambda: make_add_item().__name__, "add_item"),
                ]
            )
            '''
        ),
        md(
            """
            #### Exercise 5 — `serialize()` with `singledispatch`

            Write a generic function `serialize(value)` that converts a value into something
            `json.dumps` accepts:

            | Input type | Output |
            | --- | --- |
            | `str`, `int`, `float`, `bool`, `None` | unchanged |
            | `Decimal` | `str(value)` |
            | `dt.date` and `dt.datetime` | `value.isoformat()` |
            | `list`, `tuple` | a list, each item serialized |
            | `set`, `frozenset` | a **sorted** list of the serialized items |
            | `dict` | a dict with `str(key)` keys and serialized values |
            | anything else | `TypeError(f"cannot serialize {type(value).__name__}")` |

            Use `@functools.singledispatch` and one `register` per row (no `isinstance` chain).
            """
        ),
        code(
            '''
            @functools.singledispatch
            def serialize(value: object) -> Any:
                """Convert value into JSON-compatible data."""
                raise NotImplementedError("Lab 1.12: implement serialize() and its registrations")
            '''
        ),
        md("Run the checks."),
        code(
            """
            sample_order = {
                "order_id": 1042,
                "placed_on": dt.date(2026, 11, 5),
                "total": Decimal("889.50"),
                "items": ("TEA-500G", "RICE-5KG"),
                "tags": {"gift", "express"},
                "paid": True,
                "coupon": None,
            }
            run_checks(
                [
                    ("Decimal", lambda: serialize(Decimal("249.50")), "249.50"),
                    ("datetime", lambda: serialize(dt.datetime(2026, 11, 5, 9, 30)), "2026-11-05T09:30:00"),
                    ("set sorted", lambda: serialize({3, 1, 2}), [1, 2, 3]),
                    ("dict keys become str", lambda: serialize({1: Decimal("1.5")}), {"1": "1.5"}),
                    (
                        "nested order",
                        lambda: serialize(sample_order),
                        {
                            "order_id": 1042,
                            "placed_on": "2026-11-05",
                            "total": "889.50",
                            "items": ["TEA-500G", "RICE-5KG"],
                            "tags": ["express", "gift"],
                            "paid": True,
                            "coupon": None,
                        },
                    ),
                    ("unsupported type", lambda: raised_error_name(lambda: serialize(object())), "TypeError"),
                    ("uses singledispatch", lambda: Decimal in serialize.registry, True),
                ]
            )
            """
        ),
        md(
            """
            #### Exercise 6 — `call_with_params(func, params)`

            `params` is a dict of **strings**, as they arrive in a URL query string. Call `func`
            with them, converted by the parameters' annotations:

            - for each parameter of `func`: if its name is in `params`, convert the string with
              the annotation when it is `int`, `float` or `bool` (`"true"`, `"1"`, `"yes"` →
              `True`; `"false"`, `"0"`, `"no"` → `False`, case-insensitive; anything else
              raises `ValueError`), otherwise pass the string through;
            - if the name is missing and the parameter has a default, leave it out;
            - if it is missing and has no default, raise
              `TypeError(f"missing required parameter: {name}")`;
            - keys in `params` that are not parameters are ignored.
            """
        ),
        code(
            '''
            def call_with_params(func: Callable[..., Any], params: dict[str, str]) -> Any:
                """Call func with string params converted by its annotations."""
                raise NotImplementedError("Lab 1.12: implement call_with_params()")
            '''
        ),
        md("Run the checks."),
        code(
            '''
            def search_products(
                query: str, page: int = 1, max_price: float = 1e9, in_stock: bool = False
            ) -> tuple[Any, ...]:
                """A handler with typed query parameters."""
                return query, page, max_price, in_stock


            def missing_message() -> str:
                """Return the TypeError message for a missing required parameter."""
                try:
                    call_with_params(search_products, {"page": "2"})
                except TypeError as error:
                    return str(error)
                return "no error"


            run_checks(
                [
                    (
                        "converts",
                        lambda: call_with_params(
                            search_products,
                            {"query": "tea", "page": "2", "max_price": "499.5", "in_stock": "Yes"},
                        ),
                        ("tea", 2, 499.5, True),
                    ),
                    (
                        "defaults",
                        lambda: call_with_params(search_products, {"query": "rice"}),
                        ("rice", 1, 1e9, False),
                    ),
                    (
                        "extra keys ignored",
                        lambda: call_with_params(search_products, {"query": "x", "utm_source": "ad"}),
                        ("x", 1, 1e9, False),
                    ),
                    (
                        "bool false",
                        lambda: call_with_params(search_products, {"query": "x", "in_stock": "0"})[3],
                        False,
                    ),
                    ("missing required", missing_message, "missing required parameter: query"),
                    (
                        "bad int",
                        lambda: raised_error_name(
                            lambda: call_with_params(search_products, {"query": "x", "page": "two"})
                        ),
                        "ValueError",
                    ),
                    (
                        "bad bool",
                        lambda: raised_error_name(
                            lambda: call_with_params(search_products, {"query": "x", "in_stock": "maybe"})
                        ),
                        "ValueError",
                    ),
                ]
            )
            '''
        ),
        md(
            """
            #### Exercise 7 — a mini router with typed path parameters

            Write a `Router` class:

            - `router.get(path_template)` and `router.post(path_template)` are decorator factories
              that register the handler and **return it unchanged**;
            - a template is split on `/`; a segment like `{user_id}` captures that part of the
              path, other segments must match exactly;
            - `router.dispatch(method, path)` finds the **first** registered route whose method
              and segments match, converts each captured value with the handler parameter's
              annotation (`int`, `float` or `str`), and returns `handler(**captured)`;
            - a route whose conversion fails (`"/users/abc"` for an `int`) does not match;
            - when nothing matches, raise `LookupError(f"no route for {method} {path}")`.
            """
        ),
        code(
            '''
            class Router:
                """Register handlers with @router.get / @router.post and dispatch paths to them."""

                def __init__(self) -> None:
                    raise NotImplementedError("Lab 1.12: implement Router")

                def get(self, path_template: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
                    raise NotImplementedError

                def post(self, path_template: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
                    raise NotImplementedError

                def dispatch(self, method: str, path: str) -> Any:
                    raise NotImplementedError
            '''
        ),
        md("Run the checks. `make_shop_router()` registers four routes."),
        code(
            '''
            def make_shop_router() -> Router:
                """A router with literal, typed and multi-parameter routes."""
                router = Router()

                @router.get("/health")
                def health() -> dict[str, str]:
                    return {"status": "ok"}

                @router.get("/users/{user_id}")
                def get_user(user_id: int) -> dict[str, Any]:
                    return {"user_id": user_id, "type": type(user_id).__name__}

                @router.get("/users/{user_id}/orders/{order_code}")
                def get_order(user_id: int, order_code: str) -> tuple[int, str]:
                    return user_id, order_code

                @router.post("/users/{user_id}")
                def update_user(user_id: int) -> str:
                    return f"updated {user_id}"

                return router


            def decorator_returns_handler() -> bool:
                """router.get(...) must return the original function."""

                def handler() -> None:
                    return None

                return Router().get("/x")(handler) is handler


            run_checks(
                [
                    ("literal route", lambda: make_shop_router().dispatch("GET", "/health"), {"status": "ok"}),
                    (
                        "typed param",
                        lambda: make_shop_router().dispatch("GET", "/users/42"),
                        {"user_id": 42, "type": "int"},
                    ),
                    (
                        "two params",
                        lambda: make_shop_router().dispatch("GET", "/users/7/orders/A-19"),
                        (7, "A-19"),
                    ),
                    ("method matters", lambda: make_shop_router().dispatch("POST", "/users/7"), "updated 7"),
                    (
                        "conversion failure is 404",
                        lambda: raised_error_name(lambda: make_shop_router().dispatch("GET", "/users/abc")),
                        "LookupError",
                    ),
                    (
                        "unknown path",
                        lambda: raised_error_name(lambda: make_shop_router().dispatch("GET", "/admin")),
                        "LookupError",
                    ),
                    (
                        "segment count matters",
                        lambda: raised_error_name(lambda: make_shop_router().dispatch("GET", "/users/7/x")),
                        "LookupError",
                    ),
                    ("decorator returns handler", decorator_returns_handler, True),
                ]
            )
            '''
        ),
    ]


def _recap_cells() -> list[NotebookNode]:
    """Recap for Unit 1.12."""
    return [
        md(
            """
            ### Recap — Unit 1.12

            | Concept | One-line takeaway | JS equivalent |
            | --- | --- | --- |
            | `@decorator` | `f = decorator(f)`, run once when the `def` runs (import time) | higher-order function call |
            | Stacking | Applied bottom-up, wrappers run top-down | `a(b(fn))` |
            | Wrapper shape | `*args, **kwargs`, call, **return the result** | rest/spread wrapper |
            | `functools.wraps` | Copies name/doc/annotations, sets `__wrapped__`; signature survives | — |
            | Factories | `@retry(times=3)` = three levels: options → decorator → wrapper | decorator factories |
            | Optional arguments | `func=None, /, *, options`: works as `@timer` and `@timer(unit="s")` | — |
            | State | Function attributes, closures (`nonlocal`) or a class with `__call__` | closure state |
            | Method trap | Class-based decorators need `__get__` to bind `self` | `this` binding |
            | Class decorators | Receive the class; registries, added methods (`@dataclass`) | class decorators |
            | Gallery | `timer`, `retry` (backoff + filter), `log_calls`, `require_role`, `validate_types`, `register`, `deprecated`, `memoize`, `@app.get` | Express middleware/routes |
            | `functools` | `partial`, `partialmethod`, `cache`, `lru_cache`, `cached_property`, `reduce`, `singledispatch`, `total_ordering`, `update_wrapper` | `bind`, memoize, `reduce` |
            | `lru_cache` caveats | Arguments must be hashable; on methods it keeps instances alive | — |
            | `operator` | `itemgetter`, `attrgetter` (dotted), `methodcaller`, operator functions; faster than `lambda` | arrow functions |
            | Frames | `sys._getframe()`, `f_code`, `f_locals` (write-through proxy), `f_back`, `f_lineno` | execution contexts |
            | Stack views | `inspect.stack()` (FrameInfo), `traceback.extract_stack()` (FrameSummary) | `new Error().stack` |
            | Recursion | Limit ~1000, `RecursionError`, no tail calls; rewrite with an explicit stack | `RangeError` |
            | `inspect.signature` | `Parameter` kinds/defaults/annotations, `bind`, `apply_defaults`; basis of DI | `fn.length` (much less) |

            **Further reading**

            - [Glossary: decorator](https://docs.python.org/3/glossary.html#term-decorator),
              [function definitions (decorators)](https://docs.python.org/3/reference/compound_stmts.html#function-definitions),
              [class definitions](https://docs.python.org/3/reference/compound_stmts.html#class-definitions)
            - [`functools`](https://docs.python.org/3/library/functools.html),
              [`operator`](https://docs.python.org/3/library/operator.html),
              [`inspect`](https://docs.python.org/3/library/inspect.html),
              [`traceback`](https://docs.python.org/3/library/traceback.html),
              [`warnings.deprecated`](https://docs.python.org/3/library/warnings.html#warnings.deprecated)
            - [`sys._getframe`](https://docs.python.org/3/library/sys.html#sys._getframe),
              [`sys.setrecursionlimit`](https://docs.python.org/3/library/sys.html#sys.setrecursionlimit),
              [frame objects](https://docs.python.org/3/reference/datamodel.html#frame-objects)
            - [PEP 318 — Decorators for functions and methods](https://peps.python.org/pep-0318/),
              [PEP 3129 — Class decorators](https://peps.python.org/pep-3129/),
              [PEP 614 — Relaxing grammar restrictions on decorators](https://peps.python.org/pep-0614/)
            - [PEP 443 — Single-dispatch generic functions](https://peps.python.org/pep-0443/),
              [PEP 362 — Function signature object](https://peps.python.org/pep-0362/),
              [PEP 612 — Parameter specification variables](https://peps.python.org/pep-0612/)
            - [PEP 667 — Consistent views of namespaces](https://peps.python.org/pep-0667/),
              [PEP 702 — Marking deprecations](https://peps.python.org/pep-0702/)
            """
        ),
    ]


def cells() -> list[NotebookNode]:
    """Return the cells for Unit 1.12 and Lab 1.12."""
    return [
        *_overview_cells(),
        *_mechanics_cells(),
        *_writing_cells(),
        *_factory_cells(),
        *_stateful_cells(),
        *_methods_classes_cells(),
        *_gallery_cells(),
        *_functools_cells(),
        *_operator_cells(),
        *_frame_cells(),
        *_recursion_cells(),
        *_introspection_cells(),
        *_lab_cells(),
        *_recap_cells(),
    ]
