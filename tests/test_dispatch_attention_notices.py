from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sase.dispatch.attention_notices import (
    ATTENTION_NOTICES_SCHEMA_VERSION,
    decide_and_persist_attention_notices,
)

INSTALLATION_ID_PREFIX = "sase_inst_v1_"


def _request_key(request_id: str = "gate-00000001") -> dict[str, Any]:
    return {
        "schema_version": 1,
        "origin_installation_id": f"{INSTALLATION_ID_PREFIX}{'a' * 64}",
        "request_id": request_id,
        "pending_action_prefix": request_id[:8],
    }


def _entry(request_id: str, revision: int, *, state: str = "pending") -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": "gate",
        "state": state,
        "request_key": _request_key(request_id),
        "revision": revision,
        "logical_key": None,
        "logical_locator": None,
        "title": "Approve deploy",
        "summary": "please approve",
        "options": [{"schema_version": 1, "id": "approve", "label": "Approve"}],
        "feedback_required": False,
        "question_form": None,
        "preview": None,
        "settled_by_host_label": None,
        "settled_response": None,
    }


def test_no_entries_and_no_existing_ledger_performs_no_write(tmp_path: Path) -> None:
    path = tmp_path / "attention_notices.json"
    to_announce = decide_and_persist_attention_notices([], path=path)
    assert to_announce == []
    assert not path.exists()


def test_new_entry_announces_once_reconnect_suppresses_and_supersede_reannounces(
    tmp_path: Path,
) -> None:
    path = tmp_path / "attention_notices.json"
    entry = _entry("gate-00000001", revision=1)

    first = decide_and_persist_attention_notices([entry], now_unix=100.0, path=path)
    assert [item["request_key"]["request_id"] for item in first] == ["gate-00000001"]
    assert path.is_file()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == ATTENTION_NOTICES_SCHEMA_VERSION
    assert len(payload["entries"]) == 1

    # A reconnect re-delivering the identical revision announces nothing.
    second = decide_and_persist_attention_notices([entry], now_unix=101.0, path=path)
    assert second == []

    # A superseded and re-asked request (new revision) announces exactly once.
    superseded = _entry("gate-00000001", revision=2)
    third = decide_and_persist_attention_notices(
        [superseded], now_unix=102.0, path=path
    )
    assert len(third) == 1
    assert third[0]["revision"] == 2


def test_ledger_prunes_stale_entries_outside_retention_window(tmp_path: Path) -> None:
    path = tmp_path / "attention_notices.json"
    entry = _entry("gate-00000001", revision=1)
    decide_and_persist_attention_notices(
        [entry], retention_window_seconds=10.0, now_unix=100.0, path=path
    )

    # The request is no longer projected (settled/expired/unfollowed) and
    # has aged past the retention window: it is pruned from the ledger.
    decide_and_persist_attention_notices(
        [], retention_window_seconds=10.0, now_unix=200.0, path=path
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["entries"] == []
