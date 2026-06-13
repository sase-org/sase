"""Multi-agent ``launch_agents_from_cwd`` tests for built-in ``#cd`` refs."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tests._cd_launch_resolution_helpers import patch_cd_metadata


def test_launch_agent_from_cwd_alt_fanout_uses_named_child_prompts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_cd_metadata(monkeypatch)
    from sase.agent.launcher import launch_agent_from_cwd, launch_agents_from_cwd

    spawn_result = MagicMock(pid=123, workspace_dir=str(tmp_path), workspace_num=0)
    with (
        patch(
            "sase.main.utils.ensure_project_file_and_get_workspace_num",
            return_value=(None, None, None),
        ),
        patch("sase.history.prompt.add_or_update_prompt"),
        patch(
            "sase.core.agent_launch_facade.reserve_launch_timestamp_batch",
            return_value=["260501_120000", "260501_120001"],
        ),
        patch(
            "sase.agent.launcher.spawn_agent_subprocess",
            return_value=spawn_result,
        ) as spawn,
        patch("sase.running_field.get_first_available_axe_workspace") as first_ws,
        patch("sase.running_field.get_workspace_directory_for_num") as ws_dir,
    ):
        result = launch_agent_from_cwd(
            f"%n:ag\n%alt(sec=security pass,perf=performance pass)\n"
            f"#cd:{tmp_path} do work"
        )
        all_results = launch_agents_from_cwd(
            f"%n:ag\n%alt(sec=security pass,perf=performance pass)\n"
            f"#cd:{tmp_path} do work"
        )

    assert result is spawn_result
    assert all_results == [spawn_result, spawn_result]
    assert spawn.call_count == 4
    prompts = [c.kwargs["prompt"] for c in spawn.call_args_list]
    assert prompts == [
        f"%name:ag.sec\nsecurity pass\n#cd:{tmp_path} do work",
        f"%name:ag.perf\nperformance pass\n#cd:{tmp_path} do work",
        f"%name:ag.sec\nsecurity pass\n#cd:{tmp_path} do work",
        f"%name:ag.perf\nperformance pass\n#cd:{tmp_path} do work",
    ]
    first_ws.assert_not_called()
    ws_dir.assert_not_called()


def test_launch_agents_from_cwd_xprompt_expanded_multi_model_fans_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_cd_metadata(monkeypatch)
    from sase.agent.launcher import launch_agents_from_cwd

    launched = [MagicMock(name="opus"), MagicMock(name="sonnet")]
    expanded = "%n:ag\n%m(opus,sonnet)\nDo work"
    with (
        patch(
            "sase.main.utils.ensure_project_file_and_get_workspace_num",
            return_value=(None, None, None),
        ),
        patch("sase.history.prompt.add_or_update_prompt"),
        patch(
            "sase.xprompt.processor.process_xprompt_references",
            return_value=expanded,
        ) as expand,
        patch(
            "sase.agent.multi_prompt_launcher.launch_multi_prompt_agents",
            return_value=launched,
        ) as launch_multi,
    ):
        result = launch_agents_from_cwd("#stub_m Do work")

    assert result == launched
    expand.assert_called_once_with("#stub_m Do work")
    launch_multi.assert_called_once()
    assert launch_multi.call_args.kwargs["segments"] == ["#stub_m Do work"]
    fanout_plan = launch_multi.call_args.kwargs["preplanned_fanout_plans"][0]
    assert [slot.prompt for slot in fanout_plan.slots] == [
        "%name:ag.cld_opus\n%model:opus\nDo work",
        "%name:ag.cld_sonnet\n%model:sonnet\nDo work",
    ]


def test_launch_agents_from_cwd_unexpanded_xprompt_stays_single_agent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_cd_metadata(monkeypatch)
    from sase.agent.launcher import launch_agents_from_cwd

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
            "sase.xprompt.processor.process_xprompt_references",
            return_value="#stub_m Do work",
        ) as expand,
        patch(
            "sase.agent.multi_prompt_launcher.launch_multi_prompt_agents",
        ) as launch_multi,
        patch(
            "sase.agent.launcher.spawn_agent_subprocess",
            return_value=spawn_result,
        ) as spawn,
    ):
        result = launch_agents_from_cwd("#stub_m Do work")

    assert result == [spawn_result]
    expand.assert_called_once_with("#stub_m Do work")
    launch_multi.assert_not_called()
    spawn.assert_called_once()
    assert spawn.call_args.kwargs["prompt"] == "#stub_m Do work"


def test_launch_agents_from_cwd_multi_agent_xprompt_history_uses_submitted_prompt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_cd_metadata(monkeypatch)
    from sase.agent.launcher import launch_agents_from_cwd
    from sase.history import prompt as prompt_history
    from sase.xprompt.models import XPrompt

    history_path = tmp_path / ".sase" / "prompt_history.json"
    monkeypatch.setattr(prompt_history, "_PROMPT_HISTORY_FILE", history_path)
    monkeypatch.setattr(prompt_history, "generate_timestamp", lambda: "260501_120000")
    launched = [MagicMock(name="plan"), MagicMock(name="build")]
    catalog = {"swarm": XPrompt(name="swarm", content="Plan phase\n---\nBuild phase")}

    with (
        patch(
            "sase.main.utils.ensure_project_file_and_get_workspace_num",
            return_value=(None, None, None),
        ),
        patch(
            "sase.agent.multi_agent_xprompt.get_all_xprompts",
            return_value=catalog,
        ),
        patch(
            "sase.agent.multi_prompt_launcher.launch_multi_prompt_agents",
            return_value=launched,
        ) as launch_multi,
    ):
        result = launch_agents_from_cwd("#!swarm")

    assert result == launched
    assert launch_multi.call_args.kwargs["segments"] == ["Plan phase", "Build phase"]
    entries = json.loads(history_path.read_text(encoding="utf-8"))["prompts"]
    assert [entry["text"] for entry in entries] == ["#!swarm"]
    assert all("Plan phase" not in entry["text"] for entry in entries)


def test_launch_agents_from_cwd_multi_agent_xprompt_cancelled_history_uses_submitted_prompt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_cd_metadata(monkeypatch)
    from sase.agent.launch_validation import AgentNameSyntaxError
    from sase.agent.launcher import launch_agents_from_cwd
    from sase.history import prompt as prompt_history
    from sase.xprompt.models import XPrompt

    history_path = tmp_path / ".sase" / "prompt_history.json"
    monkeypatch.setattr(prompt_history, "_PROMPT_HISTORY_FILE", history_path)
    monkeypatch.setattr(prompt_history, "generate_timestamp", lambda: "260501_120000")
    catalog = {
        "swarm": XPrompt(
            name="swarm",
            content="%name:bad--name\nPlan phase\n---\nBuild phase",
        )
    }

    with (
        patch(
            "sase.main.utils.ensure_project_file_and_get_workspace_num",
            return_value=(None, None, None),
        ),
        patch(
            "sase.agent.multi_agent_xprompt.get_all_xprompts",
            return_value=catalog,
        ),
        patch("sase.agent.multi_prompt_launcher.launch_multi_prompt_agents") as launch,
    ):
        with pytest.raises(AgentNameSyntaxError):
            launch_agents_from_cwd("#!swarm")

    launch.assert_not_called()
    entries = json.loads(history_path.read_text(encoding="utf-8"))["prompts"]
    assert [entry["text"] for entry in entries] == ["#!swarm"]
    assert entries[0]["cancelled"] is True
    assert "Plan phase" not in entries[0]["text"]


def test_launch_agents_from_cwd_multi_agent_xprompt_failure_forces_cancelled_history(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_cd_metadata(monkeypatch)
    from sase.agent.launcher import launch_agents_from_cwd
    from sase.history import prompt as prompt_history
    from sase.xprompt.models import XPrompt

    history_path = tmp_path / ".sase" / "prompt_history.json"
    monkeypatch.setattr(prompt_history, "_PROMPT_HISTORY_FILE", history_path)
    monkeypatch.setattr(prompt_history, "generate_timestamp", lambda: "260501_120000")
    catalog = {"swarm": XPrompt(name="swarm", content="Plan phase\n---\nBuild phase")}

    with (
        patch(
            "sase.main.utils.ensure_project_file_and_get_workspace_num",
            return_value=(None, None, None),
        ),
        patch(
            "sase.agent.multi_agent_xprompt.get_all_xprompts",
            return_value=catalog,
        ),
        patch(
            "sase.agent.multi_prompt_launcher.launch_multi_prompt_agents",
            side_effect=RuntimeError("multi boom"),
        ),
    ):
        with pytest.raises(RuntimeError, match="multi boom"):
            launch_agents_from_cwd("#!swarm")

    entries = json.loads(history_path.read_text(encoding="utf-8"))["prompts"]
    assert [entry["text"] for entry in entries] == ["#!swarm"]
    assert entries[0]["cancelled"] is True
