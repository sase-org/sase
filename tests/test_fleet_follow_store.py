from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sase.core.rust import require_rust_binding
from sase.dispatch.follow_store import (
    FOLLOW_STORE_SCHEMA_VERSION,
    activate_dispatch_follow,
    follow_store_path,
    is_followed,
    prewrite_dispatch_follow,
    promote_family_follow,
    reconcile_follow_store,
    record_follow,
    unfollow,
)
from tests.conftest import redirect_sase_home

INSTALLATION_ID_PREFIX = "sase_inst_v1_"


def _known_installation_id(hex_char: str) -> str:
    return f"{INSTALLATION_ID_PREFIX}{hex_char * 64}"


def _origin(installation_id: str) -> dict[str, Any]:
    return {"schema_version": 1, "installation_id": installation_id}


def _logical_locator(
    installation_id: str,
    *,
    agent_id: str = "agent-1",
    family_id: str | None = "family-1",
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "project": {
            "schema_version": 1,
            "origin": _origin(installation_id),
            "project_id": "sase-main",
        },
        "agent_id": agent_id,
        "family_id": family_id,
    }


def _logical_key(logical_locator: dict[str, Any]) -> str:
    key = require_rust_binding("fleet_logical_locator_key")(logical_locator)
    assert isinstance(key, str)
    return key


def _operation_key(operation_id: str = "op-1") -> dict[str, Any]:
    return {
        "schema_version": 1,
        "controller_id": "controller-1",
        "operation_id": operation_id,
    }


def _follow_record(
    logical_locator: dict[str, Any],
    *,
    created_by: str,
    state: str,
    timestamp: float,
    operation_id: str = "op-1",
) -> dict[str, Any]:
    return {
        "schema_version": FOLLOW_STORE_SCHEMA_VERSION,
        "logical_locator": logical_locator,
        "logical_key": _logical_key(logical_locator),
        "created_by": created_by,
        "state": state,
        "created_at_unix": timestamp,
        "updated_at_unix": timestamp,
        "activated_at_unix": timestamp if state == "active" else None,
        "operation_key": (
            _operation_key(operation_id) if created_by == "dispatch" else None
        ),
    }


def _tombstone(logical_locator: dict[str, Any], timestamp: float) -> dict[str, Any]:
    return {
        "schema_version": FOLLOW_STORE_SCHEMA_VERSION,
        "logical_locator": logical_locator,
        "logical_key": _logical_key(logical_locator),
        "unfollowed_at_unix": timestamp,
    }


def test_follow_store_persists_explicit_follow_and_unfollow(
    tmp_path: Path,
    monkeypatch,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    logical = _logical_locator(_known_installation_id("a"))

    followed = record_follow(logical, now_unix=10.0)

    assert followed.changed is True
    assert is_followed(followed.snapshot, logical)
    assert follow_store_path().is_file()

    removed = unfollow(logical, unfollowed_at_unix=11.0)

    assert removed.changed is True
    assert removed.snapshot.records == ()
    assert len(removed.snapshot.tombstones) == 1
    assert not is_followed(removed.snapshot, logical)

    refollowed = record_follow(logical, now_unix=12.0)

    assert refollowed.changed is True
    assert is_followed(refollowed.snapshot, logical)
    assert refollowed.snapshot.tombstones == ()
    assert json.loads(follow_store_path().read_text(encoding="utf-8")) == {
        "schema_version": FOLLOW_STORE_SCHEMA_VERSION,
        "records": list(refollowed.snapshot.records),
        "tombstones": [],
    }


def test_dispatch_follow_activation_family_promotion_and_unfollow_wins(
    tmp_path: Path,
    monkeypatch,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    singleton = _logical_locator(_known_installation_id("a"), family_id=None)
    family = _logical_locator(_known_installation_id("a"), family_id="family-1")

    pending = prewrite_dispatch_follow(
        singleton,
        _operation_key("op-1"),
        now_unix=20.0,
    )
    assert pending.snapshot.records[0]["state"] == "pending"

    activated = activate_dispatch_follow(
        singleton,
        operation_key=_operation_key("op-1"),
        activated_at_unix=21.0,
    )
    assert activated.snapshot.records[0]["state"] == "active"
    assert activated.snapshot.records[0]["activated_at_unix"] == 21.0

    promoted = promote_family_follow(singleton, family, now_unix=22.0)
    assert promoted.snapshot.records[0]["logical_locator"] == family
    assert is_followed(promoted.snapshot, family)

    removed = unfollow(family, unfollowed_at_unix=23.0)
    resurrected = prewrite_dispatch_follow(
        family,
        _operation_key("op-2"),
        now_unix=24.0,
    )
    assert resurrected.changed is False
    assert resurrected.snapshot.records == ()
    assert resurrected.snapshot.tombstones == removed.snapshot.tombstones
    assert any(
        diagnostic["code"] == "follow_tombstone_blocked"
        for diagnostic in resurrected.diagnostics
    )

    path = follow_store_path()
    stale_payload = {
        "schema_version": FOLLOW_STORE_SCHEMA_VERSION,
        "records": [
            _follow_record(
                singleton,
                created_by="dispatch",
                state="pending",
                timestamp=30.0,
                operation_id="op-3",
            )
        ],
        "tombstones": [_tombstone(singleton, 31.0)],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(stale_payload), encoding="utf-8")

    reconciled = reconcile_follow_store(
        promotions=(
            {
                "schema_version": FOLLOW_STORE_SCHEMA_VERSION,
                "from": singleton,
                "to": family,
            },
        ),
        now_unix=32.0,
    )

    assert reconciled.changed is True
    assert reconciled.snapshot.records == ()
    assert any(
        diagnostic["code"] == "follow_promotion_source_tombstoned"
        for diagnostic in reconciled.diagnostics
    )
