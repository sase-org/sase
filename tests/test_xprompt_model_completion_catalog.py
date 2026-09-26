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


def test_model_completion_catalog_mirrors_visible_provider_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catalog model rows mirror the registry for visible providers.

    Expectations derive from ``get_llm_metadata_payload`` (the data source)
    rather than naming model IDs: every non-hidden provider's known models
    appear with their provider and short alias, provider rows carry the
    matching model counts, and hidden providers stay out per the hook-driven
    policy. Adding, removing, or renaming a built-in model needs no test
    edit.
    """
    from sase.llm_provider import registry

    # Keep catalog assertions on registry-driven model rows deterministic by
    # bypassing user-defined alias rows.
    monkeypatch.setattr(model_completion, "get_model_aliases", lambda: {})
    monkeypatch.setattr(model_completion, "build_alias_views", lambda **_kwargs: [])

    entries = model_completion.build_model_completion_catalog()
    model_entries = {entry.value: entry for entry in entries if entry.kind == "model"}
    by_value = {entry.value: entry for entry in entries}

    payload = registry.get_llm_metadata_payload()
    providers = payload["providers"]
    assert isinstance(providers, dict)
    model_to_provider = payload["model_to_provider"]
    assert isinstance(model_to_provider, dict)
    short_aliases = payload.get("model_short_aliases", {})
    assert isinstance(short_aliases, dict)
    hidden = registry.model_picker_hidden_provider_names()

    assert model_to_provider, "registry must publish models for this mirror check"
    for model, provider in model_to_provider.items():
        if provider in hidden:
            assert model not in model_entries, model
            continue
        assert model in model_entries, model
        entry = model_entries[model]
        assert entry.provider == provider
        expected_alias = short_aliases.get(model)
        if expected_alias is not None:
            assert expected_alias in entry.aliases, model

    for provider, meta in providers.items():
        assert isinstance(meta, dict)
        provider_row = f"{provider}/"
        if provider in hidden:
            assert provider_row not in by_value
            continue
        assert provider_row in by_value, provider
        provider_models = [
            entry for entry in model_entries.values() if entry.provider == provider
        ]
        assert provider_models, provider
        assert by_value[provider_row].provider_model_count == len(provider_models)

        scoped_values = {
            entry.value
            for entry in model_completion.filter_model_completion_entries(
                entries, provider_row
            )
        }
        for model in meta["known_model_names"]:
            if model_to_provider.get(model) != provider:
                continue
            assert f"{provider}/{model}" in scoped_values, (provider, model)

    visible_aliases = [
        (model, alias)
        for model, alias in short_aliases.items()
        if model_to_provider.get(model) not in hidden
    ]
    assert visible_aliases, "registry must publish a short alias for this check"
    for model, alias in visible_aliases[:5]:
        alias_values = {
            entry.value
            for entry in model_completion.filter_model_completion_entries(
                entries, alias
            )
        }
        assert model in alias_values, alias


def test_model_completion_lsp_payload_mirrors_visible_registry_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The serialized LSP catalog carries every visible registry model row."""
    from sase.llm_provider import registry

    monkeypatch.setattr(model_completion, "get_model_aliases", lambda: {})
    monkeypatch.setattr(model_completion, "build_alias_views", lambda **_kwargs: [])

    payload = model_completion.model_completion_catalog_payload()
    entries = payload["entries"]
    assert isinstance(entries, list)
    by_value = {entry["value"]: entry for entry in entries if isinstance(entry, dict)}

    metadata = registry.get_llm_metadata_payload()
    model_to_provider = metadata["model_to_provider"]
    assert isinstance(model_to_provider, dict)
    short_aliases = metadata.get("model_short_aliases", {})
    assert isinstance(short_aliases, dict)
    hidden = registry.model_picker_hidden_provider_names()

    for model, provider in model_to_provider.items():
        if provider in hidden:
            continue
        assert model in by_value, model
        row = by_value[model]
        assert row["provider"] == provider
        expected_alias = short_aliases.get(model)
        if expected_alias is not None:
            assert expected_alias in row["aliases"], model


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
