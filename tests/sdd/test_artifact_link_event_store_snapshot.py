"""Artifact-link event snapshot coverage cache tests."""

from __future__ import annotations

from pathlib import Path

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


def test_pending_candidates_read_the_outbox_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.sdd import _artifact_link_outbox_io as outbox_io
    from sase.sdd._artifact_link_event_store import ArtifactLinkEventStoreAdapter
    from sase.sdd.artifact_link_outbox import append_artifact_link_outbox_entry
    from tests._conftest_environment import redirect_sase_home

    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    project_key = "gh_sase-org__sase"
    queued = [
        append_artifact_link_outbox_entry(
            project_key=project_key,
            agent_name="reader",
            run_id="run-1",
            row=make_row(target=f"plan:202608/{name}.md"),
            now=created_at,
        )
        for name, created_at in (("kept", 100.0), ("excluded", 50.0))
    ]
    original = outbox_io._read_outbox_records_unlocked
    reads = 0

    def _counting(path: Path, key: str):  # type: ignore[no-untyped-def]
        nonlocal reads
        reads += 1
        return original(path, key)

    monkeypatch.setattr(outbox_io, "_read_outbox_records_unlocked", _counting)
    adapter = ArtifactLinkEventStoreAdapter(project_key, {})

    candidates, stats = adapter._pending_candidates(
        now=130.0,
        exclude_operation_ids=(queued[1].id,),
    )

    assert reads == 1
    assert [candidate.tier for candidate in candidates] == ["pending"]
    assert stats.count == 1
    assert stats.oldest_age_seconds == 30.0
