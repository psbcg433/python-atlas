"""Build notebooks/phase5_concurrency_performance.ipynb.

Phase 5 is built a few units at a time: every unit module that exists is included in syllabus
order, then the project module if it exists; missing ones are skipped. Run from the repository
root:

    uv run python scripts/phase5/build.py
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

NOTEBOOK_TITLE = "Phase 5 — Concurrency, Async and Performance"
NOTEBOOK_PATH = REPO_ROOT / "notebooks" / "phase5_concurrency_performance.ipynb"
UNIT_MODULE_NAMES = [f"unit_5_{unit_number}" for unit_number in range(1, 6)]
PROJECT_MODULE_NAME = "project"


def title_cells() -> list[NotebookNode]:
    """Return the notebook title, the phase introduction and the Phases 1–4 recap."""
    return [
        md(
            f"""
            # {NOTEBOOK_TITLE}

            **Outcome:** choose threads, processes, subinterpreters or asyncio for a workload
            and justify it with a benchmark; explain the asyncio event loop as precisely as
            Node's; profile and optimize CPU and memory.

            | Unit | Topic |
            | --- | --- |
            | 5.1 | Concurrency fundamentals, threads and the GIL |
            | 5.2 | Multiprocessing and subinterpreters |
            | 5.3 | asyncio internals: the event loop |
            | 5.4 | asyncio in production |
            | 5.5 | Performance and memory optimization |
            | Project | 10× faster sales report |

            **How to use this notebook**

            - Select the **Python 3.15 (course)** kernel, then run the *Shared setup* cell first.
            - Each unit starts with its own setup cell, so you can jump straight to any unit.
            - **Timings are measurements, not facts.** Every benchmark prints the numbers it
              measured on your machine and the ratio between them; no cell asserts a speedup.
              Your numbers will differ with CPU, core count, load and Python build.
            - **One knob for workload sizes.** Every unit setup defines
              `DEMO_SCALE = int(os.environ.get("PHASE5_DEMO_SCALE", "1"))`. Benchmarks
              multiply their sizes by it, and child processes inherit the variable. The
              default keeps every cell under about 20 seconds; start Jupyter with
              `PHASE5_DEMO_SCALE=4` for steadier numbers.
            - **Workers live in files.** Process pools, `ProcessPoolExecutor` and
              subinterpreter pools need worker functions that a fresh interpreter can import
              (Unit 5.2 explains why). Cells starting with `%%writefile` save such modules
              under `notebooks/_scratch/phase5/` (git-ignored); demos that need a clean
              process (start methods, the main guard, daemon threads at exit) run as scripts
              in a child interpreter.
            - **Optional builds and tools are detected, never assumed.** The free-threaded
              build (`python3.15t`), subinterpreters, the JIT, `uvloop` and the profilers are
              checked first; when one is missing its cell prints a skip message.
            - **No public network.** HTTP demos talk to a local server on `127.0.0.1`
              (the shop API from Unit 4.6) or to `httpx.MockTransport`.
            - *Predict the output* questions hide the answer in a collapsible block: decide
              first, then run the proof cell.
            - Labs: replace the `raise NotImplementedError` in each stub, then run the check
              cell. Until then the checks print FAIL; that is expected.
            - Features newer than Python 3.12 are labelled (*New in 3.13*, *Changed in 3.14*, …).
            """
        ),
        md(
            """
            ## What you need from Phases 1–4

            Phase 5 is about doing several things at once. These earlier ideas come back
            constantly; re-read the unit if one feels shaky.

            | Earlier idea | Unit | What Phase 5 adds |
            | --- | --- | --- |
            | Generators, `yield`, iterator protocol | 1.13 | Coroutines are generator-like objects driven by an event loop (5.3) |
            | Closures, decorators, `functools` | 1.11–1.12 | Passing work to threads and pools; `Timer` and `timer` measure it |
            | Context managers, `ExitStack` | 1.14 | `with lock:`, `with executor:`, cleanup on shutdown |
            | Reference counting, the GIL's place in CPython, the free-threaded build | 3.1 | What the GIL protects, when it is released, and what changes without it |
            | Bytecode, `dis`, the eval breaker and the switch interval | 3.2 | Why `counter += 1` is not atomic; where thread switches can happen |
            | Modules, `sys.path`, `__main__` | 3.3 | Why process workers must live in importable modules |
            | `pickle` | 4.5 | Every argument sent to a process is pickled: constraints and cost |
            | `httpx`, the local shop API, NumPy | 4.6 | Concurrent downloads; NumPy arrays in shared memory |
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
