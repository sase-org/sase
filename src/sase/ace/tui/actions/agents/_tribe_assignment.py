"""Agent tribe-assignment actions for sase's TUI Agents tab.

Wires the ``N`` keymap to a small modal that sets or clears the tribe on
the currently focused agent (or, if any agent marks exist, on every
marked agent — same precedence rule used elsewhere on the Agents tab).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from sase.macro.directive_edit import prompt_declares_clan

from ...models.agent_pin import DEFAULT_PINNED_TRIBE
from ..proc_actions import TrackedProcCompletion

TabName = Literal["artifacts", "agents", "services"]

__all__ = ["AgentTribeAssignmentMixin", "DEFAULT_PINNED_TRIBE"]

if TYPE_CHECKING:
    from ...modals.agent_tribe_modal import AgentTribeModalResult
    from ...models import Agent
    from ...models.agent import AgentType


def _clan_aware_bulk_label(affected: list[Agent]) -> str:
    """Describe a bulk modal target, naming the clan when clan-bound."""
    clans = sorted({a.agent_clan for a in affected if a.agent_clan})
    if clans and all(a.agent_clan for a in affected):
        if len(clans) == 1:
            return f"clan {clans[0]} ({len(affected)} members)"
        return f"{len(affected)} marked agent(s) in clans {', '.join(clans)}"
    return f"{len(affected)} marked agent(s)"


class AgentTribeAssignmentMixin:
    """Mixin providing the agent-tribe modal action (``N`` keymap)."""

    current_tab: TabName
    _agents: list[Agent]
    _agents_with_children: list[Agent]
    _marked_agents: set[tuple[AgentType, str, str | None]]
    _marked_agent_order: list[tuple[AgentType, str, str | None]]

    def action_edit_agent_tribe(self) -> None:
        """Open the agent-tribe modal for the focused agent or marked set."""
        if self.current_tab != "agents":
            return

        from sase.ace.agent_tribes import load_agent_tribes

        store = load_agent_tribes()
        known_tribes = sorted(set(store.values()))
        known_tabs = tuple(
            sorted(
                {
                    agent.agent_tab
                    for agent in self._agents_with_children
                    if agent.agent_tab
                }
            )
        )

        # Bulk path: if marks exist, the modal targets every marked agent.
        if self._marked_agents:
            marked: list[Agent] = [
                a
                for a in self._agents_with_children
                if a.identity in self._marked_agents
            ]
            if not marked:
                self.notify(  # type: ignore[attr-defined]
                    "No marked agents remain",
                    severity="warning",
                )
                return
            self._open_agent_tribe_modal(
                target_label=_clan_aware_bulk_label(marked),
                current_tribe=None,
                known_tribes=tuple(known_tribes),
                affected=marked,
                known_tabs=known_tabs,
            )
            return

        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
            return
        clan_bound = bool(agent.agent_clan)
        self._open_agent_tribe_modal(
            target_label=(
                f"clan {agent.agent_clan}" if clan_bound else agent.display_name
            ),
            current_tribe=(agent.clan_tribe if clan_bound else agent.tribe),
            known_tribes=tuple(known_tribes),
            affected=[agent],
            default_tribe=DEFAULT_PINNED_TRIBE,
            current_tab=agent.agent_tab,
            known_tabs=known_tabs,
        )

    def _open_agent_tribe_modal(
        self,
        *,
        target_label: str,
        current_tribe: str | None,
        known_tribes: tuple[str, ...],
        affected: list[Agent],
        default_tribe: str | None = None,
        current_tab: str | None = None,
        known_tabs: tuple[str, ...] = (),
    ) -> None:
        from ...modals import AgentTribeModal

        def on_dismiss(result: AgentTribeModalResult | None) -> None:
            if result is None:
                return
            self._apply_agent_tribe_change(result, affected)

        self.push_screen(  # type: ignore[attr-defined]
            AgentTribeModal(
                target_label=target_label,
                current_tribe=current_tribe,
                known_tribes=known_tribes,
                default_tribe=default_tribe,
                current_tab=current_tab,
                known_tabs=known_tabs,
            ),
            on_dismiss,
        )

    def _apply_agent_tribe_change(
        self,
        result: AgentTribeModalResult,
        affected: list[Agent],
    ) -> None:
        """Persist the requested tribe/tab change for every agent in *affected*."""
        from ._remote_lifecycle import is_remote_fleet_agent

        snapshot_agents = getattr(self, "_snapshot_agents_for_local_display", None)
        previous_agents = (
            snapshot_agents() if callable(snapshot_agents) else list(self._agents)
        )
        tribe_keep = result.action == "keep"
        move_tab = result.tab_action != "keep"
        tab_after: str | None = result.tab if result.tab_action == "set" else None
        # Tab moves run on the owning machine: remote fleet rows are
        # viewer-only here, so they keep their tab while local rows move.
        remote_affected = [a for a in affected if is_remote_fleet_agent(a)]
        tab_targets = [a for a in affected if not is_remote_fleet_agent(a)]
        tab_target_ids = {a.identity for a in tab_targets}
        if move_tab and remote_affected and tribe_keep and not tab_targets:
            self.notify(  # type: ignore[attr-defined]
                "Tab moves run on the owning machine",
                severity="warning",
            )
            return
        changed = 0
        tab_changed = 0
        affected_identities = {agent.identity for agent in affected}
        prior_tribes = {agent.identity: agent.tribe for agent in affected}
        prior_clan_tribes = {agent.identity: agent.clan_tribe for agent in affected}
        prior_tabs = {agent.identity: agent.agent_tab for agent in tab_targets}
        updates: list[dict[str, object]] = []
        clan_afters: dict[tuple[str, str], str | None] = {}
        emitted_clan_records: set[tuple[str, str]] = set()
        for agent in affected:
            clan_bound = bool(agent.agent_clan)
            after: str | None = None
            if not tribe_keep:
                visible_before = agent.clan_tribe if clan_bound else agent.tribe
                if result.action == "set":
                    assert result.tribe is not None
                    after = result.tribe
                if after != visible_before:
                    changed += 1

            move_this = move_tab and agent.identity in tab_target_ids
            if move_this and tab_after != (agent.agent_tab or None):
                tab_changed += 1

            artifacts_dir = agent.get_artifacts_dir()
            if clan_bound and not tribe_keep:
                clan = agent.agent_clan or ""
                clan_generation = agent.agent_clan_generation or ""
                if not clan_generation:
                    if not artifacts_dir:
                        self.notify(  # type: ignore[attr-defined]
                            "Cannot record a clan tribe without a clan generation",
                            severity="warning",
                        )
                        return
                else:
                    key = (clan, clan_generation)
                    if key not in clan_afters:
                        clan_afters[key] = after
            clan_prompt_declares = False
            if clan_bound and artifacts_dir:
                raw_prompt = agent.get_raw_prompt_content()
                clan_prompt_declares = bool(
                    raw_prompt is not None and prompt_declares_clan(raw_prompt)
                )
            prompt_kind = None
            if artifacts_dir and not tribe_keep:
                if clan_prompt_declares:
                    prompt_kind = "set_clan_tribe"
                elif not clan_bound:
                    prompt_kind = "set_tribe"
            update: dict[str, object] = {
                "artifacts_dir": artifacts_dir,
            }
            if prompt_kind is not None:
                prompt_spec: dict[str, object] = {
                    "kind": prompt_kind,
                    "tribe": after,
                }
                if move_this:
                    prompt_spec["tab"] = tab_after
                update["prompt"] = prompt_spec
            elif move_this and artifacts_dir:
                update["prompt"] = {"kind": "set_tab", "tab": tab_after}
            if artifacts_dir and (not tribe_keep or move_this):
                meta_set: dict[str, object] = {}
                meta_remove: list[str] = []
                if not tribe_keep:
                    if clan_bound and after:
                        meta_set["clan_tribe"] = after
                    elif after:
                        meta_set["tribe"] = after
                    elif clan_bound:
                        meta_remove.append("clan_tribe")
                    else:
                        meta_remove.extend(["tribe", "tag"])
                if move_this:
                    if tab_after is not None:
                        meta_set["agent_tab"] = tab_after
                        meta_set["agent_tab_source"] = "moved"
                    else:
                        meta_remove.extend(["agent_tab", "agent_tab_source"])
                update["meta_set"] = meta_set
                update["meta_remove"] = meta_remove
            if not clan_bound and not tribe_keep:
                update["tribe"] = {
                    "identity": list(agent.identity),
                    "tribe": after,
                }
            if clan_bound and not tribe_keep:
                clan = agent.agent_clan or ""
                clan_generation = agent.agent_clan_generation or ""
                key = (clan, clan_generation)
                # Only the first update per (clan, generation) carries the
                # durable record edit; later members of the same clan
                # deduplicate to one record write.
                if (
                    key in clan_afters
                    and clan_afters[key] == after
                    and key not in emitted_clan_records
                ):
                    emitted_clan_records.add(key)
                    update["clan_record"] = {
                        "clan": clan,
                        "generation": clan_generation,
                        "tribe": after,
                    }
            updates.append(update)

        if changed == 0 and tab_changed == 0:
            if not tribe_keep:
                verb = "set" if result.action == "set" else "unset"
                self.notify(  # type: ignore[attr-defined]
                    f"No tribe {verb} (already in target state)",
                    severity="information",
                )
            else:
                where = tab_after if tab_after is not None else "the default tab"
                self.notify(  # type: ignore[attr-defined]
                    f"Already on {where}",
                    severity="information",
                )
            return

        generation = object()
        for agent in affected:
            agent._directive_generation = generation  # type: ignore[attr-defined]
        # Optimistic clan display also covers sibling members and the
        # synthetic container sharing each edited (clan, generation).
        optimistic_clan_identities: set[tuple[object, str, str | None]] = set()
        for candidates in (self._agents, self._agents_with_children):
            for candidate in candidates:
                if not candidate.agent_clan:
                    continue
                key = (
                    candidate.agent_clan,
                    candidate.agent_clan_generation or "",
                )
                if key in clan_afters:
                    optimistic_clan_identities.add(candidate.identity)
        for candidates in (self._agents, self._agents_with_children):
            for candidate in candidates:
                if candidate.identity in optimistic_clan_identities:
                    if candidate.identity not in prior_tribes:
                        prior_tribes[candidate.identity] = candidate.tribe
                    if candidate.identity not in prior_clan_tribes:
                        prior_clan_tribes[candidate.identity] = candidate.clan_tribe
        from ..agent_durable import submit_agent_directive

        def _rollback_visible_tribes() -> None:
            for candidates in (self._agents, self._agents_with_children):
                for candidate in candidates:
                    if candidate.identity in prior_tribes:
                        if (
                            getattr(candidate, "_directive_generation", None)
                            is not generation
                            and candidate.identity not in optimistic_clan_identities
                        ):
                            continue
                        candidate.tribe = prior_tribes[candidate.identity]
                        candidate.clan_tribe = prior_clan_tribes[candidate.identity]
                    if candidate.identity in prior_tabs:
                        if (
                            getattr(candidate, "_directive_generation", None)
                            is not generation
                        ):
                            continue
                        candidate.agent_tab = prior_tabs[candidate.identity]
            try:
                from ._roster_generation import notify_tribe_assignment_mutation

                notify_tribe_assignment_mutation(self)
            except Exception:  # noqa: BLE001 - cache invalidation only.
                pass

        def _on_complete(
            completion: TrackedProcCompletion[object],
        ) -> None:
            if completion.collision or completion.success:
                return
            _rollback_visible_tribes()
            failed = (
                "Agent tab persist failed"
                if tribe_keep
                else "Agent tribe persist failed"
            )
            self.notify(  # type: ignore[attr-defined]
                f"{failed}: {completion.message}",
                severity="error",
            )
            refresh = getattr(self, "_schedule_agents_async_refresh", None)
            if callable(refresh):
                refresh(source="agent-tribe-persist-failed")

        first_dir = next(
            (
                str(item.get("artifacts_dir"))
                for item in updates
                if item.get("artifacts_dir")
            ),
            "agent-tribes",
        )
        display_name = (
            f"Move {tab_changed} to tab" if tribe_keep else f"Persist tribes: {changed}"
        )
        submitted = submit_agent_directive(
            self,
            artifacts_dir=first_dir,
            payload={"updates": updates},
            cl_name="agent-tribes",
            display_name=display_name,
            on_complete=_on_complete,
            tribe_store=True,
            duplicate_message="A tribe persistence proc is already running",
        )
        if not submitted:
            return

        tribe_after = result.tribe if result.action == "set" else None
        for candidates in (self._agents, self._agents_with_children):
            for candidate in candidates:
                if candidate.identity in affected_identities:
                    if not tribe_keep:
                        if candidate.agent_clan:
                            candidate.clan_tribe = tribe_after
                            if candidate.is_clan_container:
                                candidate.tribe = tribe_after
                        else:
                            candidate.tribe = tribe_after
                    if candidate.identity in tab_target_ids:
                        candidate.agent_tab = tab_after
                elif candidate.identity in optimistic_clan_identities:
                    key = (
                        candidate.agent_clan or "",
                        candidate.agent_clan_generation or "",
                    )
                    after = clan_afters.get(key)
                    candidate.clan_tribe = after
                    if candidate.is_clan_container:
                        candidate.tribe = after
        if not tribe_keep:
            try:
                from ._roster_generation import bump_tribe_assignment_generation

                bump_tribe_assignment_generation(self)
            except Exception:  # noqa: BLE001 - cache invalidation only.
                pass

        if move_tab and remote_affected and tab_targets:
            self.notify(  # type: ignore[attr-defined]
                "Tab moves run on the owning machine "
                f"(skipped {len(remote_affected)} remote "
                f"{'row' if len(remote_affected) == 1 else 'rows'})",
                severity="warning",
            )
        if tab_changed:
            tab_suffix = "agent" if tab_changed == 1 else "agents"
            tab_where = tab_after if tab_after is not None else "main"
            self.notify(  # type: ignore[attr-defined]
                f"Moved {tab_changed} {tab_suffix} to {tab_where}",
            )
            try:
                from ._tab_scope import refresh_agent_tab_index

                refresh_agent_tab_index(self)
            except Exception:  # noqa: BLE001 - the next refresh rebuilds anyway.
                pass

        clan_names = sorted({clan for clan, _gen in clan_afters})
        all_clan_bound = clan_afters and all(a.agent_clan for a in affected)
        if not tribe_keep and all_clan_bound and len(clan_names) == 1:
            if result.action == "set":
                assert result.tribe is not None
                self.notify(  # type: ignore[attr-defined]
                    f"Set @{result.tribe} for clan {clan_names[0]}",
                )
            else:
                self.notify(  # type: ignore[attr-defined]
                    f"Cleared tribe for clan {clan_names[0]}",
                )
            if not tab_changed:
                return
        elif not tribe_keep:
            suffix = "agent" if changed == 1 else "agents"
            if result.action == "set":
                assert result.tribe is not None
                self.notify(  # type: ignore[attr-defined]
                    f"Set @{result.tribe} on {changed} {suffix}",
                )
            else:
                self.notify(  # type: ignore[attr-defined]
                    f"Cleared tribe on {changed} {suffix}",
                )
        self._marked_agents -= affected_identities
        order = getattr(self, "_marked_agent_order", None)
        if order:
            self._marked_agent_order = [
                i for i in order if i not in affected_identities
            ]
        self._invalidate_agent_panel_cache()  # type: ignore[attr-defined]

        refilter = getattr(self, "_refilter_agents", None)
        if callable(refilter):
            try:
                refilter(previous_agents=previous_agents)
            except TypeError:
                refilter()
        else:
            self._refresh_agents_display(list_changed=True)  # type: ignore[attr-defined]
