"""Monitor retention: completion, resume, and edge-case paths.

Covers prepared host completion, repeated settlement, resume transfer and
degraded resume, stale claims, the proc settlement entry point, linked-repo
baselines, unavailable checkouts, and stale-binding retry.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.continuation_capture.rollout import (
    MONITOR_CONTINUATION_PROTOCOL_RECORDS_V1,
)
from sase.monitor.followup import FollowupLaunchResult
from sase.monitor.output import OutputCapture
from sase.monitor._settlement_retention import release_monitor_claim
from sase.monitor.settlement import settle_claim_and_followup
from sase.running_field import WorkspaceClaim, get_claimed_workspaces

from ._fixtures import make_starter_agent, write_project_file
from ._retention_fixtures import (
    RETENTION_CLAIM_WORKFLOW,
    fail_fresh_python_c,
    init_retention_repo,
    make_retention_monitor,
    no_launch_followup,
    pending_retention_record,
    persist_retention_delivery,
    read_retention_meta,
    retention_record,
    transfer_retention_to_successor,
    write_opened_linked,
    write_retention_meta,
)


@pytest.fixture(autouse=True)
def _sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)


def _write_monitor_baselines(
    artifacts_dir: str,
    repos: list[tuple[str, Path]],
    *,
    capture_fingerprints: bool = False,
) -> None:
    """Write a finalizer baseline covering *repos*."""
    import json

    from sase.llm_provider.commit_finalizer_baseline import FINALIZER_BASELINE_FILENAME
    from sase.llm_provider.commit_finalizer_git import normalize_path
    from sase.llm_provider.commit_finalizer_git_status import dirty_path_fingerprints

    payload = {
        "schema_version": 1,
        "repositories": [
            {
                "repo_id": repo_id,
                "path": normalize_path(str(path)),
                "kind": "primary" if repo_id == "primary" else "linked",
                "name": repo_id,
                "scope": "run_start",
                "captured_at": "2026-01-01T00:00:00+00:00",
                "fingerprints": {
                    dirty_path: list(fingerprint)
                    for dirty_path, fingerprint in dirty_path_fingerprints(
                        str(path)
                    ).items()
                }
                if capture_fingerprints
                else {},
            }
            for repo_id, path in repos
        ],
    }
    (Path(artifacts_dir) / FINALIZER_BASELINE_FILENAME).write_text(
        json.dumps(payload), encoding="utf-8"
    )


def test_prepared_completion_success_releases_clean(tmp_path: Path) -> None:
    """A committed host completion releases a clean workspace normally."""
    from sase.monitor._host_completion_shared import HOST_COMPLETED_OUTCOME

    repo = init_retention_repo(tmp_path / "ws", dirty=False)
    artifacts_dir, project_file = make_retention_monitor(
        repo, outcome=HOST_COMPLETED_OUTCOME
    )
    meta = read_retention_meta(artifacts_dir)

    error = release_monitor_claim(
        meta, project_name="proj", artifacts_dir=artifacts_dir
    )

    assert error is None
    assert get_claimed_workspaces(project_file) == []


def test_prepared_completion_failure_retains_dirty(tmp_path: Path) -> None:
    """A failed completion with unresolved dirt retains the workspace."""
    repo = init_retention_repo(tmp_path / "ws", dirty=True)
    artifacts_dir, project_file = make_retention_monitor(repo, outcome="not-launchable")
    meta = read_retention_meta(artifacts_dir)

    error = release_monitor_claim(
        meta, project_name="proj", artifacts_dir=artifacts_dir
    )

    assert error is None
    claims = get_claimed_workspaces(project_file)
    assert len(claims) == 1
    assert claims[0].pinned is True
    assert (repo / "tracked.txt").read_text() == "session owned\n"


def test_repeated_settlement_is_idempotent(tmp_path: Path) -> None:
    """Settling twice pins once and keeps the checkout intact."""
    repo = init_retention_repo(tmp_path / "ws", dirty=True)
    artifacts_dir, project_file = make_retention_monitor(repo)
    meta = read_retention_meta(artifacts_dir)

    first = settle_claim_and_followup(
        artifacts_dir,
        meta,
        monitor_state="stopped",
        exit_code=None,
        elapsed_seconds=0.0,
        capture=OutputCapture(),
        timeout_kind=None,
        project_name="proj",
        launch_followup=no_launch_followup,
    )
    meta = read_retention_meta(artifacts_dir)
    second = settle_claim_and_followup(
        artifacts_dir,
        meta,
        monitor_state="stopped",
        exit_code=None,
        elapsed_seconds=0.0,
        capture=OutputCapture(),
        timeout_kind=None,
        project_name="proj",
        launch_followup=no_launch_followup,
    )

    assert first.error is None
    assert second.error is None
    claims = get_claimed_workspaces(project_file)
    assert len(claims) == 1
    assert claims[0].pinned is True
    assert (repo / "tracked.txt").read_text() == "session owned\n"


def test_resume_success_label_without_proof_leaves_hold(tmp_path: Path) -> None:
    """A success label without live successor custody cannot clear unresolved."""
    from sase.monitor.resume import _settle_retention_after_resume
    from sase.workspace_provider.retention_record import (
        read_workspace_retention_record,
    )

    repo = init_retention_repo(tmp_path / "ws", dirty=True)
    artifacts_dir, _project_file = make_retention_monitor(repo)
    meta = read_retention_meta(artifacts_dir)
    assert (
        release_monitor_claim(meta, project_name="proj", artifacts_dir=artifacts_dir)
        is None
    )
    assert retention_record(artifacts_dir) is not None

    _settle_retention_after_resume(
        artifacts_dir,
        FollowupLaunchResult(launched=True, agent_name="acme--mon@1"),
        "acme--mon@1",
    )

    record = retention_record(artifacts_dir)
    assert record is not None
    assert record.get("settled") is not True
    typed = read_workspace_retention_record(artifacts_dir)
    assert typed is not None
    assert typed.unresolved is True


def test_resume_degraded_and_failed_leave_hold(tmp_path: Path) -> None:
    """Degraded or failed resumes must not clear the original hold."""
    from sase.monitor.resume import _settle_retention_after_resume

    cases = (
        FollowupLaunchResult(
            launched=True,
            degraded_reason="fell back to workspace #0",
            agent_name="acme--mon@1",
        ),
        FollowupLaunchResult(launched=False, error="boom"),
    )
    for index, launch in enumerate(cases):
        repo = init_retention_repo(tmp_path / f"ws-{index}", dirty=True)
        write_project_file(
            "proj",
            running_claims=[
                WorkspaceClaim(
                    10 + index,
                    RETENTION_CLAIM_WORKFLOW,
                    "acme",
                    pid=os.getpid(),
                    artifacts_timestamp=f"2026090612000{index}",
                )
            ],
        )
        artifacts_dir = make_starter_agent(
            "proj",
            f"2026090612000{index}",
            "acme--mon",
            agent_session="acme",
            agent_session_role="monitor",
            monitor_id="abc123def456",
            monitor_command="true",
            monitor_cwd=str(repo),
            monitor_reason="test",
            monitor_start_status="MONITORING",
            monitor_stop_status="MONITORED",
            monitor_timeout_seconds=30.0,
            monitor_state="failed",
            cl_name="acme",
            workspace_dir=str(repo),
            workspace_num=10 + index,
            pid=os.getpid(),
            monitor_continuation_protocol=MONITOR_CONTINUATION_PROTOCOL_RECORDS_V1,
            monitor_next_action="Report it.",
        )
        meta = read_retention_meta(artifacts_dir)
        assert (
            release_monitor_claim(
                meta, project_name="proj", artifacts_dir=artifacts_dir
            )
            is None
        )
        assert retention_record(artifacts_dir) is not None

        _settle_retention_after_resume(artifacts_dir, launch, "acme--mon@1")

        record = retention_record(artifacts_dir)
        assert record is not None
        assert record.get("settled") is not True
        assert record["disposition"] == "retain"


def test_stale_claim_is_noop(tmp_path: Path) -> None:
    """Settlement against a moved claim never pins or clears the occupant."""
    repo = init_retention_repo(tmp_path / "ws", dirty=True)
    artifacts_dir, project_file = make_retention_monitor(repo)
    meta = read_retention_meta(artifacts_dir)
    meta["pid"] = 999999999
    write_retention_meta(artifacts_dir, meta)

    error = release_monitor_claim(
        meta, project_name="proj", artifacts_dir=artifacts_dir
    )

    assert error is None
    claims = get_claimed_workspaces(project_file)
    assert len(claims) == 1
    assert claims[0].pid == os.getpid()
    assert claims[0].pinned is False


def test_proc_reconcile_path_retains_dirty(tmp_path: Path) -> None:
    """The proc settlement entry point converges on the same retention."""
    from sase.monitor.proc_adapter import settle_monitor_followup

    repo = init_retention_repo(tmp_path / "ws", dirty=True)
    artifacts_dir, project_file = make_retention_monitor(repo, next_action=None)
    meta = read_retention_meta(artifacts_dir)
    state: dict[str, object] = {
        "artifacts_dir": artifacts_dir,
        "proc_id": "abc123def456",
        "status": "success",
        "termination_reason": "success",
        "exit_code": 0,
        "monitor_state": "completed",
        "monitor_exit_code": 0,
        "monitor_elapsed_seconds": 0.0,
        "monitor_meta": dict(meta),
    }

    settle_monitor_followup(state)

    # Completed + clean would release; dirty retains through the same adapter.
    claims = get_claimed_workspaces(project_file)
    assert len(claims) == 1
    assert claims[0].pinned is True
    assert (repo / "tracked.txt").read_text() == "session owned\n"
    _ = SimpleNamespace  # keep import used across protocol variants


def test_dirty_linked_repo_beyond_eighth_still_retains(tmp_path: Path) -> None:
    """No eight-repository cutoff: the ninth dirty linked repo retains."""
    repos: list[tuple[str, Path]] = []
    primary = init_retention_repo(tmp_path / "ws-0", dirty=False)
    repos.append(("primary", primary))
    for index in range(1, 9):
        clean = init_retention_repo(tmp_path / f"ws-{index}", dirty=False)
        repos.append((f"linked-{index}", clean))
    ninth = init_retention_repo(tmp_path / "ws-9", dirty=True)
    repos.append(("linked-9", ninth))
    artifacts_dir, project_file = make_retention_monitor(primary)
    _write_monitor_baselines(artifacts_dir, repos)
    meta = read_retention_meta(artifacts_dir)

    error = release_monitor_claim(
        meta, project_name="proj", artifacts_dir=artifacts_dir
    )

    assert error is None
    claims = get_claimed_workspaces(project_file)
    assert len(claims) == 1
    assert claims[0].pinned is True
    assert (ninth / "tracked.txt").read_text() == "session owned\n"
    record = retention_record(artifacts_dir)
    assert record is not None
    assert record["disposition"] == "retain"


def test_unavailable_owned_checkout_retains_as_uncertainty(
    tmp_path: Path,
) -> None:
    """A deleted owned checkout is uncertainty, not a clean release."""
    import shutil

    repo = init_retention_repo(tmp_path / "ws", dirty=True)
    artifacts_dir, project_file = make_retention_monitor(repo)
    _write_monitor_baselines(artifacts_dir, [("primary", repo)])
    shutil.rmtree(repo)
    meta = read_retention_meta(artifacts_dir)

    error = release_monitor_claim(
        meta, project_name="proj", artifacts_dir=artifacts_dir
    )

    assert error is None
    claims = get_claimed_workspaces(project_file)
    assert len(claims) == 1
    assert claims[0].pinned is True
    record = retention_record(artifacts_dir)
    assert record is not None
    assert record["disposition"] == "retain"
    assert record.get("probe_errors")


def test_stale_binding_retries_in_fresh_interpreter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stale loaded binding retries the same Rust settlement fresh."""
    from sase.turns import workspace_retention as _adapter

    repo = init_retention_repo(tmp_path / "ws", dirty=True)
    artifacts_dir, project_file = make_retention_monitor(repo)
    meta = read_retention_meta(artifacts_dir)

    def _stale(*_args: object, **_kwargs: object) -> object:
        raise TypeError("old release_workspace signature")

    monkeypatch.setattr(_adapter, "settle_stranded_workspace", _stale)

    error = release_monitor_claim(
        meta, project_name="proj", artifacts_dir=artifacts_dir
    )

    assert error is None
    claims = get_claimed_workspaces(project_file)
    assert len(claims) == 1
    assert claims[0].pinned is True
    assert (repo / "tracked.txt").read_text() == "session owned\n"
    record = retention_record(artifacts_dir)
    assert record is not None
    assert record["disposition"] == "retain"


def test_failed_git_preflight_without_baseline_retains(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed git preflight keeps the known dirty workspace instead of dropping it."""
    repo = init_retention_repo(tmp_path / "ws", dirty=True)
    artifacts_dir, project_file = make_retention_monitor(repo)
    meta = read_retention_meta(artifacts_dir)
    monkeypatch.setattr(
        "sase.monitor.settlement_fresh_owner._classify_git_toplevel",
        lambda _path: ("failed", "git preflight failed"),
    )

    error = release_monitor_claim(
        meta, project_name="proj", artifacts_dir=artifacts_dir
    )

    assert error is None
    claims = get_claimed_workspaces(project_file)
    assert len(claims) == 1
    assert claims[0].pinned is True
    assert (repo / "tracked.txt").read_text() == "session owned\n"
    record = retention_record(artifacts_dir)
    assert record is not None
    assert record["disposition"] == "retain"


def test_discovery_failure_with_dirty_opened_linked_retains(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Failed linked discovery retains rather than classifying only a clean primary."""
    primary = init_retention_repo(tmp_path / "ws", dirty=False)
    linked = init_retention_repo(tmp_path / "linked", dirty=True)
    artifacts_dir, project_file = make_retention_monitor(primary)
    write_opened_linked(artifacts_dir, "linked-core", linked)
    monkeypatch.setattr(
        "sase.monitor.settlement_fresh_owner._shared_repos",
        lambda *_args, **_kwargs: ([], set(), "linked discovery failed"),
    )
    meta = read_retention_meta(artifacts_dir)

    error = release_monitor_claim(
        meta, project_name="proj", artifacts_dir=artifacts_dir
    )

    assert error is None
    claims = get_claimed_workspaces(project_file)
    assert len(claims) == 1
    assert claims[0].pinned is True
    assert (linked / "tracked.txt").read_text() == "session owned\n"
    record = retention_record(artifacts_dir)
    assert record is not None
    assert record["disposition"] == "retain"
    assert record.get("probe_errors")


def test_repo_less_command_releases(tmp_path: Path) -> None:
    """A positively known non-repository command still releases."""
    workspace = tmp_path / "plain"
    workspace.mkdir()
    (workspace / "notes.txt").write_text("not a repo\n", encoding="utf-8")
    artifacts_dir, project_file = make_retention_monitor(workspace)
    meta = read_retention_meta(artifacts_dir)

    error = release_monitor_claim(
        meta, project_name="proj", artifacts_dir=artifacts_dir
    )

    assert error is None
    assert get_claimed_workspaces(project_file) == []
    assert retention_record(artifacts_dir) is None
    assert (workspace / "notes.txt").read_text(encoding="utf-8") == "not a repo\n"


def test_unchanged_foreign_baseline_dirt_releases(tmp_path: Path) -> None:
    """Dirt already present in the starter baseline still releases."""
    repo = init_retention_repo(tmp_path / "ws", dirty=True)
    artifacts_dir, project_file = make_retention_monitor(repo)
    _write_monitor_baselines(
        artifacts_dir, [("primary", repo)], capture_fingerprints=True
    )
    meta = read_retention_meta(artifacts_dir)

    error = release_monitor_claim(
        meta, project_name="proj", artifacts_dir=artifacts_dir
    )

    assert error is None
    assert get_claimed_workspaces(project_file) == []
    assert retention_record(artifacts_dir) is None
    assert (repo / "tracked.txt").read_text() == "session owned\n"


def test_stale_owner_and_unavailable_fresh_interpreter_pins_monitor_timestamp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Failure pin uses the monitor artifact timestamp, never parent_timestamp."""
    import sase.monitor._settlement_retention as settlement_mod

    repo = init_retention_repo(tmp_path / "ws", dirty=True)
    artifacts_dir, project_file = make_retention_monitor(repo)
    meta = read_retention_meta(artifacts_dir)
    meta["parent_timestamp"] = "20260906115900"
    write_retention_meta(artifacts_dir, meta)

    def _stale_owner(*_args: object, **_kwargs: object) -> object:
        raise AttributeError("stale owner adapter")

    monkeypatch.setattr(settlement_mod, "_build_retention_owner", _stale_owner)
    monkeypatch.setattr(
        subprocess,
        "run",
        fail_fresh_python_c(OSError("fresh interpreter unavailable")),
    )

    error = release_monitor_claim(
        meta, project_name="proj", artifacts_dir=artifacts_dir
    )

    assert error is not None
    claims = get_claimed_workspaces(project_file)
    assert len(claims) == 1
    assert claims[0].pinned is True
    assert claims[0].artifacts_timestamp == "20260906120000"
    pending = pending_retention_record(artifacts_dir)
    assert pending is not None
    assert pending["artifacts_timestamp"] == "20260906120000"
    assert pending["pid"] == os.getpid()
    assert (repo / "tracked.txt").read_text() == "session owned\n"


def test_successor_collection_failure_pins_dirty_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Successor-proof collection failure pins the exact owner instead of releasing."""
    import sase.monitor._settlement_retention as settlement_mod

    repo = init_retention_repo(tmp_path / "ws", dirty=True)
    artifacts_dir, project_file = make_retention_monitor(repo)
    meta = read_retention_meta(artifacts_dir)

    def _boom(*_args: object, **_kwargs: object) -> object:
        raise OSError("successor collection failed")

    monkeypatch.setattr(settlement_mod, "_retention_successor_from_meta", _boom)

    error = release_monitor_claim(
        meta, project_name="proj", artifacts_dir=artifacts_dir
    )

    assert error is not None
    claims = get_claimed_workspaces(project_file)
    assert len(claims) == 1
    assert claims[0].pinned is True
    assert claims[0].artifacts_timestamp == "20260906120000"
    pending = pending_retention_record(artifacts_dir)
    assert pending is not None
    assert pending["artifacts_timestamp"] == "20260906120000"
    assert (repo / "tracked.txt").read_text() == "session owned\n"


def test_pending_write_failure_still_pins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed pending write still pins the exact matching claim."""
    repo = init_retention_repo(tmp_path / "ws", dirty=True)
    artifacts_dir, project_file = make_retention_monitor(repo)
    meta = read_retention_meta(artifacts_dir)
    monkeypatch.setattr(
        "sase.turns.workspace_retention_pending.write_pending_retention_identity",
        lambda *_args, **_kwargs: None,
    )

    error = release_monitor_claim(
        meta, project_name="proj", artifacts_dir=artifacts_dir
    )

    assert error is None
    claims = get_claimed_workspaces(project_file)
    assert len(claims) == 1
    assert claims[0].pinned is True
    assert claims[0].artifacts_timestamp == "20260906120000"
    assert (repo / "tracked.txt").read_text() == "session owned\n"
    assert pending_retention_record(artifacts_dir) is None


def test_fresh_interpreter_timeout_pins_dirty_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A timed-out fresh interpreter still pins the original dirty claim."""
    from sase.turns import workspace_retention as _adapter

    repo = init_retention_repo(tmp_path / "ws", dirty=True)
    artifacts_dir, project_file = make_retention_monitor(repo)
    meta = read_retention_meta(artifacts_dir)

    def _stale(*_args: object, **_kwargs: object) -> object:
        raise TypeError("old release_workspace signature")

    monkeypatch.setattr(_adapter, "settle_stranded_workspace", _stale)
    monkeypatch.setattr(
        subprocess,
        "run",
        fail_fresh_python_c(
            subprocess.TimeoutExpired(cmd=["python", "-c"], timeout=60)
        ),
    )

    error = release_monitor_claim(
        meta, project_name="proj", artifacts_dir=artifacts_dir
    )

    assert error is not None
    claims = get_claimed_workspaces(project_file)
    assert len(claims) == 1
    assert claims[0].pinned is True
    assert claims[0].artifacts_timestamp == "20260906120000"
    pending = pending_retention_record(artifacts_dir)
    assert pending is not None
    assert pending["artifacts_timestamp"] == "20260906120000"
    assert (repo / "tracked.txt").read_text() == "session owned\n"


def test_resume_transfer_with_live_successor_settles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Resume settles a hold only after live successor custody is proven."""
    from sase.monitor.resume import _settle_retention_after_resume
    from sase.workspace_provider.occupant import read_occupant_record
    from sase.workspace_provider.retention_record import read_workspace_retention_record

    repo = init_retention_repo(tmp_path / "ws", dirty=True)
    artifacts_dir, project_file = make_retention_monitor(repo)
    meta = read_retention_meta(artifacts_dir)
    assert (
        release_monitor_claim(meta, project_name="proj", artifacts_dir=artifacts_dir)
        is None
    )
    assert retention_record(artifacts_dir) is not None

    successor_pid = os.getpid() + 17
    meta = read_retention_meta(artifacts_dir)
    meta["monitor_followup_agent"] = "acme--mon@1"
    meta["monitor_followup_outcome"] = "launched"
    meta["project_file"] = project_file
    meta["project_name"] = "proj"
    write_retention_meta(artifacts_dir, meta)
    persist_retention_delivery(
        artifacts_dir, meta, agent="acme--mon@1", disposition="acknowledged"
    )
    transfer_retention_to_successor(
        project_file,
        repo,
        from_pid=os.getpid(),
        to_pid=successor_pid,
        timestamp="20260906120100",
    )
    monkeypatch.setattr(
        "sase.monitor.settlement_fresh_owner._receiver_is_live",
        lambda *_args, **_kwargs: True,
    )

    _settle_retention_after_resume(
        artifacts_dir,
        FollowupLaunchResult(launched=True, agent_name="acme--mon@1"),
        "acme--mon@1",
    )

    typed = read_workspace_retention_record(artifacts_dir)
    assert typed is not None
    assert typed.unresolved is False
    claims = get_claimed_workspaces(project_file)
    assert len(claims) == 1
    assert claims[0].pid == successor_pid
    occupant = read_occupant_record(str(repo))
    assert occupant is not None
    assert occupant.pid == successor_pid
    assert (repo / "tracked.txt").read_text() == "session owned\n"


def _write_starter_baseline(
    starter_dir: str, repos: list[tuple[str, str, str, Path]]
) -> None:
    """Write a run-start baseline with explicit kinds into a starter dir."""
    import json

    from sase.llm_provider.commit_finalizer_baseline import FINALIZER_BASELINE_FILENAME
    from sase.llm_provider.commit_finalizer_git import normalize_path

    payload = {
        "schema_version": 1,
        "repositories": [
            {
                "repo_id": repo_id,
                "path": normalize_path(str(path)),
                "kind": kind,
                "name": name,
                "scope": "run_start",
                "captured_at": "2026-09-06T11:59:00+00:00",
                "fingerprints": {},
            }
            for repo_id, kind, name, path in repos
        ],
    }
    (Path(starter_dir) / FINALIZER_BASELINE_FILENAME).write_text(
        json.dumps(payload), encoding="utf-8"
    )


def test_foreign_starter_evidence_releases_clean_workspace(
    tmp_path: Path,
) -> None:
    """A starter from a deleted foreign workspace must not pin this monitor."""
    import shutil

    foreign_ws = tmp_path / "foreign-ws"
    foreign_repo = init_retention_repo(foreign_ws, dirty=True)
    foreign_plans = init_retention_repo(tmp_path / "foreign-plans", dirty=True)
    starter_dir = make_starter_agent(
        "proj",
        "20260906115900",
        "acme",
        workspace_num=9,
        workspace_dir=str(foreign_ws),
        pid=999999999,
    )
    _write_starter_baseline(
        starter_dir,
        [
            ("main:main", "main", "main", foreign_repo),
            ("sibling:plans", "sibling", "plans", foreign_plans),
        ],
    )
    write_opened_linked(starter_dir, "foreign-linked", foreign_repo)
    shutil.rmtree(foreign_ws)
    shutil.rmtree(foreign_plans)

    repo = init_retention_repo(tmp_path / "ws", dirty=False)
    artifacts_dir, project_file = make_retention_monitor(repo)
    _write_monitor_baselines(artifacts_dir, [("primary", repo)])
    meta = read_retention_meta(artifacts_dir)
    meta["monitor_starter_artifacts_dir"] = starter_dir
    write_retention_meta(artifacts_dir, meta)

    error = release_monitor_claim(
        meta, project_name="proj", artifacts_dir=artifacts_dir
    )

    assert error is None
    assert get_claimed_workspaces(project_file) == []
    assert retention_record(artifacts_dir) is None


def test_same_workspace_starter_baseline_still_contributes(
    tmp_path: Path,
) -> None:
    """A starter from the same workspace still contributes baseline evidence."""
    repo = init_retention_repo(tmp_path / "ws", dirty=False)
    linked = init_retention_repo(tmp_path / "linked", dirty=False)
    starter_dir = make_starter_agent(
        "proj",
        "20260906115900",
        "acme",
        workspace_num=3,
        workspace_dir=str(repo),
        pid=os.getpid(),
    )
    _write_monitor_baselines(starter_dir, [("linked", linked)])
    write_opened_linked(starter_dir, "linked", linked)
    (linked / "tracked.txt").write_text("session owned\n", encoding="utf-8")

    artifacts_dir, project_file = make_retention_monitor(repo)
    _write_monitor_baselines(artifacts_dir, [("primary", repo)])
    meta = read_retention_meta(artifacts_dir)
    meta["monitor_starter_artifacts_dir"] = starter_dir
    write_retention_meta(artifacts_dir, meta)

    error = release_monitor_claim(
        meta, project_name="proj", artifacts_dir=artifacts_dir
    )

    assert error is None
    claims = get_claimed_workspaces(project_file)
    assert len(claims) == 1
    assert claims[0].pinned is True
    record = retention_record(artifacts_dir)
    assert record is not None
    assert record["disposition"] == "retain"
    assert record["policy_reason"] == "session_owned_dirt"
    assert "linked" in record["affected_repo_ids"]


def test_retained_monitor_stores_exactly_one_notification(
    tmp_path: Path,
) -> None:
    """A retained monitor stores one recovery notification, plus-oned on retry."""
    from sase.notifications.store import load_notifications

    repo = init_retention_repo(tmp_path / "ws", dirty=True)
    artifacts_dir, project_file = make_retention_monitor(repo)
    _write_monitor_baselines(artifacts_dir, [("primary", repo)])
    meta = read_retention_meta(artifacts_dir)

    assert (
        release_monitor_claim(meta, project_name="proj", artifacts_dir=artifacts_dir)
        is None
    )
    rows = load_notifications()
    assert len(rows) == 1
    assert "Workspace held: stranded work" in rows[0].notes
    assert rows[0].action == "JumpToAgent"
    assert rows[0].action_data["raw_suffix"] == "20260906120000"

    meta = read_retention_meta(artifacts_dir)
    assert (
        release_monitor_claim(meta, project_name="proj", artifacts_dir=artifacts_dir)
        is None
    )
    rows = load_notifications()
    assert len(rows) == 1
    assert rows[0].plus_one_count >= 1
