"""Idle hot-spare lifecycle for the agent prompt input bar."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...widgets.prompt_input_bar import PromptInputBar


class PromptBarSpareMixin:
    """Mount / reveal / discard the idle-mounted inert hidden spare bar."""

    # Phase ``space-hot-spare``: one idle-mounted inert hidden bar. Only
    # ``AceApp`` enables scheduling; harnesses composing this mixin without
    # the flag stay spare-free.
    _prompt_bar_spare_enabled: bool = False
    _prompt_bar_spare: PromptInputBar | None
    _prompt_bar_spare_timer: object | None
    # Phase ``tick-compare-skip``: matches the ``EventHandlersBase``
    # declaration; maintained by ``PromptInputBar`` mount/unmount hooks
    # and ``_detach_prompt_bar``.
    _active_prompt_bar: PromptInputBar | None

    def _schedule_prompt_bar_spare(self, *, reason: str = "unknown") -> None:
        """Schedule one idle spare-mount attempt, re-armed until it lands."""
        del reason
        try:
            if not bool(getattr(self, "_prompt_bar_spare_enabled", False)):
                return
            if getattr(self, "_prompt_bar_spare_timer", None) is not None:
                return
            delay = 0.1
            try:
                gate = getattr(self, "_nav_gate", None)
                if gate is not None and hasattr(gate, "time_until_idle"):
                    delay = max(0.05, float(gate.time_until_idle()) + 0.05)
            except Exception:  # noqa: BLE001 - nav gate read is best-effort.
                delay = 0.1
            setter = getattr(self, "set_timer", None)
            if not callable(setter):
                return

            def _fire() -> None:
                try:
                    self._prompt_bar_spare_timer = None  # type: ignore[attr-defined]
                except Exception:  # noqa: BLE001 - timer state is best-effort.
                    pass
                try:
                    self._maybe_mount_prompt_bar_spare()  # type: ignore[attr-defined]
                except Exception:  # noqa: BLE001 - spare mount never breaks callers.
                    pass

            try:
                self._prompt_bar_spare_timer = setter(  # type: ignore[attr-defined]
                    delay, _fire, name="prompt-bar-spare"
                )
            except Exception:  # noqa: BLE001 - timer scheduling is best-effort.
                try:
                    self._prompt_bar_spare_timer = None  # type: ignore[attr-defined]
                except Exception:  # noqa: BLE001 - timer state is best-effort.
                    pass
        except Exception:  # noqa: BLE001 - spare scheduling never breaks callers.
            pass

    def _spare_is_ready(self) -> PromptInputBar | None:
        """Return the mounted inert spare, or ``None`` when none is ready."""
        try:
            spare = getattr(self, "_prompt_bar_spare", None)
        except Exception:  # noqa: BLE001 - spare read is best-effort.
            return None
        if spare is None:
            return None
        try:
            if not bool(getattr(spare, "is_mounted", False)):
                return None
            if not bool(getattr(spare, "_is_prompt_spare", False)):
                return None
        except Exception:  # noqa: BLE001 - spare state is best-effort.
            return None
        return spare

    def _maybe_mount_prompt_bar_spare(self) -> None:
        """Mount one inert hidden spare when every idle gate holds."""
        try:
            if not bool(getattr(self, "_prompt_bar_spare_enabled", False)):
                return
            if not bool(getattr(self, "_mount_state_loads_done", False)):
                self._schedule_prompt_bar_spare(reason="loads-not-done")  # type: ignore[attr-defined]
                return
            try:
                gate = getattr(self, "_nav_gate", None)
                if gate is not None and callable(getattr(gate, "is_navigating", None)):
                    if bool(gate.is_navigating()):
                        self._schedule_prompt_bar_spare(reason="navigating")  # type: ignore[attr-defined]
                        return
            except Exception:  # noqa: BLE001 - nav gate is best-effort.
                pass
            try:
                active_check = getattr(self, "_prompt_input_active", None)
                if callable(active_check) and bool(active_check()):
                    self._schedule_prompt_bar_spare(reason="prompt-active")  # type: ignore[attr-defined]
                    return
            except Exception:  # noqa: BLE001 - active check is best-effort.
                pass
            try:
                from textual.screen import ModalScreen

                if isinstance(getattr(self, "screen", None), ModalScreen):
                    self._schedule_prompt_bar_spare(reason="modal")  # type: ignore[attr-defined]
                    return
            except Exception:  # noqa: BLE001 - modal check is best-effort.
                pass
            if self._spare_is_ready() is not None:  # type: ignore[attr-defined]
                return
            try:
                if getattr(self, "_prompt_bar_spare", None) is not None:
                    # Stale reference (unmounted without clearing): drop it
                    # and retry once instead of stacking a second bar.
                    try:
                        self._discard_prompt_bar_spare()  # type: ignore[attr-defined]
                    except Exception:  # noqa: BLE001 - discard is best-effort.
                        pass
                    if getattr(self, "_prompt_bar_spare", None) is not None:
                        return
            except Exception:  # noqa: BLE001 - spare state is best-effort.
                pass
            from ...widgets import PromptInputBar

            bar = PromptInputBar()
            try:
                bar._is_prompt_spare = True  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001 - spare flag is best-effort.
                pass
            try:
                bar.display = False  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001 - display is best-effort.
                pass
            try:
                bar.can_focus_children = False  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001 - focus gate is best-effort.
                pass
            try:
                self._prompt_bar_spare = bar  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001 - spare state is best-effort.
                pass
            try:
                self.mount(bar)  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001 - mount failure clears the slot.
                try:
                    if getattr(self, "_prompt_bar_spare", None) is bar:
                        self._prompt_bar_spare = None  # type: ignore[attr-defined]
                except Exception:  # noqa: BLE001 - spare state is best-effort.
                    pass
        except Exception:  # noqa: BLE001 - spare mount never breaks callers.
            pass

    def _discard_prompt_bar_spare(self) -> None:
        """Synchronously drop a leftover spare without history or focus work."""
        # Cancel a pending spare-mount timer first: a fresh mount must not
        # race a spare that would otherwise land mid-mount (before the new
        # bar publishes ``_active_prompt_bar``) and steal focus or collide.
        try:
            timer = getattr(self, "_prompt_bar_spare_timer", None)
            if timer is not None:
                try:
                    stop = getattr(timer, "stop", None)
                    if callable(stop):
                        stop()
                except Exception:  # noqa: BLE001 - timer stop is best-effort.
                    pass
                try:
                    self._prompt_bar_spare_timer = None  # type: ignore[attr-defined]
                except Exception:  # noqa: BLE001 - spare state is best-effort.
                    pass
        except Exception:  # noqa: BLE001 - discard never breaks callers.
            pass
        try:
            spare = getattr(self, "_prompt_bar_spare", None)
        except Exception:  # noqa: BLE001 - spare read is best-effort.
            return
        if spare is None:
            return
        try:
            self._prompt_bar_spare = None  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - spare state is best-effort.
            pass
        try:
            parent = getattr(spare, "_parent", None)
            if parent is not None:
                try:
                    parent._nodes._remove(spare)
                except Exception:  # noqa: BLE001 - already detached.
                    pass
            try:
                spare.remove()  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001 - removal is best-effort.
                pass
        except Exception:  # noqa: BLE001 - discard never breaks callers.
            pass

    def _try_reveal_prompt_bar_spare(
        self,
        initial_text: str = "",
        display_name: str = "~",
        history_sort_key: str = "home",
    ) -> bool:
        """Reveal the idle spare as the plain home prompt; ``False`` to fresh-mount."""
        try:
            spare = self._spare_is_ready()  # type: ignore[attr-defined]
            if spare is None:
                return False
            self._setup_home_prompt_context(  # type: ignore[attr-defined]
                display_name=display_name,
                history_sort_key=history_sort_key,
            )
            try:
                area = spare.active_text_area()  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001 - no active pane means fresh-mount.
                return False
            try:
                area.load_text(initial_text)
            except Exception:  # noqa: BLE001 - seeding failure means fresh-mount.
                return False
            try:
                sync = getattr(spare, "_sync_state_from_widgets", None)
                if callable(sync):
                    sync()
            except Exception:  # noqa: BLE001 - model sync is best-effort.
                pass
            try:
                spare.display = True  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001 - reveal is best-effort.
                pass
            try:
                spare.can_focus_children = True  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001 - reveal is best-effort.
                pass
            try:
                spare._is_prompt_spare = False  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001 - spare flag is best-effort.
                pass
            try:
                self._prompt_bar_spare = None  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001 - spare state is best-effort.
                pass
            try:
                self._active_prompt_bar = spare  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001 - explicit state is best-effort.
                pass
            try:
                activate = getattr(spare, "activate", None)
                if callable(activate):
                    activate()
                else:
                    # Fallback: publish without full activation (never expected).
                    self._active_prompt_bar = spare  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001 - activation failure means fresh-mount.
                return True
            return True
        except Exception:  # noqa: BLE001 - reveal never breaks the key handler.
            return False
