"""Custom mode mixin for user-defined prefix-key modes."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..keymaps import KeymapRegistry

log = logging.getLogger(__name__)


class CustomModeMixin:
    """Mixin providing custom mode key handling for user-defined prefix modes."""

    # Type hints for attributes accessed from AceApp (defined at runtime)
    _custom_mode_active: str | None
    _custom_mode_prefixes: dict[str, str]
    _keymap_registry: KeymapRegistry

    def _handle_custom_mode_key(self, key: str) -> bool:
        """Handle a key press in an active custom mode.

        Args:
            key: The key that was pressed.

        Returns:
            True if the key was handled, False otherwise.
        """
        mode_name = self._custom_mode_active
        assert mode_name is not None

        # Always exit custom mode
        self._custom_mode_active = None

        if key == "escape":
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        mode = self._keymap_registry.modes.get(mode_name)
        if mode is None:
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        # Find the sub-key that matches the pressed key.
        for action_name, spec in mode.keys.items():
            if not isinstance(spec, dict):
                continue
            if spec.get("key") != key:
                continue

            # Matched — dispatch to shell or action.
            if "shell" in spec:
                asyncio.ensure_future(
                    self._run_custom_mode_shell(spec["shell"], mode_name, action_name)
                )
            elif "action" in spec:
                self._run_custom_mode_action(spec["action"])

            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        # Unknown key — just exit mode and restore footer.
        self._refresh_current_tab()  # type: ignore[attr-defined]
        return True

    async def _run_custom_mode_shell(
        self, command: str, mode_name: str, action_name: str
    ) -> None:
        """Run a shell command from a custom mode sub-key.

        Args:
            command: Shell command to execute.
            mode_name: Name of the custom mode (for notification).
            action_name: Name of the sub-key action (for notification).
        """
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.wait()
            if proc.returncode == 0:
                self.notify(  # type: ignore[attr-defined]
                    f"{mode_name}: {action_name} completed",
                    severity="information",
                )
            else:
                self.notify(  # type: ignore[attr-defined]
                    f"{mode_name}: {action_name} failed (exit {proc.returncode})",
                    severity="error",
                )
        except Exception:
            log.exception("Custom mode %s action %s failed", mode_name, action_name)
            self.notify(  # type: ignore[attr-defined]
                f"{mode_name}: {action_name} error",
                severity="error",
            )

    def _run_custom_mode_action(self, action_name: str) -> None:
        """Run a built-in action from a custom mode sub-key.

        Args:
            action_name: The Textual action name to dispatch.
        """
        self.run_action(action_name)  # type: ignore[attr-defined]

    def _update_custom_mode_footer(self, mode_name: str) -> None:
        """Update the footer to show custom mode bindings.

        Args:
            mode_name: Name of the active custom mode.
        """
        from ..widgets import KeybindingFooter

        try:
            footer = self.query_one("#keybinding-footer", KeybindingFooter)  # type: ignore[attr-defined]
            footer.update_custom_mode_bindings(mode_name)
        except Exception:
            pass
