"""Unit 4.1 — Package Management and Project Structure (with Lab 4.1)."""

from nbformat import NotebookNode

from nb_builder import code, md, predict_cells

UNIT_SETUP_SOURCE = r'''
import base64
import email.parser
import hashlib
import importlib.machinery
import importlib.metadata
import importlib.util
import json
import os
import platform
import re
import shlex
import shutil
import socket
import subprocess
import sys
import sysconfig
import tarfile
import textwrap
import tomllib
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = find_repo_root()
scratch_dir = REPO_ROOT / "notebooks" / "_scratch"  # git-ignored
UNIT41_DIR = scratch_dir / "unit41"
WHEELHOUSE = UNIT41_DIR / "wheelhouse"
UNIT41_DIR.mkdir(parents=True, exist_ok=True)
VENV_BIN = Path(sys.executable).parent
COURSE_FILES = ("pyproject.toml", "uv.lock")


def file_digest(path: Path) -> str:
    """SHA-256 of a file's bytes, as hex."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


COURSE_DIGESTS_AT_START = {name: file_digest(REPO_ROOT / name) for name in COURSE_FILES}


def tool_env(**overrides: str) -> dict[str, str]:
    """Environment for child tools: plain output, scratch caches, nothing pointing at the course."""
    inherited = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("UV_", "PIP_", "VIRTUAL_ENV", "CONDA_", "PYTHONPATH"))
    }
    return {
        **inherited,
        "NO_COLOR": "1",
        "PYTHON_COLORS": "0",
        "UV_NO_PROGRESS": "1",
        "UV_PYTHON": "3.15",
        "UV_PYTHON_DOWNLOADS": "never",
        "UV_CACHE_DIR": str(UNIT41_DIR / "uv-cache"),
        "UV_TOOL_DIR": str(UNIT41_DIR / "uv-tools"),
        "UV_TOOL_BIN_DIR": str(UNIT41_DIR / "uv-tools-bin"),
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PIP_NO_COLOR": "1",
        "PIP_PROGRESS_BAR": "off",
        "PIP_CACHE_DIR": str(UNIT41_DIR / "pip-cache"),
        "GIT_CEILING_DIRECTORIES": str(scratch_dir),
        **overrides,
    }


TIMING = re.compile(r"\b(in|after) \d+(\.\d+)?(ms|s|µs)\b")
ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def tidy(text: str) -> str:
    """Show absolute paths as <scratch>, <repo> or ~ and timings as <time>; drop colour codes."""
    for folder, label in ((UNIT41_DIR, "<scratch>"), (REPO_ROOT, "<repo>"), (Path.home(), "~")):
        text = text.replace(f"file://{folder}", label).replace(str(folder), label)
    return ANSI_ESCAPE.sub("", TIMING.sub(r"\1 <time>", text))


def executable(name: str) -> str | None:
    """A path as given, the kernel's python, a tool from the course venv, or one on PATH."""
    if "/" in name:
        return name if Path(name).exists() else None
    if name == "python":
        return sys.executable
    local_tool = VENV_BIN / name
    return str(local_tool) if local_tool.exists() else shutil.which(name)


def run_tool(
    *command: str, cwd: Path = UNIT41_DIR, env: dict[str, str] | None = None, timeout: int = 300
) -> tuple[int, str]:
    """Run a CLI tool in a child process; return (exit code, tidied stdout + stderr)."""
    found = executable(command[0])
    if found is None:
        return 127, f"SKIP: {command[0]} is not installed on this machine"
    completed = subprocess.run(
        [found, *command[1:]],
        cwd=cwd,
        env=env or tool_env(),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return completed.returncode, tidy((completed.stdout + completed.stderr).rstrip())


def shell(
    *command: str,
    cwd: Path = UNIT41_DIR,
    env: dict[str, str] | None = None,
    keep: str | None = None,
    max_lines: int | None = None,
) -> int:
    """Print `[folder]$ command` and the tool's real output (only lines matching keep, if given)."""
    exit_code, output = run_tool(*command, cwd=cwd, env=env)
    shown = [Path(command[0]).name if "/" in command[0] else command[0], *command[1:]]
    print(f"[{tidy(str(cwd))}]$ {tidy(shlex.join(shown))}")
    lines = output.splitlines()
    if keep is not None:
        lines = [line for line in lines if re.search(keep, line)]
    if max_lines is not None and len(lines) > max_lines:
        lines = [*lines[:max_lines], f"... ({len(lines) - max_lines} more lines)"]
    if lines:
        print(textwrap.indent("\n".join(lines), "  "))
    if exit_code:
        print(f"  (exit code {exit_code})")
    return exit_code


def fresh_dir(name: str) -> Path:
    """An empty folder <scratch>/<name>, recreated on every run."""
    folder = UNIT41_DIR / name
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    return folder


def write_files(root: Path, files: dict[str, str]) -> Path:
    """Write relative path -> text (dedented) under root; return root."""
    for relative_path, text in files.items():
        target = root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(textwrap.dedent(text).lstrip("\n"))
    return root


SKIPPED_PARTS = {".venv", "__pycache__", ".pytest_cache", ".mypy_cache"}


def show_tree(root: Path) -> None:
    """Print every file under root (skipping virtual environments and caches)."""
    print(f"{tidy(str(root))}/")
    for path in sorted(root.rglob("*")):
        if path.is_file() and not SKIPPED_PARTS & set(path.relative_to(root).parts):
            print(f"  {path.relative_to(root).as_posix()}")


def show_file(path: Path, *, after: str | None = None) -> None:
    """Print a text file (optionally only from the first line containing after)."""
    text = path.read_text()
    if after is not None and after in text:
        text = text[text.index(after) :]
    print(f"--- {path.name} ---\n{tidy(text.rstrip())}")


@dataclass(frozen=True)
class DemoPackage:
    """A tiny package for the local wheelhouse (never published anywhere)."""

    name: str
    version: str
    source: str
    dependencies: tuple[str, ...] = ()
    extras: dict[str, list[str]] = field(default_factory=dict)
    scripts: dict[str, str] = field(default_factory=dict)

    @property
    def module(self) -> str:
        return self.name.replace("-", "_")

    def files(self) -> dict[str, str]:
        """pyproject.toml and src/<module>/__init__.py for this package."""
        lines = [
            "[project]",
            f'name = "{self.name}"',
            f'version = "{self.version}"',
            'description = "Course demo package (never published)"',
            'requires-python = ">=3.12"',
            'license = "MIT"',
            f"dependencies = {json.dumps(list(self.dependencies))}",
        ]
        if self.extras:
            lines += ["", "[project.optional-dependencies]"]
            lines += [f"{extra} = {json.dumps(reqs)}" for extra, reqs in self.extras.items()]
        if self.scripts:
            lines += ["", "[project.scripts]"]
            lines += [f'{command} = "{target}"' for command, target in self.scripts.items()]
        lines += ["", "[build-system]", 'requires = ["uv_build>=0.13,<0.14"]']
        lines += ['build-backend = "uv_build"']
        return {
            "pyproject.toml": "\n".join(lines) + "\n",
            f"src/{self.module}/__init__.py": textwrap.dedent(self.source).lstrip("\n"),
        }

    def wheel_name(self) -> str:
        return f"{self.module}-{self.version}-py3-none-any.whl"


RUPEE_V1 = """
    def fmt(amount: float) -> str:
        return f"INR {amount:,.2f}"
"""
RUPEE_V2 = """
    def fmt(amount: float, symbol: str = "\u20b9") -> str:
        return f"{symbol}{amount:,.2f}"
"""
GST_SOURCE = """
    import sys

    from rupee_fmt import fmt


    def with_gst(amount: float, rate: float = 0.18) -> float:
        return round(amount * (1 + rate), 2)


    def main() -> None:
        print(fmt(with_gst(float(sys.argv[1]))))
"""
WHEELHOUSE_PACKAGES = [
    *(DemoPackage("rupee-fmt", version, RUPEE_V1) for version in ("1.0.0", "1.1.0", "1.2.0")),
    *(DemoPackage("rupee-fmt", version, RUPEE_V2) for version in ("2.0.0", "2.1.0rc1")),
    DemoPackage(
        "table-print", "0.1.0", "def table(rows):\n    return '\\n'.join(map(str, rows))\n"
    ),
    DemoPackage("win-colors", "1.0.0", "RED = '\\x1b[31m'\n"),
    DemoPackage(
        "gst-calc",
        "1.0.0",
        GST_SOURCE,
        dependencies=("rupee-fmt>=1.0,<2", "win-colors>=1.0; sys_platform == 'win32'"),
        extras={"report": ["table-print>=0.1"]},
        scripts={"gst": "gst_calc:main"},
    ),
    DemoPackage(
        "gst-calc",
        "2.0.0",
        GST_SOURCE,
        dependencies=("rupee-fmt>=2",),
        extras={"report": ["table-print>=0.1"]},
        scripts={"gst": "gst_calc:main"},
    ),
    DemoPackage("legacy-invoice", "1.0.0", "TEMPLATE = 'plain'\n", dependencies=("rupee-fmt<1.1",)),
]


def publish_to_wheelhouse(package: DemoPackage) -> None:
    """Build one demo package (sdist + wheel) into the local wheelhouse with `uv build`."""
    source_root = write_files(
        fresh_dir(f"sources/{package.name}-{package.version}"), package.files()
    )
    exit_code, output = run_tool(
        "uv", "build", "--offline", "--out-dir", str(WHEELHOUSE), cwd=source_root
    )
    if exit_code:
        raise RuntimeError(f"uv build failed for {package.name} {package.version}:\n{output}")


def remove_from_wheelhouse(name: str, version: str) -> None:
    """Delete one release (wheel and sdist) from the local wheelhouse."""
    for path in WHEELHOUSE.glob(f"{name.replace('-', '_')}-{version}[-.]*"):
        path.unlink()


def build_wheelhouse() -> Path:
    """Build every demo package that is missing from the wheelhouse; return its folder."""
    WHEELHOUSE.mkdir(parents=True, exist_ok=True)
    for package in WHEELHOUSE_PACKAGES:
        if not (WHEELHOUSE / package.wheel_name()).exists():
            publish_to_wheelhouse(package)
    return WHEELHOUSE


def network_available(host: str = "pypi.org", port: int = 443, timeout: float = 3.0) -> bool:
    """Can we open a TCP connection to host? (Only two cells in this unit need the network.)"""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def raised_error_name(thunk: Callable[[], object]) -> str:
    """Call thunk and return the name of the exception it raised, or "no error"."""
    try:
        thunk()
    except Exception as error:
        return type(error).__name__
    return "no error"


build_wheelhouse()
print(f"Python {platform.python_version()}; {run_tool('uv', '--version')[1]}")
print(f"wheelhouse: {sorted(path.name for path in WHEELHOUSE.glob('*.whl'))}")
'''


def _overview_cells() -> list[NotebookNode]:
    """Unit opener and setup."""
    return [
        md(
            """
            ## Unit 4.1 — Package Management and Project Structure

            **Objectives**

            - Read a wheel filename and know whether it installs on a given interpreter; tell
              wheels from sdists and build frontends from build backends.
            - Use pip's resolver, editable installs, constraints files and cache, and explain why
              `pip freeze` is not a lockfile.
            - Drive a project end to end with uv: `init`, `add`, `lock`, `sync`, `run`, `tool`,
              inline-script metadata, workspaces, `export`, `build` and `publish`.
            - Write every table of a `pyproject.toml` from memory, and PEP 440 version
              specifiers that mean what you intend.
            - Choose a pinning strategy (application vs library), a project layout (`src/`) and a
              release scheme (SemVer or CalVer); keep the supply chain safe.

            **JS bridge: npm and `package.json`**

            | npm / Node.js | Python | The difference that bites |
            | --- | --- | --- |
            | registry.npmjs.org | PyPI (pypi.org) | A release holds several files: one sdist plus wheels per platform |
            | `package.json` | `pyproject.toml` | One file for metadata, build config **and** tool settings (ruff, mypy, pytest) |
            | `dependencies` | `[project] dependencies` | Same idea |
            | `devDependencies` | `[dependency-groups] dev` (PEP 735) | Groups are never published in the package metadata |
            | `optionalDependencies` / `peerDependencies` | extras: `[project.optional-dependencies]` | Extras are opt-in feature sets (`pkg[report]`), not "install if it builds" |
            | `node_modules/`, nested per package | One flat `site-packages/` per virtual environment | Only **one** version of each package per environment: conflicts are errors, not nested copies |
            | `package-lock.json`, `pnpm-lock.yaml` | `uv.lock`, `pylock.toml` (PEP 751) | `uv.lock` is cross-platform (one lock for Linux, macOS, Windows) |
            | `npm ci` | `uv sync --locked` / `--frozen` | Same promise: install exactly the lock |
            | `npx tool` | `uvx tool` | Same idea; uvx caches tool environments |
            | `"bin"` | `[project.scripts]` | uv/pip generate the launcher scripts |
            | `"scripts"` + `npm run` | no built-in task runner; `uv run <command>` | Use a Makefile, `just`, `poe` or plain `uv run` |
            | `^1.2.3` (caret) | `~=1.2` or `>=1.2,<2` | PEP 440 is not SemVer: there is no caret |
            | `.tgz` tarball | wheel (built, may be platform-specific) + sdist (source) | Installing a wheel runs no code; building an sdist does |
            | `"engines": {"node": ">=20"}` | `requires-python = ">=3.12"` | The resolver enforces it |
            | `npm link` | editable install (`uv sync`, `pip install -e`) | Implemented with a `.pth` file or an import hook |
            | `npm audit` | `pip-audit` | Same idea, different database (PyPA advisory DB / OSV) |
            | npm / pnpm workspaces | uv workspaces | One lockfile for all members |
            | `npm publish` | `uv publish` | Prefer trusted publishing (OIDC) over tokens |

            **How the demos run.** Every command runs in a child process inside
            `notebooks/_scratch/unit41/` (shown as `<scratch>`), with a scratch uv cache and the
            course's own environment variables removed, so nothing touches the course project.
            The setup cell builds a **local wheelhouse**, a folder of tiny demo packages
            (`rupee-fmt`, `gst-calc`, `table-print`, `win-colors`, `legacy-invoice`) in several
            versions. Demo projects point uv and pip at it with `no-index` + `find-links`, the
            standard way to install from a folder of wheels, so every resolution is real, offline
            and repeatable.

            | Demo package | Versions | Depends on |
            | --- | --- | --- |
            | `rupee-fmt` | 1.0.0, 1.1.0, 1.2.0, 2.0.0, 2.1.0rc1 | nothing (`fmt(amount)` changes output in 2.x) |
            | `gst-calc` | 1.0.0, 2.0.0 | `rupee-fmt>=1.0,<2` (1.x) or `>=2` (2.x); `win-colors` on Windows only; extra `report` → `table-print`; console script `gst` |
            | `table-print`, `win-colors` | 0.1.0, 1.0.0 | nothing |
            | `legacy-invoice` | 1.0.0 | `rupee-fmt<1.1` |
            """
        ),
        code(UNIT_SETUP_SOURCE),
    ]


def _ecosystem_cells() -> list[NotebookNode]:
    """4.1.1 The ecosystem."""
    return [
        md(
            """
            ### 4.1.1 The ecosystem

            **PyPI** (the Python Package Index) is Python's npm registry. A *project* has
            *releases* (versions), and each release has one or more **distribution files**:

            | File | Extension | What it is | Installing it |
            | --- | --- | --- | --- |
            | **sdist** (source distribution) | `.tar.gz` | Source code + `pyproject.toml` + `PKG-INFO` | Must be **built** first: runs the project's build backend, maybe a C compiler |
            | **wheel** (built distribution) | `.whl` (a zip) | Files laid out ready to copy into `site-packages`, plus a `.dist-info/` folder | Unzip and copy: **no code runs** |

            Installers prefer a wheel that matches the interpreter and fall back to the sdist.
            Which wheel matches is decided by the three **tags** in its filename:

            ```text
            {name}-{version}(-{build})?-{python tag}-{abi tag}-{platform tag}.whl
            numpy-2.3.4-cp315-cp315-manylinux_2_28_x86_64.whl
                        ^^^^^ ^^^^^ ^^^^^^^^^^^^^^^^^^^^^
                        |     |     platform: Linux with glibc >= 2.28 on x86-64
                        |     ABI: CPython 3.15's C ABI (cp315t = free-threaded build)
                        interpreter: CPython 3.15
            ```

            | Tag example | Meaning |
            | --- | --- |
            | `py3-none-any` | Pure Python, any Python 3, no C ABI, any OS: one wheel fits all |
            | `cp315-cp315-manylinux_2_28_x86_64` | Compiled for CPython 3.15, Linux glibc ≥ 2.28, x86-64 |
            | `cp315-cp315t-…` | The **free-threaded** (no-GIL) 3.15 build: the `t` ABI flag (Unit 3.1.5) |
            | `cp312-abi3-…` | Uses only the **stable ABI** (`abi3`): one wheel for CPython 3.12 and every later version |
            | `…-musllinux_1_2_aarch64` | Linux with musl libc (Alpine) on ARM64 |
            | `…-macosx_11_0_arm64`, `…-win_amd64` | macOS on Apple Silicon, 64-bit Windows |

            The next cell parses some (illustrative) wheel filenames with `packaging`, the
            library pip and uv's ideas come from, and asks whether each would install **here**.
            """
        ),
        code(
            r"""
            if importlib.util.find_spec("packaging") is None:
                print("SKIP: the packaging library is not installed")
            else:
                from packaging.tags import sys_tags
                from packaging.utils import parse_wheel_filename

                supported_here = set(sys_tags())
                example_wheels = [
                    "requests-2.32.5-py3-none-any.whl",
                    "numpy-2.3.4-cp315-cp315-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl",
                    "numpy-2.3.4-cp315-cp315t-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl",
                    "cryptography-46.0.3-cp311-abi3-manylinux_2_34_x86_64.whl",
                    "pydantic_core-2.50.4-cp315-cp315-musllinux_1_2_aarch64.whl",
                    "numpy-2.3.4-cp314-cp314-win_amd64.whl",
                ]
                for filename in example_wheels:
                    name, version, _build, wheel_tags = parse_wheel_filename(filename)
                    tag = sorted(wheel_tags, key=str)[0]
                    installs = bool(wheel_tags & supported_here)
                    print(
                        f"{name:<14} {str(version):<8} {tag.interpreter:<6} {tag.abi:<7} "
                        f"{tag.platform:<26} installs here: {installs}"
                    )
            """
        ),
        md(
            """
            A wheel installs when **any** of its tags is in the interpreter's list of supported
            tags, which is ordered from most to least specific. The installer picks the wheel
            whose best tag comes first in this list. Here is the start of that list for this
            kernel:
            """
        ),
        code(
            r"""
            if importlib.util.find_spec("packaging") is not None:
                from packaging.tags import sys_tags

                all_tags = [str(tag) for tag in sys_tags()]
                print(f"{len(all_tags)} supported tags; the first eight and the last:")
                for tag in [*all_tags[:8], "...", all_tags[-1]]:
                    print(f"  {tag}")
            print(f"{sys.implementation.cache_tag=}  {sys.abiflags=}")
            print(f"{sysconfig.get_config_var('SOABI')=}")
            """
        ),
        md(
            """
            **manylinux.** Compiled Linux wheels must run on many distributions. A
            `manylinux_2_28` wheel promises it only needs glibc 2.28 or newer, so it runs on any
            distribution at least that recent. Your glibc version decides which `manylinux_2_X`
            tags appear in the list above (`musllinux` is the same idea for Alpine's musl libc).

            **abi3, the stable ABI.** An extension compiled against the *limited C API* uses only
            the stable ABI and is tagged `cp3X-abi3`: one wheel serves that CPython version and
            all later ones. Its files end in `.abi3.so`. The free-threaded build has a different
            object layout, so it has its own ABI tag (`cp315t`) and suffixes; 3.15 adds `abi3t`,
            a stable ABI for free-threaded builds (*New in 3.15*). The next cell asks
            this kernel and, if one is installed, the uv-managed free-threaded 3.15 (Unit 3.1.5)
            in a child process.
            """
        ),
        code(
            r'''
            def find_free_threaded_python() -> str | None:
                """Path of an installed free-threaded 3.15 interpreter, or None."""
                env = {key: value for key, value in tool_env().items() if key != "UV_PYTHON"}
                found = subprocess.run(
                    [executable("uv"), "python", "find", "3.15t"], capture_output=True, text=True, env=env
                )
                return found.stdout.strip() if found.returncode == 0 else None


            ABI_PROBE = """
            import importlib.machinery, platform, sys, sysconfig
            soabi = sysconfig.get_config_var("SOABI")
            print(platform.python_version(), f"abiflags={sys.abiflags!r}", f"SOABI={soabi}")
            print("  extension suffixes:", importlib.machinery.EXTENSION_SUFFIXES)
            """
            print("default build:", run_tool("python", "-c", ABI_PROBE)[1])
            libc_name, libc_version = platform.libc_ver()
            print(f"  C library: {libc_name} {libc_version} -> manylinux_2_X tags up to that glibc")
            free_threaded_python = find_free_threaded_python()
            if free_threaded_python is None:
                print("SKIP: no free-threaded 3.15 installed (uv python install 3.15t)")
            else:
                print("free-threaded build:", run_tool(free_threaded_python, "-c", ABI_PROBE)[1])
            '''
        ),
        md(
            """
            **Build frontends and backends (PEP 517 / PEP 518).** Building a wheel is split
            between two programs that talk through a small, standard Python API:

            | Role | Job | Examples |
            | --- | --- | --- |
            | **Frontend** | Reads `[build-system]`, creates an isolated build environment, installs `requires`, calls the backend's hooks | pip, uv, `python -m build` |
            | **Backend** | Turns the source tree into a wheel or sdist | `setuptools`, `hatchling`, `flit-core`, `pdm-backend`, `poetry-core`, `uv_build`, `maturin` (Rust), `scikit-build-core` (CMake) |

            PEP 518 added `[build-system] requires` (what the build needs installed), PEP 517
            the hooks (`build_wheel`, `build_sdist`, `get_requires_for_build_wheel`, …) and PEP
            660 the editable-install hook (`build_editable`). Any frontend can build any project.

            ```mermaid
            flowchart LR
                F["frontend (uv, pip)"] -->|"reads [build-system]"| P[pyproject.toml]
                F -->|"creates isolated env, installs requires"| E[build env]
                F -->|"calls build_wheel() / build_sdist()"| B["backend (uv_build, hatchling, ...)"]
                B -->|"writes"| W[".whl / .tar.gz"]
                F -->|"installs the wheel"| S[site-packages]
            ```

            <details><summary>ASCII fallback</summary>

            ```text
            frontend (uv, pip) --reads--> pyproject.toml [build-system]
                     |--creates isolated env + installs `requires`
                     |--calls build_wheel()/build_sdist()--> backend --writes--> .whl/.tar.gz
                     '--installs the wheel--> site-packages
            ```

            </details>

            **Under the hood: a complete build backend in 40 lines.** A backend is just a module
            with those functions. The next cell writes one (`tiny_backend.py`), a project that
            uses it through `backend-path` (an in-tree backend, so `requires` is empty), and
            builds it with uv as the frontend.
            """
        ),
        code(
            r'''
            TINY_BACKEND = r"""
                # A minimal PEP 517 + PEP 660 build backend (pure Python, py3-none-any only).
                import base64, hashlib, io, os, tarfile, tomllib, zipfile
                from pathlib import Path

                PROJECT = tomllib.loads(Path("pyproject.toml").read_text())["project"]
                NAME, VERSION = PROJECT["name"], PROJECT["version"]
                MODULE = NAME.replace("-", "_")
                DIST_INFO = f"{MODULE}-{VERSION}.dist-info"
                METADATA = f"Metadata-Version: 2.4\nName: {NAME}\nVersion: {VERSION}\n"

                def _record_line(path, data):
                    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=")
                    return f"{path},sha256={digest.decode()},{len(data)}"

                def _wheel(directory, files):
                    files = {**files, f"{DIST_INFO}/METADATA": METADATA.encode(),
                             f"{DIST_INFO}/WHEEL": b"Wheel-Version: 1.0\nGenerator: tiny\n"
                             b"Root-Is-Purelib: true\nTag: py3-none-any\n"}
                    record = [_record_line(path, data) for path, data in files.items()]
                    name = f"{MODULE}-{VERSION}-py3-none-any.whl"
                    with zipfile.ZipFile(Path(directory) / name, "w") as wheel:
                        for path, data in files.items():
                            wheel.writestr(path, data)
                        wheel.writestr(f"{DIST_INFO}/RECORD", "\n".join(record) + f"\n{DIST_INFO}/RECORD,,\n")
                    return name

                def get_requires_for_build_wheel(config_settings=None):
                    return []

                def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
                    sources = {p.as_posix(): p.read_bytes() for p in Path(MODULE).rglob("*.py")}
                    return _wheel(wheel_directory, sources)

                def build_editable(wheel_directory, config_settings=None, metadata_directory=None):
                    # PEP 660: the "wheel" holds only a .pth file pointing at the source folder
                    return _wheel(wheel_directory, {f"_{MODULE}_editable.pth": (os.getcwd() + "\n").encode()})

                def build_sdist(sdist_directory, config_settings=None):
                    name = f"{MODULE}-{VERSION}.tar.gz"
                    with tarfile.open(Path(sdist_directory) / name, "w:gz") as sdist:
                        sources = ["pyproject.toml", "tiny_backend.py", *map(str, Path(MODULE).rglob("*.py"))]
                        for path in sources:
                            sdist.add(path, f"{MODULE}-{VERSION}/{path}")
                        info = tarfile.TarInfo(f"{MODULE}-{VERSION}/PKG-INFO")
                        info.size = len(METADATA)
                        sdist.addfile(info, io.BytesIO(METADATA.encode()))
                    return name
            """
            tiny_root = write_files(
                fresh_dir("tiny-tax"),
                {
                    "pyproject.toml": """
                        [build-system]
                        requires = []                    # nothing to install: the backend is in-tree
                        build-backend = "tiny_backend"   # module that defines the hooks
                        backend-path = ["."]             # ...found in the project folder itself

                        [project]
                        name = "tiny-tax"
                        version = "0.1.0"
                    """,
                    "tiny_backend.py": TINY_BACKEND,
                    "tiny_tax/__init__.py": "GST_RATE = 0.18\n",
                },
            )
            shell("uv", "build", "--offline", cwd=tiny_root)
            '''
        ),
        md(
            """
            uv (the frontend) built the sdist first, then a wheel *from* the unpacked sdist, which
            proves the sdist is complete. The frontend's side of the protocol is just "import
            the backend and call a hook". Calling the hooks yourself in a child interpreter shows
            there is nothing more to it, and lists what each archive contains:
            """
        ),
        code(
            r'''
            HOOK_CALLER = """
            import sys, tarfile, zipfile
            sys.path.insert(0, ".")          # backend-path = ["."]
            import tiny_backend as backend    # build-backend = "tiny_backend"
            print("get_requires_for_build_wheel ->", backend.get_requires_for_build_wheel())
            wheel = backend.build_wheel("hook-dist")
            sdist = backend.build_sdist("hook-dist")
            print("build_wheel ->", wheel, zipfile.ZipFile(f"hook-dist/{wheel}").namelist())
            print("build_sdist ->", sdist, tarfile.open(f"hook-dist/{sdist}").getnames())
            """
            (tiny_root / "hook-dist").mkdir(exist_ok=True)
            print(run_tool("python", "-c", HOOK_CALLER, cwd=tiny_root)[1])
            '''
        ),
    ]


def _pip_cells() -> list[NotebookNode]:
    """4.1.2 pip."""
    return [
        md(
            """
            ### 4.1.2 pip

            pip is the reference installer that ships with CPython (through `ensurepip`). uv
            projects do not include it, so the demo makes a classic virtual environment with
            `python -m venv`, which installs pip from the wheel bundled with the interpreter
            (no network needed). pip reads its options from `PIP_*` environment variables, so
            the demo sets `PIP_NO_INDEX=1` and `PIP_FIND_LINKS=<wheelhouse>` once.

            | npm | pip |
            | --- | --- |
            | `npm install pkg` | `pip install pkg` |
            | `npm install` (from package.json) | `pip install -r requirements.txt` or `pip install .` |
            | `npm ls` | `pip list`, `pip show pkg`, `pip freeze` |
            | `npm link` | `pip install -e path` |
            """
        ),
        code(
            r'''
            PIP_VENV = UNIT41_DIR / "pip-venv"
            shutil.rmtree(PIP_VENV, ignore_errors=True)
            print(run_tool("python", "-m", "venv", str(PIP_VENV))[1] or "venv created")
            PIP_PYTHON = str(PIP_VENV / "bin" / "python")
            PIP_ENV = tool_env(PIP_NO_INDEX="1", PIP_FIND_LINKS=str(WHEELHOUSE))


            def pip(*arguments: str, cwd: Path = UNIT41_DIR, **options: object) -> int:
                """Run pip inside the scratch venv against the local wheelhouse."""
                return shell(PIP_PYTHON, "-m", "pip", *arguments, cwd=cwd, env=PIP_ENV, **options)


            pip("--version")
            pip("list")
            '''
        ),
        md(
            """
            **The resolver.** Since pip 20.3, pip uses a *backtracking* resolver: it picks
            candidate versions, and when a later requirement conflicts it backs up and tries
            older ones. Below, `gst-calc 1.0.0` accepts `rupee-fmt>=1.0,<2` and `legacy-invoice`
            needs `rupee-fmt<1.1`, so the only answer is `rupee-fmt 1.0.0`. `--dry-run` resolves
            without installing.
            """
        ),
        code(
            r"""
            pip("install", "--dry-run", "gst-calc==1.0.0", "legacy-invoice", keep="Would install")
            """
        ),
        md(
            """
            `gst-calc 2.0.0` needs `rupee-fmt>=2`, which can never satisfy `legacy-invoice`'s
            `<1.1`. npm would nest two copies; Python has one flat environment, so the resolver
            reports a conflict and installs nothing:
            """
        ),
        code(
            r"""
            pip(
                "install",
                "--dry-run",
                "gst-calc==2.0.0",
                "legacy-invoice",
                keep=r"ERROR|requires|conflict|depends",
            )
            """
        ),
        md(
            """
            **Editable installs** (`pip install -e path`, PEP 660). The project is "installed"
            but its code stays in the working folder, so edits show up without reinstalling,
            like `npm link`. pip asks the backend's `build_editable` hook for a wheel; our tiny
            backend's editable wheel holds a single `.pth` file naming the source folder, and
            `site` adds that folder to `sys.path` at startup (Unit 3.3.5).
            """
        ),
        code(
            r"""
            pip("install", "-e", str(tiny_root), keep="Successfully|ERROR")
            site_packages = next(PIP_VENV.glob("lib/python3*/site-packages"))
            for pth_file in site_packages.glob("_tiny*.pth"):
                print(f"{pth_file.name}: {tidy(pth_file.read_text().strip())}")
            WHERE = "import tiny_tax; print(tiny_tax.__file__, tiny_tax.GST_RATE)"
            print("before edit:", run_tool(PIP_PYTHON, "-c", WHERE)[1])
            (tiny_root / "tiny_tax" / "__init__.py").write_text("GST_RATE = 0.12\n")
            print("after edit: ", run_tool(PIP_PYTHON, "-c", WHERE)[1], "(no reinstall)")
            """
        ),
        md(
            """
            **`pip freeze` vs a lockfile.** `pip freeze` prints what is installed *right now*
            in requirements format. It is a snapshot, not a lockfile:

            | `pip freeze > requirements.txt` | A real lockfile (`uv.lock`, `pylock.toml`) |
            | --- | --- |
            | Only this machine's platform and Python | Resolved for every platform and marker |
            | No hashes (unless you add them) | Hashes for every file |
            | Mixes runtime and dev tools, and anything installed by hand | Generated from declared dependencies and groups |
            | No record of *why* a package is there | Records the dependency graph |
            | Editable installs appear as paths | Editable sources recorded properly |
            """
        ),
        code(
            r"""
            pip("install", "gst-calc==1.0.0", keep="Successfully")
            pip("freeze")
            """
        ),
        md(
            """
            **Constraints files** (`-c constraints.txt`) cap versions *without* asking for
            anything to be installed: a constraint only matters if something else pulls that
            package in. Teams use one shared constraints file to keep many services on the same
            versions. Here a constraint holds `rupee-fmt` below 1.2 even though `gst-calc`
            allows up to `<2`:
            """
        ),
        code(
            r"""
            (UNIT41_DIR / "constraints.txt").write_text("rupee-fmt<1.2\ntable-print==0.1.0\n")
            pip(
                "install",
                "--dry-run",
                "--ignore-installed",
                "-c",
                "constraints.txt",
                "gst-calc==1.0.0",
                keep="Would install",
            )
            """
        ),
        md(
            """
            **The cache.** pip caches downloaded files (HTTP cache) and wheels it built from
            sdists, so a second install is fast. `pip cache dir / info / list / purge` manage
            it. The demo's `PIP_CACHE_DIR` points into the scratch folder; your real one is
            usually `~/.cache/pip`. Installing from local wheels stores nothing, so the cache is
            empty. uv's cache (next section) works differently.
            """
        ),
        code(
            r"""
            pip("cache", "dir")
            pip("cache", "info")
            """
        ),
    ]


def _uv_cells() -> list[NotebookNode]:
    """4.1.3 uv in depth."""
    return [
        md(
            """
            ### 4.1.3 uv in depth

            uv (from Astral, written in Rust) replaces pip, pip-tools, virtualenv, pipx, pyenv
            and twine with one fast binary. You met `uv init`, `uv add` and `uv run` in Unit
            0.3; this section covers the rest.

            **The global cache.** uv keeps one cache per machine (`uv cache dir`). Installing a
            package into a virtual environment **hardlinks** (or copy-on-write clones) files
            out of the cache instead of copying them, like pnpm's content-addressed store. Ten
            projects using the same package share one copy on disk. The first command below
            asks uv for your real cache location; the demos use a scratch cache.
            """
        ),
        code(
            r"""
            real_env = {key: value for key, value in tool_env().items() if key != "UV_CACHE_DIR"}
            shell("uv", "cache", "dir", env=real_env)
            shell("uv", "cache", "dir")
            shell("uv", "cache", "size", "--human", keep="iB$")  # experimental command in uv 0.13
            """
        ),
        md(
            """
            **`uv init`: three kinds of project.** All three create a `pyproject.toml`; they
            differ in whether the project is *built and installed* into its own environment.

            | Command | Layout | `[build-system]` | Use it for |
            | --- | --- | --- | --- |
            | `uv init --app --no-package` | `main.py` at the root | none (a *virtual* project: only its dependencies are installed) | Scripts, notebooks, web services you never `pip install` |
            | `uv init --app` (packaged on this uv) or `--package` | `src/<name>/__init__.py` + `[project.scripts]` | yes | CLIs and apps that need an entry point |
            | `uv init --lib` | `src/<name>/__init__.py` + `py.typed` | yes | Libraries others import |

            The course itself is a virtual project (`uv init --bare`, Unit 0.3). Every `uv init`
            below passes `--no-workspace` (otherwise uv would offer to add the scratch project
            to an enclosing workspace), `--author-from none` (otherwise uv copies your git name
            and e-mail into the file) and `--vcs none`.
            """
        ),
        code(
            r"""
            UV_INIT = ("uv", "init", "--no-workspace", "--author-from", "none", "--vcs", "none", "--no-readme")
            init_root = fresh_dir("init-demo")
            for kind, project in [
                ("--app --no-package", "shop-app"),
                ("--app", "shop-cli"),
                ("--package", "invoicing-cli"),
                ("--lib", "price-lib"),
            ]:
                shell(*UV_INIT, *kind.split(), project, cwd=init_root)
            show_tree(init_root)
            """
        ),
        md("Compare the generated `pyproject.toml` files of a virtual app and a library:"),
        code(
            r"""
            show_file(init_root / "shop-app" / "pyproject.toml")
            show_file(init_root / "price-lib" / "pyproject.toml")
            show_file(init_root / "invoicing-cli" / "src" / "invoicing_cli" / "__init__.py")
            """
        ),
        md(
            """
            **A working project: `invoicing`.** The rest of this section drives one packaged
            project. First it is pointed at the wheelhouse through a `[tool.uv]` table (the
            same settings a company uses for a private index). Before locking, the newest
            `rupee-fmt` 1.x (1.2.0) is removed from the wheelhouse; it is "released" again
            later to show how upgrades work.
            """
        ),
        code(
            r"""
            projects_root = fresh_dir("projects")
            shell(*UV_INIT, "--package", "invoicing", cwd=projects_root)
            invoicing = projects_root / "invoicing"
            with (invoicing / "pyproject.toml").open("a") as pyproject_file:
                pyproject_file.write(
                    "\n[tool.uv]\nno-index = true               # never contact PyPI\n"
                    'find-links = ["../../wheelhouse"]   # resolve from the local wheelhouse\n'
                )
            remove_from_wheelhouse("rupee-fmt", "1.2.0")
            print(sorted(path.name for path in WHEELHOUSE.glob("rupee_fmt*.whl")))
            """
        ),
        md(
            """
            **`uv add` with version specifiers.** `uv add` edits `pyproject.toml`, re-locks and
            syncs the environment in one step. Quote specifiers so the shell does not treat
            `<` or `>` as redirection. The four flags decide *where* the requirement goes:

            | Command | Written to | Installed by `uv sync`? | Published in the wheel? |
            | --- | --- | --- | --- |
            | `uv add "gst-calc~=1.0"` | `[project] dependencies` | yes | yes (`Requires-Dist`) |
            | `uv add --dev pkg` | `[dependency-groups] dev` | yes (default group) | no |
            | `uv add --group docs pkg` | `[dependency-groups] docs` | only with `--group docs` | no |
            | `uv add --optional report pkg` | `[project.optional-dependencies] report` | only with `--extra report` | yes, as an extra |
            """
        ),
        code(
            r"""
            shell("uv", "add", "gst-calc~=1.0", cwd=invoicing)
            shell("uv", "add", "--dev", "rupee-fmt>=1.1", cwd=invoicing)
            shell("uv", "add", "--group", "docs", "table-print", cwd=invoicing)
            shell("uv", "add", "--optional", "report", "table-print>=0.1", cwd=invoicing)
            """
        ),
        md(
            """
            The four tables uv wrote (note that `uv add --dev rupee-fmt>=1.1` kept the user's
            specifier, while a bare name gets a lower bound from the version it resolved):
            """
        ),
        code(
            r"""
            show_file(invoicing / "pyproject.toml", after="dependencies")
            """
        ),
        md(
            """
            **`uv lock --upgrade-package`.** A lockfile is *stable*: `uv lock` keeps every
            locked version that still satisfies `pyproject.toml`, even when newer ones exist.
            Below, `rupee-fmt 1.2.0` is "released" into the wheelhouse. Plain `uv lock` changes
            nothing; `uv lock --upgrade-package rupee-fmt` moves just that package (and only as
            far as the specifiers allow, so 2.x is never chosen). `uv lock --upgrade` would move
            everything.
            """
        ),
        code(
            r'''
            def locked_rupee() -> str:
                """The rupee-fmt version recorded in invoicing/uv.lock."""
                lock_text = (invoicing / "uv.lock").read_text()
                return re.search(r'name = "rupee-fmt"\nversion = "([^"]+)"', lock_text)[1]


            print(f"locked before the release: rupee-fmt {locked_rupee()}")
            publish_to_wheelhouse(next(p for p in WHEELHOUSE_PACKAGES if p.version == "1.2.0"))
            shell("uv", "lock", cwd=invoicing)
            print(f"after plain `uv lock`:     rupee-fmt {locked_rupee()}")
            shell("uv", "lock", "--upgrade-package", "rupee-fmt", cwd=invoicing)
            print(f"after --upgrade-package:   rupee-fmt {locked_rupee()}")
            '''
        ),
        md(
            """
            **`uv sync --locked` vs `--frozen`.** Both promise not to change the lockfile, which
            is what CI and Docker builds want:

            | Flag | If `pyproject.toml` and `uv.lock` disagree | Use it |
            | --- | --- | --- |
            | (none) | Re-locks, then installs | Day-to-day development |
            | `--locked` | **Fails** with an error | CI: catch a forgotten `uv lock` |
            | `--frozen` | Installs the lock **as is**, without checking `pyproject.toml` | Docker layers that copy only `uv.lock`, or when resolution is impossible here |

            The demo edits `pyproject.toml` by hand (adding `win-colors` for every platform)
            without re-locking:
            """
        ),
        code(
            r"""
            pyproject_path = invoicing / "pyproject.toml"
            original_pyproject = pyproject_path.read_text()
            pyproject_path.write_text(
                original_pyproject.replace('"gst-calc~=1.0",', '"gst-calc~=1.0",\n    "win-colors",')
            )
            shell("uv", "sync", "--locked", cwd=invoicing)
            shell("uv", "sync", "--frozen", cwd=invoicing)
            pyproject_path.write_text(original_pyproject)  # undo the hand edit
            shell("uv", "sync", "--locked", cwd=invoicing)
            """
        ),
        md(
            """
            `uv run` syncs first, then runs a command inside the project environment. The
            project's console script (`invoicing = "invoicing:main"` in `[project.scripts]`) is
            installed as a command. Edit `main()` to use the dependency and run it again; no
            reinstall is needed because the project itself is installed *editable*.
            """
        ),
        code(
            r'''
            shell("uv", "run", "invoicing", cwd=invoicing)
            write_files(
                invoicing / "src" / "invoicing",
                {
                    "__init__.py": """
                import sys

                from gst_calc import with_gst
                from rupee_fmt import fmt


                def main() -> None:
                    amount = float(sys.argv[1]) if len(sys.argv) > 1 else 100.0
                    print(f"{fmt(amount)} + GST = {fmt(with_gst(amount))}")
            """
                },
            )
            shell("uv", "run", "invoicing", "2500", cwd=invoicing)
            '''
        ),
        md(
            """
            **`uv tool` and `uvx`** are uv's pipx and npx. `uv tool install` puts a CLI into
            its own isolated environment and links its commands into a bin folder;
            `uvx` (short for `uv tool run`) runs a tool in a cached throwaway environment. The
            demo redirects `UV_TOOL_DIR` and `UV_TOOL_BIN_DIR` into the scratch folder, so
            nothing lands in your real `~/.local/bin`.

            | npm | uv |
            | --- | --- |
            | `npm install -g pkg` | `uv tool install pkg` |
            | `npx pkg` | `uvx pkg` (`uvx --from pkg command` when names differ) |
            | `npm ls -g` | `uv tool list` |
            """
        ),
        code(
            r"""
            shutil.rmtree(UNIT41_DIR / "uv-tools", ignore_errors=True)
            shell(
                "uv",
                "tool",
                "install",
                "--offline",
                "../wheelhouse/gst_calc-1.0.0-py3-none-any.whl",
                "--no-index",
                "--find-links",
                "../wheelhouse",
                cwd=projects_root,
            )
            shell("uv", "tool", "list")
            shell(str(UNIT41_DIR / "uv-tools-bin" / "gst"), "1000")
            shell(
                "uvx",
                "--offline",
                "--no-index",
                "--find-links",
                "wheelhouse",
                "--from",
                "gst-calc==2.0.0",
                "gst",
                "1000",
            )
            shell("uv", "tool", "uninstall", "gst-calc")
            """
        ),
        md(
            """
            **PEP 723 inline script metadata.** A single-file script can declare its own
            dependencies in a special comment block; `uv run script.py` reads it and runs the
            script in a cached environment that has exactly those packages. No project, no
            virtual environment to manage: ideal for one-off tools. `uv init --script` creates
            the block and `uv add --script` edits it.

            ```python
            # /// script
            # requires-python = ">=3.12"
            # dependencies = ["rupee-fmt>=2"]
            # ///
            ```
            """
        ),
        code(
            r"""
            scripts_root = fresh_dir("scripts")
            shell("uv", "init", "--script", "report.py", cwd=scripts_root)
            FIND_LINKS = ("--no-index", "--find-links", str(WHEELHOUSE))
            shell("uv", "add", "--script", "report.py", "rupee-fmt>=2", *FIND_LINKS, cwd=scripts_root)
            report_script = scripts_root / "report.py"
            report_script.write_text(
                report_script.read_text().replace(
                    'print("Hello from report.py!")',
                    "import importlib.metadata\n    from rupee_fmt import fmt\n\n"
                    '    print(fmt(1234567.5), "with rupee-fmt", importlib.metadata.version("rupee-fmt"))',
                )
            )
            show_file(report_script)
            shell("uv", "run", *FIND_LINKS, "report.py", cwd=scripts_root)
            """
        ),
        md(
            """
            **Workspaces** are uv's version of npm/pnpm workspaces: several packages in one
            repository share **one** `uv.lock` (so they agree on every version) and one
            environment. The root declares `[tool.uv.workspace] members`; a member depends on
            another with `[tool.uv.sources] name = { workspace = true }`, and both are installed
            editable. Here `uv init` is run *without* `--no-workspace` inside the root, so it
            adds each member automatically.
            """
        ),
        code(
            r'''
            monorepo = write_files(
                fresh_dir("monorepo"),
                {
                    "pyproject.toml": """
                [project]
                name = "monorepo"
                version = "0.1.0"
                requires-python = ">=3.15"

                [tool.uv.workspace]
                members = ["packages/*"]
            """
                },
            )
            UV_INIT_MEMBER = ("uv", "init", "--author-from", "none", "--vcs", "none", "--no-readme")
            shell(*UV_INIT_MEMBER, "--lib", "packages/pricing-core", cwd=monorepo)
            shell(*UV_INIT_MEMBER, "--package", "packages/billing-api", cwd=monorepo)
            shell("uv", "add", "--offline", "--package", "billing-api", "pricing-core", cwd=monorepo)
            show_file(monorepo / "packages" / "billing-api" / "pyproject.toml", after="dependencies")
            shell(
                "uv",
                "run",
                "--offline",
                "--package",
                "billing-api",
                "python",
                "-c",
                "import pricing_core; print(pricing_core.hello())",
                cwd=monorepo,
            )
            workspace_lock = tomllib.loads((monorepo / "uv.lock").read_text())
            print(f"one uv.lock for the workspace, members: {workspace_lock['manifest']['members']}")
            '''
        ),
        md(
            """
            **`uv export`** converts `uv.lock` into formats other tools understand:
            `requirements.txt` (for pip, Dependabot, older platforms), `pylock.toml` (the PEP 751
            standard lockfile, 4.1.6) or a CycloneDX SBOM (`cyclonedx1.5`, for security teams).
            """
        ),
        code(
            r"""
            shell("uv", "export", "--format", "requirements.txt", "--no-hashes", cwd=invoicing)
            shell(
                "uv",
                "export",
                "--format",
                "requirements.txt",
                "--no-dev",
                "--extra",
                "report",
                "--no-hashes",
                "--no-header",
                cwd=invoicing,
            )
            """
        ),
        md(
            """
            **`uv build`** is a build frontend (4.1.1): it builds an sdist into `dist/`, then a
            wheel from that sdist. `uv_build` projects are built by uv's built-in copy of the
            backend, with no extra download. 4.1.8 opens both archives.
            """
        ),
        code(
            r"""
            shell("uv", "build", "--offline", cwd=invoicing)
            print(sorted(path.name for path in (invoicing / "dist").iterdir()))
            """
        ),
        md(
            """
            **`uv publish`** uploads `dist/*` to an index (PyPI by default; `--index` or
            `--publish-url` for TestPyPI or a private index). The course never publishes, so
            this cell only prints the relevant options from `uv publish --help`. 4.1.8 shows the
            full release flow with TestPyPI and trusted publishing.
            """
        ),
        code(
            r"""
            shell(
                "uv",
                "publish",
                "--help",
                keep=r"^\s+(--index |--publish-url|--trusted-publishing|--check-url|--dry-run|\[FILES\])",
            )
            """
        ),
    ]


def _pyproject_cells() -> list[NotebookNode]:
    """4.1.4 pyproject.toml anatomy."""
    return [
        md(
            """
            ### 4.1.4 `pyproject.toml` anatomy

            `pyproject.toml` is TOML (like `package.json` with comments and typed tables). Its
            tables come from different standards:

            | Table | Standard | Read by | npm analogue |
            | --- | --- | --- | --- |
            | `[build-system]` | PEP 518 / 517 | build frontends (pip, uv) | none (npm has no build step) |
            | `[project]` | PEP 621 | backends, which turn it into wheel `METADATA` | `name`, `version`, `dependencies`, `engines`, `license` |
            | `[project.scripts]` | PEP 621 (entry points) | installers, which generate launchers | `"bin"` |
            | `[project.optional-dependencies]` | PEP 621 | resolvers (`pkg[extra]`) | `optionalDependencies` / `peerDependencies`, sort of |
            | `[project.urls]` | PEP 621 | PyPI's sidebar | `homepage`, `repository` |
            | `[dependency-groups]` | PEP 735 | uv, pip ≥ 25.1 (`--group`) | `devDependencies` |
            | `[tool.<name>]` | each tool's own docs | uv, ruff, mypy, pytest, … | `"eslintConfig"`, `"jest"` keys |

            Here is a complete, annotated example for a CLI called `invoice-kit`:
            """
        ),
        code(
            r'''
            ANATOMY_PYPROJECT = """
            [build-system]                                  # PEP 518: how to build this project
            requires = ["uv_build>=0.13,<0.14"]             # installed into the isolated build env
            build-backend = "uv_build"                      # module whose PEP 517 hooks build it

            [project]                                       # PEP 621: the package metadata
            name = "invoice-kit"                            # PyPI name (normalized: invoice_kit)
            version = "1.4.0"                               # PEP 440 version (or dynamic = ["version"])
            description = "GST invoices from the command line"
            readme = "README.md"                            # long description shown on PyPI
            requires-python = ">=3.12"                      # resolvers skip this release on older Pythons
            license = "MIT"                                 # SPDX expression (PEP 639)
            authors = [{ name = "Course Author" }]
            classifiers = ["Programming Language :: Python :: 3", "Typing :: Typed"]
            dependencies = [                                # runtime requirements -> Requires-Dist
                "gst-calc>=1.0,<2",
                "win-colors>=1.0; sys_platform == 'win32'", # environment marker: Windows only
            ]

            [project.optional-dependencies]                 # extras: pip install "invoice-kit[report]"
            report = ["table-print>=0.1"]

            [project.scripts]                               # console scripts: command = "module:function"
            invoice-kit = "invoice_kit.cli:main"

            [project.urls]
            Homepage = "https://example.com/invoice-kit"

            [dependency-groups]                             # PEP 735: local-only groups, never published
            dev = ["rupee-fmt>=1.1", { include-group = "lint" }]
            lint = ["table-print"]

            [tool.uv]                                       # uv settings for this project
            no-index = true
            find-links = ["../wheelhouse"]

            [tool.ruff]                                     # linter / formatter
            line-length = 100
            target-version = "py312"

            [tool.ruff.lint]
            select = ["E", "F", "I", "UP", "B"]

            [tool.mypy]                                     # type checker (Unit 4.2)
            strict = true
            python_version = "3.12"

            [tool.pytest.ini_options]                       # test runner (Unit 4.3)
            testpaths = ["tests"]
            addopts = "-ra --strict-markers"
            """
            anatomy = tomllib.loads(ANATOMY_PYPROJECT)
            for table, content in anatomy.items():
                keys = list(content)
                print(f"[{table}] -> {keys}")
            '''
        ),
        md(
            """
            `tomllib` (standard library since 3.11) parses TOML into dicts; note how `[tool.uv]`
            and `[tool.ruff]` become nested keys of `tool`. The `[tool.*]` tables configure the
            tools:
            """
        ),
        code(
            r"""
            for tool_name, settings in anatomy["tool"].items():
                print(f"tool.{tool_name}: {settings}")
            print(f"{anatomy['dependency-groups']=}")
            """
        ),
        md(
            """
            **Where each table ends up.** Build the project and read the wheel's `METADATA`:
            `[project]` becomes `Name`, `Version`, `Requires-Python`, `License-Expression`,
            `Requires-Dist`; each extra becomes `Provides-Extra` plus `Requires-Dist: …; extra ==
            "report"`; `[project.scripts]` becomes `entry_points.txt`. `[dependency-groups]` and
            `[tool.*]` are **not** in the wheel: they only matter in the source tree.
            """
        ),
        code(
            r"""
            anatomy_root = write_files(
                fresh_dir("projects/invoice-kit"),
                {
                    "pyproject.toml": ANATOMY_PYPROJECT.replace("../wheelhouse", "../../wheelhouse"),
                    "README.md": "# invoice-kit\n\nGST invoices from the command line.\n",
                    "src/invoice_kit/__init__.py": "",
                    "src/invoice_kit/cli.py": "def main() -> None:\n    print('invoice-kit')\n",
                    "src/invoice_kit/py.typed": "",
                },
            )
            shell("uv", "build", "--offline", "--wheel", cwd=anatomy_root, keep="Successfully")
            kit_wheel = next((anatomy_root / "dist").glob("*.whl"))
            with zipfile.ZipFile(kit_wheel) as wheel:
                metadata_text = wheel.read("invoice_kit-1.4.0.dist-info/METADATA").decode()
                entry_points = wheel.read("invoice_kit-1.4.0.dist-info/entry_points.txt").decode()
            print(metadata_text.split("\n\n")[0])  # headers only (the README body follows)
            print("--- entry_points.txt ---\n" + entry_points.strip())
            print(f"{'dependency-groups' in metadata_text=}  {'ruff' in metadata_text=}")
            """
        ),
        md(
            """
            The course's own `pyproject.toml` is a *virtual* project: `[project]` without
            `[build-system]`, a `dev` group and tool tables. Reading it is fine; no cell in this
            notebook writes to it.
            """
        ),
        code(
            r"""
            course = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
            print(f"{course['project']['name']=}  {course['project']['requires-python']=}")
            print(f"{'build-system' in course=}  (virtual project: not built or installed)")
            print(f"{sorted(course['dependency-groups'])=}  {sorted(course['tool'])=}")
            """
        ),
    ]


def _specifier_cells() -> list[NotebookNode]:
    """4.1.5 Version specifiers (PEP 440)."""
    return [
        md(
            """
            ### 4.1.5 Version specifiers (PEP 440)

            Python versions follow **PEP 440**, not SemVer. A version looks like
            `[N!]N(.N)*[{a|b|rc}N][.postN][.devN]`, and ordering is defined by the standard:
            `1.0.dev1 < 1.0a1 < 1.0b1 < 1.0rc1 < 1.0 < 1.0.post1`. A requirement combines a
            name, optional extras, specifiers and an optional environment marker:

            ```text
            gst-calc[report] >=1.0,<2 ; python_version >= "3.12"
            ^name    ^extras ^specifiers ^marker
            ```

            | Operator | Meaning | npm equivalent |
            | --- | --- | --- |
            | `==1.4.2` | Exactly this version (`==1.4.*` = any 1.4.x) | `1.4.2`, `1.4.x` |
            | `>=1.4` | This version or newer | `>=1.4` |
            | `~=1.4` | **Compatible release**: `>=1.4, ==1.*` | `^1.4` (for ≥ 1.0) |
            | `~=1.4.2` | `>=1.4.2, ==1.4.*` | `~1.4.2` |
            | `!=1.5.0` | Anything except this version | `!=` does not exist in npm (`<1.5.0 \\|\\| >1.5.0`) |
            | `<2`, `>`, `<=` | Upper bounds and exclusive comparisons | same |
            | `===` | Arbitrary string equality (rare, legacy) | none |

            `packaging.specifiers.SpecifierSet` implements these rules exactly as pip and uv do.
            Each operator gets its own demo below.
            """
        ),
        code(
            r'''
            from packaging.specifiers import SpecifierSet
            from packaging.version import Version

            CANDIDATES = ["1.3.9", "1.4.0", "1.4.2", "1.4.9", "1.5.0", "1.9.1", "2.0.0", "2.1.0rc1"]


            def matching(specifier: str) -> list[str]:
                """Which candidate versions satisfy the specifier (pre-releases excluded by default)?"""
                return [str(version) for version in SpecifierSet(specifier).filter(map(Version, CANDIDATES))]


            print(f"{matching('==1.4.2')=}")
            print(f"{matching('==1.4.*')=}  (wildcard: any 1.4.x)")
            '''
        ),
        md(
            "`>=` is a lower bound only: it happily accepts the next major version, breaking changes included."
        ),
        code(
            r"""
            print(f"{matching('>=1.4')=}")
            print(f"{matching('>=1.4,<2')=}  (the usual way to say: 1.4 or newer, but not 2.x)")
            """
        ),
        md(
            """
            `~=` (*compatible release*) drops the last component you write and pins the rest,
            so the number of components you write decides how much can float:
            """
        ),
        code(
            r"""
            print(f"{matching('~=1.4')=}    (>=1.4, ==1.*)")
            print(f"{matching('~=1.4.2')=}  (>=1.4.2, ==1.4.*)")
            print(f"{SpecifierSet('~=1.4.2') == SpecifierSet('>=1.4.2,==1.4.*')=}  (different spelling)")
            print(f"{Version('1.4.2') in SpecifierSet('~=1.4.2')=}")
            """
        ),
        md("`!=` excludes a known-bad release while still accepting everything around it:"),
        code(
            r"""
            print(f"{matching('>=1.4,!=1.5.0,<2')=}")
            print(f"{matching('!=1.4.*')=}  (exclude a whole minor series)")
            """
        ),
        md(
            """
            **Pre-releases** (`a`, `b`, `rc`, `.dev`) are excluded unless a specifier names one
            or you opt in. This keeps `2.1.0rc1` out of production by accident. The same rule
            applies in uv: `uv pip compile` picks 2.0.0 unless you pass `--prerelease allow`.
            """
        ),
        code(
            r"""
            print(f"{matching('>=2')=}")
            print(
                f"{[str(v) for v in SpecifierSet('>=2', prereleases=True).filter(map(Version, CANDIDATES))]=}"
            )
            print(f"{matching('>=2.1.0rc1')=}  (naming a pre-release opts in)")
            ordering = ["1.0", "1.0.post1", "1.0rc1", "1.0a1", "1.0.dev1", "1.0b2"]
            print(f"{sorted(ordering, key=Version)=}")
            requirements_in = UNIT41_DIR / "requirements.in"
            requirements_in.write_text("rupee-fmt>=2\n")
            for extra_flags in ([], ["--prerelease", "allow"]):
                shell(
                    "uv",
                    "pip",
                    "compile",
                    "requirements.in",
                    "--no-header",
                    "--no-annotate",
                    "--no-index",
                    "--find-links",
                    "wheelhouse",
                    "--quiet",
                    *extra_flags,
                )
            """
        ),
        md(
            """
            **Environment markers** (PEP 508) make a requirement conditional on where it is
            installed: `sys_platform`, `platform_machine`, `python_version`,
            `implementation_name`, `os_name` and more. `gst-calc` uses one to pull in
            `win-colors` on Windows only. A marker is evaluated against an environment; the
            default is the running interpreter.
            """
        ),
        code(
            r"""
            from packaging.markers import Marker, default_environment

            windows_only = Marker("sys_platform == 'win32'")
            modern_cpython = Marker("python_version >= '3.13' and implementation_name == 'cpython'")
            here = default_environment()
            print(f"{here['sys_platform']=}  {here['python_version']=}  {here['platform_machine']=}")
            print(f"{windows_only.evaluate()=}  {windows_only.evaluate({'sys_platform': 'win32'})=}")
            print(f"{modern_cpython.evaluate()=}")
            old_python = Marker('python_version < "3.11"')
            print(f"{old_python.evaluate()=}  (e.g. a tomli backport)")
            """
        ),
        md(
            """
            **Extras** name optional feature sets. `pkg[extra]` adds the extra's requirements;
            inside the published metadata they appear as markers on `extra`. `Requirement`
            parses a whole PEP 508 line:
            """
        ),
        code(
            r"""
            from packaging.requirements import Requirement

            requirement = Requirement('gst-calc[report]>=1.0,<2; python_version >= "3.12"')
            print(f"{requirement.name=}  {requirement.extras=}")
            print(f"{str(requirement.specifier)=}  {str(requirement.marker)=}")
            published = Requirement('table-print>=0.1; extra == "report"')
            print(
                f"{published.marker.evaluate({'extra': 'report'})=}\n"
                f"{published.marker.evaluate({'extra': ''})=}"
            )
            """
        ),
        md(
            "And for real: installing `gst-calc[report]` adds `table-print`, the plain name does not."
        ),
        code(
            r"""
            for requirement_text in ("gst-calc==1.0.0", "gst-calc[report]==1.0.0"):
                pip("install", "--dry-run", "--ignore-installed", requirement_text, keep="Would install")
            """
        ),
        *predict_cells(
            """
            from packaging.specifiers import SpecifierSet

            spec = SpecifierSet("~=2.2")
            print([v for v in ["2.1", "2.2", "2.9", "3.0", "2.10"] if v in spec])
            """,
            """
            `['2.2', '2.9', '2.10']`. `~=2.2` means `>=2.2, ==2.*`, so 2.1 is too old and 3.0
            is a new major series. Versions compare component by component as numbers, so
            `2.10` is **newer** than `2.9` (unlike string comparison).
            """,
            """
            from packaging.specifiers import SpecifierSet

            spec = SpecifierSet("~=2.2")
            print([v for v in ["2.1", "2.2", "2.9", "3.0", "2.10"] if v in spec])
            """,
        ),
    ]


def _lockfile_cells() -> list[NotebookNode]:
    """4.1.6 Lockfiles."""
    return [
        md(
            """
            ### 4.1.6 Lockfiles

            `pyproject.toml` says what you *accept* (`gst-calc~=1.0`); a lockfile records what
            you *got*: every package, transitive ones included, at an exact version, with file
            hashes and where it came from. Installing from the lock gives the same environment
            on every machine.

            **`uv.lock`** is uv's own format: TOML, **universal** (resolved once for every
            platform and Python version the project supports; markers record which packages
            apply where) and meant to be committed. Never edit it by hand.
            """
        ),
        code(
            r"""
            lock = tomllib.loads((invoicing / "uv.lock").read_text())
            print(f"{lock['version']=}  {lock['requires-python']=}")
            for package in lock["package"]:
                source = package["source"]
                wheels = len(package.get("wheels", []))
                dependencies = [
                    dependency["name"] + (f" ; {dependency['marker']}" if "marker" in dependency else "")
                    for dependency in package.get("dependencies", [])
                ]
                print(
                    f"{package['name']:<12} {package['version']:<7} {tidy(str(source)):<34} "
                    f"wheels={wheels} deps={dependencies}"
                )
            """
        ),
        md(
            """
            Note `win-colors`: it is locked even on Linux, with the marker
            `sys_platform == 'win32'` on the edge from `gst-calc`, so a Windows teammate gets the
            same lock. `uv sync` only installs what applies to the current machine:
            """
        ),
        code(
            r"""
            installed = run_tool("uv", "pip", "list", "--format", "freeze", cwd=invoicing)[1]
            print(installed)
            print(f"{'win-colors' in installed=}  (locked for Windows, not installed here)")
            """
        ),
        md(
            """
            **`pylock.toml` (PEP 751, accepted 2025)** is the *standard* lockfile format that
            any installer can read: a flat list of packages, each with its exact files and
            hashes. uv exports it from `uv.lock`; pip ≥ 25.1 can write one with `pip lock`
            (experimental). Think of `uv.lock` as the rich working format and `pylock.toml` as
            the interchange format for other tools and auditors.
            """
        ),
        code(
            r"""
            shell("uv", "export", "--format", "pylock.toml", "-o", "pylock.toml", "--quiet", cwd=invoicing)
            pylock = tomllib.loads((invoicing / "pylock.toml").read_text())
            print(f"{pylock['lock-version']=}  {pylock['created-by']=}")
            for package in pylock["packages"]:
                files = [*package.get("wheels", []), *([package["sdist"]] if "sdist" in package else [])]
                hashes = [next(iter(file["hashes"].values()))[:12] + "…" for file in files]
                print(
                    f"{package['name']:<12} {package.get('version', '(editable)'):<10} "
                    f"marker={package.get('marker', '-'):<24} sha256={hashes}"
                )
            """
        ),
        md(
            """
            **Pinning strategy: applications vs libraries.** The same project can be both, so
            decide per artefact:

            | | Application (service, CLI you deploy) | Library (published for others to import) |
            | --- | --- | --- |
            | `dependencies` | Reasonable ranges (`>=1.4,<2`) | **Wide** ranges: lower bound you tested, upper bound only for known breaks |
            | Lockfile | Committed; deploy exactly the lock (`uv sync --locked`) | Committed for CI and contributors, but **users never see it** |
            | Upgrades | Deliberate: `uv lock --upgrade-package`, Dependabot/Renovate PRs | Test against the newest *and* the oldest allowed versions |
            | Exact pins (`==`) in `pyproject.toml` | Acceptable | Never: they cause conflicts in every app that uses you |

            uv can resolve to the **lowest** versions your specifiers allow, which is how a
            library tests its lower bounds:
            """
        ),
        code(
            r"""
            requirements_in.write_text("gst-calc>=1.0,<2\n")
            for strategy in ("highest", "lowest"):
                print(f"--resolution {strategy}:")
                shell(
                    "uv",
                    "pip",
                    "compile",
                    "requirements.in",
                    "--resolution",
                    strategy,
                    "--no-header",
                    "--no-annotate",
                    "--no-index",
                    "--find-links",
                    "wheelhouse",
                    "--quiet",
                )
            """
        ),
    ]


def _layout_cells() -> list[NotebookNode]:
    """4.1.7 Project layouts."""
    return [
        md(
            """
            ### 4.1.7 Project layouts

            | Flat layout | `src/` layout |
            | --- | --- |
            | `myproject/mypkg/__init__.py` | `myproject/src/mypkg/__init__.py` |
            | `import mypkg` works from the project root **without installing**, because the current folder is on `sys.path` | `import mypkg` works **only** after installing (usually editable) |
            | Tests may pass against the working copy while the built wheel is broken (missing files, wrong package list) | Tests run against the installed package, like users |

            uv (`--lib`, `--package`), Hatch, PDM and the Python Packaging User Guide default to
            `src/`. The demo runs `python -c "import pricing"` from the root of each layout,
            without installing anything:
            """
        ),
        code(
            r"""
            PRICING_MODULE = "def price(amount):\n    return amount\n"
            flat_root = write_files(fresh_dir("layouts/flat"), {"pricing/__init__.py": PRICING_MODULE})
            src_root = write_files(fresh_dir("layouts/src"), {"src/pricing/__init__.py": PRICING_MODULE})
            IMPORT_CHECK = "import pricing; print('imported from', pricing.__file__)"
            print("flat:", run_tool("python", "-c", IMPORT_CHECK, cwd=flat_root)[1])
            print("src: ", run_tool("python", "-c", IMPORT_CHECK, cwd=src_root)[1].splitlines()[-1])
            """
        ),
        md(
            """
            **Editable-install mechanics.** `uv sync` installs the project itself in editable
            mode (like `pip install -e .`). What actually lands in `site-packages` is tiny: a
            `.dist-info/` folder (metadata, so `importlib.metadata` finds the project) with a
            `direct_url.json` saying *editable*, and a `.pth` file that adds `src/` to
            `sys.path`. setuptools sometimes uses an import-hook finder instead of a plain path
            (`__editable___*_finder.py`), which can hide new top-level modules; a `.pth` path
            does not.
            """
        ),
        code(
            r"""
            invoicing_site = next((invoicing / ".venv").glob("lib/python3*/site-packages"))
            for path in sorted(invoicing_site.glob("*invoicing*")):
                print(path.name + ("/" if path.is_dir() else ""))
            pth_text = next(invoicing_site.glob("*invoicing*.pth")).read_text().strip()
            print(f"pth -> {tidy(pth_text)}")
            dist_info = next(invoicing_site.glob("invoicing-*.dist-info"))
            print(f"direct_url.json -> {tidy((dist_info / 'direct_url.json').read_text())}")
            """
        ),
        md(
            """
            **Under the hood: hardlinks from the cache.** The other packages in that
            environment were not copied: each file is a hardlink into uv's cache, so its link
            count is above 1 (the same inode appears in two places).
            """
        ),
        code(
            r"""
            rupee_init = next(invoicing_site.glob("rupee_fmt/__init__.py"))
            status = rupee_init.stat()
            print(f"rupee_fmt/__init__.py: inode {status.st_ino}, {status.st_nlink} links")
            linked_in_cache = [
                path
                for path in (UNIT41_DIR / "uv-cache").rglob("__init__.py")
                if path.stat().st_ino == status.st_ino
            ]
            print(f"same inode in the uv cache: {[tidy(str(path))[:60] + '…' for path in linked_in_cache[:1]]}")
            """
        ),
        md(
            """
            **`__version__` via `importlib.metadata`.** Keep the version in exactly one place,
            `pyproject.toml`, and read it at run time from the installed metadata. A bumped
            version shows up after the next `uv sync` (which re-writes the metadata):

            ```python
            from importlib.metadata import version

            __version__ = version("invoicing")
            ```
            """
        ),
        code(
            r"""
            init_file = invoicing / "src" / "invoicing" / "__init__.py"
            init_file.write_text(
                'from importlib.metadata import version\n\n__version__ = version("invoicing")\n'
                + init_file.read_text()
            )
            VERSION_CHECK = ("python", "-c", "import invoicing; print(invoicing.__version__)")
            shell("uv", "run", *VERSION_CHECK, cwd=invoicing)
            pyproject_path.write_text(
                pyproject_path.read_text().replace('version = "0.1.0"', 'version = "0.2.0"')
            )
            shell("uv", "run", *VERSION_CHECK, cwd=invoicing)  # re-syncs: metadata rewritten
            print(
                f"in this kernel: {importlib.metadata.version('mypy')=}  "
                f"{importlib.metadata.version('pydantic')=}"
            )
            """
        ),
    ]


def _publishing_cells() -> list[NotebookNode]:
    """4.1.8 Building and publishing."""
    return [
        md(
            """
            ### 4.1.8 Building and publishing

            **Wheel contents.** A wheel is a zip file. Everything outside the `.dist-info/`
            folder is copied into `site-packages` as is; the `.dist-info/` folder holds the
            metadata installers and `importlib.metadata` read:

            | File | Content |
            | --- | --- |
            | `METADATA` | Core metadata (name, version, `Requires-Dist`, `Requires-Python`, README) |
            | `WHEEL` | Wheel format version, generator, `Root-Is-Purelib`, the tags |
            | `RECORD` | Every file with its SHA-256 and size: the installer checks them and uses it to uninstall |
            | `entry_points.txt` | Console scripts and plugin entry points |
            | `licenses/` | License files (PEP 639) |

            The demo opens the `invoicing` wheel and sdist built in 4.1.3.
            """
        ),
        code(
            r"""
            shutil.rmtree(invoicing / "dist", ignore_errors=True)
            shell("uv", "build", "--offline", cwd=invoicing, keep="Successfully")
            invoicing_wheel = next((invoicing / "dist").glob("*.whl"))
            invoicing_sdist = next((invoicing / "dist").glob("*.tar.gz"))
            with zipfile.ZipFile(invoicing_wheel) as wheel:
                print(f"{invoicing_wheel.name}:")
                for info in wheel.infolist():
                    print(f"  {info.filename:<44} {info.file_size:>6} bytes")
                dist_info_name = next(name.split("/")[0] for name in wheel.namelist() if ".dist-info/" in name)
                print(wheel.read(f"{dist_info_name}/WHEEL").decode())
            """
        ),
        md(
            """
            `METADATA` uses e-mail header syntax, so the standard library's `email.parser` reads
            it, which is exactly what `importlib.metadata` does:
            """
        ),
        code(
            r"""
            with zipfile.ZipFile(invoicing_wheel) as wheel:
                headers = email.parser.Parser().parsestr(wheel.read(f"{dist_info_name}/METADATA").decode())
                entry_points = wheel.read(f"{dist_info_name}/entry_points.txt").decode()
            for key in ("Metadata-Version", "Name", "Version", "Requires-Python"):
                print(f"{key}: {headers[key]}")
            print(f"Requires-Dist: {headers.get_all('Requires-Dist')}")
            print(f"Provides-Extra: {headers.get_all('Provides-Extra')}")
            print(f"entry_points.txt: {entry_points.split()}")
            """
        ),
        md(
            """
            **Under the hood: verifying `RECORD`.** Each line is `path,sha256=<urlsafe base64
            digest without padding>,size`. Recomputing every digest is what an installer does to
            detect a corrupted or tampered wheel:
            """
        ),
        code(
            r'''
            def record_digest(data: bytes) -> str:
                """The RECORD spelling of a SHA-256 digest."""
                return "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()


            with zipfile.ZipFile(invoicing_wheel) as wheel:
                record_lines = wheel.read(f"{dist_info_name}/RECORD").decode().splitlines()
                for line in record_lines:
                    path, digest, size = line.rsplit(",", 2)
                    if digest:  # RECORD cannot contain its own hash
                        actual = record_digest(wheel.read(path))
                        print(f"{path:<44} {'OK' if actual == digest else 'MISMATCH'}  {digest[:20]}…")
                    else:
                        print(f"{path:<44} (no hash: the RECORD file itself)")
            '''
        ),
        md(
            """
            The **sdist** is a `.tar.gz` of the source tree plus a generated `PKG-INFO` (the same
            metadata). It contains `pyproject.toml`, so anyone can rebuild the wheel; uv built
            the wheel above from this very archive. `uv_build` stores a normalized copy of
            `pyproject.toml` (comments dropped, lists on one line) and keeps your original as
            `pyproject.toml.orig`.
            """
        ),
        code(
            r"""
            with tarfile.open(invoicing_sdist) as sdist:
                for member in sdist.getmembers():
                    if member.isfile():
                        print(f"  {member.name:<48} {member.size:>6} bytes")
                pkg_info = (
                    sdist.extractfile(f"{invoicing_sdist.name.removesuffix('.tar.gz')}/PKG-INFO")
                    .read()
                    .decode()
                )
            print(pkg_info.split("\n\n")[0])
            """
        ),
        md(
            """
            **TestPyPI** (test.pypi.org) is a separate, throwaway copy of PyPI for rehearsing a
            release. Declare it as an *explicit* index (never used for resolution unless a
            package is pinned to it) with a publish URL, then `uv publish --index testpypi`, and
            install from it to check the release works. The course does not run these commands.

            ```toml
            [[tool.uv.index]]
            name = "testpypi"
            url = "https://test.pypi.org/simple/"
            publish-url = "https://test.pypi.org/legacy/"
            explicit = true
            ```

            ```bash
            uv build
            uv publish --index testpypi            # token or trusted publishing
            uv run --with invoicing --index https://test.pypi.org/simple/ --no-project -- invoicing
            ```

            **Trusted publishing (OIDC).** Instead of storing a long-lived PyPI API token as a CI
            secret, you tell PyPI once: "releases of `invoicing` may come from GitHub repository
            *owner/repo*, workflow `release.yml`, environment `pypi`". At release time the CI job
            asks GitHub for a short-lived **OIDC identity token**, PyPI checks its claims against
            that configuration and returns a 15-minute upload token. Nothing secret is stored,
            and a leaked token expires almost at once. npm now offers the same thing (trusted
            publishing with provenance).

            ```mermaid
            sequenceDiagram
                participant CI as GitHub Actions job
                participant GH as GitHub OIDC provider
                participant PyPI
                CI->>GH: request ID token (audience: pypi)
                GH-->>CI: signed JWT (repo, workflow, environment)
                CI->>PyPI: exchange JWT for an upload token
                PyPI-->>CI: short-lived API token (if claims match the trusted publisher)
                CI->>PyPI: uv publish dist/*
            ```

            <details><summary>ASCII fallback</summary>

            ```text
            CI job --(1) ask for ID token--> GitHub OIDC
            CI job <-(2) signed JWT: repo, workflow, env-- GitHub OIDC
            CI job --(3) JWT--> PyPI checks the trusted-publisher config
            CI job <-(4) 15-minute upload token-- PyPI
            CI job --(5) uv publish dist/*--> PyPI
            ```

            </details>

            ```yaml
            # .github/workflows/release.yml (shown, not used by the course)
            on:
              release:
                types: [published]
            jobs:
              publish:
                runs-on: ubuntu-latest
                environment: pypi
                permissions:
                  id-token: write        # allows the job to request the OIDC token
                steps:
                  - uses: actions/checkout@v5
                  - uses: astral-sh/setup-uv@v7
                  - run: uv build
                  - run: uv publish      # detects the OIDC environment: --trusted-publishing automatic
            ```

            **SemVer vs CalVer.**

            | Scheme | Format | Says | Used by |
            | --- | --- | --- | --- |
            | SemVer | `MAJOR.MINOR.PATCH` | Compatibility: major = breaking, minor = features, patch = fixes | most libraries, mypy, pydantic, uv (0.x: anything may break) |
            | CalVer | `YY.MINOR` or `YYYY.MM.PATCH` | *When* it was released; no compatibility promise | pip, Black, Ubuntu, `certifi` |

            Both are valid PEP 440 versions, so specifiers and ordering work the same. A SemVer
            bump helper and the versions of tools in this environment:
            """
        ),
        code(
            r'''
            def bump(version: str, part: str) -> str:
                """Next SemVer version: part is "major", "minor" or "patch"; pre-release parts are dropped."""
                major, minor, patch = Version(version).release[:3]
                match part:
                    case "major":
                        return f"{major + 1}.0.0"
                    case "minor":
                        return f"{major}.{minor + 1}.0"
                    case "patch":
                        return f"{major}.{minor}.{patch + 1}"
                raise ValueError(f"unknown part {part!r}")


            print(f"{bump('1.4.2', 'patch')=}  {bump('1.4.2', 'minor')=}  {bump('1.4.2', 'major')=}")
            print(f"{Version('2026.11.0') > Version('2026.2.3')=}  (CalVer compares numerically too)")
            for distribution in ("pip", "mypy", "pydantic", "certifi"):
                try:
                    print(f"  {distribution:<9} {importlib.metadata.version(distribution)}")
                except importlib.metadata.PackageNotFoundError:
                    print(f"  {distribution:<9} not installed")
            '''
        ),
        md(
            """
            **Changelogs.** Keep a human-written `CHANGELOG.md` in the
            [Keep a Changelog](https://keepachangelog.com) format: newest release first, an
            `Unreleased` section at the top, entries grouped under *Added*, *Changed*,
            *Deprecated*, *Removed*, *Fixed*, *Security*. With Conventional Commit messages
            (`feat:`, `fix:`, `feat!:`), tools such as `git-cliff`, `commitizen` or
            `python-semantic-release` can draft the entries and even pick the next SemVer
            version. The idea in a few lines:
            """
        ),
        code(
            r'''
            def draft_changelog(current_version: str, commit_subjects: list[str]) -> str:
                """Group Conventional Commit subjects into a Keep-a-Changelog section and pick the bump."""
                sections: dict[str, list[str]] = {"Added": [], "Fixed": [], "Changed": []}
                part = "patch"
                for subject in commit_subjects:
                    kind, _, description = subject.partition(": ")
                    if kind.endswith("!"):
                        sections["Changed"].append(f"**Breaking:** {description}")
                        part = "major"
                    elif kind.startswith("feat"):
                        sections["Added"].append(description)
                        part = "minor" if part == "patch" else part
                    elif kind.startswith("fix"):
                        sections["Fixed"].append(description)
                lines = [f"## [{bump(current_version, part)}]"]
                for heading, entries in sections.items():
                    lines += [f"### {heading}", *(f"- {entry}" for entry in entries)] if entries else []
                return "\n".join(lines)


            print(
                draft_changelog(
                    "1.4.2",
                    [
                        "feat(cli): add --currency option",
                        "fix: round GST half up",
                        "docs: fix typo",
                        "feat!: drop Python 3.11",
                    ],
                )
            )
            '''
        ),
    ]


def _supply_chain_cells() -> list[NotebookNode]:
    """4.1.9 Supply-chain hygiene."""
    return [
        md(
            """
            ### 4.1.9 Supply-chain hygiene

            Every dependency is code you run with your permissions. The main risks and the tool
            for each:

            | Risk | Defence |
            | --- | --- |
            | A dependency has a published vulnerability | `pip-audit` (or `uv` + Dependabot/Renovate) in CI |
            | You install a look-alike name (`requets`) | Review new dependencies; check name, author, download history |
            | A file is swapped in transit or on a mirror | Hash checking (lockfiles, `--require-hashes`) |
            | `pyproject.toml` drifts from the code (missing or unused dependencies) | `deptry` |
            | A license you cannot ship (copyleft in a closed product) | Read `License-Expression` metadata; license checkers |
            | Building an sdist runs arbitrary code | Prefer wheels (`--only-binary :all:`, `uv … --no-build`) |

            **`pip-audit`** checks installed packages or a requirements file against the Python
            Packaging Advisory Database (via PyPI or OSV). It needs the network, so the cell
            checks first. The requirements file pins two deliberately old releases. The
            findings change over time as advisories are published.
            """
        ),
        code(
            r"""
            audit_file = UNIT41_DIR / "audit-requirements.txt"
            audit_file.write_text("requests==2.19.0\njinja2==2.10\n")
            if not network_available():
                print("SKIP: no network connection to pypi.org; pip-audit needs the advisory database")
            else:
                exit_code, audit_output = run_tool(
                    "pip-audit",
                    "-r",
                    str(audit_file),
                    "--no-deps",
                    "--disable-pip",
                    "--progress-spinner",
                    "off",
                    "--desc",
                    "off",
                )
                lines = audit_output.splitlines()
                print(next((line for line in lines if line.startswith("Found")), "no summary line"))
                table = [line for line in lines if re.match(r"(Name |---|requests |jinja2 )", line)]
                print(*list(dict.fromkeys(table))[:8], "...", sep="\n")
                print(f"exit code {exit_code} (1 = vulnerabilities found)")
            """
        ),
        md(
            """
            **Typosquatting.** Attackers publish packages whose names are one keystroke away
            from popular ones (`requets`, `python-dateutils`, `beautifulsoup`, `colourama` all
            happened on PyPI). A quick defence when reviewing a new dependency is to compare it
            with well-known names; `difflib` finds near misses:
            """
        ),
        code(
            r'''
            import difflib

            POPULAR = [
                "requests",
                "python-dateutil",
                "beautifulsoup4",
                "colorama",
                "numpy",
                "pandas",
                "urllib3",
                "setuptools",
                "cryptography",
                "pyyaml",
                "django",
                "flask",
            ]


            def looks_like_typosquat(name: str) -> str | None:
                """The popular package this name is suspiciously close to, or None."""
                if name in POPULAR:
                    return None
                close = difflib.get_close_matches(name, POPULAR, n=1, cutoff=0.85)
                return close[0] if close else None


            for candidate in ["requets", "python-dateutils", "beautifulsoup", "colourama", "pydantic", "numpy"]:
                print(f"{candidate:<18} -> {looks_like_typosquat(candidate)}")
            '''
        ),
        md(
            """
            **Hash checking.** With `--require-hashes`, pip refuses any file whose SHA-256 is not
            listed, so a swapped file on a mirror or a compromised index cannot slip in. uv
            does the same with the hashes in `uv.lock`. `pip hash` prints the line to paste.
            Below, the first install uses a wrong hash and is refused; the second uses the real
            one.
            """
        ),
        code(
            r"""
            wheel_path = WHEELHOUSE / "table_print-0.1.0-py3-none-any.whl"
            pip("hash", str(wheel_path))
            real_hash = hashlib.sha256(wheel_path.read_bytes()).hexdigest()
            for label, digest in [("tampered", "0" * 64), ("genuine", real_hash)]:
                (UNIT41_DIR / "hashed.txt").write_text(f"table-print==0.1.0 --hash=sha256:{digest}\n")
                print(f"--- {label} hash ---")
                pip(
                    "install",
                    "--require-hashes",
                    "--force-reinstall",
                    "-r",
                    "hashed.txt",
                    keep=r"Successfully|ERROR|Expected|Got",
                )
            """
        ),
        md(
            """
            **`deptry`** compares the imports in your code with the dependencies you declare:
            `DEP001` an import that is not declared (works today only because something else
            pulled it in), `DEP002` a declared dependency nobody imports, `DEP003` a transitive
            dependency used directly, `DEP004` a dev dependency used in production code. First
            the idea in a few lines of `ast` (Unit 3.2), offline:
            """
        ),
        code(
            r'''
            import ast


            def check_dependencies(source: str, declared: list[str]) -> dict[str, list[str]]:
                """Mini deptry: top-level imports vs declared distributions (module = name with _)."""
                imported = {
                    alias.name.split(".")[0] if isinstance(node, ast.Import) else node.module.split(".")[0]
                    for node in ast.walk(ast.parse(source))
                    if isinstance(node, (ast.Import, ast.ImportFrom)) and getattr(node, "level", 0) == 0
                    for alias in (node.names if isinstance(node, ast.Import) else [node.names[0]])
                }
                third_party = imported - set(sys.stdlib_module_names)
                declared_modules = {name.replace("-", "_").lower(): name for name in declared}
                return {
                    "DEP001 missing": sorted(third_party - set(declared_modules)),
                    "DEP002 unused": sorted(declared_modules[m] for m in set(declared_modules) - third_party),
                }


            APP_SOURCE = "import json\nimport requests\nfrom rupee_fmt import fmt\n"
            print(check_dependencies(APP_SOURCE, ["rupee-fmt", "table-print"]))
            '''
        ),
        md(
            """
            The real `deptry` (a Rust-accelerated tool, not a course dependency) runs through
            `uvx`, which needs the network the first time to download it:
            """
        ),
        code(
            r'''
            deptry_root = write_files(
                fresh_dir("deptry-demo"),
                {
                    "pyproject.toml": """
                    [project]
                    name = "deptry-demo"
                    version = "0.1.0"
                    dependencies = ["rupee-fmt", "table-print"]
                """,
                    "app.py": APP_SOURCE,
                },
            )
            if not network_available():
                print("SKIP: no network connection; `uvx deptry .` needs to download deptry once")
            else:
                shell("uvx", "deptry", ".", "--no-ansi", cwd=deptry_root, keep=r"DEP\d|Found")
            '''
        ),
        md(
            """
            **Licenses.** Installed packages declare their license in metadata: the modern
            `License-Expression` field (an SPDX expression, PEP 639), the older free-text
            `License`, or `License ::` classifiers. A first look at what this course installs:
            """
        ),
        code(
            r'''
            def license_of(distribution_name: str) -> str:
                """Best available license information from installed metadata."""
                metadata = importlib.metadata.metadata(distribution_name)
                if expression := metadata.get("License-Expression"):
                    return f"{expression} (SPDX)"
                classifiers = [
                    c.split(" :: ")[-1]
                    for c in metadata.get_all("Classifier") or []
                    if c.startswith("License ::")
                ]
                if classifiers:
                    return f"{', '.join(classifiers)} (classifier)"
                return (metadata.get("License") or "unknown").splitlines()[0][:40]


            for name in ("mypy", "pyright", "pip-audit", "pydantic", "jupyterlab", "nbformat", "rich"):
                print(f"{name:<11} {license_of(name)}")
            '''
        ),
    ]


def _tool_comparison_cells() -> list[NotebookNode]:
    """4.1.10 Tool comparison."""
    return [
        md(
            """
            ### 4.1.10 Tool comparison

            | Python tool | What it does | Lockfile | Closest JS tool |
            | --- | --- | --- | --- |
            | **pip + venv** | Install into an environment you create; `requirements.txt` | none (freeze is a snapshot) | `npm install` without a lockfile |
            | **pip-tools** | `pip-compile` turns `requirements.in` into a fully pinned, hashed `requirements.txt`; `pip-sync` installs exactly it | the compiled `requirements.txt` | `npm shrinkwrap` |
            | **Poetry** | Projects, resolver, lockfile, build backend (`poetry-core`), publishing | `poetry.lock` | yarn (classic) |
            | **PDM** | Standards-first project manager (PEP 621, PEP 735), plugin system | `pdm.lock` | pnpm |
            | **Hatch** | Environments and test matrices, version bumping, the `hatchling` backend | none built in (uses others) | npm scripts + a build tool |
            | **Conda** (+ mamba, pixi) | Cross-language binary packages (CUDA, GDAL, R) from conda-forge, its own environments | `environment.yml` / `pixi.lock` | nvm + apt together |
            | **uv** | All of pip, pip-tools, virtualenv, pipx, pyenv (`uv python`), twine, workspaces; 10–100× faster | `uv.lock` (+ `pylock.toml` export) | pnpm + npx + nvm in one binary |

            Rules of thumb: new projects use **uv**; data science with native non-Python
            libraries often needs **conda/pixi**; existing Poetry or PDM projects can stay where
            they are (all of them read PEP 621 `[project]` today, so moving is cheap). Which of
            these are on this machine:
            """
        ),
        code(
            r"""
            TOOLS = {
                "pip": "pip",
                "pip-compile": "pip-tools",
                "poetry": "Poetry",
                "pdm": "PDM",
                "hatch": "Hatch",
                "conda": "Conda",
                "pixi": "pixi",
                "uv": "uv",
            }
            for command, product in TOOLS.items():
                found = executable(command)
                version = run_tool(command, "--version")[1].splitlines()[0] if found else "not installed"
                print(f"{product:<10} {command:<12} {tidy(version)}")
            """
        ),
        md(
            """
            **Check: the course project was never touched.** Every demo above ran in
            `notebooks/_scratch/unit41/`. The course's `pyproject.toml` and `uv.lock` still
            have the digests recorded by the unit's setup cell:
            """
        ),
        code(
            r"""
            for name in COURSE_FILES:
                unchanged = file_digest(REPO_ROOT / name) == COURSE_DIGESTS_AT_START[name]
                print(f"{name:<15} unchanged: {unchanged}")
            """
        ),
    ]


def _lab_cells() -> list[NotebookNode]:
    """Lab 4.1."""
    return [
        md(
            """
            ### Lab 4.1

            Four exercises. Complete each stub, then run its check cell. Until then the checks
            print FAIL; that is expected. The checks build and run your work with uv in
            `notebooks/_scratch/unit41/lab/`, offline, against the local wheelhouse.

            #### Exercise 1 — annotate every line of a `pyproject.toml`

            Return `PLAIN_PYPROJECT` (below) with a comment on **every** non-blank line,
            explaining what the line does. A comment is `# ` followed by at least three words,
            either at the end of the line or on its own line directly above it. The TOML must
            still parse to exactly the same data.
            """
        ),
        code(
            r'''
            PLAIN_PYPROJECT = """
            [build-system]
            requires = ["uv_build>=0.13,<0.14"]
            build-backend = "uv_build"

            [project]
            name = "shipping-rates"
            version = "0.3.0"
            requires-python = ">=3.12"
            dependencies = ["rupee-fmt~=1.1", "win-colors; sys_platform == 'win32'"]

            [project.optional-dependencies]
            report = ["table-print>=0.1"]

            [project.scripts]
            ship-quote = "shipping_rates.cli:main"

            [dependency-groups]
            dev = ["gst-calc>=1,<2"]

            [tool.ruff]
            line-length = 100
            """


            def annotated_pyproject() -> str:
                """PLAIN_PYPROJECT with a comment for every non-blank line."""
                raise NotImplementedError("Lab 4.1 exercise 1: annotate the file")
            '''
        ),
        md("Run the checks."),
        code(
            r'''
            def annotation_problems(plain: str, annotated: str) -> list[str]:
                """Lines of plain that have no 3-word comment (inline or on the line above) in annotated."""
                problems: list[str] = []
                comment_above = False
                content_lines = [line.strip() for line in textwrap.dedent(plain).splitlines() if line.strip()]
                seen = 0
                for line in textwrap.dedent(annotated).splitlines():
                    stripped = line.strip()
                    if stripped.startswith("#"):
                        comment_above = len(stripped.lstrip("# ").split()) >= 3
                        continue
                    if not stripped:
                        comment_above = False
                        continue
                    content, _, inline = stripped.partition(" # ")
                    if len(inline.split()) < 3 and not comment_above:
                        problems.append(content.strip())
                    seen += 1
                    comment_above = False
                if seen != len(content_lines):
                    problems.append(f"expected {len(content_lines)} TOML lines, found {seen}")
                return problems


            run_checks(
                [
                    (
                        "parses to the same data",
                        lambda: (
                            tomllib.loads(textwrap.dedent(annotated_pyproject()))
                            == tomllib.loads(textwrap.dedent(PLAIN_PYPROJECT))
                        ),
                        True,
                    ),
                    (
                        "every line annotated",
                        lambda: annotation_problems(PLAIN_PYPROJECT, annotated_pyproject()),
                        [],
                    ),
                    (
                        "still a build-system table",
                        lambda: tomllib.loads(textwrap.dedent(annotated_pyproject()))["build-system"][
                            "build-backend"
                        ],
                        "uv_build",
                    ),
                ]
            )
            '''
        ),
        md(
            """
            #### Exercise 2 — a `src/`-layout library with a console script, extras and groups

            Return the files (relative path → text) of a project that builds with uv:

            | Requirement | Detail |
            | --- | --- |
            | Name, version, Python | `invoice-tools`, `0.1.0`, `requires-python = ">=3.12"`, no runtime dependencies |
            | Build backend | `uv_build` (`requires = ["uv_build>=0.13,<0.14"]`) |
            | Layout | `src/invoice_tools/` with `__init__.py`, `cli.py` and `py.typed`; nothing importable at the root |
            | `__version__` | read with `importlib.metadata.version("invoice-tools")` in `__init__.py` |
            | Console script | `invoice-total` → `invoice_tools.cli:main`, which prints `total: <sum>` of its arguments with two decimals (`invoice-total 10 20.5` prints `total: 30.50`) |
            | Extra | `report` → `table-print>=0.1` |
            | Dependency group | `dev` → `rupee-fmt>=1` (must **not** appear in the wheel metadata) |
            """
        ),
        code(
            r'''
            def library_files() -> dict[str, str]:
                """Relative path -> file content for the invoice-tools project."""
                raise NotImplementedError("Lab 4.1 exercise 2: write the project files")
            '''
        ),
        md(
            "Run the checks. They build your project with `uv build`, then inspect and run the wheel."
        ),
        code(
            r'''
            LAB_DIR = UNIT41_DIR / "lab"


            _learner_builds: dict[str, tuple[Path, dict[str, str]]] = {}


            def build_learner_library() -> tuple[Path, dict[str, str]]:
                """Build library_files() with uv (once per distinct content); return (wheel, file texts)."""
                key = json.dumps(library_files(), sort_keys=True)
                if key not in _learner_builds:
                    _learner_builds[key] = _build_library()
                return _learner_builds[key]


            def _build_library() -> tuple[Path, dict[str, str]]:
                """Write library_files() under lab/, build with uv, read METADATA and entry points."""
                root = write_files(fresh_dir("lab/invoice-tools"), library_files())
                exit_code, output = run_tool("uv", "build", "--offline", cwd=root)
                if exit_code:
                    raise RuntimeError(output.splitlines()[-1])
                wheel_path = next((root / "dist").glob("*.whl"))
                with zipfile.ZipFile(wheel_path) as wheel:
                    names = wheel.namelist()
                    dist_info = next(name.split("/")[0] for name in names if ".dist-info/" in name)
                    report = {
                        "names": "\n".join(names),
                        "metadata": wheel.read(f"{dist_info}/METADATA").decode(),
                        "entry_points": wheel.read(f"{dist_info}/entry_points.txt").decode(),
                    }
                return wheel_path, report


            def run_learner_cli(*arguments: str) -> str:
                """Run invoice-total from the built wheel with uvx."""
                wheel_path, _ = build_learner_library()
                return run_tool(
                    "uvx", "--quiet", "--offline", "--from", str(wheel_path), "invoice-total", *arguments
                )[1]


            def learner_version() -> str:
                wheel_path, _ = build_learner_library()
                return run_tool(
                    "uv",
                    "run",
                    "--quiet",
                    "--offline",
                    "--no-project",
                    "--with",
                    str(wheel_path),
                    "python",
                    "-c",
                    "import invoice_tools; print(invoice_tools.__version__)",
                    cwd=LAB_DIR,
                )[1]


            run_checks(
                [
                    (
                        "src layout",
                        lambda: sorted(p for p in library_files() if p.startswith("src/invoice_tools/")),
                        [
                            "src/invoice_tools/__init__.py",
                            "src/invoice_tools/cli.py",
                            "src/invoice_tools/py.typed",
                        ],
                    ),
                    (
                        "nothing importable at the root",
                        lambda: [p for p in library_files() if p.endswith(".py") and "/" not in p],
                        [],
                    ),
                    (
                        "console script in entry_points.txt",
                        lambda: (
                            "invoice-total = invoice_tools.cli:main"
                            in build_learner_library()[1]["entry_points"]
                        ),
                        True,
                    ),
                    (
                        "extra published",
                        lambda: "Provides-Extra: report" in build_learner_library()[1]["metadata"],
                        True,
                    ),
                    (
                        "extra requirement",
                        lambda: (
                            re.search(
                                r"Requires-Dist: table-print>=0\.1 ?; extra == .report.",
                                build_learner_library()[1]["metadata"],
                            )
                            is not None
                        ),
                        True,
                    ),
                    (
                        "dev group not published",
                        lambda: "rupee-fmt" in build_learner_library()[1]["metadata"],
                        False,
                    ),
                    (
                        "py.typed in the wheel",
                        lambda: "invoice_tools/py.typed" in build_learner_library()[1]["names"],
                        True,
                    ),
                    ("invoice-total 10 20.5", lambda: run_learner_cli("10", "20.5"), "total: 30.50"),
                    ("__version__ from metadata", learner_version, "0.1.0"),
                ]
            )
            '''
        ),
        md(
            """
            #### Exercise 3 — a PEP 723 single-file script

            Return the source of a script with an inline metadata block that declares
            `requires-python = ">=3.12"` and the single dependency `rupee-fmt>=2`. When run, it
            prints two lines: `fmt(1234.5)` from `rupee_fmt`, then `rupee-fmt <version>` using
            `importlib.metadata`. The check runs it with `uv run` against the wheelhouse.
            Which version should the resolver choose, given that `2.1.0rc1` exists?
            """
        ),
        code(
            r'''
            def pep723_script() -> str:
                """Source of a self-describing script for `uv run`."""
                raise NotImplementedError("Lab 4.1 exercise 3: write the script")
            '''
        ),
        md(
            "Run the checks. `read_script_metadata` uses the reference regular expression from PEP 723."
        ),
        code(
            r'''
            PEP723_BLOCK = re.compile(
                r"(?m)^# /// (?P<type>[a-zA-Z0-9-]+)$\s(?P<content>(^#(| .*)$\s)+)^# ///$"
            )


            def read_script_metadata(script: str) -> dict[str, object]:
                """Parse the `# /// script` block of a PEP 723 script."""
                script = textwrap.dedent(script)
                match = next((m for m in PEP723_BLOCK.finditer(script) if m["type"] == "script"), None)
                if match is None:
                    raise ValueError("no `# /// script` block")
                toml_text = "".join(
                    line[2:] if line.startswith("# ") else line[1:]
                    for line in match["content"].splitlines(keepends=True)
                )
                return tomllib.loads(toml_text)


            def run_learner_script() -> list[str]:
                root = fresh_dir("lab/script")
                (root / "quote.py").write_text(textwrap.dedent(pep723_script()))
                output = run_tool(
                    "uv",
                    "run",
                    "--quiet",
                    "--offline",
                    "--no-index",
                    "--find-links",
                    str(WHEELHOUSE),
                    "quote.py",
                    cwd=root,
                )[1]
                return output.splitlines()[-2:]


            run_checks(
                [
                    (
                        "requires-python",
                        lambda: read_script_metadata(pep723_script())["requires-python"],
                        ">=3.12",
                    ),
                    (
                        "dependencies",
                        lambda: [
                            d.replace(" ", "") for d in read_script_metadata(pep723_script())["dependencies"]
                        ],
                        ["rupee-fmt>=2"],
                    ),
                    ("output", run_learner_script, ["\u20b91,234.50", "rupee-fmt 2.0.0"]),
                ]
            )
            '''
        ),
        md(
            """
            #### Exercise 4 — build a wheel and inspect its contents

            Write `wheel_summary(wheel_path)` returning a dict with these keys, read only from
            the wheel file (use `zipfile` and `email.parser`; do not install anything):

            | Key | Value |
            | --- | --- |
            | `"name"`, `"version"` | from `METADATA` |
            | `"tags"` | list of the `Tag:` values in `WHEEL` |
            | `"packages"` | sorted top-level folders or modules outside `.dist-info/` |
            | `"console_scripts"` | dict command → `module:function` from `entry_points.txt` (empty if none) |
            | `"requires_dist"` | list of `Requires-Dist` values |
            | `"record_ok"` | `True` if every file listed in `RECORD` with a hash matches its SHA-256 |

            The check uses `gst-calc 1.0.0` from the wheelhouse and a tampered copy of it.
            """
        ),
        code(
            r'''
            def wheel_summary(wheel_path: Path) -> dict[str, object]:
                """Facts about a wheel, read from its files."""
                raise NotImplementedError("Lab 4.1 exercise 4: inspect the wheel")
            '''
        ),
        md("Run the checks."),
        code(
            r'''
            GST_WHEEL = build_wheelhouse() / "gst_calc-1.0.0-py3-none-any.whl"


            def tampered_wheel() -> Path:
                """A copy of GST_WHEEL whose gst_calc/__init__.py was edited after building."""
                LAB_DIR.mkdir(parents=True, exist_ok=True)
                target = LAB_DIR / GST_WHEEL.name
                with zipfile.ZipFile(GST_WHEEL) as source, zipfile.ZipFile(target, "w") as copy:
                    for item in source.infolist():
                        data = source.read(item)
                        if item.filename == "gst_calc/__init__.py":
                            data += b"\nprint('surprise')\n"
                        copy.writestr(item, data)
                return target


            run_checks(
                [
                    ("name", lambda: wheel_summary(GST_WHEEL)["name"], "gst-calc"),
                    ("version", lambda: wheel_summary(GST_WHEEL)["version"], "1.0.0"),
                    ("tags", lambda: wheel_summary(GST_WHEEL)["tags"], ["py3-none-any"]),
                    ("packages", lambda: wheel_summary(GST_WHEEL)["packages"], ["gst_calc"]),
                    (
                        "console scripts",
                        lambda: wheel_summary(GST_WHEEL)["console_scripts"],
                        {"gst": "gst_calc:main"},
                    ),
                    ("three requirements", lambda: len(wheel_summary(GST_WHEEL)["requires_dist"]), 3),
                    (
                        "one extra requirement",
                        lambda: sum("extra ==" in r for r in wheel_summary(GST_WHEEL)["requires_dist"]),
                        1,
                    ),
                    ("RECORD verifies", lambda: wheel_summary(GST_WHEEL)["record_ok"], True),
                    ("tampering detected", lambda: wheel_summary(tampered_wheel())["record_ok"], False),
                ]
            )
            '''
        ),
    ]


def _recap_cells() -> list[NotebookNode]:
    """Recap for Unit 4.1."""
    return [
        md(
            """
            ### Recap — Unit 4.1

            | Concept | One-line takeaway | JS equivalent |
            | --- | --- | --- |
            | Wheels and tags | `py3-none-any` fits everywhere; `cp315-cp315t-manylinux_2_28_x86_64` fits one interpreter, ABI and platform | prebuilt binaries per platform (`node-pre-gyp`) |
            | sdist | Source + `pyproject.toml`; installing it runs the build backend | publishing raw source with an `install` script |
            | Frontend / backend | uv and pip call PEP 517 hooks of `uv_build`, `hatchling`, `setuptools`, … | none |
            | pip | Backtracking resolver; `-e` editable; `-c` constraints; `freeze` is not a lock | npm |
            | uv | `init`, `add`, `lock --upgrade-package`, `sync --locked/--frozen`, `run`, `tool`, `uvx`, scripts, workspaces, `export`, `build`, `publish` | pnpm + npx + nvm |
            | `pyproject.toml` | `[build-system]`, `[project]`, scripts, extras, `[dependency-groups]`, `[tool.*]` | `package.json` |
            | PEP 440 | `~=1.4` is `>=1.4,==1.*`; pre-releases opt-in; markers and extras | semver ranges |
            | Lockfiles | `uv.lock` (universal), `pylock.toml` (standard); apps pin, libraries stay wide | `package-lock.json` |
            | Layout | `src/` forces tests to use the installed package; editable = `.pth` | `npm link` |
            | Publishing | Inspect the wheel, rehearse on TestPyPI, use trusted publishing; SemVer or CalVer; keep a changelog | `npm publish --provenance` |
            | Supply chain | `pip-audit`, hashes, `deptry`, name checks, licenses | `npm audit`, lockfile integrity |

            **Further reading**

            - [Python Packaging User Guide](https://packaging.python.org/),
              [`pyproject.toml` specification](https://packaging.python.org/en/latest/specifications/pyproject-toml/),
              [Version specifiers](https://packaging.python.org/en/latest/specifications/version-specifiers/),
              [Platform compatibility tags](https://packaging.python.org/en/latest/specifications/platform-compatibility-tags/),
              [Binary distribution format](https://packaging.python.org/en/latest/specifications/binary-distribution-format/)
            - [uv documentation](https://docs.astral.sh/uv/) (projects, workspaces, scripts,
              tools, publishing), [pip documentation](https://pip.pypa.io/)
            - [`importlib.metadata`](https://docs.python.org/3/library/importlib.metadata.html),
              [`tomllib`](https://docs.python.org/3/library/tomllib.html),
              [`zipfile`](https://docs.python.org/3/library/zipfile.html),
              [`venv`](https://docs.python.org/3/library/venv.html)
            - [PEP 440](https://peps.python.org/pep-0440/), [PEP 508](https://peps.python.org/pep-0508/),
              [PEP 517](https://peps.python.org/pep-0517/), [PEP 518](https://peps.python.org/pep-0518/),
              [PEP 621](https://peps.python.org/pep-0621/), [PEP 639](https://peps.python.org/pep-0639/),
              [PEP 660](https://peps.python.org/pep-0660/), [PEP 723](https://peps.python.org/pep-0723/),
              [PEP 735](https://peps.python.org/pep-0735/), [PEP 751](https://peps.python.org/pep-0751/)
            - [PyPI trusted publishers](https://docs.pypi.org/trusted-publishers/),
              [Keep a Changelog](https://keepachangelog.com/), [pip-audit](https://github.com/pypa/pip-audit),
              [deptry](https://deptry.com/)
            """
        ),
    ]


def cells() -> list[NotebookNode]:
    """Return the cells for Unit 4.1 and Lab 4.1."""
    return [
        *_overview_cells(),
        *_ecosystem_cells(),
        *_pip_cells(),
        *_uv_cells(),
        *_pyproject_cells(),
        *_specifier_cells(),
        *_lockfile_cells(),
        *_layout_cells(),
        *_publishing_cells(),
        *_supply_chain_cells(),
        *_tool_comparison_cells(),
        *_lab_cells(),
        *_recap_cells(),
    ]
