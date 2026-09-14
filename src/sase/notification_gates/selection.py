"""Pure selection and feedback validation shared by acceptance and execution.

Both the fast decision-acceptance path (:mod:`sase.notification_gates.decision`)
and the option-execution path (:mod:`sase.notification_gates.executor`) must
resolve the same options, selection, and feedback rules from one envelope --
independently, under their own separate locks, so a fast acceptance never
waits behind slow execution. Keeping this logic in one dependency-free module
means both callers validate identically without importing each other.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sase.notification_gates.models import GateError, GateFeedbackMode, GateOption


def options_from_envelope(envelope: Mapping[str, Any]) -> tuple[GateOption, ...]:
    from sase.notification_gates.registry import adapter_for_kind

    raw_options = envelope.get("options")
    assert isinstance(raw_options, list)
    kind = envelope.get("kind")
    assert isinstance(kind, str)
    default_feedback = adapter_for_kind(kind).default_feedback
    return tuple(
        GateOption.from_mapping(
            raw_option,
            index,
            default_feedback=default_feedback,
        )
        for index, raw_option in enumerate(raw_options)
    )


def resolve_selection(
    envelope: Mapping[str, Any],
    options: tuple[GateOption, ...],
    selected_option_ids: Sequence[str],
) -> tuple[GateOption, ...]:
    if (
        not isinstance(selected_option_ids, Sequence)
        or isinstance(selected_option_ids, (str, bytes))
        or not all(isinstance(option_id, str) for option_id in selected_option_ids)
    ):
        raise GateError(
            "invalid_selection",
            "selected_option_ids",
            "selected_option_ids must be an array of strings",
        )
    requested = tuple(selected_option_ids)
    if not requested:
        raise GateError(
            "empty_selection",
            "selected_option_ids",
            "at least one option must be selected",
        )
    if len(set(requested)) != len(requested):
        raise GateError(
            "duplicate_option",
            "selected_option_ids",
            "selected option ids must be unique",
        )
    by_id = {option.id: option for option in options}
    unknown = sorted(set(requested) - set(by_id))
    if unknown:
        raise GateError(
            "unknown_option",
            "selected_option_ids",
            f"option is not present in the request: {', '.join(unknown)}",
        )
    raw_branches = envelope.get("branches")
    assert isinstance(raw_branches, list)
    selected_set = set(requested)
    matching = [
        tuple(str(option_id) for option_id in branch)
        for branch in raw_branches
        if isinstance(branch, list) and selected_set <= set(branch)
    ]
    if len(matching) != 1:
        raise GateError(
            "selection_crosses_branches",
            "selected_option_ids",
            "selected options must be a non-empty subset of exactly one branch",
        )
    branch = matching[0]
    return tuple(by_id[option_id] for option_id in branch if option_id in selected_set)


def normalize_feedback(
    selected: tuple[GateOption, ...], feedback: str | None
) -> str | None:
    if feedback is not None and not isinstance(feedback, str):
        raise GateError(
            "invalid_feedback", "feedback", "feedback must be a string or null"
        )
    ranks: dict[GateFeedbackMode, int] = {
        "disabled": 0,
        "optional": 1,
        "required": 2,
    }
    effective = max((option.feedback for option in selected), key=ranks.__getitem__)
    selected_text = ", ".join(option.id for option in selected)
    if effective == "disabled":
        if feedback is not None:
            raise GateError(
                "feedback_not_allowed",
                "feedback",
                f"selected option(s) do not accept feedback: {selected_text}",
            )
        return None
    normalized = feedback.strip() if isinstance(feedback, str) else None
    normalized = normalized or None
    if effective == "required" and normalized is None:
        raise GateError(
            "feedback_required",
            "feedback",
            f"selected option(s) require feedback: {selected_text}",
        )
    return normalized


__all__ = ["normalize_feedback", "options_from_envelope", "resolve_selection"]
