"""Tests for agent list bead badge rendering."""

from __future__ import annotations

import pytest

import sase.ace.tui.models.agent_bead as agent_bead_model
from sase.ace.tui.models.agent_bead import (
    _BeadDisplayCache,
    _bead_display_cache_key,
    resolve_bead_display,
    should_resolve_bead_display,
)
from sase.ace.tui.widgets._agent_list_rendering import format_agent_option
from tests.ace.tui.widgets._agent_display_helpers import (
    clear_bead_display_cache,
    confirm_bead,
    make_agent,
)

pytestmark = pytest.mark.usefixtures("clear_bead_display_cache")


def _install_expired_cache(
    agent,
    value: str | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = _BeadDisplayCache(ttl_seconds=60.0, max_entries=16)
    key = _bead_display_cache_key(agent)
    assert key is not None
    cache._entries[key] = (-1.0, value)
    monkeypatch.setattr(agent_bead_model, "_BEAD_DISPLAY_CACHE", cache)


def test_missing_cache_entries_back_off_longer_than_confirmed_hits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 100.0
    monkeypatch.setattr(agent_bead_model, "monotonic", lambda: now)
    cache = _BeadDisplayCache(
        ttl_seconds=60.0,
        miss_ttl_seconds=300.0,
        max_entries=16,
    )
    hit_key = ("sase-hit", None, None)
    miss_key = ("sase-miss", None, None)
    cache.set(hit_key, "sase-hit")
    cache.set(miss_key, None)

    now = 161.0
    assert cache.should_resolve(hit_key) is True
    assert cache.should_resolve(miss_key) is False

    now = 401.0
    assert cache.should_resolve(miss_key) is True


class TestAgentListBeadBadge:
    def test_confirmed_phase_agent_row_renders_bead_badge(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = make_agent(agent_name="sase-x.3")
        confirm_bead(agent, monkeypatch)

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert " ◆ sase-x.3" in left.plain

    def test_confirmed_land_agent_row_renders_epic_bead_badge(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = make_agent(agent_name="sase-x.land")
        confirm_bead(agent, monkeypatch)

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert " ◆ sase-x.land" in left.plain

    def test_confirmed_exact_land_agent_row_renders_epic_bead_badge(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = make_agent(agent_name="sase-x")
        confirm_bead(agent, monkeypatch)

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert " ◆ sase-x" in left.plain

    def test_confirmed_dismissed_phase_agent_row_renders_bead_badge(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = make_agent(agent_name="260428.sase-x.3")
        confirm_bead(agent, monkeypatch)

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert " ◆ 260428.sase-x.3" in left.plain

    def test_expired_confirmed_bead_row_keeps_badge_and_revalidates(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = make_agent(agent_name="sase-x.3")
        _install_expired_cache(agent, "sase-x.3 - stale description", monkeypatch)

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert " ◆ sase-x.3" in left.plain
        assert should_resolve_bead_display(agent) is True

    def test_cold_bead_candidate_row_omits_bead_badge(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Bead-shaped name, but the cache has not confirmed it exists yet. Row
        # formatting must never touch bead storage to decide the glyph.
        agent = make_agent(agent_name="sase-x.3")

        def fail_lookup(candidate_id: str, **_: object) -> object:
            raise AssertionError("row formatting must not touch bead storage")

        monkeypatch.setattr("sase.agent.bead_display._lookup_bead_issue", fail_lookup)

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert "◆" not in left.plain

    def test_missing_bead_candidate_row_omits_bead_badge(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = make_agent(agent_name="sase-x.3")
        monkeypatch.setattr(
            "sase.agent.bead_display._lookup_bead_issue",
            lambda candidate_id, **_: None,
        )
        resolve_bead_display(agent)

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert "◆" not in left.plain

    def test_deleted_bead_candidate_row_drops_badge_after_reresolve(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = make_agent(agent_name="sase-x.3")
        _install_expired_cache(agent, "sase-x.3 - stale description", monkeypatch)
        monkeypatch.setattr(
            "sase.agent.bead_display._lookup_bead_issue",
            lambda candidate_id, **_: None,
        )

        resolve_bead_display(agent)
        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert "◆" not in left.plain

    def test_ordinary_agent_row_omits_bead_badge(self) -> None:
        agent = make_agent(agent_name="reviewer")

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert "◆" not in left.plain

    def test_dotted_ordinary_agent_row_omits_bead_badge(self) -> None:
        agent = make_agent(agent_name="aij.2")

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert "◆" not in left.plain
        assert " aij.2" in left.plain
        assert "[aij.2]" not in left.plain

    def test_bead_badge_flows_from_fold_annotation_to_agent_name(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = make_agent(agent_name="sase-x.3", tag="pinned")
        confirm_bead(agent, monkeypatch)

        left, _, _ = format_agent_option(
            agent, 0, is_selected=False, fold_annotation="×3"
        )

        assert "(RUNNING)×3 ◆ sase-x.3" in left.plain
        assert "[pinned]" not in left.plain
