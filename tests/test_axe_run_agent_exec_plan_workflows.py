"""Tests for axe run_agent_exec_plan embedded workflow helpers."""

import json

from sase.axe.run_agent_exec_plan import _get_embedded_workflow_refs


def test_get_embedded_workflow_refs_excludes_vcs_when_tag_set(tmp_path) -> None:
    """VCS-tagged workflows are excluded when vcs_tag is set."""
    meta = tmp_path / "embedded_workflows.json"
    meta.write_text(
        json.dumps(
            [
                {"name": "gh", "tags": ["vcs", "rollover"]},
                {"name": "propose", "tags": ["rollover"]},
            ]
        )
    )

    result = _get_embedded_workflow_refs(str(tmp_path), "#gh:sase ")
    assert "#gh" not in result
    assert "#propose" in result


def test_get_embedded_workflow_refs_includes_vcs_when_tag_none(tmp_path) -> None:
    """VCS-tagged workflows ARE included when vcs_tag is None."""
    meta = tmp_path / "embedded_workflows.json"
    meta.write_text(
        json.dumps(
            [
                {"name": "gh", "args": {"repo": "sase"}, "tags": ["vcs", "rollover"]},
                {"name": "propose", "tags": ["rollover"]},
            ]
        )
    )

    result = _get_embedded_workflow_refs(str(tmp_path), None)
    assert "#gh:sase" in result
    assert "#propose" in result
