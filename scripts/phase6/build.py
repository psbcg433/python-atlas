"""Build notebooks/phase6_web_fastapi.ipynb.

Phase 6 is built a few units at a time: every unit module that exists is included in syllabus
order, then the project module if it exists; missing ones are skipped. Run from the repository
root:

    uv run python scripts/phase6/build.py
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

from nb_builder import code, md, new_notebook, save_notebook, shared_setup_cells  # noqa: E402

NOTEBOOK_TITLE = "Phase 6 — Web Development with FastAPI"
NOTEBOOK_PATH = REPO_ROOT / "notebooks" / "phase6_web_fastapi.ipynb"
UNIT_MODULE_NAMES = [f"unit_6_{unit_number}" for unit_number in range(1, 9)]
PROJECT_MODULE_NAME = "project"
NOTES_V1_HEADING = "### Notes API v1 — the project files"
NOTES_V1_FILES = [
    "README.md",
    "pyproject.toml",
    "ruff.toml",
    "src/notes_api/__init__.py",
    "src/notes_api/main.py",
    "src/notes_api/schemas.py",
    "src/notes_api/store.py",
    "tests/conftest.py",
    "tests/test_notes.py",
]


def title_cells() -> list[NotebookNode]:
    """Return the notebook title, the phase introduction and the Phases 1–5 recap."""
    return [
        md(
            f"""
            # {NOTEBOOK_TITLE}

            **Outcome:** build, secure, test, observe and deploy a FastAPI service, and explain
            every layer from the TCP socket to the response model.

            | Unit | Topic |
            | --- | --- |
            | 6.1 | HTTP and the Python web stack from scratch |
            | 6.2 | FastAPI fundamentals and Pydantic v2 |
            | 6.3 | Dependency injection and application structure |
            | 6.4 | Databases with SQLAlchemy 2.0 |
            | 6.5 | Authentication, authorization and security |
            | 6.6 | Background jobs, real time and caching |
            | 6.7 | API testing and observability |
            | 6.8 | Deployment and operations |
            | Project | Notes API in production |

            **The Notes API.** One application grows through Units 6.2–6.8. Its code lives in
            `projects/notes_api/`, a separate uv project (its own `pyproject.toml`, `uv.lock`,
            `src/notes_api/` package and `tests/`) so it can be containerized in Unit 6.8. The
            notebook **writes those files** with `%%writefile` cells, imports the app in the
            kernel, tests it with `TestClient` and `httpx.AsyncClient`, and serves it with
            Uvicorn. Re-running the notebook rewrites the same files, so the folder always matches
            the last unit you ran. To serve it from a terminal:

            ```bash
            cd projects/notes_api
            uv run uvicorn notes_api.main:app --reload
            # then open http://127.0.0.1:8000/docs
            ```

            **How to use this notebook**

            - Select the **Python 3.15 (course)** kernel, then run the *Shared setup* cell first.
            - Each unit starts with its own setup cell, so you can jump straight to any unit.
            - **Servers are started and stopped by the cell that needs them.** When a demo needs
              a real server, the cell starts it in a background process on a free port, waits
              for its `/health` endpoint, runs the demo and stops the server, even if the demo
              fails. No server outlives its cell.
            - **No public network and no cloud account.** HTTP demos talk to servers on
              `127.0.0.1`, to `httpx.MockTransport` / ASGI transports, or to the local shop API
              from Unit 4.6. Third-party services (OAuth providers, email) are faked locally.
            - **PostgreSQL and Redis** (from Unit 6.4) run in Docker when it is available;
              otherwise the cells run on SQLite / fakeredis and print a clear skip message for
              the parts that need the real service.
            - **Secrets** are never committed: `.env` is git-ignored, `.env.example` is committed,
              and demo keys are generated when the cell runs.
            - **Optional packages are detected, never assumed.** Packages outside the course
              dependencies (Flask, Django, Litestar, Gunicorn, aiohttp, h2) are checked with
              `importlib.util.find_spec`; when one is missing its cell prints a skip message.
            - *Predict the output* questions hide the answer in a collapsible block: decide
              first, then run the proof cell.
            - Labs: replace the `raise NotImplementedError` in each stub, then run the check
              cell. Until then the checks print FAIL; that is expected.
            - Timings are measurements on your machine, not facts; no cell asserts a speedup
              except the loose sanity checks named in a lab.
            - Features newer than Python 3.12 are labelled (*New in 3.13*, *Changed in 3.14*, …).
            """
        ),
        md(
            """
            ## What you need from Phases 1–5

            A web framework is mostly the language features you already know, wired together.

            | Earlier idea | Unit | Where Phase 6 uses it |
            | --- | --- | --- |
            | `bytes` vs `str`, encodings | 1.4 | HTTP is bytes on a socket; headers are Latin-1, bodies are usually UTF-8 |
            | Dict dispatch (`ROUTES`, `dispatch`) | 1.6.14 | the router of the raw socket server (6.1.4) |
            | Decorators, `functools.wraps` | 1.12 | `@app.get(...)` registers a function and returns it unchanged |
            | Annotation-based injection (`inject`) | 1.12.11 | FastAPI reads parameter annotations to decide where each value comes from |
            | Exceptions with `status_code` (`AppError`) | 1.14.5 | `HTTPException` and exception handlers |
            | Descriptors, metaclasses, `__init_subclass__` | 2.5 | how Pydantic builds a model class from annotations |
            | `dataclass`, `TypedDict`, enums | 2.6 | request records, enum path parameters |
            | `inspect.signature`, annotations | 3.x, 4.2 | 6.2.10: what FastAPI does with your function signature |
            | `pytest`, fixtures | 4.3 | the Notes API test suite |
            | Pydantic, `httpx`, the shop API | 4.6 | request/response models; HTTP clients (6.1.8) |
            | Threads, the event loop, blocking calls | 5.1–5.4 | `async def` vs `def` handlers and the thread pool (6.2.8) |
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


def notes_v1_prune_cells() -> list[NotebookNode]:
    """Cells that reset projects/notes_api/ to v1's file set before Unit 6.2 writes v1.

    Later units add files (routers, migrations, more tests). Without this, re-running Unit 6.2
    after them would run v3 tests against v1's conftest. The helper source lives in unit_6_3.
    """
    from unit_6_3 import PRUNE_HELPER_SOURCE

    files = ",\n    ".join(f'"{name}"' for name in NOTES_V1_FILES)
    return [
        md(
            """
            **Re-running this section after Unit 6.3 or later?** Later units add files to
            `projects/notes_api/` (routers, migrations, more tests). The next cell deletes every
            file v1 does not have, so the cells below rebuild exactly v1 and its tests run
            against v1's code; the Unit 6.3 and 6.4 sections write their versions again.
            `.venv`, `.env` and `uv.lock` are never touched:
            """
        ),
        code(
            PRUNE_HELPER_SOURCE
            + f"\n\nNOTES_V1_FILES = [\n    {files},\n]\n"
            + 'print("removed:", prune_notes_project(NOTES_V1_FILES))'
        ),
        md("Now the project metadata, as described above:"),
    ]


def insert_after_heading(
    cells: list[NotebookNode], heading: str, extra: list[NotebookNode]
) -> list[NotebookNode]:
    """Insert extra right after the markdown cell that starts with heading (if present)."""
    for index, cell in enumerate(cells):
        if cell.cell_type == "markdown" and cell.source.startswith(heading):
            return [*cells[: index + 1], *extra, *cells[index + 1 :]]
    return cells


def unit_cells() -> list[NotebookNode]:
    """Collect cells from every unit module (then the project) that exists, in syllabus order."""
    collected_cells: list[NotebookNode] = []
    for module_name in [*UNIT_MODULE_NAMES, PROJECT_MODULE_NAME]:
        unit_module = import_optional(module_name)
        if unit_module is None:
            continue
        unit_cell_list = unit_module.cells()
        if module_name == "unit_6_2":
            unit_cell_list = insert_after_heading(
                unit_cell_list, NOTES_V1_HEADING, notes_v1_prune_cells()
            )
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
