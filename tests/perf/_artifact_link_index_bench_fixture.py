"""Sanitized fixture IO, identity pinning, and snapshot reconstruction."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sase.ace.patch import Patch
from sase.ace.tui.artifact_tabs import reset_artifacts_subtabs_cache
from sase.ace.tui.relations.artifact_links import ArtifactLinksSnapshot
from sase.core.agent_identity_facade import AgentIdentitySnapshot, AgentOwnerIdentity

_REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = _REPO_ROOT / "tests" / "ace" / "tui" / "fixtures" / "artifact_link_parity"
FIXTURE_INPUT_PATH = FIXTURE_DIR / "input.json"
FIXTURE_CHIPS_PATH = FIXTURE_DIR / "expected_chips.json"
FIXTURE_PATCH_INDEX_PATH = FIXTURE_DIR / "expected_patch_index.json"
SYNTHETIC_SCALE_ROWS = 45_000

__all__ = [
    "FIXTURE_CHIPS_PATH",
    "FIXTURE_DIR",
    "FIXTURE_INPUT_PATH",
    "FIXTURE_PATCH_INDEX_PATH",
    "SYNTHETIC_SCALE_ROWS",
    "build_synthetic_scale_rows",
    "fixture_patches",
    "fixture_snapshot",
    "identity_from_payload",
    "identity_payload",
    "load_fixture_input",
    "load_saved_aggregate",
    "patches_from_payload",
    "pinned_identity",
    "snapshot_from_rows",
    "snapshot_from_saved_aggregate",
    "source_key_from_payload",
]


def source_key_from_payload(value: Any) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        return (value,)
    return tuple(tuple(item) if isinstance(item, list) else item for item in value)


def load_fixture_input(path: Path | None = None) -> dict[str, Any]:
    target = path or FIXTURE_INPUT_PATH
    return json.loads(target.read_text(encoding="utf-8"))


def identity_from_payload(payload: Mapping[str, Any]) -> AgentIdentitySnapshot:
    identity = payload.get("identity") or {}
    username = str(identity.get("username") or "alice")
    machine = str(identity.get("machine_name") or "athena")
    siblings = tuple(identity.get("sibling_machines") or (machine,))
    roots = tuple(identity.get("known_owner_roots") or ())
    return AgentIdentitySnapshot(
        AgentOwnerIdentity(username, machine),
        siblings,
        roots,
    )


def identity_payload(identity: AgentIdentitySnapshot) -> dict[str, Any]:
    owner = identity.owner
    return {
        "known_owner_roots": list(identity.known_owner_roots),
        "machine_name": None if owner is None else owner.machine_name,
        "sibling_machines": list(identity.sibling_machines),
        "username": None if owner is None else owner.username,
    }


@contextmanager
def pinned_identity(identity: AgentIdentitySnapshot) -> Iterator[None]:
    """Force identity and pane-descriptor style for deterministic chips.

    Unknown document kinds (`ref:research`, ...) otherwise hash a live
    provider palette. The fixture pins them to the no-descriptor fallback
    (external accent/icon) so tests, golden capture, and later phases agree.
    """

    from sase.ace.tui import artifact_tabs

    original = AgentIdentitySnapshot.current
    original_descriptor = artifact_tabs.descriptor_for_artifacts_pane_id

    @classmethod  # type: ignore[misc]
    def _current(_cls: type[AgentIdentitySnapshot]) -> AgentIdentitySnapshot:
        return identity

    def _no_descriptor(_pane_id: str) -> None:
        return None

    AgentIdentitySnapshot.current = _current  # type: ignore[method-assign]
    artifact_tabs.descriptor_for_artifacts_pane_id = _no_descriptor
    try:
        reset_artifacts_subtabs_cache()
        yield
    finally:
        AgentIdentitySnapshot.current = original  # type: ignore[method-assign]
        artifact_tabs.descriptor_for_artifacts_pane_id = original_descriptor
        reset_artifacts_subtabs_cache()


def patches_from_payload(items: Sequence[Mapping[str, Any]]) -> list[Patch]:
    return [
        Patch(
            name=str(item["name"]),
            description=str(item.get("description") or "d"),
            parent=item.get("parent"),
            status=str(item.get("status") or "Ready"),
            file_path=str(item["file_path"]),
            line_number=int(item.get("line_number") or 1),
        )
        for item in items
    ]


def snapshot_from_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    source_key: tuple[object, ...] = ("artifact-link-parity",),
    errors: tuple[str, ...] = (),
) -> ArtifactLinksSnapshot:
    return ArtifactLinksSnapshot(
        rows=tuple(dict(row) for row in rows),
        source_key=source_key,
        errors=errors,
    )


def snapshot_from_saved_aggregate(payload: Mapping[str, Any]) -> ArtifactLinksSnapshot:
    """Rebuild a snapshot from a durable capture (not a live sidecar read)."""

    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise ValueError("saved aggregate rows must be a list")
    return snapshot_from_rows(
        rows,
        source_key=source_key_from_payload(payload.get("source_key") or ()),
        errors=tuple(payload.get("errors") or ()),
    )


def load_saved_aggregate(path: Path) -> ArtifactLinksSnapshot:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"saved aggregate is not an object: {path}")
    return snapshot_from_saved_aggregate(payload)


def fixture_snapshot(payload: Mapping[str, Any] | None = None) -> ArtifactLinksSnapshot:
    data = payload if payload is not None else load_fixture_input()
    return snapshot_from_rows(
        data["rows"],
        source_key=source_key_from_payload(
            data.get("source_key") or ["artifact-link-parity"]
        ),
    )


def fixture_patches(payload: Mapping[str, Any] | None = None) -> list[Patch]:
    data = payload if payload is not None else load_fixture_input()
    return patches_from_payload(data.get("patches") or ())


def build_synthetic_scale_rows(
    n: int = SYNTHETIC_SCALE_ROWS,
) -> tuple[dict[str, Any], ...]:
    """Representative synthetic aggregate when no nonempty real file exists."""

    rows: list[dict[str, Any]] = []
    relations = ("related", "cites", "implements", "read", "derives-from")
    for index in range(n):
        relation = relations[index % len(relations)]
        rows.append(
            {
                "_project": "alpha" if index % 2 == 0 else "beta",
                "created_at": "2026-01-01T00:00:00Z",
                "created_by": "synthetic",
                "description": "",
                "origin": "manual" if index % 11 else "projected",
                "relation": relation,
                "source_ref": f"bead:sase-syn-{index % 500}",
                "target_ref": f"plan:202608/syn-{index}.md",
                "uses": index % 7,
            }
        )
    return tuple(rows)
