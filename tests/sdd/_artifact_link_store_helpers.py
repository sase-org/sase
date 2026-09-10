"""Helpers for artifact link store tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.sdd.artifact_link_store import (
    ARTIFACT_LINK_ROW_SCHEMA_VERSION,
    ArtifactLinkStore,
)
from sase.sdd._artifact_link_cutover_state import (
    ArtifactLinkBaselineEventIdentity,
    ArtifactLinkCutoverImportIdentity,
    ArtifactLinkCutoverRole,
    artifact_link_cutover_marker_path,
    build_artifact_link_cutover_marker_payload,
    parse_artifact_link_cutover_marker_payload,
    role_for_artifact_link_kind,
)
from sase.sdd.artifact_link_import_indexes import (
    artifact_link_legacy_links_tree_identity,
)
from tests._conftest_environment import redirect_sase_home


def _row(
    source: str = "plan:202608/a.md",
    relation: str = "implements",
    target: str = "plan:202608/b.md",
    *,
    origin: str = "manual",
    description: str = "extends the ref contract this epic landed",
    created_by: str = "bbugyi200.athena.y2",
    created_at: str = "2026-08-18T23:40:00Z",
    uses: int = 1,
) -> dict[str, object]:
    return {
        "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
        "source_ref": source,
        "relation": relation,
        "target_ref": target,
        "description": description,
        "origin": origin,
        "created_by": created_by,
        "created_at": created_at,
        "uses": uses,
    }


def allow_machine_sidecar_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Treat sidecar roots as machine-writable for background-writer tests."""

    from sase.sdd._artifact_link_authorize import MachineSidecarWritability

    monkeypatch.setattr(
        "sase.workspace_provider.ownership.authorize_store_mutation",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "sase.sdd._artifact_link_authorize.probe_machine_writable_sidecar_root",
        lambda _root: MachineSidecarWritability(writable=True),
    )


def _store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ArtifactLinkStore:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    allow_machine_sidecar_writes(monkeypatch)
    plans = tmp_path / "plans"
    research = tmp_path / "research"
    plans.mkdir()
    research.mkdir()
    return ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={"plan": plans, "research": research},
    )


def _plan_index(tmp_path: Path, stem: str) -> Path:
    return tmp_path / "plans" / "links" / "202608" / f"{stem}.json"


def assert_index_resolves_durable_rows(
    store: ArtifactLinkStore,
    index_rows: list[dict[str, object]] | tuple[dict[str, object], ...],
) -> None:
    """Assert that an index covers every durable store edge by stable key."""

    expected = {_edge_key(row) for row in store.load_durable_rows()}
    indexed = {_edge_key(row) for row in index_rows}
    missing = sorted(expected - indexed)
    assert not missing, f"index missing durable artifact-link rows: {missing!r}"


def write_imported_cutover_marker(store: ArtifactLinkStore) -> None:
    """Write a valid imported cutover marker for every sidecar root."""

    roles = tuple(
        ArtifactLinkCutoverRole(
            role=role_for_artifact_link_kind(kind),
            kind=kind,
            head="0" * 40,
            links_tree=artifact_link_legacy_links_tree_identity(root),
            remote_url="<none>",
        )
        for kind, root in sorted(store.sidecar_roots.items())
    )
    digest = "a" * 64
    payload = build_artifact_link_cutover_marker_payload(
        state="imported",
        project_key=store.project_key,
        event_store_schema_version=1,
        event_store_minimum_event_schema_version=1,
        import_identity=ArtifactLinkCutoverImportIdentity(
            import_id="legacy-v2-links-test",
            operation_id="b" * 32,
            source_head="sha256:" + "c" * 64,
            created_at="2026-09-10T00:00:00Z",
        ),
        roles=roles,
        baseline_event=ArtifactLinkBaselineEventIdentity(
            digest=digest,
            path=f"link-events/v1/{digest[:2]}/{digest}.json",
        ),
    )
    marker_bytes = parse_artifact_link_cutover_marker_payload(payload).canonical_bytes
    for root in store.sidecar_roots.values():
        path = artifact_link_cutover_marker_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(marker_bytes)


def _edge_key(row: dict[str, object]) -> tuple[str, str, str]:
    return (
        str(row.get("source_ref") or ""),
        str(row.get("relation") or ""),
        str(row.get("target_ref") or ""),
    )
