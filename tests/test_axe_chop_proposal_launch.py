"""Typed chop proposal-launch admission coverage."""

from __future__ import annotations

import shlex
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.agent.launch_request_types import LaunchRequestError
from sase.axe.chop_proposal_launch import launch_chop_proposals
from sase.axe.chop_proposals import prepare_chop_proposals
from sase.axe.chop_runner import run_configured_chop_once
from sase.axe.config import ChopConfig
from sase.axe.state import chop_run_log_path, read_chop_run
from sase.feature_flags import override_flags

from tests._axe_chop_proposal_launch_helpers import (
    config,
    known_project_resolver,
    result_script,
)

pytest_plugins = ["tests.axe_chop_runner_fixtures"]


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
        lambda _prompt: known_project_resolver(repo),
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
        lambda _prompt: known_project_resolver(repo),
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
    result_script(
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
        lambda _prompt: known_project_resolver(repo),
    )

    with (
        override_flags(typed_launch_units=True),
        patch("sase.axe.chop_runner.find_all_patches", return_value=[]),
        patch("sase.axe.chop_runner.launch_agents_from_cwd") as launch_batch,
    ):
        outcome = run_configured_chop_once(
            lumberjack_name="docs",
            chop=ChopConfig(name="docs", description=""),
            axe_config=config(tmp_path),
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
