"""Bootstrap and first-paint publication for Artifacts."""

from __future__ import annotations

import threading
from unittest.mock import patch

from sase.ace.testing import AcePage
from tests._load_tolerant import LOAD_TOLERANT_TIMEOUT
from tests.ace.tui._artifacts_post_paint_publication_helpers import (
    catalog_for,
    gated_blocking_factory,
    plan_records,
    publication_path,
    wait_for_status,
)

__all__ = [
    "test_construction_uses_bootstrap_without_synchronous_discovery",
    "test_first_paint_fixed_panes_then_one_coherent_publication",
    "test_hidden_agents_startup_publishes_without_losing_selection",
    "test_pending_digit_without_target_does_nothing",
    "test_pending_provider_jump_applies_only_without_supersede",
    "test_render_and_catalog_builders_take_snapshot_without_discovery",
    "test_user_navigation_supersedes_pending_provider_jump",
    "test_zero_providers_completes_authoritatively",
]


def test_construction_uses_bootstrap_without_synchronous_discovery() -> None:
    """The constructor must not walk projects or read the provider token."""

    from sase.ace.tui import AceApp
    from sase.ace.testing.ace_page import _stop_ace_app_proc_observer

    with (
        patch(
            "sase.ace.tui._artifact_tab_snapshot.discover_artifacts_snapshot",
            side_effect=AssertionError("constructor must not discover"),
        ),
        patch(
            "sase.ace.tui.artifact_tabs.resolve_artifacts_subtabs",
            side_effect=AssertionError("constructor must not resolve"),
        ),
        patch(
            "sase.ace.tui._artifact_tab_discovery.provider_source_token",
            side_effect=AssertionError("constructor must not read the token"),
        ),
    ):
        app = AceApp(query='"bootstrap"', refresh_interval=0, initial_tab="artifacts")
    try:
        snapshot = app.artifacts_descriptor_snapshot
        assert snapshot.is_pending
        assert snapshot.generation == 0
        assert snapshot.source_token is None
        # Fixed panes only: provider tabs are absent until publication.
        assert not snapshot.provider_ids
        assert {"stitches", "patches", "beads"} <= set(snapshot.ordered_ids)
    finally:
        _stop_ace_app_proc_observer(app)


def test_render_and_catalog_builders_take_snapshot_without_discovery() -> None:
    """Mounted-UI builders must not fall back to synchronous discovery."""

    from sase.ace.tui._artifact_tab_snapshot import bootstrap_artifacts_snapshot
    from sase.ace.tui.commands.catalog import build_command_catalog
    from sase.ace.tui.keymaps import load_keymap_registry
    from sase.ace.tui.keymaps.bindings import build_app_bindings
    from sase.ace.tui.modals.help_modal.patches_artifact_bindings import (
        artifact_sections,
    )
    from sase.ace.tui.widgets.patch_onboarding import PatchOnboarding
    from sase.ace.tui.widgets.tab_quickstart import TabQuickStart

    snapshot = bootstrap_artifacts_snapshot(generation=0)
    registry = load_keymap_registry({})
    with (
        patch(
            "sase.ace.tui.artifact_tabs.resolve_artifacts_subtabs",
            side_effect=AssertionError("render path must not resolve"),
        ),
        patch(
            "sase.ace.tui._artifact_tab_discovery.provider_source_token",
            side_effect=AssertionError("render path must not read the token"),
        ),
    ):
        bindings = build_app_bindings(registry.app, snapshot=snapshot)
        catalog = build_command_catalog(registry, snapshot=snapshot)
        artifact_sections(registry, snapshot)
        TabQuickStart.render_content(registry, tab="artifacts", snapshot=snapshot)
        PatchOnboarding.render_content(registry, snapshot=snapshot)
    assert bindings
    assert [spec for spec in catalog if spec.id.startswith("artifacts.")]
    assert snapshot.is_pending


async def test_first_paint_fixed_panes_then_one_coherent_publication() -> None:
    """Fixed panes work while discovery is gated; publication is coherent."""

    entered = threading.Event()
    release = threading.Event()
    with patch(
        publication_path(),
        gated_blocking_factory(entered, release, records=plan_records()),
    ):
        async with AcePage(initial_tab="artifacts", startup_policy="real") as page:
            await page.wait_for(
                lambda _state: entered.is_set(),
                timeout=LOAD_TOLERANT_TIMEOUT,
                timeout_message=lambda: "entered" + " never set",
            )
            app = page.app
            bootstrap = app.artifacts_descriptor_snapshot
            assert bootstrap.is_pending
            assert bootstrap.generation == 0
            before_ids = tuple(bootstrap.ordered_ids)
            assert "ref:plan" not in before_ids

            # Fixed-pane navigation, help, and the palette work pre-publish.
            await page.press(page.artifacts_digit("patches"))
            await page.expect_state("artifacts_subtab", "patches")
            await page.press(page.artifacts_digit("beads"))
            await page.expect_state("artifacts_subtab", "beads")
            await page.press("question_mark")
            await page.expect_modal("HelpModal")
            await page.press("escape")
            await page.expect_no_modal()
            await page.press("semicolon")
            await page.expect_modal("CommandPaletteModal")
            await page.press("escape")
            await page.expect_no_modal()

            before_digits = {
                descriptor.id: descriptor.digit_shortcut
                for descriptor in bootstrap.descriptors
            }
            before_commands = {
                spec.id: spec.key_display
                for spec in catalog_for(app)
                if spec.id.startswith("artifacts.")
            }

            release.set()
            await wait_for_status(page, "completed")

            published = app.artifacts_descriptor_snapshot
            assert not published.is_pending
            assert published.generation != bootstrap.generation
            assert "ref:plan" in published.ordered_ids
            after_digits = {
                descriptor.id: descriptor.digit_shortcut
                for descriptor in published.descriptors
            }
            # Every advertised target has a mounted pane; digits match labels.
            from sase.ace.tui.widgets.artifacts.view import ArtifactsView

            view = page.query_one_widget("#artifacts-view", ArtifactsView)
            assert tuple(d.id for d in view.descriptors) == tuple(published.ordered_ids)
            for descriptor in published.descriptors:
                assert view.query_one(f"#{descriptor.pane_id}") is not None
                assert after_digits[descriptor.id] == descriptor.digit_shortcut
            after_commands = {
                spec.id: spec.key_display
                for spec in catalog_for(app)
                if spec.id.startswith("artifacts.")
            }
            assert set(after_commands) >= set(before_commands) | {"artifacts.ref:plan"}
            # Selection survived publication; digits track the live strip.
            assert app.current_artifacts_subtab == "beads"
            await page.press(page.artifacts_digit("ref:plan"))
            await page.expect_state("artifacts_subtab", "ref:plan")
            # Digit presses resolve against the committed generation only.
            assert before_digits.get("ref:plan") is None


async def test_hidden_agents_startup_publishes_without_losing_selection() -> None:
    """A hidden ArtifactsView still publishes one generation coherently."""

    entered = threading.Event()
    release = threading.Event()
    with patch(
        publication_path(),
        gated_blocking_factory(entered, release, records=plan_records()),
    ):
        async with AcePage(initial_tab="agents", startup_policy="real") as page:
            await page.wait_for(
                lambda _state: entered.is_set(),
                timeout=LOAD_TOLERANT_TIMEOUT,
                timeout_message=lambda: "entered" + " never set",
            )
            assert page.app.artifacts_descriptor_snapshot.is_pending
            release.set()
            await wait_for_status(page, "completed")
            published = page.app.artifacts_descriptor_snapshot
            assert "ref:plan" in published.ordered_ids


async def test_pending_provider_jump_applies_only_without_supersede() -> None:
    """An explicit provider request during pending applies on publication."""

    entered = threading.Event()
    release = threading.Event()
    with patch(
        publication_path(),
        gated_blocking_factory(entered, release, records=plan_records()),
    ):
        async with AcePage(initial_tab="artifacts", startup_policy="real") as page:
            await page.wait_for(
                lambda _state: entered.is_set(),
                timeout=LOAD_TOLERANT_TIMEOUT,
                timeout_message=lambda: "entered" + " never set",
            )
            page.app.action_show_artifacts_pane("ref:plan")
            assert page.app._artifacts_pending_provider_target == "ref:plan"
            release.set()
            await wait_for_status(page, "completed")
            assert page.app.current_artifacts_subtab == "ref:plan"


async def test_user_navigation_supersedes_pending_provider_jump() -> None:
    """Later navigation wins over a retained pending provider target."""

    entered = threading.Event()
    release = threading.Event()
    with patch(
        publication_path(),
        gated_blocking_factory(entered, release, records=plan_records()),
    ):
        async with AcePage(initial_tab="artifacts", startup_policy="real") as page:
            await page.wait_for(
                lambda _state: entered.is_set(),
                timeout=LOAD_TOLERANT_TIMEOUT,
                timeout_message=lambda: "entered" + " never set",
            )
            page.app.action_show_artifacts_pane("ref:plan")
            await page.press(page.artifacts_digit("beads"))
            await page.expect_state("artifacts_subtab", "beads")
            release.set()
            await wait_for_status(page, "completed")
            assert page.app.current_artifacts_subtab == "beads"


async def test_pending_digit_without_target_does_nothing() -> None:
    """A digit with no displayed target never replays against a later strip."""

    entered = threading.Event()
    release = threading.Event()
    with patch(
        publication_path(),
        gated_blocking_factory(entered, release, records=plan_records()),
    ):
        async with AcePage(initial_tab="artifacts", startup_policy="real") as page:
            await page.wait_for(
                lambda _state: entered.is_set(),
                timeout=LOAD_TOLERANT_TIMEOUT,
                timeout_message=lambda: "entered" + " never set",
            )
            before = page.app.current_artifacts_subtab
            # "9" has no bootstrap target in the fixed strip.
            page.app.action_show_artifacts_digit(9)
            assert page.app.current_artifacts_subtab == before
            release.set()
            await wait_for_status(page, "completed")
            # The earlier dead digit did not replay into a later selection.
            assert page.app.current_artifacts_subtab == before


async def test_zero_providers_completes_authoritatively() -> None:
    """A completed zero-provider result clears pending without provider panes."""

    entered = threading.Event()
    release = threading.Event()
    with patch(
        publication_path(),
        gated_blocking_factory(entered, release, records=()),
    ):
        async with AcePage(initial_tab="artifacts", startup_policy="real") as page:
            await page.wait_for(
                lambda _state: entered.is_set(),
                timeout=LOAD_TOLERANT_TIMEOUT,
                timeout_message=lambda: "entered" + " never set",
            )
            assert page.app.artifacts_descriptor_snapshot.is_pending
            release.set()
            await wait_for_status(page, "completed")
            published = page.app.artifacts_descriptor_snapshot
            assert published.is_completed_zero_providers
            assert not published.is_pending
