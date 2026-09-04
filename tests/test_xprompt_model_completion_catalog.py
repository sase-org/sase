"""Catalog-population tests for ``%model`` completion."""

from __future__ import annotations

import pytest

from sase.xprompt import model_completion

from tests._xprompt_model_completion_helpers import (
    clear_model_completion_cache as clear_model_completion_cache,
    metadata_payload,
)


def test_model_completion_catalog_includes_models_implicit_and_user_aliases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        model_completion,
        "get_llm_metadata_payload",
        metadata_payload,
    )
    monkeypatch.setattr(
        model_completion,
        "get_model_aliases",
        lambda: {
            "fast": "codex/o4-mini",
            "bad alias": "claude/opus",
            "worker": "codex/o3",
        },
    )
    monkeypatch.setattr(model_completion, "build_alias_views", lambda **_kwargs: [])

    entries = model_completion.build_model_completion_catalog()
    values = [entry.value for entry in entries]

    # Models, then the implicit size aliases, then user-configured aliases.
    # A user-configured ``worker`` is now an ordinary alias (no retired
    # @worker/@other entries).
    assert values == [
        "claude-fable-5",
        "opus",
        "gpt-5.6-sol",
        "gpt-5.5",
        "o4-mini",
        "anthropic/claude-sonnet-4-5",
        "@xsmall",
        "@small",
        "@medium",
        "@large",
        "@xlarge",
        "@fast",
        "@worker",
        "claude/",
        "codex/",
        "opencode/",
    ]
    assert "@other" not in values
    assert "Custom Model (Preview)" not in values
    assert "bad alias" not in values
    assert "fable" not in values

    fable = entries[0]
    assert fable.aliases == ("fable",)
    assert fable.description == "Claude (fable)"

    by_value = {entry.value: entry for entry in entries}
    assert by_value["claude/"].kind == "provider"
    assert by_value["claude/"].description == "Claude"
    assert by_value["claude/"].provider == "claude"
    assert by_value["claude/"].provider_model_count == 2
    assert by_value["codex/"].provider_model_count == 3
    assert by_value["opencode/"].provider_model_count == 1
    assert by_value["@xsmall"].kind == "implicit_alias"
    assert by_value["@xsmall"].aliases == ("xsmall",)
    assert by_value["@medium"].aliases == ("medium",)
    assert by_value["@xlarge"].aliases == ("xlarge",)
    assert by_value["@fast"].kind == "user_alias"
    assert by_value["@fast"].aliases == ("fast",)


def test_model_completion_catalog_reflects_real_builtin_model_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Real metadata includes Spark and excludes removed Claude point versions."""
    # Keep catalog assertions on registry-driven model rows deterministic by
    # bypassing user-defined alias rows.
    monkeypatch.setattr(model_completion, "get_model_aliases", lambda: {})
    monkeypatch.setattr(model_completion, "build_alias_views", lambda **_kwargs: [])

    entries = model_completion.build_model_completion_catalog()
    model_entries = {entry.value: entry for entry in entries if entry.kind == "model"}

    assert "claude-opus-5" not in model_entries
    assert "claude-sonnet-5" not in model_entries
    assert "gpt-5.3-codex-spark" in model_entries

    spark = model_entries["gpt-5.3-codex-spark"]
    assert spark.provider == "codex"
    assert spark.aliases == ("gpt53spark",)
    assert spark.description == "Codex (gpt53spark)"


def test_model_completion_catalog_includes_agy_gemini_37_flash_variants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Real registry metadata surfaces all three Antigravity 3.7 Flash rows."""
    monkeypatch.setattr(model_completion, "get_model_aliases", lambda: {})
    monkeypatch.setattr(model_completion, "build_alias_views", lambda **_kwargs: [])

    entries = model_completion.build_model_completion_catalog()
    model_entries = {entry.value: entry for entry in entries if entry.kind == "model"}

    expected_aliases = {
        "gemini-3.7-flash-high": "flash37h",
        "gemini-3.7-flash-medium": "flash37m",
        "gemini-3.7-flash-low": "flash37l",
    }
    for model, alias in expected_aliases.items():
        assert model in model_entries
        entry = model_entries[model]
        assert entry.provider == "agy"
        assert entry.aliases == (alias,)

    scoped = model_completion.filter_model_completion_entries(entries, "agy/")
    scoped_values = {entry.value for entry in scoped}
    for model in expected_aliases:
        assert f"agy/{model}" in scoped_values


def test_model_completion_catalog_includes_agy_gemini_38_flash_variants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Real registry metadata surfaces all three Antigravity 3.8 Flash rows."""
    monkeypatch.setattr(model_completion, "get_model_aliases", lambda: {})
    monkeypatch.setattr(model_completion, "build_alias_views", lambda **_kwargs: [])

    entries = model_completion.build_model_completion_catalog()
    model_entries = {entry.value: entry for entry in entries if entry.kind == "model"}

    expected_aliases = {
        "gemini-3.8-flash-high": "flash38h",
        "gemini-3.8-flash-medium": "flash38m",
        "gemini-3.8-flash-low": "flash38l",
    }
    for model, alias in expected_aliases.items():
        assert model in model_entries
        entry = model_entries[model]
        assert entry.provider == "agy"
        assert entry.aliases == (alias,)

    scoped = model_completion.filter_model_completion_entries(entries, "agy/")
    scoped_values = {entry.value for entry in scoped}
    for model in expected_aliases:
        assert f"agy/{model}" in scoped_values


def test_model_completion_catalog_hides_fakey_from_real_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bundled fakey test provider is filtered from real %model completion."""
    monkeypatch.setattr(model_completion, "get_model_aliases", lambda: {})
    monkeypatch.setattr(model_completion, "build_alias_views", lambda **_kwargs: [])

    entries = model_completion.build_model_completion_catalog()

    assert not any(entry.provider == "fakey" for entry in entries)
    assert not any(entry.value.startswith("fakey-") for entry in entries)
    assert not any(entry.value == "@fakey_coder" for entry in entries)


def test_model_completion_catalog_filters_hidden_provider_by_metadata_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A synthetic hidden provider is filtered by the hook, not by literal name."""

    def metadata() -> dict[str, object]:
        payload = metadata_payload()
        providers = payload["providers"]
        assert isinstance(providers, dict)
        providers["hiddenprov"] = {
            "provider_name": "HiddenProv",
            "known_model_names": ["hiddenprov-large"],
        }
        model_to_provider = payload["model_to_provider"]
        assert isinstance(model_to_provider, dict)
        model_to_provider["hiddenprov-large"] = "hiddenprov"
        return payload

    monkeypatch.setattr(model_completion, "get_llm_metadata_payload", metadata)
    monkeypatch.setattr(model_completion, "get_model_aliases", lambda: {})
    monkeypatch.setattr(model_completion, "build_alias_views", lambda **_kwargs: [])
    monkeypatch.setattr(
        model_completion,
        "model_picker_hidden_provider_names",
        lambda: frozenset({"hiddenprov"}),
    )

    entries = model_completion.build_model_completion_catalog()
    values = {entry.value for entry in entries}

    assert "hiddenprov-large" not in values
    assert "hiddenprov/" not in values
    assert "@hiddenprov_coder" not in values
    # Non-hidden providers remain unaffected.
    assert "gpt-5.6-sol" in values
    assert (
        model_completion.filter_model_completion_entries(entries, "hiddenprov/") == []
    )
