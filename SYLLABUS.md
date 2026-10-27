# Python Engineering: Language Core to FastAPI — Course Syllabus

## Course overview

**Course description.** An intensive, notebook-based course that takes an experienced JavaScript developer from the Python language itself, through CPython internals, professional tooling, concurrency and performance, to building and deploying production APIs with FastAPI. Every unit pairs theory with runnable code and an "under the hood" look at how CPython implements it.

**Prerequisites.** Working knowledge of one programming language (JavaScript/TypeScript assumed): variables, functions, objects, async code, HTTP basics.

**Target platform.** CPython 3.15 (stable since 9 October 2026). Features newer than 3.12 are labelled with the version that introduced them.

### Course structure

| Phase | Title | Notebook | Units |
| --- | --- | --- | --- |
| 0 | Environment and Tooling | `phase0_environment_setup.ipynb` | 0.1–0.4 |
| 1 | Python Language Fundamentals | `phase1_language_fundamentals.ipynb` | 1.1–1.14 |
| 2 | Object-Oriented Programming and the Data Model | `phase2_oop_data_model.ipynb` | 2.1–2.6 |
| 3 | Python Internals: Memory, Bytecode, Imports | `phase3_python_internals.ipynb` | 3.1–3.3 |
| 4 | Professional Python: Packaging, Typing, Testing, Standard Library | `phase4_professional_python.ipynb` | 4.1–4.6 |
| 5 | Concurrency, Async and Performance | `phase5_concurrency_performance.ipynb` | 5.1–5.5 |
| 6 | Web Development with FastAPI | `phase6_web_fastapi.ipynb` | 6.1–6.8 |
| — | Capstone Project | `capstone_task_tracker.ipynb` | — |

### Repository layout

```text
.
├── pyproject.toml
├── .python-version
├── uv.lock
├── notebooks/            # one .ipynb per phase
├── projects/             # code that outgrows a notebook (CLI package, FastAPI apps)
├── exercises/solutions/  # phaseN_solutions.py
└── scripts/              # scripts that generate the notebooks
```

### Course learning outcomes

On completing the course, the learner can:

1. Explain how CPython compiles, executes and manages memory for any Python program.
2. Use every built-in data type and its API fluently, choosing the right one for the job.
3. Write idiomatic, typed, tested and packaged Python.
4. Build classes that integrate with the Python data model, and understand the metaprogramming behind Pydantic and SQLAlchemy.
5. Choose and apply threads, processes or asyncio, and profile and optimize code.
6. Design, secure, test, observe and deploy a production FastAPI service.

---

## Phase 0 — Environment and Tooling

**Notebook:** `phase0_environment_setup.ipynb`

**Outcome:** a reproducible Python 3.15 project with uv, a working Jupyter kernel, and the introspection habits used throughout the course.

### Unit 0.1 — Python, the Language and Its Implementations

#### 0.1.1 Language vs implementation
- The language reference vs implementations: CPython (C), PyPy (JIT), MicroPython, GraalPy.
- JS bridge: the ECMAScript spec vs V8 / SpiderMonkey.

#### 0.1.2 Release cycle
- Yearly October releases, support windows, why this course targets 3.15.

#### 0.1.3 Inspecting the interpreter
- `sys.version`, `sys.version_info`, `sys.implementation.name`, `platform.python_implementation()`, `sys.executable`.

### Unit 0.2 — Installing Python and Virtual Environments

#### 0.2.1 Installing with uv
- `uv python install 3.15`, `uv python list`, pinning with `.python-version`.
- Why never to use the OS Python.

#### 0.2.2 Virtual environments
- Contents of `.venv/`: `bin/python`, `site-packages`, `pyvenv.cfg`.
- Activation only changes `PATH`.

#### 0.2.3 Detecting the environment
- `sys.prefix` vs `sys.base_prefix`; reading `sys.path` entry by entry.

#### 0.2.4 JS bridge
- Per-project `node_modules` vs one virtual environment per project.

### Unit 0.3 — Project Management with uv

#### 0.3.1 Core commands
- `uv init`, `uv add`, `uv add --dev`, `uv remove`, `uv run`, `uv sync`.

#### 0.3.2 The lockfile
- `uv.lock` and reproducible installs.

#### 0.3.3 npm mapping table
- `npm init`, `npm install`, `npm i -D`, `npx`, `npm ci`, `package-lock.json` ↔ their uv equivalents.

### Unit 0.4 — Jupyter and Editor Workflow

#### 0.4.1 Jupyter architecture
- Server vs kernel vs notebook file (JSON); registering the venv kernel with `ipykernel`.

#### 0.4.2 Execution discipline
- Execution counter, out-of-order hazards, Restart & Run All.

#### 0.4.3 Magics
- `%timeit`, `%%time`, `%who`, `%whos`, `%load_ext autoreload` / `%autoreload 2`, `%%writefile`, `?` and `??`.
- Why `uv add` beats `%pip`.

#### 0.4.4 Notebooks are JSON
- Load a notebook with `nbformat` and count its cells.

#### 0.4.5 Editor setup
- VS Code or PyCharm, Pylance/pyright, ruff format-on-save, interpreter selection.

#### 0.4.6 Jupytext
- Pairing `.ipynb` with `.py:percent` for readable git diffs.

#### 0.4.7 Introspection toolkit
- `help()`, `dir()`, `type()`, `id()`, `vars()`, `inspect.getsource()`.

#### Lab 0
1. `environment_report()` printing the Python version, implementation, executable path, whether a venv is active, and the installed `jupyterlab` version via `importlib.metadata.version`.

### Phase 0 Deliverable

The course repository: `pyproject.toml`, `.python-version`, `uv.lock`, `notebooks/`, `projects/`, `exercises/solutions/`, `scripts/`, and a `README.md`.
---

## Phase 1 — Python Language Fundamentals

**Notebook:** `phase1_language_fundamentals.ipynb`

**Outcome:** predict the output of any core Python snippet and explain it in terms of objects, names, types and frames; use every built-in data type and its API fluently.

### Unit 1.1 — How Python Executes Code

#### 1.1.1 Compiled and interpreted
- CPython compiles source to bytecode and runs it on a stack-based virtual machine.
- Specializing adaptive interpreter (3.11+) and the JIT (3.13+, faster in 3.15).
- JS bridge: V8's Ignition bytecode + TurboFan JIT.

#### 1.1.2 The pipeline
- Tokenizer → PEG parser → AST → compiler (symbol table) → code object → eval loop.
- Demos: `ast.dump(ast.parse(...))`, `compile(...)`, `dis.dis(...)`, `exec` into a namespace dict.
- Mermaid diagram of the pipeline.

#### 1.1.3 Bytecode caching
- `__pycache__/*.cpython-315.pyc`, the magic number (`importlib.util.MAGIC_NUMBER`), `importlib.util.cache_from_source`.

#### 1.1.4 Statements vs expressions
- Indentation as block syntax, `pass`, implicit line continuation inside brackets.

### Unit 1.2 — Objects, Names and Mutability

#### 1.2.1 Everything is an object
- Identity (`id`), type (`type`), value.
- Types, functions, modules and classes are objects; `type(int) is type`.

#### 1.2.2 Names and binding
- A variable is a key in a namespace dict bound to an object; `globals()` as a dict.
- Assignment never copies; `del` removes a name, not the object.
- Python Tutor-style diagram of two names pointing at one list.

#### 1.2.3 Call by object reference
- Functions can mutate arguments, but rebinding a parameter does not affect the caller.
- JS bridge: Python has no primitives.

#### 1.2.4 Mutable vs immutable types
- Full classification table.
- "Changing" an immutable creates a new object: `id` before/after `+=` on `int`, `str` and `list`.

#### 1.2.5 Identity vs equality
- `is` vs `==` (`__eq__`); use `is` only for singletons.
- Small-int cache (-5..256 up to 3.14, -5..1024 in 3.15), string interning (`sys.intern`).
- The `SyntaxWarning` for `is` with a literal.

#### 1.2.6 Dynamic typing
- Names have no types, objects do; `type()` vs `isinstance()`; duck typing preview.

### Unit 1.3 — Numeric and Boolean Data Types

#### 1.3.0 Python's built-in data types at a glance
The notebook opens Unit 1.3 with this table (types are taught in Units 1.3–1.7):

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

#### 1.3.1 Integers (`int`)
- Arbitrary precision, 30-bit internal digits, no overflow, no separate BigInt; `sys.getsizeof` growth table.
- Literals: decimal, `0b`, `0o`, `0x`, underscores `1_000_000`.
- Operators `+ - * / // % **`; `/` always returns `float`; `//` floors and `%` takes the divisor's sign (`-7 // 2 == -4`, `-7 % 2 == 1`; JS gives `-1`).
- Functions and methods: `abs`, `divmod`, `pow(base, exp, mod)`, `round`, `bit_length`, `bit_count`, `to_bytes` / `from_bytes`, `bin` / `oct` / `hex`, `int(text, base)`, `is_integer`.
- Bitwise operators `& | ^ ~ << >>` with a permissions example.
- The 4300-digit string-conversion limit (`sys.set_int_max_str_digits`) and why it exists.

#### 1.3.2 Floating point (`float`)
- IEEE 754 double, identical to JS `number`; `0.1 + 0.2 != 0.3`; `math.isclose`.
- `round()` uses banker's rounding plus representation error (`round(2.675, 2) == 2.67`).
- Special values `inf`, `-inf`, `nan` (`nan != nan`, `math.isnan`, `math.isinf`).
- Methods: `as_integer_ratio`, `is_integer`, `hex` / `fromhex`; `sys.float_info`.
- Useful `math` functions: `floor`, `ceil`, `trunc`, `sqrt`, `fsum`, `prod`, `pi`, `e`.

#### 1.3.3 Exact decimals (`decimal.Decimal`)
- Construct from strings, never floats.
- Arithmetic; context precision with `localcontext()`.
- `quantize` with `ROUND_HALF_UP` vs `ROUND_HALF_EVEN`.
- Money calculations: 18% GST demo, float vs Decimal; performance trade-off.

#### 1.3.4 Rational numbers (`fractions.Fraction`)
- Exact arithmetic (`Fraction(1, 3) * 3 == 1`), construction from strings and floats, `limit_denominator`.

#### 1.3.5 Complex numbers (`complex`)
- `3 + 4j`, `.real`, `.imag`, `abs()`, `conjugate()`, `cmath` (brief).

#### 1.3.6 Booleans (`bool`)
- Subclass of `int` (`True + True == 2`, `sum(flags)`).
- The `isinstance(True, int)` validation trap; `bool()` conversion.

#### 1.3.7 The null value (`None`)
- The only `NoneType` instance; implicit return value; `is None` checks.
- JS bridge: no `undefined`; missing keys raise `KeyError`.

#### 1.3.8 Truthiness
- Complete falsy-values table: `None`, `False`, `0`, `0.0`, `0j`, `Decimal(0)`, `Fraction(0)`, `""`, `b""`, `[]`, `()`, `{}`, `set()`, `range(0)`, objects with `__bool__` / `__len__`.
- JS differences (`[]` and `{}` are truthy in JS); when to prefer `is not None`.

#### 1.3.9 Type conversion
- `int()`, `float()`, `str()`, `bool()`, `complex()`; what raises `ValueError` (`int("3.5")`).
- No implicit coercion: `1 + "1"` raises `TypeError`, `1 == "1"` is `False`.

#### Lab 1.3
1. `split_bill(total_amount: str, people_count: int) -> list[Decimal]` — exact paise split whose parts sum to the total.
2. An invoice calculator with `Decimal` and `ROUND_HALF_UP`, then the same with `float` to show drift.
3. Predict-the-output questions on `//`, `%`, `round` and truthiness.

### Unit 1.4 — Text and Binary Data Types

#### 1.4.1 Strings (`str`) fundamentals
- Immutable sequence of Unicode code points; single, double and triple quotes; raw strings `r"..."`; escape sequences (`\n`, `\t`, `\u20b9`).
- Indexing, negative indexing, slicing `[start:stop:step]`, reversal `[::-1]`; slices never raise `IndexError`.
- `len` counts code points (JS counts UTF-16 units — emoji demo); PEP 393 compact storage (1, 2 or 4 bytes per character).
- Concatenation `+`, repetition `*`, membership `in`, lexicographic comparison (`"10" < "9"`).

#### 1.4.2 String methods (complete API by group)
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

#### 1.4.3 String formatting
- f-strings: expressions, `=` debug specifier, `!r` / `!s` / `!a` conversions, nested fields, multi-line f-strings.
- Format-spec mini-language: fill/align (`<`, `>`, `^`), width, `,` and `_` separators, precision, types (`d`, `f`, `e`, `%`, `x`, `b`, `o`), sign, `#`, date formats (`%Y-%m-%d`).
- Legacy styles: `str.format`, `format_map`, `%` formatting, `string.Template`.
- Template strings / t-strings (3.14, PEP 750): `Template` objects, `.strings`, `.interpolations`, a safe HTML renderer.

#### 1.4.4 Unicode correctness
- Normalization with `unicodedata.normalize("NFC", ...)`, combining characters.
- `casefold` for comparisons (German ß), `unicodedata.name`.

#### 1.4.5 Bytes (`bytes`) and byte arrays (`bytearray`)
- Text vs binary; `b"..."` literals; indexing returns `int`; immutable `bytes` vs mutable `bytearray`.
- `encode("utf-8")` / `decode("utf-8")`; the `errors` argument (`strict`, `replace`, `ignore`, `backslashreplace`); UTF-8 as the default encoding (3.15, PEP 686).
- Methods shared with `str` (`split`, `replace`, `startswith`...), `hex()` / `bytes.fromhex()`.
- Why mixing `str` and `bytes` raises `TypeError`.

#### 1.4.6 Memory views (`memoryview`)
- Zero-copy slicing of binary buffers (brief; revisited in Phase 5).

#### 1.4.7 Real-world use cases
- Normalizing user input (usernames, emails, search queries).
- Parsing structured text: log lines, `key=value` configs, CSV fields with `split` / `partition`.
- Building reports and receipts with the format-spec mini-language; URL slugs.
- Safe HTML/SQL rendering with t-strings.
- `bytes` for network payloads, file signatures, hashing and base64 encoding.

#### Lab 1.4
1. `normalize_username(raw_username: str) -> str`.
2. `format_receipt_line(item_name, quantity, unit_price) -> str` with fixed-width alignment.
3. A text-normalization function for search input.

### Unit 1.5 — Collection Data Types I: Lists, Tuples and Ranges

#### 1.5.1 Common sequence operations
- Indexing, slicing, `in`, `len`, `+`, `*`, `min`, `max`, `count`, `index`.
- Support table across `list`, `tuple`, `str`, `range`, `bytes`.

#### 1.5.2 Lists (`list`) — internals
- Dynamic array of pointers; over-allocation (watch `sys.getsizeof` grow).
- Big-O: index O(1), `append` amortized O(1), `pop()` O(1), `pop(0)` / `insert(0, x)` O(n), `in` O(n), `sort` O(n log n).

#### 1.5.3 List methods (complete API)
- Adding: `append`, `extend`, `insert`, `+=` vs `+`.
- Removing: `remove` (first match, `ValueError`), `pop(index)`, `clear`, `del items[i]`, `del items[a:b]`.
- Searching: `index(x, start, end)`, `count`, `in`.
- Ordering: `sort(key=..., reverse=...)` vs `sorted()`, `reverse()` vs `reversed()`.
- Copying: `copy()`, `[:]`, `list(...)`.
- Slice assignment, extended-slice assignment, starred unpacking (`first, *rest = items`).

#### 1.5.4 Sorting in depth
- Timsort and stability; multi-pass sorting.
- `key=str.lower`, `operator.itemgetter` / `attrgetter`, tuple keys with negation for mixed directions.
- JS bridge: JS sorts numbers as strings by default.

#### 1.5.5 Tuples (`tuple`)
- The comma makes the tuple (`(1,)`); packing, unpacking, nested and starred unpacking, swap `a, b = b, a`.
- Methods `count`, `index`; hashable only if all items are; tuples as dict keys.
- Memory vs lists; the `t[0] += [1]` puzzle.

#### 1.5.6 Named tuples
- `collections.namedtuple` (`_replace`, `_asdict`, `_fields`, `_make`) and `typing.NamedTuple` with defaults and methods.

#### 1.5.7 Ranges (`range`)
- Lazy immutable sequence; O(1) `in`, `len`, indexing and slicing; negative steps.

#### 1.5.8 Arrays (`array.array`)
- Compact typed numeric storage vs a list of floats (memory comparison).

#### 1.5.9 Method reference — `list`
Every row gets a demo cell in the notebook.

| Method / operation | What it does | Returns | Cost |
| --- | --- | --- | --- |
| `append(x)` | add one item at the end | `None` | O(1) amortized |
| `extend(iterable)` / `+= iterable` | add every item of an iterable | `None` / same list | O(k) |
| `insert(i, x)` | insert before index `i` | `None` | O(n) |
| `remove(x)` | delete the first item equal to `x` (`ValueError` if absent) | `None` | O(n) |
| `pop()` / `pop(i)` | remove and return the last / i-th item (`IndexError` if empty) | item | O(1) / O(n) |
| `clear()` | remove every item | `None` | O(n) |
| `index(x[, start[, end]])` | position of the first `x` (`ValueError` if absent) | `int` | O(n) |
| `count(x)` | number of items equal to `x` | `int` | O(n) |
| `sort(*, key=None, reverse=False)` | stable in-place sort | `None` | O(n log n) |
| `reverse()` | reverse in place | `None` | O(n) |
| `copy()` | shallow copy (same as `[:]`, `list(x)`) | new `list` | O(n) |
| `items[i]`, `items[i] = x` | read / replace by index (negative indexes allowed) | item / — | O(1) |
| `items[a:b:c]`, `items[a:b] = iterable` | slice copy / slice replacement | new `list` / — | O(k) |
| `del items[i]`, `del items[a:b]` | delete by index or slice | — | O(n) |
| `x in items` | membership by `==` | `bool` | O(n) |
| `items + other`, `items * n` | concatenate / repeat into a new list | new `list` | O(n + m) |
| `len`, `min`, `max`, `sum`, `sorted`, `reversed`, `enumerate`, `any`, `all` | built-ins that work on lists | varies | O(n) |
| `==`, `<` | element-wise, lexicographic comparison | `bool` | O(n) |

#### 1.5.10 Method reference — `tuple`, `namedtuple` and `range`

| Type | Method / operation | What it does |
| --- | --- | --- |
| `tuple` | `count(x)`, `index(x[, start[, end]])` | the only two methods — tuples are immutable |
| `tuple` | indexing, slicing, `in`, `+`, `*`, `len`, comparison | same semantics as lists, but always returns new tuples |
| `tuple` | `hash(t)` | works when every item is hashable — enables dict keys and set members |
| `tuple` | unpacking `a, b = t`, `first, *rest = t` | the most common way to read tuples |
| `namedtuple` | `_make(iterable)`, `_asdict()`, `_replace(**changes)`, `_fields`, `_field_defaults` | construction, conversion, "modified copy", introspection |
| `range` | `start`, `stop`, `step`, `count(x)`, `index(x)` | attributes and O(1) arithmetic lookups |

#### 1.5.11 Real-world use cases
- `list` — shopping-cart items, a page of API results, rows read from a CSV, a stack (`append` + `pop`), ordered processing queues of moderate size.
- `tuple` — fixed records (database rows, `(latitude, longitude)`), returning several values from a function, composite dict keys like `(country, product)`, immutable constants.
- `namedtuple` / `NamedTuple` — lightweight read-only records with field names (parsed log lines, CSV rows).
- `range` — index loops, pagination offsets (`range(0, total, page_size)`), membership checks on numeric intervals.
- `array.array` — large numeric series (sensor readings) where memory matters.

#### Lab 1.5
1. Sort employee records by several keys (stable multi-pass and tuple keys).
2. `transpose(matrix)` with `zip(*matrix)`.
3. `dedupe_preserving_order(items)`.
4. Predict-the-output questions on aliasing (`[[0] * 3] * 3`).

### Unit 1.6 — Collection Data Types II: Dictionaries, Sets and the collections Module

#### 1.6.1 Dictionaries (`dict`) — internals
- Compact hash table (sparse indices + dense entries); insertion order guaranteed (3.7+).
- Open addressing with perturbed probing; resizing; key-sharing dicts (PEP 412).
- Mermaid diagram of the two arrays; `timeit` dict vs list membership.

#### 1.6.2 Hashing
- `hash()`; hashable = stable `__hash__` consistent with `__eq__`.
- `hash(1) == hash(1.0) == hash(True)`, so `{1: ..., True: ...}` has one key.
- Per-process string-hash randomization (`PYTHONHASHSEED`, hash-flooding DoS, SipHash).
- Unhashable types; tuple composite keys; a constant-`__hash__` class showing collision slowdown.
- Python has no separate "hash" type: `dict` is the hash map.

#### 1.6.3 Dictionary methods (complete API)
- Access: `d[key]` (`KeyError`), `get(key, default)`, `setdefault`, `in`.
- Modify: `d[key] = value`, `update` (mapping, pairs, kwargs), `|` and `|=`, `pop(key, default)`, `popitem()` (LIFO), `del d[key]`, `clear`.
- Views: `keys()`, `values()`, `items()` — live, with set operations on keys.
- Construction: literals, `dict(...)`, `dict.fromkeys` (shared-value trap), dict comprehensions, `zip` into `dict`.
- Copying: `copy()`, `{**d}`; `RuntimeError` when resizing during iteration.

#### 1.6.4 dict vs JS objects
- Comparison table with JS `Object` and `Map`: key types, coercion, prototype keys, order.
- `types.SimpleNamespace` for attribute-style access.

#### 1.6.5 Immutable mappings
- `frozendict` (3.15): hashable, usable as keys and constants, `|` returns a new one.
- `types.MappingProxyType` as a read-only live view.

#### 1.6.6 Sets (`set`) and frozen sets (`frozenset`)
- Hash table of keys; `{}` is a dict, use `set()`.
- `add`, `update`, `remove` vs `discard`, `pop`, `clear`.
- Operators `| & - ^` vs methods `union`, `intersection`, `difference`, `symmetric_difference` (accept any iterable).
- `issubset`, `issuperset`, `isdisjoint`; in-place variants; set comprehensions; `frozenset` as a dict key.

#### 1.6.7 The `collections` module
- `deque`: `append`, `appendleft`, `pop`, `popleft`, `extendleft`, `rotate`, `maxlen` ring buffers; O(1) vs `list.pop(0)` benchmark.
- `Counter`: counting, `most_common`, `update`, `subtract`, `total`, `elements`, arithmetic `+ - & |`.
- `defaultdict`: `default_factory`, nested defaultdicts, the `__missing__` hook behind it.
- `OrderedDict`: `move_to_end`, `popitem(last=False)`, order-sensitive equality.
- `ChainMap`: layered configuration lookups.

#### 1.6.8 Choosing a container
- Decision table: `list`, `tuple`, `NamedTuple`, `dict`, `set`, `frozenset`, `deque`, `Counter`, `defaultdict`, `frozendict`, `array`.

#### 1.6.9 Method reference — `dict`
Average costs; every row gets a demo cell.

| Method / operation | What it does | Returns | Cost |
| --- | --- | --- | --- |
| `d[key]` | read a value (`KeyError` if missing) | value | O(1) |
| `d[key] = value` | insert or replace | — | O(1) |
| `del d[key]` | delete (`KeyError` if missing) | — | O(1) |
| `key in d`, `len(d)`, `iter(d)` | membership on keys, size, iterate keys | `bool` / `int` / iterator | O(1) / O(1) / O(n) |
| `get(key, default=None)` | read without raising | value or default | O(1) |
| `setdefault(key, default=None)` | read, inserting `default` first if missing | value | O(1) |
| `pop(key[, default])` | remove and return (`KeyError` without default) | value | O(1) |
| `popitem()` | remove and return the last inserted pair | `(key, value)` | O(1) |
| `update(other=(), **kwargs)` | merge a mapping, pairs or keywords in place | `None` | O(k) |
| `d1 \| d2`, `d1 \|= d2` | merge into a new dict / in place (right wins) | new `dict` / same | O(n + m) |
| `keys()`, `values()`, `items()` | live views (keys/items support `&`, `\|`, `-`, `^`) | view | O(1) |
| `copy()` | shallow copy | new `dict` | O(n) |
| `clear()` | remove everything | `None` | O(n) |
| `dict.fromkeys(iterable, value=None)` | new dict, every key → the **same** value object | new `dict` | O(n) |
| `reversed(d)` | iterate keys newest-first | iterator | O(n) |
| `==` | equal if same key/value pairs (order ignored) | `bool` | O(n) |

#### 1.6.10 Method reference — `set` and `frozenset`

| Method | Operator | What it does | Mutates? |
| --- | --- | --- | --- |
| `add(x)` | — | add one element | yes |
| `remove(x)` / `discard(x)` | — | delete (`remove` raises `KeyError`, `discard` does not) | yes |
| `pop()` | — | remove and return an arbitrary element | yes |
| `clear()`, `copy()` | — | empty / shallow copy | yes / no |
| `union(*others)` | `a \| b` | elements in either | no |
| `intersection(*others)` | `a & b` | elements in both | no |
| `difference(*others)` | `a - b` | elements only in `a` | no |
| `symmetric_difference(other)` | `a ^ b` | elements in exactly one | no |
| `update`, `intersection_update`, `difference_update`, `symmetric_difference_update` | `\|=`, `&=`, `-=`, `^=` | in-place versions | yes |
| `issubset(other)` / `issuperset(other)` | `<=` / `>=` (`<`, `>` proper) | subset tests | no |
| `isdisjoint(other)` | — | no common elements | no |

Methods accept any iterable; operators require sets on both sides. `frozenset` has only the non-mutating methods and is hashable. `x in s` is O(1) on average.

#### 1.6.11 Method reference — `collections`

| Type | Key methods and attributes |
| --- | --- |
| `deque` | `append`, `appendleft`, `pop`, `popleft`, `extend`, `extendleft`, `rotate(n)`, `insert`, `remove`, `count`, `index`, `reverse`, `clear`, `copy`, `maxlen` |
| `Counter` | `most_common(n)`, `elements()`, `update`, `subtract`, `total()`, `+ - & \|`; missing keys count as 0 |
| `defaultdict` | `default_factory`, the `__missing__` hook; all `dict` methods |
| `OrderedDict` | `move_to_end(key, last=True)`, `popitem(last=True)`, order-sensitive `==` |
| `ChainMap` | `maps`, `new_child()`, `parents`; writes go to the first mapping |
| `namedtuple` | see 1.5.10 |

#### 1.6.12 Common dictionary patterns
- Counting (`Counter` vs `get(k, 0) + 1`); grouping (`defaultdict(list)`, `setdefault`).
- Indexing records by ID (`{row["id"]: row for row in rows}`); inverting a mapping; sorting by value.
- Safe nested access (`config.get("db", {}).get("port")`); merging with precedence.
- Filtering with dict comprehensions; iterating with `items()`; converting to and from JSON.

#### 1.6.13 Classic data structures with built-ins
- Stack (`list` `append` / `pop`), FIFO queue (`deque`), priority queue (`heapq` on a list).
- Sets for visited nodes; graphs as `dict[str, list[str]]` with BFS (`deque`) and DFS (explicit stack).
- A trie as nested dicts; a simple singly linked list with a small node class (preview of Phase 2).
- Big-O summary table for every operation used.

#### 1.6.14 Real-world use cases
- `dict` — parsed JSON payloads, lookup tables (country code → name), caches, config objects, routing/dispatch tables, records indexed by ID.
- `set` — deduplicating emails, permission/role checks, tags, comparing datasets (users in system A but not B), visited sets in graph traversal.
- `frozenset` / `frozendict` — cache keys, sets of sets, immutable configuration.
- `deque` — BFS queues, sliding windows, "last N events" history, rate-limiter timestamps.
- `Counter` — word frequencies, page-view analytics, inventory tallies.
- `defaultdict` — grouping orders by customer, building adjacency lists.
- `OrderedDict` — LRU caches; `ChainMap` — CLI > env > defaults configuration.

#### Lab 1.6
1. `group_orders_by_customer(orders)` with `defaultdict`.
2. `top_k_words(text, k)` — case- and punctuation-insensitive, ties alphabetical.
3. `merge_configs(defaults, env, cli)` with `ChainMap`.
4. `LRUCache(capacity)` on `OrderedDict`.
5. An order-analytics pipeline using `defaultdict`, `Counter`, `set`, `deque(maxlen=5)` and a `frozendict` catalog.

### Unit 1.7 — Copying: Shallow Copies, Deep Copies and Structured Clones

#### 1.7.1 Assignment vs copy
- Aliasing recap with `id` checks.

#### 1.7.2 Shallow copies
- `list.copy()`, `[:]`, `list(x)`, `dict.copy()`, `{**d}`, `set.copy()`, `copy.copy`.
- The outer container is new; inner objects are shared (demo with a nested config dict).

#### 1.7.3 Deep copies
- `copy.deepcopy`; the memo dict that preserves shared references and handles cycles (self-referencing list demo).

#### 1.7.4 Customizing copies
- `__copy__` and `__deepcopy__(self, memo)`; sharing expensive read-only parts deliberately.

#### 1.7.5 Limits and cost
- Objects that cannot be copied (locks, open files, sockets, generators).
- Shallow vs deep timing on 10,000 nested records.

#### 1.7.6 JS bridge: structuredClone
- Spread / `Object.assign` ↔ shallow copy; `structuredClone` ↔ `deepcopy` (`deepcopy` keeps class instances).
- Why `json.loads(json.dumps(x))` is the wrong deep copy (tuples, sets, `Decimal`, datetimes, int keys).

#### 1.7.7 Immutable snapshots
- Tuples, `frozenset` and `frozendict` as cheap alternatives to defensive copying.

#### Lab 1.7
1. `deep_merge(base, override)` that never mutates its inputs (verified with `is`).
2. Snapshot orders with `deepcopy` before applying discounts, then diff before/after.
### Unit 1.8 — Operators, Expressions and Control Flow

#### 1.8.1 Operators and precedence
- Arithmetic, comparison, logical, bitwise, membership (`in`), identity (`is`); precedence table.
- Chained comparisons `0 < age <= 120`.

#### 1.8.2 Boolean operators return operands
- `and` / `or` short-circuit like `&&` / `||`; `not` always returns `bool`.
- The `value or default` idiom and its `0` trap; no `??` (`x if x is not None else default`).

#### 1.8.3 Conditionals
- `if` / `elif` / `else`; conditional expression `a if condition else b`; guard clauses.

#### 1.8.4 Structural pattern matching (`match`)
- Literal, or (`|`), capture, wildcard `_`, sequence (`[cmd, *args]`), mapping (`{"type": t, **rest}`), class patterns with `__match_args__`, guards, `as` bindings.
- No fall-through; the bare-name capture trap and dotted-name constants; JS `switch` comparison.
- Demos: command parser, webhook router.

#### 1.8.5 Loops
- `for` over any iterable (no C-style loop), `while`, `break`, `continue`.
- `for ... else` / `while ... else` ("no break"); do-while emulation.

#### 1.8.6 Assignment forms
- Augmented assignment, multiple targets, unpacking, the walrus operator `:=` (PEP 572) and its scope rules.

#### 1.8.7 Unpacking operators
- `*` and `**` in calls, list/dict literals and assignment targets.

#### Lab 1.8
1. `parse_command(command_text)` with `match`.
2. `fizzbuzz(number)` with `match (number % 3, number % 5)`.
3. `find_first_duplicate(items)` with `for ... else`.

### Unit 1.9 — Iteration, Comprehensions and Built-in Functions

#### 1.9.1 The iteration protocol
- `iter()` + `next()` until `StopIteration`; the desugared `for` loop.
- `GET_ITER` / `FOR_ITER` in `dis`; `iter(callable, sentinel)` for chunked reading.

#### 1.9.2 Iteration helpers
- `enumerate(start=...)`, `zip(strict=True)`, `reversed`, `sorted`, `range`.

#### 1.9.3 Comprehensions
- List, dict and set comprehensions; filters; nested `for` order.
- Own scope (the loop variable does not leak); readability limits.

#### 1.9.4 Built-in functions catalogue
One table (signature, example, JS equivalent) plus a demo cell per group:

| Group | Functions |
| --- | --- |
| Numeric | `abs`, `round`, `divmod`, `pow`, `sum` (with `start`), `min`, `max` (with `key`, `default`) |
| Iteration | `len`, `iter`, `next` (with default), `map`, `filter`, `any`, `all`, `enumerate`, `zip`, `reversed`, `sorted` |
| Conversion | `int`, `float`, `str`, `bool`, `list`, `tuple`, `dict`, `set`, `frozenset`, `bytes`, `chr`, `ord`, `bin`, `hex`, `oct`, `format`, `repr`, `ascii` |
| Introspection | `type`, `isinstance`, `issubclass`, `id`, `hash`, `callable`, `dir`, `vars`, `globals`, `locals`, `getattr`, `setattr`, `hasattr`, `delattr`, `help` |
| I/O | `print` (`sep`, `end`, `file`, `flush`), `input`, `open` |
| Dangerous | `eval`, `exec`, `compile`; `ast.literal_eval` as the safe alternative |

#### 1.9.5 `map` / `filter` vs comprehensions
- Laziness, single use, readability; timing loop vs comprehension vs `map`.

#### 1.9.6 Pythonic idioms
- `enumerate` over `range(len())`, `zip` over parallel indexing, `in`, `any` / `all`, `dict.get`, EAFP preview.

#### Lab 1.9
1. `read_in_chunks(stream, size)` using `iter(callable, sentinel)`.
2. Rewrite five un-Pythonic loops idiomatically.
3. Summarize a batch of webhook events with `sum`, `max` and `sorted`.

### Unit 1.10 — Functions: Definition and Arguments

#### 1.10.1 `def` is an executable statement
- Functions are created at runtime (no hoisting: `NameError` demo); conditional definitions.
- Function attributes: `__name__`, `__qualname__`, `__doc__`, `__defaults__`, `__kwdefaults__`, `__code__`, `__globals__`, `__annotations__`, `__dict__`.

#### 1.10.2 Return values
- Implicit `None`, returning tuples and unpacking, guard clauses.

#### 1.10.3 Parameter kinds
- Positional-or-keyword, defaults, `*args` (tuple), keyword-only after `*`, positional-only before `/`, `**kwargs` (dict).
- Full signature order `def f(pos_only, /, standard, *, kw_only, **kwargs)`; why each kind exists.
- Reading kinds with `inspect.signature`.

#### 1.10.4 Argument unpacking
- `func(*values, **options)`; the forwarding wrapper `def wrapper(*args, **kwargs)`.

#### 1.10.5 Default values
- Evaluated once at definition; the mutable-default trap (`__defaults__` demo); the `None` pattern.
- `sentinel()` (3.15) to distinguish "not passed" from `None`; frozen `datetime.now()` defaults.

#### 1.10.6 First-class and higher-order functions
- Functions in variables, lists and dicts; callbacks; dispatch tables with `operator` functions.

#### 1.10.7 `lambda`
- Single expression, `key=` usage, `<lambda>` in tracebacks, when to prefer `def`.

#### 1.10.8 Docstrings and annotations
- PEP 257, Google style, `help()`; annotations are not enforced; lazy annotation evaluation (3.14, `annotationlib`).

#### 1.10.9 Recursion basics
- Base case, recursive vs iterative factorial, recursion-limit preview.

#### Lab 1.10
1. `build_query_string(base_url, /, *, page=1, page_size=20, **filters)`.
2. `apply_pipeline(value, *transforms)`.
3. `calculate(operation_name, left, right)` with a dispatch table.

### Unit 1.11 — Scope, Namespaces and Closures

#### 1.11.1 Namespaces
- Module, function, class and built-in namespaces; `globals()`, `locals()`, `builtins`.

#### 1.11.2 The LEGB rule
- Local → Enclosing → Global → Built-in (Mermaid diagram); shadowing built-ins (`list = [...]`).

#### 1.11.3 No block scope
- Names from `if` / `for` / `with` / `try` survive the block; comprehensions and lambdas do have scope.

#### 1.11.4 Compile-time scope decisions
- Any assignment makes a name local for the whole function; `UnboundLocalError`.
- `co_varnames` / `co_names`; `LOAD_FAST_CHECK` in `dis`.
- JS bridge: `var` hoisting and the `let` TDZ.

#### 1.11.5 `global` and `nonlocal`
- Rebinding vs mutating; why global state hurts testing.

#### 1.11.6 Closures
- Cell objects, `__closure__`, `cell_contents`, `co_freevars`, `co_cellvars`; `make_counter`, `make_multiplier`.

#### 1.11.7 Late binding
- `[lambda: i for i in range(3)]`; fixes with default arguments or `functools.partial`; JS bridge: `var` in loops.

#### 1.11.8 Name lookup cost
- `LOAD_FAST` vs `LOAD_GLOBAL` vs `LOAD_DEREF`; timing a local alias.

#### Lab 1.11
1. `make_rate_counter()` returning two closures sharing state.
2. Fix three buggy functions (mutable default, `UnboundLocalError`, late binding).
3. A closure-based field-validation system (`min_length(8)`, `matches_pattern(...)`, `one_of({...})`).

### Unit 1.12 — Decorators, functools and the Call Stack

#### 1.12.1 Decorator mechanics
- `@d` means `f = d(f)` at definition time; import-time execution.
- Stacking order (applied bottom-up, run top-down) with a sequence diagram.

#### 1.12.2 Writing decorators
- Wrapper with `*args, **kwargs`; `functools.wraps` and `__wrapped__`; returning results.

#### 1.12.3 Decorator factories
- Three-level `@retry(times=3)`; optional-argument decorators (`@timer` and `@timer(unit="ms")`).

#### 1.12.4 Stateful and class-based decorators
- Function attributes, closures, `__call__`; the method trap and the `__get__` fix.

#### 1.12.5 Decorating methods and classes
- Class decorators for registration.

#### 1.12.6 Real-world decorator gallery
- `timer`, `retry` with backoff and exception filter, `log_calls`, `require_role`, `validate_types`, `register`, `deprecated`, `memoize`.
- How `@app.get("/users")` works (registration decorator factory).

#### 1.12.7 `functools`
- `partial`, `partialmethod`, `cache`, `lru_cache` (`cache_info`, `cache_clear`, hashable arguments, memory risk on methods).
- `cached_property`, `reduce`, `singledispatch`, `total_ordering`, `update_wrapper`.

#### 1.12.8 `operator`
- `itemgetter`, `attrgetter` (dotted), `methodcaller`, operator functions; speed vs `lambda`.

#### 1.12.9 Frames and the call stack
- Frame objects (`f_code`, `f_locals`, `f_back`, `f_lineno`), `sys._getframe`, `inspect.stack`, `traceback.extract_stack`.
- JS bridge: execution contexts and the call stack.

#### 1.12.10 Recursion limits
- `sys.getrecursionlimit`, `RecursionError`, no tail-call optimization, explicit-stack rewrites.

#### 1.12.11 Introspecting callables
- `inspect.signature`, `Parameter`, `bind`, `apply_defaults`.
- A tiny dependency injector (the core idea behind FastAPI).

#### Lab 1.12
1. `@timer` with optional arguments.
2. `@retry(times, exceptions, backoff_factor)`.
3. `@count_calls`.
4. `@validate_arguments` using `inspect.signature`.
5. `serialize()` with `singledispatch`.
6. `call_with_params(func, params)`.
7. A mini router with `@router.get("/users/{user_id}")` and typed path params.

### Unit 1.13 — Iterators, Generators and itertools

#### 1.13.1 Iterable vs iterator
- `__iter__` / `__next__`; fresh iterators vs single-use iterators; JS `Symbol.iterator` comparison.

#### 1.13.2 Custom iterator classes
- Separating the iterable from its iterator; the `__getitem__` sequence fallback.

#### 1.13.3 Generator functions
- `yield`; lazy start; states (`inspect.getgeneratorstate`); suspended frames (`gi_frame`); `return` and `StopIteration.value`.

#### 1.13.4 Generator expressions
- Syntax, single use, memory vs list comprehensions (`sys.getsizeof`, `tracemalloc`).

#### 1.13.5 Lazy pipelines
- Chaining generators read → parse → filter → aggregate, with a pull-based diagram.

#### 1.13.6 `yield from`
- Delegation, recursive tree walks, capturing return values.

#### 1.13.7 Two-way generators
- `send`, priming, `throw`, `close`, `GeneratorExit`, cleanup in `finally`.

#### 1.13.8 From generators to async
- PEP 255 → 342 → 380 → 492; driving an `async def` coroutine by hand with `send`.

#### 1.13.9 The `itertools` module
- Infinite: `count`, `cycle`, `repeat`.
- Terminating: `accumulate`, `batched`, `chain`, `chain.from_iterable`, `compress`, `dropwhile`, `takewhile`, `filterfalse`, `groupby`, `islice`, `pairwise`, `starmap`, `tee`, `zip_longest`.
- Combinatoric: `product`, `permutations`, `combinations`, `combinations_with_replacement`.
- The itertools recipes and `more-itertools`.

#### Lab 1.13
1. Re-iterable `Countdown`.
2. `read_log_records(path)`.
3. `flatten(nested)`.
4. `running_average()` coroutine.
5. `paginate(fetch_page)`.
6. `sliding_windows(iterable, size)`.
7. Streaming analysis of a 1M-line log with a peak-memory comparison.

### Unit 1.14 — Exceptions and Context Managers

#### 1.14.1 The exception hierarchy
- `BaseException` vs `Exception`; key built-in exceptions (Mermaid tree); `__mro__` and what `except` matches.

#### 1.14.2 `try` / `except` / `else` / `finally`
- Execution-order table for every path; multiple clauses.
- Tuples and unparenthesized `except A, B:` (3.14); `as error` deletion.
- Bare `except:` dangers; `return` in `finally` (3.14 warning).

#### 1.14.3 Raising and chaining
- `raise`, bare re-raise, `raise ... from` (`__cause__`), implicit chaining (`__context__`), `from None`.

#### 1.14.4 Exception objects
- `args`, `__traceback__`, `add_note`, `traceback.format_exception`.

#### 1.14.5 Custom exception hierarchies
- An `AppError` base with `ValidationError` and `NotFoundError` carrying attributes and HTTP status codes.

#### 1.14.6 Exception groups
- `ExceptionGroup`, `except*`, `split`, `subgroup`.

#### 1.14.7 EAFP vs LBYL
- TOCTOU races; zero-cost `try` (3.11) measured; when LBYL is better.

#### 1.14.8 Logging exceptions
- `logger.exception`; never swallow errors.

#### 1.14.9 The `with` statement
- `__enter__` / `__exit__`, suppression by returning `True`, the desugared form, multiple managers.
- `Timer` and `DatabaseTransaction` examples.

#### 1.14.10 `contextlib`
- `@contextmanager` (with `try` / `finally`), `suppress`, `closing`, `redirect_stdout`, `nullcontext`, `chdir`, `ExitStack`, `AbstractContextManager`.

#### 1.14.11 `assert` and `warnings`
- `-O` strips asserts; `warnings.warn`, filters, `catch_warnings`, escalating to errors.

#### 1.14.12 Under the hood
- The exception table and `with` bytecode in `dis`.

#### Lab 1.14
1. `parse_age(text)` with notes and chaining.
2. `load_config(path)` converting errors with `from`.
3. A `StopwatchTimer` context-manager class.
4. `temporary_env(**variables)` with `@contextmanager`.
5. `open_many(paths)` with `ExitStack`.
6. `validate_records` raising an `ExceptionGroup` handled with `except*`.

### Phase 1 Project — Log Analyzer

- Generate a seeded synthetic access log (with malformed lines).
- Read it lazily with generators; parse with `re` and `match`.
- Collect `MalformedLineError`s without stopping.
- Aggregate status codes, top endpoints and p95 latency with `Counter`, `defaultdict` and `sorted`.
- Time the run with a context manager; wrap a flaky `upload_report()` in `@retry`.
- Print an aligned report.
- Close with 30 predict-the-output questions covering all of Phase 1.
---

## Phase 2 — Object-Oriented Programming and the Data Model

**Notebook:** `phase2_oop_data_model.ipynb`

**Outcome:** build classes that behave like built-ins, design with inheritance and composition, and understand the descriptor and metaclass machinery behind Pydantic, SQLAlchemy and dataclasses.

### Unit 2.1 — Classes and Instances

#### 2.1.1 Why classes
- Bundling state and behaviour; when functions, modules or dataclasses are better.

#### 2.1.2 The `class` statement
- The body executes in a namespace; `type(name, bases, namespace)` creates the class object; `ClassName.__dict__` (`mappingproxy`).

#### 2.1.3 Object creation
- `__new__` (allocate) then `__init__` (initialize); explicit `self`; `vars(instance)`, `instance.__class__`.

#### 2.1.4 Instance vs class attributes
- Lookup order instance → class → bases; shadowing.
- The shared mutable class-attribute trap; class constants and counters.

#### 2.1.5 Methods
- Bound methods (`__self__`, `__func__`).
- `@classmethod` alternative constructors (`from_dict`, subclass-aware); `@staticmethod`; decision table.

#### 2.1.6 Properties
- `@property` getters, setters, deleters; computed and read-only attributes; validation on assignment; uniform access principle.

#### 2.1.7 Encapsulation by convention
- `_internal`, name mangling of `__private`; JS `#private` comparison.

#### 2.1.8 JS bridge
- Classes vs prototypes; `self` vs `this`; bound methods need no `.bind`.

#### 2.1.9 The four pillars of OOP in Python
- Encapsulation (2.1.6–2.1.7), inheritance (2.2), polymorphism (2.3.4, 2.4), abstraction (2.3).
- How each looks in Python vs Java/TypeScript.

#### Lab 2.1
1. `BankAccount` with validated balance and transaction history.
2. `Temperature` with a `fahrenheit` property.
3. Subclass-aware `User.from_dict`.
4. `ShoppingCart` and `CartItem` with `Decimal` totals.

### Unit 2.2 — Inheritance, MRO and Composition

#### 2.2.1 Single inheritance
- Overriding, extending with `super().__init__`, `isinstance`, `issubclass`; everything inherits from `object`.

#### 2.2.2 `super()` in depth
- Zero-argument `super` and the `__class__` cell; "next in MRO", not "parent"; cooperative `**kwargs` passing.

#### 2.2.3 Multiple inheritance and the MRO
- C3 linearization worked step by step; `__mro__`; the diamond problem; inconsistent-MRO errors.

#### 2.2.4 Mixins
- `JsonSerializableMixin`, `TimestampMixin`, `ReprMixin`; base-class ordering; mixins in Django and DRF.

#### 2.2.5 Composition over inheritance
- Has-a vs is-a; delegation; refactoring a `Notifier` hierarchy; the Square/Rectangle Liskov violation.

#### 2.2.6 SOLID in Python
- One short example per principle.

#### Lab 2.2
1. Compute three MROs by hand and verify with `__mro__`.
2. A JSON mixin handling nested objects and datetimes.
3. Refactor an inheritance tree into composition.

### Unit 2.3 — Abstractions: ABCs, collections.abc and Protocols

#### 2.3.1 Abstract base classes
- `abc.ABC`, `@abstractmethod`, abstract properties, the template-method pattern.

#### 2.3.2 `collections.abc`
- `Iterable`, `Iterator`, `Sequence`, `Mapping`, `MutableMapping`, `Set`; mixin methods for free; `register` and `__subclasshook__`.

#### 2.3.3 Protocols (PEP 544)
- Structural typing like TypeScript interfaces; `@runtime_checkable` and its limits; Protocol vs ABC decision table.

#### 2.3.4 Duck typing and polymorphism
- EAFP over type checks.

#### Lab 2.3
1. `Shape` ABC with sorted subclasses.
2. `ReadOnlyView(Mapping)` implementing three methods.
3. A `SupportsClose` Protocol.
4. A payment-gateway abstraction with two providers behind a `PaymentProvider` Protocol.

### Unit 2.4 — The Data Model: Special (Dunder) Methods

#### 2.4.1 The data-model idea
| Syntax | Special method |
| --- | --- |
| `len(x)` | `__len__` |
| `x[i]` | `__getitem__` |
| `x + y` | `__add__` |
| `x()` | `__call__` |
| `for item in x` | `__iter__` |
| `item in x` | `__contains__` |
| `with x` | `__enter__` / `__exit__` |
| `hash(x)` | `__hash__` |
| `bool(x)` | `__bool__` |
| `format(x, spec)` | `__format__` |

#### 2.4.2 Representation
- `__repr__` vs `__str__`; `__format__` with custom specs.

#### 2.4.3 Equality and hashing
- `__eq__` returning `NotImplemented`; defining `__eq__` sets `__hash__ = None`; hashing immutable fields.

#### 2.4.4 Ordering
- Rich comparisons, reflection, `functools.total_ordering`.

#### 2.4.5 Truthiness and size
- `__bool__`, `__len__`.

#### 2.4.6 Container emulation
- `__getitem__` with ints and `slice`, `__setitem__`, `__delitem__`, `__contains__`, `__iter__`, `__reversed__`, `__missing__`.
- Why to subclass `UserDict` / `UserList` instead of `dict` / `list`.

#### 2.4.7 Callables
- `__call__` and stateful function objects.

#### 2.4.8 Numeric emulation
- `__add__`, `__radd__` (for `sum`), `__iadd__`, `__sub__`, `__mul__`, `__truediv__`, `__neg__`, `__abs__`, `__matmul__`.

#### 2.4.9 Special-method lookup
- Implicit calls look up the type, not the instance; `dis` of `BINARY_OP` and the `__add__` → `__radd__` sequence.

#### Lab 2.4
1. Immutable `Money` with currencies, formatting, ordering and `sum()` support.
2. `Vector2D`.
3. `Playlist` with slicing.
4. `CaseInsensitiveDict(UserDict)`.
5. A callable `RateLimiter`.
6. An `Inventory` collection keyed by SKU.

### Unit 2.5 — Attribute Access, Descriptors and Metaprogramming

#### 2.5.1 The attribute-lookup algorithm
- Data descriptors → instance `__dict__` → non-data descriptors / class attributes → `__getattr__` (Mermaid flowchart).

#### 2.5.2 Attribute hooks
- `__getattribute__` vs `__getattr__`, `__setattr__`, `__delattr__`; recursion traps; proxies and lazy loading.

#### 2.5.3 The descriptor protocol
- `__get__`, `__set__`, `__delete__`, `__set_name__`; data vs non-data descriptors; a reusable `PositiveNumber` descriptor.

#### 2.5.4 Descriptors inside Python
- How functions become bound methods; rebuilding `property`, `classmethod`, `staticmethod`.

#### 2.5.5 `__slots__`
- No per-instance `__dict__`; memory and speed on 1M instances; trade-offs.

#### 2.5.6 Classes as objects
- `type(name, bases, namespace)`; dynamic class creation.

#### 2.5.7 Metaclasses
- `__new__`, `__init__`, `__call__`, `__prepare__`; registries, interface enforcement, singletons; `ABCMeta`, `EnumMeta`.

#### 2.5.8 Lighter alternatives
- `__init_subclass__`, class decorators.

#### 2.5.9 How libraries do it
- Pydantic, SQLAlchemy, Django models, dataclasses.

#### Lab 2.5
1. Rebuild `property`.
2. `Typed` and `Bounded` descriptors.
3. A caching `LazyAttribute`.
4. A `PluginBase` registry with `__init_subclass__`.
5. A mini ORM with `Field` descriptors and `create_table_sql()`.

### Unit 2.6 — Dataclasses, Enums and Pythonic Design Patterns

#### 2.6.1 `@dataclass`
- Generated methods; `field()` options (`default_factory`, `repr`, `compare`, `init`, `kw_only`, `metadata`).
- `frozen`, `order`, `slots`, `kw_only`; `__post_init__` and `InitVar`.
- `asdict`, `astuple`, `replace`, `fields`; inheritance rules.

#### 2.6.2 Record-type comparison
- Dataclass vs `NamedTuple` vs `TypedDict` vs plain class vs Pydantic `BaseModel` vs attrs.

#### 2.6.3 `TypedDict`
- `Required`, `NotRequired`, `ReadOnly`, `total=False`; plain dicts at runtime.

#### 2.6.4 Enums
- `Enum`, `auto`, lookup by value and name, `IntEnum`, `StrEnum`, `Flag` / `IntFlag`, `@unique`.
- Methods on enums, enums in `match`, `_missing_`.

#### 2.6.5 Design patterns, Pythonic style
- Strategy, factory, singleton, registry, observer, adapter, builder, dependency injection, repository.
- Each shown non-Pythonic first, then Pythonic.

#### 2.6.6 Value objects vs entities

#### Lab 2.6
1. `Address` / `Customer` dataclasses with validation.
2. `OrderStatus(StrEnum)` with allowed transitions.
3. `Permission(Flag)`.
4. An `EventBus`.

### Phase 2 Project — Inventory Domain Model

- A frozen, slotted `Product` dataclass; `Money` from Unit 2.4.
- `StockMovement` with a `MovementType` enum; a `Warehouse` container class with dunders.
- An `InventoryRepository` Protocol with an in-memory implementation.
- An `InventoryService` receiving the repository by injection; custom exceptions.
- An event bus emitting low-stock alerts; a full demo script.

---

## Phase 3 — Python Internals: Memory, Bytecode and Imports

**Notebook:** `phase3_python_internals.ipynb`

**Outcome:** explain where an object's memory comes from and when it is freed, read bytecode fluently, and describe exactly what happens between `import x` and the first line of your code running.

### Unit 3.1 — Memory Management

#### 3.1.1 The memory model
- Frames on the call stack referencing objects on CPython's private heap; pointer-sized references.

#### 3.1.2 Object layout
- The `PyObject` header (`ob_refcnt`, `ob_type`), `PyVarObject.ob_size`, the GC header on containers; size table for common objects.

#### 3.1.3 Reference counting
- What increments and decrements counts; `sys.getrefcount` (+1).
- Deterministic deallocation shown with `weakref.finalize`.
- Reading a live refcount via `ctypes` (CPython-only, marked unsafe).

#### 3.1.4 Immortal objects (PEP 683)
- `None`, booleans, small ints, interned strings; `sys._is_immortal`.

#### 3.1.5 Reference counting in the free-threaded build
- Biased and deferred reference counting (overview).

#### 3.1.6 Reference cycles and the cyclic GC
- Why cycles leak under pure refcounting.
- `gc.collect`, `gc.is_tracked`, `gc.get_threshold`, `gc.get_count`, `gc.get_stats`, `gc.get_referrers`, `gc.get_referents`, `gc.freeze`, `gc.callbacks`.
- Generations; the `gc.disable` case study.

#### 3.1.7 Finalizers
- `__del__` semantics, resurrection, PEP 442; prefer context managers and `weakref.finalize`.

#### 3.1.8 Weak references
- `weakref.ref`, `WeakValueDictionary`, `WeakKeyDictionary`, `WeakSet`, `WeakMethod`; the `__weakref__` slot.

#### 3.1.9 The allocator
- pymalloc arenas → pools → blocks for objects ≤ 512 bytes; system `malloc` for larger.
- mimalloc in the free-threaded build; why RSS rarely shrinks; `sys._debugmallocstats()`.

#### 3.1.10 Free lists and caches
- Float/tuple/list free lists, small-int cache, empty-tuple singleton, interning; address reuse.

#### 3.1.11 Measuring memory
- Shallow `sys.getsizeof` vs recursive size; `tracemalloc` snapshots, statistics and diffs; process RSS; memray preview.

#### 3.1.12 Memory leaks in practice
- Unbounded caches, `lru_cache` on methods, captured closures, stored tracebacks, unremoved listeners, C-extension leaks.
- A diagnosis workflow.

#### 3.1.13 JS bridge
- V8's generational GC vs refcount + cycle GC; `WeakRef` / `FinalizationRegistry`.

#### Lab 3.1
1. `deep_getsizeof(obj)` with cycle handling.
2. Predict six refcounts, then verify.
3. Prove a cycle is freed only by `gc.collect`.
4. An `ImageCache` on `WeakValueDictionary`.
5. Find and fix a leaking `EventEmitter`.
6. Diagnose a leaking long-running worker with `tracemalloc`.

### Unit 3.2 — Bytecode and the Interpreter

#### 3.2.1 CPython architecture tour
- Parser, compiler, eval loop (`Python/ceval.c`), object implementations (`Objects/`).

#### 3.2.2 Tokens and the AST
- `tokenize`; `ast.parse`, node types, `ast.dump`, `ast.unparse`.

#### 3.2.3 Code objects
- `co_code`, `co_consts`, `co_names`, `co_varnames`, `co_freevars`, `co_cellvars`, `co_flags`, `co_qualname`, the exception table, `code.replace`.

#### 3.2.4 Function objects
- Code + globals + defaults + closure; `types.FunctionType`.

#### 3.2.5 Reading `dis`
- Columns; stack-machine walkthrough with a stack-state table; load/store families; calls; jumps; loops; `dis.get_instructions`.

#### 3.2.6 Compiler optimizations
- Constant folding, dead-code removal, constant tuples for `in` tests, comprehension inlining (PEP 709).

#### 3.2.7 The evaluation loop
- Frames, instruction pointer, inlined Python-to-Python calls (3.11).

#### 3.2.8 Specializing adaptive interpreter (PEP 659)
- Quickening, inline caches, specialized instructions, deoptimization.
- `dis.dis(func, adaptive=True)` before and after warming.

#### 3.2.9 The JIT
- Copy-and-patch design (PEP 744), micro-op traces, enabling and checking it on a 3.15 build.

#### 3.2.10 The GIL and the eval breaker
- Periodic checks; free-threaded design overview.

#### 3.2.11 `compile`, `exec`, `eval`
- Modes, namespaces, why `eval` on input is remote code execution, `ast.literal_eval`.

#### 3.2.12 AST transformation
- `NodeVisitor`, `NodeTransformer`, `fix_missing_locations`; how pytest rewrites asserts.

#### 3.2.13 `.pyc` files
- `py_compile`, `compileall`, header layout, `marshal`, invalidation modes.

#### 3.2.14 Other implementations
- PyPy, GraalPy, Cython-compiled modules.

#### Lab 3.2
1. Annotate a function's `dis` output with stack states.
2. `count_opcodes(func)`.
3. An AST lint rule for mutable defaults and bare `except`.
4. A `print` → `logger.info` transformer.
5. A safe arithmetic evaluator.
6. Observe specialization and deoptimization.
7. A code-quality scanner over a folder.

### Unit 3.3 — Modules, Packages and the Import System

#### 3.3.1 Modules as objects
- `ModuleType`, `__name__`, `__file__`, `__spec__`, `__loader__`, `__package__`, `__path__`.

#### 3.3.2 What `import` does
- `sys.modules` cache → `sys.meta_path` finders → loader → insert into `sys.modules` → execute → bind; `importlib.util.find_spec`.

#### 3.3.3 Import forms
- `import x`, `from x import y`, aliases, `from x import *` and `__all__`; copied bindings.

#### 3.3.4 Modules run once
- Import-time side effects, module singletons, `importlib.reload` caveats.

#### 3.3.5 `sys.path`
- How it is built, `site`, `.pth` files, `python -m` vs running a file, `python -P`.

#### 3.3.6 Packages
- `__init__.py`, re-exports, namespace packages (PEP 420), subpackages.

#### 3.3.7 Absolute vs relative imports

#### 3.3.8 Entry points
- `if __name__ == "__main__"`, `__main__.py`.

#### 3.3.9 Circular imports
- Reproducing the error; four fixes including `TYPE_CHECKING`.

#### 3.3.10 `importlib`
- `import_module`, `importlib.resources`, `importlib.metadata`, `pkgutil.iter_modules`, entry-point plugins.

#### 3.3.11 Import hooks
- Custom finders and loaders on `sys.meta_path`.

#### 3.3.12 Lazy imports (3.15)
- The `lazy` keyword; `importlib.util.LazyLoader`; measuring with `python -X importtime`.

#### 3.3.13 JS bridge
- `require` cache vs `sys.modules`; ESM live bindings vs copied bindings; `node_modules` resolution vs `sys.path`.

#### Lab 3.3
1. Build a `shop/` package and test its imports.
2. Fix a circular import three ways.
3. A plugin loader with `pkgutil`.
4. An in-memory `DictImporter`.
5. Read packaged data with `importlib.resources`.
6. Measure and reduce CLI startup with lazy imports.

### Phase 3 Project — Internals Toolkit

- A small `pyinspect` toolkit run with `python -m pyinspect`.
- A memory-profiler wrapper around `tracemalloc` reporting the top allocating lines of any callable.
- An AST-based code scanner.
- An import-time report.
---

## Phase 4 — Professional Python: Packaging, Typing, Testing and the Standard Library

**Notebook:** `phase4_professional_python.ipynb`

**Outcome:** ship a typed, tested, logged and installable package, and reach for the right standard-library or third-party module with confidence.

### Unit 4.1 — Package Management and Project Structure

#### 4.1.1 The ecosystem
- PyPI; wheels and their tags (`cp315-cp315-manylinux_x86_64`, `py3-none-any`, `t` for free-threaded); sdists.
- Build frontends vs backends (PEP 517/518); manylinux and `abi3`.

#### 4.1.2 pip
- The resolver, editable installs, `pip freeze` vs lockfiles, constraints files, the cache.

#### 4.1.3 uv in depth
- Global cache; `uv init --app / --lib / --package`.
- `uv add` with version specifiers, `--dev`, `--group`, `--optional`; `uv lock --upgrade-package`; `uv sync --frozen`.
- `uv tool` and `uvx`; PEP 723 inline-metadata scripts; workspaces; `uv export`; `uv build`; `uv publish`.

#### 4.1.4 `pyproject.toml` anatomy
- `[build-system]`, `[project]` (PEP 621), `[project.scripts]`, `[project.optional-dependencies]`, `[dependency-groups]` (PEP 735).
- Tool tables for uv, ruff, mypy, pytest.

#### 4.1.5 Version specifiers (PEP 440)
- `==`, `>=`, `~=`, `!=`, pre-releases, environment markers, extras.

#### 4.1.6 Lockfiles
- `uv.lock` and `pylock.toml` (PEP 751); pinning strategy for apps vs libraries.

#### 4.1.7 Project layouts
- Flat vs `src/`; editable-install mechanics; `__version__` via `importlib.metadata`.

#### 4.1.8 Building and publishing
- Wheel contents, TestPyPI, trusted publishing (OIDC), SemVer vs CalVer, changelogs.

#### 4.1.9 Supply-chain hygiene
- `pip-audit`, typosquatting, hash checking, `deptry`, licenses.

#### 4.1.10 Tool comparison
- pip + venv, pip-tools, Poetry, PDM, Hatch, Conda, uv — mapped to npm / yarn / pnpm.

#### Lab 4.1
1. Annotate every line of a `pyproject.toml`.
2. Build a `src/`-layout library with a console script, extras and dependency groups.
3. A PEP 723 single-file script run with `uv run`.
4. Build a wheel and inspect its contents.

### Unit 4.2 — The Type System (Python's TypeScript)

#### 4.2.1 Gradual typing
- PEP 484; static checkers vs runtime; nominal vs structural typing compared with TypeScript.

#### 4.2.2 Annotation syntax
- Variables, parameters, returns, `ClassVar`, `Final`; deferred evaluation (PEP 649/749) and `annotationlib`.

#### 4.2.3 Collection types
- `list[int]`, `dict[str, list[User]]`, `tuple[int, str]` vs `tuple[int, ...]`.
- Accept `collections.abc` types, return concrete ones.

#### 4.2.4 Unions and narrowing
- `X | None`; narrowing with `is None`, `isinstance`, `match`; `Never`, `NoReturn`, `assert_never`.

#### 4.2.5 Escape hatches
- `Any` vs `object`; `cast`; `# type: ignore[code]`.

#### 4.2.6 Precise types
- `Literal`, `LiteralString`, `Final`, `NewType`, `Self`.
- `TypedDict` (`Required`, `NotRequired`, `ReadOnly`, `Unpack` for `**kwargs`).

#### 4.2.7 Generics
- PEP 695 syntax for functions, classes and `type` aliases; bounds, constraints, defaults (PEP 696); variance; old `TypeVar` syntax.

#### 4.2.8 Callable types
- `Callable`, callback Protocols, `ParamSpec`, `Concatenate`, typing decorators, `@overload`.

#### 4.2.9 Class typing
- `type[T]`, `@override`, `@final`, generic Protocols.

#### 4.2.10 Custom narrowing
- `TypeIs` vs `TypeGuard`; discriminated unions.

#### 4.2.11 `Annotated` and runtime introspection
- Metadata for FastAPI / Pydantic; `get_type_hints(include_extras=True)`, `get_origin`, `get_args`.

#### 4.2.12 Running checkers
- mypy and pyright strict mode, configuration, `reveal_type`, stubs and `py.typed`, gradual adoption.

#### Lab 4.2
1. Add precise hints to 10 functions.
2. Generic `Stack[T]` and `Result[T, E]`.
3. A typed `@retry` with `ParamSpec`.
4. An `@overload`ed `parse_value`.
5. Fix 8 mypy errors in a provided module.
6. Type the Phase 2 model to pass `--strict`.
7. An `Annotated`-driven runtime validator.

### Unit 4.3 — Testing, Debugging and Logging

#### 4.3.1 Testing strategy
- Test pyramid; unit vs integration vs end-to-end; Arrange-Act-Assert; Jest/Vitest ↔ pytest.

#### 4.3.2 pytest fundamentals
- Discovery, assertion rewriting, `pytest.raises`, `pytest.approx`, CLI flags (`-k`, `-x`, `-v`, `--lf`, `-s`); running from notebooks.

#### 4.3.3 Fixtures
- Scopes, `yield` teardown, `conftest.py`, `autouse`, factory fixtures, built-ins (`tmp_path`, `monkeypatch`, `capsys`, `caplog`).

#### 4.3.4 Parametrization and markers
- `parametrize` with ids, `skip`, `skipif`, `xfail`, custom markers.

#### 4.3.5 Test doubles
- `Mock`, `MagicMock`, `AsyncMock`, `side_effect`, call assertions, `patch` (where the name is looked up), `autospec`.
- Fakes vs stubs vs mocks; freezing time.

#### 4.3.6 Coverage
- Line vs branch coverage, thresholds, limits.

#### 4.3.7 Property-based testing
- Hypothesis strategies and shrinking.

#### 4.3.8 Debugging
- `breakpoint()`, pdb commands, post-mortem (`pdb.pm`, `%debug`, `pytest --pdb`), IDE debuggers, `faulthandler`.

#### 4.3.9 Logging architecture
- Logger hierarchy, levels, handlers (`StreamHandler`, `RotatingFileHandler`, `QueueHandler`), formatters, filters, propagation, `dictConfig`.
- Library rules (`NullHandler`); `logger.exception`; lazy `%s` formatting; `LoggerAdapter`; JSON logs.

#### 4.3.10 Quality gates
- ruff rules and formatting, pre-commit, a GitHub Actions CI workflow.

#### Lab 4.3
1. Parametrized tests for `Money`.
2. Repository fixtures.
3. Mock an HTTP client.
4. Hypothesis tests for `split_bill`.
5. A `dictConfig` with JSON output.
6. A pdb debugging walkthrough.
7. A 90%+ coverage suite for the Phase 2 model.

### Unit 4.4 — Standard Library Essentials

#### 4.4.1 Paths and the OS
- `pathlib` (joining, parts, `glob`, `rglob`, `walk`, `read_text`, `write_text`, `resolve`, `stat`), `os`, `sys`, `shutil`.
- `os.path` → `pathlib` mapping table.

#### 4.4.2 Processes
- `subprocess.run` (capture, `check`, `timeout`), `Popen`, the `shell=True` injection risk.

#### 4.4.3 Dates and times
- Naive vs aware datetimes, `zoneinfo` (`Asia/Kolkata`), UTC storage, `timedelta`, DST pitfalls, ISO 8601, `strftime` / `strptime`.
- `time.monotonic` vs `perf_counter`.

#### 4.4.4 Regular expressions (`re`)
- `match` / `search` / `fullmatch`, `findall` / `finditer`, groups and named groups, lazy quantifiers, anchors, flags, `VERBOSE`, lookarounds.
- `sub` with functions; catastrophic backtracking; JS regex differences.

#### 4.4.5 Data formats
- `json` (custom encoders, `object_hook`, `parse_float=Decimal`); `csv` (`DictReader`, `DictWriter`, `newline=""`).

#### 4.4.6 Algorithm helpers
- `heapq` (priority queues, `nlargest`), `bisect`, `statistics`, `math`, `graphlib.TopologicalSorter`.

#### 4.4.7 Randomness and security
- `random` (seeded, `choices`, `sample`, `shuffle`) vs `secrets`.
- `hashlib`, `hmac` (webhook signatures), `uuid4` vs `uuid7` (3.14), `base64`, `urllib.parse`.

#### 4.4.8 Command-line interfaces
- `argparse` with subcommands; `typer` / `click` mentioned (Unit 4.6).

#### 4.4.9 Text utilities
- `textwrap`, `string.Template`, `difflib`, `pprint`.

#### Lab 4.4
1. `find_large_files(root, min_size_mb)`.
2. A `VERBOSE` nginx-log regex with named groups.
3. IST/UTC conversion including a DST case.
4. HMAC webhook verification.
5. Top-K with `heapq`.
6. Build-step ordering with `graphlib`.
7. A file-organizer CLI with `--dry-run`.

### Unit 4.5 — File I/O, Encodings and Serialization

#### 4.5.1 `open()` in depth
- Modes, the I/O stack (`FileIO` → `BufferedReader` → `TextIOWrapper`), buffering, encodings, newline handling.

#### 4.5.2 Reading and writing patterns
- Line iteration, chunked binary reads, `seek` / `tell`, `flush` / `fsync`, atomic writes with `os.replace`.

#### 4.5.3 In-memory and temporary files
- `StringIO`, `BytesIO`, `tempfile`.

#### 4.5.4 Binary formats
- `struct`, endianness, parsing a PNG header, `memoryview`, `mmap`.

#### 4.5.5 Encodings
- UTF-8, UTF-16, latin-1, BOMs, mojibake, error handlers.

#### 4.5.6 Serialization formats
- JSON, CSV, TOML (`tomllib`), YAML (`safe_load`), XML (`defusedxml`), msgpack / orjson.

#### 4.5.7 `pickle`
- Protocols, `__reduce__`, `__getstate__` / `__setstate__`, the remote-code-execution risk (harmless demo), legitimate uses.

#### 4.5.8 Compression and archives
- `gzip`, `bz2`, `lzma`, `compression.zstd` (3.14), `zipfile`, `tarfile` with `filter="data"`.

#### 4.5.9 `sqlite3`
- Connections, parameterized queries, `executemany`, transactions, `sqlite3.Row`, SQL injection demo.

#### 4.5.10 File-system safety
- Path-traversal checks with `Path.is_relative_to`.

#### Lab 4.5
1. `tail(path, n)` reading backwards with `seek`.
2. Atomic `write_json(path, data)`.
3. A CSV → SQLite importer.
4. A binary header parser with `struct`.
5. A JSON encoder for `Decimal`, `datetime`, `UUID` and dataclasses.
6. Safe zip extraction that rejects path traversal.

### Unit 4.6 — Essential Third-Party Libraries

#### 4.6.1 Choosing a library
- Maintenance activity, download stats, type hints (`py.typed`), license, security advisories, dependency weight; reading docs and source.

#### 4.6.2 HTTP and resilience
- `requests` (sessions, timeouts, `raise_for_status`), `httpx` (sync and async, shared client), `tenacity` (retry policies, backoff, stop conditions).

#### 4.6.3 Validation and configuration
- Pydantic v2 outside web frameworks (parsing API responses, config files), `pydantic-settings`, `python-dotenv`.

#### 4.6.4 Command-line apps
- `typer` (type-hint-driven CLIs), `click`, `rich` (tables, progress bars, pretty tracebacks, logging handler).

#### 4.6.5 Dates and serialization
- `python-dateutil` (parsing, relative deltas), `orjson` and `msgspec` for fast JSON.

#### 4.6.6 Data analysis
- NumPy arrays; pandas and Polars basics (read CSV, filter, group-by, join, write Parquet); when to use which.

#### 4.6.7 Parsing and scraping
- BeautifulSoup and `lxml` for HTML/XML; respecting robots.txt and rate limits.

#### 4.6.8 Templating
- Jinja2 templates (variables, loops, filters, inheritance, autoescaping) for emails and HTML reports.

#### 4.6.9 Files, images and cloud storage
- Pillow (resize, thumbnails, formats); `boto3` for S3-compatible storage (upload, download, presigned URLs).

#### 4.6.10 Developer utilities
- `loguru` vs stdlib logging, `attrs`, `more-itertools`, `cachetools`.

#### Lab 4.6
1. A `typer` + `rich` CLI that fetches data with `httpx` and `tenacity`, validates it with Pydantic, analyses it with Polars, prints a `rich` table and renders a Jinja2 HTML report.

### Phase 4 Project — Publish the Log Analyzer

- Turn the Phase 1 log analyzer into a package published to TestPyPI.
- `src/` layout, `mypy --strict` clean, pytest + Hypothesis at 90%+ coverage, `dictConfig` logging.
- An `argparse` CLI with subcommands, `.gz` input support, CSV / JSON / SQLite export.
- A GitHub Actions workflow with trusted publishing.

---

## Phase 5 — Concurrency, Async and Performance

**Notebook:** `phase5_concurrency_performance.ipynb`

**Outcome:** choose threads, processes, subinterpreters or asyncio for a workload and justify it with a benchmark; explain the asyncio event loop as precisely as Node's; profile and optimize CPU and memory.

### Unit 5.1 — Concurrency Fundamentals, Threads and the GIL

#### 5.1.1 Core concepts
- Concurrency vs parallelism; CPU-bound vs I/O-bound; latency numbers; processes vs threads vs coroutines comparison table.

#### 5.1.2 `threading.Thread`
- Creation, `start`, `join`, `daemon`, names and IDs; subclassing vs `target`.

#### 5.1.3 The Global Interpreter Lock
- What it protects, why it exists, when it is released (I/O, `sleep`, C extensions), the switch interval.
- CPU-bound vs I/O-bound benchmarks.

#### 5.1.4 Race conditions
- Non-atomic `counter += 1` (shown in `dis`), check-then-act races, what is atomic.

#### 5.1.5 Synchronization primitives
- `Lock`, `RLock`, `Semaphore`, `BoundedSemaphore`, `Event`, `Condition`, `Barrier`, `Timer`; deadlocks and prevention.

#### 5.1.6 Thread-safe queues
- `queue.Queue`, `LifoQueue`, `PriorityQueue`, `task_done` / `join`, sentinel shutdown.

#### 5.1.7 Thread-local state
- `threading.local`.

#### 5.1.8 `concurrent.futures.ThreadPoolExecutor`
- `submit`, `Future`, `map`, `as_completed`, `wait`, sizing, shutdown, exceptions.

#### 5.1.9 Errors and shutdown
- `threading.excepthook`, daemon threads, stop flags.

#### 5.1.10 Free-threaded Python
- PEP 703 / 779, `python3.15t`, `sys._is_gil_enabled()`, compatibility, benchmarks.

#### 5.1.11 JS bridge
- libuv thread pool and `worker_threads`.

#### Lab 5.1
1. Prove a race condition and fix it.
2. Producer–consumer with `Queue`.
3. A thread-pool downloader.
4. A semaphore-capped connection pool.
5. Reproduce and fix a deadlock.
6. GIL vs free-threaded CPU benchmark.

### Unit 5.2 — Multiprocessing and Subinterpreters

#### 5.2.1 Processes
- Separate memory and GIL; creation cost.

#### 5.2.2 Start methods
- `fork`, `spawn`, `forkserver` (POSIX default since 3.14); the main guard.
- Notebook caveat: worker functions must live in importable modules.

#### 5.2.3 Process APIs
- `Process`; `Pool` (`map`, `imap_unordered`, `starmap`, `chunksize`); `ProcessPoolExecutor` (`max_tasks_per_child`, `initializer`).

#### 5.2.4 Data transfer
- Pickling constraints and cost; when parallel is slower.

#### 5.2.5 IPC
- `Queue`, `Pipe`, `Value`, `Array`, `Manager`, `shared_memory` with NumPy.

#### 5.2.6 Subinterpreters
- `concurrent.interpreters` (PEP 734), `InterpreterPoolExecutor`.

#### 5.2.7 Choosing a model
- Decision matrix and Amdahl's law.

#### 5.2.8 Patterns
- Map-reduce, chunking, `KeyboardInterrupt` handling, `os.process_cpu_count()`.

#### Lab 5.2
1. Parallel hashing with processes vs threads, with the result explained.
2. A `chunksize` tuning chart.
3. Shared-memory array workers.
4. Map-reduce word counts with measured speedup vs Amdahl's prediction.

### Unit 5.3 — asyncio Internals: the Event Loop

#### 5.3.1 Why async
- The C10k problem; blocking vs non-blocking I/O; cooperative multitasking.

#### 5.3.2 OS foundations
- Non-blocking sockets, `select` / `epoll` / `kqueue` / IOCP, the `selectors` module.

#### 5.3.3 A toy event loop from scratch
- Round-robin generator scheduler → timer heap for `sleep` → I/O waiting with `selectors` → an echo server.

#### 5.3.4 Native coroutines
- `async def`, lazy coroutine objects, awaitables (coroutines, Tasks, Futures, `__await__`), driving a coroutine with `send`.

#### 5.3.5 What `await` does
- Suspension up to the Task, Future callbacks, resumption (Mermaid sequence diagram).

#### 5.3.6 The asyncio loop
- Ready queue, scheduled-timer heap, selector; one `_run_once` iteration; `call_soon`, `call_later`, `call_at`, `loop.time`.

#### 5.3.7 Futures and Tasks
- `create_task`, eager task factory, keeping task references.

#### 5.3.8 Core API
- `asyncio.run`, `Runner`; sequential `await` vs `create_task` vs `gather`; `sleep(0)`; `wait_for`; top-level `await` in Jupyter.

#### 5.3.9 JS bridge, in depth
- Node phases and microtasks vs asyncio's single ready queue; eager Promises vs lazy coroutines.
- `Promise.all` / `race` / `allSettled`, `setTimeout`, `setImmediate` equivalents.

#### 5.3.10 Function colors
- Sync/async boundaries.

#### Lab 5.3
1. Drive a coroutine by hand.
2. Add `gather` to the toy loop.
3. Turn 5 s of sequential sleeps into 1 s of concurrent ones.
4. `race(coroutines)`.
5. Eight event-loop ordering puzzles.
6. An asyncio chat server with streams.

### Unit 5.4 — asyncio in Production

#### 5.4.1 Structured concurrency
- `TaskGroup`, `ExceptionGroup`, `except*`, `as_completed`.

#### 5.4.2 Timeouts and cancellation
- `asyncio.timeout`, `CancelledError` semantics, cleanup, `shield`.

#### 5.4.3 Coordination
- `Event`, `Lock`, `Condition`, `Semaphore`, `Barrier`.

#### 5.4.4 Queues and worker pools
- `asyncio.Queue`, backpressure, `Queue.shutdown()` (3.13), pipelines.

#### 5.4.5 Async protocols
- `async with`, `asynccontextmanager`, `async for`, async generators, `aclosing`.

#### 5.4.6 Blocking the loop
- Detection with debug mode; fixes with `to_thread`, `run_in_executor`, async libraries.

#### 5.4.7 `contextvars`
- Request-scoped state and log correlation.

#### 5.4.8 HTTP clients
- Shared `httpx.AsyncClient`, limits, timeouts; `aiohttp`.

#### 5.4.9 Rate limiting and retries
- Async token bucket; backoff with jitter.

#### 5.4.10 Performance and testing
- `uvloop`; pytest-asyncio / anyio, `AsyncMock`, `httpx.MockTransport`.

#### 5.4.11 Interop
- `run_coroutine_threadsafe`; anyio and trio.

#### Lab 5.4
1. `fetch_all(urls, max_concurrency)`.
2. An async worker pool with graceful shutdown.
3. `retry_async`.
4. An async paginator.
5. Find a hidden blocking call.
6. Request-ID propagation with `contextvars`.
7. An API aggregator over 500 mocked endpoints.

### Unit 5.5 — Performance and Memory Optimization

#### 5.5.1 Method
- Measure first; Amdahl; benchmark hygiene; `pyperf`.

#### 5.5.2 Timing
- `timeit`, `%timeit`, `perf_counter`.

#### 5.5.3 CPU profiling
- `cProfile` + `pstats` + snakeviz, `py-spy`, the Tachyon sampling profiler (3.15), `line_profiler`, scalene; reading flame graphs.

#### 5.5.4 Memory profiling
- `tracemalloc`, memray; peak vs current.

#### 5.5.5 Algorithmic optimization
- Right data structures, removing quadratic loops, `heapq`, `bisect`, memoization.

#### 5.5.6 Interpreter-level optimization
- Local aliases, built-ins in C, `join`, comprehensions, avoiding exceptions in hot paths, type-stable code.

#### 5.5.7 Memory-lean data
- `__slots__`, `array`, `memoryview`, generators, interning.

#### 5.5.8 Caching
- `lru_cache` hit rates, TTL caches, invalidation.

#### 5.5.9 Vectorization
- NumPy arrays, broadcasting, ufuncs; pandas vs Polars.

#### 5.5.10 Native code
- Cython, Rust via PyO3 / maturin, CFFI / ctypes, Numba, mypyc, PyPy.

#### 5.5.11 Free-threading and JIT effects
- Benchmarking on 3.15t and a JIT build.

#### 5.5.12 Production performance
- Sampling in production, continuous profiling, `pytest-benchmark` in CI.

#### Lab 5.5
1. Profile and fix a slow function.
2. Rewrite an O(n²) algorithm as O(n).
3. A micro-optimization timing table.
4. NumPy vectorization.
5. A 5× peak-memory reduction.

### Phase 5 Project — 10× Faster Sales Report

- Start from a deliberately slow sales-report script: 1M generated rows, nested loops, repeated scans, string concatenation, float money, sequential simulated network waits.
- Make it at least 10× faster with 3× less peak memory.
- Document every step (change → time → memory → reason), including one concurrency step.
---

## Phase 6 — Web Development with FastAPI

**Notebook:** `phase6_web_fastapi.ipynb`

Application code lives in `projects/notes_api/`. Write it from the notebook with `%%writefile` cells, test it in-notebook with `TestClient` / `httpx.AsyncClient`, and serve it from a terminal.

**Outcome:** build, secure, test, observe and deploy a FastAPI service, and explain every layer from the TCP socket to the response model.

### Unit 6.1 — HTTP and the Python Web Stack from Scratch

#### 6.1.1 Networking basics
- TCP/IP, ports, DNS, TLS overview; the `socket` API.

#### 6.1.2 HTTP/1.1 anatomy
- Request and status lines, headers, bodies, CRLF.
- Method semantics (safe, idempotent); status-code classes and common codes (401 vs 403, 409, 422, 429).
- Key headers; keep-alive; chunked encoding; content negotiation; HTTP/2 and HTTP/3 overview.

#### 6.1.3 REST design
- Resources, verbs ↔ CRUD, statelessness, pagination and filtering conventions, versioning, idempotency keys.
- REST vs RPC vs GraphQL.

#### 6.1.4 A raw socket HTTP server
- Hand-parsed requests, routing, JSON.
- Blocking vs thread-per-connection vs asyncio-streams versions, benchmarked.

#### 6.1.5 WSGI (PEP 3333)
- `app(environ, start_response)`, middleware, Gunicorn, limitations.

#### 6.1.6 ASGI
- `app(scope, receive, send)`; http, websocket and lifespan scopes; streaming with `more_body`; ASGI middleware; Uvicorn.

#### 6.1.7 Framework landscape
- Flask, Django, Starlette, FastAPI, Litestar; Express mapping.

#### 6.1.8 HTTP clients
- `urllib`, `requests`, `httpx` (sync/async, HTTP/2), `aiohttp`; client reuse, timeouts, retries, streaming.

#### Lab 6.1
1. Parse a raw HTTP request into a dataclass.
2. A raw socket server with routing, JSON and 404 handling.
3. A WSGI timing middleware.
4. A raw ASGI app with a streaming endpoint.
5. A ~150-line ASGI micro-framework compared with the FastAPI equivalent.

### Unit 6.2 — FastAPI Fundamentals and Pydantic v2

#### 6.2.1 Architecture
- Starlette + Pydantic + OpenAPI; request lifecycle diagram.

#### 6.2.2 Path operations
- Decorators per method, typed path params, Enum params, path converters, route ordering.

#### 6.2.3 Query parameters
- Defaults, optional, lists, `Annotated[int, Query(ge=1, le=100)]`, query-parameter models.

#### 6.2.4 Request bodies
- Pydantic models, mixing sources, `Body(embed=True)`.

#### 6.2.5 Pydantic v2 models
- Field types (`EmailStr`, `HttpUrl`, `UUID`, `Decimal`, `datetime`, `Literal`, nested models); `Field` constraints.
- `field_validator`, `model_validator`, `computed_field`.
- `model_dump` options, `model_validate` / `model_validate_json`.
- `ConfigDict` (`extra="forbid"`, `frozen`, `from_attributes`, `str_strip_whitespace`); camelCase alias generators.
- Strict vs lax mode, `TypeAdapter`, `ValidationError.errors()`, `Annotated` custom types.

#### 6.2.6 Schema design
- Separate Create / Update / Read schemas; PATCH with `exclude_unset`.

#### 6.2.7 Responses
- `response_model`, status codes, response classes (`JSONResponse`, `StreamingResponse`, `FileResponse`, `RedirectResponse`), headers and cookies, `HTTPException`.

#### 6.2.8 `async def` vs `def` handlers
- The thread pool for sync handlers; a blocking demo under load.

#### 6.2.9 OpenAPI
- `/docs`, `/redoc`, metadata, examples, generating a TypeScript client.

#### 6.2.10 How FastAPI uses Python
- `inspect.signature`, `Annotated`, decorators and Pydantic internals.

#### Lab 6.2
1. Notes API v1 — CRUD with Create/Update/Read schemas.
2. Validated filtering and pagination parameters.
3. A `UserRegistration` model with cross-field validation.
4. A PATCH endpoint.
5. A blocking-vs-async benchmark.

### Unit 6.3 — Dependency Injection and Application Structure

#### 6.3.1 `Depends`
- Parameterized and nested dependencies, per-request caching, class dependencies, `Annotated` aliases; resolution graph diagram.

#### 6.3.2 `yield` dependencies
- Setup/teardown, exception handling, teardown order.

#### 6.3.3 Dependency scopes
- App-, router- and route-level dependencies; `dependency_overrides`.

#### 6.3.4 Project structure
- `create_app()` factory, routers, schemas, models, services, repositories, core config; dependency direction.

#### 6.3.5 `APIRouter`
- Prefixes, tags, versioning.

#### 6.3.6 Configuration
- `pydantic-settings`, `.env`, `SecretStr`, a cached settings dependency.

#### 6.3.7 Middleware
- `BaseHTTPMiddleware` vs pure ASGI; timing; request IDs with `contextvars`; GZip; ordering.

#### 6.3.8 CORS
- Preflight requests and `CORSMiddleware` configuration.

#### 6.3.9 Error handling
- Domain-exception handlers, validation-error override, RFC 9457 Problem Details.

#### 6.3.10 Lifespan
- Shared resources (engine, HTTP client, Redis) on `app.state`.

#### 6.3.11 Requests, headers, cookies, forms and uploads
- `UploadFile`, size and type validation.

#### 6.3.12 Pagination
- Offset vs keyset cursors; generic `Page[T]`.

#### 6.3.13 Server-rendered pages
- `Jinja2Templates`, `StaticFiles`, forms with redirects, HTMX partial updates.
- When to choose Django + DRF or GraphQL (Strawberry) instead.

#### Lab 6.3
1. Notes API v2 — layered structure and settings.
2. A router-level API key.
3. Request-ID and timing middleware.
4. Problem Details errors.
5. A lifespan-managed HTTP client.
6. Uploads and cursor pagination.

### Unit 6.4 — Databases with SQLAlchemy 2.0

#### 6.4.1 Relational design
- Keys, normalization, indexes, constraints, transactions, isolation levels, `EXPLAIN ANALYZE`; PostgreSQL in Docker Compose.

#### 6.4.2 Drivers and pooling
- psycopg 3, asyncpg.

#### 6.4.3 SQLAlchemy architecture
- Engine, Connection, Core vs ORM.

#### 6.4.4 Typed ORM models
- `DeclarativeBase`, `Mapped`, `mapped_column`, relationships (one-to-many, many-to-many), mixins, naming conventions.

#### 6.4.5 Sessions
- Unit of work, identity map, `flush` vs `commit`, object states.

#### 6.4.6 Querying
- `select`, `where`, joins, aggregates, subqueries, `update` / `delete` statements, bulk inserts.

#### 6.4.7 Loading strategies
- N+1 detection, `selectinload`, `joinedload`, `raiseload`.

#### 6.4.8 Async SQLAlchemy
- `create_async_engine`, `AsyncSession`, pool sizing.

#### 6.4.9 FastAPI integration
- Session dependency, transaction per request, repositories, ORM → Pydantic.

#### 6.4.10 Alembic
- Autogenerate, review, upgrade/downgrade, data migrations, expand/contract.

#### 6.4.11 Concurrency control
- Optimistic locking, `with_for_update`, `IntegrityError` → 409, savepoints.

#### 6.4.12 Alternatives
- SQLModel, raw asyncpg, document databases; Redis data types.

#### Lab 6.4
1. Notes API v3 on PostgreSQL with typed models and many-to-many tags.
2. Eight queries with the emitted SQL printed.
3. Detect and fix an N+1 problem.
4. Three Alembic migrations.
5. An optimistic-locking conflict returning 409.
6. Indexed search and keyset pagination.

### Unit 6.5 — Authentication, Authorization and Security

#### 6.5.1 AuthN vs AuthZ
- Sessions vs tokens; threat modelling.

#### 6.5.2 Password storage
- Argon2id via `pwdlib`, rehashing, constant-time comparison.

#### 6.5.3 JWT
- Structure, claims, HS256 vs RS256/EdDSA, PyJWT, algorithm-confusion attacks.

#### 6.5.4 Token lifecycle
- Access + rotating refresh tokens, reuse detection, revocation, logout.

#### 6.5.5 FastAPI security
- `OAuth2PasswordBearer`, login form, current-user dependencies, `HTTPBearer`, `APIKeyHeader`.

#### 6.5.6 Authorization
- Roles, OAuth2 scopes (`Security`, `SecurityScopes`), ownership checks, 404 vs 403.

#### 6.5.7 Browser security
- Cookie flags, CSRF, CORS.

#### 6.5.8 Third-party login
- OAuth 2.0 Authorization Code + PKCE, OpenID Connect, Authlib.

#### 6.5.9 API keys and rate limiting
- Hashed keys, Redis rate limiters, 429 with `Retry-After`.

#### 6.5.10 OWASP API Security Top 10 (2023)
- Each risk with its FastAPI mitigation.

#### 6.5.11 Injection, headers and secrets
- SQL / command injection, HSTS, CSP, secret management, `bandit`, `pip-audit`, log redaction.

#### Lab 6.5
1. A hand-built JWT, then the same with PyJWT.
2. Register / login / refresh / logout / me endpoints.
3. Roles and scopes with 401/403 tests.
4. A BOLA test.
5. Login rate limiting.
6. A log redaction filter.

### Unit 6.6 — Background Jobs, Real-Time and Caching

#### 6.6.1 `BackgroundTasks`
- Uses and limits.

#### 6.6.2 Task queues
- Broker/worker architecture; Celery; ARQ, Dramatiq, Taskiq comparison.

#### 6.6.3 Reliability
- Idempotency, retries, dead-letter queues, transactional outbox, scheduled jobs and locks.

#### 6.6.4 WebSockets
- Handshake, `@app.websocket`, connection managers, authentication, heartbeats, Redis fan-out.

#### 6.6.5 Server-Sent Events
- Event-stream format, `StreamingResponse`, `Last-Event-ID`, `EventSource`; SSE vs WebSockets vs polling; LLM token streaming.

#### 6.6.6 HTTP caching
- `Cache-Control`, `ETag`, 304 responses.

#### 6.6.7 Application caching with Redis
- Cache-aside, TTLs, key design, invalidation, stampede protection.

#### 6.6.8 Messaging
- Redis pub/sub vs Streams; outgoing signed webhooks.

#### Lab 6.6
1. Notes API v5 — ARQ notification jobs.
2. WebSocket live updates.
3. SSE export progress.
4. Redis caching with a measured hit rate.
5. ETags and 304 responses.
6. An outbox relay worker.

### Unit 6.7 — API Testing and Observability

#### 6.7.1 Test architecture
- `TestClient` vs `AsyncClient` + `ASGITransport`, async test configuration, `dependency_overrides`.

#### 6.7.2 Database tests
- Testcontainers, rollback-per-test, factories.

#### 6.7.3 External services
- `respx` / `MockTransport`; testing WebSockets, jobs and streams.

#### 6.7.4 Contract and fuzz testing
- Schemathesis; OpenAPI snapshot tests.

#### 6.7.5 Observability fundamentals
- Logs, metrics, traces; SLIs/SLOs; RED and USE.

#### 6.7.6 Structured logging
- structlog, request and trace IDs, redaction.

#### 6.7.7 Metrics
- Prometheus counters, gauges, histograms; multiprocess mode.

#### 6.7.8 Tracing
- OpenTelemetry auto-instrumentation and exporters.

#### 6.7.9 Error tracking and health checks
- Sentry; liveness, readiness and startup probes.

#### Lab 6.7
1. Notes API v6 — full test suite in CI with service containers.
2. A Schemathesis run.
3. Correlated JSON logs.
4. Latency histograms.
5. OpenTelemetry spans.
6. Health endpoints.

### Unit 6.8 — Deployment and Operations

#### 6.8.1 Process model
- Uvicorn workers vs Gunicorn + Uvicorn workers; sizing; DB pool × workers.

#### 6.8.2 Containers
- Multi-stage Dockerfile with uv, non-root user, image size.

#### 6.8.3 Docker Compose stacks
- api, worker, postgres, redis, migrations job, proxy.

#### 6.8.4 Configuration and secrets
- 12-factor practice.

#### 6.8.5 Reverse proxy and TLS
- Caddy / Nginx / Traefik, proxy headers, WebSocket proxying.

#### 6.8.6 CI/CD
- GitHub Actions: lint, type-check, test, build, scan, push, deploy.

#### 6.8.7 Migrations on deploy
- One-off jobs, expand/contract.

#### 6.8.8 Deployment targets
- VM, PaaS, Cloud Run / ECS, Kubernetes basics.

#### 6.8.9 Zero downtime and scaling
- Graceful shutdown, rolling / blue-green / canary releases, stateless scaling, PgBouncer, CDNs.

#### 6.8.10 Load testing and readiness
- Locust, capacity planning, production checklist.

#### Lab 6.8
1. An optimized multi-stage Dockerfile.
2. A Compose stack with health checks.
3. A TLS reverse-proxy config.
4. A CI/CD pipeline.
5. A graceful-shutdown test.
6. A Locust report at p95 < 200 ms.

### Phase 6 Project — Notes API in Production

- The Notes API built across Units 6.2–6.8, deployed to a real host with HTTPS, CI/CD, migrations, monitoring and a written load-test report.

---

## Capstone Project — Team Task Tracker API

**Notebook:** `capstone_task_tracker.ipynb` (design docs, diagrams, demo calls, test and load-test results). Application code lives in `projects/task_tracker/`.

### Product specification

- **Users and teams:** registration and login (JWT + rotating refresh), teams, email invites via signed links, per-team roles (owner, admin, member).
- **Projects and tasks:** tasks with title, description, status (`StrEnum`), priority, assignee, due date, labels (many-to-many), comments and an activity log.
- **Features:** filtering, sorting, search, keyset pagination, bulk status updates, attachments, optimistic locking, soft delete.
- **Async features:** ARQ notification jobs, a daily digest cron job, a WebSocket live board, SSE export progress, Redis caching.
- **Non-functional targets:** read p95 < 150 ms at 200 RPS, 85%+ coverage, `mypy --strict` clean, structured logs + metrics + traces, OWASP checklist passed, zero-downtime deploys.

### Milestones

1. **Design and core** — requirements, ER diagram, endpoint table, architecture diagram; models, migrations, repositories, services, schemas; CRUD with tests.
2. **Security and async** — auth and team-role authorization with BOLA tests; ARQ worker with a transactional outbox; WebSocket board; SSE exports; caching and rate limiting.
3. **Quality and shipping** — unit, integration and Schemathesis tests; observability; Dockerfile, Compose, CI/CD, TLS deployment, Locust report; README with ADRs and a runbook; a retrospective mapping each phase's concepts to the codebase.

---

## Appendix A — Dependencies by Phase

| Phase | Packages (`uv add`) |
| --- | --- |
| 0–3 | `jupyterlab`, `ipykernel`, `jupytext`, `nbformat`, `nbconvert` |
| 4 | `pytest`, `pytest-cov`, `hypothesis`, `mypy`, `pyright`, `ruff`, `pre-commit`, `pyyaml`, `pip-audit`, `requests`, `httpx`, `tenacity`, `pydantic`, `pydantic-settings`, `python-dotenv`, `typer`, `rich`, `python-dateutil`, `orjson`, `numpy`, `pandas`, `polars`, `beautifulsoup4`, `lxml`, `jinja2`, `pillow`, `boto3`, `loguru`, `attrs`, `more-itertools`, `cachetools` |
| 5 | `httpx`, `aiofiles`, `uvloop`, `numpy`, `line-profiler`, `memray`, `scalene`, `snakeviz`, `py-spy` |
| 6 | `fastapi[standard]`, `pydantic-settings`, `sqlalchemy[asyncio]`, `asyncpg`, `alembic`, `pyjwt`, `pwdlib[argon2]`, `redis`, `arq`, `structlog`, `prometheus-client`, `opentelemetry-sdk`, `anyio`, `respx`, `testcontainers`, `schemathesis`, `locust`, `python-multipart` |

## Appendix B — JS → Python Concept Map

| JS concept | Python equivalent | Where taught |
| --- | --- | --- |
| V8, Ignition bytecode, TurboFan | CPython bytecode, specializing interpreter, JIT | 1.1, 3.2 |
| Execution contexts and the call stack | Frame objects (`sys._getframe`, `inspect.stack`) | 1.12.9 |
| Hoisting and the TDZ | No hoisting; compile-time locals and `UnboundLocalError` | 1.10.1, 1.11.4 |
| Lexical scope and closures | LEGB, `nonlocal`, cell objects | 1.11 |
| Functions as first-class citizens | Same, plus decorators | 1.10.6, 1.12 |
| Primitives vs objects | Everything is an object; immutability by type | 1.2 |
| `structuredClone`, spread | `copy.deepcopy`, shallow copies | 1.7 |
| `Array`, `Object` / `Map`, `Set` | `list`, `dict`, `set` | 1.5, 1.6 |
| Iterators, `function*` | Iterator protocol, generators | 1.13 |
| `try/catch`, `AggregateError` | `try/except`, `ExceptionGroup` | 1.14 |
| Prototypes, `this`, classes | Classes, MRO, descriptors, `self` | 2.1–2.5 |
| TypeScript | Type hints, mypy/pyright, Pydantic at runtime | 4.2, 6.2 |
| npm, `package.json`, lockfile | uv, `pyproject.toml`, `uv.lock` | 0.3, 4.1 |
| Single thread + event loop by default | Synchronous by default; asyncio opt-in | 5.3 |
| Microtasks / macrotasks | Ready queue + timer heap | 5.3.6, 5.3.9 |
| Web APIs / libuv thread pool | `selectors`, `to_thread`, `run_in_executor` | 5.3.2, 5.4.6 |
| Promises, `Promise.all` | Futures/Tasks, `gather`, `TaskGroup` | 5.3.7, 5.4.1 |
| `worker_threads`, `cluster` | `threading`, free-threading, `multiprocessing`, subinterpreters | 5.1, 5.2 |
| Node + Express | ASGI + Uvicorn + FastAPI | 6.1–6.3 |
