"""Unit 4.5 — File I/O, Encodings and Serialization (with Lab 4.5)."""

from nbformat import NotebookNode

from nb_builder import code, md, predict_cells

UNIT_SETUP_SOURCE = r'''
import bz2
import codecs
import csv
import dataclasses
import gzip
import importlib.util
import io
import json
import lzma
import mmap
import os
import pickle
import shutil
import sqlite3
import struct
import sys
import tarfile
import tempfile
import textwrap
import tomllib
import uuid
import wave
import zipfile
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

REPO_ROOT = find_repo_root()
scratch_dir = REPO_ROOT / "notebooks" / "_scratch"  # git-ignored
UNIT45_DIR = scratch_dir / "unit45"
UNIT45_DIR.mkdir(parents=True, exist_ok=True)
FIXED_MOMENT = datetime(2026, 11, 7, 9, 30, tzinfo=UTC)


def tidy(text: str) -> str:
    """Show absolute paths as <scratch>, <repo> or ~."""
    for folder, label in ((UNIT45_DIR, "<scratch>"), (REPO_ROOT, "<repo>"), (Path.home(), "~")):
        text = text.replace(str(folder), label)
    return text


def fresh_dir(name: str) -> Path:
    """An empty folder <scratch>/<name>, recreated on every run."""
    folder = UNIT45_DIR / name
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    return folder


def raised_message(thunk: Callable[[], object]) -> str:
    """Call thunk and return "ErrorName: message" for the exception it raised, or "no error"."""
    try:
        thunk()
    except Exception as error:
        return tidy(f"{type(error).__name__}: {error}")
    return "no error"


io_demo = fresh_dir("io_demo")
print(f"scratch folder: {io_demo.relative_to(REPO_ROOT).as_posix()}")
print(f"{sys.getdefaultencoding()=}, {sys.flags.utf8_mode=}")
'''


def _overview_cells() -> list[NotebookNode]:
    """Unit opener and setup."""
    return [
        md(
            """
            ## Unit 4.5 — File I/O, Encodings and Serialization

            **Objectives**

            - Explain what `open()` builds (raw file, buffer, text wrapper) and choose modes,
              buffering, encodings and newline handling deliberately.
            - Read and write files safely: line by line, in binary chunks, with `seek`/`tell`,
              and atomically.
            - Use in-memory and temporary files for tests and pipelines.
            - Parse binary formats with `struct`, `memoryview` and `mmap`.
            - Understand encodings well enough to fix mojibake and choose error handlers.
            - Pick a serialization format (JSON, CSV, TOML, YAML, XML, MessagePack, pickle)
              and know which ones are safe for untrusted input.
            - Compress and archive files, and extract archives without path traversal.
            - Store data in SQLite with parameterized queries and transactions.

            **JS bridge: Node `fs` and friends → Python**

            | Node / browser | Python | The difference that bites |
            | --- | --- | --- |
            | `fs.readFileSync(p, "utf8")` | `open(p, encoding="utf-8").read()` | Text vs binary is the **mode** (`"r"` vs `"rb"`); always pass `encoding` |
            | `fs.createReadStream` | iterate the file object, or `read(chunk_size)` | Files are iterators of lines |
            | `Buffer` | `bytes` / `bytearray` / `memoryview` | `str` and `bytes` never mix implicitly |
            | `TextDecoder("utf-16")` | `bytes.decode("utf-16")`, `codecs` | Error handlers: `strict`, `replace`, `ignore`, `surrogateescape` |
            | `DataView.getUint32(o, false)` | `struct.unpack_from(">I", data, o)` | Format strings choose endianness and sizes |
            | `JSON.stringify` / `structuredClone` | `json`, `pickle` | **Never unpickle untrusted data** |
            | `zlib`, `tar` packages | `gzip`, `bz2`, `lzma`, `compression.zstd`, `zipfile`, `tarfile` | All in the standard library |
            | `better-sqlite3` | `sqlite3` | Built in; use `?` placeholders |

            Every demo writes under `notebooks/_scratch/unit45/` (paths are shown as
            `<scratch>`). The file contents are fixed, so outputs are the same on every run.
            """
        ),
        code(UNIT_SETUP_SOURCE),
    ]


def _open_cells() -> list[NotebookNode]:
    """4.5.1 open() in depth."""
    return [
        md(
            """
            ### 4.5.1 `open()` in depth

            **Modes** combine an action with text or binary:

            | Mode | Meaning | If the file exists | If it does not |
            | --- | --- | --- | --- |
            | `"r"` | read (default) | read from the start | `FileNotFoundError` |
            | `"w"` | write | **truncate** to empty | create |
            | `"a"` | append | write at the end | create |
            | `"x"` | exclusive create | `FileExistsError` | create |
            | `"+"` | read **and** write (`"r+"`, `"w+"`, `"a+"`) | as the base mode | as the base mode |
            | `"b"` / `"t"` | binary (`bytes`) / text (`str`, the default) | | |

            `"x"` is the safe way to create a file only if nobody else has.
            """
        ),
        code(
            r"""
            orders_path = io_demo / "orders.txt"
            with open(orders_path, "w", encoding="utf-8") as orders_file:
                orders_file.write("TEA-500,2\n")
            with open(orders_path, "a", encoding="utf-8") as orders_file:
                orders_file.write("MUG-02,1\n")
            print(f"{orders_path.read_text(encoding='utf-8')!r}")
            print(raised_message(lambda: open(orders_path, "x", encoding="utf-8")))
            print(raised_message(lambda: open(io_demo / "missing.txt", encoding="utf-8")))
            with open(orders_path, "rb") as binary_file:
                print(f"{binary_file.read()!r}  (binary mode: bytes)")
            """
        ),
        *predict_cells(
            """
            from pathlib import Path

            notes = Path("notes.txt")
            notes.write_text("order 7: paid\\n", encoding="utf-8")
            with open(notes, "w", encoding="utf-8") as notes_file:
                pass  # opened for writing, nothing written
            print(repr(notes.read_text(encoding="utf-8")))
            """,
            """
            `''`. Mode `"w"` **truncates** the file the moment it is opened, before you write
            anything, so opening a file for writing by mistake destroys its contents. Use `"a"`
            to append, `"x"` to refuse existing files, or the atomic-write pattern (4.5.2) to
            replace a file safely.
            """,
            """
            notes = io_demo / "notes.txt"
            notes.write_text("order 7: paid\\n", encoding="utf-8")
            with open(notes, "w", encoding="utf-8") as notes_file:
                pass  # opened for writing, nothing written
            print(repr(notes.read_text(encoding="utf-8")))
            """,
        ),
        md(
            """
            **The I/O stack.** `open()` builds up to three layers, and the object you get back
            depends on the mode:

            ```mermaid
            flowchart LR
                CODE["your code<br/>str"] --> TEXT["TextIOWrapper<br/>encoding, newlines"]
                TEXT --> BUF["BufferedReader / BufferedWriter<br/>buffer (io.DEFAULT_BUFFER_SIZE)"]
                BUF --> RAW["FileIO<br/>OS read()/write() calls"]
                RAW --> OS["file descriptor"]
            ```

            <details><summary>ASCII version</summary>

            ```text
            text mode:   TextIOWrapper -> BufferedReader/Writer -> FileIO -> OS
            "rb"/"wb":                    BufferedReader/Writer -> FileIO -> OS
            buffering=0:                                           FileIO -> OS
            ```

            </details>

            Each layer is reachable through an attribute (`.buffer`, `.raw`), which is how you
            get binary access to a text file such as `sys.stdout.buffer`. The buffer size is
            `io.DEFAULT_BUFFER_SIZE`: 128 KiB on this 3.15 build (it used to be 8 KiB).
            """
        ),
        code(
            r"""
            with open(orders_path, encoding="utf-8") as text_file:
                print(
                    f"{type(text_file).__name__} -> {type(text_file.buffer).__name__} -> "
                    f"{type(text_file.buffer.raw).__name__}"
                )
                print(f"{text_file.encoding=}, {text_file.buffer.raw.fileno() >= 0=}")
            with open(orders_path, "rb") as binary_file:
                print(f"'rb': {type(binary_file).__name__} -> {type(binary_file.raw).__name__}")
            with open(orders_path, "rb", buffering=0) as unbuffered_file:
                print(f"'rb', buffering=0: {type(unbuffered_file).__name__}")
            print(f"{io.DEFAULT_BUFFER_SIZE=}")
            """
        ),
        md(
            """
            **Buffering.** Writes collect in the buffer and reach the OS when it fills, on
            `flush()` or on `close()`. That is why output can seem to "disappear" when a
            program crashes, and why another reader may not see data yet. `buffering=1`
            means line-buffered (text mode only); `buffering=0` means unbuffered (binary
            only).
            """
        ),
        code(
            r"""
            log_path = io_demo / "buffered.log"
            writer = open(log_path, "w", encoding="utf-8")
            writer.write("order 7 placed\n")
            print(f"before flush: {log_path.read_text(encoding='utf-8')!r}")
            writer.flush()
            print(f"after flush:  {log_path.read_text(encoding='utf-8')!r}")
            writer.close()
            with open(log_path, "a", encoding="utf-8", buffering=1) as line_buffered:
                line_buffered.write("order 8 placed\n")  # a newline flushes
                print(f"line-buffered: {log_path.read_text(encoding='utf-8').splitlines()}")
            """
        ),
        md(
            """
            **Encodings.** A text file is bytes on disk; the `encoding` turns them into `str`.
            Without the argument Python used the platform's locale encoding (cp1252 on many
            Windows machines), so code worked on one machine and broke on another. *Changed
            in 3.15:* UTF-8 mode is the default (PEP 686), but passing
            `encoding="utf-8"` keeps code correct on every version, and linters (ruff's
            `PLW1514`) can enforce it. `encoding="locale"` asks for the old behaviour
            explicitly.
            """
        ),
        code(
            r"""
            price_path = io_demo / "price.txt"
            price_path.write_text("Masala tea: ₹240\n", encoding="utf-8")
            print(f"{price_path.read_bytes()=}")
            print(f"{price_path.read_text(encoding='utf-8')=}")
            print(f"{price_path.read_text(encoding='cp1252')=}  (wrong encoding: mojibake)")
            print(raised_message(lambda: price_path.read_text(encoding="ascii")))
            """
        ),
        md(
            """
            **Newline handling.** In text mode, `newline=None` (the default) translates `\\r\\n`
            and `\\r` to `\\n` when reading and writes `os.linesep` when writing. `newline=""`
            turns translation off (the `csv` module needs this, Unit 4.4.5); `newline="\\n"`
            writes Unix line endings on every OS. Binary mode never translates.
            """
        ),
        code(
            r"""
            mixed_path = io_demo / "mixed_endings.txt"
            mixed_path.write_bytes(b"windows\r\nunix\nold mac\r")
            with open(mixed_path, encoding="utf-8") as default_mode:
                print(f"newline=None: {default_mode.read()!r}")
            with open(mixed_path, encoding="utf-8", newline="") as untranslated:
                print(f"newline='':   {untranslated.read()!r}")
            with open(mixed_path, encoding="utf-8") as default_mode:
                default_mode.read()
                print(f"endings seen: {default_mode.newlines!r}")
            with open(io_demo / "unix.txt", "w", encoding="utf-8", newline="\n") as unix_file:
                unix_file.write("a\nb\n")
            print(f"{(io_demo / 'unix.txt').read_bytes()=}")
            """
        ),
    ]


def _pattern_cells() -> list[NotebookNode]:
    """4.5.2 Reading and writing patterns."""
    return [
        md(
            """
            ### 4.5.2 Reading and writing patterns

            **Line iteration.** A text file object is an iterator of lines (each ending in
            `\\n`, except perhaps the last). Iterating reads one buffer at a time, so a 10 GB
            log needs only a few KB of memory. `read()` and `readlines()` load everything.
            """
        ),
        code(
            r"""
            access_log = io_demo / "access.log"
            access_log.write_text(
                "".join(f"2026-11-07 GET /products/{n} {200 if n % 7 else 500}\n" for n in range(1, 1001)),
                encoding="utf-8",
            )
            with access_log.open(encoding="utf-8") as log_file:
                errors = [line.split()[2] for line in log_file if line.rstrip().endswith("500")]
            print(f"{len(errors)=}, {errors[:3]=}")
            with access_log.open(encoding="utf-8") as log_file:
                print(f"{next(log_file)!r}, {log_file.readline()!r}")
            """
        ),
        md(
            """
            **Chunked binary reads.** For binary data (or text without useful lines) read a
            fixed number of bytes at a time. The walrus operator makes the loop compact;
            `read()` returns `b""` at the end of the file. This is how you hash or copy large
            files.
            """
        ),
        code(
            r'''
            import hashlib


            def sha256_of(path: Path, chunk_size: int = 64 * 1024) -> tuple[str, int]:
                """Hash a file in chunks; return (hex digest, number of chunks read)."""
                digest, chunks = hashlib.sha256(), 0
                with path.open("rb") as binary_file:
                    while chunk := binary_file.read(chunk_size):
                        digest.update(chunk)
                        chunks += 1
                return digest.hexdigest()[:16], chunks


            print(f"{access_log.stat().st_size=}")
            print(f"{sha256_of(access_log)=}")
            print(f"{sha256_of(access_log, chunk_size=1024)=}  (same digest, more reads)")
            '''
        ),
        md(
            """
            **`seek` and `tell`.** `tell()` gives the current position; `seek(offset,
            whence)` moves it: `whence=0` from the start (`os.SEEK_SET`), `1` from the current
            position, `2` from the end. In **binary** mode positions are byte offsets. In text
            mode `tell()` returns an opaque cookie and only `seek(cookie)` or `seek(0, 2)` are
            allowed, because characters and bytes are not the same size.
            """
        ),
        code(
            r"""
            with access_log.open("rb") as binary_file:
                binary_file.seek(-40, os.SEEK_END)
                print(f"{binary_file.tell()=}, {binary_file.read()!r}")
                binary_file.seek(11)
                print(f"{binary_file.read(3)=}, {binary_file.tell()=}")
                binary_file.seek(5, os.SEEK_CUR)
                print(f"{binary_file.read(9)=}")
            with access_log.open(encoding="utf-8") as text_file:
                print(raised_message(lambda: text_file.seek(-10, os.SEEK_END)))
            """
        ),
        md(
            """
            **`flush` and `fsync`.** `flush()` moves Python's buffer into the operating
            system; the OS may still keep the data in its page cache for seconds.
            `os.fsync(fd)` asks the OS to write it to the physical disk, which matters before
            you tell someone "saved" (a payment record, a database journal). It is slow, so
            call it only where durability matters.
            """
        ),
        code(
            r"""
            ledger_path = io_demo / "ledger.txt"
            with ledger_path.open("a", encoding="utf-8") as ledger:
                ledger.write("2026-11-07 order 7 paid 679.00\n")
                ledger.flush()  # Python buffer -> OS
                os.fsync(ledger.fileno())  # OS cache -> disk
            print(f"{ledger_path.read_text(encoding='utf-8')!r}")
            """
        ),
        md(
            """
            **Atomic writes with `os.replace`.** Writing over a file in place leaves a
            truncated or half-written file if the program crashes or the disk fills mid-write.
            The safe pattern (Unit 4.4.1 showed the idea): write a temporary file **in the
            same folder** (same file system), flush and `fsync` it, then `os.replace` it over
            the target. The rename is atomic: readers see the old file or the new one. If
            anything fails, the target is untouched and the temporary file is removed.
            """
        ),
        code(
            r'''
            def write_text_atomically(target: Path, text: str) -> None:
                """Replace target's contents in one atomic step, or not at all."""
                handle, temporary_name = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.")
                try:
                    with os.fdopen(handle, "w", encoding="utf-8") as temporary_file:
                        temporary_file.write(text)
                        temporary_file.flush()
                        os.fsync(temporary_file.fileno())
                    os.replace(temporary_name, target)
                except BaseException:
                    os.unlink(temporary_name)
                    raise


            stock_path = io_demo / "stock.csv"
            write_text_atomically(stock_path, "sku,quantity\nTEA-500,40\n")
            print(f"{stock_path.read_text(encoding='utf-8')!r}")
            print(raised_message(lambda: write_text_atomically(stock_path, "sku,quantity\n" + "MUG-02," + 7)))
            print(f"unchanged: {stock_path.read_text(encoding='utf-8')!r}")
            print(f"leftover temp files: {sorted(path.name for path in io_demo.glob('.stock.csv.*'))}")
            '''
        ),
        md(
            """
            The second call failed while *building* the text (`str + int`), before anything was
            written. A failure during the write (a full disk, an encoding error) is handled the
            same way by the `except` branch: the temporary file is deleted and the target
            never changes.
            """
        ),
    ]


def _memory_file_cells() -> list[NotebookNode]:
    """4.5.3 In-memory and temporary files."""
    return [
        md(
            """
            ### 4.5.3 In-memory and temporary files

            **`io.StringIO`** and **`io.BytesIO`** are file objects backed by memory. Any code
            that accepts a file (the `csv` module, `json.dump`, a parser, a logger handler)
            works with them, which makes them ideal for tests and for building a payload
            before sending it over the network.
            """
        ),
        code(
            r"""
            report = io.StringIO()
            writer = csv.writer(report)
            writer.writerows([["sku", "quantity"], ["TEA-500", 2], ["MUG-02", 1]])
            print(f"{report.getvalue()!r}")
            report.seek(0)
            print(f"{list(csv.DictReader(report))=}")

            payload = io.BytesIO()
            payload.write(b"\x89PNG")
            payload.write(struct.pack(">I", 13))
            print(f"{payload.getvalue()=}, {payload.tell()=}")
            print(f"{io.StringIO('line 1\nline 2\n').readlines()=}")
            """
        ),
        md(
            """
            **`tempfile`** creates files and folders that do not clash with anything else and
            are cleaned up for you:

            | Function | Gives | Cleaned up |
            | --- | --- | --- |
            | `TemporaryFile()` | an anonymous file (no visible name on POSIX) | on close |
            | `NamedTemporaryFile(delete=...)` | a file with a real path (`.name`) | on close, or with `delete_on_close=False` (3.12) when the `with` block ends |
            | `TemporaryDirectory()` | a folder | when the `with` block ends |
            | `mkstemp()` / `mkdtemp()` | a low-level handle + path / a folder path | never: you delete it |
            | `SpooledTemporaryFile(max_size)` | memory until `max_size`, then a real file | on close |

            They live in `tempfile.gettempdir()` unless you pass `dir=`.
            """
        ),
        code(
            r"""
            with tempfile.TemporaryDirectory(prefix="shop-") as workspace:
                workspace_path = Path(workspace)
                (workspace_path / "export.csv").write_text("sku\nTEA-500\n", encoding="utf-8")
                print(
                    f"inside:  {workspace_path.name.startswith('shop-')=}, "
                    f"{[p.name for p in workspace_path.iterdir()]}"
                )
            print(f"after:   {workspace_path.exists()=}")

            with tempfile.NamedTemporaryFile(
                "w+", suffix=".json", encoding="utf-8", delete_on_close=False
            ) as named:
                named.write('{"ok": true}')
                named.close()  # other programs can now open it by name (needed on Windows)
                print(
                    f"{Path(named.name).suffix=}, {json.loads(Path(named.name).read_text(encoding='utf-8'))=}"
                )
            print(f"deleted at block end: {not Path(named.name).exists()}")

            with tempfile.SpooledTemporaryFile(max_size=100) as spooled:
                spooled.write(b"x" * 50)
                print(f"50 bytes -> in memory: {isinstance(spooled._file, io.BytesIO)}")
                spooled.write(b"x" * 100)
                print(f"150 bytes -> on disk: {not isinstance(spooled._file, io.BytesIO)}")
            """
        ),
    ]


def _binary_cells() -> list[NotebookNode]:
    """4.5.4 Binary formats."""
    return [
        md(
            """
            ### 4.5.4 Binary formats

            **`struct`** converts between Python values and packed C-style binary data,
            described by a format string. The first character sets byte order and alignment;
            the rest are field codes.

            | Prefix | Byte order | | Code | C type | Size |
            | --- | --- | --- | --- | --- | --- |
            | `<` | little-endian (x86, ARM, most file formats from Microsoft) | | `B` / `b` | unsigned / signed char | 1 |
            | `>` or `!` | big-endian ("network order": PNG, TCP/IP) | | `H` / `h` | unsigned / signed short | 2 |
            | `=` | native order, standard sizes | | `I` / `i` | unsigned / signed int | 4 |
            | `@` (default) | native order **and** native alignment (padding) | | `Q` / `q` | unsigned / signed long long | 8 |
            | | | | `f` / `d` | float / double | 4 / 8 |
            | | | | `4s` | 4 bytes | 4 |

            **Endianness** is the order of the bytes of a multi-byte number: the integer
            `0x01020304` is stored as `01 02 03 04` big-endian and `04 03 02 01`
            little-endian. Always use an explicit prefix for file formats.
            """
        ),
        code(
            r"""
            number = 0x01020304
            print(f"big-endian:    {struct.pack('>I', number).hex(' ')}")
            print(f"little-endian: {struct.pack('<I', number).hex(' ')}")
            print(f"this machine:  {sys.byteorder}")
            record = struct.pack("<HIf4s", 7, 67900, 2.5, b"PNQ1")  # order id, paise, weight kg, warehouse
            print(f"{record.hex(' ')}  ({len(record)} bytes, {struct.calcsize('<HIf4s')=})")
            print(f"{struct.unpack('<HIf4s', record)=}")
            print(f"{struct.calcsize('@HI')=} (native alignment pads), {struct.calcsize('<HI')=}")
            print(raised_message(lambda: struct.pack("<H", 70_000)))
            """
        ),
        md(
            """
            **Parsing a PNG header.** Every PNG starts with an 8-byte signature followed by
            chunks: a 4-byte big-endian length, a 4-byte type, the data and a CRC. The first
            chunk, `IHDR`, holds width, height, bit depth, colour type, compression, filter
            and interlace. `struct.unpack_from(fmt, buffer, offset)` reads at an offset without
            slicing. The demo image is written by hand with `zlib`, so no image library is
            needed.
            """
        ),
        code(
            r'''
            import zlib


            def tiny_png(width: int, height: int) -> bytes:
                """A valid RGB PNG (solid colour) built by hand, no image library needed."""

                def chunk(kind: bytes, data: bytes) -> bytes:
                    return (
                        struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
                    )

                header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
                pixels = b"".join(b"\x00" + b"\xff\x99\x00" * width for _ in range(height))
                return (
                    b"\x89PNG\r\n\x1a\n"
                    + chunk(b"IHDR", header)
                    + chunk(b"IDAT", zlib.compress(pixels))
                    + chunk(b"IEND", b"")
                )


            PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


            def png_header(data: bytes) -> dict[str, int]:
                if data[:8] != PNG_SIGNATURE:
                    raise ValueError("not a PNG file")
                length, kind = struct.unpack_from(">I4s", data, 8)
                if kind != b"IHDR" or length != 13:
                    raise ValueError("first chunk is not IHDR")
                width, height, depth, colour, _, _, interlace = struct.unpack_from(">IIBBBBB", data, 16)
                return {
                    "width": width,
                    "height": height,
                    "bit_depth": depth,
                    "colour_type": colour,
                    "interlace": interlace,
                }


            png_bytes = tiny_png(640, 480)
            (io_demo / "banner.png").write_bytes(png_bytes)
            print(f"{png_bytes[:24].hex(' ')}")
            print(f"{png_header(png_bytes)=}")
            print(raised_message(lambda: png_header(b"GIF89a" + bytes(30))))
            '''
        ),
        md(
            """
            **`memoryview`** gives a zero-copy view of a buffer (`bytes`, `bytearray`, `mmap`,
            NumPy arrays): slicing it does not copy the data, which matters when parsing large
            binary files or network packets. On a `bytearray` the view is writable. `.cast()`
            reinterprets the bytes as another C type.
            """
        ),
        code(
            r"""
            big_buffer = bytearray(png_bytes)
            header_view = memoryview(big_buffer)[16:29]  # no copy
            print(f"{header_view.nbytes=}, {header_view.readonly=}, {bytes(header_view[:4]).hex()=}")
            header_view[0:4] = struct.pack(">I", 1280)  # writes into big_buffer
            print(f"{png_header(bytes(big_buffer))['width']=}")
            sample_rates = memoryview(struct.pack("<4H", 8000, 16000, 44100, 48000)).cast("H")
            print(f"{sample_rates.tolist()=}, {sample_rates.format=}, {sample_rates.itemsize=}")
            print(
                f"{sys.getsizeof(png_bytes[16:29_000])=} (slice of bytes: a copy), "
                f"{sys.getsizeof(memoryview(png_bytes)[16:29_000])=} (view)"
            )
            """
        ),
        md(
            """
            **`mmap`** maps a file into memory: you index and slice it like a `bytearray`, and
            the OS loads only the pages you touch. Good for random access in large files
            (search for a marker, read a record at an offset) and for sharing memory between
            processes. Opened with `r+b`, writes go back to the file.
            """
        ),
        code(
            r"""
            records_path = io_demo / "records.bin"
            records_path.write_bytes(
                b"".join(struct.pack("<I8s", n, f"SKU{n:05d}".encode()) for n in range(10_000))
            )
            RECORD = struct.Struct("<I8s")
            with records_path.open("r+b") as records_file, mmap.mmap(records_file.fileno(), 0) as mapped:
                print(f"{len(mapped)=} bytes, record size {RECORD.size}")
                print(f"record 4321: {RECORD.unpack_from(mapped, 4321 * RECORD.size)}")
                offset = mapped.find(b"SKU09999")
                print(f"{offset=}, found record {offset // RECORD.size}")
                mapped[0:4] = struct.pack("<I", 424242)  # write through the map
            with records_path.open("rb") as records_file:
                print(f"after writing via mmap: {RECORD.unpack(records_file.read(RECORD.size))}")
            """
        ),
    ]


def _encoding_cells() -> list[NotebookNode]:
    """4.5.5 Encodings."""
    return [
        md(
            """
            ### 4.5.5 Encodings

            A `str` is a sequence of Unicode **code points**; an encoding maps them to bytes.

            | Encoding | Bytes per character | Notes |
            | --- | --- | --- |
            | UTF-8 | 1–4 (ASCII is 1) | the default for files, the web and this course |
            | UTF-16 | 2 or 4 | Windows APIs, JavaScript strings internally; needs a byte order (`-le`/`-be`) or a BOM |
            | latin-1 (ISO-8859-1) | 1 | maps bytes 0–255 to the first 256 code points: **decodes any bytes**, never errors |
            | cp1252 | 1 | Windows' variant of latin-1 (`€`, smart quotes at 0x80–0x9F) |
            | ASCII | 1 | only 128 characters |
            """
        ),
        code(
            r"""
            text = "₹240 café 🍵"
            for encoding in ("utf-8", "utf-16-le", "utf-16", "utf-32-le"):
                encoded = text.encode(encoding)
                print(f"{encoding:<10} {len(encoded):>3} bytes  {encoded[:12].hex(' ')}...")
            print(f"{len(text)=} code points, {[f'U+{ord(character):04X}' for character in '₹é🍵']}")
            print(f"{bytes(range(0x80, 0x86)).decode('latin-1')!r}  (latin-1 decodes anything)")
            print(raised_message(lambda: text.encode("latin-1")))
            """
        ),
        *predict_cells(
            """
            print("€".encode("cp1252"), "€".encode("utf-8"))
            print("€".encode("latin-1"))
            """,
            """
            `b'\\x80' b'\\xe2\\x82\\xac'`, then a `UnicodeEncodeError`. cp1252 (Windows) put `€` at
            byte 0x80, UTF-8 needs three bytes, and latin-1 has no euro sign at all (it predates
            the euro); its 0x80 is an invisible control character. That difference is why "latin-1"
            and "cp1252" files are not interchangeable.
            """,
            """
            print("€".encode("cp1252"), "€".encode())
            print(raised_message(lambda: "€".encode("latin-1")))
            """,
        ),
        md(
            """
            **BOMs (byte order marks).** UTF-16 files start with `FF FE` or `FE FF` so the
            reader knows the byte order. Some Windows tools also put `EF BB BF` (the UTF-8
            BOM) at the start of UTF-8 files, which then shows up as a stray `\\ufeff`
            character, often breaking the first CSV header. The `utf-8-sig` codec removes it
            when reading (and writes it, if you ask, for Excel).
            """
        ),
        code(
            r"""
            excel_export = io_demo / "excel_export.csv"
            excel_export.write_bytes(codecs.BOM_UTF8 + b"sku,quantity\nTEA-500,2\n")
            print(f"{excel_export.read_bytes()[:6]=}")
            with excel_export.open(encoding="utf-8", newline="") as wrong:
                print(f"utf-8:     {next(csv.reader(wrong))!r}")
            with excel_export.open(encoding="utf-8-sig", newline="") as right:
                print(f"utf-8-sig: {next(csv.reader(right))!r}")
            print(f"{'hi'.encode('utf-16')=}  (BOM + little-endian on this machine)")
            print(f"{codecs.BOM_UTF16_LE=}, {codecs.BOM_UTF16_BE=}")
            """
        ),
        md(
            """
            **Mojibake** is text decoded with the wrong encoding: `₹` written as UTF-8 and read
            as cp1252 becomes `â‚¹`. If the wrong decoding lost nothing, you can reverse it:
            encode back with the wrong codec, decode with the right one. (The third-party
            `ftfy` library automates this.) Prevention is better: declare the encoding wherever
            bytes cross a boundary (files, HTTP `Content-Type`, databases).
            """
        ),
        code(
            r"""
            original = "Café ₹240 – Diwali offer"  # every UTF-8 byte here is defined in cp1252
            garbled = original.encode("utf-8").decode("cp1252")
            print(f"{garbled=}")
            repaired = garbled.encode("cp1252").decode("utf-8")
            print(f"{repaired=}, {repaired == original=}")
            double = garbled.encode("utf-8").decode("cp1252")
            print(f"double mojibake: {double[:24]!r}...")
            """
        ),
        md(
            """
            **Error handlers** decide what happens when bytes cannot be decoded (or characters
            cannot be encoded). Pass `errors=` to `open()`, `bytes.decode` or `str.encode`.

            | Handler | Decoding bad bytes | Encoding unencodable characters | Use when |
            | --- | --- | --- | --- |
            | `strict` (default) | `UnicodeDecodeError` | `UnicodeEncodeError` | data must be correct |
            | `replace` | `�` (U+FFFD) | `?` | display, logs |
            | `ignore` | dropped | dropped | rarely: silent data loss |
            | `backslashreplace` | `\\xff` | `\\u20b9` | debugging, readable escapes |
            | `surrogateescape` | lone surrogates that round-trip | restores the original bytes | file names, pass-through of unknown bytes |
            | `xmlcharrefreplace` | (encode only) | `&#8377;` | HTML/XML output in a narrow encoding |
            """
        ),
        code(
            r"""
            damaged = "₹240 café".encode()[:-1] + b"\xff more"
            for handler in ("replace", "ignore", "backslashreplace", "surrogateescape"):
                print(f"decode {handler:<17} {damaged.decode('utf-8', errors=handler)!r}")
            print(raised_message(lambda: damaged.decode("utf-8")))
            escaped = damaged.decode("utf-8", errors="surrogateescape")
            print(
                f"surrogateescape round-trips: {escaped.encode('utf-8', errors='surrogateescape') == damaged}"
            )
            for handler in ("replace", "backslashreplace", "xmlcharrefreplace"):
                print(f"encode {handler:<17} {'₹240'.encode('ascii', errors=handler)!r}")
            """
        ),
        *predict_cells(
            """
            data = "naïve".encode()  # UTF-8 is the default
            print(len("naïve"), len(data), data.decode("latin-1"))
            """,
            """
            `5 6 naÃ¯ve`. `str.encode()` uses UTF-8 unless told otherwise. `ï` is one code
            point but two bytes in UTF-8 (`C3 AF`), so the bytes
            are one longer than the string. latin-1 decodes every byte as one character, so it
            never fails: it silently produces mojibake instead.
            """,
            """
            data = "naïve".encode()  # UTF-8 is the default
            print(len("naïve"), len(data), data.decode("latin-1"))
            """,
        ),
    ]


def _serialization_cells() -> list[NotebookNode]:
    """4.5.6 Serialization formats."""
    return [
        md(
            """
            ### 4.5.6 Serialization formats

            | Format | Module | Human-editable | Types | Safe for untrusted input | Typical use |
            | --- | --- | --- | --- | --- | --- |
            | JSON | `json`, `orjson` | yes | dict, list, str, number, bool, null | yes | APIs, configs, logs |
            | CSV | `csv` | yes (spreadsheets) | strings only | yes | tabular exchange |
            | TOML | `tomllib` (read only) | yes | + dates, tables, arrays | yes | config (`pyproject.toml`) |
            | YAML | PyYAML `safe_load` | yes | + anchors, many scalar types | **only** with `safe_load` | config (CI, Kubernetes) |
            | XML | `xml.etree`, `defusedxml` | yes | text + attributes | **only** with `defusedxml` | legacy systems, feeds, office files |
            | MessagePack | `msgpack` | no (binary) | like JSON + bytes | yes | compact JSON-like data |
            | pickle | `pickle` | no | almost any Python object | **never** (4.5.7) | caches between your own processes |

            **JSON** in brief (Unit 4.4.5 covered encoders, hooks and `Decimal`): `json.dump`
            and `json.load` take file objects.
            """
        ),
        code(
            r"""
            order = {
                "id": 7,
                "placed_at": FIXED_MOMENT.isoformat(),
                "lines": [{"sku": "TEA-500", "quantity": 2}],
                "paid": True,
            }
            order_path = io_demo / "order.json"
            with order_path.open("w", encoding="utf-8") as json_file:
                json.dump(order, json_file, indent=2)
            with order_path.open(encoding="utf-8") as json_file:
                print(f"{json.load(json_file) == order=}")
            print(order_path.read_text(encoding="utf-8")[:60] + "...")
            """
        ),
        md(
            """
            **CSV** in brief (Unit 4.4.5): `newline=""`, `DictReader`/`DictWriter`, and every
            value comes back as a string. Here a CSV is streamed into typed records:
            """
        ),
        code(
            r"""
            @dataclasses.dataclass(frozen=True)
            class StockRow:
                sku: str
                quantity: int
                unit_price: Decimal


            stock_csv = io_demo / "stock.csv"
            stock_csv.write_text(
                "sku,quantity,unit_price\nTEA-500,40,240.00\nMUG-02,6,199.00\n", encoding="utf-8"
            )
            with stock_csv.open(newline="", encoding="utf-8") as csv_file:
                rows = [
                    StockRow(row["sku"], int(row["quantity"]), Decimal(row["unit_price"]))
                    for row in csv.DictReader(csv_file)
                ]
            print(rows)
            print(f"stock value: {sum(row.quantity * row.unit_price for row in rows)}")
            """
        ),
        md(
            """
            **TOML** (`tomllib`, *New in 3.11*) is the format of `pyproject.toml`. The standard
            library only **reads** it (open the file in binary mode); writing needs a
            third-party package such as `tomli-w`. TOML has real types: integers, floats,
            booleans, dates and datetimes, arrays and nested tables.
            """
        ),
        code(
            r'''
            settings_toml = io_demo / "shop.toml"
            settings_toml.write_text(
                textwrap.dedent("""
                [store]
                name = "Pune Central"
                opened = 2019-04-01
                gst_percent = 18

                [store.hours]
                weekday = ["09:00", "21:00"]

                [[warehouses]]
                code = "PNQ1"
                capacity = 5_000
            """),
                encoding="utf-8",
            )
            with settings_toml.open("rb") as toml_file:
                settings = tomllib.load(toml_file)
            print(settings)
            print(f"{type(settings['store']['opened']).__name__=}, {settings['warehouses'][0]['capacity']=}")
            with (REPO_ROOT / "pyproject.toml").open("rb") as project_file:
                print(f"course project: {tomllib.load(project_file)['project']['name']!r}")
            print(raised_message(lambda: tomllib.loads("name = 'unterminated")))
            '''
        ),
        md(
            """
            **YAML** (PyYAML) is popular for configuration (GitHub Actions, Docker Compose,
            Kubernetes). Always use **`yaml.safe_load`**: the full loader can build arbitrary
            Python objects from tags such as `!!python/object/apply`, which turns a config file
            into code execution. `safe_load` refuses those tags. YAML's implicit typing has
            surprises: in YAML 1.1 (PyYAML) `no` and `off` are booleans and `0755` is an octal
            number.
            """
        ),
        code(
            r'''
            if importlib.util.find_spec("yaml") is None:
                print("SKIP: PyYAML is not installed (uv add pyyaml)")
            else:
                import yaml

                compose_text = textwrap.dedent("""
                    service: shop-api
                    replicas: 3
                    debug: off
                    country: NO
                    file_mode: 0755
                    ports: ["8000:8000"]
                """)
                print(yaml.safe_load(compose_text))
                print(yaml.safe_dump({"service": "shop-api", "replicas": 3, "country": "NO"}, sort_keys=False))
                tagged = "!!python/object/apply:builtins.print ['this would run on load']"
                print(raised_message(lambda: yaml.safe_load(tagged)).splitlines()[0])
            '''
        ),
        md(
            """
            `debug: off` became `False` and `country: NO` (Norway) became `False` too: quote
            values that must stay strings. The tagged document was refused by `safe_load`.

            **XML.** The standard library parses XML with `xml.etree.ElementTree`, but it is
            vulnerable to malicious documents (entity-expansion "billion laughs" attacks that
            exhaust memory, external entities in some parsers). **`defusedxml`** wraps the same
            API and refuses those constructs; use it for any XML you did not write yourself.
            `defusedxml` is not an Appendix A package; here it happens to be installed as a
            dependency of `nbconvert`, so the cell checks first.
            """
        ),
        code(
            r'''
            import xml.etree.ElementTree as ElementTree

            feed = """<orders currency="INR">
              <order id="7"><customer>Asha</customer><total>679.00</total></order>
              <order id="8"><customer>Ravi</customer><total>240.00</total></order>
            </orders>"""
            root = ElementTree.fromstring(feed)
            print(f"{root.tag=}, {root.attrib=}")
            for order_element in root.iter("order"):
                print(
                    f"  order {order_element.get('id')}: {order_element.findtext('customer')} "
                    f"{Decimal(order_element.findtext('total'))}"
                )
            print(f"{[element.text for element in root.findall('./order/customer')]=}")

            entity_bomb = (
                '<!DOCTYPE d [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]><d>&b;</d>'
            )
            if importlib.util.find_spec("defusedxml") is None:
                print("SKIP: defusedxml is not installed (not an Appendix A package)")
            else:
                import defusedxml.ElementTree as SafeElementTree

                print(f"defusedxml, normal feed: {SafeElementTree.fromstring(feed).tag!r}")
                print(
                    "defusedxml, entities:    "
                    f"{raised_message(lambda: SafeElementTree.fromstring(entity_bomb))}"
                )
            '''
        ),
        md(
            """
            **MessagePack and orjson.** MessagePack is "binary JSON": the same data model plus
            raw bytes, smaller and faster to parse. `orjson` (an Appendix A package, Unit 4.6.5)
            is a fast JSON library written in Rust that returns `bytes` and natively handles
            `datetime`, `UUID`, dataclasses and NumPy arrays. `msgpack` is not in Appendix A;
            it is installed here as a dependency of another tool, so the cell checks first.
            """
        ),
        code(
            r"""
            sample = {"id": 7, "sku": "TEA-500", "quantity": 2, "tags": ["gift", "express"], "paid": True}
            as_json = json.dumps(sample, separators=(",", ":")).encode()
            print(f"json:    {len(as_json)} bytes")
            if importlib.util.find_spec("msgpack") is None:
                print("SKIP: msgpack is not installed (not an Appendix A package)")
            else:
                import msgpack

                packed = msgpack.packb(sample)
                print(
                    f"msgpack: {len(packed)} bytes, {packed[:12].hex(' ')}..., "
                    f"round trip {msgpack.unpackb(packed) == sample}"
                )
                print(f"msgpack keeps bytes: {msgpack.unpackb(msgpack.packb({'png': png_bytes[:4]}))}")
            if importlib.util.find_spec("orjson") is None:
                print("SKIP: orjson is not installed (uv add orjson)")
            else:
                import orjson

                print(f"orjson:  {orjson.dumps(sample)[:40]!r}... ({type(orjson.dumps(sample)).__name__})")
                print(f"orjson datetime + UUID: {orjson.dumps({'at': FIXED_MOMENT, 'id': uuid.UUID(int=7)})!r}")
            """
        ),
    ]


def _pickle_cells() -> list[NotebookNode]:
    """4.5.7 pickle."""
    return [
        md(
            """
            ### 4.5.7 `pickle`

            `pickle` serializes almost any Python object graph (instances of your classes,
            nested containers, shared references, cycles) to bytes and back. It is
            Python-specific, and the bytes are **instructions** for rebuilding objects.

            **Protocols** are format versions: 0 is ASCII, 2 added efficient classes, 4 (3.4)
            large objects, 5 (3.8) out-of-band buffers. `pickle.DEFAULT_PROTOCOL` is 5 since
            Python 3.14 (4 before). Higher protocols are smaller and faster; older Pythons
            cannot read newer protocols.
            """
        ),
        code(
            r"""
            @dataclasses.dataclass
            class Basket:
                customer: str
                items: dict[str, int]
                created: datetime


            basket = Basket("Asha", {"TEA-500": 2, "MUG-02": 1}, FIXED_MOMENT)
            shared = [basket, basket]  # the same object twice
            for protocol in (0, 2, pickle.DEFAULT_PROTOCOL):
                print(f"protocol {protocol}: {len(pickle.dumps(shared, protocol=protocol))} bytes")
            restored = pickle.loads(pickle.dumps(shared))
            print(f"{restored[0] == basket=}, {restored[0] is restored[1]=}  (shared reference kept)")
            print(f"{pickle.DEFAULT_PROTOCOL=}, {pickle.HIGHEST_PROTOCOL=}")
            print(f"{pickle.dumps(42, protocol=0)=}")
            """
        ),
        md(
            """
            **Customizing: `__getstate__` / `__setstate__`.** By default pickle saves the
            instance `__dict__`. Override `__getstate__` to leave out what cannot or should not
            be saved (open connections, locks, caches, secrets) and `__setstate__` to rebuild
            it on load.
            """
        ),
        code(
            r'''
            class PriceCache:
                """Holds an open SQLite connection (unpicklable) plus cached prices."""

                def __init__(self, database: str) -> None:
                    self.database = database
                    self.prices = {"TEA-500": 240}
                    self.connection = sqlite3.connect(database)

                def __getstate__(self) -> dict[str, object]:
                    state = self.__dict__.copy()
                    del state["connection"]  # not picklable; reopened on load
                    return state

                def __setstate__(self, state: dict[str, object]) -> None:
                    self.__dict__.update(state)
                    self.connection = sqlite3.connect(self.database)


            print(raised_message(lambda: pickle.dumps(sqlite3.connect(":memory:"))))
            cache_copy = pickle.loads(pickle.dumps(PriceCache(":memory:")))
            print(f"{cache_copy.prices=}, {type(cache_copy.connection).__name__=}")
            '''
        ),
        md(
            """
            **`__reduce__`** is the lower-level hook: it returns `(callable, arguments)`, and
            unpickling **calls** `callable(*arguments)`. Extension types and classes whose
            constructor must run use it.
            """
        ),
        code(
            r'''
            import pickletools


            class Sku:
                """Validated in __init__, so unpickling must go through __init__ too."""

                def __init__(self, code: str) -> None:
                    if not code.isupper():
                        raise ValueError(f"invalid SKU {code!r}")
                    self.code = code

                def __reduce__(self) -> tuple[type, tuple[str]]:
                    return (Sku, (self.code,))

                def __repr__(self) -> str:
                    return f"Sku({self.code!r})"


            print(f"{pickle.loads(pickle.dumps(Sku('TEA-500')))=}")
            opcode_listing = io.StringIO()  # a StringIO target also keeps the listing free of colour codes
            pickletools.dis(pickle.dumps(Sku("TEA-500"), protocol=2), out=opcode_listing)
            print(opcode_listing.getvalue())  # GLOBAL names the callable, REDUCE calls it
            '''
        ),
        md(
            """
            **The remote-code-execution risk.** Because unpickling calls whatever callable the
            data names, **loading a pickle runs code chosen by whoever wrote the bytes**. The
            harmless demonstration below names a function that only appends a message to a
            list; a real attacker would name something dangerous instead, and `loads` would
            call it before your code ever sees the "object". There is no safe way to unpickle
            untrusted data: signatures (`hmac`) can prove the bytes are yours, but the rule is
            simply to never accept pickles from users, the network or shared storage you do
            not control.
            """
        ),
        code(
            r'''
            side_effects: list[str] = []


            def record_side_effect(message: str) -> str:
                """Stands in for any callable an attacker could name."""
                side_effects.append(message)
                return "not the object you expected"


            class Innocent:
                def __reduce__(self) -> tuple[Callable[[str], str], tuple[str]]:
                    return (record_side_effect, ("ran during pickle.loads",))


            untrusted_bytes = pickle.dumps(Innocent())  # pretend this arrived over the network
            result = pickle.loads(untrusted_bytes)  # the callable runs here
            print(f"{result=}")
            print(f"{side_effects=}")
            '''
        ),
        md(
            """
            **Legitimate uses** are the ones where both ends are your own trusted code:
            `multiprocessing` and `concurrent.futures` send arguments to worker processes with
            pickle (Phase 5), caches on local disk (`shelve`, `joblib`), and saving
            intermediate results of a long computation. For anything that crosses a trust
            boundary or must outlive a Python version, use JSON, MessagePack or a database.
            `shelve` is a persistent dict built on pickle:
            """
        ),
        code(
            r"""
            import shelve

            with shelve.open(str(io_demo / "report_cache")) as cache:
                cache["2026-11"] = {"orders": 412, "revenue": Decimal("187340.50")}
            with shelve.open(str(io_demo / "report_cache")) as cache:
                print(f"{dict(cache)=}")
            """
        ),
    ]


def _compression_cells() -> list[NotebookNode]:
    """4.5.8 Compression and archives."""
    return [
        md(
            """
            ### 4.5.8 Compression and archives

            Four compressors in the standard library share a file-like API (`open`,
            `compress`, `decompress`):

            | Module | Algorithm | Speed / ratio | Extension |
            | --- | --- | --- | --- |
            | `gzip` (`zlib`) | DEFLATE | fast, moderate ratio; universal | `.gz` |
            | `bz2` | Burrows–Wheeler | slower, better ratio | `.bz2` |
            | `lzma` | LZMA2 (xz) | slowest to compress, best ratio | `.xz` |
            | `compression.zstd` | Zstandard (*New in 3.14*) | very fast at good ratios; tunable levels | `.zst` |

            *New in 3.14:* the `compression` package also re-exports the others
            (`compression.gzip`, …). Sizes below are deterministic for this input; times vary.
            """
        ),
        code(
            r"""
            log_bytes = access_log.read_bytes()
            compressors = {"gzip": gzip, "bz2": bz2, "lzma": lzma}
            if sys.version_info >= (3, 14):
                from compression import zstd

                compressors["zstd"] = zstd
            print(f"original: {len(log_bytes):>6} bytes")
            for name, module in compressors.items():
                packed = module.compress(log_bytes)
                assert module.decompress(packed) == log_bytes
                print(f"{name:<8}: {len(packed):>6} bytes ({len(packed) / len(log_bytes):.1%})")
            """
        ),
        md(
            """
            The `open()` functions return file objects, so compressed files are read and
            written like plain ones, line by line, in text mode with an encoding:
            """
        ),
        code(
            r"""
            gzip_path = io_demo / "access.log.gz"
            with gzip.open(gzip_path, "wt", encoding="utf-8") as compressed:
                compressed.write(access_log.read_text(encoding="utf-8"))
            with gzip.open(gzip_path, "rt", encoding="utf-8") as compressed:
                server_errors = sum(1 for line in compressed if line.rstrip().endswith("500"))
            print(f"{gzip_path.stat().st_size=}, {server_errors=}")
            print(f"{gzip_path.read_bytes()[:2].hex(' ')=}  (gzip magic number 1f 8b)")
            if sys.version_info >= (3, 14):
                with zstd.open(io_demo / "access.log.zst", "wt", encoding="utf-8") as compressed:
                    compressed.write("TEA-500,2\n")
                print(
                    "zstd text round trip: "
                    f"{zstd.open(io_demo / 'access.log.zst', 'rt', encoding='utf-8').read()!r}"
                )
            """
        ),
        md(
            """
            **`zipfile`** reads and writes ZIP archives (also `.docx`, `.xlsx`, `.whl`, `.jar`).
            Choose the compression per archive (`ZIP_DEFLATED`, `ZIP_BZIP2`, `ZIP_LZMA`,
            *New in 3.14* `ZIP_ZSTANDARD`); `infolist()` shows each member's sizes; `writestr`
            adds data without a file on disk.
            """
        ),
        code(
            r"""
            bundle_path = io_demo / "monthly_report.zip"
            with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
                bundle.write(access_log, arcname="logs/access.log")
                bundle.writestr("summary.json", json.dumps({"orders": 1000, "errors": len(errors)}))
            with zipfile.ZipFile(bundle_path) as bundle:
                for member in bundle.infolist():
                    print(f"  {member.filename:<16} {member.file_size:>6} -> {member.compress_size:>5} bytes")
                print(f"{json.loads(bundle.read('summary.json'))=}")
                print(f"{bundle.testzip() is None=}  (all CRCs good)")
            """
        ),
        md(
            """
            **`tarfile`** handles `.tar`, `.tar.gz`, `.tar.xz` (and `.tar.zst` in 3.14). Tar
            members can be absolute paths, `..` paths, symlinks or device files, so extracting
            an untrusted archive could overwrite files anywhere. Since Python 3.12,
            `extractall(..., filter="data")` refuses all of that, and *Changed in 3.14:*
            `"data"` is the **default** filter. Always pass it explicitly so the intent is clear
            and older versions behave the same.
            """
        ),
        code(
            r"""
            tar_path = io_demo / "backup.tar.gz"
            with tarfile.open(tar_path, "w:gz") as archive:
                archive.add(access_log, arcname="logs/access.log")
                archive.add(stock_csv, arcname="data/stock.csv")
            with tarfile.open(tar_path) as archive:
                print(f"{archive.getnames()=}")
                archive.extractall(fresh_dir("restored"), filter="data")
            restored = UNIT45_DIR / "restored"
            restored_files = sorted(
                p.relative_to(restored).as_posix() for p in restored.rglob("*") if p.is_file()
            )
            print(f"{restored_files=}")

            hostile_path = io_demo / "hostile.tar"
            with tarfile.open(hostile_path, "w") as archive:
                member = tarfile.TarInfo("../../outside.txt")
                member.size = 4
                archive.addfile(member, io.BytesIO(b"oops"))
            with tarfile.open(hostile_path) as archive:
                print(raised_message(lambda: archive.extractall(fresh_dir("hostile_out"), filter="data")))
            print(f"{(UNIT45_DIR / 'outside.txt').exists()=}")
            """
        ),
    ]


def _sqlite_cells() -> list[NotebookNode]:
    """4.5.9 sqlite3."""
    return [
        md(
            """
            ### 4.5.9 `sqlite3`

            SQLite is a complete SQL database in one file (or in memory), built into Python.
            It is the right choice for local apps, caches, tests and prototypes, and the
            habits carry over to PostgreSQL in Phase 6. **Connections**: `sqlite3.connect(path)`
            (`":memory:"` for a throwaway database); `connection.execute(sql, parameters)`
            returns a cursor; `fetchone`/`fetchall` or iteration read rows.
            """
        ),
        code(
            r"""
            database_path = io_demo / "shop.db"
            database_path.unlink(missing_ok=True)
            connection = sqlite3.connect(database_path)
            connection.execute(
                "CREATE TABLE products (sku TEXT PRIMARY KEY, name TEXT NOT NULL, price_paise INTEGER NOT NULL)"
            )
            connection.execute("INSERT INTO products VALUES (?, ?, ?)", ("TEA-500", "Masala tea 500 g", 24000))
            connection.commit()
            print(f"{connection.execute('SELECT * FROM products').fetchall()=}")
            print(
                f"{sqlite3.sqlite_version=}, {connection.execute('SELECT COUNT(*) FROM products').fetchone()=}"
            )
            """
        ),
        md(
            """
            **Parameterized queries.** Values go in as **parameters**: `?` placeholders with a
            tuple, or `:name` placeholders with a dict. The driver sends them separately from
            the SQL text, so a value can never change the query's structure. **`executemany`**
            runs one statement for every item of an iterable, far faster than a Python loop of
            `execute` calls.
            """
        ),
        code(
            r"""
            catalogue = [
                ("MUG-02", "Steel mug", 19900),
                ("JAR-750", "Pickle jar 750 ml", 35000),
                ("CHAI-1", "O'Brien's chai", 15000),
            ]
            connection.executemany("INSERT INTO products VALUES (?, ?, ?)", catalogue)
            connection.commit()
            cheap = connection.execute(
                "SELECT sku, price_paise FROM products WHERE price_paise < :limit ORDER BY price_paise",
                {"limit": 20000},
            )
            print(f"{cheap.fetchall()=}")
            print(
                f"{connection.execute('SELECT name FROM products WHERE sku = ?', ('CHAI-1',)).fetchone()=}"
                "  (the quote is just data)"
            )
            """
        ),
        md(
            """
            **SQL injection** happens when user input is pasted into the SQL **text**. The
            demonstration runs against this throwaway database only: a crafted "SKU" turns the
            `WHERE` clause into something that is always true and returns every row. The
            parameterized version treats the same input as an ordinary (non-matching) value.
            Never build SQL with f-strings, `%` or `+` from input; for dynamic identifiers
            (column names) use an allow-list.
            """
        ),
        code(
            r"""
            user_input = "nothing' OR '1'='1"
            unsafe_sql = f"SELECT sku FROM products WHERE sku = '{user_input}'"  # never do this
            print(f"{unsafe_sql=}")
            print(f"string-built query returns: {connection.execute(unsafe_sql).fetchall()}")
            print(
                "parameterized query returns: "
                f"{connection.execute('SELECT sku FROM products WHERE sku = ?', (user_input,)).fetchall()}"
            )

            SORTABLE_COLUMNS = {"sku", "name", "price_paise"}


            def products_sorted_by(column: str) -> list[tuple[str, ...]]:
                if column not in SORTABLE_COLUMNS:  # identifiers cannot be parameters
                    raise ValueError(f"cannot sort by {column!r}")
                return connection.execute(f"SELECT sku FROM products ORDER BY {column}").fetchall()


            print(f"{products_sorted_by('price_paise')=}")
            print(raised_message(lambda: products_sorted_by("price_paise; DROP TABLE products")))
            """
        ),
        md(
            """
            **Transactions.** Changes are invisible to other connections and not durable until
            `commit()`; `rollback()` discards them. Using the connection as a **context
            manager** commits if the block succeeds and rolls back if it raises (it does *not*
            close the connection). Multi-step changes, such as moving stock between
            warehouses, must happen in one transaction so they cannot half-happen. *New in
            3.12:* `autocommit=` gives explicit control of the transaction mode.
            """
        ),
        code(
            r"""
            connection.execute(
                "CREATE TABLE stock (warehouse TEXT, sku TEXT, quantity INTEGER CHECK (quantity >= 0),"
                " PRIMARY KEY (warehouse, sku))"
            )
            connection.executemany(
                "INSERT INTO stock VALUES (?, ?, ?)", [("PNQ1", "TEA-500", 10), ("BLR1", "TEA-500", 0)]
            )
            connection.commit()


            def transfer(quantity: int) -> None:
                with connection:  # commit on success, rollback on error
                    connection.execute(
                        "UPDATE stock SET quantity = quantity + ? WHERE warehouse = 'BLR1' AND sku = 'TEA-500'",
                        (quantity,),
                    )
                    connection.execute(
                        "UPDATE stock SET quantity = quantity - ? WHERE warehouse = 'PNQ1' AND sku = 'TEA-500'",
                        (quantity,),
                    )


            transfer(4)
            print(
                "after transferring 4:  "
                f"{connection.execute('SELECT warehouse, quantity FROM stock ORDER BY warehouse').fetchall()}"
            )
            print(raised_message(lambda: transfer(50)))
            print(
                "after failed transfer: "
                f"{connection.execute('SELECT warehouse, quantity FROM stock ORDER BY warehouse').fetchall()}"
                "  (rolled back)"
            )
            """
        ),
        md(
            """
            **`sqlite3.Row`.** Set `connection.row_factory = sqlite3.Row` and rows support
            access by column name and `keys()` as well as by index, so code no longer depends
            on column order. (Any callable works as a row factory, for example one that builds
            a dataclass.)
            """
        ),
        code(
            r"""
            connection.row_factory = sqlite3.Row
            product = connection.execute("SELECT * FROM products WHERE sku = ?", ("TEA-500",)).fetchone()
            print(f"{product['name']=}, {product[2]=}, {product.keys()=}, {dict(product)=}")
            connection.row_factory = lambda cursor, row: StockRow(row[0], row[1], Decimal(row[2]) / 100)
            first_two = connection.execute(
                "SELECT sku, 1, price_paise FROM products ORDER BY sku LIMIT 2"
            ).fetchall()
            print(f"{first_two=}")
            connection.row_factory = None
            connection.close()
            """
        ),
        md(
            """
            **Under the hood: the query plan.** `EXPLAIN QUERY PLAN` shows how SQLite will run
            a query: a primary-key lookup uses the index (`SEARCH ... USING INDEX`), a filter on
            an unindexed column reads every row (`SCAN`). Adding an index changes the plan.
            """
        ),
        code(
            r"""
            with sqlite3.connect(database_path) as inspector:
                for sql in (
                    "SELECT * FROM products WHERE sku = 'MUG-02'",
                    "SELECT * FROM products WHERE price_paise > 20000",
                ):
                    print(f"{sql}\n  -> {[row[3] for row in inspector.execute('EXPLAIN QUERY PLAN ' + sql)]}")
                inspector.execute("CREATE INDEX IF NOT EXISTS products_by_price ON products (price_paise)")
                plan_rows = inspector.execute("EXPLAIN QUERY PLAN " + sql).fetchall()  # sql: the price query
                print(f"with an index -> {[row[3] for row in plan_rows]}")
            inspector.close()
            """
        ),
    ]


def _safety_cells() -> list[NotebookNode]:
    """4.5.10 File-system safety."""
    return [
        md(
            """
            ### 4.5.10 File-system safety

            Whenever a path comes from outside (an upload's file name, a URL segment, a zip
            member, a CLI argument), check that it stays inside the folder you meant before
            touching the disk. The robust check: **resolve** the joined path (which removes
            `..` and follows symlinks) and test `Path.is_relative_to(base)` (*New in 3.9*).
            String checks such as `".." in name` or `startswith(base)` miss absolute paths,
            symlinks and prefixes like `/srv/uploads-old`.
            """
        ),
        code(
            r'''
            uploads = fresh_dir("uploads")
            (uploads / "invoices").mkdir()
            (uploads / "shortcut").symlink_to(UNIT45_DIR)  # a symlink pointing outside


            def safe_path(base: Path, requested: str) -> Path:
                """The resolved path of requested inside base; ValueError if it would escape."""
                candidate = (base / requested).resolve()
                if not candidate.is_relative_to(base.resolve()):
                    raise ValueError(f"{requested!r} escapes {base.name}/")
                return candidate


            for requested in (
                "invoices/7.pdf",
                "../shop.db",
                "/etc/passwd",
                "invoices/../../shop.db",
                "shortcut/shop.db",
            ):
                print(
                    f"  {requested!r:<26} "
                    f"{raised_message(lambda requested=requested: safe_path(uploads, requested))}"
                )
            print(
                "naive startswith check is fooled: "
                f"{str(UNIT45_DIR / 'uploads-old' / 'x').startswith(str(uploads))}"
            )
            '''
        ),
        md(
            """
            `raised_message` prints `no error` for the allowed path; every escape attempt is
            refused, including the symlink, which only `resolve()` exposes. The last line shows
            why prefix checks on strings are wrong: `uploads-old` "starts with" `uploads`.
            The same check protects zip extraction (Lab 4.5, exercise 6); `tarfile` has it built
            in through `filter="data"` (4.5.8).
            """
        ),
    ]


LAB_SETUP_SOURCE = r"""
LAB45_DIR = find_repo_root() / "notebooks" / "_scratch" / "unit45" / "lab"
LAB45_DIR.mkdir(parents=True, exist_ok=True)
print(f"lab files go to {LAB45_DIR.relative_to(find_repo_root()).as_posix()}/")
"""


def _lab_cells_part_1() -> list[NotebookNode]:
    """Lab 4.5 exercises 1–3."""
    return [
        md(
            """
            ### Lab 4.5

            Six exercises; replace each `raise NotImplementedError`, then run the check cell.
            The checks build their own files under `notebooks/_scratch/unit45/lab/`. Until you
            finish, they print FAIL; that is expected.
            """
        ),
        code(LAB_SETUP_SOURCE),
        md(
            """
            #### Exercise 1 — `tail(path, n)` reading backwards with `seek`

            Return the last `n` lines of a UTF-8 text file as a list of strings without their
            line endings, **without reading the whole file**: open it in binary mode, `seek`
            to the end and read blocks of `chunk_size` bytes backwards until you have more than
            `n` newlines (or reach the start), then decode. A final line without a trailing
            newline counts as a line. `n <= 0` returns `[]`. Decode only after joining the
            blocks: a multi-byte character can straddle two blocks.
            """
        ),
        code(
            r'''
            def tail(path: Path, n: int, chunk_size: int = 4096) -> list[str]:
                """The last n lines of a UTF-8 file, read backwards in binary chunks."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 1:"),
        code(
            r"""
            big_log = LAB45_DIR / "big.log"
            big_log.write_text(
                "".join(f"line {number} ₹{number * 10}\n" for number in range(1, 20_001)), encoding="utf-8"
            )
            no_newline = LAB45_DIR / "no_newline.txt"
            no_newline.write_text("first\nsecond\nthird", encoding="utf-8")
            (LAB45_DIR / "empty.txt").write_text("", encoding="utf-8")
            expected_tail = big_log.read_text(encoding="utf-8").splitlines()[-5:]
            run_checks(
                [
                    ("last 5 lines", lambda: tail(big_log, 5), expected_tail),
                    ("tiny chunks (multi-byte split)", lambda: tail(big_log, 5, chunk_size=7), expected_tail),
                    ("no trailing newline", lambda: tail(no_newline, 2), ["second", "third"]),
                    ("n larger than the file", lambda: tail(no_newline, 10), ["first", "second", "third"]),
                    ("empty file", lambda: tail(LAB45_DIR / "empty.txt", 3), []),
                    ("n = 0", lambda: tail(big_log, 0), []),
                    (
                        "uses seek, not read_text",
                        lambda: (
                            "seek" in inspect.getsource(tail) and "read_text" not in inspect.getsource(tail)
                        ),
                        True,
                    ),
                ]
            )
            """
        ),
        md(
            """
            #### Exercise 2 — atomic `write_json(path, data)`

            Write `json.dumps(data, indent=2, ensure_ascii=False) + "\\n"` to `path`
            atomically: serialize first, write to a temporary file in the same folder, flush
            and `fsync` it, then `os.replace` it over `path`. If anything fails (for example
            `data` is not JSON-serializable), re-raise the error, leave any existing file
            unchanged and leave no temporary file behind.
            """
        ),
        code(
            r'''
            def write_json(path: Path, data: object) -> None:
                """Atomically replace path with data as pretty-printed JSON."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 2:"),
        code(
            r"""
            json_dir = LAB45_DIR / "json_out"
            shutil.rmtree(json_dir, ignore_errors=True)
            json_dir.mkdir()
            settings_target = json_dir / "settings.json"


            def write_then_read(data: object) -> str:
                write_json(settings_target, data)
                return settings_target.read_text(encoding="utf-8")


            def failed_write_keeps_old() -> tuple[str, str, list[str]]:
                write_json(settings_target, {"currency": "₹"})
                error = raised_message(lambda: write_json(settings_target, {"bad": {1, 2}}))
                leftovers = sorted(path.name for path in json_dir.iterdir() if path.name != "settings.json")
                return error.split(":")[0], settings_target.read_text(encoding="utf-8"), leftovers


            run_checks(
                [
                    (
                        "writes pretty JSON",
                        lambda: write_then_read({"gst": 18, "city": "Pune"}),
                        '{\n  "gst": 18,\n  "city": "Pune"\n}\n',
                    ),
                    ("keeps non-ASCII", lambda: write_then_read(["₹"]), '[\n  "₹"\n]\n'),
                    (
                        "overwrites",
                        lambda: (write_then_read({"v": 1}), write_then_read({"v": 2}))[1],
                        '{\n  "v": 2\n}\n',
                    ),
                    (
                        "failure leaves old file, no temp files",
                        failed_write_keeps_old,
                        ("TypeError", '{\n  "currency": "₹"\n}\n', []),
                    ),
                    (
                        "uses os.replace and fsync",
                        lambda: all(word in inspect.getsource(write_json) for word in ("os.replace", "fsync")),
                        True,
                    ),
                ]
            )
            """
        ),
        md(
            """
            #### Exercise 3 — a CSV → SQLite importer

            `import_orders(csv_path, connection)` reads a CSV with the header
            `order_id,customer,sku,quantity,unit_price` and inserts every row into a table
            `orders(order_id INTEGER PRIMARY KEY, customer TEXT, sku TEXT, quantity INTEGER,
            unit_price TEXT)` (create it if it does not exist; keep `unit_price` as text so
            `Decimal` values survive). Use **parameterized** `executemany` inside **one
            transaction**: if any row is invalid (quantity not a positive integer, or a
            duplicate `order_id`), raise `ValueError` and insert **nothing** from that file.
            Return the number of rows inserted.
            """
        ),
        code(
            r'''
            def import_orders(csv_path: Path, connection: sqlite3.Connection) -> int:
                """Import a CSV of orders in one transaction; return the number of rows."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 3:"),
        code(
            r"""
            HEADER = "order_id,customer,sku,quantity,unit_price\n"
            good_csv, bad_csv, duplicate_csv = (
                LAB45_DIR / name for name in ("orders_good.csv", "orders_bad.csv", "orders_dup.csv")
            )
            good_csv.write_text(
                HEADER
                + '1,Asha,TEA-500,2,240.00\n2,O\'Brien,MUG-02,1,199.00\n3,"Rao, Ravi",JAR-750,3,350.50\n',
                encoding="utf-8",
            )
            bad_csv.write_text(
                HEADER + "4,Meera,TEA-500,1,240.00\n5,John,MUG-02,two,199.00\n", encoding="utf-8"
            )
            duplicate_csv.write_text(
                HEADER + "6,Fatima,TEA-500,1,240.00\n1,Asha,TEA-500,9,240.00\n", encoding="utf-8"
            )


            def import_story() -> dict[str, object]:
                database = sqlite3.connect(":memory:")
                story: dict[str, object] = {"good": import_orders(good_csv, database)}
                story["bad"] = raised_message(lambda: import_orders(bad_csv, database)).split(":")[0]
                story["duplicate"] = raised_message(lambda: import_orders(duplicate_csv, database)).split(":")[
                    0
                ]
                story["rows"] = database.execute(
                    "SELECT order_id, customer, quantity, unit_price FROM orders ORDER BY order_id"
                ).fetchall()
                database.close()
                return story


            run_checks(
                [
                    ("rows inserted", lambda: import_story()["good"], 3),
                    (
                        "quotes and commas stored as data",
                        lambda: [row[1] for row in import_story()["rows"]],
                        ["Asha", "O'Brien", "Rao, Ravi"],
                    ),
                    ("types", lambda: import_story()["rows"][2], (3, "Rao, Ravi", 3, "350.50")),
                    ("invalid quantity -> ValueError", lambda: import_story()["bad"], "ValueError"),
                    ("duplicate id -> ValueError", lambda: import_story()["duplicate"], "ValueError"),
                    ("failed files insert nothing", lambda: len(import_story()["rows"]), 3),
                    (
                        "uses executemany with placeholders",
                        lambda: (
                            "executemany" in inspect.getsource(import_orders)
                            and "?" in inspect.getsource(import_orders)
                        ),
                        True,
                    ),
                ]
            )
            """
        ),
    ]


def _lab_cells_part_2() -> list[NotebookNode]:
    """Lab 4.5 exercises 4–6."""
    return [
        md(
            """
            #### Exercise 4 — a binary header parser with `struct`

            A WAV file starts with a little-endian RIFF header: `b"RIFF"`, a 4-byte file size
            minus 8, `b"WAVE"`, then a `b"fmt "` chunk (4-byte size 16, 2-byte audio format
            (1 = PCM), 2-byte channels, 4-byte sample rate, 4-byte byte rate, 2-byte block
            align, 2-byte bits per sample), then a `b"data"` chunk header (4-byte size).
            `parse_wav_header(data)` returns a dict with `channels`, `sample_rate`,
            `bits_per_sample`, `data_size` and `duration_seconds` (`data_size / byte_rate`,
            rounded to 3 places). Raise `ValueError` if the magic values are wrong or `data`
            is shorter than 44 bytes.
            """
        ),
        code(
            r'''
            def parse_wav_header(data: bytes) -> dict[str, int | float]:
                """Fields of a canonical 44-byte PCM WAV header."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 4 (the WAV files are written with the standard `wave` module):"),
        code(
            r"""
            def make_wav(channels: int, sample_rate: int, sample_width: int, frames: int) -> bytes:
                buffer = io.BytesIO()
                with wave.open(buffer, "wb") as wav_file:
                    wav_file.setnchannels(channels)
                    wav_file.setsampwidth(sample_width)
                    wav_file.setframerate(sample_rate)
                    wav_file.writeframes(bytes(frames * channels * sample_width))
                return buffer.getvalue()


            run_checks(
                [
                    (
                        "mono 8 kHz 16-bit",
                        lambda: parse_wav_header(make_wav(1, 8000, 2, 4000)),
                        {
                            "channels": 1,
                            "sample_rate": 8000,
                            "bits_per_sample": 16,
                            "data_size": 8000,
                            "duration_seconds": 0.5,
                        },
                    ),
                    (
                        "stereo 44.1 kHz 16-bit",
                        lambda: parse_wav_header(make_wav(2, 44_100, 2, 44_100)),
                        {
                            "channels": 2,
                            "sample_rate": 44_100,
                            "bits_per_sample": 16,
                            "data_size": 176_400,
                            "duration_seconds": 1.0,
                        },
                    ),
                    ("8-bit", lambda: parse_wav_header(make_wav(1, 22_050, 1, 11_025))["bits_per_sample"], 8),
                    (
                        "not RIFF",
                        lambda: raised_message(
                            lambda: parse_wav_header(b"RIFX" + make_wav(1, 8000, 2, 10)[4:])
                        ).split(":")[0],
                        "ValueError",
                    ),
                    (
                        "not WAVE",
                        lambda: raised_message(
                            lambda: parse_wav_header(make_wav(1, 8000, 2, 10).replace(b"WAVE", b"AVI "))
                        ).split(":")[0],
                        "ValueError",
                    ),
                    (
                        "too short",
                        lambda: raised_message(lambda: parse_wav_header(b"RIFF")).split(":")[0],
                        "ValueError",
                    ),
                    ("uses struct", lambda: "struct" in inspect.getsource(parse_wav_header), True),
                ]
            )
            """
        ),
        md(
            """
            #### Exercise 5 — a JSON encoder for `Decimal`, `datetime`, `UUID` and dataclasses

            `RichJSONEncoder` (a `json.JSONEncoder` subclass) encodes `Decimal` as a string
            (`"679.00"`), `datetime` and `date` with `isoformat()`, `UUID` as its string form,
            and dataclass instances as dicts of their fields (nested values encoded the same
            way). Anything else raises `TypeError` as usual.
            """
        ),
        code(
            r'''
            class RichJSONEncoder(json.JSONEncoder):
                """JSON for Decimal, datetime/date, UUID and dataclasses."""

                def default(self, value: object) -> object:
                    raise NotImplementedError
            '''
        ),
        md("Check exercise 5:"),
        code(
            r"""
            @dataclasses.dataclass
            class LabLine:
                sku: str
                price: Decimal


            @dataclasses.dataclass
            class LabOrder:
                order_id: uuid.UUID
                placed_at: datetime
                lines: list[LabLine]


            LAB_MOMENT = datetime(2026, 11, 7, 9, 30, tzinfo=UTC)
            ORDER_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
            sample_order = LabOrder(ORDER_ID, LAB_MOMENT, [LabLine("TEA-500", Decimal("240.00"))])
            run_checks(
                [
                    (
                        "Decimal",
                        lambda: json.dumps({"total": Decimal("679.00")}, cls=RichJSONEncoder),
                        '{"total": "679.00"}',
                    ),
                    (
                        "datetime and date",
                        lambda: json.dumps([LAB_MOMENT, date(2026, 11, 7)], cls=RichJSONEncoder),
                        '["2026-11-07T09:30:00+00:00", "2026-11-07"]',
                    ),
                    (
                        "UUID",
                        lambda: json.dumps(ORDER_ID, cls=RichJSONEncoder),
                        '"12345678-1234-5678-1234-567812345678"',
                    ),
                    (
                        "nested dataclasses",
                        lambda: json.loads(json.dumps(sample_order, cls=RichJSONEncoder)),
                        {
                            "order_id": str(ORDER_ID),
                            "placed_at": "2026-11-07T09:30:00+00:00",
                            "lines": [{"sku": "TEA-500", "price": "240.00"}],
                        },
                    ),
                    (
                        "dataclass class itself is not encoded",
                        lambda: raised_message(lambda: json.dumps(LabLine, cls=RichJSONEncoder)).split(":")[0],
                        "TypeError",
                    ),
                    (
                        "other types still fail",
                        lambda: raised_message(lambda: json.dumps({1, 2}, cls=RichJSONEncoder)).split(":")[0],
                        "TypeError",
                    ),
                ]
            )
            """
        ),
        md(
            """
            #### Exercise 6 — safe zip extraction that rejects path traversal

            `safe_extract_zip(archive, destination)` extracts a ZIP file into `destination`
            (create it if needed) and returns the sorted list of extracted file paths relative
            to `destination` (POSIX strings, directories excluded). Before extracting
            **anything**, check every member: if any would land outside `destination`
            (absolute names, `..` components, or a resolved path not relative to the resolved
            destination), raise `ValueError` naming the member and extract nothing.
            """
        ),
        code(
            r'''
            def safe_extract_zip(archive: Path, destination: Path) -> list[str]:
                """Extract archive into destination, refusing any member that escapes it."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 6:"),
        code(
            r"""
            def make_zip(name: str, members: dict[str, str]) -> Path:
                path = LAB45_DIR / name
                with zipfile.ZipFile(path, "w") as archive:
                    for member_name, text in members.items():
                        archive.writestr(member_name, text)
                return path


            def extract_into(archive: Path, folder_name: str) -> tuple[str, list[str]]:
                destination = LAB45_DIR / folder_name
                shutil.rmtree(destination, ignore_errors=True)
                outcome = raised_message(lambda: safe_extract_zip(archive, destination))
                written = (
                    sorted(
                        path.relative_to(destination).as_posix()
                        for path in destination.rglob("*")
                        if path.is_file()
                    )
                    if destination.exists()
                    else []
                )
                return outcome.split(":")[0], written


            def read_if_exists(path: Path) -> str | None:
                return path.read_text() if path.exists() else None


            shutil.rmtree(LAB45_DIR / "extract_good", ignore_errors=True)  # start clean on every run
            good_zip = make_zip(
                "good.zip",
                {"invoices/7.txt": "679.00", "invoices/8.txt": "240.00", "readme.txt": "hi", "empty/": ""},
            )
            run_checks(
                [
                    (
                        "good archive",
                        lambda: safe_extract_zip(good_zip, LAB45_DIR / "extract_good"),
                        ["invoices/7.txt", "invoices/8.txt", "readme.txt"],
                    ),
                    (
                        "contents",
                        lambda: read_if_exists(LAB45_DIR / "extract_good" / "invoices" / "7.txt"),
                        "679.00",
                    ),
                    (
                        "'..' member",
                        lambda: extract_into(
                            make_zip("dotdot.zip", {"ok.txt": "1", "../evil.txt": "x"}), "extract_dotdot"
                        ),
                        ("ValueError", []),
                    ),
                    (
                        "nested '..'",
                        lambda: extract_into(
                            make_zip("nested.zip", {"a/../../evil.txt": "x"}), "extract_nested"
                        ),
                        ("ValueError", []),
                    ),
                    (
                        "absolute member",
                        lambda: extract_into(
                            make_zip("absolute.zip", {"ok.txt": "1", "/tmp/evil.txt": "x"}), "extract_absolute"
                        ),
                        ("ValueError", []),
                    ),
                    ("nothing escaped", lambda: (LAB45_DIR.parent / "evil.txt").exists(), False),
                ]
            )
            """
        ),
    ]


def _recap_cells() -> list[NotebookNode]:
    """Recap for Unit 4.5."""
    return [
        md(
            """
            ### Recap — Unit 4.5

            | Concept | One-line takeaway | JS / Node equivalent |
            | --- | --- | --- |
            | `open()` | Mode = action + text/binary; `TextIOWrapper` → buffer → `FileIO`; pass `encoding`; `newline=""` for CSV | `fs.open`, streams |
            | Patterns | Iterate lines; `read(chunk)` with walrus; byte offsets with `seek`/`tell` in binary; `flush` + `fsync`; temp file + `os.replace` | `createReadStream`, `fs.rename` |
            | In-memory / temp | `StringIO`, `BytesIO` for tests; `tempfile` for real files that clean up | `Buffer`, `os.tmpdir()` |
            | Binary | `struct` with explicit `<`/`>`; `memoryview` for zero-copy slices; `mmap` for random access | `DataView`, `Buffer.subarray` |
            | Encodings | UTF-8 everywhere; `utf-8-sig` for BOMs; fix mojibake by re-encoding; choose `errors=` deliberately | `TextDecoder` |
            | Formats | JSON/CSV/TOML/MessagePack are data; YAML only with `safe_load`; XML only with `defusedxml` | `JSON`, `js-yaml` |
            | `pickle` | Rebuilds objects by calling code named in the data: never load untrusted pickles; customize with `__getstate__`/`__reduce__` | `structuredClone` (no code) |
            | Compression | `gzip`/`bz2`/`lzma`/`zstd` share an API; `zipfile`; `tarfile` with `filter="data"` | `zlib`, `tar` |
            | `sqlite3` | `?` parameters, `executemany`, `with connection:` transactions, `sqlite3.Row` | `better-sqlite3` |
            | Path safety | `resolve()` + `is_relative_to(base)` for any outside path | `path.resolve` + checks |

            **Further reading**

            - [`io`](https://docs.python.org/3/library/io.html),
              [`open()`](https://docs.python.org/3/library/functions.html#open),
              [`tempfile`](https://docs.python.org/3/library/tempfile.html),
              [`struct`](https://docs.python.org/3/library/struct.html),
              [`mmap`](https://docs.python.org/3/library/mmap.html)
            - [`codecs`](https://docs.python.org/3/library/codecs.html),
              [Unicode HOWTO](https://docs.python.org/3/howto/unicode.html)
            - [`tomllib`](https://docs.python.org/3/library/tomllib.html),
              [`xml.etree.ElementTree`](https://docs.python.org/3/library/xml.etree.elementtree.html)
              and [XML vulnerabilities](https://docs.python.org/3/library/xml.html#xml-vulnerabilities),
              [PyYAML](https://pyyaml.org/wiki/PyYAMLDocumentation),
              [defusedxml](https://github.com/tiran/defusedxml)
            - [`pickle`](https://docs.python.org/3/library/pickle.html) (read the warning box),
              [`shelve`](https://docs.python.org/3/library/shelve.html)
            - [`gzip`](https://docs.python.org/3/library/gzip.html),
              [`compression.zstd`](https://docs.python.org/3/library/compression.zstd.html),
              [`zipfile`](https://docs.python.org/3/library/zipfile.html),
              [`tarfile` extraction filters](https://docs.python.org/3/library/tarfile.html#extraction-filters)
            - [`sqlite3`](https://docs.python.org/3/library/sqlite3.html)
            - [PEP 686](https://peps.python.org/pep-0686/) (UTF-8 mode default),
              [PEP 706](https://peps.python.org/pep-0706/) (tar extraction filters),
              [PEP 784](https://peps.python.org/pep-0784/) (Zstandard),
              [PEP 3154](https://peps.python.org/pep-3154/) / [PEP 574](https://peps.python.org/pep-0574/) (pickle protocols 4 and 5)
            """
        ),
    ]


def cells() -> list[NotebookNode]:
    """Return the cells for Unit 4.5 and Lab 4.5."""
    return [
        *_overview_cells(),
        *_open_cells(),
        *_pattern_cells(),
        *_memory_file_cells(),
        *_binary_cells(),
        *_encoding_cells(),
        *_serialization_cells(),
        *_pickle_cells(),
        *_compression_cells(),
        *_sqlite_cells(),
        *_safety_cells(),
        *_lab_cells_part_1(),
        *_lab_cells_part_2(),
        *_recap_cells(),
    ]
