"""Tests for runner directive metadata environment transitions."""

from __future__ import annotations

import os
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.axe.run_agent_directive_metadata import (
    AgentMetadataInputs,
    EPIC_WORK_ENV_METADATA_NAMES,
    consume_epic_clan_summary_script_from_env,
    epic_work_environment_from_metadata,
    epic_work_metadata_from_env,
    preserved_agent_metadata,
)
from sase.bead.work import SASE_EPIC_CLAN_SUMMARY_SCRIPT_ENV


def test_epic_work_environment_mapping_consumes_and_reconstructs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected_metadata: dict[str, str] = {}
    for index, (env_name, meta_name) in enumerate(
        EPIC_WORK_ENV_METADATA_NAMES,
        start=1,
    ):
        value = f"value-{index}"
        monkeypatch.setenv(env_name, value)
        expected_metadata[meta_name] = value

    metadata = epic_work_metadata_from_env()

    assert {key: metadata[key] for key in expected_metadata} == expected_metadata
    assert all(
        env_name not in os.environ for env_name, _ in EPIC_WORK_ENV_METADATA_NAMES
    )
    assert epic_work_environment_from_metadata(metadata) == {
        env_name: expected_metadata[meta_name]
        for env_name, meta_name in EPIC_WORK_ENV_METADATA_NAMES
    }


def test_epic_work_environment_reconstruction_uses_only_nonempty_strings() -> None:
    metadata: dict[str, object] = {
        "epic_plan_ref": "plans/epic.md",
        "epic_plan_snapshot": "/state/epic.md",
        "epic_bead_id": "",
        "phase_bead_id": 42,
        "clan_tribe": "   ",
    }

    assert epic_work_environment_from_metadata(metadata) == {
        "SASE_EPIC_PLAN_REF": "plans/epic.md",
        "SASE_EPIC_PLAN_SNAPSHOT": "/state/epic.md",
    }


def test_epic_clan_summary_script_is_consumed_without_metadata_round_trip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SASE_EPIC_CLAN_SUMMARY_SCRIPT_ENV, "  make_summary  ")

    assert consume_epic_clan_summary_script_from_env() == "make_summary"
    assert SASE_EPIC_CLAN_SUMMARY_SCRIPT_ENV not in os.environ
    assert (
        epic_work_environment_from_metadata(
            {"epic_clan_summary_script": "make_summary"}
        )
        == {}
    )


def test_child_identity_persists_and_publishes_one_local_machine_hood(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.core.agent_identity_facade import (
        AgentIdentitySnapshot,
        AgentOwnerIdentity,
    )

    identity_snapshot = AgentIdentitySnapshot(
        AgentOwnerIdentity("alice", "athena"),
        ("athena", "zeus"),
    )
    monkeypatch.setattr(
        AgentIdentitySnapshot,
        "current",
        classmethod(lambda _cls: identity_snapshot),
    )
    monkeypatch.delenv("SASE_AGENT_PLANNED_NAME", raising=False)
    monkeypatch.delenv("SASE_REPEAT_NAME", raising=False)

    from sase.axe.run_agent_directive_identity import (
        prepare_agent_name_request,
        resolve_agent_identity,
    )
    from sase.xprompt.directives import extract_prompt_directives

    _prompt, directives = extract_prompt_directives("%id:foo\nDo work")
    request = prepare_agent_name_request(
        directives=directives,
        family_attach_plan=None,
        fork_reference_prompt="",
        wait_names=[],
        auto_dismiss=None,
    )
    artifacts_dir = tmp_path / ".sase/projects/proj/artifacts/ace-run/20260722120000"
    artifacts_dir.mkdir(parents=True)
    inputs = AgentMetadataInputs(
        workspace_dir="/workspace",
        workspace_num=7,
        output_path=None,
        bead_id=None,
        wait_names=[],
        wait_identity_deps=[],
        wait_fork_sources=[],
        wait_beads=[],
        model=None,
        llm_provider=None,
        reasoning_effort=None,
        model_alias=None,
        model_alias_trail=[],
        model_alias_origin=None,
        model_alias_reservation=None,
        model_alias_overrides={},
        vcs_provider=None,
        auto_dismiss=None,
        preserved={},
        epic_work={},
        cl_name=None,
    )

    with patch.object(Path, "home", return_value=tmp_path):
        identity = resolve_agent_identity(
            request,
            directives=directives,
            family_attach_plan=None,
            clan_membership_plan=None,
            artifacts_dir=str(artifacts_dir),
            metadata_inputs=inputs,
        )

    assert identity.name == "foo"
    assert identity.meta["name"] == "foo"
    assert identity.meta["workspace_num"] == 7
    assert os.environ["SASE_AGENT_NAME"] == "foo"


def test_preserved_agent_metadata_keeps_model_alias_provenance(
    tmp_path: Path,
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "agent_meta.json").write_text(
        (
            '{"model":"opus","llm_provider":"claude","model_alias":"medium",'
            '"model_alias_trail":["medium","worker"],'
            '"model_alias_origin":"directive"}'
        ),
        encoding="utf-8",
    )

    preserved = preserved_agent_metadata(str(artifacts_dir))

    assert preserved["model"] == "opus"
    assert preserved["llm_provider"] == "claude"
    assert preserved["model_alias"] == "medium"
    assert preserved["model_alias_trail"] == ["medium", "worker"]
    assert preserved["model_alias_origin"] == "directive"


def test_preserved_agent_metadata_keeps_model_alias_reservation(
    tmp_path: Path,
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "model": "opus",
                "llm_provider": "claude",
                "model_alias_reservation": {
                    "alias": "large",
                    "target": "claude/opus",
                    "effort": "high",
                    "alias_trail": ["large"],
                    "alias_origin": "default_model",
                    "redeemed": False,
                },
            }
        ),
        encoding="utf-8",
    )

    preserved = preserved_agent_metadata(str(artifacts_dir))

    assert preserved["model_alias_reservation"] == {
        "alias": "large",
        "target": "claude/opus",
        "effort": "high",
        "alias_trail": ["large"],
        "alias_origin": "default_model",
        "redeemed": False,
    }


@pytest.mark.parametrize(
    "model_alias_trail",
    [
        "medium",
        ["medium", 42],
        ["medium", ""],
    ],
)
def test_preserved_agent_metadata_rejects_malformed_model_alias_trail(
    tmp_path: Path,
    model_alias_trail: object,
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "agent_meta.json").write_text(
        (
            '{"model":"opus","llm_provider":"claude","model_alias":"medium",'
            f'"model_alias_trail":{model_alias_trail!r},'
            '"model_alias_origin":"directive"}'
        ).replace("'", '"'),
        encoding="utf-8",
    )

    preserved = preserved_agent_metadata(str(artifacts_dir))

    assert "model_alias_trail" not in preserved
    assert preserved["model_alias_origin"] == "directive"


def test_preserved_agent_metadata_keeps_workspace_num(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "agent_meta.json").write_text(
        '{"workspace_num":12,"workspace_dir":"/tmp/sase_12"}',
        encoding="utf-8",
    )

    preserved = preserved_agent_metadata(str(artifacts_dir))

    assert preserved["workspace_num"] == 12
