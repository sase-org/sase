"""Command-line and command-palette actions for sase's TUI app."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from ._base_types import BaseActionsHost

if TYPE_CHECKING:
    from ..commands import CommandTab


class BaseCommandActionsMixin(BaseActionsHost):
    """Mixin providing command-line and command-palette actions."""

    def action_open_command_line(self) -> None:
        """Open the bottom-anchored Command Line panel (bound to ``:``)."""
        from ..command_line.screen import CommandLineScreen

        self.push_screen(  # type: ignore[attr-defined]
            CommandLineScreen(), callback=None
        )

    def action_open_command_palette(self) -> None:
        """Open the context-aware command palette modal (bound to ``;``)."""
        from ..commands import (
            CommandPaletteResult,
            build_command_catalog,
            execute_command,
            extract_command_context,
            is_command_available,
        )
        from ..modals.command_palette_modal import CommandPaletteModal

        registry = self._keymap_registry  # type: ignore[attr-defined]
        ctx = extract_command_context(self)  # type: ignore[arg-type]
        catalog = build_command_catalog(
            registry,
            snapshot=getattr(self, "artifacts_descriptor_snapshot", None),
        )
        applicable = [s for s in catalog if is_command_available(s, ctx)]

        def _on_dismiss(result: CommandPaletteResult | None) -> None:
            if result is None:
                return
            if result.preserve_command_line_draft:
                self.action_open_command_line()
                return
            if result.command_line_prefill is not None:
                from ..command_line.session import command_line_session_for

                session = command_line_session_for(self)  # type: ignore[arg-type]
                session.draft = result.command_line_prefill
                session.draft_cursor = len(result.command_line_prefill)
                session.selected_block_id = None
                self.action_open_command_line()
                return
            if result.selected_id is None:
                return
            spec = self._command_spec_for_palette_id(result.selected_id)
            if spec is None:
                if result.selected_id.startswith("artifacts."):
                    pane_id = result.selected_id.removeprefix("artifacts.")
                    snapshot = getattr(self, "artifacts_descriptor_snapshot", None)
                    label = snapshot.label(pane_id) if snapshot is not None else pane_id
                    notify = getattr(self, "notify", None)
                    if callable(notify):
                        notify(
                            f"Artifacts pane {label} is unavailable",
                            severity="warning",
                        )
                return
            execute_command(self, spec)  # type: ignore[arg-type]

        self.push_screen(  # type: ignore[attr-defined]
            CommandPaletteModal(specs=applicable, tab=cast("CommandTab", ctx.tab)),
            callback=_on_dismiss,
        )

    def _command_spec_for_palette_id(self, command_id: str) -> Any:
        """Resolve *command_id* against the committed catalog, not open-time."""

        from ..commands import build_command_catalog

        catalog = build_command_catalog(
            self._keymap_registry,  # type: ignore[attr-defined]
            snapshot=getattr(self, "artifacts_descriptor_snapshot", None),
        )
        for spec in catalog:
            if spec.id == command_id:
                return spec
        return None
