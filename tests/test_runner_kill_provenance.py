"""Tests for shared SIGTERM kill-source classification."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from sase.agent._user_kill_intent import write_user_kill_intent
from sase.axe.run_agent_exec import _handle_killed_iteration
from sase.axe.run_agent_exec_retry import RetryTracker, handle_workflow_error
from sase.axe.run_agent_markers import build_done_marker
from sase.axe.runner_kill_provenance import (
    _KillProvenance,
    _classify_runner_kill,
    _format_kill_classification,
    _oom_kill_evidence,
    _reset_oom_baseline,
    record_kill_provenance,
    snapshot_oom_baseline,
)
from tests._axe_run_agent_exec_retry_helpers import (
    config_with_nudge,
    make_ctx,
    make_state,
)


@pytest.fixture(autouse=True)
def _clean_oom_baseline():
    _reset_oom_baseline()
    yield
    _reset_oom_baseline()


class _FakeKills:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def labels(self, **kwargs: Any) -> _FakeKills:
        self.calls.append(kwargs)
        return self

    def inc(self) -> None:
        return None


@pytest.fixture()
def fake_kills(monkeypatch: pytest.MonkeyPatch) -> _FakeKills:
    fake = _FakeKills()
    monkeypatch.setattr("sase.telemetry.metrics.AGENT_KILLS", fake)
    return fake


def _artifacts(tmp_path: Path) -> str:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir(exist_ok=True)
    return str(artifacts)


def test_classify_user_kill_intent(tmp_path: Path) -> None:
    artifacts = _artifacts(tmp_path)
    write_user_kill_intent(artifacts, pid=123, source="test")

    provenance = _classify_runner_kill(artifacts, kill_time=1000.0)

    assert provenance.source == "user"
    assert provenance.evidence is None


def test_classify_handoff_marker_predating_kill(tmp_path: Path) -> None:
    artifacts = _artifacts(tmp_path)
    with open(
        os.path.join(artifacts, ".sase_plan_pending"), "w", encoding="utf-8"
    ) as f:
        json.dump({"timestamp": 999.0}, f)

    provenance = _classify_runner_kill(artifacts, kill_time=1000.0)

    assert provenance.source == "handoff"


def test_classify_external_without_markers(tmp_path: Path) -> None:
    provenance = _classify_runner_kill(_artifacts(tmp_path), kill_time=1000.0)

    assert provenance.source == "external"
    assert provenance.evidence is None


def test_record_external_increments_metric_and_stashes_state(
    tmp_path: Path,
    fake_kills: _FakeKills,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state = make_state("Do the work.")

    provenance = record_kill_provenance(_artifacts(tmp_path), state, kill_time=1000.0)

    assert provenance.source == "external"
    assert fake_kills.calls == [{"reason": "external"}]
    assert state.kill_source == "external"
    assert state.kill_evidence is None
    assert "Kill source: external" in capsys.readouterr().err


def test_record_user_increments_user_metric(
    tmp_path: Path, fake_kills: _FakeKills
) -> None:
    artifacts = _artifacts(tmp_path)
    write_user_kill_intent(artifacts, pid=123, source="test")
    state = make_state("Do the work.")

    provenance = record_kill_provenance(artifacts, state, kill_time=1000.0)

    assert provenance.source == "user"
    assert fake_kills.calls == [{"reason": "user"}]
    assert state.kill_source == "user"


def test_record_handoff_reports_no_metric(
    tmp_path: Path, fake_kills: _FakeKills
) -> None:
    artifacts = _artifacts(tmp_path)
    with open(
        os.path.join(artifacts, ".sase_plan_pending"), "w", encoding="utf-8"
    ) as f:
        json.dump({"timestamp": 999.0}, f)

    provenance = record_kill_provenance(artifacts, None, kill_time=1000.0)

    assert provenance.source == "handoff"
    assert fake_kills.calls == []


def test_format_external_line_with_oom_evidence() -> None:
    line = _format_kill_classification(
        _KillProvenance(
            source="external",
            evidence={"cgroup_unit": "tmux-spawn-abc.scope", "oom_kill_delta": 1},
        )
    )

    assert line.startswith("Kill source: external")
    assert "tmux-spawn-abc.scope" in line
    assert "1 OOM kill" in line


def _fake_cgroup_roots(tmp_path: Path, *, oom_kill: int) -> tuple[Path, Path, str]:
    pid = os.getpid()
    proc_root = tmp_path / "proc"
    (proc_root / str(pid)).mkdir(parents=True, exist_ok=True)
    (proc_root / str(pid) / "cgroup").write_text(
        "0::/user.slice/user-1000.slice/user@1000.service/tmux-spawn-abc.scope\n",
        encoding="utf-8",
    )
    sysfs_root = tmp_path / "sys"
    events_dir = (
        sysfs_root
        / "user.slice"
        / "user-1000.slice"
        / "user@1000.service"
        / "tmux-spawn-abc.scope"
    )
    events_dir.mkdir(parents=True, exist_ok=True)
    (events_dir / "memory.events").write_text(
        f"low 0\nhigh 0\nmax 0\noom 0\noom_kill {oom_kill}\n",
        encoding="utf-8",
    )
    return proc_root, sysfs_root, "tmux-spawn-abc.scope"


def test_oom_evidence_delta_with_fake_roots(tmp_path: Path) -> None:
    proc_root, sysfs_root, unit = _fake_cgroup_roots(tmp_path, oom_kill=0)
    snapshot_oom_baseline(proc_root=proc_root, sysfs_root=sysfs_root)

    _fake_cgroup_roots(tmp_path, oom_kill=1)
    evidence = _oom_kill_evidence(proc_root=proc_root, sysfs_root=sysfs_root)

    assert evidence == {"oom_kill_delta": 1, "cgroup_unit": unit}


def test_oom_evidence_missing_without_increase(tmp_path: Path) -> None:
    proc_root, sysfs_root, _ = _fake_cgroup_roots(tmp_path, oom_kill=0)
    snapshot_oom_baseline(proc_root=proc_root, sysfs_root=sysfs_root)

    assert _oom_kill_evidence(proc_root=proc_root, sysfs_root=sysfs_root) is None


def test_oom_evidence_missing_without_counter_file(tmp_path: Path) -> None:
    pid = os.getpid()
    proc_root = tmp_path / "proc"
    (proc_root / str(pid)).mkdir(parents=True)
    (proc_root / str(pid) / "cgroup").write_text(
        "0::/user.slice/session-2.scope\n", encoding="utf-8"
    )
    sysfs_root = tmp_path / "sys"
    sysfs_root.mkdir()
    snapshot_oom_baseline(proc_root=proc_root, sysfs_root=sysfs_root)

    assert _oom_kill_evidence(proc_root=proc_root, sysfs_root=sysfs_root) is None


def _minimal_done_kwargs(tmp_path: Path) -> dict[str, Any]:
    return {
        "cl_name": "test-cl",
        "project_file": str(tmp_path / "project.sase"),
        "timestamp": "20260421_120000",
        "artifacts_timestamp": "20260421_120000",
        "workspace_num": 1,
        "workspace_dir": str(tmp_path),
        "output_path": str(tmp_path / "output.log"),
        "outcome": "killed",
    }


def test_done_marker_carries_external_kill_source(tmp_path: Path) -> None:
    marker = build_done_marker(
        kill_source="external",
        kill_evidence={"cgroup_unit": "tmux-spawn-abc.scope", "oom_kill_delta": 1},
        **_minimal_done_kwargs(tmp_path),
    )

    assert marker["outcome"] == "killed"
    assert marker["kill_source"] == "external"
    assert marker["kill_evidence"] == {
        "cgroup_unit": "tmux-spawn-abc.scope",
        "oom_kill_delta": 1,
    }


def test_done_marker_omits_kill_keys_when_not_killed(tmp_path: Path) -> None:
    kwargs = _minimal_done_kwargs(tmp_path)
    kwargs["outcome"] = "completed"
    marker = build_done_marker(**kwargs)

    assert "kill_source" not in marker
    assert "kill_evidence" not in marker


def test_handle_killed_iteration_external(
    tmp_path: Path,
    fake_kills: _FakeKills,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ctx = make_ctx(tmp_path)
    state = make_state("Do the work.")
    state.current_artifacts_dir = ctx.artifacts_dir

    outcome = _handle_killed_iteration(ctx, state)

    assert outcome == "killed"
    assert state.loop_outcome != "external"
    assert state.kill_source == "external"
    assert fake_kills.calls == [{"reason": "external"}]
    assert "Kill source: external" in capsys.readouterr().err


def test_handle_killed_iteration_user(tmp_path: Path, fake_kills: _FakeKills) -> None:
    ctx = make_ctx(tmp_path)
    write_user_kill_intent(ctx.artifacts_dir, pid=123, source="test")
    state = make_state("Do the work.")
    state.current_artifacts_dir = ctx.artifacts_dir

    outcome = _handle_killed_iteration(ctx, state)

    assert outcome == "killed"
    assert state.kill_source == "user"
    assert fake_kills.calls == [{"reason": "user"}]


def test_retry_wait_kill_records_external_provenance(
    tmp_path: Path, fake_kills: _FakeKills
) -> None:
    ctx = make_ctx(tmp_path)
    state = make_state("Do the work.")
    tracker = RetryTracker(retry_cfg=config_with_nudge("NUDGE", max_retries=2))

    with (
        patch("sase.axe.run_agent_exec_retry.time.sleep", MagicMock()),
        patch("sase.axe.run_agent_exec_retry.was_killed", return_value=True),
        patch("sase.axe.run_agent_exec_retry.prepare_workspace", MagicMock()),
        patch("sase.linked_repos.clear_workspace_repos"),
    ):
        action = handle_workflow_error(
            RuntimeError("API Error: 400 - Prompt is too long"),
            tracker,
            ctx,
            state,
        )

    assert action == "break"
    assert state.loop_outcome == "killed"
    assert state.kill_source == "external"
    assert fake_kills.calls == [{"reason": "external"}]
