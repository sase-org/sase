"""Detached ``sase gate answer`` submission.

A gate-turn-backed answer defaults to running as a supervised background
proc so an approved command outlives the client that approved it. The
submitted proc re-invokes the same command with ``--no-detach`` so it
cannot recurse into another detached submission.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from sase.notification_gates.cli_support import ResolvedGateCliBundle
from sase.notification_gates.model_options import GateOption
from sase.notification_gates.models import GateError
from sase.ops.names import GATE_ANSWER
from sase.procs.request import ProcSubmitRequest
from sase.procs.submission import submit_proc_request

#: Origin tag recorded on a proc submitted by ``sase gate answer --detach``.
GATE_ANSWER_DETACH_ORIGIN = "gate-answer-detach"


def effective_detach(args: argparse.Namespace, *, turn_backed: bool) -> bool:
    """Return whether this answer should run as a detached background proc.

    Explicit ``--detach``/``--no-detach`` always win; absent either flag, a
    gate-turn-backed gate defaults to detached so an approved command
    outlives the client that approved it, and an ordinary gate keeps
    today's synchronous default.
    """
    if bool(getattr(args, "detach", False)):
        return True
    if bool(getattr(args, "no_detach", False)):
        return False
    return turn_backed


def reject_detached_tty_options(selected: tuple[GateOption, ...]) -> None:
    """Refuse detached submission for options that need a controlling TTY."""
    ids = [option.id for option in selected if option.requires_tty]
    if not ids:
        return
    raise GateError(
        "tty_required",
        ", ".join(ids),
        "this gate option requires a controlling TTY and cannot be submitted "
        "through a detached answer proc",
    )


def submit_detached_answer(
    bundle: ResolvedGateCliBundle,
    selected: tuple[GateOption, ...],
    *,
    input_data: object | None,
    feedback: str | None,
    retry: Literal["resume", "restart"] | None,
    option_inputs: Mapping[str, object] | None,
    source: str | None = None,
    review_revision: int | None = None,
) -> dict[str, Any]:
    """Submit a supervised background proc that owns this gate's execution.

    Every resolved argument travels through the operation-request sidecar
    instead of argv, the same durable-submission contract ACE already
    answers gates through.
    """
    selected_ids = [option.id for option in selected]
    payload: dict[str, Any] = {"option_ids": selected_ids}
    if input_data is not None:
        payload["input_data"] = input_data
    if option_inputs is not None:
        payload["option_inputs"] = dict(option_inputs)
    if feedback is not None:
        payload["feedback"] = feedback
    if retry is not None:
        payload["retry"] = retry
    if source is not None:
        payload["source"] = source
    if review_revision is not None:
        payload["review_revision"] = review_revision

    proc = submit_proc_request(
        ProcSubmitRequest(
            argv=[
                "sase",
                "gate",
                "answer",
                "--id",
                bundle.request_id,
                "--kind",
                bundle.kind,
                "--no-detach",
                "--json",
            ],
            label=f"Gate answer: {bundle.kind}/{bundle.request_id}",
            cwd=str(Path.cwd()),
            origin=GATE_ANSWER_DETACH_ORIGIN,
            operation=GATE_ANSWER,
            operation_payload=payload,
        )
    )
    return {
        "already_answered": False,
        "detached": True,
        "feedback": feedback,
        "kind": bundle.kind,
        "message": f"Gate answer submitted to background proc {proc.proc_id}",
        "option_inputs": dict(option_inputs) if option_inputs else {},
        "option_results": [],
        "proc_id": proc.proc_id,
        "request_id": bundle.request_id,
        "response_path": str(bundle.response_path),
        "selected_option_ids": selected_ids,
        "status": "submitted",
    }


__all__ = [
    "GATE_ANSWER_DETACH_ORIGIN",
    "effective_detach",
    "reject_detached_tty_options",
    "submit_detached_answer",
]
