"""Tests asserting shipped skill sources keep their documented guidance."""

from __future__ import annotations

import re

import pytest

from sase.xprompt.loader import get_sase_package_skills_dir
from sase.xprompt.loader_parsing import parse_yaml_front_matter
from tests.main.init_skills_handler_helpers import collapse_whitespace


def test_gate_skill_sources_do_not_reference_v1_contract() -> None:
    """Generated gate guidance must use the query-driven v2 interface."""
    skills_dir = get_sase_package_skills_dir()

    for skill_name in ("sase_gate", "sase_notify", "sase_run"):
        body = (skills_dir / f"{skill_name}.md").read_text(encoding="utf-8")
        for stale_phrase in (
            "sase notify create --gate",
            "sase notify wait",
            "choice_id",
            "selected_extra_ids",
        ):
            assert stale_phrase not in body


def test_sase_plan_skill_does_not_expose_internal_model_aliases() -> None:
    """Planning guidance describes behavior without exposing routing internals."""
    src = get_sase_package_skills_dir() / "sase_plan.md"
    body = src.read_text(encoding="utf-8")

    for internal_name in (
        "worker",
        "cheap",
        "cheaper",
        "cheapest",
        "smart",
        "smartest",
        "xsmall_worker",
        "small_worker",
        "medium_worker",
        "large_worker",
        "xlarge_worker",
    ):
        assert internal_name not in body


def test_sase_repo_skill_description_covers_web_fetches() -> None:
    """The always-visible skill trigger closes the repository web-fetch loophole."""
    src = get_sase_package_skills_dir() / "sase_repo.md"
    front_matter, _body = parse_yaml_front_matter(src.read_text(encoding="utf-8"))

    assert front_matter is not None
    description = str(front_matter.get("description", ""))
    assert "web-fetching a repo's files or history" in description
    assert "raw.githubusercontent.com" in description
    assert "GitHub API" in description


@pytest.mark.parametrize("skill_name", ["sase_git_commit", "sase_hg_commit"])
def test_commit_skill_sources_do_not_reference_legacy_bead_flag(
    skill_name: str,
) -> None:
    """Commit skills should rely on SASE_BEAD_ID rather than a commit flag."""
    src = get_sase_package_skills_dir() / f"{skill_name}.md"
    body = src.read_text(encoding="utf-8")
    assert "--bead-id" not in body
    assert "sase bead list --status=in_progress" not in body


def test_sase_new_task_duplicate_detection_stays_query_scoped() -> None:
    """Duplicate detection permits only search, a bounded sweep, and epic lists."""
    src = get_sase_package_skills_dir() / "sase_new_task.md"
    front_matter, body = parse_yaml_front_matter(src.read_text(encoding="utf-8"))
    flat = collapse_whitespace(body)

    assert front_matter is not None
    assert (
        "sase bead search 'symbol|filename|command|error-fragment' --regex --type task"
        in flat
    )
    assert re.search(r"sase bead list --type task(?! --since)", flat) is None
    assert re.search(r"sase bead list --type task[^`]*--format full", flat) is None
    assert "sase bead list --type plan --tier epic" in flat
    assert "sase flag new <key>" in flat


def test_sase_new_task_retired_umbrella_routes_to_related_task() -> None:
    """Retired umbrella tasks should not keep receiving corroborating ``+1`` reports."""
    src = get_sase_package_skills_dir() / "sase_new_task.md"
    front_matter, body = parse_yaml_front_matter(src.read_text(encoding="utf-8"))
    flat = collapse_whitespace(body)

    assert front_matter is not None
    assert "retired umbrella" in flat
    assert "closed task whose close reason declares it retired and forbids `+1`" in flat
    assert "Do not `+1` or reopen them" in flat
    assert "Route the report to step 7 instead" in flat
    assert "node-specific task bead named for the failing node ID" in flat
    assert 'sase bead note <new-task-id> "RELATED: <retired-task-id>' in flat


def test_git_commit_skill_invokes_observable_wrapper() -> None:
    """The git commit skill should call the wrapper, not raw ``sase commit``."""
    src = get_sase_package_skills_dir() / "sase_git_commit.md"
    body = src.read_text(encoding="utf-8")
    flat = collapse_whitespace(body)
    assert "Commit changes via the `sase_git_commit` wrapper" in flat
    assert "records skill invocation evidence" in flat
    assert "sase_git_commit -M .sase/commit_message.md" in body
    assert "Repo-relative path (file or directory) to leave out of this commit" in body
    assert "fails loudly rather than quietly committing a mistyped path" in body
    assert "deleted only after a successful commit" in body
    assert "Do not preemptively stash, fast-forward, pull, or hand-sync" in body
    assert "`2`: A rebase is paused for a real conflict" in body
    assert "sase_git_commit --resume" in body
    assert "git-ignored" in body
    assert "delegates to `sase stitch create`" in body
    assert "sase commit -M" not in body
    assert "-M commit_message.md" not in body
    assert "sase commit --resume" not in body
    assert "sase commit" not in body
    assert "sase stitch create -M" not in body
