"""Regression tests for single-store bead CLI reads."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.sdd_policy_helpers import set_sdd_policy

from sase.main.entry import main as sase_main


def _write_store(root: Path, issues: list[dict[str, Any]]) -> None:
    beads_dir = root / "sdd" / "beads"
    beads_dir.mkdir(parents=True)
    (beads_dir / "config.json").write_text(
        json.dumps({"issue_prefix": "beads", "next_counter": 4, "owner": ""}),
        encoding="utf-8",
    )
    (beads_dir / "issues.jsonl").write_text(
        "".join(json.dumps(issue, separators=(",", ":")) + "\n" for issue in issues),
        encoding="utf-8",
    )


def _issue(
    issue_id: str,
    title: str,
    *,
    updated_at: str,
    ready: bool = False,
    dependencies: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "id": issue_id,
        "title": title,
        "status": "ready" if ready else "open",
        "issue_type": "task" if ready else "plan",
        "tier": None if ready else "epic",
        "parent_id": None,
        "owner": "",
        "assignee": "",
        "created_at": "2026-01-01T00:00:00Z",
        "created_by": "",
        "updated_at": updated_at,
        "closed_at": None,
        "close_reason": None,
        "description": "",
        "notes": "",
        "design": "",
        "model": "",
        "is_ready_to_work": False,
        "changespec_name": "",
        "changespec_bug_id": "",
        "dependencies": dependencies or [],
    }


def _dep(issue_id: str, depends_on_id: str) -> dict[str, str]:
    return {
        "issue_id": issue_id,
        "depends_on_id": depends_on_id,
        "created_at": "2026-01-01T00:01:00Z",
        "created_by": "",
    }


def _write_sibling_stores(tmp_path: Path) -> tuple[Path, Path]:
    primary = tmp_path / "project"
    sibling = tmp_path / "project_2"
    primary.mkdir()
    sibling.mkdir()

    _write_store(
        primary,
        [
            _issue(
                "beads-1",
                "Primary Local",
                updated_at="2026-01-01T00:00:00Z",
                ready=True,
            ),
            _issue(
                "beads-2",
                "Primary Blocked",
                updated_at="2026-01-01T00:01:00Z",
                dependencies=[_dep("beads-2", "beads-1")],
            ),
        ],
    )
    _write_store(
        sibling,
        [
            _issue(
                "beads-1",
                "Sibling Newer",
                updated_at="2026-01-02T00:00:00Z",
                ready=True,
            ),
            _issue(
                "beads-2",
                "Sibling Blocked",
                updated_at="2026-01-02T00:01:00Z",
                dependencies=[_dep("beads-2", "beads-1")],
            ),
            _issue(
                "beads-3",
                "Sibling Extra",
                updated_at="2026-01-02T00:02:00Z",
                ready=True,
            ),
        ],
    )
    return primary, sibling


def _run_bead(
    argv: list[str],
    *,
    cwd: Path,
    primary: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> tuple[int, str, str]:
    monkeypatch.chdir(cwd)
    monkeypatch.setattr(sys, "argv", ["sase", "bead", *argv])
    monkeypatch.setattr(
        "sase.bead.workspace.resolve_primary_workspace",
        lambda: primary,
    )
    set_sdd_policy(monkeypatch, "in_tree")

    with pytest.raises(SystemExit) as excinfo:
        sase_main()

    captured = capsys.readouterr()
    return int(excinfo.value.code or 0), captured.out, captured.err


def test_read_commands_use_primary_store_from_primary_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    primary, _sibling = _write_sibling_stores(tmp_path)

    code, out, err = _run_bead(
        ["list"], cwd=primary, primary=primary, monkeypatch=monkeypatch, capsys=capsys
    )
    assert code == 0
    assert err == ""
    assert "Primary Local" in out
    assert "Sibling Newer" not in out
    assert "Sibling Extra" not in out

    code, out, err = _run_bead(
        ["show", "beads-1"],
        cwd=primary,
        primary=primary,
        monkeypatch=monkeypatch,
        capsys=capsys,
    )
    assert code == 0
    assert err == ""
    assert "Primary Local" in out
    assert "Sibling Newer" not in out

    code, out, err = _run_bead(
        ["ready"], cwd=primary, primary=primary, monkeypatch=monkeypatch, capsys=capsys
    )
    assert code == 0
    assert err == ""
    assert "Primary Local" in out
    assert "Sibling Extra" not in out

    code, out, err = _run_bead(
        ["blocked"],
        cwd=primary,
        primary=primary,
        monkeypatch=monkeypatch,
        capsys=capsys,
    )
    assert code == 0
    assert err == ""
    assert "Primary Blocked" in out
    assert "Sibling Blocked" not in out

    code, out, err = _run_bead(
        ["stats"], cwd=primary, primary=primary, monkeypatch=monkeypatch, capsys=capsys
    )
    assert code == 0
    assert err == ""
    assert "  Total:       2\n" in out


def test_read_commands_use_sibling_store_from_sibling_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    primary, sibling = _write_sibling_stores(tmp_path)

    code, out, err = _run_bead(
        ["list"], cwd=sibling, primary=primary, monkeypatch=monkeypatch, capsys=capsys
    )
    assert code == 0
    assert err == ""
    assert "Sibling Newer" in out
    assert "Sibling Extra" in out
    assert "Primary Local" not in out

    code, out, err = _run_bead(
        ["show", "beads-1"],
        cwd=sibling,
        primary=primary,
        monkeypatch=monkeypatch,
        capsys=capsys,
    )
    assert code == 0
    assert err == ""
    assert "Sibling Newer" in out
    assert "Primary Local" not in out

    code, out, err = _run_bead(
        ["ready"], cwd=sibling, primary=primary, monkeypatch=monkeypatch, capsys=capsys
    )
    assert code == 0
    assert err == ""
    assert "Sibling Newer" in out
    assert "Sibling Extra" in out
    assert "Primary Local" not in out

    code, out, err = _run_bead(
        ["blocked"],
        cwd=sibling,
        primary=primary,
        monkeypatch=monkeypatch,
        capsys=capsys,
    )
    assert code == 0
    assert err == ""
    assert "Sibling Blocked" in out
    assert "Primary Blocked" not in out

    code, out, err = _run_bead(
        ["stats"], cwd=sibling, primary=primary, monkeypatch=monkeypatch, capsys=capsys
    )
    assert code == 0
    assert err == ""
    assert "  Total:       3\n" in out


def test_read_commands_use_sibling_store_from_sibling_subdirectory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    primary, sibling = _write_sibling_stores(tmp_path)
    subdir = sibling / "src" / "pkg"
    subdir.mkdir(parents=True)

    code, out, err = _run_bead(
        ["list"], cwd=subdir, primary=primary, monkeypatch=monkeypatch, capsys=capsys
    )
    assert code == 0
    assert err == ""
    assert "Sibling Newer" in out
    assert "Sibling Extra" in out
    assert "Primary Local" not in out

    code, out, err = _run_bead(
        ["show", "beads-1"],
        cwd=subdir,
        primary=primary,
        monkeypatch=monkeypatch,
        capsys=capsys,
    )
    assert code == 0
    assert err == ""
    assert "Sibling Newer" in out
    assert "Primary Local" not in out
