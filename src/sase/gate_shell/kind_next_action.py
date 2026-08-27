"""Settle-time follow-up-prompt rebuild, keyed by gate kind.

A gate kind that wants its follow-up's ``## Your next action`` rebuilt from
durable state at settlement (rather than frozen at creation time) registers a
hook here. Resolution is lazy so ``sase.gate_shell`` never imports a kind's
module eagerly, and defensive so an unregistered kind, an import failure, an
exception, or a falsy return all fall back to the declared prompt: this runs
at settlement and must never turn a settlement into a crash.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from importlib import import_module
from typing import Any, cast

logger = logging.getLogger(__name__)

_NextActionHook = Callable[..., str | None]
_NextActionTarget = tuple[str, str] | _NextActionHook


def _plan_next_action(**kwargs: Any) -> str | None:
    from sase.plan_shell.followup import plan_next_action

    return plan_next_action(**kwargs)


_KIND_NEXT_ACTIONS: dict[str, _NextActionTarget] = {
    "epic_plan": _plan_next_action,
    "plan": _plan_next_action,
    "question": ("sase.question_shell.followup", "question_next_action"),
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
    target = _KIND_NEXT_ACTIONS.get(kind or "")
    if target is None:
        return declared
    try:
        hook: _NextActionHook
        if isinstance(target, tuple):
            module_name, attribute = target
            hook = cast(_NextActionHook, getattr(import_module(module_name), attribute))
        else:
            hook = target
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
