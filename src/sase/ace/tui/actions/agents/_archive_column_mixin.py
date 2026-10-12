"""Archive column mixin and cheap Inbox probes.

Lives in its own module so ``AgentsMixinCore`` can inherit the mixin
without importing ``_archive_view`` or ``agent_archive_view`` on the TUI
app import path. Inbox ``j``/``k`` calls :func:`agents_archive_is_active`
(one attribute read) before any Archive column or view import. Every
handler uses a use-site import.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "AgentArchiveColumnMixin",
    "agents_archive_is_active",
    "agents_inbox_detail_allowed",
    "cancel_inbox_detail_debounce",
    "route_archive_key_if_active",
    "schedule_owned_inbox_detail_update",
    "scheduled_agents_detail_is_current",
]


def agents_archive_is_active(owner: Any) -> bool:
    """Return whether the Agents tab is showing Archive, without imports."""
    return (
        getattr(getattr(owner, "_agents_archive_view", None), "active_view", None)
        == "archive"
    )


def agents_inbox_detail_allowed(owner: Any) -> bool:
    """Return whether Inbox-originated detail rendering may paint.

    The Inbox path is a single attribute read. The Archive path loads the
    view module only when Archive is actually showing, so it can honor the
    beta flag.
    """
    if not agents_archive_is_active(owner):
        return True
    from ._archive_view import agents_inbox_detail_allowed as impl

    return impl(owner)


def cancel_inbox_detail_debounce(owner: Any) -> bool:
    """Cancel the pending Inbox detail debounce, never an Archive hydration."""
    if agents_archive_is_active(owner):
        from ._archive_view import cancel_inbox_detail_debounce as impl

        return impl(owner)
    debouncer = getattr(owner, "_agent_detail_debouncer", None)
    cancel = getattr(debouncer, "cancel", None)
    if not callable(cancel):
        return False
    cancel()
    return True


def schedule_owned_inbox_detail_update(owner: Any) -> None:
    """Record a fresh owner token, then schedule the shared detail debouncer."""
    from ._archive_view import schedule_owned_inbox_detail_update as impl

    impl(owner)


def scheduled_agents_detail_is_current(owner: Any) -> bool:
    """Return whether the pending debounced update still owns the panel."""
    from ._archive_view import scheduled_agents_detail_is_current as impl

    return impl(owner)


def route_archive_key_if_active(owner: Any, intent: str) -> bool:
    """Route an Archive list key. False on Inbox without importing Archive."""
    if getattr(owner, "current_tab", "agents") != "agents":
        return False
    if not agents_archive_is_active(owner):
        return False
    from ._archive_view import route_archive_key

    return route_archive_key(owner, intent)


class AgentArchiveColumnMixin:
    """Textual message handlers for the Archive column widgets.

    Handlers defer to the column code so the Inbox-only startup path never
    imports it.
    """

    def on_archive_list_cursor_moved(self, event: Any) -> None:
        from ._archive_column_nav import archive_cursor_from_widget

        archive_cursor_from_widget(self, event.key)

    def on_archive_list_item_activated(self, event: Any) -> None:
        from ._archive_column_nav import archive_activate_key

        archive_activate_key(self, event.key)

    def on_archive_pulse_activated(self, event: Any) -> None:
        from ._archive_column_nav import archive_activate_pulse

        archive_activate_pulse(self)

    def action_open_agents_archive(self) -> None:
        """Open Agents Archive, switching to Agents when needed."""
        from ...models.agent_archive_view import agents_archive_view_enabled
        from ._archive_view import open_agents_archive_view

        if not agents_archive_view_enabled():
            return
        opening = not agents_archive_is_active(self)
        capture = getattr(self, "_current_link_trail_origin", None)
        origin = capture() if opening and callable(capture) else None
        if getattr(self, "current_tab", None) != "agents":
            save_position = getattr(self, "_save_current_tab_position", None)
            if callable(save_position):
                save_position()
            switch = getattr(self, "_switch_to_tab", None)
            if callable(switch):
                switch("agents")
        open_agents_archive_view(self)
        if opening:
            record = getattr(self, "_record_link_trail", None)
            if origin is not None and callable(record):
                record(origin)
            notify = getattr(self, "notify", None)
            if callable(notify):
                notify(
                    "Opened the Archive — dismissed runs open read-only · ctrl+o back",
                    severity="information",
                )

    def action_back_to_agents_inbox(self) -> None:
        """Return from Archive to the parked Inbox."""
        from ._archive_view import close_agents_archive_view

        if agents_archive_is_active(self):
            if getattr(self, "current_tab", None) != "agents":
                save_position = getattr(self, "_save_current_tab_position", None)
                if callable(save_position):
                    save_position()
                switch = getattr(self, "_switch_to_tab", None)
                if callable(switch):
                    switch("agents")
            close_agents_archive_view(self)

    def action_toggle_agents_archive(self) -> None:
        """Open Archive from another tab, or toggle the Agents view in place."""
        from ...models.agent_archive_view import agents_archive_view_enabled
        from ._archive_view import close_agents_archive_view, open_agents_archive_view

        if not agents_archive_view_enabled():
            return
        if getattr(self, "current_tab", None) != "agents":
            self.action_open_agents_archive()
        elif agents_archive_is_active(self):
            close_agents_archive_view(self)
        else:
            open_agents_archive_view(self)
