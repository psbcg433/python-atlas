"""Unit 3.2 — Bytecode and the Interpreter (with Lab 3.2)."""

from nbformat import NotebookNode

from nb_builder import code, md, predict_cells

UNIT_SETUP_SOURCE = '''
import ast
import compileall
import contextlib
import dis
import functools
import importlib.machinery
import importlib.util
import inspect
import io
import marshal
import os
import platform
import py_compile
import re
import shutil
import signal
import struct
import subprocess
import sys
import sysconfig
import tempfile
import textwrap
import threading
import time
import tokenize
import types
from collections import Counter
from collections.abc import Callable
from pathlib import Path

CHILD_ENV = {**os.environ, "PYTHON_COLORS": "0"}  # plain output from child interpreters


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


def interpreter_label() -> str:
    """Implementation, version and build flavour: print it next to any dis listing."""
    free_threaded = bool(sysconfig.get_config_var("Py_GIL_DISABLED"))
    build = "free-threaded build" if free_threaded else "default (GIL) build"
    implementation = platform.python_implementation()
    return f"{implementation} {platform.python_version()}, {build}, {platform.machine()}"


_CODE_OBJECT_REPR = re.compile(r'<code object (\\S+) at 0x[0-9a-f]+, file "[^"]*", line \\d+>')


def show_dis(target: object, **options: object) -> None:
    """dis.dis(target) under a version banner, without code-object addresses or file paths."""
    buffer = io.StringIO()
    dis.dis(target, file=buffer, **options)
    print(f"# dis on {interpreter_label()} (instruction names change between versions)")
    print(_CODE_OBJECT_REPR.sub(r"<code object \\1>", buffer.getvalue()).rstrip())


def opnames(function: Callable[..., object], *, adaptive: bool = False) -> list[str]:
    """Instruction names of a function (adaptive=True shows specialized forms)."""
    return [instruction.opname for instruction in dis.get_instructions(function, adaptive=adaptive)]


print(interpreter_label())
'''


def _overview_cells() -> list[NotebookNode]:
    """Unit opener and setup."""
    return [
        md(
            """
            ## Unit 3.2 — Bytecode and the Interpreter

            **Objectives**

            - Name the parts of CPython and follow source code through tokens, the AST, the
              compiler and the evaluation loop.
            - Inspect and rebuild **code objects** and **function objects**.
            - Read `dis` output fluently: columns, the value stack, loads and stores, calls,
              jumps and loops.
            - Recognize compiler optimizations, the specializing adaptive interpreter
              (PEP 659) and the JIT (PEP 744) in real output.
            - Understand what the GIL and the eval breaker do between instructions.
            - Use `compile`, `exec`, `eval` and `ast` safely, and transform code with
              `NodeTransformer`.
            - Read a `.pyc` file byte by byte.

            **JS bridge**

            | JavaScript (V8) | Python (CPython) | The difference that bites |
            | --- | --- | --- |
            | Parser → AST → Ignition bytecode | Tokenizer + PEG parser → AST → compiler → bytecode | Python's bytecode is easy to see: `dis` is in the standard library |
            | Ignition (register-based interpreter) | Stack-based evaluation loop (`Python/ceval.c`) | Instructions push and pop a value stack instead of naming registers |
            | Inline caches + hidden classes (maps) | Specializing adaptive interpreter: inline caches keyed on type versions | Same idea (guess types from history, guard, fall back), different names |
            | Sparkplug, Maglev, TurboFan (optimizing JITs) | Tier-2 micro-ops + copy-and-patch JIT (experimental, off by default) | CPython's JIT is young; most speed comes from specialization |
            | `eval`, `new Function(...)` | `eval`, `exec`, `compile` | Same danger: never on untrusted input |
            | Babel / ESLint plugins (AST transforms) | `ast.NodeVisitor`, `ast.NodeTransformer` | AST tools are built in; pytest rewrites your asserts this way |
            | V8 code cache | `.pyc` files in `__pycache__` | `.pyc` holds marshalled code objects, not machine code |

            > **Note:** `dis` output changes in **every** Python release: instruction names,
            > arguments, caches and offsets. Each listing below prints the interpreter version
            > above it; on another version your listing will differ, the concepts will not.

            The next cell is this unit's setup. It defines `show_dis(target, **options)`, which
            prints `dis.dis` output under a version banner with code-object addresses removed,
            and `opnames(function, adaptive=False)`.
            """
        ),
        code(UNIT_SETUP_SOURCE),
    ]


def _architecture_cells() -> list[NotebookNode]:
    """3.2.1 CPython architecture tour."""
    return [
        md(
            """
            ### 3.2.1 CPython architecture tour

            CPython is a C program. Its source tree maps onto the pipeline you met in
            Unit 1.1:

            ```mermaid
            flowchart LR
                S["source text"] --> T["tokenizer<br/>Parser/lexer"]
                T --> P["PEG parser<br/>Parser/parser.c"]
                P --> A["AST<br/>Python/ast.c"]
                A --> C["symbol table + compiler<br/>Python/symtable.c, compile.c,<br/>flowgraph.c, assemble.c"]
                C --> K["code object"]
                K --> E["eval loop<br/>Python/ceval.c + bytecodes.c"]
                E --> O["objects<br/>Objects/*.c"]
            ```

            <details><summary>ASCII fallback</summary>

            ```text
            source -> tokenizer (Parser/lexer) -> PEG parser (Parser/parser.c) -> AST (Python/ast.c)
                   -> symtable + compiler (Python/symtable.c, compile.c, flowgraph.c, assemble.c)
                   -> code object -> eval loop (Python/ceval.c, bytecodes.c) -> objects (Objects/*.c)
            ```

            </details>

            | Directory / file | What lives there |
            | --- | --- |
            | `Grammar/python.gram` | The PEG grammar; `Parser/parser.c` is **generated** from it |
            | `Parser/` | Tokenizer and parser |
            | `Python/compile.c`, `flowgraph.c`, `assemble.c` | AST → control-flow graph → optimized bytecode |
            | `Python/bytecodes.c` | Every instruction, written in a small DSL; generates `generated_cases.c.h` for the eval loop |
            | `Python/ceval.c` | The evaluation loop: runs frames instruction by instruction |
            | `Python/specialize.c` | The specializing adaptive interpreter (3.2.8) |
            | `Python/optimizer*.c`, `Python/jit.c` | Tier-2 micro-ops and the JIT (3.2.9) |
            | `Python/gc.c`, `Objects/obmalloc.c` | Cyclic GC and pymalloc (Unit 3.1) |
            | `Objects/` | Built-in types: `listobject.c`, `dictobject.c`, `longobject.c`, `unicodeobject.c`, `typeobject.c` |
            | `Modules/` | C extension modules: `mathmodule.c`, `_json.c`, `_asynciomodule.c` |
            | `Lib/` | The standard library written in Python (`json/`, `dis.py`, `ast.py`) |
            | `Include/` | Public and internal C headers (`object.h` defines `PyObject`) |

            The cell traces where some familiar names come from: compiled into the interpreter
            (`built-in`), a C extension file, or Python source in `Lib/`. Only file **names**
            are printed.
            """
        ),
        code(
            '''
            def module_origin(module_name: str) -> str:
                """Where a module's code comes from: built in, C extension, frozen, or Python source."""
                spec = importlib.util.find_spec(module_name)
                if spec is None or spec.origin is None:
                    return "not found"
                if spec.origin in {"built-in", "frozen"}:
                    return f"{spec.origin} (compiled into the interpreter)"
                file_name = Path(spec.origin).name
                if spec.origin.endswith(tuple(importlib.machinery.EXTENSION_SUFFIXES)):
                    return f"C extension file {file_name}"
                return f"Python source {Path(spec.origin).parent.name}/{file_name}"


            print(f"{sys.version=}")
            print(f"{platform.python_compiler()=}")
            for module_name in ("sys", "builtins", "gc", "_opcode", "math", "_json", "json", "dis", "ast"):
                print(f"{module_name:<9} {module_origin(module_name)}")
            print(f"{type(len).__name__=}  (Python/bltinmodule.c)")
            print(f"{type(list.append).__name__=}  (Objects/listobject.c)")
            '''
        ),
    ]


def _token_ast_cells() -> list[NotebookNode]:
    """3.2.2 Tokens and the AST."""
    return [
        md(
            """
            ### 3.2.2 Tokens and the AST

            **Tokens.** The tokenizer turns text into a stream of typed tokens. The
            `tokenize` module exposes the same tokenizer CPython uses (including comments,
            `NEWLINE`, `INDENT` and `DEDENT`, which the parser needs because indentation is
            syntax).
            """
        ),
        code(
            '''
            invoice_source = textwrap.dedent(
                """
                if quantity > 10:  # bulk order
                    total = price * quantity * 0.9
                """
            ).lstrip()
            for token in tokenize.generate_tokens(io.StringIO(invoice_source).readline):
                print(f"{tokenize.tok_name[token.type]:<9} {token.string!r}")
            '''
        ),
        md(
            """
            **`ast.parse` and `ast.dump`.** The parser builds an **abstract syntax tree**:
            comments and most punctuation are gone, structure remains. `ast.dump(tree,
            indent=2)` prints it.
            """
        ),
        code(
            """
            tree = ast.parse("total = price * quantity")
            print(ast.dump(tree, indent=2))
            """
        ),
        md(
            """
            **Node types.** Every node is an instance of a class in `ast`. The common ones:

            | Node | Example source | Key fields |
            | --- | --- | --- |
            | `Module` | a whole file | `body` |
            | `FunctionDef` | `def f(x): ...` | `name`, `args`, `body`, `decorator_list` |
            | `Assign` | `x = 1` | `targets`, `value` |
            | `BinOp` | `a * b` | `left`, `op`, `right` |
            | `Compare` | `a > b` | `left`, `ops`, `comparators` |
            | `Call` | `f(x, key=1)` | `func`, `args`, `keywords` |
            | `Name` | `price` | `id`, `ctx` (`Load` / `Store` / `Del`) |
            | `Constant` | `0.9`, `"INR"` | `value` |
            | `Attribute` | `order.total` | `value`, `attr` |
            | `If`, `For`, `While`, `Return`, `Try` | statements | `test` / `target` / `iter` / `body` / `handlers` |

            Every node also records where it came from (`lineno`, `col_offset`,
            `end_lineno`, `end_col_offset`). `ast.walk` visits every node.
            """
        ),
        code(
            '''
            pricing_source = textwrap.dedent(
                """
                def order_total(lines, tax_rate=0.18):
                    subtotal = sum(line.price * line.quantity for line in lines)
                    if subtotal > 1000:
                        subtotal = subtotal * 0.95
                    return round(subtotal * (1 + tax_rate), 2)
                """
            )
            pricing_tree = ast.parse(pricing_source)
            node_counts = Counter(type(node).__name__ for node in ast.walk(pricing_tree))
            print(dict(node_counts.most_common(8)))
            function_node = pricing_tree.body[0]
            line_span = f"{function_node.lineno}-{function_node.end_lineno}"
            print(f"{type(function_node).__name__} {function_node.name!r} spans lines {line_span}")
            print(f"{[argument.arg for argument in function_node.args.args]=}")
            print(f"{ast.dump(function_node.args.defaults[0])=}")
            '''
        ),
        md(
            """
            **`ast.unparse`** (3.9+) turns a tree back into source. The round trip keeps the
            meaning but not the formatting: comments and redundant parentheses are gone.
            """
        ),
        code(
            """
            original = "total  =  (price * quantity)   # with comment"
            print(f"{original!r}")
            print(f"{ast.unparse(ast.parse(original))!r}")
            print(ast.unparse(pricing_tree))
            """
        ),
    ]


def _code_object_cells() -> list[NotebookNode]:
    """3.2.3 Code objects."""
    return [
        md(
            """
            ### 3.2.3 Code objects

            The compiler produces a **code object** for every module, class body, function,
            lambda and generator expression. It is immutable and holds everything needed to
            run the code, except the run-time context (globals, defaults, closure cells),
            which lives on the function object (3.2.4).

            | Attribute | Holds |
            | --- | --- |
            | `co_code` | The bytecode: 2 bytes per instruction (opcode, argument) plus inline cache slots |
            | `co_consts`, `co_names`, `co_varnames` | Constants (numbers, strings, nested code objects); global and attribute names (`LOAD_GLOBAL`, `LOAD_ATTR` index into it); local variable names, arguments first |
            | `co_freevars`, `co_cellvars` | Variables read from an enclosing function (closure, 1.11); this function's variables that inner functions capture |
            | `co_flags` | Bit flags: optimized, generator, coroutine, has `*args`, … |
            | `co_qualname` | Qualified name (*New in 3.11*) |
            | `co_exceptiontable` | Where to jump when an exception occurs (*New in 3.11*, replaces setup/pop block instructions) |
            | `code.replace(...)` | A copy with some fields changed |

            One cell per row follows. They all use this closure-based formatter:
            """
        ),
        code(
            '''
            def make_price_formatter(currency: str) -> Callable[..., str]:
                """Return a formatter that remembers the currency (a closure)."""
                symbol_width = 3

                def format_price(amount: float, *, decimals: int = 2) -> str:
                    """Format an amount with the currency."""
                    try:
                        return f"{currency:>{symbol_width}} {amount:,.{decimals}f}"
                    except ValueError:
                        return f"{currency} ?"

                return format_price


            format_inr = make_price_formatter("INR")
            price_code = format_inr.__code__
            print(f"{format_inr(1234.5)=}  {type(price_code).__name__=}")
            '''
        ),
        md(
            """
            #### `co_code`

            Raw bytes. In 3.11+ some instructions are followed by **inline cache** entries
            (`CACHE` slots, 3.2.8), so the byte count is larger than two bytes per visible
            instruction.
            """
        ),
        code(
            """
            visible_instructions = list(dis.get_instructions(price_code))
            print(f"{len(price_code.co_code)=} bytes for {len(visible_instructions)} visible instructions")
            print(f"first 12 bytes: {price_code.co_code[:12].hex(' ')}")
            first = visible_instructions[0]
            print(f"first instruction: {first.opname} (opcode {first.opcode})  [{interpreter_label()}]")
            """
        ),
        md(
            """
            #### `co_consts`, `co_names`, `co_varnames`

            Instructions refer to these tuples by index: `LOAD_CONST 2` loads
            `co_consts[2]`; `STORE_FAST 1` stores into local slot 1, named `co_varnames[1]`.
            """
        ),
        code(
            """
            print(f"{price_code.co_consts=}")
            print(f"{price_code.co_names=}")
            print(f"{price_code.co_varnames=}  (arguments first: amount, decimals)")
            print(f"{price_code.co_argcount=}  {price_code.co_kwonlyargcount=}  {price_code.co_nlocals=}")
            """
        ),
        md(
            """
            #### `co_freevars` and `co_cellvars`

            The outer function lists the captured variables in `co_cellvars`; the inner one
            lists them in `co_freevars`. At run time each is a **cell** object shared by both.
            """
        ),
        code(
            """
            outer_code = make_price_formatter.__code__
            print(f"{outer_code.co_cellvars=}  (captured by the inner function)")
            print(f"{price_code.co_freevars=}  (read from the outer function)")
            print(f"{[cell.cell_contents for cell in format_inr.__closure__]=}")
            """
        ),
        md(
            """
            #### `co_flags`

            A bit field. `dis.COMPILER_FLAG_NAMES` maps bits to names; `inspect` has
            constants such as `inspect.CO_GENERATOR`.
            """
        ),
        code(
            '''
            def flag_names(code_object: types.CodeType) -> list[str]:
                """Names of the flags set in a code object."""
                return [name for bit, name in dis.COMPILER_FLAG_NAMES.items() if code_object.co_flags & bit]


            def countdown(start: int):
                """A generator."""
                yield from range(start, 0, -1)


            print(f"format_price:    {flag_names(price_code)}")
            print(f"countdown:       {flag_names(countdown.__code__)}")
            print(f"make_price_formatter: {flag_names(outer_code)}")
            print(f"{bool(countdown.__code__.co_flags & inspect.CO_GENERATOR)=}")
            '''
        ),
        md(
            """
            #### `co_qualname`

            *New in 3.11.* The qualified name, which shows nesting, like `__qualname__` on
            functions.
            """
        ),
        code(
            """
            print(f"{price_code.co_name=}")
            print(f"{price_code.co_qualname=}")
            """
        ),
        md(
            """
            #### The exception table

            *New in 3.11.* `try` costs nothing when no exception happens: instead of
            "setup block" instructions, the code object carries a table of
            `start–end → target` ranges, consulted only when an exception is raised. `dis`
            prints it at the end as `ExceptionTable:`, and `dis.Bytecode(...).exception_entries`
            returns it as data.
            """
        ),
        code(
            """
            show_dis(format_inr)
            for entry in dis.Bytecode(format_inr).exception_entries:
                print(f"offsets {entry.start}-{entry.end} -> handler at {entry.target}, depth {entry.depth}")
            """
        ),
        md(
            """
            #### `code.replace`

            Code objects are immutable; `replace(**changes)` returns a modified copy. Here a
            constant is swapped and the result wrapped in a new function (`types.FunctionType`,
            3.2.4). Tools like coverage and debuggers use the same technique.
            """
        ),
        code(
            '''
            def greet(name: str) -> str:
                """Greet in Hindi."""
                return "Namaste, " + name


            greet_code = greet.__code__
            english_consts = tuple(
                "Hello, " if value == "Namaste, " else value for value in greet_code.co_consts
            )
            english_code = greet_code.replace(
                co_consts=english_consts, co_name="greet_english", co_qualname="greet_english"
            )
            greet_english = types.FunctionType(english_code, globals(), "greet_english")
            print(f"{greet('Asha')=}  {greet_english('Asha')=}")
            print(f"{greet_code is english_code=}  {greet_code.co_consts=}")
            '''
        ),
    ]


def _function_object_cells() -> list[NotebookNode]:
    """3.2.4 Function objects."""
    return [
        md(
            """
            ### 3.2.4 Function objects

            Running a `def` statement builds a **function object** around a code object
            compiled earlier. The function adds the run-time context:

            | Function attribute | What it supplies |
            | --- | --- |
            | `__code__` | The code object (shared by every function made from the same `def`) |
            | `__globals__` | The module namespace used by `LOAD_GLOBAL` |
            | `__defaults__`, `__kwdefaults__` | Default values, evaluated once when `def` ran |
            | `__closure__` | A tuple of cells for `co_freevars` |
            | `__name__`, `__qualname__`, `__module__`, `__doc__`, `__dict__` | Metadata |

            `types.FunctionType(code, globals, name=None, argdefs=None, closure=None)` builds
            one by hand, which proves that a function is just these pieces.
            """
        ),
        code(
            """
            print(f"{format_inr.__code__ is price_code=}")
            print(f"{format_inr.__globals__ is globals()=}")
            print(f"{format_inr.__defaults__=}  {format_inr.__kwdefaults__=}")
            print(f"{format_inr.__name__=}  {format_inr.__qualname__=}")
            format_usd = make_price_formatter("USD")
            print(f"{format_usd.__code__ is format_inr.__code__=}  (one code object, two functions)")
            print(f"{format_usd.__closure__ is format_inr.__closure__=}  (different cells)")
            """
        ),
        md(
            """
            **Same code, different globals.** `LOAD_GLOBAL` looks names up in the function's
            `__globals__`, so the same code object gives different answers in a different
            namespace.
            """
        ),
        code(
            '''
            GST_RATE = 0.18


            def with_tax(amount: float) -> float:
                """Add GST using the module-level rate."""
                return round(amount * (1 + GST_RATE), 2)


            with_low_tax = types.FunctionType(
                with_tax.__code__, {"GST_RATE": 0.05, "round": round}, "with_low_tax"
            )
            print(f"{with_tax(100)=}  {with_low_tax(100)=}")
            '''
        ),
        md(
            """
            **Defaults and closures by hand.** `argdefs` fills `__defaults__`; `closure` must
            be a tuple of `types.CellType` objects in the order of `co_freevars`.
            """
        ),
        code(
            """
            cells_by_name = {"currency": types.CellType("EUR"), "symbol_width": types.CellType(5)}
            closure = tuple(cells_by_name[name] for name in price_code.co_freevars)
            format_eur = types.FunctionType(price_code, globals(), "format_eur", None, closure)
            format_eur.__kwdefaults__ = {"decimals": 1}
            print(f"{format_eur(99.25)=}")
            print(f"{format_inr(99.25)=}  (unchanged)")
            """
        ),
    ]


def _reading_dis_cells() -> list[NotebookNode]:
    """3.2.5 Reading dis."""
    return [
        md(
            """
            ### 3.2.5 Reading `dis`

            **Columns.** Each line of `dis.dis` output is one instruction:

            | Column | Example | Meaning |
            | --- | --- | --- |
            | Source line | `3` | Line number, printed when it changes |
            | Label | `L1:` | Jump target (*Changed in 3.13*: labels replace offsets by default) |
            | Offset | `8` | Byte offset in `co_code` (shown with `show_offsets=True`, 3.13+) |
            | Opname | `BINARY_OP` | The instruction |
            | Oparg | `5` | Its integer argument |
            | Argrepr | `(*)` | What the argument means: a name, a constant, an operator, a jump target |
            """
        ),
        code(
            '''
            def discounted_price(price: float, percent: float) -> float:
                """Price after a percentage discount."""
                return price - price * percent / 100


            show_dis(discounted_price)
            if sys.version_info >= (3, 13):
                print()
                show_dis(discounted_price, show_offsets=True)
            '''
        ),
        md(
            """
            **A stack machine.** CPython's evaluation loop keeps a **value stack** per frame.
            Loads push, operators pop their operands and push the result, `RETURN_VALUE` pops
            the result and hands it to the caller. The walkthrough for `discounted_price` (on
            3.15; `LOAD_FAST_BORROW_LOAD_FAST_BORROW` is a *superinstruction* that loads two
            locals at once):

            | Instruction | Pops | Pushes | Stack after (bottom → top) |
            | --- | --- | --- | --- |
            | `LOAD_FAST_BORROW_LOAD_FAST_BORROW (price, price)` | — | 2 | `price`, `price` |
            | `LOAD_FAST_BORROW (percent)` | — | 1 | `price`, `price`, `percent` |
            | `BINARY_OP (*)` | 2 | 1 | `price`, `price*percent` |
            | `LOAD_SMALL_INT 100` | — | 1 | `price`, `price*percent`, `100` |
            | `BINARY_OP (/)` | 2 | 1 | `price`, `price*percent/100` |
            | `BINARY_OP (-)` | 2 | 1 | `price - price*percent/100` |
            | `RETURN_VALUE` | 1 | — | *(empty: the value goes to the caller)* |

            `dis.stack_effect(opcode, oparg)` gives the net change for each instruction; the
            cell replays it to confirm the depth column. The compiler stores the maximum in
            `co_stacksize`.
            """
        ),
        code(
            """
            depth = 0
            for instruction in dis.get_instructions(discounted_price):
                if instruction.opname == "RETURN_VALUE":
                    depth -= 1  # pops the return value
                elif instruction.arg is None:
                    depth += dis.stack_effect(instruction.opcode)
                else:
                    depth += dis.stack_effect(instruction.opcode, instruction.arg)
                print(f"{instruction.opname:<34} {instruction.argrepr:<16} depth after: {depth}")
            print(f"{discounted_price.__code__.co_stacksize=}  [{interpreter_label()}]")
            """
        ),
        md(
            """
            **Load and store families.** The opname tells you **where** a name lives:

            | Family | Load / store | Used for |
            | --- | --- | --- |
            | `*_FAST` | `LOAD_FAST`, `LOAD_FAST_BORROW` (3.14+), `STORE_FAST` | Function locals: an array slot, the fastest |
            | `*_DEREF` | `LOAD_DEREF`, `STORE_DEREF` | Closure cells (`nonlocal`, captured variables) |
            | `*_GLOBAL` | `LOAD_GLOBAL`, `STORE_GLOBAL` | Module globals, then builtins |
            | `*_NAME` | `LOAD_NAME`, `STORE_NAME` | Module and class bodies (dict lookups) |
            | `*_ATTR` | `LOAD_ATTR`, `STORE_ATTR` | `obj.attr` |
            | Subscript | `BINARY_OP ([])` (3.14+), `STORE_SUBSCR` | `obj[key]` |
            | Constants | `LOAD_CONST`, `LOAD_SMALL_INT` (3.14+) | Literals |

            One function that touches every family, then its instructions grouped:
            """
        ),
        code(
            '''
            RESTOCK_LEVEL = 5


            def make_restocker(warehouse: dict[str, int]) -> Callable[[object], int]:
                """Inner function uses locals, a closure cell, a global, attributes and subscripts."""
                restocked = 0

                def restock(item: object) -> int:
                    nonlocal restocked  # *_DEREF
                    global RESTOCK_LEVEL  # *_GLOBAL
                    current = warehouse[item.sku]  # subscript + attribute
                    if current < RESTOCK_LEVEL:
                        warehouse[item.sku] = RESTOCK_LEVEL  # STORE_SUBSCR
                        item.restocked = True  # STORE_ATTR
                        restocked += 1
                    RESTOCK_LEVEL = 5
                    return restocked

                return restock


            restock_names = opnames(make_restocker({}))
            for family in ("FAST", "DEREF", "GLOBAL", "ATTR", "SUBSCR", "BINARY_OP", "SMALL_INT"):
                print(f"{family:<10} {sorted({name for name in restock_names if family in name})}")
            '''
        ),
        md(
            """
            **Calls.** A call pushes the callable (and a `NULL` or `self` slot used for method
            calls), then the arguments, then runs `CALL n`. Keyword arguments use `CALL_KW`
            with a tuple of names; `f(*args)` uses `CALL_FUNCTION_EX`. In the listing,
            `LOAD_ATTR (total + NULL|self)` loads a method in a way that avoids creating a
            bound-method object.
            """
        ),
        code(
            '''
            def checkout(cart: object, *extra: object) -> str:
                """A method call, a keyword call and a star call."""
                total = cart.total()
                label = format(total, ",.2f")
                print(label, end="\\n")
                print(*extra)
                return label


            show_dis(checkout)
            '''
        ),
        md(
            """
            **Jumps.** `if` compiles to a comparison and a conditional jump. 3.13+ inserts
            `TO_BOOL` (or a comparison that already yields a bool), and 3.14 adds
            `NOT_TAKEN` markers used to record branch history.
            """
        ),
        code(
            '''
            def shipping_band(weight_kg: float) -> str:
                """One if/else."""
                if weight_kg > 20:
                    return "freight"
                return "parcel"


            show_dis(shipping_band)
            '''
        ),
        md(
            """
            **Loops.** A `for` loop is `GET_ITER`, then `FOR_ITER` (which jumps out when the
            iterator is exhausted), the body, and `JUMP_BACKWARD` to the top. A `while` loop
            is a test, a conditional jump out, the body and `JUMP_BACKWARD`. Backward jumps
            are where the interpreter checks the eval breaker (3.2.10) and where hot loops are
            detected for the JIT (3.2.9).
            """
        ),
        code(
            '''
            def drain_stock(quantities: list[int]) -> int:
                """A for loop and a while loop."""
                total = 0
                for quantity in quantities:
                    total += quantity
                while total > 100:
                    total -= 40
                return total


            show_dis(drain_stock)
            '''
        ),
        md(
            """
            **`dis.get_instructions`** returns `Instruction` named tuples instead of text, so
            tools can analyse bytecode. Useful fields: `opname`, `opcode`, `arg`, `argval`,
            `argrepr`, `offset`, `line_number` (3.13+), `label`, `positions` (exact source
            columns, 3.11+). The cell lists the jumps in `drain_stock` and where they go.
            """
        ),
        code(
            """
            drain_instructions = list(dis.get_instructions(drain_stock))
            labels_by_offset = {ins.offset: ins.label for ins in drain_instructions if ins.label}
            for instruction in drain_instructions:
                if "JUMP" in instruction.opname or instruction.opname == "FOR_ITER":
                    target = labels_by_offset.get(instruction.argval, instruction.argval)
                    print(f"line {instruction.line_number}: {instruction.opname:<18} -> L{target}")
            print(f"{drain_instructions[3].positions=}")
            """
        ),
    ]


def _optimization_cells() -> list[NotebookNode]:
    """3.2.6 Compiler optimizations."""
    return [
        md(
            """
            ### 3.2.6 Compiler optimizations

            CPython's compiler is deliberately simple, but it does a few things before your
            code runs:

            | Optimization | Example | Evidence |
            | --- | --- | --- |
            | Constant folding | `24 * 60 * 60` → `86400` | the folded value in `co_consts` |
            | Dead-code removal | code after `return`, `if False:` blocks | no instructions for them |
            | Constant containers for `in` | `x in [1, 2, 3]` → tuple; `x in {1, 2, 3}` → `frozenset` | a `LOAD_CONST` of the container |
            | Comprehension inlining (PEP 709, 3.12) | `[x * 2 for x in xs]` runs in the enclosing frame | no nested `<listcomp>` code object |

            **Constant folding.**
            """
        ),
        code(
            '''
            def seconds_per_day() -> tuple[int, str]:
                """Arithmetic on literals is folded at compile time."""
                return 24 * 60 * 60, "ab" * 3


            print(f"{seconds_per_day.__code__.co_consts=}")
            print(f"{opnames(seconds_per_day)=}")
            '''
        ),
        md(
            """
            **Dead-code removal.** No instructions are emitted for the `if False:` block or the
            line after `return`. The name `print` may still appear in `co_names` (names are
            collected before the dead code is dropped), but no instruction uses it.
            """
        ),
        code(
            '''
            def dead_code_example() -> int:
                """Contains unreachable code."""
                if False:
                    print("never compiled")
                return 1
                print("unreachable")


            print(f"{opnames(dead_code_example)=}")
            used_names = {ins.argval for ins in dis.get_instructions(dead_code_example)}
            print(f"{'print' in dead_code_example.__code__.co_names=}  {'print' in used_names=}")
            '''
        ),
        md(
            """
            **Constant containers for membership tests.** A list or set literal used only for
            `in` becomes an immutable constant built once at compile time, instead of a new
            list or set on every call.
            """
        ),
        code(
            '''
            def is_metro(city: str) -> tuple[bool, bool]:
                """Membership tests against literal containers."""
                return city in ["Delhi", "Mumbai", "Chennai"], city in {"Kolkata", "Bengaluru"}


            print(f"{is_metro.__code__.co_consts=}")
            '''
        ),
        md(
            """
            **Comprehension inlining (PEP 709, *New in 3.12*).** List, dict and set
            comprehensions used to compile into a hidden nested function (`<listcomp>`) that
            was called every time. Since 3.12 they are inlined into the enclosing code object,
            which saves a function call and a frame. Generator expressions still get their
            own code object, because they must be able to pause.
            """
        ),
        code(
            '''
            def comprehension_kinds(prices: list[float]) -> tuple[object, ...]:
                """A list comprehension, a dict comprehension and a generator expression."""
                doubled = [price * 2 for price in prices]
                labels = {price: f"{price:.2f}" for price in prices}
                lazy_total = sum(price for price in prices)
                return doubled, labels, lazy_total


            nested_code_objects = [
                constant.co_name
                for constant in comprehension_kinds.__code__.co_consts
                if isinstance(constant, types.CodeType)
            ]
            print(f"{nested_code_objects=}  (only the generator expression is separate)")
            saves_loop_variable = "LOAD_FAST_AND_CLEAR" in opnames(comprehension_kinds)
            print(f"{saves_loop_variable=}  (an inlined comprehension saves and restores its variable)")
            '''
        ),
    ]


def _eval_loop_cells() -> list[NotebookNode]:
    """3.2.7 The evaluation loop."""
    return [
        md(
            """
            ### 3.2.7 The evaluation loop

            `_PyEval_EvalFrameDefault` in `Python/ceval.c` runs a frame:

            ```text
            loop:
                instruction = code[instruction_pointer]      # fetch
                instruction_pointer += 1 + number of cache entries
                dispatch on instruction.opcode               # switch / computed goto / tail call
                    execute the body from bytecodes.c        # push, pop, call into Objects/*.c
                if the eval breaker is set: handle it        # at calls and backward jumps (3.2.10)
            ```

            - **Frames.** Each running call has an interpreter frame: the code object,
              globals, builtins, the local variable array, the value stack and the
              **instruction pointer**. Since 3.11 these frames are plain C structs pushed on a
              per-thread "data stack"; a Python `frame` object is created only when you ask
              for one.
            - **Inlined Python-to-Python calls (3.11).** When Python code calls a Python
              function, the loop pushes a new interpreter frame and **keeps going in the same
              C function**, instead of recursing into a new C call. Deep Python recursion no
              longer eats the C stack, and calls got much cheaper.
            - **Dispatch.** Builds with clang 19+ can use a *tail-calling* interpreter
              (*New in 3.14*): each instruction is a small C function that tail-calls the next.

            The frame object exposes the instruction pointer as `f_lasti` (byte offset of
            the current instruction) and the line as `f_lineno`.
            """
        ),
        code(
            '''
            def where_am_i() -> list[str]:
                """Describe the current frame and its callers."""
                described = []
                frame = sys._getframe()
                while frame is not None and len(described) < 2:
                    described.append(
                        f"{frame.f_code.co_qualname}: f_lasti={frame.f_lasti} f_lineno={frame.f_lineno}"
                    )
                    frame = frame.f_back
                return described


            def caller_of_where() -> list[str]:
                return where_am_i()


            print("\\n".join(caller_of_where()))
            tail_calls = bool(sysconfig.get_config_var("_Py_TAIL_CALL_INTERP"))
            print(f"tail-calling interpreter in this build: {tail_calls}")
            '''
        ),
        md(
            """
            **The instruction pointer survives a pause.** A generator keeps its frame
            between `next()` calls; `gi_frame.f_lasti` shows the loop resuming exactly where
            it stopped.
            """
        ),
        code(
            '''
            def ticket_numbers():
                """Yield three ticket numbers."""
                yield 101
                yield 102
                yield 103


            ticket_generator = ticket_numbers()
            for _ in range(3):
                ticket = next(ticket_generator)
                print(f"got {ticket}, paused at f_lasti={ticket_generator.gi_frame.f_lasti}")
            '''
        ),
        md(
            """
            **Inlined calls in action.** After warming up, the `CALL` in the caller becomes
            `CALL_PY_EXACT_ARGS`: the specialized form that sets up the callee's frame
            directly in the eval loop. And because Python-to-Python calls do not recurse in C,
            a 20 000-deep Python recursion works once the recursion limit allows it (the cell
            raises the limit temporarily and restores it).
            """
        ),
        code(
            '''
            def add_one(value: int) -> int:
                return value + 1


            def call_add_one(value: int) -> int:
                return add_one(value)


            for _ in range(1_000):
                call_add_one(1)
            print(f"{[name for name in opnames(call_add_one, adaptive=True) if name.startswith('CALL')]=}")


            def depth_of(remaining: int) -> int:
                """Recurse remaining levels deep."""
                return 0 if remaining == 0 else 1 + depth_of(remaining - 1)


            original_limit = sys.getrecursionlimit()
            sys.setrecursionlimit(25_000)
            try:
                print(f"{depth_of(20_000)=}  (default limit is {original_limit})")
            finally:
                sys.setrecursionlimit(original_limit)
            '''
        ),
    ]


def _specializing_cells() -> list[NotebookNode]:
    """3.2.8 Specializing adaptive interpreter (PEP 659)."""
    return [
        md(
            """
            ### 3.2.8 Specializing adaptive interpreter (PEP 659)

            *New in 3.11.* CPython watches the types each instruction actually sees and
            rewrites the instruction **in place** with a specialized version:

            | Term | Meaning |
            | --- | --- |
            | **Quickening** | After a function warms up, its generic instructions become *adaptive* ones with counters |
            | **Inline cache** | `CACHE` slots after an instruction in `co_code` store what was learned: a type version, a dict key index, a function version |
            | **Specialized instruction** | e.g. `LOAD_ATTR_INSTANCE_VALUE`, `BINARY_OP_ADD_INT`, `CALL_PY_EXACT_ARGS`, `LOAD_GLOBAL_MODULE` |
            | **Guard** | Each specialized instruction first checks its assumption (same type version, same dict keys) |
            | **Deoptimization** | A failed guard runs the generic path; after repeated misses the instruction re-specializes for the new types (with back-off) |

            `dis.dis(func, adaptive=True)` shows the current, specialized instructions.
            **Before** warming:
            """
        ),
        code(
            '''
            class CartLine:
                """A cart line with plain instance attributes."""

                def __init__(self, price: int, quantity: int) -> None:
                    self.price = price
                    self.quantity = quantity


            def line_total(line: object) -> object:
                """price * quantity of any object with those attributes."""
                return line.price * line.quantity


            show_dis(line_total, adaptive=True)
            '''
        ),
        md(
            """
            **After** 1 000 calls with `CartLine` objects holding ints. `RESUME` becomes
            `RESUME_CHECK`, both attribute loads become `LOAD_ATTR_INSTANCE_VALUE` (read the
            value straight from the object's inline values after checking the type version)
            and the multiplication becomes `BINARY_OP_MULTIPLY_INT`.
            """
        ),
        code(
            """
            for _ in range(1_000):
                line_total(CartLine(25, 4))
            show_dis(line_total, adaptive=True)
            """
        ),
        md(
            """
            **Inline caches.** `show_caches=True` reveals the `CACHE` slots that hold the
            learned facts (type version, index of the value). They are why `co_code` is longer
            than the visible instructions (3.2.3).
            """
        ),
        code(
            """
            cache_buffer = io.StringIO()
            dis.dis(line_total, adaptive=True, show_caches=True, file=cache_buffer)
            cache_slot_count = cache_buffer.getvalue().count("CACHE")
            print(f"visible instructions: {len(opnames(line_total))}, CACHE slots: {cache_slot_count}")
            print(f"{len(line_total.__code__.co_code)=} bytes  [{interpreter_label()}]")
            """
        ),
        md(
            """
            **Deoptimization.** Now feed it an object whose `price` is a **property** and whose
            values are floats. The guards fail, the instructions fall back, and after enough
            misses they re-specialize: `LOAD_ATTR_PROPERTY` for the first load, and a different
            `BINARY_OP` form for float × int.
            """
        ),
        code(
            '''
            class PromoLine:
                """price is a property, and a float."""

                def __init__(self, base_price: float, quantity: int) -> None:
                    self._base_price = base_price
                    self.quantity = quantity

                @property
                def price(self) -> float:
                    return self._base_price * 0.9


            warm_forms = opnames(line_total, adaptive=True)
            for _ in range(1_000):
                line_total(PromoLine(25.0, 4))
            for before, after in zip(warm_forms, opnames(line_total, adaptive=True), strict=True):
                marker = "   <- re-specialized" if before != after else ""
                print(f"{before:<26} -> {after:<26}{marker}")
            '''
        ),
        md(
            """
            #### JS bridge: hidden classes vs type versions

            | V8 | CPython |
            | --- | --- |
            | Every object has a hidden class (map); adding a property moves it to a new map | Every type has a **version tag**; changing the class (adding a method, assigning a class attribute) gives it a new version |
            | Inline cache at a property access remembers *map → offset* | `LOAD_ATTR_INSTANCE_VALUE` remembers *type version → slot index* |
            | Monomorphic / polymorphic / megamorphic sites | One specialization per instruction; on repeated misses it re-specializes or stays generic |
            | Deopt bails out of optimized machine code | A failed guard runs the generic instruction body (no machine code involved, unless the JIT is on) |

            The practical lesson is the same in both: code that sees **consistent types** at a
            given line runs faster.
            """
        ),
    ]


def _jit_cells() -> list[NotebookNode]:
    """3.2.9 The JIT."""
    return [
        md(
            """
            ### 3.2.9 The JIT

            *New in 3.13, experimental, off by default.* PEP 744 adds a second tier:

            1. **Hot code detection.** Backward jumps count iterations; a loop that runs often
               enough is handed to the tier-2 optimizer.
            2. **Micro-op traces.** The optimizer records a *trace* along the path the loop
               actually takes and translates each specialized instruction into smaller
               **micro-ops** (uops) such as `_GUARD_TYPE_VERSION` or `_BINARY_OP_ADD_INT`, then
               removes redundant guards.
            3. **Copy-and-patch code generation.** At **build** time, LLVM compiles every uop
               into a machine-code template ("stencil") with holes. At **run** time the JIT
               copies the templates for a trace into executable memory and patches the holes
               (constants, jump targets). No compiler runs inside your process.

            | Check | How |
            | --- | --- |
            | Was this interpreter built with the JIT? | `sys._jit.is_available()` (*New in 3.14*) |
            | Is it switched on? | `sys._jit.is_enabled()`; start Python with `PYTHON_JIT=1` |
            | Is the current frame running JIT code? | `sys._jit.is_active()` |
            | Build-time option | `./configure --enable-experimental-jit` (`=yes-off` builds it but leaves it off) |
            """
        ),
        code(
            """
            if hasattr(sys, "_jit"):
                print(f"{sys._jit.is_available()=}  (built with the JIT)")
                print(f"{sys._jit.is_enabled()=}  (switched on in this kernel)")
                print(f"{sys._jit.is_active()=}  (this cell is not running JIT code)")
                print(f"{os.environ.get('PYTHON_JIT')=}")
            else:
                print("Skipped: sys._jit needs Python 3.14+ (3.13: look for --enable-experimental-jit)")
            """
        ),
        md(
            """
            **Watching it work.** The kernel runs without the JIT, so the cell starts two child
            interpreters, with `PYTHON_JIT=0` and `PYTHON_JIT=1`, warms a hot loop in each and
            looks for **executors** (compiled traces) attached to its code object with
            `_opcode.get_executor`, a private testing hook. For the first executor it prints the
            number of micro-ops, the first few uop names and the size of the machine code. Only
            names are printed; uop operands contain addresses.
            """
        ),
        code(
            '''
            JIT_PROBE = textwrap.dedent(
                """
                import sys

                import _opcode

                def hot_loop(count):
                    total = 0
                    for number in range(count):
                        total += number * 2
                    return total

                for _ in range(50):
                    hot_loop(100_000)
                loop_code = hot_loop.__code__
                executors = []
                for offset in range(0, len(loop_code.co_code), 2):
                    try:
                        executor = _opcode.get_executor(loop_code, offset)
                    except Exception:  # no executor at this offset
                        continue
                    if executor is not None:
                        executors.append(executor)
                print("jit_enabled", sys._jit.is_enabled())
                print("executors", len(executors))
                if executors:
                    uop_names = [uop[0] for uop in executors[0]]
                    print("uop_count", len(uop_names))
                    print("first_uops", " ".join(uop_names[3:9]))
                    machine_code = executors[0].get_jit_code()
                    print("machine_code_bytes", len(machine_code) if machine_code else 0)
                """
            )

            if hasattr(sys, "_jit") and sys._jit.is_available():
                for jit_setting in ("0", "1"):
                    child_env = {**CHILD_ENV, "PYTHON_JIT": jit_setting}
                    completed = subprocess.run(
                        [sys.executable, "-c", JIT_PROBE],
                        capture_output=True, text=True, timeout=120, env=child_env,
                    )  # fmt: skip
                    print(f"--- PYTHON_JIT={jit_setting} ---")
                    print(completed.stdout.strip() or completed.stderr.strip()[-300:] or "(no output)")
            else:
                print("Skipped: this interpreter was built without the JIT")
            '''
        ),
        md(
            """
            > **Note:** on 3.15 the JIT gives modest, workload-dependent speedups (and can be
            > slower); it is a foundation for future releases. Measure before enabling it.
            > `_opcode.get_executor` and the uop names are internal and change between
            > releases.

            #### JS bridge: Ignition and TurboFan vs bytecode and the JIT

            | Stage | V8 | CPython 3.15 |
            | --- | --- | --- |
            | Bytecode | Ignition: register-based bytecode interpreter | Tier 1: stack-based bytecode interpreter |
            | Type feedback | Feedback vectors fed by inline caches | Inline caches in `co_code` (3.2.8) |
            | Cheap speed-up | Sparkplug: baseline compiler, bytecode → machine code without optimization | Specialized instructions (still interpreted) |
            | Optimizing tier | Maglev, then TurboFan (sea-of-nodes, speculative inlining) | Tier 2 uop traces + copy-and-patch JIT |
            | Deoptimization | Back to Ignition frames | Exit the trace back to tier 1 |
            | Default | Always on | JIT off by default; specialization always on |
            """
        ),
    ]


def _gil_cells() -> list[NotebookNode]:
    """3.2.10 The GIL and the eval breaker."""
    return [
        md(
            """
            ### 3.2.10 The GIL and the eval breaker

            In the default build, a thread must hold the **global interpreter lock** to run
            bytecode, so only one thread executes Python code at a time. The eval loop gives
            other threads a turn through the **eval breaker**: a word of flags that the loop
            checks cheaply at specific instructions (function entry `RESUME`, backward jumps,
            some calls). When a flag is set, the loop stops to handle it:

            | Flag | Who sets it | What the loop does |
            | --- | --- | --- |
            | GIL drop request | another thread waiting longer than `sys.getswitchinterval()` (5 ms) | releases the GIL, lets the other thread run, waits to re-acquire |
            | Signal pending | the C signal handler | runs the Python-level signal handler (`signal.signal`) |
            | Pending calls | C code (`Py_AddPendingCall`) | runs those callbacks |
            | Async exception | `PyThreadState_SetAsyncExc` | raises it in this thread |
            | GC scheduled | allocation counters (3.12+) | runs a cyclic GC collection |

            So **signal handlers and thread switches happen only between bytecode
            instructions**, never in the middle of one, and a long-running C call (a huge
            `sorted`, a regex) delays them.
            """
        ),
        code(
            '''
            def count_thread_switches(switch_interval: float, duration: float = 0.2) -> int:
                """Two CPU-bound threads; count how often the running thread changes."""
                state = {"owner": "", "switches": 0}
                deadline = time.perf_counter() + duration

                def spin(name: str) -> None:
                    while time.perf_counter() < deadline:
                        if state["owner"] != name:
                            state["owner"] = name
                            state["switches"] += 1

                original_interval = sys.getswitchinterval()
                sys.setswitchinterval(switch_interval)
                try:
                    threads = [threading.Thread(target=spin, args=(name,)) for name in ("A", "B")]
                    for thread in threads:
                        thread.start()
                    for thread in threads:
                        thread.join()
                finally:
                    sys.setswitchinterval(original_interval)
                return state["switches"]


            print(f"{sys.getswitchinterval()=}  [{interpreter_label()}]")
            for interval in (0.005, 0.0005):
                switches = count_thread_switches(interval)
                print(f"switch interval {interval * 1000:>4} ms -> {switches:>5} switches in 0.2 s")
            '''
        ),
        md(
            """
            Ten times shorter interval, roughly ten times more switches: the GIL handoffs
            are driven by the eval breaker. (On a free-threaded build both threads run at
            once, so the count is noisy and much higher.)

            **Signals arrive between instructions.** A timer thread sends `SIGUSR1` to this
            process while the main thread spins in a pure-Python loop. The C-level handler
            only sets a flag; the Python handler runs at the next eval-breaker check, in the
            main thread. (Unix only; the old handler is restored.)
            """
        ),
        code(
            '''
            if hasattr(signal, "SIGUSR1") and threading.current_thread() is threading.main_thread():
                progress = {"iterations": 0, "handled_at": None}

                def on_user_signal(signal_number: int, frame: types.FrameType | None) -> None:
                    """Python-level handler: runs between two bytecode instructions."""
                    progress["handled_at"] = progress["iterations"]

                previous_handler = signal.signal(signal.SIGUSR1, on_user_signal)
                try:
                    threading.Timer(0.05, os.kill, (os.getpid(), signal.SIGUSR1)).start()
                    give_up_at = time.perf_counter() + 2
                    while progress["handled_at"] is None and time.perf_counter() < give_up_at:
                        progress["iterations"] += 1
                finally:
                    signal.signal(signal.SIGUSR1, previous_handler)
                handled = progress["handled_at"] is not None
                iterations = progress["iterations"]
                print(f"handler ran in the main thread: {handled}, after {iterations:,} loop iterations")
            else:
                print("Skipped: needs SIGUSR1 (Unix) and the main thread")
            '''
        ),
        md(
            """
            **The free-threaded design (overview).** Without a GIL (3.1.5) the eval breaker
            still exists, but for different jobs: signals, pending calls and **stop-the-world**
            pauses, where all threads park at an eval-breaker check so the GC (or a few other
            operations) can run safely. Thread safety moves into the objects themselves
            (per-object locks, biased reference counting, mimalloc), and the specializing
            interpreter uses thread-safe variants. Phase 5 measures what this means for
            threads, processes and subinterpreters.
            """
        ),
    ]


def _compile_exec_eval_cells() -> list[NotebookNode]:
    """3.2.11 compile, exec, eval."""
    return [
        md(
            """
            ### 3.2.11 `compile`, `exec`, `eval`

            | Function | Input | Returns |
            | --- | --- | --- |
            | `compile(source, filename, mode)` | text or an AST | a code object |
            | `eval(source_or_code, globals=None, locals=None)` | **one expression** | its value |
            | `exec(source_or_code, globals=None, locals=None)` | any statements | `None` |

            | `compile` mode | Accepts | Like |
            | --- | --- | --- |
            | `"exec"` | a module: any statements | running a file |
            | `"eval"` | a single expression | `eval` |
            | `"single"` | one interactive statement; expression values are **printed** | the REPL |
            """
        ),
        code(
            """
            expression_code = compile("price * quantity", "<pricing>", "eval")
            module_code = compile(
                "subtotal = price * quantity\\ntotal = round(subtotal * 1.18, 2)", "<pricing>", "exec"
            )
            single_code = compile("price * quantity", "<repl>", "single")

            namespace = {"price": 250.0, "quantity": 3}
            print(f"{eval(expression_code, namespace)=}")
            print(f"{exec(module_code, namespace)=}  -> namespace['total']={namespace['total']}")
            repl_output = io.StringIO()
            jupyter_displayhook = sys.displayhook
            sys.displayhook = sys.__displayhook__  # the plain REPL hook (Jupyter installs its own)
            try:
                with contextlib.redirect_stdout(repl_output):
                    exec(single_code, namespace)
            finally:
                sys.displayhook = jupyter_displayhook
            print(f"'single' mode printed: {repl_output.getvalue().strip()!r}")
            print(f"{raised_message(lambda: compile('x = 1', '<e>', 'eval'))=}")
            """
        ),
        md(
            """
            **Namespaces.** `globals` is the dict used for global lookups and stores; if it has
            no `__builtins__` key, Python inserts one. With a separate `locals` mapping,
            top-level assignments go to `locals`, as in a class body.
            """
        ),
        code(
            """
            sandbox_globals: dict[str, object] = {"rate": 0.18}
            sandbox_locals: dict[str, object] = {}
            exec("tax = 100 * rate\\nlabel = f'{tax:.2f}'", sandbox_globals, sandbox_locals)
            print(f"{sorted(sandbox_locals)=}")
            print(f"{sorted(sandbox_globals)=}  (__builtins__ was added)")
            print(f"{type(sandbox_globals['__builtins__']).__name__=}")
            """
        ),
        md(
            """
            > **Warning:** `eval` or `exec` on user input is **remote code execution**. Any
            > expression can import modules and call them. Removing `__builtins__` does not help:
            > every object leads back to `object.__subclasses__()`, which reaches dangerous
            > classes. The cell runs two "inputs" that a calculator endpoint might receive; the
            > escape list is only measured, never used.
            """
        ),
        code(
            """
            user_input = "__import__('platform').system()"
            print(f"eval of user input ran an import: {eval(user_input)!r}")  # deliberate: never do this

            escape_input = "().__class__.__base__.__subclasses__()"
            reachable_classes = eval(escape_input, {"__builtins__": {}})  # deliberate: never do this
            print(f"with __builtins__ removed, still reachable classes: {len(reachable_classes) > 100}")
            """
        ),
        md(
            """
            **`ast.literal_eval`** accepts only literals (numbers, strings, bytes, tuples,
            lists, dicts, sets, `True`/`False`/`None`, and `+`/`-` on numbers). Use it to read
            Python-literal data; anything else raises `ValueError`. For arithmetic, write an
            evaluator that walks the AST (Lab 3.2, exercise 5).
            """
        ),
        code(
            """
            catalog_text = '{"sku": "TEA-01", "sizes": [250, 500], "active": True}'
            print(f"{ast.literal_eval(catalog_text)=}")
            for unsafe_text in ("__import__('os')", "2 ** 1000", "price * 2"):
                outcome = raised_message(functools.partial(ast.literal_eval, unsafe_text))
                print(f"{unsafe_text!r:<20} {outcome[:48]}...")
            """
        ),
    ]


def _ast_transform_cells() -> list[NotebookNode]:
    """3.2.12 AST transformation."""
    return [
        md(
            """
            ### 3.2.12 AST transformation

            | Class / function | Use |
            | --- | --- |
            | `ast.NodeVisitor` | Walk a tree; define `visit_<NodeType>` methods; call `self.generic_visit(node)` to continue into children |
            | `ast.NodeTransformer` | Like a visitor, but the return value **replaces** the node (`None` deletes it) |
            | `ast.fix_missing_locations(tree)` | Fill in `lineno` / `col_offset` for nodes you created, so `compile` accepts the tree |
            | `ast.copy_location(new, old)` | Give a new node the old node's position |

            **`NodeVisitor`:** collect which functions a piece of code calls.
            """
        ),
        code(
            '''
            class CallCollector(ast.NodeVisitor):
                """Count calls by the called name."""

                def __init__(self) -> None:
                    self.calls: Counter[str] = Counter()

                def visit_Call(self, node: ast.Call) -> None:
                    self.calls[ast.unparse(node.func)] += 1
                    self.generic_visit(node)  # calls inside the arguments too


            collector = CallCollector()
            collector.visit(pricing_tree)
            print(f"{dict(collector.calls)=}")
            '''
        ),
        md(
            """
            **`NodeTransformer`:** a tiny version of what pytest does. It rewrites
            `assert left <op> right` into an `if` that raises an `AssertionError` showing both
            values. New nodes have no positions, so `compile` rejects the tree until
            `ast.fix_missing_locations` fills them in. (This simple version evaluates each
            side twice; pytest stores them in temporaries.)
            """
        ),
        code(
            '''
            OPERATOR_TEXT = {
                ast.Eq: "==",
                ast.NotEq: "!=",
                ast.Lt: "<",
                ast.LtE: "<=",
                ast.Gt: ">",
                ast.GtE: ">=",
            }


            class AssertExplainer(ast.NodeTransformer):
                """Rewrite `assert a <op> b` so the failure message shows both values."""

                def visit_Assert(self, node: ast.Assert) -> ast.AST:
                    test = node.test
                    if not (
                        isinstance(test, ast.Compare)
                        and len(test.ops) == 1
                        and type(test.ops[0]) in OPERATOR_TEXT
                    ):
                        return node
                    message = ast.JoinedStr(
                        values=[
                            ast.Constant("assert "),
                            ast.FormattedValue(test.left, conversion=ord("r")),
                            ast.Constant(f" {OPERATOR_TEXT[type(test.ops[0])]} "),
                            ast.FormattedValue(test.comparators[0], conversion=ord("r")),
                        ]
                    )
                    error_call = ast.Call(
                        func=ast.Name("AssertionError", ast.Load()), args=[message], keywords=[]
                    )
                    replacement = ast.If(
                        test=ast.UnaryOp(ast.Not(), test), body=[ast.Raise(exc=error_call)], orelse=[]
                    )
                    return ast.copy_location(replacement, node)
            '''
        ),
        md(
            "Apply it to a small test, compile before and after `fix_missing_locations`, and run it:"
        ),
        code(
            '''
            test_source = textwrap.dedent(
                """
                expected_total = 590.0
                actual_total = round(2 * 250 * 1.18, 2) + 0.5
                assert actual_total == expected_total
                """
            )
            rewritten_tree = AssertExplainer().visit(ast.parse(test_source))
            print(ast.unparse(rewritten_tree).splitlines()[-2:])
            print(f"compile before fix: {raised_error_name(lambda: compile(rewritten_tree, '<test>', 'exec'))}")
            ast.fix_missing_locations(rewritten_tree)
            print(
                f"run after fix: {raised_message(lambda: exec(compile(rewritten_tree, '<test>', 'exec'), {}))}"
            )
            '''
        ),
        md(
            """
            **How pytest rewrites asserts.** pytest installs an import hook
            (`_pytest.assertion.rewrite.AssertionRewritingHook`) for test modules and
            `conftest.py`. When one is imported, the hook parses it, rewrites every `assert`
            into code that saves each sub-expression in a temporary and builds a detailed
            message, compiles the new tree and caches it as a `.pyc` with a pytest-specific
            tag. That is why a plain `assert a == b` in a test prints both values and a diff.
            pytest is a Phase 4 dependency; the cell checks for it.
            """
        ),
        code(
            """
            if importlib.util.find_spec("pytest") is None:
                print("Skipped: pytest is not installed yet (added in Phase 4: uv add --dev pytest)")
            else:
                from _pytest.assertion import rewrite

                print(f"{rewrite.AssertionRewritingHook.__name__} is in {rewrite.__name__}")
            """
        ),
    ]


def _pyc_cells() -> list[NotebookNode]:
    """3.2.13 .pyc files."""
    return [
        md(
            """
            ### 3.2.13 `.pyc` files

            Importing a module compiles it, then caches the code object in
            `__pycache__/<module>.<cache_tag>.pyc` (for example `pricing.cpython-315.pyc`), so
            the next import can skip compilation. A `.pyc` is a 16-byte header plus the module's
            code object serialized with `marshal`:

            | Bytes | Field | Meaning |
            | --- | --- | --- |
            | 0–3 | magic number | changes whenever the bytecode format changes; must equal `importlib.util.MAGIC_NUMBER` |
            | 4–7 | flags (little-endian) | `0` = timestamp-based; bit 0 = hash-based; bit 1 = check the source hash |
            | 8–15 | source mtime + size (timestamp mode) **or** 8-byte SipHash of the source (hash modes) | how the cache is validated |
            | 16– | `marshal.dumps(code_object)` | the module's code object |

            The cell compiles a module with `py_compile`, decodes the header by hand, then
            loads and runs the code object with `marshal`.
            """
        ),
        code(
            """
            PRICING_SOURCE = (
                "GST_RATE = 0.18\\n\\ndef with_gst(amount):\\n    return round(amount * (1 + GST_RATE), 2)\\n"
            )

            with tempfile.TemporaryDirectory() as folder:
                source_path = Path(folder) / "pricing.py"
                source_path.write_text(PRICING_SOURCE)
                pyc_path = Path(py_compile.compile(str(source_path), doraise=True))
                pyc_bytes = pyc_path.read_bytes()
                source_stat = source_path.stat()

            print(f"cache file: {pyc_path.parent.name}/{pyc_path.name}  ({len(pyc_bytes)} bytes)")
            magic_ok = pyc_bytes[:4] == importlib.util.MAGIC_NUMBER
            print(f"magic matches this interpreter: {magic_ok}  ({pyc_bytes[:4].hex(' ')})")
            flags = int.from_bytes(pyc_bytes[4:8], "little")
            stored_mtime, stored_size = struct.unpack("<II", pyc_bytes[8:16])
            mtime_ok = stored_mtime == int(source_stat.st_mtime)
            print(f"{flags=}  mtime matches: {mtime_ok}  size matches: {stored_size == source_stat.st_size}")
            module_code = marshal.loads(pyc_bytes[16:])
            pricing_namespace: dict[str, object] = {}
            exec(module_code, pricing_namespace)
            print(f"{type(module_code).__name__}  -> with_gst(100) = {pricing_namespace['with_gst'](100)}")
            print(f"{sys.implementation.cache_tag=}")
            """
        ),
        md(
            """
            **Invalidation modes** (PEP 552, 3.7). Timestamps break reproducible builds and
            some deployment tools, so a `.pyc` can store a hash of the source instead:

            | `py_compile.PycInvalidationMode` | Flags | On import |
            | --- | --- | --- |
            | `TIMESTAMP` (default) | `0` | Recompile if the source mtime or size changed |
            | `CHECKED_HASH` | `0b11` | Hash the source and compare (slower import, always correct) |
            | `UNCHECKED_HASH` | `0b01` | Trust the `.pyc` without looking at the source (for read-only installs) |
            """
        ),
        code(
            """
            with tempfile.TemporaryDirectory() as folder:
                source_path = Path(folder) / "pricing.py"
                source_path.write_text(PRICING_SOURCE)
                source_hash = importlib.util.source_hash(source_path.read_bytes())
                for mode in py_compile.PycInvalidationMode:
                    target = Path(folder) / f"{mode.name.lower()}.pyc"
                    header = Path(
                        py_compile.compile(str(source_path), cfile=str(target), invalidation_mode=mode)
                    ).read_bytes()[:16]
                    flags = int.from_bytes(header[4:8], "little")
                    stores_hash = header[8:16] == source_hash
                    print(f"{mode.name:<15} flags={flags:#04b}  bytes 8-15 hold the source hash: {stores_hash}")
            """
        ),
        md(
            """
            **`compileall`** compiles a whole tree ahead of time (used by installers and in
            Docker images so the first import is fast). `python -m compileall -q src/` is the
            command-line form.
            """
        ),
        code(
            """
            with tempfile.TemporaryDirectory() as folder:
                package = Path(folder) / "shop"
                package.mkdir()
                (package / "__init__.py").write_text("")
                (package / "cart.py").write_text("ITEMS = []\\n")
                (package / "pricing.py").write_text(PRICING_SOURCE)
                succeeded = compileall.compile_dir(package, quiet=1)
                cached = sorted(path.name for path in (package / "__pycache__").iterdir())
            print(f"{succeeded=}")
            print(cached)
            """
        ),
        md(
            """
            **`marshal`** is the serializer behind `.pyc` files. It handles code objects and
            core types, its format can change between versions, and it is **not secure**
            against crafted data. For your own data use `json` or `pickle` (Phase 4).
            """
        ),
        code(
            """
            payload = marshal.dumps({"sku": "TEA-01", "sizes": (250, 500), "code": with_tax.__code__})
            restored = marshal.loads(payload)
            print(f"{len(payload)=}  {restored['sku']=}  {restored['sizes']=}")
            print(f"{restored['code'] == with_tax.__code__=}  (a code object round-trips)")
            print(f"{raised_message(lambda: marshal.dumps(CartLine(1, 1)))=}")
            """
        ),
    ]


def _implementations_cells() -> list[NotebookNode]:
    """3.2.14 Other implementations."""
    return [
        md(
            """
            ### 3.2.14 Other implementations

            Everything in this unit describes **CPython**. Other implementations run the
            same language very differently:

            | Implementation | How it runs Python | Memory | C extensions |
            | --- | --- | --- | --- |
            | **CPython** | Bytecode interpreter + specialization (+ experimental JIT) | Refcounting + cycle GC | Native (the C API is CPython's) |
            | **PyPy** | Written in RPython; a **tracing JIT** compiles hot loops to machine code | Tracing, moving GC: no refcounts, finalizers run late, `id()` is synthetic | Through an emulation layer (cpyext), slower |
            | **GraalPy** | On GraalVM: Truffle AST interpreter + Graal JIT | JVM garbage collector | Partial support; can call Java |
            | **Cython** (a compiler, not an interpreter) | Translates Python (plus optional C types) into C, compiled into an extension module | CPython's | Produces them |
            | MicroPython | Small bytecode VM for microcontrollers | Simple GC | Its own native modules |

            `sys.implementation` and `platform.python_implementation()` tell you which one is
            running; code that depends on refcount timing, `sys.getrefcount` or `dis` output
            is CPython-specific. The cell checks for PyPy and GraalPy executables.
            """
        ),
        code(
            """
            print(f"{sys.implementation.name=}  {platform.python_implementation()=}")
            for executable in ("pypy3", "graalpy"):
                found = shutil.which(executable)
                print(f"{executable:<8} {'installed' if found else 'not installed (skipped)'}")
            """
        ),
        md(
            """
            **A Cython-compiled module, from the inside.** pyzmq (Jupyter's messaging library,
            installed with the kernel) is compiled with Cython. Its functions are not Python
            function objects; they carry a placeholder code object for introspection, with
            no real bytecode, because the body is machine code compiled from C.
            """
        ),
        code(
            """
            cython_module_name = "zmq.backend.cython._zmq"
            if importlib.util.find_spec("zmq") is None or importlib.util.find_spec(cython_module_name) is None:
                print("Skipped: pyzmq's Cython backend is not installed")
            else:
                cython_module = importlib.import_module(cython_module_name)
                cython_function = cython_module.has
                print(f"module file: {Path(cython_module.__file__).name}")
                print(f"{type(cython_function).__name__=}")
                print(f"{inspect.isfunction(cython_function)=}  (not a Python function object)")
                placeholder = getattr(cython_function, "__code__", None)
                if placeholder is not None:
                    real_instructions = [
                        name
                        for name in (i.opname for i in dis.get_instructions(placeholder))
                        if name != "CACHE"
                    ]
                    print(f"bytecode instructions besides CACHE placeholders: {real_instructions}")
            """
        ),
    ]


def _predict_cells() -> list[NotebookNode]:
    """A predict-the-output question for Unit 3.2."""
    return predict_cells(
        """
        import dis

        def tax_tables():
            seconds = 24 * 60 * 60
            return seconds, [rate * 2 for rate in (5, 12, 18)]

        print(86400 in tax_tables.__code__.co_consts)
        print([c.co_name for c in tax_tables.__code__.co_consts if hasattr(c, "co_name")])
        """,
        """
        ```text
        True
        []
        ```

        `24 * 60 * 60` is folded to `86400` at compile time, so the constant is stored in
        `co_consts`. Since 3.12 (PEP 709) the list comprehension is inlined into the function,
        so there is no nested `<listcomp>` code object. On 3.11 the second line printed
        `['<listcomp>']`.
        """,
        '''
        def tax_tables() -> tuple[int, list[int]]:
            """A folded constant and an inlined comprehension."""
            seconds = 24 * 60 * 60
            return seconds, [rate * 2 for rate in (5, 12, 18)]


        print(86400 in tax_tables.__code__.co_consts)
        print([c.co_name for c in tax_tables.__code__.co_consts if hasattr(c, "co_name")])
        ''',
    )


def _lab_bytecode_cells() -> list[NotebookNode]:
    """Lab 3.2 exercises 1–2."""
    return [
        md(
            """
            ### Lab 3.2

            Seven exercises. For each, complete the stub, then run the check cell. Until then
            the checks print FAIL; that is expected. Checks compare your answers with what the
            **running** interpreter's `dis` reports, so they work on any version.

            #### Exercise 1 — annotate a function's `dis` output with stack states

            Run `show_dis(taxi_fare)`, then return one `(opname, stack_after)` pair per
            instruction, **skipping `RESUME`**. `stack_after` lists what is on the value stack
            after the instruction, bottom to top, as short strings such as
            `"distance_km * rate_per_km"`. After `RETURN_VALUE` the stack is empty.
            """
        ),
        code(
            '''
            def taxi_fare(base_fare: float, distance_km: float, rate_per_km: float, discount: float) -> float:
                """The function to annotate (given)."""
                return base_fare + distance_km * rate_per_km - discount


            def annotate_stack() -> list[tuple[str, list[str]]]:
                """(opname, stack after) for each instruction of taxi_fare except RESUME."""
                raise NotImplementedError("Lab 3.2: annotate taxi_fare")
            '''
        ),
        md(
            """
            Run the checks. They compare the opnames with `dis.get_instructions(taxi_fare)` and
            the stack **depths** with `dis.stack_effect`; the wording of your stack entries is
            up to you.
            """
        ),
        code(
            '''
            def live_instructions(function: Callable[..., object]) -> list[dis.Instruction]:
                """Instructions without RESUME."""
                return [ins for ins in dis.get_instructions(function) if ins.opname != "RESUME"]


            def expected_depths(function: Callable[..., object]) -> list[int]:
                """Stack depth after each instruction, from dis.stack_effect."""
                depth, depths = 0, []
                for instruction in live_instructions(function):
                    if instruction.opname == "RETURN_VALUE":
                        depth -= 1
                    elif instruction.arg is None:
                        depth += dis.stack_effect(instruction.opcode)
                    else:
                        depth += dis.stack_effect(instruction.opcode, instruction.arg)
                    depths.append(depth)
                return depths


            run_checks(
                [
                    (
                        "opnames in order",
                        lambda: [name for name, _ in annotate_stack()],
                        [ins.opname for ins in live_instructions(taxi_fare)],
                    ),
                    (
                        "stack depths",
                        lambda: [len(stack) for _, stack in annotate_stack()],
                        expected_depths(taxi_fare),
                    ),
                    (
                        "entries are strings",
                        lambda: all(isinstance(item, str) for _, stack in annotate_stack() for item in stack),
                        True,
                    ),
                    ("empty after RETURN_VALUE", lambda: annotate_stack()[-1], ("RETURN_VALUE", [])),
                ]
            )
            '''
        ),
        md(
            """
            #### Exercise 2 — `count_opcodes(func)`

            Return a `collections.Counter` mapping each opname to how often it appears in
            `func`'s bytecode **and in every nested code object** (inner functions, lambdas,
            generator expressions, found recursively in `co_consts`). Use the non-adaptive
            instructions from `dis.get_instructions(code_object)`; `CACHE` entries are not
            instructions and must not be counted.

            > **Note:** since 3.14, annotations are evaluated lazily: a function with type
            > hints carries a hidden `__annotate__` code object, which counts as nested code
            > too.
            """
        ),
        code(
            '''
            def count_opcodes(func: Callable[..., object]) -> Counter[str]:
                """Opname counts for func and all nested code objects."""
                raise NotImplementedError("Lab 3.2: implement count_opcodes")
            '''
        ),
        md("Run the checks."),
        code(
            '''
            def three_calls(values: list[int]) -> int:
                print(values)
                print(values)
                return len(values)


            def outer_with_inner() -> Callable[[], int]:
                def inner() -> int:
                    return 1

                return inner


            def with_generator(values: list[int]) -> int:
                return sum(value * 2 for value in values)


            def total_instructions(code_object: types.CodeType) -> int:
                """Instruction count of a code object and its nested code objects (check helper)."""
                nested = [c for c in code_object.co_consts if isinstance(c, types.CodeType)]
                return len(list(dis.get_instructions(code_object))) + sum(total_instructions(c) for c in nested)


            run_checks(
                [
                    ("returns a Counter", lambda: type(count_opcodes(three_calls)).__name__, "Counter"),
                    (
                        "flat total",
                        lambda: count_opcodes(three_calls).total(),
                        len(list(dis.get_instructions(three_calls))),
                    ),
                    ("three CALLs", lambda: count_opcodes(three_calls)["CALL"], 3),
                    (
                        "inner function counted",
                        lambda: (
                            count_opcodes(outer_with_inner)["RETURN_VALUE"]
                            > opnames(outer_with_inner).count("RETURN_VALUE")
                        ),
                        True,
                    ),
                    (
                        "generator expression counted",
                        lambda: count_opcodes(with_generator).total(),
                        total_instructions(with_generator.__code__),
                    ),
                    ("no CACHE entries", lambda: "CACHE" in count_opcodes(with_generator), False),
                ]
            )
            '''
        ),
    ]


def _lab_ast_cells() -> list[NotebookNode]:
    """Lab 3.2 exercises 3–5."""
    return [
        md(
            """
            #### Exercise 3 — an AST lint rule for mutable defaults and bare `except`

            `lint_source(source)` parses `source` and returns a sorted list of
            `(line_number, code)` tuples:

            - `"B006"` for every **mutable default** of a `def` or `async def`, positional or
              keyword-only: a list, dict or set display, a list/dict/set comprehension, or a
              call to `list()`, `dict()` or `set()`. Report the line of the default value.
            - `"E722"` for every bare `except:` (an `ExceptHandler` with no type), reported at
              the `except` line.

            Lambdas and `None` defaults are fine.
            """
        ),
        code(
            '''
            def lint_source(source: str) -> list[tuple[int, str]]:
                """(line, code) findings for mutable defaults (B006) and bare except (E722)."""
                raise NotImplementedError("Lab 3.2: implement lint_source")
            '''
        ),
        md("Run the checks."),
        code(
            '''
            LINT_SAMPLE = textwrap.dedent(
                """
                def add_item(item, basket=[]):
                    basket.append(item)
                    return basket

                async def fetch(url, *, headers={}, retries=3, tags=set()):
                    try:
                        return url
                    except:
                        return None

                def fine(value=None, labels=(), factor=lambda x: x):
                    try:
                        return value
                    except ValueError:
                        return None

                def comprehension_default(cache={key: 0 for key in "ab"}):
                    return cache
                """
            )

            run_checks(
                [
                    (
                        "sample findings",
                        lambda: lint_source(LINT_SAMPLE),
                        [(2, "B006"), (6, "B006"), (6, "B006"), (9, "E722"), (18, "B006")],
                    ),
                    ("clean code", lambda: lint_source("def f(x=None):\\n    return x\\n"), []),
                    ("list() call default", lambda: lint_source("def f(x=list()):\\n    pass\\n"), [(1, "B006")]),
                    (
                        "bare except in a method",
                        lambda: lint_source(
                            "class A:\\n    def m(self):\\n        try:\\n            pass\\n"
                            "        except:\\n            pass\\n"
                        ),
                        [(5, "E722")],
                    ),
                ]
            )
            '''
        ),
        md(
            """
            #### Exercise 4 — a `print` → `logger.info` transformer

            Write `PrintToLogger(ast.NodeTransformer)` and `rewrite_prints(source)`, which
            parses, transforms, fixes locations and returns `ast.unparse(tree)`:

            - `print(a, b, ...)` with only positional, non-starred arguments becomes
              `logger.info('%s %s ...', a, b, ...)` (one `%s` per argument, joined by spaces).
            - `print()` becomes `logger.info('')`.
            - Calls with keyword arguments (`sep=`, `end=`, `file=`) or starred arguments are
              left unchanged.
            - Other calls are untouched; prints nested in functions and arguments are
              rewritten too.
            """
        ),
        code(
            '''
            class PrintToLogger(ast.NodeTransformer):
                """Replace print(...) calls with logger.info(...)."""


            def rewrite_prints(source: str) -> str:
                """Source with eligible print calls turned into logger.info calls."""
                raise NotImplementedError("Lab 3.2: implement rewrite_prints")
            '''
        ),
        md("Run the checks."),
        code(
            """
            run_checks(
                [
                    ("one argument", lambda: rewrite_prints("print(total)"), "logger.info('%s', total)"),
                    (
                        "two arguments",
                        lambda: rewrite_prints("print('total', total)"),
                        "logger.info('%s %s', 'total', total)",
                    ),
                    ("no arguments", lambda: rewrite_prints("print()"), "logger.info('')"),
                    (
                        "keywords untouched",
                        lambda: rewrite_prints("print(x, file=sys.stderr)"),
                        "print(x, file=sys.stderr)",
                    ),
                    ("starred untouched", lambda: rewrite_prints("print(*rows)"), "print(*rows)"),
                    ("other calls untouched", lambda: rewrite_prints("pprint(data)"), "pprint(data)"),
                    (
                        "nested in a function",
                        lambda: rewrite_prints("def report(n):\\n    print('rows', n)\\n    return n"),
                        "def report(n):\\n    logger.info('%s %s', 'rows', n)\\n    return n",
                    ),
                    (
                        "result compiles",
                        lambda: bool(compile(rewrite_prints("print(1, 2)"), "<t>", "exec")),
                        True,
                    ),
                ]
            )
            """
        ),
        md(
            """
            #### Exercise 5 — a safe arithmetic evaluator

            `safe_eval(expression, variables=None)` evaluates arithmetic **without** `eval`,
            by walking the AST from `ast.parse(expression, mode="eval")`:

            - Numbers: `int` and `float` constants only (`bool`, strings and others raise
              `ValueError(f"unsupported constant: {type(value).__name__}")`).
            - Names: looked up in `variables`; unknown names raise
              `ValueError(f"unknown name: {name}")`.
            - Operators: binary `+ - * / // % **` and unary `+ -`. For `**`, an exponent whose
              absolute value is over 100 raises `ValueError("exponent too large")`.
            - Any other node raises `ValueError(f"unsupported expression: {type(node).__name__}")`.
            - Text that does not parse raises `ValueError("invalid expression")`.
            - Arithmetic errors such as `ZeroDivisionError` propagate unchanged.
            """
        ),
        code(
            '''
            def safe_eval(expression: str, variables: dict[str, float] | None = None) -> float:
                """Evaluate an arithmetic expression safely."""
                raise NotImplementedError("Lab 3.2: implement safe_eval")
            '''
        ),
        md("Run the checks."),
        code(
            """
            prices = {"price": 200.0, "rate": 0.25, "quantity": 3}
            run_checks(
                [
                    ("precedence", lambda: safe_eval("2 + 3 * 4"), 14),
                    ("parentheses", lambda: safe_eval("(2 + 3) * 4"), 20),
                    ("unary minus and power", lambda: safe_eval("-x ** 2", {"x": 3}), -9),
                    ("variables", lambda: safe_eval("price * quantity * (1 + rate)", prices), 750.0),
                    ("floor division and modulo", lambda: safe_eval("17 // 5 + 17 % 5"), 5),
                    (
                        "function call refused",
                        lambda: raised_message(lambda: safe_eval("__import__('os')")),
                        "ValueError: unsupported expression: Call",
                    ),
                    (
                        "attribute refused",
                        lambda: raised_message(lambda: safe_eval("price.real", prices)),
                        "ValueError: unsupported expression: Attribute",
                    ),
                    (
                        "huge exponent refused",
                        lambda: raised_message(lambda: safe_eval("2 ** 1000")),
                        "ValueError: exponent too large",
                    ),
                    (
                        "string refused",
                        lambda: raised_message(lambda: safe_eval("'a' * 3")),
                        "ValueError: unsupported constant: str",
                    ),
                    (
                        "bool refused",
                        lambda: raised_message(lambda: safe_eval("True + 1")),
                        "ValueError: unsupported constant: bool",
                    ),
                    (
                        "unknown name",
                        lambda: raised_message(lambda: safe_eval("tax * 2")),
                        "ValueError: unknown name: tax",
                    ),
                    (
                        "invalid syntax",
                        lambda: raised_message(lambda: safe_eval("2 +")),
                        "ValueError: invalid expression",
                    ),
                    (
                        "division by zero propagates",
                        lambda: raised_error_name(lambda: safe_eval("1 / 0")),
                        "ZeroDivisionError",
                    ),
                ]
            )
            """
        ),
    ]


def _lab_runtime_cells() -> list[NotebookNode]:
    """Lab 3.2 exercises 6–7."""
    return [
        md(
            """
            #### Exercise 6 — observe specialization and deoptimization

            `binary_op_forms(func, argument_sets, *, warmups=1000)`: for each tuple in
            `argument_sets`, call `func(*arguments)` `warmups` times, then record the
            **adaptive** opname of the first instruction whose opname starts with
            `"BINARY_OP"` (`dis.get_instructions(func, adaptive=True)`). Return the list of
            recorded names.

            Feeding ints, then floats, then strings shows the instruction specializing,
            deoptimizing when its guard fails, and re-specializing for the new type.
            """
        ),
        code(
            '''
            def binary_op_forms(
                func: Callable[..., object], argument_sets: list[tuple[object, ...]], *, warmups: int = 1000
            ) -> list[str]:
                """The adaptive BINARY_OP form after warming func with each argument set in turn."""
                raise NotImplementedError("Lab 3.2: implement binary_op_forms")
            '''
        ),
        md(
            """
            Run the checks. Specialization state lives in the **code object**, and every
            function created by the same nested `def` shares one code object. So
            `make_adder()` compiles a brand-new code object with `exec` each time; otherwise
            the "cold" function would already be warm from an earlier check. Exact names are
            CPython internals; the checks only look for the type in the name.
            """
        ),
        code(
            '''
            def make_adder() -> Callable[[object, object], object]:
                """A never-called function with its own, freshly compiled code object."""
                namespace: dict[str, object] = {}
                exec("def add(left, right):\\n    return left + right", namespace)
                return namespace["add"]


            def type_shifts() -> list[str]:
                return binary_op_forms(make_adder(), [(1, 2), (1.5, 2.5), ("a", "b")])


            try:
                print(f"[{interpreter_label()}] {type_shifts()=}")
            except NotImplementedError:
                print("binary_op_forms is not implemented yet")
            run_checks(
                [
                    (
                        "cold function is generic",
                        lambda: binary_op_forms(make_adder(), [(1, 2)], warmups=0),
                        ["BINARY_OP"],
                    ),
                    ("ints specialize", lambda: "INT" in type_shifts()[0], True),
                    ("then floats", lambda: "FLOAT" in type_shifts()[1], True),
                    ("then strings", lambda: "UNICODE" in type_shifts()[2], True),
                    (
                        "always a BINARY_OP form",
                        lambda: all(name.startswith("BINARY_OP") for name in type_shifts()),
                        True,
                    ),
                ]
            )
            '''
        ),
        md(
            """
            #### Exercise 7 — a code-quality scanner over a folder

            `scan_folder(folder)` walks `folder` recursively and runs `lint_source`
            (exercise 3) on every `.py` file:

            - Skip directories named `__pycache__` or starting with `.` (such as `.venv`).
            - Keys are paths **relative to `folder`**, in POSIX form (`"pkg/models.py"`).
            - A file that does not parse gets `[(error.lineno, "E999")]`.
            - Files with no findings are left out; return the dict with keys sorted.
            """
        ),
        code(
            '''
            def scan_folder(folder: Path) -> dict[str, list[tuple[int, str]]]:
                """Lint findings for every Python file under folder."""
                raise NotImplementedError("Lab 3.2: implement scan_folder")
            '''
        ),
        md("Run the checks. They build a small project in a temporary folder."),
        code(
            '''
            def scan_sample_project() -> dict[str, list[tuple[int, str]]]:
                """Write a sample tree, scan it, delete it."""
                files = {
                    "app.py": "def handler(event, seen=[]):\\n    return seen\\n",
                    "pkg/__init__.py": "",
                    "pkg/models.py": "def load():\\n    try:\\n        pass\\n    except:\\n        pass\\n",
                    "pkg/clean.py": "def ok(value=None):\\n    return value\\n",
                    "broken.py": "def broken(:\\n    pass\\n",
                    ".venv/lib/site.py": "def bad(x=[]):\\n    pass\\n",
                    "pkg/__pycache__/junk.py": "def bad(x={}):\\n    pass\\n",
                    "notes.txt": "def not_python(x=[]): pass\\n",
                }
                with tempfile.TemporaryDirectory() as folder:
                    for relative, text in files.items():
                        path = Path(folder) / relative
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_text(text)
                    return scan_folder(Path(folder))


            run_checks(
                [
                    (
                        "findings per file",
                        scan_sample_project,
                        {"app.py": [(1, "B006")], "broken.py": [(1, "E999")], "pkg/models.py": [(4, "E722")]},
                    ),
                    (
                        "keys sorted",
                        lambda: list(scan_sample_project()),
                        ["app.py", "broken.py", "pkg/models.py"],
                    ),
                ]
            )
            '''
        ),
    ]


def _recap_cells() -> list[NotebookNode]:
    """Recap for Unit 3.2."""
    return [
        md(
            """
            ### Recap — Unit 3.2

            | Concept | One-line takeaway | JS equivalent |
            | --- | --- | --- |
            | Architecture | `Parser/` → `Python/compile.c` → `Python/ceval.c`; types in `Objects/` | V8 parser → Ignition → TurboFan |
            | Tokens and AST | `tokenize`, `ast.parse`, `ast.dump`, `ast.unparse` | Acorn / Babel ASTs |
            | Code objects | Immutable bytecode + constants + names + flags + exception table; `replace()` | `SharedFunctionInfo` + bytecode array |
            | Function objects | Code + globals + defaults + closure; `types.FunctionType` builds one | Closure objects |
            | Reading `dis` | Columns, a value stack, `*_FAST` / `*_DEREF` / `*_GLOBAL` / `*_ATTR`, `CALL`, jumps, `FOR_ITER` | `node --print-bytecode` |
            | Compiler optimizations | Constant folding, dead code, constant containers, inlined comprehensions (3.12) | Parser-level folding |
            | Eval loop | Frames with an instruction pointer; Python-to-Python calls inlined (3.11) | Ignition dispatch loop |
            | Specialization | Instructions rewrite themselves for observed types; guards and deopt | Inline caches + hidden classes |
            | JIT | Hot loops → uop traces → copy-and-patch machine code; `PYTHON_JIT=1` | Sparkplug / Maglev / TurboFan |
            | GIL and eval breaker | Switches, signals and GC only between instructions | Single-threaded event loop |
            | `compile` / `exec` / `eval` | Never on untrusted input; `ast.literal_eval` for literals | `eval`, `new Function` |
            | AST transformation | `NodeVisitor`, `NodeTransformer`, `fix_missing_locations`; pytest asserts | Babel plugins |
            | `.pyc` | 16-byte header (magic, flags, mtime/size or hash) + `marshal` | V8 code cache |
            | Other implementations | PyPy (tracing JIT), GraalPy, Cython-compiled extensions | SpiderMonkey, JavaScriptCore |

            **Further reading**

            - [`dis`](https://docs.python.org/3/library/dis.html),
              [`ast`](https://docs.python.org/3/library/ast.html),
              [`tokenize`](https://docs.python.org/3/library/tokenize.html),
              [`inspect` — code objects](https://docs.python.org/3/library/inspect.html#types-and-members),
              [`types.CodeType`](https://docs.python.org/3/library/types.html#types.CodeType)
            - [`py_compile`](https://docs.python.org/3/library/py_compile.html),
              [`compileall`](https://docs.python.org/3/library/compileall.html),
              [`marshal`](https://docs.python.org/3/library/marshal.html),
              [`sys.setswitchinterval`](https://docs.python.org/3/library/sys.html#sys.setswitchinterval)
            - [CPython internals docs](https://github.com/python/cpython/tree/main/InternalDocs)
              (interpreter, compiler, frames, exception table)
            - [PEP 659 — Specializing adaptive interpreter](https://peps.python.org/pep-0659/),
              [PEP 709 — Inlined comprehensions](https://peps.python.org/pep-0709/),
              [PEP 744 — JIT compilation](https://peps.python.org/pep-0744/),
              [PEP 552 — Deterministic pycs](https://peps.python.org/pep-0552/),
              [PEP 703 — Making the GIL optional](https://peps.python.org/pep-0703/)
            """
        ),
    ]


def cells() -> list[NotebookNode]:
    """Return the cells for Unit 3.2 and Lab 3.2."""
    return [
        *_overview_cells(),
        *_architecture_cells(),
        *_token_ast_cells(),
        *_code_object_cells(),
        *_function_object_cells(),
        *_reading_dis_cells(),
        *_optimization_cells(),
        *_eval_loop_cells(),
        *_specializing_cells(),
        *_jit_cells(),
        *_gil_cells(),
        *_compile_exec_eval_cells(),
        *_ast_transform_cells(),
        *_pyc_cells(),
        *_implementations_cells(),
        *_predict_cells(),
        *_lab_bytecode_cells(),
        *_lab_ast_cells(),
        *_lab_runtime_cells(),
        *_recap_cells(),
    ]
