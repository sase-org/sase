"""Settle-time follow-up-prompt rebuild, keyed by gate kind.

A gate kind that wants its follow-up's ``## Your next action`` rebuilt from
durable state at settlement (rather than frozen at creation time) registers a
hook here. Each hook is a thin wrapper that imports the kind's module in its
own body, so ``sase.gate_shell`` never imports a kind's module eagerly while
the real hook stays an ordinary, statically visible reference. Resolution is
defensive: an unregistered kind, an import failure, an exception, or a falsy
return all fall back to the declared prompt, because this runs at settlement
and must never turn a settlement into a crash.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

_NextActionHook = Callable[..., str | None]


def _plan_next_action(**kwargs: Any) -> str | None:
    from sase.plan_shell.followup import plan_next_action

    return plan_next_action(**kwargs)


def _question_next_action(**kwargs: Any) -> str | None:
    from sase.question_shell.followup import question_next_action

    return question_next_action(**kwargs)


_KIND_NEXT_ACTIONS: dict[str, _NextActionHook] = {
    "epic_plan": _plan_next_action,
    "plan": _plan_next_action,
    "question": _question_next_action,
}

_STRICT_KIND_NEXT_ACTIONS = frozenset({"epic_plan", "plan"})


def resolve_shell_next_action(
    *,
    kind: str | None,
    artifacts_dir: str,
    meta: dict[str, Any],
    envelope: dict[str, Any],
    response: dict[str, Any],
    declared: str | None,
) -> str | None:
    """Return the kind's rebuilt next-action text, or *declared* as a fallback."""
    hook = _KIND_NEXT_ACTIONS.get(kind or "")
    if hook is None:
        return declared
    try:
        resolved = hook(
            artifacts_dir=artifacts_dir,
            meta=meta,
            envelope=envelope,
            response=response,
            declared=declared,
        )
    except Exception:
        if kind in _STRICT_KIND_NEXT_ACTIONS:
            raise
        logger.warning(
            "Gate-shell next-action hook failed for kind %r; using declared prompt",
            kind,
            exc_info=True,
        )
        return declared
    return resolved or declared


__all__ = ["resolve_shell_next_action"]
