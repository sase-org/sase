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
        "normalize_agent_archive_name": "foo",
        "globalize_agent_name": "alice.athena.foo",
        "globalize_legacy_agent_name": "alice.athena.foo",
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
        "agent_relationship_schema_version": 2,
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

    facade.validate_agent_username("alice")
    facade.validate_agent_owner(target)
    assert (
        facade.classify_agent_ownership(source, target)
        is facade.AgentOwnershipClassification.EXACT_OWNER
    )
    assert facade.normalize_agent_archive_name("260722.foo") == "foo"
    assert facade.globalize_agent_name("foo", target) == "alice.athena.foo"
    assert (
        facade.globalize_legacy_agent_name("athena.foo", target) == "alice.athena.foo"
    )
    assert facade.strip_global_agent_name("alice.athena.foo", target) == "foo"
    assert facade.localize_agent_name("alice.athena.foo", source, target) == "foo"
    assert facade.parse_agent_family_name("foo--code").member_role == "code"
    assert facade.agent_local_hood("foo.bar") == "foo"
    assert facade.agent_name_in_hood("foo.bar", "foo")
    assert facade.agent_name_ancestors("foo.bar") == ("foo", "foo.bar")
    assert facade.agent_link_target("foo--code", target).anchor == "member-code"
    assert facade.agent_relationship_schema_version() == 2
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
        "normalize_agent_archive_name",
        "globalize_agent_name",
        "globalize_legacy_agent_name",
        "strip_global_agent_name",
        "localize_agent_name",
        "parse_agent_family_name",
        "agent_local_hood",
        "agent_name_in_hood",
        "agent_name_ancestors",
        "agent_link_target",
        "agent_relationship_schema_version",
        "validate_agent_relationship_batch",
        "rewrite_agent_relationship_batch",
    ]


def test_owner_family_and_localization_integration() -> None:
    target = facade.AgentOwnerIdentity("alice", "athena")
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
        assert facade.localize_agent_name(global_name, source, target) == expected

    assert (
        facade.globalize_agent_name("260722.foo.bar--code", target)
        == "alice.athena.foo.bar--code"
    )
    parsed = facade.parse_agent_family_name("foo.bar--code")
    assert parsed == facade.ParsedAgentFamilyName(
        kind=facade.AgentFamilyNameKind.MEMBER,
        family_name="foo.bar",
        member_role="code",
    )
    assert facade.agent_name_ancestors("foo.bar--code") == ("foo", "foo.bar")
    assert facade.agent_name_in_hood("foo.bar--code", "foo")
    assert not facade.agent_name_in_hood("foobar", "foo")
    assert facade.agent_link_target("foo.bar--code", target).path == (
        "families/alice.athena.foo.bar.md"
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
