"""Shared fixtures and assertions for VCS log rendering tests."""

from __future__ import annotations

import io
from collections.abc import Callable
from datetime import datetime

import pytest
from rich.text import Text

import sase.vcs_log._render_console as console_mod
import sase.vcs_log._render_util as util_mod
import sase.vcs_log.render as render_mod
from sase.core.vcs_log_wire import (
    AggregatedCommitWire,
    CommitPresence,
    VcsCommitWire,
)
from sase.vcs_log.models import CommitFilters, LogRepo, RepoRemoteState, VcsLogResult
from sase.vcs_log.render import render


def _entry(
    repo: str,
    full: str,
    ts: int,
    subject: str,
    author: str = "bryan",
    body: str = "",
    presence: CommitPresence = "synced",
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
            body=body,
            presence=presence,
        ),
    )


def _result() -> VcsLogResult:
    return VcsLogResult(
        repos=(
            LogRepo("sase", "/p/sase", "primary"),
            LogRepo("sase-core", "/p/core", "linked"),
        ),
        commits=(
            _entry(
                "sase",
                "a1b2c3d4",
                300,
                "fix(sdd): link store",
                presence="local_only",
            ),
            _entry(
                "sase-core",
                "9f8e7d6c",
                200,
                "feat(core): parser",
                "amy",
                presence="remote_only",
            ),
            _entry("sase", "4c5d6e7f", 100, "docs: notes", presence="synced"),
        ),
        warnings=("sase-telegram: no such checkout",),
        remote_states=(
            RepoRemoteState("sase", "origin/main", 1, 0, True),
            RepoRemoteState("sase-core", "origin/main", 0, 1, True),
        ),
    )


def _tagged_result() -> VcsLogResult:
    return VcsLogResult(
        repos=(LogRepo("sase", "/p/sase", "primary"),),
        commits=(
            _entry(
                "sase",
                "a1b2c3d4",
                300,
                "tagged subject",
                body="body text\n\nSASE_TYPE=sdd\nSASE_PLAN=sdd/foo.md",
            ),
            _entry("sase", "b2c3d4e5", 200, "plain subject"),
        ),
        warnings=(),
    )


def _linked_tagged_result() -> VcsLogResult:
    return VcsLogResult(
        repos=(LogRepo("sase", "/p/sase", "primary"),),
        commits=(
            _entry(
                "sase",
                "a1b2c3d4",
                300,
                "linked plan",
                body=(
                    "body text\n\nSASE_PLAN=[202607/foo.md][1]\n\n"
                    "[1]: https://github.com/acme/plans/blob/main/202607/foo.md"
                ),
            ),
        ),
        warnings=(),
    )


def _render(
    result: VcsLogResult,
    fmt: str,
    color: str = "never",
    *,
    limit: int = 40,
    filters: CommitFilters | None = None,
    reverse: bool = False,
    show_tags: bool = True,
    all_projects: bool = False,
) -> str:
    out = io.StringIO()
    render(
        result,
        fmt=fmt,
        color=color,
        out=out,
        limit=limit,
        filters=filters,
        reverse=reverse,
        show_tags=show_tags,
        all_projects=all_projects,
    )
    return out.getvalue()


def _patch_clock(
    monkeypatch: pytest.MonkeyPatch,
    *,
    to_local: Callable[[int], datetime] | None = None,
    local_now: Callable[[], datetime] | None = None,
    relative_age: Callable[[datetime], str] | None = None,
    now_epoch: Callable[[], float] | None = None,
) -> None:
    """Pin the render clock helpers in every module that imported them."""
    if to_local is not None:
        for module in (render_mod, console_mod, util_mod):
            monkeypatch.setattr(module, "to_local", to_local)
    if local_now is not None:
        for module in (render_mod, console_mod, util_mod):
            monkeypatch.setattr(module, "local_now", local_now)
    if relative_age is not None:
        monkeypatch.setattr(console_mod, "relative_age", relative_age)
    if now_epoch is not None:
        monkeypatch.setattr(util_mod, "_now_epoch", now_epoch)


def _styles_covering(text: Text, fragment: str) -> list[str]:
    start = text.plain.index(fragment)
    end = start + len(fragment)
    return [
        str(span.style)
        for span in text.spans
        if span.start <= start and span.end >= end
    ]
