"""Keep-work action validation and effective-target resolution."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

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
    effort = getattr(directives, "reasoning_effort", None)
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
    """Validate *action* and pin its effective concrete target and prompt.

    Escalate uses the freshly previewed target; Continue pins the
    predecessor's concrete provider/model/effort. Instruct requires the full
    edited replacement prompt: an explicit model override wins, otherwise an
    edited ``%model`` overrides Continue's default. Conflicting
    launch/fan-out directives refuse. The effective target, including
    effort, decides ``model_changed`` (``ESCALATED`` versus ``CONTINUED``).
    """
    normalized = clean_string(action) or ""
    if normalized not in KEEP_WORK_ACTIONS:
        raise RecoveryRefusal(
            "unsupported_action",
            f"Recovery action must be one of {', '.join(KEEP_WORK_ACTIONS)}, "
            f"got {action!r}",
        )
    available = bool((preview_action or {}).get("available", False))
    if not available:
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
    stalled = require_concrete_target(stalled, source="predecessor record")
    if normalized == "continue":
        if model_override is not None or prompt_text is not None:
            raise RecoveryRefusal(
                "incompatible_options",
                "Continue takes no model override or replacement prompt",
            )
        target = clean_string((preview_action or {}).get("target")) or stalled
        target = require_concrete_target(target, source="continue preview")
        return RecoveryTarget(
            action=normalized,
            concrete_target=target,
            model_changed=target != stalled,
            prompt="",
            context_mode="",
        )
    if normalized == "escalate":
        if model_override is not None or prompt_text is not None:
            raise RecoveryRefusal(
                "incompatible_options",
                "Escalate takes no model override or replacement prompt",
            )
        pinned = clean_string((preview_action or {}).get("target"))
        if not pinned:
            raise RecoveryRefusal(
                "action_unavailable",
                "Escalate has no pinned target",
            )
        target = require_concrete_target(pinned, source="escalate preview")
        return RecoveryTarget(
            action=normalized,
            concrete_target=target,
            model_changed=target != stalled,
            prompt="",
            context_mode="",
        )
    # Instruct: the edited replacement prompt is the continuation prompt.
    edited = prompt_text if isinstance(prompt_text, str) else ""
    if not edited.strip():
        raise RecoveryRefusal(
            "missing_prompt",
            "Instruct requires the full edited replacement prompt",
        )
    conflicts = conflicting_launch_directives(edited)
    if conflicts:
        raise RecoveryRefusal(
            "conflicting_directives",
            "Instruct prompt carries launch directives owned by recovery: "
            + ", ".join(conflicts),
        )
    if model_override is not None:
        override = require_concrete_target(
            model_override, source="explicit model override"
        )
        from sase.macro.directive_edit import set_prompt_model

        try:
            rewritten = set_prompt_model(edited, override)
        except Exception as exc:
            raise RecoveryRefusal(
                "invalid_prompt",
                f"Could not apply the explicit model override: {exc}",
            ) from exc
        return RecoveryTarget(
            action=normalized,
            concrete_target=override,
            model_changed=override != stalled,
            prompt=rewritten,
            context_mode="instruct",
        )
    edited_model = extract_prompt_model(edited)
    if edited_model is not None:
        normalized_model = _normalize_prompt_model(
            edited_model, predecessor_provider=clean_string(record.get("provider"))
        )
        target = require_concrete_target(
            normalized_model, source="instruct prompt %model"
        )
        return RecoveryTarget(
            action=normalized,
            concrete_target=target,
            model_changed=target != stalled,
            prompt=edited,
            context_mode="instruct",
        )
    return RecoveryTarget(
        action=normalized,
        concrete_target=stalled,
        model_changed=False,
        prompt=edited,
        context_mode="instruct",
    )


def _normalize_prompt_model(value: str, *, predecessor_provider: str | None) -> str:
    """Normalize an Instruct ``%model`` value toward concrete form.

    A bare ``model[@effort]`` inherits the predecessor's provider, mirroring
    how the stalled target is pinned. Pool aliases (``@alias``) stay
    unresolved and refuse downstream as non-concrete.
    """
    text = value.strip()
    if "/" in text or not predecessor_provider:
        return text
    return f"{predecessor_provider}/{text}"
