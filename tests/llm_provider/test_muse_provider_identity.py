"""MuseProvider identity, registration, and model-mapping tests."""

from __future__ import annotations

import pytest

from sase.ace.tui.provider_styles import provider_emoji_badge
from sase.llm_provider.base import LLMProvider
from sase.llm_provider.muse import MuseProvider
from sase.llm_provider.registry import resolve_model_provider

from ._muse_provider_helpers import _MUSE_MODELS


def test_muse_provider_is_llm_provider() -> None:
    assert isinstance(MuseProvider(), LLMProvider)


def test_muse_provider_is_registered_as_an_entry_point() -> None:
    provider, model = resolve_model_provider("muse/muse-spark-1.3")
    assert provider == "muse"
    assert model == "muse-spark-1.3"


@pytest.mark.parametrize(
    "model", ["muse-spark-1.3", "muse-spark-1.2-contributor", "muse-spark-1.1"]
)
def test_muse_known_models_resolve_implicitly(model: str) -> None:
    provider, resolved_model = resolve_model_provider(model)
    assert provider == "muse"
    assert resolved_model == model


def test_muse_provider_metadata_hooks() -> None:
    provider = MuseProvider()
    assert provider.llm_provider_name() == "muse"
    assert provider.llm_provider_short_name() == "mus"
    assert provider.llm_autodetect_cli_name() == "muse"
    assert provider.llm_skill_deploy_subpath() == ".config/muse"
    assert provider.llm_cli_status_color() == "#3D9BFF"
    assert provider.llm_known_model_names() == _MUSE_MODELS
    assert provider.llm_model_short_aliases() == {
        "muse-spark-1.3": "spark13",
        "muse-spark-1.3-contributor": "spark13c",
        "muse-spark-1.2": "spark12",
        "muse-spark-1.2-contributor": "spark12c",
        "muse-spark-1.1": "spark11",
    }
    context = provider.llm_skill_template_context()
    assert context["provider_name"] == "Muse Code"
    assert context["provider_tool_name"] == "Muse Code"
    assert context["provider_native_ask_tool"] == "request_user_input"
    assert provider.llm_auth_evidence() == {
        "credential_paths": ["$MUSE_AUTH_PATH", "~/.config/muse/auth.json"],
        "api_key_env_vars": ["META_API_KEY"],
    }


def test_muse_provider_has_no_autodetect_priority() -> None:
    """`muse` is a generic binary name; PATH presence must not win the default."""
    assert not hasattr(MuseProvider, "llm_autodetect_priority")


def test_muse_provider_surface_metadata_is_registered() -> None:
    assert provider_emoji_badge("muse") == "🦋"
    assert provider_emoji_badge("meta") == "🦋"
    assert "\ufe0f" not in (provider_emoji_badge("muse") or "")
    assert "\ufe0f" not in (provider_emoji_badge("meta") or "")


def test_muse_provider_resolve_model_name_never_routes_a_tier_to_contributor() -> None:
    """Both tiers map to the paid model; `small` phases route to `@small` directly."""
    provider = MuseProvider()
    assert provider.resolve_model_name() == "muse-spark-1.3"
    assert provider.resolve_model_name("large") == "muse-spark-1.3"
    assert provider.resolve_model_name("small") == "muse-spark-1.3"


def test_muse_install_metadata_declares_channel_and_script_install() -> None:
    metadata = MuseProvider().llm_install_metadata()
    assert metadata["manager"] == "script"
    assert metadata["display_name"] == "Muse Code"
    assert metadata["version_argv"] == ["--version"]
    assert metadata["version_compare"] == "exact"
    assert (
        metadata["latest_version_url"]
        == "https://api.meta.ai/muse-code/channels/muse-stable"
    )
    assert metadata["latest_version_json_field"] == "version"
    assert metadata["self_update_argv"] == ["--version"]
    assert metadata["self_update_env"] == {"MUSE_SYNC_UPDATE": "1"}
    assert metadata["install_script_url"] == "https://dev.meta.ai/install.sh"
    assert metadata["install_env"] == {"MUSE_UPGRADE_MODE": "1"}


def test_muse_version_regex_extracts_the_release_id() -> None:
    """`muse --version` prints `Muse Code 0.1.0 (0.1.0-R708.1)`."""
    import re

    pattern = MuseProvider().llm_install_metadata()["version_regex"]
    assert isinstance(pattern, str)
    match = re.search(pattern, "Muse Code 0.1.0 (0.1.0-R708.1)")
    assert match is not None
    assert match.group("version") == "0.1.0-R708.1"


def test_muse_setup_fallback_is_published_for_doctor() -> None:
    from sase.doctor.checks_providers import _PROVIDER_SETUP_FALLBACKS

    fallback = _PROVIDER_SETUP_FALLBACKS["muse"]
    assert fallback["tool"] == "Muse Code"
    assert "META_API_KEY" in fallback["auth"]
