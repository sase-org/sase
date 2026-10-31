"""Tests for the thin workspace-retention policy facade."""

from __future__ import annotations

from typing import Any

import pytest

from sase.core.rust import require_rust_binding
from sase.core.workspace_retention import (
    DISPOSITION_OWNERSHIP_MOVED,
    DISPOSITION_RELEASE,
    DISPOSITION_RETAIN,
    WORKSPACE_RETENTION_WIRE_SCHEMA_VERSION,
    decide_workspace_retention,
    wire_schema_version,
)


def _claim(*, pid: int = 111) -> dict[str, Any]:
    return {
        "workspace_num": 17,
        "workflow": "ace(run)-260101_000000",
        "cl_name": "feature",
        "artifacts_timestamp": "20260101000000",
        "pid": pid,
    }


def _request(**overrides: object) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": WORKSPACE_RETENTION_WIRE_SCHEMA_VERSION,
        "expected_claim": _claim(),
        "observed_claim": _claim(),
        "successor": {
            "confirmed_active": False,
            "same_workspace": False,
            "inherited_obligations": False,
        },
        "creator_restored": False,
        "gate_released_workspace": False,
        "dirt": {
            "session_owned": False,
            "only_unchanged_foreign": False,
            "all_proven_clean": False,
            "missing_baseline": False,
            "positive_custody": False,
        },
        "probe_failed": False,
    }
    payload.update(overrides)
    return payload


def test_schema_version_matches_binding() -> None:
    assert WORKSPACE_RETENTION_WIRE_SCHEMA_VERSION == 1
    assert wire_schema_version() == WORKSPACE_RETENTION_WIRE_SCHEMA_VERSION
    binding = require_rust_binding("workspace_retention_wire_schema_version")
    assert int(binding()) == WORKSPACE_RETENTION_WIRE_SCHEMA_VERSION


def test_session_owned_dirt_retains() -> None:
    decision = decide_workspace_retention(
        _request(dirt={**_request()["dirt"], "session_owned": True})
    )
    assert decision["disposition"] == DISPOSITION_RETAIN
    assert decision["reason"] == "session_owned_dirt"


def test_same_workspace_successor_releases() -> None:
    decision = decide_workspace_retention(
        _request(
            successor={
                "confirmed_active": True,
                "same_workspace": True,
                "inherited_obligations": True,
            },
            dirt={**_request()["dirt"], "session_owned": True},
        )
    )
    assert decision["disposition"] == DISPOSITION_RELEASE
    assert decision["reason"] == "same_workspace_successor"


def test_stale_owner_is_ownership_moved() -> None:
    decision = decide_workspace_retention(_request(observed_claim=_claim(pid=999)))
    assert decision["disposition"] == DISPOSITION_OWNERSHIP_MOVED
    assert decision["reason"] == "claim_ownership_moved"


def test_unknown_field_is_rejected() -> None:
    request = _request()
    request["display_visible"] = False
    with pytest.raises(ValueError, match="WorkspaceRetentionRequestWire"):
        decide_workspace_retention(request)
