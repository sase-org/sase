"""Data models for planning agent sidecar publication."""

from __future__ import annotations

from dataclasses import dataclass

from sase.agents_sync.v2_models import (
    V2CompatibilityAlias,
    V2PublicationCounts,
)


@dataclass(frozen=True, slots=True)
class V2SidecarWrite:
    path: str
    preimage_sha256: str | None
    postimage_sha256: str
    postimage_bytes: bytes

    def to_json_dict(self, *, include_bytes: bool = False) -> dict[str, object]:
        payload: dict[str, object] = {
            "path": self.path,
            "preimage_sha256": self.preimage_sha256,
            "postimage_sha256": self.postimage_sha256,
            "size_bytes": len(self.postimage_bytes),
        }
        if include_bytes:
            import base64

            payload["postimage_base64"] = base64.b64encode(self.postimage_bytes).decode(
                "ascii"
            )
        return payload


@dataclass(frozen=True, slots=True)
class V2SidecarDelete:
    path: str
    preimage_sha256: str

    def to_json_dict(self) -> dict[str, str]:
        return {"path": self.path, "preimage_sha256": self.preimage_sha256}


@dataclass(frozen=True, slots=True)
class V2SidecarRegenerationPlan:
    writes: tuple[V2SidecarWrite, ...]
    deletes: tuple[V2SidecarDelete, ...]
    compatibility_aliases: tuple[V2CompatibilityAlias, ...]
    counts: V2PublicationCounts

    @property
    def payload(self) -> dict[str, bytes]:
        return {write.path: write.postimage_bytes for write in self.writes}

    @property
    def delete_paths(self) -> tuple[str, ...]:
        return tuple(delete.path for delete in self.deletes)

    @property
    def changed(self) -> bool:
        return bool(self.writes or self.deletes)

    def to_json_dict(self, *, include_bytes: bool = False) -> dict[str, object]:
        return {
            "changed": self.changed,
            "writes": [
                write.to_json_dict(include_bytes=include_bytes) for write in self.writes
            ],
            "deletes": [delete.to_json_dict() for delete in self.deletes],
            "compatibility_aliases": [
                alias.to_json_dict() for alias in self.compatibility_aliases
            ],
            "counts": {
                "hoods_published": self.counts.hoods_published,
                "hoods_refreshed": self.counts.hoods_refreshed,
                "hoods_unchanged": self.counts.hoods_unchanged,
                "families_published": self.counts.families_published,
                "runs_published": self.counts.runs_published,
                "diagnostics": list(self.counts.diagnostics),
                "schema_version": self.counts.schema_version,
            },
        }


__all__ = [
    "V2SidecarDelete",
    "V2SidecarRegenerationPlan",
    "V2SidecarWrite",
]
