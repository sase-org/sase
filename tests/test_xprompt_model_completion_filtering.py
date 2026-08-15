"""Filtering tests for ``%model`` completion."""

from __future__ import annotations

import pytest

from sase.xprompt import model_completion

from tests._xprompt_model_completion_helpers import (
    clear_model_completion_cache as clear_model_completion_cache,
    metadata_payload,
)


def test_model_completion_filter_matches_values_without_unconfigured_default_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(model_completion, "get_llm_metadata_payload", metadata_payload)
    monkeypatch.setattr(model_completion, "get_model_aliases", lambda: {})
    monkeypatch.setattr(model_completion, "build_alias_views", lambda **_kwargs: [])

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
    ] == []
    assert all(
        entry.kind in {"implicit_alias", "user_alias"}
        for entry in model_completion.filter_model_completion_entries(entries, "@")
    )
    assert [
        entry.value
        for entry in model_completion.filter_model_completion_entries(entries, "@def")
    ] == []


def test_model_completion_provider_scoped_filter_derives_qualified_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(model_completion, "get_llm_metadata_payload", metadata_payload)
    monkeypatch.setattr(model_completion, "get_model_aliases", lambda: {})
    monkeypatch.setattr(model_completion, "build_alias_views", lambda **_kwargs: [])

    entries = model_completion.build_model_completion_catalog()

    scoped = model_completion.filter_model_completion_entries(entries, "claude/")
    assert [entry.value for entry in scoped] == [
        "claude/claude-fable-5",
        "claude/opus",
    ]
    assert [entry.kind for entry in scoped] == ["model", "model"]
    assert [entry.provider for entry in scoped] == ["claude", "claude"]
    assert not any(entry.kind == "provider" for entry in scoped)
    assert not any(entry.value.startswith("@") for entry in scoped)

    assert [
        entry.value
        for entry in model_completion.filter_model_completion_entries(
            entries, "claude/op"
        )
    ] == ["claude/opus"]
    assert [
        entry.value
        for entry in model_completion.filter_model_completion_entries(
            entries, "claude/fa"
        )
    ] == ["claude/claude-fable-5"]


def test_model_completion_provider_scope_uses_first_slash_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(model_completion, "get_llm_metadata_payload", metadata_payload)
    monkeypatch.setattr(model_completion, "get_model_aliases", lambda: {})
    monkeypatch.setattr(model_completion, "build_alias_views", lambda **_kwargs: [])

    entries = model_completion.build_model_completion_catalog()

    assert [
        entry.value
        for entry in model_completion.filter_model_completion_entries(
            entries, "opencode/anthropic/"
        )
    ] == ["opencode/anthropic/claude-sonnet-4-5"]
    assert [
        entry.value
        for entry in model_completion.filter_model_completion_entries(
            entries, "anthropic/"
        )
    ] == ["anthropic/claude-sonnet-4-5"]


def test_model_completion_provider_scope_is_case_insensitive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(model_completion, "get_llm_metadata_payload", metadata_payload)
    monkeypatch.setattr(model_completion, "get_model_aliases", lambda: {})
    monkeypatch.setattr(model_completion, "build_alias_views", lambda **_kwargs: [])

    entries = model_completion.build_model_completion_catalog()

    assert [
        entry.value
        for entry in model_completion.filter_model_completion_entries(
            entries, "Claude/"
        )
    ] == ["claude/claude-fable-5", "claude/opus"]
