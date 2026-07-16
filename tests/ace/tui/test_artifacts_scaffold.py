"""Behavioral coverage for the Artifacts rename and sub-tab scaffold."""

from __future__ import annotations

import pytest
from textual.widgets import ContentSwitcher
from textual.widgets import Static

from sase.ace.testing import AcePage
from sase.ace.tui.actions.artifacts import _ArtifactsProjectChoices
from sase.ace.tui.commands import (
    build_command_catalog,
    execute_command,
    extract_command_context,
    is_command_available,
)
from sase.ace.tui.modals.inventory_project_picker import (
    InventoryProjectChoice,
    InventoryProjectPicker,
)
from sase.ace.tui.widgets import (
    ArtifactPlaceholderPane,
    ArtifactsPrsPane,
    CommitsPane,
)
from sase.ace.tui.widgets.artifacts import ARTIFACTS_PANE_IDS, ArtifactsView
from sase.ace.tui.widgets.artifacts import ARTIFACTS_ACCENTS
import sase.ace.tui.widgets.artifacts.commits as commits_module
from sase.ace.tui.widgets.panel_tab_strip import PanelTabStrip
from sase.vcs_log.models import VcsLogResult


@pytest.fixture(autouse=True)
def _stub_commits_collector(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        commits_module,
        "run_vcs_log",
        lambda **_kwargs: VcsLogResult((), (), ()),
    )


async def test_subtab_keys_wrap_and_gate_hidden_pr_actions() -> None:
    async with AcePage(initial_tab="changespecs") as page:
        view = page.query_one_widget("#changespecs-view", ArtifactsView)
        prs = page.query_one_widget("#artifacts-prs-pane", ArtifactsPrsPane)
        commits = page.query_one_widget("#artifacts-commits-pane", CommitsPane)

        assert view.current_subtab == "prs"
        assert prs.first_activation_count == 1
        assert prs.artifacts_active is True

        await page.press("]")
        await page.expect_state("artifacts_subtab", "commits")

        switcher = page.query_one_widget("#artifacts-content-switcher", ContentSwitcher)
        assert switcher.current == ARTIFACTS_PANE_IDS["commits"]
        assert prs.artifacts_active is False
        assert commits.first_activation_count == 1
        assert commits.artifacts_active is True
        assert page.app.check_action("change_status", ()) is False
        assert page.app.check_action("next_changespec", ()) is False
        assert page.app.check_action("commits_refresh", ()) is True
        assert page.app.check_action("refresh_bugs", ()) is False
        assert page.app.check_action("plans_refresh", ()) is False
        footer = page.query_one_widget("#keybinding-content", Static)
        assert footer.content.plain == ""

        old_idx = page.app.current_idx
        await page.press("j")
        assert page.app.current_idx == old_idx

        await page.press("[")
        await page.expect_state("artifacts_subtab", "prs")
        assert page.app.check_action("commits_refresh", ()) is False
        assert prs.activation_count == 2
        assert commits.deactivation_count == 1

        await page.press("[")
        await page.expect_state("artifacts_subtab", "plans")


async def test_number_keys_jump_artifacts_without_entering_from_other_tabs() -> None:
    async with AcePage(initial_tab="changespecs") as page:
        switcher = page.query_one_widget("#artifacts-content-switcher", ContentSwitcher)
        expected = ("prs", "commits", "bugs", "plans")

        for start_key in ("1", "2", "3", "4"):
            await page.press(start_key)
            await page.expect_state("artifacts_subtab", expected[int(start_key) - 1])
            for key, subtab in zip(("1", "2", "3", "4"), expected, strict=True):
                await page.press(key)
                await page.expect_state("artifacts_subtab", subtab)
                assert switcher.current == ARTIFACTS_PANE_IDS[subtab]

        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        remembered_subtab = page.app.current_artifacts_subtab
        for key in ("1", "2", "3", "4", "asterisk"):
            await page.press(key)
            await page.pause()
            assert page.app.current_tab == "agents"
            assert page.app.current_artifacts_subtab == remembered_subtab
            assert page.state["modal"] is None

        await page.press("tab", "tab")
        await page.expect_state("tab", "axe")
        for key in ("1", "2", "3", "4", "asterisk"):
            await page.press(key)
            await page.pause()
            assert page.app.current_tab == "axe"
            assert page.app.current_artifacts_subtab == remembered_subtab
            assert page.state["modal"] is None


async def test_click_message_and_reactivation_keep_lazy_pane_state() -> None:
    async with AcePage(initial_tab="changespecs") as page:
        strip = page.query_one_widget("#artifacts-subtabs", PanelTabStrip)
        commits = page.query_one_widget("#artifacts-commits-pane", CommitsPane)
        assert (
            strip._build_content().plain
            == " 1 PRS  │  2 Commits  │  3 Bugs  │  4 Plans "
        )

        strip.post_message(PanelTabStrip.TabClicked("commits"))
        await page.expect_state("artifacts_subtab", "commits")
        assert (
            strip._build_content().plain
            == " 1 PRs  │  2 COMMITS  │  3 Bugs  │  4 Plans "
        )
        commits.set_class(True, "test-selection-state")

        strip.post_message(PanelTabStrip.TabClicked("bugs"))
        await page.expect_state("artifacts_subtab", "bugs")
        assert (
            strip._build_content().plain
            == " 1 PRs  │  2 Commits  │  3 BUGS  │  4 Plans "
        )
        strip.post_message(PanelTabStrip.TabClicked("commits"))
        await page.expect_state("artifacts_subtab", "commits")
        assert (
            strip._build_content().plain
            == " 1 PRs  │  2 COMMITS  │  3 Bugs  │  4 Plans "
        )

        assert commits.first_activation_count == 1
        assert commits.activation_count == 2
        assert commits.has_class("test-selection-state")


async def test_non_pr_panes_do_not_collect_during_pr_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        commits_module,
        "run_vcs_log",
        lambda **_kwargs: calls.append("commits") or VcsLogResult((), (), ()),
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.bugs.collect_bug_snapshot",
        lambda *_args, **_kwargs: calls.append("bugs"),
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.plans_pane.load_plans_snapshot",
        lambda *_args, **_kwargs: calls.append("plans"),
    )

    async with AcePage(initial_tab="changespecs") as page:
        await page.pause()
        assert page.app.current_artifacts_subtab == "prs"
        assert calls == []


async def test_scope_inventory_is_lazy_and_picker_updates_all_placeholders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _ArtifactsProjectChoices(
        choices=(
            InventoryProjectChoice(
                project_key="alpha",
                display_name="Alpha",
                state="enabled",
            ),
        ),
        enabled_projects=("alpha",),
        display_names={"alpha": "Alpha"},
    )
    calls = 0

    def collect() -> _ArtifactsProjectChoices:
        nonlocal calls
        calls += 1
        return result

    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        collect,
    )

    async with AcePage(initial_tab="changespecs") as page:
        await page.pause()
        assert calls == 0

        await page.press("]")
        await page.wait_for(
            lambda _state: page.app._artifacts_project_choices is result
        )
        assert calls == 1
        assert page.app.artifacts_project_scope == "alpha"

        for pane in page.app.query(ArtifactPlaceholderPane):
            assert pane.project_scope == "alpha"
        assert page.app.query_one(CommitsPane).project_scope == "alpha"

        await page.press("p")
        await page.expect_modal("InventoryProjectPicker")
        picker = page.app.screen
        assert isinstance(picker, InventoryProjectPicker)
        picker.query_one("#inventory-project-picker-list").highlighted = 0
        picker.action_select_highlighted()
        await page.expect_no_modal()
        await page.wait_for(lambda _state: page.app.artifacts_project_scope is None)
        assert page.app.artifacts_project_scope is None


async def test_palette_has_direct_jump_for_every_artifacts_subtab() -> None:
    async with AcePage(initial_tab="agents") as page:
        catalog = build_command_catalog(page.app._keymap_registry)
        by_id = {spec.id: spec for spec in catalog}
        expected = {
            "artifacts.prs",
            "artifacts.commits",
            "artifacts.bugs",
            "artifacts.plans",
        }
        assert expected <= by_id.keys()
        assert [
            by_id[f"artifacts.{subtab}"].key_display
            for subtab in (
                "prs",
                "commits",
                "bugs",
                "plans",
            )
        ] == ["1", "2", "3", "4"]

        execute_command(page.app, by_id["artifacts.bugs"])
        await page.expect_state("tab", "changespecs")
        await page.expect_state("artifacts_subtab", "bugs")

        context = extract_command_context(page.app)
        assert context.artifacts_subtab == "bugs"
        assert is_command_available(by_id["artifacts.prs"], context)
        assert not is_command_available(by_id["app.change_status"], context)
        assert not is_command_available(by_id["app.commits_refresh"], context)

        execute_command(page.app, by_id["artifacts.commits"])
        await page.expect_state("artifacts_subtab", "commits")
        context = extract_command_context(page.app)
        assert is_command_available(by_id["app.commits_refresh"], context)
        assert not is_command_available(by_id["app.refresh_bugs"], context)


def test_subtab_strip_labels_and_accents_cover_all_panes() -> None:
    view = ArtifactsView(id="changespecs-view")
    # The mounted interaction tests cover rendering; this unit assertion keeps
    # the public pane-id map exhaustive for later feature phases.
    assert tuple(ARTIFACTS_PANE_IDS) == ("prs", "commits", "bugs", "plans")
    assert ARTIFACTS_ACCENTS == {
        "prs": "#00D7AF",
        "commits": "#FFD700",
        "bugs": "#FF5F5F",
        "plans": "#AF87FF",
    }
    assert view.current_subtab == "prs"
