"""Structured chop-result parsing and proposal-planning coverage."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from sase.axe.chop_policy import apply_chop_once_per
from sase.axe.chop_proposals import (
    plan_chop_proposals,
    prepare_chop_proposals,
    proposal_previews,
)
from sase.axe.chop_runner import run_configured_chop_once
from sase.axe.config import AxeConfig, ChopConfig
from sase.axe.state import (
    chop_run_context_path,
    chop_run_result_path,
    read_chop_run,
)
from sase.core.axe_chop_facade import derive_chop_agent_name
from sase.xprompt.directives import extract_prompt_directives

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


def test_conflicting_raw_clan_summaries_fail_before_launch(
    temp_state_dir: Path,
    tmp_path: Path,
) -> None:
    _result_script(
        tmp_path,
        "conflict",
        {
            "schema_version": 1,
            "status": "ok",
            "proposed_launches": [
                {
                    "prompt": "First.",
                    "workspace": "git:sase",
                    "agent_name": "first",
                    "clan": "review-@",
                    "clan_summary": "First summary",
                },
                {
                    "prompt": "Second.",
                    "workspace": "git:sase",
                    "agent_name": "second",
                    "clan": "review-@",
                    "clan_summary": "Different summary",
                },
            ],
        },
    )

    with (
        patch("sase.axe.chop_runner.find_all_changespecs", return_value=[]),
        patch("sase.axe.chop_runner.launch_agent_from_cwd") as launch_one,
        patch("sase.axe.chop_runner.launch_agents_from_cwd") as launch_many,
    ):
        outcome = run_configured_chop_once(
            lumberjack_name="checks",
            chop=ChopConfig(name="conflict", description=""),
            axe_config=_config(tmp_path),
            dry_run=True,
        )

    launch_one.assert_not_called()
    launch_many.assert_not_called()
    assert outcome.status == "check_error"
    assert outcome.error is not None
    assert "conflicting_clan_summary" in str(outcome.error)
    assert "proposed_launches[1].clan_summary" in str(outcome.error)


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
                    "clan_summary": "[bold]Large modules[/bold]\n  Split safely.",
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
    assert previews[0]["clan_summary"] is None
    assert previews[1]["clan_role"] == "declare"
    assert previews[1]["clan_summary"] == (
        "[bold]Large modules[/bold]\n  Split safely."
    )
    assert previews[1]["wait_name"] is None
    _, directives = extract_prompt_directives(str(previews[1]["prompt"]))
    assert directives.clan_summary == "[bold]Large modules[/bold]\nSplit safely."
    assert sum("summary=[[" in str(preview["prompt"]) for preview in previews) == 1


def test_clan_summary_inherits_per_raw_clan_before_planning(
    temp_state_dir: Path,
) -> None:
    prepared = prepare_chop_proposals(
        "split",
        {
            "proposed_launches": [
                {
                    "prompt": "Research first.",
                    "workspace": "git:sase",
                    "agent_name": "first",
                    "clan": "research-@",
                },
                {
                    "prompt": "Review.",
                    "workspace": "git:sase",
                    "agent_name": "reviewer",
                    "clan": "review-@",
                    "clan_summary": "[italic]Review[/italic]",
                },
                {
                    "prompt": "Research second.",
                    "workspace": "git:sase",
                    "agent_name": "second",
                    "clan": "research-@",
                    "clan_summary": "[bold]Research[/bold]",
                },
            ]
        },
    )

    assert [proposal.clan_summary for proposal in prepared] == [
        "[bold]Research[/bold]",
        "[italic]Review[/italic]",
        "[bold]Research[/bold]",
    ]
    plans = plan_chop_proposals(prepared)
    assert [plan.clan_summary for plan in plans] == [
        "[bold]Research[/bold]",
        "[italic]Review[/italic]",
        None,
    ]
    extracted = [extract_prompt_directives(plan.prompt)[1] for plan in plans]
    assert [item.clan_summary for item in extracted] == [
        "[bold]Research[/bold]",
        "[italic]Review[/italic]",
        None,
    ]


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
    assert plans[0].prompt == (
        "#git:sase\n%id:toobig-1.split_file.new\n%clan(toobig-1, tribe=chop)\nSplit.\n"
    )
    assert plans[1].prompt == (
        "#git:sase\n%id:review-0.reviewer\n%clan(review-0, tribe=chop)\nReview.\n"
    )
