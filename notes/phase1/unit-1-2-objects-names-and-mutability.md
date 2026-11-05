# Unit 1.2 — Objects, Names and Mutability

[← Previous](unit-1-1-how-python-executes-code.md) · [Index](README.md) · [Next →](unit-1-3-numeric-and-boolean-data-types.md)

Unit 1.1 showed how CPython turns source code into bytecode and runs it. This unit
looks at what that bytecode actually manipulates: **objects**, and the **names** that
point at them. Once you see that every value in Python is an object and every
variable is just a label stuck on one, a whole family of surprises (shared lists,
functions that do or do not change your data, `is` behaving strangely on numbers)
stops being surprising.

## What you will learn

- How to describe every value as an object with an identity, a type and a value.
- Why a variable is a name bound to an object in a namespace dict, and why
  assignment never copies.
- How to predict when a function call changes the caller's data.
- How to classify built-in types as mutable or immutable, and what "changing" an
  immutable really does.
- When to use `is` and when to use `==`, and why the small-int cache and string
  interning make `is` unreliable for values.
- Why names have no type but objects do, and how `type()`, `isinstance()` and duck
  typing fit together.

## JavaScript → Python bridge

Most of this unit will feel familiar if you think of JavaScript *objects*. The
difference is that Python applies the object rules to **every** value, including
numbers and strings.

| JavaScript | Python | The difference that bites |
| --- | --- | --- |
| Primitives vs objects | Everything is an object | `int`, `str` are objects too, just immutable |
| `let x = obj` | `x = obj` binds a name | Same idea, but for *every* value |
| `===` | `==` and `is` | `is` on numbers/strings depends on caching |
| `Object.is(a, b)` | `a is b` | `is` compares identity, not value |
| `typeof x` | `type(x)`, `isinstance` | `isinstance` respects subclasses |
| `delete obj.key` | `del name` | Unbinds a name; the object may live on |

All the examples in this unit share one small setup. It imports a few standard
modules and defines `show_size`, a helper that later units reuse.

```python
import inspect
import math
import sys
import types
import warnings


def show_size(label: str, obj: object) -> None:
    """Print the shallow size in bytes, the type and the id of an object."""
    print(
        f"{label}: {sys.getsizeof(obj)} bytes, "
        f"type={type(obj).__name__}, id={id(obj)}"
    )


print(f"{sys.version_info[:2]=}")
```

```text
sys.version_info[:2]=(3, 15)
```

## 1.2.1 Everything is an object

In JavaScript you learned two worlds: primitives (`number`, `string`, `boolean`,
`undefined`, `null`, `symbol`, `bigint`) that are copied around as plain values, and
objects that live on the heap and are shared through references. Python has only
one world. The integer `499`, the string `"Asha"`, the value `None`, a list, a
function, a module and even the class `int` itself are all **objects**: blocks of
memory on the heap that CPython allocates, reference-counts and eventually frees.

### Identity, type and value

Every object has exactly three properties. Its **identity** is fixed for the whole
lifetime of the object; in CPython, `id()` simply returns the object's memory
address. Its **type** decides which operations the object supports and is also
fixed in practice. Its **value** is the data it holds, and only *mutable* objects
can change it.

| Property | How to read it | Can it change? |
| --- | --- | --- |
| **Identity** | `id(obj)` (memory address) | Never, while it lives |
| **Type** | `type(obj)` | Never (in practice) |
| **Value** | the object, `repr(obj)` | Only for mutable types |

Under the hood, every CPython object starts with the same C header, `PyObject`. It
holds two fields: a **reference count** (how many references point at the object)
and a **pointer to its type object**. That is how `type(x)` answers instantly: it
just follows the pointer. A JavaScript engine such as V8 may store small integers
directly inside a tagged pointer with no heap object at all; CPython never does
that, so even `0` is a full heap object with a header.

> **Note:** `id()` values differ on every run, and CPython may reuse the id of an
> object that has been freed. Compare ids to each other; never rely on the number.

The loop below shows that ordinary values of five different types all have a type
and an identity.

```python
price_in_rupees = 499
cart_items = ["pen", "notebook"]
for value in (price_in_rupees, "Asha", cart_items, 3.5, None):
    print(
        f"type={type(value).__name__:<8} value={value!r:<20} "
        f"has an id: {id(value) > 0}"
    )
```

```text
type=int      value=499                  has an id: True
type=str      value='Asha'               has an id: True
type=list     value=['pen', 'notebook']  has an id: True
type=float    value=3.5                  has an id: True
type=NoneType value=None                 has an id: True
```

Notice that `None` has a real type, `NoneType`. JavaScript's `typeof null` returns
the infamous `"object"`; Python's answer is consistent because `None` really is an
object, the only instance of its class.

### Types, functions, modules and classes are objects too

Because everything is an object, things you might think of as "language
constructs" are values you can store in a list, pass to a function, return from a
function or decorate with attributes. Functions are first-class in JavaScript too,
so that part is familiar. What is new is that **classes and modules** are ordinary
objects as well. The class `int` is an object whose type is `type`, and `type` is
its own type: the chain ends there.

```python
def apply_discount(amount: float) -> float:
    """Return the amount with a 10% discount."""
    return amount * 0.9


first_class_values = [int, apply_discount, math, type, len]
for value in first_class_values:
    display_name = getattr(value, "__name__", value)
    print(f"{display_name!s:<16} is a {type(value).__name__}")

print(f"{type(int) is type=}, {type(type) is type=}")
print(f"{inspect.isclass(int)=}")
print(f"{inspect.isfunction(apply_discount)=}")
print(f"{inspect.ismodule(math)=}")
# functions accept new attributes like any object
apply_discount.author = "Asha"
print(f"{apply_discount.author=}")
```

```text
int              is a type
apply_discount   is a function
math             is a module
type             is a type
len              is a builtin_function_or_method
type(int) is type=True, type(type) is type=True
inspect.isclass(int)=True
inspect.isfunction(apply_discount)=True
inspect.ismodule(math)=True
apply_discount.author='Asha'
```

> **Note:** The notebook prints the three `inspect` checks on a single line. They
> are split here to fit a phone screen; the values are the same.

`len` reports `builtin_function_or_method` rather than `function`: it is written in
C, so it is a different kind of callable object, but still an object. You will meet
`type` again in Phase 2, where it turns out to be the class that builds classes
(the *metaclass*).

### Key points

| Idea | Remember |
| --- | --- |
| Three properties | Identity, type, value |
| `id(obj)` | Memory address in CPython; varies per run |
| No primitives | `499` and `None` are heap objects |
| First-class | Classes, functions, modules are values |
| `type(int)` | `type`, and `type(type) is type` |

## 1.2.2 Names and binding

In JavaScript you usually think of a variable as a box: `let total = 5` puts 5 in
the box. For objects, you already know the box holds a *reference*. Python drops the
box metaphor entirely. A variable is a **name**, a string key in a **namespace**
dictionary, and that key is **bound** to an object. Assignment does not put a value
into a variable; it adds or updates a key in a dict so that it points at an object.

### A namespace is a dict

At module level (and in a notebook or REPL) the namespace is the dict returned by
`globals()`. This is not a metaphor: it is a real `dict`, and writing a key into it
has exactly the same effect as an assignment statement.

```python
delivery_fee = 40
module_namespace = globals()
print(f"{type(module_namespace).__name__=}")
print(f"{module_namespace['delivery_fee']=}")

module_namespace["service_fee"] = 15  # same effect as: service_fee = 15
# created through the dict, so linters cannot see it
print(f"{service_fee=}")  # noqa: F821
```

```text
type(module_namespace).__name__='dict'
module_namespace['delivery_fee']=40
service_fee=15
```

When CPython executes `delivery_fee = 40` at module level, the compiler emits a
`STORE_NAME` (or `STORE_GLOBAL`) bytecode that does a dict store. Reading the name
emits `LOAD_NAME`/`LOAD_GLOBAL`, a dict lookup. Inside a function the compiler is
cleverer: it knows every local name in advance, so it stores locals in a fixed
array in the frame ("fast locals") and uses `LOAD_FAST`/`STORE_FAST` by index. Since
Python 3.13 (PEP 667) calling `locals()` inside a function returns a fresh snapshot
of that array, so writing into it does **not** create a local variable. Only the
module-level `globals()` dict is safe to write through, and even then you should do
it only in demos like this one.

> **Warning:** Creating variables through `globals()` hides them from linters,
> type checkers and readers. Treat it as a way to *understand* binding, not as a
> technique.

### Assignment never copies

`evening_orders = morning_orders` does not copy the list. It evaluates the right
side (looks up `morning_orders` and gets the list object), then binds a **second
name** to that **same object**. If the object is mutable, a change made through one
name is visible through the other, because there is only one object. This matches
what `const b = a` does with a JavaScript array; the difference is that Python
behaves this way for *all* values, not just objects.

The diagram below draws the situation in the style of Python Tutor: names live in
a frame on the left, objects on the right, and arrows are bindings.

```text
Frames            Objects
+----------------+
| morning_orders | ----+
| evening_orders | ----+--> list ['idli', 'dosa', 'vada']
+----------------+
```

```python
morning_orders = ["idli", "dosa"]
evening_orders = morning_orders  # a second name, not a second list
evening_orders.append("vada")
print(f"{morning_orders=}")
print(f"{evening_orders is morning_orders=}")
```

```text
morning_orders=['idli', 'dosa', 'vada']
evening_orders is morning_orders=True
```

If you need an independent list you must ask for a copy explicitly
(`morning_orders.copy()`, `list(morning_orders)` or `morning_orders[:]`). Unit 1.7
covers shallow and deep copies in detail.

### `del` removes a name, not the object

JavaScript's `delete obj.key` removes a property from an object. Python's `del name`
removes a **name** from its namespace, which is the same operation as deleting a
key from the namespace dict. The object the name pointed at is not touched. It
keeps living as long as anything else still refers to it.

CPython tracks this with the reference count in the object header. Each binding,
list slot or dict value that points at an object adds one; removing it subtracts
one. When the count reaches zero, CPython frees the object immediately (a separate
cycle collector handles objects that reference each other; Phase 3 covers it).
`sys.getrefcount` reports the count, plus one for its own temporary argument.

```python
reference_count_before = sys.getrefcount(morning_orders)
del morning_orders
print(f"{'morning_orders' in globals()=}")
print(f"{evening_orders=}  (the list is still alive)")
print(
    f"{sys.getrefcount(evening_orders) == reference_count_before - 1=}"
)
try:
    print(morning_orders)  # noqa: F821
except NameError as error:
    print(f"{type(error).__name__}: {error}")
```

```text
'morning_orders' in globals()=False
evening_orders=['idli', 'dosa', 'vada']  (the list is still alive)
sys.getrefcount(evening_orders) == reference_count_before - 1=True
NameError: name 'morning_orders' is not defined
```

After `del`, the name `morning_orders` is gone from `globals()`, reading it raises
`NameError`, but the list is still reachable through `evening_orders` and its
reference count dropped by exactly one.

> **Note:** There is no way in Python to delete an *object* directly. You can only
> remove references. The object is freed when the last one goes away.

### Key points

| Idea | Remember |
| --- | --- |
| Variable | A key in a namespace dict |
| Module namespace | `globals()`, a real `dict` |
| `b = a` | Binds a second name; never copies |
| Shared mutable | Change via one name, seen via all |
| `del name` | Unbinds the name; refcount drops by one |
| Freeing | CPython frees at refcount zero |

## 1.2.3 Call by object reference

When you call a function, Python binds each parameter name, inside the function's
new frame, to the **same object** the caller passed. Nothing is copied. This is
often called *call by object reference* or *call by sharing*. It is neither C-style
"call by value" (the object is not copied) nor C++-style "call by reference" (the
function cannot rebind the caller's variable).

The model gives two clear rules, and you can predict any call with them:

| Inside the function | Effect on the caller |
| --- | --- |
| **Mutate** (`items.append(...)`) | Visible: same object |
| **Rebind** (`items = [...]`) | Invisible: only the local name moved |

### Mutation is visible, rebinding is not

`add_free_gift` calls a method that changes the list in place, so the caller sees
the change. `replace_order` assigns a new list to its parameter. That only moves
the local name `order_items` to a different object; the caller's name still points
at the original list.

```python
def add_free_gift(order_items: list[str]) -> None:
    """Mutate the caller's list by appending a gift."""
    order_items.append("free sticker")


def replace_order(order_items: list[str]) -> None:
    """Rebind the local name only; the caller's list is untouched."""
    order_items = ["something else"]
    print(f"  inside replace_order: {order_items=}")


customer_order = ["tea"]
add_free_gift(customer_order)
print(f"after add_free_gift: {customer_order=}")
replace_order(customer_order)
print(f"after replace_order: {customer_order=}")
```

```text
after add_free_gift: customer_order=['tea', 'free sticker']
  inside replace_order: order_items=['something else']
after replace_order: customer_order=['tea', 'free sticker']
```

Drawn as frames, the moment inside `replace_order` looks like this:

```text
Frames                       Objects
global
+----------------+
| customer_order | --------> list ['tea', 'free sticker']
+----------------+
replace_order
+----------------+
| order_items    | --------> list ['something else']
+----------------+
```

### Immutable arguments follow the same rule

The same rule applies to immutable arguments. `counter += 1` inside a function
cannot change the `int` object (no `int` can be changed), so it builds a new `int`
and rebinds the local name. The caller sees nothing. The Pythonic fix is to
**return** the new value and let the caller rebind its own name.

```python
def increment(counter: int) -> int:
    """Return counter + 1; rebinding the parameter does not touch the caller."""
    counter += 1
    return counter


visit_count = 10
new_visit_count = increment(visit_count)
print(f"{visit_count=}, {new_visit_count=}")
```

```text
visit_count=10, new_visit_count=11
```

### JavaScript bridge: Python has no primitives

In JavaScript, numbers and strings are passed by value and objects by a copy of the
reference, so you learned two rules. Python has **no primitives**, so it has one
rule: *everything* is passed as a reference to the object. `int` and `str` only
*look* as if they were passed by value, because there is no operation that could
mutate them. A function that receives a list, a dict or an instance of your own
class can change it; a function that receives an `int`, `str` or `tuple` cannot.

> **Warning:** A function that mutates its argument is a common source of bugs,
> because the change "leaks" to the caller. Either document it clearly (the
> standard library uses methods that return `None`, like `list.sort()`) or work on
> a copy and return a new object.

### Predict the output

```python
def reset(scores):
    scores.clear()
    scores = [100]

team_scores = [7, 9]
reset(team_scores)
print(team_scores)
```

<details><summary>Answer</summary>

```text
[]
```

`clear()` mutates the caller's list, so `team_scores` becomes empty. The rebinding
on the next line (`scores = [100]`) only moves the local name `scores` to a new
list; the caller never sees it.

</details>

### Key points

| Idea | Remember |
| --- | --- |
| Parameter passing | Parameter bound to the caller's object |
| Mutate inside | Caller sees the change |
| Rebind inside | Caller sees nothing |
| Immutable argument | Cannot be changed; return a new value |
| JS difference | One rule for all values; no primitives |

## 1.2.4 Mutable vs immutable types

A **mutable** object can change its value in place while keeping its identity. An
**immutable** object's value is fixed when it is created; there is no operation
that changes it. In JavaScript, primitives are immutable and objects are mutable,
so the split lines up roughly with "primitive vs object". In Python the split is a
property of each **type**, and you need to know which side every built-in falls on.

### Full classification

| Immutable | Mutable |
| --- | --- |
| `int`, `float`, `complex`, `bool` | `list` |
| `decimal.Decimal`, `Fraction` | `dict` |
| `str` | `set` |
| `bytes` | `bytearray` |
| `tuple` (items may be mutable) | `memoryview` (writable buffer) |
| `frozenset` | `collections.deque`, `array.array` |
| `frozendict` (new in 3.15) | most user-defined class instances |
| `range`, `NoneType`, code objects | `types.SimpleNamespace` |

`Fraction` is `fractions.Fraction`; the table shortens it to fit. Immutability
matters for more than surprise-avoidance. Only immutable (strictly, *hashable*)
objects can be dict keys or set members, immutable objects can be shared safely
between threads and between parts of a program, and CPython can cache and reuse
them (you will see this in 1.2.5).

### "Changing" an immutable creates a new object

When you write `stock_count += 1`, Python asks the `int` to add in place. `int`
has no in-place method, so Python falls back to `stock_count + 1`, which builds a
**new** `int`, and then rebinds the name to it. `str` behaves the same way. `list`
does define an in-place add (`__iadd__`), which extends the existing list, so the
identity stays the same. The demo compares the `id` before and after `+=`, without
printing the ids themselves.

```python
stock_count = 1_000
id_before = id(stock_count)
stock_count += 1
print(f"int:  same object after += ? {id(stock_count) == id_before}")

greeting_text = "Namaste"
id_before = id(greeting_text)
greeting_text += ", Asha"
print(f"str:  same object after += ? {id(greeting_text) == id_before}")

basket = ["rice"]
id_before = id(basket)
basket += ["dal"]  # list += extends in place
print(f"list: same object after += ? {id(basket) == id_before}")
```

```text
int:  same object after += ? False
str:  same object after += ? False
list: same object after += ? True
```

> **Note:** For lists, `basket += ["dal"]` and `basket = basket + ["dal"]` are
> **not** the same. The first mutates the list (every other name sees the change);
> the second builds a new list and rebinds only `basket`. The predict-the-output
> question at the end of this section turns on exactly this.

### Immutable types have no mutating methods

A useful rule of thumb: an immutable type has no method that modifies it. Methods
on `str` such as `upper()` always **return a new string**. Mutating methods on
mutable types, such as `list.sort()`, change the object and **return `None`**, a
deliberate convention that stops you from chaining them by mistake. Trying to
assign into an immutable object raises `TypeError`.

```python
coordinates = (12.97, 77.59)
try:
    coordinates[0] = 13.0
except TypeError as error:
    print(f"{type(error).__name__}: {error}")

city = "bengaluru"
print(f"{city.upper()=}, {city=}  (unchanged)")
print(f"{basket.sort()=}  (sorted in place, returns None)")
```

```text
TypeError: 'tuple' object does not support item assignment
city.upper()='BENGALURU', city='bengaluru'  (unchanged)
basket.sort()=None  (sorted in place, returns None)
```

> **Warning:** A JavaScript habit to unlearn: `sorted_items = items.sort()` sets
> `sorted_items` to `None` in Python. Use `sorted(items)` when you want a new list.

### A tuple is only as immutable as its items

The table says "`tuple` (items may be mutable)". A tuple fixes *which objects* it
holds, not the *values* of those objects. If one item is a list, you cannot replace
that list, but you can still append to it. Such a tuple is also no longer hashable,
because its value can change.

```python
order_record = ("ORD-7", ["tea"])
try:
    order_record[1] = ["coffee"]
except TypeError as error:
    print(f"{type(error).__name__}: {error}")
order_record[1].append("biscuit")
print(f"{order_record=}")
try:
    hash(order_record)
except TypeError as error:
    print(f"{type(error).__name__}: {error}")
```

```text
TypeError: 'tuple' object does not support item assignment
order_record=('ORD-7', ['tea', 'biscuit'])
TypeError: unhashable type: 'list'
```

This is the same as `Object.freeze` in JavaScript, which is shallow: a frozen object
can still hold a mutable array.

### Predict the output

```python
shopping_list = ["milk"]
other_list = shopping_list
other_list = other_list + ["bread"]
print(shopping_list)
```

<details><summary>Answer</summary>

```text
['milk']
```

`other_list + ["bread"]` builds a **new** list and rebinds `other_list` to it;
`shopping_list` still points at the original. Compare `basket += [...]` above,
which extends the list in place.

</details>

### Key points

| Idea | Remember |
| --- | --- |
| Immutable | `int`, `float`, `str`, `bytes`, `tuple`, … |
| Mutable | `list`, `dict`, `set`, `bytearray`, … |
| `+=` on immutable | New object, name rebound |
| `+=` on `list` | Extends in place, same object |
| Mutating methods | Return `None` (`list.sort()`) |
| Tuple | Fixed items; items may be mutable |

## 1.2.5 Identity vs equality

JavaScript has `==` (loose) and `===` (strict) equality, plus `Object.is` for the
edge cases. Python has two operators that ask two *different questions*:

| Operator | Question | Implemented by |
| --- | --- | --- |
| `a == b` | Equal **values**? | `a.__eq__(b)`, defined per type |
| `a is b` | **Same object**? | Identity; cannot be overridden |

`a is b` is a single pointer comparison in C: it is true only when both names refer
to the very same object, and no class can change that. `a == b` calls the
`__eq__` special method, which each type defines to mean "same value". If a class
does not define `__eq__`, it inherits the default from `object`, which falls back to
identity.

The rule for everyday code is simple. **Use `is` only for singletons**: `None`,
`True`, `False`, `...` (`Ellipsis`), and sentinel objects you create yourself (for
example `MISSING = object()`). Use `==` for everything else. PEP 8 spells out the
singleton rule: write `if discount_code is None`, never `== None`.

### `__eq__` defines value equality

`Price` stores an amount in paise and defines `__eq__` so that two `Price` objects
with the same amount compare equal. They are still two separate objects, so `is`
says `False`. Returning `NotImplemented` for foreign types tells Python to try the
other operand's `__eq__` (or fall back to identity) instead of guessing.

```python
class Price:
    """An amount in paise that compares by value."""

    def __init__(self, paise: int) -> None:
        self.paise = paise

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Price):
            return NotImplemented
        return self.paise == other.paise


first_price = Price(49_900)
second_price = Price(49_900)
print(f"{first_price == second_price=}  (__eq__ compares paise)")
print(f"{first_price is second_price=}  (two distinct objects)")
first_list, second_list = [1, 2], [1, 2]
print(f"{first_list == second_list=}, {first_list is second_list=}")
```

```text
first_price == second_price=True  (__eq__ compares paise)
first_price is second_price=False  (two distinct objects)
first_list == second_list=True, first_list is second_list=False
```

Note the JavaScript contrast: `[1, 2] === [1, 2]` is `false` in JavaScript because
`===` compares object references. Python's `==` compares list *contents*, so it
gives `True`. Python's `is` is the operator that behaves like `===` on objects.

### The small-integer cache

Creating an `int` object costs an allocation, and small numbers are used
everywhere (loop counters, indexes, lengths). So CPython pre-creates the small
integers when the interpreter starts and hands out the same objects every time one
is needed. Two names bound to the same small value can therefore be the *same
object*. The cached range grew in Python 3.15:

| Python | Cached range |
| --- | --- |
| up to 3.14 | `-5` … `256` |
| **3.15** (*changed in 3.15*) | `-5` … `1024` |

The demo builds the numbers at run time with `int("…")`. If it used literals, the
compiler would merge equal constants in one code block into a single object and
hide the effect. This whole behaviour is an implementation detail, which is exactly
why you must never use `is` to compare numbers.

```python
for number_text in ["256", "257", "1024", "1025"]:
    first_number, second_number = int(number_text), int(number_text)
    is_same_object = first_number is second_number
    print(
        f"{number_text:>5}: equal={first_number == second_number}, "
        f"same object={is_same_object}"
    )
if sys.version_info < (3, 15):
    print("Note: on this Python the cache ends at 256, so 1024 is not shared")
```

```text
  256: equal=True, same object=True
  257: equal=True, same object=True
 1024: equal=True, same object=True
 1025: equal=True, same object=False
```

On Python 3.15, `257` and `1024` are shared; on 3.14 they would not be. Values are
equal in every row; only identity changes.

### String interning

CPython also shares some strings. Identifier-like string literals and all names
(variable, attribute and function names) are **interned**: stored once in an
internal table and reused. Strings built at run time, by `join`, concatenation or
reading a file, usually are not. `sys.intern` interns a string on request and
returns the shared copy. That can save memory when the same string appears many
times, and it turns later comparisons into fast identity checks; CPython relies on
this for the dicts that hold attribute names.

```python
built_status = "".join(["sh", "ipped"])
literal_status = "shipped"
print(f"{built_status == literal_status=}, {built_status is literal_status=}")

interned_status = sys.intern(built_status)
print(
    f"{interned_status is literal_status=}  "
    "(sys.intern returned the shared copy)"
)
```

```text
built_status == literal_status=True, built_status is literal_status=False
interned_status is literal_status=True  (sys.intern returned the shared copy)
```

### The `SyntaxWarning` for `is` with a literal

Because the result of `x is 5` or `name is "Asha"` depends on caching, version and
context, the compiler flags it. Since Python 3.8 compiling such code emits a
**`SyntaxWarning`** that suggests `==`. The demo compiles a small snippet and
captures the warning instead of letting it print.

```python
suspicious_source = "order_count = 5\nprint(order_count is 5)"
with warnings.catch_warnings(record=True) as caught_warnings:
    warnings.simplefilter("always")
    compile(suspicious_source, "<demo>", "exec")
for caught_warning in caught_warnings:
    print(f"{caught_warning.category.__name__}: {caught_warning.message}")
```

```text
SyntaxWarning: "is" with 'int' literal. Did you mean "=="?
```

> **Warning:** If you see this warning in your own code, it is a bug, not a style
> issue. Replace `is` with `==`.

### Key points

| Idea | Remember |
| --- | --- |
| `==` | Value equality via `__eq__` |
| `is` | Same object; cannot be overridden |
| When to use `is` | Singletons: `None`, `True`, `False`, sentinels |
| Small-int cache | `-5..1024` in 3.15 (was `-5..256`) |
| Interning | Names and identifier literals; `sys.intern` |
| `is` with literal | `SyntaxWarning` since 3.8 |

## 1.2.6 Dynamic typing

Python is **dynamically typed**, like JavaScript: types are checked while the code
runs, not before. The precise way to say it is: **names have no types; objects
do**. A name is just a dict key, and the binding can point at an `int` now and a
`str` a moment later. The object, on the other hand, carries its type pointer in its
header for its whole life.

Python is also **strongly typed**, which JavaScript is not. `"3" + 4` is `"34"` in
JavaScript, but a `TypeError` in Python: objects refuse operations their type does
not support instead of silently converting.

### Names have no types

Type hints such as `quantity: int` document intent and let tools like pyright or
mypy find mistakes before you run the code. The interpreter itself does **not**
enforce them; it stores the annotation and moves on. Phase 4 covers static typing
properly.

```python
shipment_reference = 1042
print(f"{type(shipment_reference).__name__=}")
shipment_reference = "SHIP-1042"
print(f"{type(shipment_reference).__name__=}")

hinted_quantity: int = "three"  # legal at run time: hints are not checked
print(f"{hinted_quantity=}, {type(hinted_quantity).__name__=}")
```

```text
type(shipment_reference).__name__='int'
type(shipment_reference).__name__='str'
hinted_quantity='three', type(hinted_quantity).__name__='str'
```

> **Note:** This is the same situation as TypeScript: annotations are erased at
> run time. The difference is that Python keeps them available in
> `__annotations__` for libraries such as FastAPI and Pydantic to read.

### `type()` vs `isinstance()`

`type(x) is T` matches one exact class. `isinstance(x, T)` also accepts
**subclasses**, and it accepts a tuple of types or an `X | Y` union. It is the
Python counterpart of JavaScript's `instanceof`, while `type()` is closer to a
precise `typeof`. Prefer `isinstance` for checks, because code that rejects
subclasses breaks the moment someone extends your class.

```python
class DiscountedPrice(Price):
    """A Price subclass."""


sale_price = DiscountedPrice(39_900)
print(f"{type(sale_price) is Price=}")
print(f"{isinstance(sale_price, Price)=}")
print(f"{isinstance(3.5, int | float)=}")
print(f"{isinstance(True, int)=}  (bool is a subclass of int; see 1.3.6)")
```

```text
type(sale_price) is Price=False
isinstance(sale_price, Price)=True
isinstance(3.5, int | float)=True
isinstance(True, int)=True  (bool is a subclass of int; see 1.3.6)
```

> **Warning:** `isinstance(True, int)` is `True`. If you must accept integers but
> reject booleans, check for `bool` first. Unit 1.3 explains why `bool` subclasses
> `int`.

### Duck typing preview

Most Python code does not check types at all. It simply calls the method it needs
and lets any object that has it work: "if it walks like a duck and quacks like a
duck, it is a duck". This is how idiomatic JavaScript works too, where any object
with a `then` method can be awaited. Below, `send_receipt` works with two unrelated
classes and even with an ad-hoc `SimpleNamespace`, because all three have a
`render()` method. Phase 2 formalises this with *protocols*, which let type
checkers verify duck typing statically.

```python
class PaperReceipt:
    """A receipt that is printed."""

    def render(self) -> str:
        """Return a description of the receipt."""
        return "Printed receipt"


class EmailReceipt:
    """A receipt that is emailed; unrelated to PaperReceipt."""

    def render(self) -> str:
        """Return a description of the receipt."""
        return "Emailed receipt"


def send_receipt(receipt: PaperReceipt | EmailReceipt) -> None:
    """Works with any object that has a render() method."""
    print(receipt.render())


ad_hoc_receipt = types.SimpleNamespace(render=lambda: "Ad-hoc receipt")
for receipt in (PaperReceipt(), EmailReceipt(), ad_hoc_receipt):
    send_receipt(receipt)
```

```text
Printed receipt
Emailed receipt
Ad-hoc receipt
```

### Under the hood: names live in `__dict__`, objects carry headers

The namespace idea from 1.2.2 runs all the way down. A module's globals are
literally the module object's `__dict__`, and an instance's attributes live in its
own `__dict__` (which `vars()` returns). Every object also carries the `PyObject`
header described in 1.2.1 (reference count and type pointer), which is why even the
integer `0` costs bytes. `show_size` from the setup prints the shallow size, the
type and the id.

```python
print(f"{globals() is sys.modules['__main__'].__dict__=}")
print(f"{vars(first_price)=}")
show_size("small int 0", 0)
show_size("None", None)
show_size("empty list", [])
```

```text
globals() is sys.modules['__main__'].__dict__=True
vars(first_price)={'paise': 49900}
small int 0: 28 bytes, type=int, id=22124928
None: 16 bytes, type=NoneType, id=22109848
empty list: 56 bytes, type=list, id=140266921353408
```

> **Note:** The `id=` numbers change on every run. The small ids for `0` and `None`
> point into the interpreter's static data: these objects are built in and
> *immortal* (PEP 683), so they are never freed. The empty list is a normal heap
> object with a much larger address.

The sizes tell a story too. `None` is just the 16-byte header. An `int` adds a size
field and its digits, giving 28 bytes for `0`. An empty `list` adds a length, a
pointer to its item array and a capacity, giving 56 bytes. A JavaScript engine can
store a small integer in no extra memory at all; in Python, the price of "everything
is an object" is this per-object overhead.

### Key points

| Idea | Remember |
| --- | --- |
| Dynamic typing | Names untyped, objects typed |
| Strong typing | No silent `"3" + 4` coercion |
| Type hints | Not enforced at run time |
| `type(x) is T` | Exact class only |
| `isinstance(x, T)` | Subclasses too; tuples and unions |
| Duck typing | Call the method; don't check the type |
| `__dict__` | Modules and instances store names in dicts |

## Recap

| Concept | Takeaway | JavaScript equivalent |
| --- | --- | --- |
| Everything is an object | Identity, type, value; classes too | Objects, plus primitives |
| Names and binding | Name = key in a namespace dict | Variable holds a reference |
| Assignment | Never copies; names can share | Same for objects |
| `del` | Removes a name; object freed later | `delete` removes a property |
| Call by object reference | Mutation visible, rebinding not | Same for objects |
| Mutable vs immutable | `list` changes in place; `str` never | Objects vs primitives |
| `is` vs `==` | `is` for singletons only | `Object.is` vs `===` |
| Small-int cache | `-5..1024` in 3.15 | No equivalent |
| Dynamic typing | Prefer `isinstance`, duck typing | `typeof`, `instanceof` |

## Further reading

- [Data model: objects, values and types](https://docs.python.org/3/reference/datamodel.html#objects-values-and-types)
- [Execution model: naming and binding](https://docs.python.org/3/reference/executionmodel.html#naming-and-binding)
- [Programming FAQ: functions with output parameters](https://docs.python.org/3/faq/programming.html#how-do-i-write-a-function-with-output-parameters-call-by-reference)
- [`sys.intern`](https://docs.python.org/3/library/sys.html#sys.intern)
- [`isinstance`](https://docs.python.org/3/library/functions.html#isinstance)
- [`id`](https://docs.python.org/3/library/functions.html#id)
- [PEP 8: programming recommendations (comparisons to singletons)](https://peps.python.org/pep-0008/#programming-recommendations)
- [PEP 667: consistent views of namespaces](https://peps.python.org/pep-0667/)
- [PEP 683: immortal objects](https://peps.python.org/pep-0683/)

[← Previous](unit-1-1-how-python-executes-code.md) · [Index](README.md) · [Next →](unit-1-3-numeric-and-boolean-data-types.md)
