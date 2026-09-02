"""Typed launch identity wire, dispatch reconstruction, and keyed-marker batching."""

from __future__ import annotations

from collections.abc import Iterable
from contextlib import nullcontext

import pytest

from sase.core.agent_launch_facade import (
    agent_unit_dispatch_prompt,
    plan_typed_launch_units,
)
from sase.core.agent_launch_wire import (
    AgentUnitWire,
    agent_launch_wire_to_json_dict,
    launch_plan_from_dict,
)
from sase.feature_flags import override_flags
from sase.xprompt.directives import extract_prompt_directives


def _configure_allocation(
    monkeypatch: pytest.MonkeyPatch,
    tokens: Iterable[str],
    *,
    reserved: set[str] | None = None,
    clans: set[str] | None = None,
) -> None:
    monkeypatch.setattr(
        "sase.agent.agent_name_keys.agent_name_allocation_lock",
        nullcontext,
    )
    monkeypatch.setattr(
        "sase.agent.agent_name_keys.get_reserved_agent_names",
        lambda: set(reserved or ()),
    )
    monkeypatch.setattr(
        "sase.agent.agent_name_keys.get_reserved_clan_names",
        lambda: set(clans or ()),
    )
    monkeypatch.setattr(
        "sase.agent.agent_name_keys.get_blocked_local_namespace_roots",
        lambda: {},
    )
    token_values = tuple(tokens)
    monkeypatch.setattr(
        "sase.agent.agent_name_keys.iter_agent_name_template_tokens",
        lambda: iter(token_values),
    )


def test_legacy_agent_unit_json_defaults_to_plain_identity() -> None:
    plan = launch_plan_from_dict(
        {
            "schema_version": 1,
            "launch_kind": "auto",
            "selected_project": "sase",
            "content_digest": "a" * 64,
            "units": [
                {
                    "logical_id": "unit-1",
                    "source_order": 0,
                    "waits": [],
                    "payload": {
                        "kind": "agent",
                        "prompt": "Review",
                        "identity": "reviewer",
                        "identity_explicit": True,
                    },
                }
            ],
            "diagnostics": [],
        }
    )

    agent = plan.units[0].payload
    assert isinstance(agent, AgentUnitWire)
    assert agent.identity == "reviewer"
    assert agent.identity_explicit is True
    assert agent.clan is None
    assert agent.clan_declared is False
    assert agent.tribe is None
    assert agent.family_attach_parent is None
    payload = agent_launch_wire_to_json_dict(agent)
    assert "clan" not in payload
    assert "clan_declared" not in payload
    assert "tribe" not in payload


@pytest.mark.parametrize(
    ("prompt", "expect"),
    [
        (
            "%id:reviewer\nReview",
            {
                "identity": "reviewer",
                "identity_explicit": True,
                "clan": None,
                "clan_declared": False,
            },
        ),
        (
            "%id(worker, clan=research)\nJoin",
            {
                "identity": "worker",
                "identity_explicit": True,
                "clan": "research",
                "clan_declared": False,
            },
        ),
        (
            "%id:research.worker\n%clan(research, tribe=study, summary=[[ [bold]R[/bold] ]])\nLead",
            {
                "identity": "research.worker",
                "identity_explicit": True,
                "clan": "research",
                "clan_declared": True,
                "clan_tribe": "study",
                "clan_summary": "[bold]R[/bold]",
            },
        ),
        (
            "%id(reviewer, family=parent)\nReview",
            {
                "family_attach_parent": "parent",
                "family_attach_suffix": "reviewer",
                "identity": None,
            },
        ),
        (
            "%id(worker, tribe=review)\nReview",
            {"identity": "worker", "tribe": "review"},
        ),
        (
            "%id(tribe=review)\nReview",
            {"identity": None, "identity_explicit": False, "tribe": "review"},
        ),
    ],
)
def test_plan_typed_launch_units_preserves_identity_forms(
    prompt: str, expect: dict[str, object]
) -> None:
    pytest.importorskip("sase_core_rs")
    with override_flags(typed_launch_units=True):
        plan = plan_typed_launch_units(prompt, selected_project="sase")
    agent = plan.units[0].payload
    assert isinstance(agent, AgentUnitWire)
    for field, value in expect.items():
        assert getattr(agent, field) == value, field

    rebuilt = agent_unit_dispatch_prompt(agent)
    _, directives = extract_prompt_directives(rebuilt)
    if agent.clan_declared:
        assert directives.clan == agent.clan
        assert directives.clan_declared is True
        assert directives.clan_tribe == agent.clan_tribe
        assert directives.clan_summary == agent.clan_summary
        assert directives.name == agent.identity
    elif agent.clan is not None:
        assert directives.clan == agent.clan
        assert directives.clan_declared is False
        assert directives.name == f"{agent.clan}.{agent.identity}"
    elif agent.family_attach_parent is not None:
        assert directives.family_attach_parent == agent.family_attach_parent
        assert directives.family_attach_suffix == agent.family_attach_suffix
    elif agent.tribe is not None:
        assert directives.tribe == agent.tribe
        if agent.identity is not None:
            assert directives.name == agent.identity
    else:
        assert directives.name == agent.identity


def test_typed_dispatch_prompt_matches_extract_prompt_directives() -> None:
    pytest.importorskip("sase_core_rs")
    prompt = (
        "%id:toobig-3j.foo.0\n"
        "%clan(toobig-3j, tribe=chop, summary=[[ [bold]Large[/bold] ]])\n"
        "Lead\n"
        "---\n"
        "%id(bar.0, clan=toobig-3j)\n"
        "%wait:toobig-3j.foo.0\n"
        "Join"
    )
    with override_flags(typed_launch_units=True):
        plan = plan_typed_launch_units(
            prompt, launch_kind="multi_prompt", selected_project="sase"
        )
    declarer = plan.units[0].payload
    joiner = plan.units[1].payload
    assert isinstance(declarer, AgentUnitWire)
    assert isinstance(joiner, AgentUnitWire)
    assert declarer.clan_declared is True
    assert joiner.clan == "toobig-3j"
    assert joiner.clan_declared is False
    assert plan.units[1].waits[0].logical_id == "unit-1"

    rebuilt_decl = agent_unit_dispatch_prompt(declarer)
    rebuilt_join = agent_unit_dispatch_prompt(joiner)
    _, decl_dirs = extract_prompt_directives(rebuilt_decl)
    _, join_dirs = extract_prompt_directives(rebuilt_join)
    assert decl_dirs.name == "toobig-3j.foo.0"
    assert decl_dirs.clan == "toobig-3j"
    assert decl_dirs.clan_declared is True
    assert decl_dirs.clan_tribe == "chop"
    assert decl_dirs.clan_summary == "[bold]Large[/bold]"
    assert join_dirs.name == "toobig-3j.bar.0"
    assert join_dirs.clan == "toobig-3j"
    assert join_dirs.clan_declared is False
    assert "%wait:" not in rebuilt_decl
    assert "%if" not in rebuilt_decl


def test_typed_launch_resolves_shared_keyed_clan_marker_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("sase_core_rs")
    _configure_allocation(monkeypatch, ["3j", "zz"])
    prompt = (
        "%id:toobig-{@lead!}.foo.0\n"
        "%clan(toobig-{@lead!}, tribe=chop)\n"
        "See toobig-{@lead!}.foo.0 in prose\n"
        "```text\n"
        "literal toobig-{@lead!}.kept\n"
        "```\n"
        "%xprompts_enabled:false\n"
        "disabled toobig-{@lead!}.kept\n"
        "%xprompts_enabled:true\n"
        "Lead\n"
        "---\n"
        "%id(bar.0, clan=toobig-{@lead!})\n"
        "%wait:toobig-{@lead!}.foo.0\n"
        "Join toobig-{@lead!}.bar.0"
    )
    with override_flags(typed_launch_units=True):
        plan = plan_typed_launch_units(
            prompt, launch_kind="multi_prompt", selected_project="sase"
        )

    declarer = plan.units[0].payload
    joiner = plan.units[1].payload
    assert isinstance(declarer, AgentUnitWire)
    assert isinstance(joiner, AgentUnitWire)
    assert declarer.clan == "toobig-3j"
    assert joiner.clan == "toobig-3j"
    assert declarer.identity == "toobig-3j.foo.0"
    assert joiner.identity == "bar.0"
    assert "toobig-3j.foo.0" in declarer.prompt
    assert "literal toobig-{@lead!}.kept" in declarer.prompt
    assert "disabled toobig-{@lead!}.kept" in declarer.prompt
    assert "{@lead!}" not in (declarer.identity or "")
    assert "{@lead!}" not in (joiner.clan or "")
    assert plan.units[1].waits[0].kind == "logical"
    assert plan.units[1].waits[0].logical_id == "unit-1"

    rebuilt_decl = agent_unit_dispatch_prompt(declarer)
    rebuilt_join = agent_unit_dispatch_prompt(joiner)
    _, decl_dirs = extract_prompt_directives(rebuilt_decl)
    _, join_dirs = extract_prompt_directives(rebuilt_join)
    assert decl_dirs.clan == "toobig-3j"
    assert join_dirs.clan == "toobig-3j"
    assert decl_dirs.name == "toobig-3j.foo.0"
    assert join_dirs.name == "toobig-3j.bar.0"
