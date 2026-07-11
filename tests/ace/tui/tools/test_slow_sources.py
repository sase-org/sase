from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.tools.cache import tools_cache
from sase.ace.tui.tools.sources import (
    build_slow_tool_sources,
    supports_slow_tool_sources,
)
from sase.plan_chain import (
    PLAN_CHAIN_CODER_SUFFIX,
    PLAN_CHAIN_PLAN_SUFFIX,
)

from ._reader_helpers import _record, _write_jsonl


@pytest.fixture(autouse=True)
def _clear_tools_cache() -> None:
    tools_cache.clear()


def _agent(
    artifacts_dir: Path,
    *,
    agent_type: AgentType = AgentType.RUNNING,
    cl_name: str = "proj",
    status: str = "DONE",
    raw_suffix: str | None = None,
    **kwargs: object,
) -> Agent:
    return Agent(
        agent_type=agent_type,
        cl_name=cl_name,
        project_file="/tmp/proj/proj.sase",
        status=status,
        start_time=datetime(2026, 7, 3, 10, 0, 0),
        artifacts_dir=str(artifacts_dir),
        raw_suffix=raw_suffix or artifacts_dir.name,
        **kwargs,  # type: ignore[arg-type]
    )


def _write_call(artifacts_dir: Path, tool_use_id: str) -> None:
    _write_jsonl(
        artifacts_dir / "tool_calls.jsonl",
        [_record(tool_use_id=tool_use_id, duration_ms=30_000)],
    )


def test_leaf_source_filters_related_sibling_entries(tmp_path: Path) -> None:
    own_dir = tmp_path / "ace-run" / "20260703100000"
    sibling_dir = tmp_path / "ace-run" / "20260703100500"
    own_dir.mkdir(parents=True)
    sibling_dir.mkdir(parents=True)
    _write_call(own_dir, "own")
    _write_call(sibling_dir, "sibling")
    agent = _agent(own_dir)

    with patch(
        "sase.ace.tui.tools.cache.discover_related_tool_artifact_dirs_cached",
        return_value=([own_dir, sibling_dir], 1),
    ):
        sources = build_slow_tool_sources(agent)

    assert sources is not None
    assert len(sources) == 1
    assert sources[0].label is None
    assert [entry.tool_use_id for entry in sources[0].entries] == ["own"]


def test_root_sources_claim_shared_plan_dir_before_root(tmp_path: Path) -> None:
    root_dir = tmp_path / "ace-run" / "20260703100000"
    code_dir = tmp_path / "ace-run" / "20260703101000"
    root_dir.mkdir(parents=True)
    code_dir.mkdir(parents=True)
    _write_call(root_dir, "plan-call")
    _write_call(code_dir, "code-call")

    root = _agent(
        root_dir,
        agent_type=AgentType.WORKFLOW,
        cl_name="root",
        raw_suffix="root",
    )
    plan = _agent(
        root_dir,
        agent_type=AgentType.WORKFLOW,
        cl_name="plan",
        raw_suffix="plan",
        parent_workflow="wf",
        step_type="agent",
        role_suffix=PLAN_CHAIN_PLAN_SUFFIX,
        agent_family_role="plan",
    )
    code = _agent(
        code_dir,
        cl_name="code",
        raw_suffix="code",
        parent_timestamp="root",
        role_suffix=PLAN_CHAIN_CODER_SUFFIX,
        agent_family_role="code",
    )
    root.runtime_children.extend([plan, code])

    with patch(
        "sase.ace.tui.tools.cache.discover_related_tool_artifact_dirs_cached",
        side_effect=lambda _agent, artifacts_dir, **_kwargs: ([Path(artifacts_dir)], 1),
    ):
        sources = build_slow_tool_sources(root)

    assert sources is not None
    assert [
        (source.label, [e.tool_use_id for e in source.entries]) for source in sources
    ] == [
        ("plan", ["plan-call"]),
        ("code", ["code-call"]),
    ]


def test_source_labels_follow_role_step_name_agent_name_and_root_precedence(
    tmp_path: Path,
) -> None:
    root_dir = tmp_path / "ace-run" / "root"
    code_dir = tmp_path / "ace-run" / "code"
    feedback_dir = tmp_path / "ace-run" / "feedback"
    step_dir = tmp_path / "ace-run" / "step"
    name_dir = tmp_path / "ace-run" / "name"
    for directory in (root_dir, code_dir, feedback_dir, step_dir, name_dir):
        directory.mkdir(parents=True)
        (directory / "tool_calls.jsonl").write_text("", encoding="utf-8")

    root = _agent(root_dir, cl_name="root", raw_suffix="root", agent_name="04")
    code = _agent(
        code_dir,
        cl_name="code",
        raw_suffix="code",
        parent_timestamp="root",
        role_suffix=PLAN_CHAIN_CODER_SUFFIX,
        agent_family_role="code",
    )
    feedback = _agent(
        feedback_dir,
        cl_name="feedback",
        raw_suffix="feedback",
        parent_timestamp="root",
        role_suffix="--plan-0",
        agent_family_role="feedback",
    )
    step = _agent(
        step_dir,
        agent_type=AgentType.WORKFLOW,
        cl_name="step",
        raw_suffix="step",
        parent_workflow="wf",
        step_type="agent",
        step_name="review",
    )
    named = _agent(
        name_dir,
        cl_name="named",
        raw_suffix="named",
        parent_timestamp="root",
        agent_name="04--commit",
    )
    root.runtime_children.extend([code, feedback, step, named])

    with patch(
        "sase.ace.tui.tools.cache.discover_related_tool_artifact_dirs_cached",
        side_effect=lambda _agent, artifacts_dir, **_kwargs: ([Path(artifacts_dir)], 1),
    ):
        sources = build_slow_tool_sources(root)

    assert sources is not None
    assert [source.label for source in sources] == [
        "code",
        "fb2",
        "review",
        "commit",
        "root",
    ]


def test_source_activity_and_end_reference_are_per_row(tmp_path: Path) -> None:
    root_dir = tmp_path / "ace-run" / "root"
    child_dir = tmp_path / "ace-run" / "child"
    root_dir.mkdir(parents=True)
    child_dir.mkdir(parents=True)
    _write_call(root_dir, "root")
    _write_call(child_dir, "child")
    stopped_at = datetime(2026, 7, 3, 10, 30, 0)

    root = _agent(root_dir, cl_name="root", raw_suffix="root", status="RUNNING")
    child = _agent(
        child_dir,
        cl_name="child",
        raw_suffix="child",
        status="DONE",
        stop_time=stopped_at,
        parent_timestamp="root",
        agent_family_role="code",
        role_suffix=PLAN_CHAIN_CODER_SUFFIX,
    )
    root.runtime_children.append(child)

    with patch(
        "sase.ace.tui.tools.cache.discover_related_tool_artifact_dirs_cached",
        side_effect=lambda _agent, artifacts_dir, **_kwargs: ([Path(artifacts_dir)], 1),
    ):
        sources = build_slow_tool_sources(root)

    assert sources is not None
    child_source = sources[0]
    root_source = sources[1]
    assert child_source.label == "code"
    assert child_source.agent_is_active is False
    assert child_source.end_reference == stopped_at
    assert root_source.label == "root"
    assert root_source.agent_is_active is True


@pytest.mark.parametrize("status", ["PLAN APPROVED", "TALE APPROVED"])
def test_sticky_approved_source_is_not_active(tmp_path: Path, status: str) -> None:
    artifacts_dir = tmp_path / "ace-run" / "plan"
    artifacts_dir.mkdir(parents=True)
    _write_call(artifacts_dir, "propose")
    stopped_at = datetime(2026, 7, 3, 10, 30, 0)
    agent = _agent(artifacts_dir, status=status, stop_time=stopped_at)

    with patch(
        "sase.ace.tui.tools.cache.discover_related_tool_artifact_dirs_cached",
        return_value=([artifacts_dir], 1),
    ):
        sources = build_slow_tool_sources(agent)

    assert sources is not None
    assert sources[0].agent_is_active is False
    assert sources[0].end_reference == stopped_at


def test_missing_artifacts_dir_child_is_skipped(tmp_path: Path) -> None:
    root_dir = tmp_path / "ace-run" / "root"
    root_dir.mkdir(parents=True)
    _write_call(root_dir, "root")
    missing_dir = tmp_path / "ace-run" / "missing"

    root = _agent(root_dir, cl_name="root", raw_suffix="root")
    missing = _agent(
        missing_dir,
        cl_name="missing",
        raw_suffix="missing",
        parent_timestamp="root",
    )
    root.runtime_children.append(missing)

    with patch(
        "sase.ace.tui.tools.cache.discover_related_tool_artifact_dirs_cached",
        side_effect=lambda _agent, artifacts_dir, **_kwargs: ([Path(artifacts_dir)], 1),
    ):
        sources = build_slow_tool_sources(root)

    assert sources is not None
    assert [source.label for source in sources] == ["root"]
    assert supports_slow_tool_sources(root) is True
