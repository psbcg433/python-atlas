"""Logging set-up for the command-line tool, as one ``logging.config.dictConfig`` dictionary.

The library modules only create loggers (``logging.getLogger(__name__)``) and never configure
them; the package adds a ``NullHandler`` so an application that imports it stays silent unless
it configures logging itself. Only the CLI calls ``configure_logging``.

Logs go to **stderr**, so stdout carries only the command's output and can be piped.
"""

import logging.config
from pathlib import Path
from typing import Any

LOGGER_NAME = "log_analyzer"
VERBOSITY_LEVELS = {-1: "ERROR", 0: "WARNING", 1: "INFO", 2: "DEBUG"}
CONSOLE_FORMAT = "%(levelname)s %(name)s: %(message)s"
FILE_FORMAT = "%(asctime)s %(levelname)-8s %(name)s:%(lineno)d %(message)s"


def level_for(verbosity: int) -> str:
    """Map ``-q`` (-1), default (0), ``-v`` (1) and ``-vv`` or more (2) to a level name."""
    return VERBOSITY_LEVELS[max(-1, min(verbosity, 2))]


def build_logging_config(level: str = "WARNING", *, log_file: Path | None = None) -> dict[str, Any]:
    """Return the ``dictConfig`` dictionary.

    Args:
        level: Level of the stderr handler.
        log_file: If given, a second handler writes everything from DEBUG up to this file.
    """
    handlers: dict[str, dict[str, Any]] = {
        "console": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stderr",
            "formatter": "console",
            "level": level,
        }
    }
    if log_file is not None:
        handlers["file"] = {
            "class": "logging.FileHandler",
            "filename": str(log_file),
            "encoding": "utf-8",
            "formatter": "file",
            "level": "DEBUG",
        }
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "console": {"format": CONSOLE_FORMAT},
            "file": {"format": FILE_FORMAT, "datefmt": "%Y-%m-%dT%H:%M:%S%z"},
        },
        "handlers": handlers,
        "loggers": {
            LOGGER_NAME: {
                # The logger lets everything the most verbose handler wants through;
                # each handler then filters by its own level.
                "level": "DEBUG" if log_file is not None else level,
                "handlers": list(handlers),
                "propagate": False,
            }
        },
    }


def configure_logging(verbosity: int = 0, *, log_file: Path | None = None) -> None:
    """Apply ``build_logging_config`` for a CLI verbosity count."""
    logging.config.dictConfig(build_logging_config(level_for(verbosity), log_file=log_file))
