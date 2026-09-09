"""Tests for ``sase notify create`` behavior."""

from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

import pytest

from sase.main.notify_handler import handle_notify_command
from sase.notifications.store import load_notifications

pytest_plugins = ["tests.main.notify_handler_fixtures"]


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


def test_create_with_dedup_key_creates_then_plus_ones(
    temp_notifications_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del temp_notifications_dir
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(json.dumps({"sender": "ci_watch", "notes": ["CI failure: a"]})),
    )

    with pytest.raises(SystemExit) as excinfo:
        handle_notify_command(
            argparse.Namespace(
                notify_subcommand="create",
                sender=None,
                tag=None,
                dedup_key="combo",
                plus_one_note="first",
                supersedes=None,
            )
        )
    assert excinfo.value.code == 0
    outcome = json.loads(capsys.readouterr().out)
    assert outcome["action"] == "created"
    created_id = outcome["id"]

    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(json.dumps({"sender": "ci_watch", "notes": ["ignored"]})),
    )
    with pytest.raises(SystemExit) as excinfo:
        handle_notify_command(
            argparse.Namespace(
                notify_subcommand="create",
                sender=None,
                tag=None,
                dedup_key="combo",
                plus_one_note="second",
                supersedes=None,
            )
        )
    assert excinfo.value.code == 0
    outcome2 = json.loads(capsys.readouterr().out)
    assert outcome2 == {"action": "plus_oned", "id": created_id}

    notifications = load_notifications(include_dismissed=True)
    assert len(notifications) == 1
    # The initial create discards plus_one_note (nothing to +1 yet); only the
    # second call, which matches the stored dedup_key, appends a +1 entry.
    assert [plus_one.note for plus_one in notifications[0].plus_ones] == ["second"]


def test_create_dedup_key_requires_plus_one_note(
    temp_notifications_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del temp_notifications_dir
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"sender": "ci_watch"})))

    with pytest.raises(SystemExit) as excinfo:
        handle_notify_command(
            argparse.Namespace(
                notify_subcommand="create",
                sender=None,
                tag=None,
                dedup_key="combo",
                plus_one_note=None,
                supersedes=None,
            )
        )
    assert excinfo.value.code == 1
    assert "requires -p" in capsys.readouterr().err
    assert load_notifications(include_dismissed=True) == []


def test_create_supersedes_dismisses_old_row(
    temp_notifications_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del temp_notifications_dir
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(json.dumps({"sender": "ci_watch", "notes": ["a"]})),
    )
    with pytest.raises(SystemExit):
        handle_notify_command(
            argparse.Namespace(
                notify_subcommand="create",
                sender=None,
                tag=None,
                dedup_key="combo-a",
                plus_one_note="first",
                supersedes=None,
            )
        )
    capsys.readouterr()

    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(json.dumps({"sender": "ci_watch", "notes": ["a+b"]})),
    )
    with pytest.raises(SystemExit):
        handle_notify_command(
            argparse.Namespace(
                notify_subcommand="create",
                sender=None,
                tag=None,
                dedup_key="combo-ab",
                plus_one_note="new repo b failing",
                supersedes="combo-a",
            )
        )
    outcome = json.loads(capsys.readouterr().out)
    assert outcome["action"] == "created"

    notifications = load_notifications(include_dismissed=True)
    by_key = {n.dedup_key: n for n in notifications}
    assert by_key["combo-a"].dismissed is True
    assert by_key["combo-a"].plus_ones[-1].note.startswith("superseded by")
    assert by_key["combo-ab"].dismissed is False
