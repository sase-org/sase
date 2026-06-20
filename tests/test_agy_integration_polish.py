"""Cross-provider integration coverage for the Antigravity (agy) provider.

Phase 3 wires ``agy`` into SASE's provider ecosystem (registry metadata,
doctor, retry defaults, and TUI surfaces) the same way Claude, Codex, Qwen,
and OpenCode are. These tests exercise the provider-neutral seams with an
exact ``agy`` model whose display name contains spaces and parentheses
(``"Gemini 3.5 Flash (High)"``), which is the case most likely to break
parsing/splitting/styling code.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from rich.text import Text

from sase.ace.tui.modals.model_picker_modal import _build_model_options
from sase.ace.tui.modals.plan_approval_modal import _provider_badge_markup
from sase.ace.tui.provider_styles import provider_emoji_badge
from sase.ace.tui.widgets.prompt_panel._helpers import append_model_field
from sase.axe.run_agent_phases import extract_directives_and_write_meta
from sase.llm_provider.registry import (
    model_short_alias_map,
    model_to_provider_map,
    provider_cli_status_color_map,
    provider_short_name_map,
    resolve_model_provider,
)
from sase.llm_provider.retry_config import get_retry_config, is_retryable_error
from sase.llm_provider.temporary_override import (
    resolve_worker_provider_model_for_primary,
    set_temporary_override,
)

_AGY_LARGE = "Gemini 3.5 Flash (High)"
_AGY_SMALL = "Gemini 3.5 Flash (Low)"


def test_provider_metadata_aggregation_includes_agy() -> None:
    models = model_to_provider_map()
    provider_shorts = provider_short_name_map()
    model_aliases = model_short_alias_map()

    assert models[_AGY_LARGE] == "agy"
    assert models[_AGY_SMALL] == "agy"
    assert provider_shorts["agy"] == "agy"
    assert model_aliases[_AGY_LARGE] == "flash35h"
    assert model_aliases[_AGY_SMALL] == "flash35l"
    # A distinct Antigravity color, deliberately not Gemini blue.
    color = provider_cli_status_color_map()["agy"]
    assert color == "#6E5DE7"
    assert color != provider_cli_status_color_map().get("gemini")


def test_agy_autodetect_ordering_precedes_gemini() -> None:
    """agy inherits the late Gemini fallback slot and wins the priority tie."""
    from sase.llm_provider.registry import get_llm_metadata_payload

    candidates = get_llm_metadata_payload()["autodetect_candidates"]
    by_provider = {c["provider"]: c for c in candidates}

    assert by_provider["agy"]["priority"] == 30
    assert by_provider["agy"]["cli_name"] == "agy"

    order = [c["provider"] for c in candidates]
    # Both agy and gemini sit at priority 30; the (priority, provider) sort
    # keys agy ahead of gemini, so agy is the preferred fallback.
    if "gemini" in order:
        assert order.index("agy") < order.index("gemini")


def test_nested_agy_model_resolution_preserves_spaces_and_parens() -> None:
    assert resolve_model_provider(f"agy/{_AGY_LARGE}") == ("agy", _AGY_LARGE)


def test_model_picker_includes_agy_model_with_spaces() -> None:
    option_ids = {option.id for option in _build_model_options() if option is not None}

    assert _AGY_LARGE in option_ids
    assert _AGY_SMALL in option_ids


def test_prompt_panel_model_field_renders_agy_provider() -> None:
    text = Text()

    append_model_field(text, _AGY_LARGE, "agy")

    assert text.plain == f"Model: AGY({_AGY_LARGE})\n"


def test_prompt_panel_model_field_infers_agy_from_model_name() -> None:
    text = Text()

    append_model_field(text, _AGY_LARGE, None)

    assert text.plain == f"Model: AGY({_AGY_LARGE})\n"


def test_plan_approval_badge_renders_agy_provider_color() -> None:
    badge = _provider_badge_markup("agy", _AGY_LARGE)

    assert "AGY" in badge
    assert "#6E5DE7" in badge
    # The space/paren-laden model name survives intact in the badge markup.
    assert _AGY_LARGE in badge


def test_agy_provider_has_emoji_badge() -> None:
    assert provider_emoji_badge("agy") == "🪐"


def test_temporary_override_accepts_agy_model_with_spaces(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    override = set_temporary_override(
        f"agy/{_AGY_LARGE}",
        60.0,
        source="test",
    )

    assert override.provider == "agy"
    assert override.model == _AGY_LARGE
    assert override.raw_model == f"agy/{_AGY_LARGE}"


def test_worker_model_override_resolves_agy_target_with_spaces(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A worker_models entry targeting a space-laden agy model resolves cleanly."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(
        "sase.llm_provider.config.get_configured_worker_model_entry_for_primary",
        lambda _provider, _model: ("claude", f"agy/{_AGY_LARGE}"),
    )

    resolution = resolve_worker_provider_model_for_primary("claude", "opus")

    assert resolution.source == "config"
    assert resolution.provider == "agy"
    assert resolution.model == _AGY_LARGE
    assert resolution.configured_target == f"agy/{_AGY_LARGE}"


def test_agent_metadata_records_agy_provider_directive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The provider half of an ``%model:agy/...`` directive is recorded.

    The whitespace-delimited ``%model`` text directive cannot carry an agy
    display name's spaces; the space-tolerant entry points are the model
    picker and :func:`set_temporary_override` (covered above). This test
    pins the provider-routing half end to end through metadata writing.
    """
    workspace_dir = tmp_path / "workspace"
    artifacts_dir = tmp_path / "artifacts" / "20260619120000"
    workspace_dir.mkdir()
    artifacts_dir.mkdir(parents=True)
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)

    with (
        patch.object(Path, "home", return_value=tmp_path),
        patch("sase.vcs_provider._registry.detect_vcs", return_value=None),
        patch("sase.ace.agent_tags.update_agent_tag"),
    ):
        info = extract_directives_and_write_meta(
            "%model:agy/flash35h\nDo work",
            str(workspace_dir),
            str(artifacts_dir),
        )

    meta = json.loads((artifacts_dir / "agent_meta.json").read_text())
    assert info.llm_provider == "agy"
    assert meta["llm_provider"] == "agy"


def test_agy_default_retry_config_matches_transient_failures() -> None:
    config = get_retry_config("agy")

    assert config is not None
    assert config.max_retries == 3
    assert config.preserve_workspace is True
    # Representative Google-stack transport/rate-limit/timeout failures retry.
    assert is_retryable_error("RESOURCE_EXHAUSTED: quota exceeded", config)
    assert is_retryable_error("rpc error: DEADLINE_EXCEEDED", config)
    assert is_retryable_error("HTTP 503 UNAVAILABLE", config)
    assert is_retryable_error("hit the model rate limit", config)
    # A genuine logic error is not retried.
    assert not is_retryable_error("unknown model name", config)
