from __future__ import annotations

import subprocess
import sys
from pathlib import Path


import pytest

pytestmark = pytest.mark.contract

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "sase"
    / "scripts"
    / "sase_migrate_statuses"
)


def _run_migrate(root: Path, *extra_args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root), *extra_args],
        check=False,
        text=True,
        capture_output=True,
    )


def test_migrate_statuses_updates_canonical_sase_files(tmp_path: Path) -> None:
    project_dir = tmp_path / "projects" / "demo"
    project_dir.mkdir(parents=True)
    spec = project_dir / "demo.sase"
    spec.write_text(
        "NAME: demo\nSTATUS: WIP (demo_1)\nMENTORS:\n| mentor: #WIP\n",
        encoding="utf-8",
    )

    result = _run_migrate(tmp_path / "projects")

    assert result.returncode == 0
    assert "Scanned 1 project spec file(s), modified 1 file(s)." in result.stdout
    assert spec.read_text(encoding="utf-8") == (
        "NAME: demo\nSTATUS: Draft (demo_1)\nMENTORS:\n| mentor: #Draft\n"
    )


def test_migrate_statuses_still_updates_legacy_gp_files(tmp_path: Path) -> None:
    project_dir = tmp_path / "projects" / "demo"
    project_dir.mkdir(parents=True)
    spec = project_dir / "demo.gp"
    spec.write_text(
        "NAME: demo\nSTATUS: Drafted - (!: READY TO MAIL)\n",
        encoding="utf-8",
    )

    result = _run_migrate(tmp_path / "projects")

    assert result.returncode == 0
    assert "Scanned 1 project spec file(s), modified 1 file(s)." in result.stdout
    assert spec.read_text(encoding="utf-8").splitlines() == [
        "NAME: demo",
        "STATUS: Ready - (!: READY TO MAIL)",
    ]


def test_migrate_statuses_dry_run_does_not_modify_sase_file(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "projects" / "demo"
    project_dir.mkdir(parents=True)
    spec = project_dir / "demo.sase"
    original = "NAME: demo\nSTATUS: WIP\n"
    spec.write_text(original, encoding="utf-8")

    result = _run_migrate(tmp_path / "projects", "--dry-run")

    assert result.returncode == 0
    assert (
        "[DRY RUN] Scanned 1 project spec file(s), modified 1 file(s)." in result.stdout
    )
    assert spec.read_text(encoding="utf-8") == original
