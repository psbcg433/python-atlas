# Unit 1.5 — Collection Data Types I: Lists, Tuples and Ranges

[← Previous](unit-1-4-text-and-binary-data-types.md) · [Index](README.md) · [Next →](unit-1-6-collection-data-types-ii-dictionaries-sets-and-the-collections-module.md)

This unit covers Python's *sequence* types: containers where every item has a
position. You will see what a `list` really is inside CPython and what each
operation costs, learn the complete list API (including slice assignment and
starred unpacking), and then meet the immutable and specialised sequences:
`tuple`, named tuples, `range` and `array.array`.

## What you will learn

- The operations every sequence shares, and which types support which.
- How CPython stores a `list` (a dynamic array of pointers) and the Big-O cost
  of each list operation.
- The complete `list` API: adding, removing, searching, ordering, copying,
  slice assignment and starred unpacking.
- How to sort by several keys, stably, in mixed directions.
- When to pick a `list`, a `tuple`, a named tuple, a `range` or an
  `array.array`.

## JavaScript → Python bridge

A JavaScript `Array` does the job of nearly every type in this unit. Python
splits that job between a mutable `list`, an immutable `tuple`, a lazy `range`
and a typed `array.array`. The table lists the habits that will trip you up.

| JavaScript | Python | The difference that bites |
| --- | --- | --- |
| `arr.push(x)` | `items.append(x)` | Returns `None`, not the new length |
| `arr.pop()` | `items.pop()` | Same idea; raises on an empty list |
| `arr.shift()` | `items.pop(0)` | O(n); use `collections.deque` (1.6.7) |
| `arr.unshift(x)` | `items.insert(0, x)` | O(n) as well |
| `[10, 9, 1].sort()` | `sorted([10, 9, 1])` | Python compares values, not strings |
| `arr.sort()` returns `arr` | `items.sort()` | Returns `None`; use `sorted()` |
| `arr.slice(1, 3)` | `items[1:3]` | Slices take a step and can be assigned |
| `arr.at(-1)` | `items[-1]` | Negative indexes work everywhere |
| `Object.freeze([lat, lng])` | `(lat, lng)` | A tuple is hashable: a dict key |
| `const [first, ...rest] = arr` | `first, *rest = items` | Star can sit in the middle |
| `Array.from({length: 5}, …)` | `range(5)` | Lazy: no list is built |
| `Float64Array` | `array.array("d")` | Typed, compact numeric storage |

> **Note:** a few output lines in this unit are longer than a phone screen. They
> are wrapped at a comma or a space, and the continuation is indented by two
> spaces. Nothing else in the outputs is changed. Lines of code that were longer
> than 80 characters in the course notebook are reflowed (usually by splitting an
> f-string into two adjacent string literals, which Python joins), so they behave
> exactly the same.

The examples use two small helpers. `show_size` prints an object's shallow size,
type and id; `raised_error_name` calls a function and returns the name of the
exception it raised, so one line can show "this raises `ValueError`" without
stopping the program.

```python
import array
import csv
import dis
import io
import operator
import sqlite3
import sys
import timeit
from collections import namedtuple
from collections.abc import Callable, Hashable, Iterable
from typing import Any, NamedTuple


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


print(f"{sys.version_info[:2]=}")
```

```text
sys.version_info[:2]=(3, 15)
```

## 1.5.1 Common sequence operations

A *sequence* is any container whose items are numbered from `0`. Python defines
a common set of operations that every sequence type supports, so once you know
them for `list` you already know them for `tuple`, `str`, `range` and `bytes`:

- **Indexing** `s[i]` reads one item; negative indexes count from the end, so
  `s[-1]` is the last item (like JavaScript's `arr.at(-1)`).
- **Slicing** `s[start:stop:step]` returns a new sequence of the same type. The
  `stop` index is excluded, any part can be omitted, and a negative step walks
  backwards, so `s[::-1]` is a reversed copy.
- **Membership** `x in s` scans for an item equal to `x`.
- **Length** `len(s)`.
- **Concatenation** `s + t` and **repetition** `s * n` build new sequences.
- **`min(s)`** and **`max(s)`** compare the items.
- **`s.count(x)`** counts equal items, and **`s.index(x, start)`** returns the
  first position of `x`, optionally starting the search at `start`.

```python
weekly_orders = [12, 7, 19, 7, 25]
print(f"{weekly_orders[0]=}, {weekly_orders[-1]=}, {weekly_orders[1:4]=}")
print(
    f"{weekly_orders[::-1]=}, {19 in weekly_orders=}, "
    f"{len(weekly_orders)=}"
)
print(f"{weekly_orders + [30]=}, {[0] * 3=}")
print(f"{min(weekly_orders)=}, {max(weekly_orders)=}")
print(
    f"{weekly_orders.count(7)=}, {weekly_orders.index(7)=}, "
    f"{weekly_orders.index(7, 2)=}"
)
```

```text
weekly_orders[0]=12, weekly_orders[-1]=25, weekly_orders[1:4]=[7, 19, 7]
weekly_orders[::-1]=[25, 7, 19, 7, 12], 19 in weekly_orders=True,
  len(weekly_orders)=5
weekly_orders + [30]=[12, 7, 19, 7, 25, 30], [0] * 3=[0, 0, 0]
min(weekly_orders)=7, max(weekly_orders)=25
weekly_orders.count(7)=2, weekly_orders.index(7)=1,
  weekly_orders.index(7, 2)=3
```

### Support table

Not every sequence supports every operation. The table below summarises the
differences across `list`, `tuple`, `str`, `range` and `bytes`; anything not
listed under "Not supported" works on all five.

| Operation | Not supported by | Notes |
| --- | --- | --- |
| `s[i]` | — | `bytes` gives an `int` |
| `s[a:b]` | — | `range` gives a `range` |
| `x in s` | — | `str` finds substrings; `range` is O(1) |
| `len(s)` | — | |
| `s + t` | `range` | `TypeError` |
| `s * n` | `range` | `TypeError` |
| `min(s)`, `max(s)` | — | |
| `s.count(x)` | — | |
| `s.index(x)` | — | |
| `s[i] = x` | all but `list` | use `bytearray` for bytes |

Rather than trust the table, the next cell checks every row by running each
operation on a sample of each type and catching `TypeError`.

```python
def supports(operation: Callable[[Any], object], sequence: Any) -> bool:
    """Return True if operation(sequence) runs without TypeError."""
    try:
        operation(sequence)
    except TypeError:
        return False
    return True


def assign_first(sequence: Any) -> None:
    """Try to replace the first item in place."""
    sequence[0] = sequence[0]


sequence_samples = {
    "list": [3, 1, 2],
    "tuple": (3, 1, 2),
    "str": "312",
    "range": range(3),
    "bytes": b"312",
}
sequence_operations: dict[str, Callable[[Any], object]] = {
    "s[i]": lambda sequence: sequence[0],
    "s[a:b]": lambda sequence: sequence[1:],
    "x in s": lambda sequence: sequence[0] in sequence,
    "len(s)": len,
    "s + t": lambda sequence: sequence + sequence,
    "s * n": lambda sequence: sequence * 2,
    "min, max": lambda sequence: (min(sequence), max(sequence)),
    "s.count(x)": lambda sequence: sequence.count(sequence[0]),
    "s.index(x)": lambda sequence: sequence.index(sequence[0]),
    "s[i] = x": assign_first,
}
print(
    f"{'operation':<12}"
    + "".join(f"{type_name:>7}" for type_name in sequence_samples)
)
for operation_label, operation in sequence_operations.items():
    support_marks = [
        "✓" if supports(operation, sample) else "✗"
        for sample in sequence_samples.values()
    ]
    print(
        f"{operation_label:<12}"
        + "".join(f"{mark:>7}" for mark in support_marks)
    )
```

```text
operation      list  tuple    str  range  bytes
s[i]              ✓      ✓      ✓      ✓      ✓
s[a:b]            ✓      ✓      ✓      ✓      ✓
x in s            ✓      ✓      ✓      ✓      ✓
len(s)            ✓      ✓      ✓      ✓      ✓
s + t             ✓      ✓      ✓      ✗      ✓
s * n             ✓      ✓      ✓      ✗      ✓
min, max          ✓      ✓      ✓      ✓      ✓
s.count(x)        ✓      ✓      ✓      ✓      ✓
s.index(x)        ✓      ✓      ✓      ✓      ✓
s[i] = x          ✓      ✗      ✗      ✗      ✗
```

`range` refuses `+` and `*` because the result of joining two ranges is usually
not an arithmetic progression, so it could not be another `range`. Only `list`
allows item assignment, because it is the only mutable type in the group.

> **Note:** JavaScript has nothing like slicing with a step, and its strings and
> arrays share only a few methods by convention. In Python the shared behaviour
> is a protocol: any class that implements `__getitem__` and `__len__`
> gets indexing, slicing and `in` the same way.

### Key points

| Idea | Takeaway |
| --- | --- |
| Shared operations | Index, slice, `in`, `len`, `min`, `max` |
| Slices | `s[a:b:step]`; `stop` is excluded |
| `index(x, start)` | Search begins at `start` |
| `range` | No `+` or `*` |
| Item assignment | Only `list` (and `bytearray`) |

## 1.5.2 Lists (`list`) — internals

A JavaScript array is a fairly magical object: engines switch between packed,
holey and dictionary representations depending on how you use it. A CPython
`list` is much simpler and fully predictable. It is a **dynamic array of
pointers**. The list object itself holds three things: its length (`ob_size`),
its capacity (`allocated`) and a pointer to a separate block of `PyObject*`
slots. Each slot points to an item object that lives somewhere else on the
heap. Items are never stored inline in the list, which is why a single list can
hold a mix of types: every slot is the same size (8 bytes on a 64-bit build)
whatever it points to.

```text
list object                pointer array (capacity 4)
+----------------+        +--------+--------+--------+--------+
| ob_size = 3    |  --->  | slot 0 | slot 1 | slot 2 | spare  |
| allocated = 4  |        +---|----+---|----+---|----+--------+
+----------------+            v        v        v
                           int 10  str 'dosa' float 2.5
```

### Over-allocation

If the slot array had exactly as many slots as items, every `append` would
have to allocate a bigger block and copy all the pointers: O(n) per append and
O(n²) to build a list. Instead, when the array is full, CPython
**over-allocates**: it grows the capacity by roughly one eighth plus a few
spare slots. Most appends then just fill a spare slot and bump `ob_size`. The
occasional resize is expensive, but spread over all the appends it costs a
constant amount each, so `append` is O(1) *amortized*.

You can watch this happen with `sys.getsizeof`, which reports the size of the
list header plus its slot array (but **not** the items the slots point to).

```python
growing_list: list[int] = []
previous_size = sys.getsizeof(growing_list)
print(f"len=0    size={previous_size} bytes")
for item_count in range(1, 41):
    growing_list.append(item_count)
    current_size = sys.getsizeof(growing_list)
    if current_size != previous_size:
        added_slots = (current_size - previous_size) // 8
        print(
            f"len={item_count:<4} size={current_size} bytes "
            f"(+{added_slots} slots)"
        )
        previous_size = current_size
print(
    f"{sys.getsizeof([1]) == sys.getsizeof([10**1000])=}"
    "  (items are not counted)"
)
```

```text
len=0    size=56 bytes
len=1    size=88 bytes (+4 slots)
len=5    size=120 bytes (+4 slots)
len=9    size=184 bytes (+8 slots)
len=17   size=248 bytes (+8 slots)
len=25   size=312 bytes (+8 slots)
len=33   size=376 bytes (+8 slots)
sys.getsizeof([1]) == sys.getsizeof([10**1000])=True  (items are not counted)
```

The size only changes at lengths 1, 5, 9, 17, 25 and 33; every append in
between used a spare slot. The last line shows that a list holding a tiny int
and a list holding a thousand-digit int have the same size: the list stores
pointers, not values.

> **Note:** the exact byte counts and growth pattern are CPython
> implementation details and vary between versions and platforms. The
> principle (occasional jumps, not one per append) does not.

### Cost of list operations

Because a list is a contiguous array, anything at the **end** is cheap and
anything at the **front** is expensive: inserting or removing at position 0
must shift every other pointer by one slot. Searching has no index to help it,
so `in`, `index` and `remove` scan from the start comparing with `==`.

In the table, *n* is the length of the list and *k* the length of the other
iterable or slice.

| Operation | Cost | Why |
| --- | --- | --- |
| `items[i]`, `items[i] = x` | O(1) | pointer arithmetic |
| `append(x)`, `pop()` | O(1) amortized | work at the end only |
| `pop(0)`, `insert(0, x)` | O(n) | every pointer shifts |
| `x in items`, `index(x)` | O(n) | linear scan with `==` |
| `remove(x)` | O(n) | scan, then shift |
| `extend(other)`, `items[a:b]` | O(k) | copy *k* pointers |
| `sort()`, `sorted()` | O(n log n) | Timsort; O(n) if sorted |

Timings make the table concrete. The next cell runs each statement a thousand
times on a list of 100 000 integers.

```python
timing_cases = [
    ("items[50_000]", "O(1)"),
    ("items.append(0); items.pop()", "O(1)"),
    ("items.insert(0, 0); items.pop(0)", "O(n)"),
    ("99_999 in items", "O(n)"),
]
run_count = 1_000
for statement, complexity in timing_cases:
    elapsed_seconds = timeit.timeit(
        statement, setup="items = list(range(100_000))", number=run_count
    )
    nanoseconds_per_run = elapsed_seconds / run_count * 1e9
    print(
        f"{statement:<34} {complexity:<5} "
        f"{nanoseconds_per_run:>12,.0f} ns per run"
    )
```

```text
items[50_000]                      O(1)            11 ns per run
items.append(0); items.pop()       O(1)            24 ns per run
items.insert(0, 0); items.pop(0)   O(n)        28,440 ns per run
99_999 in items                    O(n)       568,221 ns per run
```

> **Note:** timings depend on the machine and vary from run to run. What
> matters is the gap: working at the front is thousands of times slower than
> working at the end, and a membership scan of the whole list is slower still
> because each step calls `==` on an object.

> **Warning:** a list used as a FIFO queue (`append` plus `pop(0)`) becomes
> quadratic as it grows. Use `collections.deque` (Unit 1.6) when you need to
> add or remove at the front, and a `set` or `dict` (Unit 1.6) when you need
> fast membership tests.

### Key points

| Idea | Takeaway |
| --- | --- |
| Layout | Header + separate array of pointers |
| Mixed types | Every slot is one pointer |
| Over-allocation | `append` is O(1) amortized |
| Front operations | `pop(0)`, `insert(0, x)` are O(n) |
| Search | `in`, `index`, `remove` are O(n) |
| `sys.getsizeof` | Counts slots, not items |

## 1.5.3 List methods (complete API)

Python lists have a small, regular API. One rule ties it together and differs
from JavaScript: **methods that mutate the list return `None`**. JavaScript's
`push` returns the new length and `sort` returns the array, which invites
chaining; Python deliberately refuses, so that you can never mistake an
in-place change for a new value. Functions that build a new list, such as
`sorted()` and the `+` operator, return that list.

### Adding: `append`, `extend`, `insert`, `+=` vs `+`

- `append(x)` adds **one** object at the end, even when that object is itself
  a list (it becomes a nested item).
- `extend(iterable)` adds **every item** of any iterable: a list, tuple,
  string, generator, anything you can loop over.
- `insert(i, x)` puts `x` **before** index `i`.
- `items += iterable` is the same as `extend`: it changes the list **in
  place**, so every other name bound to that list sees the change, and it
  accepts any iterable.
- `items + other` builds a **new** list and insists that `other` is also a
  list.

```python
cart_items = ["idli"]
cart_items.append("dosa")
cart_items.extend(["vada", "chutney"])
cart_items.insert(1, "coffee")
print(f"{cart_items=}")
print(f"{cart_items.append('tea')=}  (mutating methods return None)")
nested_cart = ["idli"]
nested_cart.append(["vada", "chutney"])
print(f"{nested_cart=}  (append adds the list as one item)")
original_cart = cart_items
cart_items += ("sambar",)
print(
    f"{cart_items is original_cart=}"
    "  (+= extends in place, accepts any iterable)"
)
cart_items = cart_items + ["payasam"]
print(f"{cart_items is original_cart=}  (+ builds a new list)")
print(f"list + tuple: {raised_error_name(lambda: ['idli'] + ('vada',))}")
```

```text
cart_items=['idli', 'coffee', 'dosa', 'vada', 'chutney']
cart_items.append('tea')=None  (mutating methods return None)
nested_cart=['idli', ['vada', 'chutney']]  (append adds the list as one item)
cart_items is original_cart=True  (+= extends in place, accepts any iterable)
cart_items is original_cart=False  (+ builds a new list)
list + tuple: TypeError
```

> **Warning:** `cart_items = cart_items.append("tea")` is a classic bug for
> JavaScript developers: it replaces your list with `None`. Call the method as a
> statement and keep using the same name.

### Removing: `remove`, `pop`, `clear`, `del`

- `remove(x)` deletes the **first** item equal to `x`, and raises
  `ValueError` if there is none.
- `pop(i)` removes **and returns** the item at index `i`; with no argument it
  takes the last item. It raises `IndexError` on an empty list or a bad index.
- `clear()` empties the list in place.
- The `del` statement removes by position: `del items[i]` for one item,
  `del items[a:b]` for a slice. It returns nothing.

```python
order_queue = ["idli", "dosa", "vada", "dosa", "upma", "poha", "khichdi"]
order_queue.remove("dosa")
print(f"{order_queue=}  (only the first 'dosa' is gone)")
try:
    order_queue.remove("pizza")
except ValueError as error:
    print(f"remove: {type(error).__name__}: {error}")
last_order = order_queue.pop()
second_order = order_queue.pop(1)
print(f"{last_order=}, {second_order=}, {order_queue=}")
del order_queue[0]
print(f"after del [0]: {order_queue}")
del order_queue[1:3]
print(f"after del [1:3]: {order_queue}")
order_queue.clear()
print(
    f"after clear(): {order_queue}, "
    f"pop on empty: {raised_error_name(order_queue.pop)}"
)
```

```text
order_queue=['idli', 'vada', 'dosa', 'upma', 'poha', 'khichdi']
  (only the first 'dosa' is gone)
remove: ValueError: list.remove(x): x not in list
last_order='khichdi', second_order='vada',
  order_queue=['idli', 'dosa', 'upma', 'poha']
after del [0]: ['dosa', 'upma', 'poha']
after del [1:3]: ['dosa']
after clear(): [], pop on empty: IndexError
```

### Searching: `index(x, start, end)`, `count`, `in`

`index(x, start, end)` returns the first position of `x` within the window
`items[start:end]`. The position it returns is still counted from the start of
the whole list, not from `start`. If `x` is not in the window it raises
`ValueError` (JavaScript's `indexOf` returns `-1` instead). `count(x)` counts
equal items. All three, together with `in`, compare with `==`, which matters
because `1 == 1.0 == True` in Python.

```python
daily_statuses = ["ok", "late", "ok", "failed", "late", "ok"]
print(f"{daily_statuses.index('late')=}")
print(f"{daily_statuses.index('late', 2)=}  (search from position 2)")
print(f"{daily_statuses.index('ok', 3, 6)=}")
print(
    "index outside the window: "
    f"{raised_error_name(lambda: daily_statuses.index('failed', 4))}"
)
print(f"{daily_statuses.count('ok')=}, {'failed' in daily_statuses=}")
print(f"{[1, 1.0, True].count(1)=}  (1 == 1.0 == True)")
```

```text
daily_statuses.index('late')=1
daily_statuses.index('late', 2)=4  (search from position 2)
daily_statuses.index('ok', 3, 6)=5
index outside the window: ValueError
daily_statuses.count('ok')=3, 'failed' in daily_statuses=True
[1, 1.0, True].count(1)=3  (1 == 1.0 == True)
```

> **Note:** when "not found" is a normal outcome, test with `in` first or catch
> `ValueError`. Do not reach for a `-1` sentinel: in Python, `items[-1]` is a
> perfectly valid index (the last item), so a stray `-1` silently reads the
> wrong value.

### Ordering: `sort()` vs `sorted()`, `reverse()` vs `reversed()`

Python offers each ordering operation in two flavours:

- `items.sort()` sorts **in place** and returns `None`. `sorted(iterable)`
  returns a **new** list and works on any iterable (a string, a set, a
  generator). Both take the keyword-only arguments `key=` and `reverse=`.
- `items.reverse()` reverses **in place** and returns `None`.
  `reversed(items)` returns a lazy iterator that walks the list backwards
  without copying it.

```python
dish_names = ["vada", "Idli", "dosa", "Upma"]
sorted_copy = sorted(dish_names)
print(f"{sorted_copy=}, {dish_names=}  (original untouched)")
print(f"{dish_names.sort(key=str.lower)=}  (sort() returns None)")
print(f"{dish_names=}  (sorted in place, case-insensitive)")
print(f"{sorted(dish_names, key=len, reverse=True)=}")
dish_names.reverse()
print(f"{dish_names=}  (reversed in place)")
backwards_iterator = reversed(dish_names)
print(
    f"{type(backwards_iterator).__name__=}, "
    f"{list(backwards_iterator)=}"
)
print(f"{sorted('dosa')=}, {sorted({3, 1, 2})=}  (any iterable)")
```

```text
sorted_copy=['Idli', 'Upma', 'dosa', 'vada'],
  dish_names=['vada', 'Idli', 'dosa', 'Upma']  (original untouched)
dish_names.sort(key=str.lower)=None  (sort() returns None)
dish_names=['dosa', 'Idli', 'Upma', 'vada']  (sorted in place, case-insensitive)
sorted(dish_names, key=len, reverse=True)=['dosa', 'Idli', 'Upma', 'vada']
dish_names=['vada', 'Upma', 'Idli', 'dosa']  (reversed in place)
type(backwards_iterator).__name__='list_reverseiterator',
  list(backwards_iterator)=['dosa', 'Idli', 'Upma', 'vada']
sorted('dosa')=['a', 'd', 'o', 's'], sorted({3, 1, 2})=[1, 2, 3]  (any iterable)
```

Two details are worth noticing. The plain `sorted(dish_names)` put `'Idli'`
and `'Upma'` first, because strings compare by code point and uppercase
letters come before lowercase ones. And `sorted(..., key=len, reverse=True)`
left the four-letter names in their existing order: they all have the same
key, and Python's sort is stable even when reversed (1.5.4).

### Copying: `copy()`, `[:]`, `list(...)`

`items.copy()`, `items[:]` and `list(items)` all make a **shallow** copy: a new
list object whose slots point to the *same* item objects. Adding to or
removing from the copy does not affect the original, but mutating a shared
inner object (here, a nested list) shows up through both. This is exactly
what JavaScript's `[...arr]` and `arr.slice()` do. Unit 1.7 covers deep
copies.

```python
menu_rows = [["idli", 40], ["dosa", 60]]
copy_by_method = menu_rows.copy()
copy_by_slice = menu_rows[:]
copy_by_constructor = list(menu_rows)
print(f"{copy_by_method is menu_rows=}, {copy_by_slice == menu_rows=}")
copy_by_method.append(["vada", 30])
print(
    f"{len(menu_rows)=}, {len(copy_by_method)=}"
    "  (outer lists are independent)"
)
copy_by_constructor[0][1] = 45
print(
    f"{menu_rows[0]=}"
    "  (inner lists are shared: the original changed too)"
)
print(f"{copy_by_slice[0] is menu_rows[0]=}")
```

```text
copy_by_method is menu_rows=False, copy_by_slice == menu_rows=True
len(menu_rows)=2, len(copy_by_method)=3  (outer lists are independent)
menu_rows[0]=['idli', 45]  (inner lists are shared: the original changed too)
copy_by_slice[0] is menu_rows[0]=True
```

### Slice assignment, extended slices and starred unpacking

**Slice assignment** is Python's answer to JavaScript's `splice`. Assigning an
iterable to a slice replaces those positions with the new items, and the
lengths may differ, so the list can grow or shrink. Assigning to an **empty**
slice `items[i:i]` inserts without replacing anything.

**Extended slices** (slices with a step, such as `items[::2]`) select a fixed
set of scattered positions, so the assigned iterable must have **exactly** as
many items as the slice selects; otherwise Python raises `ValueError`.

**Starred unpacking** (PEP 3132) assigns the items of a sequence to several
names, with one starred name collecting "everything else" into a list. The
star can appear at the start, in the middle or at the end.

```python
seat_row = ["A1", "A2", "A3", "A4", "A5"]
seat_row[1:3] = ["B2"]
print(f"{seat_row=}  (two items replaced by one)")
seat_row[1:1] = ["NEW1", "NEW2"]
print(f"{seat_row=}  (empty slice: pure insert)")
seat_row[::2] = ["x", "y", "z"]
print(f"{seat_row=}  (extended slice, same length)")
try:
    seat_row[::2] = ["only one"]
except ValueError as error:
    print(f"{type(error).__name__}: {error}")
first_seat, *other_seats = seat_row
*_, last_seat = seat_row
front_seat, *middle_seats, back_seat = seat_row
print(f"{first_seat=}, {other_seats=}, {last_seat=}")
print(f"{front_seat=}, {middle_seats=}, {back_seat=}")
```

```text
seat_row=['A1', 'B2', 'A4', 'A5']  (two items replaced by one)
seat_row=['A1', 'NEW1', 'NEW2', 'B2', 'A4', 'A5']  (empty slice: pure insert)
seat_row=['x', 'NEW1', 'y', 'B2', 'z', 'A5']  (extended slice, same length)
ValueError: attempt to assign sequence of size 1 to extended slice of size 3
first_seat='x', other_seats=['NEW1', 'y', 'B2', 'z', 'A5'], last_seat='A5'
front_seat='x', middle_seats=['NEW1', 'y', 'B2', 'z'], back_seat='A5'
```

`*_` is a common idiom: `_` is an ordinary name that, by convention, means
"I do not need this value".

### Key points

| Idea | Takeaway |
| --- | --- |
| Mutating methods | Return `None` |
| `append` vs `extend` | One object vs every item |
| `+=` vs `+` | In place (any iterable) vs new list |
| `remove`, `index` | Raise `ValueError` if absent |
| `pop` | Returns the item; `IndexError` if empty |
| `sort()` vs `sorted()` | In place vs new list |
| Copies | `copy()`, `[:]`, `list()` are shallow |
| Slice assignment | Can change the length |
| Extended slice | Lengths must match |
| `first, *rest = items` | Star collects a list |

## 1.5.4 Sorting in depth

### Timsort and stability

Python sorts with **Timsort**, an algorithm Tim Peters wrote for CPython in
2002 and later adopted by Java and V8. It is a merge sort that first scans the
data for runs that are already in order (ascending or strictly descending)
and then merges those runs. Real-world data is often partly sorted, so
Timsort frequently runs close to O(n); its worst case is O(n log n). Since
Python 3.11, CPython decides which runs to merge using the *powersort*
strategy, which makes merging a little more efficient without changing the
results.

Timsort is **stable**: items whose keys compare equal keep their original
relative order. JavaScript's `Array.prototype.sort` has been required to be
stable only since ES2019; Python's sort has guaranteed it for two decades, and
idiomatic Python code relies on it.

Stability is what makes **multi-pass sorting** work. To sort by several keys,
sort by the *least* important key first, then by the next one, and finish
with the *most* important key. Each later pass groups items by its own key
but, among ties, preserves the order the earlier passes produced.

```python
customer_orders = [
    ("Ravi", "Pune"),
    ("Asha", "Delhi"),
    ("Meena", "Pune"),
    ("John", "Delhi"),
]
print(f"{sorted(customer_orders, key=lambda order: order[1])=}")
print("  ^ within each city the original order (Ravi before Meena) is kept")
by_name = sorted(customer_orders, key=lambda order: order[0])
by_city_then_name = sorted(by_name, key=lambda order: order[1])
print(f"{by_city_then_name=}")
```

```text
sorted(customer_orders, key=lambda order: order[1])=[('Asha', 'Delhi'),
  ('John', 'Delhi'), ('Ravi', 'Pune'), ('Meena', 'Pune')]
  ^ within each city the original order (Ravi before Meena) is kept
by_city_then_name=[('Asha', 'Delhi'), ('John', 'Delhi'), ('Meena', 'Pune'),
  ('Ravi', 'Pune')]
```

### Key functions

JavaScript sorts with a *comparator*, `(a, b) => a - b`, that is called many
times per item. Python sorts with a **key function** instead: `key` is called
**once per item**, Python remembers the results, and the items are ordered by
comparing those keys. That is both faster and easier to write. The common key
functions are:

- `key=str.lower` for case-insensitive ordering of strings.
- `operator.itemgetter(1)` returns `item[1]`; `itemgetter(2, 0)` returns the
  tuple `(item[2], item[0])`. It works on anything indexable: tuples, lists,
  dicts (with a key) and named tuples.
- `operator.attrgetter("price")` returns `item.price`, and works on any
  object with attributes.
- **Tuple keys** compare element by element, so `key=lambda p: (p.a, p.b)`
  sorts by `a` and then by `b`. For **mixed directions**, negate the numeric
  parts: `key=lambda p: (-p.rating, p.price)` means rating descending, then
  price ascending.

> **Note:** strings cannot be negated, so a tuple key cannot sort one string
> field ascending and another descending. Use multi-pass sorting instead, with
> `reverse=True` on the pass that should run backwards.

The products below use `NamedTuple`, which 1.5.6 covers properly; for now it
is simply a record whose fields can be read by position or by name.

```python
class Product(NamedTuple):
    """A product in a catalogue."""

    name: str
    price: int
    rating: float


catalogue = [
    Product("pen", 20, 4.2),
    Product("Notebook", 60, 4.8),
    Product("eraser", 5, 4.2),
    Product("Bag", 900, 4.8),
]
print(f"{sorted(['pen', 'Notebook', 'eraser'])=}")
print(f"{sorted(['pen', 'Notebook', 'eraser'], key=str.lower)=}")
by_price = sorted(catalogue, key=operator.itemgetter(1))
print([product.name for product in by_price])
print(sorted(catalogue, key=operator.itemgetter(2, 0))[:2])
by_rating = sorted(catalogue, key=operator.attrgetter("rating"))
print([product.name for product in by_rating])
best_then_cheapest = sorted(
    catalogue, key=lambda product: (-product.rating, product.price)
)
print(
    [
        (product.name, product.rating, product.price)
        for product in best_then_cheapest
    ]
)
```

```text
sorted(['pen', 'Notebook', 'eraser'])=['Notebook', 'eraser', 'pen']
sorted(['pen', 'Notebook', 'eraser'], key=str.lower)=['eraser', 'Notebook', 'pen']
['eraser', 'pen', 'Notebook', 'Bag']
[Product(name='eraser', price=5, rating=4.2), Product(name='pen', price=20,
  rating=4.2)]
['pen', 'eraser', 'Notebook', 'Bag']
[('Notebook', 4.8, 60), ('Bag', 4.8, 900), ('eraser', 4.2, 5), ('pen', 4.2, 20)]
```

Read the outputs line by line. `itemgetter(1)` sorted by price. `itemgetter(2,
0)` sorted by rating and then by name, which put `'eraser'` before `'pen'`
among the 4.2-rated products. `attrgetter("rating")` sorted by rating alone,
and stability kept `'pen'` before `'eraser'` and `'Notebook'` before `'Bag'`,
their original order. The last line shows the negated tuple key: best rating
first, cheapest first within a rating.

### JavaScript bridge: numbers are not strings

JavaScript's default `sort()` (with no comparator) converts every item to a
string and compares the strings, so `[10, 9, 1, 100].sort()` gives
`[1, 10, 100, 9]`. Python compares the values themselves. When the values are
of unrelated types, such as `int` and `str`, Python refuses to guess and
raises `TypeError`; if you really want a string ordering, say so with
`key=str`.

```python
print(f"{sorted([10, 9, 1, 100])=}")
print(f"{sorted(['10', '9', '1', '100'])=}  (what JS does to numbers)")
try:
    sorted([3, "2", 1])
except TypeError as error:
    print(f"{type(error).__name__}: {error}")
print(f"{sorted([3, '2', 1], key=str)=}  (an explicit key makes it work)")
```

```text
sorted([10, 9, 1, 100])=[1, 9, 10, 100]
sorted(['10', '9', '1', '100'])=['1', '10', '100', '9']  (what JS does to numbers)
TypeError: '<' not supported between instances of 'str' and 'int'
sorted([3, '2', 1], key=str)=[1, '2', 3]  (an explicit key makes it work)
```

> **Note:** `functools.cmp_to_key` wraps an old-style comparator so it can be
> used as a key, which is handy when porting a JavaScript comparator. A key
> function is almost always simpler.

### Key points

| Idea | Takeaway |
| --- | --- |
| Algorithm | Timsort: O(n) on sorted runs, O(n log n) worst |
| Stability | Equal keys keep their original order |
| Multi-pass | Least important key first |
| `key=` | Called once per item |
| `itemgetter`, `attrgetter` | Fast ready-made key functions |
| Mixed directions | Negate numbers; multi-pass for strings |
| Mixed types | `TypeError` unless you pass `key=` |

## 1.5.5 Tuples (`tuple`)

A tuple is an **immutable sequence**: once built, its length and the objects
it refers to never change. Use a tuple when the *positions* mean something,
such as `(latitude, longitude)` or a database row, and a list when you have a
variable number of items of the same kind.

### The comma makes the tuple

The single most surprising rule about tuples is that **the comma makes the
tuple, not the parentheses**. Parentheses only group, as they do in
arithmetic, so `(42)` is just the integer 42, while `42,` and `(42,)` are
one-item tuples. The one exception is `()`, the empty tuple.

Writing several values separated by commas **packs** them into a tuple.
Assigning a tuple (or any iterable) to several names **unpacks** it. Unpacking
can be **nested**, mirroring the shape of the data, and **starred**, with one
name collecting the rest into a list. Because the right-hand side is packed
completely before anything is assigned, `a, b = b, a` swaps two variables
without a temporary.

```python
not_a_tuple = (42)  # fmt: skip
one_item_tuple = 42,  # fmt: skip
also_one_item = (42,)
empty_tuple = ()
print(
    f"{type(not_a_tuple).__name__=}, {one_item_tuple=}, "
    f"{also_one_item=}, {empty_tuple=}"
)
office_location = 12.97, 77.59
latitude, longitude = office_location
print(f"{office_location=}, {latitude=}, {longitude=}")
city_name, (city_latitude, city_longitude) = ("Bengaluru", (12.97, 77.59))
print(f"{city_name=}, {city_latitude=}, {city_longitude=}")
top_scorer, *other_scorers = ("Asha", "Ravi", "Meena")
print(
    f"{top_scorer=}, {other_scorers=}"
    "  (the starred name is always a list)"
)
home_team, away_team = "India", "Australia"
home_team, away_team = away_team, home_team
print(f"{home_team=}, {away_team=}")
```

```text
type(not_a_tuple).__name__='int', one_item_tuple=(42,), also_one_item=(42,),
  empty_tuple=()
office_location=(12.97, 77.59), latitude=12.97, longitude=77.59
city_name='Bengaluru', city_latitude=12.97, city_longitude=77.59
top_scorer='Asha', other_scorers=['Ravi', 'Meena']  (the starred name is
  always a list)
home_team='Australia', away_team='India'
```

> **Note:** the two `# fmt: skip` comments stop the code formatter (Ruff) from
> rewriting `(42)` as `42` and `42,` as `(42,)`, which would hide the point.

> **Warning:** a stray trailing comma creates a tuple by accident:
> `timeout = 30,` makes `timeout` the tuple `(30,)`, and the error only shows
> up later when you try to do arithmetic with it.

### Methods, hashing and tuples as dict keys

Tuples have only two methods, `count` and `index`, which behave exactly like
the list versions; there is nothing else, because every other list method
mutates.

Immutability buys one big feature: a tuple can be **hashable**, which means
it can be a dictionary key or a set member. A tuple's hash is computed from
the hashes of its items, so a tuple is hashable **only if all its items
are**. A tuple of strings and numbers can key a dict; a tuple containing a
list cannot. This is how Python does composite keys such as
`(country, product)`, something JavaScript objects cannot do without joining
the parts into a string.

```python
match_ratings = (5, 4, 5, 3, 5)
print(f"{match_ratings.count(5)=}, {match_ratings.index(3)=}")
print(f"{hash((1, 'a', (2, 3))) == hash((1, 'a', (2, 3)))=}")
try:
    hash((1, [2, 3]))
except TypeError as error:
    print(f"{type(error).__name__}: {error}")
sales_by_country_and_product = {("IN", "dosa"): 1200, ("US", "dosa"): 150}
print(f"{sales_by_country_and_product[('IN', 'dosa')]=}")
print(
    f"{isinstance((1, 'a'), Hashable)=}, "
    f"{isinstance((1, []), Hashable)=}"
)
print("  ^ the Hashable ABC checks the type only; hash() checks the items")
```

```text
match_ratings.count(5)=3, match_ratings.index(3)=3
hash((1, 'a', (2, 3))) == hash((1, 'a', (2, 3)))=True
TypeError: unhashable type: 'list'
sales_by_country_and_product[('IN', 'dosa')]=1200
isinstance((1, 'a'), Hashable)=True, isinstance((1, []), Hashable)=True
  ^ the Hashable ABC checks the type only; hash() checks the items
```

> **Warning:** `isinstance(value, Hashable)` only asks whether the *type*
> defines `__hash__`. Every tuple passes that test, even one holding a list.
> The only reliable test is to call `hash(value)` and catch `TypeError`.

### Under the hood: tuples are smaller and built once

A list has a header plus a separate, over-allocated slot array. A tuple stores
its item pointers **inline**, right after its header, in a single allocation
of exactly the right size, with no spare capacity. It is therefore smaller
than the equivalent list. CPython also keeps a free list of small tuples so
that creating and destroying them is cheap.

Second, a tuple whose items are all constants is built **once, at compile
time**, and stored in the code object's constants. The `dis` module shows
this: the tuple assignment is a single `LOAD_CONST`, while the list version
has to build a new list (`BUILD_LIST` plus `LIST_EXTEND`) every time the line
runs.

```python
show_size("tuple (1, 2, 3)", (1, 2, 3))
show_size("list  [1, 2, 3]", [1, 2, 3])
appended_list = []
for number in (1, 2, 3):
    appended_list.append(number)
show_size("list built by append", appended_list)
dis.dis(compile("rgb_tuple = (255, 153, 51)", "<tuple>", "exec"))
dis.dis(compile("rgb_list = [255, 153, 51]", "<list>", "exec"))
```

```text
tuple (1, 2, 3): 72 bytes, type=tuple, id=140266921912544
list  [1, 2, 3]: 88 bytes, type=list, id=140266922037440
list built by append: 88 bytes, type=list, id=140266922042368
  0           RESUME                   0

  1           LOAD_CONST               1 ((255, 153, 51))
              STORE_NAME               0 (rgb_tuple)
              LOAD_COMMON_CONSTANT     7 (None)
              RETURN_VALUE
  0           RESUME                   0

  1           BUILD_LIST               0
              LOAD_CONST               1 ((255, 153, 51))
              LIST_EXTEND              1
              STORE_NAME               0 (rgb_list)
              LOAD_COMMON_CONSTANT     7 (None)
              RETURN_VALUE
```

> **Note:** the `id` values differ on every run, the byte sizes depend on the
> Python version and platform, and bytecode instruction names change between
> versions (the output above is from Python 3.15).

### Predict the output: the `t[0] += [1]` puzzle

Tuples are immutable, but the objects *inside* them need not be. This classic
puzzle shows what happens when those two facts collide.

```python
pair_of_lists = ([1, 2], "x")
try:
    pair_of_lists[0] += [3]
except TypeError as error:
    print(type(error).__name__)
print(pair_of_lists)
```

<details><summary>Answer</summary>

```text
TypeError
([1, 2, 3], 'x')
```

The statement **both** raises and mutates. `pair_of_lists[0] += [3]` first
reads slot 0 and runs `list.__iadd__` on it, which extends the inner list in
place and succeeds. Then Python tries to store the result back into slot 0 of
the tuple, which fails because tuples do not support item assignment. By the
time the `TypeError` is raised, the inner list has already changed.

</details>

The bytecode shows the two steps: an in-place add (`BINARY_OP` with `+=`)
followed by `STORE_SUBSCR`, and the error comes from the store.

```python
dis.dis(compile("pair_of_lists[0] += [3]", "<puzzle>", "exec"))
```

```text
  0           RESUME                   0

  1           LOAD_NAME                0 (pair_of_lists)
              LOAD_SMALL_INT           0
              COPY                     2
              COPY                     2
              BINARY_OP               26 ([])
              LOAD_SMALL_INT           3
              BUILD_LIST               1
              BINARY_OP               13 (+=)
              SWAP                     3
              SWAP                     2
              STORE_SUBSCR
              LOAD_COMMON_CONSTANT     7 (None)
              RETURN_VALUE
```

> **Note:** to change the inner list without the error, mutate it directly:
> `pair_of_lists[0].append(3)` or `pair_of_lists[0].extend([3])`. These never
> try to assign to the tuple.

### Key points

| Idea | Takeaway |
| --- | --- |
| Creation | The comma makes it: `(42,)` |
| Unpacking | Nested and starred; `a, b = b, a` |
| Methods | Only `count` and `index` |
| Hashable | Only if every item is |
| Dict keys | Composite keys like `("IN", "dosa")` |
| Memory | Inline pointers, no spare slots |
| Constants | Built once at compile time |
| `t[0] += [x]` | Mutates *and* raises `TypeError` |

## 1.5.6 Named tuples

Plain tuples are compact but opaque: `row[2]` says nothing about what the
third field means. A **named tuple** is a tuple subclass whose positions also
have names, so you can write `row.status_code`. It is still immutable, still
unpacks, still compares and hashes like a tuple, and costs no more memory than
a plain tuple, because the names live on the class, not on each instance.
Think of it as a frozen JavaScript object literal with a fixed shape.

### `collections.namedtuple`

`collections.namedtuple(type_name, field_names)` builds a new class at
runtime. The class comes with a few helpers whose names start with an
underscore. The underscore is there to avoid clashing with your field names;
these methods are documented and public.

| API | What it does |
| --- | --- |
| `_fields` | tuple of field names |
| `_make(iterable)` | build an instance from any iterable |
| `_asdict()` | a `dict` of field name → value |
| `_replace(**changes)` | a modified **copy** |

`_make` is the natural way to build a record from a CSV or database row, and
`_replace` is the immutable-update pattern (like `{...point, longitude: 77.6}`
in JavaScript): it returns a new instance and leaves the original alone.

```python
GeoPoint = namedtuple("GeoPoint", ["latitude", "longitude"])
office_point = GeoPoint(12.97, 77.59)
print(f"{office_point=}, {office_point.latitude=}, {office_point[1]=}")
point_latitude, point_longitude = office_point
print(f"{GeoPoint._fields=}")
print(f"{GeoPoint._make(['28.61', '77.21'])=}  (values are not converted)")
print(f"{office_point._asdict()=}")
moved_point = office_point._replace(longitude=77.60)
print(f"{moved_point=}, {office_point=}  (original unchanged)")
try:
    office_point.latitude = 0.0
except AttributeError as error:
    print(f"{type(error).__name__}: {error}")
```

```text
office_point=GeoPoint(latitude=12.97, longitude=77.59),
  office_point.latitude=12.97, office_point[1]=77.59
GeoPoint._fields=('latitude', 'longitude')
GeoPoint._make(['28.61', '77.21'])=GeoPoint(latitude='28.61',
  longitude='77.21')  (values are not converted)
office_point._asdict()={'latitude': 12.97, 'longitude': 77.59}
moved_point=GeoPoint(latitude=12.97, longitude=77.6),
  office_point=GeoPoint(latitude=12.97, longitude=77.59)  (original unchanged)
AttributeError: can't set attribute
```

> **Warning:** named tuples do not validate or convert their values. The type
> hints of `typing.NamedTuple` (below) are not checked at runtime either:
> `_make(['28.61', '77.21'])` happily stores strings. Convert values yourself
> before building the record.

### `typing.NamedTuple`

`typing.NamedTuple` is the class syntax for the same thing, and the better
choice for new code. Fields are declared with type annotations, fields can
have **defaults** (fields with defaults must come after fields without), and
the class can have a docstring and **methods**. The result is still a real
tuple subclass, so it equals a plain tuple with the same items.

`LogEntry` below reappears in 1.5.11 and in the Phase 1 project.

```python
class LogEntry(NamedTuple):
    """One parsed line of an access log."""

    level: str
    message: str
    status_code: int = 200

    def is_error(self) -> bool:
        """Return True for ERROR entries and 5xx status codes."""
        return self.level == "ERROR" or self.status_code >= 500


placed_entry = LogEntry("INFO", "order placed")
failed_entry = LogEntry("WARNING", "gateway timeout", 504)
print(f"{placed_entry=}, {placed_entry.is_error()=}")
print(f"{failed_entry.is_error()=}, {LogEntry._field_defaults=}")
print(
    f"{isinstance(placed_entry, tuple)=}, "
    f"{placed_entry == ('INFO', 'order placed', 200)=}"
)
```

```text
placed_entry=LogEntry(level='INFO', message='order placed', status_code=200),
  placed_entry.is_error()=False
failed_entry.is_error()=True, LogEntry._field_defaults={'status_code': 200}
isinstance(placed_entry, tuple)=True,
  placed_entry == ('INFO', 'order placed', 200)=True
```

> **Note:** because a named tuple *is* a tuple, it also compares equal to any
> other tuple with the same items, including a different named tuple type
> with different field names. When that matters, or when you need mutable
> fields, use a dataclass (covered later in the course).

### Key points

| Idea | Takeaway |
| --- | --- |
| Named tuple | A tuple with named positions |
| Memory | Same as a plain tuple |
| `_make` | Build from any iterable |
| `_asdict` | Convert to a `dict` |
| `_replace` | Modified copy; original unchanged |
| `typing.NamedTuple` | Class syntax, defaults, methods |
| Validation | None: hints are not enforced |

## 1.5.7 Ranges (`range`)

A `range` represents an arithmetic progression of integers. It is a **lazy,
immutable sequence**: it stores only three integers, `start`, `stop` and
`step`, and computes items on demand. Its memory use therefore never depends
on its length, and `len`, indexing, slicing and `in` (for an `int`) are all
computed with arithmetic in **O(1)**, without generating a single item.
Slicing a range returns another range. Negative steps count down, and `stop`
is always excluded, just as in slicing.

This is very different from JavaScript, where producing `0..n` usually means
building an array with `Array.from` or a `for` loop. In Python 3, `range` is
not a list (in Python 2 it was), and you call `list(range(...))` only when you
really need the materialised items.

```python
page_offsets = range(0, 95, 20)
print(f"{page_offsets=}, {list(page_offsets)=}")
print(f"{list(range(10, 0, -3))=}, {list(range(5, 0, -1))=}")
huge_range = range(0, 10**18, 7)
print(f"{len(huge_range)=:,}")
print(f"{7 * 10**15 in huge_range=}, {7 * 10**15 + 1 in huge_range=}")
print(f"{huge_range[10**12]=:,}, {huge_range[-1]=:,}")
print(f"{huge_range[::2]=}  (slicing returns another range)")
print(
    f"{sys.getsizeof(huge_range)=} bytes, "
    f"{sys.getsizeof(range(3))=} bytes"
)
try:
    page_offsets[0] = 5
except TypeError as error:
    print(f"{type(error).__name__}: {error}")
```

```text
page_offsets=range(0, 95, 20), list(page_offsets)=[0, 20, 40, 60, 80]
list(range(10, 0, -3))=[10, 7, 4, 1], list(range(5, 0, -1))=[5, 4, 3, 2, 1]
len(huge_range)=142,857,142,857,142,858
7 * 10**15 in huge_range=True, 7 * 10**15 + 1 in huge_range=False
huge_range[10**12]=7,000,000,000,000, huge_range[-1]=999,999,999,999,999,999
huge_range[::2]=range(0, 1000000000000000006, 14)  (slicing returns another
  range)
sys.getsizeof(huge_range)=48 bytes, sys.getsizeof(range(3))=48 bytes
TypeError: 'range' object does not support item assignment
```

A range with 142 857 142 857 142 858 items answers `len`, `in` and indexing
instantly and occupies 48 bytes, the same as `range(3)`. For membership,
CPython checks that the number is an `int`, lies between `start` and `stop`,
and that `(x - start) % step == 0`.

> **Warning:** the O(1) membership test only applies to `int` (and `bool`)
> values. For any other type, such as a float, `x in some_range` falls back to
> a linear scan comparing each item with `==`.

### Key points

| Idea | Takeaway |
| --- | --- |
| Storage | Only `start`, `stop`, `step` |
| Cost | O(1) `len`, `in`, index, slice |
| Slicing | Returns another `range` |
| Direction | Negative step counts down |
| `stop` | Always excluded |
| Immutable | No item assignment |

## 1.5.8 Arrays (`array.array`)

A list of floats is surprisingly heavy. Each slot holds an 8-byte pointer,
and each pointer refers to a separate `float` object of 24 bytes (an object
header plus the 8-byte C `double`). Storing one number costs about 32 bytes,
plus the memory allocator's overhead.

`array.array` from the standard library stores **raw machine values of a
single type** in one contiguous block, like a JavaScript typed array
(`Float64Array`). You choose the type with a *type code*: `"d"` is a C
`double` (8 bytes), `"f"` a C `float` (4 bytes), `"i"` a C `int`, and so on.
The array behaves like a list (indexing, slicing, `append`, `extend`), but it
refuses values of the wrong type. Use it for long numeric series when memory
matters. NumPy, covered later in the course, uses the same storage idea and
adds fast vectorised maths.

```python
reading_count = 100_000
readings_list = [
    reading_index * 0.5 for reading_index in range(reading_count)
]
readings_array = array.array("d", readings_list)
list_total_bytes = sys.getsizeof(readings_list) + sum(
    sys.getsizeof(reading) for reading in readings_list
)
array_total_bytes = sys.getsizeof(readings_array)
print(f"list of floats: {list_total_bytes:>10,} bytes (list + float objects)")
print(f"array('d'):     {array_total_bytes:>10,} bytes")
print(f"ratio: {list_total_bytes / array_total_bytes:.1f}x")
print(
    f"{readings_array.typecode=}, {readings_array.itemsize=}, "
    f"{readings_array[:3]=}"
)
print(f"append a str: {raised_error_name(lambda: readings_array.append('x'))}")
```

```text
list of floats:  3,200,984 bytes (list + float objects)
array('d'):        800,080 bytes
ratio: 4.0x
readings_array.typecode='d', readings_array.itemsize=8,
  readings_array[:3]=array('d', [0.0, 0.5, 1.0])
append a str: TypeError
```

> **Note:** the byte counts depend on the Python version and platform, but the
> roughly fourfold saving for 8-byte doubles is typical. Reading an item from
> an array creates a new `float` object each time, so arrays save memory
> rather than speed up pure-Python loops.

### Key points

| Idea | Takeaway |
| --- | --- |
| Storage | Raw values in one block |
| Type code | `"d"` double, `"f"` float, `"i"` int |
| Memory | About 4x smaller than a list of floats |
| Type safety | Wrong type raises `TypeError` |
| JS equivalent | `Float64Array` |

## 1.5.9 Method reference — `list`

This section is the complete `list` reference. The tables are split by group
so each fits a phone screen. Every example starts from a fresh
`nums = [3, 1, 2]` and the Result column shows the list afterwards (for
methods that return `None`) or the value returned.

### Adding

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `append(x)` | add one item at the end | `nums.append(4)` | `[3, 1, 2, 4]` |
| `extend(it)` / `+= it` | add every item of an iterable | `nums.extend((4, 5))` | `[3, 1, 2, 4, 5]` |
| `insert(i, x)` | insert before index `i` | `nums.insert(0, 9)` | `[9, 3, 1, 2]` |

### Removing

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `remove(x)` | delete first item equal to `x` | `nums.remove(1)` | `[3, 2]` |
| `pop()` / `pop(i)` | remove and return last / i-th | `nums.pop(0)` | `3`, leaves `[1, 2]` |
| `clear()` | remove every item | `nums.clear()` | `[]` |
| `del items[i]`, `del items[a:b]` | delete by index or slice | `del nums[:2]` | `[2]` |

### Searching

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `index(x[, start[, end]])` | position of first `x` | `nums.index(2)` | `2` |
| `count(x)` | number of items equal to `x` | `[1, 1, 2].count(1)` | `2` |
| `x in items` | membership by `==` | `2 in nums` | `True` |

### Ordering and copying

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `sort(*, key, reverse)` | stable in-place sort | `nums.sort(reverse=True)` | `[3, 2, 1]` |
| `reverse()` | reverse in place | `nums.reverse()` | `[2, 1, 3]` |
| `copy()` | shallow copy (like `[:]`) | `nums.copy()` | new `[3, 1, 2]` |

### Indexing, slicing, operators and built-ins

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `items[i]`, `items[i] = x` | read / replace by index | `nums[-1]` | `2` |
| `items[a:b:c]`, `items[a:b] = it` | slice copy / replace | `nums[::-1]` | `[2, 1, 3]` |
| `items + other`, `items * n` | concatenate / repeat | `nums + [4]` | `[3, 1, 2, 4]` |
| `len`, `min`, `max`, `sum`, … | built-ins on lists | `sum(nums), max(nums)` | `(6, 3)` |
| `==`, `<` | element-wise, lexicographic | `[1, 2] < [1, 3]` | `True` |

The built-ins row covers `len`, `min`, `max`, `sum`, `sorted`, `reversed`,
`enumerate`, `any` and `all`.

### Returns and cost

| Method / operation | Returns | Cost |
| --- | --- | --- |
| `append(x)` | `None` | O(1) amortized |
| `extend(it)` / `+= it` | `None` / same list | O(k) |
| `insert(i, x)` | `None` | O(n) |
| `remove(x)` | `None` (`ValueError` if absent) | O(n) |
| `pop()` / `pop(i)` | item (`IndexError` if empty) | O(1) / O(n) |
| `clear()` | `None` | O(n) |
| `index(x[, start[, end]])` | `int` (`ValueError` if absent) | O(n) |
| `count(x)` | `int` | O(n) |
| `sort(*, key, reverse)` | `None` | O(n log n) |
| `reverse()` | `None` | O(n) |
| `copy()` | new `list` | O(n) |
| `items[i]`, `items[i] = x` | item / — | O(1) |
| `items[a:b:c]`, `items[a:b] = it` | new `list` / — | O(k) |
| `del items[i]`, `del items[a:b]` | — | O(n) |
| `x in items` | `bool` | O(n) |
| `items + other`, `items * n` | new `list` | O(n + m) |
| built-ins | varies | O(n) |
| `==`, `<` | `bool` | O(n) |

The rest of this section demonstrates every row, one at a time.

### `append(x)`

One item at the end; the call itself returns `None`.

```python
shopping_list = ["rice"]
append_result = shopping_list.append("dal")
print(f"{shopping_list=}, {append_result=}")
```

```text
shopping_list=['rice', 'dal'], append_result=None
```

### `extend(iterable)` / `+= iterable`

Every item of any iterable, in place. A string is an iterable of characters,
which is a common source of surprise.

```python
shopping_list = ["rice"]
shopping_list.extend(("dal", "ghee"))
list_before_augmented_add = shopping_list
shopping_list += "ab"
print(f"{shopping_list=}  (a str is an iterable of characters)")
print(f"{shopping_list is list_before_augmented_add=}")
```

```text
shopping_list=['rice', 'dal', 'ghee', 'a', 'b']  (a str is an iterable of
  characters)
shopping_list is list_before_augmented_add=True
```

> **Warning:** `items.extend("tea")` adds `'t'`, `'e'`, `'a'`. To add a whole
> string, use `append("tea")` or `extend(["tea"])`.

### `insert(i, x)`

Inserts before index `i`. An index past the end appends, and a negative index
counts from the end, so `insert(-1, x)` puts `x` *before* the last item.

```python
shopping_list = ["rice", "ghee"]
shopping_list.insert(1, "dal")
shopping_list.insert(0, "salt")
shopping_list.insert(100, "sugar")
shopping_list.insert(-1, "tea")
print(f"{shopping_list=}")
```

```text
shopping_list=['salt', 'rice', 'dal', 'ghee', 'tea', 'sugar']
```

### `remove(x)`

Removes the first equal item; raises `ValueError` if there is none.

```python
shopping_list = ["rice", "dal", "rice"]
shopping_list.remove("rice")
print(f"{shopping_list=}")
print(
    "remove missing: "
    f"{raised_error_name(lambda: shopping_list.remove('oil'))}"
)
```

```text
shopping_list=['dal', 'rice']
remove missing: ValueError
```

### `pop()` / `pop(i)`

Removes and returns the last item or the item at index `i`.

```python
shopping_list = ["rice", "dal", "ghee", "salt"]
print(
    f"{shopping_list.pop()=}, {shopping_list.pop(0)=}, "
    f"{shopping_list=}"
)
print(f"pop from empty: {raised_error_name(lambda: [].pop())}")
print(f"pop bad index: {raised_error_name(lambda: ['rice'].pop(5))}")
```

```text
shopping_list.pop()='salt', shopping_list.pop(0)='rice',
  shopping_list=['dal', 'ghee']
pop from empty: IndexError
pop bad index: IndexError
```

### `clear()`

Empties the list in place, so every alias sees the change. Compare
`shopping_list = []`, which would rebind only one name and leave the alias
holding the old items.

```python
shopping_list = ["rice", "dal"]
same_list_alias = shopping_list
shopping_list.clear()
print(f"{shopping_list=}, {same_list_alias=}")
```

```text
shopping_list=[], same_list_alias=[]
```

### `index(x[, start[, end]])`

The position of the first match inside the window `[start:end]`.

```python
shopping_list = ["rice", "dal", "ghee", "dal"]
print(f"{shopping_list.index('dal')=}, {shopping_list.index('dal', 2)=}")
print(
    "not in window: "
    f"{raised_error_name(lambda: shopping_list.index('rice', 1, 3))}"
)
```

```text
shopping_list.index('dal')=1, shopping_list.index('dal', 2)=3
not in window: ValueError
```

### `count(x)`

How many items are `==` to `x`. String comparison is case-sensitive, so
`'Rice'` is not counted.

```python
shopping_list = ["rice", "dal", "rice", "Rice"]
print(f"{shopping_list.count('rice')=}, {shopping_list.count('oil')=}")
```

```text
shopping_list.count('rice')=2, shopping_list.count('oil')=0
```

### `sort(*, key=None, reverse=False)`

Stable and in place. The `*` in the signature means `key` and `reverse` are
**keyword-only**: passing the key positionally raises `TypeError`.

```python
shopping_list = ["ghee", "Rice", "dal", "salt"]
shopping_list.sort()
print(f"{shopping_list=}  (uppercase first)")
shopping_list.sort(key=str.lower, reverse=True)
print(f"{shopping_list=}")
print(
    "positional key: "
    f"{raised_error_name(lambda: shopping_list.sort(str.lower))}"
)
```

```text
shopping_list=['Rice', 'dal', 'ghee', 'salt']  (uppercase first)
shopping_list=['salt', 'Rice', 'ghee', 'dal']
positional key: TypeError
```

### `reverse()`

Reverses in place and returns `None`.

```python
shopping_list = ["rice", "dal", "ghee"]
print(f"{shopping_list.reverse()=}, {shopping_list=}")
```

```text
shopping_list.reverse()=None, shopping_list=['ghee', 'dal', 'rice']
```

### `copy()`

A new list holding the same item objects (a shallow copy).

```python
shopping_list = ["rice", ["dal", "ghee"]]
copied_list = shopping_list.copy()
print(f"{copied_list == shopping_list=}, {copied_list is shopping_list=}")
print(f"{copied_list[1] is shopping_list[1]=}  (shallow)")
```

```text
copied_list == shopping_list=True, copied_list is shopping_list=False
copied_list[1] is shopping_list[1]=True  (shallow)
```

### `items[i]`, `items[i] = x`

Read or replace one slot; negative indexes count from the end. Unlike
JavaScript, assigning past the end does **not** grow the list (no "holes"):
it raises `IndexError`.

```python
shopping_list = ["rice", "dal", "ghee"]
print(f"{shopping_list[0]=}, {shopping_list[-1]=}")
shopping_list[-1] = "butter"
print(f"{shopping_list=}")
print(
    "assign past the end: "
    f"{raised_error_name(lambda: shopping_list.__setitem__(5, 'x'))}"
)
```

```text
shopping_list[0]='rice', shopping_list[-1]='ghee'
shopping_list=['rice', 'dal', 'butter']
assign past the end: IndexError
```

`shopping_list.__setitem__(5, 'x')` is what `shopping_list[5] = 'x'` calls;
it is written that way only because a lambda cannot contain an assignment.

### `items[a:b:c]`, `items[a:b] = iterable`

Copy a slice, or replace one with the items of any iterable (here a tuple of
three items replaces two).

```python
shopping_list = ["rice", "dal", "ghee", "salt", "tea"]
print(
    f"{shopping_list[1:4]=}, {shopping_list[::2]=}, "
    f"{shopping_list[::-1]=}"
)
shopping_list[1:3] = ("moong dal", "toor dal", "urad dal")
print(f"{shopping_list=}")
```

```text
shopping_list[1:4]=['dal', 'ghee', 'salt'],
  shopping_list[::2]=['rice', 'ghee', 'tea'],
  shopping_list[::-1]=['tea', 'salt', 'ghee', 'dal', 'rice']
shopping_list=['rice', 'moong dal', 'toor dal', 'urad dal', 'salt', 'tea']
```

### `del items[i]`, `del items[a:b]`

Delete by position or slice; an extended slice works too.

```python
shopping_list = ["rice", "dal", "ghee", "salt", "tea", "jam"]
del shopping_list[0]
del shopping_list[-2:]
print(f"{shopping_list=}")
del shopping_list[::2]
print(f"{shopping_list=}")
```

```text
shopping_list=['dal', 'ghee', 'salt']
shopping_list=['ghee']
```

### `x in items`

A linear scan with `==`. CPython checks **identity first** (`is`, then `==`),
so an object is always found in a list that holds it, even `nan`, which is
not equal to itself.

```python
shopping_list = ["rice", "dal"]
print(f"{'dal' in shopping_list=}, {'oil' not in shopping_list=}")
not_a_number = float("nan")
print(
    f"{not_a_number == not_a_number=}, "
    f"{not_a_number in [not_a_number]=}"
)
print(f"{float('nan') in [float('nan')]=}  (two different nan objects)")
```

```text
'dal' in shopping_list=True, 'oil' not in shopping_list=True
not_a_number == not_a_number=False, not_a_number in [not_a_number]=True
float('nan') in [float('nan')]=False  (two different nan objects)
```

> **Note:** JavaScript draws the same line differently: `[NaN].includes(NaN)`
> is `true` (SameValueZero), while `[NaN].indexOf(NaN)` is `-1`.

### `items + other`, `items * n`

Both build new lists. Repetition copies **references**, which matters when
the repeated item is mutable (see Lab 1.5, exercise 4).

```python
breakfast_list = ["idli", "dosa"]
print(
    f"{breakfast_list + ['vada']=}, {breakfast_list * 2=}, "
    f"{breakfast_list=}"
)
repeated_rows = [[]] * 3
repeated_rows[0].append("x")
print(f"{repeated_rows=}  (three references to one inner list)")
```

```text
breakfast_list + ['vada']=['idli', 'dosa', 'vada'],
  breakfast_list * 2=['idli', 'dosa', 'idli', 'dosa'],
  breakfast_list=['idli', 'dosa']
repeated_rows=[['x'], ['x'], ['x']]  (three references to one inner list)
```

### Built-ins that work on lists

`len`, `min`, `max`, `sum`, `sorted`, `reversed`, `enumerate`, `any` and
`all` accept any iterable, lists included. `enumerate(items, start=1)` is the
Python replacement for a counting `for` loop, and `max(..., default=0)`
avoids the `ValueError` that `max` raises on empty input.

```python
daily_sales = [1200, 950, 0, 1800, 1430]
print(
    f"{len(daily_sales)=}, {min(daily_sales)=}, "
    f"{max(daily_sales)=}, {sum(daily_sales)=}"
)
print(f"{sorted(daily_sales)=}, {list(reversed(daily_sales))=}")
for day_number, sales_amount in enumerate(daily_sales, start=1):
    print(f"day {day_number}: ₹{sales_amount:,}")
print(f"{any(sale == 0 for sale in daily_sales)=}, {all(daily_sales)=}")
print(f"{max([], default=0)=}  (default avoids ValueError on empty input)")
```

```text
len(daily_sales)=5, min(daily_sales)=0, max(daily_sales)=1800,
  sum(daily_sales)=5380
sorted(daily_sales)=[0, 950, 1200, 1430, 1800],
  list(reversed(daily_sales))=[1430, 1800, 0, 950, 1200]
day 1: ₹1,200
day 2: ₹950
day 3: ₹0
day 4: ₹1,800
day 5: ₹1,430
any(sale == 0 for sale in daily_sales)=True, all(daily_sales)=False
max([], default=0)=0  (default avoids ValueError on empty input)
```

### `==`, `<`

Lists compare item by item: the first difference decides, and a list that is
a prefix of a longer one is smaller. This lexicographic rule is the same one
that makes tuple sort keys work. JavaScript's `==` on arrays compares
identity, and its `<` converts both arrays to strings; Python compares
contents.

```python
print(f"{[1, 2, 3] == [1, 2, 3]=}, {[1, 2] == [1.0, 2.0]=}")
print(f"{[1, 2, 3] < [1, 3]=}  (decided at index 1)")
print(f"{[1, 2] < [1, 2, 0]=}  (prefix is smaller)")
print(f"{['b'] > ['a', 'z']=}")
print(f"mixed types: {raised_error_name(lambda: [1, 'a'] < [1, 2])}")
```

```text
[1, 2, 3] == [1, 2, 3]=True, [1, 2] == [1.0, 2.0]=True
[1, 2, 3] < [1, 3]=True  (decided at index 1)
[1, 2] < [1, 2, 0]=True  (prefix is smaller)
['b'] > ['a', 'z']=True
mixed types: TypeError
```

### Key points

| Idea | Takeaway |
| --- | --- |
| Return values | Mutators return `None`; `pop` returns the item |
| Errors | `remove`/`index`: `ValueError`; `pop`: `IndexError` |
| Keyword-only | `sort(key=..., reverse=...)` |
| No holes | Assigning past the end raises |
| `in` | Identity first, then `==` |
| Comparison | Lexicographic, by contents |
