"""Shared list navigation and selection actions for Artifacts panes."""

from __future__ import annotations

from typing import Any, cast

from ..artifacts_split import (
    ArtifactsSplitMode,
    cycle_artifacts_split_mode,
)
from ..tab_order import ARTIFACTS_TAB
from ..widgets.artifacts import (
    ArtifactEntryNavigator,
    ArtifactEntryTarget,
    ArtifactsPaneKey,
    ArtifactsSubTab,
    ArtifactsView,
    FilesSubTab,
    artifacts_pane_key,
    artifacts_subtab_order,
    normalize_artifacts_subtab,
)


class ArtifactsNavigationActionsMixin:
    """Navigate, mark, and switch between non-PR Artifacts entries."""

    current_tab: Any
    current_artifacts_subtab: str
    artifacts_split_mode: ArtifactsSplitMode
    current_files_subtab: FilesSubTab
    _artifacts_jump_mode_subtab: ArtifactsPaneKey | None
    _artifacts_jump_pending_prefix: str
    _artifacts_jump_hint_to_target: dict[str, ArtifactEntryTarget]
    _artifacts_jump_target_to_hint: dict[ArtifactEntryTarget, str]
    _artifacts_jump_history: dict[ArtifactsPaneKey, ArtifactEntryTarget]
    _artifacts_marked_targets: dict[ArtifactsPaneKey, set[ArtifactEntryTarget]]

    @property
    def current_artifacts_pane_key(self) -> ArtifactsPaneKey:
        """Resolve the visible leaf for lightweight mixin test harnesses."""

        return artifacts_pane_key(cast(ArtifactsSubTab, self.current_artifacts_subtab))

    def _artifacts_view(self) -> ArtifactsView | None:
        try:
            return self.query_one(  # type: ignore[attr-defined]
                "#artifacts-view", ArtifactsView
            )
        except Exception:
            return None

    def _non_pr_artifacts_active(self) -> bool:
        return (
            self.current_tab == ARTIFACTS_TAB
            and self.current_artifacts_pane_key != "patches"
        )

    def _sync_active_artifacts_entry_state(self) -> None:
        """Align footer and lazy scope setup with the visible Artifacts pane."""
        if self.current_tab != ARTIFACTS_TAB:
            return
        if self.current_artifacts_pane_key == "patches":
            self._refresh_display()  # type: ignore[attr-defined]
            return

        self._ensure_artifacts_project_choices()  # type: ignore[attr-defined]
        from ..widgets import KeybindingFooter

        footer = self.query_one(  # type: ignore[attr-defined]
            "#keybinding-footer",
            KeybindingFooter,
        )
        if getattr(self, "_bead_issue_mode_active", False):
            footer.update_bead_issue_bindings()
            return
        footer.show_artifacts_pane(
            self.current_artifacts_pane_key,
            mark_count=len(self._active_artifacts_marks()),
            conditional_entries=self._artifacts_footer_entries(),
        )

    def _artifacts_entry_navigator(
        self,
        pane_key: ArtifactsPaneKey | None = None,
    ) -> ArtifactEntryNavigator | None:
        target_pane = pane_key or self.current_artifacts_pane_key
        view = self._artifacts_view()
        if view is None:
            return None
        try:
            pane = view.entry_navigator(target_pane)
        except Exception:
            return None
        return cast(ArtifactEntryNavigator, pane)

    def _artifacts_footer_entries(self) -> tuple[tuple[str, str], ...]:
        pane = self._artifacts_entry_navigator()
        if pane is None:
            return ()
        return tuple(pane.conditional_footer_entries())

    def _request_artifacts_entry(self, target: ArtifactEntryTarget) -> None:
        """Switch to the target's owning pane and select it when ready."""

        pane_key = target.pane_id
        self._switch_artifacts_subtab(cast(ArtifactsSubTab, pane_key))
        pane = self._artifacts_entry_navigator(pane_key)
        if pane is None:
            return
        pane.request_entry_target(target)
        if self.current_tab == ARTIFACTS_TAB:
            self._sync_active_artifacts_entry_state()

    def _active_artifacts_marks(self) -> set[ArtifactEntryTarget]:
        """Return the app-owned mark set for the visible non-PR pane."""
        return self._artifacts_marked_targets.setdefault(
            self.current_artifacts_pane_key,
            set(),
        )

    def _toggle_artifacts_entry_mark(self) -> None:
        """Toggle the selected stable entry identity on the active pane."""
        pane = self._artifacts_entry_navigator()
        target = pane.selected_entry_target() if pane is not None else None
        if pane is None or target is None:
            self.notify(  # type: ignore[attr-defined]
                f"No {self.current_artifacts_pane_key.title()} entry to mark",
                severity="warning",
            )
            return
        marks = set(self._active_artifacts_marks())
        if target in marks:
            marks.remove(target)
        else:
            marks.add(target)
        self._artifacts_marked_targets[self.current_artifacts_pane_key] = marks
        pane.apply_entry_marks(marks)
        self._sync_active_artifacts_entry_state()

    def _clear_artifacts_marks(self) -> None:
        """Clear marks only from the active non-PR Artifacts pane."""
        marks = self._active_artifacts_marks()
        if not marks:
            self.notify(  # type: ignore[attr-defined]
                "No marks to clear", severity="warning"
            )
            return
        count = len(marks)
        self._artifacts_marked_targets[self.current_artifacts_pane_key] = set()
        pane = self._artifacts_entry_navigator()
        if pane is not None:
            pane.apply_entry_marks(set())
        self._sync_active_artifacts_entry_state()
        self.notify(f"Cleared {count} mark(s)")  # type: ignore[attr-defined]

    def _clear_all_artifacts_marks(self) -> None:
        """Drop every pane's marks after the shared project scope changes."""
        for pane_key in artifacts_subtab_order():
            if pane_key == "patches":
                continue
            self._clear_artifacts_marks_for_pane(pane_key)

    def _clear_artifacts_marks_for_pane(self, pane_key: ArtifactsPaneKey) -> None:
        """Clear one pane's marks when its effective project scope changes."""
        had_marks = bool(self._artifacts_marked_targets.get(pane_key))
        self._artifacts_marked_targets[pane_key] = set()
        if not had_marks:
            return
        pane = self._artifacts_entry_navigator(pane_key)
        if pane is not None:
            pane.apply_entry_marks(set())
        if (
            self.current_tab == ARTIFACTS_TAB
            and self.current_artifacts_pane_key == pane_key
        ):
            self._sync_active_artifacts_entry_state()

    def _navigate_non_pr_artifacts(
        self,
        *,
        action: str,
        offset: int | None = None,
        boundary: str | None = None,
    ) -> bool:
        """Route an existing global navigation action to the active entry list."""
        if not self._non_pr_artifacts_active():
            return False
        pane = self._artifacts_entry_navigator()
        if pane is None:
            return True
        from ..widgets.artifacts.entry_navigation import select_relative_entry

        self._begin_artifacts_navigation(action)
        try:
            select_relative_entry(pane, offset=offset, boundary=boundary)
        finally:
            self._finish_artifacts_navigation()
        return True

    def _scroll_non_pr_artifacts_detail(self, direction: int) -> bool:
        """Scroll only the active non-PR pane's right-hand detail viewport."""
        if not self._non_pr_artifacts_active():
            return False
        view = self._artifacts_view()
        if view is None:
            return True
        try:
            scroll = view.detail_scroll(self.current_artifacts_pane_key)
        except Exception:
            return True
        height = scroll.scrollable_content_region.height
        scroll.scroll_relative(y=direction * (height // 2), animate=False)
        return True

    def _begin_non_pr_artifacts_jump_mode(self) -> bool:
        """Paint shared adaptive hints for the active non-PR Artifacts list."""
        if not self._non_pr_artifacts_active():
            return False
        pane = self._artifacts_entry_navigator()
        if pane is None:
            return True
        targets = list(pane.entry_targets())
        if not targets:
            return True
        from .navigation.jump_hints import build_jump_hint_maps

        hint_to_target, target_to_hint = build_jump_hint_maps(targets)
        self._artifacts_jump_hint_to_target = hint_to_target
        self._artifacts_jump_target_to_hint = target_to_hint
        self._artifacts_jump_pending_prefix = ""
        self._artifacts_jump_mode_subtab = self.current_artifacts_pane_key
        self._entry_jump_mode_active = True  # type: ignore[attr-defined]
        pane.apply_entry_jump_hints(target_to_hint)
        self._update_jump_footer()  # type: ignore[attr-defined]
        return True

    def _valid_artifacts_jump_history(
        self,
        pane_key: ArtifactsPaneKey,
        pane: ArtifactEntryNavigator,
    ) -> ArtifactEntryTarget | None:
        target = self._artifacts_jump_history.get(pane_key)
        if target is not None and target not in pane.entry_targets():
            self._artifacts_jump_history.pop(pane_key, None)
            return None
        return target

    def _artifacts_jump_has_back(self) -> bool:
        pane_key = self.current_artifacts_pane_key
        pane = self._artifacts_entry_navigator(pane_key)
        if pane is None:
            return False
        return self._valid_artifacts_jump_history(pane_key, pane) is not None

    def _handle_non_pr_artifacts_jump_key(self, key: str) -> bool:
        """Dispatch one hint/back key without activating the selected entry."""
        pane_key = self._artifacts_jump_mode_subtab
        if pane_key is None:
            return False
        pane = self._artifacts_entry_navigator(pane_key)
        if pane is None:
            self._cancel_non_pr_artifacts_jump_mode()
            return True
        if key == "escape":
            self._cancel_non_pr_artifacts_jump_mode()
            return True

        if key == "apostrophe":
            target = self._valid_artifacts_jump_history(pane_key, pane)
            if target is None:
                target = next(iter(self._artifacts_jump_hint_to_target.values()), None)
        else:
            from .navigation.jump_hints import (
                JumpHintMatchOutcome,
                match_jump_hint,
            )

            match = match_jump_hint(
                self._artifacts_jump_hint_to_target,
                self._artifacts_jump_pending_prefix,
                key,
            )
            if match.outcome is JumpHintMatchOutcome.PENDING:
                self._artifacts_jump_pending_prefix = match.prefix
                return True
            if match.outcome is JumpHintMatchOutcome.INVALID:
                self._cancel_non_pr_artifacts_jump_mode()
                return True
            target = match.target
            self._artifacts_jump_pending_prefix = ""

        if target is None or target not in pane.entry_targets():
            self._cancel_non_pr_artifacts_jump_mode()
            return True
        origin = pane.selected_entry_target()
        if origin is not None and origin != target:
            self._artifacts_jump_history[pane_key] = origin
        pane.select_entry_target(target)
        self._cancel_non_pr_artifacts_jump_mode()
        return True

    def _cancel_non_pr_artifacts_jump_mode(self) -> None:
        """Clear hints from their owning pane and restore the normal footer."""
        owner = self._artifacts_jump_mode_subtab
        if owner is not None:
            pane = self._artifacts_entry_navigator(owner)
            if pane is not None:
                pane.clear_entry_jump_hints()
        self._artifacts_jump_mode_subtab = None
        self._artifacts_jump_pending_prefix = ""
        self._artifacts_jump_hint_to_target = {}
        self._artifacts_jump_target_to_hint = {}
        if owner is not None:
            self._entry_jump_mode_active = False  # type: ignore[attr-defined]
        if self._non_pr_artifacts_active():
            from ..widgets import KeybindingFooter

            try:
                self.query_one(  # type: ignore[attr-defined]
                    "#keybinding-footer", KeybindingFooter
                ).show_artifacts_pane(
                    self.current_artifacts_pane_key,
                    mark_count=len(self._active_artifacts_marks()),
                    conditional_entries=self._artifacts_footer_entries(),
                )
            except Exception:
                pass

    def _cancel_artifacts_jump_mode_for_model_change(
        self, pane_key: ArtifactsPaneKey
    ) -> None:
        """Cancel transient hints when their loaded row model is replaced."""
        if self._artifacts_jump_mode_subtab == pane_key:
            self._cancel_non_pr_artifacts_jump_mode()

    def _switch_artifacts_subtab(self, subtab: ArtifactsSubTab) -> None:
        from ..artifact_tabs import (
            switch_to_artifacts_subtab,
        )

        switch_to_artifacts_subtab(self, normalize_artifacts_subtab(subtab))

    def _cycle_artifacts_subtab(self, step: int) -> None:
        if self.current_tab != ARTIFACTS_TAB:
            return
        order = artifacts_subtab_order()
        current = normalize_artifacts_subtab(
            cast(ArtifactsSubTab, self.current_artifacts_subtab)
        )
        index = order.index(current)
        self.current_artifacts_subtab = order[(index + step) % len(order)]

    def _cycle_files_subtab(self, step: int) -> None:
        del step

    def _begin_artifacts_navigation(self, direction: str) -> None:
        """Start activity-gate and key-to-paint tracking for a pane cursor."""
        perf_begin = getattr(self, "_jk_perf_begin", None)
        if callable(perf_begin):
            perf_begin(f"{self.current_artifacts_pane_key}.{direction}")
        record_navigation = getattr(self, "_record_jk_navigation", None)
        if callable(record_navigation):
            record_navigation()

    def _finish_artifacts_navigation(self) -> None:
        """Finish key-to-paint tracking after a pane cursor has moved."""
        perf = getattr(self, "_jk_perf", None)
        if perf is None:
            return
        perf.mark_model_updated()
        self.call_after_refresh(perf.mark_painted)  # type: ignore[attr-defined]

    def action_cycle_artifacts_subtab(self) -> None:
        """Move to the next Artifacts sub-tab with wraparound."""
        self._cycle_artifacts_subtab(1)

    def action_cycle_artifacts_subtab_reverse(self) -> None:
        """Move to the previous Artifacts sub-tab with wraparound."""
        self._cycle_artifacts_subtab(-1)

    def _cycle_artifacts_split(self, direction: int) -> None:
        self.artifacts_split_mode = cycle_artifacts_split_mode(
            self.artifacts_split_mode,
            direction,
        )

    def action_cycle_artifacts_split(self) -> None:
        """Make the Artifacts list panel wider, with wraparound."""

        self._cycle_artifacts_split(1)

    def action_cycle_artifacts_split_reverse(self) -> None:
        """Make the Artifacts list panel narrower, with wraparound."""

        self._cycle_artifacts_split(-1)

    def action_cycle_files_subtab(self) -> None:
        """Retired nested Files pane cycle action."""

        self._cycle_files_subtab(1)

    def action_cycle_files_subtab_reverse(self) -> None:
        """Retired nested Files pane cycle action."""

        self._cycle_files_subtab(-1)

    def action_show_artifacts_digit(self, digit: int) -> None:
        """Switch to the descriptor carrying *digit* as its shortcut."""

        view = self._artifacts_view()
        if view is None:
            return
        selected = next(
            (
                descriptor
                for descriptor in view.descriptors
                if descriptor.digit_shortcut == str(digit)
            ),
            None,
        )
        if selected is not None:
            self._switch_artifacts_subtab(selected.id)

    def action_show_artifacts_patches(self) -> None:
        self._switch_artifacts_subtab("patches")

    def action_show_artifacts_prs(self) -> None:
        """Deprecated alias for :meth:`action_show_artifacts_patches`."""
        self._switch_artifacts_subtab("patches")

    def action_show_artifacts_stitches(self) -> None:
        self._switch_artifacts_subtab("stitches")

    def action_show_artifacts_bugs(self) -> None:
        """Deprecated alias routing the retired Bugs sub-tab to Beads."""
        self._switch_artifacts_subtab("beads")

    def action_show_artifacts_beads(self) -> None:
        self._switch_artifacts_subtab("beads")

    def action_show_artifacts_files(self) -> None:
        self._switch_artifacts_subtab("files")


__all__ = ["ArtifactsNavigationActionsMixin"]
