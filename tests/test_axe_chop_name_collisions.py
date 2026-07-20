"""Agent-name collision behavior for structured chop proposals."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.agent.launch_validation import AgentNameLaunchCollisionError
from sase.axe.chop_policy import apply_chop_once_per
from sase.axe.chop_proposals import prepare_chop_proposals
from sase.axe.chop_runner import run_configured_chop_once
from sase.axe.config import AxeConfig, ChopConfig
from sase.axe.state import chop_run_log_path, read_chop_run

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


def test_explicit_agent_name_collision_skips_and_releases_once_per_key(
    temp_state_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    _result_script(
        tmp_path,
        "audit",
        {
            "schema_version": 1,
            "status": "ok",
            "proposed_launches": [
                {
                    "prompt": "Audit bugs.",
                    "workspace": "git:sase",
                    "agent_name": "audit_bugs.sase.abc123",
                    "dedupe_key": "audit:sase:abc123",
                }
            ],
        },
    )
    collision = AgentNameLaunchCollisionError(
        "audit_bugs.sase.abc123",
        "audit_bugs.sase.abc124",
    )
    chop = ChopConfig(name="audit", description="")

    with (
        patch("sase.axe.chop_runner.find_all_changespecs", return_value=[]),
        patch(
            "sase.axe.chop_runner.launch_agent_from_cwd",
            side_effect=collision,
        ),
    ):
        outcome = run_configured_chop_once(
            lumberjack_name="audits",
            chop=chop,
            axe_config=_config(tmp_path),
        )

    assert outcome.status == "skipped"
    assert outcome.reason is not None and "agent-name collision" in outcome.reason
    assert outcome.proposals[0]["validation"] == "name_collision"
    assert "audit_bugs.sase.abc123" in outcome.proposals[0]["skip_reason"]
    assert outcome.run_id is not None
    entry = read_chop_run("audits", "audit", outcome.run_id)
    assert entry is not None
    assert entry.status == "skipped"
    assert entry.reason == outcome.reason
    assert entry.launches == []
    output = chop_run_log_path("audits", "audit", outcome.run_id).read_text(
        encoding="utf-8"
    )
    assert "Skipped proposal 1" in output
    assert "Released 1 once-per key(s) after agent-name collision skip" in output

    reproposed = prepare_chop_proposals(
        "audit",
        {
            "proposed_launches": [
                {
                    "prompt": "Audit bugs.",
                    "workspace": "git:sase",
                    "agent_name": "audit_bugs.sase.abc123",
                    "dedupe_key": "audit:sase:abc123",
                }
            ]
        },
    )
    once_per = apply_chop_once_per(
        lumberjack_name="audits",
        chop=chop,
        proposals=reproposed,
        persist=False,
    )
    assert once_per.accepted_indices == (0,)


def test_explicit_agent_name_collision_relinks_later_wait_and_keeps_launching(
    temp_state_dir: Path,
    tmp_path: Path,
) -> None:
    _result_script(
        tmp_path,
        "audit",
        {
            "schema_version": 1,
            "status": "ok",
            "proposed_launches": [
                {
                    "id": "root",
                    "prompt": "Prepare.",
                    "workspace": "git:sase",
                    "agent_name": "audit.prepare",
                },
                {
                    "id": "audit",
                    "prompt": "Audit.",
                    "workspace": "git:sase",
                    "agent_name": "audit.taken",
                    "wait_on": "root",
                },
                {
                    "prompt": "Summarize.",
                    "workspace": "git:sase",
                    "agent_name": "audit.summary",
                    "wait_on": "audit",
                },
            ],
        },
    )
    calls: list[str] = []

    def _launch(prompt: str, *, extra_env: dict[str, str]) -> SimpleNamespace:
        del extra_env
        calls.append(prompt)
        if len(calls) == 2:
            raise AgentNameLaunchCollisionError("audit.taken", "audit.taken1")
        return SimpleNamespace(
            pid=300 + len(calls),
            agent_name="actual.root" if len(calls) == 1 else "actual.summary",
        )

    with (
        patch("sase.axe.chop_runner.find_all_changespecs", return_value=[]),
        patch("sase.axe.chop_runner.launch_agent_from_cwd", side_effect=_launch),
    ):
        outcome = run_configured_chop_once(
            lumberjack_name="audits",
            chop=ChopConfig(name="audit", description=""),
            axe_config=_config(tmp_path),
        )

    assert outcome.status == "launched"
    assert len(calls) == 3
    assert "%wait:actual.root" in calls[2]
    assert outcome.proposals[1]["validation"] == "name_collision"
    assert outcome.proposals[2]["wait_on"] == "root"
    assert [launch["index"] for launch in outcome.launches] == [0, 2]
    assert outcome.launches[1]["wait_on"] == "root"
    assert outcome.launches[1]["wait_name"] == "actual.root"
    assert outcome.run_id is not None
    entry = read_chop_run("audits", "audit", outcome.run_id)
    assert entry is not None
    assert entry.status == "launched"
    assert [launch["index"] for launch in entry.launches] == [0, 2]


def test_derived_agent_name_collision_remains_action_failed(
    temp_state_dir: Path,
    tmp_path: Path,
) -> None:
    _result_script(
        tmp_path,
        "audit",
        {
            "schema_version": 1,
            "status": "ok",
            "proposed_launches": [
                {
                    "prompt": "Audit.",
                    "workspace": "git:sase",
                }
            ],
        },
    )

    with (
        patch("sase.axe.chop_runner.find_all_changespecs", return_value=[]),
        patch(
            "sase.axe.chop_runner.launch_agent_from_cwd",
            side_effect=AgentNameLaunchCollisionError("audit.run", "audit.run1"),
        ),
    ):
        outcome = run_configured_chop_once(
            lumberjack_name="audits",
            chop=ChopConfig(name="audit", description=""),
            axe_config=_config(tmp_path),
        )

    assert outcome.status == "action_failed"
    assert isinstance(outcome.error, AgentNameLaunchCollisionError)
    assert outcome.proposals[0]["validation"] == "valid"
    assert outcome.run_id is not None
    entry = read_chop_run("audits", "audit", outcome.run_id)
    assert entry is not None
    assert entry.status == "action_failed"


def test_clan_agent_name_collision_remains_action_failed(
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
                    "prompt": "Split.",
                    "workspace": "git:sase",
                    "agent_name": "split.member",
                    "clan": "split-@",
                }
            ],
        },
    )

    with (
        patch("sase.axe.chop_runner.find_all_changespecs", return_value=[]),
        patch(
            "sase.axe.chop_runner.launch_agents_from_cwd",
            side_effect=AgentNameLaunchCollisionError(
                "split-0.split.member",
                "split-0.split.member1",
            ),
        ),
    ):
        outcome = run_configured_chop_once(
            lumberjack_name="split",
            chop=ChopConfig(name="split", description=""),
            axe_config=_config(tmp_path),
        )

    assert outcome.status == "action_failed"
    assert isinstance(outcome.error, AgentNameLaunchCollisionError)
    assert outcome.run_id is not None
    entry = read_chop_run("split", "split", outcome.run_id)
    assert entry is not None
    assert entry.status == "action_failed"
