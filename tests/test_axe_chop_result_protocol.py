"""Structured chop-result parsing, proposal launch, and lifecycle coverage."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.axe.chop_agents import _record_chop_agent_launch
from sase.axe.chop_lifecycle import _agent_completion, finalize_launched_chop_runs
from sase.axe.chop_policy import apply_chop_once_per
from sase.axe.chop_proposals import prepare_chop_proposals
from sase.axe.chop_runner import run_configured_chop_once
from sase.axe.config import AxeConfig, ChopConfig
from sase.axe.state import (
    ChopRunEntry,
    chop_run_context_path,
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
    assert f"%id:{first_name}" in first_prompt
    assert "%tribe:chop" in first_prompt
    assert "%model:codex/gpt-5.6-sol" in first_prompt
    assert f"%wait:{first_name}" in second_prompt


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


def _launched_entry(run_id: str, *, pid: int) -> ChopRunEntry:
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
        launches=[{"pid": pid}],
    )
    return entry


def _record_agent(run_id: str, *, pid: int) -> object:
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
        timestamp="260718_120000",
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


def test_lifecycle_fails_dead_agent_without_done_marker(
    temp_state_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    run_id = "20260718T120001_000000"
    _launched_entry(run_id, pid=654)
    _record_agent(run_id, pid=654)

    with patch("sase.axe.chop_lifecycle.is_process_running", return_value=False):
        assert finalize_launched_chop_runs("docs", ["docs"]) == 1
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
