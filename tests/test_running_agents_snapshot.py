"""Phase 3E: snapshot-backed `list_running_agents` / `list_all_agents`.

These tests exercise the post-Phase-3E call sites in
:mod:`sase.agent.running` against the Phase 3A golden artifact tree. They
pin the filters that the previous direct-walk implementation enforced
(parent-timestamp dedup, `appears_as_agent` skip, `outcome=="noop"`
filter, per-project completed cap) on the snapshot adapter.

Process liveness still lives in Python, so the tests stub the process-running
probe, the Linux ``/proc/<pid>/cmdline`` PID-reuse guard, and
``pid_is_thread`` rather than mocking the snapshot. Fixture PIDs such as
``33333`` can collide with a live thread ID on a busy CI runner; without the
thread stub ``list_all_agents`` drops the retried child.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import json
from pathlib import Path
from unittest.mock import patch

from sase.agent.running import (
    _DONE_AGENTS_CAP_PER_PROJECT,
    _active_status_for_record,
    RunningAgentInfo,
    list_all_agents,
    list_running_agents,
)
from sase.agent.listing_snapshot import listing_snapshot
from sase.agent.running_listing import _done_from_snapshot, _running_from_snapshot
from sase.core.agent_scan_wire import (
    AgentArtifactIndexQueryWire,
    AgentArtifactIndexStatusWire,
    AgentArtifactIndexWindowWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanStatsWire,
    AgentArtifactScanWire,
    AgentArtifactRecordWire,
    AgentMetaWire,
    PendingQuestionMarkerWire,
    WaitingMarkerWire,
)
from sase.core import process_identity
from sase.core.agent_scan_facade import (
    rebuild_agent_artifact_index,
    scan_agent_artifacts,
)
from sase.core.runner_slots import running_agent_slot_count
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


def _projects_root_for(home: Path) -> Path:
    return home / ".sase" / "projects"


def _ts(info: RunningAgentInfo) -> str:
    """Return the artifact-dir basename for *info* (asserts non-None for typecheckers)."""
    assert info.artifacts_dir is not None
    return Path(info.artifacts_dir).name


def _listing_projection(
    rows: list[RunningAgentInfo],
) -> list[tuple[str, str, str, str | None, bool | None]]:
    return [
        (_ts(info), info.project, info.status, info.name, info.holds_runner_slot)
        for info in rows
    ]


def _is_proc_cmdline(path: Path) -> bool:
    parts = path.parts
    return (
        len(parts) == 4
        and parts[0] == "/"
        and parts[1] == "proc"
        and parts[2].isdigit()
        and parts[3] == "cmdline"
    )


@contextmanager
def _fixture_processes(home: Path, *, alive: bool) -> Iterator[None]:
    original_read_bytes = Path.read_bytes

    def is_process_running(_pid: int) -> bool:
        return alive

    def read_bytes(path: Path) -> bytes:
        if alive and _is_proc_cmdline(path):
            return b"python\x00-m\x00sase\x00"
        return original_read_bytes(path)

    with (
        patch("pathlib.Path.home", return_value=home),
        patch("sase.ace.hooks.processes.is_process_running", is_process_running),
        patch.object(process_identity, "current_boot_time_utc", return_value=None),
        # Fixture PIDs can collide with a live host TID; keep them as processes.
        patch.object(process_identity, "pid_is_thread", return_value=False),
        patch.object(Path, "read_bytes", read_bytes),
    ):
        yield


def test_list_running_agents_filters_done_and_dead(
    tmp_path: Path,
) -> None:
    """Running listing only emits live ace-run agents without done.json."""
    build_fixture_tree(_projects_root_for(tmp_path))
    with _fixture_processes(tmp_path, alive=True):
        running = list_running_agents()

    by_ts = {_ts(info): info for info in running}

    # The retried child (TS_ACE_RUN_RETRIED_CHILD) has no done.json and
    # carries a live PID. Records without run_started_at are visible as
    # STARTING until execution reaches the RUN timestamp write.
    assert set(by_ts) == {
        TS_HOME_RUNNING,
        TS_ACE_RUN_RUNNING,
        TS_ACE_RUN_RETRIED_CHILD,
    }
    assert by_ts[TS_HOME_RUNNING].status == "RUNNING"
    assert by_ts[TS_ACE_RUN_RUNNING].status == "STARTING"
    assert by_ts[TS_ACE_RUN_RETRIED_CHILD].status == "STARTING"
    assert by_ts[TS_ACE_RUN_RUNNING].duration == "?"
    assert by_ts[TS_ACE_RUN_RUNNING].duration_seconds is None
    assert by_ts[TS_HOME_RUNNING].project == "home"
    assert by_ts[TS_ACE_RUN_RUNNING].project == "myproj"
    # Most-recent-first ordering preserved.
    assert [_ts(info) for info in running] == sorted(by_ts, reverse=True)


def test_list_running_agents_empty_when_processes_dead(tmp_path: Path) -> None:
    """When no PIDs are alive, the running list is empty even with markers present."""
    build_fixture_tree(_projects_root_for(tmp_path))
    with _fixture_processes(tmp_path, alive=False):
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

    with _fixture_processes(tmp_path, alive=True):
        running = list_running_agents()

    assert TS_ACE_RUN_RUNNING not in {_ts(info) for info in running}


def test_list_running_agents_skips_non_parallel_parent_timestamp_followups(
    tmp_path: Path,
) -> None:
    """Non-slot family helpers stay folded instead of becoming CLI rows."""
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

    with _fixture_processes(tmp_path, alive=True):
        running = list_running_agents()

    assert TS_ACE_RUN_RUNNING not in {_ts(info) for info in running}


def _synthetic_record(
    tmp_path: Path,
    timestamp: str,
    name: str,
    *,
    run_started: bool = False,
    parent_timestamp: str | None = None,
    agent_family: str | None = None,
    agent_family_parallel: bool = False,
    waiting_for: list[str] | None = None,
    slot_requested_at: str | None = None,
    pending_question: bool = False,
    done: bool = False,
) -> AgentArtifactRecordWire:
    return AgentArtifactRecordWire(
        project_name="proj",
        project_dir=str(tmp_path / "proj"),
        project_file=str(tmp_path / "proj" / "proj.sase"),
        workflow_dir_name="ace-run",
        artifact_dir=str(tmp_path / "proj" / "artifacts" / "ace-run" / timestamp),
        timestamp=timestamp,
        agent_meta=AgentMetaWire(
            name=name,
            pid=100,
            parent_timestamp=parent_timestamp,
            agent_family=agent_family,
            agent_family_parallel=agent_family_parallel,
            run_started_at=("2026-07-17T12:00:00-04:00" if run_started else None),
        ),
        waiting=(
            WaitingMarkerWire(
                waiting_for=waiting_for or [],
                wait_runners=0 if slot_requested_at else None,
                slot_requested_at=slot_requested_at,
            )
            if waiting_for or slot_requested_at
            else None
        ),
        pending_question=(
            PendingQuestionMarkerWire(session_id="question")
            if pending_question
            else None
        ),
        has_done_marker=done,
    )


def _synthetic_snapshot(
    tmp_path: Path, records: list[AgentArtifactRecordWire]
) -> AgentArtifactScanWire:
    return AgentArtifactScanWire(
        schema_version=1,
        projects_root=str(tmp_path),
        options=AgentArtifactScanOptionsWire(),
        stats=AgentArtifactScanStatsWire(),
        records=records,
    )


def test_list_running_agents_surfaces_slot_relevant_parallel_children(
    tmp_path: Path,
) -> None:
    root_timestamp = "20260717120000"
    records = [
        _synthetic_record(
            tmp_path,
            root_timestamp,
            "root",
            waiting_for=["dependency"],
        ),
        _synthetic_record(
            tmp_path,
            "20260717120001",
            "running-phase",
            run_started=True,
            parent_timestamp=root_timestamp,
            agent_family_parallel=True,
        ),
        _synthetic_record(
            tmp_path,
            "20260717120002",
            "serial-helper",
            run_started=True,
            parent_timestamp=root_timestamp,
        ),
        _synthetic_record(
            tmp_path,
            "20260717120003",
            "dependency-phase",
            parent_timestamp=root_timestamp,
            agent_family_parallel=True,
            waiting_for=["dependency"],
        ),
        _synthetic_record(
            tmp_path,
            "20260717120004",
            "queued-phase",
            parent_timestamp=root_timestamp,
            agent_family_parallel=True,
            slot_requested_at="2026-07-17T12:00:04-04:00",
        ),
    ]
    snapshot = _synthetic_snapshot(tmp_path, records)

    with (
        _fixture_processes(tmp_path, alive=True),
        patch(
            "sase.agent.listing_snapshot._scan_listing_snapshot",
            return_value=snapshot,
        ),
    ):
        running = list_running_agents()

    by_name = {info.name: info for info in running}
    # A live serial child -- a real agent shell doing work, not a monitor --
    # must never go missing from the listing just because it never itself
    # waits at the admission gate.
    assert set(by_name) == {
        "root",
        "running-phase",
        "serial-helper",
        "queued-phase",
    }
    assert by_name["root"].status == "WAITING"
    assert by_name["running-phase"].status == "RUNNING"
    assert by_name["running-phase"].holds_runner_slot is True
    assert by_name["serial-helper"].status == "RUNNING"
    assert by_name["serial-helper"].holds_runner_slot is True
    assert by_name["queued-phase"].status == "WAITING"
    assert by_name["queued-phase"].holds_runner_slot is False


def test_running_listing_slot_occupancy_matches_admission_count(tmp_path: Path) -> None:
    root_timestamp = "20260717130000"
    records = [
        _synthetic_record(
            tmp_path,
            root_timestamp,
            "root",
            run_started=True,
            agent_family="root",
        ),
        _synthetic_record(
            tmp_path,
            "20260717130001",
            "parallel",
            run_started=True,
            parent_timestamp=root_timestamp,
            agent_family="root",
            agent_family_parallel=True,
        ),
        _synthetic_record(
            tmp_path,
            "20260717130002",
            "serial",
            run_started=True,
            parent_timestamp=root_timestamp,
            agent_family="root",
        ),
        _synthetic_record(
            tmp_path,
            "20260717130003",
            "done",
            run_started=True,
            done=True,
        ),
        _synthetic_record(
            tmp_path,
            "20260717130004",
            "question",
            run_started=True,
            pending_question=True,
        ),
    ]
    snapshot = _synthetic_snapshot(tmp_path, records)

    with _fixture_processes(tmp_path, alive=True):
        listed = _running_from_snapshot(snapshot)

    admission_count = running_agent_slot_count(records, lambda _record: True)
    assert admission_count == sum(bool(info.holds_runner_slot) for info in listed)


def test_listing_snapshot_uses_bounded_index_query_with_project_pushdown(
    tmp_path: Path,
    monkeypatch,
) -> None:
    index_path = tmp_path / "agent_artifact_index.sqlite"
    index_path.touch()
    snapshot = AgentArtifactScanWire(
        schema_version=1,
        projects_root=str(tmp_path),
        options=AgentArtifactScanOptionsWire(),
        stats=AgentArtifactScanStatsWire(),
        index_window=AgentArtifactIndexWindowWire(
            requested_limit=25,
            selected_candidate_count=3,
            returned_record_count=2,
            active_candidate_count=1,
            completed_candidate_count=2,
            has_more=True,
        ),
        records=[],
    )
    calls: list[
        tuple[
            Path,
            Path,
            AgentArtifactIndexQueryWire,
            AgentArtifactScanOptionsWire,
        ]
    ] = []

    def fake_query_agent_artifact_index(
        path: Path,
        projects_root: Path,
        *,
        query: AgentArtifactIndexQueryWire,
        options: AgentArtifactScanOptionsWire,
    ) -> AgentArtifactScanWire:
        calls.append((path, projects_root, query, options))
        return snapshot

    monkeypatch.setattr(
        "sase.core.agent_scan_facade.default_agent_artifact_index_path",
        lambda: index_path,
    )
    monkeypatch.setattr(
        "sase.core.agent_scan_facade.query_agent_artifact_index",
        fake_query_agent_artifact_index,
    )
    monkeypatch.setattr(
        "sase.agent.listing_snapshot.sase_projects_dir",
        lambda: tmp_path,
    )
    monkeypatch.setattr(
        "sase.agent.listing_snapshot._scan_listing_snapshot",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("source scan should not run when index query succeeds")
        ),
    )

    loaded, state = listing_snapshot(
        project="proj",
        index_freshness="revalidate",
        requested_limit=25,
    )

    assert loaded is snapshot
    assert state.used_artifact_index is True
    assert state.bounded_prefix is True
    assert state.requested_limit == 25
    assert state.returned_count == 2
    assert state.has_more is True
    [(path, projects_root, query, options)] = calls
    assert path == index_path
    assert projects_root == tmp_path
    assert query.include_active is True
    assert query.include_recent_completed is True
    assert query.include_full_history is False
    assert query.active_limit == 1000
    assert query.recent_completed_limit == 200
    assert query.include_hidden is False
    assert query.freshness == "revalidate"
    assert query.record_shape == "list"
    assert query.window_limit == 25
    assert query.candidate_filter == {
        "kind": "equals",
        "field": "project",
        "value": "proj",
    }
    assert options.only_projects == ("proj",)
    assert options.only_workflow_dirs == ("ace-run",)
    assert options.include_prompt_step_markers is False


def test_listing_snapshot_missing_index_uses_bounded_source_fallback(
    tmp_path: Path,
    monkeypatch,
) -> None:
    snapshot = _synthetic_snapshot(tmp_path, [])
    scan_options: list[AgentArtifactScanOptionsWire | None] = []

    def fake_scan_listing_snapshot(
        options: AgentArtifactScanOptionsWire | None = None,
    ) -> AgentArtifactScanWire:
        scan_options.append(options)
        return snapshot

    monkeypatch.setattr(
        "sase.core.agent_scan_facade.default_agent_artifact_index_path",
        lambda: tmp_path / "missing.sqlite",
    )
    monkeypatch.setattr(
        "sase.agent.listing_snapshot.sase_projects_dir",
        lambda: tmp_path,
    )
    monkeypatch.setattr(
        "sase.agent.listing_snapshot._scan_listing_snapshot",
        fake_scan_listing_snapshot,
    )

    loaded, state = listing_snapshot(project="proj")

    assert loaded is snapshot
    assert state.artifact_source == "source_scan"
    assert state.used_artifact_index is False
    assert state.repair_recommended is True
    assert state.repair_reason == "artifact_index_missing_bounded_fallback"
    [options] = scan_options
    assert options is not None
    assert options.max_records == 200
    assert options.newest_first is True
    assert options.only_projects == ("proj",)


def test_listing_snapshot_empty_index_uses_bounded_source_fallback(
    tmp_path: Path,
    monkeypatch,
) -> None:
    index_path = tmp_path / "agent_artifact_index.sqlite"
    index_path.touch()
    indexed = _synthetic_snapshot(tmp_path, [])
    fallback = _synthetic_snapshot(
        tmp_path,
        [_synthetic_record(tmp_path, "20260717130005", "manual", done=True)],
    )
    scan_options: list[AgentArtifactScanOptionsWire | None] = []

    def fake_scan_listing_snapshot(
        options: AgentArtifactScanOptionsWire | None = None,
    ) -> AgentArtifactScanWire:
        scan_options.append(options)
        return fallback

    monkeypatch.setattr(
        "sase.core.agent_scan_facade.default_agent_artifact_index_path",
        lambda: index_path,
    )
    monkeypatch.setattr(
        "sase.core.agent_scan_facade.query_agent_artifact_index",
        lambda *_args, **_kwargs: indexed,
    )
    monkeypatch.setattr(
        "sase.core.agent_scan_facade.agent_artifact_index_status",
        lambda _path: AgentArtifactIndexStatusWire(
            schema_version=1,
            index_path=str(index_path),
            agent_artifacts_rows=0,
        ),
    )
    monkeypatch.setattr(
        "sase.agent.listing_snapshot.sase_projects_dir",
        lambda: tmp_path,
    )
    monkeypatch.setattr(
        "sase.agent.listing_snapshot._scan_listing_snapshot",
        fake_scan_listing_snapshot,
    )

    loaded, state = listing_snapshot()

    assert loaded is fallback
    assert state.artifact_source == "source_scan"
    assert state.used_artifact_index is False
    assert state.repair_recommended is True
    assert state.repair_reason == "artifact_index_empty_bounded_fallback"
    [options] = scan_options
    assert options is not None
    assert options.max_records == 200
    assert options.newest_first is True


def test_list_running_agents_reports_waiting_marker(tmp_path: Path) -> None:
    """A live pre-run wait marker is reported as WAITING, not RUNNING."""
    projects_root = _projects_root_for(tmp_path)
    build_fixture_tree(projects_root)
    artifact_dir = (
        projects_root / "myproj" / "artifacts" / "ace-run" / TS_ACE_RUN_RUNNING
    )
    (artifact_dir / "waiting.json").write_text(
        json.dumps({"waiting_for": ["upstream"]}),
        encoding="utf-8",
    )

    with _fixture_processes(tmp_path, alive=True):
        running = list_running_agents()

    by_ts = {_ts(info): info for info in running}
    assert by_ts[TS_ACE_RUN_RUNNING].status == "WAITING"
    assert by_ts[TS_ACE_RUN_RUNNING].duration == "?"
    assert by_ts[TS_ACE_RUN_RUNNING].duration_seconds is None


def test_active_status_for_record_reports_wait_completed_as_running() -> None:
    """Post-wait/pre-run-start records are active RUNNING rows."""
    record = AgentArtifactRecordWire(
        project_name="proj",
        project_dir="/tmp/proj",
        project_file="/tmp/proj/proj.gp",
        workflow_dir_name="ace-run",
        artifact_dir="/tmp/proj/artifacts/ace-run/20260513120000",
        timestamp="20260513120000",
        agent_meta=AgentMetaWire(wait_completed_at="2026-05-13T16:00:00Z"),
    )

    assert _active_status_for_record(record) == "RUNNING"


def test_active_status_for_answered_question_queued_on_runner_slot(
    tmp_path: Path,
) -> None:
    request_path = tmp_path / "question_request.json"
    request_path.write_text("{}")
    (tmp_path / "question_response.json").write_text("{}")
    record = AgentArtifactRecordWire(
        project_name="proj",
        project_dir="/tmp/proj",
        project_file="/tmp/proj/proj.gp",
        workflow_dir_name="ace-run",
        artifact_dir="/tmp/proj/artifacts/ace-run/20260513120000",
        timestamp="20260513120000",
        agent_meta=AgentMetaWire(run_started_at="2026-05-13T16:00:00Z"),
        pending_question=PendingQuestionMarkerWire(request_path=str(request_path)),
        waiting=WaitingMarkerWire(
            wait_runners=0,
            slot_requested_at="2026-05-13T16:05:00Z",
        ),
    )

    assert _active_status_for_record(record) == "WAITING"


def test_list_all_agents_includes_done_and_failed(tmp_path: Path) -> None:
    """All-listing emits running + DONE/FAILED with running entries first."""
    build_fixture_tree(_projects_root_for(tmp_path))
    with _fixture_processes(tmp_path, alive=True):
        agents = list_all_agents()

    by_ts = {_ts(info): info for info in agents}

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
    projects_root = _projects_root_for(tmp_path)
    build_fixture_tree(projects_root)
    scan_options = AgentArtifactScanOptionsWire(
        include_prompt_step_markers=False,
        only_workflow_dirs=("ace-run",),
    )
    source_snapshot = scan_agent_artifacts(projects_root, scan_options)
    index_path = tmp_path / ".sase" / "agent_artifact_index.sqlite"
    rebuild_agent_artifact_index(index_path, projects_root, scan_options)

    with _fixture_processes(tmp_path, alive=True):
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

    with _fixture_processes(tmp_path, alive=True):
        running = list_running_agents()
        all_agents = list_all_agents()

    assert _listing_projection(running) == _listing_projection(expected_running)
    assert _listing_projection(all_agents) == _listing_projection(expected_all)


def test_list_all_agents_includes_retried_child_when_host_tid_collides(
    tmp_path: Path,
) -> None:
    """A host TID equal to the retried child's fixture PID must not hide it."""
    projects_root = _projects_root_for(tmp_path)
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
        _fixture_processes(tmp_path, alive=True),
    ):
        agents = list_all_agents()

    by_ts = {_ts(info): info for info in agents}
    assert TS_ACE_RUN_RETRIED_CHILD in by_ts
    assert by_ts[TS_ACE_RUN_RETRIED_CHILD].status == "STARTING"


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

    with _fixture_processes(tmp_path, alive=True):
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

    with _fixture_processes(tmp_path, alive=False):
        agents = list_all_agents()

    done_alpha = next(a for a in agents if _ts(a) == TS_ACE_RUN_DONE)
    assert done_alpha.status == "DONE"
    assert done_alpha.workspace_num == 3
    assert done_alpha.model == "claude-haiku-4-5-20251001"
    assert done_alpha.provider == "claude"
    assert done_alpha.prompt == "Land the alpha feature"
