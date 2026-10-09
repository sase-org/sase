"""Gates decide through core ``evaluate()`` (``%auto`` E1 ``gates`` phase).

Every automatic gate outcome comes from one core ``evaluate()`` applied
to the creator's record snapshot. These tests pin the service surface:
the policy block on auto, ask, and manual gates; one decision-log row
per non-manual evaluation (including auto-answered questions); the
hand-built legacy translation; missing options asking instead of
partially executing; and the agent awareness block.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from . import harness


def _request_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _launch(prompt: str, workdir: Path) -> Path:
    """Run the real launch path and return its artifacts dir."""
    workdir.mkdir(parents=True, exist_ok=True)
    _, _, artifacts_dir = harness.launch_meta(prompt, workdir)
    return artifacts_dir


def _tale_plan(workdir: Path, name: str) -> Path:
    from tests.plan_validation_helpers import VALID_TALE_PLAN

    return harness.write_plan_file(workdir, name, VALID_TALE_PLAN)


def _epic_plan(workdir: Path, name: str) -> Path:
    from tests.plan_validation_helpers import VALID_EPIC_PLAN

    return harness.write_plan_file(workdir, name, VALID_EPIC_PLAN)


def _plan_gate(
    plan_file: Path,
    request_id: str,
    monkeypatch: Any,
    artifacts_dir: Path,
    *,
    auto_enabled: bool,
    auto_argument: str | None,
) -> Any:
    """Build a real plan spec from live meta and create the gate."""
    from sase.plan_gate import build_plan_approval_gate_spec

    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))
    spec = build_plan_approval_gate_spec(
        str(plan_file),
        request_id,
        auto_enabled=auto_enabled,
        auto_argument=auto_argument,
    )
    return harness.create_plan_gate_isolated(spec, artifacts_dir, request_id)


def _policy_of(gate: Any) -> dict[str, Any]:
    return (gate.to_dict().get("auto_resolution") or {}).get("policy") or {}


def _read_log(kind: str | None = None) -> list[dict[str, Any]]:
    from sase.core.paths import sase_home
    from sase.core.rust import require_rust_binding

    read = require_rust_binding("autonomy_read_decisions")
    query: dict[str, Any] = {"limit": 1000}
    if kind is not None:
        query["gate_kind"] = kind
    return list(read(str(sase_home()), query))


def test_auto_gate_carries_policy_block_everywhere(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """An auto-resolved gate carries its deciding block in all three files."""
    harness.isolated_gate_dirs(monkeypatch, tmp_path)
    workdir = tmp_path / "work"
    artifacts_dir = _launch("%auto:tale", workdir)
    plan = _tale_plan(workdir, "tale.md")
    request_id = _request_id("tale")

    gate = _plan_gate(
        plan,
        request_id,
        monkeypatch,
        artifacts_dir,
        auto_enabled=True,
        auto_argument="tale",
    )

    resolved = gate.to_dict().get("auto_resolution") or {}
    assert resolved["state"] == "resolved"
    assert resolved["selected_option_ids"] == ["approve", "commit"]
    policy = resolved["policy"]
    assert set(policy) == {
        "profile",
        "selection",
        "rule",
        "outcome",
        "value",
        "option_ids",
        "source",
        "revision",
        "digest",
    }
    assert policy["profile"] == "tale"
    assert policy["outcome"] == "auto"
    assert policy["value"] == "approve_archive"
    assert policy["option_ids"] == ["approve", "commit"]

    request = json.loads(gate.request_path.read_text(encoding="utf-8"))
    assert request["auto"]["policy"] == policy
    response = json.loads(gate.response_path.read_text(encoding="utf-8"))
    assert response["policy"] == policy


def test_cross_tier_ask_gate_carries_policy_block(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """A cross-tier argument parks as manual but still carries its block."""
    harness.isolated_gate_dirs(monkeypatch, tmp_path)
    workdir = tmp_path / "work"
    artifacts_dir = _launch("%auto:tale", workdir)
    plan = _epic_plan(workdir, "epic.md")
    request_id = _request_id("epic")

    gate = _plan_gate(
        plan,
        request_id,
        monkeypatch,
        artifacts_dir,
        auto_enabled=True,
        auto_argument="tale",
    )

    assert gate.notification_id is not None
    resolved = gate.to_dict().get("auto_resolution") or {}
    assert resolved["state"] == "disabled"
    assert resolved["selected_option_ids"] is None
    policy = resolved["policy"]
    assert policy["profile"] == "tale"
    assert policy["outcome"] == "ask"
    assert policy["rule"] == "gates.epic"
    request = json.loads(gate.request_path.read_text(encoding="utf-8"))
    assert request["auto"] == {
        "enabled": False,
        "argument": None,
        "policy": policy,
    }


def test_manual_gate_carries_manual_policy_block(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """A manual agent's gate asks with rule ``manual`` and no log row."""
    harness.isolated_gate_dirs(monkeypatch, tmp_path)
    workdir = tmp_path / "work"
    artifacts_dir = _launch("Do the work", workdir)
    plan = _tale_plan(workdir, "tale.md")
    request_id = _request_id("manual")
    before = len(_read_log())

    gate = _plan_gate(
        plan,
        request_id,
        monkeypatch,
        artifacts_dir,
        auto_enabled=False,
        auto_argument=None,
    )

    assert gate.notification_id is not None
    policy = _policy_of(gate)
    assert policy["profile"] == "manual"
    assert policy["outcome"] == "ask"
    assert policy["rule"] == "manual"
    assert len(_read_log()) == before


def test_non_manual_evaluations_log_one_row_including_questions(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """Auto and ask evaluations log exactly one row each; manual logs none."""
    harness.isolated_gate_dirs(monkeypatch, tmp_path)
    workdir = tmp_path / "work"
    artifacts_dir = _launch("%auto:tale", workdir)
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))

    _plan_gate(
        _tale_plan(workdir, "tale.md"),
        _request_id("tale"),
        monkeypatch,
        artifacts_dir,
        auto_enabled=True,
        auto_argument="tale",
    )
    rows = _read_log()
    tale_rows = [row for row in rows if row["gate_kind"] == "plan"]
    assert len(tale_rows) == 1
    assert tale_rows[0]["creator_role"] == "top_level"
    assert tale_rows[0]["decision"]["outcome"] == "auto"

    from sase.user_question_actions import user_question_gate_spec

    question_id = _request_id("q")
    spec = user_question_gate_spec(
        [dict(question) for question in harness.QUESTIONS],
        session_id=question_id,
        producer={"agent": "contract-agent"},
        auto=True,
    )
    from sase.notification_gates.service import create_gate

    question_gate = create_gate(spec)
    assert (question_gate.to_dict().get("auto_resolution") or {})["state"] == (
        "resolved"
    )
    question_rows = _read_log("question")
    assert len(question_rows) == 1
    assert question_rows[0]["decision"]["outcome"] == "auto"

    _plan_gate(
        _epic_plan(workdir, "epic.md"),
        _request_id("epic"),
        monkeypatch,
        artifacts_dir,
        auto_enabled=True,
        auto_argument="tale",
    )
    ask_rows = [
        row for row in _read_log("epic_plan") if row["decision"]["outcome"] == "ask"
    ]
    assert len(ask_rows) == 1


def test_creator_role_follows_agent_meta(tmp_path: Path, monkeypatch: Any) -> None:
    """Bead workers log as epic workers; workflow agents as workflow."""
    from sase.autonomy.gates import _creator_role_for_meta as creator_role_for_meta

    assert creator_role_for_meta({"phase_bead_id": "sase-1ip.6"}) == "epic_worker"
    assert creator_role_for_meta({"epic_bead_id": "sase-1ip"}) == "epic_worker"
    assert creator_role_for_meta({"workflow_name": "review"}) == "workflow"
    assert creator_role_for_meta({"name": "plain"}) == "top_level"
    assert creator_role_for_meta({}) == "top_level"
    assert creator_role_for_meta(None) == "top_level"

    harness.isolated_gate_dirs(monkeypatch, tmp_path)
    workdir = tmp_path / "work"
    artifacts_dir = _launch("%auto:tale", workdir)
    meta = harness.read_meta(artifacts_dir)
    meta["phase_bead_id"] = "sase-1ip.6"
    meta["name"] = "phase-worker"
    harness.write_meta(artifacts_dir, meta)
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))

    from sase.plan_gate import build_plan_approval_gate_spec

    spec = build_plan_approval_gate_spec(
        str(_tale_plan(workdir, "tale.md")),
        _request_id("worker"),
        auto_enabled=True,
        auto_argument="tale",
    )
    spec["producer"] = {"agent": "phase-worker", "artifacts_dir": str(artifacts_dir)}
    harness.create_plan_gate_isolated(spec, artifacts_dir, spec["request_id"])
    rows = _read_log("plan")
    assert rows and rows[0]["creator_role"] == "epic_worker"
    assert rows[0]["agent"] == "phase-worker"


def test_hand_built_legacy_spec_resolves_and_invalid_stays_error(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """A spec with only ``enabled``/``argument`` translates through core."""
    from sase.notification_gates.models import GateError, GateSpec
    from sase.notification_gates.service import create_gate
    from sase.notifications.store import load_notifications
    from sase.plan_gate import build_plan_approval_gate_spec

    harness.isolated_gate_dirs(monkeypatch, tmp_path)
    workdir = tmp_path / "work"
    workdir.mkdir(parents=True, exist_ok=True)
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)

    base = build_plan_approval_gate_spec(
        str(_tale_plan(workdir, "tale.md")),
        _request_id("legacy"),
        auto_enabled=True,
        auto_argument="tale",
    )
    assert base["auto"]["enabled"] is True
    gate = harness.create_plan_gate_isolated(
        GateSpec.from_mapping(base), workdir, base["request_id"]
    )
    assert (gate.to_dict().get("auto_resolution") or {})["selected_option_ids"] == [
        "approve",
        "commit",
    ]

    for bad_argument in ("foo", "epic_plan"):
        bad = dict(base)
        bad["request_id"] = _request_id("bad")
        bad["auto"] = {"enabled": True, "argument": bad_argument}
        with patch(
            "sase.plan_approval_actions._archive_plan_for_approval",
            return_value=str(workdir / "archived.md"),
        ):
            try:
                create_gate(GateSpec.from_mapping(bad))
            except GateError as exc:
                assert exc.code == "invalid_auto_argument"
            else:
                raise AssertionError(
                    f"expected invalid_auto_argument for {bad_argument!r}"
                )
    assert load_notifications(include_dismissed=True) == []


def test_missing_option_asks_never_partially(tmp_path: Path, monkeypatch: Any) -> None:
    """A gate that cannot run the whole selection waits for a human."""
    from sase.autonomy.gates import evaluate_gate
    from sase.autonomy.record import resolve_selection

    harness.isolated_gate_dirs(monkeypatch, tmp_path)
    tale = resolve_selection("tale", source="prompt", surface="launch")
    decision = evaluate_gate(tale, gate_kind="plan", option_ids=["approve"])
    assert decision["outcome"] == "ask"
    assert decision["rule"] == "missing_options"
    assert decision["option_ids"] == []

    epic = resolve_selection("epic", source="prompt", surface="launch")
    whole = evaluate_gate(epic, gate_kind="epic_plan", option_ids=["approve"])
    assert whole["outcome"] == "auto"
    assert whole["option_ids"] == ["approve"]

    # Option order never matters: the selection comes back canonical.
    reordered = evaluate_gate(tale, gate_kind="plan", option_ids=["commit", "approve"])
    assert reordered["outcome"] == "auto"
    assert reordered["option_ids"] == ["approve", "commit"]


def _write_autonomy_meta(artifacts_dir: Path, selection: str | None) -> None:
    """Write a live ``agent_meta.json`` with the record for *selection*."""
    from sase.autonomy.record import resolve_selection

    record = resolve_selection(selection, source="prompt", surface="launch")
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps({"name": "hook-agent", "autonomy": record}), encoding="utf-8"
    )


def test_awareness_block_per_profile_once_and_live(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """The block shows for auto profiles, never for manual, once per turn."""
    from sase.autonomy.gates import AWARENESS_MARKER, with_awareness_block

    harness.isolated_gate_dirs(monkeypatch, tmp_path)
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()

    for selection in ("", "tale", "epic"):
        _write_autonomy_meta(artifacts_dir, selection)
        block_prompt = with_awareness_block("Do the work", artifacts_dir)
        assert AWARENESS_MARKER in block_prompt
        assert "covers host checkpoints only" in block_prompt
        assert "shell is not restricted" in block_prompt
        # Never accumulates across successors or retries.
        assert with_awareness_block(block_prompt, artifacts_dir) == block_prompt

    _write_autonomy_meta(artifacts_dir, None)
    assert with_awareness_block("Do the work", artifacts_dir) == "Do the work"

    # The block is read live: a toggle shows up on the next turn.
    _write_autonomy_meta(artifacts_dir, None)
    assert AWARENESS_MARKER not in with_awareness_block("Do x", artifacts_dir)
    _write_autonomy_meta(artifacts_dir, "tale")
    toggled = with_awareness_block("Do x", artifacts_dir)
    assert AWARENESS_MARKER in toggled
    assert "tale" in toggled


def _run_prompt_step(tmp_path: Path, *, anonymous: bool, selection: str | None) -> str:
    """Run one real prompt step with a stubbed provider; return its prompt."""
    import sase.macro.workflow_executor_steps_prompt as prompt_module
    from sase.macro.directives import PromptDirectives
    from sase.macro.workflow_executor import WorkflowExecutor
    from sase.macro.workflow_executor_steps_prompt_prepare import (
        _PreparedPromptStep,
    )
    from sase.macro.workflow_models import StepState, Workflow, WorkflowStep

    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    _write_autonomy_meta(artifacts_dir, selection)
    workflow = Workflow(
        name="anonymous" if anonymous else "helper",
        steps=[WorkflowStep(name="main", agent="Do the work")],
        is_anonymous_workflow=anonymous,
    )
    executor = WorkflowExecutor(
        workflow=workflow, args={}, artifacts_dir=str(artifacts_dir)
    )
    prepared = _PreparedPromptStep(
        expanded_prompt="Do the work",
        effective_directives=PromptDirectives(),
        embedded_workflows=[],
        pre_step_count=0,
        pre_step_meta={},
        authored_local_request="Do the work",
        continuation_segments=(),
    )
    seen: dict[str, str] = {}
    fake_response = SimpleNamespace(content="done")

    def _capture(prompt: str, **kwargs: Any) -> Any:
        seen["prompt"] = prompt
        return fake_response

    with (
        patch.object(WorkflowExecutor, "_prepare_prompt_step", return_value=prepared),
        patch.object(
            prompt_module,
            "resolve_prompt_step_launch_selection",
            return_value=SimpleNamespace(
                model="m",
                provider="p",
                reasoning_effort=None,
                alias_trail=[],
                alias_origin=None,
            ),
        ),
        patch.object(
            prompt_module,
            "update_root_agent_meta_from_launch",
            return_value=None,
        ),
        patch("sase.llm_provider.invoke_agent", side_effect=_capture),
        patch(
            "sase.macro.workflow_executor_steps_prompt.capture_vcs_diff",
            return_value="",
        ),
        patch(
            "sase.history.chat.save_chat_history",
            return_value=str(artifacts_dir / "chat.md"),
        ),
    ):
        assert (
            executor._execute_prompt_step(workflow.steps[0], StepState(name="main"))
            is True
        )
    return seen["prompt"]


def test_awareness_hook_only_on_root_agent_turns(tmp_path: Path) -> None:
    """Anonymous (root) turns get the block; helper workflows get none."""
    from sase.autonomy.gates import AWARENESS_MARKER

    root_prompt = _run_prompt_step(tmp_path, anonymous=True, selection="tale")
    assert AWARENESS_MARKER in root_prompt

    helper_dir = tmp_path / "helper"
    helper_dir.mkdir()
    helper_prompt = _run_prompt_step(helper_dir, anonymous=False, selection="tale")
    assert AWARENESS_MARKER not in helper_prompt

    manual_dir = tmp_path / "manual"
    manual_dir.mkdir()
    manual_prompt = _run_prompt_step(manual_dir, anonymous=True, selection=None)
    assert AWARENESS_MARKER not in manual_prompt
