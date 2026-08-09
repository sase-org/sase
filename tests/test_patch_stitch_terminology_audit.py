"""Contract tests for the Patch/stitch terminology audit."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.patch_stitch_audit import (
    _RepoSpec,
    _audit_repositories,
    _classify_candidate,
    _default_repo_specs,
    _retained_report,
)

pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parents[1]


def test_classifier_rejects_ordinary_source_regression() -> None:
    classification, rule, reason = _classify_candidate(
        "main",
        "src/sase/new_feature.py",
        "message = 'Current ChangeSpec status'",
        "ChangeSpec",
    )

    assert classification == "defect"
    assert rule == "unclassified"
    assert "Patch/stitch" in reason


def test_classifier_accepts_explicit_compatibility_comment() -> None:
    classification, rule, _reason = _classify_candidate(
        "main",
        "src/sase/current_feature.py",
        "ChangeSpec remains accepted as a legacy alias.",
        "ChangeSpec",
    )

    assert classification == "legacy-compatibility-boundary"
    assert rule == "legacy_compatibility_boundary"


def test_classifier_accepts_legacy_wire_key() -> None:
    classification, rule, _reason = _classify_candidate(
        "main",
        "src/sase/core/wire_conversion.py",
        '"commit_entry_num": "1", "changespec_name": "demo"',
        "commit_entry_num",
    )

    assert classification == "legacy-serialized-data"
    assert rule == "legacy_serialized_data"


def test_classifier_accepts_stable_public_path() -> None:
    classification, rule, _reason = _classify_candidate(
        "main",
        "src/sase/main/changespec_handler.py",
        "from sase.main.patch_handler import handle_changespec_command",
        "changespec",
    )

    assert classification == "legacy-compatibility-boundary"
    assert rule == "legacy_compatibility_boundary"


def test_real_repositories_have_no_unclassified_legacy_terms() -> None:
    report = _audit_repositories(_default_repo_specs(ROOT))

    assert report.stale_rules == ()
    assert report.defects == (), _retained_report(report)


def test_audit_scans_tracked_text_only(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "tracked.py").write_text(
        "ChangeSpec remains accepted as a legacy alias.\n",
        encoding="utf-8",
    )
    (root / "untracked.py").write_text("Current ChangeSpec prose\n", encoding="utf-8")

    import subprocess

    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "add", "tracked.py"], cwd=root, check=True)

    report = _audit_repositories((_RepoSpec("fixture", root),))

    assert report.defects == ()
    assert report.counts_by_rule == {"legacy_compatibility_boundary": 1}
