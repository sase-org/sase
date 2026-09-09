"""Tests for ``sase notify +1`` behavior."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from sase.main.notify_handler import handle_notify_command
from sase.notifications.store import append_notification, load_notifications

from tests.main.notify_handler_helpers import make_notification

pytest_plugins = ["tests.main.notify_handler_fixtures"]


def test_plus_one_by_id_appends_and_prints_id(
    temp_notifications_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del temp_notifications_dir
    append_notification(make_notification("target", sender="ci_watch"))

    with pytest.raises(SystemExit) as excinfo:
        handle_notify_command(
            argparse.Namespace(
                notify_subcommand="+1",
                id="target",
                note="fingerprint changed",
                dedup_key=None,
                sender="ci_watch",
            )
        )

    assert excinfo.value.code == 0
    assert capsys.readouterr().out.strip() == "target"
    notification = load_notifications(include_dismissed=True)[0]
    assert notification.plus_ones[0].note == "fingerprint changed"
    assert notification.plus_ones[0].sender == "ci_watch"


def test_plus_one_by_unique_prefix(
    temp_notifications_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del temp_notifications_dir
    append_notification(make_notification("abcdef01"))

    with pytest.raises(SystemExit) as excinfo:
        handle_notify_command(
            argparse.Namespace(
                notify_subcommand="+1",
                id="abcdef",
                note="churn",
                dedup_key=None,
                sender="worker",
            )
        )
    assert excinfo.value.code == 0
    assert capsys.readouterr().out.strip() == "abcdef01"


def test_plus_one_by_id_no_match_errors(
    temp_notifications_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del temp_notifications_dir
    with pytest.raises(SystemExit) as excinfo:
        handle_notify_command(
            argparse.Namespace(
                notify_subcommand="+1",
                id="missing",
                note="x",
                dedup_key=None,
                sender="worker",
            )
        )
    assert excinfo.value.code == 1
    assert "not found" in capsys.readouterr().err


def test_plus_one_by_dedup_key_no_match_prints_json_and_exits_zero(
    temp_notifications_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del temp_notifications_dir
    with pytest.raises(SystemExit) as excinfo:
        handle_notify_command(
            argparse.Namespace(
                notify_subcommand="+1",
                id=None,
                note="x",
                dedup_key="ci-failure/none",
                sender="ci_watch",
            )
        )
    assert excinfo.value.code == 0
    assert json.loads(capsys.readouterr().out) == {"action": "no_match"}


def test_plus_one_requires_id_or_dedup_key(
    temp_notifications_dir: Path,
) -> None:
    del temp_notifications_dir
    with pytest.raises(SystemExit) as excinfo:
        handle_notify_command(
            argparse.Namespace(
                notify_subcommand="+1",
                id=None,
                note="x",
                dedup_key=None,
                sender="worker",
            )
        )
    assert excinfo.value.code == 1


def test_plus_one_defaults_sender_to_current_user(
    temp_notifications_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del temp_notifications_dir
    append_notification(make_notification("target"))
    monkeypatch.setattr(
        "sase.notifications.cli_plus_one.discover_agent_identity",
        lambda: None,
    )
    monkeypatch.setattr(
        "sase.notifications.cli_plus_one.getpass.getuser", lambda: "bryan"
    )

    with pytest.raises(SystemExit):
        handle_notify_command(
            argparse.Namespace(
                notify_subcommand="+1",
                id="target",
                note="x",
                dedup_key=None,
                sender=None,
            )
        )
    notification = load_notifications(include_dismissed=True)[0]
    assert notification.plus_ones[0].sender == "bryan"


def test_plus_one_does_not_change_activity_cursor_or_state(
    temp_notifications_dir: Path,
) -> None:
    from sase.notifications.models import notification_activity_cursor

    del temp_notifications_dir
    append_notification(make_notification("target", read=True))
    before = load_notifications(include_dismissed=True)[0]
    cursor_before = notification_activity_cursor(before)

    with pytest.raises(SystemExit):
        handle_notify_command(
            argparse.Namespace(
                notify_subcommand="+1",
                id="target",
                note="churn",
                dedup_key=None,
                sender="worker",
            )
        )

    after = load_notifications(include_dismissed=True)[0]
    assert notification_activity_cursor(after) == cursor_before
    assert after.read is True
    assert after.dismissed is False
    assert after.resurfaced_at == before.resurfaced_at
    assert after.timestamp == before.timestamp
