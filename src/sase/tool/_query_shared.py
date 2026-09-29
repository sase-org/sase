"""Shared query helpers for ``sase tool runs`` and ``sase tool show``.

This is a private module: the names defined here are public only so the
``sase.tool.query_*`` siblings can import them without touching a
``_``-prefixed name across modules. External code must keep importing
the ``sase.tool.query`` facade.
"""

from __future__ import annotations

import time
from typing import Any, TextIO, cast

from sase.config.tools import DEFAULT_TOOL_RUNS_DETAIL_DAYS
from sase.core.tool_run import tool_run_triage_show
from sase.tool.logs import log_policy, read_truncation_messages
from sase.tool.render import (
    EMPTY,
    format_argv,
    format_duration_ms,
    format_state,
    format_tool_name,
)
from sase.tool.stage_protocol import format_stage_progress
from sase.tool.triage_display import show_triage_lines


def logs_map(run: dict[str, Any]) -> dict[str, Any]:
    raw = run.get("logs")
    return cast(dict[str, Any], raw) if isinstance(raw, dict) else {}


def write_bytes(stream: TextIO, data: bytes) -> None:
    buffer = getattr(stream, "buffer", None)
    if buffer is not None:
        buffer.write(data)
        buffer.flush()
        return
    stream.write(data.decode("utf-8", "replace"))
    stream.flush()


def output_truncation(run: dict[str, Any]) -> list[str]:
    return read_truncation_messages(
        logs_map(run).get("events_path"), str(run.get("run_id") or "")
    )


def detail_retention(run: dict[str, Any]) -> dict[str, Any]:
    """State the detail horizon; a run older than it may have lost its detail."""

    days = int(log_policy().get("detail_days") or DEFAULT_TOOL_RUNS_DETAIL_DAYS)
    settled = run.get("settled_ts")
    old = type(settled) is int and time.time() - settled > days * 86400
    return {"detail_days": days, "detail_may_be_pruned": bool(old)}


def show_triage(run_id: str) -> dict[str, Any]:
    """Read durable triage without making explicit show depend on the footer flag."""

    try:
        shown = tool_run_triage_show({"run_id": run_id})
    except Exception as exc:  # noqa: BLE001 - preserve ordinary show for old stores.
        return {
            "schema_version": 1,
            "run_id": run_id,
            "run_found": True,
            "triaged": False,
            "stages": [],
            "items": [],
            "diagnostics": [f"triage unavailable: {exc}"],
        }
    if not isinstance(shown, dict):
        return shown
    facts = shown.get("run_facts")
    extra = facts.get("diagnostics") if isinstance(facts, dict) else None
    if extra:
        merged = [str(item) for item in shown.get("diagnostics") or () if str(item)]
        for item in extra:
            text = str(item)
            if text and text not in merged:
                merged.append(text)
        shown["diagnostics"] = merged
    return shown


def print_show(envelope: dict[str, Any]) -> None:
    run = envelope.get("run")
    if not isinstance(run, dict):
        return
    logs = logs_map(run)
    retention_line = _format_owner_retention(run, envelope.get("owner_retention"))
    lines = [
        f"RUN       {run.get('run_id') or EMPTY}",
        f"TOOL      {format_tool_name(run)}",
        f"STATE     {format_state(run)}",
        f"ARGV      {format_argv(run)}",
        f"PROJECT   {run.get('project') or EMPTY}",
        f"LAUNCH    {run.get('launch_mode') or 'foreground'}",
        f"OWNER     {_format_owner(run)}",
        f"PARENT    {run.get('parent_run_id') or EMPTY}",
        f"DURATION  {format_duration_ms(run.get('duration_ms') if type(run.get('duration_ms')) is int else None)}",
        f"EXIT      {run.get('exit_code') if run.get('exit_code') is not None else EMPTY}",
        f"SIGNAL    {run.get('signal') if run.get('signal') is not None else EMPTY}",
        f"CAUSE     {run.get('terminal_cause') or EMPTY}",
        f"SETTLED   {run.get('settled_by') or EMPTY}",
        f"STOP      {_format_stop_request(run)}",
        f"LOST      {run.get('lost_reason') or EMPTY}",
        f"STDOUT    {logs.get('stdout_path') or EMPTY}",
        f"STDERR    {logs.get('stderr_path') or EMPTY}",
        f"EVENTS    {logs.get('events_path') or EMPTY}",
        f"OWNERLOG  {logs.get('owner_log_path') or EMPTY}",
        *([retention_line] if retention_line is not None else []),
        f"EVIDENCE  {_format_evidence(run)}",
        f"MUTATED   {_format_optional_bool(run.get('mutated_input'))}",
        f"DIRTY     {_dirty_count(run.get('fingerprint_before'))} -> {_dirty_count(run.get('fingerprint_after'))}",
        f"TOOLCHAIN {_format_toolchain(run)}",
        f"SAMPLES   {len(envelope.get('samples') or ())}",
    ]
    diagnostics = run.get("diagnostics") or ()
    if diagnostics:
        lines.append("DIAG")
        for diagnostic in diagnostics:
            lines.append(f"  {diagnostic}")
    if envelope.get("stages"):
        unattributed = envelope.get("unattributed_ms")
        unattr_line = (
            "UNATTRIB  "
            f"{format_duration_ms(unattributed if type(unattributed) is int else None)}"
        )
        if envelope.get("unattributed_incomplete"):
            unattr_line += "  incomplete"
        lines.append(unattr_line)
    print("\n".join(lines))
    stages = envelope.get("stages") or ()
    if stages:
        print("STAGES")
        for stage in stages:
            if not isinstance(stage, dict):
                continue
            print(f"  {format_stage_progress(stage)}")
    samples = envelope.get("samples") or ()
    if samples:
        print("SAMPLES")
        for sample in samples:
            if not isinstance(sample, dict):
                continue
            print(f"  {_format_sample(sample)}")
    for line in show_triage_lines(envelope.get("triage")):
        print(line)


def _format_owner_retention(run: dict[str, Any], retention: object) -> str | None:
    """Render ``OWNERRET`` for an owner-bound run; ``None`` when unowned."""

    if not isinstance(retention, dict) or retention.get("owner") in (None, "none"):
        return None
    owner = retention["owner"]
    log = retention.get("log")
    if log == "retained":
        log_text = "log retained"
    elif log == "missing":
        log_text = "log not retained" if owner == "pruned" else "log missing"
    else:
        log_text = "log not recorded"
    return (
        f"OWNERRET  {run.get('owner_kind') or EMPTY} "
        f"{run.get('owner_id') or EMPTY}: {owner}; {log_text}"
    )


def _format_evidence(run: dict[str, Any]) -> str:
    evidence = run.get("evidence_completeness")
    if not isinstance(evidence, dict):
        return EMPTY
    if evidence.get("complete"):
        return "complete"
    missing = evidence.get("missing") or ()
    detail = ", ".join(str(item) for item in missing if item)
    if detail:
        return f"incomplete ({detail})"
    return "incomplete"


def _format_optional_bool(value: object) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    return EMPTY


def _dirty_count(fingerprint: object) -> int:
    if not isinstance(fingerprint, dict):
        return 0
    total = 0
    for repo in fingerprint.get("repos") or ():
        if isinstance(repo, dict):
            total += len(repo.get("dirty_paths") or ())
    return total


def _format_toolchain(run: dict[str, Any]) -> str:
    fingerprint = run.get("fingerprint_after") or run.get("fingerprint_before")
    if not isinstance(fingerprint, dict):
        return EMPTY
    toolchain = fingerprint.get("toolchain") or {}
    if not isinstance(toolchain, dict) or not toolchain:
        return EMPTY
    parts: list[str] = []
    for name, probe in toolchain.items():
        if not isinstance(probe, dict):
            continue
        if probe.get("incomplete"):
            parts.append(f"{name}=incomplete")
            continue
        output = str(probe.get("output") or "").strip().splitlines()
        parts.append(f"{name}={output[0] if output else EMPTY}")
    return "  ".join(parts) or EMPTY


def _format_sample(sample: dict[str, Any]) -> str:
    elapsed = sample.get("elapsed_ms")
    load = sample.get("loadavg_1")
    psi = sample.get("psi_cpu_some")
    load_text = f"{load:.2f}" if isinstance(load, (int, float)) else EMPTY
    psi_text = f"{psi:.2f}" if isinstance(psi, (int, float)) else EMPTY
    elapsed_text = format_duration_ms(elapsed) if type(elapsed) is int else EMPTY
    return f"{elapsed_text}  load1={load_text}  psi_cpu={psi_text}"


def _format_owner(run: dict[str, Any]) -> str:
    kind = run.get("owner_kind")
    owner_id = run.get("owner_id")
    if kind and owner_id:
        return f"{kind}:{owner_id}"
    return EMPTY


def _format_stop_request(run: dict[str, Any]) -> str:
    stop = run.get("stop_request")
    if not isinstance(stop, dict):
        return EMPTY
    by = str(stop.get("requested_by") or "").strip()
    return f"requested by {by}" if by else "requested"


__all__ = [
    "detail_retention",
    "logs_map",
    "output_truncation",
    "print_show",
    "show_triage",
    "write_bytes",
]
