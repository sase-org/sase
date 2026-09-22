"""AGENTS.md hint tests for ``sase repo open``."""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.main.repo_handler_open import handle_open_command
from sase.main.repo_handler_common import RepoMatchResolution
from sase.repo_inventory import RepoInventory
from tests.main.repo_handler_helpers import project_context, repo_record


def _args(repo: str) -> argparse.Namespace:
    return argparse.Namespace(
        repo=repo, project="demo", workspace=0, reason="phase test"
    )


def test_open_linked_with_agents_md_prints_hint_stdout_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    host_ctx = project_context(tmp_path)
    linked = repo_record(tmp_path, name="sase-core", kind="linked")
    (Path(linked.path) / "AGENTS.md").write_text("# sase-core\n", encoding="utf-8")

    monkeypatch.setattr(
        "sase.main.workspace_handler_list.prepare_opened_checkout",
        lambda *_args, **_kwargs: linked.path,
    )
    rc = handle_open_command(
        _args("sase-core"),
        collect_inventory=lambda **_kwargs: RepoInventory((linked,)),
        resolve_project_context=lambda _project: host_ctx,
        resolve_checkout=lambda *_args, **_kwargs: linked.path,
        resolve_workspace_num=lambda _ctx, _ws: 0,
        match_repo=lambda *_args, **_kwargs: RepoMatchResolution(
            record=linked, requested="sase-core", match_reason=None
        ),
        target_context=lambda _ctx, _repo: host_ctx,
        record_repo_open=lambda **_kwargs: None,
    )

    output = capsys.readouterr()
    assert rc == 0
    assert output.out == f"{linked.path}\n"
    assert output.err == (
        f"Read {linked.path}/AGENTS.md before working in this repo; "
        "it is not loaded automatically from here.\n"
    )


def test_open_linked_without_agents_md_leaves_stderr_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    host_ctx = project_context(tmp_path)
    linked = repo_record(tmp_path, name="sase-core", kind="linked")

    monkeypatch.setattr(
        "sase.main.workspace_handler_list.prepare_opened_checkout",
        lambda *_args, **_kwargs: linked.path,
    )
    rc = handle_open_command(
        _args("sase-core"),
        collect_inventory=lambda **_kwargs: RepoInventory((linked,)),
        resolve_project_context=lambda _project: host_ctx,
        resolve_checkout=lambda *_args, **_kwargs: linked.path,
        resolve_workspace_num=lambda _ctx, _ws: 0,
        match_repo=lambda *_args, **_kwargs: RepoMatchResolution(
            record=linked, requested="sase-core", match_reason=None
        ),
        target_context=lambda _ctx, _repo: host_ctx,
        record_repo_open=lambda **_kwargs: None,
    )

    output = capsys.readouterr()
    assert rc == 0
    assert output.out == f"{linked.path}\n"
    assert output.err == ""


def test_open_external_with_agents_md_prints_hint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    host_ctx = project_context(tmp_path)
    external_path = tmp_path / "external-click"
    external_path.mkdir()
    (external_path / "AGENTS.md").write_text("# click\n", encoding="utf-8")
    inventory = RepoInventory(())

    monkeypatch.setattr(
        "sase.main.repo_open_external.resolve_external_project_reference",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "sase.main.repo_open_external.open_external_repo",
        lambda *_args, **_kwargs: SimpleNamespace(
            canonical_name="click", path=str(external_path)
        ),
    )
    rc = handle_open_command(
        _args("gh:pallets/click"),
        collect_inventory=lambda **_kwargs: inventory,
        resolve_project_context=lambda _project: host_ctx,
        resolve_checkout=lambda *_args, **_kwargs: str(external_path),
        resolve_workspace_num=lambda _ctx, _ws: 0,
        match_repo=lambda *_args, **_kwargs: RepoMatchResolution(
            record=None, requested="gh:pallets/click", match_reason=None
        ),
        target_context=lambda _ctx, _repo: host_ctx,
        record_repo_open=lambda **_kwargs: None,
    )

    output = capsys.readouterr()
    assert rc == 0
    assert output.out == f"{external_path}\n"
    assert output.err == (
        f"Read {external_path}/AGENTS.md before working in this repo; "
        "it is not loaded automatically from here.\n"
    )


def test_open_own_primary_checkout_with_agents_md_prints_no_hint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    host_ctx = project_context(tmp_path)
    primary_path = host_ctx.primary_workspace_dir
    (Path(primary_path) / "AGENTS.md").write_text("# demo\n", encoding="utf-8")
    primary = replace(
        repo_record(tmp_path, name="demo", kind="primary"), path=primary_path
    )

    monkeypatch.setattr(
        "sase.main.workspace_handler_list.prepare_opened_checkout",
        lambda *_args, **_kwargs: primary_path,
    )
    rc = handle_open_command(
        _args("demo"),
        collect_inventory=lambda **_kwargs: RepoInventory((primary,)),
        resolve_project_context=lambda _project: host_ctx,
        resolve_checkout=lambda *_args, **_kwargs: primary_path,
        resolve_workspace_num=lambda _ctx, _ws: 0,
        match_repo=lambda *_args, **_kwargs: RepoMatchResolution(
            record=primary, requested="demo", match_reason=None
        ),
        target_context=lambda _ctx, _repo: host_ctx,
        record_repo_open=lambda **_kwargs: None,
    )

    output = capsys.readouterr()
    assert rc == 0
    assert output.out == f"{primary_path}\n"
    assert output.err == ""
