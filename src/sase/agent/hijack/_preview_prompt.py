"""Continuation prompt preparation and side-effect-free budget preflight."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.agent.hijack.config import agent_hijack_config
from sase.agent.hijack.core import (
    continuation_wire_schema_version,
    hijack_continuation_prompt,
)
from sase.agent.hijack._preview_models import (
    HijackContinuationPrompt,
    HijackRecoveryRefusal,
)
from sase.agent.hijack._preview_recovery import hijack_recovery_preview
from sase.agent.hijack._preview_values import (
    concrete_model_target,
    diff_totals,
    duration,
    string,
    string_list,
)
from sase.core.continuation_facade import plan_continuation_budget
from sase.history.chat_fork.build import build_fork_injected_history
from sase.history.chat_fork.common import load_json_object
from sase.llm_provider.continuation_budget import normalized_decision, refusal_message
from sase.llm_provider.continuation_budget_decision import verify_projection
from sase.llm_provider.continuation_budget_projection import (
    project_prompt,
    prompt_projection,
    utf8_len,
)
from sase.llm_provider.continuation_budget_request import budget_request
from sase.llm_provider.types import LLMInvocationOptions


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

    selected_model = model_target or concrete_model_target(record)
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
    stale_locks = string_list(record.get("stale_lock_files"))

    def make_prompt(mode: str) -> str:
        return hijack_continuation_prompt(
            {
                "schema_version": continuation_wire_schema_version(),
                "original_prompt": original_prompt,
                "hijacked_name": str(record.get("agent_name") or "unknown"),
                "model_target": selected_model,
                "evidence": {
                    "run_duration_display": duration(
                        record.get("run_duration_seconds")
                    ),
                    "last_tool": string(record.get("last_tool")) or "",
                    "last_tool_age": duration(record.get("last_tool_age_seconds")),
                    "files_changed": diff_totals(record)[0],
                    "insertions": diff_totals(record)[1],
                    "deletions": diff_totals(record)[2],
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


def _transcript_path(artifacts_dir: Path, meta: Mapping[str, object]) -> Path | None:
    hinted = string(meta.get("chat_path"))
    candidates = [Path(hinted).expanduser()] if hinted else []
    candidates.append(artifacts_dir / "chat.md")
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def _snapshot_ref(record: Mapping[str, Any]) -> str | None:
    snapshots = record.get("snapshots")
    if not isinstance(snapshots, list):
        return None
    for item in snapshots:
        if isinstance(item, Mapping):
            reference = string(item.get("reference"))
            if reference:
                return reference
    return None


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
