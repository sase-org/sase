"""Tests for planned-name allocator and reservation edge cases."""

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


def test_multi_parent_fork_plans_neutral_auto_name(tmp_path: Path) -> None:
    allocator = PlannedNameAllocator()

    with patch.object(Path, "home", return_value=tmp_path):
        name, env_value = allocator.planned_name_for_prompt(
            "#fork:planner,coder\nMerge"
        )

    assert name == "0"
    assert env_value == "0"


def test_tribe_wait_plans_neutral_auto_name(tmp_path: Path) -> None:
    allocator = PlannedNameAllocator()

    with patch.object(Path, "home", return_value=tmp_path):
        name, env_value = allocator.planned_name_for_prompt("%wait:@epic\nContinue")

    assert name == "0"
    assert env_value == "0"


def test_tribe_fork_plans_neutral_auto_name(tmp_path: Path) -> None:
    allocator = PlannedNameAllocator()

    with patch.object(Path, "home", return_value=tmp_path):
        name, env_value = allocator.planned_name_for_prompt("#fork:@epic\nContinue")

    assert name == "0"
    assert env_value == "0"


def test_tribe_wait_is_not_rewritten_as_template(tmp_path: Path) -> None:
    allocator = PlannedNameAllocator()

    with patch.object(Path, "home", return_value=tmp_path):
        assert allocator.planned_name_for_prompt("%name:build-@\nBuild")[0] == (
            "build-0"
        )
        rewritten = allocator.rewrite_template_references(
            "%wait:@epic,build-@\nContinue"
        )

    assert rewritten == "%wait:@epic,build-0\nContinue"


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("#fork:build-@,review-@", "#fork:build-0,review-0"),
        ("#fork(build-@, review-@)", "#fork(build-0,review-0)"),
    ],
)
def test_multi_parent_fork_rewrites_every_planned_template_reference(
    tmp_path: Path, prompt: str, expected: str
) -> None:
    allocator = PlannedNameAllocator()

    with patch.object(Path, "home", return_value=tmp_path):
        assert allocator.planned_name_for_prompt("%name:build-@\nBuild")[0] == (
            "build-0"
        )
        assert allocator.planned_name_for_prompt("%name:review-@\nReview")[0] == (
            "review-0"
        )
        rewritten = allocator.rewrite_template_references(prompt)

    assert rewritten == expected


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
        "foo.w0",
        "foo.w1",
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


def test_template_group_allows_later_sibling_under_owned_namespace(
    tmp_path: Path,
) -> None:
    artifacts_root = tmp_path / ".sase" / "projects" / "proj" / "artifacts" / "ace-run"
    allocator = PlannedNameAllocator()

    with patch.object(Path, "home", return_value=tmp_path):
        first = allocator.planned_names_for_template_group(
            ["research.@.cdx", "research.@.cld"],
            artifacts_dirs=[
                artifacts_root / "260501120000",
                artifacts_root / "260501120001",
            ],
            template_group="xprompt:research:0",
        )
        second, _ = allocator.planned_name_for_prompt(
            "%name:research.@.final\nFinal",
            artifacts_dir=artifacts_root / "260501120002",
            template_group="xprompt:research:0",
        )

    assert first == ["research.0.cdx", "research.0.cld"]
    assert second == "research.0.final"


@patch("sase.agent.launcher.spawn_agent_subprocess")
@patch("sase.agent.multi_prompt_launcher._wait_for_agent_naming")
@patch("sase.running_field.get_workspace_directory")
def test_concurrent_multi_prompt_batches_reserve_distinct_template_names(
    mock_wait_ws_dir: MagicMock,
    mock_wait: MagicMock,
    mock_spawn: MagicMock,
) -> None:
    """Concurrent template-name batches get unique, internally consistent tokens."""
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
                "%name:research.@.cdx\nCDX",
                "%wait:research.@.cdx\n%name:research.@.final\nFinal",
                "#fork:research.@.final\nFollow up",
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
        "research.0.cdx",
        "research.1.cdx",
    }
    assert {names[1] for names in batch_names} == {
        "research.0.final",
        "research.1.final",
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
        if name.startswith("research.")
        and name.endswith(".final")
        and name.removeprefix("research.").removesuffix(".final").isdigit()
    ]
    fork_calls = [
        (name, prompt)
        for name, prompt in call_data
        if name.startswith("research.") and ".final.f" in name
    ]

    assert len(final_calls) == 2
    assert len(fork_calls) == 2
    for name, prompt in final_calls:
        token = name.removeprefix("research.").removesuffix(".final")
        assert prompt.startswith(f"%wait:research.{token}.cdx\n")
    for name, prompt in fork_calls:
        token = name.removeprefix("research.").split(".final.", 1)[0]
        assert prompt.startswith(f"#fork:research.{token}.final\n")
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
    stale_allocator._template_reserved = set()

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


def test_planned_template_names_reserve_namespaces_from_stale_snapshots(
    tmp_path: Path,
) -> None:
    """A stale allocator must not use token 0 after 0.* was freshly planned."""
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
    stale_allocator._template_reserved = set()

    with patch.object(Path, "home", return_value=tmp_path):
        fresh_allocator = PlannedNameAllocator()
        first_name, first_env = fresh_allocator.planned_name_for_prompt(
            "%name:@.cdx\nfirst prompt",
            artifacts_dir=first_artifacts,
        )
        second_name, second_env = stale_allocator.planned_name_for_prompt(
            "%name:@.cld\nsecond prompt",
            artifacts_dir=second_artifacts,
        )

        assert (first_name, first_env) == ("0.cdx", "0.cdx")
        assert (second_name, second_env) == ("1.cld", "1.cld")
        assert lookup_registered_name("0.cdx")["artifacts_dir"] == str(first_artifacts)
        assert lookup_registered_name("1.cld")["artifacts_dir"] == str(second_artifacts)
