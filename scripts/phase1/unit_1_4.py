"""Unit 1.4 — Text and Binary Data Types (with Lab 1.4)."""

from nbformat import NotebookNode

from nb_builder import code, md

UNIT_SETUP_SOURCE = '''
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
    print(f"{label}: {sys.getsizeof(obj)} bytes, type={type(obj).__name__}, id={id(obj)}")


def raised_error_name(thunk: Callable[[], object]) -> str:
    """Call thunk and return the name of the exception it raised, or "no error"."""
    try:
        thunk()
    except Exception as error:
        return type(error).__name__
    return "no error"


print(f"{sys.version_info[:2]=}, {sys.getdefaultencoding()=}, {unicodedata.unidata_version=}")
'''


def _overview_cells() -> list[NotebookNode]:
    """Unit opener and setup."""
    return [
        md(
            """
            ## Unit 1.4 — Text and Binary Data Types

            **Objectives**

            - Index, slice, search, clean, split and format text with the complete `str` API.
            - Explain what `len` counts, how CPython stores a string, and why `"10" < "9"`.
            - Compare Unicode text correctly with normalization and `casefold`.
            - Move between `str` and `bytes` on purpose, choosing an `errors` policy.
            - Render untrusted values safely with t-strings (*new in 3.14*).

            **JS bridge**

            | JavaScript concept | Python equivalent | The difference that bites |
            | --- | --- | --- |
            | `"😀".length === 2` | `len("😀") == 1` | Python counts code points; JS counts UTF-16 code units |
            | `` `Hi ${name}` `` | `f"Hi {name}"` | Same idea; f-strings add a format spec (`{price:,.2f}`) and `=` debugging |
            | Tagged templates (`` html`…` ``) | t-strings `t"…"` (3.14) | They give you a `Template` object, not a string; your renderer decides how to escape |
            | `"a-b-a".replace("a", "x")` replaces the first match | `str.replace` replaces **every** match | Pass `count=1` for the JS behaviour |
            | `"10" < "9"` is `true` | `"10" < "9"` is `True` | Same: strings compare character by character, never numerically |
            | `str.trim()` | `str.strip()` | `strip("xy")` removes a *set* of characters, not a prefix |
            | `str[99]` is `undefined` | `IndexError` | Slices (`text[99:]`) never raise |
            | `Buffer` / `Uint8Array` | `bytes` / `bytearray` | `bytes` is immutable; `str + bytes` raises `TypeError` |

            The next cell is this unit's setup.
            """
        ),
        code(UNIT_SETUP_SOURCE),
    ]


def _str_fundamentals_cells() -> list[NotebookNode]:
    """1.4.1 Strings fundamentals."""
    return [
        md(
            r"""
            ### 1.4.1 Strings (`str`) fundamentals

            A `str` is an **immutable sequence of Unicode code points**. Single and double quotes
            mean the same thing; pick the one that avoids escaping. Triple quotes span lines. A raw
            string `r"..."` keeps backslashes as typed (useful for regexes and Windows paths).
            Common escapes: `\n` newline, `\t` tab, `\u20b9` a code point by its hex number (₹).
            """
        ),
        code(
            r'''
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
            print(f"{escaped_windows_path=}, {len(escaped_windows_path)=}  (\\n and \\t were escapes)")
            print(f"{rupee_sign=}", "Total:\t" + rupee_sign + "120")
            '''
        ),
        md(
            """
            Immutable means no method or assignment changes a string in place. Every "change"
            builds a new string.
            """
        ),
        code(
            """
            dish_name = "dosa"
            try:
                dish_name[0] = "D"
            except TypeError as error:
                print(f"{type(error).__name__}: {error}")
            capitalized_dish_name = "D" + dish_name[1:]
            print(f"{dish_name=}, {capitalized_dish_name=}  (a new string; the original is unchanged)")
            """
        ),
        md(
            """
            **Indexing and slicing.** `text[i]` returns a one-character string; negative indexes
            count from the end. `text[start:stop:step]` copies a range (stop excluded), and
            `[::-1]` reverses. An index out of range raises `IndexError`, but a slice out of range
            just returns fewer characters.
            """
        ),
        code(
            """
            order_code = "BLR-2026-0042"
            print(f"{order_code[0]=}, {order_code[-1]=}, {order_code[-4:]=}")
            print(f"{order_code[:3]=}, {order_code[4:8]=}, {order_code[::2]=}")
            print(f"{order_code[::-1]=}")
            print(f"{order_code[100:]=}, {order_code[-100:3]=}  (slices clamp, never raise)")
            try:
                print(order_code[100])
            except IndexError as error:
                print(f"{type(error).__name__}: {error}")
            """
        ),
        md(
            """
            **What `len` counts.** Python's `len` counts **code points**. JavaScript's `.length`
            counts UTF-16 code units, so any character outside the Basic Multilingual Plane (most
            emoji) counts as 2 in JS. Neither counts what a person sees: 👍🏽 is two code points (a
            thumb plus a skin-tone modifier) and 🇮🇳 is two regional-indicator letters.
            """
        ),
        code(
            """
            for sample_text in ["dosa", "₹120", "😀", "👍🏽", "🇮🇳"]:
                code_point_count = len(sample_text)
                utf16_unit_count = len(sample_text.encode("utf-16-le")) // 2
                utf8_byte_count = len(sample_text.encode("utf-8"))
                print(
                    f"{sample_text!r:8} len={code_point_count}  JS .length={utf16_unit_count}"
                    f"  UTF-8 bytes={utf8_byte_count}"
                )
            """
        ),
        md(
            """
            #### Under the hood: PEP 393 compact strings

            CPython stores each string with the narrowest fixed width that fits its **largest**
            code point: 1 byte per character (Latin-1), 2 bytes (the rest of the BMP, e.g. ₹) or
            4 bytes (emoji). Indexing stays O(1). One emoji makes the whole string 4 bytes per
            character. Each row adds one more character and measures the growth. Exact sizes vary
            by Python version.
            """
        ),
        code(
            """
            for width_label, sample_text in [
                ("ASCII", "a" * 10),
                ("Latin-1 (é)", "é" * 10),
                ("BMP (₹)", "₹" * 10),
                ("astral (😀)", "😀" * 10),
                ("ASCII + one 😀", "a" * 9 + "😀"),
            ]:
                bytes_per_character = sys.getsizeof(sample_text + sample_text[-1]) - sys.getsizeof(sample_text)
                print(
                    f"{width_label:15} {sys.getsizeof(sample_text):>4} bytes total, "
                    f"{bytes_per_character} byte(s) per character"
                )
            """
        ),
        md(
            """
            **Operators.** `+` concatenates, `*` repeats, `in` tests for a substring. Comparison is
            **lexicographic by code point**: `"10" < "9"` because `"1"` (U+0031) comes before `"9"`
            (U+0039). Uppercase letters sort before lowercase ones. Sort numbers stored as text with
            `key=int`.
            """
        ),
        code(
            """
            print(f"{'tea' + 'pot'=}, {'-' * 10=}, {'dos' in 'dosa'=}")
            print(f"{'10' < '9'=}  (compares '1' with '9' first)")
            print(f"{sorted(['10', '9', '100', '2'])=}")
            print(f"{sorted(['10', '9', '100', '2'], key=int)=}")
            print(f"{'apple' < 'Banana'=}, {ord('a')=}, {ord('B')=}  (uppercase sorts first)")
            """
        ),
    ]


def _str_methods_cells() -> list[NotebookNode]:
    """1.4.2 String methods, one demo cell per table row."""
    return [
        md(
            """
            ### 1.4.2 String methods (complete API by group)

            | Group | Methods |
            | --- | --- |
            | Case | `lower`, `upper`, `title`, `capitalize`, `casefold`, `swapcase` |
            | Searching | `find`, `rfind`, `index`, `rindex`, `count`, `startswith`, `endswith` (accept tuples), `in` |
            | Cleaning | `strip`, `lstrip`, `rstrip` (character sets), `removeprefix`, `removesuffix` |
            | Splitting and joining | `split()` vs `split(sep)`, `maxsplit`, `rsplit`, `splitlines`, `partition`, `rpartition`, `"sep".join(iterable)` |
            | Replacing | `replace(old, new, count)`, `translate` with `str.maketrans`, `expandtabs` |
            | Testing | `isdigit` vs `isdecimal` vs `isnumeric`, `isalpha`, `isalnum`, `isspace`, `isidentifier`, `islower`, `isupper`, `istitle`, `isascii`, `isprintable` |
            | Layout | `center`, `ljust`, `rjust`, `zfill` |
            | Encoding | `encode` |

            Every method returns a **new** object; none of them changes the original string. Each
            group below gets its own demo.
            """
        ),
        md(
            """
            #### Case

            `casefold` is a stronger `lower` meant for comparisons (1.4.4). `title` capitalizes
            after *every* non-letter, including apostrophes.
            """
        ),
        code(
            """
            city_name = "new DELHI"
            print(f"{city_name.lower()=}")
            print(f"{city_name.upper()=}")
            print(f"{city_name.title()=}")
            print(f"{city_name.capitalize()=}  (first character only, the rest lowered)")
            print(f"{city_name.swapcase()=}")
            print(f"{'Straße'.lower()=}, {'Straße'.casefold()=}")
            print(f"{"o'neil's café".title()=}  (the apostrophe starts a new word)")
            """
        ),
        md(
            """
            #### Searching

            `find`/`rfind` return `-1` when nothing matches; `index`/`rindex` raise `ValueError`
            instead. `startswith` and `endswith` accept a **tuple** of options. Use `in` when you
            only need yes or no.
            """
        ),
        code(
            """
            log_line = "GET /api/orders/42 200 GET"
            print(f"{log_line.find('GET')=}, {log_line.rfind('GET')=}, {log_line.find('POST')=}")
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
            """
        ),
        md(
            """
            #### Cleaning

            With no argument, `strip`, `lstrip` and `rstrip` remove whitespace. With an argument
            they remove any characters **from that set**, not that exact prefix or suffix, which
            surprises everyone once. Use `removeprefix` / `removesuffix` (3.9+) to drop an exact
            piece of text.
            """
        ),
        code(
            r"""
            raw_email = "  \t ramesh@example.com \n"
            print(f"{raw_email.strip()=}")
            print(f"{raw_email.lstrip()=}")
            print(f"{raw_email.rstrip()=}")
            print(f"{'xxhixyx'.strip('xy')=}  (any x or y, from both ends)")
            site_name = "commerce.com"
            print(f"{site_name.strip('.com')=}  (oops: strips the characters . c o m)")
            print(f"{site_name.removesuffix('.com')=}")
            print(f"{'www.example.in'.removeprefix('www.')=}")
            print(f"{'example.in'.removeprefix('www.')=}  (no match: unchanged)")
            """
        ),
        md(
            """
            #### Splitting and joining

            `split()` with no argument splits on any run of whitespace and drops empty edges;
            `split(sep)` splits on exactly `sep` and keeps empty fields. `maxsplit` limits the
            number of cuts (`rsplit` cuts from the right). `partition` always returns a 3-tuple,
            so it is safe to unpack. `"sep".join(iterable)` is the inverse of `split`: the
            separator is the object, and every item must already be a `str`.
            """
        ),
        code(
            r"""
            messy_line = "  idli   dosa\tvada  "
            print(f"{messy_line.split()=}")
            print(f"{'a,,b'.split(',')=}  (empty field kept)")
            print(f"{''.split()=}, {''.split(',')=}")
            log_entry = "2026-10-30 12:00:01 ERROR payment failed: card declined"
            print(f"{log_entry.split(' ', maxsplit=2)=}")
            print(f"{'/srv/app/logs/today.log'.rsplit('/', maxsplit=1)=}")
            print(f"{'line one\nline two\r\nline three'.splitlines()=}")
            print(f"{'timeout=30'.partition('=')=}, {'no equals'.partition('=')=}")
            print(f"{'report.final.pdf'.rpartition('.')=}")
            print(f"{', '.join(['idli', 'dosa', 'vada'])=}")
            print(f"join with ints: {raised_error_name(lambda: ', '.join([1, 2]))}")
            """
        ),
        md(
            """
            #### Replacing

            `replace(old, new, count)` replaces every match unless you pass `count`.
            `str.maketrans` builds a table for `translate`: map characters one to one, or map a
            character to `None` to delete it. `expandtabs` turns tabs into spaces, aligned to tab
            stops.
            """
        ),
        code(
            r"""
            phone_number = "98-45-67-89-01"
            print(f"{phone_number.replace('-', '')=}")
            print(f"{phone_number.replace('-', ' ', 2)=}  (count limits the replacements)")
            vowel_masker = str.maketrans("aeiou", "*****")
            print(f"{'bangalore'.translate(vowel_masker)=}")
            amount_cleaner = str.maketrans({"₹": None, ",": None, " ": None})
            print(f"{'₹ 1,23,456'.translate(amount_cleaner)=}")
            print(f"{str.maketrans('ab', 'xy', '!')=}  (a dict of code points)")
            tabbed_row = "id\tname\tcity"
            print(f"{tabbed_row.expandtabs(8)=}")
            print(f"{tabbed_row.expandtabs(4)=}")
            """
        ),
        md(
            """
            #### Testing

            The three numeric tests differ, and only `isdecimal` matches what `int()` accepts:

            | Method | True for | Example that is True |
            | --- | --- | --- |
            | `isdecimal` | digits in any script (`int()` accepts these) | `"42"`, `"٣"` (Arabic-Indic three) |
            | `isdigit` | decimals plus superscripts and similar | `"²"` |
            | `isnumeric` | digits plus fractions and numeral characters | `"½"`, `"四"` |

            None of them accepts a sign or a decimal point.
            """
        ),
        code(
            """
            print(f"{'sample':>8} {'isdecimal':>10} {'isdigit':>8} {'isnumeric':>10}")
            for numeric_text in ["42", "٣", "²", "½", "四", "4.2", "-1"]:
                print(
                    f"{numeric_text!r:>8} {numeric_text.isdecimal()!s:>10} "
                    f"{numeric_text.isdigit()!s:>8} {numeric_text.isnumeric()!s:>10}"
                )
            print(f"{int('٣')=}  (isdecimal text converts)")
            print(f"int('²'): {raised_error_name(lambda: int('²'))}")
            """
        ),
        md(
            """
            The other tests. Every `is…` method returns `False` for the empty string, except
            `isascii` and `isprintable`. `isidentifier` does not reject keywords; use
            `keyword.iskeyword` for that.
            """
        ),
        code(
            r"""
            print(f"{'dosa'.isalpha()=}, {'dosa2'.isalpha()=}, {'dosa2'.isalnum()=}")
            print(f"{' \t\n'.isspace()=}, {''.isspace()=}")
            print(f"{'order_id'.isidentifier()=}, {'2nd_order'.isidentifier()=}")
            print(f"{'class'.isidentifier()=}  (a keyword, but still a valid identifier shape)")
            print(f"{'dosa'.islower()=}, {'DOSA 2'.isupper()=}, {'Masala Dosa'.istitle()=}")
            print(f"{'dosa'.isascii()=}, {'café'.isascii()=}, {''.isascii()=}")
            print(f"{'plain text'.isprintable()=}, {'tab\there'.isprintable()=}")
            """
        ),
        md(
            """
            #### Layout

            `ljust`, `rjust` and `center` pad to a width with an optional fill character; they
            never truncate. `zfill` pads with zeros after the sign. The format-spec mini-language
            in 1.4.3 does the same and more.
            """
        ),
        code(
            """
            for menu_item, price_in_rupees in [("Idli", 40), ("Masala Dosa", 120), ("Coffee", 35)]:
                print(menu_item.ljust(16, ".") + str(price_in_rupees).rjust(6))
            print(" Total ".center(22, "="))
            print(f"{'42'.zfill(6)=}, {'-42'.zfill(6)=}  (zfill keeps the sign first)")
            print(f"{'Masala Dosa'.ljust(5)=}  (never truncates)")
            """
        ),
        md(
            """
            #### Encoding

            `encode` turns text into `bytes` (UTF-8 unless you name another codec). A character
            the codec cannot represent raises `UnicodeEncodeError` unless you choose an `errors`
            policy; 1.4.5 covers the policies.
            """
        ),
        code(
            """
            greeting_text = "Namaste ₹"
            encoded_greeting = greeting_text.encode()
            print(f"{encoded_greeting=}, {len(greeting_text)=}, {len(encoded_greeting)=}")
            print(f"{greeting_text.encode('utf-16-le')=}")
            try:
                greeting_text.encode("ascii")
            except UnicodeEncodeError as error:
                print(f"{type(error).__name__}: {error}")
            print(f"{greeting_text.encode('ascii', errors='replace')=}")
            """
        ),
    ]


def _formatting_cells() -> list[NotebookNode]:
    """1.4.3 String formatting."""
    return [
        md(
            """
            ### 1.4.3 String formatting

            **f-strings** (PEP 498) evaluate any expression inside `{}`. Extras:

            | Syntax | Meaning |
            | --- | --- |
            | `{expr=}` | debug: prints `expr=` and then the `repr` of its value (spaces around `=` are kept) |
            | `{value!r}`, `{value!s}`, `{value!a}` | apply `repr()`, `str()` or `ascii()` before formatting |
            | `{value:>{width}}` | nested field: the format spec itself contains a replacement field |
            | multi-line `{…}` | since 3.12 (PEP 701) an expression may span lines, contain comments and reuse the outer quote character |
            """
        ),
        code(
            """
            item_name = "Masala Dosa"
            unit_price_in_rupees = 120
            quantity = 3
            print(f"{item_name} x {quantity} = ₹{unit_price_in_rupees * quantity}")
            print(f"{item_name.upper()=}, {quantity * unit_price_in_rupees = }")
            print(f"{item_name!r}, {item_name!s}, {'café ₹'!a}")
            column_width = 15
            print(f"[{item_name:>{column_width}}]  (width taken from a variable)")
            print(f"[{item_name:^{column_width + 5}}]")
            """
        ),
        md(
            """
            A multi-line f-string (3.12+): the replacement field spans several lines and contains
            a comment, with no backslashes.
            """
        ),
        code(
            """
            order_lines = [("Idli", 2), ("Vada", 1), ("Coffee", 2)]
            order_summary = f"Items: {
                ', '.join(
                    f'{dish} x{count}'  # a comment inside the replacement field
                    for dish, count in order_lines
                )
            }"
            print(order_summary)
            """
        ),
        md(
            """
            **Format-spec mini-language** (everything after the `:`):

            ```text
            [[fill]align][sign]["z"]["#"]["0"][width][grouping][.precision][type]
            ```

            | Part | Options | Example → result |
            | --- | --- | --- |
            | fill + align | `<` left, `>` right, `^` centre, any fill character | `f"{'hi':*^6}"` → `**hi**` |
            | sign | `+` always, `-` negatives only (default), space for a leading space | `f"{42:+d}"` → `+42` |
            | `#` | alternate form: `0x`, `0b`, `0o` prefixes | `f"{255:#x}"` → `0xff` |
            | width | minimum field width | `f"{7:5d}"` → `    7` |
            | grouping | `,` or `_` thousands separator | `f"{1234567:,}"` → `1,234,567` |
            | precision | digits after the point (or max characters for strings) | `f"{3.14159:.2f}"` → `3.14` |
            | type | `d` int, `f` fixed, `e` exponent, `%` percent, `x` hex, `b` binary, `o` octal | `f"{0.256:.1%}"` → `25.6%` |

            Dates have their own spec, passed to `strftime`: `f"{today:%Y-%m-%d}"`.

            > **Note:** grouping is always in thousands (`12,34,567` lakh style is not built in).
            """
        ),
        code(
            """
            order_total = 1234567.891
            print(f"[{'left':<10}] [{'right':>10}] [{'centre':^10}] [{'fill':*^10}]")
            print(f"{order_total:,.2f}  {order_total:_.1f}  {1_000_000:,d}  {1_000_000:_d}")
            print(f"{order_total:.3e}  {0.1875:.1%}  [{order_total:15,.2f}]")
            print(f"{255:x} {255:#x} {255:X} {5:b} {5:#010b} {8:o} {8:#o}")
            print(f"[{42:+d}] [{-42:+d}] [{42: d}] [{42:d}]")
            invoice_date = date(2026, 10, 30)
            print(f"{invoice_date:%Y-%m-%d}  {invoice_date:%d %b %Y, %A}")
            print(f"[{'truncated text':.9}]  (precision on a string cuts it)")
            """
        ),
        md(
            """
            **Legacy styles** you will meet in older code and libraries:

            | Style | Where you still see it |
            | --- | --- |
            | `"{} {name}".format(...)` | code from before 3.6; building a template once and filling it later |
            | `"{name}".format_map(mapping)` | filling from a dict (or a dict subclass with `__missing__`) |
            | `"%s %.2f" % (...)` | the `logging` module's lazy messages, old C-style code |
            | `string.Template("$name")` | user-editable templates: no expressions, no attribute access |

            The `%` line carries `# noqa: UP031` because ruff (rightly) suggests f-strings instead.
            """
        ),
        code(
            """
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
            """
        ),
        md(
            """
            **Template strings, t-strings** (*new in 3.14*, PEP 750). A `t"..."` literal looks like
            an f-string but produces a `string.templatelib.Template` object instead of a `str`:

            - `.strings`: the literal text parts (always one more than the interpolations).
            - `.interpolations`: `Interpolation` objects with `.value`, `.expression`,
              `.conversion` and `.format_spec`.
            - Iterating yields the non-empty strings and interpolations in order.

            Nothing is joined until **your** code renders it. That is the point: a renderer can
            escape every value for HTML, turn values into SQL parameters, and so on.
            """
        ),
        code(
            """
            customer_name = "Asha"
            amount_due = 1234.5
            reminder_template = t"Dear {customer_name}, you owe ₹{amount_due:,.2f}"
            print(f"{type(reminder_template)=}")
            print(f"{reminder_template.strings=}")
            for interpolation in reminder_template.interpolations:
                print(f"{interpolation.expression=}, {interpolation.value=}, {interpolation.format_spec=}")
            print(f"{list(reminder_template)=}")
            """
        ),
        md(
            """
            A safe HTML renderer: literal parts are trusted (the developer wrote them),
            interpolated values are not, so each value is formatted with its spec and then passed
            through `html.escape`. An f-string would have put the script tag straight into the
            page.
            """
        ),
        code(
            '''
            def render_safe_html(template: Template) -> str:
                """Render a t-string, HTML-escaping every interpolated value."""
                rendered_parts: list[str] = []
                for template_part in template:
                    if isinstance(template_part, Interpolation):
                        formatted_value = format(template_part.value, template_part.format_spec)
                        rendered_parts.append(html.escape(formatted_value))
                    else:
                        rendered_parts.append(template_part)
                return "".join(rendered_parts)


            user_comment = "<script>alert('stolen cookie')</script>"
            print("f-string:", f"<p>{user_comment}</p>")
            print("t-string:", render_safe_html(t"<p>{user_comment}</p>"))
            '''
        ),
    ]


def _unicode_cells() -> list[NotebookNode]:
    """1.4.4 Unicode correctness."""
    return [
        md(
            r"""
            ### 1.4.4 Unicode correctness

            The same visible text can be stored as different code-point sequences: `é` can be one
            precomposed code point (U+00E9) or `e` followed by a **combining** acute accent
            (U+0301). `==` compares code points, so the two are not equal until you
            **normalize** them:

            | Form | What it does |
            | --- | --- |
            | NFC | compose: `e` + `\u0301` → `é` (the usual storage form) |
            | NFD | decompose: `é` → `e` + `\u0301` |
            | NFKC / NFKD | also fold *compatibility* characters: `ﬁ` → `fi`, full-width `２` → `2`, `²` → `2` |
            """
        ),
        code(
            r"""
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
            """
        ),
        md(
            """
            **Case-insensitive comparison** needs `casefold`, not `lower`: the German `ß` lowers
            to itself but casefolds to `ss`. For a fully correct caseless match, normalize *and*
            casefold both sides. `unicodedata.name` tells you exactly which code point you are
            looking at, which helps with "identical-looking" bugs.
            """
        ),
        code(
            r'''
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
            '''
        ),
    ]


def _bytes_cells() -> list[NotebookNode]:
    """1.4.5 bytes and bytearray, 1.4.6 memoryview."""
    return [
        md(
            r"""
            ### 1.4.5 Bytes (`bytes`) and byte arrays (`bytearray`)

            `str` is text (code points); `bytes` is binary data (integers 0–255). You convert at
            the boundary: **encode** text when it leaves your program (files, sockets, hashes) and
            **decode** bytes when they come in.

            ```mermaid
            flowchart LR
                text["str<br/>'₹500'"] -- "encode('utf-8')" --> raw["bytes<br/>b'\xe2\x82\xb9500'"]
                raw -- "decode('utf-8')" --> text
            ```

            <details><summary>ASCII fallback</summary>

            ```text
            str '₹500'  --encode('utf-8')-->  bytes b'\xe2\x82\xb9500'
                        <--decode('utf-8')--
            ```

            </details>

            A `b"..."` literal may contain only ASCII characters and escapes. **Indexing a
            `bytes` object returns an `int`**; slicing returns `bytes`. `bytes` is immutable,
            `bytearray` is its mutable twin.
            """
        ),
        code(
            r"""
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
            """
        ),
        md(
            """
            `bytes` cannot change after it is created. `bytearray` supports item assignment,
            `extend`, `append` and `del`, and `bytes(…)` freezes a copy of it.
            """
        ),
        code(
            """
            frozen_payload = b"hello"
            try:
                frozen_payload[0] = 72
            except TypeError as error:
                print(f"bytes: {type(error).__name__}: {error}")
            mutable_buffer = bytearray(b"hello")
            mutable_buffer[0] = ord("H")
            mutable_buffer.extend(b" world")
            del mutable_buffer[-1]
            print(f"{mutable_buffer=}, {bytes(mutable_buffer)=}")
            print(f"{bytearray(4)=}  (four zero bytes)")
            """
        ),
        md(
            """
            **`encode` / `decode` and the `errors` argument.** The default `errors="strict"`
            raises on bad data. The alternatives:

            | `errors=` | On a bad character or byte |
            | --- | --- |
            | `strict` | raise `UnicodeEncodeError` / `UnicodeDecodeError` (default) |
            | `replace` | substitute `?` (encode) or `�` U+FFFD (decode) |
            | `ignore` | drop it silently (data loss!) |
            | `backslashreplace` | write a `\\x..` / `\\u....` escape so nothing is lost |

            The bytes below are cut in the middle of the 3-byte `₹`, which is exactly what happens
            when a network read stops halfway through a character.
            """
        ),
        code(
            """
            customer_note = "Paid ₹500 — thanks"
            note_bytes = customer_note.encode("utf-8")
            print(f"{note_bytes=}")
            print(f"{note_bytes.decode('utf-8')=}")
            truncated_bytes = note_bytes[:7]
            for error_policy in ["strict", "replace", "ignore", "backslashreplace"]:
                try:
                    decoded_text = truncated_bytes.decode("utf-8", errors=error_policy)
                except UnicodeDecodeError as error:
                    decoded_text = f"{type(error).__name__}: {error}"
                print(f"decode {error_policy:>16}: {decoded_text!r}")
            print(f"{customer_note.encode('ascii', errors='backslashreplace')=}")
            print(f"{customer_note.encode('ascii', errors='ignore')=}")
            """
        ),
        md(
            """
            **UTF-8 by default** (*changed in 3.15*, PEP 686). Python 3.15 turns on **UTF-8 mode**
            by default, so `open()` without `encoding=` reads and writes UTF-8 on every OS, no
            matter the locale (before 3.15, Windows used the ANSI code page). `locale.getencoding()`
            still reports the OS locale. Set `PYTHONUTF8=0` to opt out. Code that must also run on
            older Pythons should keep passing `encoding="utf-8"` explicitly.
            """
        ),
        code(
            """
            print(f"{sys.flags.utf8_mode=}")
            print(f"{locale.getpreferredencoding(False)=}  (what open() uses without encoding=)")
            print(f"{locale.getencoding()=}  (the OS locale encoding)")
            if sys.version_info >= (3, 15):
                print("Python 3.15+: UTF-8 mode is on by default (PEP 686)")
            else:
                print("Before 3.15: open() uses the locale encoding; pass encoding='utf-8'")
            """
        ),
        md(
            """
            **Methods shared with `str`.** Most `str` methods exist on `bytes` and `bytearray`, but
            their arguments must be bytes too. `hex()` and `bytes.fromhex()` convert to and from
            hex text, which you see in checksums and protocol dumps.
            """
        ),
        code(
            """
            raw_header = b"Content-Type: text/html; charset=utf-8"
            print(f"{raw_header.split(b': ', maxsplit=1)=}")
            print(f"{raw_header.replace(b'html', b'plain')=}")
            print(f"{raw_header.startswith(b'Content')=}, {raw_header.upper().find(b'UTF')=}")
            print(f"{raw_header.partition(b'; ')=}")
            print(f"{b'  padded  '.strip()=}, {b'abc'.isalpha()=}")
            checksum_bytes = bytes([0xDE, 0xAD, 0xBE, 0xEF])
            print(f"{checksum_bytes.hex()=}, {checksum_bytes.hex(':')=}")
            print(f"{bytes.fromhex('de ad be ef')=}")
            """
        ),
        md(
            """
            **Mixing `str` and `bytes` raises `TypeError`.** Python 2 silently mixed them and
            corrupted text; Python 3 refuses, so the bug shows up where it starts. Equality is the
            one exception: it simply returns `False`. The fix is always to decode (or encode) at
            the boundary and then work in one type.
            """
        ),
        code(
            """
            text_part = "order="
            byte_part = b"42"
            try:
                text_part + byte_part
            except TypeError as error:
                print(f"str + bytes: {type(error).__name__}: {error}")
            print(f"bytes in str: {raised_error_name(lambda: byte_part in text_part)}")
            print(f"str.join([str, bytes]): {raised_error_name(lambda: ''.join([text_part, byte_part]))}")
            print(f"{b'42' == '42'=}  (no error, just never equal)")
            print(f"{text_part + byte_part.decode()=}  (decode first, then work in str)")
            """
        ),
        md(
            """
            ### 1.4.6 Memory views (`memoryview`)

            Slicing `bytes` **copies** the data. A `memoryview` exposes another object's buffer
            without copying: slicing a view creates another view, and over a `bytearray` you can
            write through it. This matters when you parse large binary payloads. Phase 5 returns
            to buffers.

            > **Note:** while a view exists, the `bytearray` cannot be resized.
            """
        ),
        code(
            """
            frame_buffer = bytearray(b"HEADER:payload-data:CRC")
            header_view = memoryview(frame_buffer)[:6]
            payload_view = memoryview(frame_buffer)[7:19]
            print(f"{bytes(header_view)=}, {bytes(payload_view)=}")
            print(f"{payload_view.nbytes=}, {payload_view.obj is frame_buffer=}, {payload_view.readonly=}")
            payload_view[:7] = b"PAYLOAD"
            print(f"{frame_buffer=}  (written through the view)")
            print(f"append while viewed: {raised_error_name(lambda: frame_buffer.extend(b'!'))}")
            large_blob = bytes(10_000_000)
            print(f"bytes slice:      {sys.getsizeof(large_blob[1:]):>12,} bytes (a copy)")
            print(f"memoryview slice: {sys.getsizeof(memoryview(large_blob)[1:]):>12,} bytes")
            header_view.release()
            payload_view.release()
            """
        ),
    ]


def _use_case_cells() -> list[NotebookNode]:
    """1.4.7 Real-world use cases."""
    return [
        md(
            """
            ### 1.4.7 Real-world use cases

            **Normalizing user input.** Store and compare a canonical form: strip the edges,
            lowercase or casefold, and reject what is not valid. Here, emails: domains are
            case-insensitive, and in practice the whole address is treated that way. Lab 1.4 does
            the same for usernames and search queries.
            """
        ),
        code(
            '''
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
                    print(f"{raw_email!r:24} -> {type(error).__name__}: {error}")
            '''
        ),
        md(
            """
            **Parsing structured text.** `split(maxsplit=…)` handles fixed-shape log lines, and
            `partition` handles `key=value` lines (it never fails to unpack). `parse_log_line`
            returns to the Phase 1 project, the log analyzer.
            """
        ),
        code(
            '''
            def parse_log_line(log_line: str) -> dict[str, str]:
                """Split 'DATE TIME LEVEL message' into its four named fields."""
                log_date, log_time, level, message = log_line.split(maxsplit=3)
                return {"date": log_date, "time": log_time, "level": level, "message": message}


            def parse_key_value_line(config_line: str) -> tuple[str, str] | None:
                """Parse 'key = value'; return None for blank and comment-only lines."""
                content = config_line.partition("#")[0].strip()
                if not content:
                    return None
                key, separator, value = content.partition("=")
                if not separator:
                    raise ValueError(f"missing '=' in {config_line!r}")
                return key.strip(), value.strip()


            print(parse_log_line("2026-10-30 12:00:01 ERROR payment failed: card declined"))
            '''
        ),
        md(
            """
            Feeding a small config file through `parse_key_value_line`: blank lines and comments
            are skipped, and the spaces around `=` are optional.
            """
        ),
        code(
            '''
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
            '''
        ),
        md(
            """
            CSV fields: `split(",")` is fine for simple, unquoted data. As soon as a field can
            contain a comma inside quotes, use the `csv` module.
            """
        ),
        code(
            """
            simple_csv_row = "A-17,Asha,1200.50"
            order_id, customer, amount_text = simple_csv_row.split(",")
            print(f"{order_id=}, {customer=}, {Decimal(amount_text)=}")
            quoted_csv_row = 'A-18,"Kumar, Asha",950.00'
            print(f"{quoted_csv_row.split(',')=}  (wrong: 4 fields)")
            print(f"{next(csv.reader([quoted_csv_row]))=}  (right: 3 fields)")
            """
        ),
        md(
            """
            **Reports with the format-spec mini-language.** Fixed-width columns, thousands
            separators and percentages need no string arithmetic.
            """
        ),
        code(
            """
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
                print(f"{region_name:<8}{region_revenue:>16,.2f}{region_revenue / total_revenue:>9.1%}")
            print("-" * 33)
            print(f"{'Total':<8}{total_revenue:>16,.2f}{1:>9.0%}")
            """
        ),
        md(
            """
            **URL slugs.** NFKD splits accented letters into base letter plus mark; encoding to
            ASCII with `errors="ignore"` drops the marks; every run of other characters becomes
            one hyphen.
            """
        ),
        code(
            '''
            def slugify(title: str) -> str:
                """Turn a title into a URL slug: ASCII, lowercase, words joined by hyphens."""
                decomposed_title = unicodedata.normalize("NFKD", title)
                ascii_title = decomposed_title.encode("ascii", errors="ignore").decode("ascii")
                words = "".join(
                    character if character.isalnum() else " " for character in ascii_title.lower()
                ).split()
                return "-".join(words)


            for blog_title in ["Crème Brûlée: 10 Best Recipes (2026)!", "  Hello,   World  "]:
                print(f"{blog_title!r} -> {slugify(blog_title)!r}")
            '''
        ),
        md(
            """
            **Safe SQL with t-strings.** `render_sql` turns a t-string into a parameterized query:
            each interpolation becomes a `?` placeholder and its value goes into a separate tuple,
            so the database never treats data as SQL. Compare it with an f-string built query on
            an in-memory SQLite database. (`render_safe_html` from 1.4.3 covers the HTML side.)
            """
        ),
        code(
            '''
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


            print(render_sql(t"SELECT id FROM orders WHERE customer = {'Asha'} AND total > {500}"))
            '''
        ),
        md(
            """
            Now against a real (in-memory) database. The hostile name closes the quote in the
            f-string version and matches every row; as a parameter it is just an odd name that
            matches nothing.
            """
        ),
        code(
            """
            connection = sqlite3.connect(":memory:")
            connection.execute("CREATE TABLE orders (id INTEGER, customer TEXT, total INTEGER)")
            connection.executemany("INSERT INTO orders VALUES (?, ?, ?)", [(1, "Asha", 900), (2, "Ravi", 300)])
            hostile_name = "nobody' OR '1'='1"
            unsafe_query = f"SELECT id FROM orders WHERE customer = '{hostile_name}'"
            print(f"f-string query rows: {connection.execute(unsafe_query).fetchall()}  (injected!)")
            safe_query, safe_parameters = render_sql(t"SELECT id FROM orders WHERE customer = {hostile_name}")
            print(f"t-string query rows: {connection.execute(safe_query, safe_parameters).fetchall()}")
            connection.close()
            """
        ),
        md(
            """
            **`bytes` in the real world.** Network protocols and file formats are bytes. Files
            announce their type in the first few bytes (the "magic number"), hashes work on bytes,
            and base64 turns bytes into ASCII text that is safe for JSON, emails and URLs.
            """
        ),
        code(
            r'''
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


            for sample_header in [b"%PDF-1.7\n%\xe2\xe3", b"\x89PNG\r\n\x1a\n\x00\x00", b"hello"]:
                print(f"{sample_header[:8]!r:36} -> {detect_file_type(sample_header)}")
            '''
        ),
        md(
            """
            A JSON request body: its UTF-8 byte length (not its character count) is the HTTP
            `Content-Length`; SHA-256 fingerprints it; base64 makes it ASCII-safe. The URL-safe
            alphabet swaps `+` and `/` for `-` and `_`.
            """
        ),
        code(
            r"""
            request_body = '{"item": "dosa", "price": "₹120"}'
            payload_bytes = request_body.encode("utf-8")
            print(f"{len(request_body)=} characters, {len(payload_bytes)=} bytes (Content-Length)")
            payload_digest = hashlib.sha256(payload_bytes).hexdigest()
            print(f"{payload_digest=}")
            encoded_payload = base64.b64encode(payload_bytes)
            print(f"{encoded_payload=}")
            print(f"{base64.b64decode(encoded_payload).decode('utf-8')=}")
            print(f"{base64.b64encode(b'\xfb\xff')=}, {base64.urlsafe_b64encode(b'\xfb\xff')=}")
            """
        ),
    ]


def _lab_cells() -> list[NotebookNode]:
    """Lab 1.4."""
    return [
        md(
            """
            ### Lab 1.4

            Three text-cleaning functions of the kind every web application needs. For each one,
            replace the `raise NotImplementedError` in the stub, then run the check cell. Until
            then the checks print FAIL with `NotImplementedError`; that is expected.

            #### Exercise 1 — `normalize_username`

            Write `normalize_username(raw_username: str) -> str`:

            1. Normalize with **NFKC** (full-width `ＡＳＨＡ` becomes `ASHA`; `e` + combining accent
               becomes `é`).
            2. Strip the edges and **casefold**.
            3. Replace each run of inner whitespace with a single `_`.
            4. Raise `ValueError` if the result is empty, or if it contains any character that is
               not alphanumeric (`str.isalnum`), `_` or `.`.

            `normalize_username("  Ravi   Shankar ") == "ravi_shankar"`.
            """
        ),
        code(
            '''
            def normalize_username(raw_username: str) -> str:
                """Return the canonical form of a username, or raise ValueError."""
                raise NotImplementedError("Lab 1.4: implement normalize_username()")
            '''
        ),
        md(
            """
            Run the checks. They cover full-width letters, `ß`, a combining accent and two
            invalid inputs.
            """
        ),
        code(
            r"""
            run_checks(
                [
                    ("strip and casefold", lambda: normalize_username("  Asha.Kumar "), "asha.kumar"),
                    ("inner spaces become _", lambda: normalize_username("Ravi   Shankar"), "ravi_shankar"),
                    ("full-width letters", lambda: normalize_username("ＡＳＨＡ２６"), "asha26"),
                    ("ß casefolds to ss", lambda: normalize_username("STRAßE"), "strasse"),
                    (
                        "combining accent equals precomposed",
                        lambda: normalize_username("Jose\u0301") == normalize_username("JOSÉ"),
                        True,
                    ),
                    (
                        "blank raises",
                        lambda: raised_error_name(lambda: normalize_username("   ")),
                        "ValueError",
                    ),
                    (
                        "@ raises",
                        lambda: raised_error_name(lambda: normalize_username("asha@home")),
                        "ValueError",
                    ),
                ]
            )
            """
        ),
        md(
            """
            #### Exercise 2 — `format_receipt_line`

            Write `format_receipt_line(item_name: str, quantity: int, unit_price: Decimal) -> str`
            that returns one fixed-width receipt line of exactly **49 characters**:

            | Column | Width | Rule |
            | --- | --- | --- |
            | item name | 20 | left-aligned; a longer name is cut to 19 characters plus `…` |
            | quantity | 4 | right-aligned |
            | separator | 3 | the text `" x "` |
            | unit price | 10 | right-aligned, `,` separators, 2 decimal places |
            | line total | 12 | `quantity * unit_price`, right-aligned, `,` separators, 2 decimal places |

            ```text
            Masala Dosa            2 x     120.00      240.00
            ```

            You may assume the quantity, price and total fit their columns.
            """
        ),
        code(
            '''
            def format_receipt_line(item_name: str, quantity: int, unit_price: Decimal) -> str:
                """Return a 49-character receipt line: name, quantity, unit price and line total."""
                raise NotImplementedError("Lab 1.4: implement format_receipt_line()")
            '''
        ),
        md(
            """
            The checks compare exact strings, so every space counts.
            """
        ),
        code(
            """
            run_checks(
                [
                    (
                        "basic line",
                        lambda: format_receipt_line("Masala Dosa", 2, Decimal("120")),
                        "Masala Dosa            2 x     120.00      240.00",
                    ),
                    (
                        "long name is truncated with …",
                        lambda: format_receipt_line("Paneer Butter Masala Special", 1, Decimal("320.5")),
                        "Paneer Butter Masal…   1 x     320.50      320.50",
                    ),
                    (
                        "thousands separators",
                        lambda: format_receipt_line("Wedding Catering", 3, Decimal("125000")),
                        "Wedding Catering       3 x 125,000.00  375,000.00",
                    ),
                    (
                        "always 49 characters",
                        lambda: {
                            len(format_receipt_line(name, count, Decimal(price)))
                            for name, count, price in [("Tea", 1, "10"), ("A" * 40, 99, "9999.99")]
                        },
                        {49},
                    ),
                ]
            )
            """
        ),
        md(
            """
            #### Exercise 3 — search-query normalization

            Write `normalize_search_query(raw_query: str) -> str` so that differently typed
            queries match the same search index entry:

            1. Normalize with **NFKD**, then drop every combining mark (`unicodedata.combining`
               returns non-zero for them), so `é` becomes `e`.
            2. Casefold.
            3. Turn every character that is not alphanumeric into a space.
            4. Collapse whitespace runs into single spaces and strip the edges.

            `normalize_search_query("  Café   CRÈME! ") == "cafe creme"`.

            > **Note:** dropping marks is right for accented Latin text but wrong for scripts such
            > as Devanagari, where marks are part of the letters. Real search engines use
            > per-language analyzers.
            """
        ),
        code(
            '''
            def normalize_search_query(raw_query: str) -> str:
                """Return a lowercase, accent-free, single-spaced version of a search query."""
                raise NotImplementedError("Lab 1.4: implement normalize_search_query()")
            '''
        ),
        md(
            """
            Run the checks.
            """
        ),
        code(
            """
            run_checks(
                [
                    ("accents and case", lambda: normalize_search_query("  Café   CRÈME! "), "cafe creme"),
                    (
                        "punctuation becomes spaces",
                        lambda: normalize_search_query("Masala-Dosa,  Bengaluru"),
                        "masala dosa bengaluru",
                    ),
                    ("full-width text", lambda: normalize_search_query("ＤＯＳＡ ２０２６"), "dosa 2026"),
                    (
                        "ß and SS match",
                        lambda: normalize_search_query("Straße") == normalize_search_query("STRASSE"),
                        True,
                    ),
                    ("empty query", lambda: normalize_search_query(""), ""),
                    ("only punctuation", lambda: normalize_search_query("!!! ???"), ""),
                ]
            )
            """
        ),
    ]


def _recap_cells() -> list[NotebookNode]:
    """Recap for Unit 1.4."""
    return [
        md(
            """
            ### Recap — Unit 1.4

            | Concept | One-line takeaway | JS equivalent |
            | --- | --- | --- |
            | `str` | Immutable sequence of code points; every method returns a new string | `string` |
            | `len` | Counts code points, not UTF-16 units or visible characters | `.length` (UTF-16 units) |
            | PEP 393 | CPython stores 1, 2 or 4 bytes per character, chosen per string | — |
            | Slicing | `[start:stop:step]`, `[::-1]`; slices never raise | `slice()`, `at()` |
            | `strip(chars)` | Removes a *set* of characters; use `removeprefix`/`removesuffix` for exact text | `trim()` |
            | `split` / `partition` | `split()` for whitespace, `split(sep)` keeps empty fields, `partition` always gives 3 parts | `split()` |
            | `isdecimal` | The numeric test that matches what `int()` accepts | `/^\\d+$/` |
            | f-strings | Expressions, `=` debugging, `!r`, nested specs, multi-line (3.12+) | template literals |
            | Format spec | `fill align sign # width , .precision type`, plus `strftime` codes for dates | `toLocaleString`, `toFixed` |
            | t-strings (3.14) | `Template` objects that a renderer escapes safely | tagged templates |
            | Normalization | NFC before comparing; NFKC/NFKD also fold look-alike characters | `normalize("NFC")` |
            | `casefold` | Use for caseless comparison (`ß` → `ss`) | `toLowerCase()` (not enough) |
            | `bytes` / `bytearray` | Binary data; indexing gives `int`; encode/decode at the boundary | `Uint8Array`, `Buffer` |
            | `errors=` | `strict`, `replace`, `ignore`, `backslashreplace` | `TextDecoder({fatal})` |
            | UTF-8 mode (3.15) | `open()` defaults to UTF-8 everywhere (PEP 686) | — |
            | `memoryview` | Zero-copy slices of a buffer | `subarray()` |

            **Further reading**

            - [Text sequence type — `str`](https://docs.python.org/3/library/stdtypes.html#text-sequence-type-str),
              [string methods](https://docs.python.org/3/library/stdtypes.html#string-methods)
            - [Format specification mini-language](https://docs.python.org/3/library/string.html#format-specification-mini-language),
              [f-strings](https://docs.python.org/3/reference/lexical_analysis.html#f-strings),
              [`string.templatelib`](https://docs.python.org/3/library/string.templatelib.html)
            - [Unicode HOWTO](https://docs.python.org/3/howto/unicode.html),
              [`unicodedata`](https://docs.python.org/3/library/unicodedata.html)
            - [Binary sequence types — `bytes`, `bytearray`, `memoryview`](https://docs.python.org/3/library/stdtypes.html#binary-sequence-types-bytes-bytearray-memoryview),
              [codec error handlers](https://docs.python.org/3/library/codecs.html#error-handlers)
            - [PEP 393 — Flexible string representation](https://peps.python.org/pep-0393/),
              [PEP 498 — Literal string interpolation](https://peps.python.org/pep-0498/),
              [PEP 701 — Syntactic formalization of f-strings](https://peps.python.org/pep-0701/),
              [PEP 750 — Template strings](https://peps.python.org/pep-0750/),
              [PEP 686 — Make UTF-8 mode default](https://peps.python.org/pep-0686/)
            """
        ),
    ]


def cells() -> list[NotebookNode]:
    """Return the cells for Unit 1.4 and Lab 1.4."""
    return [
        *_overview_cells(),
        *_str_fundamentals_cells(),
        *_str_methods_cells(),
        *_formatting_cells(),
        *_unicode_cells(),
        *_bytes_cells(),
        *_use_case_cells(),
        *_lab_cells(),
        *_recap_cells(),
    ]
