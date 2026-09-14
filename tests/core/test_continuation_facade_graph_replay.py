"""Tests for continuation graph validation, replay planning, and retention."""

from __future__ import annotations

import pytest

from sase.core.continuation_facade import (
    plan_continuation_replay,
    plan_continuation_retention,
)
from sase.core.continuation_wire import CONTINUATION_WIRE_SCHEMA_VERSION
from tests.core._continuation_facade_helpers import call_continuation_binding, make_node


def test_graph_validation_summarizes_duplicates_and_missing_parents() -> None:
    summary = call_continuation_binding(
        "continuation_validate_graph",
        [
            make_node("root"),
            make_node("root"),
            make_node("leaf", ["root", "missing-parent"]),
        ],
    )

    assert summary["schema_version"] == CONTINUATION_WIRE_SCHEMA_VERSION
    assert summary["node_count"] == 3
    assert summary["edge_count"] == 2
    assert summary["duplicate_ids"] == ["root"]
    assert summary["missing_parent_ids"] == ["missing-parent"]


def test_replay_planning_is_parent_first_and_reports_shared_ancestry() -> None:
    request = {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "records": [
            make_node("leaf-left", ["base"]),
            make_node("base"),
            make_node("leaf-right", ["base"]),
        ],
        "root_ids": ["leaf-left", "leaf-right", "missing-root"],
        "selected_evidence_refs": ["file:explicit:diagnostics"],
        "rendered_components": [
            {"name": "local_prompt", "utf8_bytes": 100},
            {"name": "selected_evidence", "utf8_bytes": 25},
        ],
        "checkpoint_coverage": [
            {
                "checkpoint_ref": "file:explicit:checkpoint",
                "covered_node_ids": ["base"],
            }
        ],
    }

    plan = plan_continuation_replay(request)

    assert plan["ordered_node_ids"] == ["base", "leaf-left", "leaf-right"]
    assert [block["node_id"] for block in plan["stable_blocks"]] == [
        "base",
        "leaf-left",
        "leaf-right",
    ]
    assert all(
        block["block_id"].startswith("block:v1:") for block in plan["stable_blocks"]
    )
    assert plan["selected_evidence_refs"] == ["file:explicit:diagnostics"]
    assert plan["rendered_component_sizes"]["total_utf8_bytes"] == 125
    assert plan["checkpoint_coverage"][0]["covered_node_ids"] == ["base"]
    assert plan["omissions"] == [
        {
            "kind": "missing_root",
            "node_id": "missing-root",
            "parent_id": None,
            "reason": "root id has no continuation record",
        }
    ]
    assert any(
        entry["node_id"] == "base" and entry["reused"] is True
        for entry in plan["branch_attribution"]
    )


def test_retention_planning_protects_live_ancestry_only() -> None:
    plan = plan_continuation_retention(
        {
            "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
            "runs": [
                {
                    "artifact_dir": "/tmp/old",
                    "timestamp": "20260501000000",
                    "node_id": "agent-delta:old",
                    "live": False,
                    "recoverable": False,
                },
                {
                    "artifact_dir": "/tmp/live",
                    "timestamp": "20260901000000",
                    "parent_node_ids": ["agent-delta:old"],
                    "starter_artifact_dir": "/tmp/old",
                    "live": True,
                    "recoverable": False,
                },
                {
                    "artifact_dir": "/tmp/unrelated",
                    "timestamp": "20260401000000",
                    "live": False,
                    "recoverable": False,
                },
            ],
        }
    )

    assert "/tmp/old" in plan["protected_dirs"]
    assert "/tmp/live" in plan["protected_dirs"]
    assert "/tmp/unrelated" not in plan["protected_dirs"]
    assert plan["reasons_by_dir"]["/tmp/old"] == ["continuation_ancestry"]


def test_replay_rejects_conflicting_duplicates_and_cycles() -> None:
    conflicting = make_node("same")
    conflicting["content_sha256"] = "b" * 64
    with pytest.raises(ValueError, match="conflicting duplicate"):
        plan_continuation_replay(
            {
                "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
                "records": [make_node("same"), conflicting],
                "root_ids": ["same"],
            }
        )

    with pytest.raises(ValueError, match="cycle"):
        plan_continuation_replay(
            {
                "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
                "records": [make_node("left", ["right"]), make_node("right", ["left"])],
                "root_ids": ["left"],
            }
        )
