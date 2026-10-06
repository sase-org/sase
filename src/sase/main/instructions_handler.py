"""Handler for ``sase instructions`` subcommands."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime


def handle_instructions_command(args: argparse.Namespace) -> None:
    """Dispatch to the appropriate ``sase instructions`` sub-handler."""
    sub = getattr(args, "instructions_subcommand", None) or "list"

    if sub == "list":
        from sase.amd.inventory import run_amd_list

        sys.exit(run_amd_list(args))

    if sub == "verify":
        sys.exit(run_instructions_verify(args))

    print("Usage: sase instructions {list,verify}", file=sys.stderr)
    sys.exit(1)


def run_instructions_verify(args: argparse.Namespace) -> int:
    """Run the observed-mode scoreboard and render it."""
    from sase.instructions import _runs as run_mod
    from sase.instructions.render import (
        render_helper_rows,
        render_json,
        render_table,
    )
    from sase.instructions.verify import build_report, collect_observations

    limit = max(1, min(int(getattr(args, "limit", 20) or 20), 200))
    now = datetime.now(tz=UTC)
    since_raw = getattr(args, "since", "7d") or "7d"
    until_raw = getattr(args, "until", None)
    try:
        since = run_mod.parse_when(str(since_raw), now=now)
    except ValueError as exc:
        print(f"sase instructions verify: {exc}", file=sys.stderr)
        return 2
    try:
        until = (
            run_mod.parse_when(str(until_raw), now=now)
            if until_raw is not None
            else None
        )
    except ValueError as exc:
        print(f"sase instructions verify: {exc}", file=sys.stderr)
        return 2
    providers = tuple(getattr(args, "provider", []) or ())
    agent = getattr(args, "agent", None)
    want_json = bool(getattr(args, "json", False))
    want_helpers = bool(getattr(args, "helpers", False))

    scored = run_mod.enumerate_runs(
        limit_per_provider=limit,
        since=since,
        until=until,
        project=None,
        agent=agent,
        providers=providers,
    )
    observations = collect_observations(scored)
    filters: dict[str, object] = {
        "agent": agent,
        "helpers": want_helpers,
        "limit": limit,
        "providers": list(providers),
        "since": since.isoformat(),
        "until": until.isoformat() if until is not None else None,
    }
    report = build_report(scored, observations, filters=filters)
    include_observations = want_json and (agent is not None or want_helpers)
    if want_json:
        print(render_json(report, include_observations=include_observations))
        return 0
    render_table(report)
    if want_helpers:
        render_helper_rows(report)
    elif agent is not None:
        render_helper_rows(report)
    return 0


__all__ = ["handle_instructions_command", "run_instructions_verify"]
