# Unit 1.13 — Iterators, Generators and itertools

[← Previous](unit-1-12-decorators-functools-and-the-call-stack.md) · [Index](README.md) · [Next →](unit-1-14-exceptions-and-context-managers.md)

Almost every loop in Python runs on one small protocol: ask an object for an
iterator, then ask the iterator for items until it says it is done. This unit
takes that protocol apart, shows how generator functions write iterators for you
by pausing a function mid-body, and follows the same machinery all the way to
`async` / `await`. It ends with the `itertools` module, the standard library's
toolbox of lazy building blocks.

## What you will learn

- Tell an **iterable** (gives fresh iterators) from an **iterator** (single
  use), and write both as classes.
- Write generator functions and generator expressions, and explain their lazy
  start, their four states, their suspended frames and their return values.
- Build lazy, pull-based pipelines that process data of any size in constant
  memory.
- Delegate with `yield from`, and drive two-way generators with `send`, `throw`
  and `close`.
- See how `async def` coroutines grew out of generators, by driving one by hand.
- Use every `itertools` building block, and know where the recipes live.

## JavaScript → Python bridge

If you know JavaScript's iteration protocol and `function*`, you already know
the shape of everything in this unit. The spelling, and a few rules, differ.

| JavaScript | Python | The difference that bites |
| --- | --- | --- |
| `[Symbol.iterator]()` | `__iter__()` | Also used by `list()`, unpacking, `in` |
| `it.next()` → `{value, done}` | `__next__()` | Returns the value; end is `StopIteration` |
| `function*` / `yield` | `def` with `yield` | Any `yield` makes it a generator |
| `yield*` | `yield from` | Forwards `send`/`throw`, returns a value |
| `gen.next(value)` | `gen.send(value)` | First call must send `None` (priming) |
| `gen.return()` | `gen.close()` | Raises `GeneratorExit` inside |
| `gen.throw(e)` | `gen.throw(e)` | Same idea |
| `async function` | `async def` | Built on generator machinery |
| Iterator helpers | `itertools` | Python has had them since 2.3 |

The examples below share a little setup: a `raised_error_name(thunk)` helper
that calls a zero-argument function and returns the name of the exception it
raised (or `"no error"`), plus the imports `datetime as dt`, `dis`, `inspect`,
`io`, `itertools`, `operator`, `sys`, `tracemalloc` and the
`collections.abc` types `Callable`, `Generator`, `Iterable` and `Iterator`.

```python
def raised_error_name(thunk: Callable[[], object]) -> str:
    """Call thunk and return the name of the exception it raised."""
    try:
        thunk()
    except Exception as error:
        return type(error).__name__
    return "no error"
```

## 1.13.1 Iterable vs iterator

Two roles take part in every `for` loop. An **iterable** is anything you can
loop over: it has an `__iter__()` method that returns an iterator. An
**iterator** is the object that actually walks through the data: its
`__next__()` method returns the next item, or raises `StopIteration` when there
is nothing left. Iterators also have an `__iter__()` that simply returns
`self`, so every iterator is also an iterable. That design is why you can write
`for x in map(...)` as easily as `for x in [...]`.

When CPython runs `for price in basket_prices:`, the compiler emits a
`GET_ITER` instruction (which calls `iter(basket_prices)`, i.e.
`type(basket_prices).__iter__(basket_prices)`) and then a `FOR_ITER`
instruction that calls `__next__` on each pass and jumps out of the loop when
`StopIteration` appears. Written out by hand, a `for` loop is this:

```python
basket_prices = [249, 640, 162]
price_iterator = iter(basket_prices)
while True:
    try:
        price = next(price_iterator)
    except StopIteration:
        break
    print(f"price={price}")
```

```text
price=249
price=640
price=162
```

The important difference between the two roles is **who holds the position**.
A list does not remember how far a loop got; each call to `iter()` on it
produces a brand-new `list_iterator` that starts at index 0. An iterator *is*
the position, so once it has been consumed it stays consumed.

| | Iterable | Iterator |
| --- | --- | --- |
| Method | `__iter__()` | `__next__()` and `__iter__()` |
| Examples | `list`, `str`, `dict`, `range` | files, generators, `map`, `zip` |
| Loop it twice | works: fresh iterator | second loop is **empty** |

```python
basket_prices = [249, 640, 162]
print(f"{iter(basket_prices) is iter(basket_prices)=}"
      "  (fresh iterator each time)")

with_gst = map(lambda price: round(price * 1.18), basket_prices)
print(f"{iter(with_gst) is with_gst=}  (an iterator returns itself)")
print(f"first pass:  {list(with_gst)}")
print(f"second pass: {list(with_gst)}  (already consumed)")
```

```text
iter(basket_prices) is iter(basket_prices)=False  (fresh iterator each time)
iter(with_gst) is with_gst=True  (an iterator returns itself)
first pass:  [294, 755, 191]
second pass: []  (already consumed)
```

The `collections.abc` module turns the protocol into checkable types:
`Iterable` requires `__iter__`, and `Iterator` requires both `__iter__` and
`__next__`. The bug pattern that this distinction causes in real code is a
function that loops over its argument twice. Given a list it works perfectly;
given a single-use iterator, the second loop silently sees nothing. No
exception is raised, which is what makes it dangerous.

```python
def price_report(prices: Iterable[int]) -> str:
    """Loops over prices twice: fine for iterables, wrong for iterators."""
    total = sum(prices)
    count = sum(1 for _ in prices)
    return f"total={total}, count={count}"


print(f"{isinstance(basket_prices, Iterable)=}, "
      f"{isinstance(basket_prices, Iterator)=}")
print(f"{isinstance(iter(basket_prices), Iterator)=}")
print(f"list:     {price_report(basket_prices)}")
print(f"iterator: {price_report(iter(basket_prices))}  (count is wrong)")
```

```text
isinstance(basket_prices, Iterable)=True,
isinstance(basket_prices, Iterator)=False
isinstance(iter(basket_prices), Iterator)=True
list:     total=1051, count=3
iterator: total=1051, count=0  (count is wrong)
```

> **Note:** the first output line is wrapped after the comma to fit the
> screen; it is one line in the real output.

> **Warning:** when a function needs two passes, either accept a `Sequence` /
> `list`, or call `list(prices)` once at the top. A cheap guard is
> `if iter(prices) is prices: prices = list(prices)`.

**The JavaScript comparison.** JavaScript's protocol is the same idea with
different spelling. An iterable has a `[Symbol.iterator]()` method that returns
an iterator, and the iterator's `next()` returns a result object:

```javascript
const prices = [249, 640];
const it = prices[Symbol.iterator]();
it.next();  // { value: 249, done: false }
it.next();  // { value: 640, done: false }
it.next();  // { value: undefined, done: true }
```

Python has no result object. `next()` returns the value directly and signals
the end with an exception, which `for` catches for you. Raising an exception
sounds expensive, but CPython's `FOR_ITER` checks for the "exhausted" case in C
without ever creating a `StopIteration` object for built-in iterators, so the
common path is fast. When you call `next()` yourself, `next(iterator, default)`
returns `default` instead of raising.

```python
price_iterator = iter([249, 640])
print(next(price_iterator), next(price_iterator))
print(f"{next(price_iterator, 'done')=}")
print("next() after the end: "
      f"{raised_error_name(lambda: next(price_iterator))}")
```

```text
249 640
next(price_iterator, 'done')='done'
next() after the end: StopIteration
```

### Key points

| Idea | Remember |
| --- | --- |
| Iterable | `__iter__` returns a new iterator |
| Iterator | `__next__` + `__iter__` returning `self` |
| Single use | `iter(it) is it`; second loop is empty |
| End signal | `StopIteration`, not `{done: true}` |
| Safe `next` | `next(it, default)` |

## 1.13.2 Custom iterator classes

To make your own class loopable, you implement the protocol yourself. The
clean design mirrors the built-ins: **separate the iterable from its
iterator**. The container (here `DeliveryWindow`) stores the data and returns a
**new** iterator object from every `__iter__` call. The iterator
(`DeliveryWindowIterator`) holds the position and does the stepping. Because
each loop gets its own iterator, any number of loops, even nested ones, run
independently over the same container.

This is exactly how `list` and `list_iterator` are split in CPython, and how
`Array` and `ArrayIterator` are split in JavaScript.

```python
class DeliveryWindowIterator:
    """Iterator over the days of a DeliveryWindow; holds the position."""

    def __init__(self, first_day: dt.date, day_count: int) -> None:
        self.next_day = first_day
        self.days_left = day_count

    def __iter__(self) -> DeliveryWindowIterator:
        return self

    def __next__(self) -> dt.date:
        if self.days_left == 0:
            raise StopIteration
        current_day = self.next_day
        self.next_day += dt.timedelta(days=1)
        self.days_left -= 1
        return current_day


class DeliveryWindow:
    """Iterable: a range of delivery dates; every loop gets a new iterator."""

    def __init__(self, first_day: dt.date, day_count: int) -> None:
        self.first_day = first_day
        self.day_count = day_count

    def __iter__(self) -> DeliveryWindowIterator:
        return DeliveryWindowIterator(self.first_day, self.day_count)
```

The nested loop below pairs every day with every day (3 × 3 = 9 pairs) because
the inner and outer loops each received their own iterator.

```python
festival_window = DeliveryWindow(dt.date(2026, 11, 7), 3)
print([day.isoformat() for day in festival_window])
print([day.isoformat() for day in festival_window])  # works again
pairs = [
    (first.day, second.day)
    for first in festival_window
    for second in festival_window
]
print(f"{len(pairs)=}")
```

```text
['2026-11-07', '2026-11-08', '2026-11-09']
['2026-11-07', '2026-11-08', '2026-11-09']
len(pairs)=9
```

**The shortcut that breaks.** Making the container its own iterator (its
`__iter__` returns `self`) looks simpler, because there is only one class. But
now the position lives on the container, and every loop shares it. In the
nested loop below, the inner loop consumes days 2 and 3 during the outer loop's
first pass. The outer loop then finds nothing left, so the result has 2 pairs
instead of 9, and any later loop is empty.

```python
class OneShotWindow:
    """Bug: the container is its own iterator."""

    def __init__(self, first_day: dt.date, day_count: int) -> None:
        self.next_day = first_day
        self.days_left = day_count

    def __iter__(self) -> OneShotWindow:
        return self

    def __next__(self) -> dt.date:
        if self.days_left == 0:
            raise StopIteration
        self.days_left -= 1
        self.next_day += dt.timedelta(days=1)
        return self.next_day - dt.timedelta(days=1)


one_shot = OneShotWindow(dt.date(2026, 11, 7), 3)
nested_pairs = [
    (first.day, second.day) for first in one_shot for second in one_shot
]
print(f"{len(nested_pairs)=}, {list(one_shot)=}")
```

```text
len(nested_pairs)=2, list(one_shot)=[]
```

> **Warning:** a class whose `__iter__` returns `self` is an *iterator*, not a
> re-usable collection. Only do this when single use is the intended behaviour
> (as with files and network streams).

**The `__getitem__` sequence fallback.** Before the iterator protocol existed
(it arrived in Python 2.2 with PEP 234), `for` worked on anything that had
`__getitem__`: Python called it with 0, 1, 2, … until it raised `IndexError`.
`iter()` still honours that old contract. When a class has no `__iter__` but
does have `__getitem__`, `iter()` wraps the object in a generic C-level
`iterator` that does the index counting for you. The `in` operator falls back
the same way.

The catch: `isinstance(obj, Iterable)` returns **False** for such a class,
because the ABC only checks for an `__iter__` method. The only reliable test
for "can I loop over this?" is to call `iter(obj)` and see whether it raises
`TypeError`.

```python
class SeatRow:
    """Old-style sequence: only __getitem__, no __iter__."""

    def __init__(self, seat_count: int) -> None:
        self.seat_count = seat_count

    def __getitem__(self, index: int) -> str:
        if index >= self.seat_count:
            raise IndexError(index)
        return f"A{index + 1}"


front_row = SeatRow(4)
print(f"{list(front_row)=}, {'A3' in front_row=}")
print(f"{type(iter(front_row)).__name__=}")
print(f"{isinstance(front_row, Iterable)=}  (the ABC misses the fallback)")
```

```text
list(front_row)=['A1', 'A2', 'A3', 'A4'], 'A3' in front_row=True
type(iter(front_row)).__name__='iterator'
isinstance(front_row, Iterable)=False  (the ABC misses the fallback)
```

JavaScript has no equivalent fallback: an object with numeric keys and a
`length` is "array-like" for `Array.from`, but `for...of` refuses it unless it
has `Symbol.iterator`.

### Key points

| Idea | Remember |
| --- | --- |
| Clean design | Container returns a **new** iterator |
| Iterator class | Holds the position, `__iter__` returns `self` |
| Shortcut bug | Container as its own iterator: shared state |
| Legacy fallback | `__getitem__` from 0 until `IndexError` |
| Reliable test | Call `iter(obj)`, not `isinstance` |

## 1.13.3 Generator functions

Writing iterator classes by hand is tedious: you have to store every piece of
loop state as an attribute and rebuild the control flow inside `__next__`. A
**generator function** does all of that for you. Any `def` whose body contains
`yield` is a generator function. Calling it does **not** run the body; it
returns a generator object, which is an iterator. Each `next()` runs the body
until the next `yield`, hands out the yielded value, and **suspends** the
function with all its local variables intact. When the body ends, the
generator raises `StopIteration`.

This is the same model as JavaScript's `function*`, with one difference in
syntax: Python has no special marker on the `def` line. The presence of `yield`
anywhere in the body, even in a branch that never runs, changes what the
function is.

```python
def order_statuses() -> Iterator[str]:
    """Yield the stages of an order, printing as the body runs."""
    print("  body starts")
    yield "placed"
    print("  resumed after 'placed'")
    yield "packed"
    print("  resumed after 'packed'")
    yield "shipped"
    print("  body ends")


status_generator = order_statuses()
print(f"{type(status_generator).__name__=}"
      "  (nothing printed yet: lazy start)")
print(f"{next(status_generator)=}")
print(f"{next(status_generator)=}")
print(f"rest: {list(status_generator)}")
```

```text
type(status_generator).__name__='generator'  (nothing printed yet: lazy start)
  body starts
next(status_generator)='placed'
  resumed after 'placed'
next(status_generator)='packed'
  resumed after 'packed'
  body ends
rest: ['shipped']
```

Notice the **lazy start**: creating the generator printed nothing. "body
starts" only appears on the first `next()`. This matters for error handling: a
generator that opens a file or validates its arguments does so on the first
`next()`, not when you call the function.

> **Warning:** validation code at the top of a generator function runs late.
> If you need an immediate `ValueError` for bad arguments, write a plain
> function that checks them and then returns an inner generator.

### Generator states

`inspect.getgeneratorstate(gen)` reports one of four states. `GEN_RUNNING` can
only be observed from inside the generator itself, so the example's generator
inspects itself through a global name.

| State | Meaning |
| --- | --- |
| `GEN_CREATED` | created, body not started |
| `GEN_RUNNING` | currently executing |
| `GEN_SUSPENDED` | paused at a `yield` |
| `GEN_CLOSED` | finished (returned, raised, or closed) |

```python
def self_reporting() -> Iterator[str]:
    """Yield its own state while running."""
    yield inspect.getgeneratorstate(watched_generator)


watched_generator = self_reporting()
states = [inspect.getgeneratorstate(watched_generator)]
states.append(next(watched_generator))
states.append(inspect.getgeneratorstate(watched_generator))
states.append(raised_error_name(lambda: next(watched_generator)))
states.append(inspect.getgeneratorstate(watched_generator))
print(states)
```

```text
['GEN_CREATED', 'GEN_RUNNING', 'GEN_SUSPENDED', 'StopIteration', 'GEN_CLOSED']
```

### Under the hood: suspended frames

An ordinary function call creates a **frame** (the record holding its local
variables and current instruction) and throws it away on return. A generator
instead **owns** its frame, exposed as `gi_frame`. While the generator is
suspended, the frame keeps the current line and all the locals; that is all
"pausing" means. Resuming simply continues executing that frame from where it
stopped. `gi_suspended` (*New in 3.11*) says whether it is paused at a
`yield`. When the generator finishes, the frame is released and `gi_frame`
becomes `None`.

```python
def running_totals(amounts: list[int]) -> Iterator[int]:
    """Yield the running total after each amount."""
    total = 0
    for amount in amounts:
        total += amount
        yield total


totals = running_totals([249, 640, 162])
next(totals)
next(totals)
frame = totals.gi_frame
print(f"{totals.gi_suspended=}, {frame.f_locals['total']=}, "
      f"{frame.f_locals['amount']=}")
print(f"{frame.f_lineno - totals.gi_code.co_firstlineno=}"
      " (line offset of the yield)")
print(f"{list(totals)=}, {totals.gi_frame=}")
```

```text
totals.gi_suspended=True, frame.f_locals['total']=889,
frame.f_locals['amount']=640
frame.f_lineno - totals.gi_code.co_firstlineno=5 (line offset of the yield)
list(totals)=[1051], totals.gi_frame=None
```

> **Note:** the first output line is wrapped after the comma to fit the screen.

The compiler decides, at compile time, that a function is a generator
function and marks its code object with the `CO_GENERATOR` flag. Its bytecode
starts with `RETURN_GENERATOR`, which builds the generator object (and its
frame) instead of running the body, and it pauses at `YIELD_VALUE`. Opcode
names vary between Python versions.

```python
flags = running_totals.__code__.co_flags
print(f"{bool(flags & inspect.CO_GENERATOR)=}")
print(f"{inspect.isgeneratorfunction(running_totals)=}, "
      f"{inspect.isgenerator(totals)=}")
opnames = [
    instruction.opname
    for instruction in dis.get_instructions(running_totals)
]
print(f"{opnames[0]=}, {'YIELD_VALUE' in opnames=}")
```

```text
bool(flags & inspect.CO_GENERATOR)=True
inspect.isgeneratorfunction(running_totals)=True,
inspect.isgenerator(totals)=True
opnames[0]='RETURN_GENERATOR', 'YIELD_VALUE' in opnames=True
```

> **Note:** the notebook prints the flag test as
> `bool(running_totals.__code__.co_flags & inspect.CO_GENERATOR)=True`; it was
> shortened here through a `flags` variable. The second line is wrapped.

### `return` in a generator

A generator may also contain `return value`. That ends the generator, and the
value travels out as the `value` attribute of the `StopIteration` exception. A
`for` loop discards it, but code that calls `next()` itself, and `yield from`
(section 1.13.6), can read it. In JavaScript the same value would appear as
`{ value: 111, done: true }`.

```python
def take_until_budget(
    prices: list[int], budget: int
) -> Generator[int, None, int]:
    """Yield prices while they fit the budget; return the money left."""
    for price in prices:
        if price > budget:
            break
        budget -= price
        yield price
    return budget


shopper = take_until_budget([249, 640, 162], budget=1000)
bought = [next(shopper), next(shopper)]
try:
    next(shopper)
except StopIteration as stop:
    print(f"{bought=}, money left: {stop.value}")
```

```text
bought=[249, 640], money left: 111
```

> **Note:** the type hint `Generator[YieldType, SendType, ReturnType]`
> describes all three channels. `Iterator[int]` is enough when only `yield` is
> used. `SendType` and `ReturnType` default to `None` (*New in 3.13*, PEP 696),
> so `Generator[str, int]` means "yields `str`, receives `int`, returns
> nothing".

One more rule protects you here. Since Python 3.7 (PEP 479), a `StopIteration`
that escapes from *inside* a generator body, for example from a bare `next()`
call on an empty iterator, is converted to `RuntimeError`. Without that rule,
the stray exception would look like a normal end of iteration and silently
truncate the caller's loop.

```python
def broken_first_item(rows):
    """Bug: next() on an empty iterator inside a generator."""
    first_row = next(iter(rows))
    yield first_row


try:
    list(broken_first_item([]))
except RuntimeError as error:
    print(f"{type(error).__name__}: {error}")
    print(f"cause: {type(error.__cause__).__name__}")
```

```text
RuntimeError: generator raised StopIteration
cause: StopIteration
```

> **Warning:** inside a generator, use `next(iterator, default)` or catch
> `StopIteration` and `return`, never let it escape.

### Key points

| Idea | Remember |
| --- | --- |
| Generator function | Any `def` containing `yield` |
| Lazy start | Body runs on the first `next()` |
| States | CREATED → RUNNING ⇄ SUSPENDED → CLOSED |
| Suspension | The frame (`gi_frame`) is kept alive |
| `return value` | Arrives as `StopIteration.value` |
| PEP 479 | Escaping `StopIteration` → `RuntimeError` |

## 1.13.4 Generator expressions

A **generator expression** is a comprehension written in parentheses:
`(expr for x in iterable if condition)`. Where a list comprehension builds the
whole list immediately, a generator expression builds a generator that
computes each item only when asked. When it is the only argument of a call, the
extra parentheses can be dropped, which gives the idiomatic
`sum(price * 2 for price in prices)`.

Under the hood a generator expression is compiled into a tiny anonymous
generator function, called immediately with the first iterable as its
argument. JavaScript has no direct equivalent: the closest is an inline
`function*` or the ES2025 iterator helpers (`iter.map(...).filter(...)`).

```python
basket_prices = [249, 640, 162, 980]
doubled_lazily = (price * 2 for price in basket_prices if price < 900)
print(f"{type(doubled_lazily).__name__=}")
print(f"{sum(price * 2 for price in basket_prices)=}")
print(f"{max(len(sku) for sku in ['TEA-500G', 'RICE-5KG', 'SOAP'])=}")
```

```text
type(doubled_lazily).__name__='generator'
sum(price * 2 for price in basket_prices)=4062
max(len(sku) for sku in ['TEA-500G', 'RICE-5KG', 'SOAP'])=8
```

Because a generator expression produces a generator, it is an iterator, and it
is **single use**, exactly like the `map` object in section 1.13.1.

**Predict the output.**

```python
expensive = (price for price in [249, 640, 980] if price > 500)
print(list(expensive))
print(list(expensive))
print(980 in expensive)
```

<details><summary>Answer</summary>

```text
[640, 980]
[]
False
```

A generator expression is an iterator: the first `list()` consumes it, so the
second sees nothing, and `in` searches what is left (nothing). Note that `in`
on an iterator *consumes* items as it searches, so even a successful `in` test
leaves the iterator partly used up.

</details>

**Which parts are lazy?** One subtle rule: the **first** `in` iterable is
evaluated immediately, when the expression is created, because it is passed as
the argument to the hidden generator function. Everything else (the
expression, the `if` filters, any later `for` clauses) is lazy. So a bad name
in the first `for` fails at once, while an error in the expression part waits
until that item is pulled.

```python
first_iterable_error = raised_error_name(
    lambda: (x for x in missing_prices)  # noqa: F821
)
print(f"bad first iterable: {first_iterable_error}")
lazy_division = (1000 // quantity for quantity in [4, 0, 2])
print(f"created fine; first item: {next(lazy_division)}")
print(f"second item: {raised_error_name(lambda: next(lazy_division))}")
```

```text
bad first iterable: NameError
created fine; first item: 250
second item: ZeroDivisionError
```

**Memory.** A list comprehension materializes every element, so its memory
grows with the input. A generator expression holds only its frame, whatever
the input size. `sys.getsizeof` shows the size of the two container objects;
`tracemalloc` shows the **peak** memory of summing a million squares each way,
including the int objects themselves. Exact numbers vary by Python version and
platform.

```python
def peak_bytes(thunk: Callable[[], object]) -> int:
    """Return the peak traced memory while running thunk."""
    tracemalloc.start()
    try:
        thunk()
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


squares_list = [number * number for number in range(1_000_000)]
squares_generator = (number * number for number in range(1_000_000))
print(f"list object: {sys.getsizeof(squares_list):,} bytes")
print(f"generator object: {sys.getsizeof(squares_generator)} bytes")
del squares_list
list_peak = peak_bytes(
    lambda: sum([number * number for number in range(1_000_000)])
)
generator_peak = peak_bytes(
    lambda: sum(number * number for number in range(1_000_000))
)
print(f"peak with list: {list_peak / 1e6:.1f} MB, "
      f"with generator: {generator_peak / 1e3:.1f} kB")
```

```text
list object: 8,448,728 bytes
generator object: 216 bytes
peak with list: 40.4 MB, with generator: 0.4 kB
```

The list object alone is about 8 MB (one 8-byte pointer per element), and the
million int objects it points to bring the peak to about 40 MB. The generator
never holds more than one square at a time.

| Use | When |
| --- | --- |
| List comprehension | Need results twice, `len()`, indexing, sorting |
| Generator expression | Consume once (`sum`, `any`, `join`, a loop) |
| Generator expression | Input is large or infinite |

### Key points

| Idea | Remember |
| --- | --- |
| Syntax | `(expr for x in data if cond)` |
| Sole argument | `sum(x * 2 for x in data)` |
| Single use | It is a generator, so an iterator |
| Eager part | Only the first `in` iterable |
| Memory | Constant, versus O(n) for a list |

## 1.13.5 Lazy pipelines

Generators compose. If each stage of a data-processing job is a generator that
consumes the previous stage, you get a **pipeline**: read → parse → filter →
aggregate. Nothing happens when you build it. Only when the last stage asks
for a value does the request travel up the chain, and then **one item at a
time** flows down through every stage before the next item is read. The model
is **pull-based**: the consumer drives, and each stage does just enough work to
answer one `next()` call.

Two properties fall out of this. Memory stays constant whatever the input
size, because no stage ever holds more than the item it is working on. And
work stops as soon as the consumer stops: if nobody asks for the next item, no
more input is read. This is the same idea as Unix pipes (`cat | grep | wc`) or
Node.js streams, but with no buffering and no events: plain function calls.

```text
  +---------------+
  |     sum()     |  aggregate (the consumer)
  +---------------+
      |        ^
   next()      |  one matching Sale
      v        |
  +---------------+
  |  only_city()  |  filter
  +---------------+
      |        ^
   next()      |  one Sale
      v        |
  +---------------+
  | parse_sales() |  parse
  +---------------+
      |        ^
   next()      |  one line
      v        |
  +---------------+
  | read_lines()  |  read (file or StringIO)
  +---------------+

  One item travels the whole chain before the next line is read.
```

The stages below print as they work, so the trace shows the interleaving.
`Sale` is a `typing.NamedTuple`, a lightweight immutable record.

```python
class Sale(NamedTuple):
    city: str
    sku: str
    amount: int


def read_lines(stream: io.TextIOBase) -> Iterator[str]:
    """Stage 1: yield non-empty lines."""
    for line in stream:
        if line.strip():
            print(f"    read  {line.strip()!r}")
            yield line


def parse_sales(lines: Iterable[str]) -> Iterator[Sale]:
    """Stage 2: turn 'city,sku,amount' lines into Sale records."""
    for line in lines:
        city, sku, amount = line.strip().split(",")
        yield Sale(city, sku, int(amount))


def only_city(sales: Iterable[Sale], city: str) -> Iterator[Sale]:
    """Stage 3: keep one city's sales."""
    for sale in sales:
        if sale.city == city:
            print(f"    keep  {sale.sku} {sale.amount}")
            yield sale
```

Stage 4 is `sum`. Building the pipeline prints nothing; `sum` then pulls each
line through every stage before the next line is read. Look at the trace: the
Delhi line is read and then dropped by the filter before the second Pune line
is even looked at.

```python
sales_csv = (
    "Pune,TEA-500G,249\nDelhi,RICE-5KG,640\n\n"
    "Pune,SOAP-3PK,162\nGoa,TEA-500G,249\n"
)
pune_sales = only_city(
    parse_sales(read_lines(io.StringIO(sales_csv))), "Pune"
)
print("pipeline built, nothing read yet")
pune_total = sum(sale.amount for sale in pune_sales)
print(f"{pune_total=}")
```

```text
pipeline built, nothing read yet
    read  'Pune,TEA-500G,249'
    keep  TEA-500G 249
    read  'Delhi,RICE-5KG,640'
    read  'Pune,SOAP-3PK,162'
    keep  SOAP-3PK 162
    read  'Goa,TEA-500G,249'
pune_total=411
```

**Early termination.** Asking only for the first Pune sale reads **one** line;
the rest of the input is never touched. With a 10 GB log file, that is the
difference between milliseconds and minutes.

```python
first_pune_sale = next(
    only_city(parse_sales(read_lines(io.StringIO(sales_csv))), "Pune")
)
print(f"{first_pune_sale=}")
```

```text
    read  'Pune,TEA-500G,249'
    keep  TEA-500G 249
first_pune_sale=Sale(city='Pune', sku='TEA-500G', amount=249)
```

> **Note:** a file object is itself a lazy iterator of lines, so
> `for line in open(path)` never loads the whole file. Pipelines built on it
> handle files far larger than RAM.

> **Warning:** one eager stage breaks the laziness of the whole pipeline. A
> `sorted()`, `list()` or `len()` in the middle forces every item upstream to
> be read first.

### Key points

| Idea | Remember |
| --- | --- |
| Pipeline | Each stage consumes the previous one |
| Pull-based | The final consumer drives every stage |
| Memory | One item in flight, constant memory |
| Early stop | Unrequested input is never read |
| Pitfall | One eager stage loads everything |

## 1.13.6 `yield from`

`yield from sub_iterable` hands control to another iterable until it is
exhausted: every item it produces is yielded straight to our caller. For plain
iteration it is the same as `for item in sub_iterable: yield item`, just
shorter. It is the Python spelling of JavaScript's `yield*`. It does more than
the loop for two-way generators (section 1.13.7): it forwards `send()`,
`throw()` and `close()` to the sub-generator, and it evaluates to the
sub-generator's return value.

```python
def warehouse_skus() -> Iterator[str]:
    yield from ["TEA-500G", "RICE-5KG"]


def store_skus() -> Iterator[str]:
    yield from ("SOAP-3PK", "TEA-500G")


def all_skus() -> Iterator[str]:
    """Delegate to two sub-generators in turn."""
    yield from warehouse_skus()
    yield from store_skus()


print(list(all_skus()))
```

```text
['TEA-500G', 'RICE-5KG', 'SOAP-3PK', 'TEA-500G']
```

**Recursive tree walks.** Recursion and generators fit together naturally. A
recursive generator yields its own item and delegates each subtree to a
recursive call with `yield from`. The category tree below is nested dicts; the
walk yields every path, depth first, and it is lazy: a consumer that stops
early never visits the remaining branches.

```python
category_tree: dict[str, dict[str, Any]] = {
    "Grocery": {"Tea": {}, "Rice": {"Basmati": {}, "Sona Masoori": {}}},
    "Home": {"Cleaning": {"Soap": {}}},
}


def category_paths(tree: dict[str, Any], prefix: str = "") -> Iterator[str]:
    """Yield 'A/B/C' paths for every node of a nested-dict tree."""
    for name, subtree in tree.items():
        path = f"{prefix}/{name}" if prefix else name
        yield path
        yield from category_paths(subtree, path)


for path in category_paths(category_tree):
    print(f"  {path}")
```

```text
  Grocery
  Grocery/Tea
  Grocery/Rice
  Grocery/Rice/Basmati
  Grocery/Rice/Sona Masoori
  Home
  Home/Cleaning
  Home/Cleaning/Soap
```

> **Note:** each level of recursion is one more suspended generator frame, so
> very deep trees hit the recursion limit (about 1000) just like ordinary
> recursion. For deep data, use an explicit stack.

**Capturing return values.** `result = yield from sub_generator()` evaluates
to the sub-generator's `return` value (its `StopIteration.value`). This lets a
sub-generator produce items **and** report a summary at the end. Below, each
section of an inventory yields its items and returns how many it had; the outer
generator collects those counts and returns them in turn.

```python
def section_items(
    section_name: str, items: list[str]
) -> Generator[str, None, int]:
    """Yield 'section: item' strings; return the item count."""
    for item in items:
        yield f"{section_name}: {item}"
    return len(items)


def inventory(
    sections: dict[str, list[str]],
) -> Generator[str, None, dict[str, int]]:
    """Yield every item; return the count per section."""
    counts = {}
    for section_name, items in sections.items():
        counts[section_name] = yield from section_items(section_name, items)
    return counts


inventory_walk = inventory({"Shelf A": ["tea", "rice"], "Shelf B": ["soap"]})
print(list(itertools.islice(inventory_walk, 10)))
print(f"{inspect.getgeneratorstate(inventory_walk)=}")


def collect_return(generator: Generator[Any, None, Any]) -> Any:
    """Exhaust a generator and return its return value."""
    while True:
        try:
            next(generator)
        except StopIteration as stop:
            return stop.value


shelves = {"Shelf A": ["tea", "rice"], "Shelf B": ["soap"]}
print(f"{collect_return(inventory(shelves))=}")
```

```text
['Shelf A: tea', 'Shelf A: rice', 'Shelf B: soap']
inspect.getgeneratorstate(inventory_walk)='GEN_CLOSED'
collect_return(inventory(shelves))={'Shelf A': 2, 'Shelf B': 1}
```

> **Note:** the notebook passes the dict literal directly to `inventory()` in
> the last line; here it goes through a `shelves` variable to keep the line
> short, so the printed expression text is shorter. The value is the same.

### Key points

| Idea | Remember |
| --- | --- |
| Delegation | `yield from it` ≈ `for x in it: yield x` |
| JS equivalent | `yield*` |
| Recursion | Yield self, `yield from` the children |
| Return value | `r = yield from sub()` gets its `return` |
| Two-way | Also forwards `send`, `throw`, `close` |

## 1.13.7 Two-way generators

So far data has flowed one way: out of the generator. But `yield` is also an
**expression**. In `received = yield value`, the generator hands out `value`
and pauses; when it is resumed with `gen.send(something)`, the `yield`
expression evaluates to `something`, which lands in `received`. Plain
`next(gen)` is the same as `gen.send(None)`. A generator used this way is
often called a **coroutine** in the older, pre-`async` sense: a function that
can be paused, fed data, and resumed.

| Method | Effect at the paused `yield` |
| --- | --- |
| `gen.send(value)` | `yield` evaluates to `value`; runs to the next one |
| `gen.throw(exception)` | The exception is raised at the `yield` |
| `gen.close()` | `GeneratorExit` is raised at the `yield` |

Every one of these returns the value of the **next** `yield` (or raises
`StopIteration` if the generator ends instead).

**Priming.** A new generator has not reached a `yield` yet, so there is no
paused `yield` expression to receive a value. The first call must therefore be
`next(gen)` or `gen.send(None)`; sending anything else raises `TypeError`.
JavaScript has the same rule, but silently: the argument of the first
`gen.next(value)` is just thrown away.

```python
def duplicate_detector() -> Generator[bool | None, str]:
    """Receive order ids; answer True if the id was seen before."""
    seen_ids: set[str] = set()
    answer: bool | None = None
    while True:
        order_id = yield answer
        answer = order_id in seen_ids
        seen_ids.add(order_id)


detector = duplicate_detector()
print(f"priming: {next(detector)=}")
print([
    detector.send(order_id)
    for order_id in ["A-1", "A-2", "A-1", "A-3", "A-2"]
])
unprimed = duplicate_detector()
try:
    unprimed.send("A-1")
except TypeError as error:
    print(f"{type(error).__name__}: {error}")
```

```text
priming: next(detector)=None
[False, False, True, False, True]
TypeError: can't send non-None value to a just-started generator
```

Forgetting to prime is so common that coroutine-style generators were often
wrapped in a small decorator (Unit 1.12) that creates the generator and calls
`next()` once. The `[**P]` syntax makes the decorator keep the wrapped
function's parameter types.

```python
def primed[**P](
    generator_function: Callable[P, Generator[Any, Any, Any]],
) -> Callable[P, Generator[Any, Any, Any]]:
    """Decorator: create the generator and advance it to the first yield."""

    def start(*args: P.args, **kwargs: P.kwargs) -> Generator[Any, Any, Any]:
        generator = generator_function(*args, **kwargs)
        next(generator)
        return generator

    return start


ready_detector = primed(duplicate_detector)()
print([ready_detector.send(order_id) for order_id in ["B-7", "B-7"]])
```

```text
[False, True]
```

**`throw`** raises an exception at the paused `yield`, as though the `yield`
line itself had raised it. The generator may handle it and continue (the value
of its next `yield` is what `throw` returns), or let it propagate out to the
caller of `throw`.

```python
def resilient_reader(lines: list[str]) -> Iterator[str]:
    """Yield lines; on a ValueError from the caller, report and carry on."""
    for line in lines:
        try:
            yield line
        except ValueError as error:
            yield f"skipped after error: {error}"


reader = resilient_reader(["line 1", "line 2", "line 3"])
print(next(reader))
print(reader.throw(ValueError("bad checksum")))
print(next(reader), next(reader))
```

```text
line 1
skipped after error: bad checksum
line 2 line 3
```

**`close` and cleanup.** `close()` raises `GeneratorExit` at the paused
`yield`. `GeneratorExit` derives from `BaseException`, not `Exception`, so an
ordinary `except Exception:` inside the generator does not swallow it. Put
cleanup in a `finally` block: it runs whether the generator finishes, fails,
is closed explicitly, or is garbage-collected half-way. CPython calls
`close()` automatically when a suspended generator's reference count drops to
zero, which is why breaking out of a `for` loop still runs the cleanup below.

```python
def database_rows(table: str) -> Iterator[str]:
    """Pretend to stream rows from a connection; always release it."""
    print(f"  open connection for {table}")
    try:
        for row_number in itertools.count(1):
            yield f"{table} row {row_number}"
    finally:
        print(f"  close connection for {table}")


rows = database_rows("orders")
print(next(rows), "|", next(rows))
rows.close()
print(f"{inspect.getgeneratorstate(rows)=}, "
      f"{issubclass(GeneratorExit, Exception)=}")
for row in database_rows("customers"):  # noqa: B007
    break  # leaving the loop drops the generator; finally runs on collection
```

```text
  open connection for orders
orders row 1 | orders row 2
  close connection for orders
inspect.getgeneratorstate(rows)='GEN_CLOSED',
issubclass(GeneratorExit, Exception)=False
  open connection for customers
  close connection for customers
```

> **Note:** the fourth output line is wrapped after the comma to fit the
> screen.

> **Warning:** relying on garbage collection for cleanup is a CPython
> convenience. On other implementations (PyPy), or when the generator is still
> referenced somewhere, the `finally` may run much later. For resources that
> must be released promptly, call `close()` or use `contextlib.closing`
> (Unit 1.14).

A generator that **yields** again in response to `GeneratorExit` breaks the
contract: `close()` expects the generator to finish. CPython reports it as a
`RuntimeError`.

```python
def refuses_to_stop() -> Iterator[int]:
    """Bug: yields again after GeneratorExit."""
    try:
        yield 1
    except GeneratorExit:
        yield 2


stubborn = refuses_to_stop()
next(stubborn)
try:
    stubborn.close()
except RuntimeError as error:
    print(f"{type(error).__name__}: {error}")
```

```text
RuntimeError: generator ignored GeneratorExit
```

### Key points

| Idea | Remember |
| --- | --- |
| `x = yield v` | Out goes `v`; `send(y)` makes `x == y` |
| Priming | First call is `next()` / `send(None)` |
| `throw(e)` | Raises `e` at the paused `yield` |
| `close()` | Raises `GeneratorExit` (a `BaseException`) |
| Cleanup | `try` / `finally` around the yields |
| Bug | Yielding after `GeneratorExit` |

## 1.13.8 From generators to async

`async` / `await` did not appear from nowhere. Each PEP below added one
capability to generators, and the last one gave coroutines their own syntax
and type. Knowing the lineage explains why asyncio code behaves as it does.

| PEP | Python | Added |
| --- | --- | --- |
| 255 | 2.2 | `yield`: simple generators |
| 342 | 2.5 | `send`, `throw`, `close`; `yield` expression |
| 380 | 3.3 | `yield from` |
| 492 | 3.5 | `async def`, `await`, `__await__` |
| 525 | 3.6 | async generators |

Why each step mattered:

- **PEP 255** gave functions that pause and resume.
- **PEP 342** turned generators into **coroutines**: a scheduler could now
  resume them *with results* (`send`) or errors (`throw`).
- **PEP 380** let one coroutine call another and get its return value. asyncio
  (3.4) was first built on `yield from`.
- **PEP 492** added native coroutines, a distinct type that cannot be confused
  with a generator, and the `await` keyword.
- **PEP 525** allowed `yield` inside `async def`, giving async generators
  (`async for`).

A coroutine is driven exactly like a two-way generator. `coroutine.send(value)`
runs it until something deep inside an `await` chain **yields**, and the
yielded value pops out of `send`. When the coroutine finishes,
`StopIteration.value` carries its result. In CPython, `await x` compiles to
essentially the same bytecode loop as `yield from x.__await__()`. The event
loop (Phase 5) is "just" the code that calls `send` and decides when.

JavaScript hides this: an `async function` returns a Promise and the engine
drives it. Python exposes the machinery, which is why you can drive a
coroutine yourself.

The example defines an awaitable, `Delay`. Its `__await__` method is a
generator: it yields a request ("please sleep this long") to whoever drives
the coroutine, and receives a reply.

```python
class Delay:
    """Awaitable: ask the driver to wait, receive its reply."""

    def __init__(self, seconds: float) -> None:
        self.seconds = seconds

    def __await__(self) -> Generator[tuple[str, float], str, str]:
        # the yielded tuple goes out through coroutine.send()
        reply = yield ("sleep", self.seconds)
        return reply


async def fetch_order(order_id: int) -> dict[str, Any]:
    """A native coroutine that awaits twice."""
    first_reply = await Delay(0.5)
    second_reply = await Delay(0.2)
    return {"order_id": order_id, "replies": [first_reply, second_reply]}
```

Now drive it by hand. Calling `fetch_order(42)` creates a coroutine object
without running it (lazy start, like a generator); each `send` runs it to the
next yielded request.

```python
order_coroutine = fetch_order(42)
print(f"{inspect.getcoroutinestate(order_coroutine)=}")
first_request = order_coroutine.send(None)
print(f"{first_request=}, "
      f"{inspect.getcoroutinestate(order_coroutine)=}")
second_request = order_coroutine.send("woke after 0.5 s")
print(f"{second_request=}")
try:
    order_coroutine.send("woke after 0.2 s")
except StopIteration as stop:
    print(f"result: {stop.value}")
```

```text
inspect.getcoroutinestate(order_coroutine)='CORO_CREATED'
first_request=('sleep', 0.5),
inspect.getcoroutinestate(order_coroutine)='CORO_SUSPENDED'
second_request=('sleep', 0.2)
result: {'order_id': 42, 'replies': ['woke after 0.5 s', 'woke after 0.2 s']}
```

> **Note:** the second and third output lines are one line in the real output,
> wrapped after the comma here.

**A minimal event loop** is a loop around `send`. This one runs several
coroutines on a virtual clock: it always resumes the coroutine whose wake-up
time is earliest. The two orders interleave, and both finish at t=0.7 s
instead of 1.4 s, because they waited concurrently. Real asyncio does the same
thing with sockets and timers instead of a virtual clock (Phase 5).

```python
def run_all(coroutines: list[Any]) -> list[Any]:
    """Run coroutines that await Delay, interleaving them on a virtual clock."""
    ready = [
        (0.0, index, coroutine, None)
        for index, coroutine in enumerate(coroutines)
    ]
    results: list[Any] = [None] * len(coroutines)
    while ready:
        ready.sort(key=lambda entry: entry[0])
        now, index, coroutine, reply = ready.pop(0)
        try:
            _, seconds = coroutine.send(reply)
        except StopIteration as stop:
            results[index] = stop.value
            print(f"  t={now:.1f}s order {stop.value['order_id']} done")
            continue
        wake_time = now + seconds
        ready.append(
            (wake_time, index, coroutine, f"woke at {wake_time:.1f}s")
        )
    return results


finished = run_all([fetch_order(1), fetch_order(2)])
print(finished[1])
```

```text
  t=0.7s order 1 done
  t=0.7s order 2 done
{'order_id': 2, 'replies': ['woke at 0.5s', 'woke at 0.7s']}
```

> **Note:** the last lines of `run_all` introduce a `wake_time` variable to
> keep lines short; the notebook computes `now + seconds` inline. The
> behaviour is identical.

### Key points

| Idea | Remember |
| --- | --- |
| Lineage | PEP 255 → 342 → 380 → 492 → 525 |
| Coroutine | Created lazily, driven with `send` |
| `await` | ≈ `yield from x.__await__()` |
| Result | Arrives as `StopIteration.value` |
| Event loop | A loop that calls `send` and schedules |

## 1.13.9 The `itertools` module

`itertools` is a standard-library module of fast, memory-efficient building
blocks, all written in C, that take iterables and return **iterators**. They
are lazy, so they compose into pipelines exactly like the generators of
section 1.13.5, and they cover most of what you would otherwise hand-write
with loops: counting, chaining, slicing, grouping, windowing and combinatorics.
In JavaScript you would reach for lodash or the newer iterator helpers; in
Python this toolbox has shipped with the language since 2.3.

The functions fall into three groups. **Infinite** iterators never end, so
they are always capped with `islice`, `zip` or `takewhile`. **Terminating**
iterators end when their (shortest) input ends. **Combinatoric** iterators
generate arrangements of their input.

### Reference: infinite iterators

| Function | What it does | Example | Result |
| --- | --- | --- | --- |
| `count` | start, start+step, … | `count(100, 5)` | 100 105 110 … |
| `cycle` | the items, forever | `cycle("AB")` | A B A B … |
| `repeat` | `obj`, `times` times | `repeat(0, 3)` | 0 0 0 |

Full signatures: `count(start=0, step=1)`, `cycle(iterable)`,
`repeat(obj, times=None)` (without `times`, it repeats forever).

### Reference: terminating iterators (part 1)

| Function | What it does | Example | Result |
| --- | --- | --- | --- |
| `accumulate` | running results | `accumulate([1, 2, 3])` | 1 3 6 |
| `batched` | tuples of `n` items | `batched("ABCDE", 2)` | AB CD E |
| `chain` | each input in turn | `chain("AB", "CD")` | A B C D |
| `chain.from_iterable` | same, one outer input | `from_iterable(["AB", "CD"])` | A B C D |
| `compress` | keep where selector true | `compress("ABC", [1, 0, 1])` | A C |
| `dropwhile` | all after first failure | `dropwhile(lambda x: x < 3, [1, 4, 1])` | 4 1 |
| `takewhile` | until first failure | `takewhile(lambda x: x < 3, [1, 4, 1])` | 1 |

### Reference: terminating iterators (part 2)

| Function | What it does | Example | Result |
| --- | --- | --- | --- |
| `filterfalse` | where predicate false | `filterfalse(str.isdigit, "a1b")` | a b |
| `groupby` | runs of equal keys | `groupby("AAB")` | (A, AA) (B, B) |
| `islice` | slice any iterator | `islice("ABCDEF", 1, 5, 2)` | B D |
| `pairwise` | overlapping pairs | `pairwise("ABC")` | AB BC |
| `starmap` | `function(*args)` | `starmap(pow, [(2, 3)])` | 8 |
| `tee` | `n` independent copies | `tee("AB")` | two iterators |
| `zip_longest` | zip to the longest | `zip_longest("AB", "x", fillvalue="-")` | Ax B- |

Full signatures: `accumulate(iterable, func=add, *, initial=None)`,
`batched(iterable, n, *, strict=False)`, `chain(*iterables)`,
`chain.from_iterable(iterable)`, `compress(data, selectors)`,
`dropwhile(predicate, iterable)`, `takewhile(predicate, iterable)`,
`filterfalse(predicate, iterable)`, `groupby(iterable, key=None)`,
`islice(iterable, stop)` or `islice(iterable, start, stop, step)`,
`pairwise(iterable)`, `starmap(function, iterable)`, `tee(iterable, n=2)`,
`zip_longest(*iterables, fillvalue=None)`.

### Reference: combinatoric iterators

| Function | What it does | Example | Result |
| --- | --- | --- | --- |
| `product` | Cartesian product | `product("AB", "12")` | A1 A2 B1 B2 |
| `permutations` | ordered arrangements | `permutations("ABC", 2)` | AB AC BA … (6) |
| `combinations` | unordered, no repeats | `combinations("ABC", 2)` | AB AC BC |
| `combinations_with_replacement` | unordered, repeats | `…("AB", 2)` | AA AB BB |

Full signatures: `product(*iterables, repeat=1)`,
`permutations(iterable, r=None)`, `combinations(iterable, r)`,
`combinations_with_replacement(iterable, r)`.

Every function has its own demo below, in the order of the tables. The
examples assume `import itertools` and `import operator`.

### Infinite iterators

**`count(start, step)`** is an endless counter. It is often zipped with finite
data to number it (the finite input ends the `zip`), or used for generated ids.

```python
invoice_numbers = itertools.count(1001)
print([f"INV-{next(invoice_numbers)}" for _ in range(3)])
print(list(zip(
    ["tea", "rice", "soap"], itertools.count(10, 10), strict=False
)))
```

```text
['INV-1001', 'INV-1002', 'INV-1003']
[('tea', 10), ('rice', 20), ('soap', 30)]
```

**`cycle(iterable)`** repeats the items forever: round-robin assignment,
alternating styles. It saves a copy of the items on the first pass, so it
works even on single-use iterators.

```python
delivery_agents = itertools.cycle(["Asha", "Ravi"])
orders = ["A-1", "A-2", "A-3", "A-4", "A-5"]
print([(order, next(delivery_agents)) for order in orders])
```

```text
[('A-1', 'Asha'), ('A-2', 'Ravi'), ('A-3', 'Asha'), ('A-4', 'Ravi'),
 ('A-5', 'Asha')]
```

**`repeat(obj, times)`** yields the same object again and again. It is handy
as a constant argument to `map`, which stops at its shortest input.

```python
print(list(itertools.repeat("-", 5)))
# map stops at the shortest input, so an infinite repeat is safe here
print(list(map(pow, [2, 3, 4], itertools.repeat(2))))
```

```text
['-', '-', '-', '-', '-']
[4, 9, 16]
```

> **Warning:** `repeat(obj)` yields the *same* object every time, not copies.
> `list(repeat([], 3))` is three references to one list.

### Terminating iterators

**`accumulate(iterable, func, initial=None)`** produces running totals by
default; any two-argument function works (`max` gives a running maximum).
`initial` adds a starting value at the front, so the output is one item
longer. It is the lazy cousin of JavaScript's `reduce` that keeps every
intermediate result.

```python
daily_sales = [450, 1200, 300, 1500]
print(f"{list(itertools.accumulate(daily_sales))=}")
print(f"{list(itertools.accumulate(daily_sales, max))=}")
with_opening_balance = itertools.accumulate(
    daily_sales, operator.add, initial=5000
)
print(f"{list(with_opening_balance)=}")
```

```text
list(itertools.accumulate(daily_sales))=[450, 1650, 1950, 3450]
list(itertools.accumulate(daily_sales, max))=[450, 1200, 1200, 1500]
list(with_opening_balance)=[5000, 5450, 6650, 6950, 8450]
```

> **Note:** the notebook prints the third call inline, as
> `list(itertools.accumulate(daily_sales, operator.add, initial=5000))=`; it
> goes through a variable here to fit the screen.

**`batched(iterable, n)`** (*New in 3.12*) yields chunks of `n` items as
tuples; the last chunk may be shorter. `strict=True` (*New in 3.13*) raises
`ValueError` for a short last batch instead. This is the tool for sending
records to an API or database in fixed-size groups.

```python
order_ids = ["A-1", "A-2", "A-3", "A-4", "A-5"]
print(list(itertools.batched(order_ids, 2, strict=False)))
if sys.version_info >= (3, 13):
    strict_result = raised_error_name(
        lambda: list(itertools.batched(order_ids, 2, strict=True))
    )
    print(f"strict: {strict_result}")
else:
    print("batched(strict=True) needs Python 3.13; skipped")
```

```text
[('A-1', 'A-2'), ('A-3', 'A-4'), ('A-5',)]
strict: ValueError
```

**`chain(*iterables)`** gives one iterator over several iterables, one after
another, without copying them into a new list (unlike `a + b`, which builds a
new list, or JavaScript's `[...a, ...b]`).

```python
morning_orders, evening_orders = ["A-1", "A-2"], ("B-1",)
print(list(itertools.chain(morning_orders, evening_orders, "C")))
```

```text
['A-1', 'A-2', 'B-1', 'C']
```

**`chain.from_iterable(iterable)`** does the same when the iterables arrive as
one (possibly lazy) iterable of iterables. It flattens exactly **one** level,
like JavaScript's `arr.flat()` with the default depth.

```python
orders_per_store = {"Pune": ["A-1", "A-2"], "Goa": ["B-1"]}
print(list(itertools.chain.from_iterable(orders_per_store.values())))
```

```text
['A-1', 'A-2', 'B-1']
```

**`compress(data, selectors)`** keeps the items whose selector is truthy: a
boolean mask, as in NumPy.

```python
skus = ["TEA-500G", "RICE-5KG", "SOAP-3PK"]
in_stock = [True, False, True]
print(list(itertools.compress(skus, in_stock)))
```

```text
['TEA-500G', 'SOAP-3PK']
```

**`dropwhile(predicate, iterable)`** skips items while the predicate holds,
then yields everything that follows. It never checks the predicate again,
which is why the inline comment below survives.

```python
log_lines = [
    "# header",
    "# generated 2026-11-05",
    "INFO start",
    "# inline comment",
    "ERROR stop",
]
print(list(itertools.dropwhile(lambda line: line.startswith("#"), log_lines)))
```

```text
['INFO start', '# inline comment', 'ERROR stop']
```

**`takewhile(predicate, iterable)`** yields items while the predicate holds,
then stops for good. Because it stops, it is safe on infinite input.

```python
sorted_prices = [99, 149, 249, 640, 980]
print(list(itertools.takewhile(lambda price: price < 300, sorted_prices)))
print(list(itertools.takewhile(lambda n: n * n < 50, itertools.count(1))))
```

```text
[99, 149, 249]
[1, 2, 3, 4, 5, 6, 7]
```

> **Note:** `takewhile` consumes the first failing item to find out that it
> fails, and that item is lost to the underlying iterator.

**`filterfalse(predicate, iterable)`** is the complement of the built-in
`filter`.

```python
quantities = ["3", "two", "10", "x"]
print(f"{list(filter(str.isdigit, quantities))=}")
print(f"{list(itertools.filterfalse(str.isdigit, quantities))=}")
```

```text
list(filter(str.isdigit, quantities))=['3', '10']
list(itertools.filterfalse(str.isdigit, quantities))=['two', 'x']
```

**`groupby(iterable, key)`** groups **consecutive** items with the same key,
like Unix `uniq`, not SQL `GROUP BY`. It yields `(key, group)` pairs, where
each group is itself an iterator. Sort by the same key first to get exactly
one group per key. Each group shares the underlying iterator with `groupby`,
so it is invalidated as soon as you advance to the next group: consume it
immediately.

```python
sales = [("Pune", 249), ("Pune", 162), ("Goa", 640), ("Pune", 80)]
unsorted_groups = [
    (city, len(list(group)))
    for city, group in itertools.groupby(sales, key=operator.itemgetter(0))
]
print(f"{unsorted_groups=}  (runs, not totals)")
by_city = sorted(sales, key=operator.itemgetter(0))
print(
    {
        city: sum(amount for _, amount in group)
        for city, group in itertools.groupby(
            by_city, key=operator.itemgetter(0)
        )
    }
)
```

```text
unsorted_groups=[('Pune', 2), ('Goa', 1), ('Pune', 1)]  (runs, not totals)
{'Goa': 640, 'Pune': 491}
```

> **Warning:** `groupby` on unsorted data gives runs, not totals: Pune
> appears twice above. For true totals without sorting, a `dict` or
> `collections.Counter` is usually simpler.

**`islice(iterable, stop)` / `islice(iterable, start, stop, step)`** is
slicing for any iterator. Negative indices are not supported, because an
iterator does not know its length. It consumes the skipped items.

```python
print(list(itertools.islice(itertools.count(1), 5)))
print(list(itertools.islice("ABCDEFGH", 2, 7, 2)))
report_lines = iter(["header", "row 1", "row 2", "row 3"])
print(f"{list(itertools.islice(report_lines, 1, None))=}  (skip a header)")
```

```text
[1, 2, 3, 4, 5]
['C', 'E', 'G']
list(itertools.islice(report_lines, 1, None))=['row 1', 'row 2', 'row 3']
  (skip a header)
```

> **Note:** the last output line is wrapped before the comment to fit the
> screen.

**`pairwise(iterable)`** (*New in 3.10*) yields consecutive overlapping pairs,
which is exactly what you need for differences between neighbours.

```python
stock_levels = [120, 95, 95, 40]
print(list(itertools.pairwise(stock_levels)))
changes = [
    later - earlier
    for earlier, later in itertools.pairwise(stock_levels)
]
print(f"changes: {changes}")
```

```text
[(120, 95), (95, 95), (95, 40)]
changes: [-25, 0, -55]
```

**`starmap(function, iterable)`** is like `map`, but each item is unpacked
into the function's arguments: `function(*item)`.

```python
line_items = [(249, 2), (640, 1), (162, 3)]
print(list(itertools.starmap(operator.mul, line_items)))
```

```text
[498, 640, 486]
```

**`tee(iterable, n)`** splits one iterator into `n` independent ones. It
buffers the items one copy has seen and another has not, so if one copy runs
far ahead of the other, memory grows. Do not use the original iterator after
calling `tee`, or the copies will miss items.

```python
price_feed = iter([249, 640, 162])
for_total, for_maximum = itertools.tee(price_feed)
print(f"{sum(for_total)=}, {max(for_maximum)=}")
```

```text
sum(for_total)=1051, max(for_maximum)=640
```

> **Warning:** in the example, `sum` consumes all of `for_total` before `max`
> starts, so `tee` buffers the whole input. If you will consume one copy fully
> before the other, `list()` is simpler and no slower.

**`zip_longest(*iterables, fillvalue)`** is like `zip`, but runs to the
longest input, padding the gaps with `fillvalue`.

```python
skus = ["TEA-500G", "RICE-5KG", "SOAP-3PK"]
stock_counts = [40, 12]
print(list(itertools.zip_longest(skus, stock_counts, fillvalue=0)))
```

```text
[('TEA-500G', 40), ('RICE-5KG', 12), ('SOAP-3PK', 0)]
```

### Combinatoric iterators

**`product(*iterables, repeat=1)`** is the Cartesian product, the same as
nested `for` loops (the rightmost input varies fastest). `repeat=4` is short
for passing the same input four times.

```python
sizes, colours = ["S", "M"], ["red", "blue"]
print([
    f"{size}-{colour}"
    for size, colour in itertools.product(sizes, colours)
])
print(f"{len(list(itertools.product('01', repeat=4)))=}  (4-bit strings)")
```

```text
['S-red', 'S-blue', 'M-red', 'M-blue']
len(list(itertools.product('01', repeat=4)))=16  (4-bit strings)
```

**`permutations(iterable, r)`** yields ordered arrangements of `r` items;
there are `n! / (n - r)!` of them.

```python
podium = list(itertools.permutations(["Asha", "Ravi", "Meena"], 2))
print(f"{len(podium)=}, first three: {podium[:3]}")
```

```text
len(podium)=6, first three: [('Asha', 'Ravi'), ('Asha', 'Meena'),
('Ravi', 'Asha')]
```

**`combinations(iterable, r)`** yields unordered selections without repeats;
there are `n! / (r! (n - r)!)` of them.

```python
combo_items = ["tea", "rice", "soap", "oil"]
print(list(itertools.combinations(combo_items, 2)))
```

```text
[('tea', 'rice'), ('tea', 'soap'), ('tea', 'oil'), ('rice', 'soap'),
 ('rice', 'oil'), ('soap', 'oil')]
```

**`combinations_with_replacement(iterable, r)`** yields unordered selections
where an item may be chosen more than once. Below: every amount you can make
with exactly two coins.

```python
coin_values = [1, 2, 5]
two_coin_amounts = sorted(
    {
        sum(pair)
        for pair in itertools.combinations_with_replacement(coin_values, 2)
    }
)
print(f"{list(itertools.combinations_with_replacement(coin_values, 2))=}")
print(f"{two_coin_amounts=}")
```

```text
list(itertools.combinations_with_replacement(coin_values, 2))=[(1, 1),
(1, 2), (1, 5), (2, 2), (2, 5), (5, 5)]
two_coin_amounts=[2, 3, 4, 6, 7, 10]
```

> **Note:** the long list outputs in this group (and the `cycle` output
> earlier) are wrapped to fit the screen; each is one line in the real output.

> **Warning:** combinatoric iterators grow explosively. `permutations` of 12
> items is 479 million tuples. They are lazy, so creating one is free, but
> `list()` on a large one will exhaust memory.

### The itertools recipes and `more-itertools`

The
[itertools documentation](https://docs.python.org/3/library/itertools.html#itertools-recipes)
ends with **recipes**: short functions built from the blocks above, meant to
be copied into your code rather than imported. They are also the best way to
learn how the blocks combine. Five of them:

| Recipe | Does |
| --- | --- |
| `take(n, iterable)` | first `n` items as a list |
| `nth(iterable, n, default=None)` | the item at index `n` |
| `all_equal(iterable)` | are all items equal? |
| `unique_everseen(iterable, key=None)` | unique items, first-seen order |
| `partition(predicate, iterable)` | (false items, true items) |

```python
def take(n: int, iterable: Iterable[Any]) -> list[Any]:
    """Return the first n items as a list."""
    return list(itertools.islice(iterable, n))


def nth(iterable: Iterable[Any], n: int, default: Any = None) -> Any:
    """Return the nth item or a default."""
    return next(itertools.islice(iterable, n, None), default)


def all_equal(iterable: Iterable[Any]) -> bool:
    """Return True if all items are equal."""
    groups = itertools.groupby(iterable)
    return next(groups, True) and not next(groups, False)


def unique_everseen(
    iterable: Iterable[Any], key: Callable[[Any], Any] | None = None
) -> Iterator[Any]:
    """Yield unique items, preserving first-seen order."""
    seen: set[Any] = set()
    for item in iterable:
        marker = item if key is None else key(item)
        if marker not in seen:
            seen.add(marker)
            yield item


def partition(
    predicate: Callable[[Any], bool], iterable: Iterable[Any]
) -> tuple[Iterator[Any], Iterator[Any]]:
    """Split into (items where predicate is false, items where it is true)."""
    for_false, for_true = itertools.tee(iterable)
    return (
        itertools.filterfalse(predicate, for_false),
        filter(predicate, for_true),
    )
```

`all_equal` is worth a second look: `groupby` produces one group per run of
equal items, so "all equal" means "at most one group". The first `next`
fetches the first group (or `True` for empty input), and the second checks
that there is no second group.

Each recipe on a small input:

```python
print(f"{take(3, itertools.count(1001))=}")
print(f"{nth('ABCDE', 2)=}, {nth('AB', 9, 'none')=}")
print(f"{all_equal([5, 5, 5])=}, {all_equal('aab')=}")
mixed_case_skus = ["Tea", "rice", "TEA", "Rice"]
print(f"{list(unique_everseen(mixed_case_skus, key=str.lower))=}")
cheap, expensive = partition(lambda price: price > 500, [249, 640, 162, 980])
print(f"{list(cheap)=}, {list(expensive)=}")
```

```text
take(3, itertools.count(1001))=[1001, 1002, 1003]
nth('ABCDE', 2)='C', nth('AB', 9, 'none')='none'
all_equal([5, 5, 5])=True, all_equal('aab')=False
list(unique_everseen(mixed_case_skus, key=str.lower))=['Tea', 'rice']
list(cheap)=[249, 162], list(expensive)=[640, 980]
```

> **Note:** the notebook passes the SKU list inline to `unique_everseen`; it
> goes through `mixed_case_skus` here to keep the line short.

The third-party **`more-itertools`** package implements all the recipes and
many more (`chunked`, `windowed`, `peekable`, `first`, `one`, `spy`, …). It is
installed in Phase 4 (`uv add more-itertools`), so the notebook checks whether
it is available and skips cleanly if not.

```python
if importlib.util.find_spec("more_itertools") is not None:
    import more_itertools

    print(f"{more_itertools.first([249, 640])=}")
    print(f"{list(more_itertools.chunked(range(7), 3))=}")
else:
    print("more-itertools is not installed (it is added in Phase 4); skipped")
```

```text
more-itertools is not installed (it is added in Phase 4); skipped
```

### Key points

| Idea | Remember |
| --- | --- |
| Return type | Every function returns a lazy iterator |
| Infinite | `count`, `cycle`, `repeat`: always cap them |
| `groupby` | Consecutive runs only; sort first |
| `tee` | Buffers the gap between copies |
| Combinatorics | Lazy, but sizes explode |
| Recipes | Copy from the docs, or `more-itertools` |

## Lab 1.13

Seven exercises that put the unit to work. In the notebook, each one has a
stub to fill in and a check cell that prints `PASS` or `FAIL` per test case;
until you write the solution every check prints `FAIL`, which is expected.
The reference solutions below pass every check. They use `deque` and
`Counter` from `collections`, plus the imports from the top of this page.

### Exercise 1 — re-iterable `Countdown`

Unit 1.9.1 wrote `Countdown` with a separate `CountdownIterator` class.
Rewrite it with **no iterator class**: make `__iter__` a generator method that
yields `start, start - 1, …, 1`. Every loop must get a fresh generator, so the
object can be looped over many times, and nested.

| Check | Expected |
| --- | --- |
| `list(Countdown(3))` | `[3, 2, 1]` |
| Two `list()` calls on one object | `[2, 1]` both times |
| Nested loops over `Countdown(3)` | 9 pairs |
| `list(Countdown(0))` | `[]` |
| `Countdown(-1)` | `ValueError` in `__init__` |
| `iter(Countdown(3))` | a generator |

**Hint:** a method containing `yield` is a generator function; each call to
`iter()` calls `__iter__` again and so creates a new generator. Validate in
`__init__`, not in `__iter__`, because the generator body starts lazily.

<details><summary>Solution</summary>

```python
class Countdown:
    """Re-iterable countdown from start to 1."""

    def __init__(self, start: int) -> None:
        if start < 0:
            raise ValueError("start must not be negative")
        self.start = start

    def __iter__(self) -> Iterator[int]:
        """A generator method: every loop gets a fresh generator."""
        current = self.start
        while current > 0:
            yield current
            current -= 1
```

The position (`current`) is a local variable of the generator, not an
attribute of the `Countdown`, so concurrent loops cannot interfere.

</details>

### Exercise 2 — `read_log_records(path)`

Write a **generator function** that opens the log file (UTF-8, with `with`)
and yields one dict per record line, with keys `date`, `time`, `level` and
`message`, using `line.split(maxsplit=3)` (the format of `parse_log_line` from
Unit 1.4.7). Strip each line; skip blank lines, lines starting with `#`, and
lines with fewer than four fields. It must be lazy: the file is opened only
when iteration starts, and read one line at a time.

The check writes this six-line sample log:

```text
# service log
2026-11-05 09:30:01 INFO user asha logged in

2026-11-05 09:30:05 ERROR payment failed: card declined
garbage line
2026-11-05 09:31:00 WARNING disk 91% full
```

| Check | Expected |
| --- | --- |
| Record count | 3 |
| First record | `INFO`, `user asha logged in`, … |
| Levels | `["INFO", "ERROR", "WARNING"]` |
| Return value | a generator |
| Call with a missing file | no error yet |
| First `next()` on a missing file | `FileNotFoundError` |

**Hints:** put the `with` statement inside the generator, so that the file is
opened on the first `next()` and closed when the generator finishes or is
closed. Iterate the file object directly to read one line at a time.

<details><summary>Solution</summary>

```python
def read_log_records(path: Path) -> Iterator[dict[str, str]]:
    """Yield {"date", "time", "level", "message"} for each record
    line of the file."""
    with path.open(encoding="utf-8") as log_file:
        for raw_line in log_file:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            fields = line.split(maxsplit=3)
            if len(fields) < 4:
                continue
            date, time_of_day, level, message = fields
            yield {
                "date": date,
                "time": time_of_day,
                "level": level,
                "message": message,
            }
```

The "lazy open" check passes because calling a generator function runs none
of its body, so `path.open` has not been called yet.

</details>

### Exercise 3 — `flatten(nested)`

Write a recursive generator (use `yield from`) that yields the leaves of
arbitrarily nested **lists and tuples**, left to right. Everything else,
including strings and dicts, is a leaf and is yielded as is.

| Input | Expected output |
| --- | --- |
| `[1, [2, [3, [4, (5, 6)]]], 7]` | `[1, 2, 3, 4, 5, 6, 7]` |
| `["tea", ["rice", ("soap",)]]` | `["tea", "rice", "soap"]` |
| `[{"a": 1}, [[]]]` | `[{"a": 1}]` |
| `[[], [[]]]` | `[]` |
| `(1, (2, [3]))` | `[1, 2, 3]` |

It must also return a generator (`inspect.isgenerator(flatten([]))`).

**Hint:** check `isinstance(item, (list, tuple))`. Do not test "is it
iterable?": strings are iterable, and every character is itself a string, so
that recursion would never end.

<details><summary>Solution</summary>

```python
def flatten(nested: Iterable[Any]) -> Iterator[Any]:
    """Yield the leaves of nested lists and tuples."""
    for item in nested:
        if isinstance(item, (list, tuple)):
            yield from flatten(item)
        else:
            yield item
```

</details>

### Exercise 4 — `running_average()` coroutine

Write a generator used with `send`. After priming with `next()` (which yields
`None`), each `send(number)` yields the average of **all numbers sent so
far**, as a float. Each call to `running_average()` starts fresh.

| Numbers sent | Priming value, averages |
| --- | --- |
| `10, 20, 60` | `None`, `[10.0, 15.0, 30.0]` |
| `1, 2` | averages `[1.0, 1.5]` |
| `[100]` then a new one with `[2]` | `[100.0]`, `[2.0]` |

**Hint:** the shape is `duplicate_detector` from section 1.13.7: keep the
state in locals, and loop on `number = yield average`.

<details><summary>Solution</summary>

```python
def running_average() -> Generator[float | None, float]:
    """Receive numbers with send(); yield the running average."""
    total = 0.0
    count = 0
    average: float | None = None
    while True:
        number = yield average
        total += number
        count += 1
        average = total / count
```

Starting `total` at `0.0` makes every average a float, even when only ints are
sent.

</details>

### Exercise 5 — `paginate(fetch_page)`

`fetch_page(page_number)` returns a list of items (pages are numbered from 1),
and an **empty list** after the last page, like a paginated API. Write a
generator that yields every item of every page, one at a time, and fetches a
page **only when the consumer needs its first item**.

The check uses a fake API that records every page number it is asked for:

| Check | Expected |
| --- | --- |
| 7 items, page size 3 | all 7 items in order |
| Take 3 items, page size 2 | items `A-1..A-3`; pages `[1, 2]` |
| No items | `[]` |
| Create but do not iterate | no pages fetched |

**Hints:** loop over `itertools.count(1)` for the page numbers, stop with
`return` on an empty page, and `yield from` each page.

<details><summary>Solution</summary>

```python
def paginate(fetch_page: Callable[[int], list[Any]]) -> Iterator[Any]:
    """Yield items from pages 1, 2, … until fetch_page returns an empty
    list."""
    for page_number in itertools.count(1):
        page = fetch_page(page_number)
        if not page:
            return
        yield from page
```

Taking three items with a page size of 2 fetches page 2 only when the third
item is requested, and page 3 is never fetched.

</details>

### Exercise 6 — `sliding_windows(iterable, size)`

Yield tuples of `size` consecutive items: `sliding_windows("ABCD", 3)` yields
`("A", "B", "C")` then `("B", "C", "D")`. Fewer than `size` items yields
nothing. It must work on infinite iterators and keep at most `size` items in
memory. `size < 1` raises `ValueError` (raising when iteration starts is fine).

| Call | Expected |
| --- | --- |
| `sliding_windows("ABCD", 3)` | `ABC`, `BCD` (as tuples) |
| `sliding_windows([7, 8], 1)` | `[(7,), (8,)]` |
| `sliding_windows([1, 2], 3)` | `[]` |
| First 3 of `count()`, size 2 | `[(0, 1), (1, 2), (2, 3)]` |
| Moving average of `[10, 20, 40]` | `[15.0, 30.0]` |
| `size=0` | `ValueError` |

**Hint:** `collections.deque(maxlen=size)` drops the oldest item
automatically when you append to a full deque.

<details><summary>Solution</summary>

```python
def sliding_windows(
    iterable: Iterable[Any], size: int
) -> Iterator[tuple[Any, ...]]:
    """Yield overlapping windows of size consecutive items."""
    if size < 1:
        raise ValueError("size must be at least 1")
    window: deque[Any] = deque(maxlen=size)
    for item in iterable:
        window.append(item)
        if len(window) == size:
            yield tuple(window)
```

`itertools.pairwise` is the special case `size=2`.

</details>

### Exercise 7 — streaming analysis of a 1M-line log

Write two functions:

- `summarize_log(records)`: one pass over **any iterable** of record dicts (as
  yielded by `read_log_records`), returning a dict with `"total"` (the record
  count), `"by_level"` (`{level: count}` sorted by level name) and
  `"first_error"` (the message of the first `ERROR` record, or `None`). Do not
  build a list of the records.
- `analyze_log_file(path)`: `summarize_log(read_log_records(path))`.

The notebook provides `write_big_log(path, line_count)` (deterministic data:
a comment, a blank line, then records whose level follows a fixed 10-step
pattern), `analyze_log_file_eager(path)` (the same summary computed by loading
the whole file into memory with `read_text().splitlines()`, the pattern to
avoid) and `peak_memory(function, *args)`, which returns the result and the
peak bytes measured with `tracemalloc`.

| Check | Expected |
| --- | --- |
| Three small records | total 3; ERROR 2, WARNING 1 |
| Small `first_error` | `"first failure"` |
| An iterator as input | total 3 |
| No records | total 0, `{}`, `None` |
| 1M lines vs eager | same result |
| 1M lines `by_level` | DEBUG 200k, ERROR 100k, … |
| 1M lines memory | streaming peak < eager / 20 |

The full expected `by_level` for the million-line log is
`{"DEBUG": 200_000, "ERROR": 100_000, "INFO": 600_000, "WARNING": 100_000}`,
and `first_error` is `"request 9 handled"`.

**Hints:** a `collections.Counter` counts levels in one pass, and
`Counter.total()` gives the record count. Record `first_error` only while it
is still `None`. Because `read_log_records` is a generator, the whole chain
from file to summary holds one line at a time.

<details><summary>Solution</summary>

```python
def summarize_log(records: Iterable[dict[str, str]]) -> dict[str, Any]:
    """Return {"total", "by_level", "first_error"} in a single pass
    over records."""
    level_counts: Counter[str] = Counter()
    first_error: str | None = None
    for record in records:
        level_counts[record["level"]] += 1
        if first_error is None and record["level"] == "ERROR":
            first_error = record["message"]
    return {
        "total": level_counts.total(),
        "by_level": dict(sorted(level_counts.items())),
        "first_error": first_error,
    }


def analyze_log_file(path: Path) -> dict[str, Any]:
    """Stream the file through read_log_records into summarize_log."""
    return summarize_log(read_log_records(path))
```

Running the checks with this solution prints:

```text
PASS  small input
PASS  accepts an iterator
PASS  no records
  peak memory: streaming 150 kB, eager 145 MB
PASS  1M lines: same result, 20x less memory
4/4 checks passed
```

The peak-memory figures vary by machine and Python version, but the ratio is
the point: about a thousand times less memory for the same answer.

</details>

## Recap

| Concept | Takeaway | JavaScript equivalent |
| --- | --- | --- |
| Iterable vs iterator | Iterables give fresh iterators; iterators are single use | `Symbol.iterator` |
| Custom iterators | Position lives in a separate iterator object | `[Symbol.iterator]()` |
| `__getitem__` fallback | Legacy loop protocol; ABC misses it | none |
| Generator functions | `yield` makes a lazy, pausable iterator | `function*` |
| Generator `return` | Value rides on `StopIteration.value` | `{value, done: true}` |
| Generator expressions | Single use, constant memory | iterator helpers |
| Lazy pipelines | Pull-based, one item at a time, stops early | streams |
| `yield from` | Delegates, recurses, returns a value | `yield*` |
| Two-way generators | `send` (prime first), `throw`, `close` | `next(v)`, `throw`, `return` |
| Generators → async | Coroutines are driven with `send` | `async` / `await` |
| `itertools` | Infinite, terminating, combinatoric blocks | lodash |
| Recipes | Copy from the docs or use `more-itertools` | lodash |

## Further reading

- [Glossary: iterable](https://docs.python.org/3/glossary.html#term-iterable),
  [iterator](https://docs.python.org/3/glossary.html#term-iterator) and
  [generator](https://docs.python.org/3/glossary.html#term-generator)
- [Iterator types](https://docs.python.org/3/library/stdtypes.html#iterator-types)
- [Generator expressions](https://docs.python.org/3/reference/expressions.html#generator-expressions)
  and
  [yield expressions](https://docs.python.org/3/reference/expressions.html#yield-expressions)
- [Functional programming HOWTO](https://docs.python.org/3/howto/functional.html)
- [`itertools`](https://docs.python.org/3/library/itertools.html) and its
  [recipes](https://docs.python.org/3/library/itertools.html#itertools-recipes)
- [`inspect.getgeneratorstate`](https://docs.python.org/3/library/inspect.html#inspect.getgeneratorstate)
  and
  [coroutine objects](https://docs.python.org/3/reference/datamodel.html#coroutine-objects)
- [PEP 234 — Iterators](https://peps.python.org/pep-0234/)
- [PEP 255 — Simple generators](https://peps.python.org/pep-0255/)
- [PEP 289 — Generator expressions](https://peps.python.org/pep-0289/)
- [PEP 342 — Coroutines via enhanced generators](https://peps.python.org/pep-0342/)
- [PEP 380 — Syntax for delegating to a subgenerator](https://peps.python.org/pep-0380/)
- [PEP 479 — Change StopIteration handling inside generators](https://peps.python.org/pep-0479/)
- [PEP 492 — Coroutines with async and await syntax](https://peps.python.org/pep-0492/)
- [PEP 525 — Asynchronous generators](https://peps.python.org/pep-0525/)

[← Previous](unit-1-12-decorators-functools-and-the-call-stack.md) · [Index](README.md) · [Next →](unit-1-14-exceptions-and-context-managers.md)
