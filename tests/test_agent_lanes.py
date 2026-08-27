from __future__ import annotations

import pytest

from sase.agent_lanes import (
    AgentLaneRef,
    lane_name,
    lane_page_path,
    lane_ref_for_agent,
    lane_ref_for_lane_name,
)
from sase.core.agent_identity_facade import AgentIdentitySnapshot, AgentOwnerIdentity
from sase.sase_agent import (
    SaseAgentRef,
    sase_agent_name,
    sase_agent_page_path,
    sase_agent_ref_for_name,
    sase_agent_ref_for_shell,
)

_OWNER = AgentOwnerIdentity("alice", "athena")
_IDENTITY = AgentIdentitySnapshot(_OWNER)


def test_compatibility_aliases_are_the_canonical_objects() -> None:
    assert AgentLaneRef is SaseAgentRef
    assert lane_ref_for_agent is sase_agent_ref_for_shell
    assert lane_ref_for_lane_name is sase_agent_ref_for_name
    assert lane_page_path is sase_agent_page_path
    assert lane_name is sase_agent_name


def test_solo_agent_shell_projects_to_itself() -> None:
    ref = sase_agent_ref_for_shell("pc", _IDENTITY)

    assert ref == SaseAgentRef(
        local_name="pc",
        global_name="alice.athena.pc",
        is_family=False,
        member_local_name=None,
    )
    assert sase_agent_page_path(ref, _OWNER) == "agents/alice.athena.pc/README.md"
    assert lane_ref_for_agent("pc", _IDENTITY) == ref
    assert lane_page_path(ref, _OWNER) == "agents/alice.athena.pc/README.md"


def test_family_member_shell_projects_to_its_family_container() -> None:
    ref = sase_agent_ref_for_shell("pc--code", _IDENTITY)

    assert ref == SaseAgentRef(
        local_name="pc",
        global_name="alice.athena.pc",
        is_family=True,
        member_local_name="pc--code",
    )
    assert sase_agent_page_path(ref, _OWNER) == "families/alice.athena.pc.md"
    assert (
        AgentLaneRef(
            local_name="pc",
            global_name="alice.athena.pc",
            is_family=True,
            member_local_name="pc--code",
        )
        == ref
    )


def test_nested_family_member_keeps_its_dotted_family_name() -> None:
    ref = sase_agent_ref_for_shell("foo.bar--code", _IDENTITY)

    assert ref.local_name == "foo.bar"
    assert ref.global_name == "alice.athena.foo.bar"
    assert ref.is_family
    assert sase_agent_page_path(ref, _OWNER) == "families/alice.athena.foo.bar.md"


def test_legacy_machine_qualified_member_normalizes_to_the_bare_sase_agent() -> None:
    ref = sase_agent_ref_for_shell("athena.sase-7r.land--code", _IDENTITY)

    assert ref == SaseAgentRef(
        local_name="sase-7r.land",
        global_name="alice.athena.sase-7r.land",
        is_family=True,
        member_local_name="sase-7r.land--code",
    )


def test_globally_qualified_member_normalizes_to_the_bare_sase_agent() -> None:
    ref = sase_agent_ref_for_shell("alice.athena.pc--code", _IDENTITY)

    assert ref.local_name == "pc"
    assert ref.member_local_name == "pc--code"


def test_reserved_family_container_name_is_a_family(monkeypatch) -> None:
    monkeypatch.setattr(
        "sase.agent.names.get_reserved_family_names_for_display",
        lambda: {"pc"},
    )

    ref = sase_agent_ref_for_name("pc", _IDENTITY)

    assert ref == SaseAgentRef(
        local_name="pc",
        global_name="alice.athena.pc",
        is_family=True,
        member_local_name=None,
    )
    assert sase_agent_page_path(ref, _OWNER) == "families/alice.athena.pc.md"
    assert lane_ref_for_lane_name("pc", _IDENTITY) == ref


def test_already_projected_solo_name_stays_solo(monkeypatch) -> None:
    monkeypatch.setattr(
        "sase.agent.names.get_reserved_family_names_for_display",
        lambda: {"other"},
    )

    ref = sase_agent_ref_for_name("pc", _IDENTITY)

    assert not ref.is_family
    assert sase_agent_page_path(ref, _OWNER) == "agents/alice.athena.pc/README.md"


def test_name_lookup_degrades_to_solo_when_the_registry_fails(
    monkeypatch,
) -> None:
    def _explode() -> set[str]:
        raise RuntimeError("registry unreadable")

    monkeypatch.setattr(
        "sase.agent.names.get_reserved_family_names_for_display", _explode
    )

    assert not sase_agent_ref_for_name("pc", _IDENTITY).is_family
    assert not lane_ref_for_lane_name("pc", _IDENTITY).is_family


def test_name_lookup_accepts_a_member_spelling(monkeypatch) -> None:
    monkeypatch.setattr(
        "sase.agent.names.get_reserved_family_names_for_display", lambda: set()
    )

    ref = sase_agent_ref_for_name("pc--code", _IDENTITY)

    assert ref == SaseAgentRef(
        local_name="pc",
        global_name="alice.athena.pc",
        is_family=True,
        member_local_name="pc--code",
    )


def test_legacy_machine_qualified_sase_agent_name_normalizes(monkeypatch) -> None:
    monkeypatch.setattr(
        "sase.agent.names.get_reserved_family_names_for_display",
        lambda: {"sase-7r.land"},
    )

    ref = sase_agent_ref_for_name("athena.sase-7r.land", _IDENTITY)

    assert ref.local_name == "sase-7r.land"
    assert ref.global_name == "alice.athena.sase-7r.land"
    assert ref.is_family


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("pc", "pc"),
        ("pc--code", "pc"),
        ("foo.bar--code", "foo.bar"),
        ("alice.athena.pc--code", "alice.athena.pc"),
        ("alice.athena.pc", "alice.athena.pc"),
        ("foo--code.f0", "foo--code.f0"),
    ],
)
def test_sase_agent_name_projects_labels_without_requalifying(
    name: str, expected: str
) -> None:
    assert sase_agent_name(name) == expected
    assert lane_name(name) == expected
