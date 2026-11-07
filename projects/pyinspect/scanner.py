"""An AST-based code scanner with a small, extensible rule set."""

import ast
import json
from collections.abc import Callable, Iterable, Iterator
from dataclasses import asdict, dataclass
from pathlib import Path

type RuleCheck = Callable[[ast.Module], Iterator[tuple[ast.AST, str]]]


@dataclass(frozen=True, slots=True, order=True)
class Finding:
    """One problem: where it is and which rule found it."""

    path: str
    line: int
    column: int
    code: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}:{self.column}: {self.code} {self.message}"


@dataclass(frozen=True, slots=True)
class Rule:
    """A registered rule: its code, a one-line description and the check function."""

    code: str
    description: str
    check: RuleCheck


RULES: dict[str, Rule] = {}


def rule(code: str, description: str) -> Callable[[RuleCheck], RuleCheck]:
    """Register a check function under a rule code."""

    def register(check: RuleCheck) -> RuleCheck:
        if code in RULES:
            raise ValueError(f"duplicate rule code: {code}")
        RULES[code] = Rule(code, description, check)
        return check

    return register


_MUTABLE_DISPLAYS = (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp)
_MUTABLE_CONSTRUCTORS = {"list", "dict", "set"}


def _is_mutable(node: ast.expr) -> bool:
    if isinstance(node, _MUTABLE_DISPLAYS):
        return True
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in _MUTABLE_CONSTRUCTORS
    )


@rule("B006", "mutable default argument")
def mutable_defaults(tree: ast.Module) -> Iterator[tuple[ast.AST, str]]:
    """Defaults are evaluated once, so a mutable default is shared by every call."""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            keyword_defaults = [default for default in node.args.kw_defaults if default is not None]
            for default in [*node.args.defaults, *keyword_defaults]:
                if _is_mutable(default):
                    yield default, f"mutable default argument in {node.name}()"


@rule("E722", "bare except")
def bare_except(tree: ast.Module) -> Iterator[tuple[ast.AST, str]]:
    """A bare except also catches KeyboardInterrupt and SystemExit."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and node.type is None:
            yield node, "bare except: catch a specific exception"


@rule("S307", "eval() or exec() call")
def eval_exec(tree: ast.Module) -> Iterator[tuple[ast.AST, str]]:
    """eval/exec on data you do not control is remote code execution (3.2.11)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in {"eval", "exec"}:
                yield node, f"use of {node.func.id}(): use ast.literal_eval or a parser"


@rule("D103", "public function without a docstring")
def missing_docstrings(tree: ast.Module) -> Iterator[tuple[ast.AST, str]]:
    """Module-level and class-level public functions should say what they do."""
    containers: list[ast.AST] = [tree, *(n for n in tree.body if isinstance(n, ast.ClassDef))]
    for container in containers:
        for node in container.body:
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                if not node.name.startswith("_") and ast.get_docstring(node) is None:
                    yield node, f"public function {node.name}() has no docstring"


def scan_source(source: str, path: str = "<string>") -> list[Finding]:
    """Run every rule on source; a file that does not parse gives one E999 finding."""
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as error:
        return [
            Finding(
                path, error.lineno or 0, error.offset or 0, "E999", f"syntax error: {error.msg}"
            )
        ]
    findings = [
        Finding(path, node.lineno, node.col_offset + 1, registered.code, message)
        for registered in RULES.values()
        for node, message in registered.check(tree)
    ]
    return sorted(findings)


def iter_python_files(paths: Iterable[Path]) -> Iterator[Path]:
    """Python files named directly, or found under folders (skipping caches and dot-folders)."""
    for path in paths:
        if path.is_file():
            yield path
        elif path.is_dir():
            for candidate in sorted(path.rglob("*.py")):
                relative_parts = candidate.relative_to(path).parts[:-1]
                if any(part == "__pycache__" or part.startswith(".") for part in relative_parts):
                    continue
                yield candidate
        else:
            raise FileNotFoundError(f"no such file or folder: {path}")


def scan_paths(
    paths: Iterable[Path | str], *, relative_to: Path | str | None = None
) -> list[Finding]:
    """Scan files and folders; findings are sorted by path, line and column.

    Paths are reported as given, or relative to ``relative_to`` when it is set.
    """
    base = Path(relative_to) if relative_to is not None else None
    findings: list[Finding] = []
    for file_path in iter_python_files(Path(path) for path in paths):
        shown = file_path.relative_to(base) if base is not None else file_path
        findings.extend(scan_source(file_path.read_text(encoding="utf-8"), shown.as_posix()))
    return sorted(findings)


def format_findings(findings: list[Finding], *, as_json: bool = False) -> str:
    """Findings as text lines plus a summary, or as a JSON list."""
    if as_json:
        return json.dumps([asdict(finding) for finding in findings], indent=2)
    file_count = len({finding.path for finding in findings})
    summary = f"{len(findings)} finding(s) in {file_count} file(s)" if findings else "no findings"
    return "\n".join([*(str(finding) for finding in findings), summary])
