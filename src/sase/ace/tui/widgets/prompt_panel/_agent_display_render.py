"""Main agent render paths for the agent prompt panel."""

from __future__ import annotations

from typing import Any

from rich.console import Group
from rich.text import Text

from sase.project_display_names import (
    humanize_vcs_refs_in_text,
    project_display_name_map_signature,
)

from ...agent_completion import agent_wait_status_maps_for_app
from ...models.agent import Agent, AgentType, wait_display_agent
from ...models.agent_hoods import agent_owns_lane
from ...tools.slow import slow_tool_call_threshold_ms_from_widget
from ...util.lazy_syntax import LazySyntaxRenderCache, lazy_renderable
from ...util.xprompt_syntax import highlight_prompt_text
from ._agent_display_attempts import (
    AgentAttemptDisplayMixin,
    render_merged_attempt_history,
    should_render_merged,
)
from ._agent_display_content import (
    get_phase_label,
    get_prompt_content,
    render_agent_reply_content,
    render_phase_divider,
    render_timestamp_divider,
)
from ._agent_clan_aggregation import get_cached_clan_section_snapshot
from ._agent_display_clan import (
    clan_disk_sections_for_fold_state,
    panel_fold_state_from_widget,
)
from ._agent_display_family_render import AgentFamilyDisplayMixin
from ._agent_display_header import build_header_text
from ._agent_display_header_summary import (
    clear_detail_header_summary_cache,
    get_cached_detail_header_summary,
    publish_opened_workspaces_cache,
)
from ._agent_display_step_render import AgentStepDisplayMixin
from ._agent_xprompt_highlighting import known_xprompt_skill_names
from ._helpers import append_section_heading, format_output
from ._member_roster import member_jump_map_publisher_for

_HUMANIZED_TEXT_CACHE_LIMIT = 24
_HumanizedTextCacheKey = tuple[int, int, tuple[tuple[str, str], ...]]
_XPROMPT_HIGHLIGHT_CACHE_LIMIT = 24
_XPromptHighlightCacheKey = tuple[int, int, frozenset[str]]


class AgentDisplayRenderMixin(
    AgentAttemptDisplayMixin,
    AgentFamilyDisplayMixin,
    AgentStepDisplayMixin,
):
    """Core agent render paths for AgentPromptPanel."""

    # Reactive-ish field set by AgentDetail before calling update_display.
    attempt_view_mode: str = "merged"
    # When non-None, pin the prompt panel to the matching attempt_history
    # record. Exclusive with the merged / current-only toggle.
    attempt_pinned_number: int | None = None

    def _markdown_render_cache(self) -> LazySyntaxRenderCache:
        cache = getattr(self, "_agent_markdown_render_cache", None)
        if cache is None:
            cache = LazySyntaxRenderCache(max_entries=24)
            self._agent_markdown_render_cache = cache
        return cache

    def _reset_markdown_render_cache_for_agent(self, agent: Agent) -> None:
        identity = agent.identity
        previous_identity = getattr(self, "_agent_markdown_render_cache_identity", None)
        if previous_identity != identity:
            cache = getattr(self, "_agent_markdown_render_cache", None)
            if cache is not None:
                cache.clear()
            humanize_cache = getattr(self, "_agent_humanized_text_cache", None)
            if humanize_cache is not None:
                humanize_cache.clear()
            xprompt_cache = getattr(self, "_agent_xprompt_highlight_cache", None)
            if xprompt_cache is not None:
                xprompt_cache.clear()
            self._agent_markdown_render_cache_identity = identity

    def _display_raw_xprompt(self, agent: Agent, raw_xprompt: str) -> str:
        del agent
        return self._humanize_display_text(raw_xprompt)

    def _humanized_text_cache(self) -> dict[_HumanizedTextCacheKey, str]:
        cache = getattr(self, "_agent_humanized_text_cache", None)
        if cache is None:
            cache = {}
            self._agent_humanized_text_cache = cache
        return cache

    def _xprompt_highlight_cache(self) -> dict[_XPromptHighlightCacheKey, Text]:
        cache = getattr(self, "_agent_xprompt_highlight_cache", None)
        if cache is None:
            cache = {}
            self._agent_xprompt_highlight_cache = cache
        return cache

    def _render_xprompt(
        self,
        agent: Agent,
        raw_xprompt: str,
        humanized_xprompt: str,
    ) -> Text:
        known_skills = known_xprompt_skill_names(self, agent, raw_xprompt)
        key = (
            len(humanized_xprompt),
            hash(humanized_xprompt),
            known_skills,
        )
        cache = self._xprompt_highlight_cache()
        cached = cache.pop(key, None)
        if cached is not None:
            cache[key] = cached
            return cached

        highlighted = highlight_prompt_text(
            humanized_xprompt,
            known_skills=known_skills,
        )
        cache[key] = highlighted
        if len(cache) > _XPROMPT_HIGHLIGHT_CACHE_LIMIT:
            cache.pop(next(iter(cache)))
        return highlighted

    def _humanize_display_text(self, content: str) -> str:
        if "#" not in content:
            return content
        signature = project_display_name_map_signature()
        key = (len(content), hash(content), signature)
        cache = self._humanized_text_cache()
        cached = cache.get(key)
        if cached is not None:
            return cached
        humanized = humanize_vcs_refs_in_text(content)
        cache[key] = humanized
        if len(cache) > _HUMANIZED_TEXT_CACHE_LIMIT:
            cache.pop(next(iter(cache)))
        return humanized

    def _render_markdown(self, content: str) -> object:
        content = self._humanize_display_text(content)
        return lazy_renderable(
            content,
            "markdown",
            render_cache=self._markdown_render_cache(),
        )

    def _update_display_impl(self, agent: Agent) -> None:
        # Clan rows are synthetic containers. Their complete detail document
        # is derived from already-loaded members and must never probe agent
        # artifacts or append ordinary prompt/reply sections.
        if agent.is_clan_container:
            try:
                app = self.app  # type: ignore[attr-defined]
            except Exception:
                app = None
            fold_level, fold_overrides = panel_fold_state_from_widget(self)
            set_required = getattr(
                self,
                "set_clan_disk_sections_required",
                None,
            )
            if app is not None and callable(set_required):
                set_required(
                    clan_disk_sections_for_fold_state(
                        fold_level,
                        fold_overrides,
                    )
                )
            header_text, _error_tb_syntax = build_header_text(
                agent,
                unread_agent_ids=getattr(app, "_unread_completed_agent_ids", set()),
                clan_snapshot=get_cached_clan_section_snapshot(self, agent),
                clan_fold_level=fold_level,
                clan_section_fold_overrides=fold_overrides,
                member_jump_map_publisher=member_jump_map_publisher_for(app),
            )
            self.update(header_text)  # type: ignore[attr-defined]
            return

        # Attempt-pinned view: render the selected prior attempt's full error
        # + prompt + captured reply; skip all other rendering paths.
        if self.attempt_pinned_number is not None:
            self._render_attempt_pinned(agent, self.attempt_pinned_number)
            return

        # Check if this is a top-level workflow agent that should display as workflow
        # Workflows with appears_as_agent=True should show as regular agents
        # Workflow children (steps) should show the normal agent view with prompt/chat
        if (
            agent.agent_type == AgentType.WORKFLOW
            and not agent.is_workflow_child
            and not agent.appears_as_agent
        ):
            self._update_workflow_display(agent)  # type: ignore[attr-defined]
            return

        summary = get_cached_detail_header_summary(self, agent)
        if summary is not None:
            publish_opened_workspaces_cache(self, agent, summary.opened_workspaces)
        wait_status_maps = (
            agent_wait_status_maps_for_app(getattr(self, "app", None))
            if wait_display_agent(agent).waiting_for
            else None
        )
        agent_status_buckets, clan_wait_member_statuses = wait_status_maps or (
            None,
            None,
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
            summary=summary,
            agent_status_buckets=agent_status_buckets,
            clan_wait_member_statuses=clan_wait_member_statuses,
            unread_agent_ids=getattr(app, "_unread_completed_agent_ids", set()),
            marked_agent_ids=getattr(app, "_marked_agents", set()),
            slow_tool_call_threshold_ms=slow_tool_call_threshold_ms_from_widget(self),
            lane_fold_level=lane_fold_level if lane_summary_enabled else None,
            lane_section_fold_overrides=(
                lane_fold_overrides if lane_summary_enabled else None
            ),
            lane_neighbors=lane_neighbors,
            member_jump_map_publisher=(
                member_jump_map_publisher_for(app) if lane_summary_enabled else None
            ),
        )

        if agent.is_family_container_row:
            self._update_family_display(
                agent,
                header_text,
                error_tb_syntax,
                panel_level=lane_fold_level,
                section_fold_overrides=lane_fold_overrides,
            )
            return

        # Check if this is a bash/python workflow step - display differently
        if agent.is_workflow_child and agent.step_type in ("bash", "python"):
            self._update_bash_python_display(agent, header_text, error_tb_syntax)
            return

        # Check if this is a parallel workflow step - show output only, no prompt
        if agent.is_workflow_child and agent.step_type == "parallel":
            self._update_parallel_display(agent, header_text, error_tb_syntax)
            return

        # AGENT XPROMPT section
        raw_xprompt = agent.get_raw_xprompt_content()
        if raw_xprompt:
            humanized_xprompt = self._display_raw_xprompt(agent, raw_xprompt)
            append_section_heading(header_text, "AGENT XPROMPT")
            header_text.append_text(
                self._render_xprompt(agent, raw_xprompt, humanized_xprompt)
            )
            header_text.append("\n")
            header_text.append("\n")
            header_text.append("\u2500" * 50 + "\n", style="dim")
            header_text.append("\n")

        # AGENT PROMPT section
        append_section_heading(header_text, "AGENT PROMPT")

        # Get and display prompt content
        prompt_content = get_prompt_content(agent)
        if prompt_content:
            prompt_syntax = self._render_markdown(prompt_content)

            # For agents with follow-ups, show consolidated reply
            if agent.followup_agents:
                renderables: list[Any] = [header_text]
                if error_tb_syntax:
                    renderables.append(error_tb_syntax)
                renderables.append(prompt_syntax)

                reply_header = Text()
                reply_header.append("\n")
                reply_header.append("\u2500" * 50 + "\n", style="dim")
                reply_header.append("\n")
                append_section_heading(reply_header, "AGENT REPLY")
                renderables.append(reply_header)

                # Main agent's phase
                renderables.append(
                    render_phase_divider(
                        get_phase_label(agent),
                        agent.run_start_time or agent.start_time,
                    )
                )
                renderables.extend(
                    render_agent_reply_content(agent, self._render_markdown)
                )

                # Follow-up phases
                for followup in agent.followup_agents:
                    renderables.append(
                        render_phase_divider(
                            get_phase_label(followup),
                            followup.run_start_time or followup.start_time,
                        )
                    )
                    renderables.extend(
                        render_agent_reply_content(followup, self._render_markdown)
                    )

                self.update(Group(*renderables))  # type: ignore[attr-defined]
            # For completed or failed agents/steps, also show the response
            elif agent.status in ("DONE", "FAILED"):
                reply_header = Text()
                reply_header.append("\n")
                reply_header.append("\u2500" * 50 + "\n", style="dim")
                reply_header.append("\n")
                append_section_heading(reply_header, "AGENT CHAT")

                response_content = agent.get_response_content()

                # Fallback: for workflow step agents, try step_output if no response file
                # Only use step_output when it has displayable content (_raw/_data),
                # not when it only contains meta_* metadata fields.
                if (
                    response_content is None
                    and agent.is_workflow_child
                    and isinstance(agent.step_output, dict)
                    and ("_raw" in agent.step_output or "_data" in agent.step_output)
                ):
                    response_content = format_output(agent.step_output)

                renderables = [header_text]
                if error_tb_syntax:
                    renderables.append(error_tb_syntax)
                renderables.append(prompt_syntax)

                chunks = agent.get_timestamped_reply_chunks()
                merge_history = should_render_merged(agent, self.attempt_view_mode)
                if chunks:
                    renderables.append(reply_header)
                    if merge_history:
                        renderables.extend(
                            render_merged_attempt_history(
                                agent,
                                self._render_markdown,
                            )
                        )
                    for ts, chunk_text in chunks:
                        renderables.append(render_timestamp_divider(ts))
                        content = chunk_text.strip()
                        if content:
                            renderables.append(self._render_markdown(content))
                elif response_content:
                    response_syntax = self._render_markdown(response_content)
                    renderables.append(reply_header)
                    if merge_history:
                        renderables.extend(
                            render_merged_attempt_history(
                                agent,
                                self._render_markdown,
                            )
                        )
                    renderables.append(response_syntax)
                else:
                    reply_header.append("No response file found.\n", style="dim italic")
                    renderables.append(reply_header)

                self.update(Group(*renderables))  # type: ignore[attr-defined]
            else:
                renderables_other: list[Any] = [header_text]
                if error_tb_syntax:
                    renderables_other.append(error_tb_syntax)
                renderables_other.append(prompt_syntax)

                # AGENT REPLY section for running agents
                reply_header = Text()
                reply_header.append("\n")
                reply_header.append("\u2500" * 50 + "\n", style="dim")
                reply_header.append("\n")
                append_section_heading(reply_header, "AGENT REPLY")

                live_reply = agent.get_live_reply_content()
                chunks = agent.get_timestamped_reply_chunks()
                merge_history = should_render_merged(agent, self.attempt_view_mode)
                if chunks:
                    renderables_other.append(reply_header)
                    if merge_history:
                        renderables_other.extend(
                            render_merged_attempt_history(
                                agent,
                                self._render_markdown,
                            )
                        )
                    for ts, chunk_text in chunks:
                        renderables_other.append(render_timestamp_divider(ts))
                        content = chunk_text.strip()
                        if content:
                            renderables_other.append(self._render_markdown(content))
                elif live_reply:
                    reply_syntax = self._render_markdown(live_reply)
                    renderables_other.append(reply_header)
                    if merge_history:
                        renderables_other.extend(
                            render_merged_attempt_history(
                                agent,
                                self._render_markdown,
                            )
                        )
                    renderables_other.append(reply_syntax)
                else:
                    reply_header.append(
                        "Waiting for agent response...\n",
                        style="dim italic",
                    )
                    renderables_other.append(reply_header)

                self.update(Group(*renderables_other))  # type: ignore[attr-defined]
        else:
            header_text.append("No prompt file found.\n", style="dim italic")
            if error_tb_syntax:
                self.update(Group(header_text, error_tb_syntax))  # type: ignore[attr-defined]
            else:
                self.update(header_text)  # type: ignore[attr-defined]

    def show_empty(self) -> None:
        """Show empty state."""
        reset_sections = getattr(self, "reset_section_document", None)
        if callable(reset_sections):
            reset_sections()
        cancel_slow_tick = getattr(self, "_cancel_slow_tool_render_tick", None)
        if callable(cancel_slow_tick):
            cancel_slow_tick()
        current_worker = getattr(self, "_agent_bead_display_worker", None)
        if current_worker is not None and getattr(current_worker, "is_running", False):
            current_worker.cancel()
        current_worker = getattr(self, "_agent_detail_header_worker", None)
        if current_worker is not None and getattr(current_worker, "is_running", False):
            current_worker.cancel()
        current_worker = getattr(self, "_clan_section_worker", None)
        if current_worker is not None and getattr(current_worker, "is_running", False):
            current_worker.cancel()
        cancel_tribe_worker = getattr(
            self, "_cancel_tribe_section_worker_for_agent_selection", None
        )
        if callable(cancel_tribe_worker):
            cancel_tribe_worker()
        clear_detail_header_summary_cache(self)
        text = Text("No agent selected", style="dim italic")
        self.update(text)  # type: ignore[attr-defined]
