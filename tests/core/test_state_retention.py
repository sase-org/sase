from __future__ import annotations

from pathlib import Path

from sase.core.disk_footprint_models import DiskReapStep
from sase.core.state_retention import run_state_retention


def _step(**details: object) -> DiskReapStep:
    return DiskReapStep(
        owner="tool_run_retention",
        mode="apply",
        summary="applied",
        changed=True,
        details={
            "summary_rows": 1,
            "detail_rows": 0,
            "removed_files": 2,
            "empty_dirs_scanned": 3,
            "empty_dirs_selected": 1,
            "empty_dirs_removed": 1,
            "empty_dirs": ["/tmp/run-empty"],
            "protected_unsettled": 0,
            **details,
        },
    )


def _quiet_step(owner: str = "quiet") -> DiskReapStep:
    return DiskReapStep(
        owner=owner,
        mode="apply",
        summary="nothing eligible",
        changed=False,
        details={"removed": 0},
    )


def _stub_backlog_owners(monkeypatch) -> None:
    monkeypatch.setattr(
        "sase.core.state_retention.proc_log_lock_reap_step",
        lambda apply: _quiet_step("proc_log_lock_sweep"),
    )
    monkeypatch.setattr(
        "sase.core.state_retention.registry_tmp_reap_step",
        lambda apply: _quiet_step("registry_tmp_sweep"),
    )


def test_state_retention_applies_owner_without_pressure(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls: list[bool] = []
    _stub_backlog_owners(monkeypatch)
    monkeypatch.setattr(
        "sase.core.state_retention.tool_run_reap_step",
        lambda apply: calls.append(apply) or _step(),
    )
    monkeypatch.setattr(
        "sase.core.state_retention.get_tool_run_housekeeping_interval_seconds",
        lambda: 3600,
    )
    stamp = tmp_path / "stamp.json"
    outcome = run_state_retention(now=1_000.0, stamp_path=stamp)
    assert calls == [True]
    assert outcome.owner_applied is True
    assert outcome.owner_skipped is False
    assert outcome.empty_dirs.removed == 1
    assert stamp.exists()


def test_state_retention_interval_gate_skips_owner_and_still_sweeps(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls: list[bool] = []
    _stub_backlog_owners(monkeypatch)
    monkeypatch.setattr(
        "sase.core.state_retention.tool_run_reap_step",
        lambda apply: calls.append(apply) or _step(),
    )
    monkeypatch.setattr(
        "sase.core.state_retention.get_tool_run_housekeeping_interval_seconds",
        lambda: 3600,
    )
    home = tmp_path / "home"
    empty = home / "tools" / "logs" / "run-empty"
    empty.mkdir(parents=True)
    live = home / "tools" / "logs" / "run-live"
    live.mkdir()
    (live / "stdout.log").write_text("keep", encoding="utf-8")
    monkeypatch.setenv("SASE_HOME", str(home))
    stamp = tmp_path / "stamp.json"
    first = run_state_retention(now=1_000.0, stamp_path=stamp)
    assert first.owner_applied is True
    second = run_state_retention(now=1_000.0 + 10, stamp_path=stamp)
    assert calls == [True]
    assert second.owner_applied is False
    assert second.owner_skipped is True
    assert not empty.exists()
    assert live.exists()
    third = run_state_retention(now=1_000.0 + 3600, stamp_path=stamp)
    assert calls == [True, True]
    assert third.owner_applied is True


def test_state_retention_blocked_owner_still_removes_empty_dirs(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _stub_backlog_owners(monkeypatch)
    monkeypatch.setattr(
        "sase.core.state_retention.tool_run_reap_step",
        lambda apply: DiskReapStep(
            owner="tool_run_retention",
            mode="blocked",
            summary="could not inspect tool run owner",
            command=("sase", "disk", "reap", "--apply"),
            exit_code=1,
        ),
    )
    home = tmp_path / "home"
    empty = home / "tools" / "logs" / "run-empty"
    empty.mkdir(parents=True)
    monkeypatch.setenv("SASE_HOME", str(home))
    outcome = run_state_retention(
        now=1.0,
        interval_seconds=1,
        stamp_path=tmp_path / "stamp.json",
    )
    assert outcome.owner_applied is False
    assert not empty.exists()
    assert outcome.errors
    assert not (tmp_path / "stamp.json").exists()


def test_state_retention_reaps_backlog_owners_every_pass(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from sase.core.state_retention import outcome_summary_fields

    lock_calls: list[bool] = []
    tmp_calls: list[bool] = []
    monkeypatch.setattr(
        "sase.core.state_retention.tool_run_reap_step",
        lambda apply: _step(),
    )
    monkeypatch.setattr(
        "sase.core.state_retention.proc_log_lock_reap_step",
        lambda apply: (
            lock_calls.append(apply)
            or DiskReapStep(
                owner="proc_log_lock_sweep",
                mode="apply",
                summary="removed 3 orphan proc log lock(s)",
                changed=True,
                details={"removed": 3},
            )
        ),
    )
    monkeypatch.setattr(
        "sase.core.state_retention.registry_tmp_reap_step",
        lambda apply: (
            tmp_calls.append(apply)
            or DiskReapStep(
                owner="registry_tmp_sweep",
                mode="apply",
                summary="removed 1 stale registry temp file(s)",
                changed=True,
                details={"removed": 1},
            )
        ),
    )
    monkeypatch.setattr(
        "sase.core.state_retention.get_tool_run_housekeeping_interval_seconds",
        lambda: 3600,
    )

    outcome = run_state_retention(now=1_000.0, stamp_path=tmp_path / "stamp.json")

    assert lock_calls == [True]
    assert tmp_calls == [True]
    assert outcome.proc_log_lock_step is not None
    assert outcome.registry_tmp_step is not None
    assert not outcome.errors
    assert outcome_summary_fields(outcome)["proc_log_locks_removed"] == 3
    assert outcome_summary_fields(outcome)["registry_tmps_removed"] == 1


def test_state_retention_folds_backlog_owner_failure_into_errors(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _stub_backlog_owners(monkeypatch)
    monkeypatch.setattr(
        "sase.core.state_retention.tool_run_reap_step",
        lambda apply: _step(),
    )
    monkeypatch.setattr(
        "sase.core.state_retention.registry_tmp_reap_step",
        lambda apply: DiskReapStep(
            owner="registry_tmp_sweep",
            mode="blocked",
            summary="could not sweep registry temp files: boom",
            command=("sase", "disk", "reap", "--apply"),
            exit_code=1,
        ),
    )
    monkeypatch.setattr(
        "sase.core.state_retention.get_tool_run_housekeeping_interval_seconds",
        lambda: 3600,
    )

    outcome = run_state_retention(now=1_000.0, stamp_path=tmp_path / "stamp.json")

    assert outcome.registry_tmp_step is not None
    assert outcome.errors
    assert any("registry_tmp_sweep" in error for error in outcome.errors)
