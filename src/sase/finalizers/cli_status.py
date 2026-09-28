"""Finalizer run-status presentation for the ``sase final`` command group."""

from __future__ import annotations

from collections.abc import Mapping
import json
import os
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.text import Text

from sase.core.finalizer_run_view import (
    FinalizerNodeView,
    RunViewRun,
    RunViewRunInstance,
    finalizer_node_view_from_dict,
)
from sase.core.rust import require_rust_binding
from sase.core.time import format_local
from sase.finalizers._cli_shared import print_error
from sase.finalizers.run_view_inputs import (
    RunTarget,
    build_node_request,
)
from sase.finalizers.view_vocabulary import (
    FAILURE_COLOR,
    FINAL_GLYPH,
    STATE_STYLES,
    SUCCESS_COLOR,
    WARNING_COLOR,
)


class _FinalStatusError(Exception):
    """A ``sase final status`` failure with its process exit code."""

    def __init__(self, message: str, *, exit_code: int) -> None:
        super().__init__(message)
        self.exit_code = exit_code


#: Finalizer inputs whose presence means an artifacts dir has run-view data.
_STATUS_DATA_FILES: tuple[str, ...] = (
    "finalizer_plan.json",
    "finalizer_plan.authority.json",
    "final_context.json",
    "final_submission.json",
    "final_submission_attempts.jsonl",
    "finalizer_result.json",
    "finalizers/progress.jsonl",
)

#: Run dispositions rendered with the shared success color.
_STATUS_SUCCESS_DISPOSITIONS: frozenset[str] = frozenset({"ran"})


def handle_final_status(
    agent: str | None = None,
    *,
    artifacts_dir: str | None = None,
    format_name: str = "pretty",
    console: Console | None = None,
) -> int:
    """Project and render the finalizer run view for one agent.

    Returns 0 when a view was produced (whatever the finalizer outcome),
    1 when the agent is unknown or has no finalizer data, and 2 for usage
    errors.
    """

    try:
        targets, label = _resolve_status_targets(agent, artifacts_dir)
    except _FinalStatusError as exc:
        print_error(console, f"sase final status: {exc}")
        return exc.exit_code
    if not any(
        target.artifacts_dir and _artifacts_dir_has_finalizer_data(target.artifacts_dir)
        for target in targets
    ):
        print_error(console, f"sase final status: no finalizer data for {label!r}")
        return 1
    request = build_node_request(targets)
    try:
        payload = require_rust_binding("project_finalizer_node_view")(dict(request))
    except (AttributeError, ImportError) as exc:
        print_error(console, f"sase final status: run view unavailable: {exc}")
        return 1
    if not isinstance(payload, Mapping):
        print_error(console, "sase final status: run view returned an invalid payload")
        return 1
    if format_name == "json":
        print(json.dumps(dict(payload), indent=2, sort_keys=True))
        return 0
    view = finalizer_node_view_from_dict(dict(payload))
    _render_status_pretty(view, label=label, console=console or Console())
    return 0


def _resolve_status_targets(
    agent: str | None, artifacts_dir: str | None
) -> tuple[list[RunTarget], str]:
    """Return ``(targets, label)`` for a status request.

    An explicit artifacts dir wins. A named agent resolves as a session
    (one target per member in roster order), a session member or
    monitor-turn, or a lone turn. With no argument, the calling turn's
    ``SASE_ARTIFACTS_DIR`` is used; outside a SASE turn that is a usage
    error.
    """

    if artifacts_dir:
        directory = str(artifacts_dir)
        label = Path(directory).name or directory
        return [_target_for_dir(directory, label)], label
    name = (agent or "").strip()
    if name:
        return _resolve_named_status_targets(name)
    current = os.environ.get("SASE_ARTIFACTS_DIR")
    if current:
        label = (
            os.environ.get("SASE_AGENT_NAME") or Path(current).name or "current agent"
        )
        return [_target_for_dir(current, label)], label
    raise _FinalStatusError(
        "no agent given and SASE_ARTIFACTS_DIR is unset (not inside a SASE turn)",
        exit_code=2,
    )


def _resolve_named_status_targets(name: str) -> tuple[list[RunTarget], str]:
    """Resolve a session, turn, or monitor-turn name to run targets."""

    from sase.agent.names import find_agent_session, find_named_agent
    from sase.scripts._agent_chat_from_name_common import find_agent_session_member

    session = find_agent_session(name)
    if session is not None:
        return (
            [
                _target_for_dir(str(member.artifacts_dir), member.name, number=index)
                for index, member in enumerate(session.members)
            ],
            session.base_name,
        )
    member = find_agent_session_member(name)
    if member is not None:
        directory = str(member.artifacts_dir)
        return [_target_for_dir(directory, member.name)], member.name
    named = find_named_agent(name)
    if named is not None:
        return (
            [_target_for_dir(named.artifacts_dir, named.name)],
            named.name,
        )
    raise _FinalStatusError(f"unknown agent {name!r}", exit_code=1)


def _target_for_dir(directory: str, label: str, *, number: int = 0) -> RunTarget:
    """Build one status :class:`RunTarget` for an artifacts dir."""

    return RunTarget(
        run_id=label or "agent turn",
        artifacts_dir=directory,
        number=number,
        label=label or "agent turn",
        kind=_artifacts_dir_kind(directory),
        turn_terminal=(Path(directory) / "done.json").is_file(),
    )


def _artifacts_dir_kind(directory: str) -> str:
    """Return ``"monitor"`` for a durable monitor member, else ``"agent"``."""

    try:
        meta = json.loads((Path(directory) / "agent_meta.json").read_text())
    except (OSError, ValueError):
        return "agent"
    if not isinstance(meta, dict):
        return "agent"
    try:
        from sase.monitor_state import is_real_monitor_member
    except ImportError:
        return "agent"
    role = meta.get("agent_session_role")
    monitor_id = meta.get("monitor_id")
    if isinstance(role, str) and isinstance(monitor_id, str):
        return "monitor" if is_real_monitor_member(role, monitor_id) else "agent"
    return "agent"


def _artifacts_dir_has_finalizer_data(directory: str) -> bool:
    """Return whether an artifacts dir holds any finalizer run-view input."""

    root = Path(directory)
    for filename in _STATUS_DATA_FILES:
        try:
            if (root / filename).stat().st_size > 0:
                return True
        except OSError:
            continue
    try:
        return any(item.is_file() for item in (root / "finalizers").iterdir())
    except OSError:
        return False


def _render_status_pretty(
    view: FinalizerNodeView, *, label: str, console: Console
) -> None:
    """Render a node view in the shared glance vocabulary."""

    header = Text()
    header.append(f"{FINAL_GLYPH} FINAL", style="bold")
    header.append(f" · {label}", style="bold cyan")
    header.append(" · ")
    header.append(_styled_status_text(view.glyph, view.status))
    console.print(header)
    if view.instances:
        # Node instances are the selected set in DAG order; configured-but-
        # unselected instances arrive separately in ``view.unselected``.
        plan_line = Text(f"PLAN · {len(view.instances)} selected")
        console.print(plan_line)
        for item in view.instances:
            line = Text("  ")
            glyph, word = _instance_status_parts(item.status)
            line.append(_styled_status_text(glyph, word))
            line.append(f"  {item.instance_id}", style="bold")
            if item.provider_ref:
                provider = Text(f"  {item.provider_ref}", style="dim")
                line.append_text(provider)
            if item.after:
                line.append(f"  after {', '.join(item.after)}", style="dim")
            if item.selection_reason and item.selection_reason != "selected":
                line.append(f"  · {item.selection_reason}", style="dim")
            console.print(line)
    for run in view.runs:
        _render_status_run(run, console=console)
    if view.unselected:
        console.print(Text("NOT SELECTED", style="dim"))
        for unselected_item in view.unselected:
            line = Text(f"  ○ {unselected_item.instance_id}", style="dim")
            if unselected_item.reason:
                line.append(f" · {unselected_item.reason}", style="dim")
            console.print(line)
    console.print(
        Text(
            f"sase final status {label} · sase final list · sase final doctor",
            style="dim",
        )
    )


def _render_status_run(run: RunViewRun, *, console: Console) -> None:
    """Render one run: disposition, declarations, and instance detail."""

    line = Text()
    line.append(f"RUN {run.label or run.run_id}", style="bold")
    line.append(" · ")
    line.append(_styled_disposition_text(run.disposition))
    if run.reason:
        line.append(f" · {run.reason}", style="dim")
    if run.cycles > 1:
        line.append(f" · {run.cycles} cycles", style="dim")
    console.print(line)
    for declaration in run.declarations:
        entry = Text("  declaration ", style="dim")
        entry.append(_styled_declaration_text(declaration.status))
        detail = _declaration_detail(declaration)
        if detail:
            entry.append(f" {detail}", style="dim")
        console.print(entry)
    for instance in run.instances:
        _render_status_run_instance(run, instance, console=console)
    for drift in run.drift:
        console.print(Text(f"  ⚠ {drift.message}", style=WARNING_COLOR))
    for diagnostic in run.diagnostics:
        console.print(
            _styled_diagnostic_text(
                str(getattr(diagnostic, "severity", "")),
                str(getattr(diagnostic, "code", "")),
                str(getattr(diagnostic, "message", "")),
                indent="  ",
            )
        )


def _render_status_run_instance(
    run: RunViewRun, instance: RunViewRunInstance, *, console: Console
) -> None:
    """Render one per-run instance with attempts, ops, and evidence."""

    line = Text("  ")
    glyph, word = _instance_status_parts(instance.status)
    line.append(_styled_status_text(glyph, word))
    line.append(f"  {instance.instance_id}", style="bold")
    for suffix in _instance_suffixes(instance):
        line.append(f"  {suffix}", style="dim")
    console.print(line)
    for attempt in instance.attempts:
        entry = Text(f"    attempt {attempt.attempt}: {attempt.status}", style="dim")
        if attempt.duration_seconds is not None:
            entry.append(f" {_format_duration(attempt.duration_seconds)}", style="dim")
        if attempt.code:
            entry.append(f" {attempt.code}", style="dim")
        console.print(entry)
    for operation in instance.operations:
        entry = Text(f"    op {operation.op}", style="dim")
        if operation.label:
            entry.append(f" [{operation.label}]", style="dim")
        if operation.returncode is not None:
            entry.append(f" rc={operation.returncode}", style="dim")
        if operation.duration_seconds is not None:
            entry.append(
                f" {_format_duration(operation.duration_seconds)}", style="dim"
            )
        if operation.timed_out:
            entry.append(" timed out", style=WARNING_COLOR)
        console.print(entry)
        for log in operation.logs:
            console.print(
                Text(
                    f"      log finalizers/{instance.instance_id}/{log.name}",
                    style="dim",
                )
            )
        for step in operation.steps:
            console.print(Text(f"      step {step.step}: {step.state}", style="dim"))
    for evidence in instance.evidence:
        value = evidence.display or evidence.value
        console.print(Text(f"    evidence {evidence.kind}: {value}", style="dim"))
    if instance.headline is not None:
        value = instance.headline.display or instance.headline.value
        console.print(Text(f"    headline {instance.headline.kind}: {value}"))
    for diagnostic in instance.diagnostics:
        console.print(
            _styled_diagnostic_text(
                diagnostic.severity,
                diagnostic.code,
                diagnostic.message,
                indent="    ",
            )
        )
    if instance.warnings:
        console.print(Text(f"    ⚠{instance.warnings}", style=WARNING_COLOR))
    if instance.failure_reason:
        console.print(Text(f"    failure: {instance.failure_reason}"))
    if instance.refusal_reason:
        console.print(Text(f"    refused: {instance.refusal_reason}"))
    if instance.deferral is not None:
        paths = ", ".join(instance.deferral.paths)
        console.print(Text(f"    deferred: {instance.deferral.reason} ({paths})"))


def _instance_suffixes(instance: RunViewRunInstance) -> list[str]:
    """Return dimmed qualifier lines for one per-run instance."""

    suffixes: list[str] = []
    if instance.after:
        suffixes.append(f"after {', '.join(instance.after)}")
    if instance.waiting_on:
        suffixes.append(f"waiting on {instance.waiting_on}")
    if instance.blocked_by:
        suffixes.append(f"blocked by {instance.blocked_by}")
    if instance.trigger_kind:
        suffixes.append(f"trigger {instance.trigger_kind}")
    if instance.max_attempts and instance.max_attempts > 1:
        suffixes.append(f"attempt {instance.attempt or 0}/{instance.max_attempts}")
    return suffixes


def _instance_status_parts(status: str) -> tuple[str, str]:
    """Return ``(glyph, word)`` for a per-instance projection status.

    Known C5 statuses map through the shared vocabulary; an unknown
    status renders as its raw word with no glyph and no color rather
    than a wrong label.
    """

    from sase.finalizers.view_vocabulary import INSTANCE_STATUS_STYLES

    style = STATE_STYLES.get(status)
    if style is not None:
        return style.glyph, style.word
    key = INSTANCE_STATUS_STYLES.get(status)
    if key is None:
        return "", status
    mapped = STATE_STYLES[key]
    return mapped.glyph, mapped.word


def _styled_status_text(glyph: str, word: str) -> Text:
    """Return ``glyph + word`` colored in the shared vocabulary."""

    style = STATE_STYLES.get(word)
    text = Text(f"{glyph} {word}" if glyph and glyph != word else word)
    if style is not None:
        text.stylize(style.color)
    return text


def _styled_disposition_text(disposition: str) -> Text:
    """Return a run disposition colored in the shared vocabulary."""

    if disposition in _STATUS_SUCCESS_DISPOSITIONS:
        return Text(f"✓ {disposition}", style=SUCCESS_COLOR)
    style = STATE_STYLES.get(disposition)
    text = Text(disposition)
    if style is not None:
        text.stylize(style.color)
    return text


def _styled_declaration_text(status: str) -> Text:
    """Return a declaration-timeline status in its verdict color."""

    if status == "accepted":
        return Text(status, style=SUCCESS_COLOR)
    if status in ("rejected", "failed"):
        return Text(status, style=FAILURE_COLOR)
    return Text(status, style=WARNING_COLOR)


def _declaration_detail(declaration: Any) -> str:
    """Return the dimmed qualifier for one declaration-timeline entry."""

    parts: list[str] = []
    moment = getattr(declaration, "t", None)
    if isinstance(moment, (int, float)) and not isinstance(moment, bool):
        parts.append(format_local(moment, "%H:%M:%S"))
    code = getattr(declaration, "code", None)
    if code:
        parts.append(str(code))
    count = getattr(declaration, "payload_count", None)
    if isinstance(count, int) and not isinstance(count, bool):
        parts.append(f"{count} payloads")
    first_line = getattr(declaration, "first_line", None)
    if first_line:
        parts.append(str(first_line))
    return " ".join(parts)


def _styled_diagnostic_text(
    severity: str, code: str, message: str, *, indent: str
) -> Text:
    """Return one diagnostic line colored by severity."""

    if severity == "error":
        color: str | None = FAILURE_COLOR
    elif severity == "warning":
        color = WARNING_COLOR
    else:
        color = None
    text = Text(
        f"{indent}{severity} {code}: {message}"
        if severity
        else f"{indent}{code}: {message}"
    )
    if color is not None:
        text.stylize(color)
    return text


def _format_duration(seconds: float) -> str:
    """Format a duration the way the Overview card mockup does."""

    if seconds >= 60:
        minutes = int(seconds // 60)
        rest = int(seconds % 60)
        return f"{minutes}m{rest:02d}s"
    return f"{seconds:.1f}s"


__all__ = [
    "handle_final_status",
]
