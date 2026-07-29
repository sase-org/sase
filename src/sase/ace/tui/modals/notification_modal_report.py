"""Structured report preview for the notification modal."""

from __future__ import annotations

import os
from typing import Any

from rich.console import Group, RenderableType
from rich.text import Text
from textual.containers import VerticalScroll

from sase.axe.chop_report_render import TONE_STYLES, render_chop_report
from sase.notifications import (
    Notification,
    format_relative_time,
    is_report_notification,
    load_notification_report,
)

_DEFAULT_REPORT_WIDTH = 72


class NotificationReportMixin:
    """Render report notifications as rich, read-only summaries."""

    def _render_report_pane(
        self: Any, notification: Notification
    ) -> tuple[str, RenderableType] | None:
        """Return the report pane title and content for *notification*."""
        if not is_report_notification(notification):
            return None

        report = load_notification_report(notification)
        if report is None:
            return None
        if report.document is None:
            failure = Text(
                f"▲ {report.error or 'report could not be loaded'}",
                style=f"bold {TONE_STYLES['error']}",
            )
            renderables: list[RenderableType] = [failure]
            if report.path:
                renderables.append(
                    Text(f"tried {report.path}", style=TONE_STYLES["muted"])
                )
            return report.title, Group(*renderables)

        age = (
            format_relative_time(report.updated_at)
            if report.updated_at
            else "time unknown"
        )
        if report.source == "live":
            provenance = Text(
                f"live · updated {age}",
                style=f"bold {TONE_STYLES['ok']}",
            )
        else:
            provenance = Text(
                f"snapshot · captured {age}",
                style=TONE_STYLES["muted"],
            )

        renderables = [
            provenance,
            Text(""),
            render_chop_report(
                report.document,
                width=self._notification_report_width(),
            ),
        ]
        if notification.files:
            names = ", ".join(
                os.path.basename(path) or path for path in notification.files
            )
            renderables.extend(
                (
                    Text(""),
                    Text(f"attachments: {names}", style=TONE_STYLES["muted"]),
                )
            )
        return report.title, Group(*renderables)

    def _notification_report_width(self: Any) -> int:
        """Return the visible report-pane width, with a pre-layout fallback."""
        try:
            scroll = self.query_one(
                "#notification-file-scroll",
                VerticalScroll,
            )
            width = scroll.scrollable_content_region.width
            if width > 0:
                return width
        except Exception:
            pass
        return _DEFAULT_REPORT_WIDTH


__all__ = ["NotificationReportMixin"]
