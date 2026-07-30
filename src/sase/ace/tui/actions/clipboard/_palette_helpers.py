"""Shared warm-only helpers for Copy as palette contexts."""

from __future__ import annotations

import re
from typing import Any


def warm_agent_file_path(app: Any) -> str | None:
    try:
        from ...widgets import AgentDetail
        from ...widgets.file_panel import AgentFilePanel

        detail = app.query_one("#agent-detail-panel", AgentDetail)
        if not detail.is_file_visible():
            return None
        return detail.query_one(
            "#agent-file-panel", AgentFilePanel
        ).get_current_file_path()
    except Exception:
        return None


def axe_item_label(item: Any) -> str:
    if hasattr(item, "lumberjack_name") and hasattr(item, "chop_name"):
        return f"{item.lumberjack_name} · {item.chop_name}"
    if hasattr(item, "name"):
        return str(item.name)
    if hasattr(item, "slot"):
        return f"Command #{item.slot}"
    return "AXE selection"


def output_hint(output: str) -> str:
    if not output or not output.strip():
        return ""
    lines = output.strip().splitlines()
    return shorten(f"{len(lines)} lines · {lines[0]}")


def number_from_url(url: str | None) -> str:
    if not url:
        return ""
    match = re.search(r"/(\d+)(?:/)?$", url)
    return match.group(1) if match else ""


def size_hint(size: Any) -> str:
    if not isinstance(size, int) or size < 0:
        return ""
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KiB"
    return f"{size / (1024 * 1024):.1f} MiB"


def marked_hint(count: int, label: str) -> str:
    return f"{count} marked · {label}"


def marked_count_hint(representable: int, total: int, label: str) -> str:
    if representable == total:
        return marked_hint(total, label)
    return f"{representable}/{total} marked · {label}"


def shorten(value: str, *, limit: int = 58) -> str:
    collapsed = " ".join(str(value).split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1] + "…"


def notify_copy_warning(app: Any, message: str) -> None:
    app.notify(message, severity="warning")
