"""Unit 2.4 — The Data Model: Special (Dunder) Methods (with Lab 2.4)."""

from nbformat import NotebookNode

from nb_builder import code, md, predict_cells

UNIT_SETUP_SOURCE = '''
import dis
import functools
import inspect
import math  # noqa: F401 (Lab 2.4)
import sys
import time
from collections import UserDict, UserList
from collections.abc import Callable, Iterable, Iterator, Mapping, MutableMapping
from decimal import ROUND_HALF_UP, Decimal
from typing import Self

PAISE = Decimal("0.01")


def raised_error_name(thunk: Callable[[], object]) -> str:
    """Call thunk and return the name of the exception it raised, or "no error"."""
    try:
        thunk()
    except Exception as error:
        return type(error).__name__
    return "no error"


def raised_message(thunk: Callable[[], object]) -> str:
    """Call thunk and return "ErrorName: message" for the exception it raised, or "no error"."""
    try:
        thunk()
    except Exception as error:
        return f"{type(error).__name__}: {error}"
    return "no error"


def set_attribute(target: object, attribute_name: str, value: object) -> None:
    """`target.attribute_name = value` as a call, for use inside raised_error_name(lambda: ...)."""
    setattr(target, attribute_name, value)


print(f"{sys.version_info[:2]=}")
'''


def _overview_cells() -> list[NotebookNode]:
    """Unit opener and setup."""
    return [
        md(
            """
            ## Unit 2.4 — The Data Model: Special (Dunder) Methods

            **Objectives**

            - Explain the data-model idea: syntax such as `len(x)`, `x[i]` and `a + b` calls
              special ("dunder") methods on the type.
            - Write `__repr__`, `__str__` and `__format__`, and know which one each tool uses.
            - Implement value equality and hashing correctly, and ordering with
              `functools.total_ordering`.
            - Emulate containers (indexing, slicing, membership, iteration, `__missing__`) and
              know why `UserDict` / `UserList` are safer bases than `dict` / `list`.
            - Make objects callable, and make them work with `+`, `sum()`, `+=`, `*`, `/`, `@`.
            - Describe how Python looks special methods up, and read the `BINARY_OP` bytecode.

            **JS bridge**

            | JavaScript | Python | The difference that bites |
            | --- | --- | --- |
            | `toString()` | `__str__` | Python also has `__repr__`, the developer view used by the REPL, containers and `!r` |
            | `Symbol.toPrimitive` / `valueOf()` | `__format__`, `__int__`, `__float__`, `__index__` | One method per conversion, no hint argument |
            | No operator overloading (`a + b` on objects gives `"[object Object]..."`) | `__add__`, `__lt__`, `__matmul__`, … | Python operators are method calls; returning `NotImplemented` lets the other operand try |
            | `===` on objects compares identity | `==` calls `__eq__` (default: identity) | Defining `__eq__` switches hashing **off** until you define `__hash__` |
            | `Map` keys compare by identity | `dict` keys compare by `__hash__` + `__eq__` | Two equal value objects are the **same** key |
            | `Symbol.iterator` | `__iter__` | Also `__contains__`, `__reversed__`, `__len__` |
            | `Proxy` with `get` trap for `obj[key]` | `__getitem__` | `__getitem__` receives a `slice` object for `x[1:3]` |
            | Callable objects need a function wrapper | `__call__` | Any instance can be called like a function |

            The next cell is this unit's setup.
            """
        ),
        code(UNIT_SETUP_SOURCE),
    ]


def _data_model_cells() -> list[NotebookNode]:
    """2.4.1 The data-model idea: one demo cell per table row."""
    return [
        md(
            """
            ### 2.4.1 The data-model idea

            Python's syntax and built-in functions are a thin layer over **special methods**
            (also called *dunder* methods, for the double underscores). `len(x)` calls
            `type(x).__len__(x)`; `a + b` calls `type(a).__add__(a, b)`. If your class defines
            the method, the syntax works on your objects exactly as on built-ins. This is what
            "Pythonic" usually means for a class: it plugs into the language instead of
            inventing `getLength()` or `addTo()` methods.

            | Syntax | Special method |
            | --- | --- |
            | `len(x)` | `__len__` |
            | `x[i]` | `__getitem__` |
            | `x + y` | `__add__` |
            | `x()` | `__call__` |
            | `for item in x` | `__iter__` |
            | `item in x` | `__contains__` |
            | `with x` | `__enter__` / `__exit__` |
            | `hash(x)` | `__hash__` |
            | `bool(x)` | `__bool__` |
            | `format(x, spec)` | `__format__` |

            You rarely call a dunder yourself; you implement it and let the syntax call it. The
            class below implements **every row** of the table, so it is longer than a usual
            cell. Each row then gets its own demo cell, which also shows the explicit call
            Python makes, `type(x).__method__(x, ...)`.
            """
        ),
        code(
            '''
            class OrderBatch:
                """A named batch of order ids that supports every row of the table above."""

                def __init__(self, name: str, order_ids: Iterable[str]) -> None:
                    self.name = name
                    self.order_ids = tuple(order_ids)

                def __repr__(self) -> str:
                    return f"OrderBatch({self.name!r}, {list(self.order_ids)!r})"

                def __len__(self) -> int:
                    return len(self.order_ids)

                def __getitem__(self, index: int) -> str:
                    return self.order_ids[index]

                def __add__(self, other: object) -> OrderBatch:
                    if not isinstance(other, OrderBatch):
                        return NotImplemented
                    return OrderBatch(f"{self.name}+{other.name}", self.order_ids + other.order_ids)

                def __call__(self, courier: str) -> str:
                    return f"{len(self)} orders of {self.name} handed to {courier}"

                def __iter__(self) -> Iterator[str]:
                    return iter(self.order_ids)

                def __contains__(self, order_id: object) -> bool:
                    return order_id in self.order_ids

                def __enter__(self) -> Self:
                    print(f"  lock {self.name}")
                    return self

                def __exit__(self, *exc_info: object) -> None:
                    print(f"  unlock {self.name}")

                def __eq__(self, other: object) -> bool:
                    if not isinstance(other, OrderBatch):
                        return NotImplemented
                    return (self.name, self.order_ids) == (other.name, other.order_ids)

                def __hash__(self) -> int:
                    return hash((self.name, self.order_ids))

                def __bool__(self) -> bool:
                    return bool(self.order_ids)

                def __format__(self, spec: str) -> str:
                    if spec == "short":
                        return f"{self.name} ({len(self)} orders)"
                    return format(repr(self), spec)


            morning_batch = OrderBatch("morning", ["ORD-1", "ORD-2", "ORD-3"])
            evening_batch = OrderBatch("evening", ["ORD-4", "ORD-5"])
            print(morning_batch)
            '''
        ),
        md(
            """
            #### `len(x)` → `__len__`

            `len()` calls `__len__` and checks the result is a non-negative `int` (2.4.5).
            """
        ),
        code(
            """
            print(f"{len(morning_batch)=}")
            print(f"{type(morning_batch).__len__(morning_batch)=}  (what len() calls)")
            """
        ),
        md(
            """
            #### `x[i]` → `__getitem__`

            Square brackets pass the index (or a `slice`, see 2.4.6) to `__getitem__`. Here the
            tuple underneath handles negative indexes and raises `IndexError`.
            """
        ),
        code(
            """
            print(f"{morning_batch[0]=}, {morning_batch[-1]=}")
            print(f"{type(morning_batch).__getitem__(morning_batch, 1)=}")
            print(raised_message(lambda: morning_batch[10]))
            """
        ),
        md(
            """
            #### `x + y` → `__add__`

            `+` calls `__add__` on the **left** operand. Returning `NotImplemented` for unknown
            types (instead of raising) gives the right operand a chance (2.4.9); when nobody
            handles it, Python raises a `TypeError` that names both types.
            """
        ),
        code(
            """
            combined_batch = morning_batch + evening_batch
            print(f"{combined_batch=}")
            print(f"{type(morning_batch).__add__(morning_batch, 'ORD-9')=}")
            print(raised_message(lambda: morning_batch + "ORD-9"))
            """
        ),
        md(
            """
            #### `x()` → `__call__`

            Parentheses after any object call `type(obj).__call__(obj, ...)`. Functions are just
            objects whose type defines `__call__` (2.4.7).
            """
        ),
        code(
            """
            print(morning_batch("BlueDart"))
            print(f"{callable(morning_batch)=}, {callable(42)=}")
            """
        ),
        md(
            """
            #### `for item in x` → `__iter__`

            A `for` loop calls `iter(x)`, which calls `__iter__` and must return an iterator
            (Unit 1.13). Unpacking, `list()`, `sorted()` and comprehensions use the same path.
            """
        ),
        code(
            """
            for order_id in morning_batch:
                print(f"  shipping {order_id}")
            first_order, *other_orders = morning_batch
            print(f"{first_order=}, {other_orders=}, {sorted(morning_batch, reverse=True)=}")
            """
        ),
        md(
            """
            #### `item in x` → `__contains__`

            `in` calls `__contains__` and converts the result to `bool`. Without it, Python
            falls back to scanning `__iter__` (or `__getitem__`), which is slower (2.4.6).
            """
        ),
        code(
            """
            print(f"{'ORD-2' in morning_batch=}, {'ORD-9' not in morning_batch=}")
            print(f"{type(morning_batch).__contains__(morning_batch, 'ORD-3')=}")
            """
        ),
        md(
            """
            #### `with x` → `__enter__` / `__exit__`

            Covered in Unit 1.14.9: `with` calls `__enter__` (its return value is bound by
            `as`) and always calls `__exit__`, even when the block raises.
            """
        ),
        code(
            """
            with morning_batch as locked_batch:
                print(f"  inside the block: {locked_batch is morning_batch=}")
            """
        ),
        md(
            """
            #### `hash(x)` → `__hash__`

            `hash()` calls `__hash__`; sets and dict keys use it together with `__eq__`
            (2.4.3). Two equal batches hash the same, so a set keeps one of them.
            """
        ),
        code(
            """
            same_morning_batch = OrderBatch("morning", ["ORD-1", "ORD-2", "ORD-3"])
            print(f"{morning_batch == same_morning_batch=}, {morning_batch is same_morning_batch=}")
            print(f"{hash(morning_batch) == hash(same_morning_batch)=}")
            print(f"{len({morning_batch, same_morning_batch, evening_batch})=}")
            """
        ),
        md(
            """
            #### `bool(x)` → `__bool__`

            `if x:`, `while x:`, `not x`, `and` / `or` all ask `bool(x)`, which calls `__bool__`
            (falling back to `__len__`, 2.4.5).
            """
        ),
        code(
            """
            empty_batch = OrderBatch("night", [])
            for batch in (morning_batch, empty_batch):
                print(f"{batch.name}: {bool(batch)=}, {'has orders' if batch else 'empty'}")
            """
        ),
        md(
            """
            #### `format(x, spec)` → `__format__`

            `format(x, spec)`, `f"{x:spec}"` and `str.format` pass the text after the colon to
            `__format__`. The class decides what a spec means: here `"short"` is a custom spec,
            and anything else is applied to the repr text.
            """
        ),
        code(
            """
            print(format(morning_batch, "short"))
            print(f"[{morning_batch:short}] [{evening_batch:short}]")
            print(f"[{evening_batch:>48}]")
            """
        ),
    ]


def _representation_cells() -> list[NotebookNode]:
    """2.4.2 Representation."""
    return [
        md(
            """
            ### 2.4.2 Representation

            Python has **two** text forms for an object:

            | Method | Audience | Used by | Goal |
            | --- | --- | --- | --- |
            | `__repr__` | developers | the REPL, `repr()`, `!r`, debuggers, logs, **containers** | unambiguous; ideally valid Python that rebuilds the object |
            | `__str__` | end users | `print()`, `str()`, f-strings without a conversion | readable |

            If a class defines only `__repr__`, `str()` falls back to it, so **always write
            `__repr__` first**. The default from `object` shows the class and the memory
            address, which helps nobody (and changes every run, so the cell below cuts it off).
            """
        ),
        code(
            '''
            class PlainMoney:
                """No __repr__ or __str__: object's defaults apply."""

                def __init__(self, amount: Decimal, currency: str = "INR") -> None:
                    self.amount = amount
                    self.currency = currency


            plain_price = PlainMoney(Decimal("250"))
            default_text = repr(plain_price)
            print(default_text.split(" at ")[0] + " at 0x…>")
            print(f"{str(plain_price) == default_text=}  (str falls back to repr)")
            '''
        ),
        md(
            """
            With only `__repr__`, both `print()` and containers show it. Containers **always**
            use `repr` for their elements, even inside `print()`, so that `["1"]` and `[1]` look
            different.
            """
        ),
        code(
            """
            class ReprOnlyMoney(PlainMoney):
                def __repr__(self) -> str:
                    return f"ReprOnlyMoney({str(self.amount)!r}, {self.currency!r})"


            print(ReprOnlyMoney(Decimal("250")))
            print([ReprOnlyMoney(Decimal("1")), ReprOnlyMoney(Decimal("2"), "USD")])
            print(["1", 1])
            """
        ),
        md(
            """
            Now `Money` from Unit 2.1.5 grows. The amount is converted to a `Decimal` rounded
            to the paisa, `__repr__` produces text you could paste back into Python, and
            `__str__` is what a customer sees. `__format__` adds **custom format specs**:

            | Spec | Result for `Money("1234.5")` |
            | --- | --- |
            | `""` (plain `f"{m}"`) | same as `str(m)`: `INR 1,234.50` |
            | `"symbol"` | `₹1,234.50` (`$`, `€` for USD, EUR) |
            | anything else, e.g. `",.0f"` | applied to the amount: `INR 1,234` |
            """
        ),
        code(
            '''
            CURRENCY_SYMBOLS = {"INR": "₹", "USD": "$", "EUR": "€"}


            class Money:
                """An amount in one currency (Unit 2.1.5's Money, growing through Unit 2.4)."""

                def __init__(self, amount: Decimal | int | str, currency: str = "INR") -> None:
                    if not (len(currency) == 3 and currency.isalpha() and currency.isupper()):
                        raise ValueError(f"invalid currency code: {currency!r}")
                    self.amount = Decimal(amount).quantize(PAISE, rounding=ROUND_HALF_UP)
                    self.currency = currency

                def __repr__(self) -> str:
                    return f"Money({str(self.amount)!r}, {self.currency!r})"

                def __str__(self) -> str:
                    return f"{self.currency} {self.amount:,.2f}"

                def __format__(self, spec: str) -> str:
                    if spec == "":
                        return str(self)
                    if spec == "symbol":
                        symbol = CURRENCY_SYMBOLS.get(self.currency, self.currency + " ")
                        return f"{symbol}{self.amount:,.2f}"
                    return f"{self.currency} {format(self.amount, spec)}"
            '''
        ),
        md(
            """
            `repr` vs `str`, and the `!r` / `!s` conversions in f-strings. The `=` specifier
            (`f"{x=}"`) uses `repr` by default.
            """
        ),
        code(
            """
            laptop_price = Money("54999.5")
            print(repr(laptop_price))
            print(str(laptop_price))
            print(f"{laptop_price!r} / {laptop_price!s} / {laptop_price=}")
            print([laptop_price, Money(19, "USD")])
            """
        ),
        md(
            """
            The custom specs. `f"{price:symbol}"` passes the string `"symbol"` to `__format__`;
            any other spec is handed to `Decimal.__format__`, so the standard format
            mini-language (width, `,`, precision) works on the amount.
            """
        ),
        code(
            """
            print(f"{laptop_price}")
            print(f"{laptop_price:symbol} / {Money('19.99', 'USD'):symbol} / {Money(5, 'JPY'):symbol}")
            print(f"{laptop_price:,.0f}")
            print(f"[{laptop_price:>12,.2f}]")
            print(raised_message(lambda: format(laptop_price, "bogus")))
            """
        ),
        md(
            """
            `object.__format__` (what you inherit) accepts only the empty spec; anything else
            raises `TypeError`. That is why `PlainMoney` cannot be padded in an f-string until
            it defines `__format__`. A safe default for your own `__format__` is to apply the
            spec to `str(self)`, as `OrderBatch` did with its repr.
            """
        ),
        code(
            """
            print(f"{format(plain_price, '') == str(plain_price)=}")
            print(raised_message(lambda: f"{plain_price:>20}"))
            """
        ),
    ]


def _equality_cells() -> list[NotebookNode]:
    """2.4.3 Equality and hashing."""
    return [
        md(
            """
            ### 2.4.3 Equality and hashing

            Without `__eq__`, `==` falls back to identity (`is`), like `===` on JS objects. Two
            `Money("10")` objects are different objects, so they are not equal.
            """
        ),
        code(
            """
            print(f"{Money(10) == Money(10)=}  (no __eq__ yet: identity)")
            """
        ),
        md(
            """
            **`__eq__` returning `NotImplemented`.** When `__eq__` does not know the other type
            it returns the special value `NotImplemented` (not `False`, and never raises). For
            `a == b` Python then tries `b.__eq__(a)`, and if that is also `NotImplemented` it
            falls back to `a is b`. The trace below shows the sequence. `!=` calls `__ne__`,
            which by default inverts `__eq__`, so you only write `__eq__`.
            """
        ),
        code(
            '''
            class LoudEquality:
                """Prints every __eq__ call and declines to answer."""

                def __init__(self, label: str) -> None:
                    self.label = label

                def __eq__(self, other: object) -> bool:
                    print(f"  {self.label}.__eq__({getattr(other, 'label', other)!r})")
                    return NotImplemented


            left_side, right_side = LoudEquality("left"), LoudEquality("right")
            print(f"result: {left_side == right_side}  (both declined: identity fallback)")
            print(f"result: {left_side != right_side}  (__ne__ inverts __eq__)")
            '''
        ),
        md(
            """
            Value equality for `Money`: compare amount and currency, and return
            `NotImplemented` for anything that is not `Money`. Comparing with an `int` then gives
            `False` instead of a crash.

            **Defining `__eq__` sets `__hash__ = None`.** Python assumes that if you changed
            what "equal" means, the inherited identity hash is now wrong (equal objects must
            have equal hashes). So the class becomes **unhashable**: no sets, no dict keys.
            """
        ),
        code(
            '''
            class EqualityOnlyMoney(Money):
                """Adds value equality but no __hash__."""

                def __eq__(self, other: object) -> bool:
                    if not isinstance(other, Money):
                        return NotImplemented
                    return (self.amount, self.currency) == (other.amount, other.currency)


            print(f"{EqualityOnlyMoney(10) == EqualityOnlyMoney('10.00')=}")
            print(f"{EqualityOnlyMoney(10) == 10=}  (NotImplemented on both sides -> False)")
            print(f"{EqualityOnlyMoney.__hash__ is None=}")
            print(raised_message(lambda: {EqualityOnlyMoney(10)}))
            '''
        ),
        md(
            """
            **Hash only immutable fields.** A hash must never change while the object is in a
            set or used as a dict key. The trap below hashes a mutable field, then changes it:
            the object is still in the set, but Python looks in the wrong bucket and reports it
            missing.
            """
        ),
        code(
            '''
            class MutableTag:
                """BUG: hash depends on a field that can change."""

                def __init__(self, label: str) -> None:
                    self.label = label

                def __eq__(self, other: object) -> bool:
                    return isinstance(other, MutableTag) and self.label == other.label

                def __hash__(self) -> int:
                    return hash(self.label)


            sale_tag = MutableTag("sale")
            tags = {sale_tag}
            sale_tag.label = "clearance"
            print(f"{sale_tag in tags=}  (lost: hash changed after insertion)")
            print(f"{any(tag is sale_tag for tag in tags)=}  (but it is still there)")
            '''
        ),
        md(
            """
            The fix is to make the fields that take part in `__eq__` and `__hash__` read-only.
            This `Money` stores `_amount` and `_currency` behind properties with no setters (Unit
            2.1.6), and hashes the same tuple it compares. Because the amount is quantized to
            paise, `Money("10")` and `Money("10.00")` hold the same `Decimal` and hash equally.
            Lab 2.4 finishes the job (ordering, arithmetic, `sum()`).
            """
        ),
        code(
            '''
            class Money:
                """Read-only amount and currency; equality and hashing by value."""

                def __init__(self, amount: Decimal | int | str, currency: str = "INR") -> None:
                    if not (len(currency) == 3 and currency.isalpha() and currency.isupper()):
                        raise ValueError(f"invalid currency code: {currency!r}")
                    self._amount = Decimal(amount).quantize(PAISE, rounding=ROUND_HALF_UP)
                    self._currency = currency

                @property
                def amount(self) -> Decimal:
                    return self._amount

                @property
                def currency(self) -> str:
                    return self._currency

                def __repr__(self) -> str:
                    return f"Money({str(self._amount)!r}, {self._currency!r})"

                def __str__(self) -> str:
                    return f"{self._currency} {self._amount:,.2f}"

                def __eq__(self, other: object) -> bool:
                    if not isinstance(other, Money):
                        return NotImplemented
                    return (self._amount, self._currency) == (other._amount, other._currency)

                def __hash__(self) -> int:
                    return hash((self._amount, self._currency))
            '''
        ),
        md(
            """
            Equal values collapse in a set and find the same dict entry; a different currency
            is a different value; assigning to `amount` fails.
            """
        ),
        code(
            """
            price_list = {Money(10): "pen", Money("49.99"): "notebook"}
            print(f"{price_list[Money('10.00')]=}")
            print(f"{len({Money(10), Money('10.0'), Money(10, 'USD')})=}")
            print(f"{Money(10) == Money(10, 'USD')=}")
            print(raised_message(lambda: set_attribute(Money(10), "amount", Decimal(0))))
            """
        ),
        md(
            """
            #### Under the hood: `__hash__` in the class `__dict__`

            The `__hash__ = None` entry is literally written into the class namespace when the
            class body defines `__eq__` without `__hash__`. A subclass that only adds `__eq__`
            gets its own `None`, even if the parent was hashable.
            """
        ),
        code(
            """
            print(f"{'__hash__' in vars(EqualityOnlyMoney)=}, {vars(EqualityOnlyMoney)['__hash__']=}")
            print(f"{vars(Money)['__hash__'].__qualname__=}")
            print(f"{'__hash__' in vars(OrderBatch)=}  (defined explicitly)")
            """
        ),
    ]


def _ordering_cells() -> list[NotebookNode]:
    """2.4.4 Ordering."""
    return [
        md(
            """
            ### 2.4.4 Ordering

            There are six **rich comparison** methods. Each operator calls one of them on the
            left operand; if that returns `NotImplemented`, Python tries the **reflected**
            method on the right operand (the mirror image, not the negation):

            | Expression | First try | Reflected try |
            | --- | --- | --- |
            | `a < b` | `a.__lt__(b)` | `b.__gt__(a)` |
            | `a <= b` | `a.__le__(b)` | `b.__ge__(a)` |
            | `a > b` | `a.__gt__(b)` | `b.__lt__(a)` |
            | `a >= b` | `a.__ge__(b)` | `b.__le__(a)` |
            | `a == b` | `a.__eq__(b)` | `b.__eq__(a)` (then `a is b`) |
            | `a != b` | `a.__ne__(b)` | `b.__ne__(a)` (then `a is not b`) |

            Python does **not** derive `<=` from `<` and `==`. The `Version` class below writes
            only `__eq__` and `__lt__`: `<` works, `>` works through reflection (`b < a`), and
            `<=` fails.
            """
        ),
        code(
            '''
            class Version:
                """A semantic version like 3.15.1, compared field by field."""

                def __init__(self, text: str) -> None:
                    major, minor, patch = (int(part) for part in text.split("."))
                    self.parts = (major, minor, patch)

                def __repr__(self) -> str:
                    return f"Version('{'.'.join(map(str, self.parts))}')"

                def __eq__(self, other: object) -> bool:
                    if not isinstance(other, Version):
                        return NotImplemented
                    return self.parts == other.parts

                def __lt__(self, other: object) -> bool:
                    if not isinstance(other, Version):
                        return NotImplemented
                    return self.parts < other.parts


            old_release, new_release = Version("3.9.18"), Version("3.15.1")
            print(f"{old_release < new_release=}  (string comparison would say False)")
            print(f"{new_release > old_release=}  (reflected: old_release.__lt__(new_release))")
            print(raised_message(lambda: old_release <= new_release))
            '''
        ),
        md(
            """
            **Reflection, traced.** Both sides print and decline. Python tries `__lt__` on the
            left, then `__gt__` on the right, and only then raises `TypeError`.
            """
        ),
        code(
            '''
            class LoudOrdering:
                """Prints each comparison call and declines it."""

                def __init__(self, label: str) -> None:
                    self.label = label

                def __lt__(self, other: object) -> bool:
                    print(f"  {self.label}.__lt__({getattr(other, 'label', other)})")
                    return NotImplemented

                def __gt__(self, other: object) -> bool:
                    print(f"  {self.label}.__gt__({getattr(other, 'label', other)})")
                    return NotImplemented


            print(raised_message(lambda: LoudOrdering("a") < LoudOrdering("b")))
            '''
        ),
        md(
            """
            **Subclass first.** If the right operand's type is a **subclass** of the left
            operand's type and overrides the reflected method, Python tries the right side
            first. This lets a more specific type take control of mixed comparisons (the same
            rule applies to arithmetic, 2.4.9).
            """
        ),
        code(
            '''
            class PreReleaseVersion(Version):
                """A subclass that reports when its reflected __gt__ runs first."""

                def __gt__(self, other: object) -> bool:
                    print("  PreReleaseVersion.__gt__ ran first")
                    return NotImplemented


            print(f"{Version('1.0.0') < PreReleaseVersion('2.0.0')=}")
            '''
        ),
        md(
            """
            **`functools.total_ordering`.** Write `__eq__` and **one** of `__lt__`, `__le__`,
            `__gt__`, `__ge__`; the class decorator fills in the other three. The generated
            methods still return `NotImplemented` for foreign types. They add a little call
            overhead, so for a hot sorting path you can write all four by hand, or sort with a
            `key=` function instead.
            """
        ),
        code(
            '''
            @functools.total_ordering
            class OrderedVersion(Version):
                """Version plus the four ordering methods generated from __lt__ and __eq__."""


            releases = [OrderedVersion(text) for text in ["3.12.4", "3.9.18", "3.15.1", "3.13.0"]]
            print(f"{sorted(releases)=}")
            print(f"{max(releases)=}")
            print(f"{OrderedVersion('3.13.0') <= OrderedVersion('3.13.0')=}")
            print(f"{OrderedVersion('3.13.0') >= OrderedVersion('3.15.1')=}")
            print(f"{sorted(set(vars(OrderedVersion)) & {'__le__', '__gt__', '__ge__'})=}  (generated)")
            print(raised_message(lambda: OrderedVersion("1.0.0") <= "1.0.0"))
            '''
        ),
    ]


def _truthiness_cells() -> list[NotebookNode]:
    """2.4.5 Truthiness and size."""
    return [
        md(
            """
            ### 2.4.5 Truthiness and size

            `bool(x)` first looks for `__bool__`. If the class has none, it uses `__len__`
            (zero means false). If it has neither, every instance is truthy. Unit 1.3.8 showed
            the rule with `Wallet` and `ShoppingBag`; here are the details that bite.

            A class with only `__len__` is falsy when empty:
            """
        ),
        code(
            '''
            class PrintQueue:
                """Only __len__: truthiness comes from the length."""

                def __init__(self, jobs: Iterable[str] = ()) -> None:
                    self.jobs = list(jobs)

                def __len__(self) -> int:
                    return len(self.jobs)


            for queue in (PrintQueue(), PrintQueue(["invoice.pdf"])):
                print(f"{len(queue)=}, {bool(queue)=}")
            '''
        ),
        md(
            """
            `__bool__` wins over `__len__` when both exist. Use it when "has items" and "is
            usable" differ. Here a cache with entries is still falsy once it has expired.
            """
        ),
        code(
            '''
            class ExpiringCache:
                """Has a length, but is only 'true' while it is fresh."""

                def __init__(self, entries: dict[str, str], expired: bool) -> None:
                    self.entries = entries
                    self.expired = expired

                def __len__(self) -> int:
                    return len(self.entries)

                def __bool__(self) -> bool:
                    return not self.expired


            stale_cache = ExpiringCache({"home": "<html>"}, expired=True)
            print(f"{len(stale_cache)=}, {bool(stale_cache)=}")
            print("serve from cache" if stale_cache else "refetch")
            '''
        ),
        md(
            """
            Both methods have contracts that `len()` and `bool()` enforce: `__len__` must return
            a non-negative `int` (an `int` subclass such as `bool` is accepted), and `__bool__`
            must return exactly `bool`. Breaking them raises at the call site, not in your
            method.
            """
        ),
        code(
            """
            class BrokenSizes:
                def __init__(self, length: object, truth: object) -> None:
                    self.length, self.truth = length, truth

                def __len__(self) -> int:
                    return self.length  # type: ignore[return-value]

                def __bool__(self) -> bool:
                    return self.truth  # type: ignore[return-value]


            print(raised_message(lambda: len(BrokenSizes(-1, True))))
            print(raised_message(lambda: len(BrokenSizes(2.5, True))))
            print(raised_message(lambda: bool(BrokenSizes(1, 1))))
            print(f"{len(BrokenSizes(True, False))=}  (bool is an int subclass)")
            """
        ),
    ]


def _container_cells() -> list[NotebookNode]:
    """2.4.6 Container emulation."""
    return [
        md(
            """
            ### 2.4.6 Container emulation

            A class becomes a sequence or mapping by implementing these methods. The example is
            `SensorLog`, a list of temperature readings.

            | Method | Called by | Notes |
            | --- | --- | --- |
            | `__getitem__(key)` | `x[key]` | `key` is an `int`, or a `slice` for `x[a:b:c]` |
            | `__setitem__(key, value)` | `x[key] = value` | |
            | `__delitem__(key)` | `del x[key]` | |
            | `__contains__(item)` | `item in x` | falls back to `__iter__`, then `__getitem__` |
            | `__iter__()` | `for`, `list()`, unpacking | falls back to `__getitem__(0)`, `(1)`, … until `IndexError` |
            | `__reversed__()` | `reversed(x)` | falls back to `__len__` + `__getitem__` |
            | `__missing__(key)` | `dict.__getitem__` in a `dict` subclass | only for `dict` subclasses |

            **`__getitem__` with an `int`.** Accept negative indexes and raise `IndexError` when
            out of range; the old iteration protocol and `reversed()` rely on that error.
            """
        ),
        code(
            '''
            class SensorLog:
                """Temperature readings in °C, indexable like a list."""

                def __init__(self, sensor: str, readings: Iterable[float]) -> None:
                    self.sensor = sensor
                    self.readings = list(readings)

                def __repr__(self) -> str:
                    return f"{type(self).__name__}({self.sensor!r}, {self.readings!r})"

                def __len__(self) -> int:
                    return len(self.readings)

                def __getitem__(self, index: int | slice) -> float | SensorLog:
                    if isinstance(index, slice):
                        return type(self)(self.sensor, self.readings[index])
                    if not -len(self) <= index < len(self):
                        raise IndexError(f"reading {index} out of range for {len(self)} readings")
                    return self.readings[index]


            freezer_log = SensorLog("freezer", [-18.0, -17.5, -19.2, -12.4, -18.1])
            print(f"{freezer_log[0]=}, {freezer_log[-1]=}")
            print(raised_message(lambda: freezer_log[5]))
            '''
        ),
        md(
            """
            **`__getitem__` with a `slice`.** `x[1:4]` calls `x.__getitem__(slice(1, 4, None))`.
            Returning the **same type** (`type(self)(...)`, not a bare list) keeps slices useful,
            also for subclasses.
            `slice.indices(length)` turns `None`s and negatives into concrete
            `(start, stop, step)` values when you need to compute positions yourself.
            """
        ),
        code(
            """
            print(f"{freezer_log[1:4]=}")
            print(f"{freezer_log[::-2]=}")
            print(f"{freezer_log[slice(1, 4)].readings == freezer_log[1:4].readings=}")
            print(f"{slice(None, None, -2).indices(len(freezer_log))=}")
            """
        ),
        md(
            """
            **`__setitem__` and `__delitem__`.** The subclass adds writes with validation. Both
            receive the same `int` or `slice` keys as `__getitem__`; here they hand them to the
            list underneath.
            """
        ),
        code(
            '''
            class EditableSensorLog(SensorLog):
                """Adds validated writes and deletes."""

                def __setitem__(self, index: int | slice, value: float | list[float]) -> None:
                    values = value if isinstance(index, slice) else [value]
                    if any(not -90 <= reading <= 60 for reading in values):  # type: ignore[union-attr]
                        raise ValueError("readings must be between -90 and 60 °C")
                    self.readings[index] = value  # type: ignore[index]

                def __delitem__(self, index: int | slice) -> None:
                    del self.readings[index]


            editable_log = EditableSensorLog("fridge", [4.0, 4.2, 99.0, 3.9])
            del editable_log[2]
            editable_log[0] = 4.1
            editable_log[1:3] = [4.3, 4.4]
            print(f"{editable_log=}")
            print(raised_message(lambda: editable_log.__setitem__(0, 150.0)))
            '''
        ),
        md(
            """
            **`__contains__`.** Without it, `in` scans with `__iter__` or `__getitem__`. Writing
            it lets you change the meaning: this log answers `in` for a reading within ±0.5 °C,
            because comparing floats exactly is fragile (Unit 1.3.2).
            """
        ),
        code(
            """
            class TolerantSensorLog(SensorLog):
                def __contains__(self, target: object) -> bool:
                    if not isinstance(target, (int, float)):
                        return False
                    return any(abs(reading - target) <= 0.5 for reading in self.readings)


            tolerant_log = TolerantSensorLog("freezer", freezer_log.readings)
            print(f"{-17.5 in freezer_log=}, {-17.2 in freezer_log=}  (fallback: exact scan)")
            print(f"{-17.2 in tolerant_log=}, {-15.0 in tolerant_log=}, {'cold' in tolerant_log=}")
            """
        ),
        md(
            """
            **`__iter__`.** `SensorLog` has no `__iter__`, yet `for` works through the
            `__getitem__` fallback (calling indexes 0, 1, 2, … until `IndexError`). Writing
            `__iter__` as a generator is clearer and faster, and it is what
            `collections.abc.Iterable` checks for.
            """
        ),
        code(
            """
            class IterableSensorLog(SensorLog):
                def __iter__(self) -> Iterator[float]:
                    yield from self.readings


            print(f"{list(freezer_log)=}  (via __getitem__ fallback)")
            print(f"{[reading for reading in IterableSensorLog('freezer', [-18.0, -17.5])]=}")
            print(f"{'__iter__' in dir(freezer_log)=}, {'__iter__' in dir(IterableSensorLog)=}")
            """
        ),
        md(
            """
            **`__reversed__`.** `reversed(x)` uses `__reversed__` if present; otherwise it needs
            both `__len__` and `__getitem__` and walks the indexes backwards. Write it when you
            can reverse more cheaply, or when the object has no indexes at all.
            """
        ),
        code(
            """
            class ReversibleSensorLog(IterableSensorLog):
                def __reversed__(self) -> Iterator[float]:
                    print("  (custom __reversed__)")
                    return reversed(self.readings)


            print(f"{list(reversed(freezer_log))=}  (len + getitem fallback)")
            print(f"{list(reversed(ReversibleSensorLog('freezer', [-18.0, -17.5, -19.2])))=}")
            """
        ),
        md(
            """
            **`__missing__`.** Only for `dict` subclasses: when `dict.__getitem__` cannot find a
            key, it calls `self.__missing__(key)` and returns its result. `defaultdict` is built
            on it (Unit 1.6.11). Note that `.get()` and `in` do **not** call it. A handy use is
            `str.format_map`, which leaves unknown placeholders in place:
            """
        ),
        code(
            '''
            class KeepPlaceholders(dict[str, str]):
                """Unknown keys format as themselves, e.g. '{coupon}'."""

                def __missing__(self, key: str) -> str:
                    return "{" + key + "}"


            template = "Hi {name}, use {coupon} before {date}."
            values = KeepPlaceholders(name="Asha", date="31 Dec")
            print(template.format_map(values))
            print(f"{values['coupon']=}, {values.get('coupon')=}, {'coupon' in values=}")
            '''
        ),
        md(
            """
            #### Why subclass `UserDict` / `UserList` instead of `dict` / `list`

            The built-in `dict` and `list` are written in C, and their methods call each other
            **directly in C**, not through your overrides. Override `__setitem__` on a `dict`
            subclass and `dict(...)`, `update()` and `setdefault()` silently skip it. Here a
            form-data dict is meant to strip whitespace from every value:
            """
        ),
        code(
            '''
            class StrippedFormDict(dict[str, str]):
                """Meant to strip every value; only d[key] = value does."""

                def __setitem__(self, key: str, value: str) -> None:
                    super().__setitem__(key, value.strip())


            built_in_form = StrippedFormDict(name="  Asha ")
            built_in_form.update(city="  Pune ")
            built_in_form.setdefault("pin", " 411001 ")
            built_in_form["email"] = "  asha@example.com "
            print(built_in_form)
            '''
        ),
        md(
            """
            `collections.UserDict` is a pure-Python class that keeps the real dict in
            `self.data` and implements `update`, `setdefault`, the constructor and the rest **in
            terms of** `__setitem__` / `__getitem__` (it is a `MutableMapping`, Unit 2.3.2). One
            override now covers every path.
            """
        ),
        code(
            '''
            class StrippedForm(UserDict[str, str]):
                """Strips every value, whichever method stored it."""

                def __setitem__(self, key: str, value: str) -> None:
                    super().__setitem__(key, value.strip())


            user_dict_form = StrippedForm(name="  Asha ")
            user_dict_form.update(city="  Pune ")
            user_dict_form.setdefault("pin", " 411001 ")
            user_dict_form["email"] = "  asha@example.com "
            print(user_dict_form)
            print(f"{type(user_dict_form.data)=}, {isinstance(user_dict_form, MutableMapping)=}")
            '''
        ),
        md(
            """
            `UserList` has a different benefit: its operations **return your subclass**. A
            `list` subclass loses its type on slicing, `+` and `*`, so methods you added
            disappear. `UserList` builds results with `self.__class__(...)`.
            """
        ),
        code(
            """
            class TagList(list[str]):
                def as_hashtags(self) -> str:
                    return " ".join(f"#{tag}" for tag in self)


            class UserTagList(UserList[str]):
                def as_hashtags(self) -> str:
                    return " ".join(f"#{tag}" for tag in self)


            for tags in (TagList(["python", "oop", "dunder"]), UserTagList(["python", "oop", "dunder"])):
                slice_type, sum_type = type(tags[1:]).__name__, type(tags + tags).__name__
                print(f"{type(tags).__name__}: slice -> {slice_type}, + -> {sum_type}")
            print(f"{UserTagList(['python', 'oop', 'dunder'])[1:].as_hashtags()=}")
            """
        ),
        md(
            """
            > **Note:** subclassing `dict` or `list` is fine when you only **add** methods or
            > use `__missing__`. Reach for `UserDict` / `UserList` (or `MutableMapping` /
            > `MutableSequence`) when you need to **change** how items are stored or returned.
            """
        ),
    ]


def _callable_cells() -> list[NotebookNode]:
    """2.4.7 Callables."""
    return [
        md(
            """
            ### 2.4.7 Callables

            Any object whose type defines `__call__` can be called with `()`. A class with
            `__call__` is a **stateful function object**: like a closure (Unit 1.11) it keeps
            state between calls, but the state is visible as attributes and it can have more
            methods. `IdGenerator` hands out readable order numbers.
            """
        ),
        code(
            '''
            class IdGenerator:
                """Calling it returns the next id: ORD-0001, ORD-0002, …"""

                def __init__(self, prefix: str, start: int = 1) -> None:
                    self.prefix = prefix
                    self.next_number = start

                def __call__(self) -> str:
                    new_id = f"{self.prefix}-{self.next_number:04d}"
                    self.next_number += 1
                    return new_id


            next_order_id = IdGenerator("ORD")
            print(next_order_id(), next_order_id(), next_order_id())
            print(f"{next_order_id.next_number=}  (state is a plain attribute)")
            print(f"{callable(next_order_id)=}")
            '''
        ),
        md(
            """
            Because it is called like a function, it fits anywhere a function is expected:
            `map`, `sorted(key=...)`, callbacks. `inspect.signature` reads the signature of
            `__call__`. This `TaxCalculator` keeps its rate and counts how often it ran.
            """
        ),
        code(
            '''
            class TaxCalculator:
                """Adds tax to a price; remembers how many prices it handled."""

                def __init__(self, rate_percent: Decimal) -> None:
                    self.rate_percent = rate_percent
                    self.call_count = 0

                def __call__(self, price: Decimal) -> Decimal:
                    self.call_count += 1
                    with_tax = price * (1 + self.rate_percent / 100)
                    return with_tax.quantize(PAISE, rounding=ROUND_HALF_UP)


            add_gst = TaxCalculator(Decimal("18"))
            print(list(map(add_gst, [Decimal("100"), Decimal("49.99")])))
            print(f"{add_gst.call_count=}, {inspect.signature(add_gst)=}")
            '''
        ),
        md(
            """
            Only the **type's** `__call__` counts. Putting a `__call__` attribute on an instance
            does not make it callable (2.4.9 explains why), which is a common surprise when
            people try to "patch" an object into a function.
            """
        ),
        code(
            """
            class NotCallable:
                pass


            plain_object = NotCallable()
            plain_object.__call__ = lambda: "hello"  # type: ignore[attr-defined]
            print(f"{plain_object.__call__()=}  (explicit attribute call works)")
            print(raised_message(lambda: plain_object()))
            """
        ),
    ]


def _numeric_cells() -> list[NotebookNode]:
    """2.4.8 Numeric emulation: one cell per method."""
    return [
        md(
            """
            ### 2.4.8 Numeric emulation

            Arithmetic operators map to special methods; each binary one has a **reflected**
            (`__r*__`) form for when your object is on the right, and an **in-place**
            (`__i*__`) form for augmented assignment.

            | Operator | Method | Reflected | In-place |
            | --- | --- | --- | --- |
            | `a + b` | `__add__` | `__radd__` | `__iadd__` (`+=`) |
            | `a - b` | `__sub__` | `__rsub__` | `__isub__` |
            | `a * b` | `__mul__` | `__rmul__` | `__imul__` |
            | `a / b` | `__truediv__` | `__rtruediv__` | `__itruediv__` |
            | `a // b`, `a % b`, `a ** b` | `__floordiv__`, `__mod__`, `__pow__` | `__r…__` | `__i…__` |
            | `a @ b` | `__matmul__` | `__rmatmul__` | `__imatmul__` |
            | `-a`, `+a`, `abs(a)`, `~a` | `__neg__`, `__pos__`, `__abs__`, `__invert__` | — | — |

            The demos use an immutable `Duration` (whole seconds). Each method below gets its
            own cell; the class is extended one step at a time with subclasses so every cell
            stays small.
            """
        ),
        code(
            '''
            class Duration:
                """An immutable span of whole seconds."""

                def __init__(self, seconds: int) -> None:
                    self._seconds = seconds

                @property
                def seconds(self) -> int:
                    return self._seconds

                def __repr__(self) -> str:
                    return f"Duration({self._seconds})"

                def __eq__(self, other: object) -> bool:
                    if not isinstance(other, Duration):
                        return NotImplemented
                    return self._seconds == other._seconds

                def __hash__(self) -> int:
                    return hash(self._seconds)
            '''
        ),
        md(
            """
            #### `__add__`

            Return a **new** object (the class is immutable) and `NotImplemented` for types you
            do not handle. Note `type(self)(...)`, so subclasses get their own type back.
            """
        ),
        code(
            """
            class Duration(Duration):  # each step extends the previous Duration
                def __add__(self, other: object) -> Duration:
                    if not isinstance(other, Duration):
                        return NotImplemented
                    return type(self)(self.seconds + other.seconds)


            print(f"{Duration(90) + Duration(30)=}")
            print(raised_message(lambda: Duration(90) + 30))
            """
        ),
        md(
            """
            #### `__radd__` (for `sum`)

            `sum(items)` starts from `0` and computes `0 + first`. `int.__add__` returns
            `NotImplemented` for a `Duration`, so Python calls `first.__radd__(0)`. Without
            `__radd__`, `sum` fails. Treating `0` as "no time" fixes it; passing
            `start=Duration(0)` also works, but callers forget it.
            """
        ),
        code(
            """
            print(raised_message(lambda: sum([Duration(60), Duration(30)])))
            print(f"{sum([Duration(60), Duration(30)], start=Duration(0))=}")


            class Duration(Duration):
                def __radd__(self, other: object) -> Duration:
                    if other == 0:  # sum() starts from int 0
                        return self
                    return self.__add__(other)


            print(f"{sum([Duration(60), Duration(30), Duration(5)])=}")
            print(f"{0 + Duration(45)=}")
            """
        ),
        md(
            """
            #### `__iadd__`

            `total += x` calls `__iadd__` if it exists; otherwise it falls back to
            `total = total + x`. An immutable type should **not** define `__iadd__`: the name is
            simply rebound to a new object. A mutable type defines it to change itself in place
            and return `self`, so every alias sees the change (like `list +=`, Unit 1.2).
            """
        ),
        code(
            '''
            running_total = Duration(0)
            alias_of_total = running_total
            running_total += Duration(30)
            print(f"{running_total=}, {alias_of_total=}, {running_total is alias_of_total=}")


            class Timesheet:
                """Mutable: += adds a duration to this very timesheet."""

                def __init__(self) -> None:
                    self.entries: list[Duration] = []

                def __iadd__(self, entry: Duration) -> Self:
                    self.entries.append(entry)
                    return self


            my_timesheet = Timesheet()
            shared_view = my_timesheet
            my_timesheet += Duration(3600)
            print(f"{shared_view.entries=}, {my_timesheet is shared_view=}")
            '''
        ),
        md(
            """
            #### `__sub__`

            Subtraction is not commutative, so `__rsub__` (if you write one) must compute
            `other - self`, not `self - other`.
            """
        ),
        code(
            """
            class Duration(Duration):
                def __sub__(self, other: object) -> Duration:
                    if not isinstance(other, Duration):
                        return NotImplemented
                    return type(self)(self.seconds - other.seconds)


            print(f"{Duration(300) - Duration(45)=}, {Duration(45) - Duration(300)=}")
            """
        ),
        md(
            """
            #### `__mul__`

            Multiplying a duration by a whole number makes sense; multiplying two durations
            does not (seconds²). `__rmul__` handles `3 * duration`, where `int.__mul__` gives up
            first.
            """
        ),
        code(
            """
            class Duration(Duration):
                def __mul__(self, factor: object) -> Duration:
                    if not isinstance(factor, int):
                        return NotImplemented
                    return type(self)(self.seconds * factor)

                __rmul__ = __mul__  # multiplication by a number is commutative


            print(f"{Duration(25) * 4=}, {4 * Duration(25)=}")
            print(raised_message(lambda: Duration(25) * Duration(4)))
            """
        ),
        md(
            """
            #### `__truediv__`

            One method, two meanings chosen by the operand type: `Duration / int` splits a
            duration into equal parts (rounded to whole seconds), `Duration / Duration` is a
            plain ratio (`float`). `int / Duration` stays unsupported because there is no
            `__rtruediv__`.
            """
        ),
        code(
            """
            class Duration(Duration):
                def __truediv__(self, divisor: object) -> Duration | float:
                    if isinstance(divisor, Duration):
                        return self.seconds / divisor.seconds
                    if isinstance(divisor, int):
                        return type(self)(round(self.seconds / divisor))
                    return NotImplemented


            print(f"{Duration(3600) / 4=}")
            print(f"{Duration(5400) / Duration(3600)=}")
            print(raised_message(lambda: 10 / Duration(5)))
            """
        ),
        md(
            """
            #### `__neg__`

            Unary minus. Negative durations are allowed here (they come out of subtraction
            anyway), so `-d` simply flips the sign.
            """
        ),
        code(
            """
            class Duration(Duration):
                def __neg__(self) -> Duration:
                    return type(self)(-self.seconds)


            negative_span = -Duration(90)
            print(f"{negative_span=}, {-negative_span=}")
            """
        ),
        md(
            """
            #### `__abs__`

            `abs(x)` calls `__abs__`. Combined with subtraction it answers "how far apart are
            two times", whichever comes first.
            """
        ),
        code(
            """
            class Duration(Duration):
                def __abs__(self) -> Duration:
                    return type(self)(abs(self.seconds))


            planned, actual = Duration(1800), Duration(2100)
            print(f"{abs(planned - actual)=}, {abs(actual - planned)=}")
            """
        ),
        md(
            """
            #### `__matmul__`

            `@` (PEP 465) exists for matrix multiplication and no built-in type uses it; NumPy
            does. A tiny 2×2 matrix shows it: rotating by 90° twice equals rotating by 180°, and
            `matrix @ (x, y)` transforms a point (reflected `__rmatmul__` is not needed because
            the matrix is always on the left).
            """
        ),
        code(
            '''
            class Matrix2x2:
                """A 2×2 integer matrix ((a, b), (c, d))."""

                def __init__(self, a: int, b: int, c: int, d: int) -> None:
                    self.rows = ((a, b), (c, d))

                def __repr__(self) -> str:
                    return f"Matrix2x2{self.rows}"

                def __matmul__(self, other: object) -> Matrix2x2 | tuple[int, int]:
                    (a, b), (c, d) = self.rows
                    if isinstance(other, Matrix2x2):
                        (e, f), (g, h) = other.rows
                        return Matrix2x2(a * e + b * g, a * f + b * h, c * e + d * g, c * f + d * h)
                    if isinstance(other, tuple) and len(other) == 2:
                        x, y = other
                        return (a * x + b * y, c * x + d * y)
                    return NotImplemented


            rotate_90 = Matrix2x2(0, -1, 1, 0)
            print(f"{rotate_90 @ rotate_90=}  (rotate 180°)")
            print(f"{rotate_90 @ (3, 1)=}")
            '''
        ),
        md(
            """
            The finished `Duration` now works with every operator above, plus `sum()`:
            """
        ),
        code(
            """
            work_sessions = [Duration(1500), Duration(1500), Duration(900)]
            total_work = sum(work_sessions)
            print(f"{total_work=}, {total_work / len(work_sessions)=}")
            print(f"{total_work / Duration(3600)=}, {abs(-total_work)=}")
            print(f"{len(Duration.__mro__)=}  (eight Duration steps, then object)")
            """
        ),
    ]


def _lookup_cells() -> list[NotebookNode]:
    """2.4.9 Special-method lookup."""
    return [
        md(
            """
            ### 2.4.9 Special-method lookup

            **Implicit calls look up the type, not the instance.** `len(x)` runs
            `type(x).__len__(x)`; it never looks in `x.__dict__`. An explicit `x.__len__()` is a
            normal attribute lookup and **does** see the instance attribute.
            """
        ),
        code(
            """
            class Shelf:
                def __len__(self) -> int:
                    return 3


            oak_shelf = Shelf()
            oak_shelf.__len__ = lambda: 99  # type: ignore[method-assign]
            print(f"{len(oak_shelf)=}  (type lookup: Shelf.__len__)")
            print(f"{oak_shelf.__len__()=}  (normal attribute lookup finds the instance attribute)")
            """
        ),
        md(
            """
            Two reasons for the rule. **Speed**: the interpreter reads the method from a slot in
            the type struct (Unit 3.2) instead of doing a dictionary lookup. **Correctness**:
            classes are objects too. `repr(Money)` must call `type.__repr__` (the metaclass,
            Unit 2.5.7), not the `Money.__repr__` that is meant for instances, and `hash(int)`
            must hash the class, not call `int.__hash__` with no argument.
            """
        ),
        code(
            """
            print(f"{repr(Money)=}  (type(Money).__repr__)")
            print(raised_message(lambda: Money.__repr__()))
            print(f"{hash(int) == type(int).__hash__(int)=}")
            print(raised_message(lambda: int.__hash__()))
            """
        ),
        md(
            """
            #### Under the hood: `dis` and `BINARY_OP`

            Every binary operator compiles to one `BINARY_OP` instruction whose argument says
            which operator (`+`, `+=`, `@`, …); `x += y` uses the in-place variant. The
            instruction does the whole protocol: `__add__`, `NotImplemented`, `__radd__`,
            `TypeError`. (Instruction names change between versions; this is 3.15.)
            """
        ),
        code(
            '''
            def apply_charges(subtotal: Money, delivery_fee: Money) -> Money:
                """Two operators: + and +=."""
                total = subtotal + delivery_fee
                total += delivery_fee
                return total


            for instruction in dis.get_instructions(apply_charges):
                if instruction.opname == "BINARY_OP":
                    print(f"{instruction.opname} {instruction.arg} ({instruction.argrepr})")
            '''
        ),
        md(
            """
            **The `__add__` → `__radd__` sequence, traced.** For `left + right`:

            1. If `type(right)` is a **subclass** of `type(left)` and overrides `__radd__`, try
               `right.__radd__(left)` first.
            2. Otherwise try `left.__add__(right)`.
            3. If that is missing or returns `NotImplemented`, try `right.__radd__(left)`
               (skipped when both operands have the same type).
            4. If everything returns `NotImplemented`, raise `TypeError: unsupported operand
               type(s)`.
            """
        ),
        code(
            """
            class LoudLeft:
                def __add__(self, other: object) -> object:
                    print("  LoudLeft.__add__ -> NotImplemented")
                    return NotImplemented


            class LoudRight:
                def __radd__(self, other: object) -> str:
                    print("  LoudRight.__radd__ -> handled")
                    return "sum from the right"


            class Decliner:
                def __radd__(self, other: object) -> object:
                    print("  Decliner.__radd__ -> NotImplemented")
                    return NotImplemented


            print(f"result: {LoudLeft() + LoudRight()!r}")
            print(raised_message(lambda: LoudLeft() + Decliner()))
            """
        ),
        md(
            """
            Step 1, the subclass rule, in action: the right operand is tried first even though
            the left one could have answered.
            """
        ),
        code(
            """
            class Points:
                def __init__(self, value: int) -> None:
                    self.value = value

                def __add__(self, other: object) -> object:
                    print("  Points.__add__")
                    if not isinstance(other, Points):
                        return NotImplemented
                    return Points(self.value + other.value)


            class BonusPoints(Points):
                def __radd__(self, other: object) -> object:
                    print("  BonusPoints.__radd__ (subclass goes first)")
                    if not isinstance(other, Points):
                        return NotImplemented
                    return BonusPoints(other.value + self.value * 2)


            print(f"{type(Points(10) + BonusPoints(5)).__name__=}")
            """
        ),
        md(
            """
            A pure-Python model of the algorithm makes the rules concrete. It agrees with the
            real `+` on every pair below (the real one is in C, inside `BINARY_OP`).
            """
        ),
        code(
            '''
            def model_add(left: object, right: object) -> object:
                """Mimic how `left + right` picks __add__ / __radd__ (ignores C-level slots)."""
                left_type, right_type = type(left), type(right)
                reflected = getattr(right_type, "__radd__", None)
                try_right_first = (
                    right_type is not left_type
                    and issubclass(right_type, left_type)
                    and reflected is not getattr(left_type, "__radd__", None)
                )
                attempts = []
                if try_right_first:
                    attempts.append(lambda: reflected(right, left))
                if (forward := getattr(left_type, "__add__", None)) is not None:
                    attempts.append(lambda: forward(left, right))
                if reflected is not None and right_type is not left_type and not try_right_first:
                    attempts.append(lambda: reflected(right, left))
                for attempt in attempts:
                    if (result := attempt()) is not NotImplemented:
                        return result
                operand_names = f"{left_type.__name__!r} and {right_type.__name__!r}"
                raise TypeError(f"unsupported operand type(s) for +: {operand_names}")


            def outcome(thunk: Callable[[], object]) -> str:
                """repr of the result, or the TypeError message."""
                try:
                    return repr(thunk())
                except TypeError as error:
                    return f"TypeError: {error}"
            '''
        ),
        md(
            """
            Compare the model with the real operator on a few pairs, including the
            `0 + Duration` step that `sum()` performs and one unsupported pair.
            """
        ),
        code(
            """
            pairs = [(2, 3), ("ab", "cd"), (0, Duration(5)), (Duration(5), Duration(7)), (Duration(5), "x")]
            for left, right in pairs:
                model_result = outcome(lambda: model_add(left, right))  # noqa: B023 (called at once)
                real_result = outcome(lambda: left + right)  # noqa: B023
                print(f"{left!r} + {right!r}: {model_result}  same={model_result == real_result}")
            """
        ),
        *predict_cells(
            """
            class Point:
                def __init__(self, x, y):
                    self.x, self.y = x, y

                def __eq__(self, other):
                    return (self.x, self.y) == (other.x, other.y)

            print(Point(1, 2) == Point(1, 2))
            print(len({Point(1, 2), Point(1, 2)}))
            """,
            """
            ```text
            True
            TypeError: cannot use 'Point' as a set element (unhashable type: 'Point')
            ```

            The first line works: `__eq__` compares values. The second line never prints a
            number: defining `__eq__` without `__hash__` sets `Point.__hash__ = None`, so the
            set literal raises `TypeError` (the message names the set element on 3.15; older
            versions say only `unhashable type: 'Point'`). Fix it with
            `def __hash__(self): return hash((self.x, self.y))` and keep `x` and `y` immutable
            (or use `@dataclass(frozen=True)`, Unit 2.6).
            """,
            """
            class Point:
                def __init__(self, x: int, y: int) -> None:
                    self.x, self.y = x, y

                def __eq__(self, other: object) -> bool:
                    return (self.x, self.y) == (other.x, other.y)  # type: ignore[attr-defined]


            print(Point(1, 2) == Point(1, 2))
            print(raised_message(lambda: len({Point(1, 2), Point(1, 2)})))
            """,
        ),
    ]


def _lab_money_cells() -> list[NotebookNode]:
    """Lab 2.4 exercise 1."""
    return [
        md(
            """
            ### Lab 2.4

            Six exercises. For each, complete the stub, then run the check cell. Until then the
            checks print FAIL; that is expected. In exercise 4 four checks already pass on the
            stub, because they test behaviour `UserDict` gives for free: "missing key", "copy
            keeps type", "is a UserDict" and "is a MutableMapping". Keep them passing.

            #### Exercise 1 — an immutable `Money`

            Finish the `Money` started in 2.4.2–2.4.3. This is the `Money` the Phase 2 Project
            uses.

            - `Money(amount, currency="INR")`: `amount` is a `Decimal`, `int` or `str`,
              converted to `Decimal` and rounded to the paisa with `ROUND_HALF_UP`. A `float`
              raises `TypeError("amount must be Decimal, int or str, not float")`. A currency
              that is not three upper-case letters raises
              `ValueError(f"invalid currency code: {currency!r}")`.
            - **Immutable**: `amount` and `currency` are read-only properties, and
              `__slots__ = ("_amount", "_currency")` stops new attributes (Unit 2.5.5 explains
              slots).
            - `repr` → `Money('1234.50', 'INR')`; `str` → `INR 1,234.50`; `format` as in
              2.4.2 (`""`, `"symbol"`, otherwise the spec applies to the amount).
            - `==` and `hash` by value (amount and currency); comparing with a non-`Money`
              is simply unequal.
            - Ordering (`<`, `<=`, `>`, `>=`) within one currency. Different currencies raise
              `CurrencyMismatchError(f"currency mismatch: {a} vs {b}")` with the two codes;
              a non-`Money` operand raises `TypeError` (return `NotImplemented`).
            - `+` and `-` between `Money` of the same currency (mismatch: the same error);
              `0 + money` returns the money, so `sum()` works; any other `int` is a `TypeError`.
            - `money * n` and `n * money` for `int` or `Decimal` (result rounded to the paisa);
              `float` or `Money` factors raise `TypeError`.
            - `-money`, `abs(money)`; `bool(money)` is `False` only for zero.
            """
        ),
        code(
            '''
            class CurrencyMismatchError(ValueError):
                """Two Money values in different currencies were combined or compared."""


            CURRENCY_SYMBOLS = {"INR": "₹", "USD": "$", "EUR": "€"}


            class Money:
                """An immutable amount of money in one currency."""

                __slots__ = ("_amount", "_currency")

                def __init__(self, amount: Decimal | int | str, currency: str = "INR") -> None:
                    raise NotImplementedError("Lab 2.4: implement Money")
            '''
        ),
        md("Run the checks."),
        code(
            '''
            def money_errors() -> list[str]:
                """Messages for the constructor and mismatch errors."""
                return [
                    raised_message(lambda: Money(1.5)),
                    raised_message(lambda: Money(1, "inr")),
                    raised_message(lambda: Money(1) + Money(1, "USD")),
                    raised_message(lambda: Money(1) < Money(1, "USD")),
                ]


            run_checks(
                [
                    ("rounds to paise", lambda: Money("10.005").amount, Decimal("10.01")),
                    (
                        "int and str amounts",
                        lambda: (Money(10).amount, Money("2.5").currency),
                        (Decimal("10.00"), "INR"),
                    ),
                    (
                        "error messages",
                        money_errors,
                        [
                            "TypeError: amount must be Decimal, int or str, not float",
                            "ValueError: invalid currency code: 'inr'",
                            "CurrencyMismatchError: currency mismatch: INR vs USD",
                            "CurrencyMismatchError: currency mismatch: INR vs USD",
                        ],
                    ),
                    (
                        "read-only amount",
                        lambda: raised_error_name(lambda: set_attribute(Money(1), "amount", 5)),
                        "AttributeError",
                    ),
                    (
                        "no new attributes",
                        lambda: raised_error_name(lambda: set_attribute(Money(1), "note", "x")),
                        "AttributeError",
                    ),
                    ("repr", lambda: repr(Money("1234.5")), "Money('1234.50', 'INR')"),
                    ("str", lambda: str(Money("1234.5", "USD")), "USD 1,234.50"),
                    (
                        "format",
                        lambda: f"{Money('1234.5'):symbol}|{Money(7, 'USD'):symbol}|{Money(1234):,.0f}",
                        "₹1,234.50|$7.00|INR 1,234",
                    ),
                    (
                        "equality",
                        lambda: (Money(10) == Money("10.00"), Money(10) == Money(10, "USD"), Money(10) == 10),
                        (True, False, False),
                    ),
                    ("hash", lambda: len({Money(10), Money("10.0"), Money(10, "USD")}), 2),
                    (
                        "ordering",
                        lambda: (
                            Money(5) < Money(7),
                            Money(7) <= Money(7),
                            Money(9) > Money(7),
                            Money(1) >= Money(2),
                        ),
                        (True, True, True, False),
                    ),
                    (
                        "sorted and max",
                        lambda: [
                            str(money)
                            for money in [*sorted([Money(3), Money(1), Money(2)]), max(Money(3), Money(9))]
                        ],
                        ["INR 1.00", "INR 2.00", "INR 3.00", "INR 9.00"],
                    ),
                    ("compare with int", lambda: raised_error_name(lambda: Money(5) < 5), "TypeError"),
                    (
                        "add and subtract",
                        lambda: (str(Money("10.50") + Money("4.75")), str(Money(10) - Money("12.5"))),
                        ("INR 15.25", "INR -2.50"),
                    ),
                    ("sum()", lambda: str(sum([Money(100), Money("49.99"), Money("0.01")])), "INR 150.00"),
                    ("0 + money", lambda: repr(0 + Money(5)), "Money('5.00', 'INR')"),
                    ("other int", lambda: raised_error_name(lambda: Money(5) + 1), "TypeError"),
                    (
                        "multiply",
                        lambda: (str(Money("19.99") * 3), str(2 * Money(5)), str(Money(10) * Decimal("0.125"))),
                        ("INR 59.97", "INR 10.00", "INR 1.25"),
                    ),
                    ("float factor", lambda: raised_error_name(lambda: Money(10) * 1.5), "TypeError"),
                    ("money factor", lambda: raised_error_name(lambda: Money(10) * Money(2)), "TypeError"),
                    (
                        "neg and abs",
                        lambda: (str(-Money(5)), str(abs(Money(-5, "EUR")))),
                        ("INR -5.00", "EUR 5.00"),
                    ),
                    ("bool", lambda: (bool(Money(0)), bool(Money("0.01"))), (False, True)),
                ]
            )
            '''
        ),
    ]


def _lab_vector_playlist_cells() -> list[NotebookNode]:
    """Lab 2.4 exercises 2 and 3."""
    return [
        md(
            """
            #### Exercise 2 — `Vector2D`

            `Vector2D(x, y)` with numeric components:

            - read-only `x` and `y`; `repr` → `Vector2D(3, 4)` (each component with `!r`).
            - `==` and `hash` by components; iteration yields `x` then `y`, so
              `x, y = vector` works.
            - `v + w`, `v - w` → vectors; `v * k` and `k * v` for an `int` or `float` scalar;
              `-v`; `abs(v)` → length (`math.hypot`); `bool(v)` → `False` only for the zero
              vector; `v @ w` → dot product (a number).
            - Unsupported operands raise `TypeError` (return `NotImplemented`).
            """
        ),
        code(
            '''
            class Vector2D:
                """An immutable 2-D vector."""

                def __init__(self, x: float, y: float) -> None:
                    raise NotImplementedError("Lab 2.4: implement Vector2D")
            '''
        ),
        md("Run the checks."),
        code(
            """
            run_checks(
                [
                    ("repr", lambda: repr(Vector2D(3, 4)), "Vector2D(3, 4)"),
                    ("repr floats", lambda: repr(Vector2D(1.5, -2.0)), "Vector2D(1.5, -2.0)"),
                    (
                        "read-only",
                        lambda: raised_error_name(lambda: set_attribute(Vector2D(1, 2), "x", 5)),
                        "AttributeError",
                    ),
                    (
                        "equality and hash",
                        lambda: (Vector2D(1, 2) == Vector2D(1, 2), len({Vector2D(1, 2), Vector2D(1, 2)})),
                        (True, 1),
                    ),
                    ("not equal to tuple", lambda: Vector2D(1, 2) == (1, 2), False),
                    ("unpacking", lambda: tuple(Vector2D(7, 8)), (7, 8)),
                    (
                        "add and subtract",
                        lambda: (repr(Vector2D(1, 2) + Vector2D(3, 4)), repr(Vector2D(1, 2) - Vector2D(3, 4))),
                        ("Vector2D(4, 6)", "Vector2D(-2, -2)"),
                    ),
                    (
                        "scalar both sides",
                        lambda: (repr(Vector2D(1, 2) * 3), repr(0.5 * Vector2D(4, 6))),
                        ("Vector2D(3, 6)", "Vector2D(2.0, 3.0)"),
                    ),
                    ("negation", lambda: repr(-Vector2D(1, -2)), "Vector2D(-1, 2)"),
                    ("abs", lambda: abs(Vector2D(3, 4)), 5.0),
                    ("bool", lambda: (bool(Vector2D(0, 0)), bool(Vector2D(0, 1))), (False, True)),
                    ("dot product", lambda: Vector2D(1, 2) @ Vector2D(3, 4), 11),
                    ("add a number", lambda: raised_error_name(lambda: Vector2D(1, 2) + 5), "TypeError"),
                    (
                        "vector * vector",
                        lambda: raised_error_name(lambda: Vector2D(1, 2) * Vector2D(1, 2)),
                        "TypeError",
                    ),
                ]
            )
            """
        ),
        md(
            """
            #### Exercise 3 — `Playlist` with slicing

            `Playlist(name, songs=())` keeps its **own copy** of the songs as a list.

            - `len`, `in`, iteration in order, and `reversed()` (write `__reversed__`).
            - `playlist[i]` → a song (negative indexes work, out of range is `IndexError`);
              `playlist[a:b:c]` → a **new `Playlist`** with the same name.
            - `playlist[i] = song` and `del playlist[i]` (slices allowed for both).
            - `==` compares name and songs; `repr` → `Playlist('Road trip', ['A', 'B'])`.
            """
        ),
        code(
            '''
            class Playlist:
                """A named, ordered list of songs."""

                def __init__(self, name: str, songs: Iterable[str] = ()) -> None:
                    raise NotImplementedError("Lab 2.4: implement Playlist")
            '''
        ),
        md("Run the checks."),
        code(
            '''
            SONGS = ["Kun Faya Kun", "Ilahi", "Kabira", "Safarnama", "Raabta"]


            def playlist_edits() -> Playlist:
                """Replace, delete and slice-delete."""
                road_trip = Playlist("Road trip", SONGS)
                road_trip[0] = "Patakha Guddi"
                del road_trip[-1]
                del road_trip[1:3]
                return road_trip


            def keeps_own_copy() -> list[str]:
                """Changing the source list must not change the playlist."""
                source = ["A", "B"]
                playlist = Playlist("Copy", source)
                source.append("C")
                return list(playlist)


            run_checks(
                [
                    ("len", lambda: len(Playlist("Road trip", SONGS)), 5),
                    (
                        "index",
                        lambda: (Playlist("Road trip", SONGS)[0], Playlist("Road trip", SONGS)[-1]),
                        ("Kun Faya Kun", "Raabta"),
                    ),
                    (
                        "index error",
                        lambda: raised_error_name(lambda: Playlist("Road trip", SONGS)[5]),
                        "IndexError",
                    ),
                    ("slice type", lambda: type(Playlist("Road trip", SONGS)[1:3]).__name__, "Playlist"),
                    (
                        "slice content",
                        lambda: repr(Playlist("Road trip", SONGS)[1:3]),
                        "Playlist('Road trip', ['Ilahi', 'Kabira'])",
                    ),
                    (
                        "step slice",
                        lambda: list(Playlist("Road trip", SONGS)[::2]),
                        ["Kun Faya Kun", "Kabira", "Raabta"],
                    ),
                    (
                        "contains",
                        lambda: (
                            "Kabira" in Playlist("Road trip", SONGS),
                            "Tum Hi Ho" in Playlist("Road trip", SONGS),
                        ),
                        (True, False),
                    ),
                    ("reversed", lambda: list(reversed(Playlist("x", ["A", "B", "C"]))), ["C", "B", "A"]),
                    ("has __reversed__", lambda: "__reversed__" in vars(Playlist), True),
                    (
                        "edits",
                        lambda: repr(playlist_edits()),
                        "Playlist('Road trip', ['Patakha Guddi', 'Safarnama'])",
                    ),
                    ("own copy", keeps_own_copy, ["A", "B"]),
                    ("equality uses name", lambda: Playlist("A", ["x"]) == Playlist("B", ["x"]), False),
                    (
                        "repr",
                        lambda: repr(Playlist("Road trip", ["A", "B"])),
                        "Playlist('Road trip', ['A', 'B'])",
                    ),
                ]
            )
            '''
        ),
    ]


def _lab_dict_limiter_inventory_cells() -> list[NotebookNode]:
    """Lab 2.4 exercises 4–6."""
    return [
        md(
            """
            #### Exercise 4 — `CaseInsensitiveDict(UserDict)`

            Unit 2.3.2 built a case-insensitive mapping on `MutableMapping`; this time use
            `UserDict` and override as little as possible.

            - Keys must be `str` (otherwise `TypeError("keys must be str")`) and are stored
              **case-folded** (`key.casefold()`), so iteration yields lower-case keys.
            - `d[key]`, `d[key] = value`, `del d[key]` and `key in d` ignore case.
            - Because `UserDict` routes through those methods, the constructor, `update`,
              `get`, `setdefault`, `pop` and `copy` must then work case-insensitively with no
              extra code.
            """
        ),
        code(
            '''
            class CaseInsensitiveDict(UserDict[str, str]):
                """HTTP-header style dict: keys compare without case."""
            '''
        ),
        md("Run the checks."),
        code(
            '''
            def header_session() -> tuple[object, ...]:
                """Exercise every inherited method."""
                headers = CaseInsensitiveDict({"Content-Type": "text/html"}, Accept="*/*")
                headers.update({"ACCEPT": "application/json"})
                headers.setdefault("X-Request-Id", "abc123")
                headers.setdefault("x-request-id", "ignored")
                popped = headers.pop("CONTENT-TYPE")
                return popped, headers.get("accept"), headers.get("missing", "-"), sorted(headers)


            run_checks(
                [
                    (
                        "getitem ignores case",
                        lambda: CaseInsensitiveDict({"Content-Type": "text/html"})["content-TYPE"],
                        "text/html",
                    ),
                    ("contains ignores case", lambda: "ACCEPT" in CaseInsensitiveDict(accept="*/*"), True),
                    (
                        "one key per spelling",
                        lambda: len(CaseInsensitiveDict({"Accept": "a", "ACCEPT": "b"})),
                        1,
                    ),
                    ("keys case-folded", lambda: list(CaseInsensitiveDict({"Accept": "a"})), ["accept"]),
                    (
                        "inherited methods",
                        header_session,
                        ("text/html", "application/json", "-", ["accept", "x-request-id"]),
                    ),
                    (
                        "delete",
                        lambda: raised_error_name(
                            lambda: CaseInsensitiveDict(Accept="a").__delitem__("ACCEPT")
                        ),
                        "no error",
                    ),
                    (
                        "missing key",
                        lambda: raised_error_name(lambda: CaseInsensitiveDict()["accept"]),
                        "KeyError",
                    ),
                    (
                        "str keys only",
                        lambda: raised_message(lambda: CaseInsensitiveDict({1: "a"})),
                        "TypeError: keys must be str",
                    ),
                    (
                        "copy keeps type",
                        lambda: type(CaseInsensitiveDict(a="1").copy()).__name__,
                        "CaseInsensitiveDict",
                    ),
                    ("is a UserDict", lambda: isinstance(CaseInsensitiveDict(), UserDict), True),
                    ("is a MutableMapping", lambda: isinstance(CaseInsensitiveDict(), MutableMapping), True),
                ]
            )
            '''
        ),
        md(
            """
            #### Exercise 5 — a callable `RateLimiter`

            `RateLimiter(max_calls, period_seconds, clock=time.monotonic)` allows at most
            `max_calls` calls in any window of `period_seconds` (a sliding window: a call at
            time `t` still counts while `now - t < period_seconds`).

            - `limiter()` returns `True` and records the call when allowed, `False` (and records
              nothing) when the limit is reached.
            - `limiter.remaining()` → how many calls are still allowed right now.
            - `repr` → `RateLimiter(max_calls=3, period_seconds=10)`.
            - `max_calls < 1` → `ValueError("max_calls must be at least 1")`;
              `period_seconds <= 0` → `ValueError("period_seconds must be positive")`.
            - `clock` is injected so the checks can control time.
            """
        ),
        code(
            '''
            class RateLimiter:
                """Calling the limiter asks: may I make one more call now?"""

                def __init__(
                    self,
                    max_calls: int,
                    period_seconds: float,
                    clock: Callable[[], float] = time.monotonic,
                ) -> None:
                    raise NotImplementedError("Lab 2.4: implement RateLimiter")
            '''
        ),
        md("Run the checks. `ManualClock` is a fake clock you move by hand."),
        code(
            '''
            class ManualClock:
                """A clock that only moves when told to."""

                def __init__(self) -> None:
                    self.now = 0.0

                def __call__(self) -> float:
                    return self.now


            def limiter_timeline() -> list[object]:
                """Three calls allowed per 10 s; record answers over time."""
                clock = ManualClock()
                limiter = RateLimiter(3, 10, clock=clock)
                answers: list[object] = [limiter(), limiter(), limiter(), limiter(), limiter.remaining()]
                clock.now = 9.9
                answers.append(limiter())
                clock.now = 10.0
                answers.extend([limiter.remaining(), limiter(), limiter()])
                return answers


            run_checks(
                [
                    ("callable", lambda: callable(RateLimiter(1, 1)), True),
                    ("timeline", limiter_timeline, [True, True, True, False, 0, False, 3, True, True]),
                    ("remaining at start", lambda: RateLimiter(5, 60, clock=ManualClock()).remaining(), 5),
                    ("repr", lambda: repr(RateLimiter(3, 10)), "RateLimiter(max_calls=3, period_seconds=10)"),
                    (
                        "max_calls",
                        lambda: raised_message(lambda: RateLimiter(0, 10)),
                        "ValueError: max_calls must be at least 1",
                    ),
                    (
                        "period",
                        lambda: raised_message(lambda: RateLimiter(1, 0)),
                        "ValueError: period_seconds must be positive",
                    ),
                ]
            )
            '''
        ),
        md(
            """
            #### Exercise 6 — an `Inventory` keyed by SKU

            `Inventory(stock=None)` maps SKU → quantity on hand (`stock` is an optional
            mapping to start from).

            - `inventory[sku]` → quantity; an unknown SKU raises `KeyError`.
            - `inventory[sku] = quantity` requires an `int >= 0`, otherwise
              `ValueError("quantity must be a non-negative int")` (the constructor checks
              `stock` the same way); `del inventory[sku]`.
            - `len` (number of SKUs), `in`, `bool`; iteration yields SKUs in **sorted** order.
            - `add(sku, quantity)` increases stock (a new SKU starts at 0);
              `remove(sku, quantity)` decreases it and raises
              `ValueError(f"not enough {sku}: have {have}, need {quantity}")` when short.
            - `total_units` property; `inventory + other` → a **new** `Inventory` with summed
              quantities; `==` compares stock; `repr` → `Inventory({'PEN-01': 5, 'TEA-500': 2})`
              with SKUs sorted.
            """
        ),
        code(
            '''
            class Inventory:
                """Quantities on hand, keyed by SKU."""

                def __init__(self, stock: Mapping[str, int] | None = None) -> None:
                    raise NotImplementedError("Lab 2.4: implement Inventory")
            '''
        ),
        md("Run the checks."),
        code(
            '''
            def stock_session() -> Inventory:
                """Add, remove, set and delete."""
                inventory = Inventory({"TEA-500": 2})
                inventory.add("PEN-01", 10)
                inventory.add("TEA-500", 3)
                inventory.remove("PEN-01", 4)
                inventory["MUG-02"] = 1
                del inventory["MUG-02"]
                return inventory


            def merge_leaves_operands() -> tuple[str, str]:
                """first + second must build a new Inventory; return both reprs."""
                first = Inventory({"A": 1})
                merged = first + Inventory({"A": 1})
                return repr(merged), repr(first)


            run_checks(
                [
                    ("session", lambda: repr(stock_session()), "Inventory({'PEN-01': 6, 'TEA-500': 5})"),
                    ("getitem", lambda: Inventory({"PEN-01": 6})["PEN-01"], 6),
                    ("unknown sku", lambda: raised_error_name(lambda: Inventory()["NOPE"]), "KeyError"),
                    (
                        "sorted iteration",
                        lambda: list(Inventory({"TEA-500": 1, "MUG-02": 0, "PEN-01": 3})),
                        ["MUG-02", "PEN-01", "TEA-500"],
                    ),
                    (
                        "len, in, bool",
                        lambda: (len(Inventory({"A": 1})), "A" in Inventory({"A": 1}), bool(Inventory())),
                        (1, True, False),
                    ),
                    (
                        "bad quantity",
                        lambda: raised_message(lambda: Inventory().__setitem__("A", -1)),
                        "ValueError: quantity must be a non-negative int",
                    ),
                    (
                        "not an int",
                        lambda: raised_message(lambda: Inventory({"A": 1.5})),
                        "ValueError: quantity must be a non-negative int",
                    ),
                    (
                        "not enough",
                        lambda: raised_message(lambda: Inventory({"PEN-01": 2}).remove("PEN-01", 5)),
                        "ValueError: not enough PEN-01: have 2, need 5",
                    ),
                    ("total_units", lambda: Inventory({"A": 2, "B": 3}).total_units, 5),
                    (
                        "merge with +",
                        lambda: repr(Inventory({"A": 2, "B": 1}) + Inventory({"B": 4, "C": 1})),
                        "Inventory({'A': 2, 'B': 5, 'C': 1})",
                    ),
                    (
                        "+ leaves operands alone",
                        merge_leaves_operands,
                        ("Inventory({'A': 2})", "Inventory({'A': 1})"),
                    ),
                    ("+ with dict", lambda: raised_error_name(lambda: Inventory() + {"A": 1}), "TypeError"),
                    (
                        "repr",
                        lambda: repr(Inventory({"TEA-500": 2, "PEN-01": 5})),
                        "Inventory({'PEN-01': 5, 'TEA-500': 2})",
                    ),
                ]
            )
            '''
        ),
    ]


def _recap_cells() -> list[NotebookNode]:
    """Recap for Unit 2.4."""
    return [
        md(
            """
            ### Recap — Unit 2.4

            | Concept | One-line takeaway | JS equivalent |
            | --- | --- | --- |
            | Data model | Syntax calls `type(x).__dunder__(x, …)`; implement the method, get the syntax | `Symbol.iterator`, `Symbol.toPrimitive` |
            | `__repr__` / `__str__` | repr for developers (and containers), str for users; write repr first | `toString()` |
            | `__format__` | Receives the text after `:`; custom specs are yours to define | — |
            | `__eq__` + `NotImplemented` | Decline unknown types so the other side (then identity) can answer | — |
            | `__hash__` | Defining `__eq__` sets it to `None`; hash only immutable fields | — (`Map` uses identity) |
            | Rich comparisons | Reflection is `a < b` → `b > a`; `total_ordering` fills in the rest | — |
            | `__bool__` / `__len__` | `__bool__` wins; `len` must be a non-negative int | — |
            | Container methods | `__getitem__` gets ints and `slice`s; `__missing__` for dict subclasses | `Proxy` traps |
            | `UserDict` / `UserList` | Overrides are honoured by every method; results keep your type | — |
            | `__call__` | Stateful function objects | functions with properties |
            | Numeric methods | `__add__`, `__radd__` (for `sum`), `__iadd__` only for mutable types | no operator overloading |
            | Special-method lookup | Implicit calls use the type, never the instance; `BINARY_OP` runs the protocol | — |

            **Further reading**

            - [Data model — special method names](https://docs.python.org/3/reference/datamodel.html#special-method-names)
              (the complete list), and
              [special method lookup](https://docs.python.org/3/reference/datamodel.html#special-method-lookup)
            - [`functools.total_ordering`](https://docs.python.org/3/library/functools.html#functools.total_ordering),
              [`collections.UserDict` / `UserList`](https://docs.python.org/3/library/collections.html#userdict-objects),
              [`NotImplemented`](https://docs.python.org/3/library/constants.html#NotImplemented)
            - [Format specification mini-language](https://docs.python.org/3/library/string.html#formatspec),
              [`dis` — `BINARY_OP`](https://docs.python.org/3/library/dis.html#opcode-BINARY_OP)
            - [PEP 207 — Rich comparisons](https://peps.python.org/pep-0207/),
              [PEP 465 — The `@` operator](https://peps.python.org/pep-0465/),
              [PEP 3101 — Advanced string formatting](https://peps.python.org/pep-3101/)
            """
        ),
    ]


def cells() -> list[NotebookNode]:
    """Return the cells for Unit 2.4 and Lab 2.4."""
    return [
        *_overview_cells(),
        *_data_model_cells(),
        *_representation_cells(),
        *_equality_cells(),
        *_ordering_cells(),
        *_truthiness_cells(),
        *_container_cells(),
        *_callable_cells(),
        *_numeric_cells(),
        *_lookup_cells(),
        *_lab_money_cells(),
        *_lab_vector_playlist_cells(),
        *_lab_dict_limiter_inventory_cells(),
        *_recap_cells(),
    ]
