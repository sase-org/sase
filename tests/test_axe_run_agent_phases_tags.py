"""Tests for runner prompt-tag persistence."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.ace.tui.models.agent import AgentType
from sase.axe.run_agent_phases import extract_directives_and_write_meta
from sase.llm_provider.temporary_override import set_temporary_override


def test_extract_directives_persists_tag_with_atomic_helper(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace_dir = tmp_path / "workspace"
    artifacts_dir = tmp_path / "artifacts" / "20260506120000"
    workspace_dir.mkdir()
    artifacts_dir.mkdir(parents=True)
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)

    with (
        patch(
            "sase.llm_provider.temporary_override."
            "resolve_effective_default_provider_model",
            return_value=("codex", "gpt-5"),
        ),
        patch("sase.vcs_provider._registry.detect_vcs", return_value=None),
        patch("sase.agent.names.claim_agent_name"),
        patch("sase.ace.agent_tags.update_agent_tag") as update_agent_tag,
    ):
        info = extract_directives_and_write_meta(
            "%name:taggy\n%group:sase-26\nDo work",
            str(workspace_dir),
            str(artifacts_dir),
            cl_name="legend-cl",
        )

    assert info.tag == "sase-26"
    assert json.loads((artifacts_dir / "agent_meta.json").read_text())["tag"] == (
        "sase-26"
    )
    update_agent_tag.assert_called_once_with(
        (AgentType.WORKFLOW, "legend-cl", "20260506120000"),
        "sase-26",
    )


def _mock_provider_config(
    monkeypatch: pytest.MonkeyPatch, cfg: dict[str, object]
) -> None:
    monkeypatch.setattr("sase.llm_provider.config.get_llm_provider_config", lambda: cfg)
    monkeypatch.setattr(
        "sase.llm_provider.registry.get_llm_provider_config", lambda: cfg
    )


def _extract_worker_model_meta(tmp_path: Path) -> dict[str, object]:
    workspace_dir = tmp_path / "workspace"
    artifacts_dir = tmp_path / "artifacts"
    workspace_dir.mkdir()
    artifacts_dir.mkdir()

    with (
        patch("sase.vcs_provider._registry.detect_vcs", return_value=None),
        patch("sase.agent.names.claim_agent_name"),
    ):
        extract_directives_and_write_meta(
            "%name:phase-worker\n%model:worker\nDo work",
            str(workspace_dir),
            str(artifacts_dir),
        )

    return json.loads((artifacts_dir / "agent_meta.json").read_text())


def test_worker_directive_metadata_prefers_worker_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_provider_config(
        monkeypatch,
        {"provider": "claude", "worker_model": "codex/gpt-5.5"},
    )
    set_temporary_override("codex/o3", 3600.0, source="test")
    set_temporary_override(
        "gemini/gemini-2.5-pro", 3600.0, source="test", role="worker"
    )

    meta = _extract_worker_model_meta(tmp_path)

    assert (meta["llm_provider"], meta["model"]) == ("gemini", "gemini-2.5-pro")


def test_worker_directive_metadata_uses_configured_worker_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_provider_config(
        monkeypatch,
        {"provider": "claude", "worker_model": "codex/gpt-5.5"},
    )
    set_temporary_override("claude/sonnet", 3600.0, source="test")

    meta = _extract_worker_model_meta(tmp_path)

    assert (meta["llm_provider"], meta["model"]) == ("codex", "gpt-5.5")


def test_worker_directive_metadata_falls_through_to_primary_lane(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_provider_config(monkeypatch, {"provider": "claude"})
    set_temporary_override("codex/o3", 3600.0, source="test")

    meta = _extract_worker_model_meta(tmp_path)

    assert (meta["llm_provider"], meta["model"]) == ("codex", "o3")
