"""CLI coverage for Patch artifact references."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sase.ace.patch import parse_project_file
from sase.main.patch_handler import _handle_ref
from sase.main.parser import create_parser, default_list_delegation_notice
from tests.artifact_refs.helpers import context as make_context


def _project_file(tmp_path: Path, refs: tuple[str, ...] = ()) -> Path:
    project = tmp_path / "sase.sase"
    refs_section = (
        "REFS:\n" + "".join(f"  {reference}\n" for reference in refs) if refs else ""
    )
    project.write_text(
        "NAME: sase_feature\n"
        "DESCRIPTION:\n"
        "  Example\n"
        "STATUS: Draft\n"
        f"{refs_section}"
        "COMMITS:\n"
        "  (1) Initial\n",
        encoding="utf-8",
    )
    return project


def _target(monkeypatch, project: Path) -> None:
    monkeypatch.setattr(
        "sase.main.patch_handler.find_all_patches",
        lambda: parse_project_file(str(project)),
    )


def test_ref_parser_defaults_to_list_and_documents_options() -> None:
    parser = create_parser()
    args = parser.parse_args(["patch", "ref"])

    assert args.ref_action == "list"
    assert default_list_delegation_notice(args) == (
        "No subcommand provided for 'sase patch ref'; "
        "delegating to 'sase patch ref list'."
    )

    explicit = parser.parse_args(
        [
            "patch",
            "ref",
            "list",
            "--changespec",
            "sase_feature",
            "--json",
            "--resolve",
        ]
    )
    assert explicit.patch == "sase_feature"
    assert explicit.json is True
    assert explicit.resolve is True

    canonical = parser.parse_args(["patch", "ref", "list", "--patch", "sase_feature"])
    assert canonical.command == "patch"
    assert canonical.patch == "sase_feature"
    assert canonical.patch == "sase_feature"


def test_ref_add_normalizes_deduplicates_and_persists(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    project = _project_file(tmp_path, ("research:202607/existing.md",))
    _target(monkeypatch, project)
    args = argparse.Namespace(
        patch="sase_feature",
        ref_action="add",
        refs=[
            "research:202607/existing.md",
            "plans:202607/plan.md",
            "plans:202607/plan.md",
        ],
    )

    assert _handle_ref(args) == 0

    patch = parse_project_file(str(project))[0]
    assert patch.refs == [
        "research:202607/existing.md",
        "plans:202607/plan.md",
    ]
    assert "Attached 1 artifact reference" in capsys.readouterr().out


def test_ref_rm_detaches_only_requested_entries(
    monkeypatch,
    tmp_path: Path,
) -> None:
    project = _project_file(
        tmp_path,
        ("research:202607/report.md", "plans:202607/plan.md"),
    )
    _target(monkeypatch, project)
    args = argparse.Namespace(
        patch="sase_feature",
        ref_action="rm",
        refs=["research:202607/report.md"],
    )

    assert _handle_ref(args) == 0

    assert parse_project_file(str(project))[0].refs == ["plans:202607/plan.md"]


def test_ref_list_resolve_json_returns_machine_readable_outcomes(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    project = _project_file(
        tmp_path,
        ("plans:resolved.md", "plans:missing.md"),
    )
    context = make_context(tmp_path)
    resolved = context.document_roots[1].root / "resolved.md"
    resolved.parent.mkdir(parents=True)
    resolved.write_text("# Resolved\n", encoding="utf-8")
    _target(monkeypatch, project)
    monkeypatch.setattr(
        "sase.main.patch_handler._artifact_reference_context",
        lambda _project: context,
    )
    args = argparse.Namespace(
        patch="sase_feature",
        ref_action="list",
        json=True,
        resolve=True,
    )

    assert _handle_ref(args) == 0

    payload = json.loads(capsys.readouterr().out)
    exact, missing = payload["results"][0]["refs"]
    assert exact["resolution"]["status"] == "exact"
    assert exact["resolution"]["resolved_path"] == str(resolved)
    assert missing["resolution"]["status"] == "missing"
