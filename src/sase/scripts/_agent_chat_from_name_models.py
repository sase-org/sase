"""Wire models for named-agent fork source resolution."""

from __future__ import annotations

from dataclasses import dataclass

from sase.scripts._fork_proc_sources import ForkProcInfo


@dataclass(frozen=True)
class ForkFailure:
    """Terminal failure metadata for one agent fork source."""

    outcome: str
    error: str | None
    traceback: str | None
    ended_at: str | None
    transcript_available: bool
    launch_prompt: str | None = None

    def to_json_data(self) -> dict[str, object]:
        return {
            "outcome": self.outcome,
            "error": self.error,
            "traceback": self.traceback,
            "ended_at": self.ended_at,
            "transcript_available": self.transcript_available,
            "launch_prompt": self.launch_prompt,
        }


@dataclass(frozen=True)
class ForkClanMemberSource:
    """One completed clan member included in a clan fork source."""

    name: str
    path: str
    artifact_dir: str


@dataclass(frozen=True)
class ForkFamilyMemberSource:
    """One included family member: an agent shell or a proc/monitor shell."""

    name: str
    artifact_dir: str
    outcome: str
    kind: str = "agent"
    path: str = ""
    proc: ForkProcInfo | None = None
    failure: ForkFailure | None = None

    def to_json_data(self) -> dict[str, object]:
        data: dict[str, object] = {
            "kind": self.kind,
            "name": self.name,
            "artifact_dir": self.artifact_dir,
            "outcome": self.outcome,
        }
        if self.path:
            data["path"] = self.path
        if self.proc is not None:
            data["proc"] = self.proc.to_json_data()
        if self.failure is not None:
            data["failure"] = self.failure.to_json_data()
        return data


@dataclass(frozen=True)
class ForkExcludedFamilyMember:
    """One family member omitted from a family fork source."""

    name: str
    status: str


@dataclass(frozen=True)
class ForkSource:
    """One agent conversation, proc shell, family, or completed clan."""

    kind: str
    name: str
    path: str
    generation: str | None = None
    tribe: str | None = None
    members: tuple[ForkClanMemberSource | ForkFamilyMemberSource, ...] = ()
    excluded: tuple[ForkExcludedFamilyMember, ...] = ()
    failure: ForkFailure | None = None
    proc: ForkProcInfo | None = None

    def to_json_data(self) -> dict[str, object]:
        """Return the stable wire shape consumed by the fork history builder."""
        if self.kind == "agent":
            data: dict[str, object] = {
                "kind": self.kind,
                "name": self.name,
                "path": self.path,
            }
            if self.failure is not None:
                data["failure"] = self.failure.to_json_data()
            return data
        if self.kind == "proc":
            data = {
                "kind": self.kind,
                "name": self.name,
            }
            if self.proc is not None:
                data["proc"] = self.proc.to_json_data()
            return data
        if self.kind == "family":
            return {
                "kind": self.kind,
                "name": self.name,
                "members": [
                    member.to_json_data()
                    for member in self.members
                    if isinstance(member, ForkFamilyMemberSource)
                ],
                "excluded": [
                    {"name": member.name, "status": member.status}
                    for member in self.excluded
                ],
            }
        return {
            "kind": self.kind,
            "name": self.name,
            "generation": self.generation,
            "tribe": self.tribe,
            "members": [
                {
                    "name": member.name,
                    "path": member.path,
                    "artifact_dir": member.artifact_dir,
                }
                for member in self.members
            ],
        }
