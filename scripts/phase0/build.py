"""Build notebooks/phase0_environment_setup.ipynb.

Run from the repository root:

    uv run python scripts/phase0/build.py
"""

import importlib
import sys
from pathlib import Path

PHASE_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = PHASE_DIR.parent
REPO_ROOT = SCRIPTS_DIR.parent
sys.path[:0] = [str(SCRIPTS_DIR), str(PHASE_DIR)]

from nbformat import NotebookNode  # noqa: E402

from nb_builder import code, md, new_notebook, save_notebook, shared_setup_cells  # noqa: E402

NOTEBOOK_PATH = REPO_ROOT / "notebooks" / "phase0_environment_setup.ipynb"
UNIT_MODULE_NAMES = ["unit_0_1", "unit_0_2", "unit_0_3", "unit_0_4"]


def title_cells() -> list[NotebookNode]:
    """Return the notebook title and introduction."""
    return [
        md(
            """
            # Phase 0 — Environment and Tooling

            **Outcome:** a reproducible Python 3.15 project with uv, a working Jupyter kernel, and
            the introspection habits used throughout the course.

            | Unit | Topic |
            | --- | --- |
            | 0.1 | Python, the language and its implementations |
            | 0.2 | Installing Python and virtual environments |
            | 0.3 | Project management with uv |
            | 0.4 | Jupyter and editor workflow (with Lab 0) |

            **How to use this notebook**

            - Select the **Python 3.15 (course)** kernel, then run the *Shared setup* cell first.
            - Each unit starts with its own setup cell, so you can jump straight to any unit.
            - *Predict the output* questions hide the answer in a collapsible block: decide first,
              then run the proof cell.
            - Shell commands (`uv …`, `git …`) are shown in `bash` blocks for you to run in a
              terminal. The notebook only executes read-only commands such as `uv --version`.
            """
        )
    ]


def unit_cells() -> list[NotebookNode]:
    """Collect cells from every unit module that exists, in syllabus order."""
    collected_cells: list[NotebookNode] = []
    for module_name in UNIT_MODULE_NAMES:
        try:
            unit_module = importlib.import_module(module_name)
        except ModuleNotFoundError:
            print(f"Skipping {module_name}: module not written yet")
            continue
        unit_cell_list = unit_module.cells()
        print(f"{module_name}: {len(unit_cell_list)} cells")
        collected_cells.extend(unit_cell_list)
    return collected_cells


DELIVERABLE_CHECK_SOURCE = '''
from pathlib import Path


def find_repo_root(start: Path | None = None) -> Path:
    """Walk up from start (default: the working directory) to the folder holding pyproject.toml."""
    current = (start or Path.cwd()).resolve()
    for folder in (current, *current.parents):
        if (folder / "pyproject.toml").exists():
            return folder
    raise FileNotFoundError("pyproject.toml not found above the working directory")


repo_root = find_repo_root()
required_paths = [
    "pyproject.toml",
    ".python-version",
    "uv.lock",
    "README.md",
    "notebooks",
    "projects",
    "exercises/solutions",
    "scripts",
]
for relative_path in required_paths:
    status = "ok" if (repo_root / relative_path).exists() else "MISSING"
    print(f"{status:8} {relative_path}")
'''

DELIVERABLE_TREE_SOURCE = '''
import os
import shutil
import subprocess

SKIPPED_FOLDERS = {".git", ".venv", "__pycache__", ".ipynb_checkpoints", ".ruff_cache", "_scratch"}


def list_repository_files(root: Path) -> list[str]:
    """List repository files, honouring git's ignore rules when git is available."""
    if shutil.which("git") and (root / ".git").exists():
        completed = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
        return sorted(completed.stdout.splitlines())
    file_paths = []
    for folder, subfolders, file_names in os.walk(root):
        subfolders[:] = [name for name in subfolders if name not in SKIPPED_FOLDERS]
        file_paths += [str((Path(folder) / name).relative_to(root)) for name in file_names]
    return sorted(file_paths)


def print_tree(relative_paths: list[str]) -> None:
    """Print relative file paths as an indented tree with box-drawing connectors."""
    tree: dict[str, dict] = {}
    for relative_path in relative_paths:
        node = tree
        for part in Path(relative_path).parts:
            node = node.setdefault(part, {})

    def walk(node: dict[str, dict], prefix: str) -> None:
        names = sorted(node, key=lambda name: (not node[name], name))  # folders first
        for index, name in enumerate(names):
            is_last = index == len(names) - 1
            print(f"{prefix}{'└── ' if is_last else '├── '}{name}{'/' if node[name] else ''}")
            walk(node[name], prefix + ("    " if is_last else "│   "))

    print(".")
    walk(tree, "")


print_tree(list_repository_files(repo_root))
'''


def deliverable_cells() -> list[NotebookNode]:
    """Return the Phase 0 Deliverable section."""
    return [
        md(
            """
            ## Phase 0 Deliverable

            The course repository, set up with uv:

            | Path | Purpose |
            | --- | --- |
            | `pyproject.toml` | Project metadata, dependencies, dev group and ruff config |
            | `.python-version` | Pins Python 3.15 |
            | `uv.lock` | Exact versions and hashes of every dependency |
            | `notebooks/` | One notebook per phase |
            | `projects/` | Code that outgrows a notebook |
            | `exercises/solutions/` | Lab reference solutions (`phaseN_solutions.py`) |
            | `scripts/` | Notebook build scripts (`nb_builder.py`, `phaseN/`) |
            | `README.md` | Course description and setup instructions |

            The first cell checks that every required path exists.
            """
        ),
        code(DELIVERABLE_CHECK_SOURCE),
        md(
            """
            The second cell prints the repository tree. It asks git for the file list
            (`git ls-files --cached --others --exclude-standard`), so everything git ignores,
            such as `.venv/`, caches and `notebooks/_scratch/`, is left out. Without git it falls
            back to walking the folders and skipping those names.
            """
        ),
        code(DELIVERABLE_TREE_SOURCE),
    ]


def build() -> None:
    """Assemble all cells and write the notebook."""
    all_cells = [*title_cells(), *shared_setup_cells(), *unit_cells(), *deliverable_cells()]
    notebook = new_notebook("Phase 0 — Environment and Tooling", all_cells)
    save_notebook(notebook, NOTEBOOK_PATH)


if __name__ == "__main__":
    build()
