from __future__ import annotations

import json
from pathlib import Path

from sase.core.agent_artifact_index_lifecycle import _DISMISSED_PROJECTION_META_KEY
from sase.core.agent_scan_wire import AgentArtifactIndexUpdateWire

ProjectionMetaStore = dict[tuple[Path, str], str]


def install_projection_meta_store(
    monkeypatch,
    *,
    corrupt_prefix: bytes | None = None,
) -> ProjectionMetaStore:  # type: ignore[no-untyped-def]
    store: ProjectionMetaStore = {}

    def fake_read(index_path: Path, key: str) -> str | None:
        path = Path(index_path)
        if (
            corrupt_prefix is not None
            and path.exists()
            and path.read_bytes().startswith(corrupt_prefix)
        ):
            raise RuntimeError("file is not a database")
        return store.get((path, key))

    def fake_write(index_path: Path, key: str, value: str) -> None:
        store[(Path(index_path), key)] = value

    monkeypatch.setattr(
        "sase.core.agent_artifact_index_lifecycle.read_agent_artifact_index_meta",
        fake_read,
    )
    monkeypatch.setattr(
        "sase.core.agent_artifact_index_lifecycle.write_agent_artifact_index_meta",
        fake_write,
    )

    def fake_terminalize(
        index_path: Path,
        projects_root: Path,
        *,
        stale_after_seconds: int,
        max_rows: int | None,
        options: object,
    ) -> AgentArtifactIndexUpdateWire:
        del projects_root, stale_after_seconds, max_rows, options
        return AgentArtifactIndexUpdateWire(
            schema_version=1,
            index_path=str(index_path),
            projects_root="",
            rows_indexed=0,
        )

    monkeypatch.setattr(
        "sase.core.agent_artifact_index_lifecycle."
        "terminalize_stale_active_agent_artifact_index_rows",
        fake_terminalize,
    )
    return store


def write_projection_meta(
    store: ProjectionMetaStore,
    index: Path,
    *,
    dismissed_agents_signature: list[int] | None,
    dismissed_bundle_index_signature: list[int] | None,
) -> None:
    payload = {
        "version": 1,
        "dismissed_agents_signature": dismissed_agents_signature,
        "dismissed_bundle_index_signature": dismissed_bundle_index_signature,
        "projected_identity_count": 2,
    }
    store[(index, _DISMISSED_PROJECTION_META_KEY)] = json.dumps(payload)


def read_projection_meta(
    store: ProjectionMetaStore,
    index: Path,
) -> dict[str, object]:
    raw = store.get((index, _DISMISSED_PROJECTION_META_KEY))
    assert raw is not None
    value = json.loads(raw)
    assert isinstance(value, dict)
    return value


def patch_projection_sources(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Pin the dismissed-state source signatures used by the sync path."""
    monkeypatch.setattr(
        "sase.ace.dismissed_agents.dismissed_agents_file_signature",
        lambda: (10, 20),
    )
    monkeypatch.setattr(
        "sase.ace.dismissed_agents.dismissed_bundle_index_signature",
        lambda: (1, 30, 40, 2),
    )
    monkeypatch.setattr(
        "sase.ace.dismissed_agents.verify_dismissed_bundle_index",
        lambda: {"ok": True},
    )
    monkeypatch.setattr(
        "sase.ace.dismissed_agents.load_dismissed_bundle_identities",
        set,
    )


def fake_replace_update(index_path: Path, identities: list[object]) -> object:
    return AgentArtifactIndexUpdateWire(
        schema_version=1,
        index_path=str(index_path),
        projects_root="",
        rows_indexed=len(identities),
    )
