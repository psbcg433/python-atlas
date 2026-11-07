"""Build notebooks/phase4_professional_python.ipynb.

Phase 4 is built a few units at a time: every unit module that exists is included in syllabus
order, then the project module if it exists; missing ones are skipped. Run from the repository
root:

    uv run python scripts/phase4/build.py
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

NOTEBOOK_TITLE = (
    "Phase 4 — Professional Python: Packaging, Typing, Testing and the Standard Library"
)
NOTEBOOK_PATH = REPO_ROOT / "notebooks" / "phase4_professional_python.ipynb"
UNIT_MODULE_NAMES = [f"unit_4_{unit_number}" for unit_number in range(1, 7)]
PROJECT_MODULE_NAME = "project"


def title_cells() -> list[NotebookNode]:
    """Return the notebook title, the phase introduction and the Phases 1–3 recap."""
    return [
        md(
            f"""
            # {NOTEBOOK_TITLE}

            **Outcome:** ship a typed, tested, logged and installable package, and reach for the
            right standard-library or third-party module with confidence.

            | Unit | Topic |
            | --- | --- |
            | 4.1 | Package management and project structure |
            | 4.2 | The type system (Python's TypeScript) |
            | 4.3 | Testing, debugging and logging |
            | 4.4 | Standard library essentials |
            | 4.5 | File I/O, encodings and serialization |
            | 4.6 | Essential third-party libraries |
            | Project | Publish the Log Analyzer |

            **How to use this notebook**

            - Select the **Python 3.15 (course)** kernel, then run the *Shared setup* cell first.
            - Each unit starts with its own setup cell, so you can jump straight to any unit.
            - This phase is about **tools**: uv, pip, mypy, pyright, ruff and friends. Tool demos
              write small throwaway projects under `notebooks/_scratch/` (git-ignored) and run
              the real tool in a child process, printing its real output. Absolute paths are
              shown as `<scratch>` (the unit's scratch folder), `<repo>` or `~`, and timings as
              `<time>`.
            - No cell changes the course's own `pyproject.toml` or `uv.lock` (a check at the end
              of Unit 4.1 proves it), and nothing is ever published.
            - Packaging demos resolve against a **local wheelhouse** of tiny demo packages built
              in Unit 4.1, so they work offline and give the same answer every time. The only
              cells that need the network (a vulnerability audit and one third-party tool)
              check first and print a skip message when you are offline.
            - Tool output can change with the tool's version; the versions used are printed.
            - *Predict the output* questions hide the answer in a collapsible block: decide
              first, then run the proof cell.
            - Labs: replace the `raise NotImplementedError` in each stub (or fix the code, where
              the exercise says so), then run the check cell. Until then the checks print FAIL;
              that is expected.
            - Features newer than Python 3.12 are labelled (*New in 3.13*, *Changed in 3.14*, …).
            """
        ),
        md(
            """
            ## What you need from Phases 1–3

            Phase 4 turns notebook code into software other people install. If one of these
            feels shaky, re-read the unit before going on.

            | Earlier idea | Unit | What Phase 4 adds |
            | --- | --- | --- |
            | Virtual environments, `uv init`, `uv add`, `uv run` | 0.2–0.3 | The whole packaging toolchain: wheels, build backends, lockfiles, workspaces, publishing |
            | Functions, type hints on every signature, `Callable` | 1.10–1.12 | Hints become a checked contract: mypy and pyright, generics, `ParamSpec`, `@overload` |
            | Decorators (`timer`, `retry`) | 1.12 | Decorators that keep their wrapped function's signature for the type checker |
            | Exceptions, `logging` basics | 1.14 | Testing, debugging and logging configuration (Unit 4.3) |
            | Protocols, ABCs, dataclasses, enums | 2.3, 2.6 | Structural typing checked statically; `TypedDict`, `Literal`, discriminated unions |
            | `Money`, the inventory model | 2.4, Project 2 | Typed to pass `mypy --strict` (Lab 4.2) |
            | Packages, `sys.path`, `importlib.metadata`, entry points | 3.3 | `src/` layout, editable installs, `[project.scripts]`, single-sourced `__version__` |
            | `pyinspect` (a package without packaging metadata) | Project 3 | The Phase 4 Project makes code like this installable |
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
    notebook = new_notebook(NOTEBOOK_TITLE, all_cells)
    save_notebook(notebook, NOTEBOOK_PATH)


if __name__ == "__main__":
    build()
