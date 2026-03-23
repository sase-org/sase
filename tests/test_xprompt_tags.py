"""Tests for the xprompt tag system."""

import json
import os
import tempfile
from unittest.mock import patch

import pytest

from sase.xprompt.models import XPrompt, xprompt_to_workflow
from sase.xprompt.tags import XPromptTag, get_by_tag, get_by_tag_strict, parse_tags
from sase.xprompt.workflow_models import Workflow, WorkflowStep


# ── parse_tags ──────────────────────────────────────────────────────────


def test_parse_tags_none() -> None:
    assert parse_tags(None) == frozenset()


def test_parse_tags_empty_string() -> None:
    assert parse_tags("") == frozenset()


def test_parse_tags_single() -> None:
    assert parse_tags("vcs") == frozenset({XPromptTag.vcs})


def test_parse_tags_comma_separated() -> None:
    result = parse_tags("vcs, rollover")
    assert result == frozenset({XPromptTag.vcs, XPromptTag.rollover})


def test_parse_tags_list() -> None:
    result = parse_tags(["crs", "fix_hook"])
    assert result == frozenset({XPromptTag.crs, XPromptTag.fix_hook})


def test_parse_tags_invalid_raises() -> None:
    with pytest.raises(ValueError, match="Unknown xprompt tag 'bogus'"):
        parse_tags("bogus")


def test_parse_tags_all_values() -> None:
    result = parse_tags(
        [
            "vcs",
            "crs",
            "fix_hook",
            "rollover",
            "mentor",
            "commit",
            "propose",
            "make_mentor_changes",
            "diff_file",
        ]
    )
    assert result == frozenset(XPromptTag)


# ── XPrompt.has_tag ────────────────────────────────────────────────────


def test_xprompt_has_tag() -> None:
    xp = XPrompt(name="foo", content="bar", tags=frozenset({XPromptTag.vcs}))
    assert xp.has_tag(XPromptTag.vcs) is True
    assert xp.has_tag(XPromptTag.crs) is False


def test_xprompt_default_no_tags() -> None:
    xp = XPrompt(name="foo", content="bar")
    assert xp.tags == frozenset()
    assert xp.has_tag(XPromptTag.vcs) is False


# ── Workflow.has_tag ────────────────────────────────────────────────────


def test_workflow_has_tag() -> None:
    wf = Workflow(
        name="git",
        steps=[WorkflowStep(name="main", prompt_part="hi")],
        tags=frozenset({XPromptTag.vcs}),
    )
    assert wf.has_tag(XPromptTag.vcs) is True
    assert wf.has_tag(XPromptTag.rollover) is False


def test_workflow_default_no_tags() -> None:
    wf = Workflow(name="x", steps=[WorkflowStep(name="m", prompt_part="y")])
    assert wf.tags == frozenset()


# ── xprompt_to_workflow preserves tags ──────────────────────────────────


def test_xprompt_to_workflow_copies_tags() -> None:
    tags = frozenset({XPromptTag.crs})
    xp = XPrompt(name="crs", content="body", tags=tags)
    wf = xprompt_to_workflow(xp)
    assert wf.tags == tags
    assert wf.has_tag(XPromptTag.crs) is True


# ── get_by_tag ──────────────────────────────────────────────────────────


def test_get_by_tag_found() -> None:
    wf_crs = Workflow(
        name="crs",
        steps=[WorkflowStep(name="main", prompt_part="crs body")],
        tags=frozenset({XPromptTag.crs}),
    )
    wf_other = Workflow(
        name="other",
        steps=[WorkflowStep(name="main", prompt_part="other body")],
    )
    mock_prompts = {"crs": wf_crs, "other": wf_other}

    with patch("sase.xprompt.loader.get_all_prompts", return_value=mock_prompts):
        result = get_by_tag(XPromptTag.crs)
    assert result is wf_crs


def test_get_by_tag_not_found() -> None:
    wf_other = Workflow(
        name="other",
        steps=[WorkflowStep(name="main", prompt_part="other body")],
    )
    with patch("sase.xprompt.loader.get_all_prompts", return_value={"other": wf_other}):
        result = get_by_tag(XPromptTag.fix_hook)
    assert result is None


def test_get_by_tag_precedence() -> None:
    """get_by_tag returns the last (highest-priority) match.

    get_all_prompts() builds the dict from lowest to highest priority,
    so the last entry with a matching tag wins.
    """
    wf_builtin = Workflow(
        name="crs",
        steps=[WorkflowStep(name="main", prompt_part="builtin crs")],
        tags=frozenset({XPromptTag.crs}),
    )
    wf_plugin = Workflow(
        name="my_crs",
        steps=[WorkflowStep(name="main", prompt_part="plugin crs")],
        tags=frozenset({XPromptTag.crs}),
    )
    # Dict is ordered lowest→highest priority; plugin overrides builtin
    mock_prompts = {"crs": wf_builtin, "my_crs": wf_plugin}

    with patch("sase.xprompt.loader.get_all_prompts", return_value=mock_prompts):
        result = get_by_tag(XPromptTag.crs)
    assert result is wf_plugin


# ── Tags from frontmatter (.md files) ──────────────────────────────────


def test_tags_from_frontmatter(tmp_path: object) -> None:
    """Tags are parsed from .md file frontmatter."""
    from pathlib import Path

    from sase.xprompt.loader import _load_xprompt_from_file

    md = Path(str(tmp_path)) / "test.md"
    md.write_text("---\ntags: crs\n---\nBody content\n")
    xp = _load_xprompt_from_file(md)
    assert xp is not None
    assert xp.has_tag(XPromptTag.crs)


# ── Tags from config entries ──────────────────────────────────────────


def test_tags_from_config_entries() -> None:
    from sase.xprompt.loader_parsing import parse_xprompt_entries

    entries = {
        "my_hook": {
            "content": "hook body",
            "tags": ["fix_hook"],
        }
    }
    result = parse_xprompt_entries(entries, "test_config")
    assert "my_hook" in result
    assert result["my_hook"].has_tag(XPromptTag.fix_hook)


# ── Tags from workflow YAML files ──────────────────────────────────────


def test_tags_from_workflow_yaml(tmp_path: object) -> None:
    from pathlib import Path

    from sase.xprompt.workflow_loader import _load_workflow_from_file

    yml = Path(str(tmp_path)) / "test.yml"
    yml.write_text("tags: rollover\n\nsteps:\n  - name: main\n    prompt_part: body\n")
    wf = _load_workflow_from_file(yml)
    assert wf is not None
    assert wf.has_tag(XPromptTag.rollover)


# ── wraps_all backward compat ──────────────────────────────────────────


def test_wraps_all_auto_adds_vcs_tag(tmp_path: object) -> None:
    """wraps_all: true in YAML auto-adds vcs tag."""
    from pathlib import Path

    from sase.xprompt.workflow_loader import _load_workflow_from_file

    yml = Path(str(tmp_path)) / "git.yml"
    yml.write_text("wraps_all: true\n\nsteps:\n  - name: main\n    prompt_part: body\n")
    wf = _load_workflow_from_file(yml)
    assert wf is not None
    assert wf.has_tag(XPromptTag.vcs)
    assert wf.wraps_all is True


def test_vcs_tag_sets_wraps_all(tmp_path: object) -> None:
    """tags: vcs in YAML sets wraps_all = True for backward compat."""
    from pathlib import Path

    from sase.xprompt.workflow_loader import _load_workflow_from_file

    yml = Path(str(tmp_path)) / "git.yml"
    yml.write_text("tags: vcs\n\nsteps:\n  - name: main\n    prompt_part: body\n")
    wf = _load_workflow_from_file(yml)
    assert wf is not None
    assert wf.wraps_all is True
    assert wf.has_tag(XPromptTag.vcs)


# ── Tags preserved through namespace ────────────────────────────────────


def test_namespace_xprompt_preserves_tags() -> None:
    from sase.xprompt.loader import _namespace_xprompt

    xp = XPrompt(name="hook", content="body", tags=frozenset({XPromptTag.fix_hook}))
    ns = _namespace_xprompt("proj", xp)
    assert ns.name == "proj/hook"
    assert ns.tags == frozenset({XPromptTag.fix_hook})


def test_namespace_workflow_preserves_tags() -> None:
    from sase.xprompt.workflow_loader import _namespace_workflow

    wf = Workflow(
        name="git",
        steps=[WorkflowStep(name="main", prompt_part="body")],
        tags=frozenset({XPromptTag.vcs}),
        wraps_all=True,
    )
    ns = _namespace_workflow("proj", wf)
    assert ns.name == "proj/git"
    assert ns.tags == frozenset({XPromptTag.vcs})
    assert ns.wraps_all is True


# ── Serialization round-trip ────────────────────────────────────────────


def test_serialize_deserialize_preserves_tags(tmp_path: object) -> None:
    from pathlib import Path

    from sase.agent.multi_prompt_launcher import deserialize_local_xprompts

    xp = XPrompt(name="hook", content="body", tags=frozenset({XPromptTag.fix_hook}))

    # Manually serialize to replicate _serialize_local_xprompts behavior
    data = {
        "hook": {
            "name": xp.name,
            "content": xp.content,
            "inputs": [],
            "source_path": None,
            "hooks": [],
            "tags": [t.value for t in xp.tags],
        }
    }
    path = Path(str(tmp_path)) / "xprompts.json"
    path.write_text(json.dumps(data))

    result = deserialize_local_xprompts(str(path))
    assert "hook" in result
    assert result["hook"].has_tag(XPromptTag.fix_hook)


# ── Rollover filtering in _get_embedded_workflow_refs ───────────────────


def test_rollover_tagged_workflows_included_in_refs() -> None:
    """Only rollover-tagged workflows appear in follow-up agent prompts."""
    from sase.axe.run_agent_exec import _get_embedded_workflow_refs

    with tempfile.TemporaryDirectory() as tmpdir:
        metadata = [
            {"name": "gcommit", "args": {}, "tags": ["rollover"]},
            {"name": "summarize", "args": {}, "tags": []},
        ]
        metadata_path = os.path.join(tmpdir, "embedded_workflows.json")
        with open(metadata_path, "w") as f:
            json.dump(metadata, f)

        result = _get_embedded_workflow_refs(tmpdir, None)
        assert "#gcommit" in result
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
            {"name": "gcommit", "args": {}, "tags": ["rollover"]},
        ]
        metadata_path = os.path.join(tmpdir, "embedded_workflows.json")
        with open(metadata_path, "w") as f:
            json.dump(metadata, f)

        result = _get_embedded_workflow_refs(tmpdir, "#git:sase ")
        assert "#git" not in result
        assert "#gcommit" in result


def test_rollover_with_args_preserved() -> None:
    """Rollover-tagged workflow args are preserved in reconstructed refs."""
    from sase.axe.run_agent_exec import _get_embedded_workflow_refs

    with tempfile.TemporaryDirectory() as tmpdir:
        metadata = [
            {"name": "gcommit", "args": {"who": "bot"}, "tags": ["rollover"]},
            {
                "name": "gchange",
                "args": {"name": "feat", "who": "bot"},
                "tags": ["rollover"],
            },
        ]
        metadata_path = os.path.join(tmpdir, "embedded_workflows.json")
        with open(metadata_path, "w") as f:
            json.dump(metadata, f)

        result = _get_embedded_workflow_refs(tmpdir, None)
        assert "#gcommit:bot" in result
        assert "#gchange(name=feat, who=bot)" in result


def test_embedded_workflows_json_includes_tags() -> None:
    """embedded_workflows.json metadata includes tags for each workflow."""
    with tempfile.TemporaryDirectory() as tmpdir:
        metadata = [
            {"name": "gcommit", "args": {}, "tags": ["rollover"]},
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


# ── New mentor-related tags ──────────────────────────────────────────────


def test_parse_mentor_tag() -> None:
    assert parse_tags("mentor") == frozenset({XPromptTag.mentor})


def test_parse_commit_tag() -> None:
    assert parse_tags("commit") == frozenset({XPromptTag.commit})


def test_parse_propose_tag() -> None:
    assert parse_tags("propose") == frozenset({XPromptTag.propose})


def test_parse_make_mentor_changes_tag() -> None:
    assert parse_tags("make_mentor_changes") == frozenset(
        {XPromptTag.make_mentor_changes}
    )


# ── get_by_tag_strict ────────────────────────────────────────────────────


def test_get_by_tag_strict_single_match() -> None:
    """get_by_tag_strict returns the single match."""
    wf = Workflow(
        name="mentor",
        steps=[WorkflowStep(name="main", prompt_part="body")],
        tags=frozenset({XPromptTag.mentor}),
    )
    with patch("sase.xprompt.loader.get_all_prompts", return_value={"mentor": wf}):
        result = get_by_tag_strict(XPromptTag.mentor)
    assert result is wf


def test_get_by_tag_strict_no_match() -> None:
    """get_by_tag_strict returns None when no match."""
    with patch("sase.xprompt.loader.get_all_prompts", return_value={}):
        result = get_by_tag_strict(XPromptTag.mentor)
    assert result is None


def test_get_by_tag_strict_multiple_raises() -> None:
    """get_by_tag_strict raises ValueError on multiple matches."""
    wf1 = Workflow(
        name="mentor1",
        steps=[WorkflowStep(name="main", prompt_part="body1")],
        tags=frozenset({XPromptTag.mentor}),
    )
    wf2 = Workflow(
        name="mentor2",
        steps=[WorkflowStep(name="main", prompt_part="body2")],
        tags=frozenset({XPromptTag.mentor}),
    )
    mock_prompts = {"mentor1": wf1, "mentor2": wf2}
    with patch("sase.xprompt.loader.get_all_prompts", return_value=mock_prompts):
        with pytest.raises(ValueError, match="Multiple xprompts found with tag"):
            get_by_tag_strict(XPromptTag.mentor)
