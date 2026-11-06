# Unit 1.10 — Functions: Definition and Arguments

[← Previous](unit-1-9-iteration-comprehensions-and-built-in-functions.md) · [Index](README.md) · [Next →](unit-1-11-scope-namespaces-and-closures.md)

Functions look familiar to a JavaScript developer, but Python's version has a
richer argument system and a few rules that run against JavaScript instincts:
`def` is not hoisted, default values are evaluated only once, and the caller
can be forced to pass some arguments by position and others by name. This unit
covers how a function object is built, every parameter kind and how to read
them, argument unpacking, the default-value traps, functions as values,
`lambda`, docstrings and annotations, and the basics of recursion.

## What you will learn

- Why `def` is a statement that runs at run time and builds a function object,
  and which attributes that object carries (`__name__`, `__defaults__`,
  `__code__` and more).
- How return values work: the implicit `None`, returning a tuple and unpacking
  it, and guard clauses.
- Every parameter kind (positional-only, positional-or-keyword, `*args`,
  keyword-only, `**kwargs`), the order they must appear in, why each exists,
  and how to read them with `inspect.signature`.
- How to unpack arguments at a call with `*` and `**`, and how the forwarding
  wrapper `def wrapper(*args, **kwargs)` works.
- Why defaults are evaluated once, how the mutable-default trap happens, and
  how the `None` pattern and the new `sentinel()` (3.15) fix it.
- How to store, pass and return functions, build callbacks and dispatch tables,
  and when a `lambda` is the right tool.
- How to write PEP 257 and Google-style docstrings, what annotations do (and do
  not do), and the lazy annotations of Python 3.14.
- How to write a recursive function with a base case, and why CPython has a
  recursion limit.

## JavaScript → Python bridge

Most of the ideas carry over from JavaScript. What changes is the timing (when
a function and its defaults are created) and the extra control Python gives the
function author over how arguments may be passed.

| JavaScript | Python | The difference that bites |
| --- | --- | --- |
| `function f() {}` (hoisted) | `def f():` | Calling before the `def` is a `NameError` |
| `return;` → `undefined` | no return → `None` | Same idea, different value |
| `function f(a, b = 2)` | `def f(a, b=2):` | Default evaluated **once** |
| `function f(...args)` | `def f(*args):` | `args` is a **tuple** |
| `function f({ page, size })` | `def f(*, page, size):` | Keyword-only, no object |
| — | `def f(x, /):` | Positional-only parameters |
| `f(...values)` | `f(*values)`, `f(**options)` | `**` spreads a dict as keywords |
| `(x) => x * 2` | `lambda x: x * 2` | One expression only |
| JSDoc / TypeScript types | docstrings, annotations | Not checked at run time |
| `f.name`, `f.length` | `f.__name__`, `inspect.signature(f)` | Many more attributes |

> **Note:** JavaScript has no positional-only parameters in user code, and its
> "named arguments" are really one destructured object. Python has true
> keyword arguments: the interpreter matches names to parameters itself and
> raises `TypeError` for a missing, duplicate or unknown name.

### Setup used by the examples

Every example in this unit runs after this setup block. `raised_error_name`
calls a zero-argument function (a *thunk*) and returns the name of the
exception it raised, which keeps error demos to one line. `compile_error`
compiles source code without running it and reports any `SyntaxError`.

```python
import datetime as dt
import dis
import inspect
import math
import operator
import sys
import traceback
from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode


def raised_error_name(thunk: Callable[[], object]) -> str:
    """Call thunk and return the name of the exception it raised."""
    try:
        thunk()
    except Exception as error:
        return type(error).__name__
    return "no error"


def compile_error(source: str) -> str:
    """Compile source without running it; report a SyntaxError or "compiles"."""
    try:
        compile(source, "<demo>", "exec")
    except SyntaxError as error:
        return f"SyntaxError: {error.msg}"
    return "compiles"


print(f"{sys.version_info[:2]=}")
```

```text
sys.version_info[:2]=(3, 15)
```

## 1.10.1 `def` is an executable statement

In JavaScript, a function declaration is *hoisted*: the engine creates the
function while it sets up the scope, before any line of the body runs, so you
can call a function above the place where it is written. Python has nothing
like this. `def name(...):` is an ordinary statement that **runs** when
execution reaches it. Running it builds a function object from the compiled
body and binds that object to `name`, exactly like an assignment. Until the
line has run, the name simply does not exist.

The example runs a small module in a fresh, empty namespace (so nothing defined
earlier can interfere). The call above the `def` fails with `NameError`; the
second module, which defines first and calls afterwards, works.

```python
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
fixed_source = "def greet(name):\n    return name\nresult = greet('asha')"
exec(fixed_source, fixed_namespace)
print(f"{fixed_namespace['result']=}")
```

```text
NameError: name 'greet' is not defined
fixed_namespace['result']='asha'
```

> **Note:** Inside a function body the rule is relaxed in practice: a function
> may call another function defined *later in the module*, because the call
> only happens when the outer function runs, and by then the whole module has
> been executed. What matters is whether the name exists **at the moment of
> the call**, not where it appears in the file.

### Under the hood: `MAKE_FUNCTION`

When CPython compiles a module, it compiles each function body separately into
a *code object* (bytecode, constants, variable names) and stores that code
object as a constant of the module. At run time, the `def` statement does three
things: load the code object, wrap it into a new function object with
`MAKE_FUNCTION` (which links it to the module globals), and bind it with
`STORE_NAME`. The disassembly shows exactly that sequence. A `def` with
default values also evaluates them at this point and attaches them with an
extra `SET_FUNCTION_ATTRIBUTE` instruction, which is why defaults are computed
once (section 1.10.5).

```python
definition_code = compile(
    "def greet(name):\n    return name\n", "<demo>", "exec"
)
for instruction in dis.get_instructions(definition_code):
    if inspect.iscode(instruction.argval):
        # print the code object's name, not its memory address
        detail = f"<code object {instruction.argval.co_name}>"
    else:
        detail = instruction.argrepr
    print(f"{instruction.opname:16} {detail}")
```

```text
RESUME
LOAD_CONST       <code object greet>
MAKE_FUNCTION
STORE_NAME       greet
LOAD_COMMON_CONSTANT None
RETURN_VALUE
```

> **Note:** Opcode names change between Python versions (for example,
> `LOAD_COMMON_CONSTANT` is recent). The shape is what matters: the body was
> compiled ahead of time, and only the *function object* is created when the
> `def` runs. Running the same `def` twice (say, inside a loop) creates two
> different function objects that share one code object.

### Conditional definitions and redefinition

Because `def` is a statement, it can appear anywhere a statement can: inside an
`if`, a loop, a `try`, or another function. A common use is a **conditional
definition**, which picks one implementation once, at import time, based on the
Python version or the platform. Defining the same name twice is also legal: the
second `def` rebinds the name, the last definition wins, and the first function
object is garbage collected if nothing else refers to it.

```python
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


def price_label(price: int) -> str:  # rebinds the name; first object is gone
    """Second version."""
    return f"₹{price}"


print(f"{describe_runtime()=}")
print(f"{price_label(249)=}")
```

```text
describe_runtime()='3.15+ implementation'
price_label(249)='₹249'
```

> **Warning:** An accidental redefinition (two functions with the same name in
> one module, often after a copy-paste) is silent at run time. Linters catch
> it: `ruff` reports it as F811 (redefinition of unused name).

### Function attributes

A function is an object like any other, so it has a type (`function`) and
attributes. JavaScript functions expose `name` and `length`; Python functions
expose much more, and frameworks, debuggers and decorators rely on these
attributes. One function is used for all the demos:

```python
def apply_discount(
    price: float, percent: float = 10, *, round_to: int = 2
) -> float:
    """Return price reduced by percent, rounded to round_to decimal places."""
    discounted_price = price * (100 - percent) / 100
    return round(discounted_price, round_to)


print(f"{apply_discount(249)=}")
print(f"{apply_discount(249, 50, round_to=0)=}")
```

```text
apply_discount(249)=224.1
apply_discount(249, 50, round_to=0)=124.0
```

The reference tables below list every attribute, split into two groups. The
examples use `apply_discount` and the two small helpers defined in the
demos that follow (`Checkout` and `no_docstring`).

**Identity and documentation**

| Attribute | What it holds | Example | Result |
| --- | --- | --- | --- |
| `__name__` | Name from the `def` line | `apply_discount.__name__` | `'apply_discount'` |
| `__qualname__` | Dotted path from the module | `Checkout.total.__qualname__` | `'Checkout.total'` |
| `__doc__` | Docstring, or `None` | `no_docstring.__doc__` | `None` |
| `__annotations__` | Annotations by name | `apply_discount.__annotations__["return"]` | `<class 'float'>` |

**Defaults, code and namespaces**

| Attribute | What it holds | Example | Result |
| --- | --- | --- | --- |
| `__defaults__` | Positional defaults (tuple) | `apply_discount.__defaults__` | `(10,)` |
| `__kwdefaults__` | Keyword-only defaults (dict) | `apply_discount.__kwdefaults__` | `{'round_to': 2}` |
| `__code__` | Compiled code object | `type(apply_discount.__code__)` | `<class 'code'>` |
| `__globals__` | Module namespace (dict) | `apply_discount.__globals__ is globals()` | `True` |
| `__dict__` | Your own attributes | `apply_discount.__dict__` | `{}` (before you add any) |

Each attribute is shown in full below.

**`__name__`** is the name written on the `def` line. Assigning the function to
another variable does not change it, because the object is the same; only a new
name points at it.

```python
discount_function = apply_discount
print(f"{apply_discount.__name__=}")
print(f"{discount_function.__name__=}")
```

```text
apply_discount.__name__='apply_discount'
discount_function.__name__='apply_discount'
```

**`__qualname__`** (qualified name, PEP 3155) records *where* the function was
defined: `Class.method` for methods, and `outer.<locals>.inner` for a function
defined inside another function. Tracebacks and `repr()` use it, which is why
it is more useful than `__name__` when you debug nested code.

```python
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
```

```text
apply_discount.__qualname__='apply_discount'
Checkout.total.__qualname__='Checkout.total'
make_formatter().__qualname__='make_formatter.<locals>.format_price'
```

**`__doc__`** holds the docstring: the first statement of the body, if it is a
string literal. A function without one has `__doc__` set to `None`.

```python
def no_docstring() -> None:
    pass


print(repr(apply_discount.__doc__))
print(f"{make_formatter().__doc__=}")
print(f"{no_docstring.__doc__=}")
```

```text
'Return price reduced by percent, rounded to round_to decimal places.'
make_formatter().__doc__='Format a price in rupees.'
no_docstring.__doc__=None
```

**`__defaults__`** is a tuple with the default values of the positional
parameters, aligned to the *last* ones (here only `percent` has a default).
**`__kwdefaults__`** is a dict with the defaults of the keyword-only
parameters. These are the actual stored objects, which becomes important in
section 1.10.5.

```python
print(f"{apply_discount.__defaults__=}  (percent=10)")
print(f"{apply_discount.__kwdefaults__=}")
```

```text
apply_discount.__defaults__=(10,)  (percent=10)
apply_discount.__kwdefaults__={'round_to': 2}
```

**`__code__`** is the code object that `MAKE_FUNCTION` wrapped. It knows the
argument counts, the names of all local variables (parameters first) and the
raw bytecode.

```python
discount_code = apply_discount.__code__
print(f"{discount_code.co_argcount=}, {discount_code.co_kwonlyargcount=}")
print(f"{discount_code.co_varnames=}")
print(f"{len(discount_code.co_code) > 0=}  (raw bytecode bytes)")
```

```text
discount_code.co_argcount=2, discount_code.co_kwonlyargcount=1
discount_code.co_varnames=('price', 'percent', 'round_to', 'discounted_price')
len(discount_code.co_code) > 0=True  (raw bytecode bytes)
```

**`__globals__`** is the namespace (a dict) of the module where the function
was defined. Global names inside the body are looked up there, no matter where
the function is later called from. Unit 1.11 builds on this.

```python
print(f"{apply_discount.__globals__ is globals()=}")
print(f"{'apply_discount' in apply_discount.__globals__=}")
```

```text
apply_discount.__globals__ is globals()=True
'apply_discount' in apply_discount.__globals__=True
```

**`__annotations__`** maps each annotated parameter name, plus `'return'`, to
its annotation.

```python
for parameter_name, annotation in apply_discount.__annotations__.items():
    print(f"{parameter_name:9} -> {annotation!r}")
```

```text
price     -> <class 'float'>
percent   -> <class 'float'>
round_to  -> <class 'int'>
return    -> <class 'float'>
```

**`__dict__`** stores any attributes you attach yourself: version tags,
counters, registration flags. Decorators (Unit 1.12) often use it.

```python
apply_discount.version = 2
apply_discount.owner = "pricing-team"
print(f"{apply_discount.__dict__=}")
print(f"{apply_discount.version=}")
```

```text
apply_discount.__dict__={'version': 2, 'owner': 'pricing-team'}
apply_discount.version=2
```

### Key points

| Idea | Takeaway |
| --- | --- |
| `def` | A statement; runs when reached |
| Hoisting | None: call before `def` is a `NameError` |
| Under the hood | Code object compiled early, `MAKE_FUNCTION` at run time |
| Conditional `def` | Picks an implementation once |
| Redefinition | Last `def` wins, silently |
| Attributes | Name, docs, defaults, code, globals, annotations |

## 1.10.2 Return values

### Implicit `None`

A function that ends without a `return` statement, or with a bare `return`,
returns `None`. This is Python's version of JavaScript's `undefined` result.
The standard library follows a strong convention built on it: a method that
**changes an object in place** returns `None` (`list.sort()`, `list.append()`,
`dict.update()`), so you cannot accidentally believe you got a new object.

```python
def log_order(order_id: int) -> None:
    """Print a log line; no return statement."""
    print(f"  order {order_id} logged")


log_result = log_order(1001)
print(f"{log_result=}")
product_names = ["tea", "rice"]
sort_result = product_names.sort()
print(f"{sort_result=}  (sort works in place and returns None)")
```

```text
  order 1001 logged
log_result=None
sort_result=None  (sort works in place and returns None)
```

> **Warning:** `items = items.sort()` replaces your list with `None`. In
> JavaScript `array.sort()` returns the same array, so this is a common slip.
> Use `items.sort()` alone, or `items = sorted(items)` for a new list.

### Returning several values

`return a, b` does not return two values. The comma builds **one tuple**, and
the caller unpacks it with the same tuple-unpacking syntax used for assignment
(Unit 1.5). In JavaScript you would return an array or an object and
destructure it. For more than two or three values, return a `NamedTuple`
(Unit 1.5) or a dataclass (Phase 2), so each field has a name.

```python
def price_range(prices: list[int]) -> tuple[int, int]:
    """Return the lowest and highest price."""
    return min(prices), max(prices)


range_result = price_range([249, 80, 640])
lowest_price, highest_price = price_range([249, 80, 640])
print(f"{range_result=}, {type(range_result).__name__=}")
print(f"{lowest_price=}, {highest_price=}")
```

```text
range_result=(80, 640), type(range_result).__name__='tuple'
lowest_price=80, highest_price=640
```

Star-unpacking works on returned tuples too, which is handy when the number of
returned items varies:

```python
def split_full_name(full_name: str) -> tuple[str, ...]:
    """Split a full name into its words."""
    return tuple(full_name.split())


first_name, *other_names = split_full_name("Asha Rani Kumar")
print(f"{first_name=}, {other_names=}")
```

```text
first_name='Asha', other_names=['Rani', 'Kumar']
```

### Guard clauses

A **guard clause** (Unit 1.8) is an early `return` (or `raise`) at the top of a
function that deals with empty, invalid or trivial input first. The rest of the
function then handles only the normal case, with no deep nesting of `if` /
`else` blocks.

```python
def average_order_value(order_totals: list[float]) -> float | None:
    """Return the mean order total, or None for no orders."""
    if not order_totals:
        return None
    if any(total < 0 for total in order_totals):
        raise ValueError("order totals cannot be negative")
    return sum(order_totals) / len(order_totals)


print(f"{average_order_value([])=}")
print(f"{average_order_value([100, 250])=}")
print(f"negative: {raised_error_name(lambda: average_order_value([-5]))}")
```

```text
average_order_value([])=None
average_order_value([100, 250])=175.0
negative: ValueError
```

### Key points

| Idea | Takeaway |
| --- | --- |
| No `return` | Returns `None` |
| In-place methods | Return `None` by convention |
| `return a, b` | Returns one tuple; unpack at the call |
| Many values | Prefer `NamedTuple` or a dataclass |
| Guard clauses | Handle bad input first, return early |

## 1.10.3 Parameter kinds

JavaScript has one way to receive arguments: by position, plus a rest
parameter and destructuring. Python lets the function author decide, per
parameter, **how** the caller may pass it. CPython matches arguments to
parameters in a fixed procedure: positional arguments fill the positional slots
left to right, extra positionals go to `*args`, keyword arguments are matched
by name, unknown names go to `**kwargs`, and defaults fill whatever is still
empty. Anything left unfilled, or filled twice, is a `TypeError`.

| Kind | Syntax | Caller may pass | `inspect` kind |
| --- | --- | --- | --- |
| Positional-only | before `/` | by position only | `POSITIONAL_ONLY` |
| Positional-or-keyword | plain name | position or name | `POSITIONAL_OR_KEYWORD` |
| Default value | `name=value` | may be omitted | (any kind) |
| Variadic positional | `*args` | extra positionals → tuple | `VAR_POSITIONAL` |
| Keyword-only | after `*` | by name only | `KEYWORD_ONLY` |
| Variadic keyword | `**kwargs` | extra keywords → dict | `VAR_KEYWORD` |

### Positional-or-keyword

This is the default kind: a plain parameter name. The caller chooses whether to
pass it by position or by name, and keyword arguments may come in any order.
Passing the same parameter twice (once by position, once by name) is a
`TypeError`.

```python
def format_greeting(name: str, greeting: str) -> str:
    """Greet name with greeting."""
    return f"{greeting}, {name}!"


print(format_greeting("Asha", "Namaste"))
print(format_greeting(greeting="Hello", name="Ravi"))
twice = raised_error_name(lambda: format_greeting("Asha", name="Ravi"))
print(f"twice: {twice}")
```

```text
Namaste, Asha!
Hello, Ravi!
twice: TypeError
```

### Defaults

A default value makes a parameter optional. Among the positional parameters,
those with defaults must come after those without; otherwise a positional
argument could not be matched unambiguously, and the compiler rejects the
`def`.

```python
def add_gst(amount: float, rate_percent: float = 18) -> float:
    """Add GST at rate_percent (default 18%)."""
    return round(amount * (1 + rate_percent / 100), 2)


print(f"{add_gst(100)=}, {add_gst(100, 5)=}")
print(f"{add_gst(100, rate_percent=28)=}")
print(compile_error("def broken(rate=18, amount): pass"))
```

```text
add_gst(100)=118.0, add_gst(100, 5)=105.0
add_gst(100, rate_percent=28)=128.0
SyntaxError: parameter without a default follows parameter with a default
```

### `*args`

`*args` collects any extra positional arguments into a **tuple** (JavaScript's
rest parameter `...args` gives an array). The name `args` is only a convention;
the star is what matters, and a descriptive name is better.

```python
def order_total(*line_amounts: float) -> float:
    """Sum any number of line amounts."""
    print(f"  {line_amounts=}, {type(line_amounts).__name__=}")
    return sum(line_amounts)


print(f"{order_total(249, 640)=}")
print(f"{order_total()=}")
```

```text
  line_amounts=(249, 640), type(line_amounts).__name__='tuple'
order_total(249, 640)=889
  line_amounts=(), type(line_amounts).__name__='tuple'
order_total()=0
```

> **Note:** The annotation on `*line_amounts: float` describes **each item**,
> not the tuple. The same goes for `**fields: object`, which annotates each
> value of the dict.

### Keyword-only parameters

Parameters that come after a bare `*` (or after `*args`) are **keyword-only**
(PEP 3102): the caller must name them. This is Python's answer to the
JavaScript "options object" pattern, without the object. It keeps call sites
readable for flags: `is_admin=True` says what it means, a bare `True` does not.

```python
def create_user(
    name: str, *, is_admin: bool = False, send_welcome: bool = True
) -> str:
    """Create a user; the flags must be named."""
    return f"{name} (admin={is_admin}, welcome={send_welcome})"


print(create_user("asha", is_admin=True))
positional_flag = raised_error_name(lambda: create_user("asha", True))
print(f"positional flag: {positional_flag}")
```

```text
asha (admin=True, welcome=True)
positional flag: TypeError
```

### Positional-only parameters

Parameters before a `/` are **positional-only** (PEP 570, Python 3.8). The
caller cannot use their names at all. That gives the author two freedoms: the
parameters can be renamed later without breaking any caller, and their names
stay available as keys in `**kwargs`. Many built-ins have always worked this
way, for example `len(obj, /)` and `divmod(x, y, /)`.

```python
def distance_km(start_km: float, end_km: float, /) -> float:
    """Distance between two markers on a highway."""
    return abs(end_km - start_km)


print(f"{distance_km(12.5, 40.0)=}")
by_name = raised_error_name(lambda: distance_km(start_km=1, end_km=2))
print(f"by name: {by_name}")
print(f"len by name: {raised_error_name(lambda: len(obj=[1, 2]))}")
```

```text
distance_km(12.5, 40.0)=27.5
by name: TypeError
len by name: TypeError
```

### `**kwargs`

`**kwargs` collects any extra keyword arguments into a **dict**. Since Python
3.6 (PEP 468) that dict keeps the order in which the caller wrote the
arguments.

```python
def log_event(event_name: str, **fields: object) -> str:
    """Format an event with arbitrary named fields."""
    print(f"  {fields=}")
    print(f"  {type(fields).__name__=}")
    field_texts = [f"{key}={value}" for key, value in fields.items()]
    return " ".join([event_name, *field_texts])


print(log_event("checkout", user="asha", total=889, coupon=None))
```

```text
  fields={'user': 'asha', 'total': 889, 'coupon': None}
  type(fields).__name__='dict'
checkout user=asha total=889 coupon=None
```

### The full signature order

The order of the kinds is fixed by the grammar. The shortest form that shows
all the markers, and the longest form with defaults and both variadic
parameters, are:

```python
def f(pos_only, /, standard, *, kw_only, **kwargs): ...
def g(
    pos_only, /, standard=1, *args, kw_only, kw_with_default=2, **kwargs
): ...
```

How to read each part of the signature (defaults left out):

```text
def g(pos_only, /, standard, *args, kw_only, **kwargs)
      └───┬───┘    └───┬───┘ └─┬─┘  └──┬──┘  └──┬───┘
          │            │       │       │        │
  by position   position   extra     by name  extra
  only          or name    positions only     keywords
                           → tuple            → dict
```

Each kind exists for a reason:

| Kind | Use it when |
| --- | --- |
| Positional-only | Name is meaningless or may change |
| Positional-or-keyword | The ordinary case |
| `*args` | "Any number of" things (`print`, `max`) |
| Keyword-only | Options and boolean flags |
| `**kwargs` | Forwarding, or open-ended named fields |

Positional-only is also the right choice when the name must not clash with
keys collected by `**kwargs`. The example calls the full form and shows where
each argument lands.

```python
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


def show_binding(binding: dict[str, object]) -> None:
    """Print one parameter per line."""
    for parameter_name, value in binding.items():
        print(f"  {parameter_name:16} {value!r}")


print("call 1:")
show_binding(every_kind("a", "b", "c", "d", kw_only="e", extra="f"))
print("call 2:")
show_binding(every_kind("a", kw_only="e", pos_only="goes into kwargs"))
```

```text
call 1:
  pos_only         'a'
  standard         'b'
  args             ('c', 'd')
  kw_only          'e'
  kw_with_default  2
  kwargs           {'extra': 'f'}
call 2:
  pos_only         'a'
  standard         1
  args             ()
  kw_only          'e'
  kw_with_default  2
  kwargs           {'pos_only': 'goes into kwargs'}
```

The second call shows the positional-only benefit in action:
`pos_only="goes into kwargs"` is not a duplicate argument. Because the first
parameter cannot be passed by name, the keyword is just another unknown name,
and it lands in `**kwargs`.

### Reading kinds with `inspect.signature`

`inspect.signature(func)` returns a `Signature` object whose `parameters` map
each name to a `Parameter` with a `kind`, a `default` and an `annotation`.
Frameworks are built on this: pytest (Phase 4) reads a test function's
parameters to decide which fixtures to pass, and FastAPI (Phase 6) reads them
to decide which values come from the path, the query string or the body. A
missing default is the special marker `inspect.Parameter.empty`. It works on
many built-ins too.

```python
for parameter in inspect.signature(every_kind).parameters.values():
    if parameter.default is inspect.Parameter.empty:
        default = "—"
    else:
        default = parameter.default
    print(f"{parameter.name:16} {parameter.kind.name:22} default={default}")
print(f"{inspect.signature(divmod)=}")
```

```text
pos_only         POSITIONAL_ONLY        default=—
standard         POSITIONAL_OR_KEYWORD  default=1
args             VAR_POSITIONAL         default=—
kw_only          KEYWORD_ONLY           default=—
kw_with_default  KEYWORD_ONLY           default=2
kwargs           VAR_KEYWORD            default=—
inspect.signature(divmod)=<Signature (x, y, /)>
```

### Key points

| Idea | Takeaway |
| --- | --- |
| Plain names | Position or keyword, caller decides |
| Defaults | After the non-default positionals |
| `*args` | Extra positionals as a tuple |
| After `*` | Keyword-only: must be named |
| Before `/` | Positional-only: names are private |
| `**kwargs` | Extra keywords as an ordered dict |
| `inspect.signature` | Reads kinds and defaults |

## 1.10.4 Argument unpacking

The star syntax has a second job. In a `def`, `*` and `**` **collect**
arguments; at a **call**, they **spread** them. `func(*sequence)` passes each
item of any iterable as a separate positional argument, and
`func(**mapping)` passes each key/value pair of a dict as a keyword argument
(Unit 1.8 introduced both). This is how you call a function with arguments
you built as data, for example values read from a CSV row and options read
from a config file. JavaScript's `f(...values)` covers the first half;
there is no JavaScript equivalent of `**`, because JavaScript has no keyword
arguments.

```python
def ship_parcel(
    weight_kg: float, destination: str, *, express: bool = False
) -> str:
    """Describe a shipment."""
    speed = "express" if express else "standard"
    return f"{weight_kg} kg to {destination} ({speed})"


parcel_values = [2.5, "Pune"]
parcel_options = {"express": True}
print(ship_parcel(*parcel_values, **parcel_options))
unknown = raised_error_name(lambda: ship_parcel(*parcel_values, gift=True))
print(f"unknown option: {unknown}")
```

```text
2.5 kg to Pune (express)
unknown option: TypeError
```

> **Note:** Unpacked arguments go through exactly the same matching as written
> ones. An unknown key in the dict is a `TypeError` (unless the function has
> `**kwargs`), and a key that duplicates a positional argument is a
> `TypeError` too. The keys must be strings.

### The forwarding wrapper

Put the two halves together and you get the most important pattern in this
unit: a function that accepts **any** arguments with `*args, **kwargs` and
passes them on unchanged with `func(*args, **kwargs)`. The wrapper does not
need to know the signature of the function it calls. Every decorator in Unit
1.12 has this shape, and so do helpers like `functools.partial`, retry loops
and logging wrappers.

```python
def call_logged(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Call func with the given arguments and log the call and its result."""
    result = func(*args, **kwargs)
    print(f"  {func.__name__} args={args} kwargs={kwargs}")
    print(f"    -> {result!r}")
    return result


call_logged(ship_parcel, 1.0, "Delhi")
call_logged(ship_parcel, 4.2, destination="Goa", express=True)
largest_by_size = call_logged(max, [3, -9, 4], key=abs)
```

```text
  ship_parcel args=(1.0, 'Delhi') kwargs={}
    -> '1.0 kg to Delhi (standard)'
  ship_parcel args=(4.2,) kwargs={'destination': 'Goa', 'express': True}
    -> '4.2 kg to Goa (express)'
  max args=([3, -9, 4],) kwargs={'key': <built-in function abs>}
    -> -9
```

The output shows how the call was split: positionals arrive in the `args`
tuple, keywords in the `kwargs` dict, and the wrapper spreads both back out
when it calls `func`, so `ship_parcel` and `max` see exactly what the caller
wrote.

### Key points

| Idea | Takeaway |
| --- | --- |
| `f(*values)` | Spreads an iterable as positionals |
| `f(**options)` | Spreads a dict as keywords |
| Same rules | Unknown or duplicate names → `TypeError` |
| Forwarding | `def w(*args, **kwargs)` + `f(*args, **kwargs)` |

## 1.10.5 Default values

### Evaluated once, at definition

This is the rule that surprises JavaScript developers most. In JavaScript, a
default expression is evaluated **on every call** that omits the argument. In
Python, the default expression is evaluated **once**, when the `def` statement
runs, and the resulting object is stored in `__defaults__` (or
`__kwdefaults__`). Every call that omits the argument receives **that same
object**. The example makes the timing visible with a default that prints when
it is computed.

```python
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
```

```text
defining:
  default computed now (at def time)
calling twice:
tax_rate()=18, tax_rate()=18
```

For immutable defaults (numbers, strings, tuples, `None`) this never matters,
because nobody can change the shared object. It matters a great deal for
mutable ones.

### The mutable-default trap

A list, dict or set used as a default is created once and **shared by every
call**. If the function mutates it, the changes pile up across calls. The
`__defaults__` tuple lets you watch the shared list grow.

```python
def add_to_cart_buggy(
    item: str, cart: list[str] = []  # noqa: B006
) -> list[str]:
    """Append item to cart (buggy: the default list is shared)."""
    cart.append(item)
    return cart


print(f"{add_to_cart_buggy.__defaults__=}")
first_cart = add_to_cart_buggy("tea")
second_cart = add_to_cart_buggy("rice")
print(f"{second_cart=}, {first_cart is second_cart=}")
print(f"{add_to_cart_buggy.__defaults__=}")
```

```text
add_to_cart_buggy.__defaults__=([],)
second_cart=['tea', 'rice'], first_cart is second_cart=True
add_to_cart_buggy.__defaults__=(['tea', 'rice'],)
```

```text
def runs once:     __defaults__ ──► [ ]   (one list object)
                                     ▲
call 1 (no cart):  cart ─────────────┤   append "tea"
call 2 (no cart):  cart ─────────────┘   append "rice"
                   → both calls return the same list
```

> **Warning:** Never use a mutable object (`[]`, `{}`, `set()`, an instance of
> your own class) as a default value. `ruff` rule B006 flags it. The bug often
> hides in tests, because each test process starts with a fresh default.

### The `None` pattern

The standard fix is to use `None` as the default and create the object inside
the function body, which runs on every call. Each call that omits the
argument gets a fresh object, and a caller who passes their own object still
gets it mutated, as expected.

```python
def add_to_cart(item: str, cart: list[str] | None = None) -> list[str]:
    """Append item to cart, or to a new cart if none is given."""
    if cart is None:
        cart = []
    cart.append(item)
    return cart


print(f"{add_to_cart('tea')=}, {add_to_cart('rice')=}")
shared_cart = ["ghee"]
print(f"{add_to_cart('dal', shared_cart)=}")
print(f"{shared_cart=}")
```

```text
add_to_cart('tea')=['tea'], add_to_cart('rice')=['rice']
add_to_cart('dal', shared_cart)=['ghee', 'dal']
shared_cart=['ghee', 'dal']
```

> **Note:** Test with `if cart is None:`, not `if not cart:`. The second form
> would also replace an empty list that the caller passed on purpose, and the
> caller would never see the appended item.

### `sentinel()` for "not passed" (new in 3.15)

Sometimes `None` is itself a meaningful value, so it cannot also mean "not
passed". An "update profile" function needs three cases for the email: the
argument is not passed (keep the email), it is `None` (clear it), or it is a
string (change it). This is the same distinction JavaScript draws between
`undefined` and `null`.

The answer is a **sentinel**: a unique object used only as the default and
tested with `is`. Python 3.15 adds the built-in `sentinel()` (PEP 661), which
creates such an object with a readable `repr`, so signatures, `help()` and
logs show `NOT_GIVEN` instead of `<object object at 0x…>`. Before 3.15 the
usual spelling is `MISSING = object()`.

```python
if sys.version_info >= (3, 15):
    NOT_GIVEN = sentinel("NOT_GIVEN")
else:
    NOT_GIVEN = object()


def update_email(
    profile: dict[str, Any], email: str | None | object = NOT_GIVEN
) -> dict[str, Any]:
    """Return a copy of profile: keep, clear (None) or replace the email."""
    updated_profile = dict(profile)
    if email is not NOT_GIVEN:
        updated_profile["email"] = email
    return updated_profile


asha_profile = {"name": "Asha", "email": "asha@mail.in"}
print(f"keep:    {update_email(asha_profile)}")
print(f"clear:   {update_email(asha_profile, None)}")
print(f"replace: {update_email(asha_profile, 'asha@work.in')}")
print(f"{NOT_GIVEN!r}  (readable in signatures and logs)")
```

```text
keep:    {'name': 'Asha', 'email': 'asha@mail.in'}
clear:   {'name': 'Asha', 'email': None}
replace: {'name': 'Asha', 'email': 'asha@work.in'}
NOT_GIVEN  (readable in signatures and logs)
```

> **Warning:** Create the sentinel **once**, at module level. Every call to
> `sentinel(...)` makes a new, distinct object, so a sentinel created inside a
> function would never be `is`-identical to the default.

### Frozen `datetime.now()` defaults

The same trap appears with time. `created_at=dt.datetime.now()` is evaluated
once, so every order created without an explicit time gets the timestamp of
the moment the function was **defined** (usually when the module was
imported). The fix is again the `None` pattern. The example compares
timestamps instead of printing them, because their values change on every run.

```python
def create_order_buggy(
    order_id: int,
    created_at: dt.datetime = dt.datetime.now(),  # noqa: B008
) -> dict[str, Any]:
    """Create an order (buggy: created_at is frozen at definition time)."""
    return {"order_id": order_id, "created_at": created_at}


def create_order(
    order_id: int, created_at: dt.datetime | None = None
) -> dict[str, Any]:
    """Create an order stamped with the current time unless one is given."""
    if created_at is None:
        created_at = dt.datetime.now()
    return {"order_id": order_id, "created_at": created_at}


definition_time = create_order_buggy.__defaults__[0]
later_order = create_order_buggy(1002)
fresh_order = create_order(1003)
print(f"{later_order['created_at'] is definition_time=}  (frozen)")
print(f"{fresh_order['created_at'] > definition_time=}  (fresh per call)")
```

```text
later_order['created_at'] is definition_time=True  (frozen)
fresh_order['created_at'] > definition_time=True  (fresh per call)
```

> **Note:** `ruff` rule B008 flags function calls in default values for this
> reason. A long-running web server with a frozen default would stamp every
> request with the server's start time.

### Predict the output

```python
def add_tag(tag, tags=[]):
    tags.append(tag)
    return tags


print(add_tag("new"), add_tag("sale"), add_tag("eco", []))
```

<details><summary>Answer</summary>

```text
['new', 'sale'] ['new', 'sale'] ['eco']
```

Both of the first two calls append to the **one** default list, and both
return that same list object. All three arguments of `print` are evaluated
before anything is printed, so by the time `print` runs, the shared list holds
both tags and is printed twice. The third call passes its own fresh list, so
it is unaffected.

</details>

### Key points

| Idea | Takeaway |
| --- | --- |
| Defaults | Evaluated once, stored in `__defaults__` |
| Mutable default | Shared by every call: a bug |
| `None` pattern | `if arg is None: arg = []` |
| `sentinel()` (3.15) | "Not passed" when `None` is valid |
| `now()` default | Frozen at definition time |

## 1.10.6 First-class and higher-order functions

Functions in Python are **first-class** objects, just as in JavaScript: you can
bind them to other names, store them in lists and dicts, pass them as
arguments and return them from other functions. A **higher-order function** is
one that takes or returns a function. `sorted(key=...)`, `map` and `filter`
are higher-order built-ins.

### In variables, lists and dicts

Writing a function's name without parentheses refers to the function object
itself; adding `()` calls it. Methods taken from a class, such as `str.lower`,
are plain functions that take the instance as their first argument, so they
can be stored and called the same way.

```python
def strip_spaces(text: str) -> str:
    """Remove surrounding whitespace."""
    return text.strip()


clean_text = strip_spaces  # no call: the function object itself
text_cleaners = [strip_spaces, str.lower, str.title]
formatter_by_style = {
    "upper": str.upper,
    "lower": str.lower,
    "title": str.title,
}

raw_name = "  aSHA kUMAR "
print(f"{clean_text(raw_name)=}")
for cleaner in text_cleaners:
    raw_name = cleaner(raw_name)
print(f"{raw_name=}")
print(f"{formatter_by_style['upper']('masala chai')=}")
```

```text
clean_text(raw_name)='aSHA kUMAR'
raw_name='Asha Kumar'
formatter_by_style['upper']('masala chai')='MASALA CHAI'
```

### Callbacks

A callback lets the caller decide what happens next by passing in a function.
The idea is identical to JavaScript callbacks; in Python they are usually
plain functions or short `lambda`s. (Python code does not use callbacks for
asynchronous work the way older JavaScript did; `async` / `await` covers that
in Phase 3.)

```python
def process_payment(
    amount: int,
    on_success: Callable[[int], str],
    on_failure: Callable[[str], str],
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
```

```text
receipt sent for ₹889
failed: amount must be positive
```

The type hint `Callable[[int], str]` reads "a callable that takes one `int`
and returns a `str`".

### Returning functions

A function can also build and **return** a function configured by its
arguments. How the inner function remembers `percent` after `make_discount`
has returned is a *closure*, the subject of Unit 1.11.

```python
def make_discount(percent: int) -> Callable[[float], float]:
    """Return a function that applies a fixed discount."""

    def apply(price: float) -> float:
        return round(price * (100 - percent) / 100, 2)

    return apply


festive_discount = make_discount(20)
print(f"{festive_discount(1000)=}")
print(f"{festive_discount.__qualname__=}")
```

```text
festive_discount(1000)=800.0
festive_discount.__qualname__='make_discount.<locals>.apply'
```

### Dispatch tables with `operator` functions

A **dispatch table** is a dict that maps a key to a function. It replaces a
long `if` / `elif` chain with one lookup, and adding a case means adding one
dict entry. The `operator` module provides every Python operator as a
function (`operator.lt` is `<`, `operator.add` is `+`), so the table needs no
`lambda`s. These functions are implemented in C, which makes them a little
faster than an equivalent `lambda` as well.

The example filters products with a rule read from a query string, such as
`price < 500`. `operator.itemgetter(field_name)` builds a function that
returns `item[field_name]`. (Lab 1.10, exercise 3, builds an arithmetic
dispatch table.)

```python
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
    return [
        product["name"]
        for product in products
        if compare(get_field(product), threshold)
    ]


print(f"{filter_products(catalog, 'price < 500')=}")
print(f"{filter_products(catalog, 'rating >= 4.5')=}")
```

```text
filter_products(catalog, 'price < 500')=['tea', 'dal']
filter_products(catalog, 'rating >= 4.5')=['tea', 'ghee']
```

> **Note:** A dispatch table is also safer than building code from user
> input. Only the six symbols in the dict can ever be called; an unknown
> symbol raises `KeyError` instead of running anything.

### Key points

| Idea | Takeaway |
| --- | --- |
| First-class | Functions are values: store, pass, return |
| `name` vs `name()` | Object vs call |
| Callbacks | Pass behaviour in as an argument |
| Returning functions | Configured by arguments (closures) |
| Dispatch table | Dict of key → function, no `elif` chain |
| `operator` | Every operator as a function |

## 1.10.7 `lambda`

### A single expression

`lambda parameters: expression` creates a small anonymous function. The body
is a **single expression**, and its value is returned automatically. A lambda
cannot contain statements: no `return`, no `if` block (the conditional
*expression* `a if cond else b` is fine), no loops, no assignments except the
walrus `:=`, no annotations and no docstring. JavaScript arrow functions can
have a full `{ ... }` body; Python lambdas cannot. Parameters work exactly as
in `def`, defaults included.

```python
print(f"{(lambda price: price * 2)(249)=}")
print(f"{(lambda first, second=10: first + second)(5)=}")
print(f"{compile_error('lambda order: return order')=}")
```

```text
(lambda price: price * 2)(249)=498
(lambda first, second=10: first + second)(5)=15
compile_error('lambda order: return order')='SyntaxError: invalid syntax'
```

Under the hood a lambda is compiled exactly like a `def`: it gets a code
object and a function object of the same type. The only differences are the
syntax and the name, which is always `<lambda>`.

### `key=` usage

The classic place for a lambda is a one-off function passed straight to a
higher-order function: the `key=` argument of `sorted`, `min`, `max`,
`list.sort` or `itertools.groupby`. When the key just reads an item or an
attribute, `operator.itemgetter` / `operator.attrgetter` say the same thing
without a lambda.

```python
by_price = sorted(catalog, key=lambda product: product["price"])
best_rated = max(catalog, key=lambda product: product["rating"])
by_price_getter = sorted(catalog, key=operator.itemgetter("price"))
print(f"{[product['name'] for product in by_price]=}")
print(f"{best_rated['name']=}")
print(f"{[product['name'] for product in by_price_getter]=}")
```

```text
[product['name'] for product in by_price]=['dal', 'tea', 'ghee']
best_rated['name']='ghee'
[product['name'] for product in by_price_getter]=['dal', 'tea', 'ghee']
```

### `<lambda>` in tracebacks

Every lambda has the same `__name__`: `<lambda>`. When an exception is raised
inside one, the traceback names the frame `<lambda>`, which tells you little
about *which* of your lambdas failed. A `def` function appears under its real
name. The helper below returns the name of the innermost frame of the
traceback.

```python
def failing_frame_name(func: Callable[[], object]) -> str:
    """Call func and return the name of the innermost traceback frame."""
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
```

```text
failing_frame_name(lambda: 498 / 0)='<lambda>'
failing_frame_name(unit_price_from_total)='unit_price_from_total'
(lambda: 0).__name__='<lambda>'
```

### When to prefer `def`

Use `def` as soon as the function gets a name, needs more than one
expression, deserves a docstring or type hints, or is used in more than one
place. Assigning a lambda to a variable is the clearest sign that a `def` was
wanted: PEP 8 says so explicitly, and `ruff` rule E731 flags it. The `def`
version is barely longer and has a proper `__name__`.

```python
add_delivery_fee = lambda total: total + 40  # noqa: E731


def add_delivery_fee_def(total: int) -> int:
    """Add the flat delivery fee."""
    return total + 40


print(f"{add_delivery_fee.__name__=}")
print(f"{add_delivery_fee_def.__name__=}")
```

```text
add_delivery_fee.__name__='<lambda>'
add_delivery_fee_def.__name__='add_delivery_fee_def'
```

> **Note:** In JavaScript, `const addFee = (total) => total + 40` is idiomatic
> and the engine even infers the name `addFee`. Python does not infer names
> for lambdas, so the same habit produces anonymous functions in tracebacks.

### Key points

| Idea | Takeaway |
| --- | --- |
| `lambda` | One expression, implicitly returned |
| Not allowed | Statements, annotations, docstrings |
| Best use | Inline `key=` functions |
| Alternatives | `itemgetter`, `attrgetter` |
| Tracebacks | Every lambda is `<lambda>` |
| Named lambda | Use `def` instead (E731) |

## 1.10.8 Docstrings and annotations

### PEP 257 docstrings

A **docstring** is a string literal written as the first statement of a
function, class or module. Unlike a `#` comment, it is kept at run time: the
compiler stores it in `__doc__`, where `help()`, IDEs and documentation
generators find it. JSDoc comments in JavaScript play the same role, but they
are only comments, invisible to the running program.

PEP 257 sets the conventions:

- Use triple double quotes, even for a one-line docstring.
- Start with a one-line summary in the imperative mood ("Return …", not
  "Returns …"), ending with a period.
- For more detail, add a blank line after the summary, then the details.

### Google style

The **Google style** adds named sections that tools such as Sphinx (with the
napoleon extension) and IDEs understand: `Args:`, `Returns:` and `Raises:`.

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

### `help()` and `inspect.getdoc()`

`help(func)` prints the signature (built from `inspect.signature`, annotations
included) followed by the docstring. `inspect.getdoc(func)` returns the
docstring with the indentation cleaned up, which is what tooling should use.

```python
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
```

```text
Help on function delivery_eta_days in module __main__:

delivery_eta_days(distance_km: float, *, express: bool = False) -> int
    Estimate delivery time in whole days.

    Args:
        distance_km: Road distance from the warehouse.
        express: Use the express courier (twice as fast).

    Returns:
        Days until delivery, at least 1.

    Raises:
        ValueError: If distance_km is negative.
```

The first line of the cleaned docstring is the summary, which is what IDE
tooltips and API indexes show:

```python
summary_line = inspect.getdoc(delivery_eta_days).splitlines()[0]
print(f"{summary_line=}")
print(f"{delivery_eta_days(1200)=}")
print(f"{delivery_eta_days(1200, express=True)=}")
```

```text
summary_line='Estimate delivery time in whole days.'
delivery_eta_days(1200)=3
delivery_eta_days(1200, express=True)=2
```

### Annotations are not enforced

Annotations (`quantity: int`, `-> int`) are stored in `__annotations__` and
read by tools: type checkers such as mypy (Phase 4), and libraries such as
FastAPI and Pydantic (Phase 6), which use them to validate and convert data.
The interpreter itself **never checks** arguments against them. A value of
the wrong type passes straight through until some operation fails, or, worse,
silently produces nonsense. TypeScript types are erased before the code runs,
so the situation is the same; the difference is that Python keeps the
annotations available at run time.

```python
def double_quantity(quantity: int) -> int:
    """Double a quantity."""
    return quantity * 2


print(f"{double_quantity(3)=}")
print(f"{double_quantity('3')=}  (no error: str * 2 repeats the text)")
for parameter_name, annotation in double_quantity.__annotations__.items():
    print(f"{parameter_name:8} -> {annotation!r}")
```

```text
double_quantity(3)=6
double_quantity('3')='33'  (no error: str * 2 repeats the text)
quantity -> <class 'int'>
return   -> <class 'int'>
```

> **Warning:** `double_quantity('3')` returned `'33'` without any error. If you
> need run-time validation (for example of data from an HTTP request), it has
> to be done explicitly, by your code or by a library such as Pydantic.

### Lazy annotation evaluation (new in 3.14)

Before Python 3.14, annotations were evaluated when the `def` statement ran.
Naming a class that was defined later in the module raised `NameError`, so
code used quoted strings (`"Invoice"`) or
`from __future__ import annotations`. Since 3.14 (PEP 649 and PEP 749),
annotations are **lazy**: the compiler turns them into a small function, and
that function runs only when someone asks for the annotations. A function can
now name a class that does not exist yet, with no quotes.

The new `annotationlib` module asks for annotations in different formats:

| Format | Returns |
| --- | --- |
| `Format.VALUE` | Evaluated objects (`NameError` if undefined) |
| `Format.FORWARDREF` | Values, or `ForwardRef` placeholders |
| `Format.STRING` | The annotations as source strings |

Reading `__annotations__` directly is the same as asking for `Format.VALUE`.
The example asks before and after the classes exist.

```python
if sys.version_info >= (3, 14):
    import annotationlib

    def print_invoice(invoice: Invoice) -> Receipt:  # noqa: F821
        """Annotations name classes that do not exist yet."""
        return Receipt()  # noqa: F821

    Format = annotationlib.Format
    as_strings = annotationlib.get_annotations(
        print_invoice, format=Format.STRING
    )
    print(f"{as_strings=}")
    forward_refs = annotationlib.get_annotations(
        print_invoice, format=Format.FORWARDREF
    )
    print(f"{type(forward_refs['invoice']).__name__=}")
    value_error = raised_error_name(lambda: print_invoice.__annotations__)
    print(f"VALUE before the classes exist: {value_error}")

    class Invoice:
        """Defined after the function."""

    class Receipt:
        """Defined after the function."""

    for name, annotation in print_invoice.__annotations__.items():
        print(f"{name:8} -> {annotation!r}")
else:
    print("lazy annotations need Python 3.14; skipped")
```

```text
as_strings={'invoice': 'Invoice', 'return': 'Receipt'}
type(forward_refs['invoice']).__name__='ForwardRef'
VALUE before the classes exist: NameError
invoice  -> <class '__main__.Invoice'>
return   -> <class '__main__.Receipt'>
```

Defining the function did not fail, even though neither class existed. Only
the request for evaluated values failed, and the same request succeeded once
the classes had been defined.

### Key points

| Idea | Takeaway |
| --- | --- |
| Docstring | First string in the body, kept in `__doc__` |
| PEP 257 | Imperative one-line summary, then details |
| Google style | `Args:`, `Returns:`, `Raises:` sections |
| `help()` | Signature plus docstring |
| Annotations | Stored, never enforced by Python |
| 3.14+ | Lazy; read with `annotationlib` |

## 1.10.9 Recursion basics

### Base case and recursive case

A recursive function solves a problem by calling itself on a smaller version
of the same problem. It needs two parts: a **base case** that returns an
answer directly, without recursing, and a **recursive case** that moves
toward the base case. Each call waits for the inner call to return, then
finishes its own work.

```text
factorial(4) = 4 * factorial(3)
                 = 3 * factorial(2)
                     = 2 * factorial(1)
                         = 1            (base case)
```

The example writes factorial both recursively and iteratively and checks
both against `math.factorial` for 0 to 29.

```python
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
    factorial_recursive(n) == factorial_iterative(n) == math.factorial(n)
    for n in range(30)
)
print(f"{versions_agree=}  (0! to 29!)")
```

```text
factorial_recursive(10)=3628800, factorial_iterative(10)=3628800
versions_agree=True  (0! to 29!)
```

### Where recursion fits

For factorial the loop is simpler and faster. Recursion earns its place with
naturally nested data: trees, nested lists, JSON documents, directory
structures. Summing an arbitrarily nested price list takes three lines
recursively; a loop would need an explicit stack (Unit 1.6).

```python
def total_price(node: int | list[Any]) -> int:
    """Sum all ints in an arbitrarily nested list."""
    if isinstance(node, int):  # base case
        return node
    return sum(total_price(child) for child in node)


gift_hamper = [249, [640, [162, 80]], [], 525]
print(f"{total_price(gift_hamper)=}")
```

```text
total_price(gift_hamper)=1656
```

### Recursion-limit preview

Every call pushes a new *frame* (local variables, the current instruction) on
the call stack. CPython caps the depth of Python-level calls at
`sys.getrecursionlimit()`, usually 1000, and raises `RecursionError` instead
of letting the process crash. JavaScript engines have a similar limit and
throw `RangeError: Maximum call stack size exceeded`.

Python does **not** optimize tail calls: even a call in tail position keeps
its frame, by design, so that tracebacks stay complete. Deep recursion must
therefore be rewritten as a loop. A missing base case hits the limit almost
immediately. Unit 1.12 looks at frames and the call stack in detail.

```python
def countdown_without_base_case(number: int) -> int:
    """Never stops: there is no base case."""
    return countdown_without_base_case(number - 1)


print(f"{sys.getrecursionlimit()=}")
no_base = raised_error_name(lambda: countdown_without_base_case(5))
print(f"no base case: {no_base}")
print(f"too deep: {raised_error_name(lambda: factorial_recursive(50_000))}")
print(f"{factorial_iterative(5_000).bit_length()=}  (no depth limit)")
```

```text
sys.getrecursionlimit()=1000
no base case: RecursionError
too deep: RecursionError
factorial_iterative(5_000).bit_length()=54233  (no depth limit)
```

> **Warning:** Raising the limit with `sys.setrecursionlimit()` is rarely the
> right fix. It only moves the problem, and a very high limit can overflow the
> C stack and crash the interpreter. Prefer a loop or an explicit stack.

### Key points

| Idea | Takeaway |
| --- | --- |
| Base case | Returns without recursing; write it first |
| Recursive case | Must move toward the base case |
| Good fit | Nested data: trees, nested lists, JSON |
| Limit | About 1000 frames → `RecursionError` |
| Tail calls | Not optimized; use a loop for depth |

## Lab 1.10

Three exercises that use the parameter kinds, argument unpacking and dispatch
tables from this unit. In the notebook, each exercise has a stub and a check
cell that prints `PASS` or `FAIL` per test case. Try each one before opening
the solution.

### Exercise 1 — `build_query_string`

Write
`build_query_string(base_url, /, *, page=1, page_size=20, **filters)`. It
returns `base_url + "?" + query`, where the query lists `page`, then
`page_size`, then every filter **in the order the caller gave them**,
URL-encoded with `urllib.parse.urlencode` (spaces become `+`).

- Skip filters whose value is `None`.
- Raise `ValueError` if `page < 1` or `page_size` is not between 1 and 100.
- Keep the exact signature: `base_url` positional-only (so a filter may itself
  be called `base_url`), `page` and `page_size` keyword-only.

| Call | Expected |
| --- | --- |
| `build_query_string("/api/products")` | `/api/products?page=1&page_size=20` |
| `…("/api/products", page=2, category="tea", max_price=500)` | `…?page=2&page_size=20&category=tea&max_price=500` |
| `…("/search", q="masala chai", city=None)` | `/search?page=1&page_size=20&q=masala+chai` |
| `…("/api", base_url="mirror")` | `/api?page=1&page_size=20&base_url=mirror` |
| `…("/api", 2)` | `TypeError` (page is keyword-only) |
| `…("/api", page=0)` | `ValueError` |
| `…("/api", page_size=101)` | `ValueError` |

A last check reads the parameter kinds with `inspect.signature` and expects
`POSITIONAL_ONLY`, `KEYWORD_ONLY`, `KEYWORD_ONLY`, `VAR_KEYWORD`.

**Hints:**

- `**filters` is an ordered dict, so iterating `filters.items()` keeps the
  caller's order.
- `urlencode` accepts a list of `(name, value)` pairs, which keeps your order
  exactly.
- Validate first (guard clauses), then build the list of pairs.

### Exercise 2 — `apply_pipeline`

Write `apply_pipeline(value, *transforms)`. Apply each transform to the result
of the previous one, left to right, and return the final value. With no
transforms, return `value` itself (the same object).

| Call | Expected |
| --- | --- |
| `apply_pipeline("  Masala Chai ", *slug_steps)` | `'masala-chai'` |
| `apply_pipeline(10, lambda n: n + 5, lambda n: n * 2)` | `30` |
| `apply_pipeline(10, lambda n: n * 2, lambda n: n + 5)` | `25` |
| `apply_pipeline(original_list) is original_list` | `True` |
| `apply_pipeline([3, 1, 2], sorted, tuple)` | `(1, 2, 3)` |
| `apply_pipeline("42", int, float, str)` | `'42.0'` |

Here `slug_steps` is
`[str.strip, str.lower, lambda text: text.replace(" ", "-")]`.

**Hints:**

- `transforms` is a tuple of functions; a plain `for` loop is enough.
- Rebind `value` on each step. With an empty tuple the loop does nothing, and
  the original object is returned untouched.

### Exercise 3 — `calculate` with a dispatch table

Fill an `OPERATIONS` dict with **`operator` module functions** (no `lambda`)
for these names: `"add"`, `"subtract"`, `"multiply"`, `"divide"` (true
division), `"floor_divide"`, `"modulo"`, `"power"`. Then write
`calculate(operation_name, left, right)`, which looks the name up and calls
the function, with no `if` / `elif` chain over the names. An unknown name
raises `ValueError("unknown operation: <name>")`. Division by zero raises
`ZeroDivisionError` naturally.

| Call | Expected |
| --- | --- |
| `calculate("add", 2, 3)` | `5` |
| `calculate("subtract", 2, 3)` | `-1` |
| `calculate("multiply", 249, 2)` | `498` |
| `calculate("divide", 7, 2)` | `3.5` |
| `calculate("floor_divide", -7, 2)` | `-4` |
| `calculate("modulo", -7, 3)` | `2` |
| `calculate("power", 2, 10)` | `1024` |
| `calculate("divide", 1, 0)` | `ZeroDivisionError` |
| `calculate("sqrt", 9, 0)` | `ValueError` |

Two more checks expect `sorted(OPERATIONS)` to be the seven names and
`OPERATIONS["add"] is operator.add`.

**Hints:**

- The `operator` names are `add`, `sub`, `mul`, `truediv`, `floordiv`, `mod`
  and `pow`.
- `OPERATIONS.get(name)` returns `None` for an unknown name, which you can
  turn into the `ValueError`.

<details><summary>Solution</summary>

```python
MAX_PAGE_SIZE = 100


def build_query_string(
    base_url: str, /, *, page: int = 1, page_size: int = 20, **filters: object
) -> str:
    """Return base_url with page, page_size and the non-None filters."""
    if page < 1:
        raise ValueError(f"page must be at least 1, got {page}")
    if not 1 <= page_size <= MAX_PAGE_SIZE:
        raise ValueError(
            f"page_size must be between 1 and {MAX_PAGE_SIZE}, got {page_size}"
        )
    query_pairs = [
        ("page", page),
        ("page_size", page_size),
        *(
            (name, value)
            for name, value in filters.items()
            if value is not None
        ),
    ]
    return f"{base_url}?{urlencode(query_pairs)}"


def apply_pipeline(value: Any, *transforms: Callable[[Any], Any]) -> Any:
    """Return value passed through every transform, left to right."""
    for transform in transforms:
        value = transform(value)
    return value


OPERATIONS: dict[str, Callable[[float, float], float]] = {
    "add": operator.add,
    "subtract": operator.sub,
    "multiply": operator.mul,
    "divide": operator.truediv,
    "floor_divide": operator.floordiv,
    "modulo": operator.mod,
    "power": operator.pow,
}


def calculate(operation_name: str, left: float, right: float) -> float:
    """Apply the named operation from OPERATIONS to left and right."""
    operation = OPERATIONS.get(operation_name)
    if operation is None:
        raise ValueError(f"unknown operation: {operation_name}")
    return operation(left, right)
```

With the solutions in place, the notebook's check cells print:

```text
Exercise 1
PASS  defaults
PASS  filters in call order
PASS  None filters skipped
PASS  filter named base_url
PASS  page is keyword-only
PASS  page 0
PASS  page_size 101
PASS  parameter kinds
8/8 checks passed
Exercise 2
PASS  slug pipeline
PASS  numbers
PASS  order matters
PASS  no transforms returns the same object
PASS  built-ins as transforms
PASS  types can change
6/6 checks passed
Exercise 3
PASS  add
PASS  subtract
PASS  multiply
PASS  divide
PASS  floor_divide
PASS  modulo
PASS  power
PASS  divide by zero
PASS  unknown operation
PASS  table has the seven names
PASS  table uses operator functions
11/11 checks passed
```

Notes on the solution:

- Because `base_url` is positional-only, `base_url="mirror"` is not a
  duplicate argument; it lands in `**filters` like any other name.
- The star inside the list (`*(...)`) spreads the generator of filter pairs
  into the list after the two fixed pairs.
- `apply_pipeline` returns the original object when there are no transforms,
  because the loop body never runs and `value` is never rebound.
- `calculate` has one lookup instead of seven branches; a new operation is one
  more dict entry.

</details>

## Recap

| Concept | Takeaway | JavaScript equivalent |
| --- | --- | --- |
| `def` | Runs when reached; no hoisting | Hoisted declarations |
| Function attributes | `__name__`, `__defaults__`, `__code__`, … | `name`, `length` |
| Return values | No `return` → `None`; `a, b` is a tuple | `undefined`; return an array |
| Parameter kinds | `pos, /, std, *args, kw, **kwargs` | Rest params, options object |
| `*args` / `**kwargs` | Extra args as tuple / dict | `...args` (array) |
| `inspect.signature` | Read kinds and defaults | `fn.length` |
| Call unpacking | `f(*values, **options)` | `f(...values)` |
| Defaults | Evaluated once; no mutable defaults | Evaluated per call |
| `None` / `sentinel()` | Fresh object / "not passed" | `undefined` vs `null` |
| First-class functions | Store, pass, return; dispatch tables | Same |
| `lambda` | One expression; good for `key=` | Arrow functions |
| Docstrings | PEP 257 summary + Google sections | JSDoc |
| Annotations | Not enforced; lazy since 3.14 | TypeScript (erased) |
| Recursion | Base case; ~1000 frames; no TCO | Similar stack limits |

## Further reading

- [Tutorial: defining functions](https://docs.python.org/3/tutorial/controlflow.html#defining-functions)
- [Tutorial: more on defining functions](https://docs.python.org/3/tutorial/controlflow.html#more-on-defining-functions)
- [Reference: function definitions](https://docs.python.org/3/reference/compound_stmts.html#function-definitions)
- [Reference: user-defined function attributes](https://docs.python.org/3/reference/datamodel.html#user-defined-functions)
- [`inspect`: the Signature object](https://docs.python.org/3/library/inspect.html#introspecting-callables-with-the-signature-object)
- [`operator` module](https://docs.python.org/3/library/operator.html)
- [`annotationlib` module](https://docs.python.org/3/library/annotationlib.html)
- [PEP 257 — Docstring conventions](https://peps.python.org/pep-0257/)
- [PEP 570 — Positional-only parameters](https://peps.python.org/pep-0570/)
- [PEP 3102 — Keyword-only arguments](https://peps.python.org/pep-3102/)
- [PEP 468 — Preserving keyword argument order](https://peps.python.org/pep-0468/)
- [PEP 661 — Sentinel values](https://peps.python.org/pep-0661/)
- [PEP 649 — Deferred evaluation of annotations](https://peps.python.org/pep-0649/)
- [PEP 749 — Implementing PEP 649](https://peps.python.org/pep-0749/)

[← Previous](unit-1-9-iteration-comprehensions-and-built-in-functions.md) · [Index](README.md) · [Next →](unit-1-11-scope-namespaces-and-closures.md)
