"""Gate-shell request-model and envelope coverage."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.gate_shell.store import find_gate_shell_by_gate_id
from sase.notification_gates.durability import request_sha256
from sase.notification_gates.hashing import load_and_verify_bundle
from sase.notification_gates.model_shell import (
    DEFAULT_GATE_SHELL_PENDING_STATUS,
    DEFAULT_GATE_SHELL_SETTLED_STATUS,
    GATE_SHELL_DEFAULT_TIMEOUT_SECONDS,
    GATE_SHELL_STATUS_ELLIPSIS,
)
from sase.notification_gates.models import GateError, GateSpec
from sase.notification_gates.service import create_gate
from tests._notification_gates_fixtures import custom_gate_spec, gate_spec
from tests.gate_shell._settlement_followup_helpers import (
    DEFAULT_SHELL,
    gate_spec as shell_member_gate_spec,
    make_gate_shell_member,
    sandbox_home,
)

__all__ = ["sandbox_home"]


def test_shell_block_defaults_timeout_and_statuses() -> None:
    raw = gate_spec(request_id="shell-defaults")
    raw["shell"] = {}

    spec = GateSpec.from_mapping(raw)

    assert spec.gate_timeout_seconds == GATE_SHELL_DEFAULT_TIMEOUT_SECONDS
    assert spec.shell is not None
    assert spec.shell.pending_status == DEFAULT_GATE_SHELL_PENDING_STATUS
    assert spec.shell.settled_status == DEFAULT_GATE_SHELL_SETTLED_STATUS
    assert spec.shell.workspace == "inherit"
    assert spec.shell.next.output == ("results",)
    assert spec.shell.next.fork == "family"


def test_explicit_shell_gate_timeout_is_preserved() -> None:
    raw = gate_spec(request_id="shell-timeout", timeout=45)
    raw["shell"] = {}

    assert GateSpec.from_mapping(raw).gate_timeout_seconds == 45.0


def test_shell_branch_keys_follow_compiled_gate_branches() -> None:
    raw = custom_gate_spec(request_id="shell-branches")
    raw["shell"] = {
        "branches": {
            "proceed+audit+broken": {
                "status": "APPROVED",
                "accent": "#00D7AF",
                "prompt": "ship it",
                "output": ["results", "tail"],
            },
            "timeout": {"status": "TIMED OUT"},
        }
    }

    spec = GateSpec.from_mapping(raw)

    assert spec.shell is not None
    assert set(spec.shell.branches) == {"proceed+audit+broken", "timeout"}
    approved = spec.shell.branches["proceed+audit+broken"]
    assert approved.status == "APPROVED"
    assert approved.prompt == "ship it"
    assert approved.output == ("results", "tail")


def test_shell_rejects_unknown_branch_keys() -> None:
    raw = custom_gate_spec(request_id="shell-bad-branch")
    raw["shell"] = {"branches": {"proceed": {"status": "APPROVED"}}}

    with pytest.raises(GateError) as exc_info:
        GateSpec.from_mapping(raw)

    assert exc_info.value.code == "invalid_shell"
    assert exc_info.value.target == "shell.branches.proceed"


def test_shell_statuses_are_clamped_to_gate_display_width() -> None:
    raw = gate_spec(request_id="shell-clamped")
    raw["shell"] = {
        "pending_status": "ABCDEFGHIJKLMNOPQRSTUV",
        "settled_status": "ZYXWVUTSRQPONMLKJIHGF",
    }

    spec = GateSpec.from_mapping(raw)

    assert spec.shell is not None
    assert len(spec.shell.pending_status) == 20
    assert spec.shell.pending_status.endswith(GATE_SHELL_STATUS_ELLIPSIS)
    assert len(spec.shell.settled_status) == 20
    assert spec.shell.settled_status.endswith(GATE_SHELL_STATUS_ELLIPSIS)


def test_shell_survives_durable_envelope_and_request_hash(
    gate_home: Path,
) -> None:
    raw = gate_spec(request_id="shell-envelope")
    raw["shell"] = {
        "pending_status": "WAIT",
        "settled_status": "DONE",
        "workspace": "release",
        "next": {
            "prompt": "continue after review",
            "fork": "shell",
            "model": "gpt-5",
            "output": ["results", "file"],
        },
    }

    result = create_gate(raw)
    envelope, _adapter = load_and_verify_bundle(result.bundle_path)
    request = json.loads(result.request_path.read_text(encoding="utf-8"))

    assert envelope["shell"] == request["shell"]
    assert envelope["shell"]["pending_status"] == "WAIT"
    assert envelope["shell"]["settled_status"] == "DONE"
    assert envelope["shell"]["workspace"] == "release"
    assert envelope["shell"]["next"]["fork"] == "shell"
    assert request_sha256(envelope) == result.hashes["request"]


def test_shell_block_derives_gate_shell_continuation_mode() -> None:
    """A shell block without an explicit mode keeps the shell (sase-14n.12)."""
    raw = custom_gate_spec(request_id="shell-derived-mode")
    raw["shell"] = {"next": {"fork": "family"}}

    spec = GateSpec.from_mapping(raw)

    assert spec.shell is not None
    assert spec.continuation_mode == "gate_shell"


def test_shell_block_rejects_explicit_none_continuation_mode() -> None:
    """Shell plus an explicit "none" mode is rejected instead of dropped."""
    raw = custom_gate_spec(request_id="shell-none-mode")
    raw["shell"] = {"next": {"fork": "family"}}
    raw["continuation_mode"] = "none"

    with pytest.raises(GateError) as exc_info:
        GateSpec.from_mapping(raw)

    assert exc_info.value.code == "invalid_request"
    assert exc_info.value.target == "continuation_mode"


def test_shell_block_keeps_explicit_continuation_mode() -> None:
    """An explicit non-"none" mode still wins over the derived default."""
    raw = custom_gate_spec(request_id="shell-explicit-mode")
    raw["shell"] = {"next": {"fork": "family"}}
    raw["continuation_mode"] = "agent_question"

    spec = GateSpec.from_mapping(raw)

    assert spec.shell is not None
    assert spec.continuation_mode == "agent_question"


def test_shell_less_request_keeps_none_default() -> None:
    """Requests without a shell block still default to "none"."""
    spec = GateSpec.from_mapping(custom_gate_spec(request_id="no-shell-mode"))

    assert spec.shell is None
    assert spec.continuation_mode == "none"


def test_shell_block_custom_gate_records_shell_mode_and_registers_row(
    gate_home: Path,
) -> None:
    """A custom gate declaring a shell block keeps it through creation."""
    del gate_home
    request_id = "shell-row-custom"
    shell = dict(DEFAULT_SHELL)

    gate = create_gate(shell_member_gate_spec(request_id, shell=shell))

    assert gate.continuation_mode == "gate_shell"
    envelope = json.loads((gate.bundle_path / "request.json").read_text())
    assert envelope["continuation_mode"] == "gate_shell"
    assert isinstance(envelope.get("shell"), dict)

    artifacts_dir = make_gate_shell_member(request_id, gate.bundle_path, shell=shell)
    record = find_gate_shell_by_gate_id(None, request_id)

    assert record is not None
    assert record.gate_id == request_id
    assert record.artifacts_dir == artifacts_dir
