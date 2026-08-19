"""Classify live flag beads that have no matching registry definition.

`sase flag new` writes the flag bead to the machine-wide store immediately,
but the registry entry only exists on the authoring tree until that commit
lands. Sibling checkouts then see a live bead with no definition — the same
symptom as a genuine orphan (definition deleted or never written).

This module keeps the genuine-orphan case an error, and downgrades the
in-flight window to a warning.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal


_OrphanSeverity = Literal["error", "warning"]

#: Sibling trees whose HEAD has moved past bead creation still warn for this
#: long, so an in-flight `sase flag new` does not fail `just check` while the
#: definition is landing.
ORPHAN_BEAD_GRACE = timedelta(hours=24)

_GIT_TIMEOUT_SECONDS = 5


@dataclass(frozen=True)
class _OrphanBeadVerdict:
    """Severity and optional message suffix for one definition-less live bead."""

    severity: _OrphanSeverity
    detail: str = ""


def checkout_base_committed_at(repo_root: Path) -> datetime | None:
    """Return the committer date of this checkout's shared-history base.

    Prefers ``merge-base(HEAD, @{upstream})`` so local commits on this tree
    do not make the checkout look newer than a sibling's in-flight flag bead.
    Falls back to ``HEAD`` when no upstream is configured.
    """
    merge_base = _git_stdout(repo_root, "merge-base", "HEAD", "@{upstream}")
    if merge_base is not None:
        dated = _git_committer_date(repo_root, merge_base)
        if dated is not None:
            return dated
    return _git_committer_date(repo_root, "HEAD")


def classify_orphan_bead(
    *,
    created_at: str | None,
    created_by: str | None = None,
    checkout_committed_at: datetime | None,
    now: datetime,
    grace: timedelta = ORPHAN_BEAD_GRACE,
) -> _OrphanBeadVerdict:
    """Return whether a definition-less live flag bead is in-flight or orphaned.

    Warn when the bead was created after this checkout's base commit (the tree
    is older than the bead) or when the bead is younger than *grace*. Error
    otherwise, including when ``created_at`` is missing — fail closed.
    """
    created = _as_utc(created_at)
    who = f" by {created_by}" if created_by else ""
    checkout = _coerce_utc(checkout_committed_at)
    now_utc = _coerce_utc(now) or datetime.now(UTC)

    if created is not None and checkout is not None and created > checkout:
        return _OrphanBeadVerdict(
            "warning",
            f"this checkout's HEAD is older than the bead "
            f"(created {created_at}{who}), so this is likely another "
            f"tree's in-flight flag",
        )
    if created is not None and now_utc - created <= grace:
        return _OrphanBeadVerdict(
            "warning",
            f"bead was created {_format_age(now_utc - created)} ago{who} "
            "and may still be landing",
        )
    if created is not None:
        return _OrphanBeadVerdict(
            "error",
            f"created {created_at}{who} — add the registry definition or "
            "close the bead",
        )
    if created_by:
        return _OrphanBeadVerdict(
            "error",
            f"created by {created_by} — add the registry definition or close the bead",
        )
    return _OrphanBeadVerdict("error")


def _as_utc(value: str | None) -> datetime | None:
    if not value or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return _coerce_utc(parsed)


def _coerce_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _format_age(age: timedelta) -> str:
    seconds = max(0, int(age.total_seconds()))
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    if days:
        return f"{days}d"
    if hours:
        return f"{hours}h"
    if minutes:
        return f"{minutes}m"
    return f"{sec}s"


def _git_committer_date(repo_root: Path, rev: str) -> datetime | None:
    raw = _git_stdout(repo_root, "log", "-1", "--format=%cI", rev)
    return _as_utc(raw)


def _git_env() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("GIT_DIR", None)
    env.pop("GIT_WORK_TREE", None)
    return env


def _git_stdout(repo_root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            env=_git_env(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    text = result.stdout.strip()
    return text or None


__all__ = [
    "ORPHAN_BEAD_GRACE",
    "checkout_base_committed_at",
    "classify_orphan_bead",
]
