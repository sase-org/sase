"""Keep-work action validation and effective-target resolution."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase.agent.hijack.core import (
    hijack_recovery_effective_target,
    hijack_recovery_execution_wire_schema_version,
)
from sase.agent.hijack.recover_common import (
    KEEP_WORK_ACTIONS,
    RecoveryRefusal,
    RecoveryTarget,
    clean_string,
    predecessor_concrete_target,
)


def require_concrete_target(value: object, *, source: str) -> str:
    """Validate *value* as a concrete ``provider/model[@effort]`` target."""
    from sase.macro.effort import EFFORT_LEVELS

    text = clean_string(value)
    if not text:
        raise RecoveryRefusal(
            "invalid_model_target",
            f"Recovery target must be a concrete provider/model ({source})",
        )
    base, separator, raw_effort = text.rpartition("@")
    effort: str | None = None
    if separator and raw_effort in EFFORT_LEVELS:
        base, effort = base, raw_effort
    provider, slash, model = base.partition("/")
    if not slash or not provider or not model:
        raise RecoveryRefusal(
            "invalid_model_target",
            f"Recovery target must be a concrete provider/model, got "
            f"{text!r} ({source})",
        )
    if provider.startswith("@") or model.startswith("@"):
        raise RecoveryRefusal(
            "invalid_model_target",
            f"Recovery target must be a concrete provider/model, got "
            f"{text!r} ({source})",
        )
    target = f"{provider}/{model}"
    if effort:
        target += f"@{effort}"
    return target


def conflicting_launch_directives(prompt_text: str) -> list[str]:
    """Return active launch/fan-out directives that conflict with recovery.

    The reserved successor identity, held workspace, and pinned model own
    this launch: an edited Instruct prompt must not carry its own ``%id``
    identity, clan/tab/tribe placement, waits, queue budgets, or typed
    launch/fan-out branches. ``%model``/``%effort`` are the intentional
    Instruct selection and are never conflicts. Fenced code, inline
    literals, and disabled regions are inert, matching the shared
    directive contract.
    """
    from sase.macro.directives import (
        extract_prompt_directives,
        has_alt_directive,
        has_typed_launch_directive,
    )

    conflicts: list[str] = []
    try:
        _, directives = extract_prompt_directives(prompt_text)
    except Exception as exc:
        raise RecoveryRefusal(
            "invalid_prompt",
            f"Instruct prompt directives do not parse: {exc}",
        ) from exc
    if getattr(directives, "name", None):
        conflicts.append("%id identity")
    if getattr(directives, "clan", None) or getattr(directives, "clan_declared", False):
        conflicts.append("%clan placement")
    tribe = getattr(directives, "tribe", None)
    if tribe:
        conflicts.append("%tribe placement")
    wait_fields = (
        "wait",
        "wait_units",
        "wait_procs",
        "wait_beads",
        "wait_hoods",
        "wait_duration",
        "wait_until",
    )
    if any(getattr(directives, name, None) for name in wait_fields):
        conflicts.append("%wait dependency")
    queue_fields = (
        "queue_capacity",
        "queue_capacity_multiplier",
        "wait_priority",
    )
    if any(getattr(directives, name, None) is not None for name in queue_fields):
        conflicts.append("%queue budget")
    try:
        if has_typed_launch_directive(prompt_text):
            conflicts.append("typed launch branch")
    except Exception:
        if (
            getattr(directives, "if_code", None) is not None
            or getattr(directives, "proc_code", None) is not None
        ):
            conflicts.append("typed launch branch")
    try:
        if has_alt_directive(prompt_text):
            conflicts.append("fan-out branch")
    except Exception:
        pass
    return conflicts


def extract_prompt_model(prompt_text: str) -> str | None:
    """Return the first ``%model`` value in *prompt_text*, if any."""
    from sase.macro.directives import extract_prompt_directives

    try:
        _, directives = extract_prompt_directives(prompt_text)
    except Exception as exc:
        raise RecoveryRefusal(
            "invalid_prompt",
            f"Instruct prompt directives do not parse: {exc}",
        ) from exc
    model = getattr(directives, "model", None)
    model_alias = getattr(directives, "model_alias", None)
    effort = getattr(directives, "reasoning_effort", None)
    if isinstance(model_alias, str) and model_alias.strip():
        # The shared parser has already resolved the spelling into its alias
        # field. Keep it explicitly unresolved for Rust policy, which refuses
        # rotating aliases at recovery time.
        return f"@{model_alias.strip()}"
    if not isinstance(model, str) or not model.strip():
        return None
    text = model.strip()
    if effort and isinstance(effort, str) and effort:
        _, at, existing = text.rpartition("@")
        if not at:
            text = f"{text}@{effort}"
        elif not existing:
            text = f"{text}{effort}"
    return text


def resolve_effective_target(
    *,
    action: str,
    record: Mapping[str, Any],
    preview_action: Mapping[str, Any] | None,
    model_override: str | None = None,
    prompt_text: str | None = None,
) -> RecoveryTarget:
    """Resolve a concrete target through the Rust-owned shared policy.

    Continue with an explicit model or edited prompt adapts internally to
    Instruct. Escalate may also carry an explicit concrete model override;
    Rust validates it through the same target policy, while the ledger keeps
    the requested action as ``escalate``. Edited targets are written into the
    prompt so launch uses the exact provider, model, and effort selected here.
    """
    normalized = clean_string(action) or ""
    if normalized not in KEEP_WORK_ACTIONS:
        raise RecoveryRefusal(
            "unsupported_action",
            f"Recovery action must be one of {', '.join(KEEP_WORK_ACTIONS)}, "
            f"got {action!r}",
        )
    edited = prompt_text if isinstance(prompt_text, str) else None
    explicit_model = clean_string(model_override)
    customized_continue = normalized == "continue" and (
        explicit_model is not None or edited is not None
    )
    customized_escalate = normalized == "escalate" and explicit_model is not None
    customized = normalized == "instruct" or customized_continue or customized_escalate
    available = bool((preview_action or {}).get("available", False))
    if not available and not customized:
        reason = clean_string((preview_action or {}).get("reason"))
        raise RecoveryRefusal(
            "action_unavailable",
            f"Recovery action {normalized!r} is unavailable"
            + (f": {reason}" if reason else ""),
        )
    stalled = predecessor_concrete_target(record)
    if stalled is None:
        raise RecoveryRefusal(
            "unknown_model",
            "The predecessor's concrete model is unknown",
        )

    if normalized == "instruct" and (edited is None or not edited.strip()):
        raise RecoveryRefusal(
            "missing_prompt",
            "Instruct requires the full edited replacement prompt",
        )
    if normalized == "continue" and edited is not None and not edited.strip():
        raise RecoveryRefusal("missing_prompt", "The replacement prompt is empty")
    if normalized == "escalate" and edited is not None:
        raise RecoveryRefusal(
            "incompatible_options",
            "Escalate takes no replacement prompt",
        )

    internal_action = (
        "instruct"
        if normalized == "instruct" or customized_continue or customized_escalate
        else normalized
    )
    prompt_model: str | None = None
    if edited is not None:
        conflicts = conflicting_launch_directives(edited)
        if conflicts:
            raise RecoveryRefusal(
                "conflicting_directives",
                "Instruct prompt carries launch directives owned by recovery: "
                + ", ".join(conflicts),
            )
        prompt_model = extract_prompt_model(edited)

    request = {
        "schema_version": hijack_recovery_execution_wire_schema_version(),
        "action": internal_action,
        "stalled_concrete": stalled,
        "continue_target": clean_string((preview_action or {}).get("target")),
        "escalate_target": clean_string((preview_action or {}).get("target")),
        "explicit_model_override": explicit_model,
        "prompt_model": prompt_model,
        "predecessor_provider": clean_string(record.get("provider")),
    }
    try:
        result = hijack_recovery_effective_target(request)
    except (TypeError, ValueError) as exc:
        message = str(exc)
        raise RecoveryRefusal(_target_error_code(message), message) from exc

    target_value = clean_string(result.get("concrete_target"))
    if not target_value:
        raise RecoveryRefusal(
            "invalid_model_target", "Rust recovery policy returned no concrete target"
        )
    is_instruct = internal_action == "instruct"
    prepared_prompt = ""
    if edited is not None:
        from sase.macro.directive_edit import set_prompt_model

        try:
            prepared_prompt = set_prompt_model(edited, target_value)
        except Exception as exc:
            raise RecoveryRefusal(
                "invalid_prompt", f"Could not pin the Instruct prompt model: {exc}"
            ) from exc
    return RecoveryTarget(
        action="instruct" if is_instruct and normalized != "escalate" else normalized,
        concrete_target=target_value,
        model_changed=bool(result.get("model_changed")),
        prompt=prepared_prompt,
        context_mode="instruct" if is_instruct and edited is not None else "",
    )


def _target_error_code(message: str) -> str:
    text = message.lower()
    if "incompatible options" in text:
        return "incompatible_options"
    if "unavailable" in text:
        return "action_unavailable"
    if "unknown" in text:
        return "unknown_model"
    if "unsupported action" in text:
        return "unsupported_action"
    return "invalid_model_target"
