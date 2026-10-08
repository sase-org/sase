"""Guard-phase coverage for the advisory finalizer memory guard (sase-1hi.8)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import sase.finalizers.commit_memory_guard as guard
from sase.finalizers.commit_memory_guard import (
    GUARD_DIAGNOSTIC_CODE,
    memory_guard_for_new_markers,
)


def _note_row(decision_id: str, value: bool, path: str) -> dict:
    return {
        "id": decision_id,
        "kind": "toggle",
        "value": value,
        "memory": {
            "selectors": [path],
            "resolved": [
                {
                    "selector": path,
                    "kind": "note",
                    "scope": "project",
                    "path": path,
                    "type": "reference",
                    "exists": True,
                }
            ],
            "provenance": "asked",
        },
    }


def _web_row(decision_id: str, selector: str, slug: str, strands: list[str]) -> dict:
    return {
        "id": decision_id,
        "kind": "toggle",
        "value": True,
        "memory": {
            "selectors": [selector],
            "resolved": [
                {
                    "selector": selector,
                    "kind": "web",
                    "scope": "project",
                    "path": slug,
                    "type": "web",
                    "exists": True,
                    "strands": strands,
                }
            ],
            "provenance": "asked",
        },
    }


def test_covered_note_change_is_silent() -> None:
    coverage = guard._coverage_from_sheets(
        {"rows": [_note_row("tui_note", True, "tui.md")]}, None, plan_label="plan demo"
    )
    assert coverage.exact == frozenset({"sase/memory/tui.md"})
    assert (
        guard._build_memory_guard_diagnostics(
            ["sase/memory/tui.md"], coverage, instance_id="commit"
        )
        == []
    )


def test_uncovered_note_change_warns_with_path_and_plan() -> None:
    coverage = guard._coverage_from_sheets(
        {"rows": [_note_row("tui_note", True, "tui.md")]}, None, plan_label="plan demo"
    )
    diagnostics = guard._build_memory_guard_diagnostics(
        ["sase/memory/other.md"], coverage, instance_id="commit"
    )
    assert len(diagnostics) == 1
    diagnostic = diagnostics[0]
    assert diagnostic.code == GUARD_DIAGNOSTIC_CODE == "memory_change_uncovered"
    assert diagnostic.severity == "warning"
    assert "sase/memory/other.md" in diagnostic.message
    assert "plan demo" in diagnostic.message
    assert diagnostic.instance_id == "commit"


def test_answered_no_grants_nothing() -> None:
    coverage = guard._coverage_from_sheets(
        {"rows": [_note_row("tui_note", False, "tui.md")]}, None, plan_label="plan demo"
    )
    assert coverage.exact == frozenset()
    diagnostics = guard._build_memory_guard_diagnostics(
        ["sase/memory/tui.md"], coverage, instance_id="commit"
    )
    assert len(diagnostics) == 1


def test_inherited_epic_grant_covers_phase_change() -> None:
    inherited = {"rows": [_note_row("glossary_note", True, "glossary.md")]}
    coverage = guard._coverage_from_sheets(None, inherited, plan_label="epic demo")
    assert (
        guard._build_memory_guard_diagnostics(
            ["sase/memory/glossary.md"], coverage, instance_id="commit"
        )
        == []
    )
    assert (
        len(
            guard._build_memory_guard_diagnostics(
                ["sase/memory/other.md"], coverage, instance_id="commit"
            )
        )
        == 1
    )


def test_web_selector_covers_current_strands() -> None:
    coverage = guard._coverage_from_sheets(
        {"rows": [_web_row("glossary_all", "glossary", "glossary", ["stitch"])]},
        None,
        plan_label="plan demo",
    )
    assert coverage.prefixes == ("sase/memory/glossary/",)
    assert (
        guard._find_uncovered_memory_changes(
            ["sase/memory/glossary/stitch.md"], coverage
        )
        == []
    )
    assert (
        guard._find_uncovered_memory_changes(
            ["sase/memory/glossary/unknown.md"], coverage
        )
        == []
    )


def test_strand_selector_covers_only_that_strand() -> None:
    coverage = guard._coverage_from_sheets(
        {"rows": [_web_row("one_strand", "glossary:stitch", "glossary", ["stitch"])]},
        None,
        plan_label="plan demo",
    )
    assert "sase/memory/glossary/stitch.md" in coverage.exact
    assert (
        guard._find_uncovered_memory_changes(
            ["sase/memory/glossary/stitch.md"], coverage
        )
        == []
    )
    assert guard._find_uncovered_memory_changes(
        ["sase/memory/glossary/other.md"], coverage
    ) == ["sase/memory/glossary/other.md"]


def test_generated_files_need_a_covered_note_in_the_same_declaration() -> None:
    coverage = guard._coverage_from_sheets(
        {"rows": [_note_row("tui_note", True, "tui.md")]}, None, plan_label="plan demo"
    )
    assert guard._find_uncovered_memory_changes(["AGENTS.md"], coverage) == [
        "AGENTS.md"
    ]
    assert guard._find_uncovered_memory_changes(
        ["sase/memory/README.md"], coverage
    ) == ["sase/memory/README.md"]
    assert guard._find_uncovered_memory_changes(["CLAUDE.md"], coverage) == [
        "CLAUDE.md"
    ]
    together = guard._find_uncovered_memory_changes(
        ["sase/memory/tui.md", "AGENTS.md", "CLAUDE.md", "sase/memory/README.md"],
        coverage,
    )
    assert together == []


def test_non_memory_paths_are_never_checked() -> None:
    coverage = guard._MemoryCoverage(
        plan_label="plan demo", exact=frozenset(), prefixes=()
    )
    assert guard._find_uncovered_memory_changes(["src/sase/foo.py"], coverage) == []
    assert guard._classify_changed_path("src/sase/foo.py")[0] == "other"
    assert guard._classify_changed_path("memory/tui.md") == (
        "memory",
        "sase/memory/tui.md",
    )


def test_no_coverage_for_agents_not_launched_from_a_plan(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("SASE_PLAN", raising=False)
    empty = tmp_path / "empty"
    empty.mkdir()
    assert guard._resolve_memory_coverage(str(empty)) is None
    assert guard._resolve_memory_coverage(None) is None
    assert (
        guard._build_memory_guard_diagnostics(
            ["sase/memory/tui.md"], None, instance_id="c"
        )
        == []
    )


def test_plan_launched_without_grants_resolves_to_empty_coverage(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SASE_PLAN", raising=False)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text(
        json.dumps({"phase_bead_id": "sase-1hi.8"}), encoding="utf-8"
    )
    coverage = guard._resolve_memory_coverage(str(artifacts))
    assert coverage is not None
    assert coverage.exact == frozenset()
    diagnostics = guard._build_memory_guard_diagnostics(
        ["sase/memory/tui.md"], coverage, instance_id="commit"
    )
    assert len(diagnostics) == 1
    assert diagnostics[0].severity == "warning"


def test_resolve_unions_plan_and_inherited_sheets(tmp_path, monkeypatch) -> None:
    import sase.sdd.plan_decision_handoff as handoff

    plan_sheet = {"rows": [_note_row("tui_note", True, "tui.md")]}
    epic_sheet = {"rows": [_note_row("other_note", True, "other.md")]}
    monkeypatch.delenv("SASE_PLAN", raising=False)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    plan_file = tmp_path / "plan.md"
    plan_file.write_text("# plan", encoding="utf-8")
    (artifacts / "agent_meta.json").write_text(
        json.dumps({"sdd_plan_path": str(plan_file)}), encoding="utf-8"
    )
    monkeypatch.setattr(
        handoff,
        "load_stamped_decisions",
        lambda _path, _tier=None: SimpleNamespace(
            sheet=plan_sheet, title="Demo", decided_by="reviewer", decided_via="tui"
        ),
    )
    monkeypatch.setattr(
        handoff,
        "epic_decision_context",
        lambda _dir: SimpleNamespace(
            sheet=epic_sheet,
            epic_title="Epic",
            decided_by="reviewer",
            decided_via="tui",
        ),
    )
    coverage = guard._resolve_memory_coverage(str(artifacts))
    assert coverage is not None
    assert coverage.exact == frozenset({"sase/memory/tui.md", "sase/memory/other.md"})
    assert "Demo" in coverage.plan_label


def test_collect_committed_paths_uses_marker_shas() -> None:
    markers = [
        {"cwd": "/repo", "commit_sha": "abc123"},
        {"cwd": "/repo", "commit_sha": ""},
        {"cwd": "", "commit_sha": "abc123"},
    ]
    collected = guard._collect_committed_paths(
        markers, list_files=lambda repo, sha: ["sase/memory/tui.md"]
    )
    assert collected == ["sase/memory/tui.md"]


def test_guard_for_new_markers_fails_open(monkeypatch) -> None:
    before = [
        {
            "cwd": "/r",
            "result": "x",
            "commit_sha": "a",
            "commit_tree": "t",
            "entry_id": "e",
        }
    ]
    after = [
        *before,
        {
            "cwd": "/r",
            "result": "y",
            "commit_sha": "b",
            "commit_tree": "t2",
            "entry_id": "e2",
        },
    ]

    def _boom(_dir: str | None) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(guard, "_resolve_memory_coverage", _boom)
    assert memory_guard_for_new_markers("/nope", before, after) == []
    assert memory_guard_for_new_markers("/nope", before, before) == []


def test_diagnostic_names_every_uncovered_path() -> None:
    diagnostic = guard._memory_guard_diagnostic(
        ["sase/memory/b.md", "sase/memory/a.md"], "plan demo", "commit"
    )
    assert diagnostic.code == "memory_change_uncovered"
    assert diagnostic.severity == "warning"
    assert "sase/memory/a.md" in diagnostic.message
    assert "sase/memory/b.md" in diagnostic.message


def test_coverage_ignores_non_memory_and_unanswered_rows() -> None:
    rows = [
        {"id": "choice", "kind": "choice", "value": "pane"},
        _note_row("off", False, "tui.md"),
        {"id": "tui_note", "kind": "toggle", "value": True},
    ]
    coverage = guard._coverage_from_sheet_rows(rows)  # type: ignore[arg-type]
    assert coverage.exact == frozenset()


def test_frozen_grant_covers_from_tmp_cwd(
    tmp_path, monkeypatch: __import__("pytest").MonkeyPatch
) -> None:
    monkeypatch.chdir("/tmp")
    coverage = guard._coverage_from_sheets(
        {"rows": [_note_row("tui_note", True, "sase/memory/tui.md")]},
        None,
        plan_label="plan demo",
    )
    assert guard._find_uncovered_memory_changes(["sase/memory/tui.md"], coverage) == []


def test_nested_agents_md_is_other_while_root_is_generated() -> None:
    assert guard._classify_changed_path("src/sase/ace/AGENTS.md")[0] == "other"
    assert guard._classify_changed_path("AGENTS.md")[0] == "generated"
    coverage = guard._coverage_from_sheets(
        {"rows": [_note_row("tui_note", True, "tui.md")]}, None, plan_label="plan demo"
    )
    assert (
        guard._find_uncovered_memory_changes(["src/sase/ace/AGENTS.md"], coverage) == []
    )
    root_only = guard._MemoryCoverage(
        plan_label="plan demo", exact=frozenset(), prefixes=()
    )
    assert guard._find_uncovered_memory_changes(["AGENTS.md"], root_only) == [
        "AGENTS.md"
    ]


def test_generated_covered_only_in_same_repo() -> None:
    coverage = guard._coverage_from_sheets(
        {"rows": [_note_row("tui_note", True, "tui.md")]}, None, plan_label="plan demo"
    )
    same_repo = guard._find_uncovered_memory_changes(
        ["sase/memory/tui.md", "AGENTS.md"], coverage
    )
    assert same_repo == []
    markers = [
        {"cwd": "/repo-a", "commit_sha": "a1"},
        {"cwd": "/repo-b", "commit_sha": "b1"},
    ]

    def _lister(cwd: str, sha: str) -> list[str]:
        if cwd == "/repo-a":
            return ["sase/memory/tui.md"]
        return ["AGENTS.md"]

    grouped = guard._collect_committed_paths_by_repo(markers, list_files=_lister)
    assert grouped == {"/repo-a": ["sase/memory/tui.md"], "/repo-b": ["AGENTS.md"]}
    uncovered: list[str] = []
    for paths in grouped.values():
        uncovered.extend(guard._find_uncovered_memory_changes(paths, coverage))
    assert sorted(set(uncovered)) == ["AGENTS.md"]
