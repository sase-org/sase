"""Tests for the stranded-work reducer facade."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from sase.core import stranded_work_facade as facade


def _reset_binding(monkeypatch: pytest.MonkeyPatch, binding: Any) -> None:
    monkeypatch.setattr(facade, "_REDUCE_BINDING", None)
    monkeypatch.setattr(facade, "require_rust_binding", lambda _name: binding)


def test_reduce_stranded_work_hydrates_verdicts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[Mapping[str, Any]] = []

    def binding(facts: Mapping[str, Any]) -> dict[str, Any]:
        captured.append(facts)
        return {
            "schema_version": 1,
            "verdicts": [
                {
                    "bead_id": "sase-1.2",
                    "kind": "phase",
                    "state": "stranded",
                    "reason": "kept",
                    "session": "sase-1.2",
                    "last_turn": "sase-1.2",
                    "since": 10.0,
                    "blocked_by": [],
                    "blocks": ["sase-1"],
                    "delegates": [],
                }
            ],
            "stranded_ids": ["sase-1.2"],
            "blocked_ids": ["sase-1"],
        }

    _reset_binding(monkeypatch, binding)
    report = facade.reduce_stranded_work(
        {"schema_version": 1, "now": 100.0, "beads": []}
    )
    assert captured[0]["now"] == 100.0
    assert report.schema_version == 1
    assert report.stranded_ids == ("sase-1.2",)
    assert report.blocked_ids == ("sase-1",)
    verdict = report.verdicts[0]
    assert verdict.bead_id == "sase-1.2"
    assert verdict.state == "stranded"
    assert verdict.reason == "kept"
    assert verdict.since == 10.0
    assert verdict.blocks == ("sase-1",)


def test_reduce_stranded_work_rejects_non_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_binding(monkeypatch, lambda _facts: ["nope"])
    with pytest.raises(RuntimeError, match="non-mapping report"):
        facade.reduce_stranded_work({})


def test_reduce_stranded_work_round_trips_through_real_binding() -> None:
    facade._REDUCE_BINDING = None
    try:
        report = facade.reduce_stranded_work(
            {
                "schema_version": 1,
                "now": 200.0,
                "settle_grace_seconds": 120.0,
                "beads": [
                    {
                        "id": "sase-1.2",
                        "kind": "phase",
                        "status": "in_progress",
                        "candidate": True,
                        "assignee": "sase-1.2",
                        "parent_id": "sase-1",
                        "closed_at": None,
                        "records_available": True,
                        "members": [
                            {
                                "name": "sase-1.2",
                                "artifact_dir": "/tmp/sase-1.2",
                                "turn_kind": "agent",
                                "lifecycle": "done",
                                "process_live": False,
                                "remote": False,
                                "finalizing": False,
                                "pending_handoff": None,
                                "handoff_inflight": False,
                                "recovery_in_flight": False,
                                "turn_state": None,
                                "followup_pending": False,
                                "followup_outcome": None,
                                "followup_agent": None,
                                "declared_bead_action": "keep",
                                "started_at": 1.0,
                                "ended_at": 2.0,
                            }
                        ],
                    }
                ],
            }
        )
    except (RuntimeError, AttributeError) as exc:
        pytest.skip(f"stranded_work_reduce binding unavailable: {exc}")
    assert report.schema_version == 1
    assert report.stranded_ids == ("sase-1.2",)
    assert report.verdicts[0].reason == "kept"
