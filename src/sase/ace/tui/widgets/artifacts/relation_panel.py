"""Host-owned relation panel for Artifacts panes."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from rich.text import Text
from textual.widgets import Static

from sase.ace.tui._artifact_tab_model import PaneRelationDecl, RelationKind
from sase.ace.tui.util.trace import tui_trace
from sase.core.artifact_entry_target import ArtifactEntryTarget
from sase.core.artifact_relation_layout import (
    EMPTY_RELATION_KEYMAP,
    RelationEntryFact,
    RelationKeymap,
    RelationRole,
    RelationRow,
    RelationSection,
    RelationSummary,
    RelationSummaryEntry,
    RelationView,
    build_relation_summary,
    build_relation_view,
)
from sase.core.artifact_relations import RelationIndex

from .shell import _SEPARATOR


_BEAD_STATUS_INDICATORS: dict[str, tuple[str, str]] = {
    "open": ("O", "#87D7FF"),
    "in_progress": ("P", "#FFD700"),
    "claimed": ("W", "#87CEEB"),
    "ready": ("R", "#87D700"),
    "snoozed": ("Z", "#808080"),
    "closed": ("C", "#00AF00"),
    "done": ("C", "#00AF00"),
}


def _get_simple_status_indicator(status: str) -> tuple[str, str]:
    """Return a compact status glyph for a relation row.

    Patch statuses keep their historical prefix table. Bead statuses use
    the closed host vocabulary. Any other declared status falls back to
    its first letter so a provider counter is never Patch-only.
    """
    if not status:
        return "", ""
    if status.startswith("Draft"):
        return "D", "#FFD700"
    if status.startswith("Ready"):
        return "R", "#87D700"
    if status.startswith("Mailed"):
        return "M", "#00D787"
    if status.startswith("Submitted"):
        return "S", "#00AF00"
    if status.startswith("Reverted"):
        return "X", "#808080"
    if status.startswith("Archived"):
        return "A", "#606060"
    bead = _BEAD_STATUS_INDICATORS.get(status.casefold())
    if bead is not None:
        return bead
    return status[0].upper(), "#87CEEB"


_DEFAULT_MODE_KEYS: Mapping[RelationRole, str] = {
    RelationRole.ANCESTOR: "<",
    RelationRole.DESCENDANT: ">",
    RelationRole.FAMILY: "~",
}


class RelationPanel(Static):
    """Panel rendering relations for the currently selected Artifacts entry."""

    def update_relations(
        self,
        *,
        index: RelationIndex,
        origin: ArtifactEntryTarget,
        relations: tuple[PaneRelationDecl, ...],
        facts: Mapping[ArtifactEntryTarget, RelationEntryFact] | None = None,
        accent: str = "#87D7FF",
        collapsed: bool = False,
        mode_keys: Mapping[RelationRole, str] | None = None,
    ) -> RelationKeymap:
        """Render the relation view and return its navigation keymap."""
        with tui_trace(
            "widget.relation_panel.update_relations",
            count=len(index.edges),
        ):
            view = build_relation_view(
                index=index,
                origin=origin,
                relations=relations,
                facts=facts or {},
            )
            if collapsed:
                self._refresh_collapsed(view, accent=accent, mode_keys=mode_keys)
            else:
                self._refresh_content(view, accent=accent)
            return view.keymap

    def clear(self) -> None:
        """Clear the relation panel and hide it."""
        self.set_class(False, "-collapsed")
        self.display = False
        self.update("")

    def _refresh_collapsed(
        self,
        view: RelationView,
        *,
        accent: str,
        mode_keys: Mapping[RelationRole, str] | None,
    ) -> None:
        text = _build_collapsed_rail(view, accent=accent, mode_keys=mode_keys)
        if text is None:
            self.clear()
            return
        self.set_class(True, "-collapsed")
        self.display = True
        self.update(text)

    def _refresh_content(self, view: RelationView, *, accent: str) -> None:
        self.set_class(False, "-collapsed")
        if not view:
            self.clear()
            return
        self.display = True
        text = Text()
        has_previous_section = False
        for section in view.sections:
            if not section.rows and section.hidden_count == 0:
                continue
            if has_previous_section:
                text.append("\n\n")
            self._render_section(text, section, accent=accent)
            has_previous_section = True
        self.update(text)

    def _render_section(
        self,
        text: Text,
        section: RelationSection,
        *,
        accent: str,
    ) -> None:
        text.append(section.label.upper(), style=f"bold {accent}")
        if section.hidden_count > 0:
            text.append(f" ({section.hidden_count} hidden)", style="dim #808080")
        if (
            section.kind is RelationKind.HIERARCHY
            and section.role is RelationRole.DESCENDANT
        ):
            self._render_tree(section.rows, text)
            return
        rows = (
            tuple(reversed(section.rows))
            if section.role is RelationRole.ANCESTOR
            else section.rows
        )
        for row in rows:
            text.append("\n")
            self._render_flat_row(
                text, row, keyed=section.kind is not RelationKind.LINK
            )

    def _render_tree(
        self,
        rows: tuple[RelationRow, ...],
        text: Text,
        prefix: str = "",
    ) -> None:
        for index, row in enumerate(rows):
            is_last = index == len(rows) - 1
            text.append("\n")
            if row.depth == 0:
                self._render_keyed_name(text, row, indent="  ")
                if row.children:
                    self._render_tree(row.children, text, prefix="      ")
                continue
            branch = "└─" if is_last else "├─"
            text.append(f"{prefix}{branch} ", style="dim")
            self._render_keyed_name(text, row, indent="")
            if row.children:
                child_prefix = prefix + ("   " if is_last else "│  ")
                self._render_tree(row.children, text, prefix=child_prefix)

    def _render_flat_row(self, text: Text, row: RelationRow, *, keyed: bool) -> None:
        if keyed:
            self._render_keyed_name(text, row, indent="  ")
            return
        text.append("  ")
        self._render_name(text, row)

    def _render_keyed_name(self, text: Text, row: RelationRow, *, indent: str) -> None:
        text.append(f"{indent}[{row.key}] ", style="bold #FFAF00")
        self._render_name(text, row)

    def _render_name(self, text: Text, row: RelationRow) -> None:
        visually_missing = row.dangling and not row.status
        name_style = "dim #00D7AF" if visually_missing else "#00D7AF"
        text.append(row.label, style=name_style)
        indicator, color = _get_simple_status_indicator(row.status)
        if indicator:
            text.append(f" [{indicator}]", style=f"bold {color}")
        if row.cross_pane:
            text.append(f" → {row.target.pane_id}", style="dim #808080")
        if visually_missing:
            text.append(" (missing)", style="dim #808080")


class RelationPanelHostMixin:
    """Pane-side helper for hosting a single relation panel."""

    def relation_panel(self) -> RelationPanel | None:
        """Return this pane's relation panel, if mounted."""
        cached = getattr(self, "_w_relation_panel", None)
        if isinstance(cached, RelationPanel):
            return cached
        try:
            return self.query_one(RelationPanel)  # type: ignore[attr-defined]
        except Exception:
            return None

    def refresh_relation_panel(self, *, refresh_footer: bool = True) -> RelationKeymap:
        """Refresh this pane's relation panel from its snapshot-owned index."""
        panel = self.relation_panel()
        keymap = EMPTY_RELATION_KEYMAP
        if panel is None:
            self._publish_relation_keymap(keymap)
            if refresh_footer:
                self._refresh_relation_footer(keymap)
            return keymap
        index_getter = getattr(self, "relation_index", None)
        index = index_getter() if callable(index_getter) else None
        selected_getter = getattr(self, "selected_entry_target", None)
        origin = selected_getter() if callable(selected_getter) else None
        contract = getattr(self, "contract", None)
        relations = (
            contract.relations
            if contract is not None and getattr(contract, "relations", None)
            else (() if index is None else index.relations)
        )
        if index is None or origin is None or not relations:
            panel.clear()
            self._publish_relation_keymap(keymap)
            if refresh_footer:
                self._refresh_relation_footer(keymap)
            return keymap
        facts_getter = getattr(self, "relation_entry_facts", None)
        facts = facts_getter() if callable(facts_getter) else {}
        accent_getter = getattr(self, "relation_panel_accent", None)
        accent = accent_getter() if callable(accent_getter) else None
        accent = accent or getattr(contract, "accent", None) or "#87D7FF"
        app = getattr(self, "app", None)
        collapsed = bool(getattr(app, "artifacts_relations_collapsed", False))
        keymap = panel.update_relations(
            index=index,
            origin=origin,
            relations=relations,
            facts=facts,
            accent=accent,
            collapsed=collapsed,
            mode_keys=_mode_keys_from_app(app),
        )
        self._publish_relation_keymap(keymap)
        if refresh_footer:
            self._refresh_relation_footer(keymap)
        return keymap

    def relation_footer_entries(
        self,
        keymap: RelationKeymap | None = None,
    ) -> tuple[tuple[str, str], ...]:
        """Return conditional footer entries for available relation modes."""
        if keymap is None:
            candidate = getattr(self.app, "_relation_keymap", EMPTY_RELATION_KEYMAP)  # type: ignore[attr-defined]
            keymap = (
                candidate
                if isinstance(candidate, RelationKeymap)
                else EMPTY_RELATION_KEYMAP
            )
        entries: list[tuple[str, str]] = []
        if keymap.ancestors:
            entries.append(
                (
                    "start_ancestor_mode",
                    _footer_label(keymap.label_for_role(RelationRole.ANCESTOR)),
                )
            )
        if keymap.children:
            entries.append(
                (
                    "start_child_mode",
                    _footer_label(keymap.label_for_role(RelationRole.DESCENDANT)),
                )
            )
        if keymap.siblings:
            entries.append(
                (
                    "start_sibling_mode",
                    _footer_label(keymap.label_for_role(RelationRole.FAMILY)),
                )
            )
        if keymap:
            collapsed = bool(
                getattr(
                    getattr(self, "app", None),
                    "artifacts_relations_collapsed",
                    False,
                )
            )
            entries.append(
                (
                    "toggle_relation_panel",
                    "expand relations" if collapsed else "collapse relations",
                )
            )
        return tuple(entries)

    def _publish_relation_keymap(self, keymap: RelationKeymap) -> None:
        if self._relation_surface_active():
            self.app._relation_keymap = keymap  # type: ignore[attr-defined]

    def _refresh_relation_footer(self, keymap: RelationKeymap) -> None:
        app = getattr(self, "app", None)
        if app is None or not self._relation_surface_active():
            return
        if getattr(app, "current_tab", None) != "artifacts":
            return
        if getattr(app, "current_artifacts_pane_key", None) == "patches":
            return
        signature = (
            getattr(app, "current_artifacts_pane_key", None),
            self.relation_footer_entries(keymap),
        )
        if getattr(self, "_relation_footer_signature", None) == signature:
            return
        self._relation_footer_signature = signature
        sync = getattr(app, "_sync_active_artifacts_entry_state", None)
        if callable(sync):
            attr = "_relation_footer_keymap_override"
            had_previous = hasattr(app, attr)
            previous = getattr(app, attr, None)
            setattr(app, attr, keymap)
            try:
                sync()
            finally:
                if had_previous:
                    setattr(app, attr, previous)
                else:
                    delattr(app, attr)

    def _relation_surface_active(self) -> bool:
        app = getattr(self, "app", None)
        if app is None:
            return False
        current_tab = getattr(app, "current_tab", None)
        contract = getattr(self, "contract", None)
        pane_id = getattr(contract, "id", None)
        if pane_id is None:
            index_getter = getattr(self, "relation_index", None)
            index = index_getter() if callable(index_getter) else None
            pane_id = None if index is None else index.pane_id
        if current_tab == "artifacts":
            current_pane = getattr(app, "current_artifacts_pane_key", None)
            if current_pane is None:
                current_pane = getattr(app, "current_artifacts_subtab", None)
            return current_pane == pane_id
        return (
            current_tab
            in {
                "patches",
                "changespecs",  # legacy compatibility alias
            }
            and pane_id == "patches"
        )


def _build_collapsed_rail(
    view: RelationView,
    *,
    accent: str,
    mode_keys: Mapping[RelationRole, str] | None = None,
) -> Text | None:
    """Build the one-line collapsed relations rail, or None when empty."""
    summary: RelationSummary = build_relation_summary(view)
    if not summary:
        return None
    entries: tuple[RelationSummaryEntry, ...] = summary.entries
    text = Text(no_wrap=True, overflow="ellipsis")
    text.append("▸", style=f"bold {accent}")
    text.append("  ")
    for index, entry in enumerate(entries):
        if index:
            text.append(_SEPARATOR, style="dim")
        key = _rail_mode_key(entry.role, mode_keys)
        if key:
            text.append(f"{key} ", style="bold #FFAF00")
        text.append(str(entry.count), style=f"bold {accent}")
        text.append(f" {entry.label.lower()}", style="dim")
    if summary.hidden_total > 0:
        text.append(f" ({summary.hidden_total} hidden)", style="dim #808080")
    return text


def _footer_label(label: str) -> str:
    normalized = label.strip().lower()
    return normalized or "relation"


def _rail_mode_key(
    role: RelationRole,
    mode_keys: Mapping[RelationRole, str] | None,
) -> str:
    if role is RelationRole.LINK:
        return ""
    if mode_keys:
        configured = mode_keys.get(role, "")
        if configured:
            return configured
    return _DEFAULT_MODE_KEYS.get(role, "")


def _mode_keys_from_app(app: Any) -> Mapping[RelationRole, str]:
    registry = getattr(app, "_keymap_registry", None)
    app_km = getattr(registry, "app", None) if registry is not None else None
    if app_km is None:
        return _DEFAULT_MODE_KEYS
    from sase.ace.tui.keymaps import key_display_name

    def _display(action: str, fallback: str) -> str:
        raw = getattr(app_km, action, fallback)
        displayed = key_display_name(raw) if isinstance(raw, str) else ""
        return displayed or fallback

    return {
        RelationRole.ANCESTOR: _display("start_ancestor_mode", "<"),
        RelationRole.DESCENDANT: _display("start_child_mode", ">"),
        RelationRole.FAMILY: _display("start_sibling_mode", "~"),
    }


__all__ = [
    "RelationEntryFact",
    "RelationKeymap",
    "RelationPanel",
    "RelationPanelHostMixin",
    "RelationRole",
    "_get_simple_status_indicator",
]
