# Unit 1.1 — How Python Executes Code

[Index](README.md) · [Next →](unit-1-2-objects-names-and-mutability.md)

Before learning what Python code *means*, it pays to know what happens when you
press "run". This unit follows one line of source through every stage CPython
puts it through, from raw text to tokens, a syntax tree, a code object full of
bytecode, and finally a virtual machine that executes it. Along the way you will
meet the bytecode cache in `__pycache__` and the rules that separate statements
from expressions, including the one that surprises every JavaScript developer:
indentation is syntax.

## What you will learn

- What "compiled" and "interpreted" each mean for CPython, and why the answer
  is "both".
- How the specializing adaptive interpreter (3.11+) and the experimental JIT
  (3.13+) speed up hot code.
- How to follow one line of source through every stage: tokens, AST, symbol
  table, code object, bytecode, evaluation.
- Where Python caches compiled bytecode (`__pycache__/*.pyc`) and how it knows
  when a cache file is stale.
- How to tell statements from expressions, and how to read Python's block
  syntax: indentation, `pass`, and line continuation.

## JavaScript → Python bridge

Modern JavaScript engines and CPython are built on the same broad idea: compile
to bytecode, interpret it, and optimise the hot parts. The table maps the pieces
you may already know from V8 onto their CPython counterparts.

| JavaScript | Python | The difference that bites |
| --- | --- | --- |
| V8 Ignition bytecode | CPython bytecode | You can print it with `dis.dis` |
| TurboFan optimising JIT | Adaptive interpreter + JIT | The JIT is off by default |
| Esprima / acorn AST | `ast` module | The AST is in the standard library |
| V8 code cache | `__pycache__/*.pyc` | A file next to your source |
| `{ … }` blocks, `;` | Indentation, newlines | Indentation is syntax, not style |

A few more details on those rows. CPython's speed-ups today come mostly from
*specialisation* of bytecode, not from the JIT. The `.pyc` cache is written one
file per interpreter version, so 3.14 and 3.15 never fight over the same file.

### Setup used by the examples

Every example in this unit runs in one session that starts with these imports.
`scratch_dir` is a throwaway folder the bytecode-cache example writes into.

```python
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
    """Walk up from start (default: cwd) to the folder with pyproject.toml."""
    current = (start or Path.cwd()).resolve()
    for folder in (current, *current.parents):
        if (folder / "pyproject.toml").exists():
            return folder
    raise FileNotFoundError(
        "pyproject.toml not found above the working directory"
    )


repo_root = find_repo_root()
scratch_dir = repo_root / "notebooks" / "_scratch"
scratch_dir.mkdir(parents=True, exist_ok=True)
print(f"{sys.implementation.name=}, {sys.version_info[:2]=}")
```

```text
sys.implementation.name='cpython', sys.version_info[:2]=(3, 15)
```

`sys.implementation.name` tells you *which* Python you are on. "Python" is a
language specification; CPython (written in C) is the reference implementation
and the one almost everybody uses. PyPy, GraalPy and MicroPython are others.
Everything in this unit describes CPython 3.15.

## 1.1.1 Compiled and interpreted

### Both at once

People often call Python "an interpreted language" and C "a compiled language",
as if those were opposites. CPython does both. When it loads a module, it first
**compiles** the whole source file into **bytecode**: a compact list of
instructions for an imaginary computer. Then it **interprets** that bytecode,
one instruction at a time, in a big loop written in C (the *eval loop*, in
`Python/ceval.c`). The compile step happens automatically and invisibly, which
is why it is easy to forget it exists. It is also why a syntax error anywhere in
a file stops the whole file before a single line runs: the compiler rejects the
file as a unit.

The imaginary computer is a **stack-based virtual machine**. It has no named
registers. Instructions push values onto a value stack, and operators pop their
operands off the top of the stack and push their result back. Each function call
gets its own *frame*, which holds that call's stack plus an array of slots for
its local variables.

The `dis` module ("disassembler") prints the bytecode of any function. Here is a
one-line function and its bytecode.

```python
def add_tax(price: int, tax: int) -> int:
    """Return price plus tax."""
    return price + tax


dis.dis(add_tax)
```

```text
  1           RESUME                   0

  3           LOAD_FAST_BORROW_LOAD_FAST_BORROW 1 (price, tax)
              BINARY_OP                0 (+)
              RETURN_VALUE
```

The numbers in the left column are source line numbers: `RESUME` belongs to the
`def` line, and the rest to line 3, `return price + tax`. Read the body as a
stack machine:

| Instruction | Stack after it |
| --- | --- |
| load `price` | `[price]` |
| load `tax` | `[price, tax]` |
| `BINARY_OP (+)` | `[price + tax]` |
| `RETURN_VALUE` | `[]` (value returned) |

`RESUME` is a bookkeeping instruction at the start of every function; the
interpreter uses it to check for things like pending signals and tracing.

> **Note:** exact instruction names change between Python versions. 3.15 fuses
> the two loads into one `LOAD_FAST_BORROW_LOAD_FAST_BORROW` instruction
> ("borrow" means it skips a reference-count increment it can prove is not
> needed). Older versions show two separate `LOAD_FAST` lines. The shape of the
> program stays the same, so never write code that depends on bytecode details.

### The specializing adaptive interpreter (3.11+, PEP 659)

A generic `BINARY_OP (+)` has to ask, every time it runs, "what types are these
two operands, and what does `+` mean for them?" It might be integer addition,
float addition, string concatenation, list concatenation, or a call to a custom
`__add__` method. That lookup costs time on every execution.

Since Python 3.11, CPython watches what actually happens. After a function has
run a few times, the interpreter rewrites ("quickens") its bytecode in place
with **specialised** instructions for the types it saw. If both operands of `+`
were always `int`, `BINARY_OP` becomes `BINARY_OP_ADD_INT`, which skips the type
dispatch and adds two integers directly. Each specialised instruction keeps a
cheap guard: if a different type turns up later, it falls back to the generic
version (and may re-specialise for the new type).

`dis.dis(..., adaptive=True)` shows the quickened bytecode. The example calls
`add_tax` 1000 times with integers first.

```python
for _ in range(1_000):
    add_tax(100, 18)

dis.dis(add_tax, adaptive=True)
```

```text
  1           RESUME_CHECK             0

  3           LOAD_FAST_BORROW_LOAD_FAST_BORROW 1 (price, tax)
              BINARY_OP_ADD_INT        0 (+)
              RETURN_VALUE
```

Two instructions changed: `BINARY_OP` became `BINARY_OP_ADD_INT`, and `RESUME`
became the cheaper `RESUME_CHECK`. Nothing in your source changed. This is the
main reason Python 3.11 was 10–60% faster than 3.10 on many workloads.

> **Note:** specialisation rewards *type-stable* code. A function that always
> receives `int` stays on the fast path; one that alternates between `int`,
> `float` and `str` keeps falling back to the generic instruction. This is the
> same advice V8 gives about keeping functions "monomorphic".

### The JIT compiler (experimental, 3.13+, PEP 744)

On top of specialisation, CPython can compile hot *traces* (straight-line runs
of specialised bytecode that execute often) into native machine code. This is
the JIT, added as an experiment in 3.13 and made faster in 3.14 and 3.15. It
uses a "copy-and-patch" design: machine-code templates for each instruction are
prepared when CPython itself is built, and at run time the JIT stitches copies
of them together and patches in the real addresses. That keeps the JIT small and
simple compared with a full optimising compiler.

The uv builds of 3.15 include the JIT, but it is **off by default**. Set the
environment variable `PYTHON_JIT=1` before starting the interpreter to turn it
on. `sys._jit` (3.14+; the underscore marks it as an implementation detail)
reports the state. The example checks the current interpreter, then starts a
child interpreter with `PYTHON_JIT=1` and asks it the same question.
Interpreters built without the JIT print a skip message instead.

```python
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
```

```text
sys._jit.is_available()=True  (built with the JIT)
sys._jit.is_enabled()=False  (turned on in this kernel)
with PYTHON_JIT=1: is_enabled() -> True
```

> **Note:** these values depend on how your interpreter was built. A Python
> from another source (a Linux distribution package, for example) may report
> `is_available()=False`, and then `PYTHON_JIT=1` has no effect.

### How this compares with V8

V8 works the same way in outline. **Ignition** compiles JavaScript to bytecode
and interprets it, collecting *type feedback* as it goes. **TurboFan** then
compiles hot functions to optimised machine code using that feedback, and
*deoptimises* back to bytecode when an assumption breaks. CPython's adaptive
interpreter plays the role of Ignition's type feedback (with in-place
specialised instructions instead of separate feedback vectors), and its JIT is a
much younger, simpler TurboFan. The biggest practical difference: in V8 the JIT
is always on and does most of the heavy lifting, while in CPython most of the
speed comes from the interpreter itself.

### Key points

| Idea | Takeaway |
| --- | --- |
| Compile step | Whole file → bytecode before anything runs |
| Interpret step | A C loop runs bytecode on a stack VM |
| Adaptive interpreter | Rewrites hot bytecode for seen types |
| JIT | Experimental; `PYTHON_JIT=1` to enable |
| `dis.dis` | Prints bytecode; names vary by version |

## 1.1.2 The pipeline

### The stages at a glance

Turning text into running code happens in five stages. Each stage hands a
richer structure to the next, and the standard library has a module that lets
you inspect every one of them.

```text
 source text
     |
     v
 +-----------+   tokens   +------------+    AST
 | tokenizer | ---------> | PEG parser | ---------+
 +-----------+            +------------+          |
                                                  v
 +-----------+   code object (bytecode)  +--------------------+
 | eval loop | <------------------------ | compiler           |
 |   (VM)    |                           | (+ symbol table)   |
 +-----------+                           +--------------------+
     |
     v
 side effects / result
```

| Stage | Produces | Inspect with |
| --- | --- | --- |
| Tokenizer | `NAME`, `OP`, `NUMBER`… | `tokenize` |
| PEG parser (3.9+) | Abstract syntax tree | `ast.parse`, `ast.dump` |
| Symbol table | Local / global / free names | `symtable` |
| Compiler | Code object | `compile`, `co_*` |
| Eval loop | Runs the bytecode | `exec`, `eval`, `dis` |

A **code object** bundles the bytecode with the constants and names it refers
to. The PEG parser replaced the older LL(1) parser in Python 3.9 (PEP 617); its
extra power is what made syntax like `match` statements and parenthesised
context managers possible.

The stages below all follow the same line of source:

```python
source_line = "total_in_rupees = price * 2 + 18\n"
```

### Stage 1: the tokenizer

The tokenizer (also called the lexer) reads raw characters and groups them into
**tokens**: names, operators, numbers, strings, plus structural tokens such as
`NEWLINE`, `INDENT` and `DEDENT`. It does not care what the program means; it
only cares where one word ends and the next begins. Python's tokenizer is
unusual in one way: it tracks indentation and emits `INDENT`/`DEDENT` tokens
when the indentation level changes, which is how indentation becomes part of
the grammar.

```python
source_line = "total_in_rupees = price * 2 + 18\n"
for token in tokenize.generate_tokens(io.StringIO(source_line).readline):
    print(f"{tokenize.tok_name[token.type]:<10} {token.string!r}")
```

```text
NAME       'total_in_rupees'
OP         '='
NAME       'price'
OP         '*'
NUMBER     '2'
OP         '+'
NUMBER     '18'
NEWLINE    '\n'
ENDMARKER  ''
```

`generate_tokens` wants a function that returns one line per call, which is
what `io.StringIO(...).readline` provides. `ENDMARKER` marks the end of input.

### Stage 2: the parser and the AST

The parser checks the tokens against Python's grammar and builds an **abstract
syntax tree** (AST): a tree of nodes in which each node is one construct
(an assignment, a binary operation, a name, a constant). "Abstract" means the
punctuation is gone; parentheses, commas and colons have done their job and
only the structure remains. `ast.parse` returns the tree and `ast.dump` prints
it.

```python
print(ast.dump(ast.parse(source_line), indent=2))
```

```text
Module(
  body=[
    Assign(
      targets=[
        Name(id='total_in_rupees', ctx=Store())],
      value=BinOp(
        left=BinOp(
          left=Name(id='price'),
          op=Mult(),
          right=Constant(value=2)),
        op=Add(),
        right=Constant(value=18)))])
```

Notice that operator precedence is already resolved: `price * 2` is a `BinOp`
nested *inside* the `+`. Each `Name` node also records its context:
`ctx=Store()` for the assignment target. (Recent versions of `ast.dump` leave
out the default `ctx=Load()`, which is why `price` shows no context.)

Because the AST is a regular Python object, tools work on it directly: linters
such as Ruff, formatters, type checkers, test frameworks like pytest (which
rewrites `assert` statements) all start from it. In JavaScript you would install
acorn or Babel for this; in Python it ships with the language.

### Stage 3: the symbol table

Before generating bytecode, the compiler walks the AST and builds a **symbol
table**: for every function, it decides the **scope** of every name. The rule
is simple and purely textual:

- a name that is **assigned** anywhere in the function body (or is a
  parameter) is **local** to that function;
- a name that is only **read** is looked up outside: in an enclosing function
  (a *free* or closure variable) or in the module globals and built-ins.

This is decided at compile time, before the function ever runs. That is the
reason Unit 1.11's `UnboundLocalError` exists: if a function assigns `x` on any
line, *every* use of `x` in that function refers to the local, even a read that
comes before the assignment. The `symtable` module shows the result.

```python
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
```

```text
function_table.get_parameters()=('price',)
function_table.get_locals()=('price', 'taxed_price')
function_table.get_globals()=('gst_rate',)
```

`price` (a parameter) and `taxed_price` (assigned) are local; `gst_rate` is only
read, so it is global. The compiler never checked whether `gst_rate` actually
exists; that is only discovered at run time.

> **Note:** JavaScript makes the same kind of decision through `let`, `const`
> and `var` declarations. Python has no declaration keywords, so *assignment
> is the declaration*. Unit 1.11 covers `global` and `nonlocal`, which override
> the rule.

### Stage 4: the compiler and code objects

The compiler turns the AST plus the symbol table into a **code object**. The
built-in `compile(source, filename, mode)` runs stages 1 to 4 in one call and
hands you the result. The `filename` is only used in error messages and
tracebacks (by convention `"<demo>"` or `"<string>"` for code that is not in a
file). The `mode` decides what source is allowed:

| Mode | Accepts | Run with |
| --- | --- | --- |
| `"exec"` | Any statements (a module) | `exec` |
| `"eval"` | A single expression | `eval` |
| `"single"` | One interactive statement | `exec` (REPL) |

```python
module_code = compile(source_line, "<demo>", "exec")
expression_code = compile("price * 2 + 18", "<demo>", "eval")
print(f"{type(module_code).__name__=}")
print(f"{module_code.co_names=}")
print(f"{module_code.co_consts=}")
print(f"{len(module_code.co_code)=} bytes of bytecode")
print(f"{expression_code.co_names=}")
```

```text
type(module_code).__name__='code'
module_code.co_names=('price', 'total_in_rupees')
module_code.co_consts=(2,)
len(module_code.co_code)=40 bytes of bytecode
expression_code.co_names=('price',)
```

A code object is immutable and holds everything the VM needs: the raw bytecode
in `co_code`, the names the bytecode looks up in `co_names`, and the constants
in `co_consts`. Instructions refer to entries in these tables by index, which
keeps the bytecode compact. The exact contents of these tables are an
implementation detail: 3.15, for example, loads small integers with a dedicated
`LOAD_SMALL_INT` instruction (visible in the listing below) instead of reading
them from `co_consts`.

`dis.dis` turns the code object's bytes back into readable instructions.

```python
dis.dis(module_code)
```

```text
  0           RESUME                   0

  1           LOAD_NAME                0 (price)
              LOAD_SMALL_INT           2
              BINARY_OP                5 (*)
              LOAD_SMALL_INT          18
              BINARY_OP                0 (+)
              STORE_NAME               1 (total_in_rupees)
              LOAD_COMMON_CONSTANT     7 (None)
              RETURN_VALUE
```

You can map every instruction to the AST: load `price`, load `2`, multiply,
load `18`, add, store the result. The last two lines exist because every code
object returns something; a module returns `None`.

At module level, names are read with `LOAD_NAME` and written with `STORE_NAME`,
which are dictionary lookups and writes in the module's namespace. Inside a
function, the symbol table already knows which names are local, so the compiler
emits `LOAD_FAST`/`STORE_FAST`, which index straight into a fixed array of
slots in the frame. That is one reason the same code runs faster inside a
function than at the top level of a script.

> **Note:** this is why Python performance advice says "put your hot loop in a
> function". Local variable access is an array index; global access is a dict
> lookup.

### Stage 5: the eval loop

The final stage runs the code object. `exec(code, namespace)` executes it, using
a dict you supply as its **global namespace**: every top-level assignment lands
in that dict, not in your program's globals. `eval(code, namespace)` runs an
expression code object and returns its value. Both also accept source strings
directly and compile them first.

```python
demo_namespace: dict[str, object] = {"price": 500}
exec(module_code, demo_namespace)
print(f"{demo_namespace['total_in_rupees']=}")
print(f"{'total_in_rupees' in globals()=}")
print(f"{eval(expression_code, {'price': 10})=}")
```

```text
demo_namespace['total_in_rupees']=1018
'total_in_rupees' in globals()=False
eval(expression_code, {'price': 10})=38
```

The namespace dict is exactly what a module *is* at run time: when you
`import` a module, Python creates a fresh module object, compiles the file, and
`exec`s the code object with the module's `__dict__` as the namespace. The
names a module defines are just keys in that dict. (`exec` also adds a
`__builtins__` key to the dict you pass, so that `print`, `len` and friends
resolve.)

> **Warning:** never `exec` or `eval` text that came from a user, a file you do
> not control, or the network. It runs with the full power of your program and
> can delete files or open sockets. To turn a string into a Python literal
> (numbers, strings, lists, dicts, tuples, sets, booleans, `None`), use
> `ast.literal_eval`, which rejects anything else.

```python
print(f"{ast.literal_eval('[499, 150, 1_200]')=}")
try:
    ast.literal_eval("__import__('os').getcwd()")
except ValueError as error:
    print(f"rejected with {type(error).__name__}")
```

```text
ast.literal_eval('[499, 150, 1_200]')=[499, 150, 1200]
rejected with ValueError
```

JavaScript's `eval` and `new Function(...)` carry the same warning. The
difference is that Python's `exec` lets you hand it an isolated globals dict,
which makes it handy for config files you trust and for tooling, though it is
**not** a security sandbox.

### Key points

| Stage | Key fact |
| --- | --- |
| Tokenizer | Emits `INDENT`/`DEDENT` tokens |
| Parser | AST with precedence resolved |
| Symbol table | Assigned in a function = local |
| Compiler | `compile()` → immutable code object |
| Eval loop | `exec`/`eval` run in a dict you supply |

## 1.1.3 Bytecode caching

### Where `.pyc` files come from

Compiling is not free, and a large application imports hundreds of modules.
So when a module is **imported**, CPython saves its compiled code object
(serialised with the `marshal` format) to a file in a `__pycache__` folder next
to the source:

```text
my_project/
├── price_rules.py
└── __pycache__/
    └── price_rules.cpython-315.pyc
```

The next import of `price_rules` checks the `.pyc` against the source; if the
source has not changed, CPython loads the code object straight from the cache
and skips stages 1 to 4. The `cpython-315` part of the file name is the
interpreter's **cache tag**, so different Python versions keep separate cache
files side by side (PEP 3147).

Two things are never cached: the script you run directly
(`python main.py` compiles `main.py` fresh every time) and notebook cells.
Only imported modules get a `.pyc`.

The example writes a small module into the scratch folder, imports it, and then
uses `importlib.util.cache_from_source` to compute where its cache file should
be.

```python
module_path = scratch_dir / "price_rules.py"
module_path.write_text(
    "GST_RATE = 18\n\n\ndef with_gst(price: int) -> float:\n"
    '    """Return price including GST."""\n'
    "    return price * (100 + GST_RATE) / 100\n",
    encoding="utf-8",
)
if str(scratch_dir) not in sys.path:
    sys.path.insert(0, str(scratch_dir))
importlib.invalidate_caches()
# same as: import price_rules
price_rules = importlib.import_module("price_rules")

cache_path = Path(importlib.util.cache_from_source(str(module_path)))
print(f"{price_rules.with_gst(1000)=}")
print(f"{cache_path.parent.name=}")
print(f"{cache_path.name=}")
print(f"{cache_path.exists()=}")
```

```text
price_rules.with_gst(1000)=1180.0
cache_path.parent.name='__pycache__'
cache_path.name='price_rules.cpython-315.pyc'
cache_path.exists()=True
```

> **Note:** the notebook prints the cache path relative to the scratch folder
> on one line (`PosixPath('__pycache__/price_rules.cpython-315.pyc')`). Here it
> is split into the folder name and the file name to fit the screen. The full
> absolute path depends on where the repository lives on your machine.

A few details of the example: `sys.path` is the list of folders `import`
searches, so the scratch folder is added to it; `importlib.invalidate_caches()`
tells the import system to rescan folders, since the module file was created
after Python started; and `importlib.import_module` is the function form of the
`import` statement.

### The `.pyc` header and the magic number

Every `.pyc` file starts with a 16-byte header. The first 4 bytes are the
**magic number**, which changes whenever the bytecode format changes (which
happens in practically every minor release). The next 12 bytes hold a flags
field and, by default, the source file's modification time and size.

```text
 bytes 0-3    bytes 4-7    bytes 8-11     bytes 12-15
+-----------+-----------+--------------+-------------+
|  magic    |  flags    | source mtime | source size |
+-----------+-----------+--------------+-------------+
| marshalled code object ...                         |
+----------------------------------------------------+
```

When importing, CPython reads the header. If the magic number does not match
its own `importlib.util.MAGIC_NUMBER`, or the recorded mtime and size do not
match the source file, the `.pyc` is ignored and rebuilt.

```python
pyc_header = cache_path.read_bytes()[:16]
print(f"{importlib.util.MAGIC_NUMBER=}")
print(f"{pyc_header[:4]=}")
print(f"{pyc_header[:4] == importlib.util.MAGIC_NUMBER=}")
print(f"{sys.implementation.cache_tag=}")
```

```text
importlib.util.MAGIC_NUMBER=b'R\x0e\r\n'
pyc_header[:4]=b'R\x0e\r\n'
pyc_header[:4] == importlib.util.MAGIC_NUMBER=True
sys.implementation.cache_tag='cpython-315'
```

The magic number always ends in `\r\n`. That is deliberate: if a `.pyc` is
ever pushed through a tool that converts line endings, the corrupted bytes no
longer match and the file is rejected instead of being misread.

> **Note:** the exact magic number bytes are specific to this 3.15 build; a
> different Python version prints different bytes.

> **Note:** `__pycache__/` belongs in `.gitignore` (this repository has it).
> Set the environment variable `PYTHONDONTWRITEBYTECODE=1` (or run
> `python -B`) to stop Python writing caches, for example in read-only
> containers.

### Compared with JavaScript

V8 also has a **code cache**: Chrome and Node can store compiled bytecode to
skip parsing on the next load. The difference is visibility. V8's cache lives
inside the browser or in a location you rarely look at; CPython's is an
ordinary file next to your source that you will see in every Python project.
Deleting `__pycache__` folders is always safe; Python simply recompiles.

### Key points

| Item | Takeaway |
| --- | --- |
| When cached | Only on `import`, not the main script |
| Location | `__pycache__/<name>.cpython-315.pyc` |
| Magic number | First 4 bytes; version check |
| Staleness | mtime + size compared with source |
| `cache_from_source` | Computes the `.pyc` path |

## 1.1.4 Statements vs expressions

### Two kinds of code

An **expression** is code that produces a value: `price * 2`, `f(x)`,
`a if c else b`, `[n * 2 for n in prices]`. A **statement** is code that *does*
something: `x = 1`, `if`, `for`, `while`, `def`, `class`, `import`, `return`.

Every expression can be used as a statement (calling `print(...)` on its own
line is an expression used as a statement), but not the reverse. A statement
has no value, so it cannot appear where a value is expected. `eval` accepts only
expressions, and the AST labels each kind explicitly.

```python
sample_module = ast.parse("discount = 10\nprice * 2\nif discount:\n    pass")
for node in sample_module.body:
    print(f"{type(node).__name__:<6} {ast.unparse(node)!r}")

try:
    eval("discount = 10")
except SyntaxError as error:
    print(f"{type(error).__name__}: {error.msg}")
```

```text
Assign 'discount = 10'
Expr   'price * 2'
If     'if discount:\n    pass'
SyntaxError: invalid syntax
```

The bare expression `price * 2` became an `Expr` node: an *expression
statement* that evaluates the expression and throws the value away.
`ast.unparse` turns a node back into source text.

This split is sharper than in JavaScript. In JavaScript, assignment is an
expression (`if (x = next())` is legal), and so is the comma operator. In
Python, plain `=` is a statement only; when you genuinely need an assignment
inside an expression, the walrus operator `:=` (Unit 1.9) exists for that, and
it is deliberately visually distinct.

> **Note:** the REPL and Jupyter show the value of an expression statement
> automatically, which is why typing `price * 2` there prints a result. In a
> script, the same line computes the value and silently discards it.

### Indentation is block syntax

Python has no braces. A **colon** at the end of a line opens a block (after
`if`, `for`, `while`, `def`, `class`, `with`, `try` and friends), and the
**indented** lines below it form the block's body. The block ends at the first
line that returns to the previous indentation level. As you saw in stage 1, the
tokenizer turns those indentation changes into `INDENT` and `DEDENT` tokens, so
for the parser they work exactly like `{` and `}`.

PEP 8 uses **4 spaces** per level, and every formatter enforces it. Mixing tabs
and spaces inconsistently is an error in Python 3.

Wrong indentation is a *compile-time* error: `IndentationError`, a subclass of
`SyntaxError`. Since it happens before any code runs, a `try` block in the same
file cannot catch it. The example therefore compiles bad source held in a string,
which turns the compile-time error into a run-time one we can catch.

```python
badly_indented_source = "if True:\nprint('missing indent')\n"
try:
    compile(badly_indented_source, "<demo>", "exec")
except IndentationError as error:
    print(f"{type(error).__name__} on line {error.lineno}:")
    print(f"  {error.msg}")
print(f"{issubclass(IndentationError, SyntaxError)=}")
```

```text
IndentationError on line 2:
  expected an indented block after 'if' statement on line 1
issubclass(IndentationError, SyntaxError)=True
```

> **Note:** the notebook prints the error on one line; the message is split
> over two `print` calls here to fit the screen. The text is unchanged.

> **Warning:** JavaScript developers sometimes treat indentation as cosmetic
> and let an editor "fix" it. In Python, re-indenting a line can move it into
> or out of a block and silently change what the program does, for example
> moving a `return` out of a loop body.

### `pass`: the empty block

Because a colon must be followed by an indented block, Python needs a way to
write a block that does nothing. That is **`pass`**, the statement that does
nothing at all. JavaScript would use `{}`. You will use it for placeholder
functions, empty classes, and `except` clauses that deliberately ignore an
error.

```python
def not_written_yet() -> None:
    """Placeholder whose body is intentionally empty."""
    pass


class EmptyMarker:
    pass


print(f"{not_written_yet()=}, {EmptyMarker.__name__=}")
```

```text
not_written_yet()=None, EmptyMarker.__name__='EmptyMarker'
```

A function whose body never returns a value returns `None`, Python's version of
`undefined`/`null` rolled into one. A docstring is itself an expression
statement, so a function with only a docstring is already a valid body; the
`pass` above is optional and kept for illustration. You will also see `...`
(the `Ellipsis` literal) used as a placeholder, mostly in type stubs.

### Line continuation

A newline ends a statement. There are no semicolons to worry about, and none of
JavaScript's automatic-semicolon-insertion surprises. The one exception is the
key to writing long statements: a newline **inside `()`, `[]` or `{}`** does not
end the statement. The tokenizer keeps track of open brackets and ignores
newlines until they are all closed. This is called *implicit line joining*.

```python
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
```

```text
order_total=1789, line_item_prices=[499, 150, 1200]
```

The extra parentheses around the `order_total` expression change nothing about
its value; they exist only to allow the line breaks. Comments are allowed on
each line, and the trailing comma after `1_200` is legal (and recommended,
because adding an item later changes only one line in a diff).

The alternative is *explicit line joining*: ending a line with a backslash.

```python
order_total = 499 + \
    150
print(f"{order_total=}")
```

```text
order_total=649
```

It works, but it is fragile: the backslash must be the very last character on
the line. A single invisible space after it breaks the code.

```python
source_with_trailing_space = "order_total = 499 + \\ \n    150\n"
try:
    compile(source_with_trailing_space, "<demo>", "exec")
except SyntaxError as error:
    print(f"{type(error).__name__}: {error.msg}")
```

```text
SyntaxError: unexpected character after line continuation character
```

`ruff format` (and Black) never produce backslash continuations; they add
parentheses instead. Do the same. (The one place backslashes still appear is
long `with` statements in old code; since 3.10 you can parenthesise those
too.)

### Under the hood: one code object per function

A function object is a thin wrapper around a code object. The body of a `def`
is compiled **once**, together with the rest of the module; when the `def`
statement *runs*, Python creates a function object that points at that
already-compiled code object, plus the function's globals, defaults and
closure. Calling the function creates a new frame for the same code object.
`__code__` exposes it, with the variable names and constants the bytecode uses.

```python
add_tax_code = add_tax.__code__
print(f"{add_tax_code.co_name=}")
print(f"{add_tax_code.co_varnames=}")
print(f"{add_tax_code.co_argcount=}")
print(f"{add_tax_code.co_consts=}")
print(
    f"{add_tax.__code__ is add_tax_code=}"
    " (compiled once, reused on every call)"
)
```

```text
add_tax_code.co_name='add_tax'
add_tax_code.co_varnames=('price', 'tax')
add_tax_code.co_argcount=2
add_tax_code.co_consts=('Return price plus tax.',)
add_tax.__code__ is add_tax_code=True (compiled once, reused on every call)
```

`co_varnames` lists the local variable slots that `LOAD_FAST` indexes into
(parameters come first). `co_consts` holds the docstring, which is stored as the
first constant of the function's code object.

### Predict the output

Try each one before opening the answer.

**Question 1.**

```python
namespace = {}
exec("x = 2\ny = x * 21", namespace)
print(namespace["y"], "y" in globals())
```

<details><summary>Answer</summary>

```text
42 False
```

`exec` used `namespace` as the global namespace of the code it ran, so both `x`
and `y` were stored there and not in the caller's globals.

</details>

**Question 2.**

```python
print(type(ast.parse("1 + 2").body[0]).__name__)
```

<details><summary>Answer</summary>

```text
Expr
```

`ast.parse` defaults to `"exec"` mode, so the source is a module whose body is
a list of **statements**. A bare expression becomes an *expression statement*
(`Expr`) that wraps the `BinOp`. You can confirm by looking one level deeper:

```python
print(type(ast.parse("1 + 2").body[0]).__name__)
print(type(ast.parse("1 + 2").body[0].value).__name__)
```

```text
Expr
BinOp
```

</details>

### Key points

| Rule | Takeaway |
| --- | --- |
| Expression | Produces a value; usable as a statement |
| Statement | Does something; `=` is a statement |
| Blocks | Colon + 4-space indentation |
| `IndentationError` | Compile time; subclass of `SyntaxError` |
| `pass` | Empty block placeholder |
| Long lines | Wrap in brackets, not `\` |

## Recap

| Concept | Takeaway | JavaScript equivalent |
| --- | --- | --- |
| Compiled and interpreted | Source → bytecode once, then a stack VM | V8 Ignition |
| Adaptive interpreter | Hot bytecode specialised by type (3.11+) | Type feedback |
| JIT | Experimental, off; `PYTHON_JIT=1` (3.13+) | TurboFan |
| Pipeline | Tokens → AST → symbols → code → eval | Parse → AST → bytecode |
| `exec` / `eval` | Run in a dict you own; never untrusted | `eval`, `new Function` |
| `__pycache__` | Imports cache `.pyc`; magic number check | V8 code cache |
| Statement vs expression | Only expressions have values | Same split |
| Blocks | Indentation + colon; `pass` if empty | `{ }` and `;` |
| Long lines | Wrap in brackets | No ASI worries |

## Further reading

- [`dis` — Disassembler for Python bytecode](https://docs.python.org/3/library/dis.html)
- [`ast` — Abstract syntax trees](https://docs.python.org/3/library/ast.html)
- [`symtable` — Compiler symbol tables](https://docs.python.org/3/library/symtable.html)
- [`tokenize` — Tokenizer for Python source](https://docs.python.org/3/library/tokenize.html)
- [Built-in `compile`](https://docs.python.org/3/library/functions.html#compile),
  [`exec`](https://docs.python.org/3/library/functions.html#exec) and
  [`eval`](https://docs.python.org/3/library/functions.html#eval)
- [`importlib.util.cache_from_source`](https://docs.python.org/3/library/importlib.html#importlib.util.cache_from_source)
- [Language reference: lexical analysis](https://docs.python.org/3/reference/lexical_analysis.html)
  (indentation, line joining)
- [PEP 617 — New PEG parser for CPython](https://peps.python.org/pep-0617/)
- [PEP 659 — Specializing adaptive interpreter](https://peps.python.org/pep-0659/)
- [PEP 744 — JIT compilation](https://peps.python.org/pep-0744/)
- [PEP 3147 — PYC repository directories](https://peps.python.org/pep-3147/)

[Index](README.md) · [Next →](unit-1-2-objects-names-and-mutability.md)
