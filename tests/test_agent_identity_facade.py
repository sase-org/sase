"""Coverage for the explicit owner-aware Rust facade."""

from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
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
        "validate_owned_agent_name": None,
        "classify_agent_ownership": "exact_owner",
        "normalize_agent_archive_name": "foo",
        "globalize_agent_name": "alice.athena.foo",
        "normalize_owned_agent_name": "foo",
        "globalize_owned_agent_name": "alice.athena.foo",
        "foreign_agent_owner_root": None,
        "localize_agent_name": "foo",
        "parse_owned_agent_name": {
            "owner_root": None,
            "local_name": "foo--code",
            "hood": "foo",
            "family_name": "foo",
            "member_role": "code",
        },
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
    }

    def lookup(name: str) -> Callable[..., Any]:
        def invoke(*args: Any) -> Any:
            calls.append((name, args))
            return results.get(name)

        return invoke

    monkeypatch.setattr(facade, "require_rust_binding", lookup)
    target = facade.AgentOwnerIdentity("alice", "athena")
    source = facade.AgentSourceOwnerIdentity.v2(target)
    identity = facade.AgentIdentitySnapshot(target, (), ("athena", "alice.athena"))

    facade.validate_agent_username("alice")
    facade.validate_agent_owner(target)
    facade.validate_new_agent_name("foo", identity)
    assert (
        facade.classify_imported_agent_owner(source, identity)
        is facade.AgentOwnershipClassification.EXACT_OWNER
    )
    assert facade.normalize_agent_archive_name("260722.foo") == "foo"
    assert facade.globalize_agent_name("foo", target) == "alice.athena.foo"
    assert facade.normalize_owned_agent_name("alice.athena.foo", identity) == "foo"
    assert facade.globalize_owned_agent_name("foo", identity) == "alice.athena.foo"
    assert (
        facade.localize_imported_agent_name(
            "alice.athena.foo",
            source,
            identity,
        )
        == "foo"
    )
    assert facade.parse_agent_family_name("foo--code", identity).member_role == "code"
    assert facade.agent_local_hood("foo.bar", identity) == "foo"
    assert facade.agent_name_in_hood("foo.bar", "foo", identity)
    assert facade.agent_name_ancestors("foo.bar", identity) == ("foo", "foo.bar")
    assert facade.agent_link_target("foo--code", target, identity).anchor == (
        "member-code"
    )
    assert facade.validate_agent_relationship_batch(_batch()).run_count == 2

    assert [name for name, _args in calls] == [
        "validate_agent_username",
        "validate_agent_owner",
        "validate_owned_agent_name",
        "classify_agent_ownership",
        "normalize_agent_archive_name",
        "globalize_agent_name",
        "normalize_owned_agent_name",
        "globalize_owned_agent_name",
        "localize_agent_name",
        "parse_owned_agent_name",
        "agent_local_hood",
        "agent_name_in_hood",
        "agent_name_ancestors",
        "agent_link_target",
        "validate_agent_relationship_batch",
    ]


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
    parsed = facade.parse_agent_family_name("foo.bar--code", identity)
    assert (
        parsed.kind,
        parsed.family_name,
        parsed.member_role,
    ) == (
        facade.AgentFamilyNameKind.MEMBER,
        "foo.bar",
        "code",
    )
    assert facade.agent_name_ancestors("foo.bar--code", identity) == (
        "foo",
        "foo.bar",
    )
    assert facade.agent_name_in_hood("foo.bar--code", "foo", identity)
    assert not facade.agent_name_in_hood("foobar", "foo", identity)
    assert facade.agent_link_target("foo.bar--code", target, identity).path == (
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


def test_owned_name_helpers_are_total_on_empty_input() -> None:
    identity = facade.AgentIdentitySnapshot(
        facade.AgentOwnerIdentity("alice", "athena"),
        ("athena",),
    )

    assert facade.foreign_agent_owner_root("", identity) is None
    assert facade.normalize_owned_agent_name("", identity) == ""
    assert facade.current_owner_agent_name_key("", identity) == ""


def test_application_identity_policy_preserves_explicit_foreign_hoods() -> None:
    identity = facade.AgentIdentitySnapshot(
        facade.AgentOwnerIdentity("alice", "athena"),
        ("athena", "zeus"),
        ("athena", "zeus", "alice.zeus", "bob.athena"),
    )

    assert facade.foreign_agent_owner_root("zeus.foo", identity) == "zeus"
    assert facade.foreign_agent_owner_root("alice.zeus.foo", identity) == "alice.zeus"
    assert facade.foreign_agent_owner_root("bob.athena.foo", identity) == "bob.athena"
    assert facade.present_agent_name("zeus.foo", identity) == "zeus.foo"
    assert facade.present_agent_name("bob.athena.foo", identity) == ("bob.athena.foo")
    assert facade.current_owner_agent_name_lookup_candidates("zeus.foo", identity) == (
        "zeus.foo",
    )


def test_owner_roots_parse_topology_without_becoming_local_owner() -> None:
    identity = facade.AgentIdentitySnapshot(
        facade.AgentOwnerIdentity("alice", "hera"),
        (),
        ("athena",),
    )

    parsed = facade._parse_owned_agent_name("athena.7n--code", identity)

    assert parsed.owner_root == "athena"
    assert parsed.hood == "7n"
    assert parsed.family_name == "7n"
    assert parsed.member_role == "code"
    assert facade.agent_local_hood("athena.7n--code", identity) == "7n"
    assert facade.foreign_agent_owner_root("athena.7n--code", identity) == "athena"
    with pytest.raises(ValueError, match="foreign owner root"):
        facade.globalize_owned_agent_name("athena.7n--code", identity)
    with pytest.raises(ValueError, match="foreign owner root"):
        facade.validate_new_agent_name("athena.7n--code", identity)
    assert parsed.local_name == "7n--code"
    assert facade.present_imported_agent_name("athena.7n--code", identity) == (
        "7n--code"
    )


def test_imported_owner_badge_label_distinguishes_machine_and_user() -> None:
    dest = facade.AgentOwnerIdentity("alice", "athena")
    same_user = facade.AgentOwnerIdentity("alice", "zeus")
    other_user = facade.AgentOwnerIdentity("bob", "zeus")

    assert facade.imported_owner_badge_label(same_user, dest) == "zeus"
    assert facade.imported_owner_badge_label(other_user, dest) == "bob@zeus"
    assert (
        facade.imported_source_owner_from_mapping(
            {"username": "bob", "machine_name": "zeus"}
        )
        == other_user
    )
    assert facade.imported_source_owner_from_mapping("bob.zeus") is None


def test_known_owner_roots_include_raw_registry_namespaces(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    registry = tmp_path / "agent_name_registry.json"
    registry.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "entries": {
                    "zeus": {
                        "container_kind": "owner_namespace",
                        "source_owner": {
                            "username": "alice",
                            "machine_name": "zeus",
                        },
                    },
                    "bob.athena": {
                        "container_kind": "owner_namespace",
                        "source_owner": {
                            "username": "bob",
                            "machine_name": "athena",
                        },
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    roots = facade._registry_owner_roots(facade.AgentOwnerIdentity("alice", "athena"))

    assert {"zeus", "alice.zeus", "bob.athena"} <= set(roots)


def test_known_owner_roots_include_configured_sidecar_owner_directories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sidecar = tmp_path / "agents"
    same_user = sidecar / "users/alice/machines/zeus"
    other_user = sidecar / "users/bob/machines/athena"
    same_user.mkdir(parents=True)
    other_user.mkdir(parents=True)
    other_user.joinpath("manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "owner": {"username": "carol", "machine_name": "hera"},
                "project": {"key": "proj", "name": "Project"},
                "hoods": {},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        facade,
        "_configured_agents_sidecar_paths",
        lambda: (sidecar,),
    )

    roots = facade._agents_sidecar_owner_roots(
        facade.AgentOwnerIdentity("alice", "athena")
    )

    assert {"zeus", "alice.zeus", "bob.athena", "carol.hera"} <= set(roots)


def test_current_snapshot_known_owner_roots_are_deduplicated_union(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    facade._discover_known_owner_roots.cache_clear()
    facade._configured_agents_sidecar_paths.cache_clear()
    owner = facade.AgentOwnerIdentity("alice", "athena")
    import sase.config

    monkeypatch.setattr(sase.config, "get_agent_owner_identity", lambda: owner)
    monkeypatch.setattr(sase.config, "discover_machine_names", lambda: ("zeus",))
    monkeypatch.setattr(
        facade,
        "_registry_owner_roots",
        lambda _owner: ("bob.athena", "zeus"),
    )
    monkeypatch.setattr(
        facade,
        "_agents_sidecar_owner_roots",
        lambda _owner: ("bob.athena", "carol.hera"),
    )

    snapshot = facade.AgentIdentitySnapshot.current()

    assert snapshot.owner == owner
    assert snapshot.sibling_machines == ("zeus", "athena")
    assert snapshot.known_owner_roots == (
        "alice.athena",
        "bob.athena",
        "carol.hera",
        "athena",
        "zeus",
    )


def test_relationship_validation_integration() -> None:
    summary = facade.validate_agent_relationship_batch(_batch())
    assert summary.schema_version == 2
    assert summary.run_order == ("run-1", "run-2")

    malformed = _batch()
    malformed["owner"] = {"username": "Alice", "machine_name": "athena"}
    with pytest.raises(ValueError, match="invalid username"):
        facade.validate_agent_relationship_batch(malformed)
