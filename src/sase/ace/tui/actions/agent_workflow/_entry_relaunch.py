"""Agent edit/relaunch entry points."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from sase.ace.patch.project_spec_path import preferred_project_spec_path
from sase.core.paths import sase_projects_dir
from sase.project_display_names import humanize_cl_name, humanize_vcs_refs_in_text

from ._entry_name_prompts import (
    prepare_kill_and_edit_prompt,
    prompt_facing_agent_name,
)
from ._types import PromptContext

if TYPE_CHECKING:
    from ...models import Agent
    from ...modals import SelectionItem

log = logging.getLogger(__name__)


def prepare_kill_edit_agent_prompt(
    agent: Agent,
    agents: Sequence[Agent],
) -> str | None:
    """Resolve and rewrite one exact agent relaunch prompt."""
    from ...models.artifact_files import get_restartable_prompt_content

    raw_prompt = get_restartable_prompt_content(agent, agents)
    if raw_prompt is None:
        return None

    family_name: str | None = None
    agent_family = getattr(agent, "agent_family", None)
    role_suffix = getattr(agent, "role_suffix", None)
    if (
        agent_family
        and not getattr(agent, "agent_family_parallel", False)
        and role_suffix
    ):
        family_name = (
            agent.presented_family_reference_name()
            if hasattr(agent, "presented_family_reference_name")
            else prompt_facing_agent_name(agent_family)
        )
    return prepare_kill_and_edit_prompt(
        raw_prompt,
        agent.agent_name,
        family_name=family_name,
        role_suffix=role_suffix,
        phase_bead_id=getattr(agent, "phase_bead_id", None),
    )


def schedule_relaunch_prompt_resolution(
    owner: object,
    resolver: Callable[[], Any],
    on_complete: Callable[[Any], None],
    *,
    worker_name: str,
    failure_message: str,
) -> None:
    """Resolve disk-backed relaunch prompts off the Textual event loop."""
    run_worker = getattr(owner, "run_worker", None)
    if not callable(run_worker):
        # Narrow mixin unit tests do not have Textual worker infrastructure.
        try:
            on_complete(resolver())
        except Exception:
            log.exception("Failed to prepare relaunch prompt")
            owner.notify(failure_message, severity="error")  # type: ignore[attr-defined]
        return

    async def prepare_prompt() -> None:
        try:
            result = await asyncio.to_thread(resolver)
        except Exception:
            log.exception("Failed to prepare relaunch prompt")
            owner.notify(failure_message, severity="error")  # type: ignore[attr-defined]
            return
        on_complete(result)

    worker_coro = prepare_prompt()
    try:
        run_worker(
            cast(Any, worker_coro),
            name=worker_name,
            group="agent-relaunch-prompt",
            exclusive=True,
        )
    except Exception:
        worker_coro.close()
        log.exception("Failed to schedule relaunch prompt preparation")
        owner.notify(failure_message, severity="error")  # type: ignore[attr-defined]


def resolve_agent_identity(owner: object, identity: object) -> Agent | None:
    """Re-resolve a captured row identity after asynchronous prompt loading."""
    agents = getattr(owner, "_agents_with_children", None)
    if agents is not None:
        return next(
            (
                agent
                for agent in agents
                if getattr(agent, "identity", agent) == identity
            ),
            None,
        )
    selected = owner._get_selected_agent()  # type: ignore[attr-defined]
    return (
        selected
        if selected is not None and getattr(selected, "identity", selected) == identity
        else None
    )


class EntryRelaunchMixin:
    """Mixin providing agent retry and edit/relaunch entry points."""

    _prompt_context: PromptContext | None
    _last_custom_agent_selection: SelectionItem | None

    if TYPE_CHECKING:

        def _rewrite_retry_prompt_name(
            self,
            raw_prompt: str,
            retry_name: str,
            *,
            current_agent_name: str | None = None,
        ) -> str: ...

    def _retry_edit_agent(self) -> None:
        """Show the selected agent's prompt in the prompt input bar for re-launch.

        Like :meth:`_kill_and_edit_agent` but without killing or dismissing
        the existing agent.  The user can press ``Ctrl+G`` to open their
        editor from the prompt input bar.
        """
        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
            return

        raw_prompt = agent.get_raw_xprompt_content()

        if raw_prompt is None:
            self.notify("No prompt found for this agent", severity="warning")  # type: ignore[attr-defined]
            return

        if agent.agent_name:
            try:
                from sase.agent.names import allocate_retry_name
                from sase.plan_chain import AGENT_FAMILY_SEPARATOR, agent_family_base

                retry_source_name = prompt_facing_agent_name(agent.agent_name)
                if AGENT_FAMILY_SEPARATOR in retry_source_name:
                    retry_source_name = (
                        agent_family_base(retry_source_name) or retry_source_name
                    )
                retry_name = prompt_facing_agent_name(
                    allocate_retry_name(retry_source_name)
                )
                raw_prompt = self._rewrite_retry_prompt_name(
                    raw_prompt,
                    retry_name,
                    current_agent_name=retry_source_name,
                )
            except Exception:
                self.notify(  # type: ignore[attr-defined]
                    "Could not allocate retry name; using original prompt",
                    severity="warning",
                )

        self._edit_and_relaunch_agent(
            raw_prompt, agent.project_file, agent.cl_name, agent.is_project_agent
        )

    def _kill_and_edit_agent(self) -> None:
        """Kill the selected agent, then show its prompt in the prompt input bar.

        Reads the agent's raw xprompt content, kills the agent (with
        confirmation if running), and shows the prompt in the prompt input
        bar for editing.  The user can press ``Ctrl+G`` to open their
        editor, or submit directly from the bar.
        """
        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
            return

        identity = getattr(agent, "identity", agent)
        agents_snapshot = tuple(
            getattr(self, "_agents_with_children", None)
            or getattr(self, "_agents", None)
            or (agent,)
        )

        def on_prompt_resolved(raw_prompt: str | None) -> None:
            current = resolve_agent_identity(self, identity)
            if current is None:
                self.notify(  # type: ignore[attr-defined]
                    "Selected agent is no longer available; nothing killed",
                    severity="warning",
                )
                return
            if raw_prompt is None:
                self.notify(  # type: ignore[attr-defined]
                    "No prompt found for this agent",
                    severity="warning",
                )
                return
            self._finish_kill_and_edit_agent(current, identity, raw_prompt)

        schedule_relaunch_prompt_resolution(
            self,
            lambda: prepare_kill_edit_agent_prompt(agent, agents_snapshot),
            on_prompt_resolved,
            worker_name="agent-relaunch-prompt",
            failure_message="Unable to prepare agent relaunch prompt",
        )

    def _finish_kill_and_edit_agent(
        self,
        agent: Agent,
        identity: object,
        raw_prompt: str,
    ) -> None:
        """Apply a resolved relaunch prompt to a still-current row."""
        # Capture agent info before killing (agent is removed from _agents on kill)
        agent_project_file = agent.project_file
        agent_cl_name = agent.cl_name
        agent_is_project_agent = agent.is_project_agent

        from ..agents._core import DISMISSABLE_STATUSES

        if agent.status in DISMISSABLE_STATUSES or agent.pid is None:
            # No confirmation needed - dismiss and show prompt bar
            self._dismiss_done_agent(agent)  # type: ignore[attr-defined]
            self._edit_and_relaunch_agent(
                raw_prompt, agent_project_file, agent_cl_name, agent_is_project_agent
            )
            return

        # Build description for confirmation dialog.
        from ..agents._confirmation_sase_agents import (
            confirmation_sase_agent_entries,
            format_confirmation_entries,
        )

        loaded_agents = tuple(
            getattr(self, "_agents_with_children", None)
            or getattr(self, "_agents", None)
            or (agent,)
        )
        desc_parts = ["Sase agent:"]
        desc_parts.extend(
            format_confirmation_entries(
                confirmation_sase_agent_entries(
                    [agent],
                    loaded_agents,
                    include_running_family_members=True,
                )
            )
        )
        desc_parts.append(f"Type: {agent.agent_type.value}")
        if agent.workspace_num is not None:
            desc_parts.append(f"Workspace: #{agent.workspace_num}")
        desc_parts.append(f"PID: {agent.pid}")
        agent_description = "\n".join(desc_parts)

        from ...modals import ConfirmKillModal

        def on_dismiss(confirmed: bool | None) -> None:
            if not confirmed:
                return
            current = resolve_agent_identity(self, identity)
            if current is None:
                self.notify(  # type: ignore[attr-defined]
                    "Selected agent is no longer available; nothing killed",
                    severity="warning",
                )
                return
            self._do_kill_agent(current)  # type: ignore[attr-defined]
            self._edit_and_relaunch_agent(
                raw_prompt,
                agent_project_file,
                agent_cl_name,
                agent_is_project_agent,
            )

        self.push_screen(ConfirmKillModal(agent_description), on_dismiss)  # type: ignore[attr-defined]

    def _edit_and_relaunch_agent(
        self,
        raw_prompt: str,
        project_file: str,
        cl_name: str,
        is_project_agent: bool,
    ) -> None:
        """Show agent prompt in the prompt input bar for editing and relaunch.

        The prompt is loaded exactly as stored.  Long logical lines wrap
        visually in the input bar, while the user can edit inline and submit,
        or press ``Ctrl+G`` to open their editor.

        Args:
            raw_prompt: The agent's raw xprompt content.
            project_file: The agent's project file path.
            cl_name: The agent's Patch name.
            is_project_agent: Whether the agent was a project-level agent.
        """
        self._mount_edit_relaunch_prompt_bar(
            project_file, cl_name, is_project_agent, initial_value=raw_prompt
        )

    def _edit_and_relaunch_agents_bulk(
        self,
        raw_prompts: list[str],
        project_file: str,
        cl_name: str,
        is_project_agent: bool,
    ) -> None:
        """Seed one editable prompt pane per killed agent (marked-set ``,x``).

        Like :meth:`_edit_and_relaunch_agent` but mounts a prompt stack from an
        explicit list of pane texts so each killed agent maps to exactly one
        pane, even when a raw prompt embeds ``---`` separators or YAML
        frontmatter.  *project_file*/*cl_name*/*is_project_agent* describe the
        first marked agent and only seed the home-mode selection/display, just
        as the single-agent path uses the one killed agent's metadata.

        Args:
            raw_prompts: The marked agents' raw prompts, in mark order.
            project_file: The first marked agent's project file path.
            cl_name: The first marked agent's Patch name.
            is_project_agent: Whether the first marked agent was project-level.
        """
        self._mount_edit_relaunch_prompt_bar(
            project_file, cl_name, is_project_agent, initial_panes=raw_prompts
        )

    def _mount_edit_relaunch_prompt_bar(
        self,
        project_file: str,
        cl_name: str,
        is_project_agent: bool,
        *,
        initial_value: str | None = None,
        initial_panes: list[str] | None = None,
    ) -> None:
        """Set up home-mode prompt context and mount the prompt input bar.

        Shared by the single-agent (*initial_value*) and bulk (*initial_panes*)
        kill-and-edit paths.  Exactly one of *initial_value*/*initial_panes*
        should be provided; *initial_panes* loads verbatim panes without
        ``---`` splitting.
        """
        from sase.core.time import generate_timestamp

        from ...modals import SelectionItem
        from ...widgets import PromptInputBar
        from sase.project_display_names import project_display_name_for

        project_name = Path(project_file).parent.name
        display_name = (
            project_display_name_for(project_name)
            if is_project_agent
            else humanize_cl_name(cl_name)
        )
        timestamp = generate_timestamp()
        workflow_name = f"ace(run)-{timestamp}"

        # Save for Ctrl+Space repeat
        selection = SelectionItem(
            display_name=display_name,
            item_type="project" if is_project_agent else "cl",
            project_name=project_name,
            cl_name=cl_name if not is_project_agent else None,
        )
        from sase.ace.last_agent_selection import (
            save_last_agent_selection_if_launchable,
        )

        if save_last_agent_selection_if_launchable(selection):
            self._last_custom_agent_selection = selection

        # Remove any existing prompt bar before mounting a new one.
        self._unmount_prompt_bar()  # type: ignore[attr-defined]

        # Set up prompt context for home mode.
        self._prompt_context = PromptContext(
            project_name="home",
            cl_name=None,
            project_file=preferred_project_spec_path(
                str(sase_projects_dir() / "home"), "home"
            ),
            workspace_dir=str(Path.home()),
            workspace_num=0,
            workflow_name=workflow_name,
            timestamp=timestamp,
            history_sort_key=cl_name,
            display_name=display_name,
            update_target="",
            is_home_mode=True,
        )

        # Show prompt input bar with display-safe prompt text. Soft wrapping is
        # visual only; bulk panes are seeded without ``---`` splitting.
        if initial_panes is not None:
            bar = PromptInputBar(
                initial_panes=[
                    humanize_vcs_refs_in_text(pane) for pane in initial_panes
                ],
                id="prompt-input-bar",
            )
        else:
            bar = PromptInputBar(
                initial_value=humanize_vcs_refs_in_text(initial_value or ""),
                id="prompt-input-bar",
            )
        self.mount(bar)  # type: ignore[attr-defined]
