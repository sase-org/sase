"""Tests for ``sase notify list`` and ``sase notify show`` behavior."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.main.notify_handler import handle_notify_command
from sase.main.parser import create_parser
from sase.notifications.cli_list import handle_notify_list
from sase.notifications.cli_show import handle_notify_show
from sase.notifications.store import append_notification

from tests.main.notify_handler_helpers import (
    list_args,
    make_notification,
    show_args,
    timestamp,
)

pytest_plugins = ["tests.main.notify_handler_fixtures"]


def test_notify_command_dispatches_list(
    temp_notifications_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del temp_notifications_dir
    append_notification(make_notification("target"))

    with pytest.raises(SystemExit) as excinfo:
        handle_notify_command(
            argparse.Namespace(
                notify_subcommand="list",
                json=True,
                limit=20,
                query=None,
                sender=None,
                unread=False,
                all=False,
            )
        )

    assert excinfo.value.code == 0
    assert json.loads(capsys.readouterr().out)[0]["id"] == "target"


def test_list_json_shape_default_limit_and_filters(
    temp_notifications_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del temp_notifications_dir
    for idx in range(25):
        append_notification(
            make_notification(
                f"n{idx}",
                minutes_ago=25 - idx,
                sender="axe" if idx % 2 == 0 else "sync",
                notes=[f"digest {idx}"],
                read=idx % 3 == 0,
            )
        )

    handle_notify_list(list_args(json=True, query="digest", sender="axe", unread=True))

    rows = json.loads(capsys.readouterr().out)
    assert len(rows) <= 20
    assert all(row["sender"] == "axe" for row in rows)
    assert all(row["read"] is False for row in rows)
    assert list(rows[0]) == [
        "id",
        "timestamp",
        "age",
        "sender",
        "icon",
        "color",
        "priority",
        "notes",
        "files",
        "tags",
        "action",
        "action_data",
        "read",
        "dismissed",
        "silent",
        "muted",
        "snooze_until",
        "resurfaced_at",
        "plus_ones",
        "plus_one_count",
        "dedup_key",
    ]


def test_list_all_includes_dismissed(
    temp_notifications_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del temp_notifications_dir
    append_notification(make_notification("active"))
    append_notification(make_notification("dismissed", dismissed=True))

    handle_notify_list(list_args(json=True))
    rows = json.loads(capsys.readouterr().out)
    assert [row["id"] for row in rows] == ["active"]

    handle_notify_list(list_args(json=True, all=True))
    rows = json.loads(capsys.readouterr().out)
    assert {row["id"] for row in rows} == {"active", "dismissed"}


def test_list_pretty_empty(capsys: pytest.CaptureFixture[str]) -> None:
    with patch("sase.notifications.cli_list.list_notification_infos", return_value=[]):
        handle_notify_list(list_args(json=False))

    out = capsys.readouterr().out
    assert "Notifications (0)" in out
    assert "No notifications found" in out


def test_list_pretty_exposes_resurface_activity(
    temp_notifications_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del temp_notifications_dir
    append_notification(
        make_notification(
            "resurfaced",
            minutes_ago=60,
            resurfaced_at=timestamp(0),
        )
    )

    handle_notify_list(list_args(json=False))

    out = capsys.readouterr().out
    assert "ID\tAGE\tRESURFACED\tSENDER" in out
    assert "resurfaced" in out


def test_show_json_and_markdown(
    temp_notifications_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del temp_notifications_dir
    append_notification(
        make_notification(
            "target",
            sender="axe",
            icon="🚨",
            color="#FF5F5F",
            notes=["1 error"],
            files=[str(Path.home() / ".sase" / "axe" / "digest.txt")],
            tags=["digest", "error"],
            action="ViewErrorReport",
            action_data={
                "error_report_path": str(Path.home() / ".sase" / "axe" / "digest.txt")
            },
            resurfaced_at=timestamp(0),
        )
    )

    handle_notify_show(show_args(format="json"))
    payload = json.loads(capsys.readouterr().out)
    assert payload["id"] == "target"
    assert payload["icon"] == "🚨"
    assert payload["color"] == "#FF5F5F"
    assert payload["tags"] == ["digest", "error"]
    assert payload["action_data"]["error_report_path"].endswith("digest.txt")
    assert payload["resurfaced_at"] is not None

    handle_notify_show(show_args(format="markdown"))
    out = capsys.readouterr().out
    assert "# Notification target" in out
    assert "- icon: 🚨" in out
    assert "- color: `#FF5F5F`" in out
    assert "ViewErrorReport" in out
    assert "`digest`, `error`" in out
    assert "error_report_path" in out
    assert "digest.txt" in out
    assert "resurfaced_at" in out


def test_show_unknown_id_exits_2(
    temp_notifications_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del temp_notifications_dir
    with pytest.raises(SystemExit) as excinfo:
        handle_notify_show(show_args(id="missing"))

    assert excinfo.value.code == 2
    assert "not found" in capsys.readouterr().err


def test_list_store_read_failure_exits_1(capsys: pytest.CaptureFixture[str]) -> None:
    with patch(
        "sase.notifications.cli_list.list_notification_infos",
        side_effect=OSError("boom"),
    ):
        with pytest.raises(SystemExit) as excinfo:
            handle_notify_list(list_args(json=True))

    assert excinfo.value.code == 1
    assert "cannot read notifications" in capsys.readouterr().err


def test_show_store_read_failure_exits_1(capsys: pytest.CaptureFixture[str]) -> None:
    with patch(
        "sase.notifications.cli_show.resolve_notification_ref",
        side_effect=OSError("boom"),
    ):
        with pytest.raises(SystemExit) as excinfo:
            handle_notify_show(show_args(id="target"))

    assert excinfo.value.code == 1
    assert "cannot read notifications" in capsys.readouterr().err


def test_notify_skill_recommended_flow_lists_shows_and_reads_axe_digest(
    temp_notifications_dir: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del temp_notifications_dir
    digest_path = tmp_path / "axe_digest.txt"
    digest_path.write_text(
        "Axe error digest\n\n- bgcmd hooks failed with exit code 1\n",
        encoding="utf-8",
    )

    append_notification(
        make_notification(
            "regular",
            minutes_ago=15,
            sender="sync",
            notes=["regular notification"],
        )
    )
    append_notification(
        make_notification(
            "axe-digest",
            minutes_ago=5,
            sender="axe",
            notes=["1 error(s) in the last hour"],
            files=[str(digest_path)],
            tags=["digest"],
            action="ViewErrorReport",
            action_data={"error_report_path": str(digest_path)},
            read=False,
        )
    )
    append_notification(
        make_notification(
            "dismissed-axe",
            minutes_ago=1,
            sender="axe",
            notes=["old dismissed digest"],
            dismissed=True,
        )
    )

    parser = create_parser()
    list_args_ = parser.parse_args(
        ["notify", "list", "-j", "-l", "20", "--sender", "axe", "--tag", "digest"]
    )
    with pytest.raises(SystemExit) as excinfo:
        handle_notify_command(list_args_)
    assert excinfo.value.code == 0

    rows = json.loads(capsys.readouterr().out)
    assert [row["id"] for row in rows] == ["axe-digest"]
    axe_row = rows[0]
    assert axe_row["priority"] is True
    assert axe_row["tags"] == ["digest"]
    assert axe_row["read"] is False
    assert axe_row["files"] == [str(digest_path)]
    assert axe_row["action_data"]["error_report_path"] == str(digest_path)

    show_args_ = parser.parse_args(["notify", "show", "--id", axe_row["id"]])
    with pytest.raises(SystemExit) as excinfo:
        handle_notify_command(show_args_)
    assert excinfo.value.code == 0

    markdown = capsys.readouterr().out
    assert "# Notification axe-digest" in markdown
    assert "1 error(s) in the last hour" in markdown
    assert str(digest_path) in markdown
    assert "ViewErrorReport" in markdown

    digest_text = Path(axe_row["action_data"]["error_report_path"]).read_text(
        encoding="utf-8"
    )
    assert "bgcmd hooks failed with exit code 1" in digest_text

    all_args = parser.parse_args(
        ["notify", "list", "-j", "-l", "20", "--sender", "axe", "--all"]
    )
    with pytest.raises(SystemExit) as excinfo:
        handle_notify_command(all_args)
    assert excinfo.value.code == 0

    all_rows = json.loads(capsys.readouterr().out)
    assert [row["id"] for row in all_rows] == ["dismissed-axe", "axe-digest"]
