"""Launch-selection alias trail/origin tests."""

from __future__ import annotations

import pytest

from sase.llm_provider.launch_selection import (
    ALIAS_ORIGIN_DEFAULT_MODEL,
    ALIAS_ORIGIN_DIRECTIVE,
    ALIAS_ORIGIN_NONE,
    LaunchSelection,
    resolve_launch_selection,
)
from sase.xprompt.directives import PromptDirectives
from tests.llm_provider._provider_config_helpers import mock_provider_config


def _patch_provider_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.llm_provider.registry._provider_names", lambda: ["claude"]
    )


def _assert_consistent(selection: LaunchSelection) -> None:
    if selection.alias_trail:
        assert selection.alias_origin != ALIAS_ORIGIN_NONE
    else:
        assert selection.alias_origin == ALIAS_ORIGIN_NONE


def test_directive_alias_launch_records_directive_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_provider_names(monkeypatch)
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "custom": {
                    "entry": {"model": "@final"},
                    "final": {"model": "claude/opus"},
                }
            },
        },
    )

    selection = resolve_launch_selection(
        PromptDirectives(model="@entry", model_alias="entry"),
        consume=False,
    )

    assert selection is not None
    assert (selection.provider, selection.model) == ("claude", "opus")
    assert selection.alias_trail == ("entry", "final")
    assert selection.alias_origin == ALIAS_ORIGIN_DIRECTIVE
    _assert_consistent(selection)


def test_default_model_launch_records_default_origin_and_full_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_provider_names(monkeypatch)
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "default_model": "@entry",
            "model_aliases": {
                "custom": {
                    "entry": {"model": "@final"},
                    "final": {"model": "claude/opus"},
                }
            },
        },
    )

    selection = resolve_launch_selection(PromptDirectives(), consume=False)

    assert selection is not None
    assert (selection.provider, selection.model) == ("claude", "opus")
    assert selection.alias_trail == ("entry", "final")
    assert selection.alias_origin == ALIAS_ORIGIN_DEFAULT_MODEL
    _assert_consistent(selection)


def test_concrete_model_launch_records_none_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_provider_names(monkeypatch)
    mock_provider_config(monkeypatch, {"provider": "claude", "model_aliases": {}})

    selection = resolve_launch_selection(
        PromptDirectives(model="claude/opus"),
        consume=False,
    )

    assert selection is not None
    assert (selection.provider, selection.model) == ("claude", "opus")
    assert selection.alias_trail == ()
    assert selection.alias_origin == ALIAS_ORIGIN_NONE
    _assert_consistent(selection)
