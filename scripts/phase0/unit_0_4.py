"""Unit 0.4 — Jupyter and Editor Workflow (with Lab 0)."""

from nbformat import NotebookNode

from nb_builder import code, md, predict_cells

UNIT_SETUP_SOURCE = '''
import inspect
import json
import sys
from collections import Counter
from pathlib import Path

from IPython import get_ipython


def find_repo_root(start: Path | None = None) -> Path:
    """Walk up from start (default: the working directory) to the folder holding pyproject.toml."""
    current = (start or Path.cwd()).resolve()
    for folder in (current, *current.parents):
        if (folder / "pyproject.toml").exists():
            return folder
    raise FileNotFoundError("pyproject.toml not found above the working directory")


repo_root = find_repo_root()
this_notebook_path = repo_root / "notebooks" / "phase0_environment_setup.ipynb"
scratch_dir = repo_root / "notebooks" / "_scratch"
scratch_dir.mkdir(parents=True, exist_ok=True)
print(f"{this_notebook_path.exists()=}, {scratch_dir.relative_to(repo_root)=}")
'''


def cells() -> list[NotebookNode]:
    """Return the cells for Unit 0.4 and Lab 0."""
    return [
        md(
            """
            ## Unit 0.4 — Jupyter and Editor Workflow

            **Objectives**

            - Explain how the Jupyter server, the kernel and the `.ipynb` file fit together.
            - Avoid hidden-state bugs caused by running cells out of order.
            - Use the IPython magics you will rely on for the rest of the course.
            - Treat notebooks as data: read them with `nbformat`, convert them with `jupytext`.
            - Introspect any object with `help`, `dir`, `type`, `id`, `vars` and `inspect`.

            **JS bridge**

            | JavaScript concept | Python equivalent | The difference that bites |
            | --- | --- | --- |
            | Browser DevTools console / Node REPL | Jupyter kernel (IPython) | State persists across cells until you restart the kernel |
            | Observable / RunKit notebooks | Jupyter notebooks | Cells run in the order *you* click, not top to bottom |
            | `console.dir(obj)` | `dir(obj)`, `vars(obj)` | `vars` shows only the instance's own attributes |
            | `Function.prototype.toString()` | `inspect.getsource(func)` | Reads the source file; fails for built-ins written in C |
            | Prettier / ESLint | ruff format / ruff check | One tool does both |

            The next cell is this unit's setup. It also creates `notebooks/_scratch/`
            (git-ignored) for files written by the demos.
            """
        ),
        code(UNIT_SETUP_SOURCE),
        md(
            """
            ### 0.4.1 Jupyter architecture

            Three separate pieces cooperate:

            | Piece | What it is | In this project |
            | --- | --- | --- |
            | **Front end** | The UI that edits cells and shows outputs | JupyterLab in a browser, or VS Code |
            | **Jupyter server** | A web server that manages files and starts kernels (JupyterLab only; VS Code starts kernels itself) | `uv run jupyter lab` |
            | **Kernel** | A separate process that executes code and sends results back over ZeroMQ | `.venv/bin/python -m ipykernel_launcher` |
            | **Notebook file** | JSON on disk: cells, outputs, metadata | `notebooks/*.ipynb` |

            ```mermaid
            flowchart LR
                frontend["Front end (JupyterLab / VS Code)"] -- "execute_request" --> kernel["Kernel (.venv python + ipykernel)"]
                kernel -- "stream / execute_result" --> frontend
                frontend -- "save / load" --> notebook_file["notebook.ipynb (JSON)"]
            ```

            <details><summary>ASCII fallback</summary>

            ```text
            +----------------------+   execute_request    +-------------------------+
            | Front end            | -------------------> | Kernel process          |
            | (JupyterLab/VS Code) | <------------------- | .venv python + ipykernel|
            +----------------------+   outputs (ZeroMQ)   +-------------------------+
                       |
                       | save / load
                       v
               notebook.ipynb (JSON)
            ```

            </details>

            A **kernelspec** tells front ends how to start a kernel. This project registered one
            (run once in a terminal):

            ```bash
            uv run python -m ipykernel install --user --name python-course --display-name "Python 3.15 (course)"
            ```

            The cell reads that kernelspec back and checks that it starts this project's
            interpreter.
            """
        ),
        code(
            """
            from jupyter_client.kernelspec import KernelSpecManager, NoSuchKernel

            try:
                course_kernel_spec = KernelSpecManager().get_kernel_spec("python-course")
            except NoSuchKernel as error:
                print(f"Skipped: kernel not registered ({type(error).__name__})")
            else:
                print(f"{course_kernel_spec.display_name=}")
                print(f"{course_kernel_spec.argv[1:4]=}")
                print(f"{Path(course_kernel_spec.argv[0]) == Path(sys.executable)=}")
            print(f"{type(get_ipython()).__name__=}")
            """
        ),
        md(
            """
            ### 0.4.2 Execution discipline

            Every executed cell gets a number in the **execution counter** (`[7]`). The kernel keeps
            every variable alive until it restarts, so the *order you ran cells in* is what matters,
            not their order on the page. IPython also keeps history: `In` (inputs), `Out`
            (expression results) and `_` (the last result).

            The cell reads the counter and the history through the shell object: `In[-1]` is the
            source of the cell that is running right now.
            """
        ),
        code(
            """
            ipython_shell = get_ipython()
            print(f"{ipython_shell.execution_count=}")
            print(f"{len(ipython_shell.user_ns['In'])=}")
            print(f"{ipython_shell.user_ns['In'][-1].splitlines()[0]=}")
            """
        ),
        md(
            """
            **Out-of-order hazard.** Imagine these three cells are far apart in a long notebook.
            The function reads the global `tax_rate` *at call time*, so its result depends on which
            cell ran last, not on what you see above it.
            """
        ),
        code(
            """
            tax_rate = 0.18
            print(f"{tax_rate=}")
            """
        ),
        code(
            '''
            def total_with_tax(price_in_rupees: float) -> float:
                """Return the price including the current global tax rate."""
                return round(price_in_rupees * (1 + tax_rate), 2)


            print(f"{total_with_tax(100)=}")
            '''
        ),
        code(
            """
            tax_rate = 0.05  # a cell further down changes the global...
            print(f"{total_with_tax(100)=}")  # ...and the function's answer changes with it
            """
        ),
        md(
            """
            > **Warning:** a notebook that only works in the order you happened to run it is broken.
            > Before saving or committing, use **Restart & Run All** (JupyterLab: *Kernel* menu;
            > VS Code: *Restart* then *Run All*). This course verifies every notebook the same way:
            > `jupyter nbconvert --execute` runs all cells top to bottom in a fresh kernel.
            """
        ),
        md("#### Predict the output"),
        md(
            """
            **Predict the output.**

            ```python
            # cell 1
            6 * 7
            # cell 2
            print(_ + 1)
            ```

            <details><summary>Answer</summary>

            `43`. When a cell ends in an expression, IPython displays it and stores it in `_`
            (and in `Out[n]`). The next cell reads it back. `__` and `___` hold the two results
            before that. (`_` is created by IPython at run time, so the proof cell tells ruff not
            to report it as undefined with `# noqa: F821`.)

            </details>
            """
        ),
        md("Run the next two cells to check your prediction."),
        code(
            """
            6 * 7
            """
        ),
        code(
            """
            print(_ + 1)  # noqa: F821
            """
        ),
        *predict_cells(
            snippet="""
            # cell A (later deleted from the notebook, but it already ran)
            greeting = "hello"
            # cell B
            print(greeting)
            # What does cell B print now, and what after Restart & Run All?
            """,
            answer="""
            Now: `hello`, because the variable is still alive in the kernel. After Restart & Run
            All: `NameError`, because no remaining cell defines `greeting`. The proof simulates the
            restart with `del`.
            """,
            proof="""
            greeting = "hello"
            print(greeting)
            del greeting  # what a restart does to every variable
            try:
                print(greeting)
            except NameError as error:
                print(f"{type(error).__name__}: {error}")
            """,
        ),
        md(
            """
            ### 0.4.3 Magics

            Magics are IPython commands, not Python: `%name` applies to one line, `%%name` to the
            whole cell. They only work in IPython and Jupyter.

            | Magic | What it does |
            | --- | --- |
            | `%timeit stmt` | Runs a statement many times and reports mean ± std dev |
            | `%%time` | Times one run of the whole cell (wall and CPU) |
            | `%who` / `%whos` | Lists variables in the namespace / with type and value |
            | `%load_ext autoreload` + `%autoreload 2` | Re-imports edited modules before each cell |
            | `%%writefile path` | Writes the cell body to a file |
            | `obj?` / `obj??` | Shows the docstring and signature / plus the source |

            `%timeit` picks the loop count automatically; `-n` (loops) and `-r` (repeats) fix it so
            the cell stays fast. Timings vary by machine.
            """
        ),
        code(
            """
            %timeit -n 1000 -r 5 sum(range(1_000))
            """
        ),
        md(
            """
            `%%time` must be the first line of the cell and times everything below it once.
            """
        ),
        code(
            """
            %%time
            import random

            random.seed(42)
            random_numbers = [random.random() for _ in range(200_000)]
            sorted_numbers = sorted(random_numbers)
            print(f"{len(sorted_numbers)=}")
            """
        ),
        md(
            """
            `%who` prints the names of every variable you defined (modules included). Pass a type
            name to filter.
            """
        ),
        code(
            """
            %who float
            """
        ),
        md(
            """
            `%whos` adds the type and a preview of the value, as a table.
            """
        ),
        code(
            """
            %whos float list
            """
        ),
        md(
            """
            **Autoreload.** Normally `import` runs a module once and caches it in `sys.modules`;
            editing the file later has no effect until you restart. `%autoreload 2` reloads every
            changed module before each cell runs. The demo:

            1. load the extension,
            2. write a module with `%%writefile` into `notebooks/_scratch/`,
            3. import it and call it,
            4. rewrite the file and call again **without** re-importing.

            `%%writefile {path}` expands Python variables in braces, so the module path comes from
            `scratch_dir`.
            """
        ),
        code(
            """
            %load_ext autoreload
            %autoreload 2
            greeting_module_path = scratch_dir / "greeting_tools.py"
            if str(scratch_dir) not in sys.path:
                sys.path.insert(0, str(scratch_dir))
            """
        ),
        code(
            '''
            %%writefile {greeting_module_path}
            def greet(name: str) -> str:
                """Return a greeting for name."""
                return f"Hello, {name}!"
            '''
        ),
        code(
            """
            import greeting_tools

            print(greeting_tools.greet("Asha"))
            """
        ),
        md(
            """
            Now rewrite the module on disk. No restart and no new `import`.
            """
        ),
        code(
            '''
            %%writefile {greeting_module_path}
            def greet(name: str) -> str:
                """Return a warmer greeting for name."""
                return f"Namaste, {name}! Welcome to Python 3.15."
            '''
        ),
        md(
            """
            Calling the same function again picks up the new code, because autoreload re-imported
            the changed file before this cell ran.
            """
        ),
        code(
            """
            print(greeting_tools.greet("Asha"))
            """
        ),
        md(
            """
            **`?` and `??`.** `find_repo_root?` shows the signature and docstring; `find_repo_root??`
            also shows the source. JupyterLab shows the result in a pager and VS Code in the output
            area; when the notebook is executed headless (as this course's build does) the pager
            text is not stored, so the cells may look empty in the saved file.
            """
        ),
        code(
            """
            find_repo_root?
            """
        ),
        code(
            """
            find_repo_root??
            """
        ),
        md(
            """
            Under the hood `?` uses the `inspect` module, which works anywhere, not just in IPython:
            """
        ),
        code(
            """
            print(f"{inspect.signature(find_repo_root)=}")
            print(f"{inspect.getdoc(find_repo_root)=}")
            """
        ),
        md(
            """
            **Why `uv add` beats `%pip install`.**

            | | `%pip install pkg` in a cell | `uv add pkg` in a terminal |
            | --- | --- | --- |
            | Recorded in `pyproject.toml` | no | yes |
            | Recorded in `uv.lock` | no | yes, with hashes |
            | Survives `uv sync` | **no**: `uv sync` removes packages that are not in the lock | yes |
            | Reproducible for teammates and CI | no | yes |

            ```bash
            uv add httpx          # then restart the kernel so it sees the new package
            ```

            > **Warning:** never put `%pip install` or `!uv add` in a course notebook. A notebook
            > that installs packages changes the environment every time someone runs it.
            """
        ),
        md(
            """
            ### 0.4.4 Notebooks are JSON

            An `.ipynb` file is a JSON document: top-level `metadata`, `nbformat` version, and a
            list of `cells`, each with `cell_type`, `source`, and (for code) `outputs`.
            `nbformat` reads and validates it. The cell loads **this notebook** and counts its cells
            by type.

            > **Note:** it reads the copy on disk, i.e. the last saved version, not unsaved edits.
            """
        ),
        code(
            """
            import nbformat

            if this_notebook_path.exists():
                this_notebook = nbformat.read(this_notebook_path, as_version=4)
                cell_type_counts = Counter(cell.cell_type for cell in this_notebook.cells)
                print(f"{this_notebook.nbformat=}, {this_notebook.nbformat_minor=}")
                print(f"{this_notebook.metadata.kernelspec.name=}")
                print(f"{len(this_notebook.cells)=}")
                print(f"{dict(cell_type_counts)=}")
            else:
                print(f"Skipped: {this_notebook_path.name} not found on disk")
            """
        ),
        md(
            """
            #### Under the hood: the raw JSON

            Skipping `nbformat` and reading the file with `json` shows the storage format. Notice
            that `source` is stored as a **list of lines**; `nbformat` joins it into one string for
            you.
            """
        ),
        code(
            """
            raw_notebook = json.loads(this_notebook_path.read_text(encoding="utf-8"))
            first_code_cell = next(cell for cell in raw_notebook["cells"] if cell["cell_type"] == "code")
            print(f"{sorted(raw_notebook)=}")
            print(f"{sorted(first_code_cell)=}")
            print(f"{type(first_code_cell['source']).__name__=}")
            print(f"{first_code_cell['source'][:2]=}")
            """
        ),
        *predict_cells(
            snippet="""
            print(type(this_notebook.cells[0].source).__name__, this_notebook.cells[0].cell_type)
            """,
            answer="""
            `str markdown`. The first cell is the title (markdown), and `nbformat` returns `source`
            as one string even though the file stores a list of lines.
            """,
            proof="""
            print(type(this_notebook.cells[0].source).__name__, this_notebook.cells[0].cell_type)
            """,
        ),
        md(
            """
            ### 0.4.5 Editor setup

            | | VS Code | PyCharm |
            | --- | --- | --- |
            | Python support | *Python* extension (`ms-python.python`) + **Pylance** (built on the **pyright** type checker) | Built in (its own type checker) |
            | Notebooks | *Jupyter* extension (`ms-toolsai.jupyter`) | Built in (Professional edition) |
            | Formatting and linting | *Ruff* extension (`charliermarsh.ruff`), format on save | Ruff plugin or File Watcher |
            | Interpreter selection | *Python: Select Interpreter* → `.venv/bin/python`; notebook kernel picker → "Python 3.15 (course)" | *Settings → Python Interpreter* → existing uv environment |

            The repository ships VS Code settings so the right interpreter and formatter are used
            automatically. The cell prints them and the `[tool.ruff]` section they rely on.
            """
        ),
        code(
            """
            import tomllib

            vscode_dir = repo_root / ".vscode"
            for settings_name in ["settings.json", "extensions.json"]:
                settings_path = vscode_dir / settings_name
                if settings_path.exists():
                    print(f"{settings_name}: {json.loads(settings_path.read_text(encoding='utf-8'))}")
                else:
                    print(f"Skipped: {settings_name} not found")

            ruff_config = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
            print(f"[tool.ruff]: {ruff_config['tool']['ruff']}")
            """
        ),
        md(
            """
            ### 0.4.6 Jupytext

            Notebook JSON makes noisy git diffs: outputs, execution counts and metadata change on
            every run. [Jupytext](https://jupytext.readthedocs.io/) can **pair** an `.ipynb` with a
            plain `.py` file in the *percent* format, where `# %%` starts a code cell and
            `# %% [markdown]` a markdown cell. Reviewers read the `.py` diff.

            ```bash
            uv run jupytext --set-formats ipynb,py:percent notebooks/example.ipynb   # pair
            uv run jupytext --sync notebooks/example.ipynb                           # update the older side
            ```

            > **Note:** this course does not pair its notebooks, because the build scripts in
            > `scripts/` are already the readable source. The cell converts this notebook in memory
            > only, to show the format.
            """
        ),
        code(
            """
            import jupytext

            percent_script = jupytext.writes(this_notebook, fmt="py:percent")
            percent_lines = percent_script.splitlines()
            first_cell_line = percent_lines.index("# %% [markdown]")
            print("\\n".join(percent_lines[first_cell_line : first_cell_line + 12]))
            print(f"... {len(percent_lines)} lines in total")
            """
        ),
        md(
            """
            The same notebook as percent script is much smaller than the JSON, mainly because
            outputs and metadata are left out.
            """
        ),
        code(
            """
            json_size = len(this_notebook_path.read_text(encoding="utf-8"))
            print(f"{json_size=} characters, {len(percent_script)=} characters")
            """
        ),
        md(
            """
            ### 0.4.7 Introspection toolkit

            Six built-ins answer "what is this object?". They work on everything, because in Python
            everything is an object. This small class is the subject for each demo.
            """
        ),
        code(
            '''
            class ShoppingCart:
                """A minimal cart used to demonstrate introspection tools."""

                def __init__(self, owner_name: str) -> None:
                    self.owner_name = owner_name
                    self.item_prices_in_rupees: list[float] = []

                def add_item(self, price_in_rupees: float) -> None:
                    """Add one item's price to the cart."""
                    self.item_prices_in_rupees.append(price_in_rupees)

                def total(self) -> float:
                    """Return the sum of all item prices."""
                    return sum(self.item_prices_in_rupees)


            cart = ShoppingCart("Asha")
            cart.add_item(499.0)
            cart.add_item(150.5)
            print(f"{cart.total()=}")
            '''
        ),
        md(
            """
            `help(obj)` prints the signature and docstring (the same text `?` shows).
            """
        ),
        code(
            """
            help(ShoppingCart.add_item)
            """
        ),
        md(
            """
            `dir(obj)` lists every attribute name, including inherited dunder methods. Filtering out
            names that start with `_` leaves the public API.
            """
        ),
        code(
            """
            all_attribute_names = dir(cart)
            public_attribute_names = [name for name in all_attribute_names if not name.startswith("_")]
            print(f"{len(all_attribute_names)=}")
            print(f"{public_attribute_names=}")
            """
        ),
        md(
            """
            `type(obj)` returns the object's class. Classes are objects too, and their type is
            `type`.
            """
        ),
        code(
            """
            print(f"{type(cart)=}")
            print(f"{type(cart.total)=}")
            print(f"{type(ShoppingCart)=}")
            """
        ),
        md(
            """
            `id(obj)` is an integer that is unique among objects alive at the same time (in CPython
            it is the memory address). Compare ids, never their values: the number changes on every
            run.
            """
        ),
        code(
            """
            same_cart = cart
            other_cart = ShoppingCart("Ravi")
            print(f"{id(cart) == id(same_cart)=}")
            print(f"{id(cart) == id(other_cart)=}")
            print(f"{cart is same_cart=}")
            """
        ),
        md(
            """
            `vars(obj)` returns the object's `__dict__`: only its **own** attributes. Methods live
            on the class, so they do not appear.
            """
        ),
        code(
            """
            print(f"{vars(cart)=}")
            print(f"{'total' in vars(ShoppingCart)=}")
            """
        ),
        md(
            """
            `inspect.getsource(obj)` returns the source code. It works for functions and classes
            defined in files or notebook cells, and raises `TypeError` for built-ins written in C.
            """
        ),
        code(
            """
            print(inspect.getsource(ShoppingCart.total))
            try:
                inspect.getsource(len)
            except TypeError as error:
                print(f"{type(error).__name__}: {error}")
            """
        ),
        md("#### Predict the output"),
        *predict_cells(
            snippet="""
            print(type(type), type(ShoppingCart) is type)
            """,
            answer="""
            `<class 'type'> True`. `type` is its own type: it is the class of every class
            (a *metaclass*, covered in Phase 2).
            """,
            proof="""
            print(type(type), type(ShoppingCart) is type)
            """,
        ),
        *predict_cells(
            snippet="""
            empty_cart = ShoppingCart("Meera")
            print(list(vars(empty_cart)))
            """,
            answer="""
            `['owner_name', 'item_prices_in_rupees']`. Only attributes assigned on `self` in
            `__init__` are in the instance `__dict__`, in assignment order; `add_item` and `total`
            belong to the class.
            """,
            proof="""
            empty_cart = ShoppingCart("Meera")
            print(list(vars(empty_cart)))
            """,
        ),
        md(
            """
            ### Lab 0

            Write `environment_report()` that **returns** a dict describing the running interpreter
            and also **prints** it, one `key: value` per line. Required keys:

            | Key | Value |
            | --- | --- |
            | `python_version` | the version string, e.g. `'3.15.1'` (`platform.python_version()`) |
            | `implementation` | e.g. `'CPython'` (`platform.python_implementation()`) |
            | `executable` | `sys.executable` |
            | `in_virtualenv` | `True` when a virtual environment is active |
            | `jupyterlab_version` | installed JupyterLab version via `importlib.metadata.version` |

            Replace the `raise` in the stub with your implementation, then run the check cell.
            Until then every check prints FAIL with `NotImplementedError`; that is expected.
            """
        ),
        code(
            '''
            import importlib.metadata
            import platform


            def environment_report() -> dict[str, str | bool]:
                """Return and print a description of the running Python environment."""
                raise NotImplementedError("Lab 0: implement environment_report()")
            '''
        ),
        md(
            """
            The check cell compares your report with values computed independently. It silences
            the report's printing (`redirect_stdout`) so the PASS/FAIL lines stay readable.
            """
        ),
        code(
            '''
            import contextlib
            import io


            def quiet_report() -> dict[str, str | bool]:
                """Call environment_report() without letting its prints reach the output."""
                with contextlib.redirect_stdout(io.StringIO()):
                    return environment_report()


            expected_keys = [
                "python_version",
                "implementation",
                "executable",
                "in_virtualenv",
                "jupyterlab_version",
            ]
            run_checks(
                [
                    ("returns a dict", lambda: isinstance(quiet_report(), dict), True),
                    ("has exactly the five keys", lambda: sorted(quiet_report()), sorted(expected_keys)),
                    ("python_version", lambda: quiet_report()["python_version"], platform.python_version()),
                    (
                        "implementation",
                        lambda: quiet_report()["implementation"],
                        platform.python_implementation(),
                    ),
                    ("executable", lambda: quiet_report()["executable"], sys.executable),
                    (
                        "in_virtualenv",
                        lambda: quiet_report()["in_virtualenv"],
                        sys.prefix != sys.base_prefix,
                    ),
                    (
                        "jupyterlab_version",
                        lambda: quiet_report()["jupyterlab_version"],
                        importlib.metadata.version("jupyterlab"),
                    ),
                ]
            )
            '''
        ),
        md(
            """
            ### Recap — Unit 0.4

            | Concept | One-line takeaway | JS equivalent |
            | --- | --- | --- |
            | Server / kernel / file | UI, execution process and JSON document are separate pieces | Browser tab, JS engine, saved `.js` |
            | Kernelspec | Tells front ends which interpreter to start; registered with `ipykernel install` | Choosing the Node binary |
            | Execution order | State lives in the kernel; only Restart & Run All proves a notebook works | A long-lived REPL session |
            | Magics | `%timeit`, `%%time`, `%who(s)`, `%autoreload 2`, `%%writefile`, `?`/`??` | DevTools helpers like `console.time` |
            | `uv add` over `%pip` | Dependencies belong in `pyproject.toml` and `uv.lock` | `npm install` over a global install |
            | `nbformat` | Notebooks are JSON you can read and generate | `JSON.parse` on a file |
            | Jupytext | Pairs `.ipynb` with a diff-friendly `.py:percent` script | — |
            | Introspection | `help`, `dir`, `type`, `id`, `vars`, `inspect.getsource` | `console.dir`, `typeof`, `fn.toString()` |

            **Further reading**

            - [IPython built-in magic commands](https://ipython.readthedocs.io/en/stable/interactive/magics.html),
              [autoreload](https://ipython.readthedocs.io/en/stable/config/extensions/autoreload.html)
            - [Jupyter architecture](https://docs.jupyter.org/en/latest/projects/architecture/content-architecture.html),
              [nbformat](https://nbformat.readthedocs.io/),
              [Jupytext formats](https://jupytext.readthedocs.io/en/latest/formats-scripts.html)
            - [`inspect` — Inspect live objects](https://docs.python.org/3/library/inspect.html),
              [built-in functions (`dir`, `vars`, `id`, `type`, `help`)](https://docs.python.org/3/library/functions.html)
            - [uv: using uv with Jupyter](https://docs.astral.sh/uv/guides/integration/jupyter/),
              [PEP 8 — Style guide](https://peps.python.org/pep-0008/)
            """
        ),
    ]
