"""Top-level Patch data model."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import cached_property
import os
from typing import Any, cast

from .entries import CommentEntry, DeltaEntry, TimestampEntry
from .hooks import HookEntry
from .mentors import MentorEntry
from .stitches import Stitch


def _coerce_stitch_list(
    stitches: Sequence[Stitch | Mapping[str, object]] | None,
) -> list[Stitch] | None:
    if stitches is None:
        return None
    if isinstance(stitches, list) and all(
        isinstance(stitch, Stitch) for stitch in stitches
    ):
        return cast(list[Stitch], stitches)
    return [
        stitch
        if isinstance(stitch, Stitch)
        else Stitch(**cast(dict[str, Any], dict(stitch)))
        for stitch in stitches
    ]


@dataclass(init=False)
class Patch:
    """Represents a single Patch."""

    name: str
    description: str
    parent: str | None
    pr_url: str | None
    status: str
    file_path: str
    line_number: int
    bug: str | None = None
    stitches: list[Stitch] | None = None
    hooks: list[HookEntry] | None = None
    comments: list[CommentEntry] | None = None
    mentors: list[MentorEntry] | None = None
    timestamps: list[TimestampEntry] | None = None
    deltas: list[DeltaEntry] | None = None
    project_display_name: str | None = None
    refs: list[str] | None = None
    stitch_section_header: str | None = None

    def __init__(
        self,
        name: str,
        description: str,
        parent: str | None,
        pr_url: str | None = None,
        status: str | None = None,
        file_path: str = "",
        line_number: int = 0,
        bug: str | None = None,
        commits: Sequence[Stitch | Mapping[str, object]] | None = None,
        hooks: list[HookEntry] | None = None,
        comments: list[CommentEntry] | None = None,
        mentors: list[MentorEntry] | None = None,
        timestamps: list[TimestampEntry] | None = None,
        deltas: list[DeltaEntry] | None = None,
        project_display_name: str | None = None,
        refs: list[str] | None = None,
        stitch_section_header: str | None = None,
        *,
        cl: str | None = None,
        stitches: Sequence[Stitch | Mapping[str, object]] | None = None,
    ) -> None:
        if pr_url is not None and cl is not None and pr_url != cl:
            raise ValueError("Patch received conflicting pr_url and legacy cl")
        if status is None:
            raise TypeError("Patch missing required argument: 'status'")
        legacy_stitches = _coerce_stitch_list(commits)
        canonical_stitches = _coerce_stitch_list(stitches)
        if (
            legacy_stitches is not None
            and canonical_stitches is not None
            and legacy_stitches != canonical_stitches
        ):
            raise ValueError("Patch received conflicting commits and stitches")

        self.name = name
        self.description = description
        self.parent = parent
        self.pr_url = pr_url if pr_url is not None else cl
        self.status = status
        self.file_path = file_path
        self.line_number = line_number
        self.bug = bug
        self.stitches = (
            canonical_stitches if canonical_stitches is not None else legacy_stitches
        )
        self.hooks = hooks
        self.comments = comments
        self.mentors = mentors
        self.timestamps = timestamps
        self.deltas = deltas
        self.project_display_name = project_display_name
        self.refs = refs
        self.stitch_section_header = stitch_section_header

    @property
    def cl(self) -> str | None:
        """Legacy compatibility alias for :attr:`pr_url`."""
        return self.pr_url

    @cl.setter
    def cl(self, value: str | None) -> None:
        self.pr_url = value

    @property
    def commits(self) -> list[Stitch] | None:
        """Legacy compatibility alias for :attr:`stitches`."""
        return self.stitches

    @commits.setter
    def commits(self, value: list[Stitch] | None) -> None:
        self.stitches = value

    @property
    def project_basename(self) -> str:
        """Extract project basename from file_path.

        Returns:
            Project name without extension (e.g., "myproject" from "myproject.sase"
            or "myproject-archive.sase").
        """
        basename = os.path.splitext(os.path.basename(self.file_path))[0]
        if basename.endswith("-archive"):
            return basename[:-8]
        return basename

    @cached_property
    def project_name(self) -> str:
        """Parent directory name of ``file_path`` (e.g. ``"myproject"`` from
        ``"~/.sase/projects/myproject/myproject.sase"``).

        Cached because ``Path(...).parent.name`` is surprisingly expensive
        (pathlib churn) and this is read in hot filter paths for every
        patch on every filter pass.
        """
        return os.path.basename(os.path.dirname(self.file_path))

    @property
    def project_query_name(self) -> str:
        """Effective identity for exact ``project:`` query matching.

        A configured ``PROJECT_NAME`` replaces the canonical directory key as
        the query identity. Storage and VCS callers continue using
        :attr:`project_name` and :attr:`project_basename`.
        """
        return self.project_display_name or self.project_name


ChangeSpec = Patch
