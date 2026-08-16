"""Unit tests for the lock-free launch-default change-detection token."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.llm_provider import launch_default_peek
from sase.llm_provider.load_balancing import (
    ModelAliasSelector,
    rotation_state_path,
    select_model_alias_pool_member,
)
from sase.llm_provider.model_launch_settings import (
    DEFAULT_MODEL_FIELD,
    launch_model_setting_override_key,
)
from sase.llm_provider.provider_disable_peek import provider_disable_state_path
from sase.llm_provider.temporary_override_state import state_path as override_state_path


@pytest.fixture(autouse=True)
def reset_token_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(launch_default_peek, "_token_cache_deadline", 0.0)
    monkeypatch.setattr(launch_default_peek, "_token_cache_value", ())


def test_token_is_stable_across_repeated_calls_when_nothing_changes() -> None:
    first = launch_default_peek.peek_launch_default_change_token()
    launch_default_peek._token_cache_deadline = 0.0

    second = launch_default_peek.peek_launch_default_change_token()

    assert first == second


def test_missing_state_files_yield_a_stable_token_rather_than_raising() -> None:
    assert not rotation_state_path().exists()
    assert not override_state_path().exists()
    assert not provider_disable_state_path().exists()

    token = launch_default_peek.peek_launch_default_change_token()
    launch_default_peek._token_cache_deadline = 0.0

    assert launch_default_peek.peek_launch_default_change_token() == token


def test_token_changes_after_pool_cursor_advances() -> None:
    before = launch_default_peek.peek_launch_default_change_token()

    selector = ModelAliasSelector(mode="round_robin", members=("m0", "m1"))
    select_model_alias_pool_member(
        launch_model_setting_override_key(DEFAULT_MODEL_FIELD),
        selector,
        [True, True],
        consume=True,
    )
    launch_default_peek._token_cache_deadline = 0.0

    after = launch_default_peek.peek_launch_default_change_token()

    assert before != after


def test_token_changes_when_override_state_file_changes() -> None:
    before = launch_default_peek.peek_launch_default_change_token()

    path = override_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}", encoding="utf-8")
    launch_default_peek._token_cache_deadline = 0.0

    after = launch_default_peek.peek_launch_default_change_token()

    assert before != after


def test_token_changes_when_provider_disable_state_file_changes() -> None:
    before = launch_default_peek.peek_launch_default_change_token()

    path = provider_disable_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}", encoding="utf-8")
    launch_default_peek._token_cache_deadline = 0.0

    after = launch_default_peek.peek_launch_default_change_token()

    assert before != after


def test_stat_error_other_than_missing_degrades_to_sentinel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(path: Path) -> object:
        del path
        raise PermissionError("nope")

    monkeypatch.setattr(Path, "stat", boom)

    token = launch_default_peek.peek_launch_default_change_token()

    assert token == launch_default_peek._TOKEN_ERROR_SENTINEL
