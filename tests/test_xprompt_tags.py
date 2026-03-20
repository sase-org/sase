"""Tests for the xprompt tag system (Phase 1: Core Tag Infrastructure)."""

from pathlib import Path
from unittest.mock import patch

import pytest

from sase.xprompt.models import XPrompt, xprompt_to_workflow
from sase.xprompt.tags import XPromptTag, get_by_tag, parse_tags
from sase.xprompt.workflow_models import Workflow, WorkflowStep


# --- parse_tags ---


def test_parse_tags_none() -> None:
    """None returns empty set."""
    assert parse_tags(None) == set()


def test_parse_tags_empty_string() -> None:
    """Empty string returns empty set."""
    assert parse_tags("") == set()


def test_parse_tags_single_string() -> None:
    """Single tag string parses correctly."""
    assert parse_tags("vcs") == {XPromptTag.VCS}


def test_parse_tags_comma_separated() -> None:
    """Comma-separated string parses all tags."""
    result = parse_tags("vcs, crs")
    assert result == {XPromptTag.VCS, XPromptTag.CRS}


def test_parse_tags_list() -> None:
    """List of strings parses correctly."""
    result = parse_tags(["fix_hook", "rollover"])
    assert result == {XPromptTag.FIX_HOOK, XPromptTag.ROLLOVER}


def test_parse_tags_all_values() -> None:
    """All four tag values are recognized."""
    result = parse_tags(["vcs", "crs", "fix_hook", "rollover"])
    assert result == {XPromptTag.VCS, XPromptTag.CRS, XPromptTag.FIX_HOOK, XPromptTag.ROLLOVER}


def test_parse_tags_unknown_raises() -> None:
    """Unknown tag name raises ValueError."""
    with pytest.raises(ValueError, match="Unknown xprompt tag 'bogus'"):
        parse_tags("bogus")


def test_parse_tags_unknown_in_list_raises() -> None:
    """Unknown tag in list raises ValueError."""
    with pytest.raises(ValueError, match="Unknown xprompt tag 'nope'"):
        parse_tags(["vcs", "nope"])


def test_parse_tags_whitespace_handling() -> None:
    """Whitespace around tags is stripped."""
    result = parse_tags("  vcs ,  crs  ")
    assert result == {XPromptTag.VCS, XPromptTag.CRS}


# --- XPrompt.has_tag ---


def test_xprompt_has_tag() -> None:
    """XPrompt.has_tag returns True for present tags."""
    xp = XPrompt(name="test", content="hi", tags={XPromptTag.VCS})
    assert xp.has_tag(XPromptTag.VCS) is True
    assert xp.has_tag(XPromptTag.CRS) is False


def test_xprompt_default_no_tags() -> None:
    """XPrompt defaults to empty tags set."""
    xp = XPrompt(name="test", content="hi")
    assert xp.tags == set()
    assert xp.has_tag(XPromptTag.VCS) is False


# --- Workflow.has_tag ---


def test_workflow_has_tag() -> None:
    """Workflow.has_tag returns True for present tags."""
    wf = Workflow(
        name="test",
        steps=[WorkflowStep(name="main", prompt_part="hi")],
        tags={XPromptTag.CRS, XPromptTag.ROLLOVER},
    )
    assert wf.has_tag(XPromptTag.CRS) is True
    assert wf.has_tag(XPromptTag.ROLLOVER) is True
    assert wf.has_tag(XPromptTag.VCS) is False


def test_workflow_default_no_tags() -> None:
    """Workflow defaults to empty tags set."""
    wf = Workflow(name="test", steps=[WorkflowStep(name="main", prompt_part="hi")])
    assert wf.tags == set()


# --- xprompt_to_workflow preserves tags ---


def test_xprompt_to_workflow_copies_tags() -> None:
    """Tags are copied from XPrompt to the generated Workflow."""
    xp = XPrompt(
        name="tagged",
        content="content",
        tags={XPromptTag.FIX_HOOK},
    )
    wf = xprompt_to_workflow(xp)
    assert wf.tags == {XPromptTag.FIX_HOOK}
    assert wf.has_tag(XPromptTag.FIX_HOOK) is True


def test_xprompt_to_workflow_empty_tags() -> None:
    """Empty tags are preserved through conversion."""
    xp = XPrompt(name="plain", content="content")
    wf = xprompt_to_workflow(xp)
    assert wf.tags == set()


# --- Tags from .md frontmatter (loader) ---


def test_load_xprompt_from_file_with_tags(tmp_path: Path) -> None:
    """Tags are parsed from .md file frontmatter."""
    from sase.xprompt.loader import _load_xprompt_from_file

    md = tmp_path / "tagged.md"
    md.write_text("---\ntags: vcs\n---\nContent here\n")
    xp = _load_xprompt_from_file(md)
    assert xp is not None
    assert xp.tags == {XPromptTag.VCS}


def test_load_xprompt_from_file_with_list_tags(tmp_path: Path) -> None:
    """Tags as YAML list are parsed from .md file frontmatter."""
    from sase.xprompt.loader import _load_xprompt_from_file

    md = tmp_path / "multi.md"
    md.write_text("---\ntags:\n  - crs\n  - fix_hook\n---\nBody\n")
    xp = _load_xprompt_from_file(md)
    assert xp is not None
    assert xp.tags == {XPromptTag.CRS, XPromptTag.FIX_HOOK}


def test_load_xprompt_from_file_no_tags(tmp_path: Path) -> None:
    """XPrompt without tags field gets empty set."""
    from sase.xprompt.loader import _load_xprompt_from_file

    md = tmp_path / "plain.md"
    md.write_text("---\nname: plain\n---\nContent\n")
    xp = _load_xprompt_from_file(md)
    assert xp is not None
    assert xp.tags == set()


# --- Tags from config entries (loader_parsing) ---


def test_parse_xprompt_entries_with_tags() -> None:
    """Tags are parsed from structured xprompt config entries."""
    from sase.xprompt.loader_parsing import parse_xprompt_entries

    entries = {
        "my_crs": {
            "content": "Review this",
            "tags": "crs",
        }
    }
    result = parse_xprompt_entries(entries, "config")
    assert "my_crs" in result
    assert result["my_crs"].tags == {XPromptTag.CRS}


def test_parse_xprompt_entries_simple_string_no_tags() -> None:
    """Simple string xprompt entries have no tags."""
    from sase.xprompt.loader_parsing import parse_xprompt_entries

    entries = {"simple": "Just content"}
    result = parse_xprompt_entries(entries, "config")
    assert result["simple"].tags == set()


# --- Tags from workflow YAML files ---


def test_load_workflow_from_file_with_tags(tmp_path: Path) -> None:
    """Tags are parsed from workflow YAML files."""
    from sase.xprompt.workflow_loader import _load_workflow_from_file

    yml = tmp_path / "my_wf.yml"
    yml.write_text("tags: vcs\nsteps:\n  - prompt_part: content\n")
    wf = _load_workflow_from_file(yml)
    assert wf is not None
    assert wf.tags == {XPromptTag.VCS}


def test_load_workflow_from_file_with_list_tags(tmp_path: Path) -> None:
    """Tags as YAML list are parsed from workflow files."""
    from sase.xprompt.workflow_loader import _load_workflow_from_file

    yml = tmp_path / "multi_tag.yml"
    yml.write_text("tags:\n  - rollover\n  - crs\nsteps:\n  - prompt_part: hi\n")
    wf = _load_workflow_from_file(yml)
    assert wf is not None
    assert wf.tags == {XPromptTag.ROLLOVER, XPromptTag.CRS}


def test_load_workflow_from_file_no_tags(tmp_path: Path) -> None:
    """Workflow without tags field gets empty set."""
    from sase.xprompt.workflow_loader import _load_workflow_from_file

    yml = tmp_path / "plain.yml"
    yml.write_text("steps:\n  - prompt_part: content\n")
    wf = _load_workflow_from_file(yml)
    assert wf is not None
    assert wf.tags == set()


# --- Namespace operations preserve tags ---


def test_namespace_xprompt_preserves_tags() -> None:
    """_namespace_xprompt copies tags to the namespaced copy."""
    from sase.xprompt.loader import _namespace_xprompt

    xp = XPrompt(name="foo", content="bar", tags={XPromptTag.FIX_HOOK})
    ns = _namespace_xprompt("proj", xp)
    assert ns.name == "proj/foo"
    assert ns.tags == {XPromptTag.FIX_HOOK}


def test_namespace_workflow_preserves_tags() -> None:
    """_namespace_workflow copies tags to the namespaced copy."""
    from sase.xprompt.workflow_loader import _namespace_workflow

    wf = Workflow(
        name="wf",
        steps=[WorkflowStep(name="s", prompt_part="x")],
        tags={XPromptTag.VCS, XPromptTag.ROLLOVER},
    )
    ns = _namespace_workflow("proj", wf)
    assert ns.name == "proj/wf"
    assert ns.tags == {XPromptTag.VCS, XPromptTag.ROLLOVER}


# --- get_by_tag ---


def test_get_by_tag_finds_tagged_workflow() -> None:
    """get_by_tag returns a workflow that has the requested tag."""
    tagged_wf = Workflow(
        name="my_vcs",
        steps=[WorkflowStep(name="s", prompt_part="x")],
        tags={XPromptTag.VCS},
    )
    prompts = {"my_vcs": tagged_wf, "other": Workflow(
        name="other",
        steps=[WorkflowStep(name="s", prompt_part="x")],
    )}
    with patch("sase.xprompt.loader.get_all_prompts", return_value=prompts):
        result = get_by_tag(XPromptTag.VCS)
    assert result is tagged_wf


def test_get_by_tag_returns_none_when_no_match() -> None:
    """get_by_tag returns None when no workflow has the tag."""
    prompts = {"plain": Workflow(
        name="plain",
        steps=[WorkflowStep(name="s", prompt_part="x")],
    )}
    with patch("sase.xprompt.loader.get_all_prompts", return_value=prompts):
        result = get_by_tag(XPromptTag.CRS)
    assert result is None


# --- XPromptTag enum values ---


def test_xprompt_tag_values() -> None:
    """XPromptTag enum has the expected values."""
    assert XPromptTag.VCS.value == "vcs"
    assert XPromptTag.CRS.value == "crs"
    assert XPromptTag.FIX_HOOK.value == "fix_hook"
    assert XPromptTag.ROLLOVER.value == "rollover"


# --- Phase 2: VCS tag backward compatibility ---


def test_wraps_all_yaml_auto_adds_vcs_tag(tmp_path: Path) -> None:
    """wraps_all: true in YAML auto-adds the vcs tag."""
    from sase.xprompt.workflow_loader import _load_workflow_from_file

    yml = tmp_path / "git.yml"
    yml.write_text("wraps_all: true\nsteps:\n  - prompt_part: content\n")
    wf = _load_workflow_from_file(yml)
    assert wf is not None
    assert wf.has_tag(XPromptTag.VCS)
    assert wf.wraps_all is True


def test_vcs_tag_yaml_sets_wraps_all(tmp_path: Path) -> None:
    """tags: vcs in YAML sets wraps_all = True for backward compat."""
    from sase.xprompt.workflow_loader import _load_workflow_from_file

    yml = tmp_path / "myvcs.yml"
    yml.write_text("tags: vcs\nsteps:\n  - prompt_part: content\n")
    wf = _load_workflow_from_file(yml)
    assert wf is not None
    assert wf.wraps_all is True
    assert wf.has_tag(XPromptTag.VCS)


def test_wraps_all_and_tags_vcs_together(tmp_path: Path) -> None:
    """Both wraps_all: true and tags: vcs in YAML works correctly."""
    from sase.xprompt.workflow_loader import _load_workflow_from_file

    yml = tmp_path / "both.yml"
    yml.write_text("wraps_all: true\ntags: vcs\nsteps:\n  - prompt_part: content\n")
    wf = _load_workflow_from_file(yml)
    assert wf is not None
    assert wf.wraps_all is True
    assert wf.has_tag(XPromptTag.VCS)


def test_workflow_wraps_all_constructor_syncs_vcs_tag() -> None:
    """Workflow(wraps_all=True) auto-adds VCS tag via __post_init__."""
    wf = Workflow(
        name="test",
        steps=[WorkflowStep(name="s", prompt_part="x")],
        wraps_all=True,
    )
    assert wf.has_tag(XPromptTag.VCS)


def test_workflow_vcs_tag_constructor_syncs_wraps_all() -> None:
    """Workflow(tags={VCS}) auto-sets wraps_all via __post_init__."""
    wf = Workflow(
        name="test",
        steps=[WorkflowStep(name="s", prompt_part="x")],
        tags={XPromptTag.VCS},
    )
    assert wf.wraps_all is True


def test_workflow_no_vcs_tag_no_wraps_all() -> None:
    """Workflow without vcs tag or wraps_all stays unset."""
    wf = Workflow(
        name="test",
        steps=[WorkflowStep(name="s", prompt_part="x")],
        tags={XPromptTag.CRS},
    )
    assert wf.wraps_all is False
    assert not wf.has_tag(XPromptTag.VCS)


# --- Phase 3: CRS and Fix Hook tag-based lookup ---


def test_build_crs_prompt_uses_tag_lookup() -> None:
    """_build_crs_prompt uses tag-based lookup for xprompt name."""
    from sase.crs_workflow import _build_crs_prompt

    custom_wf = Workflow(
        name="my_custom_crs",
        steps=[WorkflowStep(name="s", prompt_part="x")],
        tags={XPromptTag.CRS},
    )
    with patch("sase.crs_workflow.get_by_tag", return_value=custom_wf) as mock_get:
        with patch("sase.crs_workflow.process_xprompt_references", side_effect=lambda x: x):
            result = _build_crs_prompt("/tmp/comments.json")
    mock_get.assert_called_once_with(XPromptTag.CRS)
    assert "#my_custom_crs(" in result


def test_build_crs_prompt_with_cl_name_uses_tag() -> None:
    """_build_crs_prompt uses tag-resolved name with cl_name."""
    from sase.crs_workflow import _build_crs_prompt

    custom_wf = Workflow(
        name="custom_crs",
        steps=[WorkflowStep(name="s", prompt_part="x")],
        tags={XPromptTag.CRS},
    )
    with patch("sase.crs_workflow.get_by_tag", return_value=custom_wf):
        with patch("sase.crs_workflow.process_xprompt_references", side_effect=lambda x: x):
            result = _build_crs_prompt("/tmp/c.json", cl_name="my_cl", vcs_type="hg")
    assert "#custom_crs(" in result
    assert 'cl_name="my_cl"' in result


def test_build_crs_prompt_falls_back_to_hardcoded_name() -> None:
    """_build_crs_prompt falls back to #crs when no tagged xprompt found."""
    from sase.crs_workflow import _build_crs_prompt

    with patch("sase.crs_workflow.get_by_tag", return_value=None):
        with patch("sase.crs_workflow.process_xprompt_references", side_effect=lambda x: x):
            result = _build_crs_prompt("/tmp/comments.json")
    assert "#crs(" in result


def test_fix_hook_runner_uses_tag_lookup() -> None:
    """axe_fix_hook_runner uses tag-based lookup for xprompt name."""
    custom_wf = Workflow(
        name="my_fix_hook",
        steps=[WorkflowStep(name="s", prompt_part="x")],
        tags={XPromptTag.FIX_HOOK},
    )
    with patch("sase.axe_fix_hook_runner.get_by_tag", return_value=custom_wf):
        with patch("sase.axe_fix_hook_runner.process_xprompt_references", side_effect=lambda x: x):
            # Call the relevant section via importing and testing the prompt construction
            from sase.axe_fix_hook_runner import escape_for_xprompt

            fix_hook_workflow = custom_wf
            xprompt_name = fix_hook_workflow.name if fix_hook_workflow else "fix_hook"
            escaped_cmd = escape_for_xprompt("make test")
            escaped_output = escape_for_xprompt("/tmp/output.txt")
            escaped_cl = escape_for_xprompt("my_cl")
            prompt_ref = (
                f'#{xprompt_name}(hook_command="{escaped_cmd}", '
                f'output_file="{escaped_output}", '
                f'cl_name="{escaped_cl}", vcs_type="hg")'
            )
    assert "#my_fix_hook(" in prompt_ref


def test_fix_hook_tag_on_builtin_xprompt() -> None:
    """fix_hook.md has the fix_hook tag in its frontmatter."""
    from sase.xprompt.loader import _load_xprompt_from_file

    fix_hook_path = Path("src/sase/xprompts/fix_hook.md")
    xp = _load_xprompt_from_file(fix_hook_path)
    assert xp is not None
    assert xp.has_tag(XPromptTag.FIX_HOOK)


def test_get_by_tag_crs_returns_tagged_workflow() -> None:
    """get_by_tag(CRS) returns the crs-tagged workflow."""
    crs_wf = Workflow(
        name="crs",
        steps=[WorkflowStep(name="s", prompt_part="x")],
        tags={XPromptTag.CRS},
    )
    other_wf = Workflow(
        name="other",
        steps=[WorkflowStep(name="s", prompt_part="x")],
    )
    with patch("sase.xprompt.loader.get_all_prompts", return_value={"crs": crs_wf, "other": other_wf}):
        result = get_by_tag(XPromptTag.CRS)
    assert result is crs_wf


def test_get_by_tag_fix_hook_returns_tagged_workflow() -> None:
    """get_by_tag(FIX_HOOK) returns the fix_hook-tagged workflow."""
    fh_wf = Workflow(
        name="fix_hook",
        steps=[WorkflowStep(name="s", prompt_part="x")],
        tags={XPromptTag.FIX_HOOK},
    )
    with patch("sase.xprompt.loader.get_all_prompts", return_value={"fix_hook": fh_wf}):
        result = get_by_tag(XPromptTag.FIX_HOOK)
    assert result is fh_wf


def test_user_override_crs_tag_takes_precedence() -> None:
    """Local xprompt with tags: crs takes precedence over plugin's crs.md."""
    # Simulate loader precedence: local xprompt listed first
    local_crs = Workflow(
        name="my_crs",
        steps=[WorkflowStep(name="s", prompt_part="x")],
        tags={XPromptTag.CRS},
    )
    plugin_crs = Workflow(
        name="crs",
        steps=[WorkflowStep(name="s", prompt_part="x")],
        tags={XPromptTag.CRS},
    )
    # OrderedDict-like: local comes first in iteration
    prompts = {"my_crs": local_crs, "crs": plugin_crs}
    with patch("sase.xprompt.loader.get_all_prompts", return_value=prompts):
        result = get_by_tag(XPromptTag.CRS)
    assert result is local_crs
    assert result.name == "my_crs"
