# Unit 1.7 — Copying: Shallow Copies, Deep Copies and Structured Clones

[← Previous](unit-1-6-collection-data-types-ii-dictionaries-sets-and-the-collections-module.md) · [Index](README.md) · [Next →](unit-1-8-operators-expressions-and-control-flow.md)

Assignment in Python never copies anything. It only adds another name for an object
that already exists. This unit covers what to do when you really need a second,
independent object. It explains shallow copies (a new outer container), deep copies
(new objects all the way down, with a memo dict for shared references and cycles),
how classes customize both, what cannot be copied and what copying costs. It also
shows when an immutable snapshot is a better choice than any copy.

## What you will learn

- How to tell an alias from a copy, and how to prove which one you have with `is`.
- Every idiomatic way to shallow-copy a list, dict and set, and which inner objects
  each copy still shares.
- How `copy.deepcopy` works, including the memo dict that keeps shared references
  shared and makes cycles terminate.
- How to customize copying with `__copy__` and `__deepcopy__(self, memo)`, for
  example to share an expensive read-only table on purpose.
- Which objects cannot be copied (locks, files, sockets, generators), and how much
  slower and bigger a deep copy is than a shallow one.
- How `copy.deepcopy` compares with JavaScript's `structuredClone`, and why a JSON
  round trip is the wrong way to deep-copy.
- How to avoid defensive copies with immutable snapshots: `tuple`, `frozenset` and
  `frozendict`.

## JavaScript → Python bridge

The copying model is almost the same in both languages. Names (variables) hold
references, assignment copies the reference, and the built-in "copy" idioms are
shallow. The differences are in the deep copy and in the frozen types.

| JavaScript | Python | The difference that bites |
| --- | --- | --- |
| `const b = a` | `b = a` | Same: two names, one object |
| `[...items]`, `items.slice()` | `items.copy()`, `items[:]` | Both shallow; also `list(items)` |
| `{...config}` | `config.copy()`, `{**config}` | Both shallow; also `dict(config)` |
| `Object.assign({}, config)` | `dict(config)` | Both shallow |
| `structuredClone(value)` | `copy.deepcopy(value)` | `deepcopy` keeps classes and functions |
| `JSON.parse(JSON.stringify(x))` | `json.loads(json.dumps(x))` | Wrong in both languages |
| `Object.freeze(obj)` | `tuple`, `frozenset`, `frozendict` | Real immutable types, not a flag |

`structuredClone` drops the prototype of class instances and throws on functions.
`deepcopy` keeps the class (so methods still work) and copies functions and classes
by reference. A Python JSON round trip loses tuples, sets, `Decimal`, datetimes and
integer dict keys.

The examples in this unit use the setup below. `raised_error_name` calls a function
and returns the name of the exception it raised, so one line can show "this raises
`TypeError`" without stopping the program. `show_size` is the helper from Unit 1.2,
and `scratch_dir` is a scratch folder used for the open-file demo in 1.7.5.

```python
import copy
import datetime as dt
import json
import socket
import sys
import threading
import timeit
import tracemalloc
import types
from collections.abc import Callable, Mapping
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
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


def find_repo_root(start: Path | None = None) -> Path:
    """Walk up from start to the folder holding pyproject.toml."""
    current = (start or Path.cwd()).resolve()
    for folder in (current, *current.parents):
        if (folder / "pyproject.toml").exists():
            return folder
    raise FileNotFoundError("pyproject.toml not found above the working dir")


scratch_dir = find_repo_root() / "notebooks" / "_scratch"
scratch_dir.mkdir(parents=True, exist_ok=True)
PAISE = Decimal("0.01")
print(f"{sys.version_info[:2]=}")
```

```text
sys.version_info[:2]=(3, 15)
```

> **Note:** a few output lines are longer than a phone screen. They are wrapped at a
> comma or a space, and the continuation is indented by two spaces. Some long code
> lines are split into two adjacent f-strings inside parentheses, which prints
> exactly the same text. Nothing else is changed.

## 1.7.1 Assignment vs copy

Unit 1.2 showed that a Python variable is a **name** bound to an object, not a box
holding a value. In CPython every object lives on the heap as a `PyObject` struct,
and a name is a slot (in a frame's local array or a module's dict) that holds a
pointer to that struct. The statement `b = a` copies the pointer into a second slot
and increments the object's reference count. No new object is created. Changes made
through either name are therefore visible through both, because there is only one
object. That is an **alias**.

A **copy** is a new object, and you only get one by asking for it explicitly: by
calling a method such as `list.copy()`, a constructor such as `list(...)`, or a
function from the `copy` module. Python never copies behind your back. This is the
same rule JavaScript uses for objects and arrays. The one difference is that in
JavaScript, numbers and strings are primitives that behave like values. In Python
they are objects too, but they are immutable, so sharing them is harmless.

To prove whether two names share an object, compare identities. `id(x)` returns an
integer that is unique among live objects (in CPython it is the memory address), and
`a is b` means `id(a) == id(b)`. The example compares ids instead of printing them,
because the numbers change on every run.

```python
cart_items = ["tea", "rice"]
same_cart = cart_items  # alias: a second name, no new object
copied_cart = cart_items.copy()  # a new list holding the same elements

same_cart.append("ghee")
print(f"{cart_items=}")
print(f"{copied_cart=}")
print(f"{id(same_cart) == id(cart_items)=}, {same_cart is cart_items=}")
print(f"{id(copied_cart) == id(cart_items)=}, {copied_cart is cart_items=}")
print(f"{copied_cart == ['tea', 'rice']=}  (equal values, different object)")
```

```text
cart_items=['tea', 'rice', 'ghee']
copied_cart=['tea', 'rice']
id(same_cart) == id(cart_items)=True, same_cart is cart_items=True
id(copied_cart) == id(cart_items)=False, copied_cart is cart_items=False
copied_cart == ['tea', 'rice']=True  (equal values, different object)
```

`==` asks "do these hold equal values?" and `is` asks "are these the same object?".
The copy is equal to the original but is not the original, so appending through the
alias reached `cart_items` but not `copied_cart`.

### Function arguments are assignments too

Passing an object to a function is also assignment: the parameter becomes a new name
for the caller's object (Unit 1.2). A function that mutates its argument therefore
changes the caller's data. This is the most common reason to copy. Either the caller
passes a copy, or the function copies before it mutates.

```python
def add_free_gift(order_items: list[str]) -> list[str]:
    """Append a gift item and return the list (mutates the argument!)."""
    order_items.append("free-sample")
    return order_items


customer_order = ["tea"]
gifted_order = add_free_gift(customer_order)
print(f"{customer_order=}  (the caller's list changed)")
print(f"{gifted_order is customer_order=}")

customer_order = ["tea"]
gifted_copy = add_free_gift(customer_order.copy())
print(
    f"{customer_order=}, {gifted_copy=}  "
    "(copy passed in, caller untouched)"
)
```

```text
customer_order=['tea', 'free-sample']  (the caller's list changed)
gifted_order is customer_order=True
customer_order=['tea'], gifted_copy=['tea', 'free-sample']
  (copy passed in, caller untouched)
```

> **Warning:** returning the argument, as `add_free_gift` does, makes the mutation
> easy to miss. The caller sees a "new" result and assumes the input is untouched.
> Python's own convention is that a method which mutates in place returns `None`
> (`list.sort`, `list.append`). Follow it, or return a fresh object.

### Key points

| Idea | Takeaway |
| --- | --- |
| `b = a` | Copies a pointer; one object, two names |
| Alias | Mutation through one name shows in all |
| Copy | A new object, only on explicit request |
| `is` / `id` | Identity; `==` compares values |
| Parameters | A new name for the caller's object |

## 1.7.2 Shallow copies

A **shallow copy** builds a new outer container and fills it with references to the
**same** element objects. In CPython, `list.copy()` allocates a new `PyListObject`,
copies the array of element pointers, and increments each element's reference
count. Not a single element is duplicated. `dict.copy()` is similar. When the source
dict is compact, CPython can even clone the whole key table in one block. The cost
is O(n) pointer copies, whatever the size of the elements.

JavaScript's spread syntax, `slice()` and `Object.assign` are shallow in exactly the
same way. Each built-in Python container has several spellings for the same
operation.

### Reference: ways to shallow-copy

Every row returns a new outer object whose elements are the original elements.

**`list`**

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `items.copy()` | Method; clearest for lists | `[1, 2].copy()` | `[1, 2]` |
| `items[:]` | Full slice; a new list | `[1, 2][:]` | `[1, 2]` |
| `list(items)` | Copies any iterable | `list((1, 2))` | `[1, 2]` |
| `copy.copy(items)` | Generic shallow copy | `copy.copy([1, 2])` | `[1, 2]` |

**`dict`**

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `config.copy()` | Method; same keys, values | `{"a": 1}.copy()` | `{'a': 1}` |
| `{**config}` | Unpacking; can add keys | `{**{"a": 1}, "b": 2}` | `{'a': 1, 'b': 2}` |
| `dict(config)` | Constructor copy | `dict({"a": 1})` | `{'a': 1}` |
| `copy.copy(config)` | Generic shallow copy | `copy.copy({"a": 1})` | `{'a': 1}` |

**`set`**

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `tags.copy()` | Method; a new set | `{1, 2}.copy()` | `{1, 2}` |
| `set(tags)` | Copies any iterable | `set([1, 2, 2])` | `{1, 2}` |
| `copy.copy(tags)` | Generic shallow copy | `copy.copy({1, 2})` | `{1, 2}` |

The next examples show each spelling. Each one checks that the copy is a new object
(`is` is `False` for the containers) whose elements are the same objects (`is` is
`True` for the elements).

### `list.copy()`

The explicit method is the clearest choice for lists. A reader cannot mistake it for
anything else.

```python
price_rows = [[60, 40], [30, 45]]
rows_copy = price_rows.copy()
print(f"{rows_copy == price_rows=}, {rows_copy is price_rows=}")
print(f"{rows_copy[0] is price_rows[0]=}  (inner lists are shared)")
```

```text
rows_copy == price_rows=True, rows_copy is price_rows=False
rows_copy[0] is price_rows[0]=True  (inner lists are shared)
```

### `[:]`

Every slice of a list is a new list (Unit 1.5), so the full slice `[:]` is a copy.
You will see it a lot in older code, written before `list.copy()` existed (it was
added in Python 3.3). It is the Python equivalent of `items.slice()`.

```python
price_rows = [[60, 40], [30, 45]]
rows_copy = price_rows[:]
print(f"{rows_copy is price_rows=}, {rows_copy[1] is price_rows[1]=}")
```

```text
rows_copy is price_rows=False, rows_copy[1] is price_rows[1]=True
```

### `list(x)`

The constructor copies **any** iterable into a new list: a list, a tuple, a set, a
generator. That makes it the right choice when you also want to change the outer
type. The inner objects are still shared, whatever the source type was.

```python
price_rows = [[60, 40], [30, 45]]
rows_copy = list(price_rows)
rows_from_tuple = list(((60, 40), (30, 45)))
print(f"{rows_copy is price_rows=}, {rows_copy[0] is price_rows[0]=}")
print(f"{rows_from_tuple=}  (outer type converted, inner tuples shared)")
```

```text
rows_copy is price_rows=False, rows_copy[0] is price_rows[0]=True
rows_from_tuple=[(60, 40), (30, 45)]
  (outer type converted, inner tuples shared)
```

### `dict.copy()` and `dict(config)`

`dict.copy()` returns a new dict holding the same key objects and the same value
objects. If a value is a list, both dicts point at that one list.

```python
stock_levels = {"tea": [5, 3], "rice": [9]}
stock_copy = stock_levels.copy()
print(
    f"{stock_copy is stock_levels=}, "
    f"{stock_copy['tea'] is stock_levels['tea']=}"
)
```

```text
stock_copy is stock_levels=False, stock_copy['tea'] is stock_levels['tea']=True
```

The constructor `dict(config)` behaves the same way. It is the Python spelling of
`Object.assign({}, config)`.

```python
stock_levels = {"tea": [5, 3], "rice": [9]}
stock_copy = dict(stock_levels)
print(
    f"{stock_copy is stock_levels=}, "
    f"{stock_copy['tea'] is stock_levels['tea']=}"
)
```

```text
stock_copy is stock_levels=False, stock_copy['tea'] is stock_levels['tea']=True
```

### `{**d}`

Dict unpacking into a literal is the counterpart of JavaScript's `{...config}`. It
makes a copy that can also add or override keys in the same expression (later keys
win, as in JavaScript). Unit 1.6 showed the `|` operator, which does the same for two
dicts.

```python
stock_levels = {"tea": [5, 3], "rice": [9]}
stock_copy = {**stock_levels, "ghee": [2]}
print(f"{stock_copy=}")
print(
    f"{stock_copy is stock_levels=}, "
    f"{stock_copy['tea'] is stock_levels['tea']=}"
)
```

```text
stock_copy={'tea': [5, 3], 'rice': [9], 'ghee': [2]}
stock_copy is stock_levels=False, stock_copy['tea'] is stock_levels['tea']=True
```

### `set.copy()`

Set elements must be hashable, so they are almost always immutable (numbers,
strings, tuples, frozensets). A shallow copy of a set is therefore normally all you
need, because there is nothing mutable inside it to share.

```python
ticket_numbers = {101, 102, 103}
tickets_copy = ticket_numbers.copy()
tickets_copy.add(104)
print(f"{sorted(ticket_numbers)=}, {sorted(tickets_copy)=}")
print(f"{tickets_copy is ticket_numbers=}")
```

```text
sorted(ticket_numbers)=[101, 102, 103], sorted(tickets_copy)=[101, 102, 103,
  104]
tickets_copy is ticket_numbers=False
```

### `copy.copy(x)`

`copy.copy` is the generic shallow copy for **any** object. It is handy in code that
does not know the type it is copying. It dispatches like this:

1. **Atomic immutable types** (`int`, `float`, `str`, `bytes`, `tuple`, `frozenset`,
   `frozendict`, `None`, functions, classes and a few more) are returned
   **unchanged**, because a copy of an immutable object would be pointless.
2. **Built-in containers** (`list`, `dict`, `set`, `bytearray`) call their own
   `.copy()` method.
3. A class that defines **`__copy__`** has that method called (1.7.4).
4. Anything else goes through the **pickle protocol**. `obj.__reduce_ex__(4)`
   describes how to rebuild the object. For a plain class instance that means "make
   a new, empty instance and give it a shallow copy of `__dict__`".

```python
class Basket:
    """A tiny class to show copy.copy on instances."""

    def __init__(self, owner: str, items: list[str]) -> None:
        self.owner = owner
        self.items = items


asha_basket = Basket("asha", ["tea"])
basket_copy = copy.copy(asha_basket)
print(
    f"{basket_copy is asha_basket=}, "
    f"{basket_copy.items is asha_basket.items=}"
)
print(f"{copy.copy([1, 2]) == [1, 2]=}, {copy.copy({'a': 1}) == {'a': 1}=}")
point = (3, 4)
print(
    f"{copy.copy(point) is point=}, "
    f"{copy.copy('dosa') == 'dosa'=}  (immutables)"
)
```

```text
basket_copy is asha_basket=False, basket_copy.items is asha_basket.items=True
copy.copy([1, 2]) == [1, 2]=True, copy.copy({'a': 1}) == {'a': 1}=True
copy.copy(point) is point=True, copy.copy('dosa') == 'dosa'=True  (immutables)
```

#### Under the hood: what `__reduce_ex__` hands to `copy`

You can call the reduction yourself to see the recipe that `copy.copy` follows for a
plain instance. The first three items are a constructor, its arguments, and the
state to restore.

```python
constructor, constructor_args, instance_state = (
    asha_basket.__reduce_ex__(4)[:3]
)
print(f"{constructor.__name__=}")
print(f"{constructor_args=}")
print(f"{instance_state=}")
```

```text
constructor.__name__='__newobj__'
constructor_args=(<class '__main__.Basket'>,)
instance_state={'owner': 'asha', 'items': ['tea']}
```

`__newobj__(Basket)` calls `Basket.__new__(Basket)`, which creates an instance
without running `__init__`. `copy` then fills the new instance's `__dict__` with the
state. A shallow copy passes the state dict through as it is, so `items` is the same
list object in both instances.

### The trap: the outer container is new, inner objects are shared

This is where shallow copies bite. In the next example a nested config dict is copied
shallowly, and then values are changed through the copy. Rebinding a **top-level**
key changes only the copy, because the copy has its own outer dict. Changing a value
**inside** the nested dict leaks into the original, because both outer dicts point at
the same inner dict.

```text
base_config ----\
                 +--> {"host": "db.local", "pool": [5, 10]}   (one shared dict)
staging_config -/
```

```python
base_config = {
    "app_name": "shop",
    "database": {"host": "db.local", "pool_sizes": [5, 10]},
}
staging_config = base_config.copy()
staging_config["app_name"] = "shop-staging"  # top level: only the copy changes
staging_config["database"]["host"] = "staging-db.local"  # nested: shared!
staging_config["database"]["pool_sizes"].append(20)

print(f"{base_config['app_name']=}")
print(f"{base_config['database']=}  (the original changed too)")
print(f"{staging_config['database'] is base_config['database']=}")
```

```text
base_config['app_name']='shop'
base_config['database']={'host': 'staging-db.local', 'pool_sizes': [5, 10, 20]}
  (the original changed too)
staging_config['database'] is base_config['database']=True
```

> **Warning:** this is the same bug as `const staging = {...base}` followed by
> `staging.database.host = "..."` in JavaScript. A shallow copy is only safe if you
> never mutate the inner objects, or if every inner object is immutable.

#### Predict the output: `+=` vs `+` on a shallow copy

```python
menu = {"breakfast": ["idli"], "lunch": ["thali"]}
menu_copy = {**menu}
menu_copy["breakfast"] += ["dosa"]
menu_copy["lunch"] = menu_copy["lunch"] + ["curd"]
print(menu)
```

<details><summary>Answer</summary>

```text
{'breakfast': ['idli', 'dosa'], 'lunch': ['thali']}
```

`+=` on a list **mutates** it in place (`list.__iadd__` is `extend`), and that list
is shared with `menu`. The statement then rebinds `menu_copy["breakfast"]` to the
same list, which changes nothing visible. By contrast, `menu_copy["lunch"] + [...]`
builds a **new** list and rebinds only the copy's key, so `menu["lunch"]` is
untouched. The notebook confirms this:

```python
print(f"{menu_copy['lunch'] is menu['lunch']=}")
```

```text
menu_copy['lunch'] is menu['lunch']=False
```

</details>

### Key points

| Idea | Takeaway |
| --- | --- |
| Shallow copy | New outer container, same elements |
| Cost | O(n) pointer copies plus refcount increments |
| Spellings | `.copy()`, `[:]`, `list()`, `dict()`, `{**d}`, `set()` |
| `copy.copy` | Generic; immutables come back unchanged |
| Instances | New instance, shallow copy of `__dict__` |
| The trap | Nested mutations leak into the original |

## 1.7.3 Deep copies

`copy.deepcopy(x)` copies the container **and, recursively, everything it
contains**. The result shares no mutable object with the original. It walks the
object graph. For each object it finds, it looks up a type-specific copier
(`_deepcopy_list`, `_deepcopy_dict`, `_deepcopy_tuple`, …) or falls back to
`__deepcopy__` or the pickle protocol. Each copier calls `deepcopy` again on the
elements.

Immutable atoms (`int`, `str`, `None`, `bytes`, functions, classes and so on) are
returned as they are, because copying them gains nothing. That is why a deep copy of
a config dict still shares its string values. It cannot matter, because nobody can
change a string.

Here is the nested config from 1.7.2 again, copied deeply this time:

```python
base_config = {
    "app_name": "shop",
    "database": {"host": "db.local", "pool_sizes": [5, 10]},
}
staging_config = copy.deepcopy(base_config)
staging_config["database"]["host"] = "staging-db.local"
staging_config["database"]["pool_sizes"].append(20)

print(f"{base_config['database']=}  (unchanged)")
print(f"{staging_config['database']=}")
print(f"{staging_config['database'] is base_config['database']=}")
print(
    f"{staging_config['app_name'] is base_config['app_name']=}"
    "  (str reused)"
)
```

```text
base_config['database']={'host': 'db.local', 'pool_sizes': [5, 10]}  (unchanged)
staging_config['database']={'host': 'staging-db.local', 'pool_sizes': [5, 10,
  20]}
staging_config['database'] is base_config['database']=False
staging_config['app_name'] is base_config['app_name']=True  (str reused)
```

### The memo dict

A naive recursive copy has two problems. If the same list appears twice, it makes
two independent copies, which changes the shape of the data. If a structure contains
itself, it recurses forever. `deepcopy` solves both with a dictionary called `memo`,
which maps `id(original) → copy` for every object it has already copied. Before it
copies an object, it looks the object's id up in `memo`. That gives two guarantees:

1. **Shared references stay shared.** If one list appears twice in the original, the
   copy contains one new list, twice, and not two independent lists.
2. **Cycles terminate.** A structure that contains itself is copied once, and the
   inner reference points at the copy instead of recursing forever.

JavaScript's `structuredClone` keeps an internal map that does the same job, so both
guarantees hold there too. In Python you can see and even supply the map yourself.

First, shared references. `default_tags` appears under two keys:

```python
default_tags = ["new"]
catalog = {"tea": default_tags, "rice": default_tags}
catalog_copy = copy.deepcopy(catalog)

print(
    f"{catalog_copy['tea'] is catalog_copy['rice']=}"
    "  (still one list in the copy)"
)
print(f"{catalog_copy['tea'] is default_tags=}  (but a new one)")
catalog_copy["tea"].append("sale")
print(f"{catalog_copy=}")
```

```text
catalog_copy['tea'] is catalog_copy['rice']=True  (still one list in the copy)
catalog_copy['tea'] is default_tags=False  (but a new one)
catalog_copy={'tea': ['new', 'sale'], 'rice': ['new', 'sale']}
```

Then a cycle: a list that contains itself. Python prints the inner reference as
`[...]`, because `repr` has its own guard against infinite recursion. A naive
recursive copy would never end. `deepcopy` registers the new list in `memo` **before**
it copies the elements. When it meets the same list a second time, it finds that
list in `memo` and reuses the copy it is still building.

```python
self_referencing = ["start"]
self_referencing.append(self_referencing)
print(f"{self_referencing=}")

cycle_copy = copy.deepcopy(self_referencing)
print(f"{cycle_copy=}")
print(f"{cycle_copy[1] is cycle_copy=}  (the copy points at itself)")
print(f"{cycle_copy is self_referencing=}")
```

```text
self_referencing=['start', [...]]
cycle_copy=['start', [...]]
cycle_copy[1] is cycle_copy=True  (the copy points at itself)
cycle_copy is self_referencing=False
```

```text
original:  self_referencing --> [ "start", ● ]
                                  ^        |
                                  +--------+
copy:      cycle_copy       --> [ "start", ● ]   (a new list)
                                  ^        |
                                  +--------+
```

### Under the hood: inspecting the memo

You can pass your own `memo` dict as the second argument and look at it afterwards.
Its keys are the `id()` values of the originals (not printed here, they change per
run) and its values are their copies. An object is memoized only if its copy is a
different object, so atoms such as ints and strings never appear. There is also one
bookkeeping entry: `memo[id(memo)]` holds a list that keeps every original alive
while copying. Without it, a temporary original could be garbage-collected, and its
id could be reused by a different object in the middle of the copy.

```python
shared_pool = [5, 10]
nested_settings = {"primary": shared_pool, "replica": shared_pool}
copy_memo: dict[int, Any] = {}
settings_copy = copy.deepcopy(nested_settings, copy_memo)

print(f"{len(copy_memo)=}")
print(f"{copy_memo[id(shared_pool)] is settings_copy['primary']=}")
print(f"{copy_memo[id(nested_settings)] is settings_copy=}")
print(
    f"{id(copy_memo) in copy_memo=}, "
    f"{type(copy_memo[id(copy_memo)]).__name__=}"
)
```

```text
len(copy_memo)=3
copy_memo[id(shared_pool)] is settings_copy['primary']=True
copy_memo[id(nested_settings)] is settings_copy=True
id(copy_memo) in copy_memo=True, type(copy_memo[id(copy_memo)]).__name__='list'
```

The three entries are the outer dict, the one shared list (memoized once, although
it is referenced twice), and the keep-alive list.

> **Note:** tuples are a special case. `_deepcopy_tuple` deep-copies the elements,
> and if every copied element is the same object as the original element, it returns
> the **original** tuple. A tuple of immutables therefore survives a deep copy
> unchanged (see 1.7.7).

### Key points

| Idea | Takeaway |
| --- | --- |
| `copy.deepcopy` | Recursively copies every mutable object |
| Atoms | `int`, `str`, functions, classes are reused |
| Memo | `id(original) → copy`, built during the walk |
| Shared refs | One shared original → one shared copy |
| Cycles | Found in memo, so the walk terminates |
| Keep-alive | `memo[id(memo)]` pins originals during the copy |

## 1.7.4 Customizing copies

A class can take control of both kinds of copy by defining two special methods:

| Hook | Called by | Must return |
| --- | --- | --- |
| `__copy__(self)` | `copy.copy(obj)` | The shallow copy |
| `__deepcopy__(self, memo)` | `copy.deepcopy(obj)` | The deep copy |

The main reason to customize is to **share expensive read-only parts on purpose**:
a large lookup table, a compiled regex, a connection pool, a cache. Copying them is
slow and pointless (or, for a pool, impossible), so the hook copies only the
per-object state and passes the shared part along by reference. JavaScript has no
equivalent hook. `structuredClone` cannot be customized at all.

The next example defines `PriceList`, which holds a big read-only `tax_table` and a
small mutable `overrides` dict. The table is wrapped in `types.MappingProxyType`, a
read-only view (Unit 1.6), so sharing it is safe. `__copy__` gives the copy its own
`overrides` dict but keeps the same table.

```python
class PriceList:
    """Prices with a large shared tax table and small per-copy overrides."""

    def __init__(
        self, tax_table: Mapping[str, int], overrides: dict[str, Any]
    ) -> None:
        self.tax_table = tax_table  # big and read-only: safe to share
        self.overrides = overrides  # small and mutable: each copy needs its own

    def __copy__(self) -> PriceList:
        print("  __copy__ called")
        return PriceList(self.tax_table, dict(self.overrides))

    def __deepcopy__(self, memo: dict[int, Any]) -> PriceList:
        print("  __deepcopy__ called")
        return PriceList(
            self.tax_table, copy.deepcopy(self.overrides, memo)
        )


gst_table = types.MappingProxyType(
    {f"hsn-{code}": 18 for code in range(10_000)}
)
store_prices = PriceList(gst_table, {"tea": 249})
print("shallow:")
shallow_prices = copy.copy(store_prices)
print(f"  {shallow_prices.tax_table is store_prices.tax_table=}")
print(f"  {shallow_prices.overrides is store_prices.overrides=}")
```

```text
shallow:
  __copy__ called
  shallow_prices.tax_table is store_prices.tax_table=True
  shallow_prices.overrides is store_prices.overrides=False
```

> **Note:** the return annotation `-> PriceList` names the class inside its own
> body without quotes. That works because annotations are evaluated lazily since
> Python 3.14 (PEP 649). Older versions needed `"PriceList"` in quotes or
> `from __future__ import annotations`.

`__deepcopy__` receives the memo and **must** pass it on to every nested `deepcopy`
call. Otherwise shared references and cycles inside the object are not handled. In
the next example the `overrides` dict holds a list, so it needs a real deep copy,
while the 10 000-row table is still shared on purpose.

```python
store_prices = PriceList(gst_table, {"tea": 249, "combo": 0})
store_prices.overrides["bundle_skus"] = ["tea", "rice"]
print("deep:")
deep_prices = copy.deepcopy(store_prices)
print(
    f"  {deep_prices.tax_table is store_prices.tax_table=}"
    "  (shared on purpose)"
)
print(f"  {deep_prices.overrides is store_prices.overrides=}")
bundle_original = store_prices.overrides["bundle_skus"]
print(f"  {deep_prices.overrides['bundle_skus'] is bundle_original=}")
```

```text
deep:
  __deepcopy__ called
  deep_prices.tax_table is store_prices.tax_table=True  (shared on purpose)
  deep_prices.overrides is store_prices.overrides=False
  deep_prices.overrides['bundle_skus'] is bundle_original=False
```

### What happens if you forget `memo`

The following example is not in the notebook. A `__deepcopy__` that calls
`copy.deepcopy(...)` without `memo` starts a fresh memo for its contents. Two boxes
that shared one list in the original end up with two separate lists in the copy, so
the shape of the data silently changes. With a cycle running through the object, the
copy would recurse until it hit `RecursionError`.

```python
class ForgetfulBox:
    """A box whose __deepcopy__ forgets to pass memo on."""

    def __init__(self, contents: list[str]) -> None:
        self.contents = contents

    def __deepcopy__(self, memo: dict[int, Any]) -> "ForgetfulBox":
        return ForgetfulBox(copy.deepcopy(self.contents))  # memo dropped!


shared_items = ["tea"]
pair_of_boxes = [ForgetfulBox(shared_items), ForgetfulBox(shared_items)]
boxes_copy = copy.deepcopy(pair_of_boxes)
print(f"{pair_of_boxes[0].contents is pair_of_boxes[1].contents=}")
print(f"{boxes_copy[0].contents is boxes_copy[1].contents=}  (sharing lost)")
```

```text
pair_of_boxes[0].contents is pair_of_boxes[1].contents=True
boxes_copy[0].contents is boxes_copy[1].contents=False  (sharing lost)
```

> **Warning:** always write `copy.deepcopy(part, memo)` inside `__deepcopy__`.

### The default: no hooks

Without these hooks, `copy` falls back to the pickle protocol (`__reduce_ex__`),
which for a plain class means "new instance plus a copy of `__dict__`" (shallow for
`copy.copy`, deep for `copy.deepcopy`). Classes that define `__getstate__` and
`__setstate__` for pickling get the same behaviour for copies, so one pair of
methods controls both. Python 3.13 added `copy.replace(obj, **changes)` for "copy
with some fields changed". It is covered with dataclasses in Phase 2.

The last example of this section shows the default. A deep copy of an instance
copies its `__dict__`, so every attribute is duplicated, including the big table.

```python
class PlainPriceList:
    """The same data without copy hooks."""

    def __init__(
        self, tax_table: dict[str, int], overrides: dict[str, int]
    ) -> None:
        self.tax_table = tax_table
        self.overrides = overrides


plain_prices = PlainPriceList(dict(gst_table), {"tea": 249})
plain_copy = copy.deepcopy(plain_prices)
print(
    f"{plain_copy.tax_table is plain_prices.tax_table=}"
    "  (10 000 rows copied)"
)
print(f"{plain_copy.__dict__.keys() == plain_prices.__dict__.keys()=}")
```

```text
plain_copy.tax_table is plain_prices.tax_table=False  (10 000 rows copied)
plain_copy.__dict__.keys() == plain_prices.__dict__.keys()=True
```

### Key points

| Idea | Takeaway |
| --- | --- |
| `__copy__` | Called by `copy.copy`; returns the copy |
| `__deepcopy__` | Called by `copy.deepcopy` with `memo` |
| Pass `memo` on | Or shared refs and cycles break |
| Why customize | Share big read-only parts on purpose |
| Default | `__reduce_ex__`: new instance + `__dict__` |
| Pickle hooks | `__getstate__`/`__setstate__` affect copies |

## 1.7.5 Limits and cost

### Objects that cannot be copied

Some objects **cannot** be copied, because they stand for something outside the
Python heap (an OS lock, a file descriptor, a network connection) or for a paused
computation (a generator frame). Copying the Python wrapper would not copy the
outside resource. Two "copies" would then fight over one lock or one file position,
which is worse than an error. So these types refuse. They have no `__copy__`, and
their `__reduce_ex__` raises, so `copy` fails with `TypeError: cannot pickle ...`.
JavaScript's `structuredClone` has the same idea: it throws `DataCloneError` for
values it cannot clone.

| Object | Why it cannot be copied |
| --- | --- |
| `threading.Lock()` | Its state belongs to the OS; two copies could both be held |
| Open file | The descriptor and file position are OS state |
| `socket.socket()` | A connection cannot be duplicated by copying memory |
| Generator | Its suspended frame cannot be cloned |

Each of the next four examples tries `copy.deepcopy` on one of them.

**A lock:**

```python
order_lock = threading.Lock()
try:
    copy.deepcopy(order_lock)
except TypeError as error:
    print(f"{type(error).__name__}: {error}")
```

```text
TypeError: cannot pickle '_thread.lock' object
```

**An open file.** The unit's scratch file is written first, then opened for reading:

```python
scratch_file = scratch_dir / "unit_1_7_copy_demo.txt"
scratch_file.write_text("order 1001\n", encoding="utf-8")
with scratch_file.open(encoding="utf-8") as order_file:
    try:
        copy.deepcopy(order_file)
    except TypeError as error:
        print(f"{type(error).__name__}: {error}")
```

```text
TypeError: cannot pickle 'TextIOWrapper' instances
```

**A socket**, created but never connected, so no network is used:

```python
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as api_socket:
    try:
        copy.deepcopy(api_socket)
    except TypeError as error:
        print(f"{type(error).__name__}: {error}")
```

```text
TypeError: cannot pickle 'socket' object
```

**A generator.** Here the shallow `copy.copy` fails too, because there is no way to
clone a frame at all:

```python
order_numbers = (number for number in range(1001, 1004))
for copy_function in (copy.copy, copy.deepcopy):
    try:
        copy_function(order_numbers)
    except TypeError as error:
        print(
            f"{copy_function.__name__}: {type(error).__name__}: {error}"
        )
```

```text
copy: TypeError: cannot pickle 'generator' object
deepcopy: TypeError: cannot pickle 'generator' object
```

> **Note:** to read one generator's values twice, use `itertools.tee` (Unit 1.13),
> which buffers the values. To share a lock between objects, keep a reference to the
> same lock and exclude it from copying with `__deepcopy__`, as `PriceList` did with
> its table.

### What copying costs

A shallow copy touches only the outer container: O(n) pointer copies done in C. A
deep copy visits **every** object in the graph. It runs Python-level dispatch code for
each one, inserts each copy into the memo dict and appends each original to the
keep-alive list, and allocates a new object for every mutable node. It is therefore
much slower and allocates far more memory. The next example times both on 10 000
nested order records.

```python
order_records = [
    {
        "order_id": order_id,
        "customer": "asha",
        "lines": [{"sku": "TEA-500G", "qty": 2}],
    }
    for order_id in range(10_000)
]
shallow_seconds = (
    timeit.timeit(lambda: copy.copy(order_records), number=20) / 20
)
deep_seconds = (
    timeit.timeit(lambda: copy.deepcopy(order_records), number=3) / 3
)
print(f"shallow copy: {shallow_seconds * 1000:8.3f} ms")
print(f"deep copy:    {deep_seconds * 1000:8.3f} ms")
print(f"deep is roughly {deep_seconds / shallow_seconds:,.0f}x slower")
```

```text
shallow copy:    0.027 ms
deep copy:      17.788 ms
deep is roughly 653x slower
```

> **Note:** these timings vary by machine, by Python version and from run to run.
> The ratio, a difference of hundreds of times, is what matters.

### Under the hood: memory with `tracemalloc`

`tracemalloc` traces every memory block that Python allocates, so it can measure the
bytes allocated while each copy runs. The shallow copy allocates one new list: 8
bytes per pointer on a 64-bit build, which is 80 000 bytes for 10 000 records, plus
a small header. The deep copy allocates 10 000 outer dicts, 10 000 inner lists and
10 000 inner dicts, plus the memo.

```python
def allocated_bytes(make_copy: Callable[[], object]) -> int:
    """Return the bytes still allocated by the object make_copy returns."""
    tracemalloc.start()
    before_bytes, _ = tracemalloc.get_traced_memory()
    copied_object = make_copy()
    after_bytes, _ = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    del copied_object
    return after_bytes - before_bytes


shallow_bytes = allocated_bytes(lambda: copy.copy(order_records))
deep_bytes = allocated_bytes(lambda: copy.deepcopy(order_records))
print(f"shallow copy: {shallow_bytes:>12,} bytes")
print(f"deep copy:    {deep_bytes:>12,} bytes")
```

```text
shallow copy:       80,000 bytes
deep copy:       4,634,575 bytes
```

> **Note:** exact byte counts vary with the Python version and build. The shallow
> copy stays near 8 bytes per element, while the deep copy grows with the size of
> everything inside.

### Key points

| Idea | Takeaway |
| --- | --- |
| Uncopyable | Locks, files, sockets, generators |
| The error | `TypeError: cannot pickle ...` |
| Why | They wrap OS state or a paused frame |
| Shallow cost | O(n) pointer copies, done in C |
| Deep cost | Every node, plus memo; hundreds of times slower |
| Memory | Deep copy duplicates every mutable node |

## 1.7.6 JS bridge: structuredClone

The mapping between the two languages is close:

| JavaScript | Python | Depth |
| --- | --- | --- |
| `[...items]`, `items.slice()` | `items.copy()`, `items[:]` | Shallow |
| — | `list(items)` | Shallow |
| `{...config}` | `config.copy()`, `{**config}` | Shallow |
| `Object.assign({}, config)` | `dict(config)` | Shallow |
| `structuredClone(value)` | `copy.deepcopy(value)` | Deep |

The biggest practical difference is in the deep copy. `structuredClone` copies only
"plain data" that the HTML structured-clone algorithm knows about. A class instance
comes back as a plain object without its prototype, so its methods are gone, and a
function throws `DataCloneError`. `deepcopy` keeps the class, so methods still work,
and it copies functions and classes by reference, because they count as atoms.

```javascript
class Cart {
  constructor() { this.items = [] }
  total() { return this.items.length }
}
const clone = structuredClone(new Cart())
clone instanceof Cart   // false
clone.total             // undefined
```

The Python equivalent keeps everything:

```python
class Cart:
    """A cart with a method, to show that deepcopy keeps the class."""

    def __init__(
        self, items: list[str], on_checkout: Callable[[], str]
    ) -> None:
        self.items = items
        self.on_checkout = on_checkout

    def item_count(self) -> int:
        """Return the number of items."""
        return len(self.items)


def send_receipt() -> str:
    """Pretend to send a receipt."""
    return "receipt sent"


asha_cart = Cart(["tea", "rice"], send_receipt)
cart_clone = copy.deepcopy(asha_cart)
print(f"{type(cart_clone).__name__=}, {isinstance(cart_clone, Cart)=}")
print(f"{cart_clone.item_count()=}, {cart_clone.items is asha_cart.items=}")
print(
    f"{cart_clone.on_checkout is send_receipt=}"
    "  (functions are shared, not copied)"
)
```

```text
type(cart_clone).__name__='Cart', isinstance(cart_clone, Cart)=True
cart_clone.item_count()=2, cart_clone.items is asha_cart.items=False
cart_clone.on_checkout is send_receipt=True  (functions are shared, not copied)
```

This works because the pickle-style reduction records the **class** (`__newobj__`
with `Cart`, as in 1.7.2). The copy is made with `Cart.__new__`, so its type is
`Cart` and method lookup goes through the class as usual.

### Why `json.loads(json.dumps(x))` is the wrong deep copy

The JSON round trip is the Python version of the old `JSON.parse(JSON.stringify(x))`
trick, and it fails for the same reason. JSON has only objects with string keys,
arrays, strings, numbers, booleans and null. Every other type is either converted to
one of those or rejected. It is also slower than `deepcopy` for most data, because
it builds a full text representation and parses it again.

| Value | After a JSON round trip |
| --- | --- |
| tuple | Becomes a list |
| set | `TypeError` (not serializable) |
| `Decimal` | `TypeError`, or a lossy float with `default=float` |
| `datetime` | `TypeError`, or a string with `default=str` |
| int dict keys | Become strings: `{1: ...}` → `{"1": ...}` |

The next five examples show one failure each, and `deepcopy` handles all of them.

**Tuples become lists:**

```python
shipment = {"dimensions_cm": (30, 20, 10)}
json_copy = json.loads(json.dumps(shipment))
print(f"{json_copy=}, {type(json_copy['dimensions_cm']).__name__=}")
print(f"{copy.deepcopy(shipment)=}")
```

```text
json_copy={'dimensions_cm': [30, 20, 10]},
  type(json_copy['dimensions_cm']).__name__='list'
copy.deepcopy(shipment)={'dimensions_cm': (30, 20, 10)}
```

**Sets are rejected:**

```python
product = {"tags": {"organic", "vegan"}}
try:
    json.dumps(product)
except TypeError as error:
    print(f"{type(error).__name__}: {error}")
print(f"{sorted(copy.deepcopy(product)['tags'])=}")
```

```text
TypeError: Object of type set is not JSON serializable
sorted(copy.deepcopy(product)['tags'])=['organic', 'vegan']
```

**`Decimal` is rejected**, and the usual workaround (`default=float`) silently loses
exactness. The result is a binary float, not a `Decimal`:

```python
invoice = {"total": Decimal("1999.99")}
print(f"plain dumps: {raised_error_name(lambda: json.dumps(invoice))}")
float_round_trip = json.loads(
    json.dumps({"total": Decimal("0.1") * 3}, default=float)
)
print(f"{float_round_trip=}  (a float now, not a Decimal)")
print(f"{copy.deepcopy(invoice)=}")
```

```text
plain dumps: TypeError
float_round_trip={'total': 0.3}  (a float now, not a Decimal)
copy.deepcopy(invoice)={'total': Decimal('1999.99')}
```

**Datetimes are rejected**, and `default=str` turns them into strings that do not
compare or add like dates:

```python
delivery = {"due": dt.datetime(2026, 11, 3, 18, 30)}
print(f"plain dumps: {raised_error_name(lambda: json.dumps(delivery))}")
string_round_trip = json.loads(json.dumps(delivery, default=str))
print(
    f"{string_round_trip=}, "
    f"{type(string_round_trip['due']).__name__=}"
)
print(f"{copy.deepcopy(delivery)=}")
```

```text
plain dumps: TypeError
string_round_trip={'due': '2026-11-03 18:30:00'},
  type(string_round_trip['due']).__name__='str'
copy.deepcopy(delivery)={'due': datetime.datetime(2026, 11, 3, 18, 30)}
```

**Int keys come back as strings**, so lookups by the original key fail:

```python
stock_by_shelf = {1: "tea", 2: "rice"}
json_copy = json.loads(json.dumps(stock_by_shelf))
print(f"{json_copy=}")
print(f"lookup json_copy[1]: {raised_error_name(lambda: json_copy[1])}")
print(f"{copy.deepcopy(stock_by_shelf)[1]=}")
```

```text
json_copy={'1': 'tea', '2': 'rice'}
lookup json_copy[1]: KeyError
copy.deepcopy(stock_by_shelf)[1]='tea'
```

> **Warning:** JSON is a serialization format for sending data across a boundary
> (a file, an HTTP response). It is not a copying tool. Inside one Python process,
> use `copy.deepcopy`, or better, an immutable snapshot (1.7.7).

### Key points

| Idea | Takeaway |
| --- | --- |
| Spread / `Object.assign` | Shallow, like `.copy()` / `{**d}` |
| `structuredClone` | Deep, like `deepcopy` |
| Class instances | `deepcopy` keeps the class and methods |
| Functions | Shared by `deepcopy`; rejected by `structuredClone` |
| JSON round trip | Loses tuples, sets, `Decimal`, datetimes, int keys |

## 1.7.7 Immutable snapshots

Defensive copying means copying the input in case someone mutates it later. It costs
time and memory on every call, as 1.7.5 showed. If the data is **immutable**, nobody
can mutate it, so it can be shared freely and no copy is needed at all. `copy.copy`
knows this. Its first check returns the same object for the atomic immutable
built-ins, and `deepcopy` does the same whenever nothing inside needs copying.

JavaScript's `Object.freeze` is the closest idea, but it is a shallow flag on an
ordinary object. Python's frozen types are separate, genuinely immutable types. They
have no mutating methods at all, and most of them are hashable, so they can be dict
keys and set members.

| Mutable | Immutable snapshot | Notes |
| --- | --- | --- |
| `list` | `tuple(items)` | Immutable only if the elements are |
| `set` | `frozenset(tags)` | Hashable; usable as a dict key |
| `dict` | `frozendict(config)` | New in 3.15; hashable if values are |

On versions before 3.15, `types.MappingProxyType` gives a read-only **view** of a
dict instead (Unit 1.6). It is not a snapshot, because it shows later changes to the
dict behind it.

### `tuple` snapshots

The next example takes a tuple snapshot of an order's line items. Later appends to
the live list do not reach the snapshot, and `copy.copy` and `copy.deepcopy` both
return the same object, so passing the snapshot around costs nothing.

```python
live_line_items = ["TEA-500G", "RICE-5KG"]
line_snapshot = tuple(live_line_items)
live_line_items.append("GHEE-1L")
print(f"{line_snapshot=}  (later appends do not reach the snapshot)")
print(f"{copy.copy(line_snapshot) is line_snapshot=}")
print(
    f"{copy.deepcopy(line_snapshot) is line_snapshot=}"
    "  (all elements immutable)"
)
print(
    "item assignment: "
    f"{raised_error_name(lambda: line_snapshot.__setitem__(0, 'X'))}"
)
```

```text
line_snapshot=('TEA-500G', 'RICE-5KG')
  (later appends do not reach the snapshot)
copy.copy(line_snapshot) is line_snapshot=True
copy.deepcopy(line_snapshot) is line_snapshot=True  (all elements immutable)
item assignment: AttributeError
```

The error is `AttributeError`, not `TypeError`, because a tuple has no
`__setitem__` method at all. Writing `line_snapshot[0] = "X"` directly would raise
`TypeError: 'tuple' object does not support item assignment`.

A tuple is only as immutable as its contents. A tuple holding a list can still change
through that list. `deepcopy` must then copy the list, so it returns a new tuple, and
the tuple is not hashable either.

```python
mixed_snapshot = ("asha", ["tea"])
mixed_snapshot[1].append("rice")
print(f"{mixed_snapshot=}  (the inner list changed)")
print(f"{copy.deepcopy(mixed_snapshot) is mixed_snapshot=}")
print(f"hash: {raised_error_name(lambda: hash(mixed_snapshot))}")
```

```text
mixed_snapshot=('asha', ['tea', 'rice'])  (the inner list changed)
copy.deepcopy(mixed_snapshot) is mixed_snapshot=False
hash: TypeError
```

> **Warning:** `tuple(items)` is itself a shallow copy. If `items` holds dicts or
> lists, the snapshot shares them. Convert the inner objects too (tuples of tuples,
> `frozendict`s) when the whole structure must be frozen.

### `frozenset`

`frozenset` is an immutable set. A set of permissions stored as a `frozenset` can be
shared between users without copying, and it can be used as a dict key. Two
frozensets with the same elements are equal and hash the same, whatever order they
were written in.

```python
EDITOR_PERMISSIONS = frozenset({"read", "write"})
permissions_by_user = {"asha": EDITOR_PERMISSIONS, "ravi": EDITOR_PERMISSIONS}
print(f"{copy.copy(EDITOR_PERMISSIONS) is EDITOR_PERMISSIONS=}")
print(f"add: {raised_error_name(lambda: EDITOR_PERMISSIONS.add('admin'))}")
role_names = {EDITOR_PERMISSIONS: "editor"}
print(f"{role_names[frozenset({'write', 'read'})]=}")
print(f"{sorted(permissions_by_user['ravi'])=}")
```

```text
copy.copy(EDITOR_PERMISSIONS) is EDITOR_PERMISSIONS=True
add: AttributeError
role_names[frozenset({'write', 'read'})]='editor'
sorted(permissions_by_user['ravi'])=['read', 'write']
```

### `frozendict` (new in 3.15)

`frozendict` (*New in 3.15*, PEP 814) is an immutable dict. It copies the data when
it is created, so later changes to the source dict do not reach it. `copy.copy`
returns the same object. `copy.deepcopy` still walks the values, because they could
be mutable, so it can return a new object. The point is that you do not need to call
it at all. On interpreters older than 3.15 the example falls back to
`types.MappingProxyType`, a read-only **view** that still changes if the dict behind
it changes.

```python
settings_source = {"currency": "INR", "gst_percent": 18}
if sys.version_info >= (3, 15):
    APP_SETTINGS = frozendict(settings_source)
    settings_source["gst_percent"] = 28  # frozendict copied the data already
    print(f"{APP_SETTINGS=}")
    print(f"{copy.copy(APP_SETTINGS) is APP_SETTINGS=}")
    set_currency = lambda: APP_SETTINGS.__setitem__("currency", "USD")
    print(f"assign: {raised_error_name(set_currency)}")
    same_settings = frozendict(gst_percent=18, currency="INR")
    print(f"{hash(APP_SETTINGS) == hash(same_settings)=}")
else:
    read_only_view = types.MappingProxyType(settings_source)
    settings_source["gst_percent"] = 28
    print(f"frozendict needs 3.15; MappingProxyType: {dict(read_only_view)=}")
```

```text
APP_SETTINGS=frozendict({'currency': 'INR', 'gst_percent': 18})
copy.copy(APP_SETTINGS) is APP_SETTINGS=True
assign: AttributeError
hash(APP_SETTINGS) == hash(same_settings)=True
```

> **Note:** the notebook writes the last two `print` calls inline. Here they are
> split into named helpers to fit a phone screen, so the final line names
> `same_settings` where the notebook prints the full
> `frozendict(gst_percent=18, currency='INR')` expression. The value is the same.
> Hash equality also shows that key order does not matter for `frozendict`
> equality.

**Rule of thumb:** store configuration and reference data in immutable types from
the start, and copy only the mutable working state (orders being edited, a cart
being filled). Lab 1.7, exercise 2, needs a deep copy precisely because its orders
are mutable nested dicts.

### Key points

| Idea | Takeaway |
| --- | --- |
| Defensive copy | Costs time and memory on every call |
| Immutable data | Share it freely; no copy needed |
| `tuple` | Frozen only if its elements are |
| `frozenset` | Immutable, hashable, a valid dict key |
| `frozendict` | Immutable dict, new in 3.15 (PEP 814) |
| `copy.copy` | Returns immutables unchanged |

## Lab 1.7

The lab has two exercises. In the notebook, each one has a stub function and a check
cell that prints `PASS` or `FAIL` for every test case. Try each exercise before
opening its solution.

### Exercise 1 — `deep_merge(base, override)`

Return a **new** dict that merges `override` into `base`:

- a key that is only in one input is taken from that input;
- if both values are dicts, they are merged recursively;
- otherwise the `override` value wins (a list replaces a list, it is not appended).

The function must **never mutate** its inputs, and the result must not share any
mutable object with them. Mutating the result afterwards must not change `base` or
`override`, and the checks use `is` to verify this. Use `copy.deepcopy` for values
that are taken over unchanged.

```python
def deep_merge(
    base: Mapping[str, Any], override: Mapping[str, Any]
) -> dict[str, Any]:
    """Return a new dict with override merged into base recursively."""
```

The main check uses these inputs, rebuilt fresh for each case:

```python
base_settings = {
    "app": {"name": "shop", "debug": False},
    "database": {"host": "db.local", "pool_sizes": [5, 10]},
    "features": ["search"],
}
override_settings = {
    "app": {"debug": True},
    "database": {"host": "staging-db.local"},
    "features": ["search", "wishlist"],
    "region": "ap-south-1",
}
```

and expects this result:

```python
{
    "app": {"name": "shop", "debug": True},
    "database": {"host": "staging-db.local", "pool_sizes": [5, 10]},
    "features": ["search", "wishlist"],
    "region": "ap-south-1",
}
```

The other checks:

| Check | Expected |
| --- | --- |
| Type of the result | `dict` |
| Inputs untouched, nothing shared | `True` |
| `deep_merge({"a": {"b": 1}}, {})` | `{'a': {'b': 1}}` |
| `deep_merge({}, {"a": [1]})` | `{'a': [1]}` |
| `deep_merge({"a": 1}, {"a": {"b": 2}})` | `{'a': {'b': 2}}` |
| `deep_merge({"a": {"b": 2}}, {"a": None})` | `{'a': None}` |
| Three levels deep (below) | `{'a': {'b': {'c': 1, 'd': 3}}}` |

The three-level case is
`deep_merge({"a": {"b": {"c": 1, "d": 2}}}, {"a": {"b": {"d": 3}}})`.

The "nothing shared" check calls `deep_merge`, verifies with `is` that
`merged["app"]`, `merged["database"]`, `merged["database"]["pool_sizes"]` and
`merged["features"]` are not the input objects, then appends to the result's lists,
renames the app, and confirms that both inputs still equal a deep copy taken
beforehand.

Hints:

- Start from a deep copy of every value in `base`, so that keys only in `base` are
  already safe.
- For each key in `override`, recurse only when **both** sides are dicts. Otherwise
  store a deep copy of the override value.
- Recursing on the already-copied base value is safe, because `deep_merge` never
  mutates its inputs.

<details><summary>Solution</summary>

```python
def deep_merge(
    base: Mapping[str, Any], override: Mapping[str, Any]
) -> dict[str, Any]:
    """Return a new dict with override merged into base recursively."""
    merged = {key: copy.deepcopy(value) for key, value in base.items()}
    for key, override_value in override.items():
        base_value = merged.get(key)
        if isinstance(base_value, dict) and isinstance(
            override_value, Mapping
        ):
            merged[key] = deep_merge(base_value, override_value)
        else:
            merged[key] = copy.deepcopy(override_value)
    return merged
```

The comprehension builds a brand-new outer dict and deep-copies each base value, so
nothing in `merged` is shared with `base`. Each override value is either merged
recursively, which again returns a new dict, or deep-copied, so nothing is shared
with `override` either. A plain `{**base, **override}` would be wrong twice: it is
shallow, and it replaces nested dicts instead of merging them.

</details>

### Exercise 2 — snapshot, discount, diff

`apply_discounts_in_place` is "legacy" code that changes unit prices **inside** the
orders you pass it. To report what it changed, you must take a snapshot first. The
notebook provides this code:

```python
class PriceChange(NamedTuple):
    """One changed line found by diff_orders."""

    order_id: int
    sku: str
    old_unit_price: Decimal
    new_unit_price: Decimal


def make_sample_orders() -> list[dict[str, Any]]:
    """Return fresh nested order data for Lab 1.7, exercise 2."""
    return [
        {
            "order_id": 1001,
            "customer": "asha",
            "lines": [
                {
                    "sku": "TEA-500G",
                    "unit_price": Decimal("249.00"),
                    "quantity": 2,
                },
                {
                    "sku": "GHEE-1L",
                    "unit_price": Decimal("640.00"),
                    "quantity": 1,
                },
            ],
        },
        {
            "order_id": 1002,
            "customer": "ravi",
            "lines": [
                {
                    "sku": "RICE-5KG",
                    "unit_price": Decimal("525.50"),
                    "quantity": 1,
                }
            ],
        },
    ]


def apply_discounts_in_place(
    orders: list[dict[str, Any]], discount_percent_by_sku: Mapping[str, int]
) -> None:
    """Legacy code: reduce unit prices inside orders, rounded to the paisa."""
    for order in orders:
        for line in order["lines"]:
            discount_percent = discount_percent_by_sku.get(line["sku"], 0)
            discounted = line["unit_price"] * (100 - discount_percent) / 100
            line["unit_price"] = discounted.quantize(
                PAISE, rounding=ROUND_HALF_UP
            )


print(f"{len(make_sample_orders())=}")
```

```text
len(make_sample_orders())=2
```

Write two functions:

1. `diff_orders(before, after)` compares two order lists with the same shape. It
   returns a `PriceChange(order_id, sku, old_unit_price, new_unit_price)` for every
   line whose unit price differs, in order.
2. `discount_and_diff(orders, discount_percent_by_sku)` snapshots `orders` with
   `copy.deepcopy` and calls `apply_discounts_in_place(orders, ...)`, so `orders`
   **is** changed, as the legacy code requires. It returns
   `diff_orders(snapshot, orders)`.

The checks use a 10% discount on tea and 5% on rice. Ghee is not discounted.

| Check | Expected |
| --- | --- |
| Diff of two identical order lists | `[]` |
| `discount_and_diff` with the sample discounts | tea and rice changes (below) |
| Tea price in `orders` afterwards | `Decimal('224.10')` |
| `discount_and_diff` with `{}` | `[]` |
| Diff after setting rice to `Decimal("1.00")` | one rice change |

```python
sample_discounts = {"TEA-500G": 10, "RICE-5KG": 5}
expected_changes = [
    PriceChange(1001, "TEA-500G", Decimal("249.00"), Decimal("224.10")),
    PriceChange(1002, "RICE-5KG", Decimal("525.50"), Decimal("499.23")),
]
```

The "manual edit" check expects
`[PriceChange(1002, "RICE-5KG", Decimal("525.50"), Decimal("1.00"))]`.

Hints:

- `zip(before, after, strict=True)` walks the two lists in step and raises if their
  lengths differ. Do the same for each order's `"lines"`.
- A shallow `orders.copy()` would make the diff **empty**: the snapshot's line dicts
  would be the same objects that the legacy code mutates. One check guards against
  that.

<details><summary>Solution</summary>

```python
def diff_orders(
    before: list[dict[str, Any]], after: list[dict[str, Any]]
) -> list[PriceChange]:
    """Return a PriceChange for every line whose unit price differs."""
    changes = []
    for order_before, order_after in zip(before, after, strict=True):
        for line_before, line_after in zip(
            order_before["lines"], order_after["lines"], strict=True
        ):
            if line_before["unit_price"] != line_after["unit_price"]:
                changes.append(
                    PriceChange(
                        order_before["order_id"],
                        line_before["sku"],
                        line_before["unit_price"],
                        line_after["unit_price"],
                    )
                )
    return changes


def discount_and_diff(
    orders: list[dict[str, Any]], discount_percent_by_sku: Mapping[str, int]
) -> list[PriceChange]:
    """Snapshot orders, apply discounts in place, return what changed."""
    snapshot = copy.deepcopy(orders)
    apply_discounts_in_place(orders, discount_percent_by_sku)
    return diff_orders(snapshot, orders)
```

The deep copy duplicates every order dict, every `lines` list and every line dict,
so the legacy code's writes go only into `orders`. `Decimal` values are immutable,
so the snapshot keeps the old prices even though `deepcopy` shares the `Decimal`
objects themselves. The discounted rice price is `525.50 × 0.95 = 499.225`, which
`ROUND_HALF_UP` rounds to `499.23`.

</details>

With both solutions in place, the check cells print:

```text
Exercise 1 — deep_merge
PASS  nested merge
PASS  returns a dict
PASS  inputs untouched, nothing shared
PASS  empty override
PASS  empty base
PASS  dict replaces scalar
PASS  scalar replaces dict
PASS  three levels deep
8/8 checks passed
Exercise 2 — snapshot, discount, diff
PASS  diff of identical orders
PASS  discount_and_diff changes
PASS  orders were discounted in place
PASS  no discounts, no changes
PASS  diff after a manual edit
5/5 checks passed
```

## Recap

| Concept | Takeaway | JavaScript equivalent |
| --- | --- | --- |
| Assignment | Another name, same object; never copies | `const b = a` |
| Shallow copy | New outer container, same inner objects | `[...a]`, `{...o}` |
| Shallow spellings | `.copy()`, `[:]`, `list()`, `dict()`, `{**d}` | `slice()`, spread |
| `copy.copy` | Generic shallow copy; immutables returned | — |
| Nested data | Inner changes leak through a shallow copy | Same trap |
| `copy.deepcopy` | Copies everything mutable; reuses atoms | `structuredClone` |
| Memo dict | `id → copy`; keeps sharing, ends cycles | Internal map |
| `__copy__` | Custom shallow copy | No hook |
| `__deepcopy__(memo)` | Custom deep copy; pass `memo` on | No hook |
| Uncopyable | Locks, files, sockets, generators | `DataCloneError` |
| Cost | Deep is hundreds of times slower | Same |
| Class instances | `deepcopy` keeps class and methods | Prototype dropped |
| JSON round trip | Loses tuples, sets, `Decimal`, dates | `JSON.parse(...)` trick |
| Immutable snapshots | `tuple`, `frozenset`, `frozendict` | `Object.freeze` |

## Further reading

- [`copy` — Shallow and deep copy operations](https://docs.python.org/3/library/copy.html)
- [Programming FAQ: How do I copy an object in Python?](https://docs.python.org/3/faq/programming.html#how-do-i-copy-an-object-in-python)
- [`pickle` — `object.__reduce_ex__`](https://docs.python.org/3/library/pickle.html#object.__reduce_ex__)
- [`json` — JSON encoder and decoder](https://docs.python.org/3/library/json.html)
- [`tracemalloc` — trace memory allocations](https://docs.python.org/3/library/tracemalloc.html)
- [`timeit` — measure execution time](https://docs.python.org/3/library/timeit.html)
- [`types.MappingProxyType`](https://docs.python.org/3/library/types.html#types.MappingProxyType)
- [`frozendict`](https://docs.python.org/3.15/library/stdtypes.html#frozendict)
- [PEP 814 — Add frozendict built-in type](https://peps.python.org/pep-0814/)
- [PEP 649 — Deferred evaluation of annotations](https://peps.python.org/pep-0649/)
- [MDN: `structuredClone()`](https://developer.mozilla.org/en-US/docs/Web/API/Window/structuredClone)

[← Previous](unit-1-6-collection-data-types-ii-dictionaries-sets-and-the-collections-module.md) · [Index](README.md) · [Next →](unit-1-8-operators-expressions-and-control-flow.md)
