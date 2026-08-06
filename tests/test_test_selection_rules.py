"""Unit tests for the rules that broaden or escalate a selection.

The full-suite rules, the directory-conftest and rename/delete widenings, the
core-identity environment comparison, and the always-added contract set.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests._test_selection import FULL_SUITE
from tests._test_selection_engine_helpers import (
    neutral_timings_environment,  # noqa: F401 (imported for fixture discovery)
    repo_fixture,  # noqa: F401 (imported for fixture discovery)
    select,
)
from tests._test_selection_fixtures import _git, _touch, _write
from tests._test_selection_report import explain_lines
from tests._test_selection_rules import (
    CONTRACT_MANIFEST_PATH,
    RULE_BASE_UNRESOLVED,
    RULE_CONTRACT_SET_ALWAYS,
    RULE_CORE_IDENTITY_CHANGED,
    RULE_DIRECTORY_CONFTEST,
    RULE_JUSTFILE,
    RULE_PACKAGING_CONFIG,
    RULE_RENAME_OR_DELETE,
    RULE_ROOT_CONFTEST,
    RULE_SELECTION_TOOLING,
    RULE_SRC_DATA_ASSET,
)


def _commit_contract_manifest(root: Path, *entries: str) -> None:
    """Commit a contract manifest so it is not itself part of the change set."""
    _write(root, CONTRACT_MANIFEST_PATH, "".join(f"{entry}\n" for entry in entries))
    _git(root, "add", CONTRACT_MANIFEST_PATH)
    _git(root, "commit", "-q", "-m", "contract manifest")


# --------------------------------------------------------------------------
# Broadening rules
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "rule"),
    [
        ("tests/conftest.py", RULE_ROOT_CONFTEST),
        ("tests/_suite_gate.py", RULE_ROOT_CONFTEST),
        ("pyproject.toml", RULE_PACKAGING_CONFIG),
        ("uv.lock", RULE_PACKAGING_CONFIG),
        ("Justfile", RULE_JUSTFILE),
        ("src/pkg/config.yml", RULE_SRC_DATA_ASSET),
        ("tools/run_pytest", RULE_SELECTION_TOOLING),
    ],
)
def test_full_suite_rules_fire_and_escalate(repo: Path, path: str, rule: str) -> None:
    _touch(repo, path)

    selection = select(repo)

    assert rule in selection.rules
    assert selection.escalated
    assert selection.selected == ()
    assert selection.paths_output == FULL_SUITE


def test_directory_conftest_selects_its_whole_directory(repo: Path) -> None:
    _touch(repo, "tests/sub/conftest.py")

    selection = select(repo)

    assert RULE_DIRECTORY_CONFTEST in selection.rules
    assert set(selection.selected) == {
        "tests/sub/test_sub.py",
        "tests/sub/test_sub_other.py",
    }
    assert not selection.escalated


def test_unresolvable_base_escalates(repo: Path) -> None:
    selection = select(repo, base_ref="origin/nonexistent")

    assert RULE_BASE_UNRESOLVED in selection.rules
    assert selection.escalated
    assert selection.manifest["base"]["merge_base"] is None


def test_changed_core_identity_escalates(repo: Path) -> None:
    selection = select(
        repo,
        environment={"pyproject": "new-digest"},
        previous_manifest={"baseline": {"environment": {"pyproject": "old-digest"}}},
    )

    assert RULE_CORE_IDENTITY_CHANGED in selection.rules
    assert selection.escalated
    assert selection.manifest["baseline"]["environment_changed_inputs"] == ["pyproject"]


def test_unchanged_core_identity_does_not_escalate(repo: Path) -> None:
    selection = select(
        repo,
        environment={"pyproject": "same-digest"},
        previous_manifest={"baseline": {"environment": {"pyproject": "same-digest"}}},
    )

    assert RULE_CORE_IDENTITY_CHANGED not in selection.rules
    assert not selection.escalated
    assert selection.manifest["baseline"]["environment_changed_inputs"] == []


def test_missing_previous_environment_is_not_a_change(repo: Path) -> None:
    selection = select(repo, environment={"pyproject": "digest"}, previous_manifest={})

    assert RULE_CORE_IDENTITY_CHANGED not in selection.rules
    assert selection.manifest["baseline"]["environment_changed_inputs"] == []


def test_non_escalating_environment_change_does_not_escalate(repo: Path) -> None:
    """A validator script or third-party METADATA moving is not core identity.

    Only the inputs in ``ENVIRONMENT_ESCALATING_INPUTS`` force the full suite;
    everything else is still recorded on the manifest for attribution, per the
    ``identity`` phase of ``sase-gj``.
    """
    selection = select(
        repo,
        environment={
            "validator:core-version": "new-digest",
            "pyproject": "same-digest",
        },
        previous_manifest={
            "baseline": {
                "environment": {
                    "validator:core-version": "old-digest",
                    "pyproject": "same-digest",
                }
            }
        },
    )

    assert RULE_CORE_IDENTITY_CHANGED not in selection.rules
    assert not selection.escalated
    assert selection.manifest["baseline"]["environment_changed_inputs"] == [
        "validator:core-version"
    ]


def test_explain_lines_report_changed_environment_inputs(repo: Path) -> None:
    selection = select(
        repo,
        environment={"pyproject": "new-digest", "validator:core-version": "same"},
        previous_manifest={
            "baseline": {
                "environment": {
                    "pyproject": "old-digest",
                    "validator:core-version": "same",
                }
            }
        },
    )

    assert "environment inputs changed: pyproject" in explain_lines(selection)


def test_deletion_bumps_effective_depth_by_one(repo: Path) -> None:
    _git(repo, "rm", "-q", "src/pkg/hub.py")
    _touch(repo, "src/pkg/a.py")

    selection = select(repo, depth=1)

    assert RULE_RENAME_OR_DELETE in selection.rules
    # Depth 1 alone stops before test_c; the rename/delete bump buys it back.
    assert "tests/test_c.py" in selection.selected


def test_rename_records_the_rule(repo: Path) -> None:
    _git(repo, "mv", "src/pkg/d.py", "src/pkg/renamed.py")

    selection = select(repo)

    assert RULE_RENAME_OR_DELETE in selection.rules


# --------------------------------------------------------------------------
# Contract set
# --------------------------------------------------------------------------


def test_contract_set_is_always_added(repo: Path) -> None:
    _commit_contract_manifest(repo, "tests/test_d.py")
    _touch(repo, "src/pkg/a.py")

    selection = select(repo)

    assert "tests/test_d.py" in selection.selected
    assert RULE_CONTRACT_SET_ALWAYS in selection.rules


def test_contract_set_applies_to_docs_only_changes(repo: Path) -> None:
    _commit_contract_manifest(repo, "tests/test_d.py")
    _touch(repo, "docs/development.md")

    selection = select(repo)

    assert selection.selected == ("tests/test_d.py",)


def test_absent_contract_manifest_is_valid(repo: Path) -> None:
    _touch(repo, "src/pkg/a.py")

    selection = select(repo)

    assert RULE_CONTRACT_SET_ALWAYS not in selection.rules
    assert selection.selected


def test_contract_manifest_ignores_comments_and_blanks(repo: Path) -> None:
    _commit_contract_manifest(repo, "# generated", "", "tests/test_d.py")
    _touch(repo, "docs/development.md")

    selection = select(repo)

    assert selection.selected == ("tests/test_d.py",)


def test_changing_the_contract_manifest_escalates(repo: Path) -> None:
    _write(repo, CONTRACT_MANIFEST_PATH, "tests/test_d.py\n")
    _git(repo, "add", CONTRACT_MANIFEST_PATH)

    selection = select(repo)

    assert RULE_SELECTION_TOOLING in selection.rules
    assert selection.escalated
