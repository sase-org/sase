"""Selection and in-memory state helpers for agent revival."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._panel_fold_intent import effective_panel_collapses

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType


class AgentReviveStateMixin:
    """Mixin providing revive selection and dismissed-state helpers."""

    current_idx: int
    current_attempt_number: int | None
    _agents: list[Agent]
    _current_group_key: tuple[str, ...] | None
    _dismissed_agents: set[tuple[AgentType, str, str | None]]
    _revived_agent_raw_suffixes: set[str]

    def _select_revived_agent(self, agent: Agent) -> bool:
        """Select *agent* after a revive reload, including its tribe panel."""
        target_idx: int | None = None
        for idx, candidate in enumerate(getattr(self, "_agents", [])):
            if candidate.identity == agent.identity or (
                agent.raw_suffix and candidate.raw_suffix == agent.raw_suffix
            ):
                target_idx = idx
                break
        if target_idx is None:
            return False

        if hasattr(self, "_current_group_key"):
            self._current_group_key = None
        self.current_idx = target_idx
        if hasattr(self, "current_attempt_number"):
            self.current_attempt_number = None

        panel_group = getattr(self, "_panel_group", None)
        panel_keys_per_agent = getattr(self, "_panel_keys_per_agent", None)
        if panel_group is None or not callable(panel_keys_per_agent):
            return True

        try:
            keys_per_agent = panel_keys_per_agent()
        except Exception:
            return True
        if not (0 <= target_idx < len(keys_per_agent)):
            return True

        target_panel_key = keys_per_agent[target_idx]
        panel_keys = getattr(panel_group, "panel_keys", [])
        try:
            panel_group.focused_idx = panel_keys.index(target_panel_key)
            return True
        except ValueError:
            pass

        try:
            from ...models.agent_panels import AgentPanelGroup

            self._panel_group = AgentPanelGroup.from_agents(  # type: ignore[attr-defined]
                self._agents,
                target_panel_key,
                merge_tribe_panels=getattr(self, "_agent_panels_grouped", False),
                collapsed_panel_keys=effective_panel_collapses(self),
            )
        except Exception:
            pass
        return True

    def _remove_dismissed_aliases_for_suffixes(self, suffixes: set[str]) -> None:
        """Remove dismissed identities whose raw_suffix matches revived suffixes.

        Loader suppression uses suffix-based matching in addition to exact
        identity checks. Revive must clear all aliases sharing revived suffixes
        so restored artifacts can reappear in the panel.
        """
        if not suffixes:
            return
        self._dismissed_agents = {
            identity
            for identity in self._dismissed_agents
            if identity[2] is None or identity[2] not in suffixes
        }

    def _record_revived_agent_suffixes(self, suffixes: set[str]) -> None:
        """Remember revived suffixes across incomplete Tier 1 refreshes."""
        if not suffixes:
            return
        revived_suffixes = getattr(self, "_revived_agent_raw_suffixes", None)
        if revived_suffixes is None:
            revived_suffixes = set()
            self._revived_agent_raw_suffixes = revived_suffixes
        revived_suffixes.update(suffixes)
