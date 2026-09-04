"""Cleanup archive DTO round-trips every dismissed-bundle field."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.ace.dismissed_agents import load_dismissed_bundles
from sase.ace.tui.actions.cleanup_payload import (
    CLEANUP_AGENT_ARCHIVE_VERSION,
    CLEANUP_AGENT_ARCHIVE_VERSION_KEY,
    agent_from_json,
    json_identities,
    serialize_agent,
)
from sase.ace.tui.models.agent import Agent, AgentType, LinkedRepoMetadata
from sase.ops.commands.agent import _apply_cleanup_payload_for_result


_REVIVAL_FIELDS = (
    "agent_family",
    "artifacts_dir",
    "llm_provider",
    "model",
    "reasoning_effort",
    "response_path",
)


def _local_agent(*, artifacts_dir: str | None, **overrides: object) -> Agent:
    defaults: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "my_feature",
        "project_file": "/tmp/projects/myproj/myproj.sase",
        "status": "DONE",
        "start_time": datetime(2026, 1, 1, 12, 0, 0),
        "raw_suffix": "20260101120000",
        "workflow": "ace-run",
        "agent_name": "crew--code",
        "agent_family": "crew",
        "agent_family_role": "code",
        "model": "grok-4",
        "llm_provider": "xai",
        "reasoning_effort": "high",
        "response_path": "/tmp/projects/myproj/artifacts/ace-run/20260101120000/response.md",
        "artifacts_dir": artifacts_dir,
    }
    defaults.update(overrides)
    return Agent(**defaults)  # type: ignore[arg-type]


def _imported_projected_agent(artifact_dir: str) -> Agent:
    return _local_agent(
        artifacts_dir=None,
        agent_name="athena.7n--code",
        agent_family="athena.7n",
        record_shape="list",
        index_record_dir=artifact_dir,
        response_path=f"{artifact_dir}/response.md",
        linked_repos=(
            LinkedRepoMetadata(name="sase-core", workspace_dir="/tmp/sase-core"),
        ),
    )


def _archive_without_version(agent: Agent) -> dict[str, object]:
    payload = serialize_agent(agent)
    payload.pop(CLEANUP_AGENT_ARCHIVE_VERSION_KEY)
    return payload


def _without_archive_metadata(payload: dict[str, object]) -> dict[str, object]:
    result = dict(payload)
    for key in (
        "archive_capabilities",
        "archive_payload_sha256",
        "archive_visibility",
        "durably_revivable",
        "historically_viewable",
        "missing_requirements",
        "restartable",
        "source_machine",
        "source_run_id",
        "source_username",
    ):
        result.pop(key, None)
    return result


def test_cleanup_archive_dto_fields_match_bundle_writer() -> None:
    agent = _local_agent(artifacts_dir="/tmp/artifacts/ace-run/20260101120000")
    dto_fields = set(serialize_agent(agent)) - {CLEANUP_AGENT_ARCHIVE_VERSION_KEY}
    writer_fields = set(agent.to_bundle_dict())

    assert dto_fields == writer_fields
    assert set(_REVIVAL_FIELDS) <= writer_fields


def test_cleanup_archive_round_trip_preserves_durable_record() -> None:
    artifacts_dir = "/tmp/artifacts/ace-run/20260101120000"
    agent = _local_agent(artifacts_dir=artifacts_dir)
    payload = serialize_agent(agent)
    json.dumps(payload)

    assert payload[CLEANUP_AGENT_ARCHIVE_VERSION_KEY] == CLEANUP_AGENT_ARCHIVE_VERSION
    for field_name in _REVIVAL_FIELDS:
        assert payload[field_name] == getattr(agent, field_name)

    restored = agent_from_json(payload)
    assert restored.to_bundle_dict() == _archive_without_version(agent)


def test_cleanup_archive_resolves_artifacts_dir_from_index_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_dir = "/tmp/projects/proj/artifacts/ace-run/20260101120000"
    agent = _imported_projected_agent(artifact_dir)
    monkeypatch.setattr(Agent, "get_artifacts_dir", lambda self: None)

    payload = serialize_agent(agent)
    assert payload["artifacts_dir"] == artifact_dir
    assert payload["agent_family"] == "athena.7n"
    assert payload["model"] == "grok-4"
    assert payload["llm_provider"] == "xai"
    assert payload["reasoning_effort"] == "high"
    assert payload["response_path"] == f"{artifact_dir}/response.md"

    restored = agent_from_json(payload)
    assert restored.artifacts_dir == artifact_dir
    assert restored.record_shape == "full"
    assert restored.agent_family == "athena.7n"
    assert restored.model == "grok-4"


def test_legacy_unversioned_payload_still_rehydrates() -> None:
    restored = agent_from_json(
        {
            "agent_type": "run",
            "cl_name": "legacy",
            "project_file": "/tmp/legacy.sase",
            "status": "DONE",
            "from_patch": True,
            "agent_family": "crew",
        }
    )
    assert restored.cl_name == "legacy"
    assert restored._from_patch is True
    assert restored.agent_family == "crew"


def test_unsupported_cleanup_archive_version_fails_loudly() -> None:
    with pytest.raises(ValueError, match="unsupported cleanup agent archive version"):
        agent_from_json(
            {
                CLEANUP_AGENT_ARCHIVE_VERSION_KEY: 99,
                "agent_type": "run",
                "cl_name": "x",
                "project_file": "/tmp/x.sase",
                "status": "DONE",
            }
        )


def _dismiss_through_cleanup_subprocess(agent: Agent, tmp_path: Path) -> Agent:
    bundles_dir = tmp_path / "dismissed_bundles"
    payload = json.loads(
        json.dumps(
            {
                "action": "dismiss",
                "transaction": "single_dismiss",
                "agent": serialize_agent(agent),
                "agents_with_children": [serialize_agent(agent)],
                "dismissed_identities": json_identities([agent.identity]),
                "added_identities": json_identities([agent.identity]),
            }
        )
    )
    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir),
        patch(
            "sase.ace.dismissed_agents._DISMISSED_AGENTS_FILE",
            tmp_path / "dismissed_agents.json",
        ),
        patch("sase.ace.dismissed_agents._OLD_BUNDLES_FILE", tmp_path / "old.json"),
        patch(
            "sase.ace.tui.actions.agents._dismissing.sync_dismissed_agent_artifact_index"
        ),
        patch(
            "sase.ace.tui.actions.agents._dismiss_persistence.delete_agent_artifacts"
        ),
        patch(
            "sase.ace.tui.actions.agents._dismiss_persistence."
            "delete_agent_artifact_index_artifacts"
        ),
        patch(
            "sase.ace.tui.actions.agents._dismiss_persistence."
            "_release_held_workspace_claims",
            return_value=0,
        ),
    ):
        success, message, _result = _apply_cleanup_payload_for_result(payload)
        assert success, message
        loaded = load_dismissed_bundles()
    assert len(loaded) == 1
    return loaded[0]


def test_cleanup_subprocess_dismiss_preserves_local_durable_record(
    tmp_path: Path,
) -> None:
    artifacts_dir = str(tmp_path / "artifacts" / "ace-run" / "20260101120000")
    agent = _local_agent(artifacts_dir=artifacts_dir)
    loaded = _dismiss_through_cleanup_subprocess(agent, tmp_path)
    expected = agent_from_json(serialize_agent(agent)).to_bundle_dict()
    actual = loaded.to_bundle_dict()
    assert _without_archive_metadata(actual) == _without_archive_metadata(expected)
    assert actual["archive_visibility"] == "hidden"
    assert actual["archive_capabilities"] == {
        "historically_viewable": True,
        "durably_revivable": True,
        "restartable": False,
        "missing_requirements": ["prompt"],
    }
    for field_name in _REVIVAL_FIELDS:
        assert getattr(loaded, field_name) == getattr(agent, field_name)


def test_cleanup_subprocess_dismiss_preserves_imported_projected_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_dir = str(tmp_path / "imported" / "ace-run" / "20260101120000")
    agent = _imported_projected_agent(artifact_dir)
    monkeypatch.setattr(Agent, "get_artifacts_dir", lambda self: None)
    loaded = _dismiss_through_cleanup_subprocess(agent, tmp_path)
    assert loaded.artifacts_dir == artifact_dir
    assert loaded.agent_family == "athena.7n"
    assert loaded.model == "grok-4"
    assert loaded.llm_provider == "xai"
    assert loaded.reasoning_effort == "high"
    assert loaded.response_path == f"{artifact_dir}/response.md"
    assert loaded.linked_repos == (
        LinkedRepoMetadata(name="sase-core", workspace_dir="/tmp/sase-core"),
    )
