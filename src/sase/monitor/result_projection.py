"""Monitor result wire records and selected evidence rendering."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import json
from typing import Any, cast

from sase.config.core import (
    DEFAULT_MONITOR_FALLBACK_TAIL_BYTES,
    DEFAULT_MONITOR_RAW_TAIL_LINES,
    DEFAULT_MONITOR_SELECTED_DIAGNOSTICS_BYTES,
    DEFAULT_MONITOR_TOTAL_RAW_EXCERPT_BYTES,
    get_monitor_evidence_limits,
)
from sase.core.continuation_facade import select_continuation_evidence
from sase.core.continuation_wire import (
    CONTINUATION_WIRE_SCHEMA_VERSION,
    ContinuationEvidencePolicy,
    DiagnosticManifestWire,
    MonitorOutcome,
    MonitorResultWire,
    MonitorTimeoutKind,
    RetainedLogMetadataWire,
)
from sase.shells.prompt import (
    fenced_block,
    format_shell_duration,
    untrusted_output_section,
)

# Values for ``--next-output`` / ``monitor_next_output``.
NEXT_OUTPUT_CHOICES: tuple[ContinuationEvidencePolicy, ...] = (
    "auto",
    "tail",
    "file",
    "none",
)
DEFAULT_NEXT_OUTPUT: ContinuationEvidencePolicy = "auto"
LEGACY_NEXT_OUTPUT: ContinuationEvidencePolicy = "tail"

SELECTED_DIAGNOSTICS_MAX_BYTES = DEFAULT_MONITOR_SELECTED_DIAGNOSTICS_BYTES
FALLBACK_TAIL_MAX_BYTES = DEFAULT_MONITOR_FALLBACK_TAIL_BYTES
TOTAL_RAW_EXCERPT_MAX_BYTES = DEFAULT_MONITOR_TOTAL_RAW_EXCERPT_BYTES
RAW_TAIL_LINES = DEFAULT_MONITOR_RAW_TAIL_LINES


def _normalize_next_output(
    value: object,
    *,
    missing: ContinuationEvidencePolicy = DEFAULT_NEXT_OUTPUT,
) -> ContinuationEvidencePolicy:
    """Return a valid evidence policy for persisted or user-provided text."""

    if isinstance(value, str) and value in NEXT_OUTPUT_CHOICES:
        return cast(ContinuationEvidencePolicy, value)
    return missing


def _monitor_outcome(
    monitor_state: object,
    *,
    exit_code: int | None = None,
) -> MonitorOutcome:
    """Map a monitor lifecycle state to the continuation outcome enum."""

    state = monitor_state if isinstance(monitor_state, str) else ""
    if state == "completed":
        return "completed"
    if state == "failed":
        return "failed"
    if state == "timeout":
        return "timeout"
    if state == "stopped":
        return "stopped"
    if state == "lost":
        return "lost"
    if exit_code == 0:
        return "completed"
    if isinstance(exit_code, int):
        return "failed"
    return "unknown"


def build_monitor_result_wire(
    *,
    monitor_id: object,
    monitor_state: object,
    exit_code: int | None,
    command: object,
    cwd: object,
    started_at: object,
    stopped_at: object,
    elapsed_seconds: float | int | None,
    timeout_seconds: float | int | None = None,
    timeout_kind: object = None,
    starter_execution_id: object = None,
    workspace_identity: object = None,
    diagnostic_manifest_ref: object = None,
    retained_log: Mapping[str, Any] | None = None,
    result_seed_extra: Mapping[str, Any] | None = None,
) -> MonitorResultWire:
    """Build a Rust-valid monitor-result wire record from local facts."""

    safe_monitor_id = _safe_identifier(monitor_id or "monitor")
    outcome = _monitor_outcome(monitor_state, exit_code=exit_code)
    command_argv = _command_argv(command)
    normalized_exit_code = _exit_code_for_outcome(outcome, exit_code)
    elapsed_ms = _elapsed_ms(elapsed_seconds)
    diagnostic_ref = _wire_reference_or_none(diagnostic_manifest_ref, "diagnostic")
    retained = _retained_log_wire(retained_log)
    seed = {
        "monitor_id": safe_monitor_id,
        "outcome": outcome,
        "exit_code": normalized_exit_code,
        "command": command_argv,
        "cwd": _nonempty_text(cwd, "unknown"),
        "started_at": _nonempty_text(started_at, "unknown"),
        "ended_at": _optional_text(stopped_at),
        "elapsed_ms": elapsed_ms,
        "diagnostic_manifest_ref": diagnostic_ref,
        "retained_log": retained,
        "extra": dict(result_seed_extra or {}),
    }
    result_id = f"result:{safe_monitor_id}:{_sha_json(seed)[:16]}"
    result: dict[str, Any] = {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "result_id": result_id,
        "monitor_id": safe_monitor_id,
        "starter_execution_id": _safe_identifier(
            starter_execution_id or safe_monitor_id
        ),
        "outcome": outcome,
        "command": command_argv,
        "cwd": _nonempty_text(cwd, "unknown"),
        "started_at": _nonempty_text(started_at, "unknown"),
        "workspace_identity": _workspace_identity(workspace_identity),
        "retained_log": retained,
    }
    if normalized_exit_code is not None:
        result["exit_code"] = normalized_exit_code
    ended_at = _optional_text(stopped_at)
    if ended_at:
        result["ended_at"] = ended_at
    if elapsed_ms is not None:
        result["elapsed_ms"] = elapsed_ms
    normalized_timeout = _timeout_kind(timeout_kind, outcome=outcome)
    if normalized_timeout is not None:
        result["timeout_kind"] = normalized_timeout
    timeout_ms = _timeout_budget_ms(timeout_seconds)
    if timeout_ms is not None:
        result["timeout_budget_ms"] = timeout_ms
    if diagnostic_ref:
        result["diagnostic_manifest_ref"] = diagnostic_ref
    return cast(MonitorResultWire, result)


def select_monitor_result_evidence(
    result: MonitorResultWire | Mapping[str, Any],
    *,
    next_output: object,
    diagnostic_manifest: Mapping[str, Any] | None = None,
    historical_result: bool = False,
) -> dict[str, Any]:
    """Ask Rust to choose the monitor evidence projection."""

    request: dict[str, Any] = {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "result": dict(result),
        "policy": _normalize_next_output(next_output),
        "historical_result": bool(historical_result),
        "limits": _monitor_evidence_limits(),
    }
    if diagnostic_manifest:
        request["diagnostic_manifest"] = _diagnostic_manifest_wire(diagnostic_manifest)
    return select_continuation_evidence(request)


def render_monitor_result_block(
    result: Mapping[str, Any],
    selection: Mapping[str, Any],
    *,
    output_text: str | None = None,
    output_log_path: str | None = None,
    selected_diagnostics_text: str | None = None,
    command_text: str | None = None,
    heading_level: int = 3,
) -> list[str]:
    """Render one selected monitor result for fork history projections."""

    heading = "#" * heading_level
    lines = [
        f"{heading} Monitor Result",
        "",
        *_monitor_fact_lines(result),
    ]
    if command_text:
        lines.extend(["", *fenced_block("Command", command_text)])
    lines.extend(
        [
            "",
            *render_monitor_evidence_section(
                result,
                selection,
                output_text=output_text,
                output_log_path=output_log_path,
                selected_diagnostics_text=selected_diagnostics_text,
                heading_level=heading_level + 1,
            ),
        ]
    )
    return lines


def render_monitor_evidence_section(
    result: Mapping[str, Any],
    selection: Mapping[str, Any],
    *,
    output_text: str | None = None,
    output_log_path: str | None = None,
    selected_diagnostics_text: str | None = None,
    heading_level: int = 3,
) -> list[str]:
    """Render the Rust-selected monitor evidence and optional raw excerpt."""

    heading = "#" * heading_level
    policy = str(selection.get("policy") or "unknown")
    context_kind = str(selection.get("context_kind") or "unknown")
    monitor_id = str(result.get("monitor_id") or "monitor")
    retrieval = f"sase monitor show {monitor_id} --all-lines"
    lines = [
        f"{heading} Output Evidence",
        "",
        f"- **Policy:** `{policy}`",
        f"- **Context:** `{context_kind}`",
        f"- **Retrieval:** `{retrieval}`",
    ]
    refs = _string_list(selection.get("selected_refs"))
    if refs:
        lines.append(f"- **Evidence refs:** {_code_list(refs)}")
    locators = _string_list(selection.get("log_locators"))
    if output_log_path:
        locators = _unique_strings([output_log_path, *locators])
    if locators:
        lines.append(f"- **Log locators:** {_code_list(locators)}")
    omissions = _string_list(selection.get("omissions"))
    if omissions:
        lines.append(f"- **Omissions:** {'; '.join(omissions)}")

    if _string_list(selection.get("diagnostic_stage_ids")):
        if selected_diagnostics_text:
            lines.extend(
                [
                    "",
                    f"{heading} Selected diagnostics",
                    "",
                    *fenced_block(
                        "Diagnostics (untrusted program output)",
                        selected_diagnostics_text,
                    ),
                ]
            )
        else:
            lines.extend(["", "_Selected diagnostic text was unavailable._"])

    if bool(selection.get("include_raw_excerpt")):
        tail_lines = _positive_int(selection.get("max_tail_lines"), RAW_TAIL_LINES)
        max_chars = _positive_int(
            selection.get("max_embedded_bytes"),
            TOTAL_RAW_EXCERPT_MAX_BYTES,
        )
        if output_text:
            lines.extend(
                [
                    "",
                    *untrusted_output_section(
                        f"{heading} Selected output (untrusted program output)",
                        output_text,
                        tail_lines,
                        max_chars=max_chars,
                    ),
                ]
            )
        else:
            lines.extend(["", "_No retained output text was available to embed._"])
    else:
        lines.extend(
            [
                "",
                "_Raw output omitted by the selected monitor evidence policy._",
            ]
        )
    return lines


def output_cell_for_selection(
    *,
    total_bytes: int,
    output_truncated: bool,
    selection: Mapping[str, Any],
    log_pointer: str,
    output_log_path: str | None,
) -> str:
    """Render the compact follow-up table cell for selected evidence."""

    parts = [_format_output_summary(total_bytes, output_truncated)]
    policy = str(selection.get("policy") or "unknown")
    context_kind = str(selection.get("context_kind") or "unknown")
    if output_log_path and policy == "file":
        parts.append(f"log file: `{output_log_path}`")
    refs = _string_list(selection.get("selected_refs"))
    if refs:
        parts.append(f"evidence refs: {_code_list(refs)}")
    if not bool(selection.get("include_raw_excerpt")):
        parts.append(f"raw output omitted: `{context_kind}`")
    parts.append(f"full log: `{log_pointer}`")
    return " · ".join(parts)


def selected_raw_limits(
    selection: Mapping[str, Any],
    *,
    requested_tail_lines: int,
) -> tuple[int, int] | None:
    """Return ``(tail_lines, max_chars)`` when Rust selected raw output."""

    if not bool(selection.get("include_raw_excerpt")):
        return None
    selected_lines = _positive_int(selection.get("max_tail_lines"), RAW_TAIL_LINES)
    max_chars = _positive_int(
        selection.get("max_embedded_bytes"),
        TOTAL_RAW_EXCERPT_MAX_BYTES,
    )
    return min(max(1, requested_tail_lines), selected_lines), max_chars


def _monitor_fact_lines(result: Mapping[str, Any]) -> list[str]:
    lines = [
        f"- **Monitor ID:** `{result.get('monitor_id') or 'unknown'}`",
        f"- **Outcome:** `{result.get('outcome') or 'unknown'}`",
    ]
    exit_code = result.get("exit_code")
    if isinstance(exit_code, int) and not isinstance(exit_code, bool):
        lines.append(f"- **Exit code:** `{exit_code}`")
    cwd = result.get("cwd")
    if isinstance(cwd, str) and cwd:
        lines.append(f"- **Cwd:** `{cwd}`")
    started_at = result.get("started_at")
    if isinstance(started_at, str) and started_at:
        lines.append(f"- **Started:** `{started_at}`")
    ended_at = result.get("ended_at")
    if isinstance(ended_at, str) and ended_at:
        lines.append(f"- **Finished:** `{ended_at}`")
    elapsed_ms = result.get("elapsed_ms")
    if isinstance(elapsed_ms, int) and not isinstance(elapsed_ms, bool):
        lines.append(f"- **Elapsed:** `{format_shell_duration(elapsed_ms / 1000)}`")
    return lines


def _format_output_summary(total_bytes: int, truncated: bool) -> str:
    kib = total_bytes / 1024
    summary = f"{kib:,.0f} KiB" if kib >= 1 else f"{total_bytes} bytes"
    return f"{summary} (retained output truncated)" if truncated else summary


def _command_argv(command: object) -> list[str]:
    if isinstance(command, str):
        text = command.strip()
        return _wire_command_parts(["/bin/sh", "-c", text]) if text else ["unknown"]
    if isinstance(command, Sequence) and not isinstance(
        command,
        bytes | bytearray | str,
    ):
        parts = [str(part) for part in command if str(part)]
        return _wire_command_parts(parts) or ["unknown"]
    return ["unknown"]


def _wire_command_parts(parts: Sequence[str]) -> list[str]:
    return [_wire_command_part(part) for part in parts]


def _wire_command_part(part: str) -> str:
    return part


def _monitor_evidence_limits() -> dict[str, int]:
    """Return monitor evidence limits for Rust selection, with safe defaults."""

    try:
        return get_monitor_evidence_limits()
    except Exception:  # noqa: BLE001 - projection should preserve legacy defaults.
        return {
            "selected_diagnostics_bytes": SELECTED_DIAGNOSTICS_MAX_BYTES,
            "fallback_tail_bytes": FALLBACK_TAIL_MAX_BYTES,
            "total_raw_excerpt_bytes": TOTAL_RAW_EXCERPT_MAX_BYTES,
            "raw_tail_lines": RAW_TAIL_LINES,
        }


def _retained_log_wire(
    retained_log: Mapping[str, Any] | None,
) -> RetainedLogMetadataWire:
    retained = dict(retained_log or {})
    result: dict[str, Any] = {}
    log_ref = _wire_reference_or_none(retained.get("log_ref"), "log")
    if log_ref:
        result["log_ref"] = log_ref
    locator = _wire_reference_or_none(retained.get("local_locator"), "locator")
    if locator:
        result["local_locator"] = locator
    total = _optional_int(retained.get("total_observed_bytes"))
    if total is not None:
        result["total_observed_bytes"] = max(0, total)
    ranges = _retained_ranges(retained.get("retained_ranges"))
    if ranges:
        result["retained_ranges"] = ranges
    if "complete" in retained:
        result["complete"] = bool(retained.get("complete"))
    if "drain_confirmed" in retained:
        result["drain_confirmed"] = bool(retained.get("drain_confirmed"))
    return cast(RetainedLogMetadataWire, result)


def _diagnostic_manifest_wire(
    manifest: Mapping[str, Any],
) -> DiagnosticManifestWire:
    return cast(DiagnosticManifestWire, dict(manifest))


def _retained_ranges(value: object) -> list[dict[str, int]]:
    if not isinstance(value, list):
        return []
    ranges: list[dict[str, int]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        start = _optional_int(item.get("start"))
        end = _optional_int(item.get("end"))
        if start is None or end is None or end < start:
            continue
        ranges.append({"start": max(0, start), "end": max(0, end)})
    return ranges


def _exit_code_for_outcome(
    outcome: MonitorOutcome,
    exit_code: int | None,
) -> int | None:
    if outcome == "completed":
        return 0
    if outcome == "failed":
        return exit_code if isinstance(exit_code, int) and exit_code != 0 else 1
    return exit_code if isinstance(exit_code, int) else None


def _timeout_kind(
    value: object,
    *,
    outcome: MonitorOutcome,
) -> MonitorTimeoutKind | None:
    if value == "idle":
        return "no_progress"
    if value in {"wall_clock", "no_progress", "external"}:
        return cast(MonitorTimeoutKind, value)
    if outcome == "timeout":
        return "wall_clock"
    return None


def _elapsed_ms(value: float | int | None) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    return max(0, int(float(value) * 1000))


def _timeout_budget_ms(value: float | int | None) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    seconds = float(value)
    if seconds <= 0:
        return None
    return int(seconds * 1000)


def _workspace_identity(value: object) -> str:
    if isinstance(value, str):
        return value if value.strip() else "unknown"
    if value is not None:
        return str(value)
    return "unknown"


def _optional_text(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _nonempty_text(value: object, fallback: str) -> str:
    if isinstance(value, str) and value:
        return value
    if value is not None:
        text = str(value)
        if text:
            return text
    return fallback


def _wire_reference_or_none(value: object, fallback_kind: str) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    if len(value.encode("utf-8")) <= 1024 and not any(ch.isspace() for ch in value):
        return value
    return f"{fallback_kind}:{_sha_text(value)[:16]}"


def _safe_identifier(value: object, *, max_len: int = 80) -> str:
    text = str(value).strip() or "unknown"
    safe = "".join(ch if ch.isalnum() or ch in "_.:-" else "_" for ch in text)
    safe = safe.strip("_.:-") or "unknown"
    if len(safe.encode("utf-8")) <= max_len:
        return safe
    digest = _sha_text(safe)[:16]
    keep = max(1, max_len - len(digest) - 1)
    return f"{safe[:keep]}:{digest}"


def _positive_int(value: object, default: int) -> int:
    raw = _optional_int(value)
    return raw if raw is not None and raw > 0 else default


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _unique_strings(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _code_list(values: Sequence[str]) -> str:
    return ", ".join(f"`{value}`" for value in values)


def _sha_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha_json(payload: Mapping[str, Any]) -> str:
    data = json.dumps(_json_safe(payload), sort_keys=True, separators=(",", ":"))
    return _sha_text(data)


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray | str):
        return [_json_safe(item) for item in value]
    return str(value)


__all__ = [
    "DEFAULT_NEXT_OUTPUT",
    "FALLBACK_TAIL_MAX_BYTES",
    "LEGACY_NEXT_OUTPUT",
    "NEXT_OUTPUT_CHOICES",
    "RAW_TAIL_LINES",
    "SELECTED_DIAGNOSTICS_MAX_BYTES",
    "TOTAL_RAW_EXCERPT_MAX_BYTES",
    "build_monitor_result_wire",
    "output_cell_for_selection",
    "render_monitor_evidence_section",
    "render_monitor_result_block",
    "select_monitor_result_evidence",
    "selected_raw_limits",
]
