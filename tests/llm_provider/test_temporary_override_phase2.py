"""Phase 2 tests: temporary override applied to provider resolution and metadata.

Phase 1 (``test_temporary_override.py``) verifies the shared state primitive
in isolation.  Phase 2 verifies that the rest of the system actually
*consults* that primitive — at provider resolution, agent invocation, and
agent metadata pre-resolution paths.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from sase.llm_provider._invoke import invoke_agent
from sase.llm_provider.preprocessing import PreprocessResult
from sase.llm_provider.registry import get_default_provider_name
from sase.llm_provider.temporary_override import set_temporary_override
from sase.llm_provider.types import InvokeResult
from sase.xprompt.directives import PromptDirectives


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
    data["expires_at"] = time.time() - 1
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
    )


@patch("sase.llm_provider._invoke.get_provider")
@patch("sase.llm_provider._invoke.preprocess_prompt")
@patch("sase.llm_provider._invoke.postprocess_success")
def test_invoke_agent_expired_override_ignored(
    _mock_postprocess: MagicMock,
    mock_preprocess: MagicMock,
    mock_get_provider: MagicMock,
) -> None:
    """An expired override is ignored — invocation uses configured default."""
    import json
    import time

    from sase.llm_provider.temporary_override import _state_path

    mock_preprocess.return_value = PreprocessResult(prompt="preprocessed")
    mock_provider = MagicMock()
    mock_provider.invoke.return_value = InvokeResult(content="response")
    mock_get_provider.return_value = mock_provider

    set_temporary_override("codex/o3", 60.0, source="test")
    path = _state_path()
    data = json.loads(path.read_text(encoding="utf-8"))
    data["expires_at"] = time.time() - 1
    path.write_text(json.dumps(data), encoding="utf-8")

    invoke_agent("prompt", agent_type="test", suppress_output=True)

    # No model_override applied; provider falls through to default (None → autodetect).
    mock_get_provider.assert_called_once_with(None)
    mock_provider.invoke.assert_called_once_with(
        "preprocessed",
        model_tier="large",
        suppress_output=True,
        model_override=None,
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
