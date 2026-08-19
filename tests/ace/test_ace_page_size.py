"""Accessor coverage for ``ace.page_size``."""

from __future__ import annotations

from typing import Any

import pytest

from sase.ace.config import get_ace_page_size
from sase.config.core import clear_config_cache, load_merged_config


def test_bundled_default_page_size_is_100() -> None:
    assert load_merged_config()["ace"]["page_size"] == 100
    assert get_ace_page_size() == 100


def test_get_ace_page_size_reads_merged_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.ace.config.load_merged_config",
        lambda: {"ace": {"page_size": 25}},
    )

    assert get_ace_page_size() == 25


@pytest.mark.parametrize(
    "config",
    [
        {},
        {"ace": {}},
        {"ace": None},
        {"ace": {"page_size": 0}},
        {"ace": {"page_size": -1}},
        {"ace": {"page_size": True}},
        {"ace": {"page_size": "100"}},
        {"ace": {"page_size": None}},
    ],
)
def test_get_ace_page_size_falls_back_for_invalid_values(
    monkeypatch: pytest.MonkeyPatch,
    config: dict[str, object],
) -> None:
    monkeypatch.setattr("sase.ace.config.load_merged_config", lambda: config)

    assert get_ace_page_size() == 100


def test_get_ace_page_size_falls_back_when_config_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable() -> dict[str, Any]:
        raise OSError("config unavailable")

    monkeypatch.setattr("sase.ace.config.load_merged_config", unavailable)

    assert get_ace_page_size() == 100


def test_get_ace_page_size_observes_user_config_after_cache_clear() -> None:
    from sase.config.core import CONFIG_DIR

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    (CONFIG_DIR / "sase.yml").write_text("ace:\n  page_size: 40\n", encoding="utf-8")
    clear_config_cache()

    assert get_ace_page_size() == 40
