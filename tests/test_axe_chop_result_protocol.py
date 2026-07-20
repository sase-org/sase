"""Structured chop-result parsing, proposal launch, and lifecycle coverage."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.axe.chop_agents import (
    _record_chop_agent_launch,
    get_chop_agent_records,
)
from sase.axe.chop_lifecycle import _agent_completion, finalize_launched_chop_runs
from sase.axe.chop_policy import apply_chop_once_per
from sase.axe.chop_proposals import (
    plan_chop_proposals,
    prepare_chop_proposals,
    proposal_previews,
)
from sase.axe.chop_runner import run_configured_chop_once
from sase.axe.config import AxeConfig, ChopConfig
from sase.agent.multi_prompt_launcher import MultiPromptPartialLaunchError
from sase.axe.state import (
    ChopRunEntry,
    chop_run_context_path,
    chop_run_log_path,
    chop_run_result_path,
    finish_chop_run,
    read_chop_run,
    start_chop_run,
)
from sase.core.agent_artifact_paths import resolve_agent_artifact_timestamp_path
from sase.core.axe_chop_facade import derive_chop_agent_name

from tests.axe_chop_runner_helpers import make_script

pytest_plugins = ["tests.axe_chop_runner_fixtures"]


def _result_script(tmp_path: Path, name: str, document: dict[str, object]) -> None:
    payload = json.dumps(document)
    make_script(
        tmp_path,
        name,
        f"printf '%s' '{payload}' > \"$SASE_CHOP_RESULT_FILE\"\n",
    )


def _config(tmp_path: Path) -> AxeConfig:
    return AxeConfig(chop_script_dirs=[str(tmp_path / "scripts")])


def test_structured_no_op_is_persisted_with_run_local_context(
    temp_state_dir: Path,
    tmp_path: Path,
) -> None:
    _result_script(
        tmp_path,
        "probe",
        {
            "schema_version": 1,
            "status": "no_op",
            "summary": "nothing changed",
            "counters": {"findings": 0},
        },
    )

    with patch("sase.axe.chop_runner.find_all_changespecs", return_value=[]):
        outcome = run_configured_chop_once(
            lumberjack_name="checks",
            chop=ChopConfig(
                name="probe[sase]",
                base_name="probe",
                description="",
                script="probe",
                target_key="sase",
                target={"name": "sase", "workspace": "gh:sase-org/sase"},
                vars={"prompt": "Update docs"},
            ),
            axe_config=_config(tmp_path),
        )

    assert outcome.status == "no_op"
    assert outcome.result is not None
    assert outcome.result["counters"] == {"findings": 0}
    assert outcome.run_id is not None
    entry = read_chop_run("checks", "probe[sase]", outcome.run_id)
    assert entry is not None
    assert entry.status == "no_op"
    assert entry.result == outcome.result
    assert entry.result_file.endswith(".result.json")
    result_path = chop_run_result_path("checks", "probe[sase]", outcome.run_id)
    context_path = chop_run_context_path("checks", "probe[sase]", outcome.run_id)
    assert result_path.is_file()
    context = json.loads(context_path.read_text(encoding="utf-8"))
    assert context["result_file"] == str(result_path)
    assert context["target"] == {
        "name": "sase",
        "workspace": "gh:sase-org/sase",
    }
    assert context["vars"] == {"prompt": "Update docs"}


def test_invalid_result_fails_closed_as_check_error(
    temp_state_dir: Path,
    tmp_path: Path,
) -> None:
    make_script(
        tmp_path,
        "broken",
        "printf '%s' '{not-json' > \"$SASE_CHOP_RESULT_FILE\"\n",
    )

    with patch("sase.axe.chop_runner.find_all_changespecs", return_value=[]):
        outcome = run_configured_chop_once(
            lumberjack_name="checks",
            chop=ChopConfig(name="broken", description=""),
            axe_config=_config(tmp_path),
        )

    assert outcome.status == "check_error"
    assert outcome.error is not None
    assert "invalid_json" in str(outcome.error)
    assert outcome.run_id is not None
    entry = read_chop_run("checks", "broken", outcome.run_id)
    assert entry is not None
    assert entry.status == "check_error"
    assert entry.error is not None and "invalid_json" in entry.error
    assert entry.result_file.endswith(".result.json")


def test_standalone_workflow_proposal_fails_closed(
    temp_state_dir: Path,
    tmp_path: Path,
) -> None:
    _result_script(
        tmp_path,
        "workflow",
        {
            "schema_version": 1,
            "status": "ok",
            "proposed_launches": [
                {
                    "prompt": "#!retired_workflow\nDo the work.",
                    "workspace": "git:sase",
                }
            ],
        },
    )

    with patch("sase.axe.chop_runner.find_all_changespecs", return_value=[]):
        outcome = run_configured_chop_once(
            lumberjack_name="checks",
            chop=ChopConfig(name="workflow", description=""),
            axe_config=_config(tmp_path),
        )

    assert outcome.status == "check_error"
    assert outcome.error is not None
    assert "workflow_reference_forbidden" in str(outcome.error)


def test_dry_run_previews_scaffolds_and_never_launches(
    temp_state_dir: Path,
    tmp_path: Path,
) -> None:
    _result_script(
        tmp_path,
        "docs",
        {
            "schema_version": 1,
            "status": "ok",
            "summary": "refresh then polish",
            "proposed_launches": [
                {
                    "id": "refresh",
                    "prompt": "Refresh the docs.",
                    "workspace": "gh:sase-org/sase",
                    "model": "codex/gpt-5.6-sol",
                    "env": {"MODE": "refresh"},
                },
                {
                    "prompt": "Polish the result.",
                    "workspace": "gh:sase-org/sase",
                    "wait_on": "refresh",
                },
            ],
        },
    )

    with (
        patch("sase.axe.chop_runner.find_all_changespecs", return_value=[]),
        patch("sase.axe.chop_runner.launch_agent_from_cwd") as launch,
    ):
        outcome = run_configured_chop_once(
            lumberjack_name="docs",
            chop=ChopConfig(name="docs", description=""),
            axe_config=_config(tmp_path),
            dry_run=True,
            chop_verbose=True,
        )

    launch.assert_not_called()
    assert outcome.status == "success"
    assert outcome.dry_run is True
    assert len(outcome.proposals) == 2
    assert outcome.run_id is not None
    first_name = derive_chop_agent_name("docs", run_token=outcome.run_id)
    first_prompt = str(outcome.proposals[0]["prompt"])
    second_prompt = str(outcome.proposals[1]["prompt"])
    assert "#gh:sase-org/sase" in first_prompt
    assert f"%id({first_name}, tribe=chop)" in first_prompt
    assert "%model:codex/gpt-5.6-sol" in first_prompt
    assert f"%wait:{first_name}" in second_prompt


def test_deduped_clan_head_promotes_first_survivor_to_declarer(
    temp_state_dir: Path,
) -> None:
    chop = ChopConfig(name="split", description="")
    prepared = prepare_chop_proposals(
        "split",
        {
            "proposed_launches": [
                {
                    "id": "head",
                    "prompt": "Head.",
                    "workspace": "git:sase",
                    "agent_name": "split_file.head",
                    "clan": "toobig-@",
                    "dedupe_key": "split:head",
                },
                {
                    "prompt": "Tail.",
                    "workspace": "git:sase",
                    "agent_name": "split_file.tail",
                    "clan": "toobig-@",
                    "wait_on": "head",
                },
            ]
        },
    )
    apply_chop_once_per(
        lumberjack_name="split",
        chop=chop,
        proposals=prepared[:1],
        persist=True,
    )
    once_per = apply_chop_once_per(
        lumberjack_name="split",
        chop=chop,
        proposals=prepared,
        persist=False,
    )
    accepted = [
        replace(prepared[index], wait_on=once_per.effective_waits[index])
        for index in once_per.accepted_indices
    ]
    plans = plan_chop_proposals(accepted)
    previews = proposal_previews(
        prepared,
        once_per_decisions=once_per.decisions,
        effective_waits=once_per.effective_waits,
        launch_plans=plans,
    )

    assert previews[0]["validation"] == "duplicate"
    assert previews[0]["clan_role"] == "join"
    assert previews[1]["clan_role"] == "declare"
    assert previews[1]["wait_name"] is None
    assert "%clan(toobig-0, tribe=chop)" in previews[1]["prompt"]


def test_clan_planning_allocates_multiple_templates_after_historical_generation(
    temp_state_dir: Path,
    tmp_path: Path,
) -> None:
    from sase.agent.names import reserve_registered_clan_name

    old_artifacts = tmp_path / "old-clan-member"
    old_artifacts.mkdir()
    reserve_registered_clan_name(
        "toobig-0",
        "old-generation",
        old_artifacts,
        create_only=True,
    )
    prepared = prepare_chop_proposals(
        "split",
        {
            "proposed_launches": [
                {
                    "prompt": "Split.",
                    "workspace": "git:sase",
                    "agent_name": "split_file.new",
                    "clan": "toobig-@",
                },
                {
                    "prompt": "Review.",
                    "workspace": "git:sase",
                    "agent_name": "reviewer",
                    "clan": "review-@",
                },
            ]
        },
    )

    plans = plan_chop_proposals(prepared)

    assert [plan.clan for plan in plans] == ["toobig-1", "review-0"]
    assert [plan.agent_name for plan in plans] == [
        "toobig-1.split_file.new",
        "review-0.reviewer",
    ]
    assert all(plan.declares_clan for plan in plans)


def test_clan_partial_launch_keeps_started_member_recorded(
    temp_state_dir: Path,
    tmp_path: Path,
) -> None:
    _result_script(
        tmp_path,
        "split",
        {
            "schema_version": 1,
            "status": "ok",
            "proposed_launches": [
                {
                    "prompt": "First.",
                    "workspace": "git:sase",
                    "agent_name": "first",
                    "clan": "toobig-@",
                    "dedupe_key": "split:first",
                },
                {
                    "prompt": "Second.",
                    "workspace": "git:sase",
                    "agent_name": "second",
                    "clan": "toobig-@",
                    "dedupe_key": "split:second",
                },
            ],
        },
    )
    started = SimpleNamespace(
        pid=401,
        agent_name="toobig-0.first",
        timestamp="260719_130000",
    )

    def _fail_batch(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise MultiPromptPartialLaunchError(
            [started],
            RuntimeError("second spawn failed"),
        )

    with (
        patch("sase.axe.chop_runner.find_all_changespecs", return_value=[]),
        patch("sase.axe.chop_runner.launch_agents_from_cwd", side_effect=_fail_batch),
    ):
        outcome = run_configured_chop_once(
            lumberjack_name="split",
            chop=ChopConfig(name="split", description=""),
            axe_config=_config(tmp_path),
        )

    assert outcome.status == "action_failed"
    assert [launch["pid"] for launch in outcome.launches] == [401]
    assert outcome.run_id is not None
    entry = read_chop_run("split", "split", outcome.run_id)
    assert entry is not None
    assert entry.status == "launched"
    assert entry.finished_at is None
    assert [launch["pid"] for launch in entry.launches] == [401]


def test_runner_launches_proposals_in_order_with_wait_directive(
    temp_state_dir: Path,
    tmp_path: Path,
) -> None:
    _result_script(
        tmp_path,
        "docs",
        {
            "schema_version": 1,
            "status": "ok",
            "proposed_launches": [
                {
                    "id": "refresh",
                    "prompt": "Refresh.",
                    "workspace": "git:sase",
                    "env": {"MODE": "refresh"},
                },
                {
                    "prompt": "Polish.",
                    "workspace": "git:sase",
                    "wait_on": 0,
                },
            ],
        },
    )
    calls: list[tuple[str, dict[str, str]]] = []

    def _launch(prompt: str, *, extra_env: dict[str, str]) -> SimpleNamespace:
        index = len(calls)
        calls.append((prompt, extra_env))
        return SimpleNamespace(
            pid=100 + index,
            agent_name=f"actual.{index + 1}",
            workspace_num=index + 1,
            workspace_dir=f"/workspace/{index + 1}",
            project_name="sase",
            workflow_name=f"ace(run)-{index}",
            cl_name="sase",
            timestamp=f"260718_12000{index}",
            artifacts_dir=f"/artifacts/{index}",
        )

    with (
        patch("sase.axe.chop_runner.find_all_changespecs", return_value=[]),
        patch("sase.axe.chop_runner.launch_agent_from_cwd", side_effect=_launch),
    ):
        outcome = run_configured_chop_once(
            lumberjack_name="docs",
            chop=ChopConfig(name="docs", description=""),
            axe_config=_config(tmp_path),
        )

    assert outcome.status == "launched"
    assert len(calls) == 2
    assert "%wait:actual.1" in calls[1][0]
    assert calls[0][1]["MODE"] == "refresh"
    assert calls[0][1]["SASE_CHOP_RUN_ID"] == outcome.run_id
    assert calls[1][1]["SASE_CHOP_RUN_ID"] == outcome.run_id
    assert outcome.run_id is not None
    entry = read_chop_run("docs", "docs", outcome.run_id)
    assert entry is not None
    assert entry.status == "launched"
    assert entry.finished_at is None
    assert [launch["pid"] for launch in entry.launches] == [100, 101]


def test_launch_failure_releases_only_unlaunched_once_per_keys(
    temp_state_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    _result_script(
        tmp_path,
        "docs",
        {
            "schema_version": 1,
            "status": "ok",
            "proposed_launches": [
                {
                    "prompt": "Refresh.",
                    "workspace": "git:sase",
                    "dedupe_key": "docs:refresh",
                },
                {
                    "prompt": "Polish.",
                    "workspace": "git:sase",
                    "dedupe_key": "docs:polish",
                },
            ],
        },
    )
    calls = 0

    def _launch(prompt: str, *, extra_env: dict[str, str]) -> SimpleNamespace:
        nonlocal calls
        del prompt, extra_env
        calls += 1
        if calls == 2:
            raise RuntimeError("launcher unavailable")
        return SimpleNamespace(
            pid=100,
            agent_name="actual.refresh",
            timestamp="260718_120000",
        )

    chop = ChopConfig(name="docs", description="")
    with (
        patch("sase.axe.chop_runner.find_all_changespecs", return_value=[]),
        patch("sase.axe.chop_runner.launch_agent_from_cwd", side_effect=_launch),
    ):
        outcome = run_configured_chop_once(
            lumberjack_name="docs",
            chop=chop,
            axe_config=_config(tmp_path),
        )

    assert outcome.status == "action_failed"
    assert outcome.run_id is not None
    entry = read_chop_run("docs", "docs", outcome.run_id)
    assert entry is not None
    assert entry.status == "launched"
    assert entry.finished_at is None
    assert entry.launches == list(outcome.launches)
    assert entry.launches[0]["dedupe_key"] == "docs:refresh"
    assert entry.launches[0]["artifacts_timestamp"] == "20260718120000"

    reproposed = prepare_chop_proposals(
        "docs",
        {
            "proposed_launches": [
                {
                    "prompt": "Refresh.",
                    "workspace": "git:sase",
                    "dedupe_key": "docs:refresh",
                },
                {
                    "prompt": "Polish.",
                    "workspace": "git:sase",
                    "dedupe_key": "docs:polish",
                },
            ]
        },
    )
    once_per = apply_chop_once_per(
        lumberjack_name="docs",
        chop=chop,
        proposals=reproposed,
        persist=False,
    )
    assert once_per.accepted_indices == (1,)
    assert once_per.decisions[0]["outcome"] == "duplicate"
    assert once_per.decisions[1]["outcome"] == "accept"

    _record_agent(outcome.run_id, pid=100, timestamp="260718_120000")
    failed_artifacts = resolve_agent_artifact_timestamp_path(
        "sase", "ace-run", "20260718120000"
    )
    failed_artifacts.mkdir(parents=True)
    (failed_artifacts / "done.json").write_text(
        json.dumps({"outcome": "failed"}), encoding="utf-8"
    )

    assert finalize_launched_chop_runs("docs", ["docs"]) == 1
    finalized = read_chop_run("docs", "docs", outcome.run_id)
    assert finalized is not None
    assert finalized.status == "action_failed"
    assert finalized.error is not None
    assert "proposal launch failed: launcher unavailable" in finalized.error

    retried = apply_chop_once_per(
        lumberjack_name="docs",
        chop=chop,
        proposals=reproposed,
        persist=False,
    )
    assert retried.accepted_indices == (0, 1)


def test_runner_launches_with_wait_relinked_across_duplicate(
    temp_state_dir: Path,
    tmp_path: Path,
) -> None:
    chop = ChopConfig(name="docs", description="")
    seed = prepare_chop_proposals(
        "docs",
        {
            "proposed_launches": [
                {
                    "prompt": "Seed.",
                    "workspace": "git:sase",
                    "dedupe_key": "docs:middle",
                }
            ]
        },
    )
    apply_chop_once_per(
        lumberjack_name="docs",
        chop=chop,
        proposals=seed,
        persist=True,
    )
    _result_script(
        tmp_path,
        "docs",
        {
            "schema_version": 1,
            "status": "ok",
            "proposed_launches": [
                {"id": "root", "prompt": "Root.", "workspace": "git:sase"},
                {
                    "id": "middle",
                    "prompt": "Middle.",
                    "workspace": "git:sase",
                    "dedupe_key": "docs:middle",
                    "wait_on": "root",
                },
                {
                    "prompt": "Tail.",
                    "workspace": "git:sase",
                    "dedupe_key": "docs:tail",
                    "wait_on": "middle",
                },
            ],
        },
    )
    calls: list[str] = []

    def _launch(prompt: str, *, extra_env: dict[str, str]) -> SimpleNamespace:
        del extra_env
        index = len(calls)
        calls.append(prompt)
        return SimpleNamespace(
            pid=200 + index,
            agent_name=f"actual.{index + 1}",
        )

    with (
        patch("sase.axe.chop_runner.find_all_changespecs", return_value=[]),
        patch("sase.axe.chop_runner.launch_agent_from_cwd", side_effect=_launch),
    ):
        outcome = run_configured_chop_once(
            lumberjack_name="docs",
            chop=chop,
            axe_config=_config(tmp_path),
        )

    assert outcome.status == "launched"
    assert len(calls) == 2
    assert "%wait:" not in calls[0]
    assert "%wait:actual.1" in calls[1]
    assert outcome.proposals[1]["validation"] == "duplicate"
    assert outcome.proposals[2]["wait_on"] == "root"
    assert outcome.run_id is not None
    entry = read_chop_run("docs", "docs", outcome.run_id)
    assert entry is not None
    assert [launch["index"] for launch in entry.launches] == [0, 2]
    assert entry.launches[1]["wait_on"] == "root"
    assert entry.launches[1]["wait_name"] == "actual.1"


def test_verbose_flag_reaches_script_environment(
    temp_state_dir: Path,
    tmp_path: Path,
) -> None:
    make_script(tmp_path, "verbose", "printf '%s' \"$SASE_CHOP_VERBOSE\"\n")
    with patch("sase.axe.chop_runner.find_all_changespecs", return_value=[]):
        outcome = run_configured_chop_once(
            lumberjack_name="checks",
            chop=ChopConfig(name="verbose", description=""),
            axe_config=_config(tmp_path),
            chop_verbose=True,
        )
    assert outcome.status == "success"
    assert outcome.run_id is not None
    entry = read_chop_run("checks", "verbose", outcome.run_id)
    assert entry is not None
    assert entry.output_bytes == 1


def _launched_entry(
    run_id: str,
    *,
    pid: int,
    launches: list[dict[str, object]] | None = None,
) -> ChopRunEntry:
    entry = ChopRunEntry(
        run_id=run_id,
        lumberjack_name="docs",
        chop_name="docs",
        started_at="2026-07-18T12:00:00+00:00",
        finished_at=None,
        duration_ms=0,
        status="running",
    )
    start_chop_run(entry)
    finish_chop_run(
        "docs",
        "docs",
        run_id,
        status="launched",
        finished_at=None,
        duration_ms=1,
        exit_code=0,
        agent_pid=pid,
        launches=launches or [{"pid": pid}],
    )
    return entry


def _record_agent(
    run_id: str,
    *,
    pid: int,
    timestamp: str = "260718_120000",
) -> object:
    return _record_chop_agent_launch(
        lumberjack_name="docs",
        chop_name="docs",
        run_id=run_id,
        pid=pid,
        project_file="/projects/sase/sase.sase",
        project_name="sase",
        workspace_num=1,
        workflow_name="ace(run)-260718_120000",
        cl_name="sase",
        timestamp=timestamp,
        prompt="refresh",
    )


def test_lifecycle_finalizes_completed_agents_and_clears_registry(
    temp_state_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    run_id = "20260718T120000_000000"
    _launched_entry(run_id, pid=321)
    _record_agent(run_id, pid=321)
    artifacts = resolve_agent_artifact_timestamp_path(
        "sase", "ace-run", "20260718120000"
    )
    artifacts.mkdir(parents=True)
    (artifacts / "done.json").write_text(
        json.dumps({"outcome": "completed"}), encoding="utf-8"
    )

    assert finalize_launched_chop_runs("docs", ["docs"]) == 1
    entry = read_chop_run("docs", "docs", run_id)
    assert entry is not None
    assert entry.status == "action_succeeded"
    assert get_chop_agent_records("docs", chop_name="docs", run_id=run_id) == []


def test_lifecycle_releases_only_failed_agents_once_per_key(
    temp_state_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    run_id = "20260718T120010_000000"
    chop = ChopConfig(name="docs", description="")
    proposed = prepare_chop_proposals(
        "docs",
        {
            "proposed_launches": [
                {
                    "prompt": "Keep.",
                    "workspace": "git:sase",
                    "dedupe_key": "docs:keep",
                },
                {
                    "prompt": "Retry.",
                    "workspace": "git:sase",
                    "dedupe_key": "docs:retry",
                },
            ]
        },
    )
    seeded = apply_chop_once_per(
        lumberjack_name="docs",
        chop=chop,
        proposals=proposed,
        persist=True,
    )
    assert seeded.accepted_indices == (0, 1)
    _launched_entry(
        run_id,
        pid=321,
        launches=[
            {
                "pid": 999,
                "artifacts_timestamp": "20260718120010",
                "dedupe_key": "docs:keep",
            },
            {
                "pid": 654,
                "artifacts_timestamp": "20260718120011",
                "dedupe_key": "docs:retry",
            },
        ],
    )
    _record_agent(run_id, pid=321, timestamp="260718_120010")
    _record_agent(run_id, pid=654, timestamp="260718_120011")
    succeeded_artifacts = resolve_agent_artifact_timestamp_path(
        "sase", "ace-run", "20260718120010"
    )
    succeeded_artifacts.mkdir(parents=True)
    (succeeded_artifacts / "done.json").write_text(
        json.dumps({"outcome": "completed"}), encoding="utf-8"
    )
    failed_artifacts = resolve_agent_artifact_timestamp_path(
        "sase", "ace-run", "20260718120011"
    )
    failed_artifacts.mkdir(parents=True)
    (failed_artifacts / "done.json").write_text(
        json.dumps({"outcome": "failed"}), encoding="utf-8"
    )

    assert finalize_launched_chop_runs("docs", ["docs"]) == 1
    entry = read_chop_run("docs", "docs", run_id)
    assert entry is not None
    assert entry.status == "action_failed"

    once_per = apply_chop_once_per(
        lumberjack_name="docs",
        chop=chop,
        proposals=proposed,
        persist=False,
    )
    assert once_per.accepted_indices == (1,)
    assert once_per.decisions[0]["outcome"] == "duplicate"
    assert once_per.decisions[1]["outcome"] == "accept"


def test_lifecycle_logs_once_per_release_failure_and_still_finalizes(
    temp_state_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    run_id = "20260718T120012_000000"
    _launched_entry(
        run_id,
        pid=765,
        launches=[
            {
                "pid": 765,
                "artifacts_timestamp": "20260718120012",
                "dedupe_key": "docs:retry",
            }
        ],
    )
    _record_agent(run_id, pid=765, timestamp="260718_120012")
    artifacts = resolve_agent_artifact_timestamp_path(
        "sase", "ace-run", "20260718120012"
    )
    artifacts.mkdir(parents=True)
    (artifacts / "done.json").write_text(
        json.dumps({"outcome": "failed"}), encoding="utf-8"
    )

    with patch(
        "sase.axe.chop_lifecycle.release_chop_once_per_keys",
        side_effect=OSError("seen store unavailable"),
    ):
        assert finalize_launched_chop_runs("docs", ["docs"]) == 1

    entry = read_chop_run("docs", "docs", run_id)
    assert entry is not None
    assert entry.status == "action_failed"
    output = chop_run_log_path("docs", "docs", run_id).read_text(encoding="utf-8")
    assert "Failed to release once-per keys" in output
    assert "seen store unavailable" in output


def test_lifecycle_does_not_release_keys_for_incomplete_launch_linkage(
    temp_state_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    run_id = "20260718T120013_000000"
    _launched_entry(
        run_id,
        pid=321,
        launches=[
            {"pid": 321, "dedupe_key": "docs:first"},
            {"pid": 654, "dedupe_key": "docs:missing"},
        ],
    )
    _record_agent(run_id, pid=321)

    with patch("sase.axe.chop_lifecycle.release_chop_once_per_keys") as release:
        assert finalize_launched_chop_runs("docs", ["docs"]) == 1

    release.assert_not_called()
    entry = read_chop_run("docs", "docs", run_id)
    assert entry is not None
    assert entry.status == "action_failed"
    assert entry.error is not None and "linkage incomplete" in entry.error


def test_lifecycle_fails_dead_agent_without_done_marker(
    temp_state_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    run_id = "20260718T120001_000000"
    _launched_entry(run_id, pid=654)
    _record_agent(run_id, pid=654)

    with (
        patch("sase.axe.chop_lifecycle.is_process_running", return_value=False),
        patch("sase.axe.chop_lifecycle.release_chop_once_per_keys") as release,
    ):
        assert finalize_launched_chop_runs("docs", ["docs"]) == 1
    release.assert_not_called()
    entry = read_chop_run("docs", "docs", run_id)
    assert entry is not None
    assert entry.status == "action_failed"
    assert entry.error is not None and "without completion artifact" in entry.error


def test_lifecycle_uses_done_dismissed_bundle_when_done_marker_is_missing(
    temp_state_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    run_id = "20260718T120002_000000"
    _launched_entry(run_id, pid=987)
    record = _record_agent(run_id, pid=987)
    child = SimpleNamespace(
        raw_suffix="20260718120000",
        is_workflow_child=True,
        status="KILLED",
        bundle_path="/archive/20260718120000__c0.json",
    )
    root = SimpleNamespace(
        raw_suffix="20260718120000",
        is_workflow_child=False,
        status="DONE",
        bundle_path="/archive/20260718120000.json",
    )

    with (
        patch("sase.axe.chop_lifecycle.is_process_running", return_value=False),
        patch(
            "sase.axe.chop_lifecycle.load_dismissed_bundle_summaries",
            return_value=[child, root],
        ) as load_summaries,
    ):
        completion = _agent_completion(record)
        assert finalize_launched_chop_runs("docs", ["docs"]) == 1

    assert completion.succeeded
    assert "dismissed bundle /archive/20260718120000.json" in completion.detail
    load_summaries.assert_called_with(
        suffixes={"20260718120000"},
        top_level_only=True,
        limit=None,
    )
    entry = read_chop_run("docs", "docs", run_id)
    assert entry is not None
    assert entry.status == "action_succeeded"


@pytest.mark.parametrize("status", ["FAILED", "KILLED"])
def test_lifecycle_uses_failed_dismissed_bundle_when_done_marker_is_missing(
    temp_state_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: str,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    run_id = f"20260718T120003_{status.lower()}"
    _launched_entry(run_id, pid=876)
    _record_agent(run_id, pid=876)
    summary = SimpleNamespace(
        raw_suffix="20260718120000",
        is_workflow_child=False,
        status=status,
        bundle_path="/archive/20260718120000.json",
    )

    with (
        patch("sase.axe.chop_lifecycle.is_process_running", return_value=False),
        patch(
            "sase.axe.chop_lifecycle.load_dismissed_bundle_summaries",
            return_value=[summary],
        ),
    ):
        assert finalize_launched_chop_runs("docs", ["docs"]) == 1

    entry = read_chop_run("docs", "docs", run_id)
    assert entry is not None
    assert entry.status == "action_failed"
    assert entry.error is not None
    assert "dismissed bundle /archive/20260718120000.json" in entry.error
    assert f"status {status}" in entry.error
