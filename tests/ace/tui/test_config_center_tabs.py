"""Behavioral coverage for the home-first, lazy SASE Admin Center."""

from __future__ import annotations

import asyncio
import subprocess
import sys
from typing import Any

import pytest
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widget import Widget
from textual.widgets import ContentSwitcher, Input, Static

from sase.ace.testing import AcePage
from sase.ace.tui import AceApp
from sase.ace.tui.modals.config_center_modal import (
    _AdminCenterLanding,
    _AdminCenterLandingRow,
    _HOME_ID,
    _HOME_LEAD,
    _HOME_ORIENTATION,
    _PANEL_TABS,
    _TAB_COLORS,
    _TAB_DESCRIPTIONS,
    _TAB_LABELS,
    _TAB_ORDER,
    _TAB_SPECS,
    _TITLE_LABEL,
    _TITLE_TEXT,
    _TITLE_UNDERLINE,
    _home_hint_text,
    CenterTab,
    ConfigCenterModal,
    validated_center_tab,
)
from sase.ace.tui.widgets.panel_tab_strip import PanelTab, PanelTabStrip


class _HostApp(App[None]):
    pass


class _StubPane(Static):
    can_focus = True

    def __init__(self, tab: CenterTab) -> None:
        super().__init__(f"stub {tab}", id=tab)
        self.tab = tab
        self.visibility: list[bool] = []
        self.focus_count = 0
        self.saved_state = ""

    def on_center_tab_visibility_changed(self, active: bool) -> None:
        self.visibility.append(active)

    def focus_default(self) -> None:
        self.focus_count += 1
        self.focus()


class _InputPane(Vertical):
    """Working pane whose filter must retain literal opener characters."""

    def __init__(self, tab: CenterTab) -> None:
        super().__init__(id=tab)

    def compose(self) -> ComposeResult:
        yield Input(id="stub-filter")

    def focus_default(self) -> None:
        self.query_one(Input).focus()


async def _wait_until(pilot: Any, predicate: Any, *, timeout: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError("Admin Center test condition timed out")
        await pilot.pause()


def _patch_stub_panes(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict[CenterTab, list[_StubPane]], list[CenterTab]]:
    created: dict[CenterTab, list[_StubPane]] = {}
    calls: list[CenterTab] = []

    def create(_self: ConfigCenterModal, tab: CenterTab) -> _StubPane:
        calls.append(tab)
        pane = _StubPane(tab)
        created.setdefault(tab, []).append(pane)
        return pane

    monkeypatch.setattr(ConfigCenterModal, "_create_pane", create)
    return created, calls


def test_catalog_is_the_single_numbered_alphabetical_source() -> None:
    assert tuple(spec.id for spec in _TAB_SPECS) == _TAB_ORDER
    assert tuple(spec.number for spec in _TAB_SPECS) == tuple(range(1, 8))
    assert tuple((spec.id, spec.label) for spec in _TAB_SPECS) == tuple(_TAB_LABELS)
    assert tuple(spec.id for spec in _TAB_SPECS) == tuple(_TAB_COLORS)
    assert tuple(spec.id for spec in _TAB_SPECS) == tuple(_TAB_DESCRIPTIONS)
    assert list(_TAB_ORDER) == sorted(
        _TAB_ORDER,
        key=lambda tab: dict(_TAB_LABELS)[tab].casefold(),
    )
    assert [spec.description for spec in _TAB_SPECS] == [
        "Review and edit layered SASE settings with provenance and live previews.",
        "Inspect TUI activity, launch failures, and notification history.",
        "Manage projects and inspect their repositories and workspaces.",
        "Explore agent activity, runtime, outcomes, and trends over time.",
        "Follow background work, inspect live output, and manage running jobs.",
        "Update SASE, plugins, and supported agent CLIs from one place.",
        "Find, preview, and load reusable prompts and workflows.",
    ]


def test_numbered_tab_strip_plain_text_and_click_ranges_without_selection() -> None:
    strip = PanelTabStrip(_PANEL_TABS, None, show_numbers=True)
    text = strip._build_content()
    plain = text.plain

    for spec in _TAB_SPECS:
        cell = f"{spec.number} {spec.label}"
        start, end = strip._tab_ranges[spec.id]
        assert plain[start:end].strip() == cell
        label_offset = plain.index(spec.label)
        assert any(
            span.start <= label_offset < span.end and str(span.style) == "#888888"
            for span in text.spans
        )


async def test_tab_strip_can_uppercase_only_the_active_canonical_label() -> None:
    tabs = (
        PanelTab("prs", "PRs", "green"),
        PanelTab("commits", "Commits", "yellow"),
    )

    class _TabStripApp(App[None]):
        def compose(self):  # type: ignore[no-untyped-def]
            yield PanelTabStrip(tabs, "prs", uppercase_active=True)

    async with _TabStripApp().run_test() as pilot:
        strip = pilot.app.query_one(PanelTabStrip)
        assert strip._build_content().plain == " PRS  │  Commits "
        strip.set_active_tab("commits")
        assert strip._build_content().plain == " PRs  │  COMMITS "


def test_title_has_no_leading_icon_and_underline_matches() -> None:
    assert _TITLE_TEXT == "SASE Admin Center"
    assert _TITLE_TEXT == _TITLE_LABEL
    assert not _TITLE_TEXT.startswith("⎈")
    assert len(_TITLE_UNDERLINE) == len(_TITLE_TEXT)


def test_resume_tab_validation_accepts_only_catalog_ids() -> None:
    assert validated_center_tab("tasks") == "tasks"
    assert validated_center_tab("missing") is None
    assert validated_center_tab(5) is None


def test_home_hint_explains_no_history_and_uses_catalog_resume_style() -> None:
    no_history = _home_hint_text(None, "number_sign", compact=False)
    assert no_history.plain.startswith(" #  resumes after your first section visit")
    assert "1-7/click · Tab cycle" in no_history.plain

    resume_ready = _home_hint_text("tasks", "f2", compact=False)
    assert resume_ready.plain.startswith(" f2  resume Tasks")
    target_offset = resume_ready.plain.index("resume Tasks")
    assert any(
        span.start <= target_offset < span.end and str(span.style) == "bold #5FD75F"
        for span in resume_ready.spans
    )


def test_tab_cycle_bindings_are_modal_priority() -> None:
    bindings = {
        binding.key: binding
        for binding in ConfigCenterModal.BINDINGS
        if isinstance(binding, Binding)
    }
    assert bindings["tab"].action == "next_center_tab"
    assert bindings["tab"].priority is True
    assert bindings["shift+tab"].action == "prev_center_tab"
    assert bindings["shift+tab"].priority is True


async def test_generic_modal_is_static_home_with_no_concrete_panes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_create(_self: ConfigCenterModal, _tab: CenterTab) -> _StubPane:
        raise AssertionError("home must not construct a pane")

    monkeypatch.setattr(ConfigCenterModal, "_create_pane", fail_create)
    async with _HostApp().run_test(size=(120, 40)) as pilot:
        modal = ConfigCenterModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        switcher = modal.query_one("#config-center-switcher", ContentSwitcher)
        caption = modal.query_one("#config-center-tab-description", Static)
        assert modal._active_tab is None
        assert modal._panes == {}
        assert switcher.current == _HOME_ID
        assert caption.render().plain == _HOME_ORIENTATION
        assert (
            modal.query_one("#admin-center-home-lead", Static).render().plain
            == _HOME_LEAD
        )
        assert modal.query_one("#admin-center-home-hint", Static).render().plain == (
            _home_hint_text(None, "number_sign", compact=False).plain
        )
        rows = list(modal.query(_AdminCenterLandingRow))
        assert len(rows) == len(_TAB_SPECS)
        for row, spec in zip(rows, _TAB_SPECS, strict=True):
            assert row.id == f"admin-center-home-row-{spec.id}"
            assert (
                row.query_one(".admin-center-home-row-key", Static).render().plain
                == f" {spec.number} "
            )
            assert (
                row.query_one(".admin-center-home-row-label", Static)
                .render()
                .plain.rstrip()
                == spec.label
            )
            assert (
                row.query_one(".admin-center-home-row-description", Static)
                .render()
                .plain
                == spec.description
            )
            assert not modal.query(f"#{spec.id}")


def test_importing_lightweight_modal_does_not_import_concrete_panes() -> None:
    pane_modules = [
        "config_pane",
        "logs_pane",
        "projects_pane",
        "statistics_pane",
        "tasks_pane",
        "plugins_browser_pane",
        "xprompt_browser_pane",
    ]
    script = "\n".join(
        (
            "import sys",
            "import sase.ace.tui.modals.config_center_modal",
            f"names = {pane_modules!r}",
            "loaded = [name for name in names if f'sase.ace.tui.modals.{name}' in sys.modules]",
            "assert not loaded, loaded",
        )
    )
    subprocess.run([sys.executable, "-c", script], check=True)


async def test_home_tab_directions_and_digits_mount_only_requested_panes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created, calls = _patch_stub_panes(monkeypatch)
    async with AcePage(initial_tab="agents") as page:
        modal = ConfigCenterModal()
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")

        await page.press("shift+tab")
        await page.wait_for(lambda _state: modal._active_tab == "xprompts")
        assert calls == ["xprompts"]
        assert page.app.current_tab == "agents"

        await page.press("tab")
        await page.wait_for(lambda _state: modal._active_tab == "config")
        assert calls == ["xprompts", "config"]
        assert page.app.current_tab == "agents"

        for spec in _TAB_SPECS[1:]:
            await page.press(str(spec.number))
            await page.wait_for(lambda _state, tab=spec.id: modal._active_tab == tab)
            assert modal.query_one(
                "#config-center-switcher", ContentSwitcher
            ).current == (spec.id)
            assert modal.query_one(
                "#config-center-tabs", PanelTabStrip
            )._active_tab == (spec.id)
            caption = modal.query_one("#config-center-tab-description", Static).content
            assert isinstance(caption, Text)
            assert caption.plain == f"› {spec.description}"
            assert str(caption.style) == spec.accent
            assert created[spec.id][0].focus_count >= 1
            assert page.app.current_tab == "agents"

        before = list(calls)
        for digit in ("8", "9", "0"):
            await page.press(digit)
            await page.pause()
        assert calls == before
        assert modal._active_tab == "xprompts"


async def test_tab_click_mounts_target_and_reentry_reuses_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created, calls = _patch_stub_panes(monkeypatch)
    async with _HostApp().run_test() as pilot:
        modal = ConfigCenterModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        modal._on_tab_clicked(PanelTabStrip.TabClicked("projects"))
        await _wait_until(pilot, lambda: modal._active_tab == "projects")
        pane = created["projects"][0]
        pane.saved_state = "preserved"

        await modal._switch_to("logs")
        await modal._switch_to("projects")

        assert calls == ["projects", "logs"]
        assert modal._panes["projects"] is pane
        assert pane.saved_state == "preserved"
        assert pane.visibility == [True, False, True]


async def test_landing_row_click_mounts_exact_target_and_focuses_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created, calls = _patch_stub_panes(monkeypatch)
    async with _HostApp().run_test(size=(120, 40)) as pilot:
        modal = ConfigCenterModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.click("#admin-center-home-row-projects")
        await _wait_until(pilot, lambda: modal._active_tab == "projects")

        assert calls == ["projects"]
        assert tuple(modal._panes) == ("projects",)
        assert created["projects"][0].focus_count >= 1
        assert (
            modal.query_one("#config-center-switcher", ContentSwitcher).current
            == "projects"
        )


async def test_landing_is_keyboard_transparent_and_digits_work_immediately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created, calls = _patch_stub_panes(monkeypatch)
    async with _HostApp().run_test(size=(120, 40)) as pilot:
        modal = ConfigCenterModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        landing = modal.query_one(_AdminCenterLanding)
        landing_widgets = [landing, *landing.query("*")]
        assert all(not widget.can_focus for widget in landing_widgets)

        await pilot.press("4")
        await _wait_until(pilot, lambda: modal._active_tab == "statistics")

        assert calls == ["statistics"]
        assert created["statistics"][0].focus_count >= 1


async def test_landing_compact_class_tracks_viewport_size() -> None:
    async with AcePage(query="!!!", changespecs=[], size=(120, 40)) as page:
        modal = ConfigCenterModal()
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")
        await page.wait_for(lambda _state: bool(modal.query(_AdminCenterLanding)))

        landing = modal.query_one(_AdminCenterLanding)
        key = modal.query_one(".admin-center-home-row-key", Static)
        assert not landing.has_class("-compact")
        assert key.render().plain == " 1 "

        await page._pilot.resize_terminal(100, 24)  # noqa: SLF001
        await _wait_until(page, lambda: landing.has_class("-compact"))
        assert key.render().plain == "1"

        await page._pilot.resize_terminal(120, 40)  # noqa: SLF001
        await _wait_until(page, lambda: not landing.has_class("-compact"))
        assert key.render().plain == " 1 "


async def test_repeated_first_navigation_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created, calls = _patch_stub_panes(monkeypatch)
    async with _HostApp().run_test() as pilot:
        modal = ConfigCenterModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        results = await asyncio.gather(
            modal._switch_to("tasks"),
            modal._switch_to("tasks"),
            modal._switch_to("tasks"),
        )

        assert results == [True, True, True]
        assert calls == ["tasks"]
        assert len(created["tasks"]) == 1
        assert len(modal.query("#tasks")) == 1


async def test_repeated_opener_without_history_keeps_one_zero_pane_home(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_create(_self: ConfigCenterModal, _tab: CenterTab) -> _StubPane:
        raise AssertionError("an absent resume target must not construct a pane")

    monkeypatch.setattr(ConfigCenterModal, "_create_pane", fail_create)
    async with AcePage(initial_tab="agents") as page:
        assert page.app._last_admin_center_tab is None
        await page.press("number_sign")
        await page.expect_modal("ConfigCenterModal")
        modal = page.app.screen
        assert isinstance(modal, ConfigCenterModal)

        await page.press("number_sign", "number_sign")
        await page.pause()

        assert page.app.screen is modal
        assert len(page.app.screen_stack) == 2
        assert modal._active_tab is None
        assert modal._panes == {}


async def test_construction_failure_keeps_home_and_allows_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0

    def create(_self: ConfigCenterModal, tab: CenterTab) -> _StubPane:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("synthetic construction failure")
        return _StubPane(tab)

    monkeypatch.setattr(ConfigCenterModal, "_create_pane", create)
    async with _HostApp().run_test() as pilot:
        modal = ConfigCenterModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        assert await modal._switch_to("config") is False
        assert modal._active_tab is None
        assert modal.query_one("#config-center-switcher", ContentSwitcher).current == (
            _HOME_ID
        )
        assert modal.query_one("#config-center-tabs", PanelTabStrip)._active_tab is None

        assert await modal._switch_to("config") is True
        assert modal._active_tab == "config"
        assert attempts == 2


async def test_mount_failure_keeps_home_and_allows_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_stub_panes(monkeypatch)
    original_add_content = ContentSwitcher.add_content
    attempts = 0

    def flaky_add_content(
        switcher: ContentSwitcher,
        widget: Widget,
        *,
        id: str | None = None,
        set_current: bool = False,
    ) -> Any:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("synthetic mount failure")
        return original_add_content(
            switcher,
            widget,
            id=id,
            set_current=set_current,
        )

    monkeypatch.setattr(ContentSwitcher, "add_content", flaky_add_content)
    async with _HostApp().run_test() as pilot:
        modal = ConfigCenterModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        assert await modal._switch_to("logs") is False
        assert modal._active_tab is None
        assert modal._panes == {}
        assert not modal.query("#logs")

        assert await modal._switch_to("logs") is True
        assert modal._active_tab == "logs"
        assert attempts == 2


async def test_direct_initial_tab_mounts_only_that_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _created, calls = _patch_stub_panes(monkeypatch)
    async with _HostApp().run_test() as pilot:
        modal = ConfigCenterModal(initial_tab="updates", auto_update=True)
        assert modal.check_action("resume_last_tab", ()) is False
        pilot.app.push_screen(modal)
        await _wait_until(pilot, lambda: modal._active_tab == "updates")

        assert calls == ["updates"]
        assert tuple(modal._panes) == ("updates",)
        assert modal._auto_update is True


async def test_generic_reopen_is_home_first_then_repeated_opener_resumes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _created, calls = _patch_stub_panes(monkeypatch)
    async with AcePage(initial_tab="agents") as page:
        await page.press("number_sign")
        await page.expect_modal("ConfigCenterModal")
        first = page.app.screen
        assert isinstance(first, ConfigCenterModal)
        assert first._active_tab is None

        await page.press("5")
        await page.wait_for(lambda _state: first._active_tab == "tasks")
        await page.press("escape")
        await page.expect_no_modal()
        assert page.app._last_admin_center_tab == "tasks"

        await page.press("number_sign")
        await page.expect_modal("ConfigCenterModal")
        second = page.app.screen
        assert isinstance(second, ConfigCenterModal)
        assert second is not first
        assert second._active_tab is None
        assert second._panes == {}

        await page.press("number_sign", "number_sign", "number_sign")
        await page.wait_for(lambda _state: second._active_tab == "tasks")

        assert calls == ["tasks", "tasks"]
        assert tuple(second._panes) == ("tasks",)
        assert page.app.screen is second
        assert len(page.app.screen_stack) == 2
        assert page.app.current_tab == "agents"


async def test_switching_changes_resume_target_and_home_only_close_retains_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_stub_panes(monkeypatch)
    async with AcePage() as page:
        page.app._last_admin_center_tab = "tasks"
        await page.press("number_sign")
        await page.expect_modal("ConfigCenterModal")
        modal = page.app.screen
        assert isinstance(modal, ConfigCenterModal)

        await page.press("number_sign")
        await page.wait_for(lambda _state: modal._active_tab == "tasks")
        await page.press("2")
        await page.wait_for(lambda _state: modal._active_tab == "logs")
        await page.press("escape")
        await page.expect_no_modal()
        assert page.app._last_admin_center_tab == "logs"

        await page.press("number_sign")
        await page.expect_modal("ConfigCenterModal")
        home = page.app.screen
        assert isinstance(home, ConfigCenterModal)
        assert home._active_tab is None
        await page.press("escape")
        await page.expect_no_modal()
        assert page.app._last_admin_center_tab == "logs"


async def test_direct_entry_establishes_resume_target_after_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_stub_panes(monkeypatch)
    async with AcePage() as page:
        page.app.action_open_tasks_panel()
        await page.expect_modal("ConfigCenterModal")
        modal = page.app.screen
        assert isinstance(modal, ConfigCenterModal)
        await page.wait_for(lambda _state: modal._active_tab == "tasks")

        await page.press("escape")
        await page.expect_no_modal()

        assert page.app._last_admin_center_tab == "tasks"


async def test_failed_resume_retains_prior_target_and_remains_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0

    def create(_self: ConfigCenterModal, tab: CenterTab) -> _StubPane:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("synthetic resume failure")
        return _StubPane(tab)

    monkeypatch.setattr(ConfigCenterModal, "_create_pane", create)
    async with AcePage() as page:
        page.app._last_admin_center_tab = "tasks"
        await page.press("number_sign")
        await page.expect_modal("ConfigCenterModal")
        modal = page.app.screen
        assert isinstance(modal, ConfigCenterModal)

        await page.press("number_sign")
        await page.wait_for(lambda _state: attempts == 1)
        assert modal._active_tab is None
        assert page.app._last_admin_center_tab == "tasks"

        await page.press("number_sign")
        await page.wait_for(lambda _state: modal._active_tab == "tasks")
        assert attempts == 2


async def test_custom_opener_opens_home_resumes_and_is_displayed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: {"ace": {"keymaps": {"app": {"open_config_center": "f2"}}}},
    )
    monkeypatch.setattr(AceApp, "_schedule_axe_async_refresh", lambda self: None)
    _patch_stub_panes(monkeypatch)

    async with AcePage() as page:
        page.app._last_admin_center_tab = "tasks"
        await page.press("f2")
        await page.expect_modal("ConfigCenterModal")
        modal = page.app.screen
        assert isinstance(modal, ConfigCenterModal)
        hint = modal.query_one("#admin-center-home-hint", Static).render().plain
        assert "f2" in hint
        assert "resume Tasks" in hint
        assert "#" not in hint

        await page.press("f2")
        await page.wait_for(lambda _state: modal._active_tab == "tasks")


async def test_literal_opener_remains_typeable_and_cannot_nest_modal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ConfigCenterModal,
        "_create_pane",
        lambda _self, tab: _InputPane(tab),
    )
    async with AcePage() as page:
        modal = ConfigCenterModal(initial_tab="tasks", resume_tab="logs")
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")
        await page.wait_for(lambda _state: modal._active_tab == "tasks")
        field = modal.query_one("#stub-filter", Input)
        await page.wait_for(lambda _state: field.has_focus)

        await page.press("number_sign")
        await page.pause()

        assert field.value == "#"
        assert page.app.screen is modal
        assert len(page.app.screen_stack) == 2
