"""Agent metadata integration for temporary LLM overrides."""

from __future__ import annotations

import json
import os

import pytest

from sase.llm_provider.temporary_override import (
    clear_temporary_override,
    set_temporary_override,
)


def test_agent_meta_frozen_after_later_override_change(tmp_path) -> None:
    """Changing the override later does not rewrite existing agent meta."""
    from sase.axe.run_agent_phases import extract_directives_and_write_meta

    workspace_dir = str(tmp_path / "workspace")
    artifacts_dir = str(tmp_path / "artifacts")
    os.makedirs(workspace_dir, exist_ok=True)
    os.makedirs(artifacts_dir, exist_ok=True)

    set_temporary_override("codex/o3", 3600.0, source="test")
    extract_directives_and_write_meta(
        prompt="just a plain prompt",
        workspace_dir=workspace_dir,
        artifacts_dir=artifacts_dir,
    )

    meta_path = tmp_path / "artifacts" / "agent_meta.json"
    original = json.loads(meta_path.read_text(encoding="utf-8"))
    assert original["llm_provider"] == "codex"
    assert original["model"] == "o3"
    original_mtime = meta_path.stat().st_mtime_ns

    set_temporary_override("opus", 60.0, source="test")
    clear_temporary_override()

    after = json.loads(meta_path.read_text(encoding="utf-8"))
    assert after == original
    assert meta_path.stat().st_mtime_ns == original_mtime


def test_agent_meta_after_clear_uses_configured_default_provider(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The next launch after clear resolves through the default alias."""
    from sase.axe.run_agent_phases import extract_directives_and_write_meta
    from sase.llm_provider import config as llm_config
    from sase.llm_provider.model_alias_policy import SMARTER_MODEL_ALIAS_NAME
    from tests._model_alias_defaults_fixture import (
        frozen_selector_provider_model_effort,
    )

    config = {"provider": "claude"}
    monkeypatch.setattr(llm_config, "get_llm_provider_config", lambda: config)
    monkeypatch.setattr(
        "sase.llm_provider.registry.get_llm_provider_config",
        lambda: config,
    )
    monkeypatch.setattr(
        llm_config,
        "_resolved_target_is_available",
        lambda _target: True,
    )
    llm_config._get_model_aliases_for_token.cache_clear()

    workspace_dir = str(tmp_path / "workspace")
    artifacts_a = tmp_path / "a"
    artifacts_b = tmp_path / "b"
    os.makedirs(workspace_dir, exist_ok=True)
    artifacts_a.mkdir()
    artifacts_b.mkdir()

    set_temporary_override("codex/o3", 3600.0, source="test")
    extract_directives_and_write_meta(
        prompt="a", workspace_dir=workspace_dir, artifacts_dir=str(artifacts_a)
    )
    clear_temporary_override()
    extract_directives_and_write_meta(
        prompt="b", workspace_dir=workspace_dir, artifacts_dir=str(artifacts_b)
    )

    meta_a = json.loads((artifacts_a / "agent_meta.json").read_text(encoding="utf-8"))
    meta_b = json.loads((artifacts_b / "agent_meta.json").read_text(encoding="utf-8"))

    assert (meta_a["llm_provider"], meta_a["model"]) == ("codex", "o3")
    provider, model, effort = frozen_selector_provider_model_effort(
        SMARTER_MODEL_ALIAS_NAME, 0
    )
    assert (meta_b["llm_provider"], meta_b["model"]) == (provider, model)
    assert meta_b["reasoning_effort"] == effort
    assert meta_b["model_alias"] == "default"
    assert (meta_b["llm_provider"], meta_b["model"]) != ("codex", "o3")


def test_agent_meta_until_cleared_override_records_provider(tmp_path) -> None:
    """An until-cleared override is active at metadata-resolution time."""
    from sase.axe.run_agent_phases import extract_directives_and_write_meta

    workspace_dir = str(tmp_path / "workspace")
    artifacts_dir = str(tmp_path / "artifacts")
    os.makedirs(workspace_dir, exist_ok=True)
    os.makedirs(artifacts_dir, exist_ok=True)

    set_temporary_override("codex/o3", None, source="test")
    extract_directives_and_write_meta(
        prompt="prompt",
        workspace_dir=workspace_dir,
        artifacts_dir=artifacts_dir,
    )

    meta = json.loads(
        (tmp_path / "artifacts" / "agent_meta.json").read_text(encoding="utf-8")
    )
    assert meta["llm_provider"] == "codex"
    assert meta["model"] == "o3"


def test_launch_alias_overrides_persist_to_meta_and_process_env(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import patch

    from sase.axe.run_agent_phases import extract_directives_and_write_meta
    from sase.llm_provider.launch_alias_overrides import (
        SASE_MODEL_ALIAS_OVERRIDES_ENV,
    )

    workspace_dir = tmp_path / "workspace"
    artifacts_dir = tmp_path / "artifacts"
    workspace_dir.mkdir()
    artifacts_dir.mkdir()
    monkeypatch.delenv(SASE_MODEL_ALIAS_OVERRIDES_ENV, raising=False)

    with (
        patch("sase.vcs_provider._registry.detect_vcs", return_value=None),
        patch("sase.agent.names.claim_agent_name"),
    ):
        extract_directives_and_write_meta(
            prompt="%m(opus, medium_worker=sonnet)\nDo work",
            workspace_dir=str(workspace_dir),
            artifacts_dir=str(artifacts_dir),
        )

    meta = json.loads((artifacts_dir / "agent_meta.json").read_text())
    assert meta["model_alias_overrides"] == {"medium_worker": "sonnet"}
    assert json.loads(os.environ[SASE_MODEL_ALIAS_OVERRIDES_ENV]) == {
        "medium_worker": "sonnet"
    }
