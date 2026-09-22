"""Executor and context-aware Enter action for AgentEnterTargets.

Wires the pure resolver in :mod:`._agent_enter_targets` to the live app:
the cached notification snapshot index, ``_resolve_agent_cl_name``, and the
in-memory Patch lookup, plus the ``act_on_agent`` app action that dispatches
through the chooser modal.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from sase.gate_shell.naming import short_gate_shell_id

from ._agent_enter_targets import (
    NO_TARGET_EMPTY_MESSAGE,
    AgentEnterResolution,
    AgentEnterTarget,
    GateNotificationIndex,
    PatchSummary,
    build_gate_notification_index,
    empty_gate_notification_index,
    resolve_agent_enter_targets,
)

if TYPE_CHECKING:
    from ...models import Agent


def _pr_label_for_patch(patch: Any) -> str | None:
    """Derive a ``PR #N`` label from a Patch's PR URL, if recognizable."""
    import re

    pr_url = getattr(patch, "pr_url", None)
    if not isinstance(pr_url, str) or not pr_url.strip():
        return None
    match = re.search(r"#(\d+)", pr_url) or re.search(r"/(\d+)(?:/?)$", pr_url)
    if match is None:
        return None
    return f"PR #{match.group(1)}"


def _short_gate_ref(target: AgentEnterTarget) -> str:
    if target.gate_id:
        try:
            return short_gate_shell_id(target.gate_id)
        except Exception:
            return target.gate_id[:8]
    if target.notification_id:
        return target.notification_id[:8]
    if target.bundle_path:
        return target.bundle_path.rsplit("/", 1)[-1]
    return "unknown"


class AgentEnterActionMixin:
    """Resolve and run context-aware Enter targets for the Agents tab."""

    def _agent_enter_resolution(self: Any, agent: Agent) -> AgentEnterResolution:
        """Resolve Enter targets for *agent* from in-memory state only."""
        snapshot = getattr(self, "_notification_snapshot_cache", None)
        index: GateNotificationIndex
        if snapshot is None:
            index = empty_gate_notification_index()
        else:
            index = build_gate_notification_index(snapshot)
        return resolve_agent_enter_targets(
            agent,
            gate_notifications=index,
            patch_name_for=self._resolve_agent_cl_name,  # type: ignore[attr-defined]
            patch_lookup=self._find_agent_enter_patch_summary,
        )

    def _find_agent_enter_patch_summary(
        self: Any, patch_name: str
    ) -> PatchSummary | None:
        """Look up Patch badge data in the in-memory Patch list only."""
        from ._notification_navigation import (
            find_patch_index_by_name,
            get_app_patches,
        )

        patches = get_app_patches(self)
        idx = find_patch_index_by_name(patches, patch_name)
        if idx is None:
            return None
        patch = patches[idx]
        return PatchSummary(
            status=getattr(patch, "status", None),
            pr_label=_pr_label_for_patch(patch),
        )

    def _agent_enter_agent(self: Any, agent_identity: tuple[object, ...]) -> Any:
        """Re-capture the target agent by identity, if still loaded."""
        resolver = getattr(self, "_agent_by_identity", None)
        if not callable(resolver):
            return None
        try:
            return resolver(agent_identity)
        except Exception:
            return None

    def _run_agent_enter_target(
        self: Any, target: AgentEnterTarget, *, agent_identity: tuple[object, ...]
    ) -> None:
        """Run one resolved Enter target."""
        if target.kind == "patch":
            from ._notification_navigation import navigate_to_patch_tab

            if not target.patch_name:
                self.notify("No Patch for this agent", severity="warning")  # type: ignore[attr-defined]
                return
            navigate_to_patch_tab(self, target.patch_name, target.project_file or "")
            return

        if target.source == "question_marker":
            agent = self._agent_enter_agent(agent_identity)
            if agent is None:
                self.notify("Agent is no longer visible", severity="warning")  # type: ignore[attr-defined]
                return
            opened = self._open_question_modal_from_marker(agent)  # type: ignore[attr-defined]
            if not opened:
                self.notify(  # type: ignore[attr-defined]
                    "No pending question found for this agent",
                    severity="warning",
                )
            return

        if target.source == "workflow_hitl":
            agent = self._agent_enter_agent(agent_identity)
            if agent is None:
                self.notify("Agent is no longer visible", severity="warning")  # type: ignore[attr-defined]
                return
            self._answer_workflow_hitl(agent)  # type: ignore[attr-defined]
            return

        if target.source == "remote_attention":
            agent = self._agent_enter_agent(agent_identity)
            if agent is None:
                self.notify("Agent is no longer visible", severity="warning")  # type: ignore[attr-defined]
                return
            self._answer_remote_attention_for(agent)  # type: ignore[attr-defined]
            return

        self._run_agent_enter_gate_target(target, agent_identity=agent_identity)

    def _run_agent_enter_gate_target(
        self: Any, target: AgentEnterTarget, *, agent_identity: tuple[object, ...]
    ) -> None:
        """Run a gate-row or notification gate target via the dispatcher."""
        from ._notification_dispatch import open_notification_action

        snapshot = getattr(self, "_notification_snapshot_cache", None)
        if snapshot is None:
            self._ensure_agent_enter_snapshot(
                lambda: self._run_agent_enter_target(
                    target, agent_identity=agent_identity
                )
            )
            return
        index = build_gate_notification_index(snapshot)
        notification = None
        if target.notification_id:
            notification = index.by_id.get(target.notification_id)
        if notification is None and target.bundle_path:
            notification = index.by_bundle_path.get(target.bundle_path)
        if notification is not None:
            open_notification_action(self, notification)
            self._schedule_notification_snapshot_refresh()  # type: ignore[attr-defined]
            return
        if not target.notification_id:
            self.notify(  # type: ignore[attr-defined]
                f"Gate {_short_gate_ref(target)} is no longer pending",
                severity="warning",
            )
            return
        self._load_agent_enter_gate_detail(target, agent_identity=agent_identity)

    def _load_agent_enter_gate_detail(
        self: Any, target: AgentEnterTarget, *, agent_identity: tuple[object, ...]
    ) -> None:
        """Read a missing gate notification off the pump, then revalidate."""
        from ...util.pump_tasks import spawn_pump_free_task
        from ._notification_provider import read_notification_detail_for_tui

        notification_id = target.notification_id
        assert notification_id is not None

        async def _load() -> None:
            try:
                result = await asyncio.to_thread(
                    read_notification_detail_for_tui,
                    notification_id,
                )
            except Exception:
                result = None
            invoker = getattr(self, "call_from_thread", None)
            detail = (
                result.value.notification
                if result is not None and result.value.notification is not None
                else None
            )

            def _finish() -> None:
                self._finish_agent_enter_gate_load(target, agent_identity, detail)

            if callable(invoker):
                invoker(_finish)
            else:
                _finish()

        task = spawn_pump_free_task(
            self,
            _load(),
            name="sase-agent-enter-gate-detail",
            registry_attr="_agent_enter_async_tasks",
        )
        if task is None:
            # No running loop (synchronous test doubles): cannot read
            # off-thread, so report the miss honestly instead of dispatching.
            self.notify(  # type: ignore[attr-defined]
                f"Couldn't load gate {_short_gate_ref(target)}; "
                f"try: sase gate show {_short_gate_ref(target)}",
                severity="warning",
            )

    def _finish_agent_enter_gate_load(
        self: Any,
        target: AgentEnterTarget,
        agent_identity: tuple[object, ...],
        notification: Any | None,
    ) -> None:
        """Dispatch a loaded gate notification after revalidating the target."""
        from ._notification_dispatch import open_notification_action

        short_ref = _short_gate_ref(target)
        agent = self._agent_enter_agent(agent_identity)
        if agent is None:
            self.notify("Agent is no longer visible", severity="warning")  # type: ignore[attr-defined]
            return
        resolution = self._agent_enter_resolution(agent)
        if all(item.key != target.key for item in resolution.targets):
            self.notify(  # type: ignore[attr-defined]
                f"Gate {short_ref} is no longer pending",
                severity="warning",
            )
            return
        if notification is None:
            self.notify(  # type: ignore[attr-defined]
                f"Couldn't load gate {short_ref}; try: sase gate show {short_ref}",
                severity="warning",
            )
            return
        open_notification_action(self, notification)
        self._schedule_notification_snapshot_refresh()  # type: ignore[attr-defined]

    def _ensure_agent_enter_snapshot(self: Any, then: Callable[[], None]) -> None:
        """Run *then* once the notification snapshot cache exists.

        Performs one off-pump snapshot read (stored via
        ``_set_notification_snapshot_cache``) when the cache is still empty,
        for the ``wire`` phase's Enter action.
        """
        if getattr(self, "_notification_snapshot_cache", None) is not None:
            then()
            return
        read = getattr(self, "_read_notification_snapshot_from_provider", None)
        if not callable(read):
            then()
            return

        async def _load_snapshot() -> None:
            try:
                snapshot = await asyncio.to_thread(read)
            except Exception as exc:
                self.notify(f"Couldn't load notifications: {exc}", severity="warning")  # type: ignore[attr-defined]
                return

            def _store_and_continue() -> None:
                self._set_notification_snapshot_cache(snapshot)  # type: ignore[attr-defined]
                then()

            invoker = getattr(self, "call_from_thread", None)
            if callable(invoker):
                invoker(_store_and_continue)
            else:
                _store_and_continue()

        from ...util.pump_tasks import spawn_pump_free_task

        task = spawn_pump_free_task(
            self,
            _load_snapshot(),
            name="sase-agent-enter-snapshot",
            registry_attr="_agent_enter_async_tasks",
        )
        if task is None:
            # No running loop (synchronous test doubles): continue with the
            # empty index rather than dropping the action.
            then()

    def action_act_on_agent(self: Any) -> None:
        """Run context-aware Enter for the selected Agents-tab row."""
        if getattr(self, "current_tab", None) != "agents":
            return
        if getattr(self, "_current_group_key", None) is not None:
            return
        getter = getattr(self, "_get_selected_agent", None)
        if not callable(getter):
            return
        try:
            selected = getter()
        except Exception:
            return
        if selected is None:
            return

        def _then() -> None:
            try:
                current = getter()
            except Exception:
                current = None
            target = current if current is not None else selected
            try:
                resolution = self._agent_enter_resolution(target)
            except Exception:
                return
            self._dispatch_agent_enter_resolution(target, resolution)

        self._ensure_agent_enter_snapshot(_then)

    def _dispatch_agent_enter_resolution(
        self: Any, agent: Any, resolution: AgentEnterResolution
    ) -> None:
        """Toast, run, or offer the chooser for one Enter resolution."""
        targets = resolution.targets
        if not targets:
            self.notify(  # type: ignore[attr-defined]
                resolution.empty_message or NO_TARGET_EMPTY_MESSAGE,
                severity="warning",
            )
            return
        identity = getattr(agent, "identity", None)
        if not isinstance(identity, tuple):
            fallback = targets[0].row_identity
            identity = fallback if isinstance(fallback, tuple) else ()
        if len(targets) == 1:
            self._run_agent_enter_target(targets[0], agent_identity=identity)
            return
        choices = tuple(_choice_for_enter_target(item) for item in targets)
        title = (
            f"Act on {resolution.scope_title}"
            if resolution.scope_title
            else "Act on agent"
        )

        def _on_choice(result_key: str | None) -> None:
            if result_key is None:
                return
            current = self._agent_enter_agent(identity)
            if current is None:
                self.notify("Agent is no longer visible", severity="warning")  # type: ignore[attr-defined]
                return
            try:
                fresh = self._agent_enter_resolution(current)
            except Exception:
                return
            for candidate in fresh.targets:
                if candidate.key == result_key:
                    current_identity = getattr(current, "identity", identity)
                    if not isinstance(current_identity, tuple):
                        current_identity = identity
                    self._run_agent_enter_target(
                        candidate, agent_identity=current_identity
                    )
                    return
            self.notify(  # type: ignore[attr-defined]
                "That action is no longer available",
                severity="warning",
            )

        from ...modals.agent_action_chooser_modal import AgentActionChooserModal

        self.push_screen(  # type: ignore[attr-defined]
            AgentActionChooserModal(choices, title=title),
            _on_choice,
        )


def _split_enter_badge(
    badge: str | None,
) -> tuple[str | None, str | None]:
    """Split a combined ``STATUS · age`` badge into its parts."""
    if not badge:
        return (None, None)
    if " · " in badge:
        head, tail = badge.split(" · ", 1)
        return (head.strip() or None, tail.strip() or None)
    return (badge, None)


def _choice_for_enter_target(target: AgentEnterTarget):  # type: ignore[no-untyped-def]
    """Map one Enter target to its chooser view model."""
    from ...modals.agent_action_chooser_modal import AgentActionChoice
    from sase.gate_shell.state import GATE_GLYPH

    if target.kind == "patch":
        return AgentActionChoice(
            result=target.key,
            section="patch",
            label=target.label,
            detail=target.detail,
            glyph="⎇",
            glyph_style=target.badge_style or "",
            badge=target.badge,
            badge_style=target.badge_style,
            age=None,
        )
    badge, age = _split_enter_badge(target.badge)
    style = target.badge_style or ""
    return AgentActionChoice(
        result=target.key,
        section="gate",
        label=target.label,
        detail=target.detail,
        glyph=GATE_GLYPH,
        glyph_style=style,
        badge=badge,
        badge_style=target.badge_style,
        age=age,
    )


__all__ = ["AgentEnterActionMixin"]
