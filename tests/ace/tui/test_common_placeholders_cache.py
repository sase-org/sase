"""Tests for the app-level common-placeholder cache loader."""

from __future__ import annotations

from unittest.mock import patch

from sase.ace.tui.actions._startup_common_placeholders import (
    _load_common_placeholders,
)


def test_loader_seeds_once_then_loads_on_the_first_warm() -> None:
    token = ("/tmp/prompt_placeholders.json", 10, 20)
    with (
        patch(
            "sase.history.prompt_placeholders.seed_common_placeholders_from_history",
        ) as seed,
        patch(
            "sase.history.prompt_placeholders.common_placeholder_source_token",
            return_value=token,
        ),
        patch(
            "sase.history.prompt_placeholders.load_common_placeholders",
            return_value=["feature flag"],
        ) as load,
    ):
        result = _load_common_placeholders(limit=100, previous_token=None)

    assert result.source_token == token
    assert result.placeholders == ["feature flag"]
    seed.assert_called_once_with(100)
    load.assert_called_once_with(100)


def test_loader_skips_the_seed_and_the_read_for_an_unchanged_token() -> None:
    token = ("/tmp/prompt_placeholders.json", 10, 20)
    with (
        patch(
            "sase.history.prompt_placeholders.seed_common_placeholders_from_history",
        ) as seed,
        patch(
            "sase.history.prompt_placeholders.common_placeholder_source_token",
            return_value=token,
        ),
        patch(
            "sase.history.prompt_placeholders.load_common_placeholders",
        ) as load,
    ):
        result = _load_common_placeholders(limit=100, previous_token=token)

    assert result.source_token == token
    assert result.placeholders is None
    seed.assert_not_called()
    load.assert_not_called()
