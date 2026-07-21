"""Tests for the ``%model`` completion catalog."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from sase.xprompt import model_completion


@pytest.fixture(autouse=True)
def clear_model_completion_cache() -> Iterator[None]:
    model_completion._CATALOG_CACHE = None
    yield
    model_completion._CATALOG_CACHE = None


def test_model_completion_catalog_includes_models_implicit_and_user_aliases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        model_completion,
        "get_llm_metadata_payload",
        _metadata_payload,
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

    entries = model_completion.build_model_completion_catalog()
    values = [entry.value for entry in entries]

    # Models, then the implicit role aliases (one @<provider>_coder per provider
    # in provider order), then user-configured aliases. A user-configured
    # ``worker`` is now an ordinary alias (no retired @worker/@other entries).
    assert values == [
        "claude-fable-5",
        "opus",
        "gpt-5.6-sol",
        "gpt-5.5",
        "o4-mini",
        "anthropic/claude-sonnet-4-5",
        "@default",
        "@coder",
        "@claude_coder",
        "@codex_coder",
        "@opencode_coder",
        "@epic_lander",
        "@big_epic_lander",
        "@small_phase_worker",
        "@medium_phase_worker",
        "@large_phase_worker",
        "@smartest",
        "@cheaper",
        "@cheapest",
        "@fast",
        "@worker",
    ]
    assert "@other" not in values
    assert "Gemini 3.5 Flash (High)" not in values
    assert "bad alias" not in values
    assert "fable" not in values

    fable = entries[0]
    assert fable.aliases == ("fable",)
    assert fable.description == "Claude (fable)"

    by_value = {entry.value: entry for entry in entries}
    default_entry = by_value["@default"]
    assert default_entry.kind == "implicit_alias"
    assert default_entry.description == "default model when a prompt has no %model"
    assert default_entry.aliases == ("default",)

    codex_coder = by_value["@codex_coder"]
    assert codex_coder.kind == "implicit_alias"
    assert codex_coder.description == "Codex coder follow-up model"
    assert codex_coder.aliases == ("codex_coder",)

    big_epic_lander = by_value["@big_epic_lander"]
    assert big_epic_lander.kind == "implicit_alias"
    assert big_epic_lander.description == (
        "threshold-selected large-epic land follow-up model"
    )
    assert big_epic_lander.aliases == ("big_epic_lander",)

    medium_phase_worker = by_value["@medium_phase_worker"]
    assert medium_phase_worker.kind == "implicit_alias"
    assert medium_phase_worker.description == "medium bead phase agent model"
    assert medium_phase_worker.aliases == ("medium_phase_worker",)

    cheaper = by_value["@cheaper"]
    assert cheaper.kind == "implicit_alias"
    assert cheaper.description == "load-balanced small phase agent pool"
    assert cheaper.aliases == ("cheaper",)

    smartest = by_value["@smartest"]
    assert smartest.kind == "implicit_alias"
    assert smartest.description == "highest-capability model for large phase agents"
    assert smartest.aliases == ("smartest",)

    fast = by_value["@fast"]
    assert fast.kind == "user_alias"
    assert fast.description == "alias for codex/o4-mini"
    assert fast.aliases == ("fast",)


def test_model_completion_user_alias_shadows_implicit_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A configured ``coder`` alias surfaces once, with its real target."""
    monkeypatch.setattr(model_completion, "get_llm_metadata_payload", _metadata_payload)
    monkeypatch.setattr(
        model_completion, "get_model_aliases", lambda: {"coder": "claude/opus"}
    )

    entries = model_completion.build_model_completion_catalog()
    coder_entries = [entry for entry in entries if entry.value == "@coder"]

    assert len(coder_entries) == 1
    assert coder_entries[0].kind == "user_alias"
    assert coder_entries[0].description == "alias for claude/opus"


def test_model_completion_custom_alias_uses_configured_description(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(model_completion, "get_llm_metadata_payload", _metadata_payload)
    monkeypatch.setattr(
        model_completion,
        "get_model_aliases",
        lambda: {"blogger": "claude/opus"},
    )
    monkeypatch.setattr(
        model_completion,
        "model_alias_config_source",
        lambda alias: "custom" if alias == "blogger" else None,
    )
    monkeypatch.setattr(
        model_completion,
        "model_alias_description",
        lambda alias: "Draft and edit blog posts." if alias == "blogger" else None,
    )

    entries = model_completion.build_model_completion_catalog()
    blogger = next(entry for entry in entries if entry.value == "@blogger")

    assert blogger.description == ("Draft and edit blog posts. (alias for claude/opus)")


def test_model_completion_filter_matches_values_and_short_aliases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(model_completion, "get_llm_metadata_payload", _metadata_payload)
    monkeypatch.setattr(model_completion, "get_model_aliases", lambda: {})

    entries = model_completion.build_model_completion_catalog()

    assert [
        entry.value
        for entry in model_completion.filter_model_completion_entries(entries, "GPT")
    ] == ["gpt-5.6-sol", "gpt-5.5"]
    assert [
        entry.value
        for entry in model_completion.filter_model_completion_entries(entries, "fa")
    ] == ["claude-fable-5"]
    assert [
        entry.value
        for entry in model_completion.filter_model_completion_entries(
            entries, "default"
        )
    ] == ["@default"]
    assert [
        entry.value
        for entry in model_completion.filter_model_completion_entries(entries, "@def")
    ] == ["@default"]


def test_model_completion_catalog_payload_round_trips_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(model_completion, "get_llm_metadata_payload", _metadata_payload)
    monkeypatch.setattr(model_completion, "get_model_aliases", lambda: {})

    payload = model_completion.model_completion_catalog_payload()

    assert payload["schema_version"] == (
        model_completion.MODEL_COMPLETION_CATALOG_SCHEMA_VERSION
    )
    first = payload["entries"][0]  # type: ignore[index]
    assert first == {
        "value": "claude-fable-5",
        "display": "claude-fable-5",
        "description": "Claude (fable)",
        "kind": "model",
        "provider": "claude",
        "aliases": ["fable"],
    }


def _metadata_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "providers": {
            "codex": {
                "provider_name": "Codex",
                "known_model_names": ["gpt-5.6-sol", "gpt-5.5", "o4-mini"],
            },
            "claude": {
                "provider_name": "Claude",
                "known_model_names": [
                    "claude-fable-5",
                    "opus",
                    "Gemini 3.5 Flash (High)",
                ],
            },
            "opencode": {
                "provider_name": "OpenCode",
                "known_model_names": ["anthropic/claude-sonnet-4-5"],
            },
        },
        "model_to_provider": {
            "gpt-5.6-sol": "codex",
            "gpt-5.5": "codex",
            "o4-mini": "codex",
            "claude-fable-5": "claude",
            "opus": "claude",
            "Gemini 3.5 Flash (High)": "claude",
            "anthropic/claude-sonnet-4-5": "opencode",
        },
        "model_short_aliases": {
            "claude-fable-5": "fable",
            "gpt-5.6-sol": "gpt56sol",
            "gpt-5.5": "gpt55",
        },
        "autodetect_candidates": [
            {"priority": 10, "provider": "claude", "cli_name": "claude"},
            {"priority": 20, "provider": "codex", "cli_name": "codex"},
        ],
    }
