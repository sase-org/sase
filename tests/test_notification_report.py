"""Tests for the fail-closed notification report contract."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import pytest

from sase.core.time import get_timezone
from sase.ace.tui.modals.notification_modal_constants import (
    ACTION_BADGES,
    ACTION_ICONS,
    notification_icon,
)
from sase.notifications import (
    Notification,
    is_report_notification,
    load_notification_report,
)
from sase.notifications.report import MAX_REPORT_BYTES, REPORT_ACTION


def _document(
    *,
    title: str = "Release report",
    tone: str = "ok",
) -> dict[str, object]:
    return {
        "title": title,
        "blocks": [
            {
                "kind": "headline",
                "text": "2 merged today",
                "tone": tone,
            }
        ],
    }


def _notification(
    *,
    action: str | None = REPORT_ACTION,
    action_data: dict[str, str] | None = None,
) -> Notification:
    return Notification(
        id="report-notification",
        timestamp="2026-07-29T10:14:17-04:00",
        sender="ci_watch",
        action=action,
        action_data=action_data or {},
    )


def _write_report(path: Path, document: dict[str, object] | None = None) -> None:
    path.write_text(json.dumps(document or _document()), encoding="utf-8")


def test_live_path_wins_over_inline_snapshot_and_uses_file_mtime(
    tmp_path: Path,
) -> None:
    path = tmp_path / "releases.report.json"
    _write_report(path, _document(title="Current releases"))
    mtime = 1_785_332_057
    os.utime(path, (mtime, mtime))
    notification = _notification(
        action_data={
            "report_path": str(path),
            "report": json.dumps(_document(title="Old snapshot")),
        }
    )

    report = load_notification_report(notification)

    assert report is not None
    assert report.document is not None
    assert report.document["title"] == "Current releases"
    assert report.source == "live"
    assert report.path == str(path)
    assert (
        report.updated_at
        == datetime.fromtimestamp(
            path.stat().st_mtime,
            get_timezone(),
        ).isoformat()
    )
    assert report.error is None


@pytest.mark.parametrize(
    "live_failure",
    ["absent", "missing", "oversized", "invalid"],
)
def test_inline_snapshot_falls_back_from_live_path_failure(
    tmp_path: Path,
    live_failure: str,
) -> None:
    path = tmp_path / "live.json"
    if live_failure == "oversized":
        path.write_bytes(b" " * (MAX_REPORT_BYTES + 1))
    elif live_failure == "invalid":
        path.write_text("{nope", encoding="utf-8")

    action_data = {"report": json.dumps(_document(title="Snapshot releases"))}
    if live_failure != "absent":
        action_data["report_path"] = str(path)
    notification = _notification(action_data=action_data)

    report = load_notification_report(notification)

    assert report is not None
    assert report.document is not None
    assert report.document["title"] == "Snapshot releases"
    assert report.source == "snapshot"
    assert report.path is None
    assert report.updated_at == notification.timestamp
    assert report.error is None


@pytest.mark.parametrize(
    ("failure", "error_fragment"),
    [
        ("missing", "not found"),
        ("directory", "regular file"),
        ("non_json", "not valid JSON"),
        ("array", "JSON object"),
        ("oversized", "too large"),
        ("invalid_kind", "unknown variant"),
        ("invalid_tone", "unknown variant"),
    ],
)
def test_live_failure_modes_return_bounded_errors(
    tmp_path: Path,
    failure: str,
    error_fragment: str,
) -> None:
    path = tmp_path / "report.json"
    if failure == "directory":
        path.mkdir()
    elif failure == "non_json":
        path.write_bytes(b"\xff\xfe not JSON")
    elif failure == "array":
        path.write_text("[]", encoding="utf-8")
    elif failure == "oversized":
        path.write_bytes(b"x" * (MAX_REPORT_BYTES + 1))
    elif failure == "invalid_kind":
        _write_report(
            path,
            {"blocks": [{"kind": "bogus", "text": "unsafe"}]},
        )
    elif failure == "invalid_tone":
        _write_report(path, _document(tone="rainbow"))

    report = load_notification_report(
        _notification(action_data={"report_path": str(path)})
    )

    assert report is not None
    assert report.document is None
    assert report.source is None
    assert report.updated_at is None
    assert report.error
    assert error_fragment in report.error
    assert len(report.error) <= 200


def test_tilde_path_expands_and_relative_path_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    path = home / "report.json"
    _write_report(path)
    monkeypatch.setenv("HOME", str(home))

    expanded = load_notification_report(
        _notification(action_data={"report_path": "~/report.json"})
    )
    relative = load_notification_report(
        _notification(action_data={"report_path": "report.json"})
    )

    assert expanded is not None
    assert expanded.document is not None
    assert expanded.source == "live"
    assert expanded.path == str(path)
    assert relative is not None
    assert relative.document is None
    assert relative.error == "report path must be absolute"


def test_title_precedence_default_and_truncation(tmp_path: Path) -> None:
    path = tmp_path / "report.json"
    _write_report(path, _document(title="Document title"))

    overridden = load_notification_report(
        _notification(
            action_data={
                "report_path": str(path),
                "report_title": "  Producer\n title  ",
            }
        )
    )
    document_title = load_notification_report(
        _notification(action_data={"report_path": str(path)})
    )
    default = load_notification_report(
        _notification(action_data={"report": json.dumps({"blocks": []})})
    )
    truncated = load_notification_report(
        _notification(
            action_data={
                "report": json.dumps(_document()),
                "report_title": "x" * 80,
            }
        )
    )

    assert overridden is not None and overridden.title == "Producer title"
    assert document_title is not None and document_title.title == "Document title"
    assert default is not None and default.title == "Report"
    assert truncated is not None
    assert truncated.title == "x" * 63 + "…"
    assert len(truncated.title) == 64


def test_non_report_notifications_are_not_loaded() -> None:
    assert not is_report_notification(_notification(action=None))
    assert not is_report_notification(_notification(action="ViewErrorReport"))
    assert load_notification_report(_notification(action=None)) is None
    assert load_notification_report(_notification(action="ViewErrorReport")) is None


def test_view_report_action_has_badge_icon_and_authored_icon_precedence() -> None:
    assert ACTION_BADGES[REPORT_ACTION] == "[report]"
    assert ACTION_ICONS[REPORT_ACTION] == "📊"
    assert notification_icon(REPORT_ACTION, None) == "📊"
    assert notification_icon(REPORT_ACTION, "🚢") == "🚢"


def test_missing_sources_returns_explicit_failure() -> None:
    report = load_notification_report(_notification())

    assert report is not None
    assert report.document is None
    assert report.error == "report source is missing"
