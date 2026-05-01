"""Notification-store contract fixtures for the Rust migration."""

from __future__ import annotations

import builtins
import dataclasses
import shutil
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.tui.actions.agents._killing_utils import dismiss_notifications_for_agents
from sase.notifications import is_priority
from sase.notifications.models import Notification
from sase.notifications.store import (
    append_notification,
    load_notifications,
    rewrite_notifications,
)
from tests.fixtures.notifications import generate as notification_fixtures

FIXTURE_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "notifications"
    / "store_contract.jsonl"
)


@pytest.fixture()
def notification_store_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the notification store at a test-local JSONL file."""
    notifications_dir = tmp_path / "notifications"
    notifications_file = notifications_dir / "notifications.jsonl"
    monkeypatch.setattr(
        "sase.notifications.store.NOTIFICATIONS_DIR", str(notifications_dir)
    )
    monkeypatch.setattr(
        "sase.notifications.store.NOTIFICATIONS_FILE", str(notifications_file)
    )
    return notifications_file


def _copy_contract_fixture(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FIXTURE_PATH, path)


def _ids(notifications: list[Notification]) -> set[str]:
    return {notification.id for notification in notifications}


def test_contract_fixture_loads_valid_rows_and_defaults_legacy_fields(
    notification_store_file: Path,
) -> None:
    _copy_contract_fixture(notification_store_file)

    active = load_notifications()
    all_notifications = load_notifications(include_dismissed=True)

    assert "dismissed-row" not in _ids(active)
    assert "dismissed-row" in _ids(all_notifications)
    assert "missing-required" not in _ids(all_notifications)
    assert len(active) == 12
    assert len(all_notifications) == 13

    legacy = next(n for n in all_notifications if n.id == "legacy-minimal")
    assert legacy.notes == []
    assert legacy.files == []
    assert legacy.action_data == {}
    assert legacy.read is False
    assert legacy.dismissed is False
    assert legacy.silent is False
    assert legacy.muted is False
    assert legacy.snooze_until is None


def test_contract_fixture_covers_priority_classifier_inputs(
    notification_store_file: Path,
) -> None:
    _copy_contract_fixture(notification_store_file)

    by_id = {n.id: n for n in load_notifications(include_dismissed=True)}

    assert is_priority(by_id["priority-plan"])
    assert is_priority(by_id["priority-question"])
    assert is_priority(by_id["priority-mentor"])
    assert is_priority(by_id["priority-axe"])
    assert is_priority(by_id["priority-crs"])
    assert is_priority(by_id["priority-user-agent-error"])
    assert not is_priority(by_id["agent-jump-no-suffix"])
    assert not is_priority(by_id["silent-row"])


def test_contract_fixture_covers_agent_linked_dismissal_shapes(
    notification_store_file: Path,
) -> None:
    _copy_contract_fixture(notification_store_file)

    agent = SimpleNamespace(cl_name="sase-1n-demo", raw_suffix="20260430121530")
    dismissed_count = dismiss_notifications_for_agents([agent])

    all_notifications = load_notifications(include_dismissed=True)
    dismissed_ids = {n.id for n in all_notifications if n.dismissed}
    assert dismissed_count == 4
    assert {
        "muted-row",
        "snoozed-row",
        "priority-plan",
        "agent-jump-no-suffix",
    } <= dismissed_ids


def test_fixture_generator_matches_committed_contract_fixture(tmp_path: Path) -> None:
    generated = tmp_path / "generated.jsonl"
    notification_fixtures.write_jsonl(generated, notification_fixtures.fixture_rows())

    assert generated.read_text(encoding="utf-8") == FIXTURE_PATH.read_text(
        encoding="utf-8"
    )


def test_synthetic_corpus_generator_has_expected_size_and_variety(
    tmp_path: Path,
) -> None:
    generated = tmp_path / "synthetic.jsonl"
    notification_fixtures.write_jsonl(
        generated, notification_fixtures.synthetic_rows(5_000)
    )

    lines = generated.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 5_000
    assert any('"action": "PlanApproval"' in line for line in lines)
    assert any('"action": "JumpToAgent"' in line for line in lines)
    assert any('"dismissed": true' in line for line in lines)
    assert any('"snooze_until": "2026-04-30T13:00:00+00:00"' in line for line in lines)


def test_rewrite_contract_does_not_use_python_truncate_before_lock(
    notification_store_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    existing = Notification(
        id="existing",
        timestamp="2026-04-30T12:00:00+00:00",
        sender="test",
    )
    append_notification(existing)

    replacement = dataclasses.replace(existing, read=True)
    original_open = builtins.open

    def delayed_truncating_open(file: Any, mode: str = "r", *args: Any, **kwargs: Any):
        if Path(file) == notification_store_file and mode.startswith("w"):
            raise AssertionError("notification rewrite used Python truncate mode")
        return original_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", delayed_truncating_open)

    rewrite_notifications([replacement])
    loaded = load_notifications(include_dismissed=True)

    assert loaded == [replacement]


def test_append_plus_rewrite_contract_preserves_valid_jsonl_after_race(
    notification_store_file: Path,
) -> None:
    first = Notification(
        id="first",
        timestamp="2026-04-30T12:00:00+00:00",
        sender="test",
    )
    append_notification(first)
    rewritten = dataclasses.replace(first, read=True)

    def append_second() -> None:
        time.sleep(0.01)
        append_notification(
            Notification(
                id="second",
                timestamp="2026-04-30T12:00:01+00:00",
                sender="test",
            )
        )

    writer = threading.Thread(target=rewrite_notifications, args=([rewritten],))
    appender = threading.Thread(target=append_second)
    writer.start()
    appender.start()
    writer.join(timeout=5)
    appender.join(timeout=5)

    loaded = load_notifications(include_dismissed=True)
    assert all(isinstance(n, Notification) for n in loaded)
    assert _ids(loaded) <= {"first", "second"}
