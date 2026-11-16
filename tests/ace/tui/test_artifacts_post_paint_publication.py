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
    token: tuple[object, ...] | None = ("test-token",),
    status: str = "completed",
) -> Any:
    """Build a gated fake for the publication worker's blocking body."""

    def _fake() -> tuple[Any, int, tuple[Any, ...], str]:
        from sase.ace.tui._artifact_tab_descriptors import (
            build_artifacts_strip,
            provider_descriptors,
        )

        entered.set()
        assert release.wait(timeout=LOAD_TOLERANT_TIMEOUT), "discovery gate stuck"
        providers = provider_descriptors(tuple(records or ()), ())
        return token, 0, build_artifacts_strip(providers), status

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

        calls["count"] += 1
        if calls["count"] == 1:
            first_entered.set()
            assert first_release.wait(timeout=LOAD_TOLERANT_TIMEOUT)
            return None, 0, build_artifacts_strip(()), "failed"
        second_entered.set()
        assert second_release.wait(timeout=LOAD_TOLERANT_TIMEOUT)
        providers = provider_descriptors(_plan_records(), ())
        return ("test-token",), 0, build_artifacts_strip(providers), "completed"

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
