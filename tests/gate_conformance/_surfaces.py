"""The surfaces every conformance case is run through.

Each driver calls the real entry point its surface uses in production -- the
CLI goes through ``sase gate``'s own parser and handler, ACE through the
tracked-submission worker body, mobile through the host bridge action -- so a
case passing here means that surface really behaves that way, not that a test
helper does.

``capabilities`` is the one place a surface's submission reach is declared.
When a pending phase teaches a surface to carry per-option inputs, adding the
capability here is the whole change: the cases it unlocks stop skipping.
"""

from __future__ import annotations

import argparse
import contextlib
import io
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from tests.gate_conformance._cases import (
    CAP_FEEDBACK,
    CAP_OPTION_INPUTS,
    CAP_RETRY,
    CAP_SHARED_INPUT,
    Submission,
)

#: Why a surface lacks a capability, quoted in the skip message.
#:
#: An entry here is a standing limitation with a reason, not a to-do: it must
#: name why the surface cannot submit the capability today, never a bead that
#: might close without the entry being revisited.
PENDING_CAPABILITY_PHASES = {
    ("mobile", CAP_SHARED_INPUT): (
        "the bridge wire carries no shared `input` field, so a pre-`inputs` "
        "bundle whose schema requires a value can only be answered from a "
        "surface that has one"
    ),
    ("mobile", CAP_RETRY): (
        "the bridge wire carries no `retry` field, so a mobile reviewer who "
        "reaches a partially executed AND branch gets `partial_attempt` and "
        "must resume or restart from the CLI or ACE -- a dead end, never a "
        "silent re-run"
    ),
}


@dataclass(frozen=True)
class SurfaceTarget:
    """Everything a driver needs to address one created gate."""

    bundle_path: Path
    kind: str
    request_id: str
    notification_id: str | None


@dataclass(frozen=True)
class SurfaceOutcome:
    """The surface-neutral projection of one submission attempt."""

    answered: bool
    message: str


@dataclass(frozen=True)
class Surface:
    """One way a reviewer can answer a gate."""

    name: str
    capabilities: frozenset[str]
    submit: Callable[[SurfaceTarget, Submission], SurfaceOutcome]

    def missing(self, required: frozenset[str]) -> frozenset[str]:
        return required - self.capabilities

    def why_missing(self, capability: str) -> str:
        return PENDING_CAPABILITY_PHASES.get(
            (self.name, capability), "not yet supported"
        )


def _submit_via_cli(target: SurfaceTarget, submission: Submission) -> SurfaceOutcome:
    """Answer through ``sase gate answer``, parser and handler included."""
    import json

    from sase.main.gate_handler import handle_gate_command
    from sase.main.parser_gate import register_gate_parser

    argv = ["gate", "answer", "--id", target.request_id, "--kind", target.kind]
    for option_id in submission.selected:
        argv += ["--option", option_id]
    if submission.input_data is not None:
        argv += ["--input", json.dumps(submission.input_data)]
    for option_id, value in (submission.option_inputs or {}).items():
        argv += ["--option-input", f"{option_id}={json.dumps(value)}"]
    if submission.feedback is not None:
        argv += ["--feedback", submission.feedback]
    if submission.retry == "resume":
        argv.append("--resume")
    elif submission.retry == "restart":
        argv.append("--restart")

    parser = argparse.ArgumentParser(prog="sase")
    register_gate_parser(parser.add_subparsers(dest="command"))
    args = parser.parse_args(argv)

    stdout, stderr = io.StringIO(), io.StringIO()
    code = 0
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        try:
            handle_gate_command(args)
        except SystemExit as exc:
            code = int(exc.code or 0)
    return SurfaceOutcome(
        answered=code == 0,
        message=stderr.getvalue() or stdout.getvalue(),
    )


def _submit_via_ace(target: SurfaceTarget, submission: Submission) -> SurfaceOutcome:
    """Answer through the command ACE's durable proc now executes."""
    return _submit_via_cli(target, submission)


def _submit_via_mobile(target: SurfaceTarget, submission: Submission) -> SurfaceOutcome:
    """Answer through the mobile host bridge action."""
    from sase.integrations._mobile_notification_models import MobileGateActionError
    from sase.integrations.mobile_notifications import execute_mobile_gate_action
    from sase.notifications.store import load_notifications

    rows = [
        row
        for row in load_notifications(include_dismissed=True)
        if row.id == target.notification_id
    ]
    snapshot = SimpleNamespace(
        notifications=rows,
        counts=SimpleNamespace(priority=1, errors=0, rest=1, muted=0),
        expired_ids=[],
    )
    with (
        patch(
            "sase.integrations._mobile_notification_snapshot"
            ".read_current_notification_snapshot",
            return_value=snapshot,
        ),
        patch("sase.notifications.pending_actions.resolve_prefix") as resolve,
    ):
        resolve.return_value = SimpleNamespace(
            notification_id=target.notification_id,
            prefix="conf",
            prefix_len=4,
            resolution="unique_prefix",
        )
        try:
            execute_mobile_gate_action(
                "conf",
                list(submission.selected),
                feedback=submission.feedback,
                option_inputs=submission.option_inputs,
            )
        except MobileGateActionError as exc:
            return SurfaceOutcome(answered=False, message=f"{exc.code}: {exc}")
    return SurfaceOutcome(answered=True, message="")


SURFACES: tuple[Surface, ...] = (
    Surface(
        name="cli",
        capabilities=frozenset(
            {CAP_FEEDBACK, CAP_OPTION_INPUTS, CAP_RETRY, CAP_SHARED_INPUT}
        ),
        submit=_submit_via_cli,
    ),
    Surface(
        name="ace",
        capabilities=frozenset(
            {CAP_FEEDBACK, CAP_OPTION_INPUTS, CAP_RETRY, CAP_SHARED_INPUT}
        ),
        submit=_submit_via_ace,
    ),
    Surface(
        name="mobile",
        capabilities=frozenset({CAP_FEEDBACK, CAP_OPTION_INPUTS}),
        submit=_submit_via_mobile,
    ),
)


__all__ = [
    "PENDING_CAPABILITY_PHASES",
    "SURFACES",
    "Surface",
    "SurfaceOutcome",
    "SurfaceTarget",
]
