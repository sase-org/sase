"""Coverage for the explicit owner-aware Rust facade."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from sase.core import agent_identity_facade as facade


def _batch() -> dict[str, Any]:
    owner = {"username": "alice", "machine_name": "athena"}
    return {
        "schema_version": 2,
        "owner": owner,
        "runs": [
            {
                "source_run_id": "run-1",
                "global_name": "alice.athena.foo",
                "owner": owner,
            },
            {
                "source_run_id": "run-2",
                "global_name": "alice.athena.foo--code",
                "owner": owner,
            },
        ],
        "containers": [
            {
                "kind": "family",
                "global_name": "alice.athena.foo",
                "owner": owner,
                "member_source_run_ids": ["run-1", "run-2"],
            }
        ],
        "relationships": [
            {
                "kind": "parent",
                "source_run_id": "run-2",
                "target": {
                    "kind": "source_run_id",
                    "source_run_id": "run-1",
                },
                "required": True,
            }
        ],
    }


def test_facade_delegates_every_operation_with_static_binding_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, tuple[Any, ...]]] = []
    owner = {"username": "alice", "machine_name": "athena"}

    results: dict[str, Any] = {
        "classify_agent_ownership": "exact_owner",
        "classify_legacy_v1_group_ownership": "owner_observed",
        "normalize_agent_archive_name": "foo",
        "globalize_agent_name": "alice.athena.foo",
        "strip_global_agent_name": "foo",
        "localize_agent_name": "foo",
        "parse_agent_family_name": {
            "kind": "member",
            "family_name": "foo",
            "member_role": "code",
        },
        "agent_local_hood": "foo",
        "agent_name_in_hood": True,
        "agent_name_ancestors": ["foo", "foo.bar"],
        "agent_link_target": {
            "kind": "family",
            "path": "families/alice.athena.foo.md",
            "anchor": "member-code",
        },
        "validate_agent_relationship_batch": {
            "schema_version": 2,
            "owner": owner,
            "run_count": 2,
            "container_count": 1,
            "relationship_count": 1,
            "run_order": ["run-1", "run-2"],
            "global_name_order": [
                "alice.athena.foo",
                "alice.athena.foo--code",
            ],
            "container_order": ["family:alice.athena.foo"],
            "relationship_order": [0],
        },
        "rewrite_agent_relationship_batch": {
            "schema_version": 2,
            "owner": owner,
            "runs": [{"destination_run_id": "dest-1"}],
            "containers": [],
            "relationships": [],
        },
    }

    def lookup(name: str) -> Callable[..., Any]:
        def invoke(*args: Any) -> Any:
            calls.append((name, args))
            return results.get(name)

        return invoke

    monkeypatch.setattr(facade, "require_rust_binding", lookup)
    target = facade.AgentOwnerIdentity("alice", "athena")
    source = facade.AgentSourceOwnerIdentity.v2(target)
    identity = facade.AgentIdentitySnapshot(target)

    facade.validate_agent_username("alice")
    facade.validate_agent_owner(target)
    assert (
        facade.classify_agent_ownership(source, target)
        is facade.AgentOwnershipClassification.EXACT_OWNER
    )
    assert (
        facade.classify_legacy_v1_group_ownership(
            "athena",
            target,
            facade.LegacyV1GroupOwnershipEvidence(
                v2_hood_published=False,
                proven_entry_count=1,
                total_entry_count=2,
            ),
        )
        is facade.LegacyV1GroupOwnershipClassification.OWNER_OBSERVED
    )
    assert facade.normalize_agent_archive_name("260722.foo") == "foo"
    assert facade.globalize_agent_name("foo", target) == "alice.athena.foo"
    assert facade.normalize_owned_agent_name("alice.athena.foo", identity) == "foo"
    assert (
        facade.localize_imported_agent_name(
            "alice.athena.foo",
            source,
            identity,
        )
        == "foo"
    )
    assert facade.parse_agent_family_name("foo--code").member_role == "code"
    assert facade.agent_local_hood("foo.bar") == "foo"
    assert facade.agent_name_in_hood("foo.bar", "foo")
    assert facade.agent_name_ancestors("foo.bar") == ("foo", "foo.bar")
    assert facade.agent_link_target("foo--code", target).anchor == "member-code"
    assert facade.validate_agent_relationship_batch(_batch()).run_count == 2
    assert (
        facade.rewrite_agent_relationship_batch(
            _batch(), {"run-1": "dest-1", "run-2": "dest-2"}
        ).runs[0]["destination_run_id"]
        == "dest-1"
    )

    assert [name for name, _args in calls] == [
        "validate_agent_username",
        "validate_agent_owner",
        "classify_agent_ownership",
        "classify_legacy_v1_group_ownership",
        "normalize_agent_archive_name",
        "globalize_agent_name",
        "strip_global_agent_name",
        "localize_agent_name",
        "parse_agent_family_name",
        "agent_local_hood",
        "agent_name_in_hood",
        "agent_name_ancestors",
        "agent_link_target",
        "validate_agent_relationship_batch",
        "rewrite_agent_relationship_batch",
    ]


@pytest.mark.parametrize(
    (
        "group_machine_name",
        "v2_hood_published",
        "proven_entry_count",
        "expected",
    ),
    [
        (machine, published, proven, expected)
        for machine, machine_matches in (("athena", True), ("zeus", False))
        for published in (False, True)
        for proven in (0, 1, 3)
        for expected in (
            facade.LegacyV1GroupOwnershipClassification.OWNER_OBSERVED
            if machine_matches and (published or proven > 0)
            else facade.LegacyV1GroupOwnershipClassification.FOREIGN,
        )
    ],
)
def test_legacy_v1_group_ownership_integration_matrix(
    group_machine_name: str,
    v2_hood_published: bool,
    proven_entry_count: int,
    expected: facade.LegacyV1GroupOwnershipClassification,
) -> None:
    assert (
        facade.classify_legacy_v1_group_ownership(
            group_machine_name,
            facade.AgentOwnerIdentity("alice", "athena"),
            facade.LegacyV1GroupOwnershipEvidence(
                v2_hood_published=v2_hood_published,
                proven_entry_count=proven_entry_count,
                total_entry_count=3,
            ),
        )
        is expected
    )


def test_legacy_v1_group_ownership_rejects_impossible_evidence() -> None:
    with pytest.raises(ValueError, match="proven entry count 2 exceeds total"):
        facade.classify_legacy_v1_group_ownership(
            "athena",
            facade.AgentOwnerIdentity("alice", "athena"),
            facade.LegacyV1GroupOwnershipEvidence(
                v2_hood_published=False,
                proven_entry_count=2,
                total_entry_count=1,
            ),
        )


def test_owner_family_and_localization_integration() -> None:
    target = facade.AgentOwnerIdentity("alice", "athena")
    identity = facade.AgentIdentitySnapshot(target)
    cases = [
        (
            facade.AgentSourceOwnerIdentity.v2(target),
            "alice.athena.foo",
            "foo",
        ),
        (
            facade.AgentSourceOwnerIdentity("zeus", "alice"),
            "alice.zeus.foo",
            "zeus.foo",
        ),
        (
            facade.AgentSourceOwnerIdentity("athena", "bob"),
            "bob.athena.foo",
            "bob.athena.foo",
        ),
        (
            facade.AgentSourceOwnerIdentity.username_unknown_v1("zeus"),
            "zeus.foo",
            "zeus.foo",
        ),
    ]
    for source, global_name, expected in cases:
        assert (
            facade.localize_imported_agent_name(global_name, source, identity)
            == expected
        )

    assert (
        facade.globalize_agent_name("260722.foo.bar--code", target)
        == "alice.athena.foo.bar--code"
    )
    parsed = facade.parse_agent_family_name("foo.bar--code")
    assert (
        parsed.kind,
        parsed.family_name,
        parsed.member_role,
    ) == (
        facade.AgentFamilyNameKind.MEMBER,
        "foo.bar",
        "code",
    )
    assert facade.agent_name_ancestors("foo.bar--code") == ("foo", "foo.bar")
    assert facade.agent_name_in_hood("foo.bar--code", "foo")
    assert not facade.agent_name_in_hood("foobar", "foo")
    assert facade.agent_link_target("foo.bar--code", target).path == (
        "families/alice.athena.foo.bar.md"
    )


def test_application_identity_policy_keeps_local_storage_bare() -> None:
    identity = facade.AgentIdentitySnapshot(
        facade.AgentOwnerIdentity("alice", "athena"),
        ("athena", "zeus"),
    )

    for spelling in ("foo", "athena.foo", "alice.athena.foo"):
        assert facade.normalize_owned_agent_name(spelling, identity) == "foo"
        assert facade.present_agent_name(spelling, identity) == "foo"
        assert facade.current_owner_agent_name_key(spelling, identity) == "foo"

    assert facade.current_owner_agent_name_lookup_candidates("foo", identity) == (
        "foo",
        "athena.foo",
        "alice.athena.foo",
    )
    assert facade.current_owner_agent_name_lookup_candidates(
        "athena.foo", identity
    ) == ("athena.foo", "foo", "alice.athena.foo")
    assert (
        facade.globalize_owned_agent_name("athena.foo", identity) == "alice.athena.foo"
    )


def test_application_identity_policy_preserves_explicit_foreign_hoods() -> None:
    identity = facade.AgentIdentitySnapshot(
        facade.AgentOwnerIdentity("alice", "athena"),
        ("athena", "zeus"),
    )

    assert facade.foreign_agent_owner_root("zeus.foo", identity) == "zeus"
    assert facade.foreign_agent_owner_root("alice.zeus.foo", identity) == "alice.zeus"
    assert facade.foreign_agent_owner_root("bob.athena.foo", identity) == "bob.athena"
    assert facade.present_agent_name("zeus.foo", identity) == "zeus.foo"
    assert facade.present_agent_name("bob.athena.foo", identity) == ("bob.athena.foo")
    assert facade.current_owner_agent_name_lookup_candidates("zeus.foo", identity) == (
        "zeus.foo",
    )


def test_relationship_validation_and_rewrite_integration() -> None:
    summary = facade.validate_agent_relationship_batch(_batch())
    assert summary.schema_version == 2
    assert summary.run_order == ("run-1", "run-2")

    rewritten = facade.rewrite_agent_relationship_batch(
        _batch(),
        {"run-1": "dest-1", "run-2": "dest-2"},
    )
    assert rewritten.runs[0]["source_run_id"] == "run-1"
    assert rewritten.runs[0]["destination_run_id"] == "dest-1"
    assert rewritten.relationships[0]["source_destination_run_id"] == "dest-2"
    assert rewritten.relationships[0]["target"]["destination_run_id"] == "dest-1"

    malformed = _batch()
    malformed["owner"] = {"username": "Alice", "machine_name": "athena"}
    with pytest.raises(ValueError, match="invalid username"):
        facade.validate_agent_relationship_batch(malformed)

    with pytest.raises(ValueError, match="missing source run ID 'run-2'"):
        facade.rewrite_agent_relationship_batch(
            _batch(),
            {"run-1": "dest-1"},
        )
