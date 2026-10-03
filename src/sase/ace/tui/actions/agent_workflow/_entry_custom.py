"""Custom-selection agent entry points."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from sase.ace.patch.project_spec_path import preferred_project_spec_path
from sase.core.paths import sase_projects_dir

if TYPE_CHECKING:
    from ...modals import SelectionItem


def resolve_vcs_xprompt_mru_head(
    pairs: Sequence[tuple[str, str]] | None,
) -> tuple[str, str, str] | None:
    """Resolve the VCS xprompt MRU head into a ready-to-mount prefill.

    Takes the ``(canonical_prefix, display_prefix)`` pairs instead of
    loading them, so `<space>` and the other MRU-head entry points serve
    the prefill from the app-owned snapshot without I/O. Returns
    ``(initial_text, display_name, history_sort_key)``, or ``None`` when
    the MRU is empty. ``initial_text`` uses the ``+<project>`` tag for
    project entries (Patch entries keep their ``#`` ref) while
    ``display_name``/``history_sort_key`` keep today's display/canonical
    project spelling so history grouping agrees with every other prefill
    surface.
    """
    from sase.history.vcs_macro_mru import mru_prefix_project_name
    from sase.project_tags import known_project_tag_for, peek_project_tag_catalog

    if not pairs:
        return None
    canonical_prefix, display_prefix = pairs[0]
    display_name = mru_prefix_project_name(display_prefix) or display_prefix
    history_sort_key = mru_prefix_project_name(canonical_prefix) or display_name
    initial_text = f"{display_prefix} "
    catalog = peek_project_tag_catalog()
    if catalog is not None:
        spelling = known_project_tag_for(catalog, display_name)
        if spelling is not None and spelling.startswith("+"):
            initial_text = f"{spelling} "
    return initial_text, display_name, history_sort_key


class EntryCustomMixin:
    """Mixin providing custom project/Patch launch entry points."""

    if TYPE_CHECKING:

        def _is_launchable_project(self, project_name: str) -> bool: ...

        def _vcs_prompt_prefix_or_notify(
            self, project_file: str, name: str
        ) -> str | None: ...

        def _project_tag_prefix_or_notify(
            self, project_file: str, name: str
        ) -> str | None: ...

    def action_start_agent_from_patch(self) -> None:
        """Repeat the most recently launched VCS xprompt, or open a blank home prompt."""
        perf_begin = getattr(self, "_jk_perf_begin", None)
        if callable(perf_begin):
            perf_begin("prompt_space")
        changespec_override = self.__dict__.get(
            "action_start_agent_from_changespec"  # legacy compatibility alias
        )
        if callable(changespec_override):  # legacy compatibility alias
            changespec_override()  # legacy compatibility alias
            return
        legacy_override = self.__dict__.get("action_start_agent_from_patch")
        if callable(legacy_override):
            legacy_override()
            return
        from ._space_prefill import (
            drop_pending_space_prefill,
            peek_space_prefill_pairs,
            record_pending_space_prefill,
        )

        pairs = peek_space_prefill_pairs(self)
        if pairs is not None:
            # Warm snapshot: prefill with no I/O. An empty MRU opens a
            # blank bar, matching the legacy empty-store behavior.
            drop_pending_space_prefill(self)
            resolved = resolve_vcs_xprompt_mru_head(pairs)
            if resolved is None:
                self._show_prompt_input_bar_for_home()  # type: ignore[attr-defined]
                return
            initial_text, display_name, history_sort_key = resolved
            self._show_prompt_input_bar_for_home(  # type: ignore[attr-defined]
                initial_text=initial_text,
                display_name=display_name,
                history_sort_key=history_sort_key,
            )
            return
        if hasattr(self, "peek_launchable_mru_snapshot"):
            # Cold, error, or launch-pending snapshot: open the blank home
            # bar at once and apply a late prefill only to an untouched
            # session when the next snapshot publishes. Request a build
            # best-effort (single-flight coalesces) so the prefill arrives
            # even when no build is currently in flight.
            self._show_prompt_input_bar_for_home()  # type: ignore[attr-defined]
            record_pending_space_prefill(self)
            try:
                request = getattr(self, "request_launchable_mru_refresh", None)
                if callable(request):
                    request(reason="space-cold")
            except Exception:  # noqa: BLE001 - the next tick retries.
                pass
            return
        from sase.history.vcs_macro_mru import load_launchable_vcs_macro_mru_pairs

        resolved = resolve_vcs_xprompt_mru_head(
            load_launchable_vcs_macro_mru_pairs(prune=False)
        )
        if resolved is None:
            self._show_prompt_input_bar_for_home()  # type: ignore[attr-defined]
            return
        initial_text, display_name, history_sort_key = resolved
        self._show_prompt_input_bar_for_home(  # type: ignore[attr-defined]
            initial_text=initial_text,
            display_name=display_name,
            history_sort_key=history_sort_key,
        )

    def action_start_agent_from_changespec(self) -> None:  # legacy compatibility alias
        """Legacy alias for :meth:`action_start_agent_from_patch`."""
        self.action_start_agent_from_patch()

    def action_start_last_vcs_xprompt_in_editor(self) -> None:
        """Open editor with the most recently used launchable VCS xprompt."""
        from ._space_prefill import peek_ready_mru_pairs

        pairs = peek_ready_mru_pairs(self)
        if pairs is None:
            # Cold/error snapshot (or a host without one): the editor
            # opens anyway, so fall back to the synchronous loader without
            # ever writing the MRU file.
            from sase.history.vcs_macro_mru import (
                load_launchable_vcs_macro_mru_pairs,
            )

            pairs = list(load_launchable_vcs_macro_mru_pairs(prune=False))
        resolved = resolve_vcs_xprompt_mru_head(pairs)
        if resolved is None:
            self.notify("No previous VCS xprompt", severity="warning")  # type: ignore[attr-defined]
            return
        initial_text, display_name, history_sort_key = resolved

        self._select_and_open_editor_for_home(  # type: ignore[attr-defined]
            initial_text=initial_text,
            display_name=display_name,
            history_sort_key=history_sort_key,
        )

    def action_start_custom_agent(self) -> None:
        """Start a custom agent by selecting project or PR (works on all tabs)."""
        from ...modals import (
            ProjectSelectResult,
            SelectionItem,
        )
        from ...modals.project_select_modal import show_project_select_modal

        def on_project_select(result: ProjectSelectResult | None) -> None:
            if result is None:
                self.notify("Selection cancelled")  # type: ignore[attr-defined]
                return

            selection = result.selection
            open_in_editor = result.open_in_editor

            # Handle home directory selection
            if isinstance(selection, SelectionItem) and selection.item_type == "home":
                if open_in_editor:
                    self._select_and_open_editor_for_home()  # type: ignore[attr-defined]
                else:
                    self._show_prompt_input_bar_for_home()  # type: ignore[attr-defined]
                return

            # Determine selection type and details
            if isinstance(selection, str):
                # Custom name entered - no project file, use plain home mode
                if open_in_editor:
                    self._select_and_open_editor_for_home()  # type: ignore[attr-defined]
                else:
                    self._show_prompt_input_bar_for_home()  # type: ignore[attr-defined]
                return

            self._start_custom_agent_from_selection(
                selection, open_in_editor=open_in_editor
            )

        show_project_select_modal(
            self,
            on_project_select,
            exclude_project_names={"home"},
        )

    def _start_custom_agent_from_selection(
        self,
        selection: SelectionItem,
        *,
        open_in_editor: bool = False,
    ) -> None:
        """Start a custom agent from a previously resolved selection.

        Args:
            selection: The project/Patch selection item.
            open_in_editor: Whether to open in editor instead of prompt bar.
        """
        project_name: str = selection.project_name
        if selection.item_type == "home":
            if open_in_editor:
                self._select_and_open_editor_for_home()  # type: ignore[attr-defined]
            else:
                self._show_prompt_input_bar_for_home()  # type: ignore[attr-defined]
            return

        if selection.item_type not in (
            "project",
            "cl",
        ) or not self._is_launchable_project(project_name):
            from sase.project_display_names import project_display_name_for

            display_name = project_display_name_for(project_name)
            self.notify(  # type: ignore[attr-defined]
                f"Project {display_name!r} is not launchable", severity="warning"
            )
            return

        project_dir = str(sase_projects_dir() / project_name)
        project_file = preferred_project_spec_path(project_dir, project_name)

        if selection.item_type == "cl" and selection.cl_name:
            from sase.project_display_names import humanize_cl_name

            display_name = selection.selection_label or humanize_cl_name(
                selection.cl_name
            )
            prefix = self._vcs_prompt_prefix_or_notify(project_file, display_name)
            if prefix is None:
                return
            if open_in_editor:
                self._select_and_open_editor_for_home(  # type: ignore[attr-defined]
                    initial_text=prefix,
                    display_name=display_name,
                    history_sort_key=selection.cl_name,
                )
            else:
                self._show_prompt_input_bar_for_home(  # type: ignore[attr-defined]
                    initial_text=prefix,
                    display_name=display_name,
                    history_sort_key=selection.cl_name,
                )
        else:
            # Project selection. The prefix and bar label show the configured
            # project name (falling back to the directory key); identity uses
            # above keep ``selection.project_name``, and the history grouping
            # key stays the canonical directory key.
            from sase.project_display_names import project_display_name_for

            display_name = (
                selection.selection_label
                or selection.project_label
                or project_display_name_for(project_name)
            )
            prefix = self._project_tag_prefix_or_notify(project_file, display_name)
            if prefix is None:
                return
            if open_in_editor:
                self._select_and_open_editor_for_home(  # type: ignore[attr-defined]
                    initial_text=prefix,
                    display_name=display_name,
                    history_sort_key=project_name,
                )
            else:
                self._show_prompt_input_bar_for_home(  # type: ignore[attr-defined]
                    initial_text=prefix,
                    display_name=display_name,
                    history_sort_key=project_name,
                )
