# Unit 1.4 — Text and Binary Data Types

[← Previous](unit-1-3-numeric-and-boolean-data-types.md) · [Index](README.md) · [Next →](unit-1-5-collection-data-types-i-lists-tuples-and-ranges.md)

Almost every program you write moves text around: it reads it from users, files and
sockets, cleans it, compares it, formats it and sends it back out. This unit covers
Python's two families for that job: `str` for **text** (a sequence of Unicode code
points) and `bytes` / `bytearray` / `memoryview` for **binary data** (a sequence of
integers from 0 to 255). Python keeps the two strictly apart, and learning where the
border sits is the single most useful habit this unit builds.

## What you will learn

- How to index, slice, search, clean, split and format text with the complete `str`
  API, group by group.
- What `len` really counts, how CPython stores a string in memory (PEP 393), and why
  `"10" < "9"` is `True`.
- How f-strings and the format-spec mini-language replace most manual string
  arithmetic, and how the new t-strings (3.14) make HTML and SQL rendering safe.
- How to compare Unicode text correctly with normalization and `casefold`.
- How to move between `str` and `bytes` on purpose with `encode` / `decode`, and how
  to choose an `errors` policy for bad data.
- When a `memoryview` saves you from copying large binary buffers.

## JavaScript → Python bridge

JavaScript has a single `string` type plus `Uint8Array` / `Buffer` for binary data, so
the overall shape is familiar. The differences are in the details, and several of them
are exactly the kind that cause production bugs.

| JavaScript | Python | The difference that bites |
| --- | --- | --- |
| `"😀".length === 2` | `len("😀") == 1` | Python counts code points, JS UTF-16 units |
| `` `Hi ${name}` `` | `f"Hi {name}"` | f-strings add format specs and `=` debug |
| Tagged templates | t-strings `t"…"` | Give a `Template`, not a `str` (3.14) |
| `s.replace("a", "x")` | `s.replace("a", "x")` | Python replaces **every** match |
| `"10" < "9"` is `true` | `"10" < "9"` is `True` | Same: never numeric |
| `s.trim()` | `s.strip()` | `strip("xy")` removes a *set* of chars |
| `s[99]` is `undefined` | `s[99]` raises | `IndexError`; slices never raise |
| `Buffer`, `Uint8Array` | `bytes`, `bytearray` | `str + bytes` raises `TypeError` |

All examples in this unit share one setup cell. It imports the standard modules used
below and defines two helpers: `show_size` (shared with earlier units) and
`raised_error_name`, which runs a zero-argument function and returns the name of the
exception it raised, so that a demo can show an error in one line.

```python
import base64
import csv
import hashlib
import html
import locale
import sqlite3
import string
import sys
import unicodedata
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from string.templatelib import Interpolation, Template


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
print(f"{sys.getdefaultencoding()=}")
print(f"{unicodedata.unidata_version=}")
```

```text
sys.version_info[:2]=(3, 15)
sys.getdefaultencoding()='utf-8'
unicodedata.unidata_version='17.0.0'
```

> **Note:** the setup prints the running interpreter's version, its default encoding
> and the version of the Unicode database bundled with it. All outputs in this unit
> come from CPython 3.15.

## 1.4.1 Strings (`str`) fundamentals

### Literals, quotes and escapes

A Python `str` is an **immutable sequence of Unicode code points**. A code point is
just a number that the Unicode standard assigns to a character: `A` is U+0041, `₹` is
U+20B9, `😀` is U+1F600. The string does not store glyphs or bytes; it stores those
numbers, and only turns them into bytes when you explicitly encode it.

Python has more literal forms than JavaScript, but they are simpler, because there is
no interpolation hidden in any of them (interpolation needs an explicit `f` or `t`
prefix, covered in 1.4.3):

- **Single and double quotes** mean exactly the same thing. Pick the one that avoids
  escaping: `'Annapurna "Tiffin" Centre'`, `"It's open"`.
- **Triple quotes** (`"""…"""` or `'''…'''`) span several lines and keep the line
  breaks. They are also how docstrings are written.
- **Raw strings** `r"…"` keep every backslash as typed. They exist for regular
  expressions and Windows paths, where backslashes are part of the data.
- **Escape sequences** in normal strings: `\n` newline, `\t` tab, `\\` a backslash,
  `\u20b9` a code point by its four hex digits, `\U0001F600` by eight hex digits.

The example below shows the classic Windows-path accident: in a normal string `\n` and
`\t` are escapes, so `"C:\new\table"` silently contains a newline and a tab and is two
characters shorter than it looks.

```python
shop_name = 'Annapurna "Tiffin" Centre'
opening_note = "It's open"
menu_text = """Idli
Dosa
Vada"""
raw_windows_path = r"C:\new\table"
escaped_windows_path = "C:\new\table"
rupee_sign = "\u20b9"
print(shop_name, "|", opening_note)
print(f"{menu_text.splitlines()=}")
print(f"{raw_windows_path=}, {len(raw_windows_path)=}")
print(f"{escaped_windows_path=}, {len(escaped_windows_path)=}")
print("  (\\n and \\t were escapes)")
print(f"{rupee_sign=}", "Total:\t" + rupee_sign + "120")
```

```text
Annapurna "Tiffin" Centre | It's open
menu_text.splitlines()=['Idli', 'Dosa', 'Vada']
raw_windows_path='C:\\new\\table', len(raw_windows_path)=12
escaped_windows_path='C:\new\table', len(escaped_windows_path)=10
  (\n and \t were escapes)
rupee_sign='₹' Total:	₹120
```

> **Warning:** an unknown escape such as `"\d"` is still passed through today, but
> Python emits a `SyntaxWarning` for it and plans to make it an error. Use raw strings
> (`r"\d+"`) for regexes and paths.

### Immutability

Immutable means that no method and no assignment can change a string in place. This
matches JavaScript, where `s[0] = "D"` is silently ignored; Python is stricter and
raises a `TypeError`. Every "change" builds a brand new string object and leaves the
original untouched.

```python
dish_name = "dosa"
try:
    dish_name[0] = "D"
except TypeError as error:
    print(f"{type(error).__name__}: {error}")
capitalized_dish_name = "D" + dish_name[1:]
print(f"{dish_name=}, {capitalized_dish_name=}")
print("(a new string; the original is unchanged)")
```

```text
TypeError: 'str' object does not support item assignment
dish_name='dosa', capitalized_dish_name='Dosa'
(a new string; the original is unchanged)
```

Immutability is what lets CPython share strings safely: they can be dictionary keys,
they can be interned (Unit 1.2), and a function can never change a string you passed
it.

### Indexing and slicing

`text[i]` returns a one-character string (Python has no separate `char` type).
Negative indexes count from the end, so `text[-1]` is the last character, like
JavaScript's `text.at(-1)`.

`text[start:stop:step]` copies a range. `start` is included, `stop` is excluded, and
any part can be left out: `[:3]` is the first three characters, `[-4:]` the last four,
`[::2]` every second character, and `[::-1]` the whole string reversed (there is no
`reverse()` method on `str`). The asymmetry between indexing and slicing matters:
**an index out of range raises `IndexError`, but a slice out of range just clamps** to
the available characters and returns fewer of them, possibly an empty string.

```python
order_code = "BLR-2026-0042"
print(f"{order_code[0]=}, {order_code[-1]=}, {order_code[-4:]=}")
print(f"{order_code[:3]=}, {order_code[4:8]=}, {order_code[::2]=}")
print(f"{order_code[::-1]=}")
print(f"{order_code[100:]=}, {order_code[-100:3]=}  (slices clamp)")
try:
    print(order_code[100])
except IndexError as error:
    print(f"{type(error).__name__}: {error}")
```

```text
order_code[0]='B', order_code[-1]='2', order_code[-4:]='0042'
order_code[:3]='BLR', order_code[4:8]='2026', order_code[::2]='BR22-02'
order_code[::-1]='2400-6202-RLB'
order_code[100:]='', order_code[-100:3]='BLR'  (slices clamp)
IndexError: string index out of range
```

```text
 index:    0   1   2   3   4   5   6   7   8   9  10  11  12
 char:     B   L   R   -   2   0   2   6   -   0   0   4   2
 negative:-13 -12 -11 -10 -9  -8  -7  -6  -5  -4  -3  -2  -1

 order_code[4:8]  -> positions 4,5,6,7      -> '2026'
 order_code[-4:]  -> positions -4 .. end    -> '0042'
```

### What `len` counts

Python's `len` counts **code points**. JavaScript's `.length` counts **UTF-16 code
units**, so any character outside the Basic Multilingual Plane (the first 65,536 code
points, which excludes most emoji) counts as 2 in JavaScript because it is stored as a
surrogate pair. Python has no surrogate pairs in normal strings, so `len("😀")` is 1.

Neither language counts what a person sees, though. 👍🏽 is two code points (a thumbs-up
plus a skin-tone modifier) and 🇮🇳 is two regional-indicator letters that the font
draws as one flag. Counting user-perceived characters ("grapheme clusters") needs a
third-party library such as `regex` or `grapheme`. The demo below computes all three
counts: Python's `len`, what JavaScript's `.length` would say (UTF-16 bytes divided by
2), and the UTF-8 byte count that a file or HTTP body would use.

```python
for sample_text in ["dosa", "₹120", "😀", "👍🏽", "🇮🇳"]:
    code_point_count = len(sample_text)
    utf16_unit_count = len(sample_text.encode("utf-16-le")) // 2
    utf8_byte_count = len(sample_text.encode("utf-8"))
    print(
        f"{sample_text!r:8} len={code_point_count}"
        f"  JS .length={utf16_unit_count}"
        f"  UTF-8 bytes={utf8_byte_count}"
    )
```

```text
'dosa'   len=4  JS .length=4  UTF-8 bytes=4
'₹120'   len=4  JS .length=4  UTF-8 bytes=6
'😀'      len=1  JS .length=2  UTF-8 bytes=4
'👍🏽'     len=2  JS .length=4  UTF-8 bytes=8
'🇮🇳'     len=2  JS .length=4  UTF-8 bytes=8
```

> **Note:** the emoji rows look misaligned because the terminal draws emoji two
> columns wide while the format spec counts code points. That is itself a small lesson
> in why "width", "length" and "bytes" are three different things.

### Under the hood: PEP 393 compact strings

How does CPython store a string so that `text[i]` is O(1) even though characters have
very different code-point values? Since Python 3.3 it uses the **flexible string
representation** from PEP 393. Each string object is stored with the narrowest fixed
width that fits its **largest** code point:

```text
 largest code point      storage kind   bytes per character
 U+0000 .. U+00FF        Latin-1        1
 U+0100 .. U+FFFF        UCS-2          2   (e.g. ₹ U+20B9)
 U+10000 .. U+10FFFF     UCS-4          4   (e.g. 😀 U+1F600)
```

Because every character in one string has the same width, finding character `i` is a
multiplication, never a scan. The cost is that a single emoji upgrades the whole
string to 4 bytes per character. The cell below measures this: for each sample it adds
one more character and reports how much `sys.getsizeof` grows.

```python
for width_label, sample_text in [
    ("ASCII", "a" * 10),
    ("Latin-1 (é)", "é" * 10),
    ("BMP (₹)", "₹" * 10),
    ("astral (😀)", "😀" * 10),
    ("ASCII + one 😀", "a" * 9 + "😀"),
]:
    bytes_per_character = sys.getsizeof(
        sample_text + sample_text[-1]
    ) - sys.getsizeof(sample_text)
    print(
        f"{width_label:15} {sys.getsizeof(sample_text):>4} bytes total, "
        f"{bytes_per_character} byte(s) per character"
    )
```

```text
ASCII             51 bytes total, 1 byte(s) per character
Latin-1 (é)       67 bytes total, 1 byte(s) per character
BMP (₹)           78 bytes total, 2 byte(s) per character
astral (😀)       100 bytes total, 4 byte(s) per character
ASCII + one 😀    100 bytes total, 4 byte(s) per character
```

> **Note:** total sizes include a fixed object header and vary between Python versions
> and builds. The *bytes per character* column is the point: one 😀 makes even the
> ASCII letters cost 4 bytes each.

JavaScript engines do something similar internally (V8 has one-byte and two-byte
strings), but because the language exposes UTF-16, emoji are always surrogate pairs
there.

### Operators: `+`, `*`, `in` and comparison

`+` concatenates, `*` repeats (`"-" * 10`), and `in` tests for a **substring**, not
just a single character. JavaScript's `includes` is the nearest equivalent.

Comparison (`<`, `>`, `sorted`) is **lexicographic by code point**: Python compares
the first characters, and only if they are equal moves on to the next ones. So
`"10" < "9"` is `True`, because `"1"` (U+0031) comes before `"9"` (U+0039), exactly as
in JavaScript. Uppercase letters (U+0041 to U+005A) also sort before all lowercase
ones (U+0061 to U+007A). To sort numbers stored as text, give `sorted` a key such as
`key=int`; to sort case-insensitively, use `key=str.casefold`.

```python
print(f"{'tea' + 'pot'=}, {'-' * 10=}, {'dos' in 'dosa'=}")
print(f"{'10' < '9'=}  (compares '1' with '9' first)")
print(f"{sorted(['10', '9', '100', '2'])=}")
print(f"{sorted(['10', '9', '100', '2'], key=int)=}")
print(f"{'apple' < 'Banana'=}, {ord('a')=}, {ord('B')=}")
```

```text
'tea' + 'pot'='teapot', '-' * 10='----------', 'dos' in 'dosa'=True
'10' < '9'=True  (compares '1' with '9' first)
sorted(['10', '9', '100', '2'])=['10', '100', '2', '9']
sorted(['10', '9', '100', '2'], key=int)=['2', '9', '10', '100']
'apple' < 'Banana'=False, ord('a')=97, ord('B')=66
```

> **Warning:** building a long string with `+=` in a loop can be quadratic, because
> every step creates a new string. CPython sometimes optimizes it in place, but do not
> rely on that: collect the parts in a list and call `"".join(parts)` once.

### Key points

| Idea | Rule |
| --- | --- |
| Quotes | `'…'` and `"…"` are identical; `"""…"""` spans lines |
| Raw string | `r"C:\new"` keeps backslashes |
| Immutable | Every change makes a new string |
| Index out of range | `IndexError` |
| Slice out of range | Clamps; never raises |
| `len` | Code points, not UTF-16 units or glyphs |
| Storage | 1, 2 or 4 bytes per char (PEP 393) |
| Comparison | By code point: `"10" < "9"` |

## 1.4.2 String methods (complete API by group)

`str` has 47 public methods. That sounds like a lot, but they fall into eight groups,
and once you know the groups you can usually guess the method name. Two rules hold for
all of them:

1. Every method returns a **new** object. None of them changes the original string,
   because strings are immutable. Forgetting to use the return value
   (`name.strip()` on its own line) is the most common beginner bug.
2. Methods are called on the string, including `join`: the separator is the object,
   `", ".join(items)`, the opposite of JavaScript's `items.join(", ")`.

| Group | Methods |
| --- | --- |
| Case | `lower`, `upper`, `title`, `capitalize`, `casefold`, `swapcase` |
| Searching | `find`, `rfind`, `index`, `rindex`, `count`, `startswith`, `endswith`, `in` |
| Cleaning | `strip`, `lstrip`, `rstrip`, `removeprefix`, `removesuffix` |
| Splitting, joining | `split`, `rsplit`, `splitlines`, `partition`, `rpartition`, `join` |
| Replacing | `replace`, `translate`, `maketrans`, `expandtabs` |
| Testing | `isdecimal`, `isdigit`, `isnumeric`, `isalpha`, `isalnum`, `isspace`, … |
| Layout | `center`, `ljust`, `rjust`, `zfill` |
| Encoding | `encode` |

The remaining two methods, `format` and `format_map`, belong to string formatting and
are covered in 1.4.3; their rows appear at the end of this section so that the
reference is complete.

### Case

The case methods map each character to another case using the full Unicode tables, not
just ASCII. `title` capitalizes the first letter after **every** non-letter, which
includes apostrophes, so `"o'neil's"` becomes `"O'Neil'S"`. `capitalize` uppercases
only the very first character and lowers the rest. `casefold` is a more aggressive
`lower` designed for caseless comparison; it is covered properly in 1.4.4.

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `lower` | All lowercase | `'new DELHI'.lower()` | `'new delhi'` |
| `upper` | All uppercase | `'new DELHI'.upper()` | `'NEW DELHI'` |
| `title` | Capitalize each word | `'new DELHI'.title()` | `'New Delhi'` |
| `capitalize` | First char up, rest down | `'new DELHI'.capitalize()` | `'New delhi'` |
| `casefold` | Lowercase for comparing | `'Straße'.casefold()` | `'strasse'` |
| `swapcase` | Invert each letter's case | `'new DELHI'.swapcase()` | `'NEW delhi'` |

```python
city_name = "new DELHI"
print(f"{city_name.lower()=}")
print(f"{city_name.upper()=}")
print(f"{city_name.title()=}")
print(f"{city_name.capitalize()=}  (first character only)")
print(f"{city_name.swapcase()=}")
print(f"{'Straße'.lower()=}, {'Straße'.casefold()=}")
print(f"{"o'neil's café".title()=}  (the apostrophe starts a word)")
```

```text
city_name.lower()='new delhi'
city_name.upper()='NEW DELHI'
city_name.title()='New Delhi'
city_name.capitalize()='New delhi'  (first character only)
city_name.swapcase()='NEW delhi'
'Straße'.lower()='straße', 'Straße'.casefold()='strasse'
"o'neil's café".title()="O'Neil'S Café"  (the apostrophe starts a word)
```

### Searching

There are two pairs of position finders, and they differ only in what happens when
nothing matches. `find` / `rfind` return `-1` (like JavaScript's `indexOf` /
`lastIndexOf`); `index` / `rindex` raise `ValueError`. Prefer `index` when a missing
match is a bug, because `-1` is a valid slice index and silently gives wrong results
(`text[text.find("x"):]` returns the last character when `x` is missing).

`startswith` and `endswith` accept a **tuple** of options, which replaces a chain of
`or` checks. All searching methods also take optional `start` and `end` positions. When
you only need yes or no, use the `in` operator.

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `find` | First index, or `-1` | `'a-b-a'.find('a')` | `0` |
| `find` (miss) | No match | `'a-b-a'.find('z')` | `-1` |
| `rfind` | Last index, or `-1` | `'a-b-a'.rfind('a')` | `4` |
| `index` | Like `find`, raises if missing | `'a-b-a'.index('b')` | `2` |
| `rindex` | Like `rfind`, raises if missing | `'a-b-a'.rindex('a')` | `4` |
| `count` | Non-overlapping matches | `'a-b-a'.count('a')` | `2` |
| `startswith` | Prefix test (tuple OK) | `'img.png'.startswith('img')` | `True` |
| `endswith` | Suffix test (tuple OK) | `'img.png'.endswith(('.png', '.jpg'))` | `True` |
| `in` | Substring test (operator) | `'dos' in 'dosa'` | `True` |

```python
log_line = "GET /api/orders/42 200 GET"
print(
    f"{log_line.find('GET')=}, {log_line.rfind('GET')=}, "
    f"{log_line.find('POST')=}"
)
print(f"{log_line.index('/api')=}, {log_line.rindex('GET')=}")
try:
    log_line.index("POST")
except ValueError as error:
    print(f"index: {type(error).__name__}: {error}")
print(f"{log_line.count('GET')=}, {log_line.count('/')=}")
file_name = "invoice_2026.PDF"
print(f"{file_name.startswith('invoice')=}")
print(f"{file_name.lower().endswith(('.pdf', '.png', '.jpg'))=}")
print(f"{'orders' in log_line=}")
```

```text
log_line.find('GET')=0, log_line.rfind('GET')=23, log_line.find('POST')=-1
log_line.index('/api')=4, log_line.rindex('GET')=23
index: ValueError: substring not found
log_line.count('GET')=2, log_line.count('/')=3
file_name.startswith('invoice')=True
file_name.lower().endswith(('.pdf', '.png', '.jpg'))=True
'orders' in log_line=True
```

### Cleaning

With no argument, `strip`, `lstrip` and `rstrip` remove whitespace (spaces, tabs,
newlines and the other Unicode spaces) from both ends, the left end or the right end.
They are JavaScript's `trim`, `trimStart` and `trimEnd`.

With an argument they behave differently from what most people expect: the argument is
a **set of characters**, and Python keeps removing any character from that set until
it meets one that is not in it. `"commerce.com".strip(".com")` is therefore `"erce"`,
not `"commerce"`. To remove an exact piece of text, use `removeprefix` /
`removesuffix` (3.9+), which remove it once if it is there and otherwise return the
string unchanged.

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `strip` | Trim both ends | `'  hi  '.strip()` | `'hi'` |
| `strip(chars)` | Trim a char set | `'xxhixx'.strip('x')` | `'hi'` |
| `lstrip` | Trim the left end | `'  hi  '.lstrip()` | `'hi  '` |
| `rstrip` | Trim the right end | `'  hi  '.rstrip()` | `'  hi'` |
| `removeprefix` | Drop exact prefix | `'www.site.in'.removeprefix('www.')` | `'site.in'` |
| `removesuffix` | Drop exact suffix | `'site.com'.removesuffix('.com')` | `'site'` |

```python
raw_email = "  \t ramesh@example.com \n"
print(f"{raw_email.strip()=}")
print(f"{raw_email.lstrip()=}")
print(f"{raw_email.rstrip()=}")
print(f"{'xxhixyx'.strip('xy')=}  (any x or y, from both ends)")
site_name = "commerce.com"
print(f"{site_name.strip('.com')=}  (oops: strips . c o m)")
print(f"{site_name.removesuffix('.com')=}")
print(f"{'www.example.in'.removeprefix('www.')=}")
print(f"{'example.in'.removeprefix('www.')=}  (no match)")
```

```text
raw_email.strip()='ramesh@example.com'
raw_email.lstrip()='ramesh@example.com \n'
raw_email.rstrip()='  \t ramesh@example.com'
'xxhixyx'.strip('xy')='hi'  (any x or y, from both ends)
site_name.strip('.com')='erce'  (oops: strips . c o m)
site_name.removesuffix('.com')='commerce'
'www.example.in'.removeprefix('www.')='example.in'
'example.in'.removeprefix('www.')='example.in'  (no match)
```

> **Warning:** `strip(".com")`, `lstrip("http://")` and `rstrip(".txt")` are classic
> bugs. They pass every test whose data happens not to end in one of those letters,
> then mangle the first one that does.

### Splitting and joining

`split` has two distinct modes, and the difference matters when you parse data:

- `split()` with **no argument** splits on any run of whitespace and drops empty
  strings at the edges. `"  idli   dosa\tvada  ".split()` gives three words. It is
  the right tool for "words in a line".
- `split(sep)` splits on **exactly** `sep` and keeps empty fields, so `"a,,b"`
  gives `['a', '', 'b']`. It is the right tool for delimited data. Note that
  `"".split(",")` is `['']`, a list with one empty field, while `"".split()` is `[]`.

`maxsplit` limits the number of cuts, which is how you split a log line into a fixed
number of fields and keep the free-text message intact. `rsplit` does the cutting from
the right, so `rsplit("/", maxsplit=1)` separates a directory from a file name.
`splitlines` splits on every kind of line ending (`\n`, `\r\n`, `\r` and a few Unicode
ones) and does not leave a trailing empty string.

`partition(sep)` always returns a **3-tuple** `(before, sep, after)`. If `sep` is not
found you get `(whole, '', '')`, so unpacking never fails, which makes it ideal for
`key=value` lines. `rpartition` searches from the right.

`"sep".join(iterable)` is the inverse of `split`. Every item must already be a `str`;
unlike JavaScript, Python will not call `str()` on numbers for you, so
`", ".join([1, 2])` raises `TypeError`. Write `", ".join(map(str, numbers))`.

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `split()` | Split on whitespace runs | `' a  b '.split()` | `['a', 'b']` |
| `split(sep)` | Split on exact sep | `'a,,b'.split(',')` | `['a', '', 'b']` |
| `maxsplit` | Limit the cuts | `'a b c'.split(maxsplit=1)` | `['a', 'b c']` |
| `rsplit` | Cut from the right | `'a/b/c'.rsplit('/', 1)` | `['a/b', 'c']` |
| `splitlines` | Split on line endings | `'x\ny\r\nz'.splitlines()` | `['x', 'y', 'z']` |
| `partition` | 3-tuple at first sep | `'k=v=w'.partition('=')` | `('k', '=', 'v=w')` |
| `rpartition` | 3-tuple at last sep | `'a.b.pdf'.rpartition('.')` | `('a.b', '.', 'pdf')` |
| `join` | Glue items with sep | `'-'.join(['a', 'b', 'c'])` | `'a-b-c'` |

```python
messy_line = "  idli   dosa\tvada  "
print(f"{messy_line.split()=}")
print(f"{'a,,b'.split(',')=}  (empty field kept)")
print(f"{''.split()=}, {''.split(',')=}")
log_entry = "2026-10-30 12:00:01 ERROR payment failed: card declined"
print(log_entry.split(" ", maxsplit=2))
print("/srv/app/logs/today.log".rsplit("/", maxsplit=1))
print("line one\nline two\r\nline three".splitlines())
print("timeout=30".partition("="), "no equals".partition("="))
print("report.final.pdf".rpartition("."))
print(f"{', '.join(['idli', 'dosa', 'vada'])=}")
print(f"join with ints: {raised_error_name(lambda: ', '.join([1, 2]))}")
```

```text
messy_line.split()=['idli', 'dosa', 'vada']
'a,,b'.split(',')=['a', '', 'b']  (empty field kept)
''.split()=[], ''.split(',')=['']
['2026-10-30', '12:00:01', 'ERROR payment failed: card declined']
['/srv/app/logs', 'today.log']
['line one', 'line two', 'line three']
('timeout', '=', '30') ('no equals', '', '')
('report.final', '.', 'pdf')
', '.join(['idli', 'dosa', 'vada'])='idli, dosa, vada'
join with ints: TypeError
```

### Replacing

`replace(old, new)` replaces **every** occurrence. This is the opposite of JavaScript,
where `replace` with a string replaces only the first match and you need `replaceAll`
for all of them. Pass a third argument, `count`, to limit the number of replacements.

For character-level substitutions, `translate` is faster and clearer than a chain of
`replace` calls. It takes a translation table, which `str.maketrans` builds in one of
three ways: two equal-length strings (map each character of the first to the
character at the same position in the second), a third string of characters to
delete, or a dict mapping characters to strings or to `None` (delete). The table
itself is just a dict from code points (integers) to code points or `None`.

`expandtabs(tabsize=8)` replaces each tab with enough spaces to reach the next tab
stop, so columns line up.

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `replace` | Replace all matches | `'a-b-a'.replace('a', 'x')` | `'x-b-x'` |
| `replace(…, count)` | Replace first `count` | `'a-b-a'.replace('a', 'x', 1)` | `'x-b-a'` |
| `maketrans` | Build a table | `str.maketrans('ab', 'xy')` | `{97: 120, 98: 121}` |
| `translate` | Apply a table | `'bat'.translate(str.maketrans('a', 'u'))` | `'but'` |
| `expandtabs` | Tabs to spaces | `'a\tb'.expandtabs(4)` | `'a   b'` |

```python
phone_number = "98-45-67-89-01"
print(f"{phone_number.replace('-', '')=}")
print(f"{phone_number.replace('-', ' ', 2)=}  (count=2)")
vowel_masker = str.maketrans("aeiou", "*****")
print(f"{'bangalore'.translate(vowel_masker)=}")
amount_cleaner = str.maketrans({"₹": None, ",": None, " ": None})
print(f"{'₹ 1,23,456'.translate(amount_cleaner)=}")
print(f"{str.maketrans('ab', 'xy', '!')=}")
tabbed_row = "id\tname\tcity"
print(f"{tabbed_row.expandtabs(8)=}")
print(f"{tabbed_row.expandtabs(4)=}")
```

```text
phone_number.replace('-', '')='9845678901'
phone_number.replace('-', ' ', 2)='98 45 67-89-01'  (count=2)
'bangalore'.translate(vowel_masker)='b*ng*l*r*'
'₹ 1,23,456'.translate(amount_cleaner)='123456'
str.maketrans('ab', 'xy', '!')={97: 120, 98: 121, 33: None}
tabbed_row.expandtabs(8)='id      name    city'
tabbed_row.expandtabs(4)='id  name    city'
```

### Testing

The `is…` methods answer a yes-or-no question about **every** character of the
string. All of them return `False` for the empty string, except `isascii` and
`isprintable`, which return `True` (there is no character that fails the test).

The three numeric tests are the confusing ones, because Unicode has many kinds of
digits:

| Method | True for | Example that is True |
| --- | --- | --- |
| `isdecimal` | Digits in any script | `"42"`, `"٣"` (Arabic-Indic 3) |
| `isdigit` | Decimals plus superscripts | `"²"` |
| `isnumeric` | Digits plus fractions, numerals | `"½"`, `"四"` |

Only `isdecimal` matches what `int()` accepts. None of the three accepts a sign or a
decimal point, so none of them is a full "is this a number" test; for that, try the
conversion and catch `ValueError`.

```python
print(f"{'sample':>8} {'isdecimal':>10} {'isdigit':>8} {'isnumeric':>10}")
for numeric_text in ["42", "٣", "²", "½", "四", "4.2", "-1"]:
    print(
        f"{numeric_text!r:>8} {numeric_text.isdecimal()!s:>10} "
        f"{numeric_text.isdigit()!s:>8} {numeric_text.isnumeric()!s:>10}"
    )
print(f"{int('٣')=}  (isdecimal text converts)")
print(f"int('²'): {raised_error_name(lambda: int('²'))}")
```

```text
  sample  isdecimal  isdigit  isnumeric
    '42'       True     True       True
     '٣'       True     True       True
     '²'      False     True       True
     '½'      False    False       True
     '四'      False    False       True
   '4.2'      False    False      False
    '-1'      False    False      False
int('٣')=3  (isdecimal text converts)
int('²'): ValueError
```

The other tests are simpler. `isidentifier` checks the *shape* of a Python name, but
does not reject keywords such as `class`; use `keyword.iskeyword` for that.
`islower` and `isupper` ignore non-letters, so `"DOSA 2".isupper()` is `True`.
`isprintable` is `False` for control characters such as tab and newline.

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `isdecimal` | Decimal digits only | `'٣'.isdecimal()` | `True` |
| `isdigit` | Digits incl. superscripts | `'²'.isdigit()` | `True` |
| `isnumeric` | Any numeric char | `'½'.isnumeric()` | `True` |
| `isalpha` | Letters only | `'dosa'.isalpha()` | `True` |
| `isalnum` | Letters or digits | `'dosa2'.isalnum()` | `True` |
| `isspace` | Whitespace only | `' \t'.isspace()` | `True` |
| `isidentifier` | Valid name shape | `'order_id'.isidentifier()` | `True` |
| `islower` | Cased chars all lower | `'dosa'.islower()` | `True` |
| `isupper` | Cased chars all upper | `'DOSA 2'.isupper()` | `True` |
| `istitle` | Title Case words | `'Masala Dosa'.istitle()` | `True` |
| `isascii` | All code points < 128 | `'café'.isascii()` | `False` |
| `isprintable` | No control chars | `'a\tb'.isprintable()` | `False` |

```python
print(f"{'dosa'.isalpha()=}, {'dosa2'.isalpha()=}, {'dosa2'.isalnum()=}")
print(f"{' \t\n'.isspace()=}, {''.isspace()=}")
print(f"{'order_id'.isidentifier()=}, {'2nd_order'.isidentifier()=}")
print(f"{'class'.isidentifier()=}  (a keyword, but a valid shape)")
print(f"{'dosa'.islower()=}, {'DOSA 2'.isupper()=}")
print(f"{'Masala Dosa'.istitle()=}")
print(f"{'dosa'.isascii()=}, {'café'.isascii()=}, {''.isascii()=}")
print(f"{'plain text'.isprintable()=}, {'tab\there'.isprintable()=}")
```

```text
'dosa'.isalpha()=True, 'dosa2'.isalpha()=False, 'dosa2'.isalnum()=True
' \t\n'.isspace()=True, ''.isspace()=False
'order_id'.isidentifier()=True, '2nd_order'.isidentifier()=False
'class'.isidentifier()=True  (a keyword, but a valid shape)
'dosa'.islower()=True, 'DOSA 2'.isupper()=True
'Masala Dosa'.istitle()=True
'dosa'.isascii()=True, 'café'.isascii()=False, ''.isascii()=True
'plain text'.isprintable()=True, 'tab\there'.isprintable()=False
```

### Layout

`ljust`, `rjust` and `center` pad a string to a minimum width with an optional fill
character (a space by default). They are JavaScript's `padEnd` and `padStart`, plus a
centring variant. They **never truncate**: a string longer than the width comes back
unchanged. `zfill` pads with zeros and keeps a leading sign in front, which is what you
want for numbers. In practice the format-spec mini-language from 1.4.3
(`f"{name:<16}"`) does all of this and more in one place.

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `center` | Pad both sides | `'hi'.center(6, '*')` | `'**hi**'` |
| `ljust` | Pad on the right | `'hi'.ljust(5, '.')` | `'hi...'` |
| `rjust` | Pad on the left | `'hi'.rjust(5)` | `'   hi'` |
| `zfill` | Zero-pad after sign | `'-42'.zfill(6)` | `'-00042'` |

```python
for menu_item, price_in_rupees in [
    ("Idli", 40),
    ("Masala Dosa", 120),
    ("Coffee", 35),
]:
    print(menu_item.ljust(16, ".") + str(price_in_rupees).rjust(6))
print(" Total ".center(22, "="))
print(f"{'42'.zfill(6)=}, {'-42'.zfill(6)=}  (sign stays first)")
print(f"{'Masala Dosa'.ljust(5)=}  (never truncates)")
```

```text
Idli............    40
Masala Dosa.....   120
Coffee..........    35
======= Total ========
'42'.zfill(6)='000042', '-42'.zfill(6)='-00042'  (sign stays first)
'Masala Dosa'.ljust(5)='Masala Dosa'  (never truncates)
```

### Encoding

`encode` turns text into `bytes`. With no argument it uses UTF-8, the encoding of the
web and the right default almost everywhere. You can name any other codec
(`"utf-16-le"`, `"latin-1"`, `"ascii"`, `"cp1252"`). If the codec cannot represent a
character, `encode` raises `UnicodeEncodeError`, unless you choose an `errors` policy;
1.4.5 covers the policies and the reverse operation, `bytes.decode`.

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `encode` | Text to bytes (UTF-8) | `'₹5'.encode()` | `b'\xe2\x82\xb95'` |

```python
greeting_text = "Namaste ₹"
encoded_greeting = greeting_text.encode()
print(f"{encoded_greeting=}")
print(f"{len(greeting_text)=}, {len(encoded_greeting)=}")
print(greeting_text.encode("utf-16-le"))
try:
    greeting_text.encode("ascii")
except UnicodeEncodeError as error:
    print(f"{type(error).__name__}: {error.reason} ({error.object[8]!r})")
print(f"{greeting_text.encode('ascii', errors='replace')=}")
```

```text
encoded_greeting=b'Namaste \xe2\x82\xb9'
len(greeting_text)=9, len(encoded_greeting)=11
b'N\x00a\x00m\x00a\x00s\x00t\x00e\x00 \x00\xb9 '
UnicodeEncodeError: ordinal not in range(128) ('₹')
greeting_text.encode('ascii', errors='replace')=b'Namaste ?'
```

Notice that `"Namaste ₹"` is 9 code points but 11 UTF-8 bytes: the rupee sign needs 3
bytes. In UTF-16 every BMP character is 2 bytes, so the ASCII letters are followed by
`\x00` bytes, and `₹` (U+20B9) comes out as `\xb9` followed by `\x20`, which Python
displays as a space. For readability the example prints only the error's `reason`
and the offending character; the full message is `'ascii' codec can't encode
character '\u20b9' in position 8: ordinal not in range(128)`.

### Formatting methods

These two complete the 47-method list. They use the same replacement-field syntax as
f-strings and are explained with the legacy formatting styles in 1.4.3.

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `format` | Fill `{}` fields | `'{} x{}'.format('Idli', 2)` | `'Idli x2'` |
| `format_map` | Fill from a mapping | `'{name}'.format_map({'name': 'Asha'})` | `'Asha'` |

### Key points

| Idea | Rule |
| --- | --- |
| Return values | Every method returns a new string |
| `find` vs `index` | `-1` vs `ValueError` |
| `strip(chars)` | Removes a *set*; use `removesuffix` |
| `split()` vs `split(",")` | Whitespace runs vs exact, keeps empties |
| `partition` | Always a 3-tuple; safe to unpack |
| `join` | `sep.join(strs)`; items must be `str` |
| `replace` | Replaces all; `count` limits |
| `isdecimal` | The test that matches `int()` |

## 1.4.3 String formatting

Python has accumulated four ways to build a string from values. Modern code uses
**f-strings** almost everywhere, the **format-spec mini-language** inside them for
alignment and number formatting, and, since 3.14, **t-strings** when the values must
be escaped before they reach HTML, SQL or a shell. The older styles still appear in
libraries and in `logging` calls, so you need to read them.

### f-strings

An f-string (PEP 498, Python 3.6) is a string literal with an `f` prefix. Any
expression inside `{}` is evaluated at run time, converted with `format()`, and
inserted. It is the direct equivalent of a JavaScript template literal
`` `${expr}` ``, with extras that JavaScript lacks:

| Syntax | Meaning |
| --- | --- |
| `{expr=}` | Debug: prints `expr=` and the `repr` of the value |
| `{value!r}` | Apply `repr()` before formatting |
| `{value!s}` | Apply `str()` (the default) |
| `{value!a}` | Apply `ascii()`: non-ASCII as escapes |
| `{value:>{width}}` | Nested field inside the format spec |

The `=` specifier (3.8) is the fastest debugging tool in the language: `f"{total=}"`
prints `total=360`. Spaces around the `=` are kept in the output, so
`f"{a * b = }"` prints `a * b = 360`. The conversions choose between the
human-readable `str` and the developer-oriented `repr`, which puts quotes around
strings and is what `=` uses by default. A **nested field** lets the format spec
itself contain a replacement field, so a column width can come from a variable.

```python
item_name = "Masala Dosa"
unit_price_in_rupees = 120
quantity = 3
print(f"{item_name} x {quantity} = ₹{unit_price_in_rupees * quantity}")
print(f"{item_name.upper()=}, {quantity * unit_price_in_rupees = }")
print(f"{item_name!r}, {item_name!s}, {'café ₹'!a}")
column_width = 15
print(f"[{item_name:>{column_width}}]  (width taken from a variable)")
print(f"[{item_name:^{column_width + 5}}]")
```

```text
Masala Dosa x 3 = ₹360
item_name.upper()='MASALA DOSA', quantity * unit_price_in_rupees = 360
'Masala Dosa', Masala Dosa, 'caf\xe9 \u20b9'
[    Masala Dosa]  (width taken from a variable)
[    Masala Dosa     ]
```

Under the hood, CPython compiles an f-string into bytecode that evaluates each
expression, formats it and joins the pieces with `BUILD_STRING`. There is no runtime
parsing of the string, which is why f-strings are also the fastest formatting style.

### Multi-line f-strings (3.12+)

Before Python 3.12, the expression inside an f-string could not contain a backslash, a
comment, or the same quote character as the outer string, and it had to fit on one
line. PEP 701 formalized f-strings in the real grammar and removed all of those
limits. A replacement field may now span several lines, contain comments and reuse the
outer quotes:

```python
order_lines = [("Idli", 2), ("Vada", 1), ("Coffee", 2)]
order_summary = f"Items: {
    ', '.join(
        f'{dish} x{count}'  # a comment inside the replacement field
        for dish, count in order_lines
    )
}"
print(order_summary)
```

```text
Items: Idli x2, Vada x1, Coffee x2
```

> **Note:** that this *works* does not mean it is always wise. If a replacement field
> needs a comment, consider computing the value into a well-named variable first.

### The format-spec mini-language

Everything after the `:` inside a replacement field is a **format spec**, a tiny
language interpreted by the value's `__format__` method. The same spec works in
f-strings, in `str.format`, and in the built-in `format(value, spec)`. Its full shape
is:

```text
[[fill]align][sign]["z"]["#"]["0"][width][grouping][.precision][type]
```

You rarely use more than three parts at once. Read a spec like `>16,.2f` as "right
align, width 16, comma separators, 2 decimal places, fixed-point".

| Part | Options | Example | Result |
| --- | --- | --- | --- |
| fill, align | `<` `>` `^`, any fill | `f"{'hi':*^6}"` | `**hi**` |
| sign | `+`, `-`, space | `f"{42:+d}"` | `+42` |
| `#` | `0x`, `0b`, `0o` prefix | `f"{255:#x}"` | `0xff` |
| width | Minimum width | `f"{7:5d}"` | `    7` |
| grouping | `,` or `_` | `f"{1234567:,}"` | `1,234,567` |
| precision | Digits after point | `f"{3.14159:.2f}"` | `3.14` |
| type | `d f e % x b o` | `f"{0.256:.1%}"` | `25.6%` |

The type letters: `d` integer, `f` fixed-point, `e` scientific notation, `%`
percentage (multiplies by 100), `x` / `X` hexadecimal, `b` binary, `o` octal. For a
string, precision means the *maximum* number of characters, so `:.9` truncates.

Dates and datetimes have their own spec language, because `date.__format__` passes the
spec to `strftime`: `f"{invoice_date:%Y-%m-%d}"` gives an ISO date and
`%d %b %Y, %A` a human-readable one.

```python
order_total = 1234567.891
print(f"[{'left':<10}] [{'right':>10}] [{'centre':^10}] [{'fill':*^10}]")
print(f"{order_total:,.2f}  {order_total:_.1f}  {1_000_000:,d}  {1_000_000:_d}")
print(f"{order_total:.3e}  {0.1875:.1%}  [{order_total:15,.2f}]")
print(f"{255:x} {255:#x} {255:X} {5:b} {5:#010b} {8:o} {8:#o}")
print(f"[{42:+d}] [{-42:+d}] [{42: d}] [{42:d}]")
invoice_date = date(2026, 10, 30)
print(f"{invoice_date:%Y-%m-%d}  {invoice_date:%d %b %Y, %A}")
print(f"[{'truncated text':.9}]  (precision on a string cuts it)")
```

```text
[left      ] [     right] [  centre  ] [***fill***]
1,234,567.89  1_234_567.9  1,000,000  1_000_000
1.235e+06  18.8%  [   1,234,567.89]
ff 0xff FF 101 0b00000101 10 0o10
[+42] [-42] [ 42] [42]
2026-10-30  30 Oct 2026, Friday
[truncated]  (precision on a string cuts it)
```

> **Note:** grouping is always in thousands. The Indian lakh/crore style
> (`12,34,567`) is not built in; use the `locale` module or a library such as Babel.

Compare this with JavaScript, where the same job is split across `toFixed`,
`toLocaleString`, `padStart` and `Intl.NumberFormat`. In Python one spec covers it.

### Legacy styles

You will meet three older styles in existing code and libraries:

| Style | Where you still see it |
| --- | --- |
| `"{} {name}".format(...)` | Pre-3.6 code; templates filled later |
| `"{name}".format_map(d)` | Filling from a dict |
| `"%s %.2f" % (...)` | `logging` messages, C-style code |
| `string.Template("$name")` | User-editable templates |

`str.format` uses the same `{}` fields and the same format specs as f-strings, but
the values come from arguments, so the template can be defined once and filled later.
`format_map` takes a mapping directly (useful with a dict subclass that defines
`__missing__`). The `%` operator is the oldest style, borrowed from C's `printf`; the
`logging` module still uses it because it formats lazily, only when a message is
actually emitted. `string.Template` is deliberately limited: `$name` placeholders, no
expressions and no attribute access, which makes it safe for templates written by
users. `substitute` raises `KeyError` for a missing name, `safe_substitute` leaves the
placeholder in place.

```python
customer_record = {"name": "Asha", "balance": 2500.5}
print("{} owes ₹{:,.2f}".format("Asha", 2500.5))
print("{name} owes ₹{balance:,.2f}".format(**customer_record))
print("{name} owes ₹{balance:,.2f}".format_map(customer_record))
print("%s owes ₹%.2f (%d%% overdue)" % ("Asha", 2500.5, 12))  # noqa: UP031
greeting_template = string.Template("Hello $name, order $order_id is ready")
print(greeting_template.substitute(name="Asha", order_id="A-17"))
print(greeting_template.safe_substitute(name="Asha"))
try:
    greeting_template.substitute(name="Asha")
except KeyError as error:
    print(f"substitute: {type(error).__name__}: {error}")
```

```text
Asha owes ₹2,500.50
Asha owes ₹2,500.50
Asha owes ₹2,500.50
Asha owes ₹2500.50 (12% overdue)
Hello Asha, order A-17 is ready
Hello Asha, order $order_id is ready
substitute: KeyError: 'order_id'
```

> **Note:** in the course repository, the `%` line carries `# noqa: UP031` because the
> linter (ruff) rightly suggests an f-string instead. The comment does not change
> behaviour.

### Template strings: t-strings (3.14, PEP 750)

An f-string is evaluated into a finished `str` immediately. That is exactly wrong when
the values are untrusted: by the time you hold the string, a user's `<script>` tag or
`' OR '1'='1` is already mixed into your HTML or SQL, and there is no way to tell code
from data.

A **t-string**, written `t"..."` (*new in 3.14*), looks like an f-string but produces
a `string.templatelib.Template` object instead of a `str`. Nothing is joined. The
template keeps the literal parts and the interpolated values separate, and **your**
code decides how to render them. This is the same idea as a JavaScript tagged template
(`` html`<p>${comment}</p>` ``), except that Python gives you a reusable object
rather than calling a tag function immediately.

A `Template` exposes:

- `.strings`: the literal text parts, always one more than the interpolations (the
  last one may be `''`).
- `.interpolations`: `Interpolation` objects with `.value` (the evaluated value),
  `.expression` (the source text), `.conversion` (`'r'`, `'s'`, `'a'` or `None`) and
  `.format_spec`.
- Iteration: yields the non-empty strings and the interpolations in order.

```python
customer_name = "Asha"
amount_due = 1234.5
reminder_template = t"Dear {customer_name}, you owe ₹{amount_due:,.2f}"
print(f"{type(reminder_template)=}")
print(f"{reminder_template.strings=}")
for interpolation in reminder_template.interpolations:
    print(
        f"expression={interpolation.expression!r}, "
        f"value={interpolation.value!r}, "
        f"format_spec={interpolation.format_spec!r}"
    )
for template_part in reminder_template:
    print(repr(template_part))
```

```text
type(reminder_template)=<class 'string.templatelib.Template'>
reminder_template.strings=('Dear ', ', you owe ₹', '')
expression='customer_name', value='Asha', format_spec=''
expression='amount_due', value=1234.5, format_spec=',.2f'
'Dear '
Interpolation('Asha', 'customer_name', None, '')
', you owe ₹'
Interpolation(1234.5, 'amount_due', None, ',.2f')
```

The expressions are still evaluated eagerly, when the `t"..."` line runs, just like an
f-string. What is deferred is the *joining*, and that is the point: a renderer can
treat the literal parts as trusted (the developer wrote them) and every value as
untrusted.

```text
 t"<p>{user_comment}</p>"
        |
        v
 Template
   strings:        ('<p>', '</p>')            trusted, written by you
   interpolations: (Interpolation(value=...)) untrusted, from the user
        |
        v
 your renderer: escape each value, then join
```

Here is a complete safe HTML renderer. Each interpolated value is formatted with its
own format spec, then passed through `html.escape`; the literal parts are appended
unchanged. The f-string version puts the script tag straight into the page.

```python
def render_safe_html(template: Template) -> str:
    """Render a t-string, HTML-escaping every interpolated value."""
    rendered_parts: list[str] = []
    for template_part in template:
        if isinstance(template_part, Interpolation):
            formatted_value = format(
                template_part.value, template_part.format_spec
            )
            rendered_parts.append(html.escape(formatted_value))
        else:
            rendered_parts.append(template_part)
    return "".join(rendered_parts)


user_comment = "<script>alert('stolen cookie')</script>"
print("f-string:")
print(f"<p>{user_comment}</p>")
print("t-string:")
print(render_safe_html(t"<p>{user_comment}</p>"))
```

```text
f-string:
<p><script>alert('stolen cookie')</script></p>
t-string:
<p>&lt;script&gt;alert(&#x27;stolen cookie&#x27;)&lt;/script&gt;</p>
```

> **Warning:** a t-string is not a string. `print(t"...")` shows the `Template`
> repr, and `str + Template` raises `TypeError`. That is deliberate: it forces every
> template through a renderer. Section 1.4.7 builds a second renderer, for SQL.

### Key points

| Idea | Rule |
| --- | --- |
| f-string | `f"{expr}"`, evaluated immediately |
| Debugging | `f"{expr=}"` prints name and repr |
| Conversions | `!r` repr, `!s` str, `!a` ascii |
| Format spec | `[fill]align sign # width , .prec type` |
| Dates | `f"{d:%Y-%m-%d}"` uses `strftime` |
| Legacy | `.format`, `%`, `string.Template` |
| t-string | `t"…"` gives a `Template` (3.14) |
| Safe rendering | Escape interpolations, trust literals |

## 1.4.4 Unicode correctness

### Normalization and combining characters

Unicode often has more than one way to store the same visible text. The letter `é`
can be one **precomposed** code point, U+00E9, or two code points: a plain `e`
followed by U+0301, the **combining** acute accent, which the font draws on top of the
previous letter. Both render identically, but `==` compares code points, so they are
not equal, and they do not even have the same `len`.

This happens in real data: macOS file names, text pasted from PDFs, and some keyboard
input methods produce the decomposed form, while most web forms produce the composed
one. The fix is to **normalize** both sides to the same form before comparing,
hashing or storing. `unicodedata.normalize(form, text)` supports four forms:

| Form | What it does |
| --- | --- |
| NFC | Compose: `e` + `́` → `é` (usual storage form) |
| NFD | Decompose: `é` → `e` + `́` |
| NFKC | Compose and fold look-alikes: `ﬁ` → `fi`, `２` → `2` |
| NFKD | Decompose and fold look-alikes |

The **K** forms apply *compatibility* folding: ligatures, full-width letters,
superscripts and similar variants are replaced by their plain equivalents. That loses
information (`x²` becomes `x2`), so use NFC for storage and NFKC / NFKD for search
keys and identifiers. `unicodedata.is_normalized` checks a string without building a
new one.

```python
precomposed_name = "Jos\u00e9"
combining_name = "Jose\u0301"
print(f"{precomposed_name=}, {combining_name=}")
print(f"{precomposed_name == combining_name=}")
print(f"{len(precomposed_name)=}, {len(combining_name)=}")
nfc_combining_name = unicodedata.normalize("NFC", combining_name)
print(f"{nfc_combining_name == precomposed_name=}")
print(f"{len(unicodedata.normalize('NFD', precomposed_name))=}")
print(f"{unicodedata.is_normalized('NFC', combining_name)=}")
print(f"{unicodedata.normalize('NFKC', 'ﬁle ２０２６ x²')=}")
```

```text
precomposed_name='José', combining_name='José'
precomposed_name == combining_name=False
len(precomposed_name)=4, len(combining_name)=5
nfc_combining_name == precomposed_name=True
len(unicodedata.normalize('NFD', precomposed_name))=5
unicodedata.is_normalized('NFC', combining_name)=False
unicodedata.normalize('NFKC', 'ﬁle ２０２６ x²')='file 2026 x2'
```

JavaScript has the same tool, `"José".normalize("NFC")`, and the same problem: `===`
compares code units, not what the user sees.

### `casefold` and `unicodedata.name`

Case-insensitive comparison needs `casefold`, not `lower`. `lower` maps each character
to its lowercase form, but some characters have no single-character lowercase that
matches their uppercase spelling. The German sharp s `ß` lowers to itself, yet its
uppercase spelling is `SS`; `casefold` maps it to `ss`, so `"Straße"` and `"STRASSE"`
compare equal. For a fully correct caseless match, **normalize and casefold both
sides**, as `texts_match` does below. JavaScript has no `casefold`; the usual
approximation is `toLowerCase()` or `localeCompare` with `sensitivity: "base"`.

When two strings look identical but compare unequal, `unicodedata.name` tells you
exactly which code points you are dealing with. A no-break space (U+00A0) pasted from
a web page instead of a normal space is a classic culprit.

```python
def texts_match(first_text: str, second_text: str) -> bool:
    """Compare text the Unicode way: NFC-normalize and casefold both sides."""
    first_key = unicodedata.normalize("NFC", first_text).casefold()
    second_key = unicodedata.normalize("NFC", second_text).casefold()
    return first_key == second_key


print(f"{'Straße'.lower() == 'STRASSE'.lower()=}")
print(f"{'Straße'.casefold() == 'STRASSE'.casefold()=}")
print(f"{texts_match('JOSE\u0301', 'josé')=}")
for character in "é₹ß😀\u0301\u00a0":
    print(f"U+{ord(character):04X} {unicodedata.name(character)}")
```

```text
'Straße'.lower() == 'STRASSE'.lower()=False
'Straße'.casefold() == 'STRASSE'.casefold()=True
texts_match('JOSE\u0301', 'josé')=True
U+00E9 LATIN SMALL LETTER E WITH ACUTE
U+20B9 INDIAN RUPEE SIGN
U+00DF LATIN SMALL LETTER SHARP S
U+1F600 GRINNING FACE
U+0301 COMBINING ACUTE ACCENT
U+00A0 NO-BREAK SPACE
```

### Key points

| Idea | Rule |
| --- | --- |
| Same look, different code points | Precomposed vs combining |
| Normalize before comparing | `normalize("NFC", text)` |
| NFKC / NFKD | Also fold look-alikes; lossy |
| Caseless compare | Normalize, then `casefold` |
| `ß` | `lower` keeps it, `casefold` gives `ss` |
| Debugging look-alikes | `unicodedata.name(char)` |

## 1.4.5 Bytes (`bytes`) and byte arrays (`bytearray`)

### Text versus binary data

`str` is text: a sequence of code points with no particular byte representation.
`bytes` is binary data: a sequence of integers from 0 to 255, exactly what travels
over a socket or sits in a file. Python 3 keeps the two as separate types with no
implicit conversion between them. You convert at the **boundary** of your program:
**encode** text when it leaves (writing files, sending HTTP, hashing) and **decode**
bytes when they arrive. Inside the program, work only with `str`.

```text
str '₹500'  --encode('utf-8')-->  bytes b'\xe2\x82\xb9500'
            <--decode('utf-8')--
```

A `b"..."` literal may contain only ASCII characters and escapes such as `\x89`; a
non-ASCII character in a bytes literal is a `SyntaxError`. Bytes are displayed as
ASCII where possible, so `b"GET"` looks like text, but it is a sequence of numbers.
That is why **indexing a `bytes` object returns an `int`**, while slicing returns
`bytes`. JavaScript's `Uint8Array` behaves the same way when indexed.

```python
png_header = b"\x89PNG\r\n\x1a\n"
http_request_line = b"GET / HTTP/1.1\r\n"
print(f"{png_header=}, {len(png_header)=}")
print(f"{http_request_line[0]=}  (indexing gives an int)")
print(f"{http_request_line[:3]=}  (slicing gives bytes)")
print(f"{list(b'AZ az')=}")
try:
    eval('b"café"')
except SyntaxError as error:
    print(f"{type(error).__name__}: {error.msg}")
```

```text
png_header=b'\x89PNG\r\n\x1a\n', len(png_header)=8
http_request_line[0]=71  (indexing gives an int)
http_request_line[:3]=b'GET'  (slicing gives bytes)
list(b'AZ az')=[65, 90, 32, 97, 122]
SyntaxError: bytes can only contain ASCII literal characters
```

> **Note:** the example uses `eval('b"café"')` only so that the `SyntaxError` can be
> caught and shown. Writing `b"café"` directly in a file would stop the whole module
> from compiling.

### `bytes` versus `bytearray`

`bytes` is immutable, like `str`. `bytearray` is its mutable twin: it supports item
assignment, `append`, `extend`, `pop`, `del` and slice assignment, like a list of
small integers. Use `bytearray` to build or patch a binary buffer, then call
`bytes(...)` to freeze a copy. `bytearray(n)` (and `bytes(n)`) creates `n` zero
bytes.

```python
frozen_payload = b"hello"
try:
    frozen_payload[0] = 72
except TypeError as error:
    print(f"bytes: {type(error).__name__}: {error}")
mutable_buffer = bytearray(b"hello")
mutable_buffer[0] = ord("H")
mutable_buffer.extend(b" world")
del mutable_buffer[-1]
print(f"{mutable_buffer=}")
print(f"{bytes(mutable_buffer)=}")
print(f"{bytearray(4)=}  (four zero bytes)")
```

```text
bytes: TypeError: 'bytes' object does not support item assignment
mutable_buffer=bytearray(b'Hello worl')
bytes(mutable_buffer)=b'Hello worl'
bytearray(4)=bytearray(b'\x00\x00\x00\x00')  (four zero bytes)
```

| Operation | What it does | Example | Result |
| --- | --- | --- | --- |
| `bytes(list)` | From integers | `bytes([72, 105])` | `b'Hi'` |
| `bytes(n)` | `n` zero bytes | `bytes(3)` | `b'\x00\x00\x00'` |
| index | One byte as `int` | `b'AB'[0]` | `65` |
| `list(b)` | All bytes as ints | `list(b'Hi')` | `[72, 105]` |
| `decode` | Bytes to text | `b'\xe2\x82\xb9'.decode()` | `'₹'` |

### `encode`, `decode` and the `errors` argument

`str.encode(encoding)` and `bytes.decode(encoding)` both default to UTF-8 and to
`errors="strict"`, which raises on anything that cannot be converted. The `errors`
argument picks another policy:

| `errors=` | On a bad character or byte |
| --- | --- |
| `strict` | Raise `UnicodeEncodeError` / `UnicodeDecodeError` |
| `replace` | `?` (encode) or `�` U+FFFD (decode) |
| `ignore` | Drop it silently (data loss) |
| `backslashreplace` | Write a `\x..` / `\u....` escape |

In the demo the bytes are cut in the middle of the 3-byte `₹`, which is exactly what
happens when a network read stops halfway through a character. `strict` refuses,
`replace` marks the damage visibly, `ignore` hides it, and `backslashreplace` keeps
the raw bytes as readable escapes so nothing is lost.

```python
customer_note = "Paid ₹500 — thanks"
note_bytes = customer_note.encode("utf-8")
print(f"{note_bytes=}")
print(f"{note_bytes.decode('utf-8')=}")
truncated_bytes = note_bytes[:7]
for error_policy in ["strict", "replace", "ignore", "backslashreplace"]:
    try:
        decoded_text = truncated_bytes.decode("utf-8", errors=error_policy)
    except UnicodeDecodeError as error:
        decoded_text = f"{type(error).__name__}: {error.reason}"
    print(f"decode {error_policy:>16}: {decoded_text!r}")
print(customer_note.encode("ascii", errors="backslashreplace"))
print(customer_note.encode("ascii", errors="ignore"))
```

```text
note_bytes=b'Paid \xe2\x82\xb9500 \xe2\x80\x94 thanks'
note_bytes.decode('utf-8')='Paid ₹500 — thanks'
decode           strict: 'UnicodeDecodeError: unexpected end of data'
decode          replace: 'Paid �'
decode           ignore: 'Paid '
decode backslashreplace: 'Paid \\xe2\\x82'
b'Paid \\u20b9500 \\u2014 thanks'
b'Paid 500  thanks'
```

> **Note:** for readability this example prints only `error.reason`. The full
> message is: `'utf-8' codec can't decode bytes in position 5-6: unexpected end of
> data`.

> **Warning:** never decode a stream chunk by chunk with plain `.decode()`, because a
> chunk boundary can split a character as above. Read everything first, or use an
> incremental decoder (`codecs.getincrementaldecoder("utf-8")()`), which keeps the
> partial bytes until the rest arrives. JavaScript's `TextDecoder` with
> `{stream: true}` solves the same problem.

### UTF-8 by default (3.15, PEP 686)

Which encoding does `open("notes.txt")` use if you do not pass `encoding=`? Before
Python 3.15 the answer was "the locale encoding", which is UTF-8 on Linux and macOS but
a legacy ANSI code page such as cp1252 on many Windows machines. The same script could
read a file correctly on one OS and produce mojibake on another.

*Changed in 3.15* (PEP 686): **UTF-8 mode is on by default**, so `open()`,
`sys.stdin`/`stdout` and friends use UTF-8 on every OS regardless of the locale.
`locale.getencoding()` still reports the OS locale, for the rare code that needs it.
Set the environment variable `PYTHONUTF8=0` to opt out. Code that must also run on
older Pythons should keep passing `encoding="utf-8"` explicitly.

```python
print(f"{sys.flags.utf8_mode=}")
print(f"{locale.getpreferredencoding(False)=}")
print("  (what open() uses without encoding=)")
print(f"{locale.getencoding()=}  (the OS locale encoding)")
if sys.version_info >= (3, 15):
    print("Python 3.15+: UTF-8 mode is on by default (PEP 686)")
else:
    print("Before 3.15: open() uses the locale encoding")
```

```text
sys.flags.utf8_mode=1
locale.getpreferredencoding(False)='utf-8'
  (what open() uses without encoding=)
locale.getencoding()='UTF-8'  (the OS locale encoding)
Python 3.15+: UTF-8 mode is on by default (PEP 686)
```

### Methods shared with `str`

Most `str` methods also exist on `bytes` and `bytearray`: `split`, `replace`,
`startswith`, `find`, `partition`, `strip`, `upper`, `isalpha` and many more. The
arguments must be bytes too (`b": "`, not `": "`), and the case and test methods only
understand ASCII letters. Two methods are specific to binary data: `hex()` turns
bytes into a hex string (optionally with a separator), and `bytes.fromhex()` parses
one back. You will see both in checksums, hashes and protocol dumps.

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `split` | Same as `str`, bytes args | `b'a,b'.split(b',')` | `[b'a', b'b']` |
| `hex` | Bytes to hex text | `b'\xde\xad'.hex()` | `'dead'` |
| `fromhex` | Hex text to bytes | `bytes.fromhex('dead')` | `b'\xde\xad'` |

```python
raw_header = b"Content-Type: text/html; charset=utf-8"
print(raw_header.split(b": ", maxsplit=1))
print(raw_header.replace(b"html", b"plain"))
print(f"{raw_header.startswith(b'Content')=}")
print(f"{raw_header.upper().find(b'UTF')=}")
print(raw_header.partition(b"; "))
print(f"{b'  padded  '.strip()=}, {b'abc'.isalpha()=}")
checksum_bytes = bytes([0xDE, 0xAD, 0xBE, 0xEF])
print(f"{checksum_bytes.hex()=}, {checksum_bytes.hex(':')=}")
print(f"{bytes.fromhex('de ad be ef')=}")
```

```text
[b'Content-Type', b'text/html; charset=utf-8']
b'Content-Type: text/plain; charset=utf-8'
raw_header.startswith(b'Content')=True
raw_header.upper().find(b'UTF')=33
(b'Content-Type: text/html', b'; ', b'charset=utf-8')
b'  padded  '.strip()=b'padded', b'abc'.isalpha()=True
checksum_bytes.hex()='deadbeef', checksum_bytes.hex(':')='de:ad:be:ef'
bytes.fromhex('de ad be ef')=b'\xde\xad\xbe\xef'
```

### Why mixing `str` and `bytes` raises `TypeError`

Python 2 had a `str` type that was really bytes, and it mixed it silently with
`unicode` text using an implicit ASCII decode. Code worked perfectly in testing with
English data and then crashed or corrupted text the first time a customer typed
`₹` or `é`, often far away from where the bad mix happened. Python 3 refuses to mix
the types at all: `+`, `in` and `join` raise `TypeError` immediately, at the line
where the mistake is. Equality is the one exception: `b"42" == "42"` simply returns
`False`, because a bytes object is never equal to a string.

The fix is always the same: decode (or encode) at the boundary, then work in one type.

```python
text_part = "order="
byte_part = b"42"
try:
    text_part + byte_part
except TypeError as error:
    print(f"str + bytes: {type(error).__name__}: {error}")
print(f"bytes in str: {raised_error_name(lambda: byte_part in text_part)}")
print(
    "str.join([str, bytes]): "
    f"{raised_error_name(lambda: ''.join([text_part, byte_part]))}"
)
print(f"{b'42' == '42'=}  (no error, just never equal)")
print(f"{text_part + byte_part.decode()=}  (decode first)")
```

```text
str + bytes: TypeError: can only concatenate str (not "bytes") to str
bytes in str: TypeError
str.join([str, bytes]): TypeError
b'42' == '42'=False  (no error, just never equal)
text_part + byte_part.decode()='order=42'  (decode first)
```

> **Warning:** `b"42" == "42"` being `False` rather than an error can hide bugs, for
> example a dict keyed by `str` looked up with `bytes`. Running Python with `-b`
> makes this comparison emit a `BytesWarning`.

### Key points

| Idea | Rule |
| --- | --- |
| `str` vs `bytes` | Text vs integers 0–255 |
| Boundary rule | Decode on input, encode on output |
| Indexing `bytes` | Gives an `int`; slicing gives `bytes` |
| `bytearray` | Mutable `bytes` |
| `errors=` | `strict`, `replace`, `ignore`, `backslashreplace` |
| Default encoding | UTF-8 everywhere in 3.15 |
| `hex` / `fromhex` | Bytes to hex text and back |
| Mixing types | `TypeError`; `==` is just `False` |

## 1.4.6 Memory views (`memoryview`)

Slicing `bytes` or `bytearray` **copies** the selected bytes into a new object. For a
16-byte header that does not matter; for a 10 MB payload sliced repeatedly while
parsing, it does. A `memoryview` exposes another object's memory through the **buffer
protocol** without copying it. Slicing a view creates another view onto the same
memory, and a view over a writable object such as a `bytearray` lets you write
through it. JavaScript developers know this as `Uint8Array.prototype.subarray`, which
also shares memory, versus `slice`, which copies.

```text
 frame_buffer (bytearray, one block of memory)
 +--------+---+--------------+---+-----+
 | HEADER | : | payload-data | : | CRC |
 +--------+---+--------------+---+-----+
   ^                ^
   header_view      payload_view       (views: no copies)
   [0:6]            [7:19]
```

A view keeps its source alive (`view.obj`) and reports its size in bytes
(`view.nbytes`) and whether it is read-only. While any view exists, the underlying
`bytearray` cannot be resized, because that could move the memory the view points at;
CPython raises `BufferError` instead. Call `release()` (or use the view in a `with`
block) when you are done.

```python
frame_buffer = bytearray(b"HEADER:payload-data:CRC")
header_view = memoryview(frame_buffer)[:6]
payload_view = memoryview(frame_buffer)[7:19]
print(f"{bytes(header_view)=}, {bytes(payload_view)=}")
print(f"{payload_view.nbytes=}, {payload_view.readonly=}")
print(f"{payload_view.obj is frame_buffer=}")
payload_view[:7] = b"PAYLOAD"
print(f"{frame_buffer=}")
print("  (written through the view)")
print(
    "append while viewed: "
    f"{raised_error_name(lambda: frame_buffer.extend(b'!'))}"
)
large_blob = bytes(10_000_000)
copied_slice = large_blob[1:]
viewed_slice = memoryview(large_blob)[1:]
print(f"bytes slice:      {sys.getsizeof(copied_slice):>12,} bytes (a copy)")
print(f"memoryview slice: {sys.getsizeof(viewed_slice):>12,} bytes")
viewed_slice.release()
header_view.release()
payload_view.release()
```

```text
bytes(header_view)=b'HEADER', bytes(payload_view)=b'payload-data'
payload_view.nbytes=12, payload_view.readonly=False
payload_view.obj is frame_buffer=True
frame_buffer=bytearray(b'HEADER:PAYLOAD-data:CRC')
  (written through the view)
append while viewed: BufferError
bytes slice:        10,000,032 bytes (a copy)
memoryview slice:          184 bytes
```

> **Note:** `sys.getsizeof` on a view measures only the small view object, not the
> memory it points at; that is precisely the saving. Exact sizes vary by Python
> version. Phase 5 returns to buffers and the buffer protocol in depth.

### Key points

| Idea | Rule |
| --- | --- |
| Slicing `bytes` | Copies |
| Slicing a `memoryview` | Another view, no copy |
| Writable view | Over `bytearray`, writes through |
| Resizing while viewed | `BufferError` |
| Cleanup | `view.release()` or `with` |

## 1.4.7 Real-world use cases

This section puts the unit's tools to work on problems that come up in every web
backend: cleaning user input, parsing text formats, producing reports, building URLs,
rendering untrusted data safely, and handling binary payloads.

### Normalizing user input

User input arrives with stray spaces, random capitalization and occasionally garbage.
The robust pattern is to compute one **canonical form** and use it for both storage
and comparison: strip the edges, lowercase (or casefold), and reject what is not
valid. For emails, the domain is case-insensitive by specification, and in practice
the whole address is treated that way. `rpartition("@")` splits at the last `@` and
never fails to unpack, so the validation is a couple of simple checks.

```python
def normalize_email(raw_email: str) -> str:
    """Return a trimmed, lowercased email address, or raise ValueError."""
    cleaned_email = raw_email.strip().lower()
    local_part, separator, domain_part = cleaned_email.rpartition("@")
    if not separator or not local_part or "." not in domain_part:
        raise ValueError(f"not an email address: {raw_email!r}")
    return cleaned_email


for raw_email in ["  Asha.K@Example.COM ", "ravi@mail.in", "no-at-sign.com"]:
    try:
        print(f"{raw_email!r:24} -> {normalize_email(raw_email)!r}")
    except ValueError as error:
        print(f"{raw_email!r:24} -> {type(error).__name__}")
```

```text
'  Asha.K@Example.COM '  -> 'asha.k@example.com'
'ravi@mail.in'           -> 'ravi@mail.in'
'no-at-sign.com'         -> ValueError
```

Lab 1.4 applies the same pattern to usernames and search queries, adding Unicode
normalization.

### Parsing structured text

Most text formats you meet in backend work are line-oriented, and `split` and
`partition` handle them without regular expressions. `split(maxsplit=3)` cuts a log
line into exactly four fields and keeps the free-text message intact, however many
spaces it contains. `partition` handles `key=value` lines: first it cuts off an
optional `# comment`, then it splits at the first `=`. `parse_log_line` returns in the
Phase 1 project, the log analyzer.

```python
def parse_log_line(log_line: str) -> dict[str, str]:
    """Split 'DATE TIME LEVEL message' into its four named fields."""
    log_date, log_time, level, message = log_line.split(maxsplit=3)
    return {
        "date": log_date,
        "time": log_time,
        "level": level,
        "message": message,
    }


def parse_key_value_line(config_line: str) -> tuple[str, str] | None:
    """Parse 'key = value'; return None for blank and comment-only lines."""
    content = config_line.partition("#")[0].strip()
    if not content:
        return None
    key, separator, value = content.partition("=")
    if not separator:
        raise ValueError(f"missing '=' in {config_line!r}")
    return key.strip(), value.strip()


parsed_entry = parse_log_line(
    "2026-10-30 12:00:01 ERROR payment failed: card declined"
)
for field_name, field_value in parsed_entry.items():
    print(f"{field_name:>8}: {field_value}")
```

```text
    date: 2026-10-30
    time: 12:00:01
   level: ERROR
 message: payment failed: card declined
```

Feeding a small config file through `parse_key_value_line`: blank lines and comments
are skipped, and the spaces around `=` are optional. The walrus operator `:=`
assigns and tests the parsed value in one line.

```python
config_text = """
# database settings
host = db.internal
port=5432
timeout = 30  # seconds
"""
settings: dict[str, str] = {}
for config_line in config_text.splitlines():
    if (parsed_setting := parse_key_value_line(config_line)) is not None:
        setting_key, setting_value = parsed_setting
        settings[setting_key] = setting_value
print(f"{settings=}")
```

```text
settings={'host': 'db.internal', 'port': '5432', 'timeout': '30'}
```

CSV is the cautionary tale. `split(",")` is fine for simple, unquoted rows. As soon
as a field can contain a comma inside quotes, a plain split produces the wrong number
of fields, and the `csv` module, which understands quoting, is the right tool. The
amount is converted with `Decimal` (Unit 1.3), never `float`, because it is money.

```python
simple_csv_row = "A-17,Asha,1200.50"
order_id, customer, amount_text = simple_csv_row.split(",")
print(f"{order_id=}, {customer=}, {Decimal(amount_text)=}")
quoted_csv_row = 'A-18,"Kumar, Asha",950.00'
print("split: ", quoted_csv_row.split(","), " (wrong: 4 fields)")
print("csv:   ", next(csv.reader([quoted_csv_row])), " (right: 3 fields)")
```

```text
order_id='A-17', customer='Asha', Decimal(amount_text)=Decimal('1200.50')
split:  ['A-18', '"Kumar', ' Asha"', '950.00']  (wrong: 4 fields)
csv:    ['A-18', 'Kumar, Asha', '950.00']  (right: 3 fields)
```

### Reports with the format-spec mini-language

Fixed-width columns, thousands separators and percentages need no string arithmetic:
each column is one format spec. `<8` left-aligns the region name in 8 characters,
`>16,.2f` right-aligns the revenue with separators and 2 decimals, and `>9.1%`
formats the share as a percentage.

```python
revenue_by_region = {
    "North": 1_250_000.0,
    "South": 2_480_500.5,
    "East": 975_250.25,
    "West": 1_810_000.0,
}
total_revenue = sum(revenue_by_region.values())
print(f"{'Region':<8}{'Revenue (₹)':>16}{'Share':>9}")
print("-" * 33)
for region_name, region_revenue in revenue_by_region.items():
    revenue_share = region_revenue / total_revenue
    print(f"{region_name:<8}{region_revenue:>16,.2f}{revenue_share:>9.1%}")
print("-" * 33)
print(f"{'Total':<8}{total_revenue:>16,.2f}{1:>9.0%}")
```

```text
Region       Revenue (₹)    Share
---------------------------------
North       1,250,000.00    19.2%
South       2,480,500.50    38.1%
East          975,250.25    15.0%
West        1,810,000.00    27.8%
---------------------------------
Total       6,515,750.75     100%
```

### URL slugs

A slug is the readable, URL-safe part of an address such as
`/blog/creme-brulee-10-best-recipes-2026`. Building one combines three ideas from this
unit. NFKD splits each accented letter into its base letter plus a combining mark;
encoding to ASCII with `errors="ignore"` drops the marks (and anything else
non-ASCII); then every run of characters that are not letters or digits becomes a
single hyphen.

```python
def slugify(title: str) -> str:
    """Turn a title into a URL slug: ASCII, lowercase, hyphen-joined words."""
    decomposed_title = unicodedata.normalize("NFKD", title)
    ascii_title = decomposed_title.encode("ascii", errors="ignore").decode()
    words = "".join(
        character if character.isalnum() else " "
        for character in ascii_title.lower()
    ).split()
    return "-".join(words)


for blog_title in [
    "Crème Brûlée: 10 Best Recipes (2026)!",
    "  Hello,   World  ",
]:
    print(f"{blog_title!r} -> {slugify(blog_title)!r}")
```

```text
'Crème Brûlée: 10 Best Recipes (2026)!' -> 'creme-brulee-10-best-recipes-2026'
'  Hello,   World  ' -> 'hello-world'
```

### Safe HTML and SQL rendering with t-strings

`render_safe_html` from 1.4.3 covers HTML. For SQL, the safe pattern is not escaping
but **parameters**: the query text contains placeholders and the values travel
separately, so the database never parses data as SQL. `render_sql` turns a t-string
into exactly that: each interpolation becomes a `?` placeholder and its value goes
into a parameter tuple.

```python
def render_sql(template: Template) -> tuple[str, tuple[object, ...]]:
    """Turn a t-string into '?' placeholders plus a tuple of parameters."""
    query_parts: list[str] = []
    query_parameters: list[object] = []
    for template_part in template:
        if isinstance(template_part, Interpolation):
            query_parts.append("?")
            query_parameters.append(template_part.value)
        else:
            query_parts.append(template_part)
    return "".join(query_parts), tuple(query_parameters)


customer_filter = "Asha"
minimum_total = 500
print(
    render_sql(
        t"SELECT id FROM orders "
        t"WHERE customer = {customer_filter} AND total > {minimum_total}"
    )
)
```

```text
('SELECT id FROM orders WHERE customer = ? AND total > ?', ('Asha', 500))
```

Now against a real in-memory SQLite database. The hostile name closes the quote in
the f-string version, turns the condition into `... OR '1'='1'` and matches every row.
Passed as a parameter, it is just an odd customer name that matches nothing.

```python
connection = sqlite3.connect(":memory:")
connection.execute(
    "CREATE TABLE orders (id INTEGER, customer TEXT, total INTEGER)"
)
connection.executemany(
    "INSERT INTO orders VALUES (?, ?, ?)",
    [(1, "Asha", 900), (2, "Ravi", 300)],
)
hostile_name = "nobody' OR '1'='1"
unsafe_query = f"SELECT id FROM orders WHERE customer = '{hostile_name}'"
unsafe_rows = connection.execute(unsafe_query).fetchall()
print(f"f-string query rows: {unsafe_rows}  (injected!)")
safe_query, safe_parameters = render_sql(
    t"SELECT id FROM orders WHERE customer = {hostile_name}"
)
safe_rows = connection.execute(safe_query, safe_parameters).fetchall()
print(f"t-string query rows: {safe_rows}")
connection.close()
```

```text
f-string query rows: [(1,), (2,)]  (injected!)
t-string query rows: []
```

> **Warning:** an f-string inside `execute(...)` is the textbook SQL injection, in any
> language. With t-strings the safe version is no longer than the unsafe one, which
> removes the usual excuse.

### `bytes` in the real world

Network protocols and file formats are bytes, so binary handling shows up as soon as
you touch uploads, hashes or HTTP bodies.

**File signatures.** Most file formats announce their type in the first few bytes,
the "magic number". Checking them with `bytes.startswith` is more trustworthy than
believing a file name's extension, which is the first thing an upload validator should
do.

```python
FILE_SIGNATURES: dict[bytes, str] = {
    b"\x89PNG\r\n\x1a\n": "PNG image",
    b"%PDF-": "PDF document",
    b"PK\x03\x04": "ZIP archive (also .docx, .xlsx)",
    b"\xff\xd8\xff": "JPEG image",
}


def detect_file_type(file_header: bytes) -> str:
    """Name the file type from its first bytes, or 'unknown'."""
    for signature, file_type in FILE_SIGNATURES.items():
        if file_header.startswith(signature):
            return file_type
    return "unknown"


for sample_header in [
    b"%PDF-1.7\n%\xe2\xe3",
    b"\x89PNG\r\n\x1a\n\x00\x00",
    b"hello",
]:
    print(f"{sample_header[:8]!r:36} -> {detect_file_type(sample_header)}")
```

```text
b'%PDF-1.7'                          -> PDF document
b'\x89PNG\r\n\x1a\n'                 -> PNG image
b'hello'                             -> unknown
```

**Content length, hashing and base64.** An HTTP `Content-Length` header is the UTF-8
**byte** length of the body, not its character count; the two differ as soon as the
body contains `₹`. Hash functions such as SHA-256 operate on bytes, so text must be
encoded first. Base64 turns arbitrary bytes into ASCII text that is safe inside JSON,
emails and URLs; the URL-safe alphabet swaps `+` and `/` for `-` and `_`.

```python
request_body = '{"item": "dosa", "price": "₹120"}'
payload_bytes = request_body.encode("utf-8")
print(f"{len(request_body)=} characters")
print(f"{len(payload_bytes)=} bytes (Content-Length)")
payload_digest = hashlib.sha256(payload_bytes).hexdigest()
print(f"sha256: {payload_digest}")
encoded_payload = base64.b64encode(payload_bytes)
print(f"{encoded_payload=}")
print(base64.b64decode(encoded_payload).decode("utf-8"))
print(f"{base64.b64encode(b'\xfb\xff')=}")
print(f"{base64.urlsafe_b64encode(b'\xfb\xff')=}")
```

```text
len(request_body)=33 characters
len(payload_bytes)=35 bytes (Content-Length)
sha256: 9fb30cb1ec0a47b5b0e8d4a3698a760e662aa6cfdc88d4a0cd2f97b49e87025e
encoded_payload=b'eyJpdGVtIjogImRvc2EiLCAicHJpY2UiOiAi4oK5MTIwIn0='
{"item": "dosa", "price": "₹120"}
base64.b64encode(b'\xfb\xff')=b'+/8='
base64.urlsafe_b64encode(b'\xfb\xff')=b'-_8='
```

### Key points

| Task | Tool |
| --- | --- |
| Canonical user input | `strip`, `casefold`, `normalize` |
| Log lines | `split(maxsplit=n)` |
| `key=value` lines | `partition("=")` |
| Quoted CSV | `csv` module, not `split` |
| Reports | Format specs `<8`, `>16,.2f`, `.1%` |
| Slugs | NFKD + ASCII `ignore` + join |
| Safe SQL / HTML | t-string renderer |
| Binary payloads | `encode`, `hashlib`, `base64` |

## Lab 1.4

Three text-cleaning functions of the kind every web application needs. In the
notebook each exercise has a stub that raises `NotImplementedError` and a check cell
that calls `run_checks`; the checks print `FAIL` until you implement the function.
`run_checks` is the shared helper from the course: it takes `(label, thunk, expected)`
triples and prints PASS or FAIL for each one.

```python
type TestCase = tuple[str, Callable[[], object], object]


def run_checks(test_cases: list[TestCase]) -> None:
    """Run (label, thunk, expected) cases and print PASS/FAIL for each."""
    passed_count = 0
    for label, thunk, expected in test_cases:
        try:
            actual = thunk()
        except Exception as error:  # a check must never stop the script
            print(f"FAIL  {label}: raised {type(error).__name__}: {error}")
            continue
        if actual == expected:
            passed_count += 1
            print(f"PASS  {label}")
        else:
            print(f"FAIL  {label}: expected {expected!r}, got {actual!r}")
    print(f"{passed_count}/{len(test_cases)} checks passed")
```

### Exercise 1 — `normalize_username`

Write `normalize_username(raw_username: str) -> str` that:

1. Normalizes with **NFKC** (full-width `ＡＳＨＡ` becomes `ASHA`; `e` plus a
   combining accent becomes `é`).
2. Strips the edges and **casefolds**.
3. Replaces each run of inner whitespace with a single `_`.
4. Raises `ValueError` if the result is empty, or if it contains any character that
   is not alphanumeric (`str.isalnum`), `_` or `.`.

For example, `normalize_username("  Ravi   Shankar ")` returns `"ravi_shankar"`.

| Check | Input | Expected |
| --- | --- | --- |
| strip and casefold | `"  Asha.Kumar "` | `"asha.kumar"` |
| inner spaces | `"Ravi   Shankar"` | `"ravi_shankar"` |
| full-width | `"ＡＳＨＡ２６"` | `"asha26"` |
| `ß` | `"STRAßE"` | `"strasse"` |
| combining accent | `"José"` vs `"JOSÉ"` | equal |
| blank | `"   "` | `ValueError` |
| invalid char | `"asha@home"` | `ValueError` |

**Hints:** `"_".join(text.split())` strips the edges *and* collapses inner whitespace
in one step. Collect the invalid characters in a set so the error message can list
them.

<details><summary>Solution</summary>

```python
USERNAME_EXTRA_CHARACTERS = frozenset("_.")


def normalize_username(raw_username: str) -> str:
    """Return the canonical form of a username.

    NFKC-normalized, casefolded, inner whitespace replaced by "_".

    Raises:
        ValueError: if the result is empty or holds a character other
            than letters, digits, "_" and ".".
    """
    folded_username = unicodedata.normalize("NFKC", raw_username).casefold()
    username = "_".join(folded_username.split())
    if not username:
        raise ValueError("username is empty")
    invalid_characters = sorted(
        {
            character
            for character in username
            if not (
                character.isalnum()
                or character in USERNAME_EXTRA_CHARACTERS
            )
        }
    )
    if invalid_characters:
        raise ValueError(
            f"invalid characters in username: {invalid_characters}"
        )
    return username


print(repr(normalize_username("  Ravi   Shankar ")))
print(repr(normalize_username("ＡＳＨＡ２６")))
print(raised_error_name(lambda: normalize_username("asha@home")))
```

```text
'ravi_shankar'
'asha26'
ValueError
```

```python
run_checks(
    [
        ("strip and casefold", lambda: normalize_username("  Asha.Kumar "),
         "asha.kumar"),
        ("inner spaces become _", lambda: normalize_username("Ravi   Shankar"),
         "ravi_shankar"),
        ("full-width letters", lambda: normalize_username("ＡＳＨＡ２６"),
         "asha26"),
        ("ß casefolds to ss", lambda: normalize_username("STRAßE"), "strasse"),
        (
            "combining accent equals precomposed",
            lambda: normalize_username("Jose\u0301")
            == normalize_username("JOSÉ"),
            True,
        ),
        ("blank raises",
         lambda: raised_error_name(lambda: normalize_username("   ")),
         "ValueError"),
        ("@ raises",
         lambda: raised_error_name(lambda: normalize_username("asha@home")),
         "ValueError"),
    ]
)
```

```text
PASS  strip and casefold
PASS  inner spaces become _
PASS  full-width letters
PASS  ß casefolds to ss
PASS  combining accent equals precomposed
PASS  blank raises
PASS  @ raises
7/7 checks passed
```

</details>

### Exercise 2 — `format_receipt_line`

Write `format_receipt_line(item_name: str, quantity: int, unit_price: Decimal) -> str`
that returns one fixed-width receipt line of exactly **49 characters**:

| Column | Width | Rule |
| --- | --- | --- |
| item name | 20 | Left-aligned; longer: 19 chars + `…` |
| quantity | 4 | Right-aligned |
| separator | 3 | The text `" x "` |
| unit price | 10 | Right, `,` separators, 2 decimals |
| line total | 12 | `quantity * unit_price`, same style |

```text
Masala Dosa            2 x     120.00      240.00
```

You may assume the quantity, price and total fit their columns. The checks compare
exact strings, so every space counts:

| Check | Input | Expected |
| --- | --- | --- |
| basic line | `"Masala Dosa", 2, 120` | the line above |
| long name | `"Paneer Butter Masala Special"` | cut to `Masal…` |
| separators | `"Wedding Catering", 3, 125000` | `375,000.00` total |
| width | two different inputs | always 49 |

**Hints:** format specs do not truncate strings to a width with an ellipsis, so cut
the name yourself first. A nested field (`{name:<{width}}`) keeps the width in one
constant. `Decimal` supports the same `,.2f` spec as `float`.

<details><summary>Solution</summary>

```python
RECEIPT_NAME_WIDTH = 20


def format_receipt_line(
    item_name: str, quantity: int, unit_price: Decimal
) -> str:
    """Return a 49-character receipt line.

    Columns: name (20), quantity (4), " x ", price (10), total (12).
    Names longer than the column are cut to 19 characters plus "…".
    """
    if len(item_name) > RECEIPT_NAME_WIDTH:
        item_name = item_name[: RECEIPT_NAME_WIDTH - 1] + "…"
    name_column = f"{item_name:<{RECEIPT_NAME_WIDTH}}"
    line_total = unit_price * quantity
    return (
        f"{name_column}{quantity:>4} x "
        f"{unit_price:>10,.2f}{line_total:>12,.2f}"
    )


print(format_receipt_line("Masala Dosa", 2, Decimal("120")))
print(format_receipt_line("Paneer Butter Masala Special", 1, Decimal("320.5")))
print(format_receipt_line("Wedding Catering", 3, Decimal("125000")))
```

```text
Masala Dosa            2 x     120.00      240.00
Paneer Butter Masal…   1 x     320.50      320.50
Wedding Catering       3 x 125,000.00  375,000.00
```

```python
run_checks(
    [
        (
            "basic line",
            lambda: format_receipt_line("Masala Dosa", 2, Decimal("120")),
            "Masala Dosa            2 x     120.00      240.00",
        ),
        (
            "long name is truncated with …",
            lambda: format_receipt_line(
                "Paneer Butter Masala Special", 1, Decimal("320.5")
            ),
            "Paneer Butter Masal…   1 x     320.50      320.50",
        ),
        (
            "thousands separators",
            lambda: format_receipt_line(
                "Wedding Catering", 3, Decimal("125000")
            ),
            "Wedding Catering       3 x 125,000.00  375,000.00",
        ),
        (
            "always 49 characters",
            lambda: {
                len(format_receipt_line(name, count, Decimal(price)))
                for name, count, price in [
                    ("Tea", 1, "10"),
                    ("A" * 40, 99, "9999.99"),
                ]
            },
            {49},
        ),
    ]
)
```

```text
PASS  basic line
PASS  long name is truncated with …
PASS  thousands separators
PASS  always 49 characters
4/4 checks passed
```

</details>

### Exercise 3 — search-query normalization

Write `normalize_search_query(raw_query: str) -> str` so that differently typed
queries match the same search index entry:

1. Normalize with **NFKD**, then drop every combining mark
   (`unicodedata.combining` returns non-zero for them), so `é` becomes `e`.
2. Casefold.
3. Turn every character that is not alphanumeric into a space.
4. Collapse whitespace runs into single spaces and strip the edges.

For example, `normalize_search_query("  Café   CRÈME! ")` returns `"cafe creme"`.

| Check | Input | Expected |
| --- | --- | --- |
| accents and case | `"  Café   CRÈME! "` | `"cafe creme"` |
| punctuation | `"Masala-Dosa,  Bengaluru"` | `"masala dosa bengaluru"` |
| full-width | `"ＤＯＳＡ ２０２６"` | `"dosa 2026"` |
| `ß` and `SS` | `"Straße"` vs `"STRASSE"` | equal |
| empty | `""` | `""` |
| only punctuation | `"!!! ???"` | `""` |

> **Note:** dropping marks is right for accented Latin text but wrong for scripts
> such as Devanagari, where marks are part of the letters. Real search engines use
> per-language analyzers.

**Hints:** each step is one generator expression joined with `"".join(...)`; the last
step is the same `" ".join(text.split())` trick as Exercise 1.

<details><summary>Solution</summary>

```python
def normalize_search_query(raw_query: str) -> str:
    """Return a casefolded, accent-free, single-spaced search query."""
    decomposed_query = unicodedata.normalize("NFKD", raw_query)
    unaccented_query = "".join(
        character
        for character in decomposed_query
        if not unicodedata.combining(character)
    )
    folded_query = unaccented_query.casefold()
    spaced_query = "".join(
        character if character.isalnum() else " "
        for character in folded_query
    )
    return " ".join(spaced_query.split())


print(repr(normalize_search_query("  Café   CRÈME! ")))
print(repr(normalize_search_query("ＤＯＳＡ ２０２６")))
```

```text
'cafe creme'
'dosa 2026'
```

```python
run_checks(
    [
        ("accents and case",
         lambda: normalize_search_query("  Café   CRÈME! "), "cafe creme"),
        (
            "punctuation becomes spaces",
            lambda: normalize_search_query("Masala-Dosa,  Bengaluru"),
            "masala dosa bengaluru",
        ),
        ("full-width text",
         lambda: normalize_search_query("ＤＯＳＡ ２０２６"), "dosa 2026"),
        (
            "ß and SS match",
            lambda: normalize_search_query("Straße")
            == normalize_search_query("STRASSE"),
            True,
        ),
        ("empty query", lambda: normalize_search_query(""), ""),
        ("only punctuation", lambda: normalize_search_query("!!! ???"), ""),
    ]
)
```

```text
PASS  accents and case
PASS  punctuation becomes spaces
PASS  full-width text
PASS  ß and SS match
PASS  empty query
PASS  only punctuation
6/6 checks passed
```

</details>

## Recap

| Concept | Takeaway | JavaScript equivalent |
| --- | --- | --- |
| `str` | Immutable code points; methods return new strings | `string` |
| `len` | Counts code points | `.length` (UTF-16 units) |
| PEP 393 | 1, 2 or 4 bytes per char, per string | — |
| Slicing | `[start:stop:step]`; never raises | `slice()`, `at()` |
| `strip(chars)` | Removes a *set*; use `removesuffix` | `trim()` |
| `split` / `partition` | `split(sep)` keeps empties; 3-tuple | `split()` |
| `replace` | Replaces all matches | `replaceAll()` |
| `isdecimal` | Matches what `int()` accepts | `/^\d+$/` |
| f-strings | Expressions, `=`, `!r`, nested specs | Template literals |
| Format spec | `fill align sign # width , .prec type` | `toFixed`, `Intl` |
| t-strings (3.14) | `Template` that a renderer escapes | Tagged templates |
| Normalization | NFC before comparing | `normalize("NFC")` |
| `casefold` | Caseless compare (`ß` → `ss`) | `toLowerCase()` (weaker) |
| `bytes` / `bytearray` | Binary data; index gives `int` | `Uint8Array`, `Buffer` |
| `errors=` | `strict`, `replace`, `ignore`, … | `TextDecoder({fatal})` |
| UTF-8 mode (3.15) | `open()` uses UTF-8 everywhere | — |
| `memoryview` | Zero-copy slices of a buffer | `subarray()` |

## Further reading

- [Text sequence type — `str`](https://docs.python.org/3/library/stdtypes.html#text-sequence-type-str)
- [String methods](https://docs.python.org/3/library/stdtypes.html#string-methods)
- [Format specification mini-language](https://docs.python.org/3/library/string.html#format-specification-mini-language)
- [f-strings in the language reference](https://docs.python.org/3/reference/lexical_analysis.html#f-strings)
- [`string.templatelib` — template string support](https://docs.python.org/3/library/string.templatelib.html)
- [Unicode HOWTO](https://docs.python.org/3/howto/unicode.html)
- [`unicodedata`](https://docs.python.org/3/library/unicodedata.html)
- [Binary sequence types — `bytes`, `bytearray`, `memoryview`](https://docs.python.org/3/library/stdtypes.html#binary-sequence-types-bytes-bytearray-memoryview)
- [Codec error handlers](https://docs.python.org/3/library/codecs.html#error-handlers)
- [PEP 393 — Flexible string representation](https://peps.python.org/pep-0393/)
- [PEP 498 — Literal string interpolation](https://peps.python.org/pep-0498/)
- [PEP 701 — Syntactic formalization of f-strings](https://peps.python.org/pep-0701/)
- [PEP 750 — Template strings](https://peps.python.org/pep-0750/)
- [PEP 686 — Make UTF-8 mode default](https://peps.python.org/pep-0686/)

[← Previous](unit-1-3-numeric-and-boolean-data-types.md) · [Index](README.md) · [Next →](unit-1-5-collection-data-types-i-lists-tuples-and-ranges.md)
