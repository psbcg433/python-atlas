"""Unit 3.3 — Modules, Packages and the Import System (with Lab 3.3)."""

from nbformat import NotebookNode

from nb_builder import code, md, predict_cells

UNIT_SETUP_SOURCE = '''
import ast
import contextlib
import importlib
import importlib.abc
import importlib.machinery
import importlib.metadata
import importlib.resources
import importlib.util
import io
import json
import os
import pkgutil
import platform
import runpy
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
from decimal import Decimal
from pathlib import Path

CHILD_ENV = {**os.environ, "PYTHON_COLORS": "0"}  # plain output from child interpreters


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
    """Write files (relative path -> source) to a temporary folder, or a zip of it, and put it
    first on sys.path. On exit, remove it and forget every module imported from it."""
    with tempfile.TemporaryDirectory(prefix="unit33_") as folder:
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


def run_python(
    *arguments: str, cwd: Path | None = None, extra_env: dict[str, str] | None = None
) -> str:
    """Run the kernel's interpreter in a child process; return stdout and stderr, stripped."""
    completed = subprocess.run(
        [sys.executable, *arguments],
        capture_output=True, text=True, cwd=cwd, timeout=120,
        env={**CHILD_ENV, **(extra_env or {})},
    )  # fmt: skip
    return (completed.stdout + completed.stderr).strip()


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

            The next cell is this unit's setup. `temporary_modules(files, zipped=False)` writes
            small modules to a temporary folder (or zip), puts it on `sys.path`, and on exit
            removes it and **forgets every module imported from it**, so demos never leak into
            later cells. `run_python(*arguments, cwd=...)` runs a child interpreter.
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

            for module in (json, json.decoder, contextlib):
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
            object sits in `sys.modules` **is** the module, even a fake one.
            """
        ),
        code(
            """
            import json as json_again

            print(f"{json_again is json is sys.modules['json']=}")
            sys.modules["fake_payments"] = types.SimpleNamespace(charge=lambda amount: f"faked {amount}")
            try:
                import fake_payments

                print(f"{fake_payments.charge(99)=}  (import returned whatever was cached)")
            finally:
                del sys.modules["fake_payments"]
            """
        ),
        md(
            """
            **Step 2, the finders.** `sys.meta_path` lists finder objects, asked in order.
            `importlib.util.find_spec(name)` runs the same search without executing anything.
            """
        ),
        code(
            """
            print(
                [
                    type(finder).__name__ if not isinstance(finder, type) else finder.__name__
                    for finder in sys.meta_path
                ]
            )
            for name in ("sys", "zipimport", "json", "_json", "no_such_module_here"):
                spec = importlib.util.find_spec(name)
                where = (
                    "None (ModuleNotFoundError on import)"
                    if spec is None
                    else (spec.origin if spec.origin in {"built-in", "frozen"} else Path(spec.origin).name)
                )
                print(f"find_spec({name!r:<22}) -> {where}")
            """
        ),
        md(
            """
            **Watching the steps.** A finder at the front of `sys.meta_path` that only records
            requests shows which imports reach the finders: `checkout_rules` and its helper do,
            the already-cached `json` does not. Inside the module, `__name__ in sys.modules` is
            already `True` while its code runs (step 4 before step 5).
            """
        ),
        code(
            '''
            class TracingFinder:
                """A meta path finder that records requests and lets the next finder answer."""

                def __init__(self) -> None:
                    self.requests: list[str] = []

                def find_spec(self, fullname: str, path: object, target: object = None) -> None:
                    self.requests.append(fullname)
                    return None


            checkout_files = {
                "checkout_rules.py": """
                    import json
                    import sys

                    import checkout_helpers

                    IN_SYS_MODULES_WHILE_RUNNING = __name__ in sys.modules
                    """,
                "checkout_helpers.py": "FREE_SHIPPING_ABOVE = 499\\n",
            }
            tracer = TracingFinder()
            with temporary_modules(checkout_files):
                sys.meta_path.insert(0, tracer)
                try:
                    import checkout_rules
                finally:
                    sys.meta_path.remove(tracer)
                print(f"{tracer.requests=}")
                print(f"{checkout_rules.IN_SYS_MODULES_WHILE_RUNNING=}")
            print(f"after the block: {'checkout_rules' in sys.modules=}")
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
            def simple_import(module_name: str) -> types.ModuleType:
                """The core of `import module_name` for a top-level module."""
                if module_name in sys.modules:  # 1. cache
                    return sys.modules[module_name]
                spec = importlib.util.find_spec(module_name)  # 2. finders
                if spec is None:
                    raise ModuleNotFoundError(f"No module named {module_name!r}", name=module_name)
                module = importlib.util.module_from_spec(spec)  # 3. create
                sys.modules[module_name] = module  # 4. insert before executing
                try:
                    spec.loader.exec_module(module)  # 5. execute
                except BaseException:
                    del sys.modules[module_name]
                    raise
                return module  # 6. the caller binds the name


            with temporary_modules({"discounts.py": "print('discounts executing')\\nFESTIVE = 0.1\\n"}):
                discounts = simple_import("discounts")
                print(f"{discounts.FESTIVE=}  {simple_import('discounts') is discounts=}")
                print(raised_message(lambda: simple_import("no_such_discounts")))
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

            The cell builds a `config` module and a small `shop` package and tries each form.
            """
        ),
        code(
            '''
            form_files = {
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
            with temporary_modules(form_files):
                import shop.cart

                print(
                    f"import shop.cart binds {shop.__name__!r}; then {shop.cart.Cart.__name__!r} by attribute"
                )
                import shop.cart as cart_module

                print(f"import shop.cart as cart_module -> {cart_module.__name__!r}")
                from config import region as region_name

                print(f"from config import region as region_name -> {region_name()!r}")
                star_namespace: dict[str, object] = {}
                exec("from config import *", star_namespace)
                star_names = sorted(name for name in star_namespace if not name.startswith("__"))
                print(f"from config import * -> {star_names}  (__all__ wins over TIMEOUT)")
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
            """
            binding_files = {"settings.py": "DEBUG = False\\nFEATURE_FLAGS = {'dark_mode': False}\\n"}
            with temporary_modules(binding_files):
                import settings
                from settings import DEBUG, FEATURE_FLAGS

                settings.DEBUG = True  # rebinding inside the module
                settings.FEATURE_FLAGS["dark_mode"] = True  # mutating the shared dict
                print(f"{DEBUG=}  {settings.DEBUG=}  (copied binding vs live attribute)")
                print(f"{FEATURE_FLAGS=}  (same dict object, so the mutation shows)")
            """
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
            singleton_files = {
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
            with temporary_modules(singleton_files):
                import billing
                import shipping

                print(f"{billing.charge()=}  {shipping.ship()=}  (one shared pool)")
                print(f"{billing.app_state is shipping.app_state=}")
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
            (The cell's new `rates.py` is a different size on purpose: a same-size rewrite
            within the same second would leave the timestamp-based `.pyc` looking valid, 3.2.13,
            and `reload` would run the old bytecode.)
            """
        ),
        code(
            """
            reload_files = {"rates.py": "class Rate:\\n    pass\\n\\nGST = 0.18\\n"}
            with temporary_modules(reload_files) as root:
                import rates
                from rates import GST

                old_rate = rates.Rate()
                (root / "rates.py").write_text("class Rate:\\n    pass\\n\\nGST = 0.12  # festive rate\\n")
                importlib.invalidate_caches()
                reloaded = importlib.reload(rates)
                print(f"{reloaded is rates=}  (same module object)")
                print(f"{rates.GST=}  {GST=}  (the copied name is stale)")
                print(f"{isinstance(old_rate, rates.Rate)=}  (old instance, new class)")
            """
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

            The cell labels this kernel's entries instead of printing full paths.
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
            adds one path per line, and lines starting with `import` are **executed**. Editable
            installs (`uv pip install -e .`) work this way, and so does some malware; review
            `.pth` files in your environment. `site.addsitedir(folder)` processes a folder the
            same way; the cell undoes everything afterwards.
            """
        ),
        code(
            """
            with tempfile.TemporaryDirectory() as site_folder, tempfile.TemporaryDirectory() as extra_folder:
                Path(site_folder, "course_extra.pth").write_text(
                    f"{extra_folder}\\nimport os; os.environ['UNIT33_PTH_RAN'] = 'yes'\\n"
                )
                path_before = list(sys.path)
                site.addsitedir(site_folder)
                added = [describe_path_entry(entry) for entry in sys.path if entry not in path_before]
                print(f"entries added: {len(added)} (the site folder and the folder named in the .pth)")
                print(f"import line executed: {os.environ.get('UNIT33_PTH_RAN')=}")
                sys.path[:] = path_before
                os.environ.pop("UNIT33_PTH_RAN", None)
            """
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
            where_source = """
                import os, sys
                first = sys.path[0]
                script_folder = os.path.dirname(os.path.abspath(__file__))
                if first == script_folder:
                    print("sys.path[0] = the script's folder")
                elif first in ("", os.getcwd()):
                    print("sys.path[0] = the current directory")
                else:
                    print("sys.path[0] = " + os.path.basename(first) + " (no script folder or cwd)")
                """
            with temporary_modules({"tools/__init__.py": "", "tools/where.py": where_source}) as root:
                for arguments in (
                    ["tools/where.py"],
                    ["-m", "tools.where"],
                    ["-P", "tools/where.py"],
                    ["-P", "-m", "tools.where"],
                ):
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
            inventory_files = {
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
            with temporary_modules(inventory_files):
                import inventory.reports.daily
                from inventory import StockLevel

                print(f"re-export is the same class: {StockLevel is inventory.stock.StockLevel}")
                print(f"{inventory.__all__=}  {[Path(p).name for p in inventory.__path__]=}")
            '''
        ),
        md(
            """
            **Namespace packages.** Two separate folders each contain a `plugins/` folder
            without `__init__.py`. Both are on `sys.path`, so `plugins` is one package whose
            `__path__` lists both folders.
            """
        ),
        code(
            """
            with (
                temporary_modules({"plugins/csv_export.py": "FORMAT = 'csv'\\n"}),
                temporary_modules({"plugins/pdf_export.py": "FORMAT = 'pdf'\\n"}),
            ):
                import plugins
                import plugins.csv_export
                import plugins.pdf_export

                print(f"{type(plugins.__path__).__name__=}  {len(list(plugins.__path__))=}")
                print(f"{getattr(plugins, '__file__', None)=}  {plugins.__spec__.origin=}")
                print(f"{plugins.csv_export.FORMAT=}  {plugins.pdf_export.FORMAT=}")
            """
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
            relative_files = {
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
            with temporary_modules(relative_files) as root:
                print(
                    "python -m inventory.reports.daily ->",
                    run_python("-m", "inventory.reports.daily", cwd=root),
                )
                script_output = run_python("inventory/reports/daily.py", cwd=root).splitlines()[-1]
                print("python inventory/reports/daily.py ->", script_output)
                import inventory.reports.daily

                print(f"imported: {inventory.reports.daily.__package__=}")
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
            """
        ),
        code(
            '''
            greeter_files = {
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
            with temporary_modules(greeter_files) as root:
                print("python -m greeter Ravi ->", run_python("-m", "greeter", "Ravi", cwd=root))
                print("python -m greeter.cli ->", run_python("-m", "greeter.cli", cwd=root))
                captured = io.StringIO()
                with contextlib.redirect_stdout(captured):
                    kernel_argv, sys.argv = sys.argv, ["greeter.cli", "Meena"]
                    try:
                        runpy.run_module("greeter.cli", run_name="__main__")
                    finally:
                        sys.argv = kernel_argv
                print(f"runpy.run_module(..., run_name='__main__') -> {captured.getvalue().strip()}")
                import greeter.cli

                print("import greeter.cli: nothing printed, main() not called")
                greeter.cli.main(["Asha"])
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
            with temporary_modules(BROKEN_INVOICES):
                print(raised_message(lambda: importlib.import_module("invoices")).split(" (/")[0])
            '''
        ),
        md(
            """
            Four standard fixes, each checked with the same scenario
            (`Invoice(1000).total()` should be `1180.0`):

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
            def check_invoice_fix(files: dict[str, str]) -> str:
                """Import the fixed modules (in both orders) and run the scenario."""
                results = []
                for first_import in ("invoices", "tax"):
                    with temporary_modules(files):
                        importlib.import_module(first_import)
                        results.append(importlib.import_module("invoices").Invoice(1000).total())
                return f"total={results[0]} (both import orders work: {results[0] == results[1]})"


            INVOICE_CLASS = """
                class Invoice:
                    def __init__(self, amount):
                        self.amount = amount

                    def total(self):
                        return self.amount + tax_for(self)
                """
            BROKEN_TAX = textwrap.dedent(BROKEN_INVOICES["tax.py"])
            fix_third_module = {
                "rates.py": """
                    RATE = 0.18

                    def tax_for(invoice):
                        return round(invoice.amount * RATE, 2)
                    """,
                "invoices.py": "from rates import tax_for\\n" + textwrap.dedent(INVOICE_CLASS),
                "tax.py": "from invoices import Invoice\\nfrom rates import RATE, tax_for\\n",
            }
            fix_module_import = {
                "invoices.py": "import tax\\n"
                + textwrap.dedent(INVOICE_CLASS).replace("tax_for(self)", "tax.tax_for(self)"),
                "tax.py": BROKEN_TAX.replace("from invoices import Invoice", "import invoices").replace(
                    "invoice: Invoice", "invoice: invoices.Invoice"
                ),
            }
            fix_local_import = {
                "invoices.py": textwrap.dedent(INVOICE_CLASS).replace(
                    "return self.amount", "from tax import tax_for\\n\\n        return self.amount"
                ),
                "tax.py": BROKEN_TAX,
            }
            fix_type_checking = {
                "invoices.py": BROKEN_INVOICES["invoices.py"],
                "tax.py": BROKEN_TAX.replace(
                    "from invoices import Invoice",
                    "from typing import TYPE_CHECKING\\n\\nif TYPE_CHECKING:\\n    from invoices import Invoice",
                ),
            }
            invoice_fixes = {
                "1. third module": fix_third_module,
                "2. module import": fix_module_import,
                "3. local import": fix_local_import,
                "4. TYPE_CHECKING": fix_type_checking,
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
            a library insists on one (extracting from a zip if needed).
            """
        ),
        code(
            """
            brand_files = {"brand/__init__.py": "", "brand/assets/tagline.txt": "Fresh groceries, fast.\\n"}
            with temporary_modules(brand_files):
                assets = importlib.resources.files("brand") / "assets"
                print(f"{type(assets).__name__=}")
                print(f"{[item.name for item in assets.iterdir()]=}")
                print(f"{(assets / 'tagline.txt').read_text().strip()=}")
                with importlib.resources.as_file(assets / "tagline.txt") as real_path:
                    print(f"as_file gives a real path: {real_path.exists()=}")
            """
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
            its exporters through the `nbconvert.exporters` group.
            """
        ),
        code(
            """
            console_scripts = importlib.metadata.entry_points(group="console_scripts")
            jupyter_commands = sorted(ep.name for ep in console_scripts if ep.name.startswith("jupyter"))
            print(f"jupyter commands: {jupyter_commands[:5]}")
            exporters = importlib.metadata.entry_points(group="nbconvert.exporters")
            if exporters:
                markdown_exporter = next(ep for ep in exporters if ep.name == "markdown")
                print(f"{markdown_exporter.name} -> {markdown_exporter.value}")
                print(f"loaded: {markdown_exporter.load().__name__}")
            else:
                print("Skipped: no nbconvert.exporters entry points installed")
            """
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
            `exec_module(module)`. The demo serves `<name>.json` files as modules whose
            attributes are the JSON keys.
            """
        ),
        code(
            '''
            class JsonModuleImporter(importlib.abc.MetaPathFinder, importlib.abc.Loader):
                """Import `settings` from settings.json in a folder: keys become attributes."""

                def __init__(self, folder: Path) -> None:
                    self.folder = folder

                def find_spec(
                    self, fullname: str, path: object, target: object = None
                ) -> importlib.machinery.ModuleSpec | None:
                    candidate = self.folder / f"{fullname}.json"
                    if "." in fullname or not candidate.exists():
                        return None  # not ours: the next finder tries
                    return importlib.util.spec_from_loader(fullname, self, origin=str(candidate))

                def create_module(self, spec: importlib.machinery.ModuleSpec) -> None:
                    return None  # default module object

                def exec_module(self, module: types.ModuleType) -> None:
                    module.__dict__.update(json.loads(Path(module.__spec__.origin).read_text()))
            '''
        ),
        md("Install it at the front of `sys.meta_path`, import, and remove it again:"),
        code(
            """
            with tempfile.TemporaryDirectory() as folder:
                Path(folder, "store_settings.json").write_text(
                    '{"currency": "INR", "free_shipping_above": 499}'
                )
                importer = JsonModuleImporter(Path(folder))
                sys.meta_path.insert(0, importer)
                try:
                    import store_settings

                    print(f"{store_settings.currency=}  {store_settings.free_shipping_above=}")
                    print(f"{type(store_settings.__loader__).__name__=}")
                finally:
                    sys.meta_path.remove(importer)
                    sys.modules.pop("store_settings", None)
            hook_names = [getattr(hook, "__name__", type(hook).__name__) for hook in sys.path_hooks]
            print(f"sys.path_hooks: {hook_names}")
            """
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

            Lazy syntax is 3.15-only, so the cells compile it from strings inside a version
            check (older kernels could not even parse the cell). First, the proxy and its first
            use, on a module that prints when it really runs:
            """
        ),
        code(
            '''
            LAZY_DEMO = """
            import sys
            lazy import heavy_report
            print("1. after `lazy import`:", "heavy_report" in sys.modules, type(globals()["heavy_report"]))
            print("2. first use returns:", heavy_report.summary())
            print("3. after first use:", "heavy_report" in sys.modules, type(globals()["heavy_report"]))
            """
            heavy_files = {
                "heavy_report.py": """
                    print("   heavy_report: module code runs now")

                    def summary():
                        return "ok"
                    """,
            }
            if sys.version_info >= (3, 15):
                with temporary_modules(heavy_files):
                    exec(compile(LAZY_DEMO, "<lazy demo>", "exec"), {"__name__": "lazy_demo"})
            else:
                print("Skipped: lazy imports need Python 3.15+")
            '''
        ),
        md(
            """
            **Restrictions and late errors.** Where the keyword is refused, and what happens
            when the module does not exist.
            """
        ),
        code(
            """
            if sys.version_info >= (3, 15):
                print(f"in a function: {compile_error('def load():\\n    lazy import json\\n')}")
                in_try = "try:\\n    lazy import json\\nexcept ImportError:\\n    pass\\n"
                print(f"in try:        {compile_error(in_try)}")
                print(f"star import:   {compile_error('lazy from json import *\\n')}")
                missing_demo = "lazy import no_such_reporting_lib\\nno_such_reporting_lib.render()\\n"
                print(
                    raised_message(
                        lambda: exec(compile(missing_demo, "<lazy>", "exec"), {"__name__": "missing_demo"})
                    )
                )
                pending_count = len(sys.lazy_modules)
                print(f"{sys.get_lazy_imports()=}  ({pending_count} stdlib modules still pending here)")
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
            attribute access.
            """
        ),
        code(
            '''
            def lazy_load(module_name: str) -> types.ModuleType:
                """Import module_name with LazyLoader: its code runs on first attribute access."""
                spec = importlib.util.find_spec(module_name)
                spec.loader = importlib.util.LazyLoader(spec.loader)
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
                return module


            with temporary_modules(heavy_files):
                report_module = lazy_load("heavy_report")
                print(f"module object exists: {type(report_module).__name__}")
                print(f"first attribute access -> {report_module.summary()=}")
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
    """3.3.13 JS bridge."""
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
            """
            with temporary_modules({"counter_module.py": "print('counter_module runs')\\nhits = 0\\n"}):
                import counter_module

                first_object = counter_module
                del sys.modules["counter_module"]
                import counter_module

                print(f"{first_object is counter_module=}  (a fresh module object)")
            """
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
            """
            with temporary_modules({"settings.py": "DEBUG = False\\n"}):
                import settings
                from settings import DEBUG

                settings.DEBUG = True
                print(DEBUG, settings.DEBUG)
            """,
        ),
    ]


def _lab_package_cells() -> list[NotebookNode]:
    """Lab 3.3 exercises 1–3."""
    return [
        md(
            """
            ### Lab 3.3

            Six exercises. For each, complete the stub, then run the check cell. Until then the
            checks print FAIL; that is expected. Packages are written to temporary folders by
            `temporary_modules` and forgotten afterwards, so you can re-run checks freely.

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
        md("Run the checks. Each one writes the package to a fresh temporary folder."),
        code(
            '''
            def with_shop(action: Callable[[Path], object]) -> object:
                """Write the learner's package, run action(root), forget the package."""
                with temporary_modules(shop_package_files()) as root:
                    return action(root)


            def shop_total(root: Path) -> Decimal:
                shop = importlib.import_module("shop")
                cart = shop.Cart()
                cart.add(shop.Product("tea", Decimal("120.50")), quantity=2)
                cart.add(shop.Product("rice", Decimal("80")))
                return cart.total()


            def shop_star_names(root: Path) -> list[str]:
                namespace: dict[str, object] = {}
                exec("from shop import *", namespace)
                return sorted(name for name in namespace if not name.startswith("__"))


            run_checks(
                [
                    (
                        "__all__",
                        lambda: with_shop(lambda root: sorted(importlib.import_module("shop").__all__)),
                        ["Cart", "Product"],
                    ),
                    (
                        "__version__",
                        lambda: with_shop(lambda root: importlib.import_module("shop").__version__),
                        "1.0",
                    ),
                    ("star import", lambda: with_shop(shop_star_names), ["Cart", "Product"]),
                    (
                        "re-export is the same class",
                        lambda: with_shop(
                            lambda root: (
                                importlib.import_module("shop").Cart
                                is importlib.import_module("shop.cart").Cart
                            )
                        ),
                        True,
                    ),
                    ("cart total", lambda: with_shop(shop_total), Decimal("321.00")),
                    (
                        "subpackage",
                        lambda: with_shop(
                            lambda root: importlib.import_module("shop.payments").charge(Decimal("321"))
                        ),
                        "charged INR 321.00",
                    ),
                    (
                        "relative import in cart.py",
                        lambda: "from .models import" in shop_package_files()["shop/cart.py"],
                        True,
                    ),
                    (
                        "python -m shop",
                        lambda: with_shop(lambda root: run_python("-m", "shop", cwd=root)),
                        "shop 1.0",
                    ),
                ]
            )
            '''
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
            with temporary_modules(BROKEN_ORDERS):
                failure = raised_message(lambda: importlib.import_module("customers")).split(" (/")[0]
                print(f"given version: {failure}")
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
        md("Run the checks. Each fix is imported in both orders."),
        code(
            '''
            def orders_scenario(files: dict[str, str]) -> list[str]:
                """Run the scenario after importing customers first, then orders first."""
                outcomes = []
                for first_import in ("customers", "orders"):
                    with temporary_modules(files):
                        importlib.import_module(first_import)
                        customers = importlib.import_module("customers")
                        orders = importlib.import_module("orders")
                        outcomes.append(customers.Customer("Asha").place_order(7).describe())
                        outcomes.append(raised_error_name(lambda: orders.Order(1, "nobody")))  # noqa: B023 (called at once)
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
