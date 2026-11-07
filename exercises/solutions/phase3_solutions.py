"""Reference solutions for Phase 3 labs.

Run from the repository root:

    uv run python exercises/solutions/phase3_solutions.py
"""

import ast
import dis
import functools
import gc
import inspect
import itertools
import linecache
import operator
import platform
import sys
import sysconfig
import tempfile
import textwrap
import tracemalloc
import types
import weakref
from collections import Counter, deque
from collections.abc import Callable
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


if __name__ == "__main__":
    for lab_title, check_lab in [
        ("Lab 3.1", check_lab_3_1),
        ("Lab 3.2", check_lab_3_2),
    ]:
        print(f"===== {lab_title} =====")
        check_lab()
