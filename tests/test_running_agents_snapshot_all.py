"""Phase 3E: snapshot-backed `list_all_agents`.

These tests pin completed-agent filters (`outcome=="noop"`, per-project
cap), host-TID collision handling, and index-backed listing equivalence
on the snapshot adapter.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from sase.agent.running import (
    _DONE_AGENTS_CAP_PER_PROJECT,
    list_all_agents,
    list_running_agents,
)
from sase.agent.running_listing import _done_from_snapshot, _running_from_snapshot
from sase.core import process_identity
from sase.core.agent_scan_facade import (
    rebuild_agent_artifact_index,
    scan_agent_artifacts,
)
from sase.core.agent_scan_wire import AgentArtifactScanOptionsWire
from tests._running_agents_snapshot_helpers import (
    artifact_timestamp,
    fixture_processes,
    listing_projection,
    projects_root_for,
)
from tests.agent_scan_golden.fixture_builder import (
    TS_ACE_RUN_DONE,
    TS_ACE_RUN_FAILED,
    TS_ACE_RUN_REPEAT_STOPPED,
    TS_ACE_RUN_RETRIED_CHILD,
    TS_ACE_RUN_RETRIED_PARENT,
    TS_ACE_RUN_RUNNING,
    TS_HOME_RUNNING,
    build_fixture_tree,
)


def test_list_all_agents_includes_done_and_failed(tmp_path: Path) -> None:
    """All-listing emits running + DONE/FAILED with running entries first."""
    build_fixture_tree(projects_root_for(tmp_path))
    with fixture_processes(tmp_path, alive=True):
        agents = list_all_agents()

    by_ts = {artifact_timestamp(info): info for info in agents}

    expected = {
        TS_HOME_RUNNING: "RUNNING",
        TS_ACE_RUN_RUNNING: "STARTING",
        TS_ACE_RUN_RETRIED_CHILD: "STARTING",
        TS_ACE_RUN_DONE: "DONE",
        # The repeat-stopped slot keeps ``outcome: "completed"``; the plain CLI
        # listing surfaces it as DONE (the distinct STOPPED display is a TUI
        # Agents-tab concern), while still appearing in the all-agents list.
        TS_ACE_RUN_REPEAT_STOPPED: "DONE",
        TS_ACE_RUN_FAILED: "FAILED",
        TS_ACE_RUN_RETRIED_PARENT: "FAILED",
    }
    assert set(by_ts) == set(expected)
    for ts, status in expected.items():
        assert by_ts[ts].status == status, (ts, by_ts[ts].status)

    # Active agents must precede completed agents in the returned list.
    statuses = [info.status for info in agents]
    last_active = max(i for i, s in enumerate(statuses) if s in {"STARTING", "RUNNING"})
    first_terminal = min(i for i, s in enumerate(statuses) if s in {"DONE", "FAILED"})
    assert last_active < first_terminal


def test_index_backed_listing_matches_source_snapshot_on_fixture_archive(
    tmp_path: Path,
    monkeypatch,
) -> None:
    projects_root = projects_root_for(tmp_path)
    build_fixture_tree(projects_root)
    scan_options = AgentArtifactScanOptionsWire(
        include_prompt_step_markers=False,
        only_workflow_dirs=("ace-run",),
    )
    source_snapshot = scan_agent_artifacts(projects_root, scan_options)
    index_path = tmp_path / ".sase" / "agent_artifact_index.sqlite"
    rebuild_agent_artifact_index(index_path, projects_root, scan_options)

    with fixture_processes(tmp_path, alive=True):
        expected_running = _running_from_snapshot(source_snapshot)
        expected_all = expected_running + _done_from_snapshot(
            source_snapshot,
            cap_per_project=_DONE_AGENTS_CAP_PER_PROJECT,
        )

    monkeypatch.setattr(
        "sase.core.agent_scan_facade.default_agent_artifact_index_path",
        lambda: index_path,
    )
    monkeypatch.setattr(
        "sase.agent.listing_snapshot.sase_projects_dir",
        lambda: projects_root,
    )
    monkeypatch.setattr(
        "sase.agent.listing_snapshot._scan_listing_snapshot",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("source scan should not run for indexed fixture")
        ),
    )

    with fixture_processes(tmp_path, alive=True):
        running = list_running_agents()
        all_agents = list_all_agents()

    assert listing_projection(running) == listing_projection(expected_running)
    assert listing_projection(all_agents) == listing_projection(expected_all)


def test_list_all_agents_includes_retried_child_when_host_tid_collides(
    tmp_path: Path,
) -> None:
    """A host TID equal to the retried child's fixture PID must not hide it."""
    projects_root = projects_root_for(tmp_path)
    build_fixture_tree(projects_root)
    child_meta = json.loads(
        (
            projects_root
            / "myproj"
            / "artifacts"
            / "ace-run"
            / TS_ACE_RUN_RETRIED_CHILD
            / "agent_meta.json"
        ).read_text(encoding="utf-8")
    )
    child_pid = int(child_meta["pid"])
    proc_root = tmp_path / "host-proc"
    thread_dir = proc_root / str(child_pid)
    thread_dir.mkdir(parents=True)
    (thread_dir / "status").write_text(
        f"Name:\tci-worker\nTgid:\t1000\nPid:\t{child_pid}\n",
        encoding="utf-8",
    )

    with (
        patch.object(process_identity, "_PROC_ROOT", proc_root),
        fixture_processes(tmp_path, alive=True),
    ):
        agents = list_all_agents()

    by_ts = {artifact_timestamp(info): info for info in agents}
    assert TS_ACE_RUN_RETRIED_CHILD in by_ts
    assert by_ts[TS_ACE_RUN_RETRIED_CHILD].status == "STARTING"


def test_list_all_agents_skips_noop_outcome(tmp_path: Path) -> None:
    """`outcome="noop"` done agents are filtered from the listing."""
    projects_root = projects_root_for(tmp_path)
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

    with fixture_processes(tmp_path, alive=True):
        agents = list_all_agents()

    assert TS_ACE_RUN_DONE not in {artifact_timestamp(info) for info in agents}


def test_list_all_agents_per_project_cap(tmp_path: Path) -> None:
    """`cap_per_project` bounds the number of completed entries per project."""
    projects_root = projects_root_for(tmp_path)
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
    kept_ts = sorted((artifact_timestamp(info) for info in bigproj), reverse=True)
    assert kept_ts[0] == str(base + extra - 1)
    assert kept_ts[-1] == str(base + extra - _DONE_AGENTS_CAP_PER_PROJECT)


def test_list_all_agents_carries_done_metadata(tmp_path: Path) -> None:
    """DONE entries carry workspace_num, model, provider, and prompt snippet."""
    projects_root = projects_root_for(tmp_path)
    build_fixture_tree(projects_root)
    raw_prompt = projects_root / "myproj" / "artifacts" / "ace-run" / TS_ACE_RUN_DONE
    (raw_prompt / "raw_xprompt.md").write_text(
        "Land the alpha feature\n", encoding="utf-8"
    )

    with fixture_processes(tmp_path, alive=False):
        agents = list_all_agents()

    done_alpha = next(a for a in agents if artifact_timestamp(a) == TS_ACE_RUN_DONE)
    assert done_alpha.status == "DONE"
    assert done_alpha.workspace_num == 3
    assert done_alpha.model == "claude-haiku-4-5-20251001"
    assert done_alpha.provider == "claude"
    assert done_alpha.prompt == "Land the alpha feature"
