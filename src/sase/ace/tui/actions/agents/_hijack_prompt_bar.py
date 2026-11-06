"""Hijack Instruct/Edit prompt-bar flows.

Implements the ``tui_prompt`` phase: panel keys ``i`` (Instruct) and ``e``
(Edit) open the prompt bar instead of toasting "coming soon".

- Instruct pre-fills the Rust continuation prompt (guidance slot requested,
  ``%model:`` pinned to the stalled concrete model) with the cursor on the
  empty guidance line. Submit routes through ``persist-recover -a continue
  -p <file>`` semantics (``action="continue"`` plus the edited prompt text).
  The backend decides ESCALATED vs CONTINUED from the prompt's ``%model:``.
- Edit pre-fills the original raw prompt via ``,x`` reconstruction and
  releases nothing until submit. Submit runs ``persist-recover -a restart
  -p <file>``. Cancel leaves the agent HIJACKED in both flows.

Nothing is dismissed at mount. Cancellation flows through the normal bar
safety net (history ``cancelled=True``) so no draft is lost.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

_INSTRUCT_ACTION = "continue"
_EDIT_ACTION = "restart"


@dataclass
class HijackPromptBarContext:
    """One hijack prompt-bar session owned by the TUI."""

    action: str
    hijack_id: str
    expected_revision: int
    agent_name: str
    cl_name: str
    project_file: str
    display_name: str
    session_id: str | None = None


def guidance_cursor_for_prompt(text: str) -> tuple[int, int]:
    """Return the zero-based cursor for the empty guidance line.

    The continuation prompt leads with ``%model:``, an optional ``#fork:``
    line, then one blank guidance line before the hijack frame. The cursor
    belongs on that blank line; fall back to the top when the shape is
    unexpected.
    """
    lines = text.splitlines()
    row = 0
    if row < len(lines) and lines[row].startswith("%model:"):
        row += 1
    if row < len(lines) and lines[row].startswith("#fork:"):
        row += 1
    if row < len(lines) and not lines[row].strip():
        return (row, 0)
    # Guidance line missing (unexpected shape): land at the top so the
    # user still starts above the frame instead of at the end.
    if row < len(lines):
        return (row, 0)
    return (0, 0)


def get_hijack_prompt_context(app: object) -> HijackPromptBarContext | None:
    """Return the live hijack prompt-bar context, if any."""
    context = getattr(app, "_hijack_prompt_context", None)
    if isinstance(context, HijackPromptBarContext):
        return context
    return None


def clear_hijack_prompt_context(app: object) -> None:
    """Forget any hijack prompt-bar context."""
    try:
        app._hijack_prompt_context = None  # type: ignore[attr-defined]
    except Exception:
        pass


def _record_identity(agent: Any) -> tuple[object, ...] | None:
    identity = getattr(agent, "identity", None)
    if identity is None:
        return None
    try:
        return tuple(identity)
    except TypeError:
        return None


def open_hijack_instruct_bar(app: Any, agent: Any, record: dict[str, Any]) -> None:
    """Open the Instruct prompt bar for a HIJACKED row.

    Resolves the continuation prompt off the event loop, then mounts the
    bar pre-filled with it. Failures toast and leave the agent HIJACKED.
    """
    identity = _record_identity(agent)
    resolver = lambda: _resolve_instruct_text(agent, record)  # noqa: E731

    from ..agent_workflow._entry_relaunch import schedule_relaunch_prompt_resolution

    def _on_resolved(text: str | None) -> None:
        current = _reresolve(app, identity) or agent
        if not text:
            app.notify(
                "Could not build the continuation prompt; stays hijacked",
                severity="warning",
            )
            return
        _mount_hijack_bar(
            app,
            current,
            dict(record),
            initial_text=text,
            initial_cursor=guidance_cursor_for_prompt(text),
            hijack_action=_INSTRUCT_ACTION,
        )

    schedule_relaunch_prompt_resolution(
        app,
        resolver,
        _on_resolved,
        worker_name="hijack-instruct-prompt",
        failure_message="Could not build the continuation prompt; stays hijacked",
    )


def open_hijack_edit_bar(app: Any, agent: Any, record: dict[str, Any]) -> None:
    """Open the Edit prompt bar for a HIJACKED row.

    Uses ``,x`` reconstruction and dismisses nothing at mount. The edited
    prompt is submitted through ``persist-recover -a restart``.
    """
    identity = _record_identity(agent)
    agents_snapshot = tuple(
        getattr(app, "_agents_with_children", None)
        or getattr(app, "_agents", None)
        or (agent,)
    )

    from ..agent_workflow._entry_relaunch import (
        prepare_kill_edit_agent_prompt,
        schedule_relaunch_prompt_resolution,
    )

    def _resolver() -> str | None:
        return prepare_kill_edit_agent_prompt(agent, agents_snapshot)

    def _on_resolved(text: str | None) -> None:
        current = _reresolve(app, identity) or agent
        if not text:
            app.notify(
                "No prompt found for this agent; stays hijacked",
                severity="warning",
            )
            return
        _mount_hijack_bar(
            app,
            current,
            dict(record),
            initial_text=text,
            initial_cursor=None,
            hijack_action=_EDIT_ACTION,
        )

    schedule_relaunch_prompt_resolution(
        app,
        _resolver,
        _on_resolved,
        worker_name="hijack-edit-prompt",
        failure_message="Unable to prepare agent relaunch prompt; stays hijacked",
    )


def _reresolve(app: Any, identity: tuple[object, ...] | None) -> Any | None:
    if identity is None:
        getter = getattr(app, "_get_selected_agent", None)
        return getter() if callable(getter) else None
    agents = getattr(app, "_agents_with_children", None) or getattr(
        app, "_agents", None
    )
    if agents is not None:
        for candidate in agents:
            if getattr(candidate, "identity", candidate) == identity:
                return candidate
        return None
    getter = getattr(app, "_get_selected_agent", None)
    if not callable(getter):
        return None
    selected = getter()
    return (
        selected
        if selected is not None and getattr(selected, "identity", selected) == identity
        else None
    )


def _resolve_instruct_text(agent: Any, record: dict[str, Any]) -> str | None:
    """Build the Instruct pre-fill off the event loop."""
    try:
        from sase.agent.hijack.preview import build_hijack_continuation_prompt
    except Exception as exc:  # noqa: BLE001 - resolver reports failure to the caller.
        log.debug("hijack instruct prompt unavailable: %s", exc)
        return None
    target: dict[str, Any] | str = record
    agent_name = str(record.get("agent_name") or getattr(agent, "agent_name", ""))
    if agent_name and not isinstance(target, str):
        pass
    try:
        # Prefer the ledger-backed path via the record mapping; fall back to
        # the agent name when the record cannot be resolved directly.
        built = build_hijack_continuation_prompt(target, guidance_requested=True)
    except Exception:
        try:
            built = build_hijack_continuation_prompt(
                agent_name or target, guidance_requested=True
            )
        except Exception as exc:  # noqa: BLE001 - caller toasts a warning.
            log.debug("hijack instruct prompt failed: %s", exc)
            return None
    prompt = getattr(built, "prompt", "")
    return prompt if isinstance(prompt, str) and prompt.strip() else None


def _mount_hijack_bar(
    app: Any,
    agent: Any,
    record: dict[str, Any],
    *,
    initial_text: str,
    initial_cursor: tuple[int, int] | None,
    hijack_action: str,
) -> None:
    """Mount the prompt bar for one hijack flow without dismissing anything."""
    from sase.core.paths import sase_projects_dir
    from sase.ace.patch.project_spec_path import preferred_project_spec_path
    from sase.core.time import generate_timestamp
    from sase.project_display_names import humanize_cl_name, humanize_vcs_refs_in_text

    from ..agent_workflow._types import begin_prompt_session, PromptContext
    from ...widgets import PromptInputBar

    project_file = str(
        getattr(agent, "project_file", None) or record.get("project_file") or ""
    )
    cl_name = str(getattr(agent, "cl_name", None) or record.get("cl_name") or "")
    display_name = str(
        getattr(agent, "display_name", None)
        or getattr(agent, "presented_agent_name", None)
        or getattr(agent, "agent_name", None)
        or record.get("agent_name")
        or "hijacked agent"
    )
    if not project_file:
        project_file = preferred_project_spec_path(
            str(sase_projects_dir() / "home"), "home"
        )
    humanized = humanize_vcs_refs_in_text(initial_text)
    if cl_name:
        history_sort_key = cl_name
        try:
            home_display = humanize_cl_name(cl_name)
        except Exception:
            home_display = display_name
    else:
        history_sort_key = "home"
        home_display = display_name

    app._unmount_prompt_bar()  # type: ignore[attr-defined]
    try:
        app._discard_prompt_bar_spare()  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - spare discard is best-effort.
        pass

    timestamp = generate_timestamp()
    session = begin_prompt_session(
        app,
        PromptContext(
            project_name="home",
            cl_name=None,
            project_file=preferred_project_spec_path(
                str(sase_projects_dir() / "home"), "home"
            ),
            workspace_dir="",
            workspace_num=0,
            workflow_name=f"ace(run)-{timestamp}",
            timestamp=timestamp,
            history_sort_key=history_sort_key,
            display_name=home_display,
            update_target="",
            is_home_mode=True,
        ),
        prompt_origin="typed",
    )
    app._hijack_prompt_context = HijackPromptBarContext(  # type: ignore[attr-defined]
        action=hijack_action,
        hijack_id=str(record.get("hijack_id") or ""),
        expected_revision=int(record.get("revision") or 0),
        agent_name=str(record.get("agent_name") or getattr(agent, "agent_name", "")),
        cl_name=cl_name,
        project_file=project_file,
        display_name=f"Recover {display_name}",
        session_id=session.session_id,
    )
    bar_kwargs: dict[str, Any] = {"initial_value": humanized, "id": "prompt-input-bar"}
    if initial_cursor is not None:
        bar_kwargs["initial_cursor"] = initial_cursor
    app.mount(bar_kwargs and PromptInputBar(**bar_kwargs))  # type: ignore[attr-defined]


def handle_hijack_prompt_submitted(app: Any, prompt_text: str) -> bool:
    """Submit an Instruct/Edit prompt through ``persist-recover``.

    Returns True when a hijack context owned the submit (the caller must
    not fall through to the normal launch path).
    """
    context = get_hijack_prompt_context(app)
    if context is None:
        return False
    if not prompt_text.strip():
        app.notify("Empty prompt - cancelled", severity="warning")  # type: ignore[attr-defined]
        clear_hijack_prompt_context(app)
        try:
            app._unmount_prompt_bar()  # type: ignore[attr-defined]
            app._prompt_context = None
        except Exception:
            pass
        return True

    from ..agent_workflow._types import current_prompt_session
    from ..agent_durable import submit_agent_recovery

    try:
        session = current_prompt_session(app)
        session_id = session.session_id if session is not None else None
    except Exception:
        session_id = None
    if context.session_id is not None and session_id != context.session_id:
        app.notify(  # type: ignore[attr-defined]
            "Launch cancelled; the prompt bar was closed while submitting.",
            severity="warning",
        )
        clear_hijack_prompt_context(app)
        return True

    agent = _find_hijack_agent(app, context)
    overlay_target = agent
    if overlay_target is not None:
        overlay_target.hijack_overlay = "recovering"
        refresh = getattr(app, "_refresh_agents_display", None)
        if callable(refresh):
            try:
                refresh(list_changed=False, defer_detail=True)
            except Exception:
                pass

    try:
        app._unmount_prompt_bar_after_submit()  # type: ignore[attr-defined]
    except Exception:
        pass
    try:
        app._prompt_context = None  # type: ignore[attr-defined]
    except Exception:
        pass
    submitted_text = prompt_text
    hijack_action = context.action
    clear_hijack_prompt_context(app)

    def _on_complete(completion: Any) -> None:
        current = _find_hijack_agent(app, context) or overlay_target
        if current is not None:
            current.hijack_overlay = None
            if hijack_action != _EDIT_ACTION or (getattr(completion, "success", False)):
                current.hijack_record = None
            refresh_row = getattr(app, "_refresh_agents_display", None)
            if callable(refresh_row):
                try:
                    refresh_row(list_changed=False, defer_detail=True)
                except Exception:
                    pass
        payload = (
            completion.payload
            if isinstance(getattr(completion, "payload", None), dict)
            else {}
        )
        success = bool(getattr(completion, "success", False))
        if not success and hijack_action == _EDIT_ACTION:
            try:
                saver = getattr(app, "_save_text_as_cancelled", None)
                if callable(saver):
                    saver(submitted_text)
            except Exception:
                pass
        severity = payload.get("severity")
        if severity not in {"information", "warning", "error"}:
            severity = "information" if success else "error"
        message = completion.message or (
            f"Recovery {hijack_action} completed"
            if success
            else f"Recovery {hijack_action} failed"
        )
        app.notify(message, severity=severity)
        refresh_source = payload.get("schedule_agents_refresh_source")
        refresh_fn = getattr(app, "_schedule_agents_async_refresh", None)
        if isinstance(refresh_source, str) and callable(refresh_fn):
            try:
                refresh_fn(source=refresh_source)
            except Exception:
                pass

    submitted = submit_agent_recovery(
        app,
        name=context.agent_name,
        hijack_id=context.hijack_id,
        expected_revision=context.expected_revision,
        action=hijack_action,
        prompt=submitted_text,
        cl_name=context.cl_name,
        project_file=context.project_file,
        display_name=context.display_name,
        on_complete=_on_complete,
    )
    if not submitted and overlay_target is not None:
        overlay_target.hijack_overlay = None
        try:
            refresh = getattr(app, "_refresh_agents_display", None)
            if callable(refresh):
                refresh(list_changed=False, defer_detail=True)
        except Exception:
            pass
        app.notify("Could not queue recovery", severity="error")
    return True


def _find_hijack_agent(app: Any, context: HijackPromptBarContext) -> Any | None:
    agents = getattr(app, "_agents_with_children", None) or getattr(
        app, "_agents", None
    )
    if agents:
        for candidate in agents:
            if getattr(candidate, "agent_name", None) == context.agent_name:
                return candidate
            record = getattr(candidate, "hijack_record", None)
            if isinstance(record, dict) and (
                str(record.get("hijack_id") or "") == context.hijack_id
            ):
                return candidate
    getter = getattr(app, "_get_selected_agent", None)
    if callable(getter):
        try:
            return getter()
        except Exception:
            return None
    return None


__all__ = [
    "HijackPromptBarContext",
    "clear_hijack_prompt_context",
    "get_hijack_prompt_context",
    "guidance_cursor_for_prompt",
    "handle_hijack_prompt_submitted",
    "open_hijack_edit_bar",
    "open_hijack_instruct_bar",
]
