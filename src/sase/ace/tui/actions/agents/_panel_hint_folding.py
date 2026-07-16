"""Hint-selected whole-panel folding for the Agents tab."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ....hints import parse_numeric_hint_selection

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent_panels import AgentPanelGroup, PanelKey


class AgentPanelHintFoldingMixin:
    """Select and atomically toggle split Agents panels by numeric hints."""

    current_tab: str
    current_idx: int
    current_attempt_number: int | None
    _agents: list[Agent]
    _panel_group: AgentPanelGroup
    _agent_panels_grouped: bool
    _collapsed_panel_keys: set[PanelKey]
    _current_group_key: tuple[str, ...] | None
    _hint_mode_active: bool
    _hint_mode_hints_for: str | None
    _panel_fold_hint_mode_active: bool
    _panel_fold_hint_snapshot: tuple[PanelKey, ...]
    _panel_fold_hint_to_key: dict[int, PanelKey]
    _panel_fold_key_to_hint: dict[PanelKey, int]

    def action_toggle_selected_agent_panels(self) -> None:
        """Open the numeric panel selector for one atomic mixed-state toggle."""
        if self.current_tab != "agents":
            return
        if self._refocus_existing_hint_bar():  # type: ignore[attr-defined]
            return

        if getattr(self, "_agent_panels_grouped", False):
            self.notify(  # type: ignore[attr-defined]
                "Panel selection requires split tag panels", severity="warning"
            )
            return

        panel_group = getattr(self, "_panel_group", None)
        panel_keys = tuple(getattr(panel_group, "panel_keys", ()))
        if len(panel_keys) < 2:
            self.notify(  # type: ignore[attr-defined]
                "Need at least two panels to select", severity="warning"
            )
            return

        # A title must never carry both the apostrophe jump namespace and the
        # numeric panel-selection namespace.
        if getattr(self, "_entry_jump_mode_active", False):
            self._exit_entry_jump_mode()  # type: ignore[attr-defined]

        self._panel_fold_hint_snapshot = panel_keys
        self._panel_fold_hint_to_key = dict(enumerate(panel_keys, start=1))
        self._panel_fold_key_to_hint = {
            key: hint for hint, key in self._panel_fold_hint_to_key.items()
        }
        self._panel_fold_hint_mode_active = True
        self._hint_mode_active = True
        self._hint_mode_hints_for = "panels"

        from ...widgets import HintInputBar

        try:
            detail_container = self.query_one("#agent-detail-container")  # type: ignore[attr-defined]
            if not bool(getattr(detail_container, "is_attached", True)):
                raise RuntimeError("agent detail container is detached")
            detail_container.mount(HintInputBar(mode="panels", id="hint-input-bar"))
        except Exception:
            self._teardown_panel_fold_hint_mode(refresh_titles=False)
            self.notify("Panel selector is unavailable", severity="warning")  # type: ignore[attr-defined]
            return

        self._refresh_agent_panel_titles()  # type: ignore[attr-defined]

    def _teardown_panel_fold_hint_mode(self, *, refresh_titles: bool = True) -> None:
        """Clear panel-selection state before removing any transient widgets."""
        if not getattr(self, "_panel_fold_hint_mode_active", False):
            return

        self._panel_fold_hint_mode_active = False
        self._panel_fold_hint_snapshot = ()
        self._panel_fold_hint_to_key = {}
        self._panel_fold_key_to_hint = {}
        self._hint_mode_active = False
        self._hint_mode_hints_for = None

        from ...widgets import HintInputBar

        try:
            hint_bar = self.query_one("#hint-input-bar", HintInputBar)  # type: ignore[attr-defined]
            hint_bar.remove()
        except Exception:
            pass

        if refresh_titles and self.current_tab == "agents":
            self._refresh_agent_panel_titles()  # type: ignore[attr-defined]

    def _live_split_panel_keys(self) -> tuple[PanelKey, ...]:
        """Return the current split-panel collection without mutating UI state."""
        from ...models.agent_panels import AgentPanelGroup

        focused_key = getattr(self._panel_group, "focused_key", None)
        live = AgentPanelGroup.from_agents(
            self._agents,
            focused_key,
            merge_tag_panels=False,
            collapsed_panel_keys=self._collapsed_panel_keys,
        )
        return tuple(live.panel_keys)

    def _process_panel_fold_hint_input(self, user_input: str) -> None:
        """Validate a panel selection and apply one coalesced fold transition."""
        mappings = dict(getattr(self, "_panel_fold_hint_to_key", {}))
        parsed = parse_numeric_hint_selection(user_input, mappings)
        if not user_input.strip() or not parsed.numbers:
            if parsed.malformed or parsed.unavailable:
                self._notify_invalid_panel_hints(parsed.malformed, parsed.unavailable)
            else:
                self.notify(  # type: ignore[attr-defined]
                    "Enter one or more panel hints", severity="warning"
                )
            return
        if parsed.malformed or parsed.unavailable:
            self._notify_invalid_panel_hints(parsed.malformed, parsed.unavailable)
            return

        snapshot = tuple(getattr(self, "_panel_fold_hint_snapshot", ()))
        live_keys = self._live_split_panel_keys()
        if (
            getattr(self, "_agent_panels_grouped", False)
            or len(live_keys) < 2
            or len(snapshot) != len(live_keys)
            or set(snapshot) != set(live_keys)
            or any(mappings.get(hint) not in live_keys for hint in parsed.numbers)
        ):
            self._teardown_panel_fold_hint_mode()
            self.notify(  # type: ignore[attr-defined]
                "Agent panels changed; retry panel selection", severity="warning"
            )
            return

        selected_keys = [mappings[hint] for hint in parsed.numbers]
        previous_collapsed = set(self._collapsed_panel_keys)
        next_collapsed = set(previous_collapsed)
        for key in selected_keys:
            if key in next_collapsed:
                next_collapsed.remove(key)
            else:
                next_collapsed.add(key)

        expanded = sum(1 for key in selected_keys if key in previous_collapsed)
        collapsed = len(selected_keys) - expanded
        focused_key = self._panel_group.focused_key
        focused_toggled = focused_key in selected_keys
        focused_now_collapsed = focused_key in next_collapsed

        # Clear transient state before the one list-changing repaint.  This
        # also ensures the refresh can safely restore focus to the AgentList.
        self._teardown_panel_fold_hint_mode(refresh_titles=False)
        self._collapsed_panel_keys.clear()
        self._collapsed_panel_keys.update(next_collapsed)
        self._invalidate_agent_panel_cache()  # type: ignore[attr-defined]

        if focused_toggled:
            self.current_attempt_number = None
            if focused_now_collapsed:
                self._current_group_key = None
                from ._navigation_order import rendered_panel_slice

                global_indices, _panel_agents = rendered_panel_slice(self, focused_key)
                if global_indices:
                    self.current_idx = global_indices[0]
            else:
                stops = self._panel_navigation_stops()  # type: ignore[attr-defined]
                if stops:
                    self._focus_panel_navigation_stop(stops[0])  # type: ignore[attr-defined]
                else:
                    self._current_group_key = None
                    self._snap_current_idx_to_focused_panel(  # type: ignore[attr-defined]
                        self._panel_keys_per_agent(),  # type: ignore[attr-defined]
                        focused_key,
                    )

        self._refresh_agents_display(list_changed=True)  # type: ignore[attr-defined]
        for key in selected_keys:
            self._persist_panel_fold_change(  # type: ignore[attr-defined]
                key,
                collapsed=key in next_collapsed,
            )

        parts: list[str] = []
        if expanded:
            parts.append(f"{expanded} expanded")
        if collapsed:
            parts.append(f"{collapsed} collapsed")
        self.notify(f"Panels toggled: {', '.join(parts)}", timeout=1.5)  # type: ignore[attr-defined]

    def _notify_invalid_panel_hints(
        self,
        malformed: tuple[str, ...],
        unavailable: tuple[int, ...],
    ) -> None:
        """Explain a rejected panel selection while leaving the bar mounted."""
        details: list[str] = []
        if malformed:
            details.append(f"malformed: {', '.join(malformed)}")
        if unavailable:
            details.append(
                f"unavailable: {', '.join(str(number) for number in unavailable)}"
            )
        self.notify(  # type: ignore[attr-defined]
            f"Invalid panel selection ({'; '.join(details)})",
            severity="warning",
        )


__all__ = ["AgentPanelHintFoldingMixin"]
