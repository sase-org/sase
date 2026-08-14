"""Shared panel fakes and builders for header-enrichment tests."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from sase.ace.patch.models import DeltaEntry, DeltaLineStats
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.models.agent_associated_plan import PhaseBeadSummary
from sase.ace.tui.widgets.prompt_panel._agent_display import AgentDisplayMixin
from sase.ace.tui.widgets.prompt_panel._agent_display_hints import (
    AgentHintsDisplayMixin,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import (
    _DetailHeaderSummary,
)
from sase.ace.tui.widgets.prompt_panel._artifact_files import ArtifactFilePath
from tests.ace.tui.widgets._agent_display_helpers import make_agent

BUILD_DETAIL_HEADER_SUMMARY = (
    "sase.ace.tui.widgets.prompt_panel._agent_display_async.build_detail_header_summary"
)


class FakeWorker:
    def __init__(self, result: object | None = None) -> None:
        self.is_running = True
        self.result = result
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True
        self.is_running = False


class HeaderEnrichmentPanel(AgentDisplayMixin, AgentHintsDisplayMixin):
    def __init__(self) -> None:
        self.captured: list[object] = []
        self.worker = FakeWorker()
        self.worker_fn: Callable[[], object] | None = None

    def update(self, renderable: object) -> None:
        self.captured.append(renderable)

    def run_worker(self, fn: Callable[[], object], *, thread: bool) -> FakeWorker:
        assert thread
        self.worker_fn = fn
        self.worker = FakeWorker()
        return self.worker


class MessageHeaderEnrichmentPanel(HeaderEnrichmentPanel):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[object] = []

    def post_message(self, message: object) -> None:
        self.messages.append(message)


class RecordingApp:
    """Minimal ``call_from_thread`` stand-in: runs the callback inline.

    Real Textual marshals the call onto the event loop from a worker
    thread; these tests run everything on one thread, so calling straight
    through is equivalent for exercising what gets published and when.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    def call_from_thread(self, fn: Callable[..., object], *args: object) -> object:
        self.calls.append(args)
        return fn(*args)


class StreamingHeaderEnrichmentPanel(MessageHeaderEnrichmentPanel):
    """A panel with an ``app`` so the streaming worker can publish batches."""

    def __init__(self) -> None:
        super().__init__()
        self.app = RecordingApp()


def patch_summary_builder(
    monkeypatch: pytest.MonkeyPatch,
    build: Callable[..., _DetailHeaderSummary],
) -> None:
    """Replace the async worker's summary builder with ``build``."""
    monkeypatch.setattr(BUILD_DETAIL_HEADER_SUMMARY, build)


def set_context(
    panel: AgentDisplayMixin,
    agent_identity: tuple[Any, ...],
    *,
    current: bool,
) -> None:
    def is_current(
        identity: tuple[Any, ...],
        generation: int,
        attempt_view_mode: str,
        attempt_pinned_number: int | None,
    ) -> bool:
        return (
            current
            and identity == agent_identity
            and generation == 7
            and attempt_view_mode == "merged"
            and attempt_pinned_number is None
        )

    panel.set_agent_detail_render_context(
        generation=7,
        attempt_view_mode="merged",
        attempt_pinned_number=None,
        is_current=is_current,
    )


def make_summary() -> _DetailHeaderSummary:
    return _DetailHeaderSummary(
        delta_entries=[
            DeltaEntry(
                path="src/foo.py",
                change_type="M",
                line_stats=DeltaLineStats(modified=1),
            )
        ],
        artifact_file_paths=[
            ArtifactFilePath(
                display_path="artifact.txt",
                actual_path="/tmp/artifact.txt",
            )
        ],
    )


def make_phase_summary(bead_id: str, *, notes: str | None = None) -> PhaseBeadSummary:
    return PhaseBeadSummary(
        id=bead_id,
        phase_title="Deferred selected phase title",
        description="Deferred selected phase description.",
        actual_plan_path="/tmp/workspace/sase/repos/plans/epic.md",
        display_plan_path="sase/repos/plans/epic.md",
        plan_exists=True,
        plan_readable=True,
        epic_title="Deferred phase epic",
        size="medium",
        notes=notes,
    )


def make_family_agent() -> Agent:
    root = make_agent(
        raw_suffix="family-root",
        agent_name="family--plan",
        agent_family="family",
        agent_family_role="plan",
        role_suffix="--plan",
        plan_chain_root=True,
    )
    child = make_agent(
        raw_suffix="family-child",
        agent_name="family--code",
        agent_family="family",
        agent_family_role="code",
        role_suffix="--code",
    )
    root.followup_agents = [child]
    assert root.is_family_container_row
    return root
