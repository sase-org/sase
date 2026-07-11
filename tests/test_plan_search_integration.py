"""End-to-end integration coverage for ``sase plan search``.

Unlike :mod:`tests.test_plan_search_cli` (which calls the handler in-process),
these tests drive the real ``python -m sase plan search`` entry point as a
subprocess over a temp repo ``sdd/`` tree plus a temp ``~/.sase/plans/`` archive.
That exercises the full ``parse -> dispatch -> Rust-backed facade -> render``
path for every output format the design promises: ``compact``, ``full``,
``json``, and ``markdown``.

The repo corpus is wired by running the subprocess with ``cwd`` at the temp repo
(so ``resolve_sdd_root`` finds ``<repo>/sdd``) and ``SASE_HOME`` pointed at the
temp archive (so the local-plans dir resolves under it). Local plans are dated
older than every repo plan so repo-prioritization holds under both the repo and
recency ranking boosts.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def _write_plan(
    path: Path,
    *,
    title: str,
    status: str,
    create_time: str,
    body: str,
    tier: str = "tale",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\ntier: {tier}\ncreate_time: {create_time}\nstatus: {status}\n---\n# {title}\n\n{body}\n",
        encoding="utf-8",
    )


@pytest.fixture
def corpus(tmp_path: Path) -> tuple[Path, Path]:
    """Build a temp repo ``sdd/`` tree (tale/epic/research) + a local archive."""
    repo = tmp_path / "repo"
    sase_home = tmp_path / ".sase"
    repo.mkdir(parents=True)
    subprocess.run(
        ["git", "init", "-q"],
        cwd=repo,
        check=True,
    )
    bare = tmp_path / "repo.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", str(bare)],
        cwd=repo,
        check=True,
    )

    _write_plan(
        repo / "sdd" / "plans" / "202606" / "auth_token_refresh.md",
        title="Refresh auth tokens on 401",
        status="wip",
        create_time="2026-06-18 21:29:20",
        body="Retry the request once after refreshing the auth token.",
    )
    _write_plan(
        repo / "sdd" / "plans" / "202605" / "unified_auth.md",
        title="Unified auth across providers",
        status="done",
        create_time="2026-05-10 09:00:00",
        body="Consolidate the providers behind one interface.",
        tier="epic",
    )
    _write_plan(
        repo / "sdd" / "research" / "202604" / "auth_strategy.md",
        title="Long-term auth strategy",
        status="wip",
        create_time="2026-04-15 09:00:00",
        body="Where authentication is heading over the next year.",
    )
    # Dated older than every repo plan so repo plans win on both boosts.
    _write_plan(
        sase_home / "plans" / "202603" / "auth_login_fix.md",
        title="Fix login auth race",
        status="done",
        create_time="2026-03-02 08:30:00",
        body="Guard the session write behind a lock.",
    )
    return repo, sase_home


def _run_cli(
    args: list[str], *, repo: Path, sase_home: Path
) -> subprocess.CompletedProcess[str]:
    """Run ``python -m sase plan search <args>`` against the temp corpus."""
    env = dict(os.environ)
    env["SASE_HOME"] = str(sase_home)
    env["PYTHONIOENCODING"] = "utf-8"
    env["NO_COLOR"] = "1"
    return subprocess.run(
        [sys.executable, "-m", "sase", "plan", "search", *args],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def test_json_envelope_is_repo_prioritized(corpus: tuple[Path, Path]) -> None:
    repo, sase_home = corpus
    result = _run_cli(["auth", "--format", "json"], repo=repo, sase_home=sase_home)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["query"] == "auth"
    assert payload["count"] == 4
    # All three repo plans rank above the single local plan (repo boost).
    sources = [r["plan"]["source"] for r in payload["results"]]
    assert sources == ["repo", "repo", "repo", "local"]
    assert payload["results"][-1]["plan"]["name"] == "auth_login_fix"
    top = payload["results"][0]
    assert top["plan"]["kind"] == "tale"
    assert "title" in top["matched_fields"]
    assert isinstance(top["score"], float)


def test_compact_groups_repo_above_local(corpus: tuple[Path, Path]) -> None:
    repo, sase_home = corpus
    result = _run_cli(
        ["auth", "--format", "compact", "--color", "never"],
        repo=repo,
        sase_home=sase_home,
    )

    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert "REPO" in out and "LOCAL" in out
    assert out.index("REPO") < out.index("LOCAL")
    assert "auth_token_refresh" in out
    assert "4 plans · 3 repo · 1 local · sorted by relevance" in out


def test_markdown_renders_grouped_tables(corpus: tuple[Path, Path]) -> None:
    repo, sase_home = corpus
    result = _run_cli(["auth", "--format", "markdown"], repo=repo, sase_home=sase_home)

    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert out.startswith("# Plan Search Results")
    assert "**Query:** `auth`" in out
    assert "## REPO — sdd/" in out
    assert "## LOCAL — ~/.sase/plans/" in out
    assert "| Status | Kind | Plan | Title | Created |" in out


def test_full_renders_panels(corpus: tuple[Path, Path]) -> None:
    repo, sase_home = corpus
    result = _run_cli(
        ["auth", "--format", "full", "--color", "never"],
        repo=repo,
        sase_home=sase_home,
    )

    assert result.returncode == 0, result.stderr
    out = result.stdout
    # One bordered rich panel per match, carrying the title and matched fields.
    assert "Refresh auth tokens on 401" in out
    assert "Matched" in out
    assert "╭" in out


def test_browse_without_query_applies_filters(corpus: tuple[Path, Path]) -> None:
    repo, sase_home = corpus
    # No query (browse) + source/kind filters narrow to the single epic.
    result = _run_cli(
        ["--format", "json", "--source", "repo", "--kind", "epic"],
        repo=repo,
        sase_home=sase_home,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["query"] == ""
    assert [r["plan"]["name"] for r in payload["results"]] == ["unified_auth"]
    # Browse mode reports no matched fields.
    assert payload["results"][0]["matched_fields"] == []
