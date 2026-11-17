"""Widget replacement and mount-failure handling for post-paint publication."""

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
    "test_healthy_provider_is_replaced_when_it_degrades",
    "test_partial_mount_failure_discards_staged_and_retries",
    "test_unchanged_widgets_are_retained_across_generations",
]


def _research_issue() -> Any:
    from sase.ace.tui._artifact_tab_model import ProviderDiscoveryIssue

    return ProviderDiscoveryIssue(
        message="research provider missing",
        code="missing_ref_provider",
        kind="research",
        source="test",
    )


async def test_healthy_provider_is_replaced_when_it_degrades() -> None:
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
            from sase.ace.tui.widgets.artifacts.degraded_pane import (
                ArtifactsDegradedPane,
            )
            from sase.ace.tui.widgets.artifacts.plans_pane import ArtifactsPlansPane
            from sase.ace.tui.widgets.artifacts.view import ArtifactsView

            view = page.query_one_widget("#artifacts-view", ArtifactsView)
            plan = page.app.artifacts_descriptor_snapshot.lookup("ref:plan")
            assert plan is not None
            plan_pane_id = plan.pane_id
            healthy = switcher_child(view, plan_pane_id)
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
                publication_path(),
                gated_blocking_factory(
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
                        switcher_child(view, plan_pane_id), ArtifactsDegradedPane
                    ),
                    timeout=LOAD_TOLERANT_TIMEOUT,
                    timeout_message=lambda: "degraded pane never replaced healthy",
                )
            replacement = switcher_child(view, plan_pane_id)
            assert isinstance(replacement, ArtifactsDegradedPane)
            assert id(replacement) != healthy_id


async def test_unchanged_widgets_are_retained_across_generations() -> None:
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
            from sase.ace.tui.widgets.artifacts.view import ArtifactsView

            view = page.query_one_widget("#artifacts-view", ArtifactsView)
            stitches = switcher_child(view, "artifacts-stitches-pane")
            assert stitches is not None
            stitches_id = id(stitches)
            generation = page.app.artifacts_descriptor_snapshot.generation

            again_entered = threading.Event()
            again_release = threading.Event()
            with patch(
                publication_path(),
                gated_blocking_factory(
                    again_entered, again_release, records=plan_records()
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
            assert switcher_child(view, "artifacts-stitches-pane") is stitches
            assert id(switcher_child(view, "artifacts-stitches-pane")) == stitches_id


async def test_partial_mount_failure_discards_staged_and_retries() -> None:
    entered = threading.Event()
    release = threading.Event()
    mount_calls = {"n": 0, "fail": True}

    with patch(
        publication_path(),
        gated_blocking_factory(
            entered,
            release,
            records=plan_records(),
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
                publication_path(),
                gated_blocking_factory(
                    retry_entered,
                    retry_release,
                    records=plan_records(),
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
                await wait_for_status(page, "completed")
            assert "ref:plan" in page.app.artifacts_descriptor_snapshot.ordered_ids
