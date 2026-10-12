"""Archive fork, chat, and chooser entry points.

Entry seam for the Archive restore split. The public import path stays
:mod:`sase.ace.tui.actions.agents._archive_restore`, which re-exports this
module's public names.
"""

from __future__ import annotations

from typing import Any

from ._archive_restore_keys import hydrate_archive_candidate
from ._archive_restore_run import run_archive_restore
from ._archive_restore_support import archive_light_name, notify_owner
from ._archive_restore_types import (
    CHOICE_COPY_MORE,
    CHOICE_COPY_REF,
    CHOICE_FORK,
    CHOICE_OPEN_CHAT,
    CHOICE_RESTORE,
    CHOICE_RESTORE_SHOW,
)

__all__ = [
    "archive_chooser_model",
    "archive_fork_accepted",
    "fork_archive_agent",
    "open_archive_chat",
    "open_archive_chooser",
]


def archive_fork_accepted(agent: Any) -> bool:
    """Return whether the fork path accepts one hydrated Archive agent."""
    try:
        if bool(getattr(agent, "is_clan_container", False)):
            return False
        if not bool(getattr(agent, "is_agent_entry", False)):
            return False
    except Exception:
        return False
    try:
        from ._wait_helpers import action_agent_prompt_name

        if action_agent_prompt_name(agent):
            return True
    except Exception:
        pass
    try:
        return bool(getattr(agent, "agent_name", None))
    except Exception:
        return False


def fork_archive_agent(owner: Any, agent: Any) -> bool:
    """Prefill the fork prompt for one hydrated Archive agent."""
    from ._fork_scope import agent_prompt_target_scope
    from ._wait_helpers import action_agent_prompt_name

    try:
        reference = action_agent_prompt_name(agent) or getattr(
            agent, "agent_name", None
        )
    except Exception:
        reference = None
    if not reference:
        notify_owner(
            owner, "The selected archived run has no forkable name", severity="warning"
        )
        return False
    try:
        scope = agent_prompt_target_scope(
            agent, str(reference), history_fallback="fork"
        )
    except Exception:
        notify_owner(
            owner, "The selected archived run can't be forked", severity="warning"
        )
        return False
    prepare = getattr(owner, "_prepare_agent_prompt_target", None)
    if not callable(prepare):
        notify_owner(owner, "Fork is unavailable here", severity="warning")
        return False
    try:
        prepare(scope, action="fork")
    except Exception:
        notify_owner(owner, "Fork failed to start", severity="error")
        return False
    return True


def open_archive_chat(owner: Any, agent: Any) -> bool:
    """Open one hydrated Archive agent's chat in $EDITOR, read-only.

    Reading never revives, never marks anything read, and never writes: the
    opener only views the retained chat file.
    """
    if agent is None:
        notify_owner(owner, "Select an archived run first", severity="warning")
        return False
    try:
        response_path = getattr(agent, "response_path", None)
    except Exception:
        response_path = None
    if not response_path:
        notify_owner(owner, "No chat file found", severity="warning")
        return False
    opener = getattr(owner, "_open_agent_chat_paths", None)
    if not callable(opener):
        notify_owner(owner, "Open in editor is unavailable here", severity="warning")
        return False
    try:
        import os

        opener([os.path.expanduser(str(response_path))])
    except Exception:
        notify_owner(owner, "Open in editor failed", severity="error")
        return False
    return True


def archive_chooser_model(
    owner: Any, key: str
) -> tuple[tuple[Any, ...], int, str] | None:
    """Build the ⏎ chooser model for one Archive run key.

    Returns ``(choices, initial_index, title)`` or None when the key names
    no readable run. With Archive marks the default restores the marked set;
    when the row can't be restored the default falls to Open chat.
    """
    from ...modals.agent_action_chooser_modal import AgentActionChoice
    from ._archive_actions import archive_marked_count

    agent, light_row, reason = hydrate_archive_candidate(owner, key)
    if agent is None:
        return None
    can_restore = reason is None
    name = archive_light_name(light_row)
    try:
        marked = int(archive_marked_count(owner))
    except Exception:
        marked = 0
    fork_ok = archive_fork_accepted(agent)
    choices: list[Any] = []
    if can_restore:
        if marked > 0:
            restore_label = f"Restore {marked} marked"
            restore_detail = "shows them again · starts no new run"
        else:
            restore_label = "Restore to inbox"
            restore_detail = "shows it again · starts no new run"
        choices.extend(
            [
                AgentActionChoice(
                    result=CHOICE_RESTORE,
                    section="archive",
                    label=restore_label,
                    detail=restore_detail,
                    glyph="⌂",
                    glyph_style="",
                    badge=None,
                    badge_style=None,
                    age=None,
                    hotkey="r",
                ),
                AgentActionChoice(
                    result=CHOICE_RESTORE_SHOW,
                    section="archive",
                    label="Restore and show in inbox",
                    detail="reveals the agent in the Inbox",
                    glyph="⌂",
                    glyph_style="",
                    badge=None,
                    badge_style=None,
                    age=None,
                    hotkey="s",
                ),
            ]
        )
    if fork_ok:
        choices.append(
            AgentActionChoice(
                result=CHOICE_FORK,
                section="archive",
                label="Fork into a new agent",
                detail="starts a new run from this one",
                glyph="⑂",
                glyph_style="",
                badge=None,
                badge_style=None,
                age=None,
                hotkey="F",
            )
        )
    choices.extend(
        [
            AgentActionChoice(
                result=CHOICE_OPEN_CHAT,
                section="archive",
                label="Open chat in $EDITOR",
                detail="read-only",
                glyph="▤",
                glyph_style="",
                badge=None,
                badge_style=None,
                age=None,
                hotkey="e",
            ),
            AgentActionChoice(
                result=CHOICE_COPY_REF,
                section="archive",
                label="Copy @agent reference",
                detail=None,
                glyph="@",
                glyph_style="",
                badge=None,
                badge_style=None,
                age=None,
                hotkey="y",
            ),
            AgentActionChoice(
                result=CHOICE_COPY_MORE,
                section="archive",
                label="More copy targets",
                detail=None,
                glyph="%",
                glyph_style="",
                badge=None,
                badge_style=None,
                age=None,
                hotkey="%",
            ),
        ]
    )
    initial = 0
    if not can_restore:
        initial = next(
            (
                index
                for index, choice in enumerate(choices)
                if choice.result == CHOICE_OPEN_CHAT
            ),
            0,
        )
    return tuple(choices), initial, f"Act on {name} · archived"


def open_archive_chooser(owner: Any, key: str) -> bool:
    """Push the ARCHIVE chooser for one Archive run key. False when refused."""
    model = archive_chooser_model(owner, key)
    if model is None:
        notify_owner(
            owner,
            "Archive entry unreadable — Record only",
            severity="warning",
        )
        return False
    choices, initial, title = model

    def _on_choice(result_key: str | None) -> None:
        if result_key is None:
            return
        if result_key == CHOICE_RESTORE:
            run_archive_restore(owner)
        elif result_key == CHOICE_RESTORE_SHOW:
            run_archive_restore(owner, and_show=True)
        elif result_key == CHOICE_FORK:
            from ._archive_actions import archive_read_target

            try:
                target = archive_read_target(owner)
            except Exception:
                target = None
            if target is None:
                notify_owner(
                    owner, "Archived run is no longer selected", severity="warning"
                )
                return
            fork_archive_agent(owner, target)
        elif result_key == CHOICE_OPEN_CHAT:
            from ._archive_actions import archive_read_target

            try:
                target = archive_read_target(owner)
            except Exception:
                target = None
            if target is None:
                notify_owner(
                    owner, "Archived run is no longer selected", severity="warning"
                )
                return
            open_archive_chat(owner, target)
        elif result_key == CHOICE_COPY_REF:
            copier = getattr(owner, "_copy_agent_reference", None)
            if callable(copier):
                try:
                    copier()
                except Exception:
                    notify_owner(owner, "Copy failed", severity="error")
            else:
                notify_owner(owner, "Copy is unavailable here", severity="warning")
        elif result_key == CHOICE_COPY_MORE:
            palette = getattr(owner, "action_copy_tab_content", None)
            if callable(palette):
                try:
                    palette()
                except Exception:
                    notify_owner(owner, "Copy palette failed", severity="error")
            else:
                notify_owner(
                    owner, "Copy palette is unavailable here", severity="warning"
                )

    try:
        from ...modals.agent_action_chooser_modal import AgentActionChooserModal

        push = getattr(owner, "push_screen", None)
        if not callable(push):
            return False
        push(
            AgentActionChooserModal(choices, title=title, initial_index=initial),
            _on_choice,
        )
    except Exception:
        return False
    return True
