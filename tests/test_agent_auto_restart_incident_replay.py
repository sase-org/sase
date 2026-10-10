"""End-to-end replay of the 2026-10-09 update-skew incident (land acceptance).

Every step after fixture setup runs through real code: the runner doorbell
and silent notification, the scheduler tick, the healer with the real
classifier, settlement of the live report, and the replacement's
already-restarted escalation. Fake only quiescence, the probe subprocess,
and plan/execute.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import sase.agent.auto_restart.notify as notify
from sase.agent.auto_restart.healer import HealerTarget, heal_one
from sase.agent.auto_restart.provenance import PROVENANCE_ENV
from sase.axe.run_agent_runner import _silence_notification_for_pending_recovery
from sase.axe.run_agent_runner_errors import RunnerErrorContext, record_runner_error
from sase.axe.run_agent_runner_finalize import (
    send_completion_notification,
    write_error_done_marker,
)
from sase.axe.run_agent_runner_state import RunnerRunState
from sase.agent.status_buckets import UPDATE_RECOVERY_GLYPH
from sase.axe.runner_lifecycle_phase import mark_lifecycle_phase
from sase.notifications.store import load_notifications

AGENT_NAME = "research.46.final"
BOOT_REV = "9c5000f2dbb126962ea0a84856d0a49115450dc7"
UPDATE_REV = "9fd8a081f45689655249b7bf6ed7b561de65b8bf"
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


def _incident_import_error() -> BaseException:
    try:
        raise ImportError(
            "cannot import name 'auto_launch_prefix' from "
            "'sase.monitor.continuation_delivery'",
            name="sase.monitor.continuation_delivery",
        )
    except ImportError as exc:
        return exc
    raise AssertionError("unreachable")


def _kills() -> Any:
    return SimpleNamespace(labels=MagicMock(return_value=MagicMock()))


def _ok_quiescence() -> SimpleNamespace:
    return SimpleNamespace(ok=True, reason="quiet", quiet_seconds=60.0)


def _ok_probe(
    modules: list[str], binding_checks: list[tuple[str, str]] | None = None
) -> SimpleNamespace:
    _ = modules, binding_checks
    return SimpleNamespace(ok=True, failures=(), detail="clean")


def _runner_state(artifacts: Path, log_path: Path) -> RunnerRunState:
    return RunnerRunState(
        cl_name="cl",
        project_file="/tmp/project.sase",
        prompt_file="/tmp/prompt.md",
        output_path=str(log_path),
        workflow_name="research",
        timestamp="20261009_120400",
        update_target="",
        is_home_mode=False,
        workspace_dir=str(artifacts / "workspace"),
        workspace_num=1,
        project_name="sase",
        artifacts_timestamp=artifacts.name,
        artifacts_dir=str(artifacts),
        agent_name=AGENT_NAME,
        agent_model="model",
        agent_llm_provider="provider",
        auto_restart_enabled=True,
        success=False,
        error_summary=INCIDENT_ERROR,
    )


def _error_context(state: RunnerRunState) -> RunnerErrorContext:
    return state.error_context()


def _episode_rows(episode_id: str) -> list[Any]:
    return [
        row
        for row in load_notifications(include_dismissed=True)
        if row.sender == notify.SENDER
        and (row.dedup_key or "").startswith(f"agent-auto-restart:{episode_id}")
        and not row.dismissed
    ]


def _now_by_agent(document: dict[str, Any]) -> dict[str, str]:
    rows_block = next(
        block for block in document["blocks"] if block.get("kind") == "rows"
    )
    return {row["cells"][0]: row["cells"][5] for row in rows_block["rows"]}


def test_incident_replay_end_to_end(
    tmp_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = tmp_home
    from sase.ace.tui.actions.agents._toasts import format_batch_toasts
    from sase.agent.auto_restart import ledger as ledger_mod
    from sase.agent.auto_restart import sweep as sweep_mod
    from sase.agent.auto_restart.managed_roots import current_code_identity
    from sase.chops import validate_chop_report

    artifacts = tmp_path / "artifacts" / "ace-run" / "20261009T120400"
    artifacts.mkdir(parents=True)
    identity = current_code_identity()
    roots = [dict(root) for root in identity.get("roots", [])]
    sase_root = next(root for root in roots if root.get("name") == "sase")
    sase_root["commit"] = BOOT_REV
    (artifacts / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": AGENT_NAME,
                "booted_at": "2026-10-09T11:55:00+00:00",
                "lifecycle_phase": "waiting",
                "code_identity": {**identity, "roots": roots},
            }
        ),
        encoding="utf-8",
    )
    (artifacts / "waiting.json").write_text(
        json.dumps({"waiting_for": ["upstream.final"], "reason": "%wait"}),
        encoding="utf-8",
    )
    log_path = artifacts / "runner.log"
    log_path.write_text(
        "Refreshing sase runner code after dependency wait: "
        f"{BOOT_REV} -> {UPDATE_REV}\n",
        encoding="utf-8",
    )
    (artifacts / "error_report.md").write_text(
        f"# {INCIDENT_ERROR}\n\nRefreshing sase runner code after %wait.\n",
        encoding="utf-8",
    )
    mark_lifecycle_phase(str(artifacts), "waiting")

    state = _runner_state(artifacts, log_path)
    record_runner_error(
        _incident_import_error(),
        context=_error_context(state),
        write_error_done_marker=write_error_done_marker,
        agent_kills=_kills(),
        message_prefix="Error running agent",
        auto_restart_enabled=True,
        killed=False,
    )
    _silence_notification_for_pending_recovery(state)
    assert state.force_silent_notification is True
    send_completion_notification(
        cl_name=state.cl_name,
        artifacts_timestamp=state.artifacts_timestamp,
        workflow_name=state.workflow_name,
        success=False,
        agent_hidden=state.force_silent_notification,
        agent_name=state.agent_name,
        agent_model=state.agent_model,
        agent_llm_provider=state.agent_llm_provider,
        error_summary=state.error_summary,
        error_report_path=str(artifacts / "error_report.md"),
        saved_path=None,
        diff_path=None,
        current_artifacts_dir=str(artifacts),
        output_path=state.output_path,
        step_output=None,
        prompt="",
    )

    done = json.loads((artifacts / "done.json").read_text(encoding="utf-8"))
    assert done["recovery"]["state"] == "pending"
    assert done["failure_facts"]["skew_suspect"] is True
    assert done["failure_facts"]["lifecycle_phase"] == "waiting"
    assert (
        done["failure_facts"]["import_error"]["missing_symbol"] == "auto_launch_prefix"
    )
    assert ledger_mod.list_doorbells(), "the dying runner must ring the doorbell"
    silent_failures = [
        row
        for row in load_notifications(include_dismissed=True)
        if row.sender == "user-agent" and row.silent
    ]
    assert silent_failures, "the runner must silence the original failure notice"

    target = HealerTarget(
        artifacts_dir=artifacts, project="sase", agent_name=AGENT_NAME
    )
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

    launched: list[str] = []
    planned_names: list[str] = []

    def fake_plan(name: str, *, follow_live_autonomy: bool = True) -> Any:
        planned_names.append(name)
        assert follow_live_autonomy is True
        return SimpleNamespace(
            rewritten_prompt="relaunch prompt",
            artifacts_dir=artifacts,
            force_reuse_plan=SimpleNamespace(segment_envs=[None]),
            preview=SimpleNamespace(is_live=False),
            wipe_preview=SimpleNamespace(artifact_dirs=[str(artifacts)]),
        )

    def fake_execute(plan: Any, evidence_files: dict[str, Any]) -> Any:
        assert planned_names == [AGENT_NAME]
        env = plan.force_reuse_plan.segment_envs[0] or {}
        assert PROVENANCE_ENV in env, "replacement must carry ↻ provenance"
        provenance = json.loads(env[PROVENANCE_ENV])
        assert provenance["from_rev"] == BOOT_REV
        assert provenance["to_rev"] == UPDATE_REV
        assert "verdict.json" in evidence_files
        assert "error_report.md" in evidence_files
        new_dir = artifacts.parent / "20261009T120500"
        new_dir.mkdir(parents=True, exist_ok=True)
        (new_dir / "agent_meta.json").write_text(
            json.dumps(
                {
                    "name": AGENT_NAME,
                    "auto_restart": {
                        "of_artifacts_dir": str(artifacts),
                        "lineage_root": artifacts.name,
                        "episode_id": provenance.get("episode_id"),
                        "ledger_key": provenance.get("ledger_key"),
                    },
                }
            ),
            encoding="utf-8",
        )
        (new_dir / "error_report.md").write_text(
            f"# {INCIDENT_ERROR}\n\nBroke again after the automatic restart.\n",
            encoding="utf-8",
        )
        launched.append(str(new_dir))
        return SimpleNamespace(
            status="ok", launched_artifacts_dir=str(new_dir), error=None
        )

    outcome = heal_one(
        target,
        check_quiescence=_ok_quiescence,
        run_probe=_ok_probe,
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
    episode_id = stored.record.episode_id
    assert isinstance(episode_id, str) and episode_id
    assert "unknown" not in episode_id

    rows = _episode_rows(episode_id)
    assert len(rows) == 1
    title = rows[0].notes[0]
    assert UPDATE_RECOVERY_GLYPH in title
    assert AGENT_NAME in title
    assert "sase@" not in title
    assert "unknown" not in title.lower()
    assert "fail" not in title.lower()
    assert "error" not in title.lower()
    assert UPDATE_REV[:7] in title
    all_rows = load_notifications(include_dismissed=True)
    assert len(all_rows) == 2, "one episode row and one silent failure notice"
    toastable = [
        row for row in all_rows if (not row.silent and not row.muted and not row.read)
    ]
    toasts = format_batch_toasts(toastable)
    assert len(toasts) == 1
    assert toasts[0][1] == "information"

    report_path = Path(rows[0].action_data["report_path"])
    assert report_path.is_file()
    document = json.loads(report_path.read_text(encoding="utf-8"))
    validate_chop_report(document)
    assert _now_by_agent(document)[AGENT_NAME] == "RUNNING"

    replacement = Path(launched[0])
    (replacement / "done.json").write_text(
        json.dumps({"outcome": "failed", "error": INCIDENT_ERROR}), encoding="utf-8"
    )
    replacement_target = HealerTarget(
        artifacts_dir=replacement, project="sase", agent_name=AGENT_NAME
    )
    again = heal_one(
        replacement_target,
        check_quiescence=_ok_quiescence,
        run_probe=_ok_probe,
        plan_restart=fake_plan,
        execute_restart=fake_execute,
    )
    assert again.action == "declined", again.reason_text
    assert again.reason == "already_restarted"
    assert len(launched) == 1, "a re-broken replacement is never relaunched"
    settled = ledger_mod.load_ledger_record(outcome.ledger_key)
    assert settled is not None
    assert settled.record.state == "settled_failed"
    recovery = json.loads((replacement / "done.json").read_text(encoding="utf-8"))[
        "recovery"
    ]
    assert recovery["state"] == "declined"
    assert recovery["reason"] == "already_restarted"
    surfaced = [
        row
        for row in load_notifications(include_dismissed=True)
        if row.sender == "user-agent"
        and AGENT_NAME in (row.notes[0] if row.notes else "")
        and not row.silent
    ]
    assert surfaced, "the re-broken replacement must be re-surfaced loudly"
    assert any(
        "This was its automatic restart" in (note or "")
        and UPDATE_REV[:7] in (note or "")
        and "sase@" not in (note or "")
        for row in surfaced
        for note in row.notes
    )
