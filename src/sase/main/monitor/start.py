"""Start handler for ``sase monitor``."""

from __future__ import annotations

import argparse
import json
import sys

from sase.core.cli_duration import parse_cli_duration
from sase.monitor import (
    MonitorAlreadyRunningError,
    MonitorError,
    StartMonitorRequest,
    default_caller,
    maybe_handoff_monitor_from_agent,
    short_monitor_id,
    start_monitor,
    will_handoff_monitor_to_agent_runner,
)
from sase.monitor.outcome_policy import load_outcome_policy_file
from sase.monitor.profiles import resolve_monitor_profile
from sase.monitor.start import (
    DEFAULT_NEXT_OUTPUT,
    DEFAULT_REASON,
    DEFAULT_TAIL_LINES,
    DEFAULT_TIMEOUT_SECONDS,
)
from sase.monitor_status import MONITOR_STATUS_MAX_CHARS, clamp_monitor_status

from ..monitor_render import monitor_start_json
from .common import infer_project_name, optional_text, resolve_cwd, start_command

_MISSING_START_STATUS = (
    "sase monitor start: -s/--start-status is required -- give the label shown while the "
    "command runs (present tense, e.g. TESTING), and pair it with -S/--stop-status (e.g. "
    "TESTED), or pass -p/--profile verify. Max 20 characters."
)
_MISSING_STOP_STATUS = (
    "sase monitor start: -S/--stop-status is required -- give the label shown when the "
    "command finishes (past tense, e.g. TESTED), and pair it with -s/--start-status (e.g. "
    "TESTING), or pass -p/--profile verify. Max 20 characters."
)
_MODEL_WITHOUT_NEXT = (
    "sase monitor start: -m/--model requires -n/--next -- no follow-up agent would "
    "consume the model selection"
)


def handle_monitor_start(args: argparse.Namespace) -> int:
    """Start a command as a monitor family member."""
    command = start_command(args)
    if not command:
        print(
            "sase monitor start: command is required "
            "(pass `-- COMMAND` or the hidden `-c/--command` alias)",
            file=sys.stderr,
        )
        return 2
    reason = (getattr(args, "reason", None) or DEFAULT_REASON).strip()
    if not reason:
        print("sase monitor start: -r/--reason must not be empty", file=sys.stderr)
        return 2

    checkpoint_ref: str | None = None
    checkpoint_document: dict[str, object] | None = None
    checkpoint_path = optional_text(getattr(args, "checkpoint", None))
    if checkpoint_path:
        from sase.continuation_capture import (
            AuthoredCheckpointError,
            load_authored_checkpoint,
        )

        try:
            authored = load_authored_checkpoint(checkpoint_path)
        except AuthoredCheckpointError as exc:
            print(f"sase monitor start: {exc}", file=sys.stderr)
            return 2
        checkpoint_ref = authored.content_ref
        checkpoint_document = authored.payload

    next_action = getattr(args, "next", None)
    next_model = optional_text(getattr(args, "model", None))
    profile = optional_text(getattr(args, "profile", None))
    policy_path = optional_text(getattr(args, "policy", None))
    if profile and policy_path:
        print(
            "sase monitor start: -p/--profile and -P/--policy are mutually exclusive",
            file=sys.stderr,
        )
        return 2
    outcome_policy = None
    if policy_path:
        try:
            outcome_policy = load_outcome_policy_file(policy_path)
        except ValueError as exc:
            print(f"sase monitor start: {exc}", file=sys.stderr)
            return 2
    completion_ref = optional_text(getattr(args, "completion", None))
    if next_model and not (
        optional_text(next_action) or profile or policy_path or completion_ref
    ):
        print(_MODEL_WITHOUT_NEXT, file=sys.stderr)
        return 2
    profile_config = resolve_monitor_profile(profile)
    if profile and profile_config is None:
        print(f"sase monitor start: unknown -p/--profile {profile!r}", file=sys.stderr)
        return 2
    raw_start_status = getattr(args, "start_status", None) or (
        profile_config.start_status if profile_config is not None else None
    )
    raw_stop_status = getattr(args, "stop_status", None) or (
        profile_config.stop_status if profile_config is not None else None
    )
    if raw_start_status is None:
        print(_MISSING_START_STATUS, file=sys.stderr)
        return 2
    if raw_stop_status is None:
        print(_MISSING_STOP_STATUS, file=sys.stderr)
        return 2
    raw_next_output = getattr(args, "next_output", None)
    next_output = (
        raw_next_output
        or (profile_config.next_output if profile_config is not None else None)
        or DEFAULT_NEXT_OUTPUT
    )

    try:
        raw_timeout = (
            getattr(args, "timeout", None) or f"{int(DEFAULT_TIMEOUT_SECONDS)}s"
        )
        timeout_seconds, timeout_label = parse_cli_duration(
            raw_timeout, flag="-t/--timeout"
        )
        idle_timeout_seconds = 0.0
        idle_timeout_label: str | None = None
        raw_idle_timeout = getattr(args, "idle_timeout", None)
        if raw_idle_timeout:
            idle_timeout_seconds, idle_timeout_label = parse_cli_duration(
                raw_idle_timeout,
                flag="-i/--idle-timeout",
            )
        start_status = _clamp_status_label(raw_start_status, flag="-s/--start-status")
        stop_status = _clamp_status_label(raw_stop_status, flag="-S/--stop-status")
    except ValueError as exc:
        print(f"sase monitor start: {exc}", file=sys.stderr)
        return 2

    explicit_agent = getattr(args, "agent", None)
    if explicit_agent:
        agent = explicit_agent
        exact_caller = False
    else:
        agent = default_caller()
        exact_caller = True
    if not agent:
        print(
            "sase monitor start: no agent given and SASE_AGENT_NAME is unset; "
            "pass -a/--agent explicitly",
            file=sys.stderr,
        )
        return 2

    cwd = resolve_cwd(getattr(args, "cwd", None), agent, exact=exact_caller)
    project_name = infer_project_name(str(cwd))
    if not project_name:
        print(
            f"sase monitor start: could not infer a project from cwd {cwd}",
            file=sys.stderr,
        )
        return 2

    request = StartMonitorRequest(
        command=command,
        reason=reason,
        timeout_seconds=timeout_seconds,
        cwd=str(cwd),
        project_name=project_name,
        lane=explicit_agent,
        label=getattr(args, "label", None),
        next_action=next_action,
        next_model=next_model,
        start_status=start_status,
        stop_status=stop_status,
        tail_lines=getattr(args, "tail_lines", None) or DEFAULT_TAIL_LINES,
        idle_timeout_seconds=idle_timeout_seconds,
        next_output=next_output,
        completion_ref=completion_ref,
        profile=profile,
        outcome_policy=outcome_policy,
        cli_evidence=optional_text(raw_next_output),
        checkpoint_ref=checkpoint_ref,
        checkpoint_document=checkpoint_document,
    )

    try:
        record = start_monitor(request)
    except (MonitorAlreadyRunningError, MonitorError) as exc:
        print(f"sase monitor start: {exc}", file=sys.stderr)
        return 1

    # kill_agent_runner_group() (invoked below, once handed off) never
    # returns, so every line of output must print before it -- including
    # the --json envelope, whose handed_off flag is decided the same way.
    handed_off = will_handoff_monitor_to_agent_runner()

    if bool(getattr(args, "json", False)):
        json.dump(
            monitor_start_json(record, handed_off=handed_off), sys.stdout, indent=2
        )
        sys.stdout.write("\n")
    else:
        short_id = short_monitor_id(record.monitor_id)
        print(f"Started monitor {short_id} ({record.monitor_id})")
        print(f"  member: {record.member_agent_name}")
        print(f"  timeout: {timeout_label}")
        if idle_timeout_label is not None:
            print(f"  idle timeout: {idle_timeout_label}")
        print(f"  sase monitor show {short_id} --follow")
        if handed_off:
            print(
                "\nThis is the last output before the agent runner is killed; "
                "the monitor keeps running."
            )
    sys.stdout.flush()

    maybe_handoff_monitor_from_agent(record)
    return 0


def _clamp_status_label(value: str, *, flag: str) -> str:
    try:
        clamped = clamp_monitor_status(value)
    except ValueError as exc:
        raise ValueError(f"{flag}: {exc}") from exc
    if clamped != value.strip():
        print(
            f"sase monitor start: {flag} truncated to {MONITOR_STATUS_MAX_CHARS} "
            f"chars: {clamped!r}",
            file=sys.stderr,
        )
    return clamped


__all__ = [
    "handle_monitor_start",
]
