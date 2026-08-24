"""Chop runner launch-ordering and wait-directive coverage."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sase.agent.multi_prompt_launcher import MultiPromptPartialLaunchError
from sase.axe.chop_policy import apply_chop_once_per
from sase.axe.chop_proposals import prepare_chop_proposals
from sase.axe.chop_runner import run_configured_chop_once
from sase.axe.config import ChopConfig
from sase.axe.state import read_chop_run

from tests._axe_chop_proposal_launch_helpers import config, result_script
from tests.axe_chop_runner_helpers import make_script

pytest_plugins = ["tests.axe_chop_runner_fixtures"]


def test_clan_partial_launch_keeps_started_member_recorded(
    temp_state_dir: Path,
    tmp_path: Path,
) -> None:
    result_script(
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
        patch("sase.axe.chop_runner.find_all_patches", return_value=[]),
        patch("sase.axe.chop_runner.launch_agents_from_cwd", side_effect=_fail_batch),
    ):
        outcome = run_configured_chop_once(
            lumberjack_name="split",
            chop=ChopConfig(name="split", description=""),
            axe_config=config(tmp_path),
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
    result_script(
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
        patch("sase.axe.chop_runner.find_all_patches", return_value=[]),
        patch("sase.axe.chop_runner.launch_agent_from_cwd", side_effect=_launch),
    ):
        outcome = run_configured_chop_once(
            lumberjack_name="docs",
            chop=ChopConfig(name="docs", description=""),
            axe_config=config(tmp_path),
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
    result_script(
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
        patch("sase.axe.chop_runner.find_all_patches", return_value=[]),
        patch("sase.axe.chop_runner.launch_agent_from_cwd", side_effect=_launch),
    ):
        outcome = run_configured_chop_once(
            lumberjack_name="docs",
            chop=chop,
            axe_config=config(tmp_path),
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
    with patch("sase.axe.chop_runner.find_all_patches", return_value=[]):
        outcome = run_configured_chop_once(
            lumberjack_name="checks",
            chop=ChopConfig(name="verbose", description=""),
            axe_config=config(tmp_path),
            chop_verbose=True,
        )
    assert outcome.status == "success"
    assert outcome.run_id is not None
    entry = read_chop_run("checks", "verbose", outcome.run_id)
    assert entry is not None
    assert entry.output_bytes == 1
