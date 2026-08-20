"""Data model for workspace claims in the RUNNING field."""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ClaimResult:
    """Outcome of a workspace claim/release/transfer operation.

    ``success`` is the headline outcome; ``error`` carries the human-readable
    reason on failure (sourced from the Rust outcome dict when the Rust core
    rejected the claim, or ``repr(exc)`` when a Python exception was caught).
    """

    success: bool
    error: str | None = None


class WorkspaceClaimError(RuntimeError):
    """Raised when a workspace claim or transfer fails.

    Subclasses ``RuntimeError`` so existing ``except RuntimeError`` blocks
    continue to handle it; the retry wrapper in ``launch_executor`` catches
    this type explicitly so the predicate doesn't depend on a string match.
    """

    def __init__(self, message: str, *, workspace_num: int | None = None) -> None:
        super().__init__(message)
        self.workspace_num = workspace_num


@dataclass
class WorkspaceClaim:
    """Represents a single workspace claim in the RUNNING field."""

    workspace_num: int
    workflow: str
    cl_name: str | None
    pid: int
    artifacts_timestamp: str | None = None
    pinned: bool = False
    suffix_fields: tuple[str, ...] = ()

    def to_line(self) -> str:
        """Convert to RUNNING field line format.

        Format: #N | PID | WORKFLOW | CL_NAME | TIMESTAMP
        PID is second to make it easily visible for process management.

        Raises:
            ValueError: If pid is not set (every RUNNING entry must have a PID).
        """
        cl_part = self.cl_name or ""
        suffix_fields = list(self.suffix_fields)
        if self.artifacts_timestamp and not any(
            _is_timestamp_part(field) for field in suffix_fields
        ):
            insert_idx = (
                suffix_fields.index("PINNED")
                if "PINNED" in suffix_fields
                else len(suffix_fields)
            )
            suffix_fields.insert(insert_idx, self.artifacts_timestamp)
        if self.pinned and "PINNED" not in suffix_fields:
            suffix_fields.append("PINNED")
        suffix_part = f" | {' | '.join(suffix_fields)}" if suffix_fields else ""
        return (
            f"  #{self.workspace_num} | {self.pid} | {self.workflow} | "
            f"{cl_part}{suffix_part}"
        )

    @staticmethod
    def from_line(line: str) -> "WorkspaceClaim | None":
        """Parse a RUNNING field line into a WorkspaceClaim.

        Format (PID second, required):
        - #<N> | <PID> | <WORKFLOW> | <CL_NAME>
        - #<N> | <PID> | <WORKFLOW> | <CL_NAME> | <TIMESTAMP>

        Note: Returns None for entries without a PID (PID is required).
        """
        trimmed = line.strip()
        if not trimmed.startswith("#"):
            return None
        parts = [part.strip() for part in trimmed.split("|")]
        if len(parts) < 4:
            return None
        try:
            workspace_num = int(parts[0].removeprefix("#"))
            pid = int(parts[1])
        except ValueError:
            return None
        workflow = parts[2]
        if not workflow:
            return None

        suffix_fields = tuple(parts[4:])
        artifacts_timestamp = next(
            (field for field in suffix_fields if _is_timestamp_part(field)),
            None,
        )
        pinned = "PINNED" in suffix_fields
        return WorkspaceClaim(
            workspace_num=workspace_num,
            workflow=workflow,
            cl_name=parts[3].strip() or None,
            pid=pid,
            artifacts_timestamp=artifacts_timestamp,
            pinned=pinned,
            suffix_fields=suffix_fields,
        )


def _is_timestamp_part(value: str) -> bool:
    return (
        re.fullmatch(r"\d{14}", value) is not None
        or re.fullmatch(r"\d{8}_\d{6}", value) is not None
        or re.fullmatch(r"\d{6}_\d{6}", value) is not None
    )
