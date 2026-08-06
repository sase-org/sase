"""Tests for doctor SDD config checks."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.doctor.checks_config_sdd import check_config_sdd
from sase.doctor.runner import DoctorContext


def _doctor_context(tmp_path: Path) -> DoctorContext:
    return DoctorContext(cwd=tmp_path, project=None, sase_home=tmp_path)


def test_config_sdd_warns_on_retired_version_controlled(
    tmp_path: Path,
) -> None:
    (tmp_path / "sdd").mkdir()
    (tmp_path / "sase.yml").write_text(
        "sdd:\n  version_controlled: true\n",
        encoding="utf-8",
    )

    check = check_config_sdd(_doctor_context(tmp_path))

    assert check.status == "WARN"
    assert any(
        issue["code"] == "retired-version-controlled"
        for issue in check.data["storage_issues"]
    )


def test_config_sdd_errors_when_provider_sidecar_has_no_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sase.vcs_provider.detect_vcs", lambda _cwd: "github")
    monkeypatch.setattr(
        "sase.workspace_provider.get_sdd_storage_policy_by_vcs",
        lambda _name: "separate_repo",
    )

    check = check_config_sdd(_doctor_context(tmp_path))

    assert check.status == "ERROR"
    assert any(
        issue["code"] == "separate-repo-not-materialized"
        for issue in check.data["storage_issues"]
    )


def test_config_sdd_uses_materialized_separate_repo_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_sdd_pair(tmp_path / ".sase" / "sdd")
    _write_materialized_sdd_record(tmp_path)

    def fake_git_stdout(_cwd: Path, args: list[str]) -> str | None:
        if args == ["remote", "get-url", "origin"]:
            return "git@github.com:acme/widget-sdd.git"
        return None

    monkeypatch.setattr(
        "sase.doctor.checks_config_sdd._git_stdout",
        fake_git_stdout,
    )

    check = check_config_sdd(_doctor_context(tmp_path))

    assert check.status == "OK"
    assert check.data["sdd_root"] == str((tmp_path / ".sase" / "sdd").resolve())
    assert check.data["file_count"] == 1


def test_config_sdd_allows_non_strict_validation_warnings(tmp_path: Path) -> None:
    from sase.sdd.links import LEGACY_INVALID_SDD_ERROR_ALLOWLIST

    allowlisted = next(iter(LEGACY_INVALID_SDD_ERROR_ALLOWLIST))
    legacy_prompt = tmp_path / ".sase" / "sdd" / allowlisted
    legacy_prompt.parent.mkdir(parents=True)
    legacy_prompt.write_text("# Historical prompt\n", encoding="utf-8")

    check = check_config_sdd(_doctor_context(tmp_path))

    assert check.status == "OK"
    assert "1 warning" in check.summary
    assert check.details == ()
    assert check.data["warning_count"] == 1


def test_config_sdd_errors_on_orphaned_store_record(tmp_path: Path) -> None:
    from sase.sdd.store import write_sdd_store_record

    write_sdd_store_record(
        tmp_path,
        {
            "schema_version": 1,
            "storage": "separate_repo",
            "provider": "github",
            "host": "github.com",
            "repo": "acme/widget-sdd",
            "remote_url": "git@github.com:acme/widget-sdd.git",
            "discovery": "found",
        },
    )

    check = check_config_sdd(_doctor_context(tmp_path))

    assert check.status == "ERROR"
    assert any(
        issue["code"] == "orphaned-store-record"
        for issue in check.data["storage_issues"]
    )


def test_config_sdd_errors_when_split_sidecar_clone_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plans, _research = _write_sidecar_sdd_record(tmp_path)
    (plans / ".git").mkdir(parents=True)
    monkeypatch.setattr(
        "sase.doctor.checks_config_sdd._git_stdout", lambda *_args: None
    )

    check = check_config_sdd(_doctor_context(tmp_path))

    assert check.status == "ERROR"
    assert any(
        issue["code"] == "missing-research-sidecar-clone"
        for issue in check.data["storage_issues"]
    )


def test_config_sdd_checks_custom_role_without_requiring_research(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.sdd.store import write_sdd_store_record

    write_sdd_store_record(
        tmp_path,
        {
            "schema_version": 2,
            "storage": "sidecar_repos",
            "sidecars": {
                "plans": {
                    "repo": "acme/widget--plans",
                    "remote_url": "git@github.com:acme/widget--plans.git",
                },
                "designs": {
                    "repo": "acme/widget--designs",
                    "remote_url": "git@github.com:acme/widget--designs.git",
                },
            },
        },
    )
    plans = tmp_path / "sase" / "repos" / "plans"
    (plans / ".git").mkdir(parents=True)
    monkeypatch.setattr(
        "sase.doctor.checks_config_sdd._git_stdout", lambda *_args: None
    )

    missing = check_config_sdd(_doctor_context(tmp_path))

    assert missing.status == "ERROR"
    assert any(
        issue["code"] == "missing-designs-sidecar-clone"
        for issue in missing.data["storage_issues"]
    )
    assert not any(
        "research" in issue["code"] for issue in missing.data["storage_issues"]
    )


def test_config_sdd_reports_unresolved_agents_sidecar_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.sdd.store import write_sdd_store_record

    write_sdd_store_record(
        tmp_path,
        {
            "schema_version": 2,
            "storage": "sidecar_repos",
            "sidecars": {
                "plans": {
                    "repo": "acme/widget--plans",
                    "remote_url": "git@github.com:acme/widget--plans.git",
                },
                "agents": {
                    "repo": "acme/widget--agents",
                    "remote_url": "git@github.com:acme/widget--agents.git",
                },
            },
        },
    )
    plans = tmp_path / "sase" / "repos" / "plans"
    (plans / ".git").mkdir(parents=True)
    monkeypatch.setattr(
        "sase.doctor.checks_config_sdd._git_stdout", lambda *_args: None
    )
    monkeypatch.setattr(
        "sase.bead.project_name.infer_project_name_from_cwd",
        lambda *_args, **_kwargs: None,
    )

    check = check_config_sdd(_doctor_context(tmp_path))

    assert check.status == "ERROR"
    assert any(
        issue["code"] == "unresolved-agents-sidecar-root"
        and "could not resolve the owning SASE project key" in issue["message"]
        for issue in check.data["storage_issues"]
    )
    assert not any(
        "missing-agents" in issue["code"] for issue in check.data["storage_issues"]
    )


def test_config_sdd_warns_when_legacy_clone_lingers_after_split(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plans, research = _write_sidecar_sdd_record(tmp_path)
    (plans / ".git").mkdir(parents=True)
    (research / ".git").mkdir(parents=True)
    (tmp_path / ".sase" / "sdd").mkdir()
    monkeypatch.setattr(
        "sase.doctor.checks_config_sdd._git_stdout", lambda *_args: None
    )

    check = check_config_sdd(_doctor_context(tmp_path))

    assert check.status == "WARN"
    assert any(
        issue["code"] == "legacy-sdd-after-migration"
        for issue in check.data["storage_issues"]
    )


@pytest.mark.parametrize("record_kind", ["missing", "separate_repo"])
def test_config_sdd_errors_when_record_regresses_with_split_clones(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    record_kind: str,
) -> None:
    if record_kind == "separate_repo":
        _write_materialized_sdd_record(tmp_path)
    _write_regressed_split_clones(tmp_path)
    monkeypatch.setattr(
        "sase.doctor.checks_config_sdd._git_stdout", lambda *_args: None
    )

    check = check_config_sdd(_doctor_context(tmp_path))

    assert check.status == "ERROR"
    assert any(
        issue["code"] == "sdd-record-regressed" and "sase repo init" in issue["message"]
        for issue in check.data["storage_issues"]
    )


def test_config_sdd_errors_when_record_regresses_with_beads_sidecar_clone(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repos = tmp_path / "sase" / "repos"
    for kind in ("plans", "research", "beads"):
        (repos / kind / ".git").mkdir(parents=True)
    monkeypatch.setattr(
        "sase.doctor.checks_config_sdd._git_stdout", lambda *_args: None
    )

    check = check_config_sdd(_doctor_context(tmp_path))

    assert check.status == "ERROR"
    assert any(
        issue["code"] == "sdd-record-regressed"
        for issue in check.data["storage_issues"]
    )


def test_config_sdd_record_regression_check_ignores_legacy_only_layout(
    tmp_path: Path,
) -> None:
    (tmp_path / ".sase" / "sdd" / "beads").mkdir(parents=True)

    check = check_config_sdd(_doctor_context(tmp_path))

    assert not any(
        issue["code"] == "sdd-record-regressed"
        for issue in check.data.get("storage_issues", ())
    )


def test_config_sdd_record_regression_check_ignores_healthy_sidecars(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plans, research = _write_sidecar_sdd_record(tmp_path)
    (plans / ".git").mkdir(parents=True)
    (research / ".git").mkdir(parents=True)
    monkeypatch.setattr(
        "sase.doctor.checks_config_sdd._git_stdout", lambda *_args: None
    )

    check = check_config_sdd(_doctor_context(tmp_path))

    assert not any(
        issue["code"] == "sdd-record-regressed"
        for issue in check.data.get("storage_issues", ())
    )


def _write_materialized_sdd_record(
    primary: Path,
    *,
    remote_url: str = "git@github.com:acme/widget-sdd.git",
) -> None:
    from sase.sdd.store import write_sdd_store_record

    write_sdd_store_record(
        primary,
        {
            "schema_version": 1,
            "storage": "separate_repo",
            "provider": "github",
            "host": "github.com",
            "repo": "acme/widget-sdd",
            "remote_url": remote_url,
            "discovery": "found",
        },
    )
    (primary / ".sase" / "sdd" / ".git").mkdir(parents=True)


def _write_sidecar_sdd_record(primary: Path) -> tuple[Path, Path]:
    from sase.sdd.store import write_sdd_store_record

    write_sdd_store_record(
        primary,
        {
            "schema_version": 2,
            "storage": "sidecar_repos",
            "provider": "github",
            "sidecars": {
                "plans": {
                    "repo": "acme/widget--plans",
                    "remote_url": "git@github.com:acme/widget--plans.git",
                },
                "research": {
                    "repo": "acme/widget--research",
                    "remote_url": "git@github.com:acme/widget--research.git",
                },
            },
        },
    )
    repos = primary / "sase" / "repos"
    plans = repos / "plans"
    (plans / "beads").mkdir(parents=True)
    return plans, repos / "research"


def _write_regressed_split_clones(primary: Path) -> tuple[Path, Path]:
    repos = primary / "sase" / "repos"
    plans = repos / "plans"
    research = repos / "research"
    (plans / ".git").mkdir(parents=True)
    (plans / "beads").mkdir()
    (research / ".git").mkdir(parents=True)
    return plans, research


def _write_sdd_pair(root: Path) -> None:
    tale = root / "plans" / "202605" / "linked.md"
    tale.parent.mkdir(parents=True, exist_ok=True)
    tale.write_text(
        "---\ntier: tale\n---\n\n"
        "- **PROMPT:** [prompts/202605/linked.md](https://example.test/prompt)"
        "\n\n# Tale\n",
        encoding="utf-8",
    )


def test_config_sdd_retired_storage_is_ignored_while_record_stays_active(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "sase.yml").write_text(
        "sdd:\n  storage: local\n",
        encoding="utf-8",
    )
    _write_materialized_sdd_record(tmp_path)
    monkeypatch.setattr(
        "sase.doctor.checks_config_sdd._git_stdout", lambda *_args: None
    )

    check = check_config_sdd(_doctor_context(tmp_path))

    assert check.status == "WARN"
    assert any(
        issue["code"] == "retired-storage" for issue in check.data["storage_issues"]
    )
    assert not any(
        issue["code"] == "record-ignored-by-config"
        for issue in check.data["storage_issues"]
    )


def test_config_sdd_warns_when_sidecar_diverged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    remote_url = "git@github.com:acme/widget-sdd.git"
    (tmp_path / "sase.yml").write_text(
        "sdd:\n  storage: separate_repo\n",
        encoding="utf-8",
    )
    _write_materialized_sdd_record(tmp_path, remote_url=remote_url)
    git_commands: list[list[str]] = []

    def fake_run(
        args: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        git_commands.append(args)
        if args == ["git", "remote", "get-url", "origin"]:
            return subprocess.CompletedProcess(args, 0, f"{remote_url}\n", "")
        if args == [
            "git",
            "rev-list",
            "--left-right",
            "--count",
            "@{upstream}...HEAD",
        ]:
            return subprocess.CompletedProcess(args, 0, "2 3\n", "")
        return subprocess.CompletedProcess(args, 1, "", "unexpected git command")

    monkeypatch.setattr("sase.doctor.checks_config_sdd.subprocess.run", fake_run)

    check = check_config_sdd(_doctor_context(tmp_path))

    assert check.status == "WARN"
    assert all("fetch" not in command for command in git_commands)
    assert any(
        issue["code"] == "sidecar-diverged"
        and "3 ahead and 2 behind" in issue["message"]
        for issue in check.data["storage_issues"]
    )


def test_config_sdd_warns_on_duplicate_sidecar_remote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    remote_url = "git@github.com:acme/shared-sdd.git"
    other = tmp_path / "other"
    other.mkdir()
    (tmp_path / "sase.yml").write_text(
        "sdd:\n  storage: separate_repo\n",
        encoding="utf-8",
    )
    _write_materialized_sdd_record(tmp_path, remote_url=remote_url)
    _write_materialized_sdd_record(other, remote_url=remote_url)
    monkeypatch.setattr(
        "sase.doctor.checks_config_sdd._git_stdout", lambda *_args: None
    )
    monkeypatch.setattr(
        "sase.doctor.checks_project.resolve_current_project_record",
        lambda _context: SimpleNamespace(
            records=(
                SimpleNamespace(project_name="alpha", workspace_dir=str(tmp_path)),
                SimpleNamespace(project_name="beta", workspace_dir=str(other)),
            )
        ),
    )

    check = check_config_sdd(_doctor_context(tmp_path))

    assert check.status == "WARN"
    assert any(
        issue["code"] == "duplicate-sidecar-remote" and "beta" in issue["message"]
        for issue in check.data["storage_issues"]
    )
