"""CLI coverage for parsing and full bead show output."""

from __future__ import annotations

from pathlib import Path
import shlex

import pytest

from sase.bead.cli_detail import resolve_bead_creator_url
from sase.bead.model import Issue, IssueType
from sase.main.parser import create_parser
from tests.test_bead.cli_show_test_helpers import (
    show,
    show_with_format,
    use_single_issue_view,
)


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

    out = show(phase, capsys)

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

    out = show(root, capsys)

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

    out = show(phase, capsys)

    assert "CHILDREN\n  CHILD EPICS" in out
    assert f"○ {child.id}: {child.title}   [OPEN] · Tier: epic" in out


def test_show_childless_phase_omits_children(
    nested_store: dict[str, Issue],
    capsys: pytest.CaptureFixture[str],
) -> None:
    phase = nested_store["childless_phase"]

    out = show(phase, capsys)

    assert "Size: small" in out
    assert "CHILDREN" not in out


def test_show_child_epic_under_phase_has_lineage_and_own_plan(
    nested_store: dict[str, Issue],
    capsys: pytest.CaptureFixture[str],
) -> None:
    child = nested_store["phase_child"]
    phase = nested_store["phase"]
    root = nested_store["root"]

    out = show(child, capsys)

    assert f"↑ {child.id} ← phase {phase.id} ← epic {root.id}" in out
    assert "EPIC PLAN" in out
    assert "phase_child.md" in out


def test_show_child_epic_under_epic_has_full_lineage(
    nested_store: dict[str, Issue],
    capsys: pytest.CaptureFixture[str],
) -> None:
    child = nested_store["epic_child"]
    root = nested_store["root"]

    out = show(child, capsys)

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

    out = show(child, capsys)

    assert (
        f"↑ {child.id} ← phase {nested_phase.id} ← epic {phase_child.id}"
        f" ← phase {phase.id} ← epic {root.id}"
    ) in out


def test_show_explicit_full_matches_default(
    nested_store: dict[str, Issue],
    capsys: pytest.CaptureFixture[str],
) -> None:
    phase = nested_store["phase"]

    default_out = show(phase, capsys)
    full_out = show_with_format(phase, "full", capsys)

    assert full_out == default_out


def test_show_full_prints_page_url_when_resolved(
    nested_store: dict[str, Issue],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = nested_store["root"]
    monkeypatch.setattr(
        "sase.bead.cli_query.resolve_bead_page_url",
        lambda bead_id: f"https://example.test/pages/{bead_id}",
    )

    out = show(root, capsys)

    assert f"\nPAGE\n  https://example.test/pages/{root.id}\n" in out


def test_show_full_renders_localized_creator_with_resolved_agent_url(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    issue = Issue(
        id="beads-agent",
        title="Agent-created task",
        issue_type=IssueType.TASK,
        owner="owner@example.com",
        created_by="bbugyi200.athena.q8--plan",
    )
    creator_url = "https://example.test/agents/q8--plan"
    use_single_issue_view(monkeypatch, issue)
    monkeypatch.setattr(
        "sase.bead.cli_detail.present_agent_name",
        lambda name: "q8--plan" if name == issue.created_by else name,
    )
    monkeypatch.setattr(
        "sase.bead.cli_query.resolve_bead_creator_url",
        lambda name: creator_url if name == issue.created_by else None,
    )

    out = show(issue, capsys)

    assert f"\nCREATED BY\n  q8--plan\n  → {creator_url}\n" in out


def test_show_full_falls_back_to_raw_creator_without_agent_url(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    issue = Issue(
        id="beads-human",
        title="Human-created task",
        issue_type=IssueType.TASK,
        owner="owner@example.com",
        created_by="owner@example.com",
    )
    use_single_issue_view(monkeypatch, issue)

    def fail_to_present(_name: str) -> str:
        raise ValueError("not an agent name")

    monkeypatch.setattr(
        "sase.bead.cli_detail.present_agent_name",
        fail_to_present,
    )
    monkeypatch.setattr(
        "sase.bead.cli_query.resolve_bead_creator_url",
        lambda _name: None,
    )

    out = show(issue, capsys)

    assert "\nCREATED BY\n  owner@example.com\n" in out
    assert "\n  → " not in out


def test_resolve_bead_creator_url_uses_hosted_agent_link(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = object()
    creator = "bbugyi200.athena.q8--plan"
    expected = "https://example.test/agents/q8--plan"

    class _Resolver:
        def agent_url(self, agent_name: str) -> str | None:
            assert agent_name == creator
            return expected

    monkeypatch.setattr(
        "sase.sdd.plan_refs.workspace_context_for_plan_resolution",
        lambda _cwd: (tmp_path, 17),
    )
    monkeypatch.setattr(
        "sase.sdd.store.resolve_sdd_store",
        lambda workspace_dir, workspace_num: (
            store
            if (workspace_dir, workspace_num) == (tmp_path, 17)
            else pytest.fail("unexpected workspace context")
        ),
    )
    monkeypatch.setattr(
        "sase.sdd.hosted_links.hosted_link_resolver",
        lambda resolved_store, *, primary_root: (
            _Resolver()
            if (resolved_store, primary_root) == (store, tmp_path)
            else pytest.fail("unexpected hosted link context")
        ),
    )

    assert resolve_bead_creator_url(creator) == expected


def test_resolve_bead_creator_url_never_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(_cwd: Path) -> tuple[Path, int]:
        raise OSError("workspace unavailable")

    monkeypatch.setattr(
        "sase.sdd.plan_refs.workspace_context_for_plan_resolution",
        fail,
    )

    assert resolve_bead_creator_url("bbugyi200.athena.q8--plan") is None
