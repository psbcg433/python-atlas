"""The dictConfig logging set-up."""

import logging
from pathlib import Path

import pytest

from log_analyzer.logging_config import (
    LOGGER_NAME,
    build_logging_config,
    configure_logging,
    level_for,
)


@pytest.mark.parametrize(
    ("verbosity", "level"),
    [(-5, "ERROR"), (-1, "ERROR"), (0, "WARNING"), (1, "INFO"), (2, "DEBUG"), (9, "DEBUG")],
)
def test_level_for(verbosity: int, level: str) -> None:
    assert level_for(verbosity) == level


def test_config_shape_without_file() -> None:
    config = build_logging_config("INFO")
    assert config["version"] == 1
    assert config["disable_existing_loggers"] is False
    assert list(config["handlers"]) == ["console"]
    assert config["handlers"]["console"]["stream"] == "ext://sys.stderr"
    assert config["loggers"][LOGGER_NAME] == {
        "level": "INFO",
        "handlers": ["console"],
        "propagate": False,
    }


def test_file_handler_lowers_the_logger_level(tmp_path: Path) -> None:
    config = build_logging_config("WARNING", log_file=tmp_path / "run.log")
    assert config["loggers"][LOGGER_NAME]["level"] == "DEBUG"
    assert config["handlers"]["console"]["level"] == "WARNING"
    assert config["handlers"]["file"]["level"] == "DEBUG"


def test_configure_logging_routes_by_level(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    log_file = tmp_path / "run.log"
    configure_logging(0, log_file=log_file)
    module_logger = logging.getLogger("log_analyzer.export")  # a child of the package logger
    module_logger.debug("debug detail")
    module_logger.warning("something odd")
    assert capsys.readouterr().err == "WARNING log_analyzer.export: something odd\n"
    file_text = log_file.read_text(encoding="utf-8")
    assert "DEBUG    log_analyzer.export:" in file_text
    assert "debug detail" in file_text
    assert "WARNING  log_analyzer.export:" in file_text


def test_library_is_silent_until_configured(capsys: pytest.CaptureFixture[str]) -> None:
    logging.getLogger("log_analyzer.analysis").warning("nobody should see this")
    assert capsys.readouterr().err == ""
