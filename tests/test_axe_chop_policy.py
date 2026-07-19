"""Declarative chop guards, triggers, checkpoints, and dedupe coverage."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

from sase.axe.chop_policy import (
    ChopPreflight,
    apply_chop_once_per,
    evaluate_chop_preflight,
    finalize_pending_chop_checkpoints,
    record_chop_checkpoint_event,
)
from sase.axe.chop_inventory import collect_chop_inventory
from sase.axe.chop_proposals import prepare_chop_proposals
from sase.axe.chop_runner import run_configured_chop_once
from sase.axe.config import AxeConfig, ChopConfig, LumberjackConfig
from sase.axe.state import read_chop_run
from sase.core.project_lifecycle_wire import ProjectRecordWire

from tests.axe_chop_runner_helpers import make_script

pytest_plugins = ["tests.axe_chop_runner_fixtures"]


def _context_with_changespecs(
    tmp_path: Path,
    rows: list[dict[str, str]],
) -> Path:
    changespecs = tmp_path / "changespecs.json"
    changespecs.write_text(json.dumps(rows), encoding="utf-8")
    context = tmp_path / "context.json"
    context.write_text(
        json.dumps({"all_changespecs_file": str(changespecs)}),
        encoding="utf-8",
    )
    return context


def _project_record(name: str, workspace: Path) -> ProjectRecordWire:
    return ProjectRecordWire(
        schema_version=3,
        project_name=name,
        project_dir=str(workspace.parent / f"state-{name}"),
        project_file=str(workspace.parent / f"state-{name}" / f"{name}.sase"),
        archive_file=None,
        workspace_dir=str(workspace),
        state="enabled",
        state_explicit=False,
        system_managed=False,
        active_claim_count=0,
        launchable=True,
        display_name=name,
        is_project=True,
        vcs_kind="git",
    )


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _commit(repo: Path, message: str) -> str:
    tracked = repo / "tracked.txt"
    previous = tracked.read_text(encoding="utf-8") if tracked.exists() else ""
    tracked.write_text(previous + message + "\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(
        repo,
        "-c",
        "user.name=SASE Tests",
        "-c",
        "user.email=sase-tests@example.com",
        "commit",
        "-m",
        message,
    )
    return _git(repo, "rev-parse", "HEAD")


def test_changespec_guard_skips_scheduled_run_and_force_bypasses_it(
    temp_state_dir: Path,
    tmp_path: Path,
) -> None:
    marker = tmp_path / "executed"
    make_script(tmp_path, "guarded", f"touch '{marker}'\n")
    context = _context_with_changespecs(
        tmp_path,
        [{"name": "fix_just_rollout", "status": "WIP"}],
    )
    chop = ChopConfig(
        name="guarded",
        description="",
        inhibit_if=[
            {
                "provider": "changespec",
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

    with patch("sase.axe.chop_runner.find_all_changespecs", return_value=[]):
        outcome = run_configured_chop_once(
            lumberjack_name="checks",
            chop=chop,
            axe_config=AxeConfig(chop_script_dirs=[str(tmp_path / "scripts")]),
            source="manual",
        )

    assert outcome.status == "success"


def test_git_commits_since_uses_runner_checkpoint_and_accumulates(
    temp_state_dir: Path,
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    first_head = _commit(repo, "first")
    chop = ChopConfig(
        name="audit",
        description="",
        trigger={
            "provider": "git.commits_since",
            "project": "demo",
            "threshold": 2,
            "checkpoint_policy": "on_observation",
        },
    )

    with patch(
        "sase.axe.chop_policy.list_project_records",
        return_value=[_project_record("demo", repo)],
    ):
        first = evaluate_chop_preflight(
            lumberjack_name="docs",
            chop=chop,
            context_file=None,
            scheduled=True,
        )
        assert first.outcome == "fire"
        assert "no prior checkpoint" in first.reason
        record_chop_checkpoint_event("docs", "audit", first, "observed")

        _commit(repo, "second")
        below = evaluate_chop_preflight(
            lumberjack_name="docs",
            chop=chop,
            context_file=None,
            scheduled=True,
        )
        assert below.outcome == "skip"
        assert "1 commits observed" in below.reason

        latest_head = _commit(repo, "third")
        ready = evaluate_chop_preflight(
            lumberjack_name="docs",
            chop=chop,
            context_file=None,
            scheduled=True,
        )

    assert ready.outcome == "fire"
    assert "2 commits observed" in ready.reason
    assert first.decision is not None
    assert first.decision["checkpoint_cursor"] == first_head
    assert ready.decision is not None
    assert ready.decision["checkpoint_cursor"] == latest_head


def test_on_action_success_checkpoint_commits_only_after_success(
    temp_state_dir: Path,
) -> None:
    preflight = ChopPreflight(
        outcome="fire",
        reason="ready",
        checkpoint_enabled=True,
        decision={
            "checkpoint_key": "git.commits_since:demo",
            "checkpoint_cursor": "abc123",
            "checkpoint_policy": "on_action_success",
        },
    )

    record_chop_checkpoint_event("docs", "audit", preflight, "observed")
    checkpoint_path = (
        temp_state_dir / "lumberjacks" / "docs" / "chops" / "audit" / "checkpoint.json"
    )
    pending = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    entry = pending["entries"]["git.commits_since:demo"]
    assert entry["cursor"] == ""
    assert entry["pending_cursor"] == "abc123"

    assert finalize_pending_chop_checkpoints("docs", "audit", "action_succeeded") == 1
    committed = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    entry = committed["entries"]["git.commits_since:demo"]
    assert entry["cursor"] == "abc123"
    assert entry["pending_cursor"] is None


def test_runner_terminal_success_finalizes_pending_checkpoint(
    temp_state_dir: Path,
    tmp_path: Path,
) -> None:
    make_script(tmp_path, "checkpointed", "echo ok\n")
    preflight = ChopPreflight(
        outcome="fire",
        reason="threshold reached",
        checkpoint_enabled=True,
        decision={
            "checkpoint_key": "git.commits_since:demo",
            "checkpoint_cursor": "def456",
            "checkpoint_policy": "on_action_success",
        },
    )

    with (
        patch("sase.axe.chop_runner.find_all_changespecs", return_value=[]),
        patch(
            "sase.axe.chop_runner_script.evaluate_chop_preflight",
            return_value=preflight,
        ),
    ):
        outcome = run_configured_chop_once(
            lumberjack_name="docs",
            chop=ChopConfig(name="checkpointed", description=""),
            axe_config=AxeConfig(chop_script_dirs=[str(tmp_path / "scripts")]),
            source="scheduled",
        )

    assert outcome.status == "success"
    checkpoint_path = (
        temp_state_dir
        / "lumberjacks"
        / "docs"
        / "chops"
        / "checkpointed"
        / "checkpoint.json"
    )
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert checkpoint["entries"]["git.commits_since:demo"]["cursor"] == "def456"


def test_once_per_relinks_duplicate_head_dependent_to_no_wait(
    temp_state_dir: Path,
) -> None:
    chop = ChopConfig(name="events", description="")
    proposals = prepare_chop_proposals(
        "events",
        {
            "proposed_launches": [
                {
                    "id": "root",
                    "prompt": "Root.",
                    "workspace": "git:sase",
                    "dedupe_key": "event:root",
                },
                {
                    "prompt": "Dependent.",
                    "workspace": "git:sase",
                    "dedupe_key": "event:dependent",
                    "wait_on": "root",
                },
            ]
        },
    )
    first = apply_chop_once_per(
        lumberjack_name="events",
        chop=chop,
        proposals=proposals[:1],
        persist=True,
    )
    assert first.accepted_indices == (0,)

    repeated = apply_chop_once_per(
        lumberjack_name="events",
        chop=chop,
        proposals=proposals,
        persist=True,
    )
    assert repeated.accepted_indices == (1,)
    assert repeated.effective_waits == {1: None}
    assert repeated.decisions[0]["outcome"] == "duplicate"
    assert repeated.decisions[1]["outcome"] == "accept"
    assert repeated.decisions[1]["reason"] == (
        "wait dependency 'root' was deduped; relinked to none"
    )


def test_once_per_relinks_across_mid_chain_duplicate_by_id(
    temp_state_dir: Path,
) -> None:
    chop = ChopConfig(name="events", description="")
    seed = prepare_chop_proposals(
        "events",
        {
            "proposed_launches": [
                {
                    "prompt": "Seed.",
                    "workspace": "git:sase",
                    "dedupe_key": "event:middle",
                }
            ]
        },
    )
    apply_chop_once_per(
        lumberjack_name="events",
        chop=chop,
        proposals=seed,
        persist=True,
    )
    proposals = prepare_chop_proposals(
        "events",
        {
            "proposed_launches": [
                {"id": "root", "prompt": "Root.", "workspace": "git:sase"},
                {
                    "id": "middle",
                    "prompt": "Middle.",
                    "workspace": "git:sase",
                    "dedupe_key": "event:middle",
                    "wait_on": "root",
                },
                {
                    "prompt": "Leaf.",
                    "workspace": "git:sase",
                    "dedupe_key": "event:leaf",
                    "wait_on": "middle",
                },
            ]
        },
    )

    outcome = apply_chop_once_per(
        lumberjack_name="events",
        chop=chop,
        proposals=proposals,
        persist=True,
    )

    assert outcome.accepted_indices == (0, 2)
    assert outcome.effective_waits == {0: None, 2: "root"}
    assert outcome.decisions[1]["outcome"] == "duplicate"
    assert outcome.decisions[2]["reason"] == (
        "wait dependency 'middle' was deduped; relinked to 'root'"
    )


def test_once_per_relinks_across_consecutive_duplicates_by_index(
    temp_state_dir: Path,
) -> None:
    chop = ChopConfig(name="events", description="")
    seed = prepare_chop_proposals(
        "events",
        {
            "proposed_launches": [
                {
                    "prompt": "Seed one.",
                    "workspace": "git:sase",
                    "dedupe_key": "event:one",
                },
                {
                    "prompt": "Seed two.",
                    "workspace": "git:sase",
                    "dedupe_key": "event:two",
                },
            ]
        },
    )
    apply_chop_once_per(
        lumberjack_name="events",
        chop=chop,
        proposals=seed,
        persist=True,
    )
    proposals = prepare_chop_proposals(
        "events",
        {
            "proposed_launches": [
                {"prompt": "Root.", "workspace": "git:sase"},
                {
                    "prompt": "Duplicate one.",
                    "workspace": "git:sase",
                    "dedupe_key": "event:one",
                    "wait_on": 0,
                },
                {
                    "prompt": "Duplicate two.",
                    "workspace": "git:sase",
                    "dedupe_key": "event:two",
                    "wait_on": 1,
                },
                {
                    "prompt": "Leaf.",
                    "workspace": "git:sase",
                    "dedupe_key": "event:leaf",
                    "wait_on": 2,
                },
            ]
        },
    )

    outcome = apply_chop_once_per(
        lumberjack_name="events",
        chop=chop,
        proposals=proposals,
        persist=True,
    )

    assert outcome.accepted_indices == (0, 3)
    assert outcome.effective_waits == {0: None, 3: 0}
    assert outcome.decisions[1]["outcome"] == "duplicate"
    assert outcome.decisions[2]["outcome"] == "duplicate"
    assert outcome.decisions[3]["reason"] == (
        "wait dependency 2 was deduped; relinked to 0"
    )


def test_all_duplicate_proposals_record_skipped_run(
    temp_state_dir: Path,
    tmp_path: Path,
) -> None:
    result = {
        "schema_version": 1,
        "status": "ok",
        "proposed_launches": [
            {
                "prompt": "Do it.",
                "workspace": "git:sase",
                "dedupe_key": "event:known",
            }
        ],
    }
    proposals = prepare_chop_proposals("events", result)
    chop = ChopConfig(name="events", description="")
    apply_chop_once_per(
        lumberjack_name="events",
        chop=chop,
        proposals=proposals,
        persist=True,
    )
    payload = json.dumps(result)
    make_script(
        tmp_path,
        "events",
        f"printf '%s' '{payload}' > \"$SASE_CHOP_RESULT_FILE\"\n",
    )

    with (
        patch("sase.axe.chop_runner.find_all_changespecs", return_value=[]),
        patch("sase.axe.chop_runner.launch_agent_from_cwd") as launch,
    ):
        outcome = run_configured_chop_once(
            lumberjack_name="events",
            chop=chop,
            axe_config=AxeConfig(chop_script_dirs=[str(tmp_path / "scripts")]),
            source="manual",
        )

    launch.assert_not_called()
    assert outcome.status == "skipped"
    assert outcome.run_id is not None
    entry = read_chop_run("events", "events", outcome.run_id)
    assert entry is not None
    assert entry.status == "skipped"
    assert entry.reason is not None and "once-per" in entry.reason
    assert entry.proposals[0]["validation"] == "duplicate"
