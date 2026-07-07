"""Timestamp formatting helpers for the tools panel."""

from __future__ import annotations

import sys
from datetime import datetime
from typing import Any

from sase.core.time import get_timezone


def format_timestamp(iso_str: str) -> str:
    """Format an ISO timestamp to HH:MM:SS display."""
    try:
        cleaned = iso_str.replace("Z", "+00:00")
        datetime_type, timezone_getter = _panel_time_dependencies()
        dt = datetime_type.fromisoformat(cleaned)
        dt = dt.astimezone(timezone_getter())
        return dt.strftime("%H:%M:%S")
    except (ValueError, AttributeError):
        return "??:??:??"


def _panel_time_dependencies() -> tuple[Any, Any]:
    panel_module = sys.modules.get("sase.ace.tui.widgets.tools_panel")
    if panel_module is None:
        return datetime, get_timezone
    return (
        getattr(panel_module, "datetime", datetime),
        getattr(panel_module, "get_timezone", get_timezone),
    )
