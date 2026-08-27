"""The question gate shell's request spec and chain-metadata bookkeeping."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sase.gate_shell.member import create_gate_shell_member
from sase.gate_shell.transaction import GateShellCreation
from sase.main.qa_markdown import QARound
from sase.notification_gates.model_shell import (
    GATE_SHELL_DEFAULT_TIMEOUT_SECONDS,
    GateShellSpec,
)
from sase.notification_gates.models import GateSpec
from sase.notification_gates.service import create_gate
from sase.question_shell.create import (
    _question_gate_shell_spec,
    create_question_gate_shell,
)


@pytest.fixture(autouse=True)
def _sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))


def _questions() -> list[dict[str, Any]]:
    return [
        {
            "question": "Which database?",
            "options": [{"label": "SQLite"}, {"label": "PostgreSQL"}],
        }
    ]


def test_shell_block_pins_statuses_and_accents() -> None:
    spec = _question_gate_shell_spec(
        _questions(),
        session_id="round-1",
        base_prompt="Implement the feature.",
        prior_rounds=[],
    )

    shell = spec["shell"]
    assert shell["pending_status"] == "QUESTION"
    assert shell["settled_status"] == "ANSWERED"
    assert shell["accent"] == "#FFAF00"
    assert shell["workspace"] == "inherit"
    assert shell["next"] == {"fork": "family", "output": ["results"], "prompt": None}
    assert shell["branches"]["submit"]["status"] == "ANSWERED"
    assert shell["branches"]["submit"]["accent"] == "#5FD7FF"
    assert shell["branches"]["submit"]["output"] == ["results"]
    assert shell["branches"]["submit"]["fork"] == "family"
    assert "Implement the feature." in shell["branches"]["submit"]["prompt"]
    assert shell["branches"]["timeout"] == {
        "status": "QUESTION TIMED OUT",
        "accent": "#FFAF00",
        "prompt": None,
    }
    assert shell["branches"]["stopped"] == {
        "status": "QUESTION CANCELLED",
        "accent": "#FFAF00",
        "prompt": None,
    }
    assert shell["branches"]["failed"] == {
        "status": "QUESTION FAILED",
        "accent": "#FF5F5F",
        "prompt": None,
    }


def test_shell_block_is_accepted_by_gate_shell_spec() -> None:
    spec = _question_gate_shell_spec(
        _questions(),
        session_id="round-1",
        base_prompt="Implement the feature.",
        prior_rounds=[],
    )

    parsed = GateShellSpec.from_mapping(spec["shell"], branches=(("submit",),))

    assert parsed.pending_status == "QUESTION"
    assert parsed.settled_status == "ANSWERED"
    assert set(parsed.branches) == {"submit", "timeout", "stopped", "failed"}


def test_default_timeout_is_24_hours() -> None:
    spec = _question_gate_shell_spec(
        _questions(),
        session_id="round-1",
        base_prompt="Implement the feature.",
        prior_rounds=[],
    )
    spec["request_id"] = "round-1"

    built = GateSpec.from_mapping(spec)

    assert built.gate_timeout_seconds == GATE_SHELL_DEFAULT_TIMEOUT_SECONDS


def _create_via_fake_transaction(
    monkeypatch: pytest.MonkeyPatch,
    *,
    session_id: str,
    prior_rounds: list[Any],
    parent_artifacts_dir: str | None,
    base_prompt: str,
    sdd_spec_path: str | None = None,
) -> GateShellCreation:
    """Exercise ``create_question_gate_shell`` without the creator-resolution path.

    ``create_gate_shell`` itself resolves the calling agent from
    ``SASE_AGENT_NAME``/``SASE_ARTIFACTS_DIR`` -- machinery already covered by
    ``tests/gate_shell/``. Faking it here isolates what this module owns: the
    request spec and the chain-metadata bookkeeping written after creation.
    """
    request = _question_gate_shell_spec(
        _questions(),
        session_id=session_id,
        base_prompt=base_prompt,
        prior_rounds=prior_rounds,
    )
    request["request_id"] = session_id
    gate = create_gate(request)
    shell = GateShellSpec.from_mapping(request["shell"], branches=(("submit",),))
    artifacts_dir = create_gate_shell_member(
        "proj",
        {"name": "lane--0", "agent_family": "lane"},
        lane="lane",
        suffix="--gate",
        prev_artifacts_timestamp="20260812120000",
        workspace_num=None,
        gate_id=session_id,
        gate_kind="question",
        label="Question",
        reason="wait for reviewer",
        creator_agent="lane--0",
        timeout_seconds=86400.0,
        request_fingerprint=None,
        shell=shell,
    )
    from sase.axe.run_agent_helpers_artifacts import update_meta_field

    update_meta_field(artifacts_dir, "gate_bundle_path", str(gate.bundle_path))

    from sase.gate_shell.store import read_gate_shell_marker

    record = read_gate_shell_marker("proj", artifacts_dir)
    assert record is not None
    fake_creation = GateShellCreation(
        gate=gate, record=record, project_file=None, claim_move=None, cl_name=None
    )

    def _fake_create_gate_shell(_request: Any) -> GateShellCreation:
        return fake_creation

    monkeypatch.setattr(
        "sase.question_shell.create.create_gate_shell", _fake_create_gate_shell
    )
    return create_question_gate_shell(
        _questions(),
        session_id=session_id,
        base_prompt=base_prompt,
        prior_rounds=prior_rounds,
        parent_artifacts_dir=parent_artifacts_dir,
        sdd_spec_path=sdd_spec_path,
    )


def test_round_one_writes_base_prompt_and_no_parent_link(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    creation = _create_via_fake_transaction(
        monkeypatch,
        session_id="round-1",
        prior_rounds=[],
        parent_artifacts_dir=None,
        base_prompt="Implement the feature.",
    )

    meta = json.loads(
        (Path(creation.record.artifacts_dir) / "agent_meta.json").read_text()
    )
    assert meta["question_round_index"] == 1
    assert "question_prev_artifacts_dir" not in meta
    base_prompt_path = Path(meta["question_base_prompt_path"])
    assert base_prompt_path.is_file()
    assert base_prompt_path.read_text(encoding="utf-8") == "Implement the feature."
    assert meta["question_session_id"] == "round-1"


def test_round_two_inherits_base_prompt_path_and_links_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _create_via_fake_transaction(
        monkeypatch,
        session_id="round-1",
        prior_rounds=[],
        parent_artifacts_dir=None,
        base_prompt="Implement the feature.",
    )

    second = _create_via_fake_transaction(
        monkeypatch,
        session_id="round-2",
        prior_rounds=[QARound()],
        parent_artifacts_dir=first.record.artifacts_dir,
        base_prompt="Implement the feature.",
    )

    parent_meta = json.loads(
        (Path(first.record.artifacts_dir) / "agent_meta.json").read_text()
    )
    child_meta = json.loads(
        (Path(second.record.artifacts_dir) / "agent_meta.json").read_text()
    )
    assert child_meta["question_round_index"] == 2
    assert child_meta["question_prev_artifacts_dir"] == first.record.artifacts_dir
    assert (
        child_meta["question_base_prompt_path"]
        == parent_meta["question_base_prompt_path"]
    )
