"""Revision-pin config parsing, project-local resolution, and doctor checks."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase._linked_repo_config import (
    normalize_revision_pin,
    revision_pin_for_entry,
)
from sase._linked_repo_env import ResolvedLinkedRepo
from sase._repo_inventory_models import RepoRecord
from sase.doctor import checks_config_repos as repos_checks


# Config parsing and validation.


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("sase-core-revision.txt", "sase-core-revision.txt"),
        ("./sase-core-revision.txt", "sase-core-revision.txt"),
        ("sub/dir/pin.txt", "sub/dir/pin.txt"),
        ("a/b/../c.txt", "a/c.txt"),
    ],
)
def test_normalize_revision_pin_accepts_relative_paths(raw: str, expected: str) -> None:
    assert normalize_revision_pin(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["/abs/pin.txt", "~/pin.txt", "../escape.txt", "a/../../escape.txt", "", "   "],
)
def test_normalize_revision_pin_rejects_absolute_and_escaping_paths(
    raw: str,
) -> None:
    with pytest.raises(ValueError):
        normalize_revision_pin(raw)


def test_normalize_revision_pin_rejects_non_strings() -> None:
    with pytest.raises(ValueError):
        normalize_revision_pin(42)


def test_revision_pin_for_entry_returns_none_when_unset() -> None:
    assert revision_pin_for_entry({"name": "core"}) is None


def test_revision_pin_models_carry_the_field() -> None:
    resolved = ResolvedLinkedRepo(
        name="sase-core",
        env_name="SASE_CORE",
        primary_dir="/primary",
        workspace_dir="/ws",
        workspace_num=1,
        revision_pin="sase-core-revision.txt",
    )
    assert resolved.to_json_dict()["revision_pin"] == "sase-core-revision.txt"

    record = RepoRecord(
        name="sase-core",
        kind="linked",
        project="sase",
        project_key="sase",
        path="/primary/../sase-core",
        exists=True,
        auto_clone=True,
        description="core",
        source="repos.linked config",
        env_name="SASE_CORE",
        revision_pin="sase-core-revision.txt",
    )
    assert record.to_json_dict()["revision_pin"] == "sase-core-revision.txt"


@pytest.mark.parametrize(
    "raw",
    ["C:/pin.txt", "C:\\pin.txt", "D:pin.txt", "c:/sub/pin.txt"],
)
def test_normalize_revision_pin_rejects_windows_drive_paths(raw: str) -> None:
    with pytest.raises(ValueError):
        normalize_revision_pin(raw)


# Project-local pin resolution.


def test_revision_pins_read_from_project_local_config(tmp_path: Path) -> None:
    from sase.finalizers.commit_revision_pin import revision_pins_for_project

    primary = tmp_path / "proj"
    (primary / "sase").mkdir(parents=True)
    (primary / "sase" / "sase.yml").write_text(
        "repos:\n"
        "  linked:\n"
        "    - name: sase-core\n"
        "      path: ../sase-core\n"
        "      description: core\n"
        "      revision_pin: sase-core-revision.txt\n",
        encoding="utf-8",
    )

    assert revision_pins_for_project(str(primary)) == {
        "sase-core": "sase-core-revision.txt"
    }


def test_revision_pins_ignore_cwd_project_config(tmp_path: Path) -> None:
    """A tmp primary without its own config gets no pins.

    Regression: the sase checkout's own ``sase/sase.yml`` (the process cwd)
    must not leak its pin into unrelated finalizer runs.
    """

    from sase.finalizers.commit_revision_pin import revision_pins_for_project

    primary = tmp_path / "proj"
    primary.mkdir()

    assert revision_pins_for_project(str(primary)) == {}


# Doctor check.


def test_doctor_flags_missing_pin_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sase.config.core.load_merged_config",
        lambda: {
            "repos": {
                "linked": [
                    {
                        "name": "sase-core",
                        "path": "../sase-core",
                        "description": "core",
                        "revision_pin": "sase-core-revision.txt",
                    }
                ]
            }
        },
    )
    monkeypatch.setattr(
        "sase.doctor.checks_config_repos._artifact_provider_registry_problems",
        lambda: [],
    )

    check = repos_checks.check_config_repos()

    assert check.status == "WARN"
    assert any("missing" in row["message"] for row in check.data["problems"])


def test_doctor_flags_non_sha_pin_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "sase-core-revision.txt").write_text("not-a-sha\n", encoding="utf-8")
    monkeypatch.setattr(
        "sase.config.core.load_merged_config",
        lambda: {
            "repos": {
                "linked": [
                    {
                        "name": "sase-core",
                        "path": "../sase-core",
                        "description": "core",
                        "revision_pin": "sase-core-revision.txt",
                    }
                ]
            }
        },
    )
    monkeypatch.setattr(
        "sase.doctor.checks_config_repos._artifact_provider_registry_problems",
        lambda: [],
    )

    check = repos_checks.check_config_repos()

    assert check.status == "WARN"
    assert any("40-character hex" in row["message"] for row in check.data["problems"])


def test_doctor_flags_absolute_pin_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sase.config.core.load_merged_config",
        lambda: {
            "repos": {
                "linked": [
                    {
                        "name": "sase-core",
                        "path": "../sase-core",
                        "description": "core",
                        "revision_pin": "/abs/pin.txt",
                    }
                ]
            }
        },
    )
    monkeypatch.setattr(
        "sase.doctor.checks_config_repos._artifact_provider_registry_problems",
        lambda: [],
    )

    check = repos_checks.check_config_repos()

    assert check.status == "WARN"


def test_doctor_accepts_valid_pin_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "sase-core-revision.txt").write_text("a" * 40 + "\n", encoding="utf-8")
    monkeypatch.setattr(
        "sase.config.core.load_merged_config",
        lambda: {
            "repos": {
                "linked": [
                    {
                        "name": "sase-core",
                        "path": "../sase-core",
                        "description": "core",
                        "revision_pin": "sase-core-revision.txt",
                    }
                ]
            }
        },
    )
    monkeypatch.setattr(
        "sase.doctor.checks_config_repos._artifact_provider_registry_problems",
        lambda: [],
    )

    check = repos_checks.check_config_repos()

    assert check.status == "OK"


def test_doctor_flags_symlinked_pin_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary = tmp_path / "sase"
    primary.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    (external / "sase-core-revision.txt").write_text("a" * 40 + "\n", encoding="utf-8")
    (primary / "link").symlink_to(external, target_is_directory=True)
    monkeypatch.chdir(primary)
    monkeypatch.setattr(
        "sase.config.core.load_merged_config",
        lambda: {
            "repos": {
                "linked": [
                    {
                        "name": "sase-core",
                        "path": "../sase-core",
                        "description": "core",
                        "revision_pin": "link/sase-core-revision.txt",
                    }
                ]
            }
        },
    )
    monkeypatch.setattr(
        "sase.doctor.checks_config_repos._artifact_provider_registry_problems",
        lambda: [],
    )

    check = repos_checks.check_config_repos()

    assert check.status == "WARN"
    assert any("symlink" in row["message"] for row in check.data["problems"])
