"""Tests for rollover filtering in _get_embedded_workflow_refs."""

import json
import os
import tempfile


# ── Rollover filtering in _get_embedded_workflow_refs ───────────────────


def test_rollover_tagged_workflows_included_in_refs() -> None:
    """Only rollover-tagged workflows appear in follow-up agent prompts."""
    from sase.axe.run_agent_exec import _get_embedded_workflow_refs

    with tempfile.TemporaryDirectory() as tmpdir:
        metadata = [
            {"name": "commit", "args": {}, "tags": ["rollover"]},
            {"name": "summarize", "args": {}, "tags": []},
        ]
        metadata_path = os.path.join(tmpdir, "embedded_workflows.json")
        with open(metadata_path, "w") as f:
            json.dump(metadata, f)

        result = _get_embedded_workflow_refs(tmpdir, None)
        assert "#commit" in result
        assert "#summarize" not in result


def test_non_tagged_workflows_excluded_from_rollover() -> None:
    """Workflows without the rollover tag are excluded from follow-up refs."""
    from sase.axe.run_agent_exec import _get_embedded_workflow_refs

    with tempfile.TemporaryDirectory() as tmpdir:
        metadata = [
            {"name": "sync", "args": {}, "tags": []},
        ]
        metadata_path = os.path.join(tmpdir, "embedded_workflows.json")
        with open(metadata_path, "w") as f:
            json.dump(metadata, f)

        result = _get_embedded_workflow_refs(tmpdir, None)
        assert result == ""


def test_rollover_backward_compat_no_tags() -> None:
    """When no entry has tags key, all non-VCS workflows roll over (legacy)."""
    from sase.axe.run_agent_exec import _get_embedded_workflow_refs

    with tempfile.TemporaryDirectory() as tmpdir:
        metadata = [
            {"name": "propose", "args": {}},
            {"name": "sync", "args": {}},
        ]
        metadata_path = os.path.join(tmpdir, "embedded_workflows.json")
        with open(metadata_path, "w") as f:
            json.dump(metadata, f)

        result = _get_embedded_workflow_refs(tmpdir, None)
        # Both should appear (no tags key means legacy behavior)
        assert "#propose" in result
        assert "#sync" in result


def test_rollover_with_vcs_excluded() -> None:
    """VCS workflows are still excluded even if they have rollover tag."""
    from sase.axe.run_agent_exec import _get_embedded_workflow_refs

    with tempfile.TemporaryDirectory() as tmpdir:
        metadata = [
            {"name": "git", "args": {}, "tags": ["vcs", "rollover"]},
            {"name": "commit", "args": {}, "tags": ["rollover"]},
        ]
        metadata_path = os.path.join(tmpdir, "embedded_workflows.json")
        with open(metadata_path, "w") as f:
            json.dump(metadata, f)

        result = _get_embedded_workflow_refs(tmpdir, "#git:sase ")
        assert "#git" not in result
        assert "#commit" in result


def test_rollover_with_args_preserved() -> None:
    """Rollover-tagged workflow args are preserved in reconstructed refs."""
    from sase.axe.run_agent_exec import _get_embedded_workflow_refs

    with tempfile.TemporaryDirectory() as tmpdir:
        metadata = [
            {"name": "commit", "args": {"who": "bot"}, "tags": ["rollover"]},
            {
                "name": "pr",
                "args": {"name": "feat", "who": "bot"},
                "tags": ["rollover"],
            },
        ]
        metadata_path = os.path.join(tmpdir, "embedded_workflows.json")
        with open(metadata_path, "w") as f:
            json.dump(metadata, f)

        result = _get_embedded_workflow_refs(tmpdir, None)
        assert "#commit:bot" in result
        assert "#pr(name=feat, who=bot)" in result


def test_embedded_workflows_json_includes_tags() -> None:
    """embedded_workflows.json metadata includes tags for each workflow."""
    with tempfile.TemporaryDirectory() as tmpdir:
        metadata = [
            {"name": "commit", "args": {}, "tags": ["rollover"]},
            {"name": "git", "args": {}, "tags": ["vcs"]},
            {"name": "sync", "args": {}, "tags": []},
        ]
        metadata_path = os.path.join(tmpdir, "embedded_workflows.json")
        with open(metadata_path, "w") as f:
            json.dump(metadata, f)

        with open(metadata_path) as f:
            loaded = json.load(f)

        assert loaded[0]["tags"] == ["rollover"]
        assert loaded[1]["tags"] == ["vcs"]
        assert loaded[2]["tags"] == []
