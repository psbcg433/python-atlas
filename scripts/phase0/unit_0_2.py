"""Unit 0.2 — Installing Python and Virtual Environments."""

from nbformat import NotebookNode

from nb_builder import code, md, predict_cells

UNIT_SETUP_SOURCE = '''
import os
import shutil
import subprocess
import sys
from pathlib import Path


def find_repo_root(start: Path | None = None) -> Path:
    """Walk up from start (default: the working directory) to the folder holding pyproject.toml."""
    current = (start or Path.cwd()).resolve()
    for folder in (current, *current.parents):
        if (folder / "pyproject.toml").exists():
            return folder
    raise FileNotFoundError("pyproject.toml not found above the working directory")


repo_root = find_repo_root()
venv_dir = repo_root / ".venv"
venv_scripts_dir = venv_dir / ("Scripts" if os.name == "nt" else "bin")
print(f"{repo_root.name=}, {venv_dir.exists()=}, {venv_scripts_dir.name=}")
'''


def cells() -> list[NotebookNode]:
    """Return the cells for Unit 0.2."""
    return [
        md(
            """
            ## Unit 0.2 — Installing Python and Virtual Environments

            **Objectives**

            - Install and pin a Python version per project with `uv`, never touching the OS Python.
            - Know what is inside `.venv/` and what "activating" it really does.
            - Detect from code whether a virtual environment is active and where imports come from.

            **JS bridge**

            | JavaScript concept | Python equivalent | The difference that bites |
            | --- | --- | --- |
            | `nvm install 22` | `uv python install 3.15` | uv downloads standalone builds; nothing is compiled or installed system-wide |
            | `.nvmrc` | `.python-version` | uv reads it automatically for every `uv run`, no shell hook needed |
            | `node_modules/` | `.venv/` | `.venv` also contains its own `python` launcher, not just packages |
            | Module resolution walks up `node_modules` folders | Imports search the `sys.path` list in order | No nesting: one flat `site-packages` per environment, one version of each package |

            The next cell is this unit's setup: it re-imports what the unit needs and locates the
            repository root and the virtual environment, so the unit runs on its own.
            """
        ),
        code(UNIT_SETUP_SOURCE),
        md(
            """
            ### 0.2.1 Installing with uv

            [uv](https://docs.astral.sh/uv/) manages Python versions as well as packages. These
            commands are run in a terminal (shown here, not executed from the notebook):

            ```bash
            uv python install 3.15        # download a standalone CPython 3.15 build
            uv python list                # every version uv knows: installed and downloadable
            uv python pin 3.15            # write .python-version in the current project
            ```

            `uv python pin` writes a one-line `.python-version` file. Every later `uv run`,
            `uv sync` or `uv venv` in this folder uses that version.

            Only **read-only** commands are executed from the notebook. The cell checks that `uv` is
            on `PATH` first (`shutil.which`) and prints a skip message if it is not.
            """
        ),
        code(
            '''
            def run_read_only(command: list[str]) -> str:
                """Run a read-only command and return its output, or a skip message if missing."""
                if shutil.which(command[0]) is None:
                    return f"Skipped: {command[0]!r} is not on PATH"
                no_color_environment = {**os.environ, "NO_COLOR": "1"}  # plain text, no ANSI codes
                completed = subprocess.run(
                    command, capture_output=True, text=True, env=no_color_environment, check=False
                )
                return (completed.stdout or completed.stderr).strip()


            print(run_read_only(["uv", "--version"]))
            print(run_read_only(["uv", "python", "list", "--only-installed"]))
            '''
        ),
        md(
            """
            The pin itself is just text. Reading it shows exactly what `uv` will use.
            """
        ),
        code(
            """
            pinned_version = (repo_root / ".python-version").read_text(encoding="utf-8").strip()
            print(f"{pinned_version=}")
            print(f"{sys.version_info[:2]=}")
            """
        ),
        md(
            """
            **Why never use the OS Python**

            | Problem | What happens |
            | --- | --- |
            | The OS depends on it | Linux tools (package managers, desktop utilities) import system packages; upgrading or removing them can break the OS |
            | You do not choose the version | It is whatever your distribution ships, and it changes on OS upgrades |
            | Installs need `sudo` and collide | `pip install` into it mixes your packages with the OS's; modern distros block it ([PEP 668](https://peps.python.org/pep-0668/) "externally managed") |
            | Not reproducible | Teammates and CI have different versions |

            The cell compares the interpreter running this notebook with the first `python3` on a
            `PATH` that excludes the virtual environment (usually the OS one). Paths vary by machine.
            """
        ),
        code(
            """
            path_without_venv = os.pathsep.join(
                folder
                for folder in os.environ.get("PATH", "").split(os.pathsep)
                if Path(folder).resolve() != venv_scripts_dir.resolve()
            )
            os_python = shutil.which("python3", path=path_without_venv)
            print(f"{sys.executable=}")
            print(f"{os_python=}")
            """
        ),
        md(
            """
            ### 0.2.2 Virtual environments

            A virtual environment is a folder that makes an existing Python installation behave as
            if it had its own, separate `site-packages`. `uv sync` creates `.venv/` automatically.

            | Item | Purpose |
            | --- | --- |
            | `pyvenv.cfg` | Marks the folder as a venv; `home` points at the base interpreter |
            | `bin/` (`Scripts\\` on Windows) | `python` (a link to the base interpreter), `activate` scripts, console scripts such as `jupyter` and `ruff` |
            | `lib/python3.15/site-packages/` | Every third-party package installed into this environment |

            First, `pyvenv.cfg`. Notice `include-system-site-packages = false`: the OS's packages are
            invisible here.
            """
        ),
        code(
            """
            print((venv_dir / "pyvenv.cfg").read_text(encoding="utf-8"))
            """
        ),
        md(
            """
            The `bin/` folder: `python*` entries are links to the base interpreter; the rest are
            console scripts created by installed packages (the equivalent of `node_modules/.bin`).
            The cell lists the first 15 entries and the total.
            """
        ),
        code(
            """
            bin_entries = sorted(entry.name for entry in venv_scripts_dir.iterdir())
            python_entries = [name for name in bin_entries if name.startswith("python")]
            print(f"{len(bin_entries)=}")
            print(f"{python_entries=}")
            print(f"{bin_entries[:15]=}")
            print(f"{(venv_scripts_dir / 'python').resolve()=}")
            """
        ),
        md(
            """
            `site-packages` is where `uv add` puts packages. `sysconfig` reports its path, and
            `importlib.metadata.distributions()` lists what is installed there.
            """
        ),
        code(
            """
            import importlib.metadata
            import sysconfig

            site_packages_dir = Path(sysconfig.get_paths()["purelib"])
            installed_names = sorted({dist.metadata["Name"] for dist in importlib.metadata.distributions()})
            print(f"{site_packages_dir.relative_to(repo_root)=}")
            print(f"{len(installed_names)=}")
            print(f"{installed_names[:10]=}")
            """
        ),
        md(
            """
            **Activation only changes `PATH`.** `source .venv/bin/activate` prepends `.venv/bin` to
            `PATH`, sets `VIRTUAL_ENV`, and changes the prompt (`PS1`). Nothing else. The cell
            prints the three lines of the activate script that do this.
            """
        ),
        code(
            """
            activate_script = (venv_scripts_dir / "activate").read_text(encoding="utf-8")
            activation_prefixes = ("VIRTUAL_ENV='", 'PATH="$VIRTUAL_ENV', 'PS1="(')
            for line in activate_script.splitlines():
                if line.strip().startswith(activation_prefixes):
                    print(line.strip())
            """
        ),
        md(
            """
            So activation is never required: running `.venv/bin/python` directly gives you the
            environment, because the interpreter finds `pyvenv.cfg` next to itself. The cell runs it
            with `VIRTUAL_ENV` removed and the venv removed from `PATH`. `uv run` works the same way.
            """
        ),
        code(
            """
            clean_environment = {key: value for key, value in os.environ.items() if key != "VIRTUAL_ENV"}
            clean_environment["PATH"] = path_without_venv
            probe_code = "import sys; print(sys.prefix != sys.base_prefix, sys.prefix)"
            completed = subprocess.run(
                [str(venv_scripts_dir / "python"), "-c", probe_code],
                capture_output=True,
                text=True,
                env=clean_environment,
                check=False,
            )
            print(f"in venv without activation: {completed.stdout.strip()}")
            """
        ),
        md(
            """
            #### Under the hood: how `site` finds `pyvenv.cfg`

            At startup CPython looks for `pyvenv.cfg` next to the executable or one folder up. If it
            finds one, it sets `sys.prefix` to the venv folder, and the `site` module (imported
            automatically unless `-S` is passed) adds the venv's `site-packages` to `sys.path`.
            Because `include-system-site-packages = false`, the base installation's site-packages
            and the per-user site directory are skipped.
            """
        ),
        code(
            """
            import site

            print(f"{sys.flags.no_site=}")
            print(f"{site.ENABLE_USER_SITE=}")
            for site_packages_path in site.getsitepackages():
                print(f"site-packages: {Path(site_packages_path).relative_to(repo_root)}")
            """
        ),
        md(
            """
            ### 0.2.3 Detecting the environment

            Inside a virtual environment `sys.prefix` is the venv folder, while `sys.base_prefix`
            is the installation it was created from. Outside a venv they are equal. This is the
            reliable test; `VIRTUAL_ENV` is only set by activation, and a Jupyter kernel is often
            launched without it.
            """
        ),
        code(
            '''
            def in_virtualenv() -> bool:
                """Return True when the running interpreter belongs to a virtual environment."""
                return sys.prefix != sys.base_prefix


            print(f"{sys.prefix=}")
            print(f"{sys.base_prefix=}")
            print(f"{in_virtualenv()=}")
            print(f"{os.environ.get('VIRTUAL_ENV')=}")
            '''
        ),
        md(
            """
            `sys.path` is the ordered list of folders searched by `import`. The first match wins.
            The cell labels each entry so you can see where the standard library ends and
            third-party packages begin.
            """
        ),
        code(
            '''
            def label_path_entry(entry: str) -> str:
                """Describe what kind of folder a sys.path entry is."""
                if entry in ("", os.getcwd()):
                    return "working directory (notebook folder)"
                if entry.endswith(".zip"):
                    exists_note = "present" if Path(entry).exists() else "absent, kept for zipped stdlib"
                    return f"standard library zip ({exists_note})"
                if entry.endswith("lib-dynload"):
                    return "standard library C extensions"
                if "site-packages" in entry and entry.startswith(sys.prefix):
                    return "virtual environment site-packages (third-party)"
                if entry.startswith(sys.base_prefix):
                    return "standard library (pure Python)"
                return "other (PYTHONPATH, .pth file or IPython)"


            for position, entry in enumerate(sys.path):
                print(f"[{position}] {label_path_entry(entry):48} {entry or repr(entry)}")
            '''
        ),
        md("#### Predict the output"),
        *predict_cells(
            snippet="""
            import sys
            print(sys.prefix == sys.base_prefix)
            """,
            answer="""
            `False`, because this kernel runs from `.venv`. `sys.prefix` is the venv folder,
            `sys.base_prefix` is uv's standalone CPython installation.
            """,
            proof="""
            print(sys.prefix == sys.base_prefix)
            """,
        ),
        *predict_cells(
            snippet="""
            import sys
            from pathlib import Path
            print(Path(sys.executable).parent.name, Path(sys.executable).parent.parent.name)
            """,
            answer="""
            `bin .venv` on Linux and macOS; `Scripts .venv` on Windows. The interpreter lives in the
            venv's scripts folder, so its grandparent is the venv itself.
            """,
            proof="""
            print(Path(sys.executable).parent.name, Path(sys.executable).parent.parent.name)
            """,
        ),
        md(
            """
            ### 0.2.4 JS bridge

            | npm / Node | uv / Python | Note |
            | --- | --- | --- |
            | `node_modules/` per project | `.venv/` per project | Both are disposable and git-ignored; recreate with `npm ci` / `uv sync` |
            | Nested `node_modules` allow two versions of one package | One flat `site-packages`; exactly one version of each package | Version conflicts must be resolved, not nested |
            | Node finds packages by walking up the folder tree | Python searches `sys.path` in order | Running from a different folder does not change which packages load |
            | `require.resolve("pkg")` | `importlib.util.find_spec("pkg").origin` | Shows the file an import would load |
            | Node binary is global (or per nvm version) | `.venv/bin/python` is per project | The environment includes its own interpreter link |

            The cell resolves where `nbformat` would be imported from without importing it,
            the same question `require.resolve` answers.
            """
        ),
        code(
            """
            import importlib.util

            nbformat_spec = importlib.util.find_spec("nbformat")
            nbformat_origin = Path(nbformat_spec.origin)
            print(f"{nbformat_origin.relative_to(repo_root)=}")
            print(f"{importlib.metadata.version('nbformat')=}")
            """
        ),
        md(
            """
            Like `node_modules`, a `.venv` is big. The cell adds up the size of every file in
            `site-packages`. The number depends on the installed versions and the OS.
            """
        ),
        code(
            """
            total_bytes = sum(
                file_path.stat().st_size for file_path in site_packages_dir.rglob("*") if file_path.is_file()
            )
            print(f"site-packages size: {total_bytes / 1_000_000:.0f} MB")
            """
        ),
        md(
            """
            ### Recap — Unit 0.2

            | Concept | One-line takeaway | JS equivalent |
            | --- | --- | --- |
            | `uv python install` | Downloads standalone CPython builds; no OS changes | `nvm install` |
            | `.python-version` | Pins the interpreter version for the project | `.nvmrc` |
            | OS Python | Belongs to the OS; never install into it | System Node from `apt` |
            | `.venv/` | Own `python` link, own `site-packages`, `pyvenv.cfg` marker | `node_modules/` |
            | Activation | Only edits `PATH`, `VIRTUAL_ENV` and the prompt; optional | Adding `node_modules/.bin` to `PATH` |
            | `sys.prefix != sys.base_prefix` | Reliable "am I in a venv?" test | — |
            | `sys.path` | Ordered import search list; first match wins | Node's module resolution algorithm |

            **Further reading**

            - [`venv` — Creation of virtual environments](https://docs.python.org/3/library/venv.html)
            - [`site` — Site-specific configuration hook](https://docs.python.org/3/library/site.html)
            - [The module search path (`sys.path`)](https://docs.python.org/3/library/sys_path_init.html)
            - [PEP 405 — Python virtual environments](https://peps.python.org/pep-0405/),
              [PEP 668 — Externally managed environments](https://peps.python.org/pep-0668/)
            - [uv: installing Python](https://docs.astral.sh/uv/guides/install-python/)
            """
        ),
    ]
