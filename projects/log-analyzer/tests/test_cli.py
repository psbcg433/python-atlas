"""The command-line interface, called in-process through ``main(argv)``."""

import errno
import json
import os
import runpy
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from log_analyzer import __version__
from log_analyzer.cli import EXIT_ERROR, EXIT_MALFORMED, EXIT_OK, build_parser, main

type Capture = pytest.CaptureFixture[str]


def test_version(capsys: Capture) -> None:
    with pytest.raises(SystemExit) as caught:
        main(["--version"])
    assert caught.value.code == 0
    assert capsys.readouterr().out == f"log-analyzer {__version__}\n"


def test_subcommand_is_required(capsys: Capture) -> None:
    with pytest.raises(SystemExit) as caught:
        main([])
    assert caught.value.code == 2
    assert "the following arguments are required: COMMAND" in capsys.readouterr().err


def test_parser_lists_every_subcommand() -> None:
    help_text = build_parser().format_help()
    for command in ("generate", "report", "export", "validate"):
        assert command in help_text


@pytest.mark.parametrize(
    "argv",
    [
        ["generate", "x.log", "--lines", "-3"],
        ["generate", "x.log", "--malformed-rate", "2"],
        ["report", "x.log", "--top", "0"],
        ["validate", "x.log", "--show", "-1"],
        ["-v", "-q", "report", "x.log"],
    ],
)
def test_bad_arguments_exit_2(argv: list[str], capsys: Capture) -> None:
    with pytest.raises(SystemExit) as caught:
        main(argv)
    assert caught.value.code == 2
    assert "error:" in capsys.readouterr().err


def test_generate_then_report(tmp_path: Path, capsys: Capture) -> None:
    log_path = tmp_path / "demo.log.gz"
    argv = ["generate", str(log_path), "-n", "500", "--seed", "3", "--malformed-rate", "0.1"]
    assert main(argv) == EXIT_OK
    assert capsys.readouterr().out.startswith(f"wrote 500 lines to {log_path} (")
    assert main(["-q", "report", str(log_path), "--top", "2"]) == EXIT_OK
    captured = capsys.readouterr()
    assert "ACCESS LOG REPORT" in captured.out
    assert captured.err == ""  # -q hides the malformed-lines warning


def test_generate_without_malformed_lines(tmp_path: Path, capsys: Capture) -> None:
    log_path = tmp_path / "clean.log"
    assert main(["generate", str(log_path), "-n", "10", "--malformed-rate", "0"]) == EXIT_OK
    assert capsys.readouterr().out == f"wrote 10 lines to {log_path} (no malformed lines)\n"


def test_report_json(sample_log: Path, capsys: Capture) -> None:
    assert main(["report", str(sample_log), "--format", "json"]) == EXIT_OK
    captured = capsys.readouterr()
    assert json.loads(captured.out)["malformed_lines"] == 4
    assert captured.err.startswith("WARNING log_analyzer.analysis: 4 of 6 lines")


@pytest.mark.parametrize(
    ("file_name", "argv_extra", "label"),
    [
        ("out.csv", [], "csv"),
        ("out.json", [], "json"),
        ("records.data", ["--format", "sqlite"], "sqlite"),
    ],
)
def test_export_formats(
    sample_log: Path,
    tmp_path: Path,
    capsys: Capture,
    file_name: str,
    argv_extra: list[str],
    label: str,
) -> None:
    output = tmp_path / file_name
    assert main(["-q", "export", str(sample_log), str(output), *argv_extra]) == EXIT_OK
    where = "stored in table 'malformed'" if label == "sqlite" else "skipped"
    assert capsys.readouterr().out == (
        f"exported 2 records to {output} ({label}); 4 malformed lines {where}\n"
    )
    if label == "sqlite":
        with closing(sqlite3.connect(output)) as connection:
            assert connection.execute("SELECT COUNT(*) FROM malformed").fetchone() == (4,)


def test_export_unknown_extension_is_an_error(
    sample_log: Path, tmp_path: Path, capsys: Capture
) -> None:
    assert main(["export", str(sample_log), str(tmp_path / "out.txt")]) == EXIT_ERROR
    assert capsys.readouterr().err.startswith("log-analyzer: error: cannot infer the export format")


def test_validate_clean_log(clean_log: Path, capsys: Capture) -> None:
    assert main(["validate", str(clean_log)]) == EXIT_OK
    assert capsys.readouterr().out == f"{clean_log}: OK, 200 records, no malformed lines\n"


def test_validate_lists_problems(sample_log: Path, capsys: Capture) -> None:
    assert main(["-q", "validate", str(sample_log), "--show", "2"]) == EXIT_MALFORMED
    assert capsys.readouterr().out.splitlines() == [
        f"{sample_log}: FAILED, 4 malformed lines",
        "  line 2: unrecognized format: '2026-11-06T09:00:01Z 10.0.1.5 \"POST /api/check'",
        "  line 3: unrecognized format: '<html>502 Bad Gateway</html>'",
        "  ... and 2 more",
    ]


NO_SUCH_FILE = os.strerror(errno.ENOENT)  # "No such file or directory", Windows included


# A backslash and a quote are where str(OSError) goes wrong: its repr of the path doubles
# the backslash (every separator on Windows) and switches quotes. On Windows the backslash
# is a separator, so that case is a missing file in a missing folder: still ENOENT.
@pytest.mark.parametrize("file_name", ["missing.log", "it's\\back.log"])
def test_missing_file_is_a_clean_error(tmp_path: Path, capsys: Capture, file_name: str) -> None:
    missing = tmp_path / file_name
    assert main(["report", str(missing)]) == EXIT_ERROR
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == f"log-analyzer: error: cannot read {missing}: {NO_SUCH_FILE}\n"


def test_unwritable_output_is_a_clean_error(
    sample_log: Path, tmp_path: Path, capsys: Capture
) -> None:
    output = tmp_path / "no-such-folder" / "out.csv"
    assert main(["export", str(sample_log), str(output)]) == EXIT_ERROR
    assert (
        capsys.readouterr().err == f"log-analyzer: error: cannot write {output}: {NO_SUCH_FILE}\n"
    )


def test_os_error_without_a_file_name(monkeypatch: pytest.MonkeyPatch, capsys: Capture) -> None:
    def disk_full(*_args: object, **_kwargs: object) -> None:
        raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))

    monkeypatch.setattr("log_analyzer.cli.write_synthetic_log", disk_full)
    assert main(["generate", "x.log"]) == EXIT_ERROR
    assert (
        capsys.readouterr().err
        == f"log-analyzer: error: {OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))}\n"
    )


def test_verbose_and_log_file(sample_log: Path, tmp_path: Path, capsys: Capture) -> None:
    log_file = tmp_path / "debug.log"
    assert main(["-vv", "--log-file", str(log_file), "validate", str(sample_log)]) == 1
    err = capsys.readouterr().err
    assert "DEBUG log_analyzer.cli: arguments:" in err
    assert "DEBUG log_analyzer.parsing: skipping line 2: unrecognized format" in err
    assert "INFO log_analyzer.analysis: analyzed sample.log" in err
    assert "skipping line 6: status out of range" in log_file.read_text(encoding="utf-8")


def test_python_dash_m(monkeypatch: pytest.MonkeyPatch, capsys: Capture) -> None:
    monkeypatch.setattr("sys.argv", ["log_analyzer", "--version"])
    with pytest.raises(SystemExit) as caught:
        runpy.run_module("log_analyzer", run_name="__main__")
    assert caught.value.code == 0
    assert capsys.readouterr().out == f"log-analyzer {__version__}\n"
