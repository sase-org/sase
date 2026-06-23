"""``launch_agent_from_cwd`` tests for built-in ``#cd`` launch resolution."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.workspace_provider._hookspec import ResolvedRef
from tests._cd_launch_resolution_helpers import (
    patch_cd_git_metadata,
    patch_cd_metadata,
)


def test_launch_agent_from_cwd_cd_launches_in_target_without_workspace_claim(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_cd_metadata(monkeypatch)
    from sase.agent.launcher import launch_agent_from_cwd

    spawn_result = MagicMock(pid=123, workspace_dir=str(tmp_path), workspace_num=0)
    with (
        patch(
            "sase.main.utils.ensure_project_file_and_get_workspace_num",
            return_value=(None, None, None),
        ),
        patch("sase.history.prompt.add_or_update_prompt"),
        patch(
            "sase.core.agent_launch_facade.reserve_launch_timestamp_batch",
            return_value=["260501_120000"],
        ),
        patch(
            "sase.agent.launcher.spawn_agent_subprocess",
            return_value=spawn_result,
        ) as spawn,
        patch("sase.running_field.get_first_available_axe_workspace") as first_ws,
        patch("sase.running_field.get_workspace_directory_for_num") as ws_dir,
    ):
        result = launch_agent_from_cwd(f"#cd:{tmp_path} do work")

    assert result is spawn_result
    kwargs = spawn.call_args.kwargs
    assert kwargs["workspace_dir"] == str(tmp_path.resolve())
    assert kwargs["workspace_num"] == 0
    assert kwargs["is_home_mode"] is True
    assert kwargs["update_target"] == ""
    assert kwargs["vcs_ref"] == ("cd", str(tmp_path))
    first_ws.assert_not_called()
    ws_dir.assert_not_called()


def test_launch_agent_from_cwd_no_ref_defaults_to_git_home(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_cd_git_metadata(monkeypatch)
    from sase.agent.launcher import launch_agent_from_cwd
    from sase.vcs_provider import VCS_DEFAULT_REVISION

    primary_workspace = tmp_path / "home"
    allocated_workspace = tmp_path / "home_101"
    project_file = str(tmp_path / "home.sase")
    spawn_result = MagicMock(
        pid=123, workspace_dir=str(allocated_workspace), workspace_num=101
    )
    with (
        patch(
            "sase.main.utils.ensure_project_file_and_get_workspace_num",
            return_value=("/projects/repo/repo.sase", 3, "repo"),
        ),
        patch("sase.history.prompt.add_or_update_prompt"),
        patch(
            "sase.core.agent_launch_facade.reserve_launch_timestamp_batch",
            return_value=["260501_120000"],
        ),
        patch(
            "sase.agent.launcher.spawn_agent_subprocess",
            return_value=spawn_result,
        ) as spawn,
        patch(
            "sase.workspace_provider.resolve_ref",
            return_value=ResolvedRef(
                project_file=project_file,
                project_name="home",
                primary_workspace_dir=str(primary_workspace),
                checkout_target="main",
            ),
        ) as resolve_ref,
        patch("sase.running_field.get_first_available_axe_workspace") as first_ws,
        patch("sase.workspace_provider.get_workspace_directory") as provider_ws_dir,
        patch(
            "sase.running_field.claim_next_axe_workspace",
            return_value=101,
        ) as claim_ws,
        patch(
            "sase.running_field.get_workspace_directory_for_num",
            return_value=(str(allocated_workspace), None),
        ) as ws_dir,
    ):
        result = launch_agent_from_cwd("do work")

    assert result is spawn_result
    kwargs = spawn.call_args.kwargs
    assert kwargs["prompt"] == "#git:home do work"
    assert kwargs["project_name"] == "home"
    assert kwargs["workspace_dir"] == str(allocated_workspace)
    assert kwargs["workspace_num"] == 101
    assert kwargs["is_home_mode"] is False
    assert kwargs["update_target"] == VCS_DEFAULT_REVISION
    assert kwargs["vcs_ref"] == ("git", "home")
    assert kwargs["retry_transfer_from_pid"] == os.getpid()
    resolve_ref.assert_called_once_with("home", "git")
    first_ws.assert_not_called()
    provider_ws_dir.assert_not_called()
    claim_ws.assert_called_once()
    assert claim_ws.call_args.args[0] == project_file
    ws_dir.assert_called_once_with(101, "home")


def test_launch_agent_from_cwd_wait_cd_stays_directory_mode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_cd_metadata(monkeypatch)
    from sase.agent.launcher import launch_agent_from_cwd

    spawn_result = MagicMock(pid=123, workspace_dir=str(tmp_path), workspace_num=0)
    with (
        patch(
            "sase.main.utils.ensure_project_file_and_get_workspace_num",
            return_value=(None, None, None),
        ),
        patch("sase.history.prompt.add_or_update_prompt"),
        patch(
            "sase.core.agent_launch_facade.reserve_launch_timestamp_batch",
            return_value=["260501_120000"],
        ),
        patch(
            "sase.agent.launcher.spawn_agent_subprocess",
            return_value=spawn_result,
        ) as spawn,
        patch("sase.running_field.get_first_available_axe_workspace") as first_ws,
        patch("sase.running_field.get_workspace_directory_for_num") as ws_dir,
    ):
        result = launch_agent_from_cwd(f"%wait:1s #cd:{tmp_path} do work")

    assert result is spawn_result
    kwargs = spawn.call_args.kwargs
    assert kwargs["workspace_dir"] == str(tmp_path.resolve())
    assert kwargs["workspace_num"] == 0
    assert kwargs["is_home_mode"] is True
    assert kwargs["deferred_workspace"] is True
    assert kwargs["vcs_ref"] == ("cd", str(tmp_path))
    first_ws.assert_not_called()
    ws_dir.assert_not_called()


def test_launch_agent_from_cwd_bad_cd_path_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_cd_metadata(monkeypatch)
    from sase.agent.launcher import launch_agent_from_cwd

    with (
        patch(
            "sase.main.utils.ensure_project_file_and_get_workspace_num",
            return_value=(None, None, None),
        ),
        patch("sase.agent.launcher.spawn_agent_subprocess") as spawn,
    ):
        with pytest.raises(ValueError, match="does not exist"):
            launch_agent_from_cwd(f"#cd:{tmp_path / 'missing'} do work")

    spawn.assert_not_called()


def test_launch_agent_from_cwd_spawn_failure_records_short_failed_history(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_cd_metadata(monkeypatch)
    from sase.agent.launcher import launch_agent_from_cwd
    from sase.history import prompt_store

    history_path = tmp_path / ".sase" / "prompt_history.json"
    prompt = f"#cd:{tmp_path}"
    monkeypatch.setattr(prompt_store, "_PROMPT_HISTORY_FILE", history_path)

    with (
        patch(
            "sase.main.utils.ensure_project_file_and_get_workspace_num",
            return_value=(None, None, None),
        ),
        patch(
            "sase.core.agent_launch_facade.reserve_launch_timestamp_batch",
            return_value=["260501_120000"],
        ),
        patch(
            "sase.agent.launcher.spawn_agent_subprocess",
            side_effect=RuntimeError("spawn boom"),
        ),
    ):
        with pytest.raises(RuntimeError, match="spawn boom"):
            launch_agent_from_cwd(prompt)

    entries = prompt_store.load_prompt_history()
    assert len(entries) == 1
    assert entries[0].text == prompt
    assert entries[0].timestamp == entries[0].last_used
    assert entries[0].cancelled is True


def test_launch_agent_from_cwd_alt_failure_records_failed_history(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_cd_metadata(monkeypatch)
    from sase.agent.launcher import launch_agents_from_cwd
    from sase.history import prompt_store

    history_path = tmp_path / ".sase" / "prompt_history.json"
    prompt = f"%alt(sec=security pass,perf=performance pass)\n#cd:{tmp_path} do work"
    monkeypatch.setattr(prompt_store, "_PROMPT_HISTORY_FILE", history_path)

    with (
        patch(
            "sase.main.utils.ensure_project_file_and_get_workspace_num",
            return_value=(None, None, None),
        ),
        patch(
            "sase.agent.multi_prompt_launcher.launch_multi_prompt_agents",
            side_effect=RuntimeError("fanout boom"),
        ),
    ):
        with pytest.raises(RuntimeError, match="fanout boom"):
            launch_agents_from_cwd(prompt)

    entries = prompt_store.load_prompt_history()
    assert entries[0].text == prompt
    assert entries[0].cancelled is True


def test_launch_agent_from_cwd_repeat_failure_records_failed_history(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_cd_metadata(monkeypatch)
    from sase.agent.launcher import launch_agents_from_cwd
    from sase.history import prompt_store

    history_path = tmp_path / ".sase" / "prompt_history.json"
    prompt = f"%r:2\n#cd:{tmp_path} do work"
    monkeypatch.setattr(prompt_store, "_PROMPT_HISTORY_FILE", history_path)

    with (
        patch(
            "sase.main.utils.ensure_project_file_and_get_workspace_num",
            return_value=(None, None, None),
        ),
        patch(
            "sase.core.agent_launch_facade.reserve_launch_timestamp_batch",
            return_value=["260501_120000", "260501_120001"],
        ),
        patch(
            "sase.agent.repeat_launcher.spawn_repeat_batch",
            side_effect=RuntimeError("repeat boom"),
        ),
    ):
        with pytest.raises(RuntimeError, match="repeat boom"):
            launch_agents_from_cwd(prompt)

    entries = prompt_store.load_prompt_history()
    assert entries[0].text == prompt
    assert entries[0].cancelled is True


def test_launch_agents_from_cwd_repeat_injects_prev_name_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The daemon/cwd repeat path forwards SASE_REPEAT_PREV_NAME to later slots."""
    patch_cd_metadata(monkeypatch)
    import sase.agent.launch_cwd as launch_cwd_mod

    real_launch = launch_cwd_mod.launch_agents_from_cwd
    captured: list[dict[str, str]] = []

    def fake(query, extra_env=None, segment_extra_env=None, timestamp=None):
        # Per-slot recursive calls carry the repeat env; the top-level call does
        # not. Capture the slot envs and short-circuit before any real spawn.
        if extra_env and "SASE_REPEAT_NAME" in extra_env:
            captured.append(dict(extra_env))
            return []
        return real_launch(
            query,
            extra_env=extra_env,
            segment_extra_env=segment_extra_env,
            timestamp=timestamp,
        )

    prompt = f"%r:2\n#cd:{tmp_path} do work"
    with (
        patch.object(Path, "home", return_value=tmp_path),
        patch(
            "sase.main.utils.ensure_project_file_and_get_workspace_num",
            return_value=(None, None, None),
        ),
        patch(
            "sase.core.agent_launch_facade.reserve_launch_timestamp_batch",
            return_value=["260501_120000", "260501_120001"],
        ),
        patch.object(launch_cwd_mod, "launch_agents_from_cwd", side_effect=fake),
    ):
        launch_cwd_mod.launch_agents_from_cwd(prompt)

    assert len(captured) == 2
    assert "SASE_REPEAT_PREV_NAME" not in captured[0]
    assert captured[1]["SASE_REPEAT_PREV_NAME"] == captured[0]["SASE_REPEAT_NAME"]
