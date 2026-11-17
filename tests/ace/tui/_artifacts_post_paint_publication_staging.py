"""Staging, epoch, and late-lifecycle handling for post-paint publication."""

from __future__ import annotations

import threading
from typing import Any
from unittest.mock import patch

from sase.ace.testing import AcePage
from sase.ace.tui.actions._artifacts_publication_diff import (
    is_staged_replacement_widget,
)
from tests._load_tolerant import LOAD_TOLERANT_TIMEOUT
from tests.ace.tui._artifacts_post_paint_publication_helpers import (
    gated_blocking_factory,
    plan_records,
    publication_path,
    switcher_child,
    wait_for_status,
)

__all__ = [
    "test_cold_nonempty_agents_identity_runs_after_first_paint_off_pump",
    "test_leave_and_return_does_not_revive_pending_provider_jump",
    "test_open_help_contents_include_published_provider",
    "test_open_palette_selects_newly_published_command",
    "test_scope_change_during_staging_is_applied_before_commit",
    "test_stale_epoch_is_rejected_then_coalesced",
    "test_teardown_during_mount_discards_staged_widgets",
]


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
        providers = provider_descriptors(plan_records(), ())
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
        patch(publication_path(), _stale_then_fresh),
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
            await wait_for_status(page, "completed")
            assert committed_epochs
            assert committed_epochs[0] != 0 or calls["count"] >= 2
            assert "ref:plan" in page.app.artifacts_descriptor_snapshot.ordered_ids


async def test_leave_and_return_does_not_revive_pending_provider_jump() -> None:
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
            page.app.current_tab = "agents"
            page.app.current_tab = "artifacts"
            assert page.app._artifacts_pending_provider_target is None
            before = page.app.current_artifacts_subtab
            release.set()
            await wait_for_status(page, "completed")
            assert page.app.current_artifacts_subtab == before
            assert page.app.current_artifacts_subtab != "ref:plan"


async def test_open_palette_selects_newly_published_command() -> None:
    from sase.ace.tui.commands.types import CommandPaletteResult
    from sase.ace.tui.modals.command_palette_modal import CommandPaletteModal

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
            await page.press("semicolon")
            await page.expect_modal("CommandPaletteModal")
            release.set()
            await wait_for_status(page, "completed")
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
        publication_path(),
        gated_blocking_factory(entered, release, records=plan_records()),
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
        publication_path(),
        gated_blocking_factory(entered, release, records=plan_records()),
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
            await wait_for_status(page, "completed")
            from sase.ace.tui.widgets.artifacts.view import ArtifactsView

            view = page.query_one_widget("#artifacts-view", ArtifactsView)
            plan = page.app.artifacts_descriptor_snapshot.lookup("ref:plan")
            assert plan is not None
            pane = switcher_child(view, plan.pane_id)
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
            publication_path(),
            gated_blocking_factory(entered, release, records=plan_records()),
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
