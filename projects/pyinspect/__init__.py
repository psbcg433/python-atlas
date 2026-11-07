"""pyinspect: a small CPython internals toolkit (Phase 3 project).

Run it with ``python -m pyinspect`` from the ``projects/`` folder:

- ``memory MODULE:FUNCTION``: top allocating lines of a callable (tracemalloc),
- ``scan PATH...``: AST-based code scanner,
- ``imports MODULE``: import-time report (``python -X importtime``).

The same features are importable as functions. The re-exports below are lazy imports
(Python 3.15, Unit 3.3.12): ``import pyinspect`` stays cheap, and each submodule is loaded the
first time one of its names is used.
"""

lazy from pyinspect.importtime import (
    ImportTiming,
    format_import_report,
    import_subtree,
    measure_import,
    parse_importtime,
)
lazy from pyinspect.memory import (
    AllocationSite,
    MemoryReport,
    format_memory_report,
    profile_allocations,
)
lazy from pyinspect.scanner import RULES, Finding, format_findings, scan_paths, scan_source

__version__ = "0.1.0"

__all__ = [
    "RULES",
    "AllocationSite",
    "Finding",
    "ImportTiming",
    "MemoryReport",
    "__version__",
    "format_findings",
    "format_import_report",
    "format_memory_report",
    "import_subtree",
    "measure_import",
    "parse_importtime",
    "profile_allocations",
    "scan_paths",
    "scan_source",
]
