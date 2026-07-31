"""Tests for the ``%model`` completion catalog."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from sase.llm_provider.alias_view import AliasView
from sase.llm_provider.config import ModelAliasSelectorMember
from sase.llm_provider.temporary_override import TemporaryLLMOverride
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
    monkeypatch.setattr(model_completion, "build_alias_views", lambda **_kwargs: [])

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
        "@task_worker",
        "@xsmall_phase_worker",
        "@small_phase_worker",
        "@medium_phase_worker",
        "@large_phase_worker",
        "@xlarge_phase_worker",
        "@smartest",
        "@smart",
        "@cheap",
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
    assert by_value["@default"].kind == "implicit_alias"
    assert by_value["@default"].aliases == ("default",)
    assert by_value["@codex_coder"].aliases == ("codex_coder",)
    assert by_value["@big_epic_lander"].aliases == ("big_epic_lander",)
    assert by_value["@task_worker"].aliases == ("task_worker",)
    assert by_value["@medium_phase_worker"].aliases == ("medium_phase_worker",)
    assert by_value["@cheap"].aliases == ("cheap",)
    assert by_value["@smartest"].aliases == ("smartest",)
    assert by_value["@fast"].kind == "user_alias"
    assert by_value["@fast"].aliases == ("fast",)


def test_model_completion_user_alias_shadows_implicit_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A configured ``coder`` alias surfaces once, with its real target."""
    monkeypatch.setattr(model_completion, "get_llm_metadata_payload", _metadata_payload)
    monkeypatch.setattr(
        model_completion, "get_model_aliases", lambda: {"coder": "claude/opus"}
    )
    monkeypatch.setattr(
        model_completion,
        "build_alias_views",
        lambda **_kwargs: [
            _alias_view(
                "coder",
                kind="role",
                configured=True,
                configured_value="claude/opus",
                description="Coder follow-up agents.",
                config_source="builtin",
            )
        ],
    )

    entries = model_completion.build_model_completion_catalog()
    coder_entries = [entry for entry in entries if entry.value == "@coder"]

    assert len(coder_entries) == 1
    assert coder_entries[0].kind == "user_alias"
    assert coder_entries[0].description == "Coder follow-up agents."
    assert coder_entries[0].alias_kind == "role"
    assert coder_entries[0].provenance == "configured"


def test_model_completion_alias_enrichment_and_pool_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(model_completion, "get_llm_metadata_payload", _metadata_payload)
    monkeypatch.setattr(
        model_completion,
        "get_model_aliases",
        lambda: {"blogger": "@coder@high"},
    )
    monkeypatch.setattr(
        model_completion,
        "build_alias_views",
        lambda **_kwargs: [
            _alias_view(
                "default",
                kind="default",
                configured=False,
                description="Default model.",
            ),
            _alias_view(
                "cheap",
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
            _alias_view(
                "blogger",
                kind="user",
                configured=True,
                configured_value="@coder@high",
                description="Draft and edit blog posts.",
                config_source="custom",
                bucket="writing",
                effort="high",
            ),
        ],
    )

    entries = model_completion.build_model_completion_catalog()
    by_value = {entry.value: entry for entry in entries}

    default = by_value["@default"]
    assert default.description == "Default model."
    assert default.alias_kind == "default"
    assert (default.target_provider, default.target_model) == ("claude", "opus")
    assert default.provenance == "implicit"

    cheap = by_value["@cheap"]
    assert cheap.selector_mode == "round_robin"
    assert (cheap.pool_available, cheap.pool_total) == (1, 2)

    blogger = by_value["@blogger"]
    assert blogger.description == "Draft and edit blog posts."
    assert blogger.alias_kind == "user"
    assert blogger.provenance == "configured"
    assert blogger.reference == "coder"
    assert blogger.reference_effort == "high"
    assert blogger.target_effort == "high"
    assert blogger.config_source == "custom"
    assert blogger.bucket == "writing"


def test_model_completion_filter_matches_values_and_short_aliases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(model_completion, "get_llm_metadata_payload", _metadata_payload)
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
    ] == ["@default"]
    assert all(
        entry.kind in {"implicit_alias", "user_alias"}
        for entry in model_completion.filter_model_completion_entries(entries, "@")
    )
    assert [
        entry.value
        for entry in model_completion.filter_model_completion_entries(entries, "@def")
    ] == ["@default"]


def test_model_completion_catalog_payload_round_trips_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(model_completion, "get_llm_metadata_payload", _metadata_payload)
    monkeypatch.setattr(model_completion, "get_model_aliases", lambda: {})
    monkeypatch.setattr(model_completion, "build_alias_views", lambda **_kwargs: [])

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
    }


def test_model_completion_override_overlay_rewrites_only_alias_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(model_completion, "get_llm_metadata_payload", _metadata_payload)
    monkeypatch.setattr(model_completion, "get_model_aliases", lambda: {})
    monkeypatch.setattr(
        model_completion,
        "build_alias_views",
        lambda **_kwargs: [
            _alias_view(
                "default",
                kind="default",
                configured=False,
                description="Default model.",
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
        overrides={"default": override}
    )
    static_default = next(entry for entry in static if entry.value == "@default")
    live_default = next(entry for entry in overlaid if entry.value == "@default")

    assert static_default.provenance == "implicit"
    assert (static_default.target_provider, static_default.target_model) == (
        "claude",
        "opus",
    )
    assert live_default.provenance == "override"
    assert (
        live_default.target_provider,
        live_default.target_model,
        live_default.target_effort,
    ) == ("codex", "gpt-5.6-sol", "medium")
    assert live_default.reference == ""


def test_model_completion_catalog_rebuilds_when_config_token_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = [("config", 1)]
    calls = 0

    def metadata() -> dict[str, object]:
        nonlocal calls
        calls += 1
        return _metadata_payload()

    monkeypatch.setattr(model_completion, "current_config_token", lambda: token[0])
    monkeypatch.setattr(model_completion, "get_llm_metadata_payload", metadata)
    monkeypatch.setattr(model_completion, "get_model_aliases", lambda: {})
    monkeypatch.setattr(model_completion, "build_alias_views", lambda **_kwargs: [])

    model_completion.build_model_completion_catalog()
    model_completion.build_model_completion_catalog()
    token[0] = ("config", 2)
    model_completion.build_model_completion_catalog()

    assert calls == 2


def test_model_completion_alias_enrichment_failure_keeps_plain_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(model_completion, "get_llm_metadata_payload", _metadata_payload)
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

    assert "@default" in by_value
    assert "@fast" in by_value
    assert by_value["@fast"].alias_kind == ""
    assert by_value["@fast"].target_model == ""


def _alias_view(
    name: str,
    *,
    kind: str,
    configured: bool,
    configured_value: str | None = None,
    provider: str | None = "claude",
    model: str = "opus",
    description: str | None = None,
    config_source: str | None = None,
    bucket: str | None = None,
    selector_mode: str | None = None,
    selector_members: tuple[ModelAliasSelectorMember, ...] = (),
    effort: str | None = None,
) -> AliasView:
    return AliasView(
        name=name,
        kind=kind,  # type: ignore[arg-type]
        configured=configured,
        configured_value=configured_value,
        provider=provider,
        model=model,
        override=None,
        configured_source=config_source,
        description=description,
        bucket=bucket,
        selector_mode=selector_mode,  # type: ignore[arg-type]
        selector_members=selector_members,
        effort=effort,
    )


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
