"""Fail-closed loading for structured notification report documents."""

from __future__ import annotations

import json
import os
import stat
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from sase.chops import validate_chop_report
from sase.core.time import get_timezone
from sase.notifications.models import Notification

REPORT_ACTION = "ViewReport"
MAX_REPORT_BYTES = 256 * 1024

_MAX_TITLE_CHARS = 64
_MAX_VALIDATION_ERROR_CHARS = 160

ReportSource = Literal["live", "snapshot"]


@dataclass(frozen=True)
class NotificationReport:
    """One validated notification report or a bounded loading failure."""

    document: dict[str, Any] | None
    source: ReportSource | None
    title: str
    path: str | None
    updated_at: str | None
    error: str | None


def is_report_notification(notification: Notification) -> bool:
    """Return whether *notification* carries the generic report action."""

    return notification.action == REPORT_ACTION


def _bounded_line(value: object, *, limit: int) -> str:
    text = str(value)
    without_controls = "".join(
        " " if unicodedata.category(character) == "Cc" else character
        for character in text
    )
    normalized = " ".join(without_controls.split())
    if len(normalized) > limit:
        return normalized[: limit - 1] + "…"
    return normalized


def _title(notification: Notification, document: dict[str, Any] | None) -> str:
    override = _bounded_line(
        notification.action_data.get("report_title", ""),
        limit=_MAX_TITLE_CHARS,
    )
    if override:
        return override
    if document is not None and isinstance(document.get("title"), str):
        document_title = _bounded_line(
            document["title"],
            limit=_MAX_TITLE_CHARS,
        )
        if document_title:
            return document_title
    return "Report"


def _validation_error(error: Exception) -> str:
    detail = _bounded_line(error, limit=_MAX_VALIDATION_ERROR_CHARS)
    return f"report document is invalid: {detail or type(error).__name__}"


def _decode_report(raw: bytes | str) -> dict[str, Any]:
    try:
        document = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ValueError("report document is not valid JSON") from error
    if not isinstance(document, dict):
        raise ValueError("report document must be a JSON object")
    try:
        return validate_chop_report(document)
    except ValueError as error:
        raise ValueError(_validation_error(error)) from error


def _size_error(size: int) -> str:
    kibibytes = (size + 1023) // 1024
    return f"report file is too large ({kibibytes} KiB)"


def _load_live_report(
    raw_path: str,
) -> tuple[dict[str, Any] | None, str | None, str | None, str | None]:
    expanded_path = os.path.expanduser(raw_path)
    path = Path(expanded_path)
    path_value = str(path)
    if not path.is_absolute():
        return None, path_value, None, "report path must be absolute"

    try:
        metadata = path.stat()
        if not stat.S_ISREG(metadata.st_mode):
            return None, path_value, None, "report path is not a regular file"
        if metadata.st_size > MAX_REPORT_BYTES:
            return None, path_value, None, _size_error(metadata.st_size)
        raw = path.read_bytes()
        if len(raw) > MAX_REPORT_BYTES:
            return None, path_value, None, _size_error(len(raw))
        document = _decode_report(raw)
    except FileNotFoundError:
        return None, path_value, None, "report file not found"
    except PermissionError:
        return None, path_value, None, "report file is not readable"
    except OSError as error:
        detail = _bounded_line(error, limit=_MAX_VALIDATION_ERROR_CHARS)
        message = "report file could not be read"
        if detail:
            message += f": {detail}"
        return None, path_value, None, message
    except ValueError as error:
        return None, path_value, None, str(error)

    updated_at = datetime.fromtimestamp(
        metadata.st_mtime,
        get_timezone(),
    ).isoformat()
    return document, path_value, updated_at, None


def _load_snapshot_report(
    raw_report: str,
) -> tuple[dict[str, Any] | None, str | None]:
    try:
        return _decode_report(raw_report), None
    except (UnicodeError, ValueError) as error:
        return None, str(error)


def load_notification_report(
    notification: Notification,
) -> NotificationReport | None:
    """Resolve a live report or inline snapshot without ever raising."""

    if not is_report_notification(notification):
        return None

    try:
        raw_path = notification.action_data.get("report_path")
        live_error: str | None = None
        attempted_path: str | None = None
        if raw_path:
            document, attempted_path, updated_at, live_error = _load_live_report(
                raw_path
            )
            if document is not None:
                return NotificationReport(
                    document=document,
                    source="live",
                    title=_title(notification, document),
                    path=attempted_path,
                    updated_at=updated_at,
                    error=None,
                )

        if "report" in notification.action_data:
            document, snapshot_error = _load_snapshot_report(
                notification.action_data["report"]
            )
            if document is not None:
                return NotificationReport(
                    document=document,
                    source="snapshot",
                    title=_title(notification, document),
                    path=None,
                    updated_at=notification.timestamp,
                    error=None,
                )
            failure = snapshot_error or "report snapshot could not be loaded"
        else:
            failure = live_error or "report source is missing"

        return NotificationReport(
            document=None,
            source=None,
            title=_title(notification, None),
            path=attempted_path,
            updated_at=None,
            error=failure,
        )
    except Exception as error:
        detail = _bounded_line(error, limit=_MAX_VALIDATION_ERROR_CHARS)
        return NotificationReport(
            document=None,
            source=None,
            title="Report",
            path=None,
            updated_at=None,
            error=f"report could not be loaded: {detail or type(error).__name__}",
        )
