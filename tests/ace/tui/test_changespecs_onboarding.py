"""Tests for PRs-tab onboarding visibility."""

from __future__ import annotations

import pytest
from textual.widgets import Static

from sase.ace.saved_queries import save_query
from sase.ace.testing import AcePage, make_changespec
from sase.ace.tui.actions.changespec._onboarding import ChangeSpecOnboardingMixin
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patch_startup_loaders,
    wait_for_startup,
)


def _mounted_onboarding_plain(page: AcePage) -> str:
    onboarding = page.query_one_widget("#changespec-quickstart-panel")
    return "\n".join(
        getattr(child.render(), "plain", "") for child in onboarding.query(Static)
    )


def _search_query_plain(page: AcePage) -> str:
    search_query_panel = page.query_one_widget("#search-query-panel")
    return getattr(search_query_panel.render(), "plain", "")


async def _open_prs(page: AcePage) -> None:
    await page.press("5")
    await page.expect_state("artifacts_subtab", "prs")


def _assert_changespecs_onboarding_layout(page: AcePage, *, active: bool) -> None:
    changespecs_view = page.query_one_widget("#changespecs-view")
    list_container = page.query_one_widget("#list-container")
    search_query_panel = page.query_one_widget("#search-query-panel")
    detail_container = page.query_one_widget("#detail-container")
    detail_scroll = page.query_one_widget("#detail-scroll")
    expected_chrome_display = not active

    assert changespecs_view.has_class("-onboarding-active") is active
    assert list_container.display is expected_chrome_display
    assert detail_container.display is True
    assert search_query_panel.display is True
    assert detail_scroll.display is expected_chrome_display


class _PredicateApp(ChangeSpecOnboardingMixin):
    def __init__(
        self,
        *,
        loaded: bool,
        filtered_changespecs: list[object] | None = None,
        all_changespecs: list[object] | None = None,
        saved_queries: dict[str, str] | None = None,
    ) -> None:
        self._changespecs_first_load_done = loaded
        self.changespecs = filtered_changespecs or []
        self._all_changespecs = all_changespecs or []
        self._saved_queries = saved_queries or {}


def test_changespecs_onboarding_predicate_requires_loaded_filtered_empty() -> None:
    app = _PredicateApp(loaded=True)

    assert app._should_show_changespecs_onboarding() is True


def test_changespecs_onboarding_predicate_hides_before_first_load() -> None:
    app = _PredicateApp(loaded=False)

    assert app._should_show_changespecs_onboarding() is False


def test_changespecs_onboarding_predicate_ignores_saved_queries() -> None:
    app = _PredicateApp(loaded=True, saved_queries={"1": '"visual"'})

    assert app._should_show_changespecs_onboarding() is True


def test_changespecs_onboarding_predicate_hides_when_filtered_specs_exist() -> None:
    app = _PredicateApp(loaded=True, filtered_changespecs=[object()])

    assert app._should_show_changespecs_onboarding() is False


def test_changespecs_onboarding_predicate_uses_filtered_changespecs() -> None:
    app = _PredicateApp(loaded=True, all_changespecs=[object()])

    assert app._should_show_changespecs_onboarding() is True


async def test_changespecs_onboarding_visible_after_empty_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=[])

    async with AcePage(
        query='"visual"',
        changespecs=[],
        initial_tab="changespecs",
    ) as page:
        await wait_for_startup(page)
        await _open_prs(page)
        await page.expect_state("tab", "changespecs")
        await page.expect_state("total", 0)

        onboarding = page.query_one_widget("#changespec-quickstart-panel")
        assert not onboarding.has_class("hidden")
        _assert_changespecs_onboarding_layout(page, active=True)
        assert "Every PR your agents produce" in _mounted_onboarding_plain(page)
        search = _search_query_plain(page)
        assert "Search Query" in search
        assert '"visual"' in search


async def test_changespecs_onboarding_visible_when_saved_queries_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=[])
    assert save_query("1", '"visual"')

    async with AcePage(
        query='"visual"',
        changespecs=[],
        initial_tab="changespecs",
    ) as page:
        await wait_for_startup(page)
        await _open_prs(page)
        await page.expect_state("total", 0)

        onboarding = page.query_one_widget("#changespec-quickstart-panel")
        assert not onboarding.has_class("hidden")
        _assert_changespecs_onboarding_layout(page, active=True)


async def test_changespecs_onboarding_hidden_when_changespecs_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=[])

    async with AcePage(
        query='"visual"',
        changespecs=[make_changespec(name="visual_first")],
        initial_tab="changespecs",
    ) as page:
        await wait_for_startup(page)
        await _open_prs(page)
        await page.expect_state("total", 1)

        onboarding = page.query_one_widget("#changespec-quickstart-panel")
        assert onboarding.has_class("hidden")
        _assert_changespecs_onboarding_layout(page, active=False)


async def test_changespecs_onboarding_visible_when_specs_are_filtered_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=[])

    async with AcePage(
        query='"missing"',
        changespecs=[make_changespec(name="visual_first")],
        initial_tab="changespecs",
    ) as page:
        await wait_for_startup(page)
        await _open_prs(page)
        await page.expect_state("total", 0)
        assert page.app._all_changespecs

        onboarding = page.query_one_widget("#changespec-quickstart-panel")
        assert not onboarding.has_class("hidden")
        _assert_changespecs_onboarding_layout(page, active=True)
        assert "No PRs match this query" in _mounted_onboarding_plain(page)
        assert "1 exists" in _mounted_onboarding_plain(page)
        assert '"missing"' in _search_query_plain(page)


async def test_changespecs_onboarding_hides_after_first_changespec_arrives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=[])

    async with AcePage(
        query='"visual"',
        changespecs=[],
        initial_tab="changespecs",
    ) as page:
        await wait_for_startup(page)
        await _open_prs(page)
        assert "Every PR your agents produce" in _mounted_onboarding_plain(page)

        page.app._apply_reloaded_changespecs(
            [make_changespec(name="visual_first")],
            current_name=None,
        )
        await page.pause()
        await page.expect_state("total", 1)

        onboarding = page.query_one_widget("#changespec-quickstart-panel")
        assert onboarding.has_class("hidden")
        _assert_changespecs_onboarding_layout(page, active=False)


async def test_changespecs_onboarding_reappears_after_last_changespec_disappears(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=[])

    async with AcePage(
        query='"visual"',
        changespecs=[make_changespec(name="visual_first")],
        initial_tab="changespecs",
    ) as page:
        await wait_for_startup(page)
        await _open_prs(page)
        await page.expect_state("total", 1)

        page.app._apply_reloaded_changespecs([], current_name="visual_first")
        await page.pause()
        await page.expect_state("total", 0)

        onboarding = page.query_one_widget("#changespec-quickstart-panel")
        assert not onboarding.has_class("hidden")
        _assert_changespecs_onboarding_layout(page, active=True)


async def test_changespecs_onboarding_ignores_saved_query_cache_invalidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=[])

    async with AcePage(
        query='"visual"',
        changespecs=[],
        initial_tab="changespecs",
    ) as page:
        await wait_for_startup(page)
        await _open_prs(page)
        _assert_changespecs_onboarding_layout(page, active=True)

        assert save_query("1", '"visual"')
        page.app._invalidate_saved_queries_cache()
        await page.pause()

        onboarding = page.query_one_widget("#changespec-quickstart-panel")
        assert not onboarding.has_class("hidden")
        _assert_changespecs_onboarding_layout(page, active=True)
