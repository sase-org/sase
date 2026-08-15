"""Reasoning-effort metadata persistence tests."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


def test_agent_meta_persists_explicit_effort(tmp_path: Path) -> None:
    """An explicit ``%effort`` directive lands in ``agent_meta.json``."""
    from sase.axe.run_agent_phases import extract_directives_and_write_meta

    workspace_dir = str(tmp_path / "workspace")
    artifacts_dir = str(tmp_path / "artifacts")
    os.makedirs(workspace_dir, exist_ok=True)
    os.makedirs(artifacts_dir, exist_ok=True)

    extract_directives_and_write_meta(
        prompt="%effort:xhigh\ndo the work",
        workspace_dir=workspace_dir,
        artifacts_dir=artifacts_dir,
    )

    meta = json.loads(
        (tmp_path / "artifacts" / "agent_meta.json").read_text(encoding="utf-8")
    )
    assert meta["reasoning_effort"] == "xhigh"


def test_agent_meta_records_default_alias_for_plain_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A no-%model launch records the configured launch-default alias provenance."""
    from sase.axe.run_agent_phases import extract_directives_and_write_meta
    from tests._model_alias_defaults_fixture import (
        frozen_selector_provider_model_effort,
    )

    # Pin the config default to "unset" so the test is independent of the
    # developer's ~/.config/sase/sase.yml (which Phase 6 sets to xhigh).
    monkeypatch.setattr("sase.llm_provider.config._get_default_effort", lambda: None)

    workspace_dir = str(tmp_path / "workspace")
    artifacts_dir = str(tmp_path / "artifacts")
    os.makedirs(workspace_dir, exist_ok=True)
    os.makedirs(artifacts_dir, exist_ok=True)

    extract_directives_and_write_meta(
        prompt="just a plain prompt",
        workspace_dir=workspace_dir,
        artifacts_dir=artifacts_dir,
    )

    meta = json.loads(
        (tmp_path / "artifacts" / "agent_meta.json").read_text(encoding="utf-8")
    )
    provider, model, effort = frozen_selector_provider_model_effort("large", 0)
    assert (meta["llm_provider"], meta["model"], meta["reasoning_effort"]) == (
        provider,
        model,
        effort,
    )
    assert meta["model_alias"] == "large"


def test_agent_meta_default_alias_effort_beats_config_default_effort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Alias-borne launch-default effort wins before ``default_effort``."""
    from sase.axe.run_agent_phases import extract_directives_and_write_meta
    from tests._model_alias_defaults_fixture import (
        frozen_selector_provider_model_effort,
    )

    monkeypatch.setattr("sase.llm_provider.config._get_default_effort", lambda: "low")

    workspace_dir = str(tmp_path / "workspace")
    artifacts_dir = str(tmp_path / "artifacts")
    os.makedirs(workspace_dir, exist_ok=True)
    os.makedirs(artifacts_dir, exist_ok=True)

    extract_directives_and_write_meta(
        prompt="plain prompt",
        workspace_dir=workspace_dir,
        artifacts_dir=artifacts_dir,
    )

    meta = json.loads(
        (tmp_path / "artifacts" / "agent_meta.json").read_text(encoding="utf-8")
    )
    provider, model, effort = frozen_selector_provider_model_effort("large", 0)
    assert (meta["llm_provider"], meta["model"], meta["reasoning_effort"]) == (
        provider,
        model,
        effort,
    )
    assert meta["model_alias"] == "large"


def test_agent_meta_records_model_alias_and_launch_override_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Alias launches store the typed alias while model follows overrides."""
    from sase.axe.run_agent_phases import extract_directives_and_write_meta
    from sase.llm_provider import config as llm_config

    config = {
        "provider": "claude",
        "model_aliases": {"builtin": {"medium": "claude/sonnet"}},
    }
    monkeypatch.setattr(llm_config, "get_llm_provider_config", lambda: config)
    monkeypatch.setattr(
        "sase.llm_provider.registry.get_llm_provider_config", lambda: config
    )
    llm_config._get_model_aliases_for_token.cache_clear()

    workspace_dir = str(tmp_path / "workspace")
    artifacts_dir = str(tmp_path / "artifacts")
    os.makedirs(workspace_dir, exist_ok=True)
    os.makedirs(artifacts_dir, exist_ok=True)

    extract_directives_and_write_meta(
        prompt="%m(@medium, medium=codex/gpt-5)\ndo the work",
        workspace_dir=workspace_dir,
        artifacts_dir=artifacts_dir,
    )

    meta = json.loads(
        (tmp_path / "artifacts" / "agent_meta.json").read_text(encoding="utf-8")
    )
    assert meta["model_alias"] == "medium"
    assert (meta["llm_provider"], meta["model"]) == ("codex", "gpt-5")


def test_agent_meta_omits_model_alias_for_concrete_model(
    tmp_path: Path,
) -> None:
    from sase.axe.run_agent_phases import extract_directives_and_write_meta

    workspace_dir = str(tmp_path / "workspace")
    artifacts_dir = str(tmp_path / "artifacts")
    os.makedirs(workspace_dir, exist_ok=True)
    os.makedirs(artifacts_dir, exist_ok=True)

    extract_directives_and_write_meta(
        prompt="%model:claude/opus\ndo the work",
        workspace_dir=workspace_dir,
        artifacts_dir=artifacts_dir,
    )

    meta = json.loads(
        (tmp_path / "artifacts" / "agent_meta.json").read_text(encoding="utf-8")
    )
    assert "model_alias" not in meta


def test_agent_meta_previews_alias_pool_without_consuming_and_resume_reuses_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The axe metadata lane only previews the pool; a re-exec reuses the
    preserved selection without re-resolving. The pool's cursor only
    advances when the anonymous workflow's prompt step performs the real,
    consuming resolution immediately before invoking the provider."""
    from sase.axe.run_agent_phases import extract_directives_and_write_meta
    from sase.llm_provider import config as llm_config

    monkeypatch.setattr(
        llm_config,
        "get_llm_provider_config",
        lambda: {
            "provider": "claude",
            "model_aliases": {
                "custom": {
                    "pool": {
                        "model": "claude/opus@medium | codex/gpt-5.5",
                        "description": "Test pool.",
                    }
                }
            },
        },
    )
    monkeypatch.setattr(
        "sase.llm_provider.registry.get_llm_provider_config",
        llm_config.get_llm_provider_config,
    )
    monkeypatch.setattr(
        llm_config, "_resolved_target_is_available", lambda _target: True
    )
    llm_config._get_model_aliases_for_token.cache_clear()

    workspace_dir = str(tmp_path / "workspace")
    first_artifacts = str(tmp_path / "first")
    second_artifacts = str(tmp_path / "second")
    os.makedirs(workspace_dir, exist_ok=True)
    os.makedirs(first_artifacts, exist_ok=True)
    os.makedirs(second_artifacts, exist_ok=True)

    prompt = "%model:@pool\ndo the work"
    extract_directives_and_write_meta(
        prompt=prompt,
        workspace_dir=workspace_dir,
        artifacts_dir=first_artifacts,
    )
    # Simulate the same runner re-executing after a wait/resume boundary.
    extract_directives_and_write_meta(
        prompt=prompt,
        workspace_dir=workspace_dir,
        artifacts_dir=first_artifacts,
    )
    first = json.loads(
        (Path(first_artifacts) / "agent_meta.json").read_text(encoding="utf-8")
    )
    assert (first["llm_provider"], first["model"], first["reasoning_effort"]) == (
        "claude",
        "opus",
        "medium",
    )
    assert first["model_alias"] == "pool"

    # A second, independent launch's metadata preview sees the same
    # unconsumed cursor position as the first, since neither call is a real
    # invocation.
    extract_directives_and_write_meta(
        prompt=prompt,
        workspace_dir=workspace_dir,
        artifacts_dir=second_artifacts,
    )
    second = json.loads(
        (Path(second_artifacts) / "agent_meta.json").read_text(encoding="utf-8")
    )
    assert (second["llm_provider"], second["model"], second["reasoning_effort"]) == (
        "claude",
        "opus",
        "medium",
    )
    assert second["model_alias"] == "pool"


def test_agent_meta_default_lane_previews_pool_without_consuming(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The implicit default launch lane previews the pool but never advances
    its shared cursor; only a real invocation does that (see
    ``test_workflow_executor.py`` for the composed, consuming path)."""
    from sase.axe.run_agent_phases import extract_directives_and_write_meta
    from sase.llm_provider import config as llm_config
    from sase.llm_provider.model_alias_policy import LARGE_MODEL_ALIAS_NAME
    from tests._model_alias_defaults_fixture import (
        frozen_selector_provider_model_effort,
    )

    config = {"provider": "claude"}
    monkeypatch.setattr(llm_config, "get_llm_provider_config", lambda: config)
    monkeypatch.setattr(
        "sase.llm_provider.registry.get_llm_provider_config", lambda: config
    )
    monkeypatch.setattr(
        llm_config,
        "_resolved_target_is_available",
        lambda _target: True,
    )
    llm_config._get_model_aliases_for_token.cache_clear()

    workspace_dir = str(tmp_path / "workspace")
    first_artifacts = str(tmp_path / "first")
    second_artifacts = str(tmp_path / "second")
    os.makedirs(workspace_dir, exist_ok=True)
    os.makedirs(first_artifacts, exist_ok=True)
    os.makedirs(second_artifacts, exist_ok=True)
    state_path = Path.home() / ".sase" / "llm_lb.json"

    def cursor() -> int:
        if not state_path.exists():
            return 0
        state = json.loads(state_path.read_text(encoding="utf-8"))
        return int(state["entries"][LARGE_MODEL_ALIAS_NAME]["cursor"])

    extract_directives_and_write_meta(
        prompt="do the work",
        workspace_dir=workspace_dir,
        artifacts_dir=first_artifacts,
    )
    first = json.loads(
        (Path(first_artifacts) / "agent_meta.json").read_text(encoding="utf-8")
    )
    first_provider, first_model, first_effort = frozen_selector_provider_model_effort(
        LARGE_MODEL_ALIAS_NAME, 0
    )
    assert (first["llm_provider"], first["model"], first["reasoning_effort"]) == (
        first_provider,
        first_model,
        first_effort,
    )
    assert first["model_alias"] == "large"
    assert cursor() == 0

    extract_directives_and_write_meta(
        prompt="do the work",
        workspace_dir=workspace_dir,
        artifacts_dir=first_artifacts,
    )
    preserved = json.loads(
        (Path(first_artifacts) / "agent_meta.json").read_text(encoding="utf-8")
    )
    assert preserved["model_alias"] == "large"
    assert (preserved["llm_provider"], preserved["model"]) == (
        first_provider,
        first_model,
    )
    assert cursor() == 0

    # A second, independent launch's preview also sees member 0: previewing
    # never advances the cursor, regardless of how many previews run.
    extract_directives_and_write_meta(
        prompt="do the work",
        workspace_dir=workspace_dir,
        artifacts_dir=second_artifacts,
    )
    second = json.loads(
        (Path(second_artifacts) / "agent_meta.json").read_text(encoding="utf-8")
    )
    assert (second["llm_provider"], second["model"], second["reasoning_effort"]) == (
        first_provider,
        first_model,
        first_effort,
    )
    assert second["model_alias"] == "large"
    assert cursor() == 0


def test_step_marker_persists_and_preserves_effort(tmp_path: Path) -> None:
    """The step marker stores ``reasoning_effort`` and preserves it on rewrite."""
    from sase.xprompt.workflow_executor import WorkflowExecutor
    from sase.xprompt.workflow_models import (
        StepState,
        StepStatus,
        Workflow,
        WorkflowStep,
    )

    step = WorkflowStep(name="s1", agent="do it")
    workflow = Workflow(name="wf", steps=[step])
    executor = WorkflowExecutor(workflow=workflow, args={}, artifacts_dir=str(tmp_path))

    state = StepState(name="s1", status=StepStatus.IN_PROGRESS)
    executor._save_prompt_step_marker(
        "s1",
        state,
        model="opus",
        llm_provider="claude",
        reasoning_effort="xhigh",
        model_alias="medium",
    )

    marker_path = tmp_path / "prompt_step_s1.json"
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    assert marker["reasoning_effort"] == "xhigh"
    assert marker["model_alias"] == "medium"

    # A later rewrite that does not re-pass the effort keeps the stored value
    # (mirrors model/llm_provider preservation).
    state.status = StepStatus.COMPLETED
    executor._save_prompt_step_marker("s1", state)
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    assert marker["reasoning_effort"] == "xhigh"
    assert marker["model_alias"] == "medium"
