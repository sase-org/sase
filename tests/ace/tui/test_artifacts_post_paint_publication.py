"""Delayed provider discovery: first paint with fixed panes, then one generation.

Uses the real startup scheduling path (``startup_policy="real"``): the only
stub is the blocking worker body, gated so tests can observe bootstrap,
drive fixed-pane UI while discovery is pending, and then verify one
coherent publication.
"""

from __future__ import annotations

import threading
from typing import Any
from unittest.mock import patch

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.actions._artifacts_publication_diff import (
    is_staged_replacement_widget,
)
from tests._load_tolerant import LOAD_TOLERANT_TIMEOUT


def _plan_records() -> tuple[Any, ...]:
    """Return one healthy plan provider record through the real spec path."""

    from pathlib import Path

    from sase.ace.tui._artifact_tab_model import ProjectProviderRecord
    from sase.artifact_providers import builtin_plan_ref_provider_spec
    from sase.sidecar_ref_config import SidecarRefPolicy

    return (
        ProjectProviderRecord(
            project="sase",
            display_name="sase",
            workspace_dir=None,
            role="plans",
            root=Path("."),
            policy=SidecarRefPolicy(
                role="plans",
                ref_kind="plan",
                is_document=True,
                spec=builtin_plan_ref_provider_spec(),
            ),
        ),
    )


def _gated_blocking_factory(
    entered: threading.Event,
    release: threading.Event,
    *,
    records: tuple[Any, ...] | None = None,
    issues: tuple[Any, ...] = (),
    token: tuple[object, ...] | None = ("test-token",),
    status: str = "completed",
) -> Any:
    """Build a gated fake for the publication worker's blocking body."""

    def _fake() -> tuple[Any, int, tuple[Any, ...], str]:
        from sase.ace.tui._artifact_tab_descriptors import (
            build_artifacts_strip,
            provider_descriptors,
        )
        from sase.ace.tui.artifact_tabs import artifacts_tab_cache_epoch

        entered.set()
        assert release.wait(timeout=LOAD_TOLERANT_TIMEOUT), "discovery gate stuck"
        providers = provider_descriptors(tuple(records or ()), issues)
        epoch = int(artifacts_tab_cache_epoch())
        return token, epoch, build_artifacts_strip(providers), status

    return _fake


def _publication_path() -> str:
    return "sase.ace.tui.actions._artifacts_publication._fresh_artifacts_discovery_blocking"


async def _wait_for_status(page: AcePage, status: str) -> None:
    def _is(status_name: str) -> bool:
        snapshot = page.app.artifacts_descriptor_snapshot
        return snapshot.status.value == status_name

    await page.wait_for(
        lambda _state: _is(status),
        timeout=LOAD_TOLERANT_TIMEOUT,
        timeout_message=lambda: f"artifacts discovery never reached {status}",
    )


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
        _publication_path(),
        _gated_blocking_factory(entered, release, records=_plan_records()),
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
                for spec in _catalog_for(app)
                if spec.id.startswith("artifacts.")
            }

            release.set()
            await _wait_for_status(page, "completed")

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
                for spec in _catalog_for(app)
                if spec.id.startswith("artifacts.")
            }
            assert set(after_commands) >= set(before_commands) | {"artifacts.ref:plan"}
            # Selection survived publication; digits track the live strip.
            assert app.current_artifacts_subtab == "beads"
            await page.press(page.artifacts_digit("ref:plan"))
            await page.expect_state("artifacts_subtab", "ref:plan")
            # Digit presses resolve against the committed generation only.
            assert before_digits.get("ref:plan") is None


def _catalog_for(app: Any) -> list[Any]:
    from sase.ace.tui.commands import build_command_catalog

    return list(
        build_command_catalog(
            app._keymap_registry,
            snapshot=getattr(app, "artifacts_descriptor_snapshot", None),
        )
    )


async def test_hidden_agents_startup_publishes_without_losing_selection() -> None:
    """A hidden ArtifactsView still publishes one generation coherently."""

    entered = threading.Event()
    release = threading.Event()
    with patch(
        _publication_path(),
        _gated_blocking_factory(entered, release, records=_plan_records()),
    ):
        async with AcePage(initial_tab="agents", startup_policy="real") as page:
            await page.wait_for(
                lambda _state: entered.is_set(),
                timeout=LOAD_TOLERANT_TIMEOUT,
                timeout_message=lambda: "entered" + " never set",
            )
            assert page.app.artifacts_descriptor_snapshot.is_pending
            release.set()
            await _wait_for_status(page, "completed")
            published = page.app.artifacts_descriptor_snapshot
            assert "ref:plan" in published.ordered_ids


async def test_pending_provider_jump_applies_only_without_supersede() -> None:
    """An explicit provider request during pending applies on publication."""

    entered = threading.Event()
    release = threading.Event()
    with patch(
        _publication_path(),
        _gated_blocking_factory(entered, release, records=_plan_records()),
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
            await _wait_for_status(page, "completed")
            assert page.app.current_artifacts_subtab == "ref:plan"


async def test_user_navigation_supersedes_pending_provider_jump() -> None:
    """Later navigation wins over a retained pending provider target."""

    entered = threading.Event()
    release = threading.Event()
    with patch(
        _publication_path(),
        _gated_blocking_factory(entered, release, records=_plan_records()),
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
            await _wait_for_status(page, "completed")
            assert page.app.current_artifacts_subtab == "beads"


async def test_pending_digit_without_target_does_nothing() -> None:
    """A digit with no displayed target never replays against a later strip."""

    entered = threading.Event()
    release = threading.Event()
    with patch(
        _publication_path(),
        _gated_blocking_factory(entered, release, records=_plan_records()),
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
            await _wait_for_status(page, "completed")
            # The earlier dead digit did not replay into a later selection.
            assert page.app.current_artifacts_subtab == before


async def test_zero_providers_completes_authoritatively() -> None:
    """A completed zero-provider result clears pending without provider panes."""

    entered = threading.Event()
    release = threading.Event()
    with patch(
        _publication_path(),
        _gated_blocking_factory(entered, release, records=()),
    ):
        async with AcePage(initial_tab="artifacts", startup_policy="real") as page:
            await page.wait_for(
                lambda _state: entered.is_set(),
                timeout=LOAD_TOLERANT_TIMEOUT,
                timeout_message=lambda: "entered" + " never set",
            )
            assert page.app.artifacts_descriptor_snapshot.is_pending
            release.set()
            await _wait_for_status(page, "completed")
            published = page.app.artifacts_descriptor_snapshot
            assert published.is_completed_zero_providers
            assert not published.is_pending


async def test_retry_after_failed_discovery_retains_generation() -> None:
    """A failed pass keeps the bootstrap generation; an explicit retry heals."""

    from sase.ace.tui.actions._artifacts_publication import (
        ArtifactsPublicationMixin,
    )

    first_entered = threading.Event()
    first_release = threading.Event()
    second_entered = threading.Event()
    second_release = threading.Event()
    calls = {"count": 0}

    def _flaky() -> tuple[Any, int, tuple[Any, ...], str]:
        from sase.ace.tui._artifact_tab_descriptors import (
            build_artifacts_strip,
            provider_descriptors,
        )

        from sase.ace.tui.artifact_tabs import artifacts_tab_cache_epoch

        calls["count"] += 1
        if calls["count"] == 1:
            first_entered.set()
            assert first_release.wait(timeout=LOAD_TOLERANT_TIMEOUT)
            return (
                None,
                int(artifacts_tab_cache_epoch()),
                build_artifacts_strip(()),
                "failed",
            )
        second_entered.set()
        assert second_release.wait(timeout=LOAD_TOLERANT_TIMEOUT)
        providers = provider_descriptors(_plan_records(), ())
        return (
            ("test-token",),
            int(artifacts_tab_cache_epoch()),
            build_artifacts_strip(providers),
            "completed",
        )

    with patch(_publication_path(), _flaky):
        async with AcePage(initial_tab="artifacts", startup_policy="real") as page:
            await page.wait_for(
                lambda _state: first_entered.is_set(),
                timeout=LOAD_TOLERANT_TIMEOUT,
                timeout_message=lambda: "first_entered" + " never set",
            )
            first_release.set()
            await page.wait_for(
                lambda _state: (
                    page.app._artifacts_last_discovery_error is not None
                    and page.app.artifacts_descriptor_snapshot.is_pending
                ),
                timeout=LOAD_TOLERANT_TIMEOUT,
                timeout_message=lambda: "failed discovery never recorded",
            )
            assert page.app.artifacts_descriptor_snapshot.is_pending
            ArtifactsPublicationMixin.action_retry_artifacts_discovery(page.app)
            await page.wait_for(
                lambda _state: second_entered.is_set(),
                timeout=LOAD_TOLERANT_TIMEOUT,
                timeout_message=lambda: "second_entered" + " never set",
            )
            second_release.set()
            await _wait_for_status(page, "completed")
            assert "ref:plan" in page.app.artifacts_descriptor_snapshot.ordered_ids


async def test_provider_removal_while_selected_falls_back_to_default() -> None:
    """Removing the selected provider pane selects the fixed default."""

    entered = threading.Event()
    release = threading.Event()
    with patch(
        _publication_path(),
        _gated_blocking_factory(entered, release, records=_plan_records()),
    ):
        async with AcePage(initial_tab="artifacts", startup_policy="real") as page:
            await page.wait_for(
                lambda _state: entered.is_set(),
                timeout=LOAD_TOLERANT_TIMEOUT,
                timeout_message=lambda: "entered" + " never set",
            )
            release.set()
            await _wait_for_status(page, "completed")
            await page.press(page.artifacts_digit("ref:plan"))
            await page.expect_state("artifacts_subtab", "ref:plan")

            removed_entered = threading.Event()
            removed_release = threading.Event()
            published_generation = page.app.artifacts_descriptor_snapshot.generation
            with patch(
                _publication_path(),
                _gated_blocking_factory(removed_entered, removed_release, records=()),
            ):
                page.app._schedule_artifacts_provider_discovery(reason="test")
                await page.wait_for(
                    lambda _state: removed_entered.is_set(),
                    timeout=LOAD_TOLERANT_TIMEOUT,
                    timeout_message=lambda: "removed_entered" + " never set",
                )
                removed_release.set()
                await page.wait_for(
                    lambda _state: (
                        page.app.artifacts_descriptor_snapshot.generation
                        != published_generation
                    ),
                    timeout=LOAD_TOLERANT_TIMEOUT,
                    timeout_message=lambda: "removal publication never landed",
                )
            assert "ref:plan" not in page.app.artifacts_descriptor_snapshot.ordered_ids
            assert page.app.current_artifacts_subtab == "stitches"


async def test_shutdown_before_completion_discards_late_result() -> None:
    """Results landing after teardown must not mutate the app."""

    from sase.ace.tui.actions._artifacts_publication import (
        ArtifactsPublicationMixin,
    )

    entered = threading.Event()
    release = threading.Event()
    with patch(
        _publication_path(),
        _gated_blocking_factory(entered, release, records=_plan_records()),
    ):
        async with AcePage(initial_tab="artifacts", startup_policy="real") as page:
            await page.wait_for(
                lambda _state: entered.is_set(),
                timeout=LOAD_TOLERANT_TIMEOUT,
                timeout_message=lambda: "entered" + " never set",
            )
            page.app._artifacts_discovery_teardown = True
            release.set()
            await page.wait_for(
                lambda _state: not page.app._artifacts_discovery_in_flight,
                timeout=LOAD_TOLERANT_TIMEOUT,
                timeout_message=lambda: "discovery pass never finished",
            )
            assert page.app.artifacts_descriptor_snapshot.is_pending
            assert isinstance(page.app, ArtifactsPublicationMixin)


async def test_open_help_and_palette_refresh_on_publication() -> None:
    """Already-open help/palette adopt the published generation in place."""

    entered = threading.Event()
    release = threading.Event()
    with patch(
        _publication_path(),
        _gated_blocking_factory(entered, release, records=_plan_records()),
    ):
        async with AcePage(initial_tab="artifacts", startup_policy="real") as page:
            await page.wait_for(
                lambda _state: entered.is_set(),
                timeout=LOAD_TOLERANT_TIMEOUT,
                timeout_message=lambda: "entered" + " never set",
            )
            await page.press("question_mark")
            await page.expect_modal("HelpModal")
            release.set()
            await _wait_for_status(page, "completed")
            await page.wait_for(
                lambda _state: _help_adopted_publication(page),
                timeout=LOAD_TOLERANT_TIMEOUT,
                timeout_message=lambda: "open help never adopted publication",
            )
            await page.press("escape")
            await page.expect_no_modal()


def _help_adopted_publication(page: AcePage) -> bool:
    """Return whether the open help modal reflects the published generation."""

    try:
        from sase.ace.tui.modals.help_modal.modal import HelpModal

        for screen in page.app.screen_stack:
            if isinstance(screen, HelpModal):
                catalog_ids = {
                    spec.id
                    for spec in _catalog_for(page.app)
                    if spec.id.startswith("artifacts.")
                }
                # The modal stayed open across publication, kept its (empty)
                # filter, re-rendered, and the committed catalog now carries
                # the provider pane.
                return (
                    "artifacts.ref:plan" in catalog_ids
                    and screen._filter_query == ""
                    and screen._filter_result is not None
                )
    except Exception:
        return False
    return False


async def test_cold_identity_not_called_during_construction() -> None:
    """Cold agent identity stays out of app construction and first paint."""

    import time

    from sase.core.agent_identity_facade import AgentIdentitySnapshot
    from sase.ace.tui import AceApp
    from sase.ace.testing.ace_page import _stop_ace_app_proc_observer

    construction_calls: list[float] = []
    original = AgentIdentitySnapshot.current

    def _recording(*args: Any, **kwargs: Any) -> Any:
        construction_calls.append(time.monotonic())
        return original(*args, **kwargs)

    with patch.object(AgentIdentitySnapshot, "current", _recording):
        app = AceApp(query='"identity"', refresh_interval=0, initial_tab="artifacts")
    try:
        assert construction_calls == []
    finally:
        _stop_ace_app_proc_observer(app)

    pilot_calls: list[float] = []
    with patch.object(AgentIdentitySnapshot, "current", _recording):
        # Reuse the same recorder; construction proved clean above.
        construction_calls.clear()
        async with AcePage(initial_tab="artifacts", startup_policy="real") as page:
            await page.wait_for(
                lambda _state: page.app._mount_state_loads_done,
                timeout=LOAD_TOLERANT_TIMEOUT,
                timeout_message=lambda: "mount state never loaded",
            )
            first_paint = page.app._startup_first_paint_mono
        pilot_calls.extend(construction_calls)
    assert first_paint is not None
    assert all(call >= first_paint for call in pilot_calls), (
        "cold identity must not run before first paint"
    )


@pytest.mark.parametrize("files_enabled", [True, False])
async def test_publication_covers_files_flag(files_enabled: bool) -> None:
    """The published generation matches the Files flag, not a later cache."""

    from sase.feature_flags import override_flags

    entered = threading.Event()
    release = threading.Event()
    with (
        override_flags(artifacts_files_pane=files_enabled),
        patch(
            _publication_path(),
            _gated_blocking_factory(entered, release, records=_plan_records()),
        ),
    ):
        async with AcePage(initial_tab="artifacts", startup_policy="real") as page:
            await page.wait_for(
                lambda _state: entered.is_set(),
                timeout=LOAD_TOLERANT_TIMEOUT,
                timeout_message=lambda: "entered" + " never set",
            )
            release.set()
            await _wait_for_status(page, "completed")
            published = page.app.artifacts_descriptor_snapshot
            assert ("files" in published.ordered_ids) is files_enabled


def _switcher_child(view: Any, widget_id: str) -> Any | None:
    switcher = view.query_one("#artifacts-content-switcher")
    return next(
        (
            child
            for child in switcher.children
            if getattr(child, "id", None) == widget_id
        ),
        None,
    )


def _research_issue() -> Any:
    from sase.ace.tui._artifact_tab_model import ProviderDiscoveryIssue

    return ProviderDiscoveryIssue(
        message="research provider missing",
        code="missing_ref_provider",
        kind="research",
        source="test",
    )


@pytest.mark.parametrize("agent_retired", [True, False])
async def test_publication_covers_retired_agent_flag(agent_retired: bool) -> None:
    from sase.feature_flags import override_flags

    entered = threading.Event()
    release = threading.Event()
    with (
        override_flags(artifacts_agent_pane_retired=agent_retired),
        patch(
            _publication_path(),
            _gated_blocking_factory(entered, release, records=_plan_records()),
        ),
    ):
        async with AcePage(initial_tab="artifacts", startup_policy="real") as page:
            await page.wait_for(
                lambda _state: entered.is_set(),
                timeout=LOAD_TOLERANT_TIMEOUT,
                timeout_message=lambda: "entered" + " never set",
            )
            release.set()
            await _wait_for_status(page, "completed")
            published = page.app.artifacts_descriptor_snapshot
            assert ("agents" in published.ordered_ids) is not agent_retired
            assert "ref:plan" in published.ordered_ids


async def test_healthy_provider_is_replaced_when_it_degrades() -> None:
    entered = threading.Event()
    release = threading.Event()
    with patch(
        _publication_path(),
        _gated_blocking_factory(entered, release, records=_plan_records()),
    ):
        async with AcePage(initial_tab="artifacts", startup_policy="real") as page:
            await page.wait_for(
                lambda _state: entered.is_set(),
                timeout=LOAD_TOLERANT_TIMEOUT,
                timeout_message=lambda: "entered" + " never set",
            )
            release.set()
            await _wait_for_status(page, "completed")
            from sase.ace.tui.widgets.artifacts.degraded_pane import (
                ArtifactsDegradedPane,
            )
            from sase.ace.tui.widgets.artifacts.plans_pane import ArtifactsPlansPane
            from sase.ace.tui.widgets.artifacts.view import ArtifactsView

            view = page.query_one_widget("#artifacts-view", ArtifactsView)
            plan = page.app.artifacts_descriptor_snapshot.lookup("ref:plan")
            assert plan is not None
            plan_pane_id = plan.pane_id
            healthy = _switcher_child(view, plan_pane_id)
            assert isinstance(healthy, ArtifactsPlansPane)
            healthy_id = id(healthy)

            degraded_entered = threading.Event()
            degraded_release = threading.Event()
            from sase.ace.tui._artifact_tab_model import ProviderDiscoveryIssue

            issue = ProviderDiscoveryIssue(
                message="provider exploded",
                code="provider_error",
                kind="plan",
                source="test",
            )
            with patch(
                _publication_path(),
                _gated_blocking_factory(
                    degraded_entered,
                    degraded_release,
                    records=(),
                    issues=(issue,),
                ),
            ):
                page.app._schedule_artifacts_provider_discovery(reason="test")
                await page.wait_for(
                    lambda _state: degraded_entered.is_set(),
                    timeout=LOAD_TOLERANT_TIMEOUT,
                    timeout_message=lambda: "degraded_entered never set",
                )
                degraded_release.set()
                await page.wait_for(
                    lambda _state: isinstance(
                        _switcher_child(view, plan_pane_id), ArtifactsDegradedPane
                    ),
                    timeout=LOAD_TOLERANT_TIMEOUT,
                    timeout_message=lambda: "degraded pane never replaced healthy",
                )
            replacement = _switcher_child(view, plan_pane_id)
            assert isinstance(replacement, ArtifactsDegradedPane)
            assert id(replacement) != healthy_id


async def test_unchanged_widgets_are_retained_across_generations() -> None:
    entered = threading.Event()
    release = threading.Event()
    with patch(
        _publication_path(),
        _gated_blocking_factory(entered, release, records=_plan_records()),
    ):
        async with AcePage(initial_tab="artifacts", startup_policy="real") as page:
            await page.wait_for(
                lambda _state: entered.is_set(),
                timeout=LOAD_TOLERANT_TIMEOUT,
                timeout_message=lambda: "entered" + " never set",
            )
            release.set()
            await _wait_for_status(page, "completed")
            from sase.ace.tui.widgets.artifacts.view import ArtifactsView

            view = page.query_one_widget("#artifacts-view", ArtifactsView)
            stitches = _switcher_child(view, "artifacts-stitches-pane")
            assert stitches is not None
            stitches_id = id(stitches)
            generation = page.app.artifacts_descriptor_snapshot.generation

            again_entered = threading.Event()
            again_release = threading.Event()
            with patch(
                _publication_path(),
                _gated_blocking_factory(
                    again_entered, again_release, records=_plan_records()
                ),
            ):
                page.app._schedule_artifacts_provider_discovery(reason="test")
                await page.wait_for(
                    lambda _state: again_entered.is_set(),
                    timeout=LOAD_TOLERANT_TIMEOUT,
                    timeout_message=lambda: "again_entered never set",
                )
                again_release.set()
                await page.wait_for(
                    lambda _state: (
                        page.app.artifacts_descriptor_snapshot.generation != generation
                    ),
                    timeout=LOAD_TOLERANT_TIMEOUT,
                    timeout_message=lambda: "second generation never landed",
                )
            assert _switcher_child(view, "artifacts-stitches-pane") is stitches
            assert id(_switcher_child(view, "artifacts-stitches-pane")) == stitches_id


async def test_partial_mount_failure_discards_staged_and_retries() -> None:
    entered = threading.Event()
    release = threading.Event()
    mount_calls = {"n": 0, "fail": True}

    with patch(
        _publication_path(),
        _gated_blocking_factory(
            entered,
            release,
            records=_plan_records(),
            issues=(_research_issue(),),
        ),
    ):
        async with AcePage(initial_tab="artifacts", startup_policy="real") as page:
            await page.wait_for(
                lambda _state: entered.is_set(),
                timeout=LOAD_TOLERANT_TIMEOUT,
                timeout_message=lambda: "entered" + " never set",
            )
            from sase.ace.tui.widgets.artifacts.view import ArtifactsView

            view = page.query_one_widget("#artifacts-view", ArtifactsView)
            switcher = view.query_one("#artifacts-content-switcher")
            original_mount = switcher.mount

            def _flaky_mount(*args: Any, **kwargs: Any) -> Any:
                mount_calls["n"] += 1
                if mount_calls["fail"] and mount_calls["n"] >= 2:
                    raise RuntimeError("second mount failed")
                return original_mount(*args, **kwargs)

            switcher.mount = _flaky_mount  # type: ignore[method-assign]
            release.set()
            await page.wait_for(
                lambda _state: (
                    page.app._artifacts_last_discovery_error is not None
                    and page.app.artifacts_descriptor_snapshot.is_pending
                ),
                timeout=LOAD_TOLERANT_TIMEOUT,
                timeout_message=lambda: "partial mount never recorded",
            )
            from sase.ace.tui.widgets.artifacts.view import ArtifactsView

            view = page.query_one_widget("#artifacts-view", ArtifactsView)
            switcher = view.query_one("#artifacts-content-switcher")
            staged = [
                child
                for child in switcher.children
                if is_staged_replacement_widget(child)
            ]
            assert staged == []
            assert "ref:plan" not in page.app.artifacts_descriptor_snapshot.ordered_ids

            mount_calls["fail"] = False
            mount_calls["n"] = 0
            retry_entered = threading.Event()
            retry_release = threading.Event()
            with patch(
                _publication_path(),
                _gated_blocking_factory(
                    retry_entered,
                    retry_release,
                    records=_plan_records(),
                    issues=(_research_issue(),),
                ),
            ):
                page.app.action_retry_artifacts_discovery()
                await page.wait_for(
                    lambda _state: retry_entered.is_set(),
                    timeout=LOAD_TOLERANT_TIMEOUT,
                    timeout_message=lambda: "retry_entered never set",
                )
                retry_release.set()
                await _wait_for_status(page, "completed")
            assert "ref:plan" in page.app.artifacts_descriptor_snapshot.ordered_ids


async def test_stale_epoch_is_rejected_then_coalesced() -> None:
    from sase.ace.tui.actions._artifacts_publication import ArtifactsPublicationMixin
    from sase.ace.tui.artifact_tabs import reset_artifacts_subtabs_cache

    first_entered = threading.Event()
    first_release = threading.Event()
    second_entered = threading.Event()
    second_release = threading.Event()
    calls = {"count": 0}
    committed_epochs: list[int] = []
    original_commit = ArtifactsPublicationMixin._commit_artifacts_snapshot

    def _commit(
        self: Any,
        new_snapshot: Any,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        committed_epochs.append(int(new_snapshot.source_epoch))
        return original_commit(self, new_snapshot, *args, **kwargs)

    def _stale_then_fresh() -> tuple[Any, int, tuple[Any, ...], str]:
        from sase.ace.tui._artifact_tab_descriptors import (
            build_artifacts_strip,
            provider_descriptors,
        )
        from sase.ace.tui.artifact_tabs import artifacts_tab_cache_epoch

        calls["count"] += 1
        providers = provider_descriptors(_plan_records(), ())
        descriptors = build_artifacts_strip(providers)
        if calls["count"] == 1:
            first_entered.set()
            assert first_release.wait(timeout=LOAD_TOLERANT_TIMEOUT)
            epoch = int(artifacts_tab_cache_epoch())
            reset_artifacts_subtabs_cache()
            return ("test-token",), epoch, descriptors, "completed"
        second_entered.set()
        assert second_release.wait(timeout=LOAD_TOLERANT_TIMEOUT)
        return (
            ("test-token",),
            int(artifacts_tab_cache_epoch()),
            descriptors,
            "completed",
        )

    with (
        patch.object(ArtifactsPublicationMixin, "_commit_artifacts_snapshot", _commit),
        patch(_publication_path(), _stale_then_fresh),
    ):
        async with AcePage(initial_tab="artifacts", startup_policy="real") as page:
            await page.wait_for(
                lambda _state: first_entered.is_set(),
                timeout=LOAD_TOLERANT_TIMEOUT,
                timeout_message=lambda: "first_entered never set",
            )
            first_release.set()
            await page.wait_for(
                lambda _state: second_entered.is_set(),
                timeout=LOAD_TOLERANT_TIMEOUT,
                timeout_message=lambda: "coalesced pass never started",
            )
            assert page.app.artifacts_descriptor_snapshot.is_pending
            assert committed_epochs == []
            second_release.set()
            await _wait_for_status(page, "completed")
            assert committed_epochs
            assert committed_epochs[0] != 0 or calls["count"] >= 2
            assert "ref:plan" in page.app.artifacts_descriptor_snapshot.ordered_ids


async def test_leave_and_return_does_not_revive_pending_provider_jump() -> None:
    entered = threading.Event()
    release = threading.Event()
    with patch(
        _publication_path(),
        _gated_blocking_factory(entered, release, records=_plan_records()),
    ):
        async with AcePage(initial_tab="artifacts", startup_policy="real") as page:
            await page.wait_for(
                lambda _state: entered.is_set(),
                timeout=LOAD_TOLERANT_TIMEOUT,
                timeout_message=lambda: "entered" + " never set",
            )
            page.app.action_show_artifacts_pane("ref:plan")
            assert page.app._artifacts_pending_provider_target == "ref:plan"
            page.app.current_tab = "agents"
            page.app.current_tab = "artifacts"
            assert page.app._artifacts_pending_provider_target is None
            before = page.app.current_artifacts_subtab
            release.set()
            await _wait_for_status(page, "completed")
            assert page.app.current_artifacts_subtab == before
            assert page.app.current_artifacts_subtab != "ref:plan"


async def test_open_palette_selects_newly_published_command() -> None:
    from sase.ace.tui.commands.types import CommandPaletteResult
    from sase.ace.tui.modals.command_palette_modal import CommandPaletteModal

    entered = threading.Event()
    release = threading.Event()
    with patch(
        _publication_path(),
        _gated_blocking_factory(entered, release, records=_plan_records()),
    ):
        async with AcePage(initial_tab="artifacts", startup_policy="real") as page:
            await page.wait_for(
                lambda _state: entered.is_set(),
                timeout=LOAD_TOLERANT_TIMEOUT,
                timeout_message=lambda: "entered" + " never set",
            )
            await page.press("semicolon")
            await page.expect_modal("CommandPaletteModal")
            release.set()
            await _wait_for_status(page, "completed")
            modal = page.app.screen
            assert isinstance(modal, CommandPaletteModal)
            assert any(spec.id == "artifacts.ref:plan" for spec in modal._all_specs)
            modal.dismiss(CommandPaletteResult(selected_id="artifacts.ref:plan"))
            await page.expect_no_modal()
            await page.expect_state("artifacts_subtab", "ref:plan")


async def test_open_help_contents_include_published_provider() -> None:
    entered = threading.Event()
    release = threading.Event()
    with patch(
        _publication_path(),
        _gated_blocking_factory(entered, release, records=_plan_records()),
    ):
        async with AcePage(initial_tab="artifacts", startup_policy="real") as page:
            await page.wait_for(
                lambda _state: entered.is_set(),
                timeout=LOAD_TOLERANT_TIMEOUT,
                timeout_message=lambda: "entered" + " never set",
            )
            await page.press("question_mark")
            await page.expect_modal("HelpModal")
            release.set()
            await _wait_for_status(page, "completed")
            await page.wait_for(
                lambda _state: _help_lists_plans(page),
                timeout=LOAD_TOLERANT_TIMEOUT,
                timeout_message=lambda: "open help never listed Plans",
            )


def _help_lists_plans(page: AcePage) -> bool:
    from sase.ace.tui.modals.help_modal.modal import HelpModal

    try:
        for screen in page.app.screen_stack:
            if isinstance(screen, HelpModal):
                blob = str(screen._get_bindings_for_tab())
                return "Plan" in blob
    except Exception:
        return False
    return False


async def test_teardown_during_mount_discards_staged_widgets() -> None:
    entered = threading.Event()
    release = threading.Event()
    with patch(
        _publication_path(),
        _gated_blocking_factory(entered, release, records=_plan_records()),
    ):
        async with AcePage(initial_tab="artifacts", startup_policy="real") as page:
            await page.wait_for(
                lambda _state: entered.is_set(),
                timeout=LOAD_TOLERANT_TIMEOUT,
                timeout_message=lambda: "entered" + " never set",
            )
            from sase.ace.tui.widgets.artifacts.view import ArtifactsView

            view = page.query_one_widget("#artifacts-view", ArtifactsView)
            switcher = view.query_one("#artifacts-content-switcher")
            original_mount = switcher.mount

            def _teardown_on_mount(*args: Any, **kwargs: Any) -> Any:
                page.app._artifacts_discovery_teardown = True
                return original_mount(*args, **kwargs)

            switcher.mount = _teardown_on_mount  # type: ignore[method-assign]
            release.set()
            await page.wait_for(
                lambda _state: not page.app._artifacts_discovery_in_flight,
                timeout=LOAD_TOLERANT_TIMEOUT,
                timeout_message=lambda: "discovery pass never finished",
            )
            assert page.app.artifacts_descriptor_snapshot.is_pending
            from sase.ace.tui.widgets.artifacts.view import ArtifactsView

            view = page.query_one_widget("#artifacts-view", ArtifactsView)
            switcher = view.query_one("#artifacts-content-switcher")
            assert not any(
                is_staged_replacement_widget(child) for child in switcher.children
            )


async def test_scope_change_during_staging_is_applied_before_commit() -> None:
    entered = threading.Event()
    release = threading.Event()
    with patch(
        _publication_path(),
        _gated_blocking_factory(entered, release, records=_plan_records()),
    ):
        async with AcePage(initial_tab="artifacts", startup_policy="real") as page:
            await page.wait_for(
                lambda _state: entered.is_set(),
                timeout=LOAD_TOLERANT_TIMEOUT,
                timeout_message=lambda: "entered" + " never set",
            )
            from sase.ace.tui.widgets.artifacts.view import ArtifactsView

            view = page.query_one_widget("#artifacts-view", ArtifactsView)
            switcher = view.query_one("#artifacts-content-switcher")
            original_mount = switcher.mount

            def _change_scope_on_mount(*args: Any, **kwargs: Any) -> Any:
                page.app.artifacts_project_scope = "sase"
                choices = getattr(page.app, "_artifacts_project_choices", None)
                display_names = getattr(choices, "display_names", None)
                if isinstance(display_names, dict):
                    display_names["sase"] = "SASE Display"
                return original_mount(*args, **kwargs)

            switcher.mount = _change_scope_on_mount  # type: ignore[method-assign]
            release.set()
            await _wait_for_status(page, "completed")
            from sase.ace.tui.widgets.artifacts.view import ArtifactsView

            view = page.query_one_widget("#artifacts-view", ArtifactsView)
            plan = page.app.artifacts_descriptor_snapshot.lookup("ref:plan")
            assert plan is not None
            pane = _switcher_child(view, plan.pane_id)
            scope = getattr(pane, "project_scope", None) or getattr(
                pane, "_project_scope", None
            )
            assert scope == "sase"


def _install_nonempty_owner_identity() -> None:
    """Give the isolated test home a complete owner overlay.

    Pytest redirects ``CONFIG_DIR`` and ``~/.sase``. The real identity
    loader still runs; this only supplies a nonempty owner for it to
    load, instead of stubbing ``unconfigured()``.
    """

    from pathlib import Path

    from sase.config.core import CONFIG_DIR, clear_config_cache
    from sase.core.paths import machine_name_path

    config_dir = Path(CONFIG_DIR)
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "sase_athena.yml").write_text(
        "id:\n  username: bbugyi200\n  machine_name: athena\n",
        encoding="utf-8",
    )
    selector = machine_name_path()
    selector.parent.mkdir(parents=True, exist_ok=True)
    selector.write_text("athena\n", encoding="utf-8")
    clear_config_cache()


async def test_cold_nonempty_agents_identity_runs_after_first_paint_off_pump() -> None:
    import threading
    import time

    from sase.core.agent_identity_facade import AgentIdentitySnapshot
    from sase.ace.tui.actions._artifacts_publication import (
        ArtifactsPublicationMixin,
    )

    _install_nonempty_owner_identity()
    original = AgentIdentitySnapshot.current
    calls: list[tuple[float, str, object]] = []

    def _recording(*args: Any, **kwargs: Any) -> Any:
        snapshot = original(*args, **kwargs)
        calls.append(
            (time.monotonic(), threading.current_thread().name, snapshot.owner)
        )
        return snapshot

    entered = threading.Event()
    release = threading.Event()
    with (
        patch.object(AgentIdentitySnapshot, "current", _recording),
        patch(
            _publication_path(),
            _gated_blocking_factory(entered, release, records=_plan_records()),
        ),
    ):
        async with AcePage(initial_tab="agents", startup_policy="real") as page:
            await page.wait_for(
                lambda _state: page.app._agents_first_load_done,
                timeout=LOAD_TOLERANT_TIMEOUT,
                timeout_message=lambda: "agents first load never finished",
            )
            first_paint = page.app._startup_first_paint_mono
            release.set()
            await page.wait_for(
                lambda _state: any(
                    call[0] >= (first_paint or 0) and call[2] is not None
                    for call in calls
                ),
                timeout=LOAD_TOLERANT_TIMEOUT,
                timeout_message=lambda: (
                    "nonempty identity never ran after first paint; "
                    f"calls={calls!r} first_paint={first_paint!r}"
                ),
            )
            assert isinstance(page.app, ArtifactsPublicationMixin)

    assert first_paint is not None
    after_paint = [call for call in calls if call[0] >= first_paint]
    nonempty = [call for call in after_paint if call[2] is not None]
    assert nonempty, "cold Agents identity must run a nonempty owner load"
    ui_thread = "MainThread"
    assert any(call[1] != ui_thread for call in nonempty), (
        "nonempty identity load must run off the UI thread"
    )
