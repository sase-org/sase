"""Data model for workspace claims in the RUNNING field."""

import re
from dataclasses import dataclass


@dataclass
class WorkspaceClaim:
    """Represents a single workspace claim in the RUNNING field."""

    workspace_num: int
    workflow: str
    cl_name: str | None
    pid: int
    artifacts_timestamp: str | None = None
    pinned: bool = False

    def to_line(self) -> str:
        """Convert to RUNNING field line format.

        Format: #N | PID | WORKFLOW | CL_NAME | TIMESTAMP
        PID is second to make it easily visible for process management.

        Raises:
            ValueError: If pid is not set (every RUNNING entry must have a PID).
        """
        cl_part = self.cl_name or ""
        ts_part = f" | {self.artifacts_timestamp}" if self.artifacts_timestamp else ""
        pin_part = " | PINNED" if self.pinned else ""
        return f"  #{self.workspace_num} | {self.pid} | {self.workflow} | {cl_part}{ts_part}{pin_part}"

    @staticmethod
    def from_line(line: str) -> "WorkspaceClaim | None":
        """Parse a RUNNING field line into a WorkspaceClaim.

        Format (PID second, required):
        - #<N> | <PID> | <WORKFLOW> | <CL_NAME>
        - #<N> | <PID> | <WORKFLOW> | <CL_NAME> | <TIMESTAMP>

        Note: Returns None for entries without a PID (PID is required).
        """
        match = re.match(
            r"^\s*#(\d+)\s*\|\s*(\d+)\s*\|\s*(\S+)\s*\|\s*([^|]*?)"
            r"(?:\s*\|\s*(\d{6}_\d{6}|\d{14}))?(?:\s*\|\s*([^|]+))?$",
            line,
        )
        if match:
            workspace_num = int(match.group(1))
            pid = int(match.group(2))
            workflow = match.group(3)
            cl_name = match.group(4).strip() or None
            artifacts_timestamp = match.group(5) if match.group(5) else None
            pinned = match.group(6) is not None and match.group(6).strip() == "PINNED"
            return WorkspaceClaim(
                workspace_num=workspace_num,
                workflow=workflow,
                cl_name=cl_name,
                pid=pid,
                artifacts_timestamp=artifacts_timestamp,
                pinned=pinned,
            )

        return None
