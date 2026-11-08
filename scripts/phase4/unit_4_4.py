"""Unit 4.4 — Standard Library Essentials (with Lab 4.4)."""

from nbformat import NotebookNode

from nb_builder import code, md, predict_cells

UNIT_SETUP_SOURCE = r'''
import argparse
import base64
import bisect
import contextlib
import csv
import dataclasses
import difflib
import enum
import glob
import graphlib
import hashlib
import heapq
import hmac
import inspect
import io
import json
import math
import os
import pprint
import random
import re
import secrets
import shlex
import shutil
import statistics
import string
import subprocess
import sys
import textwrap
import time
import urllib.parse
import uuid
import warnings
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path, PurePosixPath, PureWindowsPath
from zoneinfo import ZoneInfo

REPO_ROOT = find_repo_root()
scratch_dir = REPO_ROOT / "notebooks" / "_scratch"  # git-ignored
UNIT44_DIR = scratch_dir / "unit44"
UNIT44_DIR.mkdir(parents=True, exist_ok=True)
IST = ZoneInfo("Asia/Kolkata")
NEW_YORK = ZoneInfo("America/New_York")
LONDON = ZoneInfo("Europe/London")
FIXED_MOMENT = datetime(2026, 11, 7, 9, 30, tzinfo=UTC)  # every "now" in this unit


def tidy(text: str) -> str:
    """Show absolute paths as <scratch>, <repo> or ~."""
    for folder, label in ((UNIT44_DIR, "<scratch>"), (REPO_ROOT, "<repo>"), (Path.home(), "~")):
        text = text.replace(str(folder), label)
    return text


def fresh_dir(name: str) -> Path:
    """An empty folder <scratch>/<name>, recreated on every run."""
    folder = UNIT44_DIR / name
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    return folder


def raised_message(thunk: Callable[[], object]) -> str:
    """Call thunk and return "ErrorName: message" for the exception it raised, or "no error"."""
    try:
        thunk()
    except Exception as error:
        return f"{type(error).__name__}: {error}"
    return "no error"


SAMPLE_FILES = {
    "src/shop/__init__.py": "",
    "src/shop/orders.py": "def total(prices):\n    return sum(prices)\n",
    "tests/test_orders.py": "from shop.orders import total\n",
    "data/sales_2026-10.csv": "sku,quantity\nTEA-500,12\n",
    "data/sales_2026-11.csv": "sku,quantity\nTEA-500,7\nMUG-02,3\n",
    "docs/README.md": "# Shop\n\nPrices in ₹ (rupees).\n",
}


def make_sample_tree(name: str = "sample_tree") -> Path:
    """A small project tree with fixed contents and fixed modification times."""
    root = fresh_dir(name)
    for offset, (relative_path, text) in enumerate(sorted(SAMPLE_FILES.items())):
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        stamp = (FIXED_MOMENT - timedelta(days=offset)).timestamp()
        os.utime(path, (stamp, stamp))
    return root


sample_root = make_sample_tree()
print(f"{sample_root.relative_to(REPO_ROOT).as_posix()}: {len(SAMPLE_FILES)} files")
print(f"time zones: {IST}, {NEW_YORK}, {LONDON}; fixed moment {FIXED_MOMENT.isoformat()}")
'''


def _overview_cells() -> list[NotebookNode]:
    """Unit opener and setup."""
    return [
        md(
            """
            ## Unit 4.4 — Standard Library Essentials

            **Objectives**

            - Work with files and folders through `pathlib`, and know the `os`, `sys` and
              `shutil` functions around it.
            - Run other programs safely with `subprocess`.
            - Handle dates and times correctly: aware datetimes, time zones, UTC storage, DST,
              ISO 8601, and the right clock for measuring time.
            - Read and write regular expressions, including verbose patterns and lookarounds,
              and avoid catastrophic backtracking.
            - Serialize JSON and CSV without losing precision or data.
            - Reach for `heapq`, `bisect`, `statistics`, `math` and `graphlib` instead of
              writing them yourself.
            - Tell `random` from `secrets`; hash, sign, encode and parse URLs.
            - Build a command-line interface with `argparse`; format text with the text
              utilities.

            **JS bridge: Node built-ins → the standard library**

            | Node / browser | Python | The difference that bites |
            | --- | --- | --- |
            | `path.join`, `fs.readFileSync` | `Path("a") / "b"`, `path.read_text(encoding="utf-8")` | Paths are **objects**; always pass `encoding` |
            | `child_process.execFile` / `exec` | `subprocess.run([...])` / `shell=True` | Pass a **list**; `shell=True` with user input is an injection hole |
            | `Date` (always UTC inside, local outside) | `datetime` naive or **aware** | A naive datetime has no time zone at all; use `ZoneInfo` |
            | `Intl.DateTimeFormat` | `strftime` | Format codes such as `%Y-%m-%d` |
            | `/\\d+/g`, `str.match(re)` | `re.findall(r"\\d+", text)` | Raw strings; `re.match` anchors at the start; no `g` flag |
            | `JSON.parse(text)` | `json.loads(text, parse_float=Decimal)` | Python can keep decimals exact |
            | (npm `heap`, `lodash.sortedIndex`) | `heapq`, `bisect` | Batteries included |
            | `Math.random()` | `random` (seedable) / `secrets` (crypto) | Never use `random` for tokens |
            | `crypto.createHmac` | `hmac.new(key, body, "sha256")` | `hmac.compare_digest` for checks |
            | `crypto.randomUUID()` | `uuid.uuid4()`, `uuid.uuid7()` (3.14) | v7 sorts by creation time |
            | `new URL(...)`, `URLSearchParams` | `urllib.parse.urlsplit`, `parse_qs`, `urlencode` | Functions, not classes |
            | `process.argv` + commander/yargs | `sys.argv` + `argparse` | Built in, with `--help` for free |

            **Determinism.** Dates use fixed example datetimes with explicit time zones
            (`FIXED_MOMENT` is 2026-11-07 09:30 UTC), `random` is seeded, file demos use a
            scratch tree with fixed modification times under `notebooks/_scratch/unit44/`.
            Only the `secrets` and `uuid4` demos print properties instead of values: being
            unpredictable is their whole point.
            """
        ),
        code(UNIT_SETUP_SOURCE),
    ]


def _path_cells() -> list[NotebookNode]:
    """4.4.1 Paths and the OS."""
    return [
        md(
            """
            ### 4.4.1 Paths and the OS

            **`pathlib`** (Python 3.4+) represents a path as an object. `Path` is the concrete
            class for the current OS (`PosixPath` here, `WindowsPath` on Windows);
            `PurePosixPath` and `PureWindowsPath` manipulate paths of either system without
            touching the disk. The `/` operator joins.

            **Joining and taking apart:**
            """
        ),
        code(
            r"""
            report = Path("data") / "reports" / "sales_2026-11.tar.gz"
            print(f"{report=}")
            print(f"{report.name=}, {report.stem=}, {report.suffix=}, {report.suffixes=}")
            print(f"{report.parent=}, {list(report.parents)=}")
            print(f"{report.parts=}, {Path('/srv/shop').anchor=}")
            print(f"{report.with_suffix('.zip')=}, {report.with_name('summary.txt')=}")
            print(f"{Path('data').joinpath('2026', 'nov.csv')=}")
            print(f"{PureWindowsPath(r'C:\Shop\data\nov.csv').parts=}")
            print(f"{PurePosixPath('/srv/shop/data/nov.csv').relative_to('/srv/shop')=}")
            """
        ),
        *predict_cells(
            """
            from pathlib import Path

            archive = Path("backups/shop.tar.gz")
            print(archive.suffix, archive.suffixes, archive.stem)
            """,
            """
            `.gz ['.tar', '.gz'] shop.tar`. `suffix` is only the **last** extension and `stem`
            is the name without it, so multi-part extensions need `suffixes` (or
            `name.removesuffix(".tar.gz")`).
            """,
            """
            archive = Path("backups/shop.tar.gz")
            print(archive.suffix, archive.suffixes, archive.stem)
            """,
        ),
        md(
            """
            **Searching: `glob`, `rglob`, `walk`.** `glob(pattern)` matches in one folder
            (`**` recurses); `rglob(pattern)` is `glob("**/" + pattern)`. `Path.walk()` (*New
            in 3.12*) is the pathlib version of `os.walk`: it yields `(folder, subfolders,
            files)` top-down, and you can prune `subfolders` in place to skip them. Results
            are sorted here because the OS returns entries in no particular order.
            """
        ),
        code(
            r"""
            print(f"{sorted(path.name for path in sample_root.glob('data/*.csv'))=}")
            print(f"{sorted(path.relative_to(sample_root).as_posix() for path in sample_root.rglob('*.py'))=}")
            print(f"{sorted(path.name for path in sample_root.glob('**/sales_*'))=}")
            for folder, subfolders, files in sample_root.walk():
                subfolders[:] = sorted(name for name in subfolders if name != "tests")  # prune
                print(
                    f"  {folder.relative_to(sample_root).as_posix():<10} "
                    f"dirs={subfolders} files={sorted(files)}"
                )
            """
        ),
        md(
            """
            **Reading and writing.** `read_text` / `write_text` open, read or write and close
            in one call; `read_bytes` / `write_bytes` for binary data. Always pass
            `encoding="utf-8"`: the default depends on the platform (*Changed in 3.15*: UTF-8
            mode is on by default, PEP 686, but explicit is still clearer and works on every
            version). For large files, use `open()` and iterate line by line.
            """
        ),
        code(
            r"""
            readme = sample_root / "docs" / "README.md"
            print(f"{readme.read_text(encoding='utf-8')!r}")
            notes = sample_root / "docs" / "notes.txt"
            characters_written = notes.write_text("Diwali sale: 10% off ₹500+\n", encoding="utf-8")
            print(f"{characters_written=}, {len(notes.read_bytes())=} bytes (₹ is 3 bytes in UTF-8)")
            with (sample_root / "data" / "sales_2026-11.csv").open(encoding="utf-8") as sales_file:
                print(f"{[line.rstrip() for line in sales_file]=}")
            print(f"{sys.flags.utf8_mode=}")
            """
        ),
        md(
            """
            **`resolve`, `absolute`, relative paths and symlinks.** `absolute()` prefixes the
            current folder without touching the disk; `resolve()` also follows symlinks and
            removes `..`. `relative_to` computes a relative path (`walk_up=True`, *New in
            3.12*, allows `..` steps), `is_relative_to` tests containment, which is how you
            stop a user-supplied path from escaping a folder (`../../etc/passwd`).
            """
        ),
        code(
            r"""
            latest = sample_root / "data" / "latest.csv"
            latest.unlink(missing_ok=True)
            latest.symlink_to("sales_2026-11.csv")
            print(f"{latest.is_symlink()=}, {latest.resolve().name=}")
            messy = sample_root / "src" / ".." / "docs" / "README.md"
            print(f"{tidy(str(messy))}\n -> {tidy(str(messy.resolve()))}")
            print(f"{(sample_root / 'docs').relative_to(sample_root / 'src', walk_up=True)=}")
            uploads = sample_root / "uploads"
            for requested in ("invoice.pdf", "../../etc/passwd"):
                inside = (uploads / requested).resolve().is_relative_to(uploads.resolve())
                print(f"  {requested!r:<20} safe={inside}")
            """
        ),
        md(
            """
            **`stat`, `exists`, `is_file`, `is_dir`.** `stat()` returns size, timestamps and
            permissions (one system call; *New in 3.14*: `path.info` caches the file-type
            checks of a directory listing). Modification times are POSIX timestamps (seconds
            since 1970 UTC): convert with `datetime.fromtimestamp(ts, UTC)`.
            """
        ),
        code(
            r"""
            sales = sample_root / "data" / "sales_2026-11.csv"
            file_status = sales.stat()
            print(f"{file_status.st_size=} bytes, {file_status.st_mtime=}")
            print(f"modified: {datetime.fromtimestamp(file_status.st_mtime, UTC).isoformat()}")
            print(
                f"{sales.exists()=}, {sales.is_file()=}, "
                f"{sales.parent.is_dir()=}, {(sample_root / 'nope').exists()=}"
            )
            if sys.version_info >= (3, 14):
                entry = next(
                    path for path in (sample_root / "data").iterdir() if path.name == "sales_2026-10.csv"
                )
                print(f"New in 3.14: {entry.info.is_file()=}, {entry.info.is_symlink()=}")
            """
        ),
        md(
            """
            **Creating, copying, moving, deleting.** `mkdir(parents=True, exist_ok=True)`,
            `touch`, `rename`/`replace`, `unlink`, `rmdir` (empty folders only). *New in 3.14:*
            `Path.copy`, `Path.copy_into` and `Path.move` cover what used to need `shutil`.
            """
        ),
        code(
            r"""
            archive_dir = sample_root / "archive" / "2026" / "10"
            archive_dir.mkdir(parents=True, exist_ok=True)
            october = sample_root / "data" / "sales_2026-10.csv"
            if sys.version_info >= (3, 14):
                copied = october.copy_into(archive_dir)  # New in 3.14
                moved = copied.move(archive_dir / "sales.csv")  # New in 3.14
                print(f"{copied.name=}, {moved.relative_to(sample_root).as_posix()=}")
            else:
                shutil.copy2(october, archive_dir / "sales.csv")
            (archive_dir / "sales.csv").unlink()
            archive_dir.rmdir()
            print(f"{sorted(path.name for path in (sample_root / 'archive' / '2026').iterdir())=}")
            """
        ),
        md(
            """
            **Under the hood: one class per OS.** `Path(...)` returns an instance of the
            platform's subclass, and pure paths never touch the filesystem. Path objects use
            `__slots__` (no per-instance `__dict__`) and are immutable and hashable, so they
            work as dict keys.
            """
        ),
        code(
            r"""
            print([klass.__name__ for klass in type(Path("x")).__mro__])
            print(f"{hasattr(Path('x'), '__dict__')=}, {'__slots__' in vars(Path.__mro__[-2])=}")
            print(f"{Path('data/nov.csv') == Path('data//nov.csv')=}, {len({Path('a/b'), Path('a') / 'b'})=}")
            print(
                f"{PureWindowsPath('C:/Shop/Data.CSV') == PureWindowsPath('c:/shop/data.csv')=}"
                "  (Windows is case-insensitive)"
            )
            """
        ),
        md(
            """
            **`os` and `sys`.** `os` talks to the operating system (environment, processes,
            low-level files); `sys` talks to the interpreter. The ones you meet most:

            | Call | Gives |
            | --- | --- |
            | `os.environ`, `os.getenv(name, default)` | environment variables (strings) |
            | `os.sep`, `os.linesep`, `os.pathsep` | `/`, `\\n`, `:` here (`\\`, `\\r\\n`, `;` on Windows) |
            | `os.cpu_count()`, `os.process_cpu_count()` (3.13) | CPUs in the machine / usable by this process |
            | `os.getpid()` | this process's id |
            | `os.scandir(folder)` | fast directory listing with cached type checks |
            | `os.replace(src, dst)` | atomic rename, the basis of safe file writes |
            | `sys.argv`, `sys.exit(code)` | command-line arguments, exit status |
            | `sys.platform`, `sys.version_info`, `sys.executable` | where and what is running |
            | `sys.stdin`, `sys.stdout`, `sys.stderr` | the standard streams |
            """
        ),
        code(
            r"""
            print(f"{os.getenv('SHOP_CURRENCY', 'INR')=}  (default used: the variable is not set)")
            print(f"{os.sep=}, {os.linesep=}, {os.pathsep=}")
            print(
                f"{isinstance(os.cpu_count(), int)=}, {isinstance(os.getpid(), int)=}  (values vary by machine)"
            )
            with os.scandir(sample_root / "data") as entries:
                print(f"{sorted((entry.name, entry.is_file()) for entry in entries)=}")
            print(f"{sys.platform=}, {sys.version_info[:2]=}, {Path(sys.executable).name=}")
            print(f"{sys.getrecursionlimit()=}, {sys.stdout.isatty()=}")
            """
        ),
        md(
            """
            **Atomic writes with `os.replace`.** Writing a file in place can leave it
            half-written if the program crashes. Write a temporary file in the same folder,
            then `os.replace` it over the target: readers see either the old file or the new
            one, never a mix (the rename is atomic on POSIX and Windows).
            """
        ),
        code(
            r'''
            def write_atomically(target: Path, text: str) -> None:
                """Replace target's contents in one atomic step."""
                temporary = target.with_name(f".{target.name}.tmp")
                temporary.write_text(text, encoding="utf-8")
                os.replace(temporary, target)


            settings_file = sample_root / "settings.json"
            write_atomically(settings_file, json.dumps({"currency": "INR", "gst": 18}))
            write_atomically(settings_file, json.dumps({"currency": "INR", "gst": 12}))
            print(f"{settings_file.read_text()=}, {sorted(path.name for path in sample_root.glob('.*.tmp'))=}")
            '''
        ),
        md(
            """
            **`shutil`: high-level file operations.** `copy2` copies contents **and** metadata
            (timestamps), `copytree` copies a folder (with `ignore=shutil.ignore_patterns(...)`),
            `move`, `rmtree`, `make_archive` (zip/tar), `which` (find a program on `PATH`) and
            `disk_usage`.
            """
        ),
        code(
            r"""
            backup = UNIT44_DIR / "backup_tree"
            shutil.rmtree(backup, ignore_errors=True)
            shutil.copytree(sample_root, backup, ignore=shutil.ignore_patterns("tests", "*.tmp", "latest.csv"))
            print(
                f"{sorted(path.relative_to(backup).as_posix() for path in backup.rglob('*') if path.is_file())}"
            )
            copied = shutil.copy2(sample_root / "docs" / "README.md", backup / "README.copy.md")
            same_mtime = Path(copied).stat().st_mtime == (sample_root / "docs" / "README.md").stat().st_mtime
            print(f"copy2 keeps the modification time: {same_mtime}")
            archive_path = shutil.make_archive(str(UNIT44_DIR / "backup"), "zip", backup)
            print(f"{Path(archive_path).name=}, {shutil.which('git') is not None=}")
            usage = shutil.disk_usage(UNIT44_DIR)
            print(f"{usage.used <= usage.total=}  (disk_usage values vary)")
            """
        ),
        md(
            """
            #### `os.path` → `pathlib` mapping

            Older code (and many answers online) use the string functions of `os.path`. Each
            has a `pathlib` equivalent; one demo per row follows, grouped by purpose.

            | `os.path` / `os` / `glob` | `pathlib` | Demo group |
            | --- | --- | --- |
            | `os.path.join(a, b)` | `Path(a) / b` | Building paths |
            | `os.path.abspath(p)` | `Path(p).absolute()` | Building paths |
            | `os.path.realpath(p)` | `Path(p).resolve()` | Building paths |
            | `os.path.expanduser("~/x")` | `Path("~/x").expanduser()`, `Path.home()` | Building paths |
            | `os.path.relpath(p, start)` | `Path(p).relative_to(start, walk_up=True)` | Building paths |
            | `os.path.basename(p)` | `Path(p).name` | Taking paths apart |
            | `os.path.dirname(p)` | `Path(p).parent` | Taking paths apart |
            | `os.path.splitext(p)` | `Path(p).stem`, `Path(p).suffix` | Taking paths apart |
            | `os.path.isabs(p)` | `Path(p).is_absolute()` | Taking paths apart |
            | `os.path.exists(p)` | `Path(p).exists()` | Querying the filesystem |
            | `os.path.isfile(p)`, `os.path.isdir(p)` | `.is_file()`, `.is_dir()` | Querying the filesystem |
            | `os.path.getsize(p)` | `Path(p).stat().st_size` | Querying the filesystem |
            | `os.path.getmtime(p)` | `Path(p).stat().st_mtime` | Querying the filesystem |
            | `os.path.samefile(a, b)` | `Path(a).samefile(b)` | Querying the filesystem |
            | `os.listdir(p)` | `Path(p).iterdir()` | Listing and walking |
            | `glob.glob("**/*.py", recursive=True)` | `Path().glob("**/*.py")`, `rglob("*.py")` | Listing and walking |
            | `os.walk(p)` | `Path(p).walk()` (3.12) | Listing and walking |
            | `os.makedirs(p, exist_ok=True)` | `Path(p).mkdir(parents=True, exist_ok=True)` | Changing the filesystem |
            | `os.rename(a, b)`, `os.replace(a, b)` | `Path(a).rename(b)`, `.replace(b)` | Changing the filesystem |
            | `os.remove(p)` | `Path(p).unlink()` | Changing the filesystem |
            | `open(p).read()` | `Path(p).read_text(encoding=...)` | Changing the filesystem |

            #### Building paths

            `os.path.join(a, b)` → `Path(a) / b`. Both treat an absolute second part as a
            restart.
            """
        ),
        code(
            r"""
            print(f"{os.path.join('data', 'nov.csv')=}, {Path('data') / 'nov.csv'=}")
            print(f"{os.path.join('data', '/etc/hosts')=}, {Path('data') / '/etc/hosts'=}")
            """
        ),
        md(
            "`os.path.abspath(p)` → `Path(p).absolute()` (no symlink resolution, no `..` removal for `absolute`):"
        ),
        code(
            r"""
            with contextlib.chdir(sample_root):  # contextlib.chdir: New in 3.11
                print(f"{tidy(os.path.abspath('docs/../data'))=}")
                print(f"{tidy(str(Path('docs/../data').absolute()))=}")
            """
        ),
        md("`os.path.realpath(p)` → `Path(p).resolve()` (follows symlinks, removes `..`):"),
        code(
            r"""
            link = sample_root / "data" / "latest.csv"
            print(f"{Path(os.path.realpath(link)).name=}, {link.resolve().name=}")
            """
        ),
        md("`os.path.expanduser` → `Path.expanduser()` / `Path.home()`:"),
        code(
            r"""
            print(f"{tidy(os.path.expanduser('~/.config/shop'))=}")
            print(
                f"{tidy(str(Path('~/.config/shop').expanduser()))=}, {Path.home() == Path('~').expanduser()=}"
            )
            """
        ),
        md("`os.path.relpath(p, start)` → `Path(p).relative_to(start, walk_up=True)`:"),
        code(
            r"""
            print(f"{os.path.relpath('/srv/shop/docs', '/srv/shop/src')=}")
            print(f"{Path('/srv/shop/docs').relative_to('/srv/shop/src', walk_up=True)=}")
            print(raised_message(lambda: Path("/srv/shop/docs").relative_to("/srv/shop/src")))
            """
        ),
        md(
            """
            #### Taking paths apart

            `os.path.basename(p)` → `Path(p).name` (note the trailing-slash difference):
            """
        ),
        code(
            r"""
            print(f"{os.path.basename('data/nov.csv')=}, {Path('data/nov.csv').name=}")
            print(f"{os.path.basename('data/')=}, {Path('data/').name=}")
            """
        ),
        md("`os.path.dirname(p)` → `Path(p).parent`:"),
        code(
            r"""
            print(f"{os.path.dirname('data/2026/nov.csv')=}, {Path('data/2026/nov.csv').parent=}")
            print(f"{os.path.dirname('nov.csv')=}, {Path('nov.csv').parent=}  ('' vs '.')")
            """
        ),
        md("`os.path.splitext(p)` → `.stem` and `.suffix`:"),
        code(
            r"""
            print(f"{os.path.splitext('reports/sales.tar.gz')=}")
            print(f"{Path('reports/sales.tar.gz').stem=}, {Path('reports/sales.tar.gz').suffix=}")
            """
        ),
        md("`os.path.isabs(p)` → `Path(p).is_absolute()`:"),
        code(
            r"""
            print(
                f"{os.path.isabs('/srv/shop')=}, {Path('/srv/shop').is_absolute()=}, "
                f"{Path('srv/shop').is_absolute()=}"
            )
            print(
                f"{PureWindowsPath('C:/shop').is_absolute()=}, "
                f"{PureWindowsPath('/shop').is_absolute()=}  (no drive)"
            )
            """
        ),
        md(
            """
            #### Querying the filesystem

            `os.path.exists(p)` → `Path(p).exists()`:
            """
        ),
        code(
            r"""
            print(
                f"{os.path.exists(sample_root / 'docs')=}, {(sample_root / 'docs').exists()=}, "
                f"{(sample_root / 'missing').exists()=}"
            )
            """
        ),
        md("`os.path.isfile` / `isdir` → `.is_file()` / `.is_dir()`:"),
        code(
            r"""
            readme = sample_root / "docs" / "README.md"
            print(
                f"{os.path.isfile(readme)=}, {readme.is_file()=}, {readme.is_dir()=}, {readme.parent.is_dir()=}"
            )
            """
        ),
        md("`os.path.getsize(p)` → `Path(p).stat().st_size`:"),
        code(
            r"""
            print(f"{os.path.getsize(readme)=}, {readme.stat().st_size=}")
            """
        ),
        md("`os.path.getmtime(p)` → `Path(p).stat().st_mtime`:"),
        code(
            r"""
            print(f"{os.path.getmtime(readme) == readme.stat().st_mtime=}")
            print(f"{datetime.fromtimestamp(readme.stat().st_mtime, UTC).date()=}")
            """
        ),
        md("`os.path.samefile(a, b)` → `Path(a).samefile(b)`:"),
        code(
            r"""
            link, target = sample_root / "data" / "latest.csv", sample_root / "data" / "sales_2026-11.csv"
            print(f"{os.path.samefile(link, target)=}, {link.samefile(target)=}, {link == target=}")
            """
        ),
        md(
            """
            #### Listing and walking

            `os.listdir(p)` → `Path(p).iterdir()` (names vs `Path` objects):
            """
        ),
        code(
            r"""
            print(f"{sorted(os.listdir(sample_root / 'docs'))=}")
            print(f"{sorted(path.name for path in (sample_root / 'docs').iterdir())=}")
            """
        ),
        md("`glob.glob(..., recursive=True)` → `Path.glob` / `rglob`:"),
        code(
            r"""
            with contextlib.chdir(sample_root):
                print(f"{sorted(glob.glob('**/*.py', recursive=True))=}")
                print(f"{sorted(path.as_posix() for path in Path().rglob('*.py'))=}")
            """
        ),
        md("`os.walk(p)` → `Path(p).walk()` (strings vs `Path` objects for the folder):"),
        code(
            r"""
            walked_with_os = sorted(
                os.path.relpath(folder, sample_root) for folder, _, _ in os.walk(sample_root)
            )
            walked_with_path = sorted(
                folder.relative_to(sample_root).as_posix() for folder, _, _ in sample_root.walk()
            )
            print(f"{walked_with_os=}")
            print(f"{walked_with_os == walked_with_path=}")
            """
        ),
        md(
            """
            #### Changing the filesystem

            `os.makedirs(p, exist_ok=True)` → `Path(p).mkdir(parents=True, exist_ok=True)`:
            """
        ),
        code(
            r"""
            os.makedirs(sample_root / "out" / "a", exist_ok=True)
            (sample_root / "out" / "b" / "c").mkdir(parents=True, exist_ok=True)
            out_folders = [
                folder.relative_to(sample_root).as_posix() for folder, _, _ in (sample_root / "out").walk()
            ]
            print(f"{sorted(out_folders)=}")
            """
        ),
        md(
            "`os.rename` / `os.replace` → `Path.rename` / `Path.replace` (both return the new path):"
        ),
        code(
            r"""
            draft = sample_root / "out" / "draft.txt"
            draft.write_text("v1", encoding="utf-8")
            final = draft.rename(sample_root / "out" / "final.txt")
            (sample_root / "out" / "draft.txt").write_text("v2", encoding="utf-8")
            os.replace(sample_root / "out" / "draft.txt", final)
            print(f"{final.name=}, {final.read_text()=}, {(sample_root / 'out' / 'draft.txt').exists()=}")
            """
        ),
        md("`os.remove(p)` → `Path(p).unlink()` (`missing_ok=True` ignores a missing file):"),
        code(
            r"""
            final.unlink()
            print(tidy(raised_message(lambda: os.remove(final))))
            final.unlink(missing_ok=True)
            print(f"{final.exists()=}")
            """
        ),
        md("`open(p).read()` → `Path(p).read_text(encoding=...)` (the file is closed for you):"),
        code(
            r"""
            with open(readme, encoding="utf-8") as readme_file:
                via_open = readme_file.read()
            print(
                f"{via_open == readme.read_text(encoding='utf-8')=}, "
                f"{readme.read_text(encoding='utf-8').splitlines()[0]=}"
            )
            """
        ),
    ]


def _process_cells() -> list[NotebookNode]:
    """4.4.2 Processes."""
    return [
        md(
            """
            ### 4.4.2 Processes

            **`subprocess.run`** starts a program, waits for it and returns a
            `CompletedProcess`. Pass the command as a **list** (program, then each argument);
            `capture_output=True` collects stdout and stderr, `text=True` decodes them to
            `str`. The demos run Python children (`sys.executable`) so they behave the same on
            every machine.
            """
        ),
        code(
            r"""
            completed = subprocess.run(
                [sys.executable, "-c", "import sys; print('stock ok'); print('2 warnings', file=sys.stderr)"],
                capture_output=True,
                text=True,
            )
            print(f"{completed.returncode=}")
            print(f"{completed.stdout=}")
            print(f"{completed.stderr=}")
            print(f"{completed.args[1:]=}")
            """
        ),
        md(
            """
            **`check=True`** raises `CalledProcessError` on a non-zero exit code (the exception
            carries `returncode`, `stdout` and `stderr`), so failures cannot be ignored by
            accident. Without it you must test `returncode` yourself.
            """
        ),
        code(
            r"""
            try:
                subprocess.run(
                    [sys.executable, "-c", "import sys; sys.exit('database migration failed')"],
                    capture_output=True,
                    text=True,
                    check=True,
                )
            except subprocess.CalledProcessError as error:
                print(f"{type(error).__name__}: exit {error.returncode}, stderr={error.stderr.strip()!r}")
            """
        ),
        md(
            """
            **`timeout=`** kills the child if it runs too long and raises `TimeoutExpired`.
            Always set one for programs that talk to the network or might hang.
            """
        ),
        code(
            r"""
            started = time.monotonic()
            try:
                subprocess.run([sys.executable, "-c", "import time; time.sleep(10)"], timeout=0.5)
            except subprocess.TimeoutExpired as error:
                print(
                    f"{type(error).__name__}: {error.timeout=}s, "
                    f"gave up after ~{time.monotonic() - started:.1f}s"
                )
            """
        ),
        md(
            """
            `input=` sends data to the child's stdin, `cwd=` sets its working folder and
            `env=` its environment (start from `os.environ` and add to it; an `env` without
            `PATH` breaks most programs).
            """
        ),
        code(
            r"""
            counter = (
                "import os, sys; lines = sys.stdin.read().splitlines(); "
                "print(os.environ['SHOP_REGION'], os.getcwd().endswith('data'), len(lines))"
            )
            completed = subprocess.run(
                [sys.executable, "-c", counter],
                input="TEA-500\nMUG-02\nJAR-750\n",
                cwd=sample_root / "data",
                env={**os.environ, "SHOP_REGION": "west"},
                capture_output=True,
                text=True,
                check=True,
            )
            print(f"{completed.stdout.strip()=}")
            """
        ),
        md(
            """
            **`Popen`** is the lower-level class `run` is built on. Use it to **stream** output
            while the child runs (a progress log, a long build), to talk to a child
            interactively, or to connect two processes with a pipe. `poll()` checks without
            waiting, `wait()` waits, `communicate()` sends input and collects all output.
            """
        ),
        code(
            r"""
            worker = (
                "import time\nfor step in range(1, 4):\n"
                "    print(f'imported batch {step}/3', flush=True)\n    time.sleep(0.1)\n"
            )
            with subprocess.Popen([sys.executable, "-c", worker], stdout=subprocess.PIPE, text=True) as process:
                print(f"running: {process.poll() is None}")
                for line in process.stdout:
                    print(f"  live: {line.rstrip()}")
            print(f"{process.returncode=}")

            producer = subprocess.Popen(
                [sys.executable, "-c", "print('TEA-500\\nMUG-02\\nTEA-500')"], stdout=subprocess.PIPE
            )
            consumer = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    "import sys, collections; print(dict(collections.Counter(sys.stdin.read().split())))",
                ],
                stdin=producer.stdout,
                stdout=subprocess.PIPE,
                text=True,
            )
            producer.stdout.close()  # so the producer gets SIGPIPE if the consumer exits early
            output, _ = consumer.communicate(timeout=30)
            producer.wait()
            print(f"pipeline (producer | consumer): {output.strip()}")
            """
        ),
        md(
            """
            **The `shell=True` injection risk.** With `shell=True` the command is a single
            string run by `/bin/sh`, so shell syntax in any part you interpolate is
            *executed*: `;`, `&&`, `$(...)`, backticks. A file name supplied by a user becomes
            a command. (`wc -c` counts bytes; the "file name" below smuggles in a second
            command, a harmless `echo` here, `rm -rf` in an attack.)
            """
        ),
        code(
            r"""
            user_supplied_name = "notes.txt; echo INJECTED: this command was not supposed to run"
            unsafe = subprocess.run(
                f"wc -c {user_supplied_name}", shell=True, capture_output=True, text=True, cwd=sample_root
            )
            print("shell=True:")
            print(textwrap.indent((unsafe.stdout + unsafe.stderr).strip(), "  "))
            safe = subprocess.run(
                ["wc", "-c", user_supplied_name], capture_output=True, text=True, cwd=sample_root
            )
            print("list form:")
            print(textwrap.indent((safe.stdout + safe.stderr).strip(), "  "))
            print(f"if you really need a shell, quote: {shlex.quote(user_supplied_name)}")
            """
        ),
        md(
            """
            In the list form the whole string is one argument, a (non-existent) file name, and
            no shell ever sees it. Rules: pass a list; never build a shell string from input;
            if you need shell features (pipes, globbing), do them in Python (`Popen` pipes,
            `Path.glob`) or `shlex.quote` every interpolated value. ruff's `S602`/`S604`
            rules flag `shell=True` (4.3.10). `shutil.which("git")` finds a program before you
            run it. For many concurrent children, `asyncio.create_subprocess_exec` (Phase 5).
            """
        ),
    ]


def _datetime_cells() -> list[NotebookNode]:
    """4.4.3 Dates and times."""
    return [
        md(
            """
            ### 4.4.3 Dates and times

            A `datetime` is either **naive** (no `tzinfo`: "09:30", but where?) or **aware**
            (carries a time zone, so it denotes one exact instant). JavaScript's `Date` is
            always an instant; Python's naive datetimes are a common source of bugs. Rules:
            use aware datetimes for anything that happened or will happen, store and compute
            in **UTC**, and convert to a local zone only for display.

            Naive and aware datetimes cannot be compared or subtracted:
            """
        ),
        code(
            r"""
            naive = datetime(2026, 11, 7, 9, 30)
            aware = datetime(2026, 11, 7, 9, 30, tzinfo=UTC)
            print(f"{naive.tzinfo=}, {aware.tzinfo=}, {aware.utcoffset()=}")
            print(f"{naive.isoformat()=}, {aware.isoformat()=}")
            print(raised_message(lambda: naive < aware))
            print(raised_message(lambda: aware - naive))
            """
        ),
        md(
            """
            **Getting "now".** `datetime.now(UTC)` gives an aware UTC timestamp.
            `datetime.utcnow()` returned a **naive** datetime that merely happened to show UTC,
            and is deprecated since 3.12. This unit never prints the real time; it uses
            `FIXED_MOMENT` (in real code, inject a clock, Unit 4.3.5).
            """
        ),
        code(
            r"""
            print(f"{datetime.now(UTC).tzinfo=}  (the value itself changes every run)")
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                legacy = datetime.utcnow()
            print(f"{legacy.tzinfo=}, warning: {caught[0].category.__name__}: {str(caught[0].message)[:60]}...")
            """
        ),
        md(
            """
            **`zoneinfo`** (3.9+) provides real time zones from the IANA database (the system's,
            or the `tzdata` package on Windows). India Standard Time is `Asia/Kolkata`: UTC+05:30
            all year, no daylight saving. `astimezone(zone)` converts an instant to another
            zone; the instant stays the same, only the wall-clock reading changes.
            """
        ),
        code(
            r"""
            meeting_ist = datetime(2026, 11, 7, 15, 0, tzinfo=IST)
            print(f"{meeting_ist.isoformat()=}, {meeting_ist.tzname()=}, {meeting_ist.utcoffset()=}")
            print(f"{meeting_ist.astimezone(UTC).isoformat()=}")
            for zone in (LONDON, NEW_YORK):
                local = meeting_ist.astimezone(zone)
                print(f"  {str(zone):<17} {local:%a %d %b %H:%M} {local.tzname()}")
            print(f"{meeting_ist == meeting_ist.astimezone(NEW_YORK)=}  (same instant)")
            """
        ),
        md(
            """
            **Store UTC, display local.** Databases, logs and APIs should hold UTC (or an ISO
            8601 string with an offset); convert at the edges. A naive `replace(tzinfo=...)`
            *labels* a datetime without converting it, which is right only when you know the
            naive value was in that zone.
            """
        ),
        code(
            r"""
            order_placed_utc = FIXED_MOMENT
            stored = order_placed_utc.isoformat()
            print(f"{stored=}  (what goes into the database)")
            loaded = datetime.fromisoformat(stored)
            print(f"shown to an Indian customer: {loaded.astimezone(IST):%d %b %Y, %I:%M %p %Z}")
            form_input = datetime(2026, 11, 7, 15, 0)  # naive, typed by a user in Pune
            print(f"{form_input.replace(tzinfo=IST).astimezone(UTC).isoformat()=}  (label, then convert)")
            print(f"{form_input.replace(tzinfo=UTC).isoformat()=}  (wrong label: 5h30m off)")
            """
        ),
        md(
            """
            **`timedelta`** is a duration (days, seconds, microseconds internally). Adding it to
            a datetime moves it; subtracting two datetimes gives one. `total_seconds()` gives
            the whole duration as a float; dividing two timedeltas gives a ratio.
            """
        ),
        code(
            r"""
            delivery_window = timedelta(days=2, hours=6)
            print(f"{delivery_window=}, {delivery_window.total_seconds()=}")
            print(f"{FIXED_MOMENT + delivery_window=}")
            print(f"{timedelta(hours=25)=}  (normalized to days + seconds)")
            print(
                f"{date(2026, 12, 25) - date(2026, 11, 7)=}, {(date(2026, 12, 25) - date(2026, 11, 7)).days=}"
            )
            print(
                f"{timedelta(hours=8) / timedelta(minutes=45)=}, {timedelta(hours=8) // timedelta(minutes=45)=}"
            )
            """
        ),
        *predict_cells(
            """
            from datetime import timedelta

            print(timedelta(hours=-1))
            """,
            """
            `-1 day, 23:00:00`. A `timedelta` is normalized so that only `days` can be negative;
            `seconds` is always `0 <= s < 86400`. Minus one hour is stored as minus one day plus
            23 hours. Use `total_seconds()` (`-3600.0`) when you need the plain number.
            """,
            """
            print(timedelta(hours=-1), timedelta(hours=-1).total_seconds())
            """,
        ),
        md(
            """
            **DST pitfalls.** Zones with daylight saving time skip an hour in spring and repeat
            one in autumn. In New York in 2026 clocks jump from 02:00 to 03:00 on 8 March and
            fall back from 02:00 to 01:00 on 1 November. Three consequences:

            1. **Non-existent times.** 02:30 on 8 March never happens there. `ZoneInfo` still
               builds the datetime, with an offset that does not round-trip; detect it by
               converting to UTC and back.
            2. **Ambiguous times.** 01:30 on 1 November happens twice. `fold=0` picks the
               first (EDT, -04:00), `fold=1` the second (EST, -05:00).
            3. **Arithmetic is wall-clock arithmetic** within one zone: adding `timedelta(days=1)`
               keeps the local time and changes the offset, so only 23 hours pass across the
               spring change. Subtracting two datetimes **with the same `tzinfo`** also ignores
               the offset change. Convert to UTC for elapsed time.
            """
        ),
        code(
            r"""
            gap = datetime(2026, 3, 8, 2, 30, tzinfo=NEW_YORK)
            round_trip = gap.astimezone(UTC).astimezone(NEW_YORK)
            print(
                f"non-existent: {gap.isoformat()} -> {round_trip.isoformat()} "
                f"(exists: {gap.replace(tzinfo=None) == round_trip.replace(tzinfo=None)})"
            )

            first = datetime(2026, 11, 1, 1, 30, tzinfo=NEW_YORK, fold=0)
            second = first.replace(fold=1)
            print(
                f"ambiguous: fold=0 {first.isoformat()} {first.tzname()}, "
                f"fold=1 {second.isoformat()} {second.tzname()}"
            )

            saturday_noon = datetime(2026, 3, 7, 12, 0, tzinfo=NEW_YORK)
            sunday_noon = saturday_noon + timedelta(days=1)
            print(f"{sunday_noon.isoformat()=}")
            print(f"same-zone subtraction: {sunday_noon - saturday_noon}")
            print(f"real elapsed (UTC):    {sunday_noon.astimezone(UTC) - saturday_noon.astimezone(UTC)}")
            """
        ),
        md(
            """
            **ISO 8601** is the interchange format: `2026-11-07T09:30:00+00:00`.
            `isoformat()` writes it (`timespec=` controls precision), `fromisoformat()` reads it
            (since 3.11 almost any ISO 8601 form, including a trailing `Z`).
            `isocalendar()` gives ISO year, week and weekday (weeks start on Monday).
            """
        ),
        code(
            r"""
            print(f"{FIXED_MOMENT.isoformat()=}")
            print(f"{FIXED_MOMENT.isoformat(timespec='minutes')=}, {FIXED_MOMENT.date().isoformat()=}")
            print(f"{datetime.fromisoformat('2026-11-07T09:30:00Z')=}")
            print(f"{datetime.fromisoformat('2026-11-07T15:00+05:30').astimezone(UTC)=}")
            print(f"{date.fromisoformat('2026-11-07').isocalendar()=}")
            """
        ),
        md(
            """
            **`strftime` / `strptime`** format and parse with codes (the same codes as C):

            | Code | Meaning | Example |
            | --- | --- | --- |
            | `%Y` `%m` `%d` | year, month, day (zero-padded) | `2026` `11` `07` |
            | `%H` `%M` `%S` `%f` | hour (24h), minute, second, microsecond | `09` `30` `00` `000000` |
            | `%I` `%p` | hour (12h), AM/PM | `09` `AM` |
            | `%a` `%A` `%b` `%B` | weekday and month names (locale-dependent) | `Sat` `Saturday` `Nov` `November` |
            | `%j` | day of the year | `311` |
            | `%z` `%Z` | UTC offset, zone name | `+0000` `UTC` |
            | `%%` | a literal `%` | `%` |

            f-strings accept the same codes after a colon: `f"{moment:%d %b %Y}"`.
            `strptime` returns a naive datetime unless the text has `%z`. *New in 3.14:*
            `date.strptime` and `time.strptime` classmethods.
            """
        ),
        code(
            r"""
            print(f"{FIXED_MOMENT.strftime('%A %d %B %Y, %H:%M %Z')=}")
            print(f"{FIXED_MOMENT:%Y-%m-%d %I:%M %p (day %j)}")
            parsed = datetime.strptime("07/11/2026 15:00 +0530", "%d/%m/%Y %H:%M %z")
            print(f"{parsed=}, {parsed.astimezone(UTC).isoformat()=}")
            print(raised_message(lambda: datetime.strptime("2026-13-01", "%Y-%m-%d")))
            if sys.version_info >= (3, 14):
                print(f"New in 3.14: {date.strptime('07 Nov 2026', '%d %b %Y')=}")
            """
        ),
        md(
            """
            **Measuring time: `time.monotonic` vs `perf_counter` (vs `time.time`).**
            `time.time()` is the wall clock: it can jump when NTP corrects it or an
            administrator changes it, so never use it for durations. `monotonic()` never goes
            backwards: use it for timeouts and deadlines. `perf_counter()` is monotonic with
            the highest available resolution: use it for benchmarks. Their absolute values
            mean nothing; only differences do. (The clock details below vary by OS; on Linux
            both use `CLOCK_MONOTONIC`.)
            """
        ),
        code(
            r"""
            for clock_name in ("time", "monotonic", "perf_counter"):
                info = time.get_clock_info(clock_name)
                print(
                    f"{clock_name:<13} monotonic={info.monotonic!s:<5} "
                    f"adjustable={info.adjustable!s:<5} resolution={info.resolution:g}"
                )

            deadline = time.monotonic() + 0.2  # a timeout: monotonic
            started = time.perf_counter()  # a measurement: perf_counter
            while time.monotonic() < deadline:
                time.sleep(0.01)
            print(f"waited about {time.perf_counter() - started:.1f} s")
            """
        ),
    ]


def _regex_cells() -> list[NotebookNode]:
    """4.4.4 Regular expressions."""
    return [
        md(
            r"""
            ### 4.4.4 Regular expressions (`re`)

            Write patterns as **raw strings** (`r"\d+"`) so backslashes reach `re` unchanged.
            Three functions differ only in *where* the match must be:

            | Function | Matches | JS equivalent |
            | --- | --- | --- |
            | `re.match(p, s)` | at the **start** of `s` | `/^p/.exec(s)` |
            | `re.search(p, s)` | **anywhere** in `s` (first match) | `/p/.exec(s)` |
            | `re.fullmatch(p, s)` | the **whole** of `s` | `/^p$/.test(s)` |

            They return a `Match` object or `None`.
            """
        ),
        code(
            r"""
            order_text = "Order 42 shipped on 2026-11-07"
            print(f"{re.match(r'\d+', order_text)=}")
            print(f"{re.search(r'\d+', order_text)=}")
            print(f"{re.fullmatch(r'\d+', '42')=}, {re.fullmatch(r'\d+', '42a')=}")
            found = re.search(r"\d{4}-\d{2}-\d{2}", order_text)
            print(f"{found.group()=}, {found.start()=}, {found.end()=}, {found.span()=}")
            """
        ),
        *predict_cells(
            """
            import re

            print(re.match(r"\\d+", "SKU 42"), re.search(r"\\d+", "SKU 42").group())
            """,
            """
            `None 42`. `re.match` only tries at position 0, where `S` is not a digit; it is
            not "match anywhere" as in JavaScript's `String.prototype.match`. `re.search` scans
            and finds `42`.
            """,
            r"""
            print(re.match(r"\d+", "SKU 42"), re.search(r"\d+", "SKU 42").group())
            """,
        ),
        md(
            """
            **All matches: `findall` and `finditer`.** `findall` returns a list of strings (or
            of tuples when the pattern has several groups); `finditer` yields `Match` objects
            lazily, with positions. Python has no `g` flag: these functions are "global" by
            design.
            """
        ),
        code(
            r"""
            invoice = "TEA-500 x2 @240, MUG-02 x1 @199, JAR-750 x3 @350"
            print(f"{re.findall(r'[A-Z]{3}-\d+', invoice)=}")
            print(f"{re.findall(r'([A-Z]{3}-\d+) x(\d+)', invoice)=}")
            for line_match in re.finditer(r"@(\d+)", invoice):
                print(f"  price {line_match.group(1)} at {line_match.span()}")
            """
        ),
        md(
            """
            **Groups and named groups.** Parentheses capture; `(?P<name>...)` names a group
            (Python syntax; JavaScript's `(?<name>...)` is a syntax error in Python's `re`),
            `(?:...)` groups without capturing. `groupdict()` returns the named groups as a
            dict; `(?P=name)` matches the same text again.
            """
        ),
        code(
            r"""
            line_pattern = re.compile(r"(?P<sku>[A-Z]{3}-\d+) x(?P<quantity>\d+) @(?P<price>\d+)")
            first_line = line_pattern.search(invoice)
            print(f"{first_line.group('sku')=}, {first_line['quantity']=}, {first_line.groups()=}")
            print(f"{first_line.groupdict()=}")
            print(f"{re.findall(r'(?:TEA|MUG)-(\d+)', invoice)=}  (non-capturing group)")
            print(f"{re.search(r'(?P<word>\b\w+\b) (?P=word)', 'please ship ship today').group()=}")
            print(raised_message(lambda: re.compile(r"(?<sku>[A-Z]+)")))
            """
        ),
        md(
            """
            **Lazy quantifiers.** `*`, `+`, `?` and `{m,n}` are **greedy**: they take as much as
            possible and give back only if the rest fails. Adding `?` (`*?`, `+?`) makes them
            **lazy**: as little as possible.
            """
        ),
        code(
            r"""
            html = "<b>Masala tea</b> and <b>Steel mug</b>"
            print(f"{re.findall(r'<b>(.*)</b>', html)=}   greedy")
            print(f"{re.findall(r'<b>(.*?)</b>', html)=}   lazy")
            print(f"{re.findall(r'<b>([^<]*)</b>', html)=}   negated class (often the best choice)")
            """
        ),
        md(
            r"""
            **Anchors.** `^` and `$` match at the start and end of the string (and of each line
            with `re.MULTILINE`); `\A` and `\Z` always mean the whole string; `\b` is a word
            boundary. Python's `$` also matches **before a final newline**, so validate input
            with `fullmatch` or `\Z`.
            """
        ),
        code(
            r"""
            log = "ERROR disk full\nINFO started\nERROR timeout"
            print(f"{re.findall(r'^ERROR (.+)$', log)=}  (no MULTILINE: none)")
            print(f"{re.findall(r'^ERROR (.+)$', log, re.MULTILINE)=}")
            print(f"{bool(re.match(r'\d{6}$', '411001\n'))=}  ($ before a trailing newline)")
            print(f"{bool(re.match(r'\d{6}\Z', '411001\n'))=}, {bool(re.fullmatch(r'\d{6}', '411001\n'))=}")
            print(f"{re.findall(r'\bcat\b', 'cat category concat cat.')=}")
            """
        ),
        md(
            """
            **Flags** change how the pattern is read: `re.IGNORECASE` (`re.I`), `re.MULTILINE`
            (`re.M`), `re.DOTALL` (`re.S`: `.` also matches newlines), `re.ASCII` (`re.A`:
            `\\d`, `\\w`, `\\b` ASCII-only), `re.VERBOSE` (`re.X`). Combine with `|`, or put them
            inline at the start of the pattern: `(?i)`, `(?m)`, `(?s)`.
            """
        ),
        code(
            r"""
            note = "Coupon: diwali10\nvalid till Nov"
            print(f"{re.findall(r'coupon: (\w+)', note)=}, {re.findall(r'coupon: (\w+)', note, re.I)=}")
            print(f"{re.search(r'Coupon.*Nov', note)=}, {re.search(r'Coupon.*Nov', note, re.S).group()!r}")
            print(f"{re.findall(r'(?i)NOV', note)=}  (inline flag)")
            print(f"{re.findall(r'\d+', 'Order ४२ and 42')=}, {re.findall(r'\d+', 'Order ४२ and 42', re.A)=}")
            """
        ),
        md(
            """
            **`re.VERBOSE`** ignores whitespace in the pattern and allows `#` comments, so a
            long pattern can be laid out and explained. Spaces you *want* to match must be
            escaped (`\\ `) or written as `[ ]` or `\\s`. `re.compile` once, reuse many times
            (Python caches recently used patterns too).
            """
        ),
        code(
            r'''
            PHONE_PATTERN = re.compile(
                r"""
                ^(?:\+91[ -]?)?        # optional country code
                (?P<operator>[6-9]\d{4})  # mobile numbers start with 6-9
                [ -]?                  # optional separator
                (?P<subscriber>\d{5})$
                """,
                re.VERBOSE,
            )
            for phone in ("+91 98765 43210", "9876543210", "+91-98765-43210", "12345 67890"):
                phone_match = PHONE_PATTERN.match(phone)
                print(f"  {phone:<17} {phone_match.groupdict() if phone_match else None}")
            print(f"{bool(PHONE_PATTERN.flags & re.VERBOSE)=}, {PHONE_PATTERN.groupindex=}")
            '''
        ),
        md(
            """
            **Lookarounds** check what comes before or after **without consuming it**:
            `(?=...)` lookahead, `(?!...)` negative lookahead, `(?<=...)` lookbehind, `(?<!...)`
            negative lookbehind. Python requires lookbehinds to be **fixed-width** (JavaScript
            allows variable width).
            """
        ),
        code(
            r"""
            prices = "₹240, $3, ₹1,199 and 15 items"
            print(f"{re.findall(r'(?<=₹)\d+(?:,\d+)*', prices)=}   lookbehind: amounts after ₹")
            print(f"{re.findall(r'\d+(?= items)', prices)=}   lookahead: the number before ' items'")
            print(
                f"{re.findall(r'\b\d+\b(?!,| items)', prices)=}"
                "   negative lookahead: not before ',' or ' items'"
            )
            strong = re.compile(r"^(?=.*[A-Z])(?=.*\d)(?=.*[^\w\s]).{10,}$")
            for password in ("chai-time-2026", "Chai-time-2026", "Ch@i1"):
                print(f"  {password:<16} strong={bool(strong.match(password))}")
            print(raised_message(lambda: re.compile(r"(?<=₹\s*)\d+")))
            """
        ),
        md(
            """
            **`sub` with a function.** `re.sub(pattern, replacement, text)` replaces every
            match; the replacement can use `\\1` or `\\g<name>` (JavaScript: `$1`, `$<name>`),
            or be a **function** that receives each `Match` and returns the replacement text.
            `subn` also returns the count; `re.split` splits on a pattern.
            """
        ),
        code(
            r"""
            print(f"{re.sub(r'(\d{4})-(\d{2})-(\d{2})', r'\3/\2/\1', 'due 2026-11-07')=}")
            print(f"{re.sub(r'(?P<sku>[A-Z]{3})-(?P<n>\d+)', r'\g<sku>#\g<n>', 'TEA-500 MUG-02')=}")


            def mask_card(card_match: re.Match[str]) -> str:
                digits = re.sub(r"\D", "", card_match.group())
                return "**** **** **** " + digits[-4:]


            print(f"{re.sub(r'\b(?:\d{4}[ -]?){3}\d{4}\b', mask_card, 'card 4111 1111 1111 1234 ok')=}")
            print(f"{re.subn(r'\s+', ' ', 'too    many   spaces')=}")
            print(f"{re.split(r'[;,]\s*', 'tea, mug;jar,  spoon')=}")
            """
        ),
        md(
            """
            **Catastrophic backtracking.** Python's `re` is a backtracking engine (like
            JavaScript's). Nested quantifiers such as `(a+)+` can match the same text in
            exponentially many ways, so a *failing* match tries them all: each extra character
            roughly doubles the time. With user-controlled input this is a denial-of-service
            hole (ReDoS). Timings below vary by machine; the doubling does not.
            """
        ),
        code(
            r"""
            nested = re.compile(r"(a+)+$")
            for length in (16, 18, 20, 22):
                started = time.perf_counter()
                nested.match("a" * length + "!")
                print(f"  length {length}: {(time.perf_counter() - started) * 1000:8.1f} ms")
            """
        ),
        md(
            """
            The fixes: remove the nesting (`a+$` means the same here), or use a
            **possessive** quantifier `a++` or an **atomic group** `(?>...)` (*New in 3.11*),
            which never give back what they matched. Both are linear even for 50,000
            characters. For untrusted patterns, the third-party `regex` module supports a
            `timeout`.
            """
        ),
        code(
            r"""
            attack = "a" * 50_000 + "!"
            for pattern in (r"a+$", r"(a++)+$", r"(?>a+)+$"):
                started = time.perf_counter()
                result = re.match(pattern, attack)
                print(f"  {pattern:<10} {result=}, fast: {time.perf_counter() - started < 0.1}")
            """
        ),
        md(
            r"""
            **JavaScript regex differences**, each shown in a cell above or below:

            | Topic | JavaScript | Python |
            | --- | --- | --- |
            | Literal | `/\d+/g` | `re.compile(r"\d+")` (raw string) |
            | All matches | `g` flag + `matchAll` | `findall` / `finditer` (no `g` flag) |
            | Named group | `(?<name>...)` | `(?P<name>...)` |
            | Replacement | `$1`, `$<name>` | `\1`, `\g<name>` (or a function) |
            | `\d`, `\w` | ASCII only | Unicode by default (`re.ASCII` for ASCII) |
            | `$` | end of string | end, **or before a final `\n`** (use `\Z` / `fullmatch`) |
            | Lookbehind | variable width allowed | fixed width only |
            | Sticky `y` flag | `re.lastIndex` | `pattern.match(text, pos)` |
            | Possessive / atomic | not supported | `a++`, `(?>...)` (3.11+) |
            | Start-only match | (none) | `re.match` |

            The sticky-flag equivalent: a compiled pattern's `match(text, pos)` anchors at
            `pos`, which is how simple tokenizers are written:
            """
        ),
        code(
            r"""
            TOKEN = re.compile(r"\s*(?:(?P<number>\d+)|(?P<operator>[+*-]))")
            expression, position, tokens = "12 + 30 * 2", 0, []
            while position < len(expression):
                token = TOKEN.match(expression, position)
                tokens.append((token.lastgroup, token.group(token.lastgroup)))
                position = token.end()
            print(tokens)
            """
        ),
        md(
            """
            **Under the hood: the compiled pattern.** `re.compile` parses the pattern into a
            tree of opcodes for the C matching engine; `re.DEBUG` prints that tree, which shows
            how quantifiers and groups are represented (`MAX_REPEAT`, `SUBPATTERN`,
            `POSSESSIVE_REPEAT`). The output goes to stdout, captured here.
            """
        ),
        code(
            r"""
            parse_tree = io.StringIO()
            with contextlib.redirect_stdout(parse_tree):
                re.compile(r"(?P<sku>[A-Z]{3})-\d++", re.DEBUG)
            print("\n".join(parse_tree.getvalue().splitlines()[:12]))
            print(f"{re.compile(r'\d+') is re.compile(r'\d+')=}  (re caches compiled patterns)")
            """
        ),
    ]


def _format_cells() -> list[NotebookNode]:
    """4.4.5 Data formats."""
    return [
        md(
            """
            ### 4.4.5 Data formats

            **`json`.** `dumps`/`loads` work with strings, `dump`/`load` with files. Python
            types map to JSON as `dict`→object, `list`/`tuple`→array, `str`, `int`/`float`→number,
            `True`/`False`/`None`→`true`/`false`/`null`. Options worth knowing: `indent`,
            `sort_keys`, `ensure_ascii=False` (keep `₹` readable), `separators` for compact
            output. Errors carry the line and column.
            """
        ),
        code(
            r"""
            order = {
                "id": 7,
                "customer": "Asha",
                "items": [("TEA-500", 2)],
                "paid": True,
                "note": None,
                "currency": "₹",
            }
            print(json.dumps(order))
            print(json.dumps(order, ensure_ascii=False, sort_keys=True, indent=2))
            print(json.dumps(order, separators=(",", ":"), ensure_ascii=False))
            print(f"{json.loads(json.dumps(order))['items']=}  (tuples come back as lists)")
            print(raised_message(lambda: json.loads('{"id": 7, "paid": true,}')))
            """
        ),
        md(
            """
            **Custom encoders.** `json` refuses types it does not know (`Decimal`, `datetime`,
            `set`, dataclasses, enums). Either pass `default=function` (called for each unknown
            object, returns something serializable) or subclass `JSONEncoder` and override
            `default`. Decide deliberately how each type is represented: money as a
            **string** keeps every digit.
            """
        ),
        code(
            r"""
            class OrderStatus(enum.StrEnum):
                PAID = "paid"
                SHIPPED = "shipped"


            @dataclasses.dataclass
            class OrderLine:
                sku: str
                quantity: int
                unit_price: Decimal


            class ShopEncoder(json.JSONEncoder):
                def default(self, value: object) -> object:
                    if isinstance(value, Decimal):
                        return str(value)
                    if isinstance(value, datetime | date):
                        return value.isoformat()
                    if isinstance(value, set | frozenset):
                        return sorted(value)
                    if dataclasses.is_dataclass(value) and not isinstance(value, type):
                        return dataclasses.asdict(value)
                    return super().default(value)  # raises TypeError for anything else


            shipment = {
                "placed_at": FIXED_MOMENT,
                "status": OrderStatus.SHIPPED,
                "tags": {"gift", "express"},
                "lines": [OrderLine("TEA-500", 2, Decimal("240.00"))],
                "total": Decimal("480.00"),
            }
            print(raised_message(lambda: json.dumps(shipment)))
            print(json.dumps(shipment, cls=ShopEncoder))
            print(raised_message(lambda: json.dumps({"lock": io.StringIO()}, cls=ShopEncoder)))
            """
        ),
        md(
            """
            **`object_hook`** is the decoding counterpart: it is called with every decoded JSON
            object (dict) and can return anything, for example turning ISO strings back into
            datetimes or tagged dicts into your own classes. (`object_pairs_hook` receives the
            key-value pairs in order, e.g. to reject duplicate keys.)
            """
        ),
        code(
            r'''
            def decode_shop(obj: dict[str, object]) -> object:
                """Revive datetimes and order lines from their JSON form."""
                if "placed_at" in obj:
                    obj["placed_at"] = datetime.fromisoformat(str(obj["placed_at"]))
                if obj.keys() == {"sku", "quantity", "unit_price"}:
                    return OrderLine(str(obj["sku"]), int(obj["quantity"]), Decimal(str(obj["unit_price"])))
                return obj


            revived = json.loads(json.dumps(shipment, cls=ShopEncoder), object_hook=decode_shop)
            print(f"{revived['placed_at']=}")
            print(f"{revived['lines']=}")


            def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
                keys = [key for key, _ in pairs]
                if len(keys) != len(set(keys)):
                    raise ValueError(f"duplicate keys in {keys}")
                return dict(pairs)


            print(f"{json.loads('{\"qty\": 1, \"qty\": 5}')=}  (last one silently wins)")
            print(
                raised_message(lambda: json.loads('{"qty": 1, "qty": 5}', object_pairs_hook=reject_duplicates))
            )
            '''
        ),
        md(
            """
            **`parse_float=Decimal`.** By default JSON numbers with a decimal point become
            `float`, with the usual binary rounding (`0.1 + 0.2`). For money, parse them
            straight into `Decimal` so no digit is ever lost (JavaScript's `JSON.parse` has no
            such option). `parse_int` does the same for integers.
            """
        ),
        code(
            r"""
            payload = '{"items": [{"price": 0.1}, {"price": 0.2}], "discount": 0.3}'
            as_floats = json.loads(payload)
            as_decimals = json.loads(payload, parse_float=Decimal)
            print(f"{sum(item['price'] for item in as_floats['items'])=}")
            print(f"{sum(item['price'] for item in as_decimals['items'])=}")
            print(f"{sum(item['price'] for item in as_decimals['items']) == as_decimals['discount']=}")
            print(f"{json.loads('{\"id\": 12345678901234567890}')['id']=}  (Python ints never overflow)")
            """
        ),
        md(
            """
            **`csv`.** `csv.DictWriter` writes dicts as rows (`fieldnames` fixes the column
            order; `writeheader()` writes the first row); `csv.DictReader` yields one dict per
            row, keyed by the header. Everything read back is a **string**: convert types
            yourself. Always open CSV files with **`newline=""`** (explained below).
            """
        ),
        code(
            r"""
            csv_path = UNIT44_DIR / "orders.csv"
            rows = [
                {
                    "order_id": 7,
                    "customer": "Asha Rao",
                    "total": Decimal("679.00"),
                    "note": 'gift wrap, "fragile"',
                },
                {"order_id": 8, "customer": "Ravi", "total": Decimal("240.00"), "note": ""},
            ]
            with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
                writer = csv.DictWriter(csv_file, fieldnames=["order_id", "customer", "total", "note"])
                writer.writeheader()
                writer.writerows(rows)
            print(csv_path.read_text(encoding="utf-8"))
            with csv_path.open(newline="", encoding="utf-8") as csv_file:
                loaded_rows = list(csv.DictReader(csv_file))
            print(f"{loaded_rows[0]=}")
            print(f"{sum(Decimal(row['total']) for row in loaded_rows)=}")
            """
        ),
        md(
            """
            Note the quoting in the printed file: the `note` field contains a comma and quotes,
            so the writer wrapped it in quotes and doubled the inner ones. `DictWriter` refuses keys not in `fieldnames` unless
            `extrasaction="ignore"`; other dialects (`csv.excel_tab`, `delimiter=";"`) and
            `quoting=csv.QUOTE_NONNUMERIC` cover the variants you meet in practice.

            **Why `newline=""`.** A quoted CSV field may contain line breaks, and the CSV
            format uses `\\r\\n` between rows. Text mode normally translates line endings, which
            corrupts both: on reading, an embedded `\\r\\n` becomes `\\n`; on writing on
            Windows, every `\\r\\n` becomes `\\r\\r\\n` (blank rows in Excel). `newline=""` turns
            the translation off and lets the `csv` module handle line endings itself.
            """
        ),
        code(
            r"""
            address_path = UNIT44_DIR / "addresses.csv"
            with address_path.open("w", newline="", encoding="utf-8") as csv_file:
                csv.writer(csv_file).writerow(["Asha", "Flat 4\r\nMG Road\r\nPune"])
            print(f"{address_path.read_bytes()=}")
            with address_path.open(encoding="utf-8") as csv_file:  # wrong
                print(f"without newline='': {next(csv.reader(csv_file))[1]!r}")
            with address_path.open(newline="", encoding="utf-8") as csv_file:  # right
                print(f"with newline='':    {next(csv.reader(csv_file))[1]!r}")
            print(
                raised_message(
                    lambda: csv.DictWriter(io.StringIO(), fieldnames=["a"]).writerow({"a": 1, "b": 2})
                )
            )
            """
        ),
    ]


def _algorithm_cells() -> list[NotebookNode]:
    """4.4.6 Algorithm helpers."""
    return [
        md(
            """
            ### 4.4.6 Algorithm helpers

            **`heapq`** keeps a plain list arranged as a binary **min-heap**: `heap[0]` is
            always the smallest item, `heappush` and `heappop` are O(log n). That makes a
            **priority queue**. Store tuples `(priority, sequence, item)`: the sequence number
            breaks ties in insertion order and stops Python from ever comparing the items
            themselves (dicts cannot be compared).
            """
        ),
        code(
            r"""
            import itertools

            task_queue: list[tuple[int, int, dict[str, str]]] = []
            sequence = itertools.count()
            for priority, task in [
                (2, {"job": "send invoice"}),
                (1, {"job": "refund order 8"}),
                (3, {"job": "weekly report"}),
                (1, {"job": "restock TEA-500"}),
            ]:
                heapq.heappush(task_queue, (priority, next(sequence), task))
            print(f"{task_queue[0]=}  (smallest first)")
            while task_queue:
                priority, _, task = heapq.heappop(task_queue)
                print(f"  priority {priority}: {task['job']}")
            print(raised_message(lambda: heapq.heappush([(1, {"a": 1})], (1, {"b": 2}))))
            """
        ),
        md(
            """
            `heapify` turns a list into a heap in O(n). `nlargest(k, items, key=)` and
            `nsmallest` find the top k in O(n log k) without sorting everything (for k = 1 use
            `max`/`min`; for k close to n, `sorted`). `heappushpop` keeps a bounded heap;
            `heapq.merge` lazily merges already-sorted inputs. *New in 3.14:* `heappush_max`,
            `heappop_max`, `heapify_max` for max-heaps (before, you negated the priorities).
            """
        ),
        code(
            r"""
            sales = {"TEA-500": 480, "MUG-02": 199, "JAR-750": 1050, "SPOON-1": 60, "KETTLE-9": 899}
            print(f"{heapq.nlargest(3, sales.items(), key=lambda item: item[1])=}")
            print(f"{heapq.nsmallest(2, sales, key=sales.get)=}")
            numbers = [9, 4, 7, 1, 8]
            heapq.heapify(numbers)
            print(f"{numbers=}  (heap order, not sorted)")
            print(f"{list(heapq.merge([1, 4, 9], [2, 3, 10], [5]))=}")
            if sys.version_info >= (3, 14):
                max_heap = [3, 9, 1]
                heapq.heapify_max(max_heap)
                print(f"New in 3.14: {heapq.heappop_max(max_heap)=}")
            """
        ),
        md(
            """
            **Under the hood: a C accelerator with a Python fallback.** `heapq` is written in
            Python, but at import time it replaces its functions with C versions from `_heapq`
            when available. The pure-Python helpers remain, and `inspect` can show them: a
            push appends at the end, then sifts the new item up towards the root.
            """
        ),
        code(
            r"""
            print(f"{heapq.heappush.__module__=}, {type(heapq.heappush).__name__=}")
            print(inspect.getsource(heapq._siftdown))
            """
        ),
        md(
            """
            **`bisect`** finds positions in a **sorted** list by binary search, O(log n):
            `bisect_left` / `bisect_right` (where an item would go), `insort` (insert keeping
            order). The classic use: mapping a number to a band, such as income-tax slabs or
            shipping rates. `key=` (*New in 3.10*) searches records by a field.
            """
        ),
        code(
            r'''
            slab_limits = [400_000, 800_000, 1_200_000, 1_600_000, 2_000_000, 2_400_000]  # rupees
            slab_rates = [0, 5, 10, 15, 20, 25, 30]  # percent


            def marginal_rate(income: int) -> int:
                """Rate of the slab an income falls into (illustrative new-regime slabs)."""
                return slab_rates[bisect.bisect_right(slab_limits, income)]


            print({income: marginal_rate(income) for income in (300_000, 400_000, 950_000, 2_500_000)})
            scores = [55, 70, 85]
            bisect.insort(scores, 77)
            print(f"{scores=}, {bisect.bisect_left(scores, 77)=}, {bisect.bisect_right(scores, 77)=}")
            orders = [(3, "MUG-02"), (5, "TEA-500"), (9, "JAR-750")]
            print(f"{bisect.bisect_left(orders, 6, key=lambda order: order[0])=}")
            '''
        ),
        md(
            """
            **`statistics`** covers descriptive statistics without NumPy: averages, spread,
            quantiles, correlation, simple linear regression and the normal distribution.
            `fmean` is the fast float mean; `mean` keeps exact types (`Decimal`, `Fraction`).
            """
        ),
        code(
            r"""
            daily_orders = [42, 38, 51, 47, 38, 60, 55, 38, 49, 52]
            print(f"{statistics.mean(daily_orders)=}, {statistics.fmean(daily_orders)=}")
            print(
                f"{statistics.median(daily_orders)=}, {statistics.mode(daily_orders)=}, "
                f"{statistics.multimode([1, 1, 2, 2])=}"
            )
            print(
                f"{statistics.stdev(daily_orders):.2f} (sample), "
                f"{statistics.pstdev(daily_orders):.2f} (population)"
            )
            print(f"{statistics.quantiles(daily_orders, n=4)=}")
            ad_spend = [10, 9, 14, 12, 8, 18, 16, 9, 13, 15]
            print(f"{statistics.correlation(ad_spend, daily_orders):.3f}")
            slope, intercept = statistics.linear_regression(ad_spend, daily_orders)
            print(f"orders ≈ {slope:.2f} × spend + {intercept:.2f}")
            delivery_days = statistics.NormalDist(mu=3, sigma=0.8)
            print(f"P(delivery within 4 days) = {delivery_days.cdf(4):.3f}")
            print(f"{statistics.mean([Decimal('0.10'), Decimal('0.20')])=}")
            """
        ),
        md(
            """
            **`math`** beyond the basics of Unit 1.3: exactly rounded float sums (`fsum`;
            *Changed in 3.12:* built-in `sum()` of floats also compensates for rounding, but
            only `fsum` is exact in every case), products,
            combinatorics (`comb`, `perm`), integer roots (`isqrt`), `gcd`/`lcm`, distances,
            `isclose` for float comparisons, and `fma` (fused multiply-add, *New in 3.13*).
            """
        ),
        code(
            r"""
            running_total = 0.0
            for _ in range(10):
                running_total += 0.1
            print(
                f"{running_total=}, {sum([0.1] * 10)=} (Changed in 3.12: compensated), {math.fsum([0.1] * 10)=}"
            )
            print(
                f"{sum([2**53, 1.0, 1.0])=}, {math.fsum([2**53, 1.0, 1.0])=}  (fsum is always exactly rounded)"
            )
            print(f"{math.prod([2, 3, 4])=}, {math.comb(10, 3)=}, {math.perm(10, 3)=}")
            print(f"{math.isqrt(10**20 + 1)=}, {math.gcd(240, 360)=}, {math.lcm(4, 6)=}")
            print(f"{math.dist((0, 0), (3, 4))=}, {math.hypot(3, 4)=}, {math.log2(1024)=}")
            print(f"{math.isclose(0.1 + 0.2, 0.3)=}, {math.ceil(4.01)=}, {math.floor(-4.5)=}")
            if sys.version_info >= (3, 13):
                print(f"New in 3.13: {math.fma(2.0, 3.0, 1.0)=}")
            """
        ),
        md(
            """
            **`graphlib.TopologicalSorter`** orders the nodes of a dependency graph so every
            node comes after its dependencies: build steps, database migrations, task
            pipelines. You give `{node: dependencies}`. `static_order()` returns one valid
            order; a cycle raises `CycleError` with the cycle in its arguments.
            """
        ),
        code(
            r"""
            build_steps = {
                "package": {"test", "docs"},
                "test": {"compile"},
                "docs": {"compile"},
                "compile": {"fetch"},
                "fetch": set(),
            }
            print(f"{list(graphlib.TopologicalSorter(build_steps).static_order())=}")
            try:
                list(graphlib.TopologicalSorter({"migrate": {"seed"}, "seed": {"migrate"}}).static_order())
            except graphlib.CycleError as error:
                print(f"{type(error).__name__}: {error.args[1]}")
            """
        ),
        md(
            """
            For **parallel** execution use the incremental API: `prepare()`, then repeatedly
            `get_ready()` (everything whose dependencies are done, which can run at the same
            time) and `done(node)` as each finishes. Sorting each batch makes the output
            deterministic.
            """
        ),
        code(
            r"""
            sorter = graphlib.TopologicalSorter(build_steps)
            sorter.prepare()
            batch_number = 0
            while sorter.is_active():
                ready = sorted(sorter.get_ready())
                batch_number += 1
                print(f"  batch {batch_number}: run {ready} in parallel")
                sorter.done(*ready)
            """
        ),
    ]


def _random_security_cells() -> list[NotebookNode]:
    """4.4.7 Randomness and security."""
    return [
        md(
            """
            ### 4.4.7 Randomness and security

            **`random`** is a Mersenne Twister pseudo-random generator: fast, good statistical
            quality, and **reproducible** with `random.seed(...)`, which is what simulations,
            sampling and tests need. Every call below follows `random.seed(42)`, so the output
            is the same on every run (for a given Python version).
            """
        ),
        code(
            r"""
            random.seed(42)
            print(f"{random.random()=:.6f}, {random.randint(1, 6)=}, {random.uniform(100, 200)=:.2f}")
            customers = ["Asha", "Ravi", "Meera", "John", "Fatima"]
            print(f"{random.choice(customers)=}")
            print(f"{random.choices(['card', 'upi', 'cash'], weights=[5, 4, 1], k=8)=}  (with replacement)")
            print(f"{random.sample(customers, 3)=}  (without replacement)")
            deck = list(range(1, 11))
            random.shuffle(deck)  # in place, returns None
            print(f"{deck=}")
            print(f"{random.gauss(mu=3, sigma=0.5)=:.3f}")
            """
        ),
        md(
            """
            A `random.Random(seed)` instance is an **independent** generator: give each
            simulation or test its own, so code elsewhere calling `random.random()` cannot
            shift its sequence.
            """
        ),
        code(
            r"""
            simulation_a, simulation_b = random.Random(7), random.Random(7)
            random.random()  # global calls do not disturb the instances
            print(f"{[simulation_a.randint(1, 100) for _ in range(3)]=}")
            print(f"{[simulation_b.randint(1, 100) for _ in range(3)]=}  (same seed, same stream)")
            """
        ),
        md(
            """
            **Never use `random` for security.** Its whole state can be reconstructed from 624
            consecutive 32-bit outputs, after which every future "random" token is predictable.
            **`secrets`** draws from the operating system's cryptographically secure source
            (`os.urandom`): use it for passwords, reset tokens, API keys, session ids. Its
            output is unpredictable by design, so this cell prints only properties.
            """
        ),
        code(
            r"""
            reset_token = secrets.token_urlsafe(32)  # 32 random bytes, URL-safe base64
            api_key = secrets.token_hex(16)  # 16 bytes as 32 hex characters
            print(
                f"{len(reset_token)=}, {set(reset_token) <= set(string.ascii_letters + string.digits + '-_')=}"
            )
            print(f"{len(api_key)=}, {all(character in string.hexdigits for character in api_key)=}")
            print(f"{secrets.token_hex(16) != secrets.token_hex(16)=}")
            otp = "".join(secrets.choice(string.digits) for _ in range(6))
            print(f"{len(otp)=}, {otp.isdigit()=}, {0 <= secrets.randbelow(10) < 10=}")
            print(f"{secrets.compare_digest('abc123', 'abc123')=}")
            """
        ),
        md(
            """
            **`hashlib`**: cryptographic hash functions. A hash is a fixed-size fingerprint of
            data: the same input always gives the same digest, any change gives a completely
            different one, and you cannot go back. `update()` hashes data in pieces (same
            result as one call), `hashlib.file_digest` (*New in 3.11*) hashes a file
            efficiently. `blake2b` is fast and supports keys and custom digest sizes.
            """
        ),
        code(
            r"""
            print(f"{hashlib.sha256(b'order 7: 679.00 INR').hexdigest()=}")
            print(f"{hashlib.sha256(b'order 7: 679.01 INR').hexdigest()[:16]=}...  (one character changed)")
            incremental = hashlib.sha256()
            for chunk in (b"order 7: ", b"679.00 INR"):
                incremental.update(chunk)
            print(f"{incremental.hexdigest() == hashlib.sha256(b'order 7: 679.00 INR').hexdigest()=}")
            with (sample_root / "docs" / "README.md").open("rb") as readme_file:
                print(f"{hashlib.file_digest(readme_file, 'sha256').hexdigest()[:16]=}...")
            print(f"{hashlib.blake2b(b'TEA-500', digest_size=8).hexdigest()=}")
            print(f"{sorted(hashlib.algorithms_guaranteed)[:6]=}")
            """
        ),
        md(
            """
            **Passwords are not hashed with plain SHA-256** (too fast: attackers try billions
            per second). Use a deliberately slow, salted key-derivation function:
            `hashlib.scrypt` or `hashlib.pbkdf2_hmac` in the standard library, or argon2
            (Phase 6 uses `pwdlib[argon2]`). The salt is random per user and stored next to the
            hash; it is fixed here only so the output is stable.
            """
        ),
        code(
            r"""
            demo_salt = b"fixed-demo-salt!"  # real code: secrets.token_bytes(16) per user
            stored_hash = hashlib.scrypt(b"correct horse battery staple", salt=demo_salt, n=2**14, r=8, p=1)
            print(f"{stored_hash.hex()[:32]=}...")
            attempt = hashlib.scrypt(b"correct horse battery staple", salt=demo_salt, n=2**14, r=8, p=1)
            print(f"{hmac.compare_digest(stored_hash, attempt)=}")
            print(f"{hashlib.pbkdf2_hmac('sha256', b'chai123', demo_salt, 600_000).hex()[:32]=}...")
            """
        ),
        md(
            """
            **`hmac`: message authentication, e.g. webhook signatures.** A payment provider
            that calls your webhook signs the request body with a secret you share:
            `HMAC-SHA256(secret, timestamp + "." + body)`. You recompute the signature and
            compare. A plain hash would not do, because anyone can hash a forged body; only
            the secret holder can produce the HMAC. Compare with **`hmac.compare_digest`**,
            which takes the same time whatever the input, so an attacker cannot learn the
            signature byte by byte from response timings. Include a timestamp to stop replays.
            """
        ),
        code(
            r"""
            webhook_secret = b"whsec_demo_only_not_a_real_secret"
            body = b'{"event": "payment.captured", "order_id": 7, "amount": 67900}'
            timestamp = int(FIXED_MOMENT.timestamp())
            signature = hmac.new(webhook_secret, f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
            print(f"X-Signature: t={timestamp},v1={signature}")


            def signature_is_valid(received_body: bytes, received_signature: str) -> bool:
                expected = hmac.new(
                    webhook_secret, f"{timestamp}.".encode() + received_body, hashlib.sha256
                ).hexdigest()
                return hmac.compare_digest(expected, received_signature)


            print(f"{signature_is_valid(body, signature)=}")
            print(f"{signature_is_valid(body.replace(b'67900', b'100'), signature)=}  (tampered amount)")
            """
        ),
        md(
            """
            **`uuid`.** `uuid4()` is 122 random bits: unique without coordination but in random
            order, which scatters database index inserts. **`uuid7()`** (*New in 3.14*, RFC
            9562) starts with a 48-bit Unix timestamp in milliseconds, so ids **sort by
            creation time** and index well; prefer it for primary keys. `uuid5` is
            deterministic (a namespace + a name), useful for stable ids derived from data.
            Random ids are shown only through their properties.
            """
        ),
        code(
            r"""
            random_id = uuid.uuid4()
            print(f"{random_id.version=}, {random_id.variant=}, {len(str(random_id))=}")
            if sys.version_info >= (3, 14):
                time_ordered = [uuid.uuid7() for _ in range(5)]
                print(f"{time_ordered == sorted(time_ordered)=}, {time_ordered[0].version=}")
                milliseconds = time_ordered[0].int >> 80
                print(
                    f"timestamp inside: within a minute of now = {abs(milliseconds / 1000 - time.time()) < 60}"
                )
                print(f"{uuid.NIL=}, {uuid.MAX=}")
            print(f"{uuid.uuid5(uuid.NAMESPACE_URL, 'https://shop.example.com/orders/7')=}  (always the same)")
            """
        ),
        md(
            """
            **`base64`** turns bytes into ASCII text so binary data fits in JSON, URLs, e-mail
            or HTTP headers. It is an **encoding, not encryption**: anyone can decode it.
            `urlsafe_b64encode` uses `-` and `_` instead of `+` and `/`; the `=` padding makes
            the length a multiple of 4. (`b32encode`, `b16encode` and `b85encode` exist too.)
            """
        ),
        code(
            r"""
            credentials = base64.b64encode(b"asha:chai123").decode("ascii")
            print(f"Authorization: Basic {credentials}")
            print(f"{base64.b64decode(credentials)=}  (anyone can read it)")
            token_bytes = bytes([251, 255, 0, 62])
            print(f"{base64.b64encode(token_bytes)=}, {base64.urlsafe_b64encode(token_bytes)=}")
            print(f"{[base64.b64encode(b'x' * size) for size in (1, 2, 3)]=}  (padding)")
            print(f"{base64.b16encode(b'TEA')=}, {base64.b32encode(b'TEA')=}")
            """
        ),
        md(
            """
            **`urllib.parse`** splits, builds and escapes URLs (JavaScript's `URL` and
            `URLSearchParams`). `urlsplit` gives the parts; `parse_qs` returns lists (a key can
            repeat), `parse_qsl` pairs; `urlencode` builds a query string (`doseq=True` for list
            values); `quote` escapes a path segment, `quote_plus` a form value; `urljoin`
            resolves a relative link the way a browser does.
            """
        ),
        code(
            r"""
            url = "https://shop.example.com:8443/products/search?q=masala+tea&tag=organic&tag=gift#reviews"
            parts = urllib.parse.urlsplit(url)
            print(f"{parts.scheme=}, {parts.hostname=}, {parts.port=}, {parts.path=}, {parts.fragment=}")
            print(f"{urllib.parse.parse_qs(parts.query)=}")
            print(f"{urllib.parse.parse_qsl(parts.query)=}")
            print(
                f"{urllib.parse.urlencode({'q': 'chai & biscuits', 'page': 2, 'tag': ['a', 'b']}, doseq=True)=}"
            )
            print(
                f"{urllib.parse.quote('reports/Nov 2026/₹.csv')=}, "
                f"{urllib.parse.quote_plus('chai & biscuits')=}"
            )
            print(f"{urllib.parse.unquote('%E2%82%B9500')=}")
            print(f"{urllib.parse.urljoin('https://shop.example.com/products/tea/', '../mugs?page=2')=}")
            print(f"{urllib.parse.urlunsplit(parts._replace(query='q=mug', fragment=''))=}")
            """
        ),
    ]


def _cli_cells() -> list[NotebookNode]:
    """4.4.8 Command-line interfaces."""
    return [
        md(
            """
            ### 4.4.8 Command-line interfaces

            **`argparse`** turns `sys.argv` into a namespace of typed values and generates
            `--help` and error messages. Positional arguments are required; options start with
            `-`/`--`. Per argument you choose a `type` (any callable), `default`, `choices`,
            `nargs`, `action` (`store_true`, `count`, `append`) and `help`. **Subcommands**
            (`git commit`, `uv add`) come from `add_subparsers()`, each with its own parser;
            `set_defaults(handler=...)` attaches the function that runs it.

            In a notebook, pass an explicit list to `parse_args([...])`; a real script calls
            `parse_args()` with no argument and reads `sys.argv[1:]`. Since 3.14 argparse
            colours help and errors when it thinks the output is a terminal, and the notebook
            frontend can look like one, so the cell sets `PYTHON_COLORS=0` for plain text.
            """
        ),
        code(
            r"""
            os.environ["PYTHON_COLORS"] = "0"  # plain argparse output in this notebook (3.14+ colours it)


            def report_command(arguments: argparse.Namespace) -> str:
                return f"report for {arguments.month} as {arguments.format}"


            def restock_command(arguments: argparse.Namespace) -> str:
                verb = "would add" if arguments.dry_run else "added"
                return f"{verb} {arguments.quantity} x {arguments.sku}"


            def build_shopctl() -> argparse.ArgumentParser:
                parser = argparse.ArgumentParser(prog="shopctl", description="Shop admin tool.")
                verbosity = parser.add_mutually_exclusive_group()
                verbosity.add_argument("-v", "--verbose", action="count", default=0, help="more output")
                verbosity.add_argument("-q", "--quiet", action="store_true", help="errors only")
                commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

                report = commands.add_parser("report", help="sales report for a month")
                report.add_argument("month", help="YYYY-MM")
                report.add_argument("--format", choices=["table", "csv", "json"], default="table")
                report.set_defaults(handler=report_command)

                restock = commands.add_parser("restock", help="add stock for a SKU")
                restock.add_argument("sku")
                restock.add_argument("-n", "--quantity", type=int, default=1)
                restock.add_argument("--dry-run", action="store_true")
                restock.set_defaults(handler=restock_command)
                return parser


            shopctl = build_shopctl()
            for argv in (["report", "2026-11"], ["-vv", "restock", "TEA-500", "-n", "24", "--dry-run"]):
                arguments = shopctl.parse_args(argv)
                print(f"{argv} -> {vars(arguments) | {'handler': arguments.handler.__name__}}")
                print(f"   {arguments.handler(arguments)}")
            """
        ),
        md(
            """
            **Help and errors for free.** `format_help()` returns what `--help` prints. On a
            bad command line argparse prints usage plus an error to stderr and exits with
            status 2; `exit_on_error=False` raises `ArgumentError` instead (useful in tests).
            *New in 3.14:* `suggest_on_error=True` suggests the closest valid choice, and help
            output is coloured in terminals (`color=False` turns that off).
            """
        ),
        code(
            r"""
            print(build_shopctl().format_help())
            with contextlib.redirect_stdout(io.StringIO()) as restock_help, contextlib.suppress(SystemExit):
                build_shopctl().parse_args(["restock", "--help"])  # --help prints, then exits
            print(restock_help.getvalue())
            """
        ),
        md(
            """
            The real command-line experience, in a child process: the script runs the same
            parser as `shopctl.py`. A typo in the subcommand, a bad type and a successful call:
            """
        ),
        code(
            r"""
            cli_dir = fresh_dir("cli")
            cli_source = inspect.getsource(report_command) + "\n\n" + inspect.getsource(restock_command)
            parser_source = inspect.getsource(build_shopctl)
            if sys.version_info >= (3, 14):  # suggest_on_error: New in 3.14
                parser_source = parser_source.replace(
                    'description="Shop admin tool."', 'description="Shop admin tool.", suggest_on_error=True'
                )
            cli_source += "\n\n" + parser_source
            cli_source += "\n\narguments = build_shopctl().parse_args()\nprint(arguments.handler(arguments))\n"
            (cli_dir / "shopctl.py").write_text("import argparse\n\n\n" + cli_source, encoding="utf-8")
            for argv in (
                ["reprot", "2026-11"],
                ["restock", "TEA-500", "-n", "many"],
                ["restock", "MUG-02", "-n", "6"],
            ):
                completed = subprocess.run(
                    [sys.executable, "shopctl.py", *argv],
                    cwd=cli_dir,
                    capture_output=True,
                    text=True,
                    env={**os.environ, "PYTHON_COLORS": "0", "NO_COLOR": "1"},
                )
                print(f"$ python shopctl.py {shlex.join(argv)}   (exit {completed.returncode})")
                print(textwrap.indent((completed.stdout + completed.stderr).strip(), "  "))
            """
        ),
        md(
            """
            For tests, `exit_on_error=False` turns most usage errors into an exception you can
            assert on (some errors, such as missing required arguments, still exit; catch
            `SystemExit` for those):
            """
        ),
        code(
            r"""
            strict_parser = argparse.ArgumentParser(prog="shopctl", exit_on_error=False)
            strict_parser.add_argument("--quantity", type=int)
            print(raised_message(lambda: strict_parser.parse_args(["--quantity", "many"])))
            with contextlib.redirect_stderr(io.StringIO()) as usage_message:
                try:
                    build_shopctl().parse_args([])
                except SystemExit as exit_request:
                    print(
                        f"SystemExit({exit_request.code}): {usage_message.getvalue().strip().splitlines()[-1]}"
                    )
            """
        ),
        md(
            """
            **`typer` and `click`.** For larger CLIs, third-party libraries trade a dependency
            for less code: `click` builds commands from decorators; `typer` builds them from
            **type hints** (the same idea as FastAPI) on top of click. Unit 4.6 uses typer; the
            `restock` command would look like this:

            ```python
            import typer

            app = typer.Typer()


            @app.command()
            def restock(sku: str, quantity: int = 1, dry_run: bool = False) -> None:
                verb = "would add" if dry_run else "added"
                print(f"{verb} {quantity} x {sku}")
            ```
            """
        ),
    ]


def _text_cells() -> list[NotebookNode]:
    """4.4.9 Text utilities."""
    return [
        md(
            """
            ### 4.4.9 Text utilities

            **`textwrap`**: `wrap` (list of lines) and `fill` (one string) re-flow text to a
            width; `shorten` truncates on word boundaries with a placeholder; `dedent` removes
            common indentation (handy for triple-quoted strings, as this course's build scripts
            do); `indent` adds a prefix to lines.
            """
        ),
        code(
            r'''
            description = (
                "Hand-picked Assam tea leaves blended with cardamom, ginger and cinnamon "
                "for a strong, spicy cup."
            )
            print(textwrap.fill(description, width=40))
            print(f"{textwrap.wrap(description, width=40)[:2]=}")
            print(f"{textwrap.shorten(description, width=45, placeholder=' [...]')=}")
            block = """
                Dear Asha,
                    Your order has shipped.
            """
            print(repr(textwrap.dedent(block).strip("\n")))
            print(textwrap.indent("line one\nline two", "> "))
            '''
        ),
        md(
            """
            **`string.Template`** does `$name` / `${name}` substitution and nothing else: no
            attribute access, no indexing, no format specs. That makes it the safe choice when
            the **template** comes from users or translators. `str.format` with a
            user-supplied template can read attributes of the objects you pass, all the way to
            module globals (a real vulnerability class). `substitute` raises `KeyError` for a
            missing name; `safe_substitute` leaves it in place.
            """
        ),
        code(
            r"""
            @dataclasses.dataclass
            class Customer:
                name: str
                city: str

                def __post_init__(self) -> None:
                    self.api_secret = "sk_live_demo_secret"


            asha = Customer("Asha", "Pune")
            user_template = "Hi {customer.name}, secret: {customer.api_secret}"  # typed by a user
            print(f"str.format leaks: {user_template.format(customer=asha)!r}")

            greeting = string.Template("Hi $name, your order ships to ${city}. Code: $coupon")
            print(f"{greeting.safe_substitute(name=asha.name, city=asha.city)=}")
            print(raised_message(lambda: greeting.substitute(name=asha.name, city=asha.city)))
            print(
                f"{string.Template('$customer.api_secret').safe_substitute(customer=asha)=}"
                "  (no attribute access)"
            )
            """
        ),
        md(
            """
            *New in 3.14:* template strings (`t"Hi {name}"`, PEP 750, `string.templatelib`)
            produce a `Template` object with the static parts and the interpolated values kept
            separate, so a library can escape values for HTML or SQL before combining them.
            Unlike `string.Template`, the template is written in your code, not supplied at run
            time.

            **`difflib`** compares sequences: `unified_diff` produces `git diff`-style output,
            `ndiff` a character-level view, `SequenceMatcher.ratio()` a similarity score, and
            `get_close_matches` powers "did you mean ...?" suggestions.
            """
        ),
        code(
            r"""
            old_config = ["currency = INR", "gst = 18", "free_shipping_above = 500"]
            new_config = ["currency = INR", "gst = 12", "free_shipping_above = 500", "cod = true"]
            print(
                "\n".join(
                    difflib.unified_diff(old_config, new_config, "settings.old", "settings.new", lineterm="")
                )
            )
            print(f"{difflib.SequenceMatcher(None, 'masala tea', 'masala chai').ratio():.2f}")
            catalogue_names = ["masala tea", "green tea", "steel mug", "pickle jar", "tea strainer"]
            print(f"{difflib.get_close_matches('masla tee', catalogue_names)=}")
            print(f"{difflib.get_close_matches('stel mug', catalogue_names, n=1)=}")
            print(list(difflib.ndiff(["gst = 18"], ["gst = 12"])))
            """
        ),
        md(
            """
            **`pprint`** prints nested data readably: it wraps at `width`, can limit `depth`,
            and sorts dict keys unless `sort_dicts=False`. `pformat` returns the string;
            `pprint.pp` (3.8) is `pprint` with `sort_dicts=False` by default.
            """
        ),
        code(
            r"""
            store_config = {
                "store": {"name": "Pune Central", "city": "Pune", "opens": "09:00"},
                "payments": {"methods": ["upi", "card", "cash"], "gateway": {"name": "demo-pay", "timeout": 5}},
                "inventory": {"warehouses": ["PNQ1", "BLR1"], "reorder": {"TEA-500": 10, "MUG-02": 5}},
            }
            pprint.pprint(store_config, width=70)
            print("--- depth=1, sort_dicts=False ---")
            pprint.pprint(store_config, depth=1, sort_dicts=False)
            print(f"{len(pprint.pformat(store_config, width=40).splitlines())=} lines at width 40")
            pprint.pp({"z": 1, "a": 2})
            """
        ),
    ]


LAB_SETUP_SOURCE = r"""
LAB44_DIR = find_repo_root() / "notebooks" / "_scratch" / "unit44" / "lab"
LAB44_DIR.mkdir(parents=True, exist_ok=True)
MIB = 1024 * 1024
print(f"lab files go to {LAB44_DIR.relative_to(find_repo_root()).as_posix()}/")
"""


def _lab_cells_part_1() -> list[NotebookNode]:
    """Lab 4.4 exercises 1–4."""
    return [
        md(
            """
            ### Lab 4.4

            Seven exercises; replace each `raise NotImplementedError`, then run the check cell.
            The checks build their own test folders under `notebooks/_scratch/unit44/lab/`.
            Until you finish, they print FAIL; that is expected.
            """
        ),
        code(LAB_SETUP_SOURCE),
        md(
            """
            #### Exercise 1 — `find_large_files(root, min_size_mb)`

            Return every **regular file** under `root` (recursively; skip symlinks) whose size
            is at least `min_size_mb` mebibytes (`min_size_mb * 1024 * 1024` bytes; the
            argument may be a float). Each result is `(path relative to root as a POSIX
            string, size in bytes)`, sorted by size (largest first), then by path. Raise
            `NotADirectoryError` if `root` is not a directory.
            """
        ),
        code(
            r'''
            def find_large_files(root: Path, min_size_mb: float) -> list[tuple[str, int]]:
                """Files of at least min_size_mb MiB under root, largest first."""
                raise NotImplementedError
            '''
        ),
        md(
            "Check exercise 1 (the test files are *sparse*: they report a size but use almost no disk):"
        ),
        code(
            r'''
            def make_large_file_tree() -> Path:
                """big.iso 5 MiB, two 2.5 MiB logs, edge.bin exactly 1 MiB, small files, a symlink."""
                root = LAB44_DIR / "large_files"
                shutil.rmtree(root, ignore_errors=True)
                sizes = {
                    "big.iso": 5 * MIB,
                    "logs/app.log": 5 * MIB // 2,
                    "logs/old/app.1.log": 5 * MIB // 2,
                    "edge.bin": MIB,
                    "notes.txt": 10,
                    "logs/old/tiny.gz": 2048,
                }
                for relative_path, size in sizes.items():
                    path = root / relative_path
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with path.open("wb") as handle:
                        handle.truncate(size)
                (root / "big-link.iso").symlink_to("big.iso")
                return root


            large_root = make_large_file_tree()
            run_checks(
                [
                    (
                        "at least 1 MiB",
                        lambda: find_large_files(large_root, 1),
                        [
                            ("big.iso", 5 * MIB),
                            ("logs/app.log", 5 * MIB // 2),
                            ("logs/old/app.1.log", 5 * MIB // 2),
                            ("edge.bin", MIB),
                        ],
                    ),
                    ("at least 3 MiB", lambda: find_large_files(large_root, 3), [("big.iso", 5 * MIB)]),
                    (
                        "float threshold",
                        lambda: [path for path, _ in find_large_files(large_root, 2.5)],
                        ["big.iso", "logs/app.log", "logs/old/app.1.log"],
                    ),
                    ("nothing that large", lambda: find_large_files(large_root, 10), []),
                    (
                        "symlink skipped",
                        lambda: "big-link.iso" in [path for path, _ in find_large_files(large_root, 0)],
                        False,
                    ),
                    (
                        "root is a file",
                        lambda: raised_message(lambda: find_large_files(large_root / "notes.txt", 1)).split(
                            ":"
                        )[0],
                        "NotADirectoryError",
                    ),
                ]
            )
            '''
        ),
        md(
            """
            #### Exercise 2 — a `VERBOSE` nginx-log regex with named groups

            nginx's default "combined" access-log format looks like this:

            ```text
            203.0.113.7 - - [07/Nov/2026:09:30:00 +0530] "GET /products/TEA-500?ref=home HTTP/1.1" 200 5120 "https://shop.example.com/" "Mozilla/5.0 (X11; Linux x86_64)"
            ```

            1. `NGINX_LOG_PATTERN`: a pattern compiled with `re.VERBOSE` (laid out over several
               lines with comments) with exactly these named groups: `ip`, `user`, `time`,
               `method`, `path`, `protocol`, `status`, `size`, `referrer`, `user_agent`.
            2. `parse_access_line(line)` returns `None` for a line that does not match, else
               the named groups as a dict with `status` and `size` converted to `int` (`-` as
               size means 0) and `user` / `referrer` set to `None` when they are `-`.
            """
        ),
        code(
            r'''
            NGINX_LOG_PATTERN = re.compile(r"replace me")


            def parse_access_line(line: str) -> dict[str, str | int | None] | None:
                """One combined-format log line -> dict of fields, or None."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 2:"),
        code(
            r"""
            GET_LINE = (
                '203.0.113.7 - - [07/Nov/2026:09:30:00 +0530] "GET /products/TEA-500?ref=home HTTP/1.1" '
                '200 5120 "https://shop.example.com/" "Mozilla/5.0 (X11; Linux x86_64)"'
            )
            POST_LINE = (
                '198.51.100.23 - asha [07/Nov/2026:09:31:12 +0530] "POST /api/orders HTTP/2.0" '
                '201 - "-" "curl/8.10.1"'
            )
            LOG_GROUPS = {
                "ip",
                "user",
                "time",
                "method",
                "path",
                "protocol",
                "status",
                "size",
                "referrer",
                "user_agent",
            }
            run_checks(
                [
                    ("compiled with re.VERBOSE", lambda: bool(NGINX_LOG_PATTERN.flags & re.VERBOSE), True),
                    ("named groups", lambda: set(NGINX_LOG_PATTERN.groupindex), LOG_GROUPS),
                    (
                        "GET line",
                        lambda: parse_access_line(GET_LINE),
                        {
                            "ip": "203.0.113.7",
                            "user": None,
                            "time": "07/Nov/2026:09:30:00 +0530",
                            "method": "GET",
                            "path": "/products/TEA-500?ref=home",
                            "protocol": "HTTP/1.1",
                            "status": 200,
                            "size": 5120,
                            "referrer": "https://shop.example.com/",
                            "user_agent": "Mozilla/5.0 (X11; Linux x86_64)",
                        },
                    ),
                    (
                        "POST line: user, size '-', referrer '-'",
                        lambda: {
                            key: parse_access_line(POST_LINE)[key]
                            for key in ("user", "method", "status", "size", "referrer", "user_agent")
                        },
                        {
                            "user": "asha",
                            "method": "POST",
                            "status": 201,
                            "size": 0,
                            "referrer": None,
                            "user_agent": "curl/8.10.1",
                        },
                    ),
                    ("malformed line", lambda: parse_access_line("GET /index.html 200"), None),
                    (
                        "status must be 3 digits",
                        lambda: parse_access_line(GET_LINE.replace(" 200 ", " 20 ")),
                        None,
                    ),
                ]
            )
            """
        ),
        md(
            """
            #### Exercise 3 — IST/UTC conversion, including a DST case

            1. `ist_to_utc("2026-11-07 15:00")` treats the text as India Standard Time and
               returns the UTC instant in ISO format: `"2026-11-07T09:30:00+00:00"`.
            2. `utc_to_zone(utc_text, zone_name)` converts an ISO timestamp **with an offset**
               to the zone and returns ISO text; text without an offset raises `ValueError`.
            3. `local_to_utc(local_text, zone_name)` treats `"YYYY-MM-DD HH:MM"` as wall-clock
               time in the zone: a time that does not exist there (skipped by a DST change)
               raises `ValueError`; an ambiguous time (repeated by a DST change) uses the
               **earlier** instant.
            """
        ),
        code(
            r'''
            def ist_to_utc(local_text: str) -> str:
                """'YYYY-MM-DD HH:MM' in IST -> ISO 8601 in UTC."""
                raise NotImplementedError


            def utc_to_zone(utc_text: str, zone_name: str) -> str:
                """ISO 8601 with offset -> ISO 8601 in zone_name."""
                raise NotImplementedError


            def local_to_utc(local_text: str, zone_name: str) -> str:
                """'YYYY-MM-DD HH:MM' wall-clock time in zone_name -> ISO 8601 in UTC."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 3 (New York's clocks change on 8 March and 1 November 2026):"),
        code(
            r"""
            run_checks(
                [
                    ("IST afternoon", lambda: ist_to_utc("2026-11-07 15:00"), "2026-11-07T09:30:00+00:00"),
                    (
                        "IST crosses midnight",
                        lambda: ist_to_utc("2026-01-01 03:00"),
                        "2025-12-31T21:30:00+00:00",
                    ),
                    (
                        "UTC -> IST",
                        lambda: utc_to_zone("2026-11-07T09:30:00+00:00", "Asia/Kolkata"),
                        "2026-11-07T15:00:00+05:30",
                    ),
                    (
                        "UTC -> New York before DST",
                        lambda: utc_to_zone("2026-03-06T14:00:00+00:00", "America/New_York"),
                        "2026-03-06T09:00:00-05:00",
                    ),
                    (
                        "UTC -> New York after DST",
                        lambda: utc_to_zone("2026-03-09T14:00:00+00:00", "America/New_York"),
                        "2026-03-09T10:00:00-04:00",
                    ),
                    (
                        "IST input -> London",
                        lambda: utc_to_zone("2026-07-01T19:30:00+05:30", "Europe/London"),
                        "2026-07-01T15:00:00+01:00",
                    ),
                    (
                        "naive input rejected",
                        lambda: raised_message(
                            lambda: utc_to_zone("2026-11-07T09:30:00", "Asia/Kolkata")
                        ).split(":")[0],
                        "ValueError",
                    ),
                    (
                        "non-existent New York time",
                        lambda: raised_message(
                            lambda: local_to_utc("2026-03-08 02:30", "America/New_York")
                        ).split(":")[0],
                        "ValueError",
                    ),
                    (
                        "ambiguous New York time: earlier",
                        lambda: local_to_utc("2026-11-01 01:30", "America/New_York"),
                        "2026-11-01T05:30:00+00:00",
                    ),
                    (
                        "London summer time",
                        lambda: local_to_utc("2026-07-01 09:00", "Europe/London"),
                        "2026-07-01T08:00:00+00:00",
                    ),
                ]
            )
            """
        ),
        md(
            """
            #### Exercise 4 — HMAC webhook verification

            A payment provider signs each webhook as `"sha256=" + hex(HMAC-SHA256(secret,
            f"{timestamp}." + body))`, where `timestamp` is Unix seconds (as text) and `body`
            the raw request bytes.

            1. `sign_webhook(secret, timestamp, body)` returns that signature string.
            2. `verify_webhook(secret, timestamp, body, signature, now, tolerance_seconds=300)`
               returns `True` only if the signature matches (compare with
               `hmac.compare_digest`) **and** `timestamp` is within `tolerance_seconds` of
               `now` in either direction (replay protection).
            """
        ),
        code(
            r'''
            def sign_webhook(secret: bytes, timestamp: int, body: bytes) -> str:
                """'sha256=<hex>' signature of timestamp + '.' + body."""
                raise NotImplementedError


            def verify_webhook(
                secret: bytes,
                timestamp: int,
                body: bytes,
                signature: str,
                now: int,
                tolerance_seconds: int = 300,
            ) -> bool:
                """True if the signature is valid and the timestamp is fresh."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 4:"),
        code(
            r"""
            SECRET, OTHER_SECRET = b"whsec_lab_secret", b"whsec_attacker_guess"
            BODY = b'{"event": "payment.captured", "order_id": 7}'
            SENT_AT = int(datetime(2026, 11, 7, 9, 30, tzinfo=UTC).timestamp())
            EXPECTED_SIGNATURE = (
                "sha256=" + hmac.new(SECRET, f"{SENT_AT}.".encode() + BODY, hashlib.sha256).hexdigest()
            )
            run_checks(
                [
                    (
                        "signature format and value",
                        lambda: sign_webhook(SECRET, SENT_AT, BODY),
                        EXPECTED_SIGNATURE,
                    ),
                    (
                        "valid webhook",
                        lambda: verify_webhook(SECRET, SENT_AT, BODY, EXPECTED_SIGNATURE, SENT_AT + 30),
                        True,
                    ),
                    (
                        "tampered body",
                        lambda: verify_webhook(
                            SECRET, SENT_AT, BODY.replace(b"7", b"8"), EXPECTED_SIGNATURE, SENT_AT
                        ),
                        False,
                    ),
                    (
                        "wrong secret",
                        lambda: verify_webhook(OTHER_SECRET, SENT_AT, BODY, EXPECTED_SIGNATURE, SENT_AT),
                        False,
                    ),
                    (
                        "timestamp is signed too",
                        lambda: verify_webhook(SECRET, SENT_AT + 1, BODY, EXPECTED_SIGNATURE, SENT_AT),
                        False,
                    ),
                    (
                        "stale (replayed) webhook",
                        lambda: verify_webhook(SECRET, SENT_AT, BODY, EXPECTED_SIGNATURE, SENT_AT + 301),
                        False,
                    ),
                    (
                        "from the future",
                        lambda: verify_webhook(SECRET, SENT_AT, BODY, EXPECTED_SIGNATURE, SENT_AT - 301),
                        False,
                    ),
                    (
                        "custom tolerance",
                        lambda: verify_webhook(
                            SECRET, SENT_AT, BODY, EXPECTED_SIGNATURE, SENT_AT + 600, tolerance_seconds=900
                        ),
                        True,
                    ),
                    (
                        "uses hmac.compare_digest",
                        lambda: "compare_digest" in inspect.getsource(verify_webhook),
                        True,
                    ),
                ]
            )
            """
        ),
    ]


def _lab_cells_part_2() -> list[NotebookNode]:
    """Lab 4.4 exercises 5–7."""
    return [
        md(
            """
            #### Exercise 5 — top-K with `heapq`

            `top_k(scores, k)` takes any iterable of `(name, score)` pairs (possibly a
            generator too large to sort in memory) and returns the `k` highest as a list,
            highest score first, ties by name (alphabetical). `k <= 0` returns `[]`. Use
            `heapq` (`nlargest`, or a bounded heap of size `k`).
            """
        ),
        code(
            r'''
            def top_k(scores: Iterable[tuple[str, int]], k: int) -> list[tuple[str, int]]:
                """The k highest (name, score) pairs, highest first, ties by name."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 5:"),
        code(
            r'''
            LEADERBOARD = [("ravi", 75), ("meera", 90), ("john", 60), ("asha", 90), ("fatima", 82)]


            def big_stream(count: int = 100_000):
                """A seeded generator of (name, score) pairs; never materialized as a list."""
                generator = random.Random(44)
                for number in range(count):
                    yield f"customer-{number:06d}", generator.randint(0, 1_000_000)


            def expected_top(pairs: list[tuple[str, int]], k: int) -> list[tuple[str, int]]:
                return sorted(pairs, key=lambda pair: (-pair[1], pair[0]))[:k]


            run_checks(
                [
                    (
                        "top 3 with a tie",
                        lambda: top_k(LEADERBOARD, 3),
                        [("asha", 90), ("meera", 90), ("fatima", 82)],
                    ),
                    ("k = 1", lambda: top_k(LEADERBOARD, 1), [("asha", 90)]),
                    ("k larger than the input", lambda: top_k(LEADERBOARD, 10), expected_top(LEADERBOARD, 10)),
                    ("k = 0", lambda: top_k(LEADERBOARD, 0), []),
                    ("generator input", lambda: top_k(iter(LEADERBOARD), 2), [("asha", 90), ("meera", 90)]),
                    (
                        "100,000-item stream",
                        lambda: top_k(big_stream(), 5),
                        expected_top(list(big_stream()), 5),
                    ),
                    ("uses heapq", lambda: "heapq" in inspect.getsource(top_k), True),
                ]
            )
            '''
        ),
        md(
            """
            #### Exercise 6 — build-step ordering with `graphlib`

            `steps` maps each build step to the steps it depends on. A dependency that is not
            itself a key is a step with no dependencies.

            1. `build_batches(steps)` returns the steps in **batches** that can run in
               parallel: each batch contains every step whose dependencies are all in earlier
               batches, sorted alphabetically.
            2. `build_order(steps)` returns one flat list: the batches concatenated.
            3. Both raise `ValueError` with a message starting `"cycle: "` followed by the
               cycle joined with `" -> "` (as `graphlib.CycleError` reports it) when the
               dependencies form a cycle.
            """
        ),
        code(
            r'''
            def build_batches(steps: Mapping[str, Iterable[str]]) -> list[list[str]]:
                """Parallel batches of steps, each sorted alphabetically."""
                raise NotImplementedError


            def build_order(steps: Mapping[str, Iterable[str]]) -> list[str]:
                """All steps in a valid order (the batches, concatenated)."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 6:"),
        code(
            r"""
            PIPELINE = {
                "package": ["test", "lint", "docs"],
                "test": ["compile"],
                "lint": [],
                "docs": ["fetch"],
                "compile": ["fetch"],
            }
            run_checks(
                [
                    (
                        "batches",
                        lambda: build_batches(PIPELINE),
                        [["fetch", "lint"], ["compile", "docs"], ["test"], ["package"]],
                    ),
                    (
                        "order",
                        lambda: build_order(PIPELINE),
                        ["fetch", "lint", "compile", "docs", "test", "package"],
                    ),
                    ("implicit leaf step", lambda: build_order({"deploy": ["build"]}), ["build", "deploy"]),
                    (
                        "independent steps sorted",
                        lambda: build_batches({"b": [], "c": [], "a": []}),
                        [["a", "b", "c"]],
                    ),
                    ("empty", lambda: build_order({}), []),
                    (
                        "cycle message",
                        lambda: (
                            re.fullmatch(
                                r"ValueError: cycle: \w+( -> \w+)+",
                                raised_message(lambda: build_order({"migrate": ["seed"], "seed": ["migrate"]})),
                            )
                            is not None
                        ),
                        True,
                    ),
                    (
                        "cycle in batches too",
                        lambda: raised_message(
                            lambda: build_batches({"a": ["b"], "b": ["c"], "c": ["a"]})
                        ).split(":")[0],
                        "ValueError",
                    ),
                ]
            )
            """
        ),
        md(
            """
            #### Exercise 7 — a file-organizer CLI with `--dry-run`

            `organizer_main(argv)` implements a command-line tool with two `argparse`
            subcommands and returns an exit code (it never calls `sys.exit`):

            - `organize FOLDER [--by {extension,month}] [--dry-run]` moves every regular,
              non-hidden file directly inside `FOLDER` (not in subfolders) into a subfolder:
              `--by extension` (the default) uses the lower-case extension without the dot
              (`no_extension` when there is none); `--by month` uses the file's modification
              month in UTC as `YYYY-MM`. Files are processed in sorted name order, printing
              `moved NAME -> SUBFOLDER/NAME` for each, then `N files moved`. With
              `--dry-run` nothing changes on disk and the lines say `would move ...` and
              `N files would be moved`.
            - `summary FOLDER` prints `EXTENSION: COUNT` lines for the same files, sorted by
              extension (using the same extension rule).
            - If `FOLDER` is not a directory, print `error: FOLDER is not a directory` to
              **stderr** and return 2. Invalid arguments (argparse errors) also return 2.
              Success returns 0.
            """
        ),
        code(
            r'''
            def organizer_main(argv: list[str]) -> int:
                """The file-organizer CLI; returns the exit code."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 7:"),
        code(
            r'''
            ORGANIZER_FILES = {
                "Invoice.PDF": (2026, 10, 30),
                "photo.jpg": (2026, 11, 2),
                "notes.txt": (2026, 11, 5),
                "README": (2026, 9, 1),
                "data.csv": (2026, 11, 6),
                ".hidden": (2026, 11, 7),
            }


            def make_messy_folder() -> Path:
                """Six files (one hidden) with fixed modification times, plus a subfolder."""
                folder = LAB44_DIR / "messy"
                shutil.rmtree(folder, ignore_errors=True)
                (folder / "existing").mkdir(parents=True)
                (folder / "existing" / "keep.txt").write_text("untouched", encoding="utf-8")
                for name, (year, month, day) in ORGANIZER_FILES.items():
                    (folder / name).write_text(name, encoding="utf-8")
                    stamp = datetime(year, month, day, 12, tzinfo=UTC).timestamp()
                    os.utime(folder / name, (stamp, stamp))
                return folder


            def run_organizer(*arguments: str) -> tuple[int, list[str], str]:
                """(exit code, stdout lines, stderr); "messy"/"missing" are folders in the lab folder."""
                stdout, stderr = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    exit_code = organizer_main(
                        [
                            str(LAB44_DIR / argument) if argument in ("messy", "missing") else argument
                            for argument in arguments
                        ]
                    )
                return exit_code, stdout.getvalue().splitlines(), stderr.getvalue()


            def folder_listing() -> list[str]:
                folder = LAB44_DIR / "messy"
                return sorted(
                    path.relative_to(folder).as_posix() for path in folder.rglob("*") if path.is_file()
                )


            def dry_run_then_listing() -> tuple[tuple[int, list[str], str], list[str]]:
                make_messy_folder()
                return run_organizer("organize", "messy", "--dry-run"), folder_listing()


            def organize_then_listing(*options: str) -> tuple[list[str], list[str]]:
                make_messy_folder()
                return run_organizer("organize", "messy", *options)[1], folder_listing()


            BY_EXTENSION = [
                "Invoice.PDF -> pdf/Invoice.PDF",
                "README -> no_extension/README",
                "data.csv -> csv/data.csv",
                "notes.txt -> txt/notes.txt",
                "photo.jpg -> jpg/photo.jpg",
            ]
            run_checks(
                [
                    (
                        "summary",
                        lambda: (make_messy_folder(), run_organizer("summary", "messy"))[1],
                        (0, ["csv: 1", "jpg: 1", "no_extension: 1", "pdf: 1", "txt: 1"], ""),
                    ),
                    (
                        "dry run output",
                        lambda: dry_run_then_listing()[0],
                        (0, [f"would move {line}" for line in BY_EXTENSION] + ["5 files would be moved"], ""),
                    ),
                    (
                        "dry run changes nothing",
                        lambda: dry_run_then_listing()[1],
                        sorted([*ORGANIZER_FILES, "existing/keep.txt"]),
                    ),
                    (
                        "organize by extension",
                        lambda: organize_then_listing()[0],
                        [f"moved {line}" for line in BY_EXTENSION] + ["5 files moved"],
                    ),
                    (
                        "files really moved",
                        lambda: organize_then_listing()[1],
                        [
                            ".hidden",
                            "csv/data.csv",
                            "existing/keep.txt",
                            "jpg/photo.jpg",
                            "no_extension/README",
                            "pdf/Invoice.PDF",
                            "txt/notes.txt",
                        ],
                    ),
                    (
                        "organize by month",
                        lambda: organize_then_listing("--by", "month")[0],
                        [
                            "moved Invoice.PDF -> 2026-10/Invoice.PDF",
                            "moved README -> 2026-09/README",
                            "moved data.csv -> 2026-11/data.csv",
                            "moved notes.txt -> 2026-11/notes.txt",
                            "moved photo.jpg -> 2026-11/photo.jpg",
                            "5 files moved",
                        ],
                    ),
                    (
                        "missing folder",
                        lambda: run_organizer("organize", "missing"),
                        (2, [], f"error: {LAB44_DIR / 'missing'} is not a directory\n"),
                    ),
                    ("bad --by value", lambda: run_organizer("organize", "messy", "--by", "size")[0], 2),
                ]
            )
            '''
        ),
    ]


def _recap_cells() -> list[NotebookNode]:
    """Recap for Unit 4.4."""
    return [
        md(
            """
            ### Recap — Unit 4.4

            | Concept | One-line takeaway | JS / Node equivalent |
            | --- | --- | --- |
            | `pathlib`, `os`, `sys`, `shutil` | Paths are objects (`/`, `.name`, `.glob`, `.walk`); always pass `encoding`; atomic writes with `os.replace` | `path`, `fs`, `process` |
            | `subprocess` | `run([...], capture_output=True, text=True, check=True, timeout=...)`; `Popen` to stream; never `shell=True` with input | `child_process` |
            | Dates and times | Aware datetimes, `ZoneInfo("Asia/Kolkata")`, store UTC, ISO 8601; DST: gaps, folds, wall-clock arithmetic; `monotonic`/`perf_counter` for durations | `Date`, `Intl`, `performance.now()` |
            | `re` | `match`/`search`/`fullmatch`, named groups `(?P<n>)`, lazy `*?`, `VERBOSE`, lookarounds, `sub` with a function; beware nested quantifiers | `RegExp` |
            | `json`, `csv` | `default=`/`JSONEncoder`, `object_hook`, `parse_float=Decimal`; `DictReader`/`DictWriter` with `newline=""` | `JSON`, csv libraries |
            | Algorithms | `heapq` priority queues and top-k, `bisect` bands, `statistics`, `math`, `graphlib` for dependency order | npm packages |
            | Randomness and security | `random` (seeded, reproducible) vs `secrets`; `hashlib`, slow KDFs for passwords, `hmac` + `compare_digest`, `uuid7`, `base64` is not encryption, `urllib.parse` | `Math.random`, `crypto`, `URL` |
            | CLIs | `argparse` subcommands, `set_defaults(handler=...)`, `exit_on_error=False` for tests; typer/click in Unit 4.6 | commander, yargs |
            | Text utilities | `textwrap`, `string.Template` (safe for user templates), `difflib`, `pprint` | template literals, `diff` |

            **Further reading**

            - [`pathlib`](https://docs.python.org/3/library/pathlib.html),
              [`os`](https://docs.python.org/3/library/os.html),
              [`shutil`](https://docs.python.org/3/library/shutil.html),
              [`subprocess`](https://docs.python.org/3/library/subprocess.html)
            - [`datetime`](https://docs.python.org/3/library/datetime.html),
              [`zoneinfo`](https://docs.python.org/3/library/zoneinfo.html),
              [`time`](https://docs.python.org/3/library/time.html)
            - [`re`](https://docs.python.org/3/library/re.html),
              [Regular Expression HOWTO](https://docs.python.org/3/howto/regex.html),
              [`json`](https://docs.python.org/3/library/json.html),
              [`csv`](https://docs.python.org/3/library/csv.html)
            - [`heapq`](https://docs.python.org/3/library/heapq.html),
              [`bisect`](https://docs.python.org/3/library/bisect.html),
              [`statistics`](https://docs.python.org/3/library/statistics.html),
              [`graphlib`](https://docs.python.org/3/library/graphlib.html)
            - [`random`](https://docs.python.org/3/library/random.html),
              [`secrets`](https://docs.python.org/3/library/secrets.html),
              [`hashlib`](https://docs.python.org/3/library/hashlib.html),
              [`hmac`](https://docs.python.org/3/library/hmac.html),
              [`uuid`](https://docs.python.org/3/library/uuid.html),
              [`base64`](https://docs.python.org/3/library/base64.html),
              [`urllib.parse`](https://docs.python.org/3/library/urllib.parse.html)
            - [`argparse`](https://docs.python.org/3/library/argparse.html),
              [`textwrap`](https://docs.python.org/3/library/textwrap.html),
              [`string`](https://docs.python.org/3/library/string.html),
              [`difflib`](https://docs.python.org/3/library/difflib.html),
              [`pprint`](https://docs.python.org/3/library/pprint.html)
            - [PEP 428](https://peps.python.org/pep-0428/) (pathlib),
              [PEP 495](https://peps.python.org/pep-0495/) (`fold`),
              [PEP 615](https://peps.python.org/pep-0615/) (zoneinfo),
              [PEP 506](https://peps.python.org/pep-0506/) (secrets),
              [PEP 686](https://peps.python.org/pep-0686/) (UTF-8 mode),
              [PEP 750](https://peps.python.org/pep-0750/) (template strings),
              [RFC 9562](https://www.rfc-editor.org/rfc/rfc9562) (UUIDv7)
            """
        ),
    ]


def cells() -> list[NotebookNode]:
    """Return the cells for Unit 4.4 and Lab 4.4."""
    return [
        *_overview_cells(),
        *_path_cells(),
        *_process_cells(),
        *_datetime_cells(),
        *_regex_cells(),
        *_format_cells(),
        *_algorithm_cells(),
        *_random_security_cells(),
        *_cli_cells(),
        *_text_cells(),
        *_lab_cells_part_1(),
        *_lab_cells_part_2(),
        *_recap_cells(),
    ]
