from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

from sase.dispatch import attention_inbox
from sase.dispatch.federation import FederationConfig, FederationWorkerSettings
from sase.notifications.store import load_notifications, rewrite_notifications

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
                        "next_cursor": None,
                        "has_more": False,
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
        f"remote-attention:{_INSTALLATION_ID}:gate-00000001:1"
    )

    decoded = attention_inbox.remote_attention_from_notification(notification)
    assert decoded is not None
    alias, entry = decoded
    assert alias == "apollo"
    assert entry["request_key"]["request_id"] == "gate-00000001"


def test_attention_inventory_resurfaces_dismissed_pending_request(
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
    assert outcome.updated == 1
    [active] = load_notifications()
    assert active.id == notification.id
    assert active.read is False
    assert active.dismissed is False
    assert active.muted is True
    assert active.snooze_until == "2026-05-12T10:00:00+00:00"


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

    assert outcome.created == 1
    assert outcome.dismissed == 1
    [active] = load_notifications()
    assert (
        active.action_data[attention_inbox.REMOTE_ATTENTION_REVISION_ACTION_DATA_KEY]
        == "2"
    )
    all_rows = load_notifications(include_dismissed=True)
    assert len(all_rows) == 2
    assert sum(1 for row in all_rows if row.dismissed) == 1


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
