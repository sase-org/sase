"""Follow one selected live reply without rebuilding the detail document."""

from __future__ import annotations

import asyncio
import copy
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rich.console import Group
from rich.text import Text

from sase.agent.artifact_files_cache import get_global_cache
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_session_members import (
    agent_row_is_in_flight,
    current_agent_session_turn_row,
)
from sase.ace.tui.util.lazy_syntax import lazy_renderable
from sase.project_display_names import humanize_vcs_refs_in_text

from ..decks.card_block import CardBlock
from ..decks.card_part import CardPart, REPLY_CARD_ID
from ._agent_display_content import render_timestamp_divider


_WAITING_REPLY = "Waiting for agent response.\n"


class _LiveReplyRegion(Group):
    """A replaceable, invisible wrapper around one live turn's reply body."""

    __slots__ = ("agent_identity",)
    __sase_live_reply_region__ = True

    def __init__(self, agent_identity: tuple[Any, ...], *renderables: Any) -> None:
        self.agent_identity = agent_identity
        super().__init__(*renderables)


def live_reply_region(
    agent_identity: tuple[Any, ...], renderables: list[Any] | tuple[Any, ...]
) -> _LiveReplyRegion:
    """Mark the currently rendered live reply body for targeted replacement."""
    return _LiveReplyRegion(agent_identity, *renderables)


def _contains_live_reply_region(
    content: object, agent_identity: tuple[Any, ...]
) -> bool:
    """Return whether the Main Reply card contains a region for this source."""
    if isinstance(content, _LiveReplyRegion):
        return content.agent_identity == agent_identity
    if isinstance(content, (CardPart, CardBlock)):
        if isinstance(content, CardPart) and content.card_id != REPLY_CARD_ID:
            return False
        return any(
            _contains_live_reply_region(child, agent_identity)
            for child in content.renderables
        )
    if isinstance(content, Group):
        return any(
            _contains_live_reply_region(child, agent_identity)
            for child in content.renderables
        )
    return False


def _replace_live_reply_region(
    content: object,
    agent_identity: tuple[Any, ...],
    renderables: tuple[Any, ...],
) -> tuple[object, int]:
    """Replace matching live reply regions while preserving all other cards."""
    if isinstance(content, _LiveReplyRegion):
        if content.agent_identity == agent_identity:
            return _LiveReplyRegion(agent_identity, *renderables), 1
        return content, 0
    if isinstance(content, CardPart):
        if content.card_id != REPLY_CARD_ID:
            return content, 0
        children, count = _replace_children(
            tuple(content.renderables), agent_identity, renderables
        )
        return (CardPart(content.card_id, content.title, *children), count)
    if isinstance(content, CardBlock):
        children, count = _replace_children(
            tuple(content.renderables), agent_identity, renderables
        )
        return (
            CardBlock(
                content.block_id,
                content.title,
                *children,
                meta=content.meta,
            ),
            count,
        )
    if isinstance(content, Group):
        children, count = _replace_children(
            tuple(content.renderables), agent_identity, renderables
        )
        return Group(*children), count
    return content, 0


def _replace_children(
    children: tuple[Any, ...],
    agent_identity: tuple[Any, ...],
    renderables: tuple[Any, ...],
) -> tuple[tuple[Any, ...], int]:
    updated: list[Any] = []
    count = 0
    for child in children:
        replacement, replaced = _replace_live_reply_region(
            child, agent_identity, renderables
        )
        updated.append(replacement)
        count += replaced
    return tuple(updated), count


@dataclass(frozen=True, slots=True)
class _ReplyFileSignature:
    mtime_ns: int
    size: int


@dataclass(frozen=True, slots=True)
class _LiveReplySource:
    selected_identity: tuple[Any, ...]
    reply_identity: tuple[Any, ...]
    generation: int
    attempt_view_mode: str
    attempt_pinned_number: int | None
    reply_path: str
    timestamps_path: str


@dataclass(frozen=True, slots=True)
class _LiveReplySnapshot:
    source: _LiveReplySource
    signatures: tuple[_ReplyFileSignature | None, _ReplyFileSignature | None]
    chunks: tuple[tuple[str, str], ...]
    live_text: str | None


def _reply_signature(path: str) -> _ReplyFileSignature | None:
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return _ReplyFileSignature(stat.st_mtime_ns, stat.st_size)


def _collect_live_reply_snapshot(source: _LiveReplySource) -> _LiveReplySnapshot:
    """Read a stable two-file reply snapshot on a worker thread."""
    before = (
        _reply_signature(source.timestamps_path),
        _reply_signature(source.reply_path),
    )
    cache = get_global_cache()
    raw_chunks = cache.read_reply_chunks(source.timestamps_path, source.reply_path)
    live_text = cache.read_live_reply(source.reply_path)
    after = (
        _reply_signature(source.timestamps_path),
        _reply_signature(source.reply_path),
    )
    if before != after:
        raise _ReplyChangedDuringRead
    return _LiveReplySnapshot(
        source=source,
        signatures=after,
        chunks=tuple(raw_chunks or ()),
        live_text=live_text,
    )


class _ReplyChangedDuringRead(Exception):
    """A writer changed reply files while the worker was collecting them."""


def _snapshot_renderables(snapshot: _LiveReplySnapshot) -> tuple[Any, ...]:
    """Prepare Markdown renderables from immutable reply data off the UI thread."""
    renderables: list[Any] = []
    if snapshot.chunks:
        for timestamp, chunk in snapshot.chunks:
            renderables.append(render_timestamp_divider(timestamp))
            body = chunk.strip()
            if body:
                renderables.append(
                    lazy_renderable(
                        humanize_vcs_refs_in_text(body),
                        "markdown",
                    )
                )
        return tuple(renderables)

    body = (snapshot.live_text or "").strip()
    if body:
        renderables.append(lazy_renderable(humanize_vcs_refs_in_text(body), "markdown"))
    else:
        renderables.append(Text(_WAITING_REPLY, style="dim italic"))
    return tuple(renderables)


def is_live_reply_agent(agent: Agent) -> bool:
    if agent.agent_type != AgentType.RUNNING or not agent_row_is_in_flight(agent):
        return False
    return not (agent.is_workflow_child and agent.step_type in ("bash", "python"))


def _selected_live_reply_agent(agent: Agent) -> Agent | None:
    """Choose the one concrete in-flight turn currently shown in Reply."""
    current_turn = current_agent_session_turn_row(agent)
    if current_turn is not None:
        return current_turn if is_live_reply_agent(current_turn) else None

    for candidate in reversed((agent, *tuple(agent.followup_agents or ()))):
        if is_live_reply_agent(candidate):
            return candidate
    return None


def _build_live_reply_source(
    selected: Agent,
    target: Agent,
    generation: int,
    attempt_view_mode: str,
    attempt_pinned_number: int | None,
) -> _LiveReplySource | None:
    """Resolve the selected concrete agent's artifact paths off the UI thread."""
    resolved_target = copy.copy(target)
    artifacts_dir = resolved_target.get_artifacts_dir()
    if not artifacts_dir:
        return None
    resolved_dir = os.path.abspath(os.path.expanduser(artifacts_dir))
    return _LiveReplySource(
        selected_identity=selected.identity,
        reply_identity=target.identity,
        generation=generation,
        attempt_view_mode=attempt_view_mode,
        attempt_pinned_number=attempt_pinned_number,
        reply_path=os.path.join(resolved_dir, "live_reply.md"),
        timestamps_path=os.path.join(resolved_dir, "live_reply_timestamps.jsonl"),
    )


_LIVE_REPLY_THROTTLE_SECONDS = 0.3
_LIVE_REPLY_POLL_SECONDS = 1.0


class LiveReplyFollowMixin:
    """Panel-owned event, throttle, poll, collection, and apply controller."""

    _live_reply_source: _LiveReplySource | None = None
    _live_reply_timer: Any | None = None
    _live_reply_config_generation: int = 0
    _live_reply_running: bool = False
    _live_reply_pending: bool = False
    _live_reply_scheduled: bool = False
    _live_reply_last_dispatch: float = 0.0
    _live_reply_last_probe: float = 0.0
    _live_reply_applied_signatures: (
        tuple[_ReplyFileSignature | None, _ReplyFileSignature | None] | None
    ) = None
    _live_reply_render_generation: int = 0

    def configure_live_reply_follow(self, selected: Agent) -> None:
        """Prepare a fresh selected-source descriptor after a normal render."""
        self.cancel_live_reply_follow()
        self._live_reply_config_generation += 1
        config_generation = self._live_reply_config_generation
        app = self._live_reply_app()
        context = getattr(self, "_agent_detail_render_context", None)
        if (
            app is None
            or getattr(app, "current_tab", None) != "agents"
            or getattr(self, "id", None) != "agent-prompt-panel"
            or getattr(self, "attempt_pinned_number", None) is not None
            or getattr(self, "_agent_hint_mode_rendered", False)
            or context is None
        ):
            return
        get_selected = getattr(app, "_get_selected_agent", None)
        current_selected = get_selected() if callable(get_selected) else None
        if current_selected is None or current_selected.identity != selected.identity:
            return
        target = _selected_live_reply_agent(selected)
        if target is None or not _contains_live_reply_region(
            getattr(self, "_last_prompt_panel_content", None), target.identity
        ):
            return

        self._live_reply_render_generation = int(context.generation)
        self._live_reply_pending = True
        self._live_reply_last_probe = 0.0

        async def prepare() -> None:
            descriptor = await asyncio.to_thread(
                _build_live_reply_source,
                selected,
                target,
                int(context.generation),
                str(context.attempt_view_mode),
                context.attempt_pinned_number,
            )
            if config_generation != self._live_reply_config_generation:
                return
            if descriptor is None or not self._live_reply_context_current(descriptor):
                self._live_reply_pending = False
                return
            self._live_reply_source = descriptor
            self._live_reply_request()

        from ...util.pump_tasks import spawn_pump_free_task

        task = spawn_pump_free_task(
            self,
            prepare(),
            name="selected live reply source",
            registry_attr="_live_reply_follow_tasks",
        )
        if task is None:
            self._live_reply_pending = False

    def _live_reply_app(self) -> Any | None:
        try:
            return self.app  # type: ignore[attr-defined]
        except Exception:
            return None

    def cancel_live_reply_follow(self) -> None:
        """Invalidate the source and stop scheduled collection work."""
        self._live_reply_config_generation = (
            int(getattr(self, "_live_reply_config_generation", 0)) + 1
        )
        timer = getattr(self, "_live_reply_timer", None)
        self._live_reply_timer = None
        self._live_reply_scheduled = False
        if timer is not None:
            try:
                timer.stop()
            except Exception:
                pass
        for task in tuple(getattr(self, "_live_reply_follow_tasks", ())):
            task.cancel()
        self._live_reply_source = None
        self._live_reply_pending = False
        self._live_reply_running = False
        self._live_reply_applied_signatures = None
        self._live_reply_last_probe = 0.0

    def live_reply_path_matches(self, path: Path) -> bool:
        """Match watcher paths against the prepared source without disk access."""
        source = getattr(self, "_live_reply_source", None)
        if source is None:
            return False
        candidate = os.path.abspath(os.path.expanduser(str(path)))
        return candidate in {source.reply_path, source.timestamps_path}

    def on_live_reply_artifact_change(self, paths: tuple[Path, ...]) -> None:
        """Route matching reply events without setting Agents dirty state."""
        if any(self.live_reply_path_matches(path) for path in paths):
            self._live_reply_request()

    def maybe_probe_live_reply_drift(self, *, now_mono: float | None = None) -> None:
        """Stat only the selected reply files once per second as a backstop."""
        source = getattr(self, "_live_reply_source", None)
        if source is None or not self._live_reply_is_idle_and_current(source):
            return
        now = time.monotonic() if now_mono is None else now_mono
        if now - self._live_reply_last_probe < _LIVE_REPLY_POLL_SECONDS:
            return
        self._live_reply_last_probe = now
        if getattr(self, "_live_reply_probe_running", False):
            self._live_reply_probe_pending = True
            return
        self._live_reply_probe_running = True

        async def probe() -> None:
            try:
                signatures = await asyncio.to_thread(
                    lambda: (
                        _reply_signature(source.timestamps_path),
                        _reply_signature(source.reply_path),
                    )
                )
                if self._live_reply_source != source:
                    return
                if not self._live_reply_context_current(source):
                    self.cancel_live_reply_follow()
                    return
                if signatures != self._live_reply_applied_signatures:
                    self._live_reply_request()
            finally:
                self._live_reply_probe_running = False
                if getattr(self, "_live_reply_probe_pending", False):
                    self._live_reply_probe_pending = False
                    self._live_reply_last_probe = 0.0
                    self.maybe_probe_live_reply_drift()

        from ...util.pump_tasks import spawn_pump_free_task

        task = spawn_pump_free_task(
            self,
            probe(),
            name="selected live reply signature probe",
            registry_attr="_live_reply_follow_tasks",
        )
        if task is None:
            self._live_reply_probe_running = False

    def _live_reply_request(self) -> None:
        source = getattr(self, "_live_reply_source", None)
        if source is None or not self._live_reply_context_current(source):
            return
        self._live_reply_pending = True
        if self._live_reply_running:
            return
        if not self._live_reply_is_idle_and_current(source):
            self._live_reply_schedule(0.25)
            return
        remaining = _LIVE_REPLY_THROTTLE_SECONDS - (
            time.monotonic() - self._live_reply_last_dispatch
        )
        self._live_reply_schedule(max(0.0, remaining))

    def _live_reply_schedule(self, delay: float) -> None:
        if self._live_reply_scheduled:
            return
        self._live_reply_scheduled = True
        try:
            self._live_reply_timer = self.set_timer(  # type: ignore[attr-defined]
                max(0.0, delay), self._live_reply_timer_fired
            )
        except Exception:
            self._live_reply_scheduled = False
            self._live_reply_timer = None
            self._live_reply_pending = False

    def _live_reply_timer_fired(self) -> None:
        self._live_reply_scheduled = False
        self._live_reply_timer = None
        if not self._live_reply_pending or self._live_reply_running:
            return
        source = self._live_reply_source
        if source is None or not self._live_reply_context_current(source):
            self._live_reply_pending = False
            return
        if not self._live_reply_is_idle_and_current(source):
            self._live_reply_schedule(0.25)
            return

        self._live_reply_pending = False
        self._live_reply_running = True
        self._live_reply_last_dispatch = time.monotonic()

        async def collect_apply() -> None:
            accepted = False
            try:
                snapshot = await asyncio.to_thread(_collect_live_reply_snapshot, source)
                if not self._live_reply_is_idle_and_current(source):
                    self._live_reply_pending = True
                    return
                renderables = await asyncio.to_thread(_snapshot_renderables, snapshot)
                # Revalidate after both worker awaits; the selected source and its
                # presentation generation may have changed while files were read.
                if not self._live_reply_is_idle_and_current(source):
                    self._live_reply_pending = True
                    return
                if snapshot.signatures == self._live_reply_applied_signatures:
                    accepted = True
                    return
                current = getattr(self, "_last_prompt_panel_content", None)
                updated, replaced = _replace_live_reply_region(
                    current, source.reply_identity, renderables
                )
                if replaced != 1:
                    return
                self.update(updated)  # type: ignore[attr-defined]
                self._live_reply_applied_signatures = snapshot.signatures
                accepted = True
            except _ReplyChangedDuringRead:
                self._live_reply_pending = True
            finally:
                if self._live_reply_source == source:
                    self._live_reply_running = False
                    if not accepted and not self._live_reply_pending:
                        self._live_reply_pending = True
                    if self._live_reply_pending:
                        self._live_reply_request()

        from ...util.pump_tasks import spawn_pump_free_task

        task = spawn_pump_free_task(
            self,
            collect_apply(),
            name="selected live reply snapshot",
            registry_attr="_live_reply_follow_tasks",
        )
        if task is None:
            self._live_reply_running = False
            self._live_reply_pending = False

    def _live_reply_is_idle_and_current(self, source: _LiveReplySource) -> bool:
        if not self._live_reply_context_current(source):
            return False
        app = self._live_reply_app()
        if app is None:
            return False
        try:
            gate = getattr(app, "_nav_gate", None)
            if gate is not None and gate.is_navigating():
                return False
            prompt_active = getattr(app, "_prompt_input_active", None)
            return not (callable(prompt_active) and prompt_active())
        except Exception:
            return False

    def _live_reply_context_current(self, source: _LiveReplySource) -> bool:
        app = self._live_reply_app()
        context = getattr(self, "_agent_detail_render_context", None)
        if (
            app is None
            or context is None
            or getattr(app, "current_tab", None) != "agents"
            or getattr(self, "attempt_pinned_number", None) is not None
            or getattr(self, "_agent_hint_mode_rendered", False)
            or source.generation != self._live_reply_render_generation
            or source.attempt_view_mode != getattr(self, "attempt_view_mode", "merged")
            or source.attempt_pinned_number
            != getattr(self, "attempt_pinned_number", None)
        ):
            return False
        if not context.is_current(
            source.selected_identity,
            source.generation,
            source.attempt_view_mode,
            source.attempt_pinned_number,
        ):
            return False
        get_selected = getattr(app, "_get_selected_agent", None)
        selected = get_selected() if callable(get_selected) else None
        if selected is None or selected.identity != source.selected_identity:
            return False
        target = _selected_live_reply_agent(selected)
        return (
            target is not None
            and target.identity == source.reply_identity
            and _contains_live_reply_region(
                getattr(self, "_last_prompt_panel_content", None),
                source.reply_identity,
            )
        )


__all__ = ["LiveReplyFollowMixin", "is_live_reply_agent", "live_reply_region"]
