"""Tests for get_by_tag, get_by_tag_strict, _extract_plugin_module, and VCS hint."""

from unittest.mock import patch

import pytest

from sase.xprompt.tags import (
    XPromptTag,
    _extract_plugin_module,
    get_by_tag,
    get_by_tag_strict,
)
from sase.xprompt.workflow_models import Workflow, WorkflowStep


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


# ── _extract_plugin_module ────────────────────────────────────────────


def test_extract_plugin_module_none() -> None:
    assert _extract_plugin_module(None) is None


def test_extract_plugin_module_empty() -> None:
    assert _extract_plugin_module("") is None


def test_extract_plugin_module_plugin_workflow() -> None:
    assert _extract_plugin_module("plugin:sase_github/gh.yml") == "sase_github"


def test_extract_plugin_module_plugin_config() -> None:
    assert _extract_plugin_module("plugin_config:sase_google") == "sase_google"


def test_extract_plugin_module_builtin() -> None:
    assert _extract_plugin_module("builtin:sase/xprompts/pr_diff.md") is None


def test_extract_plugin_module_user() -> None:
    assert _extract_plugin_module("user:~/.config/sase/sase.yml") is None


# ── get_by_tag with vcs_hint ─────────────────────────────────────────


def test_get_by_tag_vcs_hint_disambiguates() -> None:
    """When two xprompts share diff_file tag, vcs_hint picks the right one."""
    wf_gh = Workflow(
        name="gh",
        steps=[WorkflowStep(name="main", prompt_part="github vcs")],
        tags=frozenset({XPromptTag.vcs}),
        source_path="plugin:sase_github/gh.yml",
    )
    wf_pr_diff = Workflow(
        name="pr_diff",
        steps=[WorkflowStep(name="main", prompt_part="pr diff")],
        tags=frozenset({XPromptTag.diff_file}),
        source_path="plugin_config:sase_github",
    )
    wf_cl_diff = Workflow(
        name="cl_diff",
        steps=[WorkflowStep(name="main", prompt_part="cl diff")],
        tags=frozenset({XPromptTag.diff_file}),
        source_path="plugin_config:sase_google",
    )
    mock_prompts = {
        "gh": wf_gh,
        "pr_diff": wf_pr_diff,
        "cl_diff": wf_cl_diff,
    }

    with patch("sase.xprompt.loader.get_all_prompts", return_value=mock_prompts):
        result = get_by_tag(XPromptTag.diff_file, vcs_hint="gh")
    assert result is wf_pr_diff


def test_get_by_tag_vcs_hint_picks_google() -> None:
    """vcs_hint='hg' picks the sase_google diff xprompt."""
    wf_hg = Workflow(
        name="hg",
        steps=[WorkflowStep(name="main", prompt_part="hg vcs")],
        tags=frozenset({XPromptTag.vcs}),
        source_path="plugin:sase_google/hg.yml",
    )
    wf_pr_diff = Workflow(
        name="pr_diff",
        steps=[WorkflowStep(name="main", prompt_part="pr diff")],
        tags=frozenset({XPromptTag.diff_file}),
        source_path="plugin_config:sase_github",
    )
    wf_cl_diff = Workflow(
        name="cl_diff",
        steps=[WorkflowStep(name="main", prompt_part="cl diff")],
        tags=frozenset({XPromptTag.diff_file}),
        source_path="plugin_config:sase_google",
    )
    mock_prompts = {
        "hg": wf_hg,
        "pr_diff": wf_pr_diff,
        "cl_diff": wf_cl_diff,
    }

    with patch("sase.xprompt.loader.get_all_prompts", return_value=mock_prompts):
        result = get_by_tag(XPromptTag.diff_file, vcs_hint="hg")
    assert result is wf_cl_diff


def test_get_by_tag_no_vcs_hint_returns_last() -> None:
    """Without vcs_hint, last-wins behavior is preserved."""
    wf_pr_diff = Workflow(
        name="pr_diff",
        steps=[WorkflowStep(name="main", prompt_part="pr diff")],
        tags=frozenset({XPromptTag.diff_file}),
        source_path="plugin_config:sase_github",
    )
    wf_cl_diff = Workflow(
        name="cl_diff",
        steps=[WorkflowStep(name="main", prompt_part="cl diff")],
        tags=frozenset({XPromptTag.diff_file}),
        source_path="plugin_config:sase_google",
    )
    mock_prompts = {"pr_diff": wf_pr_diff, "cl_diff": wf_cl_diff}

    with patch("sase.xprompt.loader.get_all_prompts", return_value=mock_prompts):
        result = get_by_tag(XPromptTag.diff_file)
    assert result is wf_cl_diff


def test_get_by_tag_vcs_hint_unknown_workflow_falls_back() -> None:
    """If vcs_hint names an unknown workflow, fall back to last-wins."""
    wf_pr_diff = Workflow(
        name="pr_diff",
        steps=[WorkflowStep(name="main", prompt_part="pr diff")],
        tags=frozenset({XPromptTag.diff_file}),
        source_path="plugin_config:sase_github",
    )
    wf_cl_diff = Workflow(
        name="cl_diff",
        steps=[WorkflowStep(name="main", prompt_part="cl diff")],
        tags=frozenset({XPromptTag.diff_file}),
        source_path="plugin_config:sase_google",
    )
    mock_prompts = {"pr_diff": wf_pr_diff, "cl_diff": wf_cl_diff}

    with patch("sase.xprompt.loader.get_all_prompts", return_value=mock_prompts):
        result = get_by_tag(XPromptTag.diff_file, vcs_hint="svn")
    assert result is wf_cl_diff


def test_get_by_tag_vcs_hint_no_module_match_falls_back() -> None:
    """If vcs_hint workflow has no plugin module, fall back to last-wins."""
    wf_custom_vcs = Workflow(
        name="custom",
        steps=[WorkflowStep(name="main", prompt_part="custom vcs")],
        tags=frozenset({XPromptTag.vcs}),
        source_path="user:~/.config/sase/sase.yml",
    )
    wf_pr_diff = Workflow(
        name="pr_diff",
        steps=[WorkflowStep(name="main", prompt_part="pr diff")],
        tags=frozenset({XPromptTag.diff_file}),
        source_path="plugin_config:sase_github",
    )
    wf_cl_diff = Workflow(
        name="cl_diff",
        steps=[WorkflowStep(name="main", prompt_part="cl diff")],
        tags=frozenset({XPromptTag.diff_file}),
        source_path="plugin_config:sase_google",
    )
    mock_prompts = {
        "custom": wf_custom_vcs,
        "pr_diff": wf_pr_diff,
        "cl_diff": wf_cl_diff,
    }

    with patch("sase.xprompt.loader.get_all_prompts", return_value=mock_prompts):
        result = get_by_tag(XPromptTag.diff_file, vcs_hint="custom")
    assert result is wf_cl_diff


def test_get_by_tag_single_match_ignores_vcs_hint() -> None:
    """With only one match, vcs_hint doesn't change anything."""
    wf_gh = Workflow(
        name="gh",
        steps=[WorkflowStep(name="main", prompt_part="github vcs")],
        tags=frozenset({XPromptTag.vcs}),
        source_path="plugin:sase_github/gh.yml",
    )
    wf_pr_diff = Workflow(
        name="pr_diff",
        steps=[WorkflowStep(name="main", prompt_part="pr diff")],
        tags=frozenset({XPromptTag.diff_file}),
        source_path="plugin_config:sase_github",
    )
    mock_prompts = {"gh": wf_gh, "pr_diff": wf_pr_diff}

    with patch("sase.xprompt.loader.get_all_prompts", return_value=mock_prompts):
        result = get_by_tag(XPromptTag.diff_file, vcs_hint="gh")
    assert result is wf_pr_diff


# ── Append tag lookup ──────────────────────────────────────────────────


def test_get_by_tag_append_to_pr_vcs_disambiguates() -> None:
    """append_to_pr tag with vcs_hint picks the right VCS plugin xprompt."""
    wf_hg = Workflow(
        name="hg",
        steps=[WorkflowStep(name="main", prompt_part="hg vcs")],
        tags=frozenset({XPromptTag.vcs}),
        source_path="plugin:sase_google/hg.yml",
    )
    wf_no_cl_ops = Workflow(
        name="no_cl_ops",
        steps=[WorkflowStep(name="main", prompt_part="no cl ops")],
        tags=frozenset({XPromptTag.append_to_pr}),
        source_path="plugin_config:sase_google",
    )
    mock_prompts = {"hg": wf_hg, "no_cl_ops": wf_no_cl_ops}

    with patch("sase.xprompt.loader.get_all_prompts", return_value=mock_prompts):
        result = get_by_tag(XPromptTag.append_to_pr, vcs_hint="hg")
    assert result is wf_no_cl_ops


def test_get_by_tag_append_to_commit_and_propose_vcs_disambiguates() -> None:
    """append_to_commit_and_propose uses VCS-aware disambiguation."""
    wf_gh = Workflow(
        name="gh",
        steps=[WorkflowStep(name="main", prompt_part="github vcs")],
        tags=frozenset({XPromptTag.vcs}),
        source_path="plugin:sase_github/gh.yml",
    )
    wf_google_append = Workflow(
        name="no_cl_ops_and_cldd",
        steps=[WorkflowStep(name="main", prompt_part="#no_cl_ops #cldd")],
        tags=frozenset({XPromptTag.append_to_commit_and_propose}),
        source_path="plugin_config:sase_google",
    )
    wf_github_append = Workflow(
        name="prdd",
        steps=[WorkflowStep(name="main", prompt_part="#pr_diff")],
        tags=frozenset({XPromptTag.append_to_commit_and_propose}),
        source_path="plugin_config:sase_github",
    )
    mock_prompts = {
        "gh": wf_gh,
        "no_cl_ops_and_cldd": wf_google_append,
        "prdd": wf_github_append,
    }

    with patch("sase.xprompt.loader.get_all_prompts", return_value=mock_prompts):
        result = get_by_tag(XPromptTag.append_to_commit_and_propose, vcs_hint="gh")
    assert result is wf_github_append


def test_get_by_tag_append_to_commit_and_propose_picks_google() -> None:
    """append_to_commit_and_propose with hg vcs_hint picks Google plugin."""
    wf_hg = Workflow(
        name="hg",
        steps=[WorkflowStep(name="main", prompt_part="hg vcs")],
        tags=frozenset({XPromptTag.vcs}),
        source_path="plugin:sase_google/hg.yml",
    )
    wf_google_append = Workflow(
        name="no_cl_ops_and_cldd",
        steps=[WorkflowStep(name="main", prompt_part="#no_cl_ops #cldd")],
        tags=frozenset({XPromptTag.append_to_commit_and_propose}),
        source_path="plugin_config:sase_google",
    )
    wf_github_append = Workflow(
        name="prdd",
        steps=[WorkflowStep(name="main", prompt_part="#pr_diff")],
        tags=frozenset({XPromptTag.append_to_commit_and_propose}),
        source_path="plugin_config:sase_github",
    )
    mock_prompts = {
        "hg": wf_hg,
        "no_cl_ops_and_cldd": wf_google_append,
        "prdd": wf_github_append,
    }

    with patch("sase.xprompt.loader.get_all_prompts", return_value=mock_prompts):
        result = get_by_tag(XPromptTag.append_to_commit_and_propose, vcs_hint="hg")
    assert result is wf_google_append


def test_get_by_tag_append_no_match_returns_none() -> None:
    """append_to_pr returns None when no xprompts have the tag."""
    wf_gh = Workflow(
        name="gh",
        steps=[WorkflowStep(name="main", prompt_part="github vcs")],
        tags=frozenset({XPromptTag.vcs}),
        source_path="plugin:sase_github/gh.yml",
    )
    mock_prompts = {"gh": wf_gh}

    with patch("sase.xprompt.loader.get_all_prompts", return_value=mock_prompts):
        result = get_by_tag(XPromptTag.append_to_pr, vcs_hint="gh")
    assert result is None
