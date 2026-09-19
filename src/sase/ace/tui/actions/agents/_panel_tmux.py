"""Agent tmux workspace actions for sase's TUI app."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from ._panel_types import TabName

if TYPE_CHECKING:
    from ...models.agent import Agent
    from ...modals.agent_workspace_tmux_modal import (
        AgentWorkspaceTmuxChoice,
        AgentWorkspaceTmuxSelection,
    )
    from ...opened_workspaces import OpenedWorkspaceDisplayEvent

_TMUX_MISSING = "tmux command not found"
_NO_WORKSPACE = "No workspace directory for agent"

_TmuxOutcomeStatus = Literal["opened", "switched", "skipped", "failed"]


@dataclass(frozen=True)
class _AgentTmuxDispatchTarget:
    """One tmux window captured on the UI thread and opened on a worker."""

    kind: str  # "current" or "linked"
    label: str
    window_name: str = ""
    workspace_dir: str | None = None
    use_primary: bool = False


@dataclass(frozen=True)
class _TmuxTargetOutcome:
    status: _TmuxOutcomeStatus
    label: str
    window_name: str
    detail: str


class AgentPanelTmuxMixin:
    """Mixin providing tmux workspace actions for selected agents."""

    current_tab: TabName

    # ------------------------------------------------------------------
    # No-I/O opened-workspace cache handoff
    #
    # The debounced detail render publishes the selected agent's cached
    # opened-workspace events here (keyed by agent identity). ``t`` reads only
    # this in-memory cache to decide whether to open the chooser, so the
    # keypress never parses marker JSON or ``stat()``s marker files.
    # ------------------------------------------------------------------

    def publish_selected_agent_opened_workspaces(
        self,
        agent: Agent,
        events: tuple[OpenedWorkspaceDisplayEvent, ...],
    ) -> None:
        """Store the cached opened-workspace events for ``agent``.

        Empty tuples are stored too, so old non-empty data cannot leak across
        refreshes once the selection's expensive summary is rebuilt.
        """
        self._selected_agent_opened_workspaces: tuple[
            tuple[Any, ...], tuple[OpenedWorkspaceDisplayEvent, ...]
        ] = (agent.identity, tuple(events))

    def cached_opened_workspaces_for_agent(
        self, agent: Agent
    ) -> tuple[OpenedWorkspaceDisplayEvent, ...]:
        """Return cached opened-workspace events for ``agent`` (no I/O)."""
        cached = getattr(self, "_selected_agent_opened_workspaces", None)
        if cached is None:
            return ()
        identity, events = cached
        if identity != agent.identity:
            return ()
        return events

    def cached_agent_tmux_choice_count(self, agent: Agent | None) -> int:
        """Return the number of tmux chooser targets for ``agent`` (no I/O).

        Counts ``CURRENT`` plus one deduped option per opened linked repo. A
        return value of ``0`` means no opened-workspace context is cached, so
        ``t`` keeps its direct-open behavior.
        """
        if agent is None:
            return 0
        events = self.cached_opened_workspaces_for_agent(agent)
        if not events:
            return 0
        from ...modals.agent_workspace_tmux_modal import (
            build_agent_workspace_tmux_choices,
        )

        return len(build_agent_workspace_tmux_choices(agent, events))

    # ------------------------------------------------------------------
    # Keymap actions
    # ------------------------------------------------------------------

    def action_open_tmux(self) -> None:
        """Open tmux window for primary workspace (agents tab) or default."""
        if self.current_tab == "agents":
            self._open_agent_tmux_window(use_primary=True)
            return
        super().action_open_tmux()  # type: ignore[misc]

    def action_start_tmux_mode(self) -> None:
        """``t`` opens the workspace chooser or tmux directly; tmux mode otherwise."""
        if self.current_tab == "agents":
            agent = self._get_selected_agent()  # type: ignore[attr-defined]
            if agent is None:
                self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
                return
            events = self.cached_opened_workspaces_for_agent(agent)
            if events:
                self._open_agent_workspace_tmux_chooser(agent, events)
                return
            self._open_agent_tmux_window(use_primary=False)
            return
        super().action_start_tmux_mode()  # type: ignore[misc]

    # ------------------------------------------------------------------
    # Chooser
    # ------------------------------------------------------------------

    def _open_agent_workspace_tmux_chooser(
        self,
        agent: Agent,
        events: tuple[OpenedWorkspaceDisplayEvent, ...],
    ) -> None:
        """Push the tmux workspace chooser for the selected agent."""
        from ...modals.agent_workspace_tmux_modal import (
            AgentWorkspaceTmuxModal,
            build_agent_workspace_tmux_choices,
        )

        current_dir, _ = self._resolve_agent_tmux_target(agent, use_primary=False)
        choices = tuple(
            build_agent_workspace_tmux_choices(
                agent, events, current_workspace_dir=current_dir
            )
        )

        def _on_selected(selection: AgentWorkspaceTmuxSelection | None) -> None:
            if selection is None or not selection.indexes:
                return
            targets = _dispatch_targets_for_selection(choices, selection.indexes)
            if not targets:
                return
            self._dispatch_agent_tmux_targets(targets, agent=agent)

        self.push_screen(AgentWorkspaceTmuxModal(list(choices)), _on_selected)  # type: ignore[attr-defined]

    # ------------------------------------------------------------------
    # Current/primary workspace resolution + tmux open
    # ------------------------------------------------------------------

    def _resolve_agent_tmux_target(
        self, agent: Agent, *, use_primary: bool
    ) -> tuple[str | None, str]:
        """Resolve ``(workspace_dir, window_name)`` for the selected agent.

        Args:
            use_primary: If True, use the primary workspace (num=1) and project
                name as the tmux window name instead of the agent's workspace.
        """
        from pathlib import Path

        from ...widgets.prompt_panel._file_path_hints import (
            resolve_agent_workspace_dir,
        )

        workspace_num = 1 if use_primary else agent.effective_workspace_num
        if not use_primary and workspace_num is not None and workspace_num > 0:
            workspace_dir = resolve_agent_workspace_dir(
                workspace_num,
                agent.project_file,
            )
            if not workspace_dir and agent.workspace_dir:
                workspace_dir = resolve_agent_workspace_dir(
                    None,
                    agent.project_file,
                    agent.workspace_dir,
                )
        else:
            workspace_dir = resolve_agent_workspace_dir(
                workspace_num,
                agent.project_file,
                agent.workspace_dir if not use_primary else None,
            )

        project_name = (
            agent.project_display_name or Path(agent.project_file).parent.name
        )
        if use_primary:
            window_name = project_name
        else:
            window_name = f"{project_name}_{workspace_num}"
        return workspace_dir, window_name

    def _open_agent_tmux_window(self, *, use_primary: bool = False) -> None:
        """Open a new tmux window in the selected agent's workspace directory.

        Args:
            use_primary: If True, use the primary workspace (num=1) and project
                name as the tmux window name instead of the agent's workspace.
        """
        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
            return

        self._dispatch_agent_tmux_targets(
            (
                _AgentTmuxDispatchTarget(
                    kind="current",
                    label=agent.display_name or agent.cl_name or "workspace",
                    use_primary=use_primary,
                ),
            ),
            agent=agent,
        )

    def _dispatch_agent_tmux_targets(
        self,
        targets: Sequence[_AgentTmuxDispatchTarget],
        *,
        agent: Agent | None,
    ) -> None:
        """Open ``targets`` on a thread-backed worker; notify on the UI thread."""
        if not targets:
            return
        captured = tuple(targets)

        def work() -> None:
            outcomes = _open_agent_tmux_targets(
                captured,
                agent=agent,
                resolve_current=self._resolve_agent_tmux_target,
            )

            def complete() -> None:
                self._notify_agent_tmux_outcomes(outcomes)

            call_from_thread = getattr(self, "call_from_thread", None)
            if callable(call_from_thread):
                call_from_thread(complete)
                return
            complete()

        run_worker = getattr(self, "run_worker", None)
        if not callable(run_worker):
            work()
            return
        try:
            run_worker(
                work,
                thread=True,
                name="agent-tmux-open",
                exit_on_error=False,
            )
        except TypeError:
            run_worker(work, thread=True)

    def _notify_agent_tmux_outcomes(
        self, outcomes: Sequence[_TmuxTargetOutcome]
    ) -> None:
        formatted = _format_agent_tmux_notify(outcomes)
        if formatted is None:
            return
        message, severity = formatted
        if severity == "information":
            self.notify(message)  # type: ignore[attr-defined]
            return
        self.notify(message, severity=severity)  # type: ignore[attr-defined]


def _dispatch_targets_for_selection(
    choices: Sequence[AgentWorkspaceTmuxChoice],
    indexes: Sequence[int],
) -> tuple[_AgentTmuxDispatchTarget, ...]:
    """Map chooser indexes onto dispatch targets, skipping out-of-range rows."""
    targets: list[_AgentTmuxDispatchTarget] = []
    for index in indexes:
        if not 0 <= index < len(choices):
            continue
        choice = choices[index]
        if choice.kind == "current":
            targets.append(
                _AgentTmuxDispatchTarget(
                    kind="current",
                    label=choice.label,
                    use_primary=False,
                )
            )
            continue
        targets.append(
            _AgentTmuxDispatchTarget(
                kind="linked",
                label=choice.label,
                window_name=choice.window_name,
                workspace_dir=choice.workspace_dir,
            )
        )
    return tuple(targets)


def _open_agent_tmux_targets(
    targets: Sequence[_AgentTmuxDispatchTarget],
    *,
    agent: Agent | None,
    resolve_current: Any,
) -> list[_TmuxTargetOutcome]:
    """Resolve directories and run tmux for ``targets`` in chooser order."""
    outcomes: list[_TmuxTargetOutcome] = []
    for target in targets:
        if target.kind == "current":
            if agent is None:
                outcomes.append(
                    _TmuxTargetOutcome(
                        status="skipped",
                        label=target.label,
                        window_name=target.window_name,
                        detail="No agent selected",
                    )
                )
                continue
            workspace_dir, window_name = resolve_current(
                agent, use_primary=target.use_primary
            )
            if not workspace_dir:
                outcomes.append(
                    _TmuxTargetOutcome(
                        status="skipped",
                        label=target.label,
                        window_name=window_name,
                        detail=_NO_WORKSPACE,
                    )
                )
                continue
            outcome = _tmux_select_or_create_window(
                workspace_dir,
                window_name,
                label=target.label,
            )
        else:
            workspace_dir = os.path.expanduser(target.workspace_dir or "")
            if not workspace_dir or not os.path.isdir(workspace_dir):
                outcomes.append(
                    _TmuxTargetOutcome(
                        status="skipped",
                        label=target.label,
                        window_name=target.window_name,
                        detail=f"Linked workspace not found: {target.label}",
                    )
                )
                continue
            outcome = _tmux_select_or_create_window(
                workspace_dir.rstrip("/"),
                target.window_name,
                label=target.label,
            )
        outcomes.append(outcome)
        if outcome.detail == _TMUX_MISSING:
            break
    return outcomes


def _tmux_select_or_create_window(
    workspace_dir: str,
    window_name: str,
    *,
    label: str,
) -> _TmuxTargetOutcome:
    """Select an existing tmux window named ``window_name`` or create one."""
    try:
        listed = subprocess.run(
            ["tmux", "list-windows", "-F", "#{window_name}"],
            capture_output=True,
            text=True,
            check=False,
        )
        if listed.returncode == 0 and window_name in listed.stdout.strip().splitlines():
            selected = subprocess.run(
                ["tmux", "select-window", "-t", f":={window_name}"],
                capture_output=True,
                text=True,
                check=False,
            )
            if selected.returncode == 0:
                return _TmuxTargetOutcome(
                    status="switched",
                    label=label,
                    window_name=window_name,
                    detail=f"Switched to tmux window: {window_name}",
                )
            return _TmuxTargetOutcome(
                status="failed",
                label=label,
                window_name=window_name,
                detail=f"Failed to switch to tmux window: {window_name}",
            )
        created = subprocess.run(
            ["tmux", "new-window", "-n", window_name, "-c", workspace_dir],
            capture_output=True,
            text=True,
            check=False,
        )
        if created.returncode == 0:
            return _TmuxTargetOutcome(
                status="opened",
                label=label,
                window_name=window_name,
                detail=f"Opened tmux window: {window_name}",
            )
        return _TmuxTargetOutcome(
            status="failed",
            label=label,
            window_name=window_name,
            detail=f"Failed to open tmux window: {window_name}",
        )
    except FileNotFoundError:
        return _TmuxTargetOutcome(
            status="failed",
            label=label,
            window_name=window_name,
            detail=_TMUX_MISSING,
        )


def _format_agent_tmux_notify(
    outcomes: Sequence[_TmuxTargetOutcome],
) -> tuple[str, str] | None:
    """Return ``(message, severity)`` for one or more tmux open outcomes."""
    if not outcomes:
        return None
    if len(outcomes) == 1:
        outcome = outcomes[0]
        if outcome.status in {"opened", "switched"}:
            return outcome.detail, "information"
        if outcome.status == "skipped":
            return outcome.detail, "warning"
        return outcome.detail, "error"

    opened = [item for item in outcomes if item.status == "opened"]
    switched = [item for item in outcomes if item.status == "switched"]
    skipped = [item for item in outcomes if item.status == "skipped"]
    failed = [item for item in outcomes if item.status == "failed"]
    if (
        not opened
        and not switched
        and not skipped
        and failed
        and all(item.detail == _TMUX_MISSING for item in failed)
    ):
        return _TMUX_MISSING, "error"

    parts: list[str] = []
    if opened:
        parts.append(f"Opened {len(opened)}")
    if switched:
        verb = "Switched" if not parts else "switched"
        parts.append(f"{verb} {len(switched)}")
    if skipped:
        verb = "Skipped" if not parts else "skipped"
        labels = ", ".join(item.label for item in skipped)
        parts.append(f"{verb} {len(skipped)}: {labels}")
    if failed:
        verb = "Failed" if not parts else "failed"
        names = ", ".join(item.window_name or item.label for item in failed)
        parts.append(f"{verb} {len(failed)}: {names}")
    if failed:
        severity = "error"
    elif skipped:
        severity = "warning"
    else:
        severity = "information"
    return ", ".join(parts), severity
