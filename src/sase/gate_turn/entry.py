"""Shared CLI entry protocol for turn-backed custom, sudo, and launch gates."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from sase.gate_turn.models import GateTurnError, GateTurnRecord
from sase.gate_turn.transaction import GateTurnCreation
from sase.notification_gates.model_request import GateSpec
from sase.notification_gates.model_results import GateCreationResult

if TYPE_CHECKING:
    from sase.gate_turn.staged_contract import StagedGatePreparation

STAGED_GATE_INSTRUCTION = (
    "Nothing starts until this turn ends; finish through `/sase_final`. "
    "Do not wait for your own staged gate."
)


@dataclass(frozen=True)
class _GateEntryOutcome:
    """Result of one shared gate-entry attempt, before CLI output."""

    status: Literal["staged", "published"]
    preparation: StagedGatePreparation | None = None
    creation: GateTurnCreation | None = None
    reservation_id: str | None = None

    @property
    def is_staged(self) -> bool:
        return self.status == "staged"


def handle_gate_entry(
    request_factory: Callable[[], Mapping[str, Any] | GateSpec],
    *,
    command: str,
    before_legacy_prepare: Callable[[], None] | None = None,
    on_legacy_failure: Callable[[], None] | None = None,
    before_auto_settle: Callable[[GateTurnRecord, GateCreationResult], None]
    | None = None,
    allow_auto: bool = True,
) -> None:
    """Prepare, stage or publish a gate, print its descriptor, then hand off.

    Agent calls reserve their one-handoff slot before gate preparation. With
    staged handoffs enabled, pending human gates write only a staged record;
    effective auto gates still publish synchronously. With the flag disabled,
    the existing marker-and-kill protocol is retained, with its slot protected
    from concurrent gate publication by the same reservation.
    """
    _complete_gate_entry(
        run_gate_entry(
            request_factory,
            command=command,
            before_legacy_prepare=before_legacy_prepare,
            on_legacy_failure=on_legacy_failure,
            before_auto_settle=before_auto_settle,
            allow_auto=allow_auto,
        )
    )


def run_gate_entry(
    request_factory: Callable[[], Mapping[str, Any] | GateSpec],
    *,
    command: str,
    before_legacy_prepare: Callable[[], None] | None = None,
    on_legacy_failure: Callable[[], None] | None = None,
    before_auto_settle: Callable[[GateTurnRecord, GateCreationResult], None]
    | None = None,
    allow_auto: bool = True,
) -> _GateEntryOutcome:
    """Reserve, prepare, and stage or publish a gate without printing or handoff.

    The caller owns any leftover reservation on a published outcome and must
    either hand off or release it. Staged outcomes have already consumed the
    reservation by writing the durable record.
    """
    from sase.agent.staged_handoff import (
        StagedHandoffError,
        acquire_staging_reservation,
        release_staging_reservation,
        staged_handoffs_enabled,
        write_staged_handoff,
    )
    from sase.gate_turn import create_gate_turn

    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    in_agent = bool(os.environ.get("SASE_AGENT"))
    reservation_id: str | None = None
    preparation: StagedGatePreparation | None = None
    staged_record_written = False
    success = False

    try:
        if in_agent:
            use_staged = staged_handoffs_enabled()
            reservation_id = acquire_staging_reservation(
                artifacts_dir=artifacts_dir,
                command=command,
            )
            if use_staged:
                from sase.gate_turn.staged_contract import collect_staged_gate_creator

                creator = collect_staged_gate_creator(artifacts_dir=artifacts_dir)
                preparation = _prepare_staged_gate(
                    request_factory(), creator=creator, artifacts_dir=artifacts_dir
                )
                if preparation.auto_execute and not allow_auto:
                    raise GateTurnError("LaunchApproval cannot auto-execute")
                if not preparation.auto_execute:
                    if preparation.record is None:
                        raise GateTurnError(
                            "pending gate preparation did not produce a staged record"
                        )
                    write_staged_handoff(
                        preparation.record,
                        artifacts_dir=artifacts_dir,
                        command=command,
                        reservation_id=reservation_id,
                    )
                    staged_record_written = True
                    reservation_id = None
                    success = True
                    return _GateEntryOutcome(
                        status="staged",
                        preparation=preparation,
                    )

                creation_kwargs: dict[str, Any] = {
                    "frozen_auto": {
                        "decision": preparation.decision,
                        "policy_block": preparation.policy_block,
                        "auto_execute": True,
                    }
                }
                if before_auto_settle is not None:
                    creation_kwargs["before_auto_settle"] = before_auto_settle
                creation = create_gate_turn(preparation.spec, **creation_kwargs)
            else:
                creation = _run_legacy_creation(
                    request_factory,
                    before_legacy_prepare=before_legacy_prepare,
                    on_legacy_failure=on_legacy_failure,
                    before_auto_settle=before_auto_settle,
                    allow_auto=allow_auto,
                )
        else:
            creation = _run_legacy_creation(
                request_factory,
                before_legacy_prepare=before_legacy_prepare,
                on_legacy_failure=on_legacy_failure,
                before_auto_settle=before_auto_settle,
                allow_auto=allow_auto,
            )

        success = True
        return _GateEntryOutcome(
            status="published",
            preparation=preparation,
            creation=creation,
            reservation_id=reservation_id,
        )
    except StagedHandoffError as exc:
        raise GateTurnError(str(exc)) from exc
    finally:
        if preparation is not None and not staged_record_written:
            _discard_prepared_snapshot(preparation, artifacts_dir)
        if not success and reservation_id is not None:
            release_staging_reservation(
                reservation_id,
                artifacts_dir=artifacts_dir,
            )


def _complete_gate_entry(outcome: _GateEntryOutcome) -> None:
    """Print the common descriptor and hand off a published gate turn."""
    from sase.agent.staged_handoff import release_staging_reservation
    from sase.gate_turn import (
        maybe_handoff_gate_from_agent,
        will_handoff_gate_to_agent_runner,
    )

    if outcome.status == "staged":
        if outcome.preparation is None:
            raise GateTurnError("staged gate entry has no preparation")
        emit_staged_descriptor(
            kind=outcome.preparation.spec.kind,
            request_id=outcome.preparation.request_id,
            staged_id=outcome.preparation.staged_id,
            workspace_mode=outcome.preparation.workspace_mode,
        )
        return
    if outcome.creation is None:
        raise GateTurnError("published gate entry has no creation")
    reservation_id = outcome.reservation_id
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    try:
        _emit_published_descriptor(outcome.creation)
        if outcome.creation.should_handoff and will_handoff_gate_to_agent_runner():
            if reservation_id is None:
                raise GateTurnError("gate handoff has no active admission reservation")
            maybe_handoff_gate_from_agent(
                outcome.creation,
                reservation_id=reservation_id,
            )
            reservation_id = None
    finally:
        if reservation_id is not None:
            release_staging_reservation(
                reservation_id,
                artifacts_dir=artifacts_dir,
            )


def emit_staged_descriptor(
    *,
    kind: str,
    request_id: str,
    staged_id: str,
    workspace_mode: str,
) -> None:
    """Print the shared staged descriptor: JSON on stdout, instruction on stderr."""
    descriptor = {
        "schema_version": 1,
        "status": "staged",
        "kind": kind,
        "request_id": request_id,
        "staged_id": staged_id,
        "workspace_mode": workspace_mode,
        "instruction": STAGED_GATE_INSTRUCTION,
    }
    json.dump(descriptor, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    sys.stdout.flush()
    print(
        f"Staged {kind} gate request {request_id}. {STAGED_GATE_INSTRUCTION}",
        file=sys.stderr,
    )


def _run_legacy_creation(
    request_factory: Callable[[], Mapping[str, Any] | GateSpec],
    *,
    before_legacy_prepare: Callable[[], None] | None,
    on_legacy_failure: Callable[[], None] | None,
    before_auto_settle: Callable[[GateTurnRecord, GateCreationResult], None] | None,
    allow_auto: bool,
) -> GateTurnCreation:
    from sase.gate_turn import create_gate_turn

    try:
        if before_legacy_prepare is not None:
            before_legacy_prepare()
        request = request_factory()
        if not allow_auto and _request_auto_enabled(request):
            raise GateTurnError("LaunchApproval cannot auto-execute")
        if before_auto_settle is None:
            return create_gate_turn(request)
        return create_gate_turn(request, before_auto_settle=before_auto_settle)
    except BaseException:
        if on_legacy_failure is not None:
            on_legacy_failure()
        raise


def _request_auto_enabled(request: Mapping[str, Any] | GateSpec) -> bool:
    if isinstance(request, GateSpec):
        return bool(request.auto.enabled)
    auto = request.get("auto")
    if auto is True:
        return True
    return isinstance(auto, Mapping) and auto.get("enabled") is True


def _prepare_staged_gate(
    request: Mapping[str, Any] | GateSpec,
    *,
    creator: Mapping[str, Any],
    artifacts_dir: str | None,
) -> StagedGatePreparation:
    from sase.gate_turn.staged_contract import prepare_staged_gate

    if not artifacts_dir:
        raise GateTurnError("SASE_ARTIFACTS_DIR is unset")
    return prepare_staged_gate(
        request,
        creator=creator,
        artifacts_dir=artifacts_dir,
    )


def _emit_published_descriptor(creation: GateTurnCreation) -> None:
    print(json.dumps(creation.to_dict(), sort_keys=True))
    sys.stdout.flush()


def _discard_prepared_snapshot(
    preparation: StagedGatePreparation, artifacts_dir: str | None
) -> None:
    if preparation.snapshot_dir is None or not artifacts_dir:
        return
    from sase.gate_turn.staged_contract import discard_staged_gate_snapshot

    discard_staged_gate_snapshot(artifacts_dir, preparation.staged_id)


__all__ = [
    "STAGED_GATE_INSTRUCTION",
    "emit_staged_descriptor",
    "handle_gate_entry",
    "run_gate_entry",
]
