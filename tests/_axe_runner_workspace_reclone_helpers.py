"""Shared public helpers for the private workspace-reclone test modules."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from sase.running_field import WorkspaceClaim
from sase.workspace_provider.occupant import new_occupant_record, write_occupant_record


def claim_checkout_num7(
    tmp_path: Path, workspace_dir: Path, workflow: str = "ace(run)-mine"
) -> str:
    """Claim workspace #7 for this process (guard + occupant record)."""
    with tempfile.NamedTemporaryFile(
        dir=tmp_path, mode="w", delete=False, suffix=".sase"
    ) as f:
        f.write("# Test Project\n\nRUNNING:\n")
        f.write(
            WorkspaceClaim(
                workspace_num=7,
                workflow=workflow,
                cl_name="feature",
                pid=os.getpid(),
                artifacts_timestamp="mine-ts",
            ).to_line()
            + "\n"
        )
        f.write("NAME: Test Feature\nDESCRIPTION:\n  Test\nSTATUS: Ready\n")
        project_file = f.name
    write_occupant_record(
        str(workspace_dir),
        new_occupant_record(
            pid=os.getpid(),
            workflow=workflow,
            project="sase",
            workspace_num=7,
        ),
    )
    return project_file
