"""Monitor retention: stranded monitor workspaces are held, clean ones released.

Exercises the monitor-retention phase through the real settlement entry
point (:func:`sase.monitor.settlement.settle_claim_and_followup`) and the
retention-aware claim releaser, asserting on the RUNNING claim row and the
checkout files — not merely that a helper was called. Covers stopped and
reboot-lost monitors, failed and absent follow-ups, capture blockage,
degraded successors, prepared host completion, repeated settlement, resume
transfer, and both handoff protocols (legacy and records_v1).
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.continuation_capture.rollout import (
    MONITOR_CONTINUATION_PROTOCOL_LEGACY,
    MONITOR_CONTINUATION_PROTOCOL_RECORDS_V1,
)
from sase.monitor.followup import FollowupLaunchResult
from sase.monitor.models import MONITOR_FOLLOWUP_DEGRADED_OUTCOME
from sase.monitor.output import OutputCapture
from sase.monitor.settlement import (
    _release_monitor_claim,
    settle_claim_and_followup,
)
from sase.running_field import WorkspaceClaim, get_claimed_workspaces

from ._fixtures import make_starter_agent, write_project_file

_CLAIM_WORKFLOW = "ace-monitor"


@pytest.fixture(autouse=True)
def _sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(path: Path, *, dirty: bool = False) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init")
    _git(path, "config", "user.email", "sase-test@example.invalid")
    _git(path, "config", "user.name", "SASE Test")
    (path / "tracked.txt").write_text("base\n", encoding="utf-8")
    _git(path, "add", "tracked.txt")
    _git(path, "commit", "-m", "init")
    if dirty:
        (path / "tracked.txt").write_text("session owned\n", encoding="utf-8")
    return path


def _make_monitor(
    repo: Path,
    *,
    monitor_state: str = "stopped",
    next_action: str | None = None,
    protocol: str = MONITOR_CONTINUATION_PROTOCOL_RECORDS_V1,
    outcome: str | None = None,
    degraded_reason: str | None = None,
    workspace_num: int = 3,
) -> tuple[str, str]:
    project_file = write_project_file(
        "proj",
        running_claims=[
            WorkspaceClaim(
                workspace_num,
                _CLAIM_WORKFLOW,
                "acme",
                pid=os.getpid(),
                artifacts_timestamp="20260906120000",
            )
        ],
    )
    artifacts_dir = make_starter_agent(
        "proj",
        "20260906120000",
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
        monitor_state="running",
        cl_name="acme",
        workspace_dir=str(repo),
        workspace_num=workspace_num,
        pid=os.getpid(),
        monitor_continuation_protocol=protocol,
        **({"monitor_next_action": next_action} if next_action else {}),
        **({"monitor_followup_outcome": outcome} if outcome else {}),
        **(
            {"monitor_followup_degraded_reason": degraded_reason}
            if degraded_reason
            else {}
        ),
    )
    meta_path = Path(artifacts_dir) / "agent_meta.json"
    meta = json.loads(meta_path.read_text())
    meta["monitor_state"] = monitor_state
    meta_path.write_text(json.dumps(meta))
    return artifacts_dir, project_file


def _read_meta(artifacts_dir: str) -> dict:
    return json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())


def _write_meta(artifacts_dir: str, meta: dict) -> None:
    (Path(artifacts_dir) / "agent_meta.json").write_text(json.dumps(meta))


def _retention_record(artifacts_dir: str) -> dict | None:
    path = Path(artifacts_dir) / "diagnostics" / "workspace_retention.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text())


def _no_launch(*_args: object, **_kwargs: object) -> FollowupLaunchResult:
    raise AssertionError("no follow-up launch expected")


def _failed_launch(*_args: object, **_kwargs: object) -> FollowupLaunchResult:
    return FollowupLaunchResult(launched=False, error="follow-up launch failed")


def _degraded_launch(*_args: object, **_kwargs: object) -> FollowupLaunchResult:
    return FollowupLaunchResult(
        launched=True,
        degraded_reason="claim transfer failed; fell back to workspace #0",
        agent_name="acme--mon@1",
        artifacts_dir="/tmp/other",
        pid=999999,
    )


@pytest.mark.parametrize(
    "protocol",
    [MONITOR_CONTINUATION_PROTOCOL_LEGACY, MONITOR_CONTINUATION_PROTOCOL_RECORDS_V1],
)
def test_stopped_dirty_monitor_pins_claim_and_keeps_files(
    tmp_path: Path, protocol: str
) -> None:
    """Stopped monitors with uncommitted work retain the workspace on both protocols."""
    repo = _init_repo(tmp_path / "ws", dirty=True)
    artifacts_dir, project_file = _make_monitor(repo, protocol=protocol)
    meta = _read_meta(artifacts_dir)

    result = settle_claim_and_followup(
        artifacts_dir,
        meta,
        monitor_state="stopped",
        exit_code=None,
        elapsed_seconds=0.0,
        capture=OutputCapture(),
        timeout_kind=None,
        project_name="proj",
        launch_followup=_no_launch,
    )

    assert result.error is None
    claims = get_claimed_workspaces(project_file)
    assert len(claims) == 1
    assert claims[0].pinned is True
    assert (repo / "tracked.txt").read_text() == "session owned\n"
    record = _retention_record(artifacts_dir)
    assert record is not None
    assert record["disposition"] == "retain"
    assert record["terminal_reason"] == "stopped"
    assert record["monitor_state"] == "stopped"
    from sase.workspace_provider.retention_record import (
        read_workspace_retention_record,
        workspace_retention_lines,
    )

    typed = read_workspace_retention_record(artifacts_dir)
    assert typed is not None and typed.unresolved is True
    assert typed.monitor_resume_eligible is False
    joined = "\n".join(workspace_retention_lines(typed))
    assert "sase monitor resume" not in joined
    assert "Dismiss this agent to release the workspace." in joined


@pytest.mark.parametrize(
    "protocol",
    [MONITOR_CONTINUATION_PROTOCOL_LEGACY, MONITOR_CONTINUATION_PROTOCOL_RECORDS_V1],
)
def test_stopped_clean_monitor_releases_claim(tmp_path: Path, protocol: str) -> None:
    """Stopped monitors with no dirty work keep the normal release path."""
    repo = _init_repo(tmp_path / "ws", dirty=False)
    artifacts_dir, project_file = _make_monitor(repo, protocol=protocol)
    meta = _read_meta(artifacts_dir)

    result = settle_claim_and_followup(
        artifacts_dir,
        meta,
        monitor_state="stopped",
        exit_code=0,
        elapsed_seconds=0.0,
        capture=OutputCapture(),
        timeout_kind=None,
        project_name="proj",
        launch_followup=_no_launch,
    )

    assert result.error is None
    assert get_claimed_workspaces(project_file) == []
    assert _retention_record(artifacts_dir) is None


def test_reboot_lost_dirty_monitor_retains(tmp_path: Path) -> None:
    """A reboot-lost monitor (unknown outcome) retains dirty work."""
    repo = _init_repo(tmp_path / "ws", dirty=True)
    artifacts_dir, project_file = _make_monitor(repo, next_action="Report it.")
    meta = _read_meta(artifacts_dir)

    result = settle_claim_and_followup(
        artifacts_dir,
        meta,
        monitor_state="lost",
        exit_code=None,
        elapsed_seconds=0.0,
        capture=OutputCapture(),
        timeout_kind=None,
        project_name="proj",
        launch_followup=_no_launch,
    )

    assert result.error is not None  # lost follow-up cannot launch
    claims = get_claimed_workspaces(project_file)
    assert len(claims) == 1
    assert claims[0].pinned is True
    assert (repo / "tracked.txt").read_text() == "session owned\n"


def test_failed_monitor_with_failed_followup_retains_dirty(tmp_path: Path) -> None:
    """Launch failure with unresolved dirt retains the original workspace."""
    repo = _init_repo(tmp_path / "ws", dirty=True)
    artifacts_dir, project_file = _make_monitor(
        repo, monitor_state="failed", next_action="Report it."
    )
    meta = _read_meta(artifacts_dir)

    result = settle_claim_and_followup(
        artifacts_dir,
        meta,
        monitor_state="failed",
        exit_code=1,
        elapsed_seconds=0.0,
        capture=OutputCapture(),
        timeout_kind=None,
        project_name="proj",
        launch_followup=_failed_launch,
    )

    assert result.error is not None
    assert result.launch_result is not None
    assert result.launch_result.launched is False
    claims = get_claimed_workspaces(project_file)
    assert len(claims) == 1
    assert claims[0].pinned is True
    assert (repo / "tracked.txt").read_text() == "session owned\n"
    record = _retention_record(artifacts_dir)
    assert record is not None
    assert record["disposition"] == "retain"
    assert record.get("monitor_state") == "failed"
    assert record.get("monitor_next_action") == "Report it."
    from sase.workspace_provider.retention_record import (
        read_workspace_retention_record,
        workspace_retention_lines,
    )

    typed = read_workspace_retention_record(artifacts_dir)
    assert typed is not None and typed.monitor_resume_eligible is True
    assert any(
        "sase monitor resume abc123def456" in line
        for line in workspace_retention_lines(typed)
    )


def test_failed_monitor_with_failed_followup_releases_when_clean(
    tmp_path: Path,
) -> None:
    """Launch failure with a proven-clean tree keeps the release path."""
    repo = _init_repo(tmp_path / "ws", dirty=False)
    artifacts_dir, project_file = _make_monitor(repo, next_action="Report it.")
    meta = _read_meta(artifacts_dir)

    result = settle_claim_and_followup(
        artifacts_dir,
        meta,
        monitor_state="failed",
        exit_code=1,
        elapsed_seconds=0.0,
        capture=OutputCapture(),
        timeout_kind=None,
        project_name="proj",
        launch_followup=_failed_launch,
    )

    assert result.error is not None  # the launch failure is still reported
    assert get_claimed_workspaces(project_file) == []


def test_degraded_followup_retains_original_dirty_workspace(
    tmp_path: Path,
) -> None:
    """A follow-up in another checkout does not discharge the dirty original."""
    repo = _init_repo(tmp_path / "ws", dirty=True)
    artifacts_dir, project_file = _make_monitor(repo, next_action="Report it.")
    meta = _read_meta(artifacts_dir)

    result = settle_claim_and_followup(
        artifacts_dir,
        meta,
        monitor_state="failed",
        exit_code=1,
        elapsed_seconds=0.0,
        capture=OutputCapture(),
        timeout_kind=None,
        project_name="proj",
        launch_followup=_degraded_launch,
    )

    assert result.error is None
    assert result.launch_result is not None
    assert result.launch_result.launched is True
    assert result.launch_result.degraded_reason
    claims = get_claimed_workspaces(project_file)
    assert len(claims) == 1
    assert claims[0].pinned is True
    assert (repo / "tracked.txt").read_text() == "session owned\n"
    record = _retention_record(artifacts_dir)
    assert record is not None
    assert record["disposition"] == "retain"
    assert record["policy_reason"] in {
        "session_owned_dirt",
        "missing_baseline_with_custody",
        "evidence_unavailable",
    }


def test_blocked_continuation_capture_retains_dirty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Blocked dispatch (records protocol) retains instead of direct release."""
    import sase.monitor.settlement as settlement

    repo = _init_repo(tmp_path / "ws", dirty=True)
    artifacts_dir, project_file = _make_monitor(
        repo,
        monitor_state="failed",
        next_action="Report it.",
        protocol=MONITOR_CONTINUATION_PROTOCOL_RECORDS_V1,
    )
    meta = _read_meta(artifacts_dir)
    monkeypatch.setattr(
        settlement, "_continuation_dispatch_blocked_reason", lambda _m: "blocked"
    )
    monkeypatch.setattr(
        settlement, "_repair_missing_starter_parent", lambda _a, _m: False
    )

    result = settle_claim_and_followup(
        artifacts_dir,
        meta,
        monitor_state="failed",
        exit_code=1,
        elapsed_seconds=0.0,
        capture=OutputCapture(),
        timeout_kind=None,
        project_name="proj",
        launch_followup=_no_launch,
    )

    assert result.error is not None
    assert result.launch_result is not None
    assert result.launch_result.launched is False
    claims = get_claimed_workspaces(project_file)
    assert len(claims) == 1
    assert claims[0].pinned is True
    assert (repo / "tracked.txt").read_text() == "session owned\n"


def test_same_workspace_successor_does_not_hold(tmp_path: Path) -> None:
    """A confirmed same-workspace successor keeps custody without a hold."""
    from sase.monitor.delivery import (
        new_delivery_record,
        persist_delivery_record,
        transition_delivery,
    )

    repo = _init_repo(tmp_path / "ws", dirty=True)
    artifacts_dir, project_file = _make_monitor(
        repo, outcome="launched", protocol=MONITOR_CONTINUATION_PROTOCOL_LEGACY
    )
    meta = _read_meta(artifacts_dir)
    meta["monitor_followup_agent"] = "acme--mon@1"
    _write_meta(artifacts_dir, meta)
    key = {
        "monitor_id": "abc123def456",
        "result_id": meta.get("monitor_result_id") or "result",
        "branch": "failed",
    }
    record = new_delivery_record(key, selected_action="continue")
    reserved = transition_delivery(record, "reserved", reserved_identity="acme--mon@1")
    dispatching = transition_delivery(reserved, "dispatching")
    acknowledged = transition_delivery(
        dispatching, "acknowledged", acknowledged_by="acme--mon@1"
    )
    persist_delivery_record(artifacts_dir, acknowledged)

    error = _release_monitor_claim(
        meta, project_name="proj", artifacts_dir=artifacts_dir
    )

    assert error is None
    assert get_claimed_workspaces(project_file) == []


def test_stale_launch_label_without_proof_retains_dirty(tmp_path: Path) -> None:
    """A bare launched label with a still-owned dirty claim must retain."""
    repo = _init_repo(tmp_path / "ws", dirty=True)
    artifacts_dir, project_file = _make_monitor(
        repo, outcome="launched", protocol=MONITOR_CONTINUATION_PROTOCOL_LEGACY
    )
    meta = _read_meta(artifacts_dir)

    error = _release_monitor_claim(
        meta, project_name="proj", artifacts_dir=artifacts_dir
    )

    assert error is None
    claims = get_claimed_workspaces(project_file)
    assert len(claims) == 1
    assert claims[0].pinned is True
    assert (repo / "tracked.txt").read_text() == "session owned\n"
    record = _retention_record(artifacts_dir)
    assert record is not None
    assert record["disposition"] == "retain"


def test_prepared_completion_success_releases_clean(tmp_path: Path) -> None:
    """A committed host completion releases a clean workspace normally."""
    from sase.monitor._host_completion_shared import HOST_COMPLETED_OUTCOME

    repo = _init_repo(tmp_path / "ws", dirty=False)
    artifacts_dir, project_file = _make_monitor(repo, outcome=HOST_COMPLETED_OUTCOME)
    meta = _read_meta(artifacts_dir)

    error = _release_monitor_claim(
        meta, project_name="proj", artifacts_dir=artifacts_dir
    )

    assert error is None
    assert get_claimed_workspaces(project_file) == []


def test_prepared_completion_failure_retains_dirty(tmp_path: Path) -> None:
    """A failed completion with unresolved dirt retains the workspace."""
    repo = _init_repo(tmp_path / "ws", dirty=True)
    artifacts_dir, project_file = _make_monitor(repo, outcome="not-launchable")
    meta = _read_meta(artifacts_dir)

    error = _release_monitor_claim(
        meta, project_name="proj", artifacts_dir=artifacts_dir
    )

    assert error is None
    claims = get_claimed_workspaces(project_file)
    assert len(claims) == 1
    assert claims[0].pinned is True
    assert (repo / "tracked.txt").read_text() == "session owned\n"


def test_repeated_settlement_is_idempotent(tmp_path: Path) -> None:
    """Settling twice pins once and keeps the checkout intact."""
    repo = _init_repo(tmp_path / "ws", dirty=True)
    artifacts_dir, project_file = _make_monitor(repo)
    meta = _read_meta(artifacts_dir)

    first = settle_claim_and_followup(
        artifacts_dir,
        meta,
        monitor_state="stopped",
        exit_code=None,
        elapsed_seconds=0.0,
        capture=OutputCapture(),
        timeout_kind=None,
        project_name="proj",
        launch_followup=_no_launch,
    )
    meta = _read_meta(artifacts_dir)
    second = settle_claim_and_followup(
        artifacts_dir,
        meta,
        monitor_state="stopped",
        exit_code=None,
        elapsed_seconds=0.0,
        capture=OutputCapture(),
        timeout_kind=None,
        project_name="proj",
        launch_followup=_no_launch,
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

    repo = _init_repo(tmp_path / "ws", dirty=True)
    artifacts_dir, _project_file = _make_monitor(repo)
    meta = _read_meta(artifacts_dir)
    assert (
        _release_monitor_claim(meta, project_name="proj", artifacts_dir=artifacts_dir)
        is None
    )
    assert _retention_record(artifacts_dir) is not None

    _settle_retention_after_resume(
        artifacts_dir,
        FollowupLaunchResult(launched=True, agent_name="acme--mon@1"),
        "acme--mon@1",
    )

    record = _retention_record(artifacts_dir)
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
        repo = _init_repo(tmp_path / f"ws-{index}", dirty=True)
        write_project_file(
            "proj",
            running_claims=[
                WorkspaceClaim(
                    10 + index,
                    _CLAIM_WORKFLOW,
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
        meta = _read_meta(artifacts_dir)
        assert (
            _release_monitor_claim(
                meta, project_name="proj", artifacts_dir=artifacts_dir
            )
            is None
        )
        assert _retention_record(artifacts_dir) is not None

        _settle_retention_after_resume(artifacts_dir, launch, "acme--mon@1")

        record = _retention_record(artifacts_dir)
        assert record is not None
        assert record.get("settled") is not True
        assert record["disposition"] == "retain"


def test_stale_claim_is_noop(tmp_path: Path) -> None:
    """Settlement against a moved claim never pins or clears the occupant."""
    repo = _init_repo(tmp_path / "ws", dirty=True)
    artifacts_dir, project_file = _make_monitor(repo)
    meta = _read_meta(artifacts_dir)
    meta["pid"] = 999999999
    _write_meta(artifacts_dir, meta)

    error = _release_monitor_claim(
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

    repo = _init_repo(tmp_path / "ws", dirty=True)
    artifacts_dir, project_file = _make_monitor(repo, next_action=None)
    meta = _read_meta(artifacts_dir)
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


def test_dirty_linked_repo_beyond_eighth_still_retains(tmp_path: Path) -> None:
    """No eight-repository cutoff: the ninth dirty linked repo retains."""
    repos: list[tuple[str, Path]] = []
    primary = _init_repo(tmp_path / "ws-0", dirty=False)
    repos.append(("primary", primary))
    for index in range(1, 9):
        clean = _init_repo(tmp_path / f"ws-{index}", dirty=False)
        repos.append((f"linked-{index}", clean))
    ninth = _init_repo(tmp_path / "ws-9", dirty=True)
    repos.append(("linked-9", ninth))
    artifacts_dir, project_file = _make_monitor(primary)
    _write_monitor_baselines(artifacts_dir, repos)
    meta = _read_meta(artifacts_dir)

    error = _release_monitor_claim(
        meta, project_name="proj", artifacts_dir=artifacts_dir
    )

    assert error is None
    claims = get_claimed_workspaces(project_file)
    assert len(claims) == 1
    assert claims[0].pinned is True
    assert (ninth / "tracked.txt").read_text() == "session owned\n"
    record = _retention_record(artifacts_dir)
    assert record is not None
    assert record["disposition"] == "retain"


def test_unavailable_owned_checkout_retains_as_uncertainty(
    tmp_path: Path,
) -> None:
    """A deleted owned checkout is uncertainty, not a clean release."""
    import shutil

    repo = _init_repo(tmp_path / "ws", dirty=True)
    artifacts_dir, project_file = _make_monitor(repo)
    _write_monitor_baselines(artifacts_dir, [("primary", repo)])
    shutil.rmtree(repo)
    meta = _read_meta(artifacts_dir)

    error = _release_monitor_claim(
        meta, project_name="proj", artifacts_dir=artifacts_dir
    )

    assert error is None
    claims = get_claimed_workspaces(project_file)
    assert len(claims) == 1
    assert claims[0].pinned is True
    record = _retention_record(artifacts_dir)
    assert record is not None
    assert record["disposition"] == "retain"
    assert record.get("probe_errors")


def test_stale_binding_retries_in_fresh_interpreter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stale loaded binding retries the same Rust settlement fresh."""
    from sase.turns import workspace_retention as _adapter

    repo = _init_repo(tmp_path / "ws", dirty=True)
    artifacts_dir, project_file = _make_monitor(repo)
    meta = _read_meta(artifacts_dir)

    def _stale(*_args: object, **_kwargs: object) -> object:
        raise TypeError("old release_workspace signature")

    monkeypatch.setattr(_adapter, "settle_stranded_workspace", _stale)

    error = _release_monitor_claim(
        meta, project_name="proj", artifacts_dir=artifacts_dir
    )

    assert error is None
    claims = get_claimed_workspaces(project_file)
    assert len(claims) == 1
    assert claims[0].pinned is True
    assert (repo / "tracked.txt").read_text() == "session owned\n"
    record = _retention_record(artifacts_dir)
    assert record is not None
    assert record["disposition"] == "retain"
