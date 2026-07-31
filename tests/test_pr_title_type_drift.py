"""Guard the PR-title CI type list against the commit-subject validator defaults."""

from __future__ import annotations

import re
from pathlib import Path

from sase.core.commit_subject_facade import default_commit_subject_types

_WORKFLOW_PATH = (
    Path(__file__).resolve().parent.parent / ".github" / "workflows" / "pr-title.yml"
)
_ALLOWED_TYPES_RE = re.compile(r"^\s*allowed_types='([^']+)'\s*$", re.MULTILINE)


def _pr_title_allowed_types() -> tuple[str, ...]:
    match = _ALLOWED_TYPES_RE.search(_WORKFLOW_PATH.read_text())
    assert match is not None, (
        f"Could not find an `allowed_types='...'` line in {_WORKFLOW_PATH}. "
        "If the PR-title check was restructured, update this test to match."
    )
    return tuple(part for part in match.group(1).split("|") if part)


def test_pr_title_allowed_types_parse() -> None:
    assert "feat" in _pr_title_allowed_types()


def test_pr_title_types_are_a_subset_of_validator_defaults() -> None:
    ci_types = _pr_title_allowed_types()
    defaults = default_commit_subject_types()

    drifted = [commit_type for commit_type in ci_types if commit_type not in defaults]

    assert not drifted, (
        "PR-title CI accepts commit type(s) that `sase commit` would reject: "
        f"{', '.join(drifted)}.\n"
        "Add them to default_commit_subject_types() in "
        "sase-core's crates/sase_core/src/commit_subject.rs (and the "
        "commit.message.allowed_types default in src/sase/default_config.yml "
        "and src/sase/config/sase.schema.json), or remove them from "
        f"{_WORKFLOW_PATH.name}'s allowed_types list.\n"
        f"Validator defaults: {', '.join(defaults)}."
    )
