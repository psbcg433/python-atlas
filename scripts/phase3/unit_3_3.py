"""Unit 3.3 — Modules, Packages and the Import System (with Lab 3.3)."""

from nbformat import NotebookNode

from nb_builder import code, md, predict_cells

UNIT_SETUP_SOURCE = '''
import ast
import importlib
import importlib.abc
import importlib.machinery
import importlib.metadata
import importlib.resources
import importlib.util
import json
import os
import pkgutil
import platform
import shutil
import site
import subprocess
import sys
import sysconfig
import tempfile
import textwrap
import types
import zipfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

CHILD_ENV = {**os.environ, "PYTHON_COLORS": "0"}  # plain output from child interpreters
scratch_dir = find_repo_root() / "notebooks" / "_scratch"  # git-ignored
scratch_dir.mkdir(parents=True, exist_ok=True)
KERNEL_PATH_AT_START = list(sys.path)  # compared again after the demos


def raised_error_name(thunk: Callable[[], object]) -> str:
    """Call thunk and return the name of the exception it raised, or "no error"."""
    try:
        thunk()
    except Exception as error:
        return type(error).__name__
    return "no error"


def raised_message(thunk: Callable[[], object]) -> str:
    """Call thunk and return "ErrorName: message" for the exception it raised, or "no error"."""
    try:
        thunk()
    except Exception as error:
        return f"{type(error).__name__}: {error}"
    return "no error"


def compile_error(source: str) -> str:
    """Compile without running; return "SyntaxError: <msg>" or "compiles"."""
    try:
        compile(source, "<demo>", "exec")
    except SyntaxError as error:
        return f"SyntaxError: {error.msg}"
    return "compiles"


def interpreter_label() -> str:
    """Implementation, version and build flavour of the running interpreter."""
    free_threaded = bool(sysconfig.get_config_var("Py_GIL_DISABLED"))
    build = "free-threaded build" if free_threaded else "default (GIL) build"
    implementation = platform.python_implementation()
    return f"{implementation} {platform.python_version()}, {build}, {platform.machine()}"


def run_python(
    *arguments: str, cwd: Path | None = None, extra_env: dict[str, str] | None = None
) -> str:
    """Run the kernel's interpreter in a child process; return its output, stripped.

    The folder passed as cwd is shown as <project>, so no absolute path is printed.
    """
    completed = subprocess.run(
        [sys.executable, *arguments],
        capture_output=True, text=True, cwd=cwd, timeout=120,
        env={**CHILD_ENV, **(extra_env or {})},
    )  # fmt: skip
    output = (completed.stdout + completed.stderr).strip()
    return output.replace(str(cwd), "<project>") if cwd is not None else output


@contextmanager
def scratch_project(name: str, files: dict[str, str]) -> Iterator[Path]:
    """Write files under notebooks/_scratch/<name>/ for a child process; delete them afterwards."""
    root = scratch_dir / name
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    for relative_path, text in files.items():
        target = root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(textwrap.dedent(text).lstrip("\\n"))
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


def run_script(
    root: Path, script: str, *arguments: str, extra_env: dict[str, str] | None = None
) -> str:
    """Save script as root/main.py and run it in a child interpreter from root.

    The child's sys.path[0] is root, so the project's modules are imported there, never in
    the kernel.
    """
    (root / "main.py").write_text(textwrap.dedent(script).lstrip("\\n"))
    return run_python("main.py", *arguments, cwd=root, extra_env=extra_env)


def in_src(files: dict[str, str]) -> dict[str, str]:
    """The same files moved into src/, a folder the script adds to sys.path itself."""
    return {f"src/{relative_path}": text for relative_path, text in files.items()}


def child_json(output: str) -> object:
    """Parse the last line of a child's output as JSON; raise with the child's error if not."""
    last_line = output.splitlines()[-1] if output else ""
    try:
        return json.loads(last_line)
    except ValueError:
        raise RuntimeError(f"child process failed: {last_line}") from None


def _comes_from(module: object, folder: str) -> bool:
    """Was this module loaded from somewhere under folder?"""
    spec = getattr(module, "__spec__", None)
    locations = [
        getattr(spec, "origin", None) or "",
        *(getattr(spec, "submodule_search_locations", None) or []),
    ]
    return any(str(location).startswith(folder) for location in locations)


@contextmanager
def temporary_modules(files: dict[str, str], *, zipped: bool = False) -> Iterator[Path]:
    """For lab checks that must import into the kernel: write files under notebooks/_scratch
    (or zip them), put the folder first on sys.path, and on exit remove it and forget every
    module imported from it."""
    with tempfile.TemporaryDirectory(prefix="unit33_lab_", dir=scratch_dir) as folder:
        root = Path(folder) / "src"
        root.mkdir()
        for relative_path, text in files.items():
            target = root / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(textwrap.dedent(text))
        entry = root
        if zipped:
            entry = Path(folder) / "bundle.zip"
            with zipfile.ZipFile(entry, "w") as archive:
                for path in sorted(root.rglob("*")):
                    if path.is_file():
                        archive.write(path, path.relative_to(root).as_posix())
        sys.path.insert(0, str(entry))
        importlib.invalidate_caches()
        try:
            yield root
        finally:
            sys.path.remove(str(entry))
            sys.path_importer_cache.pop(str(entry), None)
            for name, module in list(sys.modules.items()):
                if _comes_from(module, folder):
                    del sys.modules[name]
            importlib.invalidate_caches()


print(interpreter_label())
'''


def _overview_cells() -> list[NotebookNode]:
    """Unit opener and setup."""
    return [
        md(
            """
            ## Unit 3.3 — Modules, Packages and the Import System

            **Objectives**

            - Treat modules as ordinary objects and read their metadata (`__spec__`,
              `__loader__`, `__path__`).
            - Describe exactly what `import x` does: the `sys.modules` cache, finders on
              `sys.meta_path`, loaders, execution and name binding.
            - Predict the effect of every import form, including `from x import *`, and why
              `from x import y` copies a binding.
            - Explain how `sys.path` is built and how `python -m`, `python file.py` and
              `python -P` differ.
            - Structure packages (regular and namespace), choose between absolute and relative
              imports, and write entry points.
            - Diagnose and fix circular imports.
            - Use `importlib`, `importlib.resources`, `importlib.metadata` and `pkgutil`;
              write an import hook; cut startup time with lazy imports (*New in 3.15*).

            **JS bridge**

            | JavaScript (Node.js) | Python | The difference that bites |
            | --- | --- | --- |
            | `require.cache` | `sys.modules` | Both run a module once and cache it; Python's cache is an ordinary dict you can edit |
            | ESM `import { x } from "./m.js"` (live binding) | `from m import x` (a **copy** of the binding) | Rebinding `m.x` later does not change your `x` |
            | `node_modules` lookup, walking up the directories | A flat list, `sys.path`, searched in order | No per-folder dependency trees; one version per environment |
            | `package.json` `"main"` / `"exports"` | `__init__.py`, `__all__` | `__init__.py` is code that runs on import |
            | `require.main === module` | `if __name__ == "__main__":` | Same idea |
            | Circular `require` returns a partial `exports` | Circular import sees a *partially initialized module* | Same root cause, different error |
            | `import()` (dynamic) | `importlib.import_module(name)` | Python's is synchronous |
            | Hoisted, static ESM imports | `import` is a statement executed in order | Imports can sit inside functions and `if` blocks |

            **How the demos run.** Importing a throwaway module into this kernel would leave it
            in `sys.modules` (and its folder in `sys.path`) for the rest of the notebook. So
            every import demo writes its small project under `notebooks/_scratch/` with
            `scratch_project(name, files)` and runs it in a **child interpreter** with
            `run_script(root, script)`, which saves the script as `main.py` in that folder and
            runs it from there. The folder is deleted afterwards, and absolute paths in the
            child's output are shown as `<project>`. A check after 3.3.13 proves the kernel
            stayed clean.
            """
        ),
        code(UNIT_SETUP_SOURCE),
    ]


def _module_object_cells() -> list[NotebookNode]:
    """3.3.1 Modules as objects."""
    return [
        md(
            """
            ### 3.3.1 Modules as objects

            A module is an instance of `types.ModuleType` whose `__dict__` is the module's
            global namespace. Its special attributes record where it came from:

            | Attribute | Meaning | Example (`json.decoder`) |
            | --- | --- | --- |
            | `__name__` | Fully qualified name | `"json.decoder"` |
            | `__file__` | Source or extension file (absent for built-in and namespace modules) | `.../json/decoder.py` |
            | `__spec__` | `ModuleSpec`: name, loader, origin, search locations; the import system's record | `ModuleSpec(name='json.decoder', ...)` |
            | `__loader__` | The object that executed the module | `SourceFileLoader` |
            | `__package__` | Package used to resolve relative imports | `"json"` |
            | `__path__` | **Packages only**: where to look for submodules | `[".../json"]` |

            **`types.ModuleType`.** You can create a module by hand and run code in its
            namespace; that is essentially what a loader does.
            """
        ),
        code(
            """
            pricing = types.ModuleType("pricing", "Hand-made module for GST maths.")
            exec(
                "GST_RATE = 0.18\\ndef with_gst(amount):\\n    return round(amount * (1 + GST_RATE), 2)",
                pricing.__dict__,
            )
            print(f"{type(pricing).__name__=}  {pricing.__name__=}  {pricing.__doc__=}")
            print(f"{pricing.with_gst(100)=}")
            print(
                f"{pricing.with_gst.__globals__ is vars(pricing)=}  (the module dict is the functions' globals)"
            )
            print(f"{type(json) is types.ModuleType=}")
            """
        ),
        md(
            """
            **`__name__` and `__package__`.** A package's `__package__` is its own name; a
            submodule's is the package it lives in. A top-level module has `""`.
            """
        ),
        code(
            """
            import json.decoder

            for module in (json, json.decoder, textwrap):
                print(f"{module.__name__:<13} __package__={module.__package__!r}")
            """
        ),
        md(
            """
            **`__file__` and `__path__`.** Only packages have `__path__`. Built-in modules
            (compiled into the interpreter) have no `__file__`. File names only are printed.
            """
        ),
        code(
            """
            for module in (json, json.decoder, sys):
                file_name = Path(module.__file__).name if getattr(module, "__file__", None) else None
                package_path = [Path(entry).name for entry in getattr(module, "__path__", [])] or None
                print(f"{module.__name__:<13} __file__={file_name!r:<16} __path__={package_path}")
            """
        ),
        md(
            """
            **`__spec__` and `__loader__`.** The spec is what the finder returned; the loader
            is what ran the module. Different kinds of module have different loaders.
            """
        ),
        code(
            """
            for module in (
                json.decoder,
                sys,
                importlib.util.module_from_spec(importlib.util.find_spec("zipimport")),
            ):
                spec = module.__spec__
                origin = spec.origin if spec.origin in {"built-in", "frozen"} else Path(spec.origin).name
                loader = module.__loader__
                loader_name = loader.__name__ if isinstance(loader, type) else type(loader).__name__
                print(f"{spec.name:<13} origin={origin!r:<14} loader={loader_name}")
            print(f"{json.decoder.__spec__.parent=}  {json.__spec__.submodule_search_locations is not None=}")
            """
        ),
    ]


def _import_steps_cells() -> list[NotebookNode]:
    """3.3.2 What import does."""
    return [
        md(
            """
            ### 3.3.2 What `import` does

            ```mermaid
            flowchart TD
                A["import checkout_rules"] --> B{"in sys.modules?"}
                B -- yes --> H["bind the name"]
                B -- no --> C["ask each finder on sys.meta_path: find_spec(name, path)"]
                C -- "all return None" --> E["ModuleNotFoundError"]
                C -- "a ModuleSpec" --> D["loader.create_module(spec) or a new ModuleType"]
                D --> F["sys.modules[name] = module  (BEFORE running it)"]
                F --> G["loader.exec_module(module): run its code"]
                G --> H
            ```

            <details><summary>ASCII fallback</summary>

            ```text
            import x
              1. x in sys.modules?            yes -> step 6
              2. for finder in sys.meta_path: spec = finder.find_spec("x", path)   (None = next finder)
                 no finder found it           -> ModuleNotFoundError
              3. module = spec.loader.create_module(spec) or ModuleType("x")
              4. sys.modules["x"] = module    (inserted before execution: this is what makes cycles possible)
              5. spec.loader.exec_module(module)   (runs the module's code in module.__dict__)
              6. bind the name x in the importing namespace
            ```

            </details>

            **Step 1, the cache.** A second import of the same name is a dict lookup. Whatever
            object sits in `sys.modules` **is** the module, even a fake one. (The script runs in
            a child interpreter, so the fake never reaches this kernel.)
            """
        ),
        code(
            '''
            CACHE_DEMO = """
            import json
            import json as json_again
            import sys
            import types

            print("json_again is json is sys.modules['json']:", json_again is json is sys.modules["json"])
            sys.modules["fake_payments"] = types.SimpleNamespace(charge=lambda amount: f"faked {amount}")
            import fake_payments

            print("fake_payments.charge(99) ->", fake_payments.charge(99), "(whatever was cached)")
            """
            print(run_python("-c", textwrap.dedent(CACHE_DEMO)))
            '''
        ),
        md(
            """
            **Step 2, the finders.** `sys.meta_path` lists finder objects, asked in order.
            `importlib.util.find_spec(name)` runs the same search **without executing**
            anything, so it is safe to call in the kernel.
            """
        ),
        code(
            """
            finder_names = [getattr(finder, "__name__", type(finder).__name__) for finder in sys.meta_path]
            print(f"{finder_names=}")
            for name in ("sys", "zipimport", "json", "_json", "no_such_module_here"):
                spec = importlib.util.find_spec(name)
                if spec is None:
                    where = "None (ModuleNotFoundError on import)"
                elif spec.origin in {"built-in", "frozen"}:
                    where = spec.origin
                else:
                    where = Path(spec.origin).name
                print(f"find_spec({name!r:<22}) -> {where}")
            """
        ),
        md(
            """
            **Watching the steps.** A finder at the front of `sys.meta_path` that only records
            requests shows which imports reach the finders: `checkout_rules` and its helper do,
            the already-cached `json` and `sys` do not. Inside the module,
            `__name__ in sys.modules` is already `True` while its code runs (step 4 before
            step 5).
            """
        ),
        code(
            '''
            TRACING_FILES = {
                "checkout_rules.py": """
                    import json
                    import sys

                    import checkout_helpers

                    IN_SYS_MODULES_WHILE_RUNNING = __name__ in sys.modules
                    """,
                "checkout_helpers.py": "FREE_SHIPPING_ABOVE = 499\\n",
            }
            TRACING_SCRIPT = """
            import json  # loaded before the tracer is installed, so later imports hit the cache
            import sys


            class TracingFinder:
                # A meta path finder that records requests and lets the next finder answer.
                def __init__(self):
                    self.requests = []

                def find_spec(self, fullname, path, target=None):
                    self.requests.append(fullname)
                    return None


            tracer = TracingFinder()
            sys.meta_path.insert(0, tracer)
            import checkout_rules

            sys.meta_path.remove(tracer)
            print("requests that reached the finders:", tracer.requests)
            print("in sys.modules while its code ran:", checkout_rules.IN_SYS_MODULES_WHILE_RUNNING)
            """
            with scratch_project("unit33_tracing", TRACING_FILES) as root:
                print(run_script(root, TRACING_SCRIPT))
            '''
        ),
        md(
            """
            **The whole algorithm in a few lines.** `simple_import` follows the steps for a
            top-level module with the real `importlib` building blocks (the real code also
            handles packages, parent imports and locking).
            """
        ),
        code(
            '''
            SIMPLE_IMPORT_SCRIPT = """
            import importlib.util
            import sys


            def simple_import(module_name):
                # The core of `import module_name` for a top-level module.
                if module_name in sys.modules:  # 1. cache
                    return sys.modules[module_name]
                spec = importlib.util.find_spec(module_name)  # 2. finders
                if spec is None:
                    raise ModuleNotFoundError(f"No module named {module_name!r}")
                module = importlib.util.module_from_spec(spec)  # 3. create
                sys.modules[module_name] = module  # 4. insert before executing
                try:
                    spec.loader.exec_module(module)  # 5. execute
                except BaseException:
                    del sys.modules[module_name]
                    raise
                return module  # 6. the caller binds the name


            discounts = simple_import("discounts")
            print("FESTIVE =", discounts.FESTIVE)
            print("cached on the second call:", simple_import("discounts") is discounts)
            try:
                simple_import("no_such_discounts")
            except ModuleNotFoundError as error:
                print("ModuleNotFoundError:", error)
            """
            discount_files = {"discounts.py": "print('discounts executing')\\nFESTIVE = 0.1\\n"}
            with scratch_project("unit33_simple_import", discount_files) as root:
                print(run_script(root, SIMPLE_IMPORT_SCRIPT))
            '''
        ),
    ]


def _import_forms_cells() -> list[NotebookNode]:
    """3.3.3 Import forms."""
    return [
        md(
            """
            ### 3.3.3 Import forms

            | Form | Binds | Notes |
            | --- | --- | --- |
            | `import config` | `config` → the module | Attribute access later sees changes |
            | `import shop.cart` | `shop` → the **package** | Imports `shop` first; use `shop.cart.Cart` |
            | `import shop.cart as cart` | `cart` → the submodule | Alias |
            | `from config import DEBUG` | `DEBUG` → the object `config.DEBUG` pointed to **at that moment** | A copy of the binding |
            | `from config import DEBUG as debug_flag` | `debug_flag` | Alias |
            | `from config import *` | every name in `config.__all__`, or every public name (no leading `_`) | Avoid outside the REPL and `__init__.py` re-exports |

            The cell builds a `config` module and a small `shop` package and tries each form in
            a child interpreter.
            """
        ),
        code(
            '''
            FORM_FILES = {
                "config.py": """
                    __all__ = ["DEBUG", "region"]
                    DEBUG = False
                    _SECRET = "hidden"
                    TIMEOUT = 30

                    def region():
                        return "south"
                    """,
                "shop/__init__.py": "",
                "shop/cart.py": "class Cart:\\n    pass\\n",
            }
            FORMS_SCRIPT = """
            import shop.cart

            print("import shop.cart binds", repr(shop.__name__), "and reaches", shop.cart.Cart.__name__)
            import shop.cart as cart_module

            print("import shop.cart as cart_module ->", repr(cart_module.__name__))
            from config import region as region_name

            print("from config import region as region_name ->", repr(region_name()))
            star_namespace = {}
            exec("from config import *", star_namespace)
            star_names = sorted(name for name in star_namespace if not name.startswith("__"))
            print("from config import * ->", star_names, "(__all__ wins over TIMEOUT)")
            """
            with scratch_project("unit33_forms", FORM_FILES) as root:
                print(run_script(root, FORMS_SCRIPT))
            '''
        ),
        md(
            """
            **Copied bindings.** `from config import DEBUG` creates a new name bound to the
            same object. Rebinding `config.DEBUG` afterwards changes the module's name, not
            yours. Code that must see updates should use `config.DEBUG` (or a function).
            Mutating a shared **mutable** object is visible through both names, because there
            is only one object.
            """
        ),
        code(
            '''
            BINDING_SCRIPT = """
            import settings
            from settings import DEBUG, FEATURE_FLAGS

            settings.DEBUG = True  # rebinding inside the module
            settings.FEATURE_FLAGS["dark_mode"] = True  # mutating the shared dict
            print("DEBUG =", DEBUG, "| settings.DEBUG =", settings.DEBUG, "(copied binding vs live attribute)")
            print("FEATURE_FLAGS =", FEATURE_FLAGS, "(same dict object, so the mutation shows)")
            """
            binding_files = {"settings.py": "DEBUG = False\\nFEATURE_FLAGS = {'dark_mode': False}\\n"}
            with scratch_project("unit33_bindings", binding_files) as root:
                print(run_script(root, BINDING_SCRIPT))
            '''
        ),
    ]


def _run_once_cells() -> list[NotebookNode]:
    """3.3.4 Modules run once."""
    return [
        md(
            """
            ### 3.3.4 Modules run once

            A module's top-level code runs on the **first** import only. That gives two things:

            - **Import-time side effects** (prints, network calls, reading files, registering
              handlers) happen once, at a time you may not control. Keep module top levels
              cheap and free of I/O.
            - **Module singletons.** A module-level object is shared by every importer: the
              Pythonic singleton (Unit 2.6).
            """
        ),
        code(
            '''
            SINGLETON_FILES = {
                "app_state.py": """
                    print("app_state: top-level code runs")
                    connection_pool = {"opened": 0}

                    def open_connection():
                        connection_pool["opened"] += 1
                        return connection_pool["opened"]
                    """,
                "billing.py": "import app_state\\n\\ndef charge():\\n    return app_state.open_connection()\\n",
                "shipping.py": "import app_state\\n\\ndef ship():\\n    return app_state.open_connection()\\n",
            }
            SINGLETON_SCRIPT = """
            import billing
            import shipping

            print("billing.charge() =", billing.charge(), "| shipping.ship() =", shipping.ship(), "(one pool)")
            print("billing.app_state is shipping.app_state:", billing.app_state is shipping.app_state)
            """
            with scratch_project("unit33_singleton", SINGLETON_FILES) as root:
                print(run_script(root, SINGLETON_SCRIPT))
            '''
        ),
        md(
            """
            **`importlib.reload` caveats.** `reload(module)` re-executes the module's code
            **in the same module object**. It does not update:

            - names copied with `from module import name`,
            - instances of classes defined in the module (they keep the **old** class, so
              `isinstance` against the new class fails),
            - other modules that hold references to old functions.

            Use it in a REPL, not as a deployment mechanism; restart the process instead.
            (The script replaces `rates.py` with a file of a different size on purpose: a
            same-size rewrite within the same second would leave the timestamp-based `.pyc`
            looking valid, 3.2.13, and `reload` would run the old bytecode.)
            """
        ),
        code(
            '''
            RELOAD_SCRIPT = """
            import importlib
            from pathlib import Path

            import rates
            from rates import GST

            old_rate = rates.Rate()
            Path("rates.py").write_text(Path("rates_v2.txt").read_text())
            importlib.invalidate_caches()
            reloaded = importlib.reload(rates)
            print("reloaded is rates:", reloaded is rates, "(same module object)")
            print("rates.GST =", rates.GST, "| copied GST =", GST, "(the copied name is stale)")
            print("old instance of new class:", isinstance(old_rate, rates.Rate), "(old object, new class)")
            """
            reload_files = {
                "rates.py": "class Rate:\\n    pass\\n\\nGST = 0.18\\n",
                "rates_v2.txt": "class Rate:\\n    pass\\n\\nGST = 0.12  # festive rate\\n",
            }
            with scratch_project("unit33_reload", reload_files) as root:
                print(run_script(root, RELOAD_SCRIPT))
            '''
        ),
    ]


def _sys_path_cells() -> list[NotebookNode]:
    """3.3.5 sys.path."""
    return [
        md(
            """
            ### 3.3.5 `sys.path`

            The path-based finder searches the folders (and zip files) in `sys.path`, in
            order. At start-up it is built from:

            1. The **script's folder** (`python app.py`) or the **current directory**
               (`python -m pkg`, `python -c`, the REPL). Skipped with `python -P` or
               `PYTHONSAFEPATH=1` (*New in 3.11*).
            2. `PYTHONPATH` entries.
            3. The standard library: a zip (`python315.zip`), the `python3.15` folder,
               `lib-dynload` (C extensions).
            4. `site-packages`, added by the `site` module at start-up, plus anything listed in
               `.pth` files found there.

            The cell labels this kernel's entries (reading `sys.path` changes nothing) instead
            of printing full paths.
            """
        ),
        code(
            '''
            def describe_path_entry(entry: str) -> str:
                """A short label for a sys.path entry."""
                path = Path(entry)
                if entry in {"", os.getcwd()}:
                    return "current directory"
                if entry.endswith(".zip"):
                    return f"{path.name} (zipped standard library)"
                if path.name == "lib-dynload":
                    return "lib-dynload (standard C extensions)"
                if "site-packages" in path.parts:
                    return "site-packages (third-party, added by site)"
                if path.name.startswith("python3"):
                    return f"{path.name} (standard library)"
                return f".../{path.name}"


            for index, entry in enumerate(sys.path):
                print(f"{index}: {describe_path_entry(entry)}")
            print(f"{sys.flags.no_site=}  {sys.flags.safe_path=}  {site.ENABLE_USER_SITE=}")
            '''
        ),
        md(
            """
            **`.pth` files.** When `site` processes a site directory, each `*.pth` file in it
            adds one path per line (relative paths are resolved against the site directory),
            and lines starting with `import` are **executed**. Editable installs
            (`uv pip install -e .`) work this way, and so does some malware; review `.pth`
            files in your environment. `site.addsitedir(folder)` processes a folder the same
            way. The child interpreter below does that with a scratch site folder.
            """
        ),
        code(
            '''
            PTH_FILES = {
                "site_folder/course_extra.pth": """
                    ../extra_folder
                    import os; os.environ["UNIT33_PTH_RAN"] = "yes"
                    """,
                "extra_folder/README.txt": "a folder named in the .pth file\\n",
            }
            PTH_SCRIPT = """
            import os
            import site
            import sys
            from pathlib import Path

            before = list(sys.path)
            site.addsitedir(str(Path("site_folder").resolve()))
            print("entries added:", [Path(entry).name for entry in sys.path if entry not in before])
            print("import line executed:", os.environ.get("UNIT33_PTH_RAN"))
            """
            with scratch_project("unit33_pth", PTH_FILES) as root:
                print(run_script(root, PTH_SCRIPT))
            '''
        ),
        md(
            """
            **`python -m` vs running a file vs `python -P`.** A tiny script reports what
            `sys.path[0]` is in each mode:

            | Command | `sys.path[0]` | Consequence |
            | --- | --- | --- |
            | `python tools/where.py` | the script's folder (`tools/`) | `import tools` fails from inside the script |
            | `python -m tools.where` | the current directory | package imports work; relative imports work |
            | `python -P tools/where.py` | the standard library | a local file named `json.py` can no longer shadow `json` |
            | `python -P -m tools.where` | the standard library | `tools` is not found unless installed |
            """
        ),
        code(
            '''
            WHERE_FILES = {
                "tools/__init__.py": "",
                "tools/where.py": """
                    import os, sys
                    first = sys.path[0]
                    script_folder = os.path.dirname(os.path.abspath(__file__))
                    if first == script_folder:
                        print("sys.path[0] = the script's folder")
                    elif first in ("", os.getcwd()):
                        print("sys.path[0] = the current directory")
                    else:
                        print("sys.path[0] = " + os.path.basename(first) + " (no script folder or cwd)")
                    """,
            }
            modes = [
                ["tools/where.py"],
                ["-m", "tools.where"],
                ["-P", "tools/where.py"],
                ["-P", "-m", "tools.where"],
            ]
            with scratch_project("unit33_sys_path", WHERE_FILES) as root:
                for arguments in modes:
                    output = run_python(*arguments, cwd=root).splitlines()[-1].split("python: ")[-1]
                    print(f"python {' '.join(arguments):<22} {output}")
            '''
        ),
    ]


def _package_cells() -> list[NotebookNode]:
    """3.3.6 Packages."""
    return [
        md(
            """
            ### 3.3.6 Packages

            A **package** is a module with a `__path__`, so it can contain submodules.

            - A **regular package** is a folder with `__init__.py`. Importing the package
              runs `__init__.py`; importing `inventory.reports.daily` runs `inventory/__init__.py`,
              then `inventory/reports/__init__.py`, then `daily.py`, parents first.
            - `__init__.py` often **re-exports** the public API (`from .stock import
              StockLevel`) so users write `from inventory import StockLevel`.
            - A **namespace package** (PEP 420) is a folder **without** `__init__.py`. Folders
              with the same name in several `sys.path` entries merge into one package; there is
              no `__init__` code and no `__file__`. Useful for plugins split across
              distributions.
            """
        ),
        code(
            '''
            INVENTORY_FILES = {
                "inventory/__init__.py": """
                    print("run inventory/__init__.py")
                    from .stock import StockLevel

                    __all__ = ["StockLevel"]
                    """,
                "inventory/stock.py": 'print("run inventory/stock.py")\\nclass StockLevel:\\n    pass\\n',
                "inventory/reports/__init__.py": 'print("run inventory/reports/__init__.py")\\n',
                "inventory/reports/daily.py": """
                    print("run inventory/reports/daily.py")
                    from ..stock import StockLevel
                    """,
            }
            PACKAGE_SCRIPT = """
            from pathlib import Path

            import inventory.reports.daily
            from inventory import StockLevel

            print("re-export is the same class:", StockLevel is inventory.stock.StockLevel)
            print("__all__ =", inventory.__all__, "| __path__ =", [Path(p).name for p in inventory.__path__])
            """
            with scratch_project("unit33_packages", INVENTORY_FILES) as root:
                print(run_script(root, PACKAGE_SCRIPT))
            '''
        ),
        md(
            """
            **Namespace packages.** Two separate folders, `first/` and `second/`, each contain a
            `plugins/` folder without `__init__.py`. With both on `sys.path`, `plugins` is one
            package whose `__path__` lists both folders.
            """
        ),
        code(
            '''
            NAMESPACE_FILES = {
                "first/plugins/csv_export.py": "FORMAT = 'csv'\\n",
                "second/plugins/pdf_export.py": "FORMAT = 'pdf'\\n",
            }
            NAMESPACE_SCRIPT = """
            import sys

            sys.path[:0] = ["first", "second"]
            import plugins
            import plugins.csv_export
            import plugins.pdf_export

            print("__path__ type:", type(plugins.__path__).__name__, "| entries:", len(list(plugins.__path__)))
            print("__file__:", getattr(plugins, "__file__", None), "| origin:", plugins.__spec__.origin)
            print("formats:", plugins.csv_export.FORMAT, plugins.pdf_export.FORMAT)
            """
            with scratch_project("unit33_namespace", NAMESPACE_FILES) as root:
                print(run_script(root, NAMESPACE_SCRIPT))
            '''
        ),
    ]


def _relative_import_cells() -> list[NotebookNode]:
    """3.3.7 Absolute vs relative imports."""
    return [
        md(
            """
            ### 3.3.7 Absolute vs relative imports

            | Style | Example | Resolved against |
            | --- | --- | --- |
            | Absolute | `from inventory.stock import StockLevel` | `sys.path` |
            | Relative, same package | `from . import formatting`, `from .stock import StockLevel` | `__package__` |
            | Relative, parent package | `from ..stock import StockLevel` | `__package__` minus one level |

            PEP 8 prefers absolute imports; relative imports are fine inside a package and
            survive renaming the top-level package. A relative import needs a known parent
            package, so it **fails when the file is run as a script**: `__package__` is empty
            and Python cannot resolve the dots. Run modules inside packages with `python -m`.
            """
        ),
        code(
            '''
            RELATIVE_FILES = {
                "inventory/__init__.py": "",
                "inventory/stock.py": "LEVEL = 7\\n",
                "inventory/reports/__init__.py": "",
                "inventory/reports/formatting.py": "def bold(text):\\n    return f'**{text}**'\\n",
                "inventory/reports/daily.py": """
                    from . import formatting
                    from ..stock import LEVEL

                    if __name__ == "__main__":
                        print(f"__package__={__package__!r}:", formatting.bold(f"stock {LEVEL}"))
                    """,
            }
            with scratch_project("unit33_relative", RELATIVE_FILES) as root:
                print(
                    "python -m inventory.reports.daily ->",
                    run_python("-m", "inventory.reports.daily", cwd=root),
                )
                script_output = run_python("inventory/reports/daily.py", cwd=root).splitlines()[-1]
                print("python inventory/reports/daily.py ->", script_output)
                imported = run_script(root, "import inventory.reports.daily as daily\\nprint(daily.__package__)")
                print(f"imported from main.py: __package__ = {imported!r}")
            '''
        ),
    ]


def _entry_point_cells() -> list[NotebookNode]:
    """3.3.8 Entry points."""
    return [
        md(
            """
            ### 3.3.8 Entry points

            - **`if __name__ == "__main__":`** A module run as the program (`python file.py`,
              `python -m pkg.module`) gets `__name__ == "__main__"`; imported, it gets its real
              name. The guard keeps "run me" code from running on import (and is required for
              `multiprocessing` on spawn platforms, Phase 5).
            - **`__main__.py`** inside a package makes `python -m package` work. Keep it a
              one-liner that calls a `main()` function, so the logic stays importable and
              testable.
            - Installed command-line tools come from `[project.scripts]` in `pyproject.toml`,
              which point at a `module:function` (Phase 4).

            `runpy.run_module(name, run_name="__main__")` is what `python -m` uses; the last
            child script calls it directly, then imports the same module normally.
            """
        ),
        code(
            '''
            GREETER_FILES = {
                "greeter/__init__.py": "",
                "greeter/__main__.py": "from greeter.cli import main\\n\\nmain()\\n",
                "greeter/cli.py": """
                    import sys

                    def main(argv=None):
                        names = (sys.argv[1:] if argv is None else argv) or ["world"]
                        print(f"[{__name__}] Namaste, " + " and ".join(names))

                    if __name__ == "__main__":
                        main()
                    """,
            }
            ENTRY_SCRIPT = """
            import runpy
            import sys

            sys.argv = ["greeter.cli", "Meena"]
            runpy.run_module("greeter.cli", run_name="__main__")  # what python -m does
            import greeter.cli

            print("import greeter.cli: main() was not called on import")
            greeter.cli.main(["Asha"])
            """
            with scratch_project("unit33_entry_points", GREETER_FILES) as root:
                print("python -m greeter Ravi ->", run_python("-m", "greeter", "Ravi", cwd=root))
                print("python -m greeter.cli  ->", run_python("-m", "greeter.cli", cwd=root))
                print(run_script(root, ENTRY_SCRIPT))
            '''
        ),
    ]


def _circular_cells() -> list[NotebookNode]:
    """3.3.9 Circular imports."""
    return [
        md(
            """
            ### 3.3.9 Circular imports

            `invoices` imports `tax`, and `tax` imports `invoices`. Importing `invoices`
            inserts a half-built `invoices` into `sys.modules`, starts running it, and its first
            line imports `tax`; `tax` then asks for `invoices.Invoice`, which does not exist yet:

            ```text
            import invoices
              invoices: sys.modules["invoices"] = <empty module>; line 1: from tax import tax_for
                tax: line 1: from invoices import Invoice
                     invoices is in sys.modules but has no Invoice yet  -> ImportError
            ```

            The modules live in `src/`, which the script puts on `sys.path`. If they sat in
            the script's own folder, 3.13+ would print a different hint, *consider renaming
            '…/invoices.py' if it has the same name as a library you intended to import*: a
            half-imported module from the script's folder is usually a file that shadows a
            standard module (a `random.py` next to your script), so CPython suggests that first.
            """
        ),
        code(
            '''
            BROKEN_INVOICES = {
                "invoices.py": """
                    from tax import tax_for

                    class Invoice:
                        def __init__(self, amount):
                            self.amount = amount

                        def total(self):
                            return self.amount + tax_for(self)
                    """,
                "tax.py": """
                    from invoices import Invoice

                    RATE = 0.18

                    def tax_for(invoice: Invoice) -> float:
                        return round(invoice.amount * RATE, 2)
                    """,
            }
            FROM_SRC = "import sys\\nsys.path.insert(0, 'src')\\n"
            with scratch_project("unit33_circular", in_src(BROKEN_INVOICES)) as root:
                print(run_script(root, FROM_SRC + "import invoices").splitlines()[-1])
            '''
        ),
        md(
            """
            Four standard fixes, each checked in child processes with the same scenario
            (`Invoice(1000).total()` should be `1180.0`), importing each module first in turn:

            | Fix | Change | When to use |
            | --- | --- | --- |
            | 1. Move shared code to a third module | Both import from a new module; neither imports the other | The best fix when the cycle reveals a misplaced piece |
            | 2. Import the **module**, not the name | `import tax` … `tax.tax_for(...)` at call time | The attribute is looked up after both modules finished |
            | 3. Import inside the function | `from tax import tax_for` inside `total()` | Quick fix; hides the dependency |
            | 4. `if TYPE_CHECKING:` | Import only for type checkers when a module needs the other **only for annotations** | Type-hint-only cycles; 3.14+ lazy annotations need no quotes |
            """
        ),
        code(
            '''
            ORDER_SCRIPT = """
            import importlib
            import sys

            sys.path.insert(0, "src")
            importlib.import_module(sys.argv[1])  # import this module first
            import invoices

            print(invoices.Invoice(1000).total())
            """


            def check_invoice_fix(files: dict[str, str]) -> str:
                """Run the scenario in child processes, importing each module first in turn."""
                totals = []
                for first_import in ("invoices", "tax"):
                    with scratch_project("unit33_circular", in_src(files)) as root:
                        totals.append(run_script(root, ORDER_SCRIPT, first_import).splitlines()[-1])
                return f"total={totals[0]} (both import orders work: {totals[0] == totals[1] == '1180.0'})"


            INVOICE_CLASS = textwrap.dedent(
                """
                class Invoice:
                    def __init__(self, amount):
                        self.amount = amount

                    def total(self):
                        return self.amount + tax_for(self)
                """
            )
            BROKEN_TAX = textwrap.dedent(BROKEN_INVOICES["tax.py"])
            invoice_fixes = {
                "1. third module": {
                    "rates.py": """
                        RATE = 0.18

                        def tax_for(invoice):
                            return round(invoice.amount * RATE, 2)
                        """,
                    "invoices.py": "from rates import tax_for\\n" + INVOICE_CLASS,
                    "tax.py": "from invoices import Invoice\\nfrom rates import RATE, tax_for\\n",
                },
                "2. module import": {
                    "invoices.py": "import tax\\n" + INVOICE_CLASS.replace("tax_for(self)", "tax.tax_for(self)"),
                    "tax.py": BROKEN_TAX.replace("from invoices import Invoice", "import invoices").replace(
                        "invoice: Invoice", "invoice: invoices.Invoice"
                    ),
                },
                "3. local import": {
                    "invoices.py": INVOICE_CLASS.replace(
                        "return self.amount", "from tax import tax_for\\n\\n        return self.amount"
                    ),
                    "tax.py": BROKEN_TAX,
                },
                "4. TYPE_CHECKING": {
                    "invoices.py": BROKEN_INVOICES["invoices.py"],
                    "tax.py": BROKEN_TAX.replace(
                        "from invoices import Invoice",
                        "from typing import TYPE_CHECKING\\n\\n"
                        "if TYPE_CHECKING:\\n    from invoices import Invoice",
                    ),
                },
            }
            for label, files in invoice_fixes.items():
                print(f"{label:<18} {check_invoice_fix(files)}")
            '''
        ),
        md(
            """
            > **Note:** fix 4 works because `tax` uses `Invoice` only in an annotation, and since
            > 3.14 annotations are evaluated lazily (PEP 649), so the unquoted `Invoice` is never
            > looked up at import time. `typing.TYPE_CHECKING` is `False` at run time and `True`
            > for mypy / pyright.
            """
        ),
    ]


def _importlib_cells() -> list[NotebookNode]:
    """3.3.10 importlib."""
    return [
        md(
            """
            ### 3.3.10 `importlib`

            | API | Use |
            | --- | --- |
            | `importlib.import_module(name, package=None)` | Import by a string name (config-driven backends, plugins); relative names need `package` |
            | `importlib.resources.files(package)` | Read data files shipped **inside** a package, from a folder, a zip or a wheel |
            | `importlib.metadata` | Installed distributions: `version`, `metadata`, `requires`, `files`, `entry_points` |
            | `pkgutil.iter_modules(path)` | List the modules in a package without importing them |
            | Entry points | Plugins advertised by **installed distributions** in their metadata (`[project.entry-points."group"]`) |

            #### `importlib.import_module`

            `json` and its submodules are already loaded in this kernel, so these calls only
            look them up in `sys.modules`.
            """
        ),
        code(
            """
            backend_name = "json.decoder"  # e.g. read from a settings file
            decoder_module = importlib.import_module(backend_name)
            encoder_module = importlib.import_module(".encoder", package="json")
            print(f"{decoder_module.__name__=}  {encoder_module.__name__=}")
            print(raised_message(lambda: importlib.import_module(".encoder")))
            """
        ),
        md(
            """
            #### `importlib.resources`

            `files(package)` returns a `Traversable` (like a read-only `pathlib.Path`) for the
            package's folder, wherever it really lives. `as_file()` gives a real file path when
            a library insists on one (extracting from a zip if needed). Reading the
            already-imported `json` package is safe in the kernel; the `brand` package with a
            data file runs in a child.
            """
        ),
        code(
            '''
            json_files = sorted(item.name for item in importlib.resources.files("json").iterdir())
            print(f"json package files (read in the kernel): {json_files[:4]}")
            BRAND_FILES = {"brand/__init__.py": "", "brand/assets/tagline.txt": "Fresh groceries, fast.\\n"}
            RESOURCES_SCRIPT = """
            import importlib.resources

            assets = importlib.resources.files("brand") / "assets"
            print("type:", type(assets).__name__, "| contents:", [item.name for item in assets.iterdir()])
            print("tagline:", (assets / "tagline.txt").read_text().strip())
            with importlib.resources.as_file(assets / "tagline.txt") as real_path:
                print("as_file gives a real path:", real_path.exists())
            """
            with scratch_project("unit33_resources", BRAND_FILES) as root:
                print(run_script(root, RESOURCES_SCRIPT))
            '''
        ),
        md(
            """
            #### `importlib.metadata`

            Information about **installed distributions** (what `uv add` installed), read from
            their `.dist-info` folders, without importing them.
            """
        ),
        code(
            """
            nbformat_meta = importlib.metadata.metadata("nbformat")
            print(f"{importlib.metadata.version('nbformat')=}")
            print(f"Summary: {nbformat_meta['Summary']}")
            print(f"first requirements: {sorted(importlib.metadata.requires('nbformat'))[:3]}")
            print(f"files installed: {len(importlib.metadata.files('nbformat'))}")
            providers = importlib.metadata.packages_distributions().get("nbformat")
            print(f"distributions providing the nbformat package: {providers}")
            print(raised_error_name(lambda: importlib.metadata.version("not-a-real-distribution")))
            """
        ),
        md("#### `pkgutil.iter_modules`"),
        code(
            """
            json_parts = sorted((info.name, info.ispkg) for info in pkgutil.iter_modules(json.__path__))
            print(f"{json_parts=}")
            print(f"{[info.name for info in pkgutil.iter_modules(importlib.__path__)][:6]=}")
            """
        ),
        md(
            """
            #### Entry-point plugins

            A distribution can advertise objects under a named **group** in its metadata;
            the host application discovers and loads them without knowing their modules in
            advance. `console_scripts` is the group behind installed commands; nbconvert finds
            its exporters through the `nbconvert.exporters` group. Listing entry points only
            reads metadata; **loading** one imports its module, so that part runs in a child.
            """
        ),
        code(
            '''
            console_scripts = importlib.metadata.entry_points(group="console_scripts")
            jupyter_commands = sorted(ep.name for ep in console_scripts if ep.name.startswith("jupyter"))
            print(f"jupyter commands: {jupyter_commands[:5]}")
            exporters = importlib.metadata.entry_points(group="nbconvert.exporters")
            if exporters:
                print(f"nbconvert exporters advertised: {sorted(ep.name for ep in exporters)[:6]}")
                LOAD_SCRIPT = """
                from importlib.metadata import entry_points

                markdown = next(ep for ep in entry_points(group="nbconvert.exporters") if ep.name == "markdown")
                print(markdown.name, "->", markdown.value, "| loaded:", markdown.load().__name__)
                """
                print(run_python("-c", textwrap.dedent(LOAD_SCRIPT)))
            else:
                print("Skipped: no nbconvert.exporters entry points installed")
            '''
        ),
    ]


def _hook_cells() -> list[NotebookNode]:
    """3.3.11 Import hooks."""
    return [
        md(
            """
            ### 3.3.11 Import hooks

            Two extension points:

            - **`sys.meta_path`**: finders asked for **every** import (3.3.2). A custom one
              can serve modules from anywhere: a database, the network, an encrypted bundle.
            - **`sys.path_hooks`**: factories that turn a `sys.path` entry into a finder for
              that entry (this is how zip files on `sys.path` work); results are cached in
              `sys.path_importer_cache`.

            A finder implements `find_spec(fullname, path, target=None)` and returns a
            `ModuleSpec` or `None`; the spec names a loader that implements
            `create_module(spec)` (return `None` for a default module) and
            `exec_module(module)`. The demo's `json_importer.py` serves `<name>.json` files
            from a folder as modules whose attributes are the JSON keys; a child script
            installs it and imports `store_settings` from `settings/store_settings.json`.
            """
        ),
        code(
            '''
            HOOK_FILES = {
                "json_importer.py": """
                    import importlib.abc
                    import importlib.util
                    import json
                    from pathlib import Path


                    class JsonModuleImporter(importlib.abc.MetaPathFinder, importlib.abc.Loader):
                        # Import `name` from name.json in a folder: the JSON keys become attributes.

                        def __init__(self, folder):
                            self.folder = Path(folder)

                        def find_spec(self, fullname, path, target=None):
                            candidate = self.folder / f"{fullname}.json"
                            if "." in fullname or not candidate.exists():
                                return None  # not ours: the next finder tries
                            return importlib.util.spec_from_loader(fullname, self, origin=str(candidate))

                        def create_module(self, spec):
                            return None  # use the default module object

                        def exec_module(self, module):
                            module.__dict__.update(json.loads(Path(module.__spec__.origin).read_text()))
                    """,
                "settings/store_settings.json": '{"currency": "INR", "free_shipping_above": 499}',
            }
            HOOK_SCRIPT = """
            import sys

            from json_importer import JsonModuleImporter

            sys.meta_path.insert(0, JsonModuleImporter("settings"))
            import store_settings

            print("currency:", store_settings.currency, "| free above:", store_settings.free_shipping_above)
            print("loader:", type(store_settings.__loader__).__name__)
            print("origin:", store_settings.__spec__.origin)
            """
            with scratch_project("unit33_import_hook", HOOK_FILES) as root:
                print(run_script(root, HOOK_SCRIPT))
            hook_names = [getattr(hook, "__name__", type(hook).__name__) for hook in sys.path_hooks]
            print(f"this kernel's sys.path_hooks: {hook_names}")
            '''
        ),
    ]


def _lazy_cells() -> list[NotebookNode]:
    """3.3.12 Lazy imports (3.15)."""
    return [
        md(
            """
            ### 3.3.12 Lazy imports (3.15)

            Command-line tools often import a dozen heavy modules at start-up and use one.
            *New in 3.15* (PEP 810): `lazy import x` and `lazy from x import y` bind a
            **proxy** instead of importing. The real import happens the first time the name is
            used; the module code then runs exactly as before.

            | Rule | Detail |
            | --- | --- |
            | Where allowed | Module level only; not inside functions, classes, `try`/`except` or `with` blocks |
            | Not allowed | `lazy from x import *` |
            | Errors | A missing module raises `ModuleNotFoundError` at **first use**, not at the import line |
            | Global switch | `sys.set_lazy_imports("all")`, `python -X lazy_imports=all`, `PYTHON_LAZY_IMPORTS=all` make ordinary top-level imports lazy too; a filter (`sys.set_lazy_imports_filter`) can opt modules out |
            | Inspecting | `sys.lazy_modules` lists modules imported lazily but not yet loaded |

            Lazy syntax is 3.15-only, so it never appears in a notebook cell's own code (an
            older kernel could not even parse the cell): it lives in **separate files** run by a
            child interpreter, or in strings passed to `compile()`, all behind a
            `sys.version_info >= (3, 15)` check. First, the proxy and its first use, on a module
            that prints when it really runs:
            """
        ),
        code(
            '''
            LAZY_FILES = {
                "heavy_report.py": """
                    print("   heavy_report: module code runs now")

                    def summary():
                        return "ok"
                    """,
                "lazy_demo.py": """
                    import sys

                    lazy import heavy_report

                    kind = type(globals()["heavy_report"]).__name__
                    print("1. after `lazy import`:", "heavy_report" in sys.modules, kind)
                    print("2. first use returns:", heavy_report.summary())
                    kind = type(globals()["heavy_report"]).__name__
                    print("3. after first use:", "heavy_report" in sys.modules, kind)
                    """,
                "missing_demo.py": """
                    lazy import no_such_reporting_lib

                    print("the lazy import line passed")
                    try:
                        no_such_reporting_lib.render()
                    except ModuleNotFoundError as error:
                        print("first use ->", type(error).__name__ + ":", error)
                    """,
            }
            if sys.version_info >= (3, 15):
                with scratch_project("unit33_lazy", LAZY_FILES) as root:
                    print(run_python("lazy_demo.py", cwd=root))
                    print(run_python("missing_demo.py", cwd=root))
            else:
                print("Skipped: lazy imports need Python 3.15+")
            '''
        ),
        md(
            """
            **Restrictions.** Where the keyword is refused, checked with `compile()` on strings
            (nothing is imported), plus this kernel's global mode.
            """
        ),
        code(
            """
            if sys.version_info >= (3, 15):
                print(f"in a function: {compile_error('def load():\\n    lazy import json\\n')}")
                in_try = "try:\\n    lazy import json\\nexcept ImportError:\\n    pass\\n"
                print(f"in try:        {compile_error(in_try)}")
                print(f"star import:   {compile_error('lazy from json import *\\n')}")
                print(f"module level:  {compile_error('lazy import json\\n')}")
                pending_count = len(sys.lazy_modules)
                print(
                    f"{sys.get_lazy_imports()=}  ({pending_count} stdlib modules still pending in this kernel)"
                )
            else:
                print("Skipped: lazy imports need Python 3.15+")
            """
        ),
        md(
            """
            **The global switch.** With `-X lazy_imports=all`, a plain `import json` at the top
            of a program is lazy too.
            """
        ),
        code(
            """
            switch_probe = (
                "import sys, json\\n"
                "print('json loaded before use:', 'json' in sys.modules)\\n"
                "json.dumps(1)\\n"
                "print('after use:', 'json' in sys.modules)"
            )
            if sys.version_info >= (3, 15):
                print("default:              ", run_python("-c", switch_probe).replace("\\n", " | "))
                print(
                    "-X lazy_imports=all:  ",
                    run_python("-X", "lazy_imports=all", "-c", switch_probe).replace("\\n", " | "),
                )
            else:
                print("Skipped: lazy imports need Python 3.15+")
            """
        ),
        md(
            """
            **`importlib.util.LazyLoader`** (3.5+) gives the same effect for one module on any
            version: the module object is created at once, and its code runs on the first
            attribute access. It registers the module in `sys.modules`, so it runs in a child.
            """
        ),
        code(
            '''
            LAZY_LOADER_SCRIPT = """
            import importlib.util
            import sys


            def lazy_load(module_name):
                # Import module_name with LazyLoader: its code runs on first attribute access.
                spec = importlib.util.find_spec(module_name)
                spec.loader = importlib.util.LazyLoader(spec.loader)
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
                return module


            report_module = lazy_load("heavy_report")
            print("module object exists:", type(report_module).__name__)
            print("first attribute access ->", report_module.summary())
            """
            with scratch_project(
                "unit33_lazy_loader", {"heavy_report.py": LAZY_FILES["heavy_report.py"]}
            ) as root:
                print(run_script(root, LAZY_LOADER_SCRIPT))
            '''
        ),
        md(
            """
            **Measuring with `python -X importtime`.** The interpreter prints one line per
            module imported, to stderr: self time and cumulative time in microseconds,
            indented by nesting depth. The cell compares `import asyncio` with
            `lazy import asyncio`; the counts are lines of the report (times vary by machine).
            """
        ),
        code(
            """
            eager_report = run_python("-X", "importtime", "-c", "import asyncio")
            print("\\n".join(eager_report.splitlines()[:1] + eager_report.splitlines()[-3:]))
            eager_lines = [line for line in eager_report.splitlines() if line.startswith("import time:")]
            print(f"eager: {len(eager_lines) - 1} modules reported")
            if sys.version_info >= (3, 15):
                lazy_report = run_python("-X", "importtime", "-c", "lazy import asyncio")
                lazy_lines = [line for line in lazy_report.splitlines() if line.startswith("import time:")]
                asyncio_listed = "asyncio" in lazy_report
                print(f"lazy, unused: {len(lazy_lines) - 1} modules reported; asyncio listed: {asyncio_listed}")
            """
        ),
    ]


def _js_bridge_cells() -> list[NotebookNode]:
    """3.3.13 JS bridge, the predict question and the kernel-isolation check."""
    return [
        md(
            """
            ### 3.3.13 JS bridge

            | Topic | Node.js / browsers | Python |
            | --- | --- | --- |
            | Module cache | `require.cache[resolvedPath]`; ESM has an internal module map | `sys.modules[name]`, keyed by **name**, not path |
            | Forcing a re-run | `delete require.cache[path]` | `del sys.modules[name]` then import, or `importlib.reload` |
            | Named imports | ESM bindings are **live**: the importer sees later reassignments | `from m import x` copies the binding (3.3.3) |
            | Resolution | `node_modules` searched in the current folder, then each parent; per-package versions | `sys.path` searched in order; one installed version per environment |
            | Package entry | `package.json` `"main"` / `"exports"` | `__init__.py` (and `__all__`), `__main__.py` for `-m` |
            | Run as program | `require.main === module` / `import.meta.main` | `__name__ == "__main__"` |
            | Cycles | CommonJS returns the partial `exports`; ESM can hit TDZ errors | Partially initialized module → `ImportError` / `AttributeError` |
            | Dynamic import | `await import("./m.js")` | `importlib.import_module("m")` (synchronous) |
            | Lazy loading | dynamic `import()` at the point of use | `lazy import` (3.15), `LazyLoader`, imports inside functions |

            Like deleting from `require.cache`, removing a module from `sys.modules` makes the
            next import run its code again and create a **new** module object; old
            references keep the old one.
            """
        ),
        code(
            '''
            RERUN_SCRIPT = """
            import sys

            import counter_module

            first_object = counter_module
            del sys.modules["counter_module"]
            import counter_module

            print("first_object is counter_module:", first_object is counter_module, "(a fresh module object)")
            """
            with scratch_project(
                "unit33_rerun", {"counter_module.py": "print('counter_module runs')\\n"}
            ) as root:
                print(run_script(root, RERUN_SCRIPT))
            '''
        ),
        *predict_cells(
            """
            # settings.py contains:  DEBUG = False
            import settings
            from settings import DEBUG

            settings.DEBUG = True
            print(DEBUG, settings.DEBUG)
            """,
            """
            ```text
            False True
            ```

            `from settings import DEBUG` bound a new name to the object `False`. Assigning
            `settings.DEBUG = True` rebinds the name **inside the module**; your `DEBUG` still
            points at `False`. In JavaScript, an ESM named import would see `true` (live
            binding).
            """,
            '''
            PREDICT_SCRIPT = """
            import settings
            from settings import DEBUG

            settings.DEBUG = True
            print(DEBUG, settings.DEBUG)
            """
            with scratch_project("unit33_predict", {"settings.py": "DEBUG = False\\n"}) as root:
                print(run_script(root, PREDICT_SCRIPT))
            ''',
        ),
        md(
            """
            #### Proof that the demos stayed out of this kernel

            Every module above was imported by a child interpreter. The kernel's `sys.path` is
            the same list as when the setup cell ran, none of the demo modules are in its
            `sys.modules`, and every scratch folder has been deleted.
            """
        ),
        code(
            """
            DEMO_MODULE_NAMES = {
                "checkout_rules", "checkout_helpers", "discounts", "fake_payments", "config", "shop",
                "settings", "app_state", "billing", "shipping", "rates", "tools", "inventory", "plugins",
                "greeter", "invoices", "tax", "brand", "json_importer", "store_settings", "heavy_report",
                "lazy_demo", "missing_demo", "counter_module",
            }  # fmt: skip
            print(f"kernel sys.path unchanged since the setup cell: {sys.path == KERNEL_PATH_AT_START}")
            print(f"demo modules in the kernel's sys.modules: {sorted(DEMO_MODULE_NAMES & set(sys.modules))}")
            leftover_folders = sorted(path.name for path in scratch_dir.glob("unit33_*"))
            print(f"demo folders left in notebooks/_scratch: {leftover_folders}")
            """
        ),
    ]


def _lab_package_cells() -> list[NotebookNode]:
    """Lab 3.3 exercises 1–3."""
    return [
        md(
            """
            ### Lab 3.3

            Six exercises. For each, complete the stub, then run the check cell. Until then the
            checks print FAIL; that is expected.

            - Exercises 1, 2 and 6 hand over files or source code, so their checks run your
              packages in **child processes** from `notebooks/_scratch/`, like the demos.
            - Exercises 3–5 test functions you write **in this kernel** (`load_plugins`,
              `DictImporter`, the `importlib.resources` readers), so those checks must import
              into the kernel. `temporary_modules` writes the packages under
              `notebooks/_scratch/` and, on exit, removes the folder from `sys.path` and forgets
              every module imported from it, so you can re-run checks freely.

            #### Exercise 1 — build a `shop/` package and test its imports

            Return a dict mapping relative paths to file contents for this package:

            | File | Contents |
            | --- | --- |
            | `shop/models.py` | a frozen dataclass `Product(name: str, price: Decimal)` |
            | `shop/cart.py` | `Cart` with `add(product, quantity=1)` and `total() -> Decimal`; imports `Product` with a **relative** import |
            | `shop/payments/__init__.py` | a subpackage with `charge(amount: Decimal) -> str` returning `f"charged INR {amount:.2f}"` |
            | `shop/__init__.py` | re-exports `Cart` and `Product`, sets `__all__ = ["Cart", "Product"]` and `__version__ = "1.0"` |
            | `shop/__main__.py` | prints `f"shop {__version__}"`, so `python -m shop` prints `shop 1.0` |
            """
        ),
        code(
            '''
            def shop_package_files() -> dict[str, str]:
                """Relative path -> source for the shop package."""
                raise NotImplementedError("Lab 3.3: write the shop package")
            '''
        ),
        md(
            "Run the checks. Each one writes your package to `notebooks/_scratch/` and inspects it in a child process."
        ),
        code(
            """
            SHOP_SCRIPT = \"\"\"
            import json
            from decimal import Decimal

            import shop
            import shop.cart
            import shop.payments

            namespace = {}
            exec("from shop import *", namespace)
            cart = shop.Cart()
            cart.add(shop.Product("tea", Decimal("120.50")), quantity=2)
            cart.add(shop.Product("rice", Decimal("80")))
            report = {
                "all": sorted(shop.__all__),
                "version": shop.__version__,
                "star": sorted(name for name in namespace if not name.startswith("__")),
                "same_class": shop.Cart is shop.cart.Cart,
                "total": str(cart.total()),
                "charge": shop.payments.charge(Decimal("321")),
            }
            print(json.dumps(report))
            \"\"\"


            def shop_report() -> dict[str, object]:
                \"\"\"Write the learner's package and inspect it in a child process.\"\"\"
                with scratch_project("unit33_lab_shop", shop_package_files()) as root:
                    return child_json(run_script(root, SHOP_SCRIPT))


            def shop_run_as_module() -> str:
                \"\"\"Output of `python -m shop` in the package folder.\"\"\"
                with scratch_project("unit33_lab_shop", shop_package_files()) as root:
                    return run_python("-m", "shop", cwd=root)


            run_checks(
                [
                    ("__all__", lambda: shop_report()["all"], ["Cart", "Product"]),
                    ("__version__", lambda: shop_report()["version"], "1.0"),
                    ("star import", lambda: shop_report()["star"], ["Cart", "Product"]),
                    ("re-export is the same class", lambda: shop_report()["same_class"], True),
                    ("cart total", lambda: shop_report()["total"], "321.00"),
                    ("subpackage", lambda: shop_report()["charge"], "charged INR 321.00"),
                    (
                        "relative import in cart.py",
                        lambda: "from .models import" in shop_package_files()["shop/cart.py"],
                        True,
                    ),
                    ("python -m shop", shop_run_as_module, "shop 1.0"),
                ]
            )
            """
        ),
        md(
            """
            #### Exercise 2 — fix a circular import three ways

            `orders` and `customers` need each other **at run time**: `Customer.place_order`
            creates an `Order`, and `Order.__init__` checks `isinstance(customer, Customer)`.
            The given version fails on import (the demo below shows the error). Return three
            fixed file sets (each a dict like `BROKEN_ORDERS`), keeping the behaviour:

            1. `fix_with_module_imports()`: both files use `import orders` / `import customers`
               at the top and look up classes as attributes at call time.
            2. `fix_with_local_import()`: one top-level import stays; the other moves inside the
               function that needs it.
            3. `fix_with_third_module()`: move both classes into a new module (for example
               `models.py`); `orders.py` and `customers.py` re-export them.

            The scenario: `customers.Customer("Asha").place_order(7).describe()` returns
            `"order 7 for Asha"`, and `orders.Order(1, "nobody")` raises `TypeError`.
            """
        ),
        code(
            '''
            BROKEN_ORDERS = {
                "orders.py": """
                    from customers import Customer

                    class Order:
                        def __init__(self, order_id, customer):
                            if not isinstance(customer, Customer):
                                raise TypeError("customer must be a Customer")
                            self.order_id = order_id
                            self.customer = customer

                        def describe(self):
                            return f"order {self.order_id} for {self.customer.name}"
                    """,
                "customers.py": """
                    from orders import Order

                    class Customer:
                        def __init__(self, name):
                            self.name = name
                            self.orders = []

                        def place_order(self, order_id):
                            order = Order(order_id, self)
                            self.orders.append(order)
                            return order
                    """,
            }
            FROM_SRC = "import sys\\nsys.path.insert(0, 'src')\\n"
            with scratch_project("unit33_lab_orders", in_src(BROKEN_ORDERS)) as root:
                print(f"given version: {run_script(root, FROM_SRC + 'import customers').splitlines()[-1]}")
            '''
        ),
        md("The stubs:"),
        code(
            '''
            def fix_with_module_imports() -> dict[str, str]:
                """Fix 1: import modules, not names."""
                raise NotImplementedError("Lab 3.3: fix with module imports")


            def fix_with_local_import() -> dict[str, str]:
                """Fix 2: move one import into the function that needs it."""
                raise NotImplementedError("Lab 3.3: fix with a local import")


            def fix_with_third_module() -> dict[str, str]:
                """Fix 3: move both classes into a third module."""
                raise NotImplementedError("Lab 3.3: fix with a third module")
            '''
        ),
        md("Run the checks. Each fix runs in child processes, imported in both orders."),
        code(
            '''
            ORDERS_SCRIPT = """
            import importlib
            import json
            import sys

            sys.path.insert(0, "src")
            importlib.import_module(sys.argv[1])  # this module is imported first
            import customers
            import orders

            outcome = [customers.Customer("Asha").place_order(7).describe()]
            try:
                orders.Order(1, "nobody")
                outcome.append("no error")
            except Exception as error:
                outcome.append(type(error).__name__)
            print(json.dumps(outcome))
            """


            def orders_scenario(files: dict[str, str]) -> list[str]:
                """Run the scenario in child processes: customers imported first, then orders first."""
                outcomes: list[str] = []
                for first_import in ("customers", "orders"):
                    with scratch_project("unit33_lab_orders", in_src(files)) as root:
                        outcomes.extend(child_json(run_script(root, ORDERS_SCRIPT, first_import)))
                return outcomes


            def top_level_imports(source: str) -> list[str]:
                """Module names imported with plain `import` at the top level of source."""
                return [
                    alias.name
                    for node in ast.parse(textwrap.dedent(source)).body
                    if isinstance(node, ast.Import)
                    for alias in node.names
                ]


            def has_function_level_import(files: dict[str, str]) -> bool:
                """Is there an import statement inside some function?"""
                for source in files.values():
                    for node in ast.walk(ast.parse(textwrap.dedent(source))):
                        if isinstance(node, ast.FunctionDef) and any(
                            isinstance(inner, ast.Import | ast.ImportFrom) for inner in ast.walk(node)
                        ):
                            return True
                return False


            EXPECTED_SCENARIO = ["order 7 for Asha", "TypeError", "order 7 for Asha", "TypeError"]
            run_checks(
                [
                    (
                        "module imports: scenario",
                        lambda: orders_scenario(fix_with_module_imports()),
                        EXPECTED_SCENARIO,
                    ),
                    (
                        "module imports: uses `import`",
                        lambda: (
                            "customers" in top_level_imports(fix_with_module_imports()["orders.py"]),
                            "orders" in top_level_imports(fix_with_module_imports()["customers.py"]),
                        ),
                        (True, True),
                    ),
                    (
                        "local import: scenario",
                        lambda: orders_scenario(fix_with_local_import()),
                        EXPECTED_SCENARIO,
                    ),
                    (
                        "local import: inside a function",
                        lambda: has_function_level_import(fix_with_local_import()),
                        True,
                    ),
                    (
                        "third module: scenario",
                        lambda: orders_scenario(fix_with_third_module()),
                        EXPECTED_SCENARIO,
                    ),
                    ("third module: three files", lambda: len(fix_with_third_module()) >= 3, True),
                ]
            )
            '''
        ),
        md(
            """
            #### Exercise 3 — a plugin loader with `pkgutil`

            `load_plugins(package_name)` imports the package, then every **module** (not
            subpackage) inside it found with `pkgutil.iter_modules(package.__path__)`:

            - skip modules whose name starts with `_`,
            - a plugin is a module with a string `PLUGIN_NAME` and a callable `run`; skip
              modules missing either,
            - two plugins with the same `PLUGIN_NAME` raise
              `ValueError(f"duplicate plugin name: {name}")`,
            - return `{PLUGIN_NAME: run}` with keys sorted.
            """
        ),
        code(
            '''
            def load_plugins(package_name: str) -> dict[str, Callable[..., object]]:
                """Discover plugin modules in a package."""
                raise NotImplementedError("Lab 3.3: implement load_plugins")
            '''
        ),
        md("Run the checks."),
        code(
            '''
            EXPORTER_FILES = {
                "exporters/__init__.py": "",
                "exporters/csv_exporter.py": """
                    PLUGIN_NAME = "csv"

                    def run(rows):
                        return "\\\\n".join(",".join(str(value) for value in row.values()) for row in rows)
                    """,
                "exporters/json_exporter.py": """
                    import json

                    PLUGIN_NAME = "json"

                    def run(rows):
                        return json.dumps(rows)
                    """,
                "exporters/_shared.py": "PLUGIN_NAME = 'shared'\\n\\ndef run(rows):\\n    return ''\\n",
                "exporters/draft_exporter.py": "PLUGIN_NAME = 'draft'  # no run() yet\\n",
                "exporters/legacy/__init__.py": "PLUGIN_NAME = 'legacy'\\n\\ndef run(rows):\\n    return ''\\n",
            }
            SAMPLE_ROWS = [{"sku": "TEA-01", "qty": 2}, {"sku": "RICE-5", "qty": 1}]


            def plugins_from(files: dict[str, str]) -> Callable[[], object]:
                """A thunk that loads the exporters plugins from files."""

                def load() -> object:
                    with temporary_modules(files):
                        plugins = load_plugins("exporters")
                        return list(plugins), plugins["csv"](SAMPLE_ROWS), plugins["json"](SAMPLE_ROWS[:1])

                return load


            duplicate_files = {
                **EXPORTER_FILES,
                "exporters/csv_again.py": "PLUGIN_NAME = 'csv'\\n\\ndef run(rows):\\n    return ''\\n",
            }
            run_checks(
                [
                    (
                        "plugins, sorted, run",
                        plugins_from(EXPORTER_FILES),
                        (["csv", "json"], "TEA-01,2\\nRICE-5,1", '[{"sku": "TEA-01", "qty": 2}]'),
                    ),
                    (
                        "duplicate name",
                        lambda: raised_message(plugins_from(duplicate_files)),
                        "ValueError: duplicate plugin name: csv",
                    ),
                ]
            )
            '''
        ),
    ]


def _lab_import_system_cells() -> list[NotebookNode]:
    """Lab 3.3 exercises 4–6."""
    return [
        md(
            """
            #### Exercise 4 — an in-memory `DictImporter`

            `DictImporter(sources)` serves modules from a dict mapping **dotted module names**
            to source code. It is both the finder and the loader:

            - `find_spec(fullname, path=None, target=None)`: `None` for names not in
              `sources`; otherwise `importlib.util.spec_from_loader(fullname, self,
              origin="<dict>", is_package=...)`, where a name is a package if some other key
              starts with `fullname + "."`.
            - `create_module(spec)` returns `None`; `exec_module(module)` compiles the source
              (filename `f"<dict:{name}>"`) and executes it in `module.__dict__`.

            Relative imports inside the served packages must work.
            """
        ),
        code(
            '''
            class DictImporter(importlib.abc.MetaPathFinder, importlib.abc.Loader):
                """Serve modules from a dict of dotted name -> source code."""

                def __init__(self, sources: dict[str, str]) -> None:
                    raise NotImplementedError("Lab 3.3: implement DictImporter")
            '''
        ),
        md(
            "Run the checks. `installed(importer)` adds it to `sys.meta_path` and cleans up afterwards."
        ),
        code(
            '''
            IN_MEMORY_SOURCES = {
                "greetings": "def hello(name):\\n    return f'Namaste, {name}'\\n",
                "toolbox": "from .strings import shout\\n",
                "toolbox.strings": "def shout(text):\\n    return text.upper() + '!'\\n",
                "run_counter": "import builtins\\nbuiltins.__dict__.setdefault('_run_counter_hits', []).append(1)",  # noqa: E501
            }


            @contextmanager
            def installed(importer: object) -> Iterator[object]:
                """Put importer first on sys.meta_path; remove it and its modules afterwards."""
                sys.meta_path.insert(0, importer)
                try:
                    yield importer
                finally:
                    sys.meta_path.remove(importer)
                    for name in [
                        name
                        for name, module in sys.modules.items()
                        if getattr(module, "__loader__", None) is importer
                    ]:
                        del sys.modules[name]


            def with_importer(action: Callable[[object], object]) -> Callable[[], object]:
                def run() -> object:
                    with installed(DictImporter(IN_MEMORY_SOURCES)) as importer:
                        return action(importer)

                return run


            def imports_once(importer: object) -> int:
                import builtins

                builtins.__dict__.pop("_run_counter_hits", None)
                importlib.import_module("run_counter")
                importlib.import_module("run_counter")
                return len(builtins.__dict__.pop("_run_counter_hits", []))


            run_checks(
                [
                    (
                        "plain module",
                        with_importer(lambda imp: importlib.import_module("greetings").hello("Asha")),
                        "Namaste, Asha",
                    ),
                    (
                        "spec origin and loader",
                        with_importer(
                            lambda imp: (
                                importlib.import_module("greetings").__spec__.origin,
                                importlib.import_module("greetings").__loader__ is imp,
                            )
                        ),
                        ("<dict>", True),
                    ),
                    (
                        "package + relative import",
                        with_importer(lambda imp: importlib.import_module("toolbox").shout("hi")),
                        "HI!",
                    ),
                    (
                        "package has __path__",
                        with_importer(lambda imp: hasattr(importlib.import_module("toolbox"), "__path__")),
                        True,
                    ),
                    ("unknown name -> None", with_importer(lambda imp: imp.find_spec("json", None)), None),
                    (
                        "missing module",
                        with_importer(
                            lambda imp: raised_error_name(lambda: importlib.import_module("not_in_the_dict"))
                        ),
                        "ModuleNotFoundError",
                    ),
                    ("runs once", with_importer(imports_once), 1),
                ]
            )
            '''
        ),
        md(
            """
            #### Exercise 5 — read packaged data with `importlib.resources`

            The `catalog` package ships `data/products.csv` (columns `name,price`) and
            `data/tax_rates.json`. Write three functions that take the **package name** and use
            `importlib.resources.files(...)` only (no `__file__` arithmetic), so they also work
            when the package is imported from a zip file:

            - `load_tax_rates(package)` → the JSON object as a `dict[str, float]`,
            - `product_names(package)` → the `name` column in file order,
            - `data_file_names(package)` → sorted file names in `data/`.

            The cell below shows why `__file__` arithmetic breaks for a zipped package.
            """
        ),
        code(
            """
            CATALOG_FILES = {
                "catalog/__init__.py": "",
                "catalog/data/products.csv": "name,price\\nGreen tea,120.50\\nBasmati rice,80\\nTurmeric,45\\n",
                "catalog/data/tax_rates.json": '{"food": 0.05, "electronics": 0.18}',
            }
            with temporary_modules(CATALOG_FILES, zipped=True):
                catalog = importlib.import_module("catalog")
                naive_path = Path(catalog.__file__).parent / "data" / "tax_rates.json"
                print(f"zipped: catalog.__file__ ends with {'/'.join(Path(catalog.__file__).parts[-3:])!r}")
                print(f"naive open(): {raised_error_name(naive_path.read_text)}")
            """
        ),
        md("The stubs:"),
        code(
            '''
            def load_tax_rates(package: str) -> dict[str, float]:
                """data/tax_rates.json from the package."""
                raise NotImplementedError("Lab 3.3: implement load_tax_rates")


            def product_names(package: str) -> list[str]:
                """The name column of data/products.csv, in file order."""
                raise NotImplementedError("Lab 3.3: implement product_names")


            def data_file_names(package: str) -> list[str]:
                """Sorted file names in data/."""
                raise NotImplementedError("Lab 3.3: implement data_file_names")
            '''
        ),
        md("Run the checks, from a folder and from a zip."),
        code(
            """
            def read_catalog(zipped: bool) -> Callable[[], object]:
                def read() -> object:
                    with temporary_modules(CATALOG_FILES, zipped=zipped):
                        return load_tax_rates("catalog"), product_names("catalog"), data_file_names("catalog")

                return read


            EXPECTED_CATALOG = (
                {"food": 0.05, "electronics": 0.18},
                ["Green tea", "Basmati rice", "Turmeric"],
                ["products.csv", "tax_rates.json"],
            )
            run_checks(
                [
                    ("from a folder", read_catalog(zipped=False), EXPECTED_CATALOG),
                    ("from a zip", read_catalog(zipped=True), EXPECTED_CATALOG),
                ]
            )
            """
        ),
        md(
            """
            #### Exercise 6 — measure and reduce CLI startup with lazy imports

            `REPORT_CLI` (given) imports six modules at the top but needs only `decimal`, and
            only for its `total` command; `--version` needs none of them.

            1. `parse_importtime(stderr_text)` → `{module: cumulative_microseconds}` from
               `python -X importtime` output: keep only lines starting with `"import time:"`,
               skip the header, strip the indentation from the module name.
            2. `make_lazy(source)` → the source with every **module-level** `import` /
               `from … import` statement turned into `lazy import` / `lazy from … import`.
               Leave alone imports inside functions, `if` blocks or `try`, star imports and
               `from __future__` imports. (Hint: `ast.parse(source).body` holds the
               module-level statements and their line numbers.)

            The checks run both versions with `-X importtime` and compare what they load.
            """
        ),
        code(
            '''
            REPORT_CLI = """
            import asyncio
            import email.parser
            import http.client
            import json
            import xml.etree.ElementTree as ElementTree
            from decimal import Decimal
            import sys


            def main(argv):
                if argv[:1] == ["--version"]:
                    print("report 2.0")
                elif argv[:1] == ["total"]:
                    print(sum(Decimal(value) for value in argv[1:]))
                else:
                    print("usage: report [--version | total VALUE...]")


            if __name__ == "__main__":
                main(sys.argv[1:])
            """


            def parse_importtime(stderr_text: str) -> dict[str, int]:
                """{module: cumulative microseconds} from `python -X importtime` output."""
                raise NotImplementedError("Lab 3.3: implement parse_importtime")


            def make_lazy(source: str) -> str:
                """Turn module-level imports into lazy imports."""
                raise NotImplementedError("Lab 3.3: implement make_lazy")
            '''
        ),
        md("Run the checks. They need Python 3.15 for the `lazy` keyword."),
        code(
            '''
            SAMPLE_IMPORTTIME = """
            import time: self [us] | cumulative | imported package
            import time:       120 |        120 |   _json
            import time:       850 |       1300 | json
            import time:        90 |         90 |     _decimal
            import time:       400 |        490 |   decimal
            garbage line
            """.strip()


            def run_cli(source: str, *arguments: str) -> tuple[str, set[str]]:
                """Run a CLI source with -X importtime; return (stdout's last line, imported modules)."""
                with tempfile.TemporaryDirectory() as folder:
                    script = Path(folder) / "report.py"
                    script.write_text(source)
                    completed = subprocess.run(
                        [sys.executable, "-X", "importtime", str(script), *arguments],
                        capture_output=True, text=True, env=CHILD_ENV, timeout=60,
                    )  # fmt: skip
                return completed.stdout.strip(), set(parse_importtime(completed.stderr))


            def startup_comparison() -> tuple[bool, bool, bool, bool]:
                eager_output, eager_modules = run_cli(REPORT_CLI, "--version")
                lazy_output, lazy_modules = run_cli(make_lazy(REPORT_CLI), "--version")
                print(f"    modules loaded for --version: eager {len(eager_modules)}, lazy {len(lazy_modules)}")
                return (
                    eager_output == lazy_output == "report 2.0",
                    "asyncio" in eager_modules,
                    "asyncio" in lazy_modules,
                    len(lazy_modules) * 2 < len(eager_modules),
                )


            KEEP_SAMPLE = (
                "from __future__ import annotations\\nimport os\\n\\n"
                "def f():\\n    import json\\n\\n"
                "try:\\n    import tomllib\\nexcept ImportError:\\n    pass\\n"
            )
            run_checks(
                [
                    (
                        "parse sample",
                        lambda: parse_importtime(SAMPLE_IMPORTTIME),
                        {"_json": 120, "json": 1300, "_decimal": 90, "decimal": 490},
                    ),
                    (
                        "make_lazy rewrites top-level imports",
                        lambda: [line for line in make_lazy(REPORT_CLI).splitlines() if "import" in line][:2],
                        ["lazy import asyncio", "lazy import email.parser"],
                    ),
                    (
                        "make_lazy leaves the rest",
                        lambda: make_lazy(KEEP_SAMPLE),
                        KEEP_SAMPLE.replace("\\nimport os", "\\nlazy import os"),
                    ),
                    (
                        "--version: same output, asyncio skipped, half the modules",
                        startup_comparison,
                        (True, True, False, True),
                    ),
                    (
                        "total still works lazily",
                        lambda: run_cli(make_lazy(REPORT_CLI), "total", "1.10", "2.20")[0],
                        "3.30",
                    ),
                ]
            )
            '''
        ),
    ]


def _recap_cells() -> list[NotebookNode]:
    """Recap for Unit 3.3."""
    return [
        md(
            """
            ### Recap — Unit 3.3

            | Concept | One-line takeaway | JS equivalent |
            | --- | --- | --- |
            | Modules as objects | `ModuleType` + `__spec__` / `__loader__` / `__path__`; the module dict is the globals | module records |
            | What `import` does | cache → finders → loader → insert in `sys.modules` → execute → bind | resolve → instantiate → evaluate |
            | Import forms | `from m import x` copies a binding; `__all__` controls `*` | ESM live bindings |
            | Run once | Top-level code runs on the first import; module = singleton; `reload` is a REPL tool | module caching |
            | `sys.path` | script folder or cwd, `PYTHONPATH`, stdlib, `site-packages` + `.pth`; `-P` drops the first | `node_modules` walk |
            | Packages | `__init__.py` runs and re-exports; namespace packages merge folders | `package.json` `exports` |
            | Relative imports | Need a parent package: use `python -m` | `./` specifiers |
            | Entry points | `__name__ == "__main__"`, `__main__.py`, `[project.scripts]` | `require.main`, `bin` |
            | Circular imports | Third module, module import, local import, `TYPE_CHECKING` | partial `exports` |
            | `importlib` | `import_module`, `resources.files`, `metadata`, `pkgutil.iter_modules`, entry points | `import()`, `require.resolve` |
            | Import hooks | Finders + loaders on `sys.meta_path` (and `sys.path_hooks`) | loaders / custom resolvers |
            | Lazy imports | `lazy import` (3.15), `LazyLoader`; measure with `-X importtime` | dynamic `import()` |

            **Further reading**

            - [The import system](https://docs.python.org/3/reference/import.html),
              [`importlib`](https://docs.python.org/3/library/importlib.html),
              [`importlib.resources`](https://docs.python.org/3/library/importlib.resources.html),
              [`importlib.metadata`](https://docs.python.org/3/library/importlib.metadata.html),
              [`pkgutil`](https://docs.python.org/3/library/pkgutil.html)
            - [`sys.path` initialization](https://docs.python.org/3/library/sys_path_init.html),
              [`site`](https://docs.python.org/3/library/site.html),
              [`__main__`](https://docs.python.org/3/library/__main__.html),
              [`-X importtime`](https://docs.python.org/3/using/cmdline.html#cmdoption-X)
            - [PEP 302 — New import hooks](https://peps.python.org/pep-0302/),
              [PEP 420 — Implicit namespace packages](https://peps.python.org/pep-0420/),
              [PEP 451 — ModuleSpec](https://peps.python.org/pep-0451/),
              [PEP 649 — Deferred evaluation of annotations](https://peps.python.org/pep-0649/),
              [PEP 810 — Explicit lazy imports](https://peps.python.org/pep-0810/)
            """
        ),
    ]


def cells() -> list[NotebookNode]:
    """Return the cells for Unit 3.3 and Lab 3.3."""
    return [
        *_overview_cells(),
        *_module_object_cells(),
        *_import_steps_cells(),
        *_import_forms_cells(),
        *_run_once_cells(),
        *_sys_path_cells(),
        *_package_cells(),
        *_relative_import_cells(),
        *_entry_point_cells(),
        *_circular_cells(),
        *_importlib_cells(),
        *_hook_cells(),
        *_lazy_cells(),
        *_js_bridge_cells(),
        *_lab_package_cells(),
        *_lab_import_system_cells(),
        *_recap_cells(),
    ]
