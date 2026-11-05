"""Read-only recovery previews and pinned continuation prompt preparation."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sase.agent.hijack import ledger
from sase.agent.hijack.config import agent_hijack_config, build_alias_candidates
from sase.agent.hijack.core import (
    assemble_hijack_recovery_preview,
    continuation_wire_schema_version,
    escalation_wire_schema_version,
    hijack_continuation_prompt,
    hijack_escalation_target,
    hijack_recovery_preview_wire_schema_version,
)
from sase.history.chat_fork.build import build_fork_injected_history
from sase.history.chat_fork.common import load_json_object
from sase.llm_provider.continuation_budget import normalized_decision, refusal_message
from sase.llm_provider.continuation_budget_projection import (
    project_prompt,
    prompt_projection,
    utf8_len,
)
from sase.llm_provider.continuation_budget_request import budget_request
from sase.llm_provider.types import LLMInvocationOptions
from sase.core.continuation_facade import plan_continuation_budget
from sase.llm_provider.continuation_budget_decision import verify_projection


@dataclass(frozen=True)
class RecoveryAction:
    """One action row returned by the Rust recovery preview policy."""

    action: str
    available: bool
    reason: str | None
    label: str
    detail: str
    target: str | None


@dataclass(frozen=True)
class RecoveryPreview:
    """Stable adapter result for CLI, TUI, and recovery transaction callers."""

    hijack_id: str
    revision: int
    header: Mapping[str, Any]
    default_action: str | None
    actions: tuple[RecoveryAction, ...]
    state: str
    _record: Mapping[str, Any] = field(repr=False, compare=False)
    _artifacts_dir: str = field(repr=False, compare=False)

    def action(self, name: str) -> RecoveryAction | None:
        """Return the preview row for *name*, if present."""
        return next((item for item in self.actions if item.action == name), None)

    def to_dict(self) -> dict[str, Any]:
        """Return the public wire payload without the local ledger snapshot."""
        return {
            "hijack_id": self.hijack_id,
            "revision": self.revision,
            "header": dict(self.header),
            "default_action": self.default_action,
            "actions": [
                {
                    "action": action.action,
                    "available": action.available,
                    "reason": action.reason,
                    "label": action.label,
                    "detail": action.detail,
                    "target": action.target,
                }
                for action in self.actions
            ],
        }


@dataclass(frozen=True)
class HijackContinuationPrompt:
    """Prepared prompt and the side-effect-free context budget decision."""

    prompt: str
    model_target: str
    context_mode: str
    transcript_path: str | None
    expanded_prompt_bytes: int
    budget_decision: Mapping[str, Any]


class HijackRecoveryRefusal(RuntimeError):
    """A typed, user-actionable reason a recovery prompt cannot be prepared."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def hijack_recovery_preview(agent_or_name: object) -> RecoveryPreview:
    """Gather current read-only facts and invoke the Rust preview policy."""
    record, artifacts_dir, meta = _load_recovery_context(agent_or_name)
    state = _record_state(record)
    header = _recovery_header(record)
    model_target = _concrete_model_target(record)
    lineage_to_rung = _lineage_to_rung(meta)
    config = agent_hijack_config()
    escalation = hijack_escalation_target(
        {
            "schema_version": escalation_wire_schema_version(),
            "model_facts": {
                "alias": _string(record.get("model_alias")),
                "alias_trail": _string_list(record.get("model_alias_trail")),
                "origin": _string(record.get("model_origin")),
                "provider": _string(record.get("provider")),
                "model": _string(record.get("model")),
                "effort": _string(record.get("effort")),
            },
            "ladder": list(config.escalation_ladder),
            "alias_candidates": build_alias_candidates(config.escalation_ladder),
            "lineage_to_rung": lineage_to_rung,
            "stalled_concrete": model_target,
        }
    )
    wire = assemble_hijack_recovery_preview(
        {
            "schema_version": hijack_recovery_preview_wire_schema_version(),
            "hijack_id": str(record.get("hijack_id") or ""),
            "revision": _integer(record.get("revision")),
            "state": state,
            "header": header,
            "escalate": escalation,
            "continue_target": model_target,
        }
    )
    return _preview_from_wire(
        wire, record=record, artifacts_dir=artifacts_dir, state=state
    )


def build_hijack_continuation_prompt(
    agent_or_name: object,
    *,
    model_target: str | None = None,
    guidance_requested: bool = False,
    successor_context: str | None = None,
) -> HijackContinuationPrompt:
    """Build a concrete continuation prompt and preflight its expanded context.

    Preview work is read-only: this function does not reserve a session name,
    rotate a model pool, write a budget receipt, or mutate the hijack ledger.
    Invocation-time budget enforcement remains in the normal provider path.
    """
    preview = hijack_recovery_preview(agent_or_name)
    if preview.state != "held":
        raise HijackRecoveryRefusal(
            "not_held",
            f"Keep-work recovery is unavailable while state is {preview.state}",
        )
    record = preview._record
    artifacts_dir = Path(preview._artifacts_dir)
    raw_prompt_path = artifacts_dir / "raw_prompt.md"
    try:
        original_prompt = raw_prompt_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise HijackRecoveryRefusal(
            "missing_prompt",
            f"Could not read the original prompt at {raw_prompt_path}: {exc}",
        ) from exc

    selected_model = model_target or _concrete_model_target(record)
    if not selected_model:
        raise HijackRecoveryRefusal(
            "unknown_model", "The predecessor's concrete model is unknown"
        )

    config = agent_hijack_config()
    requested_context = successor_context or config.successor_context
    if requested_context not in {"fork", "brief"}:
        requested_context = "fork"
    meta = load_json_object(artifacts_dir / "agent_meta.json")
    transcript = _transcript_path(artifacts_dir, meta)
    stale_locks = _string_list(record.get("stale_lock_files"))

    def make_prompt(mode: str) -> str:
        return hijack_continuation_prompt(
            {
                "schema_version": continuation_wire_schema_version(),
                "original_prompt": original_prompt,
                "hijacked_name": str(record.get("agent_name") or "unknown"),
                "model_target": selected_model,
                "evidence": {
                    "run_duration_display": _duration(
                        record.get("run_duration_seconds")
                    ),
                    "last_tool": _string(record.get("last_tool")) or "",
                    "last_tool_age": _duration(record.get("last_tool_age_seconds")),
                    "files_changed": _diff_totals(record)[0],
                    "insertions": _diff_totals(record)[1],
                    "deletions": _diff_totals(record)[2],
                    "snapshot_ref": _snapshot_ref(record) or "",
                    "model_display": str(preview.header.get("model_display") or ""),
                },
                "context_mode": mode,
                "transcript_path": str(transcript)
                if mode == "brief" and transcript
                else None,
                "guidance_requested": guidance_requested,
                "stale_lock_files": stale_locks,
            }
        )

    if requested_context == "fork" and transcript is not None:
        fork_prompt = make_prompt("fork")
        history = build_fork_injected_history(
            [
                {
                    "kind": "agent",
                    "name": str(record.get("agent_name") or "unknown"),
                    "path": str(transcript),
                    "artifact_dir": str(artifacts_dir),
                }
            ],
            record_shadow_measurement=False,
        )
        expanded = _expand_fork_directive(
            fork_prompt,
            name=str(record.get("agent_name") or "unknown"),
            history=history,
        )
        decision = _budget_decision(expanded, model_target=selected_model)
        if str(decision.get("kind") or "") != "refuse":
            return HijackContinuationPrompt(
                prompt=fork_prompt,
                model_target=selected_model,
                context_mode="fork",
                transcript_path=str(transcript),
                expanded_prompt_bytes=utf8_len(expanded),
                budget_decision=decision,
            )

    brief_prompt = make_prompt("brief")
    brief_decision = _budget_decision(brief_prompt, model_target=selected_model)
    if str(brief_decision.get("kind") or "") == "refuse":
        raise HijackRecoveryRefusal(
            "continuation_budget_exceeded", refusal_message(brief_decision)
        )
    return HijackContinuationPrompt(
        prompt=brief_prompt,
        model_target=selected_model,
        context_mode="brief",
        transcript_path=str(transcript) if transcript else None,
        expanded_prompt_bytes=utf8_len(brief_prompt),
        budget_decision=brief_decision,
    )


def validate_hijack_continuation_prompt(
    agent_or_name: object,
    *,
    prompt: str,
    model_target: str,
) -> HijackContinuationPrompt:
    """Preflight an edited continuation prompt without writing artifacts.

    A user-edited ``#fork`` prompt is budgeted with its expanded transcript;
    if it no longer fits, the caller gets a typed refusal instead of silently
    dropping the user's edits. Unedited prompts use
    :func:`build_hijack_continuation_prompt`, which can safely fall back to the
    brief form.
    """
    preview = hijack_recovery_preview(agent_or_name)
    if preview.state != "held":
        raise HijackRecoveryRefusal(
            "not_held",
            f"Keep-work recovery is unavailable while state is {preview.state}",
        )
    record = preview._record
    artifacts_dir = Path(preview._artifacts_dir)
    meta = load_json_object(artifacts_dir / "agent_meta.json")
    transcript = _transcript_path(artifacts_dir, meta)
    name = str(record.get("agent_name") or "unknown")
    fork_pattern = re.compile(r"(?m)^#fork:(?P<name>[^\s]+)\s*$")
    fork_matches = _active_fork_matches(prompt, fork_pattern)
    expanded = prompt
    context_mode = "instruct"
    if fork_matches:
        if len(fork_matches) != 1 or fork_matches[0].group("name") != name:
            raise HijackRecoveryRefusal(
                "invalid_fork_directive",
                "An edited continuation prompt must fork only the held predecessor",
            )
        if transcript is None:
            raise HijackRecoveryRefusal(
                "missing_transcript",
                "The edited fork prompt has no readable predecessor transcript",
            )
        try:
            history = build_fork_injected_history(
                [
                    {
                        "kind": "agent",
                        "name": name,
                        "path": str(transcript),
                        "artifact_dir": str(artifacts_dir),
                    }
                ],
                record_shadow_measurement=False,
            )
            expanded = _expand_fork_directive(prompt, name=name, history=history)
        except Exception as exc:
            raise HijackRecoveryRefusal(
                "invalid_fork_transcript",
                f"Could not prepare the edited fork transcript: {exc}",
            ) from exc
        context_mode = "fork"

    decision = _budget_decision(expanded, model_target=model_target)
    if str(decision.get("kind") or "") == "refuse":
        raise HijackRecoveryRefusal(
            "continuation_budget_exceeded", refusal_message(decision)
        )
    return HijackContinuationPrompt(
        prompt=prompt,
        model_target=model_target,
        context_mode=context_mode,
        transcript_path=str(transcript) if transcript else None,
        expanded_prompt_bytes=utf8_len(expanded),
        budget_decision=decision,
    )


def _load_recovery_context(
    agent_or_name: object,
) -> tuple[dict[str, Any], str, Mapping[str, object]]:
    from sase.agent.names import find_named_agent

    direct_record: dict[str, Any] | None = None
    agent_name: str | None = None
    artifacts_dir: str | None = None
    if isinstance(agent_or_name, Mapping):
        candidate = dict(agent_or_name)
        if candidate.get("hijack_id"):
            direct_record = candidate
        agent_name = _string(candidate.get("agent_name") or candidate.get("name"))
        artifacts_dir = _string(candidate.get("artifacts_dir"))
    elif isinstance(agent_or_name, str):
        direct_record = ledger.load_record(agent_or_name)
        agent_name = agent_or_name
    else:
        agent_name = _string(getattr(agent_or_name, "name", None))
        artifacts_dir = _string(getattr(agent_or_name, "artifacts_dir", None))

    if artifacts_dir is None and agent_name:
        try:
            found = find_named_agent(agent_name)
        except Exception:
            found = None
        artifacts_dir = _string(getattr(found, "artifacts_dir", None))
    if artifacts_dir and direct_record is None:
        direct_record = ledger.load_record_by_artifacts_dir(artifacts_dir)
    if direct_record is None and agent_name:
        direct_record = ledger.load_record_by_agent_name(agent_name)

    meta: Mapping[str, object] = {}
    if artifacts_dir:
        meta = load_json_object(Path(artifacts_dir) / "agent_meta.json")
        done = load_json_object(Path(artifacts_dir) / "done.json")
        recovery = done.get("recovery")
        hijack_id = recovery.get("hijack_id") if isinstance(recovery, Mapping) else None
        if direct_record is None and isinstance(hijack_id, str) and hijack_id:
            direct_record = ledger.load_record(hijack_id)
    if direct_record is None:
        subject = agent_name or str(agent_or_name)
        raise HijackRecoveryRefusal(
            "record_not_found", f"No hijack recovery record was found for {subject}"
        )
    record = dict(direct_record)
    artifacts_dir = _string(record.get("artifacts_dir")) or artifacts_dir
    if not artifacts_dir:
        raise HijackRecoveryRefusal(
            "missing_artifacts",
            "The hijack record has no predecessor artifact directory",
        )
    if not meta:
        meta = load_json_object(Path(artifacts_dir) / "agent_meta.json")
    return record, artifacts_dir, meta


def _preview_from_wire(
    wire: Mapping[str, Any],
    *,
    record: Mapping[str, Any],
    artifacts_dir: str,
    state: str,
) -> RecoveryPreview:
    raw_actions = wire.get("actions")
    actions: list[RecoveryAction] = []
    if isinstance(raw_actions, Sequence) and not isinstance(raw_actions, (str, bytes)):
        for value in raw_actions:
            if not isinstance(value, Mapping):
                continue
            actions.append(
                RecoveryAction(
                    action=_string(value.get("action")) or "",
                    available=bool(value.get("available")),
                    reason=_string(value.get("reason")),
                    label=_string(value.get("label")) or "",
                    detail=_string(value.get("detail")) or "",
                    target=_string(value.get("target")),
                )
            )
    header = wire.get("header")
    return RecoveryPreview(
        hijack_id=_string(wire.get("hijack_id")) or str(record.get("hijack_id") or ""),
        revision=_integer(wire.get("revision")),
        header=dict(header) if isinstance(header, Mapping) else {},
        default_action=_string(wire.get("default_action")),
        actions=tuple(actions),
        state=state,
        _record=dict(record),
        _artifacts_dir=artifacts_dir,
    )


def _record_state(record: Mapping[str, Any]) -> str:
    state = _string(record.get("state")) or "unknown"
    return state


def _recovery_header(record: Mapping[str, Any]) -> dict[str, Any]:
    files, insertions, deletions = _diff_totals(record)
    return {
        "agent_name": _string(record.get("agent_name")) or "unknown",
        "workspace_num": _integer_or_none(record.get("workspace_num")),
        "model_display": _model_display(record),
        "run_duration_display": _duration(record.get("run_duration_seconds")),
        "hijacked_ago": _age_since(record.get("hijacked_at")),
        "files_changed": files,
        "insertions": insertions,
        "deletions": deletions,
        "last_tool": _string(record.get("last_tool")) or "",
        "last_tool_age": _duration(record.get("last_tool_age_seconds")),
    }


def _model_display(record: Mapping[str, Any]) -> str:
    from sase.history.chat_storage import format_metadata_model

    provider = _string(record.get("provider"))
    model = _string(record.get("model"))
    display = format_metadata_model(provider, model) or "unknown model"
    effort = _string(record.get("effort"))
    if effort and not display.endswith(f"@{effort}"):
        display += f"@{effort}"
    return display


def _concrete_model_target(record: Mapping[str, Any]) -> str | None:
    provider = _string(record.get("provider"))
    model = _string(record.get("model"))
    if not model:
        return None
    concrete = model if "/" in model or not provider else f"{provider}/{model}"
    effort = _string(record.get("effort"))
    if effort and not concrete.endswith(f"@{effort}"):
        concrete += f"@{effort}"
    return concrete


def _lineage_to_rung(meta: Mapping[str, object]) -> str | None:
    lineage = meta.get("hijack_lineage")
    if not isinstance(lineage, Mapping):
        lineage = meta.get("recovery_lineage")
    return _string(lineage.get("to_rung")) if isinstance(lineage, Mapping) else None


def _diff_totals(record: Mapping[str, Any]) -> tuple[int, int, int]:
    diffs = record.get("repo_diffs")
    files = insertions = deletions = 0
    if isinstance(diffs, list):
        for entry in diffs:
            if not isinstance(entry, Mapping):
                continue
            files += _integer(entry.get("files_changed"))
            insertions += _integer(entry.get("insertions"))
            deletions += _integer(entry.get("deletions"))
    return files, insertions, deletions


def _snapshot_ref(record: Mapping[str, Any]) -> str | None:
    snapshots = record.get("snapshots")
    if not isinstance(snapshots, list):
        return None
    for item in snapshots:
        if isinstance(item, Mapping):
            reference = _string(item.get("reference"))
            if reference:
                return reference
    return None


def _transcript_path(artifacts_dir: Path, meta: Mapping[str, object]) -> Path | None:
    hinted = _string(meta.get("chat_path"))
    candidates = [Path(hinted).expanduser()] if hinted else []
    candidates.append(artifacts_dir / "chat.md")
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def _expand_fork_directive(prompt: str, *, name: str, history: str) -> str:
    pattern = re.compile(rf"(?m)^#fork:{re.escape(name)}\s*$")
    matches = _active_fork_matches(prompt, pattern)
    if len(matches) != 1:
        raise HijackRecoveryRefusal(
            "invalid_fork_directive",
            "The continuation prompt must include one active fork directive",
        )
    match = matches[0]
    return prompt[: match.start()] + history + prompt[match.end() :]


def _active_fork_matches(prompt: str, pattern: re.Pattern[str]) -> list[re.Match[str]]:
    from sase.macro._literal_zones import literal_zone_ranges

    inert_ranges = literal_zone_ranges(prompt)
    return [
        match
        for match in pattern.finditer(prompt)
        if not any(start <= match.start() < end for start, end in inert_ranges)
    ]


def _budget_decision(prompt: str, *, model_target: str) -> dict[str, Any]:
    provider, model, effort = _split_model_target(model_target)
    projection = prompt_projection(prompt)
    request = budget_request(
        prompt,
        os.environ,
        provider_name=provider,
        model_tier="large",
        model_name=model,
        options=LLMInvocationOptions(reasoning_effort=effort),
        projection=projection,
    )
    decision = normalized_decision(plan_continuation_budget(request))
    projected = project_prompt(prompt, decision, projection)
    return verify_projection(decision, projected)


def _split_model_target(value: str) -> tuple[str, str, str | None]:
    base, separator, raw_effort = value.rpartition("@")
    effort: str | None = raw_effort
    if not separator or effort not in {
        "none",
        "minimal",
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
    }:
        base, effort = value, None
    provider, slash, model = base.partition("/")
    if not slash or not provider or not model:
        raise HijackRecoveryRefusal(
            "invalid_model_target",
            f"Recovery target must be concrete provider/model: {value}",
        )
    return provider, model, effort


def _age_since(value: object) -> str:
    from sase.core.time import local_now, parse_local

    raw = _string(value)
    if not raw:
        return ""
    try:
        parsed = parse_local(raw)
        if parsed is None:
            return ""
        seconds = max(0.0, (local_now() - parsed).total_seconds())
    except (TypeError, ValueError):
        return ""
    return _duration(seconds)


def _duration(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return ""
    seconds = int(value)
    if seconds < 60:
        return "<1m"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours, remaining = divmod(minutes, 60)
    return f"{hours}h {remaining}m" if remaining else f"{hours}h"


def _integer(value: object) -> int:
    return value if type(value) is int else 0


def _integer_or_none(value: object) -> int | None:
    return value if type(value) is int else None


def _string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _string_list(value: object) -> list[str]:
    return (
        [item for item in value if isinstance(item, str) and item]
        if isinstance(value, list)
        else []
    )


__all__ = [
    "HijackContinuationPrompt",
    "HijackRecoveryRefusal",
    "RecoveryAction",
    "RecoveryPreview",
    "build_hijack_continuation_prompt",
    "hijack_recovery_preview",
    "validate_hijack_continuation_prompt",
]
