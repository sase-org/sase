"""External-repository opening tests for ``sase repo``."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.linked_repos import opened_external_repo_records
from sase.main.parser import create_parser
from sase.main.repo_handler import handle_repo_command
from sase.repo_inventory import RepoInventory
from sase.repo_open_log import read_repo_open_events
from sase.workspace_provider import ExternalRepoCloneResult
from tests.main.repo_handler_helpers import (
    init_git_repo,
    project_context,
    project_record,
    repo_record,
)


def test_repo_open_registered_project_clones_locally_and_reopens_without_cleaning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state = tmp_path / "state"
    artifacts = tmp_path / "artifacts"
    monkeypatch.setenv("SASE_HOME", str(state))
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    monkeypatch.setenv("SASE_AGENT_NAME", "phase-two")

    host_ctx = project_context(tmp_path)
    source = tmp_path / "other-primary"
    init_git_repo(source)
    registered_project = project_record("other", source)
    inventory = RepoInventory((repo_record(tmp_path, name="demo", kind="primary"),))
    monkeypatch.setattr(
        "sase.main.workspace_handler._resolve_project_context",
        lambda _project: host_ctx,
    )
    monkeypatch.setattr(
        "sase.main.workspace_handler._resolve_checkout_path",
        lambda _ctx, _workspace, *, materialize: host_ctx.primary_workspace_dir,
    )
    monkeypatch.setattr(
        "sase.main.repo_handler.collect_repo_inventory",
        lambda **_kwargs: inventory,
    )
    monkeypatch.setattr(
        "sase.main.repo_open_external.list_project_records",
        lambda *_args, **_kwargs: [registered_project],
    )

    args = create_parser().parse_args(
        ["repo", "open", "other", "-p", "demo", "-r", "port fix", "-w", "0"]
    )
    with pytest.raises(SystemExit) as first_exit:
        handle_repo_command(args)

    assert first_exit.value.code == 0
    first = capsys.readouterr()
    expected = (
        Path(host_ctx.primary_workspace_dir)
        / "sase"
        / "repos"
        / "external"
        / "projects"
        / "other"
    )
    assert first.out == f"{expected}\n"
    assert (expected / ".git").is_dir()
    exclude = expected / ".git" / "info" / "exclude"
    exclude_lines = exclude.read_text(encoding="utf-8").splitlines()
    assert exclude_lines.count(".sase/") == 1
    assert exclude_lines.count("/sase/repos/") == 1

    dirty = expected / "keep-me.txt"
    dirty.write_text("agent work\n", encoding="utf-8")
    with pytest.raises(SystemExit) as second_exit:
        handle_repo_command(args)

    assert second_exit.value.code == 0
    assert capsys.readouterr().out == f"{expected}\n"
    assert dirty.read_text(encoding="utf-8") == "agent work\n"
    exclude_lines = exclude.read_text(encoding="utf-8").splitlines()
    assert exclude_lines.count(".sase/") == 1
    assert exclude_lines.count("/sase/repos/") == 1
    marker = opened_external_repo_records(artifacts)["other"]
    assert marker["workspace_dir"] == str(expected)
    assert marker["reason"] == "port fix"
    events = read_repo_open_events(project="demo")
    assert [event.repo_kind for event in events] == ["external", "external"]
    assert [event.repo for event in events] == ["other", "other"]


def test_repo_open_provider_ref_is_atomic_audited_and_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state = tmp_path / "state"
    artifacts = tmp_path / "artifacts"
    monkeypatch.setenv("SASE_HOME", str(state))
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    monkeypatch.setenv("SASE_AGENT_NAME", "phase-two")
    host_ctx = project_context(tmp_path)
    clone_calls: list[tuple[str, str, str]] = []

    def clone(scheme: str, ref: str, dest_dir: str) -> ExternalRepoCloneResult:
        clone_calls.append((scheme, ref, dest_dir))
        init_git_repo(Path(dest_dir))
        return ExternalRepoCloneResult(
            canonical_name="gh:acme/widget",
            dest_dir=dest_dir,
            default_branch="main",
        )

    monkeypatch.setattr(
        "sase.main.workspace_handler._resolve_project_context",
        lambda _project: host_ctx,
    )
    monkeypatch.setattr(
        "sase.main.workspace_handler._resolve_checkout_path",
        lambda _ctx, _workspace, *, materialize: host_ctx.primary_workspace_dir,
    )
    monkeypatch.setattr(
        "sase.main.repo_handler.collect_repo_inventory",
        lambda **_kwargs: RepoInventory(()),
    )
    monkeypatch.setattr(
        "sase.main.repo_open_external.list_project_records",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        "sase.main.repo_open_external.get_external_repo_schemes", lambda: {"gh"}
    )
    monkeypatch.setattr("sase.main.repo_open_external.clone_external_repo", clone)

    args = create_parser().parse_args(
        [
            "repo",
            "open",
            "acme/widget",
            "-p",
            "demo",
            "-r",
            "inspect upstream",
            "-w",
            "0",
        ]
    )
    with pytest.raises(SystemExit) as first_exit:
        handle_repo_command(args)

    assert first_exit.value.code == 0
    expected = (
        Path(host_ctx.primary_workspace_dir)
        / "sase"
        / "repos"
        / "external"
        / "gh"
        / "acme"
        / "widget"
    )
    assert capsys.readouterr().out == f"{expected}\n"
    assert len(clone_calls) == 1
    assert clone_calls[0][:2] == ("gh", "acme/widget")
    assert Path(clone_calls[0][2]).parent == expected.parent
    assert Path(clone_calls[0][2]) != expected

    dirty = expected / "keep-me.txt"
    dirty.write_text("agent work\n", encoding="utf-8")
    with pytest.raises(SystemExit) as second_exit:
        handle_repo_command(args)

    assert second_exit.value.code == 0
    assert capsys.readouterr().out == f"{expected}\n"
    assert len(clone_calls) == 1
    assert dirty.is_file()
    marker = opened_external_repo_records(artifacts)["gh:acme/widget"]
    assert marker["ref"] == "gh:acme/widget"
    assert marker["reason"] == "inspect upstream"
    assert [event.repo for event in read_repo_open_events(project="demo")] == [
        "gh:acme/widget",
        "gh:acme/widget",
    ]


def test_repo_open_provider_failure_removes_staging_and_records_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state = tmp_path / "state"
    artifacts = tmp_path / "artifacts"
    monkeypatch.setenv("SASE_HOME", str(state))
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    host_ctx = project_context(tmp_path)

    def fail_clone(_scheme: str, _ref: str, dest_dir: str) -> ExternalRepoCloneResult:
        partial = Path(dest_dir)
        partial.mkdir(parents=True)
        (partial / "partial").write_text("nope", encoding="utf-8")
        raise RuntimeError("GitHub clone failed; run 'gh auth login'")

    monkeypatch.setattr(
        "sase.main.workspace_handler._resolve_project_context",
        lambda _project: host_ctx,
    )
    monkeypatch.setattr(
        "sase.main.workspace_handler._resolve_checkout_path",
        lambda _ctx, _workspace, *, materialize: host_ctx.primary_workspace_dir,
    )
    monkeypatch.setattr(
        "sase.main.repo_handler.collect_repo_inventory",
        lambda **_kwargs: RepoInventory(()),
    )
    monkeypatch.setattr(
        "sase.main.repo_open_external.list_project_records",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        "sase.main.repo_open_external.get_external_repo_schemes", lambda: {"gh"}
    )
    monkeypatch.setattr("sase.main.repo_open_external.clone_external_repo", fail_clone)
    args = create_parser().parse_args(
        ["repo", "open", "gh:acme/widget", "-r", "inspect", "-w", "0"]
    )

    with pytest.raises(SystemExit) as exc_info:
        handle_repo_command(args)

    assert exc_info.value.code == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "gh auth login" in output.err
    external_root = Path(host_ctx.primary_workspace_dir) / "sase" / "repos" / "external"
    assert not (external_root / "gh" / "acme" / "widget").exists()
    assert not list(external_root.rglob("*.clone-tmp-*"))
    assert opened_external_repo_records(artifacts) == {}
    assert read_repo_open_events(project="demo") == ()


def test_repo_open_missing_provider_lists_registered_schemes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    host_ctx = project_context(tmp_path)
    monkeypatch.setattr(
        "sase.main.workspace_handler._resolve_project_context",
        lambda _project: host_ctx,
    )
    monkeypatch.setattr(
        "sase.main.workspace_handler._resolve_checkout_path",
        lambda _ctx, _workspace, *, materialize: host_ctx.primary_workspace_dir,
    )
    monkeypatch.setattr(
        "sase.main.repo_handler.collect_repo_inventory",
        lambda **_kwargs: RepoInventory(()),
    )
    monkeypatch.setattr(
        "sase.main.repo_open_external.list_project_records",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        "sase.main.repo_open_external.get_external_repo_schemes", lambda: {"gl"}
    )
    args = create_parser().parse_args(
        ["repo", "open", "gh:acme/widget", "-r", "inspect", "-w", "0"]
    )

    with pytest.raises(SystemExit) as exc_info:
        handle_repo_command(args)

    assert exc_info.value.code == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "Install or upgrade sase-github" in output.err
    assert "Registered external schemes: gl" in output.err
