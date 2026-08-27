"""Gate-shell request-model and envelope coverage."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

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
