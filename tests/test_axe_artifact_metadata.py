"""Tests for provider-neutral agent artifact metadata helpers."""

import json
from pathlib import Path

from sase.axe.artifact_metadata import (
    _fallback_agent_artifact_id,
    enrich_agent_artifact_metadata,
)
from sase.axe.run_agent_helpers import create_followup_artifacts
from sase.axe.run_agent_runner_setup import apply_retry_chain_to_meta
from sase.axe.run_agent_retry_spawn import RetryHandoff


def test_fallback_agent_artifact_id_uses_artifacts_dir_identity(tmp_path: Path) -> None:
    artifacts_dir = (
        tmp_path
        / ".sase"
        / "projects"
        / "proj"
        / "artifacts"
        / "ace-run"
        / "20260505120000"
    )

    assert (
        _fallback_agent_artifact_id(str(artifacts_dir))
        == "agent:proj:ace-run:20260505120000"
    )


def test_enrich_preserves_runtime_fields_and_adds_contract(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts" / "ace-run" / "20260505120000"
    metadata = {
        "name": "alpha",
        "model": "gpt-5.4",
        "llm_provider": "codex",
        "vcs_provider": "github",
    }

    enriched = enrich_agent_artifact_metadata(
        metadata,
        artifacts_dir=str(artifacts_dir),
        cl_name="feature",
    )

    assert enriched["artifact_schema_version"] == 1
    assert enriched["artifact_agent_id"] == "alpha"
    assert enriched["artifact_source_dir"] == str(artifacts_dir)
    assert enriched["changespec_name"] == "feature"
    assert enriched["model"] == "gpt-5.4"
    assert enriched["llm_provider"] == "codex"
    assert enriched["vcs_provider"] == "github"


def test_retry_handoff_writes_parent_agent_contract(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "agent"
    artifacts_dir.mkdir()
    handoff = RetryHandoff(
        parent_timestamp="20260505115900",
        retry_attempt=1,
        chain_root_timestamp="20260505115900",
        error_snippet="Prompt is too long",
        error_category="context_overflow",
        continuation_prompt=None,
        original_prompt="Do it",
        chat_path=None,
        plan_path=None,
        role_suffix=None,
        workspace_num=1,
        workspace_dir=str(tmp_path),
        vcs_ref=None,
        cl_name="feature",
        project_file=str(tmp_path / "proj.gp"),
        project_name="proj",
        update_target="",
        is_home_mode=False,
        agent_name="parent",
        agent_model="gpt-5.4",
        agent_llm_provider="codex",
        agent_vcs_provider="github",
        fallback_model=None,
        use_fallback=False,
    )
    meta = {"name": "child", "changespec_name": "feature"}

    apply_retry_chain_to_meta(
        retry_handoff=handoff,
        agent_meta=meta,
        artifacts_dir=str(artifacts_dir),
    )

    written = json.loads((artifacts_dir / "agent_meta.json").read_text())
    assert written["artifact_agent_id"] == "child"
    assert written["retry_of_timestamp"] == "20260505115900"
    assert written["parent_agent_timestamp"] == "20260505115900"
    assert written["parent_agent_name"] == "parent"
    assert written["retry_chain_root_timestamp"] == "20260505115900"


def test_followup_artifacts_inherit_parent_contract(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    artifacts_dir = create_followup_artifacts(
        "proj",
        {
            "name": "planner",
            "model": "gpt-5.4",
            "llm_provider": "codex",
            "changespec_name": "feature",
        },
        ".code",
        "20260505120000",
        workspace_num=2,
        agent_name_override="planner.code",
        workflow_name="planner",
    )

    meta = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    assert meta["artifact_agent_id"] == "planner.code"
    assert meta["parent_agent_timestamp"] == "20260505120000"
    assert meta["parent_agent_name"] == "planner"
    assert meta["changespec_name"] == "feature"
    assert meta["model"] == "gpt-5.4"
