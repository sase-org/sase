"""Inheritance contract: host-composed successors keep the live ``%auto`` state.

E1 ``inherit``: every host-composed successor inherits its predecessor's
live record structurally through core ``autonomy_inherit`` (profile,
selection, policy, and ``last`` carry over with ``source: inherited``).
Follow-up prompts re-emit no ``%auto`` prefix; an explicit ``%auto`` in an
agent-authored successor prompt narrows under agent semantics, and a
widening request keeps the inherited record.
"""

from __future__ import annotations

from pathlib import Path

from sase.autonomy.record import read_record
from sase.feature_flags import override_flags

from . import harness


def _launch_tale(tmp_path: Path, *, prompt: str = "%auto:tale\nDo the work"):
    workdir = tmp_path / "work"
    workdir.mkdir(parents=True, exist_ok=True)
    return harness.launch_meta(prompt, workdir)


def test_tale_successor_inherits_record(tmp_path) -> None:
    """A ``%auto:tale`` successor keeps the tale record structurally."""
    _, live_meta, _ = _launch_tale(tmp_path)
    successor_meta = harness.adapt_followup_artifacts(
        live_meta, tmp_path, suffix="--pipe"
    )
    record = read_record(successor_meta)
    assert record is not None
    assert record["profile"] == "tale"
    assert record["selection"] == "tale"
    assert record["source"] == "inherited"


def test_tale_successor_inherits_both_flag_states(tmp_path) -> None:
    """Inheritance matches with the sunset flag on and off."""
    _, live_meta, _ = _launch_tale(tmp_path)
    on = harness.adapt_followup_artifacts(live_meta, tmp_path, suffix="--on")
    with override_flags(autonomy_record_only=False):
        _, off_live, _ = harness.launch_meta(
            "%auto:tale\nDo the work", tmp_path / "off-work"
        )
        off = harness.adapt_followup_artifacts(off_live, tmp_path, suffix="--off")
    assert read_record(on)["profile"] == "tale"
    assert read_record(off)["profile"] == "tale"
    assert read_record(on)["selection"] == read_record(off)["selection"] == "tale"


def test_plan_successor_not_widened_to_bare(tmp_path) -> None:
    """A ``%auto:plan`` successor stays tale (``:plan`` preserved, not bare)."""
    _, live_meta, _ = _launch_tale(tmp_path, prompt="%auto:plan\nDo the work")
    successor_meta = harness.adapt_followup_artifacts(
        live_meta, tmp_path, suffix="--monitor"
    )
    record = read_record(successor_meta)
    assert record is not None
    assert record["profile"] == "tale"
    assert record["selection"] == "plan"
    assert record["source"] == "inherited"


def test_a_off_successor_is_manual(tmp_path) -> None:
    """``A`` off on the live member means the next successor is manual."""
    _, _, predecessor = _launch_tale(tmp_path, prompt="%auto\nDo the work")
    harness.adapt_a_off(predecessor)
    live_meta = harness.read_meta(predecessor)
    successor_meta = harness.adapt_followup_artifacts(
        live_meta, tmp_path, suffix="--monitor"
    )
    record = read_record(successor_meta)
    assert record is not None
    assert record["profile"] == "manual"


def test_explicit_narrowing_applies(tmp_path) -> None:
    """An explicit ``%auto:manual`` in a successor prompt narrows to manual."""
    from sase.autonomy.record import autonomy_inherit_record

    _, live_meta, _ = _launch_tale(tmp_path)
    predecessor = read_record(live_meta)
    assert predecessor is not None
    outcome = autonomy_inherit_record(
        predecessor,
        predecessor_name="contract-agent",
        explicit_selection="manual",
        actor_kind="host",
    )
    assert outcome["status"] == "narrowed"
    assert outcome["record"]["profile"] == "manual"


def test_widening_is_refused(tmp_path) -> None:
    """A widening ``%auto`` keeps the inherited tale record."""
    from sase.autonomy.record import autonomy_inherit_record

    _, live_meta, _ = _launch_tale(tmp_path)
    predecessor = read_record(live_meta)
    assert predecessor is not None
    outcome = autonomy_inherit_record(
        predecessor,
        predecessor_name="contract-agent",
        explicit_selection="",
        actor_kind="host",
    )
    assert outcome["status"] == "refused"
    assert outcome["record"]["profile"] == "tale"
    assert outcome["record"]["selection"] == "tale"


def test_retry_after_a_off_carries_no_auto(tmp_path) -> None:
    """A retry after ``A`` off rewrites the launch-time ``%auto`` away."""
    from sase.axe.run_agent_retry_spawn import _rewrite_prompt_from_live_record

    _, _, predecessor = _launch_tale(tmp_path, prompt="%auto\nDo the work")
    harness.adapt_a_off(predecessor)
    rewritten = _rewrite_prompt_from_live_record("%auto\nDo the work", str(predecessor))
    assert "%auto" not in rewritten
    assert "Do the work" in rewritten


def test_human_attach_without_auto_stays_manual(tmp_path) -> None:
    """A human ``%id(..., session=...)`` launch without ``%auto`` is manual."""
    from sase.axe.run_agent_directive_metadata import (
        AgentMetadataInputs,
        build_agent_meta,
    )
    from sase.agent._agent_session_attach_types import AgentSessionAttachLaunchPlan
    from sase.macro.directives import extract_prompt_directives

    _, _, parent_dir = _launch_tale(tmp_path)
    parent_meta = harness.read_meta(parent_dir)
    plan = AgentSessionAttachLaunchPlan(
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
        host_composed=False,
    )
    _, directives = extract_prompt_directives("Do the work")
    inputs = AgentMetadataInputs(
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
        preserved={},
        epic_work={},
        cl_name=None,
    )
    meta = build_agent_meta(
        inputs,
        directives=directives,
        agent_name="contract-agent--1",
        agent_tribe=None,
        agent_session_attach_plan=plan,
        clan_membership_plan=None,
    )
    assert read_record(meta)["profile"] == "manual"


def test_host_composed_attach_inherits(tmp_path) -> None:
    """A host-composed attach child inherits the parent member's record."""
    from dataclasses import replace

    from sase.axe.run_agent_directive_metadata import (
        AgentMetadataInputs,
        build_agent_meta,
    )
    from sase.agent._agent_session_attach_types import AgentSessionAttachLaunchPlan
    from sase.macro.directives import extract_prompt_directives

    _, _, parent_dir = _launch_tale(tmp_path)
    parent_meta = harness.read_meta(parent_dir)
    base_plan = AgentSessionAttachLaunchPlan(
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
        host_composed=False,
    )
    plan = replace(base_plan, host_composed=True)
    _, directives = extract_prompt_directives("Do the work")
    inputs = AgentMetadataInputs(
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
        preserved={},
        epic_work={},
        cl_name=None,
    )
    meta = build_agent_meta(
        inputs,
        directives=directives,
        agent_name="contract-agent--1",
        agent_tribe=None,
        agent_session_attach_plan=plan,
        clan_membership_plan=None,
    )
    record = read_record(meta)
    assert record is not None
    assert record["profile"] == "tale"
    assert record["source"] == "inherited"
