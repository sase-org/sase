"""Caller-supplied artifact-reference context models."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sase.artifact_ref_wire import ARTIFACT_REF_CONTEXT_WIRE_SCHEMA_VERSION
from sase.core.time import get_timezone, local_now


@dataclass(frozen=True, slots=True)
class ArtifactRefDocumentRoot:
    kind: str
    root: Path
    path_globs: tuple[str, ...] | None = None

    def to_wire(self) -> dict[str, object]:
        raw: dict[str, object] = {"kind": self.kind, "root": str(self.root)}
        if self.path_globs is not None:
            raw["path_globs"] = list(self.path_globs)
        return raw


@dataclass(frozen=True, slots=True)
class ArtifactRefFileRoot:
    name: str
    root: Path
    path_globs: tuple[str, ...] | None = None

    def to_wire(self) -> dict[str, object]:
        raw: dict[str, object] = {"name": self.name, "path": str(self.root)}
        if self.path_globs is not None:
            raw["path_globs"] = list(self.path_globs)
        return raw


@dataclass(frozen=True, slots=True)
class ArtifactRefRepository:
    name: str
    aliases: tuple[str, ...] = ()
    shas: tuple[str, ...] = ()
    checkout_path: Path | None = None
    checkout_paths: tuple[Path, ...] = ()
    kind: str = ""

    def to_wire(self) -> dict[str, object]:
        return {
            "name": self.name,
            "aliases": list(self.aliases),
            "shas": list(self.shas),
            "checkout_paths": [str(path) for path in self.checkout_paths],
            "kind": self.kind,
        }


@dataclass(frozen=True, slots=True)
class ArtifactRefProject:
    name: str
    key: str
    aliases: tuple[str, ...] = ()

    def to_wire(self) -> dict[str, object]:
        return {
            "name": self.name,
            "key": self.key,
            "aliases": list(self.aliases),
        }


@dataclass(frozen=True, slots=True)
class ArtifactRefBeadStore:
    project: str
    prefix: str
    root: Path

    def to_wire(self) -> dict[str, str]:
        return {
            "project": self.project,
            "prefix": self.prefix,
            "root": str(self.root),
        }


@dataclass(frozen=True, slots=True)
class ArtifactRefAgentRoot:
    project: str
    root: Path

    def to_wire(self) -> dict[str, str]:
        return {"project": self.project, "root": str(self.root)}


@dataclass(frozen=True, slots=True)
class ArtifactRefAgentOwner:
    username: str
    machine_name: str

    def to_wire(self) -> dict[str, str]:
        return {
            "username": self.username,
            "machine_name": self.machine_name,
        }


@dataclass(frozen=True, slots=True)
class ArtifactRefDocumentExpansion:
    """One document kind's Python-owned expansion-format policy.

    Carried on :class:`ArtifactRefContext` for Python-side rendering only;
    never sent across the Rust wire (see ``ArtifactRefContext.to_wire``).
    """

    kind: str
    role: str
    expansion_format: str
    is_pointer: bool


def _utc_offset_seconds() -> int:
    """Return the configured timezone's current UTC offset in whole seconds."""

    offset = get_timezone().utcoffset(local_now())
    return 0 if offset is None else int(offset.total_seconds())


@dataclass(frozen=True, slots=True)
class ArtifactRefContext:
    """Caller-supplied local namespaces used by the Rust resolver."""

    document_roots: tuple[ArtifactRefDocumentRoot, ...]
    chats_root: Path
    artifact_index_path: Path
    repositories: tuple[ArtifactRefRepository, ...]
    projects: tuple[ArtifactRefProject, ...]
    file_roots: tuple[ArtifactRefFileRoot, ...] = ()
    bead_stores: tuple[ArtifactRefBeadStore, ...] = ()
    agent_roots: tuple[ArtifactRefAgentRoot, ...] = ()
    agent_owner: ArtifactRefAgentOwner | None = None
    home_dir: Path | None = None
    file_capture_max_bytes: int | None = None
    selected_project: str | None = None
    document_expansions: tuple[ArtifactRefDocumentExpansion, ...] = ()

    @property
    def known_kinds(self) -> tuple[str, ...]:
        # Lazy import: artifact_ref_kinds imports ArtifactRef from the public facade.
        from sase.artifact_ref_kinds import parsable_artifact_ref_kinds

        return tuple(
            dict.fromkeys(
                (
                    *parsable_artifact_ref_kinds(),
                    *(entry.kind for entry in self.document_roots),
                )
            )
        )

    def document_expansion_for(self, kind: str) -> ArtifactRefDocumentExpansion | None:
        return next(
            (entry for entry in self.document_expansions if entry.kind == kind),
            None,
        )

    def document_is_pointer(self, kind: str) -> bool:
        """Return whether *kind* expands as a pointer rather than a local path.

        Unconfigured document kinds use the default sidecar pointer format, so
        a missing expansion policy is a pointer rather than a path-bound
        fallback.
        """

        expansion = self.document_expansion_for(kind)
        if expansion is None:
            return True
        return expansion.is_pointer

    def to_wire(self) -> dict[str, object]:
        return {
            "schema_version": ARTIFACT_REF_CONTEXT_WIRE_SCHEMA_VERSION,
            "document_roots": [document.to_wire() for document in self.document_roots],
            "file_roots": [root.to_wire() for root in self.file_roots],
            "chats_root": str(self.chats_root),
            "artifact_index_path": str(self.artifact_index_path),
            "repositories": [repository.to_wire() for repository in self.repositories],
            "projects": [project.to_wire() for project in self.projects],
            "bead_stores": [store.to_wire() for store in self.bead_stores],
            "agent_roots": [root.to_wire() for root in self.agent_roots],
            "agent_owner": (
                None if self.agent_owner is None else self.agent_owner.to_wire()
            ),
            "home_dir": None if self.home_dir is None else str(self.home_dir),
            "file_capture_max_bytes": self.file_capture_max_bytes,
            "utc_offset_seconds": _utc_offset_seconds(),
            "selected_project": self.selected_project,
        }


__all__ = [
    "ArtifactRefAgentOwner",
    "ArtifactRefAgentRoot",
    "ArtifactRefBeadStore",
    "ArtifactRefContext",
    "ArtifactRefDocumentExpansion",
    "ArtifactRefDocumentRoot",
    "ArtifactRefFileRoot",
    "ArtifactRefProject",
    "ArtifactRefRepository",
]
