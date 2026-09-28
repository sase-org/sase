"""Adapter round trips for the ToolRun glance projections (epic sase-1bt).

Covers ``tool_run_live_glance``, ``tool_run_briefs``, and
``tool_run_node_summaries`` against the real binding, plus the tolerant
``from_wire`` parsing (unknown keys ignored, missing optionals become None).
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from sase.core.tool_run import (
    ToolRunBrief,
    ToolRunBriefs,
    ToolRunGlance,
    ToolRunLiveGlance,
    ToolRunNodeSummaries,
    ToolRunNodeSummary,
    ToolRunVerdictSummary,
    tool_run_begin,
    tool_run_briefs,
    tool_run_finish,
    tool_run_live_glance,
    tool_run_node_summaries,
)


pytestmark = pytest.mark.skipif(
    not hasattr(importlib.import_module("sase_core_rs"), "tool_run_live_glance"),
    reason="glance bindings are not in this wheel",
)


def _definition() -> dict:
    return {
        "schema_version": 1,
        "name": "check",
        "argv": ["just", "check"],
        "description": "check",
        "stages": "run_silent",
        "inputs": ["Justfile"],
        "env": [],
        "args": "deny",
        "fingerprint": {"repos": [], "toolchain": {}},
    }


def _begin(store: str, **extra) -> str:
    payload = {
        "schema_version": 1,
        "tool_name": "check",
        "definition": _definition(),
        "display_argv": ["just", "check"],
        "project": "sase",
        "agent": "0t9--code",
        "workspace": "13",
        "bead": "sase-1bt.3",
        "now_ts": 10,
        "commit_running": True,
        **extra,
    }
    started = tool_run_begin(payload, store_path=store)
    assert started["run"]["state"] == "running"
    return str(started["run"]["run_id"])


def test_live_glance_round_trip(tmp_path: Path) -> None:
    store = str(tmp_path / "tools" / "runs.sqlite")
    run_id = _begin(store)
    glance = tool_run_live_glance(store_path=store)
    assert isinstance(glance, ToolRunLiveGlance)
    assert glance.store_exists is True
    assert glance.silent_after_s == 60
    assert glance.truncated is False
    assert [row.run_id for row in glance.runs] == [run_id]
    row = glance.runs[0]
    assert isinstance(row, ToolRunGlance)
    assert (row.label, row.state) == ("check", "running")
    assert row.agent == "0t9--code"
    assert row.workspace == "13"
    assert row.bead == "sase-1bt.3"
    assert row.project == "sase"
    assert row.stop_requested is False
    assert row.owner_kind is None


def test_briefs_round_trip_with_settled_run(tmp_path: Path) -> None:
    store = str(tmp_path / "tools" / "runs.sqlite")
    run_id = _begin(store)
    tool_run_finish(
        {
            "schema_version": 1,
            "run_id": run_id,
            "state": "failed",
            "exit_code": 3,
            "duration_ms": 252000,
            "now_ts": 262,
        },
        store_path=store,
    )
    briefs = tool_run_briefs({"agents": ["0t9--code"]}, store_path=store)
    assert isinstance(briefs, ToolRunBriefs)
    assert briefs.store_exists is True
    assert [row.run_id for row in briefs.runs] == [run_id]
    row = briefs.runs[0]
    assert isinstance(row, ToolRunBrief)
    assert (row.label, row.state) == ("check", "failed")
    assert row.exit_code == 3
    assert row.duration_ms == 252000
    assert isinstance(row.verdict, ToolRunVerdictSummary)
    assert row.verdict.bucket == "undetermined"


def test_node_summaries_round_trip(tmp_path: Path) -> None:
    store = str(tmp_path / "tools" / "runs.sqlite")
    live_id = _begin(store, now_ts=10)
    settled_id = _begin(store, now_ts=12)
    tool_run_finish(
        {
            "schema_version": 1,
            "run_id": settled_id,
            "state": "failed",
            "exit_code": 3,
            "duration_ms": 1000,
            "now_ts": 20,
        },
        store_path=store,
    )
    summaries = tool_run_node_summaries(
        {"nodes": [{"key": "n1", "agents": ["0t9--code"], "owners": []}]},
        store_path=store,
    )
    assert isinstance(summaries, ToolRunNodeSummaries)
    assert summaries.store_exists is True
    assert summaries.silent_after_s == 60
    assert [node.key for node in summaries.nodes] == ["n1"]
    node = summaries.nodes[0]
    assert isinstance(node, ToolRunNodeSummary)
    assert node.total_runs == 2
    assert node.truncated is False
    assert [row.run_id for row in node.live] == [live_id]
    assert [row.run_id for row in node.runs] == [settled_id, live_id]


def test_from_wire_tolerates_unknown_and_missing_keys() -> None:
    glance = ToolRunGlance.from_wire(
        {"run_id": "r", "label": "check", "state": "running", "bogus": [1]}
    )
    assert glance.run_id == "r"
    assert glance.tool_name is None
    assert glance.current_stage is None
    assert glance.stages_expected is None

    brief = ToolRunBrief.from_wire(
        {"run_id": "r", "label": "check", "state": "failed", "verdict": None}
    )
    assert brief.verdict.bucket == "undetermined"
    assert brief.exit_code is None

    summary = ToolRunVerdictSummary.from_wire({"bucket": "pass", "new": 0})
    assert summary == ToolRunVerdictSummary(bucket="pass")

    node = ToolRunNodeSummary.from_wire({"key": "n1"})
    assert node.live == () and node.runs == () and node.total_runs == 0
