"""Tests for the ``llm_provider.default_effort`` config getter (epic sase-55)."""

from typing import Any
from unittest.mock import patch

import pytest

from sase.llm_provider.config import _get_default_effort
from sase.xprompt.effort import EFFORT_LEVELS_ORDERED


def _mock_config(*, default_effort: Any) -> dict[str, Any]:
    """Build a merged-config payload carrying ``llm_provider.default_effort``."""
    return {"llm_provider": {"provider": "", "default_effort": default_effort}}


class TestGetDefaultEffort:
    @pytest.mark.parametrize("level", EFFORT_LEVELS_ORDERED)
    @patch("sase.llm_provider.config.load_merged_config")
    def test_returns_each_valid_level(self, mock_config: object, level: str) -> None:
        # Every canonical vocabulary level (the single source of truth) is
        # accepted and returned verbatim.
        mock_config.return_value = _mock_config(default_effort=level)  # type: ignore[union-attr]
        assert _get_default_effort() == level

    @patch("sase.llm_provider.config.load_merged_config")
    def test_merged_value_is_returned(self, mock_config: object) -> None:
        # load_merged_config already layers default_config.yml -> plugin
        # defaults -> ~/.config/sase/sase.yml -> overlays -> ./sase/sase.yml,
        # so the getter just reads whatever that single merge point resolves to.
        mock_config.return_value = _mock_config(default_effort="xhigh")  # type: ignore[union-attr]
        assert _get_default_effort() == "xhigh"

    @patch("sase.llm_provider.config.load_merged_config")
    def test_empty_string_returns_none(self, mock_config: object) -> None:
        mock_config.return_value = _mock_config(default_effort="")  # type: ignore[union-attr]
        assert _get_default_effort() is None

    @patch("sase.llm_provider.config.load_merged_config")
    def test_missing_key_returns_none(self, mock_config: object) -> None:
        mock_config.return_value = {"llm_provider": {"provider": ""}}  # type: ignore[union-attr]
        assert _get_default_effort() is None

    @patch("sase.llm_provider.config.load_merged_config")
    def test_missing_llm_provider_section_returns_none(
        self, mock_config: object
    ) -> None:
        mock_config.return_value = {}  # type: ignore[union-attr]
        assert _get_default_effort() is None

    @patch("sase.llm_provider.config.load_merged_config")
    def test_invalid_level_returns_none(self, mock_config: object) -> None:
        mock_config.return_value = _mock_config(default_effort="turbo")  # type: ignore[union-attr]
        assert _get_default_effort() is None

    @patch("sase.llm_provider.config.load_merged_config")
    def test_non_string_value_returns_none(self, mock_config: object) -> None:
        mock_config.return_value = _mock_config(default_effort=5)  # type: ignore[union-attr]
        assert _get_default_effort() is None

    @patch("sase.llm_provider.config.load_merged_config")
    def test_normalizes_whitespace_and_case(self, mock_config: object) -> None:
        mock_config.return_value = _mock_config(default_effort="  XHigh  ")  # type: ignore[union-attr]
        assert _get_default_effort() == "xhigh"

    @patch("sase.llm_provider.config.load_merged_config")
    def test_returns_none_on_exception(self, mock_config: object) -> None:
        # get_llm_provider_config swallows load failures and yields {}, so a
        # broken config never forces an effort.
        mock_config.side_effect = RuntimeError("config error")  # type: ignore[union-attr]
        assert _get_default_effort() is None
