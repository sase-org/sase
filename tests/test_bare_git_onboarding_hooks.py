"""Tests for the built-in bare-git workspace onboarding hooks."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from sase.workspace_provider.plugins import bare_git_workspace as bare_git


def _use_temporary_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: home))
    monkeypatch.setattr(
        bare_git.os.path,
        "expanduser",
        lambda value: str(home / value[2:]) if value.startswith("~/") else value,
    )
    monkeypatch.setattr(
        bare_git,
        "sase_subdir",
        lambda subdir: tmp_path / "sase" / subdir,
    )
    return home


def _git_init_bare(path: Path) -> None:
    result = subprocess.run(
        ["git", "init", "--bare", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def _push_managed_main_branch(bare_path: Path, seed_path: Path) -> None:
    seed_path.mkdir()
    commands = (
        ["git", "init", "--initial-branch=main", str(seed_path)],
        ["git", "-C", str(seed_path), "config", "user.name", "SASE tests"],
        [
            "git",
            "-C",
            str(seed_path),
            "config",
            "user.email",
            "tests@example.invalid",
        ],
    )
    for command in commands:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        assert result.returncode == 0, result.stderr
    config = seed_path / "sase" / "sase.yml"
    config.parent.mkdir()
    config.write_text("is_sase_managed: true\n", encoding="utf-8")
    for command in (
        ["git", "-C", str(seed_path), "add", "sase/sase.yml"],
        ["git", "-C", str(seed_path), "commit", "-m", "seed managed repo"],
        ["git", "-C", str(seed_path), "remote", "add", "origin", str(bare_path)],
        ["git", "-C", str(seed_path), "push", "origin", "main"],
        ["git", "--git-dir", str(bare_path), "symbolic-ref", "HEAD", "refs/heads/main"],
    ):
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        assert result.returncode == 0, result.stderr


def test_parse_repo_ref_is_pure_and_accepts_bare_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_temporary_paths(monkeypatch, tmp_path)

    def fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("parse hook must not use subprocesses or stat paths")

    plugin = bare_git.BareGitWorkspacePlugin()
    with monkeypatch.context() as patcher:
        patcher.setattr(bare_git.subprocess, "run", fail)
        patcher.setattr(Path, "exists", fail)
        parsed = plugin.ws_parse_repo_ref("git", "git:widget")
        path_ref = plugin.ws_parse_repo_ref("git", "~/projects/git/other.git")
        wrong_provider = plugin.ws_parse_repo_ref("other", "widget")
        invalid_ref = plugin.ws_parse_repo_ref("git", "../widget")

    assert parsed is not None
    assert parsed.ref == "widget"
    assert parsed.identity_key.endswith("/sase/repos/widget.git")
    assert parsed.project_key_base == "widget"
    assert parsed.project_name_base == "widget"
    assert parsed.normalized_from == "git:widget"
    assert path_ref is not None
    assert path_ref.ref.endswith("/projects/git/other.git")
    assert path_ref.name == "other"
    assert wrong_provider is None
    assert invalid_ref is None


def test_local_candidates_read_configs_without_subprocesses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = _use_temporary_paths(monkeypatch, tmp_path)
    bare_path = tmp_path / "sase" / "repos" / "widget.git"
    _git_init_bare(bare_path)
    checkout = home / "projects" / "git" / "widget_2"
    git_dir = checkout / ".git"
    git_dir.mkdir(parents=True)
    (git_dir / "config").write_text(
        f'[remote "origin"]\n\turl = {bare_path}\n',
        encoding="utf-8",
    )

    def fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("local candidate discovery must not spawn subprocesses")

    monkeypatch.setattr(bare_git.subprocess, "run", fail)
    candidates = bare_git.BareGitWorkspacePlugin().ws_list_local_repo_candidates("git")

    assert candidates is not None
    assert len(candidates.entries) == 2
    checkout_candidate = next(
        candidate
        for candidate in candidates.entries
        if candidate.path.endswith("widget_2")
    )
    assert checkout_candidate.origin_url == str(bare_path)
    assert checkout_candidate.numbered_copy is True
    assert checkout_candidate.parsed.identity_key == f"git:{bare_path}"


def test_probe_reports_local_bare_repo_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_temporary_paths(monkeypatch, tmp_path)
    bare_path = tmp_path / "sase" / "repos" / "widget.git"
    _git_init_bare(bare_path)

    probe = bare_git.BareGitWorkspacePlugin().ws_probe_repo("git", "widget")

    assert probe is not None
    assert probe.status == "found"
    assert probe.visibility == "local"
    assert probe.is_empty is True
    assert probe.can_push is True
    assert probe.repo_id == str(bare_path)


def test_probe_and_create_recognize_a_populated_managed_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_temporary_paths(monkeypatch, tmp_path)
    bare_path = tmp_path / "sase" / "repos" / "widget.git"
    _git_init_bare(bare_path)
    _push_managed_main_branch(bare_path, tmp_path / "seed")

    plugin = bare_git.BareGitWorkspacePlugin()
    probe = plugin.ws_probe_repo("git", "widget")
    created = plugin.ws_create_repo("git", "widget", {})

    assert probe is not None
    assert probe.status == "found"
    assert probe.default_branch == "main"
    assert probe.is_empty is False
    assert probe.sase_managed is True
    assert created is not None and created.status == "exists"


def test_create_repo_initializes_only_an_empty_bare_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_temporary_paths(monkeypatch, tmp_path)
    plugin = bare_git.BareGitWorkspacePlugin()

    result = plugin.ws_create_repo("git", "widget", {})
    repeated = plugin.ws_create_repo("git", "widget", {})

    assert result is not None and result.status == "created"
    assert repeated is not None and repeated.status == "created"
    assert Path(result.repo_id).is_dir()
    assert (Path(result.repo_id) / "config").is_file()


def test_create_repo_carries_custom_paths_into_parsed_reference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_temporary_paths(monkeypatch, tmp_path)
    bare_path = tmp_path / "custom" / "widget.git"
    checkout_path = tmp_path / "checkouts" / "widget"

    result = bare_git.BareGitWorkspacePlugin().ws_create_repo(
        "git",
        "widget",
        {"bare_dir": str(bare_path), "checkout_dir": str(checkout_path)},
    )

    assert result is not None and result.status == "created"
    assert result.parsed.ref == str(bare_path)
    assert result.parsed.identity_key == f"git:{bare_path}"
    assert result.parsed.checkout_dir == f"{checkout_path}/"


def test_empty_precreated_repo_uses_bare_git_fresh_init_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_temporary_paths(monkeypatch, tmp_path)
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    bare_path = tmp_path / "precreated.git"
    _git_init_bare(bare_path)

    from sase.workspace_provider.plugins.bare_git_init import init_bare_git_project

    project_file = Path(
        init_bare_git_project(
            "adopted",
            existing_bare=str(bare_path),
            clone_dir=str(tmp_path / "checkout"),
        )
    )
    refs = subprocess.run(
        ["git", "--git-dir", str(bare_path), "show-ref", "--heads"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert project_file.is_file()
    assert refs.returncode == 0
    assert (tmp_path / "checkout" / ".git" / "config").is_file()


def test_describe_repo_creation_exposes_advanced_path_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_temporary_paths(monkeypatch, tmp_path)

    form = bare_git.BareGitWorkspacePlugin().ws_describe_repo_creation("git", "")

    assert form is not None
    assert [field.name for field in form.fields] == ["bare_dir"]
    assert all(field.group == "advanced" for field in form.fields)
    assert all(field.kind == "line" for field in form.fields)
