"""Shared fixtures for the pager chrome test modules."""

from __future__ import annotations

from rich.console import Console

from sase.pager.document import PagerSection

CONSOLE = Console(color_system="truecolor")


def file_section(title: str = "artifact_links.py") -> PagerSection:
    return PagerSection(
        identity=f"file:/tmp/{title}",
        title=title,
        kind="file",
        body="line one\nline two\n",
        subject_ref=f"file:/tmp/{title}",
    )
