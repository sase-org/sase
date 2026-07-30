"""CLI coverage for durable bead artifact references."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.bead import cli as bead_cli
from sase.bead.model import Issue, IssueType
from sase.bead.project import BeadProject
from sase.main.parser import create_parser, default_list_delegation_notice
from tests.artifact_refs.helpers import context as make_context


@pytest.fixture
def referenced_issue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Issue, object, Path]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    context = make_context(tmp_path)
    plan = context.document_roots[1].root / "resolved.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Resolved\n", encoding="utf-8")
    with BeadProject.init(workspace) as project:
        issue = project.create(
            "Referenced",
            IssueType.PLAN,
            refs=["plans:resolved.md", "plans:missing.md"],
        )
    monkeypatch.chdir(workspace)
    monkeypatch.setattr("sase.bead.workspace.resolve_primary_workspace", lambda: None)
    monkeypatch.setattr(
        "sase.bead.cli_query.artifact_reference_context",
        lambda: context,
    )
    monkeypatch.setattr(
        "sase.bead.cli_refs.artifact_reference_context",
        lambda: context,
    )
    return issue, context, plan


def test_ref_parser_defaults_to_list_and_documents_options() -> None:
    parser = create_parser()
    args = parser.parse_args(["bead", "ref"])

    assert args.ref_action == "list"
    assert default_list_delegation_notice(args) == (
        "No subcommand provided for 'sase bead ref'; "
        "delegating to 'sase bead ref list'."
    )

    explicit = parser.parse_args(
        ["bead", "ref", "list", "sase-bb.3", "--json", "--resolve"]
    )
    assert explicit.id == "sase-bb.3"
    assert explicit.json is True
    assert explicit.resolve is True


def test_show_renders_resolved_and_missing_references(
    referenced_issue: tuple[Issue, object, Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue, _, plan = referenced_issue
    args = create_parser().parse_args(["bead", "show", issue.id])

    bead_cli.handle_bead_show(args)

    output = capsys.readouterr().out
    assert (
        "REFS\n"
        "  plans:resolved.md\n"
        f"  → {plan}\n"
        "  plans:missing.md\n"
        "  → (unresolved: no plan file found)\n"
    ) in output


def test_ref_list_resolve_json_returns_machine_readable_outcomes(
    referenced_issue: tuple[Issue, object, Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue, _, plan = referenced_issue
    args = create_parser().parse_args(
        ["bead", "ref", "list", issue.id, "--resolve", "--json"]
    )

    bead_cli.handle_bead_ref(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] == 2
    assert payload["results"][0]["issue_id"] == issue.id
    resolved, missing = payload["results"][0]["refs"]
    assert resolved["rendered"] == "plans:resolved.md"
    assert resolved["resolution"]["status"] == "exact"
    assert resolved["resolution"]["resolved_path"] == str(plan)
    assert missing["resolution"]["status"] == "missing"


def test_show_without_references_omits_refs_section(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject.init(tmp_path) as project:
        issue = project.create("Plain", IssueType.PLAN)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sase.bead.workspace.resolve_primary_workspace", lambda: None)
    monkeypatch.setattr(
        "sase.bead.cli_query.artifact_reference_context",
        lambda: pytest.fail("reference context built for an empty list"),
    )

    bead_cli.handle_bead_show(create_parser().parse_args(["bead", "show", issue.id]))

    assert "\nREFS\n" not in capsys.readouterr().out
