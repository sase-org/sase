"""Accessor coverage for ``ace.prompt_stash.trash_limit``."""

from __future__ import annotations

from typing import Any

import pytest

from sase.ace.config import get_ace_prompt_stash_trash_limit
from sase.config.core import clear_config_cache, load_merged_config


def test_bundled_default_trash_limit_is_20() -> None:
    assert load_merged_config()["ace"]["prompt_stash"]["trash_limit"] == 20
    assert get_ace_prompt_stash_trash_limit() == 20


def test_get_trash_limit_reads_merged_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.config.load_merged_config",
        lambda: {"ace": {"prompt_stash": {"trash_limit": 5}}},
    )

    assert get_ace_prompt_stash_trash_limit() == 5


def test_get_trash_limit_accepts_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.config.load_merged_config",
        lambda: {"ace": {"prompt_stash": {"trash_limit": 0}}},
    )

    assert get_ace_prompt_stash_trash_limit() == 0


@pytest.mark.parametrize(
    "config",
    [
        {},
        {"ace": {}},
        {"ace": None},
        {"ace": {"prompt_stash": None}},
        {"ace": {"prompt_stash": {}}},
        {"ace": {"prompt_stash": {"trash_limit": -1}}},
        {"ace": {"prompt_stash": {"trash_limit": True}}},
        {"ace": {"prompt_stash": {"trash_limit": False}}},
        {"ace": {"prompt_stash": {"trash_limit": "20"}}},
        {"ace": {"prompt_stash": {"trash_limit": 20.0}}},
        {"ace": {"prompt_stash": {"trash_limit": None}}},
    ],
)
def test_get_trash_limit_falls_back_for_invalid_values(
    monkeypatch: pytest.MonkeyPatch,
    config: dict[str, object],
) -> None:
    monkeypatch.setattr("sase.ace.config.load_merged_config", lambda: config)

    assert get_ace_prompt_stash_trash_limit() == 20


def test_get_trash_limit_falls_back_when_config_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable() -> dict[str, Any]:
        raise OSError("config unavailable")

    monkeypatch.setattr("sase.ace.config.load_merged_config", unavailable)

    assert get_ace_prompt_stash_trash_limit() == 20


def test_get_trash_limit_observes_user_config_after_cache_clear() -> None:
    from sase.config.core import CONFIG_DIR

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    (CONFIG_DIR / "sase.yml").write_text(
        "ace:\n  prompt_stash:\n    trash_limit: 7\n", encoding="utf-8"
    )
    clear_config_cache()

    assert get_ace_prompt_stash_trash_limit() == 7
