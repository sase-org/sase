"""explain-equals-runtime: ``sase autonomy explain`` predicts every gate.

For every contract row, ``sase autonomy explain -p "<prompt>"`` (and the
``explain <agent>`` record path for the context rows) equals the decision
recorded in that row's gate policy block, per gate kind. The property runs
through production code with no mocks on the decision path: real launch,
real successor helpers, and real gate creation (execution side effects
stubbed, exactly as in the contract harness).
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from sase.autonomy.cli_explain import _dry_run_prompt, handle_autonomy_explain
from sase.autonomy.cli_shared import predictions_for_record
from sase.autonomy.record import read_record
from sase.macro._exceptions import DirectiveError
from sase.macro.directives import extract_prompt_directives

from . import harness
from .rows import INVALID_PROMPTS, SPELLING_ROWS, STATE_ROWS
from tests.plan_validation_helpers import VALID_EPIC_PLAN, VALID_TALE_PLAN

#: Policy-block keys ``explain`` must predict exactly.
POLICY_KEYS = (
    "profile",
    "selection",
    "rule",
    "outcome",
    "value",
    "option_ids",
    "source",
    "revision",
    "digest",
)


def _policies_for_live_meta(
    artifacts_dir: Path,
    tale_plan: Path,
    epic_plan: Path,
    monkeypatch: Any,
    tag: str,
) -> dict[str, dict[str, Any]]:
    """Create real tale, epic, and question gates; return policy blocks."""
    from sase.plan_gate import build_plan_approval_gate_spec

    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))
    from sase.main.plan_approve_handler import (
        get_auto_plan_approval_action,
        get_auto_plan_approval_argument,
        is_auto_approve_active,
    )

    policies: dict[str, dict[str, Any]] = {}
    for kind, plan_file in (("plan", tale_plan), ("epic_plan", epic_plan)):
        auto_action = get_auto_plan_approval_action()
        auto_enabled = auto_action is not None
        auto_argument = get_auto_plan_approval_argument()
        if auto_argument is None and auto_action in {"tale", "epic"}:
            auto_argument = auto_action
        spec = build_plan_approval_gate_spec(
            str(plan_file),
            f"{kind}-{tag}",
            auto_enabled=auto_enabled,
            auto_argument=auto_argument,
        )
        gate = harness.create_plan_gate_isolated(spec, artifacts_dir, f"{kind}-{tag}")
        resolved = gate.to_dict().get("auto_resolution") or {}
        policies[kind] = dict(resolved.get("policy") or {})

    from sase.user_question_actions import user_question_gate_spec

    question_spec = user_question_gate_spec(
        [dict(question) for question in harness.QUESTIONS],
        session_id=f"q-{tag}",
        producer={"agent": "contract-agent"},
        auto=is_auto_approve_active(),
    )
    from sase.notification_gates.service import create_gate

    question_gate = create_gate(question_spec)
    resolved = question_gate.to_dict().get("auto_resolution") or {}
    policies["question"] = dict(resolved.get("policy") or {})
    return policies


def _assert_predictions_match_policies(
    predictions: dict[str, dict[str, Any]],
    policies: dict[str, dict[str, Any]],
) -> None:
    for kind in ("plan", "epic_plan", "question"):
        predicted = {key: predictions[kind].get(key) for key in POLICY_KEYS}
        recorded = {key: policies[kind].get(key) for key in POLICY_KEYS}
        assert predicted == recorded, f"explain != runtime for {kind}"


@pytest.mark.parametrize("row", SPELLING_ROWS, ids=[row.id for row in SPELLING_ROWS])
def test_explain_prompt_equals_gate_policy(
    row, tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    """``explain -p`` predicts the policy block of every gate column."""
    harness.isolated_gate_dirs(monkeypatch, tmp_path)
    workdir = tmp_path / "work"
    workdir.mkdir()
    tale_plan = harness.write_plan_file(workdir, "tale.md", VALID_TALE_PLAN)
    epic_plan = harness.write_plan_file(workdir, "epic.md", VALID_EPIC_PLAN)

    _, _, artifacts_dir = harness.launch_meta(row.prompt, workdir)
    policies = _policies_for_live_meta(
        artifacts_dir, tale_plan, epic_plan, monkeypatch, row.id
    )
    outcome = _dry_run_prompt(row.prompt)
    assert outcome["error"] is None
    _assert_predictions_match_policies(outcome["predictions"], policies)

    # The same predictions through the real CLI handler's ``--json`` path.
    args = SimpleNamespace(prompt=row.prompt, gate=None, agent=None, json=True)
    assert handle_autonomy_explain(args) == 0
    cli_predictions = json.loads(capsys.readouterr().out)["predictions"]
    _assert_predictions_match_policies(cli_predictions, policies)


@pytest.mark.parametrize("prompt", INVALID_PROMPTS)
def test_explain_prompt_error_matches_launch(prompt: str) -> None:
    """An invalid spelling reports the launch-exact message, never a guess."""
    with pytest.raises(DirectiveError) as launch_error:
        extract_prompt_directives(prompt)
    assert _dry_run_prompt(prompt)["error"] == str(launch_error.value)


def _context_meta(
    row_id: str, prompt: str, tmp_path: Path
) -> tuple[dict[str, Any], Path]:
    """Build the successor meta named by a ``STATE_ROWS`` context."""
    workdir = tmp_path / "work"
    workdir.mkdir(exist_ok=True)
    if row_id == "tale_epic_worker":
        prompt = f"{harness.adapt_epic_worker_prompt()}\nDo the work"
    _, live_meta, predecessor = harness.launch_meta(prompt, workdir)
    if row_id in ("bare_a_off", "tale_a_off_on", "bare_a_off_successor"):
        harness.adapt_a_off(predecessor)
        live_meta = harness.read_meta(predecessor)
    if row_id == "tale_a_off_on":
        live_meta = harness.adapt_a_on_bare(predecessor)
    if row_id in (
        "tale_pipe",
        "tale_monitor_followup",
        "tale_gate_followup",
        "tale_question_successor",
        "plan_monitor_followup",
        "bare_a_off_successor",
    ):
        live_meta = harness.adapt_followup_artifacts(
            live_meta, tmp_path, suffix=f"--{row_id}"
        )
    if row_id == "tale_coder":
        snapshot = dict(live_meta)
        live_meta = harness.adapt_in_process_coder(predecessor, snapshot)
    followed = tmp_path / f"live-{row_id}"
    followed.mkdir(exist_ok=True)
    harness.write_meta(followed, live_meta)
    return live_meta, followed


@pytest.mark.parametrize("row", STATE_ROWS, ids=[row.id for row in STATE_ROWS])
def test_explain_agent_path_equals_gate_policy(
    row, tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    """The ``explain <agent>`` path predicts each context row's gates."""
    harness.isolated_gate_dirs(monkeypatch, tmp_path)
    workdir = tmp_path / "work"
    workdir.mkdir(exist_ok=True)
    tale_plan = harness.write_plan_file(workdir, "tale.md", VALID_TALE_PLAN)
    epic_plan = harness.write_plan_file(workdir, "epic.md", VALID_EPIC_PLAN)

    live_meta, artifacts_dir = _context_meta(row.id, row.prompt, tmp_path)
    record = read_record(live_meta)
    assert record is not None
    policies = _policies_for_live_meta(
        artifacts_dir, tale_plan, epic_plan, monkeypatch, row.id
    )
    _assert_predictions_match_policies(predictions_for_record(record), policies)

    # The same record through the real ``explain <agent>`` handler path,
    # with agent resolution pointed at the context's artifacts dir (the
    # lookup scans the live registry; the handler path below it is real).
    resolved = SimpleNamespace(name="context-agent", artifacts_dir=str(artifacts_dir))
    args = SimpleNamespace(prompt=None, gate=None, agent="context-agent", json=True)
    with patch("sase.agent.names.find_named_agent", return_value=resolved):
        assert handle_autonomy_explain(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["agent"] == "context-agent"
    _assert_predictions_match_policies(payload["predictions"], policies)


@pytest.mark.parametrize("selection", ["", "tale", "epic"])
def test_dispatched_prompt_resolves_to_same_record(selection: str) -> None:
    """A ``%dispatch``-forwarded prompt resolves to the identical record."""
    from sase.macro._directive_scan import scan_dispatch_directive

    suffix = "" if selection == "" else f":{selection}"
    sender_prompt = f"%auto{suffix} %dispatch(machine)\nDo the work"
    scan = scan_dispatch_directive(sender_prompt)
    assert scan is not None
    # The intent forwards the prompt verbatim, `%auto` token included.
    assert f"%auto{suffix}" in scan.prompt
    _, forwarded = extract_prompt_directives(scan.prompt)
    _, direct = extract_prompt_directives(f"%auto{suffix}\nDo the work")
    assert (forwarded.auto_enabled, forwarded.auto_argument) == (
        direct.auto_enabled,
        direct.auto_argument,
    )
    from sase.autonomy.record import resolve_selection

    def _resolve(argument: str | None, enabled: bool) -> dict[str, Any]:
        if enabled and argument is not None:
            choice: str | None = argument
        elif enabled:
            choice = ""
        else:
            choice = None
        return resolve_selection(choice, source="prompt", surface="launch")

    receiving = _resolve(forwarded.auto_argument, forwarded.auto_enabled)
    sending = _resolve(direct.auto_argument, direct.auto_enabled)
    for key in ("profile", "selection", "policy", "digest"):
        assert receiving[key] == sending[key], f"dispatch drift on {key}"
