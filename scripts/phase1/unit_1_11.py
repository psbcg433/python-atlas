"""Unit 1.11 — Scope, Namespaces and Closures (with Lab 1.11)."""

from nbformat import NotebookNode

from nb_builder import code, md, predict_cells

UNIT_SETUP_SOURCE = '''
import builtins
import dis
import functools
import inspect
import io
import math
import re  # noqa: F401 (used in Lab 1.11)
import sys
import timeit
from collections.abc import Callable
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
            """
            ## Unit 1.11 — Scope, Namespaces and Closures

            **Objectives**

            - Name the four kinds of namespace (built-in, module, class, function) and inspect
              them with `globals()`, `locals()` and the `builtins` module.
            - Resolve any name with the LEGB rule, and spot a shadowed built-in.
            - Explain why Python has no block scope, and which constructs *do* create a scope.
            - Explain `UnboundLocalError` from the compiler's point of view (`co_varnames`,
              `LOAD_FAST_CHECK`).
            - Use `global` and `nonlocal` correctly, and prefer passing state explicitly.
            - Read a closure's cell objects, and fix the late-binding trap.

            **JS bridge**

            | JavaScript concept | Python equivalent | The difference that bites |
            | --- | --- | --- |
            | `let` / `const` block scope | no block scope: function, class, module, comprehension | A name set inside `if` / `for` survives the block |
            | `var` hoisting (`undefined`) | assignment anywhere makes a name local | Reading it early raises `UnboundLocalError`, not `undefined` |
            | `let` temporal dead zone | `UnboundLocalError` | Same idea, decided at compile time |
            | Assigning an outer variable just works | `nonlocal` / `global` needed to **rebind** | Without them the assignment creates a new local |
            | `globalThis`, `window` | `globals()` (module), `builtins` | Each module has its own global namespace |
            | Closures capture variables | Closures capture **cells** | Same late binding; no per-iteration `let` binding in loops |
            | `for (let i …)` callbacks | `lambda i=i: …` or `functools.partial` | Python loops reuse one variable |

            The next cell is this unit's setup (`compile_error` is the helper from Unit 1.8).
            """
        ),
        code(UNIT_SETUP_SOURCE),
    ]


def _namespace_cells() -> list[NotebookNode]:
    """1.11.1 Namespaces."""
    return [
        md(
            """
            ### 1.11.1 Namespaces

            A **namespace** is a mapping from names to objects. Python keeps several of them, with
            different lifetimes:

            | Namespace | Created | Lives until | Look at it with |
            | --- | --- | --- | --- |
            | Built-in | interpreter start | interpreter exit | `import builtins; vars(builtins)` |
            | Module (global) | first import of the module | interpreter exit (usually) | `globals()`, `module.__dict__` |
            | Class | the `class` body runs | becomes the class's `__dict__` | `vars(SomeClass)` |
            | Function (local) | **each call** | the call returns (unless a closure keeps a cell) | `locals()` inside the function |

            **Module namespace.** In a notebook the module is `__main__`. `globals()` returns the
            module's own `__dict__`, the real thing, not a copy: writing to it creates a variable.
            """
        ),
        code(
            """
            main_module = sys.modules[__name__]
            print(f"{__name__=}")
            print(f"{globals() is main_module.__dict__=}")

            globals()["created_through_globals"] = "hello"
            print(f"{created_through_globals=}")  # noqa: F821 (created on the line above)
            print(f"{'show_size' in globals()=}, {'len' in globals()=}")
            """
        ),
        md(
            """
            Note the last line: `len` is **not** in `globals()`. Built-ins live in their own
            namespace, which is searched after the module namespace (1.11.2).

            **Function namespace.** Every call gets a fresh local namespace. Inside a function,
            `locals()` returns a dict *snapshot* of it (*Changed in 3.13*, PEP 667: writes to the
            snapshot never change the real local variables).
            """
        ),
        code(
            '''
            def price_with_tax(base_price: int, tax_percent: int = 18) -> int:
                """Show the local namespace of one call."""
                tax_amount = base_price * tax_percent // 100
                print(f"  locals()={locals()}")
                return base_price + tax_amount


            print(price_with_tax(500))
            print(price_with_tax(1000, 5))


            def try_to_write_locals() -> int:
                """Writing to the locals() snapshot does not create a variable."""
                local_snapshot = locals()
                local_snapshot["discount"] = 50
                return len(local_snapshot)


            print(f"{try_to_write_locals()=}, the variable 'discount' was never created")
            '''
        ),
        md(
            """
            **Class namespace.** A `class` body runs once, in its own namespace, which then becomes
            the class's `__dict__` (wrapped in a read-only `mappingproxy`). The trap: names
            defined in the class body are **not** visible inside methods. Methods must go through
            `self` or the class.
            """
        ),
        code(
            '''
            class MenuItem:
                """A class whose body defines a name and two methods."""

                tax_percent = 5
                print(f"  inside the class body: {sorted(locals())}")

                def tax_without_self(self) -> int:
                    """Looks for tax_percent in the local, global and built-in scopes only."""
                    return tax_percent  # noqa: F821 (deliberate: class scope is skipped)

                def tax_with_self(self) -> int:
                    """Finds the class attribute through the instance."""
                    return self.tax_percent


            print(f"{type(vars(MenuItem)).__name__=}, {vars(MenuItem)['tax_percent']=}")
            print(f"{MenuItem().tax_with_self()=}")
            print(f"tax_without_self(): {raised_error_name(MenuItem().tax_without_self)}")
            '''
        ),
        md(
            """
            **Built-in namespace.** `len`, `print`, `ValueError` and friends live in the
            `builtins` module. Each module also has `__builtins__` (an implementation detail:
            in `__main__` it is the module itself, elsewhere its `__dict__`). Always use
            `import builtins` in your own code.
            """
        ),
        code(
            """
            builtin_names = [name for name in vars(builtins) if not name.startswith("_")]
            print(f"{len(builtin_names)=} public built-in names")
            print(f"{builtins.len is len=}, {builtins.ValueError is ValueError=}")
            print(f"first few: {sorted(builtin_names)[:6]}")
            print(f"{type(__builtins__).__name__=}  (in __main__; a dict in other modules)")
            """
        ),
        md(
            """
            #### Under the hood: function locals are not a dict

            Module and class namespaces are real dicts. Function locals are not: the compiler
            gives each local a slot number, and the frame stores them in a C array ("fast
            locals"). `locals()` builds a dict from that array on demand. The code object lists
            the slots in `co_varnames` and counts them in `co_nlocals`.
            """
        ),
        code(
            """
            price_code = price_with_tax.__code__
            print(f"{price_code.co_varnames=}")
            print(f"{price_code.co_nlocals=}, {price_code.co_argcount=}")
            print(f"{inspect.isfunction(price_with_tax)=}, {type(vars(MenuItem)).__name__=}")
            """
        ),
    ]


def _legb_cells() -> list[NotebookNode]:
    """1.11.2 The LEGB rule."""
    return [
        md(
            """
            ### 1.11.2 The LEGB rule

            To find the object a name refers to, Python searches four scopes in order and stops
            at the first hit:

            ```mermaid
            flowchart LR
                lookup(["name lookup"]) --> local["L: Local<br/>current function"]
                local -- "not found" --> enclosing["E: Enclosing<br/>outer functions, inside out"]
                enclosing -- "not found" --> global_scope["G: Global<br/>module namespace"]
                global_scope -- "not found" --> builtin["B: Built-in<br/>builtins module"]
                builtin -- "not found" --> error(["NameError"])
            ```

            <details><summary>ASCII fallback</summary>

            ```text
            name --> Local --> Enclosing (inside out) --> Global (module) --> Built-in --> NameError
                     (stop at the first scope that has the name)
            ```

            </details>

            Class bodies are **not** an enclosing scope for the methods inside them (1.11.1).

            The next cell defines the same name at three levels. Each print shows which binding
            the lookup reaches first.
            """
        ),
        code(
            '''
            currency_symbol = "Rs"  # global


            def outer_report() -> Callable[[], str]:
                """Enclosing function with its own currency_symbol."""
                currency_symbol = "₹"  # enclosing

                def inner_report() -> str:
                    """Uses the nearest currency_symbol and the built-in len."""
                    return f"{currency_symbol} (name length {len(currency_symbol)})"

                return inner_report


            def global_report() -> str:
                """No local or enclosing binding: falls through to the global."""
                return currency_symbol


            print(f"{outer_report()()=}")
            print(f"{global_report()=}")
            '''
        ),
        md(
            """
            `inspect.getclosurevars` reports where each free name of a function was found:
            enclosing (`nonlocals`), global or built-in.
            """
        ),
        code(
            """
            print(inspect.getclosurevars(outer_report()))
            print(inspect.getclosurevars(global_report))
            """
        ),
        md(
            """
            **Shadowing built-ins.** Because the global scope is searched before the built-in
            scope, `list = [...]` at module level hides the built-in `list` for the whole module.
            The error comes much later, far from the cause. `del list` removes the global and
            uncovers the built-in again.

            The next cell runs the mistake in a throwaway namespace, so this notebook's `list`
            stays intact.
            """
        ),
        code(
            '''
            shadowing_module = """
            list = ["idli", "dosa"]
            try:
                letters = list("abc")
            except TypeError as error:
                print(f"  {type(error).__name__}: {error}")
            del list
            print(f"  after del: {list('abc')}")
            """
            exec(shadowing_module, {})
            print(f"{list('ok')=}  (this notebook's list is untouched)")
            '''
        ),
        md(
            """
            A parameter or local with a built-in's name shadows it only inside that function.
            That is common and usually harmless (`id`, `type`, `input` are popular parameter
            names), until the function needs the built-in itself.
            """
        ),
        code(
            '''
            def describe_order(id: int, type: str) -> str:
                """Parameters named id and type hide the built-ins inside this function."""
                try:
                    return f"order {id} of kind {type}, class name {type(id).__name__}"
                except TypeError as error:
                    return f"{builtins.type(error).__name__}: {error}"


            print(describe_order(42, "express"))
            order_id = 42
            print(f"{type(order_id).__name__=}  (outside the function, type is the built-in again)")
            '''
        ),
        *predict_cells(
            snippet="""
            stock = 100

            def outer():
                stock = 50
                def inner():
                    return stock
                stock = 25
                return inner()

            print(outer(), stock)
            """,
            answer="""
            `25 100`. `inner` finds `stock` in the enclosing scope, and it reads the variable
            **when called**, by which time `outer` has rebound it to 25. The global `stock` is
            never touched: both assignments in `outer` create an `outer` local.
            """,
            proof='''
            stock = 100


            def outer() -> int:
                """Rebind the enclosing variable before calling inner."""
                stock = 50

                def inner() -> int:
                    """Reads stock from the enclosing scope at call time."""
                    return stock

                stock = 25
                return inner()


            print(outer(), stock)
            ''',
        ),
    ]


def _block_scope_cells() -> list[NotebookNode]:
    """1.11.3 No block scope."""
    return [
        md(
            """
            ### 1.11.3 No block scope

            Only modules, classes, functions, comprehensions and lambdas create scopes. Blocks
            (`if`, `for`, `while`, `with`, `try`) do **not**: a name bound inside them is an
            ordinary variable of the surrounding function or module and survives the block.
            """
        ),
        code(
            '''
            def block_survivors(order_total: int) -> dict[str, Any]:
                """Names bound inside if / for / with / try are still there afterwards."""
                if order_total > 1000:
                    shipping_label = "free shipping"
                else:
                    shipping_label = "Rs 49 shipping"

                for line_number in range(1, 4):  # noqa: B007
                    pass  # the loop variable keeps its last value

                with io.StringIO("receipt text") as log_file:
                    pass  # the buffer is closed, but the name still exists

                try:
                    parsed_quantity = int("3")
                except ValueError:
                    parsed_quantity = 0

                return {
                    "shipping_label": shipping_label,
                    "line_number": line_number,
                    "log_file_closed": log_file.closed,
                    "parsed_quantity": parsed_quantity,
                }


            print(block_survivors(1500))
            '''
        ),
        md(
            """
            Two consequences:

            - If a `for` loop never runs, its variable is **never bound**, and reading it later
              fails.
            - `except ... as error` is the one exception to the rule: Python **deletes** `error`
              at the end of the `except` block (to break a reference cycle through the
              traceback). Copy it to another name if you need it later.
            """
        ),
        code(
            '''
            def last_item(items: list[str]) -> str:
                """Return the loop variable after the loop (broken for empty lists)."""
                for item in items:  # noqa: B007
                    pass
                return item


            def error_after_except() -> str:
                """The 'as' name is deleted when the except block ends."""
                try:
                    int("not a number")
                except ValueError as error:
                    saved_error = error
                return f"{type(saved_error).__name__}; error itself: {'error' in locals()}"


            print(f"{last_item(['tea', 'coffee'])=}")
            print(f"last_item([]): {raised_error_name(lambda: last_item([]))}")
            print(f"{error_after_except()=}")
            '''
        ),
        md(
            """
            **Comprehensions and lambdas do have their own scope.** The loop variable of a
            comprehension does not leak (since Python 3; Python 2 list comprehensions leaked).
            Since 3.12, list/dict/set comprehensions are *inlined* into the surrounding function
            (PEP 709) for speed, but the isolation is kept. The one deliberate leak is the walrus
            operator `:=`, which binds in the enclosing scope (PEP 572).
            """
        ),
        code(
            '''
            def comprehension_scope() -> dict[str, Any]:
                """Comprehension and lambda variables stay inside; := leaks on purpose."""
                prices = [120, 80, 250]
                doubled = [price * 2 for price in prices]
                with_tax = [(taxed := price * 118 // 100) for price in prices]
                add_one = lambda value: value + 1  # noqa: E731
                return {
                    "doubled": doubled,
                    "price leaked": "price" in locals(),
                    "value leaked": "value" in locals(),
                    "taxed (walrus)": taxed,
                    "with_tax": with_tax,
                    "add_one(1)": add_one(1),
                }


            print(comprehension_scope())
            '''
        ),
    ]


def _compile_time_cells() -> list[NotebookNode]:
    """1.11.4 Compile-time scope decisions."""
    return [
        md(
            """
            ### 1.11.4 Compile-time scope decisions

            Scope is decided when the function is **compiled**, not while it runs. If a name is
            assigned *anywhere* in a function body (`=`, `+=`, `for name in`, `import name`,
            `def name`, `except ... as name`, …), it is local for the **whole** function, even on
            lines before the assignment. Reading it before it has a value raises
            `UnboundLocalError`.
            """
        ),
        code(
            '''
            stock_count = 10


            def sell_one() -> int:
                """Reads stock_count, then assigns it: the compiler made it local."""
                print(f"  selling one of {stock_count}")  # noqa: F823
                stock_count -= 1
                return stock_count


            try:
                sell_one()
            except UnboundLocalError as error:
                print(f"{type(error).__name__}: {error}")
            print(f"{issubclass(UnboundLocalError, NameError)=}")
            '''
        ),
        md(
            """
            The assignment does not even need to run. A branch that can never execute still makes
            the name local, because the decision was made from the source text.
            """
        ),
        code(
            '''
            def read_with_dead_branch() -> int:
                """An assignment that never runs still makes stock_count local."""
                if False:
                    stock_count = 0
                return stock_count


            print(f"read_with_dead_branch(): {raised_error_name(read_with_dead_branch)}")
            '''
        ),
        md(
            """
            The code object records the decision. `co_varnames` lists the local slots
            (parameters first); `co_names` lists the global and attribute names the code uses.
            """
        ),
        code(
            '''
            def build_receipt(customer_name: str) -> str:
                """Uses a parameter, a local, a global function and an attribute."""
                greeting = customer_name.title()
                return f"{greeting}: {len(greeting)} letters, pi≈{math.pi:.2f}"


            receipt_code = build_receipt.__code__
            print(f"{receipt_code.co_varnames=}")
            print(f"{receipt_code.co_names=}")
            print(f"{sell_one.__code__.co_varnames=}  (stock_count is a local slot)")
            '''
        ),
        md(
            """
            #### Under the hood: `LOAD_FAST_CHECK`

            Locals are read with `LOAD_FAST` (or `LOAD_FAST_BORROW`, *New in 3.14*), which skips
            the "is it bound?" test when the compiler can prove the variable has a value. When it
            cannot (as in `sell_one`), it emits `LOAD_FAST_CHECK`, which raises
            `UnboundLocalError` if the slot is empty. Globals use `LOAD_GLOBAL`. Opcode names vary
            between versions.
            """
        ),
        code(
            """
            for function in (sell_one, build_receipt):
                load_instructions = [
                    f"{instruction.opname} {instruction.argval}"
                    for instruction in dis.get_instructions(function)
                    if instruction.opname.startswith(("LOAD_FAST", "LOAD_GLOBAL", "LOAD_ATTR"))
                ]
                print(f"{function.__name__}: {load_instructions}")

            sell_one_opnames = {instruction.opname for instruction in dis.get_instructions(sell_one)}
            print(f"{'LOAD_FAST_CHECK' in sell_one_opnames=}")
            """
        ),
        md(
            """
            **JS bridge: `var` hoisting and the `let` TDZ.**

            | | JavaScript `var` | JavaScript `let` / `const` | Python |
            | --- | --- | --- | --- |
            | Scope | function | block | function (no blocks) |
            | Read before assignment | `undefined` (hoisted) | `ReferenceError` (temporal dead zone) | `UnboundLocalError` |
            | Decided | at parse time | at parse time | at compile time |

            ```javascript
            function sellOne() {
              console.log(stock);   // var: undefined; let: ReferenceError
              let stock = 9;
            }
            ```

            Python behaves like `let`: the name is reserved for the whole function, but has no
            value until the assignment runs. The fixes are in 1.11.5: pass the value in, return
            the new value, or declare `global` / `nonlocal`.
            """
        ),
        code(
            '''
            def sell_one_fixed(current_stock: int) -> int:
                """Take the value as a parameter and return the new value."""
                return current_stock - 1


            stock_count = sell_one_fixed(stock_count)
            print(f"{stock_count=}")
            '''
        ),
    ]


def _global_nonlocal_cells() -> list[NotebookNode]:
    """1.11.5 global and nonlocal."""
    return [
        md(
            """
            ### 1.11.5 `global` and `nonlocal`

            | Statement | Lets a function **rebind** | Typical use |
            | --- | --- | --- |
            | `global name` | a module-level name | module-level counters, caches, configuration (sparingly) |
            | `nonlocal name` | a name in the nearest enclosing function | closures that keep state (1.11.6) |

            `global` makes assignments inside the function write to the module namespace.
            """
        ),
        code(
            '''
            request_count = 0


            def record_request() -> int:
                """Rebind the module-level counter."""
                global request_count
                request_count += 1
                return request_count


            record_request()
            record_request()
            print(f"{request_count=}")
            '''
        ),
        md(
            """
            **Rebinding vs mutating.** `global` / `nonlocal` are only needed to make the name
            point at a **new object**. Calling a method that changes the object in place
            (`append`, `update`, item assignment) is a read of the name, so no declaration is
            needed.
            """
        ),
        code(
            '''
            audit_log: list[str] = []


            def log_event(message: str) -> None:
                """Mutates the global list: no 'global' needed."""
                audit_log.append(message)


            def reset_log_wrong() -> None:
                """Assignment creates a new local; the global list is unchanged."""
                audit_log = []  # noqa: F841 (deliberate: local variable, never used)


            log_event("login")
            log_event("checkout")
            reset_log_wrong()
            print(f"{audit_log=}  (reset_log_wrong did nothing)")
            '''
        ),
        md(
            """
            `nonlocal` does the same for an enclosing function's variable. Without it, `+=` inside
            the inner function would make `total` local and fail with `UnboundLocalError`.
            """
        ),
        code(
            '''
            def make_cart_total() -> Callable[[int], int]:
                """Return an add function that keeps a running total."""
                total = 0

                def add(amount: int) -> int:
                    """Rebind the enclosing total."""
                    nonlocal total
                    total += amount
                    return total

                return add


            add_to_cart = make_cart_total()
            add_to_cart(249)
            print(f"{add_to_cart(640)=}")
            '''
        ),
        md(
            """
            Both statements are checked at compile time: `nonlocal` must name a variable of an
            enclosing *function* (not a global), and a name may not be used before its `global`
            declaration.
            """
        ),
        code(
            """
            print(compile_error("def outer():\\n    nonlocal missing_name\\n"))
            print(compile_error("rate = 1\\ndef show():\\n    print(rate)\\n    global rate\\n"))
            print(compile_error("def outer():\\n    total = 0\\n    def add():\\n        nonlocal total\\n"))
            """
        ),
        md(
            """
            **Why global state hurts testing.** A function that reads or writes module state gives
            different answers depending on what ran before it. Tests then pass alone and fail
            together (or the other way round). Below, two "tests" of `process_order` share the
            hidden `processed_order_ids` set.
            """
        ),
        code(
            '''
            processed_order_ids: set[int] = set()


            def process_order(order_id: int) -> str:
                """Depends on hidden module state."""
                if order_id in processed_order_ids:
                    return "duplicate"
                processed_order_ids.add(order_id)
                return "processed"


            def test_new_order_is_processed() -> bool:
                return process_order(101) == "processed"


            def test_repeat_order_is_duplicate() -> bool:
                process_order(101)
                return process_order(101) == "duplicate"


            print(f"order A then B: {test_new_order_is_processed()}, {test_repeat_order_is_duplicate()}")
            processed_order_ids.clear()
            print(f"order B then A: {test_repeat_order_is_duplicate()}, {test_new_order_is_processed()}")
            '''
        ),
        md(
            """
            The fix is to make the state an **explicit argument** (or an object attribute, Phase
            2). Each test then builds its own state, and the function has no hidden inputs.
            """
        ),
        code(
            '''
            def process_order_explicit(order_id: int, processed_ids: set[int]) -> str:
                """Same logic; the state is passed in."""
                if order_id in processed_ids:
                    return "duplicate"
                processed_ids.add(order_id)
                return "processed"


            print(f"{process_order_explicit(101, set())=}")
            seen_ids = {101}
            print(f"{process_order_explicit(101, seen_ids)=}")
            '''
        ),
    ]


def _closure_cells() -> list[NotebookNode]:
    """1.11.6 Closures."""
    return [
        md(
            """
            ### 1.11.6 Closures

            A **closure** is a function that remembers variables of the enclosing function after
            that function has returned. Unit 1.10.6 used one (`make_discount`) without explaining
            it. The classic example is a counter: `make_counter` returns a function whose `count`
            lives on between calls, and every call to `make_counter` creates independent state.
            """
        ),
        code(
            '''
            def make_counter(start: int = 0) -> Callable[[], int]:
                """Return a function that counts up from start."""
                count = start

                def increment() -> int:
                    """Rebind the enclosing count."""
                    nonlocal count
                    count += 1
                    return count

                return increment


            ticket_counter = make_counter()
            invoice_counter = make_counter(start=1000)
            print(ticket_counter(), ticket_counter(), ticket_counter())
            print(invoice_counter(), invoice_counter())
            '''
        ),
        md(
            """
            A closure that only **reads** the enclosing variable needs no `nonlocal`.
            `make_multiplier` is a function factory: each returned function carries its own
            `factor`.
            """
        ),
        code(
            '''
            def make_multiplier(factor: float) -> Callable[[float], float]:
                """Return a function that multiplies by factor."""

                def multiply(value: float) -> float:
                    return value * factor

                return multiply


            double = make_multiplier(2)
            add_gst = make_multiplier(1.18)
            print(f"{double(21)=}, {add_gst(500)=}")
            '''
        ),
        md(
            """
            #### Under the hood: cells

            The compiler sees that `count` is used by an inner function, so it does not store it
            in a plain local slot. It stores it in a **cell object**, a tiny box holding one
            reference. Both functions point at the same cell:

            | Attribute | On | Holds |
            | --- | --- | --- |
            | `co_cellvars` | outer code object | names that inner functions capture |
            | `co_freevars` | inner code object | names it reads from enclosing scopes |
            | `__closure__` | inner function | a tuple of cell objects, one per free variable |
            | `cell.cell_contents` | each cell | the current value |
            """
        ),
        code(
            """
            print(f"{make_counter.__code__.co_cellvars=}")
            print(f"{ticket_counter.__code__.co_freevars=}")
            print(f"{type(ticket_counter.__closure__[0]).__name__=}")
            print(f"{ticket_counter.__closure__[0].cell_contents=}")
            print(f"{invoice_counter.__closure__[0].cell_contents=}")
            print(f"{add_gst.__code__.co_freevars=}, {add_gst.__closure__[0].cell_contents=}")
            """
        ),
        md(
            """
            A cell holds the **variable**, not a frozen value. Two closures created in the same
            call share their cells, and a change made after the closure was created is visible
            through it. A function without free variables has `__closure__ = None`.
            """
        ),
        code(
            '''
            def make_price_tools(initial_price: int) -> tuple[Callable[[], int], Callable[[int], None]]:
                """Return a getter and a setter that share one cell."""
                price = initial_price

                def get_price() -> int:
                    return price

                def set_price(new_price: int) -> None:
                    nonlocal price
                    price = new_price

                return get_price, set_price


            get_price, set_price = make_price_tools(250)
            set_price(199)
            print(f"{get_price()=}")
            print(f"{get_price.__closure__[0] is set_price.__closure__[0]=}")
            print(f"{show_size.__closure__=}")
            '''
        ),
        md(
            """
            The bytecode shows the cell machinery: `MAKE_CELL` in the outer function, then
            `STORE_DEREF` / `LOAD_DEREF` instead of `STORE_FAST` / `LOAD_FAST`. The inner function
            starts with `COPY_FREE_VARS`, which copies the cells from `__closure__` into its
            frame. Opcode names vary between versions.
            """
        ),
        code(
            """
            for function in (make_counter, ticket_counter):
                opnames = [instruction.opname for instruction in dis.get_instructions(function)]
                cell_ops = [name for name in opnames if "DEREF" in name or "CELL" in name or "FREE" in name]
                print(f"{function.__qualname__}: {cell_ops}")
            """
        ),
        md(
            """
            > **Note:** JavaScript closures work the same way (they capture variables, not
            > values). The difference is that JavaScript can assign an outer variable directly,
            > while Python needs `nonlocal` to rebind it.
            """
        ),
    ]


def _late_binding_cells() -> list[NotebookNode]:
    """1.11.7 Late binding."""
    return [
        md(
            """
            ### 1.11.7 Late binding

            Because closures capture variables, they read the value **when they are called**, not
            when they are created. Functions made in a loop all share the loop variable, so they
            all see its last value.
            """
        ),
        *predict_cells(
            snippet="""
            callbacks = [lambda: i for i in range(3)]
            print([callback() for callback in callbacks])
            """,
            answer="""
            `[2, 2, 2]`. The three lambdas share **one** variable `i` (one cell). By the time they
            are called, the comprehension has finished and `i` is 2.
            """,
            proof="""
            callbacks = [lambda: i for i in range(3)]  # noqa: B023
            print([callback() for callback in callbacks])
            print(f"{callbacks[0].__closure__[0] is callbacks[2].__closure__[0]=}")
            """,
        ),
        md(
            """
            **Fix 1: a default argument.** Defaults are evaluated once, when the function is
            created (1.10.5), so `i=i` freezes the current value into each lambda. This is the
            common idiom; its downside is that callers could pass `i` by mistake.
            """
        ),
        code(
            """
            frozen_callbacks = [lambda i=i: i for i in range(3)]
            print([callback() for callback in frozen_callbacks])
            print(f"{frozen_callbacks[1].__defaults__=}, {frozen_callbacks[1].__closure__=}")
            """
        ),
        md(
            """
            **Fix 2: `functools.partial`.** `partial(function, value)` stores the value when it
            is created, with no extra parameter to misuse. A small factory function (like
            `make_multiplier`) works too, because every call creates a new cell.
            """
        ),
        code(
            '''
            def label_for(slot_number: int) -> str:
                """Return a delivery-slot label."""
                return f"slot {slot_number}"


            partial_callbacks = [functools.partial(label_for, slot) for slot in range(3)]
            factory_callbacks = [make_multiplier(slot) for slot in range(3)]
            print([callback() for callback in partial_callbacks])
            print([callback(10) for callback in factory_callbacks])
            '''
        ),
        md(
            """
            **JS bridge: `var` in loops.** JavaScript had the same bug with `var` and fixed it
            with `let`, which creates a **new binding per iteration**. Python has no per-iteration
            binding, so it behaves like `var`:

            ```javascript
            for (var i = 0; i < 3; i++) setTimeout(() => console.log(i));  // 3 3 3
            for (let i = 0; i < 3; i++) setTimeout(() => console.log(i));  // 0 1 2
            ```

            The same trap appears in real code whenever callbacks are registered in a loop, for
            example one handler per button or per route. The next cell shows it with a plain
            `for` loop, which shares the variable just like the comprehension.
            """
        ),
        code(
            """
            button_handlers: dict[str, Callable[[], str]] = {}
            for button_name in ["save", "cancel", "delete"]:
                button_handlers[button_name] = lambda: f"clicked {button_name}"  # noqa: B023

            print(f"{button_handlers['save']()=}  (late binding)")

            for button_name in ["save", "cancel", "delete"]:
                button_handlers[button_name] = lambda name=button_name: f"clicked {name}"

            print(f"{button_handlers['save']()=}  (fixed with a default)")
            """
        ),
    ]


def _lookup_cost_cells() -> list[NotebookNode]:
    """1.11.8 Name lookup cost."""
    return [
        md(
            """
            ### 1.11.8 Name lookup cost

            The scope decision also picks the instruction used to read a name:

            | Instruction | Scope | Cost |
            | --- | --- | --- |
            | `LOAD_FAST` / `LOAD_FAST_BORROW` | local | index into the frame's array |
            | `LOAD_DEREF` | enclosing (cell) | array index + one pointer hop through the cell |
            | `LOAD_GLOBAL` | global, then built-in | dict lookups (cached by the specializing interpreter, 3.11+) |
            | `LOAD_ATTR` | `module.name` | one more lookup on top of the global |

            The next cell shows all of them in one function.
            """
        ),
        code(
            '''
            def make_scaler(scale: float) -> Callable[[list[float]], list[float]]:
                """Return a function that reads a local, a cell, a global and a built-in."""

                def scale_values(values: list[float]) -> list[float]:
                    rounded_values = [round(value * scale, 2) for value in values]
                    return [math.floor(value) for value in rounded_values]

                return scale_values


            loads = {
                f"{instruction.opname} {instruction.argval}"
                for instruction in dis.get_instructions(make_scaler(1.5))
                if instruction.opname.startswith(("LOAD_FAST", "LOAD_DEREF", "LOAD_GLOBAL", "LOAD_ATTR"))
            }
            print(sorted(loads))
            '''
        ),
        md(
            """
            **Timing a local alias.** The classic micro-optimization binds a global or a method
            to a local name before a hot loop: `sqrt = math.sqrt`, `append = results.append`.
            The specializing interpreter (3.11+) has narrowed the gap a lot, so the gain is
            usually small. Measure before you do it, and only in genuinely hot loops. Timings vary
            by machine and Python version.
            """
        ),
        code(
            '''
            def roots_global(count: int) -> list[float]:
                """math.sqrt and results.append looked up on every iteration."""
                results: list[float] = []
                for number in range(count):
                    results.append(math.sqrt(number))
                return results


            def roots_local_alias(count: int) -> list[float]:
                """Both looked up once, then read as locals."""
                results: list[float] = []
                append, sqrt = results.append, math.sqrt
                for number in range(count):
                    append(sqrt(number))
                return results


            global_seconds = min(timeit.repeat(lambda: roots_global(10_000), number=50, repeat=5))
            alias_seconds = min(timeit.repeat(lambda: roots_local_alias(10_000), number=50, repeat=5))
            print(f"global lookups: {global_seconds * 1000:.1f} ms, local alias: {alias_seconds * 1000:.1f} ms")
            print(f"speed-up: {global_seconds / alias_seconds:.2f}x  (varies by machine and version)")
            '''
        ),
    ]


def _lab_cells() -> list[NotebookNode]:
    """Lab 1.11."""
    return [
        md(
            """
            ### Lab 1.11

            Three exercises. For each, replace the `raise NotImplementedError` in the stub, then
            run the check cell. Until then the checks print FAIL; that is expected.

            #### Exercise 1 — `make_rate_counter(window_seconds)`

            Return **two closures that share state**, `(record_hit, hits_in_window)`:

            - `record_hit(timestamp)` remembers that a hit happened at `timestamp` (seconds, a
              float; timestamps arrive in increasing order).
            - `hits_in_window(now)` returns how many recorded hits satisfy
              `now - window_seconds < timestamp <= now`.
            - Raise `ValueError` if `window_seconds <= 0`.
            - Two calls to `make_rate_counter` give independent counters. Use a closure, not a
              global or a class.
            """
        ),
        code(
            '''
            def make_rate_counter(
                window_seconds: float,
            ) -> tuple[Callable[[float], None], Callable[[float], int]]:
                """Return (record_hit, hits_in_window) closures sharing one list of timestamps."""
                raise NotImplementedError("Lab 1.11: implement make_rate_counter()")
            '''
        ),
        md(
            """
            Run the checks. `rate_counter_trace` records hits at 0, 10, 20, 30 and 65 seconds in a
            60-second window and asks the count at several moments.
            """
        ),
        code(
            '''
            def rate_counter_trace() -> list[int]:
                """Counts at t=30, 59.9, 60, 65 and 85 after hits at 0, 10, 20, 30 and 65."""
                record_hit, hits_in_window = make_rate_counter(60)
                for timestamp in (0, 10, 20, 30):
                    record_hit(timestamp)
                counts = [hits_in_window(30), hits_in_window(59.9), hits_in_window(60)]
                record_hit(65)
                counts += [hits_in_window(65), hits_in_window(85)]
                return counts


            def rate_counters_independent() -> tuple[int, int]:
                """Hits recorded on one counter are not seen by another."""
                record_first, count_first = make_rate_counter(10)
                _, count_second = make_rate_counter(10)
                record_first(1.0)
                return count_first(1.0), count_second(1.0)


            run_checks(
                [
                    ("window counts", rate_counter_trace, [4, 4, 3, 4, 2]),
                    ("independent counters", rate_counters_independent, (1, 0)),
                    ("both are closures", lambda: all(f.__closure__ for f in make_rate_counter(5)), True),
                    ("window 0", lambda: raised_error_name(lambda: make_rate_counter(0)), "ValueError"),
                ]
            )
            '''
        ),
        md(
            """
            #### Exercise 2 — fix three buggy functions

            The next cell defines three buggy functions and shows each bug. Write fixed versions
            **with the same names minus `_buggy`**, keeping the signatures:

            1. `add_tag(tag, tags=None)`: return a list of the given tags plus `tag`. The buggy
               version shares one default list between calls (mutable default).
            2. `make_accumulator()`: return a function `add(amount)` returning the running total.
               The buggy version raises `UnboundLocalError`.
            3. `make_price_formatters(currency_codes)`: return one formatter per currency code;
               each takes an amount and returns e.g. `"INR 250.00"`. The buggy version formats
               every amount with the last currency (late binding).

            `add_tag` must not change a list passed in by the caller.
            """
        ),
        code(
            """
            def add_tag_buggy(tag: str, tags: list[str] = []) -> list[str]:  # noqa: B006 (the bug)
                tags.append(tag)
                return tags


            def make_accumulator_buggy() -> Callable[[float], float]:
                total = 0.0

                def add(amount: float) -> float:
                    total += amount  # noqa: F823 (the bug)
                    return total

                return add


            def make_price_formatters_buggy(currency_codes: list[str]) -> list[Callable[[float], str]]:
                return [lambda amount: f"{code} {amount:.2f}" for code in currency_codes]  # noqa: B023


            print(f"{add_tag_buggy('new')=}, {add_tag_buggy('sale')=}")
            print(f"accumulator: {raised_error_name(lambda: make_accumulator_buggy()(5))}")
            print([formatter(250) for formatter in make_price_formatters_buggy(["INR", "USD"])])
            """
        ),
        md("Write the fixed versions here."),
        code(
            '''
            def add_tag(tag: str, tags: list[str] | None = None) -> list[str]:
                """Return a new list holding the given tags followed by tag."""
                raise NotImplementedError("Lab 1.11: fix add_tag()")


            def make_accumulator() -> Callable[[float], float]:
                """Return add(amount), which returns the running total."""
                raise NotImplementedError("Lab 1.11: fix make_accumulator()")


            def make_price_formatters(currency_codes: list[str]) -> list[Callable[[float], str]]:
                """Return one formatter per currency code, e.g. 'INR 250.00'."""
                raise NotImplementedError("Lab 1.11: fix make_price_formatters()")
            '''
        ),
        md("Run the checks."),
        code(
            '''
            def accumulator_trace() -> list[float]:
                """Running totals from one accumulator."""
                add = make_accumulator()
                return [add(100), add(49.5), add(-20)]


            def caller_list_untouched() -> tuple[list[str], list[str]]:
                """The caller's list is not modified."""
                existing_tags = ["new"]
                return add_tag("sale", existing_tags), existing_tags


            run_checks(
                [
                    ("add_tag fresh default", lambda: (add_tag("new"), add_tag("sale")), (["new"], ["sale"])),
                    ("add_tag keeps caller list", caller_list_untouched, (["new", "sale"], ["new"])),
                    ("accumulator", accumulator_trace, [100, 149.5, 129.5]),
                    (
                        "accumulators independent",
                        lambda: (make_accumulator()(1), make_accumulator()(2)),
                        (1, 2),
                    ),
                    (
                        "formatters",
                        lambda: [f(250) for f in make_price_formatters(["INR", "USD", "EUR"])],
                        ["INR 250.00", "USD 250.00", "EUR 250.00"],
                    ),
                    (
                        "formatter per currency",
                        lambda: [f(9.5) for f in make_price_formatters(["INR", "USD"])][0],
                        "INR 9.50",
                    ),
                ]
            )
            '''
        ),
        md(
            """
            #### Exercise 3 — closure-based field validation

            Write three **validator factories**. Each returns a validator: a function that takes a
            string and returns an error message, or `None` if the value is valid.

            | Factory | Error message (exactly) |
            | --- | --- |
            | `min_length(length)` | `"must be at least {length} characters"` |
            | `matches_pattern(pattern, description)` | `"must be {description}"` (use `re.fullmatch`) |
            | `one_of(allowed_values)` | `"must be one of: a, b, c"` (allowed values sorted, joined with `", "`) |

            Then `validate_record(record, rules)`: `rules` maps a field name to a list of
            validators. Return a dict mapping each field to its list of error messages, in rule
            order, leaving out fields with no errors. A field missing from `record` is
            validated as `""`.
            """
        ),
        code(
            '''
            type Validator = Callable[[str], str | None]


            def min_length(length: int) -> Validator:
                """Return a validator that rejects values shorter than length."""
                raise NotImplementedError("Lab 1.11: implement min_length()")


            def matches_pattern(pattern: str, description: str) -> Validator:
                """Return a validator that rejects values that do not fully match pattern."""
                raise NotImplementedError("Lab 1.11: implement matches_pattern()")


            def one_of(allowed_values: set[str]) -> Validator:
                """Return a validator that rejects values outside allowed_values."""
                raise NotImplementedError("Lab 1.11: implement one_of()")


            def validate_record(
                record: dict[str, str], rules: dict[str, list[Validator]]
            ) -> dict[str, list[str]]:
                """Return {field: [error messages]} for every field that has errors."""
                raise NotImplementedError("Lab 1.11: implement validate_record()")
            '''
        ),
        md("Run the checks. `signup_rules()` builds a realistic rule set for a sign-up form."),
        code(
            '''
            def signup_rules() -> dict[str, list[Validator]]:
                """Rules for a sign-up form, built from the three factories."""
                return {
                    "password": [min_length(8), matches_pattern(r".*\\d.*", "a value containing a digit")],
                    "username": [min_length(3), matches_pattern(r"[a-z_]+", "lowercase letters or _")],
                    "plan": [one_of({"free", "pro", "team"})],
                }


            run_checks(
                [
                    ("min_length ok", lambda: min_length(3)("abc"), None),
                    ("min_length short", lambda: min_length(8)("abc"), "must be at least 8 characters"),
                    ("pattern ok", lambda: matches_pattern(r"\\d{6}", "a 6-digit PIN code")("560001"), None),
                    (
                        "pattern is a full match",
                        lambda: matches_pattern(r"\\d{6}", "a 6-digit PIN code")("5600012"),
                        "must be a 6-digit PIN code",
                    ),
                    ("one_of ok", lambda: one_of({"free", "pro"})("pro"), None),
                    ("one_of message", lambda: one_of({"pro", "free"})("gold"), "must be one of: free, pro"),
                    (
                        "valid record",
                        lambda: validate_record(
                            {"password": "chai2024!", "username": "asha", "plan": "pro"}, signup_rules()
                        ),
                        {},
                    ),
                    (
                        "invalid record",
                        lambda: validate_record({"password": "chai", "username": "Asha K"}, signup_rules()),
                        {
                            "password": ["must be at least 8 characters", "must be a value containing a digit"],
                            "username": ["must be lowercase letters or _"],
                            "plan": ["must be one of: free, pro, team"],
                        },
                    ),
                    ("validators are closures", lambda: min_length(8).__closure__ is not None, True),
                ]
            )
            '''
        ),
    ]


def _recap_cells() -> list[NotebookNode]:
    """Recap for Unit 1.11."""
    return [
        md(
            """
            ### Recap — Unit 1.11

            | Concept | One-line takeaway | JS equivalent |
            | --- | --- | --- |
            | Namespaces | Built-in, module (`globals()`), class (`__dict__`), function (a new one per call) | global object, module scope, function scope |
            | `locals()` | A dict snapshot of a function's fast locals; writes are ignored (3.13+) | — |
            | LEGB | Local → Enclosing → Global → Built-in → `NameError`; class bodies are skipped | scope chain |
            | Shadowing | `list = [...]` hides the built-in for the whole module; `del list` restores it | shadowing `Array`, `name` |
            | No block scope | `if` / `for` / `with` / `try` names survive; `except … as e` is deleted | `var` (`let` is block-scoped) |
            | Comprehension scope | Loop variables stay inside (inlined since 3.12); `:=` leaks on purpose | — |
            | Compile-time scope | Any assignment makes a name local for the whole function → `UnboundLocalError` | `let` TDZ (`ReferenceError`) |
            | `co_varnames` / `co_names` | Local slots / global and attribute names; `LOAD_FAST_CHECK` guards maybe-unbound locals | — |
            | `global` / `nonlocal` | Needed to rebind, not to mutate; prefer passing state explicitly | assignment just works |
            | Closures | Inner functions keep enclosing variables alive in cells (`__closure__`, `cell_contents`) | closures |
            | Late binding | Closures read variables at call time; fix with `x=x` defaults or `functools.partial` | `var` in loops; fixed by `let` |
            | Lookup cost | `LOAD_FAST` < `LOAD_DEREF` < `LOAD_GLOBAL`; alias only in measured hot loops | — |

            **Further reading**

            - [Tutorial: Python scopes and namespaces](https://docs.python.org/3/tutorial/classes.html#python-scopes-and-namespaces)
            - [Execution model: naming and binding](https://docs.python.org/3/reference/executionmodel.html#naming-and-binding)
            - [The `global` statement](https://docs.python.org/3/reference/simple_stmts.html#the-global-statement),
              [the `nonlocal` statement](https://docs.python.org/3/reference/simple_stmts.html#the-nonlocal-statement)
            - [FAQ: why am I getting an UnboundLocalError?](https://docs.python.org/3/faq/programming.html#why-am-i-getting-an-unboundlocalerror-when-the-variable-has-a-value),
              [FAQ: lambdas defined in a loop](https://docs.python.org/3/faq/programming.html#why-do-lambdas-defined-in-a-loop-with-different-values-all-return-the-same-result)
            - [`builtins`](https://docs.python.org/3/library/builtins.html),
              [`inspect.getclosurevars`](https://docs.python.org/3/library/inspect.html#inspect.getclosurevars),
              [`dis`](https://docs.python.org/3/library/dis.html)
            - [PEP 227 — Statically nested scopes](https://peps.python.org/pep-0227/),
              [PEP 3104 — Access to names in outer scopes (`nonlocal`)](https://peps.python.org/pep-3104/),
              [PEP 572 — Assignment expressions](https://peps.python.org/pep-0572/)
            - [PEP 709 — Inlined comprehensions](https://peps.python.org/pep-0709/),
              [PEP 667 — Consistent views of namespaces](https://peps.python.org/pep-0667/)
            """
        ),
    ]


def cells() -> list[NotebookNode]:
    """Return the cells for Unit 1.11 and Lab 1.11."""
    return [
        *_overview_cells(),
        *_namespace_cells(),
        *_legb_cells(),
        *_block_scope_cells(),
        *_compile_time_cells(),
        *_global_nonlocal_cells(),
        *_closure_cells(),
        *_late_binding_cells(),
        *_lookup_cost_cells(),
        *_lab_cells(),
        *_recap_cells(),
    ]
