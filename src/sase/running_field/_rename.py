"""Renaming the Patch that RUNNING field claims point at."""

import os

from sase.ace.patch import patch_lock, write_patch_atomic
from sase.running_field._model import WorkspaceClaim


def update_running_field_cl_name(
    project_file: str,
    old_cl_name: str,
    new_cl_name: str,
) -> bool:
    """Update the cl_name in RUNNING field entries.

    This is used when a Patch is renamed (e.g., during restore) to
    ensure the RUNNING field entries reference the new name.
    Acquires a lock for the entire read-modify-write cycle.

    Args:
        project_file: Path to the ProjectSpec file
        old_cl_name: The old Patch name to replace
        new_cl_name: The new Patch name

    Returns:
        True if update was successful, False otherwise
    """
    if not os.path.exists(project_file):
        return False

    try:
        with patch_lock(project_file):
            with open(project_file, encoding="utf-8") as f:
                content = f.read()
                lines = content.split("\n")

            new_lines: list[str] = []
            in_running_field = False
            updated = False

            for line in lines:
                if line.startswith("RUNNING:"):
                    in_running_field = True
                    new_lines.append(line)
                    continue

                if in_running_field and line.startswith("  "):
                    claim = WorkspaceClaim.from_line(line)
                    if claim and claim.cl_name == old_cl_name:
                        # Update the cl_name, preserving other fields
                        updated_claim = WorkspaceClaim(
                            workspace_num=claim.workspace_num,
                            workflow=claim.workflow,
                            cl_name=new_cl_name,
                            pid=claim.pid,
                            artifacts_timestamp=claim.artifacts_timestamp,
                            pinned=claim.pinned,
                        )
                        new_lines.append(updated_claim.to_line())
                        updated = True
                        continue
                else:
                    in_running_field = False

                new_lines.append(line)

            if not updated:
                # No changes needed
                return True

            # Write atomically
            write_patch_atomic(
                project_file,
                "\n".join(new_lines),
                f"Rename {old_cl_name} to {new_cl_name} in RUNNING field",
            )
            return True
    except Exception:
        return False
