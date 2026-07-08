"""Golden rendering tests for ``sase vcs log`` (color forced off)."""

from __future__ import annotations

import io
import json
from datetime import datetime

import pytest

import sase.vcs_log.render as render_mod
from sase.core.vcs_log_wire import AggregatedCommitWire, VcsCommitWire
from sase.vcs_log.models import LogRepo, VcsLogResult
from sase.vcs_log.render import render


def _entry(
    repo: str, full: str, ts: int, subject: str, author: str = "bryan"
) -> AggregatedCommitWire:
    return AggregatedCommitWire(
        repo=repo,
        commit=VcsCommitWire(
            full_id=full,
            short_id=full[:7],
            author_name=author,
            author_email="b@x",
            timestamp=ts,
            subject=subject,
            body="",
        ),
    )


def _result() -> VcsLogResult:
    return VcsLogResult(
        repos=(
            LogRepo("sase", "/p/sase", "primary"),
            LogRepo("sase-core", "/p/core", "linked"),
        ),
        commits=(
            _entry("sase", "a1b2c3d4", 300, "fix(sdd): link store"),
            _entry("sase-core", "9f8e7d6c", 200, "feat(core): parser", "amy"),
            _entry("sase", "4c5d6e7f", 100, "docs: notes"),
        ),
        warnings=("sase-telegram: no such checkout",),
    )


def _render(result: VcsLogResult, fmt: str, color: str = "never") -> str:
    out = io.StringIO()
    render(result, fmt=fmt, color=color, out=out)
    return out.getvalue()


def test_oneline_golden() -> None:
    assert _render(_result(), "oneline") == (
        "a1b2c3d sase      fix(sdd): link store\n"
        "9f8e7d6 sase-core feat(core): parser\n"
        "4c5d6e7 sase      docs: notes\n"
    )


def test_oneline_empty_is_blank() -> None:
    empty = VcsLogResult(repos=(), commits=(), warnings=())
    assert _render(empty, "oneline") == ""


def test_json_shape_and_ordering() -> None:
    payload = json.loads(_render(_result(), "json"))
    assert list(payload.keys()) == ["commits", "repos", "warnings"]
    assert [c["short_id"] for c in payload["commits"]] == [
        "a1b2c3d",
        "9f8e7d6",
        "4c5d6e7",
    ]
    # Each commit carries repo label + ids + author + email + timestamp + subject.
    first = payload["commits"][0]
    assert first == {
        "author_email": "b@x",
        "author_name": "bryan",
        "full_id": "a1b2c3d4",
        "repo": "sase",
        "short_id": "a1b2c3d",
        "subject": "fix(sdd): link store",
        "timestamp": 300,
    }
    assert payload["repos"][0] == {
        "kind": "primary",
        "name": "sase",
        "path": "/p/sase",
    }
    assert payload["warnings"] == ["sase-telegram: no such checkout"]


def test_json_empty_result() -> None:
    empty = VcsLogResult(repos=(), commits=(), warnings=())
    payload = json.loads(_render(empty, "json"))
    assert payload == {"commits": [], "repos": [], "warnings": []}


def test_pretty_day_groups_labels_and_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 7, 8, 15, 0)
    local = {
        300: datetime(2026, 7, 8, 14, 22),  # Today
        200: datetime(2026, 7, 8, 13, 5),  # Today
        100: datetime(2026, 7, 7, 18, 40),  # Yesterday
    }
    monkeypatch.setattr(render_mod, "_local_now", lambda: now)
    monkeypatch.setattr(render_mod, "_to_local", lambda ts: local[ts])

    text = _render(_result(), "pretty")

    # Day headers appear once each, Today before Yesterday.
    assert "── Today " in text
    assert "── Yesterday " in text
    assert text.index("── Today ") < text.index("── Yesterday ")
    # Legend lists both repos with counts.
    assert "sase (2)" in text
    assert "sase-core (1)" in text
    # Rows carry short SHA, repo label, subject, author, and time.
    assert "a1b2c3d" in text
    assert "14:22" in text
    assert "feat(core): parser" in text
    assert "· amy" in text
    # Ordering: newest commit before the yesterday commit.
    assert text.index("fix(sdd): link store") < text.index("docs: notes")
    # Warnings surfaced in a trailing block.
    assert "⚠ sase-telegram: no such checkout" in text


def test_pretty_empty_shows_no_commits() -> None:
    empty = VcsLogResult(repos=(), commits=(), warnings=())
    text = _render(empty, "pretty")
    assert "No commits found" in text


def test_pretty_empty_still_shows_warnings() -> None:
    empty = VcsLogResult(repos=(), commits=(), warnings=("boom",))
    text = _render(empty, "pretty")
    assert "No commits found" in text
    assert "⚠ boom" in text
