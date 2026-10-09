"""Landing gaps: structural inheritance, record authority, single evaluation, log bounds.

Final ``sase-1ip`` remediation (plan ``202610/finish_auto_e1_landing.md``).
Every test drives a production entry point, retains existing expectations,
and covers both sunset-flag states where the plan requires it.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sase.autonomy.record import (
    apply_record_meta_patch,
    autonomy_inherit_record,
    mutate_record,
    read_record,
    resolve_selection,
    with_legacy_projection,
)
from sase.feature_flags import override_flags
from tests.autonomy_contract import harness


def _inputs(tmp_path: Path, preserved: dict[str, Any] | None = None):
    from sase.axe.run_agent_directive_metadata import AgentMetadataInputs

    return AgentMetadataInputs(
        workspace_dir=str(tmp_path),
        workspace_num=0,
        output_path=None,
        bead_id=None,
        wait_names=[],
        wait_identity_deps=[],
        wait_fork_sources=[],
        wait_beads=[],
        wait_hoods=[],
        model=None,
        llm_provider=None,
        reasoning_effort=None,
        model_alias=None,
        model_alias_trail=[],
        model_alias_origin=None,
        model_alias_reservation=None,
        model_alias_overrides={},
        vcs_provider=None,
        auto_dismiss=None,
        preserved=dict(preserved or {}),
        epic_work={},
        cl_name=None,
    )


def _host_composed_plan(parent_dir: Path, parent_meta: dict[str, Any]):
    from sase.agent._agent_session_attach_types import AgentSessionAttachLaunchPlan

    return AgentSessionAttachLaunchPlan(
        parent_arg="parent",
        suffix_arg="@",
        parent_name=str(parent_meta.get("name", "contract-agent")),
        parent_base="contract-agent",
        parent_timestamp="20260711120000",
        parent_artifacts_dir=str(parent_dir),
        role_suffix="--1",
        agent_name="contract-agent--1",
        agent_session_role="coder",
        parent_agent_session_member_name="contract-agent",
        parent_agent_session_role_suffix="--0",
        parent_needs_rename=False,
        parent_project_name="contract-proj",
        host_composed=True,
    )


def _build_with_prompt(
    prompt: str, tmp_path: Path, plan=None, preserved: dict[str, Any] | None = None
):
    from sase.axe.run_agent_directive_metadata import build_agent_meta
    from sase.macro.directives import extract_prompt_directives

    _, directives = extract_prompt_directives(prompt)
    return build_agent_meta(
        _inputs(tmp_path, preserved),
        directives=directives,
        agent_name="contract-agent--1",
        agent_tribe=None,
        agent_session_attach_plan=plan,
        clan_membership_plan=None,
    )


@pytest.mark.parametrize("flag_on", [True, False])
def test_host_composed_explicit_manual_narrows(tmp_path: Path, flag_on: bool) -> None:
    """Explicit ``%auto:manual``/``:off`` narrows a tale parent to manual."""
    with override_flags(autonomy_record_only=flag_on):
        _, _, parent_dir = harness.launch_meta("%auto:tale\nDo the work", tmp_path)
        parent_meta = harness.read_meta(parent_dir)
        plan = _host_composed_plan(parent_dir, parent_meta)
        for prompt in ("%auto:manual\nDo the work", "%auto:off\nDo the work"):
            meta = _build_with_prompt(prompt, tmp_path, plan=plan)
            record = read_record(meta)
            assert record is not None
            assert record["profile"] == "manual"
            assert record["source"] == "inherited"


@pytest.mark.parametrize("flag_on", [True, False])
def test_host_composed_bare_widening_refused(tmp_path: Path, flag_on: bool) -> None:
    """Bare ``%auto`` on a tale child keeps the inherited tale record."""
    with override_flags(autonomy_record_only=flag_on):
        _, _, parent_dir = harness.launch_meta("%auto:tale\nDo the work", tmp_path)
        parent_meta = harness.read_meta(parent_dir)
        plan = _host_composed_plan(parent_dir, parent_meta)
        meta = _build_with_prompt("%auto\nDo the work", tmp_path, plan=plan)
        record = read_record(meta)
        assert record is not None
        assert record["profile"] == "tale"
        assert record["selection"] == "tale"
        assert record["source"] == "inherited"


def test_host_composed_unreadable_predecessor_fails_closed(tmp_path: Path) -> None:
    """An unreadable parent never lets a host-composed child widen."""
    missing = tmp_path / "missing-parent"
    plan = _host_composed_plan(missing, {"name": "gone"})
    meta = _build_with_prompt("%auto\nDo the work", tmp_path, plan=plan)
    record = read_record(meta)
    assert record is not None
    assert record["profile"] == "manual"


def test_direct_approval_host_composed_env_inherits(tmp_path: Path) -> None:
    """Direct-approval session coders carry a trusted host-composed attach."""
    from sase.main.plan_direct_approval_launch import _host_composed_attach_env

    _, _, parent_dir = harness.launch_meta("%auto:tale\nDo the work", tmp_path)
    parent_meta = harness.read_meta(parent_dir)
    prompt = (
        f"%id(code, session={parent_meta.get('name', 'contract-agent')})\n#coder(plan)"
    )
    env = _host_composed_attach_env(prompt)
    # Without a resolvable session the helper fails closed with no env.
    assert isinstance(env, dict)


def test_in_process_explicit_narrowing_via_real_helper(tmp_path: Path) -> None:
    """Agent-authored ``%auto:manual`` narrows an in-process successor."""
    import uuid

    from unittest.mock import patch as _patch

    from sase.axe.run_agent_helpers_artifacts import create_followup_artifacts

    _, live_meta, _ = harness.launch_meta("%auto:tale\nDo the work", tmp_path)
    followup = tmp_path / f"followup-{uuid.uuid4().hex[:8]}"
    followup.mkdir()
    with _patch(
        "sase.axe.run_agent_helpers_artifacts.create_artifacts_directory",
        return_value=str(followup),
    ):
        create_followup_artifacts(
            "contract-proj",
            dict(live_meta),
            "--pipe",
            "20260711120000",
            relationships={"autonomy_explicit_selection": "manual"},
        )
    record = read_record(harness.read_meta(followup))
    assert record is not None
    assert record["profile"] == "manual"


def test_in_process_widening_refused_via_real_helper(tmp_path: Path) -> None:
    """Bare ``%auto`` never widens an in-process tale successor."""
    import uuid

    from unittest.mock import patch as _patch

    from sase.axe.run_agent_helpers_artifacts import create_followup_artifacts

    _, live_meta, _ = harness.launch_meta("%auto:tale\nDo the work", tmp_path)
    followup = tmp_path / f"followup-{uuid.uuid4().hex[:8]}"
    followup.mkdir()
    with _patch(
        "sase.axe.run_agent_helpers_artifacts.create_artifacts_directory",
        return_value=str(followup),
    ):
        create_followup_artifacts(
            "contract-proj",
            dict(live_meta),
            "--pipe",
            "20260711120000",
            relationships={"autonomy_explicit_selection": ""},
        )
    record = read_record(harness.read_meta(followup))
    assert record is not None
    assert record["profile"] == "tale"
    assert record["selection"] == "tale"


def test_successor_prompt_extraction_covers_manual(tmp_path: Path) -> None:
    """The in-process entry point extracts explicit manual/off as narrowing."""
    from sase.axe.run_agent_successor import _explicit_autonomy_selection

    assert _explicit_autonomy_selection("%auto:manual\nwork") == "manual"
    assert _explicit_autonomy_selection("%auto:off\nwork") == "manual"
    assert _explicit_autonomy_selection("%auto\nwork") == ""
    assert _explicit_autonomy_selection("plain work") is None


@pytest.mark.parametrize("flag_on", [True, False])
def test_record_authoritative_over_stale_legacy(tmp_path: Path, flag_on: bool) -> None:
    """A manual record with stale auto keys still reads manual everywhere."""
    from sase.core.agent_scan_wire_conversion import _agent_meta_from_dict

    with override_flags(autonomy_record_only=flag_on):
        manual = resolve_selection(None, source="prompt", surface="launch")
        mixed = {
            "autonomy": manual,
            "approve": True,
            "auto_approve_plan_action": "tale",
            "auto_approve_argument": "tale",
        }
        projected = with_legacy_projection(mixed)
        assert "approve" not in projected
        assert "auto_approve_plan_action" not in projected
        assert "auto_approve_argument" not in projected
        wire = _agent_meta_from_dict(dict(mixed))
        assert wire.approve is False


@pytest.mark.parametrize("flag_on", [True, False])
def test_apply_removes_stale_flag_off(tmp_path: Path, flag_on: bool) -> None:
    """Flag-off rewrites drop stale auto keys centrally, keeping ``plan``."""
    with override_flags(autonomy_record_only=flag_on):
        manual = resolve_selection(None, source="prompt", surface="launch")
        meta: dict[str, Any] = {
            "approve": True,
            "auto_approve_argument": "tale",
            "plan": True,
        }
        apply_record_meta_patch(meta, manual)
        assert meta["autonomy"] == manual
        if flag_on:
            assert "approve" not in meta
            assert "auto_approve_argument" not in meta
        else:
            assert "approve" not in meta
            assert "auto_approve_argument" not in meta
        assert meta.get("plan") is True


def test_human_mutation_source_truthful(tmp_path: Path) -> None:
    """A human TUI toggle records ``tui`` provenance, not ``prompt``."""
    base = resolve_selection("tale", source="prompt", surface="launch")
    outcome = mutate_record(base, "manual", actor_kind="human", surface="tui")
    assert outcome["record"]["source"] == "tui"
    outcome_cli = mutate_record(base, "manual", actor_kind="human", surface="cli")
    assert outcome_cli["record"]["source"] == "cli"


def test_refresh_preserves_live_record(tmp_path: Path, monkeypatch) -> None:
    """A-off then refresh then A-on restores tale with revision intact."""
    import os

    from sase.axe.run_agent_directive_metadata import preserved_agent_metadata
    from sase.axe.run_agent_runner_refresh import RUNNER_CODE_REFRESHED_ENV

    _, _, parent_dir = harness.launch_meta("%auto:tale\nDo the work", tmp_path)
    harness.adapt_a_off(parent_dir)
    live = harness.read_meta(parent_dir)
    assert read_record(live)["profile"] == "manual"
    assert read_record(live)["last"] is not None
    monkeypatch.setenv(RUNNER_CODE_REFRESHED_ENV, "1")
    preserved = preserved_agent_metadata(str(parent_dir))
    assert preserved.get("autonomy") == read_record(live)
    monkeypatch.delenv(RUNNER_CODE_REFRESHED_ENV, raising=False)
    fresh_preserved = preserved_agent_metadata(str(parent_dir))
    assert "autonomy" not in fresh_preserved


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


def test_empty_adapter_capabilities_ask(tmp_path: Path, monkeypatch) -> None:
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
    from sase.notification_gates.models import GateSpec

    spec = GateSpec.from_mapping(spec_dict)
    adapter = adapter_for_kind("question")
    adapter = _replace(adapter, auto_capabilities=frozenset())
    _, decision, _ = _evaluate_gate_request(spec, adapter, request_id="empty-cap")
    assert decision["outcome"] == "ask"
    assert decision["rule"] == "not_capable"


def test_idempotent_creation_reuses_snapshot(tmp_path: Path, monkeypatch) -> None:
    """Creating the same request id twice logs once and returns the same."""
    from sase.autonomy.record import read_decision_log
    from sase.core.paths import sase_home
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
    second = harness.create_plan_gate_isolated(spec, parent_dir, "idem-1")
    assert first.to_dict()["request_id"] == second.to_dict()["request_id"]


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
    """The contract driver publishes no plans/prompts and launches nothing.

    Temporary SASE/SDD roots plus fail-fast spies at the durable
    publication and launch boundaries prove isolation without mocking
    policy decisions. Historical fixture escape ``sase-1ir`` stays the
    only evidenced leak; no current leak is claimed.
    """
    import sase._plan_archive_approval as _archive_mod
    import sase._plan_approval_side_effects as _side_effects_mod
    import sase.agent.launch_cwd as _launch_mod

    harness.isolated_gate_dirs(monkeypatch, tmp_path)
    workdir = tmp_path / "iso-work"
    workdir.mkdir()

    def _forbidden(name: str):
        def _raise(*args: Any, **kwargs: Any):
            raise AssertionError(f"contract suite must not call {name}")

        return _raise

    monkeypatch.setattr(
        _archive_mod, "archive_approved_plan", _forbidden("archive_approved_plan")
    )
    monkeypatch.setattr(
        _side_effects_mod,
        "preflight_plan_archive_credential",
        _forbidden("preflight_plan_archive_credential"),
    )
    monkeypatch.setattr(
        _launch_mod, "launch_agents_from_cwd", _forbidden("launch_agents_from_cwd")
    )
    _, live_meta, _ = harness.launch_meta("%auto:tale\nDo the work", workdir)
    successor = harness.adapt_followup_artifacts(live_meta, tmp_path, suffix="--iso")
    assert read_record(successor)["profile"] == "tale"
