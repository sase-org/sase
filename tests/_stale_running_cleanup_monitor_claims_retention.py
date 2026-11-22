"""Held-claim TTL and leaked monitor retention cases."""

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.ace.scheduler import stale_running_sweep as cleanup_module
from sase.ace.scheduler.stale_running_cleanup import cleanup_stale_running_entries
from sase.running_field import WorkspaceClaim


def _old_stamp(*, days_ago: int = 30) -> str:
    """Return a claim timestamp safely beyond the default held-claim TTL."""
    return (datetime.now() - timedelta(days=days_ago)).strftime("%Y%m%d%H%M%S")


def test_cleanup_releases_dead_gate_claim_after_held_ttl() -> None:
    """A dead-pid ace-gate claim stuck non-terminal releases past the TTL.

    Mirrors the 2026-09-19 shape: ``gate_state=settling`` with no
    ``done.json`` and no decision record. The workspace releases while the
    gate record itself is left untouched.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        artifacts = Path(tmpdir) / "gate-artifacts"
        artifacts.mkdir()
        (artifacts / "agent_meta.json").write_text("{}")
        claim = WorkspaceClaim(
            workspace_num=10,
            workflow="ace-gate",
            cl_name="feature",
            pid=33333,
            artifacts_timestamp=_old_stamp(),
        )
        project_file = "/tmp/projects/proj/proj.sase"
        with (
            patch(
                "sase.ace.scheduler.stale_running_sweep._get_all_project_files",
                return_value=[project_file],
            ),
            patch(
                "sase.ace.scheduler.stale_running_sweep.get_claimed_workspaces",
                return_value=[claim],
            ),
            patch(
                "sase.ace.scheduler.stale_running_sweep.is_process_running",
                return_value=False,
            ),
            patch(
                "sase.core.agent_artifact_paths.resolve_agent_artifact_timestamp_path",
                return_value=artifacts,
            ),
            patch(
                "sase.gate_turn.store.read_gate_turn_marker",
                return_value=MagicMock(is_terminal=False),
            ),
            patch(
                "sase.ace.scheduler.stale_running_sweep.release_workspace"
            ) as release,
        ):
            assert cleanup_stale_running_entries() == 1
        release.assert_called_once_with(
            project_file,
            10,
            "ace-gate",
            "feature",
            caller_tag="stale-cleanup",
            expected_pid=claim.pid,
            artifacts_timestamp=claim.artifacts_timestamp,
        )
        assert (artifacts / "done.json").is_file() is False
        assert sorted(path.name for path in artifacts.iterdir()) == ["agent_meta.json"]


def test_cleanup_keeps_dead_gate_claim_when_held_ttl_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A zero held-claim TTL never releases a non-terminal gate claim."""
    monkeypatch.setattr(cleanup_module, "_held_claim_ttl_days", lambda: 0)
    claim = WorkspaceClaim(
        workspace_num=10,
        workflow="ace-gate",
        cl_name="feature",
        pid=33333,
        artifacts_timestamp=_old_stamp(),
    )
    project_file = "/tmp/projects/proj/proj.sase"
    with (
        patch(
            "sase.ace.scheduler.stale_running_sweep._get_all_project_files",
            return_value=[project_file],
        ),
        patch(
            "sase.ace.scheduler.stale_running_sweep.get_claimed_workspaces",
            return_value=[claim],
        ),
        patch(
            "sase.ace.scheduler.stale_running_sweep.is_process_running",
            return_value=False,
        ),
        patch(
            "sase.core.agent_artifact_paths.resolve_agent_artifact_timestamp_path",
            return_value=Path("/tmp/artifacts/20200101120000"),
        ),
        patch(
            "sase.gate_turn.store.read_gate_turn_marker",
            return_value=MagicMock(is_terminal=False),
        ),
        patch("sase.ace.scheduler.stale_running_sweep.release_workspace") as release,
    ):
        assert cleanup_stale_running_entries() == 0
    release.assert_not_called()


def _write_repo_baselines(target_dir: str, repos: list) -> None:
    """Write run-start finalizer baselines with empty fingerprints."""
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
                "captured_at": "2026-11-04T00:00:00+00:00",
                "fingerprints": {},
            }
            for repo_id, kind, name, path in repos
        ],
    }
    (Path(target_dir) / FINALIZER_BASELINE_FILENAME).write_text(json.dumps(payload))


def _git(cwd: Path, *args: str) -> None:
    import subprocess

    subprocess.run(
        ["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True
    )


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init")
    _git(path, "config", "user.email", "sase-test@example.invalid")
    _git(path, "config", "user.name", "SASE Test")


def _make_leaked_monitor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    dirty_primary: bool,
) -> dict:
    """Build a faithful already-leaked epic-launch monitor claim.

    A pinned dead-pid ``ace-monitor`` claim whose first settlement retained
    on session-owned dirt (an untracked decisions sheet), with a foreign
    starter workspace. Returns the paths and store the repair needs.
    """
    import json

    from tests.monitor._fixtures import make_starter_agent, write_project_file

    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)

    now = datetime.now()
    monitor_ts = (now - timedelta(days=2)).strftime("%Y%m%d%H%M%S")
    starter_ts = (now - timedelta(days=2, hours=1)).strftime("%Y%m%d%H%M%S")
    dead_pid = 987654321

    checkout = tmp_path / "ws"
    _init_repo(checkout)
    (checkout / "tracked.txt").write_text("base\n", encoding="utf-8")
    (checkout / ".gitignore").write_text("/sase/repos/\n", encoding="utf-8")
    _git(checkout, "add", "-A")
    _git(checkout, "commit", "-m", "init")
    if dirty_primary:
        (checkout / "tracked.txt").write_text("session owned\n", encoding="utf-8")

    plans = checkout / "sase" / "repos" / "plans"
    _init_repo(plans)
    (plans / "202611").mkdir(parents=True)
    (plans / "202611" / "next_plan.md").write_text("# plan\n", encoding="utf-8")
    _git(plans, "add", "-A")
    _git(plans, "commit", "-m", "archive plan")
    stray = plans / "202611" / "next_plan.plan-decisions.json"
    stray.write_text(
        json.dumps({"schema": 1, "definitions": [{"id": "d1"}]}, indent=2) + "\n",
        encoding="utf-8",
    )

    starter_dir = make_starter_agent(
        "proj",
        starter_ts,
        "acme--starter",
        agent_session="acme",
        workspace_num=9,
        workspace_dir=str(tmp_path / "foreign-ws"),
        pid=dead_pid,
    )
    _write_repo_baselines(
        starter_dir,
        [
            ("main:main", "main", "main", tmp_path / "foreign-ws" / "repo"),
            ("sibling:plans", "sibling", "plans", tmp_path / "foreign-plans"),
        ],
    )

    artifacts_dir = make_starter_agent(
        "proj",
        monitor_ts,
        "acme--mon",
        agent_session="acme",
        agent_session_role="monitor",
        monitor_id="abc123def456",
        monitor_command="true",
        monitor_cwd=str(checkout),
        monitor_reason="test",
        monitor_start_status="MONITORING",
        monitor_stop_status="MONITORED",
        monitor_timeout_seconds=30.0,
        monitor_state="running",
        cl_name="acme",
        workspace_dir=str(checkout),
        workspace_num=3,
        pid=dead_pid,
    )
    meta_path = Path(artifacts_dir) / "agent_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["monitor_state"] = "completed"
    meta["monitor_starter_artifacts_dir"] = starter_dir
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    (Path(artifacts_dir) / "done.json").write_text("{}", encoding="utf-8")
    _write_repo_baselines(
        artifacts_dir,
        [
            ("primary", "primary", "primary", checkout),
            ("sibling:plans", "sibling", "plans", plans),
        ],
    )

    from sase.monitor._settlement_retention import release_monitor_claim

    project_file = write_project_file(
        "proj",
        running_claims=[
            WorkspaceClaim(
                3,
                "ace-monitor",
                "acme",
                pid=dead_pid,
                artifacts_timestamp=monitor_ts,
                pinned=True,
            )
        ],
    )
    assert (
        release_monitor_claim(meta, project_name="proj", artifacts_dir=artifacts_dir)
        is None
    )

    from sase.sdd.store import SddStore

    return {
        "checkout": checkout,
        "plans": plans,
        "stray": stray,
        "artifacts_dir": artifacts_dir,
        "project_file": project_file,
        "store": SddStore(storage="sidecar_repos", sdd_dir=plans, repo_root=plans),
    }


def _run_cleanup_sweep(fixture: dict) -> int:
    """Run one stale-running sweep over the leaked claim's project file."""
    with (
        patch(
            "sase.ace.scheduler.stale_running_sweep._get_all_project_files",
            return_value=[fixture["project_file"]],
        ),
        patch(
            "sase.ace.scheduler.stale_running_sweep.is_process_running",
            return_value=False,
        ),
        patch(
            "sase.ace.scheduler.stale_running_leak.peek_workspace_checkout_dir",
            return_value=str(fixture["checkout"]),
        ),
        patch(
            "sase.ace.scheduler._stale_running_shared.peek_workspace_checkout_dir",
            return_value=str(fixture["checkout"]),
        ),
        patch("sase.sdd.store.resolve_sdd_store", return_value=fixture["store"]),
    ):
        return cleanup_stale_running_entries()


def test_cleanup_repairs_leaked_monitor_claim_with_stray_sheet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A leaked monitor claim releases after its stray sheet is published.

    held_settle: the first sweep after the initial settle skips (evidence
    unchanged), so the interval is expired first to reach the re-probe that
    publishes the stray sheet and releases the clean workspace.
    """
    import json
    import subprocess
    import time

    from sase.running_field import get_claimed_workspaces
    from sase.workspace_provider.retention_record import (
        read_workspace_retention_record,
    )

    fixture = _make_leaked_monitor(tmp_path, monkeypatch, dirty_primary=False)

    assert _run_cleanup_sweep(fixture) == 0

    record_path = (
        Path(fixture["artifacts_dir"]) / "diagnostics" / "workspace_retention.json"
    )
    payload = json.loads(record_path.read_text(encoding="utf-8"))
    payload["probed_at"] = time.time() - 2000
    record_path.write_text(json.dumps(payload), encoding="utf-8")

    assert _run_cleanup_sweep(fixture) == 1
    assert get_claimed_workspaces(fixture["project_file"]) == []

    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=str(fixture["plans"]),
        capture_output=True,
        text=True,
        check=True,
    )
    assert status.stdout == ""
    head = subprocess.run(
        ["git", "show", "HEAD:202611/next_plan.plan-decisions.json"],
        cwd=str(fixture["plans"]),
        capture_output=True,
        text=True,
        check=True,
    )
    assert head.stdout == fixture["stray"].read_text(encoding="utf-8")

    record = read_workspace_retention_record(fixture["artifacts_dir"])
    assert record is not None
    assert record.payload.get("settled_at")


def test_cleanup_keeps_leaked_monitor_claim_with_real_dirt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A leaked claim with unchanged dirt stays held with no new +1.

    held_settle: the evidence fingerprint is unchanged since the first
    settle, so the sweep skips the re-settle (and its +1) entirely.
    """
    from sase.notifications.store import load_notifications
    from sase.running_field import get_claimed_workspaces

    fixture = _make_leaked_monitor(tmp_path, monkeypatch, dirty_primary=True)

    assert _run_cleanup_sweep(fixture) == 0
    claims = get_claimed_workspaces(fixture["project_file"])
    assert len(claims) == 1
    assert claims[0].pinned is True

    rows = load_notifications()
    assert len(rows) == 1
    assert rows[0].plus_one_count == 0


def test_cleanup_sweep_never_reaches_workspace_provider_ensure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Retained monitor holds resolve their checkout path read-only.

    Every 5 s the hooks-lane sweep re-examines each pinned dead-pid monitor
    hold. It used to resolve the claimed checkout through the workspace
    provider, whose ensure_* functions clone, fetch, and materialize SDD
    sidecars, before reaching the cheap unchanged-hold skip.
    """
    fixture = _make_leaked_monitor(tmp_path, monkeypatch, dirty_primary=True)
    calls: list[str] = []

    def _forbidden(name: str) -> MagicMock:
        return MagicMock(side_effect=lambda *_a, **_k: calls.append(name))

    with (
        patch(
            "sase.ace.scheduler.stale_running_sweep._get_all_project_files",
            return_value=[fixture["project_file"]],
        ),
        patch(
            "sase.ace.scheduler.stale_running_sweep.is_process_running",
            return_value=False,
        ),
        patch(
            "sase.running_field._workspace.get_workspace_directory",
            _forbidden("get_workspace_directory"),
        ),
        patch(
            "sase.workspace_provider._utils_checkout_workspace.ensure_workspace_checkout",
            _forbidden("ensure_workspace_checkout"),
        ),
        patch(
            "sase.workspace_provider.utils.ensure_workspace_checkout",
            _forbidden("ensure_workspace_checkout"),
        ),
        patch(
            "sase.sdd.store.ensure_workspace_sdd_clone",
            _forbidden("ensure_workspace_sdd_clone"),
        ),
    ):
        for _ in range(3):
            assert cleanup_stale_running_entries() == 0

    assert calls == []
