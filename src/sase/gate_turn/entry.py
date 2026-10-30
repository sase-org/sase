"""Shared CLI entry protocol for turn-backed custom and sudo gates."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any

from sase.gate_turn.models import GateTurnError, GateTurnRecord
from sase.gate_turn.transaction import GateTurnCreation
from sase.notification_gates.model_request import GateSpec
from sase.notification_gates.model_results import GateCreationResult

if TYPE_CHECKING:
    from sase.gate_turn.staged_contract import StagedGatePreparation

_STAGED_INSTRUCTION = (
    "Nothing starts until this turn ends; finish through `/sase_final`. "
    "Do not wait for your own staged gate."
)


def handle_gate_entry(
    request_factory: Callable[[], Mapping[str, Any] | GateSpec],
    *,
    command: str,
    before_legacy_prepare: Callable[[], None] | None = None,
    on_legacy_failure: Callable[[], None] | None = None,
    before_auto_settle: Callable[[GateTurnRecord, GateCreationResult], None]
    | None = None,
) -> None:
    """Prepare, stage or publish a gate, print its descriptor, then hand off.

    Agent calls reserve their one-handoff slot before gate preparation. With
    staged handoffs enabled, pending human gates write only a staged record;
    effective auto gates still publish synchronously. With the flag disabled,
    the existing marker-and-kill protocol is retained, with its slot protected
    from concurrent gate publication by the same reservation.
    """
    from sase.agent.staged_handoff import (
        StagedHandoffError,
        acquire_staging_reservation,
        release_staging_reservation,
        staged_handoffs_enabled,
        write_staged_handoff,
    )
    from sase.gate_turn import (
        create_gate_turn,
        maybe_handoff_gate_from_agent,
        will_handoff_gate_to_agent_runner,
    )

    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    in_agent = bool(os.environ.get("SASE_AGENT"))
    reservation_id: str | None = None
    preparation: StagedGatePreparation | None = None
    staged_record_written = False

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
                    _emit_staged_descriptor(preparation)
                    return

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
                )
        else:
            creation = _run_legacy_creation(
                request_factory,
                before_legacy_prepare=before_legacy_prepare,
                on_legacy_failure=on_legacy_failure,
                before_auto_settle=before_auto_settle,
            )

        _emit_published_descriptor(creation)
        if creation.should_handoff and will_handoff_gate_to_agent_runner():
            if reservation_id is None:
                raise GateTurnError("gate handoff has no active admission reservation")
            maybe_handoff_gate_from_agent(
                creation,
                reservation_id=reservation_id,
            )
            reservation_id = None
    except StagedHandoffError as exc:
        raise GateTurnError(str(exc)) from exc
    finally:
        if preparation is not None and not staged_record_written:
            _discard_prepared_snapshot(preparation, artifacts_dir)
        if reservation_id is not None:
            release_staging_reservation(
                reservation_id,
                artifacts_dir=artifacts_dir,
            )


def _run_legacy_creation(
    request_factory: Callable[[], Mapping[str, Any] | GateSpec],
    *,
    before_legacy_prepare: Callable[[], None] | None,
    on_legacy_failure: Callable[[], None] | None,
    before_auto_settle: Callable[[GateTurnRecord, GateCreationResult], None] | None,
) -> GateTurnCreation:
    from sase.gate_turn import create_gate_turn

    try:
        if before_legacy_prepare is not None:
            before_legacy_prepare()
        request = request_factory()
        if before_auto_settle is None:
            return create_gate_turn(request)
        return create_gate_turn(request, before_auto_settle=before_auto_settle)
    except BaseException:
        if on_legacy_failure is not None:
            on_legacy_failure()
        raise


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


def _emit_staged_descriptor(preparation: StagedGatePreparation) -> None:
    descriptor = {
        "schema_version": 1,
        "status": "staged",
        "kind": preparation.spec.kind,
        "request_id": preparation.request_id,
        "staged_id": preparation.staged_id,
        "workspace_mode": preparation.workspace_mode,
        "instruction": _STAGED_INSTRUCTION,
    }
    json.dump(descriptor, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    sys.stdout.flush()
    print(
        f"Staged {preparation.spec.kind} gate request {preparation.request_id}. "
        f"{_STAGED_INSTRUCTION}",
        file=sys.stderr,
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


__all__ = ["handle_gate_entry"]
