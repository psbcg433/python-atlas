"""Build notebooks/phase1_language_fundamentals.ipynb.

Phase 1 is built a few units at a time: every unit module that exists is included in syllabus
order, missing ones are skipped. Run from the repository root:

    uv run python scripts/phase1/build.py
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

NOTEBOOK_PATH = REPO_ROOT / "notebooks" / "phase1_language_fundamentals.ipynb"
UNIT_MODULE_NAMES = [f"unit_1_{unit_number}" for unit_number in range(1, 15)]
PROJECT_MODULE_NAME = "project"


def title_cells() -> list[NotebookNode]:
    """Return the notebook title and phase introduction."""
    return [
        md(
            """
            # Phase 1 — Python Language Fundamentals

            **Outcome:** predict the output of any core Python snippet and explain it in terms of
            objects, names, types and frames; use every built-in data type and its API fluently.

            | Unit | Topic |
            | --- | --- |
            | 1.1 | How Python executes code |
            | 1.2 | Objects, names and mutability |
            | 1.3 | Numeric and boolean data types |
            | 1.4 | Text and binary data types |
            | 1.5 | Collection data types I: lists, tuples and ranges |
            | 1.6 | Collection data types II: dictionaries, sets and the `collections` module |
            | 1.7 | Copying: shallow copies, deep copies and structured clones |
            | 1.8 | Operators, expressions and control flow |
            | 1.9 | Iteration, comprehensions and built-in functions |
            | 1.10 | Functions: definition and arguments |
            | 1.11 | Scope, namespaces and closures |
            | 1.12 | Decorators, `functools` and the call stack |
            | 1.13 | Iterators, generators and `itertools` |
            | 1.14 | Exceptions and context managers |
            | Project | Log analyzer |

            **How to use this notebook**

            - Select the **Python 3.15 (course)** kernel, then run the *Shared setup* cell first.
            - Each unit starts with its own setup cell, so you can jump straight to any unit.
            - *Predict the output* questions hide the answer in a collapsible block: decide first,
              then run the proof cell.
            - Labs: replace the `raise NotImplementedError` in each stub, then run the check cell.
              Until then the checks print FAIL; that is expected.
            - Features newer than Python 3.12 are labelled (*New in 3.13*, *Changed in 3.15*, …).
            """
        )
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
    notebook = new_notebook("Phase 1 — Python Language Fundamentals", all_cells)
    save_notebook(notebook, NOTEBOOK_PATH)


if __name__ == "__main__":
    build()
