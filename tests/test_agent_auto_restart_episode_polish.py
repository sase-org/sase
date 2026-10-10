"""Episode-polish acceptance: settlement refresh, Now mapping, titles, keys."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import sase.agent.auto_restart.notify as notify
from sase.agent.auto_restart._notify_report import (
    _replacement_outcome,
    display_episode,
)

EPISODE = "sase@9fd8a08"
SHORT = "9fd8a08"


@pytest.fixture
def tmp_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    import sase.core.paths as paths

    monkeypatch.setattr(paths, "sase_home", lambda: home)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home


def _seed(
    name: str,
    *,
    episode: str = EPISODE,
    state: str = "launched",
    launched_outcome: str | None = None,
    index: int = 0,
) -> Any:
    import tempfile

    from sase.agent.auto_restart import ledger as ledger_mod
    from sase.core.agent_auto_restart_wire import AutoRestartLedgerRecordWire

    launched_dir = Path(tempfile.mkdtemp(prefix=f"launched-{name}-{index}-"))
    if launched_outcome is not None:
        (launched_dir / "done.json").write_text(
            json.dumps({"outcome": launched_outcome}), encoding="utf-8"
        )
    evidence = launched_dir / "bundle"
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "error_report.md").write_text("# boom\n", encoding="utf-8")
    record = AutoRestartLedgerRecordWire(
        key=f"polish__{uuid.uuid4().hex[:8]}",
        lineage_root=f"lineage-{name}-{index}",
        state=state,
        claimed_at="2026-10-09T12:00:00+00:00",
        failed_artifacts_dir=f"/tmp/failed-{name}-{index}",
        agent_name=name,
        project="sase",
        episode_id=episode,
        launched_artifacts_dir=str(launched_dir),
        evidence_dir=str(evidence),
    )
    return ledger_mod.store_ledger_record(
        ledger_mod.StoredLedgerRecord(record=record, extra={}),
        extra={
            "python_verdict": {
                "tier": "tier1_torn_python",
                "family": "torn_python_import",
                "signature": "ImportError: cannot import name 'x'",
                "phase_class": "pre_provider",
                "mode": "relaunch",
                "witnesses_fired": ["W1", "W4"],
                "episode_id": episode,
            },
            "python_witnesses": {
                "refresh_log_line": {"from": "9c5000f", "to": "9fd8a08"},
                "file_proof": {
                    "symbol": "x",
                    "culprit_commit": "9fd8a08",
                    "culprit_subject": "feat",
                },
            },
        },
    )


def _live_episode_rows() -> list[Any]:
    from sase.notifications.store import load_notifications

    return [
        r
        for r in load_notifications(include_dismissed=True)
        if r.sender == notify.SENDER
        and (r.dedup_key or "").startswith(f"agent-auto-restart:{EPISODE}")
        and not r.dismissed
    ]


def test_titles_never_show_raw_episode_or_unknown(tmp_home: Path) -> None:
    _ = tmp_home
    assert display_episode(EPISODE) == SHORT
    assert display_episode("unknown") == "a sase update"
    assert display_episode("") == "a sase update"
    _seed("alpha", index=0)
    notify.publish_relaunch(
        episode_id=EPISODE,
        agent_name="alpha",
        update_ref=EPISODE,
        reason_text="skew",
    )
    row = _live_episode_rows()[0]
    assert "sase@" not in row.notes[0]
    assert "unknown" not in row.notes[0].lower()
    assert SHORT in row.notes[0]


def test_now_column_maps_every_terminal_outcome(tmp_path: Path) -> None:
    cases = {
        "completed": "DONE",
        "noop": "DONE",
        "epic_approved": "DONE",
        "plan_committed": "DONE",
        "stopped": "FAILED",
        "failed": "FAILED",
        "killed": "FAILED",
        "epic_launch_failed": "FAILED",
        "timeout": "FAILED",
        "custom_terminal": "DONE",
    }
    for outcome, expected in cases.items():
        launched = tmp_path / f"launched-{outcome}"
        launched.mkdir(exist_ok=True)
        (launched / "done.json").write_text(
            json.dumps({"outcome": outcome}), encoding="utf-8"
        )
        stored = SimpleNamespace(
            record=SimpleNamespace(
                state="launched", launched_artifacts_dir=str(launched)
            )
        )
        assert _replacement_outcome(stored) == expected, outcome
    pending = tmp_path / "launched-pending"
    pending.mkdir(exist_ok=True)
    stored = SimpleNamespace(
        record=SimpleNamespace(state="launched", launched_artifacts_dir=str(pending))
    )
    assert _replacement_outcome(stored) == "RUNNING"


def test_settlement_refreshes_report_and_row_snapshot(tmp_home: Path) -> None:
    _ = tmp_home
    from sase.agent.auto_restart import sweep as sweep_mod

    stored = _seed("alpha", index=0)
    notify.publish_relaunch(
        episode_id=EPISODE, agent_name="alpha", update_ref=SHORT, reason_text="skew"
    )
    report_path = notify.refresh_episode_report(EPISODE)
    assert report_path is not None and report_path.is_file()
    row = _live_episode_rows()[0]
    first_timestamp = row.timestamp
    before = report_path.read_bytes()

    launched = Path(str(stored.record.launched_artifacts_dir))
    (launched / "done.json").write_text(
        json.dumps({"outcome": "completed"}), encoding="utf-8"
    )
    settled = sweep_mod._settle_launched_records()
    assert settled >= 1
    assert report_path.read_bytes() != before
    rows = _live_episode_rows()
    assert len(rows) == 1
    assert rows[0].timestamp == first_timestamp
    snapshot = json.loads(rows[0].action_data["report"])
    rows_block = next(b for b in snapshot["blocks"] if b.get("kind") == "rows")
    now_by_agent = {r["cells"][0]: r["cells"][5] for r in rows_block["rows"]}
    assert now_by_agent["alpha"] == "DONE"


def test_reused_name_escalation_creates_new_row(tmp_home: Path) -> None:
    _ = tmp_home
    import tempfile

    from sase.notifications.store import load_notifications, mark_dismissed

    first_dir = Path(tempfile.mkdtemp(prefix="failed-bead-1-"))
    (first_dir / "error_report.md").write_text("# boom\n", encoding="utf-8")
    notify.resurface_failure(
        agent_name="bead.agent",
        reason_text="first death",
        artifacts_dir=str(first_dir),
    )
    rows = [
        r
        for r in load_notifications(include_dismissed=True)
        if (r.dedup_key or "").startswith("agent-auto-restart-resurfaced:bead.agent")
    ]
    assert len(rows) == 1
    assert mark_dismissed(rows[0].id)

    second_dir = Path(tempfile.mkdtemp(prefix="failed-bead-2-"))
    (second_dir / "error_report.md").write_text("# boom\n", encoding="utf-8")
    notify.resurface_failure(
        agent_name="bead.agent",
        reason_text="second death",
        artifacts_dir=str(second_dir),
    )
    rows = [
        r
        for r in load_notifications(include_dismissed=True)
        if (r.dedup_key or "").startswith("agent-auto-restart-resurfaced:bead.agent")
    ]
    assert len(rows) == 2
    assert len({r.dedup_key for r in rows}) == 2
