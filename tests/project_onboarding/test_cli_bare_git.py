"""Bare-git create end-to-end tests split from ``test_cli``."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sase import workspace_provider
from sase.main.parser import create_parser
from sase.main import project_handler_add as add_cli
from sase.project_onboarding.journal import lookup_journal

from ._cli_test_support import make_create_args


def _bare_git_create_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path]:
    from sase.workspace_provider.plugins import bare_git_workspace as bare_git

    home = tmp_path / "home"
    home.mkdir()
    sase_home = tmp_path / "sase-home"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: home))
    monkeypatch.setattr(
        bare_git.os.path,
        "expanduser",
        lambda value: (
            str(home / str(value)[2:]) if str(value).startswith("~/") else value
        ),
    )
    monkeypatch.setattr(add_cli, "detect_actor", lambda **_kwargs: "human")
    monkeypatch.setattr(
        "sase.project_onboarding._apply_run.detect_actor", lambda **_kwargs: "human"
    )
    return home, sase_home


def test_bare_git_create_end_to_end(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home, sase_home = _bare_git_create_home(tmp_path, monkeypatch)
    assert (
        add_cli.handle_create(
            make_create_args(["git:tools", "--check", "--json", "--no-setup"])
        )
        == 0
    )
    document = json.loads(capsys.readouterr().out)
    argv = document["apply_argv"]
    assert argv[0:4] == ["sase", "project", "create", "git:tools"]
    assert "--visibility" not in argv
    assert "--no-setup" in argv
    emitted = create_parser(only="project").parse_args(argv[1:])
    assert add_cli.handle_create(emitted) == 0
    assert (sase_home / "repos" / "tools.git" / "HEAD").is_file()
    assert (home / "projects" / "git" / "tools" / ".git").exists()


def test_bare_git_create_honors_custom_bare_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, sase_home = _bare_git_create_home(tmp_path, monkeypatch)
    custom_bare = tmp_path / "custom" / "tools.git"
    args = make_create_args(
        [
            "git:tools",
            "--yes",
            "--no-setup",
            "--option",
            f"bare_dir={custom_bare}",
        ]
    )
    assert add_cli.handle_create(args) == 0
    assert (custom_bare / "HEAD").is_file()
    assert not (sase_home / "repos" / "tools.git").exists()
    assert (home / "projects" / "git" / "tools" / ".git").exists()


def test_bare_git_create_resumes_after_checkout_failure_with_custom_bare_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home, sase_home = _bare_git_create_home(tmp_path, monkeypatch)
    from sase.workspace_provider.plugins.bare_git_workspace import (
        BareGitWorkspacePlugin,
    )

    custom_bare = tmp_path / "custom" / "tools.git"
    args = make_create_args(
        [
            "git:tools",
            "--yes",
            "--no-setup",
            "--option",
            f"bare_dir={custom_bare}",
        ]
    )
    planned_identity = BareGitWorkspacePlugin().ws_parse_repo_ref("git", "tools")
    assert planned_identity is not None

    create_calls: list[tuple[Any, ...]] = []
    original_create = workspace_provider.create_repo

    def counted_create(*call_args: Any, **call_kwargs: Any) -> Any:
        create_calls.append(call_args)
        return original_create(*call_args, **call_kwargs)

    monkeypatch.setattr(workspace_provider, "create_repo", counted_create)
    original_resolve = workspace_provider.resolve_ref
    resolve_calls = 0
    resolved_refs: list[str] = []

    def fail_checkout_once(ref: str, workflow_type: str) -> Any:
        nonlocal resolve_calls
        resolve_calls += 1
        resolved_refs.append(ref)
        if resolve_calls == 1:
            raise RuntimeError("injected checkout failure")
        return original_resolve(ref, workflow_type)

    monkeypatch.setattr(workspace_provider, "resolve_ref", fail_checkout_once)
    assert add_cli.handle_create(args) == 1
    capsys.readouterr()
    first_journal = lookup_journal(planned_identity.identity_key)
    assert first_journal is not None
    assert first_journal["status"] == "failed"
    assert first_journal["remote"]["adopted_ref"] == str(custom_bare)
    assert first_journal["remote"]["adopted_identity_key"] == f"git:{custom_bare}"
    first_created_at = first_journal["remote"]["created_at"]
    assert (custom_bare / "HEAD").is_file()
    assert not (sase_home / "repos" / "tools.git").exists()

    assert add_cli.handle_create(args) == 0
    capsys.readouterr()
    resumed_journal = lookup_journal(planned_identity.identity_key)
    assert resumed_journal is not None
    assert resumed_journal["status"] == "complete"
    assert resumed_journal["remote"]["adopted_identity_key"] == f"git:{custom_bare}"
    assert len(create_calls) == 2  # The provider recognizes the existing bare path.
    assert resolve_calls == 2
    assert resolved_refs == [str(custom_bare), str(custom_bare)]
    assert resumed_journal["remote"]["created_at"] == first_created_at
    assert list(tmp_path.rglob("tools.git")) == [custom_bare]
    assert (home / "projects" / "git" / "tools" / ".git").exists()
