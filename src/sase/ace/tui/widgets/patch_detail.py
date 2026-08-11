"""Patch detail widget for the ace TUI."""

from pathlib import Path
import sys
from typing import Any

from rich.markup import escape as _esc
from rich.panel import Panel
from rich.text import Text
from sase.running_field import get_claimed_workspaces
from sase.project_display_names import humanize_cl_name
from textual.widgets import Static

from ...patch import PR_ORIGIN_UNKNOWN, Patch, normalize_pr_origin
from ....core.patch import get_workspace_directory_for_patch
from ...display_helpers import (
    format_running_claims_aligned,
    get_status_color,
)
from ...query.highlighting import (
    PR_ORIGIN_VALUE_STYLES,
    QUERY_TOKEN_STYLES,
    tokenize_query_for_display,
)
from ..models.fold_state import FoldLevel
from ..util.trace import tui_trace
from .section_builders import (
    HintTracker,
    build_comments_section,
    build_stitches_section,
    build_deltas_section,
    build_hooks_section,
    build_mentors_section,
    build_refs_section,
    build_timestamps_section,
)


def build_query_text(query: str) -> Text:
    """Build a styled Text object for the query.

    Uses shared highlighting from query.highlighting module.
    """
    text = Text()
    tokens = tokenize_query_for_display(query)

    for token, token_type in tokens:
        style = QUERY_TOKEN_STYLES.get(token_type, "")
        if token_type == "keyword":
            text.append(token.upper(), style=style)
        elif style:
            text.append(token, style=style)
        else:
            text.append(token)

    return text


class SearchQueryPanel(Static):
    """Panel showing the current search query."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the search query panel."""
        super().__init__(**kwargs)
        self._query_string: str = ""

    def update_query(self, query_string: str) -> None:
        """Update the stored query and trigger a refresh.

        Args:
            query_string: The current search query string.
        """
        self._query_string = query_string
        self.refresh()

    def _resolve_saved_queries(self) -> dict[str, str]:
        """Return the app's cached saved-query map, falling back to disk.

        The TUI seeds ``app._saved_queries`` during startup and invalidates
        it on save/delete, so the hot render path is disk-free in the
        common case. The fallback covers tests that mount the panel
        without going through the full app lifecycle.
        """
        app = getattr(self, "app", None)
        cache = getattr(app, "_saved_queries", None)
        if isinstance(cache, dict):
            return cache
        from ...saved_queries import load_saved_queries

        return load_saved_queries()

    def render(self) -> Text:
        """Render the search query panel with proper right-alignment."""
        # Build left side content
        text = Text()
        text.append("Search Query ", style="dim italic #87D7FF")
        text.append("» ", style="dim #808080")
        text.append_text(build_query_text(self._query_string))

        # Check for saved query match.  Read the in-memory cache the app
        # populates at startup (and refreshes on save/delete) so this hot
        # render path skips the per-keystroke disk read.
        saved_queries = self._resolve_saved_queries()
        matched_slot: str | None = None
        for slot, saved_query in saved_queries.items():
            if saved_query == self._query_string:
                matched_slot = slot
                break

        if matched_slot is not None:
            # Build indicator matching the configured saved-query slot key.
            prefix = "0"
            registry = getattr(getattr(self, "app", None), "_keymap_registry", None)
            if registry is not None:
                from ..keymaps import key_display_name

                prefix = key_display_name(registry.app.start_saved_query_mode)
            indicator = Text()
            indicator.append(
                f"[{prefix}{matched_slot}]",
                style="bold #00FF00",
            )

            # Calculate padding for right-alignment
            left_len = len(text.plain)
            indicator_len = len(indicator.plain)
            # Subtract 2 for left/right padding (padding: 0 1)
            available_width = self.size.width - 2
            padding = max(1, available_width - left_len - indicator_len)
            text.append(" " * padding)
            text.append_text(indicator)

        return text


class PatchDetail(Static):
    """Right panel showing detailed Patch information."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the detail widget."""
        super().__init__(**kwargs)

    def update_display(
        self,
        patch: Patch,
        query_string: str,
        hooks_collapsed: FoldLevel = FoldLevel.COLLAPSED,
        stitches_collapsed: FoldLevel = FoldLevel.COLLAPSED,
        mentors_collapsed: FoldLevel = FoldLevel.COLLAPSED,
        timestamps_collapsed: FoldLevel = FoldLevel.COLLAPSED,
        deltas_collapsed: FoldLevel = FoldLevel.COLLAPSED,
    ) -> None:
        """Update the detail view with a new patch.

        Args:
            patch: The Patch to display
            query_string: The current query string
            hooks_collapsed: Fold level for hook status lines
            stitches_collapsed: Fold level for STITCHES drawer lines
            mentors_collapsed: Fold level for MENTORS entries
            timestamps_collapsed: Fold level for TIMESTAMPS section
            deltas_collapsed: Fold level for DELTAS section
        """
        with tui_trace("widget.patch_detail.update_display"):
            content, _, _, _, _ = self._build_display_content(
                patch,
                query_string,
                hooks_collapsed=hooks_collapsed,
                stitches_collapsed=stitches_collapsed,
                mentors_collapsed=mentors_collapsed,
                timestamps_collapsed=timestamps_collapsed,
                deltas_collapsed=deltas_collapsed,
            )
            self.update(content)

    def update_display_with_hints(
        self,
        patch: Patch,
        query_string: str,
        hints_for: str | None = None,
        hooks_collapsed: FoldLevel = FoldLevel.COLLAPSED,
        stitches_collapsed: FoldLevel = FoldLevel.COLLAPSED,
        mentors_collapsed: FoldLevel = FoldLevel.COLLAPSED,
        timestamps_collapsed: FoldLevel = FoldLevel.COLLAPSED,
        deltas_collapsed: FoldLevel = FoldLevel.COLLAPSED,
    ) -> tuple[
        dict[int, str], dict[int, int], dict[int, str], dict[int, tuple[str, str]]
    ]:
        """Update display with inline hints and return mappings.

        Args:
            patch: The Patch to display
            query_string: The current query string
            hints_for: Controls which entries get hints:
                - None or "all": Show hints for all entries
                - "hooks_latest_only": Show hints only for hook status lines
                  that match current/proposal entry IDs
            hooks_collapsed: Fold level for hook status lines
            stitches_collapsed: Fold level for STITCHES drawer lines
            mentors_collapsed: Fold level for MENTORS entries
            timestamps_collapsed: Fold level for TIMESTAMPS section
            deltas_collapsed: Fold level for DELTAS section

        Returns:
            Tuple of:
            - Dict mapping hint numbers to file paths
            - Dict mapping hint numbers to hook indices (for hooks_latest_only)
            - Dict mapping hint numbers to stitch entry IDs (for hooks_latest_only)
            - Dict mapping hint numbers to (mentor_name, profile_name) tuples
        """
        (
            content,
            hint_mappings,
            hook_hint_to_idx,
            hint_to_entry_id,
            mentor_hint_to_info,
        ) = self._build_display_content(
            patch,
            query_string,
            with_hints=True,
            hints_for=hints_for,
            hooks_collapsed=hooks_collapsed,
            stitches_collapsed=stitches_collapsed,
            mentors_collapsed=mentors_collapsed,
            timestamps_collapsed=timestamps_collapsed,
            deltas_collapsed=deltas_collapsed,
        )
        self.update(content)
        return hint_mappings, hook_hint_to_idx, hint_to_entry_id, mentor_hint_to_info

    def show_empty(self, query_string: str) -> None:
        """Show empty state when no Patches match."""
        del query_string  # Query is already displayed in SearchQueryPanel
        text = Text()
        text.append("No Patches match this query.", style="yellow")

        panel = Panel(
            text,
            title="No Results",
            border_style="yellow",
            padding=(1, 2),
        )
        self.update(panel)

    def _build_display_content(
        self,
        patch: Patch,
        query_string: str,
        with_hints: bool = False,
        hints_for: str | None = None,
        hooks_collapsed: FoldLevel = FoldLevel.COLLAPSED,
        stitches_collapsed: FoldLevel = FoldLevel.COLLAPSED,
        mentors_collapsed: FoldLevel = FoldLevel.COLLAPSED,
        timestamps_collapsed: FoldLevel = FoldLevel.COLLAPSED,
        deltas_collapsed: FoldLevel = FoldLevel.COLLAPSED,
    ) -> tuple[
        Panel,
        dict[int, str],
        dict[int, int],
        dict[int, str],
        dict[int, tuple[str, str]],
    ]:
        """Build the display content for a Patch."""
        del query_string  # No longer displayed inline; shown in SearchQueryPanel
        text = Text()

        # Initialize hint tracking
        hint_mappings: dict[int, str] = {}
        hook_hint_to_idx: dict[int, int] = {}
        hint_to_entry_id: dict[int, str] = {}
        mentor_hint_to_info: dict[int, tuple[str, str]] = {}
        hint_counter = 1

        # Determine which entries get hints
        show_history_hints = with_hints and hints_for in (None, "all")
        show_comment_hints = with_hints and hints_for in (None, "all")
        show_delta_hints = with_hints and hints_for in (None, "all")
        delta_workspace_dir = (
            self._resolve_delta_workspace_dir(patch) if show_delta_hints else None
        )

        # Build RUNNING field (displayed at top of panel)
        self._build_running_field(text, patch)

        # Build basic Patch fields
        self._build_basic_fields(text, patch)

        # REFS is a flat stored list; rendering performs no resolution or I/O.
        build_refs_section(text, patch)

        # Build STITCHES section
        hint_tracker = HintTracker(
            counter=hint_counter,
            mappings=hint_mappings,
            hook_hint_to_idx=hook_hint_to_idx,
            hint_to_entry_id=hint_to_entry_id,
            mentor_hint_to_info=mentor_hint_to_info,
        )
        hint_tracker = build_stitches_section(
            text,
            patch,
            show_history_hints,
            stitches_collapsed,
            hint_tracker,
            max_width=self.size.width,
        )

        # Build DELTAS section
        hint_tracker = build_deltas_section(
            text,
            patch,
            deltas_collapsed,
            hint_tracker,
            show_file_hints=show_delta_hints,
            workspace_dir=delta_workspace_dir,
        )

        # Build HOOKS section
        hint_tracker = build_hooks_section(
            text,
            patch,
            with_hints,
            hints_for,
            hooks_collapsed,
            hint_tracker,
        )

        # Build COMMENTS section
        hint_tracker = build_comments_section(
            text, patch, show_comment_hints, hint_tracker
        )

        # Build MENTORS section
        # Don't show mentor hints in hooks_latest_only mode (h key) —
        # mentor killing has its own dedicated mode (,M)
        show_mentor_hints = with_hints and hints_for != "hooks_latest_only"
        hint_tracker = build_mentors_section(
            text,
            patch,
            mentors_collapsed,
            show_mentor_hints,
            hints_for,
            hint_tracker,
        )

        # Build TIMESTAMPS section
        hint_tracker = build_timestamps_section(
            text,
            patch,
            timestamps_collapsed,
            hint_tracker,
        )

        text.rstrip()

        # Display in a panel with file location as title
        file_path = patch.file_path.replace(str(Path.home()), "~")
        file_location = f"{file_path}:{patch.line_number}"

        panel = Panel(
            text,
            title=f"{_esc(file_location)}",
            border_style="cyan",
            padding=(1, 2),
        )
        return (
            panel,
            hint_tracker.mappings,
            hint_tracker.hook_hint_to_idx,
            hint_tracker.hint_to_entry_id,
            hint_tracker.mentor_hint_to_info,
        )

    def _resolve_delta_workspace_dir(self, patch: Patch) -> str | None:
        """Resolve the primary workspace used for repo-relative DELTAS paths."""
        workspace_resolver = get_workspace_directory_for_patch
        compat_module = sys.modules.get(
            "sase.ace.tui.widgets.changespec_detail"  # legacy compatibility alias
        )
        legacy_resolver = getattr(  # legacy compatibility alias
            compat_module,
            "get_workspace_directory_for_changespec",  # legacy compatibility alias
            None,
        )
        if callable(legacy_resolver) and legacy_resolver is not workspace_resolver:
            workspace_resolver = legacy_resolver  # legacy compatibility alias
        workspace_dir = workspace_resolver(patch)
        if workspace_dir is None:
            return None
        return str(Path(workspace_dir).expanduser())

    def _build_running_field(
        self,
        text: Text,
        patch: Patch,
    ) -> None:
        """Build RUNNING claims section (displayed at top of panel)."""
        claims_loader = get_claimed_workspaces
        compat_module = sys.modules.get(
            "sase.ace.tui.widgets.changespec_detail"  # legacy compatibility alias
        )
        legacy_claims_loader = getattr(  # legacy compatibility alias
            compat_module, "get_claimed_workspaces", None
        )
        if callable(legacy_claims_loader) and legacy_claims_loader is not claims_loader:
            claims_loader = legacy_claims_loader  # legacy compatibility alias
        running_claims = claims_loader(patch.file_path)

        if running_claims:
            text.append("RUNNING:\n", style="bold #87D7FF")
            formatted_claims = format_running_claims_aligned(running_claims)
            for ws_col, pid_col, wf_col, cl_name in formatted_claims:
                # Each column gets a distinct color for beautiful syntax highlighting
                text.append(f"  {ws_col}", style="#5FD7FF")  # Cyan for workspace
                text.append(" | ", style="dim")
                text.append(pid_col, style="#FF87D7")  # Magenta/pink for PID
                text.append(" | ", style="dim")
                text.append(wf_col, style="#FFD787")  # Gold/amber for workflow
                if cl_name:
                    text.append(" | ", style="dim")
                    text.append(
                        humanize_cl_name(cl_name),
                        style="#87D7AF",
                    )  # Green for Patch name
                text.append("\n")
            text.append("\n\n")  # Separator after RUNNING

    def _build_basic_fields(
        self,
        text: Text,
        patch: Patch,
    ) -> None:
        """Build basic Patch fields (NAME, DESCRIPTION, etc.)."""
        # NAME field
        text.append("NAME: ", style="bold #87D7FF")
        text.append(f"{humanize_cl_name(patch.name)}\n", style="bold #00D7AF")

        # DESCRIPTION field
        text.append("DESCRIPTION:\n", style="bold #87D7FF")
        for line in patch.description.split("\n"):
            text.append(f"  {line}\n", style="#D7D7AF")

        # PARENT field (only display if present)
        if patch.parent:
            text.append("PARENT: ", style="bold #87D7FF")
            text.append(
                f"{humanize_cl_name(patch.parent)}\n",
                style="bold #00D7AF",
            )

        # PR field (only display if present)
        if patch.pr_url:
            text.append("PR: ", style="bold #87D7FF")
            text.append(f"{patch.pr_url}\n", style="bold underline #569CD6")

        if patch.pr_url or patch.pr_origin != PR_ORIGIN_UNKNOWN:
            pr_origin = normalize_pr_origin(patch.pr_origin)
            text.append("PR_ORIGIN: ", style="bold #87D7FF")
            text.append(
                f"{pr_origin}\n",
                style=PR_ORIGIN_VALUE_STYLES.get(pr_origin, "dim #FF5F5F"),
            )

        # BUG field (only display if present)
        if patch.bug:
            text.append("BUG: ", style="bold #87D7FF")
            text.append(f"{patch.bug}\n", style="bold underline #569CD6")

        # STATUS field
        text.append("STATUS: ", style="bold #87D7FF")
        status_color = get_status_color(patch.status)
        text.append(f"{patch.status}\n", style=f"bold {status_color}")

    def show_failed_hooks_targets(
        self,
        targets: list[str],
        file_path: str,
    ) -> None:
        """Display failed hooks targets with numbered hints for selection.

        Args:
            targets: List of test targets (lines starting with //).
            file_path: Path to the failed hooks file.
        """
        text = Text()

        # Header with file path
        text.append("FAILED HOOKS TARGETS\n", style="bold #FF5F5F")
        text.append("Source: ", style="dim")
        text.append(file_path, style="bold underline #00D7AF")
        text.append("\n\n")

        # List targets with numbered hints
        text.append("Select targets to add as hooks:\n", style="dim italic")
        for idx, target in enumerate(targets, 1):
            text.append(f"  [{idx}] ", style="bold #FFFF00")
            text.append(f"{target}\n", style="bold #AFD75F")

        text.append("\n")
        text.append("Enter numbers (e.g., 1 3 5 or 1-5) to add as hooks", style="dim")

        panel = Panel(
            text,
            title="Failed Hooks Selection",
            border_style="#FF5F5F",
            padding=(1, 2),
        )
        self.update(panel)
