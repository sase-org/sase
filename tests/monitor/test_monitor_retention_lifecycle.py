"""Monitor retention: completion, resume, and edge-case paths.

Covers prepared host completion, repeated settlement, resume transfer and
degraded resume, stale claims, the proc settlement entry point, linked-repo
baselines, unavailable checkouts, and stale-binding retry.
"""

from __future__ import annotations

import os
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
    init_retention_repo,
    make_retention_monitor,
    no_launch_followup,
    read_retention_meta,
    retention_record,
    write_retention_meta,
)


@pytest.fixture(autouse=True)
def _sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)


def _write_monitor_baselines(artifacts_dir: str, repos: list[tuple[str, Path]]) -> None:
    """Write a finalizer baseline covering *repos* with empty fingerprints."""
    import json

    from sase.llm_provider.commit_finalizer_baseline import FINALIZER_BASELINE_FILENAME
    from sase.llm_provider.commit_finalizer_git import normalize_path

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
                "fingerprints": {},
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


def test_resume_transfer_settles_retention_record(tmp_path: Path) -> None:
    """A same-workspace resume discharges the stranded hold."""
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
    assert record["settled"] is True
    assert record["settled_via"] == "resume_transfer"
    assert record.get("settled_at")
    assert record.get("settled_reason") == "resume_transfer"
    typed = read_workspace_retention_record(artifacts_dir)
    assert typed is not None
    assert typed.unresolved is False


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
