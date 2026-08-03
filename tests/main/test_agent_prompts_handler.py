"""Tests for ``sase agent prompts`` CLI handling."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from sase.agents import cli_prompts
from sase.agents_sync.models import ProjectTarget, SyncOutcome, TargetSelection
from sase.main.parser import create_parser, default_list_delegation_notice
from sase.repo_inventory import RepoCloneRecord, RepoInventory, RepoRecord


def _target(repo: Path, workspace: Path) -> ProjectTarget:
    return ProjectTarget(
        project_key="project-key",
        project="Project",
        primary_checkout=workspace,
        primary_roots=(workspace,),
        sidecar_path=repo,
        remote_url="git@example.test:project/agents.git",
    )


def _args(subcommand: str, **overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "prompts_subcommand": subcommand,
        "json": False,
        "month": None,
        "project": None,
        "show_warnings": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_bare_agent_prompts_defaults_to_list() -> None:
    args = create_parser().parse_args(["agent", "prompts"])

    assert args.prompts_subcommand == "list"
    assert default_list_delegation_notice(args) == (
        "No subcommand provided for 'sase agent prompts'; "
        "delegating to 'sase agent prompts list'."
    )


def test_prompt_month_rejects_invalid_format() -> None:
    parser = create_parser()

    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["agent", "prompts", "validate", "--month", "202613"])

    assert excinfo.value.code == 2


def test_prompt_list_and_validate_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = tmp_path / "agents"
    workspace = tmp_path / "workspace"
    prompt = repo / "prompts/202608/example.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("# Prompt\n", encoding="utf-8")
    target = _target(repo, workspace)
    monkeypatch.setattr(
        cli_prompts,
        "resolve_sync_targets",
        lambda _selectors=(): TargetSelection((target,), ()),
    )
    monkeypatch.setattr(cli_prompts, "_plans_repo", lambda _target: None)

    assert cli_prompts.handle_agents_prompts(_args("list", json=True)) == 0
    listing = json.loads(capsys.readouterr().out)
    assert listing[0]["path"] == "prompts/202608/example.md"

    assert cli_prompts.handle_agents_prompts(_args("validate", json=True)) == 0
    validation = json.loads(capsys.readouterr().out)
    assert validation["ok"] is True
    assert "legacy_files" not in validation
    assert validation["files"][0]["name"] == "example"


def test_prompt_show_prints_whole_archive_document(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = tmp_path / "agents"
    workspace = tmp_path / "workspace"
    prompt = repo / "prompts/202608/example.md"
    prompt.parent.mkdir(parents=True)
    content = "# Archive prompt\n\nUse #plan.\n"
    prompt.write_text(content, encoding="utf-8")
    target = _target(repo, workspace)
    monkeypatch.setattr(
        cli_prompts,
        "resolve_sync_targets",
        lambda _selectors=(): TargetSelection((target,), ()),
    )
    monkeypatch.setattr(cli_prompts, "_plans_repo", lambda _target: None)

    assert cli_prompts.handle_agents_prompts(_args("show", prompt="example")) == 0

    out = capsys.readouterr().out
    assert "prompts/202608/example.md" in out
    assert "# Archive prompt" in out
    assert "Use #plan." in out


def test_prompt_show_json_reports_whole_archive_document(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = tmp_path / "agents"
    workspace = tmp_path / "workspace"
    prompt = repo / "prompts/202608/example.md"
    prompt.parent.mkdir(parents=True)
    content = "# Archive prompt\n\nUse #plan.\n"
    prompt.write_text(content, encoding="utf-8")
    target = _target(repo, workspace)
    monkeypatch.setattr(
        cli_prompts,
        "resolve_sync_targets",
        lambda _selectors=(): TargetSelection((target,), ()),
    )
    monkeypatch.setattr(cli_prompts, "_plans_repo", lambda _target: None)

    assert (
        cli_prompts.handle_agents_prompts(_args("show", prompt="example", json=True))
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert "rendering" not in payload
    assert payload["content"] == content


@pytest.mark.parametrize(
    "selection, reason",
    [
        (
            TargetSelection(
                (),
                (
                    SyncOutcome(
                        "missing",
                        "missing",
                        error="project 'missing' was not found",
                    ),
                ),
            ),
            "project 'missing' was not found",
        ),
        (
            TargetSelection((), ()),
            "no project with an available agents sidecar was found",
        ),
    ],
)
def test_prompt_validate_reports_unavailable_context_as_skip(
    selection: TargetSelection,
    reason: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli_prompts,
        "resolve_sync_targets",
        lambda _selectors=(): selection,
    )

    assert cli_prompts.handle_agents_prompts(_args("validate", json=True)) == (
        cli_prompts.PROMPT_ARCHIVE_CONTEXT_UNAVAILABLE_EXIT_CODE
    )
    assert json.loads(capsys.readouterr().out) == {
        "ok": False,
        "skipped": True,
        "reason": reason,
    }


def test_prompt_validate_skips_when_agents_checkout_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = tmp_path / "missing-agents"
    target = _target(repo, tmp_path / "workspace")
    monkeypatch.setattr(
        cli_prompts,
        "resolve_sync_targets",
        lambda _selectors=(): TargetSelection((target,), ()),
    )

    assert cli_prompts.handle_agents_prompts(_args("validate")) == (
        cli_prompts.PROMPT_ARCHIVE_CONTEXT_UNAVAILABLE_EXIT_CODE
    )
    output = capsys.readouterr().out
    assert "Prompt archive validation skipped: context unavailable:" in output
    assert str(repo) in output.replace("\n", "")


def test_prompt_validate_keeps_invalid_archive_as_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = tmp_path / "agents"
    artifact = repo / "artifacts/202608/000000000000-example.txt"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("digest does not match the filename\n", encoding="utf-8")
    target = _target(repo, tmp_path / "workspace")
    monkeypatch.setattr(
        cli_prompts,
        "resolve_sync_targets",
        lambda _selectors=(): TargetSelection((target,), ()),
    )
    monkeypatch.setattr(cli_prompts, "_plans_repo", lambda _target: None)

    assert cli_prompts.handle_agents_prompts(_args("validate", json=True)) == 1
    validation = json.loads(capsys.readouterr().out)
    assert validation["ok"] is False
    assert validation["errors"][0]["code"] == "artifact-digest"
    assert "skipped" not in validation


def test_prompt_list_keeps_unavailable_context_as_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli_prompts,
        "resolve_sync_targets",
        lambda _selectors=(): TargetSelection((), ()),
    )

    assert cli_prompts.handle_agents_prompts(_args("list")) == 1
    assert "no project with an available agents sidecar was found" in (
        capsys.readouterr().err
    )


def test_plans_repo_uses_the_callers_workspace_clone(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary = tmp_path / "primary"
    current = tmp_path / "workspace-7"
    old_plans = tmp_path / "primary-plans"
    current_plans = tmp_path / "workspace-7-plans"
    for path in (primary, current, old_plans, current_plans):
        path.mkdir()
    target = _target(tmp_path / "agents", primary)
    clones = (
        RepoCloneRecord(0, str(primary), True),
        RepoCloneRecord(7, str(current), True),
    )
    plan_clones = (
        RepoCloneRecord(0, str(old_plans), True),
        RepoCloneRecord(7, str(current_plans), True),
    )
    inventory = RepoInventory(
        (
            RepoRecord(
                "project",
                "primary",
                "Project",
                "project-key",
                str(primary),
                True,
                False,
                None,
                "test",
                None,
                clones=clones,
            ),
            RepoRecord(
                "plans",
                "sidecar",
                "Project",
                "project-key",
                str(old_plans),
                True,
                True,
                None,
                "test",
                None,
                slug="plans",
                clones=plan_clones,
            ),
        )
    )
    monkeypatch.setattr(cli_prompts, "collect_repo_inventory", lambda **_kw: inventory)
    monkeypatch.chdir(current)

    assert cli_prompts._plans_repo(target) == current_plans
