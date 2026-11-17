"""Retry, removal, shutdown, and flag coverage for post-paint publication."""

from __future__ import annotations

import threading
from typing import Any
from unittest.mock import patch

import pytest

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
    "test_cold_identity_not_called_during_construction",
    "test_open_help_and_palette_refresh_on_publication",
    "test_provider_removal_while_selected_falls_back_to_default",
    "test_publication_covers_files_flag",
    "test_publication_covers_retired_agent_flag",
    "test_retry_after_failed_discovery_retains_generation",
    "test_shutdown_before_completion_discards_late_result",
]


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
        providers = provider_descriptors(plan_records(), ())
        return (
            ("test-token",),
            int(artifacts_tab_cache_epoch()),
            build_artifacts_strip(providers),
            "completed",
        )

    with patch(publication_path(), _flaky):
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
            await wait_for_status(page, "completed")
            assert "ref:plan" in page.app.artifacts_descriptor_snapshot.ordered_ids


async def test_provider_removal_while_selected_falls_back_to_default() -> None:
    """Removing the selected provider pane selects the fixed default."""

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
            release.set()
            await wait_for_status(page, "completed")
            await page.press(page.artifacts_digit("ref:plan"))
            await page.expect_state("artifacts_subtab", "ref:plan")

            removed_entered = threading.Event()
            removed_release = threading.Event()
            published_generation = page.app.artifacts_descriptor_snapshot.generation
            with patch(
                publication_path(),
                gated_blocking_factory(removed_entered, removed_release, records=()),
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
        publication_path(),
        gated_blocking_factory(entered, release, records=plan_records()),
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
        publication_path(),
        gated_blocking_factory(entered, release, records=plan_records()),
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
            await wait_for_status(page, "completed")
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
                    for spec in catalog_for(page.app)
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
            publication_path(),
            gated_blocking_factory(entered, release, records=plan_records()),
        ),
    ):
        async with AcePage(initial_tab="artifacts", startup_policy="real") as page:
            await page.wait_for(
                lambda _state: entered.is_set(),
                timeout=LOAD_TOLERANT_TIMEOUT,
                timeout_message=lambda: "entered" + " never set",
            )
            release.set()
            await wait_for_status(page, "completed")
            published = page.app.artifacts_descriptor_snapshot
            assert ("files" in published.ordered_ids) is files_enabled


@pytest.mark.parametrize("agent_retired", [True, False])
async def test_publication_covers_retired_agent_flag(agent_retired: bool) -> None:
    from sase.feature_flags import override_flags

    entered = threading.Event()
    release = threading.Event()
    with (
        override_flags(artifacts_agent_pane_retired=agent_retired),
        patch(
            publication_path(),
            gated_blocking_factory(entered, release, records=plan_records()),
        ),
    ):
        async with AcePage(initial_tab="artifacts", startup_policy="real") as page:
            await page.wait_for(
                lambda _state: entered.is_set(),
                timeout=LOAD_TOLERANT_TIMEOUT,
                timeout_message=lambda: "entered" + " never set",
            )
            release.set()
            await wait_for_status(page, "completed")
            published = page.app.artifacts_descriptor_snapshot
            assert ("agents" in published.ordered_ids) is not agent_retired
            assert "ref:plan" in published.ordered_ids
