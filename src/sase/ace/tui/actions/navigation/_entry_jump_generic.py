"""Generic entry-jump history helpers for non-Agents tabs."""

from __future__ import annotations

from typing import Literal, cast

from ._types import NavigationMixinBase
from .jump_hints import EntryJumpAnchor


class EntryJumpGenericHistoryMixin(NavigationMixinBase):
    """Mixin providing non-Agents entry-jump anchor history."""

    def _entry_jump_index_stack_for_current_tab(self) -> list[EntryJumpAnchor]:
        """Return the current non-Agents tab's jump-back stack."""
        return self._entry_jump_index_stack.setdefault(self.current_tab, [])

    def _entry_jump_forward_stack_map(self) -> dict[str, list[EntryJumpAnchor]]:
        """Return the non-Agents tab forward stacks, creating them for old harnesses."""
        stacks = getattr(self, "_entry_jump_forward_index_stack", None)
        if stacks is None:
            stacks = {}
            self._entry_jump_forward_index_stack = stacks
        return cast("dict[str, list[EntryJumpAnchor]]", stacks)

    def _entry_jump_forward_stack_for_current_tab(self) -> list[EntryJumpAnchor]:
        """Return the current non-Agents tab's jump-forward stack."""
        return self._entry_jump_forward_stack_map().setdefault(self.current_tab, [])

    def _entry_jump_index_stack_has_current_tab_history(self) -> bool:
        """Return whether the current non-Agents tab has jump-back history."""
        return bool(self._entry_jump_index_stack.get(self.current_tab))

    def _entry_jump_index_is_valid(self, tab: str, idx: int) -> bool:
        """Return whether ``idx`` still identifies a row in ``tab``."""
        if tab in {"artifacts", "patches", "changespecs"}:
            patches = getattr(self, "patches", getattr(self, "changespecs", []))
            return 0 <= idx < len(patches)
        if tab == "axe":
            return 0 <= idx < len(self._axe_items)  # type: ignore[attr-defined]
        return False

    def _patch_banner_anchor_is_valid(
        self,
        group_key: tuple[str, ...],
    ) -> bool:
        """Return whether ``group_key`` is a selectable Patch banner right now."""
        stops_fn = getattr(self, "_patch_navigation_stops", None)
        if not callable(stops_fn):
            return False
        try:
            stops = stops_fn()
        except Exception:
            return False
        return any(kind == "banner" and payload == group_key for kind, payload in stops)

    def _entry_jump_anchor_is_valid(
        self,
        tab: str,
        anchor: EntryJumpAnchor,
    ) -> bool:
        """Return whether a non-Agents jump anchor can be restored."""
        if isinstance(anchor, int):
            return self._entry_jump_index_is_valid(tab, anchor)
        kind, group_key = anchor
        return (
            kind in {"patch_banner", "changespec_banner"}
            and tab in {"artifacts", "patches", "changespecs"}
            and self._patch_banner_anchor_is_valid(group_key)
        )

    def _current_entry_jump_anchor(self) -> EntryJumpAnchor | None:
        """Snapshot the current non-Agents cursor as a row or Patch banner."""
        if self.current_tab in {"artifacts", "patches", "changespecs"}:
            group_key = getattr(self, "_current_patch_group_key", None)
            if group_key is None:
                group_key = getattr(self, "_current_changespec_group_key", None)
            if group_key is not None:
                kind: Literal["patch_banner", "changespec_banner"] = (
                    "patch_banner"
                    if self.current_tab == "artifacts"
                    else "changespec_banner"
                )
                banner_anchor: EntryJumpAnchor = (
                    kind,
                    tuple(group_key),
                )
                if self._entry_jump_anchor_is_valid(self.current_tab, banner_anchor):
                    return banner_anchor

        if self._entry_jump_index_is_valid(self.current_tab, self.current_idx):
            return self.current_idx
        return None

    def _push_entry_jump_anchor_to_stack(
        self,
        stacks: dict[str, list[EntryJumpAnchor]],
        anchor: EntryJumpAnchor,
    ) -> None:
        """Push ``anchor`` onto the current tab's stack without adjacent duplicates."""
        stack = stacks.setdefault(self.current_tab, [])
        if not stack or stack[-1] != anchor:
            stack.append(anchor)

    def _clear_current_entry_jump_forward_stack(self) -> None:
        """Clear forward history for the current non-Agents tab."""
        stack = self._entry_jump_forward_stack_map().get(self.current_tab)
        if stack is not None:
            stack.clear()

    def _push_entry_jump_index_origin_if_changed(
        self,
        *,
        target_idx: int | None,
        target_group_key: tuple[str, ...] | None = None,
    ) -> None:
        """Push the current non-Agents row when a jump will move focus."""
        row_changed = target_idx is not None and target_idx != self.current_idx
        current_group_key = getattr(self, "_current_patch_group_key", None)
        if current_group_key is None:
            current_group_key = getattr(self, "_current_changespec_group_key", None)
        group_changed = (
            self.current_tab in {"artifacts", "patches", "changespecs"}
            and target_group_key != current_group_key
        )
        if not row_changed and not group_changed:
            return
        anchor = self._current_entry_jump_anchor()
        if anchor is None:
            return
        self._push_entry_jump_anchor_to_stack(self._entry_jump_index_stack, anchor)
        self._clear_current_entry_jump_forward_stack()

    def _push_patch_to_history(self) -> None:
        """Push the current Patch cursor onto the jump-back stack."""
        if self.current_tab not in {"artifacts", "patches", "changespecs"}:
            return
        anchor = self._current_entry_jump_anchor()
        if anchor is None:
            return
        self._push_entry_jump_anchor_to_stack(self._entry_jump_index_stack, anchor)
        self._clear_current_entry_jump_forward_stack()

    def _push_changespec_to_history(self) -> None:
        self._push_patch_to_history()

    def _pop_entry_jump_anchor_from(
        self,
        stacks: dict[str, list[EntryJumpAnchor]],
    ) -> EntryJumpAnchor | None:
        """Pop the latest valid anchor for the current non-Agents tab."""
        stack = stacks.get(self.current_tab)
        if not stack:
            return None
        while stack:
            anchor = stack.pop()
            if self._entry_jump_anchor_is_valid(self.current_tab, anchor):
                return anchor
        stacks.pop(self.current_tab, None)
        return None

    def _pop_entry_jump_index(self) -> EntryJumpAnchor | None:
        """Pop the latest valid anchor for the current non-Agents tab."""
        return self._pop_entry_jump_anchor_from(self._entry_jump_index_stack)

    def _restore_entry_jump_anchor(self, anchor: EntryJumpAnchor) -> bool:
        """Restore a non-Agents jump anchor. Returns True when it was valid."""
        if not self._entry_jump_anchor_is_valid(self.current_tab, anchor):
            return False
        if isinstance(anchor, int):
            if self.current_tab in {"artifacts", "patches", "changespecs"}:
                self._current_patch_group_key = None  # type: ignore[attr-defined]
                if hasattr(self, "_current_changespec_group_key"):
                    self._current_changespec_group_key = None  # type: ignore[attr-defined]
            self.current_idx = anchor
            return True

        _, group_key = anchor
        self._current_patch_group_key = group_key  # type: ignore[attr-defined]
        if hasattr(self, "_current_changespec_group_key"):
            self._current_changespec_group_key = group_key  # type: ignore[attr-defined]
        return True

    def _refresh_after_entry_jump_restore(self) -> None:
        """Refresh the tab after a direct jump-stack restore."""
        if self.current_tab == "agents":
            self._refresh_agents_display(list_changed=True)  # type: ignore[attr-defined]
        elif self.current_tab in {"artifacts", "patches", "changespecs"}:
            self._refresh_display()  # type: ignore[attr-defined]
        else:
            self._refresh_current_tab()  # type: ignore[attr-defined]

    def _notify_no_next_jump_point(self) -> None:
        """Notify the user that the jump-forward stack is empty."""
        notify = getattr(self, "notify", None)
        if callable(notify):
            notify("No next jump point", severity="information")
