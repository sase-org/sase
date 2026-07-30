"""Tests for the doctor check that audits published bead-page commit links."""

from __future__ import annotations

from pathlib import Path

from sase.doctor.checks_beads import _check_bead_page_commit_links
from sase.doctor.runner import DoctorContext

_PRIMARY_REMOTE = "git@github.com:sase-org/sase.git"


def _context(tmp_path: Path) -> DoctorContext:
    return DoctorContext(
        cwd=tmp_path,
        project=None,
        sase_home=tmp_path / ".sase",
    )


def _publish(pages_root: Path, label: str, repo: str) -> Path:
    page = pages_root / "sase-b3" / "README.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(
        "## Commits\n\n"
        "| Commit | Subject | Bead | Committed (UTC) |\n"
        "|---|---|---|---|\n"
        f"| [`{label}`](https://github.com/sase-org/{repo}/commit/{'6c21bbb6' * 5})"
        " | subject | [sase-b3](README.md) | now |\n",
        encoding="utf-8",
    )
    return page


def _use_inputs(monkeypatch, pages_root: Path | None, remote: str | None) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_beads._bead_pages_audit_inputs",
        lambda _context: (pages_root, remote),
    )


def test_bead_pages_skips_without_pages_or_remote(monkeypatch, tmp_path: Path) -> None:
    _use_inputs(monkeypatch, None, None)

    check = _check_bead_page_commit_links(_context(tmp_path))

    assert check.status == "SKIP"
    assert "no published bead pages" in check.summary


def test_bead_pages_errors_on_a_misattributed_commit_link(
    monkeypatch,
    tmp_path: Path,
) -> None:
    page = _publish(tmp_path, "6c21bbb", "sase--plans")
    _use_inputs(monkeypatch, tmp_path, _PRIMARY_REMOTE)

    check = _check_bead_page_commit_links(_context(tmp_path))

    assert check.status == "ERROR"
    assert [dict(entry) for entry in check.data["misattributed"]] == [
        {
            "page": str(page),
            "label": "6c21bbb",
            "url": (f"https://github.com/sase-org/sase--plans/commit/{'6c21bbb6' * 5}"),
        }
    ]
    assert check.next_steps == ("Run `sase bead pages refresh --write`.",)


def test_bead_pages_accepts_a_qualified_sidecar_commit_link(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _publish(tmp_path, "sase--plans@6c21bbb", "sase--plans")
    _use_inputs(monkeypatch, tmp_path, _PRIMARY_REMOTE)

    check = _check_bead_page_commit_links(_context(tmp_path))

    assert check.status == "OK"
    assert not check.data["misattributed"]
