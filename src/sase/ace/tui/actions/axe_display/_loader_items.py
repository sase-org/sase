"""AXE sidebar item construction and selection-state helpers."""

from __future__ import annotations

from ...bgcmd import (
    get_active_slots,
    get_slot_info,
    is_slot_running,
    mark_slot_finished,
)
from ...widgets.bgcmd_list import AxeItem, BgCmdItem, ChopItem, LumberjackItem
from ._loader_state import AxeItemKey, AxeLoaderState


def axe_item_key(item: AxeItem) -> AxeItemKey:
    """Return the stable identity key for an AXE side-panel item."""
    match item:
        case LumberjackItem(name=name):
            return ("lumberjack", name)
        case ChopItem(lumberjack_name=lj_name, chop_name=chop_name):
            return ("chop", lj_name, chop_name)
        case BgCmdItem(slot=slot):
            return ("bgcmd", slot)


def find_axe_item_idx(items: list[AxeItem], key: AxeItemKey | None) -> int | None:
    """Find the row index for an AXE item identity key."""
    if key is None:
        return None
    for idx, item in enumerate(items):
        if axe_item_key(item) == key:
            return idx
    return None


def selected_axe_item_key(items: list[AxeItem], current_idx: int) -> AxeItemKey | None:
    """Return the selected AXE item identity key, if the row is valid."""
    if 0 <= current_idx < len(items):
        return axe_item_key(items[current_idx])
    return None


class AxeDisplayItemsMixin(AxeLoaderState):
    """Mixin providing AXE sidebar loading, construction, and selection."""

    def _load_lumberjack_names(self) -> None:
        """Load lumberjack names from axe config."""
        from sase.axe.config import load_axe_config as load_new_axe_config

        config = load_new_axe_config()
        self._axe_lumberjack_names = sorted(config.lumberjacks.keys())

        # Reset index if it's now out of bounds
        if self._axe_lumberjack_idx is not None and self._axe_lumberjack_idx >= len(
            self._axe_lumberjack_names
        ):
            self._axe_lumberjack_idx = None

    def _load_bgcmd_state(self) -> None:
        """Load background command state from disk (running + done commands)."""
        active_slots = get_active_slots()
        self._bgcmd_slots = []

        for slot in active_slots:
            info = get_slot_info(slot)
            if info is not None:
                # Check if command just finished and mark it
                if not is_slot_running(slot) and info.finished_at is None:
                    mark_slot_finished(slot)
                    info = get_slot_info(slot)  # Reload to get updated info
                if info is not None:
                    self._bgcmd_slots.append((slot, info))

        # Update footer with bgcmd count
        self._update_bgcmd_count()

        # Rebuild axe items list
        self._build_axe_items()

    def _update_bgcmd_count(self) -> None:
        """Update the keybinding footer with bgcmd running/done counts."""
        from ...widgets import KeybindingFooter

        running_count, done_count = self._get_bgcmd_counts()
        try:
            footer = self.query_one("#keybinding-footer", KeybindingFooter)  # type: ignore[attr-defined]
            footer.set_bgcmd_count(running_count, done_count)
        except Exception:
            pass

    def _get_bgcmd_counts(self) -> tuple[int, int]:
        """Get running and done counts for background commands.

        Returns:
            Tuple of (running_count, done_count).
        """
        running_count = 0
        done_count = 0
        for slot, _ in self._bgcmd_slots:
            if is_slot_running(slot):
                running_count += 1
            else:
                done_count += 1
        return running_count, done_count

    def _build_axe_items(self) -> None:
        """Build the flat list of AXE side-panel items based on fold and hidden state."""
        from ...models.fold_state import FoldLevel
        from ...util.selection import restore_selection_by_identity

        on_axe_tab = self.current_tab == "axe"

        # Capture identity *before* mutating ``_axe_items`` so off-tab
        # rebuilds (e.g. axe daemon push while the user is on Agents)
        # still preserve the saved-key for when the user returns. When
        # on-tab, the live cursor wins; when off-tab, fall back to the
        # last-saved key so we don't lose it across tab switches.
        if on_axe_tab:
            selected_key = selected_axe_item_key(self._axe_items, self.current_idx)
            prior_visual_row: int | None = self.current_idx
        else:
            selected_key = self._axe_last_item_key
            prior_visual_row = self._axe_last_idx

        pending = getattr(self, "_axe_pending_selection", None)
        pending_target: AxeItemKey | None = None
        if pending is not None:
            if not on_axe_tab or selected_key != pending.guard_key:
                self._axe_pending_selection = None
            else:
                pending_target = pending.target_key
                if pending_target[0] == "chop":
                    self._axe_fold_manager.expand(f"lumberjack:{pending_target[1]}")

        items: list[AxeItem] = []

        # Top-level lumberjacks, each followed by its configured chops
        # when its per-lumberjack fold is expanded. First-time sightings
        # default to expanded so chops are visible without an extra keystroke.
        for lumberjack_name in self._axe_lumberjack_names:
            items.append(LumberjackItem(name=lumberjack_name))
            fold_key = f"lumberjack:{lumberjack_name}"
            if not self._axe_fold_manager.has(fold_key):
                self._axe_fold_manager.expand(fold_key)
            if self._axe_fold_manager.get(fold_key) != FoldLevel.COLLAPSED:
                for chop_name in self._axe_lumberjack_chop_names.get(
                    lumberjack_name, []
                ):
                    items.append(
                        ChopItem(lumberjack_name=lumberjack_name, chop_name=chop_name)
                    )

        # Add bgcmd entries when not hidden, visually separated below the
        # lumberjack tree.
        if not self._axe_cmds_hidden:
            for slot, _ in sorted(self._bgcmd_slots, key=lambda x: x[0]):
                items.append(BgCmdItem(slot=slot))

        self._axe_items = items

        restored_idx = restore_selection_by_identity(
            items,
            prior_identity=selected_key,
            prior_visual_row=prior_visual_row,
            identity_fn=axe_item_key,
        )

        if pending_target is not None:
            pending_idx = find_axe_item_idx(items, pending_target)
            self._axe_pending_selection = None
            if pending_idx is not None:
                restored_idx = pending_idx

        if on_axe_tab:
            self.current_idx = restored_idx

        # Always update the tab-saved position/key so a later tab switch
        # back to AXE lands on the same logical entry. Off-tab rebuilds
        # never touch ``current_idx`` (it belongs to whatever tab is active).
        self._axe_last_idx = restored_idx
        self._axe_last_item_key = selected_axe_item_key(items, restored_idx)

    # Max number of recorded runs kept per chop (mirrors the on-disk cap).
    _MAX_CHOP_RUN_HISTORY: int = 10

    def _axe_resolve_chop_run_offset(self, chop_key: tuple[str, str]) -> int:
        """Return the displayed run offset for a chop, clamped to history.

        Absent or out-of-range entries collapse to ``0`` (newest run).
        """
        snap = self._axe_chop_snapshots.get(chop_key)
        run_total = len(snap.runs) if snap is not None else 0
        if run_total <= 0:
            return 0
        raw = self._axe_chop_run_offsets.get(chop_key, 0)
        upper = min(run_total, self._MAX_CHOP_RUN_HISTORY) - 1
        if raw <= 0:
            return 0
        if raw > upper:
            return upper
        return raw

    def _axe_step_chop_run_offset(self, direction: int) -> bool:
        """Move the selected chop's run-history offset by ``direction``.

        Returns:
            True iff the offset actually changed (so the caller knows it
            needs to repaint). No-ops when no chop is selected, the chop
            has zero recorded runs, or the move is already clamped.
        """
        chop_key = self._axe_chop_selection
        if chop_key is None:
            return False
        snap = self._axe_chop_snapshots.get(chop_key)
        run_total = len(snap.runs) if snap is not None else 0
        if run_total <= 0:
            return False
        current = self._axe_resolve_chop_run_offset(chop_key)
        upper = min(run_total, self._MAX_CHOP_RUN_HISTORY) - 1
        target = current + direction
        if target < 0:
            target = 0
        elif target > upper:
            target = upper
        if target == current:
            return False
        if target == 0:
            # Back to newest → drop the pin so future newer runs auto-track.
            self._axe_chop_run_offsets.pop(chop_key, None)
        else:
            self._axe_chop_run_offsets[chop_key] = target
        return True

    def _derive_axe_view_from_selection(self) -> None:
        """Derive _axe_current_view, _axe_lumberjack_idx, and _axe_chop_selection.

        The render layer distinguishes three AXE views off the resulting
        state:

        - Lumberjack row → ``_axe_current_view == "axe"`` with
          ``_axe_chop_selection is None``.
        - Chop row → ``_axe_current_view == "axe"`` with
          ``_axe_chop_selection`` set to the (lumberjack, chop) identity.
        - Bgcmd row → ``_axe_current_view`` set to the slot number.
        """
        if not (0 <= self.current_idx < len(self._axe_items)):
            self._axe_current_view = "axe"
            self._axe_lumberjack_idx = None
            self._axe_chop_selection = None
            return

        item = self._axe_items[self.current_idx]
        match item:
            case LumberjackItem(name=name):
                self._axe_current_view = "axe"
                self._axe_chop_selection = None
                try:
                    self._axe_lumberjack_idx = self._axe_lumberjack_names.index(name)
                except ValueError:
                    self._axe_lumberjack_idx = None
            case ChopItem(lumberjack_name=lj_name, chop_name=chop_name):
                # Chops live under their parent lumberjack; the render
                # layer keys off ``_axe_chop_selection`` to pick the
                # chop-run-detail view from the same cached snapshot the
                # lumberjack overview uses.
                self._axe_current_view = "axe"
                self._axe_chop_selection = (lj_name, chop_name)
                try:
                    self._axe_lumberjack_idx = self._axe_lumberjack_names.index(lj_name)
                except ValueError:
                    self._axe_lumberjack_idx = None
            case BgCmdItem(slot=slot):
                self._axe_current_view = slot
                self._axe_chop_selection = None
                self._axe_lumberjack_idx = None
