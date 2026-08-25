"""Option-list reconciliation and summary rendering for the Agent pane."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import RenderableType
from rich.text import Text
from textual.widgets import Static

from sase.ace.tui.keymaps import KeymapRegistry, key_display_name

from ..._artifact_tab_model import PaneGroupingModeDecl
from ...models.artifact_groups import (
    ArtifactGroupBuildResult,
    group_banner_option_id,
    group_banner_target,
)
from ...models.group_fold import GroupFoldRegistry
from .agents_data import AgentsSnapshot
from .agents_list import (
    AGENTS_PANE_ID,
    AgentRow,
    build_agent_options,
    build_grouped_agent_rows,
)
from .agents_navigation import AgentsOptionList
from .entry_navigation import ArtifactEntryTarget
from .shell import (
    ArtifactsPaneState,
    build_empty_card,
    build_footer_hints,
    build_state_badge,
)
from .types import ARTIFACTS_ACCENTS, ArtifactsPaneContract

if TYPE_CHECKING:
    from textual.containers import Vertical as _MixinBase
else:
    _MixinBase = object


class AgentsOptionsMixin(_MixinBase):
    """Own list rebuilding, match counts, and pane summary text."""

    contract: ArtifactsPaneContract | None
    project_scope: str | None
    _project_display_name: str | None
    _registry: KeymapRegistry
    _snapshot: AgentsSnapshot | None
    _loading: bool
    _load_error: str | None
    _rows: dict[str, AgentRow]
    _entry_jump_hints: dict[ArtifactEntryTarget, str]
    _entry_marks: set[ArtifactEntryTarget]
    _option_id_by_target: dict[ArtifactEntryTarget, str]
    _pending_entry_target: ArtifactEntryTarget | None
    _syncing_options: bool

    if TYPE_CHECKING:

        def selected_entry_target(self) -> ArtifactEntryTarget | None: ...

        def _option_list(self) -> AgentsOptionList | None: ...

        def _set_agent_rows(
            self,
            rows: dict[str, AgentRow],
            options: list,
            banner_targets: dict[str, ArtifactEntryTarget] | None = None,
        ) -> None: ...

        def _active_grouping_mode(self) -> PaneGroupingModeDecl | None: ...

        def _group_fold_registry(self) -> GroupFoldRegistry: ...

    def _group_pane_id(self) -> str:
        return AGENTS_PANE_ID

    def _group_build_result(
        self,
        *,
        fold_registry: GroupFoldRegistry,
    ) -> ArtifactGroupBuildResult:
        mode = self._active_grouping_mode()
        snapshot = self._current_snapshot()
        if mode is None or snapshot is None:
            return ArtifactGroupBuildResult(rows=(), known_group_keys=())
        return build_grouped_agent_rows(
            snapshot, mode=mode, fold_registry=fold_registry
        )

    def _group_refresh(self, preferred_target: ArtifactEntryTarget | None) -> None:
        self._refresh_options(preferred_target=preferred_target)

    def _refresh_options(
        self,
        *,
        preferred_target: ArtifactEntryTarget | None = None,
    ) -> None:
        option_list = self._option_list()
        if option_list is None:
            return
        pending_target = self._pending_entry_target
        if pending_target is not None:
            preferred_target = pending_target
        elif preferred_target is None:
            preferred_target = self.selected_entry_target()
        mode = self._active_grouping_mode()
        registry = self._group_fold_registry() if mode is not None else None
        options, rows, known_group_keys = build_agent_options(
            self._current_snapshot(),
            loading=self._loading,
            mode=mode,
            fold_registry=registry,
            accent=self._accent(),
            jump_hints=self._entry_jump_hints,
            marks=self._entry_marks,
        )
        if registry is not None:
            registry.clear_unknown(known_group_keys)
        banner_targets_by_option_id = (
            {}
            if mode is None
            else {
                group_banner_option_id(mode.id, key): group_banner_target(
                    AGENTS_PANE_ID, mode.id, key
                )
                for key in known_group_keys
            }
        )
        self._set_agent_rows(rows, options, banner_targets_by_option_id)
        preferred_option_id = (
            None
            if preferred_target is None
            else self._option_id_by_target.get(preferred_target)
        )
        highlighted = next(
            (
                index
                for index, option in enumerate(options)
                if option.id == preferred_option_id
            ),
            None,
        )
        if pending_target is not None:
            if highlighted is not None:
                self._pending_entry_target = None
            elif self._current_snapshot() is not None:
                self._pending_entry_target = None
                notify = getattr(self, "notify", None)
                if callable(notify):
                    notify(
                        "Linked agent is no longer visible in Agent",
                        severity="warning",
                    )
        if highlighted is None:
            highlighted = next(
                (index for index, option in enumerate(options) if not option.disabled),
                None,
            )
        self._syncing_options = True
        try:
            option_list.replace_options(options, highlighted=highlighted)
        finally:
            self._syncing_options = False
        self._update_empty()
        self._update_status()
        self._update_static("#agents-info", self._scope_text())
        self._update_static("#agents-hints", self._hints_text())

    def _update_empty(self) -> None:
        if not self.is_mounted:
            return
        empty = self.query_one("#agents-empty", Static)
        option_list = self.query_one("#agents-list", AgentsOptionList)
        has_current_snapshot = self._current_snapshot() is not None
        show_empty = (
            has_current_snapshot
            and not self._rows
            and not self._loading
            and self._load_error is None
        )
        if show_empty:
            if self.contract is not None:
                empty.update(build_empty_card(self.contract, has_active_filter=False))
            else:
                empty.update("No agents found.")
        empty.display = show_empty
        option_list.display = not show_empty

    def _update_status(self) -> None:
        self._update_static("#agents-status", self._status_text())

    def _update_static(self, selector: str, content: RenderableType) -> None:
        if self.is_mounted:
            self.query_one(selector, Static).update(content)

    def _accent(self) -> str:
        contract = self.contract
        return ARTIFACTS_ACCENTS["agents"] if contract is None else contract.accent

    def _scope_text(self) -> RenderableType:
        scope = self._project_display_name or self.project_scope or "All projects"
        text = Text()
        text.append(" Agent ", style=f"bold #1a1a1a on {self._accent()}")
        text.append("  Project scope  ", style="dim")
        text.append(f" {scope} ", style=f"bold {self._accent()}")
        text.append("  ·  ", style="dim")
        text.append(
            f"{key_display_name(self._registry.app.pick_artifacts_project)} change",
            style="dim",
        )
        snapshot = self._current_snapshot()
        if snapshot is not None and snapshot.truncated:
            text.append("  │  ", style="dim")
            text.append(
                f"showing {len(snapshot.rows):,} of {snapshot.total_row_count:,}",
                style=f"bold {self._accent()}",
            )
        return text

    def _status_text(self) -> RenderableType:
        snapshot = self._current_snapshot()
        text = Text()
        if snapshot is None:
            if self._load_error:
                text.append(self._load_error, style="bold #FF5F5F")
            else:
                text.append(
                    "Loading agents…"
                    if self._loading
                    else "Agents have not loaded yet",
                    style="bold #FFD700" if self._loading else "dim",
                )
            return text
        if self._loading or self._load_error:
            text.append_text(
                build_state_badge(
                    ArtifactsPaneState.STALE,
                    error_message=self._load_error if not self._loading else None,
                )
            )
            text.append("  ·  ", style="dim")
        text.append(f"{snapshot.total_row_count:,} agents loaded", style="dim")
        return text

    def _hints_text(self) -> RenderableType:
        keymap = self._registry.app
        parts = (
            (key_display_name(keymap.jump_to_entry), "jump"),
            (key_display_name(keymap.toggle_mark), "mark"),
            (key_display_name(keymap.artifacts_copy_reference), "copy ref"),
            (key_display_name(keymap.refresh), "refresh"),
        )
        return build_footer_hints(parts, accent=self._accent())

    def _current_snapshot(self) -> AgentsSnapshot | None:
        snapshot = self._snapshot
        if snapshot is None or snapshot.project != self.project_scope:
            return None
        return snapshot

    def _snapshot_matches_scope(self) -> bool:
        return self._current_snapshot() is not None

    def _snapshot_row_count(self) -> int:
        snapshot = self._current_snapshot()
        return 0 if snapshot is None else snapshot.total_row_count


__all__ = ["AgentsOptionsMixin"]
