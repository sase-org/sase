"""Shared helpers for RUNNING field regression tests."""

from __future__ import annotations

import tempfile
from pathlib import Path

from sase.running_field import WorkspaceClaim


def create_project_file_with_running(
    tmp_path: Path,
    running_claims: list[WorkspaceClaim] | None = None,
) -> str:
    """Create a temporary project file with optional RUNNING field."""
    with tempfile.NamedTemporaryFile(
        dir=tmp_path, mode="w", delete=False, suffix=".sase"
    ) as f:
        f.write("# Test Project\n\n")
        if running_claims:
            f.write("RUNNING:\n")
            for claim in running_claims:
                f.write(claim.to_line() + "\n")
        f.write("NAME: Test Feature\n")
        f.write("DESCRIPTION:\n")
        f.write("  Test description\n")
        f.write("PARENT: None\n")
        f.write("PR: None\n")
        f.write("STATUS: Ready\n")
        return f.name
