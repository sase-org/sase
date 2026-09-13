"""Budget preflight for continuation-backed provider invocations."""

from __future__ import annotations

import json
import os
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.core.continuation_facade import plan_continuation_budget
from sase.core.continuation_wire import CONTINUATION_WIRE_SCHEMA_VERSION
from sase.llm_provider.continuation_budget_spans import extract_reducible_spans
from sase.llm_provider.types import LLMInvocationError, LLMInvocationOptions, ModelTier

MONITOR_CONTINUATION_ENV = "SASE_MONITOR_CONTINUATION"
CONTINUATION_BUDGET_ENFORCE_ENV = "SASE_CONTINUATION_BUDGET_ENFORCE"
CONTINUATION_BUDGET_DECISION_FILENAME = "continuation_budget_decision.json"

_DEFAULT_CONTEXT_LIMIT_BYTES = 800_000
_AGY_PRINT_PROMPT_TRANSPORT_LIMIT_BYTES = 120 * 1024
_AGY_PRINT_PROMPT_OVERHEAD_BYTES = 512
_PROVIDER_TRANSPORT_LIMIT_BYTES = {
    "agy": _AGY_PRINT_PROMPT_TRANSPORT_LIMIT_BYTES,
}
_PROVIDER_INSTRUCTION_RESERVE_BYTES = {
    "agy": _AGY_PRINT_PROMPT_OVERHEAD_BYTES,
}
_ENV_TO_CONFIG_KEY = {
    "context_limit_bytes": "SASE_CONTINUATION_CONTEXT_LIMIT_BYTES",
    "transport_limit_bytes": "SASE_CONTINUATION_TRANSPORT_LIMIT_BYTES",
    "checkpoint_threshold_bytes": "SASE_CONTINUATION_CHECKPOINT_THRESHOLD_BYTES",
    "instruction_reserve_bytes": "SASE_CONTINUATION_INSTRUCTION_RESERVE_BYTES",
    "tool_reserve_bytes": "SASE_CONTINUATION_TOOL_RESERVE_BYTES",
    "output_reserve_bytes": "SASE_CONTINUATION_OUTPUT_RESERVE_BYTES",
    "reasoning_reserve_bytes": "SASE_CONTINUATION_REASONING_RESERVE_BYTES",
}
_OMISSION_MESSAGES = {
    "newest_diagnostics": (
        "Selected diagnostics omitted by continuation budget; "
        "use the evidence refs and monitor retrieval command above."
    ),
    "old_raw_excerpts": (
        "Raw output excerpt omitted by continuation budget; "
        "use the retained log refs or monitor retrieval command above."
    ),
    "checkpoint": (
        "Pre-checkpoint assistant transcript omitted by continuation "
        "budget; the checkpoint in this block preserves the current "
        "objective, constraints, findings, and remaining work."
    ),
}


@dataclass(frozen=True, slots=True)
class _PromptReplacement:
    kind: str
    start: int
    end: int
    replacement: str
    checkpoint_ref: str | None = None
    covered_node_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _PromptProjection:
    rendered_prompt_bytes: int
    essential_bytes: int
    selected_evidence_bytes: int
    candidates: tuple[dict[str, Any], ...]
    replacements_by_kind: Mapping[str, tuple[_PromptReplacement, ...]]


def enforce_continuation_budget(
    prompt: str,
    *,
    artifacts_dir: str | None,
    provider_name: str,
    model_tier: ModelTier,
    model_override: str | None,
    model_name: str | None = None,
    options: LLMInvocationOptions,
    env: Mapping[str, str] | None = None,
) -> str:
    """Record and enforce the Rust-owned continuation budget decision."""

    runtime_env = env or os.environ
    if not _budget_required(runtime_env):
        return prompt

    projection = _prompt_projection(prompt)
    request = _budget_request(
        prompt,
        runtime_env,
        provider_name=provider_name,
        model_tier=model_tier,
        model_name=model_name or model_override,
        options=options,
        projection=projection,
    )
    decision = _normalized_decision(plan_continuation_budget(request))
    projected_prompt = _project_prompt(prompt, decision, projection)
    decision = _verify_projection(decision, projected_prompt)
    record = {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "kind": "continuation_budget_preflight",
        "provider": provider_name,
        "model_tier": model_tier,
        "model": model_name or model_override,
        "reasoning_effort": options.reasoning_effort,
        "request": request,
        "decision": decision,
        "projected_prompt_bytes": _utf8_len(projected_prompt),
        "recorded_at_epoch": time.time(),
    }
    projected_prompt_path = _persist_projected_prompt(
        artifacts_dir,
        projected_prompt,
        original_prompt=prompt,
        decision=decision,
    )
    if projected_prompt_path:
        record["projected_prompt_path"] = projected_prompt_path
    decision_path = _persist_decision(artifacts_dir, record)
    _record_child_metadata(
        artifacts_dir,
        decision,
        decision_path=decision_path,
        projected_prompt_bytes=_utf8_len(projected_prompt),
        projected_prompt_path=projected_prompt_path,
    )

    if str(decision.get("kind") or "") != "refuse":
        return projected_prompt

    message = _refusal_message(decision)
    _record_parent_refusal(
        runtime_env,
        message,
        decision_path=decision_path,
        prompt_path=_prompt_path(artifacts_dir),
    )
    _record_delivery_refusal(
        runtime_env,
        message,
        decision_path=decision_path,
    )
    raise LLMInvocationError(message)


def _budget_required(env: Mapping[str, str]) -> bool:
    return (
        env.get(MONITOR_CONTINUATION_ENV) == "1"
        or env.get(CONTINUATION_BUDGET_ENFORCE_ENV) == "1"
    )


def _budget_request(
    prompt: str,
    env: Mapping[str, str],
    *,
    provider_name: str,
    model_tier: ModelTier,
    model_name: str | None,
    options: LLMInvocationOptions,
    projection: _PromptProjection | None = None,
) -> dict[str, Any]:
    from sase.llm_provider.config import get_llm_provider_config

    raw_config = get_llm_provider_config()
    budget_config = raw_config.get("continuation_budget") if raw_config else None
    config = budget_config if isinstance(budget_config, Mapping) else {}
    layers = _config_layers(config, provider_name=provider_name, model_name=model_name)
    prompt_projection = projection or _prompt_projection(prompt)
    provider_budget = _provider_budget(
        env,
        provider_name=provider_name,
        layers=layers,
    )
    request: dict[str, Any] = {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "rendered_prompt_bytes": prompt_projection.rendered_prompt_bytes,
        "essential_bytes": prompt_projection.essential_bytes,
        "selected_evidence_bytes": prompt_projection.selected_evidence_bytes,
        "provider_budget": provider_budget,
        "reduction_candidates": list(prompt_projection.candidates),
        "provider": provider_name,
        "model_tier": model_tier,
        "model": model_name,
        "reasoning_effort": options.reasoning_effort,
    }
    threshold = _int_setting("checkpoint_threshold_bytes", env, layers)
    if threshold is not None:
        request["checkpoint_threshold_bytes"] = threshold
    return request


def _provider_budget(
    env: Mapping[str, str],
    *,
    provider_name: str,
    layers: tuple[Mapping[str, object], ...],
) -> dict[str, Any]:
    instruction_reserve = (
        _int_setting("instruction_reserve_bytes", env, layers, default=0) or 0
    )
    instruction_reserve = max(
        instruction_reserve,
        _PROVIDER_INSTRUCTION_RESERVE_BYTES.get(provider_name, 0),
    )
    return {
        "context_limit_bytes": _int_setting(
            "context_limit_bytes",
            env,
            layers,
            default=_DEFAULT_CONTEXT_LIMIT_BYTES,
        ),
        "transport_limit_bytes": _int_setting(
            "transport_limit_bytes",
            env,
            layers,
            default=_PROVIDER_TRANSPORT_LIMIT_BYTES.get(provider_name),
        ),
        "instruction_reserve_bytes": instruction_reserve,
        "tool_reserve_bytes": _int_setting(
            "tool_reserve_bytes",
            env,
            layers,
            default=0,
        )
        or 0,
        "output_reserve_bytes": _int_setting(
            "output_reserve_bytes",
            env,
            layers,
            default=0,
        )
        or 0,
        "reasoning_reserve_bytes": _int_setting(
            "reasoning_reserve_bytes",
            env,
            layers,
            default=0,
        )
        or 0,
        "estimate_uncertain": _bool_setting(
            "estimate_uncertain",
            layers,
            default=True,
        ),
    }


def _normalized_decision(decision: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(decision)
    if "target_prompt_bytes" not in normalized:
        normalized["target_prompt_bytes"] = normalized.get("prompt_budget_bytes")
    if normalized.get("kind") == "refuse":
        normalized.setdefault("disposition", "context_budget_exceeded")
        if not normalized.get("recovery_guidance"):
            normalized["recovery_guidance"] = [
                "Resume with an adequate explicit checkpoint or choose a route "
                "with a larger context budget.",
                "Do not rerun the monitored command solely to rebuild context.",
            ]
    return normalized


def _int_setting(
    key: str,
    env: Mapping[str, str],
    config_layers: tuple[Mapping[str, object], ...],
    *,
    default: int | None = None,
) -> int | None:
    raw: object | None = env.get(_ENV_TO_CONFIG_KEY[key])
    if raw is None:
        for config in reversed(config_layers):
            if key in config:
                raw = config.get(key)
                break
    if raw is None or isinstance(raw, bool):
        return default
    if not isinstance(raw, (int, str)):
        return default
    if isinstance(raw, int):
        return raw if raw > 0 else default
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _bool_setting(
    key: str,
    config_layers: tuple[Mapping[str, object], ...],
    *,
    default: bool,
) -> bool:
    for config in reversed(config_layers):
        if key not in config:
            continue
        value = config.get(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().casefold()
            if lowered in {"1", "true", "yes", "on"}:
                return True
            if lowered in {"0", "false", "no", "off"}:
                return False
    return default


def _config_layers(
    config: Mapping[str, object],
    *,
    provider_name: str,
    model_name: str | None,
) -> tuple[Mapping[str, object], ...]:
    layers: list[Mapping[str, object]] = [config]
    providers = config.get("providers")
    provider_config: Mapping[str, object] | None = None
    if isinstance(providers, Mapping):
        raw_provider = providers.get(provider_name)
        if isinstance(raw_provider, Mapping):
            provider_config = raw_provider
            layers.append(provider_config)
    if model_name and provider_config is not None:
        models = provider_config.get("models")
        if isinstance(models, Mapping):
            raw_model = models.get(model_name)
            if isinstance(raw_model, Mapping):
                layers.append(raw_model)
    return tuple(layers)


def _prompt_projection(prompt: str) -> _PromptProjection:
    replacements = _discover_replacements(prompt)
    by_kind: dict[str, list[_PromptReplacement]] = {}
    for replacement in replacements:
        saved = _replacement_saved_bytes(prompt, replacement)
        if saved <= 0:
            continue
        by_kind.setdefault(replacement.kind, []).append(replacement)

    candidates: list[dict[str, Any]] = []
    reducible_bytes = 0
    selected_evidence_bytes = 0
    replacements_by_kind: dict[str, tuple[_PromptReplacement, ...]] = {}
    for kind, items in by_kind.items():
        replacements_by_kind[kind] = tuple(items)
        bytes_saved = sum(_replacement_saved_bytes(prompt, item) for item in items)
        reducible_bytes += bytes_saved
        if kind in {"old_raw_excerpts", "newest_diagnostics"}:
            selected_evidence_bytes += bytes_saved
        candidate: dict[str, Any] = {
            "kind": kind,
            "bytes": bytes_saved,
        }
        checkpoint_refs = [item.checkpoint_ref for item in items if item.checkpoint_ref]
        if checkpoint_refs:
            candidate["checkpoint_ref"] = checkpoint_refs[0]
        covered = sorted(
            {node_id for item in items for node_id in item.covered_node_ids if node_id}
        )
        if covered:
            candidate["covered_node_ids"] = covered
        candidates.append(candidate)

    rendered_bytes = _utf8_len(prompt)
    return _PromptProjection(
        rendered_prompt_bytes=rendered_bytes,
        essential_bytes=max(0, rendered_bytes - reducible_bytes),
        selected_evidence_bytes=selected_evidence_bytes,
        candidates=tuple(candidates),
        replacements_by_kind=replacements_by_kind,
    )


def _discover_replacements(prompt: str) -> list[_PromptReplacement]:
    """Discover reducible spans the render layer explicitly marked.

    Discovery never guesses from Markdown headings: an authored or
    untrusted heading string like ``## Selected diagnostics`` is not
    evidence of a genuinely reducible section, only the render-emitted
    marker pair around it is. See ``continuation_budget_spans``.
    """

    replacements: list[_PromptReplacement] = []
    for span in extract_reducible_spans(prompt):
        message = _OMISSION_MESSAGES.get(span.kind)
        if message is None:
            continue
        replacements.append(
            _PromptReplacement(
                kind=span.kind,
                start=span.start,
                end=span.end,
                replacement=f"_{message}_\n",
                checkpoint_ref=span.checkpoint_ref,
                covered_node_ids=span.covered_node_ids,
            )
        )
    return replacements


def _verify_projection(
    decision: Mapping[str, Any],
    projected_prompt: str,
) -> dict[str, Any]:
    """Remeasure actual projected UTF-8 bytes; refuse durably if still oversized.

    Rust selects reductions from declared candidate byte counts computed
    before projection. Applying those reductions can save fewer bytes than
    declared (defensive overlap skipping, for example), so the prompt that
    would actually be sent must be remeasured here -- never trust the
    pre-projection estimate as proof the compacted prompt fits.
    """

    if str(decision.get("kind") or "") != "compact":
        return dict(decision)
    projected_bytes = _utf8_len(projected_prompt)
    target = _intish(
        decision.get("target_prompt_bytes") or decision.get("prompt_budget_bytes")
    )
    updated = dict(decision)
    updated["estimated_prompt_bytes"] = projected_bytes
    if projected_bytes <= target:
        return updated
    updated["kind"] = "refuse"
    updated["reasons"] = [
        *_strings(updated.get("reasons")),
        "post_projection_budget_exceeded",
    ]
    return _normalized_decision(updated)


def _project_prompt(
    prompt: str,
    decision: Mapping[str, Any],
    projection: _PromptProjection,
) -> str:
    if str(decision.get("kind") or "") != "compact":
        return prompt
    selected_kinds = [
        str(item.get("kind"))
        for item in decision.get("reductions", [])
        if isinstance(item, Mapping) and item.get("kind")
    ]
    replacements: list[_PromptReplacement] = []
    for kind in selected_kinds:
        replacements.extend(projection.replacements_by_kind.get(kind, ()))
    if not replacements:
        return prompt
    return _apply_replacements(prompt, replacements)


def _apply_replacements(
    prompt: str,
    replacements: list[_PromptReplacement],
) -> str:
    selected: list[_PromptReplacement] = []
    last_end = 0
    for replacement in sorted(replacements, key=lambda item: (item.start, item.end)):
        if replacement.start < last_end:
            continue
        selected.append(replacement)
        last_end = replacement.end
    parts: list[str] = []
    cursor = 0
    for replacement in selected:
        parts.append(prompt[cursor : replacement.start])
        parts.append(replacement.replacement)
        cursor = replacement.end
    parts.append(prompt[cursor:])
    return "".join(parts)


def _replacement_saved_bytes(
    prompt: str,
    replacement: _PromptReplacement,
) -> int:
    return max(
        0,
        _utf8_len(prompt[replacement.start : replacement.end])
        - _utf8_len(replacement.replacement),
    )


def _utf8_len(text: str) -> int:
    return len(text.encode("utf-8", errors="replace"))


def _persist_decision(
    artifacts_dir: str | None,
    record: Mapping[str, Any],
) -> str | None:
    if not artifacts_dir:
        return None
    root = Path(artifacts_dir)
    try:
        root.mkdir(parents=True, exist_ok=True)
        path = root / CONTINUATION_BUDGET_DECISION_FILENAME
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{CONTINUATION_BUDGET_DECISION_FILENAME}.",
            suffix=".tmp",
            dir=str(root),
            text=True,
        )
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(record, stream, sort_keys=True, indent=2)
            stream.write("\n")
        os.replace(tmp_name, path)
        return str(path)
    except OSError:
        return None


def _persist_projected_prompt(
    artifacts_dir: str | None,
    prompt: str,
    *,
    original_prompt: str,
    decision: Mapping[str, Any],
) -> str | None:
    if not artifacts_dir or prompt == original_prompt:
        return None
    if str(decision.get("kind") or "") != "compact":
        return None
    root = Path(artifacts_dir)
    try:
        root.mkdir(parents=True, exist_ok=True)
        path = root / "continuation_budget_prompt.md"
        path.write_text(prompt, encoding="utf-8")
        return str(path)
    except OSError:
        return None


def _record_child_metadata(
    artifacts_dir: str | None,
    decision: Mapping[str, Any],
    *,
    decision_path: str | None,
    projected_prompt_bytes: int,
    projected_prompt_path: str | None,
) -> None:
    if not artifacts_dir:
        return
    fields: dict[str, Any] = {
        "continuation_budget_kind": decision.get("kind"),
        "continuation_budget_prompt_bytes": decision.get("estimated_prompt_bytes"),
        "continuation_budget_prompt_budget_bytes": decision.get("prompt_budget_bytes"),
        "continuation_budget_target_bytes": decision.get("target_prompt_bytes")
        or decision.get("prompt_budget_bytes"),
    }
    if decision_path:
        fields["continuation_budget_decision_path"] = decision_path
    fields["continuation_budget_projected_prompt_bytes"] = projected_prompt_bytes
    if projected_prompt_path:
        fields["continuation_budget_projected_prompt_path"] = projected_prompt_path
    disposition = decision.get("disposition")
    if isinstance(disposition, str) and disposition:
        fields["continuation_budget_disposition"] = disposition
    try:
        from sase.axe.run_agent_helpers import update_meta_field

        for key, value in fields.items():
            update_meta_field(artifacts_dir, key, value)
    except Exception:
        return


def _record_delivery_refusal(
    env: Mapping[str, str],
    message: str,
    *,
    decision_path: str | None,
) -> None:
    try:
        from sase.monitor.continuation_delivery import (
            DELIVERY_ARTIFACTS_ENV,
            DELIVERY_IDENTITY_ENV,
            DELIVERY_KEY_ENV,
        )
        from sase.monitor.delivery import (
            apply_delivery_transition,
            load_delivery_record,
        )
    except Exception:
        return
    artifacts_dir = env.get(DELIVERY_ARTIFACTS_ENV)
    raw_key = env.get(DELIVERY_KEY_ENV)
    identity = env.get("SASE_AGENT_NAME") or env.get(DELIVERY_IDENTITY_ENV)
    if not artifacts_dir or not raw_key:
        return
    try:
        key_payload = json.loads(raw_key)
    except ValueError:
        return
    if not isinstance(key_payload, Mapping):
        return
    try:
        key = {
            "monitor_id": str(key_payload["monitor_id"]),
            "result_id": str(key_payload["result_id"]),
            "branch": str(key_payload["branch"]),
        }
    except KeyError:
        return
    try:
        record = load_delivery_record(artifacts_dir, key)
        current = str(record.get("disposition") or "") if record else ""
        target = "needs_attention" if current == "acknowledged" else "nonlaunchable"
        reason = f"context_budget_exceeded: {message}"
        if decision_path:
            reason = f"{reason} (decision: {decision_path})"
        apply_delivery_transition(
            artifacts_dir,
            key,
            target,
            selected_action="continue",
            reason=reason,
            reserved_identity=identity,
        )
    except Exception:
        return


def _record_parent_refusal(
    env: Mapping[str, str],
    message: str,
    *,
    decision_path: str | None,
    prompt_path: str | None,
) -> None:
    parent_dir = _parent_artifacts_dir(env)
    if parent_dir is None:
        return
    try:
        meta_path = Path(parent_dir) / "agent_meta.json"
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError):
        return
    if not isinstance(data, dict) or not data.get("monitor_id"):
        return
    try:
        from sase.axe.run_agent_helpers import update_meta_field

        update_meta_field(parent_dir, "monitor_followup_outcome", "not-launchable")
        update_meta_field(parent_dir, "monitor_followup_error", message)
        if decision_path:
            update_meta_field(
                parent_dir,
                "monitor_followup_budget_decision_path",
                decision_path,
            )
        if prompt_path:
            update_meta_field(parent_dir, "monitor_followup_prompt_path", prompt_path)
    except Exception:
        return


def _parent_artifacts_dir(env: Mapping[str, str]) -> str | None:
    try:
        from sase.agent._family_attach_types import FAMILY_ATTACH_ENV
    except Exception:
        return None
    raw = env.get(FAMILY_ATTACH_ENV)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    parent_dir = data.get("parent_artifacts_dir") if isinstance(data, dict) else None
    return parent_dir if isinstance(parent_dir, str) and parent_dir else None


def _prompt_path(artifacts_dir: str | None) -> str | None:
    if not artifacts_dir:
        return None
    path = Path(artifacts_dir) / "agent_prompt.md"
    return str(path) if path.exists() else None


def _refusal_message(decision: Mapping[str, Any]) -> str:
    estimated = _intish(decision.get("estimated_prompt_bytes"))
    target = _intish(
        decision.get("target_prompt_bytes") or decision.get("prompt_budget_bytes")
    )
    reasons = ", ".join(_strings(decision.get("reasons"))) or "context_budget_exceeded"
    guidance = "; ".join(_strings(decision.get("recovery_guidance")))
    if not guidance:
        guidance = (
            "Resume with an adequate checkpoint or choose a route with a larger "
            "context budget; do not rerun the monitored command just to rebuild "
            "context."
        )
    return (
        "Continuation context budget exceeded: final expanded prompt is "
        f"{estimated} bytes, budget target is {target} bytes "
        f"({reasons}). {guidance}"
    )


def _intish(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    try:
        return int(str(value))
    except ValueError:
        return 0


def _strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


__all__ = [
    "CONTINUATION_BUDGET_DECISION_FILENAME",
    "CONTINUATION_BUDGET_ENFORCE_ENV",
    "MONITOR_CONTINUATION_ENV",
    "enforce_continuation_budget",
]
