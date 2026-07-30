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

_OWNER = AgentOwnerIdentity("alice", "athena")
_IDENTITY = AgentIdentitySnapshot(_OWNER)


def test_solo_agent_lane_is_the_agent_itself() -> None:
    ref = lane_ref_for_agent("pc", _IDENTITY)

    assert ref == AgentLaneRef(
        local_name="pc",
        global_name="alice.athena.pc",
        is_family=False,
        member_local_name=None,
    )
    assert lane_page_path(ref, _OWNER) == "agents/alice.athena.pc/README.md"


def test_family_member_lane_is_its_family_container() -> None:
    ref = lane_ref_for_agent("pc--code", _IDENTITY)

    assert ref == AgentLaneRef(
        local_name="pc",
        global_name="alice.athena.pc",
        is_family=True,
        member_local_name="pc--code",
    )
    assert lane_page_path(ref, _OWNER) == "families/alice.athena.pc.md"


def test_nested_family_member_keeps_its_dotted_family_name() -> None:
    ref = lane_ref_for_agent("foo.bar--code", _IDENTITY)

    assert ref.local_name == "foo.bar"
    assert ref.global_name == "alice.athena.foo.bar"
    assert ref.is_family
    assert lane_page_path(ref, _OWNER) == "families/alice.athena.foo.bar.md"


def test_legacy_machine_qualified_member_normalizes_to_the_bare_lane() -> None:
    ref = lane_ref_for_agent("athena.sase-7r.land--code", _IDENTITY)

    assert ref == AgentLaneRef(
        local_name="sase-7r.land",
        global_name="alice.athena.sase-7r.land",
        is_family=True,
        member_local_name="sase-7r.land--code",
    )


def test_globally_qualified_member_normalizes_to_the_bare_lane() -> None:
    ref = lane_ref_for_agent("alice.athena.pc--code", _IDENTITY)

    assert ref.local_name == "pc"
    assert ref.member_local_name == "pc--code"


def test_lane_name_from_registered_family_container_is_a_family(monkeypatch) -> None:
    monkeypatch.setattr(
        "sase.agent.names.get_reserved_family_names",
        lambda: {"pc"},
    )

    ref = lane_ref_for_lane_name("pc", _IDENTITY)

    assert ref == AgentLaneRef(
        local_name="pc",
        global_name="alice.athena.pc",
        is_family=True,
        member_local_name=None,
    )
    assert lane_page_path(ref, _OWNER) == "families/alice.athena.pc.md"


def test_lane_name_of_a_real_solo_agent_stays_solo(monkeypatch) -> None:
    monkeypatch.setattr(
        "sase.agent.names.get_reserved_family_names",
        lambda: {"other"},
    )

    ref = lane_ref_for_lane_name("pc", _IDENTITY)

    assert not ref.is_family
    assert lane_page_path(ref, _OWNER) == "agents/alice.athena.pc/README.md"


def test_lane_name_lookup_degrades_to_solo_when_the_registry_fails(
    monkeypatch,
) -> None:
    def _explode() -> set[str]:
        raise RuntimeError("registry unreadable")

    monkeypatch.setattr("sase.agent.names.get_reserved_family_names", _explode)

    assert not lane_ref_for_lane_name("pc", _IDENTITY).is_family


def test_lane_name_lookup_accepts_a_member_spelling(monkeypatch) -> None:
    monkeypatch.setattr("sase.agent.names.get_reserved_family_names", lambda: set())

    ref = lane_ref_for_lane_name("pc--code", _IDENTITY)

    assert ref == AgentLaneRef(
        local_name="pc",
        global_name="alice.athena.pc",
        is_family=True,
        member_local_name="pc--code",
    )


def test_legacy_machine_qualified_lane_name_normalizes(monkeypatch) -> None:
    monkeypatch.setattr(
        "sase.agent.names.get_reserved_family_names",
        lambda: {"sase-7r.land"},
    )

    ref = lane_ref_for_lane_name("athena.sase-7r.land", _IDENTITY)

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
def test_lane_name_projects_labels_without_requalifying(
    name: str, expected: str
) -> None:
    assert lane_name(name) == expected
