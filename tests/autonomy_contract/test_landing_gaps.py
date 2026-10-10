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


def _direct_approval_plan(tmp_path: Path, *, recovery: bool = False):
    from sase.main.plan_direct_approval import (
        CoderPlacement,
        DirectApprovalPlan,
        DirectApprovalRequest,
    )

    source = tmp_path / "approved-plan.md"
    source.write_text("# Approved plan\n", encoding="utf-8")
    fields: dict[str, Any] = {}
    if recovery:
        from sase.main.plan_direct_approval_recovery import CoderRecovery

        fields["recovery"] = CoderRecovery(
            verdict="recover",
            approved_action="approve",
            approved_age="1m ago",
            plan_argument="plan:202610/approved-plan.md",
        )
    return DirectApprovalPlan(
        request=DirectApprovalRequest(selector=str(source), project="contract-proj"),
        kind="approve",
        source_path=source,
        location="proposal",
        name="approved-plan",
        title="Approved plan",
        size="small",
        project="contract-proj",
        project_tag="+contract-proj",
        planner="contract-agent",
        gate=None,
        placement=CoderPlacement(
            mode="session",
            parent="contract-agent",
            member_name="contract-agent--code",
            agent_session="contract-agent",
        ),
        model_directive="@small",
        predicted_plan_ref="plan:202610/approved-plan.md",
        **fields,
    )


@pytest.mark.parametrize("caller", ["direct", "recovery"])
@pytest.mark.parametrize("cwd_project", ["contract-proj", "other-proj", None])
@pytest.mark.parametrize("parent_mode", ["tale", "off"])
@pytest.mark.parametrize("flag_on", [True, False])
def test_direct_approval_and_recovery_inherit_from_target_project(
    tmp_path: Path,
    monkeypatch,
    caller: str,
    cwd_project: str | None,
    parent_mode: str,
    flag_on: bool,
) -> None:
    """Direct approval and recovery retain inheritance across unrelated CWDs."""
    from types import SimpleNamespace

    from sase.agent._agent_session_attach_launch import (
        load_agent_session_attach_plan_from_env,
        prepare_agent_session_attach_launch,
    )
    from sase.agent import _agent_session_attach_resolution as attach_resolution
    from sase.agent.launch_types import AgentLaunchResult
    from sase.axe.run_agent_directive_metadata import build_agent_meta
    from sase.macro.directives import extract_prompt_directives
    from sase.main.plan_direct_approval_run import (
        execute_coder_recovery,
        execute_direct_approval,
    )

    monkeypatch.delenv("SASE_AGENT", raising=False)
    workdir = tmp_path / "work"
    workdir.mkdir()
    with override_flags(autonomy_record_only=flag_on):
        _, _, parent_dir = harness.launch_meta("%auto:tale\nDo the work", workdir)
        if parent_mode == "off":
            harness.adapt_a_off(parent_dir)
        parent_meta = harness.read_meta(parent_dir)
        parent_record = read_record(parent_meta)
        assert parent_record is not None

        unresolved_plan = replace(
            _host_composed_plan(parent_dir, parent_meta), host_composed=False
        )
        resolved_projects: list[str] = []

        def _resolve(directive, *, project_name: str, **_kwargs):
            resolved_projects.append(project_name)
            if project_name != "contract-proj":
                raise RuntimeError(f"unrecognized session project: {project_name}")
            return unresolved_plan

        monkeypatch.setattr(
            attach_resolution, "resolve_agent_session_attach_plan", _resolve
        )
        monkeypatch.setattr(
            "sase.main.utils.ensure_project_file_and_get_workspace_num",
            lambda **_kwargs: (None, 0, cwd_project),
        )
        monkeypatch.setattr(
            "sase.config._owner.require_agent_owner_identity", lambda: object()
        )
        built: list[dict[str, Any]] = []

        def _fake_process_launch(prompt: str, extra_env=None, **_kwargs):
            context = SimpleNamespace(project_name="contract-proj", is_home_mode=True)
            pre_resolved = load_agent_session_attach_plan_from_env(
                dict(extra_env or {})
            )
            assert pre_resolved is not None and pre_resolved.host_composed is True
            _context, child_env = prepare_agent_session_attach_launch(
                prompt,
                context,
                dict(extra_env or {}),
                resolve_agent_session_attach_plan=_resolve,
            )
            attach_plan = load_agent_session_attach_plan_from_env(child_env)
            assert attach_plan is not None and attach_plan.host_composed is True
            _, directives = extract_prompt_directives(prompt)
            child_meta = build_agent_meta(
                _inputs(workdir),
                directives=directives,
                agent_name=attach_plan.agent_name,
                agent_tribe=None,
                agent_session_attach_plan=attach_plan,
                clan_membership_plan=None,
            )
            built.append(child_meta)
            return [
                AgentLaunchResult(
                    pid=123,
                    workspace_num=0,
                    workspace_dir=str(workdir),
                    output_path=str(tmp_path / "coder.out"),
                    agent_name=attach_plan.agent_name,
                )
            ]

        monkeypatch.setattr(
            "sase.agent.launch_cwd.launch_agents_from_cwd", _fake_process_launch
        )
        plan = _direct_approval_plan(tmp_path, recovery=caller == "recovery")
        outcome = (
            execute_coder_recovery(plan)
            if caller == "recovery"
            else execute_direct_approval(plan)
        )

        assert outcome.coder is not None
        assert len(built) == 1
        child_record = read_record(built[0])
        assert child_record is not None
        assert child_record["profile"] == parent_record["profile"]
        assert child_record["selection"] == parent_record["selection"]
        assert child_record["policy"] == parent_record["policy"]
        assert child_record["source"] == "inherited"
        assert child_record["revision"] == parent_record["revision"]
        assert child_record["last"] == parent_record["last"]
        assert child_record["digest"] == parent_record["digest"]
        assert set(resolved_projects) == {"contract-proj"}


def test_human_session_attach_uses_its_prompt_and_standalone_stays_standalone(
    tmp_path: Path,
) -> None:
    """Human attaches resolve their prompt; standalone coders need no attach."""
    from types import SimpleNamespace

    from sase.agent._agent_session_attach_launch import (
        load_agent_session_attach_plan_from_env,
        prepare_agent_session_attach_launch,
    )
    from sase.main.plan_direct_approval_launch import launch_coder_once
    from sase.main.plan_direct_approval_types import CoderPlacement

    _, _, parent_dir = harness.launch_meta("%auto:tale\nDo the work", tmp_path)
    prompt = "%id(code, session=contract-agent)\n%auto:manual\nHuman work"
    context = SimpleNamespace(project_name="contract-proj", is_home_mode=True)
    _context, env = prepare_agent_session_attach_launch(
        prompt,
        context,
        None,
        resolve_agent_session_attach_plan=lambda _directive, **_kwargs: replace(
            _host_composed_plan(parent_dir, {"name": "contract-agent"}),
            host_composed=False,
        ),
    )
    human_meta = _build_with_prompt(
        prompt, tmp_path, plan=load_agent_session_attach_plan_from_env(env)
    )
    human_record = read_record(human_meta)
    assert human_record is not None
    assert human_record["profile"] == "manual"
    assert human_record["source"] == "prompt"

    seen: list[dict[str, str]] = []

    def _launch(_prompt: str, extra_env=None, **_kwargs):
        seen.append(dict(extra_env or {}))
        return [object()]

    with patch("sase.agent.launch_cwd.launch_agents_from_cwd", _launch):
        launch_coder_once(
            "+contract-proj #coder(plan)",
            tmp_path / "standalone.md",
            project_name="contract-proj",
            placement=CoderPlacement(mode="standalone"),
        )
    assert seen and "SASE_AGENT_SESSION_ATTACH" not in seen[0]


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


@pytest.mark.parametrize("flag_on", [True, False])
def test_refresh_preserves_live_record(
    tmp_path: Path, monkeypatch, flag_on: bool
) -> None:
    """A-off, refreshed metadata build, and A-on retain the tale restore state."""
    from sase.axe.run_agent_directive_metadata import preserved_agent_metadata
    from sase.axe.run_agent_runner_refresh import RUNNER_CODE_REFRESHED_ENV
    from sase.axe.run_agent_runner_refresh import reconcile_prompt_with_live_auto_state
    from sase.macro.directives import extract_prompt_directives

    with override_flags(autonomy_record_only=flag_on):
        _, _, parent_dir = harness.launch_meta("%auto:tale\nDo the work", tmp_path)
        harness.adapt_a_off(parent_dir)
        live = harness.read_meta(parent_dir)
        live_record = read_record(live)
        assert live_record is not None
        assert live_record["profile"] == "manual"
        assert live_record["revision"] == 2
        assert live_record["last"] == {"profile": "tale", "selection": "tale"}

        monkeypatch.setenv(RUNNER_CODE_REFRESHED_ENV, "1")
        preserved = preserved_agent_metadata(str(parent_dir))
        assert preserved.get("autonomy") == live_record
        submitted_prompt = "%auto:tale\nDo the work"
        refreshed_prompt = reconcile_prompt_with_live_auto_state(
            submitted_prompt, str(parent_dir)
        )
        assert refreshed_prompt == "Do the work"
        _, directives = extract_prompt_directives(refreshed_prompt)
        from sase.axe.run_agent_directive_metadata import build_agent_meta

        rebuilt = build_agent_meta(
            _inputs(tmp_path, preserved),
            directives=directives,
            agent_name="contract-agent",
            agent_tribe=None,
            agent_session_attach_plan=None,
            clan_membership_plan=None,
        )
        harness.write_meta(parent_dir, rebuilt)
        rebuilt_record = read_record(rebuilt)
        assert rebuilt_record == live_record
        assert rebuilt_record["revision"] == 2
        assert rebuilt_record["last"] == {"profile": "tale", "selection": "tale"}

        monkeypatch.delenv(RUNNER_CODE_REFRESHED_ENV, raising=False)
        fresh_preserved = preserved_agent_metadata(str(parent_dir))
        assert "autonomy" not in fresh_preserved

        restored = harness.adapt_a_on_bare(parent_dir)
        restored_record = read_record(restored)
        assert restored_record is not None
        assert restored_record["profile"] == "tale"
        assert restored_record["selection"] == "tale"
        assert restored_record["revision"] == 3


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
        == harness.FIRST
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
