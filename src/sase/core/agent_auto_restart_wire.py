"""Wire records for the Rust-backed update-skew auto-restart domain.

Mirrors ``sase_core::agent_auto_restart::wire``. Every object carries
``schema_version``; :func:`agent_auto_restart_wire_schema_version` must
match ``AGENT_AUTO_RESTART_WIRE_SCHEMA_VERSION`` in core.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

AGENT_AUTO_RESTART_WIRE_SCHEMA_VERSION = 1

LEDGER_CLAIMED = "claimed"
LEDGER_DEFERRED = "deferred"
LEDGER_DECLINED = "declined"
LEDGER_LAUNCHING = "launching"
LEDGER_LAUNCHED = "launched"
LEDGER_SETTLED_OK = "settled_ok"
LEDGER_SETTLED_FAILED = "settled_failed"

LEDGER_EVENT_DEFER = "defer"
LEDGER_EVENT_RECLAIM = "reclaim"
LEDGER_EVENT_DECLINE = "decline"
LEDGER_EVENT_BEGIN_LAUNCH = "begin_launch"
LEDGER_EVENT_LAUNCHED = "launched"
LEDGER_EVENT_SETTLED_OK = "settled_ok"
LEDGER_EVENT_SETTLED_FAILED = "settled_failed"

RECOVERY_IN_FLIGHT_STATES: tuple[str, ...] = (
    "pending",
    "deferred",
    "launching",
)

VERDICT_MODE_RELAUNCH = "relaunch"
VERDICT_MODE_DEFER = "defer"
VERDICT_MODE_NOTIFY_POST_PROVIDER = "notify_post_provider"
VERDICT_MODE_ASK = "ask"
VERDICT_MODE_DECLINE = "decline"

PHASE_PRE_PROVIDER = "pre_provider"
PHASE_POST_PROVIDER = "post_provider"
PHASE_PLAN_HANDOFF = "plan_handoff"
PHASE_UNKNOWN = "unknown"


def _check_schema(data: dict[str, Any], *, what: str) -> int:
    schema_version = int(data.get("schema_version", 0))
    if schema_version != AGENT_AUTO_RESTART_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            "sase_core_rs auto-restart wire is stale: "
            f"expected schema {AGENT_AUTO_RESTART_WIRE_SCHEMA_VERSION}, "
            f"got {schema_version} for {what}"
        )
    return schema_version


def _opt_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _opt_int(value: Any) -> int | None:
    return None if value is None else int(value)


def _str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


@dataclass(frozen=True)
class AgentFailureChainLinkWire:
    type: str = ""
    qualname: str = ""
    module: str = ""
    message: str = ""


@dataclass(frozen=True)
class AgentFailureImportErrorWire:
    name: str | None = None
    path: str | None = None
    missing_symbol: str | None = None


@dataclass(frozen=True)
class AgentFailureAttributeErrorWire:
    module: str | None = None
    attribute: str | None = None


@dataclass(frozen=True)
class AgentFailureFrameWire:
    file: str = ""
    function: str = ""
    line: int | None = None


@dataclass(frozen=True)
class AgentFailureFactsWire:
    """Structured failure facts mirroring phase ``failure-facts`` exactly."""

    schema_version: int = AGENT_AUTO_RESTART_WIRE_SCHEMA_VERSION
    captured_at: str | None = None
    lifecycle_phase: str | None = None
    exception_chain: tuple[AgentFailureChainLinkWire, ...] = ()
    import_error: AgentFailureImportErrorWire | None = None
    attribute_error: AgentFailureAttributeErrorWire | None = None
    frames: tuple[AgentFailureFrameWire, ...] = ()
    last_frame_file: str | None = None
    skew_suspect: bool = False
    error_text: str | None = None


@dataclass(frozen=True)
class AutoRestartManagedRootWire:
    name: str = ""
    root: str = ""


@dataclass(frozen=True)
class AutoRestartContextWire:
    schema_version: int = AGENT_AUTO_RESTART_WIRE_SCHEMA_VERSION
    managed_roots: tuple[AutoRestartManagedRootWire, ...] = ()
    workspace_dir: str | None = None
    outcome: str | None = None
    kill_source: str | None = None
    lifecycle_phase: str | None = None
    has_pending_question: bool = False
    has_pending_handoff: bool = False
    is_remote: bool = False
    error_text: str = ""
    traceback_text: str = ""
    log_tail: str = ""


@dataclass(frozen=True)
class AutoRestartFileProofWire:
    symbol: str | None = None
    module: str | None = None
    boot_has: bool | None = None
    head_has: bool | None = None
    culprit_commit: str | None = None
    culprit_subject: str | None = None


@dataclass(frozen=True)
class AutoRestartProbeWire:
    ok: bool = False
    failures: tuple[str, ...] = ()


@dataclass(frozen=True)
class AutoRestartRefreshLogLineWire:
    from_rev: str = ""
    to_rev: str = ""


@dataclass(frozen=True)
class AutoRestartWitnessesWire:
    schema_version: int = AGENT_AUTO_RESTART_WIRE_SCHEMA_VERSION
    boot_identity: str | None = None
    current_identity: str | None = None
    journal_updates: tuple[str, ...] = ()
    file_proof: AutoRestartFileProofWire | None = None
    probe: AutoRestartProbeWire | None = None
    refresh_log_line: AutoRestartRefreshLogLineWire | None = None


@dataclass(frozen=True)
class RecoveryVerdictWire:
    """Deterministic recovery verdict returned by ``sase_core_rs``."""

    schema_version: int = AGENT_AUTO_RESTART_WIRE_SCHEMA_VERSION
    tier: str = ""
    family: str = ""
    signature: str = ""
    origin_module: str | None = None
    missing_symbol: str | None = None
    phase_class: str = PHASE_UNKNOWN
    mode: str = VERDICT_MODE_DECLINE
    reason: str = ""
    reason_text: str = ""
    witnesses_fired: tuple[str, ...] = ()
    episode_id: str | None = None


@dataclass(frozen=True)
class AutoRestartLedgerHistoryWire:
    state: str = ""
    at: str | None = None
    note: str | None = None


@dataclass(frozen=True)
class AutoRestartLedgerRecordWire:
    schema_version: int = AGENT_AUTO_RESTART_WIRE_SCHEMA_VERSION
    key: str = ""
    lineage_root: str = ""
    state: str = LEDGER_CLAIMED
    claimed_at: str | None = None
    failed_artifacts_dir: str | None = None
    agent_name: str | None = None
    project: str | None = None
    episode_id: str | None = None
    planned_name: str | None = None
    launched_artifacts_dir: str | None = None
    evidence_dir: str | None = None
    decline_reason: str | None = None
    deferrals: int = 0
    history: tuple[AutoRestartLedgerHistoryWire, ...] = ()


@dataclass(frozen=True)
class AutoRestartEpisodeWire:
    schema_version: int = AGENT_AUTO_RESTART_WIRE_SCHEMA_VERSION
    id: str = ""
    slug: str = ""
    culprit_short: str | None = None
    from_rev: str | None = None
    to_rev: str | None = None
    label: str = ""


@dataclass(frozen=True)
class AgentRecoveryWire:
    """The ``done.json`` recovery object."""

    state: str | None = None
    reason: str | None = None
    reason_text: str | None = None
    requested_at: str | None = None
    updated_at: str | None = None
    episode_id: str | None = None
    ledger_key: str | None = None


def agent_failure_facts_to_dict(facts: AgentFailureFactsWire) -> dict[str, Any]:
    """Serialize facts to the ``AgentFailureFactsWire`` dict shape."""
    return {
        "schema_version": facts.schema_version,
        "captured_at": facts.captured_at,
        "lifecycle_phase": facts.lifecycle_phase,
        "exception_chain": [
            {
                "type": link.type,
                "qualname": link.qualname,
                "module": link.module,
                "message": link.message,
            }
            for link in facts.exception_chain
        ],
        "import_error": (
            None
            if facts.import_error is None
            else {
                "name": facts.import_error.name,
                "path": facts.import_error.path,
                "missing_symbol": facts.import_error.missing_symbol,
            }
        ),
        "attribute_error": (
            None
            if facts.attribute_error is None
            else {
                "module": facts.attribute_error.module,
                "attribute": facts.attribute_error.attribute,
            }
        ),
        "frames": [
            {"file": f.file, "function": f.function, "line": f.line}
            for f in facts.frames
        ],
        "last_frame_file": facts.last_frame_file,
        "skew_suspect": facts.skew_suspect,
        "error_text": facts.error_text,
    }


def auto_restart_context_to_dict(
    context: AutoRestartContextWire,
) -> dict[str, Any]:
    """Serialize context to the ``AutoRestartContextWire`` dict shape."""
    return {
        "schema_version": context.schema_version,
        "managed_roots": [
            {"name": root.name, "root": root.root} for root in context.managed_roots
        ],
        "workspace_dir": context.workspace_dir,
        "outcome": context.outcome,
        "kill_source": context.kill_source,
        "lifecycle_phase": context.lifecycle_phase,
        "has_pending_question": context.has_pending_question,
        "has_pending_handoff": context.has_pending_handoff,
        "is_remote": context.is_remote,
        "error_text": context.error_text,
        "traceback_text": context.traceback_text,
        "log_tail": context.log_tail,
    }


def auto_restart_witnesses_to_dict(
    witnesses: AutoRestartWitnessesWire,
) -> dict[str, Any]:
    """Serialize witnesses to the ``AutoRestartWitnessesWire`` dict shape."""
    proof = witnesses.file_proof
    probe = witnesses.probe
    refresh = witnesses.refresh_log_line
    return {
        "schema_version": witnesses.schema_version,
        "boot_identity": witnesses.boot_identity,
        "current_identity": witnesses.current_identity,
        "journal_updates": list(witnesses.journal_updates),
        "file_proof": (
            None
            if proof is None
            else {
                "symbol": proof.symbol,
                "module": proof.module,
                "boot_has": proof.boot_has,
                "head_has": proof.head_has,
                "culprit_commit": proof.culprit_commit,
                "culprit_subject": proof.culprit_subject,
            }
        ),
        "probe": (
            None
            if probe is None
            else {"ok": probe.ok, "failures": list(probe.failures)}
        ),
        "refresh_log_line": (
            None
            if refresh is None
            else {"from": refresh.from_rev, "to": refresh.to_rev}
        ),
    }


def ledger_record_to_dict(
    record: AutoRestartLedgerRecordWire,
) -> dict[str, Any]:
    """Serialize a ledger record to its wire dict shape."""
    return {
        "schema_version": record.schema_version,
        "key": record.key,
        "lineage_root": record.lineage_root,
        "state": record.state,
        "claimed_at": record.claimed_at,
        "failed_artifacts_dir": record.failed_artifacts_dir,
        "agent_name": record.agent_name,
        "project": record.project,
        "episode_id": record.episode_id,
        "planned_name": record.planned_name,
        "launched_artifacts_dir": record.launched_artifacts_dir,
        "evidence_dir": record.evidence_dir,
        "decline_reason": record.decline_reason,
        "deferrals": record.deferrals,
        "history": [
            {"state": entry.state, "at": entry.at, "note": entry.note}
            for entry in record.history
        ],
    }


def recovery_verdict_from_dict(data: dict[str, Any]) -> RecoveryVerdictWire:
    """Rehydrate a recovery verdict from the PyO3 dict shape."""
    _check_schema(data, what="RecoveryVerdictWire")
    return RecoveryVerdictWire(
        schema_version=int(data["schema_version"]),
        tier=str(data.get("tier", "")),
        family=str(data.get("family", "")),
        signature=str(data.get("signature", "")),
        origin_module=_opt_str(data.get("origin_module")),
        missing_symbol=_opt_str(data.get("missing_symbol")),
        phase_class=str(data.get("phase_class", PHASE_UNKNOWN)),
        mode=str(data.get("mode", VERDICT_MODE_DECLINE)),
        reason=str(data.get("reason", "")),
        reason_text=str(data.get("reason_text", "")),
        witnesses_fired=tuple(_str_list(data.get("witnesses_fired"))),
        episode_id=_opt_str(data.get("episode_id")),
    )


def ledger_record_from_dict(data: dict[str, Any]) -> AutoRestartLedgerRecordWire:
    """Rehydrate a ledger record from the PyO3 dict shape."""
    _check_schema(data, what="AutoRestartLedgerRecordWire")
    history: list[AutoRestartLedgerHistoryWire] = []
    for entry in data.get("history") or []:
        if isinstance(entry, dict):
            history.append(
                AutoRestartLedgerHistoryWire(
                    state=str(entry.get("state", "")),
                    at=_opt_str(entry.get("at")),
                    note=_opt_str(entry.get("note")),
                )
            )
    return AutoRestartLedgerRecordWire(
        schema_version=int(data["schema_version"]),
        key=str(data.get("key", "")),
        lineage_root=str(data.get("lineage_root", "")),
        state=str(data.get("state", LEDGER_CLAIMED)),
        claimed_at=_opt_str(data.get("claimed_at")),
        failed_artifacts_dir=_opt_str(data.get("failed_artifacts_dir")),
        agent_name=_opt_str(data.get("agent_name")),
        project=_opt_str(data.get("project")),
        episode_id=_opt_str(data.get("episode_id")),
        planned_name=_opt_str(data.get("planned_name")),
        launched_artifacts_dir=_opt_str(data.get("launched_artifacts_dir")),
        evidence_dir=_opt_str(data.get("evidence_dir")),
        decline_reason=_opt_str(data.get("decline_reason")),
        deferrals=int(data.get("deferrals", 0)),
        history=tuple(history),
    )


def episode_from_dict(data: dict[str, Any]) -> AutoRestartEpisodeWire:
    """Rehydrate an episode identity from the PyO3 dict shape."""
    _check_schema(data, what="AutoRestartEpisodeWire")
    return AutoRestartEpisodeWire(
        schema_version=int(data["schema_version"]),
        id=str(data.get("id", "")),
        slug=str(data.get("slug", "")),
        culprit_short=_opt_str(data.get("culprit_short")),
        from_rev=_opt_str(data.get("from_rev")),
        to_rev=_opt_str(data.get("to_rev")),
        label=str(data.get("label", "")),
    )


def agent_recovery_from_mapping(data: Any) -> AgentRecoveryWire | None:
    """Return the ``AgentRecoveryWire`` *data* describes, or ``None``."""
    if not isinstance(data, dict):
        return None
    if not data:
        return None
    return AgentRecoveryWire(
        state=_opt_str(data.get("state")),
        reason=_opt_str(data.get("reason")),
        reason_text=_opt_str(data.get("reason_text")),
        requested_at=_opt_str(data.get("requested_at")),
        updated_at=_opt_str(data.get("updated_at")),
        episode_id=_opt_str(data.get("episode_id")),
        ledger_key=_opt_str(data.get("ledger_key")),
    )


__all__ = [
    "AGENT_AUTO_RESTART_WIRE_SCHEMA_VERSION",
    "LEDGER_CLAIMED",
    "LEDGER_DECLINED",
    "LEDGER_DEFERRED",
    "LEDGER_EVENT_BEGIN_LAUNCH",
    "LEDGER_EVENT_DECLINE",
    "LEDGER_EVENT_DEFER",
    "LEDGER_EVENT_LAUNCHED",
    "LEDGER_EVENT_RECLAIM",
    "LEDGER_EVENT_SETTLED_FAILED",
    "LEDGER_EVENT_SETTLED_OK",
    "LEDGER_LAUNCHED",
    "LEDGER_LAUNCHING",
    "LEDGER_SETTLED_FAILED",
    "LEDGER_SETTLED_OK",
    "PHASE_PLAN_HANDOFF",
    "PHASE_POST_PROVIDER",
    "PHASE_PRE_PROVIDER",
    "PHASE_UNKNOWN",
    "RECOVERY_IN_FLIGHT_STATES",
    "VERDICT_MODE_ASK",
    "VERDICT_MODE_DECLINE",
    "VERDICT_MODE_DEFER",
    "VERDICT_MODE_NOTIFY_POST_PROVIDER",
    "VERDICT_MODE_RELAUNCH",
    "AgentFailureAttributeErrorWire",
    "AgentFailureChainLinkWire",
    "AgentFailureFactsWire",
    "AgentFailureFrameWire",
    "AgentFailureImportErrorWire",
    "AgentRecoveryWire",
    "AutoRestartContextWire",
    "AutoRestartEpisodeWire",
    "AutoRestartFileProofWire",
    "AutoRestartLedgerHistoryWire",
    "AutoRestartLedgerRecordWire",
    "AutoRestartManagedRootWire",
    "AutoRestartProbeWire",
    "AutoRestartRefreshLogLineWire",
    "AutoRestartWitnessesWire",
    "RecoveryVerdictWire",
    "agent_failure_facts_to_dict",
    "agent_recovery_from_mapping",
    "auto_restart_context_to_dict",
    "auto_restart_witnesses_to_dict",
    "episode_from_dict",
    "ledger_record_from_dict",
    "ledger_record_to_dict",
    "recovery_verdict_from_dict",
]
