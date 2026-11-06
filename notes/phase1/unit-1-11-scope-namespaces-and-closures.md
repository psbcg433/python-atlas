# Unit 1.11 — Scope, Namespaces and Closures

[← Previous](unit-1-10-functions-definition-and-arguments.md) · [Index](README.md) · [Next →](unit-1-12-decorators-functools-and-the-call-stack.md)

Every time Python meets a name such as `total` or `len`, it has to decide which
object that name means. This unit explains the machinery behind that decision:
the namespaces that hold names, the LEGB rule that searches them, the fact that
scope is fixed when a function is compiled, and the cell objects that let
closures keep variables alive after their function has returned. These ideas
are the foundation for decorators in Unit 1.12.

## What you will learn

- The four kinds of namespace (built-in, module, class, function) and how to
  inspect them with `globals()`, `locals()` and the `builtins` module.
- How the LEGB rule resolves any name, and how to spot a shadowed built-in.
- Why Python has no block scope, and which constructs *do* create a scope.
- Why `UnboundLocalError` happens, seen from the compiler's point of view
  (`co_varnames`, `LOAD_FAST_CHECK`).
- How to use `global` and `nonlocal` correctly, and why passing state
  explicitly is usually better.
- How a closure stores its variables in cell objects, and how to fix the
  late-binding trap.
- What each kind of name lookup costs, and when a local alias is worth it.

## JavaScript → Python bridge

Scoping is one of the places where Python and JavaScript look alike but behave
differently. JavaScript has had block scope since `let` and `const`; Python never
had it. JavaScript lets an inner function assign an outer variable directly;
Python needs a declaration for that. The table lists the closest equivalents and
the difference that usually surprises people.

| JavaScript | Python | The difference that bites |
| --- | --- | --- |
| `let` / `const` blocks | Function, class, module scope | `if` / `for` names survive the block |
| `var` hoisting | Any assignment makes a local | Early read: `UnboundLocalError` |
| `let` dead zone | `UnboundLocalError` | Same idea, fixed at compile time |
| Assign outer var | `nonlocal` / `global` | Without them you get a new local |
| `globalThis` | `globals()`, `builtins` | Each module has its own globals |
| Closures capture variables | Closures capture cells | Same late binding |
| `for (let i …)` callbacks | `lambda i=i: …` | Python loops reuse one variable |

### Setup used by the examples

Every example in this unit runs after this setup block. `show_size` was
introduced in Unit 1.2, `raised_error_name` calls a zero-argument function (a
*thunk*) and returns the name of the exception it raised, and `compile_error`
(from Unit 1.8) compiles source text without running it, so compile-time errors
can be shown without crashing the example.

```python
import builtins
import dis
import functools
import inspect
import io
import math
import re
import sys
import timeit
from collections.abc import Callable
from typing import Any


def show_size(label: str, obj: object) -> None:
    """Print the shallow size in bytes, the type and the id of an object."""
    print(
        f"{label}: {sys.getsizeof(obj)} bytes, "
        f"type={type(obj).__name__}, id={id(obj)}"
    )


def raised_error_name(thunk: Callable[[], object]) -> str:
    """Call thunk and return the name of the exception it raised."""
    try:
        thunk()
    except Exception as error:
        return type(error).__name__
    return "no error"


def compile_error(source: str) -> str:
    """Compile source without running it; report a SyntaxError if any."""
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

## 1.11.1 Namespaces

A **namespace** is a mapping from names to objects. When you write
`price = 250`, Python stores the key `"price"` with a reference to the integer
object `250` in some namespace. Which namespace depends on where the statement
runs. Python keeps several namespaces at once, and they have very different
lifetimes: the built-in namespace lives as long as the interpreter, a module
namespace usually lives until the interpreter exits, and a function namespace
is created fresh on every call and thrown away when the call returns.

| Namespace | Created | Lives until | Inspect with |
| --- | --- | --- | --- |
| Built-in | Interpreter start | Interpreter exit | `vars(builtins)` |
| Module | First import | Exit (usually) | `globals()` |
| Class | `class` body runs | Becomes `__dict__` | `vars(SomeClass)` |
| Function | **Each call** | Call returns | `locals()` |

A function namespace can outlive its call in one case: when an inner function
(a closure) still needs one of its variables. That case is the subject of
1.11.6.

JavaScript has a similar layering (the global object, module scope, function
scope, block scope), but it hides the containers. Python exposes most of them as
ordinary dicts you can read, and sometimes write.

### Module namespace

Each module has one global namespace, and it is the module's own `__dict__`. A
script run directly, or a notebook, is the module `__main__`. `globals()`
returns that dict itself, not a copy, so writing a key into it creates a
variable just as an assignment would. This is the Python counterpart of
`globalThis`, with one important difference: there is no single global object
shared by all modules. "Global" in Python always means "module-level".

```python
main_module = sys.modules[__name__]
print(f"{__name__=}")
print(f"{globals() is main_module.__dict__=}")

globals()["created_through_globals"] = "hello"
print(f"{created_through_globals=}")  # noqa: F821
print(f"{'show_size' in globals()=}, {'len' in globals()=}")
```

```text
__name__='__main__'
globals() is main_module.__dict__=True
created_through_globals='hello'
'show_size' in globals()=True, 'len' in globals()=False
```

Look at the last line: `len` is **not** in `globals()`. Built-in functions are
not copied into each module; they live in their own namespace, which is
searched after the module namespace (1.11.2).

### Function namespace

Every call to a function gets a fresh local namespace holding its parameters
and the names it assigns. Inside a function, `locals()` returns a dict
*snapshot* of that namespace. Since Python 3.13 (PEP 667) the semantics are
precise: each call to `locals()` in a function builds a new, independent dict,
and writing to it never changes the real local variables.

```python
def price_with_tax(base_price: int, tax_percent: int = 18) -> int:
    """Show the local namespace of one call."""
    tax_amount = base_price * tax_percent // 100
    print(f"  locals()={locals()}")
    return base_price + tax_amount


print(price_with_tax(500))
print(price_with_tax(1000, 5))


def try_to_write_locals() -> int:
    """Writing to the locals() snapshot does not create a variable."""
    local_snapshot = locals()
    local_snapshot["discount"] = 50
    return len(local_snapshot)


print(f"{try_to_write_locals()=}")
print("the variable 'discount' was never created")
```

```text
  locals()={'base_price': 500, 'tax_percent': 18, 'tax_amount': 90}
590
  locals()={'base_price': 1000, 'tax_percent': 5, 'tax_amount': 50}
1050
try_to_write_locals()=1
the variable 'discount' was never created
```

`try_to_write_locals()` returns 1. When `locals()` ran, no local had a value
yet (`local_snapshot` is assigned only after the call returns), so the snapshot
started empty, and its one key is the `discount` we wrote into the dict. The
dict changed; the function's namespace did not, and no variable named
`discount` exists.

> **Note:** At module level `locals()` and `globals()` are the same dict, so
> writing to it *does* create variables there. The snapshot rule applies only
> inside functions.

### Class namespace

A `class` body is ordinary code that runs once, top to bottom, in its own
namespace. When the body finishes, that namespace becomes the class's
`__dict__`, wrapped in a read-only `mappingproxy`. The trap for JavaScript
developers: names defined in the class body are **not** visible inside the
methods. A method body looks in its own locals, then the module, then the
built-ins, and skips the class entirely. Methods must reach class attributes
through `self` or through the class name.

```python
class MenuItem:
    """A class whose body defines a name and two methods."""

    tax_percent = 5
    print(f"  inside the class body: {sorted(locals())}")

    def tax_without_self(self) -> int:
        """Looks in the local, global and built-in scopes only."""
        return tax_percent  # noqa: F821 (deliberate: class scope is skipped)

    def tax_with_self(self) -> int:
        """Finds the class attribute through the instance."""
        return self.tax_percent


print(f"{type(vars(MenuItem)).__name__=}")
print(f"{vars(MenuItem)['tax_percent']=}")
print(f"{MenuItem().tax_with_self()=}")
print(f"tax_without_self(): {raised_error_name(MenuItem().tax_without_self)}")
```

```text
  inside the class body: ['__doc__', '__firstlineno__', '__module__',
'__qualname__', 'tax_percent']
type(vars(MenuItem)).__name__='mappingproxy'
vars(MenuItem)['tax_percent']=5
MenuItem().tax_with_self()=5
tax_without_self(): NameError
```

> **Note:** The first output line was wrapped to fit the screen; Python prints
> the list on one line. `__firstlineno__` is new in Python 3.13.

> **Warning:** In a JavaScript class, a method can call another method or read
> a field only through `this`, so the habit transfers well. The surprise is
> that a plain name like `tax_percent` inside a method does not raise a
> compile error: it compiles as a global lookup and fails with `NameError` only
> when the method runs.

### Built-in namespace

`len`, `print`, `ValueError` and the other built-ins live in the `builtins`
module. Every module also has a `__builtins__` name, but it is an
implementation detail: in `__main__` it is the `builtins` module itself, in
other modules it is that module's `__dict__`. In your own code always write
`import builtins`.

```python
builtin_names = [name for name in vars(builtins) if not name.startswith("_")]
print(f"{len(builtin_names)=} public built-in names")
print(f"{builtins.len is len=}, {builtins.ValueError is ValueError=}")
print(f"first few: {sorted(builtin_names)[:3]}")
print(f"{type(__builtins__).__name__=}  (in __main__)")
```

```text
len(builtin_names)=153 public built-in names
builtins.len is len=True, builtins.ValueError is ValueError=True
first few: ['ArithmeticError', 'AssertionError', 'AttributeError']
type(__builtins__).__name__='module'  (in __main__)
```

> **Note:** The count depends on the Python version and the environment. This
> output comes from a plain script; inside Jupyter the same code printed 155,
> because IPython adds a couple of names (such as `display`) to `builtins`.

### Under the hood: function locals are not a dict

Module and class namespaces really are dicts. Function locals are not. When
CPython compiles a function, it gives each local variable a slot number, and at
run time the frame stores the values in a C array ("fast locals"). Reading a
local is then an array index, not a hash lookup. `locals()` builds a dict from
that array on demand, which is why it is a snapshot. The code object lists the
slots in `co_varnames` (parameters first) and counts them in `co_nlocals`.

```python
price_code = price_with_tax.__code__
print(f"{price_code.co_varnames=}")
print(f"{price_code.co_nlocals=}, {price_code.co_argcount=}")
print(f"{inspect.isfunction(price_with_tax)=}")
```

```text
price_code.co_varnames=('base_price', 'tax_percent', 'tax_amount')
price_code.co_nlocals=3, price_code.co_argcount=2
inspect.isfunction(price_with_tax)=True
```

### Key points

| Idea | Takeaway |
| --- | --- |
| Namespace | A mapping from names to objects |
| `globals()` | The module's real `__dict__`; writes create names |
| `locals()` in a function | A fresh snapshot; writes are ignored (3.13+) |
| Class body | Becomes `__dict__`; invisible to methods |
| Built-ins | Separate `builtins` module, searched last |
| Fast locals | Slots in a C array, listed in `co_varnames` |

## 1.11.2 The LEGB rule

To find the object a name refers to, Python searches up to four scopes in a
fixed order and stops at the first one that has the name. The order is spelled
**LEGB**:

- **L — Local:** the current function's own names (parameters and anything it
  assigns).
- **E — Enclosing:** the locals of any enclosing *functions*, from the inside
  out.
- **G — Global:** the module namespace.
- **B — Built-in:** the `builtins` module.

If none of them has the name, Python raises `NameError`.

```text
  name lookup
       |
       v
  L: Local        current function
       | not found
       v
  E: Enclosing    outer functions, inside out
       | not found
       v
  G: Global       module namespace
       | not found
       v
  B: Built-in     builtins module
       | not found
       v
  NameError

  (the search stops at the first scope that has the name)
```

This is the same idea as JavaScript's scope chain, with two differences. First,
there is no block level in the chain (1.11.3). Second, class bodies are **not**
an enclosing scope for the methods inside them, as 1.11.1 showed.

The next example defines the same name at two levels and lets the lookup find
each one. `inner_report` has no local `currency_symbol`, so it finds the
enclosing one; `len` is found all the way down in the built-ins.
`global_report` has neither a local nor an enclosing binding, so it falls
through to the module.

```python
currency_symbol = "Rs"  # global


def outer_report() -> Callable[[], str]:
    """Enclosing function with its own currency_symbol."""
    currency_symbol = "₹"  # enclosing

    def inner_report() -> str:
        """Uses the nearest currency_symbol and the built-in len."""
        return f"{currency_symbol} (name length {len(currency_symbol)})"

    return inner_report


def global_report() -> str:
    """No local or enclosing binding: falls through to the global."""
    return currency_symbol


print(f"{outer_report()()=}")
print(f"{global_report()=}")
```

```text
outer_report()()='₹ (name length 1)'
global_report()='Rs'
```

`inspect.getclosurevars` reports where each free name of a function was found:
in an enclosing function (`nonlocals`), the module (`globals`), the built-ins
(`builtins`), or nowhere (`unbound`). The notebook printed the whole
`ClosureVars` tuple; here the interesting fields are printed one per line.

```python
inner_vars = inspect.getclosurevars(outer_report())
global_vars = inspect.getclosurevars(global_report)
print(f"{inner_vars.nonlocals=}")
print(f"{inner_vars.builtins=}")
print(f"{global_vars.globals=}")
print(f"{global_vars.unbound=}")
```

```text
inner_vars.nonlocals={'currency_symbol': '₹'}
inner_vars.builtins={'len': <built-in function len>}
global_vars.globals={'currency_symbol': 'Rs'}
global_vars.unbound=set()
```

### Shadowing built-ins

Because the global scope is searched before the built-in scope, a module-level
assignment such as `list = [...]` hides the built-in `list` for the whole
module. Nothing fails at the assignment. The error comes much later, wherever
some other line calls `list(...)`, often far from the cause. `del list`
removes the global binding and uncovers the built-in again, because the built-in
itself was never touched.

The next example runs the mistake inside `exec` with a fresh, empty globals
dict, so the surrounding module's `list` stays intact.

```python
shadowing_module = """
list = ["idli", "dosa"]
try:
    letters = list("abc")
except TypeError as error:
    print(f"  {type(error).__name__}: {error}")
del list
print(f"  after del: {list('abc')}")
"""
exec(shadowing_module, {})
print(f"{list('ok')=}  (this module's list is untouched)")
```

```text
  TypeError: 'list' object is not callable
  after del: ['a', 'b', 'c']
list('ok')=['o', 'k']  (this module's list is untouched)
```

A parameter or local variable with a built-in's name shadows it only inside
that function. That is common and usually harmless (`id`, `type`, `input` and
`filter` are popular parameter names), until the function needs the built-in
itself. The fix inside such a function is `builtins.type(...)`, or better, a
different parameter name.

```python
def describe_order(id: int, type: str) -> str:
    """Parameters named id and type hide the built-ins in here."""
    try:
        return f"order {id} of kind {type}, class {type(id).__name__}"
    except TypeError as error:
        return f"{builtins.type(error).__name__}: {error}"


print(describe_order(42, "express"))
order_id = 42
print(f"{type(order_id).__name__=}  (outside, type is the built-in)")
```

```text
TypeError: 'str' object is not callable
type(order_id).__name__='int'  (outside, type is the built-in)
```

> **Warning:** Linters flag shadowed built-ins (Ruff rules `A001`/`A002`). The
> common offenders at module level are `list`, `dict`, `str`, `id`, `input`,
> `sum`, `max` and `file`. In JavaScript the nearest equivalent is naming a
> variable `name` or `Array` at the top level of a script.

### Predict the output

```python
stock = 100

def outer():
    stock = 50
    def inner():
        return stock
    stock = 25
    return inner()

print(outer(), stock)
```

<details><summary>Answer</summary>

```text
25 100
```

`inner` finds `stock` in the enclosing scope, and it reads the variable **when
it is called**, by which time `outer` has rebound it to 25. The global `stock`
is never touched: both assignments inside `outer` create an `outer` local. The
fully typed version of this snippet, run as a script, prints the same line.

</details>

### Key points

| Idea | Takeaway |
| --- | --- |
| LEGB | Local → Enclosing → Global → Built-in |
| Not found | `NameError` |
| Class bodies | Not part of the chain for methods |
| `getclosurevars` | Shows where each free name was found |
| Global shadowing | `list = [...]` hides the built-in module-wide |
| Undo it | `del list` uncovers the built-in |

## 1.11.3 No block scope

Only modules, classes, functions, comprehensions and lambdas create scopes.
Blocks (`if`, `for`, `while`, `with`, `try`) do **not**. A name bound inside a
block is an ordinary variable of the surrounding function or module, and it is
still there after the block ends. For a JavaScript developer this is the
behaviour of `var`, not of `let`. It is not an accident: Python has no variable
declarations, so there is no syntax that could say "this name belongs to this
block only", and the language chose the simpler model.

The example binds a name inside each kind of block and reads it afterwards.

```python
def block_survivors(order_total: int) -> dict[str, Any]:
    """Names bound inside if / for / with / try survive the block."""
    if order_total > 1000:
        shipping_label = "free shipping"
    else:
        shipping_label = "Rs 49 shipping"

    for line_number in range(1, 4):  # noqa: B007
        pass  # the loop variable keeps its last value

    with io.StringIO("receipt text") as log_file:
        pass  # the buffer is closed, but the name still exists

    try:
        parsed_quantity = int("3")
    except ValueError:
        parsed_quantity = 0

    return {
        "shipping_label": shipping_label,
        "line_number": line_number,
        "log_file_closed": log_file.closed,
        "parsed_quantity": parsed_quantity,
    }


for key, value in block_survivors(1500).items():
    print(f"{key}: {value!r}")
```

```text
shipping_label: 'free shipping'
line_number: 3
log_file_closed: True
parsed_quantity: 3
```

The idiom of setting a variable in both branches of an `if` and using it
afterwards is normal Python. You do not need to "declare it first" with
`shipping_label = None` as you might in JavaScript with `let`.

Two consequences need care:

- If a `for` loop never runs (an empty iterable), its loop variable is
  **never bound**, and reading it later fails with `UnboundLocalError`.
- `except ... as error` is the one exception to the rule. Python **deletes**
  `error` at the end of the `except` block. The exception holds its traceback,
  the traceback holds the frame, and the frame holds `error`, which would form
  a reference cycle and keep every local of the frame alive. Copy the exception
  to another name if you need it later.

```python
def last_item(items: list[str]) -> str:
    """Return the loop variable after the loop (broken for [])."""
    for item in items:  # noqa: B007
        pass
    return item


def error_after_except() -> str:
    """The 'as' name is deleted when the except block ends."""
    try:
        int("not a number")
    except ValueError as error:
        saved_error = error
    error_exists = "error" in locals()
    return f"{type(saved_error).__name__}; error itself: {error_exists}"


print(f"{last_item(['tea', 'coffee'])=}")
print(f"last_item([]): {raised_error_name(lambda: last_item([]))}")
print(f"{error_after_except()=}")
```

```text
last_item(['tea', 'coffee'])='coffee'
last_item([]): UnboundLocalError
error_after_except()='ValueError; error itself: False'
```

### Comprehensions and lambdas do have their own scope

The loop variable of a comprehension does not leak into the surrounding code.
(It did in Python 2 list comprehensions; Python 3 fixed that.) A lambda is a
function, so its parameters are its own locals. Since Python 3.12, list, dict
and set comprehensions are *inlined* into the surrounding function (PEP 709):
CPython no longer creates and calls a hidden function object for each one,
which makes them faster, but the compiler still keeps the loop variable
isolated. Generator expressions are still separate functions.

The one deliberate leak is the walrus operator `:=`. An assignment expression
inside a comprehension binds the name in the **enclosing** scope (PEP 572), so
you can keep a value computed during the comprehension.

```python
def comprehension_scope() -> dict[str, Any]:
    """Comprehension and lambda variables stay inside; := leaks."""
    prices = [120, 80, 250]
    doubled = [price * 2 for price in prices]
    with_tax = [(taxed := price * 118 // 100) for price in prices]
    add_one = lambda value: value + 1  # noqa: E731
    return {
        "doubled": doubled,
        "price leaked": "price" in locals(),
        "value leaked": "value" in locals(),
        "taxed (walrus)": taxed,
        "with_tax": with_tax,
        "add_one(1)": add_one(1),
    }


for key, value in comprehension_scope().items():
    print(f"{key}: {value}")
```

```text
doubled: [240, 160, 500]
price leaked: False
value leaked: False
taxed (walrus): 295
with_tax: [141, 94, 295]
add_one(1): 2
```

`taxed` holds 295, the value from the last iteration, because `:=` wrote it into
`comprehension_scope`'s own namespace.

### Key points

| Idea | Takeaway |
| --- | --- |
| Scopes | Module, class, function, comprehension, lambda |
| Blocks | `if` / `for` / `while` / `with` / `try` add none |
| Loop variable | Keeps its last value; unbound if no iterations |
| `except … as e` | `e` is deleted when the block ends |
| Comprehensions | Own scope, inlined since 3.12 (PEP 709) |
| Walrus `:=` | Binds in the enclosing scope on purpose |

## 1.11.4 Compile-time scope decisions

Here is the rule that causes most scope surprises in Python: **scope is decided
when the function is compiled, not while it runs.** Before a function ever
executes, the compiler scans its whole body. If a name is assigned *anywhere*
in that body, the name is local for the **whole** function, including the
lines before the assignment. "Assigned" covers every binding form: `=`,
augmented assignment such as `+=`, `for name in`, `import name`, `def name`,
`class name`, `with ... as name` and `except ... as name`.

A local that is read before it has been given a value raises
`UnboundLocalError`. The classic case reads a global and then updates it:

```python
stock_count = 10


def sell_one() -> int:
    """Reads stock_count, then assigns it: the compiler made it local."""
    print(f"  selling one of {stock_count}")  # noqa: F823
    stock_count -= 1
    return stock_count


try:
    sell_one()
except UnboundLocalError as error:
    print(f"{type(error).__name__}: {error}")
print(f"{issubclass(UnboundLocalError, NameError)=}")
```

```text
UnboundLocalError: cannot access local variable 'stock_count' where it is
not associated with a value
issubclass(UnboundLocalError, NameError)=True
```

> **Note:** The error message is one line in the real output; it was wrapped
> here to fit the screen.

Notice that the `print` never ran: the very first read of `stock_count`
failed. A beginner expects the first line to read the global (it "exists") and
the second line to update it. The compiler, however, saw `stock_count -= 1`,
decided `stock_count` is local, and compiled *both* reads as local reads.
`UnboundLocalError` is a subclass of `NameError`, so code that catches
`NameError` catches it too.

The assignment does not even need to run. A branch that can never execute
still makes the name local, because the decision is made from the source text,
not from the values at run time:

```python
def read_with_dead_branch() -> int:
    """An assignment that never runs still makes stock_count local."""
    if False:
        stock_count = 0
    return stock_count


print(f"read_with_dead_branch(): {raised_error_name(read_with_dead_branch)}")
```

```text
read_with_dead_branch(): UnboundLocalError
```

### `co_varnames` and `co_names`

The compiler records its decisions in the function's code object.
`co_varnames` lists the local slots (parameters first, then other locals).
`co_names` lists the names the code looks up by name at run time: globals,
built-ins and attribute names. `build_receipt` uses one of each kind.

```python
def build_receipt(customer_name: str) -> str:
    """Uses a parameter, a local, a global function and an attribute."""
    greeting = customer_name.title()
    return f"{greeting}: {len(greeting)} letters, pi≈{math.pi:.2f}"


receipt_code = build_receipt.__code__
print(f"{receipt_code.co_varnames=}")
print(f"{receipt_code.co_names=}")
print(f"{sell_one.__code__.co_varnames=}")
```

```text
receipt_code.co_varnames=('customer_name', 'greeting')
receipt_code.co_names=('title', 'len', 'math', 'pi')
sell_one.__code__.co_varnames=('stock_count',)
```

The last line is the whole story of `sell_one`: `stock_count` is a local slot,
so the global of the same name is never consulted.

### Under the hood: `LOAD_FAST_CHECK`

The compiler also chooses the bytecode instruction for each read. Locals are
read with `LOAD_FAST`, or `LOAD_FAST_BORROW` (new in 3.14, which avoids
touching the reference count). Those instructions skip the "does this slot have
a value?" test, which is safe only when the compiler can prove the variable is
already bound. When it cannot prove that (as in `sell_one`, where the first
read comes before any assignment), it emits `LOAD_FAST_CHECK`, which raises
`UnboundLocalError` if the slot is empty. Globals and built-ins use
`LOAD_GLOBAL`, and attributes use `LOAD_ATTR`. Opcode names change between
Python versions, so treat the exact names as a 3.15 snapshot.

```python
load_prefixes = ("LOAD_FAST", "LOAD_GLOBAL", "LOAD_ATTR")
for function in (sell_one, build_receipt):
    print(f"{function.__name__}:")
    for instruction in dis.get_instructions(function):
        if instruction.opname.startswith(load_prefixes):
            print(f"  {instruction.opname} {instruction.argval}")

sell_one_opnames = {
    instruction.opname for instruction in dis.get_instructions(sell_one)
}
print(f"{'LOAD_FAST_CHECK' in sell_one_opnames=}")
```

```text
sell_one:
  LOAD_GLOBAL print
  LOAD_FAST_CHECK stock_count
  LOAD_FAST_BORROW stock_count
  LOAD_FAST_BORROW stock_count
build_receipt:
  LOAD_FAST_BORROW customer_name
  LOAD_ATTR title
  LOAD_FAST_BORROW greeting
  LOAD_GLOBAL len
  LOAD_FAST_BORROW greeting
  LOAD_GLOBAL math
  LOAD_ATTR pi
'LOAD_FAST_CHECK' in sell_one_opnames=True
```

Only the first read in `sell_one` needs the check. After `stock_count -= 1`
has stored a value, the compiler knows the slot is filled and uses the cheaper
instruction.

### JavaScript bridge: `var` hoisting and the `let` TDZ

JavaScript went through the same design question twice. With `var`, the
declaration is hoisted to the top of the function and the variable reads as
`undefined` until it is assigned. With `let` and `const`, the name is reserved
for the whole block but sits in a *temporal dead zone* until the declaration
runs, and reading it throws `ReferenceError`.

| | JS `var` | JS `let` / `const` | Python |
| --- | --- | --- | --- |
| Scope | Function | Block | Function |
| Early read | `undefined` | `ReferenceError` | `UnboundLocalError` |
| Decided | Parse time | Parse time | Compile time |

```javascript
function sellOne() {
  console.log(stock);   // var: undefined; let: ReferenceError
  let stock = 9;
}
```

Python behaves like `let` at function level: the name is reserved for the whole
function, but it has no value until the assignment runs. The fixes are covered
in 1.11.5: pass the value in and return the new value, or declare the name
`global` / `nonlocal`. The first is almost always better.

```python
def sell_one_fixed(current_stock: int) -> int:
    """Take the value as a parameter and return the new value."""
    return current_stock - 1


stock_count = sell_one_fixed(stock_count)
print(f"{stock_count=}")
```

```text
stock_count=9
```

### Key points

| Idea | Takeaway |
| --- | --- |
| When scope is fixed | At compile time, from the source text |
| Any binding | Makes the name local for the whole function |
| Early read | `UnboundLocalError` (a `NameError`) |
| `co_varnames` | Local slots, parameters first |
| `co_names` | Global, built-in and attribute names |
| `LOAD_FAST_CHECK` | Guards a local that may be unbound |

## 1.11.5 `global` and `nonlocal`

Python has no declarations for ordinary variables, but it has two scope
declarations that change where an assignment goes.

| Statement | Lets a function rebind | Typical use |
| --- | --- | --- |
| `global name` | A module-level name | Counters, caches (sparingly) |
| `nonlocal name` | Nearest enclosing function's name | Stateful closures (1.11.6) |

`global name` tells the compiler: in this function, `name` is not a local, and
every assignment to it writes to the module namespace. It applies to the whole
function body, like any other scope decision.

```python
request_count = 0


def record_request() -> int:
    """Rebind the module-level counter."""
    global request_count
    request_count += 1
    return request_count


record_request()
record_request()
print(f"{request_count=}")
```

```text
request_count=2
```

### Rebinding vs mutating

`global` and `nonlocal` are needed only to make a name point at a **new
object** (rebinding). Calling a method that changes an object in place, such as
`append`, `update` or item assignment `config["debug"] = True`, only *reads*
the name to find the object. Reading follows the LEGB rule, so no declaration
is needed. This is the same distinction Unit 1.2 drew between names and
objects.

```python
audit_log: list[str] = []


def log_event(message: str) -> None:
    """Mutates the global list: no 'global' needed."""
    audit_log.append(message)


def reset_log_wrong() -> None:
    """Assignment creates a new local; the global list is unchanged."""
    audit_log = []  # noqa: F841 (deliberate: local variable, never used)


log_event("login")
log_event("checkout")
reset_log_wrong()
print(f"{audit_log=}  (reset_log_wrong did nothing)")
```

```text
audit_log=['login', 'checkout']  (reset_log_wrong did nothing)
```

`reset_log_wrong` created a brand-new local list and threw it away. To really
reset the global list, either declare `global audit_log` before assigning, or
mutate it in place with `audit_log.clear()`, which needs no declaration.

> **Warning:** In JavaScript, `auditLog = []` inside a function silently
> reassigns the outer variable. In Python the same line silently creates a new
> local. Neither language warns you; Ruff's `F841` (unused local) is often the
> only hint.

`nonlocal` does the same for a variable of an enclosing function. Without it,
`total += amount` inside `add` would make `total` a local of `add`, and the
first call would fail with `UnboundLocalError`.

```python
def make_cart_total() -> Callable[[int], int]:
    """Return an add function that keeps a running total."""
    total = 0

    def add(amount: int) -> int:
        """Rebind the enclosing total."""
        nonlocal total
        total += amount
        return total

    return add


add_to_cart = make_cart_total()
add_to_cart(249)
print(f"{add_to_cart(640)=}")
```

```text
add_to_cart(640)=889
```

Both statements are checked at compile time. `nonlocal` must name a variable
that exists in an enclosing *function* (a module-level name does not count),
and a name may not be used in a function before its `global` declaration. The
third case below is correct and compiles.

```python
print(compile_error("def outer():\n    nonlocal missing_name\n"))
print(
    compile_error("rate = 1\ndef show():\n    print(rate)\n    global rate\n")
)
print(
    compile_error(
        "def outer():\n    total = 0\n    def add():\n        nonlocal total\n"
    )
)
```

```text
SyntaxError: no binding for nonlocal 'missing_name' found
SyntaxError: name 'rate' is used prior to global declaration
compiles
```

### Why global state hurts testing

A function that reads or writes module state has hidden inputs: its result
depends on whatever ran before it. Tests of such a function pass when run alone
and fail when run together, or pass in one order and fail in another, which is
the hardest kind of failure to debug. Below, two "tests" of `process_order`
share the hidden `processed_order_ids` set.

```python
processed_order_ids: set[int] = set()


def process_order(order_id: int) -> str:
    """Depends on hidden module state."""
    if order_id in processed_order_ids:
        return "duplicate"
    processed_order_ids.add(order_id)
    return "processed"


def test_new_order_is_processed() -> bool:
    return process_order(101) == "processed"


def test_repeat_order_is_duplicate() -> bool:
    process_order(101)
    return process_order(101) == "duplicate"


first = test_new_order_is_processed()
second = test_repeat_order_is_duplicate()
print(f"order A then B: {first}, {second}")
processed_order_ids.clear()
first = test_repeat_order_is_duplicate()
second = test_new_order_is_processed()
print(f"order B then A: {first}, {second}")
```

```text
order A then B: True, True
order B then A: True, False
```

The same two tests pass in one order and fail in the other. The fix is to make
the state an **explicit argument** (or, in Phase 2, an attribute of an object).
Each test then builds its own state, and the function has no hidden inputs.

```python
def process_order_explicit(order_id: int, processed_ids: set[int]) -> str:
    """Same logic; the state is passed in."""
    if order_id in processed_ids:
        return "duplicate"
    processed_ids.add(order_id)
    return "processed"


print(f"{process_order_explicit(101, set())=}")
seen_ids = {101}
print(f"{process_order_explicit(101, seen_ids)=}")
```

```text
process_order_explicit(101, set())='processed'
process_order_explicit(101, seen_ids)='duplicate'
```

### Key points

| Idea | Takeaway |
| --- | --- |
| `global x` | Assignments to `x` go to the module |
| `nonlocal x` | Assignments go to the enclosing function |
| Mutating | `x.append(…)` needs no declaration |
| Rebinding | `x = …` needs one, or it creates a local |
| Checked | At compile time (`SyntaxError`) |
| Best practice | Pass state in, return results |

## 1.11.6 Closures

A **closure** is a function that remembers variables of the function that
created it, even after that outer function has returned. Unit 1.10 already used
one (`make_discount`) without explaining how it works. The classic example is a
counter: `make_counter` returns a function whose `count` lives on between
calls, and every call to `make_counter` creates a fresh, independent `count`.

```python
def make_counter(start: int = 0) -> Callable[[], int]:
    """Return a function that counts up from start."""
    count = start

    def increment() -> int:
        """Rebind the enclosing count."""
        nonlocal count
        count += 1
        return count

    return increment


ticket_counter = make_counter()
invoice_counter = make_counter(start=1000)
print(ticket_counter(), ticket_counter(), ticket_counter())
print(invoice_counter(), invoice_counter())
```

```text
1 2 3
1001 1002
```

A closure that only **reads** the enclosing variable needs no `nonlocal`.
`make_multiplier` is a *function factory*: each function it returns carries its
own `factor`.

```python
def make_multiplier(factor: float) -> Callable[[float], float]:
    """Return a function that multiplies by factor."""

    def multiply(value: float) -> float:
        return value * factor

    return multiply


double = make_multiplier(2)
add_gst = make_multiplier(1.18)
print(f"{double(21)=}, {add_gst(500)=}")
```

```text
double(21)=42, add_gst(500)=590.0
```

Closures are Python's lightweight alternative to a class with one method. They
are used everywhere: callbacks, decorators (Unit 1.12), configuration
factories, and the validators in this unit's lab.

### Under the hood: cells

A normal local lives in the frame's fast-locals array and disappears when the
call returns. That cannot work for `count`, because `increment` still needs it
after `make_counter` has returned. So the compiler, seeing that an inner
function uses `count`, stores it differently: in a **cell object**, a tiny heap
box that holds one reference. The outer function and every inner function that
uses the variable point at the same cell, so the cell (and the value inside it)
lives as long as any of them does.

| Attribute | On | Holds |
| --- | --- | --- |
| `co_cellvars` | Outer code object | Names inner functions capture |
| `co_freevars` | Inner code object | Names read from outer scopes |
| `__closure__` | Inner function | Tuple of cells, one per free var |
| `cell_contents` | Each cell | The current value |

```text
  make_counter() call            increment function object
  +------------------+           +-----------------------+
  | count  --------------+       | __closure__ = (cell,) |
  +------------------+   |       +-----------|-----------+
                         v                   |
                    +---------+              |
                    |  cell   | <------------+
                    |  -> 3   |
                    +---------+
```

```python
print(f"{make_counter.__code__.co_cellvars=}")
print(f"{ticket_counter.__code__.co_freevars=}")
print(f"{type(ticket_counter.__closure__[0]).__name__=}")
print(f"{ticket_counter.__closure__[0].cell_contents=}")
print(f"{invoice_counter.__closure__[0].cell_contents=}")
print(f"{add_gst.__code__.co_freevars=}")
print(f"{add_gst.__closure__[0].cell_contents=}")
```

```text
make_counter.__code__.co_cellvars=('count',)
ticket_counter.__code__.co_freevars=('count',)
type(ticket_counter.__closure__[0]).__name__='cell'
ticket_counter.__closure__[0].cell_contents=3
invoice_counter.__closure__[0].cell_contents=1002
add_gst.__code__.co_freevars=('factor',)
add_gst.__closure__[0].cell_contents=1.18
```

`ticket_counter` has been called three times and `invoice_counter` twice, and
the cells show exactly that: each counter has its own cell.

A cell holds the **variable**, not a frozen copy of the value. Two closures
created in the same call share their cells, and a change made after the closure
was created is visible through it. A function with no free variables has
`__closure__` set to `None`.

```python
def make_price_tools(
    initial_price: int,
) -> tuple[Callable[[], int], Callable[[int], None]]:
    """Return a getter and a setter that share one cell."""
    price = initial_price

    def get_price() -> int:
        return price

    def set_price(new_price: int) -> None:
        nonlocal price
        price = new_price

    return get_price, set_price


get_price, set_price = make_price_tools(250)
set_price(199)
print(f"{get_price()=}")
print(f"{get_price.__closure__[0] is set_price.__closure__[0]=}")
print(f"{show_size.__closure__=}")
```

```text
get_price()=199
get_price.__closure__[0] is set_price.__closure__[0]=True
show_size.__closure__=None
```

The bytecode shows the cell machinery. The outer function starts with
`MAKE_CELL` and writes the variable with `STORE_DEREF` instead of
`STORE_FAST`. The inner function starts with `COPY_FREE_VARS`, which copies the
cells from its `__closure__` into its own frame, then reads and writes through
them with `LOAD_DEREF` / `STORE_DEREF`. As before, opcode names vary between
versions.

```python
for function in (make_counter, ticket_counter):
    opnames = [
        instruction.opname for instruction in dis.get_instructions(function)
    ]
    cell_ops = [
        name
        for name in opnames
        if "DEREF" in name or "CELL" in name or "FREE" in name
    ]
    print(f"{function.__qualname__}:")
    print(f"  {cell_ops}")
```

```text
make_counter:
  ['MAKE_CELL', 'STORE_DEREF']
make_counter.<locals>.increment:
  ['COPY_FREE_VARS', 'LOAD_DEREF', 'STORE_DEREF', 'LOAD_DEREF']
```

> **Note:** JavaScript closures work the same way: they capture variables, not
> values, and engines such as V8 move captured variables into a heap "context"
> object, much like a cell. The visible difference is that JavaScript can
> assign an outer variable directly, while Python needs `nonlocal` to rebind it.

### Key points

| Idea | Takeaway |
| --- | --- |
| Closure | Inner function + the outer variables it uses |
| Independent state | Each outer call makes new cells |
| Read-only use | No `nonlocal` needed |
| Cells | Boxes for captured variables, shared |
| Introspection | `__closure__`, `cell_contents`, `co_freevars` |
| Bytecode | `MAKE_CELL`, `LOAD_DEREF`, `STORE_DEREF` |

## 1.11.7 Late binding

Because closures capture variables (cells), they read the value **when they are
called**, not when they are created. This is called *late binding*. Most of the
time it is exactly what you want (`get_price` above sees the new price). It
bites when functions are created in a loop: they all share the one loop
variable, so they all see its last value.

### Predict the output

```python
callbacks = [lambda: i for i in range(3)]
print([callback() for callback in callbacks])
```

<details><summary>Answer</summary>

```text
[2, 2, 2]
callbacks[0].__closure__[0] is callbacks[2].__closure__[0]=True
```

The three lambdas share **one** variable `i`, held in one cell. By the time
they are called, the comprehension has finished and `i` is 2. The second line
comes from the checking code in the notebook, which adds
`print(f"{callbacks[0].__closure__[0] is callbacks[2].__closure__[0]=}")` and
proves that the first and last lambdas hold the very same cell.

</details>

### Fix 1: a default argument

Default values are evaluated once, when the function is created (Unit 1.10),
so `i=i` copies the *current* value of `i` into each lambda's defaults. The
lambda then reads its own parameter instead of the shared cell, and has no
closure at all. This is the most common idiom. Its downside is that callers
could pass a value for `i` by mistake.

```python
frozen_callbacks = [lambda i=i: i for i in range(3)]
print([callback() for callback in frozen_callbacks])
print(f"{frozen_callbacks[1].__defaults__=}")
print(f"{frozen_callbacks[1].__closure__=}")
```

```text
[0, 1, 2]
frozen_callbacks[1].__defaults__=(1,)
frozen_callbacks[1].__closure__=None
```

### Fix 2: `functools.partial` or a factory

`functools.partial(function, value)` stores the value when the partial object
is created, with no extra parameter to misuse. A small factory function (like
`make_multiplier`) works too, because every call to the factory creates a new
cell holding that call's value.

```python
def label_for(slot_number: int) -> str:
    """Return a delivery-slot label."""
    return f"slot {slot_number}"


partial_callbacks = [functools.partial(label_for, slot) for slot in range(3)]
factory_callbacks = [make_multiplier(slot) for slot in range(3)]
print([callback() for callback in partial_callbacks])
print([callback(10) for callback in factory_callbacks])
```

```text
['slot 0', 'slot 1', 'slot 2']
[0, 10, 20]
```

### JavaScript bridge: `var` in loops

JavaScript had exactly this bug with `var` and fixed it with `let`, which
creates a **new binding for every iteration** of a `for` loop. Python has no
per-iteration binding: a `for` loop assigns to the same variable again and
again, so Python behaves like `var`.

```javascript
for (var i = 0; i < 3; i++) setTimeout(() => console.log(i));  // 3 3 3
for (let i = 0; i < 3; i++) setTimeout(() => console.log(i));  // 0 1 2
```

The trap appears in real code whenever callbacks are registered in a loop, for
example one handler per button or per route. A plain `for` loop shares the
variable just like the comprehension did.

```python
button_handlers: dict[str, Callable[[], str]] = {}
for button_name in ["save", "cancel", "delete"]:
    button_handlers[button_name] = (
        lambda: f"clicked {button_name}"  # noqa: B023
    )

print(f"{button_handlers['save']()=}  (late binding)")

for button_name in ["save", "cancel", "delete"]:
    button_handlers[button_name] = (
        lambda name=button_name: f"clicked {name}"
    )

print(f"{button_handlers['save']()=}  (fixed with a default)")
```

```text
button_handlers['save']()='clicked delete'  (late binding)
button_handlers['save']()='clicked save'  (fixed with a default)
```

> **Warning:** Here the loop runs at module level, so the lambdas read the
> *global* `button_name`, not a cell, but the effect is identical: they look the
> name up when called. Ruff's rule `B023` ("function definition does not bind
> loop variable") catches this pattern.

### Key points

| Idea | Takeaway |
| --- | --- |
| Late binding | Closures read the variable at call time |
| Loop trap | All functions see the last value |
| Fix 1 | `lambda i=i: …` freezes the value |
| Fix 2 | `functools.partial(f, i)` or a factory |
| JS | Like `var`; Python has no `let`-style loop |

## 1.11.8 Name lookup cost

The compile-time scope decision also picks the instruction used to read each
name, and those instructions do different amounts of work.

| Instruction | Scope | Cost |
| --- | --- | --- |
| `LOAD_FAST(_BORROW)` | Local | Index into the frame's array |
| `LOAD_DEREF` | Enclosing | Array index + one cell hop |
| `LOAD_GLOBAL` | Global, built-in | Dict lookups, cached (3.11+) |
| `LOAD_ATTR` | `module.name` | One more lookup on top |

A local read is a C array index. A cell read adds one pointer hop. A global
read is, in principle, a dict lookup in the module namespace and, on a miss, a
second one in the built-ins. Since 3.11, CPython's *specializing adaptive
interpreter* (PEP 659) rewrites hot `LOAD_GLOBAL` instructions into
specialized versions that cache the result and only check that the dicts have
not changed, which makes global reads nearly as cheap as local ones.

The next example uses all four kinds in one function.

```python
def make_scaler(scale: float) -> Callable[[list[float]], list[float]]:
    """Return a function reading a local, a cell, a global, a built-in."""

    def scale_values(values: list[float]) -> list[float]:
        rounded_values = [round(value * scale, 2) for value in values]
        return [math.floor(value) for value in rounded_values]

    return scale_values


load_prefixes = ("LOAD_FAST", "LOAD_DEREF", "LOAD_GLOBAL", "LOAD_ATTR")
loads = {
    f"{instruction.opname} {instruction.argval}"
    for instruction in dis.get_instructions(make_scaler(1.5))
    if instruction.opname.startswith(load_prefixes)
}
for load in sorted(loads):
    print(load)
```

```text
LOAD_ATTR floor
LOAD_DEREF scale
LOAD_FAST rounded_values
LOAD_FAST values
LOAD_FAST_AND_CLEAR value
LOAD_FAST_BORROW value
LOAD_GLOBAL math
LOAD_GLOBAL round
```

`values` and `rounded_values` are locals, `scale` is a cell, `math` and
`round` go through `LOAD_GLOBAL` (one found in the module, one in the
built-ins), and `floor` is an attribute of `math`. `LOAD_FAST_AND_CLEAR` is a
sign of PEP 709 inlining: it saves and clears the comprehension variable
`value` so that it cannot leak into `scale_values`.

### Timing a local alias

The classic micro-optimization binds a global or a bound method to a local
name before a hot loop, for example `sqrt = math.sqrt` or
`append = results.append`, so that the loop does local reads instead of a
global read plus an attribute lookup on every iteration. On modern CPython the
specializing interpreter has narrowed the gap so much that the gain is usually
small or zero. Measure before doing it, and only in genuinely hot loops.

```python
def roots_global(count: int) -> list[float]:
    """math.sqrt and results.append looked up on every iteration."""
    results: list[float] = []
    for number in range(count):
        results.append(math.sqrt(number))
    return results


def roots_local_alias(count: int) -> list[float]:
    """Both looked up once, then read as locals."""
    results: list[float] = []
    append, sqrt = results.append, math.sqrt
    for number in range(count):
        append(sqrt(number))
    return results


global_seconds = min(
    timeit.repeat(lambda: roots_global(10_000), number=50, repeat=5)
)
alias_seconds = min(
    timeit.repeat(lambda: roots_local_alias(10_000), number=50, repeat=5)
)
print(f"global lookups: {global_seconds * 1000:.1f} ms")
print(f"local alias:    {alias_seconds * 1000:.1f} ms")
print(f"speed-up: {global_seconds / alias_seconds:.2f}x")
```

```text
global lookups: 34.5 ms
local alias:    33.5 ms
speed-up: 1.03x
```

> **Note:** Timings vary by machine, load and Python version, so your numbers
> will differ. In the executed notebook the same comparison gave 19.6 ms versus
> 21.1 ms, a "speed-up" of 0.93x: the alias was actually slightly *slower*.
> On Python 3.15 the difference is within measurement noise.

> **Warning:** A local alias also freezes the lookup. If something later
> replaces `math.sqrt` (a test mock, for example), the aliased loop keeps
> calling the old function. Readability usually matters more than a few
> percent.

### Key points

| Idea | Takeaway |
| --- | --- |
| `LOAD_FAST` | Cheapest: array index |
| `LOAD_DEREF` | One extra hop through a cell |
| `LOAD_GLOBAL` | Dict lookups, cached since 3.11 |
| Local alias | Little or no gain today; measure first |

## Lab 1.11

The lab has three exercises. In the notebook each one has a stub that raises
`NotImplementedError` and a check cell that calls `run_checks`, which prints
`PASS` or `FAIL` per case. Try each exercise yourself before opening the
solution. All solutions use closures; none uses a global or a class.

### Exercise 1 — `make_rate_counter(window_seconds)`

Write a factory that returns **two closures sharing state**, as the tuple
`(record_hit, hits_in_window)`:

- `record_hit(timestamp)` remembers that a hit happened at `timestamp` (seconds,
  a float; timestamps arrive in increasing order).
- `hits_in_window(now)` returns how many recorded hits satisfy
  `now - window_seconds < timestamp <= now`.
- Raise `ValueError` if `window_seconds <= 0`.
- Two calls to `make_rate_counter` must give independent counters.

The checks:

| Check | Expected |
| --- | --- |
| Hits 0, 10, 20, 30, 65; window 60 | `[4, 4, 3, 4, 2]` |
| Counts at | t = 30, 59.9, 60, 65, 85 |
| Two counters, one hit on the first | `(1, 0)` |
| Both functions have `__closure__` | `True` |
| `make_rate_counter(0)` | `ValueError` |

At t = 60 the hit at 0 drops out, because the window excludes its left edge
(`60 - 60 < 0` is false). At t = 85 only the hits at 30 and 65 remain.

**Hints:**

- Create one container (a list or a `collections.deque`) in the factory, and
  let both inner functions use it.
- `record_hit` only *mutates* the container, so it needs no `nonlocal`.
- Validate `window_seconds` before defining the inner functions, so the error
  is raised at creation time.

<details><summary>Solution</summary>

```python
from collections import deque


def make_rate_counter(
    window_seconds: float,
) -> tuple[Callable[[float], None], Callable[[float], int]]:
    """Return (record_hit, hits_in_window) closures sharing one deque."""
    if window_seconds <= 0:
        raise ValueError("window_seconds must be positive")
    hit_times: deque[float] = deque()

    def record_hit(timestamp: float) -> None:
        """Remember one hit (timestamps arrive in increasing order)."""
        hit_times.append(timestamp)

    def hits_in_window(now: float) -> int:
        """Count hits with now - window_seconds < timestamp <= now."""
        return sum(
            1
            for hit_time in hit_times
            if now - window_seconds < hit_time <= now
        )

    return record_hit, hits_in_window
```

Both inner functions close over the same `hit_times` cell, and each call to
`make_rate_counter` creates a new deque and a new cell, which keeps counters
independent. Because the hits arrive in order, a production version could also
`popleft()` timestamps that have fallen out of the window to keep memory
bounded; the checks only require correct counts.

</details>

### Exercise 2 — fix three buggy functions

Each buggy function shows one of this unit's (or the previous unit's) traps.
Here they are, followed by what they actually do:

```python
def add_tag_buggy(tag: str, tags: list[str] = []) -> list[str]:  # noqa: B006
    tags.append(tag)
    return tags


def make_accumulator_buggy() -> Callable[[float], float]:
    total = 0.0

    def add(amount: float) -> float:
        total += amount  # noqa: F823 (the bug)
        return total

    return add


def make_price_formatters_buggy(
    currency_codes: list[str],
) -> list[Callable[[float], str]]:
    return [
        lambda amount: f"{code} {amount:.2f}"  # noqa: B023
        for code in currency_codes
    ]


print(f"{add_tag_buggy('new')=}, {add_tag_buggy('sale')=}")
accumulator_error = raised_error_name(lambda: make_accumulator_buggy()(5))
print(f"accumulator: {accumulator_error}")
formatters = make_price_formatters_buggy(["INR", "USD"])
print([formatter(250) for formatter in formatters])
```

```text
add_tag_buggy('new')=['new'], add_tag_buggy('sale')=['new', 'sale']
accumulator: UnboundLocalError
['USD 250.00', 'USD 250.00']
```

Write fixed versions named `add_tag`, `make_accumulator` and
`make_price_formatters` (the same names without `_buggy`), keeping the
signatures:

1. `add_tag(tag, tags=None)` returns a list of the given tags plus `tag`. The
   buggy version shares one default list between calls (the mutable-default
   trap from Unit 1.10). The fixed version must also **not change** a list
   passed in by the caller.
2. `make_accumulator()` returns `add(amount)`, which returns the running total.
   The buggy version raises `UnboundLocalError` (1.11.4).
3. `make_price_formatters(currency_codes)` returns one formatter per currency
   code; each takes an amount and returns, for example, `"INR 250.00"`. The
   buggy version formats every amount with the last currency (1.11.7).

The checks:

| Check | Expected |
| --- | --- |
| `add_tag("new")`, `add_tag("sale")` | `["new"]`, `["sale"]` |
| `add_tag("sale", ["new"])` | `["new", "sale"]` |
| Caller's list afterwards | Still `["new"]` |
| `add(100)`, `add(49.5)`, `add(-20)` | `[100, 149.5, 129.5]` |
| Two new accumulators: 1 and 2 | `(1, 2)` |
| Formatters for INR, USD, EUR at 250 | `"INR 250.00"`, … |
| First formatter at 9.5 | `"INR 9.50"` |

**Hints:**

- Use `None` as the default and build a **new** list inside the function.
- The inner function rebinds `total`, so it needs a declaration.
- Freeze each currency code with a default argument.

<details><summary>Solution</summary>

```python
def add_tag(tag: str, tags: list[str] | None = None) -> list[str]:
    """Return a new list holding the given tags followed by tag."""
    return [*(tags or []), tag]


def make_accumulator() -> Callable[[float], float]:
    """Return add(amount), which returns the running total."""
    total = 0.0

    def add(amount: float) -> float:
        nonlocal total
        total += amount
        return total

    return add


def make_price_formatters(
    currency_codes: list[str],
) -> list[Callable[[float], str]]:
    """Return one formatter per currency code, e.g. 'INR 250.00'."""
    return [
        lambda amount, code=code: f"{code} {amount:.2f}"
        for code in currency_codes
    ]
```

`[*(tags or []), tag]` unpacks the caller's tags (or nothing) into a brand-new
list, so neither the default nor the caller's list is ever mutated.
`nonlocal total` makes `+=` rebind the enclosing variable instead of creating a
local. `code=code` evaluates the current code once per lambda, which defeats
late binding; `functools.partial` would work as well.

</details>

### Exercise 3 — closure-based field validation

Write three **validator factories**. Each returns a *validator*: a function
that takes a string and returns an error message, or `None` if the value is
valid. The type alias is `type Validator = Callable[[str], str | None]`.

| Factory | Exact error message |
| --- | --- |
| `min_length(length)` | `"must be at least {length} characters"` |
| `matches_pattern(pattern, description)` | `"must be {description}"` |
| `one_of(allowed_values)` | `"must be one of: a, b, c"` |

`matches_pattern` must use `re.fullmatch` (the whole value must match), and
`one_of` lists the allowed values sorted and joined with `", "`.

Then write `validate_record(record, rules)`. `rules` maps a field name to a list
of validators. Return a dict mapping each field to its list of error messages,
in rule order, leaving out fields with no errors. A field missing from `record`
is validated as `""`.

The checks use this rule set for a sign-up form:

```python
def signup_rules() -> dict[str, list[Validator]]:
    """Rules for a sign-up form, built from the three factories."""
    return {
        "password": [
            min_length(8),
            matches_pattern(r".*\d.*", "a value containing a digit"),
        ],
        "username": [
            min_length(3),
            matches_pattern(r"[a-z_]+", "lowercase letters or _"),
        ],
        "plan": [one_of({"free", "pro", "team"})],
    }
```

| Check | Expected |
| --- | --- |
| `min_length(3)("abc")` | `None` |
| `min_length(8)("abc")` | `"must be at least 8 characters"` |
| 6-digit PIN pattern on `"560001"` | `None` |
| Same pattern on `"5600012"` | `"must be a 6-digit PIN code"` |
| `one_of({"free", "pro"})("pro")` | `None` |
| `one_of({"pro", "free"})("gold")` | `"must be one of: free, pro"` |
| A fully valid record | `{}` |
| `min_length(8).__closure__` | Not `None` |

The "invalid record" check validates
`{"password": "chai", "username": "Asha K"}` and expects every field to fail:

| Field | Expected messages |
| --- | --- |
| `password` | At least 8 characters; containing a digit |
| `username` | Lowercase letters or `_` |
| `plan` (missing) | One of: free, pro, team |

**Hints:**

- Do the expensive work (`re.compile`, building the `one_of` message) once, in
  the factory, not on every validation.
- An assignment expression keeps the message-collecting loop short:
  `if (message := validator(value))`.

<details><summary>Solution</summary>

```python
type Validator = Callable[[str], str | None]


def min_length(length: int) -> Validator:
    """Return a validator that rejects values shorter than length."""

    def validate(value: str) -> str | None:
        if len(value) >= length:
            return None
        return f"must be at least {length} characters"

    return validate


def matches_pattern(pattern: str, description: str) -> Validator:
    """Return a validator that rejects values not fully matching pattern."""
    compiled_pattern = re.compile(pattern)

    def validate(value: str) -> str | None:
        if compiled_pattern.fullmatch(value):
            return None
        return f"must be {description}"

    return validate


def one_of(allowed_values: set[str]) -> Validator:
    """Return a validator that rejects values outside allowed_values."""
    allowed = frozenset(allowed_values)
    message = "must be one of: " + ", ".join(sorted(allowed))

    def validate(value: str) -> str | None:
        return None if value in allowed else message

    return validate


def validate_record(
    record: dict[str, str], rules: dict[str, list[Validator]]
) -> dict[str, list[str]]:
    """Return {field: [error messages]} for every field that has errors."""
    errors_by_field: dict[str, list[str]] = {}
    for field_name, validators in rules.items():
        value = record.get(field_name, "")
        messages = [
            message
            for validator in validators
            if (message := validator(value))
        ]
        if messages:
            errors_by_field[field_name] = messages
    return errors_by_field
```

Each factory captures its configuration (`length`, `compiled_pattern` and
`description`, `allowed` and `message`) in cells, so a validator is just a
one-argument function that can be stored in a list and called later. `one_of`
copies the set into a `frozenset`, so later changes to the caller's set cannot
change an existing validator. Running all the lab checks against the reference
solutions prints:

```text
Exercise 1 — make_rate_counter
4/4 checks passed
Exercise 2 — fix three buggy functions
6/6 checks passed
Exercise 3 — closure-based field validation
9/9 checks passed
```

(The individual `PASS` lines are omitted.)

</details>

## Recap

| Concept | Takeaway | JavaScript equivalent |
| --- | --- | --- |
| Namespaces | Built-in, module, class, function | Global, module, function scope |
| `globals()` | The module's real `__dict__` | `globalThis` (per module) |
| `locals()` | Snapshot; writes ignored (3.13+) | — |
| LEGB | Local → Enclosing → Global → Built-in | Scope chain |
| Class bodies | Skipped by method lookups | Use `this` |
| Shadowing | `list = [...]` hides the built-in | Shadowing `Array` |
| No block scope | Block names survive the block | `var` |
| `except … as e` | `e` deleted after the block | — |
| Comprehensions | Own scope; `:=` leaks on purpose | — |
| Compile-time scope | Any assignment makes a local | `let` TDZ |
| `co_varnames` | Local slots of a code object | — |
| `LOAD_FAST_CHECK` | Guards a maybe-unbound local | — |
| `global` / `nonlocal` | Needed to rebind, not to mutate | Plain assignment |
| Global state | Hidden inputs; pass state instead | Same advice |
| Closures | Captured variables live in cells | Closures |
| Late binding | Read at call time; `i=i` or `partial` | `var` loop; fixed by `let` |
| Lookup cost | `LOAD_FAST` < `LOAD_DEREF` < `LOAD_GLOBAL` | — |
| Local alias | Measure first; often no gain | — |

## Further reading

- [Tutorial: Python scopes and namespaces](https://docs.python.org/3/tutorial/classes.html#python-scopes-and-namespaces)
- [Execution model: naming and binding](https://docs.python.org/3/reference/executionmodel.html#naming-and-binding)
- [The `global` statement](https://docs.python.org/3/reference/simple_stmts.html#the-global-statement)
- [The `nonlocal` statement](https://docs.python.org/3/reference/simple_stmts.html#the-nonlocal-statement)
- [FAQ: why am I getting an UnboundLocalError?](https://docs.python.org/3/faq/programming.html#why-am-i-getting-an-unboundlocalerror-when-the-variable-has-a-value)
- [FAQ: lambdas defined in a loop](https://docs.python.org/3/faq/programming.html#why-do-lambdas-defined-in-a-loop-with-different-values-all-return-the-same-result)
- [`builtins`](https://docs.python.org/3/library/builtins.html)
- [`inspect.getclosurevars`](https://docs.python.org/3/library/inspect.html#inspect.getclosurevars)
- [`dis`](https://docs.python.org/3/library/dis.html)
- [`functools.partial`](https://docs.python.org/3/library/functools.html#functools.partial)
- [PEP 227 — Statically nested scopes](https://peps.python.org/pep-0227/)
- [PEP 3104 — Access to names in outer scopes](https://peps.python.org/pep-3104/)
- [PEP 572 — Assignment expressions](https://peps.python.org/pep-0572/)
- [PEP 659 — Specializing adaptive interpreter](https://peps.python.org/pep-0659/)
- [PEP 667 — Consistent views of namespaces](https://peps.python.org/pep-0667/)
- [PEP 709 — Inlined comprehensions](https://peps.python.org/pep-0709/)

[← Previous](unit-1-10-functions-definition-and-arguments.md) · [Index](README.md) · [Next →](unit-1-12-decorators-functools-and-the-call-stack.md)
