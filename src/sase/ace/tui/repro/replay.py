"""Headless Agents-tab replay harness for repro bundles."""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass, replace
from types import SimpleNamespace
from typing import Literal
from unittest.mock import patch

from sase.ace.changespec import ChangeSpec
from sase.ace.testing import AcePage
from sase.ace.tui import AceApp
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.models.agent import AgentType
from sase.ace.tui.models.agent_loader import AgentLoadState

from .agent_factory import (
    agent_to_repro_identity,
    agents_from_repro_rows,
    load_state_from_repro,
)
from .invariants import ReproInvariantReport, check_bundle_invariants
from .schema import (
    AgentIdentity,
    ReproAppState,
    ReproBundle,
    ReproLoadStep,
    ReproScreen,
)
from .serialize import serialize_agent_rows

ReplayMergeMode = Literal["current", "legacy_replace"]


@dataclass(frozen=True)
class ReproReplayStepSnapshot:
    """Runtime state captured after one replayed loader step."""

    step_id: str
    visible_identities: list[AgentIdentity]
    agents_with_children_identities: list[AgentIdentity]
    selected_identity: AgentIdentity | None
    load_state: dict[str, object] | None
    agents_seen_complete_history: bool
    screen_text: str
    svg: str


@dataclass(frozen=True)
class ReproReplayResult:
    """Replay output consumed by tests and the later CLI phase."""

    bundle: ReproBundle
    observed_bundle: ReproBundle
    invariant_report: ReproInvariantReport
    steps: list[ReproReplayStepSnapshot]
    verdict: str

    @property
    def ok(self) -> bool:
        return self.invariant_report.ok

    @property
    def failed_invariant_codes(self) -> list[str]:
        return [failure.code for failure in self.invariant_report.failures]

    def assert_fixed(self) -> None:
        if self.ok:
            return
        details = "\n".join(
            f"{failure.code}: {failure.message}"
            for failure in self.invariant_report.failures
        )
        raise AssertionError(f"{self.verdict}\n{details}")


@dataclass(frozen=True)
class _ReplayDiskLoadResult:
    """Loader result shape consumed by the Agents-tab loading path."""

    all_agents: list[Agent]
    dismissed_from_loader: list[Agent]
    load_state: AgentLoadState


async def replay_agents_tab_bundle(
    bundle: ReproBundle,
    *,
    merge_mode: ReplayMergeMode = "current",
    size: tuple[int, int] = (120, 40),
    changespecs: list[ChangeSpec] | None = None,
) -> ReproReplayResult:
    """Replay a bundle through ``AceApp.run_test()`` and check invariants."""

    loader = _FixtureLoader(bundle.load_steps)
    with _patched_replay_environment(loader, merge_mode):
        async with AcePage(
            query='"sase-repro"',
            size=size,
            changespecs=[] if changespecs is None else changespecs,
            initial_tab="agents",
            wait_for_startup_state=False,
        ) as page:
            await page.expect_state("tab", "agents")

            observed_steps: list[ReproLoadStep] = []
            snapshots: list[ReproReplayStepSnapshot] = []
            for step in bundle.load_steps:
                _expand_visible_fixture_parents(page.app, step)
                page.app._load_agents(full_history=step.load_state.complete_history)
                await page.pause()

                observed = _capture_replay_step(page, step)
                observed_steps.append(observed)
                snapshots.append(_snapshot_from_page(page, observed))

    observed_bundle = replace(bundle, load_steps=observed_steps)
    report = check_bundle_invariants(observed_bundle)
    return ReproReplayResult(
        bundle=bundle,
        observed_bundle=observed_bundle,
        invariant_report=report,
        steps=snapshots,
        verdict=_build_verdict(report, merge_mode),
    )


class _FixtureLoader:
    def __init__(self, steps: list[ReproLoadStep]) -> None:
        self._steps = list(steps)
        self.calls: list[bool] = []

    def __call__(self, *_args: object, **kwargs: object) -> _ReplayDiskLoadResult:
        if not self._steps:
            raise AssertionError("replay loader was called after fixture exhaustion")
        step = self._steps.pop(0)
        full_history = bool(kwargs.get("full_history", False))
        self.calls.append(full_history)
        if full_history != step.load_state.complete_history:
            raise AssertionError(
                f"replay step {step.step_id!r} expected full_history="
                f"{step.load_state.complete_history!r}, got {full_history!r}"
            )
        return _ReplayDiskLoadResult(
            all_agents=agents_from_repro_rows(step.agent_rows),
            dismissed_from_loader=[],
            load_state=load_state_from_repro(step.load_state),
        )


def _patched_replay_environment(
    loader: _FixtureLoader,
    merge_mode: ReplayMergeMode,
) -> ExitStack:
    stack = ExitStack()
    stack.enter_context(
        patch(
            "sase.ace.tui.actions.agents._loading.load_agents_from_disk_with_state",
            loader,
        )
    )
    stack.enter_context(
        patch.object(AceApp, "_start_post_mount_background_loads", lambda _self: None)
    )
    stack.enter_context(
        patch("sase.ace.dismissed_agents.load_dismissed_agents", return_value=set())
    )
    stack.enter_context(
        patch("sase.notifications.read_notification_snapshot", _empty_notifications)
    )
    if merge_mode == "legacy_replace":
        stack.enter_context(
            patch.object(
                AceApp,
                "_merge_incomplete_load_after_complete_history",
                _legacy_replace_only_merge,
            )
        )
    return stack


def _expand_visible_fixture_parents(app: AceApp, step: ReproLoadStep) -> None:
    visible = set(step.app_state.visible_identities)
    for row in step.agent_rows:
        if row.identity not in visible or row.parent_timestamp is None:
            continue
        app._fold_manager.expand(row.parent_timestamp)


def _capture_replay_step(page: AcePage, source: ReproLoadStep) -> ReproLoadStep:
    app = page.app
    app_state = ReproAppState(
        visible_identities=[agent_to_repro_identity(agent) for agent in app._agents],
        selected_identity=_selected_identity(app),
        dismissed_identities=[
            (identity[0].value, identity[1], identity[2])
            for identity in sorted(
                app._dismissed_agents, key=_runtime_identity_sort_key
            )
        ],
        flattened_parent_timestamps=[],
        agents_seen_complete_history=bool(app._agents_seen_complete_history),
    )
    return replace(
        source,
        agent_rows=serialize_agent_rows(app._agents_with_children),
        app_state=app_state,
        screen=ReproScreen(text=page.screen, svg_path=None),
    )


def _snapshot_from_page(
    page: AcePage,
    observed: ReproLoadStep,
) -> ReproReplayStepSnapshot:
    app = page.app
    load_state: dict[str, object] | None = None
    if app._agent_load_state is not None:
        load_state = {
            "tier": app._agent_load_state.tier,
            "complete_history": app._agent_load_state.complete_history,
            "complete_visible_inbox": app._agent_load_state.complete_visible_inbox,
            "artifact_source": app._agent_load_state.artifact_source,
            "used_artifact_index": app._agent_load_state.used_artifact_index,
            "index_error": app._agent_load_state.index_error,
            "repair_recommended": app._agent_load_state.repair_recommended,
            "repair_reason": app._agent_load_state.repair_reason,
            "truncated": app._agent_load_state.truncated,
        }
    return ReproReplayStepSnapshot(
        step_id=observed.step_id,
        visible_identities=list(observed.app_state.visible_identities),
        agents_with_children_identities=[
            agent_to_repro_identity(agent) for agent in app._agents_with_children
        ],
        selected_identity=observed.app_state.selected_identity,
        load_state=load_state,
        agents_seen_complete_history=bool(app._agents_seen_complete_history),
        screen_text=page.screen,
        svg=page.export_svg(title=f"Agents tab replay {observed.step_id}"),
    )


def _selected_identity(app: AceApp) -> AgentIdentity | None:
    if not app._agents or not (0 <= app.current_idx < len(app._agents)):
        return None
    return agent_to_repro_identity(app._agents[app.current_idx])


def _runtime_identity_sort_key(
    identity: tuple[AgentType, str, str | None],
) -> tuple[str, str, str]:
    return (identity[1], identity[2] or "", identity[0].value)


def _legacy_replace_only_merge(
    _self: AceApp,
    _prep: object,
    _load_state: object | None,
) -> None:
    return None


def _empty_notifications(*_args: object, **_kwargs: object) -> SimpleNamespace:
    return SimpleNamespace(
        notifications=[],
        counts=SimpleNamespace(priority=0, errors=0, rest=0, muted=0),
        unread_count=0,
        active_count=0,
        snoozed_count=0,
        muted_count=0,
        expired_ids=[],
    )


def _build_verdict(
    report: ReproInvariantReport,
    merge_mode: ReplayMergeMode,
) -> str:
    if report.ok:
        if merge_mode == "legacy_replace":
            return "legacy control unexpectedly passed the captured bug-class replay"
        return "current code fixed for the captured Agents-tab bug class"
    failed = ", ".join(failure.code for failure in report.failures)
    if merge_mode == "legacy_replace":
        return f"legacy control reproduced the historical Agents-tab bug: {failed}"
    return f"current code is not fixed for the captured Agents-tab bug class: {failed}"
