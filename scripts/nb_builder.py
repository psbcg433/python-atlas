"""Shared helpers for generating course notebooks.

Every phase build script imports this module. Unit modules describe cells with ``md()`` and
``code()``; ``build.py`` wraps them with ``new_notebook()`` and writes the file with
``save_notebook()``.
"""

import textwrap
from pathlib import Path

import nbformat
from nbformat import NotebookNode

KERNEL_NAME = "python-course"
KERNEL_DISPLAY_NAME = "Python 3.15 (course)"


def _clean(text: str) -> str:
    """Remove the common indentation and surrounding blank lines from a triple-quoted string."""
    return textwrap.dedent(text).strip("\n")


def md(text: str) -> NotebookNode:
    """Create a markdown cell from an (optionally indented) triple-quoted string."""
    return nbformat.v4.new_markdown_cell(_clean(text))


def code(source: str) -> NotebookNode:
    """Create a code cell from an (optionally indented) triple-quoted string."""
    return nbformat.v4.new_code_cell(_clean(source))


def predict_cells(snippet: str, answer: str, proof: str) -> list[NotebookNode]:
    """Build a predict-the-output exercise: the snippet, a hidden answer and a cell that proves it.

    Args:
        snippet: Python code shown in a fenced block for the reader to predict.
        answer: Markdown explanation revealed inside a ``<details>`` element.
        proof: Runnable code that demonstrates the answer.
    """
    question = (
        "**Predict the output.**\n\n```python\n"
        + _clean(snippet)
        + "\n```\n\n<details><summary>Answer</summary>\n\n"
        + _clean(answer)
        + "\n\n</details>"
    )
    return [
        nbformat.v4.new_markdown_cell(question),
        md("Run the next cell to check your prediction."),
        code(proof),
    ]


SHARED_SETUP_SOURCE = '''
import inspect
import os
import platform
import sys
from collections.abc import Callable
from pathlib import Path

type TestCase = tuple[str, Callable[[], object], object]


def run_checks(test_cases: list[TestCase]) -> None:
    """Run (label, thunk, expected) cases and print PASS/FAIL for each. Never raises."""
    passed_count = 0
    for label, thunk, expected in test_cases:
        try:
            actual = thunk()
        except Exception as error:  # a check cell must never stop Run All
            print(f"FAIL  {label}: raised {type(error).__name__}: {error}")
            continue
        if actual == expected:
            passed_count += 1
            print(f"PASS  {label}")
        else:
            print(f"FAIL  {label}: expected {expected!r}, got {actual!r}")
    print(f"{passed_count}/{len(test_cases)} checks passed")


def show_size(label: str, obj: object) -> None:
    """Print the shallow size in bytes, the type and the id of an object."""
    print(f"{label}: {sys.getsizeof(obj)} bytes, type={type(obj).__name__}, id={id(obj)}")


def find_repo_root(start: Path | None = None) -> Path:
    """Walk up from start (default: the working directory) to the folder holding pyproject.toml."""
    current = (start or Path.cwd()).resolve()
    for folder in (current, *current.parents):
        if (folder / "pyproject.toml").exists():
            return folder
    raise FileNotFoundError("pyproject.toml not found above the working directory")


print(f"Python {platform.python_version()} ({sys.implementation.name}) on {platform.system()}")
print(f"Repository root: {find_repo_root().name}/")
'''


def shared_setup_cells() -> list[NotebookNode]:
    """Return the markdown + code cells that open every notebook (convention 12)."""
    return [
        md(
            """
            ## Shared setup

            This cell runs first in every notebook of the course. It imports common modules and
            defines three helpers used everywhere:

            | Helper | What it does |
            | --- | --- |
            | `run_checks(test_cases)` | runs `(label, thunk, expected)` cases, prints PASS/FAIL |
            | `show_size(label, obj)` | prints `sys.getsizeof(obj)`, type name and `id()` |
            | `find_repo_root()` | finds the folder holding `pyproject.toml` |

            `run_checks` catches every exception, so a failing check never stops Run All.

            > **Note:** each unit re-imports what it needs, so you can run any unit on its own
            > after this cell.
            """
        ),
        code(SHARED_SETUP_SOURCE),
    ]


def new_notebook(title: str, cells: list[NotebookNode]) -> NotebookNode:
    """Assemble a notebook bound to the course kernel, with deterministic cell ids.

    Args:
        title: Notebook title stored in the metadata (the ``#`` heading lives in the first cell).
        cells: Cells in display order.
    """
    notebook = nbformat.v4.new_notebook()
    notebook.metadata["kernelspec"] = {
        "name": KERNEL_NAME,
        "display_name": KERNEL_DISPLAY_NAME,
        "language": "python",
    }
    notebook.metadata["language_info"] = {"name": "python"}
    notebook.metadata["title"] = title
    for index, cell in enumerate(cells):
        cell["id"] = f"cell-{index:03d}"
    notebook.cells = cells
    return notebook


def save_notebook(notebook: NotebookNode, path: Path) -> None:
    """Validate the notebook against the nbformat schema and write it to path."""
    nbformat.validate(notebook)
    path.parent.mkdir(parents=True, exist_ok=True)
    nbformat.write(notebook, path)
    print(f"Wrote {path} ({len(notebook.cells)} cells)")
