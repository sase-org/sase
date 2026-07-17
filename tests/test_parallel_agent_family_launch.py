from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.agent.family_membership import FAMILY_MEMBERSHIP_ENV
from sase.agent.launch_types import AgentLaunchResult
from sase.agent.multi_prompt_launcher import launch_multi_prompt_agents
from sase.xprompt._exceptions import DirectiveError


def _launch_with_captured_spawns(
    segments: list[str],
    *,
    template_groups: list[str | None] | None = None,
) -> list[dict[str, object]]:
    calls: list[dict[str, object]] = []

    def spawn_agent(**kwargs: object) -> AgentLaunchResult:
        calls.append(kwargs)
        return AgentLaunchResult(
            pid=len(calls),
            workspace_num=int(str(kwargs["workspace_num"])),
            workspace_dir=str(kwargs["workspace_dir"]),
            output_path="/tmp/out",
            project_file=str(kwargs["project_file"]),
            project_name=str(kwargs["project_name"]),
            workflow_name=str(kwargs["workflow_name"]),
            cl_name=str(kwargs["cl_name"]),
            timestamp=str(kwargs["timestamp"]),
        )

    with (
        patch("sase.agent.names.ensure_historical_auto_name_migration"),
        patch("sase.agent.launcher.spawn_agent_subprocess", side_effect=spawn_agent),
    ):
        launch_multi_prompt_agents(
            segments=segments,
            local_xprompts={},
            cl_name="feature",
            project_file="/tmp/sase.sase",
            project_name="sase",
            is_home_mode=True,
            vcs_ref=None,
            segment_template_groups=template_groups,
        )
    return calls


def test_member_before_template_root_gets_pinned_family_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    calls = _launch_with_captured_spawns(
        [
            "%name:research.@.worker\n"
            "%wait:research.@.final\n"
            "%family(research.@.final, role=researcher)\nWork",
            "%name:research.@.final\nLead",
        ],
        template_groups=["xprompt:research:0", "xprompt:research:0"],
    )

    assert len(calls) == 2
    member_env = calls[0]["extra_env"]
    root_env = calls[1]["extra_env"]
    assert isinstance(member_env, dict)
    assert isinstance(root_env, dict)
    member_payload = json.loads(str(member_env[FAMILY_MEMBERSHIP_ENV]))
    root_payload = json.loads(str(root_env[FAMILY_MEMBERSHIP_ENV]))

    root_name = str(root_env["SASE_AGENT_PLANNED_NAME"])
    member_name = str(member_env["SASE_AGENT_PLANNED_NAME"])
    token = root_name.removeprefix("research.").removesuffix(".final")
    assert member_name == f"research.{token}.worker"
    assert "%wait:" + root_name in str(calls[0]["prompt"])
    assert member_payload == {
        **root_payload,
        "is_root": False,
        "role": "researcher",
    }
    assert root_payload["family_base"] == root_name
    assert root_payload["is_root"] is True
    assert root_payload["role"] == "root"
    assert root_payload["root_timestamp"] == (
        "20" + str(calls[1]["timestamp"])[:6] + str(calls[1]["timestamp"])[7:]
    )


def test_family_membership_is_execution_neutral_for_multi_prompt_launches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline_segments = [
        "%name:research.@.final\n%model:opus\nLead",
        "%name:research.@.worker\n%model:sonnet\n%wait:research.@.final\nWork",
        "%name:review\n%wait\nReview",
    ]
    family_segments = [
        baseline_segments[0],
        baseline_segments[1].replace(
            "%model:sonnet\n",
            "%model:sonnet\n%family(research.@.final, role=researcher)\n",
        ),
        baseline_segments[2],
    ]
    template_groups = [
        "xprompt:research:0",
        "xprompt:research:0",
        None,
    ]

    monkeypatch.setenv("SASE_HOME", str(tmp_path / "baseline" / ".sase"))
    baseline = _launch_with_captured_spawns(
        baseline_segments,
        template_groups=template_groups,
    )
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "family" / ".sase"))
    family = _launch_with_captured_spawns(
        family_segments,
        template_groups=template_groups,
    )

    def planned_names(calls: list[dict[str, object]]) -> list[str]:
        return [
            str(call["extra_env"]["SASE_AGENT_PLANNED_NAME"])  # type: ignore[index]
            for call in calls
        ]

    assert planned_names(family) == planned_names(baseline)
    assert planned_names(family) == [
        "research.0.final",
        "research.0.worker",
        "review",
    ]

    family_prompts_without_membership = [
        str(call["prompt"]).replace(
            "%family(research.@.final, role=researcher)\n",
            "",
        )
        for call in family
    ]
    baseline_prompts = [str(call["prompt"]) for call in baseline]
    assert family_prompts_without_membership == baseline_prompts
    assert "%wait:research.0.final" in baseline_prompts[1]
    assert "%wait:research.0.worker" in baseline_prompts[2]

    def model_directive(prompt: str) -> str | None:
        return next(
            (
                line.removeprefix("%model:")
                for line in prompt.splitlines()
                if line.startswith("%model:")
            ),
            None,
        )

    baseline_models = [model_directive(prompt) for prompt in baseline_prompts]
    family_models = [model_directive(str(call["prompt"])) for call in family]
    assert family_models == baseline_models == ["opus", "sonnet", None]

    context_keys = (
        "cl_name",
        "project_file",
        "project_name",
        "history_sort_key",
        "update_target",
        "is_home_mode",
        "vcs_ref",
    )
    workspace_keys = ("workspace_num", "workspace_dir", "deferred_workspace")
    for baseline_call, family_call in zip(baseline, family, strict=True):
        assert {key: family_call[key] for key in context_keys} == {
            key: baseline_call[key] for key in context_keys
        }
        assert {key: family_call[key] for key in workspace_keys} == {
            key: baseline_call[key] for key in workspace_keys
        }

    family_envs = [call["extra_env"] for call in family]
    assert all(isinstance(env, dict) for env in family_envs)
    assert FAMILY_MEMBERSHIP_ENV not in baseline[0]["extra_env"]  # type: ignore[operator]
    assert FAMILY_MEMBERSHIP_ENV in family_envs[0]  # type: ignore[operator]
    assert FAMILY_MEMBERSHIP_ENV in family_envs[1]  # type: ignore[operator]
    assert FAMILY_MEMBERSHIP_ENV not in family_envs[2]  # type: ignore[operator]


def test_family_member_fanout_variants_join_the_same_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    calls = _launch_with_captured_spawns(
        [
            "%name:worker\n%family(root, role=worker)\n%{First | Second}",
            "%name:root\nLead",
        ]
    )

    assert len(calls) == 3
    assert [
        call["extra_env"]["SASE_AGENT_PLANNED_NAME"]  # type: ignore[index]
        for call in calls
    ] == ["worker.1", "worker.2", "root"]
    member_payloads = [
        json.loads(str(calls[index]["extra_env"][FAMILY_MEMBERSHIP_ENV]))  # type: ignore[index]
        for index in (0, 1)
    ]
    root_payload = json.loads(
        str(calls[2]["extra_env"][FAMILY_MEMBERSHIP_ENV])  # type: ignore[index]
    )

    assert member_payloads[0] == member_payloads[1]
    assert member_payloads[0] == {
        **root_payload,
        "is_root": False,
        "role": "worker",
    }
    assert root_payload["is_root"] is True
    assert root_payload["role"] == "root"


def test_family_root_fanout_is_rejected_before_spawn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    with pytest.raises(DirectiveError, match="exactly one launch slot"):
        _launch_with_captured_spawns(
            [
                "%name:worker\n%family:root\nWork",
                "%name:root\n%{First | Second}",
            ]
        )


def test_family_target_rejects_duplicate_sibling_roots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    with pytest.raises(DirectiveError, match="more than one sibling root"):
        _launch_with_captured_spawns(
            [
                "%name:worker\n%family:root\nWork",
                "%name:root\nLead one",
                "%name:root\nLead two",
            ]
        )


def test_family_segment_cannot_target_itself(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    with pytest.raises(DirectiveError, match="cannot target itself"):
        _launch_with_captured_spawns(["%name:root\n%family:root\nWork"])
