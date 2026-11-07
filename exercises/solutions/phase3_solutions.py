"""Reference solutions for Phase 3 labs.

Run from the repository root:

    uv run python exercises/solutions/phase3_solutions.py
"""

import ast
import csv
import dis
import functools
import gc
import importlib
import importlib.abc
import importlib.machinery
import importlib.resources
import importlib.resources.abc
import importlib.util
import inspect
import io
import itertools
import json
import linecache
import operator
import os
import pkgutil
import platform
import subprocess
import sys
import sysconfig
import tempfile
import textwrap
import tracemalloc
import types
import weakref
import zipfile
from collections import Counter, deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

type TestCase = tuple[str, Callable[[], object], object]


def run_checks(test_cases: list[TestCase]) -> None:
    """Run (label, thunk, expected) cases and print PASS/FAIL for each. Never raises."""
    passed_count = 0
    for label, thunk, expected in test_cases:
        try:
            actual = thunk()
        except Exception as error:  # a check must never stop the script
            print(f"FAIL  {label}: raised {type(error).__name__}: {error}")
            continue
        if actual == expected:
            passed_count += 1
            print(f"PASS  {label}")
        else:
            print(f"FAIL  {label}: expected {expected!r}, got {actual!r}")
    print(f"{passed_count}/{len(test_cases)} checks passed")


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


# ---------------------------------------------------------------------------------------------
# Lab 3.1 — Memory management
# ---------------------------------------------------------------------------------------------

# Exercise 1 — deep_getsizeof

_NOT_DESCENDED = (type, types.FunctionType, types.BuiltinFunctionType, types.ModuleType)


def deep_getsizeof(obj: object) -> int:
    """Total size of obj and everything reachable from it, each object counted once."""
    seen_ids: set[int] = set()
    total_bytes = 0
    pending: list[object] = [obj]
    while pending:
        current = pending.pop()
        if id(current) in seen_ids:
            continue
        seen_ids.add(id(current))
        total_bytes += sys.getsizeof(current)
        if isinstance(current, _NOT_DESCENDED):
            continue
        if isinstance(current, dict):
            pending.extend(current.keys())
            pending.extend(current.values())
        elif isinstance(current, list | tuple | set | frozenset):
            pending.extend(current)
        instance_dict = getattr(current, "__dict__", None)
        if isinstance(instance_dict, dict):
            pending.append(instance_dict)
        for klass in type(current).__mro__:
            slot_names = vars(klass).get("__slots__", ())
            if isinstance(slot_names, str):
                slot_names = (slot_names,)
            for slot_name in slot_names:
                if slot_name in {"__dict__", "__weakref__"}:
                    continue
                try:
                    pending.append(getattr(current, slot_name))
                except AttributeError:  # slot declared but never set
                    pass
    return total_bytes


# Exercise 2 — predicted refcount changes


def predict_refcount_deltas() -> dict[str, int]:
    """Predicted change in sys.getrefcount(target) for each scenario."""
    return {
        "second name": 1,  # one more name
        "list append": 1,  # one list slot
        "dict key and value": 2,  # the key slot and the value slot
        "tuple twice": 2,  # two tuple slots
        "weak reference": 0,  # weak references are not counted
        "bind then del": 0,  # +1 then -1
    }


# Exercise 3 — a cycle is freed only by gc.collect


class CycleNode:
    """A node with an optional peer."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.peer: CycleNode | None = None


def _node_lifecycle(make_cycle: bool) -> tuple[bool, bool]:
    """(alive after del, alive after gc.collect) for two nodes, with or without a cycle."""
    was_enabled = gc.isenabled()
    gc.disable()
    try:
        first, second = CycleNode("first"), CycleNode("second")
        first.peer = second
        if make_cycle:
            second.peer = first
        probe = weakref.ref(first)
        del first, second
        alive_after_del = probe() is not None
        gc.collect()
        return alive_after_del, probe() is not None
    finally:
        if was_enabled:
            gc.enable()


def cycle_lifecycle() -> tuple[bool, bool]:
    """(alive after del, alive after gc.collect) for a two-node cycle."""
    return _node_lifecycle(make_cycle=True)


def acyclic_lifecycle() -> tuple[bool, bool]:
    """The same measurements for two nodes without a cycle."""
    return _node_lifecycle(make_cycle=False)


# Exercise 4 — ImageCache


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
        self._loader = loader
        self._images: weakref.WeakValueDictionary[str, Image] = weakref.WeakValueDictionary()
        self.load_count = 0

    def get(self, path: str) -> Image:
        """The live cached image for path, or a freshly loaded one."""
        image = self._images.get(path)
        if image is None:
            image = self._loader(path)
            self.load_count += 1
            self._images[path] = image
        return image

    def __len__(self) -> int:
        return len(self._images)

    def __contains__(self, path: object) -> bool:
        return path in self._images


# Exercise 5 — EventEmitter


class StockAlertPanel:
    """A subscriber with a bound-method callback (given)."""

    def __init__(self) -> None:
        self.alerts: list[str] = []
        self.screen_buffer = bytearray(500_000)

    def on_low_stock(self, sku: str) -> None:
        self.alerts.append(sku)


class _StrongReference:
    """Same call interface as a weak reference, but keeps its callable alive."""

    def __init__(self, callback: Callable[..., object]) -> None:
        self._callback = callback

    def __call__(self) -> Callable[..., object]:
        return self._callback


class EventEmitter:
    """An emitter that does not keep bound-method subscribers alive."""

    def __init__(self) -> None:
        self._listeners: dict[str, list[Callable[[], Callable[..., object] | None]]] = {}

    def on(self, event: str, callback: Callable[..., object]) -> Callable[[], None]:
        """Subscribe; bound methods are held weakly. Returns an unsubscribe function."""
        if inspect.ismethod(callback):
            reference: Callable[[], Callable[..., object] | None] = weakref.WeakMethod(callback)
        else:
            reference = _StrongReference(callback)
        entries = self._listeners.setdefault(event, [])
        entries.append(reference)

        def unsubscribe() -> None:
            for index, entry in enumerate(entries):
                if entry is reference:
                    del entries[index]
                    return

        return unsubscribe

    def _live_callbacks(self, event: str) -> list[Callable[..., object]]:
        """Resolve the references for event, dropping dead ones."""
        entries = self._listeners.get(event, [])
        live: list[Callable[..., object]] = []
        for entry in list(entries):
            callback = entry()
            if callback is None:
                entries.remove(entry)
            else:
                live.append(callback)
        return live

    def emit(self, event: str, *args: object) -> int:
        """Call every live listener in subscription order; return how many were called."""
        live = self._live_callbacks(event)
        for callback in live:
            callback(*args)
        return len(live)

    def listener_count(self, event: str) -> int:
        """Number of live listeners for event."""
        return len(self._live_callbacks(event))


# Exercise 6 — diagnose a leaking worker


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
    started_here = not tracemalloc.is_tracing()
    if started_here:
        tracemalloc.start()
    ignore_tracemalloc = [tracemalloc.Filter(False, tracemalloc.__file__)]
    try:
        workload()  # warm-up: one-time allocations are not leaks
        before = tracemalloc.take_snapshot().filter_traces(ignore_tracemalloc)
        for _ in range(repeat):
            workload()
        after = tracemalloc.take_snapshot().filter_traces(ignore_tracemalloc)
    finally:
        if started_here:
            tracemalloc.stop()
    top = max(after.compare_to(before, "lineno"), key=lambda stat: stat.size_diff)
    frame = top.traceback[0]
    return linecache.getline(frame.filename, frame.lineno).strip(), top.size_diff


class BoundedWorker(LeakyWorker):
    """LeakyWorker whose audit trail keeps only the newest entries."""

    def __init__(self, max_audit: int = 100) -> None:
        super().__init__()
        self.audit_trail: deque[str] = deque(maxlen=max_audit)  # type: ignore[assignment]


def check_lab_3_1() -> None:
    """Run the same checks as the Lab 3.1 check cells in the notebook."""
    print(f"[{interpreter_label()}]")
    print("Exercise 1 — deep_getsizeof")

    class StockLine:
        def __init__(self, sku: str, quantity: int) -> None:
            self.sku = sku
            self.quantity = quantity

    class SlottedStockLine:
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
            sys.getsizeof(mapping)
            + sys.getsizeof(key_text)
            + sys.getsizeof(value_list)
            + sys.getsizeof(value_list[0])
        )
        return deep_getsizeof(mapping) == expected

    def check_self_referencing_list() -> bool:
        looped: list[object] = [10_002]
        looped.append(looped)
        return deep_getsizeof(looped) == sys.getsizeof(looped) + sys.getsizeof(looped[0])

    def check_instance_dict() -> bool:
        line = StockLine("TEA-" + "01", 10_003)
        total = deep_getsizeof(line)
        expected = (
            sys.getsizeof(line)
            + sys.getsizeof(vars(line))
            + sys.getsizeof("sku")
            + sys.getsizeof("quantity")
            + sys.getsizeof(line.sku)
            + sys.getsizeof(line.quantity)
        )
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
            (
                "tuple of sets",
                lambda: deep_getsizeof(({1}, {1})) > sys.getsizeof(({1}, {1})),
                True,
            ),
        ]
    )

    print("Exercise 2 — predict six reference counts")

    class RefcountTarget:
        pass

    def measure_refcount_deltas() -> dict[str, int]:
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
        return predict_refcount_deltas()[scenario]

    measured_deltas = measure_refcount_deltas()
    run_checks(
        [
            (
                "all six keys answered",
                lambda: sorted(predict_refcount_deltas()),
                sorted(measured_deltas),
            )
        ]
        + [
            (
                f"{scenario}: measured {delta:+d}",
                functools.partial(predicted_delta, scenario),
                delta,
            )
            for scenario, delta in measured_deltas.items()
        ]
    )

    print("Exercise 3 — a cycle is freed only by gc.collect")

    def set_collector(enabled: bool) -> None:
        if enabled:
            gc.enable()
        else:
            gc.disable()

    def state_restored_after(function: Callable[[], object], start_enabled: bool) -> bool:
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
            (
                "collector stays disabled",
                lambda: state_restored_after(cycle_lifecycle, False),
                True,
            ),
        ]
    )

    print("Exercise 4 — ImageCache")

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
        cache.get("logo.png")
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
        names_cached = all(name in cache for name in ("a.png", "b.png", "c.png"))
        return len(cache), names_cached and len(kept) == 3

    run_checks(
        [
            ("same object while alive, one load", cache_reuses_live_image, (True, 1)),
            ("entry vanishes when the image dies", cache_forgets_dead_image, (0, False, 1)),
            ("reloads after the image died", cache_reloads_after_death, 2),
            ("cache does not keep images alive", cache_does_not_keep_alive, True),
            ("len counts only live entries", cache_counts_live_entries, (3, True)),
        ]
    )

    print("Exercise 5 — EventEmitter")

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
        return (
            panel_ref() is None,
            emitter.listener_count("low_stock"),
            emitter.emit("low_stock", "X"),
        )

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

    print("Exercise 6 — diagnose a leaking worker with tracemalloc")

    def worker_workload(worker: LeakyWorker) -> Callable[[], None]:
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
        return (
            len(worker.audit_trail),
            worker.audit_trail[-1].split(":")[0],
            worker.processed_count,
        )

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


# ---------------------------------------------------------------------------------------------
# Lab 3.2 — Bytecode and the interpreter
# ---------------------------------------------------------------------------------------------

# Exercise 1 — annotate taxi_fare's dis output with stack states


def taxi_fare(base_fare: float, distance_km: float, rate_per_km: float, discount: float) -> float:
    """The function to annotate (given)."""
    return base_fare + distance_km * rate_per_km - discount


def annotate_stack() -> list[tuple[str, list[str]]]:
    """(opname, stack after) for each instruction of taxi_fare except RESUME (CPython 3.15)."""
    return [
        ("LOAD_FAST_BORROW_LOAD_FAST_BORROW", ["base_fare", "distance_km"]),
        ("LOAD_FAST_BORROW", ["base_fare", "distance_km", "rate_per_km"]),
        ("BINARY_OP", ["base_fare", "distance_km * rate_per_km"]),
        ("BINARY_OP", ["base_fare + distance_km * rate_per_km"]),
        ("LOAD_FAST_BORROW", ["base_fare + distance_km * rate_per_km", "discount"]),
        ("BINARY_OP", ["base_fare + distance_km * rate_per_km - discount"]),
        ("RETURN_VALUE", []),
    ]


# Exercise 2 — count_opcodes


def count_opcodes(func: Callable[..., object]) -> Counter[str]:
    """Opname counts for func and all nested code objects."""
    counts: Counter[str] = Counter()
    pending: list[types.CodeType] = [func.__code__]
    while pending:
        code_object = pending.pop()
        counts.update(instruction.opname for instruction in dis.get_instructions(code_object))
        pending.extend(c for c in code_object.co_consts if isinstance(c, types.CodeType))
    return counts


# Exercise 3 — AST lint rule

_MUTABLE_DISPLAYS = (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp)
_MUTABLE_CONSTRUCTORS = {"list", "dict", "set"}


def _is_mutable_default(node: ast.expr) -> bool:
    """A list/dict/set display or comprehension, or a call to list(), dict() or set()."""
    if isinstance(node, _MUTABLE_DISPLAYS):
        return True
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in _MUTABLE_CONSTRUCTORS
    )


def lint_source(source: str) -> list[tuple[int, str]]:
    """(line, code) findings for mutable defaults (B006) and bare except (E722)."""
    findings: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            keyword_defaults = [default for default in node.args.kw_defaults if default is not None]
            for default in [*node.args.defaults, *keyword_defaults]:
                if _is_mutable_default(default):
                    findings.append((default.lineno, "B006"))
        elif isinstance(node, ast.ExceptHandler) and node.type is None:
            findings.append((node.lineno, "E722"))
    return sorted(findings)


# Exercise 4 — print -> logger.info


class PrintToLogger(ast.NodeTransformer):
    """Replace print(...) calls with logger.info(...)."""

    def visit_Call(self, node: ast.Call) -> ast.AST:
        self.generic_visit(node)  # rewrite prints nested in the arguments first
        is_print = isinstance(node.func, ast.Name) and node.func.id == "print"
        if not is_print or node.keywords or any(isinstance(a, ast.Starred) for a in node.args):
            return node
        template = " ".join(["%s"] * len(node.args))
        logger_info = ast.Attribute(
            value=ast.Name("logger", ast.Load()), attr="info", ctx=ast.Load()
        )
        replacement = ast.Call(
            func=logger_info, args=[ast.Constant(template), *node.args], keywords=[]
        )
        return ast.copy_location(replacement, node)


def rewrite_prints(source: str) -> str:
    """Source with eligible print calls turned into logger.info calls."""
    tree = PrintToLogger().visit(ast.parse(source))
    return ast.unparse(ast.fix_missing_locations(tree))


# Exercise 5 — safe arithmetic evaluator

_BINARY_OPERATORS: dict[type[ast.operator], Callable[[float, float], float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPERATORS: dict[type[ast.unaryop], Callable[[float], float]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}
MAX_EXPONENT = 100


def safe_eval(expression: str, variables: dict[str, float] | None = None) -> float:
    """Evaluate an arithmetic expression safely."""
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError:
        raise ValueError("invalid expression") from None
    names = variables or {}

    def evaluate(node: ast.AST) -> float:
        match node:
            case ast.Expression(body=body):
                return evaluate(body)
            case ast.Constant(value=value):
                if isinstance(value, bool) or not isinstance(value, int | float):
                    raise ValueError(f"unsupported constant: {type(value).__name__}")
                return value
            case ast.Name(id=name):
                if name not in names:
                    raise ValueError(f"unknown name: {name}")
                return names[name]
            case ast.BinOp(left=left, op=binary_op, right=right) if (
                type(binary_op) in _BINARY_OPERATORS
            ):
                left_value, right_value = evaluate(left), evaluate(right)
                if isinstance(binary_op, ast.Pow) and abs(right_value) > MAX_EXPONENT:
                    raise ValueError("exponent too large")
                return _BINARY_OPERATORS[type(binary_op)](left_value, right_value)
            case ast.UnaryOp(op=unary_op, operand=operand) if type(unary_op) in _UNARY_OPERATORS:
                return _UNARY_OPERATORS[type(unary_op)](evaluate(operand))
            case _:
                raise ValueError(f"unsupported expression: {type(node).__name__}")

    return evaluate(tree)


# Exercise 6 — observe specialization and deoptimization


def binary_op_forms(
    func: Callable[..., object], argument_sets: list[tuple[object, ...]], *, warmups: int = 1000
) -> list[str]:
    """The adaptive BINARY_OP form after warming func with each argument set in turn."""
    forms: list[str] = []
    for arguments in argument_sets:
        for _ in range(warmups):
            func(*arguments)
        forms.append(
            next(
                instruction.opname
                for instruction in dis.get_instructions(func, adaptive=True)
                if instruction.opname.startswith("BINARY_OP")
            )
        )
    return forms


# Exercise 7 — code-quality scanner


def scan_folder(folder: Path) -> dict[str, list[tuple[int, str]]]:
    """Lint findings for every Python file under folder."""
    results: dict[str, list[tuple[int, str]]] = {}
    for path in sorted(folder.rglob("*.py")):
        relative = path.relative_to(folder)
        if any(part == "__pycache__" or part.startswith(".") for part in relative.parts[:-1]):
            continue
        try:
            findings = lint_source(path.read_text(encoding="utf-8"))
        except SyntaxError as error:
            findings = [(error.lineno or 0, "E999")]
        if findings:
            results[relative.as_posix()] = findings
    return dict(sorted(results.items()))


def check_lab_3_2() -> None:
    """Run the same checks as the Lab 3.2 check cells in the notebook."""
    print(f"[{interpreter_label()}]")
    print("Exercise 1 — annotate dis output with stack states")

    def live_instructions(function: Callable[..., object]) -> list[dis.Instruction]:
        return [ins for ins in dis.get_instructions(function) if ins.opname != "RESUME"]

    def expected_depths(function: Callable[..., object]) -> list[int]:
        depth, depths = 0, []
        for instruction in live_instructions(function):
            if instruction.opname == "RETURN_VALUE":
                depth -= 1
            elif instruction.arg is None:
                depth += dis.stack_effect(instruction.opcode)
            else:
                depth += dis.stack_effect(instruction.opcode, instruction.arg)
            depths.append(depth)
        return depths

    run_checks(
        [
            (
                "opnames in order",
                lambda: [name for name, _ in annotate_stack()],
                [ins.opname for ins in live_instructions(taxi_fare)],
            ),
            (
                "stack depths",
                lambda: [len(stack) for _, stack in annotate_stack()],
                expected_depths(taxi_fare),
            ),
            (
                "entries are strings",
                lambda: all(
                    isinstance(item, str) for _, stack in annotate_stack() for item in stack
                ),
                True,
            ),
            ("empty after RETURN_VALUE", lambda: annotate_stack()[-1], ("RETURN_VALUE", [])),
        ]
    )

    print("Exercise 2 — count_opcodes")

    def three_calls(values: list[int]) -> int:
        print(values)
        print(values)
        return len(values)

    def outer_with_inner() -> Callable[[], int]:
        def inner() -> int:
            return 1

        return inner

    def with_generator(values: list[int]) -> int:
        return sum(value * 2 for value in values)

    def total_instructions(code_object: types.CodeType) -> int:
        nested = [c for c in code_object.co_consts if isinstance(c, types.CodeType)]
        own = len(list(dis.get_instructions(code_object)))
        return own + sum(total_instructions(c) for c in nested)

    run_checks(
        [
            ("returns a Counter", lambda: type(count_opcodes(three_calls)).__name__, "Counter"),
            (
                "flat total",
                lambda: count_opcodes(three_calls).total(),
                len(list(dis.get_instructions(three_calls))),
            ),
            ("three CALLs", lambda: count_opcodes(three_calls)["CALL"], 3),
            (
                "inner function counted",
                lambda: (
                    count_opcodes(outer_with_inner)["RETURN_VALUE"]
                    > [ins.opname for ins in dis.get_instructions(outer_with_inner)].count(
                        "RETURN_VALUE"
                    )
                ),
                True,
            ),
            (
                "generator expression counted",
                lambda: count_opcodes(with_generator).total(),
                total_instructions(with_generator.__code__),
            ),
            ("no CACHE entries", lambda: "CACHE" in count_opcodes(with_generator), False),
        ]
    )

    print("Exercise 3 — AST lint rule")
    lint_sample = textwrap.dedent(
        """
        def add_item(item, basket=[]):
            basket.append(item)
            return basket

        async def fetch(url, *, headers={}, retries=3, tags=set()):
            try:
                return url
            except:
                return None

        def fine(value=None, labels=(), factor=lambda x: x):
            try:
                return value
            except ValueError:
                return None

        def comprehension_default(cache={key: 0 for key in "ab"}):
            return cache
        """
    )
    method_source = (
        "class A:\n    def m(self):\n        try:\n            pass\n"
        "        except:\n            pass\n"
    )
    run_checks(
        [
            (
                "sample findings",
                lambda: lint_source(lint_sample),
                [(2, "B006"), (6, "B006"), (6, "B006"), (9, "E722"), (18, "B006")],
            ),
            ("clean code", lambda: lint_source("def f(x=None):\n    return x\n"), []),
            (
                "list() call default",
                lambda: lint_source("def f(x=list()):\n    pass\n"),
                [(1, "B006")],
            ),
            ("bare except in a method", lambda: lint_source(method_source), [(5, "E722")]),
        ]
    )

    print("Exercise 4 — print -> logger.info")
    run_checks(
        [
            ("one argument", lambda: rewrite_prints("print(total)"), "logger.info('%s', total)"),
            (
                "two arguments",
                lambda: rewrite_prints("print('total', total)"),
                "logger.info('%s %s', 'total', total)",
            ),
            ("no arguments", lambda: rewrite_prints("print()"), "logger.info('')"),
            (
                "keywords untouched",
                lambda: rewrite_prints("print(x, file=sys.stderr)"),
                "print(x, file=sys.stderr)",
            ),
            ("starred untouched", lambda: rewrite_prints("print(*rows)"), "print(*rows)"),
            ("other calls untouched", lambda: rewrite_prints("pprint(data)"), "pprint(data)"),
            (
                "nested in a function",
                lambda: rewrite_prints("def report(n):\n    print('rows', n)\n    return n"),
                "def report(n):\n    logger.info('%s %s', 'rows', n)\n    return n",
            ),
            (
                "result compiles",
                lambda: bool(compile(rewrite_prints("print(1, 2)"), "<t>", "exec")),
                True,
            ),
        ]
    )

    print("Exercise 5 — safe arithmetic evaluator")
    prices = {"price": 200.0, "rate": 0.25, "quantity": 3}
    run_checks(
        [
            ("precedence", lambda: safe_eval("2 + 3 * 4"), 14),
            ("parentheses", lambda: safe_eval("(2 + 3) * 4"), 20),
            ("unary minus and power", lambda: safe_eval("-x ** 2", {"x": 3}), -9),
            ("variables", lambda: safe_eval("price * quantity * (1 + rate)", prices), 750.0),
            ("floor division and modulo", lambda: safe_eval("17 // 5 + 17 % 5"), 5),
            (
                "function call refused",
                lambda: raised_message(lambda: safe_eval("__import__('os')")),
                "ValueError: unsupported expression: Call",
            ),
            (
                "attribute refused",
                lambda: raised_message(lambda: safe_eval("price.real", prices)),
                "ValueError: unsupported expression: Attribute",
            ),
            (
                "huge exponent refused",
                lambda: raised_message(lambda: safe_eval("2 ** 1000")),
                "ValueError: exponent too large",
            ),
            (
                "string refused",
                lambda: raised_message(lambda: safe_eval("'a' * 3")),
                "ValueError: unsupported constant: str",
            ),
            (
                "bool refused",
                lambda: raised_message(lambda: safe_eval("True + 1")),
                "ValueError: unsupported constant: bool",
            ),
            (
                "unknown name",
                lambda: raised_message(lambda: safe_eval("tax * 2")),
                "ValueError: unknown name: tax",
            ),
            (
                "invalid syntax",
                lambda: raised_message(lambda: safe_eval("2 +")),
                "ValueError: invalid expression",
            ),
            (
                "division by zero propagates",
                lambda: raised_error_name(lambda: safe_eval("1 / 0")),
                "ZeroDivisionError",
            ),
        ]
    )

    print("Exercise 6 — observe specialization and deoptimization")

    def make_adder() -> Callable[[object, object], object]:
        namespace: dict[str, object] = {}
        exec("def add(left, right):\n    return left + right", namespace)
        return namespace["add"]

    def type_shifts() -> list[str]:
        return binary_op_forms(make_adder(), [(1, 2), (1.5, 2.5), ("a", "b")])

    print(f"{type_shifts()=}")
    run_checks(
        [
            (
                "cold function is generic",
                lambda: binary_op_forms(make_adder(), [(1, 2)], warmups=0),
                ["BINARY_OP"],
            ),
            ("ints specialize", lambda: "INT" in type_shifts()[0], True),
            ("then floats", lambda: "FLOAT" in type_shifts()[1], True),
            ("then strings", lambda: "UNICODE" in type_shifts()[2], True),
            (
                "always a BINARY_OP form",
                lambda: all(name.startswith("BINARY_OP") for name in type_shifts()),
                True,
            ),
        ]
    )

    print("Exercise 7 — code-quality scanner")

    def scan_sample_project() -> dict[str, list[tuple[int, str]]]:
        files = {
            "app.py": "def handler(event, seen=[]):\n    return seen\n",
            "pkg/__init__.py": "",
            "pkg/models.py": "def load():\n    try:\n        pass\n    except:\n        pass\n",
            "pkg/clean.py": "def ok(value=None):\n    return value\n",
            "broken.py": "def broken(:\n    pass\n",
            ".venv/lib/site.py": "def bad(x=[]):\n    pass\n",
            "pkg/__pycache__/junk.py": "def bad(x={}):\n    pass\n",
            "notes.txt": "def not_python(x=[]): pass\n",
        }
        with tempfile.TemporaryDirectory() as folder:
            for relative, text in files.items():
                path = Path(folder) / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
            return scan_folder(Path(folder))

    run_checks(
        [
            (
                "findings per file",
                scan_sample_project,
                {
                    "app.py": [(1, "B006")],
                    "broken.py": [(1, "E999")],
                    "pkg/models.py": [(4, "E722")],
                },
            ),
            (
                "keys sorted",
                lambda: list(scan_sample_project()),
                ["app.py", "broken.py", "pkg/models.py"],
            ),
        ]
    )


# ---------------------------------------------------------------------------------------------
# Lab 3.3 — Modules, packages and the import system
# ---------------------------------------------------------------------------------------------

CHILD_ENV = {**os.environ, "PYTHON_COLORS": "0"}


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
    """Write files to a temporary folder (or zip), put it first on sys.path, undo on exit."""
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


def run_python(*arguments: str, cwd: Path | None = None) -> str:
    """Run this interpreter in a child process; return stdout and stderr, stripped."""
    completed = subprocess.run(
        [sys.executable, *arguments],
        capture_output=True,
        text=True,
        cwd=cwd,
        env=CHILD_ENV,
        timeout=120,
    )
    return (completed.stdout + completed.stderr).strip()


@contextmanager
def child_project(files: dict[str, str]) -> Iterator[Path]:
    """Write files to a temporary folder for a child process (the notebook uses _scratch)."""
    with tempfile.TemporaryDirectory(prefix="lab33_") as folder:
        root = Path(folder)
        for relative_path, text in files.items():
            target = root / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(textwrap.dedent(text).lstrip("\n"))
        yield root


def run_script(root: Path, script: str, *arguments: str) -> str:
    """Save script as root/main.py and run it in a child interpreter from root."""
    (root / "main.py").write_text(textwrap.dedent(script).lstrip("\n"))
    return run_python("main.py", *arguments, cwd=root)


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


# Exercise 1 — the shop package


def shop_package_files() -> dict[str, str]:
    """Relative path -> source for the shop package."""
    return {
        "shop/__init__.py": """
            from .cart import Cart
            from .models import Product

            __all__ = ["Cart", "Product"]
            __version__ = "1.0"
            """,
        "shop/models.py": """
            from dataclasses import dataclass
            from decimal import Decimal


            @dataclass(frozen=True)
            class Product:
                name: str
                price: Decimal
            """,
        "shop/cart.py": """
            from decimal import Decimal

            from .models import Product


            class Cart:
                def __init__(self):
                    self._lines: list[tuple[Product, int]] = []

                def add(self, product: Product, quantity: int = 1) -> None:
                    self._lines.append((product, quantity))

                def total(self) -> Decimal:
                    line_totals = (product.price * quantity for product, quantity in self._lines)
                    return sum(line_totals, Decimal("0"))
            """,
        "shop/payments/__init__.py": """
            from decimal import Decimal


            def charge(amount: Decimal) -> str:
                return f"charged INR {amount:.2f}"
            """,
        "shop/__main__.py": """
            from . import __version__

            print(f"shop {__version__}")
            """,
    }


# Exercise 2 — circular imports fixed three ways

_ORDER_CLASS = """
    class Order:
        def __init__(self, order_id, customer):
            if not isinstance(customer, {customer_class}):
                raise TypeError("customer must be a Customer")
            self.order_id = order_id
            self.customer = customer

        def describe(self):
            return f"order {{self.order_id}} for {{self.customer.name}}"
    """
_CUSTOMER_CLASS = """
    class Customer:
        def __init__(self, name):
            self.name = name
            self.orders = []

        def place_order(self, order_id):{local_import}
            order = {order_class}(order_id, self)
            self.orders.append(order)
            return order
    """


def fix_with_module_imports() -> dict[str, str]:
    """Fix 1: import modules, not names; look classes up at call time."""
    return {
        "orders.py": "import customers\n"
        + textwrap.dedent(_ORDER_CLASS.format(customer_class="customers.Customer")),
        "customers.py": "import orders\n"
        + textwrap.dedent(_CUSTOMER_CLASS.format(local_import="", order_class="orders.Order")),
    }


def fix_with_local_import() -> dict[str, str]:
    """Fix 2: orders keeps its top-level import; customers imports Order inside the method."""
    return {
        "orders.py": "from customers import Customer\n"
        + textwrap.dedent(_ORDER_CLASS.format(customer_class="Customer")),
        "customers.py": textwrap.dedent(
            _CUSTOMER_CLASS.format(
                local_import="\n            from orders import Order\n", order_class="Order"
            )
        ),
    }


def fix_with_third_module() -> dict[str, str]:
    """Fix 3: both classes live in models.py; orders and customers re-export them."""
    return {
        "models.py": textwrap.dedent(_ORDER_CLASS.format(customer_class="Customer"))
        + textwrap.dedent(_CUSTOMER_CLASS.format(local_import="", order_class="Order")),
        "orders.py": "from models import Order\n\n__all__ = ['Order']\n",
        "customers.py": "from models import Customer\n\n__all__ = ['Customer']\n",
    }


# Exercise 3 — plugin loader


def load_plugins(package_name: str) -> dict[str, Callable[..., object]]:
    """Discover plugin modules (PLUGIN_NAME + run) in a package."""
    package = importlib.import_module(package_name)
    plugins: dict[str, Callable[..., object]] = {}
    for module_info in pkgutil.iter_modules(package.__path__):
        if module_info.ispkg or module_info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{package_name}.{module_info.name}")
        plugin_name = getattr(module, "PLUGIN_NAME", None)
        run = getattr(module, "run", None)
        if not isinstance(plugin_name, str) or not callable(run):
            continue
        if plugin_name in plugins:
            raise ValueError(f"duplicate plugin name: {plugin_name}")
        plugins[plugin_name] = run
    return dict(sorted(plugins.items()))


# Exercise 4 — DictImporter


class DictImporter(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Serve modules from a dict of dotted name -> source code."""

    def __init__(self, sources: dict[str, str]) -> None:
        self.sources = dict(sources)

    def find_spec(
        self, fullname: str, path: object = None, target: object = None
    ) -> importlib.machinery.ModuleSpec | None:
        if fullname not in self.sources:
            return None
        is_package = any(name.startswith(fullname + ".") for name in self.sources)
        return importlib.util.spec_from_loader(
            fullname, self, origin="<dict>", is_package=is_package
        )

    def create_module(self, spec: importlib.machinery.ModuleSpec) -> None:
        return None

    def exec_module(self, module: types.ModuleType) -> None:
        name = module.__spec__.name
        exec(compile(self.sources[name], f"<dict:{name}>", "exec"), module.__dict__)


# Exercise 5 — importlib.resources


def _data_folder(package: str) -> importlib.resources.abc.Traversable:
    return importlib.resources.files(package).joinpath("data")


def load_tax_rates(package: str) -> dict[str, float]:
    """data/tax_rates.json from the package."""
    return json.loads(_data_folder(package).joinpath("tax_rates.json").read_text(encoding="utf-8"))


def product_names(package: str) -> list[str]:
    """The name column of data/products.csv, in file order."""
    text = _data_folder(package).joinpath("products.csv").read_text(encoding="utf-8")
    return [row["name"] for row in csv.DictReader(io.StringIO(text))]


def data_file_names(package: str) -> list[str]:
    """Sorted file names in data/."""
    return sorted(item.name for item in _data_folder(package).iterdir() if item.is_file())


# Exercise 6 — lazy imports for a CLI


def parse_importtime(stderr_text: str) -> dict[str, int]:
    """{module: cumulative microseconds} from `python -X importtime` output."""
    timings: dict[str, int] = {}
    for line in stderr_text.splitlines():
        if not line.startswith("import time:"):
            continue
        fields = line.removeprefix("import time:").split("|")
        if len(fields) != 3 or not fields[1].strip().isdigit():
            continue  # the header line
        timings[fields[2].strip()] = int(fields[1])
    return timings


def make_lazy(source: str) -> str:
    """Turn module-level imports into lazy imports (not __future__ or star imports)."""
    lines = source.splitlines(keepends=True)
    for node in ast.parse(source).body:
        eligible = isinstance(node, ast.Import) or (
            isinstance(node, ast.ImportFrom)
            and node.module != "__future__"
            and not any(alias.name == "*" for alias in node.names)
        )
        if eligible:
            lines[node.lineno - 1] = "lazy " + lines[node.lineno - 1]
    return "".join(lines)


def check_lab_3_3() -> None:
    """Run the same checks as the Lab 3.3 check cells in the notebook."""
    print("Exercise 1 — the shop package")
    shop_script = """
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
"""

    def shop_report() -> dict[str, object]:
        with child_project(shop_package_files()) as root:
            return child_json(run_script(root, shop_script))

    def shop_run_as_module() -> str:
        with child_project(shop_package_files()) as root:
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

    print("Exercise 2 — circular imports fixed three ways")
    orders_script = """
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
        outcomes: list[str] = []
        for first_import in ("customers", "orders"):
            with child_project(in_src(files)) as root:
                outcomes.extend(child_json(run_script(root, orders_script, first_import)))
        return outcomes

    def top_level_imports(source: str) -> list[str]:
        tree = ast.parse(textwrap.dedent(source))
        return [
            alias.name for node in tree.body if isinstance(node, ast.Import) for alias in node.names
        ]

    def has_function_level_import(files: dict[str, str]) -> bool:
        for source in files.values():
            for node in ast.walk(ast.parse(textwrap.dedent(source))):
                if isinstance(node, ast.FunctionDef) and any(
                    isinstance(inner, ast.Import | ast.ImportFrom) for inner in ast.walk(node)
                ):
                    return True
        return False

    def uses_module_imports() -> tuple[bool, bool]:
        files = fix_with_module_imports()
        return (
            "customers" in top_level_imports(files["orders.py"]),
            "orders" in top_level_imports(files["customers.py"]),
        )

    expected_scenario = ["order 7 for Asha", "TypeError", "order 7 for Asha", "TypeError"]
    run_checks(
        [
            (
                "module imports: scenario",
                lambda: orders_scenario(fix_with_module_imports()),
                expected_scenario,
            ),
            ("module imports: uses `import`", uses_module_imports, (True, True)),
            (
                "local import: scenario",
                lambda: orders_scenario(fix_with_local_import()),
                expected_scenario,
            ),
            (
                "local import: inside a function",
                lambda: has_function_level_import(fix_with_local_import()),
                True,
            ),
            (
                "third module: scenario",
                lambda: orders_scenario(fix_with_third_module()),
                expected_scenario,
            ),
            ("third module: three files", lambda: len(fix_with_third_module()) >= 3, True),
        ]
    )

    print("Exercise 3 — plugin loader")
    exporter_files = {
        "exporters/__init__.py": "",
        "exporters/csv_exporter.py": """
            PLUGIN_NAME = "csv"

            def run(rows):
                return "\\n".join(",".join(str(value) for value in row.values()) for row in rows)
            """,
        "exporters/json_exporter.py": """
            import json

            PLUGIN_NAME = "json"

            def run(rows):
                return json.dumps(rows)
            """,
        "exporters/_shared.py": "PLUGIN_NAME = 'shared'\n\ndef run(rows):\n    return ''\n",
        "exporters/draft_exporter.py": "PLUGIN_NAME = 'draft'  # no run() yet\n",
        "exporters/legacy/__init__.py": "PLUGIN_NAME = 'legacy'\n\ndef run(rows):\n    return ''\n",
    }
    sample_rows = [{"sku": "TEA-01", "qty": 2}, {"sku": "RICE-5", "qty": 1}]

    def plugins_from(files: dict[str, str]) -> Callable[[], object]:
        def load() -> object:
            with temporary_modules(files):
                plugins = load_plugins("exporters")
                return list(plugins), plugins["csv"](sample_rows), plugins["json"](sample_rows[:1])

        return load

    duplicate_files = {
        **exporter_files,
        "exporters/csv_again.py": "PLUGIN_NAME = 'csv'\n\ndef run(rows):\n    return ''\n",
    }
    run_checks(
        [
            (
                "plugins, sorted, run",
                plugins_from(exporter_files),
                (["csv", "json"], "TEA-01,2\nRICE-5,1", '[{"sku": "TEA-01", "qty": 2}]'),
            ),
            (
                "duplicate name",
                lambda: raised_message(plugins_from(duplicate_files)),
                "ValueError: duplicate plugin name: csv",
            ),
        ]
    )

    print("Exercise 4 — DictImporter")
    in_memory_sources = {
        "greetings": "def hello(name):\n    return f'Namaste, {name}'\n",
        "toolbox": "from .strings import shout\n",
        "toolbox.strings": "def shout(text):\n    return text.upper() + '!'\n",
        "run_counter": "import builtins\n"
        "builtins.__dict__.setdefault('_run_counter_hits', []).append(1)",
    }

    @contextmanager
    def installed(importer: object) -> Iterator[object]:
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
            with installed(DictImporter(in_memory_sources)) as importer:
                return action(importer)

        return run

    def imports_once(importer: object) -> int:
        import builtins

        builtins.__dict__.pop("_run_counter_hits", None)
        importlib.import_module("run_counter")
        importlib.import_module("run_counter")
        return len(builtins.__dict__.pop("_run_counter_hits", []))

    def spec_facts(importer: object) -> tuple[str, bool]:
        module = importlib.import_module("greetings")
        return module.__spec__.origin, module.__loader__ is importer

    run_checks(
        [
            (
                "plain module",
                with_importer(lambda imp: importlib.import_module("greetings").hello("Asha")),
                "Namaste, Asha",
            ),
            ("spec origin and loader", with_importer(spec_facts), ("<dict>", True)),
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
                    lambda imp: raised_error_name(
                        lambda: importlib.import_module("not_in_the_dict")
                    )
                ),
                "ModuleNotFoundError",
            ),
            ("runs once", with_importer(imports_once), 1),
        ]
    )

    print("Exercise 5 — importlib.resources")
    catalog_files = {
        "catalog/__init__.py": "",
        "catalog/data/products.csv": "name,price\nGreen tea,120.50\nBasmati rice,80\nTurmeric,45\n",
        "catalog/data/tax_rates.json": '{"food": 0.05, "electronics": 0.18}',
    }

    def read_catalog(zipped: bool) -> Callable[[], object]:
        def read() -> object:
            with temporary_modules(catalog_files, zipped=zipped):
                return (
                    load_tax_rates("catalog"),
                    product_names("catalog"),
                    data_file_names("catalog"),
                )

        return read

    expected_catalog = (
        {"food": 0.05, "electronics": 0.18},
        ["Green tea", "Basmati rice", "Turmeric"],
        ["products.csv", "tax_rates.json"],
    )
    run_checks(
        [
            ("from a folder", read_catalog(zipped=False), expected_catalog),
            ("from a zip", read_catalog(zipped=True), expected_catalog),
        ]
    )

    print("Exercise 6 — lazy imports for a CLI")
    report_cli = textwrap.dedent(
        """
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
    )
    sample_importtime = textwrap.dedent(
        """
        import time: self [us] | cumulative | imported package
        import time:       120 |        120 |   _json
        import time:       850 |       1300 | json
        import time:        90 |         90 |     _decimal
        import time:       400 |        490 |   decimal
        garbage line
        """
    ).strip()

    def run_cli(source: str, *arguments: str) -> tuple[str, set[str]]:
        with tempfile.TemporaryDirectory() as folder:
            script = Path(folder) / "report.py"
            script.write_text(source)
            completed = subprocess.run(
                [sys.executable, "-X", "importtime", str(script), *arguments],
                capture_output=True,
                text=True,
                env=CHILD_ENV,
                timeout=60,
            )
        return completed.stdout.strip(), set(parse_importtime(completed.stderr))

    def startup_comparison() -> tuple[bool, bool, bool, bool]:
        eager_output, eager_modules = run_cli(report_cli, "--version")
        lazy_output, lazy_modules = run_cli(make_lazy(report_cli), "--version")
        counts = f"eager {len(eager_modules)}, lazy {len(lazy_modules)}"
        print(f"    modules loaded for --version: {counts}")
        return (
            eager_output == lazy_output == "report 2.0",
            "asyncio" in eager_modules,
            "asyncio" in lazy_modules,
            len(lazy_modules) * 2 < len(eager_modules),
        )

    keep_sample = (
        "from __future__ import annotations\nimport os\n\n"
        "def f():\n    import json\n\n"
        "try:\n    import tomllib\nexcept ImportError:\n    pass\n"
    )
    run_checks(
        [
            (
                "parse sample",
                lambda: parse_importtime(sample_importtime),
                {"_json": 120, "json": 1300, "_decimal": 90, "decimal": 490},
            ),
            (
                "make_lazy rewrites top-level imports",
                lambda: [line for line in make_lazy(report_cli).splitlines() if "import" in line][
                    :2
                ],
                ["lazy import asyncio", "lazy import email.parser"],
            ),
            (
                "make_lazy leaves the rest",
                lambda: make_lazy(keep_sample),
                keep_sample.replace("\nimport os", "\nlazy import os"),
            ),
            (
                "--version: same output, asyncio skipped, half the modules",
                startup_comparison,
                (True, True, False, True),
            ),
            (
                "total still works lazily",
                lambda: run_cli(make_lazy(report_cli), "total", "1.10", "2.20")[0],
                "3.30",
            ),
        ]
    )


if __name__ == "__main__":
    for lab_title, check_lab in [
        ("Lab 3.1", check_lab_3_1),
        ("Lab 3.2", check_lab_3_2),
        ("Lab 3.3", check_lab_3_3),
    ]:
        print(f"===== {lab_title} =====")
        check_lab()
