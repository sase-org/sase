"""In-flight vs genuine-orphan classification for live flag beads."""

from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from sase.feature_flags.orphan import (
    ORPHAN_BEAD_GRACE,
    checkout_base_committed_at,
    classify_orphan_bead,
)


_NOW = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
_BEAD_AT = "2026-08-19T01:21:12Z"


def _git(cwd: Path, *args: str, env: dict[str, str] | None = None) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, env=env, capture_output=True)


def _init_repo(path: Path) -> None:
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.name", "Tests")
    _git(path, "config", "user.email", "tests@example.test")


def _commit(path: Path, message: str, when: str) -> None:
    env = os.environ.copy()
    env["GIT_AUTHOR_DATE"] = when
    env["GIT_COMMITTER_DATE"] = when
    _git(path, "add", ".", env=env)
    _git(path, "commit", "-m", message, "-q", env=env)


def test_checkout_base_committed_at_returns_none_outside_a_git_repo(
    tmp_path: Path,
) -> None:
    assert checkout_base_committed_at(tmp_path) is None


def test_checkout_base_committed_at_reads_head_committer_date(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "tracked.txt").write_text("one\n", encoding="utf-8")
    _commit(tmp_path, "seed", "2026-08-01T00:00:00 +0000")

    dated = checkout_base_committed_at(tmp_path)

    assert dated == datetime(2026, 8, 1, tzinfo=UTC)


def test_checkout_base_committed_at_prefers_upstream_merge_base(
    tmp_path: Path,
) -> None:
    origin = tmp_path / "origin"
    clone = tmp_path / "clone"
    origin.mkdir()
    _init_repo(origin)
    (origin / "tracked.txt").write_text("one\n", encoding="utf-8")
    _commit(origin, "seed", "2026-08-01T00:00:00 +0000")
    subprocess.run(
        ["git", "clone", "-q", str(origin), str(clone)],
        check=True,
        capture_output=True,
    )
    _git(clone, "config", "user.name", "Tests")
    _git(clone, "config", "user.email", "tests@example.test")
    (origin / "tracked.txt").write_text("two\n", encoding="utf-8")
    _commit(origin, "later", "2026-08-18T00:00:00 +0000")
    _git(clone, "fetch", "-q", "origin")
    (clone / "local.txt").write_text("local\n", encoding="utf-8")
    _commit(clone, "local", "2026-08-19T00:00:00 +0000")

    dated = checkout_base_committed_at(clone)

    assert dated == datetime(2026, 8, 1, tzinfo=UTC)


def test_classify_warns_when_bead_is_newer_than_checkout() -> None:
    verdict = classify_orphan_bead(
        created_at=_BEAD_AT,
        created_by="sase-qn.2",
        checkout_committed_at=datetime(2026, 8, 18, tzinfo=UTC),
        now=_NOW,
    )

    assert verdict.severity == "warning"
    assert "older than the bead" in verdict.detail
    assert "sase-qn.2" in verdict.detail


def test_classify_warns_when_bead_is_within_grace_even_if_checkout_is_newer() -> None:
    created = _NOW - (ORPHAN_BEAD_GRACE / 2)
    verdict = classify_orphan_bead(
        created_at=created.isoformat().replace("+00:00", "Z"),
        created_by="sase-qn.2",
        checkout_committed_at=_NOW,
        now=_NOW,
    )

    assert verdict.severity == "warning"
    assert "may still be landing" in verdict.detail


def test_classify_errors_when_bead_is_older_than_checkout_and_grace() -> None:
    created = _NOW - (ORPHAN_BEAD_GRACE * 2)
    verdict = classify_orphan_bead(
        created_at=created.isoformat().replace("+00:00", "Z"),
        created_by="sase-old",
        checkout_committed_at=_NOW,
        now=_NOW,
    )

    assert verdict.severity == "error"
    assert "add the registry definition" in verdict.detail
    assert "sase-old" in verdict.detail


def test_classify_errors_when_created_at_is_missing() -> None:
    verdict = classify_orphan_bead(
        created_at=None,
        checkout_committed_at=datetime(2026, 8, 1, tzinfo=UTC),
        now=_NOW,
    )

    assert verdict.severity == "error"
    assert verdict.detail == ""
