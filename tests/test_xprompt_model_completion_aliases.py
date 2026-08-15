"""Alias and override tests for ``%model`` completion."""

from __future__ import annotations

import pytest

from sase.llm_provider.config import ModelAliasSelectorMember
from sase.llm_provider.temporary_override import TemporaryLLMOverride
from sase.xprompt import model_completion

from tests._xprompt_model_completion_helpers import (
    alias_view,
    clear_model_completion_cache as clear_model_completion_cache,
    metadata_payload,
)


def test_model_completion_configured_retired_coder_alias_is_user_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A configured ``coder`` alias surfaces once as an ordinary user alias."""
    monkeypatch.setattr(model_completion, "get_llm_metadata_payload", metadata_payload)
    monkeypatch.setattr(
        model_completion, "get_model_aliases", lambda: {"coder": "claude/opus"}
    )
    monkeypatch.setattr(
        model_completion,
        "build_alias_views",
        lambda **_kwargs: [
            alias_view(
                "coder",
                kind="user",
                configured=True,
                configured_value="claude/opus",
                description="Legacy coder alias.",
                config_source="builtin",
            )
        ],
    )

    entries = model_completion.build_model_completion_catalog()
    coder_entries = [entry for entry in entries if entry.value == "@coder"]

    assert len(coder_entries) == 1
    assert coder_entries[0].kind == "user_alias"
    assert coder_entries[0].description == "Legacy coder alias."
    assert coder_entries[0].alias_kind == "user"
    assert coder_entries[0].provenance == "configured"


def test_model_completion_alias_enrichment_and_pool_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(model_completion, "get_llm_metadata_payload", metadata_payload)
    monkeypatch.setattr(
        model_completion,
        "get_model_aliases",
        lambda: {"blogger": "@medium@high"},
    )
    monkeypatch.setattr(
        model_completion,
        "build_alias_views",
        lambda **_kwargs: [
            alias_view(
                "small",
                kind="role",
                configured=False,
                provider="codex",
                model="gpt-5.5",
                description="Small-agent pool.",
                selector_mode="round_robin",
                selector_members=(
                    ModelAliasSelectorMember(
                        value="claude/opus",
                        target="claude/opus",
                        effort=None,
                        provider="claude",
                        available=False,
                    ),
                    ModelAliasSelectorMember(
                        value="codex/gpt-5.5",
                        target="codex/gpt-5.5",
                        effort=None,
                        provider="codex",
                        available=True,
                        selected=True,
                    ),
                ),
            ),
            alias_view(
                "blogger",
                kind="user",
                configured=True,
                configured_value="@medium@high",
                description="Draft and edit blog posts.",
                config_source="custom",
                bucket="writing",
                effort="high",
            ),
        ],
    )

    entries = model_completion.build_model_completion_catalog()
    by_value = {entry.value: entry for entry in entries}

    small = by_value["@small"]
    assert small.description == "Small-agent pool."
    assert small.alias_kind == "role"
    assert small.selector_mode == "round_robin"
    assert (small.pool_available, small.pool_total) == (1, 2)

    blogger = by_value["@blogger"]
    assert blogger.description == "Draft and edit blog posts."
    assert blogger.alias_kind == "user"
    assert blogger.provenance == "configured"
    assert blogger.reference == "medium"
    assert blogger.reference_effort == "high"
    assert blogger.target_effort == "high"
    assert blogger.config_source == "custom"
    assert blogger.bucket == "writing"


def test_model_completion_override_overlay_rewrites_only_alias_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(model_completion, "get_llm_metadata_payload", metadata_payload)
    monkeypatch.setattr(model_completion, "get_model_aliases", lambda: {})
    monkeypatch.setattr(
        model_completion,
        "build_alias_views",
        lambda **_kwargs: [
            alias_view(
                "large",
                kind="role",
                configured=False,
                description="Default launch model.",
            )
        ],
    )
    override = TemporaryLLMOverride(
        provider="codex",
        model="gpt-5.6-sol",
        raw_model="codex/gpt-5.6-sol@medium",
        created_at=1.0,
        expires_at=None,
        source="test",
        effort="medium",
    )

    static = model_completion.build_model_completion_catalog()
    overlaid = model_completion.build_model_completion_catalog(
        overrides={"large": override}
    )
    static_large = next(entry for entry in static if entry.value == "@large")
    live_large = next(entry for entry in overlaid if entry.value == "@large")
    static_provider = next(entry for entry in static if entry.value == "claude/")
    live_provider = next(entry for entry in overlaid if entry.value == "claude/")

    assert static_large.provenance == "implicit"
    assert (static_large.target_provider, static_large.target_model) == (
        "claude",
        "opus",
    )
    assert live_large.provenance == "override"
    assert (
        live_large.target_provider,
        live_large.target_model,
        live_large.target_effort,
    ) == ("codex", "gpt-5.6-sol", "medium")
    assert live_large.reference == ""
    assert live_provider == static_provider


def test_configured_provider_coder_alias_gets_ordinary_override_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(model_completion, "get_llm_metadata_payload", metadata_payload)
    monkeypatch.setattr(
        model_completion, "get_model_aliases", lambda: {"codex_coder": "claude/opus"}
    )
    monkeypatch.setattr(
        model_completion,
        "build_alias_views",
        lambda **_kwargs: [
            alias_view(
                "codex_coder",
                kind="user",
                configured=True,
                configured_value="claude/opus",
                config_source="custom",
                description="Explicit legacy alias.",
                provider="claude",
                model="opus",
            ),
        ],
    )
    generic = TemporaryLLMOverride(
        provider="codex",
        model="gpt-5.6-sol",
        raw_model="codex/gpt-5.6-sol@medium",
        created_at=1.0,
        expires_at=None,
        source="test",
        effort="medium",
    )
    specific = TemporaryLLMOverride(
        provider="claude",
        model="opus",
        raw_model="claude/opus",
        created_at=1.0,
        expires_at=None,
        source="test",
    )

    entries = model_completion.build_model_completion_catalog(
        overrides={"coder": generic, "codex_coder": specific}
    )
    by_value = {entry.value: entry for entry in entries}

    codex = by_value["@codex_coder"]
    assert (codex.target_provider, codex.target_model) == ("claude", "opus")
    assert codex.provenance == "override"
    assert codex.reference == ""
    assert "@claude_coder" not in by_value
    assert "@opencode_coder" not in by_value


def test_model_completion_alias_enrichment_failure_keeps_plain_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(model_completion, "get_llm_metadata_payload", metadata_payload)
    monkeypatch.setattr(
        model_completion, "get_model_aliases", lambda: {"fast": "codex/o4-mini"}
    )
    monkeypatch.setattr(
        model_completion,
        "build_alias_views",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    by_value = {
        entry.value: entry
        for entry in model_completion.build_model_completion_catalog()
    }

    assert "@xsmall" in by_value
    assert "@large" in by_value
    assert "@fast" in by_value
    assert by_value["@fast"].alias_kind == ""
    assert by_value["@fast"].target_model == ""
