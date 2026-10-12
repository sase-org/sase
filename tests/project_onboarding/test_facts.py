"""Tests for read-only onboarding fact gathering."""

from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Any

import pytest

from sase import workspace_provider
from sase.core.project_lifecycle_wire import ProjectRecordWire
from sase.project_onboarding.facts import gather_facts
from sase.workspace_provider._hookspec import (
    ParsedRepoRef,
    RepoCreationChoice,
    RepoCreationField,
    RepoCreationForm,
    RepoProbe,
    WorkflowMetadata,
)


def _metadata() -> list[WorkflowMetadata]:
    return [
        WorkflowMetadata(
            workflow_type="gh",
            ref_pattern="",
            display_name="GitHub",
            pre_allocated_env_prefix="",
            sdd_storage_policy="separate_repo",
        )
    ]


def _parsed(ref: str = "sase-org/bob") -> ParsedRepoRef:
    owner, name = ref.split("/")
    return ParsedRepoRef(
        workflow_type="gh",
        ref=ref,
        identity_key=f"github.com/{owner}/{name}".casefold(),
        display=ref,
        host="github.com",
        owner=owner,
        name=name,
        project_key_base=f"gh_{owner}__{name}",
        project_name_base=name,
        checkout_dir=f"/tmp/{name}",
        web_url=f"https://github.com/{ref}",
    )


def _probe(**overrides: Any) -> RepoProbe:
    payload: dict[str, Any] = {
        "status": "found",
        "parsed": _parsed(),
        "visibility": "private",
        "default_branch": "main",
        "can_push": True,
        "sase_managed": False,
        "web_url": "https://github.com/sase-org/bob",
        "repo_id": "R1",
    }
    payload.update(overrides)
    return RepoProbe(**payload)


def _target(tmp_path: Path, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "workflow_type": "gh",
        "identity_key": "github.com/sase-org/bob",
        "ref": "sase-org/bob",
        "display": "sase-org/bob",
        "checkout_dir": str(tmp_path / "bob"),
        "project_key_base": "gh_sase-org__bob",
        "project_name_base": "bob",
        "storage_policy": "separate_repo",
    }
    payload.update(overrides)
    return payload


def _git(path: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )


def _init_git(path: Path, origin: str) -> None:
    path.mkdir(parents=True)
    _git(path, "init")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test")
    _git(path, "remote", "add", "origin", origin)
    (path / "README").write_text("hi\n", encoding="utf-8")
    _git(path, "add", "README")
    _git(path, "commit", "-m", "init")
    _git(path, "branch", "-M", "main")


@pytest.fixture
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "sase-home"
    monkeypatch.setenv("SASE_HOME", str(home))
    return home


@pytest.fixture
def gh_provider(monkeypatch: pytest.MonkeyPatch) -> list[RepoProbe]:
    probes: list[RepoProbe] = [_probe()]

    def parse(workflow_type: str, text: str) -> ParsedRepoRef | None:
        if workflow_type != "gh":
            return None
        value = text.strip()
        if "github.com/" in value:
            value = value.rstrip("/").split("github.com/")[-1].removesuffix(".git")
        if value.startswith("gh:"):
            value = value[3:]
        if "/" not in value:
            return None
        return _parsed(value)

    monkeypatch.setattr(workspace_provider, "get_all_workflow_metadata", _metadata)
    monkeypatch.setattr(workspace_provider, "parse_repo_ref", parse)
    monkeypatch.setattr(
        workspace_provider, "probe_repo", lambda workflow_type, ref: probes[0]
    )
    monkeypatch.setattr(
        workspace_provider, "get_display_name", lambda workflow_type: "GitHub"
    )
    return probes


class TestGatherFacts:
    def test_absent_checkout_and_found_probe(
        self, tmp_path: Path, isolated_home: Path, gh_provider: list[RepoProbe]
    ) -> None:
        del isolated_home, gh_provider
        facts = gather_facts(_target(tmp_path), "add", actor="human")
        assert facts["remote"]["status"] == "found"
        assert facts["remote"]["can_push"] is True
        assert facts["checkout"]["state"] == "absent"
        assert (tmp_path / "bob").exists() is False

    def test_unavailable_probe_keeps_message(
        self, tmp_path: Path, isolated_home: Path, gh_provider: list[RepoProbe]
    ) -> None:
        del isolated_home
        gh_provider[0] = _probe(
            status="unavailable",
            message="gh not signed in",
            can_push=None,
            sase_managed=None,
        )
        facts = gather_facts(_target(tmp_path), "add", actor="human")
        assert facts["remote"]["status"] == "unavailable"
        assert facts["remote"]["message"] == "gh not signed in"
        assert facts["remote"]["can_push"] is None

    def test_empty_dir_and_not_git(
        self, tmp_path: Path, isolated_home: Path, gh_provider: list[RepoProbe]
    ) -> None:
        del isolated_home, gh_provider
        empty = tmp_path / "empty"
        empty.mkdir()
        cluttered = tmp_path / "clutter"
        cluttered.mkdir()
        (cluttered / "file.txt").write_text("x", encoding="utf-8")
        assert (
            gather_facts(
                _target(tmp_path, checkout_dir=str(empty)), "add", actor="human"
            )["checkout"]["state"]
            == "empty_dir"
        )
        assert (
            gather_facts(
                _target(tmp_path, checkout_dir=str(cluttered)), "add", actor="human"
            )["checkout"]["state"]
            == "not_git"
        )

    def test_matching_and_mismatch_use_provider_parse(
        self, tmp_path: Path, isolated_home: Path, gh_provider: list[RepoProbe]
    ) -> None:
        del isolated_home, gh_provider
        matching = tmp_path / "match"
        mismatch = tmp_path / "other"
        _init_git(matching, "https://github.com/sase-org/bob.git")
        _init_git(mismatch, "https://github.com/sase-org/other.git")
        assert (
            gather_facts(
                _target(tmp_path, checkout_dir=str(matching)), "add", actor="human"
            )["checkout"]["state"]
            == "matching"
        )
        observed = gather_facts(
            _target(tmp_path, checkout_dir=str(mismatch)), "add", actor="human"
        )["checkout"]
        assert observed["state"] == "mismatch"
        assert "other" in observed["origin_url"]

    def test_gitfile_worktree_is_matching_not_conflict(
        self, tmp_path: Path, isolated_home: Path, gh_provider: list[RepoProbe]
    ) -> None:
        del isolated_home, gh_provider
        primary = tmp_path / "primary"
        worktree = tmp_path / "worktree"
        _init_git(primary, "https://github.com/sase-org/bob.git")
        _git(primary, "worktree", "add", str(worktree))
        assert (worktree / ".git").is_file()
        facts = gather_facts(
            _target(tmp_path, checkout_dir=str(worktree)), "add", actor="human"
        )
        assert facts["checkout"]["state"] == "matching"

    def test_local_managed_and_dirty_config(
        self, tmp_path: Path, isolated_home: Path, gh_provider: list[RepoProbe]
    ) -> None:
        del isolated_home, gh_provider
        checkout = tmp_path / "managed"
        _init_git(checkout, "https://github.com/sase-org/bob.git")
        config = checkout / "sase" / "sase.yml"
        config.parent.mkdir()
        config.write_text("is_sase_managed: true\n", encoding="utf-8")
        facts = gather_facts(
            _target(tmp_path, checkout_dir=str(checkout)), "add", actor="human"
        )
        assert facts["local_managed"] is True
        assert facts["checkout"]["config_dirty"] is True

    def test_matching_record_and_collision_records(
        self,
        tmp_path: Path,
        isolated_home: Path,
        gh_provider: list[RepoProbe],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        del isolated_home, gh_provider
        checkout = tmp_path / "bob"
        _init_git(checkout, "https://github.com/sase-org/bob.git")
        records = [
            ProjectRecordWire(
                schema_version=1,
                project_name="gh_sase-org__bob",
                project_dir="/tmp/p",
                project_file="/tmp/p/p.sase",
                archive_file=None,
                workspace_dir=str(checkout),
                state="disabled",
                state_explicit=True,
                system_managed=False,
                active_claim_count=0,
                launchable=True,
                aliases=["bob"],
            ),
            ProjectRecordWire(
                schema_version=1,
                project_name="other",
                project_dir="/tmp/o",
                project_file="/tmp/o/o.sase",
                archive_file=None,
                workspace_dir=None,
                state="enabled",
                state_explicit=False,
                system_managed=False,
                active_claim_count=0,
                launchable=True,
            ),
        ]
        monkeypatch.setattr(
            "sase.project_onboarding.facts.list_project_records",
            lambda *args, **kwargs: records,
        )
        facts = gather_facts(
            _target(tmp_path, checkout_dir=str(checkout)), "add", actor="human"
        )
        assert facts["record"]["key"] == "gh_sase-org__bob"
        assert facts["record"]["state"] == "disabled"
        keys = {row["key"] for row in facts["projects"]}
        assert keys == {"gh_sase-org__bob", "other"}

    def test_preview_does_not_write(
        self, tmp_path: Path, isolated_home: Path, gh_provider: list[RepoProbe]
    ) -> None:
        gh_provider[0] = _probe(status="found")
        checkout = tmp_path / "missing"
        gather_facts(
            _target(tmp_path, checkout_dir=str(checkout)), "add", actor="human"
        )
        assert checkout.exists() is False
        assert (isolated_home / "project_onboarding").exists() is False

    def test_create_mode_evaluates_options_before_any_write(
        self,
        tmp_path: Path,
        isolated_home: Path,
        gh_provider: list[RepoProbe],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        del gh_provider
        gh_provider_form = RepoCreationForm(
            workflow_type="gh",
            namespace="sase-org",
            fields=(
                RepoCreationField(
                    name="visibility",
                    label="Visibility",
                    kind="choice",
                    default="private",
                    choices=(
                        RepoCreationChoice(value="public", label="Public"),
                        RepoCreationChoice(value="private", label="Private"),
                    ),
                ),
                RepoCreationField(
                    name="template",
                    label="Template",
                    kind="line",
                    excludes=("license",),
                ),
                RepoCreationField(name="license", label="License", kind="search"),
            ),
            can_create=True,
        )
        monkeypatch.setattr(
            workspace_provider,
            "describe_repo_creation",
            lambda workflow_type, namespace: gh_provider_form,
        )
        facts = gather_facts(
            _target(tmp_path),
            "create",
            actor="human",
            options={"template": "sase-org/template", "license": "MIT"},
        )
        assert facts["can_create"] is True
        assert facts["creation_errors"]
        assert any(item["code"] == "conflict" for item in facts["creation_errors"])
        assert facts["creation_fields"]
        assert (tmp_path / "bob").exists() is False
        assert (isolated_home / "project_onboarding").exists() is False
