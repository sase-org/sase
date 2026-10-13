"""Target resolution and non-artifacts destinations for ``$`` link-follow."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from sase.core.artifact_entry_target import ArtifactEntryTarget

if TYPE_CHECKING:
    from ..models.agent import AgentType

from ..relations.artifact_links import parse_link_ref, target_for_ref_kind
from ..tab_order import ARTIFACTS_TAB
from ..widgets.artifacts.entry_navigation import LinkRequestState
from ._link_follow_helpers import (
    agent_matches_ref,
    chop_matches,
    pane_label,
)
from ._link_follow_types import LinkTrailHop, record_link_follow_outcome
from .axe_display._loader_items import selected_axe_item_key

log = logging.getLogger(__name__)


def _confirmed_loaded_agent(owner: Any, match: Any) -> tuple[Any | None, str]:
    """Return the loaded-set agent for *match* (object or name).

    The ``(agent, name)`` pair confirms the target is still loaded before any
    caller rewrites the Inbox query; ``(None, name)`` means the follow must
    fall through without touching the query.
    """
    complete = list(
        getattr(owner, "_agents_with_children", None)
        or getattr(owner, "_agents", None)
        or ()
    )
    if isinstance(match, str):
        resolved = next(
            (agent for agent in complete if agent_matches_ref(agent, match)),
            None,
        )
        return resolved, match
    name = str(getattr(match, "agent_name", "") or "")
    if not name:
        return None, ""
    identity = getattr(match, "identity", None)
    if identity is not None:
        for agent in complete:
            if getattr(agent, "identity", None) == identity:
                return agent, name
    resolved = next(
        (agent for agent in complete if agent_matches_ref(agent, name)),
        None,
    )
    return resolved, name


def reveal_filtered_loaded_agent(owner: Any, match: Any) -> bool:
    """Reveal a filter-hidden loaded agent through an exact-name query.

    Shared by ``$`` link-follow and Archive restore-and-show: *match* is a
    loaded agent or its name. The target is confirmed in the loaded agent set
    before the Inbox query is touched, so a fallthrough never leaves a
    rewritten query behind. After the refilter the full tab/fold reveal runs
    first, with the visible select as fallback, and the toast names the ``^``
    restore key.
    """
    import json

    resolved, name = _confirmed_loaded_agent(owner, match)
    if resolved is None or not name:
        return False
    old_query = str(getattr(owner, "_agent_search_query", "") or "")
    query = f"name:{json.dumps(name, ensure_ascii=False)}"
    record_transition = getattr(owner, "_record_agents_live_query_transition", None)
    if callable(record_transition):
        record_transition(old_query, query)
    commit = getattr(owner, "_record_explicit_agents_query_commit", None)
    if callable(commit):
        commit(query)
    refilter = getattr(owner, "_refilter_agents", None)
    if callable(refilter):
        refilter()
    reveal = getattr(owner, "_reveal_loaded_agent", None)
    selected = reveal(resolved) if callable(reveal) else False
    if not selected:
        select = getattr(owner, "_select_visible_loaded_agent", None)
        selected = select(name) if callable(select) else False
    if selected:
        notify = getattr(owner, "notify", None)
        if callable(notify):
            notify(
                f"The inbox filter hid it — showing {query} · ^ restores your filter",
                severity="information",
            )
    return bool(selected)


class LinkFollowTargetsMixin:
    """Resolve destinations and select loaded target rows."""

    current_tab: Any
    current_idx: int
    _link_follow_dispatching: bool
    _link_follow_dispatch_slot: tuple[int, LinkRequestState] | None
    _link_follow_agents_tab_filtered: bool
    _agents_last_idx: int
    _agents_last_identity: tuple[AgentType, str, str | None] | None
    _current_group_key: tuple[str, ...] | None
    _expanded_panel_focus: bool

    def _follow_artifacts_target(
        self,
        ref: str,
        chip_target: ArtifactEntryTarget,
        origin: LinkTrailHop,
    ) -> None:
        """Resolve and dispatch one artifacts-pane follow to completion.

        Handles the immediate same-pane fast path itself; every other case
        opens a host-owned transaction before touching the destination pane,
        so a synchronous ``SELECTED``/``MISSING``/``FAILED`` report through
        the shared completion seam can finalize safely, and a ``PENDING``
        report leaves the transaction open for a later async one.

        An ``agent:`` ref never enters the Artifacts transaction while the
        Agent pane stays retired: it reveals on the Agents tab (Inbox) or
        arrives in the Archive by lookup. With the pane itself shown
        (flag off) the pane path below still resolves it there.
        """
        parsed = parse_link_ref(ref)
        if parsed is not None and parsed[0] == "agent":
            from .._artifact_tab_model import artifacts_agent_pane_retired

            if artifacts_agent_pane_retired():
                self._follow_agent_ref_to_agents_tab(parsed[1], origin)
                return
        target = self._resolve_link_follow_target(ref, chip_target)
        if self._is_unconfigured_artifacts_target(target.pane_id):
            navigator = getattr(self, "_artifacts_entry_navigator", None)
            pane = navigator(target.pane_id) if callable(navigator) else None
            if pane is None:
                record_link_follow_outcome("missing")
                self._notify_unconfigured_link_pane(ref, target)
                return
        if self._select_current_artifacts_target(target):
            record_link_follow_outcome("select")
            self._record_link_trail(origin)  # type: ignore[attr-defined]
            return
        scope_change = self._switch_artifacts_scope_for_target(ref, target)
        if self.current_tab != ARTIFACTS_TAB:
            self._save_current_tab_position()  # type: ignore[attr-defined]
            self.current_tab = ARTIFACTS_TAB
        generation = self._begin_link_follow_transaction(  # type: ignore[attr-defined]
            ref,
            target,
            origin,
            scope_change=scope_change,
        )
        state = self._request_artifacts_target(target, generation=generation)
        handle = self._handle_link_follow_outcome  # type: ignore[attr-defined]
        handle(generation, state)

    def _follow_agent_ref_to_agents_tab(
        self,
        payload: str,
        origin: LinkTrailHop,
    ) -> None:
        """Route an ``agent:`` ref to the Agents tab, never the retired pane.

        A loaded agent reveals in place and records one trail hop; a
        dismissed one arrives in the Archive through the lookup-first
        arrival, which toasts on a miss and changes nothing.
        """
        if self._follow_loaded_agent(payload):
            record_link_follow_outcome("select")
            self._record_link_trail(origin)  # type: ignore[attr-defined]
            return
        from .agents._archive_arrival import open_archive_for_agent

        open_archive_for_agent(
            self,
            payload,
            source="Not in your inbox",
            origin=origin,
            return_on_miss=True,
        )

    def _switch_artifacts_scope_for_target(
        self,
        ref: str,
        target: ArtifactEntryTarget,
    ) -> tuple[str | None, str | None] | None:
        """Switch the Artifacts project scope for *target*, if required.

        An All-projects scope is never narrowed. A specific scope that
        excludes the target switches to the target's own project (answered
        by the destination pane's
        :meth:`~sase.ace.tui.widgets.artifacts.entry_navigation.ArtifactEntryNavigator.entry_target_project`,
        never by guessing from the ref). When the project is unknown, the
        scope widens to All projects only if the pane cannot resolve the
        target under the current scope. Returns the ``(old, new)`` scope
        change, or ``None`` when the scope was untouched.
        """
        current = getattr(self, "artifacts_project_scope", None)
        if current is None:
            return None
        pane = self._artifacts_entry_navigator(  # type: ignore[attr-defined]
            target.pane_id
        )
        projector = getattr(pane, "entry_target_project", None)
        project = projector(target) if callable(projector) else None
        if project is not None:
            if project == current:
                return None
            self._set_artifacts_project_scope(  # type: ignore[attr-defined]
                project,
                picked=True,
            )
            return (current, project)
        parsed = parse_link_ref(ref)
        answered = False
        if parsed is not None and pane is not None:
            resolver = getattr(pane, "entry_target_for_ref", None)
            if callable(resolver):
                answered = resolver(*parsed) is not None
        if answered:
            return None
        self._set_artifacts_project_scope(  # type: ignore[attr-defined]
            None,
            picked=True,
        )
        return (current, None)

    def _resolve_link_follow_target(
        self,
        ref: str,
        chip_target: ArtifactEntryTarget,
    ) -> ArtifactEntryTarget:
        """Address *ref* by this pane's own row identity; *chip_target* is a hint.

        ``chip_target`` was synthesized at chip-build time from the ref's
        kind alone (:func:`target_for_ref_kind`) and can name a row identity
        the destination pane never uses -- it is reliable about which pane
        owns the ref, unreliable about which row. The destination pane's own
        :meth:`~.entry_navigation.ArtifactEntryNavigator.entry_target_for_ref`
        resolves the real row from its unfiltered snapshot; ``chip_target``
        survives only as the fallback when that pane has no answer, so a
        same-pane visible row still fast-paths through unchanged.
        """
        parsed = parse_link_ref(ref)
        if parsed is None:
            return chip_target
        kind, payload = parsed
        routed = target_for_ref_kind(kind, payload, project_hint=None)
        pane_id = routed.pane_id if routed is not None else chip_target.pane_id
        pane = self._artifacts_entry_navigator(pane_id)  # type: ignore[attr-defined]
        resolver = (
            getattr(pane, "entry_target_for_ref", None) if pane is not None else None
        )
        resolved = resolver(kind, payload) if callable(resolver) else None
        return resolved if resolved is not None else chip_target

    def _is_unconfigured_artifacts_target(self, pane_id: str) -> bool:
        """Return whether *pane_id* names a document pane with no provider.

        An unconfigured ``ref:<kind>`` must never normalize to Stitches
        (the default sub-tab). The exact descriptor lookup distinguishes a
        configured provider from a missing one; fixed panes never count.
        """
        try:
            from ..artifact_tabs import is_unconfigured_ref_pane
        except Exception:  # noqa: BLE001 - fail open to the old Stitches path
            return False
        try:
            return is_unconfigured_ref_pane(pane_id)
        except Exception:  # noqa: BLE001 - discovery errors are not unconfigured
            return False

    def _select_current_artifacts_target(self, target: ArtifactEntryTarget) -> bool:
        if self.current_tab != ARTIFACTS_TAB:
            return False
        pane = self._artifacts_entry_navigator()  # type: ignore[attr-defined]
        if pane is None or target not in pane.entry_targets():
            return False
        if not pane.select_entry_target(target):
            return False
        sync = getattr(self, "_sync_active_artifacts_entry_state", None)
        if callable(sync):
            sync()
        return True

    def _request_artifacts_target(
        self,
        target: ArtifactEntryTarget,
        *,
        generation: int | None = None,
    ) -> LinkRequestState:
        """Dispatch one pane request without the completion seam reentering.

        ``_link_follow_dispatching`` marks this call's extent so a
        synchronous report through :meth:`_complete_link_follow_request`
        lands in the dispatch slot instead of finalizing reentrantly. A
        returned ``PENDING`` is then upgraded to the recorded outcome for
        this generation -- panes report the state their synchronous
        refresh actually reached, but may still return ``PENDING``; the
        slot is the defense-in-depth guarantee that no such report is
        ever lost, whatever a pane returns.
        """
        request = getattr(self, "_request_artifacts_entry", None)
        if not callable(request):
            pane = self._artifacts_entry_navigator(  # type: ignore[attr-defined]
                target.pane_id
            )
            if pane is not None and pane.selected_entry_target() == target:
                return LinkRequestState.SELECTED
            return LinkRequestState.MISSING
        self._link_follow_dispatching = True
        self._link_follow_dispatch_slot = None
        try:
            state = request(target, generation=generation)
        finally:
            slot = self._link_follow_dispatch_slot
            self._link_follow_dispatching = False
            self._link_follow_dispatch_slot = None
        if (
            state is LinkRequestState.PENDING
            and slot is not None
            and slot[0] == generation
        ):
            return slot[1]
        return state

    def _follow_loaded_agent(self, payload: str) -> bool:
        """Reveal one loaded Agents-tab row in place for an ``agent:`` ref.

        Searches the full loaded agent set (``_agents_with_children``),
        not just the visible rows, and reveals through the shared
        prepare/reveal contract so collapsed folds, group banners, and
        panels open around the target. A row the Agents-tab filter hides
        (``TARGET_FILTERED``) is revealed by replacing the Inbox query
        with an exact name query. When the reveal machinery itself
        is unavailable, a directly visible row still selects the legacy
        way rather than failing the follow.
        """
        self._link_follow_agents_tab_filtered = False
        complete = list(
            getattr(self, "_agents_with_children", None)
            or getattr(self, "_agents", None)
            or ()
        )
        match = next(
            (agent for agent in complete if agent_matches_ref(agent, payload)),
            None,
        )
        if match is None:
            return False
        if self._reveal_loaded_agent(match):
            return True
        if self._link_follow_agents_tab_filtered:
            return self._reveal_filtered_loaded_agent(match)
        return self._select_visible_loaded_agent(payload)

    def _reveal_filtered_loaded_agent(self, match: Any) -> bool:
        """Replace the Inbox query with an exact name query and reveal *match*."""
        return reveal_filtered_loaded_agent(self, match)

    def _reveal_loaded_agent(self, match: Any) -> bool:
        """Reveal *match* on the Agents tab; ``False`` falls through."""
        from .agents._agent_tab_jump import (
            ensure_agent_tab_for_identity,
            restore_agent_tab,
        )
        from .navigation._agent_reveal import (
            AgentRevealFailure,
            prepare_agent_navigation_target,
            reveal_agent_navigation_target,
        )

        try:
            plan, failure = prepare_agent_navigation_target(
                self,
                match.identity,
                require_current=False,
            )
        except Exception:  # noqa: BLE001 - degrade to the visible select below
            log.debug("agents-tab link reveal unavailable", exc_info=True)
            return False
        if plan is None:
            self._link_follow_agents_tab_filtered = (
                failure is AgentRevealFailure.TARGET_FILTERED
            )
            return False
        previous_tab = ensure_agent_tab_for_identity(self, match.identity)
        try:
            outcome = reveal_agent_navigation_target(self, plan)
        except Exception:  # noqa: BLE001 - degrade to the visible select below
            log.debug("agents-tab link reveal unavailable", exc_info=True)
            restore_agent_tab(self, previous_tab)
            return False
        result = outcome.result
        if result is None:
            self._link_follow_agents_tab_filtered = (
                outcome.failure is AgentRevealFailure.TARGET_FILTERED
            )
            restore_agent_tab(self, previous_tab)
            return False
        self._save_current_tab_position()  # type: ignore[attr-defined]
        self.current_tab = "agents"
        panel_group = getattr(self, "_panel_group", None)
        if panel_group is not None:
            panel_group.focused_idx = result.panel_idx
        self._current_group_key = None
        self._expanded_panel_focus = False
        self.current_idx = result.target_idx
        self._agents_last_idx = result.target_idx
        self._agents_last_identity = result.target_identity
        self._refresh_current_tab()  # type: ignore[attr-defined]
        self.refresh_link_rail()  # type: ignore[attr-defined]
        return True

    def _select_visible_loaded_agent(self, payload: str) -> bool:
        """Select a directly visible Agents-tab row for an ``agent:`` ref.

        Legacy path for harnesses without the reveal machinery: it only
        ever matches rows the tab is already showing, so a filtered-out
        row still falls through to the remaining link-follow targets.
        """
        agents = getattr(self, "_agents", ())
        for idx, agent in enumerate(agents):
            if agent_matches_ref(agent, payload):
                self._save_current_tab_position()  # type: ignore[attr-defined]
                self.current_tab = "agents"
                self.current_idx = idx
                self._agents_last_idx = idx
                self._agents_last_identity = agent.identity
                self._refresh_current_tab()  # type: ignore[attr-defined]
                self.refresh_link_rail()  # type: ignore[attr-defined]
                return True
        return False

    def _follow_chop_link(
        self,
        payload: str,
        *,
        expanded: list[str] | None = None,
    ) -> bool:
        lumberjack, sep, base_chop = payload.partition("/")
        if not sep or not lumberjack or not base_chop:
            self._notify_dangling_link_ref(f"job:{payload}")
            return False
        lumberjack_changed = self._expand_lumberjack_for_chop(lumberjack)
        if lumberjack_changed and expanded is not None:
            expanded.append(lumberjack)
        idx = self._find_chop_index(lumberjack, base_chop)
        if idx is None:
            if lumberjack_changed:
                self._step_lumberjack_fold(lumberjack, expand=False)
            build = getattr(self, "_build_axe_items", None)
            if callable(build) and lumberjack_changed:
                build()
            self._notify_dangling_link_ref(f"job:{payload}")
            return False
        self._save_current_tab_position()  # type: ignore[attr-defined]
        self.current_tab = "services"
        self.current_idx = idx
        self._axe_last_idx = idx  # type: ignore[attr-defined]
        self._axe_last_item_key = selected_axe_item_key(  # type: ignore[attr-defined]
            self._axe_items,  # type: ignore[attr-defined]
            idx,
        )
        self._refresh_current_tab()  # type: ignore[attr-defined]
        self.refresh_link_rail()  # type: ignore[attr-defined]
        return True

    def _expand_lumberjack_for_chop(self, lumberjack: str) -> bool:
        """Reveal *lumberjack*'s chops, reporting whether that changed the fold.

        ``expand`` advances at most one rung, so a single ``collapse`` is the
        exact inverse -- which is what makes the ``Ctrl+O`` undo in
        :mod:`.link_trail` faithful rather than approximate.
        """
        changed = self._step_lumberjack_fold(lumberjack, expand=True)
        build = getattr(self, "_build_axe_items", None)
        if callable(build):
            build()
        return changed

    def _step_lumberjack_fold(self, lumberjack: str, *, expand: bool) -> bool:
        manager = getattr(self, "_axe_fold_manager", None)
        if manager is None:
            return False
        key = f"lumberjack:{lumberjack}"
        return bool(manager.expand(key) if expand else manager.collapse(key))

    def collapse_lumberjack_after_link_trail(self, lumberjack: str) -> None:
        """Undo one :meth:`_expand_lumberjack_for_chop` step."""
        self._step_lumberjack_fold(lumberjack, expand=False)
        build = getattr(self, "_build_axe_items", None)
        if callable(build):
            build()

    def _find_chop_index(self, lumberjack: str, base_chop: str) -> int | None:
        items = getattr(self, "_axe_items", ())
        snapshots = getattr(self, "_axe_chop_snapshots", {})
        for idx, item in enumerate(items):
            if not chop_matches(item, snapshots, lumberjack, base_chop):
                continue
            return idx
        return None

    def _notify_dangling_link_ref(self, ref: str) -> None:
        from ._link_follow_toast import format_link_failure

        record_link_follow_outcome("dangling")
        title, message, severity = format_link_failure("dangling", ref=ref)
        self.notify(  # type: ignore[attr-defined]
            message,
            title=title,
            severity=severity,
        )

    def _notify_missing_in_inventory(
        self,
        ref: str,
        target: ArtifactEntryTarget | None,
    ) -> None:
        from ._link_follow_toast import format_link_failure

        title, message, severity = format_link_failure(
            "missing", ref=ref, pane_label=pane_label(target)
        )
        self.notify(  # type: ignore[attr-defined]
            message,
            title=title,
            severity=severity,
        )

    def _notify_unconfigured_link_pane(
        self,
        ref: str,
        target: ArtifactEntryTarget | None,
    ) -> None:
        from ._link_follow_toast import format_link_failure

        title, message, severity = format_link_failure(
            "unconfigured", ref=ref, pane_label=pane_label(target)
        )
        self.notify(  # type: ignore[attr-defined]
            message,
            title=title,
            severity=severity,
        )


__all__ = ["LinkFollowTargetsMixin", "reveal_filtered_loaded_agent"]
