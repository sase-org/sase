"""Agent display with file-path hints for the agent prompt panel."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from hashlib import blake2b
from typing import Any, cast

from rich.console import Group, RenderableType
from rich.syntax import Syntax
from rich.text import Text

from sase.project_display_names import project_display_name_map_signature
from sase.ace.tui.tools.report import SlowToolCallReportSpec
from sase.ace.tui.tools.slow import slow_tool_call_threshold_ms_from_widget

from ...agent_completion import agent_wait_status_maps_for_app
from ...models.agent import Agent, AgentType, wait_display_agent
from ...models._agent_clan_sections import clan_section_member_rows
from ...models.agent_hoods import agent_owns_lane
from ...util.lazy_syntax import CachedRenderable
from ...util.trace import tui_trace
from ...util.xprompt_syntax import apply_xprompt_overlays
from ._agent_display_content import (
    get_phase_label,
    get_prompt_content,
    render_phase_divider,
    render_timestamp_divider,
)
from ._agent_clan_aggregation import (
    get_cached_clan_section_snapshot,
    prepare_clan_section_snapshot,
)
from ._agent_display_clan import (
    clan_disk_sections_for_fold_state,
    panel_fold_state_from_widget,
)
from ._agent_display_context import runner_capacity_for_app
from ._agent_display_header import AgentHeader, build_header_text
from ._agent_display_header_summary import (
    detail_header_summary_cache_key,
    get_cached_detail_header_summary,
    publish_opened_workspaces_cache,
)
from ._agent_display_state import AgentHintRender, HeaderHintState
from ._agent_xprompt_highlighting import known_xprompt_skill_names
from ._file_path_hints import (
    annotated_char_scope,
    clear_file_hint_resolution_caches,
    resolve_agent_workspace_dir,
)
from ._helpers import append_section_heading, format_output
from ._hint_caps import (
    HintContentBudget,
    append_bounded_text_with_file_hints,
)
from ._member_roster import member_jump_map_publisher_for

_AGENT_HINT_RENDER_CACHE_MAX_ENTRIES = 16


@dataclass(frozen=True)
class _AgentHintRenderCacheKey:
    """Inputs whose changes can alter an annotated hint document."""

    agent_identity: tuple[object, ...]
    agent_state_digest: str
    source_digest: str
    summary_key: tuple[object, ...] | None
    fold_level: object
    fold_overrides: tuple[tuple[str, str], ...]
    context_digest: str
    cap_parameters: tuple[int, int]
    attempt_view_mode: str
    attempt_pinned_number: int | None


@dataclass(frozen=True)
class _AgentHintRenderCacheEntry:
    """A memoized hint result and its width-cached Rich document."""

    result: AgentHintRender
    renderable: CachedRenderable


def _agent_hint_render_cache(
    widget: object,
) -> OrderedDict[_AgentHintRenderCacheKey, _AgentHintRenderCacheEntry]:
    cache = getattr(widget, "_agent_hint_render_cache", None)
    if cache is None:
        cache = OrderedDict()
        cast(Any, widget)._agent_hint_render_cache = cache
    return cast(
        OrderedDict[_AgentHintRenderCacheKey, _AgentHintRenderCacheEntry],
        cache,
    )


def clear_agent_hint_render_cache(widget: object) -> None:
    """Clear the panel-local annotated-document cache, when initialized."""
    cache = getattr(widget, "_agent_hint_render_cache", None)
    if cache is not None:
        cache.clear()
    cast(Any, widget)._rendered_agent_hint_cache_key = None


def _digest_parts(*parts: object) -> str:
    digest = blake2b(digest_size=16)
    for part in parts:
        encoded = repr(part).encode("utf-8", errors="replace")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()


def _source_digest(agent: Agent) -> str:
    """Digest every body source that can contribute hints for ``agent``."""
    digest = blake2b(digest_size=16)
    seen: set[int] = set()

    def add(label: str, value: object) -> None:
        encoded_label = label.encode("utf-8")
        encoded_value = repr(value).encode("utf-8", errors="replace")
        digest.update(len(encoded_label).to_bytes(4, "big"))
        digest.update(encoded_label)
        digest.update(len(encoded_value).to_bytes(8, "big"))
        digest.update(encoded_value)

    def visit(candidate: Agent) -> None:
        candidate_id = id(candidate)
        if candidate_id in seen:
            return
        seen.add(candidate_id)
        add("identity", candidate.identity)
        add("error_traceback", candidate.error_traceback)
        add("raw_xprompt", candidate.get_raw_xprompt_content())
        add("prompt", get_prompt_content(candidate))
        add("reply_chunks", candidate.get_timestamped_reply_chunks())
        add("live_reply", candidate.get_live_reply_content())
        add("response", candidate.get_response_content())
        add("chat_response", candidate.get_chat_response_content())
        for followup in candidate.followup_agents:
            visit(followup)

    visit(agent)
    return digest.hexdigest()


def _fold_overrides_key(
    overrides: Mapping[str, Any],
) -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted((repr(section), repr(level)) for section, level in overrides.items())
    )


def _hint_context_digest(
    widget: object,
    agent: Agent,
    raw_xprompt: str | None,
) -> str:
    """Digest warm in-memory header and styling context outside ``agent``."""
    try:
        app = widget.app  # type: ignore[attr-defined]
    except Exception:
        app = None
    wait_status_maps = (
        agent_wait_status_maps_for_app(app)
        if wait_display_agent(agent).waiting_for
        else None
    )
    lane_owner = agent_owns_lane(agent)
    projection_resolver = getattr(app, "lane_neighbor_projection_for", None)
    lane_neighbors = (
        projection_resolver(agent)
        if lane_owner and callable(projection_resolver)
        else None
    )
    known_skills = (
        known_xprompt_skill_names(widget, agent, raw_xprompt)
        if raw_xprompt
        else frozenset()
    )
    return _digest_parts(
        getattr(app, "_unread_completed_agent_ids", set()),
        getattr(app, "_marked_agents", set()),
        runner_capacity_for_app(app),
        wait_status_maps,
        lane_neighbors,
        slow_tool_call_threshold_ms_from_widget(widget),
        project_display_name_map_signature(),
        known_skills,
    )


def _agent_hint_render_cache_key(
    widget: object,
    agent: Agent,
) -> _AgentHintRenderCacheKey:
    """Build the conservative key for the current annotated document."""
    fold_level, fold_overrides = panel_fold_state_from_widget(widget)
    if agent.is_clan_container:
        snapshot = get_cached_clan_section_snapshot(widget, agent)
        member_states = tuple(
            (member.identity, member.display_status)
            for member in clan_section_member_rows(agent)
        )
        agent_state_digest = _digest_parts(
            member_states,
            agent.agent_clan,
            agent.agent_clan_generation,
            snapshot.revision if snapshot is not None else 0,
        )
        source_digest = _digest_parts(agent.clan_summary)
        summary_key = None
        raw_xprompt = None
    else:
        agent_state_digest = _digest_parts(agent)
        source_digest = _source_digest(agent)
        summary_key = detail_header_summary_cache_key(widget, agent)
        raw_xprompt = agent.get_raw_xprompt_content()
    return _AgentHintRenderCacheKey(
        agent_identity=cast(tuple[object, ...], agent.identity),
        agent_state_digest=agent_state_digest,
        source_digest=source_digest,
        summary_key=summary_key,
        fold_level=fold_level,
        fold_overrides=_fold_overrides_key(fold_overrides),
        context_digest=_hint_context_digest(widget, agent, raw_xprompt),
        cap_parameters=(
            HintContentBudget().remaining_bytes,
            HintContentBudget().remaining_lines,
        ),
        attempt_view_mode=str(getattr(widget, "attempt_view_mode", "merged")),
        attempt_pinned_number=getattr(widget, "attempt_pinned_number", None),
    )


def _plain_renderable_content(renderable: object) -> str:
    """Flatten the hint document for introspection without rendering it."""
    if isinstance(renderable, Text):
        return renderable.plain
    if isinstance(renderable, Syntax):
        return str(renderable.code)
    if isinstance(renderable, Group):
        return "\n".join(
            _plain_renderable_content(child) for child in renderable.renderables
        )
    plain = getattr(renderable, "plain", None)
    if isinstance(plain, str):
        return plain
    return str(renderable)


def _render_reply_with_hints(
    agent: Agent,
    target: AgentHeader,
    hint_counter: int,
    hint_mappings: dict[int, str],
    workspace_dir: str | None,
    humanize_text: Callable[[str], str],
) -> int:
    """Render one agent's reply content with file hints into a Text."""
    chunks = agent.get_timestamped_reply_chunks()
    if chunks:
        for ts, chunk_text in chunks:
            target.append_text(render_timestamp_divider(ts))
            content = chunk_text.strip()
            if content:
                content = humanize_text(content)
                hint_counter = append_bounded_text_with_file_hints(
                    target,
                    content + "\n",
                    hint_counter,
                    hint_mappings,
                    workspace_dir,
                )
                target.append("\n")
        return hint_counter
    live_reply = agent.get_live_reply_content()
    if live_reply:
        live_reply = humanize_text(live_reply)
        return append_bounded_text_with_file_hints(
            target,
            live_reply + "\n",
            hint_counter,
            hint_mappings,
            workspace_dir,
        )
    response_content = agent.get_response_content()
    if response_content:
        response_content = humanize_text(response_content)
        return append_bounded_text_with_file_hints(
            target,
            response_content + "\n",
            hint_counter,
            hint_mappings,
            workspace_dir,
        )
    return hint_counter


class AgentHintsDisplayMixin:
    """Mixin providing hint-annotated agent display for AgentPromptPanel."""

    _agent_hint_renderable: CachedRenderable | None = None
    _rendered_agent_hint_cache_key: _AgentHintRenderCacheKey | None = None

    def hint_document_is_current(self, agent: Agent) -> bool:
        """Return whether the visible annotated document matches ``agent``."""
        if not getattr(self, "_agent_hint_mode_rendered", False):
            return False
        rendered_key = getattr(self, "_rendered_agent_hint_cache_key", None)
        return (
            rendered_key is not None
            and rendered_key == _agent_hint_render_cache_key(self, agent)
        )

    def _prepare_cached_hint_renderable(
        self,
        renderable: RenderableType,
    ) -> CachedRenderable:
        """Wrap and retain a newly built hint document's segment cache."""
        cached = CachedRenderable(
            renderable,
            _plain_renderable_content(renderable),
        )
        self._agent_hint_renderable = cached
        return cached

    def update_display_with_hints(self, agent: Agent) -> AgentHintRender:
        """Render the agent display with hints and trace the keystroke path.

        The span carries the counters a view-hints capture needs to apportion
        cost: how much text was annotated, how many hints came out, and whether
        the render ran against a warm or cold detail-header summary.
        """
        prepare_sections = getattr(self, "prepare_section_document_for_agent", None)
        if callable(prepare_sections):
            prepare_sections(agent)
        if agent.is_clan_container:
            prepare_clan_section_snapshot(self, agent)
        self._reset_markdown_render_cache_for_agent(agent)  # type: ignore[attr-defined]
        cache_key = _agent_hint_render_cache_key(self, agent)
        cache = _agent_hint_render_cache(self)
        with (
            tui_trace(
                "widget.prompt_panel.update_display_with_hints",
                family_container=agent.is_family_container_row,
            ) as extra,
            annotated_char_scope() as annotated_chars,
        ):
            cached = cache.get(cache_key)
            if cached is not None:
                cache.move_to_end(cache_key)
                self._agent_hint_mode_rendered = True  # type: ignore[attr-defined]
                self._agent_hint_renderable = cached.renderable
                cancel_slow_tick = getattr(self, "_cancel_slow_tool_render_tick", None)
                if callable(cancel_slow_tick):
                    cancel_slow_tick()
                summary = get_cached_detail_header_summary(self, agent)
                if summary is not None:
                    publish_opened_workspaces_cache(
                        self,
                        agent,
                        summary.opened_workspaces,
                    )
                self.update(cached.renderable)  # type: ignore[attr-defined]
                if cached.result.header_enrichment_pending:
                    if agent.is_clan_container:
                        self._start_clan_section_enrichment_from_context(agent)  # type: ignore[attr-defined]
                    else:
                        self._start_agent_detail_header_enrichment_from_context(agent)  # type: ignore[attr-defined]
                extra["cache"] = "hit"
                render = cached.result
            else:
                clear_file_hint_resolution_caches()
                self._agent_hint_renderable = None
                render = self._update_display_with_hints_impl(agent)
                renderable = getattr(self, "_agent_hint_renderable", None)
                if isinstance(renderable, CachedRenderable):
                    cache[cache_key] = _AgentHintRenderCacheEntry(
                        result=render,
                        renderable=renderable,
                    )
                    cache.move_to_end(cache_key)
                    while len(cache) > _AGENT_HINT_RENDER_CACHE_MAX_ENTRIES:
                        cache.popitem(last=False)
                extra["cache"] = "miss"
            extra["hints"] = len(render.file_hints)
            extra["commit_views"] = len(render.commit_views)
            extra["tool_call_reports"] = len(render.tool_call_reports)
            extra["header_summary"] = (
                "cold" if render.header_enrichment_pending else "warm"
            )
            extra["annotated_chars"] = annotated_chars[0]
            self._rendered_agent_hint_cache_key = cache_key
            return render

    def _update_display_with_hints_impl(self, agent: Agent) -> AgentHintRender:
        """Render agent display with ``[N]`` file path hints.

        Same visual structure as :meth:`update_display` but scans xprompt,
        prompt, and chat sections for file paths and inserts numbered hint
        markers.  Syntax highlighting is temporarily replaced with plain
        text so that hint markers can be inserted inline.

        Args:
            agent: The Agent to display.

        Returns:
            File hint mappings and deferred tool-call report specs.
        """
        # Workflow top-level or bash/python/parallel: no hint support
        if (
            agent.agent_type == AgentType.WORKFLOW
            and not agent.is_workflow_child
            and not agent.appears_as_agent
        ):
            self.update_display(agent)  # type: ignore[attr-defined]
            return AgentHintRender(file_hints={}, tool_call_reports={})

        if agent.is_workflow_child and agent.step_type in (
            "bash",
            "python",
            "parallel",
        ):
            self.update_display(agent)  # type: ignore[attr-defined]
            return AgentHintRender(file_hints={}, tool_call_reports={})

        self._agent_hint_mode_rendered = True  # type: ignore[attr-defined]
        cancel_slow_tick = getattr(self, "_cancel_slow_tool_render_tick", None)
        if callable(cancel_slow_tick):
            cancel_slow_tick()
        if agent.is_clan_container:
            return self._update_clan_display_with_hints(agent)
        humanize_text = self._humanize_display_text  # type: ignore[attr-defined]
        workspace_dir = resolve_agent_workspace_dir(
            agent.effective_workspace_num,
            agent.project_file,
            agent.workspace_dir,
        )
        hint_counter = 1
        hint_mappings: dict[int, str] = {}
        tool_call_reports: dict[str, SlowToolCallReportSpec] = {}

        # Build header (same structured fields as normal display)
        header_hint_state = HeaderHintState(
            hint_counter=hint_counter,
            hint_mappings=hint_mappings,
            workspace_dir=workspace_dir,
            tool_call_reports=tool_call_reports,
        )
        summary = get_cached_detail_header_summary(self, agent)
        if summary is not None:
            publish_opened_workspaces_cache(self, agent, summary.opened_workspaces)
        wait_status_maps = (
            agent_wait_status_maps_for_app(getattr(self, "app", None))
            if wait_display_agent(agent).waiting_for
            else None
        )
        agent_status_buckets = (
            wait_status_maps.buckets if wait_status_maps is not None else None
        )
        clan_wait_member_statuses = (
            wait_status_maps.clan_member_statuses
            if wait_status_maps is not None
            else None
        )
        tribe_wait_bindings = (
            wait_status_maps.tribe_bindings if wait_status_maps is not None else None
        )
        lane_fold_level, lane_fold_overrides = panel_fold_state_from_widget(self)
        try:
            app = self.app  # type: ignore[attr-defined]
        except Exception:
            app = None
        lane_owner = agent_owns_lane(agent)
        lane_summary_enabled = agent.is_family_container_row or lane_owner
        projection_resolver = getattr(app, "lane_neighbor_projection_for", None)
        lane_neighbors = (
            projection_resolver(agent)
            if lane_owner and callable(projection_resolver)
            else None
        )
        header_text, error_tb_syntax = build_header_text(
            agent,
            hint_state=header_hint_state,
            summary=summary,
            agent_status_buckets=agent_status_buckets,
            clan_wait_member_statuses=clan_wait_member_statuses,
            tribe_wait_bindings=tribe_wait_bindings,
            unread_agent_ids=getattr(app, "_unread_completed_agent_ids", set()),
            marked_agent_ids=getattr(app, "_marked_agents", set()),
            slow_tool_call_threshold_ms=slow_tool_call_threshold_ms_from_widget(self),
            lane_fold_level=lane_fold_level,
            lane_section_fold_overrides=lane_fold_overrides,
            lane_neighbors=lane_neighbors,
            runner_capacity=runner_capacity_for_app(app),
            member_jump_map_publisher=(
                member_jump_map_publisher_for(app) if lane_summary_enabled else None
            ),
        )
        hint_counter = header_hint_state.hint_counter

        if agent.is_family_container_row:
            self._update_family_display(  # type: ignore[attr-defined]
                agent,
                header_text,
                error_tb_syntax,
                panel_level=lane_fold_level,
                section_fold_overrides=lane_fold_overrides,
                hint_state=header_hint_state,
            )
            if summary is None:
                self._start_agent_detail_header_enrichment_from_context(agent)  # type: ignore[attr-defined]
            return AgentHintRender(
                file_hints=hint_mappings,
                tool_call_reports=tool_call_reports,
                commit_views=header_hint_state.commit_views,
                header_enrichment_pending=summary is None,
            )

        # Error traceback as text with hints (not Syntax)
        if agent.error_traceback:
            hint_counter = append_bounded_text_with_file_hints(
                header_text,
                agent.error_traceback + "\n",
                hint_counter,
                hint_mappings,
                workspace_dir,
            )

        # AGENT XPROMPT section (with file path hints)
        raw_xprompt = agent.get_raw_xprompt_content()
        if raw_xprompt:
            source_xprompt = raw_xprompt
            raw_xprompt = humanize_text(source_xprompt)
            append_section_heading(header_text, "AGENT XPROMPT")
            xprompt_start = len(header_text.plain)
            hint_counter = append_bounded_text_with_file_hints(
                header_text,
                raw_xprompt + "\n",
                hint_counter,
                hint_mappings,
                workspace_dir,
            )
            xprompt_source = header_text.plain[xprompt_start:]
            hint_spans = [
                span for span in header_text.spans if span.end > xprompt_start
            ]
            try:
                apply_xprompt_overlays(
                    header_text,
                    xprompt_source,
                    region_start=xprompt_start,
                    known_skills=known_xprompt_skill_names(
                        self,
                        agent,
                        source_xprompt,
                    ),
                )
                for span in hint_spans:
                    header_text.stylize(span.style, span.start, span.end)
            except Exception:
                pass
            header_text.append("\n")
            header_text.append("\u2500" * 50 + "\n", style="dim")
            header_text.append("\n")

        # AGENT PROMPT section (with file path hints, Text instead of Syntax)
        append_section_heading(header_text, "AGENT PROMPT")

        prompt_content = get_prompt_content(agent)
        if prompt_content:
            prompt_content = humanize_text(prompt_content)
            hint_counter = append_bounded_text_with_file_hints(
                header_text,
                prompt_content + "\n",
                hint_counter,
                hint_mappings,
                workspace_dir,
            )

            # Consolidated AGENT REPLY for agents with follow-ups (with hints)
            if agent.followup_agents:
                header_text.append("\n")
                header_text.append("\u2500" * 50 + "\n", style="dim")
                header_text.append("\n")
                append_section_heading(header_text, "AGENT REPLY")

                # Main agent's phase
                header_text.append_text(
                    render_phase_divider(
                        get_phase_label(agent),
                        agent.run_start_time or agent.start_time,
                    )
                )
                hint_counter = _render_reply_with_hints(
                    agent,
                    header_text,
                    hint_counter,
                    hint_mappings,
                    workspace_dir,
                    humanize_text,
                )

                # Follow-up phases
                for followup in agent.followup_agents:
                    header_text.append_text(
                        render_phase_divider(
                            get_phase_label(followup),
                            followup.run_start_time or followup.start_time,
                        )
                    )
                    hint_counter = _render_reply_with_hints(
                        followup,
                        header_text,
                        hint_counter,
                        hint_mappings,
                        workspace_dir,
                        humanize_text,
                    )
            # AGENT CHAT section for completed agents (with hints)
            elif agent.status in ("DONE", "FAILED"):
                response_content = agent.get_response_content()
                # Only use step_output when it has displayable content (_raw/_data),
                # not when it only contains meta_* metadata fields.
                if (
                    response_content is None
                    and agent.is_workflow_child
                    and isinstance(agent.step_output, dict)
                    and ("_raw" in agent.step_output or "_data" in agent.step_output)
                ):
                    response_content = format_output(agent.step_output)

                header_text.append("\n")
                header_text.append("\u2500" * 50 + "\n", style="dim")
                header_text.append("\n")
                append_section_heading(header_text, "AGENT CHAT")

                chunks = agent.get_timestamped_reply_chunks()
                if chunks:
                    for ts, chunk_text in chunks:
                        header_text.append_text(render_timestamp_divider(ts))
                        content = chunk_text.strip()
                        if content:
                            content = humanize_text(content)
                            hint_counter = append_bounded_text_with_file_hints(
                                header_text,
                                content + "\n",
                                hint_counter,
                                hint_mappings,
                                workspace_dir,
                            )
                            header_text.append("\n")
                elif response_content:
                    response_content = humanize_text(response_content)
                    hint_counter = append_bounded_text_with_file_hints(
                        header_text,
                        response_content + "\n",
                        hint_counter,
                        hint_mappings,
                        workspace_dir,
                    )
                else:
                    header_text.append("No response file found.\n", style="dim italic")
            else:
                # AGENT REPLY section for running agents (with hints)
                header_text.append("\n")
                header_text.append("\u2500" * 50 + "\n", style="dim")
                header_text.append("\n")
                append_section_heading(header_text, "AGENT REPLY")

                live_reply = agent.get_live_reply_content()
                chunks = agent.get_timestamped_reply_chunks()
                if chunks:
                    for ts, chunk_text in chunks:
                        header_text.append_text(render_timestamp_divider(ts))
                        content = chunk_text.strip()
                        if content:
                            content = humanize_text(content)
                            hint_counter = append_bounded_text_with_file_hints(
                                header_text,
                                content + "\n",
                                hint_counter,
                                hint_mappings,
                                workspace_dir,
                            )
                            header_text.append("\n")
                elif live_reply:
                    live_reply = humanize_text(live_reply)
                    hint_counter = append_bounded_text_with_file_hints(
                        header_text,
                        live_reply + "\n",
                        hint_counter,
                        hint_mappings,
                        workspace_dir,
                    )
                else:
                    header_text.append(
                        "Waiting for agent response...\n",
                        style="dim italic",
                    )
        else:
            header_text.append("No prompt file found.\n", style="dim italic")

        self.update(self._prepare_cached_hint_renderable(header_text))  # type: ignore[attr-defined]
        if summary is None:
            self._start_agent_detail_header_enrichment_from_context(agent)  # type: ignore[attr-defined]
        return AgentHintRender(
            file_hints=hint_mappings,
            tool_call_reports=tool_call_reports,
            commit_views=header_hint_state.commit_views,
            header_enrichment_pending=summary is None,
        )

    def _update_clan_display_with_hints(self, agent: Agent) -> AgentHintRender:
        """Render one fold-aware clan document with summary path hints."""
        self._cancel_tribe_section_worker_for_agent_selection()  # type: ignore[attr-defined]
        self._cancel_clan_section_worker_for_selection_change(agent)  # type: ignore[attr-defined]
        snapshot = prepare_clan_section_snapshot(self, agent)
        fold_level, fold_overrides = panel_fold_state_from_widget(self)
        required_sections = clan_disk_sections_for_fold_state(
            fold_level,
            fold_overrides,
        )
        self.set_clan_disk_sections_required(required_sections)  # type: ignore[attr-defined]
        try:
            app = self.app  # type: ignore[attr-defined]
        except Exception:
            app = None

        hint_mappings: dict[int, str] = {}
        tool_call_reports: dict[str, SlowToolCallReportSpec] = {}
        hint_state = HeaderHintState(
            hint_counter=1,
            hint_mappings=hint_mappings,
            workspace_dir=None,
            tool_call_reports=tool_call_reports,
        )
        clan_text, _error_tb_syntax = build_header_text(
            agent,
            hint_state=hint_state,
            unread_agent_ids=getattr(app, "_unread_completed_agent_ids", set()),
            clan_snapshot=snapshot,
            clan_fold_level=fold_level,
            clan_section_fold_overrides=fold_overrides,
            member_jump_map_publisher=member_jump_map_publisher_for(app),
        )
        self.update(self._prepare_cached_hint_renderable(clan_text))  # type: ignore[attr-defined]

        self._cancel_agent_bead_display_worker_for_selection_change(agent)  # type: ignore[attr-defined]
        self._cancel_agent_linked_delta_worker_for_selection_change(agent)  # type: ignore[attr-defined]
        self._cancel_agent_detail_header_worker_for_selection_change(agent)  # type: ignore[attr-defined]
        self._start_clan_section_enrichment_from_context(agent)  # type: ignore[attr-defined]

        snapshot = get_cached_clan_section_snapshot(self, agent) or snapshot
        loaded_sections = (
            snapshot.disk.loaded_sections if snapshot.disk is not None else frozenset()
        )
        enrichment_pending = bool(snapshot.loading_sections) or not (
            required_sections.issubset(loaded_sections)
        )
        return AgentHintRender(
            file_hints=hint_mappings,
            tool_call_reports=tool_call_reports,
            commit_views=hint_state.commit_views,
            header_enrichment_pending=enrichment_pending,
        )
