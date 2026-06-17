"""TUI diagnostics file logging.

Installs a rotating ``FileHandler`` on the ``sase`` logger so that every
``log.exception(...)`` / ``log.warning(...)`` raised anywhere in the package
lands in a durable, findable file (``~/.sase/logs/tui.log``). This is the
implicit backstop for the explicit :func:`sase.logs.log_launch_failure`
writer: even an un-instrumented failure path leaves a trace.

The handler is scoped to the ``sase ace`` TUI (installed from
``handle_ace_command``), not the bare CLI or tests, and is idempotent so
re-entrant startups never double-install.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from sase.logs import tui_log_path

# Identifying name so the install is idempotent across re-entrant startups.
_HANDLER_NAME = "sase_tui_file"
# Keep the log focused on problems and bounded in size (see the epic's risk
# note on tui.log noise/volume).
_MAX_BYTES = 2 * 1024 * 1024  # 2 MiB
_BACKUP_COUNT = 3


def install_tui_file_logging(level: int = logging.WARNING) -> None:
    """Attach a rotating file handler for the ``sase`` logger to ``tui.log``.

    Idempotent: a second call is a no-op once the handler is installed. Scoped
    to ``WARNING`` and above by default so the file stays focused on failures
    and bounded by rotation.
    """
    logger = logging.getLogger("sase")
    for handler in logger.handlers:
        if getattr(handler, "name", None) == _HANDLER_NAME:
            return

    path = tui_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    handler = RotatingFileHandler(
        path,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.name = _HANDLER_NAME
    handler.setLevel(level)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logger.addHandler(handler)
    # Ensure records at the chosen level actually reach the handler without
    # clobbering a more verbose level a caller may have configured.
    if logger.level == logging.NOTSET or logger.level > level:
        logger.setLevel(level)
