"""Unit 1.3 — Numeric and Boolean Data Types (with Lab 1.3)."""

from nbformat import NotebookNode

from nb_builder import code, md, predict_cells

UNIT_SETUP_SOURCE = '''
import cmath
import math
import sys
import timeit
from collections.abc import Callable
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal, getcontext, localcontext
from fractions import Fraction


def show_size(label: str, obj: object) -> None:
    """Print the shallow size in bytes, the type and the id of an object."""
    print(f"{label}: {sys.getsizeof(obj)} bytes, type={type(obj).__name__}, id={id(obj)}")


PAISE = Decimal("0.01")  # quantize() target for rupee amounts
print(f"{sys.version_info[:2]=}, {getcontext().prec=}")
'''


def _overview_cells() -> list[NotebookNode]:
    """Unit opener and 1.3.0."""
    return [
        md(
            """
            ## Unit 1.3 — Numeric and Boolean Data Types

            **Objectives**

            - Use `int`, `float`, `Decimal`, `Fraction` and `complex`, and choose the right one for
              money, measurements and exact ratios.
            - Predict `//`, `%` and `round()` results, including negative numbers and halves.
            - Explain why `bool` is an `int`, what `None` is, and which values are falsy.
            - Convert between types explicitly, knowing what raises.

            **JS bridge**

            | JavaScript concept | Python equivalent | The difference that bites |
            | --- | --- | --- |
            | `number` (one type) | `int` and `float` (two types) | `7 / 2 == 3.5`, but `7 // 2 == 3`; ints never lose precision |
            | `BigInt` (`10n`) | `int` | Every `int` is a big int; no suffix, no mixing errors |
            | `-7 % 2 === -1` | `-7 % 2 == 1` | `%` takes the sign of the divisor |
            | `Math.round(2.5) === 3` | `round(2.5) == 2` | Banker's rounding (round half to even) |
            | `1 / 0 === Infinity` | `1 / 0` raises `ZeroDivisionError` | Division by zero is an error |
            | `null` and `undefined` | `None` only | Missing dict keys raise `KeyError` |
            | `[]` and `{}` are truthy | `[]` and `{}` are falsy | Empty containers are false |
            | `1 + "1" === "11"` | `TypeError` | No implicit coercion |

            The next cell is this unit's setup.
            """
        ),
        code(UNIT_SETUP_SOURCE),
        md(
            """
            ### 1.3.0 Python's built-in data types at a glance

            Units 1.3–1.7 teach these types:

            | Category | Type | Mutable | Ordered | Hashable | Literal / constructor | Section |
            | --- | --- | --- | --- | --- | --- | --- |
            | Numeric | `int` | No | — | Yes | `42`, `0xff`, `1_000` | 1.3.1 |
            | Numeric | `float` | No | — | Yes | `3.14`, `1e-3` | 1.3.2 |
            | Numeric | `complex` | No | — | Yes | `3 + 4j` | 1.3.5 |
            | Numeric (stdlib) | `Decimal`, `Fraction` | No | — | Yes | `Decimal("0.1")`, `Fraction(1, 3)` | 1.3.3–1.3.4 |
            | Boolean | `bool` | No | — | Yes | `True`, `False` | 1.3.6 |
            | Null | `NoneType` | No | — | Yes | `None` | 1.3.7 |
            | Text | `str` | No | Yes | Yes | `"hi"`, `f"{name}"` | 1.4 |
            | Binary | `bytes` | No | Yes | Yes | `b"hi"` | 1.4.5 |
            | Binary | `bytearray` | Yes | Yes | No | `bytearray(b"hi")` | 1.4.5 |
            | Binary | `memoryview` | Depends on buffer | Yes | Read-only views only | `memoryview(data)` | 1.4.6 |
            | Sequence | `list` | Yes | Yes | No | `[1, 2]` | 1.5 |
            | Sequence | `tuple` | No | Yes | If all items are | `(1, 2)`, `(1,)` | 1.5.5 |
            | Sequence | `range` | No | Yes | Yes | `range(10)` | 1.5.7 |
            | Mapping | `dict` | Yes | Insertion order | No | `{"a": 1}` | 1.6 |
            | Mapping | `frozendict` (3.15) | No | Insertion order | If all values are | `frozendict(a=1)` | 1.6.5 |
            | Set | `set` | Yes | No | No | `{1, 2}`, `set()` | 1.6.6 |
            | Set | `frozenset` | No | No | Yes | `frozenset({1, 2})` | 1.6.6 |

            **Hashable** means `hash(obj)` works, so the object can be a dict key or a set member
            (1.6.2). The cell checks the *Hashable* column for one sample of each row, including the
            "it depends" cases. Unhashable objects raise `TypeError`, except a writable
            `memoryview`, which raises `ValueError`. `frozendict` is *new in 3.15*, so it is added
            only on 3.15+.
            """
        ),
        code(
            """
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
                except (TypeError, ValueError) as error:  # writable memoryview raises ValueError
                    verdict = f"unhashable ({type(error).__name__})"
                print(f"{label:<26} {verdict}")
            """
        ),
    ]


def _int_cells() -> list[NotebookNode]:
    """1.3.1 Integers."""
    return [
        md(
            """
            ### 1.3.1 Integers (`int`)

            Python's `int` has **arbitrary precision**: it grows to hold any value, so it never
            overflows. There is no separate BigInt type and no `n` suffix. JavaScript's `number`
            silently loses integer precision above `2**53`; Python does not.
            """
        ),
        code(
            """
            js_max_safe_integer = 2**53 - 1
            print(f"{js_max_safe_integer + 2=}  (exact; JS number would print ...992)")
            print(f"{2**100=}")
            print(f"{math.factorial(30)=}")
            print(f"{float(2**53 + 1) == 2**53=}  (float, like JS number, cannot hold it)")
            """
        ),
        md(
            """
            Internally CPython stores an `int` as an array of **30-bit digits** (`sys.int_info`), so
            its memory grows by 4 bytes for every 30 bits of magnitude. The growth table:
            """
        ),
        code(
            """
            print(f"{sys.int_info=}")
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
            """
        ),
        md(
            """
            **Literals.** Decimal, binary (`0b`), octal (`0o`, never a bare leading zero) and
            hexadecimal (`0x`). Underscores group digits for readability and are ignored.
            """
        ),
        code(
            """
            population_of_india = 1_428_627_663
            file_mode = 0o755
            flag_byte = 0b1010_0001
            brand_colour = 0xFF9933
            print(f"{population_of_india=}, {file_mode=}, {flag_byte=}, {brand_colour=}")
            try:
                eval("0755")
            except SyntaxError as error:
                print(f"{type(error).__name__}: {error.msg}")
            """
        ),
        md(
            """
            **Operators.**

            | Operator | Meaning | `17 op 5` |
            | --- | --- | --- |
            | `+ - *` | add, subtract, multiply | `22`, `12`, `85` |
            | `/` | true division, **always returns `float`** | `3.4` |
            | `//` | floor division: rounds **down** (towards −∞) | `3` |
            | `%` | modulo: the result takes the **divisor's** sign | `2` |
            | `**` | power | `1419857` |

            Floor means *down*, not *towards zero*, so `-7 // 2 == -4`. And `a == (a // b) * b + a % b`
            always holds, which forces `-7 % 2 == 1`. JavaScript's `%` is a *remainder* that keeps the
            dividend's sign (`-7 % 2 === -1`).
            """
        ),
        code(
            """
            print(f"{17 + 5=}, {17 - 5=}, {17 * 5=}, {17 ** 5=}")
            print(f"{17 / 5=}, {10 / 2=}  (always float)")
            print(f"{17 // 5=}, {17 % 5=}")
            print(f"{-7 // 2=}, {-7 % 2=}  (JS: Math.trunc gives -3, % gives -1)")
            print(f"{7 // -2=}, {7 % -2=}")
            dividend, divisor = -7, 2
            print(f"{(dividend // divisor) * divisor + dividend % divisor == dividend=}")
            print(f"{math.fmod(-7, 2)=}  (JS-style remainder, when you need it)")
            """
        ),
        md(
            """
            **Functions and methods.** Each gets its own demo below.

            | Name | What it does |
            | --- | --- |
            | `abs(x)` | absolute value |
            | `divmod(a, b)` | `(a // b, a % b)` in one call |
            | `pow(base, exp, mod)` | modular power, fast even for huge exponents |
            | `round(x, ndigits)` | rounds to a multiple of `10**-ndigits` (round half to even) |
            | `int.bit_length()` | bits needed, ignoring the sign |
            | `int.bit_count()` | number of 1 bits (*popcount*) |
            | `int.to_bytes` / `int.from_bytes` | convert to and from raw bytes |
            | `bin` / `oct` / `hex` | text in base 2 / 8 / 16 |
            | `int(text, base)` | parse text in any base 2–36 |
            | `int.is_integer()` | always `True`; exists so code can treat `int` and `float` alike |

            `abs` works on every numeric type.
            """
        ),
        code(
            """
            account_balance_change = -2_500
            print(f"{abs(account_balance_change)=}, {abs(-3.5)=}, {abs(Decimal('-0.10'))=}")
            """
        ),
        md(
            """
            `divmod` returns quotient and remainder together, e.g. to split minutes into hours.
            """
        ),
        code(
            """
            hours, minutes = divmod(135, 60)
            print(f"{hours=}, {minutes=}")
            print(f"{divmod(-7, 2)=}")
            """
        ),
        md(
            """
            Three-argument `pow(base, exp, mod)` computes `base ** exp % mod` without building the
            huge intermediate number. It is the core of RSA. With `exp=-1` it returns the modular
            inverse (3.8+).
            """
        ),
        code(
            """
            print(f"{pow(2, 10)=}")
            print(f"{pow(7, 10**18, 13)=}  (instant; 7 ** 10**18 would never finish)")
            print(f"{pow(3, -1, 11)=}  (3 * 4 % 11 == 1)")
            """
        ),
        md(
            """
            `round(int, ndigits)` with a **negative** `ndigits` rounds to tens, hundreds, …. Ties
            go to the even neighbour, so `1250` becomes `1200`.
            """
        ),
        code(
            """
            print(f"{round(1_234, -2)=}, {round(1_250, -2)=}, {round(1_350, -2)=}")
            print(f"{round(7)=}, {type(round(7.6)).__name__=}  (round() with no ndigits returns int)")
            """
        ),
        md(
            """
            `bit_length()` is the number of bits needed for the magnitude; `bit_count()` counts the
            ones (*new in 3.10*).
            """
        ),
        code(
            """
            sample_number = 0b1011_0000
            print(f"{sample_number=}, {sample_number.bit_length()=}, {(-sample_number).bit_length()=}")
            print(f"{sample_number.bit_count()=}, {(255).bit_count()=}")
            """
        ),
        md(
            """
            `to_bytes(length, byteorder, signed=...)` and `int.from_bytes` convert between an `int`
            and its raw bytes, e.g. for binary file formats and network protocols. Both default to
            big-endian (3.11+).
            """
        ),
        code(
            """
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
            """
        ),
        md(
            """
            `bin`, `oct` and `hex` return prefixed strings. `format()` with `b`, `o`, `x` does the
            same without the prefix, and can pad.
            """
        ),
        code(
            """
            print(f"{bin(10)=}, {oct(493)=}, {hex(16_750_899)=}")
            print(f"{format(10, '08b')=}, {format(255, 'X')=}")
            """
        ),
        md(
            """
            `int(text, base)` parses text in bases 2 to 36. Base `0` reads the prefix from the text.
            Surrounding whitespace and underscores between digits are allowed.
            """
        ),
        code(
            """
            print(f"{int('ff', 16)=}, {int('1010', 2)=}, {int('z', 36)=}")
            print(f"{int('0x1F', 0)=}, {int('0b101', 0)=}")
            print(f"{int('  1_000  ')=}")
            """
        ),
        md(
            """
            `int.is_integer()` (*new in 3.12*) always returns `True`. It exists so code that receives
            "a number" can ask the question without checking the type first.
            """
        ),
        code(
            """
            for quantity in (3, 3.0, 3.5):
                print(f"{quantity!r:>4}: {quantity.is_integer()=}")
            """
        ),
        md(
            """
            **Bitwise operators** work on the binary digits. Their classic use is a set of on/off
            flags packed into one integer, such as Unix file permissions. (Phase 2 shows
            `enum.Flag`, the type-safe version.)

            | Operator | Meaning | Use with flags |
            | --- | --- | --- |
            | `a \\| b` | OR | grant a permission |
            | `a & b` | AND | test a permission |
            | `a & ~b` | AND NOT | revoke a permission |
            | `a ^ b` | XOR | toggle a permission |
            | `a << n`, `a >> n` | shift left / right | build masks, multiply / divide by `2**n` |
            """
        ),
        code(
            """
            READ, WRITE, EXECUTE = 0b100, 0b010, 0b001

            permissions = READ | WRITE
            print(f"{bin(permissions)=}, can write: {bool(permissions & WRITE)}")
            permissions &= ~WRITE
            print(f"{bin(permissions)=}, can write: {bool(permissions & WRITE)}")
            permissions ^= EXECUTE
            print(f"{bin(permissions)=}, can execute: {bool(permissions & EXECUTE)}")
            print(f"{~5=}  (~x == -x - 1: Python ints behave as infinite two's complement)")
            print(f"{1 << 10=}, {1024 >> 3=}")
            owner_group_other = (0o7 << 6) | (0o5 << 3) | 0o5
            print(f"{oct(owner_group_other)=}")
            """
        ),
        md(
            """
            **The 4300-digit limit (3.11+, also back-ported to security releases).** Converting a
            huge `int` to or from **decimal text** takes time quadratic in the number of digits. A
            web service that ran `int(request_body)` could be stalled by a megabyte of digits
            (CVE-2020-10735). Python therefore refuses decimal conversions above 4300 digits by
            default. Binary bases (`hex`, `bin`) are linear and are not limited. Raise the limit
            only for trusted data, and put it back afterwards.
            """
        ),
        code(
            """
            huge_number = 10**5000
            try:
                str(huge_number)
            except ValueError as error:
                print(f"{type(error).__name__}: {str(error)[:70]}...")
            print(f"{len(hex(huge_number))=}  (hex is not limited)")

            default_limit = sys.get_int_max_str_digits()
            sys.set_int_max_str_digits(10_000)
            try:
                print(f"{len(str(huge_number))=}")
            finally:
                sys.set_int_max_str_digits(default_limit)
            print(f"{sys.get_int_max_str_digits()=}")
            """
        ),
    ]


def _float_cells() -> list[NotebookNode]:
    """1.3.2 Floating point."""
    return [
        md(
            """
            ### 1.3.2 Floating point (`float`)

            A Python `float` is an **IEEE 754 double** (64 bits), exactly the same as a JavaScript
            `number`. Most decimal fractions such as `0.1` have no exact binary form, so they are
            stored as the nearest double, and the errors show up in arithmetic.
            `Decimal(some_float)` reveals the value that is really stored. Compare floats with
            `math.isclose`, never with `==`.
            """
        ),
        code(
            """
            print(f"{0.1 + 0.2=}")
            print(f"{0.1 + 0.2 == 0.3=}")
            print(f"{Decimal(0.1)=}")
            print(f"{math.isclose(0.1 + 0.2, 0.3)=}")
            print(f"{math.isclose(1e-12, 0.0)=}  (relative tolerance fails near 0)")
            print(f"{math.isclose(1e-12, 0.0, abs_tol=1e-9)=}")
            """
        ),
        md(
            """
            **`round()` surprises.** Two effects combine:

            1. **Banker's rounding:** an exact tie goes to the **even** neighbour, so `round(2.5) == 2`.
               This avoids an upward bias when many values are rounded. JS `Math.round(2.5)` is `3`.
            2. **Representation error:** `2.675` is really stored as `2.67499999…`, so it is not a
               tie at all and rounds *down*.
            """
        ),
        code(
            """
            print(f"{round(0.5)=}, {round(1.5)=}, {round(2.5)=}, {round(-2.5)=}")
            print(f"{round(2.675, 2)=}")
            print(f"{Decimal(2.675)=}")
            """
        ),
        md(
            """
            **Special values.** `inf`, `-inf` and `nan` ("not a number") come from `float("inf")` /
            `math.inf` / `math.nan` or from overflowing operations. `nan` is not equal to anything,
            not even itself, so test it with `math.isnan`. Unlike JS, `1 / 0` raises instead of
            returning `Infinity`.
            """
        ),
        code(
            """
            positive_infinity = float("inf")
            not_a_number = float("nan")
            print(f"{positive_infinity > 10**308=}, {-math.inf < -1e308=}")
            print(f"{positive_infinity - positive_infinity=}")
            print(f"{not_a_number == not_a_number=}, {not_a_number != not_a_number=}")
            print(f"{math.isnan(not_a_number)=}, {math.isinf(-math.inf)=}, {math.isfinite(1e308)=}")
            print(f"{1e308 * 10=}")
            try:
                ratio = 1 / 0
            except ZeroDivisionError as error:
                print(f"{type(error).__name__}: {error}")
            """
        ),
        md(
            """
            **`float` methods.** `as_integer_ratio()` returns the exact fraction the double stores.
            For `0.1` that is not `1/10`.
            """
        ),
        code(
            """
            print(f"{(0.75).as_integer_ratio()=}")
            print(f"{(0.1).as_integer_ratio()=}")
            """
        ),
        md(
            """
            `is_integer()` tells whether the float has no fractional part.
            """
        ),
        code(
            """
            print(f"{(4.0).is_integer()=}, {(4.5).is_integer()=}, {(1e20).is_integer()=}")
            """
        ),
        md(
            """
            `hex()` and `float.fromhex()` write and read the exact bits in hexadecimal, with no
            decimal rounding. Use them to store or send a float losslessly.
            """
        ),
        code(
            """
            exact_text = (0.1).hex()
            print(f"{exact_text=}")
            print(f"{float.fromhex(exact_text) == 0.1=}")
            """
        ),
        md(
            """
            `sys.float_info` describes the platform's doubles. `epsilon` is the gap between `1.0`
            and the next float, and `dig` is how many decimal digits are always kept.
            """
        ),
        code(
            """
            print(f"{sys.float_info.max=}")
            print(f"{sys.float_info.min=}")
            print(f"{sys.float_info.epsilon=}")
            print(f"{sys.float_info.dig=}, {sys.float_info.mant_dig=}")
            print(f"{1.0 + sys.float_info.epsilon > 1.0=}, {1.0 + sys.float_info.epsilon / 2 > 1.0=}")
            """
        ),
        md(
            """
            **Useful `math` functions.** `floor` rounds down, `ceil` rounds up, `trunc` drops the
            fraction (towards zero, like `int()`). They differ only for negative numbers, and all
            three return `int`.
            """
        ),
        code(
            """
            for value in (3.7, -3.7):
                rounded_values = (math.floor(value), math.ceil(value), math.trunc(value), int(value))
                print(f"{value:>5}: floor, ceil, trunc, int = {rounded_values}")
            """
        ),
        md(
            """
            `math.sqrt` returns a float and rejects negatives (use `cmath`, 1.3.5). `math.isqrt`
            gives the exact integer square root of any `int`.
            """
        ),
        code(
            """
            print(f"{math.sqrt(2)=}, {math.isqrt(10**20 + 1)=}")
            try:
                math.sqrt(-1)
            except ValueError as error:
                print(f"{type(error).__name__}: {error}")
            """
        ),
        md(
            """
            `math.fsum` adds floats while tracking every lost low-order bit, so the result is
            correctly rounded. A plain `+=` loop (what JS `reduce` does) accumulates error.
            *Changed in 3.12:* `sum()` of floats uses compensated (Neumaier) summation, which fixes
            the common cases, but `fsum` is still the exact one when values of wildly different
            sizes cancel.
            """
        ),
        code(
            """
            ten_dimes = [0.1] * 10
            loop_total = 0.0
            for dime in ten_dimes:
                loop_total += dime
            print(f"{loop_total=}  (naive left-to-right)")
            print(f"{sum(ten_dimes)=}, {math.fsum(ten_dimes)=}")

            mixed_magnitudes = [1e100, 1.0, -1e100, 1e-100, 1e50, -1.0, -1e50]
            print(f"{sum(mixed_magnitudes)=}, {math.fsum(mixed_magnitudes)=}")
            """
        ),
        md(
            """
            `math.prod` multiplies an iterable, the way `sum` adds one (3.8+).
            """
        ),
        code(
            """
            print(f"{math.prod([2, 3, 7])=}")
            print(f"{math.prod([1.05] * 3)=}  (three years of 5% growth)")
            """
        ),
        md(
            """
            `math.pi`, `math.e` (and `math.tau`, `math.inf`, `math.nan`) are float constants.
            """
        ),
        code(
            """
            circle_radius_in_metres = 2.5
            print(f"{math.pi=}, {math.e=}, {math.tau == 2 * math.pi=}")
            print(f"{math.pi * circle_radius_in_metres**2=}")
            """
        ),
    ]


def _decimal_fraction_complex_cells() -> list[NotebookNode]:
    """1.3.3 Decimal, 1.3.4 Fraction, 1.3.5 complex."""
    return [
        md(
            """
            ### 1.3.3 Exact decimals (`decimal.Decimal`)

            `Decimal` stores numbers in base 10, so `0.1` is exactly one tenth. That is what money
            needs. **Always construct it from a string (or an `int`), never from a float**: a float
            argument copies the float's representation error.
            """
        ),
        code(
            """
            print(f"{Decimal('0.1')=}")
            print(f"{Decimal(0.1)=}")
            print(f"{Decimal('0.1') + Decimal('0.2') == Decimal('0.3')=}")
            print(f"{Decimal(25)=}, {Decimal('1.50')=}  (trailing zeros are kept)")
            """
        ),
        md(
            """
            **Arithmetic.** `Decimal` supports the usual operators and mixes with `int`, but not
            with `float` (that would bring the inexactness back). Results are rounded to the
            **context precision**: 28 significant digits by default. `localcontext()` changes the
            precision (or the rounding) only inside a `with` block.
            """
        ),
        code(
            """
            unit_price = Decimal("19.99")
            print(f"{unit_price * 3=}, {unit_price - 5=}, {unit_price / 4=}")
            print(f"{Decimal(1) / Decimal(7)=}")
            with localcontext() as local_context:
                local_context.prec = 6
                print(f"inside localcontext: {Decimal(1) / Decimal(7)=}")
            print(f"after the block: {getcontext().prec=}")
            try:
                unit_price + 0.5
            except TypeError as error:
                print(f"{type(error).__name__}: {error}")
            """
        ),
        md(
            """
            **`quantize`** rounds to a fixed exponent, e.g. `Decimal("0.01")` for paise. The
            rounding mode is explicit:

            | Mode | Ties go… | Typical use |
            | --- | --- | --- |
            | `ROUND_HALF_UP` | away from zero (`2.675 → 2.68`) | invoices and tax, as taught in school |
            | `ROUND_HALF_EVEN` | to the even digit (`2.665 → 2.66`) | statistics, the `Decimal` default |
            """
        ),
        code(
            """
            print(f"{'value':>7} {'HALF_UP':>8} {'HALF_EVEN':>10}")
            for amount_text in ["2.675", "2.665", "0.125", "-1.005"]:
                amount = Decimal(amount_text)
                half_up = amount.quantize(PAISE, rounding=ROUND_HALF_UP)
                half_even = amount.quantize(PAISE, rounding=ROUND_HALF_EVEN)
                print(f"{amount_text:>7} {half_up!s:>8} {half_even!s:>10}")
            """
        ),
        md(
            """
            **Money: an 18% GST demo.** One thousand orders of ₹99.99 each, with GST computed and
            rounded per order. Float accumulates representation error across the additions;
            `Decimal` is exact to the paisa.
            """
        ),
        code(
            """
            order_count = 1_000

            float_grand_total = 0.0
            for _ in range(order_count):
                float_grand_total += 99.99 + round(99.99 * 0.18, 2)

            decimal_grand_total = Decimal("0.00")
            for _ in range(order_count):
                gst = (Decimal("99.99") * Decimal("0.18")).quantize(PAISE, rounding=ROUND_HALF_UP)
                decimal_grand_total += Decimal("99.99") + gst

            print(f"{float_grand_total=}")
            print(f"{decimal_grand_total=}")
            """
        ),
        md(
            """
            **Performance trade-off.** `float` arithmetic runs in hardware; `Decimal` is software
            (C-accelerated `_decimal`, but still slower). The usual pattern is `Decimal` (or
            integer paise) for money and `float` for measurements and science. Timings vary by
            machine; the ratio is what matters.
            """
        ),
        code(
            """
            float_operands = {"a": 99.99, "b": 0.18, "c": 1.5}
            decimal_operands = {"a": Decimal("99.99"), "b": Decimal("0.18"), "c": Decimal("1.5")}
            float_seconds = timeit.timeit("a * b + c", globals=float_operands, number=200_000)
            decimal_seconds = timeit.timeit("a * b + c", globals=decimal_operands, number=200_000)
            slowdown = decimal_seconds / float_seconds
            print(f"float:   {float_seconds * 1000:.1f} ms")
            print(f"Decimal: {decimal_seconds * 1000:.1f} ms  (about {slowdown:.0f}x slower)")
            """
        ),
        md(
            """
            ### 1.3.4 Rational numbers (`fractions.Fraction`)

            A `Fraction` is an exact numerator/denominator pair, always kept in lowest terms. One
            third really is one third, so `Fraction(1, 3) * 3 == 1`.
            """
        ),
        code(
            """
            one_third = Fraction(1, 3)
            print(f"{one_third * 3 == 1=}, {one_third * 3=}")
            print(f"{Fraction(6, 8)=}  (reduced automatically)")
            print(f"{one_third + Fraction(1, 6)=}")
            print(f"{1 / 3 * 3 == 1=}  (float happens to round back here, but not in general)")
            """
        ),
        md(
            """
            Build a `Fraction` from a **string** for the exact value you typed. Building it from a
            float shows the float's exact binary value. `limit_denominator(max_denominator)` finds
            the closest fraction with a small denominator, which recovers the intended value.
            """
        ),
        code(
            """
            print(f"{Fraction('3/7')=}, {Fraction('0.125')=}, {Fraction('1.5e-2')=}")
            print(f"{Fraction(0.1)=}")
            print(f"{Fraction(0.1).limit_denominator(1000)=}")
            print(f"{Fraction(math.pi).limit_denominator(1000)=}")
            """
        ),
        md(
            """
            ### 1.3.5 Complex numbers (`complex`)

            Python has complex numbers built in: write the imaginary part with a `j` suffix. They
            are used in signal processing and electrical engineering; you will rarely need them for
            web work.
            """
        ),
        code(
            """
            impedance = 3 + 4j
            print(f"{impedance=}, {type(impedance).__name__=}")
            print(f"{impedance.real=}, {impedance.imag=}")
            print(f"{abs(impedance)=}  (magnitude)")
            print(f"{impedance.conjugate()=}, {impedance * impedance.conjugate()=}")
            print(f"{complex(3, 4) == impedance=}")
            """
        ),
        md(
            """
            `cmath` is the complex-number version of `math`: its functions accept negative and
            complex inputs.
            """
        ),
        code(
            """
            print(f"{cmath.sqrt(-1)=}")
            print(f"{cmath.phase(1j)=}  (pi / 2)")
            print(f"{cmath.polar(impedance)=}")
            print(f"{cmath.rect(5, 0.9272952180016122)=}")
            """
        ),
    ]


def _bool_none_cells() -> list[NotebookNode]:
    """1.3.6 bool, 1.3.7 None, 1.3.8 truthiness, 1.3.9 conversion."""
    return [
        md(
            """
            ### 1.3.6 Booleans (`bool`)

            `bool` is a **subclass of `int`**: `True` is `1` and `False` is `0` in arithmetic. A
            useful consequence: `sum(flags)` counts the `True` values.
            """
        ),
        code(
            """
            print(f"{issubclass(bool, int)=}")
            print(f"{True + True=}, {True * 10=}, {True == 1=}")
            order_is_paid = [True, False, True, True]
            print(f"{sum(order_is_paid)=} paid orders")
            """
        ),
        md(
            """
            **The validation trap.** Because `True` *is* an `int`, `isinstance(True, int)` is
            `True`, and a check meant to accept quantities also accepts booleans. Reject `bool`
            explicitly.
            """
        ),
        code(
            '''
            def is_valid_quantity_naive(quantity: object) -> bool:
                """Accept positive ints (buggy: also accepts True)."""
                return isinstance(quantity, int) and quantity > 0


            def is_valid_quantity(quantity: object) -> bool:
                """Accept positive ints, rejecting bool."""
                return isinstance(quantity, int) and not isinstance(quantity, bool) and quantity > 0


            for candidate in (3, True, 0, 2.0):
                naive_verdict = is_valid_quantity_naive(candidate)
                print(f"{candidate!r:>5}: naive={naive_verdict}, fixed={is_valid_quantity(candidate)}")
            '''
        ),
        md(
            """
            `bool(x)` converts any value using the truthiness rules (1.3.8). Watch out for strings:
            any non-empty string is `True`, including `"False"` and `"0"`.
            """
        ),
        code(
            """
            print(f"{bool(0)=}, {bool(42)=}, {bool('')=}, {bool('False')=}, {bool('0')=}")
            form_value = "false"
            print(f"{form_value.strip().lower() in {'true', '1', 'yes'}=}  (parse text explicitly)")
            """
        ),
        md(
            """
            ### 1.3.7 The null value (`None`)

            `None` is the only instance of `NoneType`, so every `None` is the same object; check it
            with `is None`. A function without a `return` (or with a bare `return`) returns `None`.
            """
        ),
        code(
            '''
            def log_message(message: str) -> None:
                """Print a message; no return statement."""
                print(f"log: {message}")


            result = log_message("order created")
            print(f"{result is None=}")
            print(f"{type(None).__name__=}, {type(None)() is None=}")
            '''
        ),
        md(
            """
            > **JS bridge:** Python has **no `undefined`**. An unassigned name raises `NameError`,
            > a missing attribute raises `AttributeError`, and a missing dict key raises `KeyError`.
            > `dict.get(key)` returns `None` (or a default) when you want JS-like behaviour.
            """
        ),
        code(
            """
            customer = {"name": "Asha", "city": "Pune"}
            try:
                customer["phone"]
            except KeyError as error:
                print(f"{type(error).__name__}: {error}")
            print(f"{customer.get('phone')=}, {customer.get('phone', 'not given')=}")
            """
        ),
        md(
            """
            ### 1.3.8 Truthiness

            Every object is true or false in an `if`, `while`, `and`, `or` or `not`. These values are
            **falsy**; everything else is truthy:

            | Falsy value | Type |
            | --- | --- |
            | `None` | `NoneType` |
            | `False` | `bool` |
            | `0`, `0.0`, `0j` | `int`, `float`, `complex` |
            | `Decimal(0)`, `Fraction(0)` | `Decimal`, `Fraction` |
            | `""`, `b""` | `str`, `bytes` |
            | `[]`, `()`, `{}` | `list`, `tuple`, `dict` |
            | `set()`, `range(0)` | `set`, `range` |
            | an object whose `__bool__` returns `False`, or whose `__len__` returns `0` | user classes |

            The cell evaluates every row.
            """
        ),
        code(
            """
            falsy_candidates = [None, False, 0, 0.0, 0j, Decimal(0), Fraction(0)]
            falsy_candidates += ["", b"", [], (), {}, set(), range(0)]
            for candidate in falsy_candidates:
                print(f"{candidate!r:<14} -> {bool(candidate)}")
            """
        ),
        md(
            """
            User classes decide with `__bool__`, or, if it is missing, with `__len__` (zero length
            is false). With neither, every instance is truthy.
            """
        ),
        code(
            '''
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
            '''
        ),
        md(
            """
            **Differences from JavaScript**

            | Value | JavaScript | Python |
            | --- | --- | --- |
            | `[]`, `{}` | truthy | **falsy** |
            | `"0"`, `" "` | truthy | truthy |
            | `NaN` | falsy | **truthy** (`nan` is a non-zero float) |
            | `0n` / `0` | falsy | falsy |
            | `document.all` | falsy (!) | — |

            **When to prefer `is not None`.** `if value:` treats `0`, `""` and `[]` the same as a
            missing value. When `0` is a legitimate input, test for `None` explicitly.
            """
        ),
        code(
            '''
            def price_after_discount_buggy(price: int, discount: int | None = None) -> int:
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
            '''
        ),
        md(
            """
            ### 1.3.9 Type conversion

            Conversions are always **explicit**: call the type. They raise `ValueError` when the
            text is not a valid literal for that type. Note that `int("3.5")` fails: convert to
            `float` first if decimals are allowed. `int(3.99)` truncates.
            """
        ),
        code(
            """
            print(f"{int('42')=}, {int(' -7 ')=}, {int(3.99)=}, {int(True)=}")
            print(f"{float('3.5')=}, {float('1e3')=}, {float('nan')=}, {float(7)=}")
            print(f"{str(42)=}, {str(3.5)=}, {str(None)=}")
            print(f"{bool(1)=}, {bool('')=}")
            print(f"{complex('3+4j')=}, {complex(2)=}")
            print(f"{int(float('3.5'))=}")
            """
        ),
        md(
            """
            Each failing conversion raises `ValueError` with a message that quotes the bad text.
            """
        ),
        code(
            """
            for converter, bad_text in [(int, "3.5"), (int, "12abc"), (float, "abc"), (complex, "3 + 4j")]:
                try:
                    converter(bad_text)
                except ValueError as error:
                    print(f"{converter.__name__}({bad_text!r}) -> {type(error).__name__}: {error}")
            """
        ),
        md(
            """
            **No implicit coercion.** JavaScript converts silently (`1 + "1" === "11"`,
            `1 == "1"` is `true`). Python raises `TypeError` for mixed `+` and returns `False` for
            `==` between unrelated types. Numeric types do mix with each other (`1 + 2.5`, `1 == 1.0`).
            """
        ),
        code(
            """
            try:
                mixed_total = 1 + "1"
            except TypeError as error:
                print(f"{type(error).__name__}: {error}")
            print(f"{1 == '1'=}")
            print(f"{1 + int('1')=}, {str(1) + '1'=}")
            print(f"{1 + 2.5=}, {1 == 1.0 == Decimal(1) == Fraction(1)=}")
            """
        ),
    ]


def _under_the_hood_cells() -> list[NotebookNode]:
    """Under the hood for Unit 1.3."""
    return [
        md(
            """
            #### Under the hood: object sizes and the int digit formula

            Every number is a full object with a header, so even `True` costs bytes. For `int`,
            the size is a fixed header plus 4 bytes per 30-bit digit; the cell checks the formula
            against `sys.getsizeof` for growing values. `show_size` (shared setup) prints a few
            other numeric types for comparison.
            """
        ),
        code(
            """
            int_header_bytes = sys.getsizeof(1) - sys.int_info.sizeof_digit
            for exponent in (10, 100, 1_000):
                number = 2**exponent
                digit_count = -(-number.bit_length() // sys.int_info.bits_per_digit)  # ceiling division
                predicted_bytes = int_header_bytes + digit_count * sys.int_info.sizeof_digit
                actual_bytes = sys.getsizeof(number)
                print(f"2**{exponent:<5} digits={digit_count:<3} {predicted_bytes=:<4} {actual_bytes=}")

            show_size("float", 1.5)
            show_size("complex", 1 + 2j)
            show_size("Decimal", Decimal("1.5"))
            show_size("Fraction", Fraction(1, 2))
            show_size("True", True)
            """
        ),
    ]


def _lab_cells() -> list[NotebookNode]:
    """Lab 1.3."""
    return [
        md(
            """
            ### Lab 1.3

            Three exercises: an exact bill splitter, an invoice calculator (with a float version to
            show drift), and predict-the-output questions. For each coding exercise, replace the
            `raise NotImplementedError` in the stub, then run the check cell. Until then the checks
            print FAIL with `NotImplementedError`; that is expected.

            #### Exercise 1 — `split_bill`

            Write `split_bill(total_amount: str, people_count: int) -> list[Decimal]`:

            - Split the total (a rupee amount as text, e.g. `"100"` or `"1000.01"`) into
              `people_count` parts **exact to the paisa**: every part has two decimal places and
              the parts sum to exactly the total.
            - Parts differ by at most one paisa; the leftover paise go to the **first** people.
              `split_bill("100", 3) == [Decimal("33.34"), Decimal("33.33"), Decimal("33.33")]`.
            - Raise `ValueError` when `people_count` is less than 1.

            *Hint:* work in whole paise with `divmod`.
            """
        ),
        code(
            '''
            def split_bill(total_amount: str, people_count: int) -> list[Decimal]:
                """Split a rupee amount into people_count parts that sum exactly to the total."""
                raise NotImplementedError("Lab 1.3: implement split_bill()")
            '''
        ),
        md(
            """
            The check cell defines `raised_error_name(thunk)`, which returns the name of the
            exception a call raises (or `"no error"`), so error cases fit the
            `(label, thunk, expected)` format of `run_checks`.
            """
        ),
        code(
            '''
            def raised_error_name(thunk: Callable[[], object]) -> str:
                """Call thunk and return the name of the exception it raised, or "no error"."""
                try:
                    thunk()
                except Exception as error:
                    return type(error).__name__
                return "no error"


            run_checks(
                [
                    (
                        "100 between 3",
                        lambda: split_bill("100", 3),
                        [Decimal("33.34"), Decimal("33.33"), Decimal("33.33")],
                    ),
                    ("parts sum to the total", lambda: sum(split_bill("1000.01", 7)), Decimal("1000.01")),
                    ("one part per person", lambda: len(split_bill("10", 4)), 4),
                    (
                        "parts differ by at most one paisa",
                        lambda: max(split_bill("0.05", 3)) - min(split_bill("0.05", 3)) <= PAISE,
                        True,
                    ),
                    (
                        "every part has two decimal places",
                        lambda: {part.as_tuple().exponent for part in split_bill("90", 4)},
                        {-2},
                    ),
                    ("returns Decimal", lambda: type(split_bill("1", 1)[0]).__name__, "Decimal"),
                    (
                        "zero people raises",
                        lambda: raised_error_name(lambda: split_bill("10", 0)),
                        "ValueError",
                    ),
                ]
            )
            '''
        ),
        md(
            """
            #### Exercise 2 — invoice calculator

            An invoice is a list of `(unit_price, quantity)` line items. For **each line**:
            net amount = unit price × quantity, GST = net amount × rate, **rounded to paise per
            line**. The invoice total is the sum of every line's net amount plus its GST.

            1. `invoice_total_decimal(line_items: list[tuple[str, int]], gst_rate_percent: str = "18") -> Decimal`:
               prices and rate are strings, GST is rounded with `quantize(PAISE, rounding=ROUND_HALF_UP)`,
               and the total is returned with two decimal places.
            2. `invoice_total_float(line_items: list[tuple[float, int]], gst_rate_percent: float = 18.0) -> float`:
               the same calculation with floats and `round(gst, 2)`. Do **not** round the final
               total, so the drift stays visible.
            """
        ),
        code(
            '''
            def invoice_total_decimal(
                line_items: list[tuple[str, int]], gst_rate_percent: str = "18"
            ) -> Decimal:
                """Return net + per-line GST (ROUND_HALF_UP to paise) for all line items."""
                raise NotImplementedError("Lab 1.3: implement invoice_total_decimal()")


            def invoice_total_float(
                line_items: list[tuple[float, int]], gst_rate_percent: float = 18.0
            ) -> float:
                """Return the same total computed with float and round()."""
                raise NotImplementedError("Lab 1.3: implement invoice_total_float()")
            '''
        ),
        md(
            """
            The checks include a line of ₹2.75: its GST is exactly ₹0.495, which `ROUND_HALF_UP`
            makes ₹0.50. The float `2.75 * 18 / 100` is stored just *below* 0.495, so `round()`
            gives ₹0.49.
            """
        ),
        code(
            """
            sample_line_items = [
                ("19.99", 3),
                ("0.10", 7),
                ("2.75", 1),
                ("12.25", 2),
                ("0.25", 1),
                ("5.25", 1),
            ]
            float_line_items = [(float(price), quantity) for price, quantity in sample_line_items]

            run_checks(
                [
                    ("empty invoice", lambda: invoice_total_decimal([]), Decimal("0.00")),
                    ("one line, 18% GST", lambda: invoice_total_decimal([("100", 2)]), Decimal("236.00")),
                    ("GST rounds half up", lambda: invoice_total_decimal([("1.25", 1)]), Decimal("1.48")),
                    ("custom rate 5%", lambda: invoice_total_decimal([("10.10", 1)], "5"), Decimal("10.61")),
                    ("sample invoice", lambda: invoice_total_decimal(sample_line_items), Decimal("110.25")),
                    ("float: one line, 18% GST", lambda: invoice_total_float([(100.0, 2)]), 236.0),
                    ("float: round() loses a paisa on 2.75", lambda: invoice_total_float([(2.75, 1)]), 3.24),
                    (
                        "float: sample invoice drifts from the exact total",
                        lambda: (
                            invoice_total_float(float_line_items)
                            != float(invoice_total_decimal(sample_line_items))
                        ),
                        True,
                    ),
                ]
            )
            """
        ),
        md(
            """
            Once both functions work, this cell shows the drift side by side. Until then it prints
            a reminder.
            """
        ),
        code(
            """
            try:
                exact_invoice_total = invoice_total_decimal(sample_line_items)
                float_invoice_total = invoice_total_float(float_line_items)
            except NotImplementedError as error:
                print(f"Not yet: {error}")
            else:
                print(f"{exact_invoice_total=}")
                print(f"{float_invoice_total=}")
                print(f"difference: {Decimal(float_invoice_total) - exact_invoice_total:.17f}")
            """
        ),
        md("#### Exercise 3 — predict the output"),
        *predict_cells(
            snippet="""
            print(-7 // 2, 7 // -2, -7.0 // 2)
            """,
            answer="""
            `-4 -4 -4.0`. `//` floors towards negative infinity: −3.5 becomes −4 in both sign
            combinations. With a float operand the result is a float.
            """,
            proof="""
            print(-7 // 2, 7 // -2, -7.0 // 2)
            """,
        ),
        *predict_cells(
            snippet="""
            print(-7 % 2, 7 % -2, -7 % -2)
            """,
            answer="""
            `1 -1 -1`. The result of `%` takes the sign of the **divisor**, so that
            `(a // b) * b + a % b == a`. For `-7 % 2`: `(-4) * 2 + 1 == -7`.
            """,
            proof="""
            print(-7 % 2, 7 % -2, -7 % -2)
            """,
        ),
        *predict_cells(
            snippet="""
            print(round(0.5), round(1.5), round(2.5), round(2.675, 2))
            """,
            answer="""
            `0 2 2 2.67`. Exact ties go to the even neighbour (banker's rounding), and `2.675` is
            stored as `2.67499999…`, which is below the tie.
            """,
            proof="""
            print(round(0.5), round(1.5), round(2.5), round(2.675, 2))
            """,
        ),
        *predict_cells(
            snippet="""
            print(bool([0]), bool("0"), bool(0.0), bool(None), bool(" "), bool({}))
            """,
            answer="""
            `True True False False True False`. `[0]` is a non-empty list, and `"0"` and `" "` are
            non-empty strings, so all three are truthy. `0.0`, `None` and the empty dict `{}` are
            falsy.
            """,
            proof="""
            print(bool([0]), bool("0"), bool(0.0), bool(None), bool(" "), bool({}))
            """,
        ),
    ]


def _recap_cells() -> list[NotebookNode]:
    """Recap for Unit 1.3."""
    return [
        md(
            """
            ### Recap — Unit 1.3

            | Concept | One-line takeaway | JS equivalent |
            | --- | --- | --- |
            | `int` | Arbitrary precision, 30-bit digits, never overflows | `BigInt` |
            | `/`, `//`, `%` | `/` is always float; `//` floors; `%` takes the divisor's sign | `/`, `Math.floor`, remainder `%` |
            | 4300-digit limit | Decimal-text conversion of huge ints is capped against DoS | — |
            | `float` | IEEE 754 double; compare with `math.isclose`; `1/0` raises | `number` |
            | `round()` | Round half to even, plus representation error | `Math.round` rounds half up |
            | `Decimal` | Exact base-10; build from strings; `quantize` with explicit rounding for money | decimal.js, big.js |
            | `Fraction` | Exact rationals; `limit_denominator` recovers simple ratios | — |
            | `complex` | `3 + 4j`, `.real`, `.imag`, `abs`, `cmath` | — |
            | `bool` | Subclass of `int`; reject it explicitly when validating ints | `boolean` |
            | `None` | The only null; check with `is None`; no `undefined` | `null` / `undefined` |
            | Truthiness | Empty containers and zeros are falsy; use `is not None` when 0 is valid | `[]` and `{}` are truthy |
            | Conversion | Always explicit; bad text raises `ValueError`; mixed `+` raises `TypeError` | Implicit coercion |

            **Further reading**

            - [Numeric types — `int`, `float`, `complex`](https://docs.python.org/3/library/stdtypes.html#numeric-types-int-float-complex),
              [integer string conversion length limitation](https://docs.python.org/3/library/stdtypes.html#int-max-str-digits)
            - [Floating-point arithmetic: issues and limitations](https://docs.python.org/3/tutorial/floatingpoint.html),
              [`math`](https://docs.python.org/3/library/math.html),
              [`cmath`](https://docs.python.org/3/library/cmath.html)
            - [`decimal`](https://docs.python.org/3/library/decimal.html),
              [`fractions`](https://docs.python.org/3/library/fractions.html)
            - [Truth value testing](https://docs.python.org/3/library/stdtypes.html#truth-value-testing),
              [`None`](https://docs.python.org/3/library/constants.html#None)
            - [PEP 515 — Underscores in numeric literals](https://peps.python.org/pep-0515/),
              [PEP 285 — Adding a bool type](https://peps.python.org/pep-0285/),
              [PEP 327 — Decimal data type](https://peps.python.org/pep-0327/),
              [PEP 237 — Unifying long integers and integers](https://peps.python.org/pep-0237/)
            """
        ),
    ]


def cells() -> list[NotebookNode]:
    """Return the cells for Unit 1.3 and Lab 1.3."""
    return [
        *_overview_cells(),
        *_int_cells(),
        *_float_cells(),
        *_decimal_fraction_complex_cells(),
        *_bool_none_cells(),
        *_under_the_hood_cells(),
        *_lab_cells(),
        *_recap_cells(),
    ]
