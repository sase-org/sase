"""Archive fork, chat, and chooser entry points.

Entry seam for the Archive restore split. The public import path stays
:mod:`sase.ace.tui.actions.agents._archive_restore`, which re-exports this
module's public names.
"""

from __future__ import annotations

import asyncio
from typing import Any

from ...models.agent_archive_view import (
    container_key_of,
    is_archive_container_key,
)
from ...util.pump_tasks import spawn_pump_free_task
from ._archive_restore_keys import hydrate_archive_candidate
from ._archive_restore_run import run_archive_restore, run_archive_restore_async
from ._archive_restore_support import archive_light_name, notify_owner
from ._archive_restore_types import (
    CHOICE_COPY_MORE,
    CHOICE_COPY_REF,
    CHOICE_FORK,
    CHOICE_OPEN_CHAT,
    CHOICE_RESTORE,
    CHOICE_RESTORE_SHOW,
)

_CHOOSER_TASK_NAME = "archive-chooser-hydrate"
_CHOOSER_TASK_REGISTRY = "_archive_chooser_tasks"

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
    named = False
    try:
        from ._wait_helpers import action_agent_prompt_name

        named = bool(action_agent_prompt_name(agent))
    except Exception:
        named = False
    if not named:
        try:
            named = bool(getattr(agent, "agent_name", None))
        except Exception:
            named = False
    if not named:
        return False
    try:
        if getattr(agent, "response_path", None):
            return True
    except Exception:
        pass
    try:
        getter = getattr(agent, "get_response_content", None)
        if callable(getter) and getter():
            return True
    except Exception:
        pass
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


def _marked_restore_targets(owner: Any) -> list[str]:
    """Return marked restore keys after dropping container rows."""
    try:
        from ._archive_actions import archive_marked_run_keys

        marked = [key for key in archive_marked_run_keys(owner) if key]
    except Exception:
        marked = []
    return [key for key in marked if not is_archive_container_key(key)]


def _container_restore_label(owner: Any, key: str, light_row: Any) -> str:
    """Return the Restore label for one clan or session container."""
    container_key = container_key_of(key) or ""
    kind = "session" if container_key.startswith("session:") else "clan"
    name = archive_light_name(light_row)
    count = 0
    try:
        count = int((light_row or {}).get("member_count") or 0)
    except Exception:
        count = 0
    if count <= 0 and container_key:
        try:
            from ._archive_column import archive_container_members

            count = len(archive_container_members(owner, container_key))
        except Exception:
            count = 0
    noun = "member" if count == 1 else "members"
    return f"Restore {kind} {name} ({count} {noun})"


def _hydrate_chooser_candidate(
    owner: Any, key: str
) -> tuple[Any | None, Any | None, str | None]:
    """Return ``(agent, light_row, reason)`` without hydrating containers."""
    if is_archive_container_key(key):
        try:
            from ._archive_column import archive_light_row

            light_row = archive_light_row(owner, key)
        except Exception:
            light_row = None
        return None, light_row, None
    return hydrate_archive_candidate(owner, key)


def archive_chooser_model(
    owner: Any,
    key: str,
    *,
    hydrated: tuple[Any | None, Any | None, str | None] | None = None,
) -> tuple[tuple[Any, ...], int, str] | None:
    """Build the ⏎ chooser model for one Archive run key.

    Returns ``(choices, initial_index, title)`` or None when the key names
    no readable run and no marks exist. With Archive marks the default
    restores the marked set; when the row can't be restored the default
    falls to Open chat.
    """
    from ...modals.agent_action_chooser_modal import AgentActionChoice

    is_container = is_archive_container_key(key)
    if hydrated is not None:
        agent, light_row, reason = hydrated
    else:
        agent, light_row, reason = _hydrate_chooser_candidate(owner, key)
    marked_targets = _marked_restore_targets(owner)
    marked_n = len(marked_targets)
    if agent is None and not is_container and marked_n == 0:
        return None
    name = archive_light_name(light_row)
    fork_ok = (not is_container) and agent is not None and archive_fork_accepted(agent)
    offer_restore = (
        marked_n > 0 or is_container or (reason is None and agent is not None)
    )
    choices: list[Any] = []
    if offer_restore:
        if marked_n > 0:
            restore_label = f"Restore {marked_n} marked"
            restore_detail = "shows them again · starts no new run"
        elif is_container:
            restore_label = _container_restore_label(owner, key, light_row)
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
    if agent is not None and not is_container:
        choices.extend(
            [
                AgentActionChoice(
                    result=CHOICE_OPEN_CHAT,
                    section="read",
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
                    section="read",
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
                    section="read",
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
    if not choices:
        return None
    initial = 0
    if not offer_restore:
        initial = next(
            (
                index
                for index, choice in enumerate(choices)
                if choice.result == CHOICE_OPEN_CHAT
            ),
            0,
        )
    return tuple(choices), initial, f"Act on {name} · archived"


def _archive_generation(owner: Any) -> int:
    try:
        view = getattr(owner, "_agents_archive_view", None)
        return int(getattr(view, "generation", 0))
    except Exception:
        return 0


def _chooser_selection_is_current(owner: Any, key: str, generation: int) -> bool:
    """Return whether the Archive selection still matches ``key``."""
    try:
        from ._archive_view import agents_archive_view_state

        state = agents_archive_view_state(owner)
    except Exception:
        return True
    try:
        if int(getattr(state, "generation", -1)) != generation:
            return False
        current = getattr(getattr(state, "archive", None), "selected_key", None)
    except Exception:
        return True
    if current is not None and current != key:
        return False
    return True


def _copy_captured_agent_reference(owner: Any, agent: Any) -> None:
    """Copy ``agent``'s durable reference without re-reading the selection."""
    if agent is None:
        notify_owner(owner, "Archived run is no longer selected", severity="warning")
        return
    try:
        from ..clipboard._artifact_reference_resolution import reference_for_agent_row
        from ..clipboard._delivery import schedule_copy_delivery
    except Exception:
        notify_owner(owner, "Copy is unavailable here", severity="warning")
        return
    try:
        reference = reference_for_agent_row(agent)
    except Exception:
        reference = None
    if not reference:
        notify_owner(
            owner, "The selected agent has no durable agent name", severity="warning"
        )
        return
    try:
        schedule_copy_delivery(
            owner,
            f"@{reference}",
            copied_label=f"agent reference ({reference})",
            task_name="sase-copy-agent-reference",
        )
    except Exception:
        notify_owner(owner, "Copy failed", severity="error")


def _submit_archive_restore(owner: Any, *, and_show: bool = False) -> None:
    """Submit the Archive restore from the chooser without blocking the loop.

    The submit-time capability re-check reads bundles off-thread, so the
    chooser spawns the async submit when a loop is running and restores
    synchronously otherwise (tests and loop-free callers).
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        run_archive_restore(owner, and_show=and_show)
        return

    async def _submit() -> None:
        await run_archive_restore_async(owner, and_show=and_show)

    spawner = getattr(owner, "_archive_spawn", None)
    if callable(spawner):
        spawner(
            owner,
            _submit(),
            name="archive-restore-submit",
            registry_attr=_CHOOSER_TASK_REGISTRY,
        )
    else:
        spawn_pump_free_task(
            owner,
            _submit(),
            name="archive-restore-submit",
            registry_attr=_CHOOSER_TASK_REGISTRY,
        )


def _present_archive_chooser(
    owner: Any,
    key: str,
    hydrated: tuple[Any | None, Any | None, str | None],
) -> bool:
    """Push the Archive chooser for a already-hydrated candidate."""
    model = archive_chooser_model(owner, key, hydrated=hydrated)
    if model is None:
        notify_owner(
            owner,
            "Archive entry unreadable — Record only",
            severity="warning",
        )
        return False
    choices, initial, title = model
    captured_agent = hydrated[0]

    def _on_choice(result_key: str | None) -> None:
        if result_key is None:
            return
        if result_key == CHOICE_RESTORE:
            _submit_archive_restore(owner)
        elif result_key == CHOICE_RESTORE_SHOW:
            _submit_archive_restore(owner, and_show=True)
        elif result_key == CHOICE_FORK:
            if captured_agent is None:
                notify_owner(
                    owner, "Archived run is no longer selected", severity="warning"
                )
                return
            fork_archive_agent(owner, captured_agent)
        elif result_key == CHOICE_OPEN_CHAT:
            if captured_agent is None:
                notify_owner(
                    owner, "Archived run is no longer selected", severity="warning"
                )
                return
            open_archive_chat(owner, captured_agent)
        elif result_key == CHOICE_COPY_REF:
            _copy_captured_agent_reference(owner, captured_agent)
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


def open_archive_chooser(owner: Any, key: str) -> bool:
    """Push the ARCHIVE chooser for one Archive run key. False when refused."""
    generation = _archive_generation(owner)

    def _hydrate() -> tuple[Any | None, Any | None, str | None]:
        return _hydrate_chooser_candidate(owner, key)

    def _present(hydrated: tuple[Any | None, Any | None, str | None]) -> bool:
        if not _chooser_selection_is_current(owner, key, generation):
            return False
        return _present_archive_chooser(owner, key, hydrated)

    if is_archive_container_key(key):
        return _present(_hydrate())

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return _present(_hydrate())

    async def _hydrate_and_present() -> None:
        runner = getattr(owner, "_archive_run_off_thread", None)
        if callable(runner):
            hydrated = await runner(_hydrate)
        else:
            hydrated = await asyncio.to_thread(_hydrate)
        if not _chooser_selection_is_current(owner, key, generation):
            return
        _present(hydrated)

    spawner = getattr(owner, "_archive_spawn", None)
    if callable(spawner):
        spawner(
            owner,
            _hydrate_and_present(),
            name=_CHOOSER_TASK_NAME,
            registry_attr=_CHOOSER_TASK_REGISTRY,
        )
    else:
        spawn_pump_free_task(
            owner,
            _hydrate_and_present(),
            name=_CHOOSER_TASK_NAME,
            registry_attr=_CHOOSER_TASK_REGISTRY,
        )
    return True
