"""Typed read model and cached loader for question-gate rounds.

Each round's bundle (``<bundle_path>/request.json`` etc.) is read through
the mtime/size JSON cache and projected by the Rust ``question_round``
core module through :mod:`sase.core.question_round_facade`. Everything
here is tolerant: :func:`parse_question_round_wire` coerces malformed
fields to defaults, and :func:`load_question_round` never raises,
returning a ``data_state="unavailable"`` view when the binding or the
parse fails. The loader holds no shared mutable state, so the lane
worker may call it from any thread.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sase.agent.artifact_files_cache import get_global_cache
from sase.core import question_round_facade


@dataclass(frozen=True)
class QuestionOptionView:
    label: str
    description: str | None = None


@dataclass(frozen=True)
class QuestionAnswerView:
    selected: tuple[str, ...] = ()
    custom_feedback: str | None = None


@dataclass(frozen=True)
class QuestionEntryView:
    index: int = 0
    header: str | None = None
    question: str = ""
    options: tuple[QuestionOptionView, ...] = ()
    multi_select: bool = False
    recommended_index: int | None = None
    recommendation_basis: str = "none"
    answer: QuestionAnswerView | None = None
    recommendation_match: str | None = None


@dataclass(frozen=True)
class QuestionPolicyView:
    profile: str | None = None
    rule: str | None = None
    value: str | None = None
    source: str | None = None


@dataclass(frozen=True)
class QuestionProvenanceView:
    channel: str | None = None
    actor: str = "unknown"
    policy: QuestionPolicyView | None = None
    responded_at_unix: float | None = None


@dataclass(frozen=True)
class QuestionCancellationView:
    reason: str | None = None
    source: str | None = None
    cancelled_at_unix: float | None = None


@dataclass(frozen=True)
class QuestionRoundView:
    gate_id: str = ""
    status: str = "unknown"
    data_state: str = "unavailable"
    schema_version: int = question_round_facade.QUESTION_ROUND_WIRE_SCHEMA_VERSION
    round_index: int | None = None
    asked_by: str | None = None
    asked_at_unix: float | None = None
    gate_state: str | None = None
    entries: tuple[QuestionEntryView, ...] = ()
    global_note: str | None = None
    provenance: QuestionProvenanceView | None = None
    cancellation: QuestionCancellationView | None = None


@dataclass(frozen=True)
class NumberedQuestionRound:
    """One in-scope round with its session-wide presentation numbering.

    ``first_number`` is the 1-based Q number of the round's first
    question; later questions follow continuously. ``member_label`` is the
    gate member suffix (``gate``, ``gate-0``, ...) and ``deadline_unix``
    the round's answer deadline, when known. Both the Rich presenter and
    the questions summary lane consume this type.
    """

    view: QuestionRoundView
    first_number: int = 1
    member_label: str = "gate"
    deadline_unix: float | None = None


def _as_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _as_opt_str(value: Any) -> str | None:
    if value is None:
        return None
    return value if isinstance(value, str) else None


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _as_bool(value: Any, default: bool = False) -> bool:
    return value if isinstance(value, bool) else default


def _parse_option(value: Any) -> QuestionOptionView | None:
    if not isinstance(value, Mapping):
        return None
    label = _as_str(value.get("label"))
    if label is None:
        return None
    return QuestionOptionView(
        label=label, description=_as_opt_str(value.get("description"))
    )


def _parse_answer(value: Any) -> QuestionAnswerView | None:
    if not isinstance(value, Mapping):
        return None
    raw_selected = value.get("selected")
    selected = (
        tuple(item for item in raw_selected if isinstance(item, str))
        if isinstance(raw_selected, list)
        else ()
    )
    return QuestionAnswerView(
        selected=selected,
        custom_feedback=_as_opt_str(value.get("custom_feedback")),
    )


def _parse_entry(value: Any) -> QuestionEntryView:
    if not isinstance(value, Mapping):
        return QuestionEntryView()
    raw_options = value.get("options")
    options = (
        tuple(
            option
            for item in raw_options
            if (option := _parse_option(item)) is not None
        )
        if isinstance(raw_options, list)
        else ()
    )
    raw_answer = value.get("answer")
    return QuestionEntryView(
        index=_as_int(value.get("index")) or 0,
        header=_as_opt_str(value.get("header")),
        question=_as_str(value.get("question")) or "",
        options=options,
        multi_select=_as_bool(value.get("multi_select")),
        recommended_index=_as_int(value.get("recommended_index")),
        recommendation_basis=_as_str(value.get("recommendation_basis")) or "none",
        answer=_parse_answer(raw_answer) if raw_answer is not None else None,
        recommendation_match=_as_opt_str(value.get("recommendation_match")),
    )


def _parse_policy(value: Any) -> QuestionPolicyView | None:
    if not isinstance(value, Mapping):
        return None
    return QuestionPolicyView(
        profile=_as_opt_str(value.get("profile")),
        rule=_as_opt_str(value.get("rule")),
        value=_as_opt_str(value.get("value")),
        source=_as_opt_str(value.get("source")),
    )


def _parse_provenance(value: Any) -> QuestionProvenanceView | None:
    if not isinstance(value, Mapping):
        return None
    raw_policy = value.get("policy")
    return QuestionProvenanceView(
        channel=_as_opt_str(value.get("channel")),
        actor=_as_str(value.get("actor")) or "unknown",
        policy=_parse_policy(raw_policy) if raw_policy is not None else None,
        responded_at_unix=_as_float(value.get("responded_at_unix")),
    )


def _parse_cancellation(value: Any) -> QuestionCancellationView | None:
    if not isinstance(value, Mapping):
        return None
    return QuestionCancellationView(
        reason=_as_opt_str(value.get("reason")),
        source=_as_opt_str(value.get("source")),
        cancelled_at_unix=_as_float(value.get("cancelled_at_unix")),
    )


def parse_question_round_wire(data: Mapping[str, Any]) -> QuestionRoundView:
    """Coerce a ``QuestionRoundWire``-shape mapping into a typed view.

    Every field is tolerant: wrong-typed values fall back to defaults and
    unknown fields are ignored. Never raises for mapping input.
    """
    if not isinstance(data, Mapping):
        return QuestionRoundView()
    raw_entries = data.get("entries")
    entries = (
        tuple(_parse_entry(item) for item in raw_entries)
        if isinstance(raw_entries, list)
        else ()
    )
    raw_provenance = data.get("provenance")
    raw_cancellation = data.get("cancellation")
    return QuestionRoundView(
        gate_id=_as_str(data.get("gate_id")) or "",
        status=_as_str(data.get("status")) or "unknown",
        data_state=_as_str(data.get("data_state")) or "unavailable",
        schema_version=_as_int(data.get("schema_version"))
        or question_round_facade.QUESTION_ROUND_WIRE_SCHEMA_VERSION,
        round_index=_as_int(data.get("round_index")),
        asked_by=_as_opt_str(data.get("asked_by")),
        asked_at_unix=_as_float(data.get("asked_at_unix")),
        gate_state=_as_opt_str(data.get("gate_state")),
        entries=entries,
        global_note=_as_opt_str(data.get("global_note")),
        provenance=_parse_provenance(raw_provenance)
        if raw_provenance is not None
        else None,
        cancellation=_parse_cancellation(raw_cancellation)
        if raw_cancellation is not None
        else None,
    )


def _unavailable_view(
    *,
    gate_id: str,
    gate_state: str | None,
    asked_by: str | None,
    asked_at_unix: float | None,
    round_index: int | None,
) -> QuestionRoundView:
    return QuestionRoundView(
        gate_id=gate_id,
        status="unknown",
        data_state="unavailable",
        round_index=round_index,
        asked_by=asked_by,
        asked_at_unix=asked_at_unix,
        gate_state=gate_state,
    )


def load_question_round(
    *,
    gate_id: str,
    gate_state: str | None,
    bundle_path: str,
    asked_by: str | None,
    asked_at_unix: float | None,
    round_index: int | None = None,
) -> QuestionRoundView:
    """Load and project one question round from its bundle directory.

    Reads ``request.json``, ``response.json``, and ``cancellation.json``
    through the shared mtime/size cache, then projects them through the
    Rust binding. Any binding or parse failure returns a
    ``data_state="unavailable"`` view; this function never raises, so the
    lane worker can call it for every session row without guarding.
    """
    try:
        cache = get_global_cache()
        wire_request: dict[str, Any] = {
            "schema_version": (
                question_round_facade.QUESTION_ROUND_WIRE_SCHEMA_VERSION
            ),
            "gate": {
                "gate_id": gate_id,
                "gate_state": gate_state,
                "asked_by": asked_by,
                "asked_at_unix": asked_at_unix,
                "round_index": round_index,
            },
        }
        for name in ("request", "response", "cancellation"):
            document = cache.read_json(os.path.join(bundle_path, f"{name}.json"))
            if document is not None:
                wire_request[name] = document
        return parse_question_round_wire(
            question_round_facade.project_question_round(wire_request)
        )
    except Exception:
        return _unavailable_view(
            gate_id=gate_id,
            gate_state=gate_state,
            asked_by=asked_by,
            asked_at_unix=asked_at_unix,
            round_index=round_index,
        )


__all__ = [
    "NumberedQuestionRound",
    "QuestionAnswerView",
    "QuestionCancellationView",
    "QuestionEntryView",
    "QuestionOptionView",
    "QuestionPolicyView",
    "QuestionProvenanceView",
    "QuestionRoundView",
    "load_question_round",
    "parse_question_round_wire",
]
