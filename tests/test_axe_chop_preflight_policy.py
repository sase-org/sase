"""Declarative chop preflight guard and trigger coverage."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sase.agent.running_listing import _running_from_snapshot
from sase.axe.chop_inventory import collect_chop_inventory
from sase.axe.chop_policy import (
    ChopPreflight,
    _agent_snapshots,
    evaluate_chop_preflight,
)
from sase.axe.chop_runner import run_configured_chop_once
from sase.axe.config import AxeConfig, ChopConfig, LumberjackConfig
from sase.axe.state import ChopRunEntry, read_chop_run, write_chop_run
from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanStatsWire,
    AgentArtifactScanWire,
    AgentMetaWire,
    PendingQuestionMarkerWire,
)
from sase.core.runner_slots import running_agent_slot_count

from tests.axe_chop_runner_helpers import make_script

pytest_plugins = ["tests.axe_chop_runner_fixtures"]


def _context_with_patches(
    tmp_path: Path,
    rows: list[dict[str, str]],
) -> Path:
    patches = tmp_path / "patches.json"
    patches.write_text(json.dumps(rows), encoding="utf-8")
    context = tmp_path / "context.json"
    context.write_text(
        json.dumps({"all_patches_file": str(patches)}),
        encoding="utf-8",
    )
    return context


def _agent_record(
    tmp_path: Path,
    timestamp: str,
    name: str,
    *,
    run_started: bool = False,
    parent_timestamp: str | None = None,
    agent_family: str | None = None,
    agent_family_parallel: bool = False,
    pending_question: bool = False,
    done: bool = False,
) -> AgentArtifactRecordWire:
    return AgentArtifactRecordWire(
        project_name="proj",
        project_dir=str(tmp_path / "proj"),
        project_file=str(tmp_path / "proj" / "proj.sase"),
        workflow_dir_name="ace-run",
        artifact_dir=str(tmp_path / "proj" / "artifacts" / "ace-run" / timestamp),
        timestamp=timestamp,
        agent_meta=AgentMetaWire(
            name=name,
            pid=100,
            parent_timestamp=parent_timestamp,
            agent_family=agent_family,
            agent_family_parallel=agent_family_parallel,
            run_started_at=("2026-08-12T12:00:00-04:00" if run_started else None),
        ),
        pending_question=(
            PendingQuestionMarkerWire(session_id="question")
            if pending_question
            else None
        ),
        has_done_marker=done,
    )


def _agent_snapshot(
    tmp_path: Path,
    records: list[AgentArtifactRecordWire],
) -> AgentArtifactScanWire:
    return AgentArtifactScanWire(
        schema_version=1,
        projects_root=str(tmp_path),
        options=AgentArtifactScanOptionsWire(),
        stats=AgentArtifactScanStatsWire(),
        records=records,
    )


def test_patch_guard_skips_scheduled_run_and_force_bypasses_it(
    temp_state_dir: Path,
    tmp_path: Path,
) -> None:
    marker = tmp_path / "executed"
    make_script(tmp_path, "guarded", f"touch '{marker}'\n")
    context = _context_with_patches(
        tmp_path,
        [{"name": "fix_just_rollout", "status": "WIP"}],
    )
    chop = ChopConfig(
        name="guarded",
        description="",
        inhibit_if=[
            {
                "provider": "patch",
                "name_prefix": "fix_just",
                "statuses": ["WIP"],
            }
        ],
    )
    config = AxeConfig(chop_script_dirs=[str(tmp_path / "scripts")])

    skipped = run_configured_chop_once(
        lumberjack_name="checks",
        chop=chop,
        axe_config=config,
        context_file=str(context),
        source="scheduled",
    )

    assert skipped.status == "skipped"
    assert skipped.skip_reason == "inhibited"
    assert skipped.reason is not None and "fix_just_rollout" in skipped.reason
    assert marker.exists() is False
    assert skipped.run_id is not None
    entry = read_chop_run("checks", "guarded", skipped.run_id)
    assert entry is not None
    assert entry.status == "skipped"
    assert entry.reason == skipped.reason
    inventory = collect_chop_inventory(
        AxeConfig(
            chop_script_dirs=config.chop_script_dirs,
            lumberjacks={
                "checks": LumberjackConfig(
                    name="checks",
                    description="Run preflight policy checks",
                    interval=60,
                    chops=[chop],
                )
            },
        )
    )
    assert inventory.configured_chops[0].latest_run_reason == skipped.reason

    forced = run_configured_chop_once(
        lumberjack_name="checks",
        chop=chop,
        axe_config=config,
        context_file=str(context),
        source="manual",
        force=True,
    )
    assert forced.status == "success"
    assert marker.exists()


def test_agent_runners_guard_skips_scheduled_run_and_records_reason(
    temp_state_dir: Path,
    tmp_path: Path,
) -> None:
    marker = tmp_path / "executed"
    make_script(tmp_path, "idle_only", f"touch '{marker}'\n")
    chop = ChopConfig(
        name="idle_only",
        description="",
        inhibit_if=[{"provider": "agent_runners", "max": 0}],
    )
    config = AxeConfig(chop_script_dirs=[str(tmp_path / "scripts")])
    active = SimpleNamespace(
        name="slot.user.agent",
        status="RUNNING",
        agent_clan=None,
        holds_runner_slot=True,
    )

    with patch("sase.axe.chop_policy.list_running_agents", return_value=[active]):
        skipped = run_configured_chop_once(
            lumberjack_name="checks",
            chop=chop,
            axe_config=config,
            source="scheduled",
        )

    assert skipped.status == "skipped"
    assert skipped.reason is not None
    assert skipped.reason == (
        "inhibited by 1 agent holding runner slots (e.g. `slot.user.agent`); max is 0"
    )
    assert marker.exists() is False
    assert skipped.run_id is not None
    entry = read_chop_run("checks", "idle_only", skipped.run_id)
    assert entry is not None
    assert entry.reason == skipped.reason


def test_agent_runners_guard_fires_at_or_below_max_and_force_bypasses(
    temp_state_dir: Path,
) -> None:
    slot_holder = SimpleNamespace(
        name="slot.user.agent",
        status="RUNNING",
        agent_clan=None,
        holds_runner_slot=True,
    )
    parked = SimpleNamespace(
        name="question.user.agent",
        status="QUESTION",
        agent_clan=None,
        holds_runner_slot=False,
    )

    with patch("sase.axe.chop_policy.list_running_agents", return_value=[parked]):
        below_max = evaluate_chop_preflight(
            lumberjack_name="checks",
            chop=ChopConfig(
                name="idle_only",
                description="",
                inhibit_if=[{"provider": "agent_runners", "max": 0}],
            ),
            context_file=None,
            scheduled=True,
        )

    with patch("sase.axe.chop_policy.list_running_agents", return_value=[slot_holder]):
        at_max = evaluate_chop_preflight(
            lumberjack_name="checks",
            chop=ChopConfig(
                name="idle_only",
                description="",
                inhibit_if=[{"provider": "agent_runners", "max": 1}],
            ),
            context_file=None,
            scheduled=True,
        )
        forced = evaluate_chop_preflight(
            lumberjack_name="checks",
            chop=ChopConfig(
                name="idle_only",
                description="",
                inhibit_if=[{"provider": "agent_runners", "max": 0}],
            ),
            context_file=None,
            scheduled=False,
            force=True,
        )

    assert below_max.outcome == "fire"
    assert at_max.outcome == "fire"
    assert forced.outcome == "fire"


def test_agent_snapshots_only_emit_runner_slot_for_agent_runners_guard() -> None:
    active = SimpleNamespace(
        name="slot.user.agent",
        status="RUNNING",
        agent_clan="audit",
        holds_runner_slot=True,
    )

    with patch("sase.axe.chop_policy.list_running_agents", return_value=[active]):
        clan_rows = _agent_snapshots([{"provider": "agent_clan"}])
        runner_rows = _agent_snapshots([{"provider": "agent_runners"}])

    assert "holds_runner_slot" not in clan_rows[0]
    assert runner_rows[0]["holds_runner_slot"] is True


def test_agent_runner_snapshot_count_matches_admission_count(
    temp_state_dir: Path,
    tmp_path: Path,
) -> None:
    root_timestamp = "20260812120000"
    records = [
        _agent_record(
            tmp_path, root_timestamp, "root", run_started=True, agent_family="root"
        ),
        _agent_record(
            tmp_path,
            "20260812120001",
            "parallel",
            run_started=True,
            parent_timestamp=root_timestamp,
            agent_family="root",
            agent_family_parallel=True,
        ),
        _agent_record(
            tmp_path,
            "20260812120002",
            "serial",
            run_started=True,
            parent_timestamp=root_timestamp,
            agent_family="root",
        ),
        _agent_record(
            tmp_path,
            "20260812120003",
            "question",
            run_started=True,
            pending_question=True,
        ),
        _agent_record(tmp_path, "20260812120004", "starting"),
        _agent_record(tmp_path, "20260812120005", "done", run_started=True, done=True),
    ]
    with patch("sase.agent.running_listing.is_process_alive", return_value=True):
        listed = _running_from_snapshot(_agent_snapshot(tmp_path, records))

    with patch("sase.axe.chop_policy.list_running_agents", return_value=listed):
        rows = _agent_snapshots([{"provider": "agent_runners"}])

    assert sum(bool(row["holds_runner_slot"]) for row in rows) == (
        running_agent_slot_count(records, lambda _record: True)
    )


def test_agent_clan_guard_uses_canonical_active_metadata_and_force_bypasses(
    temp_state_dir: Path,
) -> None:
    chop = ChopConfig(
        name="split",
        description="",
        inhibit_if=[{"provider": "agent_clan", "name_prefix": "toobig-"}],
    )
    active = SimpleNamespace(
        name="ordinary.hood.member",
        status="WAITING",
        agent_clan="toobig-3",
    )

    with patch("sase.axe.chop_policy.list_running_agents", return_value=[active]):
        skipped = evaluate_chop_preflight(
            lumberjack_name="checks",
            chop=chop,
            context_file=None,
            scheduled=False,
        )
        forced = evaluate_chop_preflight(
            lumberjack_name="checks",
            chop=chop,
            context_file=None,
            scheduled=False,
            force=True,
        )

    assert skipped.outcome == "skip"
    assert "toobig-3" in skipped.reason
    assert "ordinary.hood.member" in skipped.reason
    assert skipped.decision is not None
    assert skipped.decision["provider"] == "agent_clan"
    assert forced.outcome == "fire"


def test_active_clan_guard_precedes_launched_run_dedupe_and_force_bypasses(
    temp_state_dir: Path,
    tmp_path: Path,
) -> None:
    marker = tmp_path / "executed"
    make_script(tmp_path, "split", f"touch '{marker}'\n")
    context = tmp_path / "context.json"
    context.write_text("{}", encoding="utf-8")
    chop = ChopConfig(
        name="split",
        description="",
        inhibit_if=[{"provider": "agent_clan", "name_prefix": "toobig-"}],
    )
    config = AxeConfig(chop_script_dirs=[str(tmp_path / "scripts")])
    active = SimpleNamespace(
        name="toobig-3.split_file.module",
        status="WAITING",
        agent_clan="toobig-3",
    )

    def _record_launched(run_id: str) -> None:
        write_chop_run(
            ChopRunEntry(
                run_id=run_id,
                lumberjack_name="checks",
                chop_name="split",
                started_at="2026-07-19T12:00:00+00:00",
                finished_at=None,
                duration_ms=0,
                status="launched",
                launches=[{"pid": 321, "agent_name": active.name}],
            )
        )

    _record_launched("20260719T120000_000000")
    with (
        patch(
            "sase.axe.chop_runner_script.finalize_launched_chop_runs",
            return_value=0,
        ),
        patch("sase.axe.chop_policy.list_running_agents", return_value=[active]),
    ):
        skipped = run_configured_chop_once(
            lumberjack_name="checks",
            chop=chop,
            axe_config=config,
            context_file=str(context),
            source="manual",
        )

        assert skipped.status == "skipped"
        assert skipped.reason is not None and "toobig-3" in skipped.reason
        assert active.name in skipped.reason
        assert marker.exists() is False

        # Put an active launched row back at the head so this also proves that
        # force bypasses action-level dedupe, not only the clan policy.
        _record_launched("20260719T120001_000000")
        forced = run_configured_chop_once(
            lumberjack_name="checks",
            chop=chop,
            axe_config=config,
            context_file=str(context),
            source="manual",
            force=True,
        )

    assert forced.status == "success"
    assert marker.exists()


def test_agent_clan_guard_does_not_infer_clan_from_dotted_name(
    temp_state_dir: Path,
) -> None:
    chop = ChopConfig(
        name="split",
        description="",
        inhibit_if=[{"provider": "agent_clan", "name_prefix": "toobig-"}],
    )
    active = SimpleNamespace(
        name="toobig-3.split_file.module",
        status="RUNNING",
        agent_clan=None,
    )

    with patch("sase.axe.chop_policy.list_running_agents", return_value=[active]):
        decision = evaluate_chop_preflight(
            lumberjack_name="checks",
            chop=chop,
            context_file=None,
            scheduled=False,
        )

    assert decision.outcome == "fire"


def test_manual_run_bypasses_configured_git_trigger(
    temp_state_dir: Path,
    tmp_path: Path,
) -> None:
    make_script(tmp_path, "manual", "echo ran\n")
    chop = ChopConfig(
        name="manual",
        description="",
        trigger={
            "provider": "git.commits_since",
            "project": "does-not-exist",
            "threshold": 100,
            "checkpoint_policy": "on_action_success",
        },
    )

    with patch("sase.axe.chop_runner.find_all_patches", return_value=[]):
        outcome = run_configured_chop_once(
            lumberjack_name="checks",
            chop=chop,
            axe_config=AxeConfig(chop_script_dirs=[str(tmp_path / "scripts")]),
            source="manual",
        )

    assert outcome.status == "success"


def test_guard_skip_does_not_advance_run_every_cadence(
    temp_state_dir: Path,
    tmp_path: Path,
) -> None:
    make_script(tmp_path, "guarded", "echo ran\n")
    chop = ChopConfig(name="guarded", description="", run_every=3600)
    preflight = ChopPreflight(
        outcome="skip",
        reason="inhibited by active agent clan `toobig-3` member `agent.name`",
        decision={"provider": "agent_clan"},
    )

    with patch(
        "sase.axe.chop_runner_script.evaluate_chop_preflight",
        return_value=preflight,
    ):
        outcome = run_configured_chop_once(
            lumberjack_name="checks",
            chop=chop,
            axe_config=AxeConfig(chop_script_dirs=[str(tmp_path / "scripts")]),
            source="scheduled",
        )

    assert outcome.status == "skipped"
    assert outcome.advances_cadence is False


def test_git_commits_since_trigger_skip_still_advances_run_every_cadence(
    temp_state_dir: Path,
    tmp_path: Path,
) -> None:
    make_script(tmp_path, "audited", "echo ran\n")
    chop = ChopConfig(name="audited", description="", run_every=3600)
    preflight = ChopPreflight(
        outcome="skip",
        reason="1 commits observed for `demo`; threshold is 2",
        decision={"provider": "git.commits_since"},
    )

    with patch(
        "sase.axe.chop_runner_script.evaluate_chop_preflight",
        return_value=preflight,
    ):
        outcome = run_configured_chop_once(
            lumberjack_name="checks",
            chop=chop,
            axe_config=AxeConfig(chop_script_dirs=[str(tmp_path / "scripts")]),
            source="scheduled",
        )

    assert outcome.status == "skipped"
    assert outcome.skip_reason == "trigger"
    assert outcome.advances_cadence is True


def test_fs_trigger_skip_still_advances_run_every_cadence(
    temp_state_dir: Path,
    tmp_path: Path,
) -> None:
    make_script(tmp_path, "watched", "echo ran\n")
    chop = ChopConfig(name="watched", description="", run_every=3600)
    preflight = ChopPreflight(
        outcome="skip",
        reason="watched paths unchanged and within max_quiet",
        decision={"provider": "fs"},
    )

    with patch(
        "sase.axe.chop_runner_script.evaluate_chop_preflight",
        return_value=preflight,
    ):
        outcome = run_configured_chop_once(
            lumberjack_name="checks",
            chop=chop,
            axe_config=AxeConfig(chop_script_dirs=[str(tmp_path / "scripts")]),
            source="scheduled",
        )

    assert outcome.status == "skipped"
    assert outcome.skip_reason == "trigger"
    assert outcome.advances_cadence is True
