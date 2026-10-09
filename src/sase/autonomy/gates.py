"""Gate-side adapter over the core autonomy record (``%auto`` E1 ``gates`` phase).

Every automatic gate outcome comes from one core ``evaluate()`` applied to
the creator's record snapshot. Python never re-implements the schema, the
profiles, or the decision algorithm: every function below delegates to
``sase_core_rs`` and only handles capability tables, meta-dict plumbing,
the durable policy block, the host decision log, and the agent awareness
block.
"""

from __future__ import annotations

import datetime
import warnings
from collections.abc import Mapping
from pathlib import Path
from typing import Any

#: Decision values each auto-allowable gate kind can execute. Every other
#: kind declares no capabilities, so core answers ``ask`` for it
#: (``not_auto_allowable`` / ``unknown_kind``) and it always waits.
GATE_AUTO_CAPABILITIES: dict[str, frozenset[str]] = {
    "plan": frozenset({"approve_archive"}),
    "epic_plan": frozenset({"approve"}),
    "question": frozenset({"first"}),
}

#: Gate kinds whose creation response carries a policy block. Privileged
#: kinds (launch, sudo, custom, triage, ...) never auto-resolve, so they
#: carry no block.
POLICY_BLOCK_KINDS = frozenset({"plan", "epic_plan", "question"})

#: Marker identifying an appended awareness block, used to keep it to one
#: copy per turn even if the hook ever runs twice on one prompt.
AWARENESS_MARKER = "SASE autonomy:"


def capabilities_for_kind(kind: str) -> frozenset[str]:
    """Return the executable decision values for a gate *kind*."""
    return GATE_AUTO_CAPABILITIES.get(kind, frozenset())


def record_for_auto_block(auto: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Return the record snapshot a gate creation evaluates.

    The attached ``policy`` snapshot wins; otherwise a legacy hand-built
    ``{enabled, argument}`` block translates through core
    (``enabled`` with no argument is bare ``%auto``). A disabled block
    with no snapshot gives ``None`` (Manual). Unknown spellings raise
    ``ValueError`` with the classifier's ``invalid-auto`` message, which
    the service reports as ``invalid_auto_argument``.
    """
    if auto is None:
        return None
    try:
        policy = auto.get("policy")
    except AttributeError:
        return None
    if isinstance(policy, dict) and policy:
        return dict(policy)
    try:
        enabled = bool(auto.get("enabled", False))
    except AttributeError:
        return None
    if not enabled:
        return None
    from sase.autonomy.record import resolve_selection

    argument = auto.get("argument")
    return resolve_selection(
        argument if argument is not None else "",
        source="prompt",
        surface="gate",
    )


def evaluate_gate(
    record: Mapping[str, Any] | None,
    *,
    gate_kind: str,
    option_ids: list[str],
) -> dict[str, Any]:
    """Evaluate one gate request against *record* through core.

    A ``None`` record is Manual and always asks.
    """
    from sase.autonomy.record import evaluate

    return evaluate(
        record,
        gate_kind,
        option_ids,
        sorted(capabilities_for_kind(gate_kind)),
    )


def policy_block_for_decision(decision: Mapping[str, Any]) -> dict[str, Any]:
    """Return the durable policy block for a core decision dict.

    A ``manual``-profile decision is recorded with rule ``manual``: the
    gate asks because its agent carries no automatic policy, not because
    of one policy row.
    """
    block = {
        "profile": decision.get("profile"),
        "selection": decision.get("selection"),
        "rule": decision.get("rule"),
        "outcome": decision.get("outcome"),
        "value": decision.get("value"),
        "option_ids": list(decision.get("option_ids") or []),
        "source": decision.get("source"),
        "revision": decision.get("revision"),
        "digest": decision.get("digest"),
    }
    if block["profile"] == "manual":
        block["rule"] = "manual"
    return block


def _creator_role_for_meta(meta: Mapping[str, Any] | None) -> str:
    """Return the decision-log creator role for a creator agent *meta*."""
    if not isinstance(meta, Mapping):
        return "top_level"
    try:
        if meta.get("epic_bead_id") or meta.get("phase_bead_id"):
            return "epic_worker"
        if meta.get("workflow_name"):
            return "workflow"
    except Exception:
        return "top_level"
    return "top_level"


def creator_meta_for_producer(producer: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return the creator's live agent meta for a gate *producer* mapping."""
    if not isinstance(producer, Mapping):
        return {}
    artifacts_dir = producer.get("artifacts_dir")
    if not artifacts_dir:
        return {}
    try:
        from sase.axe.agent_meta import read_live_agent_meta

        meta = read_live_agent_meta(artifacts_dir)
    except Exception:
        return {}
    return dict(meta) if isinstance(meta, dict) else {}


def _utc_now() -> str:
    return (
        datetime.datetime.now(datetime.UTC)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def append_decision_log(
    *,
    decision: Mapping[str, Any],
    gate_kind: str,
    gate_id: str,
    creator_meta: Mapping[str, Any] | None,
) -> None:
    """Append one decision-log row for a non-manual evaluation.

    Manual evaluations are never logged. Failures warn and never block
    gate creation.
    """
    try:
        if decision.get("profile") == "manual":
            return
        from sase.core.paths import sase_home
        from sase.core.rust import require_rust_binding

        meta = creator_meta if isinstance(creator_meta, Mapping) else {}
        try:
            agent = meta.get("name") or ""
            session = meta.get("agent_session") or ""
            project = meta.get("project_name") or meta.get("project") or ""
        except Exception:
            agent, session, project = "", "", ""
        entry = {
            "schema_version": 1,
            "at": _utc_now(),
            "agent": agent if isinstance(agent, str) else "",
            "agent_session": session if isinstance(session, str) else "",
            "project": project if isinstance(project, str) else "",
            "gate_kind": gate_kind,
            "gate_id": gate_id,
            "creator_role": _creator_role_for_meta(meta),
            "decision": dict(decision),
        }
        append = require_rust_binding("autonomy_append_decision")
        append(str(sase_home()), entry)
    except Exception as exc:
        warnings.warn(f"autonomy decision log append failed: {exc}", stacklevel=2)


def _awareness_block_for_record(record: Mapping[str, Any] | None) -> str | None:
    """Return the advisory awareness block for *record*, if it has one.

    The text comes only from core; manual records (and missing bindings)
    give ``None``, so manual agents get no block.
    """
    if not isinstance(record, dict) or not record:
        return None
    try:
        from sase.core.rust import require_rust_binding

        text = require_rust_binding("autonomy_awareness_text")(dict(record))
    except Exception:
        return None
    return text if isinstance(text, str) and text else None


def _awareness_block_for_artifacts_dir(
    artifacts_dir: str | Path | None,
) -> str | None:
    """Return the awareness block for the live record under *artifacts_dir*."""
    if not artifacts_dir:
        return None
    try:
        from sase.autonomy.record import live_record

        return _awareness_block_for_record(live_record(artifacts_dir))
    except Exception:
        return None


def with_awareness_block(prompt: str, artifacts_dir: str | Path | None) -> str:
    """Append the live awareness block to *prompt* exactly once.

    Prompts that already carry a block are returned unchanged, so the
    block never accumulates across successors or retries.
    """
    if AWARENESS_MARKER in prompt:
        return prompt
    block = _awareness_block_for_artifacts_dir(artifacts_dir)
    if not block:
        return prompt
    return f"{prompt}\n\n{block}"


__all__ = [
    "AWARENESS_MARKER",
    "GATE_AUTO_CAPABILITIES",
    "POLICY_BLOCK_KINDS",
    "append_decision_log",
    "capabilities_for_kind",
    "creator_meta_for_producer",
    "evaluate_gate",
    "policy_block_for_decision",
    "record_for_auto_block",
    "with_awareness_block",
]
