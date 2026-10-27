"""Reference solutions for Phase 0 labs.

Run from the repository root:

    uv run python exercises/solutions/phase0_solutions.py
"""

import contextlib
import importlib.metadata
import io
import platform
import sys
from collections.abc import Callable

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


# Lab 0 ---------------------------------------------------------------------------------------


def environment_report() -> dict[str, str | bool]:
    """Return and print a description of the running Python environment."""
    report: dict[str, str | bool] = {
        "python_version": platform.python_version(),
        "implementation": platform.python_implementation(),
        "executable": sys.executable,
        "in_virtualenv": sys.prefix != sys.base_prefix,
        "jupyterlab_version": importlib.metadata.version("jupyterlab"),
    }
    for key, value in report.items():
        print(f"{key}: {value}")
    return report


def quiet_report() -> dict[str, str | bool]:
    """Call environment_report() without letting its prints reach the output."""
    with contextlib.redirect_stdout(io.StringIO()):
        return environment_report()


def check_lab_0() -> None:
    """Run the same checks as the Lab 0 check cell in the notebook."""
    expected_keys = [
        "python_version",
        "implementation",
        "executable",
        "in_virtualenv",
        "jupyterlab_version",
    ]
    run_checks(
        [
            ("returns a dict", lambda: isinstance(quiet_report(), dict), True),
            ("has exactly the five keys", lambda: sorted(quiet_report()), sorted(expected_keys)),
            ("python_version", lambda: quiet_report()["python_version"], platform.python_version()),
            (
                "implementation",
                lambda: quiet_report()["implementation"],
                platform.python_implementation(),
            ),
            ("executable", lambda: quiet_report()["executable"], sys.executable),
            (
                "in_virtualenv",
                lambda: quiet_report()["in_virtualenv"],
                sys.prefix != sys.base_prefix,
            ),
            (
                "jupyterlab_version",
                lambda: quiet_report()["jupyterlab_version"],
                importlib.metadata.version("jupyterlab"),
            ),
        ]
    )


if __name__ == "__main__":
    print("Lab 0 — environment_report()")
    environment_report()
    print()
    check_lab_0()
