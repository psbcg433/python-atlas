# Unit 1.9 — Iteration, Comprehensions and Built-in Functions

[← Previous](unit-1-8-operators-expressions-and-control-flow.md) · [Index](README.md) · [Next →](unit-1-10-functions-definition-and-arguments.md)

Every `for` loop in Python runs on a small protocol of two methods,
`__iter__` and `__next__`. Once you see that protocol, the built-in helpers
(`enumerate`, `zip`, `map`, `any` …) and comprehensions all make sense as
tools built on top of it. This unit takes the protocol apart, shows the
comprehension syntax that replaces most `.map().filter()` chains, walks
through the everyday built-in functions one group at a time, and ends with the
idioms that make a loop read like Python rather than translated JavaScript.

## What you will learn

- How the iteration protocol works (`iter`, `next`, `StopIteration`), and how
  to rewrite a `for` loop by hand as the `while` loop it really is.
- How to use `enumerate`, `zip`, `reversed`, `sorted` and `range` instead of
  index arithmetic.
- How to write list, dict and set comprehensions, and when a plain loop reads
  better.
- The commonly used built-in functions, grouped by purpose, and which ones are
  dangerous.
- How to choose between `map` / `filter` and comprehensions, and how to write
  idiomatic loops.

## JavaScript → Python bridge

Both languages have an iteration protocol, and `for...of` and `for ... in`
are the same idea. The differences are in the details: how the end of the
sequence is signalled, and the fact that Python's `map` and `filter` are lazy.

| JavaScript | Python | The difference that bites |
| --- | --- | --- |
| `for (const x of items)` | `for item in items` | Same idea: a protocol |
| `obj[Symbol.iterator]()` | `iter(obj)` | Calls `obj.__iter__()` |
| `it.next()` → `{value, done}` | `next(it)` | End is an exception |
| `items.map(f)` | `map(f, items)` | Lazy, single-use iterator |
| `items.filter(f)` | `filter(f, items)` | Lazy, single-use iterator |
| `.map(...).filter(...)` | `[f(x) for x in xs if c(x)]` | The idiomatic form |
| `items.entries()` | `enumerate(items)` | `start=` sets first index |
| lodash `zip` | `zip(a, b, strict=True)` | Truncates without `strict` |
| `items.some(f)` | `any(...)` | Any iterable of values |
| `items.every(f)` | `all(...)` | `all([])` is `True` |
| `Math.max(...items)` | `max(items, key=...)` | `default=` for empty input |
| `typeof x` | `type(x)` | Returns the class itself |
| `x instanceof C` | `isinstance(x, C)` | Also takes a tuple or union |
| `eval(code)` | `eval(code)` | Just as dangerous |

In JavaScript the end of an iteration is a flag: `next()` returns
`{value: undefined, done: true}`. In Python the end is an exception:
`next()` raises `StopIteration`. And where `items.map(f)` in JavaScript builds
a new array immediately, Python's `map(f, items)` returns an iterator that
does nothing until you consume it, and can be consumed only once. For data
parsing, replace `eval` with `ast.literal_eval` or `json.loads`.

The examples in this unit use the setup below. `raised_error_name` calls a
function and returns the name of the exception it raised, so one line can show
"this raises `TypeError`" without stopping the program. `scratch_dir` is a
scratch folder used by the `open` demo in 1.9.4.

```python
import ast
import datetime as dt
import dis
import io
import operator
import subprocess
import sys
import timeit
from collections.abc import Callable, Iterator
from decimal import Decimal
from pathlib import Path
from typing import IO, Any, NamedTuple


def raised_error_name(thunk: Callable[[], object]) -> str:
    """Call thunk and return the name of the exception it raised."""
    try:
        thunk()
    except Exception as error:
        return type(error).__name__
    return "no error"


def find_repo_root(start: Path | None = None) -> Path:
    """Walk up from start to the folder holding pyproject.toml."""
    current = (start or Path.cwd()).resolve()
    for folder in (current, *current.parents):
        if (folder / "pyproject.toml").exists():
            return folder
    raise FileNotFoundError("pyproject.toml not found")


scratch_dir = find_repo_root() / "notebooks" / "_scratch"
scratch_dir.mkdir(parents=True, exist_ok=True)
print(f"{sys.version_info[:2]=}")
```

```text
sys.version_info[:2]=(3, 15)
```

## 1.9.1 The iteration protocol

Python separates two roles that JavaScript also separates, though it rarely
names them. An **iterable** is anything you can loop over: it has an
`__iter__()` method that returns a *new* iterator each time it is called.
An **iterator** is the object that does the walking: it has a `__next__()`
method that returns the next item or raises `StopIteration` when there are no
more, plus an `__iter__()` that returns the iterator itself.

| Role | Has | Examples |
| --- | --- | --- |
| Iterable | `__iter__()` → new iterator | `list`, `str`, `dict`, files |
| Iterator | `__next__()` and `__iter__()` | `iter([1, 2])`, `map`, `zip` |

You rarely call the dunder methods directly. The built-in `iter(obj)` calls
`obj.__iter__()`, and `next(it)` calls `it.__next__()`. The JavaScript
equivalents are `obj[Symbol.iterator]()` and `it.next()`. The difference is
the end signal: JavaScript returns `{done: true}`, Python raises
`StopIteration`. Walking a list by hand shows the whole protocol:

```python
queue_names = ["asha", "ravi"]
name_iterator = iter(queue_names)
print(f"{type(name_iterator).__name__=}")
print(f"{next(name_iterator)=}")
print(f"{next(name_iterator)=}")
try:
    next(name_iterator)
except StopIteration:
    print("StopIteration: the iterator is exhausted")
print(f"{list(name_iterator)=}  (an exhausted iterator stays empty)")
print(f"{iter(name_iterator) is name_iterator=}")
print(f"{iter(queue_names) is queue_names=}")
```

```text
type(name_iterator).__name__='list_iterator'
next(name_iterator)='asha'
next(name_iterator)='ravi'
StopIteration: the iterator is exhausted
list(name_iterator)=[]  (an exhausted iterator stays empty)
iter(name_iterator) is name_iterator=True
iter(queue_names) is queue_names=False
```

Two facts in that output matter for the rest of the unit. First, an
exhausted iterator stays exhausted: there is no rewind, and `list()` on it
quietly returns `[]`. Second, `iter()` on an iterator returns the same object,
while `iter()` on a list returns a fresh `list_iterator` every time. That is
why you can loop over a list as often as you like, but only once over an
iterator.

> **Note:** a `list_iterator` holds only a reference to the list and an index.
> It does not copy the list, so creating one is O(1) no matter how long the
> list is.

### The desugared `for` loop

A `for` loop is not special syntax for lists. The statement
`for item in iterable: body` is exactly this:

```python
hidden_iterator = iter(iterable)
while True:
    try:
        item = next(hidden_iterator)
    except StopIteration:
        break
    body
```

The loop calls `iter()` once at the start, then `next()` before every pass,
and stops when `StopIteration` comes out. Running both versions side by side
shows they do the same thing:

```python
order_totals = [120, 499, 999]

for order_total in order_totals:
    print(f"for loop:     {order_total}")

hidden_iterator = iter(order_totals)
while True:
    try:
        order_total = next(hidden_iterator)
    except StopIteration:
        break
    print(f"desugared:    {order_total}")
```

```text
for loop:     120
for loop:     499
for loop:     999
desugared:    120
desugared:    499
desugared:    999
```

### Making your own class iterable

Any class can take part in the protocol. Below, `Countdown` is an iterable:
each `iter()` call returns a fresh `CountdownIterator`, so it can be looped
over more than once. `CountdownIterator` is the iterator: it keeps the
current position and raises `StopIteration` when it reaches zero. Unit 1.13
writes the same thing in three lines with a generator.

```python
class CountdownIterator:
    """Iterator from start down to 1."""

    def __init__(self, start: int) -> None:
        self.current = start

    def __iter__(self) -> CountdownIterator:
        return self

    def __next__(self) -> int:
        if self.current < 1:
            raise StopIteration
        self.current -= 1
        return self.current + 1


class Countdown:
    """Iterable: a new iterator per loop."""

    def __init__(self, start: int) -> None:
        self.start = start

    def __iter__(self) -> CountdownIterator:
        return CountdownIterator(self.start)


launch = Countdown(3)
print(f"{list(launch)=}, {list(launch)=}  (iterable: reusable)")
single_pass = iter(launch)
print(f"{list(single_pass)=}, {list(single_pass)=}  (iterator: one pass)")
```

```text
list(launch)=[3, 2, 1], list(launch)=[3, 2, 1]  (iterable: reusable)
list(single_pass)=[3, 2, 1], list(single_pass)=[]  (iterator: one pass)
```

> **Note:** the return annotation `-> CountdownIterator` inside the class body
> refers to the class being defined. That works because Python 3.14 evaluates
> annotations lazily (PEP 649); on older versions you would quote it.

The split between iterable and iterator is the same as in JavaScript, where an
object with `[Symbol.iterator]()` is iterable and the object it returns has
`next()`. JavaScript's built-in iterators also return themselves from
`[Symbol.iterator]()`, so they too are single-pass.

### Under the hood: `GET_ITER` and `FOR_ITER`

In CPython bytecode, a `for` loop compiles to `GET_ITER` (call `iter()` once)
followed by `FOR_ITER` (call `next()`; when the iterator is exhausted, jump
past the loop body). For built-in iterators such as `list_iterator`, the C
code signals the end by returning `NULL` without setting an exception, so the
normal end of a loop never creates a `StopIteration` object at all. Only
iterators written in Python have to raise it, and the interpreter swallows it
inside `FOR_ITER`. The `dis` module shows the instructions:

```python
def total_of(prices: list[int]) -> int:
    """Sum prices with an explicit loop."""
    running_total = 0
    for price in prices:
        running_total += price
    return running_total


for instruction in dis.get_instructions(total_of):
    print(instruction.opname)
```

```text
RESUME
LOAD_SMALL_INT
STORE_FAST
LOAD_FAST
GET_ITER
FOR_ITER
STORE_FAST
LOAD_FAST_BORROW_LOAD_FAST_BORROW
BINARY_OP
STORE_FAST
JUMP_BACKWARD
END_FOR
POP_ITER
LOAD_FAST_BORROW
RETURN_VALUE
```

> **Note:** opcode names change between Python versions (this is 3.15). The
> shape stays the same: `GET_ITER`, then a `FOR_ITER` … `JUMP_BACKWARD` cycle,
> then `END_FOR` when the loop finishes.

### `iter(callable, sentinel)`

`iter` has a second, less known form. With two arguments, `iter(callable,
sentinel)` calls `callable()` with no arguments again and again, yields each
result, and stops as soon as a result **equals** `sentinel`. It turns
"read until empty" loops into iterators. A text stream's `readline` returns
`""` at the end of the stream, so `""` is the sentinel:

```python
access_log = io.StringIO("GET /\nPOST /cart\nGET /checkout\n")
for log_line in iter(access_log.readline, ""):
    print(f"line: {log_line.rstrip()}")
```

```text
line: GET /
line: POST /cart
line: GET /checkout
```

The callable must take no arguments. To pass one, wrap the call in a `lambda`
(covered in 1.10.7). That gives **fixed-size chunks**: read 4 bytes at a time
until `read` returns `b""`. This is how you would stream a large upload
without loading it into memory. Lab 1.9, exercise 1, wraps this in a reusable
function.

```python
upload_stream = io.BytesIO(b"PNG-image-bytes")
chunk_list = list(iter(lambda: upload_stream.read(4), b""))
print(f"{chunk_list=}")
```

```text
chunk_list=[b'PNG-', b'imag', b'e-by', b'tes']
```

> **Warning:** the sentinel must have the right type. A binary stream returns
> `b""` at the end, and `b"" == ""` is `False`, so `iter(stream.read, "")` on a
> binary stream never stops.

JavaScript has no equivalent of the two-argument form; you would write a
`while` loop or a generator function.

### Key points

| Idea | Takeaway |
| --- | --- |
| Iterable | `__iter__()` returns a new iterator |
| Iterator | `__next__()`; `__iter__()` returns itself |
| End of iteration | `StopIteration`, not a `done` flag |
| Exhausted iterator | Stays empty; no rewind |
| `for` loop | `iter()` once, `next()` until `StopIteration` |
| Bytecode | `GET_ITER` + `FOR_ITER` |
| `iter(f, sentinel)` | Calls `f()` until it returns `sentinel` |

## 1.9.2 Iteration helpers

Five built-ins remove almost every need for index arithmetic like
`for i in range(len(items))`. Each returns a lazy iterator, except `sorted`
(which returns a new list) and `range` (a lazy *sequence* object that supports
`len` and indexing). They are all implemented in C, so they are also faster
than the hand-written index loop they replace.

| Helper | Returns | Use it for |
| --- | --- | --- |
| `enumerate(it, start=0)` | iterator of pairs | index + item |
| `zip(*its, strict=False)` | iterator of tuples | parallel items |
| `reversed(seq)` | iterator | walking backwards |
| `sorted(it, key=, reverse=)` | new list | ordering anything |
| `range(start, stop, step)` | lazy sequence | runs of integers |

### `enumerate`

`enumerate(iterable, start=0)` yields `(index, item)` pairs. Unpacking the
pair in the `for` target gives both names at once, and `start=1` gives human
numbering. It is the counterpart of JavaScript's `items.entries()`, but it
works on any iterable, not only arrays.

```python
checkout_steps = ["cart", "address", "payment"]
for step_number, step_name in enumerate(checkout_steps, start=1):
    print(f"step {step_number}: {step_name}")
print(f"{list(enumerate('ab'))=}")
```

```text
step 1: cart
step 2: address
step 3: payment
list(enumerate('ab'))=[(0, 'a'), (1, 'b')]
```

### `zip`

`zip(*iterables, strict=False)` pairs items up from several iterables. By
default it stops at the **shortest** input and silently drops the rest.
`strict=True` (Python 3.10, PEP 618) raises `ValueError` when the lengths
differ, which is almost always what you want when the inputs are supposed to
line up.

```python
product_names = ["tea", "rice", "ghee"]
unit_prices = [249, 525]
loose_pairs = list(zip(product_names, unit_prices, strict=False))
print(f"{loose_pairs=}  (ghee lost silently)")
print(
    "strict: "
    + raised_error_name(
        lambda: list(zip(product_names, unit_prices, strict=True))
    )
)
rows = [("tea", 249), ("rice", 525)]
names_column, prices_column = zip(*rows, strict=True)  # transposes
print(f"{names_column=}, {prices_column=}")
```

```text
loose_pairs=[('tea', 249), ('rice', 525)]  (ghee lost silently)
strict: ValueError
names_column=('tea', 'rice'), prices_column=(249, 525)
```

The last two lines show a classic trick: `zip(*rows)` **transposes** a list
of rows into columns. The `*` unpacks the list, so the call becomes
`zip(("tea", 249), ("rice", 525))`, and `zip` pairs the first items together
and the second items together.

> **Warning:** the silent truncation is the bug. If a CSV row is missing a
> column, plain `zip` drops data without a word. Pass `strict=True` whenever
> the inputs must have equal lengths. Ruff's rule B905 flags `zip` calls
> without it.

`strict=True` checks lazily: the `ValueError` comes when the shorter input
runs out, not when `zip` is called. Items already produced have been
consumed by then.

### `reversed`

`reversed(sequence)` iterates backwards **without copying**. It needs either
a sequence (`__len__` plus integer indexing) or a `__reversed__` method. Dicts
and their views support it since Python 3.8, because dicts keep insertion
order. A generator does not, because it has neither a length nor indexing.

```python
print(f"{list(reversed([1, 2, 3]))=}, {''.join(reversed('UPI'))=}")
print(f"{list(reversed({'a': 1, 'b': 2}))=}")
print(f"{list(reversed(range(3)))=}")
print(f"generator: {raised_error_name(lambda: reversed(n for n in range(3)))}")
```

```text
list(reversed([1, 2, 3]))=[3, 2, 1], ''.join(reversed('UPI'))='IPU'
list(reversed({'a': 1, 'b': 2}))=['b', 'a']
list(reversed(range(3)))=[2, 1, 0]
generator: TypeError
```

Compare JavaScript's `items.reverse()`, which reverses the array in place, and
`items.toReversed()`, which builds a reversed copy. Python's `reversed` does
neither: it returns an iterator that reads the original from the end. To get
a reversed copy of a list, use `items[::-1]` or `list(reversed(items))`.

### `sorted`

`sorted(iterable, *, key=None, reverse=False)` accepts **any** iterable and
returns a **new list**; the input is not changed. `key` is a function that
turns each item into the value to compare. Unit 1.5.4 covers sorting in depth
(stability, multi-key sorts).

```python
stock_levels = {"tea": 5, "rice": 12, "ghee": 2}
print(f"{sorted(stock_levels)=}  (keys)")
by_stock = sorted(stock_levels, key=stock_levels.get, reverse=True)
print(f"{by_stock=}  (by stock)")
print(f"{sorted('python')=}, {sorted({3, 1, 2})=}")
```

```text
sorted(stock_levels)=['ghee', 'rice', 'tea']  (keys)
by_stock=['rice', 'tea', 'ghee']  (by stock)
sorted('python')=['h', 'n', 'o', 'p', 't', 'y'], sorted({3, 1, 2})=[1, 2, 3]
```

Iterating a dict gives its keys, so `sorted(stock_levels)` sorts the keys, and
`key=stock_levels.get` sorts those keys by their values. A string is an
iterable of characters, and a set has no order of its own, so `sorted` is
also the way to get a predictable order from a set.

> **Note:** `list.sort()` sorts in place and returns `None`; `sorted()`
> returns a new list. That is the same split as JavaScript's `sort()` and
> `toSorted()`, except that Python's default comparison is by value, not by
> string conversion: `sorted([10, 9])` is `[9, 10]`.

### `range`

`range(start, stop, step)` is a lazy, immutable sequence of integers. It
stores only the three numbers, so `range(10**9)` uses the same memory as
`range(3)`. It supports `len`, indexing, slicing (which returns another
`range`), and O(1) `in` tests for integers, which are computed arithmetically
instead of by scanning (see 1.5.7).

```python
invoice_numbers = range(1000, 2000, 10)
print(f"{len(invoice_numbers)=}, {invoice_numbers[3]=}")
print(f"{1500 in invoice_numbers=}")
print(f"{invoice_numbers[:3]=}, {list(range(5, 0, -2))=}")
```

```text
len(invoice_numbers)=100, invoice_numbers[3]=1030
1500 in invoice_numbers=True
invoice_numbers[:3]=range(1000, 1030, 10), list(range(5, 0, -2))=[5, 3, 1]
```

JavaScript has no built-in `range`; the usual replacement,
`Array.from({length: n}, (_, i) => i)`, builds the whole array in memory.

### Key points

| Helper | Takeaway |
| --- | --- |
| `enumerate` | `(index, item)` pairs; `start=1` for humans |
| `zip` | Stops at shortest; use `strict=True` |
| `zip(*rows)` | Transposes rows into columns |
| `reversed` | Backwards without copying; needs a sequence |
| `sorted` | Any iterable in, new list out |
| `range` | Lazy ints with `len`, slicing and O(1) `in` |

## 1.9.3 Comprehensions

A comprehension builds a container from an iterable in one expression. It
reads like set-builder notation from mathematics: "the list of `f(x)` for
each `x` in `items`, if `x` passes this test". In JavaScript you would chain
`.map()` and `.filter()` or write a loop with `push`; in Python the
comprehension is the idiomatic form, and it is usually faster than the loop
it replaces. There are four kinds, distinguished only by their brackets:

| Kind | Syntax | Result |
| --- | --- | --- |
| List | `[expr for x in it if cond]` | `list` |
| Dict | `{k: v for x in it if cond}` | `dict` |
| Set | `{expr for x in it if cond}` | `set` |
| Generator expression | `(expr for x in it)` | lazy iterator |

The generator expression produces items one at a time instead of building a
container; Unit 1.13 covers it. You have already seen one form of it in this
unit: `any(days > 30 for days in days_overdue)` passes a generator expression
straight to a function, and the extra parentheses can then be dropped.

### List comprehensions

The list comprehension replaces both `.map()` and the "empty list, loop,
`append`" pattern. The expression on the left is computed for each item:

```python
prices_in_rupees = [120, 499, 999]
prices_with_gst = [round(price * 1.18, 2) for price in prices_in_rupees]
print(f"{prices_with_gst=}")
```

```text
prices_with_gst=[141.6, 588.82, 1178.82]
```

### Filters

An `if` clause after the `for` keeps only the items that pass the test. This
is the `.filter()` part. Do not confuse it with a conditional *expression*
(`a if cond else b`) in the output part, which keeps every item but chooses
what to produce for it:

```python
order_totals = [120, 1499, 650, 2300]
free_shipping_orders = [total for total in order_totals if total >= 999]
print(f"{free_shipping_orders=}")
labels = ["big" if total >= 999 else "small" for total in order_totals]
print(f"{labels=}")
```

```text
free_shipping_orders=[1499, 2300]
labels=['small', 'big', 'small', 'big']
```

The first comprehension has two items (filtered); the second has four (one
label per order). The position tells them apart: a filter `if` comes *after*
the `for` and has no `else`; a conditional expression comes *before* the
`for` and must have an `else`.

### Dict comprehensions

A dict comprehension has `key: value` on the left. It is the natural way to
build an index, or to invert a dict (swap keys and values), which in
JavaScript needs `Object.fromEntries(Object.entries(obj).map(...))`:

```python
product_names = ["tea", "rice", "ghee"]
name_lengths = {name: len(name) for name in product_names}
sku_by_name = {"tea": "TEA-500G", "rice": "RICE-5KG"}
name_by_sku = {sku: name for name, sku in sku_by_name.items()}
print(f"{name_lengths=}")
print(f"{name_by_sku=}")
```

```text
name_lengths={'tea': 3, 'rice': 4, 'ghee': 4}
name_by_sku={'TEA-500G': 'tea', 'RICE-5KG': 'rice'}
```

> **Note:** if two items produce the same key, the later one silently wins,
> exactly as with repeated assignment `d[key] = value`. Inverting a dict whose
> values are not unique therefore loses entries.

### Set comprehensions

A set comprehension uses braces without a colon and keeps only unique
results. The output below is printed through `sorted`, because the order of
a set of strings changes between runs (string hashes are randomized; see
1.6):

```python
customer_emails = ["Asha@Mail.in", "asha@mail.in", "ravi@mail.in"]
unique_emails = {email.lower() for email in customer_emails}
print(f"{sorted(unique_emails)=}")
```

```text
sorted(unique_emails)=['asha@mail.in', 'ravi@mail.in']
```

> **Warning:** `{}` is an empty **dict**, not an empty set. Write `set()` for
> an empty set.

### Nested `for` order

A comprehension can have several `for` clauses. They read **left to right,
outer to inner**, in exactly the order of the nested loops they replace. Many
people expect the opposite, so it helps to write the loops out once:

```python
[cell for row in grid for cell in row]
# is the same as
result = []
for row in grid:
    for cell in row:
        result.append(cell)
```

```python
sizes, colours = ["S", "M"], ["red", "blue"]
variants = [f"{size}-{colour}" for size in sizes for colour in colours]
print(f"{variants=}")

seat_grid = [[1, 2, 3], [4, 5, 6]]
flat_seats = [seat for row in seat_grid for seat in row]
even_seats = [seat for row in seat_grid for seat in row if seat % 2 == 0]
print(f"{flat_seats=}, {even_seats=}")
```

```text
variants=['S-red', 'S-blue', 'M-red', 'M-blue']
flat_seats=[1, 2, 3, 4, 5, 6], even_seats=[2, 4, 6]
```

`flat_seats` is the Python version of JavaScript's `grid.flat()` or
`grid.flatMap(row => row)`. An `if` can follow any `for` clause and can use
every name bound to its left.

### Own scope: the loop variable does not leak

A comprehension's loop variable exists only inside the comprehension. A plain
`for` loop is different: its variable is an ordinary assignment in the
enclosing scope, so it survives the loop with its last value. That is like
JavaScript's `var` in a `for` loop, while the comprehension behaves like
`let`:

```python
comprehension_item = "before"
doubled_items = [comprehension_item * 2 for comprehension_item in "ab"]
print(f"{doubled_items=}, {comprehension_item=}  (unchanged)")

for loop_item in "ab":  # noqa: B007
    pass
print(f"{loop_item=}  (a for loop's variable survives the loop)")
```

```text
doubled_items=['aa', 'bb'], comprehension_item='before'  (unchanged)
loop_item='b'  (a for loop's variable survives the loop)
```

> **Note:** an assignment expression (`:=`, the walrus operator from 1.8) inside
> a comprehension is the one exception: it deliberately binds the name in the
> enclosing scope, so you can keep a value found during the comprehension.

```python
order_totals = [120, 1499, 650]
has_large = any((large_total := total) > 1000 for total in order_totals)
print(f"{has_large=}, {large_total=}")
```

```text
has_large=True, large_total=1499
```

### Under the hood: inlined comprehensions (PEP 709)

Before Python 3.12, every comprehension compiled to a hidden nested function
that was created and called each time the comprehension ran. That is how the
loop variable was kept private, but creating a function object per run is
not free. Since 3.12 (PEP 709), list, dict and set comprehensions are
**inlined**: their bytecode sits directly in the enclosing function. To keep
the isolation, the compiler emits `LOAD_FAST_AND_CLEAR`, which saves any
outer variable with the same name before the loop and restores it afterwards.
There is no `MAKE_FUNCTION` in the output any more:

```python
def doubled(values: list[int]) -> list[int]:
    """Double every value with a comprehension."""
    return [value * 2 for value in values]


doubled_opnames = [
    instruction.opname for instruction in dis.get_instructions(doubled)
]
print(f"{'MAKE_FUNCTION' in doubled_opnames=}")
print(f"{'LOAD_FAST_AND_CLEAR' in doubled_opnames=}")
```

```text
'MAKE_FUNCTION' in doubled_opnames=False
'LOAD_FAST_AND_CLEAR' in doubled_opnames=True
```

Generator expressions are not inlined: they still compile to a separate code
object, because they must be able to pause and resume (Unit 1.13).

### Readability limits

One `for`, maybe one `if`: a comprehension then reads like a sentence. With
two loops, two conditions and a conditional expression, it stops being
readable, and a plain loop with a name for each step is better. Both versions
below compute the same result; ask yourself which one you would rather debug.

```python
daily_orders = [[120, 1500, -1], [999, 2300], [450]]

hard_to_read = [
    total * 0.9 if total > 1000 else total
    for day in daily_orders
    for total in day
    if total > 0
    if total != 999
]


def discounted_totals(days: list[list[int]]) -> list[float]:
    """Skip invalid and exact-999 totals; give 10% off totals over 1000."""
    result = []
    for day in days:
        for total in day:
            if total <= 0 or total == 999:
                continue
            result.append(total * 0.9 if total > 1000 else total)
    return result


print(f"{hard_to_read == discounted_totals(daily_orders)=}")
print(f"{hard_to_read=}")
```

```text
hard_to_read == discounted_totals(daily_orders)=True
hard_to_read=[120, 1350.0, 2070.0, 450]
```

A good rule: if the comprehension does not fit on one or two lines, or if
you need a comment to explain it, write the loop. Also never use a
comprehension only for its side effects (`[print(x) for x in items]`): it
builds a list of `None` values you throw away. Use a `for` loop.

### Predict the output: flat or nested?

```python
grid = [[1, 2], [3, 4]]
print([cell * 10 for row in grid for cell in row if cell != 2])
print([[cell * 10 for cell in row] for row in grid])
```

<details><summary>Answer</summary>

```text
[10, 30, 40]
[[10, 20], [30, 40]]
```

The first line has two `for` clauses in **one** comprehension, so it is a
single flat loop (outer `row`, inner `cell`) and the filter drops the `2`.
The second line puts a whole comprehension in the output position, so the
outer comprehension produces one inner list per row: a nested result. Two
`for` clauses flatten; a comprehension inside a comprehension nests.

</details>

### Key points

| Idea | Takeaway |
| --- | --- |
| List / dict / set | `[...]`, `{k: v ...}`, `{...}` |
| Filter | `if` after the `for`, no `else` |
| Conditional expression | `a if c else b` before the `for` |
| Nested `for` | Left to right = outer to inner |
| Scope | Loop variable does not leak (`:=` does) |
| Since 3.12 | Inlined, no hidden function (PEP 709) |
| Readability | One `for`, one `if`; otherwise a loop |

## 1.9.4 Built-in functions catalogue

Python has about 70 built-in functions. They live in the `builtins` module,
and you can list them with `import builtins; dir(builtins)`. You never import
them because of how name lookup works: when the compiler sees a name such as
`len`, it looks in the local scope, then any enclosing functions, then the
module's globals, and finally the `builtins` module (the "LEGB" rule, covered
in Unit 1.11). Built-ins are the last stop, which has a consequence:

> **Warning:** a variable named `list`, `sum`, `max`, `id`, `type` or `input`
> **shadows** the built-in for the rest of that scope. The built-in is not
> gone, just hidden, and the error appears later, far from the cause.

```python
def sum(values: list[int]) -> str:  # do not do this
    """A function that hides the built-in sum."""
    return "shadowed"


print(f"{sum([1, 2])=}")
del sum  # remove the global name; lookup falls through to builtins again
print(f"{sum([1, 2])=}")
```

```text
sum([1, 2])='shadowed'
sum([1, 2])=3
```

This section covers the built-ins you will use every day, in six groups:
numeric, iteration, conversion, introspection, input/output, and the
dangerous ones that run code. Each group starts with a reference table
(every row is a one-line example and its result), then a table of JavaScript
equivalents, then a demo for each function with the details and traps. In the
reference tables, the Result column shows the value as the REPL would echo it.

### Numeric

| Function | What it does | Example | Result |
| --- | --- | --- | --- |
| `abs` | Absolute value | `abs(-5)` | `5` |
| `round` | Round, ties to even | `round(2.5)` | `2` |
| `divmod` | Quotient and remainder | `divmod(17, 5)` | `(3, 2)` |
| `pow` | Power, optional modulus | `pow(3, 4, 5)` | `1` |
| `sum` | Add up, from `start` | `sum([1, 2], start=10)` | `13` |
| `min` | Smallest item | `min([], default=0)` | `0` |
| `max` | Largest item | `max(names, key=len)` | `'rice'` |

In the `max` example, `names` is `["tea", "rice", "ghee"]`.

| Function | JavaScript equivalent |
| --- | --- |
| `abs` | `Math.abs(x)` |
| `round` | `Math.round(x)` (but that rounds half up) |
| `divmod` | none; `Math.floor(a / b)` and `a % b` |
| `pow` | `a ** b`, `Math.pow(a, b)` |
| `sum` | `items.reduce((a, b) => a + b, 0)` |
| `min` | `Math.min(...items)` |
| `max` | `Math.max(...items)` |

#### `abs(x)`

`abs` returns the absolute value. For a complex number it returns the
magnitude (the distance from zero). It works on any type that defines
`__abs__`, which includes `Decimal` and `Fraction`, and the result keeps the
input's type.

```python
print(f"{abs(-5)=}, {abs(-2.5)=}, {abs(3 + 4j)=}")
print(f"{abs(Decimal('-19.99'))=}")
```

```text
abs(-5)=5, abs(-2.5)=2.5, abs(3 + 4j)=5.0
abs(Decimal('-19.99'))=Decimal('19.99')
```

#### `round(number, ndigits=None)`

Without `ndigits`, `round` returns an `int`. Ties go to the **even**
neighbour ("banker's rounding"), which avoids the upward bias of always
rounding halves up. JavaScript's `Math.round` rounds halves up (towards
positive infinity), so `Math.round(2.5)` is `3` but `round(2.5)` is `2`. A
negative `ndigits` rounds to tens, hundreds and so on.

```python
print(f"{round(2.5)=}, {round(3.5)=}, {round(-0.5)=}  (ties to even)")
print(f"{round(3.14159, 2)=}, {round(1234, -2)=}")
print(f"{type(round(2.7)).__name__=}")
print(f"{round(2.675, 2)=}  (2.675 is really 2.67499999...)")
```

```text
round(2.5)=2, round(3.5)=4, round(-0.5)=0  (ties to even)
round(3.14159, 2)=3.14, round(1234, -2)=1200
type(round(2.7)).__name__='int'
round(2.675, 2)=2.67  (2.675 is really 2.67499999...)
```

> **Warning:** some "ties" are not ties at all. The float literal `2.675` is
> stored as `2.67499999…` (see 1.3.2), so it rounds down. For money, use
> `Decimal` and its `quantize` method with an explicit rounding mode.

#### `divmod(a, b)`

`divmod` returns `(a // b, a % b)` in one call, which is handy for unit
conversions such as seconds to hours, minutes and seconds. Like `//` and `%`,
it floors towards negative infinity, so the remainder takes the sign of the
divisor: `divmod(-7, 2)` is `(-4, 1)`, whereas JavaScript's `-7 % 2` is `-1`.

```python
total_seconds = 3725
minutes, seconds = divmod(total_seconds, 60)
hours, minutes = divmod(minutes, 60)
print(f"{hours}h {minutes}m {seconds}s, {divmod(-7, 2)=}")
```

```text
1h 2m 5s, divmod(-7, 2)=(-4, 1)
```

#### `pow(base, exp, mod=None)`

With two arguments `pow` is the same as `**`. A negative integer exponent
gives a float. The three-argument form `pow(base, exp, mod)` computes
`base ** exp % mod` efficiently, without ever building the huge intermediate
number; this is the core operation of RSA-style cryptography. Since Python
3.8, `pow(base, -1, mod)` computes the **modular inverse**: the number that
gives 1 when multiplied by `base` modulo `mod`.

```python
print(f"{pow(2, 10)=}, {pow(2, -1)=}, {pow(3, 4, 5)=}")
print(f"{pow(38, -1, 97)=}, {38 * pow(38, -1, 97) % 97=}")
```

```text
pow(2, 10)=1024, pow(2, -1)=0.5, pow(3, 4, 5)=1
pow(38, -1, 97)=23, 38 * pow(38, -1, 97) % 97=1
```

#### `sum(iterable, /, start=0)`

`sum` adds numbers. `start` is the initial value: it is the result for an
empty input and it sets the type of the result. With
`start=Decimal("0.00")`, an empty list of prices still sums to a `Decimal`
instead of the plain `int` 0. `sum` refuses strings even with `start=""`,
because adding strings one by one is quadratic; it tells you to use
`"".join(...)` instead.

```python
line_totals = [Decimal("498.00"), Decimal("640.00")]
print(f"{sum(line_totals)=}")
print(f"{sum([], start=Decimal('0.00'))=}, {sum([])=}")
print(f"{sum([1, 2, 3], start=10)=}")
print(f"strings: {raised_error_name(lambda: sum(['a', 'b'], start=''))}")
```

```text
sum(line_totals)=Decimal('1138.00')
sum([], start=Decimal('0.00'))=Decimal('0.00'), sum([])=0
sum([1, 2, 3], start=10)=16
strings: TypeError
```

> **Note:** summing many floats with `sum` accumulates rounding error. Since
> Python 3.12, `sum` of floats uses Neumaier compensated summation, which is
> more accurate; `math.fsum` gives the exactly rounded result.

#### `min(iterable, *, key=None, default=...)`

`min` returns the smallest item. It accepts either one iterable or several
separate arguments (`min(a, b, c)`). `key` compares items by a derived value
but returns the **original item**, so `min(stock_levels,
key=stock_levels.get)` returns the product name with the lowest stock, not
the stock number. `default` is returned for an empty iterable instead of
raising `ValueError`.

```python
stock_levels = {"tea": 5, "rice": 12, "ghee": 2}
print(f"{min(4, 9, 1)=}, {min(stock_levels, key=stock_levels.get)=}")
print(f"{min([], default=None)=}, empty: {raised_error_name(lambda: min([]))}")
```

```text
min(4, 9, 1)=1, min(stock_levels, key=stock_levels.get)='ghee'
min([], default=None)=None, empty: ValueError
```

JavaScript's `Math.min(...items)` returns `Infinity` for an empty array and
`NaN` for anything non-numeric; Python's `min` raises instead, and works on
anything comparable: strings, tuples, dates.

#### `max(iterable, *, key=None, default=...)`

`max` is the mirror of `min`. On ties, the **first** maximal item wins (the
same is true for `min`), which matters when you pick "the largest event" from
a list that has two events with the same amount, as Lab 1.9 does.

```python
product_names = ["tea", "rice", "ghee"]
print(f"{max(product_names, key=len)=}  (rice and ghee tie: first wins)")
print(f"{max([], default=0)=}, {max('apple', 'banana')=}")
```

```text
max(product_names, key=len)='rice'  (rice and ghee tie: first wins)
max([], default=0)=0, max('apple', 'banana')='banana'
```

### Iteration

| Function | What it does | Example | Result |
| --- | --- | --- | --- |
| `len` | Number of items | `len("tea")` | `3` |
| `iter` | Get an iterator | `next(iter([1, 2]))` | `1` |
| `next` | Next item or default | `next(iter([]), None)` | `None` |
| `map` | Lazy `f(item)` for each | `list(map(str.upper, ["a"]))` | `['A']` |
| `filter` | Lazy truthy items | `list(filter(None, [0, 1]))` | `[1]` |
| `any` | Some item truthy? | `any(x > 3 for x in [1, 5])` | `True` |
| `all` | Every item truthy? | `all([])` | `True` |
| `enumerate` | `(index, item)` pairs | `list(enumerate("ab", 1))` | `[(1, 'a'), (2, 'b')]` |
| `zip` | Parallel tuples | `list(zip("ab", [1, 2]))` | `[('a', 1), ('b', 2)]` |
| `reversed` | Reverse iterator | `list(reversed([1, 2]))` | `[2, 1]` |
| `sorted` | New sorted list | `sorted(["bb", "a"], key=len)` | `['a', 'bb']` |

| Function | JavaScript equivalent |
| --- | --- |
| `len` | `.length`, `.size` |
| `iter` | `items[Symbol.iterator]()` |
| `next` | `it.next().value` |
| `map` | `items.map(f)` (eager) |
| `filter` | `items.filter(f)` (eager) |
| `any` | `items.some(f)` |
| `all` | `items.every(f)` |
| `enumerate` | `items.entries()` |
| `zip` | lodash `_.zip` |
| `reversed` | `items.toReversed()` |
| `sorted` | `items.toSorted(compare)` |

#### `len(obj)`

`len` returns the number of items by calling `__len__`. For every built-in
container it is O(1), because the size is stored in the object; nothing is
counted. Note that `len` of a string counts code points, so `'₹99'` has length
3, whereas JavaScript's `'₹99'.length` counts UTF-16 units (also 3 here, but 2
for a single emoji). Iterators and generators have no length, because they do
not know how many items are left.

```python
print(f"{len('₹99')=}, {len([1, 2])=}, {len({'a': 1})=}")
print(f"{len(range(0, 10, 3))=}")
print(f"generator: {raised_error_name(lambda: len(n for n in range(3)))}")
```

```text
len('₹99')=3, len([1, 2])=2, len({'a': 1})=1
len(range(0, 10, 3))=4
generator: TypeError
```

#### `iter(obj)` / `iter(callable, sentinel)`

`iter` gets an iterator (1.9.1). Calling it on an iterator returns the same
object; calling it on something that is not iterable raises `TypeError`. The
two-argument form calls a function until it returns the sentinel.

```python
letter_iterator = iter("ab")
print(f"{next(letter_iterator)=}")
print(f"{iter(letter_iterator) is letter_iterator=}")
print(f"iter(5): {raised_error_name(lambda: iter(5))}")
```

```text
next(letter_iterator)='a'
iter(letter_iterator) is letter_iterator=True
iter(5): TypeError
```

> **Note:** `iter` also works on old-style classes that define only
> `__getitem__` (indexing from 0 until `IndexError`). That fallback is why
> some objects are iterable without having `__iter__`.

#### `next(iterator, default)`

`next` returns the next item. With a second argument it returns that value
instead of raising `StopIteration` when the iterator is exhausted.
`next(generator_expression, None)` is the standard idiom for "the first match,
or `None`", the equivalent of JavaScript's `items.find(f)`. It stops at the
first match, so the rest of the list is never examined.

```python
order_totals = [120, 1499, 650]
first_large = next((total for total in order_totals if total > 1000), None)
first_huge = next((total for total in order_totals if total > 5000), None)
print(f"{first_large=}, {first_huge=}")
```

```text
first_large=1499, first_huge=None
```

#### `map(function, *iterables, strict=False)`

`map` returns a lazy iterator of `function(item)` for each item. With several
iterables it calls `function(a, b)` with one item from each, stopping at the
shortest. `strict=True` is new in Python 3.14 and has the same meaning as in
`zip`: unequal lengths raise `ValueError`. Section 1.9.5 compares `map` with
comprehensions.

```python
print(f"{list(map(str.upper, ['tea', 'rice']))=}")
line_amounts = list(map(operator.mul, [249, 525], [2, 1]))  # noqa: B912
print(f"{line_amounts=}")
if sys.version_info >= (3, 14):
    strict_error = raised_error_name(
        lambda: list(map(pow, [2, 3], [3], strict=True))
    )
    print(f"strict: {strict_error}")
else:
    print("map(strict=True) needs Python 3.14; skipped")
```

```text
list(map(str.upper, ['tea', 'rice']))=['TEA', 'RICE']
line_amounts=[498, 525]
strict: ValueError
```

#### `filter(function, iterable)`

`filter` returns a lazy iterator of the items for which `function(item)` is
truthy. Passing `None` as the function keeps the truthy items themselves,
which is a quick way to drop empty strings and `None` values.

```python
raw_tags = ["new", "", "sale", None, "organic"]
print(f"{list(filter(None, raw_tags))=}")
print(f"{list(filter(str.isdigit, ['12', 'ab', '7']))=}")
```

```text
list(filter(None, raw_tags))=['new', 'sale', 'organic']
list(filter(str.isdigit, ['12', 'ab', '7']))=['12', '7']
```

#### `any(iterable)`

`any` returns `True` as soon as it finds a truthy item, and stops there
(short-circuit). For an empty iterable it returns `False`. Unlike JavaScript's
`some`, it does not take a callback: you pass it an iterable of values,
usually a generator expression that computes them.

```python
days_overdue = [0, 3, 45, 2]
print(f"{any(days > 30 for days in days_overdue)=}, {any([])=}")
```

```text
any(days > 30 for days in days_overdue)=True, any([])=False
```

#### `all(iterable)`

`all` returns `False` as soon as it finds a falsy item. For an empty iterable
it returns `True`: nothing failed the test ("vacuous truth"). JavaScript's
`[].every(f)` is also `true`. Below, the empty phone number is falsy, so not
every required field is filled in.

```python
required_fields = {"name": "Asha", "email": "asha@mail.in", "phone": ""}
print(f"{all(required_fields.values())=}, {all([])=}")
```

```text
all(required_fields.values())=False, all([])=True
```

#### `enumerate(iterable, start=0)`

`enumerate` yields `(index, item)` pairs (see 1.9.2).

```python
print(f"{list(enumerate(['tea', 'rice'], start=1))=}")
```

```text
list(enumerate(['tea', 'rice'], start=1))=[(1, 'tea'), (2, 'rice')]
```

#### `zip(*iterables, strict=False)`

`zip` yields tuples of parallel items (see 1.9.2). Passing the pairs to
`dict` builds a mapping from two lists, the equivalent of JavaScript's
`Object.fromEntries` over zipped arrays.

```python
price_by_name = dict(zip(["tea", "rice"], [249, 525], strict=True))
print(f"{price_by_name=}")
```

```text
price_by_name={'tea': 249, 'rice': 525}
```

#### `reversed(sequence)`

`reversed` returns a reverse iterator without copying (see 1.9.2).

```python
print(f"{list(reversed(['v1', 'v2', 'v3']))=}")
```

```text
list(reversed(['v1', 'v2', 'v3']))=['v3', 'v2', 'v1']
```

#### `sorted(iterable, *, key=None, reverse=False)`

`sorted` returns a new sorted list (see 1.9.2 and 1.5.4). By default,
uppercase letters sort before lowercase ones because their code points are
smaller; `key=str.casefold` gives a case-insensitive order.

```python
print(f"{sorted(['Rice', 'tea', 'Ghee'], key=str.casefold)=}")
```

```text
sorted(['Rice', 'tea', 'Ghee'], key=str.casefold)=['Ghee', 'Rice', 'tea']
```

### Conversion

The conversion functions are really the constructors of the built-in types:
`int` is the class `int`, and calling a class creates an instance. That is
why `type(int)` is `type`.

| Function | What it does | Example | Result |
| --- | --- | --- | --- |
| `int` | Integer from text/number | `int("ff", 16)` | `255` |
| `float` | Float from text/number | `float("1e3")` | `1000.0` |
| `str` | Readable text | `str(42)` | `'42'` |
| `bool` | Truthiness | `bool([])` | `False` |
| `list` | New list | `list("ab")` | `['a', 'b']` |
| `tuple` | New tuple | `tuple([1, 2])` | `(1, 2)` |
| `dict` | New dict | `dict(a=1)` | `{'a': 1}` |
| `set` | Unique items | `sorted(set("aab"))` | `['a', 'b']` |
| `frozenset` | Immutable set | `frozenset({1, 2})` | `frozenset({1, 2})` |

| Function | What it does | Example | Result |
| --- | --- | --- | --- |
| `bytes` | Encode text | `bytes("₹", "utf-8")` | `b'\xe2\x82\xb9'` |
| `chr` | Code point → char | `chr(8377)` | `'₹'` |
| `ord` | Char → code point | `ord("A")` | `65` |
| `bin` | Binary text | `bin(5)` | `'0b101'` |
| `hex` | Hex text | `hex(255)` | `'0xff'` |
| `oct` | Octal text | `oct(8)` | `'0o10'` |
| `format` | Format spec | `format(0.25, ".0%")` | `'25%'` |
| `repr` | Developer text | `repr("tea")` | `"'tea'"` |
| `ascii` | `repr`, ASCII only | `print(ascii("₹"))` | `'₹'` |

The `set` row goes through `sorted` because the order of a set of strings
varies between runs. The `ascii` row shows the *printed* text.

| Function | JavaScript equivalent |
| --- | --- |
| `int` | `parseInt(s, 16)`, `Math.trunc(x)` |
| `float` | `parseFloat(s)`, `Number(s)` |
| `str` | `String(x)` |
| `bool` | `Boolean(x)` |
| `list` | `Array.from(x)` |
| `tuple` | none (frozen array) |
| `dict` | `Object.fromEntries(pairs)` |
| `set` | `new Set(items)` |
| `frozenset` | none |
| `bytes` | `new TextEncoder().encode(s)` |
| `chr` | `String.fromCodePoint(n)` |
| `ord` | `s.codePointAt(0)` |
| `bin` / `hex` / `oct` | `n.toString(2)`, `(16)`, `(8)` |
| `format` | `Intl.NumberFormat`, `toFixed` |
| `repr` | `JSON.stringify` (roughly) |
| `ascii` | none |

#### `int(x=0)` / `int(text, base=10)`

From a float, `int` truncates toward zero (like JavaScript's `Math.trunc`,
not `Math.floor`). From text it accepts surrounding whitespace and `_` digit
separators, but **not** a decimal point. Unlike `parseInt`, which happily
reads `"42px"` as `42`, `int` rejects any text that is not entirely a number.
Base `0` means "use the prefix in the text" (`0b`, `0o`, `0x`).

```python
print(f"{int('42')=}, {int(' 7 ')=}, {int('1_000')=}")
print(f"{int('ff', 16)=}, {int('0b101', 0)=}")
print(f"{int(3.9)=}, {int(-3.9)=}  (truncates toward zero)")
print(f"int('3.5'): {raised_error_name(lambda: int('3.5'))}")
```

```text
int('42')=42, int(' 7 ')=7, int('1_000')=1000
int('ff', 16)=255, int('0b101', 0)=5
int(3.9)=3, int(-3.9)=-3  (truncates toward zero)
int('3.5'): ValueError
```

> **Note:** to protect against denial-of-service attacks, converting a very
> long digit string (more than 4300 digits by default) to `int` raises
> `ValueError`. See `sys.set_int_max_str_digits` if you really need it.

#### `float(x=0.0)`

`float` parses decimal and scientific notation, plus the special values
`'nan'` and `'inf'`. It does not understand locale formats such as a comma as
the decimal separator.

```python
print(f"{float('1e3')=}, {float(' 2.5 ')=}")
print(f"{float('inf')=}, {float('nan')=}")
print(f"float('1,5'): {raised_error_name(lambda: float('1,5'))}")
```

```text
float('1e3')=1000.0, float(' 2.5 ')=2.5
float('inf')=inf, float('nan')=nan
float('1,5'): ValueError
```

#### `str(object="")`

`str` returns the readable text form of an object, from its `__str__` method.

```python
print(f"{str(42)=}, {str(None)=}, {str(['tea'])=}")
print(f"{str(b'tea')=}  vs  {b'tea'.decode('utf-8')=}")
```

```text
str(42)='42', str(None)='None', str(['tea'])="['tea']"
str(b'tea')="b'tea'"  vs  b'tea'.decode('utf-8')='tea'
```

> **Warning:** `str(b'tea')` does **not** decode the bytes; it gives the text
> `"b'tea'"`, prefix and quotes included. Decode bytes with
> `.decode("utf-8")`.

#### `bool(x=False)`

`bool` returns an object's truthiness (see 1.3.8): zero, empty containers,
`None` and `False` are falsy; almost everything else is truthy.

```python
print(f"{bool(0)=}, {bool([])=}, {bool('False')=}, {bool('0')=}")
```

```text
bool(0)=False, bool([])=False, bool('False')=True, bool('0')=True
```

> **Warning:** any non-empty string is `True`, including `'False'` and `'0'`.
> To read a boolean from a config file or query string, compare the text, for
> example `text.lower() in {"1", "true", "yes"}`. JavaScript differs here
> too: `Boolean("0")` is `true` in both languages, but `Boolean([])` is
> `true` in JavaScript and `bool([])` is `False` in Python.

#### `list(iterable=())`

`list` builds a new list from any iterable. Iterating a dict gives its keys.

```python
print(f"{list('UPI')=}, {list(range(3))=}")
print(f"{list({'a': 1, 'b': 2})=}")
```

```text
list('UPI')=['U', 'P', 'I'], list(range(3))=[0, 1, 2]
list({'a': 1, 'b': 2})=['a', 'b']
```

#### `tuple(iterable=())`

`tuple` builds a new tuple, an immutable snapshot of the items (see 1.7.7).

```python
print(f"{tuple(['tea', 'rice'])=}, {tuple('ab')=}")
```

```text
tuple(['tea', 'rice'])=('tea', 'rice'), tuple('ab')=('a', 'b')
```

#### `dict(mapping_or_pairs, **kwargs)`

`dict` builds a dict from a mapping, from an iterable of `(key, value)`
pairs, from keyword arguments, or from a mapping plus keywords that are added
on top.

```python
print(f"{dict([('tea', 249), ('rice', 525)])=}")
print(f"{dict(tea=249, rice=525)=}")
print(f"{dict({'tea': 249}, ghee=640)=}")
```

```text
dict([('tea', 249), ('rice', 525)])={'tea': 249, 'rice': 525}
dict(tea=249, rice=525)={'tea': 249, 'rice': 525}
dict({'tea': 249}, ghee=640)={'tea': 249, 'ghee': 640}
```

#### `set(iterable=())`

`set` keeps the unique elements of an iterable. `set()` is the only way to
write an empty set, because `{}` is an empty dict.

```python
print(f"{sorted(set('banana'))=}, {set()=}, {type({}).__name__=}")
```

```text
sorted(set('banana'))=['a', 'b', 'n'], set()=set(), type({}).__name__='dict'
```

#### `frozenset(iterable=())`

`frozenset` is an immutable, hashable set, so it can be a dict key or an
element of another set. Two frozensets with the same elements are equal and
hash equally, whatever order they were built in.

```python
weekend_days = frozenset({"sat", "sun"})
same_days = frozenset({"sun", "sat"})
print(f"{sorted(weekend_days)=}")
print(f"{hash(weekend_days) == hash(same_days)=}")
```

```text
sorted(weekend_days)=['sat', 'sun']
hash(weekend_days) == hash(same_days)=True
```

#### `bytes(source, encoding)`

`bytes` has three main forms: encode a string with an encoding, create a
zero-filled buffer of a given size, or copy a list of integers from 0 to 255.
The rupee sign takes three bytes in UTF-8.

```python
print(f"{bytes('₹99', 'utf-8')=}")
print(f"{bytes(3)=}, {bytes([72, 105])=}")
```

```text
bytes('₹99', 'utf-8')=b'\xe2\x82\xb999'
bytes(3)=b'\x00\x00\x00', bytes([72, 105])=b'Hi'
```

#### `chr(code_point)`

`chr` returns the one-character string for a Unicode code point. Python
strings are sequences of code points, so an emoji is one character.

```python
print(f"{chr(65)=}, {chr(8377)=}, {chr(0x1F600)=}")
```

```text
chr(65)='A', chr(8377)='₹', chr(0x1F600)='😀'
```

#### `ord(character)`

`ord` is the inverse of `chr`: the code point of a single character. A
longer string raises `TypeError`.

```python
print(f"{ord('A')=}, {ord('₹')=}, {hex(ord('₹'))=}")
print(f"ord('ab'): {raised_error_name(lambda: ord('ab'))}")
```

```text
ord('A')=65, ord('₹')=8377, hex(ord('₹'))='0x20b9'
ord('ab'): TypeError
```

#### `bin(integer)`

`bin` returns binary text with a `0b` prefix. A negative number gets a minus
sign, not two's complement. `format(n, "b")` gives the digits without the
prefix, with optional padding.

```python
print(f"{bin(10)=}, {bin(-10)=}, {format(10, '08b')=}")
```

```text
bin(10)='0b1010', bin(-10)='-0b1010', format(10, '08b')='00001010'
```

#### `hex(integer)`

`hex` returns hexadecimal text with a `0x` prefix, in lowercase.
`format(n, "X")` gives uppercase digits without the prefix.

```python
print(f"{hex(255)=}, {hex(8377)=}, {format(255, 'X')=}")
```

```text
hex(255)='0xff', hex(8377)='0x20b9', format(255, 'X')='FF'
```

#### `oct(integer)`

`oct` returns octal text with a `0o` prefix. Unix file permissions are the
place you meet octal: `0o755` is the familiar `rwxr-xr-x`. Note that Python
requires the `0o` prefix; a literal with a leading zero such as `0755` is a
`SyntaxError`, which avoids a classic JavaScript and C trap.

```python
print(f"{oct(8)=}, {oct(0o755)=}, {0o755 == 493=}")
```

```text
oct(8)='0o10', oct(0o755)='0o755', 0o755 == 493=True
```

#### `format(value, format_spec="")`

`format` applies the format-spec mini-language of f-strings (see 1.4.3) as a
function call: `format(x, ",.2f")` is the same as `f"{x:,.2f}"`. It calls the
value's `__format__` method, so types such as `Decimal` and `datetime` define
their own specs.

```python
print(f"{format(1234567.891, ',.2f')=}")
print(f"{format(0.25, '.0%')=}, {format(42, '>6')=}")
```

```text
format(1234567.891, ',.2f')='1,234,567.89'
format(0.25, '.0%')='25%', format(42, '>6')='    42'
```

#### `repr(object)`

`repr` returns the unambiguous developer form of an object, from its
`__repr__` method. For strings it adds quotes, so you can see the difference
between the number `249` and the text `'249'`. For built-in types, the result
is valid Python that recreates the value. The `!r` conversion in f-strings and
the `=` specifier both use `repr`.

```python
price_text = "249"
print(f"{str(price_text)=}, {repr(price_text)=}")
print(f"{eval(repr([1, 'two', None])) == [1, 'two', None]=}")
```

```text
str(price_text)='249', repr(price_text)="'249'"
eval(repr([1, 'two', None])) == [1, 'two', None]=True
```

#### `ascii(object)`

`ascii` is like `repr`, but every non-ASCII character is replaced by an
escape sequence. It is useful for logs and terminals that cannot show
Unicode. The output below shows the `repr` of the result, so each backslash
appears doubled.

```python
print(f"{ascii('₹99 café')=}")
```

```text
ascii('₹99 café')="'\\u20b999 caf\\xe9'"
```

### Introspection

Introspection functions ask an object about itself at run time: its class,
its attributes, its identity. JavaScript spreads this across `typeof`,
`instanceof`, `Object.keys` and `Reflect`; Python has one built-in for each
question.

| Function | What it does | Example | Result |
| --- | --- | --- | --- |
| `type` | Class of an object | `type(3)` | `<class 'int'>` |
| `isinstance` | Instance check | `isinstance(3, int \| float)` | `True` |
| `issubclass` | Subclass check | `issubclass(bool, int)` | `True` |
| `id` | Identity number | `id(a) == id(b)` | `True` if same object |
| `hash` | Hash value | `hash(1) == hash(1.0)` | `True` |
| `callable` | Can it be called? | `callable(len)` | `True` |
| `dir` | Attribute names | `"upper" in dir("")` | `True` |
| `vars` | `__dict__` of object | `vars(order)` | `{'x': 1}` |

| Function | What it does | Example | Result |
| --- | --- | --- | --- |
| `globals` | Module namespace | `"x" in globals()` | `True` if defined |
| `locals` | Function namespace | `locals()` | dict snapshot |
| `getattr` | Read by name | `getattr(order, "y", 0)` | `0` |
| `setattr` | Write by name | `setattr(order, "x", 1)` | `None` |
| `hasattr` | Attribute exists? | `hasattr(order, "x")` | `True` |
| `delattr` | Delete by name | `delattr(order, "x")` | `None` |
| `help` | Show documentation | `help(divmod)` | prints docs |

In these rows, `order` is an instance of an empty class after
`setattr(order, "x", 1)`.

| Function | JavaScript equivalent |
| --- | --- |
| `type` | `typeof x`, `x.constructor` |
| `isinstance` | `x instanceof C` |
| `issubclass` | `C.prototype instanceof B` |
| `id` | none |
| `hash` | none |
| `callable` | `typeof f === "function"` |
| `dir` | `Object.getOwnPropertyNames` |
| `vars` | the object itself |
| `globals` | `globalThis` |
| `locals` | none |
| `getattr` | `obj[name] ?? fallback` |
| `setattr` | `obj[name] = value` |
| `hasattr` | `name in obj` |
| `delattr` | `delete obj[name]` |
| `help` | none (MDN) |

#### `type(obj)` / `type(name, bases, namespace)`

With one argument, `type` returns the class of an object. Unlike JavaScript's
`typeof`, which returns a string such as `"number"`, `type` returns the class
object itself, and `type(type)` is `type`. The rarely used three-argument
form creates a new class at run time; Phase 2 covers this together with
metaclasses.

```python
sample_quantity, sample_name = 3, "tea"
print(f"{type(sample_quantity)=}, {type(sample_name).__name__=}")
print(f"{type(type)=}")
DynamicProduct = type("DynamicProduct", (), {"currency": "INR"})
print(f"{DynamicProduct.__name__=}, {DynamicProduct().currency=}")
```

```text
type(sample_quantity)=<class 'int'>, type(sample_name).__name__='str'
type(type)=<class 'type'>
DynamicProduct.__name__='DynamicProduct', DynamicProduct().currency='INR'
```

#### `isinstance(obj, class_or_tuple)`

`isinstance` returns `True` if the object is an instance of the class **or
of a subclass**. The second argument can be a tuple of classes or, since
Python 3.10, a union written with `|`. Prefer `isinstance(x, int)` over
`type(x) == int`, because the latter rejects subclasses.

```python
print(f"{isinstance(3, int)=}, {isinstance(3.0, int | float)=}")
print(f"{isinstance('3', (int, float))=}")
print(f"{isinstance(True, int)=}  (bool subclasses int)")
```

```text
isinstance(3, int)=True, isinstance(3.0, int | float)=True
isinstance('3', (int, float))=False
isinstance(True, int)=True  (bool subclasses int)
```

> **Warning:** `bool` is a subclass of `int`, so `isinstance(True, int)` is
> `True`. When validating that a value is "a number but not a boolean",
> check `bool` first.

#### `issubclass(cls, class_or_tuple)`

`issubclass` is the same test for classes. Every class is a subclass of
`object`, and a class counts as a subclass of itself.

```python
print(f"{issubclass(bool, int)=}, {issubclass(int, object)=}")
print(f"{issubclass(str, int)=}")
```

```text
issubclass(bool, int)=True, issubclass(int, object)=True
issubclass(str, int)=False
```

#### `id(obj)`

`id` returns an integer that is unique among the objects alive at the same
time. In CPython it is the object's memory address. Two names refer to the
same object exactly when their ids are equal, which is what `is` tests
(see 1.2).

```python
first_cart = ["tea"]
second_cart = first_cart
print(f"{id(first_cart) == id(second_cart)=}")
print(f"{id(first_cart) == id(['tea'])=}")
```

```text
id(first_cart) == id(second_cart)=True
id(first_cart) == id(['tea'])=False
```

> **Note:** id values change on every run and can be reused after an object
> is freed. Compare ids; never store or print them as data.

#### `hash(obj)`

`hash` returns the integer that dicts and sets use to place a key (see 1.6.2).
The rule is that equal objects must have equal hashes, which is why
`1`, `1.0` and `True` hash the same and count as the same dict key. Mutable
built-ins (`list`, `dict`, `set`) have no hash, because their value, and so
their hash, could change while they sit in a dict.

```python
print(f"{hash(1) == hash(1.0) == hash(True)=}")
print(f"{hash((1, 2)) == hash((1, 2))=}")
print(f"hash([]): {raised_error_name(lambda: hash([]))}")
```

```text
hash(1) == hash(1.0) == hash(True)=True
hash((1, 2)) == hash((1, 2))=True
hash([]): TypeError
```

#### `callable(obj)`

`callable` returns `True` for anything that can be called: functions,
lambdas, classes (calling a class creates an instance) and objects whose
class defines `__call__`.

```python
print(f"{callable(len)=}, {callable(str)=}")
print(f"{callable('len')=}, {callable(lambda: 0)=}")
```

```text
callable(len)=True, callable(str)=True
callable('len')=False, callable(lambda: 0)=True
```

#### `dir(obj)`

`dir` returns the sorted list of attribute names an object has, including
the dunder methods. Filtering out the names that start with `_` gives a quick
overview of a type's public API, which is handy in a REPL.

```python
public_str_methods = [name for name in dir(str) if not name.startswith("_")]
print(f"{len(public_str_methods)=}")
print(f"{public_str_methods[:4]=}")
```

```text
len(public_str_methods)=47
public_str_methods[:4]=['capitalize', 'casefold', 'center', 'count']
```

#### `vars(obj)`

`vars` returns the object's `__dict__`: its attributes as a real dict. It
works for instances, classes and modules. It is the same dict object, not a
copy, so writing to it changes the object. Instances of classes with
`__slots__` (Phase 2) have no `__dict__`, and `vars` raises `TypeError`.

```python
class Customer:
    """A small class for the attribute built-ins."""

    def __init__(self, name: str, city: str) -> None:
        self.name = name
        self.city = city


asha = Customer("Asha", "Pune")
print(f"{vars(asha)=}, {vars(asha) is asha.__dict__=}")
```

```text
vars(asha)={'name': 'Asha', 'city': 'Pune'}, vars(asha) is asha.__dict__=True
```

#### `globals()`

`globals` returns the current module's namespace as a dict. At the top level
of a script or notebook, that is every name defined so far. Each module has
its own globals; there is no single global object as in JavaScript's
`globalThis`.

```python
print(f"{'Customer' in globals()=}, {type(globals()).__name__=}")
print(f"{globals()['asha'] is asha=}")
```

```text
'Customer' in globals()=True, type(globals()).__name__='dict'
globals()['asha'] is asha=True
```

#### `locals()`

`locals` returns the local names of the current function. This changed in
Python 3.13 (PEP 667): inside a function it now returns a **fresh snapshot**
on every call. Assignments made after the call do not show up in an earlier
snapshot, and writing to the snapshot never changes a variable.

```python
def checkout_summary(order_total: int) -> None:
    """Show locals() as a snapshot."""
    delivery_fee = 40
    snapshot = locals()
    delivery_fee = 0
    print(f"{snapshot=}")
    print(f"{locals()['delivery_fee']=}  (a new snapshot sees the change)")


checkout_summary(1200)
```

```text
snapshot={'order_total': 1200, 'delivery_fee': 40}
locals()['delivery_fee']=0  (a new snapshot sees the change)
```

#### `getattr(obj, name, default)`

`getattr` reads an attribute whose name is a string known only at run time:
a column header, a config key, a field from a request. With a literal name,
just write `obj.name`. The optional default is returned instead of raising
`AttributeError`. It is the Python version of JavaScript's
`obj[name] ?? fallback`, except that Python separates attributes from
dictionary keys, so `obj[name]` would not work on a plain object.

```python
for field_name in ("city", "phone"):
    print(f"{field_name}: {getattr(asha, field_name, 'not given')}")
missing_field = "phone"
print(
    f"no default: {raised_error_name(lambda: getattr(asha, missing_field))}"
)
```

```text
city: Pune
phone: not given
no default: AttributeError
```

#### `setattr(obj, name, value)`

`setattr` assigns an attribute by name, for example when applying a dict of
updates to an object.

```python
profile_updates = {"city": "Mumbai", "phone": "98200 00000"}
for field_name, new_value in profile_updates.items():
    setattr(asha, field_name, new_value)
print(f"{vars(asha)=}")
```

```text
vars(asha)={'name': 'Asha', 'city': 'Mumbai', 'phone': '98200 00000'}
```

#### `hasattr(obj, name)`

`hasattr` returns `True` if `getattr(obj, name)` would succeed. It works by
calling `getattr` and catching `AttributeError`.

```python
print(f"{hasattr(asha, 'name')=}, {hasattr(asha, 'email')=}")
print(f"{hasattr('tea', 'upper')=}")
```

```text
hasattr(asha, 'name')=True, hasattr(asha, 'email')=False
hasattr('tea', 'upper')=True
```

#### `delattr(obj, name)`

`delattr` deletes an attribute by name; it is the dynamic form of
`del obj.name`.

```python
for field_name in ("city", "phone"):
    delattr(asha, field_name)
print(f"{vars(asha)=}, {hasattr(asha, 'city')=}")
```

```text
vars(asha)={'name': 'Asha'}, hasattr(asha, 'city')=False
```

#### `help(obj)`

`help` prints an object's signature and docstring. In an interactive session
it opens a pager; in a script it prints. Unit 1.10.8 shows how to write
docstrings that `help` can display. The `/` in the signature means both
parameters are positional-only (see 1.10).

```python
help(divmod)
```

```text
Help on built-in function divmod in module builtins:

divmod(x, y, /)
    Return the tuple (x//y, x%y).  Invariant: div*y + mod == x.
```

### Input and output

| Function | What it does | Example | Result |
| --- | --- | --- | --- |
| `print` | Write text | `print("a", "b", sep=", ")` | prints `a, b` |
| `input` | Read one line | `input("Name: ")` | the line, as `str` |
| `open` | Open a file | `open(path, encoding="utf-8")` | a file object |

| Function | JavaScript equivalent |
| --- | --- |
| `print` | `console.log(...)` |
| `input` | `prompt()` / `readline` |
| `open` | `fs.openSync`, `fs.readFileSync` |

#### `print(*objects, sep=" ", end="\n", file=None, flush=False)`

`print` converts each object with `str` and writes them to standard output.
`sep` goes between the objects, `end` after the last one, and `file`
redirects the output to any object with a `write` method (a file,
`sys.stderr`, an in-memory `io.StringIO`). Output to a terminal is
line-buffered, but output to a pipe or file is block-buffered, so progress
messages may appear late; `flush=True` pushes the text out immediately.

```python
print("tea", "rice", "ghee", sep=" | ")
print("loading", end="... ")
print("done")
report_buffer = io.StringIO()
print("total", 1498, sep="=", file=report_buffer, flush=True)
print(f"{report_buffer.getvalue()=}")
```

```text
tea | rice | ghee
loading... done
report_buffer.getvalue()='total=1498\n'
```

#### `input(prompt="")`

`input` prints the prompt, reads one line from standard input, and returns it
**without** the trailing newline, always as a `str`: convert numbers yourself
with `int` or `Decimal`. It raises `EOFError` if the input ends. A notebook
run headless has no keyboard, so this demo starts a child Python interpreter
and feeds its standard input. The prompts appear in the output too, because
the child writes them to its standard output.

```python
child_code = (
    'name = input("Name: "); qty = int(input("Qty: ")); '
    'print(f"|{name}|{qty * 2}|")'
)
completed = subprocess.run(
    [sys.executable, "-c", child_code],
    input="Asha\n3\n",
    capture_output=True,
    text=True,
    check=True,
)
print(f"{completed.stdout=}")
```

```text
completed.stdout='Name: Qty: |Asha|6|\n'
```

#### `open(file, mode="r", encoding=None, ...)`

`open` opens a file and returns a file object. Always pass
`encoding="utf-8"` for text files: the default depends on the operating
system's locale (it is not UTF-8 on many Windows setups). Use `with` so the
file is closed even if an error happens (Unit 1.14). The main modes are
`"r"` (read), `"w"` (write, truncating the file first), `"a"` (append) and
`"x"` (create, failing if the file exists), plus `"b"` for bytes. A text file
object is itself an iterator over its lines.

```python
receipt_path = scratch_dir / "unit_1_9_receipt.txt"
with open(receipt_path, "w", encoding="utf-8") as receipt_file:
    receipt_file.write("tea 2 x ₹249\n")
    receipt_file.write("ghee 1 x ₹640\n")
with open(receipt_path, encoding="utf-8") as receipt_file:
    receipt_lines = [line.rstrip() for line in receipt_file]
print(f"{receipt_lines=}, {receipt_file.closed=}")
```

```text
receipt_lines=['tea 2 x ₹249', 'ghee 1 x ₹640'], receipt_file.closed=True
```

### Dangerous: running code from strings

| Function | What it does | Example | Result |
| --- | --- | --- | --- |
| `eval` | Evaluate an expression | `eval("2 + 3")` | `5` |
| `exec` | Run statements | `exec("x = 1", namespace)` | `None` |
| `compile` | Source → code object | `compile("x * 2", "<r>", "eval")` | a code object |
| `ast.literal_eval` | Parse literals only | `literal_eval("[1, 2]")` | `[1, 2]` |

| Function | JavaScript equivalent |
| --- | --- |
| `eval` | `eval(code)` |
| `exec` | `new Function(code)()` |
| `compile` | `new Function(code)` |
| `ast.literal_eval` | `JSON.parse(text)` |

> **Warning:** `eval`, `exec` and `compile` run arbitrary code. Never pass
> them text that came from a user, a file or the network. Restricting the
> `globals` dict does **not** make them safe.

#### `eval(expression, globals=None, locals=None)`

`eval` evaluates one expression and returns its value. Optional dicts supply
the global and local names it can see. The demo shows why it is dangerous:
an innocent-looking "expression" can import a module and call any function
in it. Even with an empty `__builtins__`, the expression can climb the object
graph from a tuple to `object` and list every class loaded in the process,
including ones that can run shell commands.

```python
print(f"{eval('2 + 3 * 4')=}")
print(f"{eval('unit_price * 2', {'unit_price': 249})=}")
sneaky_input = "__import__('os').getcwd()"
print(f"{type(eval(sneaky_input)).__name__=}")
print("(it imported os and ran a function)")
escape_route = "().__class__.__mro__[1].__subclasses__()"
reachable_classes = eval(escape_route, {"__builtins__": {}})
print(f"{len(reachable_classes) > 100=}")
print("(every loaded class is reachable without builtins)")
```

```text
eval('2 + 3 * 4')=14
eval('unit_price * 2', {'unit_price': 249})=498
type(eval(sneaky_input)).__name__='str'
(it imported os and ran a function)
len(reachable_classes) > 100=True
(every loaded class is reachable without builtins)
```

#### `exec(source, globals=None, locals=None)`

`exec` runs statements (definitions, loops, imports) and always returns
`None`. Pass a dict as the namespace to keep the names it defines out of your
own module.

```python
plugin_namespace: dict[str, Any] = {}
exec_result = exec(
    "def bonus(total):\n    return total // 10", plugin_namespace
)
print(f"{exec_result=}, {plugin_namespace['bonus'](1500)=}")
```

```text
exec_result=None, plugin_namespace['bonus'](1500)=150
```

#### `compile(source, filename, mode)`

`compile` turns source text into a code object without running it; it is the
first step that `eval` and `exec` perform internally. The modes are `"eval"`
(one expression), `"exec"` (statements) and `"single"` (one interactive
statement, as in the REPL). The `filename` appears in tracebacks. Compiling
once and evaluating many times avoids parsing the text again for every call.

```python
discount_rule = compile(
    "total * 0.9 if total > 1000 else total", "<discount-rule>", "eval"
)
print(f"{type(discount_rule).__name__=}, {discount_rule.co_filename=}")
print([eval(discount_rule, {"total": total}) for total in (500, 2000)])
```

```text
type(discount_rule).__name__='code', discount_rule.co_filename='<discount-rule>'
[500, 1800.0]
```

#### `ast.literal_eval(text)`: the safe alternative

`ast.literal_eval` is not a built-in, but it is the answer whenever you are
tempted to `eval` data. It parses the text into a syntax tree and accepts
only Python literals: strings, bytes, numbers, tuples, lists, dicts, sets,
booleans and `None`. Names, calls, attribute access and arithmetic (apart
from the `+` and `-` needed to write negative and complex numbers) are
rejected with `ValueError`, so nothing can run.
For JSON text, use `json.loads`.

```python
saved_settings = "{'currency': 'INR', 'tiers': (499, 999), 'beta': None}"
parsed_settings = ast.literal_eval(saved_settings)
print(f"{parsed_settings=}")
print(f"call: {raised_error_name(lambda: ast.literal_eval(sneaky_input))}")
print(
    f"name: {raised_error_name(lambda: ast.literal_eval('unit_price * 2'))}"
)
```

```text
parsed_settings={'currency': 'INR', 'tiers': (499, 999), 'beta': None}
call: ValueError
name: ValueError
```

### Key points

| Group | Takeaway |
| --- | --- |
| Lookup | Built-ins are the last scope; do not shadow them |
| Numeric | `round` ties to even; `sum(start=)` sets the type |
| `min` / `max` | `key` returns the item; `default` for empty |
| Iteration | `map`, `filter`, `zip` are lazy iterators |
| `any` / `all` | Short-circuit; `all([])` is `True` |
| Conversion | `int("3.5")` fails; `bool("False")` is `True` |
| Introspection | `isinstance` over `type() ==`; `getattr` default |
| `locals()` | A snapshot in functions since 3.13 |
| I/O | `print(sep, end, file, flush)`; `open(encoding=)` |
| Dangerous | `eval`/`exec` run code; use `literal_eval` |

## 1.9.5 `map` / `filter` vs comprehensions

`map` and `filter` come from functional programming, and Python has had them
since the beginning. Comprehensions arrived later (PEP 202, Python 2.0) and
became the preferred style for most cases. Both are correct; the choice is
about laziness, reuse and readability.

| Aspect | `map` / `filter` | List comprehension |
| --- | --- | --- |
| Result | lazy iterator | list, built now |
| Reusable | no: one pass | yes |
| Reads well with | an existing function | any expression |
| Needs `lambda` | for an expression | never |

### Laziness

`map` does no work until something consumes it. When you call `map(f,
items)`, Python only creates a small `map` object that remembers `f` and an
iterator over `items`; each `next()` call computes one result. A
comprehension computes every result immediately. The `loud_gst` function
below prints when it runs, so you can see when the work happens:

```python
def loud_gst(price: int) -> float:
    """Add 18% GST and print that the work happened."""
    print(f"  computing GST for {price}")
    return round(price * 1.18, 2)


lazy_prices = map(loud_gst, [100, 200])
print("map created, nothing computed yet")
print(f"{next(lazy_prices)=}")
print("comprehension:")
eager_prices = [loud_gst(price) for price in [100, 200]]
```

```text
map created, nothing computed yet
  computing GST for 100
next(lazy_prices)=118.0
comprehension:
  computing GST for 100
  computing GST for 200
```

Only one GST value was computed for the `map`, because only one `next()`
was called. Laziness saves memory for long inputs and lets you stop early,
but it also means errors appear late, at the point of consumption rather
than at the line that created the `map`. If you want laziness with
comprehension syntax, use a generator expression: `(f(x) for x in items)`.

### Single use

A `map` or `filter` object is an iterator, so after one full pass it is
empty. A second pass does not raise an error; it silently finds nothing.
This is the biggest trap for JavaScript developers, whose `.map()` returns an
array that can be read any number of times. Convert with `list()` if you need
the values twice.

```python
valid_quantities = filter(lambda quantity: quantity > 0, [3, 0, 2])
print(f"{sum(valid_quantities)=}")
print(f"{sum(valid_quantities)=}  (already consumed)")
```

```text
sum(valid_quantities)=5
sum(valid_quantities)=0  (already consumed)
```

> **Warning:** the second `sum` returns `0`, not an error. Code that checks
> `if valid_quantities:` is also wrong: a `filter` object is always truthy,
> even when it will produce nothing.

### Readability

With an existing named function, `map` is short and clear:
`map(str.title, names)` reads as "title-case every name". As soon as you need
a `lambda`, and especially a `lambda` inside a `filter` inside a `map`, the
comprehension wins: it puts the expression and the condition in reading
order, with no extra function syntax.

```python
product_names = ["tea", "rice", "ghee"]
prices_in_rupees = [80, 249, 640, 1500]
print(f"{list(map(str.title, product_names))=}  (fine)")
with_lambdas = list(
    map(
        lambda price: price * 2,
        filter(lambda price: price > 200, prices_in_rupees),
    )
)
with_comprehension = [price * 2 for price in prices_in_rupees if price > 200]
print(f"{with_lambdas == with_comprehension=}")
print(f"{with_comprehension=}")
```

```text
list(map(str.title, product_names))=['Tea', 'Rice', 'Ghee']  (fine)
with_lambdas == with_comprehension=True
with_comprehension=[498, 1280, 3000]
```

### Timing

The four candidates below all uppercase 10 000 words: a loop with `append`,
a comprehension, `map` with the built-in method `str.upper`, and `map` with a
`lambda`. `timeit.repeat` runs each one 50 times, three times over, and the
best run is reported.

```python
sample_words = ["tea", "rice", "ghee", "dal"] * 2_500


def upper_with_loop() -> list[str]:
    """Uppercase with an explicit loop."""
    result = []
    for word in sample_words:
        result.append(word.upper())
    return result


timing_candidates = {
    "loop + append": upper_with_loop,
    "comprehension": lambda: [word.upper() for word in sample_words],
    "map(str.upper)": lambda: list(map(str.upper, sample_words)),
    "map(lambda)": lambda: list(map(lambda word: word.upper(), sample_words)),
}
for label, candidate in timing_candidates.items():
    seconds = min(timeit.repeat(candidate, number=50, repeat=3)) / 50
    print(f"{label:15} {seconds * 1e6:8.1f} µs per 10 000 words")
```

```text
loop + append      452.9 µs per 10 000 words
comprehension      377.5 µs per 10 000 words
map(str.upper)     309.7 µs per 10 000 words
map(lambda)        563.0 µs per 10 000 words
```

> **Note:** timings vary by machine, load and Python version; your numbers
> will differ. The ranking is what matters, and it is usually stable.

The reasons are visible in the bytecode. The loop looks up `result.append`
and calls it as a method for every item. The comprehension uses a dedicated
`LIST_APPEND` instruction, with no lookup and no call. `map(str.upper, ...)`
runs its whole loop in C and calls a C function per item, so it is usually
the fastest. `map` with a `lambda` loses that edge, because every item pays
for a full Python function call, which is more expensive than evaluating the
expression inline as the comprehension does.

### Predict the output

```python
quantities = map(int, ["10", "20", "30"])
print(sum(quantities), sum(quantities))
print(any([]), all([]))
```

<details><summary>Answer</summary>

```text
60 0
False True
```

The first `sum` consumes the `map` iterator, so the second `sum` sees no
items and returns its start value `0`. `any([])` has no truthy item, so it is
`False`; `all([])` has no falsy item, so it is vacuously `True`.

</details>

### Key points

| Idea | Takeaway |
| --- | --- |
| `map` / `filter` | Lazy: no work until consumed |
| Single use | Second pass is silently empty |
| Truthiness | A `map` object is always truthy |
| Existing function | `map(str.upper, xs)` reads well, is fast |
| Expression or filter | Use a comprehension |
| Lazy + readable | Generator expression `(f(x) for x in xs)` |

## 1.9.6 Pythonic idioms

"Pythonic" code uses the language's own tools instead of patterns carried
over from C or JavaScript. It is not about style points: the idioms below are
shorter, harder to get wrong (no off-by-one indexes, no forgotten `break`),
and usually faster because the loop runs in C. Each pair does the same work:
first the translated style, then the Python idiom.

### `enumerate` over `range(len())`

When you need the index *and* the item, do not loop over indexes and then
index into the list. `enumerate` gives both, and it works on any iterable,
including files and generators that cannot be indexed.

```python
queue_names = ["asha", "ravi", "meena"]
for position in range(len(queue_names)):  # un-Pythonic
    print(f"{position}: {queue_names[position]}", end="  ")
print()
for position, queue_name in enumerate(queue_names):  # idiomatic
    print(f"{position}: {queue_name}", end="  ")
print()
```

```text
0: asha  1: ravi  2: meena
0: asha  1: ravi  2: meena
```

### `zip` over parallel indexing

To walk two sequences together, `zip` them instead of sharing an index.
With `strict=True` you also get the length check that the indexed version
silently skips (it would raise `IndexError` only if the *second* list were
shorter, and ignore extra items if it were longer).

```python
cities = ["Pune", "Delhi"]
temperatures = [31, 38]
for index in range(len(cities)):  # un-Pythonic
    print(f"{cities[index]}: {temperatures[index]}°C", end="  ")
print()
for city, temperature in zip(cities, temperatures, strict=True):  # idiomatic
    print(f"{city}: {temperature}°C", end="  ")
print()
```

```text
Pune: 31°C  Delhi: 38°C
Pune: 31°C  Delhi: 38°C
```

### `in` instead of a search loop or `==` chain

The `in` operator tests membership in any container. Against a set literal it
is a hash lookup, and CPython even stores a constant set literal as a
`frozenset` constant, so the test is cheap. It replaces both a hand-written
search loop and a chain of `or` comparisons:

```python
payment_method = "upi"
is_instant_long = (
    payment_method == "upi"
    or payment_method == "card"
    or payment_method == "wallet"
)
is_instant = payment_method in {"upi", "card", "wallet"}
print(f"{is_instant_long=}, {is_instant=}")
```

```text
is_instant_long=True, is_instant=True
```

> **Warning:** `payment_method == "upi" or "card"` does **not** test two
> values. It parses as `(payment_method == "upi") or "card"`, and the
> non-empty string `"card"` is always truthy. Use `in`.

### `any` / `all` instead of a flag and `break`

A flag variable, a loop and a `break` are three moving parts for one
question: "is there at least one?" `any` answers it directly and stops at the
first match, just as the `break` did. `all` answers "are they all?".

```python
stock_levels = [5, 0, 12]
has_sold_out = False  # un-Pythonic
for stock in stock_levels:
    if stock == 0:
        has_sold_out = True
        break
print(f"{has_sold_out=}, {any(stock == 0 for stock in stock_levels)=}")
print(f"{all(stock > 0 for stock in stock_levels)=}")
```

```text
has_sold_out=True, any(stock == 0 for stock in stock_levels)=True
all(stock > 0 for stock in stock_levels)=False
```

### `dict.get` instead of checking the key first

Checking `if key in d` and then reading `d[key]` looks the key up twice.
`d.get(key, default)` does it once and reads as a single thought. It is the
Python counterpart of JavaScript's `obj[key] ?? fallback`. For counting and
grouping, `collections.Counter` and `defaultdict` (Unit 1.6) go one step
further.

```python
discount_by_code = {"WELCOME10": 10, "FESTIVE20": 20}
entered_code = "SUMMER5"
if entered_code in discount_by_code:  # un-Pythonic
    discount_percent = discount_by_code[entered_code]
else:
    discount_percent = 0
print(f"{discount_percent=}, {discount_by_code.get(entered_code, 0)=}")
```

```text
discount_percent=0, discount_by_code.get(entered_code, 0)=0
```

### EAFP preview

Python culture prefers **EAFP**, "easier to ask forgiveness than
permission": try the operation and handle the failure, instead of checking
every precondition first (**LBYL**, "look before you leap"). EAFP avoids a
race between the check and the use (a file can disappear between
`exists()` and `open()`), and it does not do the work twice. It also means
the operation itself decides what is valid, so your check cannot drift away
from it. In JavaScript the same choice exists, but `try`/`catch` is used less
often because many operations return `NaN` or `undefined` instead of
throwing. Unit 1.14 covers exceptions in depth.

```python
def parse_quantity_lbyl(text: str) -> int | None:
    """Look before you leap: check, then convert."""
    if text.strip().isdigit():
        return int(text)
    return None


def parse_quantity_eafp(text: str) -> int | None:
    """Easier to ask forgiveness: convert, handle the failure."""
    try:
        return int(text)
    except ValueError:
        return None


for raw_quantity in ("3", " 4 ", "-2", "two"):
    print(
        f"{raw_quantity!r:6} LBYL={parse_quantity_lbyl(raw_quantity)}, "
        f"EAFP={parse_quantity_eafp(raw_quantity)}"
    )
```

```text
'3'    LBYL=3, EAFP=3
' 4 '  LBYL=4, EAFP=4
'-2'   LBYL=None, EAFP=-2
'two'  LBYL=None, EAFP=None
```

Look at `"-2"`: `isdigit` does not accept a sign, so the LBYL version
rejects a value that `int` parses fine. Checks written by hand tend to drift
from what the operation really accepts; with EAFP, `int` itself is the check.

### Key points

| Instead of | Write |
| --- | --- |
| `for i in range(len(xs))` | `for i, x in enumerate(xs)` |
| `a[i]`, `b[i]` together | `zip(a, b, strict=True)` |
| `x == 1 or x == 2` | `x in {1, 2}` |
| flag + loop + `break` | `any(...)` / `all(...)` |
| `if k in d: v = d[k]` | `v = d.get(k, default)` |
| check, then act (LBYL) | try, then handle (EAFP) |

## Lab 1.9

The lab has three exercises. In the notebook, each one has a stub function
and a check cell that prints `PASS` or `FAIL` for every test case. Try each
exercise before opening its solution.

### Exercise 1 — `read_in_chunks(stream, size)`

Return an **iterator** over chunks of at most `size` characters (for a text
stream) or bytes (for a binary stream). Build it with
`iter(callable, sentinel)`: no `while` loop and no generator. It must work
for both kinds of stream.

```python
def read_in_chunks(stream: IO[Any], size: int) -> Iterator[Any]:
    """Return an iterator of chunks of at most size items from stream."""
```

Hints:

- `stream.read(0)` returns the empty value of the right type: `""` for a text
  stream, `b""` for a binary one. That is your sentinel.
- Raise `ValueError` immediately if `size < 1`, when the function is called,
  not later when the first chunk is requested.
- Read lazily: nothing may be read from the stream until the first `next()`.

The checks use in-memory streams (`io.StringIO` and `io.BytesIO`):

| Check | Expected |
| --- | --- |
| `"abcdefgh"`, size 3 | `['abc', 'def', 'gh']` |
| `b"\x00\x01\x02\x03"`, size 2 | `[b'\x00\x01', b'\x02\x03']` |
| empty text stream, size 4 | `[]` |
| `b"hi"`, size 100 | `[b'hi']` |
| `iter(result) is result` | `True` |
| position before / after `next()` | `[0, 3]` |
| size 0 | raises `ValueError` |

<details><summary>Solution</summary>

```python
def read_in_chunks(stream: IO[Any], size: int) -> Iterator[Any]:
    """Return an iterator of chunks of at most size items from stream."""
    if size < 1:
        raise ValueError(f"size must be at least 1, got {size}")
    end_of_stream = stream.read(0)  # "" for text, b"" for binary streams
    return iter(lambda: stream.read(size), end_of_stream)
```

`stream.read(0)` reads nothing, so it does not move the stream position, but
it tells you which empty value the stream returns at its end. The validation
runs before `iter` is called, so a bad size fails at once. The lambda closes
over `stream` and `size`, and `iter` does not call it until the first
`next()`, which makes the function lazy.

```python
print(list(read_in_chunks(io.StringIO("abcdefgh"), 3)))
print(list(read_in_chunks(io.BytesIO(b"\x00\x01\x02\x03"), 2)))
lazy_stream = io.StringIO("abcdefgh")
chunk_iterator = read_in_chunks(lazy_stream, 3)
print(lazy_stream.tell(), next(chunk_iterator), lazy_stream.tell())
```

```text
['abc', 'def', 'gh']
[b'\x00\x01', b'\x02\x03']
0 abc 3
```

</details>

### Exercise 2 — rewrite five un-Pythonic loops

The five functions below work, but they are written in translated C or
JavaScript style. Write idiomatic versions with the same names minus
`_unpythonic`, using the tools from 1.9.2 to 1.9.6.

```python
def numbered_lines_unpythonic(lines: list[str]) -> list[str]:
    """Number lines from 1."""
    result = []
    for index in range(len(lines)):
        result.append(f"{index + 1}. {lines[index]}")
    return result


def line_totals_unpythonic(
    unit_prices: list[int], quantities: list[int]
) -> list[int]:
    """Multiply parallel lists."""
    totals = []
    for index in range(len(unit_prices)):
        totals.append(unit_prices[index] * quantities[index])
    return totals


def has_overdue_unpythonic(days_overdue: list[int]) -> bool:
    """Return True if any invoice is more than 30 days overdue."""
    found = False
    for days in days_overdue:
        if days > 30:
            found = True
            break
    return found


def count_statuses_unpythonic(statuses: list[str]) -> dict[str, int]:
    """Count how often each status occurs."""
    counts = {}
    for status in statuses:
        if status in counts:
            counts[status] = counts[status] + 1
        else:
            counts[status] = 1
    return counts


def even_squares_unpythonic(numbers: list[int]) -> list[int]:
    """Square the even numbers."""
    squares = []
    for number in numbers:
        if number % 2 == 0:
            squares.append(number * number)
    return squares
```

| Function | Use |
| --- | --- |
| `numbered_lines(lines)` | `enumerate(..., start=1)` in a comprehension |
| `line_totals(prices, quantities)` | `zip(..., strict=True)` |
| `has_overdue(days_overdue)` | `any(...)` |
| `count_statuses(statuses)` | `dict.get` or `collections.Counter` |
| `even_squares(numbers)` | a comprehension with a filter |

The checks run each new function and its original on the same inputs, for
example `["GET /", "POST /cart"]` for the lines and
`["paid", "failed", "paid", "refunded", "paid"]` for the statuses. They also
check the edge cases: empty inputs, `has_overdue([30, 0])` is `False` (30
days is not *more* than 30), and `line_totals([249, 640], [2])` must raise
`ValueError`, which the original silently does not. The checks cannot judge
style, so compare your code with the reference solution afterwards.

<details><summary>Solution</summary>

```python
from collections import Counter


def numbered_lines(lines: list[str]) -> list[str]:
    """Number lines from 1 (enumerate)."""
    return [
        f"{line_number}. {line}"
        for line_number, line in enumerate(lines, start=1)
    ]


def line_totals(unit_prices: list[int], quantities: list[int]) -> list[int]:
    """Multiply parallel lists (zip, strict)."""
    return [
        price * quantity
        for price, quantity in zip(unit_prices, quantities, strict=True)
    ]


def has_overdue(days_overdue: list[int]) -> bool:
    """Return True if any invoice is more than 30 days overdue (any)."""
    return any(days > 30 for days in days_overdue)


def count_statuses(statuses: list[str]) -> dict[str, int]:
    """Count how often each status occurs (Counter)."""
    return dict(Counter(statuses))


def even_squares(numbers: list[int]) -> list[int]:
    """Square the even numbers (comprehension)."""
    return [number * number for number in numbers if number % 2 == 0]
```

Each rewrite removes an index, a flag or an `append`. `count_statuses`
converts the `Counter` to a plain `dict` so the result compares equal and has
the declared type; with `dict.get` the loop body would be
`counts[status] = counts.get(status, 0) + 1`.

```python
sample_statuses = ["paid", "failed", "paid", "refunded", "paid"]
print(numbered_lines(["GET /", "POST /cart"]))
print(line_totals([249, 640], [2, 1]))
print(raised_error_name(lambda: line_totals([249, 640], [2])))
print(has_overdue([3, 45]), has_overdue([30, 0]), has_overdue([]))
print(count_statuses(sample_statuses))
print(even_squares([1, 2, 3, 4, -6]))
```

```text
['1. GET /', '2. POST /cart']
[498, 640]
ValueError
True False False
{'paid': 3, 'failed': 1, 'refunded': 1}
[4, 16, 36]
```

</details>

### Exercise 3 — summarize webhook events

A payment provider sends webhook events; amounts are in paise (1 rupee = 100
paise), and the sample list is deliberately not in time order:

```python
class WebhookEvent(NamedTuple):
    """One webhook delivery from a payment provider (amount in paise)."""

    event_id: str
    event_type: str
    amount: int
    received_at: dt.datetime


SAMPLE_WEBHOOK_EVENTS = [
    WebhookEvent(
        "evt_3", "payment.captured", 49_900, dt.datetime(2026, 11, 3, 10, 5)
    ),
    WebhookEvent(
        "evt_1", "payment.captured", 129_900, dt.datetime(2026, 11, 3, 9, 15)
    ),
    WebhookEvent(
        "evt_4", "refund.created", 19_900, dt.datetime(2026, 11, 3, 11, 0)
    ),
    WebhookEvent(
        "evt_2", "payment.failed", 129_900, dt.datetime(2026, 11, 3, 9, 40)
    ),
    WebhookEvent(
        "evt_5", "payment.captured", 9_900, dt.datetime(2026, 11, 3, 8, 55)
    ),
]
```

Write `summarize_webhooks(events)` returning a dict with exactly these keys,
using `sum`, `max` and `sorted` (no explicit loops needed):

| Key | Value |
| --- | --- |
| `"event_count"` | number of events |
| `"captured_total"` | sum of `amount` of `"payment.captured"`; `0` if none |
| `"largest_event_id"` | id with the largest `amount`; first on ties; `None` if empty |
| `"ids_by_time"` | event ids sorted by `received_at`, oldest first |
| `"event_types"` | the distinct event types, sorted |

The checks:

| Check | Expected |
| --- | --- |
| Sample: `event_count` | `5` |
| Sample: `captured_total` | `189_700` |
| Sample: `largest_event_id` | `"evt_1"` (ties with `evt_2`) |
| Sample: `ids_by_time` | `evt_5`, `evt_1`, `evt_2`, `evt_3`, `evt_4` |
| Sample: `event_types` | the three types, sorted |
| Empty list | count `0`, total `0`, `None`, `[]`, `[]` |
| Events 3 and 4 only | `captured_total` is `0` |

Hints: `max` needs both `key=` and `default=`; `sum` takes a generator
expression with a filter; a set comprehension removes duplicate types before
`sorted`.

<details><summary>Solution</summary>

```python
def summarize_webhooks(events: list[WebhookEvent]) -> dict[str, object]:
    """Summarize webhook events with sum, max and sorted."""
    largest_event = max(events, key=lambda event: event.amount, default=None)
    return {
        "event_count": len(events),
        "captured_total": sum(
            event.amount
            for event in events
            if event.event_type == "payment.captured"
        ),
        "largest_event_id": (
            None if largest_event is None else largest_event.event_id
        ),
        "ids_by_time": [
            event.event_id
            for event in sorted(events, key=lambda event: event.received_at)
        ],
        "event_types": sorted({event.event_type for event in events}),
    }
```

`max` with `key` returns the whole event, and because `max` keeps the first
maximal item, `evt_1` wins its tie with `evt_2`. `default=None` handles the
empty list without a special case. `sum` of an empty generator is `0`, its
default start value. `sorted` with `key=` returns the events in time order
without changing the input list, and the set comprehension removes duplicate
types before sorting.

```python
for key, value in summarize_webhooks(SAMPLE_WEBHOOK_EVENTS).items():
    print(f"{key}: {value}")
print("--- no events ---")
for key, value in summarize_webhooks([]).items():
    print(f"{key}: {value}")
```

```text
event_count: 5
captured_total: 189700
largest_event_id: evt_1
ids_by_time: ['evt_5', 'evt_1', 'evt_2', 'evt_3', 'evt_4']
event_types: ['payment.captured', 'payment.failed', 'refund.created']
--- no events ---
event_count: 0
captured_total: 0
largest_event_id: None
ids_by_time: []
event_types: []
```

</details>

Running the notebook's check cells against the reference solutions prints:

```text
Exercise 1 — read_in_chunks
PASS  text chunks
PASS  binary chunks
PASS  empty stream
PASS  size larger than data
PASS  returns an iterator
PASS  reads lazily
PASS  size 0 raises
7/7 checks passed
Exercise 2 — five idiomatic rewrites
PASS  numbered_lines
PASS  numbered_lines empty
PASS  line_totals
PASS  line_totals strict
PASS  has_overdue true
PASS  has_overdue false
PASS  has_overdue empty
PASS  count_statuses
PASS  count_statuses empty
PASS  even_squares
10/10 checks passed
Exercise 3 — summarize_webhooks
PASS  sample summary
PASS  no events
PASS  no captures
3/3 checks passed
```

## Recap

| Concept | Takeaway | JavaScript equivalent |
| --- | --- | --- |
| Iterable / iterator | `__iter__` gives an iterator; `__next__` items | `[Symbol.iterator]`, `next()` |
| End of iteration | `StopIteration` is raised | `{done: true}` |
| `for` loop | `iter()` once, `next()` until done | `for...of` |
| Bytecode | `GET_ITER` + `FOR_ITER` | none |
| `iter(f, sentinel)` | Call `f` until sentinel: chunked reads | none |
| `enumerate` | Index + item; `start=1` | `entries()` |
| `zip(strict=True)` | Parallel items, length-checked | lodash `zip` |
| `reversed`, `sorted` | Reverse iterator; new sorted list | `toReversed`, `toSorted` |
| `range` | Lazy int sequence, O(1) `in` | `Array.from({length})` |
| Comprehensions | `[e for x in it if c]`, dict, set | `map` + `filter` |
| Nested `for` | Left to right = outer to inner | `flatMap` |
| Comprehension scope | Variable does not leak; inlined 3.12 | `let` |
| Numeric built-ins | `round` to even; `sum(start=)` | `Math.*`, `reduce` |
| `min` / `max` | `key=` and `default=` | `Math.min(...a)` |
| `map` / `filter` | Lazy, single-use iterators | eager array methods |
| `any` / `all` | Short-circuit; `all([])` is `True` | `some` / `every` |
| Conversion | `int`, `float`, `chr`, `ord`, `hex` … | `parseInt`, `String` |
| Introspection | `type`, `isinstance`, `getattr` … | `typeof`, `Reflect` |
| `locals()` | Snapshot in functions (3.13) | none |
| `eval` / `exec` | Run arbitrary code: never on input | `eval`, `new Function` |
| `ast.literal_eval` | Safe parsing of literals | `JSON.parse` |
| Idioms | `enumerate`, `zip`, `in`, `get`, EAFP | none |

## Further reading

- [Built-in functions](https://docs.python.org/3/library/functions.html)
- [Iterator types](https://docs.python.org/3/library/stdtypes.html#iterator-types)
- [Glossary: iterable](https://docs.python.org/3/glossary.html#term-iterable)
  and [EAFP](https://docs.python.org/3/glossary.html#term-EAFP)
- [Tutorial: list comprehensions](https://docs.python.org/3/tutorial/datastructures.html#list-comprehensions)
- [Displays for lists, sets and dictionaries](https://docs.python.org/3/reference/expressions.html#displays-for-lists-sets-and-dictionaries)
- [`ast.literal_eval`](https://docs.python.org/3/library/ast.html#ast.literal_eval)
  and [`dis`](https://docs.python.org/3/library/dis.html)
- [PEP 234 — Iterators](https://peps.python.org/pep-0234/)
- [PEP 202 — List comprehensions](https://peps.python.org/pep-0202/)
- [PEP 274 — Dict comprehensions](https://peps.python.org/pep-0274/)
- [PEP 618 — Add optional length-checking to zip](https://peps.python.org/pep-0618/)
- [PEP 709 — Inlined comprehensions](https://peps.python.org/pep-0709/)
- [PEP 667 — Consistent views of namespaces](https://peps.python.org/pep-0667/)

[← Previous](unit-1-8-operators-expressions-and-control-flow.md) · [Index](README.md) · [Next →](unit-1-10-functions-definition-and-arguments.md)
