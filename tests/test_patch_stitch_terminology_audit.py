"""Contract tests for the Patch/stitch terminology audit."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.patch_stitch_audit import (
    _RepoSpec,
    _audit_repositories,
    _classify_candidate,
    _discover_default_repo_specs,
    _retained_report,
    main as audit_main,
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
        'message = "ChangeSpec"',
        "ChangeSpec",
        "# Backward compatibility: ChangeSpec remains accepted as a legacy alias.\n"
        'message = "ChangeSpec"',
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
        "src/sase/current_feature.py",
        "from sase.main.changespec_handler import handle_patch_command",
        "changespec",
    )

    assert classification == "stable-public-path"
    assert rule == "stable_public_path"


def test_default_discovery_reports_missing_expected_linked_repos(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    (repo_root / "sase" / "repos" / "linked" / "sase-core").mkdir(parents=True)

    discovery = _discover_default_repo_specs(repo_root)

    assert [repo.name for repo in discovery.repos] == ["main", "sase-core"]
    assert discovery.missing == ("sase-github", "sase-telegram", "sase-nvim", "chezmoi")


def test_cli_fails_for_missing_expected_linked_repos_unless_allowed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "repo"
    (root / "src" / "sase" / "core").mkdir(parents=True)
    (root / "src" / "sase" / "core" / "changespec.py").write_text(
        '"""ChangeSpec compatibility shim."""\n',
        encoding="utf-8",
    )
    (root / "src" / "sase" / "core" / "wire_conversion.py").write_text(
        'DATA = {"changespec_name": "demo"}\n',
        encoding="utf-8",
    )
    (root / "src" / "sase" / "imports.py").write_text(
        "from sase.ace.changespec.parser import parse_patch\n",
        encoding="utf-8",
    )

    import subprocess

    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)

    blocked_status = audit_main(["--repo-root", str(root), "--json"])
    blocked_output = capsys.readouterr().out
    allowed_status = audit_main(
        ["--repo-root", str(root), "--json", "--allow-missing-linked-repos"]
    )
    allowed_output = capsys.readouterr().out

    assert blocked_status == 1
    assert allowed_status == 0
    assert '"missing_repos"' in blocked_output
    assert '"sase-core"' in blocked_output
    assert '"missing_repos"' in allowed_output


def test_real_repositories_keep_required_retained_categories() -> None:
    report = _audit_repositories(_discover_default_repo_specs(ROOT).repos)

    assert report.stale_rules == (), _retained_report(report)
    assert report.counts_by_classification["legacy-compatibility-boundary"] > 0
    assert report.counts_by_classification["legacy-data-test-fixture"] > 0
    assert report.counts_by_classification["stable-public-path"] > 0


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
