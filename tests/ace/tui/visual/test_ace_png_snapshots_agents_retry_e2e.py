"""ACE retry PNGs backed by real fakey subprocess artifacts and loaders."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import time

import pytest

from sase.ace.testing import AcePage
from sase.axe import runner_utils
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui._retry_family_loader_fixture import build_retrying_plan_family
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture
from tests.fakey.harness import (
    FakeyRetryHarness,
    retryable_failure,
    successful_attempt,
)

pytestmark = pytest.mark.visual

_VISUAL_NOW = datetime(2026, 7, 6, 12, 0, 0)


def _patch_sentinel_pid_liveness(monkeypatch: pytest.MonkeyPatch) -> None:
    def is_sentinel_live(pid: int | None) -> bool:
        return pid == 4242

    for target in (
        "sase.ace.tui.models.agent_loader.is_process_running",
        "sase.ace.tui.models._loaders._running_loaders.is_process_running",
        "sase.ace.tui.models._loaders._workflow_loaders.is_process_running",
    ):
        monkeypatch.setattr(target, is_sentinel_live)


async def _open_agents_tab(page: AcePage, *, agent_count: int) -> None:
    await wait_for_startup(page)
    await page.press("shift+tab")
    await page.expect_state("tab", "agents")
    await page.expect_state("agent_count", agent_count)
    await wait_for_visual_idle(page)


async def _reload_finished_agent(page: AcePage) -> None:
    page.app._load_agents(full_history=True, source="visual_fakey_finished")
    await page.expect_state("agent_count", 1)
    await wait_for_svg_contains(page, "DONE")
    await wait_for_visual_idle(page)
    assert_page_svg_contains(page, "DONE")


async def test_real_fakey_retry_countdown_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = FakeyRetryHarness(
        tmp_path,
        monkeypatch,
        wait_times=[30],
        expose_to_agent_loader=True,
        artifacts_timestamp="20260706115800",
        is_home_mode=True,
    )
    harness.seed_running_agent(started_at=datetime(2026, 7, 6, 11, 58, 0))
    harness.use_scenario(
        monkeypatch,
        [retryable_failure(), successful_attempt("retry recovered")],
    )
    retry_wait = harness.barrier("retry-wait", timeout=15)
    harness.hold_retry_wait(monkeypatch, retry_wait)
    patch_startup_loaders(monkeypatch, use_real_agent_loader=True)

    handle = harness.run_in_background()
    try:
        harness.wait_for_retry_state("retrying")
        retry_wait.wait_until_started()
        harness.normalize_visual_timestamps(_VISUAL_NOW, countdown_seconds=9)
        _patch_sentinel_pid_liveness(monkeypatch)
        monkeypatch.setattr(time, "time", lambda: _VISUAL_NOW.timestamp())

        async with AcePage(query='"fakey"', changespecs=changespecs()) as page:
            await _open_agents_tab(page, agent_count=1)

            loaded = page.app._agents[0]
            assert (loaded.status, loaded.retry_status) == ("RETRYING", "retrying")
            await wait_for_svg_contains(page, "RETRYING (9s)")
            await wait_for_visual_idle(page)
            assert_page_svg_contains(page, "RETRYING (9s)")
            assert_page_svg_contains(page, "Retries:")
            assert_page_svg_contains(page, "1/1")
            ace_png_visual.assert_page_png(
                page,
                "agents_retry_e2e_countdown_120x40",
                title="ACE real fakey retry countdown",
            )

            retry_wait.open()
            assert handle.finish().success is True
            harness.clear_running_agent()
            await _reload_finished_agent(page)
    finally:
        retry_wait.open()
        if handle.thread.is_alive():
            try:
                handle.finish(timeout=5)
            except (AssertionError, TimeoutError):
                runner_utils._killed_state["killed"] = True
                handle.thread.join(5)
        runner_utils.reset_killed()


async def test_real_loader_plan_family_retry_countdown_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed coder attempt cannot conceal its live family's backoff."""
    sase_home = tmp_path / ".sase"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    now_epoch = _VISUAL_NOW.timestamp()
    build_retrying_plan_family(
        sase_home,
        next_retry_at_epoch=now_epoch + 9,
    )
    _patch_sentinel_pid_liveness(monkeypatch)
    monkeypatch.setattr(time, "time", lambda: now_epoch)
    patch_startup_loaders(monkeypatch, use_real_agent_loader=True)

    async with AcePage(query='"retry-family"', changespecs=changespecs()) as page:
        await _open_agents_tab(page, agent_count=1)

        loaded = page.app._agents[0]
        assert (loaded.status, loaded.retry_status) == ("RETRYING", "retrying")
        assert (loaded.retry_count, loaded.max_retries) == (2, 3)
        await wait_for_svg_contains(page, "RETRYING (9s)")
        await wait_for_visual_idle(page)
        assert_page_svg_contains(page, "RETRYING (9s)")
        assert_page_svg_contains(page, "Retries:")
        assert_page_svg_contains(page, "2/3")
        ace_png_visual.assert_page_png(
            page,
            "agents_retry_e2e_plan_family_countdown_120x40",
            title="ACE real-loader plan family retry countdown",
        )


async def test_real_fakey_running_fallback_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = FakeyRetryHarness(
        tmp_path,
        monkeypatch,
        max_retries=1,
        wait_times=[0],
        fallback_model="fakey-small",
        expose_to_agent_loader=True,
        artifacts_timestamp="20260706115900",
        is_home_mode=True,
    )
    harness.seed_running_agent(started_at=datetime(2026, 7, 6, 11, 59, 0))
    fallback = harness.barrier("fallback", timeout=15)
    harness.use_scenario(
        monkeypatch,
        [
            retryable_failure("primary unavailable"),
            retryable_failure("primary still unavailable"),
            {
                **successful_attempt("fallback recovered"),
                "steps": fallback.steps(),
            },
        ],
    )
    patch_startup_loaders(monkeypatch, use_real_agent_loader=True)

    handle = harness.run_in_background()
    try:
        fallback.wait_until_started()
        state = harness.wait_for_retry_state("running_fallback")
        assert state.fallback_model == "fakey-small"
        harness.normalize_visual_timestamps(_VISUAL_NOW)
        _patch_sentinel_pid_liveness(monkeypatch)

        async with AcePage(query='"fakey"', changespecs=changespecs()) as page:
            await _open_agents_tab(page, agent_count=1)

            loaded = page.app._agents[0]
            assert (
                loaded.status,
                loaded.retry_count,
                loaded.using_fallback,
                loaded.fallback_model,
            ) == ("RUNNING", 1, True, "fakey-small")
            await wait_for_svg_contains(page, "fakey-small")
            await wait_for_visual_idle(page)
            assert_page_svg_contains(page, "RUNNING")
            assert_page_svg_contains(page, "↻1▸fakey")
            assert_page_svg_contains(page, "Fallback:")
            assert_page_svg_contains(page, "fakey-small")
            ace_png_visual.assert_page_png(
                page,
                "agents_retry_e2e_running_fallback_120x40",
                title="ACE real fakey running fallback",
            )

            fallback.open()
            assert handle.finish().success is True
            harness.clear_running_agent()
            await _reload_finished_agent(page)
    finally:
        fallback.open()
        if handle.thread.is_alive():
            try:
                handle.finish(timeout=5)
            except (AssertionError, TimeoutError):
                runner_utils._killed_state["killed"] = True
                handle.thread.join(5)
        runner_utils.reset_killed()


async def test_real_fakey_completed_retry_chain_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = FakeyRetryHarness(
        tmp_path,
        monkeypatch,
        wait_times=[0],
        spawn_new_agent=True,
        expose_to_agent_loader=True,
        artifacts_timestamp="20260706114500",
    )
    harness.seed_running_agent(started_at=datetime(2026, 7, 6, 11, 45, 0))
    harness.use_scenario(
        monkeypatch,
        [retryable_failure("temporarily unavailable"), successful_attempt()],
    )
    child_artifacts = harness.run_spawn_retry_chain(
        child_artifacts_timestamp="20260706115500"
    )
    harness.normalize_visual_timestamps(
        _VISUAL_NOW,
        stopped_at=datetime(2026, 7, 6, 11, 46, 0),
    )
    harness.normalize_visual_timestamps(
        _VISUAL_NOW,
        stopped_at=datetime(2026, 7, 6, 11, 57, 0),
        artifacts_dir=child_artifacts,
    )
    _patch_sentinel_pid_liveness(monkeypatch)
    patch_startup_loaders(monkeypatch, use_real_agent_loader=True)

    async with AcePage(query='"fakey"', changespecs=changespecs()) as page:
        await _open_agents_tab(page, agent_count=2)

        loaded_states = [
            (
                agent.status,
                agent.retry_attempt,
                agent.retried_as_timestamp,
                agent.retry_chain_root_timestamp,
            )
            for agent in page.app._agents
        ]
        assert [state[0] for state in loaded_states] == ["DONE", "FAILED (RETRIED)"]
        assert loaded_states[0][1:] == (1, None, "20260706114500")
        assert loaded_states[1][1:] == (
            0,
            "20260706115500",
            "20260706114500",
        )
        await wait_for_svg_contains(page, "FAILED")
        await wait_for_visual_idle(page)
        assert_page_svg_contains(page, "FAILED")
        assert_page_svg_contains(page, "↳")
        assert_page_svg_contains(page, "↻1")
        assert_page_svg_contains(page, "DONE")
        ace_png_visual.assert_page_png(
            page,
            "agents_retry_e2e_completed_chain_120x40",
            title="ACE real fakey completed retry chain",
        )
