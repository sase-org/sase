"""Marking mixin for the ace TUI app."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from ...status import get_available_statuses
from ..tab_order import ARTIFACTS_TAB
from ..modals import StatusModal
from ..widgets.artifacts.entry_navigation import ArtifactEntryTarget
from ..widgets.artifacts.patch_entry import patch_row_target

if TYPE_CHECKING:
    from ...patch import Patch
    from ..artifact_tabs import ArtifactsPaneKey

# Type alias for tab names
TabName = Literal["artifacts", "patches", "changespecs", "agents", "axe"]


class MarkingMixin:
    """Mixin providing marking actions for Patches."""

    # Type hints for attributes accessed from AceApp (defined at runtime)
    patches: list[Patch]
    current_idx: int
    current_tab: TabName
    marked_indices: set[int]
    _artifacts_marked_targets: dict[ArtifactsPaneKey, set[ArtifactEntryTarget]]

    def _is_patch_tab(self) -> bool:
        return self.current_tab in {
            ARTIFACTS_TAB,
            "patches",
            "changespecs",  # legacy compatibility alias
        }

    def _visible_patches(self) -> list[Patch]:
        return getattr(
            self,
            "patches",
            getattr(self, "changespecs", []),  # legacy compatibility alias
        )

    def action_toggle_mark(self) -> None:
        """Toggle mark on the current Patch or agent."""
        if (
            self._is_patch_tab()
            and getattr(self, "current_artifacts_pane_key", "patches") != "patches"
        ):
            self._toggle_artifacts_entry_mark()  # type: ignore[attr-defined]
            return
        if self._is_patch_tab():
            self._toggle_mark_patch()
            return
        if self.current_tab == "agents":
            self._toggle_mark_agent()  # type: ignore[attr-defined]
            return

    def action_toggle_agent_unread(self) -> None:
        """Toggle the selected agent row's unread marker."""
        if self.current_tab == "agents":
            self._toggle_agent_unread()  # type: ignore[attr-defined]
            return

    def _toggle_mark_patch(self) -> None:
        """Toggle mark on the currently-selected Patch."""
        patches = self._visible_patches()
        if not patches:
            self.notify("No Patches to mark", severity="warning")  # type: ignore[attr-defined]
            return

        idx = self.current_idx
        target = patch_row_target(patches[idx])
        marks = self._artifacts_marked_targets.setdefault("patches", set())
        was_marked = target in marks

        if was_marked:
            marks.discard(target)
        else:
            marks.add(target)

        # Patch only the toggled row in place; falls back to a full refresh
        # if the widget can't accept the patch (e.g. width grew).
        patch_row = getattr(self, "_try_patch_patch_row", None)
        if not callable(patch_row):
            patch_row = getattr(
                self,
                "_try_patch_changespec_row",  # legacy compatibility alias
                None,
            )
        if not callable(patch_row) or not patch_row(idx):
            self._refresh_display()  # type: ignore[attr-defined]
        else:
            self._update_info_panel()  # type: ignore[attr-defined]

        # Auto-navigate to next spec (with wraparound)
        if len(patches) > 1:
            self.current_idx = (self.current_idx + 1) % len(patches)

    def _toggle_mark_changespec(self) -> None:  # legacy compatibility alias
        self._toggle_mark_patch()

    def action_clear_marks(self) -> None:
        """Clear all marks on the active tab."""
        if (
            self._is_patch_tab()
            and getattr(self, "current_artifacts_pane_key", "patches") != "patches"
        ):
            self._clear_artifacts_marks()  # type: ignore[attr-defined]
            return
        if self._is_patch_tab():
            self._clear_patch_marks()
            return
        if self.current_tab == "agents":
            self._clear_agent_marks()  # type: ignore[attr-defined]
            return

    def _clear_patch_marks(self) -> None:
        """Clear all Patch marks."""
        marks = self._artifacts_marked_targets.get("patches")
        if not marks:
            self.notify("No marks to clear", severity="warning")  # type: ignore[attr-defined]
            return

        count = len(marks)
        self._artifacts_marked_targets["patches"] = set()
        self._refresh_display()  # type: ignore[attr-defined]
        self.notify(f"Cleared {count} mark(s)")  # type: ignore[attr-defined]

    def _clear_changespec_marks(self) -> None:  # legacy compatibility alias
        self._clear_patch_marks()

    def action_bulk_change_status(self) -> None:
        """Change status for marked Patches."""
        if not self._is_patch_tab():
            return

        if not self.marked_indices:
            self.notify("No Patches marked", severity="warning")  # type: ignore[attr-defined]
            return

        # Get marked patches (sorted by index for consistent ordering)
        patches = self._visible_patches()
        marked_specs = [patches[i] for i in sorted(self.marked_indices)]

        # Find common available statuses (intersection)
        common_statuses: set[str] | None = None
        for spec in marked_specs:
            available = set(get_available_statuses(spec.status))
            if common_statuses is None:
                common_statuses = available
            else:
                common_statuses &= available

        if not common_statuses:
            self.notify("No common status transitions available", severity="warning")  # type: ignore[attr-defined]
            return

        def on_dismiss(new_status: str | None) -> None:
            if new_status:
                self._apply_bulk_status_change(marked_specs, new_status)

        # Use first marked spec for modal display, but pass common statuses
        self.push_screen(  # type: ignore[attr-defined]
            StatusModal(marked_specs[0].status, list(common_statuses)),
            on_dismiss,
        )

    def action_save_marked_agents(self) -> None:
        """Save and dismiss marked agents on the Agents tab."""
        if self.current_tab != "agents":
            return
        self._prompt_and_save_marked_agent_group()  # type: ignore[attr-defined]

    def _apply_bulk_status_change(self, patches: list[Patch], new_status: str) -> None:
        """Apply status change to multiple Patches."""
        success_count = 0
        fail_count = 0

        for spec in patches:
            try:
                self._apply_status_change(spec, new_status)  # type: ignore[attr-defined]
                success_count += 1
            except Exception:
                fail_count += 1

        # Clear marks after bulk operation (indices will shift)
        self._artifacts_marked_targets["patches"] = set()

        # Reload and reposition
        self._reload_and_reposition()  # type: ignore[attr-defined]

        # Show summary notification
        if fail_count == 0:
            self.notify(f"Changed {success_count} Patch(s) to {new_status}")  # type: ignore[attr-defined]
        else:
            self.notify(  # type: ignore[attr-defined]
                f"Changed {success_count}, failed {fail_count}",
                severity="warning",
            )
