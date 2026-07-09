"""Tests for unresolved xprompt-reference diagnostics."""

from __future__ import annotations

import re
from unittest.mock import patch

import pytest

from sase.xprompt.models import XPrompt
from sase.xprompt.unresolved import (
    find_unresolved_reference_names,
    scan_query_for_unresolved_references,
)
from sase.xprompt.workflow_models import Workflow, WorkflowStep


def _workflow(name: str) -> Workflow:
    return Workflow(name=name, steps=[WorkflowStep(name="main", prompt_part="body")])


@pytest.fixture(autouse=True)
def _stable_unresolved_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.project_aliases.canonicalize_project_aliases_in_prompt",
        lambda prompt, *args, **kwargs: prompt,
    )
    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: {"xprompt_aliases": {}},
    )
    monkeypatch.setattr(
        "sase.workspace_provider.get_workflow_names",
        lambda: {"git"},
    )
    monkeypatch.setattr(
        "sase.workspace_provider.get_ref_patterns",
        lambda: {
            "git": re.compile(r"(?:^|(?<=\s))#git(?:[_:]([^\s]+)|\(([^)]*)\))"),
        },
    )
    monkeypatch.setattr(
        "sase.xprompt.loader.get_known_project_workspaces",
        lambda *args, **kwargs: {},
    )


def test_unknown_names_are_deduped_in_first_seen_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.xprompt.loader.get_all_prompts", lambda: {})

    assert find_unresolved_reference_names("#missing #other #missing") == (
        "missing",
        "other",
    )


def test_known_global_workflow_and_local_xprompt_are_not_flagged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.xprompt.loader.get_all_prompts",
        lambda: {"review": _workflow("review"), "ship": _workflow("ship")},
    )
    local = {"_helper": XPrompt(name="_helper", content="local")}

    assert find_unresolved_reference_names(
        "#review #!ship #_helper #typo",
        extra_xprompts=local,
    ) == ("typo",)


def test_alias_resolved_name_is_not_flagged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: {"xprompt_aliases": {"rvw": "review"}},
    )
    monkeypatch.setattr(
        "sase.xprompt.loader.get_all_prompts",
        lambda: {"review": _workflow("review")},
    )

    assert find_unresolved_reference_names("#rvw") == ()


def test_vcs_and_resume_references_are_not_flagged_but_removed_cd_is(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.xprompt.loader.get_all_prompts", lambda: {})

    removed_ref = "#" + "cd:/tmp"
    assert find_unresolved_reference_names(
        f"#git:sase {removed_ref} #fork #resume:abc"
    ) == ("cd",)


def test_fenced_disabled_numeric_and_midword_hashes_are_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.xprompt.loader.get_all_prompts", lambda: {})

    prompt = (
        "```\n#inside\n```\n"
        "%xprompts_enabled:false\n#disabled\n%xprompts_enabled:true\n"
        "#123 https://example.test/page#anchor #real"
    )

    assert find_unresolved_reference_names(prompt) == ("real",)


def test_scan_query_expands_local_xprompts_before_scanning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.xprompt.loader.get_all_prompts", lambda: {})
    monkeypatch.setattr("sase.xprompt.processor.get_all_xprompts", lambda: {})

    query = "---\nxprompts:\n  _local: local body\n---\n#_local #missing"

    assert scan_query_for_unresolved_references(query) == ("missing",)


def test_scan_query_is_exception_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(_query: str) -> object:
        raise SystemExit(2)

    monkeypatch.setattr("sase.agent.multi_prompt.parse_multi_prompt", fail)

    assert scan_query_for_unresolved_references("#missing") == ()
