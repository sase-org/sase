"""Behavioral coverage for the home-first, lazy SASE Admin Center."""

from __future__ import annotations

import subprocess
import sys

import pytest
from rich.text import Text
from textual.app import App
from textual.binding import Binding
from textual.widgets import ContentSwitcher, Static

from sase.ace.testing import AcePage, wait_for
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
from tests.ace.tui._config_center_tabs_helpers import (
    _HostApp,
    _StubPane,
    _patch_stub_panes,
)


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
        "Follow procs, inspect live output, and manage running jobs.",
        "Manage projects and inspect their repositories and workspaces.",
        "Explore runners, projects, activity, and trends over time.",
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
        PanelTab("patches", "PRs", "green"),
        PanelTab("commits", "Commits", "yellow"),
    )

    class _TabStripApp(App[None]):
        def compose(self):  # type: ignore[no-untyped-def]
            yield PanelTabStrip(tabs, "patches", uppercase_active=True)

    async with _TabStripApp().run_test() as pilot:
        strip = pilot.app.query_one(PanelTabStrip)
        assert strip._build_content().plain == " PRS  │  Commits "
        strip.set_active_tab("commits")
        assert strip._build_content().plain == " PRs  │  COMMITS "


async def test_micro_tab_tier_is_opt_in_and_uses_numbered_micro_labels() -> None:
    tabs = (
        PanelTab("overview", "Overview", "cyan", micro_label="Ovr"),
        PanelTab(
            "plans_questions",
            "Plans & Questions",
            "magenta",
            compact_label="Plans/Q",
            micro_label="P&Q",
        ),
    )

    class _TabStripApp(App[None]):
        def compose(self):  # type: ignore[no-untyped-def]
            yield PanelTabStrip(
                tabs,
                "overview",
                show_numbers=True,
                uppercase_active=True,
                compact_below=40,
                compact_separator="│",
                id="compact-only",
            )
            yield PanelTabStrip(
                tabs,
                "overview",
                show_numbers=True,
                uppercase_active=True,
                compact_below=40,
                compact_separator="│",
                micro_below=30,
                micro_separator="│",
                id="micro",
            )

    async with _TabStripApp().run_test(size=(20, 5)) as pilot:
        await pilot.pause()
        compact_only = pilot.app.query_one("#compact-only", PanelTabStrip)
        assert compact_only._tier == "compact"
        assert compact_only._build_content().plain == "1 OVERVIEW│2 Plans/Q"

        micro = pilot.app.query_one("#micro", PanelTabStrip)
        assert micro._tier == "micro"
        assert micro._build_content().plain == "1 OVR│2 P&Q"


def test_title_has_no_leading_icon_and_underline_matches() -> None:
    assert _TITLE_TEXT == "SASE Admin Center"
    assert _TITLE_TEXT == _TITLE_LABEL
    assert not _TITLE_TEXT.startswith("⎈")
    assert len(_TITLE_UNDERLINE) == len(_TITLE_TEXT)


def test_resume_tab_validation_accepts_only_catalog_ids() -> None:
    assert validated_center_tab("procs") == "procs"
    assert validated_center_tab("missing") is None
    assert validated_center_tab(5) is None


def test_home_hint_explains_no_history_and_uses_catalog_resume_style() -> None:
    no_history = _home_hint_text(None, "number_sign", compact=False)
    assert no_history.plain.startswith(" #  resumes after your first section visit")
    assert "1-7/click · Tab cycle" in no_history.plain

    resume_ready = _home_hint_text("procs", "f2", compact=False)
    assert resume_ready.plain.startswith(" f2  resume Procs")
    target_offset = resume_ready.plain.index("resume Procs")
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
        "procs_pane",
        "plugins_browser_pane",
        "xprompt_browser_pane",
        "config_hub_pane",
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
        await wait_for(pilot, lambda: modal._active_tab == "projects")
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
        await wait_for(pilot, lambda: modal._active_tab == "projects")

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

        await pilot.press("5")
        await wait_for(pilot, lambda: modal._active_tab == "statistics")

        assert calls == ["statistics"]
        assert created["statistics"][0].focus_count >= 1


async def test_landing_compact_class_tracks_viewport_size() -> None:
    async with AcePage(query="!!!", patches=[], size=(120, 40)) as page:
        modal = ConfigCenterModal()
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")
        await page.wait_for(lambda _state: bool(modal.query(_AdminCenterLanding)))

        landing = modal.query_one(_AdminCenterLanding)
        key = modal.query_one(".admin-center-home-row-key", Static)
        assert not landing.has_class("-compact")
        assert key.render().plain == " 1 "

        await page._pilot.resize_terminal(100, 24)  # noqa: SLF001
        await page.wait_for(lambda _state: landing.has_class("-compact"))
        assert key.render().plain == "1"

        await page._pilot.resize_terminal(120, 40)  # noqa: SLF001
        await page.wait_for(lambda _state: not landing.has_class("-compact"))
        assert key.render().plain == " 1 "
