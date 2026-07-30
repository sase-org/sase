"""Core copy-mode entry, key dispatch, and tab-shared snapshot action."""

from __future__ import annotations

from ...keymaps import key_display_name

from ._base import ClipboardBase
from ._delivery import schedule_copy_delivery
from ._helpers import (
    cap_copy_content,
    capture_tmux_pane,
    format_multi_copy_content_capped,
)
from ._palette import build_copy_as_context


class ClipboardCoreMixin(ClipboardBase):
    """Copy-mode lifecycle, per-tab key dispatch, and the shared snapshot action."""

    def action_copy_tab_content(self) -> None:
        """Copy tab-specific content to clipboard based on current tab."""
        self.action_start_copy_mode()

    def action_start_copy_mode(self) -> None:
        """Paint the legacy footer and open the warm-only Copy as palette."""
        context = build_copy_as_context(self)
        if context is None:
            return

        self._copy_mode_active = True  # type: ignore[attr-defined]
        self._update_copy_footer()

        from ...modals.copy_as_modal import CopyAsModal
        from ...modals.copy_as_types import CopyAsRow

        def _on_dismiss(row: CopyAsRow | None) -> None:
            if row is None:
                self._handle_copy_key("escape")
                return

            def dispatch() -> None:
                self._handle_copy_key(row.key)

            if row.captures_snapshot:
                call_after_refresh = getattr(self, "call_after_refresh", None)
                if callable(call_after_refresh):
                    call_after_refresh(dispatch)
                    return
            dispatch()

        self.push_screen(  # type: ignore[attr-defined]
            CopyAsModal(context),
            callback=_on_dismiss,
        )

    def _handle_copy_key(self, key: str) -> bool:
        """Handle the second key in copy mode sequence.

        Args:
            key: The key pressed after %.

        Returns:
            True if key was handled, False otherwise.
        """
        self._copy_mode_active = False  # type: ignore[attr-defined]

        if key == "escape":
            # Cancel copy mode silently and restore footer
            self._restore_copy_footer()
            return True

        if self._non_pr_artifacts_copy_active():  # type: ignore[attr-defined]
            result = self._handle_artifacts_copy_key(key)  # type: ignore[attr-defined]
        elif self.current_tab == "changespecs":
            result = self._handle_changespecs_copy_key(key)
        elif self.current_tab == "agents":
            result = self._handle_agents_copy_key(key)
        else:  # axe
            result = self._handle_axe_copy_key(key)

        # Restore normal footer
        self._restore_copy_footer()
        return result

    def _restore_copy_footer(self) -> None:
        """Restore the active pane's normal footer after copy mode."""
        if self._non_pr_artifacts_copy_active():  # type: ignore[attr-defined]
            self._sync_active_artifacts_entry_state()  # type: ignore[attr-defined]
        else:
            self._refresh_current_tab()  # type: ignore[attr-defined]

    def _update_copy_footer(self) -> None:
        """Update the footer to show copy mode bindings."""
        from ...widgets import KeybindingFooter

        try:
            footer = self.query_one("#keybinding-footer", KeybindingFooter)  # type: ignore[attr-defined]
            file_visible = False
            if self.current_tab == "agents":
                from ...widgets import AgentDetail

                agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
                file_visible = agent_detail.is_file_visible()
            footer.update_copy_bindings(
                self.current_tab,
                artifacts_subtab=getattr(self, "current_artifacts_subtab", None),
                file_visible=file_visible,
            )
        except Exception:
            pass

    def _handle_changespecs_copy_key(self, key: str) -> bool:
        """Handle copy key for changespecs tab.

        Args:
            key: The key pressed after %.

        Returns:
            True if key was handled, False otherwise.
        """
        if not self.changespecs:
            return False

        cs_keys = self._keymap_registry.copy_mode.keys["changespecs"]
        assert isinstance(cs_keys, dict)
        pr_number_key = cs_keys.get("pr_number", cs_keys.get("cl_number"))

        if key == cs_keys["raw"]:
            self._copy_changespec()  # type: ignore[attr-defined]
        elif key == cs_keys["with_snapshot"]:
            self._copy_changespec_and_snapshot()  # type: ignore[attr-defined]
        elif key == cs_keys["bug"]:
            self._copy_bug_number()  # type: ignore[attr-defined]
        elif pr_number_key is not None and key == pr_number_key:
            self._copy_pr_number()  # type: ignore[attr-defined]
        elif key == cs_keys["name"]:
            self._copy_cl_name()  # type: ignore[attr-defined]
        elif key == cs_keys.get("link"):
            self._copy_changespec_link()  # type: ignore[attr-defined]
        elif key == cs_keys["spec"]:
            self._copy_project_spec()  # type: ignore[attr-defined]
        elif key == cs_keys["snapshot"]:
            self._copy_snapshot()
        else:
            key_list = ", ".join(
                key_display_name(v) for v in cs_keys.values() if isinstance(v, str)
            )
            self.notify(  # type: ignore[attr-defined]
                f"Unknown copy key (ChangeSpecs: {key_list})", severity="warning"
            )
            return False
        return True

    def _handle_agents_copy_key(self, key: str) -> bool:
        """Handle copy key for agents tab.

        Args:
            key: The key pressed after %.

        Returns:
            True if key was handled, False otherwise.
        """
        ag_keys = self._keymap_registry.copy_mode.keys["agents"]
        assert isinstance(ag_keys, dict)

        if key == ag_keys["chat"]:
            self._copy_chat_path()  # type: ignore[attr-defined]
        elif key == ag_keys["file_path"]:
            self._copy_file_path()  # type: ignore[attr-defined]
        elif key == ag_keys["name"]:
            self._copy_agent_name()  # type: ignore[attr-defined]
        elif key == ag_keys["prompt"]:
            self._copy_agent_prompt()  # type: ignore[attr-defined]
        elif key == ag_keys["snapshot"]:
            self._copy_snapshot()
        else:
            key_list = ", ".join(
                key_display_name(v) for v in ag_keys.values() if isinstance(v, str)
            )
            self.notify(f"Unknown copy key (agents: {key_list})", severity="warning")  # type: ignore[attr-defined]
            return False
        return True

    def _handle_axe_copy_key(self, key: str) -> bool:
        """Handle copy key for axe tab.

        Args:
            key: The key pressed after %.

        Returns:
            True if key was handled, False otherwise.
        """
        axe_keys = self._keymap_registry.copy_mode.keys["axe"]
        assert isinstance(axe_keys, dict)

        if key == axe_keys["visible"]:
            self._copy_axe_output()  # type: ignore[attr-defined]
        elif key == axe_keys["full"]:
            self._copy_axe_full_output()  # type: ignore[attr-defined]
        elif key == axe_keys["snapshot"]:
            self._copy_snapshot()
        else:
            key_list = ", ".join(
                key_display_name(v) for v in axe_keys.values() if isinstance(v, str)
            )
            self.notify(f"Unknown copy key (axe: {key_list})", severity="warning")  # type: ignore[attr-defined]
            return False
        return True

    def _copy_snapshot(self) -> None:
        """Copy the tmux pane snapshot with header and backticks (%s)."""
        state = {"truncated": False}

        def snapshot_value() -> str:
            snapshot_content = capture_tmux_pane()
            if snapshot_content is None:
                raise RuntimeError("failed to capture tmux pane")
            contents = [("`sase ace` Snapshot", snapshot_content.strip())]
            capped = format_multi_copy_content_capped(contents)
            total = cap_copy_content("\n" + capped.value)
            state["truncated"] = capped.truncated or total.truncated
            return total.value

        schedule_copy_delivery(
            self,
            snapshot_value,
            copied_label=lambda: (
                "snapshot — truncated" if state["truncated"] else "snapshot"
            ),
            task_name="sase-copy-snapshot",
        )
