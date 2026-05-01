"""Phase 3E: snapshot-backed `list_running_agents` / `list_all_agents`.

These tests exercise the post-Phase-3E call sites in
:mod:`sase.agent.running` against the Phase 3A golden artifact tree. They
pin the filters that the previous direct-walk implementation enforced
(parent-timestamp dedup, `appears_as_agent` skip, `outcome=="noop"`
filter, per-project completed cap) on the snapshot adapter.

Process liveness still lives in Python, so the tests stub
``sase.ace.hooks.processes.is_process_running`` rather than mocking the
snapshot.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from sase.agent.running import (
    _DONE_AGENTS_CAP_PER_PROJECT,
    RunningAgentInfo,
    list_all_agents,
    list_running_agents,
)
from tests.agent_scan_golden.fixture_builder import (
    TS_ACE_RUN_DONE,
    TS_ACE_RUN_FAILED,
    TS_ACE_RUN_RETRIED_CHILD,
    TS_ACE_RUN_RETRIED_PARENT,
    TS_ACE_RUN_RUNNING,
    TS_HOME_RUNNING,
    build_fixture_tree,
)


def _projects_root_for(home: Path) -> Path:
    return home / ".sase" / "projects"


def _ts(info: RunningAgentInfo) -> str:
    """Return the artifact-dir basename for *info* (asserts non-None for typecheckers)."""
    assert info.artifacts_dir is not None
    return Path(info.artifacts_dir).name


def _all_alive(_pid: int) -> bool:
    return True


def _none_alive(_pid: int) -> bool:
    return False


def test_list_running_agents_filters_done_and_dead(
    tmp_path: Path,
) -> None:
    """Running listing only emits live ace-run agents without done.json."""
    build_fixture_tree(_projects_root_for(tmp_path))
    with (
        patch("pathlib.Path.home", return_value=tmp_path),
        patch("sase.ace.hooks.processes.is_process_running", _all_alive),
    ):
        running = list_running_agents()

    by_ts = {_ts(info): info for info in running}

    # The retried child (TS_ACE_RUN_RETRIED_CHILD) has no done.json and
    # carries a live PID; the original direct walk emitted it as RUNNING
    # so the snapshot path must too. The waiting/malformed dirs lack a
    # parseable PID so liveness skips them.
    assert set(by_ts) == {
        TS_HOME_RUNNING,
        TS_ACE_RUN_RUNNING,
        TS_ACE_RUN_RETRIED_CHILD,
    }
    assert all(info.status == "RUNNING" for info in running)
    assert by_ts[TS_HOME_RUNNING].project == "home"
    assert by_ts[TS_ACE_RUN_RUNNING].project == "myproj"
    # Most-recent-first ordering preserved.
    assert [_ts(info) for info in running] == sorted(by_ts, reverse=True)


def test_list_running_agents_empty_when_processes_dead(tmp_path: Path) -> None:
    """When no PIDs are alive, the running list is empty even with markers present."""
    build_fixture_tree(_projects_root_for(tmp_path))
    with (
        patch("pathlib.Path.home", return_value=tmp_path),
        patch("sase.ace.hooks.processes.is_process_running", _none_alive),
    ):
        running = list_running_agents()
    assert running == []


def test_list_running_agents_skips_appears_as_agent_false(tmp_path: Path) -> None:
    """An ace-run dir with `appears_as_agent=False` workflow_state is skipped."""
    projects_root = _projects_root_for(tmp_path)
    build_fixture_tree(projects_root)
    # Drop a workflow_state.json next to the live ace-run agent flagging it
    # as a multi-step orchestrator that should NOT surface as its own row.
    wf_path = (
        projects_root
        / "myproj"
        / "artifacts"
        / "ace-run"
        / TS_ACE_RUN_RUNNING
        / "workflow_state.json"
    )
    wf_path.write_text(
        json.dumps({"workflow_name": "wf", "appears_as_agent": False}),
        encoding="utf-8",
    )

    with (
        patch("pathlib.Path.home", return_value=tmp_path),
        patch("sase.ace.hooks.processes.is_process_running", _all_alive),
    ):
        running = list_running_agents()

    assert TS_ACE_RUN_RUNNING not in {_ts(info) for info in running}


def test_list_running_agents_skips_parent_timestamp_followups(
    tmp_path: Path,
) -> None:
    """Follow-up agents with `parent_timestamp` set are deduped against parents."""
    projects_root = _projects_root_for(tmp_path)
    build_fixture_tree(projects_root)
    meta_path = (
        projects_root
        / "myproj"
        / "artifacts"
        / "ace-run"
        / TS_ACE_RUN_RUNNING
        / "agent_meta.json"
    )
    data = json.loads(meta_path.read_text(encoding="utf-8"))
    data["parent_timestamp"] = "20260101000000"
    meta_path.write_text(json.dumps(data), encoding="utf-8")

    with (
        patch("pathlib.Path.home", return_value=tmp_path),
        patch("sase.ace.hooks.processes.is_process_running", _all_alive),
    ):
        running = list_running_agents()

    assert TS_ACE_RUN_RUNNING not in {_ts(info) for info in running}


def test_list_running_agents_includes_plan_chain_followups(
    tmp_path: Path,
) -> None:
    """Independent plan-chain follow-ups are visible in CLI status listings."""
    projects_root = _projects_root_for(tmp_path)
    build_fixture_tree(projects_root)
    meta_path = (
        projects_root
        / "myproj"
        / "artifacts"
        / "ace-run"
        / TS_ACE_RUN_RUNNING
        / "agent_meta.json"
    )
    data = json.loads(meta_path.read_text(encoding="utf-8"))
    data["name"] = "a.coder"
    data["workflow_name"] = "a"
    data["parent_timestamp"] = "20260101000000"
    data["plan_chain_parent_timestamp"] = "20260101000000"
    data["role_suffix"] = ".coder"
    meta_path.write_text(json.dumps(data), encoding="utf-8")

    with (
        patch("pathlib.Path.home", return_value=tmp_path),
        patch("sase.ace.hooks.processes.is_process_running", _all_alive),
    ):
        running = list_running_agents()

    by_ts = {_ts(info): info for info in running}
    assert TS_ACE_RUN_RUNNING in by_ts
    assert by_ts[TS_ACE_RUN_RUNNING].name == "a.coder"


def test_list_all_agents_includes_done_and_failed(tmp_path: Path) -> None:
    """All-listing emits running + DONE/FAILED with running entries first."""
    build_fixture_tree(_projects_root_for(tmp_path))
    with (
        patch("pathlib.Path.home", return_value=tmp_path),
        patch("sase.ace.hooks.processes.is_process_running", _all_alive),
    ):
        agents = list_all_agents()

    by_ts = {_ts(info): info for info in agents}

    expected = {
        TS_HOME_RUNNING: "RUNNING",
        TS_ACE_RUN_RUNNING: "RUNNING",
        TS_ACE_RUN_RETRIED_CHILD: "RUNNING",
        TS_ACE_RUN_DONE: "DONE",
        TS_ACE_RUN_FAILED: "FAILED",
        TS_ACE_RUN_RETRIED_PARENT: "FAILED",
    }
    assert set(by_ts) == set(expected)
    for ts, status in expected.items():
        assert by_ts[ts].status == status, (ts, by_ts[ts].status)

    # Running agents must precede completed agents in the returned list.
    statuses = [info.status for info in agents]
    last_running = max(i for i, s in enumerate(statuses) if s == "RUNNING")
    first_terminal = min(i for i, s in enumerate(statuses) if s in {"DONE", "FAILED"})
    assert last_running < first_terminal


def test_list_all_agents_skips_noop_outcome(tmp_path: Path) -> None:
    """`outcome="noop"` done agents are filtered from the listing."""
    projects_root = _projects_root_for(tmp_path)
    build_fixture_tree(projects_root)
    done_path = (
        projects_root
        / "myproj"
        / "artifacts"
        / "ace-run"
        / TS_ACE_RUN_DONE
        / "done.json"
    )
    data = json.loads(done_path.read_text(encoding="utf-8"))
    data["outcome"] = "noop"
    done_path.write_text(json.dumps(data), encoding="utf-8")

    with (
        patch("pathlib.Path.home", return_value=tmp_path),
        patch("sase.ace.hooks.processes.is_process_running", _all_alive),
    ):
        agents = list_all_agents()

    assert TS_ACE_RUN_DONE not in {_ts(info) for info in agents}


def test_list_all_agents_per_project_cap(tmp_path: Path) -> None:
    """`cap_per_project` bounds the number of completed entries per project."""
    projects_root = _projects_root_for(tmp_path)
    projects_root.mkdir(parents=True)
    project_dir = projects_root / "bigproj" / "artifacts" / "ace-run"
    project_dir.mkdir(parents=True)

    base = 20260101000000
    extra = _DONE_AGENTS_CAP_PER_PROJECT + 5
    for i in range(extra):
        ts = str(base + i)
        artifact_dir = project_dir / ts
        artifact_dir.mkdir()
        (artifact_dir / "done.json").write_text(
            json.dumps({"outcome": "completed"}),
            encoding="utf-8",
        )

    with patch("pathlib.Path.home", return_value=tmp_path):
        agents = list_all_agents(cap_per_project=_DONE_AGENTS_CAP_PER_PROJECT)

    bigproj = [a for a in agents if a.project == "bigproj"]
    assert len(bigproj) == _DONE_AGENTS_CAP_PER_PROJECT
    # Cap keeps the newest entries (descending timestamp).
    kept_ts = sorted((_ts(info) for info in bigproj), reverse=True)
    assert kept_ts[0] == str(base + extra - 1)
    assert kept_ts[-1] == str(base + extra - _DONE_AGENTS_CAP_PER_PROJECT)


def test_list_all_agents_carries_done_metadata(tmp_path: Path) -> None:
    """DONE entries carry workspace_num, model, provider, and prompt snippet."""
    projects_root = _projects_root_for(tmp_path)
    build_fixture_tree(projects_root)
    raw_prompt = projects_root / "myproj" / "artifacts" / "ace-run" / TS_ACE_RUN_DONE
    (raw_prompt / "raw_xprompt.md").write_text(
        "Land the alpha feature\n", encoding="utf-8"
    )

    with (
        patch("pathlib.Path.home", return_value=tmp_path),
        patch("sase.ace.hooks.processes.is_process_running", _none_alive),
    ):
        agents = list_all_agents()

    done_alpha = next(a for a in agents if _ts(a) == TS_ACE_RUN_DONE)
    assert done_alpha.status == "DONE"
    assert done_alpha.workspace_num == 3
    assert done_alpha.model == "claude-haiku-4-5-20251001"
    assert done_alpha.provider == "claude"
    assert done_alpha.prompt == "Land the alpha feature"
