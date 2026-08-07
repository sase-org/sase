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
    icon: str | None = None,
    color: str | None = None,
    notes: list[str] | None = None,
    files: list[str] | None = None,
    tags: list[str] | None = None,
    action: str | None = None,
    action_data: dict[str, str] | None = None,
    read: bool = False,
    dismissed: bool = False,
    resurfaced_at: str | None = None,
) -> Notification:
    return Notification(
        id=notification_id,
        timestamp=_timestamp(minutes_ago),
        sender=sender,
        icon=icon,
        color=color,
        notes=notes or [],
        files=files or [],
        tags=tags or [],
        action=action,
        action_data=action_data or {},
        read=read,
        dismissed=dismissed,
        resurfaced_at=resurfaced_at,
    )


def _list_args(**overrides: object) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "json": False,
        "limit": 20,
        "query": None,
        "sender": None,
        "unread": False,
        "all": False,
        "tag": None,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _show_args(**overrides: object) -> argparse.Namespace:
    defaults: dict[str, object] = {"id": "target", "format": "markdown"}
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_parser_defaults_bare_notify_to_list() -> None:
    parser = create_parser()
    args = parser.parse_args(["notify"])
    assert args.command == "notify"
    assert args.notify_subcommand == "list"
    assert args.json is False
    assert args.limit == 20
    assert args.query is None
    assert args.sender is None
    assert args.tag is None
    assert args.unread is False
    assert args.all is False


def test_parser_registers_notify_list_options() -> None:
    parser = create_parser()
    args = parser.parse_args(
        [
            "notify",
            "list",
            "-j",
            "-l",
            "5",
            "-q",
            "digest",
            "-s",
            "axe",
            "-u",
            "-a",
            "--tag",
            "done",
        ]
    )
    assert args.command == "notify"
    assert args.notify_subcommand == "list"
    assert args.json is True
    assert args.limit == 5
    assert args.query == "digest"
    assert args.sender == "axe"
    assert args.unread is True
    assert args.all is True
    assert args.tag == "done"


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
    args = parser.parse_args(["notify", "create", "-s", "worker", "-t", "Review"])
    assert args.notify_subcommand == "create"
    assert args.sender == "worker"
    assert args.tag == ["Review"]


def test_parser_registers_gate_create_wait_options_and_help() -> None:
    parser = create_parser()
    create_args = parser.parse_args(
        [
            "gate",
            "create",
            "--origin-agent",
            "filer.agent",
            "--panel",
            "reviews",
            "--sender",
            "worker",
            "--tag",
            "review",
        ]
    )
    assert create_args.command == "gate"
    assert create_args.gate_subcommand == "create"
    assert create_args.origin_agent == "filer.agent"
    assert create_args.panel == "reviews"
    assert create_args.sender == "worker"
    assert create_args.tag == ["review"]

    args = parser.parse_args(
        [
            "gate",
            "wait",
            "--id",
            "custom-123",
            "-j",
            "--kind",
            "custom",
            "-t",
            "30",
        ]
    )

    assert args.gate_subcommand == "wait"
    assert args.id == "custom-123"
    assert args.json is True
    assert args.kind == "custom"
    assert args.timeout == 30.0

    gate_parser = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    ).choices["gate"]
    gate_subparsers = next(
        action
        for action in gate_parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    assert list(gate_subparsers.choices) == [
        "act",
        "answer",
        "create",
        "show",
        "wait",
    ]
    create_help = gate_subparsers.choices["create"].format_help()
    assert "--origin-agent" in create_help
    assert "--panel" in create_help
    assert "sase gate create --panel deployments" in create_help
    wait_subparsers = next(
        action
        for action in gate_parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    wait_help = wait_subparsers.choices["wait"].format_help()
    assert "--id REQUEST_ID" in wait_help
    assert "--json" in wait_help
    assert "--kind" in wait_help
    assert "--timeout SECONDS" in wait_help
    assert "answered" in wait_help
    assert "cancelled" in wait_help
    assert "timeout" in wait_help


def test_parser_retires_notify_gate_entrypoints() -> None:
    parser = create_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["notify", "create", "--gate"])
    with pytest.raises(SystemExit):
        parser.parse_args(["notify", "wait", "--id", "custom-123", "--kind", "custom"])


def test_explicit_create_path_writes_notification(
    temp_notifications_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del temp_notifications_dir
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(
            json.dumps(
                {
                    "sender": "json",
                    "icon": "✅",
                    "color": "#AABBCC",
                    "notes": ["created"],
                }
            )
        ),
    )

    with pytest.raises(SystemExit) as excinfo:
        handle_notify_command(
            argparse.Namespace(notify_subcommand="create", sender=None, tag=None)
        )

    assert excinfo.value.code == 0
    notification_id = capsys.readouterr().out.strip()
    notifications = load_notifications(include_dismissed=True)
    assert len(notifications) == 1
    assert notifications[0].id == notification_id
    assert notifications[0].sender == "json"
    assert notifications[0].icon == "✅"
    assert notifications[0].color == "#AABBCC"
    assert notifications[0].notes == ["created"]


def test_raw_create_rejects_invalid_icon(
    temp_notifications_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del temp_notifications_dir
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(json.dumps({"sender": "json", "icon": "✅🚀"})),
    )

    with pytest.raises(SystemExit) as excinfo:
        handle_notify_command(
            argparse.Namespace(notify_subcommand="create", sender=None, tag=None)
        )

    assert excinfo.value.code == 1
    assert "invalid_icon" in capsys.readouterr().err
    assert load_notifications(include_dismissed=True) == []


def test_raw_create_rejects_a_malformed_color(
    temp_notifications_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Junk stored now would render as an unstyled chip forever after."""
    del temp_notifications_dir
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(json.dumps({"sender": "json", "color": "red"})),
    )

    with pytest.raises(SystemExit) as excinfo:
        handle_notify_command(
            argparse.Namespace(notify_subcommand="create", sender=None, tag=None)
        )

    assert excinfo.value.code == 1
    assert "invalid_color" in capsys.readouterr().err
    assert load_notifications(include_dismissed=True) == []


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


def test_create_combines_json_and_cli_tags(
    temp_notifications_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del temp_notifications_dir
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(json.dumps({"sender": "json", "tags": [" Done ", "Review"]})),
    )

    with pytest.raises(SystemExit) as excinfo:
        handle_notify_command(
            argparse.Namespace(
                notify_subcommand="create",
                sender=None,
                tag=["review", "CLI"],
            )
        )

    assert excinfo.value.code == 0
    assert load_notifications(include_dismissed=True)[0].tags == [
        "done",
        "review",
        "cli",
    ]


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


def test_list_pretty_exposes_resurface_activity(
    temp_notifications_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del temp_notifications_dir
    append_notification(
        _make_notification(
            "resurfaced",
            minutes_ago=60,
            resurfaced_at=_timestamp(0),
        )
    )

    handle_notify_list(_list_args(json=False))

    out = capsys.readouterr().out
    assert "ID\tAGE\tRESURFACED\tSENDER" in out
    assert "resurfaced" in out


def test_show_json_and_markdown(
    temp_notifications_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del temp_notifications_dir
    append_notification(
        _make_notification(
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
            resurfaced_at=_timestamp(0),
        )
    )

    handle_notify_show(_show_args(format="json"))
    payload = json.loads(capsys.readouterr().out)
    assert payload["id"] == "target"
    assert payload["icon"] == "🚨"
    assert payload["color"] == "#FF5F5F"
    assert payload["tags"] == ["digest", "error"]
    assert payload["action_data"]["error_report_path"].endswith("digest.txt")
    assert payload["resurfaced_at"] is not None

    handle_notify_show(_show_args(format="markdown"))
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
        _make_notification(
            "regular",
            minutes_ago=15,
            sender="sync",
            notes=["regular notification"],
        )
    )
    append_notification(
        _make_notification(
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
        _make_notification(
            "dismissed-axe",
            minutes_ago=1,
            sender="axe",
            notes=["old dismissed digest"],
            dismissed=True,
        )
    )

    parser = create_parser()
    list_args = parser.parse_args(
        ["notify", "list", "-j", "-l", "20", "--sender", "axe", "--tag", "digest"]
    )
    with pytest.raises(SystemExit) as excinfo:
        handle_notify_command(list_args)
    assert excinfo.value.code == 0

    rows = json.loads(capsys.readouterr().out)
    assert [row["id"] for row in rows] == ["axe-digest"]
    axe_row = rows[0]
    assert axe_row["priority"] is True
    assert axe_row["tags"] == ["digest"]
    assert axe_row["read"] is False
    assert axe_row["files"] == [str(digest_path)]
    assert axe_row["action_data"]["error_report_path"] == str(digest_path)

    show_args = parser.parse_args(["notify", "show", "--id", axe_row["id"]])
    with pytest.raises(SystemExit) as excinfo:
        handle_notify_command(show_args)
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
