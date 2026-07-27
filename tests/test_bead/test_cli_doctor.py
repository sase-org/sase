"""CLI coverage for bead design-reference diagnosis and repair."""

from __future__ import annotations

import argparse
from contextlib import contextmanager, nullcontext
import json
from pathlib import Path
from types import SimpleNamespace
from collections.abc import Iterator

import pytest

from sase.bead import cli_admin
from sase.bead.design_ref_repair import (
    DesignRefRepairPreview,
    _DesignRefRepair,
)
from sase.bead.model import Issue, IssueType
from sase.bead.project import BeadProject
from sase.main.parser import create_parser
from sase.sdd import plan_refs


def test_doctor_parser_accepts_fix_aliases_and_documents_help(
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = create_parser()
    for flag in ("-F", "--fix-design-refs"):
        args = parser.parse_args(["bead", "doctor", flag])
        assert args.fix_design_refs is True

    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["bead", "doctor", "-h"])
    assert excinfo.value.code == 0
    assert "--fix-design-refs" in capsys.readouterr().out


def test_plain_doctor_forwards_roots_without_planning_or_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    roots = (tmp_path / "store", tmp_path / "local")
    calls: list[tuple[Path, ...]] = []

    class Project:
        def doctor(self, plan_roots: tuple[Path, ...]) -> list[str]:
            calls.append(plan_roots)
            return ["OK"]

    monkeypatch.setattr(cli_admin, "_resolve_doctor_plan_roots", lambda: roots)
    monkeypatch.setattr(cli_admin, "get_project", lambda: nullcontext(Project()))
    monkeypatch.setattr(
        cli_admin,
        "plan_design_ref_repairs",
        lambda *_args, **_kwargs: pytest.fail("plain doctor planned repairs"),
    )
    monkeypatch.setattr(
        cli_admin,
        "bead_store_mutation",
        lambda *_args: pytest.fail("plain doctor opened a mutation"),
    )

    cli_admin.handle_bead_doctor(argparse.Namespace(fix_design_refs=False))

    assert calls == [roots]
    assert capsys.readouterr().out == "OK\n"


def test_doctor_root_discovery_degrades_to_explicit_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        plan_refs,
        "workspace_context_for_plan_resolution",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("unavailable")),
    )

    assert cli_admin._resolve_doctor_plan_roots() == ()


def test_fix_preview_cancellation_never_opens_mutation(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue = Issue(id="beads-1", title="One", design="/old/one.md")
    preview = DesignRefRepairPreview(
        repairs=(
            _DesignRefRepair(
                bead_id="beads-1",
                old_reference="/old/one.md",
                new_reference="plans:202607/one.md",
            ),
        ),
        unrepaired=(),
    )
    project = SimpleNamespace(
        doctor=lambda _roots: ["WARNING"],
        list_issues=lambda: [issue],
    )
    monkeypatch.setattr(cli_admin, "_resolve_doctor_plan_roots", lambda: ())
    monkeypatch.setattr(cli_admin, "get_project", lambda: nullcontext(project))
    monkeypatch.setattr(
        cli_admin,
        "plan_design_ref_repairs",
        lambda *_args, **_kwargs: preview,
    )
    monkeypatch.setattr(
        cli_admin,
        "_confirm_design_ref_repairs",
        lambda _count: False,
    )
    monkeypatch.setattr(
        cli_admin,
        "bead_store_mutation",
        lambda *_args: pytest.fail("cancelled repair opened a mutation"),
    )

    cli_admin.handle_bead_doctor(argparse.Namespace(fix_design_refs=True))

    output = capsys.readouterr().out
    assert "/old/one.md -> plans:202607/one.md" in output
    assert "cancelled; no changes applied" in output


def test_confirmed_fix_uses_update_events_and_one_aggregate_commit(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plans_root = project_dir / "sdd/plans"
    plan = plans_root / "202607/one.md"
    plan.parent.mkdir(parents=True)
    with BeadProject(project_dir) as project:
        issue = project.create(
            "One",
            IssueType.PLAN,
            design=str(plan),
        )
    plan.write_text(
        f"---\nbead_id: {issue.id}\n---\n# One\n",
        encoding="utf-8",
    )
    commits: list[tuple[str, dict[str, object]]] = []

    def auto_commit(message: str, **kwargs: object) -> bool:
        commits.append((message, kwargs))
        return False

    monkeypatch.setattr(
        cli_admin,
        "_resolve_doctor_plan_roots",
        lambda: (plans_root,),
    )
    monkeypatch.setattr(
        cli_admin,
        "_confirm_design_ref_repairs",
        lambda _count: True,
    )
    monkeypatch.setattr(cli_admin, "auto_commit_bead_store", auto_commit)

    cli_admin.handle_bead_doctor(argparse.Namespace(fix_design_refs=True))

    with BeadProject(project_dir) as project:
        assert project.show(issue.id).design == "plans:202607/one.md"
    stream = project_dir / f"sdd/beads/events/streams/{issue.id}.jsonl"
    operations = [
        json.loads(line)["operation"]
        for line in stream.read_text(encoding="utf-8").splitlines()
    ]
    assert operations.count("issue_updated") == 1
    assert len(commits) == 1
    assert commits[0][0] == "chore(beads): repair 1 design reference"
    assert commits[0][1]["push_after_commit"] is False
    assert "already_locked" in commits[0][1]


def test_stale_preview_performs_no_updates_or_commit(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    original = DesignRefRepairPreview(
        repairs=(
            _DesignRefRepair(
                "beads-1",
                "/old/one.md",
                "plans:202607/one.md",
            ),
        ),
        unrepaired=(),
    )
    stale = DesignRefRepairPreview(repairs=(), unrepaired=())
    project = SimpleNamespace(
        doctor=lambda _roots: ["WARNING"],
        list_issues=lambda: [],
        update=lambda *_args, **_kwargs: pytest.fail("stale preview updated"),
    )
    previews = iter((original, stale))

    @contextmanager
    def mutation_scope(
        _auto_commit: object,
    ) -> Iterator[SimpleNamespace]:
        yield SimpleNamespace(
            project=project,
            commit=lambda _message: pytest.fail("stale preview committed"),
        )

    monkeypatch.setattr(cli_admin, "_resolve_doctor_plan_roots", lambda: ())
    monkeypatch.setattr(cli_admin, "get_project", lambda: nullcontext(project))
    monkeypatch.setattr(
        cli_admin,
        "plan_design_ref_repairs",
        lambda *_args, **_kwargs: next(previews),
    )
    monkeypatch.setattr(
        cli_admin,
        "_confirm_design_ref_repairs",
        lambda _count: True,
    )
    monkeypatch.setattr(cli_admin, "bead_store_mutation", mutation_scope)

    cli_admin.handle_bead_doctor(argparse.Namespace(fix_design_refs=True))

    assert "changed after the preview" in capsys.readouterr().err


def test_confirmation_requires_interactive_yes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli_admin.sys,
        "stdin",
        SimpleNamespace(isatty=lambda: False),
    )
    assert cli_admin._confirm_design_ref_repairs(1) is False

    monkeypatch.setattr(
        cli_admin.sys,
        "stdin",
        SimpleNamespace(isatty=lambda: True),
    )
    monkeypatch.setattr(
        "builtins.input",
        lambda _prompt: (_ for _ in ()).throw(EOFError),
    )
    assert cli_admin._confirm_design_ref_repairs(1) is False
