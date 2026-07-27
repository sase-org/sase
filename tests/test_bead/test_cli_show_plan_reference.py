"""``sase bead show`` renders a plan reference and where it resolves."""

from __future__ import annotations

import argparse
from collections.abc import Iterator
from pathlib import Path

import pytest

from sase.bead import cli as bead_cli
from sase.bead.model import BeadTier, Issue, IssueType
from sase.bead.project import BeadProject


@pytest.fixture
def plans_root(tmp_path: Path) -> Path:
    root = tmp_path / "plans-store"
    (root / "202607").mkdir(parents=True)
    return root


@pytest.fixture
def store(
    tmp_path: Path,
    plans_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with BeadProject.init(workspace):
        pass
    monkeypatch.chdir(workspace)
    monkeypatch.setattr("sase.bead.workspace.resolve_primary_workspace", lambda: None)
    monkeypatch.setattr(
        "sase.bead.cli_query.plan_reference_roots",
        lambda: (plans_root,),
    )
    monkeypatch.setattr(
        "sase.bead.cli_query.design_paths_are_relative",
        lambda: False,
    )
    yield


def _epic(design: str) -> Issue:
    with BeadProject(Path.cwd()) as project:
        return project.create(
            "Durable Epic",
            IssueType.PLAN,
            tier=BeadTier.EPIC,
            design=design,
        )


def _show(issue: Issue, capsys: pytest.CaptureFixture[str]) -> str:
    bead_cli.handle_bead_show(argparse.Namespace(id=issue.id, format="full"))
    return capsys.readouterr().out


@pytest.mark.usefixtures("store")
def test_show_prints_the_reference_above_its_resolved_path(
    plans_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    plan = plans_root / "202607/durable.md"
    plan.write_text("# Plan\n", encoding="utf-8")
    epic = _epic("plans:202607/durable.md")

    out = _show(epic, capsys)

    assert f"PLAN\n  plans:202607/durable.md\n  → {plan}\n" in out


@pytest.mark.usefixtures("store")
def test_show_marks_a_reference_resolved_through_month_drift(
    plans_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    plan = plans_root / "202607/drifted.md"
    plan.write_text("# Plan\n", encoding="utf-8")
    epic = _epic("plans:202606/drifted.md")

    out = _show(epic, capsys)

    assert f"  plans:202606/drifted.md\n  → {plan} (month drift)\n" in out


@pytest.mark.usefixtures("store")
def test_show_says_plainly_when_a_reference_resolves_nowhere(
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic = _epic("plans:202607/gone.md")

    out = _show(epic, capsys)

    assert "  plans:202607/gone.md\n  → (unresolved: no plan file found)\n" in out


@pytest.mark.usefixtures("store")
def test_show_reports_an_ambiguous_reference_instead_of_guessing(
    plans_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for month in ("202606", "202607"):
        month_dir = plans_root / month
        month_dir.mkdir(exist_ok=True)
        (month_dir / "twin.md").write_text("# Plan\n", encoding="utf-8")
    epic = _epic("plans:202605/twin.md")

    out = _show(epic, capsys)

    assert (
        "  plans:202605/twin.md\n"
        "  → (ambiguous: multiple plans match this reference)\n" in out
    )


@pytest.mark.usefixtures("store")
def test_show_reports_a_malformed_reference(
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic = _epic("plans:../escape.md")

    out = _show(epic, capsys)

    assert "  plans:../escape.md\n  → (unresolved: malformed plan reference)\n" in out


@pytest.mark.usefixtures("store")
def test_show_keeps_one_line_for_a_legacy_path_that_resolves_to_itself(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.bead.cli_query.design_paths_are_relative",
        lambda: True,
    )
    plan = Path.cwd() / "plans/legacy.md"
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_text("# Plan\n", encoding="utf-8")
    epic = _epic("plans/legacy.md")

    out = _show(epic, capsys)

    assert "PLAN\n  plans/legacy.md\n" in out
    assert "→" not in out.split("PLAN\n")[1]


@pytest.mark.usefixtures("store")
def test_show_renders_the_parent_epic_reference_for_a_phase(
    plans_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    plan = plans_root / "202607/durable.md"
    plan.write_text("# Plan\n", encoding="utf-8")
    epic = _epic("plans:202607/durable.md")
    with BeadProject(Path.cwd()) as project:
        phase = project.create("Phase", IssueType.PHASE, parent_id=epic.id)

    out = _show(phase, capsys)

    assert "EPIC PLAN" in out
    assert f"  plans:202607/durable.md\n  → {plan}\n" in out


def _rust_plan_section(issue: Issue, plans_root: Path) -> str:
    """Render the same bead through the Rust parity renderer."""
    from sase.core.rust import require_rust_binding

    beads_dir = Path.cwd() / "sdd/beads"
    outcome = require_rust_binding("bead_cli_execute")(
        ["show", issue.id],
        [str(beads_dir)],
        str(beads_dir),
        str(Path.cwd()),
        False,
        [str(plans_root)],
    )
    return str(dict(outcome)["stdout"]).split("\nPLAN\n")[1]


@pytest.mark.usefixtures("store")
@pytest.mark.parametrize(
    "reference",
    [
        "plans:202607/durable.md",
        "plans:202606/durable.md",
        "plans:202607/gone.md",
        "plans:../escape.md",
    ],
)
def test_python_and_rust_renderers_agree_on_the_plan_section(
    plans_root: Path,
    capsys: pytest.CaptureFixture[str],
    reference: str,
) -> None:
    (plans_root / "202607/durable.md").write_text("# Plan\n", encoding="utf-8")
    epic = _epic(reference)

    python_section = _show(epic, capsys).split("\nPLAN\n")[1]

    assert python_section == _rust_plan_section(epic, plans_root)
