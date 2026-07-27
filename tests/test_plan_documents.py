"""Tests for stable local plan resolution and commit-footer loading."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from sase.plan_documents import (
    PlanDocument,
    PlanWorkspace,
    load_commit_plan_document,
    resolve_plan_path,
)


def _owner(workspace: Path, plans: Path) -> PlanWorkspace:
    return PlanWorkspace(
        workspace_dir=str(workspace),
        plans_root=str(plans),
        project="alpha",
    )


@pytest.mark.parametrize(
    ("reference", "location"),
    (
        ("docs/plan.md", "repo"),
        ("notes/plan.md", "workspace"),
        ("sdd/plans/202607/plan.md", "plans"),
        (".sase/sdd/plans/202607/plan.md", "plans"),
        ("plans/202607/plan.md", "plans"),
        ("plans:202607/plan.md", "plans"),
        ("202607/plan.md", "plans"),
    ),
)
def test_resolves_every_repository_and_store_relative_form(
    tmp_path: Path,
    reference: str,
    location: str,
) -> None:
    repo = tmp_path / "repo"
    workspace = tmp_path / "workspace"
    plans = tmp_path / "plans"
    relative = {
        "repo": Path(reference),
        "workspace": Path(reference),
        "plans": Path("202607/plan.md"),
    }[location]
    root = {"repo": repo, "workspace": workspace, "plans": plans}[location]
    expected = root / relative
    expected.parent.mkdir(parents=True, exist_ok=True)
    expected.write_text("# Local plan\n", encoding="utf-8")

    resolved = resolve_plan_path(
        reference,
        repo_dir=str(repo),
        workspaces=(_owner(workspace, plans),),
    )

    assert resolved.status == "success"
    assert resolved.path == str(expected.resolve())


def test_resolves_absolute_and_home_relative_references(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    plan = home / "plans" / "home.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Home plan\n", encoding="utf-8")
    original_expanduser = Path.expanduser

    def expanduser(path: Path) -> Path:
        value = str(path)
        if value == "~/plans/home.md":
            return plan
        return original_expanduser(path)

    monkeypatch.setattr(Path, "expanduser", expanduser)

    absolute = resolve_plan_path(str(plan))
    home_relative = resolve_plan_path("~/plans/home.md")

    assert absolute.status == "success"
    assert home_relative.status == "success"
    assert home_relative.path == str(plan.resolve())


def test_commit_footer_loads_plain_and_markdown_linked_plan_values(
    tmp_path: Path,
) -> None:
    plan = tmp_path / "202607" / "plan.md"
    plan.parent.mkdir()
    plan.write_text("# Attached plan\n", encoding="utf-8")
    owner = _owner(tmp_path / "workspace", tmp_path)

    plain = load_commit_plan_document(
        "Subject\n\nSASE_PLAN=202607/plan.md",
        repo_dir=None,
        workspaces=(owner,),
    )
    linked = load_commit_plan_document(
        "Subject\n\nSASE_PLAN=[202607/plan.md][1]\n\n"
        "[1]: https://example.test/remote-plan.md",
        repo_dir=None,
        workspaces=(owner,),
    )

    assert plain.available is True
    assert plain.content == "# Attached plan\n"
    assert linked.available is True
    assert linked.reference == "202607/plan.md"
    assert linked.destination == "https://example.test/remote-plan.md"
    assert linked.path == str(plan.resolve())


def test_commit_footer_requires_terminal_prefixed_tag_and_keeps_last_value(
    tmp_path: Path,
) -> None:
    plans = tmp_path / "plans"
    plans.mkdir()
    (plans / "new.md").write_text("# New\n", encoding="utf-8")
    owner = _owner(tmp_path / "workspace", plans)

    non_terminal = load_commit_plan_document(
        "Subject\n\nSASE_PLAN=old.md\n\nTrailing prose",
        repo_dir=None,
        workspaces=(owner,),
    )
    unprefixed = load_commit_plan_document(
        "Subject\n\nPLAN=new.md",
        repo_dir=None,
        workspaces=(owner,),
    )
    duplicate = load_commit_plan_document(
        "Subject\n\nSASE_PLAN=old.md\nSASE_PLAN=new.md",
        repo_dir=None,
        workspaces=(owner,),
    )

    assert non_terminal.status == "missing_tag"
    assert unprefixed.status == "missing_tag"
    assert duplicate.available is True
    assert duplicate.reference == "new.md"


def test_resolution_tries_every_candidate_owner(tmp_path: Path) -> None:
    second_plans = tmp_path / "second-plans"
    plan = second_plans / "202607" / "shared.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Shared owner\n", encoding="utf-8")

    resolved = resolve_plan_path(
        "202607/shared.md",
        workspaces=(
            _owner(tmp_path / "first", tmp_path / "first-plans"),
            _owner(tmp_path / "second", second_plans),
        ),
    )

    assert resolved.status == "success"
    assert resolved.path == str(plan.resolve())


def test_typed_plan_failures_cover_invalid_missing_non_file_and_unreadable(
    tmp_path: Path,
) -> None:
    plans = tmp_path / "plans"
    plans.mkdir()
    directory = plans / "directory"
    directory.mkdir()
    invalid_utf8 = plans / "binary.md"
    invalid_utf8.write_bytes(b"\xff\xfe")
    unreadable = plans / "unreadable.md"
    unreadable.write_text("# Hidden\n", encoding="utf-8")
    owner = _owner(tmp_path / "workspace", plans)

    def load(
        reference: str,
        *,
        read_text: Callable[[Path], str] | None = None,
    ) -> PlanDocument:
        return load_commit_plan_document(
            f"Subject\n\nSASE_PLAN={reference}",
            repo_dir=None,
            workspaces=(owner,),
            read_text=read_text,
        )

    invalid = load("bad\x00reference")
    missing = load("missing.md")
    non_file = load("directory")
    non_utf8 = load("binary.md")

    def fail_read(_path: Path) -> str:
        raise PermissionError("private host detail")

    read_error = load("unreadable.md", read_text=fail_read)

    assert invalid.status == "invalid_reference"
    assert missing.status == "missing_file"
    assert non_file.status == "not_file"
    assert non_utf8.status == "unreadable"
    assert non_utf8.detail is not None and "UTF-8" in non_utf8.detail
    assert read_error.status == "unreadable"
