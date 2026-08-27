"""One-shot ``$`` link-follow navigation for the app-owned link graph."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from textual.events import Key
from textual.widgets import Input

from sase.ace.query.limit_token import LimitTokenError, extract_limit
from sase.artifact_ref_entries import reference_for_agent_name
from sase.core.artifact_entry_target import ArtifactEntryTarget
from sase.core.artifact_relation_layout import RelationRole

from ..artifact_tabs import artifacts_pane_contract
from ..link_rail_flag import link_rail_enabled
from ..modals.numbered_link_keys import (
    LINK_FOLLOW_PREFIX,
    arm_link_prefix,
    clear_link_prefix,
    handle_link_prefix_key,
)
from ..relations.artifact_links import parse_link_ref
from ..relations.link_index import LinkChip
from ..relations.link_keys import MAX_DIRECT_LINK_KEYS, LinkRailItem, link_rail_items
from ..tab_order import ARTIFACTS_TAB

_LINK_TRAIL_MAX = 32


@dataclass(frozen=True, slots=True)
class _LinkTrailHop:
    """One successful link-follow origin, retained for future backtracking."""

    tab: str
    pane_key: str | None
    origin: ArtifactEntryTarget | None
    query_source: str | None


class LinkFollowMixin:
    """Resolve and follow addressable link-rail chips."""

    current_tab: Any
    current_idx: int
    _pending_link_prefix: bool
    _link_trail: list[_LinkTrailHop]

    def action_follow_artifact_link(self) -> None:
        """Arm ``$`` link selection, or follow the lead chip on ``$$``."""

        if not self._link_follow_available():
            clear_link_prefix(self, LINK_FOLLOW_PREFIX)
            return
        if getattr(self, LINK_FOLLOW_PREFIX.state_attr, False):
            clear_link_prefix(self, LINK_FOLLOW_PREFIX)
            self._follow_link_number(1)
            return
        arm_link_prefix(self, LINK_FOLLOW_PREFIX)

    def _handle_link_prefix_key(self, event: Key) -> bool:
        if not getattr(self, LINK_FOLLOW_PREFIX.state_attr, False):
            if not self._link_follow_available():
                return False
        elif not self._link_follow_available():
            clear_link_prefix(self, LINK_FOLLOW_PREFIX)
            return False
        return handle_link_prefix_key(
            self,
            event,
            LINK_FOLLOW_PREFIX,
            follow=self._follow_link_number,
            on_double=lambda: self._follow_link_number(1),
            on_zero=self._open_artifact_links_panel,
        )

    def _link_follow_available(self) -> bool:
        if not link_rail_enabled():
            return False
        if isinstance(getattr(self, "focused", None), Input):
            return False
        try:
            return bool(self.link_edges_for_selection())  # type: ignore[attr-defined]
        except Exception:
            return False

    def _follow_link_number(self, number: int) -> None:
        if number < 1 or number > MAX_DIRECT_LINK_KEYS:
            return
        chips = self.link_edges_for_selection()  # type: ignore[attr-defined]
        items = link_rail_items(tuple(chips))
        if number > len(items):
            return
        self._follow_link_item(items[number - 1])

    def _follow_link_item(self, item: LinkRailItem) -> None:
        if item.count > 1:
            self._open_artifact_links_panel()
            return
        chip = item.chip
        parsed = parse_link_ref(chip.neighbor_ref)
        if parsed is None:
            self._notify_missing_link_target(chip.neighbor_ref, None)
            return
        kind, payload = parsed
        origin = self._current_link_trail_origin()
        if kind == "chop":
            if self._follow_chop_link(payload):
                self._record_link_trail(origin)
            return
        if kind == "agent" and self._follow_loaded_agent(payload):
            self._record_link_trail(origin)
            return
        target = chip.neighbor_target
        if target is None:
            self._notify_missing_link_target(chip.neighbor_ref, None)
            return
        if self._follow_artifacts_target(chip.neighbor_ref, target):
            self._record_link_trail(origin)

    def _open_artifact_links_panel(self) -> None:
        self.notify(  # type: ignore[attr-defined]
            "Links panel is not yet available",
            severity="warning",
        )

    def _current_link_trail_origin(self) -> _LinkTrailHop:
        tab = str(getattr(self, "current_tab", ""))
        pane_key: str | None = None
        origin: ArtifactEntryTarget | None = None
        query_source: str | None = None
        if tab == ARTIFACTS_TAB:
            pane_key = str(getattr(self, "current_artifacts_pane_key", ""))
            pane = self._artifacts_entry_navigator()  # type: ignore[attr-defined]
            if pane is not None:
                origin = pane.selected_entry_target()
                query_source = _pane_limit_query(pane)
        elif tab == "agents":
            agent = self._get_selected_agent()  # type: ignore[attr-defined]
            name = getattr(agent, "name", None) if agent is not None else None
            if isinstance(name, str) and name:
                origin = ArtifactEntryTarget("agents", (name,))
        return _LinkTrailHop(
            tab=tab,
            pane_key=pane_key or None,
            origin=origin,
            query_source=query_source,
        )

    def _record_link_trail(self, hop: _LinkTrailHop) -> None:
        trail = getattr(self, "_link_trail", None)
        if not isinstance(trail, list):
            trail = []
            self._link_trail = trail
        trail.append(hop)
        if len(trail) > _LINK_TRAIL_MAX:
            del trail[: len(trail) - _LINK_TRAIL_MAX]

    def _follow_artifacts_target(self, ref: str, target: ArtifactEntryTarget) -> bool:
        if self._select_current_artifacts_target(target):
            return True
        project = _target_project_scope(target)
        if project is not None and project != getattr(
            self, "artifacts_project_scope", None
        ):
            self._set_artifacts_project_scope(  # type: ignore[attr-defined]
                project,
                picked=True,
            )
        if self.current_tab != ARTIFACTS_TAB:
            self._save_current_tab_position()  # type: ignore[attr-defined]
            self.current_tab = ARTIFACTS_TAB
        if self._request_artifacts_target(target):
            return True
        pane = self._artifacts_entry_navigator(target.pane_id)  # type: ignore[attr-defined]
        if pane is None or _pane_is_loading(pane):
            return False
        if self._drop_head_slice_limit(pane, ref, target):
            if self._request_artifacts_target(target):
                return True
        if pane.reveal_entry_target(target, role=RelationRole.FAMILY):
            return True
        if self._request_artifacts_target(target):
            return True
        self._notify_missing_link_target(ref, target)
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

    def _request_artifacts_target(self, target: ArtifactEntryTarget) -> bool:
        request = getattr(self, "_request_artifacts_entry", None)
        selected = bool(request(target)) if callable(request) else False
        pane = self._artifacts_entry_navigator(target.pane_id)  # type: ignore[attr-defined]
        return bool(
            selected or (pane is not None and pane.selected_entry_target() == target)
        )

    def _drop_head_slice_limit(
        self,
        pane: Any,
        ref: str,
        target: ArtifactEntryTarget,
    ) -> bool:
        query = _pane_limit_query(pane)
        apply = getattr(pane, "apply_host_limit_query", None)
        if query is None or not callable(apply):
            return False
        try:
            remainder, cap = extract_limit(query)
        except LimitTokenError:
            return False
        if cap is None:
            return False
        rewritten = _limit_all_query(remainder)
        try:
            apply(rewritten, grow=True)
        except TypeError:
            apply(rewritten)
        self.notify(  # type: ignore[attr-defined]
            f"Expanded {_pane_label(target)} limit to show linked {ref}",
        )
        return True

    def _follow_loaded_agent(self, payload: str) -> bool:
        agents = getattr(self, "_agents", ())
        for idx, agent in enumerate(agents):
            if _agent_matches_ref(agent, payload):
                self._save_current_tab_position()  # type: ignore[attr-defined]
                self.current_tab = "agents"
                self.current_idx = idx
                self._agents_last_idx = idx  # type: ignore[attr-defined]
                self._agents_last_identity = agent.identity  # type: ignore[attr-defined]
                self._refresh_current_tab()  # type: ignore[attr-defined]
                self.refresh_link_rail()  # type: ignore[attr-defined]
                return True
        return False

    def _follow_chop_link(self, payload: str) -> bool:
        lumberjack, sep, base_chop = payload.partition("/")
        if not sep or not lumberjack or not base_chop:
            self._notify_missing_link_target(f"chop:{payload}", None)
            return False
        self._expand_lumberjack_for_chop(lumberjack)
        idx = self._find_chop_index(lumberjack, base_chop)
        if idx is None:
            self._notify_missing_link_target(f"chop:{payload}", None)
            return False
        from .axe_display._loader_items import selected_axe_item_key

        self._save_current_tab_position()  # type: ignore[attr-defined]
        self.current_tab = "axe"
        self.current_idx = idx
        self._axe_last_idx = idx  # type: ignore[attr-defined]
        self._axe_last_item_key = selected_axe_item_key(  # type: ignore[attr-defined]
            self._axe_items,  # type: ignore[attr-defined]
            idx,
        )
        self._refresh_current_tab()  # type: ignore[attr-defined]
        self.refresh_link_rail()  # type: ignore[attr-defined]
        return True

    def _expand_lumberjack_for_chop(self, lumberjack: str) -> None:
        manager = getattr(self, "_axe_fold_manager", None)
        if manager is not None:
            manager.expand(f"lumberjack:{lumberjack}")
        build = getattr(self, "_build_axe_items", None)
        if callable(build):
            build()

    def _find_chop_index(self, lumberjack: str, base_chop: str) -> int | None:
        items = getattr(self, "_axe_items", ())
        snapshots = getattr(self, "_axe_chop_snapshots", {})
        for idx, item in enumerate(items):
            if not _chop_matches(item, snapshots, lumberjack, base_chop):
                continue
            return idx
        return None

    def _notify_missing_link_target(
        self,
        ref: str,
        target: ArtifactEntryTarget | None,
    ) -> None:
        self.notify(  # type: ignore[attr-defined]
            f"Linked target {ref} is not visible in {_pane_label(target)}",
            severity="warning",
        )


def _pane_limit_query(pane: Any) -> str | None:
    getter = getattr(pane, "host_limit_query", None)
    if not callable(getter):
        return None
    return str(getter())


def _limit_all_query(remainder: str) -> str:
    stripped = remainder.strip()
    if not stripped:
        return "limit:all"
    return f"{stripped} limit:all"


def _target_project_scope(target: ArtifactEntryTarget) -> str | None:
    contract = artifacts_pane_contract(target.pane_id)
    project_scoped = (
        contract.project_scoping
        if contract is not None
        else target.pane_id in {"patches", "beads"}
    )
    if project_scoped and target.parts:
        return target.parts[0] or None
    return None


def _pane_is_loading(pane: Any) -> bool:
    return bool(
        getattr(pane, "_loading", False) or getattr(pane, "_loading_full", False)
    )


def _pane_label(target: ArtifactEntryTarget | None) -> str:
    if target is None:
        return "the destination pane"
    from ..artifact_tabs import descriptor_for_artifacts_pane_id

    descriptor = descriptor_for_artifacts_pane_id(target.pane_id)
    return descriptor.label if descriptor is not None else target.pane_id


def _agent_matches_ref(agent: Any, payload: str) -> bool:
    payload_key = payload.casefold()
    for name in _agent_candidate_names(agent):
        if name.casefold() == payload_key:
            return True
        ref = reference_for_agent_name(name)
        parsed = parse_link_ref("" if ref is None else ref)
        if parsed is not None and parsed == ("agent", payload):
            return True
    return False


def _agent_candidate_names(agent: Any) -> tuple[str, ...]:
    names: list[str] = []
    for attr in (
        "name",
        "agent_name",
        "presented_agent_name",
        "presented_identity_name",
        "display_name",
        "cl_name",
    ):
        value = getattr(agent, attr, None)
        if isinstance(value, str) and value:
            names.append(value)
    for method_name in (
        "family_reference_name",
        "presented_family_reference_name",
        "presented_clan_reference_name",
    ):
        method = getattr(agent, method_name, None)
        if not callable(method):
            continue
        value = method()
        if isinstance(value, str) and value:
            names.append(value)
    return tuple(dict.fromkeys(names))


def _chop_matches(
    item: Any,
    snapshots: Any,
    lumberjack: str,
    base_chop: str,
) -> bool:
    from ..widgets.bgcmd_list import ChopItem

    if not isinstance(item, ChopItem) or item.lumberjack_name != lumberjack:
        return False
    if item.chop_name == base_chop:
        return True
    snapshot = snapshots.get((item.lumberjack_name, item.chop_name))
    return bool(
        snapshot is not None and snapshot.base_identity == (lumberjack, base_chop)
    )


__all__ = ["LinkFollowMixin"]
