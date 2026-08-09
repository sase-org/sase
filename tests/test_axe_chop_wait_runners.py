"""Lumberjack runner-slot defaults on structured chop proposals."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sase.axe.chop_proposals import (
    launch_chop_proposals,
    prepare_chop_proposals,
    proposal_previews,
)
from sase.axe.chop_runner import run_configured_chop_once
from sase.axe.config import AxeConfig, ChopConfig
from sase.xprompt.directives import (
    extract_prompt_directives,
    has_deferred_start_directive,
)

from tests.axe_chop_runner_helpers import make_script

pytest_plugins = ["tests.axe_chop_runner_fixtures"]


def _proposal_result(*prompts: dict[str, object]) -> dict[str, object]:
    return {"proposed_launches": list(prompts)}


def test_prepare_and_preview_inject_lumberjack_wait_runners() -> None:
    prepared = prepare_chop_proposals(
        "audit",
        _proposal_result(
            {"prompt": "Audit.", "workspace": "git:sase"},
        ),
        lumberjack_wait_runners=0,
    )

    prompt = str(proposal_previews(prepared)[0]["prompt"])

    assert prepared[0].wait_runners == 0
    assert "%wait(runners=0)" in prompt
    assert has_deferred_start_directive(prompt) is True


def test_absent_lumberjack_wait_runners_leaves_prompt_unchanged() -> None:
    prepared = prepare_chop_proposals(
        "audit",
        _proposal_result(
            {"prompt": "Audit.", "workspace": "git:sase"},
        ),
    )

    prompt = str(proposal_previews(prepared)[0]["prompt"])

    assert prepared[0].wait_runners is None
    assert "%wait(runners" not in prompt


def test_proposal_wait_runners_overrides_lumberjack_default() -> None:
    prepared = prepare_chop_proposals(
        "audit",
        _proposal_result(
            {
                "prompt": "%wait(runners=2)\nAudit.",
                "workspace": "git:sase",
            },
        ),
        lumberjack_wait_runners=0,
    )

    prompt = str(proposal_previews(prepared)[0]["prompt"])

    assert prompt.count("runners=") == 1
    assert "%wait(runners=2)" in prompt


def test_fenced_wait_runners_does_not_override_lumberjack_default() -> None:
    prepared = prepare_chop_proposals(
        "audit",
        _proposal_result(
            {
                "prompt": "```text\n%wait(runners=2)\n```\nAudit.",
                "workspace": "git:sase",
            },
        ),
        lumberjack_wait_runners=0,
    )

    prompt = str(proposal_previews(prepared)[0]["prompt"])

    assert prompt.count("runners=") == 2
    assert "%wait(runners=0)" in prompt


def test_wait_dependency_and_runner_threshold_merge() -> None:
    prepared = prepare_chop_proposals(
        "audit",
        _proposal_result(
            {
                "id": "inspect",
                "prompt": "Inspect.",
                "workspace": "git:sase",
            },
            {
                "prompt": "Summarize.",
                "workspace": "git:sase",
                "wait_on": "inspect",
            },
        ),
        lumberjack_wait_runners=1,
    )

    preview = proposal_previews(prepared)[1]
    prompt = str(preview["prompt"])
    _, directives = extract_prompt_directives(prompt)

    assert f"%wait:{preview['wait_name']}" in prompt
    assert "%wait(runners=1)" in prompt
    assert directives.wait == [preview["wait_name"]]
    assert directives.wait_runners == 1


def test_clan_batch_injects_threshold_into_every_segment(
    temp_state_dir: Path,
) -> None:
    prepared = prepare_chop_proposals(
        "audit",
        _proposal_result(
            {
                "prompt": "First.",
                "workspace": "git:sase",
                "agent_name": "first",
                "clan": "audit-@",
            },
            {
                "prompt": "Second.",
                "workspace": "git:sase",
                "agent_name": "second",
                "clan": "audit-@",
            },
        ),
        lumberjack_wait_runners=0,
    )
    captured: list[str] = []

    def _launch_batch(
        query: str,
        *,
        segment_extra_env: list[dict[str, str]],
    ) -> list[SimpleNamespace]:
        captured.append(query)
        assert len(segment_extra_env) == 2
        return [
            SimpleNamespace(pid=101, agent_name="audit-0.first"),
            SimpleNamespace(pid=102, agent_name="audit-0.second"),
        ]

    launch_chop_proposals(
        lumberjack_name="audits",
        chop_name="audit",
        run_id="run-1",
        proposals=prepared,
        launch_agent_from_cwd_fn=lambda *args, **kwargs: None,
        launch_agents_from_cwd_fn=_launch_batch,
    )

    segments = captured[0].split("\n---\n")
    assert len(segments) == 2
    assert all(segment.count("%wait(runners=0)") == 1 for segment in segments)


def test_runner_threads_lumberjack_threshold_into_dry_run_preview(
    temp_state_dir: Path,
    tmp_path: Path,
) -> None:
    payload = json.dumps(
        {
            "schema_version": 1,
            "status": "ok",
            "proposed_launches": [
                {"prompt": "Audit.", "workspace": "git:sase"},
            ],
        }
    )
    make_script(
        tmp_path,
        "audit",
        f"printf '%s' '{payload}' > \"$SASE_CHOP_RESULT_FILE\"\n",
    )

    with patch("sase.axe.chop_runner.find_all_patches", return_value=[]):
        outcome = run_configured_chop_once(
            lumberjack_name="audits",
            chop=ChopConfig(name="audit", description=""),
            axe_config=AxeConfig(chop_script_dirs=[str(tmp_path / "scripts")]),
            wait_runners_default=0,
            dry_run=True,
        )

    assert outcome.status == "success"
    assert "%wait(runners=0)" in str(outcome.proposals[0]["prompt"])
