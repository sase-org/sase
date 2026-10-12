"""Restore, fork, and copy entry points for Archive rows (sase-1jm.5).

Chooser and bulk-restore seam for the Agents Archive epic. While the Archive
owns the Agents tab, ``⏎`` opens the ``AgentActionChooserModal`` with an
ARCHIVE section first (Restore to inbox, Restore and show, Fork, Open chat,
Copy). Restore hydrates the selected bundles synchronously (one small JSON
read per run, the same order of work as the existing revive path), re-checks
the ``durably_revivable`` capability just before submitting, revives through
the existing ``_do_revive_agent(s)`` execution, and keeps every restored row
in place behind the ``⌂ restored`` overlay. The Inbox is never read or
written here except by an explicit Restore-and-show.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

CHOICE_RESTORE = "archive-restore"
CHOICE_RESTORE_SHOW = "archive-restore-show"
CHOICE_FORK = "archive-fork"
CHOICE_OPEN_CHAT = "archive-open-chat"
CHOICE_COPY_REF = "archive-copy-ref"
CHOICE_COPY_MORE = "archive-copy-more"


@dataclass(frozen=True, slots=True)
class ArchiveRestoreSkip:
    """One requested restore that did not run, with its user-facing reason."""

    key: str
    name: str
    reason: str


@dataclass(frozen=True, slots=True)
class ArchiveRestoreSummary:
    """Outcome of one Archive restore submission for toasts and tests."""

    restored: tuple[tuple[str, str], ...]
    skipped: tuple[ArchiveRestoreSkip, ...]
    failed: tuple[tuple[str, str, str], ...]
    and_show: bool = False


def _notify(owner: Any, message: str, *, severity: str = "information") -> None:
    notify = getattr(owner, "notify", None)
    if callable(notify):
        try:
            notify(message, severity=severity)
        except Exception:
            pass


def _light_name(light_row: Any) -> str:
    if light_row is None:
        return "archived run"
    try:
        return str(
            light_row.get("agent_name") or light_row.get("name") or "archived run"
        )
    except Exception:
        return "archived run"


def collect_archive_restore_keys(
    owner: Any,
) -> tuple[list[str], list[ArchiveRestoreSkip]]:
    """Return the restore target keys in priority order plus nav-item skips.

    Marked runs (containers expanded to their loaded members) win over the
    cursor. A container cursor restores its loaded members. Banners, page
    tails, and the Inbox pulse are navigable but never runs, so they resolve
    to a skip, never to the parked Inbox.
    """
    from ...models.agent_archive_list import archive_row_key
    from ...models.agent_archive_view import (
        ARCHIVE_SECTION_PULSE,
        container_key_of,
        is_archive_container_key,
        is_archive_row_key,
    )

    skipped: list[ArchiveRestoreSkip] = []
    try:
        from ._archive_actions import archive_marked_run_keys

        marked = [key for key in archive_marked_run_keys(owner) if key]
    except Exception:
        marked = []
    if marked:
        keys = [key for key in marked if not is_archive_container_key(key)]
        return keys, skipped

    try:
        from ._archive_view import agents_archive_view_state

        state = agents_archive_view_state(owner)
        key = state.archive.selected_key
        pulse_focused = state.archive.focused_section == ARCHIVE_SECTION_PULSE
    except Exception:
        return [], skipped
    if pulse_focused:
        key = None
    if not key or not is_archive_row_key(key):
        label = "selection"
        try:
            from ._archive_column import archive_light_row

            label = _light_name(archive_light_row(owner, key))
        except Exception:
            pass
        return [], [
            ArchiveRestoreSkip(
                key=str(key or ""), name=label, reason="not an archived run"
            )
        ]
    if is_archive_container_key(key):
        container_key = container_key_of(key)
        members: tuple[Any, ...] = ()
        if container_key is not None:
            try:
                from ._archive_column import archive_container_members

                members = archive_container_members(owner, container_key)
            except Exception:
                members = ()
        member_keys = []
        for member in members:
            try:
                member_key = archive_row_key(member)
            except Exception:
                member_key = None
            if member_key:
                member_keys.append(member_key)
        if not member_keys:
            try:
                from ._archive_column import archive_light_row

                name = _light_name(archive_light_row(owner, key))
            except Exception:
                name = "container"
            return [], [
                ArchiveRestoreSkip(
                    key=key,
                    name=name,
                    reason="no loaded members — expand the container (l) first",
                )
            ]
        return member_keys, skipped
    return [key], skipped


def hydrate_archive_candidate(
    owner: Any, key: str
) -> tuple[Any | None, Any | None, str | None]:
    """Return ``(agent, light_row, skip_reason)`` for one restore key.

    The bundle read is one small JSON file, the same order of work as the
    existing revive path's artifact restore. Never writes. The agent is
    returned even when unrestorable so the chooser can still offer Open
    chat, Fork, and Copy; only an unreadable bundle yields no agent. The
    light row's ``restorable`` chip never decides: the corpus row may be
    stale, so the hydrated agent's capability is re-checked just before
    submitting.
    """
    try:
        from ._archive_column import archive_light_row
        from ._archive_reader import _load_archive_bundle

        light_row = archive_light_row(owner, key)
    except Exception:
        return None, None, "row is no longer listed"
    if light_row is None:
        return None, None, "row is no longer listed"
    try:
        bundle = _load_archive_bundle(owner, light_row)
    except Exception:
        return None, light_row, "bundle unreadable"
    agent = bundle.get("agent") if bundle else None
    if bundle is None or bundle.get("unreadable") or agent is None:
        return None, light_row, "bundle unreadable"
    if not bool(getattr(agent, "durably_revivable", True)):
        return agent, light_row, "can't restore"
    return agent, light_row, None


def _failed_identities(delta: Any) -> set[Any]:
    failed = set()
    try:
        for failure in getattr(delta, "failed", None) or ():
            identity = getattr(failure, "identity", None)
            if identity is not None:
                failed.add(identity)
    except Exception:
        pass
    return failed


def _submit_revive(owner: Any, agents: list[Any]) -> Any | None:
    batch = getattr(owner, "_do_revive_agents", None)
    if callable(batch):
        try:
            return batch(list(agents))
        except Exception:
            return None
    single = getattr(owner, "_do_revive_agent", None)
    if not callable(single):
        return None
    revived: list[Any] = []
    failed: list[Any] = []
    for agent in agents:
        try:
            delta = single(agent)
        except Exception:
            continue
        if delta is None:
            continue
        revived.extend(getattr(delta, "revived", None) or ())
        failed.extend(getattr(delta, "failed", None) or ())
    from ._revive_delta import AgentReviveDelta

    return AgentReviveDelta(revived=tuple(revived), failed=tuple(failed))


def _refresh_archive_chrome(owner: Any) -> None:
    try:
        from ._archive_column import refresh_archive_footer

        refresh_archive_footer(owner)
    except Exception:
        pass


def run_archive_restore(
    owner: Any, *, keys: list[str] | None = None, and_show: bool = False
) -> ArchiveRestoreSummary:
    """Restore Archive runs to the Inbox and keep their rows in place.

    Returns a summary for toasts and tests. The cursor never moves: every
    restored row stays in the list behind the ``⌂ restored`` overlay until
    the query changes or the Archive is left, and the pulse counts the agent
    through the revive path's own inbox refresh.
    """
    from ._archive_view import mark_archive_row_restored

    targets, skipped = (
        (list(keys), []) if keys is not None else collect_archive_restore_keys(owner)
    )
    skips = list(skipped)
    submittable: list[tuple[str, str, Any]] = []
    for key in targets:
        agent, light_row, reason = hydrate_archive_candidate(owner, key)
        name = _light_name(light_row)
        if agent is None or reason is not None:
            skips.append(
                ArchiveRestoreSkip(key=key, name=name, reason=reason or "skipped")
            )
        else:
            submittable.append((key, name, agent))
    if not submittable:
        summary = ArchiveRestoreSummary(restored=(), skipped=tuple(skips), failed=())
        _toast_restore(owner, summary)
        return summary

    delta = _submit_revive(owner, [agent for _key, _name, agent in submittable])
    if delta is None:
        unavailable = tuple(
            (key, name, "revive is unavailable") for key, name, _agent in submittable
        )
        summary = ArchiveRestoreSummary(
            restored=(), skipped=tuple(skips), failed=unavailable, and_show=and_show
        )
        _toast_restore(owner, summary)
        return summary

    failed_ids = _failed_identities(delta)
    restored: list[tuple[str, str]] = []
    failures: list[tuple[str, str, str]] = []
    for key, name, agent in submittable:
        try:
            identity = getattr(agent, "identity", None)
        except Exception:
            identity = None
        if identity is not None and identity in failed_ids:
            message = "revive failed"
            try:
                for failure in getattr(delta, "failed", None) or ():
                    if getattr(failure, "identity", None) == identity:
                        message = str(getattr(failure, "message", None) or message)
                        break
            except Exception:
                pass
            failures.append((key, name, message))
        else:
            restored.append((key, name))
            try:
                mark_archive_row_restored(owner, key)
            except Exception:
                pass
    summary = ArchiveRestoreSummary(
        restored=tuple(restored),
        skipped=tuple(skips),
        failed=tuple(failures),
        and_show=and_show,
    )
    _refresh_archive_chrome(owner)
    if and_show and len(restored) == 1 and not failures:
        _show_restored_in_inbox(owner, submittable[0][2], restored[0][1])
    else:
        _toast_restore(owner, summary)
    return summary


def _toast_restore(owner: Any, summary: ArchiveRestoreSummary) -> None:
    total = len(summary.restored)
    if total == 1 and not summary.skipped and not summary.failed:
        _notify(
            owner,
            f"{summary.restored[0][1]} is back in the inbox · no new run started",
        )
        return
    if total == 0 and len(summary.skipped) == 1 and not summary.failed:
        skip = summary.skipped[0]
        _notify(
            owner, f"Nothing restored — {skip.name}: {skip.reason}", severity="warning"
        )
        return
    parts = [f"Restored {total}"]
    if summary.skipped:
        reasons: dict[str, int] = {}
        for skip in summary.skipped:
            reasons[skip.reason] = reasons.get(skip.reason, 0) + 1
        detail = ", ".join(
            f"{reason} ×{count}" for reason, count in sorted(reasons.items())
        )
        parts.append(f"skipped {len(summary.skipped)} ({detail})")
    else:
        parts.append("skipped 0")
    if summary.failed:
        parts.append(f"failed {len(summary.failed)}")
    else:
        parts.append("failed 0")
    _notify(
        owner,
        " · ".join(parts),
        severity="warning" if total == 0 else "information",
    )


def _show_restored_in_inbox(owner: Any, agent: Any, name: str) -> None:
    """Leave the Archive and reveal one restored agent in the Inbox."""
    try:
        from ._archive_view import close_agents_archive_view

        close_agents_archive_view(owner)
    except Exception:
        pass
    revealed = False
    select = getattr(owner, "_select_revived_agent", None)
    if callable(select):
        try:
            revealed = bool(select(agent))
        except Exception:
            revealed = False
    refresh = getattr(owner, "_refresh_agents_display", None)
    if callable(refresh):
        try:
            refresh(list_changed=False)
        except Exception:
            pass
    if revealed:
        _notify(owner, f"{name} is back in the inbox · showing in Inbox")
        return
    # Unrevealed covers two cases: the parked Inbox filter hides the row,
    # or the revive reload has not landed yet (its own scheduled refresh
    # reveals the row when it does). Only claim the filter when the agent
    # is already loaded but still unreached.
    try:
        loaded = tuple(
            getattr(owner, "_agents_with_children", None)
            or getattr(owner, "_agents", None)
            or ()
        )
        identity = getattr(agent, "identity", None)
        visible = any(
            getattr(candidate, "identity", None) == identity for candidate in loaded
        )
    except Exception:
        visible = False
    if visible:
        _notify(
            owner,
            f"{name} is back in the inbox · the inbox filter hides it",
            severity="warning",
        )
    else:
        _notify(owner, f"{name} is back in the inbox · no new run started")


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
        _notify(
            owner, "The selected archived run has no forkable name", severity="warning"
        )
        return False
    try:
        scope = agent_prompt_target_scope(
            agent, str(reference), history_fallback="fork"
        )
    except Exception:
        _notify(owner, "The selected archived run can't be forked", severity="warning")
        return False
    prepare = getattr(owner, "_prepare_agent_prompt_target", None)
    if not callable(prepare):
        _notify(owner, "Fork is unavailable here", severity="warning")
        return False
    try:
        prepare(scope, action="fork")
    except Exception:
        _notify(owner, "Fork failed to start", severity="error")
        return False
    return True


def open_archive_chat(owner: Any, agent: Any) -> bool:
    """Open one hydrated Archive agent's chat in $EDITOR, read-only.

    Reading never revives, never marks anything read, and never writes: the
    opener only views the retained chat file.
    """
    if agent is None:
        _notify(owner, "Select an archived run first", severity="warning")
        return False
    try:
        response_path = getattr(agent, "response_path", None)
    except Exception:
        response_path = None
    if not response_path:
        _notify(owner, "No chat file found", severity="warning")
        return False
    opener = getattr(owner, "_open_agent_chat_paths", None)
    if not callable(opener):
        _notify(owner, "Open in editor is unavailable here", severity="warning")
        return False
    try:
        import os

        opener([os.path.expanduser(str(response_path))])
    except Exception:
        _notify(owner, "Open in editor failed", severity="error")
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
    name = _light_name(light_row)
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
        _notify(
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
                _notify(owner, "Archived run is no longer selected", severity="warning")
                return
            fork_archive_agent(owner, target)
        elif result_key == CHOICE_OPEN_CHAT:
            from ._archive_actions import archive_read_target

            try:
                target = archive_read_target(owner)
            except Exception:
                target = None
            if target is None:
                _notify(owner, "Archived run is no longer selected", severity="warning")
                return
            open_archive_chat(owner, target)
        elif result_key == CHOICE_COPY_REF:
            copier = getattr(owner, "_copy_agent_reference", None)
            if callable(copier):
                try:
                    copier()
                except Exception:
                    _notify(owner, "Copy failed", severity="error")
            else:
                _notify(owner, "Copy is unavailable here", severity="warning")
        elif result_key == CHOICE_COPY_MORE:
            palette = getattr(owner, "action_copy_tab_content", None)
            if callable(palette):
                try:
                    palette()
                except Exception:
                    _notify(owner, "Copy palette failed", severity="error")
            else:
                _notify(owner, "Copy palette is unavailable here", severity="warning")

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


__all__ = [
    "CHOICE_COPY_MORE",
    "CHOICE_COPY_REF",
    "CHOICE_FORK",
    "CHOICE_OPEN_CHAT",
    "CHOICE_RESTORE",
    "CHOICE_RESTORE_SHOW",
    "ArchiveRestoreSkip",
    "ArchiveRestoreSummary",
    "archive_chooser_model",
    "archive_fork_accepted",
    "collect_archive_restore_keys",
    "fork_archive_agent",
    "hydrate_archive_candidate",
    "open_archive_chat",
    "open_archive_chooser",
    "run_archive_restore",
]
