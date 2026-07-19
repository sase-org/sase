from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.agent.clan_membership import CLAN_MEMBERSHIP_ENV
from sase.agent.launch_types import AgentLaunchResult
from sase.agent.multi_prompt_launcher import launch_multi_prompt_agents
from sase.history.prompt_metadata import summarize_prompt_for_list
from sase.xprompt._exceptions import DirectiveError
from sase.xprompt.directives import extract_prompt_directives
from sase.xprompt.models import XPrompt


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


def _persist_first_clan_member(
    sase_home: Path,
    call: dict[str, object],
) -> None:
    from sase.agent.names import rebuild_name_registry

    env = call["extra_env"]
    assert isinstance(env, dict)
    payload = json.loads(str(env[CLAN_MEMBERSHIP_ENV]))
    agent_name = str(env["SASE_AGENT_PLANNED_NAME"])
    artifacts_dir = (
        sase_home / "projects/sase/artifacts/ace-run" / str(payload["generation"])
    )
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": agent_name,
                "agent_clan": payload["clan_name"],
                "agent_clan_generation": payload["generation"],
            }
        ),
        encoding="utf-8",
    )
    rebuild_name_registry()


def test_template_clan_is_resolved_once_without_a_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    calls = _launch_with_captured_spawns(
        [
            "%id:research.@.worker\n%clan:research.@\nWork",
            "%id(final, clan=research.@)\nLead",
        ],
        template_groups=["xprompt:research:0", "xprompt:research:0"],
    )

    assert len(calls) == 2
    envs = [call["extra_env"] for call in calls]
    assert all(isinstance(env, dict) for env in envs)
    names = [str(env["SASE_AGENT_PLANNED_NAME"]) for env in envs]  # type: ignore[index]
    assert names == ["research.0.worker", "research.0.final"]
    payloads = [
        json.loads(str(env[CLAN_MEMBERSHIP_ENV]))  # type: ignore[index]
        for env in envs
    ]
    assert payloads[0] == payloads[1]
    assert payloads[0]["clan_name"] == "research.0"
    assert set(payloads[0]) == {"clan_name", "generation"}


def test_research_swarm_style_launch_resolves_names_waits_and_tribe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    calls = _launch_with_captured_spawns(
        [
            "%clan(research.@, tribe=research)\n%id:research.@.lead\nLead",
            "%id(worker, clan=research.@)\n%wait:research.@.lead\nInvestigate",
            "%id(final, clan=research.@)\n%wait:research.@.worker\nSynthesize",
        ],
        template_groups=[
            "xprompt:research:0",
            "xprompt:research:0",
            "xprompt:research:0",
        ],
    )

    envs = [call["extra_env"] for call in calls]
    assert all(isinstance(env, dict) for env in envs)
    assert [str(env["SASE_AGENT_PLANNED_NAME"]) for env in envs] == [  # type: ignore[index]
        "research.0.lead",
        "research.0.worker",
        "research.0.final",
    ]
    payloads = [
        json.loads(str(env[CLAN_MEMBERSHIP_ENV]))  # type: ignore[index]
        for env in envs
    ]
    assert payloads[0] == payloads[1] == payloads[2]
    assert payloads[0]["clan_name"] == "research.0"
    assert payloads[0]["generation"]

    prompts = [str(call["prompt"]) for call in calls]
    assert "%wait:research.0.lead" in prompts[1]
    assert "%wait:research.0.worker" in prompts[2]
    parsed = [extract_prompt_directives(prompt)[1] for prompt in prompts]
    assert [directive.clan_tribe for directive in parsed] == [
        "research",
        None,
        None,
    ]
    assert [directive.clan_declared for directive in parsed] == [True, False, False]


def test_clan_membership_is_execution_neutral(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline_segments = [
        "%id:research.@.final\n%model:opus\nLead",
        "%id:research.@.worker\n%model:sonnet\n%wait:research.@.final\nWork",
        "%id:review\n%wait\nReview",
    ]
    clan_segments = [
        baseline_segments[0].replace(
            "%model:opus\n", "%model:opus\n%clan:research.@\n"
        ),
        baseline_segments[1].replace(
            "%id:research.@.worker\n%model:sonnet\n",
            "%id(worker, clan=research.@)\n%model:sonnet\n",
        ),
        baseline_segments[2],
    ]
    template_groups = ["xprompt:research:0", "xprompt:research:0", None]

    monkeypatch.setenv("SASE_HOME", str(tmp_path / "baseline" / ".sase"))
    baseline = _launch_with_captured_spawns(
        baseline_segments,
        template_groups=template_groups,
    )
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "clan" / ".sase"))
    clan = _launch_with_captured_spawns(
        clan_segments,
        template_groups=template_groups,
    )

    def planned_names(calls: list[dict[str, object]]) -> list[str]:
        return [
            str(call["extra_env"]["SASE_AGENT_PLANNED_NAME"])  # type: ignore[index]
            for call in calls
        ]

    assert (
        planned_names(clan)
        == planned_names(baseline)
        == [
            "research.0.final",
            "research.0.worker",
            "review",
        ]
    )
    clan_prompts = [str(call["prompt"]) for call in clan]
    assert "%wait:research.0.final" in clan_prompts[1]
    assert "%wait:research.0.worker" in clan_prompts[2]
    assert CLAN_MEMBERSHIP_ENV in clan[0]["extra_env"]  # type: ignore[operator]
    assert CLAN_MEMBERSHIP_ENV in clan[1]["extra_env"]  # type: ignore[operator]
    assert CLAN_MEMBERSHIP_ENV not in clan[2]["extra_env"]  # type: ignore[operator]


def test_clan_member_fanout_variants_share_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    calls = _launch_with_captured_spawns(
        ["%id:root.worker\n%clan:root\n%{First | Second}"]
    )

    assert len(calls) == 2
    payloads = [
        json.loads(str(call["extra_env"][CLAN_MEMBERSHIP_ENV]))  # type: ignore[index]
        for call in calls
    ]
    assert payloads[0] == payloads[1]
    assert payloads[0]["clan_name"] == "root"


def test_declaration_and_joiner_share_generation_and_only_declaration_has_tribe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    calls = _launch_with_captured_spawns(
        [
            "%id:root.one\n%clan(root, tribe=alpha)\nOne",
            "%id(two, clan=root)\nTwo",
        ]
    )

    payloads = [
        json.loads(str(call["extra_env"][CLAN_MEMBERSHIP_ENV]))  # type: ignore[index]
        for call in calls
    ]
    assert payloads[0] == payloads[1]
    assert payloads[0]["clan_name"] == "root"


def test_duplicate_clan_declarations_spawn_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    with pytest.raises(DirectiveError, match="declared in more than one prompt"):
        _launch_with_captured_spawns(
            [
                "%id:root.one\n%clan:root\nOne",
                "%id:root.two\n%clan:root\nTwo",
            ]
        )


def test_joiners_only_create_then_reuse_clan_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    first = _launch_with_captured_spawns(
        ["%id(one, clan=root)\nOne", "%id(two, clan=root)\nTwo"]
    )
    _persist_first_clan_member(tmp_path / ".sase", first[0])
    second = _launch_with_captured_spawns(["%id(three, clan=root)\nThree"])

    first_payloads = [
        json.loads(str(call["extra_env"][CLAN_MEMBERSHIP_ENV]))  # type: ignore[index]
        for call in first
    ]
    second_payload = json.loads(
        str(second[0]["extra_env"][CLAN_MEMBERSHIP_ENV])  # type: ignore[index]
    )
    assert first_payloads[0] == first_payloads[1] == second_payload
    prompts = [*(str(call["prompt"]) for call in first), str(second[0]["prompt"])]
    assert all(
        extract_prompt_directives(prompt)[1].clan_tribe is None for prompt in prompts
    )


@pytest.mark.parametrize(
    ("prompt", "message"),
    [
        (
            "%id(worker, clan=root)\n%tribe:review\nWork",
            r"joining a clan joins its tribe.*Put tribe= on the clan's %clan",
        ),
        (
            "%id(worker, clan=root)\n%clan:root\nWork",
            r"Cannot combine %clan with %id\(\.\.\., clan=\.\.\.\)",
        ),
        (
            "%id(parent, worker, clan=root)\nWork",
            "positional family form",
        ),
        (
            "%id(clan=root)\nWork",
            "requires exactly one positional member id",
        ),
    ],
)
def test_prompt_local_clan_errors_surface_through_launch_preflight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    prompt: str,
    message: str,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))

    with pytest.raises(DirectiveError, match=message):
        _launch_with_captured_spawns([prompt])


def test_declaration_rejects_existing_clan_but_joiner_succeeds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    first = _launch_with_captured_spawns(["%id(one, clan=root)\nOne"])
    _persist_first_clan_member(tmp_path / ".sase", first[0])

    with pytest.raises(
        DirectiveError,
        match=r"clan 'root' already exists.*%id\(<id>, clan=root\)",
    ):
        _launch_with_captured_spawns(["%id:root.two\n%clan:root\nTwo"])

    calls = _launch_with_captured_spawns(["%id(three, clan=root)\nThree"])
    assert len(calls) == 1


def test_deprecated_name_fails_launch_but_remains_display_safe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    prompt = "%name:legacy\nReview the parser"

    with pytest.raises(
        DirectiveError,
        match=r"renamed; use %id/%i.*%id\(<id>, clan=<clan>\)",
    ):
        _launch_with_captured_spawns([prompt])

    summary = summarize_prompt_for_list(prompt)
    assert summary.directive_token == "%n"
    assert summary.clean_preview == "Review the parser"


def test_xprompt_introduced_clan_tribe_conflict_spawns_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    spawn = patch("sase.agent.launcher.spawn_agent_subprocess")
    with (
        spawn as mock_spawn,
        pytest.raises(
            DirectiveError,
            match="Cannot combine %tribe with %clan",
        ),
    ):
        launch_multi_prompt_agents(
            segments=["%id:root.one\n%tribe:research\n#_join"],
            local_xprompts={
                "_join": XPrompt(
                    name="_join",
                    content="%clan(root, tribe=research)\nWork",
                )
            },
            cl_name="feature",
            project_file="/tmp/sase.sase",
            project_name="sase",
            is_home_mode=True,
            vcs_ref=None,
        )
    mock_spawn.assert_not_called()


@pytest.mark.parametrize(
    "segments",
    [
        ["%id:outsider\n%clan:root\nWork"],
        ["%id:root\n%clan:root\nWork"],
    ],
)
def test_clan_rejects_members_outside_its_hood_before_spawn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    segments: list[str],
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    with pytest.raises(DirectiveError, match="clan members must use"):
        _launch_with_captured_spawns(segments)
