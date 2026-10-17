"""Artifact-link event snapshot coverage cache tests."""

from __future__ import annotations

import pytest

from tests.sdd._artifact_link_event_store_test_helpers import row as make_row


def test_covers_row_caches_edge_identities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.sdd import _artifact_link_event_store as event_store_module
    from sase.sdd._artifact_link_event_store import ArtifactLinkEventSnapshot

    edges = (
        {
            "edge": {
                "kind": "directed",
                "source_ref": "plan:202608/a.md",
                "relation": "implements",
                "target_ref": "plan:202608/b.md",
            }
        },
        {
            "edge": {
                "kind": "undirected",
                "left_ref": "plan:202608/c.md",
                "relation": "related",
                "right_ref": "plan:202608/d.md",
            }
        },
    )
    snapshot = ArtifactLinkEventSnapshot(edges=edges, durable_event_count=1)
    original = event_store_module._event_edge_identities
    calls: list[int] = []

    def _counting(
        edges_arg: object,
    ) -> frozenset[tuple[str, ...]]:
        calls.append(1)
        return original(edges_arg)  # type: ignore[arg-type]

    monkeypatch.setattr(event_store_module, "_event_edge_identities", _counting)
    covered_directed = {
        "source_ref": "plan:202608/a.md",
        "relation": "implements",
        "target_ref": "plan:202608/b.md",
    }
    covered_undirected = {
        "source_ref": "plan:202608/d.md",
        "relation": "related",
        "target_ref": "plan:202608/c.md",
    }
    uncovered = {
        "source_ref": "plan:202608/x.md",
        "relation": "implements",
        "target_ref": "plan:202608/y.md",
    }

    assert snapshot.covers_row(covered_directed) is True
    assert snapshot.covers_row(covered_undirected) is True
    assert snapshot.covers_row(uncovered) is False
    assert snapshot.covers_row(covered_directed) is True
    assert len(calls) == 1

    fresh = ArtifactLinkEventSnapshot(edges=edges, durable_event_count=1)
    assert snapshot == fresh


def test_covers_row_resolves_aliases_with_one_binding_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.sdd import _artifact_link_event_store as event_store_module
    from sase.sdd._artifact_link_event_store import ArtifactLinkEventSnapshot

    aliases = (
        {"old_ref": "plan:202608/a.md", "new_ref": "plan:202608/b.md"},
        {"old_ref": "plan:202608/b.md", "new_ref": "plan:202608/c.md"},
    )
    edges = (
        {
            "edge": {
                "kind": "directed",
                "source_ref": "plan:202608/c.md",
                "relation": "implements",
                "target_ref": "plan:202608/d.md",
            }
        },
    )
    snapshot = ArtifactLinkEventSnapshot(
        aliases=aliases, edges=edges, durable_event_count=1
    )
    real_require = event_store_module.require_rust_binding
    calls: list[int] = []

    def _counting(name: str) -> object:
        if name == "artifact_link_event_resolve_aliases":
            calls.append(1)
        return real_require(name)

    monkeypatch.setattr(event_store_module, "require_rust_binding", _counting)

    two_hop = make_row(source="plan:202608/a.md", target="plan:202608/d.md")
    one_hop = make_row(source="plan:202608/b.md", target="plan:202608/d.md")
    direct = make_row(source="plan:202608/c.md", target="plan:202608/d.md")
    uncovered = make_row(source="plan:202608/x.md", target="plan:202608/d.md")

    assert snapshot.covers_row(two_hop) is True
    assert snapshot.covers_row(one_hop) is True
    assert snapshot.covers_row(direct) is True
    assert snapshot.covers_row(uncovered) is False
    assert snapshot.covers_row(two_hop) is True
    assert snapshot.covers_row(one_hop) is True
    assert len(calls) == 1

    fresh = ArtifactLinkEventSnapshot(
        aliases=aliases, edges=edges, durable_event_count=1
    )
    assert snapshot == fresh


def test_covers_row_caches_alias_resolution_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.sdd import _artifact_link_event_store as event_store_module
    from sase.sdd._artifact_link_event_store import ArtifactLinkEventSnapshot

    aliases = ({"old_ref": "plan:202608/a.md", "new_ref": "plan:202608/b.md"},)
    edges = (
        {
            "edge": {
                "kind": "directed",
                "source_ref": "plan:202608/c.md",
                "relation": "implements",
                "target_ref": "plan:202608/d.md",
            }
        },
    )
    snapshot = ArtifactLinkEventSnapshot(
        aliases=aliases, edges=edges, durable_event_count=1
    )
    real_require = event_store_module.require_rust_binding
    calls: list[int] = []

    def _stub(*args: object, **kwargs: object) -> object:
        calls.append(1)
        raise ValueError("boom")

    def _patching(name: str) -> object:
        if name == "artifact_link_event_resolve_aliases":
            return _stub
        return real_require(name)

    monkeypatch.setattr(event_store_module, "require_rust_binding", _patching)

    aliased = make_row(source="plan:202608/a.md", target="plan:202608/d.md")
    direct = make_row(source="plan:202608/c.md", target="plan:202608/d.md")

    assert snapshot.covers_row(aliased) is False
    assert snapshot.covers_row(aliased) is False
    assert snapshot.covers_row(direct) is True
    assert len(calls) == 1
