"""Join tests for ``,X`` launch records and loaded agent rows."""

from __future__ import annotations

from types import SimpleNamespace

from sase.ace.tui.actions.agent_workflow._kill_last_launch import (
    _agent_for_launch_result,
    _matched_agents_for_record,
)
from sase.ace.tui.actions.agent_workflow._launch_records import push_launch_record
from sase.agent.launch_types import AgentLaunchResult

from tests.ace.tui._kill_and_edit_last_launch_helpers import (
    _FakeAgent,
    _artifacts_dir,
    _context,
    _matchable_result,
)

# --- join: AgentLaunchResult -> loaded row ----------------------------------


def test_agent_for_launch_result_matches_on_artifacts_dir() -> None:
    target_dir = _artifacts_dir("proj", "20260903170000")
    agent = _FakeAgent("agent-a", artifacts_dir_value=target_dir)
    other = _FakeAgent("agent-b", artifacts_dir_value="/tmp/somewhere/else")
    result = _matchable_result("proj", "20260903170000")

    assert _agent_for_launch_result([other, agent], result) is agent


def test_agent_for_launch_result_prefers_explicit_result_artifacts_dir() -> None:
    target_dir = "/tmp/explicit-artifacts/live"
    agent = _FakeAgent("agent-a", artifacts_dir_value=target_dir)
    canonical_fallback = _artifacts_dir("proj", "20260903170000")
    other = _FakeAgent("agent-b", artifacts_dir_value=canonical_fallback)
    result = AgentLaunchResult(
        pid=100,
        workspace_num=1,
        workspace_dir="/tmp/ws",
        output_path=f"{canonical_fallback}/live_reply.md",
        project_name="proj",
        workflow_name="ace-run",
        timestamp="20260903170000",
        artifacts_dir=target_dir,
    )

    assert _agent_for_launch_result([other, agent], result) is agent


def test_agent_for_launch_result_returns_none_when_row_is_gone() -> None:
    result = _matchable_result("proj", "20260903170000")
    still_loaded = _FakeAgent("agent-a", artifacts_dir_value="/tmp/unrelated")

    assert _agent_for_launch_result([still_loaded], result) is None


def test_matched_agents_for_record_follows_proc_id_order_and_skips_gone_rows() -> None:
    record = push_launch_record(
        SimpleNamespace(),
        proc_ids=("p1", "p2"),
        prompt="prompt",
        context=_context(),
    )
    assert record is not None
    dir1 = _artifacts_dir("proj", "20260903170001")
    dir2 = _artifacts_dir("proj", "20260903170002")
    record.results["p1"] = (_matchable_result("proj", "20260903170001"),)
    record.results["p2"] = (_matchable_result("proj", "20260903170002"),)

    second_only = [_FakeAgent("second", artifacts_dir_value=dir2)]
    assert _matched_agents_for_record(record, second_only) == second_only

    both = [
        _FakeAgent("second", artifacts_dir_value=dir2),
        _FakeAgent("first", artifacts_dir_value=dir1),
    ]
    matched = _matched_agents_for_record(record, both)
    # Order follows proc_ids (p1, p2), i.e. launch order, not row order.
    assert [a.name for a in matched] == ["first", "second"]
