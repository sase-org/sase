"""One-shot ``$`` link-follow navigation for the app-owned link graph."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from textual.events import Key
from textual.widgets import Input

from sase.ace.query.limit_token import LimitTokenError, extract_limit
from sase.artifact_ref_entries import reference_for_agent_name
from sase.core.artifact_entry_target import ArtifactEntryTarget
from sase.core.artifact_relation_layout import RelationRole

from ..artifact_tabs import artifacts_pane_contract
from ..modals.numbered_link_keys import (
    LINK_FOLLOW_PREFIX,
    arm_link_prefix,
    clear_link_prefix,
    handle_link_prefix_key,
)
from ..relations.artifact_links import parse_link_ref
from ..relations.link_index import LinkChip
from ..relations.link_keys import (
    MAX_DIRECT_LINK_KEYS,
    LinkRailItem,
    link_item_chips,
    link_rail_items,
)
from ..relations.link_subject import selected_link_subject
from ..tab_order import ARTIFACTS_TAB
from .axe_display._loader_items import selected_axe_item_key

if TYPE_CHECKING:
    from .axe_display._loader_state import AxeItemKey

_LINK_TRAIL_MAX = 32


@dataclass(frozen=True, slots=True)
class LinkTrailHop:
    """One successful link-follow origin, retained for future backtracking."""

    tab: str
    pane_key: str | None
    origin: ArtifactEntryTarget | None
    query_source: str | None
    project_scope: str | None = None
    axe_key: AxeItemKey | None = None
    #: Lumberjack this hop's forward jump had to expand to reveal its chop,
    #: recorded so walking back can put the AXE tree back the way it was.
    axe_fold_expanded: str | None = None


class LinkFollowMixin:
    """Resolve and follow addressable link-rail chips."""

    current_tab: Any
    current_idx: int
    _pending_link_prefix: bool
    _link_trail: list[LinkTrailHop]
    _link_trail_forward: list[LinkTrailHop]
    _link_trail_guard: bool

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
        if isinstance(getattr(self, "focused", None), Input):
            return False
        try:
            available = getattr(self, "link_follow_available_for_selection", None)
            if callable(available):
                return bool(available())
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
            self._open_artifact_links_panel(item)
            return
        self._follow_single_link_chip(item.chip)

    def _follow_single_link_chip(self, chip: LinkChip) -> None:
        parsed = parse_link_ref(chip.neighbor_ref)
        if parsed is None:
            self._notify_missing_link_target(chip.neighbor_ref, None)
            return
        kind, payload = parsed
        origin = self._current_link_trail_origin()
        self._link_trail_guard = True
        try:
            if kind == "chop":
                expanded: list[str] = []
                if self._follow_chop_link(payload, expanded=expanded):
                    self._record_link_trail(
                        replace(
                            origin,
                            axe_fold_expanded=expanded[0] if expanded else None,
                        )
                    )
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
        finally:
            self._link_trail_guard = False

    def _open_artifact_links_panel(
        self, scope_item: LinkRailItem | None = None
    ) -> None:
        chips = tuple(self.link_edges_for_selection())  # type: ignore[attr-defined]
        subject_for_selection = getattr(self, "link_subject_for_selection", None)
        subject = (
            subject_for_selection()
            if callable(subject_for_selection)
            else selected_link_subject(self)
        )
        if subject is None or not chips:
            self.notify(  # type: ignore[attr-defined]
                "No links for the current selection",
                severity="warning",
            )
            return
        panel_chips = (
            link_item_chips(chips, scope_item) if scope_item is not None else chips
        )
        if not panel_chips:
            self.notify(  # type: ignore[attr-defined]
                "No links for the current selection",
                severity="warning",
            )
            return
        from ..modals.artifact_links_panel_modal import (
            ArtifactLinksPanelModal,
            ArtifactLinksPanelResult,
        )

        subject_ref = subject.ref

        def _on_result(result: ArtifactLinksPanelResult | None) -> None:
            if result is None:
                return
            if result.action == "follow" and result.chip is not None:
                self._follow_single_link_chip(result.chip)
                return
            if result.action == "add":
                add = getattr(self, "action_artifacts_link_marked", None)
                if callable(add):
                    add()
                else:
                    self.notify(  # type: ignore[attr-defined]
                        "Artifact link authoring is unavailable",
                        severity="warning",
                    )
                return
            if result.action == "remove" and result.chip is not None:
                self._remove_artifact_link_chip(subject_ref, result.chip)

        initial_notice = _cached_link_panel_staleness_notice(self)
        modal = ArtifactLinksPanelModal(
            subject_ref=subject_ref,
            chips=panel_chips,
            scoped_label=_scope_label(scope_item) if scope_item is not None else None,
            add_enabled=_artifact_link_add_enabled(self),
            staleness_notice=initial_notice,
        )
        push_screen = getattr(self, "push_screen", None)
        if not callable(push_screen):
            self.notify(  # type: ignore[attr-defined]
                "Links panel is unavailable",
                severity="warning",
            )
            return
        push_screen(modal, _on_result)
        self._schedule_artifact_links_panel_staleness_refresh(
            modal,
            initial_notice=initial_notice,
        )

    def _remove_artifact_link_chip(self, subject_ref: str, chip: LinkChip) -> None:
        if not chip.writable:
            self.notify(  # type: ignore[attr-defined]
                f"Cannot remove {_readonly_link_source(chip)} link from the store",
                severity="warning",
            )
            return
        source_ref, target_ref = _link_chip_endpoints(subject_ref, chip)

        async def _runner() -> None:
            try:
                outcome = await asyncio.to_thread(
                    _remove_artifact_link,
                    source_ref,
                    target_ref,
                    chip.relation,
                )
            except Exception as exc:  # noqa: BLE001 - surfaced as a TUI notification
                self.notify(str(exc), severity="error")  # type: ignore[attr-defined]
                return
            removed = tuple(outcome.get("rows") or ())
            count = len(removed)
            plural = "" if count == 1 else "s"
            self.notify(  # type: ignore[attr-defined]
                f"removed {count} {chip.relation} link{plural} "
                f"@{source_ref} -> @{target_ref}"
            )
            refresh = getattr(self, "_request_active_artifacts_refresh", None)
            if callable(refresh):
                refresh()
            refresh_links = getattr(self, "_schedule_link_index_refresh", None)
            if callable(refresh_links):
                refresh_links(source="artifact_link_remove")

        from ..util.pump_tasks import spawn_pump_free_task

        task = spawn_pump_free_task(
            self,
            _runner(),
            name="sase-artifacts-link-remove",
            registry_attr="_pump_free_async_tasks",
        )
        if task is None:
            self.notify(  # type: ignore[attr-defined]
                "Unable to start artifact link removal",
                severity="error",
            )

    def _schedule_artifact_links_panel_staleness_refresh(
        self,
        modal: Any,
        *,
        initial_notice: str,
    ) -> None:
        async def _runner() -> None:
            notice = await asyncio.to_thread(_artifact_link_index_drift_notice)
            update = getattr(modal, "update_staleness_notice", None)
            if callable(update):
                update(_combine_notices(initial_notice, notice))

        from ..util.pump_tasks import spawn_pump_free_task

        spawn_pump_free_task(
            self,
            _runner(),
            name="sase-artifacts-link-panel-staleness",
            registry_attr="_link_rail_tasks",
        )

    def _current_link_trail_origin(self) -> LinkTrailHop:
        tab = str(getattr(self, "current_tab", ""))
        pane_key: str | None = None
        origin: ArtifactEntryTarget | None = None
        query_source: str | None = None
        project_scope: str | None = None
        axe_key: AxeItemKey | None = None
        if tab == ARTIFACTS_TAB:
            pane_key = str(getattr(self, "current_artifacts_pane_key", ""))
            pane = self._artifacts_entry_navigator()  # type: ignore[attr-defined]
            if pane is not None:
                origin = pane.selected_entry_target()
                query_source = _pane_limit_query(pane)
            project_scope = getattr(self, "artifacts_project_scope", None)
        elif tab == "agents":
            agent = self._get_selected_agent()  # type: ignore[attr-defined]
            name = getattr(agent, "agent_name", None) if agent is not None else None
            if isinstance(name, str) and name:
                origin = ArtifactEntryTarget("agents", (name,))
        elif tab == "axe":
            axe_key = selected_axe_item_key(
                getattr(self, "_axe_items", []),
                getattr(self, "current_idx", -1),
            )
        return LinkTrailHop(
            tab=tab,
            pane_key=pane_key or None,
            origin=origin,
            query_source=query_source,
            project_scope=project_scope,
            axe_key=axe_key,
        )

    def _record_link_trail(self, hop: LinkTrailHop) -> None:
        trail = getattr(self, "_link_trail", None)
        if not isinstance(trail, list):
            trail = []
            self._link_trail = trail
        trail.append(hop)
        if len(trail) > _LINK_TRAIL_MAX:
            del trail[: len(trail) - _LINK_TRAIL_MAX]
        forward = getattr(self, "_link_trail_forward", None)
        if isinstance(forward, list):
            forward.clear()

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

    def _follow_chop_link(
        self,
        payload: str,
        *,
        expanded: list[str] | None = None,
    ) -> bool:
        lumberjack, sep, base_chop = payload.partition("/")
        if not sep or not lumberjack or not base_chop:
            self._notify_missing_link_target(f"chop:{payload}", None)
            return False
        if self._expand_lumberjack_for_chop(lumberjack) and expanded is not None:
            expanded.append(lumberjack)
        idx = self._find_chop_index(lumberjack, base_chop)
        if idx is None:
            self._notify_missing_link_target(f"chop:{payload}", None)
            return False
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


def _artifact_link_add_enabled(app: Any) -> bool:
    if getattr(app, "current_tab", None) != ARTIFACTS_TAB:
        return False
    return str(getattr(app, "current_artifacts_pane_key", "")) != "patches"


def _cached_link_panel_staleness_notice(app: Any) -> str:
    notices: list[str] = []
    loading = bool(getattr(app, "_link_index_loading", False))
    if loading and getattr(app, "_link_index", None) is not None:
        notices.append("Link index refresh in progress; showing the previous index.")
    elif loading:
        notices.append("Link index refresh in progress.")
    errors = tuple(str(error) for error in getattr(app, "_link_index_errors", ()))
    if errors:
        joined = "; ".join(errors[:3])
        suffix = "" if len(errors) <= 3 else f"; +{len(errors) - 3} more"
        notices.append(f"Some project link indexes were skipped: {joined}{suffix}")
    return "\n".join(notices)


def _artifact_link_index_drift_notice() -> str:
    try:
        from sase.artifact_cli.link_health import inspect_artifact_link_health
        from sase.sdd.artifact_link_drift import format_artifact_link_index_drift

        report = inspect_artifact_link_health(fix=False)
    except Exception as exc:  # noqa: BLE001 - panel notice, not modal failure
        return f"Index drift unavailable: {exc}"
    if report.skipped:
        return ""
    if report.errors:
        joined = "; ".join(report.errors[:3])
        suffix = "" if len(report.errors) <= 3 else f"; +{len(report.errors) - 3} more"
        return f"Index drift unavailable: {joined}{suffix}"
    if not report.aggregate_drift.has_drift:
        return ""
    return f"Index stale: {format_artifact_link_index_drift(report.aggregate_drift)}"


def _combine_notices(*notices: str) -> str:
    return "\n".join(notice for notice in notices if notice)


def _scope_label(item: LinkRailItem | None) -> str:
    if item is None:
        return ""
    if item.projected_group:
        return f"{item.count} {_plural_kind(item.neighbor_kind)}"
    return item.chip.label


def _plural_kind(kind: str) -> str:
    if kind == "stitch":
        return "stitches"
    if kind.endswith("s"):
        return kind
    return f"{kind}s" if kind else "links"


def _readonly_link_source(chip: LinkChip) -> str:
    if chip.origin == "projected" and chip.created_by.startswith("projection:"):
        return chip.created_by
    return chip.origin or "read-only"


def _link_chip_endpoints(subject_ref: str, chip: LinkChip) -> tuple[str, str]:
    if chip.this_is_source:
        return subject_ref, chip.neighbor_ref
    return chip.neighbor_ref, subject_ref


def _remove_artifact_link(
    source_ref: str,
    target_ref: str,
    relation: str,
) -> dict[str, Any]:
    from sase.artifact_cli.link_ops import remove_artifact_link

    return remove_artifact_link(
        source_ref=source_ref,
        target_ref=target_ref,
        relation=relation,
    )


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


__all__ = ["LinkFollowMixin", "LinkTrailHop"]
