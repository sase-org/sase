"""Tests for xprompt template-group launch planning."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tests._agent_names_fixtures import make_agent
from tests._multi_prompt_launcher_launch_helpers import spawn_result_with_planned_name
from sase.agent.multi_prompt_launcher import launch_multi_prompt_agents
from sase.xprompt.models import XPrompt


@patch("sase.agent.launcher.spawn_agent_subprocess")
@patch("sase.agent.multi_prompt_launcher._wait_for_agent_naming")
@patch("sase.core.time.generate_timestamp", return_value="260501_120000")
@patch("sase.artifacts.create_artifacts_directory", return_value="/a")
@patch("sase.history.prompt.add_or_update_prompt")
@patch(
    "sase.main.utils.ensure_project_file_and_get_workspace_num",
    return_value=(None, None, None),
)
def test_launch_agents_from_cwd_resolves_template_refs_after_multi_xprompt_expansion(
    mock_project: MagicMock,
    mock_history: MagicMock,
    mock_create_artifacts: MagicMock,
    mock_timestamp: MagicMock,
    mock_wait: MagicMock,
    mock_spawn: MagicMock,
    tmp_path: Path,
) -> None:
    """The cwd launch path resolves template refs after xprompt swarm expansion."""
    from sase.agent.launcher import launch_agents_from_cwd

    mock_spawn.side_effect = spawn_result_with_planned_name
    catalog = {
        "ix": XPrompt(
            name="ix",
            content="%i:flow-@\nBuild\n---\n%w:flow-@\nReview",
        )
    }

    with (
        patch.object(Path, "home", return_value=tmp_path),
        patch("sase.agent.xprompt_swarm.get_all_xprompts", return_value=catalog),
        patch(
            "sase.agent.launch_projects.extract_known_project_vcs_launch_ref",
            return_value=None,
        ),
        patch(
            "sase.running_field.claim_next_axe_workspace",
            side_effect=[100, 101],
        ),
        patch(
            "sase.running_field.get_workspace_directory_for_num",
            side_effect=[("/ws1", None), ("/ws2", None)],
        ),
    ):
        results = launch_agents_from_cwd("#!ix")

    assert [result.agent_name for result in results] == ["flow-0", None]
    assert [call.kwargs["prompt"] for call in mock_spawn.call_args_list] == [
        "%i:flow-@\n#git:home Build",
        "%w:flow-0\n#git:home Review",
    ]
    assert mock_wait.call_count == 0
    assert mock_create_artifacts.call_count == 0


@patch("sase.agent.launcher.spawn_agent_subprocess")
@patch("sase.agent.multi_prompt_launcher._wait_for_agent_naming")
@patch("sase.core.time.generate_timestamp", return_value="260501_120000")
@patch("sase.artifacts.create_artifacts_directory", return_value="/a")
@patch("sase.history.prompt.add_or_update_prompt")
@patch(
    "sase.main.utils.ensure_project_file_and_get_workspace_num",
    return_value=(None, None, None),
)
def test_launch_agents_from_cwd_groups_xprompt_template_names_by_invocation(
    mock_project: MagicMock,
    mock_history: MagicMock,
    mock_create_artifacts: MagicMock,
    mock_timestamp: MagicMock,
    mock_wait: MagicMock,
    mock_spawn: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Template names from one xprompt swarm invocation share a namespace."""
    from sase.agent.launcher import launch_agents_from_cwd
    from sase.agent.names import reset_name_registry_caches_for_tests

    del mock_project, mock_history, mock_timestamp
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    reset_name_registry_caches_for_tests()
    marker = tmp_path / ".sase" / "agent_name_auto_migration.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        '{"schema_version": 1, "completed": true, "migrated_count": 0}\n',
        encoding="utf-8",
    )
    make_agent(tmp_path, "proj", "existing", "research.0.any", done=True)
    mock_spawn.side_effect = spawn_result_with_planned_name
    catalog = {
        "swarm": XPrompt(
            name="swarm",
            content=(
                "%id:research.@.cdx\nCDX\n"
                "---\n"
                "%id:research.@.cld\nCLD\n"
                "---\n"
                "%id:research.@.final\nFinal\n"
                "---\n"
                "%id:research.@.image\nImage"
            ),
        )
    }

    with (
        patch.object(Path, "home", return_value=tmp_path),
        patch("sase.agent.xprompt_swarm.get_all_xprompts", return_value=catalog),
        patch(
            "sase.agent.launch_projects.extract_known_project_vcs_launch_ref",
            return_value=None,
        ),
        patch(
            "sase.running_field.claim_next_axe_workspace",
            side_effect=[100, 101, 102, 103],
        ),
        patch(
            "sase.running_field.get_workspace_directory_for_num",
            side_effect=[
                ("/ws1", None),
                ("/ws2", None),
                ("/ws3", None),
                ("/ws4", None),
            ],
        ),
    ):
        results = launch_agents_from_cwd("#!swarm")

    assert [result.agent_name for result in results] == [
        "research.1.cdx",
        "research.1.cld",
        "research.1.final",
        "research.1.image",
    ]
    assert mock_wait.call_count == 0
    assert mock_create_artifacts.call_count == 0


@patch("sase.history.prompt.add_or_update_prompt")
@patch(
    "sase.main.utils.ensure_project_file_and_get_workspace_num",
    return_value=(None, None, None),
)
def test_launch_agents_from_cwd_segment_extra_env_shares_xprompt_group_counter(
    mock_project: MagicMock,
    mock_history: MagicMock,
    tmp_path: Path,
) -> None:
    """Per-segment expansion with env still separates xprompt invocations."""
    from sase.agent.launcher import launch_agents_from_cwd

    del mock_project, mock_history
    catalog = {
        "swarm": XPrompt(
            name="swarm",
            content="%id:research.@.cdx\nCDX\n---\n%id:research.@.cld\nCLD",
        )
    }

    with (
        patch.object(Path, "home", return_value=tmp_path),
        patch("sase.agent.xprompt_swarm.get_all_xprompts", return_value=catalog),
        patch(
            "sase.agent.launch_projects.extract_known_project_vcs_launch_ref",
            return_value=None,
        ),
        patch(
            "sase.agent.multi_prompt_launcher.launch_multi_prompt_agents",
            return_value=[],
        ) as launch_multi,
    ):
        launch_agents_from_cwd(
            "#!swarm\n---\n#!swarm",
            segment_extra_env=({"SLOT": "one"}, {"SLOT": "two"}),
        )

    kwargs = launch_multi.call_args.kwargs
    assert kwargs["segment_extra_env"] == [
        {"SLOT": "one"},
        {"SLOT": "one"},
        {"SLOT": "two"},
        {"SLOT": "two"},
    ]
    assert kwargs["segment_template_groups"] == [
        "xprompt:swarm:0",
        "xprompt:swarm:0",
        "xprompt:swarm:1",
        "xprompt:swarm:1",
    ]
    assert kwargs["segment_swarm_xprompts"] == [
        ("swarm",),
        ("swarm",),
        ("swarm",),
        ("swarm",),
    ]


@patch("sase.history.prompt.add_or_update_prompt")
@patch(
    "sase.main.utils.ensure_project_file_and_get_workspace_num",
    return_value=(None, None, None),
)
def test_launch_agents_from_cwd_force_reuse_marker_applies_to_first_swarm_slot_only(
    mock_project: MagicMock,
    mock_history: MagicMock,
    tmp_path: Path,
) -> None:
    """The one-shot force-reuse bead marker goes to only the first swarm slot.

    Unlike an ordinary segment_extra_env marker (which every xprompt-swarm
    slot of a segment shares), ``SASE_AGENT_FORCE_REUSE_BEAD`` is a one-shot
    authorization tied to exactly one killed agent's name. Copying it to every
    expanded slot would let more than one spawned agent try to consume it.
    """
    from sase.agent.force_reuse_bead import SASE_AGENT_FORCE_REUSE_BEAD_ENV
    from sase.agent.launcher import launch_agents_from_cwd

    del mock_project, mock_history
    catalog = {
        "swarm": XPrompt(
            name="swarm",
            content="%id:research.@.cdx\nCDX\n---\n%id:research.@.cld\nCLD",
        )
    }
    marker = {SASE_AGENT_FORCE_REUSE_BEAD_ENV: '{"bead_id":"sase-1","owner_name":"a"}'}

    with (
        patch.object(Path, "home", return_value=tmp_path),
        patch("sase.agent.xprompt_swarm.get_all_xprompts", return_value=catalog),
        patch(
            "sase.agent.launch_projects.extract_known_project_vcs_launch_ref",
            return_value=None,
        ),
        patch(
            "sase.agent.multi_prompt_launcher.launch_multi_prompt_agents",
            return_value=[],
        ) as launch_multi,
    ):
        launch_agents_from_cwd(
            "#!swarm\n---\n#!swarm",
            segment_extra_env=(marker, {"SLOT": "two"}),
        )

    kwargs = launch_multi.call_args.kwargs
    assert kwargs["segment_extra_env"] == [
        marker,
        None,
        {"SLOT": "two"},
        {"SLOT": "two"},
    ]


@patch("sase.agent.launcher.spawn_agent_subprocess")
@patch("sase.core.time.generate_timestamp", return_value="260501_120000")
@patch(
    "sase.main.utils.ensure_project_file_and_get_workspace_num",
    return_value=(None, None, None),
)
def test_launch_agents_from_cwd_passes_single_segment_swarm_provenance(
    mock_project: MagicMock,
    mock_timestamp: MagicMock,
    mock_spawn: MagicMock,
    tmp_path: Path,
) -> None:
    """A one-segment swarm keeps provenance on the single-agent path."""
    from sase.agent.launcher import launch_agents_from_cwd
    from sase.xprompt.used_xprompts import SASE_LAUNCH_SWARM_XPROMPTS

    del mock_project, mock_timestamp
    mock_spawn.side_effect = spawn_result_with_planned_name
    catalog = {
        "swarm": XPrompt(
            name="swarm",
            content="Only one segment\n---\n",
        )
    }

    with (
        patch.object(Path, "home", return_value=tmp_path),
        patch("sase.agent.xprompt_swarm.get_all_xprompts", return_value=catalog),
        patch(
            "sase.agent.launch_projects.extract_known_project_vcs_launch_ref",
            return_value=None,
        ),
    ):
        launch_agents_from_cwd("#swarm")

    assert (
        mock_spawn.call_args.kwargs["extra_env"][SASE_LAUNCH_SWARM_XPROMPTS]
        == '["swarm"]'
    )


@patch("sase.history.prompt.add_or_update_prompt")
@patch(
    "sase.main.utils.ensure_project_file_and_get_workspace_num",
    return_value=(None, None, None),
)
def test_launcher_qualifies_research_swarm_per_dispatch(
    mock_project: MagicMock,
    mock_history: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A later keyed swarm gets a new hood without changing prior prompt text."""
    from sase.agent.launcher import launch_agents_from_cwd
    from sase.agent.names import reset_name_registry_caches_for_tests

    del mock_project, mock_history
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    reset_name_registry_caches_for_tests()
    marker = tmp_path / ".sase" / "agent_name_auto_migration.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        '{"schema_version": 1, "completed": true, "migrated_count": 0}\n',
        encoding="utf-8",
    )
    catalog = {
        "research_swarm": XPrompt(
            name="research_swarm",
            content=(
                "%clan(research.{@1}, description=Research) "
                "%id:research.{@1}.cdx\n"
                "CDX\n"
                "---\n"
                "%id(cld, clan=research.{@1})\n"
                "CLD\n"
                "---\n"
                "%id(final, clan=research.{@1}) "
                "%wait:research.{@1}.cdx\n"
                "Read `research.{@1}.cdx`; #fork:research.{@1}.cld\n"
                "---\n"
                "%id(image, clan=research.{@1}) "
                "%wait:research.{@1}.final\n"
                "Image"
            ),
        )
    }

    with (
        patch.object(Path, "home", return_value=tmp_path),
        patch("sase.agent.xprompt_swarm.get_all_xprompts", return_value=catalog),
        patch(
            "sase.agent.launch_projects.extract_known_project_vcs_launch_ref",
            return_value=None,
        ),
        patch(
            "sase.agent.multi_prompt_launcher.launch_multi_prompt_agents",
            return_value=[],
        ) as launch_multi,
        patch("sase.core.time.generate_timestamp", return_value="260729_093000"),
    ):
        launch_agents_from_cwd("#!research_swarm")
        first_segments = list(launch_multi.call_args.kwargs["segments"])

        make_agent(tmp_path, "proj", "first", "research.0.cdx", done=True)
        reset_name_registry_caches_for_tests()

        launch_agents_from_cwd("#!research_swarm")
        second_segments = list(launch_multi.call_args.kwargs["segments"])

    assert len(first_segments) == len(second_segments) == 4
    assert all("research.0" in segment for segment in first_segments)
    assert all("research.1" in segment for segment in second_segments)
    assert all("{@" not in segment for segment in [*first_segments, *second_segments])
    assert "research.0.cdx" in first_segments[2]
    assert "#fork:research.0.cld" in first_segments[2]
    assert "%wait:research.0.final" in first_segments[3]


@patch("sase.agent.launcher.spawn_agent_subprocess")
@patch("sase.agent.multi_prompt_launcher._wait_for_agent_naming")
@patch("sase.core.time.generate_timestamp", return_value="260501_120000")
@patch("sase.artifacts.create_artifacts_directory", return_value="/a")
@patch(
    "sase.running_field.claim_next_axe_workspace",
    side_effect=[100, 101, 102, 103],
)
@patch(
    "sase.running_field.get_workspace_directory_for_num",
    side_effect=[
        ("/ws1", None),
        ("/ws2", None),
        ("/ws3", None),
        ("/ws4", None),
    ],
)
def test_launch_multi_prompt_distinguishes_two_xprompt_template_groups(
    mock_ws_dir: MagicMock,
    mock_first_ws: MagicMock,
    mock_create_artifacts: MagicMock,
    mock_timestamp: MagicMock,
    mock_wait: MagicMock,
    mock_spawn: MagicMock,
    tmp_path: Path,
) -> None:
    """Two xprompt invocations in one submitted prompt get distinct namespaces."""
    del mock_ws_dir, mock_first_ws, mock_timestamp
    mock_spawn.side_effect = spawn_result_with_planned_name

    with patch.object(Path, "home", return_value=tmp_path):
        results = launch_multi_prompt_agents(
            segments=[
                "%id:research.@.cdx\nA",
                "%id:research.@.cld\nB",
                "%id:research.@.cdx\nC",
                "%id:research.@.cld\nD",
            ],
            segment_template_groups=[
                "xprompt:swarm:0",
                "xprompt:swarm:0",
                "xprompt:swarm:1",
                "xprompt:swarm:1",
            ],
            local_xprompts={},
            cl_name="test",
            project_file="/test.sase",
            project_name="test",
            is_home_mode=False,
            vcs_ref=None,
        )

    assert [result.agent_name for result in results] == [
        "research.0.cdx",
        "research.0.cld",
        "research.1.cdx",
        "research.1.cld",
    ]
    assert mock_wait.call_count == 0
    assert mock_create_artifacts.call_count == 0


@patch("sase.agent.launcher.spawn_agent_subprocess")
@patch("sase.agent.multi_prompt_launcher._wait_for_agent_naming")
@patch("sase.core.time.generate_timestamp", return_value="260501_120000")
@patch("sase.artifacts.create_artifacts_directory", return_value="/a")
@patch(
    "sase.running_field.claim_next_axe_workspace",
    side_effect=[100, 101, 102, 103],
)
@patch(
    "sase.running_field.get_workspace_directory_for_num",
    side_effect=[
        ("/ws1", None),
        ("/ws2", None),
        ("/ws3", None),
        ("/ws4", None),
    ],
)
def test_launch_multi_prompt_text_alt_model_alt_uses_distinct_generated_templates(
    mock_ws_dir: MagicMock,
    mock_first_ws: MagicMock,
    mock_create_artifacts: MagicMock,
    mock_timestamp: MagicMock,
    mock_wait: MagicMock,
    mock_spawn: MagicMock,
    tmp_path: Path,
) -> None:
    """Text and model fan-out axes do not render duplicate template names."""
    del mock_ws_dir, mock_first_ws, mock_timestamp
    mock_spawn.side_effect = spawn_result_with_planned_name
    local_xprompts = {"codex": XPrompt(name="codex", content="gpt-5.6-sol")}

    with patch.object(Path, "home", return_value=tmp_path):
        results = launch_multi_prompt_agents(
            segments=["%{Describe | Explain} repo. %{%m:opus | %m:#codex}"],
            local_xprompts=local_xprompts,
            cl_name="test",
            project_file="/test.sase",
            project_name="test",
            is_home_mode=False,
            vcs_ref=None,
        )

    assert [result.agent_name for result in results] == [
        "0.1.cld",
        "0.1.cdx",
        "0.2.cld",
        "0.2.cdx",
    ]
    assert [call.kwargs["prompt"] for call in mock_spawn.call_args_list] == [
        "%id:@.1.cld\nDescribe repo. %m:opus",
        "%id:@.1.cdx\nDescribe repo. %m:#codex",
        "%id:@.2.cld\nExplain repo. %m:opus",
        "%id:@.2.cdx\nExplain repo. %m:#codex",
    ]
    assert mock_wait.call_count == 0
    assert mock_create_artifacts.call_count == 0
