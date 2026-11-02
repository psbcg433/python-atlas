"""Unit 1.8 — Operators, Expressions and Control Flow (with Lab 1.8)."""

from nbformat import NotebookNode

from nb_builder import code, md, predict_cells

UNIT_SETUP_SOURCE = '''
import dis
import re
import sys
from collections.abc import Callable, Hashable, Iterable
from http import HTTPStatus
from typing import Any


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


def compile_error(source: str) -> str:
    """Compile source without running it; return "SyntaxError: <message>" or "compiles"."""
    try:
        compile(source, "<demo>", "exec")
    except SyntaxError as error:
        return f"SyntaxError: {error.msg}"
    return "compiles"


print(f"{sys.version_info[:2]=}")
'''


def _overview_cells() -> list[NotebookNode]:
    """Unit opener and setup."""
    return [
        md(
            r"""
            ## Unit 1.8 — Operators, Expressions and Control Flow

            **Objectives**

            - Use every operator family, read the precedence table, and write chained
              comparisons.
            - Explain why `and` / `or` return one of their operands, and avoid the
              `value or default` trap.
            - Write conditionals, guard clauses and structural pattern matching (`match`) with
              every pattern kind.
            - Use `for`, `while`, `break`, `continue` and the `else` clause of loops.
            - Use every assignment form, including the walrus operator, and `*` / `**` unpacking.

            **JS bridge**

            | JavaScript concept | Python equivalent | The difference that bites |
            | --- | --- | --- |
            | `a === b` | `a == b` (value), `a is b` (identity) | No coercion: `1 == "1"` is `False`; `==` calls `__eq__` |
            | `&&`, `\|\|`, `!` | `and`, `or`, `not` | Words, not symbols; `not` always returns a `bool` |
            | `a ?? b` | `a if a is not None else b` | No `??` operator; `a or b` also replaces `0` and `""` |
            | `c ? a : b` | `a if c else b` | The condition sits in the middle |
            | `a < b && b < c` | `a < b < c` | Chained comparisons are real syntax |
            | `-7 % 3` is `-1` | `-7 % 3` is `2` | `%` takes the sign of the divisor; `//` floors |
            | `5 & 1 == 0` is `5 & (1 == 0)` | `5 & 1 == 0` is `(5 & 1) == 0` | Bitwise operators bind tighter than comparisons |
            | `switch` / `case` / `break` | `match` / `case` | No fall-through; patterns destructure and bind names |
            | `for (let i = 0; i < n; i++)` | `for index in range(n)` | No C-style loop, no `++` |
            | `for (const x of items)` | `for item in items` | Works on any iterable |
            | `"key" in obj` | `key in mapping` | `in` on a list searches **values** |
            | `const [first, ...rest] = items` | `first, *rest = items` | `rest` is always a `list` |

            The next cell is this unit's setup. `compile_error(source)` compiles a snippet without
            running it and reports a `SyntaxError`, so illegal code can be shown safely.
            """
        ),
        code(UNIT_SETUP_SOURCE),
    ]


def _operator_cells() -> list[NotebookNode]:
    """1.8.1 Operators and precedence."""
    return [
        md(
            """
            ### 1.8.1 Operators and precedence

            | Family | Operators |
            | --- | --- |
            | Arithmetic | `+`, `-`, `*`, `/` (true division), `//` (floor division), `%`, `**`, `@` (matrix, for libraries) |
            | Comparison | `==`, `!=`, `<`, `<=`, `>`, `>=` |
            | Logical | `and`, `or`, `not` |
            | Bitwise | `&`, `\\|`, `^`, `~`, `<<`, `>>` |
            | Membership | `in`, `not in` |
            | Identity | `is`, `is not` |

            **Arithmetic.** `/` always returns a `float`; `//` floors toward negative infinity,
            and `%` takes the sign of the **divisor**, so `a == (a // b) * b + a % b` always holds.
            JavaScript's `%` takes the sign of the dividend, so negative numbers differ.
            """
        ),
        code(
            """
            items_in_stock, box_size = 17, 5
            print(f"{items_in_stock + box_size=}, {items_in_stock - box_size=}, {items_in_stock * box_size=}")
            print(f"{items_in_stock / box_size=}, {items_in_stock // box_size=}, {items_in_stock % box_size=}")
            print(f"{2**10=}, {-items_in_stock=}, {+items_in_stock=}")
            print(f"{-7 // 2=}, {-7 % 3=}  (JS: Math.trunc(-7 / 2) is -3, -7 % 3 is -1)")
            print(f"{divmod(-7, 3)=}, {(-7 // 3) * 3 + (-7 % 3)=}")
            print(f"{4 / 2=}  (true division always gives a float)")
            """
        ),
        md(
            """
            **Comparison.** `==` compares values (calls `__eq__`) with **no type coercion**:
            numbers of different types compare by value, but a string never equals a number.
            Ordering between unrelated types raises `TypeError` instead of guessing. Sequences
            compare element by element (lexicographically).
            """
        ),
        code(
            """
            print(f"{1 == 1.0=}, {1 == '1'=}, {1 != '1'=}")
            print(f"{'apple' < 'banana'=}, {'Zebra' < 'apple'=}  (code point order: 'Z' < 'a')")
            print(f"{[1, 2, 3] < [1, 3]=}, {(2026, 11) >= (2026, 10)=}")
            print(f"'10' < 5: {raised_error_name(lambda: '10' < 5)}")
            """
        ),
        md(
            """
            **Logical.** `and`, `or`, `not` work on truthiness (1.3.8). 1.8.2 shows that `and`
            and `or` return an operand, not necessarily a `bool`.
            """
        ),
        code(
            """
            is_logged_in, has_items = True, False
            print(f"{is_logged_in and has_items=}, {is_logged_in or has_items=}, {not has_items=}")
            print(f"{not []=}, {not 'text'=}")
            """
        ),
        md(
            """
            **Bitwise.** They work on the binary digits of ints. Python ints have arbitrary
            precision, so shifts never overflow (JavaScript truncates bitwise operands to 32 bits).
            `~x` is `-x - 1`. A typical use is a set of permission flags packed into one int.
            """
        ),
        code(
            """
            READ, WRITE, DELETE = 0b001, 0b010, 0b100
            editor_permissions = READ | WRITE
            print(f"{editor_permissions=:03b}, {editor_permissions & WRITE != 0=}")
            print(f"{editor_permissions & DELETE != 0=}  (& binds tighter than !=)")
            print(f"{editor_permissions ^ WRITE=:03b}  (toggle WRITE off)")
            print(f"{~5=}, {1 << 4=}, {256 >> 2=}")
            print(f"{1 << 100=}  (no 32-bit overflow)")
            """
        ),
        md(
            """
            **Membership.** `x in container` asks the container (`__contains__`): a list or
            tuple searches values (O(n)), a `str` searches for a **substring**, a dict checks
            **keys**, and a set checks elements in O(1) on average.
            """
        ),
        code(
            """
            print(f"{'tea' in ['tea', 'rice']=}, {'ghee' not in ('tea', 'rice')=}")
            print(f"{'err' in 'server error'=}  (substring)")
            print(f"{'tea' in {'tea': 249}=}, {249 in {'tea': 249}=}  (keys only)")
            print(f"{249 in {'tea': 249}.values()=}, {101 in {101, 102}=}")
            """
        ),
        md(
            """
            **Identity.** `is` checks that two names refer to the **same object**. Use it for
            singletons (`None`, `True`, `False`, sentinels), never for comparing numbers or
            strings (1.2.5).
            """
        ),
        code(
            """
            discount_code = None
            saved_cart = ["tea"]
            same_cart = saved_cart
            fresh_cart = ["tea"]
            print(f"{discount_code is None=}, {saved_cart is same_cart=}, {saved_cart is not fresh_cart=}")
            print(f"{saved_cart == fresh_cart=}  (equal values, different objects)")
            """
        ),
        md(
            """
            **Precedence**, from highest (binds tightest) to lowest:

            | Level | Operators |
            | --- | --- |
            | 1 | `(...)`, `[...]`, `{...}` displays |
            | 2 | `x[index]`, `x[start:stop]`, `f(args)`, `x.attribute` |
            | 3 | `await x` |
            | 4 | `**` (right-associative; binds tighter than a unary minus on its left) |
            | 5 | `+x`, `-x`, `~x` |
            | 6 | `*`, `@`, `/`, `//`, `%` |
            | 7 | `+`, `-` |
            | 8 | `<<`, `>>` |
            | 9 | `&` |
            | 10 | `^` |
            | 11 | `\\|` |
            | 12 | `in`, `not in`, `is`, `is not`, `<`, `<=`, `>`, `>=`, `!=`, `==` (all one level, chainable) |
            | 13 | `not x` |
            | 14 | `and` |
            | 15 | `or` |
            | 16 | `x if condition else y` |
            | 17 | `lambda` |
            | 18 | `:=` |

            The next cell shows the cases that surprise people. When in doubt, add parentheses.
            """
        ),
        code(
            """
            print(f"{-2**2=}  (** first: -(2**2))")
            print(f"{2**3**2=}  (right-associative: 2**(3**2))")
            print(f"{1 + 2 * 3=}, {(1 + 2) * 3=}")
            print(f"{5 & 1 == 0=}  ((5 & 1) == 0, unlike JS where == binds first)")
            print(f"{not 1 == 2=}  (not (1 == 2))")
            print(f"{True or False and False=}  (and before or)")
            """
        ),
        *predict_cells(
            snippet="""
            print(-3**2, 2**-1, 7 // -2, -7 % 3)
            """,
            answer="""
            `-9 0.5 -4 2`. `**` binds tighter than the unary minus on its left, so `-3**2` is
            `-(3**2)`; a negative exponent gives a float; `//` floors toward negative infinity
            (`-3.5` → `-4`); `%` takes the sign of the divisor, so `-7 % 3` is `2`.
            """,
            proof="""
            print(-3**2, 2**-1, 7 // -2, -7 % 3)  # fmt: skip
            """,
        ),
        md(
            """
            **Chained comparisons.** `0 < age <= 120` means `0 < age and age <= 120`, except that
            `age` is evaluated **once**. Any comparison operators can chain, which allows
            `low <= value < high` range checks and `a == b == c`. It also allows confusing
            chains such as `x < y > z`; avoid those.
            """
        ),
        code(
            '''
            def is_valid_age(age: int) -> bool:
                """Return True for a plausible human age."""
                return 0 < age <= 120


            print(f"{is_valid_age(35)=}, {is_valid_age(0)=}, {is_valid_age(130)=}")
            first_price, second_price, third_price = 249, 249, 249
            print(f"{first_price == second_price == third_price=}")
            print(f"{1 < 3 > 2=}  (legal but unclear: 1 < 3 and 3 > 2)")
            print(f"{(1 < 2) == True=}, {1 < 2 == True=}  (1 < 2 and 2 == True)")  # noqa: E712
            '''
        ),
        md(
            """
            #### Under the hood: a chained comparison in bytecode

            `dis` shows how `0 < age <= 120` evaluates `age` once: it is loaded a single time,
            `COPY` duplicates it for the second comparison, and a conditional jump skips the
            second comparison when the first is false (short-circuit). Opcode names vary between
            Python versions.
            """
        ),
        code(
            """
            dis.dis(is_valid_age)
            """
        ),
    ]


def _boolean_operand_cells() -> list[NotebookNode]:
    """1.8.2 Boolean operators return operands."""
    return [
        md(
            """
            ### 1.8.2 Boolean operators return operands

            `and` and `or` short-circuit like JavaScript's `&&` and `||`, and like them they
            return **one of their operands**, not `True` / `False`:

            | Expression | Returns |
            | --- | --- |
            | `a or b` | `a` if `a` is truthy, else `b` |
            | `a and b` | `a` if `a` is falsy, else `b` |
            | `not a` | always a `bool` |

            The right operand is evaluated **only if needed**. The next cell uses a function
            with a visible side effect to prove which operands run.
            """
        ),
        code(
            '''
            def loud(value: object) -> object:
                """Print the value, then return it (to see which operands are evaluated)."""
                print(f"  evaluated {value!r}")
                return value


            print(f"result {loud('') or loud('guest')!r}")
            print(f"result {loud('asha') or loud('guest')!r}  (right side skipped)")
            print(f"result {loud(0) and loud(1 / 1)!r}  (right side skipped)")
            print(f"{[] and 1 / 0=}  (1 / 0 never runs)")
            print(f"{not 'asha'=}, {not 0=}, {type(not 'asha').__name__=}")
            '''
        ),
        md(
            """
            **`value or default` and its `0` trap.** `or` is a handy default, but it replaces
            **every** falsy value: `0`, `0.0`, `""`, `[]`, `False`; not only `None`. If those are
            valid inputs, it silently changes them.

            Python has no `??` (null-coalescing) operator (PEP 505 proposed one and was deferred).
            The explicit form is a conditional expression on `is not None`.
            """
        ),
        code(
            '''
            def items_per_page_with_or(requested: int | None) -> int:
                """Default to 20 when nothing was requested (buggy: 0 is replaced too)."""
                return requested or 20


            def items_per_page(requested: int | None) -> int:
                """Default to 20 only when requested is None (the JS `requested ?? 20`)."""
                return requested if requested is not None else 20


            for requested in (None, 50, 0):
                print(
                    f"{requested=}: with or -> {items_per_page_with_or(requested)}, "
                    f"with is not None -> {items_per_page(requested)}"
                )
            display_name = "" or "Anonymous"
            print(f"{display_name=}  (fine here: an empty name should get the default)")
            '''
        ),
        md(
            """
            An `or` chain picks the first truthy value, which reads well for layered settings
            when empty values really mean "not set":
            """
        ),
        code(
            """
            cli_region, env_region, default_region = None, "", "ap-south-1"
            chosen_region = cli_region or env_region or default_region
            print(f"{chosen_region=}")
            """
        ),
    ]


def _conditional_cells() -> list[NotebookNode]:
    """1.8.3 Conditionals."""
    return [
        md(
            """
            ### 1.8.3 Conditionals

            `if` / `elif` / `else` with a colon and an indented block; no parentheses around the
            condition and no braces. Any object can be a condition (truthiness, 1.3.8). The first
            true branch runs and the rest are skipped.
            """
        ),
        code(
            '''
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
            '''
        ),
        md(
            """
            **Conditional expression:** `value_if_true if condition else value_if_false` is an
            *expression* (it has a value), the equivalent of JavaScript's `c ? a : b`. Keep it to
            one simple condition; nested conditional expressions are hard to read, use
            `if` / `elif` instead.
            """
        ),
        code(
            """
            stock_count = 0
            availability = "in stock" if stock_count > 0 else "sold out"
            print(f"{availability=}")
            plural_suffix = "" if stock_count == 1 else "s"
            print(f"{stock_count} item{plural_suffix} left")
            """
        ),
        md(
            """
            **Guard clauses** handle the special cases first and `return` (or `raise`) early, so
            the main path is not buried in nested `if` blocks. Both functions below behave the
            same; the second is flat.
            """
        ),
        code(
            '''
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


            pending_order = {"order_id": 1001, "paid": True, "items": ["tea"], "address": ""}
            print(f"{ship_order_nested(pending_order)=}, {ship_order(pending_order)=}")
            '''
        ),
        md(
            """
            A block cannot be empty: use `pass` as a placeholder (or `...`). There is no
            `else if`; it is spelled `elif`.
            """
        ),
        code(
            """
            log_level = "DEBUG"
            if log_level == "DEBUG":
                pass  # nothing to do yet; the block must not be empty
            print(f"{compile_error('if True:' + chr(10) + 'print(1)')=}")
            """
        ),
    ]


def _match_cells() -> list[NotebookNode]:
    """1.8.4 Structural pattern matching."""
    return [
        md(
            """
            ### 1.8.4 Structural pattern matching (`match`)

            `match subject:` compares one value against `case` patterns, top to bottom, and runs
            the **first** case that matches (PEP 634, Python 3.10). A pattern describes the
            *shape* of the data and can bind parts of it to names.

            | Pattern | Example | Matches |
            | --- | --- | --- |
            | Literal | `case 200:` | equal value (`None`, `True`, `False` by identity) |
            | Or | `case 401 \\| 403:` | any of the alternatives |
            | Capture | `case other:` | anything; binds it to `other` |
            | Wildcard | `case _:` | anything; binds nothing |
            | Sequence | `case ["deploy", env]:`, `case [cmd, *args]:` | lists/tuples of that length and shape (not `str`) |
            | Mapping | `case {"type": event_type, **rest}:` | mappings with those keys (extra keys allowed) |
            | Class | `case Point(x=0, y=y):`, `case Point(0, y):` | `isinstance` plus attributes |
            | Value | `case HTTPStatus.NOT_FOUND:` | equal to a dotted name |
            | Guard | `case [x, y] if x == y:` | the pattern **and** the condition |
            | As | `case [("start" \\| "stop") as action, name]:` | binds a sub-pattern's value |

            Each of the next cells shows one pattern kind.

            **Literal patterns** compare with `==` (and `is` for `None`, `True`, `False`):
            """
        ),
        code(
            '''
            def describe_status(status_code: int) -> str:
                """Describe an HTTP status code with literal patterns."""
                match status_code:
                    case 200:
                        return "OK"
                    case 404:
                        return "Not Found"
                    case _:
                        return "something else"


            print(f"{describe_status(200)=}, {describe_status(404)=}, {describe_status(418)=}")
            '''
        ),
        md("**Or patterns** (`|`) try several alternatives in one case:"),
        code(
            '''
            def status_family(status_code: int) -> str:
                """Group status codes with or-patterns."""
                match status_code:
                    case 200 | 201 | 204:
                        return "success"
                    case 401 | 403:
                        return "auth problem"
                    case _:
                        return "other"


            print(f"{status_family(201)=}, {status_family(403)=}, {status_family(500)=}")
            '''
        ),
        md(
            """
            **Capture patterns**: a bare name matches **anything** and binds it. A capture as a
            whole case is irrefutable, so it must be the last case.
            """
        ),
        code(
            '''
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
            '''
        ),
        md(
            """
            **Wildcard `_`** matches anything and binds nothing (it is not a variable). It is
            the `default:` of a `switch`, and it can stand in for parts of other patterns.
            """
        ),
        code(
            '''
            def first_word_kind(words: list[str]) -> str:
                """Use _ alone and inside a sequence pattern."""
                match words:
                    case ["help", _]:
                        return "help with a topic"
                    case _:
                        return "anything else"


            print(f"{first_word_kind(['help', 'deploy'])=}, {first_word_kind(['status'])=}")
            '''
        ),
        md(
            """
            **Sequence patterns** match lists and tuples by length and element patterns;
            `*rest` collects any remaining elements into a list. Strings, bytes and bytearrays
            are **not** treated as sequences here, so `"abc"` does not match `[a, b, c]`.
            """
        ),
        code(
            '''
            def describe_words(words: list[str]) -> str:
                """Match on the shape of a split command."""
                match words:
                    case []:
                        return "empty"
                    case [single_word]:
                        return f"one word: {single_word}"
                    case [command, *arguments]:
                        return f"{command} with {len(arguments)} argument(s): {arguments}"


            print(describe_words([]))
            print(describe_words(["status"]))
            print(describe_words(["copy", "a.txt", "b.txt"]))
            print(f"{describe_words('ab')=}  (a str never matches a sequence pattern)")
            '''
        ),
        md(
            """
            **Mapping patterns** check that the listed keys exist and match their value
            patterns. Extra keys are **ignored**; `**rest` captures them into a dict.
            """
        ),
        code(
            '''
            def describe_event(event: dict[str, Any]) -> str:
                """Match dicts by their keys."""
                match event:
                    case {"type": "login", "user": user_name}:
                        return f"login by {user_name}"
                    case {"type": event_type, **other_fields}:
                        return f"{event_type} event with extra keys {sorted(other_fields)}"
                    case _:
                        return "not an event"


            print(describe_event({"type": "login", "user": "asha", "ip": "10.0.0.1"}))
            print(describe_event({"type": "logout", "user": "ravi", "reason": "timeout"}))
            print(describe_event({"user": "meena"}))
            '''
        ),
        md(
            """
            **Class patterns** check `isinstance` and then attributes. Keyword sub-patterns
            (`Point(x=0)`) name attributes directly. Positional sub-patterns (`Point(0, y)`) use
            the class attribute `__match_args__` to know which attribute each position means.
            Dataclasses and named tuples generate `__match_args__` for you (Phase 2); here it is
            written by hand. Built-in types such as `int(n)` and `str(s)` match the whole value.
            """
        ),
        code(
            '''
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
            '''
        ),
        md(
            """
            **Guards**: `case pattern if condition:` matches only when the pattern matches **and**
            the condition (which can use the bound names) is true. If the guard fails, matching
            continues with the next case.
            """
        ),
        code(
            '''
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


            print(f"{classify_pair((3, 3))=}, {classify_pair((5, 1))=}, {classify_pair((1, 5))=}")
            '''
        ),
        md(
            """
            **`as` bindings** name the value matched by a sub-pattern, which is useful after an
            or-pattern (you know *that* it matched, `as` tells you *which*).
            """
        ),
        code(
            '''
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
            '''
        ),
        md(
            """
            **No fall-through.** Exactly one case runs (or none: then nothing happens, there is
            no error). There is no `break`, and no way to fall into the next case. Compare:

            | | JavaScript `switch` | Python `match` |
            | --- | --- | --- |
            | Comparison | `===` against each `case` value | structural patterns (shape, type, keys, values) |
            | After a match | falls through until `break` | runs one case, then leaves |
            | Several values | stacked `case 1: case 2:` | `case 1 \\| 2:` |
            | Destructuring | no | binds names from the subject |
            | Conditions | no (use `if`) | guards: `case ... if condition:` |
            | Default | `default:` | `case _:` |
            | No match | nothing happens | nothing happens |
            """
        ),
        code(
            '''
            def count_matches(signal: str) -> list[str]:
                """Show that only the first matching case runs."""
                ran_cases = []
                match signal:
                    case "go":
                        ran_cases.append("first go case")
                    case "go":  # also matches, but never runs
                        ran_cases.append("second go case")
                return ran_cases


            print(f"{count_matches('go')=}, {count_matches('stop')=}  (no match is not an error)")
            '''
        ),
        md(
            """
            **The bare-name capture trap.** A bare name in a pattern is a **capture**, never a
            constant lookup. `case NOT_FOUND:` does not compare with your variable `NOT_FOUND`;
            it matches everything and **rebinds** `NOT_FOUND`. If more cases follow, Python
            refuses to compile it; if it is the last case, it silently "works".
            """
        ),
        code(
            '''
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
            '''
        ),
        md(
            """
            **Dotted names are value patterns.** Any name with a dot (`HTTPStatus.NOT_FOUND`,
            `config.LIMIT`) is looked up and compared with `==`. That is why enums and constants
            on a class or module work as cases. `HTTPStatus` is an `IntEnum`, so its members also
            equal plain ints.
            """
        ),
        code(
            '''
            def describe_with_enum(status_code: int) -> str:
                """Use dotted names as constant (value) patterns."""
                match status_code:
                    case HTTPStatus.OK:
                        return "OK"
                    case HTTPStatus.NOT_FOUND:
                        return "Not Found"
                    case _:
                        return "other"


            print(f"{describe_with_enum(404)=}, {describe_with_enum(200)=}, {describe_with_enum(500)=}")
            '''
        ),
        md(
            """
            **Demo: a command parser.** A tiny deploy tool turns a command line into an action.
            Sequence patterns pick the command apart, or-patterns accept aliases, guards
            validate arguments, and `*` handles optional flags.
            """
        ),
        code(
            '''
            def run_deploy_command(command_text: str) -> str:
                """Parse a deploy-tool command and describe the action it would take."""
                match command_text.split():
                    case ["deploy", ("staging" | "production") as environment]:
                        return f"deploying to {environment}"
                    case ["deploy", environment]:
                        return f"error: unknown environment {environment!r}"
                    case ["rollback", version] if re.fullmatch(r"v\\d+\\.\\d+\\.\\d+", version):
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
            '''
        ),
        md(
            """
            **Demo: a webhook router.** A payment provider posts JSON events. Mapping patterns
            route them by `type`, nested patterns pull out fields, class patterns (`int(amount)`)
            check types, guards check values, and `**rest` keeps unknown fields. Phase 6 builds
            a real FastAPI endpoint around this idea.
            """
        ),
        code(
            '''
            def route_webhook(event: dict[str, Any]) -> str:
                """Route a payment-provider webhook event to a handler description."""
                match event:
                    case {"type": "payment.captured", "data": {"amount": int(amount), "currency": "INR"}}:
                        return f"mark order paid: ₹{amount / 100:,.2f}"
                    case {"type": "payment.failed", "data": {"reason": str(reason)}}:
                        return f"notify customer: payment failed ({reason})"
                    case {"type": "refund.created", "data": {"amount": int(amount)}} if amount > 1_000_000:
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
            '''
        ),
        md(
            """
            #### Under the hood: `match` opcodes

            `match` compiles to ordinary bytecode plus a few dedicated instructions:
            `MATCH_SEQUENCE`, `MATCH_MAPPING`, `MATCH_KEYS` and `MATCH_CLASS`. The next cell
            collects them from the two demo functions above. There is no jump
            table: the cases are tried in order, as a chain of tests. Opcode names vary by
            version.
            """
        ),
        code(
            """
            match_opcodes = {
                instruction.opname
                for matcher in (run_deploy_command, route_webhook)
                for instruction in dis.get_instructions(matcher)
                if instruction.opname.startswith("MATCH_")
            }
            print(f"{sorted(match_opcodes)=}")
            """
        ),
    ]


def _loop_cells() -> list[NotebookNode]:
    """1.8.5 Loops."""
    return [
        md(
            """
            ### 1.8.5 Loops

            Python has two loops. `for` iterates over **any iterable** (list, tuple, str, dict,
            set, range, file, generator); there is no C-style `for (init; cond; step)`. For
            counting, iterate over a `range`.
            """
        ),
        code(
            """
            for product_name in ["tea", "rice"]:
                print(f"list item: {product_name}")
            for character in "OK":
                print(f"str character: {character}")
            for sku, unit_price in {"TEA-500G": 249, "GHEE-1L": 640}.items():
                print(f"dict item: {sku} = {unit_price}")
            for even_number in range(0, 7, 2):  # JS: for (let n = 0; n < 7; n += 2)
                print(f"range value: {even_number}")
            print(f"{even_number=}  (the loop variable still exists after the loop)")
            """
        ),
        md(
            """
            `while condition:` repeats while the condition is truthy, for loops where the number
            of iterations is not known in advance.
            """
        ),
        code(
            """
            remaining_stock = 10
            orders_served = 0
            while remaining_stock >= 3:
                remaining_stock -= 3
                orders_served += 1
            print(f"{orders_served=}, {remaining_stock=}")
            """
        ),
        md(
            "`break` leaves the innermost loop immediately; `continue` skips to the next iteration."
        ),
        code(
            """
            log_lines = ["INFO start", "DEBUG cache warm", "ERROR db down", "INFO retry"]
            for log_line in log_lines:
                if log_line.startswith("DEBUG"):
                    continue  # skip noise
                if log_line.startswith("ERROR"):
                    print(f"stopping at: {log_line}")
                    break
                print(f"processing: {log_line}")
            """
        ),
        md(
            """
            **`for ... else`**: the `else` block runs when the loop finishes **without `break`**.
            Read it as "no break". It replaces the `found = False` flag pattern for searches.
            """
        ),
        code(
            '''
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
            '''
        ),
        md(
            """
            **`while ... else`** works the same way: `else` runs when the condition becomes false,
            not when the loop is left with `break`. The example retries a flaky operation.
            """
        ),
        code(
            '''
            def connect_with_retries(responses: list[bool], max_attempts: int) -> str:
                """Try up to max_attempts times; responses[i] is the result of attempt i."""
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
            '''
        ),
        md(
            """
            **Do-while emulation.** Python has no `do { ... } while (cond)`. Use `while True:`
            with a `break` at the bottom, so the body always runs at least once.
            """
        ),
        code(
            """
            pending_pages = ["page-3", "page-2", "page-1"]
            fetched_pages = []
            while True:
                fetched_pages.append(pending_pages.pop())  # the body runs at least once
                if not pending_pages:
                    break
            print(f"{fetched_pages=}")
            """
        ),
    ]


def _assignment_cells() -> list[NotebookNode]:
    """1.8.6 Assignment forms."""
    return [
        md(
            """
            ### 1.8.6 Assignment forms

            | Form | Example | Notes |
            | --- | --- | --- |
            | Simple | `total = 0` | binds a name |
            | Augmented | `total += price` | in place for mutable objects, rebinding for immutable ones |
            | Multiple targets | `low = high = 0` | every name gets the **same** object |
            | Unpacking | `name, price = row` | counts must match (or use `*`) |
            | Walrus | `if (match := pattern.search(line)):` | an assignment **expression** (PEP 572) |

            **Augmented assignment** (`+=`, `-=`, `*=`, `/=`, `//=`, `%=`, `**=`, `&=`, `|=`,
            `^=`, `<<=`, `>>=`, `@=`) calls the in-place method (`__iadd__`, …) if the type has
            one, so a list is changed **in place**; immutable types have none and get a new
            object. There is no `++` / `--`.
            """
        ),
        code(
            """
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
            """
        ),
        md(
            """
            **Multiple targets**: `a = b = value` evaluates `value` once and binds every target to
            **that one object**. Harmless for immutable values, a trap for mutable ones (Lab 1.5,
            exercise 4).
            """
        ),
        code(
            """
            low_score = high_score = 0
            high_score += 10  # rebinding high_score; low_score keeps 0
            print(f"{low_score=}, {high_score=}")

            pending_ids = done_ids = []
            pending_ids.append(1001)  # one list, two names
            print(f"{done_ids=}  (the trap)")
            """
        ),
        md(
            """
            **Unpacking assignment**: any iterable on the right, a matching number of targets on
            the left. It swaps without a temporary, and nests.
            """
        ),
        code(
            """
            sku, unit_price = ("TEA-500G", 249)
            print(f"{sku=}, {unit_price=}")
            first_slot, second_slot = "morning", "evening"
            first_slot, second_slot = second_slot, first_slot  # swap: the right side is a tuple
            print(f"{first_slot=}, {second_slot=}")
            store_name, (latitude, longitude) = ("Indiranagar", (12.97, 77.64))
            print(f"{store_name=}, {latitude=}, {longitude=}")
            print(f"too many values: {raised_error_name(lambda: exec('a, b = 1, 2, 3'))}")
            """
        ),
        md(
            """
            **The walrus operator `:=`** (PEP 572, Python 3.8) assigns **and** returns the value
            inside an expression. It avoids computing something twice, or splitting "compute,
            then test" into two statements. Typical places: `while` conditions, `if` with a regex
            match, and comprehension filters.
            """
        ),
        code(
            """
            order_line_pattern = re.compile(r"(?P<sku>[A-Z]+-\\w+) x(?P<quantity>\\d+)")
            raw_line = "order 1001: TEA-500G x2"
            if (line_match := order_line_pattern.search(raw_line)) is not None:
                print(f"{line_match['sku']=}, {int(line_match['quantity'])=}")

            pending_jobs = ["resize", "upload", "notify"]
            while (current_job := pending_jobs.pop(0) if pending_jobs else None) is not None:
                print(f"running {current_job}")

            prices = [120, 499, 999, 1500]
            with_gst = [taxed for price in prices if (taxed := round(price * 1.18)) > 600]
            print(f"{with_gst=}")
            """
        ),
        md(
            """
            **Walrus scope rules:**

            - In a comprehension, `:=` binds in the **enclosing** scope (on purpose, so you can
              keep the last value or a "witness"); the comprehension's own loop variable does not
              leak (1.9.3).
            - It cannot rebind a comprehension's iteration variable.
            - An unparenthesized `:=` is not allowed as a top-level statement (use `=`), and it
              is not allowed for attributes or subscripts (`obj.x := 1`).
            """
        ),
        code(
            """
            order_amounts = [250, 900, 1200]
            has_large = any((large_amount := candidate) > 1000 for candidate in order_amounts)
            print(f"{has_large=}, {large_amount=}  (the witness leaked out on purpose)")
            print(f"'candidate' defined outside: {'candidate' in dir()}")

            print(f"{compile_error('total := 5')=}")
            print(f"{compile_error('[i := 0 for i in range(3)]')=}")
            print(f"{compile_error('cart.total := 5')=}")
            print(f"{compile_error('(total := 5)')=}  (parenthesized is legal, but use = instead)")
            """
        ),
    ]


def _unpacking_cells() -> list[NotebookNode]:
    """1.8.7 Unpacking operators."""
    return [
        md(
            """
            ### 1.8.7 Unpacking operators

            `*` unpacks any iterable into positional items; `**` unpacks a mapping into
            `key=value` pairs. They work in three places:

            | Place | `*` | `**` |
            | --- | --- | --- |
            | Calls | `f(*args)` → positional arguments | `f(**options)` → keyword arguments |
            | Literals | `[*a, *b]`, `(*a, x)`, `{*a, *b}` | `{**defaults, **overrides}` |
            | Assignment targets | `first, *rest = items` | — |

            **In calls**:
            """
        ),
        code(
            '''
            def format_address(street: str, city: str, pin_code: str, country: str = "IN") -> str:
                """Join address parts into one line."""
                return f"{street}, {city} {pin_code}, {country}"


            address_parts = ["12 MG Road", "Bengaluru", "560001"]
            address_options = {"country": "India"}
            print(format_address(*address_parts))
            print(format_address(*address_parts, **address_options))
            print(*["tea", "rice", "ghee"], sep=" | ")
            '''
        ),
        md(
            """
            **In list, tuple, set and dict literals**: build a new container from several
            sources (the JS spread `[...a, ...b]` and `{...a, ...b}`). In dicts, later keys win.
            """
        ),
        code(
            """
            breakfast_items, lunch_items = ["idli", "dosa"], ("thali", "dosa")
            all_items = [*breakfast_items, *lunch_items, "chai"]
            unique_items = {*breakfast_items, *lunch_items}
            print(f"{all_items=}")
            print(f"{sorted(unique_items)=}, {(*breakfast_items, 'vada')=}")

            default_options = {"timeout": 10, "retries": 3}
            request_options = {**default_options, "timeout": 30, "verbose": True}
            print(f"{request_options=}")
            """
        ),
        md(
            """
            **In assignment targets**: one starred name collects "everything else" into a
            **list** (even when the source is a tuple or a string). At most one starred target is
            allowed per level.
            """
        ),
        code(
            """
            first_step, *middle_steps, last_step = ("cart", "address", "payment", "confirm")
            print(f"{first_step=}, {middle_steps=}, {last_step=}")
            head_char, *tail_chars = "UPI"
            print(f"{head_char=}, {tail_chars=}")
            *_, latest_version = ["v1.0.0", "v1.1.0", "v2.0.0"]
            print(f"{latest_version=}")
            only_item, *nothing_else = ["solo"]
            print(f"{nothing_else=}  (an empty list, not an error)")
            print(f"{compile_error('*first, *second = [1, 2, 3]')=}")
            """
        ),
        md(
            """
            **Unpacking in comprehensions** (*New in 3.15*, PEP 798): `[*batch for batch in
            batches]` flattens one level, and `{**layer for layer in layers}` merges dicts. On
            older versions it is a `SyntaxError`, so the cell compiles the expressions from
            strings behind the version check.
            """
        ),
        code(
            """
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
            """
        ),
    ]


def _lab_cells() -> list[NotebookNode]:
    """Lab 1.8."""
    return [
        md(
            """
            ### Lab 1.8

            Three exercises. For each, replace the `raise NotImplementedError` in the stub, then
            run the check cell. Until then the checks print FAIL; that is expected.

            #### Exercise 1 — `parse_command(command_text)` with `match`

            Parse a shopping-cart command line into a tuple. Split on whitespace and use one
            `match` statement:

            | Input | Result |
            | --- | --- |
            | `"add SKU"` | `("add", "SKU", 1)` |
            | `"add SKU QTY"` (QTY all digits and > 0) | `("add", "SKU", QTY as int)` |
            | `"add SKU QTY"` (anything else) | `("error", "quantity must be a positive integer")` |
            | `"remove SKU"` | `("remove", "SKU")` |
            | `"list"` or `"ls"` | `("list",)` |
            | `"checkout"` | `("checkout",)` |
            | `"quit"` or `"exit"` | `("quit",)` |
            | blank line | `("error", "empty command")` |
            | anything else | `("error", "unknown command: <first word>")` |

            Commands are case-sensitive; SKUs are returned as typed.
            """
        ),
        code(
            '''
            def parse_command(command_text: str) -> tuple[Any, ...]:
                """Parse a cart command into a tuple, using match."""
                raise NotImplementedError("Lab 1.8: implement parse_command()")
            '''
        ),
        md("Run the checks."),
        code(
            """
            run_checks(
                [
                    (
                        "add default quantity",
                        lambda: parse_command("add TEA-500G"),
                        ("add", "TEA-500G", 1),
                    ),
                    ("add with quantity", lambda: parse_command("add RICE-5KG 3"), ("add", "RICE-5KG", 3)),
                    ("extra spaces", lambda: parse_command("  add   GHEE-1L   2 "), ("add", "GHEE-1L", 2)),
                    (
                        "bad quantity",
                        lambda: parse_command("add TEA-500G two"),
                        ("error", "quantity must be a positive integer"),
                    ),
                    (
                        "zero quantity",
                        lambda: parse_command("add TEA-500G 0"),
                        ("error", "quantity must be a positive integer"),
                    ),
                    ("remove", lambda: parse_command("remove TEA-500G"), ("remove", "TEA-500G")),
                    ("list", lambda: parse_command("list"), ("list",)),
                    ("ls alias", lambda: parse_command("ls"), ("list",)),
                    ("checkout", lambda: parse_command("checkout"), ("checkout",)),
                    ("quit", lambda: parse_command("quit"), ("quit",)),
                    ("exit alias", lambda: parse_command("exit"), ("quit",)),
                    ("blank", lambda: parse_command("   "), ("error", "empty command")),
                    ("unknown", lambda: parse_command("dance now"), ("error", "unknown command: dance")),
                    (
                        "remove without sku",
                        lambda: parse_command("remove"),
                        ("error", "unknown command: remove"),
                    ),
                ]
            )
            """
        ),
        md(
            """
            #### Exercise 2 — `fizzbuzz(number)` with `match`

            Return `"FizzBuzz"` for multiples of 15, `"Fizz"` for multiples of 3, `"Buzz"` for
            multiples of 5, otherwise the number as a string. Match on the **tuple**
            `(number % 3, number % 5)`: one `case` per outcome, no `if`.
            """
        ),
        code(
            '''
            def fizzbuzz(number: int) -> str:
                """Return the FizzBuzz word for number, using match on a tuple of remainders."""
                raise NotImplementedError("Lab 1.8: implement fizzbuzz()")
            '''
        ),
        md("Run the checks."),
        code(
            """
            run_checks(
                [
                    ("1", lambda: fizzbuzz(1), "1"),
                    ("3", lambda: fizzbuzz(3), "Fizz"),
                    ("5", lambda: fizzbuzz(5), "Buzz"),
                    ("15", lambda: fizzbuzz(15), "FizzBuzz"),
                    ("0 is a multiple of 15", lambda: fizzbuzz(0), "FizzBuzz"),
                    (
                        "1 to 15",
                        lambda: " ".join(fizzbuzz(number) for number in range(1, 16)),
                        "1 2 Fizz 4 Buzz Fizz 7 8 Fizz Buzz 11 Fizz 13 14 FizzBuzz",
                    ),
                ]
            )
            """
        ),
        md(
            """
            #### Exercise 3 — `find_first_duplicate(items)` with `for ... else`

            Return the first item that appears **for the second time** while scanning left to
            right (so for `[3, 1, 4, 1, 3]` the answer is `1`, found at index 3, before the
            second `3`). Return `None` if every item is unique. Use a set of seen items, `break`
            when you find a duplicate, and put the "no duplicate" result in the loop's `else`.
            Items are hashable; any iterable must work.
            """
        ),
        code(
            '''
            def find_first_duplicate(items: Iterable[Hashable]) -> Hashable | None:
                """Return the first item seen twice, or None, using for ... else."""
                raise NotImplementedError("Lab 1.8: implement find_first_duplicate()")
            '''
        ),
        md("Run the checks."),
        code(
            """
            run_checks(
                [
                    ("second occurrence wins", lambda: find_first_duplicate([3, 1, 4, 1, 3]), 1),
                    ("adjacent", lambda: find_first_duplicate(["a", "a"]), "a"),
                    ("no duplicate", lambda: find_first_duplicate([1, 2, 3]), None),
                    ("empty", lambda: find_first_duplicate([]), None),
                    ("string iterable", lambda: find_first_duplicate("python"), None),
                    ("generator", lambda: find_first_duplicate(n % 4 for n in range(10)), 0),
                    ("1 and True are equal", lambda: find_first_duplicate([1, True]), True),
                ]
            )
            """
        ),
    ]


def _recap_cells() -> list[NotebookNode]:
    """Recap for Unit 1.8."""
    return [
        md(
            r"""
            ### Recap — Unit 1.8

            | Concept | One-line takeaway | JS equivalent |
            | --- | --- | --- |
            | `/`, `//`, `%` | True division; floor division; `%` takes the divisor's sign | `/`, `Math.floor(a / b)`, `%` (dividend's sign) |
            | `==` / `is` | Value equality without coercion / same object | `===` (no deep equality) / — |
            | Bitwise | Arbitrary-precision ints; bind tighter than comparisons | 32-bit; `==` binds tighter than `&` |
            | `in` | Calls `__contains__`: values in lists, substrings in str, keys in dicts | `includes`, `in` (keys) |
            | Precedence | `**` > unary > `* /` > `+ -` > shifts > `&` > `^` > `\|` > comparisons > `not` > `and` > `or` | similar, but not identical |
            | Chained comparisons | `0 < age <= 120`; middle evaluated once | `0 < age && age <= 120` |
            | `and` / `or` | Short-circuit and return an operand | `&&` / `\|\|` |
            | `value or default` | Replaces every falsy value, including `0` and `""` | `\|\|` (same trap) |
            | No `??` | `x if x is not None else default` | `x ?? default` |
            | Conditional expression | `a if condition else b` | `condition ? a : b` |
            | Guard clauses | Handle special cases first and return early | same |
            | `match` | Structural patterns, first match wins, no fall-through | `switch` with `===` and fall-through |
            | Capture trap | A bare name in a case captures; use dotted names for constants | — |
            | `for` | Iterates any iterable; counting via `range` | `for...of` |
            | Loop `else` | Runs when the loop ends without `break` | no equivalent |
            | Do-while | `while True: ... if not condition: break` | `do { } while ()` |
            | Augmented assignment | In place for mutable types, rebinds immutable ones; no `++` | `+=`, `++` |
            | Walrus `:=` | Assignment expression; binds in the enclosing scope from comprehensions | assignment is an expression in JS |
            | `*` / `**` | Unpack in calls, literals and assignment targets; in comprehensions (3.15) | `...` spread / rest |

            **Further reading**

            - [Expressions: operator precedence](https://docs.python.org/3/reference/expressions.html#operator-precedence),
              [comparisons](https://docs.python.org/3/reference/expressions.html#comparisons),
              [boolean operations](https://docs.python.org/3/reference/expressions.html#boolean-operations)
            - [Compound statements: `if`, `while`, `for`, `match`](https://docs.python.org/3/reference/compound_stmts.html)
            - [Tutorial: `match` statements](https://docs.python.org/3/tutorial/controlflow.html#match-statements),
              [`break`, `continue` and `else` on loops](https://docs.python.org/3/tutorial/controlflow.html#break-and-continue-statements-and-else-clauses-on-loops)
            - [Simple statements: assignment, augmented assignment](https://docs.python.org/3/reference/simple_stmts.html#assignment-statements),
              [assignment expressions](https://docs.python.org/3/reference/expressions.html#assignment-expressions)
            - [PEP 634 — Structural pattern matching: specification](https://peps.python.org/pep-0634/),
              [PEP 635 — motivation and rationale](https://peps.python.org/pep-0635/),
              [PEP 636 — tutorial](https://peps.python.org/pep-0636/)
            - [PEP 572 — Assignment expressions](https://peps.python.org/pep-0572/),
              [PEP 448 — Additional unpacking generalizations](https://peps.python.org/pep-0448/),
              [PEP 3132 — Extended iterable unpacking](https://peps.python.org/pep-3132/),
              [PEP 798 — Unpacking in comprehensions](https://peps.python.org/pep-0798/),
              [PEP 505 — None-aware operators (deferred)](https://peps.python.org/pep-0505/)
            """
        ),
    ]


def cells() -> list[NotebookNode]:
    """Return the cells for Unit 1.8 and Lab 1.8."""
    return [
        *_overview_cells(),
        *_operator_cells(),
        *_boolean_operand_cells(),
        *_conditional_cells(),
        *_match_cells(),
        *_loop_cells(),
        *_assignment_cells(),
        *_unpacking_cells(),
        *_lab_cells(),
        *_recap_cells(),
    ]
