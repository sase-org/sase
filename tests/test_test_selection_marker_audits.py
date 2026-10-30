"""The marker-audit broadening rule (task sase-1mv).

The two agent-artifact marker AST audits read ``src/sase`` as text rather
than importing the writer functions they audit, so the import-graph closure
never reaches them. The selector adds them whenever a changed ``src/``
Python file contains a tracked marker literal — and only then.
"""

from __future__ import annotations

from pathlib import Path

from tests._test_selection_engine_helpers import (
    neutral_timings_environment,  # noqa: F401 (imported for fixture discovery)
    repo_fixture,  # noqa: F401 (imported for fixture discovery)
    select,
)
from tests._test_selection_fixtures import _git, _touch, _write
from tests._test_selection_rules import (
    MARKER_AUDIT_PATHS,
    RULE_MARKER_AUDIT,
)


def _commit_marker_audits(root: Path) -> None:
    """Commit empty stand-ins at the real audit paths.

    The rule selects by path, so the stand-ins only need to exist as graph
    nodes; asserting against the real repository's audits would make these
    tests rot on every change to either audit's imports.
    """
    for audit in MARKER_AUDIT_PATHS:
        _write(root, audit, "")
    _git(root, "add", *MARKER_AUDIT_PATHS)
    _git(root, "commit", "-q", "-m", "marker audits")


def _write_marker_writer(root: Path, path: str = "src/pkg/a.py") -> None:
    target = root / path
    target.write_text(
        target.read_text(encoding="utf-8") + 'MARKER = "done.json"\n', "utf-8"
    )


def test_marker_writer_change_selects_both_audits(repo: Path) -> None:
    _commit_marker_audits(repo)
    _write_marker_writer(repo)

    selection = select(repo)

    assert RULE_MARKER_AUDIT in selection.rules
    for audit in MARKER_AUDIT_PATHS:
        assert audit in selection.selected
        assert selection.explanations[audit] == ("src/pkg/a.py", 0)
    assert selection.manifest["rules_fired"] == list(selection.rules)
    assert not selection.escalated


def test_source_change_without_marker_literal_selects_neither(
    repo: Path,
) -> None:
    _commit_marker_audits(repo)
    _touch(repo, "src/pkg/a.py")

    selection = select(repo)

    assert RULE_MARKER_AUDIT not in selection.rules
    for audit in MARKER_AUDIT_PATHS:
        assert audit not in selection.selected


def test_marker_literal_outside_src_selects_neither(repo: Path) -> None:
    _commit_marker_audits(repo)
    target = repo / "docs/contribute/development.md"
    target.write_text(target.read_text(encoding="utf-8") + "done.json\n", "utf-8")

    selection = select(repo)

    assert RULE_MARKER_AUDIT not in selection.rules
    for audit in MARKER_AUDIT_PATHS:
        assert audit not in selection.selected


def test_deleted_marker_writer_neither_fires_nor_crashes(repo: Path) -> None:
    _commit_marker_audits(repo)
    _write_marker_writer(repo)
    _git(repo, "add", "src/pkg/a.py")
    _git(repo, "commit", "-q", "-m", "marker writer")
    _git(repo, "rm", "-q", "src/pkg/a.py")

    selection = select(repo)

    assert RULE_MARKER_AUDIT not in selection.rules
    for audit in MARKER_AUDIT_PATHS:
        assert audit not in selection.selected
