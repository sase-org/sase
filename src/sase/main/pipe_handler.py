"""Handler for ``sase pipe '<prompt>'``."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, NoReturn

from rich.panel import Panel
from rich.text import Text

from sase.agent.pending_handoff import PIPE_PENDING_MARKER
from sase.agent.pending_handoff_write import (
    PendingHandoffError,
    handoff_guard,
    write_pending_handoff_marker,
)
from sase.config import get_max_agent_pipe_chain
from sase.main.utils import kill_agent_runner_group
from sase.output import console, error_console
from sase.plan_chain import (
    PLAN_CHAIN_CODER_SUFFIX,
    PLAN_CHAIN_COMMIT_SUFFIX,
    PLAN_CHAIN_EPIC_SUFFIX,
    PLAN_CHAIN_MONITOR_SUFFIX,
    PLAN_CHAIN_PLAN_SUFFIX,
    canonical_plan_chain_suffix,
)

_PIPE_JSON_SCHEMA_VERSION = 1
_PIPE_NAME_TOKEN_RE = re.compile(r"^[A-Za-z0-9_]+$")
_RESERVED_PIPE_NAME_TOKENS = frozenset(
    {
        PLAN_CHAIN_PLAN_SUFFIX.removeprefix("--"),
        PLAN_CHAIN_CODER_SUFFIX.removeprefix("--"),
        PLAN_CHAIN_EPIC_SUFFIX.removeprefix("--"),
        PLAN_CHAIN_COMMIT_SUFFIX.removeprefix("--"),
        PLAN_CHAIN_MONITOR_SUFFIX.removeprefix("--"),
    }
)
_OUTSIDE_AGENT_MESSAGE = "`sase pipe` is only available inside a sase agent"
_BORDER_STYLE = "#5FAFFF"


class _PipeCommandError(ValueError):
    """Raised when ``sase pipe`` cannot start a hand-off."""


def _validate_pipe_name_token(token: str) -> str:
    """Return a validated role token, or raise :class:`_PipeCommandError`."""
    cleaned = token.strip()
    if not cleaned or not _PIPE_NAME_TOKEN_RE.fullmatch(cleaned):
        raise _PipeCommandError(
            f"invalid --name token {token!r}: use letters, digits, or underscore"
        )
    suffix = f"--{cleaned}"
    canonical = canonical_plan_chain_suffix(suffix)
    if canonical is None:
        raise _PipeCommandError(f"invalid --name token {token!r}")
    if cleaned in _RESERVED_PIPE_NAME_TOKENS:
        reserved = ", ".join(sorted(_RESERVED_PIPE_NAME_TOKENS))
        raise _PipeCommandError(
            f"--name {cleaned!r} collides with a reserved suffix ({reserved})"
        )
    return cleaned


def _pipe_depth_from_meta(meta: dict[str, Any] | None) -> int:
    """Return the recorded ``pipe_depth``, treating a missing value as 0."""
    if not meta:
        return 0
    raw = meta.get("pipe_depth")
    if type(raw) is int and raw >= 0:
        return raw
    return 0


def _read_agent_meta(artifacts_dir: str) -> dict[str, Any]:
    """Return ``agent_meta.json`` as a dict, or ``{}`` when unreadable."""
    path = Path(artifacts_dir) / "agent_meta.json"
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError, UnicodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _build_pipe_payload(
    *,
    prompt: str,
    reason: str | None,
    model: str | None,
    name_token: str | None,
    fresh: bool,
    pipe_depth: int,
) -> dict[str, Any]:
    """Return the pending-marker payload (timestamp is stamped on write)."""
    return {
        "prompt": prompt,
        "reason": reason,
        "model": model,
        "name_token": name_token,
        "fresh": fresh,
        "pipe_depth": pipe_depth,
    }


def _pipe_handoff_json(
    payload: dict[str, Any],
    *,
    agent_name: str | None,
    max_chain: int,
) -> dict[str, Any]:
    """Machine-readable summary printed before the runner kill."""
    return {
        "schema_version": _PIPE_JSON_SCHEMA_VERSION,
        "command": "pipe",
        "agent": agent_name,
        "prompt": payload["prompt"],
        "reason": payload.get("reason"),
        "model": payload.get("model"),
        "name": payload.get("name_token"),
        "fresh": bool(payload.get("fresh")),
        "pipe_depth": payload["pipe_depth"],
        "next_pipe_depth": payload["pipe_depth"] + 1,
        "max_agent_pipe_chain": max_chain,
    }


def _render_pipe_summary(
    payload: dict[str, Any],
    *,
    agent_name: str | None,
    max_chain: int,
) -> Text:
    """Rich hand-off summary matching the monitor command surface."""
    text = Text()
    text.append("This ends your turn.\n", style="bold yellow")
    text.append("The next family member starts immediately with the prompt below.\n\n")
    text.append("from  ", style="dim")
    text.append(agent_name or "(unnamed agent)", style="bold")
    text.append("\n")
    name_token = payload.get("name_token")
    text.append("to    ", style="dim")
    if isinstance(name_token, str) and name_token:
        text.append(f"<family>--{name_token}", style="bold cyan")
    else:
        text.append("next numbered family member", style="bold cyan")
    text.append("\n")
    model = payload.get("model")
    text.append("model ", style="dim")
    text.append(model if isinstance(model, str) and model else "inherit")
    text.append("\n")
    text.append("fresh ", style="dim")
    text.append("yes" if payload.get("fresh") else "no (inherits this chat)")
    text.append("\n")
    reason = payload.get("reason")
    if isinstance(reason, str) and reason:
        text.append("why   ", style="dim")
        text.append(reason)
        text.append("\n")
    text.append("depth ", style="dim")
    text.append(
        f"{payload['pipe_depth'] + 1} / {max_chain}  (config: max_agent_pipe_chain)"
    )
    text.append("\n\n")
    text.append("prompt", style="dim")
    text.append("\n")
    text.append(str(payload["prompt"]))
    return text


def _print_summary(
    payload: dict[str, Any],
    *,
    json_output: bool,
    agent_name: str | None,
    max_chain: int,
) -> None:
    if json_output:
        json.dump(
            _pipe_handoff_json(payload, agent_name=agent_name, max_chain=max_chain),
            sys.stdout,
            indent=2,
        )
        sys.stdout.write("\n")
    else:
        console.print(
            Panel(
                _render_pipe_summary(
                    payload, agent_name=agent_name, max_chain=max_chain
                ),
                title="sase pipe",
                border_style=_BORDER_STYLE,
            )
        )
        console.print(
            "This is the last output before the agent runner is killed.",
            style="dim",
        )
    sys.stdout.flush()


def _fail(message: str, *, code: int = 1) -> NoReturn:
    error_console.print(f"Error: {message}")
    sys.exit(code)


def handle_pipe_command(
    prompt: str,
    *,
    fresh: bool = False,
    json_output: bool = False,
    model: str | None = None,
    name: str | None = None,
    reason: str | None = None,
) -> NoReturn:
    """Hand this agent's turn to the next family member.

    1. Guard: only inside a sase agent, and only one hand-off per turn
    2. Reject an empty prompt, a reserved ``--name``, or a chain past the bound
    3. Print the summary
    4. Write ``.sase_pipe_pending`` and SIGTERM the runner group
    """
    try:
        artifacts_dir = handoff_guard()
    except PendingHandoffError as exc:
        message = str(exc)
        if message in {"SASE_AGENT is unset", "SASE_ARTIFACTS_DIR is unset"}:
            _fail(_OUTSIDE_AGENT_MESSAGE)
        _fail(message)

    if not prompt.strip():
        _fail("prompt must not be empty")

    name_token: str | None = None
    if name is not None and name.strip():
        try:
            name_token = _validate_pipe_name_token(name)
        except _PipeCommandError as exc:
            _fail(str(exc))

    meta = _read_agent_meta(artifacts_dir)
    current_depth = _pipe_depth_from_meta(meta)
    max_chain = get_max_agent_pipe_chain()
    next_depth = current_depth + 1
    if next_depth > max_chain:
        _fail(
            f"next link would exceed max_agent_pipe_chain={max_chain} "
            f"(chain length reached: {current_depth})"
        )

    model_value = model.strip() if isinstance(model, str) and model.strip() else None
    reason_value = (
        reason.strip() if isinstance(reason, str) and reason.strip() else None
    )
    payload = _build_pipe_payload(
        prompt=prompt,
        reason=reason_value,
        model=model_value,
        name_token=name_token,
        fresh=bool(fresh),
        pipe_depth=current_depth,
    )
    agent_name = meta.get("name") if isinstance(meta.get("name"), str) else None

    _print_summary(
        payload,
        json_output=json_output,
        agent_name=agent_name,
        max_chain=max_chain,
    )

    try:
        write_pending_handoff_marker(
            PIPE_PENDING_MARKER,
            payload,
            artifacts_dir=artifacts_dir,
        )
    except PendingHandoffError as exc:
        _fail(str(exc))

    kill_agent_runner_group(artifacts_dir)
