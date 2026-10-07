"""Pre-start inline routing refusal for catalog tools that cannot fit.

A duration class is a floor, not a forecast. Before ``sase tool run`` starts
anything, this module refuses an agent's inline run of a named catalog tool
whose class floor meets the provider's synchronous kill ceiling, and prints
the monitor command to use instead. The Rust core owns the floors and the
fit rule; this module only reads the ceiling, asks the core, and formats.
"""

from __future__ import annotations

import json
import shlex
import sys
from collections.abc import Mapping

from sase.core.tool_run import tool_run_duration_fit
from sase.env_contracts import (
    SASE_PROVIDER_SYNC_CEILING_SECONDS_ENV,
    SASE_PROVIDER_SYNC_SOFT_CEILING_SECONDS_ENV,
)
from sase.tool.argv import ResolvedToolArgv

_CEILING_ENV = SASE_PROVIDER_SYNC_CEILING_SECONDS_ENV
_SOFT_CEILING_ENV = SASE_PROVIDER_SYNC_SOFT_CEILING_SECONDS_ENV

#: Placeholder next action printed in the refusal's monitor form; the agent
#: replaces it with what the follow-up should do with the result.
REFUSAL_NEXT_PLACEHOLDER = "<what the follow-up should do with the result>"

#: Reason printed in the refusal's prepared-completion monitor form.
REFUSAL_COMPLETION_REASON = "Verify before host completion"


def read_ceiling_seconds(environ: Mapping[str, str], key: str) -> int | None:
    """Return a validated positive-integer ceiling for *key*, if present.

    A missing, empty, non-integer, zero, or negative value is treated as
    absent, so callers fail open.
    """

    raw = environ.get(key)
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        value = int(text, 10)
    except ValueError:
        return None
    if value <= 0:
        return None
    return value


def _read_sync_ceiling(env: Mapping[str, str] | None = None) -> int | None:
    """Return the provider synchronous kill ceiling in seconds, if valid.

    Only positive integers count. A missing, empty, non-integer, zero, or
    negative value is treated as absent, so the check fails open.
    """

    import os

    return read_ceiling_seconds(os.environ if env is None else env, _CEILING_ENV)


def _format_seconds(seconds: int) -> str:
    """Format a duration in seconds as ``4h``, ``10m``, or ``45s``."""

    if seconds % 3600 == 0:
        return f"{seconds // 3600}h"
    if seconds % 60 == 0:
        return f"{seconds // 60}m"
    return f"{seconds}s"


def monitor_start_form(
    words: tuple[str, ...] | list[str],
    *,
    reason: str,
    next_text: str | None = None,
    completion_ref: str | None = None,
) -> str:
    """Build the ``sase monitor start`` command for a ``sase tool run``."""

    parts = ["sase", "monitor", "start", "-p", "verify"]
    if completion_ref is not None:
        parts += ["-f", str(completion_ref)]
    parts += ["--reason", str(reason)]
    if next_text is not None:
        parts += ["-n", str(next_text)]
    parts += ["--", "sase", "tool", "run", *[str(part) for part in words]]
    return " ".join(shlex.quote(part) for part in parts)


def _finalizer_owned_turn_is_active(
    env: Mapping[str, str] | None = None,
) -> bool:
    """Return whether a host finalizer owns the current provider turn.

    Imported lazily so ``sase.finalizers`` (a heavy package) is not pulled
    into every process that imports this module; the check itself is owned
    by :func:`sase.finalizers.owned_turn.finalizer_owned_turn_is_active`.
    """
    import os

    from sase.finalizers import owned_turn as _owned_turn

    return _owned_turn.finalizer_owned_turn_is_active(
        os.environ if env is None else env
    )


def _run_words(resolved: ResolvedToolArgv) -> list[str]:
    """Return the ``sase tool run`` remainder words for a resolved tool."""

    words = [str(resolved.tool_name)]
    extra = [str(part) for part in resolved.extra_args]
    if extra:
        words += ["--", *extra]
    return words


def inline_refusal(
    resolved: ResolvedToolArgv,
    env: Mapping[str, str] | None = None,
) -> str | None:
    """Return the refusal message when an inline run cannot fit, else None.

    All four conditions must hold: an agent is running, the ceiling is
    valid, the run is a named catalog tool, and the core fit call says the
    tool does not fit. A missing or raising binding fails open (no refusal)
    with one stderr warning.
    """

    import os

    environ = os.environ if env is None else env
    if not str(environ.get("SASE_AGENT") or "").strip():
        return None
    ceiling = _read_sync_ceiling(environ)
    if ceiling is None:
        return None
    if resolved.adhoc or not resolved.tool_name:
        return None
    declared = resolved.definition.get("duration_class")
    try:
        fit = tool_run_duration_fit(
            {"duration_class": declared, "ceiling_seconds": ceiling}
        )
    except Exception as exc:  # noqa: BLE001 - the refusal never blocks a run.
        print(
            f"sase: duration fit unavailable ({exc}); running inline",
            file=sys.stderr,
        )
        return None
    if not isinstance(fit, dict) or fit.get("fits_inline", True):
        return None
    effective = str(fit.get("duration_class") or declared or "short")
    floor = fit.get("floor_seconds")
    tool_name = str(resolved.tool_name)
    if effective == "unbounded" or floor is None:
        floor_phrase = "has no upper bound"
    else:
        floor_phrase = f"runs at least {_format_seconds(int(floor))}"
    ceiling_phrase = _format_seconds(ceiling)
    words = _run_words(resolved)
    monitor_form = monitor_start_form(
        words,
        reason=f"run {tool_name} (duration class {effective})",
        next_text=REFUSAL_NEXT_PLACEHOLDER,
    )
    verification_argv = ["sase", "tool", "run", *words]
    completion_form = monitor_start_form(
        words,
        reason=REFUSAL_COMPLETION_REASON,
        completion_ref="<ref>",
    )
    return (
        f"sase tool run: refused before starting {tool_name}: "
        f"its duration class is {effective} ({floor_phrase}), "
        f"and this agent's provider kills any command at {ceiling_phrase} "
        f"({_CEILING_ENV}={ceiling}). Nothing was started.\n"
        f"Hand it to a monitor:\n"
        f"  {monitor_form}\n"
        f"For a final verification gate, prepare host completion first "
        f'(/sase_final "Prepared Monitor Completion") '
        f"with verification.command {json.dumps(verification_argv)}, then:\n"
        f"  {completion_form}"
    )


#: Placeholder next action printed in the escalation block's join form.
JOIN_NEXT_PLACEHOLDER = "<what the follow-up should do with the result>"

#: Tail lines carried by the escalation block's bounded re-wait form.
ESCALATION_REWAIT_TAIL_LINES = 200


def sync_wait_budget(
    env: Mapping[str, str] | None = None,
) -> dict[str, object] | None:
    """Return the core-computed sync wait budget for an agent, if any.

    Reads the hard and soft ceiling variables with the same positive-integer
    rule as the inline refusal, then asks Rust for the budget. Returns
    ``None`` without ``SASE_AGENT``, when neither ceiling is present, or
    when the core reports no budget. A missing or raising binding warns
    once and fails open to today's unbounded behaviour.
    """

    import os

    environ = os.environ if env is None else env
    if not str(environ.get("SASE_AGENT") or "").strip():
        return None
    ceiling = read_ceiling_seconds(environ, _CEILING_ENV)
    soft_ceiling = read_ceiling_seconds(environ, _SOFT_CEILING_ENV)
    if ceiling is None and soft_ceiling is None:
        return None
    try:
        from sase.core.tool_run import tool_run_sync_wait_budget

        request: dict[str, object] = {}
        if ceiling is not None:
            request["ceiling_seconds"] = ceiling
        if soft_ceiling is not None:
            request["soft_ceiling_seconds"] = soft_ceiling
        response = tool_run_sync_wait_budget(request)
    except Exception as exc:  # noqa: BLE001 - the budget never blocks a wait.
        print(
            f"sase: sync wait budget unavailable ({exc}); waiting without a bound",
            file=sys.stderr,
        )
        return None
    if not isinstance(response, dict):
        return None
    budget = response.get("budget_seconds")
    source = response.get("source")
    if type(budget) is not int or budget <= 0:
        return None
    if source not in ("hard", "soft"):
        return None
    out: dict[str, object] = {
        "budget_seconds": budget,
        "source": str(source),
    }
    if ceiling is not None:
        out["ceiling_seconds"] = ceiling
    if soft_ceiling is not None:
        out["soft_ceiling_seconds"] = soft_ceiling
    margin = response.get("margin_seconds")
    if type(margin) is int:
        out["margin_seconds"] = margin
    return out


def is_joinable(
    run: dict[str, object] | object,
    env: Mapping[str, str] | None = None,
) -> bool:
    """Return whether an agent may escalate *run* to ``monitor start -J``.

    Joinable means the run is unsettled, carries a starter, has no stop
    request, is unjoined (or joined by the caller's own monitor), and names
    the caller as its starter agent. A finalizer-owned provider turn is
    never joinable: the monitor join would end the finalizer's own turn.
    """

    import os

    if not isinstance(run, dict):
        return False
    if _finalizer_owned_turn_is_active(os.environ if env is None else env):
        return False
    from typing import cast

    run_d = cast(dict[str, object], run)
    if str(run_d.get("state") or "") not in ("created", "running"):
        return False
    starter = run_d.get("starter")
    if not isinstance(starter, dict) or not str(starter.get("agent") or ""):
        return False
    if run_d.get("stop_request") is not None:
        return False
    environ = os.environ if env is None else env
    caller = str(environ.get("SASE_AGENT_NAME") or "").strip()
    if not caller or caller != str(starter.get("agent") or ""):
        return False
    join = run_d.get("join")
    if (
        isinstance(join, dict)
        and str(join.get("kind") or "")
        and str(join.get("id") or "")
    ):
        if str(join.get("kind")) != "monitor":
            return False
        monitor_id = str(environ.get("SASE_MONITOR_ID") or "").strip()
        return bool(monitor_id) and monitor_id == str(join.get("id"))
    return True


def _run_elapsed_seconds(run: dict[str, object], now: float | None = None) -> float:
    """Return seconds since the run started (``running_ts``, else ``created_ts``)."""

    import time

    stamp = run.get("running_ts")
    if type(stamp) is not int:
        stamp = run.get("created_ts")
    if type(stamp) is not int:
        return 0.0
    now_s = time.time() if now is None else now
    return max(0.0, float(now_s - stamp))


def _format_elapsed(seconds: float) -> str:
    """Format an elapsed duration as ``45s``, ``8m30s``, or ``2h5m``."""

    total = int(seconds)
    if total < 60:
        return f"{total}s"
    minutes, rem = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m{rem}s" if rem else f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes}m" if minutes else f"{hours}h"


def _escalation_tool_name(run: dict[str, object]) -> str:
    """Return the tool name printed in the escalation block."""

    name = str(run.get("tool_name") or "").strip()
    return name or "ad-hoc"


def _join_command(run_id: str, tool_name: str | None = None) -> str:
    """Build the ``sase monitor start -J`` form for an escalation block."""

    tool = str(tool_name or "").strip() or "run"
    parts = [
        "sase",
        "monitor",
        "start",
        "-J",
        str(run_id),
        "-p",
        "verify",
        "-r",
        f"finish {tool} (joined run)",
        "-n",
        JOIN_NEXT_PLACEHOLDER,
    ]
    return " ".join(shlex.quote(part) for part in parts)


def _rewait_command(run_id: str) -> str:
    """Build the bounded re-wait form for an escalation block."""

    parts = [
        "sase",
        "tool",
        "wait",
        str(run_id),
        "-T",
        str(ESCALATION_REWAIT_TAIL_LINES),
    ]
    return " ".join(shlex.quote(part) for part in parts)


def _escalation_source_line(budget: dict[str, object]) -> str:
    """Return the budget-source sentence for an escalation block."""

    if str(budget.get("source")) == "soft":
        soft = budget.get("soft_ceiling_seconds")
        value = int(soft) if type(soft) is int else budget.get("budget_seconds")
        assert type(value) is int
        return (
            f"This agent's soft ceiling is {_format_seconds(value)} "
            f"({_SOFT_CEILING_ENV}={value})."
        )
    ceiling = budget.get("ceiling_seconds")
    value = int(ceiling) if type(ceiling) is int else budget.get("budget_seconds")
    assert type(value) is int
    return (
        "This agent's provider kills synchronous commands at "
        f"{_format_seconds(value)} ({_CEILING_ENV}={value})."
    )


def escalation_block(
    run: dict[str, object],
    budget: dict[str, object],
    run_id: str | None = None,
    env: Mapping[str, str] | None = None,
) -> str:
    """Build the shared escalation block for a still-running run.

    A joinable run prints the full block (tool and id, elapsed, the source
    line, the ``-J/--join`` form, the bounded re-wait form, and the turn-end
    stop rule). A run that is not joinable prints only the existing
    still-running line plus the re-wait form, so no refused join command is
    ever suggested.
    """

    rid = str(run_id or run.get("run_id") or "").strip()
    elapsed = _format_elapsed(_run_elapsed_seconds(run))
    if not is_joinable(run, env):
        return (
            f"tool run {rid} is still running\n"
            "Or wait again inline, bounded by the same ceiling:\n"
            f"  {_rewait_command(rid)}"
        )
    tool = _escalation_tool_name(run)
    return (
        f"sase tool run: {tool} (run {rid}) is still running after "
        f"{elapsed}; it was not stopped.\n"
        f"{_escalation_source_line(budget)}\n"
        "Hand the same run to a monitor and end this turn (nothing reruns):\n"
        f"  {_join_command(rid, tool)}\n"
        "Or wait again inline, bounded by the same ceiling:\n"
        f"  {_rewait_command(rid)}\n"
        "Unless a monitor joins it, this run is stopped when this agent's turn ends."
    )


def escalation_json(
    run_id: str,
    budget: dict[str, object],
    joinable: bool,
    tool_name: str | None = None,
) -> dict[str, object]:
    """Build the ``escalation`` object for ``sase tool wait -j`` at a budget."""

    budget_seconds = budget.get("budget_seconds")
    assert type(budget_seconds) is int
    return {
        "budget_seconds": budget_seconds,
        "source": str(budget.get("source")),
        "joinable": bool(joinable),
        "join_command": _join_command(run_id, tool_name) if joinable else None,
    }


__all__ = [
    "ESCALATION_REWAIT_TAIL_LINES",
    "JOIN_NEXT_PLACEHOLDER",
    "REFUSAL_COMPLETION_REASON",
    "REFUSAL_NEXT_PLACEHOLDER",
    "escalation_block",
    "escalation_json",
    "inline_refusal",
    "is_joinable",
    "monitor_start_form",
    "read_ceiling_seconds",
    "sync_wait_budget",
    "_read_sync_ceiling",
]
