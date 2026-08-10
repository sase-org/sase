"""Rendering tests for ``sase stitch list``."""

from __future__ import annotations

import io
import json

import pytest

import sase.vcs_list.render as render_mod
from sase.core.vcs_log_wire import VcsCommitWire
from sase.core.vcs_repo_stats_wire import VcsRepoStatsWire
from sase.vcs_list.models import RepoListing, VcsListResult, VcsListTotals
from sase.vcs_list.render import render
from sase.vcs_log.models import LogRepo


def _commit(full: str, ts: int, subject: str) -> VcsCommitWire:
    return VcsCommitWire(
        full_id=full,
        short_id=full[:7],
        author_name="bryan",
        author_email="b@x",
        timestamp=ts,
        subject=subject,
        body="",
    )


def _stats(total: int, ts: int, *, dirty: bool = False) -> VcsRepoStatsWire:
    return VcsRepoStatsWire(
        total_commits=total,
        contributors=("Bryan <b@x>",),
        last_commit=_commit("a1b2c3d4", ts, "feat: thing"),
        branch="main",
        dirty=dirty,
    )


def _result() -> VcsListResult:
    primary = LogRepo("sase", "/p/sase", "primary")
    linked = LogRepo("sase-core", "/p/core", "linked")
    return VcsListResult(
        repos=(
            RepoListing(primary, _stats(10, 300, dirty=True)),
            RepoListing(
                linked,
                None,
                description="Core backend",
                description_source="config",
                error="no such checkout",
            ),
        ),
        totals=VcsListTotals(
            repo_count=2,
            total_commits=10,
            contributors=("Bryan <b@x>",),
            latest_activity=300,
        ),
        warnings=("sase-core: no such checkout",),
        color_repos=(primary, linked),
    )


def _render(result: VcsListResult, fmt: str, color: str = "never") -> str:
    out = io.StringIO()
    render(result, fmt=fmt, color=color, out=out)
    return out.getvalue()


def test_json_shape() -> None:
    payload = json.loads(_render(_result(), "json"))

    assert payload["totals"] == {
        "contributors": 1,
        "latest_activity": 300,
        "repos": 2,
        "total_commits": 10,
    }
    assert payload["repos"][0]["name"] == "sase"
    assert payload["repos"][0]["dirty"] is True
    assert payload["repos"][0]["last_commit"]["subject"] == "feat: thing"
    assert payload["repos"][1]["description"] == "Core backend"
    assert payload["repos"][1]["description_source"] == "config"
    assert payload["repos"][1]["error"] == "no such checkout"
    assert payload["warnings"] == ["sase-core: no such checkout"]


def test_oneline_contains_rows_and_warnings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(render_mod, "_relative_age", lambda timestamp: "5m ago")

    text = _render(_result(), "oneline")

    assert "sase       primary     10c    1a  5m ago" in text
    assert "sase-core  linked       -c    -a  -" in text
    assert "Core backend  [no such checkout]" in text
    assert "WARNING: sase-core: no such checkout" in text


def test_pretty_contains_summary_repo_blocks_and_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(render_mod, "_relative_age", lambda timestamp: "5m ago")

    text = _render(_result(), "pretty")

    assert "Constellation" in text
    assert "2 repos" in text
    assert "10 commits" in text
    assert "1 contributor" in text
    assert "sase" in text
    assert "✎ dirty" in text
    assert "Core backend" in text
    assert "stats unavailable: no such checkout" in text
    assert "⚠ sase-core: no such checkout" in text
