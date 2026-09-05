"""Target resolution and non-artifacts destinations for ``$`` link-follow."""

from __future__ import annotations

from typing import Any

from sase.core.artifact_entry_target import ArtifactEntryTarget

from ..relations.artifact_links import parse_link_ref, target_for_ref_kind
from ..tab_order import ARTIFACTS_TAB
from ..widgets.artifacts.entry_navigation import LinkRequestState
from ._link_follow_helpers import (
    agent_matches_ref,
    chop_matches,
    pane_label,
    target_project_scope,
)
from ._link_follow_types import LinkTrailHop, record_link_follow_outcome
from .axe_display._loader_items import selected_axe_item_key


class LinkFollowTargetsMixin:
    """Resolve destinations and select loaded target rows."""

    current_tab: Any
    current_idx: int
    _link_follow_dispatching: bool

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
        """
        target = self._resolve_link_follow_target(ref, chip_target)
        if self._select_current_artifacts_target(target):
            record_link_follow_outcome("select")
            self._record_link_trail(origin)  # type: ignore[attr-defined]
            return
        project = target_project_scope(target)
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
        generation = self._begin_link_follow_transaction(  # type: ignore[attr-defined]
            ref,
            target,
            origin,
        )
        state = self._request_artifacts_target(target, generation=generation)
        handle = self._handle_link_follow_outcome  # type: ignore[attr-defined]
        handle(generation, state)

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
        synchronous report through :meth:`_complete_link_follow_request` is a
        no-op; the resolved state returned here is what the caller (this
        method's own caller, not the pane) uses to finalize instead.
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
        try:
            return request(target, generation=generation)
        finally:
            self._link_follow_dispatching = False

    def _follow_loaded_agent(self, payload: str) -> bool:
        agents = getattr(self, "_agents", ())
        for idx, agent in enumerate(agents):
            if agent_matches_ref(agent, payload):
                self._save_current_tab_position()  # type: ignore[attr-defined]
                self.current_tab = "agents"
                self.current_idx = idx
                self._agents_last_idx = idx  # type: ignore[attr-defined]
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
            self._notify_dangling_link_ref(f"chop:{payload}")
            return False
        if self._expand_lumberjack_for_chop(lumberjack) and expanded is not None:
            expanded.append(lumberjack)
        idx = self._find_chop_index(lumberjack, base_chop)
        if idx is None:
            self._notify_dangling_link_ref(f"chop:{payload}")
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
            if not chop_matches(item, snapshots, lumberjack, base_chop):
                continue
            return idx
        return None

    def _notify_dangling_link_ref(self, ref: str) -> None:
        record_link_follow_outcome("dangling")
        self.notify(  # type: ignore[attr-defined]
            f"No such artifact: {ref}",
            severity="warning",
        )

    def _notify_missing_in_inventory(
        self,
        ref: str,
        target: ArtifactEntryTarget | None,
    ) -> None:
        self.notify(  # type: ignore[attr-defined]
            f"{pane_label(target)} has no {ref} in its inventory",
            severity="warning",
        )


__all__ = ["LinkFollowTargetsMixin"]
