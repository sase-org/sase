"""Cross-kind mixed Agent/Proc launch-matrix coverage for Phase 8 verification.

Existing coordinator tests in ``test_launch_admission.py`` exercise each admission
behavior (skip propagation, condition errors, crash recovery, cancellation, proc
dispatch) in isolation, one unit kind at a time. These tests combine Agent and Proc
units in a single plan — skipped predecessors, condition errors, forward waits,
external time waits, partial launch failure, and documented prompt forms — and assert
that the coordinator summary, per-unit results, persisted receipt, and notification
text agree on outcomes and counts.
"""

from __future__ import annotations

import json
import stat
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sase.agent.launch_admission import dispatch_typed_launch_request
from sase.agent.launch_request_types import LaunchRequestError
from sase.agent.launch_types import AgentLaunchResult
from sase.core.agent_launch_facade import (
    plan_typed_launch_units,
    prepare_proc_script,
    proc_script_argv,
)
from sase.core.agent_launch_wire import (
    AgentUnitWire,
    LaunchConditionWire,
    LaunchPlanWire,
    LaunchUnitWire,
    ProcUnitWire,
    WaitTargetWire,
    agent_launch_wire_to_json_dict,
)
from sase.feature_flags import override_flags
from sase.xprompt.code_value import CodeValue, make_code_value
from sase.xprompt.directives import DirectiveError, extract_prompt_directives


def _agent_result(tmp_path: Path, name: str) -> AgentLaunchResult:
    return AgentLaunchResult(
        pid=321,
        workspace_num=2,
        workspace_dir=str(tmp_path / "ws" / name),
        output_path=str(tmp_path / f"{name}.log"),
        agent_name=name,
    )


def _code() -> CodeValue:
    return CodeValue(
        source="true",
        language="bash",
        info_string=None,
        digest="c" * 64,
        preview="true",
    )


def _plan(*units: LaunchUnitWire) -> LaunchPlanWire:
    return LaunchPlanWire(
        schema_version=1,
        launch_kind="multi_prompt",
        selected_project="sase",
        content_digest="d" * 64,
        units=list(units),
        approval_preview=["LaunchPlan v1"],
    )


def _run_plan(
    tmp_path: Path,
    plan: LaunchPlanWire,
    *,
    request_id: str,
    include_digest: bool = False,
    **kwargs: Any,
) -> tuple[Any, Path]:
    response_dir = tmp_path / "bundle"
    response_dir.mkdir(exist_ok=True)
    payload: dict[str, Any] = {
        "request_id": request_id,
        "typed_plan": agent_launch_wire_to_json_dict(plan),
        "dispatch": {"cwd": str(tmp_path), "prompt": "Do work"},
    }
    if include_digest:
        payload["plan_digest"] = plan.content_digest
    result = dispatch_typed_launch_request(
        response_dir,
        payload,
        spawn_coordinator=False,
        **kwargs,
    )
    return result, response_dir


def _receipt(response_dir: Path) -> dict[str, Any]:
    return json.loads(
        (response_dir / "launch_admission" / "receipt.json").read_text(encoding="utf-8")
    )


def _assert_receipt_agrees(
    progress: Any, response_dir: Path, plan: LaunchPlanWire
) -> None:
    summary = progress.summary
    assert summary is not None
    receipt = _receipt(response_dir)
    assert receipt["plan_digest"] == plan.content_digest
    assert receipt["summary"] == {
        "total": summary.total,
        "eligible": summary.eligible,
        "launched": summary.launched,
        "skipped": summary.skipped,
        "condition_errors": summary.condition_errors,
        "launch_errors": summary.launch_errors,
    }
    receipt_outcomes = {
        entry["logical_id"]: entry["outcome"] for entry in receipt["units"]
    }
    live_outcomes = {
        result.logical_id: result.outcome for result in progress.unit_results
    }
    assert receipt_outcomes == live_outcomes


def test_full_mixed_matrix_chain_agrees_across_summary_and_receipt(
    tmp_path: Path,
) -> None:
    """Agent + Proc units chained through skip, condition-error, and a forward wait.

    Graph (declared out of dependency order to exercise forward references):

    - unit-1 (Agent, conditioned): predicate settles ``skipped``.
    - unit-2 (Proc): waits on unit-1 (a skipped predecessor still satisfies a wait).
    - unit-3 (Agent): waits on unit-2, so an Agent depends on a Proc.
    - unit-4 (Proc): waits on unit-6, a *forward* reference to a unit declared later.
    - unit-5 (Proc, conditioned): predicate settles ``condition_error``, isolated.
    - unit-6 (Proc): no dependencies; declared last but targeted by unit-4.
    """

    pytest.importorskip("sase_core_rs")

    def evaluator(
        unit: LaunchUnitWire, waited: Any, context: Any
    ) -> tuple[str, str | None]:
        del waited, context
        if unit.logical_id == "unit-1":
            return "skipped", "predicate exited 1"
        if unit.logical_id == "unit-5":
            return "condition_error", "predicate exited 2"
        return "eligible", None

    agent_calls: list[str] = []
    proc_calls: list[str] = []

    def agent_dispatcher(
        unit: LaunchUnitWire, fingerprint: str
    ) -> tuple[bool, str | None, str | None, list[AgentLaunchResult]]:
        del fingerprint
        agent_calls.append(unit.logical_id)
        return (
            True,
            unit.logical_id,
            None,
            [_agent_result(tmp_path, unit.logical_id)],
        )

    def proc_dispatcher(
        unit: LaunchUnitWire, fingerprint: str
    ) -> tuple[bool, str | None, str | None, list[AgentLaunchResult]]:
        del fingerprint
        proc_calls.append(unit.logical_id)
        return True, f"proc-{unit.logical_id}", None, []

    plan = _plan(
        LaunchUnitWire(
            logical_id="unit-1",
            source_order=0,
            payload=AgentUnitWire(prompt="First"),
            condition=LaunchConditionWire(code=_code()),
        ),
        LaunchUnitWire(
            logical_id="unit-2",
            source_order=1,
            payload=ProcUnitWire(code=_code(), workspace=False, cwd=str(tmp_path)),
            waits=[WaitTargetWire(kind="logical", logical_id="unit-1", source="%wait")],
        ),
        LaunchUnitWire(
            logical_id="unit-3",
            source_order=2,
            payload=AgentUnitWire(prompt="Third"),
            waits=[WaitTargetWire(kind="logical", logical_id="unit-2", source="%wait")],
        ),
        LaunchUnitWire(
            logical_id="unit-4",
            source_order=3,
            payload=ProcUnitWire(code=_code(), workspace=False, cwd=str(tmp_path)),
            waits=[
                WaitTargetWire(
                    kind="logical", logical_id="unit-6", source="%wait(unit=unit-6)"
                )
            ],
        ),
        LaunchUnitWire(
            logical_id="unit-5",
            source_order=4,
            payload=ProcUnitWire(code=_code(), workspace=False, cwd=str(tmp_path)),
            condition=LaunchConditionWire(code=_code()),
        ),
        LaunchUnitWire(
            logical_id="unit-6",
            source_order=5,
            payload=ProcUnitWire(code=_code(), workspace=False, cwd=str(tmp_path)),
        ),
    )

    with patch("sase.notifications.senders.notify_workflow_complete") as notify:
        progress, response_dir = _run_plan(
            tmp_path,
            plan,
            request_id="req-mixed-matrix",
            include_digest=True,
            condition_evaluator=evaluator,
            agent_dispatcher=agent_dispatcher,
            proc_dispatcher=proc_dispatcher,
        )

    assert progress.admission_complete
    summary = progress.summary
    assert summary is not None
    assert summary.total == 6
    assert summary.skipped == 1
    assert summary.condition_errors == 1
    assert summary.launched == 4
    assert summary.launch_errors == 0

    outcomes = {result.logical_id: result.outcome for result in progress.unit_results}
    assert outcomes == {
        "unit-1": "skipped",
        "unit-2": "launched",
        "unit-3": "launched",
        "unit-4": "launched",
        "unit-5": "condition_error",
        "unit-6": "launched",
    }

    # Forward reference: unit-4 dispatched only after unit-6 (declared after it)
    # settled, even though unit-6 was reached later in the journal.
    assert proc_calls.index("unit-6") < proc_calls.index("unit-4")
    # A skipped predecessor never retargets or blocks its dependent's dispatch.
    assert "unit-2" in proc_calls
    assert set(agent_calls) == {"unit-3"}
    assert set(proc_calls) == {"unit-2", "unit-4", "unit-6"}

    _assert_receipt_agrees(progress, response_dir, plan)
    notify.assert_called_once()
    notes = notify.call_args.kwargs["notes"]
    assert "6 total" in notes[1]
    assert "4 launched" in notes[1]
    assert "1 skipped" in notes[1]
    assert "1 condition error(s)" in notes[1]
    extra_files = notify.call_args.kwargs["extra_files"]
    assert extra_files == [str(response_dir / "launch_admission" / "receipt.json")]


def test_mixed_partial_success_keeps_launched_identities(tmp_path: Path) -> None:
    pytest.importorskip("sase_core_rs")
    agent_ids: list[str] = []

    def agent_dispatcher(
        unit: LaunchUnitWire, fingerprint: str
    ) -> tuple[bool, str | None, str | None, list[AgentLaunchResult]]:
        del fingerprint
        agent_ids.append(unit.logical_id)
        return True, unit.logical_id, None, [_agent_result(tmp_path, unit.logical_id)]

    def proc_dispatcher(
        unit: LaunchUnitWire, fingerprint: str
    ) -> tuple[bool, str | None, str | None, list[AgentLaunchResult]]:
        del unit, fingerprint
        return False, None, "spawn failed", []

    plan = _plan(
        LaunchUnitWire(
            logical_id="unit-1",
            source_order=0,
            payload=AgentUnitWire(prompt="First"),
        ),
        LaunchUnitWire(
            logical_id="unit-2",
            source_order=1,
            payload=ProcUnitWire(code=_code(), workspace=False, cwd=str(tmp_path)),
            waits=[WaitTargetWire(kind="logical", logical_id="unit-1", source="%wait")],
        ),
    )
    progress, response_dir = _run_plan(
        tmp_path,
        plan,
        request_id="req-mixed-partial",
        include_digest=True,
        agent_dispatcher=agent_dispatcher,
        proc_dispatcher=proc_dispatcher,
    )
    assert progress.summary is not None
    assert progress.summary.launched == 1
    assert progress.summary.launch_errors == 1
    assert agent_ids == ["unit-1"]
    outcomes = {result.logical_id: result.outcome for result in progress.unit_results}
    assert outcomes == {"unit-1": "launched", "unit-2": "launch_error"}
    _assert_receipt_agrees(progress, response_dir, plan)


def test_external_time_wait_resolves_without_resources(tmp_path: Path) -> None:
    pytest.importorskip("sase_core_rs")
    plan = _plan(
        LaunchUnitWire(
            logical_id="unit-1",
            source_order=0,
            payload=ProcUnitWire(code=_code(), workspace=False, cwd=str(tmp_path)),
            waits=[WaitTargetWire(kind="time", value="0s", source="%wait(time=0s)")],
        )
    )
    with (
        patch("sase.running_field.claim_workspace") as claim_workspace,
        patch("sase.procs.store.reserve_proc") as reserve_proc,
    ):
        progress, response_dir = _run_plan(
            tmp_path,
            plan,
            request_id="req-time-wait",
            proc_dispatcher=lambda unit, fingerprint: (
                True,
                "proc-time",
                None,
                [],
            ),
        )
    assert progress.admission_complete
    assert progress.summary is not None
    assert progress.summary.launched == 1
    claim_workspace.assert_not_called()
    reserve_proc.assert_not_called()
    _assert_receipt_agrees(progress, response_dir, plan)


def test_cancel_after_first_mixed_unit_preserves_launched(tmp_path: Path) -> None:
    pytest.importorskip("sase_core_rs")
    cancelled = False

    def agent_dispatcher(
        unit: LaunchUnitWire, fingerprint: str
    ) -> tuple[bool, str | None, str | None, list[AgentLaunchResult]]:
        nonlocal cancelled
        del fingerprint
        cancelled = True
        return True, unit.logical_id, None, [_agent_result(tmp_path, unit.logical_id)]

    plan = _plan(
        LaunchUnitWire(
            logical_id="unit-1",
            source_order=0,
            payload=AgentUnitWire(prompt="First"),
        ),
        LaunchUnitWire(
            logical_id="unit-2",
            source_order=1,
            payload=ProcUnitWire(code=_code(), workspace=False, cwd=str(tmp_path)),
            waits=[WaitTargetWire(kind="logical", logical_id="unit-1", source="%wait")],
        ),
    )
    progress, response_dir = _run_plan(
        tmp_path,
        plan,
        request_id="req-mixed-cancel",
        cancelled=lambda: cancelled,
        agent_dispatcher=agent_dispatcher,
        proc_dispatcher=lambda unit, fingerprint: (True, "proc-late", None, []),
    )
    assert progress.summary is not None
    assert progress.summary.launched == 1
    assert progress.summary.launch_errors == 1
    outcomes = {result.logical_id: result.outcome for result in progress.unit_results}
    assert outcomes["unit-1"] == "launched"
    assert outcomes["unit-2"] == "launch_error"
    _assert_receipt_agrees(progress, response_dir, plan)


def test_repeat_and_alt_produce_stable_mixed_units() -> None:
    pytest.importorskip("sase_core_rs")
    with override_flags(typed_launch_units=True):
        repeated = plan_typed_launch_units(
            '%repeat:2\n%proc("echo ready")',
            selected_project="sase",
        )
        mixed_alt = plan_typed_launch_units(
            '%{%proc("echo left") | %id:reviewer\nReview}',
            selected_project="sase",
        )
        fanout = plan_typed_launch_units(
            '%proc("echo first")\n---\n%wait\n%id:reviewer\nReview',
            launch_kind="multi_prompt",
            selected_project="sase",
        )

    assert len(repeated.units) == 2
    assert all(isinstance(unit.payload, ProcUnitWire) for unit in repeated.units)
    assert [unit.logical_id for unit in repeated.units] == ["unit-1", "unit-2"]
    assert mixed_alt.units
    kinds = {type(unit.payload) for unit in mixed_alt.units}
    assert AgentUnitWire in kinds
    assert ProcUnitWire in kinds
    assert isinstance(fanout.units[0].payload, ProcUnitWire)
    assert isinstance(fanout.units[1].payload, AgentUnitWire)
    assert fanout.units[1].waits[0].kind == "logical"
    assert fanout.units[1].waits[0].logical_id == fanout.units[0].logical_id
    assert fanout.units[0].logical_id != fanout.units[1].logical_id


def test_documented_typed_launch_forms_plan_and_flag_off_rejects() -> None:
    pytest.importorskip("sase_core_rs")
    examples = [
        "%if::\n\n```bash\ntest -f pyproject.toml\n```\nReview",
        '%proc("just check")',
        '%proc(python="print(\'ready\')", timeout="20m", label="Preflight")',
        (
            '%proc(timeout="20m", idle_timeout="5m", cwd="docs", workspace="true")::\n\n'
            "```bash\njust docs-check\n```\n"
        ),
    ]
    for prompt in examples:
        with pytest.raises(DirectiveError, match="typed_launch_units"):
            extract_prompt_directives(prompt)
        with pytest.raises(DirectiveError, match="typed_launch_units"):
            plan_typed_launch_units(prompt, selected_project="sase")

    with override_flags(typed_launch_units=True):
        conditioned = plan_typed_launch_units(examples[0], selected_project="sase")
        positional = plan_typed_launch_units(examples[1], selected_project="sase")
        named = plan_typed_launch_units(examples[2], selected_project="sase")
        fenced = plan_typed_launch_units(examples[3], selected_project="sase")

    assert isinstance(conditioned.units[0].payload, AgentUnitWire)
    assert conditioned.units[0].condition is not None
    assert conditioned.units[0].condition.code.language == "bash"
    assert "test -f pyproject.toml" in conditioned.units[0].condition.code.source
    assert isinstance(positional.units[0].payload, ProcUnitWire)
    assert positional.units[0].payload.code.source == "just check"
    assert isinstance(named.units[0].payload, ProcUnitWire)
    assert named.units[0].payload.code.language == "python"
    assert named.units[0].payload.timeout == "20m"
    assert named.units[0].payload.label == "Preflight"
    assert isinstance(fenced.units[0].payload, ProcUnitWire)
    assert fenced.units[0].payload.workspace is True
    assert fenced.units[0].payload.cwd == "docs"
    assert fenced.units[0].payload.timeout == "20m"
    assert fenced.units[0].payload.idle_timeout == "5m"
    assert "just docs-check" in fenced.units[0].payload.code.source


def test_plan_digest_mismatch_is_rejected(tmp_path: Path) -> None:
    pytest.importorskip("sase_core_rs")
    plan = _plan(
        LaunchUnitWire(
            logical_id="unit-1",
            source_order=0,
            payload=AgentUnitWire(prompt="First"),
        )
    )
    response_dir = tmp_path / "bundle"
    response_dir.mkdir()
    with pytest.raises(LaunchRequestError, match="plan digest") as exc:
        dispatch_typed_launch_request(
            response_dir,
            {
                "request_id": "req-digest",
                "plan_digest": "0" * 64,
                "typed_plan": agent_launch_wire_to_json_dict(plan),
                "dispatch": {"cwd": str(tmp_path), "prompt": "Do work"},
            },
            spawn_coordinator=False,
            agent_dispatcher=lambda unit, fingerprint: (
                True,
                "reviewer",
                None,
                [_agent_result(tmp_path, "reviewer")],
            ),
        )
    assert exc.value.code == "plan_digest_mismatch"
    assert not (response_dir / "launch_admission" / "receipt.json").exists()


def test_proc_script_argv_is_not_interpolated_from_source(tmp_path: Path) -> None:
    pytest.importorskip("sase_core_rs")
    from sase.core.agent_launch_facade import proc_dispatch_wire_schema_version

    work = tmp_path / "work"
    work.mkdir()
    hostile = 'echo ready; rm -rf /; $(reboot); `id`; echo "$HOME"'
    code = make_code_value(hostile, "bash", "bash")
    prepared = prepare_proc_script(
        {
            "schema_version": proc_dispatch_wire_schema_version(),
            "logical_id": "unit-1",
            "fingerprint": "fp",
            "code": {
                "schema_version": 1,
                "source": code.source,
                "language": code.language,
                "digest": code.digest,
                "preview": code.preview,
            },
            "work_dir": str(work),
            "python_executable": sys.executable,
            "workspace": False,
            "declared_cwd": str(tmp_path),
            "source_cwd": str(tmp_path),
            "proc_id": "proc-argv",
        }
    )
    argv = list(prepared["argv"])
    assert argv[:3] == ["/bin/bash", "--noprofile", "--norc"]
    assert hostile not in " ".join(argv)
    script = Path(str(prepared["script_path"]))
    assert stat.S_IMODE(script.stat().st_mode) == 0o600
    assert script.read_text(encoding="utf-8") == hostile
    assert argv == proc_script_argv("bash", str(work), sys.executable)


def test_prepare_proc_script_rejects_digest_mismatch(tmp_path: Path) -> None:
    pytest.importorskip("sase_core_rs")
    from sase.core.agent_launch_facade import proc_dispatch_wire_schema_version

    work = tmp_path / "work"
    work.mkdir()
    code = make_code_value("echo ready", "bash", "bash")
    with pytest.raises(Exception, match="digest"):
        prepare_proc_script(
            {
                "schema_version": proc_dispatch_wire_schema_version(),
                "logical_id": "unit-1",
                "fingerprint": "fp",
                "code": {
                    "schema_version": 1,
                    "source": code.source,
                    "language": code.language,
                    "digest": "0" * 64,
                    "preview": code.preview,
                },
                "work_dir": str(work),
                "python_executable": sys.executable,
                "workspace": False,
                "declared_cwd": str(tmp_path),
                "source_cwd": str(tmp_path),
                "proc_id": "proc-digest",
            }
        )
