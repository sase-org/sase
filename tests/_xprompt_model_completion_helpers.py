"""Shared fixtures and builders for ``%model`` completion catalog tests."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from sase.llm_provider.alias_view import AliasView
from sase.llm_provider.config import ModelAliasSelectorMember
from sase.xprompt import model_completion


@pytest.fixture(autouse=True)
def clear_model_completion_cache() -> Iterator[None]:
    model_completion._CATALOG_CACHE = None
    yield
    model_completion._CATALOG_CACHE = None


def alias_view(
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
    implicit_value: str | None = None,
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
        implicit_value=implicit_value,
        selector_mode=selector_mode,  # type: ignore[arg-type]
        selector_members=selector_members,
        effort=effort,
    )


def metadata_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "providers": {
            "codex": {
                "provider_name": "codex",
                "display_name": "Codex",
                "known_model_names": ["gpt-5.6-sol", "gpt-5.5", "o4-mini"],
            },
            "claude": {
                "provider_name": "claude",
                "display_name": "Claude",
                "known_model_names": [
                    "claude-fable-5",
                    "opus",
                    "Custom Model (Preview)",
                ],
            },
            "opencode": {
                "provider_name": "opencode",
                "display_name": "OpenCode",
                "known_model_names": ["anthropic/claude-sonnet-4-5"],
            },
        },
        "model_to_provider": {
            "gpt-5.6-sol": "codex",
            "gpt-5.5": "codex",
            "o4-mini": "codex",
            "claude-fable-5": "claude",
            "opus": "claude",
            "Custom Model (Preview)": "claude",
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
