"""Tests for canonicalizing and humanizing project refs in prompts."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.project_aliases import (
    canonicalize_project_aliases_in_prompt,
    humanize_project_refs_in_prompt,
)
from tests._project_alias_services_helpers import _record
from tests.main.project_handler_helpers import (
    _write_project,
    projects_root,
)

__all__ = ["projects_root"]


def test_canonicalize_leaves_provider_mismatched_ref_untouched(
    projects_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A #git: tag aimed at a GitHub project must not canonicalize.

    Rewriting it to the real spec key would let a downstream bare-git
    resolver silently convert that project's ProjectSpec (the
    ``bare_git_project_clobber`` bug). #gh: (the tag matching the project's
    actual provider) must still canonicalize normally.
    """
    sase_file = _write_project(
        projects_root,
        "gh_sase-org__sase",
        "PROJECT_ALIASES: sase\nWORKSPACE_DIR: /tmp/sase\nNAME: b\n",
    )
    monkeypatch.setattr(
        "sase.project_aliases.list_project_records",
        lambda *_args, **_kwargs: [
            _record(
                "gh_sase-org__sase",
                aliases=["sase"],
                project_file=sase_file,
            ),
        ],
    )
    monkeypatch.setattr(
        "sase.project_aliases._project_workflow_type",
        lambda project: "gh" if project == "gh_sase-org__sase" else None,
    )

    assert canonicalize_project_aliases_in_prompt("#git:sase fix") == "#git:sase fix"
    assert canonicalize_project_aliases_in_prompt("#gh:sase fix") == (
        "#gh:gh_sase-org__sase fix"
    )


def test_canonicalize_project_aliases_caches_project_lookups_until_spec_changes(
    projects_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase import project_alias_prompts

    with project_alias_prompts._PROJECT_LOOKUP_CACHE_LOCK:
        project_alias_prompts._WORKFLOW_TYPE_CACHE.clear()
        project_alias_prompts._CHANGESPEC_NAMES_CACHE.clear()
    project = "gh_sase-org__sase"
    project_file = _write_project(
        projects_root,
        project,
        "PROJECT_ALIASES: sase\nWORKSPACE_DIR: /tmp/sase\nNAME: existing\n",
    )
    monkeypatch.setattr("sase.project_aliases.sase_projects_dir", lambda: projects_root)
    monkeypatch.setattr(
        "sase.project_aliases.list_project_records",
        lambda *_args, **_kwargs: [
            _record(project, aliases=["sase"], project_file=project_file)
        ],
    )
    monkeypatch.setattr("sase.project_aliases._vcs_workflow_names", lambda: {"gh"})
    reads = {"changespec_names": 0, "workflow_type": 0}

    def load_changespec_names(project_name: str) -> frozenset[str]:
        assert project_name == project
        reads["changespec_names"] += 1
        project_file.read_text(encoding="utf-8")
        return frozenset({"sase_fix"})

    def project_workflow_type(project_name: str) -> str | None:
        assert project_name == project
        reads["workflow_type"] += 1
        project_file.read_text(encoding="utf-8")
        return "gh"

    monkeypatch.setattr(
        "sase.project_aliases._load_project_changespec_names",
        load_changespec_names,
    )
    monkeypatch.setattr(
        "sase.project_aliases._project_workflow_type",
        project_workflow_type,
    )
    prompt = "#gh:sase_fix review #gh:sase fix"
    expected = "#gh:sase_fix review #gh:gh_sase-org__sase fix"

    assert canonicalize_project_aliases_in_prompt(prompt) == expected
    assert reads == {"changespec_names": 1, "workflow_type": 1}
    assert canonicalize_project_aliases_in_prompt(prompt) == expected
    assert reads == {"changespec_names": 1, "workflow_type": 1}

    project_file.write_text(
        project_file.read_text(encoding="utf-8") + "# touch cache signature\n",
        encoding="utf-8",
    )

    assert canonicalize_project_aliases_in_prompt(prompt) == expected
    assert reads == {"changespec_names": 2, "workflow_type": 2}


def test_canonicalize_project_aliases_allows_fresh_lookup_bypass(
    projects_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase import project_alias_prompts

    with project_alias_prompts._PROJECT_LOOKUP_CACHE_LOCK:
        project_alias_prompts._WORKFLOW_TYPE_CACHE.clear()
        project_alias_prompts._CHANGESPEC_NAMES_CACHE.clear()
    project = "gh_sase-org__sase"
    project_file = _write_project(
        projects_root,
        project,
        "PROJECT_ALIASES: sase\nWORKSPACE_DIR: /tmp/sase\nNAME: existing\n",
    )
    monkeypatch.setattr("sase.project_aliases.sase_projects_dir", lambda: projects_root)
    monkeypatch.setattr(
        "sase.project_aliases.list_project_records",
        lambda *_args, **_kwargs: [
            _record(project, aliases=["sase"], project_file=project_file)
        ],
    )
    monkeypatch.setattr("sase.project_aliases._vcs_workflow_names", lambda: {"gh"})
    reads = {"changespec_names": 0, "workflow_type": 0}

    def load_changespec_names(project_name: str) -> frozenset[str]:
        assert project_name == project
        reads["changespec_names"] += 1
        project_file.read_text(encoding="utf-8")
        return frozenset({"sase_fix"})

    def project_workflow_type(project_name: str) -> str | None:
        assert project_name == project
        reads["workflow_type"] += 1
        project_file.read_text(encoding="utf-8")
        return "gh"

    monkeypatch.setattr(
        "sase.project_aliases._load_project_changespec_names",
        load_changespec_names,
    )
    monkeypatch.setattr(
        "sase.project_aliases._project_workflow_type",
        project_workflow_type,
    )
    prompt = "#gh:sase_fix review #gh:sase fix"

    assert canonicalize_project_aliases_in_prompt(prompt, use_cache=False)
    assert canonicalize_project_aliases_in_prompt(prompt, use_cache=False)
    assert reads == {"changespec_names": 2, "workflow_type": 2}


def test_humanize_project_refs_in_prompt_rewrites_only_vcs_refs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.project_aliases._vcs_workflow_names", lambda: {"gh"})

    prompt = (
        "#gh:gh_acme__widgets fix\n"
        "#gh(gh_acme__widgets) inspect\n"
        "path: /tmp/gh_acme__widgets/file\n"
        "```text\n#gh:gh_acme__widgets fenced\n```\n"
    )

    result = humanize_project_refs_in_prompt(
        prompt,
        {"gh_acme__widgets": "widgets"},
    )

    assert "#gh:widgets fix" in result
    assert "#gh(widgets) inspect" in result
    assert "path: /tmp/gh_acme__widgets/file" in result
    assert "#gh:gh_acme__widgets fenced" in result


def test_humanize_project_refs_in_prompt_rewrites_prefixed_refs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.project_aliases._vcs_workflow_names", lambda: {"gh"})

    result = humanize_project_refs_in_prompt(
        "#gh:gh_acme__widgets_fix_1 fix",
        {"gh_acme__widgets": "widgets"},
    )

    assert result == "#gh:widgets_fix_1 fix"
