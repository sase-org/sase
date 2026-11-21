"""Shared helpers for the ``test_dispatch_attention_inbox_*`` test modules.

Split from ``tests.test_dispatch_attention_inbox``. Public helpers used by more
than one split module live here under public names so no new module imports
a ``_``-prefixed name from another new module.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

__all__ = [
    "INSTALLATION_ID",
    "OBSERVED_AT",
    "entry",
    "inbox_notification_store_file",
    "response",
]

INSTALLATION_ID = "sase_inst_v1_" + "a" * 64
OBSERVED_AT = 1_800_000_000.0


@pytest.fixture(name="notification_store_file")
def inbox_notification_store_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    notifications_dir = tmp_path / "notifications"
    notifications_file = notifications_dir / "notifications.jsonl"
    monkeypatch.setattr(
        "sase.notifications.store.NOTIFICATIONS_DIR", str(notifications_dir)
    )
    monkeypatch.setattr(
        "sase.notifications.store.NOTIFICATIONS_FILE", str(notifications_file)
    )
    return notifications_file


def entry(
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
            "origin_installation_id": INSTALLATION_ID,
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


def response(
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
                "installation_id": INSTALLATION_ID,
                "status": "ok",
                "cached": cached,
                "payload": {
                    "schema_version": 1,
                    "observed_at_unix": OBSERVED_AT,
                    "freshness": {
                        "schema_version": 1,
                        "freshness": freshness,
                        "partial": partial,
                        "refreshed_at_unix": OBSERVED_AT,
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
