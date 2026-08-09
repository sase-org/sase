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


def _just_recipe_body(recipe_name: str) -> str:
    lines = (ROOT / "Justfile").read_text(encoding="utf-8").splitlines()
    header = f"{recipe_name}:"
    start = next(index for index, line in enumerate(lines) if line.startswith(header))
    body: list[str] = []
    for line in lines[start + 1 :]:
        if line and not line.startswith((" ", "\t")):
            break
        body.append(line)
    return "\n".join(body)


def test_just_gate_missing_repo_policy() -> None:
    lint_body = _just_recipe_body("_lint-patch-stitch-terminology")
    audit_body = _just_recipe_body("audit-patch-stitch-terminology")

    assert (
        "tools/audit_patch_stitch_terminology --repo-root . --allow-missing-linked-repos"
        in lint_body
    )
    assert "tools/audit_patch_stitch_terminology --repo-root ." in audit_body
    assert "--allow-missing-linked-repos" not in audit_body
    assert "_lint-patch-stitch-terminology" not in audit_body


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


def test_classifier_accepts_sase_core_stable_mobile_wire_name() -> None:
    classification, rule, _reason = _classify_candidate(
        "sase-core",
        "crates/sase_gateway/contracts/api_v1/mobile_api_v1.json",
        '"success": "MobileChangeSpecTagListResponseWire"',
        "MobileChangeSpecTagListResponseWire",
    )

    assert classification == "legacy-compatibility-boundary"
    assert rule == "external_legacy_boundary"


def test_classifier_accepts_stable_public_path() -> None:
    classification, rule, _reason = _classify_candidate(
        "main",
        "src/sase/current_feature.py",
        "from sase.main.changespec_handler import handle_patch_command",
        "changespec",
    )

    assert classification == "stable-public-path"
    assert rule == "stable_public_path"


def test_classifier_accepts_test_tree_declared_legacy_alias() -> None:
    classification, rule, _reason = _classify_candidate(
        "main",
        "tests/ace/tui/test_patch_tab_state.py",
        'initial_tab = "changespecs"',
        "changespecs",
        "# legacy alias fixture for the retained changespecs tab id\n"
        'initial_tab = "changespecs"',
    )

    assert classification == "legacy-data-test-fixture"
    assert rule == "compatibility_test_or_fixture"


def test_classifier_rejects_test_tree_current_concept_prose() -> None:
    classification, rule, reason = _classify_candidate(
        "main",
        "tests/ace/tui/test_patch_grouping.py",
        '"""Current ChangeSpec grouping renders by Patch."""',
        "ChangeSpec",
    )

    assert classification == "defect"
    assert rule == "unclassified"
    assert "Patch/stitch" in reason


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


def test_audit_scans_existing_worktree_text_files(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "tracked.py").write_text(
        "ChangeSpec remains accepted as a legacy alias.\n",
        encoding="utf-8",
    )
    (root / "deleted.py").write_text("Current ChangeSpec prose\n", encoding="utf-8")
    (root / "untracked.py").write_text("Current ChangeSpec prose\n", encoding="utf-8")

    import subprocess

    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "add", "tracked.py", "deleted.py"], cwd=root, check=True)
    (root / "deleted.py").unlink()

    report = _audit_repositories((_RepoSpec("fixture", root),))

    assert [(defect.path, defect.matched) for defect in report.defects] == [
        ("untracked.py", "ChangeSpec")
    ]
    assert report.counts_by_rule == {
        "legacy_compatibility_boundary": 1,
        "unclassified": 1,
    }
