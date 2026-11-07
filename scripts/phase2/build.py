"""Build notebooks/phase2_oop_data_model.ipynb.

Phase 2 is built a few units at a time: every unit module that exists is included in syllabus
order, missing ones are skipped. Run from the repository root:

    uv run python scripts/phase2/build.py
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

NOTEBOOK_PATH = REPO_ROOT / "notebooks" / "phase2_oop_data_model.ipynb"
UNIT_MODULE_NAMES = [f"unit_2_{unit_number}" for unit_number in range(1, 7)]
PROJECT_MODULE_NAME = "project"


def title_cells() -> list[NotebookNode]:
    """Return the notebook title, the phase introduction and the Phase 1 recap."""
    return [
        md(
            """
            # Phase 2 — Object-Oriented Programming and the Data Model

            **Outcome:** build classes that behave like built-ins, design with inheritance and
            composition, and understand the descriptor and metaclass machinery behind Pydantic,
            SQLAlchemy and dataclasses.

            | Unit | Topic |
            | --- | --- |
            | 2.1 | Classes and instances |
            | 2.2 | Inheritance, MRO and composition |
            | 2.3 | Abstractions: ABCs, `collections.abc` and Protocols |
            | 2.4 | The data model: special (dunder) methods |
            | 2.5 | Attribute access, descriptors and metaprogramming |
            | 2.6 | Dataclasses, enums and Pythonic design patterns |
            | Project | Inventory domain model |

            **How to use this notebook**

            - Select the **Python 3.15 (course)** kernel, then run the *Shared setup* cell first.
            - Each unit starts with its own setup cell, so you can jump straight to any unit.
            - *Predict the output* questions hide the answer in a collapsible block: decide first,
              then run the proof cell.
            - Labs: replace the `raise NotImplementedError` in each stub, then run the check cell.
              Until then the checks print FAIL; that is expected.
            - Features newer than Python 3.12 are labelled (*New in 3.13*, *Changed in 3.15*, …).
            """
        ),
        md(
            """
            ## What you need from Phase 1

            Phase 2 builds directly on these Phase 1 ideas. If one feels shaky, re-read the unit
            before going on.

            | Phase 1 idea | Unit | Why it matters for classes |
            | --- | --- | --- |
            | Everything is an object; names are references | 1.2 | Classes, methods and instances are all objects you can inspect and pass around |
            | Mutable vs immutable, identity vs equality | 1.2.4–1.2.5 | The shared mutable class-attribute trap; `__eq__` vs `is` |
            | `dict` internals and key-sharing dictionaries | 1.6.1 | Every instance stores its attributes in a `__dict__` that shares keys with its siblings |
            | `__copy__` / `__deepcopy__` | 1.7.4 | Classes customize built-in behaviour through special methods |
            | Class patterns and `__match_args__` | 1.8.4 | `match` destructures your own classes |
            | Functions are first-class; `*args` / `**kwargs` | 1.10 | Methods are functions stored on the class; cooperative `**kwargs` in `super()` chains |
            | Scope, closures and cells | 1.11 | Zero-argument `super()` reads a hidden `__class__` cell |
            | Decorators, including class decorators and `__get__` | 1.12 | `@property`, `@classmethod` and `@staticmethod` are decorators built on descriptors |
            | The iterator protocol | 1.13 | `collections.abc.Iterator` and `Iterable` formalize it |
            | Custom exception hierarchies, `__enter__` / `__exit__` | 1.14 | You already designed classes around inheritance and special methods |

            > **Note:** Phase 1 used small classes (`Price`, `LinkedListNode`, `Timer`, `AppError`)
            > before explaining them fully. This phase explains everything those classes relied on.
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
    notebook = new_notebook("Phase 2 — Object-Oriented Programming and the Data Model", all_cells)
    save_notebook(notebook, NOTEBOOK_PATH)


if __name__ == "__main__":
    build()
