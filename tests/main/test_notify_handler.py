"""Tests for the 'sase notify' parser, handler, and CLI subcommands."""

from __future__ import annotations

import argparse
import io
import json
import sys
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.core.time import get_timezone
from sase.main.notify_handler import handle_notify_command
from sase.main.parser import create_parser
from sase.notifications.cli_list import handle_notify_list
from sase.notifications.cli_show import handle_notify_show
from sase.notifications.models import Notification
from sase.notifications.store import append_notification, load_notifications


@pytest.fixture()
def temp_notifications_dir(tmp_path: Path) -> Iterator[Path]:
    notifications_dir = str(tmp_path / "notifications")
    notifications_file = str(tmp_path / "notifications" / "notifications.jsonl")
    with (
        patch("sase.notifications.store.NOTIFICATIONS_DIR", notifications_dir),
        patch("sase.notifications.store.NOTIFICATIONS_FILE", notifications_file),
        patch.dict("sase.notifications.store._LOAD_CACHE", {}, clear=True),
    ):
        yield tmp_path


def _timestamp(minutes_ago: int) -> str:
    return (datetime.now(get_timezone()) - timedelta(minutes=minutes_ago)).isoformat()


def _make_notification(
    notification_id: str,
    *,
    minutes_ago: int = 0,
    sender: str = "test",
    notes: list[str] | None = None,
    files: list[str] | None = None,
    action: str | None = None,
    action_data: dict[str, str] | None = None,
    read: bool = False,
    dismissed: bool = False,
) -> Notification:
    return Notification(
        id=notification_id,
        timestamp=_timestamp(minutes_ago),
        sender=sender,
        notes=notes or [],
        files=files or [],
        action=action,
        action_data=action_data or {},
        read=read,
        dismissed=dismissed,
    )


def _list_args(**overrides: object) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "json": False,
        "limit": 20,
        "query": None,
        "sender": None,
        "unread": False,
        "all": False,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _show_args(**overrides: object) -> argparse.Namespace:
    defaults: dict[str, object] = {"id": "target", "format": "markdown"}
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_parser_preserves_legacy_bare_notify_create() -> None:
    parser = create_parser()
    args = parser.parse_args(["notify", "--sender", "axe"])
    assert args.command == "notify"
    assert args.notify_subcommand is None
    assert args.sender == "axe"


def test_parser_registers_notify_list_options() -> None:
    parser = create_parser()
    args = parser.parse_args(
        ["notify", "list", "-j", "-l", "5", "-q", "digest", "-s", "axe", "-u", "-a"]
    )
    assert args.command == "notify"
    assert args.notify_subcommand == "list"
    assert args.json is True
    assert args.limit == 5
    assert args.query == "digest"
    assert args.sender == "axe"
    assert args.unread is True
    assert args.all is True


def test_parser_registers_notify_show_options() -> None:
    parser = create_parser()
    args = parser.parse_args(["notify", "show", "--id", "n1", "-f", "json"])
    assert args.notify_subcommand == "show"
    assert args.id == "n1"
    assert args.format == "json"

    with pytest.raises(SystemExit):
        parser.parse_args(["notify", "show"])
    with pytest.raises(SystemExit):
        parser.parse_args(["notify", "show", "--id", "n1", "-f", "raw"])


def test_parser_registers_explicit_create_alias() -> None:
    parser = create_parser()
    args = parser.parse_args(["notify", "create", "-s", "worker"])
    assert args.notify_subcommand == "create"
    assert args.sender == "worker"


def test_legacy_create_path_still_writes_notification(
    temp_notifications_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del temp_notifications_dir
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(json.dumps({"sender": "json", "notes": ["created"]})),
    )

    with pytest.raises(SystemExit) as excinfo:
        handle_notify_command(argparse.Namespace(notify_subcommand=None, sender=None))

    assert excinfo.value.code == 0
    notification_id = capsys.readouterr().out.strip()
    notifications = load_notifications(include_dismissed=True)
    assert len(notifications) == 1
    assert notifications[0].id == notification_id
    assert notifications[0].sender == "json"
    assert notifications[0].notes == ["created"]


def test_create_sender_flag_overrides_stdin(
    temp_notifications_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del temp_notifications_dir
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"sender": "json"})))

    with pytest.raises(SystemExit) as excinfo:
        handle_notify_command(
            argparse.Namespace(notify_subcommand="create", sender="cli")
        )

    assert excinfo.value.code == 0
    assert load_notifications(include_dismissed=True)[0].sender == "cli"


def test_notify_command_dispatches_list(
    temp_notifications_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del temp_notifications_dir
    append_notification(_make_notification("target"))

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
            _make_notification(
                f"n{idx}",
                minutes_ago=25 - idx,
                sender="axe" if idx % 2 == 0 else "sync",
                notes=[f"digest {idx}"],
                read=idx % 3 == 0,
            )
        )

    handle_notify_list(_list_args(json=True, query="digest", sender="axe", unread=True))

    rows = json.loads(capsys.readouterr().out)
    assert len(rows) <= 20
    assert all(row["sender"] == "axe" for row in rows)
    assert all(row["read"] is False for row in rows)
    assert list(rows[0]) == [
        "id",
        "timestamp",
        "age",
        "sender",
        "priority",
        "notes",
        "files",
        "action",
        "action_data",
        "read",
        "dismissed",
        "silent",
        "muted",
        "snooze_until",
    ]


def test_list_all_includes_dismissed(
    temp_notifications_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del temp_notifications_dir
    append_notification(_make_notification("active"))
    append_notification(_make_notification("dismissed", dismissed=True))

    handle_notify_list(_list_args(json=True))
    rows = json.loads(capsys.readouterr().out)
    assert [row["id"] for row in rows] == ["active"]

    handle_notify_list(_list_args(json=True, all=True))
    rows = json.loads(capsys.readouterr().out)
    assert {row["id"] for row in rows} == {"active", "dismissed"}


def test_list_pretty_empty(capsys: pytest.CaptureFixture[str]) -> None:
    with patch("sase.notifications.cli_list.list_notification_infos", return_value=[]):
        handle_notify_list(_list_args(json=False))

    out = capsys.readouterr().out
    assert "Notifications (0)" in out
    assert "No notifications found" in out


def test_show_json_and_markdown(
    temp_notifications_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del temp_notifications_dir
    append_notification(
        _make_notification(
            "target",
            sender="axe",
            notes=["1 error"],
            files=[str(Path.home() / ".sase" / "axe" / "digest.txt")],
            action="ViewErrorReport",
            action_data={
                "error_report_path": str(Path.home() / ".sase" / "axe" / "digest.txt")
            },
        )
    )

    handle_notify_show(_show_args(format="json"))
    payload = json.loads(capsys.readouterr().out)
    assert payload["id"] == "target"
    assert payload["action_data"]["error_report_path"].endswith("digest.txt")

    handle_notify_show(_show_args(format="markdown"))
    out = capsys.readouterr().out
    assert "# Notification target" in out
    assert "ViewErrorReport" in out
    assert "error_report_path" in out
    assert "digest.txt" in out


def test_show_unknown_id_exits_2(
    temp_notifications_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del temp_notifications_dir
    with pytest.raises(SystemExit) as excinfo:
        handle_notify_show(_show_args(id="missing"))

    assert excinfo.value.code == 2
    assert "not found" in capsys.readouterr().err


def test_list_store_read_failure_exits_1(capsys: pytest.CaptureFixture[str]) -> None:
    with patch(
        "sase.notifications.cli_list.list_notification_infos",
        side_effect=OSError("boom"),
    ):
        with pytest.raises(SystemExit) as excinfo:
            handle_notify_list(_list_args(json=True))

    assert excinfo.value.code == 1
    assert "cannot read notifications" in capsys.readouterr().err


def test_show_store_read_failure_exits_1(capsys: pytest.CaptureFixture[str]) -> None:
    with patch(
        "sase.notifications.cli_show.resolve_notification_ref",
        side_effect=OSError("boom"),
    ):
        with pytest.raises(SystemExit) as excinfo:
            handle_notify_show(_show_args(id="target"))

    assert excinfo.value.code == 1
    assert "cannot read notifications" in capsys.readouterr().err
