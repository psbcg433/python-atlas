"""Unit 3.1 — Memory Management (with Lab 3.1)."""

from nbformat import NotebookNode

from nb_builder import code, md, predict_cells

UNIT_SETUP_SOURCE = '''
import ctypes
import dis
import functools
import gc
import importlib.util
import itertools
import linecache
import os
import platform
import shutil
import struct
import subprocess
import sys
import sysconfig
import tempfile
import textwrap
import traceback
import tracemalloc
import weakref
from collections.abc import Callable, Iterator
from contextlib import contextmanager
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


def interpreter_label() -> str:
    """Implementation, version and build flavour: print it next to any size or refcount."""
    free_threaded = bool(sysconfig.get_config_var("Py_GIL_DISABLED"))
    build = "free-threaded build" if free_threaded else "default (GIL) build"
    implementation = platform.python_implementation()
    return f"{implementation} {platform.python_version()}, {build}, {platform.machine()}"


def rss_bytes() -> int | None:
    """Resident set size of this process in bytes, or None when it cannot be read."""
    status_file = Path("/proc/self/status")  # Linux
    if status_file.exists():
        for line in status_file.read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    if importlib.util.find_spec("psutil") is not None:  # macOS / Windows fallback
        import psutil

        return psutil.Process().memory_info().rss
    return None


def source_line(frame: tracemalloc.Frame) -> str:
    """The source text of a tracemalloc frame (works for notebook cells too)."""
    return linecache.getline(frame.filename, frame.lineno).strip() or "<source unavailable>"


def find_free_threaded_python() -> str | None:
    """Path of an installed free-threaded 3.15 interpreter, or None."""
    candidates: list[str] = []
    if uv_path := shutil.which("uv"):
        found = subprocess.run(
            [uv_path, "python", "find", "3.15t"], capture_output=True, text=True, timeout=60
        )
        if found.returncode == 0:
            candidates.append(found.stdout.strip())
    if on_path := shutil.which("python3.15t"):
        candidates.append(on_path)
    probe = "import sysconfig; print(sysconfig.get_config_var('Py_GIL_DISABLED'))"
    for candidate in candidates:
        answer = subprocess.run([candidate, "-c", probe], capture_output=True, text=True)
        if answer.stdout.strip() == "1":
            return candidate
    return None


print(interpreter_label())
'''


def _overview_cells() -> list[NotebookNode]:
    """Unit opener and setup."""
    return [
        md(
            """
            ## Unit 3.1 — Memory Management

            **Objectives**

            - Picture what a running program looks like in memory: frames that hold
              references, objects on a private heap, every object starting with the same
              header.
            - Explain when CPython frees an object: reference counting first, the cyclic
              garbage collector for cycles, immortal objects never.
            - Use `sys.getrefcount`, `gc`, `weakref` and `tracemalloc` as instruments, and read
              their output without trusting exact numbers.
            - Know how the allocator (pymalloc, mimalloc) and free lists shape memory use, and
              why the process's RSS rarely shrinks.
            - Find and fix the six common kinds of leak with a repeatable workflow.

            **JS bridge**

            | JavaScript (V8) | Python (CPython) | The difference that bites |
            | --- | --- | --- |
            | Tracing generational GC (Orinoco: scavenger + mark-compact) | Reference counting + a cycle collector for containers | CPython frees most objects **the moment** the last reference goes, not "some time later" |
            | Objects can move (compaction) | Objects never move; `id()` is the address | Fragmentation: freed memory can stay inside the process |
            | `WeakRef`, `FinalizationRegistry` | `weakref.ref`, `weakref.finalize` | CPython runs finalizers deterministically when the count hits zero (other Pythons may not) |
            | `WeakMap`, `WeakSet` | `WeakKeyDictionary`, `WeakValueDictionary`, `WeakSet` | Python also has weak **values**; many built-in types cannot be weakly referenced |
            | Heap snapshots in DevTools | `tracemalloc` snapshots and diffs | Both group allocations by where they were made |
            | `process.memoryUsage().rss` | `/proc/self/status`, `psutil`, `resource` | RSS includes allocator slack in both |

            > **Note:** sizes, reference counts and addresses printed in this unit come from the
            > interpreter running the notebook. Every cell that prints them also prints the
            > version and build; your values may differ.

            The next cell is this unit's setup. Besides the usual error helpers it defines
            `interpreter_label()`, `rss_bytes()`, `source_line(frame)` (source text of a
            `tracemalloc` frame) and `find_free_threaded_python()`.
            """
        ),
        code(UNIT_SETUP_SOURCE),
    ]


def _memory_model_cells() -> list[NotebookNode]:
    """3.1.1 The memory model."""
    return [
        md(
            """
            ### 3.1.1 The memory model

            Every Python value is an **object on CPython's private heap**. Nothing lives
            "on the stack" the way a C `int` or a JS small integer (Smi) does. What the call
            stack holds are **frames**, one per running function call, and a frame's local
            variables are just **references**: pointer-sized slots that point at heap objects.

            ```mermaid
            flowchart LR
                subgraph stack["Call stack (frames)"]
                    F1["checkout()<br/>cart_items, tax_rate"]
                    F2["apply_tax()<br/>cart_items, tax_rate"]
                end
                subgraph heap["Private heap (objects)"]
                    L["list [120.0, 80.0]"]
                    T["float 0.18"]
                end
                F1 -- "cart_items" --> L
                F2 -- "cart_items" --> L
                F1 -- "tax_rate" --> T
                F2 -- "tax_rate" --> T
            ```

            <details><summary>ASCII fallback</summary>

            ```text
            CALL STACK (frames)                 PRIVATE HEAP (objects)
            +---------------------------+
            | apply_tax()               |
            |   cart_items  ------------+-----> list [120.0, 80.0]
            |   tax_rate    ------------+--+
            +---------------------------+  |
            | checkout()                |  +--> float 0.18
            |   cart_items  ------------+-----> (same list)
            |   tax_rate    ------------+-----> (same float)
            +---------------------------+
            ```

            </details>

            Since 3.11 the frames themselves are lightweight C structs on a per-thread data
            stack; a full `frame` object is only built when someone asks for it
            (`sys._getframe()`, a traceback, a debugger). The cell asks for both frames and
            shows that they reference **one** list.
            """
        ),
        code(
            '''
            def checkout(cart_items: list[float]) -> float:
                """Outer call: owns the list and passes a reference down."""
                tax_rate = 0.18
                return apply_tax(cart_items, tax_rate)


            def apply_tax(cart_items: list[float], tax_rate: float) -> float:
                """Inner call: its frame holds a second reference to the caller's list."""
                caller_frame = sys._getframe(1)
                for frame in (sys._getframe(), caller_frame):
                    local_names = sorted(set(frame.f_locals) - {"caller_frame", "frame"})
                    print(f"frame {frame.f_code.co_name:<9} local names: {local_names}")
                same_list = caller_frame.f_locals["cart_items"] is cart_items
                print(f"both frames reference one heap object: {same_list}")
                return round(sum(cart_items) * (1 + tax_rate), 2)


            print(f"{checkout([120.0, 80.0])=}")
            '''
        ),
        md(
            """
            **References are pointer-sized.** A list stores references, not values, so each
            slot costs one pointer (8 bytes on a 64-bit build) whether it points at a small
            int or a megabyte string. A thousand references to one big string cost about 8 kB,
            not a gigabyte.
            """
        ),
        code(
            """
            pointer_bytes = struct.calcsize("P")
            print(f"{pointer_bytes=}  ({interpreter_label()})")

            big_text = "x" * 1_000_000
            list_of_big = [big_text] * 1_000
            list_of_small = [7] * 1_000
            print(f"{sys.getsizeof(big_text)=:,}")
            print(f"{sys.getsizeof(list_of_big)=:,}  {sys.getsizeof(list_of_small)=:,}")
            per_slot = (sys.getsizeof(list_of_big) - sys.getsizeof([])) / len(list_of_big)
            print(f"bytes per list slot: {per_slot}")
            print(f"{all(item is big_text for item in list_of_big)=}  (1 000 references, 1 string)")
            del big_text, list_of_big, list_of_small
            """
        ),
    ]


def _object_layout_cells() -> list[NotebookNode]:
    """3.1.2 Object layout."""
    return [
        md(
            """
            ### 3.1.2 Object layout

            Every object starts with the same C header, so the interpreter can handle any
            object through a `PyObject *` pointer:

            ```c
            typedef struct _object {
                Py_ssize_t ob_refcnt;     /* reference count (a union with split fields since 3.12) */
                PyTypeObject *ob_type;    /* pointer to the type object: list, int, your class */
            } PyObject;

            typedef struct {
                PyObject ob_base;
                Py_ssize_t ob_size;       /* number of items in variable-size objects */
            } PyVarObject;
            ```

            Container types that can form reference cycles (lists, dicts, sets, most class
            instances) carry an extra **GC header** (`PyGC_Head`, two words) placed **before**
            the object, which links them into the garbage collector's lists. Instances of
            ordinary classes also have pre-header slots for the managed `__dict__` and
            weak-reference list (3.12+).

            ```text
                       +----------------------------+
              -16 B    | PyGC_Head (2 words)        |  only for GC-tracked container types
                       +----------------------------+  <-- id(obj) points here (CPython)
               +0      | ob_refcnt                  |
               +8      | ob_type  ------------------+--> the type object
              +16      | ob_size (variable-size)    |  list, tuple, int digits, bytes, ...
              +24 ...  | type-specific fields       |  e.g. list: pointer to the item array
                       +----------------------------+
            ```

            | Piece | Who has it | Where you can see it |
            | --- | --- | --- |
            | `ob_refcnt` | every object | `sys.getrefcount(obj)` (plus one) |
            | `ob_type` | every object | `type(obj)` |
            | `ob_size` | variable-size objects | `len(obj)` for list / tuple / bytes |
            | GC header | GC-tracked types | `sys.getsizeof` includes it; `gc.is_tracked(obj)` |
            | Fixed part | every type | `type.__basicsize__` |
            | Per-item part | variable-size types | `type.__itemsize__` |

            > **Note:** the free-threaded build (3.1.5) has a larger header: an owning-thread
            > id, two reference-count fields and a small lock.

            The first cell prints the fixed and per-item sizes of common types and whether the
            type is GC-capable (the `Py_TPFLAGS_HAVE_GC` bit, `1 << 14`, in `__flags__`).
            """
        ),
        code(
            """
            PY_TPFLAGS_HAVE_GC = 1 << 14

            print(interpreter_label())
            print(f"{'type':<8}{'__basicsize__':>14}{'__itemsize__':>13}  GC-capable type")
            for some_type in (object, float, int, str, bytes, tuple, list, dict, set):
                gc_capable = bool(some_type.__flags__ & PY_TPFLAGS_HAVE_GC)
                print(
                    f"{some_type.__name__:<8}{some_type.__basicsize__:>14}"
                    f"{some_type.__itemsize__:>13}  {gc_capable}"
                )
            """
        ),
        md(
            """
            **The GC header shows up in `sys.getsizeof`.** For a GC-capable type,
            `sys.getsizeof` adds the header to the object's own size, so an empty list reports
            `list.__basicsize__ + 16` on a 64-bit build. A `float` is not a container and has no
            GC header.
            """
        ),
        code(
            """
            print(interpreter_label())
            samples = {"float": 1.5, "empty list": [], "empty tuple": (), "empty dict": {}}
            for label, sample in samples.items():
                basic_size = type(sample).__basicsize__
                extra_bytes = sys.getsizeof(sample) - basic_size
                print(
                    f"{label:<12} getsizeof={sys.getsizeof(sample):>3}  "
                    f"__basicsize__={basic_size:>3}  extra (GC header)={extra_bytes:>3}"
                )
            """
        ),
        md(
            """
            **Reading the header directly (unsafe).** `ctypes` can read raw memory at
            `id(obj)`. This is **CPython-only, 64-bit-only and unsafe**: a wrong address
            crashes the kernel, and the layout is private and changes between versions and
            builds. The cell checks the build first and only reads live objects it holds a
            reference to. It confirms `ob_type` points at `list` and `ob_size` equals `len()`.
            """
        ),
        code(
            '''
            CAN_PEEK = (
                sys.implementation.name == "cpython"
                and struct.calcsize("P") == 8
                and not sysconfig.get_config_var("Py_GIL_DISABLED")
            )


            def read_word(address: int) -> int:
                """UNSAFE: read one signed machine word at address (64-bit CPython default build)."""
                return ctypes.c_ssize_t.from_address(address).value


            if CAN_PEEK:
                basket = ["tea", "rice", "salt"]
                print(f"ob_type is list: {read_word(id(basket) + 8) == id(list)}")
                print(f"ob_size: {read_word(id(basket) + 16)}  (len: {len(basket)})")
                basket.append("sugar")
                print(f"ob_size after append: {read_word(id(basket) + 16)}")
            else:
                print(f"Skipped: offsets assume 64-bit CPython, default build ({interpreter_label()})")
            '''
        ),
        md(
            """
            **Size table for common objects.** The cell prints `sys.getsizeof` for everyday
            values. What explains each family:

            | Family | Size is made of |
            | --- | --- |
            | `None`, `bool`, small objects | the 16-byte header, maybe one more field |
            | `int` | header + `ob_size` + 30-bit digits (4 bytes each) |
            | `float` | header + one C `double` |
            | `str` | header + PEP 393 fields + 1, 2 or 4 bytes per character (widest character decides) |
            | `bytes` | header + length + hash + one byte per item + a trailing NUL |
            | `tuple` | header + length + cached hash (3.14+) + 8 bytes per item (+ GC header) |
            | `list`, `dict`, `set` | header + bookkeeping + GC header; items live in a **separate** array that `getsizeof` adds on top (see 3.1.11) |
            | class instance | header + inline values / managed `__dict__` pointers (+ GC header) |

            > **Warning:** these numbers change between Python versions (3.14 added a cached
            > hash to tuples, for example). Use them to compare, never hard-code them.
            """
        ),
        code(
            '''
            class PlainRecord:
                """An ordinary class with two attributes."""

                def __init__(self) -> None:
                    self.sku = "TEA-01"
                    self.quantity = 3


            def sample_function() -> None:
                """A function object to measure."""


            common_objects: dict[str, object] = {
                "None": None, "True": True, "0": 0, "2**30": 2**30, "2**100": 2**100,
                "1.5": 1.5, "1+2j": 1 + 2j, "'' (empty str)": "", "'a'": "a",
                "'é' (Latin-1)": "é", "'₹' (BMP)": "₹", "'😀' (astral)": "😀",
                "'a' * 100": "a" * 100, "b''": b"", "b'a' * 100": b"a" * 100,
                "()": (), "(1,)": (1,), "(1, 2, 3)": (1, 2, 3), "[]": [], "[1, 2, 3]": [1, 2, 3],
                "{}": {}, "{'a': 1}": {"a": 1}, "set()": set(), "frozenset()": frozenset(),
                "range(10)": range(10), "object()": object(), "PlainRecord()": PlainRecord(),
                "function": sample_function,
            }  # fmt: skip
            print(interpreter_label())
            for label, sample in common_objects.items():
                print(f"{label:<16}{sys.getsizeof(sample):>6} B   {type(sample).__name__}")
            '''
        ),
    ]


def _refcount_cells() -> list[NotebookNode]:
    """3.1.3 Reference counting."""
    return [
        md(
            """
            ### 3.1.3 Reference counting

            Every object counts how many references point at it. When the count drops to
            zero, CPython frees the object **immediately** (and decrements everything it
            referenced, which can cascade).

            | Increments the count | Decrements the count |
            | --- | --- |
            | binding a name: `alias = obj` | rebinding or `del` of that name |
            | storing in a container: `items.append(obj)`, `{key: obj}` | removing it, or the container dying |
            | storing as an attribute: `holder.inner = obj` | `del holder.inner`, or `holder` dying |
            | pushing it on the eval stack for an operation (usually) | popping it when the operation ends |
            | a frame holding it as a local or argument | the frame finishing (return or exception) |

            `sys.getrefcount(obj)` reports the count **plus one**: the call's own argument is
            a temporary reference. The cell watches one object at module level and prints the
            change after each step.
            """
        ),
        code(
            '''
            class Ticket:
                """A plain object whose reference count we watch."""


            ticket = Ticket()
            baseline = sys.getrefcount(ticket)
            print(f"{baseline=}  (the name `ticket` + getrefcount's own argument)  [{interpreter_label()}]")

            alias = ticket
            print(f"alias = ticket            -> {sys.getrefcount(ticket) - baseline:+d}")
            queue = [ticket]
            print(f"queue = [ticket]          -> {sys.getrefcount(ticket) - baseline:+d}")
            by_code = {"T1": ticket}
            print(f"by_code = {{'T1': ticket}}  -> {sys.getrefcount(ticket) - baseline:+d}")
            holder = Ticket()
            holder.inner = ticket
            print(f"holder.inner = ticket     -> {sys.getrefcount(ticket) - baseline:+d}")
            del alias
            print(f"del alias                 -> {sys.getrefcount(ticket) - baseline:+d}")
            queue.clear()
            print(f"queue.clear()             -> {sys.getrefcount(ticket) - baseline:+d}")
            del by_code, holder
            print(f"del by_code, holder       -> {sys.getrefcount(ticket) - baseline:+d}")
            '''
        ),
        md(
            """
            **The "+1" is not guaranteed.** *Changed in 3.14:* inside functions the compiler
            emits `LOAD_FAST_BORROW`, which pushes a **borrowed** reference (no increment)
            when it can prove the local outlives the use. `sys.getrefcount(local)` can then
            print `1` for an object with one real reference, and passing an object as an
            argument may add nothing. Treat `getrefcount` as an approximate instrument; compare
            **changes**, never absolute values.
            """
        ),
        code(
            '''
            def local_refcount() -> int:
                """getrefcount of an object referenced only by this function's local."""
                fresh_ticket = Ticket()
                return sys.getrefcount(fresh_ticket)


            def argument_refcount(some_object: object) -> int:
                """getrefcount of an argument, seen from inside the callee."""
                return sys.getrefcount(some_object)


            print(f"{sys.getrefcount(ticket)=}  (module level)")
            print(f"{argument_refcount(ticket)=}  (same object, seen as an argument)")
            print(f"{local_refcount()=}  (one local reference)")
            load_ops = [ins.opname for ins in dis.get_instructions(local_refcount)]
            print(f"loads in local_refcount: {[name for name in load_ops if name.startswith('LOAD_FAST')]}")
            print(interpreter_label())
            '''
        ),
        md(
            """
            **Deterministic deallocation.** Because freeing happens when the count reaches
            zero, you can predict *exactly* when an object dies. `weakref.finalize(obj, func,
            *args)` registers a callback that runs when `obj` is freed, without keeping `obj`
            alive. The event list shows the finalizer running **between** the two statements
            around `del`, and at the moment a function returns.
            """
        ),
        code(
            '''
            events: list[str] = []
            receipt = Ticket()
            weakref.finalize(receipt, events.append, "receipt freed")
            events.append("before del")
            del receipt
            events.append("after del")
            print(events)


            def issue_temporary_ticket() -> None:
                """Create a ticket that only this frame references."""
                temporary = Ticket()
                weakref.finalize(temporary, events.append, "temporary freed (frame finished)")
                events.append("returning")


            events.clear()
            issue_temporary_ticket()
            events.append("caller continues")
            print(events)
            '''
        ),
        md(
            """
            > **Note:** this is a CPython guarantee, not a language guarantee. PyPy and GraalPy
            > use tracing collectors, so finalizers there run "later". Code that must release a
            > resource at a known point should use a `with` block (3.1.7).

            **Reading the live count with `ctypes` (unsafe).** `ob_refcnt` is the first word of
            the object. Reading it directly avoids the extra argument reference. Same
            warnings as in 3.1.2: CPython-only, and never read an address after the object
            might have been freed.
            """
        ),
        code(
            """
            if CAN_PEEK:
                watched = Ticket()
                watched_address = id(watched)  # valid only while `watched` is alive
                # read_word (3.1.2) is ctypes.c_ssize_t.from_address(address).value
                print(f"one name:           ob_refcnt={read_word(watched_address)}")
                three_more = [watched, watched, watched]
                print(f"+ list of 3 refs:   ob_refcnt={read_word(watched_address)}")
                del three_more
                print(f"list deleted:       ob_refcnt={read_word(watched_address)}")
                print(f"compare: sys.getrefcount(watched)={sys.getrefcount(watched)}")
                del watched  # from here on, watched_address must not be read
            else:
                print(f"Skipped: needs 64-bit CPython, default build ({interpreter_label()})")
            """
        ),
    ]


def _immortal_cells() -> list[NotebookNode]:
    """3.1.4 Immortal objects (PEP 683)."""
    return [
        md(
            """
            ### 3.1.4 Immortal objects (PEP 683)

            *New in 3.12.* Some objects are **immortal**: their reference count is set to a
            special value, `Py_INCREF` / `Py_DECREF` leave it alone, and they are never freed.
            Immortal objects include `None`, `True`, `False`, `Ellipsis`, the small-int cache,
            the empty tuple, the empty string and one-character Latin-1 strings, the strings
            CPython preallocates for its own identifiers, and the built-in types.

            Why bother:

            - **No writes to shared objects.** Incrementing `None`'s count on every use wrote to
              one hot cache line from every thread and dirtied memory pages shared after
              `fork()` (copy-on-write).
            - **A prerequisite** for the per-interpreter GIL (3.12) and the free-threaded build
              (3.1.5).

            `sys._is_immortal(obj)` (*New in 3.14*, CPython-specific) answers directly. The cell
            checks a mix of objects; which strings are immortal depends on how they were
            created.
            """
        ),
        code(
            """
            if hasattr(sys, "_is_immortal"):
                runtime_text = "".join(["warehouse", "_zone"])  # built at run time
                immortality_samples: dict[str, object] = {
                    "None": None, "True": True, "Ellipsis": ..., "int (the type)": int,
                    "-5": -5, "256": int("256"), "1024": int("1024"), "1025": int("1025"),
                    "'' (empty str)": "", "'a' (1 char)": "a", "'order_id' (literal)": "order_id",
                    "str built at run time": runtime_text,
                    "sys.intern(that str)": sys.intern(runtime_text),
                    "() (empty tuple)": (), "[] (new list)": [], "object()": object(),
                }  # fmt: skip
                print(interpreter_label())
                for label, sample in immortality_samples.items():
                    print(f"{label:<24} immortal={sys._is_immortal(sample)}")
            else:
                print("Skipped: sys._is_immortal needs Python 3.14+")
            """
        ),
        md(
            """
            Notice that on this build the small-int cache reaches 1024 (*Changed in 3.15*;
            it ended at 256 before). A string literal from **your** code (`'order_id'`) and a
            string interned at run time with `sys.intern` are interned (deduplicated) but
            **not** immortal: they are freed when the code or the last user goes away.

            Making a hundred thousand new references to `None` does not change its reported
            count. The huge value is the immortal marker, not a real count.
            """
        ),
        code(
            """
            none_count_before = sys.getrefcount(None)
            many_nones = [None] * 100_000
            none_count_after = sys.getrefcount(None)
            print(f"{none_count_before=:,}")
            print(f"{none_count_after=:,}")
            print(f"unchanged: {none_count_before == none_count_after}  [{interpreter_label()}]")
            del many_nones
            """
        ),
    ]


def _free_threaded_cells() -> list[NotebookNode]:
    """3.1.5 Reference counting in the free-threaded build."""
    return [
        md(
            """
            ### 3.1.5 Reference counting in the free-threaded build

            The free-threaded build (PEP 703; experimental in 3.13, officially supported since
            3.14 under PEP 779) removes the GIL, so threads really run Python code in parallel.
            Plain `ob_refcnt += 1` would then be a data race, and making every increment atomic
            would be slow. Two techniques keep it fast (overview):

            | Technique | Idea | Effect |
            | --- | --- | --- |
            | **Biased reference counting** | Each object records an **owning thread** (`ob_tid`). The owner updates a local count (`ob_ref_local`) with plain, fast instructions; other threads update a shared count (`ob_ref_shared`) atomically. | Most objects are only touched by the thread that made them, so most updates stay cheap. |
            | **Deferred reference counting** | Objects that are referenced constantly from many threads (functions, modules, code objects, classes) skip count updates when pushed on the interpreter stack; the GC accounts for those references when it runs. | No contention on the hottest objects. |
            | **Immortalization** | 3.1.4: `None`, small ints, interned strings never change count. | Zero writes for the most shared objects. |

            Other parts of the design: per-object locks (*critical sections*) inside
            `list` / `dict` methods, mimalloc as the allocator (3.1.9), and a GC that stops all
            threads briefly. The object header grows to hold `ob_tid`, both counts and a lock.

            First, which build is this kernel? `sysconfig` tells you how the interpreter was
            **built**; `sys._is_gil_enabled()` (*New in 3.13*) tells you whether the GIL is on
            **right now** (a free-threaded build can re-enable it, e.g. for an extension that
            is not marked safe).
            """
        ),
        code(
            """
            gil_disabled_build = bool(sysconfig.get_config_var("Py_GIL_DISABLED"))
            print(f"{gil_disabled_build=}")
            if hasattr(sys, "_is_gil_enabled"):
                print(f"{sys._is_gil_enabled()=}")
            else:
                print("sys._is_gil_enabled() needs Python 3.13+")
            print(f"{sys.getsizeof(object())=}  (object header size on this build)")
            if not gil_disabled_build:
                print("This kernel is the default build: the comparison below runs in child processes.")
            """
        ),
        md(
            """
            **Comparing the two builds.** If a free-threaded interpreter is installed
            (`uv python install 3.15t`, found with `uv python find 3.15t`), the next cell runs
            the same probe in this kernel's interpreter and in the free-threaded one, each in
            a child process. The probe reports:

            - the size of a bare `object()` (the bigger header),
            - `sys.getrefcount` of a module-level function (deferred reference counting makes
              it a huge marker value on the free-threaded build),
            - wall time of 4 threads doing pure-Python arithmetic, divided by the time for 1
              thread. With a GIL the threads take turns (ratio around 4 or worse); without
              it they run in parallel (ratio near 1 when you have 4+ cores).

            > **Note:** timings depend on the machine and its load. The interpreter path is
            > never printed.
            """
        ),
        code(
            '''
            FREE_THREADING_PROBE = textwrap.dedent(
                """
                import os, sys, sysconfig, threading, time

                def spin(count):
                    total = 0
                    for number in range(count):
                        total += number * number

                def wall_time(thread_count, count=1_500_000):
                    threads = [threading.Thread(target=spin, args=(count,)) for _ in range(thread_count)]
                    start = time.perf_counter()
                    for thread in threads:
                        thread.start()
                    for thread in threads:
                        thread.join()
                    return time.perf_counter() - start

                def module_level_function():
                    pass

                print("build", "free-threaded" if sysconfig.get_config_var("Py_GIL_DISABLED") else "default")
                print("gil_enabled", sys._is_gil_enabled())
                print("object_header_bytes", sys.getsizeof(object()))
                print("function_refcount", sys.getrefcount(module_level_function))
                print("ratio_4_threads_vs_1", round(wall_time(4) / wall_time(1), 2))
                """
            )


            def run_probe(python_path: str) -> dict[str, str]:
                """Run FREE_THREADING_PROBE in a child interpreter and parse "key value" lines."""
                completed = subprocess.run(
                    [python_path, "-c", FREE_THREADING_PROBE],
                    capture_output=True, text=True, env=CHILD_ENV, timeout=180,
                )  # fmt: skip
                return dict(line.split(" ", 1) for line in completed.stdout.splitlines())


            free_threaded_python = find_free_threaded_python()
            if free_threaded_python is None:
                print("Skipped: no free-threaded interpreter found (try: uv python install 3.15t)")
            else:
                print(f"CPU cores: {os.cpu_count()}")
                default_result = run_probe(sys.executable)
                free_threaded_result = run_probe(free_threaded_python)
                print(f"{'metric':<22}{'this kernel':>22}{'3.15t child':>22}")
                for key in default_result:
                    print(f"{key:<22}{default_result[key]:>22}{free_threaded_result.get(key, '?'):>22}")
            '''
        ),
    ]


def _cyclic_gc_cells() -> list[NotebookNode]:
    """3.1.6 Reference cycles and the cyclic GC."""
    return [
        md(
            """
            ### 3.1.6 Reference cycles and the cyclic GC

            Reference counting alone cannot free a **cycle**: two objects that reference each
            other keep each other's count at 1 or more even after every outside name is gone.

            ```mermaid
            flowchart LR
                name["name `parent` (deleted)"] -. "x" .-> P
                P["Category 'Tea'"] -- children --> C["Category 'Green tea'"]
                C -- parent --> P
            ```

            <details><summary>ASCII fallback</summary>

            ```text
            parent (name deleted)  -x->  [Category 'Tea'] --children--> [Category 'Green tea']
                                                ^                               |
                                                +------------parent-------------+
            each count stays at 1: refcounting alone never frees them
            ```

            </details>

            CPython's **cyclic garbage collector** handles this. It only tracks objects that
            can hold references (containers), and periodically looks for groups that are
            referenced *only from inside the group*. Those are unreachable and get freed.

            The cell builds a parent/child cycle with the collector switched off, shows that
            `del` does not free it, then runs `gc.collect()`. The `try` / `finally` restores
            the collector so later cells are unaffected.
            """
        ),
        code(
            '''
            class Category:
                """A tree node that links to its parent and children: a natural cycle."""

                def __init__(self, name: str, parent: Category | None = None) -> None:
                    self.name = name
                    self.parent = parent
                    self.children: list[Category] = []
                    if parent is not None:
                        parent.children.append(self)


            freed: list[str] = []
            gc_was_enabled = gc.isenabled()
            gc.disable()
            try:
                tea = Category("Tea")
                green_tea = Category("Green tea", parent=tea)
                weakref.finalize(tea, freed.append, "Tea")
                weakref.finalize(green_tea, freed.append, "Green tea")
                del tea, green_tea
                print(f"after del:          freed={freed}  (the cycle keeps both alive)")
                unreachable_count = gc.collect()
                print(f"after gc.collect(): freed={sorted(freed)}  ({unreachable_count} objects found)")
            finally:
                if gc_was_enabled:
                    gc.enable()
            '''
        ),
        md(
            """
            #### The `gc` module API

            | Function | What it does | Typical use |
            | --- | --- | --- |
            | `gc.collect(generation=2)` | Run a collection now; returns the number of unreachable objects found | Tests, benchmarks, before a memory snapshot |
            | `gc.is_tracked(obj)` | Is this object in the collector's lists? | Learning which objects the GC even looks at |
            | `gc.get_threshold()` | The allocation thresholds that trigger collections | Tuning (rarely needed) |
            | `gc.get_count()` | Current counters per generation | Watching allocation pressure |
            | `gc.get_stats()` | Per-generation totals: collections, collected, uncollectable | Monitoring |
            | `gc.get_referrers(*objs)` | Objects that refer to these objects | Finding who keeps a leaked object alive |
            | `gc.get_referents(*objs)` | Objects these objects refer to | Walking an object graph |
            | `gc.freeze()` | Move every tracked object to a permanent generation the GC ignores | Before `fork()` in pre-fork servers |
            | `gc.callbacks` | List of `callback(phase, info)` run before and after each collection | Measuring GC pauses |

            One demo per function follows.

            #### `gc.collect`

            Returns how many unreachable objects it found. A second call right after usually
            finds nothing.
            """
        ),
        code(
            """
            for _ in range(3):
                first_node, second_node = {}, {}
                first_node["peer"], second_node["peer"] = second_node, first_node
            del first_node, second_node
            print(f"{gc.collect()=}  (three 2-dict cycles, plus anything else pending)")
            print(f"{gc.collect()=}  (nothing left)")
            """
        ),
        md(
            """
            #### `gc.is_tracked`

            Atomic objects (ints, strings, floats) cannot form cycles, so they are never
            tracked. Containers are. As an optimization, CPython may **untrack** a tuple that
            holds only untracked objects, since it can never be part of a cycle. *When* that
            happens (at creation, or when the collector first inspects the tuple) is an
            implementation detail that has changed between versions; the output shows what
            this build does.
            """
        ),
        code(
            """
            print(interpreter_label())
            for label, sample in {
                "42": 42,
                "'text'": "text",
                "[]": [],
                "{}": {},
                "(1, 2) constant": (1, 2),
                "([],) holds a list": ([],),
                "Category('x')": Category("x"),
            }.items():
                print(f"{label:<20} tracked={gc.is_tracked(sample)}")

            runtime_tuple = tuple([1, 2, 3])
            tuple_with_list = tuple([[]])
            print(f"runtime tuple of ints:   before collect {gc.is_tracked(runtime_tuple)}", end="")
            print(f", tuple holding a list: {gc.is_tracked(tuple_with_list)}")
            gc.collect()
            print(f"after gc.collect():      tuple of ints {gc.is_tracked(runtime_tuple)}", end="")
            print(f", tuple holding a list: {gc.is_tracked(tuple_with_list)}")
            """
        ),
        md(
            """
            #### `gc.get_threshold`

            A collection of the youngest generation starts when *allocations minus
            deallocations* of tracked objects exceed the first threshold; the other two values
            control how often older generations are examined. `gc.set_threshold` changes them;
            the cell only reads them.
            """
        ),
        code(
            """
            print(f"{gc.get_threshold()=}  [{interpreter_label()}]")
            """
        ),
        md(
            """
            #### `gc.get_count`

            The counters that are compared with the thresholds. Allocating tracked
            containers raises the first one; a collection resets it.
            """
        ),
        code(
            """
            gc.collect()
            print(f"after collect:          {gc.get_count()=}")
            new_containers = [{} for _ in range(500)]
            print(f"after 500 new dicts:    {gc.get_count()=}")
            del new_containers
            """
        ),
        md(
            """
            #### `gc.get_stats`

            One dictionary per generation with running totals since the interpreter started.
            `uncollectable` should stay at 0 (it counts objects the GC found but could not
            free).
            """
        ),
        code(
            """
            for generation, stats in enumerate(gc.get_stats()):
                print(f"generation {generation}: {stats}")
            """
        ),
        md(
            """
            #### `gc.get_referrers`

            Answers "who is keeping this alive?". It scans every tracked object, so it is slow
            and returns frames and namespaces too; filter the result. Here a `Category` is
            found inside a registry list.
            """
        ),
        code(
            """
            registry: list[Category] = []
            orphan = Category("Orphan")
            registry.append(orphan)
            referrer_types = sorted({type(referrer).__name__ for referrer in gc.get_referrers(orphan)})
            print(f"{referrer_types=}")
            print(f"registry is a referrer: {any(ref is registry for ref in gc.get_referrers(orphan))}")
            registry.clear()
            """
        ),
        md(
            """
            #### `gc.get_referents`

            The other direction: what an object refers to (as the C-level traversal sees it).
            For an instance with a materialized `__dict__` this includes the dict and the
            class.
            """
        ),
        code(
            """
            parent_category = Category("Coffee")
            child_category = Category("Espresso", parent=parent_category)
            vars(child_category)  # materialize the instance __dict__
            print(sorted(type(item).__name__ for item in gc.get_referents(child_category)))
            print([type(item).__name__ for item in gc.get_referents([1, "two", parent_category])])
            del parent_category, child_category
            """
        ),
        md(
            """
            #### `gc.freeze`

            *New in 3.7.* Moves every currently tracked object into a **permanent
            generation** that future collections skip. Pre-fork servers (gunicorn, uWSGI)
            call it in the parent before forking workers, so the GC in each child does not
            write to (and copy) the shared pages. `gc.unfreeze()` undoes it.
            """
        ),
        code(
            """
            gc.collect()
            gc.freeze()
            try:
                print(f"after freeze:   {gc.get_freeze_count()=:,}")
            finally:
                gc.unfreeze()
            print(f"after unfreeze: {gc.get_freeze_count()=}")
            """
        ),
        md(
            """
            #### `gc.callbacks`

            A list of functions called as `callback(phase, info)` with `phase` `"start"` or
            `"stop"` and an `info` dict (`generation`, `collected`, `uncollectable`). Useful for
            timing collections in production. Always remove your callback again.
            """
        ),
        code(
            '''
            collection_log: list[str] = []


            def record_collection(phase: str, info: dict[str, int]) -> None:
                """GC callback: log each phase with the generation and the result."""
                collected = info.get("collected", "-")
                collection_log.append(f"{phase}: generation={info['generation']} collected={collected}")


            gc.callbacks.append(record_collection)
            try:
                gc.collect()
            finally:
                gc.callbacks.remove(record_collection)
            print("\\n".join(collection_log))
            '''
        ),
        md(
            """
            #### Generations

            Most objects die young. The collector therefore groups tracked objects by age:
            new containers start in the **youngest generation**, which is collected often and
            cheaply; survivors move to **older generations**, examined less often. A full
            collection (`gc.collect()` with no argument) looks at everything.

            ```text
            new container --> [ young ] --survives--> [ older ] --survives--> [ oldest ]
                             collected often           less often             rarely
            gc.freeze()  --> [ permanent ]  never examined
            ```

            > **Note:** the exact scheme is an implementation detail that has been reworked in
            > recent releases (thresholds and how many generations are scanned per step). Read
            > `gc.get_threshold()` and `gc.get_stats()` on your version instead of memorizing
            > numbers.

            #### Case study: `gc.disable`

            Instagram's Django workers (2017) ran with `gc.disable()`: after `fork()`, every
            collection wrote to the GC headers of shared objects, which forced the OS to copy
            those pages into every worker. Turning the collector off saved memory because their
            code created few cycles. The risk: **any cycle you do create now leaks**. That trade
            led to `gc.freeze()`, which keeps the copy-on-write benefit without giving up
            collection.

            The cell shows the risk. With the collector off, 20 000 small cycles per round pile
            up; `tracemalloc` (3.1.11) shows memory growing until `gc.collect()` runs. The
            `finally` block restores everything.
            """
        ),
        code(
            """
            gc_was_enabled = gc.isenabled()
            gc.disable()
            tracemalloc.start()
            try:
                for round_number in range(1, 4):
                    for _ in range(20_000):
                        first_node, second_node = {}, {}
                        first_node["peer"], second_node["peer"] = second_node, first_node
                    traced_now, _peak = tracemalloc.get_traced_memory()
                    print(f"round {round_number}: traced {traced_now / 1e6:5.1f} MB, {gc.get_count()=}")
                del first_node, second_node
                found_count = gc.collect()
                traced_now, _peak = tracemalloc.get_traced_memory()
                print(f"gc.collect() found {found_count:,} objects; traced now {traced_now / 1e6:.1f} MB")
            finally:
                tracemalloc.stop()
                if gc_was_enabled:
                    gc.enable()
            print(f"collector restored: {gc.isenabled()=}")
            """
        ),
    ]


def _finalizer_cells() -> list[NotebookNode]:
    """3.1.7 Finalizers."""
    return [
        md(
            """
            ### 3.1.7 Finalizers

            `__del__` runs when an object is about to be destroyed: when its count hits zero,
            or when the cyclic GC frees it. Its rules surprise people:

            | Rule | Consequence |
            | --- | --- |
            | Timing depends on references | One forgotten reference (a traceback, a cache) and it never runs |
            | Not guaranteed at interpreter exit | Objects alive at shutdown may never be finalized |
            | Exceptions are not raised | They go to `sys.unraisablehook` ("Exception ignored in ...") |
            | It can **resurrect** the object | By storing `self` somewhere; the object survives |
            | Runs at most once per object (PEP 442) | A resurrected object will not be finalized again |
            | Cycles with `__del__` are collected (PEP 442, 3.4) | Before 3.4 they went to `gc.garbage` and leaked |

            **When it runs.** With no cycle involved, CPython calls `__del__` right at `del`.
            """
        ),
        code(
            '''
            class Connection:
                """Pretends to hold a socket and logs its own finalization."""

                log: list[str] = []

                def __init__(self, name: str) -> None:
                    self.name = name

                def __del__(self) -> None:
                    Connection.log.append(f"__del__ {self.name}")


            database_connection = Connection("db")
            Connection.log.append("before del")
            del database_connection
            Connection.log.append("after del")
            print(Connection.log)
            '''
        ),
        md(
            """
            **Exceptions inside `__del__` are swallowed.** They are reported through
            `sys.unraisablehook` (by default a message on stderr) and the program carries on.
            The cell installs a temporary hook to capture the report, then restores the
            original.
            """
        ),
        code(
            '''
            class BrokenCleanup:
                """A finalizer that fails."""

                def __del__(self) -> None:
                    raise RuntimeError("cleanup failed")


            captured_reports: list[str] = []


            def capture_unraisable(unraisable: sys.UnraisableHookArgs) -> None:
                """Record the exception instead of printing it."""
                captured_reports.append(f"{type(unraisable.exc_value).__name__}: {unraisable.exc_value}")


            original_hook = sys.unraisablehook
            sys.unraisablehook = capture_unraisable
            try:
                broken = BrokenCleanup()
                del broken
                print("after del: the program kept running")
            finally:
                sys.unraisablehook = original_hook
            print(f"{captured_reports=}")
            '''
        ),
        md(
            """
            **Resurrection and PEP 442.** A finalizer that stores `self` somewhere creates a new
            reference, so the object survives. PEP 442 guarantees `__del__` is called **at most
            once**: when the resurrected object dies for real, it is freed without a second
            call.
            """
        ),
        code(
            '''
            resurrected: list[object] = []


            class Phoenix:
                """Resurrects itself the first time it is finalized."""

                del_calls = 0

                def __del__(self) -> None:
                    Phoenix.del_calls += 1
                    resurrected.append(self)  # a new strong reference


            bird = Phoenix()
            del bird
            print(f"{Phoenix.del_calls=}  {len(resurrected)=}  (alive again)")
            resurrected.clear()  # the last reference goes away a second time
            gc.collect()
            print(f"{Phoenix.del_calls=}  (not called again)")
            '''
        ),
        md(
            """
            **Cycles with finalizers are collected.** Two objects with `__del__` that reference
            each other are freed by `gc.collect()`; both finalizers run and nothing lands in
            `gc.garbage`.
            """
        ),
        code(
            """
            gc_was_enabled = gc.isenabled()
            gc.disable()
            try:
                Connection.log.clear()
                primary, replica = Connection("primary"), Connection("replica")
                primary.peer, replica.peer = replica, primary
                del primary, replica
                print(f"before collect: {Connection.log}")
                gc.collect()
                print(f"after collect:  {sorted(Connection.log)}   gc.garbage={gc.garbage}")
            finally:
                if gc_was_enabled:
                    gc.enable()
            """
        ),
        md(
            """
            **Prefer context managers and `weakref.finalize`.** For a resource that must be
            released, give the class a `close()` method and `__enter__` / `__exit__`, so
            callers release it at a known point. Add `weakref.finalize` as a safety net for
            callers who forget:

            - it does not keep the object alive (pass the data it needs, never `self` or a
              bound method),
            - it runs at most once, whether called explicitly or at object death,
            - by default it also runs at interpreter exit (`atexit=True`), unlike `__del__`.
            """
        ),
        code(
            '''
            class ScratchFolder:
                """A temporary folder: removed by close()/with, or by a finalizer as a safety net."""

                def __init__(self) -> None:
                    self.path = Path(tempfile.mkdtemp(prefix="unit31_"))
                    self._finalizer = weakref.finalize(self, shutil.rmtree, self.path, ignore_errors=True)

                def close(self) -> None:
                    """Remove the folder now (safe to call twice)."""
                    self._finalizer()

                @property
                def closed(self) -> bool:
                    return not self._finalizer.alive

                def __enter__(self) -> ScratchFolder:
                    return self

                def __exit__(self, *exc_info: object) -> None:
                    self.close()


            with ScratchFolder() as folder:
                (folder.path / "notes.txt").write_text("draft")
                print(f"inside with: exists={folder.path.exists()}")
            print(f"after with:  exists={folder.path.exists()}  closed={folder.closed}")

            forgotten = ScratchFolder()
            forgotten_path = forgotten.path
            del forgotten  # the caller forgot close(): the finalizer cleans up
            print(f"forgotten folder removed by the finalizer: {not forgotten_path.exists()}")
            '''
        ),
    ]


def _weakref_cells() -> list[NotebookNode]:
    """3.1.8 Weak references."""
    return [
        md(
            """
            ### 3.1.8 Weak references

            A **weak reference** points at an object without adding to its count, so it does
            not keep the object alive. Use them for caches, registries and observer lists
            that should not decide an object's lifetime.

            | API | What it is | JS equivalent |
            | --- | --- | --- |
            | `weakref.ref(obj, callback=None)` | Call it to get the object, or `None` once it died; optional callback on death | `new WeakRef(obj)`, `.deref()` |
            | `weakref.WeakValueDictionary` | Dict whose **values** are weak: entries vanish when the value dies | — |
            | `weakref.WeakKeyDictionary` | Dict whose **keys** are weak: attach data to objects you do not own | `WeakMap` |
            | `weakref.WeakSet` | Set of weakly held objects | `WeakSet` |
            | `weakref.WeakMethod` | Weak reference to a **bound method** that stays valid while the instance lives | — |
            | `__weakref__` slot | Where an instance keeps its list of weak references; needed with `__slots__` | — |

            Many built-in types (`int`, `str`, `list`, `dict`, `tuple`) **cannot** be weakly
            referenced; instances of your own classes can.

            #### `weakref.ref`
            """
        ),
        code(
            '''
            class Session:
                """A logged-in user session."""

                def __init__(self, user: str) -> None:
                    self.user = user


            death_notices: list[str] = []
            session = Session("asha")
            session_ref = weakref.ref(session, lambda dead_ref: death_notices.append("session gone"))
            print(f"{session_ref() is session=}  {session_ref().user=}")
            del session
            print(f"{session_ref()=}  {death_notices=}")
            for value in (42, "text", [1, 2], {"a": 1}):
                outcome = raised_message(functools.partial(weakref.ref, value))
                print(f"weakref to {type(value).__name__:<5}: {outcome}")
            '''
        ),
        md(
            """
            #### `weakref.WeakValueDictionary`

            A registry of live sessions by id. The registry never keeps a session alive: when
            the last strong reference goes, the entry disappears.
            """
        ),
        code(
            """
            live_sessions: weakref.WeakValueDictionary[str, Session] = weakref.WeakValueDictionary()
            asha_session, ravi_session = Session("asha"), Session("ravi")
            live_sessions["s-1"], live_sessions["s-2"] = asha_session, ravi_session
            print(f"{sorted(live_sessions)=}")
            del ravi_session
            print(f"{sorted(live_sessions)=}  (s-2 vanished with its session)")
            print(f"{live_sessions.get('s-2')=}")
            """
        ),
        md(
            """
            #### `weakref.WeakKeyDictionary`

            Attach extra data to objects you do not own (or cannot add attributes to) without
            extending their life. Like a JS `WeakMap`.
            """
        ),
        code(
            """
            request_counts: weakref.WeakKeyDictionary[Session, int] = weakref.WeakKeyDictionary()
            meena_session = Session("meena")
            request_counts[asha_session] = 3
            request_counts[meena_session] = 1
            print(f"{len(request_counts)=}")
            del meena_session
            print(f"{len(request_counts)=}  {[s.user for s in request_counts]=}")
            """
        ),
        md(
            """
            #### `weakref.WeakSet`

            Track "everything currently alive" of some kind, such as open connections, for a
            status page or a shutdown hook.
            """
        ),
        code(
            """
            open_sessions: weakref.WeakSet[Session] = weakref.WeakSet()
            temporary_sessions = [Session(f"guest-{number}") for number in range(3)]
            open_sessions.update(temporary_sessions)
            open_sessions.add(asha_session)
            print(f"{len(open_sessions)=}")
            del temporary_sessions
            print(f"{len(open_sessions)=}  {[s.user for s in open_sessions]=}")
            """
        ),
        md(
            """
            #### `weakref.WeakMethod`

            `obj.method` creates a **new** bound-method object on every access. A plain
            `weakref.ref` to it dies immediately, because nothing else holds that temporary
            object. `WeakMethod` stores weak references to the instance and the function
            separately and rebuilds the bound method on demand.
            """
        ),
        code(
            '''
            class PriceDisplay:
                """Something with a callback method."""

                def refresh(self, price: float) -> str:
                    return f"showing {price:.2f}"


            display = PriceDisplay()
            plain_ref = weakref.ref(display.refresh)
            method_ref = weakref.WeakMethod(display.refresh)
            print(f"{plain_ref()=}  (the temporary bound method already died)")
            print(f"{method_ref()(99.5)=}")
            del display
            print(f"{method_ref()=}  (the instance died)")
            '''
        ),
        md(
            """
            #### The `__weakref__` slot

            Ordinary classes get a `__weakref__` descriptor automatically. A class with
            `__slots__` does not, unless you list `"__weakref__"` among the slots; it costs one
            pointer per instance.
            """
        ),
        code(
            """
            class SlottedPoint:
                __slots__ = ("x", "y")


            class WeakableSlottedPoint:
                __slots__ = ("x", "y", "__weakref__")


            print(f"{'__weakref__' in vars(Session)=}  (added automatically)")
            print(f"SlottedPoint:         {raised_message(lambda: weakref.ref(SlottedPoint()))}")
            print(f"WeakableSlottedPoint: {raised_message(lambda: weakref.ref(WeakableSlottedPoint()))}")
            print(
                f"{sys.getsizeof(SlottedPoint())=}  {sys.getsizeof(WeakableSlottedPoint())=}"
                f"  [{interpreter_label()}]"
            )
            del asha_session
            """
        ),
    ]


def _allocator_cells() -> list[NotebookNode]:
    """3.1.9 The allocator."""
    return [
        md(
            """
            ### 3.1.9 The allocator

            Python creates and frees small objects constantly, and the C `malloc` is slow for
            that pattern. CPython's default build therefore uses its own small-object
            allocator, **pymalloc**, for requests of **512 bytes or less**; bigger requests go
            to the system `malloc`.

            ```mermaid
            flowchart TD
                R["allocation request"] --> Q{"size <= 512 bytes?"}
                Q -- yes --> A["pymalloc"]
                Q -- no --> M["system malloc / mmap"]
                A --> AR["arena: 1 MiB from mmap"]
                AR --> P["pools: 16 KiB, each serving ONE size class"]
                P --> B["blocks: fixed size, multiple of 16 bytes"]
            ```

            <details><summary>ASCII fallback</summary>

            ```text
            request --(> 512 B)--> system malloc / mmap
               |
               +--(<= 512 B)--> pymalloc
                                  arena (1 MiB, from mmap)
                                    +-- pool (16 KiB) for 16-byte blocks
                                    +-- pool (16 KiB) for 32-byte blocks
                                    +-- pool (16 KiB) for 48-byte blocks ...
                                          +-- block, block, block (one object each)
            ```

            </details>

            | Level | Size (64-bit, 3.10+) | Holds |
            | --- | --- | --- |
            | Arena | 1 MiB, requested from the OS with `mmap` | many pools |
            | Pool | 16 KiB | blocks of **one** size class |
            | Block | 16, 32, 48, … 512 bytes (32 classes) | one object (request rounded up) |

            `sys._debugmallocstats()` prints pymalloc's tables. It writes to the C-level
            stderr, which a notebook does not capture, so the helper below runs it in a child
            interpreter and returns the lines.
            """
        ),
        code(
            '''
            def malloc_stats_lines(
                python_path: str, setup_code: str = "", extra_env: dict[str, str] | None = None
            ) -> list[str]:
                """Run setup_code then sys._debugmallocstats() in a child; return its report lines."""
                script = f"import sys\\n{setup_code}\\nsys._debugmallocstats()"
                completed = subprocess.run(
                    [python_path, "-c", script],
                    capture_output=True, text=True, env={**CHILD_ENV, **(extra_env or {})}, timeout=60,
                )  # fmt: skip
                return completed.stderr.splitlines()


            default_stats = malloc_stats_lines(sys.executable)
            print(interpreter_label())
            print(default_stats[0])
            summary_prefixes = ("# arenas allocated current", "# bytes in allocated blocks", "Total")
            shown_prefixes: set[str] = set()
            for line in default_stats:
                prefix = next((p for p in summary_prefixes if line.startswith(p)), None)
                if prefix and prefix not in shown_prefixes:
                    shown_prefixes.add(prefix)
                    print(line)
            '''
        ),
        md(
            """
            **Size classes in action.** A `bytes` object of 150 bytes needs about 183 bytes
            (header + data), which rounds up to the **192-byte** size class. The cell asks two
            child interpreters for their 192-byte row: one idle, one holding 10 000 such
            objects. Columns: size-class index, block size, pools, blocks in use, free blocks.
            """
        ),
        code(
            """
            def size_class_row(stats_lines: list[str], block_size: int) -> str:
                \"\"\"The pymalloc table row for one block size.\"\"\"
                for line in stats_lines:
                    columns = line.split()
                    if len(columns) == 5 and columns[1] == str(block_size):
                        return line.strip()
                return "<row not found>"


            print(f"{sys.getsizeof(bytes(150))=}  -> rounded up to a 192-byte block")
            print("class  size  pools  in-use  free")
            print(size_class_row(malloc_stats_lines(sys.executable), 192), " (idle child)")
            holding_code = "keep = [bytes(150) for _ in range(10_000)]"
            print(size_class_row(malloc_stats_lines(sys.executable, holding_code), 192), " (10 000 objects)")
            """
        ),
        md(
            """
            **Why RSS rarely shrinks.** pymalloc returns an arena to the OS only when **every**
            block in it is free. Free one million small objects but keep one in every 64
            alive, and almost every pool still has a live block, so almost every arena stays.
            The memory is free *inside* the process (reused for new objects) but the RSS does
            not drop. Free them all and arenas go back.

            > **Note:** RSS numbers depend on the OS and the allocator; read the trend.
            """
        ),
        code(
            '''
            class Crumb:
                """A small object (one pymalloc block each)."""


            def rss_megabytes() -> str:
                """RSS formatted in MB, or 'n/a'."""
                rss_value = rss_bytes()
                return "n/a" if rss_value is None else f"{rss_value / 1e6:6.1f} MB"


            print(f"start:                      RSS {rss_megabytes()}")
            crumbs = [Crumb() for _ in range(1_000_000)]
            print(f"1 000 000 objects:          RSS {rss_megabytes()}")
            survivors = crumbs[::64]
            del crumbs
            print(f"freed all but 1 in 64:      RSS {rss_megabytes()}  (arenas pinned)")
            del survivors
            print(f"freed the survivors too:    RSS {rss_megabytes()}  [{interpreter_label()}]")
            '''
        ),
        md(
            """
            **mimalloc in the free-threaded build.** pymalloc relies on the GIL for thread
            safety. The free-threaded build uses **mimalloc** (Microsoft's allocator, *New in
            3.13*) instead: it has per-thread heaps, and the free-threaded GC finds objects by
            walking mimalloc's heaps rather than a linked list. The default build also ships
            mimalloc (selectable with `PYTHONMALLOC=mimalloc`). Its report looks different: no
            512-byte limit, no arenas/pools table.
            """
        ),
        code(
            """
            free_threaded_python = find_free_threaded_python()
            if free_threaded_python is not None:
                print("free-threaded 3.15t child:")
                print("\\n".join(malloc_stats_lines(free_threaded_python)[:4]))
            else:
                print("Skipped: no free-threaded interpreter found (uv python install 3.15t)")
            if sysconfig.get_config_var("WITH_MIMALLOC"):
                print("\\nthis interpreter with PYTHONMALLOC=mimalloc:")
                print("\\n".join(malloc_stats_lines(sys.executable, extra_env={"PYTHONMALLOC": "mimalloc"})[:2]))
            else:
                print("Skipped: this interpreter was built without mimalloc")
            """
        ),
    ]


def _free_list_cells() -> list[NotebookNode]:
    """3.1.10 Free lists and caches."""
    return [
        md(
            """
            ### 3.1.10 Free lists and caches

            On top of pymalloc, CPython keeps a few shortcuts for the most common objects:

            | Mechanism | What it does | Visible as |
            | --- | --- | --- |
            | Free lists (`float`, `tuple` by length, `list`, `dict`, …) | A freed object's memory is kept on a per-type list and handed to the next object of that type | The same address reused at once |
            | Small-int cache | Ints from -5 up to 256 (1024 since 3.15) are preallocated, immortal singletons | `int("100") is int("100")` |
            | Empty-tuple singleton | There is only one `()` | `tuple() is ()` |
            | One-character Latin-1 strings, empty `str` / `bytes` | Preallocated singletons | `chr(97) is "a"` |
            | Interning | One shared object per distinct identifier-like string | `sys.intern`, identity of names |

            The free lists appear at the end of `sys._debugmallocstats()`.
            """
        ),
        code(
            """
            stats_lines = malloc_stats_lines(sys.executable)
            free_list_lines = [line.strip() for line in stats_lines if " free Py" in line]
            print(interpreter_label())
            print("\\n".join(free_list_lines[:8]))
            """
        ),
        md(
            """
            **Address reuse.** Free a float and immediately create another, and the new one
            usually lands at the same address, taken straight from the free list. That is why
            `id()` values are only unique **among objects alive at the same time**. Never
            store an `id()` as a long-term key.
            """
        ),
        code(
            """
            multiplier = len("ab")  # computed, so the floats below are new objects
            first_price = 1.5 * multiplier
            first_address = id(first_price)
            del first_price
            second_price = 2.5 * multiplier
            print(f"float reused the freed address: {id(second_price) == first_address}")

            first_list = [multiplier]
            first_list_address = id(first_list)
            del first_list
            second_list = [multiplier + 1]
            print(f"list reused the freed address:  {id(second_list) == first_list_address}")
            print(f"(free-list behaviour, not a guarantee)  [{interpreter_label()}]")
            """
        ),
        md(
            """
            **The small-int cache and singletons.** Numbers are built with `int(str)` at run
            time; literals in one cell would be folded into shared constants and hide the
            effect.
            """
        ),
        code(
            """
            print(interpreter_label())
            for number in (-6, -5, 256, 257, 1024, 1025):
                cached = int(str(number)) is int(str(number))
                print(f"{number:>5}: two separately built ints are one object: {cached}")

            empty_tuple_literal, empty_str_literal, empty_bytes_literal = (), "", b""
            print(f"built empty tuple is ():  {tuple(range(0)) is empty_tuple_literal}")
            print(f"built empty str is '':    {''.join([]) is empty_str_literal}")
            print(f"built empty bytes is b'': {bytes(bytearray()) is empty_bytes_literal}")
            print(f"chr(97) is 'a': {chr(97) is 'abc'[0]}  (one-character Latin-1 strings are cached)")
            """
        ),
        md(
            """
            **Interning.** The compiler interns identifiers and identifier-like string
            constants, so attribute names and dict keys in your code compare by pointer first.
            Strings built at run time are separate objects until you call `sys.intern`, which
            returns the one canonical copy.
            """
        ),
        code(
            """
            built_once = "".join(["order", "_", "status"])
            built_twice = "".join(["order", "_", "status"])
            print(f"{built_once == built_twice=}  {built_once is built_twice=}")
            canonical_once, canonical_twice = sys.intern(built_once), sys.intern(built_twice)
            print(f"after sys.intern: {canonical_once is canonical_twice=}")
            order_status_literal = "order_status"
            print(f"same object as the literal: {canonical_once is order_status_literal}")
            """
        ),
    ]


def _measuring_cells() -> list[NotebookNode]:
    """3.1.11 Measuring memory."""
    return [
        md(
            """
            ### 3.1.11 Measuring memory

            | Tool | Measures | Blind spots |
            | --- | --- | --- |
            | `sys.getsizeof(obj)` | One object, **shallow**: not the objects it references | Contents of containers, shared objects |
            | Recursive size (you write it) | An object graph | Must handle cycles and sharing (Lab 3.1, exercise 1) |
            | `tracemalloc` | Every allocation made through Python's allocators, with the line that made it | Memory allocated by C libraries directly |
            | Process RSS | What the OS has given the process | Cannot tell you which code; includes allocator slack |
            | memray (Phase 5) | Every allocation including native (C) ones, flame graphs | Separate tool, Linux/macOS |

            **Shallow vs recursive.** `sys.getsizeof` of an order dict counts only the dict's
            own table. A naive recursive version adds the contents, but it double-counts shared
            objects and never finishes on a cycle (it hits the recursion limit).
            """
        ),
        code(
            '''
            def naive_total_size(obj: object) -> int:
                """Recursive size of nested lists and dicts, WITHOUT cycle or sharing handling."""
                size = sys.getsizeof(obj)
                if isinstance(obj, list):
                    size += sum(naive_total_size(item) for item in obj)
                elif isinstance(obj, dict):
                    size += sum(naive_total_size(key) + naive_total_size(value) for key, value in obj.items())
                return size


            order = {"id": 7, "lines": [{"sku": "TEA-01", "qty": 2}, {"sku": "RICE-5", "qty": 1}]}
            print(f"{sys.getsizeof(order)=}  (shallow)")
            print(f"{naive_total_size(order)=}  (contents included)  [{interpreter_label()}]")
            looped_list: list[object] = [1, 2]
            looped_list.append(looped_list)
            print(f"on a cycle: {raised_error_name(lambda: naive_total_size(looped_list))}")
            '''
        ),
        md(
            """
            **`tracemalloc` snapshots and diffs.** `tracemalloc.start()` records the
            traceback of every allocation. Take a snapshot before and after some work, then
            `after.compare_to(before, "lineno")` lists the source lines whose allocations grew,
            biggest first. Each `StatisticDiff` has `size_diff`, `count_diff` and a
            `traceback`; `source_line` (from the setup cell) shows the code instead of a file
            path.
            """
        ),
        code(
            """
            tracemalloc.start()
            try:
                before_snapshot = tracemalloc.take_snapshot()
                price_history = [{"sku": f"SKU-{number}", "price": number * 1.5} for number in range(50_000)]
                labels = [f"label {number}" for number in range(50_000)]
                after_snapshot = tracemalloc.take_snapshot()
            finally:
                tracemalloc.stop()

            ignore_tracemalloc = [tracemalloc.Filter(False, tracemalloc.__file__)]
            growth = after_snapshot.filter_traces(ignore_tracemalloc).compare_to(
                before_snapshot.filter_traces(ignore_tracemalloc), "lineno"
            )
            for stat in growth[:2]:
                frame = stat.traceback[0]
                print(f"+{stat.size_diff / 1024:7.0f} KiB  +{stat.count_diff:>7,} blocks  {source_line(frame)}")
            del price_history, labels
            """
        ),
        md(
            """
            **Statistics, current and peak.** `snapshot.statistics("lineno")` ranks lines by
            the memory they hold *now*. `tracemalloc.get_traced_memory()` returns
            `(current, peak)` bytes, and `tracemalloc.reset_peak()` (3.9+) starts a new peak
            measurement, handy for measuring one phase of a program.
            """
        ),
        code(
            """
            tracemalloc.start()
            try:
                scratch_buffers = [bytes(1_000) for _ in range(5_000)]
                current_bytes, peak_bytes = tracemalloc.get_traced_memory()
                print(
                    f"holding 5 000 buffers: {current_bytes / 1e6:.2f} MB now, peak {peak_bytes / 1e6:.2f} MB"
                )
                top_stat = tracemalloc.take_snapshot().statistics("lineno")[0]
                top_source = source_line(top_stat.traceback[0])
                print(f"top line: {top_stat.size / 1e6:.2f} MB in {top_stat.count:,} blocks: {top_source}")
                del scratch_buffers
                current_bytes, peak_bytes = tracemalloc.get_traced_memory()
                print(
                    f"after del:             {current_bytes / 1e6:.2f} MB now, peak {peak_bytes / 1e6:.2f} MB"
                )
                tracemalloc.reset_peak()
                print(f"after reset_peak():    peak {tracemalloc.get_traced_memory()[1] / 1e6:.2f} MB")
            finally:
                tracemalloc.stop()
            """
        ),
        md(
            """
            **Grouping by traceback.** `tracemalloc.start(nframes)` keeps that many frames per
            allocation, and `statistics("traceback")` groups by the whole call stack, which
            tells you *which caller* drove the allocations, not just the line that made them.
            """
        ),
        code(
            '''
            def load_row(row_number: int) -> dict[str, object]:
                """Allocate one report row."""
                return {"row": row_number, "text": f"row {row_number} " * 3}


            def build_report(row_count: int) -> list[dict[str, object]]:
                """Allocate many rows through load_row."""
                return [load_row(row_number) for row_number in range(row_count)]


            tracemalloc.start(3)
            try:
                report_rows = build_report(20_000)
                report_snapshot = tracemalloc.take_snapshot()
            finally:
                tracemalloc.stop()
            largest = report_snapshot.statistics("traceback")[0]
            print(f"largest group: {largest.size / 1e6:.2f} MB in {largest.count:,} blocks; its call stack:")
            for frame in largest.traceback:
                print(f"    {source_line(frame)}")
            del report_rows
            '''
        ),
        md(
            """
            **Process RSS.** `rss_bytes()` (setup cell) reads `VmRSS` from `/proc/self/status`
            on Linux, with `psutil` as a fallback elsewhere. A large allocation (bigger than
            512 bytes, so it skips pymalloc) gets its own `mmap` and is returned to the OS as
            soon as it is freed, so RSS goes up **and back down**; compare with the small
            objects in 3.1.9.
            """
        ),
        code(
            """
            if rss_bytes() is None:
                print("Skipped: cannot read RSS on this platform (no /proc and no psutil)")
            else:
                rss_start = rss_bytes()
                big_block = b"x" * (80 * 1024 * 1024)  # written byte by byte, so the pages are real
                rss_with_block = rss_bytes()
                del big_block
                rss_after = rss_bytes()
                print(f"RSS at start:          {rss_start / 1e6:6.0f} MB")
                print(f"RSS with an 80 MiB block: {rss_with_block / 1e6:3.0f} MB")
                print(f"RSS after del:         {rss_after / 1e6:6.0f} MB")
                print(interpreter_label())
            """
        ),
        md(
            """
            **memray preview.** [memray](https://bloomberg.github.io/memray/) (Bloomberg)
            traces every allocation, including those made by C extensions, and renders flame
            graphs. It is a Phase 5 dependency; the cell checks whether it is installed. Typical
            use:

            ```bash
            uv run memray run -o report.bin my_script.py       # record
            uv run memray flamegraph report.bin                # HTML flame graph
            uv run memray run --native -o report.bin my_script.py   # include C frames
            ```

            In Jupyter: `%load_ext memray`, then `%%memray_flamegraph` at the top of a cell.
            """
        ),
        code(
            """
            if importlib.util.find_spec("memray") is None:
                print("Skipped: memray is not installed (it is added in Phase 5: uv add memray)")
            else:
                import memray

                print(f"memray {memray.__version__} is installed; try %load_ext memray")
            """
        ),
    ]


def _leak_cells() -> list[NotebookNode]:
    """3.1.12 Memory leaks in practice."""
    return [
        md(
            """
            ### 3.1.12 Memory leaks in practice

            In a garbage-collected language a "leak" means memory that is still
            **reachable** but no longer **useful**: something keeps a reference you forgot
            about. Six classic sources follow, each with a demo and a fix. A weak reference
            to the victim proves whether it is still alive.

            | Leak | What holds the reference | Fix |
            | --- | --- | --- |
            | Unbounded cache | a module-level dict that only grows | `lru_cache(maxsize=...)`, a bounded `OrderedDict`, TTLs |
            | `lru_cache` on a method | the cache, keyed by `self` | per-instance cache, or cache a function of plain values |
            | Captured closure | a stored callback's closure cell | capture only the values you need |
            | Stored traceback | exception → traceback → frames → locals | store a string or `TracebackException`, or `traceback.clear_frames` |
            | Unremoved listener | the publisher's listener list | unsubscribe (context manager) or weak references |
            | C-extension leak | memory `tracemalloc` cannot see | RSS trend, memray `--native`, valgrind, debug builds |

            #### Unbounded caches

            A dict used as a cache, keyed by user input, grows forever.
            """
        ),
        code(
            '''
            _quote_cache: dict[str, float] = {}


            def quote_price_unbounded(sku: str) -> float:
                """Cache every quote forever."""
                if sku not in _quote_cache:
                    _quote_cache[sku] = len(sku) * 9.5
                return _quote_cache[sku]


            @functools.lru_cache(maxsize=1_024)
            def quote_price_bounded(sku: str) -> float:
                """Keep only the 1 024 most recently used quotes."""
                return len(sku) * 9.5


            for number in range(100_000):
                quote_price_unbounded(f"SKU-{number}")
                quote_price_bounded(f"SKU-{number}")
            print(f"{len(_quote_cache)=:,}  (one entry per distinct key, forever)")
            print(f"{quote_price_bounded.cache_info()=}")
            _quote_cache.clear()
            quote_price_bounded.cache_clear()
            '''
        ),
        md(
            """
            #### `lru_cache` on methods

            `@lru_cache` (or `@cache`, which is `lru_cache(maxsize=None)`) on a method caches
            on the **class**, and `self` is part of every key,
            so the cache keeps every instance alive (ruff rule B019 warns about this). The fix
            here gives each instance its own cache: the instance and its cache form a cycle
            that the GC can free.
            """
        ),
        code(
            '''
            class PriceEngine:
                """Holds a big rate table and caches quotes the wrong way."""

                def __init__(self, region: str) -> None:
                    self.region = region
                    self.rate_table = bytearray(2_000_000)

                @functools.cache  # noqa: B019 (the leak being demonstrated)
                def quote(self, sku: str) -> float:
                    return len(sku) * 2.0


            class FixedPriceEngine:
                """Same engine with a per-instance cache."""

                def __init__(self, region: str) -> None:
                    self.region = region
                    self.rate_table = bytearray(2_000_000)
                    self.quote = functools.lru_cache(maxsize=256)(self._quote)

                def _quote(self, sku: str) -> float:
                    return len(sku) * 2.0


            engine_refs: dict[str, weakref.ref[object]] = {}
            for engine_class in (PriceEngine, FixedPriceEngine):
                engine = engine_class("south")
                engine.quote("TEA-01")
                engine_refs[engine_class.__name__] = weakref.ref(engine)
                del engine
                gc.collect()
                alive = engine_refs[engine_class.__name__]() is not None
                print(f"{engine_class.__name__:<16} alive after del + collect: {alive}")
            PriceEngine.quote.cache_clear()
            print(f"after cache_clear(): PriceEngine alive = {engine_refs['PriceEngine']() is not None}")
            '''
        ),
        md(
            """
            > **Note:** `cache_clear()` releases the leaked `PriceEngine`. For a method without
            > arguments, `functools.cached_property` stores the value on the instance and does
            > not leak.

            #### Captured closures

            A closure keeps alive **every variable it uses** from the enclosing function. A
            callback that only needs a row count but mentions the whole report keeps the whole
            report.
            """
        ),
        code(
            '''
            class Report:
                """A report with many rows."""

                def __init__(self, row_count: int) -> None:
                    self.rows = [{"row": number} for number in range(row_count)]


            pending_callbacks: list[Callable[[], str]] = []


            def schedule_summary_leaky(report: Report) -> None:
                """The callback captures the whole report."""
                pending_callbacks.append(lambda: f"{len(report.rows)} rows")


            def schedule_summary_fixed(report: Report) -> None:
                """The callback captures only an int."""
                row_count = len(report.rows)
                pending_callbacks.append(lambda: f"{row_count} rows")


            for schedule in (schedule_summary_leaky, schedule_summary_fixed):
                big_report = Report(50_000)
                report_ref = weakref.ref(big_report)
                schedule(big_report)
                del big_report
                captured = type(pending_callbacks[-1].__closure__[0].cell_contents).__name__
                alive = report_ref() is not None
                print(f"{schedule.__name__:<24} captures a {captured:<6} report alive: {alive}")
            pending_callbacks.clear()
            '''
        ),
        md(
            """
            #### Stored tracebacks

            An exception object holds its traceback, the traceback holds the frames, and the
            frames hold **all their local variables**. Keeping exceptions in a list (for a
            later error report) keeps every buffer those functions had in hand.
            `traceback.clear_frames(tb)` drops the locals; storing
            `traceback.TracebackException.from_exception(error)` (or a formatted string) keeps
            the information without the frames.
            """
        ),
        code(
            '''
            class UploadBuffer:
                """A large in-memory upload."""

                def __init__(self) -> None:
                    self.data = bytearray(5_000_000)


            buffer_refs: list[weakref.ref[UploadBuffer]] = []
            stored_errors: list[BaseException] = []


            def parse_upload() -> None:
                """Fails while holding a big buffer in a local variable."""
                upload_buffer = UploadBuffer()
                buffer_refs.append(weakref.ref(upload_buffer))
                raise ValueError("bad header")


            try:
                parse_upload()
            except ValueError as error:
                stored_errors.append(error)  # kept for a later report
            print(f"buffer alive while the exception is stored: {buffer_refs[-1]() is not None}")
            traceback.clear_frames(stored_errors[-1].__traceback__)
            print(f"after traceback.clear_frames:              {buffer_refs[-1]() is not None}")
            summary = traceback.TracebackException.from_exception(stored_errors[-1])
            print(f"still reportable: {''.join(summary.format_exception_only()).strip()}")
            stored_errors.clear()
            '''
        ),
        md(
            """
            #### Unremoved listeners

            A publisher keeps a list of callbacks. A widget subscribes with a bound method
            (which references the widget) and is "closed" but never unsubscribes: the
            publisher keeps every widget alive. The fix below subscribes inside a context
            manager that always unsubscribes. (Lab 3.1, exercise 5, fixes the same problem
            with weak references instead.)
            """
        ),
        code(
            '''
            class PriceTicker:
                """Publishes prices to subscribed callbacks."""

                def __init__(self) -> None:
                    self.listeners: list[Callable[[float], None]] = []

                def subscribe(self, listener: Callable[[float], None]) -> None:
                    self.listeners.append(listener)

                def unsubscribe(self, listener: Callable[[float], None]) -> None:
                    self.listeners.remove(listener)


            class PriceWidget:
                """A screen widget with a big pixel buffer."""

                def __init__(self) -> None:
                    self.pixels = bytearray(1_000_000)
                    self.last_price: float | None = None

                def on_price(self, price: float) -> None:
                    self.last_price = price


            @contextmanager
            def subscribed(ticker: PriceTicker, listener: Callable[[float], None]) -> Iterator[None]:
                """Subscribe for the duration of a with block."""
                ticker.subscribe(listener)
                try:
                    yield
                finally:
                    ticker.unsubscribe(listener)
            '''
        ),
        md("Five widgets with the leak, then five with the context manager:"),
        code(
            """
            leaky_ticker = PriceTicker()
            widget_refs = []
            for _ in range(5):
                widget = PriceWidget()
                leaky_ticker.subscribe(widget.on_price)  # never unsubscribed
                widget_refs.append(weakref.ref(widget))
            del widget
            alive_count = sum(ref() is not None for ref in widget_refs)
            print(f"leaky:  {len(leaky_ticker.listeners)} listeners, {alive_count} widgets alive")

            fixed_ticker = PriceTicker()
            widget_refs.clear()
            for _ in range(5):
                widget = PriceWidget()
                with subscribed(fixed_ticker, widget.on_price):
                    pass  # the widget is on screen here
                widget_refs.append(weakref.ref(widget))
            del widget
            alive_count = sum(ref() is not None for ref in widget_refs)
            print(f"fixed:  {len(fixed_ticker.listeners)} listeners, {alive_count} widgets alive")
            leaky_ticker.listeners.clear()
            """
        ),
        md(
            """
            #### C-extension leaks

            Memory allocated by C code with plain `malloc` bypasses Python's allocators, so
            `tracemalloc` never sees it; only RSS grows. The cell simulates a C library that
            allocates 64 MiB through `ctypes` (and frees it in `finally`, unlike a real leak).
            When RSS climbs while `tracemalloc` stays flat, suspect native code. Tools for that
            case: memray with `--native`, valgrind / heaptrack, and a CPython debug build,
            where `sys.gettotalrefcount()` exposes reference leaks in extensions.
            """
        ),
        code(
            """
            try:
                libc = ctypes.CDLL(None)  # the C library already loaded into this process
                libc.malloc.restype, libc.malloc.argtypes = ctypes.c_void_p, [ctypes.c_size_t]
                libc.free.argtypes = [ctypes.c_void_p]
                libc.memset.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_size_t]
            except (OSError, AttributeError) as error:
                libc = None
                print(f"Skipped: cannot load the C library here ({type(error).__name__})")

            if libc is not None and rss_bytes() is not None:
                block_size = 64 * 1024 * 1024
                tracemalloc.start()
                rss_before, traced_before = rss_bytes(), tracemalloc.get_traced_memory()[0]
                native_block = libc.malloc(block_size)
                try:
                    libc.memset(native_block, 1, block_size)  # touch the pages
                    rss_growth = (rss_bytes() - rss_before) / 1e6
                    traced_growth = (tracemalloc.get_traced_memory()[0] - traced_before) / 1e6
                    print(f"RSS grew {rss_growth:.0f} MB; tracemalloc saw {traced_growth:.3f} MB")
                finally:
                    libc.free(native_block)
                    tracemalloc.stop()
            print(f"{hasattr(sys, 'gettotalrefcount')=}  (True only on debug builds)")
            """
        ),
        md(
            """
            #### A diagnosis workflow

            1. **Confirm the trend.** Plot or log RSS over hours. Steady growth under steady
               load is a leak; a plateau is just a warm cache or allocator slack.
            2. **Reproduce in a loop.** Find a request or job you can run N times in a test
               or a REPL.
            3. **Diff `tracemalloc` snapshots** between rounds (`compare_to(..., "lineno")`).
               Lines that grow **every** round are suspects; one-time growth is warm-up.
            4. **Find the holder.** `statistics("traceback")` for the call path, then
               `gc.get_referrers(suspect)` (or objgraph's back-reference chains) to see which
               container keeps the objects.
            5. **Fix and lock it in** with a test: a weak reference that must die, or a
               `tracemalloc` growth limit.
            6. **If `tracemalloc` is flat but RSS grows**, look at native code and
               fragmentation: memray `--native`, valgrind, `sys._debugmallocstats()`.

            The cell walks steps 2–4 on a request handler with a hidden leak.
            """
        ),
        code(
            '''
            _audit_log: list[object] = []  # the hidden holder


            class OrderSession:
                """Per-request state with a payload."""

                def __init__(self, order_id: int) -> None:
                    self.order_id = order_id
                    self.payload = "x" * 2_000

                def close(self) -> None:
                    _audit_log.append(self)  # bug: keeps every session forever


            def handle_order(order_id: int) -> None:
                OrderSession(order_id).close()


            tracemalloc.start()
            try:
                round_snapshots = []
                for _ in range(3):
                    for order_id in range(2_000):
                        handle_order(order_id)
                    round_snapshots.append(tracemalloc.take_snapshot())
            finally:
                tracemalloc.stop()
            for earlier, later in itertools.pairwise(round_snapshots):
                top = later.compare_to(earlier, "lineno")[0]
                print(f"round growth +{top.size_diff / 1024:.0f} KiB at: {source_line(top.traceback[0])}")
            suspect = _audit_log[-1]
            held_by_log = any(referrer is _audit_log for referrer in gc.get_referrers(suspect))
            print(f"suspect is held by _audit_log: {held_by_log}")
            del suspect
            _audit_log.clear()
            '''
        ),
    ]


def _js_bridge_cells() -> list[NotebookNode]:
    """3.1.13 JS bridge."""
    return [
        md(
            """
            ### 3.1.13 JS bridge

            | Topic | V8 (Node.js, Chrome) | CPython |
            | --- | --- | --- |
            | Main mechanism | Tracing GC: finds live objects from roots, everything else is garbage | Reference counting frees objects as soon as the count is 0 |
            | Generations | Young generation (scavenger, copies survivors) + old generation (mark-sweep-compact) | Generations only for the cycle collector; refcounting has no generations |
            | Cycles | No problem for a tracing GC | Need the cyclic GC (3.1.6) |
            | When memory is freed | Whenever the GC decides | At the `del` / return for acyclic objects |
            | Object movement | Compaction moves objects | Objects never move; fragmentation possible (3.1.9) |
            | Pauses | Incremental and concurrent marking | Short GC pauses for tracked containers only |
            | Weak references | `WeakRef` + `deref()` | `weakref.ref` + call it |
            | Finalization | `FinalizationRegistry`: the callback *may* run later, or never | `weakref.finalize`: runs at death (deterministic in CPython) and at exit |
            | Weak maps | `WeakMap` (weak keys), `WeakSet` | `WeakKeyDictionary`, `WeakSet`, plus `WeakValueDictionary` |
            | Heap tools | DevTools heap snapshots, `--inspect` | `tracemalloc`, `gc`, memray |

            ```javascript
            // JavaScript: when (and whether) the callback runs is up to the engine
            const registry = new FinalizationRegistry((label) => console.log(`${label} collected`));
            let session = { user: "asha" };
            const sessionRef = new WeakRef(session);
            registry.register(session, "session");
            session = null;            // nothing printed yet; maybe later, maybe never
            console.log(sessionRef.deref()); // probably still the object
            ```

            The Python version prints at the exact line where the last reference goes.
            """
        ),
        code(
            """
            finalization_events: list[str] = []
            session = Session("asha")
            session_ref = weakref.ref(session)
            weakref.finalize(session, finalization_events.append, "session collected")
            session = None  # last reference gone: finalizer runs right here
            finalization_events.append("next statement")
            print(f"{finalization_events=}")
            print(f"{session_ref()=}")
            """
        ),
        *predict_cells(
            """
            import weakref

            class Node:
                pass

            first, second = Node(), Node()
            first.peer, second.peer = second, first
            probe = weakref.ref(first)
            del first, second
            print(probe() is None)
            """,
            """
            ```text
            False
            ```

            The two nodes form a cycle, so each keeps the other's count above zero after the
            names are deleted. Only the cyclic GC can free them, and it has not run yet.
            (In rare runs an automatic collection could happen between the two lines; the
            proof disables the collector to make the result certain.) A JS developer expects
            "maybe" here too, but for a different reason: V8 frees nothing until it decides
            to collect.
            """,
            '''
            class Node:
                """A node that will be part of a cycle."""


            gc_was_enabled = gc.isenabled()
            gc.disable()
            try:
                first, second = Node(), Node()
                first.peer, second.peer = second, first
                probe = weakref.ref(first)
                del first, second
                print(probe() is None)
                gc.collect()
                print(f"after gc.collect(): {probe() is None}")
            finally:
                if gc_was_enabled:
                    gc.enable()
            ''',
        ),
    ]


def _lab_size_refcount_cycle_cells() -> list[NotebookNode]:
    """Lab 3.1 exercises 1–3."""
    return [
        md(
            """
            ### Lab 3.1

            Six exercises. For each, complete the stub, then run the check cell. Until then
            the checks print FAIL; that is expected. Checks never compare against fixed sizes
            or counts: expected values are measured live with `sys.getsizeof` and
            `sys.getrefcount` on your interpreter.

            #### Exercise 1 — `deep_getsizeof(obj)` with cycle handling

            Return the total `sys.getsizeof` of `obj` and every object reachable from it
            through:

            - items of `list`, `tuple`, `set` and `frozenset`,
            - keys **and** values of `dict`,
            - the instance `__dict__` (count the dict itself too) and any `__slots__`
              attributes that are set (walk the class's `__mro__` for `__slots__`).

            Count every object **once** (track `id()`s you have seen), so shared objects and
            cycles are handled. Do not descend into classes, functions or modules. An
            iterative version with an explicit stack avoids the recursion limit.
            """
        ),
        code(
            '''
            def deep_getsizeof(obj: object) -> int:
                """Total size of obj and everything reachable from it, each object counted once."""
                raise NotImplementedError("Lab 3.1: implement deep_getsizeof")
            '''
        ),
        md(
            """
            Run the checks. Expected values are computed with `sys.getsizeof` at check time;
            objects are built inside the check functions.
            """
        ),
        code(
            '''
            class StockLine:
                """An instance with a __dict__."""

                def __init__(self, sku: str, quantity: int) -> None:
                    self.sku = sku
                    self.quantity = quantity


            class SlottedStockLine:
                """An instance with __slots__."""

                __slots__ = ("sku", "quantity")

                def __init__(self, sku: str, quantity: int) -> None:
                    self.sku = sku
                    self.quantity = quantity


            def check_flat_list() -> bool:
                first_text, second_text = "alpha" * 3, "beta" * 3
                items = [first_text, second_text]
                expected = sys.getsizeof(items) + sys.getsizeof(first_text) + sys.getsizeof(second_text)
                return deep_getsizeof(items) == expected


            def check_shared_counted_once() -> bool:
                shared_text = "shared" * 20
                items = [shared_text, shared_text, shared_text]
                return deep_getsizeof(items) == sys.getsizeof(items) + sys.getsizeof(shared_text)


            def check_dict_keys_and_values() -> bool:
                key_text, value_list = "key" * 5, [10_001]
                mapping = {key_text: value_list}
                expected = (
                    sys.getsizeof(mapping) + sys.getsizeof(key_text)
                    + sys.getsizeof(value_list) + sys.getsizeof(value_list[0])
                )  # fmt: skip
                return deep_getsizeof(mapping) == expected


            def check_self_referencing_list() -> bool:
                looped: list[object] = [10_002]
                looped.append(looped)
                return deep_getsizeof(looped) == sys.getsizeof(looped) + sys.getsizeof(looped[0])


            def check_instance_dict() -> bool:
                line = StockLine("TEA-" + "01", 10_003)
                total = deep_getsizeof(line)  # may materialize __dict__ first
                expected = (
                    sys.getsizeof(line) + sys.getsizeof(vars(line))
                    + sys.getsizeof("sku") + sys.getsizeof("quantity")
                    + sys.getsizeof(line.sku) + sys.getsizeof(line.quantity)
                )  # fmt: skip
                return total == expected


            def check_slots() -> bool:
                line = SlottedStockLine("RICE-" + "05", 10_004)
                expected = sys.getsizeof(line) + sys.getsizeof(line.sku) + sys.getsizeof(line.quantity)
                return deep_getsizeof(line) == expected


            def check_two_object_cycle() -> bool:
                first, second = StockLine("A", 1), StockLine("B", 2)
                first.peer, second.peer = second, first
                return deep_getsizeof(first) == deep_getsizeof(second)


            run_checks(
                [
                    ("int equals getsizeof", lambda: deep_getsizeof(10**20) == sys.getsizeof(10**20), True),
                    ("flat list", check_flat_list, True),
                    ("shared object counted once", check_shared_counted_once, True),
                    ("dict keys and values", check_dict_keys_and_values, True),
                    ("self-referencing list", check_self_referencing_list, True),
                    ("instance __dict__", check_instance_dict, True),
                    ("__slots__ attributes", check_slots, True),
                    ("two-object cycle", check_two_object_cycle, True),
                    ("tuple of sets", lambda: deep_getsizeof(({1}, {1})) > sys.getsizeof(({1}, {1})), True),
                ]
            )
            '''
        ),
        md(
            """
            #### Exercise 2 — predict six reference counts, then verify

            Each scenario starts from one object referenced by one local variable and does one
            thing. Predict how much `sys.getrefcount(target)` changes compared with the start
            (`+1`, `+2`, `0`, …) **before** running the check. The check measures the real
            changes on your interpreter.

            | Key | What happens |
            | --- | --- |
            | `"second name"` | `alias = target` |
            | `"list append"` | `holder = []; holder.append(target)` |
            | `"dict key and value"` | `mapping = {target: target}` |
            | `"tuple twice"` | `pair = (target, target)` |
            | `"weak reference"` | `ref = weakref.ref(target)` |
            | `"bind then del"` | `temporary = target; del temporary` |

            Return a dict with those six keys and your predicted change for each.
            """
        ),
        code(
            '''
            def predict_refcount_deltas() -> dict[str, int]:
                """Your predicted change in sys.getrefcount(target) for each scenario."""
                raise NotImplementedError("Lab 3.1: fill in your six predictions")
            '''
        ),
        md(
            """
            Run the checks. `measure_refcount_deltas()` performs each scenario inside a function
            and measures the change (changes are reliable even where borrowed references make
            the absolute count unusual).
            """
        ),
        code(
            '''
            class RefcountTarget:
                """The object whose count is measured."""


            def measure_refcount_deltas() -> dict[str, int]:
                """Measure the change in sys.getrefcount(target) for each scenario."""
                target = RefcountTarget()
                start = sys.getrefcount(target)
                measured: dict[str, int] = {}
                alias = target
                measured["second name"] = sys.getrefcount(target) - start
                del alias
                holder = []
                holder.append(target)
                measured["list append"] = sys.getrefcount(target) - start
                del holder
                mapping = {target: target}
                measured["dict key and value"] = sys.getrefcount(target) - start
                del mapping
                pair = (target, target)
                measured["tuple twice"] = sys.getrefcount(target) - start
                del pair
                ref = weakref.ref(target)
                measured["weak reference"] = sys.getrefcount(target) - start
                del ref
                temporary = target
                del temporary
                measured["bind then del"] = sys.getrefcount(target) - start
                return measured


            def predicted_delta(scenario: str) -> int:
                """The learner's prediction for one scenario."""
                return predict_refcount_deltas()[scenario]


            measured_deltas = measure_refcount_deltas()
            print(f"[{interpreter_label()}]")
            run_checks(
                [("all six keys answered", lambda: sorted(predict_refcount_deltas()), sorted(measured_deltas))]
                + [
                    (f"{scenario}: measured {delta:+d}", functools.partial(predicted_delta, scenario), delta)
                    for scenario, delta in measured_deltas.items()
                ]
            )
            '''
        ),
        md(
            """
            #### Exercise 3 — prove a cycle is freed only by `gc.collect`

            Write `cycle_lifecycle()`:

            1. Remember whether the collector is enabled, then `gc.disable()`.
            2. Build two `CycleNode` objects that reference each other, and keep only a
               `weakref.ref` to one of them.
            3. Delete both names and record whether the object is still alive.
            4. Call `gc.collect()` and record again.
            5. In a `finally` block, re-enable the collector **only if it was enabled before**.

            Return `(alive_after_del, alive_after_collect)`. Also write
            `acyclic_lifecycle()`, which does steps 1–5 with two nodes that do **not** form a
            cycle (only `first.peer = second`), and returns the same pair.
            """
        ),
        code(
            '''
            class CycleNode:
                """A node with an optional peer."""

                def __init__(self, name: str) -> None:
                    self.name = name
                    self.peer: CycleNode | None = None


            def cycle_lifecycle() -> tuple[bool, bool]:
                """(alive after del, alive after gc.collect) for a two-node cycle."""
                raise NotImplementedError("Lab 3.1: implement cycle_lifecycle")


            def acyclic_lifecycle() -> tuple[bool, bool]:
                """The same measurements for two nodes without a cycle."""
                raise NotImplementedError("Lab 3.1: implement acyclic_lifecycle")
            '''
        ),
        md("Run the checks. The last two confirm the collector's state is restored either way."),
        code(
            '''
            def set_collector(enabled: bool) -> None:
                """Switch the cyclic GC on or off."""
                if enabled:
                    gc.enable()
                else:
                    gc.disable()


            def state_restored_after(function: Callable[[], object], start_enabled: bool) -> bool:
                """Run function with the collector on or off and check the state is unchanged."""
                was_enabled = gc.isenabled()
                set_collector(start_enabled)
                try:
                    function()
                    return gc.isenabled() == start_enabled
                finally:
                    set_collector(was_enabled)


            run_checks(
                [
                    ("cycle survives del, freed by collect", cycle_lifecycle, (True, False)),
                    ("no cycle: freed at del", acyclic_lifecycle, (False, False)),
                    ("collector stays enabled", lambda: state_restored_after(cycle_lifecycle, True), True),
                    ("collector stays disabled", lambda: state_restored_after(cycle_lifecycle, False), True),
                ]
            )
            '''
        ),
    ]


def _lab_cache_emitter_worker_cells() -> list[NotebookNode]:
    """Lab 3.1 exercises 4–6."""
    return [
        md(
            """
            #### Exercise 4 — an `ImageCache` on `WeakValueDictionary`

            Decoding images is slow, so the app caches them, but the cache must not keep
            images alive on its own: an image should be freed as soon as no screen uses it.

            `ImageCache(loader)`:

            - `get(path)` returns the cached `Image` if one is still alive, otherwise calls
              `loader(path)` once, stores the result **weakly** and returns it.
            - `load_count` (attribute or property): how many times `loader` was called.
            - `len(cache)`: number of **live** entries; `path in cache`: is a live image
              cached for that path.

            `Image` and `decode_image` are given.
            """
        ),
        code(
            '''
            class Image:
                """A decoded image (given)."""

                def __init__(self, path: str, pixels: bytes) -> None:
                    self.path = path
                    self.pixels = pixels


            def decode_image(path: str) -> Image:
                """Slow decoder stand-in (given)."""
                return Image(path, bytes(10_000))


            class ImageCache:
                """Caches decoded images without keeping them alive."""

                def __init__(self, loader: Callable[[str], Image]) -> None:
                    raise NotImplementedError("Lab 3.1: implement ImageCache")
            '''
        ),
        md("Run the checks. Each check builds its own cache and images inside a function."),
        code(
            """
            def cache_reuses_live_image() -> tuple[bool, int]:
                cache = ImageCache(decode_image)
                first = cache.get("logo.png")
                second = cache.get("logo.png")
                return first is second, cache.load_count


            def cache_forgets_dead_image() -> tuple[int, bool, int]:
                cache = ImageCache(decode_image)
                logo = cache.get("logo.png")
                del logo
                return len(cache), "logo.png" in cache, cache.load_count


            def cache_reloads_after_death() -> int:
                cache = ImageCache(decode_image)
                cache.get("logo.png")  # result not kept: dies at once
                cache.get("logo.png")
                return cache.load_count


            def cache_does_not_keep_alive() -> bool:
                cache = ImageCache(decode_image)
                banner = cache.get("banner.png")
                banner_ref = weakref.ref(banner)
                del banner
                return banner_ref() is None


            def cache_counts_live_entries() -> tuple[int, bool]:
                cache = ImageCache(decode_image)
                kept = [cache.get(name) for name in ("a.png", "b.png", "c.png")]
                cache.get("d.png")
                return len(cache), all(name in cache for name in ("a.png", "b.png", "c.png")) and len(kept) == 3


            run_checks(
                [
                    ("same object while alive, one load", cache_reuses_live_image, (True, 1)),
                    ("entry vanishes when the image dies", cache_forgets_dead_image, (0, False, 1)),
                    ("reloads after the image died", cache_reloads_after_death, 2),
                    ("cache does not keep images alive", cache_does_not_keep_alive, True),
                    ("len counts only live entries", cache_counts_live_entries, (3, True)),
                ]
            )
            """
        ),
        md(
            """
            #### Exercise 5 — find and fix a leaking `EventEmitter`

            `LeakyEventEmitter` (given) stores every callback strongly. Subscribers that
            register a bound method can never be freed, as the demo below shows.

            Write `EventEmitter` that fixes it:

            - `on(event, callback)` subscribes and returns a function that unsubscribes.
              **Bound methods** are stored as `weakref.WeakMethod`, so the emitter does not
              keep their instance alive. Other callables (plain functions, lambdas) are stored
              strongly, otherwise a lambda would die immediately.
            - `emit(event, *args)` calls the live listeners in subscription order, drops dead
              ones, and returns how many were called.
            - `listener_count(event)` returns the number of **live** listeners.
            """
        ),
        code(
            '''
            class LeakyEventEmitter:
                """Stores every callback strongly (given)."""

                def __init__(self) -> None:
                    self.listeners: dict[str, list[Callable[..., object]]] = {}

                def on(self, event: str, callback: Callable[..., object]) -> None:
                    self.listeners.setdefault(event, []).append(callback)

                def emit(self, event: str, *args: object) -> int:
                    for callback in self.listeners.get(event, []):
                        callback(*args)
                    return len(self.listeners.get(event, []))


            class StockAlertPanel:
                """A subscriber with a bound-method callback (given)."""

                def __init__(self) -> None:
                    self.alerts: list[str] = []
                    self.screen_buffer = bytearray(500_000)

                def on_low_stock(self, sku: str) -> None:
                    self.alerts.append(sku)


            leaky_emitter = LeakyEventEmitter()
            panel = StockAlertPanel()
            leaky_emitter.on("low_stock", panel.on_low_stock)
            panel_ref = weakref.ref(panel)
            del panel  # the screen closed...
            print(f"panel still alive: {panel_ref() is not None}  (the emitter holds it)")
            print(f"emit still reaches it: {leaky_emitter.emit('low_stock', 'TEA-01')} listener(s)")
            leaky_emitter.listeners.clear()
            '''
        ),
        md("Now the stub:"),
        code(
            '''
            class EventEmitter:
                """An emitter that does not keep bound-method subscribers alive."""

                def __init__(self) -> None:
                    raise NotImplementedError("Lab 3.1: implement EventEmitter")
            '''
        ),
        md("Run the checks."),
        code(
            """
            def emitter_calls_functions_and_methods() -> tuple[int, list[str], list[str]]:
                emitter = EventEmitter()
                seen: list[str] = []
                panel = StockAlertPanel()
                emitter.on("low_stock", seen.append)
                emitter.on("low_stock", panel.on_low_stock)
                called = emitter.emit("low_stock", "TEA-01")
                return called, seen, panel.alerts


            def emitter_lets_subscriber_die() -> tuple[bool, int, int]:
                emitter = EventEmitter()
                panel = StockAlertPanel()
                emitter.on("low_stock", panel.on_low_stock)
                panel_ref = weakref.ref(panel)
                del panel
                return panel_ref() is None, emitter.listener_count("low_stock"), emitter.emit("low_stock", "X")


            def emitter_keeps_lambdas() -> tuple[int, int]:
                emitter = EventEmitter()
                seen: list[str] = []
                emitter.on("restock", lambda sku: seen.append(sku))
                return emitter.listener_count("restock"), emitter.emit("restock", "RICE-5")


            def emitter_unsubscribe() -> tuple[int, int]:
                emitter = EventEmitter()
                unsubscribe = emitter.on("restock", print)
                before = emitter.listener_count("restock")
                unsubscribe()
                return before, emitter.listener_count("restock")


            def emitter_order() -> list[str]:
                emitter = EventEmitter()
                calls: list[str] = []
                emitter.on("tick", lambda: calls.append("first"))
                emitter.on("tick", lambda: calls.append("second"))
                emitter.emit("tick")
                return calls


            run_checks(
                [
                    (
                        "functions and bound methods are called",
                        emitter_calls_functions_and_methods,
                        (2, ["TEA-01"], ["TEA-01"]),
                    ),
                    ("subscriber freed, listener dropped", emitter_lets_subscriber_die, (True, 0, 0)),
                    ("lambdas are kept", emitter_keeps_lambdas, (1, 1)),
                    ("on() returns an unsubscribe function", emitter_unsubscribe, (1, 0)),
                    ("subscription order", emitter_order, ["first", "second"]),
                    ("unknown event", lambda: EventEmitter().emit("nothing"), 0),
                    ("unknown event count", lambda: EventEmitter().listener_count("nothing"), 0),
                ]
            )
            """
        ),
        md(
            """
            #### Exercise 6 — diagnose a leaking long-running worker with `tracemalloc`

            `LeakyWorker` (given) handles requests forever, and its memory grows. Find the
            line with `tracemalloc`, then fix it.

            1. `top_growth_line(workload, *, repeat=3)`:
               - start `tracemalloc` if it is not already tracing (and stop it at the end
                 only if you started it),
               - run `workload()` once as a warm-up, take a snapshot, run it `repeat` more
                 times, take another snapshot,
               - compare with `"lineno"`, ignoring frames from the `tracemalloc` module
                 itself (`tracemalloc.Filter(False, tracemalloc.__file__)`),
               - return `(source_text, size_diff)` for the line with the largest positive
                 growth, where `source_text` is the stripped source line (`source_line` from
                 the setup cell does this).
            2. `BoundedWorker(max_audit=100)`: a subclass of `LeakyWorker` whose `audit_trail`
               keeps only the newest `max_audit` entries (hint: `deque(maxlen=...)`), without
               changing `handle`.
            """
        ),
        code(
            '''
            class LeakyWorker:
                """A long-running request handler (given). One line in it leaks."""

                def __init__(self) -> None:
                    self.processed_count = 0
                    self.recent_ids: list[int] = []
                    self.audit_trail: list[str] = []

                def handle(self, request_id: int) -> str:
                    payload = f"request {request_id}: " + "x" * 200
                    checksum = sum(payload.encode()) % 997
                    self.recent_ids = self.recent_ids[-9:] + [request_id]
                    self.audit_trail.append(f"{request_id}:{checksum}:" + payload)
                    self.processed_count += 1
                    return f"ok {checksum}"


            def top_growth_line(workload: Callable[[], object], *, repeat: int = 3) -> tuple[str, int]:
                """(source line, bytes) of the line whose allocations grew most across repeats."""
                raise NotImplementedError("Lab 3.1: implement top_growth_line")


            class BoundedWorker(LeakyWorker):
                """LeakyWorker whose audit trail keeps only the newest entries."""

                def __init__(self, max_audit: int = 100) -> None:
                    raise NotImplementedError("Lab 3.1: implement BoundedWorker")
            '''
        ),
        md(
            """
            Run the checks. The growth checks compare the leaky and bounded workers with each
            other, not with fixed byte counts.
            """
        ),
        code(
            '''
            def worker_workload(worker: LeakyWorker) -> Callable[[], None]:
                """A workload that sends 2 000 requests to worker."""
                request_ids = itertools.count()

                def run_batch() -> None:
                    for _ in range(2_000):
                        worker.handle(next(request_ids))

                return run_batch


            def leaky_line_found() -> bool:
                line_text, _size = top_growth_line(worker_workload(LeakyWorker()))
                return "self.audit_trail.append" in line_text


            def leaky_growth_is_large() -> bool:
                _line, size_diff = top_growth_line(worker_workload(LeakyWorker()))
                return size_diff > 500_000


            def tracing_left_as_found() -> bool:
                top_growth_line(worker_workload(LeakyWorker()), repeat=1)
                return tracemalloc.is_tracing()


            def bounded_keeps_newest() -> tuple[int, str, int]:
                worker = BoundedWorker(max_audit=100)
                for request_id in range(5_000):
                    worker.handle(request_id)
                return len(worker.audit_trail), worker.audit_trail[-1].split(":")[0], worker.processed_count


            def bounded_growth_is_small() -> bool:
                _line, leaky_diff = top_growth_line(worker_workload(LeakyWorker()))
                _line, bounded_diff = top_growth_line(worker_workload(BoundedWorker()))
                return bounded_diff * 10 < leaky_diff


            run_checks(
                [
                    ("finds the leaking line", leaky_line_found, True),
                    ("growth over 500 kB for 6 000 requests", leaky_growth_is_large, True),
                    ("tracemalloc stopped again", tracing_left_as_found, False),
                    ("bounded audit trail", bounded_keeps_newest, (100, "4999", 5_000)),
                    ("bounded worker grows 10x less", bounded_growth_is_small, True),
                ]
            )
            '''
        ),
    ]


def _recap_cells() -> list[NotebookNode]:
    """Recap for Unit 3.1."""
    return [
        md(
            """
            ### Recap — Unit 3.1

            | Concept | One-line takeaway | JS equivalent |
            | --- | --- | --- |
            | Memory model | Frames hold pointer-sized references to objects on a private heap | Same idea, minus V8's unboxed Smis |
            | Object header | `ob_refcnt` + `ob_type` (+ `ob_size`), GC header before containers | Hidden-class pointer + fields |
            | Reference counting | Freed the moment the count hits 0; `getrefcount` is approximate (+1, borrowing in 3.14+) | — (tracing only) |
            | Immortal objects | `None`, small ints, interned literals never change count (3.12+) | Read-only space roots |
            | Free-threaded refcounting | Biased (owner thread vs shared) + deferred counts, mimalloc | — |
            | Cyclic GC | Finds groups referenced only from inside; generations; `gc.freeze` before fork | The whole GC |
            | Finalizers | `__del__` runs once, swallows errors, can resurrect; prefer `with` + `weakref.finalize` | `FinalizationRegistry` (non-deterministic) |
            | Weak references | `ref`, `WeakValueDictionary`, `WeakKeyDictionary`, `WeakSet`, `WeakMethod` | `WeakRef`, `WeakMap`, `WeakSet` |
            | Allocator | pymalloc arenas → pools → blocks for ≤ 512 B; RSS stays while any block lives | Heap spaces, compaction |
            | Free lists and caches | Reused memory, small ints, singletons, interning; `id()` is reused | — |
            | Measuring | `getsizeof` is shallow; `tracemalloc` diffs; RSS for native memory; memray | DevTools heap snapshots |
            | Leaks | Something reachable you forgot: caches, `lru_cache` on methods, closures, tracebacks, listeners, C code | Detached DOM nodes, listeners, closures |

            **Further reading**

            - [`gc`](https://docs.python.org/3/library/gc.html),
              [`weakref`](https://docs.python.org/3/library/weakref.html),
              [`tracemalloc`](https://docs.python.org/3/library/tracemalloc.html),
              [`sys.getsizeof`](https://docs.python.org/3/library/sys.html#sys.getsizeof),
              [`sys._is_immortal`](https://docs.python.org/3/library/sys.html#sys._is_immortal)
            - [Memory management (C API)](https://docs.python.org/3/c-api/memory.html),
              [Python support for free threading](https://docs.python.org/3/howto/free-threading-python.html),
              [Garbage collector design (CPython internals)](https://github.com/python/cpython/blob/main/InternalDocs/garbage_collector.md)
            - [PEP 442 — Safe object finalization](https://peps.python.org/pep-0442/),
              [PEP 445 — APIs to customize memory allocators](https://peps.python.org/pep-0445/),
              [PEP 454 — tracemalloc](https://peps.python.org/pep-0454/),
              [PEP 683 — Immortal objects](https://peps.python.org/pep-0683/),
              [PEP 703 — Making the GIL optional](https://peps.python.org/pep-0703/),
              [PEP 779 — Supported status for free-threaded Python](https://peps.python.org/pep-0779/)
            """
        ),
    ]


def cells() -> list[NotebookNode]:
    """Return the cells for Unit 3.1 and Lab 3.1."""
    return [
        *_overview_cells(),
        *_memory_model_cells(),
        *_object_layout_cells(),
        *_refcount_cells(),
        *_immortal_cells(),
        *_free_threaded_cells(),
        *_cyclic_gc_cells(),
        *_finalizer_cells(),
        *_weakref_cells(),
        *_allocator_cells(),
        *_free_list_cells(),
        *_measuring_cells(),
        *_leak_cells(),
        *_js_bridge_cells(),
        *_lab_size_refcount_cycle_cells(),
        *_lab_cache_emitter_worker_cells(),
        *_recap_cells(),
    ]
