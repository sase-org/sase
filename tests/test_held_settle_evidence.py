"""held_settle: settle once per evidence fingerprint, +1 only on change.

Covers the phase requirements: N consecutive cleanup passes over an
unchanged held workspace cause zero store rewrites and zero git subprocess
calls; an index/HEAD touch triggers a re-probe without a +1; a clean hold
releases once the re-probe interval elapses; changed evidence re-snapshots
with exactly one +1; the heartbeat fires hourly on undismissed rows only;
and the dismissed latch survives store compaction.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.notifications.store import (
    load_notifications,
    mark_dismissed,
    notifications_file_path,
    read_notification_snapshot,
)
from sase.running_field import get_claimed_workspaces
from sase.workspace_provider.retention_record import (
    read_workspace_retention_record,
)

from tests._stale_running_cleanup_monitor_claims_retention import (
    _make_leaked_monitor,
    _run_cleanup_sweep,
)


@pytest.fixture(autouse=True)
def _sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)


def _generation() -> int:
    return int(read_notification_snapshot(include_dismissed=True).generation)


def _run_sweeps_counting_git(fixture: dict, count: int) -> tuple[int, list[list[str]]]:
    """Run *count* sweeps, counting every git subprocess invocation."""
    git_calls: list[list[str]] = []
    real_run = subprocess.run

    def counting(*args: object, **kwargs: object) -> object:
        argv = args[0] if args else kwargs.get("args")
        if (
            isinstance(argv, (list, tuple)) and argv and argv[0] == "git"  # noqa: PLR2004 - argv shape check
        ):
            git_calls.append([str(part) for part in argv])
        return real_run(*args, **kwargs)

    released = 0
    with patch("subprocess.run", side_effect=counting):
        for _ in range(count):
            released += _run_cleanup_sweep(fixture)
    return released, git_calls


def _run_sweep_logged(fixture: dict) -> tuple[int, list[str]]:
    """Run one sweep, capturing log lines."""
    from sase.ace.scheduler.stale_running_sweep import cleanup_stale_running_entries

    lines: list[str] = []
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
        released = cleanup_stale_running_entries(
            log_fn=lambda message, _style: lines.append(message)
        )
    return released, lines


def _expire_probed_at(fixture: dict, *, seconds_ago: int = 2000) -> None:
    record_path = (
        Path(fixture["artifacts_dir"]) / "diagnostics" / "workspace_retention.json"
    )
    payload = json.loads(record_path.read_text(encoding="utf-8"))
    payload["probed_at"] = time.time() - seconds_ago
    record_path.write_text(json.dumps(payload), encoding="utf-8")


def _archive_dismissed_rows() -> None:
    """Simulate post-compaction live store: drop dismissed rows from the JSONL."""
    path = notifications_file_path()
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    live = [row for row in rows if not row.get("dismissed")]
    path.write_text("".join(json.dumps(row) + "\n" for row in live), encoding="utf-8")


def _expire_heartbeat(fixture: dict, *, seconds_ago: int = 3700) -> None:
    marker_path = (
        Path(fixture["artifacts_dir"])
        / "diagnostics"
        / "workspace_retention_notify.json"
    )
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    marker["last_plus_one_at"] = time.time() - seconds_ago
    marker_path.write_text(json.dumps(marker), encoding="utf-8")


def test_unchanged_passes_skip_store_git_and_plus_ones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """N unchanged passes: no store rewrite, no git, no +1, still held."""
    fixture = _make_leaked_monitor(tmp_path, monkeypatch, dirty_primary=True)
    assert load_notifications()[0].plus_one_count == 0

    before = _generation()
    released, git_calls = _run_sweeps_counting_git(fixture, 3)

    assert released == 0
    assert git_calls == []
    assert _generation() == before
    assert load_notifications()[0].plus_one_count == 0
    claims = get_claimed_workspaces(fixture["project_file"])
    assert len(claims) == 1
    assert claims[0].pinned is True
    record = read_workspace_retention_record(fixture["artifacts_dir"])
    assert record is not None
    assert record.unresolved


def test_skip_logs_summary_once_per_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A skipped pass logs one summary line instead of per-claim lines."""
    fixture = _make_leaked_monitor(tmp_path, monkeypatch, dirty_primary=True)

    released, lines = _run_sweep_logged(fixture)

    assert released == 0
    assert lines == ["1 held workspace unchanged; skipped re-settlement"]


def test_index_touch_triggers_reprobe_without_plus_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A gitdir HEAD touch re-probes on the next pass but sends no +1."""
    fixture = _make_leaked_monitor(tmp_path, monkeypatch, dirty_primary=True)

    # Expire the interval so the first sweep publishes the stray sheet and
    # records post-publish evidence with its change +1.
    _expire_probed_at(fixture)
    released, _ = _run_sweeps_counting_git(fixture, 1)
    assert released == 0
    assert load_notifications()[0].plus_one_count == 1

    released, _ = _run_sweeps_counting_git(fixture, 1)
    assert released == 0
    before_probed = read_workspace_retention_record(fixture["artifacts_dir"]).probed_at

    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "probe"],
        cwd=str(fixture["checkout"]),
        check=True,
        capture_output=True,
        text=True,
    )

    released, git_calls = _run_sweeps_counting_git(fixture, 1)

    assert released == 0
    assert git_calls != []
    assert load_notifications()[0].plus_one_count == 1
    after_probed = read_workspace_retention_record(fixture["artifacts_dir"]).probed_at
    assert after_probed is not None
    assert before_probed is not None
    assert after_probed > before_probed


def test_cleaned_hold_releases_after_reprobe_interval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A hold cleaned without touching the index releases once probed again."""
    fixture = _make_leaked_monitor(tmp_path, monkeypatch, dirty_primary=True)

    released, _ = _run_sweeps_counting_git(fixture, 1)
    assert released == 0

    (fixture["checkout"] / "tracked.txt").write_text("base\n", encoding="utf-8")
    fixture["stray"].unlink()

    released, _ = _run_sweeps_counting_git(fixture, 1)
    assert released == 0
    assert len(get_claimed_workspaces(fixture["project_file"])) == 1

    _expire_probed_at(fixture)
    released, _ = _run_sweeps_counting_git(fixture, 1)

    assert released == 1
    assert get_claimed_workspaces(fixture["project_file"]) == []
    record = read_workspace_retention_record(fixture["artifacts_dir"])
    assert record is not None
    assert not record.unresolved


def test_changed_evidence_resnapshots_with_single_change_plus_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Changed evidence re-snapshots and sends exactly one +1 naming it."""
    from sase.monitor._settlement_retention import release_monitor_claim
    from tests.monitor._retention_fixtures import (
        init_retention_repo,
        make_retention_monitor,
        read_retention_meta,
        write_monitor_baselines,
    )

    repo = init_retention_repo(tmp_path / "ws", dirty=True)
    artifacts_dir, _ = make_retention_monitor(repo)
    write_monitor_baselines(artifacts_dir, [("primary", repo)])
    meta = read_retention_meta(artifacts_dir)

    assert (
        release_monitor_claim(meta, project_name="proj", artifacts_dir=artifacts_dir)
        is None
    )
    meta = read_retention_meta(artifacts_dir)
    assert (
        release_monitor_claim(meta, project_name="proj", artifacts_dir=artifacts_dir)
        is None
    )
    rows = load_notifications()
    assert len(rows) == 1
    assert rows[0].plus_one_count == 0

    (repo / "new_evidence.txt").write_text("new dirt\n", encoding="utf-8")
    meta = read_retention_meta(artifacts_dir)
    assert (
        release_monitor_claim(meta, project_name="proj", artifacts_dir=artifacts_dir)
        is None
    )

    rows = load_notifications()
    assert len(rows) == 1
    assert rows[0].plus_one_count == 1
    assert "evidence changed" in rows[0].plus_ones[-1].note
    record = read_workspace_retention_record(artifacts_dir)
    assert record is not None
    assert record.evidence_fingerprint
    assert record.snapshot_paths != ()


def test_hourly_heartbeat_only_when_due(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The heartbeat sends one +1 after an hour, then stays quiet."""
    fixture = _make_leaked_monitor(tmp_path, monkeypatch, dirty_primary=True)

    released, _ = _run_sweeps_counting_git(fixture, 1)
    assert released == 0
    assert load_notifications()[0].plus_one_count == 0

    _expire_heartbeat(fixture)
    released, _ = _run_sweeps_counting_git(fixture, 1)

    assert released == 0
    rows = load_notifications()
    assert rows[0].plus_one_count == 1
    assert rows[0].plus_ones[-1].note.startswith("Workspace still held (")

    released, _ = _run_sweeps_counting_git(fixture, 1)
    assert released == 0
    assert load_notifications()[0].plus_one_count == 1


def test_dismissed_latch_survives_compaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A dismissed row latches: no heartbeat, and no resurrection row."""
    fixture = _make_leaked_monitor(tmp_path, monkeypatch, dirty_primary=True)

    released, _ = _run_sweeps_counting_git(fixture, 1)
    assert released == 0
    row = load_notifications()[0]
    assert mark_dismissed(row.id) is True

    _expire_heartbeat(fixture)
    released, _ = _run_sweeps_counting_git(fixture, 1)

    assert released == 0
    assert load_notifications(include_dismissed=True)[0].plus_one_count == 0
    marker_path = (
        Path(fixture["artifacts_dir"])
        / "diagnostics"
        / "workspace_retention_notify.json"
    )
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    assert marker.get("dismissed_latch") is True

    _archive_dismissed_rows()

    released, _ = _run_sweeps_counting_git(fixture, 1)
    assert released == 0
    assert load_notifications(include_dismissed=True) == []
