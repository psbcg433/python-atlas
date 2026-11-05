# Phase 1 Study Notes — Python Language Fundamentals

[Index](README.md) · [Next →](unit-1-1-how-python-executes-code.md)

These notes are the textbook version of the Phase 1 notebook,
`notebooks/phase1_language_fundamentals.ipynb`. They cover the same fourteen units,
in the same order, but they are written to be **read**, on a phone or anywhere
else, without running anything. Each topic is explained in prose first (what it is,
why it exists, how CPython does it under the hood, and how it differs from
JavaScript), then shown in code with the real output that code printed on
CPython 3.15.

The intended reader already knows JavaScript or TypeScript well. Every unit opens
with a bridge table that maps familiar JavaScript ideas onto their Python
counterparts and points out the difference that bites.

## How to use these notes

- **Read in order the first time.** Later units lean on earlier ones: copying (1.7)
  only makes sense after names and mutability (1.2), and decorators (1.12) build on
  closures (1.11).
- **Predict before you peek.** Predict-the-output questions hide their answers in
  collapsible *Answer* blocks. Decide what the code prints first, then open the
  answer.
- **Try the labs.** Each lab gives a problem, test cases and hints. The reference
  solution is in a collapsible *Solution* block; attempt the problem in the notebook
  (or a REPL) before opening it.
- **Revise with the recap tables.** Every unit ends with a recap table
  (Concept, Takeaway, JavaScript equivalent), and the
  [cheat sheet](cheatsheet.md) gathers every method and syntax form on one page.
- **Run the code when in doubt.** Every example is runnable with
  `uv run python` from the repository root. Values such as `id()` numbers, memory
  addresses and timings vary from run to run; the notes point these out.

Conventions used throughout:

| Marker | Meaning |
| --- | --- |
| ` ```python ` block | Code you can run |
| ` ```text ` block | What that code printed |
| **Note** callout | A detail worth remembering |
| **Warning** callout | A common pitfall |
| *Answer* / *Solution* | Collapsible; tap to open |
| "New in 3.x" | Feature newer than Python 3.12 |

## Reading order

```text
1.1 How Python executes code
 └─ 1.2 Objects, names, mutability
     ├─ 1.3 Numbers and booleans
     ├─ 1.4 Text and binary
     ├─ 1.5 Lists, tuples, ranges
     │   └─ 1.6 Dicts, sets, collections
     │       └─ 1.7 Copying
     └─ 1.8 Operators and control flow
         └─ 1.9 Iteration and built-ins
             └─ 1.10 Functions
                 └─ 1.11 Scope and closures
                     └─ 1.12 Decorators and the call stack
                         └─ 1.13 Iterators and generators
                             └─ 1.14 Exceptions and context managers
                                 └─ Project: log analyzer
```

## Contents

| Unit | Title | Topics |
| --- | --- | --- |
| 1.1 | [How Python Executes Code](unit-1-1-how-python-executes-code.md) | Bytecode, AST, `dis`, `.pyc` caching, statements vs expressions |
| 1.2 | [Objects, Names and Mutability](unit-1-2-objects-names-and-mutability.md) | Objects, binding, call by object reference, `is` vs `==` |
| 1.3 | [Numeric and Boolean Data Types](unit-1-3-numeric-and-boolean-data-types.md) | `int`, `float`, `Decimal`, `Fraction`, `complex`, `bool`, `None`, truthiness |
| 1.4 | [Text and Binary Data Types](unit-1-4-text-and-binary-data-types.md) | `str` API, formatting, Unicode, `bytes`, `bytearray`, `memoryview` |
| 1.5 | [Lists, Tuples and Ranges](unit-1-5-collection-data-types-i-lists-tuples-and-ranges.md) | List internals and API, sorting, tuples, named tuples, `range`, `array` |
| 1.6 | [Dictionaries, Sets and collections](unit-1-6-collection-data-types-ii-dictionaries-sets-and-the-collections-module.md) | Hashing, `dict` and `set` APIs, `Counter`, `deque`, `defaultdict` |
| 1.7 | [Copying](unit-1-7-copying-shallow-copies-deep-copies-and-structured-clones.md) | Shallow and deep copies, `__deepcopy__`, `structuredClone` bridge |
| 1.8 | [Operators, Expressions and Control Flow](unit-1-8-operators-expressions-and-control-flow.md) | Precedence, `and`/`or`, `match`, loops, unpacking |
| 1.9 | [Iteration, Comprehensions and Built-ins](unit-1-9-iteration-comprehensions-and-built-in-functions.md) | Iteration protocol, comprehensions, built-in functions |
| 1.10 | [Functions: Definition and Arguments](unit-1-10-functions-definition-and-arguments.md) | Parameter kinds, defaults, `lambda`, annotations, recursion |
| 1.11 | [Scope, Namespaces and Closures](unit-1-11-scope-namespaces-and-closures.md) | LEGB, `global`, `nonlocal`, closures, late binding |
| 1.12 | [Decorators, functools and the Call Stack](unit-1-12-decorators-functools-and-the-call-stack.md) | Decorators, `functools`, `operator`, frames, `inspect` |
| 1.13 | [Iterators, Generators and itertools](unit-1-13-iterators-generators-and-itertools.md) | Generators, `yield from`, `send`, lazy pipelines, `itertools` |
| 1.14 | [Exceptions and Context Managers](unit-1-14-exceptions-and-context-managers.md) | `try` forms, chaining, exception groups, `with`, `contextlib` |
| Project | [Log Analyzer](project-log-analyzer.md) | Case study using all of Phase 1, plus 30 review questions |
| — | [Cheat Sheet](cheatsheet.md) | One-page revision tables for every type and syntax form |

## Where this fits

Phase 1 is the language core. Phase 2 (object-oriented programming and the data
model) turns the behaviour you learn to predict here (`len()`, `in`, `with`,
iteration) into behaviour you can give your own classes.

[Index](README.md) · [Next →](unit-1-1-how-python-executes-code.md)
