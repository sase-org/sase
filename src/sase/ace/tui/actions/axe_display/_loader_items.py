"""AXE sidebar item construction and selection-state helpers."""

from __future__ import annotations

from ...widgets.bgcmd_list import (
    AxeItem,
    BgCmdItem,
    ChopItem,
    LumberjackItem,
    ServiceProcItem,
)
from ._loader_state import AxeItemKey, AxeLoaderState


def axe_item_key(item: AxeItem) -> AxeItemKey:
    """Return the stable identity key for an AXE side-panel item."""
    match item:
        case ServiceProcItem(name=name):
            return ("service", name)
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
        """Load lumberjack names and declaring origins from axe config."""
        from sase.axe.config import load_axe_config as load_new_axe_config
        from sase.axe.config_backend import AxeEntityOrigin

        config = load_new_axe_config()
        self._axe_lumberjack_names = sorted(config.lumberjacks.keys())
        self._axe_routine_origins = {
            name: AxeEntityOrigin(source=jack.source, declared_by=jack.declared_by)
            for name, jack in config.lumberjacks.items()
        }
        self._axe_chop_origins = {
            (name, chop.name): AxeEntityOrigin(
                source=chop.source, declared_by=chop.declared_by
            )
            for name, jack in config.lumberjacks.items()
            for chop in jack.chops
        }

        # Reset index if it's now out of bounds
        if self._axe_lumberjack_idx is not None and self._axe_lumberjack_idx >= len(
            self._axe_lumberjack_names
        ):
            self._axe_lumberjack_idx = None

    def _load_bgcmd_state(self) -> None:
        """Reload background command state (oneshot rows) off the event loop.

        The oneshot rows live in the proc store, so this schedules the
        coalesced async AXE refresh instead of reading them inline.
        """
        self._schedule_axe_async_refresh()  # type: ignore[attr-defined]

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
        for _slot, info in self._bgcmd_slots:
            if info.running:
                running_count += 1
            else:
                done_count += 1
        return running_count, done_count

    def _build_axe_items(self) -> None:
        """Build the flat list of AXE side-panel items based on fold and hidden state."""
        from ...models.fold_state import FoldLevel
        from ...util.selection import restore_selection_by_identity

        on_axe_tab = self.current_tab == "services"

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

        # Visual order matches the sidebar panels: every service proc,
        # then the oneshot rows, then routines grouped by declaring
        # source (User → Plugin → Builtin), alphabetically within each
        # panel with each routine's jobs immediately after it. Jobs
        # always render in their parent routine's panel.
        service_status = getattr(self, "_service_status", None)
        if service_status is not None:
            for proc in service_status.procs:
                items.append(ServiceProcItem(name=proc.name))

        # Add bgcmd entries when not hidden, visually separated below the
        # service procs.
        if not self._axe_cmds_hidden:
            for slot, _ in sorted(self._bgcmd_slots, key=lambda x: x[0]):
                items.append(BgCmdItem(slot=slot))

        self._append_lumberjack_items(items)

        self._axe_items = items
        from ._panels import build_services_panel_index

        routine_origins = getattr(self, "_axe_routine_origins", None)
        self._axe_panel_index = build_services_panel_index(items, routine_origins)

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

    def _ordered_routine_names_by_source(self) -> list[str]:
        """Return routine names in panel order, alphabetical within panel."""
        from ._panels import ROUTINE_PANEL_ORDER, routine_panel_key_for_source

        origins = getattr(self, "_axe_routine_origins", None) or {}
        buckets: dict[str, list[str]] = {key: [] for key in ROUTINE_PANEL_ORDER}
        for name in self._axe_lumberjack_names:
            origin = origins.get(name)
            if origin is None:
                # Tests and degraded configs may seed names without
                # origins; keep them visible in User rather than dropping
                # the row. Real collector payloads always carry origins.
                buckets["user_routines"].append(name)
                continue
            source = getattr(origin, "source", origin)
            if isinstance(origin, dict):
                candidate = origin.get("source", source)
                if isinstance(candidate, str):
                    source = candidate
            try:
                panel_key = routine_panel_key_for_source(source)  # type: ignore[arg-type]
            except ValueError:
                # Unknown source values fail clearly at index build time;
                # keep the row out of the wrong panel here so the error
                # surfaces from the single membership helper instead.
                raise
            buckets[panel_key].append(name)
        ordered: list[str] = []
        for key in ROUTINE_PANEL_ORDER:
            ordered.extend(sorted(buckets[key]))
        return ordered

    def _fold_builtin_on_first_sight(self, lumberjack_name: str) -> bool:
        """Return whether a first-seen routine row starts folded.

        Only builtin routines fold, only when the permanent
        ``ace.services.fold_builtin_routines`` preference is on, and only
        once the full job snapshots needed for the health badge have
        arrived — a header-only pre-load must not initialize a misleading
        fold. Explicit user folds are stored, so this runs once per
        routine and never overrides the user; User and Plugin routines
        always start expanded.
        """
        if not getattr(self, "_axe_fold_builtin_routines", True):
            return False
        if not getattr(self, "_axe_full_snapshot_ready", False):
            return False
        origins = getattr(self, "_axe_routine_origins", None) or {}
        origin = origins.get(lumberjack_name)
        if origin is None:
            return False
        source = getattr(origin, "source", origin)
        if isinstance(origin, dict):
            candidate = origin.get("source", source)
            if isinstance(candidate, str):
                source = candidate
        return source == "builtin"

    def _append_lumberjack_items(self, items: list[AxeItem]) -> None:
        """Append routine/job rows to ``items`` using per-routine fold state."""
        from ...models.fold_state import FoldLevel, FoldStateManager

        fold_manager: FoldStateManager = self._axe_fold_manager
        # Top-level lumberjacks, each followed by its configured chops
        # when its per-lumberjack fold is expanded. First-time sightings
        # default to expanded so chops are visible without an extra
        # keystroke, except builtin routines under the fold preference.
        # Order is panel order (User → Plugin → Builtin), then alphabetical
        # by routine so status or interval changes never reorder rows.
        for lumberjack_name in self._ordered_routine_names_by_source():
            items.append(LumberjackItem(name=lumberjack_name))
            fold_key = f"lumberjack:{lumberjack_name}"
            if not fold_manager.has(fold_key):
                if self._fold_builtin_on_first_sight(lumberjack_name):
                    fold_manager.restore_levels({fold_key: FoldLevel.COLLAPSED})
                else:
                    fold_manager.expand(fold_key)
            if fold_manager.get(fold_key) != FoldLevel.COLLAPSED:
                for chop_name in self._axe_lumberjack_chop_names.get(
                    lumberjack_name, []
                ):
                    items.append(
                        ChopItem(lumberjack_name=lumberjack_name, chop_name=chop_name)
                    )

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
            self._axe_service_selection = None
            return

        item = self._axe_items[self.current_idx]
        match item:
            case ServiceProcItem(name=name):
                self._axe_current_view = "axe"
                self._axe_service_selection = name
                self._axe_chop_selection = None
                self._axe_lumberjack_idx = None
            case LumberjackItem(name=name):
                self._axe_current_view = "axe"
                self._axe_service_selection = None
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
                self._axe_service_selection = None
                self._axe_chop_selection = (lj_name, chop_name)
                try:
                    self._axe_lumberjack_idx = self._axe_lumberjack_names.index(lj_name)
                except ValueError:
                    self._axe_lumberjack_idx = None
            case BgCmdItem(slot=slot):
                self._axe_current_view = slot
                self._axe_service_selection = None
                self._axe_chop_selection = None
                self._axe_lumberjack_idx = None
