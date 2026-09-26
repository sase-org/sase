"""Focused edit-capacity tests for the queue multiplier (<M>x)."""

from __future__ import annotations

import json
from pathlib import Path

from sase.ace.tui.actions.agents._directive_persistence import (
    persist_agent_directive_update,
    AgentDirectivePersistenceSpec,
    wait_meta_patch_for_token,
    waiting_marker_patch_for_token,
)
from sase.ace.tui.modals.wait_modal_types import WaitModalResult
from sase.ace.tui.modals.wait_modal_values import (
    prefill_capacity_token,
    validate_capacity_token,
)
from sase.ace.tui.actions.agents._wait_helpers import (
    prompt_wait_spec,
    result_has_wait_spec,
    wait_spec_label,
)
from sase.ops.commands._agent_directive import (
    _capacity_multiplier_from_payload,
    _capacity_pair_from_payload,
    persist_directive_from_payload,
)
from sase.xprompt.directive_edit import (
    PromptWaitDirective,
    set_prompt_queue,
    set_prompt_wait_and_queue,
)
from sase.xprompt.directives import extract_prompt_directives


def test_modal_accepts_multiplier_and_prefills_authored_form() -> None:
    valid = validate_capacity_token("1.5x")
    assert valid.valid is True
    assert valid.value is None
    assert valid.multiplier == 1.5
    assert "1.5x" in valid.message

    assert prefill_capacity_token(None, 1.5) == "1.5x"
    assert prefill_capacity_token(3, None) == "3"
    assert prefill_capacity_token(None, None) == ""
    # Integer still explicit-clears the multiplier form.
    assert prefill_capacity_token(None, 2.0) == "2x"


def test_modal_rejects_bad_multiplier_and_keeps_integer_rules() -> None:
    assert validate_capacity_token("1.125x").valid is False
    assert validate_capacity_token("0x").valid is False
    assert validate_capacity_token("1.5").valid is False
    zero = validate_capacity_token("0")
    assert zero.valid is False
    assert "must be at least 1" in zero.message
    run_alone = validate_capacity_token("1")
    assert run_alone.valid is True
    assert run_alone.value == 1


def test_modal_result_carries_multiplier_through_helpers() -> None:
    result = WaitModalResult(
        agents=[],
        time_token=None,
        capacity=None,
        capacity_multiplier=1.5,
    )
    assert result_has_wait_spec(result) is True
    assert "1.5x" in wait_spec_label(result)
    spec = prompt_wait_spec(result)
    assert spec is not None
    assert spec.capacity is None
    assert spec.capacity_multiplier == 1.5


def test_prompt_queue_accepts_multiplier_and_clears_integer() -> None:
    rewritten = set_prompt_queue(
        "%q(capacity=3)\nDo work",
        capacity=None,
        priority=None,
        capacity_multiplier=1.5,
    )
    _, directives = extract_prompt_directives(rewritten)
    assert directives.queue_capacity_multiplier == 1.5
    assert directives.wait_runners is None
    assert "1.5x" in rewritten

    cleared = set_prompt_queue(
        "%q(1.5x)\nDo work",
        capacity=3,
        priority=None,
    )
    _, cleared_directives = extract_prompt_directives(cleared)
    assert cleared_directives.wait_runners == 3
    assert cleared_directives.queue_capacity_multiplier is None


def test_prompt_edits_preserve_multiplier_on_priority_or_weight_only() -> None:
    priority_only = set_prompt_wait_and_queue(
        "%q(1.5x, w=0.25)\n%wait:old\nDo work",
        PromptWaitDirective(agents=("dep",), priority=20),
    )
    _, directives = extract_prompt_directives(priority_only)
    assert directives.queue_capacity_multiplier == 1.5
    assert directives.queue_weight == 0.25
    assert directives.wait_priority == 20

    weight_only = set_prompt_queue(
        "%q(1.5x, w=0.25)\nDo work",
        capacity=None,
        priority=None,
        weight=0.5,
    )
    _, weight_directives = extract_prompt_directives(weight_only)
    assert weight_directives.queue_capacity_multiplier == 1.5
    assert weight_directives.queue_weight == 0.5


def test_capacity_pair_reads_multiplier_and_string_forms() -> None:
    assert _capacity_pair_from_payload({"capacity": "1.5x"}) == (None, 1.5)
    assert _capacity_pair_from_payload({"capacity": 3}) == (3, None)
    assert _capacity_pair_from_payload({"queue_capacity_multiplier": 1.5}) == (
        None,
        1.5,
    )
    assert _capacity_multiplier_from_payload({"capacity": "2x"}) == 2.0


def test_persistence_patches_keep_forms_mutually_exclusive(tmp_path: Path) -> None:
    multiplier_patch = wait_meta_patch_for_token(
        update_wait_runners=True,
        queue_capacity_multiplier=1.5,
    )
    assert multiplier_patch.set_values["queue_capacity_multiplier"] == 1.5
    assert "queue_capacity" not in multiplier_patch.set_values
    assert "queue_capacity_multiplier" in multiplier_patch.remove_keys

    integer_patch = wait_meta_patch_for_token(
        update_wait_runners=True,
        wait_runners=3,
    )
    assert integer_patch.set_values["queue_capacity"] == 3
    assert "queue_capacity_multiplier" not in integer_patch.set_values

    marker = waiting_marker_patch_for_token(
        update_wait_runners=True,
        queue_capacity_multiplier=1.5,
    )
    assert marker.queue_capacity_multiplier == 1.5
    assert marker.wait_runners is None


def test_persist_directive_round_trips_multiplier_and_clears_integer(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "raw_xprompt.md").write_text(
        "%q(capacity=2)\nDo work", encoding="utf-8"
    )
    (artifacts / "agent_meta.json").write_text("{}", encoding="utf-8")

    persist_agent_directive_update(
        AgentDirectivePersistenceSpec(
            artifacts_dir=artifacts,
            prompt_mutator=lambda prompt: set_prompt_queue(
                prompt,
                capacity=None,
                priority=None,
                capacity_multiplier=1.5,
            ),
            meta_patch=wait_meta_patch_for_token(
                update_wait_runners=True,
                queue_capacity_multiplier=1.5,
            ),
            waiting_marker=waiting_marker_patch_for_token(
                update_wait_runners=True,
                queue_capacity_multiplier=1.5,
            ),
        )
    )
    assert "1.5x" in (artifacts / "raw_xprompt.md").read_text(encoding="utf-8")
    meta = json.loads((artifacts / "agent_meta.json").read_text(encoding="utf-8"))
    assert meta["queue_capacity_multiplier"] == 1.5
    assert "queue_capacity" not in meta
    waiting = json.loads((artifacts / "waiting.json").read_text(encoding="utf-8"))
    assert waiting["queue_capacity_multiplier"] == 1.5
    assert "queue_capacity" not in waiting


def test_agent_directive_command_persists_multiplier(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "raw_xprompt.md").write_text("Do work", encoding="utf-8")
    (artifacts / "agent_meta.json").write_text("{}", encoding="utf-8")

    persist_directive_from_payload(
        {
            "prompt": {
                "kind": "set_wait",
                "wait": {"agents": ["dep"], "capacity": "1.5x"},
            },
            "wait": {
                "names": ["dep"],
                "update_wait_runners": True,
                "queue_capacity": "1.5x",
            },
            "waiting": {
                "names": ["dep"],
                "update_wait_runners": True,
                "queue_capacity": "1.5x",
            },
        },
        artifacts_dir=str(artifacts),
    )
    assert "1.5x" in (artifacts / "raw_xprompt.md").read_text(encoding="utf-8")
    meta = json.loads((artifacts / "agent_meta.json").read_text(encoding="utf-8"))
    assert meta["queue_capacity_multiplier"] == 1.5
