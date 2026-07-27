"""Root classification for SDD sidecar repositories."""

from pathlib import Path

from sase.sdd._link_files import resolve_sdd_root


def test_beads_sidecar_is_not_misclassified_as_project_root(tmp_path: Path) -> None:
    beads = tmp_path / "sase" / "repos" / "beads"
    (beads / ".git").mkdir(parents=True)

    assert resolve_sdd_root(str(beads)) == beads.resolve()
