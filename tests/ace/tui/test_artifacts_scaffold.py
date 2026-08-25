"""Behavioral coverage for the Artifacts rename and sub-tab scaffold."""

from __future__ import annotations

from dataclasses import replace

import pytest
from textual.widgets import ContentSwitcher
from textual.widgets import Static

from sase.ace.testing import AcePage
from sase.ace.tui.actions.artifacts import (
    BEADS_ARTIFACT_ACTIONS,
    FILES_ARTIFACT_ACTIONS,
    _ArtifactsProjectChoices,
)
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
    ArtifactsBeadsPane,
    ArtifactsDocumentsPane,
    ArtifactsFilesPane,
    ArtifactsPatchesPane,
    CommitsPane,
)
from sase.ace.tui.widgets.artifacts import (
    ARTIFACTS_PANE_IDS,
    ARTIFACTS_SUBTAB_ORDER,
    DEFAULT_ARTIFACTS_SUBTAB,
    FILES_PANE_IDS,
    FILES_SUBTAB_ORDER,
    ArtifactsView,
)
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


def _strip_plain(view: ArtifactsView, active_tab: str) -> str:
    parts: list[str] = []
    for index, descriptor in enumerate(view.descriptors, start=1):
        shortcut = descriptor.digit_shortcut or str(index)
        label = (
            descriptor.label.upper()
            if descriptor.id == active_tab
            else descriptor.label
        )
        icon = f" {descriptor.icon}" if descriptor.icon else ""
        parts.append(f" {shortcut}{icon} {label} ")
    return " │ ".join(parts)


def _digit_for(view: ArtifactsView, subtab: str) -> str:
    descriptor = next(d for d in view.descriptors if d.id == subtab)
    assert descriptor.digit_shortcut is not None
    return descriptor.digit_shortcut


async def test_subtab_keys_wrap_and_gate_hidden_pr_actions() -> None:
    async with AcePage(initial_tab="patches") as page:
        view = page.query_one_widget("#artifacts-view", ArtifactsView)
        patches_pane = page.query_one_widget(
            "#artifacts-patches-pane", ArtifactsPatchesPane
        )
        commits = page.query_one_widget("#artifacts-stitches-pane", CommitsPane)

        assert view.current_subtab == "stitches"
        assert patches_pane.first_activation_count == 0
        assert patches_pane.artifacts_active is False
        assert commits.first_activation_count == 1
        assert commits.artifacts_active is True

        switcher = page.query_one_widget("#artifacts-content-switcher", ContentSwitcher)
        assert switcher.current == ARTIFACTS_PANE_IDS["stitches"]
        assert page.app.check_action("change_status", ()) is False
        assert page.app.check_action("next_patch", ()) is False
        assert page.app.check_action("refresh", ()) is True
        assert page.app.check_action("start_leader_mode", ()) is not False
        footer = page.query_one_widget("#keybinding-content", Static)
        assert footer.content.plain == ""

        old_idx = page.app.current_idx
        await page.press("j")
        assert page.app.current_idx == old_idx

        await page.press("]")
        await page.expect_state("artifacts_subtab", "patches")
        assert commits.deactivation_count == 1
        assert patches_pane.activation_count == 1
        assert page.app.focused is not None
        assert page.app.focused.id == "list-panel"

        await page.press("]")
        await page.expect_state("artifacts_subtab", "beads")
        assert patches_pane.deactivation_count == 1
        assert all(
            page.app.check_action(action, ()) is True
            for action in BEADS_ARTIFACT_ACTIONS
        )

        await page.press("[")
        await page.expect_state("artifacts_subtab", "patches")
        assert patches_pane.activation_count == 2

        await page.press("[")
        await page.expect_state("artifacts_subtab", "stitches")
        assert commits.activation_count == 2

        await page.press("[")
        await page.expect_state("artifacts_subtab", "files")
        assert page.app.check_action("refresh", ()) is True
        await page.press("(")
        await page.expect_state("artifacts_subtab", "files")
        files = page.query_one_widget("#artifacts-files-pane", ArtifactsFilesPane)
        assert files.first_activation_count == 1
        # sase-m6.9 unified refresh onto a single app-wide action reachable from
        # every Artifacts pane (not just Patches), so it stays available here.
        assert page.app.check_action("refresh", ()) is True
        assert all(
            page.app.check_action(action, ()) is True
            for action in FILES_ARTIFACT_ACTIONS
        )
        assert "No artifact files" in str(
            page.query_one_widget("#files-empty", Static).content
        )
        await page.press("R")
        assert files.refresh_request_count == 1

        provider = next(
            (descriptor for descriptor in view.descriptors if descriptor.is_provider),
            None,
        )
        if provider is not None and provider.digit_shortcut is not None:
            await page.press(provider.digit_shortcut)
            await page.expect_state("artifacts_subtab", provider.id)
            assert page.app.check_action("refresh", ()) is True

        await page.press("3")
        await page.expect_state("artifacts_subtab", "beads")
        await page.press(_digit_for(view, "files"))
        await page.expect_state("artifacts_subtab", "files")
        await page.press("R")
        assert files.refresh_request_count == 2


async def test_ctrl_space_dispatches_repeat_agent_from_every_subtab() -> None:
    async with AcePage(initial_tab="patches") as page:
        view = page.query_one_widget("#artifacts-view", ArtifactsView)
        calls: list[str] = []

        def record_repeat_agent() -> None:
            calls.append(page.app.current_artifacts_subtab)

        page.app.action_start_agent_from_patch = record_repeat_agent  # type: ignore[method-assign]

        expected = ("stitches", "patches", "beads", "files")
        for index, subtab in enumerate(expected, start=1):
            await page.press(_digit_for(view, subtab))
            await page.expect_state("artifacts_subtab", subtab)
            assert page.app.check_action("start_agent_from_patch", ()) is True

            await page.press("ctrl+@")
            assert calls == list(expected[:index])


async def test_number_keys_jump_artifacts_without_entering_from_other_tabs() -> None:
    async with AcePage(initial_tab="patches") as page:
        view = page.query_one_widget("#artifacts-view", ArtifactsView)
        switcher = page.query_one_widget("#artifacts-content-switcher", ContentSwitcher)
        expected = ("stitches", "patches", "beads", "files")

        for start_subtab in expected:
            await page.press(_digit_for(view, start_subtab))
            await page.expect_state("artifacts_subtab", start_subtab)
            for subtab in expected:
                await page.press(_digit_for(view, subtab))
                await page.expect_state("artifacts_subtab", subtab)
                assert switcher.current == ARTIFACTS_PANE_IDS[subtab]

        await page.press(_digit_for(view, "stitches"))
        await page.expect_state("artifacts_subtab", "stitches")
        provider = next(
            (descriptor for descriptor in view.descriptors if descriptor.is_provider),
            None,
        )
        if provider is None or provider.digit_shortcut is None:
            await page.press("5")
            await page.pause()
            assert page.app.current_artifacts_subtab == "stitches"
        else:
            await page.press(provider.digit_shortcut)
            await page.pause()
            assert page.app.current_artifacts_subtab == provider.id
            assert switcher.current == provider.pane_id
            await page.press(_digit_for(view, "stitches"))
            await page.expect_state("artifacts_subtab", "stitches")

        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        remembered_subtab = page.app.current_artifacts_subtab
        for key in ("1", "2", "3", "4", "5", "6", "asterisk"):
            await page.press(key)
            await page.pause()
            assert page.app.current_tab == "agents"
            assert page.app.current_artifacts_subtab == remembered_subtab
            assert page.state["modal"] is None

        await page.press("tab", "tab")
        await page.expect_state("tab", "axe")
        for key in ("1", "2", "3", "4", "5", "6", "asterisk"):
            await page.press(key)
            await page.pause()
            assert page.app.current_tab == "axe"
            assert page.app.current_artifacts_subtab == remembered_subtab
            assert page.state["modal"] is None


async def test_click_message_and_reactivation_keep_lazy_pane_state() -> None:
    async with AcePage(initial_tab="patches") as page:
        view = page.query_one_widget("#artifacts-view", ArtifactsView)
        strip = page.query_one_widget("#artifacts-subtabs", PanelTabStrip)
        commits = page.query_one_widget("#artifacts-stitches-pane", CommitsPane)
        assert strip._build_content().plain == _strip_plain(view, "stitches")

        commits.set_class(True, "test-selection-state")

        strip.post_message(PanelTabStrip.TabClicked("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        assert strip._build_content().plain == _strip_plain(view, "patches")
        strip.post_message(PanelTabStrip.TabClicked("stitches"))
        await page.expect_state("artifacts_subtab", "stitches")
        assert strip._build_content().plain == _strip_plain(view, "stitches")

        assert commits.first_activation_count == 1
        assert commits.activation_count == 2
        assert commits.has_class("test-selection-state")


async def test_first_artifacts_entry_activates_default_without_hidden_collection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        commits_module,
        "run_vcs_log",
        lambda **_kwargs: calls.append("stitches") or VcsLogResult((), (), ()),
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.plans_pane.load_plans_snapshot",
        lambda *_args, **_kwargs: calls.append("plans"),
    )

    async with AcePage(initial_tab="agents") as page:
        await page.pause()
        view = page.query_one_widget("#artifacts-view", ArtifactsView)
        commits = page.query_one_widget("#artifacts-stitches-pane", CommitsPane)
        switcher = page.query_one_widget("#artifacts-content-switcher", ContentSwitcher)
        strip = page.query_one_widget("#artifacts-subtabs", PanelTabStrip)

        assert page.app.current_artifacts_subtab == "stitches"
        assert view.current_subtab == "stitches"
        assert switcher.current == ARTIFACTS_PANE_IDS["stitches"]
        assert "1 ◉ STITCH" in strip._build_content().plain
        assert commits.first_activation_count == 0
        assert commits.artifacts_active is False
        assert calls == []

        await page.press("tab")
        await page.expect_state("tab", "patches")
        await page.wait_for(lambda _state: calls == ["stitches"])

        assert page.app.current_artifacts_subtab == "stitches"
        assert view.current_subtab == "stitches"
        assert switcher.current == ARTIFACTS_PANE_IDS["stitches"]
        assert commits.first_activation_count == 1
        assert commits.artifacts_active is True
        assert page.app.check_action("refresh", ()) is True
        assert page.app.check_action("change_status", ()) is False
        assert page.query_one_widget("#keybinding-content", Static).content.plain == ""


async def test_direct_artifacts_start_initializes_default_non_pr_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _ArtifactsProjectChoices((), (), {})
    inventory_calls = 0

    def collect() -> _ArtifactsProjectChoices:
        nonlocal inventory_calls
        inventory_calls += 1
        return result

    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        collect,
    )

    async with AcePage(initial_tab="patches") as page:
        commits = page.query_one_widget("#artifacts-stitches-pane", CommitsPane)
        await page.wait_for(
            lambda _state: page.app._artifacts_project_choices is result
        )

        assert page.app.current_artifacts_subtab == "stitches"
        assert commits.first_activation_count == 1
        assert commits.artifacts_active is True
        assert inventory_calls == 1
        assert page.query_one_widget("#keybinding-content", Static).content.plain == ""


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
            InventoryProjectChoice(
                project_key="beta",
                display_name="Beta",
                state="disabled",
            ),
        ),
        enabled_projects=("alpha",),
        display_names={"alpha": "Alpha", "beta": "Beta"},
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

    async with AcePage(initial_tab="agents") as page:
        await page.pause()
        assert calls == 0

        await page.press("tab")
        await page.wait_for(
            lambda _state: page.app._artifacts_project_choices is result
        )
        assert calls == 1
        assert page.app.artifacts_project_scope == "alpha"

        for pane in page.app.query(ArtifactPlaceholderPane):
            assert pane.project_scope == "alpha"
        commits = page.app.query_one(CommitsPane)
        assert commits.project_scope == "Alpha"
        assert commits.filters.project == "Alpha"
        assert page.app.query_one(ArtifactsBeadsPane).project_scope == "alpha"
        assert page.app.query_one(ArtifactsFilesPane).project_scope == "alpha"
        for pane in page.app.query(ArtifactsDocumentsPane):
            assert pane.project_scope == "alpha"

        retained_filters = replace(
            commits.filters,
            repos=("plans",),
            authors=("Ada",),
            limit=5,
            text=("fix",),
        )
        commits._commit_filter_values(retained_filters, close_session=False)
        commits.set_project_scope("beta", display_name="Beta")
        await page.wait_for(lambda _state: commits.filters.project == "Beta")
        assert commits.filters == replace(retained_filters, project="Beta")
        assert page.app.artifacts_project_scope == "alpha"

        await page.press("p")
        await page.expect_modal("InventoryProjectPicker")
        picker = page.app.screen
        assert isinstance(picker, InventoryProjectPicker)
        assert picker.query_one("#inventory-project-picker-list").highlighted == 2
        picker.query_one("#inventory-project-picker-list").highlighted = 0
        picker.action_select_highlighted()
        await page.expect_no_modal()
        await page.wait_for(lambda _state: page.app.artifacts_project_scope is None)
        assert page.app.artifacts_project_scope is None
        assert commits.filters == replace(retained_filters, project=None)


async def test_startup_scope_normalizes_display_name_to_project_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A #gh project named by its query-token display name resolves to its key."""
    result = _ArtifactsProjectChoices(
        choices=(
            InventoryProjectChoice(
                project_key="gh_acme__widget",
                display_name="widget",
                state="enabled",
            ),
        ),
        enabled_projects=("gh_acme__widget",),
        display_names={"gh_acme__widget": "widget"},
    )
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        lambda: result,
    )

    async with AcePage(query="project:widget", initial_tab="agents") as page:
        assert page.app.artifacts_project_scope == "widget"

        await page.press("tab")
        await page.wait_for(
            lambda _state: page.app._artifacts_project_choices is result
        )
        assert page.app.artifacts_project_scope == "gh_acme__widget"


async def test_startup_scope_keeps_unresolvable_ref_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unknown project ref stays put instead of silently widening to None."""
    result = _ArtifactsProjectChoices((), (), {})
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        lambda: result,
    )

    async with AcePage(query="project:mystery", initial_tab="agents") as page:
        assert page.app.artifacts_project_scope == "mystery"

        await page.press("tab")
        await page.wait_for(
            lambda _state: page.app._artifacts_project_choices is result
        )
        assert page.app.artifacts_project_scope == "mystery"


async def test_palette_has_direct_jump_for_every_artifacts_subtab() -> None:
    async with AcePage(initial_tab="agents") as page:
        view = page.query_one_widget("#artifacts-view", ArtifactsView)
        catalog = build_command_catalog(page.app._keymap_registry)
        by_id = {spec.id: spec for spec in catalog}
        descriptors = view.descriptors
        expected = {f"artifacts.{descriptor.id}" for descriptor in descriptors}
        assert expected <= by_id.keys()
        assert {f"app.{action}" for action in FILES_ARTIFACT_ACTIONS} <= by_id.keys()
        assert [
            by_id[f"artifacts.{descriptor.id}"].key_display
            for descriptor in descriptors
            if descriptor.digit_shortcut is not None
        ] == [
            descriptor.digit_shortcut
            for descriptor in descriptors
            if descriptor.digit_shortcut is not None
        ]

        execute_command(page.app, by_id["artifacts.beads"])
        await page.expect_state("tab", "patches")
        await page.expect_state("artifacts_subtab", "beads")

        context = extract_command_context(page.app)
        assert context.artifacts_subtab == "beads"
        assert is_command_available(by_id["artifacts.patches"], context)
        assert not is_command_available(by_id["app.change_status"], context)
        assert is_command_available(by_id["app.refresh"], context)

        execute_command(page.app, by_id["artifacts.stitches"])
        await page.expect_state("artifacts_subtab", "stitches")
        context = extract_command_context(page.app)
        assert is_command_available(by_id["app.refresh"], context)

        execute_command(page.app, by_id["artifacts.files"])
        await page.expect_state("artifacts_subtab", "files")
        context = extract_command_context(page.app)
        assert context.artifacts_subtab == "files"
        assert is_command_available(by_id["app.refresh"], context)

        provider = next(
            (descriptor for descriptor in descriptors if descriptor.is_provider),
            None,
        )
        if provider is not None:
            execute_command(page.app, by_id[f"artifacts.{provider.id}"])
            await page.expect_state("artifacts_subtab", provider.id)
            context = extract_command_context(page.app)
            assert context.artifacts_subtab == provider.id
            assert is_command_available(by_id["app.refresh"], context)


def test_subtab_strip_labels_and_accents_cover_all_panes() -> None:
    view = ArtifactsView(id="patches-view")
    # The mounted interaction tests cover rendering; this unit assertion keeps
    # the public pane-id map exhaustive for later feature phases.
    assert DEFAULT_ARTIFACTS_SUBTAB == "stitches"
    assert ARTIFACTS_SUBTAB_ORDER[0] == DEFAULT_ARTIFACTS_SUBTAB
    assert ARTIFACTS_SUBTAB_ORDER == (
        "stitches",
        "patches",
        "beads",
        "files",
    )
    assert tuple(ARTIFACTS_PANE_IDS) == (
        "patches",
        "stitches",
        "beads",
        "agents",
        "files",
    )
    assert ARTIFACTS_PANE_IDS["patches"] == "artifacts-patches-pane"
    assert ARTIFACTS_PANE_IDS["agents"] == "artifacts-agents-pane"
    assert "bugs" not in ARTIFACTS_PANE_IDS
    assert {
        "patches": "#00D7AF",
        "stitches": "#FFD700",
        "beads": "#D787FF",
        "agents": "#0062FF",
        "files": "#FFAF5F",
        "ref:plan": "#AF87FF",
        "plans": "#AF87FF",
        "other": "#FFAF5F",
    }.items() <= ARTIFACTS_ACCENTS.items()
    assert FILES_SUBTAB_ORDER == ()
    assert FILES_PANE_IDS == {}
    descriptor_ids = tuple(descriptor.id for descriptor in view.descriptors)
    assert descriptor_ids[:3] == ("stitches", "patches", "beads")
    assert descriptor_ids[-2:] == ("agents", "files")
    assert all(identifier.startswith("ref:") for identifier in descriptor_ids[3:-2])
    assert [descriptor.digit_shortcut for descriptor in view.descriptors[:3]] == [
        "1",
        "2",
        "3",
    ]
    assert view.descriptors[-1].id == "files"
    assigned_digits = [
        int(descriptor.digit_shortcut)
        for descriptor in view.descriptors
        if descriptor.digit_shortcut is not None
    ]
    files_digit = view.descriptors[-1].digit_shortcut
    assert files_digit is not None
    assert int(files_digit) == max(assigned_digits)
    assert view.current_subtab == "stitches"


async def test_action_show_artifacts_bugs_lands_on_beads() -> None:
    async with AcePage(initial_tab="patches") as page:
        page.app.action_show_artifacts_bugs()
        await page.expect_state("artifacts_subtab", "beads")


async def test_action_show_artifacts_prs_and_switch_helper_land_on_patches() -> None:
    from sase.ace.tui.artifact_tabs import switch_to_artifacts_subtab

    async with AcePage(initial_tab="patches") as page:
        page.app.current_artifacts_subtab = "beads"
        await page.expect_state("artifacts_subtab", "beads")

        page.app.action_show_artifacts_prs()
        await page.expect_state("artifacts_subtab", "patches")

        page.app.current_artifacts_subtab = "beads"
        await page.expect_state("artifacts_subtab", "beads")

        switch_to_artifacts_subtab(page.app, "prs")  # type: ignore[arg-type]  # legacy alias
        await page.expect_state("artifacts_subtab", "patches")
