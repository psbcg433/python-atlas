"""Unit 1.1 — How Python Executes Code."""

from nbformat import NotebookNode

from nb_builder import code, md, predict_cells

UNIT_SETUP_SOURCE = '''
import ast
import dis
import importlib
import importlib.util
import io
import os
import subprocess
import symtable
import sys
import tokenize
from pathlib import Path


def find_repo_root(start: Path | None = None) -> Path:
    """Walk up from start (default: the working directory) to the folder holding pyproject.toml."""
    current = (start or Path.cwd()).resolve()
    for folder in (current, *current.parents):
        if (folder / "pyproject.toml").exists():
            return folder
    raise FileNotFoundError("pyproject.toml not found above the working directory")


repo_root = find_repo_root()
scratch_dir = repo_root / "notebooks" / "_scratch"
scratch_dir.mkdir(parents=True, exist_ok=True)
print(f"{sys.implementation.name=}, {sys.version_info[:2]=}")
'''


def cells() -> list[NotebookNode]:
    """Return the cells for Unit 1.1."""
    return [
        md(
            """
            ## Unit 1.1 — How Python Executes Code

            **Objectives**

            - Explain what "compiled" and "interpreted" each mean for CPython.
            - Follow one line of source through every stage: tokens, AST, symbol table, code
              object, bytecode, evaluation.
            - Find and recognise the cached bytecode files Python writes in `__pycache__`.
            - Tell statements from expressions and read Python's block syntax.

            **JS bridge**

            | JavaScript concept | Python equivalent | The difference that bites |
            | --- | --- | --- |
            | V8 Ignition bytecode | CPython bytecode (`dis.dis`) | You can print CPython's bytecode from inside the program |
            | TurboFan optimising JIT | Specializing adaptive interpreter (3.11+) and experimental JIT (3.13+) | CPython's JIT is off by default; most speed-ups come from specialisation |
            | Esprima / acorn AST | `ast` module (built in) | The AST is part of the standard library |
            | V8 code cache | `__pycache__/*.pyc` | The cache is a file next to your source, one per interpreter version |
            | `{ … }` blocks, semicolons | Indentation, newlines | Indentation is syntax, not style |
            """
        ),
        code(UNIT_SETUP_SOURCE),
        # 1.1.1 ---------------------------------------------------------------------------------
        md(
            """
            ### 1.1.1 Compiled and interpreted

            CPython does both. It **compiles** the whole source file to **bytecode** (instructions
            for an imaginary machine), then **interprets** that bytecode in a loop. The imaginary
            machine is a **stack-based virtual machine**: instructions push values onto a stack,
            and operators pop their operands off it and push the result.

            The cell disassembles a one-line function. Read it as a stack machine:

            | Instruction | Stack after it |
            | --- | --- |
            | load `price` | `[price]` |
            | load `tax` | `[price, tax]` |
            | `BINARY_OP (+)` | `[price + tax]` |
            | `RETURN_VALUE` | `[]` (value returned) |

            > **Note:** exact instruction names change between Python versions (3.15 fuses the two
            > loads into one `LOAD_FAST_BORROW_LOAD_FAST_BORROW` instruction). The shape stays the same.
            """
        ),
        code(
            '''
            def add_tax(price: int, tax: int) -> int:
                """Return price plus tax."""
                return price + tax


            dis.dis(add_tax)
            '''
        ),
        md(
            """
            **Specializing adaptive interpreter (new in 3.11, PEP 659).** After a function has run
            a few times, CPython rewrites ("quickens") its bytecode in place with versions
            specialised for the types it actually saw. `BINARY_OP (+)` becomes
            `BINARY_OP_ADD_INT` when both operands were always `int`. If a different type turns up,
            the instruction falls back to the generic version.

            `dis.dis(..., adaptive=True)` shows the specialised bytecode. The cell calls `add_tax`
            1000 times with integers first.
            """
        ),
        code(
            """
            for _ in range(1_000):
                add_tax(100, 18)

            dis.dis(add_tax, adaptive=True)
            """
        ),
        md(
            """
            **JIT compiler (experimental, new in 3.13; faster in 3.14 and 3.15, PEP 744).** On top
            of specialisation, CPython can compile hot traces of specialised bytecode to machine
            code. The JIT is built in to the uv builds of 3.15 but **off by default**; set the
            environment variable `PYTHON_JIT=1` to turn it on. `sys._jit` (3.14+) reports the state.

            The cell checks this kernel, then starts a child interpreter with `PYTHON_JIT=1`.
            Interpreters built without the JIT print a skip message.
            """
        ),
        code(
            """
            if hasattr(sys, "_jit"):
                print(f"{sys._jit.is_available()=}  (built with the JIT)")
                print(f"{sys._jit.is_enabled()=}  (turned on in this kernel)")
                child_result = subprocess.run(
                    [sys.executable, "-c", "import sys; print(sys._jit.is_enabled())"],
                    env={**os.environ, "PYTHON_JIT": "1"},
                    capture_output=True,
                    text=True,
                    check=True,
                )
                print(f"with PYTHON_JIT=1: is_enabled() -> {child_result.stdout.strip()}")
            else:
                print("Skipped: sys._jit needs Python 3.14+")
            """
        ),
        md(
            """
            > **JS bridge:** V8 works the same way in outline. **Ignition** compiles JavaScript to
            > bytecode and interprets it; **TurboFan** compiles hot functions to optimised machine
            > code using type feedback. CPython's *adaptive interpreter* plays the role of
            > Ignition's type feedback, and its JIT is a much younger, simpler TurboFan.
            """
        ),
        # 1.1.2 ---------------------------------------------------------------------------------
        md(
            """
            ### 1.1.2 The pipeline

            ```mermaid
            flowchart LR
                source["source text"] --> tokenizer["tokenizer"]
                tokenizer -- "tokens" --> parser["PEG parser"]
                parser -- "AST" --> compiler["compiler + symbol table"]
                compiler -- "code object (bytecode)" --> eval_loop["eval loop (VM)"]
                eval_loop --> result["side effects / result"]
            ```

            <details><summary>ASCII fallback</summary>

            ```text
            source --tokenize--> tokens --PEG parser--> AST --compiler (symbol table)--> code object --eval loop--> result
            ```

            </details>

            | Stage | What it produces | Module to look at it |
            | --- | --- | --- |
            | Tokenizer | `NAME`, `OP`, `NUMBER`… tokens | `tokenize` |
            | PEG parser (3.9+, PEP 617) | Abstract syntax tree | `ast.parse`, `ast.dump` |
            | Symbol table | Which names are local, global, free | `symtable` |
            | Compiler | A **code object**: bytecode + constants + names | `compile`, `code.co_*` |
            | Eval loop | Runs the bytecode on the VM | `exec`, `eval`, `dis` |

            **Stage 1: tokenizer.** It splits source text into tokens.
            """
        ),
        code(
            """
            source_line = "total_in_rupees = price * 2 + 18\\n"
            for token in tokenize.generate_tokens(io.StringIO(source_line).readline):
                print(f"{tokenize.tok_name[token.type]:<10} {token.string!r}")
            """
        ),
        md(
            """
            **Stage 2: parser.** It builds an **abstract syntax tree** from the tokens.
            `ast.dump(ast.parse(...))` prints the tree. Notice that operator precedence is already
            resolved: `price * 2` is nested inside the `+`.
            """
        ),
        code(
            """
            print(ast.dump(ast.parse(source_line), indent=2))
            """
        ),
        md(
            """
            **Stage 3: symbol table.** Before generating bytecode, the compiler decides the scope of
            every name. Inside a function, a name that is assigned is **local**; a name that is only
            read is **global** (or a closure variable). This is decided at compile time, which is
            why Unit 1.11's `UnboundLocalError` exists.
            """
        ),
        code(
            '''
            function_source = """
            def add_gst(price):
                taxed_price = price * gst_rate
                return taxed_price
            """
            module_table = symtable.symtable(function_source, "<demo>", "exec")
            function_table = module_table.lookup("add_gst").get_namespace()
            print(f"{function_table.get_parameters()=}")
            print(f"{function_table.get_locals()=}")
            print(f"{function_table.get_globals()=}")
            '''
        ),
        md(
            """
            **Stage 4: compiler.** `compile(source, filename, mode)` returns a **code object**. The
            mode decides what source is allowed: `"exec"` for statements (a module), `"eval"` for a
            single expression. The code object holds the bytecode (`co_code`) and the tables it
            refers to.
            """
        ),
        code(
            """
            module_code = compile(source_line, "<demo>", "exec")
            expression_code = compile("price * 2 + 18", "<demo>", "eval")
            print(f"{type(module_code).__name__=}")
            print(f"{module_code.co_names=}")
            print(f"{module_code.co_consts=}")
            print(f"{len(module_code.co_code)=} bytes of bytecode")
            print(f"{expression_code.co_names=}")
            """
        ),
        md(
            """
            `dis.dis` turns the code object's bytes back into readable instructions. At module level,
            names are stored with `STORE_NAME` (a dict write) instead of `STORE_FAST` (a slot in the
            frame), which is one reason code inside functions runs faster.
            """
        ),
        code(
            """
            dis.dis(module_code)
            """
        ),
        md(
            """
            **Stage 5: eval loop.** `exec(code, namespace)` runs a code object with a dict you
            supply as its global namespace. The assignment lands in that dict, not in the notebook's
            globals. `eval` runs an expression and returns its value.
            """
        ),
        code(
            """
            demo_namespace: dict[str, object] = {"price": 500}
            exec(module_code, demo_namespace)
            print(f"{demo_namespace['total_in_rupees']=}")
            print(f"{'total_in_rupees' in globals()=}")
            print(f"{eval(expression_code, {'price': 10})=}")
            """
        ),
        md(
            """
            > **Warning:** never `exec` or `eval` text that came from a user. It runs with the
            > full power of your program. Use `ast.literal_eval` to parse literals safely.
            """
        ),
        # 1.1.3 ---------------------------------------------------------------------------------
        md(
            """
            ### 1.1.3 Bytecode caching

            Compiling is not free, so when a module is **imported**, CPython saves the code object
            to `__pycache__/<module>.cpython-315.pyc` next to the source. The next import loads
            the `.pyc` directly, unless the source changed. (The script you run directly, and
            notebook cells, are never cached.)

            The cell writes a small module into `notebooks/_scratch/` and imports it.
            `importlib.util.cache_from_source` computes where its cache file goes.
            """
        ),
        code(
            '''
            module_path = scratch_dir / "price_rules.py"
            module_path.write_text(
                "GST_RATE = 18\\n\\n\\ndef with_gst(price: int) -> float:\\n"
                '    """Return price including GST."""\\n'
                "    return price * (100 + GST_RATE) / 100\\n",
                encoding="utf-8",
            )
            if str(scratch_dir) not in sys.path:
                sys.path.insert(0, str(scratch_dir))
            importlib.invalidate_caches()
            price_rules = importlib.import_module("price_rules")  # same as: import price_rules

            cache_path = Path(importlib.util.cache_from_source(str(module_path)))
            print(f"{price_rules.with_gst(1000)=}")
            print(f"{cache_path.relative_to(scratch_dir)=}")
            print(f"{cache_path.exists()=}")
            '''
        ),
        md(
            """
            Every `.pyc` starts with a 4-byte **magic number** that changes whenever the bytecode
            format changes. A `.pyc` with the wrong magic number is ignored and rebuilt, which is
            why each Python version gets its own file name tag (`sys.implementation.cache_tag`).
            The next 12 bytes hold flags and the source's modification time and size.
            """
        ),
        code(
            """
            pyc_header = cache_path.read_bytes()[:16]
            print(f"{importlib.util.MAGIC_NUMBER=}")
            print(f"{pyc_header[:4]=}")
            print(f"{pyc_header[:4] == importlib.util.MAGIC_NUMBER=}")
            print(f"{sys.implementation.cache_tag=}")
            """
        ),
        md(
            """
            > **Note:** `__pycache__/` belongs in `.gitignore` (this repository has it). Set
            > `PYTHONDONTWRITEBYTECODE=1` to stop Python writing caches, e.g. in read-only containers.
            """
        ),
        # 1.1.4 ---------------------------------------------------------------------------------
        md(
            """
            ### 1.1.4 Statements vs expressions

            An **expression** produces a value (`price * 2`, `f(x)`, `a if c else b`). A
            **statement** does something (`x = 1`, `if`, `for`, `def`, `import`, `return`). Every
            expression can be used as a statement, but not the reverse: `eval` accepts only
            expressions. The AST labels each kind.
            """
        ),
        code(
            """
            sample_module = ast.parse("discount = 10\\nprice * 2\\nif discount:\\n    pass")
            for node in sample_module.body:
                print(f"{type(node).__name__:<6} {ast.unparse(node)!r}")

            try:
                eval("discount = 10")
            except SyntaxError as error:
                print(f"{type(error).__name__}: {error.msg}")
            """
        ),
        md(
            """
            **Indentation is block syntax.** A colon opens a block, and the indented lines below it
            form the body; there are no braces. PEP 8 uses 4 spaces. Wrong indentation is a
            *compile-time* error (`IndentationError`, a subclass of `SyntaxError`), so the cell
            compiles bad source as a string to catch it.
            """
        ),
        code(
            """
            badly_indented_source = "if True:\\nprint('missing indent')\\n"
            try:
                compile(badly_indented_source, "<demo>", "exec")
            except IndentationError as error:
                print(f"{type(error).__name__}: {error.msg} (line {error.lineno})")
            print(f"{issubclass(IndentationError, SyntaxError)=}")
            """
        ),
        md(
            """
            **`pass`** is the statement that does nothing. Python needs it where a block is required
            but you have nothing to put there yet (JS would use `{}`).
            """
        ),
        code(
            '''
            def not_written_yet() -> None:
                """Placeholder whose body is intentionally empty."""
                pass


            class EmptyMarker:
                pass


            print(f"{not_written_yet()=}, {EmptyMarker.__name__=}")
            '''
        ),
        md(
            """
            **Line continuation.** A newline ends a statement *unless* it is inside `()`, `[]` or
            `{}`. Wrap long expressions in brackets instead of ending a line with a backslash:

            ```python
            order_total = 499 + \\
                150          # explicit continuation: breaks if a space follows the backslash
            ```

            `ruff format` (and Black) never produce backslash continuations; they add parentheses.
            """
        ),
        code(
            """
            line_item_prices = [
                499,
                150,
                1_200,
            ]
            order_total = (
                sum(line_item_prices)
                + 40  # delivery charge
                - 100  # coupon
            )
            print(f"{order_total=}, {line_item_prices=}")
            """
        ),
        # Under the hood + predict ----------------------------------------------------------------
        md(
            """
            #### Under the hood: one code object per function

            A function is a thin wrapper around a code object compiled once, when its `def` ran.
            `__code__` exposes it, with the variable names and constants the bytecode uses.
            """
        ),
        code(
            """
            add_tax_code = add_tax.__code__
            print(f"{add_tax_code.co_name=}")
            print(f"{add_tax_code.co_varnames=}")
            print(f"{add_tax_code.co_argcount=}")
            print(f"{add_tax_code.co_consts=}")
            print(f"{add_tax.__code__ is add_tax_code=} (compiled once, reused on every call)")
            """
        ),
        md("#### Predict the output"),
        *predict_cells(
            snippet="""
            namespace = {}
            exec("x = 2\\ny = x * 21", namespace)
            print(namespace["y"], "y" in globals())
            """,
            answer="""
            `42 False`. `exec` used `namespace` as the global namespace of the code it ran, so both
            `x` and `y` were stored there and not in the notebook's globals.
            """,
            proof="""
            namespace: dict[str, object] = {}
            exec("x = 2\\ny = x * 21", namespace)
            print(namespace["y"], "y" in globals())
            """,
        ),
        *predict_cells(
            snippet="""
            print(type(ast.parse("1 + 2").body[0]).__name__)
            """,
            answer="""
            `Expr`. `ast.parse` defaults to `"exec"` mode, so the source is a module whose body is a
            list of **statements**. A bare expression becomes an *expression statement* (`Expr`)
            that wraps the `BinOp`.
            """,
            proof="""
            print(type(ast.parse("1 + 2").body[0]).__name__)
            print(type(ast.parse("1 + 2").body[0].value).__name__)
            """,
        ),
        md(
            """
            ### Recap — Unit 1.1

            | Concept | One-line takeaway | JS equivalent |
            | --- | --- | --- |
            | Compiled *and* interpreted | Source → bytecode once, then a stack VM runs it | V8 Ignition |
            | Adaptive interpreter | Hot bytecode is specialised for the types it sees (3.11+) | Inline caches / type feedback |
            | JIT | Experimental, off by default, enable with `PYTHON_JIT=1` (3.13+) | TurboFan |
            | Pipeline | tokenize → PEG parser → AST → symbol table → code object → eval loop | parse → AST → bytecode → execute |
            | `exec` / `eval` | Run code in a namespace dict you control; never on untrusted input | `eval`, `new Function` |
            | `__pycache__` | Imported modules cache bytecode in `.pyc`, checked by magic number | V8 code cache |
            | Statement vs expression | Only expressions have values; `eval` accepts only expressions | Same split |
            | Blocks | Indentation + colon; `pass` for an empty body; wrap long lines in brackets | `{ }` and `;` |

            **Further reading**

            - [`dis` — Disassembler](https://docs.python.org/3/library/dis.html),
              [`ast`](https://docs.python.org/3/library/ast.html),
              [`symtable`](https://docs.python.org/3/library/symtable.html),
              [`tokenize`](https://docs.python.org/3/library/tokenize.html)
            - [Built-in `compile`, `exec`, `eval`](https://docs.python.org/3/library/functions.html#compile),
              [`importlib.util.cache_from_source`](https://docs.python.org/3/library/importlib.html#importlib.util.cache_from_source)
            - [Language reference: lexical analysis (indentation, line joining)](https://docs.python.org/3/reference/lexical_analysis.html)
            - [PEP 617 — PEG parser](https://peps.python.org/pep-0617/),
              [PEP 659 — Specializing adaptive interpreter](https://peps.python.org/pep-0659/),
              [PEP 744 — JIT compilation](https://peps.python.org/pep-0744/),
              [PEP 3147 — `__pycache__` directories](https://peps.python.org/pep-3147/)
            """
        ),
    ]
