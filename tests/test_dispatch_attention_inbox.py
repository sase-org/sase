from __future__ import annotations

import dataclasses
import json
import uuid
from pathlib import Path
from typing import Any

import pytest

from sase.dispatch import attention_inbox
from sase.dispatch.federation import FederationConfig, FederationWorkerSettings
from sase.notifications.models import Notification
from sase.notifications.store import (
    load_notifications,
    read_unread_completion_index,
    rewrite_notifications,
)

_INSTALLATION_ID = "sase_inst_v1_" + "a" * 64
_OBSERVED_AT = 1_800_000_000.0


@pytest.fixture()
def notification_store_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    notifications_dir = tmp_path / "notifications"
    notifications_file = notifications_dir / "notifications.jsonl"
    monkeypatch.setattr(
        "sase.notifications.store.NOTIFICATIONS_DIR", str(notifications_dir)
    )
    monkeypatch.setattr(
        "sase.notifications.store.NOTIFICATIONS_FILE", str(notifications_file)
    )
    return notifications_file


def _entry(
    *,
    revision: int = 1,
    request_id: str = "gate-00000001",
    kind: str = "gate",
    state: str = "pending",
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": kind,
        "state": state,
        "request_key": {
            "schema_version": 1,
            "origin_installation_id": _INSTALLATION_ID,
            "request_id": request_id,
            "pending_action_prefix": request_id[:8],
        },
        "revision": revision,
        "logical_key": None,
        "logical_locator": None,
        "title": "Approve deploy",
        "summary": "Deployment gate waiting on the owner",
        "options": [{"id": "approve", "label": "Approve"}],
        "feedback_required": False,
        "question_form": None,
        "preview": None,
        "settled_by_host_label": None,
        "settled_response": None,
    }


def _response(
    entries: list[dict[str, Any]],
    *,
    alias: str = "apollo",
    cached: bool = False,
    freshness: str = "fresh",
    partial: bool = False,
    has_more: bool = False,
    next_cursor: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "operation": "attention_inventory",
        "configured_hosts": 1,
        "hosts": [
            {
                "schema_version": 1,
                "alias": alias,
                "installation_id": _INSTALLATION_ID,
                "status": "ok",
                "cached": cached,
                "payload": {
                    "schema_version": 1,
                    "observed_at_unix": _OBSERVED_AT,
                    "freshness": {
                        "schema_version": 1,
                        "freshness": freshness,
                        "partial": partial,
                        "refreshed_at_unix": _OBSERVED_AT,
                        "error": None,
                    },
                    "page": {
                        "schema_version": 1,
                        "entries": entries,
                        "limit": 100,
                        "total_matching_entries": len(entries),
                        "next_cursor": next_cursor,
                        "has_more": has_more,
                    },
                },
                "error": None,
            }
        ],
    }


def _unavailable_response() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "operation": "attention_inventory",
        "configured_hosts": 1,
        "hosts": [
            {
                "schema_version": 1,
                "alias": "apollo",
                "installation_id": _INSTALLATION_ID,
                "status": "error",
                "cached": False,
                "payload": None,
                "error": {"message": "offline"},
            }
        ],
    }


def test_attention_inventory_creates_durable_remote_attention_notification(
    notification_store_file: Path,
) -> None:
    del notification_store_file

    outcome = attention_inbox.reconcile_remote_attention_inbox(
        _response([_entry()]),
        now_unix=_OBSERVED_AT,
    )

    assert outcome.pending == 1
    assert outcome.created == 1
    [notification] = load_notifications()
    assert notification.sender == attention_inbox.REMOTE_ATTENTION_NOTIFICATION_SENDER
    assert notification.action == attention_inbox.REMOTE_ATTENTION_NOTIFICATION_ACTION
    assert notification.action_data["panel"] == "attention"
    assert (
        notification.action_data[
            attention_inbox.REMOTE_ATTENTION_REQUEST_ID_ACTION_DATA_KEY
        ]
        == "gate-00000001"
    )
    assert notification.read is False
    assert notification.dismissed is False
    assert notification.dedup_key == (
        f"remote-attention:{_INSTALLATION_ID}:gate-00000001"
    )
    assert (
        notification.action_data[
            attention_inbox.REMOTE_ATTENTION_REVISION_ACTION_DATA_KEY
        ]
        == "1"
    )

    decoded = attention_inbox.remote_attention_from_notification(notification)
    assert decoded is not None
    alias, entry = decoded
    assert alias == "apollo"
    assert entry["request_key"]["request_id"] == "gate-00000001"


def test_attention_inventory_keeps_user_dismissed_pending_request(
    notification_store_file: Path,
) -> None:
    del notification_store_file
    response = _response([_entry()])
    attention_inbox.reconcile_remote_attention_inbox(response, now_unix=_OBSERVED_AT)
    [notification] = load_notifications()
    rewrite_notifications(
        [
            dataclasses.replace(
                notification,
                read=True,
                dismissed=True,
                muted=True,
                snooze_until="2026-05-12T10:00:00+00:00",
            )
        ]
    )

    outcome = attention_inbox.reconcile_remote_attention_inbox(
        response,
        now_unix=_OBSERVED_AT,
    )

    assert outcome.created == 0
    assert outcome.updated == 0
    assert outcome.changed is False
    assert load_notifications() == []
    [dismissed] = load_notifications(include_dismissed=True)
    assert dismissed.id == notification.id
    assert dismissed.dismissed is True
    assert dismissed.read is True
    assert dismissed.muted is True
    assert dismissed.snooze_until == "2026-05-12T10:00:00+00:00"


def test_attention_inventory_cached_repeat_never_resurfaces_user_dismissal(
    notification_store_file: Path,
) -> None:
    del notification_store_file
    attention_inbox.reconcile_remote_attention_inbox(
        _response([_entry()]),
        now_unix=_OBSERVED_AT,
    )
    [notification] = load_notifications()
    rewrite_notifications(
        [dataclasses.replace(notification, read=True, dismissed=True)]
    )

    for _ in range(5):
        outcome = attention_inbox.reconcile_remote_attention_inbox(
            _response([_entry()], cached=True),
            now_unix=_OBSERVED_AT,
        )
        assert outcome.changed is False

    assert load_notifications() == []
    [dismissed] = load_notifications(include_dismissed=True)
    assert dismissed.dismissed is True
    assert dismissed.read is True


def test_attention_inventory_new_revision_resurfaces_user_dismissed_row(
    notification_store_file: Path,
) -> None:
    del notification_store_file
    attention_inbox.reconcile_remote_attention_inbox(
        _response([_entry(revision=1)]),
        now_unix=_OBSERVED_AT,
    )
    [old] = load_notifications()
    rewrite_notifications(
        [dataclasses.replace(old, read=True, dismissed=True, muted=True)]
    )

    revised = _response([_entry(revision=2)])
    revised["hosts"][0]["payload"]["observed_at_unix"] = _OBSERVED_AT + 60.0
    outcome = attention_inbox.reconcile_remote_attention_inbox(
        revised,
        now_unix=_OBSERVED_AT + 60.0,
    )

    assert outcome.created == 0
    assert outcome.updated == 1
    assert outcome.dismissed == 0
    [row] = load_notifications(include_dismissed=True)
    assert row.id == old.id
    assert row.dedup_key == old.dedup_key
    assert (
        row.action_data[attention_inbox.REMOTE_ATTENTION_REVISION_ACTION_DATA_KEY]
        == "2"
    )
    assert row.dismissed is False
    assert row.read is False
    # Local mute survives; the row's activity time moves to the new revision.
    assert row.muted is True
    assert row.timestamp == old.timestamp
    assert row.resurfaced_at is not None
    assert row.resurfaced_at > old.timestamp


def test_attention_inventory_dismissal_sticks_for_its_revision(
    notification_store_file: Path,
) -> None:
    del notification_store_file
    attention_inbox.reconcile_remote_attention_inbox(
        _response([_entry(revision=1)]),
        now_unix=_OBSERVED_AT,
    )
    attention_inbox.reconcile_remote_attention_inbox(
        _response([_entry(revision=2)]),
        now_unix=_OBSERVED_AT,
    )
    [row] = load_notifications()
    rewrite_notifications([dataclasses.replace(row, read=True, dismissed=True)])

    for _ in range(3):
        outcome = attention_inbox.reconcile_remote_attention_inbox(
            _response([_entry(revision=2)]),
            now_unix=_OBSERVED_AT,
        )
        assert outcome.changed is False

    assert load_notifications() == []
    [dismissed] = load_notifications(include_dismissed=True)
    assert dismissed.dismissed is True
    assert dismissed.read is True

    outcome = attention_inbox.reconcile_remote_attention_inbox(
        _response([_entry(revision=3)]),
        now_unix=_OBSERVED_AT,
    )
    assert outcome.updated == 1
    [active] = load_notifications()
    assert active.id == row.id
    assert active.read is False


def test_attention_inventory_same_revision_re_emission_writes_nothing(
    notification_store_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attention_inbox.reconcile_remote_attention_inbox(
        _response([_entry(revision=1)]),
        now_unix=_OBSERVED_AT,
    )
    [row] = load_notifications()
    rewrite_notifications([dataclasses.replace(row, read=True, dismissed=True)])
    before = notification_store_file.read_bytes()
    generation_before = read_unread_completion_index().generation

    reconcile_calls: list[list[Any]] = []
    real_reconcile = attention_inbox.reconcile_notification_rows

    def _spying_reconcile(rows, **kwargs):  # type: ignore[no-untyped-def]
        reconcile_calls.append(list(rows))
        return real_reconcile(rows, **kwargs)

    monkeypatch.setattr(
        attention_inbox, "reconcile_notification_rows", _spying_reconcile
    )

    outcome = attention_inbox.reconcile_remote_attention_inbox(
        _response([_entry(revision=1)]),
        now_unix=_OBSERVED_AT + 60.0,
    )

    assert outcome.changed is False
    assert reconcile_calls == []
    assert notification_store_file.read_bytes() == before
    assert read_unread_completion_index().generation == generation_before


def test_attention_inventory_resurfaces_own_auto_dismissal(
    notification_store_file: Path,
) -> None:
    del notification_store_file
    attention_inbox.reconcile_remote_attention_inbox(
        _response([_entry()]),
        now_unix=_OBSERVED_AT,
    )

    outcome = attention_inbox.reconcile_remote_attention_inbox(
        _response([]),
        now_unix=_OBSERVED_AT,
    )
    assert outcome.dismissed == 1
    [dismissed] = load_notifications(include_dismissed=True)
    assert dismissed.dismissed is True
    assert (
        dismissed.action_data[
            attention_inbox.REMOTE_ATTENTION_AUTO_DISMISSED_ACTION_DATA_KEY
        ]
        == "true"
    )

    outcome = attention_inbox.reconcile_remote_attention_inbox(
        _response([_entry()]),
        now_unix=_OBSERVED_AT,
    )

    assert outcome.updated == 1
    [active] = load_notifications()
    assert active.id == dismissed.id
    assert active.dismissed is False
    assert active.read is False
    assert attention_inbox.REMOTE_ATTENTION_AUTO_DISMISSED_ACTION_DATA_KEY not in (
        active.action_data or {}
    )


def test_attention_inventory_new_revision_keeps_one_row_per_request(
    notification_store_file: Path,
) -> None:
    del notification_store_file
    for revision in (1, 2, 3):
        attention_inbox.reconcile_remote_attention_inbox(
            _response([_entry(revision=revision)]),
            now_unix=_OBSERVED_AT,
        )

    [row] = load_notifications(include_dismissed=True)
    assert row.dismissed is False
    assert (
        row.action_data[attention_inbox.REMOTE_ATTENTION_REVISION_ACTION_DATA_KEY]
        == "3"
    )
    assert attention_inbox.REMOTE_ATTENTION_AUTO_DISMISSED_ACTION_DATA_KEY not in (
        row.action_data or {}
    )


def test_attention_inventory_incomplete_page_does_not_settle_absences(
    notification_store_file: Path,
) -> None:
    del notification_store_file
    attention_inbox.reconcile_remote_attention_inbox(
        _response([_entry()]),
        now_unix=_OBSERVED_AT,
    )

    outcome = attention_inbox.reconcile_remote_attention_inbox(
        _response([], has_more=True, next_cursor="off:100"),
        now_unix=_OBSERVED_AT,
    )

    assert outcome.changed is False
    [active] = load_notifications()
    assert active.dismissed is False


def test_attention_inventory_new_revision_supersedes_old_decision(
    notification_store_file: Path,
) -> None:
    del notification_store_file
    attention_inbox.reconcile_remote_attention_inbox(
        _response([_entry(revision=1)]),
        now_unix=_OBSERVED_AT,
    )

    outcome = attention_inbox.reconcile_remote_attention_inbox(
        _response([_entry(revision=2)]),
        now_unix=_OBSERVED_AT,
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
        _response([_entry()]),
        now_unix=_OBSERVED_AT,
    )

    outcome = attention_inbox.reconcile_remote_attention_inbox(
        _response([]),
        now_unix=_OBSERVED_AT,
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
        _response([_entry()]),
        now_unix=_OBSERVED_AT,
    )

    outcome = attention_inbox.reconcile_remote_attention_inbox(
        _unavailable_response(),
        now_unix=_OBSERVED_AT,
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
    from sase.notifications.models import Notification

    completion = Notification(
        id="completion-00000001",
        timestamp="2026-09-30T00:00:00+00:00",
        sender="agent-completion",
        notes=["agent finished"],
    )
    notification_store.append_notification(completion)
    attention_inbox.reconcile_remote_attention_inbox(
        _response([_entry(revision=1)]),
        now_unix=_OBSERVED_AT,
    )

    real_load = notification_store.load_notifications

    def _interleaving_load(*, include_dismissed: bool = False):  # type: ignore[no-untyped-def]
        snapshot = real_load(include_dismissed=include_dismissed)
        notification_store.mark_dismissed(completion.id)
        return snapshot

    monkeypatch.setattr(attention_inbox, "load_notifications", _interleaving_load)

    outcome = attention_inbox.reconcile_remote_attention_inbox(
        _response([_entry(revision=2)]),
        now_unix=_OBSERVED_AT,
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
        _response([_entry()]),
        now_unix=_OBSERVED_AT,
    )
    assert len(reconcile_calls) == 1
    assert len(reconcile_calls[0]) == 1

    second = _response([_entry()])
    second["hosts"][0]["payload"]["observed_at_unix"] = _OBSERVED_AT + 60.0
    outcome = attention_inbox.reconcile_remote_attention_inbox(
        second,
        now_unix=_OBSERVED_AT + 60.0,
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
        _response([_entry(revision=1)]),
        now_unix=_OBSERVED_AT,
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

    refreshed_entry = _entry(revision=1)
    refreshed_entry["title"] = "Approve deploy v2"
    outcome = attention_inbox.reconcile_remote_attention_inbox(
        _response([refreshed_entry]),
        now_unix=_OBSERVED_AT + 60.0,
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
        _response([_entry(kind="question", request_id="question-0001")]),
        now_unix=_OBSERVED_AT,
    )

    [notification] = load_notifications()
    raw_entry = notification.action_data[
        attention_inbox.REMOTE_ATTENTION_ENTRY_ACTION_DATA_KEY
    ]
    assert isinstance(raw_entry, str)
    assert json.loads(raw_entry)["kind"] == "question"


def _seed_legacy_row(
    *,
    revision: int,
    request_id: str = "gate-00000001",
    read: bool = False,
    dismissed: bool = False,
    auto_dismissed: bool = False,
    muted: bool = False,
    timestamp: str = "2026-05-01T00:00:00+00:00",
) -> Notification:
    """Build a per-revision row the way the reconciler wrote it before the
    stable request key."""
    attention_inbox.reconcile_remote_attention_inbox(
        _response([_entry(revision=revision, request_id=request_id)]),
        now_unix=_OBSERVED_AT,
    )
    stable = next(
        row
        for row in load_notifications(include_dismissed=True)
        if row.action_data.get(
            attention_inbox.REMOTE_ATTENTION_REQUEST_ID_ACTION_DATA_KEY
        )
        == request_id
    )
    legacy_key = f"remote-attention:{_INSTALLATION_ID}:{request_id}:{revision}"
    action_data = dict(stable.action_data)
    if auto_dismissed:
        action_data[attention_inbox.REMOTE_ATTENTION_AUTO_DISMISSED_ACTION_DATA_KEY] = (
            "true"
        )
    legacy = dataclasses.replace(
        stable,
        id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"sase:{legacy_key}")),
        dedup_key=legacy_key,
        timestamp=timestamp,
        read=read,
        dismissed=dismissed,
        muted=muted,
        action_data=action_data,
    )
    others = [
        row for row in load_notifications(include_dismissed=True) if row != stable
    ]
    _replace_store([*others, legacy])
    return legacy


def _replace_store(rows: list[Notification]) -> None:
    from sase.notifications import store as notification_store

    Path(notification_store.NOTIFICATIONS_FILE).unlink()
    rewrite_notifications(rows)


def _stable_row(request_id: str = "gate-00000001") -> Notification:
    stable_key = f"remote-attention:{_INSTALLATION_ID}:{request_id}"
    [row] = [
        row
        for row in load_notifications(include_dismissed=True)
        if row.dedup_key == stable_key
    ]
    return row


def test_legacy_user_dismissal_carries_to_the_stable_row(
    notification_store_file: Path,
) -> None:
    del notification_store_file
    legacy = _seed_legacy_row(revision=1, read=True, dismissed=True, muted=True)

    outcome = attention_inbox.reconcile_remote_attention_inbox(
        _response([_entry(revision=1)]),
        now_unix=_OBSERVED_AT,
    )

    assert outcome.created == 1
    assert outcome.dismissed == 0
    assert load_notifications() == []
    stable = _stable_row()
    assert stable.id != legacy.id
    assert stable.dismissed is True
    assert stable.read is True
    assert stable.muted is True
    assert stable.timestamp == legacy.timestamp
    [untouched] = [
        row for row in load_notifications(include_dismissed=True) if row.id == legacy.id
    ]
    assert untouched == legacy

    # The migration happens once: the next pass writes nothing.
    outcome = attention_inbox.reconcile_remote_attention_inbox(
        _response([_entry(revision=1)]),
        now_unix=_OBSERVED_AT,
    )
    assert outcome.changed is False


def test_legacy_undismissed_row_folds_into_the_stable_row(
    notification_store_file: Path,
) -> None:
    del notification_store_file
    legacy = _seed_legacy_row(revision=1, read=True)

    outcome = attention_inbox.reconcile_remote_attention_inbox(
        _response([_entry(revision=1)]),
        now_unix=_OBSERVED_AT,
    )

    assert outcome.created == 1
    assert outcome.dismissed == 1
    [active] = load_notifications()
    assert active.dedup_key == f"remote-attention:{_INSTALLATION_ID}:gate-00000001"
    assert active.read is True
    [folded] = [
        row for row in load_notifications(include_dismissed=True) if row.id == legacy.id
    ]
    assert folded.dismissed is True
    assert (
        folded.action_data[
            attention_inbox.REMOTE_ATTENTION_AUTO_DISMISSED_ACTION_DATA_KEY
        ]
        == "true"
    )


def test_legacy_dismissal_of_an_older_revision_does_not_hide_a_new_one(
    notification_store_file: Path,
) -> None:
    del notification_store_file
    older = _seed_legacy_row(revision=1, read=True, dismissed=True)

    outcome = attention_inbox.reconcile_remote_attention_inbox(
        _response([_entry(revision=2)]),
        now_unix=_OBSERVED_AT,
    )

    assert outcome.created == 1
    assert outcome.dismissed == 0
    [active] = load_notifications()
    assert active.read is False
    assert (
        active.action_data[attention_inbox.REMOTE_ATTENTION_REVISION_ACTION_DATA_KEY]
        == "2"
    )
    [kept] = [
        row for row in load_notifications(include_dismissed=True) if row.id == older.id
    ]
    assert kept == older


def test_legacy_auto_dismissal_does_not_carry_to_the_stable_row(
    notification_store_file: Path,
) -> None:
    del notification_store_file
    _seed_legacy_row(revision=1, read=True, dismissed=True, auto_dismissed=True)

    outcome = attention_inbox.reconcile_remote_attention_inbox(
        _response([_entry(revision=1)]),
        now_unix=_OBSERVED_AT,
    )

    assert outcome.created == 1
    [active] = load_notifications()
    assert active.read is False
    assert active.dismissed is False
