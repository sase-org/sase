"""Preview and apply historical bead-derived agent identity migrations."""

from __future__ import annotations

import base64
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sase.core.agent_identity_facade import AgentIdentitySnapshot, AgentOwnerIdentity


FileActionKind = Literal["write", "rename", "delete"]


class AgentIdentityMigrationError(ValueError):
    """Raised when a historical agent identity migration cannot be applied."""


@dataclass(frozen=True, slots=True)
class AgentIdentityMigrationRequest:
    """Explicit roots and authoritative bead-ID map for one migration preview."""

    bead_id_map: Mapping[str, str]
    state_root: str | Path
    projects_root: str | Path | None = None
    identity: AgentIdentitySnapshot | None = None
    include_chats: bool = True

    @property
    def state_path(self) -> Path:
        return Path(self.state_root).expanduser()

    @property
    def projects_path(self) -> Path:
        if self.projects_root is not None:
            return Path(self.projects_root).expanduser()
        return self.state_path / "projects"

    def normalized_bead_map(self) -> dict[str, str]:
        return {str(old): str(new) for old, new in sorted(self.bead_id_map.items())}

    def to_json_dict(self) -> dict[str, object]:
        owner = _owner_dict(self.identity.owner) if self.identity else None
        return {
            "bead_id_map": self.normalized_bead_map(),
            "state_root": str(self.state_path),
            "projects_root": str(self.projects_path),
            "identity_owner": owner,
            "include_chats": self.include_chats,
        }


@dataclass(frozen=True, slots=True)
class AgentIdentityMigrationFileAction:
    """One digest-addressed local file mutation planned by a preview."""

    kind: FileActionKind
    source_path: str
    destination_path: str | None
    preimage_sha256: str | None
    postimage_sha256: str | None
    replacement_counts: tuple[tuple[str, int], ...] = ()
    postimage_bytes: bytes | None = None

    @property
    def path(self) -> str:
        return self.destination_path or self.source_path

    def to_json_dict(self, *, include_bytes: bool = False) -> dict[str, object]:
        payload: dict[str, object] = {
            "kind": self.kind,
            "source_path": self.source_path,
            "destination_path": self.destination_path,
            "preimage_sha256": self.preimage_sha256,
            "postimage_sha256": self.postimage_sha256,
            "replacement_counts": dict(self.replacement_counts),
        }
        if include_bytes and self.postimage_bytes is not None:
            payload["postimage_base64"] = base64.b64encode(self.postimage_bytes).decode(
                "ascii"
            )
        return payload


@dataclass(frozen=True, slots=True)
class AgentIdentityMigrationBlocker:
    """A deterministic reason the preview must not be applied."""

    code: str
    message: str
    path: str | None = None

    def to_json_dict(self) -> dict[str, object]:
        return {"code": self.code, "message": self.message, "path": self.path}


@dataclass(frozen=True, slots=True)
class AgentIdentityMigrationSkip:
    """A deterministic audit skip for a scanned but unsupported input."""

    code: str
    message: str
    path: str | None = None

    def to_json_dict(self) -> dict[str, object]:
        return {"code": self.code, "message": self.message, "path": self.path}


@dataclass(frozen=True, slots=True)
class AgentIdentityMigrationPreview:
    """Pure preview result for local historical agent identity migration."""

    request: AgentIdentityMigrationRequest
    bead_id_map: tuple[tuple[str, str], ...]
    local_name_map: tuple[tuple[str, str], ...] = ()
    global_name_map: tuple[tuple[str, str], ...] = ()
    chat_path_map: tuple[tuple[str, str], ...] = ()
    actions: tuple[AgentIdentityMigrationFileAction, ...] = ()
    blockers: tuple[AgentIdentityMigrationBlocker, ...] = ()
    skips: tuple[AgentIdentityMigrationSkip, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.blockers

    @property
    def changed(self) -> bool:
        return bool(self.actions)

    def to_json_dict(self, *, include_bytes: bool = False) -> dict[str, object]:
        return {
            "request": self.request.to_json_dict(),
            "ok": self.ok,
            "changed": self.changed,
            "bead_id_map": dict(self.bead_id_map),
            "local_name_map": dict(self.local_name_map),
            "global_name_map": dict(self.global_name_map),
            "chat_path_map": dict(self.chat_path_map),
            "actions": [
                action.to_json_dict(include_bytes=include_bytes)
                for action in self.actions
            ],
            "blockers": [blocker.to_json_dict() for blocker in self.blockers],
            "skips": [skip.to_json_dict() for skip in self.skips],
        }


@dataclass(frozen=True, slots=True)
class AgentIdentityMigrationApplyResult:
    """Outcome of applying one successful preview."""

    preview: AgentIdentityMigrationPreview
    applied_actions: tuple[AgentIdentityMigrationFileAction, ...]
    post_apply_preview: AgentIdentityMigrationPreview

    @property
    def changed(self) -> bool:
        return bool(self.applied_actions)

    @property
    def idempotent(self) -> bool:
        return (
            not self.post_apply_preview.actions and not self.post_apply_preview.blockers
        )

    def to_json_dict(self, *, include_bytes: bool = False) -> dict[str, object]:
        return {
            "changed": self.changed,
            "idempotent": self.idempotent,
            "applied_actions": [
                action.to_json_dict(include_bytes=include_bytes)
                for action in self.applied_actions
            ],
            "post_apply_preview": self.post_apply_preview.to_json_dict(
                include_bytes=include_bytes
            ),
        }


def preview_historical_agent_identity_migration(
    request: AgentIdentityMigrationRequest | Mapping[str, str],
    *,
    state_root: str | Path | None = None,
    projects_root: str | Path | None = None,
    identity: AgentIdentitySnapshot | None = None,
    include_chats: bool = True,
) -> AgentIdentityMigrationPreview:
    """Plan the local agent/chat rewrite for an authoritative bead-ID map."""

    from sase.agent.names._identity_migration_preview import (
        build_historical_agent_identity_migration_preview,
    )

    req = _coerce_request(
        request,
        state_root=state_root,
        projects_root=projects_root,
        identity=identity,
        include_chats=include_chats,
    )
    return build_historical_agent_identity_migration_preview(req)


def apply_historical_agent_identity_migration(
    preview: AgentIdentityMigrationPreview,
) -> AgentIdentityMigrationApplyResult:
    """Apply one successful preview with digest checks and local rollback."""

    if not isinstance(preview, AgentIdentityMigrationPreview):
        raise AgentIdentityMigrationError("apply requires a preview result")
    if preview.blockers:
        raise AgentIdentityMigrationError("cannot apply a preview with blockers")
    if not preview.actions:
        post_preview = preview_historical_agent_identity_migration(preview.request)
        return AgentIdentityMigrationApplyResult(preview, (), post_preview)

    from sase.agent.names._identity_migration_apply import apply_preview_actions

    apply_preview_actions(preview)
    post_preview = preview_historical_agent_identity_migration(preview.request)
    if post_preview.blockers or post_preview.actions:
        raise AgentIdentityMigrationError(
            "historical identity migration was applied, but a second preview "
            "was not a no-op"
        )
    return AgentIdentityMigrationApplyResult(preview, preview.actions, post_preview)


def _coerce_request(
    request: AgentIdentityMigrationRequest | Mapping[str, str],
    *,
    state_root: str | Path | None,
    projects_root: str | Path | None,
    identity: AgentIdentitySnapshot | None,
    include_chats: bool,
) -> AgentIdentityMigrationRequest:
    if isinstance(request, AgentIdentityMigrationRequest):
        return request
    if state_root is None:
        raise TypeError("state_root is required when passing a bead map directly")
    return AgentIdentityMigrationRequest(
        bead_id_map=request,
        state_root=state_root,
        projects_root=projects_root,
        identity=identity,
        include_chats=include_chats,
    )


def _owner_dict(owner: AgentOwnerIdentity | None) -> dict[str, str] | None:
    if owner is None:
        return None
    return {"username": owner.username, "machine_name": owner.machine_name}


# Explicit aliases for callers that use the shorter plan terminology.
preview_agent_identity_migration = preview_historical_agent_identity_migration
apply_agent_identity_migration = apply_historical_agent_identity_migration


__all__ = [
    "AgentIdentityMigrationApplyResult",
    "AgentIdentityMigrationBlocker",
    "AgentIdentityMigrationError",
    "AgentIdentityMigrationFileAction",
    "AgentIdentityMigrationPreview",
    "AgentIdentityMigrationRequest",
    "AgentIdentityMigrationSkip",
    "apply_agent_identity_migration",
    "apply_historical_agent_identity_migration",
    "preview_agent_identity_migration",
    "preview_historical_agent_identity_migration",
]
