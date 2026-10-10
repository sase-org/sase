"""Tests for the episode-notify experience (one upserted row per episode)."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import pytest

import sase.agent.auto_restart.notify as notify
from sase.agent.auto_restart.healer import HealerTarget

EPISODE = "sase@9fd8a08"


@pytest.fixture
def tmp_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolate all state-dir writes (ledger, reports, notifications)."""
    home = tmp_path / "home"
    home.mkdir()
    import sase.core.paths as paths

    monkeypatch.setattr(paths, "sase_home", lambda: home)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home


def _seed_record(
    tmp_home: Path,
    name: str,
    *,
    project: str = "sase",
    episode: str = EPISODE,
    state: str = "launched",
    decline_reason: str | None = None,
    launched_outcome: str | None = None,
    index: int = 0,
) -> Any:
    """Store one ledger record carrying the episode, with verdict extras."""
    from sase.agent.auto_restart import ledger as ledger_mod
    from sase.core.agent_auto_restart_wire import AutoRestartLedgerRecordWire

    _ = tmp_home
    launched_dir = tmp_path_launched_dir(name, index)
    if launched_outcome is not None:
        launched_dir.mkdir(parents=True, exist_ok=True)
        (launched_dir / "done.json").write_text(
            json.dumps({"outcome": launched_outcome}), encoding="utf-8"
        )
    evidence = launched_dir / "bundle"
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "error_report.md").write_text("# boom\n", encoding="utf-8")
    record = AutoRestartLedgerRecordWire(
        key=f"test__{uuid.uuid4().hex[:8]}",
        lineage_root=f"lineage-{name}-{index}",
        state=state,
        claimed_at="2026-10-09T12:00:00+00:00",
        failed_artifacts_dir=f"/tmp/failed-{name}",
        agent_name=name,
        project=project,
        episode_id=episode,
        launched_artifacts_dir=str(launched_dir) if state != "declined" else None,
        evidence_dir=str(evidence),
        decline_reason=decline_reason,
    )
    stored = ledger_mod.StoredLedgerRecord(record=record, extra={})
    return ledger_mod.store_ledger_record(
        stored,
        extra={
            "python_verdict": {
                "tier": "tier1_torn_python",
                "family": "torn_python_import",
                "signature": ("ImportError: cannot import name 'auto_launch_prefix'"),
                "phase_class": "pre_provider",
                "mode": "relaunch",
                "witnesses_fired": ["W1", "W4"],
                "episode_id": episode,
            },
            "python_witnesses": {
                "refresh_log_line": {"from": "9c5000f", "to": "9fd8a08"},
                "file_proof": {
                    "symbol": "auto_launch_prefix",
                    "module": "sase.monitor.continuation_delivery",
                    "boot_has": True,
                    "head_has": False,
                    "culprit_commit": "9fd8a08",
                    "culprit_subject": "feat(autonomy): structural inheritance",
                },
            },
        },
    )


def tmp_path_launched_dir(name: str, index: int) -> Path:
    import tempfile

    return Path(tempfile.mkdtemp(prefix=f"launched-{name}-{index}-"))


def _expected_report_path() -> Path:
    from sase.agent.auto_restart.ledger import auto_restart_root

    return auto_restart_root() / "episodes" / f"{EPISODE}.report.json"


def _episode_rows() -> list[Any]:
    from sase.notifications.store import load_notifications

    return [
        r
        for r in load_notifications(include_dismissed=True)
        if r.sender == notify.SENDER
        and (r.dedup_key or "").startswith(f"agent-auto-restart:{EPISODE}")
    ]


def test_five_agents_one_row_four_plus_ones(tmp_home: Path) -> None:
    names = ["alpha", "bravo", "casa", "delta", "echo"]
    first_timestamp = None
    for i, name in enumerate(names):
        _seed_record(tmp_home, name, index=i)
        outcome = notify.publish_relaunch(
            episode_id=EPISODE,
            agent_name=name,
            update_ref=EPISODE,
            reason_text="in-memory code asked the new tree for a removed symbol",
            evidence_files=[f"/tmp/bundle-{name}"],
        )
        if i == 0:
            assert outcome is not None and outcome.action == "created"
            first_timestamp = _episode_rows()[0].timestamp
        else:
            assert outcome is not None and outcome.action == "plus_oned"

    rows = [r for r in _episode_rows() if not r.dismissed]
    assert len(rows) == 1
    row = rows[0]
    assert row.plus_one_count == 4
    assert row.notes[0] == f"↻ Restarted 5 agents after sase update {EPISODE}"
    assert "fail" not in row.notes[0].lower()
    assert "error" not in row.notes[0].lower()
    # Title refreshes must not move delivery cursors: only the create toasts.
    assert row.timestamp == first_timestamp
    assert row.resurfaced_at is None
    assert row.action == "ViewReport"
    assert row.action_data["report_path"] == str(_expected_report_path())
    assert "report" in row.action_data

    from sase.ace.tui.actions.agents._toasts import _format_notification_toast

    message, severity = _format_notification_toast(row)
    assert severity == "information"
    assert message == row.notes[0]
    assert message.startswith("↻ Restarted 5 agents")


def test_live_report_settles_with_replacements(tmp_home: Path) -> None:
    _seed_record(tmp_home, "alpha", index=0, launched_outcome="completed")
    launched = _seed_record(tmp_home, "bravo", index=1)
    notify.publish_relaunch(
        episode_id=EPISODE,
        agent_name="bravo",
        update_ref=EPISODE,
        reason_text="skew",
    )
    path = notify.refresh_episode_report(EPISODE)
    assert path is not None and path.is_file()

    from sase.chops import validate_chop_report

    document = json.loads(path.read_text(encoding="utf-8"))
    validate_chop_report(document)
    kinds = [b.get("kind") for b in document["blocks"]]
    assert kinds[0] == "headline"
    assert document["blocks"][0]["text"] == "2 agents restarted · 0 left alone"
    assert "rows" in kinds and "kv" in kinds and "divider" in kinds
    for block in document["blocks"]:
        # The Rust validator normalizes absent tones to explicit nulls.
        assert block.get("tone") in (None, "ok", "warn", "muted")
    rows_block = next(b for b in document["blocks"] if b.get("kind") == "rows")
    assert rows_block["columns"] == [
        "Agent",
        "Project",
        "Broke during",
        "Signature",
        "Action",
        "Now",
    ]
    now_by_agent = {r["cells"][0]: r["cells"][5] for r in rows_block["rows"]}
    assert now_by_agent["alpha"] == "DONE"
    assert now_by_agent["bravo"] == "RUNNING"
    # The replacement settles: the Now column follows without a new row.
    launched_dir = Path(str(launched.record.launched_artifacts_dir))
    launched_dir.mkdir(parents=True, exist_ok=True)
    (launched_dir / "done.json").write_text(
        json.dumps({"outcome": "failed"}), encoding="utf-8"
    )
    notify.refresh_episode_report(EPISODE)
    document = json.loads(path.read_text(encoding="utf-8"))
    rows_block = next(b for b in document["blocks"] if b.get("kind") == "rows")
    now_by_agent = {r["cells"][0]: r["cells"][5] for r in rows_block["rows"]}
    assert now_by_agent["bravo"] == "FAILED"


def test_dismissed_episode_rolls_over(tmp_home: Path) -> None:
    from sase.notifications.store import mark_dismissed

    _seed_record(tmp_home, "alpha", index=0)
    notify.publish_relaunch(
        episode_id=EPISODE, agent_name="alpha", update_ref=EPISODE, reason_text="skew"
    )
    assert len(_episode_rows()) == 1
    assert mark_dismissed(_episode_rows()[0].id)

    _seed_record(tmp_home, "bravo", index=1)
    notify.publish_relaunch(
        episode_id=EPISODE, agent_name="bravo", update_ref=EPISODE, reason_text="skew"
    )
    rows = _episode_rows()
    assert len(rows) == 2
    keys = sorted(r.dedup_key or "" for r in rows)
    assert keys[0] == f"agent-auto-restart:{EPISODE}"
    assert keys[1] == f"{f'agent-auto-restart:{EPISODE}'}#2"
    live = [r for r in rows if not r.dismissed]
    assert len(live) == 1 and live[0].dedup_key == keys[1]


def test_storm_escalation_is_loud_error(tmp_home: Path) -> None:
    _ = tmp_home
    from sase.ace.tui.actions.agents._toasts import _format_notification_toast
    from sase.notifications.priority import is_error
    from sase.notifications.store import load_notifications

    notify.publish_escalation(
        agent_name="alpha",
        title="Auto-restart paused: 13 automatic launches",
        detail="Episode sase@9fd8a08.",
        episode_id=EPISODE,
        kind="storm",
    )
    rows = [
        r
        for r in load_notifications(include_dismissed=True)
        if r.sender == notify.SENDER
    ]
    assert len(rows) == 1
    assert rows[0].action == "ViewErrorReport"
    assert is_error(rows[0])
    message, severity = _format_notification_toast(rows[0])
    assert severity == "error"
    assert not message.startswith("Axe:")


def test_declined_escalation_resurfaces_agent_row(tmp_home: Path) -> None:
    _ = tmp_home
    from sase.notifications.priority import is_error
    from sase.notifications.store import load_notifications

    notify.publish_escalation(
        agent_name="alpha",
        title="Couldn't restart alpha automatically — no witness",
        detail="Press ,x on it to retry by hand.",
        episode_id=EPISODE,
    )
    rows = load_notifications(include_dismissed=True)
    assert len(rows) == 1
    assert rows[0].sender == "user-agent"
    assert rows[0].action == "ViewErrorReport"
    assert is_error(rows[0])


def test_single_agent_title_and_notes0_rule(tmp_home: Path) -> None:
    _seed_record(tmp_home, "solo", index=0)
    notify.publish_relaunch(
        episode_id=EPISODE, agent_name="solo", update_ref=EPISODE, reason_text="skew"
    )
    rows = [r for r in _episode_rows() if not r.dismissed]
    assert len(rows) == 1
    assert rows[0].notes[0] == f"↻ Restarted solo after sase update {EPISODE}"
    assert "fail" not in rows[0].notes[0].lower()
    assert "error" not in rows[0].notes[0].lower()


def test_healer_escalation_copy_per_situation(
    tmp_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ = tmp_home
    import sase.agent.auto_restart.healer as healer_mod

    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(notify, "publish_escalation", lambda **kw: calls.append(kw))
    target = HealerTarget(
        artifacts_dir=tmp_path_launched_dir("copy", 99),
        project="sase",
        agent_name="research.46.final",
    )
    healer_mod._escalate(target, "no witness", episode_id=EPISODE, kind="decline")
    healer_mod._escalate(target, "post turn", episode_id=EPISODE, kind="post_provider")
    healer_mod._escalate(
        target, "already spent", episode_id=EPISODE, kind="already_restarted"
    )
    healer_mod._escalate(target, "13 in flight", episode_id=EPISODE, kind="storm")
    assert len(calls) == 4

    decline, post, spent, storm = calls
    assert decline["title"].startswith(
        "Couldn't restart research.46.final automatically"
    )
    assert post["title"].startswith(
        "research.46.final broke after its model turn during a sase update"
    )
    assert "This was its automatic restart" in spent["title"]
    assert EPISODE in spent["title"]
    assert storm["kind"] == "storm"
    assert storm["title"].startswith("Auto-restart paused:")
    assert all(c["kind"] != "storm" for c in (decline, post, spent))
