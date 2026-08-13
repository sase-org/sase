"""Phase 2 tests: temporary override applied to provider resolution and metadata.

The lower-level temporary override tests verify the shared state primitive and
provider/model resolution helpers in isolation.  Phase 2 verifies that the rest
of the system actually *consults* those helpers — at provider resolution, agent
invocation, and agent metadata pre-resolution paths.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from sase.llm_provider._invoke import invoke_agent
from sase.llm_provider.preprocessing import PreprocessResult
from sase.llm_provider.registry import get_default_provider_name
from sase.llm_provider.temporary_override import (
    set_alias_override,
    set_temporary_override,
)
from sase.llm_provider.types import InvokeResult, LLMInvocationOptions
from sase.xprompt.directives import PromptDirectives

_NO_EFFORT = LLMInvocationOptions(reasoning_effort=None, explicit=False)


# ---------------------------------------------------------------------------
# get_default_provider_name() honors active override
# ---------------------------------------------------------------------------


def test_get_default_provider_name_uses_override() -> None:
    set_temporary_override("codex/o3", 3600.0, source="test")
    assert get_default_provider_name() == "codex"


def test_get_default_provider_name_falls_through_when_no_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.llm_provider.registry.get_llm_provider_config",
        lambda: {"provider": "claude"},
    )

    assert get_default_provider_name() == "claude"


def test_get_default_provider_name_ignores_expired_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json
    import time

    from sase.llm_provider.temporary_override import _state_path

    monkeypatch.setattr(
        "sase.llm_provider.registry.get_llm_provider_config",
        lambda: {"provider": "claude"},
    )

    set_temporary_override("codex/o3", 60.0, source="test")
    path = _state_path()
    data = json.loads(path.read_text(encoding="utf-8"))
    data["overrides"]["default"]["expires_at"] = time.time() - 1
    path.write_text(json.dumps(data), encoding="utf-8")

    assert get_default_provider_name() == "claude"


# ---------------------------------------------------------------------------
# invoke_agent() default path uses override
# ---------------------------------------------------------------------------


@patch("sase.llm_provider._invoke.get_provider")
@patch("sase.llm_provider._invoke.preprocess_prompt")
@patch("sase.llm_provider._invoke.postprocess_success")
def test_invoke_agent_applies_active_override(
    _mock_postprocess: MagicMock,
    mock_preprocess: MagicMock,
    mock_get_provider: MagicMock,
) -> None:
    """When no %model and no provider_name, active override drives both."""
    mock_preprocess.return_value = PreprocessResult(prompt="preprocessed prompt")
    mock_provider = MagicMock()
    mock_provider.invoke.return_value = InvokeResult(content="response")
    mock_get_provider.return_value = mock_provider

    set_temporary_override("codex/o3", 3600.0, source="test")
    invoke_agent("prompt", agent_type="test", suppress_output=True)

    # provider_name resolved from override
    mock_get_provider.assert_called_once_with("codex")
    # model_override threaded through to provider.invoke()
    mock_provider.invoke.assert_called_once_with(
        "preprocessed prompt",
        model_tier="large",
        suppress_output=True,
        model_override="o3",
        options=_NO_EFFORT,
    )


@patch("sase.llm_provider._invoke.get_provider")
@patch("sase.llm_provider._invoke.preprocess_prompt")
@patch("sase.llm_provider._invoke.postprocess_success")
def test_invoke_agent_applies_default_override_effort(
    _mock_postprocess: MagicMock,
    mock_preprocess: MagicMock,
    mock_get_provider: MagicMock,
) -> None:
    mock_preprocess.return_value = PreprocessResult(prompt="preprocessed prompt")
    mock_provider = MagicMock()
    mock_provider.invoke.return_value = InvokeResult(content="response")
    mock_get_provider.return_value = mock_provider

    set_temporary_override("codex/o3@medium", 3600.0, source="test")
    invoke_agent("prompt", agent_type="test", suppress_output=True)

    mock_provider.invoke.assert_called_once_with(
        "preprocessed prompt",
        model_tier="large",
        suppress_output=True,
        model_override="o3",
        options=LLMInvocationOptions(reasoning_effort="medium", explicit=False),
    )


@patch("sase.llm_provider._invoke.get_provider")
@patch("sase.llm_provider._invoke.preprocess_prompt")
@patch("sase.llm_provider._invoke.postprocess_success")
def test_invoke_agent_applies_nondefault_alias_override_effort(
    _mock_postprocess: MagicMock,
    mock_preprocess: MagicMock,
    mock_get_provider: MagicMock,
) -> None:
    mock_preprocess.return_value = PreprocessResult(
        prompt="preprocessed prompt",
        directives=PromptDirectives(model="@medium_worker"),
    )
    mock_provider = MagicMock()
    mock_provider.invoke.return_value = InvokeResult(content="response")
    mock_get_provider.return_value = mock_provider

    set_alias_override("medium_worker", "codex/o3@medium", 3600.0, source="test")
    invoke_agent("prompt", agent_type="test", suppress_output=True)

    mock_get_provider.assert_called_once_with("codex")
    mock_provider.invoke.assert_called_once_with(
        "preprocessed prompt",
        model_tier="large",
        suppress_output=True,
        model_override="o3",
        options=LLMInvocationOptions(reasoning_effort="medium", explicit=False),
    )


@patch("sase.llm_provider._invoke.get_provider")
@patch("sase.llm_provider._invoke.preprocess_prompt")
@patch("sase.llm_provider._invoke.postprocess_success")
def test_invoke_agent_prompt_directive_beats_override(
    _mock_postprocess: MagicMock,
    mock_preprocess: MagicMock,
    mock_get_provider: MagicMock,
) -> None:
    """An explicit %model in the prompt always wins over the temp override."""
    mock_preprocess.return_value = PreprocessResult(
        prompt="preprocessed",
        directives=PromptDirectives(model="opus"),  # → claude/opus
    )
    mock_provider = MagicMock()
    mock_provider.invoke.return_value = InvokeResult(content="response")
    mock_get_provider.return_value = mock_provider

    set_temporary_override("codex/o3", 3600.0, source="test")
    invoke_agent("prompt", agent_type="test", suppress_output=True)

    # Resolved from %model directive, NOT from override.
    mock_get_provider.assert_called_once_with("claude")
    mock_provider.invoke.assert_called_once_with(
        "preprocessed",
        model_tier="large",
        suppress_output=True,
        model_override="opus",
        options=_NO_EFFORT,
    )


@patch("sase.llm_provider._invoke.get_provider")
@patch("sase.llm_provider._invoke.preprocess_prompt")
@patch("sase.llm_provider._invoke.postprocess_success")
def test_invoke_agent_explicit_provider_name_beats_override(
    _mock_postprocess: MagicMock,
    mock_preprocess: MagicMock,
    mock_get_provider: MagicMock,
) -> None:
    """An explicit provider_name argument wins over the temp override."""
    mock_preprocess.return_value = PreprocessResult(prompt="preprocessed")
    mock_provider = MagicMock()
    mock_provider.invoke.return_value = InvokeResult(content="response")
    mock_get_provider.return_value = mock_provider

    set_temporary_override("codex/o3", 3600.0, source="test")
    invoke_agent(
        "prompt",
        agent_type="test",
        suppress_output=True,
        provider_name="claude",
    )

    # Caller's explicit provider preserved; no override model applied.
    mock_get_provider.assert_called_once_with("claude")
    mock_provider.invoke.assert_called_once_with(
        "preprocessed",
        model_tier="large",
        suppress_output=True,
        model_override=None,
        options=_NO_EFFORT,
    )


@patch("sase.llm_provider._invoke.get_provider")
@patch("sase.llm_provider._invoke.preprocess_prompt")
@patch("sase.llm_provider._invoke.postprocess_success")
def test_invoke_agent_expired_override_ignored(
    _mock_postprocess: MagicMock,
    mock_preprocess: MagicMock,
    mock_get_provider: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An expired override is ignored and the launch uses ``@default``."""
    import json
    import time

    from sase.llm_provider import config as llm_config
    from sase.llm_provider.model_alias_policy import SMARTER_MODEL_ALIAS_NAME
    from sase.llm_provider.temporary_override import _state_path
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

    mock_preprocess.return_value = PreprocessResult(prompt="preprocessed")
    mock_provider = MagicMock()
    mock_provider.invoke.return_value = InvokeResult(content="response")
    mock_get_provider.return_value = mock_provider

    set_temporary_override("codex/o3", 60.0, source="test")
    path = _state_path()
    data = json.loads(path.read_text(encoding="utf-8"))
    data["overrides"]["default"]["expires_at"] = time.time() - 1
    path.write_text(json.dumps(data), encoding="utf-8")

    invoke_agent("prompt", agent_type="test", suppress_output=True)

    provider, model, effort = frozen_selector_provider_model_effort(
        SMARTER_MODEL_ALIAS_NAME, 0
    )
    mock_get_provider.assert_called_once_with(provider)
    mock_provider.invoke.assert_called_once_with(
        "preprocessed",
        model_tier="large",
        suppress_output=True,
        model_override=model,
        options=LLMInvocationOptions(reasoning_effort=effort, explicit=False),
    )


# ---------------------------------------------------------------------------
# Agent metadata pre-resolution honors override
# ---------------------------------------------------------------------------


def test_extract_directives_records_override_in_meta(tmp_path) -> None:
    """``run_agent_phases.extract_directives_and_write_meta`` must record the
    override's provider/model in agent_meta.json when there's no %model.
    """
    import json

    from sase.axe.run_agent_phases import extract_directives_and_write_meta

    workspace_dir = str(tmp_path / "workspace")
    artifacts_dir = str(tmp_path / "artifacts")
    import os

    os.makedirs(workspace_dir, exist_ok=True)
    os.makedirs(artifacts_dir, exist_ok=True)

    set_temporary_override("codex/o3", 3600.0, source="test")
    extract_directives_and_write_meta(
        prompt="just a plain prompt",
        workspace_dir=workspace_dir,
        artifacts_dir=artifacts_dir,
    )

    meta = json.loads(
        (tmp_path / "artifacts" / "agent_meta.json").read_text(encoding="utf-8")
    )
    assert meta["llm_provider"] == "codex"
    assert meta["model"] == "o3"


def test_extract_directives_records_default_override_effort_in_meta(tmp_path) -> None:
    import json
    import os

    from sase.axe.run_agent_phases import extract_directives_and_write_meta

    workspace_dir = str(tmp_path / "workspace")
    artifacts_dir = str(tmp_path / "artifacts")
    os.makedirs(workspace_dir, exist_ok=True)
    os.makedirs(artifacts_dir, exist_ok=True)

    set_temporary_override("codex/o3@medium", 3600.0, source="test")
    extract_directives_and_write_meta(
        prompt="just a plain prompt",
        workspace_dir=workspace_dir,
        artifacts_dir=artifacts_dir,
    )

    meta = json.loads(
        (tmp_path / "artifacts" / "agent_meta.json").read_text(encoding="utf-8")
    )
    assert meta["llm_provider"] == "codex"
    assert meta["model"] == "o3"
    assert meta["reasoning_effort"] == "medium"


def test_extract_directives_prompt_model_beats_override(tmp_path) -> None:
    """An explicit %model in the prompt overrides the temp override in metadata."""
    import json
    import os

    from sase.axe.run_agent_phases import extract_directives_and_write_meta

    workspace_dir = str(tmp_path / "workspace")
    artifacts_dir = str(tmp_path / "artifacts")
    os.makedirs(workspace_dir, exist_ok=True)
    os.makedirs(artifacts_dir, exist_ok=True)

    set_temporary_override("codex/o3", 3600.0, source="test")
    extract_directives_and_write_meta(
        prompt="%model:opus\nplain prompt",
        workspace_dir=workspace_dir,
        artifacts_dir=artifacts_dir,
    )

    meta = json.loads(
        (tmp_path / "artifacts" / "agent_meta.json").read_text(encoding="utf-8")
    )
    assert meta["llm_provider"] == "claude"
    assert meta["model"] == "opus"
