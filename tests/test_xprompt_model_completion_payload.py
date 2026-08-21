"""Payload and cache tests for ``%model`` completion."""

from __future__ import annotations

import pytest

from sase.xprompt import model_completion

from tests._xprompt_model_completion_helpers import (
    clear_model_completion_cache as clear_model_completion_cache,
    metadata_payload,
)


def test_model_completion_catalog_payload_round_trips_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(model_completion, "get_llm_metadata_payload", metadata_payload)
    monkeypatch.setattr(model_completion, "get_model_aliases", lambda: {})
    monkeypatch.setattr(model_completion, "build_alias_views", lambda **_kwargs: [])

    payload = model_completion.model_completion_catalog_payload()

    assert payload["schema_version"] == (
        model_completion.MODEL_COMPLETION_CATALOG_SCHEMA_VERSION
    )
    entries = payload["entries"]
    assert isinstance(entries, list)
    first = entries[0]
    assert tuple(first) == model_completion.MODEL_COMPLETION_ENTRY_WIRE_FIELDS
    assert first == {
        "value": "claude-fable-5",
        "display": "claude-fable-5",
        "description": "Claude (fable)",
        "kind": "model",
        "provider": "claude",
        "aliases": ["fable"],
        "alias_kind": "",
        "target_provider": "",
        "target_model": "",
        "target_effort": "",
        "provenance": "",
        "reference": "",
        "reference_effort": "",
        "selector_mode": "",
        "pool_available": 0,
        "pool_total": 0,
        "config_source": "",
        "bucket": "",
        "advisory_label": "",
        "advisory_severity": "",
        "provider_model_count": 0,
    }
    provider = next(entry for entry in entries if entry["value"] == "claude/")
    assert provider == {
        "value": "claude/",
        "display": "claude/",
        "description": "Claude",
        "kind": "provider",
        "provider": "claude",
        "aliases": [],
        "alias_kind": "",
        "target_provider": "",
        "target_model": "",
        "target_effort": "",
        "provenance": "",
        "reference": "",
        "reference_effort": "",
        "selector_mode": "",
        "pool_available": 0,
        "pool_total": 0,
        "config_source": "",
        "bucket": "",
        "advisory_label": "",
        "advisory_severity": "",
        "provider_model_count": 2,
    }


def test_model_completion_catalog_rebuilds_when_config_token_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = [("config", 1)]
    calls = 0

    def metadata() -> dict[str, object]:
        nonlocal calls
        calls += 1
        return metadata_payload()

    monkeypatch.setattr(model_completion, "current_config_token", lambda: token[0])
    monkeypatch.setattr(model_completion, "get_llm_metadata_payload", metadata)
    monkeypatch.setattr(model_completion, "get_model_aliases", lambda: {})
    monkeypatch.setattr(model_completion, "build_alias_views", lambda **_kwargs: [])

    model_completion.build_model_completion_catalog()
    model_completion.build_model_completion_catalog()
    token[0] = ("config", 2)
    model_completion.build_model_completion_catalog()

    assert calls == 2
