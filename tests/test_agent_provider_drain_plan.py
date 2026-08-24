"""Planning a provider drain is read-only and never aborts for one bad row."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from sase.agent.provider_drain import ProviderDrainError, plan_provider_drain
from sase.agent.running_listing import RunningAgentInfo
from sase.llm_provider.provider_disable import TemporaryProviderDisable
from tests._agent_restart_helpers import (
    dummy_force_plan,
    dummy_wipe_preview,
    make_restartable_agent,
    named_agent_for,
)

_DEFAULT_PROMPT = "%id:02p\n#gh:sase\nDo the work"


def _hard_disable(provider: str = "claude") -> TemporaryProviderDisable:
    return TemporaryProviderDisable(
        version=2,
        provider=provider,
        created_at=1_800_000_000.0,
        expires_at=None,
        source="test",
        mode="hard",
    )


def _row(
    artifacts_dir: Path,
    *,
    name: str = "02p",
    status: str = "RUNNING",
    provider: str = "claude",
) -> RunningAgentInfo:
    return RunningAgentInfo(
        name=name,
        project="gh_sase-org__sase",
        pid=481920,
        model="opus",
        provider=provider,
        workspace_num=1,
        duration="2m",
        approve=False,
        status=status,
        artifacts_dir=str(artifacts_dir),
    )


def _plan_drain(
    rows: list[RunningAgentInfo],
    *,
    provider: str = "claude",
    disable: TemporaryProviderDisable | None = None,
    model_override: str | None = None,
    limit: int = 20,
    force_plan: object = ...,
):
    resolved_disable = disable if disable is not None else _hard_disable(provider)
    planned = dummy_force_plan() if force_plan is ... else force_plan
    with (
        patch(
            "sase.llm_provider.provider_disable.get_active_provider_disable",
            return_value=resolved_disable,
        ),
        patch("sase.agent.running_listing.list_all_agents", return_value=rows),
        patch("sase.agent.identity.discover_agent_identity", return_value=None),
        patch("sase.agent.names.find_named_agent", side_effect=_lookup_agent(rows)),
        patch("sase.agent.names.lookup_registered_name", return_value=None),
        patch(
            "sase.agent.names.preview_agent_name_wipe",
            return_value=dummy_wipe_preview(),
        ),
        patch(
            "sase.agent.force_reuse_launch.plan_force_reuse_launch",
            return_value=planned,
        ),
    ):
        return plan_provider_drain(provider, model_override=model_override, limit=limit)


def _lookup_agent(rows: list[RunningAgentInfo]):
    by_name = {row.name: row for row in rows if row.name is not None}

    def _find(name: str):
        row = by_name.get(name)
        if row is None or row.artifacts_dir is None:
            return None
        return named_agent_for(Path(row.artifacts_dir), name=name)

    return _find


def test_refuses_when_provider_has_no_active_disable() -> None:
    with (
        patch(
            "sase.llm_provider.provider_disable.get_active_provider_disable",
            return_value=None,
        ),
        pytest.raises(ProviderDrainError) as caught,
    ):
        plan_provider_drain("claude")
    assert caught.value.reason == "not_disabled"


def test_refuses_when_disable_is_soft_only() -> None:
    soft = TemporaryProviderDisable(
        version=2,
        provider="claude",
        created_at=1_800_000_000.0,
        expires_at=None,
        source="test",
        mode="soft",
    )
    with (
        patch(
            "sase.llm_provider.provider_disable.get_active_provider_disable",
            return_value=soft,
        ),
        pytest.raises(ProviderDrainError) as caught,
    ):
        plan_provider_drain("claude")
    assert caught.value.reason == "soft_disabled"


def test_reroutes_a_candidate_whose_alias_still_has_an_enabled_member(
    tmp_path: Path,
) -> None:
    artifacts_dir = make_restartable_agent(
        tmp_path, name="02p", raw_prompt=_DEFAULT_PROMPT
    )
    row = _row(artifacts_dir)
    unit = _fake_unit(blocked=False, provider="codex", model="gpt-5")
    with patch("sase.agent.launch_guard.plan_launch_units", return_value=(unit,)):
        plan = _plan_drain([row])
    assert [m.name for m in plan.moves] == ["02p"]
    assert plan.moves[0].route.kind == "reroute"
    assert plan.moves[0].route.target_provider == "codex"
    assert plan.skips == ()


def test_strands_a_candidate_pinned_to_the_disabled_provider(tmp_path: Path) -> None:
    artifacts_dir = make_restartable_agent(
        tmp_path, name="02p", raw_prompt=_DEFAULT_PROMPT
    )
    row = _row(artifacts_dir)
    unit = _fake_unit(blocked=True, provider="claude", model="opus")
    with patch("sase.agent.launch_guard.plan_launch_units", return_value=(unit,)):
        plan = _plan_drain([row])
    assert plan.moves == ()
    assert [s.reason for s in plan.skips] == ["stranded"]
    assert "claude/opus" in plan.skips[0].detail


def test_a_restart_refusal_becomes_a_skip_and_does_not_abort_the_plan(
    tmp_path: Path,
) -> None:
    ok_dir = make_restartable_agent(tmp_path, name="02p", raw_prompt=_DEFAULT_PROMPT)
    missing_prompt_dir = make_restartable_agent(
        tmp_path, name="03p", raw_prompt=None, suffix="20260818130000"
    )
    rows = [_row(ok_dir, name="02p"), _row(missing_prompt_dir, name="03p")]
    unit = _fake_unit(blocked=False, provider="codex", model="gpt-5")
    with patch("sase.agent.launch_guard.plan_launch_units", return_value=(unit,)):
        plan = _plan_drain(rows)
    assert [m.name for m in plan.moves] == ["02p"]
    skip_reasons = {s.name: s.reason for s in plan.skips}
    assert skip_reasons["03p"] == "no_prompt"


def test_a_different_restart_refusal_reason_passes_through_verbatim(
    tmp_path: Path,
) -> None:
    multi_segment_dir = make_restartable_agent(
        tmp_path,
        name="04p",
        raw_prompt="%id:04p\n#gh:sase\nFirst\n---\n%id:05p\nSecond",
    )
    rows = [_row(multi_segment_dir, name="04p")]
    unit = _fake_unit(blocked=False, provider="codex", model="gpt-5")
    with patch("sase.agent.launch_guard.plan_launch_units", return_value=(unit,)):
        plan = _plan_drain(rows)
    assert plan.moves == ()
    assert [s.reason for s in plan.skips] == ["multi_segment"]


def test_limit_truncates_moves_and_reports_the_rest_as_capped(tmp_path: Path) -> None:
    rows = []
    for index in range(3):
        artifacts_dir = make_restartable_agent(
            tmp_path,
            name=f"agent{index}",
            raw_prompt=f"%id:agent{index}\n#gh:sase\nDo the work",
            suffix=f"2026081812000{index}",
        )
        rows.append(_row(artifacts_dir, name=f"agent{index}", status="WAITING"))
    unit = _fake_unit(blocked=False, provider="codex", model="gpt-5")
    with patch("sase.agent.launch_guard.plan_launch_units", return_value=(unit,)):
        plan = _plan_drain(rows, limit=2)
    assert len(plan.moves) == 2
    capped = [s for s in plan.skips if s.reason == "capped"]
    assert len(capped) == 1
    assert plan.limit == 2


def _fake_unit(*, blocked: bool, provider: str, model: str):
    from sase.agent.launch_guard import LaunchUnit, LaunchUnitCandidate

    candidate = LaunchUnitCandidate(
        slot_index=0,
        prompt="Do the work",
        provider=provider,
        model=model,
        blocked_by=_hard_disable(provider) if blocked else None,
        unavailable=False,
    )
    return LaunchUnit(
        index=0,
        total=1,
        prompt="Do the work",
        template_group=None,
        swarm_xprompts=(),
        candidates=(candidate,),
    )
