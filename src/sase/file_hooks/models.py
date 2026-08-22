"""Shared file-hook event models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from sase.config.file_hooks import FileHookEvent, FileHookOp


RepoKind = Literal["primary"] | str


@dataclass(frozen=True)
class CapturedFileEvent:
    """One fully attributed file event ready for execution."""

    abs_path: str
    repo_root: str
    project: str
    repo_kind: RepoKind
    sidecar_role: str | None
    rel_path: str
    op: FileHookOp
    cause: str = "user"
    agent_name: str | None = None

    def matching_event(self) -> FileHookEvent:
        """Return the config matcher's intentionally smaller event view."""
        return FileHookEvent(
            project=self.project,
            repo_kind=self.repo_kind,
            sidecar_role=self.sidecar_role,
            rel_path=self.rel_path,
            op=self.op,
            cause=self.cause,
            agent_name=self.agent_name,
        )

    def identity(self) -> dict[str, Any]:
        """Return the durable, non-secret identity for producer audits."""
        return {
            "abs_path": self.abs_path,
            "repo_root": self.repo_root,
            "project": self.project,
            "repo_kind": self.repo_kind,
            "sidecar_role": self.sidecar_role,
            "rel_path": self.rel_path,
            "op": self.op,
            "cause": self.cause,
            "agent_name": self.agent_name,
        }


__all__ = ["CapturedFileEvent", "RepoKind"]
