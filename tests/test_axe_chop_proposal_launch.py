"""Structured chop proposal-launch coverage."""

from __future__ import annotations

import json
import shlex
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.agent.launch_request_types import LaunchRequestError
from sase.agent.multi_prompt_launcher import MultiPromptPartialLaunchError
from sase.axe.chop_proposal_launch import launch_chop_proposals
from sase.axe.chop_policy import apply_chop_once_per
from sase.axe.chop_proposals import prepare_chop_proposals
from sase.axe.chop_runner import run_configured_chop_once
from sase.axe.config import AxeConfig, ChopConfig
from sase.axe.state import chop_run_log_path, read_chop_run
from sase.feature_flags import override_flags

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


def _known_project_resolver(repo: Path) -> object:
    return SimpleNamespace(
        workflow_type="git",
        ref="sase",
        workspace_dir=str(repo),
        project_file="/tmp/projects/sase/sase.sase",
    )


def test_typed_chop_proposal_uses_durable_admission_and_chop_env(
    temp_state_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("sase_core_rs")
    repo = tmp_path / "repo"
    repo.mkdir()
    pwd_capture = tmp_path / "condition-pwd.txt"
    prepared = prepare_chop_proposals(
        "docs",
        {
            "proposed_launches": [
                {
                    "id": "refresh",
                    "prompt": (
                        "%if::\n"
                        "```bash\n"
                        f"pwd > {shlex.quote(str(pwd_capture))}\n"
                        "```\n"
                        "Review docs."
                    ),
                    "workspace": "git:sase",
                    "agent_name": "refresh",
                    "env": {"MODE": "typed", "SASE_CHOP_NAME": "prompt-owned"},
                }
            ]
        },
    )
    monkeypatch.setattr(
        "sase.agent.launch_cwd_common.resolve_known_project_vcs_launch_ref",
        lambda _prompt: _known_project_resolver(repo),
    )
    calls: list[tuple[str, dict[str, str]]] = []

    def _launch(prompt: str, *, extra_env: dict[str, str]) -> list[SimpleNamespace]:
        calls.append((prompt, extra_env))
        return [
            SimpleNamespace(
                pid=501,
                agent_name="refresh",
                workspace_num=2,
                workspace_dir=str(repo),
                project_name="sase",
                workflow_name="ace(run)-260823_120000",
                cl_name="sase",
                timestamp="260823_120000",
                artifacts_dir=str(tmp_path / "artifacts" / "20260823120000"),
            )
        ]

    with (
        override_flags(typed_launch_units=True),
        patch("sase.notifications.senders.notify_workflow_complete") as notify,
    ):
        launches = launch_chop_proposals(
            lumberjack_name="docs",
            chop_name="docs",
            run_id="run-typed",
            proposals=prepared,
            launch_agent_from_cwd_fn=lambda *args, **kwargs: None,
            launch_agents_from_cwd_fn=_launch,
        )

    assert len(launches) == 1
    assert launches.typed_admission is not None
    assert launches.admission_result.admission_complete
    assert pwd_capture.read_text(encoding="utf-8").strip() == str(repo)
    prompt, env = calls[0]
    assert "%if" not in prompt
    assert "condition-pwd" not in prompt
    assert env["MODE"] == "typed"
    assert env["SASE_CHOP_NAME"] == "docs"
    assert env["SASE_CHOP_RUN_ID"] == "run-typed"
    assert env["SASE_CHOP_PROPOSAL_INDEX"] == "0"
    assert env["SASE_CHOP_ADMISSION_LOGICAL_ID"] == env["SASE_LAUNCH_LOGICAL_ID"]
    assert env["SASE_CHOP_ADMISSION_FINGERPRINT"]
    notify.assert_not_called()


def test_typed_chop_proposal_flag_off_rejects_before_launch(
    temp_state_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("sase_core_rs")
    repo = tmp_path / "repo"
    repo.mkdir()
    prepared = prepare_chop_proposals(
        "docs",
        {
            "proposed_launches": [
                {
                    "prompt": "%if::\n```bash\ntrue\n```\nReview docs.",
                    "workspace": "git:sase",
                }
            ]
        },
    )
    monkeypatch.setattr(
        "sase.agent.launch_cwd_common.resolve_known_project_vcs_launch_ref",
        lambda _prompt: _known_project_resolver(repo),
    )

    def _launch(*args: object, **kwargs: object) -> list[SimpleNamespace]:
        raise AssertionError("typed flag-off proposal reached the launcher")

    with override_flags(typed_launch_units=False):
        with pytest.raises(LaunchRequestError, match="typed_launch_units"):
            launch_chop_proposals(
                lumberjack_name="docs",
                chop_name="docs",
                run_id="run-flag-off",
                proposals=prepared,
                launch_agent_from_cwd_fn=lambda *args, **kwargs: None,
                launch_agents_from_cwd_fn=_launch,
            )


def test_runner_all_skipped_typed_admission_succeeds_without_agent(
    temp_state_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("sase_core_rs")
    repo = tmp_path / "repo"
    repo.mkdir()
    _result_script(
        tmp_path,
        "docs",
        {
            "schema_version": 1,
            "status": "ok",
            "proposed_launches": [
                {
                    "prompt": "%if::\n```bash\nexit 1\n```\nReview stale docs.",
                    "workspace": "git:sase",
                    "dedupe_key": "docs:stale",
                }
            ],
        },
    )
    monkeypatch.setattr(
        "sase.agent.launch_cwd_common.resolve_known_project_vcs_launch_ref",
        lambda _prompt: _known_project_resolver(repo),
    )

    with (
        override_flags(typed_launch_units=True),
        patch("sase.axe.chop_runner.find_all_patches", return_value=[]),
        patch("sase.axe.chop_runner.launch_agents_from_cwd") as launch_batch,
    ):
        outcome = run_configured_chop_once(
            lumberjack_name="docs",
            chop=ChopConfig(name="docs", description=""),
            axe_config=_config(tmp_path),
        )

    assert outcome.status == "action_succeeded"
    launch_batch.assert_not_called()
    assert outcome.run_id is not None
    entry = read_chop_run("docs", "docs", outcome.run_id)
    assert entry is not None
    assert entry.status == "action_succeeded"
    output = chop_run_log_path("docs", "docs", outcome.run_id).read_text(
        encoding="utf-8"
    )
    assert "Typed admission:" in output
    assert "1 skipped" in output
    assert "once-per duplicate" not in output


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
        patch("sase.axe.chop_runner.find_all_patches", return_value=[]),
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
        patch("sase.axe.chop_runner.find_all_patches", return_value=[]),
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
        patch("sase.axe.chop_runner.find_all_patches", return_value=[]),
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
    with patch("sase.axe.chop_runner.find_all_patches", return_value=[]):
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
