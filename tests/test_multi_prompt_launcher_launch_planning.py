"""Tests for multi-prompt launch name and reference planning."""

from concurrent.futures import ThreadPoolExecutor
from itertools import count
from pathlib import Path
from threading import Barrier, Lock
from unittest.mock import MagicMock, patch

import pytest

from tests._agent_names_fixtures import make_agent
from tests._multi_prompt_launcher_launch_helpers import spawn_result_with_planned_name
from sase.agent.names import lookup_registered_name
from sase.agent.multi_prompt_launcher import launch_multi_prompt_agents
from sase.agent.multi_prompt_references import PlannedNameAllocator
from sase.xprompt.models import XPrompt


@patch("sase.agent.launcher.spawn_agent_subprocess")
@patch("sase.agent.multi_prompt_launcher._wait_for_agent_naming")
@patch("sase.core.time.generate_timestamp", return_value="260501_120000")
@patch("sase.artifacts.create_artifacts_directory", return_value="/a")
@patch("sase.running_field.get_workspace_directory", return_value="/ws/main")
@patch(
    "sase.running_field.claim_next_axe_workspace",
    side_effect=[100, 101],
)
@patch(
    "sase.running_field.get_workspace_directory_for_num",
    side_effect=[("/ws1", None), ("/ws2", None)],
)
def test_launch_multi_prompt_resolves_indexed_wait_to_planned_predecessor(
    mock_ws_dir: MagicMock,
    mock_first_ws: MagicMock,
    mock_wait_ws_dir: MagicMock,
    mock_create_artifacts: MagicMock,
    mock_timestamp: MagicMock,
    mock_wait: MagicMock,
    mock_spawn: MagicMock,
    tmp_path: Path,
) -> None:
    """Later segments can wait on an indexed name planned earlier in the batch."""
    mock_spawn.side_effect = spawn_result_with_planned_name

    with patch.object(Path, "home", return_value=tmp_path):
        results = launch_multi_prompt_agents(
            segments=["%n:build-@\nBuild", "%w:build-@\nReview"],
            local_xprompts={},
            cl_name="test",
            project_file="/test.sase",
            project_name="test",
            is_home_mode=False,
            vcs_ref=None,
        )

    calls = mock_spawn.call_args_list
    assert [result.agent_name for result in results] == ["build-0", "build-0.w1"]
    assert calls[0].kwargs["prompt"] == "%n:build-@\nBuild"
    assert calls[1].kwargs["prompt"] == "%w:build-0\nReview"
    assert calls[0].kwargs["extra_env"]["SASE_AGENT_PLANNED_NAME"] == "build-0"
    assert calls[1].kwargs["extra_env"]["SASE_AGENT_PLANNED_NAME"] == "build-0.w1"
    assert mock_wait.call_count == 0
    assert mock_create_artifacts.call_count == 0


@patch("sase.agent.launcher.spawn_agent_subprocess")
@patch("sase.agent.multi_prompt_launcher._wait_for_agent_naming")
@patch("sase.core.time.generate_timestamp", return_value="260501_120000")
@patch("sase.artifacts.create_artifacts_directory", return_value="/a")
@patch(
    "sase.running_field.claim_next_axe_workspace",
    side_effect=[100, 101],
)
@patch(
    "sase.running_field.get_workspace_directory_for_num",
    side_effect=[("/ws1", None), ("/ws2", None)],
)
def test_launch_multi_prompt_allocates_distinct_indexed_names_per_segment(
    mock_ws_dir: MagicMock,
    mock_first_ws: MagicMock,
    mock_create_artifacts: MagicMock,
    mock_timestamp: MagicMock,
    mock_wait: MagicMock,
    mock_spawn: MagicMock,
    tmp_path: Path,
) -> None:
    """Two indexed name templates in one launch reserve consecutive names."""
    mock_spawn.side_effect = spawn_result_with_planned_name

    with patch.object(Path, "home", return_value=tmp_path):
        results = launch_multi_prompt_agents(
            segments=["%n:build-@\nFirst", "%n:build-@\nSecond"],
            local_xprompts={},
            cl_name="test",
            project_file="/test.sase",
            project_name="test",
            is_home_mode=False,
            vcs_ref=None,
        )

    assert [result.agent_name for result in results] == ["build-0", "build-1"]
    assert [
        call.kwargs["extra_env"]["SASE_AGENT_PLANNED_NAME"]
        for call in mock_spawn.call_args_list
    ] == ["build-0", "build-1"]
    assert mock_wait.call_count == 0
    assert mock_create_artifacts.call_count == 0


@patch("sase.agent.launcher.spawn_agent_subprocess")
@patch("sase.agent.multi_prompt_launcher._wait_for_agent_naming")
@patch("sase.core.time.generate_timestamp", return_value="260501_120000")
@patch("sase.artifacts.create_artifacts_directory", return_value="/a")
@patch(
    "sase.running_field.claim_next_axe_workspace",
    side_effect=[100, 101],
)
@patch(
    "sase.running_field.get_workspace_directory_for_num",
    side_effect=[("/ws1", None), ("/ws2", None)],
)
def test_launch_multi_prompt_allocates_distinct_suffix_shape_template_names(
    mock_ws_dir: MagicMock,
    mock_first_ws: MagicMock,
    mock_create_artifacts: MagicMock,
    mock_timestamp: MagicMock,
    mock_wait: MagicMock,
    mock_spawn: MagicMock,
    tmp_path: Path,
) -> None:
    """Generic suffix-shape templates allocate by rendering template tokens."""
    mock_spawn.side_effect = spawn_result_with_planned_name

    with patch.object(Path, "home", return_value=tmp_path):
        results = launch_multi_prompt_agents(
            segments=["%n:@.cld\nFirst", "%n:@.cld\nSecond"],
            local_xprompts={},
            cl_name="test",
            project_file="/test.sase",
            project_name="test",
            is_home_mode=False,
            vcs_ref=None,
        )

    assert [result.agent_name for result in results] == ["0.cld", "1.cld"]
    assert [
        call.kwargs["extra_env"]["SASE_AGENT_PLANNED_NAME"]
        for call in mock_spawn.call_args_list
    ] == ["0.cld", "1.cld"]
    assert mock_wait.call_count == 0
    assert mock_create_artifacts.call_count == 0


@patch("sase.agent.launcher.spawn_agent_subprocess")
@patch("sase.agent.multi_prompt_launcher._wait_for_agent_naming")
@patch("sase.core.time.generate_timestamp", return_value="260501_120000")
@patch("sase.artifacts.create_artifacts_directory", return_value="/a")
@patch("sase.running_field.get_workspace_directory", return_value="/ws/main")
@patch(
    "sase.running_field.claim_next_axe_workspace",
    side_effect=[100, 101],
)
@patch(
    "sase.running_field.get_workspace_directory_for_num",
    side_effect=[("/ws1", None), ("/ws2", None)],
)
def test_launch_multi_prompt_resolves_indexed_resume_to_planned_predecessor(
    mock_ws_dir: MagicMock,
    mock_first_ws: MagicMock,
    mock_wait_ws_dir: MagicMock,
    mock_create_artifacts: MagicMock,
    mock_timestamp: MagicMock,
    mock_wait: MagicMock,
    mock_spawn: MagicMock,
    tmp_path: Path,
) -> None:
    """#fork/#resume indexed refs resolve to the latest planned concrete name."""
    mock_spawn.side_effect = spawn_result_with_planned_name

    with patch.object(Path, "home", return_value=tmp_path):
        launch_multi_prompt_agents(
            segments=[
                "%n:build-@\nBuild",
                "#fork:build-@\n#resume:build-@\nReview",
            ],
            local_xprompts={},
            cl_name="test",
            project_file="/test.sase",
            project_name="test",
            is_home_mode=False,
            vcs_ref=None,
        )

    assert mock_spawn.call_args_list[1].kwargs["prompt"] == (
        "#fork:build-0\n#resume:build-0\nReview"
    )
    assert (
        mock_spawn.call_args_list[1].kwargs["extra_env"]["SASE_AGENT_PLANNED_NAME"]
        == "build-0.f1"
    )
    assert mock_wait.call_count == 0
    assert mock_create_artifacts.call_count == 0


@patch("sase.agent.launcher.spawn_agent_subprocess")
@patch("sase.agent.multi_prompt_launcher._wait_for_agent_naming")
@patch("sase.core.time.generate_timestamp", return_value="260501_120000")
@patch("sase.artifacts.create_artifacts_directory", return_value="/a")
@patch("sase.running_field.get_workspace_directory", return_value="/ws/main")
@patch(
    "sase.running_field.claim_next_axe_workspace",
    side_effect=[100, 101],
)
@patch(
    "sase.running_field.get_workspace_directory_for_num",
    side_effect=[("/ws1", None), ("/ws2", None)],
)
def test_launch_multi_prompt_resolves_middle_template_wait_to_planned_name(
    mock_ws_dir: MagicMock,
    mock_first_ws: MagicMock,
    mock_wait_ws_dir: MagicMock,
    mock_create_artifacts: MagicMock,
    mock_timestamp: MagicMock,
    mock_wait: MagicMock,
    mock_spawn: MagicMock,
    tmp_path: Path,
) -> None:
    """Middle-marker wait refs resolve to earlier planned concrete names."""
    mock_spawn.side_effect = spawn_result_with_planned_name

    with patch.object(Path, "home", return_value=tmp_path):
        results = launch_multi_prompt_agents(
            segments=[
                "%n:research.@.final\nFinal",
                "%w:research.@.final\nReview",
            ],
            local_xprompts={},
            cl_name="test",
            project_file="/test.sase",
            project_name="test",
            is_home_mode=False,
            vcs_ref=None,
        )

    assert [result.agent_name for result in results] == [
        "research.0.final",
        "research.0.final.w1",
    ]
    assert mock_spawn.call_args_list[1].kwargs["prompt"] == (
        "%w:research.0.final\nReview"
    )
    assert mock_wait.call_count == 0
    assert mock_create_artifacts.call_count == 0


@patch("sase.agent.launcher.spawn_agent_subprocess")
@patch("sase.agent.multi_prompt_launcher._wait_for_agent_naming")
@patch("sase.core.time.generate_timestamp", return_value="260501_120000")
@patch("sase.artifacts.create_artifacts_directory", return_value="/a")
@patch("sase.running_field.get_workspace_directory", return_value="/ws/main")
@patch(
    "sase.running_field.claim_next_axe_workspace",
    side_effect=[100, 101],
)
@patch(
    "sase.running_field.get_workspace_directory_for_num",
    side_effect=[("/ws1", None), ("/ws2", None)],
)
def test_launch_multi_prompt_template_refs_prefer_planned_over_existing_latest(
    mock_ws_dir: MagicMock,
    mock_first_ws: MagicMock,
    mock_wait_ws_dir: MagicMock,
    mock_create_artifacts: MagicMock,
    mock_timestamp: MagicMock,
    mock_wait: MagicMock,
    mock_spawn: MagicMock,
    tmp_path: Path,
) -> None:
    """Current-batch planned names win over a higher existing template token."""
    make_agent(tmp_path, "proj", "run1", "build-z")
    mock_spawn.side_effect = spawn_result_with_planned_name

    with patch.object(Path, "home", return_value=tmp_path):
        launch_multi_prompt_agents(
            segments=["%n:build-@\nBuild", "%w:build-@\nReview"],
            local_xprompts={},
            cl_name="test",
            project_file="/test.sase",
            project_name="test",
            is_home_mode=False,
            vcs_ref=None,
        )

    assert mock_spawn.call_args_list[1].kwargs["prompt"] == "%w:build-0\nReview"
    assert mock_wait.call_count == 0
    assert mock_create_artifacts.call_count == 0


@patch("sase.agent.launcher.spawn_agent_subprocess")
@patch("sase.agent.multi_prompt_launcher._wait_for_agent_naming")
@patch("sase.core.time.generate_timestamp", return_value="260501_120000")
@patch("sase.artifacts.create_artifacts_directory", return_value="/a")
@patch("sase.running_field.get_workspace_directory", return_value="/ws/main")
@patch("sase.agent.launch_projects.extract_known_project_vcs_launch_ref")
def test_launch_multi_prompt_same_segment_indexed_wait_uses_existing_latest(
    mock_known_project_ref: MagicMock,
    mock_wait_ws_dir: MagicMock,
    mock_create_artifacts: MagicMock,
    mock_timestamp: MagicMock,
    mock_wait: MagicMock,
    mock_spawn: MagicMock,
    tmp_path: Path,
) -> None:
    """Indexed waits resolve before a same-segment indexed name is allocated."""
    mock_known_project_ref.return_value = None
    make_agent(tmp_path, "proj", "run1", "build-1")
    mock_spawn.side_effect = spawn_result_with_planned_name

    with patch.object(Path, "home", return_value=tmp_path):
        results = launch_multi_prompt_agents(
            segments=["%w:build-@\n%n:build-@\nDo work"],
            local_xprompts={},
            cl_name="test",
            project_file="/test.sase",
            project_name="test",
            is_home_mode=False,
            vcs_ref=None,
        )

    assert [result.agent_name for result in results] == ["build-0"]
    assert mock_spawn.call_args.kwargs["prompt"] == "%w:build-1\n%n:build-@\nDo work"
    assert (
        mock_spawn.call_args.kwargs["extra_env"]["SASE_AGENT_PLANNED_NAME"] == "build-0"
    )
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
def test_launch_agents_from_cwd_resolves_indexed_refs_after_multi_xprompt_expansion(
    mock_project: MagicMock,
    mock_history: MagicMock,
    mock_create_artifacts: MagicMock,
    mock_timestamp: MagicMock,
    mock_wait: MagicMock,
    mock_spawn: MagicMock,
    tmp_path: Path,
) -> None:
    """The cwd launch path resolves indexed refs after multi-agent xprompt expansion."""
    from sase.agent.launcher import launch_agents_from_cwd

    mock_spawn.side_effect = spawn_result_with_planned_name
    catalog = {
        "ix": XPrompt(
            name="ix",
            content="%n:flow-@\nBuild\n---\n%w:flow-@\nReview",
        )
    }

    with (
        patch.object(Path, "home", return_value=tmp_path),
        patch("sase.agent.multi_agent_xprompt.get_all_xprompts", return_value=catalog),
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
        "%n:flow-@\n#git:home Build",
        "%w:flow-0\n#git:home Review",
    ]
    assert mock_wait.call_count == 0
    assert mock_create_artifacts.call_count == 0


@patch("sase.agent.launcher.spawn_agent_subprocess")
@patch("sase.agent.multi_prompt_launcher._wait_for_agent_naming")
@patch("sase.core.time.generate_timestamp")
@patch("sase.artifacts.create_artifacts_directory")
@patch("sase.running_field.get_workspace_directory")
def test_launch_multi_prompt_plans_wait_derived_sibling_names(
    mock_wait_ws_dir: MagicMock,
    mock_create_artifacts: MagicMock,
    mock_timestamp: MagicMock,
    mock_wait: MagicMock,
    mock_spawn: MagicMock,
    tmp_path: Path,
) -> None:
    """Sibling explicit waits on the same agent reserve distinct .w slots."""
    mock_wait_ws_dir.return_value = "/ws/1"
    mock_timestamp.return_value = "260501_120000"
    mock_wait.return_value = "alpha"
    mock_create_artifacts.return_value = "/artifacts/dir"
    mock_spawn.return_value = MagicMock(pid=1)

    with patch.object(Path, "home", return_value=tmp_path):
        launch_multi_prompt_agents(
            segments=["%wait:foo first", "%wait:foo second"],
            local_xprompts={},
            cl_name="test",
            project_file="/test.sase",
            project_name="test",
            is_home_mode=False,
            vcs_ref=None,
        )

    calls = mock_spawn.call_args_list
    assert [c.kwargs["extra_env"]["SASE_AGENT_PLANNED_NAME"] for c in calls] == [
        "foo.w1",
        "foo.w2",
    ]
    assert [c.kwargs["prompt"] for c in calls] == [
        "%wait:foo first",
        "%wait:foo second",
    ]
    assert mock_wait.call_count == 0


def test_template_group_allocates_shared_token_for_generic_shapes(
    tmp_path: Path,
) -> None:
    """Callers can group distinct templates that should share one token."""
    make_agent(tmp_path, "proj", "existing", "0.cdx")
    artifacts_root = tmp_path / ".sase" / "projects" / "proj" / "artifacts" / "ace-run"
    allocator = PlannedNameAllocator()

    with patch.object(Path, "home", return_value=tmp_path):
        names = allocator.planned_names_for_template_group(
            ["@.cld", "@.cdx"],
            artifacts_dirs=[
                artifacts_root / "260501120000",
                artifacts_root / "260501120001",
            ],
            template_group="fanout",
        )

    assert names == ["1.cld", "1.cdx"]


@patch("sase.agent.launcher.spawn_agent_subprocess")
@patch("sase.agent.multi_prompt_launcher._wait_for_agent_naming")
@patch("sase.running_field.get_workspace_directory")
def test_concurrent_multi_prompt_batches_reserve_distinct_indexed_names(
    mock_wait_ws_dir: MagicMock,
    mock_wait: MagicMock,
    mock_spawn: MagicMock,
) -> None:
    """Concurrent indexed-name batches get unique, internally consistent suffixes."""
    mock_wait_ws_dir.return_value = "/ws/main"
    mock_spawn.side_effect = spawn_result_with_planned_name
    barrier = Barrier(2)
    lock = Lock()
    timestamp_counter = count()
    workspace_counter = count(100)

    def reserve_timestamps(
        count_value: int,
        *,
        base_timestamp: str | None = None,
        after_timestamp: str | None = None,
    ) -> list[str]:
        del base_timestamp, after_timestamp
        with lock:
            return [
                f"260501_120{next(timestamp_counter):03d}" for _ in range(count_value)
            ]

    def claim_workspace(*args: object, **kwargs: object) -> int:
        del args, kwargs
        with lock:
            return next(workspace_counter)

    def workspace_dir(workspace_num: int, project_name: str) -> tuple[str, None]:
        return f"/ws/{project_name}/{workspace_num}", None

    def launch_batch() -> list[str | None]:
        barrier.wait()
        results = launch_multi_prompt_agents(
            segments=[
                "%name:research.cdx-@\nCDX",
                "%wait:research.cdx-@\n%name:research.final-@\nFinal",
                "#fork:research.final-@\nFollow up",
            ],
            local_xprompts={},
            cl_name="test",
            project_file="/test.sase",
            project_name="test",
            is_home_mode=False,
            vcs_ref=None,
        )
        return [result.agent_name for result in results]

    with (
        patch(
            "sase.core.agent_launch_facade.reserve_launch_timestamp_batch",
            side_effect=reserve_timestamps,
        ),
        patch(
            "sase.running_field.claim_next_axe_workspace",
            side_effect=claim_workspace,
        ),
        patch(
            "sase.running_field.get_workspace_directory_for_num",
            side_effect=workspace_dir,
        ),
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        batch_names = list(pool.map(lambda _i: launch_batch(), range(2)))

    assert {names[0] for names in batch_names} == {
        "research.cdx-0",
        "research.cdx-1",
    }
    assert {names[1] for names in batch_names} == {
        "research.final-0",
        "research.final-1",
    }

    call_data = [
        (
            call.kwargs["extra_env"]["SASE_AGENT_PLANNED_NAME"],
            call.kwargs["prompt"],
        )
        for call in mock_spawn.call_args_list
    ]
    final_calls = [
        (name, prompt)
        for name, prompt in call_data
        if name.startswith("research.final-")
        and name.removeprefix("research.final-").isdigit()
    ]
    fork_calls = [
        (name, prompt)
        for name, prompt in call_data
        if name.startswith("research.final-")
        and ".f" in name.removeprefix("research.final-")
    ]

    assert len(final_calls) == 2
    assert len(fork_calls) == 2
    for name, prompt in final_calls:
        suffix = name.rsplit("-", 1)[1]
        assert prompt.startswith(f"%wait:research.cdx-{suffix}\n")
    for name, prompt in fork_calls:
        suffix = name.split("research.final-", 1)[1].split(".", 1)[0]
        assert prompt.startswith(f"#fork:research.final-{suffix}\n")
    assert mock_wait.call_count == 0


@patch("sase.core.time.generate_timestamp", return_value="260501_120000")
def test_unstarted_template_reservations_are_released_on_later_spawn_failure(
    mock_timestamp: MagicMock,
    tmp_path: Path,
) -> None:
    """A later failed slot releases reservations for children that never started."""
    del mock_timestamp

    spawn_count = 0

    def spawn_or_fail(**kwargs: object):
        nonlocal spawn_count
        spawn_count += 1
        if spawn_count == 2:
            raise RuntimeError("boom")
        return spawn_result_with_planned_name(**kwargs)

    with (
        patch.object(Path, "home", return_value=tmp_path),
        patch("sase.agent.launcher.spawn_agent_subprocess", side_effect=spawn_or_fail),
        pytest.raises(RuntimeError, match="boom"),
    ):
        launch_multi_prompt_agents(
            segments=["%name:build-@\nFirst", "%name:build-@\nSecond"],
            local_xprompts={},
            cl_name="test",
            project_file="/test.sase",
            project_name="test",
            is_home_mode=True,
            vcs_ref=None,
        )

    with patch.object(Path, "home", return_value=tmp_path):
        first = lookup_registered_name("build-0")
        assert first is not None
        assert first["reservation_kind"] == "planned"
        assert lookup_registered_name("build-1") is None


def test_planned_auto_names_reserve_registry_slots_from_stale_snapshots(
    tmp_path: Path,
) -> None:
    """A stale parent-side auto-name snapshot must not duplicate a new plan."""
    first_artifacts = (
        tmp_path
        / ".sase"
        / "projects"
        / "proj"
        / "artifacts"
        / "ace-run"
        / "260501120000"
    )
    second_artifacts = first_artifacts.with_name("260501120001")
    stale_allocator = PlannedNameAllocator()
    stale_allocator._auto_reserved = set()

    with patch.object(Path, "home", return_value=tmp_path):
        fresh_allocator = PlannedNameAllocator()
        first_name, first_env = fresh_allocator.planned_name_for_prompt(
            "first prompt",
            artifacts_dir=first_artifacts,
        )
        second_name, second_env = stale_allocator.planned_name_for_prompt(
            "second prompt",
            artifacts_dir=second_artifacts,
        )

        assert (first_name, first_env) == ("0", "0")
        assert (second_name, second_env) == ("1", "1")
        assert lookup_registered_name("0")["artifacts_dir"] == str(first_artifacts)
        assert lookup_registered_name("1")["artifacts_dir"] == str(second_artifacts)
