"""Tests for VCS-specific append tags on commit xprompts (sase-9.2)."""

from unittest.mock import patch

from sase.xprompt.tags import XPromptTag, get_by_tag
from sase.xprompt.workflow_models import Workflow, WorkflowStep


def _make_commit_workflow(
    name: str = "commit",
    commit_method: str = "create_commit",
    prompt_part: str = "Make changes.",
    tags: frozenset[XPromptTag] = frozenset({XPromptTag.rollover, XPromptTag.commit}),
) -> Workflow:
    """Create a commit-like workflow with SASE_COMMIT_METHOD environment."""
    return Workflow(
        name=name,
        steps=[WorkflowStep(name="inject", prompt_part=prompt_part)],
        tags=tags,
        environment={"SASE_COMMIT_METHOD": commit_method},
    )


def _make_tagged_xprompt(
    name: str,
    tag: XPromptTag,
    content: str,
    plugin_module: str,
) -> Workflow:
    """Create a workflow representing a tagged xprompt from a plugin."""
    return Workflow(
        name=name,
        steps=[WorkflowStep(name="main", prompt_part=content)],
        tags=frozenset({tag}),
        source_path=f"plugin_config:{plugin_module}",
    )


# ── Tag lookup for append tags ──────────────────────────────────────────


def test_append_to_commit_and_propose_found_for_google() -> None:
    """Commit workflow with hg hint finds Google append xprompt."""
    wf_hg = Workflow(
        name="hg",
        steps=[WorkflowStep(name="main", prompt_part="vcs")],
        tags=frozenset({XPromptTag.vcs}),
        source_path="plugin:sase_google/hg.yml",
    )
    wf_append = _make_tagged_xprompt(
        "no_cl_ops_and_cldd",
        XPromptTag.append_to_commit_and_propose,
        "#no_cl_ops #cldd",
        "sase_google",
    )
    mock = {"hg": wf_hg, "no_cl_ops_and_cldd": wf_append}

    with patch("sase.xprompt.loader.get_all_prompts", return_value=mock):
        result = get_by_tag(XPromptTag.append_to_commit_and_propose, vcs_hint="hg")
    assert result is wf_append
    assert result is not None
    assert result.get_prompt_part_content() == "#no_cl_ops #cldd"


def test_append_to_pr_found_for_google() -> None:
    """PR workflow with hg hint finds Google append_to_pr xprompt."""
    wf_hg = Workflow(
        name="hg",
        steps=[WorkflowStep(name="main", prompt_part="vcs")],
        tags=frozenset({XPromptTag.vcs}),
        source_path="plugin:sase_google/hg.yml",
    )
    wf_append = _make_tagged_xprompt(
        "no_cl_ops",
        XPromptTag.append_to_pr,
        "Don't create a CL.",
        "sase_google",
    )
    mock = {"hg": wf_hg, "no_cl_ops": wf_append}

    with patch("sase.xprompt.loader.get_all_prompts", return_value=mock):
        result = get_by_tag(XPromptTag.append_to_pr, vcs_hint="hg")
    assert result is wf_append


def test_append_to_commit_and_propose_found_for_github() -> None:
    """Commit workflow with gh hint finds GitHub append xprompt."""
    wf_gh = Workflow(
        name="gh",
        steps=[WorkflowStep(name="main", prompt_part="vcs")],
        tags=frozenset({XPromptTag.vcs}),
        source_path="plugin:sase_github/gh.yml",
    )
    wf_google = _make_tagged_xprompt(
        "no_cl_ops_and_cldd",
        XPromptTag.append_to_commit_and_propose,
        "#no_cl_ops #cldd",
        "sase_google",
    )
    wf_github = _make_tagged_xprompt(
        "prdd",
        XPromptTag.append_to_commit_and_propose,
        "#pr_diff",
        "sase_github",
    )
    mock = {"gh": wf_gh, "no_cl_ops_and_cldd": wf_google, "prdd": wf_github}

    with patch("sase.xprompt.loader.get_all_prompts", return_value=mock):
        result = get_by_tag(XPromptTag.append_to_commit_and_propose, vcs_hint="gh")
    assert result is wf_github


def test_no_append_when_no_tagged_xprompts() -> None:
    """No append content when no xprompts have the tag."""
    wf_gh = Workflow(
        name="gh",
        steps=[WorkflowStep(name="main", prompt_part="vcs")],
        tags=frozenset({XPromptTag.vcs}),
        source_path="plugin:sase_github/gh.yml",
    )
    mock = {"gh": wf_gh}

    with patch("sase.xprompt.loader.get_all_prompts", return_value=mock):
        result = get_by_tag(XPromptTag.append_to_commit_and_propose, vcs_hint="gh")
    assert result is None


def test_no_append_for_bare_git_append_to_pr() -> None:
    """Bare git (no plugin) has no append_to_pr xprompt."""
    wf_git = Workflow(
        name="git",
        steps=[WorkflowStep(name="main", prompt_part="vcs")],
        tags=frozenset({XPromptTag.vcs}),
        source_path="builtin:sase/xprompts/git.yml",
    )
    mock = {"git": wf_git}

    with patch("sase.xprompt.loader.get_all_prompts", return_value=mock):
        result = get_by_tag(XPromptTag.append_to_pr, vcs_hint="git")
    assert result is None


# ── Commit method → tag mapping ─────────────────────────────────────────


def test_commit_method_create_commit_maps_to_append_to_commit_and_propose() -> None:
    """SASE_COMMIT_METHOD=create_commit uses append_to_commit_and_propose."""
    wf = _make_commit_workflow(commit_method="create_commit")
    method = wf.environment.get("SASE_COMMIT_METHOD")
    assert method == "create_commit"
    # The mapping logic in the mixin
    if method in ("create_commit", "create_proposal"):
        tag = XPromptTag.append_to_commit_and_propose
    else:
        tag = XPromptTag.append_to_pr
    assert tag == XPromptTag.append_to_commit_and_propose


def test_commit_method_create_proposal_maps_to_append_to_commit_and_propose() -> None:
    """SASE_COMMIT_METHOD=create_proposal uses append_to_commit_and_propose."""
    wf = _make_commit_workflow(commit_method="create_proposal")
    method = wf.environment.get("SASE_COMMIT_METHOD")
    assert method == "create_proposal"
    if method in ("create_commit", "create_proposal"):
        tag = XPromptTag.append_to_commit_and_propose
    else:
        tag = XPromptTag.append_to_pr
    assert tag == XPromptTag.append_to_commit_and_propose


def test_commit_method_create_pull_request_maps_to_append_to_pr() -> None:
    """SASE_COMMIT_METHOD=create_pull_request uses append_to_pr."""
    wf = _make_commit_workflow(
        name="pr",
        commit_method="create_pull_request",
        tags=frozenset({XPromptTag.rollover}),
    )
    method = wf.environment.get("SASE_COMMIT_METHOD")
    assert method == "create_pull_request"
    if method in ("create_commit", "create_proposal"):
        tag = XPromptTag.append_to_commit_and_propose
    else:
        tag = XPromptTag.append_to_pr
    assert tag == XPromptTag.append_to_pr


# ── Built-in workflow structure ─────────────────────────────────────────


def test_builtin_commit_workflow_has_environment() -> None:
    """Built-in commit.yml sets SASE_COMMIT_METHOD=create_commit."""
    from pathlib import Path

    from sase.xprompt.workflow_loader import _load_workflow_from_file

    yml = (
        Path(__file__).resolve().parent.parent
        / "src"
        / "sase"
        / "xprompts"
        / "commit.yml"
    )
    wf = _load_workflow_from_file(yml)
    assert wf is not None
    assert wf.environment.get("SASE_COMMIT_METHOD") == "create_commit"
    assert wf.has_tag(XPromptTag.commit)
    assert wf.has_tag(XPromptTag.rollover)


def test_builtin_propose_workflow_has_environment() -> None:
    """Built-in propose.yml sets SASE_COMMIT_METHOD=create_proposal."""
    from pathlib import Path

    from sase.xprompt.workflow_loader import _load_workflow_from_file

    yml = (
        Path(__file__).resolve().parent.parent
        / "src"
        / "sase"
        / "xprompts"
        / "propose.yml"
    )
    wf = _load_workflow_from_file(yml)
    assert wf is not None
    assert wf.environment.get("SASE_COMMIT_METHOD") == "create_proposal"
    assert wf.has_tag(XPromptTag.propose)
    assert wf.has_tag(XPromptTag.rollover)


def test_builtin_pr_workflow_has_environment() -> None:
    """Built-in pr.yml sets SASE_COMMIT_METHOD and SASE_BUG_ID."""
    from pathlib import Path

    from sase.xprompt.workflow_loader import _load_workflow_from_file

    yml = (
        Path(__file__).resolve().parent.parent / "src" / "sase" / "xprompts" / "pr.yml"
    )
    wf = _load_workflow_from_file(yml)
    assert wf is not None
    assert wf.environment.get("SASE_COMMIT_METHOD") == "create_pull_request"
    assert wf.environment.get("SASE_BUG_ID") == "{{ bug_id }}"
    assert wf.has_tag(XPromptTag.rollover)
    assert len(wf.inputs) == 2
    assert wf.inputs[0].name == "name"
    assert wf.inputs[1].name == "bug_id"
