"""Shared test data for the Artifacts Stitches pane."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from io import StringIO
from typing import Any

from rich.console import Console

from sase.core.vcs_log_wire import AggregatedCommitWire, VcsCommitWire
from sase.vcs_log.models import LogRepo, RepoRemoteState, VcsLogResult


_DIFF = """diff --git a/src/app.py b/src/app.py
index 1111111..2222222 100644
--- a/src/app.py
+++ b/src/app.py
@@ -1 +1,2 @@
 old
+new
"""


def _rendered_text(renderable: Any) -> str:
    stream = StringIO()
    Console(file=stream, color_system=None, width=120).print(renderable)
    return stream.getvalue()


def _byte_heavy_diff() -> str:
    header = """diff --git a/events.jsonl b/events.jsonl
--- a/events.jsonl
+++ b/events.jsonl
@@ -1 +1 @@
"""
    return header + ("+" + "x" * 7_000 + "\n") * 500


def _result(timestamp: int | None = None) -> VcsLogResult:
    now = timestamp or int(datetime.now(tz=UTC).timestamp())
    commits = (
        AggregatedCommitWire(
            "alpha-platform-repository",
            VcsCommitWire(
                full_id="a" * 40,
                short_id="aaaaaaa",
                author_name="Ada Lovelace, Principal Analytical Engine Programmer",
                author_email="ada@example.com",
                timestamp=now,
                subject=(
                    "feat(artifacts): keep every commit timeline entry on one calm "
                    "physical row"
                ),
                body=(
                    "Render the selected commit's complete metadata without "
                    "sacrificing scan density.\n\n"
                    "SASE_TYPE=bead_work\n"
                    "SASE_AGENT=sase-69.3\n"
                    "SASE_MACHINE=athena\n"
                    "SASE_PLAN=sdd/plans/commits_single_line_timeline.md\n"
                    "SASE_BUG=42"
                ),
                presence="local_only",
            ),
        ),
        AggregatedCommitWire(
            "sase-core-foundation",
            VcsCommitWire(
                full_id="b" * 40,
                short_id="bbbbbbb",
                author_name="Rear Admiral Grace Murray Hopper",
                author_email="grace@example.com",
                timestamp=now - 60,
                subject=(
                    "fix(artifacts): preserve the selected commit identity across "
                    "timeline refreshes"
                ),
                body="Keep the highlighted SHA across refreshes.",
                presence="remote_only",
            ),
        ),
    )
    return VcsLogResult(
        repos=(
            LogRepo("alpha-platform-repository", "/tmp/alpha", "primary"),
            LogRepo("sase-core-foundation", "/tmp/core", "linked"),
        ),
        commits=commits,
        warnings=(),
        remote_states=(
            RepoRemoteState(
                "alpha-platform-repository", "origin/main", 1, 0, False, 1.0
            ),
            RepoRemoteState("sase-core-foundation", "origin/main", 0, 1, True, 1.0),
        ),
    )


def _result_with_sidecar(timestamp: int | None = None) -> VcsLogResult:
    base = _result(timestamp)
    now = timestamp or int(datetime.now(tz=UTC).timestamp())
    sidecar = AggregatedCommitWire(
        "plans",
        VcsCommitWire(
            full_id="c" * 40,
            short_id="ccccccc",
            author_name="Plan Curator",
            author_email="plans@example.com",
            timestamp=now - 120,
            subject="docs(plans): record the approved sidecar rollout",
            body="Keep plans history available through sidecar:true.",
            presence="synced",
        ),
    )
    return replace(
        base,
        repos=(*base.repos, LogRepo("plans", "/tmp/plans", "sidecar")),
        commits=(sidecar, *base.commits),
        remote_states=(
            *base.remote_states,
            RepoRemoteState("plans", "origin/main", 0, 0, True, 1.0),
        ),
    )


def _result_with_merge(timestamp: int | None = None) -> VcsLogResult:
    base = _result(timestamp)
    now = timestamp or int(datetime.now(tz=UTC).timestamp())
    merge = AggregatedCommitWire(
        "alpha-platform-repository",
        VcsCommitWire(
            full_id="m" * 40,
            short_id="mmmmmmm",
            author_name="Merge Bot",
            author_email="merge@example.com",
            timestamp=now + 60,
            parent_ids=("a" * 40, "b" * 40),
            subject="Merge pull request #123 from sase-org/merge-support",
            body="Add merge support to the commit log\n\nPreserve the raw body.",
            presence="synced",
        ),
    )
    return replace(base, commits=(merge, *base.commits))
