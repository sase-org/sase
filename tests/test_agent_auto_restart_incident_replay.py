"""End-to-end replay of the 2026-10-09 update-skew incident (land acceptance).

Replays the incident with fakes for provider and launch, through the real
doorbell, scheduler tick, healer, ledger, notification, and live-report
components:

1. A runner boots with identity A and parks on ``%wait``.
2. A simulated update to identity B removes ``auto_launch_prefix`` on a
   deferred path.
3. The runner fails pre-provider with the incident's ``ImportError``.
4. The doorbell rings, the job submits the healer proc, and the healer
   relaunches under the same name with provenance.
5. Exactly one episode notification and one information toast appear; the
   live report's **Now** column settles RUNNING → DONE.
6. A second failure of the replacement is declined (never relaunched) and
   surfaced with the loud not-retrying copy.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

import sase.agent.auto_restart.notify as notify
from sase.agent.auto_restart.healer import HealerTarget, heal_one, write_recovery
from sase.agent.auto_restart.provenance import PROVENANCE_ENV
from sase.axe import runner_auto_restart_doorbell as doorbell_mod

EPISODE = "sase@9fd8a08"
AGENT_NAME = "research.46.final"
INCIDENT_ERROR = (
    "ImportError: cannot import name 'auto_launch_prefix' "
    "from 'sase.monitor.continuation_delivery'"
)


@pytest.fixture
def tmp_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolate all state-dir writes (doorbells, ledger, reports, notes)."""
    home = tmp_path / "home"
    home.mkdir()
    import sase.core.paths as paths

    monkeypatch.setattr(paths, "sase_home", lambda: home)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("SASE_HOME", str(home))
    return home


@pytest.fixture
def incident_row(tmp_path: Path) -> Path:
    """The incident's failed row: booted at A, parked on %wait, broke at B."""
    artifacts = tmp_path / "artifacts" / "ace-run" / "20261009T120400"
    artifacts.mkdir(parents=True)
    (artifacts / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": AGENT_NAME,
                "booted_at": "2026-10-09T11:55:00+00:00",
                "lifecycle_phase": "waiting",
                "code_identity": {
                    "schema_version": 1,
                    "roots": [
                        {
                            "name": "sase",
                            "role": "host",
                            "version": "0.18.0",
                            "commit": "9c5000f",
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    (artifacts / "done.json").write_text(
        json.dumps(
            {
                "outcome": "failed",
                "error": INCIDENT_ERROR,
                "finished_at": 1720000000.0,
                "failure_facts": {
                    "lifecycle_phase": "waiting",
                    "skew_suspect": True,
                    "last_frame_file": ("src/sase/axe/run_agent_runner_refresh.py"),
                },
            }
        ),
        encoding="utf-8",
    )
    (artifacts / "error_report.md").write_text(
        f"# {INCIDENT_ERROR}\n\nRefreshing sase runner code after %wait.\n",
        encoding="utf-8",
    )
    return artifacts


def _relaunch_verdict() -> SimpleNamespace:
    """The classifier's verdict for the incident: torn import, pre-provider."""
    return SimpleNamespace(
        tier="1",
        family="torn_python_import",
        signature=INCIDENT_ERROR,
        origin_module="sase.monitor.continuation_delivery",
        missing_symbol="auto_launch_prefix",
        phase_class="pre_provider",
        mode="relaunch",
        reason="torn_python",
        reason_text="in-memory code asked the new tree for a removed symbol",
        witnesses_fired=("W1", "W3", "W4"),
        episode_id=EPISODE,
    )


def test_incident_replay_end_to_end(
    tmp_home: Path,
    incident_row: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = tmp_home
    import sase.agent.auto_restart._healer_common as healer_common
    from sase.agent.auto_restart import ledger as ledger_mod
    from sase.agent.auto_restart import sweep as sweep_mod

    target = HealerTarget(
        artifacts_dir=incident_row, project="sase", agent_name=AGENT_NAME
    )

    # Step 3-4a: the dying runner marks recovery pending and rings the doorbell.
    write_recovery(target, "pending", "sase update moved HEAD during %wait")
    doorbell_path = doorbell_mod.drop_doorbell(
        artifacts_dir=str(incident_row),
        project="sase",
        agent_name=AGENT_NAME,
    )
    assert doorbell_path is not None and Path(doorbell_path).is_file()

    # Step 4b: the scheduler job sweeps and submits the healer as a proc.
    # The submission is captured; the healer body runs inline below, exactly
    # as the durable proc would run it.
    submissions: list[int] = []
    monkeypatch.setattr(
        "sase.agent.auto_restart.gate.auto_restart_automatic_enabled",
        lambda: True,
    )
    with (
        patch("sase.procs.store.read_procs", return_value=[]),
        patch.object(
            sweep_mod,
            "_submit_healer_proc",
            lambda *, count: submissions.append(count) or True,
        ),
    ):
        tick = sweep_mod.run_job_tick()
    assert tick.action == "submitted", tick
    assert submissions == [1]

    # Step 4c: the healer claims the ledger and relaunches under the same name.
    launched: list[str] = []
    planned_names: list[str] = []

    def fake_plan(name: str, *, follow_live_autonomy: bool = True) -> Any:
        planned_names.append(name)
        assert follow_live_autonomy is True
        return SimpleNamespace(
            rewritten_prompt="relaunch prompt",
            artifacts_dir=incident_row,
            force_reuse_plan=SimpleNamespace(segment_envs=[None]),
            preview=SimpleNamespace(is_live=False),
            wipe_preview=SimpleNamespace(artifact_dirs=[str(incident_row)]),
        )

    def fake_execute(plan: Any, evidence_files: dict[str, Any]) -> Any:
        assert planned_names == [AGENT_NAME]
        env = plan.force_reuse_plan.segment_envs[0] or {}
        assert PROVENANCE_ENV in env, "replacement must carry ↻ provenance"
        assert "verdict.json" in evidence_files
        assert "error_report.md" in evidence_files
        new_dir = incident_row.parent / "20261009T120500"
        new_dir.mkdir(parents=True, exist_ok=True)
        (new_dir / "agent_meta.json").write_text(
            json.dumps(
                {
                    "name": AGENT_NAME,
                    "auto_restart": {
                        "of_artifacts_dir": str(incident_row),
                        "lineage_root": incident_row.name,
                        "episode_id": EPISODE,
                        "ledger_key": f"sase__{incident_row.name}",
                    },
                }
            ),
            encoding="utf-8",
        )
        launched.append(str(new_dir))
        return SimpleNamespace(
            status="ok", launched_artifacts_dir=str(new_dir), error=None
        )

    outcome = heal_one(
        target,
        classify=lambda assembled: _relaunch_verdict(),
        check_quiescence=lambda: SimpleNamespace(
            ok=True, reason="quiet", quiet_seconds=60.0
        ),
        run_probe=lambda modules, binding_checks=None: SimpleNamespace(
            ok=True, failures=(), detail="clean"
        ),
        plan_restart=fake_plan,
        execute_restart=fake_execute,
    )
    assert outcome.action == "relaunched", outcome.reason_text
    assert outcome.launched_artifacts_dir == launched[0]
    assert outcome.evidence_dir is not None
    assert Path(outcome.evidence_dir, "verdict.json").is_file()
    assert Path(outcome.evidence_dir, "error_report.md").is_file()
    stored = ledger_mod.load_ledger_record(outcome.ledger_key)
    assert stored is not None and stored.record.state == "launched"
    assert stored.record.planned_name == AGENT_NAME

    # Step 5: one episode notification, one information toast, live report.
    from sase.notifications.store import load_notifications

    rows = [
        r
        for r in load_notifications(include_dismissed=True)
        if r.sender == notify.SENDER
        and (r.dedup_key or "").startswith(f"agent-auto-restart:{EPISODE}")
        and not r.dismissed
    ]
    assert len(rows) == 1
    row = rows[0]
    assert row.notes[0] == f"↻ Restarted {AGENT_NAME} after sase update 9fd8a08"
    assert "fail" not in row.notes[0].lower()
    assert "error" not in row.notes[0].lower()

    from sase.ace.tui.actions.agents._toasts import _format_notification_toast

    message, severity = _format_notification_toast(row)
    assert severity == "information"
    assert message == row.notes[0]

    report_path = notify.refresh_episode_report(EPISODE)
    assert report_path is not None and report_path.is_file()
    from sase.chops import validate_chop_report

    document = json.loads(report_path.read_text(encoding="utf-8"))
    validate_chop_report(document)
    rows_block = next(b for b in document["blocks"] if b.get("kind") == "rows")
    now_by_agent = {r["cells"][0]: r["cells"][5] for r in rows_block["rows"]}
    assert now_by_agent[AGENT_NAME] == "RUNNING"
    # The replacement settles: the Now column follows without a new row.
    Path(launched[0], "done.json").write_text(
        json.dumps({"outcome": "completed"}), encoding="utf-8"
    )
    notify.refresh_episode_report(EPISODE)
    document = json.loads(report_path.read_text(encoding="utf-8"))
    rows_block = next(b for b in document["blocks"] if b.get("kind") == "rows")
    now_by_agent = {r["cells"][0]: r["cells"][5] for r in rows_block["rows"]}
    assert now_by_agent[AGENT_NAME] == "DONE"

    # Step 6: the replacement breaks again with the same skew error. The job
    # settles its record, the healer declines it without relaunching, and the
    # loud not-retrying copy names the episode.
    replacement = Path(launched[0])
    (replacement / "done.json").write_text(
        json.dumps({"outcome": "failed", "error": INCIDENT_ERROR}),
        encoding="utf-8",
    )
    (replacement / "error_report.md").write_text(
        f"# {INCIDENT_ERROR}\n\nBroke again after the automatic restart.\n",
        encoding="utf-8",
    )
    replacement_target = HealerTarget(
        artifacts_dir=replacement, project="sase", agent_name=AGENT_NAME
    )
    with (
        patch("sase.procs.store.read_procs", return_value=[]),
        patch.object(
            sweep_mod,
            "_submit_healer_proc",
            lambda *, count: submissions.append(count) or True,
        ),
    ):
        settled_tick = sweep_mod.run_job_tick()
    assert settled_tick.settled >= 1
    again = heal_one(
        replacement_target,
        classify=lambda assembled: _relaunch_verdict(),
        check_quiescence=lambda: SimpleNamespace(
            ok=True, reason="quiet", quiet_seconds=60.0
        ),
        run_probe=lambda modules, binding_checks=None: SimpleNamespace(
            ok=True, failures=(), detail="clean"
        ),
        plan_restart=fake_plan,
        execute_restart=fake_execute,
    )
    assert again.action == "declined", again.reason_text
    assert len(launched) == 1, "a re-broken replacement is never relaunched"
    settled = ledger_mod.load_ledger_record(outcome.ledger_key)
    assert settled is not None and settled.record.state == "settled_failed"

    healer_common.escalate_healer(
        replacement_target,
        "replacement broke again with the same skew error",
        episode_id=EPISODE,
        kind="already_restarted",
    )
    surfaced = [
        r
        for r in load_notifications(include_dismissed=True)
        if r.sender == "user-agent" and AGENT_NAME in (r.notes[0] if r.notes else "")
    ]
    assert surfaced, "the re-broken replacement must be re-surfaced loudly"
    assert any(
        "This was its automatic restart" in (note or "")
        and "9fd8a08" in (note or "")
        and "sase@" not in (note or "")
        for r in surfaced
        for note in r.notes
    )
