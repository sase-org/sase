"""Landing-gap contracts for gate evaluation, logs, and publication fences."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.autonomy.record import read_record
from tests.autonomy_contract import harness


def test_single_evaluation_per_creation(tmp_path: Path, monkeypatch) -> None:
    """Gate creation evaluates exactly once, using adapter capabilities."""
    from sase.autonomy import gates as _gates

    harness.isolated_gate_dirs(monkeypatch, tmp_path)
    _, _, parent_dir = harness.launch_meta("%auto:tale\nDo the work", tmp_path)
    calls: list[tuple[str, list[str]]] = []
    real_evaluate = _gates.evaluate_gate

    def _counting(record, *, gate_kind, option_ids, capabilities=None):
        calls.append((gate_kind, list(option_ids)))
        return real_evaluate(
            record,
            gate_kind=gate_kind,
            option_ids=option_ids,
            capabilities=capabilities,
        )

    monkeypatch.setattr(_gates, "evaluate_gate", _counting)
    from sase.plan_gate import build_plan_approval_gate_spec
    from tests.plan_validation_helpers import VALID_TALE_PLAN

    workdir = tmp_path / "single-work"
    workdir.mkdir()
    plan_file = harness.write_plan_file(workdir, "tale.md", VALID_TALE_PLAN)
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(parent_dir))
    from sase.main.plan_approve_handler import (
        get_auto_plan_approval_action,
        get_auto_plan_approval_argument,
    )

    auto_action = get_auto_plan_approval_action()
    auto_argument = get_auto_plan_approval_argument()
    if auto_argument is None and auto_action in {"tale", "epic"}:
        auto_argument = auto_action
    spec = build_plan_approval_gate_spec(
        str(plan_file),
        "single-1",
        auto_enabled=auto_action is not None,
        auto_argument=auto_argument,
    )
    harness.create_plan_gate_isolated(spec, parent_dir, "single-1")
    assert len(calls) == 1


@pytest.mark.parametrize("profile", ["standard", "question_fixture"])
def test_empty_adapter_capabilities_ask(
    tmp_path: Path, monkeypatch, profile: str
) -> None:
    """A question adapter with no capabilities always asks."""
    from dataclasses import replace as _replace

    from sase.notification_gates.registry import adapter_for_kind
    from sase.notification_gates.service_evaluation import _evaluate_gate_request
    from sase.user_question_actions import user_question_gate_spec

    harness.isolated_gate_dirs(monkeypatch, tmp_path)
    _, _, parent_dir = harness.launch_meta("%auto\nDo the work", tmp_path)
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(parent_dir))
    spec_dict = user_question_gate_spec(
        [dict(q) for q in harness.QUESTIONS],
        session_id="empty-cap",
        producer={"agent": "contract-agent"},
        auto=True,
    )
    if profile == "question_fixture":
        spec_dict["auto"] = {
            "enabled": True,
            "policy": harness.question_first_fixture_record(),
        }
    from sase.notification_gates.models import GateSpec

    spec = GateSpec.from_mapping(spec_dict)
    adapter = adapter_for_kind("question")
    _, capable_decision, _ = _evaluate_gate_request(
        spec, adapter, request_id="with-cap"
    )
    assert capable_decision["outcome"] == (
        "auto" if profile == "question_fixture" else "ask"
    )
    adapter = _replace(adapter, auto_capabilities=frozenset())
    _, decision, _ = _evaluate_gate_request(spec, adapter, request_id="empty-cap")
    assert decision["outcome"] == "ask"
    assert decision["rule"] == (
        "not_capable" if profile == "question_fixture" else "gates.question"
    )


def test_idempotent_creation_reuses_snapshot(tmp_path: Path, monkeypatch) -> None:
    """Repeated and recovered creation preserve one decision and policy snapshot."""
    import json

    from sase.autonomy.record import read_decision_log
    from sase.notification_gates.durability import read_json_object
    from sase.notification_gates.paths import bundle_paths
    from sase.plan_gate import build_plan_approval_gate_spec
    from tests.plan_validation_helpers import VALID_TALE_PLAN

    harness.isolated_gate_dirs(monkeypatch, tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("SASE_HOME", str(home))
    monkeypatch.setenv("HOME", str(home))
    try:
        from sase.core.paths import _SASE_HOME_OVERRIDE  # type: ignore
    except Exception:
        pass
    _, _, parent_dir = harness.launch_meta("%auto:tale\nDo the work", tmp_path)
    workdir = tmp_path / "idem-work"
    workdir.mkdir()
    plan_file = harness.write_plan_file(workdir, "tale.md", VALID_TALE_PLAN)
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(parent_dir))
    from sase.main.plan_approve_handler import (
        get_auto_plan_approval_action,
        get_auto_plan_approval_argument,
    )

    auto_action = get_auto_plan_approval_action()
    auto_argument = get_auto_plan_approval_argument()
    if auto_argument is None and auto_action in {"tale", "epic"}:
        auto_argument = auto_action
    spec = build_plan_approval_gate_spec(
        str(plan_file),
        "idem-1",
        auto_enabled=auto_action is not None,
        auto_argument=auto_argument,
    )
    first = harness.create_plan_gate_isolated(spec, parent_dir, "idem-1")
    expected_policy = first.to_dict()["auto_resolution"]["policy"]
    assert expected_policy["profile"] == "tale"
    paths = bundle_paths("plan", "idem-1")
    request = read_json_object(paths.request)
    response = read_json_object(paths.response)
    assert request["auto"]["policy"] == expected_policy
    assert response["policy"] == expected_policy

    # Simulate interruption after the request/journal snapshot was committed
    # but before the public creation result was written.
    paths.creation_result.unlink()
    journal = read_json_object(paths.journal)
    journal["state"] = "bundle_written"
    paths.journal.write_text(json.dumps(journal), encoding="utf-8")
    recovered = harness.create_plan_gate_isolated(spec, parent_dir, "idem-1")
    repeated = harness.create_plan_gate_isolated(spec, parent_dir, "idem-1")
    assert recovered.to_dict()["request_id"] == repeated.to_dict()["request_id"]
    assert recovered.to_dict()["auto_resolution"]["policy"] == expected_policy
    assert read_json_object(paths.response)["policy"] == expected_policy

    rows = read_decision_log({"limit": 1000})
    explicit_rows = [row for row in rows if row.get("gate_id") == "idem-1"]
    assert len(explicit_rows) == 1
    assert {
        key: explicit_rows[0]["decision"].get(key) for key in expected_policy
    } == expected_policy

    # A service-generated request id must also be the id in the one decision
    # row, instead of the empty input id.
    generated_spec = dict(spec)
    generated_spec["request_id"] = None
    generated = harness.create_plan_gate_isolated(
        generated_spec, parent_dir, "generated"
    )
    generated_id = generated.to_dict()["request_id"]
    assert generated_id and generated_id != "generated"
    generated_rows = [
        row
        for row in read_decision_log({"limit": 1000})
        if row.get("gate_id") == generated_id
    ]
    assert len(generated_rows) == 1
    generated_policy = generated.to_dict()["auto_resolution"]["policy"]
    assert {
        key: generated_rows[0]["decision"].get(key) for key in generated_policy
    } == generated_policy


def test_log_since_normalization(tmp_path: Path, monkeypatch) -> None:
    """Relative ``--since`` bounds filter old entries; invalid input fails."""
    from sase.autonomy.cli_log import _normalize_since_bound
    from sase.vcs_log.dates import VcsLogDateError

    recent = _normalize_since_bound("1h")
    assert recent.endswith("Z")
    assert "T" in recent
    today = _normalize_since_bound("today")
    assert today.endswith("Z")
    with pytest.raises(VcsLogDateError):
        _normalize_since_bound("not-a-date")

    # A year-2000 entry must not match a 1h bound after normalization.
    assert "2000-01-01T00:00:00Z" < recent


def test_log_agent_shorthand_resolves(tmp_path: Path) -> None:
    """Agent shorthand resolves the way other autonomy views do."""
    from sase.autonomy.cli_log import _resolve_agent_filter

    assert _resolve_agent_filter("no-such-agent-xyz") == "no-such-agent-xyz"


def test_contract_suite_publishes_nothing(tmp_path: Path, monkeypatch) -> None:
    """Automatic contract gates run while durable publication/launch stay fenced."""
    from types import SimpleNamespace

    import sase._plan_archive_approval as _archive_mod
    import sase.bead.epic_launch as _epic_launch_mod
    import sase.agent.launch_cwd as _launch_mod
    from tests.plan_validation_helpers import VALID_EPIC_PLAN, VALID_TALE_PLAN

    harness.isolated_gate_dirs(monkeypatch, tmp_path)
    home = tmp_path / "sase-home"
    plans_root = tmp_path / "sdd-plans"
    beads_root = tmp_path / "sdd-beads"
    home.mkdir()
    monkeypatch.setenv("SASE_HOME", str(home))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("SASE_SDD_PLANS_DIR", str(plans_root))
    monkeypatch.setenv("SASE_SDD_BEADS_DIR", str(beads_root))

    forbidden_calls: list[str] = []

    def _forbidden(name: str):
        def _raise(*args: Any, **kwargs: Any):
            forbidden_calls.append(name)
            raise AssertionError(f"contract suite must not call {name}")

        return _raise

    monkeypatch.setattr(
        _archive_mod,
        "archive_approved_plan",
        _forbidden("archive_approved_plan"),
    )
    monkeypatch.setattr(
        _epic_launch_mod,
        "start_epic_launch_monitor",
        _forbidden("start_epic_launch_monitor"),
    )
    monkeypatch.setattr(
        _launch_mod,
        "launch_agents_from_cwd",
        _forbidden("launch_agents_from_cwd"),
    )

    archive_calls: list[tuple[Any, ...]] = []
    launch_calls: list[tuple[Any, ...]] = []

    def _archive_stub(*args: Any, **_kwargs: Any) -> str:
        archive_calls.append(args)
        return str(tmp_path / "blocked-archive.md")

    def _epic_stub(*args: Any, **_kwargs: Any):
        launch_calls.append(args)
        return SimpleNamespace(monitor_id="blocked-monitor")

    workdir = tmp_path / "iso-work"
    workdir.mkdir()
    tale_work = workdir / "tale"
    tale_work.mkdir()
    epic_work = workdir / "epic"
    epic_work.mkdir()
    tale_plan = harness.write_plan_file(tale_work, "tale.md", VALID_TALE_PLAN)
    epic_plan = harness.write_plan_file(epic_work, "epic.md", VALID_EPIC_PLAN)

    _, tale_meta, tale_artifacts = harness.launch_meta(
        "%auto:tale\nDo the work", tale_work
    )
    assert read_record(tale_meta)["profile"] == "tale"
    assert (
        harness.plan_outcome(
            tale_meta,
            tale_artifacts,
            tale_plan,
            monkeypatch=monkeypatch,
            request_id="isolated-tale",
            archive_plan=_archive_stub,
            epic_launch=_epic_stub,
        )
        == harness.APPROVE_ARCHIVE
    )
    assert (
        harness.question_outcome(
            tale_artifacts, monkeypatch=monkeypatch, request_id="isolated-question"
        )
        == harness.ASK
    )

    _, epic_meta, epic_artifacts = harness.launch_meta(
        "%auto:epic\nDo the work", epic_work
    )
    assert read_record(epic_meta)["profile"] == "epic"
    assert (
        harness.plan_outcome(
            epic_meta,
            epic_artifacts,
            epic_plan,
            monkeypatch=monkeypatch,
            request_id="isolated-epic",
            archive_plan=_archive_stub,
            epic_launch=_epic_stub,
        )
        == harness.APPROVE_LAUNCH
    )

    # These assertions prove the intended creation operations actually ran;
    # the matching high-level aliases were stubbed while every lower-level
    # durable publication and real launch boundary remained fail-fast.
    assert len(archive_calls) == 1
    assert len(launch_calls) == 1
    assert forbidden_calls == []
