"""Root classification for SDD sidecar repositories."""

from pathlib import Path

from sase.sdd._link_files import list_sdd_files, resolve_sdd_root


def _write_plan(path: Path, *, title: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\ntier: tale\n---\n# {title}\n", encoding="utf-8")


def test_beads_sidecar_is_not_misclassified_as_project_root(tmp_path: Path) -> None:
    beads = tmp_path / "sase" / "repos" / "beads"
    (beads / ".git").mkdir(parents=True)

    assert resolve_sdd_root(str(beads)) == beads.resolve()


def test_list_sdd_files_uses_flat_root_with_readme_only_plans_subdir(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo--plans"
    (root / "plans").mkdir(parents=True)
    (root / "plans" / "README.md").write_text("generated directory guide\n")
    _write_plan(root / "202607" / "flat_sidecar.md", title="Flat sidecar plan")

    files = list_sdd_files(root, kind="plans")

    assert [file.relpath for file in files] == ["202607/flat_sidecar.md"]


def test_list_sdd_files_prefers_nested_plans_subdir_with_month_dirs(
    tmp_path: Path,
) -> None:
    root = tmp_path / "sdd"
    _write_plan(root / "202607" / "flat_shadowed.md", title="Flat shadowed plan")
    _write_plan(root / "plans" / "202608" / "nested_wins.md", title="Nested wins")

    files = list_sdd_files(root, kind="plans")

    assert [file.relpath for file in files] == ["plans/202608/nested_wins.md"]
