"""App-level back/forward walking of the link trail across tabs.

:mod:`.link_follow` records a :class:`~.link_follow.LinkTrailHop` origin on
every successful ``$`` jump. This module is the other half: it walks that
trail with ``Ctrl+O``/``Ctrl+Shift+O`` (bead:sase-ug.8), restoring whichever
tab, pane, project scope, and pane query the origin needs, and renders the
breadcrumb chip that makes the trail visible on the rail.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any

from ..relations.artifact_links import parse_link_ref
from ..relations.link_keys import short_ref_label
from ..relations.link_subject import accent_and_icon_for_ref, ref_for_target
from ..tab_order import ARTIFACTS_TAB
from ..widgets.artifacts.entry_navigation import LinkRequestState
from .axe_display._loader_items import find_axe_item_idx
from .link_follow import LinkTrailHop

if TYPE_CHECKING:
    from .axe_display._loader_state import AxeItemKey

_LINK_TRAIL_MAX = 32
_AXE_ICON = "⚒"
_UNKNOWN_ICON = "•"


class LinkTrailMixin:
    """Walk ``_link_trail`` back and forward, and clear it on other moves."""

    current_tab: Any
    current_idx: int
    _link_trail: list[LinkTrailHop]
    _link_trail_forward: list[LinkTrailHop]
    _link_trail_guard: bool
    _axe_last_idx: int
    _axe_last_item_key: AxeItemKey | None

    def _walk_link_trail_back(self) -> bool:
        """Pop the most recent link-follow origin and land back on it."""
        return self._walk_link_trail(
            self._link_trail,
            self._link_trail_forward,
            undo_fold=True,
        )

    def _walk_link_trail_forward(self) -> bool:
        """Redo a link-follow origin previously undone by ``Ctrl+O``."""
        return self._walk_link_trail(self._link_trail_forward, self._link_trail)

    def _walk_link_trail(
        self,
        source: list[LinkTrailHop],
        other: list[LinkTrailHop],
        *,
        undo_fold: bool = False,
    ) -> bool:
        if not source:
            return False
        hop = source.pop()
        current = self._current_link_trail_origin()  # type: ignore[attr-defined]
        # The expansion belongs to the pair of positions, not to one of them,
        # so it rides along with whichever entry is being pushed. Without this
        # a back / forward / back sequence would leave the tree expanded.
        other.append(replace(current, axe_fold_expanded=hop.axe_fold_expanded))
        if undo_fold and hop.axe_fold_expanded:
            collapse = getattr(self, "collapse_lumberjack_after_link_trail", None)
            if callable(collapse):
                collapse(hop.axe_fold_expanded)
        if len(other) > _LINK_TRAIL_MAX:
            del other[: len(other) - _LINK_TRAIL_MAX]
        self._link_trail_guard = True
        try:
            landed = self._restore_link_trail_hop(hop)
        finally:
            self._link_trail_guard = False
        if not landed:
            notify = getattr(self, "notify", None)
            if callable(notify):
                notify(
                    "That link-trail position is no longer available",
                    severity="warning",
                )
        refresh = getattr(self, "_refresh_after_entry_jump_restore", None)
        if callable(refresh):
            refresh()
        rail = getattr(self, "refresh_link_rail", None)
        if callable(rail):
            rail()
        return True

    def _restore_link_trail_hop(self, hop: LinkTrailHop) -> bool:
        if hop.tab == ARTIFACTS_TAB:
            return self._restore_artifacts_link_trail_hop(hop)
        if hop.tab == "agents":
            return self._restore_agents_link_trail_hop(hop)
        if hop.tab == "axe":
            return self._restore_axe_link_trail_hop(hop)
        return False

    def _restore_artifacts_link_trail_hop(self, hop: LinkTrailHop) -> bool:
        if hop.project_scope != getattr(self, "artifacts_project_scope", None):
            set_scope = getattr(self, "_set_artifacts_project_scope", None)
            if callable(set_scope):
                set_scope(hop.project_scope, picked=False)
        if self.current_tab != ARTIFACTS_TAB:
            self._save_current_tab_position()  # type: ignore[attr-defined]
            self.current_tab = ARTIFACTS_TAB
        if hop.pane_key is not None and hop.query_source is not None:
            pane = self._artifacts_entry_navigator(hop.pane_key)  # type: ignore[attr-defined]
            apply_query = (
                getattr(pane, "apply_host_limit_query", None)
                if pane is not None
                else None
            )
            if callable(apply_query):
                apply_query(hop.query_source)
        if hop.origin is None:
            return True
        request = getattr(self, "_request_artifacts_entry", None)
        if not callable(request):
            return False
        return request(hop.origin) is LinkRequestState.SELECTED

    def _restore_agents_link_trail_hop(self, hop: LinkTrailHop) -> bool:
        name = (
            hop.origin.parts[0] if hop.origin is not None and hop.origin.parts else ""
        )
        if not name:
            return False
        agents = getattr(self, "_agents", ())
        for idx, agent in enumerate(agents):
            if getattr(agent, "agent_name", None) != name:
                continue
            if self.current_tab != "agents":
                self._save_current_tab_position()  # type: ignore[attr-defined]
                self.current_tab = "agents"
            self.current_idx = idx
            self._agents_last_idx = idx  # type: ignore[attr-defined]
            self._agents_last_identity = agent.identity  # type: ignore[attr-defined]
            return True
        return False

    def _restore_axe_link_trail_hop(self, hop: LinkTrailHop) -> bool:
        if hop.axe_key is None:
            return False
        if hop.axe_key[0] == "chop":
            expand = getattr(self, "_expand_lumberjack_for_chop", None)
            if callable(expand):
                expand(hop.axe_key[1])
        idx = find_axe_item_idx(getattr(self, "_axe_items", []), hop.axe_key)
        if idx is None:
            return False
        if self.current_tab != "axe":
            self._save_current_tab_position()  # type: ignore[attr-defined]
            self.current_tab = "axe"
        self.current_idx = idx
        self._axe_last_idx = idx
        self._axe_last_item_key = hop.axe_key
        return True

    def _clear_link_trail_if_unguarded(self) -> None:
        """Drop the link trail once the user navigates by any other means.

        Also cancels any still-open link-follow transaction, so a pane's
        later async resolution (a stale generation) is silently ignored
        instead of producing a trail hop or toast for a follow the user has
        already navigated away from.
        """
        if getattr(self, "_link_trail_guard", False):
            return
        trail = getattr(self, "_link_trail", None)
        if trail:
            trail.clear()
        forward = getattr(self, "_link_trail_forward", None)
        if forward:
            forward.clear()
        cancel = getattr(self, "_cancel_link_follow_transaction", None)
        if callable(cancel):
            cancel()

    def _note_artifacts_selection_for_link_trail(self) -> None:
        """Clear the trail only when the selected Artifacts row really moved.

        Non-navigation events (marking a row, toggling a filter) also sync
        the footer through the same path a real row change does, so this
        compares against the previously observed selection instead of
        clearing unconditionally.
        """
        pane = self._artifacts_entry_navigator()  # type: ignore[attr-defined]
        target = pane.selected_entry_target() if pane is not None else None
        selection = (getattr(self, "current_artifacts_pane_key", None), target)
        last = getattr(self, "_link_trail_last_artifacts_selection", None)
        self._link_trail_last_artifacts_selection = selection
        if last is not None and last != selection:
            self._clear_link_trail_if_unguarded()


def link_trail_breadcrumb_text(app: Any) -> str | None:
    """Return the leading breadcrumb chip text, or ``None`` with an empty trail.

    Pure and Textual-free like :mod:`.link_subject`, so it is unit-testable
    against a small duck-typed stand-in for the app.
    """

    trail = getattr(app, "_link_trail", None)
    if not trail:
        return None
    icon, label = _hop_icon_and_label(trail[-1])
    chip = f"{icon} {label}".strip()
    if len(trail) > 1:
        return f"⟨ …{len(trail) - 1} › {chip} ⟩"
    return f"⟨ {chip} ⟩"


def _hop_icon_and_label(hop: LinkTrailHop) -> tuple[str, str]:
    axe_key = hop.axe_key
    if hop.tab == "axe" and axe_key is not None:
        if axe_key[0] == "chop":
            return _AXE_ICON, f"{axe_key[1]}/{axe_key[2]}"
        if axe_key[0] == "lumberjack":
            return _AXE_ICON, axe_key[1]
        return _AXE_ICON, f"bg:{axe_key[1]}"
    if hop.origin is not None:
        ref = ref_for_target(hop.origin)
        if ref is not None:
            parsed = parse_link_ref(ref)
            ref_kind = parsed[0] if parsed is not None else ""
            _, icon = accent_and_icon_for_ref(ref_kind, hop.origin)
            return icon, short_ref_label(ref)
    return _UNKNOWN_ICON, hop.pane_key or hop.tab or "entry"


__all__ = ["LinkTrailMixin", "link_trail_breadcrumb_text"]
