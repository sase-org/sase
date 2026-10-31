"""Shared helpers for the agent-session-successor split.

Public names in this private module are shared by the successor split
(``run_agent_successor_*``). Helpers needed by only one successor module
live in that module instead.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.plan_chain import allocate_agent_session_child_suffix

if TYPE_CHECKING:
    from sase.axe.run_agent_exec_types import AgentExecContext
    from sase.axe.run_agent_successor_types import SuccessorRequest


def _fallback_successor_suffix(template: str, *, token: str) -> str:
    from sase.agent.names import render_agent_name_template

    return render_agent_name_template(template, token)


def resolved_suffix(
    ctx: AgentExecContext,
    request: SuccessorRequest,
) -> str:
    """Resolve the successor suffix from an explicit value or a template."""
    if request.suffix is not None:
        return request.suffix
    assert request.suffix_template is not None
    if ctx.agent_name:
        return allocate_agent_session_child_suffix(
            ctx.agent_name,
            request.suffix_template,
            extra_reserved_suffixes=request.extra_reserved_suffixes,
        )
    return _fallback_successor_suffix(
        request.suffix_template,
        token=request.fallback_token,
    )


def read_successor_json(path: Path) -> dict[str, Any] | None:
    """Read a successor JSON document, returning None when unreadable."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


__all__ = [
    "read_successor_json",
    "resolved_suffix",
]
