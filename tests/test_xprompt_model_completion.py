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


def test_model_completion_catalog_includes_models_reserved_and_user_aliases(
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

    assert values == [
        "claude-fable-5",
        "opus",
        "gpt-5.5",
        "o4-mini",
        "anthropic/claude-sonnet-4-5",
        "@worker",
        "@other",
        "@fast",
    ]
    assert "Gemini 3.5 Flash (High)" not in values
    assert "bad alias" not in values
    assert "fable" not in values

    fable = entries[0]
    assert fable.aliases == ("fable",)
    assert fable.description == "Claude (fable)"

    fast = entries[-1]
    assert fast.kind == "user_alias"
    assert fast.description == "alias for codex/o4-mini"
    assert fast.aliases == ("fast",)


def test_model_completion_filter_matches_values_and_short_aliases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(model_completion, "get_llm_metadata_payload", _metadata_payload)
    monkeypatch.setattr(model_completion, "get_model_aliases", lambda: {})

    entries = model_completion.build_model_completion_catalog()

    assert [
        entry.value
        for entry in model_completion.filter_model_completion_entries(entries, "GPT")
    ] == ["gpt-5.5"]
    assert [
        entry.value
        for entry in model_completion.filter_model_completion_entries(entries, "fa")
    ] == ["claude-fable-5"]
    assert [
        entry.value
        for entry in model_completion.filter_model_completion_entries(entries, "oth")
    ] == ["@other"]
    assert [
        entry.value
        for entry in model_completion.filter_model_completion_entries(entries, "@oth")
    ] == ["@other"]


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
                "known_model_names": ["gpt-5.5", "o4-mini"],
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
            "gpt-5.5": "codex",
            "o4-mini": "codex",
            "claude-fable-5": "claude",
            "opus": "claude",
            "Gemini 3.5 Flash (High)": "claude",
            "anthropic/claude-sonnet-4-5": "opencode",
        },
        "model_short_aliases": {
            "claude-fable-5": "fable",
            "gpt-5.5": "gpt55",
        },
        "autodetect_candidates": [
            {"priority": 10, "provider": "claude", "cli_name": "claude"},
            {"priority": 20, "provider": "codex", "cli_name": "codex"},
        ],
    }
