# Unit 1.3 — Numeric and Boolean Data Types

[← Previous](unit-1-2-objects-names-and-mutability.md) · [Index](README.md) · [Next →](unit-1-4-text-and-binary-data-types.md)

JavaScript gives you one numeric type, `number`, plus `BigInt` when you need more.
Python gives you several, each with a clear job: `int` for exact whole numbers of any
size, `float` for fast approximate measurements, `Decimal` for money, `Fraction` for
exact ratios and `complex` for engineering maths. This unit also covers `bool`,
`None` and the truthiness rules, which look familiar but differ from JavaScript in
ways that cause real bugs.

## What you will learn

- How to use `int`, `float`, `Decimal`, `Fraction` and `complex`, and how to choose
  the right one for money, measurements and exact ratios.
- How to predict `//`, `%` and `round()` results, including negative numbers and
  exact halves.
- Why `bool` is a kind of `int`, what `None` is, and exactly which values are falsy.
- How CPython stores each numeric type in memory, and what that costs.
- How to convert between types explicitly, and which conversions raise.

## JavaScript → Python bridge

Most of your JavaScript intuition about numbers carries over, because a Python
`float` *is* a JavaScript `number`. The rows below are the places where it does not.

| JavaScript | Python | The difference that bites |
| --- | --- | --- |
| `number` (one type) | `int` and `float` | `7 / 2` is `3.5`, `7 // 2` is `3` |
| `BigInt` (`10n`) | `int` | Every `int` is a big int, no suffix |
| `-7 % 2 === -1` | `-7 % 2 == 1` | `%` takes the divisor's sign |
| `Math.round(2.5) === 3` | `round(2.5) == 2` | Ties round to the even neighbour |
| `1 / 0 === Infinity` | `ZeroDivisionError` | Division by zero is an error |
| `null`, `undefined` | `None` only | Missing dict keys raise `KeyError` |
| `[]`, `{}` are truthy | `[]`, `{}` are falsy | Empty containers are false |
| `1 + "1" === "11"` | `TypeError` | No implicit coercion |

The examples in this unit share one setup block. It imports the modules used
throughout and defines `show_size`, the helper from Unit 1.2 that prints an object's
size, type and identity. `PAISE` is the `Decimal` step used for rupee amounts
(one paisa is one hundredth of a rupee).

```python
import cmath
import math
import sys
import timeit
from collections.abc import Callable
from decimal import (
    ROUND_HALF_EVEN,
    ROUND_HALF_UP,
    Decimal,
    getcontext,
    localcontext,
)
from fractions import Fraction


def show_size(label: str, obj: object) -> None:
    """Print the shallow size in bytes, the type and the id of an object."""
    print(
        f"{label}: {sys.getsizeof(obj)} bytes, "
        f"type={type(obj).__name__}, id={id(obj)}"
    )


PAISE = Decimal("0.01")  # quantize() target for rupee amounts
print(f"{sys.version_info[:2]=}, {getcontext().prec=}")
```

```text
sys.version_info[:2]=(3, 15), getcontext().prec=28
```

> **Note:** the examples were run on Python 3.15. Most of them work on any modern
> Python 3; features that need a recent version are labelled where they appear.

## 1.3.0 Python's built-in data types at a glance

Before looking at numbers in detail, it helps to see the whole family of built-in
types that Units 1.3 to 1.7 teach. Three properties matter for every type:

- **Mutable**: can the object change after it is created? A mutable object can be
  changed in place; an immutable one can only be replaced by a new object (Unit 1.2).
- **Ordered**: do the items keep a position, so that indexing and iteration order
  mean something?
- **Hashable**: does `hash(obj)` work? Only hashable objects can be dict keys or set
  members (1.6.2). In practice, immutable objects are hashable and mutable ones are
  not, with a few "it depends" cases.

The overview is split into two tables so that each fits a phone screen. The first
table shows the three properties.

| Type | Mutable | Ordered | Hashable |
| --- | --- | --- | --- |
| `int` | No | — | Yes |
| `float` | No | — | Yes |
| `complex` | No | — | Yes |
| `Decimal`, `Fraction` | No | — | Yes |
| `bool` | No | — | Yes |
| `NoneType` | No | — | Yes |
| `str` | No | Yes | Yes |
| `bytes` | No | Yes | Yes |
| `bytearray` | Yes | Yes | No |
| `memoryview` | Depends on buffer | Yes | Read-only only |
| `list` | Yes | Yes | No |
| `tuple` | No | Yes | If all items are |
| `range` | No | Yes | Yes |
| `dict` | Yes | Insertion order | No |
| `frozendict` (3.15) | No | Insertion order | If all values are |
| `set` | Yes | No | No |
| `frozenset` | No | No | Yes |

The second table shows the category, how you write a value, and where the type is
taught.

| Type | Category | Literal / constructor | Section |
| --- | --- | --- | --- |
| `int` | Numeric | `42`, `0xff`, `1_000` | 1.3.1 |
| `float` | Numeric | `3.14`, `1e-3` | 1.3.2 |
| `complex` | Numeric | `3 + 4j` | 1.3.5 |
| `Decimal` | Numeric (stdlib) | `Decimal("0.1")` | 1.3.3 |
| `Fraction` | Numeric (stdlib) | `Fraction(1, 3)` | 1.3.4 |
| `bool` | Boolean | `True`, `False` | 1.3.6 |
| `NoneType` | Null | `None` | 1.3.7 |
| `str` | Text | `"hi"`, `f"{name}"` | 1.4 |
| `bytes` | Binary | `b"hi"` | 1.4.5 |
| `bytearray` | Binary | `bytearray(b"hi")` | 1.4.5 |
| `memoryview` | Binary | `memoryview(data)` | 1.4.6 |
| `list` | Sequence | `[1, 2]` | 1.5 |
| `tuple` | Sequence | `(1, 2)`, `(1,)` | 1.5.5 |
| `range` | Sequence | `range(10)` | 1.5.7 |
| `dict` | Mapping | `{"a": 1}` | 1.6 |
| `frozendict` | Mapping | `frozendict(a=1)` | 1.6.5 |
| `set` | Set | `{1, 2}`, `set()` | 1.6.6 |
| `frozenset` | Set | `frozenset({1, 2})` | 1.6.6 |

The *Hashable* column is easy to verify: call `hash()` on one sample of each type and
see whether it raises. The cell below includes the "it depends" cases: a tuple of
ints is hashable but a tuple holding a list is not, because a tuple's hash is built
from the hashes of its items. A `memoryview` over read-only `bytes` is hashable, but
one over a writable `bytearray` is not, and it is the one type that refuses with
`ValueError` instead of `TypeError`. `frozendict` is new in Python 3.15, so its rows
are added only when the interpreter is new enough.

```python
hashability_samples: list[tuple[str, object]] = [
    ("int", 42),
    ("float", 3.14),
    ("complex", 3 + 4j),
    ("Decimal", Decimal("0.1")),
    ("Fraction", Fraction(1, 3)),
    ("bool", True),
    ("NoneType", None),
    ("str", "hi"),
    ("bytes", b"hi"),
    ("bytearray", bytearray(b"hi")),
    ("memoryview (read-only)", memoryview(b"hi")),
    ("memoryview (writable)", memoryview(bytearray(b"hi"))),
    ("list", [1, 2]),
    ("tuple of ints", (1, 2)),
    ("tuple holding a list", (1, [2])),
    ("range", range(10)),
    ("dict", {"a": 1}),
    ("set", {1, 2}),
    ("frozenset", frozenset({1, 2})),
]
if sys.version_info >= (3, 15):
    hashability_samples += [
        ("frozendict of ints", frozendict(a=1)),
        ("frozendict holding a list", frozendict(a=[1])),
    ]
else:
    print("Skipped frozendict rows: new in 3.15")

for label, sample in hashability_samples:
    try:
        hash(sample)
        verdict = "hashable"
    # a writable memoryview raises ValueError, the rest raise TypeError
    except (TypeError, ValueError) as error:
        verdict = f"unhashable ({type(error).__name__})"
    print(f"{label:<26} {verdict}")
```

```text
int                        hashable
float                      hashable
complex                    hashable
Decimal                    hashable
Fraction                   hashable
bool                       hashable
NoneType                   hashable
str                        hashable
bytes                      hashable
bytearray                  unhashable (TypeError)
memoryview (read-only)     hashable
memoryview (writable)      unhashable (ValueError)
list                       unhashable (TypeError)
tuple of ints              hashable
tuple holding a list       unhashable (TypeError)
range                      hashable
dict                       unhashable (TypeError)
set                        unhashable (TypeError)
frozenset                  hashable
frozendict of ints         hashable
frozendict holding a list  unhashable (TypeError)
```

> **Note:** in JavaScript any value can be a `Map` key, because `Map` compares keys
> by identity. Python dicts and sets compare keys by *value*, which is only safe if
> the value can never change. That is why the mutable types are unhashable.

### Key points

| Idea | Takeaway |
| --- | --- |
| Mutable | Can change in place; immutable objects are replaced |
| Hashable | `hash()` works; needed for dict keys and set members |
| Rule of thumb | Immutable is hashable, mutable is not |
| Containers | `tuple`, `frozendict` are hashable only if their contents are |

## 1.3.1 Integers (`int`)

### Arbitrary precision

A Python `int` has **arbitrary precision**: it grows to hold any value you compute,
so it never overflows and never silently loses digits. There is no separate BigInt
type, no `n` suffix and no rule against mixing big and small integers, because every
`int` is already a big integer. Python 2 had two types (`int` and `long`) and
switched between them automatically; PEP 237 merged them, and Python 3 has only the
unbounded one.

JavaScript's `number` is a 64-bit float, so it holds integers exactly only up to
`Number.MAX_SAFE_INTEGER` (`2**53 - 1`). Above that, consecutive integers collapse
onto the same float. Python's `int` keeps every digit; only converting to `float`
brings the JavaScript limit back.

```python
js_max_safe_integer = 2**53 - 1
print(f"{js_max_safe_integer + 2=}")
print("  (exact; a JS number would print ...992)")
print(f"{2**100=}")
print(f"{math.factorial(30)=}")
print(f"{float(2**53 + 1) == 2**53=}")
print("  (float, like a JS number, cannot hold 2**53 + 1)")
```

```text
js_max_safe_integer + 2=9007199254740993
  (exact; a JS number would print ...992)
2**100=1267650600228229401496703205376
math.factorial(30)=265252859812191058636308480000000
float(2**53 + 1) == 2**53=True
  (float, like a JS number, cannot hold 2**53 + 1)
```

### Under the hood: 30-bit digits

CPython stores an `int` as a C structure (`PyLongObject`) with a fixed header
followed by a variable-length array of **digits**. Each digit is a 32-bit C integer
that holds 30 bits of the number's magnitude; the sign and the number of digits
are kept in the header. The value is the sum of `digit[i] * 2**(30 * i)`, just as a
decimal number is the sum of its digits times powers of ten, only in base `2**30`.

```text
PyLongObject for 2**60 (three 30-bit digits)

+-----------+-----------+-------------+---------+---------+---------+
| refcount  | type ptr  | tag: sign + | digit 0 | digit 1 | digit 2 |
| (8 bytes) | (8 bytes) | ndigits (8) |    0    |    0    |    1    |
+-----------+-----------+-------------+---------+---------+---------+
 <------------ 24-byte header -------->  4 bytes each

value = 0 * 2**0 + 0 * 2**30 + 1 * 2**60
```

Why 30 bits and not 32? Multiplying two 30-bit digits gives at most 60 bits, which
fits comfortably in a 64-bit machine word with room for carries, so the arithmetic
loops in C never overflow. The consequence you can measure is that an `int` grows by
4 bytes for every 30 bits of magnitude. `sys.int_info` reports the digit size, and
`sys.getsizeof` shows the growth.

```python
print(f"{sys.int_info.bits_per_digit=}")
print(f"{sys.int_info.sizeof_digit=}")
print(f"{sys.int_info.default_max_str_digits=}")
print(f"{'value':>14} {'bits':>5} {'bytes':>6}")
for label, number in [
    ("0", 0),
    ("1", 1),
    ("2**30 - 1", 2**30 - 1),
    ("2**30", 2**30),
    ("2**60", 2**60),
    ("2**90", 2**90),
    ("10**100", 10**100),
    ("10**1000", 10**1000),
]:
    print(f"{label:>14} {number.bit_length():>5} {sys.getsizeof(number):>6}")
```

```text
sys.int_info.bits_per_digit=30
sys.int_info.sizeof_digit=4
sys.int_info.default_max_str_digits=4300
         value  bits  bytes
             0     0     28
             1     1     28
     2**30 - 1    30     28
         2**30    31     32
         2**60    61     36
         2**90    91     40
       10**100   333     72
      10**1000  3322    468
```

Even `0` costs 28 bytes: a 24-byte header plus one digit. The jump from 28 to 32
bytes happens exactly when the value needs a 31st bit, that is, a second digit.

> **Note:** big-integer arithmetic is not free. Adding two small ints is a handful of
> machine instructions plus the object overhead, but multiplying two numbers with
> thousands of digits takes real time. CPython also keeps the integers from -5 to 256
> pre-built (the small-int cache from Unit 1.2), so the most common values are never
> allocated at all.

### Literals

An integer literal can be written in four bases: decimal, binary (`0b`), octal
(`0o`) and hexadecimal (`0x`). Underscores may separate groups of digits for
readability (PEP 515) and are ignored by the parser, much like JavaScript's
`1_000_000`. Unlike old JavaScript, a bare leading zero does **not** mean octal: it is
a syntax error, so `0755` can never be silently misread.

```python
population_of_india = 1_428_627_663
file_mode = 0o755
flag_byte = 0b1010_0001
brand_colour = 0xFF9933
print(f"{population_of_india=}, {file_mode=}")
print(f"{flag_byte=}, {brand_colour=}")
try:
    eval("0755")
except SyntaxError as error:
    message_start, message_end = error.msg.split("; ")
    print(f"{type(error).__name__}: {message_start};")
    print(f"  {message_end}")
```

```text
population_of_india=1428627663, file_mode=493
flag_byte=161, brand_colour=16750899
SyntaxError: leading zeros in decimal integer literals are not permitted;
  use an 0o prefix for octal integers
```

### Operators

The arithmetic operators look like JavaScript's, with two important differences:
`/` and `//` are separate operators, and `%` follows a different sign rule.

| Operator | Meaning | `17 op 5` |
| --- | --- | --- |
| `+ - *` | add, subtract, multiply | `22`, `12`, `85` |
| `/` | true division, always `float` | `3.4` |
| `//` | floor division, rounds down | `3` |
| `%` | modulo, divisor's sign | `2` |
| `**` | power | `1419857` |

`/` is **true division** and always returns a `float`, even when the result is a
whole number: `10 / 2` is `5.0`, not `5`. When you want an integer result, use `//`,
**floor division**. "Floor" means *down*, towards negative infinity, not *towards
zero*. For positive numbers there is no difference, but `-7 // 2` is `-4`, whereas
JavaScript's `Math.trunc(-7 / 2)` gives `-3`.

Python keeps one identity true for every pair of integers:

```text
(a // b) * b + a % b == a
```

Since `-7 // 2` is `-4`, the identity forces `-7 % 2` to be `1`, because
`(-4) * 2 + 1 == -7`. The practical rule is that the result of `%` takes the sign of
the **divisor**. JavaScript's `%` is a *remainder* operator that keeps the sign of
the dividend, so `-7 % 2 === -1`. Python's rule is the useful one for wrapping
indexes and clock arithmetic: `index % length` is always a valid non-negative index
when `length` is positive. If you need the JavaScript behaviour, `math.fmod` provides
it.

```python
print(f"{17 + 5=}, {17 - 5=}, {17 * 5=}, {17 ** 5=}")
print(f"{17 / 5=}, {10 / 2=}  (always float)")
print(f"{17 // 5=}, {17 % 5=}")
print(f"{-7 // 2=}, {-7 % 2=}  (JS: Math.trunc gives -3, % gives -1)")
print(f"{7 // -2=}, {7 % -2=}")
dividend, divisor = -7, 2
print(f"{(dividend // divisor) * divisor + dividend % divisor == dividend=}")
print(f"{math.fmod(-7, 2)=}  (JS-style remainder, when you need it)")
```

```text
17 + 5=22, 17 - 5=12, 17 * 5=85, 17 ** 5=1419857
17 / 5=3.4, 10 / 2=5.0  (always float)
17 // 5=3, 17 % 5=2
-7 // 2=-4, -7 % 2=1  (JS: Math.trunc gives -3, % gives -1)
7 // -2=-4, 7 % -2=-1
(dividend // divisor) * divisor + dividend % divisor == dividend=True
math.fmod(-7, 2)=-1.0  (JS-style remainder, when you need it)
```

> **Warning:** porting code from JavaScript, `x % n` gives different answers whenever
> `x` or `n` is negative, and `Math.floor(a / b)` becomes `a // b`, not `int(a / b)`.
> `int()` truncates towards zero, and `a / b` goes through a float, which loses
> precision for large integers.

### Functions and methods

Python has a small set of built-in functions and `int` methods for everyday integer
work. The reference tables below list every one, split into two groups; each is
then demonstrated in its own example.

**Arithmetic helpers**

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `abs(x)` | absolute value | `abs(-7)` | `7` |
| `divmod(a, b)` | `(a // b, a % b)` | `divmod(17, 5)` | `(3, 2)` |
| `pow(b, e, m)` | fast modular power | `pow(3, 4, 5)` | `1` |
| `round(x, n)` | round half to even | `round(1250, -2)` | `1200` |

**Bits, bytes and bases**

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `bit_length()` | bits needed, no sign | `(1000).bit_length()` | `10` |
| `bit_count()` | number of 1 bits | `(255).bit_count()` | `8` |
| `to_bytes()` | int to raw bytes | `(8080).to_bytes(2)` | `b'\x1f\x90'` |
| `int.from_bytes()` | raw bytes to int | `int.from_bytes(b"\x1f\x90")` | `8080` |
| `bin(x)` | base-2 text | `bin(10)` | `'0b1010'` |
| `oct(x)` | base-8 text | `oct(493)` | `'0o755'` |
| `hex(x)` | base-16 text | `hex(255)` | `'0xff'` |
| `int(text, base)` | parse base 2–36 | `int("ff", 16)` | `255` |
| `is_integer()` | always `True` for `int` | `(7).is_integer()` | `True` |

`abs` works on every numeric type, including `Decimal`, and returns the same type it
was given.

```python
account_balance_change = -2_500
print(f"{abs(account_balance_change)=}, {abs(-3.5)=}")
print(f"{abs(Decimal('-0.10'))=}")
```

```text
abs(account_balance_change)=2500, abs(-3.5)=3.5
abs(Decimal('-0.10'))=Decimal('0.10')
```

`divmod` returns the quotient and the remainder together as a tuple, which you can
unpack in one line. It is the natural tool for splitting a quantity into units, such
as minutes into hours and minutes. It follows the same floor rule as `//` and `%`.

```python
hours, minutes = divmod(135, 60)
print(f"{hours=}, {minutes=}")
print(f"{divmod(-7, 2)=}")
```

```text
hours=2, minutes=15
divmod(-7, 2)=(-4, 1)
```

`pow(base, exp)` is the same as `base ** exp`, but the three-argument form
`pow(base, exp, mod)` computes `base ** exp % mod` **without ever building the huge
intermediate number**. It squares and reduces modulo `mod` at every step, so even an
exponent of `10**18` finishes instantly. This is the core operation of RSA and many
other cryptographic algorithms. Since Python 3.8, an exponent of `-1` returns the
modular inverse: the number that multiplies with `base` to give 1 modulo `mod`.

```python
print(f"{pow(2, 10)=}")
print(f"{pow(7, 10**18, 13)=}  (instant; 7 ** 10**18 would never finish)")
print(f"{pow(3, -1, 11)=}  (3 * 4 % 11 == 1)")
```

```text
pow(2, 10)=1024
pow(7, 10**18, 13)=9  (instant; 7 ** 10**18 would never finish)
pow(3, -1, 11)=4  (3 * 4 % 11 == 1)
```

`round(number, ndigits)` with a **negative** `ndigits` rounds an integer to tens,
hundreds and so on. An exact tie goes to the **even** neighbour (banker's rounding,
explained in 1.3.2), so `1250` rounds down to `1200` while `1350` rounds up to
`1400`. With no `ndigits` at all, `round()` always returns an `int`, even for a float
argument.

```python
print(f"{round(1_234, -2)=}, {round(1_250, -2)=}, {round(1_350, -2)=}")
print(f"{round(7)=}, {type(round(7.6)).__name__=}")
print("  (round() with no ndigits returns int)")
```

```text
round(1_234, -2)=1200, round(1_250, -2)=1200, round(1_350, -2)=1400
round(7)=7, type(round(7.6)).__name__='int'
  (round() with no ndigits returns int)
```

`bit_length()` is the number of bits needed to write the magnitude in binary,
ignoring the sign, so a number and its negative give the same answer.
`bit_count()` (new in 3.10) counts the 1 bits, an operation often called
*popcount*; it is handy for counting flags that are set.

```python
sample_number = 0b1011_0000
print(f"{sample_number=}, {sample_number.bit_length()=}")
print(f"{(-sample_number).bit_length()=}")
print(f"{sample_number.bit_count()=}, {(255).bit_count()=}")
```

```text
sample_number=176, sample_number.bit_length()=8
(-sample_number).bit_length()=8
sample_number.bit_count()=3, (255).bit_count()=8
```

`to_bytes(length, byteorder, signed=...)` and the class method `int.from_bytes`
convert between an `int` and its raw bytes. You need them for binary file formats
and network protocols, where a port number, for example, travels as two big-endian
bytes. The byte order matters: reading the same two bytes as little-endian gives a
different number. Negative numbers need `signed=True`, otherwise Python refuses
rather than guessing. Since 3.11 both functions default to big-endian, so the
`byteorder` argument can be left out.

```python
port_number = 8080
port_bytes = port_number.to_bytes(2, "big")
print(f"{port_bytes=}, {port_bytes.hex()=}")
print(f"{int.from_bytes(port_bytes, 'big')=}")
print(f"{int.from_bytes(port_bytes, 'little')=}  (byte order matters)")
print(f"{(-1).to_bytes(2, 'big', signed=True)=}")
try:
    (-1).to_bytes(2, "big")
except OverflowError as error:
    print(f"{type(error).__name__}: {error}")
```

```text
port_bytes=b'\x1f\x90', port_bytes.hex()='1f90'
int.from_bytes(port_bytes, 'big')=8080
int.from_bytes(port_bytes, 'little')=36895  (byte order matters)
(-1).to_bytes(2, 'big', signed=True)=b'\xff\xff'
OverflowError: can't convert negative int to unsigned
```

`bin`, `oct` and `hex` return the number as text in base 2, 8 or 16, with the
matching prefix. When you want the digits without a prefix, or padded to a fixed
width, use `format()` (or an f-string) with the `b`, `o`, `x` or `X` format codes.

```python
print(f"{bin(10)=}, {oct(493)=}, {hex(16_750_899)=}")
print(f"{format(10, '08b')=}, {format(255, 'X')=}")
```

```text
bin(10)='0b1010', oct(493)='0o755', hex(16_750_899)='0xff9933'
format(10, '08b')='00001010', format(255, 'X')='FF'
```

`int(text, base)` goes the other way and parses text in any base from 2 to 36 (the
letters `a` to `z` stand for digits 10 to 35). Base `0` means "read the base from the
prefix in the text", exactly as the parser does for literals. Surrounding whitespace
and underscores between digits are accepted, which makes `int()` forgiving for user
input.

```python
print(f"{int('ff', 16)=}, {int('1010', 2)=}, {int('z', 36)=}")
print(f"{int('0x1F', 0)=}, {int('0b101', 0)=}")
print(f"{int('  1_000  ')=}")
```

```text
int('ff', 16)=255, int('1010', 2)=10, int('z', 36)=35
int('0x1F', 0)=31, int('0b101', 0)=5
int('  1_000  ')=1000
```

`int.is_integer()` (new in 3.12) always returns `True`. That sounds pointless, but it
exists so that code receiving "a number" can ask `value.is_integer()` without
checking first whether it holds an `int` or a `float` (`float` has had the method
for a long time).

```python
for quantity in (3, 3.0, 3.5):
    print(f"{quantity!r:>4}: {quantity.is_integer()=}")
```

```text
   3: quantity.is_integer()=True
 3.0: quantity.is_integer()=True
 3.5: quantity.is_integer()=False
```

### Bitwise operators

The bitwise operators work on the binary digits of an integer. Their classic use is a
set of on/off flags packed into one integer, as in Unix file permissions, where read,
write and execute are the bits `100`, `010` and `001`. Phase 2 introduces
`enum.Flag`, the type-safe version of the same idea.

| Operator | Meaning | Use with flags |
| --- | --- | --- |
| `a \| b` | OR | grant a permission |
| `a & b` | AND | test a permission |
| `a & ~b` | AND NOT | revoke a permission |
| `a ^ b` | XOR | toggle a permission |
| `a << n`, `a >> n` | shift left / right | build masks, `* or / 2**n` |

JavaScript converts operands of bitwise operators to 32-bit signed integers, so
`2**32 | 0` is `0` there. Python ints have no fixed width: they behave as if they
were written in two's complement with an *infinite* number of sign bits. That is why
`~x` is always `-x - 1`, and why shifting left never loses bits.

```python
READ, WRITE, EXECUTE = 0b100, 0b010, 0b001

permissions = READ | WRITE
print(f"{bin(permissions)=}, can write: {bool(permissions & WRITE)}")
permissions &= ~WRITE
print(f"{bin(permissions)=}, can write: {bool(permissions & WRITE)}")
permissions ^= EXECUTE
print(f"{bin(permissions)=}, can execute: {bool(permissions & EXECUTE)}")
print(f"{~5=}  (~x == -x - 1: infinite two's complement)")
print(f"{1 << 10=}, {1024 >> 3=}")
owner_group_other = (0o7 << 6) | (0o5 << 3) | 0o5
print(f"{oct(owner_group_other)=}")
```

```text
bin(permissions)='0b110', can write: True
bin(permissions)='0b100', can write: False
bin(permissions)='0b101', can execute: True
~5=-6  (~x == -x - 1: infinite two's complement)
1 << 10=1024, 1024 >> 3=128
oct(owner_group_other)='0o755'
```

### The 4300-digit string-conversion limit

Converting a huge `int` to or from **decimal text** takes time that grows with the
square of the number of digits, because base 10 does not line up with the internal
base `2**30`. A web service that ran `int(request_body)` on untrusted input could be
stalled for seconds by a request containing a megabyte of digits, a denial-of-service
attack recorded as CVE-2020-10735. Since Python 3.11 (and in security releases of
older versions), Python therefore refuses decimal conversions of more than 4300
digits by default and raises `ValueError`.

The limit applies only to decimal text. Binary-based conversions such as `hex()` and
`bin()` are linear in the number of digits and are not limited. Arithmetic on huge
ints is not limited either; only the text conversion is. If you really need longer
decimal strings, for trusted data only, raise the limit with
`sys.set_int_max_str_digits` and put it back afterwards.

```python
huge_number = 10**5000
try:
    str(huge_number)
except ValueError as error:
    print(f"{type(error).__name__}: {str(error)[:50]}...")
print(f"{len(hex(huge_number))=}  (hex is not limited)")

default_limit = sys.get_int_max_str_digits()
sys.set_int_max_str_digits(10_000)
try:
    print(f"{len(str(huge_number))=}")
finally:
    sys.set_int_max_str_digits(default_limit)
print(f"{sys.get_int_max_str_digits()=}")
```

```text
ValueError: Exceeds the limit (4300 digits) for integer string...
len(hex(huge_number))=4155  (hex is not limited)
len(str(huge_number))=5001
sys.get_int_max_str_digits()=4300
```

> **Warning:** the limit is a process-wide setting. Changing it inside a request
> handler affects every other thread, so wrap the change in `try`/`finally` as above,
> or set it once at start-up with the `-X int_max_str_digits` option or the
> `PYTHONINTMAXSTRDIGITS` environment variable.

### Key points

| Idea | Takeaway |
| --- | --- |
| Precision | Unlimited; no overflow, no BigInt |
| Storage | 30-bit digits, +4 bytes per 30 bits |
| `/` vs `//` | `/` is always float; `//` floors |
| `%` | Takes the divisor's sign: `-7 % 2 == 1` |
| `pow(b, e, m)` | Modular power without huge numbers |
| Bitwise | Infinite two's complement; `~x == -x - 1` |
| Digit limit | Decimal text over 4300 digits raises |

## 1.3.2 Floating point (`float`)

### IEEE 754 doubles, exactly like JavaScript

A Python `float` is an **IEEE 754 double-precision** number: 64 bits, split into a
sign bit, an 11-bit exponent and a 52-bit fraction (the *mantissa*). This is exactly
the format of a JavaScript `number`, so every float result you get in Python is
bit-for-bit what JavaScript would give for the same operation. Under the hood,
CPython's `PyFloatObject` is just the usual object header plus one C `double`, which
is why every float is 24 bytes.

```text
IEEE 754 double (64 bits)

+------+-------------+--------------------------------------+
| sign | exponent    | fraction (mantissa)                  |
| 1    | 11 bits     | 52 bits (+1 implicit leading bit)    |
+------+-------------+--------------------------------------+

value = (-1)**sign * 1.fraction (binary) * 2**(exponent - 1023)
```

Because the fraction is binary, only numbers that are sums of powers of two can be
stored exactly. `0.5`, `0.25` and `0.75` are exact, but most decimal fractions,
including `0.1`, have an infinitely repeating binary form, just as one third is
`0.333…` in decimal. Python stores the nearest double instead, and the tiny errors
show up when you do arithmetic: `0.1 + 0.2` is not `0.3`.

`Decimal(some_float)` reveals the exact value that is really stored, because
`Decimal` converts the float's bits without any rounding. To compare floats, use
`math.isclose`, which allows a small *relative* difference (by default about nine
significant digits). Near zero, a relative tolerance is useless, because any
non-zero number differs from zero by 100%, so pass an absolute tolerance
(`abs_tol`) when one of the values may be zero.

```python
print(f"{0.1 + 0.2=}")
print(f"{0.1 + 0.2 == 0.3=}")
print("Decimal(0.1) =")
print(f"  {Decimal(0.1)!r}")
print(f"{math.isclose(0.1 + 0.2, 0.3)=}")
print(f"{math.isclose(1e-12, 0.0)=}  (relative tolerance fails near 0)")
print(f"{math.isclose(1e-12, 0.0, abs_tol=1e-9)=}")
```

```text
0.1 + 0.2=0.30000000000000004
0.1 + 0.2 == 0.3=False
Decimal(0.1) =
  Decimal('0.1000000000000000055511151231257827021181583404541015625')
math.isclose(0.1 + 0.2, 0.3)=True
math.isclose(1e-12, 0.0)=False  (relative tolerance fails near 0)
math.isclose(1e-12, 0.0, abs_tol=1e-9)=True
```

### `round()` surprises

Two separate effects make `round()` behave differently from what school arithmetic
and JavaScript's `Math.round` lead you to expect.

1. **Banker's rounding.** When a value is *exactly* halfway between two candidates,
   Python's `round()` picks the **even** one: `round(0.5)` is `0`, `round(1.5)` is `2`
   and `round(2.5)` is also `2`. This rule, *round half to even*, is the IEEE 754
   default because it does not push totals upwards when many values are rounded:
   half the ties go down and half go up. JavaScript's `Math.round(2.5)` is `3`, and
   `Math.round(-2.5)` is `-2`, because it always rounds ties towards positive
   infinity.
2. **Representation error.** `2.675` cannot be stored exactly; the nearest double is
   `2.67499999…`. That value is not a tie at all, it is slightly below one, so
   `round(2.675, 2)` correctly rounds *down* to `2.67`. No rounding mode can fix
   this, because the information was lost when the literal was parsed. If you need
   decimal rounding rules, use `Decimal` (1.3.3).

```python
print(f"{round(0.5)=}, {round(1.5)=}, {round(2.5)=}, {round(-2.5)=}")
print(f"{round(2.675, 2)=}")
print(f"{Decimal(2.675)=}")
```

```text
round(0.5)=0, round(1.5)=2, round(2.5)=2, round(-2.5)=-2
round(2.675, 2)=2.67
Decimal(2.675)=Decimal('2.67499999999999982236431605997495353221893310546875')
```

### Special values: `inf`, `-inf` and `nan`

IEEE 754 reserves some bit patterns for special values: positive and negative
infinity, and `nan` ("not a number"). You create them with `float("inf")`,
`float("nan")`, or the constants `math.inf` and `math.nan`. Infinity is also what
you get when a float operation overflows, and `nan` is the result of undefined
operations such as `inf - inf`.

`nan` is not equal to anything, **not even itself**, so `x == float("nan")` is always
`False`. Test for it with `math.isnan`, just as you use `Number.isNaN` in JavaScript.
`math.isinf` and `math.isfinite` complete the set.

The big difference from JavaScript is integer and float division by zero: JavaScript
returns `Infinity`, Python raises `ZeroDivisionError`. Python takes the view that
dividing by zero is almost always a bug and should fail loudly at the point where it
happens, not produce an `inf` that surfaces much later.

```python
positive_infinity = float("inf")
not_a_number = float("nan")
print(f"{positive_infinity > 10**308=}, {-math.inf < -1e308=}")
print(f"{positive_infinity - positive_infinity=}")
print(f"{not_a_number == not_a_number=}")
print(f"{not_a_number != not_a_number=}")
print(f"{math.isnan(not_a_number)=}, {math.isinf(-math.inf)=}")
print(f"{math.isfinite(1e308)=}")
print(f"{1e308 * 10=}")
try:
    ratio = 1 / 0
except ZeroDivisionError as error:
    print(f"{type(error).__name__}: {error}")
```

```text
positive_infinity > 10**308=True, -math.inf < -1e308=True
positive_infinity - positive_infinity=nan
not_a_number == not_a_number=False
not_a_number != not_a_number=True
math.isnan(not_a_number)=True, math.isinf(-math.inf)=True
math.isfinite(1e308)=True
1e308 * 10=inf
ZeroDivisionError: division by zero
```

### `float` methods

`float` has four methods worth knowing, plus the `sys.float_info` constants.

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `as_integer_ratio()` | exact stored fraction | `(0.75).as_integer_ratio()` | `(3, 4)` |
| `is_integer()` | no fractional part? | `(4.0).is_integer()` | `True` |
| `hex()` | exact bits as hex text | `(0.5).hex()` | `'0x1.0000000000000p-1'` |
| `float.fromhex()` | hex text back to float | `float.fromhex("0x1.8p1")` | `3.0` |

`as_integer_ratio()` returns the exact fraction the double stores, as a pair of
integers. For `0.75` that is `3/4`, but for `0.1` it is a fraction with a power of
two in the denominator, which proves that the stored value is not one tenth.

```python
print(f"{(0.75).as_integer_ratio()=}")
print(f"{(0.1).as_integer_ratio()=}")
```

```text
(0.75).as_integer_ratio()=(3, 4)
(0.1).as_integer_ratio()=(3602879701896397, 36028797018963968)
```

`is_integer()` tells whether a float has no fractional part. Large floats are always
whole numbers, because at that size the gap between neighbouring doubles is bigger
than 1.

```python
print(f"{(4.0).is_integer()=}, {(4.5).is_integer()=}")
print(f"{(1e20).is_integer()=}")
```

```text
(4.0).is_integer()=True, (4.5).is_integer()=False
(1e20).is_integer()=True
```

`hex()` and `float.fromhex()` write and read the exact bits of a float as
hexadecimal text, with no decimal rounding at all. They are a lossless way to store
or transmit a float as text. (`repr()` of a float is also lossless since Python 3.1,
because it prints the shortest decimal string that converts back to the same
double, but `hex()` makes the bits visible.)

```python
exact_text = (0.1).hex()
print(f"{exact_text=}")
print(f"{float.fromhex(exact_text) == 0.1=}")
```

```text
exact_text='0x1.999999999999ap-4'
float.fromhex(exact_text) == 0.1=True
```

`sys.float_info` describes the platform's doubles. `max` and `min` are the largest
and smallest positive normal values. `epsilon` is the gap between `1.0` and the next
larger float, so adding less than half of it to `1.0` changes nothing. `dig` is the
number of decimal digits that always survive a round trip (15), and `mant_dig` the
number of bits in the mantissa, including the implicit leading bit (53). JavaScript
exposes the same numbers as `Number.MAX_VALUE`, `Number.EPSILON` and so on.

```python
print(f"{sys.float_info.max=}")
print(f"{sys.float_info.min=}")
print(f"{sys.float_info.epsilon=}")
print(f"{sys.float_info.dig=}, {sys.float_info.mant_dig=}")
print(f"{1.0 + sys.float_info.epsilon > 1.0=}")
print(f"{1.0 + sys.float_info.epsilon / 2 > 1.0=}")
```

```text
sys.float_info.max=1.7976931348623157e+308
sys.float_info.min=2.2250738585072014e-308
sys.float_info.epsilon=2.220446049250313e-16
sys.float_info.dig=15, sys.float_info.mant_dig=53
1.0 + sys.float_info.epsilon > 1.0=True
1.0 + sys.float_info.epsilon / 2 > 1.0=False
```

### Useful `math` functions

The `math` module is Python's counterpart of JavaScript's `Math` object, but it is a
module you import, and it works on real numbers only (`cmath`, in 1.3.5, handles
complex ones). These are the functions you will use most.

**Rounding to whole numbers**

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `math.floor(x)` | round down | `math.floor(-3.7)` | `-4` |
| `math.ceil(x)` | round up | `math.ceil(-3.7)` | `-3` |
| `math.trunc(x)` | drop the fraction | `math.trunc(-3.7)` | `-3` |

**Roots, sums and products**

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `math.sqrt(x)` | square root (float) | `math.sqrt(16)` | `4.0` |
| `math.isqrt(n)` | exact integer root | `math.isqrt(17)` | `4` |
| `math.fsum(xs)` | exactly rounded sum | `math.fsum([0.1] * 10)` | `1.0` |
| `math.prod(xs)` | product of items | `math.prod([2, 3, 7])` | `42` |

**Constants**

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `math.pi` | π | `math.pi` | `3.141592653589793` |
| `math.e` | Euler's number | `math.e` | `2.718281828459045` |
| `math.tau` | 2π | `math.tau` | `6.283185307179586` |

**Comparisons and remainders** (used in the examples above)

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `math.isclose(a, b)` | nearly equal? | `math.isclose(0.1 + 0.2, 0.3)` | `True` |
| `math.isnan(x)` | is it `nan`? | `math.isnan(float("nan"))` | `True` |
| `math.isinf(x)` | is it ±infinity? | `math.isinf(-math.inf)` | `True` |
| `math.isfinite(x)` | neither inf nor nan? | `math.isfinite(1e308)` | `True` |
| `math.fmod(a, b)` | JS-style remainder | `math.fmod(-7, 2)` | `-1.0` |

`floor` rounds down, `ceil` rounds up, and `trunc` drops the fractional part, which
is rounding *towards zero*, the same thing `int()` does to a float. For positive
numbers `floor` and `trunc` agree; they differ only for negative numbers. Unlike
JavaScript's `Math.floor`, which returns a float, all three return an `int`.

```python
for value in (3.7, -3.7):
    rounded_values = (
        math.floor(value),
        math.ceil(value),
        math.trunc(value),
        int(value),
    )
    print(f"{value:>5}: floor, ceil, trunc, int = {rounded_values}")
```

```text
  3.7: floor, ceil, trunc, int = (3, 4, 3, 3)
 -3.7: floor, ceil, trunc, int = (-4, -3, -3, -3)
```

`math.sqrt` returns a float and raises `ValueError` for negative input instead of
returning `NaN` as JavaScript's `Math.sqrt(-1)` does. For square roots of negative
numbers use `cmath.sqrt` (1.3.5). `math.isqrt` returns the exact integer square
root (the floor of the true root) of any `int`, however large, without going through
a float.

```python
print(f"{math.sqrt(2)=}, {math.isqrt(10**20 + 1)=}")
try:
    math.sqrt(-1)
except ValueError as error:
    print(f"{type(error).__name__}: {error}")
```

```text
math.sqrt(2)=1.4142135623730951, math.isqrt(10**20 + 1)=10000000000
ValueError: expected a nonnegative input, got -1.0
```

Adding many floats one at a time, as a `for` loop or JavaScript's
`reduce((a, b) => a + b)` does, rounds after every addition, and the errors pile up.
`math.fsum` tracks every low-order bit that would be lost and rounds only once at the
end, so its result is the correctly rounded sum of the exact values. Since Python
3.12 the built-in `sum()` of floats also uses a compensated algorithm (Neumaier
summation), which fixes the common cases such as ten dimes. `fsum` is still the
fully exact one when values of wildly different sizes cancel each other out.

```python
ten_dimes = [0.1] * 10
loop_total = 0.0
for dime in ten_dimes:
    loop_total += dime
print(f"{loop_total=}  (naive left-to-right)")
print(f"{sum(ten_dimes)=}, {math.fsum(ten_dimes)=}")

mixed_magnitudes = [1e100, 1.0, -1e100, 1e-100, 1e50, -1.0, -1e50]
print(f"{sum(mixed_magnitudes)=}, {math.fsum(mixed_magnitudes)=}")
```

```text
loop_total=0.9999999999999999  (naive left-to-right)
sum(ten_dimes)=1.0, math.fsum(ten_dimes)=1.0
sum(mixed_magnitudes)=0.0, math.fsum(mixed_magnitudes)=1e-100
```

`math.prod` (3.8+) multiplies the items of an iterable, the way `sum` adds them. Its
float results carry the usual representation error.

```python
print(f"{math.prod([2, 3, 7])=}")
print(f"{math.prod([1.05] * 3)=}  (three years of 5% growth)")
```

```text
math.prod([2, 3, 7])=42
math.prod([1.05] * 3)=1.1576250000000001  (three years of 5% growth)
```

`math.pi`, `math.e` and `math.tau` (2π), along with `math.inf` and `math.nan`, are
plain float constants.

```python
circle_radius_in_metres = 2.5
print(f"{math.pi=}, {math.e=}")
print(f"{math.tau == 2 * math.pi=}")
print(f"{math.pi * circle_radius_in_metres**2=}")
```

```text
math.pi=3.141592653589793, math.e=2.718281828459045
math.tau == 2 * math.pi=True
math.pi * circle_radius_in_metres**2=19.634954084936208
```

### Key points

| Idea | Takeaway |
| --- | --- |
| Format | IEEE 754 double, same as a JS `number` |
| Equality | Never `==`; use `math.isclose` |
| `round()` | Ties go to even; `2.675` is not a tie |
| `nan` | Not equal to itself; use `math.isnan` |
| Division by zero | Raises `ZeroDivisionError` |
| Exact bits | `as_integer_ratio()`, `hex()`, `Decimal(x)` |
| Summing | `math.fsum` is exactly rounded |

## 1.3.3 Exact decimals (`decimal.Decimal`)

### Construct from strings, never floats

The `decimal` module provides `Decimal`, a number type that stores values in **base
10**. In a `Decimal`, `0.1` really is one tenth, so the sums an accountant does by
hand come out exactly the same in code. That is what money needs: rupees and paise,
dollars and cents, tax rates such as 18%. JavaScript has no built-in equivalent;
people reach for libraries such as decimal.js or big.js, or store amounts as integer
paise.

Internally a `Decimal` is a sign, a sequence of decimal digits (the *coefficient*)
and a base-10 exponent. `Decimal("1.50")` is the digits `1, 5, 0` with exponent `-2`,
which you can see with `as_tuple()`. Because the exponent is stored, trailing zeros
are kept: `Decimal("1.50")` remembers that it has two decimal places, which is useful
for amounts. The arithmetic itself is done by `_decimal`, a C extension built on the
libmpdec library, specified by PEP 327 and the General Decimal Arithmetic standard.

```python
print(f"{Decimal('1.50').as_tuple()=}")
```

```text
Decimal('1.50').as_tuple()=DecimalTuple(sign=0, digits=(1, 5, 0), exponent=-2)
```

**Always construct a `Decimal` from a string (or an `int`), never from a float.** A
float argument is converted exactly, which means the float's representation error is
copied into the `Decimal`: you get 55 digits of `0.1000000000000000055…` instead of
one tenth. The constructor cannot guess what you meant, because by the time it sees
the float, the literal `0.1` has already become the nearest double.

```python
print(f"{Decimal('0.1')=}")
print("Decimal(0.1) =")
print(f"  {Decimal(0.1)!r}")
print(f"{Decimal('0.1') + Decimal('0.2') == Decimal('0.3')=}")
print(f"{Decimal(25)=}, {Decimal('1.50')=}")
print("  (trailing zeros are kept)")
```

```text
Decimal('0.1')=Decimal('0.1')
Decimal(0.1) =
  Decimal('0.1000000000000000055511151231257827021181583404541015625')
Decimal('0.1') + Decimal('0.2') == Decimal('0.3')=True
Decimal(25)=Decimal('25'), Decimal('1.50')=Decimal('1.50')
  (trailing zeros are kept)
```

> **Warning:** `Decimal(0.1)` is a silent bug: it produces no error, only the wrong
> number. Values that arrive as text (form fields, JSON strings, CSV cells, database
> `NUMERIC` columns) should go straight into `Decimal(text)` without ever becoming a
> float.

### Arithmetic and context precision

`Decimal` supports the usual arithmetic operators and mixes freely with `int`. It
deliberately refuses to mix with `float`, raising `TypeError`, because that would
bring the inexactness back in through the side door.

Every `Decimal` operation is carried out under a **context**: a settings object that
holds the precision (28 significant digits by default), the rounding mode, and which
conditions raise errors. Results such as `1 / 7`, which have infinitely many digits,
are rounded to the context precision. `getcontext()` returns the current context,
and `localcontext()` gives you a temporary copy for the duration of a `with` block,
so a change of precision cannot leak into the rest of the program. The context is
per thread (and per async task), so it is safe to change locally.

```python
unit_price = Decimal("19.99")
print(f"{unit_price * 3=}, {unit_price - 5=}")
print(f"{unit_price / 4=}")
print(f"{Decimal(1) / Decimal(7)=}")
with localcontext() as local_context:
    local_context.prec = 6
    print(f"inside localcontext: {Decimal(1) / Decimal(7)=}")
print(f"after the block: {getcontext().prec=}")
try:
    unit_price + 0.5
except TypeError as error:
    print(f"{type(error).__name__}: {error}")
```

```text
unit_price * 3=Decimal('59.97'), unit_price - 5=Decimal('14.99')
unit_price / 4=Decimal('4.9975')
Decimal(1) / Decimal(7)=Decimal('0.1428571428571428571428571429')
inside localcontext: Decimal(1) / Decimal(7)=Decimal('0.142857')
after the block: getcontext().prec=28
TypeError: unsupported operand type(s) for +: 'decimal.Decimal' and 'float'
```

> **Note:** the precision counts *significant digits*, not decimal places. With the
> default 28 digits, an amount such as `12345678.90` has 18 digits to spare, so
> ordinary money arithmetic is never rounded by the context. Rounding to paise is a
> separate, explicit step: `quantize`.

### `quantize` and rounding modes

`quantize(exponent, rounding=...)` rounds a `Decimal` to the same exponent as its
argument. Passing `PAISE`, which is `Decimal("0.01")`, rounds to two decimal places.
Unlike `round()` on floats, the rounding mode is explicit and the input is exact, so
the result is always what the rule says. The two modes you will use most:

| Mode | Ties go… | Typical use |
| --- | --- | --- |
| `ROUND_HALF_UP` | away from zero | invoices, tax, school maths |
| `ROUND_HALF_EVEN` | to the even digit | statistics; the default |

With `ROUND_HALF_UP`, `2.675` becomes `2.68` and `2.665` becomes `2.67`. With
`ROUND_HALF_EVEN` (banker's rounding, the default context mode), `2.665` becomes
`2.66` because 6 is even. Tax authorities usually specify half-up rounding, so
invoices should name it explicitly rather than rely on the default. The module also
offers `ROUND_DOWN`, `ROUND_UP`, `ROUND_CEILING`, `ROUND_FLOOR`, `ROUND_HALF_DOWN` and
`ROUND_05UP`.

```python
print(f"{'value':>7} {'HALF_UP':>8} {'HALF_EVEN':>10}")
for amount_text in ["2.675", "2.665", "0.125", "-1.005"]:
    amount = Decimal(amount_text)
    half_up = amount.quantize(PAISE, rounding=ROUND_HALF_UP)
    half_even = amount.quantize(PAISE, rounding=ROUND_HALF_EVEN)
    print(f"{amount_text:>7} {half_up!s:>8} {half_even!s:>10}")
```

```text
  value  HALF_UP  HALF_EVEN
  2.675     2.68       2.68
  2.665     2.67       2.66
  0.125     0.13       0.12
 -1.005    -1.01      -1.00
```

Note that `-1.005` rounds half-up to `-1.01`: "up" means *away from zero*, so
negative amounts are rounded symmetrically.

### Money: an 18% GST demo

Here is the difference in practice. One thousand orders of ₹99.99 each, with 18% GST
computed and rounded to paise on every order, then added to a grand total. The float
version uses `round()`; the `Decimal` version uses `quantize` with `ROUND_HALF_UP`.
The exact answer is ₹117,990.00. The float total is off in the ninth decimal place,
because each of the thousand additions rounds to the nearest double. That looks
harmless until a reconciliation check compares totals with `==`, or the error is
printed on an invoice.

```python
order_count = 1_000

float_grand_total = 0.0
for _ in range(order_count):
    float_grand_total += 99.99 + round(99.99 * 0.18, 2)

decimal_grand_total = Decimal("0.00")
for _ in range(order_count):
    gst = (Decimal("99.99") * Decimal("0.18")).quantize(
        PAISE, rounding=ROUND_HALF_UP
    )
    decimal_grand_total += Decimal("99.99") + gst

print(f"{float_grand_total=}")
print(f"{decimal_grand_total=}")
```

```text
float_grand_total=117990.00000000196
decimal_grand_total=Decimal('117990.00')
```

### The performance trade-off

Float arithmetic runs directly in the CPU's floating-point hardware. `Decimal`
arithmetic runs in software: the `_decimal` C extension is fast, but it still has to
allocate a larger object and process decimal digits. The measurement below runs the
same expression 200,000 times with each type.

```python
float_operands = {"a": 99.99, "b": 0.18, "c": 1.5}
decimal_operands = {
    "a": Decimal("99.99"),
    "b": Decimal("0.18"),
    "c": Decimal("1.5"),
}
float_seconds = timeit.timeit(
    "a * b + c", globals=float_operands, number=200_000
)
decimal_seconds = timeit.timeit(
    "a * b + c", globals=decimal_operands, number=200_000
)
slowdown = decimal_seconds / float_seconds
print(f"float:   {float_seconds * 1000:.1f} ms")
print(f"Decimal: {decimal_seconds * 1000:.1f} ms")
print(f"Decimal is about {slowdown:.0f}x slower")
```

```text
float:   3.3 ms
Decimal: 15.9 ms
Decimal is about 5x slower
```

> **Note:** timings vary from machine to machine and from run to run; the ratio is
> what matters. A few times slower is irrelevant for an invoice with fifty lines, and
> relevant for a simulation with fifty million steps.

The usual pattern is therefore `Decimal` (or integer paise) for money, and `float`
for measurements, statistics and science, where tiny relative errors do not matter
and speed does.

### Key points

| Idea | Takeaway |
| --- | --- |
| Base 10 | `Decimal("0.1")` is exactly one tenth |
| Construction | From `str` or `int`, never from `float` |
| Mixing | Works with `int`, raises with `float` |
| Context | 28 significant digits; `localcontext()` |
| `quantize` | Round to paise with an explicit mode |
| Money | `ROUND_HALF_UP` per line, then add |
| Cost | Several times slower than `float` |

## 1.3.4 Rational numbers (`fractions.Fraction`)

A `Fraction` is an exact rational number: a numerator and a denominator, both Python
`int`s, always kept in lowest terms with a positive denominator. Because both parts
are arbitrary-precision integers, `Fraction` arithmetic never rounds. One third
really is one third, so `Fraction(1, 3) * 3 == 1` holds exactly. Fractions are
useful for exact ratios, probabilities, musical intervals, scaling recipes and unit
conversions.

Under the hood, `fractions` is a pure-Python module. Every operation computes a new
numerator and denominator and divides both by their greatest common divisor
(`math.gcd`) to keep the fraction reduced. That makes `Fraction` the slowest of the
numeric types, and the numbers can grow large over long calculations, but the answer
is always exact.

```python
one_third = Fraction(1, 3)
print(f"{one_third * 3 == 1=}, {one_third * 3=}")
print(f"{Fraction(6, 8)=}  (reduced automatically)")
print(f"{one_third + Fraction(1, 6)=}")
print(f"{1 / 3 * 3 == 1=}")
print("  (float happens to round back here, but not in general)")
```

```text
one_third * 3 == 1=True, one_third * 3=Fraction(1, 1)
Fraction(6, 8)=Fraction(3, 4)  (reduced automatically)
one_third + Fraction(1, 6)=Fraction(1, 2)
1 / 3 * 3 == 1=True
  (float happens to round back here, but not in general)
```

There are three ways to build a `Fraction` from something other than two integers:

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `Fraction(text)` | parse "a/b" or decimals | `Fraction("0.125")` | `Fraction(1, 8)` |
| `Fraction(float)` | exact stored value | `Fraction(0.75)` | `Fraction(3, 4)` |
| `limit_denominator(n)` | closest with denom ≤ n | `Fraction(0.1).limit_denominator(10)` | `Fraction(1, 10)` |

Building a `Fraction` from a **string** gives the exact value you typed, whether it
is written as `"3/7"`, as a decimal or in scientific notation. Building it from a
**float** gives the float's exact binary value, the same fraction that
`as_integer_ratio()` returns, which for `0.1` is not one tenth. To recover the value
you probably meant, `limit_denominator(max_denominator)` finds the closest fraction
whose denominator is no larger than the limit. Applied to `math.pi` with a limit of
1000, it finds the famous approximation 355/113.

```python
print(f"{Fraction('3/7')=}, {Fraction('0.125')=}")
print(f"{Fraction('1.5e-2')=}")
print(f"{Fraction(0.1)=}")
print(f"{Fraction(0.1).limit_denominator(1000)=}")
print(f"{Fraction(math.pi).limit_denominator(1000)=}")
```

```text
Fraction('3/7')=Fraction(3, 7), Fraction('0.125')=Fraction(1, 8)
Fraction('1.5e-2')=Fraction(3, 200)
Fraction(0.1)=Fraction(3602879701896397, 36028797018963968)
Fraction(0.1).limit_denominator(1000)=Fraction(1, 10)
Fraction(math.pi).limit_denominator(1000)=Fraction(355, 113)
```

> **Note:** a `Fraction` mixes with `int` and stays exact, but mixing it with a
> `float` produces a `float`, and the exactness is gone. Choose `Fraction` when the
> values are ratios (1/3 of a bill), and `Decimal` when they are decimal amounts with
> a fixed number of places (₹33.33).

### Key points

| Idea | Takeaway |
| --- | --- |
| Exact | `Fraction(1, 3) * 3 == 1` |
| Reduced | Always in lowest terms |
| From text | Exact value you typed |
| From float | The float's binary value |
| `limit_denominator` | Recovers simple ratios |

## 1.3.5 Complex numbers (`complex`)

Python has complex numbers built into the language: write the imaginary part as a
number with a `j` suffix (the electrical-engineering convention, since `i` usually
means current). A `complex` is stored as two C doubles, the real and imaginary parts,
so it has the same precision as `float`. Complex numbers are used in signal
processing, electrical engineering and some geometry; JavaScript has no equivalent,
and in web work you will rarely need them.

The real and imaginary parts are available as the attributes `.real` and `.imag`
(always floats). `abs()` returns the magnitude, the distance from zero, computed with
Pythagoras. `conjugate()` flips the sign of the imaginary part, and a number times
its conjugate is the square of its magnitude. `complex(real, imag)` builds one from
two numbers.

```python
impedance = 3 + 4j
print(f"{impedance=}, {type(impedance).__name__=}")
print(f"{impedance.real=}, {impedance.imag=}")
print(f"{abs(impedance)=}  (magnitude)")
print(f"{impedance.conjugate()=}")
print(f"{impedance * impedance.conjugate()=}")
print(f"{complex(3, 4) == impedance=}")
```

```text
impedance=(3+4j), type(impedance).__name__='complex'
impedance.real=3.0, impedance.imag=4.0
abs(impedance)=5.0  (magnitude)
impedance.conjugate()=(3-4j)
impedance * impedance.conjugate()=(25+0j)
complex(3, 4) == impedance=True
```

`cmath` is the complex-number version of `math`. Its functions accept negative and
complex inputs and return complex results, so `cmath.sqrt(-1)` is `1j` where
`math.sqrt(-1)` raises. `phase` gives the angle of a complex number in radians,
`polar` converts to (magnitude, angle), and `rect` converts back. The last result
shows float representation error again: `3.0000000000000004` instead of `3`.

```python
print(f"{cmath.sqrt(-1)=}")
print(f"{cmath.phase(1j)=}  (pi / 2)")
print(f"{cmath.polar(impedance)=}")
print(f"{cmath.rect(5, 0.9272952180016122)=}")
```

```text
cmath.sqrt(-1)=1j
cmath.phase(1j)=1.5707963267948966  (pi / 2)
cmath.polar(impedance)=(5.0, 0.9272952180016122)
cmath.rect(5, 0.9272952180016122)=(3.0000000000000004+3.9999999999999996j)
```

### Key points

| Idea | Takeaway |
| --- | --- |
| Literal | `3 + 4j`; `j` marks the imaginary part |
| Parts | `.real`, `.imag` are floats |
| Magnitude | `abs(z)` |
| Maths | Use `cmath`, not `math` |

## 1.3.6 Booleans (`bool`)

### `bool` is a subclass of `int`

Python's `bool` type has exactly two instances, `True` and `False`, written with
capital letters. What surprises JavaScript developers is that `bool` is a
**subclass of `int`**: `True` behaves as `1` and `False` as `0` in every arithmetic
context, and `True == 1` is `True`. This is a historical design. Python had no
boolean type until 2.3, when PEP 285 added one; making it a subclass of `int` kept
all the existing code that used `1` and `0` as truth values working.

Under the hood, `True` and `False` are two pre-built singleton objects, laid out
exactly like the integers 1 and 0 (which is why `True` is 28 bytes, like a small
`int`). `bool` cannot be subclassed further, and `bool(x)` always returns one of the
two singletons, so `is True` comparisons are reliable, though rarely needed.

The integer nature has one genuinely handy consequence: `sum()` over a list of
booleans counts the `True` values, and `sum(1 for ...)` patterns become
`sum(condition for ...)`.

```python
print(f"{issubclass(bool, int)=}")
print(f"{True + True=}, {True * 10=}, {True == 1=}")
order_is_paid = [True, False, True, True]
print(f"{sum(order_is_paid)=} paid orders")
```

```text
issubclass(bool, int)=True
True + True=2, True * 10=10, True == 1=True
sum(order_is_paid)=3 paid orders
```

### The `isinstance(True, int)` validation trap

Because `True` *is* an `int`, `isinstance(True, int)` returns `True`. A validation
check written to accept positive integer quantities therefore also accepts `True`,
which then behaves as a quantity of 1. A JSON payload with `"quantity": true` would
slip through and order one item. The fix is to reject `bool` explicitly before
checking for `int`. (Libraries such as Pydantic, used in the FastAPI phase, have a
*strict* mode for exactly this reason.)

```python
def is_valid_quantity_naive(quantity: object) -> bool:
    """Accept positive ints (buggy: also accepts True)."""
    return isinstance(quantity, int) and quantity > 0


def is_valid_quantity(quantity: object) -> bool:
    """Accept positive ints, rejecting bool."""
    return (
        isinstance(quantity, int)
        and not isinstance(quantity, bool)
        and quantity > 0
    )


for candidate in (3, True, 0, 2.0):
    naive_verdict = is_valid_quantity_naive(candidate)
    fixed_verdict = is_valid_quantity(candidate)
    print(f"{candidate!r:>5}: naive={naive_verdict}, fixed={fixed_verdict}")
```

```text
    3: naive=True, fixed=True
 True: naive=True, fixed=False
    0: naive=False, fixed=False
  2.0: naive=False, fixed=False
```

> **Warning:** the same trap appears with `type(value) in (int, float)` versus
> `isinstance`, with dict keys (`True` and `1` are the same key, 1.6.2), and in
> sorting, where `False < 1 < True + 1` is perfectly legal. When a value must be a
> number and not a flag, say so explicitly.

### Converting with `bool()`

`bool(x)` converts any value to `True` or `False` using the truthiness rules of
1.3.8. Watch out for strings: **any non-empty string is `True`**, including `"False"`
and `"0"`. This matters for form fields, query parameters and environment variables,
which always arrive as text. Parse such text explicitly by comparing it against the
values you accept.

```python
print(f"{bool(0)=}, {bool(42)=}, {bool('')=}")
print(f"{bool('False')=}, {bool('0')=}")
form_value = "false"
print(f"{form_value.strip().lower() in {'true', '1', 'yes'}=}")
print("  (parse text explicitly)")
```

```text
bool(0)=False, bool(42)=True, bool('')=False
bool('False')=True, bool('0')=True
form_value.strip().lower() in {'true', '1', 'yes'}=False
  (parse text explicitly)
```

### Key points

| Idea | Takeaway |
| --- | --- |
| Values | `True`, `False` (capitalised singletons) |
| Subclass of `int` | `True + True == 2`; `sum(flags)` counts |
| Validation | Reject `bool` before checking `int` |
| `bool("False")` | `True`: any non-empty string is true |

## 1.3.7 The null value (`None`)

`None` is Python's single "no value" marker. It is the **only instance** of the type
`NoneType`; there is exactly one `None` object in the interpreter, and calling
`type(None)()` just hands it back. Because every `None` is the same object, the
idiomatic check is `value is None` (identity), not `value == None` (equality). The
identity check is faster and cannot be fooled by a class whose `__eq__` claims to
equal everything.

A function that ends without a `return` statement, or with a bare `return`, returns
`None`. This is the Python equivalent of a JavaScript function implicitly returning
`undefined`, and it is why the return type of such functions is annotated `-> None`.

```python
def log_message(message: str) -> None:
    """Print a message; no return statement."""
    print(f"log: {message}")


result = log_message("order created")
print(f"{result is None=}")
print(f"{type(None).__name__=}, {type(None)() is None=}")
```

```text
log: order created
result is None=True
type(None).__name__='NoneType', type(None)() is None=True
```

### No `undefined`

JavaScript has two empty values, `null` and `undefined`, and produces `undefined`
silently in many situations: reading a missing property, a missing array element, an
unassigned variable, a missing function argument. Python has **no `undefined`** and
raises an exception in each of those situations instead:

| Situation | JavaScript | Python |
| --- | --- | --- |
| Unknown variable | `ReferenceError` | `NameError` |
| Missing attribute | `undefined` | `AttributeError` |
| Missing dict key | `undefined` | `KeyError` |
| Index past the end | `undefined` | `IndexError` |
| Missing argument | `undefined` | `TypeError` |

When you want the JavaScript behaviour of "give me nothing if it is missing", ask for
it explicitly: `dict.get(key)` returns `None` for a missing key, and
`dict.get(key, default)` returns the default you supply.

```python
customer = {"name": "Asha", "city": "Pune"}
try:
    customer["phone"]
except KeyError as error:
    print(f"{type(error).__name__}: {error}")
print(f"{customer.get('phone')=}")
print(f"{customer.get('phone', 'not given')=}")
```

```text
KeyError: 'phone'
customer.get('phone')=None
customer.get('phone', 'not given')='not given'
```

> **Note:** JavaScript's optional chaining (`user?.address?.city`) and nullish
> coalescing (`value ?? fallback`) have no direct operators in Python. You write
> `value if value is not None else fallback`, or use `dict.get` and `getattr(obj,
> name, default)`.

### Key points

| Idea | Takeaway |
| --- | --- |
| Singleton | The only `NoneType` instance |
| Check | `is None`, never `== None` |
| Implicit return | Functions without `return` give `None` |
| No `undefined` | Missing things raise; use `.get()` |

## 1.3.8 Truthiness

### The falsy values

Every Python object has a truth value, used whenever it appears in an `if` or
`while` condition, or as an operand of `and`, `or` and `not`. The rule is short: a
small set of values is **falsy**, and everything else is truthy. The falsy values are
`None`, `False`, the zero of every numeric type, and every empty container.

| Falsy value | Type |
| --- | --- |
| `None` | `NoneType` |
| `False` | `bool` |
| `0`, `0.0`, `0j` | `int`, `float`, `complex` |
| `Decimal(0)`, `Fraction(0)` | `Decimal`, `Fraction` |
| `""`, `b""` | `str`, `bytes` |
| `[]`, `()`, `{}` | `list`, `tuple`, `dict` |
| `set()`, `range(0)` | `set`, `range` |
| `__bool__` returns `False` | user classes |
| `__len__` returns `0` | user classes |

The loop below evaluates every built-in row of the table.

```python
falsy_candidates = [None, False, 0, 0.0, 0j, Decimal(0), Fraction(0)]
falsy_candidates += ["", b"", [], (), {}, set(), range(0)]
for candidate in falsy_candidates:
    print(f"{candidate!r:<14} -> {bool(candidate)}")
```

```text
None           -> False
False          -> False
0              -> False
0.0            -> False
0j             -> False
Decimal('0')   -> False
Fraction(0, 1) -> False
''             -> False
b''            -> False
[]             -> False
()             -> False
{}             -> False
set()          -> False
range(0, 0)    -> False
```

### How CPython decides

When CPython needs a truth value, it calls the C function `PyObject_IsTrue`, which
works through a fixed order of checks:

```text
PyObject_IsTrue(obj)
  obj is True               -> true
  obj is False or None      -> false
  type defines __bool__     -> call it (must return a bool)
  type defines __len__      -> true if len(obj) != 0
  otherwise                 -> true
```

So a user class decides its own truthiness with `__bool__`, or, if that is missing,
with `__len__`, where a length of zero is false. A class with neither is always
truthy. The example shows all three cases: a wallet that is truthy only when it
holds money, a bag whose truthiness comes from its length, and a plain object.

```python
class Wallet:
    """A wallet that is truthy only when it holds money."""

    def __init__(self, balance_in_paise: int) -> None:
        self.balance_in_paise = balance_in_paise

    def __bool__(self) -> bool:
        return self.balance_in_paise > 0


class ShoppingBag:
    """A bag whose truthiness comes from its length."""

    def __init__(self, items: list[str]) -> None:
        self.items = items

    def __len__(self) -> int:
        return len(self.items)


class PlainObject:
    """No __bool__ and no __len__."""


print(f"{bool(Wallet(0))=}, {bool(Wallet(500))=}")
print(f"{bool(ShoppingBag([]))=}, {bool(ShoppingBag(['soap']))=}")
print(f"{bool(PlainObject())=}")
```

```text
bool(Wallet(0))=False, bool(Wallet(500))=True
bool(ShoppingBag([]))=False, bool(ShoppingBag(['soap']))=True
bool(PlainObject())=True
```

### Differences from JavaScript

The biggest difference is that empty containers are falsy in Python and truthy in
JavaScript. In JavaScript you write `if (items.length)` because `if (items)` is
always true for an array; in Python, `if items:` is the idiomatic emptiness check.

| Value | JavaScript | Python |
| --- | --- | --- |
| `[]`, `{}` | truthy | **falsy** |
| `"0"`, `" "` | truthy | truthy |
| `NaN` | falsy | **truthy** (non-zero) |
| `0n` / `0` | falsy | falsy |
| `document.all` | falsy (!) | — |

`nan` is truthy in Python because the rule is "zero is false", and `nan` is not
zero.

### When to prefer `is not None`

`if value:` treats `0`, `""`, `[]` and `None` alike. That is exactly right when you
mean "is there anything here?", and exactly wrong when `0` or an empty string is a
legitimate value. The classic bug is a default argument: a discount of `0` is a
valid input meaning "no discount", but `if not discount:` mistakes it for "not
given" and applies the default discount instead. Test for `None` explicitly when a
falsy value is valid input.

```python
def price_after_discount_buggy(
    price: int, discount: int | None = None
) -> int:
    """Apply a discount; treats a discount of 0 as 'not given' (bug)."""
    if not discount:
        discount = 10  # default discount
    return price - discount


def price_after_discount(price: int, discount: int | None = None) -> int:
    """Apply a discount; only None means 'not given'."""
    if discount is None:
        discount = 10
    return price - discount


print(f"{bool(float('nan'))=}")
print(f"{price_after_discount_buggy(100, 0)=}  (wanted 100)")
print(f"{price_after_discount(100, 0)=}")
```

```text
bool(float('nan'))=True
price_after_discount_buggy(100, 0)=90  (wanted 100)
price_after_discount(100, 0)=100
```

> **Warning:** JavaScript's `value || fallback` has the same bug, which is why `??`
> was added. Python's `value or fallback` behaves like `||`, and there is no `??`; use
> `fallback if value is None else value` when zero or empty is valid.

### Key points

| Idea | Takeaway |
| --- | --- |
| Falsy | `None`, `False`, zeros, empty containers |
| Custom | `__bool__`, else `__len__`, else true |
| JS difference | `[]` and `{}` are falsy in Python |
| `nan` | Truthy in Python |
| Optional values | Use `is not None` when 0 is valid |

## 1.3.9 Type conversion

### Explicit conversion functions

Python converts between types only when you ask, by calling the target type like a
function: `int()`, `float()`, `str()`, `bool()` and `complex()`. Each accepts the
obvious inputs and rejects the rest.

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `int(x)` | text or number to `int` | `int(" -7 ")` | `-7` |
| `float(x)` | text or number to `float` | `float("1e3")` | `1000.0` |
| `str(x)` | any object to text | `str(None)` | `'None'` |
| `bool(x)` | truthiness | `bool("")` | `False` |
| `complex(x)` | text or number to `complex` | `complex("3+4j")` | `(3+4j)` |

A few behaviours deserve attention. `int()` of a float **truncates** towards zero, so
`int(3.99)` is `3`; use `round()` if you want rounding. `int()` of text accepts only
an integer literal, so `int("3.5")` fails; convert to `float` first if decimals are
allowed. `float()` accepts scientific notation and the special names `"nan"` and
`"inf"`. `str()` works on every object, because every object can describe itself.

```python
print(f"{int('42')=}, {int(' -7 ')=}, {int(3.99)=}, {int(True)=}")
print(f"{float('3.5')=}, {float('1e3')=}")
print(f"{float('nan')=}, {float(7)=}")
print(f"{str(42)=}, {str(3.5)=}, {str(None)=}")
print(f"{bool(1)=}, {bool('')=}")
print(f"{complex('3+4j')=}, {complex(2)=}")
print(f"{int(float('3.5'))=}")
```

```text
int('42')=42, int(' -7 ')=-7, int(3.99)=3, int(True)=1
float('3.5')=3.5, float('1e3')=1000.0
float('nan')=nan, float(7)=7.0
str(42)='42', str(3.5)='3.5', str(None)='None'
bool(1)=True, bool('')=False
complex('3+4j')=(3+4j), complex(2)=(2+0j)
int(float('3.5'))=3
```

### What raises `ValueError`

When the text is not a valid literal for the target type, the conversion raises
`ValueError`, with a message that quotes the bad text. This is different from
JavaScript, where `Number("12abc")` quietly returns `NaN` and `parseInt("12abc")`
quietly returns `12`. In Python a bad input fails at the conversion, where it is
easy to catch and report. Note that `complex()` does not allow spaces around the `+`.

```python
bad_conversions: list[tuple[Callable[[str], object], str]] = [
    (int, "3.5"),
    (int, "12abc"),
    (float, "abc"),
    (complex, "3 + 4j"),
]
for converter, bad_text in bad_conversions:
    try:
        converter(bad_text)
    except ValueError as error:
        print(f"{converter.__name__}({bad_text!r}) -> ValueError:")
        print(f"  {error}")
```

```text
int('3.5') -> ValueError:
  invalid literal for int() with base 10: '3.5'
int('12abc') -> ValueError:
  invalid literal for int() with base 10: '12abc'
float('abc') -> ValueError:
  could not convert string to float: 'abc'
complex('3 + 4j') -> ValueError:
  complex() arg is a malformed string
```

### No implicit coercion

JavaScript converts between types silently: `1 + "1"` is `"11"`, and `1 == "1"` is
`true` (which is why you were taught to use `===`). Python never mixes text and
numbers behind your back. `1 + "1"` raises `TypeError`, and `==` between unrelated
types simply returns `False`, so Python's `==` behaves like JavaScript's `===` here.
Convert explicitly in the direction you mean.

Numeric types are the exception: they do mix with each other, because the
conversion is well defined. `1 + 2.5` is `3.5`, and `1`, `1.0`, `Decimal(1)` and
`Fraction(1)` all compare equal (and hash equal, so they are the same dict key).

```python
try:
    mixed_total = 1 + "1"
except TypeError as error:
    print(f"{type(error).__name__}: {error}")
print(f"{1 == '1'=}")
print(f"{1 + int('1')=}, {str(1) + '1'=}")
print(f"{1 + 2.5=}")
print(f"{1 == 1.0 == Decimal(1) == Fraction(1)=}")
```

```text
TypeError: unsupported operand type(s) for +: 'int' and 'str'
1 == '1'=False
1 + int('1')=2, str(1) + '1'='11'
1 + 2.5=3.5
1 == 1.0 == Decimal(1) == Fraction(1)=True
```

### Under the hood: object sizes across the unit

Every number in Python is a full heap object with a header (reference count and type
pointer), not a raw machine value as in a JavaScript engine's optimised paths. That
is why even `True` costs bytes. For `int`, the size is a fixed header plus 4 bytes
per 30-bit digit, as 1.3.1 showed. The cell below checks that formula against
`sys.getsizeof` for growing values, then uses `show_size` to compare the other
numeric types: `float` is the header plus one double, `complex` the header plus two,
and `Decimal` and `Fraction` are larger because they carry more structure.

```python
int_header_bytes = sys.getsizeof(1) - sys.int_info.sizeof_digit
bits_per_digit = sys.int_info.bits_per_digit
for exponent in (10, 100, 1_000):
    number = 2**exponent
    digit_count = -(-number.bit_length() // bits_per_digit)  # ceiling
    predicted_bytes = (
        int_header_bytes + digit_count * sys.int_info.sizeof_digit
    )
    actual_bytes = sys.getsizeof(number)
    print(
        f"2**{exponent:<5} digits={digit_count:<3} "
        f"{predicted_bytes=:<4} {actual_bytes=}"
    )

show_size("float", 1.5)
show_size("complex", 1 + 2j)
show_size("Decimal", Decimal("1.5"))
show_size("Fraction", Fraction(1, 2))
show_size("True", True)
```

```text
2**10    digits=1   predicted_bytes=28   actual_bytes=28
2**100   digits=4   predicted_bytes=40   actual_bytes=40
2**1000  digits=34  predicted_bytes=160  actual_bytes=160
float: 24 bytes, type=float, id=140564979715888
complex: 32 bytes, type=complex, id=140564979712848
Decimal: 120 bytes, type=Decimal, id=140564979880640
Fraction: 48 bytes, type=Fraction, id=140564979900592
True: 28 bytes, type=bool, id=22110296
```

> **Note:** the `id=` values are memory addresses and change on every run. The byte
> sizes are stable for a given Python version and platform (64-bit CPython here).
> `sys.getsizeof` is shallow: the 48 bytes of a `Fraction` do not include the two
> `int` objects it holds.

### Key points

| Idea | Takeaway |
| --- | --- |
| Explicit | Call the type: `int()`, `float()`, … |
| `int(3.99)` | Truncates to `3` |
| Bad text | Raises `ValueError` (no `NaN`) |
| `1 + "1"` | Raises `TypeError` |
| `1 == "1"` | `False`; numbers mix with numbers only |

## Lab 1.3

The lab has three exercises: an exact bill splitter, an invoice calculator with a
float version that shows the drift, and four predict-the-output questions. The
checks use `run_checks`, the shared helper from Unit 1.1 that runs
`(label, thunk, expected)` cases and prints `PASS` or `FAIL` for each. The error
case uses a small helper, `raised_error_name(thunk)`, which calls a function and
returns the name of the exception it raised, or `"no error"`.

### Exercise 1 — `split_bill`

Write `split_bill(total_amount: str, people_count: int) -> list[Decimal]`:

- Split the total, a rupee amount given as text such as `"100"` or `"1000.01"`, into
  `people_count` parts **exact to the paisa**: every part has two decimal places,
  and the parts add up to exactly the total.
- Parts differ by at most one paisa, and the leftover paise go to the **first**
  people, so `split_bill("100", 3)` returns
  `[Decimal("33.34"), Decimal("33.33"), Decimal("33.33")]`.
- Raise `ValueError` when `people_count` is less than 1.

The checks:

| Check | Call | Expected |
| --- | --- | --- |
| 100 between 3 | `split_bill("100", 3)` | `33.34, 33.33, 33.33` |
| Sum is exact | `sum(split_bill("1000.01", 7))` | `Decimal("1000.01")` |
| One part each | `len(split_bill("10", 4))` | `4` |
| Max − min | `split_bill("0.05", 3)` | at most `0.01` |
| Two places | `split_bill("90", 4)` | every exponent `-2` |
| Type | `split_bill("1", 1)[0]` | a `Decimal` |
| Zero people | `split_bill("10", 0)` | raises `ValueError` |

*Hint:* work in whole paise. Convert the total to an integer number of paise, then
`divmod(total_in_paise, people_count)` gives the base share and the number of people
who get one extra paisa.

### Exercise 2 — invoice calculator

An invoice is a list of `(unit_price, quantity)` line items. For **each line**, the
net amount is unit price × quantity, and the GST is net amount × rate, **rounded to
paise per line**. The invoice total is the sum of every line's net amount plus its
GST.

1. `invoice_total_decimal(line_items, gst_rate_percent="18") -> Decimal`, where
   `line_items` is a `list[tuple[str, int]]`: prices and the rate are strings, GST
   is rounded with `quantize(PAISE, rounding=ROUND_HALF_UP)`, and the total is
   returned with two decimal places.
2. `invoice_total_float(line_items, gst_rate_percent=18.0) -> float`, where
   `line_items` is a `list[tuple[float, int]]`: the same calculation with floats and
   `round(gst, 2)`. Do **not** round the final total, so the drift stays visible.

The checks use this sample invoice:

```python
sample_line_items = [
    ("19.99", 3),
    ("0.10", 7),
    ("2.75", 1),
    ("12.25", 2),
    ("0.25", 1),
    ("5.25", 1),
]
float_line_items = [
    (float(price), quantity) for price, quantity in sample_line_items
]
```

| Check | Call | Expected |
| --- | --- | --- |
| Empty invoice | `invoice_total_decimal([])` | `Decimal("0.00")` |
| One line | `invoice_total_decimal([("100", 2)])` | `Decimal("236.00")` |
| Half up | `invoice_total_decimal([("1.25", 1)])` | `Decimal("1.48")` |
| Rate 5% | `invoice_total_decimal([("10.10", 1)], "5")` | `Decimal("10.61")` |
| Sample | `invoice_total_decimal(sample_line_items)` | `Decimal("110.25")` |
| Float, one line | `invoice_total_float([(100.0, 2)])` | `236.0` |
| Float, 2.75 | `invoice_total_float([(2.75, 1)])` | `3.24` |
| Float drift | float total vs exact total | not equal |

*Hint:* the ₹2.75 line is the interesting one. Its GST is exactly ₹0.495, which
`ROUND_HALF_UP` makes ₹0.50. The float `2.75 * 18 / 100` is stored just *below*
0.495, so `round()` gives ₹0.49, and the float invoice loses a paisa.

<details><summary>Solution</summary>

`split_bill` rounds the total to paise, converts it to an integer number of paise,
and lets `divmod` share it out. The first `leftover_paise` people get one extra
paisa. Converting back with `/ 100` and `quantize(PAISE)` guarantees two decimal
places on every part.

```python
from collections.abc import Callable
from decimal import ROUND_HALF_UP, Decimal

PAISE = Decimal("0.01")


def raised_error_name(thunk: Callable[[], object]) -> str:
    """Call thunk and return the name of the exception it raised."""
    try:
        thunk()
    except Exception as error:
        return type(error).__name__
    return "no error"


def split_bill(total_amount: str, people_count: int) -> list[Decimal]:
    """Split a rupee amount into people_count parts, exact to the paisa.

    The parts differ by at most one paisa and always sum to the total;
    the leftover paise go to the first people in the list.

    Raises:
        ValueError: if people_count is less than 1.
    """
    if people_count < 1:
        raise ValueError(
            f"people_count must be at least 1, got {people_count}"
        )
    total_in_paise = int(
        Decimal(total_amount).quantize(PAISE, rounding=ROUND_HALF_UP) * 100
    )
    base_share_in_paise, leftover_paise = divmod(
        total_in_paise, people_count
    )
    return [
        (
            Decimal(base_share_in_paise + (1 if index < leftover_paise else 0))
            / 100
        ).quantize(PAISE)
        for index in range(people_count)
    ]
```

The invoice functions follow the specification line by line. The `Decimal` version
starts from `Decimal("0.00")` so even an empty invoice has two decimal places; the
float version deliberately leaves the total unrounded.

```python
def invoice_total_decimal(
    line_items: list[tuple[str, int]], gst_rate_percent: str = "18"
) -> Decimal:
    """Return the total: each line's net amount plus its GST (half-up).

    Args:
        line_items: (unit price as a string, quantity) pairs.
        gst_rate_percent: GST rate as a string, e.g. "18".
    """
    gst_rate = Decimal(gst_rate_percent) / 100
    invoice_total = Decimal("0.00")
    for unit_price, quantity in line_items:
        line_net_amount = Decimal(unit_price) * quantity
        line_gst = (line_net_amount * gst_rate).quantize(
            PAISE, rounding=ROUND_HALF_UP
        )
        invoice_total += line_net_amount + line_gst
    return invoice_total.quantize(PAISE)


def invoice_total_float(
    line_items: list[tuple[float, int]], gst_rate_percent: float = 18.0
) -> float:
    """Return the same total computed with float and round().

    Args:
        line_items: (unit price, quantity) pairs.
        gst_rate_percent: GST rate, e.g. 18.0.
    """
    invoice_total = 0.0
    for unit_price, quantity in line_items:
        line_net_amount = unit_price * quantity
        line_gst = round(line_net_amount * gst_rate_percent / 100, 2)
        invoice_total += line_net_amount + line_gst
    return invoice_total
```

A quick run of both exercises:

```python
print(split_bill("100", 3))
print(sum(split_bill("1000.01", 7)))
print(raised_error_name(lambda: split_bill("10", 0)))
exact_invoice_total = invoice_total_decimal(sample_line_items)
float_invoice_total = invoice_total_float(float_line_items)
print(f"{exact_invoice_total=}")
print(f"{float_invoice_total=}")
print(f"{invoice_total_float([(2.75, 1)])=}  (a paisa short)")
```

```text
[Decimal('33.34'), Decimal('33.33'), Decimal('33.33')]
1000.01
ValueError
exact_invoice_total=Decimal('110.25')
float_invoice_total=110.21999999999998
invoice_total_float([(2.75, 1)])=3.24  (a paisa short)
```

The float invoice is three paise short and also carries representation error in the
last digits. Running the lab's checks against these solutions prints:

```text
Exercise 1 — split_bill
PASS  100 between 3
PASS  parts sum to the total
PASS  one part per person
PASS  parts differ by at most one paisa
PASS  every part has two decimal places
PASS  returns Decimal
PASS  zero people raises
7/7 checks passed

Exercise 2 — invoice calculator
PASS  empty invoice
PASS  one line, 18% GST
PASS  GST rounds half up
PASS  custom rate 5%
PASS  sample invoice
PASS  float: one line, 18% GST
PASS  float: round() loses a paisa on 2.75
PASS  float: sample invoice drifts from the exact total
8/8 checks passed
```

</details>

### Exercise 3 — predict the output

Work out each answer before you open it.

**Question 1.** What does this print?

```python
print(-7 // 2, 7 // -2, -7.0 // 2)
```

<details><summary>Answer</summary>

```text
-4 -4 -4.0
```

`//` floors towards negative infinity: −3.5 becomes −4 in both sign combinations.
With a float operand, the result is a float.

</details>

**Question 2.** What does this print?

```python
print(-7 % 2, 7 % -2, -7 % -2)
```

<details><summary>Answer</summary>

```text
1 -1 -1
```

The result of `%` takes the sign of the **divisor**, so that
`(a // b) * b + a % b == a`. For `-7 % 2`: `(-4) * 2 + 1 == -7`.

</details>

**Question 3.** What does this print?

```python
print(round(0.5), round(1.5), round(2.5), round(2.675, 2))
```

<details><summary>Answer</summary>

```text
0 2 2 2.67
```

Exact ties go to the even neighbour (banker's rounding), and `2.675` is stored as
`2.67499999…`, which is below the tie.

</details>

**Question 4.** What does this print?

```python
print(bool([0]), bool("0"), bool(0.0), bool(None), bool(" "), bool({}))
```

<details><summary>Answer</summary>

```text
True True False False True False
```

`[0]` is a non-empty list, and `"0"` and `" "` are non-empty strings, so all three
are truthy. `0.0`, `None` and the empty dict `{}` are falsy.

</details>

## Recap

| Concept | Takeaway | JavaScript equivalent |
| --- | --- | --- |
| `int` | Arbitrary precision, never overflows | `BigInt` |
| `/`, `//` | `/` is always float; `//` floors | `/`, `Math.floor` |
| `%` | Takes the divisor's sign | remainder `%` |
| Digit limit | Huge decimal text conversion is capped | — |
| `float` | IEEE 754; use `math.isclose`; `1/0` raises | `number` |
| `round()` | Half to even, plus representation error | `Math.round` (half up) |
| `Decimal` | Exact base 10; from strings; `quantize` | decimal.js, big.js |
| `Fraction` | Exact rationals; `limit_denominator` | — |
| `complex` | `3 + 4j`, `.real`, `.imag`, `cmath` | — |
| `bool` | Subclass of `int`; reject in int checks | `boolean` |
| `None` | The only null; `is None`; no `undefined` | `null` / `undefined` |
| Truthiness | Zeros and empty containers are falsy | `[]`, `{}` truthy |
| Conversion | Explicit; `ValueError`, `TypeError` | Implicit coercion |

## Further reading

- [Numeric types — `int`, `float`, `complex`](https://docs.python.org/3/library/stdtypes.html#numeric-types-int-float-complex)
- [Integer string conversion length limitation](https://docs.python.org/3/library/stdtypes.html#int-max-str-digits)
- [Floating-point arithmetic: issues and limitations](https://docs.python.org/3/tutorial/floatingpoint.html)
- [`math` — mathematical functions](https://docs.python.org/3/library/math.html)
- [`cmath` — functions for complex numbers](https://docs.python.org/3/library/cmath.html)
- [`decimal` — decimal fixed-point and floating-point arithmetic](https://docs.python.org/3/library/decimal.html)
- [`fractions` — rational numbers](https://docs.python.org/3/library/fractions.html)
- [Truth value testing](https://docs.python.org/3/library/stdtypes.html#truth-value-testing)
- [The `None` constant](https://docs.python.org/3/library/constants.html#None)
- [PEP 237 — Unifying long integers and integers](https://peps.python.org/pep-0237/)
- [PEP 285 — Adding a bool type](https://peps.python.org/pep-0285/)
- [PEP 327 — Decimal data type](https://peps.python.org/pep-0327/)
- [PEP 515 — Underscores in numeric literals](https://peps.python.org/pep-0515/)

[← Previous](unit-1-2-objects-names-and-mutability.md) · [Index](README.md) · [Next →](unit-1-4-text-and-binary-data-types.md)
