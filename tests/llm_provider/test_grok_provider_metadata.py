"""GrokProvider registration, metadata, and retry-config tests."""

from __future__ import annotations

import pytest

from sase.ace.tui.provider_styles import provider_emoji_badge
from sase.llm_provider.base import LLMProvider
from sase.llm_provider.grok import GrokProvider
from sase.llm_provider.registry import (
    provider_cli_status_color_map,
    resolve_model_provider,
)
from sase.llm_provider.retry_config import (
    find_retry_config_for_error,
    is_retryable_error,
)

from ._grok_provider_core_helpers import clear_grok_env_vars

# Captured live from ace(run)-260904_135714 (grok-4.6, effort xhigh, turn 55):
# the Grok Build CLI aborted the whole session with exit code 1 and this
# internal-error JSON payload on stderr.
_GROK_MAX_TOKENS_TRUNCATION_ERROR = (
    "Error running LLM provider command (exit code 1)\n"
    "Error: Internal error: {\n"
    '  "message": "response truncated by max_tokens",\n'
    '  "error_kind": "max_tokens_truncation"\n'
    "}"
)


@pytest.fixture(autouse=True)
def _clear_grok_env(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_grok_env_vars(monkeypatch)


def test_grok_provider_is_llm_provider() -> None:
    assert isinstance(GrokProvider(), LLMProvider)


def test_grok_provider_is_registered_as_an_entry_point() -> None:
    provider, model = resolve_model_provider("grok/grok-4.7")
    assert provider == "grok"
    assert model == "grok-4.7"

    provider, model = resolve_model_provider("grok/grok-4.6")
    assert provider == "grok"
    assert model == "grok-4.6"


def test_grok_known_model_resolves_implicitly() -> None:
    provider, model = resolve_model_provider("grok-4.7")
    assert provider == "grok"
    assert model == "grok-4.7"

    provider, model = resolve_model_provider("grok-4.6")
    assert provider == "grok"
    assert model == "grok-4.6"


def test_grok_provider_metadata_hooks() -> None:
    provider = GrokProvider()
    assert provider.llm_provider_name() == "grok"
    assert provider.llm_provider_short_name() == "grk"
    assert provider.llm_autodetect_cli_name() == "grok"
    assert provider.llm_cli_status_color() == "#00C8D7"
    assert provider.llm_known_model_names() == ["grok-4.7", "grok-4.6"]
    assert provider.llm_skill_template_context() == {
        "provider_name": "Grok",
        "provider_tool_name": "Grok Build",
        "provider_native_ask_tool": "ask_user_question",
    }
    assert provider.llm_auth_evidence() == {
        "credential_paths": ["~/.grok/auth.json"],
        "api_key_env_vars": ["XAI_API_KEY"],
    }


def test_grok_provider_surface_metadata_is_registered() -> None:
    assert provider_cli_status_color_map()["grok"] == "#00C8D7"
    assert provider_emoji_badge("grok") == "🚀"
    assert provider_emoji_badge("xai") == "🚀"


def test_grok_provider_has_no_autodetect_priority() -> None:
    """`grok` is a contested executable name; PATH presence is explicit-only."""
    assert not hasattr(GrokProvider, "llm_autodetect_priority")


def test_grok_install_metadata_declares_npm_package_and_self_update() -> None:
    metadata = GrokProvider().llm_install_metadata()
    assert metadata["manager"] == "npm"
    assert metadata["package"] == "@xai-official/grok"
    assert metadata["scope"] == "global"
    assert metadata["display_name"] == "Grok Build"
    assert metadata["docs_url"] == "https://docs.x.ai/build/overview"
    assert metadata["self_update_argv"] == ["update"]
    assert metadata["latest_version_package"] == "@xai-official/grok"


def test_grok_retry_config_uses_xai_specific_patterns() -> None:
    config = GrokProvider().llm_default_retry_config()
    assert config.max_retries == 3
    assert config.wait_times == [60, 300, 1800]
    assert config.preserve_workspace is True
    xai_patterns = {
        "xAI API error",
        "xAI rate limit",
        "xAI server error",
        "xAI upstream request failed",
    }
    assert xai_patterns.issubset(config.error_patterns)


def test_grok_retry_config_retries_max_tokens_truncation() -> None:
    config = GrokProvider().llm_default_retry_config()
    assert "max_tokens_truncation" in config.error_patterns
    assert "response truncated by max_tokens" in config.error_patterns
    assert is_retryable_error(_GROK_MAX_TOKENS_TRUNCATION_ERROR, config) is True


def test_grok_max_tokens_truncation_error_found_via_cross_provider_lookup() -> None:
    """Guards the lookup path `handle_workflow_error` actually uses."""
    config = find_retry_config_for_error(_GROK_MAX_TOKENS_TRUNCATION_ERROR)
    assert config is not None
    assert is_retryable_error(_GROK_MAX_TOKENS_TRUNCATION_ERROR, config) is True


def test_grok_provider_resolve_model_name_maps_tiers_to_their_models() -> None:
    provider = GrokProvider()
    assert provider.resolve_model_name() == "grok-4.7"
    assert provider.resolve_model_name("large") == "grok-4.7"
    assert provider.resolve_model_name("small") == "grok-4.6"
