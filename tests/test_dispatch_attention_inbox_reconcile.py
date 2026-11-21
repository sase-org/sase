"""Absence, concurrency, fetch, and payload tests for the remote attention inbox.

Split from ``tests.test_dispatch_attention_inbox``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sase.dispatch import attention_inbox
from sase.dispatch.federation import FederationConfig, FederationWorkerSettings
from sase.notifications.models import Notification
from sase.notifications.store import load_notifications
from tests._dispatch_attention_inbox_helpers import (
    INSTALLATION_ID,
    OBSERVED_AT,
    entry,
    inbox_notification_store_file,  # noqa: F401 (registers the notification_store_file fixture)
    response,
)

__all__ = [
    "test_attention_inventory_absence_from_fresh_host_dismisses_stale_request",
    "test_attention_inventory_incomplete_page_does_not_settle_absences",
    "test_attention_inventory_new_revision_supersedes_old_decision",
    "test_attention_inventory_unavailable_host_does_not_settle_absences",
    "test_consecutive_polls_differing_only_in_observed_at_skip_rewrite",
    "test_fetch_attention_inventory_skips_facade_without_configured_machines",
    "test_reconcile_atomic_write_preserves_concurrent_remote_row_dismissal",
    "test_reconcile_delta_write_preserves_concurrent_completion_dismissal",
    "test_remote_attention_payload_is_string_encoded",
]


def _unavailable_response() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "operation": "attention_inventory",
        "configured_hosts": 1,
        "hosts": [
            {
                "schema_version": 1,
                "alias": "apollo",
                "installation_id": INSTALLATION_ID,
                "status": "error",
                "cached": False,
                "payload": None,
                "error": {"message": "offline"},
            }
        ],
    }


def test_attention_inventory_incomplete_page_does_not_settle_absences(
    notification_store_file: Path,
) -> None:
    del notification_store_file
    attention_inbox.reconcile_remote_attention_inbox(
        response([entry()]),
        now_unix=OBSERVED_AT,
    )

    outcome = attention_inbox.reconcile_remote_attention_inbox(
        response([], has_more=True, next_cursor="off:100"),
        now_unix=OBSERVED_AT,
    )

    assert outcome.changed is False
    [active] = load_notifications()
    assert active.dismissed is False


def test_attention_inventory_new_revision_supersedes_old_decision(
    notification_store_file: Path,
) -> None:
    del notification_store_file
    attention_inbox.reconcile_remote_attention_inbox(
        response([entry(revision=1)]),
        now_unix=OBSERVED_AT,
    )

    outcome = attention_inbox.reconcile_remote_attention_inbox(
        response([entry(revision=2)]),
        now_unix=OBSERVED_AT,
    )

    assert outcome.created == 0
    assert outcome.updated == 1
    assert outcome.dismissed == 0
    [active] = load_notifications()
    assert (
        active.action_data[attention_inbox.REMOTE_ATTENTION_REVISION_ACTION_DATA_KEY]
        == "2"
    )
    all_rows = load_notifications(include_dismissed=True)
    assert len(all_rows) == 1


def test_attention_inventory_absence_from_fresh_host_dismisses_stale_request(
    notification_store_file: Path,
) -> None:
    del notification_store_file
    attention_inbox.reconcile_remote_attention_inbox(
        response([entry()]),
        now_unix=OBSERVED_AT,
    )

    outcome = attention_inbox.reconcile_remote_attention_inbox(
        response([]),
        now_unix=OBSERVED_AT,
    )

    assert outcome.dismissed == 1
    assert load_notifications() == []
    [dismissed] = load_notifications(include_dismissed=True)
    assert dismissed.dismissed is True


def test_attention_inventory_unavailable_host_does_not_settle_absences(
    notification_store_file: Path,
) -> None:
    del notification_store_file
    attention_inbox.reconcile_remote_attention_inbox(
        response([entry()]),
        now_unix=OBSERVED_AT,
    )

    outcome = attention_inbox.reconcile_remote_attention_inbox(
        _unavailable_response(),
        now_unix=OBSERVED_AT,
    )

    assert outcome.changed is False
    [active] = load_notifications()
    assert active.dismissed is False


def test_fetch_attention_inventory_skips_facade_without_configured_machines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    empty_config = FederationConfig(
        worker=FederationWorkerSettings(enabled=True),
        hosts=(),
    )
    monkeypatch.setattr(
        attention_inbox,
        "load_federation_config",
        lambda: empty_config,
    )
    monkeypatch.setattr(
        attention_inbox,
        "build_federation_facade",
        lambda _config: pytest.fail("zero-machine inventory must not build a facade"),
    )

    result = attention_inbox.fetch_remote_attention_inventory()

    assert result["operation"] == "attention_inventory"
    assert result["disabled"] is True
    assert result["hosts"] == []


def test_reconcile_delta_write_preserves_concurrent_completion_dismissal(
    notification_store_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del notification_store_file
    from sase.notifications import store as notification_store

    completion = Notification(
        id="completion-00000001",
        timestamp="2026-09-30T00:00:00+00:00",
        sender="agent-completion",
        notes=["agent finished"],
    )
    notification_store.append_notification(completion)
    attention_inbox.reconcile_remote_attention_inbox(
        response([entry(revision=1)]),
        now_unix=OBSERVED_AT,
    )

    real_load = notification_store.load_notifications

    def _interleaving_load(*, include_dismissed: bool = False):  # type: ignore[no-untyped-def]
        snapshot = real_load(include_dismissed=include_dismissed)
        notification_store.mark_dismissed(completion.id)
        return snapshot

    monkeypatch.setattr(attention_inbox, "load_notifications", _interleaving_load)

    outcome = attention_inbox.reconcile_remote_attention_inbox(
        response([entry(revision=2)]),
        now_unix=OBSERVED_AT,
    )

    assert outcome.updated == 1
    [dismissed] = [
        row
        for row in notification_store.load_notifications(include_dismissed=True)
        if row.id == completion.id
    ]
    assert dismissed.dismissed is True


def test_consecutive_polls_differing_only_in_observed_at_skip_rewrite(
    notification_store_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del notification_store_file

    reconcile_calls: list[list[Any]] = []
    real_reconcile = attention_inbox.reconcile_notification_rows

    def _spying_reconcile(rows, **kwargs):  # type: ignore[no-untyped-def]
        reconcile_calls.append(list(rows))
        return real_reconcile(rows, **kwargs)

    monkeypatch.setattr(
        attention_inbox, "reconcile_notification_rows", _spying_reconcile
    )

    attention_inbox.reconcile_remote_attention_inbox(
        response([entry()]),
        now_unix=OBSERVED_AT,
    )
    assert len(reconcile_calls) == 1
    assert len(reconcile_calls[0]) == 1

    second = response([entry()])
    second["hosts"][0]["payload"]["observed_at_unix"] = OBSERVED_AT + 60.0
    outcome = attention_inbox.reconcile_remote_attention_inbox(
        second,
        now_unix=OBSERVED_AT + 60.0,
    )

    assert outcome.updated == 0
    assert outcome.changed is False
    assert len(reconcile_calls) == 1


def test_reconcile_atomic_write_preserves_concurrent_remote_row_dismissal(
    notification_store_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del notification_store_file
    from sase.notifications import store as notification_store

    attention_inbox.reconcile_remote_attention_inbox(
        response([entry(revision=1)]),
        now_unix=OBSERVED_AT,
    )
    [seeded] = [
        row
        for row in notification_store.load_notifications(include_dismissed=True)
        if row.sender == attention_inbox.REMOTE_ATTENTION_NOTIFICATION_SENDER
    ]

    real_load = notification_store.load_notifications

    def _interleaving_load(*, include_dismissed: bool = False):  # type: ignore[no-untyped-def]
        snapshot = real_load(include_dismissed=include_dismissed)
        notification_store.mark_dismissed(seeded.id)
        return snapshot

    monkeypatch.setattr(attention_inbox, "load_notifications", _interleaving_load)

    refreshed_entry = entry(revision=1)
    refreshed_entry["title"] = "Approve deploy v2"
    outcome = attention_inbox.reconcile_remote_attention_inbox(
        response([refreshed_entry]),
        now_unix=OBSERVED_AT + 60.0,
    )

    assert outcome.updated == 1
    [dismissed] = [
        row
        for row in notification_store.load_notifications(include_dismissed=True)
        if row.id == seeded.id
    ]
    assert dismissed.dismissed is True
    assert (
        dismissed.action_data.get(
            attention_inbox.REMOTE_ATTENTION_AUTO_DISMISSED_ACTION_DATA_KEY
        )
        is None
    )


def test_remote_attention_payload_is_string_encoded(
    notification_store_file: Path,
) -> None:
    del notification_store_file
    attention_inbox.reconcile_remote_attention_inbox(
        response([entry(kind="question", request_id="question-0001")]),
        now_unix=OBSERVED_AT,
    )

    [notification] = load_notifications()
    raw_entry = notification.action_data[
        attention_inbox.REMOTE_ATTENTION_ENTRY_ACTION_DATA_KEY
    ]
    assert isinstance(raw_entry, str)
    assert json.loads(raw_entry)["kind"] == "question"
