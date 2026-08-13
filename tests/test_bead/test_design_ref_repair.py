from __future__ import annotations

from pathlib import Path

from sase.bead.design_ref_repair import plan_design_ref_repairs
from sase.bead.model import Issue


def _issue(bead_id: str, design: str) -> Issue:
    return Issue(id=bead_id, title=bead_id, design=design)


def _plan(path: Path, owner: str | None = None, *, legacy: bool = False) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    owner_line = ""
    if owner is not None:
        owner_line = f"{'bead' if legacy else 'bead_id'}: {owner}\n"
    path.write_text(f"---\n{owner_line}---\n# Plan\n", encoding="utf-8")
    return path


def test_repair_planner_uses_owner_then_root_order(tmp_path: Path) -> None:
    store = tmp_path / "store"
    local = tmp_path / "local"
    store_owner = _plan(
        store / "202607/store-owner.md",
        "beads-owner",
    )
    _plan(local / "202607/local-owner.md", "beads-owner")
    store_basename = _plan(store / "202607/by-name.md")
    _plan(local / "202607/by-name.md")
    local_only = _plan(local / "202607/local-only.md", legacy=True)

    preview = plan_design_ref_repairs(
        [
            _issue("beads-owner", "/retired/wrong-name.md"),
            _issue("beads-name", "/retired/by-name.md"),
            _issue("beads-local", "/retired/local-only.md"),
        ],
        roots=(store, local),
    )

    assert [(item.bead_id, item.new_reference) for item in preview.repairs] == [
        ("beads-owner", "plan:202607/store-owner.md"),
        ("beads-name", "plan:202607/by-name.md"),
        ("beads-local", "plan:202607/local-only.md"),
    ]
    assert preview.unrepaired == ()
    assert store_owner.is_file()
    assert store_basename.is_file()
    assert local_only.is_file()


def test_repair_planner_stops_at_ambiguous_or_wrong_owner_tier(
    tmp_path: Path,
) -> None:
    store = tmp_path / "store"
    local = tmp_path / "local"
    _plan(store / "202607/owner-a.md", "beads-owner")
    _plan(store / "202608/owner-b.md", "beads-owner")
    _plan(local / "202607/owner-only.md", "beads-owner")
    _plan(store / "202607/duplicate.md")
    _plan(store / "202608/duplicate.md")
    _plan(local / "202607/duplicate.md")
    _plan(store / "202607/wrong.md", "another-bead")
    _plan(local / "202607/wrong.md")

    preview = plan_design_ref_repairs(
        [
            _issue("beads-owner", "/retired/owner.md"),
            _issue("beads-duplicate", "/retired/duplicate.md"),
            _issue("beads-wrong", "/retired/wrong.md"),
            _issue("beads-missing", "/retired/missing.md"),
        ],
        roots=(store, local),
    )

    assert preview.repairs == ()
    assert [(item.bead_id, item.reason) for item in preview.unrepaired] == [
        ("beads-owner", "ambiguous"),
        ("beads-duplicate", "ambiguous"),
        ("beads-wrong", "frontmatter names another bead"),
        ("beads-missing", "no candidate"),
    ]


def test_repair_planner_migrates_resolving_legacy_and_keeps_canonical(
    tmp_path: Path,
) -> None:
    store = tmp_path / "store"
    plan = _plan(store / "202607/plan.md", "beads-plan")

    preview = plan_design_ref_repairs(
        [
            _issue("beads-plan", str(plan)),
            _issue("beads-canonical", "plans:202607/plan.md"),
        ],
        roots=(store,),
    )

    assert [(item.bead_id, item.new_reference) for item in preview.repairs] == [
        ("beads-plan", "plan:202607/plan.md")
    ]
    assert preview.unrepaired == ()


def test_repair_planner_recovers_malformed_canonical_by_basename(
    tmp_path: Path,
) -> None:
    store = tmp_path / "store"
    _plan(store / "202607/plan.md")

    preview = plan_design_ref_repairs(
        [_issue("beads-plan", "plans:../plan.md")],
        roots=(store,),
    )

    assert [item.new_reference for item in preview.repairs] == ["plan:202607/plan.md"]
