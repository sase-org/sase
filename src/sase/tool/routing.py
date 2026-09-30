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
from sase.env_contracts import SASE_PROVIDER_SYNC_CEILING_SECONDS_ENV
from sase.tool.argv import ResolvedToolArgv

_CEILING_ENV = SASE_PROVIDER_SYNC_CEILING_SECONDS_ENV

#: Placeholder next action printed in the refusal's monitor form; the agent
#: replaces it with what the follow-up should do with the result.
REFUSAL_NEXT_PLACEHOLDER = "<what the follow-up should do with the result>"

#: Reason printed in the refusal's prepared-completion monitor form.
REFUSAL_COMPLETION_REASON = "Verify before host completion"


def _read_sync_ceiling(env: Mapping[str, str] | None = None) -> int | None:
    """Return the provider synchronous kill ceiling in seconds, if valid.

    Only positive integers count. A missing, empty, non-integer, zero, or
    negative value is treated as absent, so the check fails open.
    """

    import os

    raw = (os.environ if env is None else env).get(_CEILING_ENV)
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


__all__ = [
    "REFUSAL_COMPLETION_REASON",
    "REFUSAL_NEXT_PLACEHOLDER",
    "inline_refusal",
    "monitor_start_form",
    "_read_sync_ceiling",
]
