"""Unit 1.10 — Functions: Definition and Arguments (with Lab 1.10)."""

from nbformat import NotebookNode

from nb_builder import code, md, predict_cells

UNIT_SETUP_SOURCE = '''
import datetime as dt
import dis
import inspect
import math
import operator
import sys
import traceback
from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode  # noqa: F401 (used in Lab 1.10)


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


def compile_error(source: str) -> str:
    """Compile source without running it; return "SyntaxError: <message>" or "compiles"."""
    try:
        compile(source, "<demo>", "exec")
    except SyntaxError as error:
        return f"SyntaxError: {error.msg}"
    return "compiles"


print(f"{sys.version_info[:2]=}")
'''


def _overview_cells() -> list[NotebookNode]:
    """Unit opener and setup."""
    return [
        md(
            """
            ## Unit 1.10 — Functions: Definition and Arguments

            **Objectives**

            - Explain that `def` runs at run time and builds a function object with inspectable
              attributes.
            - Use every parameter kind (positional-only, standard, `*args`, keyword-only,
              `**kwargs`), in the right order, and read them with `inspect.signature`.
            - Forward arguments with `*` / `**`, and avoid the mutable-default trap.
            - Pass functions around: callbacks, dispatch tables, `lambda`.
            - Write PEP 257 docstrings and annotations, and know what annotations do **not** do.
            - Write a recursive function with a base case, and know the recursion limit.

            **JS bridge**

            | JavaScript concept | Python equivalent | The difference that bites |
            | --- | --- | --- |
            | `function f() {}` is hoisted | `def f():` runs when reached | Calling before the `def` raises `NameError` |
            | `return;` / no return → `undefined` | no return → `None` | |
            | `function f(a, b = 2)` | `def f(a, b=2):` | Python evaluates the default **once**, at definition |
            | `function f(...args)` | `def f(*args):` | `args` is a **tuple** |
            | `function f({ page, size })` | `def f(*, page, size):` | Keyword-only parameters, no object needed |
            | — | `def f(x, /):` | Positional-only parameters |
            | `f(...values)` | `f(*values)`, `f(**options)` | `**` unpacks a dict into keyword arguments |
            | `(x) => x * 2` | `lambda x: x * 2` | One expression only; no statements |
            | JSDoc / TypeScript types | docstrings and annotations | Annotations are **not** checked at run time |
            | `f.name`, `f.length` | `f.__name__`, `inspect.signature(f)` | Many more attributes (`__defaults__`, `__code__`, …) |

            The next cell is this unit's setup (`compile_error` is the helper from Unit 1.8).
            """
        ),
        code(UNIT_SETUP_SOURCE),
    ]


def _def_cells() -> list[NotebookNode]:
    """1.10.1 def is an executable statement."""
    return [
        md(
            """
            ### 1.10.1 `def` is an executable statement

            `def name(...):` is a statement that **runs**: it builds a function object from
            the compiled body and binds it to `name`. Until that line has run, the name does not
            exist. There is no hoisting, unlike JavaScript function declarations.

            The next cell runs a small module in a fresh namespace (so earlier notebook cells
            cannot interfere): the call before the `def` fails, the call after it works.
            """
        ),
        code(
            '''
            module_source = """
            print(greet("asha"))

            def greet(name):
                return f"hello {name}"
            """
            try:
                exec(module_source, {})
            except NameError as error:
                print(f"{type(error).__name__}: {error}")

            fixed_namespace: dict[str, Any] = {}
            exec("def greet(name):\\n    return name\\nresult = greet('asha')", fixed_namespace)
            print(f"{fixed_namespace['result']=}")
            '''
        ),
        md(
            """
            #### Under the hood: `MAKE_FUNCTION`

            The bytecode of a `def` shows it: the body was compiled ahead of time into a code
            object (a constant), and at run time `MAKE_FUNCTION` wraps it into a function object,
            which `STORE_NAME` binds to the name. Opcode names vary by version.
            """
        ),
        code(
            """
            definition_code = compile("def greet(name):\\n    return name\\n", "<demo>", "exec")
            for instruction in dis.get_instructions(definition_code):
                if inspect.iscode(instruction.argval):
                    detail = f"<code object {instruction.argval.co_name}>"  # no address printed
                else:
                    detail = instruction.argrepr
                print(f"{instruction.opname:16} {detail}")
            """
        ),
        md(
            """
            Because `def` is a statement, it can sit inside an `if`: **conditional definitions**
            pick an implementation once, at import time. Defining the same name twice simply
            rebinds it; the last definition wins.
            """
        ),
        code(
            '''
            if sys.version_info >= (3, 15):

                def describe_runtime() -> str:
                    """Implementation for new interpreters."""
                    return "3.15+ implementation"

            else:

                def describe_runtime() -> str:
                    """Fallback implementation."""
                    return "fallback implementation"


            def price_label(price: int) -> str:
                """First version."""
                return f"Rs {price}"


            def price_label(price: int) -> str:  # rebinding the name; the first object is gone
                """Second version."""
                return f"₹{price}"


            print(f"{describe_runtime()=}, {price_label(249)=}")
            '''
        ),
        md(
            """
            **Function attributes.** A function is an object like any other, with attributes:

            | Attribute | Holds |
            | --- | --- |
            | `__name__` | the name given in `def` |
            | `__qualname__` | the dotted path from the module (`Class.method`, `outer.<locals>.inner`) |
            | `__doc__` | the docstring, or `None` |
            | `__defaults__` | tuple of default values for positional parameters, or `None` |
            | `__kwdefaults__` | dict of defaults for keyword-only parameters, or `None` |
            | `__code__` | the compiled code object (bytecode, variable names, argument counts) |
            | `__globals__` | the module namespace the function looks up global names in |
            | `__annotations__` | dict of parameter and return annotations |
            | `__dict__` | arbitrary attributes you attach yourself |

            The next cell defines one function used by every attribute demo below.
            """
        ),
        code(
            '''
            def apply_discount(price: float, percent: float = 10, *, round_to: int = 2) -> float:
                """Return price reduced by percent, rounded to round_to decimal places."""
                discounted_price = price * (100 - percent) / 100
                return round(discounted_price, round_to)


            print(f"{apply_discount(249)=}, {apply_discount(249, 50, round_to=0)=}")
            '''
        ),
        md(
            "**`__name__`**: the name from the `def` line (it does not change if you assign the function to another name)."
        ),
        code(
            """
            discount_function = apply_discount
            print(f"{apply_discount.__name__=}, {discount_function.__name__=}")
            """
        ),
        md("**`__qualname__`**: the qualified name, showing where the function was defined."),
        code(
            '''
            class Checkout:
                """A class with one method, to show qualified names."""

                def total(self) -> int:
                    """Return a fixed total."""
                    return 0


            def make_formatter() -> Callable[[int], str]:
                """Return a nested function."""

                def format_price(price: int) -> str:
                    """Format a price in rupees."""
                    return f"₹{price}"

                return format_price


            print(f"{apply_discount.__qualname__=}")
            print(f"{Checkout.total.__qualname__=}")
            print(f"{make_formatter().__qualname__=}")
            '''
        ),
        md(
            "**`__doc__`**: the docstring (the first statement of the body, if it is a string literal)."
        ),
        code(
            """
            def no_docstring() -> None:
                pass


            print(f"{apply_discount.__doc__=}")
            print(f"{make_formatter().__doc__=}, {no_docstring.__doc__=}")
            """
        ),
        md(
            "**`__defaults__`**: defaults of the positional parameters, as a tuple aligned to the *last* ones."
        ),
        code(
            """
            print(f"{apply_discount.__defaults__=}  (percent=10)")
            """
        ),
        md("**`__kwdefaults__`**: defaults of the keyword-only parameters, as a dict."),
        code(
            """
            print(f"{apply_discount.__kwdefaults__=}")
            """
        ),
        md(
            "**`__code__`**: the code object: argument counts, local variable names, the bytecode itself."
        ),
        code(
            """
            discount_code = apply_discount.__code__
            print(f"{discount_code.co_argcount=}, {discount_code.co_kwonlyargcount=}")
            print(f"{discount_code.co_varnames=}")
            print(f"{len(discount_code.co_code) > 0=}  (raw bytecode bytes)")
            """
        ),
        md(
            "**`__globals__`**: the namespace of the module where the function was defined; here, the notebook's globals."
        ),
        code(
            """
            print(f"{apply_discount.__globals__ is globals()=}")
            print(f"{'apply_discount' in apply_discount.__globals__=}")
            """
        ),
        md("**`__annotations__`**: the annotations, by parameter name, plus `'return'`."),
        code(
            """
            print(f"{apply_discount.__annotations__=}")
            """
        ),
        md(
            "**`__dict__`**: attributes you attach yourself (version tags, counters, registry flags)."
        ),
        code(
            """
            apply_discount.version = 2
            apply_discount.owner = "pricing-team"
            print(f"{apply_discount.__dict__=}, {apply_discount.version=}")
            """
        ),
    ]


def _return_cells() -> list[NotebookNode]:
    """1.10.2 Return values."""
    return [
        md(
            """
            ### 1.10.2 Return values

            **Implicit `None`**: a function without `return`, or with a bare `return`, returns
            `None`. Methods that change an object in place follow this convention (`list.sort()`,
            `list.append()`, `dict.update()`), so `items = items.sort()` loses the list.
            """
        ),
        code(
            '''
            def log_order(order_id: int) -> None:
                """Print a log line; no return statement."""
                print(f"  order {order_id} logged")


            log_result = log_order(1001)
            print(f"{log_result=}")
            product_names = ["tea", "rice"]
            sort_result = product_names.sort()
            print(f"{sort_result=}  (sort works in place and returns None)")
            '''
        ),
        md(
            """
            **Returning several values**: `return a, b` returns **one tuple**; the caller unpacks
            it. For more than two or three values, return a `NamedTuple` (1.5.6) or a dataclass
            (Phase 2) so the fields have names.
            """
        ),
        code(
            '''
            def price_range(prices: list[int]) -> tuple[int, int]:
                """Return the lowest and highest price."""
                return min(prices), max(prices)


            range_result = price_range([249, 80, 640])
            lowest_price, highest_price = price_range([249, 80, 640])
            print(f"{range_result=}, {type(range_result).__name__=}")
            print(f"{lowest_price=}, {highest_price=}")
            '''
        ),
        md(
            """
            **Guard clauses** (1.8.3) are early returns: deal with invalid or trivial input
            first, so the rest of the function handles only the normal case.
            """
        ),
        code(
            '''
            def average_order_value(order_totals: list[float]) -> float | None:
                """Return the mean order total, or None for no orders."""
                if not order_totals:
                    return None
                if any(total < 0 for total in order_totals):
                    raise ValueError("order totals cannot be negative")
                return sum(order_totals) / len(order_totals)


            print(f"{average_order_value([])=}, {average_order_value([100, 250])=}")
            print(f"negative: {raised_error_name(lambda: average_order_value([-5]))}")
            '''
        ),
    ]


def _parameter_cells() -> list[NotebookNode]:
    """1.10.3 Parameter kinds."""
    return [
        md(
            """
            ### 1.10.3 Parameter kinds

            | Kind | Syntax | Caller may pass | `inspect` kind |
            | --- | --- | --- | --- |
            | Positional-only | before `/` | by position only | `POSITIONAL_ONLY` |
            | Positional-or-keyword | plain names | by position or by name | `POSITIONAL_OR_KEYWORD` |
            | Default value | `name=value` | may be omitted | (any kind) |
            | Variadic positional | `*args` | any number of extra positionals → a **tuple** | `VAR_POSITIONAL` |
            | Keyword-only | after `*` or `*args` | by name only | `KEYWORD_ONLY` |
            | Variadic keyword | `**kwargs` | any number of extra keywords → a **dict** | `VAR_KEYWORD` |

            **Positional-or-keyword** (the default kind): the caller chooses. Passing the same
            parameter twice is a `TypeError`.
            """
        ),
        code(
            '''
            def format_greeting(name: str, greeting: str) -> str:
                """Greet name with greeting."""
                return f"{greeting}, {name}!"


            print(format_greeting("Asha", "Namaste"))
            print(format_greeting(greeting="Hello", name="Ravi"))
            print(f"twice: {raised_error_name(lambda: format_greeting('Asha', name='Ravi'))}")
            '''
        ),
        md(
            """
            **Defaults** make a parameter optional. Parameters with defaults must come after
            those without (among the positional ones).
            """
        ),
        code(
            '''
            def add_gst(amount: float, rate_percent: float = 18) -> float:
                """Add GST at rate_percent (default 18%)."""
                return round(amount * (1 + rate_percent / 100), 2)


            print(f"{add_gst(100)=}, {add_gst(100, 5)=}, {add_gst(100, rate_percent=28)=}")
            print(f"{compile_error('def broken(rate=18, amount): pass')=}")
            '''
        ),
        md("**`*args`** collects any extra positional arguments into a **tuple**."),
        code(
            '''
            def order_total(*line_amounts: float) -> float:
                """Sum any number of line amounts."""
                print(f"  {line_amounts=}, {type(line_amounts).__name__=}")
                return sum(line_amounts)


            print(f"{order_total(249, 640)=}")
            print(f"{order_total()=}")
            '''
        ),
        md(
            """
            **Keyword-only parameters** come after `*` (or after `*args`). They must be passed by
            name, which keeps call sites readable for flags and options: `is_admin=True` instead
            of a bare `True`.
            """
        ),
        code(
            '''
            def create_user(name: str, *, is_admin: bool = False, send_welcome: bool = True) -> str:
                """Create a user; the flags must be named."""
                return f"{name} (admin={is_admin}, welcome={send_welcome})"


            print(create_user("asha", is_admin=True))
            print(f"positional flag: {raised_error_name(lambda: create_user('asha', True))}")
            '''
        ),
        md(
            """
            **Positional-only parameters** come before `/` (PEP 570, Python 3.8). The caller cannot
            use their names, so the author can rename them later without breaking anyone, and
            the names stay free for `**kwargs`. Many built-ins work this way: `len(obj, /)`,
            `divmod(x, y, /)`.
            """
        ),
        code(
            '''
            def distance_km(start_km: float, end_km: float, /) -> float:
                """Distance between two markers on a highway."""
                return abs(end_km - start_km)


            print(f"{distance_km(12.5, 40.0)=}")
            print(f"by name: {raised_error_name(lambda: distance_km(start_km=1, end_km=2))}")
            print(f"len by name: {raised_error_name(lambda: len(obj=[1, 2]))}")
            '''
        ),
        md(
            "**`**kwargs`** collects any extra keyword arguments into a **dict** (insertion-ordered, PEP 468)."
        ),
        code(
            '''
            def log_event(event_name: str, **fields: object) -> str:
                """Format an event with arbitrary named fields."""
                print(f"  {fields=}, {type(fields).__name__=}")
                return " ".join([event_name, *(f"{key}={value}" for key, value in fields.items())])


            print(log_event("checkout", user="asha", total=889, coupon=None))
            '''
        ),
        md(
            """
            **The full signature order** is fixed:

            ```python
            def f(pos_only, /, standard, *, kw_only, **kwargs): ...
            def g(pos_only, /, standard=1, *args, kw_only, kw_with_default=2, **kwargs): ...
            ```

            Why each kind exists:

            | Kind | Use it when |
            | --- | --- |
            | Positional-only | the name means nothing to callers (`x`, `obj`), may change, or must not clash with `**kwargs` |
            | Positional-or-keyword | the ordinary case |
            | `*args` | the function naturally takes "any number of" things (`print`, `max`) |
            | Keyword-only | options and boolean flags, so call sites say what they mean |
            | `**kwargs` | forwarding to another function, or open-ended named fields |

            The next cell calls the full form and shows where each argument lands.
            """
        ),
        code(
            '''
            def every_kind(
                pos_only: object,
                /,
                standard: object = 1,
                *args: object,
                kw_only: object,
                kw_with_default: object = 2,
                **kwargs: object,
            ) -> dict[str, object]:
                """Return how the arguments were bound."""
                return {
                    "pos_only": pos_only,
                    "standard": standard,
                    "args": args,
                    "kw_only": kw_only,
                    "kw_with_default": kw_with_default,
                    "kwargs": kwargs,
                }


            print(every_kind("a", "b", "c", "d", kw_only="e", extra="f"))
            print(every_kind("a", kw_only="e", pos_only="goes into kwargs"))
            '''
        ),
        md(
            """
            The last call shows the positional-only benefit: `pos_only="..."` is not a duplicate,
            it lands in `**kwargs`.

            **Reading kinds with `inspect.signature`**: frameworks (FastAPI in Phase 6, pytest
            fixtures in Phase 4) inspect signatures to decide what to pass.
            """
        ),
        code(
            """
            for parameter in inspect.signature(every_kind).parameters.values():
                default = "—" if parameter.default is inspect.Parameter.empty else parameter.default
                print(f"{parameter.name:16} {parameter.kind.name:22} default={default}")
            print(f"{inspect.signature(divmod)=}")
            """
        ),
    ]


def _unpacking_cells() -> list[NotebookNode]:
    """1.10.4 Argument unpacking."""
    return [
        md(
            """
            ### 1.10.4 Argument unpacking

            At a **call**, `*sequence` spreads items into positional arguments and `**mapping`
            spreads key/value pairs into keyword arguments (1.8.7). It is how you call a function
            with arguments you built as data.
            """
        ),
        code(
            '''
            def ship_parcel(weight_kg: float, destination: str, *, express: bool = False) -> str:
                """Describe a shipment."""
                return f"{weight_kg} kg to {destination} ({'express' if express else 'standard'})"


            parcel_values = [2.5, "Pune"]
            parcel_options = {"express": True}
            print(ship_parcel(*parcel_values, **parcel_options))
            print(f"unknown option: {raised_error_name(lambda: ship_parcel(*parcel_values, gift=True))}")
            '''
        ),
        md(
            """
            **The forwarding wrapper**: `def wrapper(*args, **kwargs)` accepts **any** arguments
            and passes them on unchanged with `func(*args, **kwargs)`. It is the shape of every
            decorator (Unit 1.12).
            """
        ),
        code(
            '''
            def call_logged(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
                """Call func with the given arguments and log the call and its result."""
                result = func(*args, **kwargs)
                print(f"  {func.__name__}(args={args}, kwargs={kwargs}) -> {result!r}")
                return result


            call_logged(ship_parcel, 1.0, "Delhi")
            call_logged(ship_parcel, 4.2, destination="Goa", express=True)
            largest_by_size = call_logged(max, [3, -9, 4], key=abs)
            '''
        ),
    ]


def _default_cells() -> list[NotebookNode]:
    """1.10.5 Default values."""
    return [
        md(
            """
            ### 1.10.5 Default values

            A default expression is evaluated **once**, when the `def` statement runs, and the
            resulting object is stored in `__defaults__`. Every call that omits the argument gets
            **that same object**. JavaScript evaluates defaults on every call, so this surprises
            JS developers.
            """
        ),
        code(
            '''
            def announce_default() -> int:
                """Print when the default is computed."""
                print("  default computed now (at def time)")
                return 18


            print("defining:")


            def tax_rate(rate: int = announce_default()) -> int:
                """Return rate (default computed once)."""
                return rate


            print("calling twice:")
            print(f"{tax_rate()=}, {tax_rate()=}")
            '''
        ),
        md(
            """
            **The mutable-default trap.** A list (or dict, or set) as a default is created once
            and shared by every call, so it accumulates. `__defaults__` shows the shared list
            growing.
            """
        ),
        code(
            '''
            def add_to_cart_buggy(item: str, cart: list[str] = []) -> list[str]:  # noqa: B006
                """Append item to cart (buggy: the default list is shared)."""
                cart.append(item)
                return cart


            print(f"{add_to_cart_buggy.__defaults__=}")
            first_cart = add_to_cart_buggy("tea")
            second_cart = add_to_cart_buggy("rice")
            print(f"{second_cart=}, {first_cart is second_cart=}")
            print(f"{add_to_cart_buggy.__defaults__=}")
            '''
        ),
        md(
            """
            **The `None` pattern**: use `None` as the default and create the object inside the
            function, so each call gets a fresh one. (`ruff` rule B006 flags the buggy version.)
            """
        ),
        code(
            '''
            def add_to_cart(item: str, cart: list[str] | None = None) -> list[str]:
                """Append item to cart, or to a new cart if none is given."""
                if cart is None:
                    cart = []
                cart.append(item)
                return cart


            print(f"{add_to_cart('tea')=}, {add_to_cart('rice')=}")
            shared_cart = ["ghee"]
            print(f"{add_to_cart('dal', shared_cart)=}, {shared_cart=}")
            '''
        ),
        md(
            """
            **`sentinel()`** (*New in 3.15*, PEP 661): sometimes `None` is a valid value. An
            "update profile" function needs three cases: argument not passed (keep the email),
            `None` (clear it), or a string (change it). A sentinel is a unique object with a clear
            `repr`, used as the default and checked with `is`. Create it **once** at module level:
            every `sentinel(...)` call makes a new, distinct object. Before 3.15 the usual
            spelling is `MISSING = object()`.
            """
        ),
        code(
            '''
            if sys.version_info >= (3, 15):
                NOT_GIVEN = sentinel("NOT_GIVEN")
            else:
                NOT_GIVEN = object()


            def update_email(profile: dict[str, Any], email: str | None | object = NOT_GIVEN) -> dict[str, Any]:
                """Return a copy of profile: keep, clear (None) or replace the email."""
                updated_profile = dict(profile)
                if email is not NOT_GIVEN:
                    updated_profile["email"] = email
                return updated_profile


            asha_profile = {"name": "Asha", "email": "asha@mail.in"}
            print(f"{update_email(asha_profile)=}")
            print(f"{update_email(asha_profile, None)=}")
            print(f"{update_email(asha_profile, 'asha@work.in')=}")
            print(f"{NOT_GIVEN!r}  (readable in signatures and logs)")
            '''
        ),
        md(
            """
            **Frozen `datetime.now()` defaults**: the same trap with time. `created_at=now()` is
            computed once, so every order made without an explicit time gets the timestamp of the
            moment the function was **defined**. Use the `None` pattern (the cell compares
            timestamps instead of printing them, since they change every run).
            """
        ),
        code(
            '''
            def create_order_buggy(
                order_id: int,
                created_at: dt.datetime = dt.datetime.now(),  # noqa: B008
            ) -> dict[str, Any]:
                """Create an order (buggy: created_at is frozen at definition time)."""
                return {"order_id": order_id, "created_at": created_at}


            def create_order(order_id: int, created_at: dt.datetime | None = None) -> dict[str, Any]:
                """Create an order stamped with the current time unless one is given."""
                if created_at is None:
                    created_at = dt.datetime.now()
                return {"order_id": order_id, "created_at": created_at}


            definition_time = create_order_buggy.__defaults__[0]
            later_order = create_order_buggy(1002)
            print(f"{later_order['created_at'] is definition_time=}  (frozen)")
            print(f"{create_order(1003)['created_at'] > definition_time=}  (fresh per call)")
            '''
        ),
        *predict_cells(
            snippet="""
            def add_tag(tag, tags=[]):
                tags.append(tag)
                return tags

            print(add_tag("new"), add_tag("sale"), add_tag("eco", []))
            """,
            answer="""
            `['new', 'sale'] ['new', 'sale'] ['eco']`. Both of the first two calls append to the
            **one** default list, and both return that same list object; by the time `print`
            runs, it holds both tags. The third call passes its own list, so it is unaffected.
            """,
            proof="""
            def add_tag(tag, tags=[]):  # noqa: B006
                tags.append(tag)
                return tags


            print(add_tag("new"), add_tag("sale"), add_tag("eco", []))
            """,
        ),
    ]


def _first_class_cells() -> list[NotebookNode]:
    """1.10.6 First-class and higher-order functions."""
    return [
        md(
            """
            ### 1.10.6 First-class and higher-order functions

            Functions are ordinary objects: you can bind them to other names, store them in lists
            and dicts, pass them as arguments, and return them. A **higher-order** function is one
            that takes or returns a function.

            **In variables, lists and dicts**:
            """
        ),
        code(
            '''
            def strip_spaces(text: str) -> str:
                """Remove surrounding whitespace."""
                return text.strip()


            clean_text = strip_spaces  # no call: the function object itself
            text_cleaners = [strip_spaces, str.lower, str.title]
            formatter_by_style = {"upper": str.upper, "lower": str.lower, "title": str.title}

            raw_name = "  aSHA kUMAR "
            print(f"{clean_text(raw_name)=}")
            for cleaner in text_cleaners:
                raw_name = cleaner(raw_name)
            print(f"{raw_name=}")
            print(f"{formatter_by_style['upper']('masala chai')=}")
            '''
        ),
        md(
            """
            **Callbacks**: the caller decides what happens next by passing functions. Same idea as
            JS callbacks; in Python they are usually plain functions or `lambda`s.
            """
        ),
        code(
            '''
            def process_payment(
                amount: int, on_success: Callable[[int], str], on_failure: Callable[[str], str]
            ) -> str:
                """Pretend to charge amount and call the matching callback."""
                if amount <= 0:
                    return on_failure("amount must be positive")
                return on_success(amount)


            def send_receipt(amount: int) -> str:
                """Success callback."""
                return f"receipt sent for ₹{amount}"


            print(process_payment(889, send_receipt, lambda reason: f"failed: {reason}"))
            print(process_payment(0, send_receipt, lambda reason: f"failed: {reason}"))
            '''
        ),
        md(
            """
            A function can also **return** a function, configured by its arguments (how it
            remembers `percent` is a closure, Unit 1.11):
            """
        ),
        code(
            '''
            def make_discount(percent: int) -> Callable[[float], float]:
                """Return a function that applies a fixed discount."""

                def apply(price: float) -> float:
                    return round(price * (100 - percent) / 100, 2)

                return apply


            festive_discount = make_discount(20)
            print(f"{festive_discount(1000)=}, {festive_discount.__qualname__=}")
            '''
        ),
        md(
            """
            **Dispatch tables with `operator` functions.** A dict from a key to a function
            replaces a long `if` / `elif` chain, and the `operator` module provides every operator
            as a function (`operator.lt` is `<`, `operator.add` is `+`), so you do not need a
            `lambda` for each. The demo filters products by a rule read from a query string, such
            as `price < 500`. (Lab 1.10, exercise 3, builds an arithmetic one.)
            """
        ),
        code(
            '''
            COMPARISONS: dict[str, Callable[[Any, Any], bool]] = {
                "<": operator.lt,
                "<=": operator.le,
                "==": operator.eq,
                "!=": operator.ne,
                ">=": operator.ge,
                ">": operator.gt,
            }
            catalog = [
                {"name": "tea", "price": 249, "rating": 4.5},
                {"name": "ghee", "price": 640, "rating": 4.8},
                {"name": "dal", "price": 162, "rating": 3.9},
            ]


            def filter_products(products: list[dict[str, Any]], rule: str) -> list[str]:
                """Apply a 'field operator value' rule such as 'price < 500'."""
                field_name, symbol, raw_value = rule.split()
                compare = COMPARISONS[symbol]
                get_field = operator.itemgetter(field_name)
                threshold = float(raw_value)
                return [product["name"] for product in products if compare(get_field(product), threshold)]


            print(f"{filter_products(catalog, 'price < 500')=}")
            print(f"{filter_products(catalog, 'rating >= 4.5')=}")
            '''
        ),
    ]


def _lambda_cells() -> list[NotebookNode]:
    """1.10.7 lambda."""
    return [
        md(
            """
            ### 1.10.7 `lambda`

            `lambda parameters: expression` creates a small anonymous function. The body is a
            **single expression** (its value is returned): no statements, no assignments (except
            `:=`), no annotations, no docstring.
            """
        ),
        code(
            """
            print(f"{(lambda price: price * 2)(249)=}")
            print(f"{(lambda first, second=10: first + second)(5)=}")
            print(f"{compile_error('lambda order: return order')=}")
            """
        ),
        md(
            """
            **`key=` usage** is the classic place for a `lambda`: a one-off function passed
            straight to `sorted`, `min`, `max` or `groupby`. When the key is just an item or an
            attribute, `operator.itemgetter` / `attrgetter` say the same thing.
            """
        ),
        code(
            """
            print(f"{[p['name'] for p in sorted(catalog, key=lambda product: product['price'])]=}")
            print(f"{max(catalog, key=lambda product: product['rating'])['name']=}")
            print(f"{[p['name'] for p in sorted(catalog, key=operator.itemgetter('price'))]=}")
            """
        ),
        md(
            """
            **`<lambda>` in tracebacks**: every lambda is named `<lambda>`, so an error inside one
            tells you little about *which* lambda failed. A `def` has a real name.
            """
        ),
        code(
            '''
            def failing_frame_name(func: Callable[[], object]) -> str:
                """Call func and return the name of the innermost frame in the traceback."""
                try:
                    func()
                except Exception as error:
                    return traceback.extract_tb(error.__traceback__)[-1].name
                return "no error"


            def unit_price_from_total() -> float:
                """Divide by a zero quantity on purpose."""
                return 498 / 0


            print(f"{failing_frame_name(lambda: 498 / 0)=}")
            print(f"{failing_frame_name(unit_price_from_total)=}")
            print(f"{(lambda: 0).__name__=}")
            '''
        ),
        md(
            """
            **When to prefer `def`**: as soon as the function gets a name, needs more than one
            expression, deserves a docstring or a type hint, or is reused. Assigning a lambda to a
            name is the clearest sign (PEP 8 says so, and `ruff` rule E731 flags it); the `def`
            version is no longer and has a proper `__name__`.
            """
        ),
        code(
            '''
            add_delivery_fee = lambda total: total + 40  # noqa: E731


            def add_delivery_fee_def(total: int) -> int:
                """Add the flat delivery fee."""
                return total + 40


            print(f"{add_delivery_fee.__name__=}, {add_delivery_fee_def.__name__=}")
            '''
        ),
    ]


def _docstring_cells() -> list[NotebookNode]:
    """1.10.8 Docstrings and annotations."""
    return [
        md(
            '''
            ### 1.10.8 Docstrings and annotations

            **PEP 257 docstrings**: a string literal as the first statement of a function, class
            or module. Use triple double quotes; start with a one-line summary in the imperative
            ("Return …", not "Returns …"), ending with a period; for more, add a blank line and
            the details.

            **Google style** adds named sections that tools such as Sphinx (with napoleon) and
            IDEs understand:

            ```python
            def split_bill(total, people):
                """Split total into equal shares.

                Args:
                    total: Amount in rupees.
                    people: Number of people, at least 1.

                Returns:
                    One share per person.

                Raises:
                    ValueError: If people is less than 1.
                """
            ```

            `help()` prints the signature and the docstring; `inspect.getdoc()` returns the
            docstring with the indentation cleaned up.
            '''
        ),
        code(
            '''
            def delivery_eta_days(distance_km: float, *, express: bool = False) -> int:
                """Estimate delivery time in whole days.

                Args:
                    distance_km: Road distance from the warehouse.
                    express: Use the express courier (twice as fast).

                Returns:
                    Days until delivery, at least 1.

                Raises:
                    ValueError: If distance_km is negative.
                """
                if distance_km < 0:
                    raise ValueError("distance cannot be negative")
                speed_km_per_day = 800 if express else 400
                return max(1, math.ceil(distance_km / speed_km_per_day))


            help(delivery_eta_days)
            '''
        ),
        md(
            "`inspect.getdoc` gives the cleaned text, useful for tooling (the first line is the summary):"
        ),
        code(
            """
            print(f"{inspect.getdoc(delivery_eta_days).splitlines()[0]=}")
            print(f"{delivery_eta_days(1200)=}, {delivery_eta_days(1200, express=True)=}")
            """
        ),
        md(
            """
            **Annotations are not enforced.** Python stores them and tools read them (type
            checkers in Phase 4, FastAPI and Pydantic in Phase 6), but the interpreter does not
            check arguments against them. A wrong type passes through until some operation
            fails, or silently produces nonsense.
            """
        ),
        code(
            '''
            def double_quantity(quantity: int) -> int:
                """Double a quantity."""
                return quantity * 2


            print(f"{double_quantity(3)=}")
            print(f"{double_quantity('3')=}  (no error: str * 2 repeats the text)")
            print(f"{double_quantity.__annotations__=}")
            '''
        ),
        md(
            """
            **Lazy annotation evaluation** (*New in 3.14*, PEP 649 / PEP 749). Annotations are no
            longer evaluated when the `def` runs; they are computed only when someone asks. So a
            function can name a class that is defined **later** (no quotes, no
            `from __future__ import annotations`). The `annotationlib` module asks in
            different formats:

            | Format | Returns |
            | --- | --- |
            | `Format.VALUE` | the evaluated objects (raises `NameError` if a name is still undefined) |
            | `Format.FORWARDREF` | values where possible, `ForwardRef` placeholders otherwise |
            | `Format.STRING` | the annotations as source strings |
            """
        ),
        code(
            '''
            if sys.version_info >= (3, 14):
                import annotationlib

                def print_invoice(invoice: Invoice) -> Receipt:  # noqa: F821
                    """Annotations name classes that do not exist yet."""
                    return Receipt()  # noqa: F821

                Format = annotationlib.Format
                print(f"{annotationlib.get_annotations(print_invoice, format=Format.STRING)=}")
                forward_refs = annotationlib.get_annotations(print_invoice, format=Format.FORWARDREF)
                print(f"{type(forward_refs['invoice']).__name__=}")
                value_error = raised_error_name(lambda: print_invoice.__annotations__)
                print(f"VALUE before the classes exist: {value_error}")

                class Invoice:
                    """Defined after the function."""

                class Receipt:
                    """Defined after the function."""

                print(f"{print_invoice.__annotations__=}")
            else:
                print("lazy annotations need Python 3.14; skipped")
            '''
        ),
    ]


def _recursion_cells() -> list[NotebookNode]:
    """1.10.9 Recursion basics."""
    return [
        md(
            """
            ### 1.10.9 Recursion basics

            A recursive function calls itself on a smaller problem. It needs a **base case** that
            returns without recursing; every other call must move toward it.

            ```text
            factorial(4) = 4 * factorial(3)
                             = 3 * factorial(2)
                                 = 2 * factorial(1)
                                     = 1            (base case)
            ```

            The next cell writes factorial recursively and iteratively and checks both against
            `math.factorial`.
            """
        ),
        code(
            '''
            def factorial_recursive(number: int) -> int:
                """Return number! recursively."""
                if number <= 1:  # base case
                    return 1
                return number * factorial_recursive(number - 1)


            def factorial_iterative(number: int) -> int:
                """Return number! with a loop."""
                product = 1
                for factor in range(2, number + 1):
                    product *= factor
                return product


            print(f"{factorial_recursive(10)=}, {factorial_iterative(10)=}")
            versions_agree = all(
                factorial_recursive(n) == factorial_iterative(n) == math.factorial(n) for n in range(30)
            )
            print(f"{versions_agree=}  (0! to 29!)")
            '''
        ),
        md(
            """
            Recursion fits naturally nested data, such as summing a nested price structure,
            where a loop would need an explicit stack (1.6.13).
            """
        ),
        code(
            '''
            def total_price(node: int | list[Any]) -> int:
                """Sum all ints in an arbitrarily nested list."""
                if isinstance(node, int):  # base case
                    return node
                return sum(total_price(child) for child in node)


            gift_hamper = [249, [640, [162, 80]], [], 525]
            print(f"{total_price(gift_hamper)=}")
            '''
        ),
        md(
            """
            **Recursion-limit preview.** Every call adds a frame to the call stack. CPython caps
            the depth (`sys.getrecursionlimit()`, usually 1000) and raises `RecursionError`
            instead of crashing. Python does **not** optimize tail calls, so deep recursion
            should be rewritten as a loop. A missing base case hits the limit immediately. Unit
            1.12 looks at the call stack in detail.
            """
        ),
        code(
            '''
            def countdown_without_base_case(number: int) -> int:
                """Never stops: there is no base case."""
                return countdown_without_base_case(number - 1)


            print(f"{sys.getrecursionlimit()=}")
            print(f"no base case: {raised_error_name(lambda: countdown_without_base_case(5))}")
            print(f"too deep: {raised_error_name(lambda: factorial_recursive(50_000))}")
            print(f"{factorial_iterative(5_000).bit_length()=}  (the loop has no depth limit)")
            '''
        ),
    ]


def _lab_cells() -> list[NotebookNode]:
    """Lab 1.10."""
    return [
        md(
            """
            ### Lab 1.10

            Three exercises. For each, replace the `raise NotImplementedError` in the stub, then
            run the check cell. Until then the checks print FAIL; that is expected.

            #### Exercise 1 — `build_query_string(base_url, /, *, page=1, page_size=20, **filters)`

            Return `base_url + "?" + query`, where the query lists `page`, then `page_size`, then
            every filter **in the order given**, URL-encoded with `urllib.parse.urlencode`
            (imported in the setup cell; spaces become `+`).

            - Filters whose value is `None` are skipped.
            - Raise `ValueError` if `page < 1` or `page_size` is not between 1 and 100.
            - Keep the exact signature: `base_url` positional-only (so a filter may be called
              `base_url`), `page` and `page_size` keyword-only. The two signature checks
              ("page is keyword-only", "parameter kinds") already pass on the stub; they guard
              against changing it.
            """
        ),
        code(
            '''
            def build_query_string(
                base_url: str, /, *, page: int = 1, page_size: int = 20, **filters: object
            ) -> str:
                """Return base_url with page, page_size and the non-None filters as a query string."""
                raise NotImplementedError("Lab 1.10: implement build_query_string()")
            '''
        ),
        md("Run the checks."),
        code(
            """
            run_checks(
                [
                    (
                        "defaults",
                        lambda: build_query_string("/api/products"),
                        "/api/products?page=1&page_size=20",
                    ),
                    (
                        "filters in call order",
                        lambda: build_query_string("/api/products", page=2, category="tea", max_price=500),
                        "/api/products?page=2&page_size=20&category=tea&max_price=500",
                    ),
                    (
                        "None filters skipped",
                        lambda: build_query_string("/search", q="masala chai", city=None),
                        "/search?page=1&page_size=20&q=masala+chai",
                    ),
                    (
                        "filter named base_url",
                        lambda: build_query_string("/api", base_url="mirror"),
                        "/api?page=1&page_size=20&base_url=mirror",
                    ),
                    (
                        "page is keyword-only",
                        lambda: raised_error_name(lambda: build_query_string("/api", 2)),
                        "TypeError",
                    ),
                    (
                        "page 0",
                        lambda: raised_error_name(lambda: build_query_string("/api", page=0)),
                        "ValueError",
                    ),
                    (
                        "page_size 101",
                        lambda: raised_error_name(lambda: build_query_string("/api", page_size=101)),
                        "ValueError",
                    ),
                    (
                        "parameter kinds",
                        lambda: [
                            parameter.kind.name
                            for parameter in inspect.signature(build_query_string).parameters.values()
                        ],
                        ["POSITIONAL_ONLY", "KEYWORD_ONLY", "KEYWORD_ONLY", "VAR_KEYWORD"],
                    ),
                ]
            )
            """
        ),
        md(
            """
            #### Exercise 2 — `apply_pipeline(value, *transforms)`

            Apply each transform to the result of the previous one, left to right, and return the
            final value. With no transforms, return `value` itself (the same object).
            """
        ),
        code(
            '''
            def apply_pipeline(value: Any, *transforms: Callable[[Any], Any]) -> Any:
                """Return value passed through every transform, left to right."""
                raise NotImplementedError("Lab 1.10: implement apply_pipeline()")
            '''
        ),
        md("Run the checks."),
        code(
            """
            slug_steps = [str.strip, str.lower, lambda text: text.replace(" ", "-")]
            original_list = [3, 1, 2]
            run_checks(
                [
                    ("slug pipeline", lambda: apply_pipeline("  Masala Chai ", *slug_steps), "masala-chai"),
                    ("numbers", lambda: apply_pipeline(10, lambda n: n + 5, lambda n: n * 2), 30),
                    ("order matters", lambda: apply_pipeline(10, lambda n: n * 2, lambda n: n + 5), 25),
                    (
                        "no transforms returns the same object",
                        lambda: apply_pipeline(original_list) is original_list,
                        True,
                    ),
                    ("built-ins as transforms", lambda: apply_pipeline([3, 1, 2], sorted, tuple), (1, 2, 3)),
                    ("types can change", lambda: apply_pipeline("42", int, float, str), "42.0"),
                ]
            )
            """
        ),
        md(
            """
            #### Exercise 3 — `calculate(operation_name, left, right)` with a dispatch table

            Fill the `OPERATIONS` dict with **`operator` module functions** (no `lambda`) for these
            names: `"add"`, `"subtract"`, `"multiply"`, `"divide"` (true division),
            `"floor_divide"`, `"modulo"`, `"power"`. Then `calculate` looks the name up and calls
            the function: no `if` / `elif` chain. An unknown name raises
            `ValueError("unknown operation: <name>")`. Division by zero raises
            `ZeroDivisionError` naturally.
            """
        ),
        code(
            '''
            OPERATIONS: dict[str, Callable[[float, float], float]] = {}  # fill in


            def calculate(operation_name: str, left: float, right: float) -> float:
                """Apply the named operation from OPERATIONS to left and right."""
                raise NotImplementedError("Lab 1.10: implement calculate()")
            '''
        ),
        md("Run the checks."),
        code(
            """
            run_checks(
                [
                    ("add", lambda: calculate("add", 2, 3), 5),
                    ("subtract", lambda: calculate("subtract", 2, 3), -1),
                    ("multiply", lambda: calculate("multiply", 249, 2), 498),
                    ("divide", lambda: calculate("divide", 7, 2), 3.5),
                    ("floor_divide", lambda: calculate("floor_divide", -7, 2), -4),
                    ("modulo", lambda: calculate("modulo", -7, 3), 2),
                    ("power", lambda: calculate("power", 2, 10), 1024),
                    (
                        "divide by zero",
                        lambda: raised_error_name(lambda: calculate("divide", 1, 0)),
                        "ZeroDivisionError",
                    ),
                    (
                        "unknown operation",
                        lambda: raised_error_name(lambda: calculate("sqrt", 9, 0)),
                        "ValueError",
                    ),
                    (
                        "table has the seven names",
                        lambda: sorted(OPERATIONS),
                        ["add", "divide", "floor_divide", "modulo", "multiply", "power", "subtract"],
                    ),
                    ("table uses operator functions", lambda: OPERATIONS.get("add") is operator.add, True),
                ]
            )
            """
        ),
    ]


def _recap_cells() -> list[NotebookNode]:
    """Recap for Unit 1.10."""
    return [
        md(
            """
            ### Recap — Unit 1.10

            | Concept | One-line takeaway | JS equivalent |
            | --- | --- | --- |
            | `def` | A statement that builds a function object at run time (`MAKE_FUNCTION`); no hoisting | function declarations are hoisted |
            | Function attributes | `__name__`, `__qualname__`, `__doc__`, `__defaults__`, `__kwdefaults__`, `__code__`, `__globals__`, `__annotations__`, `__dict__` | `name`, `length` |
            | Return values | No `return` → `None`; `return a, b` returns one tuple | `undefined`; return an array/object |
            | Parameter kinds | `pos_only, /, standard, *args, kw_only, **kwargs` | rest parameters, destructured options |
            | `*args` / `**kwargs` | Extra positionals as a tuple / extra keywords as a dict | `...args` (array) |
            | `inspect.signature` | Read parameter kinds and defaults (frameworks rely on it) | `fn.length`, `toString()` parsing |
            | Call unpacking | `f(*values, **options)`; forwarding wrapper `f(*args, **kwargs)` | `f(...values)` |
            | Defaults | Evaluated once at definition; never use a mutable default | evaluated per call |
            | `None` / `sentinel()` | `None` for "fresh object per call"; `sentinel()` (3.15) when `None` is a valid value | `undefined` vs `null` |
            | First-class functions | Store, pass and return functions; dispatch tables with `operator` | same |
            | `lambda` | One expression; fine for `key=`; named functions get `def` | arrow functions (full bodies allowed) |
            | Docstrings | PEP 257 summary line + Google-style sections; `help()` shows them | JSDoc |
            | Annotations | Stored, not enforced; lazily evaluated since 3.14 (`annotationlib`) | TypeScript types (erased) |
            | Recursion | Base case first; limit ~1000 frames; no tail-call optimization | similar stack limits |

            **Further reading**

            - [Tutorial: defining functions](https://docs.python.org/3/tutorial/controlflow.html#defining-functions),
              [more on defining functions](https://docs.python.org/3/tutorial/controlflow.html#more-on-defining-functions)
            - [Function definitions (reference)](https://docs.python.org/3/reference/compound_stmts.html#function-definitions),
              [user-defined function attributes](https://docs.python.org/3/reference/datamodel.html#user-defined-functions)
            - [`inspect.signature`](https://docs.python.org/3/library/inspect.html#introspecting-callables-with-the-signature-object),
              [`operator`](https://docs.python.org/3/library/operator.html),
              [`annotationlib`](https://docs.python.org/3/library/annotationlib.html)
            - [PEP 257 — Docstring conventions](https://peps.python.org/pep-0257/),
              [Google Python style guide: docstrings](https://google.github.io/styleguide/pyguide.html#38-comments-and-docstrings)
            - [PEP 570 — Positional-only parameters](https://peps.python.org/pep-0570/),
              [PEP 3102 — Keyword-only arguments](https://peps.python.org/pep-3102/),
              [PEP 468 — Preserving keyword argument order](https://peps.python.org/pep-0468/)
            - [PEP 661 — Sentinel values](https://peps.python.org/pep-0661/),
              [PEP 649 — Deferred evaluation of annotations](https://peps.python.org/pep-0649/),
              [PEP 749 — Implementing PEP 649](https://peps.python.org/pep-0749/)
            """
        ),
    ]


def cells() -> list[NotebookNode]:
    """Return the cells for Unit 1.10 and Lab 1.10."""
    return [
        *_overview_cells(),
        *_def_cells(),
        *_return_cells(),
        *_parameter_cells(),
        *_unpacking_cells(),
        *_default_cells(),
        *_first_class_cells(),
        *_lambda_cells(),
        *_docstring_cells(),
        *_recursion_cells(),
        *_lab_cells(),
        *_recap_cells(),
    ]
