"""One-shot ``$`` link-follow navigation for the app-owned link graph.

Missing-target follows walk a host-owned reveal ladder. Fold expansion
runs before any query rewrite -- it is strictly cheaper and the phase's
test invariant prefers it over a ``limit:`` drop -- then the head-slice
drop, an identity-field query, minimal widening, and a blunt
``limit:all`` neutral query. Every rewrite commits through the pane's
host-query adapter so query history records exactly one ``^`` restore.

When every rung misses, one final acquisition step -- targeted hydration
-- gets a row the pane never fetched at all (a deep-archive plan, a
stitch outside the collection window, a capped provider snapshot)
directly from its source, off the message pump, before falling back to
the honest "not in this pane's inventory" toast. It fires at most once
per transaction and never for a ref that failed to parse or route.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any

from textual.events import Key
from textual.widgets import Input

from sase.ace.link_reveal import LinkReveal

from ..modals.numbered_link_keys import (
    LINK_FOLLOW_PREFIX,
    arm_link_prefix,
    clear_link_prefix,
    handle_link_prefix_key,
)
from ..relations.artifact_links import parse_link_ref, target_for_ref_kind
from ..relations.link_index import LinkChip
from ..relations.link_keys import (
    MAX_DIRECT_LINK_KEYS,
    LinkRailItem,
    link_item_chips,
    link_rail_items,
)
from ..relations.link_subject import selected_link_subject
from ._link_follow_helpers import (
    artifact_link_add_enabled,
    artifact_link_index_drift_notice,
    cached_link_panel_staleness_notice,
    combine_notices,
    link_chip_endpoints,
    link_panel_reveal_flags,
    pane_is_loading,
    readonly_link_source,
    remove_artifact_link,
    scope_label,
)
from ._link_follow_targets import LinkFollowTargetsMixin
from ._link_follow_transaction import LinkFollowTransactionMixin
from ._link_follow_trail_state import LinkFollowTrailStateMixin
from ._link_follow_types import (
    LinkFollowTransaction,
    LinkTrailHop,
    _link_follow_outcomes,
)


class _LinkFollowPanelMixin:
    """Open and handle the expanded links panel."""

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
        reveal_flags = link_panel_reveal_flags(self, panel_chips)

        def _on_result(result: ArtifactLinksPanelResult | None) -> None:
            if result is None:
                return
            if result.action == "follow" and result.chip is not None:
                self._follow_single_link_chip(result.chip)  # type: ignore[attr-defined]
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

        initial_notice = cached_link_panel_staleness_notice(self)
        modal = ArtifactLinksPanelModal(
            subject_ref=subject_ref,
            chips=panel_chips,
            scoped_label=scope_label(scope_item) if scope_item is not None else None,
            add_enabled=artifact_link_add_enabled(self),
            staleness_notice=initial_notice,
            reveal_flags=reveal_flags,
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
                f"Cannot remove {readonly_link_source(chip)} link from the store",
                severity="warning",
            )
            return
        source_ref, target_ref = link_chip_endpoints(subject_ref, chip)

        async def _runner() -> None:
            try:
                outcome = await asyncio.to_thread(
                    remove_artifact_link,
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
            notice = await asyncio.to_thread(artifact_link_index_drift_notice)
            update = getattr(modal, "update_staleness_notice", None)
            if callable(update):
                update(combine_notices(initial_notice, notice))

        from ..util.pump_tasks import spawn_pump_free_task

        spawn_pump_free_task(
            self,
            _runner(),
            name="sase-artifacts-link-panel-staleness",
            registry_attr="_link_rail_tasks",
        )


class LinkFollowMixin(
    _LinkFollowPanelMixin,
    LinkFollowTrailStateMixin,
    LinkFollowTargetsMixin,
    LinkFollowTransactionMixin,
):
    """Resolve and follow addressable link-rail chips."""

    current_tab: Any
    current_idx: int
    _pending_link_prefix: bool
    _link_trail: list[LinkTrailHop]
    _link_trail_forward: list[LinkTrailHop]
    _link_trail_guard: bool
    _link_follow_generation: int
    _link_follow_transaction: LinkFollowTransaction | None
    _link_follow_dispatching: bool
    _link_reveals: dict[str, LinkReveal]
    _link_hydration_waiters: dict[tuple[str, str], int]
    _link_hydration_in_flight: set[tuple[str, str]]

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
            self._notify_dangling_link_ref(chip.neighbor_ref)
            return
        kind, payload = parsed
        origin = self._current_link_trail_origin()
        # A new follow supersedes whatever the previous one left open, so a
        # late resolution for it is ignored rather than producing a stale
        # trail hop or toast.
        self._cancel_link_follow_transaction()
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
                target = target_for_ref_kind(kind, payload, project_hint=None)
                if target is None:
                    self._notify_dangling_link_ref(chip.neighbor_ref)
                    return
            self._follow_artifacts_target(chip.neighbor_ref, target, origin)
        finally:
            self._link_trail_guard = False


__all__ = ["LinkFollowMixin", "LinkTrailHop"]
