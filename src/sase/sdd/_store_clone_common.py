"""Shared helpers for SDD store clone operations."""

from __future__ import annotations

import logging
from pathlib import Path
import shutil
import time

from sase.sdd._store_types import (
    SddMaterializationError,
    SddTransientMaterializationError,
)

_logger = logging.getLogger(__name__)


def remove_partial_sdd_clone(workspace_sdd: Path) -> None:
    """Best-effort removal of a failed clone destination."""

    try:
        if workspace_sdd.is_dir() and not workspace_sdd.is_symlink():
            shutil.rmtree(workspace_sdd)
        else:
            workspace_sdd.unlink(missing_ok=True)
    except OSError:
        _logger.warning(
            "Failed to clean partial SDD clone at %s",
            workspace_sdd,
            exc_info=True,
        )


def handle_failed_sdd_clone(
    workspace_sdd: Path,
    message: str,
    *,
    strict: bool,
    cause: Exception | None = None,
    transient: bool = False,
    cleanup_path: Path | None = None,
) -> bool:
    """Remove partial clone output and optionally fail the setup transaction."""

    if cleanup_path is not None:
        remove_partial_sdd_clone(cleanup_path)
    if strict:
        error_cls = (
            SddTransientMaterializationError if transient else SddMaterializationError
        )
        error = error_cls(message)
        if cause is not None:
            raise error from cause
        raise error
    _logger.warning(message, exc_info=cause is not None)
    return False


def deadline_timeout(default: float, deadline: float | None) -> float:
    if deadline is None:
        return max(0.0, default)
    return min(max(0.0, default), max(0.0, deadline - time.monotonic()))


def sleep_before_retry(delay: float, deadline: float | None) -> bool:
    wait = max(0.0, delay)
    if deadline is not None:
        remaining = max(0.0, deadline - time.monotonic())
        if remaining <= 0.0:
            return False
        wait = min(wait, remaining)
    time.sleep(wait)
    return deadline is None or time.monotonic() < deadline
