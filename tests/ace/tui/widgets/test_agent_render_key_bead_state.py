"""Tests for bead-state render-key extraction."""

from __future__ import annotations

import pytest

from ._agent_render_cache_helpers import agent as _agent
from ._agent_render_cache_helpers import bead_key as _bead_key


def test_render_key_changes_when_confirmed_bead_state_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui.models.agent_bead import (
        _BEAD_DISPLAY_CACHE,
        resolve_bead_display,
    )
    from sase.bead.model import Issue

    _BEAD_DISPLAY_CACHE.clear()
    try:
        a = _agent(agent_name="sase-x.3")
        k_cold = _bead_key(a)

        monkeypatch.setattr(
            "sase.agent.bead_display.lookup_bead_issue",
            lambda candidate_id, **_: Issue(id=candidate_id, title="", description=""),
        )
        resolve_bead_display(a)
        k_confirmed = _bead_key(a)

        assert k_cold != k_confirmed
    finally:
        _BEAD_DISPLAY_CACHE.clear()


def test_render_key_preserves_confirmed_bead_state_after_cache_expiry() -> None:
    from sase.ace.tui.models.agent_bead import (
        _BEAD_DISPLAY_CACHE,
        _bead_display_cache_key,
    )

    _BEAD_DISPLAY_CACHE.clear()
    try:
        a = _agent(agent_name="sase-x.3")
        key = _bead_display_cache_key(a)
        assert key is not None
        _BEAD_DISPLAY_CACHE.set(key, "sase-x.3")
        k_fresh = _bead_key(a)

        _BEAD_DISPLAY_CACHE._entries[key] = (-1.0, "sase-x.3")
        k_expired = _bead_key(a)

        assert k_expired == k_fresh
    finally:
        _BEAD_DISPLAY_CACHE.clear()


def test_render_key_unchanged_when_unconfirmed_candidate_resolves_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The candidate id alone must not bust the row cache: a cold candidate and a
    # candidate confirmed-missing both render no glyph, so their keys match.
    from sase.ace.tui.models.agent_bead import (
        _BEAD_DISPLAY_CACHE,
        resolve_bead_display,
    )

    _BEAD_DISPLAY_CACHE.clear()
    try:
        a = _agent(agent_name="sase-x.3")
        k_cold = _bead_key(a)

        monkeypatch.setattr(
            "sase.agent.bead_display.lookup_bead_issue",
            lambda candidate_id, **_: None,
        )
        resolve_bead_display(a)
        k_missing = _bead_key(a)

        assert k_cold == k_missing
    finally:
        _BEAD_DISPLAY_CACHE.clear()
