"""Shared helpers for the split autonomy landing-gap contract tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def inputs(tmp_path: Path, preserved: dict[str, Any] | None = None):
    from sase.axe.run_agent_directive_metadata import AgentMetadataInputs

    return AgentMetadataInputs(
        workspace_dir=str(tmp_path),
        workspace_num=0,
        output_path=None,
        bead_id=None,
        wait_names=[],
        wait_identity_deps=[],
        wait_fork_sources=[],
        wait_beads=[],
        wait_hoods=[],
        model=None,
        llm_provider=None,
        reasoning_effort=None,
        model_alias=None,
        model_alias_trail=[],
        model_alias_origin=None,
        model_alias_reservation=None,
        model_alias_overrides={},
        vcs_provider=None,
        auto_dismiss=None,
        preserved=dict(preserved or {}),
        epic_work={},
        cl_name=None,
    )
