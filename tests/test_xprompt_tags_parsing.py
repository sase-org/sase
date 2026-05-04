"""Tests for xprompt tag parsing, model tag support, and tags from various sources."""

import json
from pathlib import Path

from sase.xprompt.models import XPrompt, xprompt_to_workflow
from sase.xprompt.tags import XPromptTag, parse_tags
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
    import pytest

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
            "append_to_pr",
            "append_to_commit_and_propose",
            "memory",
            "create_epic_bead",
            "create_legend_bead",
            "work_phase_bead",
            "land_epic",
            "land_legend",
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


# ── Tags from frontmatter (.md files) ──────────────────────────────────


def test_tags_from_frontmatter(tmp_path: Path) -> None:
    """Tags are parsed from .md file frontmatter."""
    from sase.xprompt.loader import _load_xprompt_from_file

    md = tmp_path / "test.md"
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


def test_tags_from_workflow_yaml(tmp_path: Path) -> None:
    from sase.xprompt.workflow_loader import _load_workflow_from_file

    yml = tmp_path / "test.yml"
    yml.write_text("tags: rollover\n\nsteps:\n  - name: main\n    prompt_part: body\n")
    wf = _load_workflow_from_file(yml)
    assert wf is not None
    assert wf.has_tag(XPromptTag.rollover)


# ── wraps_all backward compat ──────────────────────────────────────────


def test_wraps_all_auto_adds_vcs_tag(tmp_path: Path) -> None:
    """wraps_all: true in YAML auto-adds vcs tag."""
    from sase.xprompt.workflow_loader import _load_workflow_from_file

    yml = tmp_path / "git.yml"
    yml.write_text("wraps_all: true\n\nsteps:\n  - name: main\n    prompt_part: body\n")
    wf = _load_workflow_from_file(yml)
    assert wf is not None
    assert wf.has_tag(XPromptTag.vcs)
    assert wf.wraps_all is True


def test_vcs_tag_sets_wraps_all(tmp_path: Path) -> None:
    """tags: vcs in YAML sets wraps_all = True for backward compat."""
    from sase.xprompt.workflow_loader import _load_workflow_from_file

    yml = tmp_path / "git.yml"
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


def test_serialize_deserialize_preserves_tags(tmp_path: Path) -> None:
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
    path = tmp_path / "xprompts.json"
    path.write_text(json.dumps(data))

    result = deserialize_local_xprompts(str(path))
    assert "hook" in result
    assert result["hook"].has_tag(XPromptTag.fix_hook)


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


# ── Append tags ────────────────────────────────────────────────────────


def test_parse_append_to_pr_tag() -> None:
    assert parse_tags("append_to_pr") == frozenset({XPromptTag.append_to_pr})


def test_parse_append_to_commit_and_propose_tag() -> None:
    assert parse_tags("append_to_commit_and_propose") == frozenset(
        {XPromptTag.append_to_commit_and_propose}
    )
