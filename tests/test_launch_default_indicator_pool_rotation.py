"""Composed regression test for the launch-default indicator pool-rotation fix.

Reproduces the reported bug end to end against the shipped two-member
``@large`` pool that ``llm_provider.default_model`` delegates to: a real
consuming resolution advances the machine-global round-robin cursor, and one
indicator tick must pick up the new next-in-line member -- without ever
advancing the cursor itself.
"""

from __future__ import annotations

import json

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.llm_override_indicator import LLMOverrideIndicator
from sase.llm_provider import launch_default_peek
from sase.llm_provider.launch_selection import resolve_launch_selection
from sase.llm_provider.load_balancing import rotation_state_path
from sase.llm_provider.model_alias_policy import LARGE_MODEL_ALIAS_NAME
from sase.xprompt.directives import PromptDirectives
from tests._model_alias_defaults_fixture import frozen_selector_provider_model_effort

_POOL_ALIAS = LARGE_MODEL_ALIAS_NAME


@pytest.fixture(autouse=True)
def _force_pool_availability(monkeypatch: pytest.MonkeyPatch) -> None:
    """Route the launch default through the shipped two-member ``@large`` pool.

    Mirrors the setup in ``tests/test_pooled_alias_single_consumption.py``: a
    bare ``claude`` provider config (so ``llm_provider.default_model``
    resolves through the shipped ``@large`` pool) with availability filtering
    disabled so member selection is deterministic regardless of installed
    provider CLIs.
    """
    from sase.llm_provider import config as llm_config

    config = {"provider": "claude"}
    monkeypatch.setattr(llm_config, "get_llm_provider_config", lambda: config)
    monkeypatch.setattr(
        "sase.llm_provider.registry.get_llm_provider_config", lambda: config
    )
    monkeypatch.setattr(llm_config, "_resolved_target_is_available", lambda _t: True)
    llm_config._get_model_aliases_for_token.cache_clear()


def _reset_launch_default_token_cache() -> None:
    """Force the next peek to re-stat rather than reuse a floor-cached token."""
    launch_default_peek._token_cache_deadline = 0.0


def _pool_cursor() -> int:
    path = rotation_state_path()
    if not path.exists():
        return 0
    state = json.loads(path.read_text(encoding="utf-8"))
    entry = state["entries"].get(_POOL_ALIAS)
    return int(entry["cursor"]) if entry else 0


async def test_indicator_pill_follows_pool_rotation_without_consuming() -> None:
    member0 = frozen_selector_provider_model_effort(_POOL_ALIAS, 0)
    member1 = frozen_selector_provider_model_effort(_POOL_ALIAS, 1)

    _reset_launch_default_token_cache()
    async with AcePage() as page:
        indicator = page.query_one_widget(
            "#llm-override-indicator", LLMOverrideIndicator
        )
        await page.wait_for(lambda _state: indicator._cached_default is not None)
        assert indicator._cached_default == (member0[0], member0[1])

        selection = resolve_launch_selection(PromptDirectives(), consume=True)
        assert selection is not None
        assert (selection.provider, selection.model) == (member0[0], member0[1])
        assert _pool_cursor() == 1

        _reset_launch_default_token_cache()
        indicator.refresh()
        await page.wait_for(
            lambda _state: indicator._cached_default == (member1[0], member1[1])
        )

        assert indicator._cached_default == (member1[0], member1[1])
        # The display-only resolve must never itself advance the pool cursor.
        assert _pool_cursor() == 1
