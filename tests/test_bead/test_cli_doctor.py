"""CLI coverage for bead design-reference diagnosis and repair."""

from __future__ import annotations

import argparse
from contextlib import contextmanager, nullcontext
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from types import SimpleNamespace
from collections.abc import Iterator

import pytest

from sase.bead import cli_admin
from sase.bead.config import load_config, save_config
from sase.bead.design_ref_repair import (
    DesignRefRepairPreview,
    _DesignRefRepair,
)
from sase.bead.model import Issue, IssueType
from sase.bead.project import BeadProject
from sase.main.parser import create_parser
from sase.sdd import plan_refs
from tests.test_bead.resolution_test_helpers import isolate_bead_store_resolution


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


def test_doctor_parser_accepts_projection_repair_and_yes_aliases(
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = create_parser()
    for flag in ("-P", "--fix-projection"):
        args = parser.parse_args(["bead", "doctor", flag])
        assert args.fix_projection is True
    for flag in ("-y", "--yes"):
        args = parser.parse_args(["bead", "doctor", flag])
        assert args.yes is True

    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["bead", "doctor", "-h"])
    assert excinfo.value.code == 0
    help_text = capsys.readouterr().out
    assert "--fix-projection" in help_text
    assert "--yes" in help_text


def test_doctor_parser_accepts_fix_issue_prefix_alias_and_documents_help(
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = create_parser()
    for flag in ("-I", "--fix-issue-prefix"):
        args = parser.parse_args(["bead", "doctor", flag])
        assert args.fix_issue_prefix is True

    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["bead", "doctor", "-h"])
    assert excinfo.value.code == 0
    assert "--fix-issue-prefix" in capsys.readouterr().out


def _doctor_args(**overrides: bool) -> argparse.Namespace:
    defaults = {
        "fix_design_refs": False,
        "fix_issue_prefix": False,
        "fix_projection": False,
        "yes": False,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_doctor_warns_about_leaked_key_prefix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject.init(tmp_path):
        pass
    beads_dir = tmp_path / "sdd" / "beads"
    stale_config = load_config(beads_dir)
    stale_config["issue_prefix"] = "gh_bobs-org__bob-cli"
    save_config(beads_dir, stale_config)

    monkeypatch.setattr(
        "sase.bead.prefix_policy.infer_project_name_from_cwd",
        lambda: "gh_bobs-org__bob-cli",
    )
    monkeypatch.setattr(
        "sase.project_display_names.project_display_name_for",
        lambda _key, *_args, **_kwargs: "bob-cli",
    )
    isolate_bead_store_resolution(monkeypatch, tmp_path)

    cli_admin.handle_bead_doctor(_doctor_args())

    output = capsys.readouterr().out
    assert (
        "WARNING: bead issue prefix 'gh_bobs-org__bob-cli' is a ProjectSpec key; "
        "project name is 'bob-cli' "
        "(repair with: sase bead doctor --fix-issue-prefix)"
    ) in output


def test_doctor_omits_prefix_warning_for_correctly_prefixed_store(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cli_admin.handle_bead_doctor(_doctor_args())

    output = capsys.readouterr().out
    assert "is a ProjectSpec key" not in output


def test_fix_issue_prefix_rewrites_config_and_preserves_existing_ids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject.init(tmp_path) as project:
        issue = project.create("One", IssueType.PLAN)
    beads_dir = tmp_path / "sdd" / "beads"
    stale_config = load_config(beads_dir)
    stale_config["issue_prefix"] = "gh_bobs-org__bob-cli"
    save_config(beads_dir, stale_config)

    monkeypatch.setattr(
        "sase.bead.prefix_policy.infer_project_name_from_cwd",
        lambda: "gh_bobs-org__bob-cli",
    )
    monkeypatch.setattr(
        "sase.project_display_names.project_display_name_for",
        lambda _key, *_args, **_kwargs: "bob-cli",
    )
    isolate_bead_store_resolution(monkeypatch, tmp_path)

    before_config = json.loads((tmp_path / "sdd/beads/config.json").read_text())

    commits: list[str] = []

    def auto_commit(message: str, **_kwargs: object) -> bool:
        commits.append(message)
        return False

    monkeypatch.setattr(cli_admin, "auto_commit_bead_store", auto_commit)

    cli_admin.handle_bead_doctor(_doctor_args(fix_issue_prefix=True, yes=True))

    output = capsys.readouterr().out
    assert "gh_bobs-org__bob-cli -> bob-cli" in output
    assert "Repaired bead issue prefix" in output

    after_config = json.loads((tmp_path / "sdd/beads/config.json").read_text())
    assert after_config["issue_prefix"] == "bob-cli"
    assert after_config["next_counter"] == before_config["next_counter"]
    assert commits == [
        "chore(beads): repair issue prefix gh_bobs-org__bob-cli -> bob-cli"
    ]

    with BeadProject(tmp_path) as project:
        assert project.show(issue.id).id == issue.id


def test_fix_issue_prefix_with_nothing_to_repair(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cli_admin.handle_bead_doctor(_doctor_args(fix_issue_prefix=True, yes=True))

    assert "No issue prefix to repair." in capsys.readouterr().out


def test_plain_doctor_forwards_roots_without_planning_or_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    roots = (tmp_path / "store", tmp_path / "local")
    calls: list[tuple[tuple[Path, ...], object | None]] = []

    class Project:
        def doctor(
            self,
            plan_roots: tuple[Path, ...],
            reference_context: object | None,
        ) -> list[str]:
            calls.append((plan_roots, reference_context))
            return ["OK"]

    monkeypatch.setattr(cli_admin, "_resolve_doctor_plan_roots", lambda: roots)
    monkeypatch.setattr(
        cli_admin,
        "_resolve_doctor_reference_context",
        lambda: None,
    )
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

    assert calls == [(roots, None)]
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
        doctor=lambda _roots, _context: ["WARNING"],
        list_issues=lambda: [issue],
    )
    monkeypatch.setattr(cli_admin, "_resolve_doctor_plan_roots", lambda: ())
    monkeypatch.setattr(
        cli_admin,
        "_resolve_doctor_reference_context",
        lambda: None,
    )
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
        doctor=lambda _roots, _context: ["WARNING"],
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


def test_fix_projection_repairs_expected_drift_and_second_run_is_noop(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as project:
        issue = project.create("One", IssueType.PLAN)
        project.close([issue.id], reason="shipped")
    first_close, second_close = _append_redundant_close_and_stale_projection(
        project_dir,
        issue.id,
    )
    commits: list[str] = []

    def auto_commit(message: str, **_kwargs: object) -> bool:
        commits.append(message)
        return False

    monkeypatch.setattr(cli_admin, "auto_commit_bead_store", auto_commit)
    args = argparse.Namespace(
        fix_design_refs=False,
        fix_projection=True,
        yes=True,
    )

    cli_admin.handle_bead_doctor(args)

    output = capsys.readouterr().out
    assert "Projection repair preview:" in output
    assert f"{json.dumps(second_close)} -> {json.dumps(first_close)}" in output
    assert "Reprojected 1 bead row from canonical events" in output
    assert commits == ["chore(beads): reproject bead state from canonical events"]
    with BeadProject(project_dir) as project:
        report = project.doctor_report()
        repaired = project.show(issue.id)
    assert report["projection_drift"] == []
    assert repaired.closed_at == first_close
    assert repaired.close_reason == "shipped"

    cli_admin.handle_bead_doctor(args)

    assert "No projection drift to repair." in capsys.readouterr().out
    assert commits == ["chore(beads): reproject bead state from canonical events"]


def test_fix_projection_refuses_row_set_drift(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as project:
        issue = project.create("One", IssueType.PLAN)
    projection = project_dir / "sdd/beads/issues.jsonl"
    projection.write_text("", encoding="utf-8")
    before = projection.read_bytes()
    monkeypatch.setattr(
        cli_admin,
        "bead_store_mutation",
        lambda *_args: pytest.fail("unsafe projection repair opened a mutation"),
    )

    cli_admin.handle_bead_doctor(
        argparse.Namespace(
            fix_design_refs=False,
            fix_projection=True,
            yes=True,
        )
    )

    assert projection.read_bytes() == before
    assert (
        f"refusing projection repair: {issue.id} would change the issues.jsonl row set"
    ) in capsys.readouterr().err


@pytest.mark.parametrize(
    ("fields", "current_updates", "reduced_updates", "expected"),
    [
        (
            ["status"],
            {"status": "open"},
            {"status": "closed"},
            "changes unexpected field(s): status",
        ),
        (
            ["title"],
            {"title": "stale"},
            {"title": "canonical"},
            "changes unexpected field(s): title",
        ),
        (
            ["closed_at"],
            {"closed_at": "2026-07-30T12:00:00Z"},
            {"closed_at": "2026-07-30T12:01:00Z"},
            "moves closed_at later",
        ),
    ],
)
def test_projection_repair_guard_refuses_unexpected_shapes(
    fields: list[str],
    current_updates: dict[str, object],
    reduced_updates: dict[str, object],
    expected: str,
) -> None:
    current = {"status": "closed", **current_updates}
    reduced = {"status": "closed", **reduced_updates}

    refusal = cli_admin._projection_repair_refusal(
        [
            {
                "issue_id": "beads-1",
                "changed_fields": fields,
                "current": current,
                "reduced": reduced,
            }
        ]
    )

    assert refusal is not None
    assert expected in refusal


def _append_redundant_close_and_stale_projection(
    project_dir: Path,
    issue_id: str,
) -> tuple[str, str]:
    projection_path = project_dir / "sdd/beads/issues.jsonl"
    current = json.loads(projection_path.read_text(encoding="utf-8"))
    first_close = str(current["closed_at"])
    second_close = (datetime.now(UTC) + timedelta(minutes=1)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    stream_path = project_dir / f"sdd/beads/events/streams/{issue_id}.jsonl"
    events = [
        json.loads(line)
        for line in stream_path.read_text(encoding="utf-8").splitlines()
    ]
    duplicate = dict(events[-1])
    duplicate["event_id"] = f"{duplicate['event_id']}:duplicate"
    duplicate["timestamp"] = second_close
    duplicate["payload"] = dict(duplicate["payload"])
    duplicate["payload"]["close_reason"] = None
    with stream_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(duplicate, separators=(",", ":")) + "\n")
    current["closed_at"] = second_close
    current["close_reason"] = None
    current["updated_at"] = second_close
    projection_path.write_text(
        json.dumps(current, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return first_close, second_close
