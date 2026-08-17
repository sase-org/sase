"""Regression coverage for the retired Mercurial workspace workflow."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.history.prompt_metadata import summarize_prompt_for_list
from sase.project_aliases import canonicalize_project_aliases_in_prompt
from sase.workspace_provider import get_ref_patterns, get_workflow_names
from sase.xprompt._parsing_vcs_refs import (
    iter_known_project_vcs_refs,
    normalize_launch_xprompt_at_refs,
)
from sase.xprompt.processor import prompt_may_reference_xprompt
from tests._workspace_provider_helpers import (
    patch_no_workspace_metadata,
    patch_spy_metadata,
)


def _retired_workflow_name() -> str:
    """Build the retired name without restoring its literal prompt token."""
    return "".join(("h", "g"))


def test_retired_workflow_has_no_core_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_no_workspace_metadata(monkeypatch)
    workflow = _retired_workflow_name()
    prompt = f"#{workflow}:sase"
    known_projects = {"sase": Path("/tmp/sase")}
    monkeypatch.setattr(
        "sase.project_aliases.load_project_alias_map",
        lambda projects_root=None: {"sase": "canonical-sase"},
    )
    monkeypatch.setattr(
        "sase.xprompt.loader.get_known_project_workspaces",
        lambda: known_projects,
    )

    assert workflow not in get_workflow_names()
    assert workflow not in get_ref_patterns()
    assert iter_known_project_vcs_refs(prompt, known_projects) == []
    assert normalize_launch_xprompt_at_refs(f"#{workflow}@sase") == f"#{workflow}@sase"
    assert canonicalize_project_aliases_in_prompt(prompt) == prompt
    assert prompt_may_reference_xprompt(prompt) is True

    summary = summarize_prompt_for_list(prompt)
    assert summary.project_prefix == ""
    assert summary.project_ref_display == ""


def test_registered_fake_provider_uses_generic_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_spy_metadata(monkeypatch)
    prompt = "#spy:sase Fix it"
    known_projects = {"sase": Path("/tmp/sase")}
    monkeypatch.setattr(
        "sase.project_aliases.load_project_alias_map",
        lambda projects_root=None: {"sase": "canonical-sase"},
    )

    assert "spy" in get_workflow_names()
    assert "spy" in get_ref_patterns()
    assert iter_known_project_vcs_refs(prompt, known_projects) == [("spy", "sase")]
    assert normalize_launch_xprompt_at_refs("#spy@sase") == "#spy:sase"
    assert (
        canonicalize_project_aliases_in_prompt(prompt) == "#spy:canonical-sase Fix it"
    )

    summary = summarize_prompt_for_list(prompt)
    assert summary.project_prefix == "spy:"
    assert summary.project_ref_display == "sase"
