"""Tests for runner prompt-tag persistence."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from sase.ace.tui.models.agent import AgentType
from sase.axe.run_agent_phases import extract_directives_and_write_meta


def test_extract_directives_persists_tag_with_atomic_helper(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace_dir = tmp_path / "workspace"
    artifacts_dir = tmp_path / "artifacts" / "20260506120000"
    workspace_dir.mkdir()
    artifacts_dir.mkdir(parents=True)
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)

    with (
        patch(
            "sase.llm_provider.temporary_override."
            "resolve_effective_default_provider_model",
            return_value=("codex", "gpt-5"),
        ),
        patch("sase.vcs_provider._registry.detect_vcs", return_value=None),
        patch("sase.agent.names.claim_agent_name"),
        patch("sase.ace.agent_tags.update_agent_tag") as update_agent_tag,
    ):
        info = extract_directives_and_write_meta(
            "%name:taggy\n%tag:sase-26\nDo work",
            str(workspace_dir),
            str(artifacts_dir),
            cl_name="legend-cl",
        )

    assert info.tag == "sase-26"
    assert json.loads((artifacts_dir / "agent_meta.json").read_text())["tag"] == (
        "sase-26"
    )
    update_agent_tag.assert_called_once_with(
        (AgentType.WORKFLOW, "legend-cl", "20260506120000"),
        "sase-26",
    )
