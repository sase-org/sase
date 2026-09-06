"""Type definitions for agent workflow mixin."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, cast
from uuid import uuid4

# Type alias for tab names
TabName = Literal["artifacts", "agents", "axe"]


@dataclass
class PromptContext:
    """Context for in-progress agent prompt input."""

    project_name: str
    cl_name: str | None
    project_file: str
    workspace_dir: str
    workspace_num: int
    workflow_name: str
    timestamp: str
    history_sort_key: str
    display_name: str
    update_target: str
    is_home_mode: bool = False


PromptSessionId = str


@dataclass(frozen=True)
class RelaunchOperation:
    """One kill/edit cleanup operation that may hold its replacement launch."""

    label: str
    operation_id: str = field(default_factory=lambda: uuid4().hex)


@dataclass
class _PromptSession:
    """Live prompt-bar ownership state for async submit/cancel callbacks."""

    session_id: PromptSessionId
    context: PromptContext
    relaunch_operation: RelaunchOperation | None = None
    accepted_whole_bar_submit: bool = False


def begin_prompt_session(
    app: object,
    context: PromptContext,
    *,
    relaunch_operation: RelaunchOperation | None = None,
) -> _PromptSession:
    """Attach a fresh prompt session to *app* and publish its legacy context."""
    session = _PromptSession(
        session_id=uuid4().hex,
        context=context,
        relaunch_operation=relaunch_operation,
    )
    cast(Any, app)._prompt_context = context
    cast(Any, app)._prompt_session = session
    return session


def current_prompt_session(app: object) -> _PromptSession | None:
    """Return the live prompt session, adopting legacy context if needed."""
    context = getattr(app, "_prompt_context", None)
    if context is None:
        cast(Any, app)._prompt_session = None
        return None

    session = getattr(app, "_prompt_session", None)
    if isinstance(session, _PromptSession) and session.context is context:
        return session

    return begin_prompt_session(app, context)


def prompt_session_is_live(app: object, session_id: PromptSessionId | None) -> bool:
    """Return whether *session_id* still owns the current prompt context."""
    if session_id is None:
        return getattr(app, "_prompt_context", None) is not None
    session = getattr(app, "_prompt_session", None)
    context = getattr(app, "_prompt_context", None)
    return (
        isinstance(session, _PromptSession)
        and session.session_id == session_id
        and context is not None
        and session.context is context
    )


def invalidate_prompt_session(
    app: object,
    session_id: PromptSessionId | None = None,
    *,
    clear_context: bool = True,
) -> None:
    """Retire the current prompt session before cancellation or replacement."""
    session = getattr(app, "_prompt_session", None)
    if session_id is not None and (
        not isinstance(session, _PromptSession) or session.session_id != session_id
    ):
        return
    cast(Any, app)._prompt_session = None
    if clear_context:
        cast(Any, app)._prompt_context = None
