"""``sase flag enable`` / ``sase flag disable`` — persist a machine-local preference."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable

from rich.console import Console
from rich.text import Text

from sase.axe.process import is_axe_running, restart_axe_daemon_result
from sase.bead_flag_presentation import flag_key_chip
from sase.feature_flags.cli_json import mutation_json
from sase.feature_flags.cli_render import (
    FLAG_DISABLED_STYLE,
    FLAG_ENABLED_STYLE,
    enabled_text,
    on_off,
    render_diagnostics,
    resolve_console,
    source_text,
)
from sase.feature_flags.models import (
    FeatureFlagError,
    FeatureFlagMutationOutcome,
    FeatureFlagStateError,
)
from sase.feature_flags.state import set_saved_feature_flag
from sase.main.update_json import restart_info_json
from sase.main.update_restart import render_restart_info, restart_after_update
from sase.main.update_types import AxeRunningFn, RestartAxeFn, RestartInfo


SET_JSON_SCHEMA_VERSION = 1
APPLY_SAVED_FEATURE_FLAG = "apply the saved feature flag"
ACE_RESTART_NOTICE = (
    "Restart any separately running ACE session to apply the saved feature flag."
)
_AXE_NOT_RUNNING_MESSAGE = "AXE is not running; left stopped."
MutateFn = Callable[[str, bool], FeatureFlagMutationOutcome]


def handle_flag_set(
    args: argparse.Namespace,
    *,
    enabled: bool,
    console: Console | None = None,
    mutate_fn: MutateFn = set_saved_feature_flag,
    axe_running_fn: AxeRunningFn = is_axe_running,
    restart_axe_fn: RestartAxeFn = restart_axe_daemon_result,
) -> int:
    """Persist *enabled* for the parsed flag key and retry the AXE restart."""
    key = str(getattr(args, "flag_key", "") or "")
    as_json = bool(getattr(args, "json", False))
    command = "enable" if enabled else "disable"
    try:
        outcome = mutate_fn(key, enabled)
    except FeatureFlagStateError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except FeatureFlagError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    restart = restart_after_update(
        changed=True,
        axe_running_fn=axe_running_fn,
        restart_axe_fn=restart_axe_fn,
        source=f"sase flag {command}",
    )
    if as_json:
        print(
            json.dumps(
                _set_json(outcome, restart, command=command),
                indent=2,
                sort_keys=True,
            )
        )
        return 0 if restart.status != "failed" else 1

    _render_set(outcome, restart, console=resolve_console(console))
    return 0 if restart.status != "failed" else 1


def _set_json(
    outcome: FeatureFlagMutationOutcome,
    restart: RestartInfo,
    *,
    command: str,
) -> dict[str, object]:
    return {
        "command": command,
        "mutation": mutation_json(outcome),
        "ok": restart.status != "failed",
        "restart": restart_info_json(restart),
        "schema_version": SET_JSON_SCHEMA_VERSION,
    }


def _render_set(
    outcome: FeatureFlagMutationOutcome,
    restart: RestartInfo,
    *,
    console: Console,
) -> None:
    action = "enabled" if outcome.enabled else "disabled"
    heading = flag_key_chip(outcome.key)
    heading.append("  ")
    heading.append(
        action,
        style=FLAG_ENABLED_STYLE if outcome.enabled else FLAG_DISABLED_STYLE,
    )
    console.print(heading)
    console.print(f"previous saved:  {_saved_label(outcome.previous_saved)}")
    effective = Text("effective:       ")
    effective.append_text(enabled_text(outcome.after.enabled))
    effective.append("  ")
    effective.append_text(source_text(outcome.after))
    console.print(effective)
    console.print(f"state:           {outcome.state_path}")
    if outcome.shadowed:
        console.print(
            Text(
                "warning: saved preference is shadowed by "
                f"{source_text(outcome.after).plain}; effective remains "
                f"{on_off(outcome.after.enabled)} for this process",
                style="bold yellow",
            )
        )
    render_diagnostics(outcome.diagnostics, console)
    console.print(Text(ACE_RESTART_NOTICE, style="dim"))
    if restart.status == "skipped_not_running":
        console.print(Text(_AXE_NOT_RUNNING_MESSAGE, style="dim"))
        return
    render_restart_info(
        restart,
        console=console,
        quiet=False,
        purpose=APPLY_SAVED_FEATURE_FLAG,
    )


def _saved_label(value: bool | None) -> str:
    if value is None:
        return "—"
    return on_off(value)


__all__ = [
    "ACE_RESTART_NOTICE",
    "APPLY_SAVED_FEATURE_FLAG",
    "SET_JSON_SCHEMA_VERSION",
    "handle_flag_set",
]
