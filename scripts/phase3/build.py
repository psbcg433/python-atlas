"""Build notebooks/phase3_python_internals.ipynb.

Phase 3 is built a few units at a time: every unit module that exists is included in syllabus
order, then the project module if it exists; missing ones are skipped. Run from the repository
root:

    uv run python scripts/phase3/build.py
"""

import importlib
import sys
from pathlib import Path
from types import ModuleType

PHASE_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = PHASE_DIR.parent
REPO_ROOT = SCRIPTS_DIR.parent
sys.path[:0] = [str(SCRIPTS_DIR), str(PHASE_DIR)]

from nbformat import NotebookNode  # noqa: E402

from nb_builder import md, new_notebook, save_notebook, shared_setup_cells  # noqa: E402

NOTEBOOK_PATH = REPO_ROOT / "notebooks" / "phase3_python_internals.ipynb"
UNIT_MODULE_NAMES = [f"unit_3_{unit_number}" for unit_number in range(1, 4)]
PROJECT_MODULE_NAME = "project"


def title_cells() -> list[NotebookNode]:
    """Return the notebook title, the phase introduction and the Phase 1–2 recap."""
    return [
        md(
            """
            # Phase 3 — Python Internals: Memory, Bytecode and Imports

            **Outcome:** explain where an object's memory comes from and when it is freed, read
            bytecode fluently, and describe exactly what happens between `import x` and the
            first line of your code running.

            | Unit | Topic |
            | --- | --- |
            | 3.1 | Memory management |
            | 3.2 | Bytecode and the interpreter |
            | 3.3 | Modules, packages and the import system |
            | Project | Internals toolkit |

            **How to use this notebook**

            - Select the **Python 3.15 (course)** kernel, then run the *Shared setup* cell first.
            - Each unit starts with its own setup cell, so you can jump straight to any unit.
            - This phase looks at **CPython implementation details**. Object sizes, reference
              counts, addresses and `dis` listings change between Python versions (and some
              between operating systems). Cells that print them also print the interpreter
              version; your numbers may differ, the ideas do not.
            - Nothing here asserts an exact size, address or reference count. Checks compare
              *relationships* (bigger than, freed or not, same object or not).
            - Cells that need a special build (free-threaded, JIT) check first and print a skip
              message when the feature is missing.
            - *Predict the output* questions hide the answer in a collapsible block: decide
              first, then run the proof cell.
            - Labs: replace the `raise NotImplementedError` in each stub, then run the check
              cell. Until then the checks print FAIL; that is expected.
            - Features newer than Python 3.12 are labelled (*New in 3.13*, *Changed in 3.14*, …).
            """
        ),
        md(
            """
            ## What you need from Phases 1 and 2

            Phase 3 opens the box behind ideas you have already used. If one feels shaky,
            re-read the unit before going on.

            | Earlier idea | Unit | What Phase 3 adds |
            | --- | --- | --- |
            | Source → tokens → AST → code object → eval loop | 1.1 | Each stage in detail: code-object fields, `dis` columns, the specializing interpreter and the JIT |
            | Names are references; `is` vs `==`; the small-int cache | 1.2 | References are counted; some objects are immortal; the cyclic GC handles what counting cannot |
            | `sys.getsizeof`, PEP 393 strings, list over-allocation | 1.4–1.5 | The object header, the GC header, pymalloc pools and free lists |
            | `dict` internals and key-sharing | 1.6.1 | Measuring memory with `tracemalloc` snapshots and diffs |
            | Closures and cells (`co_freevars`, `co_cellvars`) | 1.11 | Code objects and function objects as data you can inspect and rebuild |
            | `functools.lru_cache`, decorators | 1.12 | Why `lru_cache` on a method leaks |
            | Generators and frames | 1.13 | Frames, the instruction pointer and inlined calls |
            | Exceptions, tracebacks, context managers | 1.14 | Stored tracebacks keep frames alive; context managers beat `__del__` |
            | `__slots__`, descriptors, `__weakref__` | 2.5 | The `__weakref__` slot and what weak references are for |

            > **Note:** you will see `sys._is_immortal`, `sys._jit`, `sys._is_gil_enabled` and
            > `sys._debugmallocstats`. A leading underscore in `sys` means *CPython-specific
            > and may change*; use them to learn and debug, not in production code.
            """
        ),
    ]


def import_optional(module_name: str) -> ModuleType | None:
    """Import a unit or project module, or return None if it has not been written yet."""
    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError as error:
        if error.name != module_name:  # a real import error inside an existing module
            raise
        print(f"Skipping {module_name}: module not written yet")
        return None


def unit_cells() -> list[NotebookNode]:
    """Collect cells from every unit module (then the project) that exists, in syllabus order."""
    collected_cells: list[NotebookNode] = []
    for module_name in [*UNIT_MODULE_NAMES, PROJECT_MODULE_NAME]:
        unit_module = import_optional(module_name)
        if unit_module is None:
            continue
        unit_cell_list = unit_module.cells()
        print(f"{module_name}: {len(unit_cell_list)} cells")
        collected_cells.extend(unit_cell_list)
    return collected_cells


def build() -> None:
    """Assemble all cells and write the notebook."""
    all_cells = [*title_cells(), *shared_setup_cells(), *unit_cells()]
    notebook = new_notebook("Phase 3 — Python Internals: Memory, Bytecode and Imports", all_cells)
    save_notebook(notebook, NOTEBOOK_PATH)


if __name__ == "__main__":
    build()
