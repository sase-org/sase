"""CLI coverage for sized phases and nested child epics."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import json
from pathlib import Path
import shlex

import pytest

from sase.bead import cli as bead_cli
from sase.bead.model import BeadTier, Dependency, Issue, IssueType
from sase.bead.project import BeadProject
from sase.main.parser import create_parser


@pytest.fixture
def nested_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[dict[str, Issue]]:
    with BeadProject.init(tmp_path):
        pass
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sase.bead.workspace.resolve_primary_workspace", lambda: None)

    plan_paths = {
        name: tmp_path / f"{name}.md"
        for name in ("root", "phase_child", "epic_child", "deep_child")
    }
    for path in plan_paths.values():
        path.write_text(f"# {path.stem}\n", encoding="utf-8")

    with BeadProject(tmp_path) as project:
        root = project.create(
            "Root Epic",
            IssueType.PLAN,
            tier=BeadTier.EPIC,
            design=str(plan_paths["root"]),
        )
        phase = project.create("Root Phase", IssueType.PHASE, parent_id=root.id)
        phase = project.update(phase.id, size="medium")
        childless_phase = project.create(
            "Childless Phase",
            IssueType.PHASE,
            parent_id=root.id,
        )
        phase_child = project.create(
            "Phase Child Epic",
            IssueType.PLAN,
            parent_id=phase.id,
            tier=BeadTier.EPIC,
            design=str(plan_paths["phase_child"]),
        )
        nested_phase = project.create(
            "Nested Phase",
            IssueType.PHASE,
            parent_id=phase_child.id,
        )
        nested_phase = project.update(nested_phase.id, size="large")
        deep_child = project.create(
            "Deep Child Epic",
            IssueType.PLAN,
            parent_id=nested_phase.id,
            tier=BeadTier.EPIC,
            design=str(plan_paths["deep_child"]),
        )
        epic_child = project.create(
            "Epic Child Epic",
            IssueType.PLAN,
            parent_id=root.id,
            tier=BeadTier.EPIC,
            design=str(plan_paths["epic_child"]),
        )

    yield {
        "root": root,
        "phase": phase,
        "childless_phase": childless_phase,
        "phase_child": phase_child,
        "nested_phase": nested_phase,
        "deep_child": deep_child,
        "epic_child": epic_child,
    }


def _show(issue: Issue, capsys: pytest.CaptureFixture[str]) -> str:
    args = create_parser().parse_args(["bead", "show", issue.id])
    bead_cli.handle_bead_show(args)
    return capsys.readouterr().out


def _show_with_format(
    issue: Issue,
    output_format: str,
    capsys: pytest.CaptureFixture[str],
) -> str:
    args = create_parser().parse_args(
        ["bead", "show", issue.id, "--format", output_format]
    )
    bead_cli.handle_bead_show(args)
    return capsys.readouterr().out


def test_show_skill_examples_parse_against_cli_contract() -> None:
    source_path = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "sase"
        / "xprompts"
        / "skills"
        / "sase_beads.md"
    )
    source = source_path.read_text(encoding="utf-8")
    show_section = source.split("### show", 1)[1].split("### dep add", 1)[0]
    examples = [
        line.strip()
        for line in show_section.splitlines()
        if line.strip().startswith("sase bead show ")
    ]

    assert examples == [
        "sase bead show <id>",
        "sase bead show <id> --format compact",
        "sase bead show <id> --format json",
    ]

    parser = create_parser()
    for example in examples:
        argv = shlex.split(example.replace("<id>", "sase-64"))
        args = parser.parse_args(argv[1:])
        assert args.command == "bead"
        assert args.bead_subcommand == "show"
        assert args.id == "sase-64"


@pytest.mark.parametrize("flag", ["--format", "-f"])
def test_show_parser_accepts_format_aliases(flag: str) -> None:
    args = create_parser().parse_args(["bead", "show", "sase-64", flag, "json"])

    assert args.format == "json"


def test_show_parser_defaults_to_full_without_overwriting_bare_bead_default() -> None:
    parser = create_parser()

    assert parser.parse_args(["bead", "show", "sase-64"]).format == "full"
    assert parser.parse_args(["bead"]).format == "compact"


def test_show_parser_rejects_unknown_format() -> None:
    with pytest.raises(SystemExit) as excinfo:
        create_parser().parse_args(["bead", "show", "sase-64", "-f", "bogus"])

    assert excinfo.value.code == 2


def test_show_phase_displays_size_and_rootward_lineage(
    nested_store: dict[str, Issue],
    capsys: pytest.CaptureFixture[str],
) -> None:
    phase = nested_store["phase"]
    root = nested_store["root"]

    out = _show(phase, capsys)

    assert "Size: medium" in out
    assert f"↑ {phase.id} ← epic {root.id}" in out
    assert "EPIC PLAN" in out
    assert "From parent epic bead" in out


def test_show_plan_splits_phases_from_child_epics(
    nested_store: dict[str, Issue],
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = nested_store["root"]
    phase = nested_store["phase"]
    epic_child = nested_store["epic_child"]

    out = _show(root, capsys)

    assert "CHILDREN\n  PHASES" in out
    assert f"○ {phase.id}: {phase.title}   [OPEN] · Size: medium" in out
    assert "  CHILD EPICS" in out
    assert f"○ {epic_child.id}: {epic_child.title}   [OPEN] · Tier: epic" in out
    assert nested_store["phase_child"].id not in out


def test_show_phase_lists_child_epics(
    nested_store: dict[str, Issue],
    capsys: pytest.CaptureFixture[str],
) -> None:
    phase = nested_store["phase"]
    child = nested_store["phase_child"]

    out = _show(phase, capsys)

    assert "CHILDREN\n  CHILD EPICS" in out
    assert f"○ {child.id}: {child.title}   [OPEN] · Tier: epic" in out


def test_show_childless_phase_omits_children(
    nested_store: dict[str, Issue],
    capsys: pytest.CaptureFixture[str],
) -> None:
    phase = nested_store["childless_phase"]

    out = _show(phase, capsys)

    assert "Size: small" in out
    assert "CHILDREN" not in out


def test_show_child_epic_under_phase_has_lineage_and_own_plan(
    nested_store: dict[str, Issue],
    capsys: pytest.CaptureFixture[str],
) -> None:
    child = nested_store["phase_child"]
    phase = nested_store["phase"]
    root = nested_store["root"]

    out = _show(child, capsys)

    assert f"↑ {child.id} ← phase {phase.id} ← epic {root.id}" in out
    assert "EPIC PLAN" in out
    assert "phase_child.md" in out


def test_show_child_epic_under_epic_has_full_lineage(
    nested_store: dict[str, Issue],
    capsys: pytest.CaptureFixture[str],
) -> None:
    child = nested_store["epic_child"]
    root = nested_store["root"]

    out = _show(child, capsys)

    assert f"↑ {child.id} ← epic {root.id}" in out
    assert "EPIC PLAN" in out
    assert "epic_child.md" in out


def test_show_deep_nested_child_epic_has_complete_lineage(
    nested_store: dict[str, Issue],
    capsys: pytest.CaptureFixture[str],
) -> None:
    child = nested_store["deep_child"]
    nested_phase = nested_store["nested_phase"]
    phase_child = nested_store["phase_child"]
    phase = nested_store["phase"]
    root = nested_store["root"]

    out = _show(child, capsys)

    assert (
        f"↑ {child.id} ← phase {nested_phase.id} ← epic {phase_child.id}"
        f" ← phase {phase.id} ← epic {root.id}"
    ) in out


def test_show_compact_matches_the_same_list_row(
    nested_store: dict[str, Issue],
    capsys: pytest.CaptureFixture[str],
) -> None:
    phase = nested_store["phase"]

    show_out = _show_with_format(phase, "compact", capsys)
    bead_cli.handle_bead_list(create_parser().parse_args(["bead", "list"]))
    list_out = capsys.readouterr().out

    assert show_out.rstrip("\n") in list_out.splitlines()


def test_show_explicit_full_matches_default(
    nested_store: dict[str, Issue],
    capsys: pytest.CaptureFixture[str],
) -> None:
    phase = nested_store["phase"]

    default_out = _show(phase, capsys)
    full_out = _show_with_format(phase, "full", capsys)

    assert full_out == default_out


def test_show_json_root_includes_children_and_self_plan(
    nested_store: dict[str, Issue],
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = nested_store["root"]

    payload = json.loads(_show_with_format(root, "json", capsys))

    assert payload["issue"]["id"] == root.id
    assert payload["ancestors"] == []
    assert [ref["id"] for ref in payload["children"]["phases"]] == [
        nested_store["phase"].id,
        nested_store["childless_phase"].id,
    ]
    assert [ref["id"] for ref in payload["children"]["epics"]] == [
        nested_store["epic_child"].id
    ]
    assert payload["plan"]["source"] == "self"
    assert payload["plan"]["from"] is None
    assert payload["plan"]["path"] == root.design


def test_show_json_nested_phase_includes_nearest_first_lineage_and_parent_plan(
    nested_store: dict[str, Issue],
    capsys: pytest.CaptureFixture[str],
) -> None:
    nested_phase = nested_store["nested_phase"]

    payload = json.loads(_show_with_format(nested_phase, "json", capsys))

    assert [ref["id"] for ref in payload["ancestors"]] == [
        nested_store["phase_child"].id,
        nested_store["phase"].id,
        nested_store["root"].id,
    ]
    assert payload["plan"]["source"] == "parent"
    assert payload["plan"]["section"] == "EPIC PLAN"
    assert payload["plan"]["from"]["id"] == nested_store["phase_child"].id


def test_show_json_includes_resolved_dependencies_and_blockers(
    nested_store: dict[str, Issue],
    capsys: pytest.CaptureFixture[str],
) -> None:
    phase = nested_store["phase"]
    childless_phase = nested_store["childless_phase"]
    with BeadProject(Path.cwd()) as project:
        project.add_dependency(childless_phase.id, phase.id)

    depends_payload = json.loads(_show_with_format(childless_phase, "json", capsys))
    blocks_payload = json.loads(_show_with_format(phase, "json", capsys))

    assert [(ref["id"], ref["resolved"]) for ref in depends_payload["depends_on"]] == [
        (phase.id, True)
    ]
    assert [(ref["id"], ref["resolved"]) for ref in blocks_payload["blocks"]] == [
        (childless_phase.id, True)
    ]


def test_show_json_and_full_mirror_dangling_relationships(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue = Issue(
        id="beads-dangling",
        title="Dangling",
        issue_type=IssueType.PHASE,
        parent_id="beads-missing-parent",
        dependencies=[
            Dependency(
                issue_id="beads-dangling",
                depends_on_id="beads-missing-dependency",
                created_at="2026-07-27T00:00:00Z",
            )
        ],
    )

    class _DanglingView:
        def show(self, issue_id: str) -> Issue:
            if issue_id == issue.id:
                return issue
            raise KeyError(issue_id)

        def get_epic_children(self, _issue_id: str) -> list[Issue]:
            return []

        def list_issues(self) -> list[Issue]:
            return [issue]

    @contextmanager
    def read_view() -> Iterator[_DanglingView]:
        yield _DanglingView()

    monkeypatch.setattr("sase.bead.cli_query.get_read_view", read_view)
    monkeypatch.setattr(
        "sase.bead.cli_query.design_paths_are_relative",
        lambda: False,
    )

    payload = json.loads(_show_with_format(issue, "json", capsys))
    full_out = _show(issue, capsys)

    unresolved_parent = payload["ancestors"][0]
    unresolved_dependency = payload["depends_on"][0]
    assert unresolved_parent == {
        "id": "beads-missing-parent",
        "resolved": False,
        "title": None,
        "status": None,
        "issue_type": None,
        "tier": None,
        "size": None,
    }
    assert unresolved_dependency == {
        "id": "beads-missing-dependency",
        "resolved": False,
        "title": None,
        "status": None,
        "issue_type": None,
        "tier": None,
        "size": None,
    }
    assert "beads-missing-parent (not found)" in full_out
    assert "beads-missing-dependency (not found)" in full_out


def test_show_json_contains_every_bead_id_from_full_output(
    nested_store: dict[str, Issue],
    capsys: pytest.CaptureFixture[str],
) -> None:
    for issue in nested_store.values():
        full_out = _show(issue, capsys)
        payload = json.loads(_show_with_format(issue, "json", capsys))
        json_text = json.dumps(payload)
        ids_in_full = {
            candidate.id
            for candidate in nested_store.values()
            if candidate.id in full_out
        }
        assert all(issue_id in json_text for issue_id in ids_in_full)


def test_show_json_missing_id_exits_with_stderr_only(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = create_parser().parse_args(
        ["bead", "show", "beads-missing", "--format", "json"]
    )

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_show(args)

    captured = capsys.readouterr()
    assert excinfo.value.code == 1
    assert captured.out == ""
    assert captured.err == "Error: issue not found: beads-missing\n"


def test_search_json_keeps_phase_size_in_machine_output(
    nested_store: dict[str, Issue],
    capsys: pytest.CaptureFixture[str],
) -> None:
    phase = nested_store["phase"]
    args = create_parser().parse_args(["bead", "search", "medium", "--format", "json"])

    bead_cli.handle_bead_search(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] == 1
    assert payload["results"][0]["issue"]["id"] == phase.id
    assert payload["results"][0]["issue"]["size"] == "medium"
    assert payload["results"][0]["matched_fields"] == ["size"]


def test_show_renders_recorded_and_unrecorded_resolution(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as project:
        recorded = project.create("Canceled", IssueType.PLAN)
        project.close(
            [recorded.id],
            reason="Replaced by a newer plan",
            resolution="canceled",
        )
        historical = project.create("Historical", IssueType.PLAN)
        project.update(historical.id, status="closed")

    recorded_out = _show(recorded, capsys)
    assert "RESOLUTION" in recorded_out
    assert "Resolution: canceled" in recorded_out
    assert "Close reason: Replaced by a newer plan" in recorded_out
    assert "Closed at:" in recorded_out

    historical_out = _show(historical, capsys)
    assert "Resolution: (unrecorded)" in historical_out

    payload = json.loads(_show_with_format(recorded, "json", capsys))
    assert payload["issue"]["resolution"] == "canceled"
