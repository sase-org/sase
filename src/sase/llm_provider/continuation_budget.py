"""Budget preflight for continuation-backed provider invocations."""

from __future__ import annotations

import json
import os
import tempfile
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.core.continuation_facade import plan_continuation_budget
from sase.core.continuation_wire import CONTINUATION_WIRE_SCHEMA_VERSION
from sase.llm_provider.types import LLMInvocationError, LLMInvocationOptions, ModelTier

MONITOR_CONTINUATION_ENV = "SASE_MONITOR_CONTINUATION"
CONTINUATION_BUDGET_ENFORCE_ENV = "SASE_CONTINUATION_BUDGET_ENFORCE"
CONTINUATION_BUDGET_DECISION_FILENAME = "continuation_budget_decision.json"

_DEFAULT_CONTEXT_LIMIT_BYTES = 800_000
_ENV_TO_CONFIG_KEY = {
    "context_limit_bytes": "SASE_CONTINUATION_CONTEXT_LIMIT_BYTES",
    "transport_limit_bytes": "SASE_CONTINUATION_TRANSPORT_LIMIT_BYTES",
    "checkpoint_threshold_bytes": "SASE_CONTINUATION_CHECKPOINT_THRESHOLD_BYTES",
    "instruction_reserve_bytes": "SASE_CONTINUATION_INSTRUCTION_RESERVE_BYTES",
    "tool_reserve_bytes": "SASE_CONTINUATION_TOOL_RESERVE_BYTES",
    "output_reserve_bytes": "SASE_CONTINUATION_OUTPUT_RESERVE_BYTES",
    "reasoning_reserve_bytes": "SASE_CONTINUATION_REASONING_RESERVE_BYTES",
}


def enforce_continuation_budget(
    prompt: str,
    *,
    artifacts_dir: str | None,
    provider_name: str,
    model_tier: ModelTier,
    model_override: str | None,
    options: LLMInvocationOptions,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any] | None:
    """Record and enforce the Rust-owned continuation budget decision."""

    runtime_env = env or os.environ
    if not _budget_required(runtime_env):
        return None

    request = _budget_request(prompt, runtime_env)
    decision = _normalized_decision(plan_continuation_budget(request))
    record = {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "kind": "continuation_budget_preflight",
        "provider": provider_name,
        "model_tier": model_tier,
        "model": model_override,
        "reasoning_effort": options.reasoning_effort,
        "request": request,
        "decision": decision,
        "recorded_at_epoch": time.time(),
    }
    decision_path = _persist_decision(artifacts_dir, record)
    _record_child_metadata(
        artifacts_dir,
        decision,
        decision_path=decision_path,
    )

    if str(decision.get("kind") or "") != "refuse":
        return decision

    message = _refusal_message(decision)
    _record_parent_refusal(
        runtime_env,
        message,
        decision_path=decision_path,
        prompt_path=_prompt_path(artifacts_dir),
    )
    raise LLMInvocationError(message)


def _budget_required(env: Mapping[str, str]) -> bool:
    return (
        env.get(MONITOR_CONTINUATION_ENV) == "1"
        or env.get(CONTINUATION_BUDGET_ENFORCE_ENV) == "1"
    )


def _budget_request(prompt: str, env: Mapping[str, str]) -> dict[str, Any]:
    from sase.llm_provider.config import get_llm_provider_config

    raw_config = get_llm_provider_config()
    budget_config = raw_config.get("continuation_budget") if raw_config else None
    config = budget_config if isinstance(budget_config, Mapping) else {}
    prompt_bytes = len(prompt.encode("utf-8", errors="replace"))
    provider_budget: dict[str, Any] = {
        "context_limit_bytes": _int_setting(
            "context_limit_bytes",
            env,
            config,
            default=_DEFAULT_CONTEXT_LIMIT_BYTES,
        ),
        "transport_limit_bytes": _int_setting(
            "transport_limit_bytes",
            env,
            config,
        ),
        "instruction_reserve_bytes": _int_setting(
            "instruction_reserve_bytes",
            env,
            config,
            default=0,
        )
        or 0,
        "tool_reserve_bytes": _int_setting(
            "tool_reserve_bytes",
            env,
            config,
            default=0,
        )
        or 0,
        "output_reserve_bytes": _int_setting(
            "output_reserve_bytes",
            env,
            config,
            default=0,
        )
        or 0,
        "reasoning_reserve_bytes": _int_setting(
            "reasoning_reserve_bytes",
            env,
            config,
            default=0,
        )
        or 0,
        "estimate_uncertain": True,
    }
    request: dict[str, Any] = {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "rendered_prompt_bytes": prompt_bytes,
        "essential_bytes": prompt_bytes,
        "selected_evidence_bytes": 0,
        "provider_budget": provider_budget,
        "reduction_candidates": [],
    }
    threshold = _int_setting("checkpoint_threshold_bytes", env, config)
    if threshold is not None:
        request["checkpoint_threshold_bytes"] = threshold
    return request


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
    config: Mapping[str, object],
    *,
    default: int | None = None,
) -> int | None:
    raw = env.get(_ENV_TO_CONFIG_KEY[key])
    if raw is None:
        raw = config.get(key)
    if raw is None:
        return default
    if isinstance(raw, bool):
        return default
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


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


def _record_child_metadata(
    artifacts_dir: str | None,
    decision: Mapping[str, Any],
    *,
    decision_path: str | None,
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
    disposition = decision.get("disposition")
    if isinstance(disposition, str) and disposition:
        fields["continuation_budget_disposition"] = disposition
    try:
        from sase.axe.run_agent_helpers import update_meta_field

        for key, value in fields.items():
            update_meta_field(artifacts_dir, key, value)
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
