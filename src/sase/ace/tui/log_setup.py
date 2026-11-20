"""TUI diagnostics file logging.

Installs a rotating ``FileHandler`` on the ``sase`` logger so that every
``log.exception(...)`` / ``log.warning(...)`` raised anywhere in the package
lands in a durable, findable file (``~/.sase/logs/tui.log``). This is the
implicit backstop for the explicit :func:`sase.logs.log_launch_failure`
writer: even an un-instrumented failure path leaves a trace.

The handler is scoped to ``sase tui`` (installed from
``handle_ace_command``), not the bare CLI or tests, and is idempotent so
re-entrant startups never double-install.

Rotation is by size and by age: the active file rolls when it exceeds
``_MAX_BYTES`` or when its oldest entry is older than ``_MAX_AGE_SECONDS``.
Rotated segments whose newest entry is older than that horizon are deleted
at TUI start and after each rotation.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from sase.logs import tui_log_path

# Identifying name so the install is idempotent across re-entrant startups.
_HANDLER_NAME = "sase_tui_file"
# Keep the log focused on problems and bounded in size (see the epic's risk
# note on tui.log noise/volume).
_MAX_BYTES = 2 * 1024 * 1024  # 2 MiB
_BACKUP_COUNT = 3
_MAX_AGE_SECONDS = 14 * 24 * 60 * 60
_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
_TIMESTAMP_WIDTH = 19


def _now() -> float:
    return time.time()


def _parse_log_timestamp(line: str) -> float | None:
    text = line.strip()
    if len(text) < _TIMESTAMP_WIDTH:
        return None
    try:
        parsed = datetime.strptime(text[:_TIMESTAMP_WIDTH], _TIMESTAMP_FORMAT)
    except ValueError:
        return None
    return parsed.timestamp()


def _oldest_entry_ts(path: Path) -> float | None:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                parsed = _parse_log_timestamp(line)
                if parsed is not None:
                    return parsed
    except OSError:
        return None
    return None


def _newest_entry_ts(path: Path) -> float | None:
    try:
        size = path.stat().st_size
    except OSError:
        return None
    if size <= 0:
        return None
    try:
        with path.open("rb") as handle:
            handle.seek(max(0, size - 8192))
            chunk = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    for line in reversed(chunk.splitlines()):
        parsed = _parse_log_timestamp(line)
        if parsed is not None:
            return parsed
    return None


def _segment_newest_ts(path: Path) -> float | None:
    newest = _newest_entry_ts(path)
    if newest is not None:
        return newest
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _prune_old_tui_log_segments(
    path: Path,
    *,
    now: float | None = None,
    max_age_seconds: float | None = None,
) -> list[Path]:
    """Delete rotated ``tui.log`` segments older than the age horizon."""

    moment = _now() if now is None else now
    horizon = _MAX_AGE_SECONDS if max_age_seconds is None else max_age_seconds
    if horizon <= 0:
        return []
    deleted: list[Path] = []
    # Numbered RotatingFileHandler backups only — do not list ~/.sase/logs.
    for index in range(1, _BACKUP_COUNT + 8):
        candidate = path.with_name(f"{path.name}.{index}")
        try:
            if candidate.is_symlink() or not candidate.is_file():
                continue
        except OSError:
            continue
        newest = _segment_newest_ts(candidate)
        if newest is None or (moment - newest) <= horizon:
            continue
        try:
            os.unlink(candidate)
        except OSError:
            continue
        deleted.append(candidate)
    return deleted


def _active_log_is_stale(path: Path, *, now: float, max_age_seconds: float) -> bool:
    if max_age_seconds <= 0 or not path.is_file():
        return False
    oldest = _oldest_entry_ts(path)
    return oldest is not None and (now - oldest) > max_age_seconds


class _AgeAndSizeRotatingFileHandler(RotatingFileHandler):
    """Rotate ``tui.log`` by size or by the age of the oldest record."""

    def __init__(
        self,
        filename: str,
        *,
        maxBytes: int,
        backupCount: int,
        max_age_seconds: float,
        encoding: str = "utf-8",
    ) -> None:
        super().__init__(
            filename,
            maxBytes=maxBytes,
            backupCount=backupCount,
            encoding=encoding,
        )
        self.max_age_seconds = max_age_seconds
        self._oldest_ts: float | None = None

    def shouldRollover(self, record: logging.LogRecord) -> int:
        if super().shouldRollover(record):
            return 1
        if self.max_age_seconds <= 0:
            return 0
        oldest = self._cached_oldest_ts()
        if oldest is None:
            return 0
        return 1 if (_now() - oldest) > self.max_age_seconds else 0

    def doRollover(self) -> None:
        super().doRollover()
        self._oldest_ts = None
        _prune_old_tui_log_segments(
            Path(self.baseFilename),
            max_age_seconds=self.max_age_seconds,
        )

    def _cached_oldest_ts(self) -> float | None:
        if self._oldest_ts is not None:
            return self._oldest_ts
        self._oldest_ts = _oldest_entry_ts(Path(self.baseFilename))
        return self._oldest_ts


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
    _prune_old_tui_log_segments(path, max_age_seconds=_MAX_AGE_SECONDS)

    handler = _AgeAndSizeRotatingFileHandler(
        str(path),
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        max_age_seconds=_MAX_AGE_SECONDS,
        encoding="utf-8",
    )
    handler.name = _HANDLER_NAME
    handler.setLevel(level)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s",
            datefmt=_TIMESTAMP_FORMAT,
        )
    )
    if _active_log_is_stale(path, now=_now(), max_age_seconds=_MAX_AGE_SECONDS):
        handler.doRollover()
    logger.addHandler(handler)
    # Ensure records at the chosen level actually reach the handler without
    # clobbering a more verbose level a caller may have configured.
    if logger.level == logging.NOTSET or logger.level > level:
        logger.setLevel(level)
