# Unit 1.8 — Operators, Expressions and Control Flow

[← Previous](unit-1-7-copying-shallow-copies-deep-copies-and-structured-clones.md) · [Index](README.md) · [Next →](unit-1-9-iteration-comprehensions-and-built-in-functions.md)

This unit covers the everyday grammar of Python: the operators that build
expressions, the statements that choose between paths, and the loops that
repeat work. Most of it looks familiar to a JavaScript developer, which is
exactly the danger: `%` on negative numbers, `and` / `or`, operator precedence,
`match` and the `else` clause on loops all behave differently from their
JavaScript look-alikes.

## What you will learn

- Every operator family (arithmetic, comparison, logical, bitwise,
  membership, identity), how to read the precedence table, and how chained
  comparisons such as `0 < age <= 120` work.
- Why `and` / `or` return one of their operands, and how to avoid the
  `value or default` trap now that you have no `??`.
- How to write `if` / `elif` / `else`, conditional expressions and guard
  clauses.
- Structural pattern matching (`match`) with every pattern kind, its pitfalls,
  and how it differs from a JavaScript `switch`.
- `for`, `while`, `break`, `continue`, the `else` clause of loops, and how to
  emulate a do-while loop.
- Every assignment form, including the walrus operator `:=`, and the `*` /
  `**` unpacking operators.

## JavaScript → Python bridge

Python reuses many JavaScript symbols, but it replaces `&&`, `||` and `!` with
words, drops the ternary `?:` and `??`, and has no C-style `for` loop. The
table lists the differences that bite most often.

| JavaScript | Python | The difference that bites |
| --- | --- | --- |
| `a === b` | `a == b`, `a is b` | No coercion; `==` calls `__eq__` |
| `&&`, `\|\|`, `!` | `and`, `or`, `not` | `not` always returns a `bool` |
| `a ?? b` | `a if a is not None else b` | No `??`; `a or b` also replaces `0` |
| `c ? a : b` | `a if c else b` | The condition sits in the middle |
| `a < b && b < c` | `a < b < c` | Chained comparisons are real syntax |
| `-7 % 3` is `-1` | `-7 % 3` is `2` | `%` takes the divisor's sign |
| `5 & 1 == 0` | `5 & 1 == 0` | JS: `5 & (1 == 0)`; Python: `(5 & 1) == 0` |
| `switch` / `break` | `match` / `case` | No fall-through; patterns bind names |
| `for (let i = 0; …)` | `for index in range(n)` | No C-style loop, no `++` |
| `for (const x of xs)` | `for item in items` | Works on any iterable |
| `"key" in obj` | `key in mapping` | `in` on a list searches **values** |
| `[first, ...rest] = xs` | `first, *rest = items` | `rest` is always a `list` |

> **Note:** a few output lines in this unit are longer than a phone screen.
> They are wrapped at a comma or a space, and the continuation is indented by
> two spaces. Nothing else in the outputs is changed. Lines of code that were
> longer than 80 characters in the course notebook are reflowed (usually by
> splitting an f-string into two adjacent string literals, which Python joins,
> or by breaking a line inside brackets), so they behave exactly the same.

The examples use two small helpers. `raised_error_name` calls a function and
returns the name of the exception it raised, so one line can show "this raises
`TypeError`" without stopping the program. `compile_error` compiles a snippet
of source code **without running it** and reports any `SyntaxError`, so this
unit can show illegal code safely.

```python
import dis
import re
import sys
from collections.abc import Callable, Hashable, Iterable
from http import HTTPStatus
from typing import Any


def raised_error_name(thunk: Callable[[], object]) -> str:
    """Call thunk and return the name of the exception it raised.

    Returns "no error" when nothing was raised.
    """
    try:
        thunk()
    except Exception as error:
        return type(error).__name__
    return "no error"


def compile_error(source: str) -> str:
    """Compile source without running it.

    Return "SyntaxError: <message>" or "compiles".
    """
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

## 1.8.1 Operators and precedence

An *operator* is a symbol or keyword that combines values into a new value:
`a + b`, `a < b`, `x in items`. An *expression* is any piece of code that
produces a value. In CPython almost every operator is a thin layer over a
special ("dunder") method: `a + b` becomes `type(a).__add__(a, b)` (with
`type(b).__radd__(b, a)` as a fallback), `a < b` becomes `__lt__`, `x in c`
becomes `c.__contains__(x)`. That is why your own classes can support
operators (Phase 2), and why each built-in type decides for itself what an
operator means. Only `and`, `or`, `not`, `is` and `is not` are wired directly
into the interpreter and cannot be customised.

Python groups its operators into six families:

| Family | Operators |
| --- | --- |
| Arithmetic | `+ - * / // % ** @` |
| Comparison | `== != < <= > >=` |
| Logical | `and`, `or`, `not` |
| Bitwise | `& \| ^ ~ << >>` |
| Membership | `in`, `not in` |
| Identity | `is`, `is not` |

### Arithmetic

The arithmetic operators, one row each:

| Operator | What it does | Example | Result |
| --- | --- | --- | --- |
| `+` | Addition | `17 + 5` | `22` |
| `-` | Subtraction | `17 - 5` | `12` |
| `*` | Multiplication | `17 * 5` | `85` |
| `/` | True division, always a `float` | `4 / 2` | `2.0` |
| `//` | Floor division (toward −∞) | `-7 // 2` | `-4` |
| `%` | Remainder, divisor's sign | `-7 % 3` | `2` |
| `**` | Power | `2**10` | `1024` |
| `@` | Matrix multiply (for libraries) | `matrix_a @ matrix_b` | NumPy only |

Three things differ from JavaScript. First, `/` **always** returns a `float`,
even when the division is exact; Python has a separate `int` type, so it needs
a separate operator, `//`, for integer (floor) division. Second, `//` floors
toward negative infinity rather than truncating toward zero, so `-7 // 2` is
`-4` where JavaScript's `Math.trunc(-7 / 2)` is `-3`. Third, `%` takes the
sign of the **divisor** (JavaScript's takes the sign of the dividend). The two
choices go together: Python guarantees `a == (a // b) * b + a % b` for every
pair, and `divmod(a, b)` returns both halves at once. The practical upside is
that `index % length` is always a valid non-negative index, even for negative
`index`.

```python
items_in_stock, box_size = 17, 5
print(
    f"{items_in_stock + box_size=}, {items_in_stock - box_size=}, "
    f"{items_in_stock * box_size=}"
)
print(
    f"{items_in_stock / box_size=}, {items_in_stock // box_size=}, "
    f"{items_in_stock % box_size=}"
)
print(f"{2**10=}, {-items_in_stock=}, {+items_in_stock=}")
print(
    f"{-7 // 2=}, {-7 % 3=}  "
    "(JS: Math.trunc(-7 / 2) is -3, -7 % 3 is -1)"
)
print(f"{divmod(-7, 3)=}, {(-7 // 3) * 3 + (-7 % 3)=}")
print(f"{4 / 2=}  (true division always gives a float)")
```

```text
items_in_stock + box_size=22, items_in_stock - box_size=12,
  items_in_stock * box_size=85
items_in_stock / box_size=3.4, items_in_stock // box_size=3,
  items_in_stock % box_size=2
2**10=1024, -items_in_stock=-17, +items_in_stock=17
-7 // 2=-4, -7 % 3=2  (JS: Math.trunc(-7 / 2) is -3, -7 % 3 is -1)
divmod(-7, 3)=(-3, 2), (-7 // 3) * 3 + (-7 % 3)=-7
4 / 2=2.0  (true division always gives a float)
```

> **Note:** ints have arbitrary precision, so `+`, `-`, `*` and `**` on ints
> never overflow; they just get slower as the numbers grow. `float` follows
> IEEE 754 exactly as JavaScript numbers do (Unit 1.3).

### Comparison

`==` compares **values** by calling `__eq__`, and it never coerces types. Ints
and floats compare by numeric value (`1 == 1.0`), but a string never equals a
number, so there is no need for a separate `===`. Ordering operators between
unrelated types (`"10" < 5`) raise `TypeError` instead of guessing, which
removes a whole class of JavaScript bugs. Strings compare by Unicode code
point, so every uppercase ASCII letter sorts before every lowercase one.
Sequences of the same type (lists, tuples, strings) compare element by
element, lexicographically, which makes tuples handy for comparing dates or
version numbers.

```python
print(f"{1 == 1.0=}, {1 == '1'=}, {1 != '1'=}")
print(
    f"{'apple' < 'banana'=}, {'Zebra' < 'apple'=}  "
    "(code point order: 'Z' < 'a')"
)
print(f"{[1, 2, 3] < [1, 3]=}, {(2026, 11) >= (2026, 10)=}")
print(f"'10' < 5: {raised_error_name(lambda: '10' < 5)}")
```

```text
1 == 1.0=True, 1 == '1'=False, 1 != '1'=True
'apple' < 'banana'=True, 'Zebra' < 'apple'=True  (code point order: 'Z' < 'a')
[1, 2, 3] < [1, 3]=True, (2026, 11) >= (2026, 10)=True
'10' < 5: TypeError
```

`[1, 2, 3] < [1, 3]` is `True` because the first difference decides: at index
1, `2 < 3`. The length only matters when one sequence is a prefix of the other.

### Logical

`and`, `or` and `not` are spelled as words. They work on *truthiness*
(Unit 1.3): `None`, `0`, `0.0`, empty strings and empty containers are falsy,
almost everything else is truthy. Section 1.8.2 shows that `and` and `or`
return one of their operands, not necessarily a `bool`.

```python
is_logged_in, has_items = True, False
print(
    f"{is_logged_in and has_items=}, {is_logged_in or has_items=}, "
    f"{not has_items=}"
)
print(f"{not []=}, {not 'text'=}")
```

```text
is_logged_in and has_items=False, is_logged_in or has_items=True,
  not has_items=True
not []=True, not 'text'=False
```

> **Note:** unlike JavaScript, an empty list `[]` and an empty dict `{}` are
> **falsy** in Python. `if items:` is the idiomatic "is the list non-empty?"
> test.

### Bitwise

The bitwise operators work on the binary digits of ints:

| Operator | What it does | Example | Result |
| --- | --- | --- | --- |
| `&` | AND: bits set in both | `0b011 & 0b010` | `2` |
| `\|` | OR: bits set in either | `0b001 \| 0b010` | `3` |
| `^` | XOR: bits set in one only | `0b011 ^ 0b010` | `1` |
| `~` | Invert: `-x - 1` | `~5` | `-6` |
| `<<` | Shift left | `1 << 4` | `16` |
| `>>` | Shift right | `256 >> 2` | `64` |

Because Python ints have arbitrary precision, shifts never overflow:
`1 << 100` is a 31-digit number. JavaScript, by contrast, converts both
operands to 32-bit signed integers before any bitwise operation. Python's `~x`
is defined as `-x - 1`, which is what two's complement gives on an infinitely
wide integer. A typical use is a set of permission flags packed into one int.

```python
READ, WRITE, DELETE = 0b001, 0b010, 0b100
editor_permissions = READ | WRITE
print(f"{editor_permissions=:03b}, {editor_permissions & WRITE != 0=}")
print(f"{editor_permissions & DELETE != 0=}  (& binds tighter than !=)")
print(f"{editor_permissions ^ WRITE=:03b}  (toggle WRITE off)")
print(f"{~5=}, {1 << 4=}, {256 >> 2=}")
print(f"{1 << 100=}  (no 32-bit overflow)")
```

```text
editor_permissions=011, editor_permissions & WRITE != 0=True
editor_permissions & DELETE != 0=False  (& binds tighter than !=)
editor_permissions ^ WRITE=001  (toggle WRITE off)
~5=-6, 1 << 4=16, 256 >> 2=64
1 << 100=1267650600228229401496703205376  (no 32-bit overflow)
```

> **Warning:** in JavaScript, `flags & WRITE != 0` parses as
> `flags & (WRITE != 0)`, a classic bug. In Python the bitwise operators bind
> **tighter** than comparisons, so the same text means `(flags & WRITE) != 0`,
> which is what you meant. Code ported between the two languages can silently
> change meaning; add parentheses.

For real flag sets, the standard library's `enum.Flag` gives the same packing
with readable names (Phase 2).

### Membership

`x in container` asks the container whether it contains `x`, by calling its
`__contains__` method. Each type answers in its own way, and with its own
cost:

| Container | `in` checks | Cost |
| --- | --- | --- |
| `list`, `tuple` | values, one by one | O(n) |
| `str` | substrings | O(n) typical |
| `dict` | **keys** only | O(1) average |
| `set`, `frozenset` | elements | O(1) average |

If a type has no `__contains__`, Python falls back to iterating over it.
`not in` is a single operator, the readable form of `not (x in container)`.

```python
print(f"{'tea' in ['tea', 'rice']=}, {'ghee' not in ('tea', 'rice')=}")
print(f"{'err' in 'server error'=}  (substring)")
print(f"{'tea' in {'tea': 249}=}, {249 in {'tea': 249}=}  (keys only)")
print(f"{249 in {'tea': 249}.values()=}, {101 in {101, 102}=}")
```

```text
'tea' in ['tea', 'rice']=True, 'ghee' not in ('tea', 'rice')=True
'err' in 'server error'=True  (substring)
'tea' in {'tea': 249}=True, 249 in {'tea': 249}=False  (keys only)
249 in {'tea': 249}.values()=True, 101 in {101, 102}=True
```

> **Note:** JavaScript's `in` checks *property names* of an object, and on an
> array it checks indexes (`0 in ["tea"]` is `true`). Python's `in` on a list
> checks **values**, like `Array.prototype.includes`. If you test membership
> many times, convert the list to a `set` first.

### Identity

`is` checks that two names refer to the **same object**: it compares the
objects' identities (in CPython, their memory addresses), which is a single
pointer comparison and cannot be overridden. Use it for singletons (`None`,
`True`, `False`, sentinel objects), never for comparing numbers or strings,
whose identity depends on caching details (Unit 1.2).

```python
discount_code = None
saved_cart = ["tea"]
same_cart = saved_cart
fresh_cart = ["tea"]
print(
    f"{discount_code is None=}, {saved_cart is same_cart=}, "
    f"{saved_cart is not fresh_cart=}"
)
print(f"{saved_cart == fresh_cart=}  (equal values, different objects)")
```

```text
discount_code is None=True, saved_cart is same_cart=True,
  saved_cart is not fresh_cart=True
saved_cart == fresh_cart=True  (equal values, different objects)
```

### Precedence

Precedence decides how an expression without parentheses is grouped. The
table runs from highest (binds tightest) to lowest. Operators on the same level
group left to right, except `**`, which groups right to left.

| Level | Operators | Notes |
| --- | --- | --- |
| 1 | `(...)`, `[...]`, `{...}` | Displays and grouping |
| 2 | `x[i]`, `x[a:b]`, `f(args)`, `x.attr` | Subscript, slice, call, attribute |
| 3 | `await x` | |
| 4 | `**` | Right-associative |
| 5 | `+x`, `-x`, `~x` | Unary |
| 6 | `*`, `@`, `/`, `//`, `%` | |
| 7 | `+`, `-` | Binary |
| 8 | `<<`, `>>` | |
| 9 | `&` | |
| 10 | `^` | |
| 11 | `\|` | |
| 12 | `in`, `not in`, `is`, `is not` | Same level as the row below |
| 12 | `<`, `<=`, `>`, `>=`, `!=`, `==` | All one level, chainable |
| 13 | `not x` | |
| 14 | `and` | |
| 15 | `or` | |
| 16 | `x if condition else y` | Conditional expression |
| 17 | `lambda` | |
| 18 | `:=` | Assignment expression |

Level 12 is split over two rows only to fit a phone screen: all ten
comparison operators (membership and identity included) share one level and
can be chained together.

Two entries deserve a closer look. `**` binds tighter than a unary minus **on
its left**, so `-2**2` is `-(2**2)`, which is `-4` (JavaScript refuses to
parse `-2 ** 2` at all and forces you to add parentheses). On its right, a
unary minus is fine: `2**-1` is `0.5`. And `not` sits **below** the
comparisons, so `not a == b` means `not (a == b)`. The next cell shows the
cases that surprise people. When in doubt, add parentheses.

```python
print(f"{-2**2=}  (** first: -(2**2))")
print(f"{2**3**2=}  (right-associative: 2**(3**2))")
print(f"{1 + 2 * 3=}, {(1 + 2) * 3=}")
print(f"{5 & 1 == 0=}  ((5 & 1) == 0, unlike JS where == binds first)")
print(f"{not 1 == 2=}  (not (1 == 2))")
print(f"{True or False and False=}  (and before or)")
```

```text
-2**2=-4  (** first: -(2**2))
2**3**2=512  (right-associative: 2**(3**2))
1 + 2 * 3=7, (1 + 2) * 3=9
5 & 1 == 0=False  ((5 & 1) == 0, unlike JS where == binds first)
not 1 == 2=True  (not (1 == 2))
True or False and False=True  (and before or)
```

### Predict the output: precedence and negative numbers

```python
print(-3**2, 2**-1, 7 // -2, -7 % 3)
```

<details><summary>Answer</summary>

```text
-9 0.5 -4 2
```

`**` binds tighter than the unary minus on its left, so `-3**2` is `-(3**2)`;
a negative exponent gives a float; `//` floors toward negative infinity
(`-3.5` → `-4`); `%` takes the sign of the divisor, so `-7 % 3` is `2`.

</details>

### Chained comparisons

`0 < age <= 120` means `0 < age and age <= 120`, except that `age` is
evaluated **once**. This is real syntax, not a trick: any comparison operators
can chain, which gives readable `low <= value < high` range checks and
`a == b == c` equality checks. In JavaScript, `0 < age <= 120` is a silent
bug: `0 < age` produces `true` or `false`, which is then coerced to `1` or `0`
and compared with `120`, so it is always `true`.

The flip side is that confusing chains such as `x < y > z` are also legal, and
so is `1 < 2 == True`, which does **not** mean `(1 < 2) == True`.

```python
def is_valid_age(age: int) -> bool:
    """Return True for a plausible human age."""
    return 0 < age <= 120


print(f"{is_valid_age(35)=}, {is_valid_age(0)=}, {is_valid_age(130)=}")
first_price, second_price, third_price = 249, 249, 249
print(f"{first_price == second_price == third_price=}")
print(f"{1 < 3 > 2=}  (legal but unclear: 1 < 3 and 3 > 2)")
print(
    f"{(1 < 2) == True=}, {1 < 2 == True=}  "  # noqa: E712
    "(1 < 2 and 2 == True)"
)
```

```text
is_valid_age(35)=True, is_valid_age(0)=False, is_valid_age(130)=False
first_price == second_price == third_price=True
1 < 3 > 2=True  (legal but unclear: 1 < 3 and 3 > 2)
(1 < 2) == True=True, 1 < 2 == True=False  (1 < 2 and 2 == True)
```

> **Warning:** `1 < 2 == True` is `(1 < 2) and (2 == True)`, and `2 == True`
> is `False` because `True` equals `1`. Never compare with `== True`; write
> the condition itself.

### Under the hood: a chained comparison in bytecode

`dis` shows how `0 < age <= 120` evaluates `age` once. It is loaded a single
time, `COPY` duplicates it for the second comparison, and a conditional jump
(`POP_JUMP_IF_FALSE`) skips the second comparison when the first is false:
the same short-circuit as `and`.

```python
dis.dis(is_valid_age)
```

```text
  1           RESUME                   0

  3           LOAD_SMALL_INT           0
              LOAD_FAST                0 (age)
              SWAP                     2
              COPY                     2
              COMPARE_OP               2 (<)
              COPY                     1
              TO_BOOL
              POP_JUMP_IF_FALSE        6 (to L1)
              NOT_TAKEN
              POP_TOP
              LOAD_SMALL_INT         120
              COMPARE_OP              42 (<=)
              RETURN_VALUE
      L1:     SWAP                     2
              POP_TOP
              RETURN_VALUE
```

> **Note:** opcode names and arguments vary between Python versions; this
> listing is from Python 3.15. The line numbers on the left (1 and 3) depend
> on where the function is defined, so yours may differ.

### Key points

| Idea | Takeaway |
| --- | --- |
| `/` vs `//` | `/` gives a float; `//` floors toward −∞ |
| `%` | Takes the divisor's sign |
| `==` | Value equality, never coerces |
| Ordering mixed types | `TypeError`, not a guess |
| Bitwise | No 32-bit limit; binds tighter than `==` |
| `in` | Values in lists, substrings in str, keys in dicts |
| `is` | Same object; use for `None` and sentinels |
| `**` | Right-associative; `-2**2` is `-4` |
| Chains | `0 < age <= 120`; middle evaluated once |

## 1.8.2 Boolean operators return operands

`and` and `or` short-circuit exactly like JavaScript's `&&` and `||`, and like
them they return **one of their operands**, not `True` or `False`. `not` is
different: it always returns a `bool`.

| Expression | Returns |
| --- | --- |
| `a or b` | `a` if `a` is truthy, else `b` |
| `a and b` | `a` if `a` is falsy, else `b` |
| `not a` | always a `bool` |

The right operand is evaluated **only if it is needed**. CPython compiles
`a or b` into "evaluate `a`; if it is truthy, jump to the end with `a` still on
the stack; otherwise discard it and evaluate `b`". No `bool` object is ever
built for the result, which is why the operand itself comes back. The next
cell uses a function with a visible side effect to prove which operands run.

```python
def loud(value: object) -> object:
    """Print the value, then return it (to see which operands run)."""
    print(f"  evaluated {value!r}")
    return value


print(f"result {loud('') or loud('guest')!r}")
print(f"result {loud('asha') or loud('guest')!r}  (right side skipped)")
print(f"result {loud(0) and loud(1 / 1)!r}  (right side skipped)")
print(f"{[] and 1 / 0=}  (1 / 0 never runs)")
print(f"{not 'asha'=}, {not 0=}, {type(not 'asha').__name__=}")
```

```text
  evaluated ''
  evaluated 'guest'
result 'guest'
  evaluated 'asha'
result 'asha'  (right side skipped)
  evaluated 0
result 0  (right side skipped)
[] and 1 / 0=[]  (1 / 0 never runs)
not 'asha'=False, not 0=True, type(not 'asha').__name__='bool'
```

`[] and 1 / 0` returns `[]` without ever dividing by zero: the left operand is
falsy, so `and` returns it and stops. Short-circuiting is therefore a real
control-flow tool (`user and user.name`), not just an optimisation.

### `value or default` and its `0` trap

`or` makes a handy default, but it replaces **every** falsy value: `0`, `0.0`,
`""`, `[]`, `False`, not only `None`. If those are valid inputs, it silently
changes them. JavaScript's `||` has the very same trap, which is why
JavaScript added `??`. Python has **no** `??` (null-coalescing) operator:
PEP 505 proposed `??` and `?.` and was deferred. The explicit form is a
conditional expression on `is not None`.

```python
def items_per_page_with_or(requested: int | None) -> int:
    """Default to 20 when nothing was requested (buggy: 0 too)."""
    return requested or 20


def items_per_page(requested: int | None) -> int:
    """Default to 20 only when requested is None (JS `requested ?? 20`)."""
    return requested if requested is not None else 20


for requested in (None, 50, 0):
    print(
        f"{requested=}: with or -> {items_per_page_with_or(requested)}, "
        f"with is not None -> {items_per_page(requested)}"
    )
display_name = "" or "Anonymous"
print(f"{display_name=}  (fine here: an empty name should get the default)")
```

```text
requested=None: with or -> 20, with is not None -> 20
requested=50: with or -> 50, with is not None -> 50
requested=0: with or -> 20, with is not None -> 0
display_name='Anonymous'  (fine here: an empty name should get the default)
```

> **Warning:** `requested or 20` turns a deliberate `0` into `20`. Use `or`
> only when *every* falsy value should get the default (an empty display
> name, say). When only "missing" should, write
> `value if value is not None else default`.

An `or` chain picks the first truthy value, which reads well for layered
settings when empty values really do mean "not set":

```python
cli_region, env_region, default_region = None, "", "ap-south-1"
chosen_region = cli_region or env_region or default_region
print(f"{chosen_region=}")
```

```text
chosen_region='ap-south-1'
```

### Key points

| Idea | Takeaway |
| --- | --- |
| `a or b` | First truthy operand, else `b` |
| `a and b` | First falsy operand, else `b` |
| `not a` | Always `True` or `False` |
| Short-circuit | Right side runs only if needed |
| `value or default` | Replaces `0`, `""`, `[]` too |
| No `??` | `x if x is not None else default` |

## 1.8.3 Conditionals

`if` / `elif` / `else` work like JavaScript's `if` / `else if` / `else`, with
three spelling differences: there are no parentheses around the condition, a
colon ends the header line, and the body is an indented block instead of
braces. Any object can be a condition; Python calls its truth test
(`__bool__`, or `__len__` as a fallback) just as JavaScript applies
`ToBoolean`. The branches are tried top to bottom; the first true one runs and
the rest are skipped.

```python
def shipping_fee(order_total: int) -> int:
    """Return the delivery fee in rupees for an order total."""
    if order_total >= 999:
        return 0
    elif order_total >= 499:
        return 40
    else:
        return 80


for order_total in (1200, 650, 120):
    print(f"{order_total=}: {shipping_fee(order_total)=}")
```

```text
order_total=1200: shipping_fee(order_total)=0
order_total=650: shipping_fee(order_total)=40
order_total=120: shipping_fee(order_total)=80
```

### Conditional expression

`value_if_true if condition else value_if_false` is an **expression**: it has
a value and can sit anywhere a value can, such as an assignment, an argument or
an f-string. It is Python's version of JavaScript's `condition ? a : b`, with
the condition moved to the middle so the line reads like English. Only the
chosen branch is evaluated. Keep it to one simple condition; nested
conditional expressions are hard to read, so use `if` / `elif` instead.

```python
stock_count = 0
availability = "in stock" if stock_count > 0 else "sold out"
print(f"{availability=}")
plural_suffix = "" if stock_count == 1 else "s"
print(f"{stock_count} item{plural_suffix} left")
```

```text
availability='sold out'
0 items left
```

### Guard clauses

A *guard clause* handles a special case first and leaves the function at once
with `return` (or `raise`), so the main path is not buried inside nested `if`
blocks. Because Python marks blocks with indentation, deep nesting is
especially visible and especially costly to read. Both functions below behave
the same; the second one is flat, and each rule sits on its own line.

```python
def ship_order_nested(order: dict[str, Any]) -> str:
    """Decide what to do with an order (nested style)."""
    if order["paid"]:
        if order["items"]:
            if order["address"]:
                return f"shipping order {order['order_id']}"
            else:
                return "missing address"
        else:
            return "empty order"
    else:
        return "awaiting payment"


def ship_order(order: dict[str, Any]) -> str:
    """Decide what to do with an order (guard clauses)."""
    if not order["paid"]:
        return "awaiting payment"
    if not order["items"]:
        return "empty order"
    if not order["address"]:
        return "missing address"
    return f"shipping order {order['order_id']}"


pending_order = {
    "order_id": 1001, "paid": True, "items": ["tea"], "address": ""
}
print(f"{ship_order_nested(pending_order)=}, {ship_order(pending_order)=}")
```

```text
ship_order_nested(pending_order)='missing address',
  ship_order(pending_order)='missing address'
```

### Empty blocks and `elif`

A block can never be empty: the parser needs at least one statement after the
colon. Use `pass` (a statement that does nothing) or `...` as a placeholder.
There is also no `else if`; the keyword is `elif`. Forgetting the indentation
is a `SyntaxError` caught before anything runs.

```python
log_level = "DEBUG"
if log_level == "DEBUG":
    pass  # nothing to do yet; the block must not be empty
print(compile_error("if True:\nprint(1)"))
```

```text
SyntaxError: expected an indented block after 'if' statement on line 1
```

> **Note:** the notebook builds the source with `'if True:' + chr(10) +
> 'print(1)'`; `"\n"` is the same newline character (`chr(10)`), written more
> briefly here so the output fits a phone screen.

### Key points

| Idea | Takeaway |
| --- | --- |
| Syntax | `if cond:` + indented block; `elif`, `else:` |
| Conditions | Any object; truthiness decides |
| Ternary | `a if condition else b` |
| Guard clauses | Handle special cases first, return early |
| Empty block | Use `pass` |

## 1.8.4 Structural pattern matching (`match`)

`match subject:` compares one value, the *subject*, against a list of `case`
patterns, top to bottom, and runs the **first** case that matches. It arrived
in Python 3.10 (PEP 634). It looks like a `switch`, but it is much closer to
destructuring: a pattern describes the *shape* of the data (its type, its
length, its keys, its values) and can bind parts of it to names in the same
step. Only the subject expression is evaluated once; then each pattern is
tested in order.

| Pattern | Example | Matches |
| --- | --- | --- |
| Literal | `case 200:` | Equal value |
| Or | `case 401 \| 403:` | Any alternative |
| Capture | `case other:` | Anything; binds `other` |
| Wildcard | `case _:` | Anything; binds nothing |
| Sequence | `case [cmd, *args]:` | List/tuple of that shape |
| Mapping | `case {"type": t, **rest}:` | Mapping with those keys |
| Class | `case Point(0, y):` | `isinstance` + attributes |
| Value | `case HTTPStatus.NOT_FOUND:` | Equal to a dotted name |
| Guard | `case [x, y] if x == y:` | Pattern **and** condition |
| As | `case [("go" \| "stop") as act]:` | Binds a sub-pattern's value |

Each of the next examples shows one pattern kind.

### Literal patterns

Numbers, strings, `None`, `True` and `False` can be patterns. Literals compare
with `==`, except the three singletons `None`, `True` and `False`, which
compare with `is` (so `case True:` does not match `1`).

```python
def describe_status(status_code: int) -> str:
    """Describe an HTTP status code with literal patterns."""
    match status_code:
        case 200:
            return "OK"
        case 404:
            return "Not Found"
        case _:
            return "something else"


print(
    f"{describe_status(200)=}, {describe_status(404)=}, "
    f"{describe_status(418)=}"
)
```

```text
describe_status(200)='OK', describe_status(404)='Not Found',
  describe_status(418)='something else'
```

### Or patterns

`|` inside a pattern separates alternatives; the case matches if any of them
does. This replaces JavaScript's stacked `case 1: case 2:` labels. (It is not
the bitwise operator here: inside a `case`, `|` is pattern syntax.)

```python
def status_family(status_code: int) -> str:
    """Group status codes with or-patterns."""
    match status_code:
        case 200 | 201 | 204:
            return "success"
        case 401 | 403:
            return "auth problem"
        case _:
            return "other"


print(
    f"{status_family(201)=}, {status_family(403)=}, "
    f"{status_family(500)=}"
)
```

```text
status_family(201)='success', status_family(403)='auth problem',
  status_family(500)='other'
```

### Capture patterns

A bare name matches **anything** and binds the matched value to that name. A
capture used as a whole case is *irrefutable* (it can never fail), so it must
be the last case; the compiler rejects any case after it.

```python
def label_quantity(quantity: int) -> str:
    """Use a capture pattern for 'any other value'."""
    match quantity:
        case 0:
            return "none"
        case 1:
            return "one"
        case many:
            return f"{many} items"


print(f"{label_quantity(0)=}, {label_quantity(7)=}")
```

```text
label_quantity(0)='none', label_quantity(7)='7 items'
```

### Wildcard `_`

`_` matches anything and binds nothing; inside a pattern it is not a variable
at all. Alone, it is the `default:` of a `switch`. It can also stand in for
parts of other patterns, as in `["help", _]`: "a two-element sequence whose
first item is `"help"`, second item anything".

```python
def first_word_kind(words: list[str]) -> str:
    """Use _ alone and inside a sequence pattern."""
    match words:
        case ["help", _]:
            return "help with a topic"
        case _:
            return "anything else"


print(f"{first_word_kind(['help', 'deploy'])=}")
print(f"{first_word_kind(['status'])=}")
```

```text
first_word_kind(['help', 'deploy'])='help with a topic'
first_word_kind(['status'])='anything else'
```

### Sequence patterns

`[a, b]` or `(a, b)` (the bracket style does not matter) matches any
*sequence* of exactly that length whose items match the sub-patterns. One
starred name, `*rest`, collects any remaining items into a **list**, so
`[command, *arguments]` means "at least one item". Strings, `bytes` and
`bytearray` are deliberately **not** treated as sequences here, so `"abc"`
never matches `[a, b, c]`; otherwise every string would be picked apart
character by character by accident.

```python
def describe_words(words: list[str]) -> str:
    """Match on the shape of a split command."""
    match words:
        case []:
            return "empty"
        case [single_word]:
            return f"one word: {single_word}"
        case [command, *arguments]:
            return (
                f"{command} with {len(arguments)} argument(s): "
                f"{arguments}"
            )


print(describe_words([]))
print(describe_words(["status"]))
print(describe_words(["copy", "a.txt", "b.txt"]))
print(f"{describe_words('ab')=}  (a str never matches a sequence pattern)")
```

```text
empty
one word: status
copy with 2 argument(s): ['a.txt', 'b.txt']
describe_words('ab')=None  (a str never matches a sequence pattern)
```

`describe_words('ab')` returns `None` because no case matched, so the function
fell off its end. A `match` with no matching case simply does nothing.

### Mapping patterns

`{"key": pattern, ...}` matches any mapping (a `dict` or anything registered
as a `Mapping`) that **has** those keys and whose values match the
sub-patterns. Extra keys are **ignored**, which is ideal for JSON payloads
that grow new fields over time. `**rest` captures the keys that were not
mentioned into a new dict.

```python
def describe_event(event: dict[str, Any]) -> str:
    """Match dicts by their keys."""
    match event:
        case {"type": "login", "user": user_name}:
            return f"login by {user_name}"
        case {"type": event_type, **other_fields}:
            return (
                f"{event_type} event with extra keys "
                f"{sorted(other_fields)}"
            )
        case _:
            return "not an event"


print(describe_event({"type": "login", "user": "asha", "ip": "10.0.0.1"}))
print(describe_event({"type": "logout", "user": "ravi", "reason": "timeout"}))
print(describe_event({"user": "meena"}))
```

```text
login by asha
logout event with extra keys ['reason', 'user']
not an event
```

> **Note:** sequence patterns check the *length* exactly, but mapping
> patterns check only for the keys they list. `{"type": t}` matches a dict
> with twenty keys; `[a]` matches only a one-item list.

### Class patterns and `__match_args__`

`ClassName(...)` first checks `isinstance(subject, ClassName)` and then
matches attributes. Keyword sub-patterns (`Point(x=0)`) name the attribute
directly. Positional sub-patterns (`Point(0, y)`) need a mapping from position
to attribute name, which the class provides in its `__match_args__` tuple.
Dataclasses and named tuples generate `__match_args__` for you (Phase 2); here
it is written by hand. Built-in types such as `int(n)` and `str(s)` are
special: a single positional sub-pattern matches the **whole** value, which
makes `int(number)` a combined type check and capture.

```python
class Point:
    """A 2-D point with __match_args__ for positional class patterns."""

    __match_args__ = ("x", "y")

    def __init__(self, x: int, y: int) -> None:
        self.x = x
        self.y = y


def where_is(location: object) -> str:
    """Use class patterns, positional and keyword."""
    match location:
        case Point(0, 0):
            return "origin"
        case Point(0, y):
            return f"on the y axis at {y}"
        case Point(x=x, y=0):
            return f"on the x axis at {x}"
        case Point():
            return "somewhere else"
        case int(number) | float(number):
            return f"a number: {number}"
        case _:
            return "not a point"


for location in (Point(0, 0), Point(0, 5), Point(3, 0), Point(2, 2), 7, "home"):
    print(where_is(location))
```

```text
origin
on the y axis at 5
on the x axis at 3
somewhere else
a number: 7
not a point
```

`case Point():` with empty parentheses is a pure type check. Note that
`Point(x=x, y=0)` reads oddly but is correct: the `x` on the left of `=` is
the attribute name, the `x` on the right is the capture variable.

> **Warning:** `case Point:` without parentheses is **not** a class pattern.
> It is a capture pattern that binds the subject to a variable named `Point`,
> shadowing your class. Always write the parentheses.

### Guards

`case pattern if condition:` matches only when the pattern matches **and**
the condition, which can use the names the pattern just bound, is true. If the
guard fails, matching simply continues with the next case. Guards cover
everything a pattern cannot express by itself: comparisons between captured
values, ranges, regex checks.

```python
def classify_pair(pair: tuple[int, int]) -> str:
    """Use guards on top of a sequence pattern."""
    match pair:
        case (first, second) if first == second:
            return "equal"
        case (first, second) if first > second:
            return "descending"
        case (_, _):
            return "ascending"
        case _:
            return "not a pair"


print(
    f"{classify_pair((3, 3))=}, {classify_pair((5, 1))=}, "
    f"{classify_pair((1, 5))=}"
)
```

```text
classify_pair((3, 3))='equal', classify_pair((5, 1))='descending',
  classify_pair((1, 5))='ascending'
```

> **Note:** in CPython, names bound by a pattern can stay bound even when the
> guard then fails (the language reference leaves this unspecified). Do not
> rely on the values of capture variables from a case that did not run.

### `as` bindings

`pattern as name` binds the value matched by a sub-pattern. It is most useful
after an or-pattern: the or-pattern tells you *that* one of the alternatives
matched, and `as` tells you *which*. It also works on a whole case, to keep the
entire subject while still checking its shape.

```python
def service_action(words: list[str]) -> str:
    """Bind the matched alternative with as."""
    match words:
        case [("start" | "stop" | "restart") as action, service_name]:
            return f"{action} {service_name}"
        case [_, *_] as whole_command:
            return f"unknown command {whole_command}"
        case _:
            return "empty"


print(f"{service_action(['restart', 'nginx'])=}")
print(f"{service_action(['reload', 'nginx'])=}")
```

```text
service_action(['restart', 'nginx'])='restart nginx'
service_action(['reload', 'nginx'])="unknown command ['reload', 'nginx']"
```

### No fall-through: `match` versus JavaScript `switch`

Exactly one case runs, or none. There is no `break`, and no way to fall into
the next case. If no case matches, nothing happens and no error is raised
(add `case _:` if you want to catch "everything else").

| Aspect | JavaScript `switch` | Python `match` |
| --- | --- | --- |
| Comparison | `===` per `case` value | Structural patterns |
| After a match | Falls through to `break` | Runs one case, leaves |
| Several values | `case 1: case 2:` | `case 1 \| 2:` |
| Destructuring | No | Binds names |
| Conditions | No (use `if`) | `case … if condition:` |
| Default | `default:` | `case _:` |
| No match | Nothing happens | Nothing happens |

```python
def count_matches(signal: str) -> list[str]:
    """Show that only the first matching case runs."""
    ran_cases = []
    match signal:
        case "go":
            ran_cases.append("first go case")
        case "go":  # also matches, but never runs
            ran_cases.append("second go case")
    return ran_cases


print(f"{count_matches('go')=}, {count_matches('stop')=}")
print("(no match is not an error)")
```

```text
count_matches('go')=['first go case'], count_matches('stop')=[]
(no match is not an error)
```

### The bare-name capture trap

This is the most common `match` bug. A bare name in a pattern is **always** a
capture, never a lookup of an existing variable. `case NOT_FOUND:` does not
compare the subject with your constant `NOT_FOUND`; it matches everything and
**rebinds** `NOT_FOUND` to the subject. If more cases follow, Python refuses
to compile the `match`, because they could never be reached. If it is the last
case, the code compiles and silently "works", overwriting your constant.

```python
trap_source = """
NOT_FOUND = 404
match 200:
    case NOT_FOUND:
        print("not found")
    case _:
        print("other")
"""
print(compile_error(trap_source))

NOT_FOUND = 404
match 200:
    case NOT_FOUND:  # captures 200 and rebinds the name
        print("this runs for 200!")
print(f"{NOT_FOUND=}  (the 'constant' was overwritten)")
```

```text
SyntaxError: name capture 'NOT_FOUND' makes remaining patterns unreachable
this runs for 200!
NOT_FOUND=200  (the 'constant' was overwritten)
```

### Dotted names are value patterns

Any name containing a dot (`HTTPStatus.NOT_FOUND`, `config.LIMIT`) is a
*value pattern*: Python looks it up and compares it with `==`. That is the
rule that makes enums and constants on a class or module usable as cases, and
it is the standard fix for the capture trap. `HTTPStatus` is an `IntEnum`, so
its members also equal plain ints.

```python
def describe_with_enum(status_code: int) -> str:
    """Use dotted names as constant (value) patterns."""
    match status_code:
        case HTTPStatus.OK:
            return "OK"
        case HTTPStatus.NOT_FOUND:
            return "Not Found"
        case _:
            return "other"


print(
    f"{describe_with_enum(404)=}, {describe_with_enum(200)=}, "
    f"{describe_with_enum(500)=}"
)
```

```text
describe_with_enum(404)='Not Found', describe_with_enum(200)='OK',
  describe_with_enum(500)='other'
```

> **Warning:** if a constant must appear in a pattern, give it a dot: put it
> in an `Enum`, a class or a module and write `Status.NOT_FOUND`. A plain
> module-level `NOT_FOUND` can only be compared in a guard
> (`case code if code == NOT_FOUND:`).

### Demo: a command parser

A tiny deploy tool turns a command line into an action. Splitting the text
gives a list of words, and the `match` picks it apart: sequence patterns fix
the shape, or-patterns accept aliases, `as` records which alias matched,
guards validate arguments with a regular expression, and `*flags` gathers
optional flags. Case order matters: the specific `deploy` case comes before
the general one that reports an unknown environment.

```python
def run_deploy_command(command_text: str) -> str:
    """Parse a deploy-tool command and describe the action it would take."""
    match command_text.split():
        case ["deploy", ("staging" | "production") as environment]:
            return f"deploying to {environment}"
        case ["deploy", environment]:
            return f"error: unknown environment {environment!r}"
        case ["rollback", version] if re.fullmatch(
            r"v\d+\.\d+\.\d+", version
        ):
            return f"rolling back to {version}"
        case ["rollback", _]:
            return "error: version must look like v1.2.3"
        case ["logs", service_name, *flags]:
            follow = "--follow" in flags
            return f"showing logs for {service_name} (follow={follow})"
        case ["status" | "st"]:
            return "showing status"
        case []:
            return "error: empty command"
        case [unknown_command, *_]:
            return f"error: unknown command {unknown_command!r}"


sample_commands = [
    "deploy staging",
    "deploy moon",
    "rollback v2.0.1",
    "rollback 2",
    "logs api --follow",
    "st",
    "",
    "dance",
]
for command_text in sample_commands:
    print(f"{command_text!r:22} -> {run_deploy_command(command_text)}")
```

```text
'deploy staging'       -> deploying to staging
'deploy moon'          -> error: unknown environment 'moon'
'rollback v2.0.1'      -> rolling back to v2.0.1
'rollback 2'           -> error: version must look like v1.2.3
'logs api --follow'    -> showing logs for api (follow=True)
'st'                   -> showing status
''                     -> error: empty command
'dance'                -> error: unknown command 'dance'
```

### Demo: a webhook router

A payment provider posts JSON events. Mapping patterns route them by their
`type`, nested patterns reach into the `data` object, class patterns such as
`int(amount)` check types, a guard checks a value, and `**rest` keeps the
unknown fields for a log line. Amounts are in paise (hundredths of a rupee),
so `2_500_000` is ₹25,000. Phase 6 builds a real FastAPI endpoint around this
idea.

```python
def route_webhook(event: dict[str, Any]) -> str:
    """Route a payment-provider webhook event to a handler description."""
    match event:
        case {
            "type": "payment.captured",
            "data": {"amount": int(amount), "currency": "INR"},
        }:
            return f"mark order paid: ₹{amount / 100:,.2f}"
        case {"type": "payment.failed", "data": {"reason": str(reason)}}:
            return f"notify customer: payment failed ({reason})"
        case {
            "type": "refund.created",
            "data": {"amount": int(amount)},
        } if amount > 1_000_000:
            return "refund over ₹10,000: needs manual approval"
        case {"type": "refund.created", "data": {"amount": int(amount)}}:
            return f"refund ₹{amount / 100:,.2f}"
        case {"type": str(event_type), **rest}:
            return f"ignored {event_type} (fields: {sorted(rest)})"
        case _:
            return "rejected: not a webhook event"


webhook_events = [
    {"type": "payment.captured", "data": {"amount": 49900, "currency": "INR"}},
    {"type": "payment.failed", "data": {"reason": "card declined"}},
    {"type": "refund.created", "data": {"amount": 2_500_000}},
    {"type": "refund.created", "data": {"amount": 19900}},
    {"type": "dispute.opened", "id": "evt_9", "data": {}},
    {"event": "payment.captured"},
]
for webhook_event in webhook_events:
    print(route_webhook(webhook_event))
```

```text
mark order paid: ₹499.00
notify customer: payment failed (card declined)
refund over ₹10,000: needs manual approval
refund ₹199.00
ignored dispute.opened (fields: ['data', 'id'])
rejected: not a webhook event
```

### Under the hood: `match` opcodes

`match` compiles to ordinary bytecode plus a few dedicated instructions:
`MATCH_SEQUENCE` (is the subject a non-string sequence?), `MATCH_MAPPING` (is
it a mapping?), `MATCH_KEYS` (look up several keys at once) and `MATCH_CLASS`
(the `isinstance` check plus attribute extraction). There is no jump table as
a C `switch` might use: the cases are tried in order, as a chain of tests and
conditional jumps. The next cell collects the `MATCH_*` opcodes from the two
demo functions above.

```python
match_opcodes = {
    instruction.opname
    for matcher in (run_deploy_command, route_webhook)
    for instruction in dis.get_instructions(matcher)
    if instruction.opname.startswith("MATCH_")
}
print(f"{sorted(match_opcodes)=}")
```

```text
sorted(match_opcodes)=['MATCH_CLASS', 'MATCH_KEYS', 'MATCH_MAPPING',
  'MATCH_SEQUENCE']
```

> **Note:** opcode names vary between Python versions. Because the cases are a
> linear chain, put the most common cases first in hot code.

### Key points

| Idea | Takeaway |
| --- | --- |
| First match wins | No fall-through, no `break` |
| No match | Nothing happens, no error |
| Sequence | Exact length; `*rest` is a list; not `str` |
| Mapping | Listed keys only; extras ignored |
| Class | `isinstance` + `__match_args__` |
| Guard | `case pattern if condition:` |
| Capture trap | Bare names capture; use dotted names |

## 1.8.5 Loops

Python has exactly two loops. `for` iterates over **any iterable**: a list,
tuple, string, dict, set, `range`, file, generator, or your own class. There is
no C-style `for (init; condition; step)`; for counting, you iterate over a
`range`. Under the hood, `for item in items:` calls `iter(items)` once to get
an iterator and then calls `next()` on it until it raises `StopIteration`
(Unit 1.13 covers the protocol). JavaScript's closest relative is
`for...of`; Python has nothing like `for...in` over property names, because
iterating a dict already gives its keys.

```python
for product_name in ["tea", "rice"]:
    print(f"list item: {product_name}")
for character in "OK":
    print(f"str character: {character}")
for sku, unit_price in {"TEA-500G": 249, "GHEE-1L": 640}.items():
    print(f"dict item: {sku} = {unit_price}")
for even_number in range(0, 7, 2):  # JS: for (let n = 0; n < 7; n += 2)
    print(f"range value: {even_number}")
print(f"{even_number=}  (the loop variable still exists after the loop)")
```

```text
list item: tea
list item: rice
str character: O
str character: K
dict item: TEA-500G = 249
dict item: GHEE-1L = 640
range value: 0
range value: 2
range value: 4
range value: 6
even_number=6  (the loop variable still exists after the loop)
```

> **Note:** a `for` loop does not create a new scope. The loop variable is an
> ordinary variable of the enclosing function (or module), so it keeps its
> last value after the loop, unlike a `let` in a JavaScript `for` header. If
> the iterable was empty, the variable is never assigned at all.

`while condition:` repeats as long as the condition is truthy. Use it when
the number of iterations is not known in advance.

```python
remaining_stock = 10
orders_served = 0
while remaining_stock >= 3:
    remaining_stock -= 3
    orders_served += 1
print(f"{orders_served=}, {remaining_stock=}")
```

```text
orders_served=3, remaining_stock=1
```

### `break` and `continue`

`break` leaves the innermost loop immediately; `continue` skips the rest of
the body and moves on to the next iteration. Both work as in JavaScript, but
Python has no labelled `break outer;`. To leave nested loops at once, move
them into a function and `return`, or use the loop `else` described next.

```python
log_lines = ["INFO start", "DEBUG cache warm", "ERROR db down", "INFO retry"]
for log_line in log_lines:
    if log_line.startswith("DEBUG"):
        continue  # skip noise
    if log_line.startswith("ERROR"):
        print(f"stopping at: {log_line}")
        break
    print(f"processing: {log_line}")
```

```text
processing: INFO start
stopping at: ERROR db down
```

### `for ... else`

A loop can have an `else` block. It runs when the loop finishes **without
`break`**: read it as "no break". The classic use is a search. Instead of
setting a `found = False` flag before the loop and testing it afterwards, you
`break` when you find the item and put the "not found" handling in `else`.
JavaScript has no equivalent.

```python
def find_first_error(lines: list[str]) -> str:
    """Return the first ERROR line, or a message if there is none."""
    for line in lines:
        if line.startswith("ERROR"):
            result = f"found: {line}"
            break
    else:  # no break: the loop ran to the end
        result = "no errors"
    return result


print(f"{find_first_error(log_lines)=}")
print(f"{find_first_error(['INFO ok'])=}")
print(f"{find_first_error([])=}  (empty loop: else still runs)")
```

```text
find_first_error(log_lines)='found: ERROR db down'
find_first_error(['INFO ok'])='no errors'
find_first_error([])='no errors'  (empty loop: else still runs)
```

> **Warning:** the loop `else` does **not** mean "the loop body never ran".
> It runs for an empty iterable *and* for a loop that ran to the end; only
> `break` (or `return` / an exception) skips it. A short comment such as
> `# no break` helps readers who have not met the construct.

### `while ... else`

`while` loops take an `else` too, with the same rule: it runs when the
condition becomes false, not when the loop is left with `break`. The example
retries a flaky connection a limited number of times.

```python
def connect_with_retries(responses: list[bool], max_attempts: int) -> str:
    """Try up to max_attempts times; responses[i] is attempt i's result."""
    attempt = 0
    while attempt < max_attempts:
        if responses[attempt]:
            outcome = f"connected on attempt {attempt + 1}"
            break
        attempt += 1
    else:
        outcome = f"gave up after {max_attempts} attempts"
    return outcome


print(f"{connect_with_retries([False, True, True], 3)=}")
print(f"{connect_with_retries([False, False, False], 3)=}")
```

```text
connect_with_retries([False, True, True], 3)='connected on attempt 2'
connect_with_retries([False, False, False], 3)='gave up after 3 attempts'
```

### Do-while emulation

Python has no `do { ... } while (condition)`. The idiom is `while True:` with
a conditional `break` at the **bottom** of the body, so the body always runs
at least once.

```python
pending_pages = ["page-3", "page-2", "page-1"]
fetched_pages = []
while True:
    fetched_pages.append(pending_pages.pop())  # the body runs at least once
    if not pending_pages:
        break
print(f"{fetched_pages=}")
```

```text
fetched_pages=['page-1', 'page-2', 'page-3']
```

### Key points

| Idea | Takeaway |
| --- | --- |
| `for` | Any iterable; count with `range` |
| Loop variable | Survives after the loop |
| `break` / `continue` | Innermost loop only; no labels |
| Loop `else` | Runs when there was no `break` |
| Do-while | `while True:` + `break` at the bottom |

## 1.8.6 Assignment forms

In Python, plain `=` is a **statement**, not an expression: `if (x = 5)` is a
syntax error, which rules out the classic `=` versus `==` typo. Assignment
never copies an object; it binds a name to an object (Unit 1.2). Python offers
five forms:

| Form | Example | Notes |
| --- | --- | --- |
| Simple | `total = 0` | Binds a name |
| Augmented | `total += price` | In place if mutable |
| Multiple targets | `low = high = 0` | All share one object |
| Unpacking | `name, price = row` | Counts must match |
| Walrus | `(found := search(line))` | An expression (PEP 572) |

### Augmented assignment

The augmented operators are `+=`, `-=`, `*=`, `/=`, `//=`, `%=`, `**=`, `&=`,
`|=`, `^=`, `<<=`, `>>=` and `@=`. `x += y` first tries the *in-place* method
`x.__iadd__(y)`; only if the type has none does it fall back to
`x = x + y`. Mutable types such as `list` implement `__iadd__`, so the list is
changed **in place** and every alias sees the change. Immutable types (`int`,
`str`, `tuple`) have no in-place method, so a new object is built and the name
is rebound. There is no `++` or `--`.

```python
running_total = 100
running_total += 49
running_total //= 2
print(f"{running_total=}")

cart = ["tea"]
cart_alias = cart
cart += ["rice"]  # list.__iadd__: extends the same list
print(f"{cart_alias=}, {cart is cart_alias=}")

point = (1, 2)
point_alias = point
point += (3,)  # tuples have no __iadd__: a new tuple is bound to point
print(f"{point_alias=}, {point is point_alias=}")
print(f"{compile_error('count = 0; count++')=}")
```

```text
running_total=74
cart_alias=['tea', 'rice'], cart is cart_alias=True
point_alias=(1, 2), point is point_alias=False
compile_error('count = 0; count++')='SyntaxError: invalid syntax'
```

> **Note:** `++count` is *not* a syntax error: it parses as `+(+count)`, two
> unary pluses, and leaves `count` unchanged. Only the postfix form `count++`
> fails to compile.

### Multiple targets

`a = b = value` evaluates `value` **once** and binds every target to that one
object. That is harmless for immutable values, because "changing" one name
really rebinds it. It is a trap for mutable values: both names share one list,
so appending through one is visible through the other (Lab 1.5, exercise 4).

```python
low_score = high_score = 0
high_score += 10  # rebinding high_score; low_score keeps 0
print(f"{low_score=}, {high_score=}")

pending_ids = done_ids = []
pending_ids.append(1001)  # one list, two names
print(f"{done_ids=}  (the trap)")
```

```text
low_score=0, high_score=10
done_ids=[1001]  (the trap)
```

### Unpacking assignment

With several comma-separated targets on the left, Python iterates over the
right-hand side, which can be **any iterable**, and assigns item by item. The
counts must match, or Python raises `ValueError`. Because the right side is
evaluated completely (into a tuple) before any target is assigned, swapping
two variables needs no temporary. Targets can nest to unpack nested data.
This is JavaScript's array destructuring, minus the silent `undefined` for
missing items.

```python
sku, unit_price = ("TEA-500G", 249)
print(f"{sku=}, {unit_price=}")
first_slot, second_slot = "morning", "evening"
# swap: the right side is a tuple
first_slot, second_slot = second_slot, first_slot
print(f"{first_slot=}, {second_slot=}")
store_name, (latitude, longitude) = ("Indiranagar", (12.97, 77.64))
print(f"{store_name=}, {latitude=}, {longitude=}")
print(f"too many values: {raised_error_name(lambda: exec('a, b = 1, 2, 3'))}")
```

```text
sku='TEA-500G', unit_price=249
first_slot='evening', second_slot='morning'
store_name='Indiranagar', latitude=12.97, longitude=77.64
too many values: ValueError
```

### The walrus operator `:=`

The walrus operator (PEP 572, Python 3.8), officially the *assignment
expression*, assigns a value to a name **and** returns that value, so the
assignment can live inside a larger expression. It exists to avoid computing
something twice, or splitting "compute, then test" into two statements. The
typical places are `while` conditions, an `if` that tests a regex match, and
comprehension filters that would otherwise call a function twice.

```python
order_line_pattern = re.compile(r"(?P<sku>[A-Z]+-\w+) x(?P<quantity>\d+)")
raw_line = "order 1001: TEA-500G x2"
if (line_match := order_line_pattern.search(raw_line)) is not None:
    print(f"{line_match['sku']=}, {int(line_match['quantity'])=}")

pending_jobs = ["resize", "upload", "notify"]
while (
    current_job := pending_jobs.pop(0) if pending_jobs else None
) is not None:
    print(f"running {current_job}")

prices = [120, 499, 999, 1500]
with_gst = [
    taxed for price in prices if (taxed := round(price * 1.18)) > 600
]
print(f"{with_gst=}")
```

```text
line_match['sku']='TEA-500G', int(line_match['quantity'])=2
running resize
running upload
running notify
with_gst=[1179, 1770]
```

`:=` has the lowest precedence of all, so it nearly always needs parentheses.
In the `if`, the parentheses make `line_match` hold the match object rather
than the result of the `is not None` test.

**Walrus scope rules:**

- In a comprehension, `:=` binds the name in the **enclosing** scope. That is
  deliberate: it lets you keep the last value, or a "witness" that made
  `any()` true. The comprehension's own loop variable still does not leak
  (Unit 1.9).
- It cannot rebind a comprehension's iteration variable.
- An unparenthesized `:=` is not allowed as a top-level statement (use `=`),
  and it can only assign to a plain name, never to an attribute or subscript
  (`cart.total := 5` is illegal).

```python
order_amounts = [250, 900, 1200]
has_large = any(
    (large_amount := candidate) > 1000 for candidate in order_amounts
)
print(f"{has_large=}, {large_amount=}  (the witness leaked out on purpose)")
print(f"'candidate' defined outside: {'candidate' in dir()}")

print(f"{compile_error('total := 5')=}")
print(f"{compile_error('[i := 0 for i in range(3)]')=}")
print(f"{compile_error('cart.total := 5')=}")
print(
    f"{compile_error('(total := 5)')=}  "
    "(parenthesized is legal, but use = instead)"
)
```

```text
has_large=True, large_amount=1200  (the witness leaked out on purpose)
'candidate' defined outside: False
compile_error('total := 5')='SyntaxError: invalid syntax'
compile_error('[i := 0 for i in range(3)]')="SyntaxError: assignment
  expression cannot rebind comprehension iteration variable 'i'"
compile_error('cart.total := 5')='SyntaxError: cannot use assignment
  expressions with attribute'
compile_error('(total := 5)')='compiles'  (parenthesized is legal, but use =
  instead)
```

> **Note:** the output above is from running this snippet on its own. In the
> course notebook the same line prints `True`, only because an earlier cell
> had already defined a top-level `candidate`. A comprehension's (or
> generator expression's) loop variable is local to it; only the walrus
> target `large_amount` is written outward.

### Key points

| Idea | Takeaway |
| --- | --- |
| `=` | A statement; binds, never copies |
| `+=` | In place for lists; rebinds ints, str, tuples |
| No `++` | Write `count += 1` |
| `a = b = []` | One shared list |
| Unpacking | Any iterable; counts must match |
| `:=` | Assigns inside an expression |
| Walrus scope | Leaks out of comprehensions on purpose |

## 1.8.7 Unpacking operators

`*` unpacks any iterable into separate positional items, and `**` unpacks a
mapping into separate `key=value` pairs. Together they are Python's version
of JavaScript's `...` (spread and rest), split into two operators because
Python distinguishes positional and keyword arguments. They work in three
places:

| Place | `*` | `**` |
| --- | --- | --- |
| Calls | `f(*args)` | `f(**options)` |
| Literals | `[*a, *b]`, `{*a, *b}` | `{**defaults, **overrides}` |
| Assignment targets | `first, *rest = items` | — |

### In calls

`f(*sequence)` passes each item as a separate positional argument;
`f(**mapping)` passes each pair as a keyword argument. They can be mixed with
ordinary arguments and with each other. (Their mirror images in a function
*definition*, `*args` and `**kwargs`, which collect arguments, are covered in
Unit 1.10.)

```python
def format_address(
    street: str, city: str, pin_code: str, country: str = "IN"
) -> str:
    """Join address parts into one line."""
    return f"{street}, {city} {pin_code}, {country}"


address_parts = ["12 MG Road", "Bengaluru", "560001"]
address_options = {"country": "India"}
print(format_address(*address_parts))
print(format_address(*address_parts, **address_options))
print(*["tea", "rice", "ghee"], sep=" | ")
```

```text
12 MG Road, Bengaluru 560001, IN
12 MG Road, Bengaluru 560001, India
tea | rice | ghee
```

### In list, tuple, set and dict literals

Starred items inside a display build a **new** container from several
sources (PEP 448): JavaScript's `[...a, ...b]` and `{...a, ...b}`. Any
iterable can be starred into a list, tuple or set, and any mapping can be
double-starred into a dict. In dicts, later keys win, so "defaults first,
overrides last" is the standard way to merge settings (`defaults | overrides`
does the same for two dicts, Unit 1.6).

```python
breakfast_items, lunch_items = ["idli", "dosa"], ("thali", "dosa")
all_items = [*breakfast_items, *lunch_items, "chai"]
unique_items = {*breakfast_items, *lunch_items}
print(f"{all_items=}")
print(f"{sorted(unique_items)=}, {(*breakfast_items, 'vada')=}")

default_options = {"timeout": 10, "retries": 3}
request_options = {**default_options, "timeout": 30, "verbose": True}
print(f"{request_options=}")
```

```text
all_items=['idli', 'dosa', 'thali', 'dosa', 'chai']
sorted(unique_items)=['dosa', 'idli', 'thali'], (*breakfast_items,
  'vada')=('idli', 'dosa', 'vada')
request_options={'timeout': 30, 'retries': 3, 'verbose': True}
```

> **Note:** like JavaScript's spread, `*` and `**` copy only the top level.
> Nested lists and dicts are shared with the source (Unit 1.7).

### In assignment targets

On the left of `=`, one starred name collects "everything else" into a
**list** (PEP 3132), even when the source is a tuple or a string. Unlike
JavaScript's rest element, it can sit at the start, in the middle or at the
end. It may collect nothing, giving an empty list. At most one starred target
is allowed per level, because two would make the split ambiguous.

```python
first_step, *middle_steps, last_step = (
    "cart", "address", "payment", "confirm"
)
print(f"{first_step=}, {middle_steps=}, {last_step=}")
head_char, *tail_chars = "UPI"
print(f"{head_char=}, {tail_chars=}")
*_, latest_version = ["v1.0.0", "v1.1.0", "v2.0.0"]
print(f"{latest_version=}")
only_item, *nothing_else = ["solo"]
print(f"{nothing_else=}  (an empty list, not an error)")
print(f"{compile_error('*first, *second = [1, 2, 3]')=}")
```

```text
first_step='cart', middle_steps=['address', 'payment'], last_step='confirm'
head_char='U', tail_chars=['P', 'I']
latest_version='v2.0.0'
nothing_else=[]  (an empty list, not an error)
compile_error('*first, *second = [1, 2, 3]')='SyntaxError: multiple starred
  expressions in assignment'
```

### Unpacking in comprehensions (*New in 3.15*)

Python 3.15 (PEP 798) allows `*` and `**` directly in comprehensions:
`[*batch for batch in batches]` flattens one level, and
`{**layer for layer in layers}` merges a list of dicts, later ones winning. On
older versions these are a `SyntaxError`, so the example compiles them from
strings behind a version check and also shows the classic nested-loop
spelling.

```python
order_batches = [["TEA-500G", "RICE-5KG"], ["GHEE-1L"], []]
config_layers = [{"timeout": 10}, {"timeout": 30, "debug": True}]
if sys.version_info >= (3, 15):
    flat_skus = eval("[*batch for batch in order_batches]")
    merged_config = eval("{**layer for layer in config_layers}")
    print(f"{flat_skus=}")
    print(f"{merged_config=}")
else:
    print("unpacking in comprehensions needs Python 3.15; skipped")
flat_skus_classic = [sku for batch in order_batches for sku in batch]
print(f"{flat_skus_classic=}  (the pre-3.15 spelling)")
```

```text
flat_skus=['TEA-500G', 'RICE-5KG', 'GHEE-1L']
merged_config={'timeout': 30, 'debug': True}
flat_skus_classic=['TEA-500G', 'RICE-5KG', 'GHEE-1L']  (the pre-3.15
  spelling)
```

### Key points

| Idea | Takeaway |
| --- | --- |
| `*` in calls | Iterable → positional arguments |
| `**` in calls | Mapping → keyword arguments |
| In literals | Build new containers; later dict keys win |
| Starred target | Collects the rest into a list |
| One star | At most one starred target per level |
| 3.15 | `[*x for x in xs]` flattens |

## Lab 1.8

Three exercises that use this unit's control-flow tools. Write each function,
then test it against the cases listed. The reference solutions follow each
exercise, hidden until you open them.

### Exercise 1 — `parse_command(command_text)` with `match`

Parse a shopping-cart command line into a tuple. Split the text on whitespace
and use **one** `match` statement on the resulting list of words.

| Input | Result |
| --- | --- |
| `"add SKU"` | `("add", "SKU", 1)` |
| `"add SKU QTY"`, QTY digits > 0 | `("add", "SKU", QTY)` as int |
| `"add SKU QTY"`, anything else | `("error", "quantity must …")` |
| `"remove SKU"` | `("remove", "SKU")` |
| `"list"` or `"ls"` | `("list",)` |
| `"checkout"` | `("checkout",)` |
| `"quit"` or `"exit"` | `("quit",)` |
| blank line | `("error", "empty command")` |
| anything else | `("error", "unknown command: <word>")` |

The full message for a bad quantity is
`"quantity must be a positive integer"`, and `<word>` is the first word of the
command. Commands are case-sensitive; SKUs are returned as typed.

The checks include: `"add TEA-500G"`, `"add RICE-5KG 3"`, extra spaces
(`"  add   GHEE-1L   2 "`), a non-numeric quantity (`"add TEA-500G two"`), a
zero quantity, `"remove TEA-500G"`, both aliases of `list` and `quit`, a
blank line (`"   "`), `"dance now"`, and `"remove"` without a SKU (which must
report `unknown command: remove`).

**Hints**

- `str.split()` with no argument splits on runs of whitespace and drops
  leading and trailing spaces, so `"   ".split()` is `[]`.
- Use a guard to accept the quantity: `str.isdigit()` and `int(...) > 0`.
  Then add a less specific `["add", _, _]` case below it for the error.
- Use or-patterns for aliases, and `[unknown_command, *_]` as the last case.

<details><summary>Solution</summary>

```python
def parse_command(command_text: str) -> tuple[Any, ...]:
    """Parse a cart command into a tuple, using match."""
    match command_text.split():
        case ["add", sku]:
            return ("add", sku, 1)
        case ["add", sku, quantity_text] if (
            quantity_text.isdigit() and int(quantity_text) > 0
        ):
            return ("add", sku, int(quantity_text))
        case ["add", _, _]:
            return ("error", "quantity must be a positive integer")
        case ["remove", sku]:
            return ("remove", sku)
        case ["list" | "ls"]:
            return ("list",)
        case ["checkout"]:
            return ("checkout",)
        case ["quit" | "exit"]:
            return ("quit",)
        case []:
            return ("error", "empty command")
        case [unknown_command, *_]:
            return ("error", f"unknown command: {unknown_command}")
```

Case order does the validation work. The guarded `add` case accepts only a
positive integer quantity; anything else with three words falls through to
`["add", _, _]`. `["remove"]` matches no `remove` case (that needs two words),
so it reaches the final catch-all and reports `unknown command: remove`, as
the checks require.

```text
PASS  add default quantity
PASS  add with quantity
PASS  extra spaces
PASS  bad quantity
PASS  zero quantity
PASS  remove
PASS  list
PASS  ls alias
PASS  checkout
PASS  quit
PASS  exit alias
PASS  blank
PASS  unknown
PASS  remove without sku
14/14 checks passed
```

</details>

### Exercise 2 — `fizzbuzz(number)` with `match`

Return `"FizzBuzz"` for multiples of 15, `"Fizz"` for multiples of 3,
`"Buzz"` for multiples of 5, and otherwise the number as a string. Match on
the **tuple** `(number % 3, number % 5)`: one `case` per outcome, no `if`.

The checks: `1` → `"1"`, `3` → `"Fizz"`, `5` → `"Buzz"`, `15` →
`"FizzBuzz"`, `0` → `"FizzBuzz"` (zero is a multiple of 15), and the numbers
1 to 15 joined with spaces give
`"1 2 Fizz 4 Buzz Fizz 7 8 Fizz Buzz 11 Fizz 13 14 FizzBuzz"`.

**Hints**

- A remainder of `0` means "divisible". Use the literal `0` for "must be
  divisible" and `_` for "don't care".
- Order the cases from most to least specific: `(0, 0)` first.

<details><summary>Solution</summary>

```python
def fizzbuzz(number: int) -> str:
    """Return the FizzBuzz word for number.

    Uses match on a tuple of remainders.
    """
    match (number % 3, number % 5):
        case (0, 0):
            return "FizzBuzz"
        case (0, _):
            return "Fizz"
        case (_, 0):
            return "Buzz"
        case _:
            return str(number)
```

The tuple turns two independent questions into one subject, and the four
cases read like a truth table. `(0, _)` only runs when `(0, 0)` did not, so it
means "divisible by 3 but not by 5".

```text
PASS  1
PASS  3
PASS  5
PASS  15
PASS  0 is a multiple of 15
PASS  1 to 15
6/6 checks passed
```

</details>

### Exercise 3 — `find_first_duplicate(items)` with `for ... else`

Return the first item that appears **for the second time** while scanning
left to right. For `[3, 1, 4, 1, 3]` the answer is `1`, found at index 3,
before the second `3`. Return `None` if every item is unique. Items are
hashable, and any iterable must work, including a generator that can only be
read once.

| Input | Expected |
| --- | --- |
| `[3, 1, 4, 1, 3]` | `1` |
| `["a", "a"]` | `"a"` |
| `[1, 2, 3]` | `None` |
| `[]` | `None` |
| `"python"` | `None` |
| `(n % 4 for n in range(10))` | `0` |
| `[1, True]` | `True` |

**Hints**

- Keep a `set` of items already seen; membership tests on a set are O(1).
- `break` as soon as you meet an item that is already in the set.
- Put the "no duplicate" result in the loop's `else`, which runs only when
  the loop ended without `break`.

<details><summary>Solution</summary>

```python
def find_first_duplicate(items: Iterable[Hashable]) -> Hashable | None:
    """Return the first item seen twice, or None, using for ... else."""
    seen_items: set[Hashable] = set()
    for item in items:
        if item in seen_items:
            duplicate = item
            break
        seen_items.add(item)
    else:
        duplicate = None
    return duplicate
```

The single pass works on any iterable, generators included. The last case is
a reminder from Unit 1.3: `True == 1` and `hash(True) == hash(1)`, so `True`
counts as a repeat of `1`. The function returns the item seen at the moment
of the repeat, which is `True`.

```text
PASS  second occurrence wins
PASS  adjacent
PASS  no duplicate
PASS  empty
PASS  string iterable
PASS  generator
PASS  1 and True are equal
7/7 checks passed
```

</details>

## Recap

| Concept | Takeaway | JavaScript equivalent |
| --- | --- | --- |
| `/`, `//`, `%` | Float division; floor; divisor's sign | `/`, `Math.floor`, `%` |
| `==` / `is` | Value equality, no coercion / same object | `===` / — |
| Bitwise | Unlimited ints; tighter than `==` | 32-bit; looser than `==` |
| `in` | `__contains__`: values, substrings, keys | `includes`, `in` (keys) |
| Precedence | `**` highest, then unary, … `or` lowest | Similar, not identical |
| Chained comparisons | `0 < age <= 120`; middle once | `0 < age && age <= 120` |
| `and` / `or` | Short-circuit, return an operand | `&&` / `\|\|` |
| `value or default` | Replaces `0` and `""` too | `\|\|` (same trap) |
| No `??` | `x if x is not None else default` | `x ?? default` |
| Conditional expression | `a if condition else b` | `condition ? a : b` |
| Guard clauses | Special cases first, return early | Same |
| `match` | Structural patterns, first match wins | `switch` (`===`, falls through) |
| Capture trap | Bare names capture; use dotted names | — |
| `for` | Any iterable; count with `range` | `for...of` |
| Loop `else` | Runs when there was no `break` | No equivalent |
| Do-while | `while True:` + `break` at the bottom | `do { } while ()` |
| Augmented assignment | In place if mutable; no `++` | `+=`, `++` |
| Walrus `:=` | Assignment expression | `=` is an expression |
| `*` / `**` | Unpack in calls, literals, targets | `...` spread / rest |

## Further reading

- [Expressions: operator precedence](https://docs.python.org/3/reference/expressions.html#operator-precedence)
- [Expressions: comparisons](https://docs.python.org/3/reference/expressions.html#comparisons)
- [Expressions: boolean operations](https://docs.python.org/3/reference/expressions.html#boolean-operations)
- [Compound statements: `if`, `while`, `for`, `match`](https://docs.python.org/3/reference/compound_stmts.html)
- [Tutorial: `match` statements](https://docs.python.org/3/tutorial/controlflow.html#match-statements)
- [Tutorial: `break`, `continue` and `else` on loops](https://docs.python.org/3/tutorial/controlflow.html#break-and-continue-statements-and-else-clauses-on-loops)
- [Simple statements: assignment](https://docs.python.org/3/reference/simple_stmts.html#assignment-statements)
- [Expressions: assignment expressions](https://docs.python.org/3/reference/expressions.html#assignment-expressions)
- [PEP 634 — Structural pattern matching: specification](https://peps.python.org/pep-0634/)
- [PEP 635 — Structural pattern matching: motivation and rationale](https://peps.python.org/pep-0635/)
- [PEP 636 — Structural pattern matching: tutorial](https://peps.python.org/pep-0636/)
- [PEP 572 — Assignment expressions](https://peps.python.org/pep-0572/)
- [PEP 448 — Additional unpacking generalizations](https://peps.python.org/pep-0448/)
- [PEP 3132 — Extended iterable unpacking](https://peps.python.org/pep-3132/)
- [PEP 798 — Unpacking in comprehensions](https://peps.python.org/pep-0798/)
- [PEP 505 — None-aware operators (deferred)](https://peps.python.org/pep-0505/)

[← Previous](unit-1-7-copying-shallow-copies-deep-copies-and-structured-clones.md) · [Index](README.md) · [Next →](unit-1-9-iteration-comprehensions-and-built-in-functions.md)
