"""Tests for the fast planned ``sase bead work`` launch adapter."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from sase.agent.launch_guard import DisabledProviderLaunchError
from sase.llm_provider.provider_disable import PROVIDER_DISABLE_MODE_SOFT
from tests.agent._launch_guard_helpers import (
    disable,
    install_disables,
    pin_cli_available,
)


def _bead_segments() -> tuple[list[str], list[dict[str, str]], set[str]]:
    segments = [
        "#git:proj\n%id(proj-epic.1, bead=proj-epic.1)\n"
        "%clan(proj-epic, tribe=epic)\n%model:@worker\n"
        "%auto\n#bd/work_phase_bead:proj-epic.1",
        "#git:proj\n%id(land, clan=proj-epic, bead=proj-epic)\n"
        "%auto\n%w:proj-epic.1\n#bd/land_epic:proj-epic",
    ]
    envs = [
        {"SASE_BEAD_ID": "proj-epic.1", "SASE_INTERNAL_AGENT_NAME_BYPASS": "1"},
        {"SASE_BEAD_ID": "proj-epic", "SASE_INTERNAL_AGENT_NAME_BYPASS": "1"},
    ]
    return segments, envs, {"proj-epic.1", "proj-epic.land"}


def test_adapter_passes_one_slot_preplanned_plans(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.agent import launch_cwd

    segments, envs, expected = _bead_segments()
    captured: dict[str, Any] = {}

    def fake_launch_multi(**kwargs: Any) -> list[object]:
        captured.update(kwargs)
        return [object(), object()]

    monkeypatch.setattr(
        "sase.agent.multi_prompt_launcher.launch_multi_prompt_agents",
        fake_launch_multi,
    )
    monkeypatch.setattr(
        "sase.history.prompt.add_or_update_prompt", lambda *a, **k: None
    )
    monkeypatch.setattr("sase.agent.names.get_reserved_agent_names", lambda: set())
    install_disables(monkeypatch, {})

    results = launch_cwd.launch_planned_bead_work_agents(
        segments=segments,
        segment_extra_env=envs,
        expected_names=expected,
        project_name="proj",
    )

    assert len(results) == 2
    plans = captured["preplanned_fanout_plans"]
    assert len(plans) == len(segments)
    # Every segment is preplanned as a single slot so the generic launcher never
    # expands the bead xprompts to discover there is no fan-out.
    assert all(len(plan.slots) == 1 for plan in plans)
    assert captured["project_name"] == "proj"
    assert captured["is_home_mode"] is False
    assert list(captured["segment_extra_env"]) == envs
    # All segments carry the internal-name bypass env, so reserved-family names
    # are permitted.
    assert captured["allow_reserved_family_separator_names"] is True
    assert captured["local_xprompts"] == {}


def test_adapter_rejects_unexpected_rendered_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.agent import launch_cwd

    segments, envs, _ = _bead_segments()
    monkeypatch.setattr(
        "sase.agent.multi_prompt_launcher.launch_multi_prompt_agents",
        lambda **kwargs: pytest.fail("must not launch on name mismatch"),
    )

    with pytest.raises(ValueError, match="do not match planned names"):
        launch_cwd.launch_planned_bead_work_agents(
            segments=segments,
            segment_extra_env=envs,
            expected_names={"proj-epic.1"},  # missing the land name
            project_name="proj",
        )


def test_adapter_rejects_fanout_segment(monkeypatch: pytest.MonkeyPatch) -> None:
    from sase.agent import launch_cwd

    segments, envs, expected = _bead_segments()
    monkeypatch.setattr(
        "sase.agent.multi_prompt_launcher.launch_multi_prompt_agents",
        lambda **kwargs: pytest.fail("must not launch when a segment fans out"),
    )
    # Force the fan-out detector to flag the first segment.
    monkeypatch.setattr(
        "sase.xprompt.directives.plan_prompt_fanout_variants",
        lambda segment, **kwargs: object(),
    )

    with pytest.raises(ValueError, match="fan-out directive"):
        launch_cwd.launch_planned_bead_work_agents(
            segments=segments,
            segment_extra_env=envs,
            expected_names=expected,
            project_name="proj",
        )


def test_adapter_rejects_mismatched_env_length() -> None:
    from sase.agent import launch_cwd

    with pytest.raises(ValueError, match="one entry per bead-work segment"):
        launch_cwd.launch_planned_bead_work_agents(
            segments=["a", "b"],
            segment_extra_env=[{}],
            expected_names=set(),
            project_name="proj",
        )


def _explicit_claude_segment() -> tuple[list[str], list[dict[str, str]], set[str]]:
    segments = [
        "#git:proj\n%id(proj-epic.1, bead=proj-epic.1)\n"
        "%clan(proj-epic, tribe=epic)\n%model:claude/opus\n"
        "%auto\n#bd/work_phase_bead:proj-epic.1",
    ]
    envs = [{"SASE_BEAD_ID": "proj-epic.1", "SASE_INTERNAL_AGENT_NAME_BYPASS": "1"}]
    return segments, envs, {"proj-epic.1"}


def test_adapter_refuses_hard_disabled_provider_before_spawn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.agent import launch_cwd

    segments, envs, expected = _explicit_claude_segment()
    pin_cli_available(monkeypatch)
    install_disables(monkeypatch, {"claude": disable("claude")})
    recorded: list[str] = []
    monkeypatch.setattr(
        "sase.history.prompt.record_failed_launch_prompt",
        recorded.append,
    )
    monkeypatch.setattr(
        "sase.history.prompt.add_or_update_prompt", lambda *a, **k: None
    )
    monkeypatch.setattr("sase.agent.names.get_reserved_agent_names", lambda: set())
    monkeypatch.setattr(
        "sase.agent.multi_prompt_launcher.launch_multi_prompt_agents",
        lambda **kwargs: pytest.fail("must not spawn a hard-disabled bead-work unit"),
    )

    with pytest.raises(DisabledProviderLaunchError) as exc_info:
        launch_cwd.launch_planned_bead_work_agents(
            segments=segments,
            segment_extra_env=envs,
            expected_names=expected,
            project_name="proj",
        )

    assert recorded
    assert "Launch Control" in str(exc_info.value)


def test_adapter_launches_when_provider_is_only_soft_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.agent import launch_cwd

    segments, envs, expected = _explicit_claude_segment()
    pin_cli_available(monkeypatch)
    install_disables(
        monkeypatch,
        {"claude": disable("claude", mode=PROVIDER_DISABLE_MODE_SOFT)},
    )
    monkeypatch.setattr(
        "sase.history.prompt.add_or_update_prompt", lambda *a, **k: None
    )
    monkeypatch.setattr("sase.agent.names.get_reserved_agent_names", lambda: set())
    launched: list[object] = []

    def fake_launch_multi(**kwargs: Any) -> list[object]:
        launched.append(kwargs)
        return [object()]

    monkeypatch.setattr(
        "sase.agent.multi_prompt_launcher.launch_multi_prompt_agents",
        fake_launch_multi,
    )

    results = launch_cwd.launch_planned_bead_work_agents(
        segments=segments,
        segment_extra_env=envs,
        expected_names=expected,
        project_name="proj",
    )

    assert len(results) == 1
    assert launched


def test_adapter_guard_failure_logs_and_launches(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from sase.agent import launch_cwd

    segments, envs, expected = _bead_segments()
    monkeypatch.setattr(
        "sase.history.prompt.add_or_update_prompt", lambda *a, **k: None
    )
    monkeypatch.setattr("sase.agent.names.get_reserved_agent_names", lambda: set())
    monkeypatch.setattr(
        "sase.agent.launch_guard.blocked_launch_units",
        lambda *a, **k: (_ for _ in ()).throw(ValueError("guard exploded")),
    )
    launched: list[object] = []

    def fake_launch_multi(**kwargs: Any) -> list[object]:
        launched.append(kwargs)
        return [object(), object()]

    monkeypatch.setattr(
        "sase.agent.multi_prompt_launcher.launch_multi_prompt_agents",
        fake_launch_multi,
    )

    with caplog.at_level(logging.WARNING, logger="sase.agent.launch_cwd_bead_work"):
        results = launch_cwd.launch_planned_bead_work_agents(
            segments=segments,
            segment_extra_env=envs,
            expected_names=expected,
            project_name="proj",
        )

    assert len(results) == 2
    assert launched
    assert "failed open" in caplog.text


def test_bead_work_ref_canonicalizes_owner_repo_known_project(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from sase.agent.launch_cwd_bead_work import _canonicalize_bead_work_ref

    workspace = tmp_path / "projects" / "github" / "sase-org" / "sase"
    workspace.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(
        "sase.project_aliases.load_project_alias_map",
        lambda projects_root=None: {},
    )
    monkeypatch.setattr(
        "sase.xprompt.loader.get_known_project_workspaces",
        lambda: {"sase": str(workspace)},
    )

    assert _canonicalize_bead_work_ref("sase-org/sase") == "sase"


def test_routing_uses_adapter_when_launch_context_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.bead import cli_work
    from sase.bead.work import VCSLaunchContext

    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        "sase.agent.launcher.launch_planned_bead_work_agents",
        lambda **kwargs: captured.update(kwargs) or ["adapter-result"],
    )
    monkeypatch.setattr(
        "sase.agent.launcher.launch_agent_from_cwd",
        lambda *a, **k: pytest.fail("adapter path must not call launch_agent_from_cwd"),
    )

    query = "#git:proj\n%id:a\n#x:1\n---\n#git:proj\n%id:b\n#y:2"
    envs = ({"SASE_BEAD_ID": "1"}, {"SASE_BEAD_ID": "2"})

    results = cli_work._launch_bead_work_agents(
        query,
        segment_extra_env=envs,
        expected_names={"a", "b"},
        launch_context=VCSLaunchContext(vcs_workflow="git", project_name="proj"),
    )

    assert results == ["adapter-result"]
    assert captured["segments"] == query.split("\n---\n")
    assert captured["segment_extra_env"] == envs
    assert captured["expected_names"] == {"a", "b"}
    assert captured["project_name"] == "proj"


def test_routing_falls_back_without_launch_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.bead import cli_work

    monkeypatch.setattr(
        "sase.agent.launcher.launch_planned_bead_work_agents",
        lambda **kwargs: pytest.fail("no-context path must not use the adapter"),
    )

    captured: dict[str, Any] = {}

    def fake_single(query: str, extra_env: Any = None, segment_extra_env: Any = None):
        captured["query"] = query
        captured["segment_extra_env"] = segment_extra_env
        return "single-result"

    monkeypatch.setattr("sase.agent.launcher.launch_agent_from_cwd", fake_single)

    results = cli_work._launch_bead_work_agents(
        "bare prompt",
        segment_extra_env=({"SASE_BEAD_ID": "1"},),
        expected_names=set(),
        launch_context=None,
    )

    assert results == ["single-result"]
    assert captured["query"] == "bare prompt"
    assert captured["segment_extra_env"] == ({"SASE_BEAD_ID": "1"},)


@patch("sase.agent.launcher.spawn_agent_subprocess")
@patch("sase.core.time.generate_timestamp")
@patch("sase.artifacts.create_artifacts_directory")
@patch("sase.agent.names.get_reserved_agent_names", return_value=set())
@patch("sase.running_field.claim_next_axe_workspace")
@patch("sase.running_field.get_workspace_directory_for_num")
def test_preplanned_one_slot_plans_spawn_each_segment_verbatim(
    mock_ws_dir: MagicMock,
    mock_first_ws: MagicMock,
    mock_reserved: MagicMock,
    mock_create_artifacts: MagicMock,
    mock_timestamp: MagicMock,
    mock_spawn: MagicMock,
) -> None:
    """Multi-segment preplanned one-slot plans spawn each segment as-is.

    This is the mechanism the bead-work adapter relies on: every segment is fed
    through as a single slot with its own env, with no fan-out expansion.
    """
    from sase.agent.multi_prompt_launcher import launch_multi_prompt_agents
    from sase.core.agent_launch_facade import plan_fake_fanout

    mock_first_ws.side_effect = [100, 101]
    mock_ws_dir.side_effect = [("/ws/100", None), ("/ws/101", None)]
    mock_timestamp.return_value = "260501_120000"
    mock_create_artifacts.return_value = "/artifacts/dir"
    mock_spawn.return_value = MagicMock(pid=1)

    from sase.agent.clan_membership import CLAN_MEMBERSHIP_ENV

    segments = [
        "%id:phase\n%family(land, role=phase)\nwork one",
        "%id:land\nwork two",
    ]
    plans = [plan_fake_fanout("multi_prompt", [segment]) for segment in segments]

    results = launch_multi_prompt_agents(
        segments=segments,
        local_xprompts={},
        cl_name="t",
        project_file="/t.sase",
        project_name="t",
        is_home_mode=False,
        vcs_ref=None,
        preplanned_fanout_plans=plans,
        segment_extra_env=[{"SASE_BEAD_ID": "1"}, {"SASE_BEAD_ID": "2"}],
    )

    assert len(results) == 2
    assert mock_spawn.call_count == 2
    calls = mock_spawn.call_args_list
    assert [c.kwargs["prompt"] for c in calls] == segments
    assert calls[0].kwargs["extra_env"]["SASE_BEAD_ID"] == "1"
    assert calls[1].kwargs["extra_env"]["SASE_BEAD_ID"] == "2"
    assert CLAN_MEMBERSHIP_ENV not in calls[0].kwargs["extra_env"]
    assert CLAN_MEMBERSHIP_ENV not in calls[1].kwargs["extra_env"]
    # No fan-out probing means the naming-wait artifacts path is never hit.
    assert mock_create_artifacts.call_count == 0
