"""Planning is read-only and refuses a restart before any mutation."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from sase.agent.force_reuse_launch import ForceReuseLaunchPlan
from sase.agent.names import AgentNameWipePreview
from sase.agent.restart import AgentRestartError, plan_agent_restart
from tests._agent_restart_helpers import (
    dummy_force_plan,
    dummy_wipe_preview,
    make_restartable_agent,
    mutation_spies,
    named_agent_for,
)


def _force_cm(
    *,
    force_plan: ForceReuseLaunchPlan | None | object,
    force_error: Exception | None,
):
    if force_error is not None:
        return patch(
            "sase.agent.force_reuse_launch.plan_force_reuse_launch",
            side_effect=force_error,
        )
    if callable(force_plan):
        return patch(
            "sase.agent.force_reuse_launch.plan_force_reuse_launch",
            side_effect=force_plan,
        )
    planned = dummy_force_plan() if force_plan is ... else force_plan
    return patch(
        "sase.agent.force_reuse_launch.plan_force_reuse_launch",
        return_value=planned,
    )


def _plan(
    tmp_path: Path,
    *,
    name: str = "02p",
    done: bool = False,
    raw_prompt: str = "%id:02p\n#gh:sase\nDo the work",
    extra_meta: dict[str, object] | None = None,
    agent_family: str | None = None,
    role_suffix: str | None = None,
    force_plan: ForceReuseLaunchPlan | None | object = ...,
    force_error: Exception | None = None,
    model_override: str | None = None,
    registered: dict[str, object] | None = None,
    wipe_preview: AgentNameWipePreview | None = None,
):
    artifacts = make_restartable_agent(
        tmp_path,
        name=name,
        done=done,
        raw_prompt=raw_prompt,
        extra_meta=extra_meta,
        agent_family=agent_family,
        role_suffix=role_suffix,
    )
    agent = named_agent_for(artifacts, name=name, done=done)
    spies = mutation_spies()
    preview = (
        wipe_preview if wipe_preview is not None else dummy_wipe_preview(artifacts)
    )
    with (
        patch("sase.agent.names.find_named_agent", return_value=agent),
        patch("sase.agent.names.lookup_registered_name", return_value=registered),
        patch("sase.agent.names.preview_agent_name_wipe", return_value=preview),
        _force_cm(force_plan=force_plan, force_error=force_error),
        patch("sase.agent.running.kill_named_agent", spies["kill"]),
        patch("sase.agent.running.dismiss_named_agent", spies["dismiss"]),
        patch("sase.agent.force_reuse_launch.apply_force_reuse_launch", spies["apply"]),
        patch("sase.agent.launch_cwd.launch_agents_from_cwd", spies["launch"]),
    ):
        plan = plan_agent_restart(name, model_override=model_override)
    return plan, artifacts, spies


def test_plan_refuses_not_found(tmp_path: Path) -> None:
    spies = mutation_spies()
    with (
        patch("sase.agent.names.find_named_agent", return_value=None),
        patch("sase.agent.running.kill_named_agent", spies["kill"]),
        patch("sase.agent.running.dismiss_named_agent", spies["dismiss"]),
        patch("sase.agent.force_reuse_launch.apply_force_reuse_launch", spies["apply"]),
        patch("sase.agent.launch_cwd.launch_agents_from_cwd", spies["launch"]),
        pytest.raises(AgentRestartError) as caught,
    ):
        plan_agent_restart("missing")
    assert caught.value.reason == "not_found"
    assert "missing" in caught.value.message
    for spy in spies.values():
        spy.assert_not_called()


def test_plan_refuses_missing_raw_xprompt(tmp_path: Path) -> None:
    artifacts = make_restartable_agent(tmp_path, raw_prompt=None)
    agent = named_agent_for(artifacts)
    spies = mutation_spies()
    with (
        patch("sase.agent.names.find_named_agent", return_value=agent),
        patch("sase.agent.running.kill_named_agent", spies["kill"]),
        patch("sase.agent.running.dismiss_named_agent", spies["dismiss"]),
        patch("sase.agent.force_reuse_launch.apply_force_reuse_launch", spies["apply"]),
        patch("sase.agent.launch_cwd.launch_agents_from_cwd", spies["launch"]),
        pytest.raises(AgentRestartError) as caught,
    ):
        plan_agent_restart("02p")
    assert caught.value.reason == "no_prompt"
    assert "raw_xprompt.md" in caught.value.message
    assert ",x" in caught.value.hint
    for spy in spies.values():
        spy.assert_not_called()


def test_plan_refuses_blank_raw_xprompt(tmp_path: Path) -> None:
    with pytest.raises(AgentRestartError) as caught:
        _plan(tmp_path, raw_prompt="   \n")
    assert caught.value.reason == "no_prompt"


def test_plan_refuses_multi_segment_prompt(tmp_path: Path) -> None:
    raw = "%id:02p\n#gh:sase\nFirst\n---\n%id:03p\nSecond"
    spies = mutation_spies()
    artifacts = make_restartable_agent(tmp_path, raw_prompt=raw)
    agent = named_agent_for(artifacts)
    with (
        patch("sase.agent.names.find_named_agent", return_value=agent),
        patch("sase.agent.running.kill_named_agent", spies["kill"]),
        patch("sase.agent.running.dismiss_named_agent", spies["dismiss"]),
        patch("sase.agent.force_reuse_launch.apply_force_reuse_launch", spies["apply"]),
        patch("sase.agent.launch_cwd.launch_agents_from_cwd", spies["launch"]),
        pytest.raises(AgentRestartError) as caught,
    ):
        plan_agent_restart("02p")
    assert caught.value.reason == "multi_segment"
    for spy in spies.values():
        spy.assert_not_called()


_EPIC_ROOT_PROMPT = (
    "#gh:gh_sase-org__sase\n"
    "%id(sase-pw.1, bead=sase-pw.1)\n"
    "%clan(sase-pw, tribe=epic, summary_script=sase_clan_summary_epic)\n"
    "%model:@medium\n"
    "%auto\n"
    "#bd/work_phase_bead:sase-pw.1"
)


def test_plan_family_root_keeps_clan_not_family(tmp_path: Path) -> None:
    plan, _artifacts, spies = _plan(
        tmp_path,
        name="sase-pw.1--plan",
        raw_prompt=_EPIC_ROOT_PROMPT,
        agent_family="sase-pw.1",
        role_suffix="--plan",
        extra_meta={
            "phase_bead_id": "sase-pw.1",
            "plan_chain_root": True,
            "agent_family_role": "root",
        },
    )
    assert plan.rewritten_prompt.startswith(
        "%id(!1, clan=sase-pw, bead=sase-pw.1)\n#gh:gh_sase-org__sase\n"
    )
    assert "family=" not in plan.rewritten_prompt
    assert "%clan" not in plan.rewritten_prompt
    for spy in spies.values():
        spy.assert_not_called()


def test_plan_refuses_self_attaching_family_identity(tmp_path: Path) -> None:
    spies = mutation_spies()
    artifacts = make_restartable_agent(
        tmp_path,
        name="sase-pw.1",
        raw_prompt="Do work",
        agent_family="sase-pw.1",
        role_suffix="--code",
    )
    agent = named_agent_for(artifacts, name="sase-pw.1")
    with (
        patch("sase.agent.names.find_named_agent", return_value=agent),
        patch("sase.agent.names.lookup_registered_name", return_value=None),
        patch("sase.agent.running.kill_named_agent", spies["kill"]),
        patch("sase.agent.running.dismiss_named_agent", spies["dismiss"]),
        patch("sase.agent.force_reuse_launch.apply_force_reuse_launch", spies["apply"]),
        patch("sase.agent.launch_cwd.launch_agents_from_cwd", spies["launch"]),
        pytest.raises(AgentRestartError) as caught,
    ):
        plan_agent_restart("sase-pw.1")
    assert caught.value.reason == "identity"
    assert "family=" in caught.value.message
    assert caught.value.hint
    for spy in spies.values():
        spy.assert_not_called()


def test_plan_family_member_keeps_role_and_bead(tmp_path: Path) -> None:
    plan, _artifacts, spies = _plan(
        tmp_path,
        name="sase-oc.4--plan",
        raw_prompt="Do work",
        agent_family="sase-oc.4",
        role_suffix="--plan",
        extra_meta={"phase_bead_id": "sase-oc.4"},
    )
    assert "family=" in plan.rewritten_prompt
    assert "sase-oc.4" in plan.rewritten_prompt
    assert "plan" in plan.rewritten_prompt
    assert "bead=" in plan.rewritten_prompt
    assert "!" in plan.rewritten_prompt
    for spy in spies.values():
        spy.assert_not_called()


def test_plan_parallel_family_member_skips_family_branch(tmp_path: Path) -> None:
    plan, _artifacts, spies = _plan(
        tmp_path,
        name="sase-oc.4--plan",
        raw_prompt="%id:sase-oc.4--plan\nDo work",
        agent_family="sase-oc.4",
        role_suffix="--plan",
        extra_meta={"agent_family_parallel": True, "phase_bead_id": "sase-oc.4"},
    )
    assert "family=" not in plan.rewritten_prompt
    assert "!" in plan.rewritten_prompt
    for spy in spies.values():
        spy.assert_not_called()


def test_plan_model_override_without_effort_leaves_effort(tmp_path: Path) -> None:
    plan, _artifacts, spies = _plan(
        tmp_path,
        raw_prompt="%id:02p\n%model:sonnet\n%effort:low\nDo the work",
        model_override="opus",
    )
    assert "%model:opus" in plan.rewritten_prompt
    assert "%effort:low" in plan.rewritten_prompt
    assert plan.model_override == "opus"
    assert plan.preview.model_override_label is not None
    assert "→ opus" in plan.preview.model_override_label
    for spy in spies.values():
        spy.assert_not_called()


def test_plan_model_override_with_effort_removes_effort(tmp_path: Path) -> None:
    plan, _artifacts, _spies = _plan(
        tmp_path,
        raw_prompt="%id:02p\n%model:sonnet\n%effort:low\nDo the work",
        model_override="opus@high",
    )
    assert "%model:opus@high" in plan.rewritten_prompt
    assert "%effort:" not in plan.rewritten_prompt


def test_plan_preflight_failure_surfaces_underlying_message(tmp_path: Path) -> None:
    spies = mutation_spies()
    artifacts = make_restartable_agent(tmp_path)
    agent = named_agent_for(artifacts)
    with (
        patch("sase.agent.names.find_named_agent", return_value=agent),
        patch("sase.agent.names.lookup_registered_name", return_value=None),
        patch(
            "sase.agent.force_reuse_launch.plan_force_reuse_launch",
            side_effect=RuntimeError("name '02p' is already reserved"),
        ),
        patch("sase.agent.running.kill_named_agent", spies["kill"]),
        patch("sase.agent.running.dismiss_named_agent", spies["dismiss"]),
        patch("sase.agent.force_reuse_launch.apply_force_reuse_launch", spies["apply"]),
        patch("sase.agent.launch_cwd.launch_agents_from_cwd", spies["launch"]),
        pytest.raises(AgentRestartError) as caught,
    ):
        plan_agent_restart("02p")
    assert caught.value.reason == "preflight"
    assert caught.value.message == "name '02p' is already reserved"
    for spy in spies.values():
        spy.assert_not_called()


def test_plan_name_not_reusable_when_force_marker_vanishes(tmp_path: Path) -> None:
    with pytest.raises(AgentRestartError) as caught:
        _plan(tmp_path, force_plan=None)
    assert caught.value.reason == "name_not_reusable"


def test_plan_injects_forced_id_for_plain_prompt(tmp_path: Path) -> None:
    raw = "#gh:gh_bobs-org__bob-cli Describe this repo. #m_sonnet"

    def fake_force(prompt: str) -> ForceReuseLaunchPlan | None:
        if "%id:!061" in prompt:
            return dummy_force_plan(prompt, owner_names=["061"])
        return None

    plan, _artifacts, spies = _plan(
        tmp_path,
        name="061",
        raw_prompt=raw,
        force_plan=fake_force,
    )
    assert plan.name_reuse_source == "prompt"
    assert "from prompt" in plan.preview.name_reuse
    assert "%id:!061" in plan.rewritten_prompt
    assert plan.rewritten_prompt.startswith("%id:!061")
    from sase.xprompt import extract_vcs_workflow_tag

    tag = extract_vcs_workflow_tag(plan.rewritten_prompt)
    assert tag is not None
    assert "gh_bobs-org__bob-cli" in tag
    for spy in spies.values():
        spy.assert_not_called()


def test_plan_name_reuse_source_is_prompt_when_id_already_present(
    tmp_path: Path,
) -> None:
    from sase.agent.relaunch_prompt import prepare_kill_and_edit_prompt

    raw = "%id:02p\n#gh:sase\nDo the work"
    plan, _artifacts, spies = _plan(tmp_path, raw_prompt=raw)
    assert plan.name_reuse_source == "prompt"
    assert "from prompt" in plan.preview.name_reuse
    assert plan.rewritten_prompt == prepare_kill_and_edit_prompt(raw, "02p")
    for spy in spies.values():
        spy.assert_not_called()


def test_plan_family_member_is_not_double_rewritten(tmp_path: Path) -> None:
    plan, _artifacts, spies = _plan(
        tmp_path,
        name="sase-oc.4--plan",
        raw_prompt="Do work",
        agent_family="sase-oc.4",
        role_suffix="--plan",
        extra_meta={"phase_bead_id": "sase-oc.4"},
    )
    assert plan.name_reuse_source == "prompt"
    assert plan.rewritten_prompt.count("%id") == 1
    assert "family=" in plan.rewritten_prompt
    for spy in spies.values():
        spy.assert_not_called()


def test_plan_fanout_prompt_raises_fanout_not_preflight(tmp_path: Path) -> None:
    with pytest.raises(AgentRestartError) as caught:
        _plan(
            tmp_path,
            raw_prompt="%{First | Second}\n#gh:sase\nDo the work",
            force_plan=None,
        )
    assert caught.value.reason == "fanout"
    assert "preflight" not in caught.value.reason
    assert "fan-out" in caught.value.message


def test_plan_container_name_raises_before_mutation(tmp_path: Path) -> None:
    spies = mutation_spies()
    artifacts = make_restartable_agent(tmp_path, name="fam")
    agent = named_agent_for(artifacts, name="fam")
    with (
        patch("sase.agent.names.find_named_agent", return_value=agent),
        patch(
            "sase.agent.names.lookup_registered_name",
            return_value={"name": "fam", "container_kind": "family"},
        ),
        patch("sase.agent.names.preview_agent_name_wipe") as preview,
        patch("sase.agent.force_reuse_launch.plan_force_reuse_launch") as force,
        patch("sase.agent.running.kill_named_agent", spies["kill"]),
        patch("sase.agent.running.dismiss_named_agent", spies["dismiss"]),
        patch("sase.agent.force_reuse_launch.apply_force_reuse_launch", spies["apply"]),
        patch("sase.agent.launch_cwd.launch_agents_from_cwd", spies["launch"]),
        pytest.raises(AgentRestartError) as caught,
    ):
        plan_agent_restart("fam")
    assert caught.value.reason == "container"
    assert "family" in caught.value.message
    preview.assert_not_called()
    force.assert_not_called()
    for spy in spies.values():
        spy.assert_not_called()


def test_plan_collects_file_change_and_home_warnings(tmp_path: Path) -> None:
    plan, _artifacts, _spies = _plan(
        tmp_path,
        done=True,
        raw_prompt="%id:02p\nDo the work",
        extra_meta={"commit_diff_path": "/tmp/diff.patch"},
    )
    assert any("file changes" in warning for warning in plan.preview.warnings)
    assert any("no VCS tag" in warning for warning in plan.preview.warnings)
    assert plan.preview.is_live is False
    assert plan.preview.has_file_changes is True
    assert plan.preview.status == "DONE"
    assert isinstance(plan.preview.project_display, str)
    assert plan.preview.project_display
