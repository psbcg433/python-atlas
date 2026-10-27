"""Unit 0.1 — Python, the Language and Its Implementations."""

from nbformat import NotebookNode

from nb_builder import code, md, predict_cells


def cells() -> list[NotebookNode]:
    """Return the cells for Unit 0.1."""
    return [
        md(
            """
            ## Unit 0.1 — Python, the Language and Its Implementations

            **Objectives**

            - Separate *Python the language* (a specification) from *CPython the program* that runs it.
            - Know the yearly release cycle and how long each version is supported.
            - Ask a running interpreter exactly which version and implementation it is.

            **JS bridge**

            | JavaScript concept | Python equivalent | The difference that bites |
            | --- | --- | --- |
            | ECMAScript specification | The Python Language Reference | Python's reference is less formal; CPython's behaviour is the de-facto spec for edge cases |
            | V8, SpiderMonkey, JavaScriptCore | CPython, PyPy, MicroPython, GraalPy | Almost everyone runs CPython; in JS the engine depends on the browser or runtime |
            | `process.version` (Node) | `sys.version`, `sys.version_info` | `sys.version_info` is a tuple you can compare, not a string |
            | `process.execPath` | `sys.executable` | Tells you *which* interpreter (and so which environment) runs your code |
            """
        ),
        md(
            """
            ### 0.1.1 Language vs implementation

            *Python* is a language defined by the
            [Python Language Reference](https://docs.python.org/3/reference/index.html) plus the
            [standard library docs](https://docs.python.org/3/library/index.html). Programs that read
            and execute Python source are **implementations**:

            | Implementation | Written in | Execution strategy | Typical use |
            | --- | --- | --- | --- |
            | **CPython** | C | Compiles to bytecode, runs it in an interpreter loop (with an experimental JIT since 3.13) | The reference implementation; what `python.org` and `uv` install |
            | **PyPy** | RPython (a Python subset) | Tracing JIT compiler | Long-running pure-Python code that needs speed |
            | **MicroPython** | C | Compact bytecode VM | Microcontrollers (ESP32, Raspberry Pi Pico) |
            | **GraalPy** | Java on GraalVM | JIT via the Truffle framework | Embedding Python in JVM applications |

            The JavaScript parallel is exact: **ECMAScript** is the specification, and **V8**
            (Chrome, Node, Deno), **SpiderMonkey** (Firefox) and **JavaScriptCore** (Safari, Bun) are
            engines that implement it.

            > **Note:** this course targets CPython. "Under the hood" sections describe CPython
            > internals, which other implementations are free to do differently.

            The cell below asks the running interpreter which implementation it is.
            """
        ),
        code(
            """
            import platform
            import sys

            implementation_name = sys.implementation.name
            print(f"{implementation_name=}")
            print(f"{platform.python_implementation()=}")
            """
        ),
        md(
            """
            #### Under the hood: `sys.implementation`

            `sys.implementation` is a namespace object every implementation must provide
            ([PEP 421](https://peps.python.org/pep-0421/)). `vars()` exposes its attributes as a dict.
            Notice `cache_tag`: it is the suffix CPython puts on files in `__pycache__`
            (for example `module.cpython-315.pyc`), so two different interpreters never read each
            other's bytecode. `hexversion` packs the version into one integer, which is handy for
            fast comparisons in C extensions.
            """
        ),
        code(
            """
            import sys

            for attribute_name, attribute_value in vars(sys.implementation).items():
                print(f"{attribute_name:32} {attribute_value!r}")

            print(f"{sys.hexversion=:#x}")
            """
        ),
        md(
            """
            ### 0.1.2 Release cycle

            Since [PEP 602](https://peps.python.org/pep-0602/), CPython ships **one feature release
            every October**. Each release gets:

            - about **2 years of bugfix releases** (3.15.1, 3.15.2, …), then
            - **security-only releases** until **5 years** after the first release.

            | Version | Released | Bugfix support ends | End of life |
            | --- | --- | --- | --- |
            | 3.12 | October 2023 | April 2025 (18 months under the earlier rule) | October 2028 |
            | 3.13 | October 2024 | October 2026 | October 2029 |
            | 3.14 | October 2025 | October 2027 | October 2030 |
            | 3.15 | October 2026 | October 2028 | October 2031 |

            The live table is on the [devguide versions page](https://devguide.python.org/versions/);
            the 3.15 schedule is [PEP 790](https://peps.python.org/pep-0790/).

            **Why this course targets 3.15.** It is the newest stable release, so it has the longest
            support window and the newest features. Two that matter later in the course:

            | Feature | PEP | Version label |
            | --- | --- | --- |
            | UTF-8 mode is on by default (`open()` without `encoding=` uses UTF-8 on every OS) | [PEP 686](https://peps.python.org/pep-0686/) | New in 3.15 |
            | Explicit lazy imports with the `lazy import` statement | [PEP 810](https://peps.python.org/pep-0810/) | New in 3.15 |

            The next cell computes the support windows from the PEP 602 rule instead of hard-coding
            them.
            """
        ),
        code(
            '''
            def support_window(minor_version: int) -> tuple[int, int]:
                """Return (bugfix_end_year, end_of_life_year) for 3.<minor_version> under PEP 602."""
                release_year = 2023 + (minor_version - 12)  # 3.12 shipped in October 2023
                return release_year + 2, release_year + 5


            for minor_version in range(12, 16):
                bugfix_end_year, end_of_life_year = support_window(minor_version)
                print(f"3.{minor_version}: bugfix until ~{bugfix_end_year}, security until {end_of_life_year}")
            '''
        ),
        md(
            """
            **New in 3.15 — UTF-8 mode by default.** `sys.flags.utf8_mode` is `1` on 3.15 even
            without `-X utf8`. On older versions it is usually `0` (except where the locale is
            `C`/`POSIX`). The cell is guarded so it prints a skip message on an older kernel.
            """
        ),
        code(
            """
            import locale
            import sys

            if sys.version_info >= (3, 15):
                print(f"{sys.flags.utf8_mode=}")
                print(f"{locale.getpreferredencoding(False)=}")
            else:
                print(f"Skipped: UTF-8 mode default needs Python 3.15, this is {sys.version_info[:2]}")
            """
        ),
        md(
            """
            ### 0.1.3 Inspecting the interpreter

            Five attributes answer "what exactly is running my code?". Each gets its own cell.

            | Expression | Returns | Use it for |
            | --- | --- | --- |
            | `sys.version` | human-readable string (version, build date, compiler) | logs and bug reports |
            | `sys.version_info` | named tuple `(major, minor, micro, releaselevel, serial)` | version checks in code |
            | `sys.implementation.name` | lower-case name, e.g. `'cpython'` | implementation-specific branches |
            | `platform.python_implementation()` | display name, e.g. `'CPython'` | reports |
            | `sys.executable` | absolute path of the interpreter binary | finding which environment is active |

            `sys.version` is a free-form string: print it, but never parse it.
            """
        ),
        code(
            """
            import sys

            print(sys.version)
            """
        ),
        md(
            """
            `sys.version_info` is a named tuple. Index it, unpack it, or read fields by name.
            Comparing it to a plain tuple is the idiomatic version check.
            """
        ),
        code(
            """
            import sys

            print(f"{sys.version_info=}")
            print(f"{sys.version_info.major=}, {sys.version_info.minor=}, {sys.version_info.micro=}")
            print(f"{sys.version_info >= (3, 12)=}")
            """
        ),
        md(
            """
            `sys.implementation.name` is the machine-friendly identifier (always lower case).
            """
        ),
        code(
            """
            import sys

            print(f"{sys.implementation.name=}")
            """
        ),
        md(
            """
            `platform.python_implementation()` returns the display name of the same thing.
            """
        ),
        code(
            """
            import platform

            print(f"{platform.python_implementation()=}")
            print(f"{platform.python_version()=}")
            """
        ),
        md(
            """
            `sys.executable` is the path of the interpreter binary. In this notebook it should point
            inside the project's `.venv/`, which proves the kernel uses the project environment.
            The exact path depends on your machine and OS.
            """
        ),
        code(
            """
            import sys
            from pathlib import Path

            print(f"{sys.executable=}")
            print(f"{'.venv' in Path(sys.executable).parts=}")
            """
        ),
        md("#### Predict the output"),
        *predict_cells(
            snippet="""
            import sys
            print(sys.version_info >= (3, 15), (3, 9) < (3, 15), "3.9" < "3.15")
            """,
            answer="""
            `True True False`. Tuples compare element by element as numbers, so `(3, 9) < (3, 15)`
            is `True`. Strings compare character by character: `"9"` is greater than `"1"`, so
            `"3.9" < "3.15"` is `False`. This is why you compare `sys.version_info`, never
            `sys.version`.
            """,
            proof="""
            import sys

            print(sys.version_info >= (3, 15), (3, 9) < (3, 15), "3.9" < "3.15")
            """,
        ),
        *predict_cells(
            snippet="""
            import sys
            version_pair = sys.version_info[:2]
            print(type(version_pair).__name__, version_pair)
            """,
            answer="""
            `tuple (3, 15)`. Slicing the named tuple returns a plain `tuple`, not another
            `version_info` object, so the field names are gone.
            """,
            proof="""
            import sys

            version_pair = sys.version_info[:2]
            print(type(version_pair).__name__, version_pair)
            """,
        ),
        md(
            """
            ### Recap — Unit 0.1

            | Concept | One-line takeaway | JS equivalent |
            | --- | --- | --- |
            | Language vs implementation | Python is a spec; CPython is the C program that runs it | ECMAScript vs V8 |
            | Other implementations | PyPy (JIT), MicroPython (devices), GraalPy (JVM) | SpiderMonkey, JavaScriptCore, QuickJS |
            | Release cycle | One release every October, about 2 years of bugfixes, 5 years total | Node's even-numbered LTS lines |
            | `sys.version_info` | Compare it to tuples for version checks | `process.versions.node` (a string) |
            | `sys.implementation` | Name, cache tag and version of the running implementation | `process.release.name` |
            | `sys.executable` | Which interpreter binary, so which environment | `process.execPath` |

            **Further reading**

            - [`sys` — System-specific parameters](https://docs.python.org/3/library/sys.html)
            - [`platform` — Access to underlying platform data](https://docs.python.org/3/library/platform.html)
            - [Status of Python versions (devguide)](https://devguide.python.org/versions/)
            - [PEP 602 — Annual release cycle](https://peps.python.org/pep-0602/),
              [PEP 790 — Python 3.15 release schedule](https://peps.python.org/pep-0790/),
              [PEP 421 — `sys.implementation`](https://peps.python.org/pep-0421/)
            - [What's new in Python 3.15](https://docs.python.org/3.15/whatsnew/3.15.html)
            """
        ),
    ]
