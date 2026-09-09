"""Shared fixtures for standalone ``SasePager`` app tests."""

from __future__ import annotations

from pathlib import Path

from textual.containers import VerticalScroll

from sase.pager.app import SasePager
from sase.pager.document import AttachedTarget, PagerDocument, PagerOrigin, PagerSection
from sase.pager.link_context import LinkAnchor
from sase.pager.screen import PagerScreen


def lines(prefix: str, count: int) -> str:
    return "\n".join(f"{prefix} {index}" for index in range(count)) + "\n"


def long_document(title: str = "one file") -> PagerDocument:
    section = PagerSection(
        identity="file:/tmp/long.py",
        title="long.py",
        kind="file",
        body=lines("line", 80),
    )
    return PagerDocument(sections=(section,), title=title, origin=PagerOrigin.FILE)


def multi_section_document() -> PagerDocument:
    sections = tuple(
        PagerSection(
            identity=f"file:/tmp/{name}.py",
            title=f"{name}.py",
            kind="file",
            body=lines(name, 30),
        )
        for name in ("alpha", "beta", "gamma")
    )
    return PagerDocument(sections=sections, title="3 files", origin=PagerOrigin.FILE)


def link_document(count: int) -> PagerDocument:
    body = "\n".join(f"https://example.test/{index}" for index in range(count)) + "\n"
    section = PagerSection(
        identity="file:/tmp/links.txt",
        title="links.txt",
        kind="file",
        body=body,
    )
    return PagerDocument(sections=(section,), title="links", origin=PagerOrigin.FILE)


def path_link_document(path: Path) -> PagerDocument:
    section = PagerSection(
        identity="file:/tmp/source.py",
        title="source.py",
        kind="file",
        body=f"see {path} for details\n",
        subject_ref="file:/tmp/source.py",
    )
    return PagerDocument(
        sections=(section,), title="source.py", origin=PagerOrigin.FILE
    )


def target_document(title: str = "target") -> PagerDocument:
    section = PagerSection(
        identity="file:/tmp/target.py", title="target.py", kind="file", body="target\n"
    )
    return PagerDocument(sections=(section,), title=title, origin=PagerOrigin.FILE)


def long_link_source_document(path: Path) -> PagerDocument:
    section = PagerSection(
        identity="file:/tmp/source.py",
        title="source.py",
        kind="file",
        body=f"{lines('source', 80)}see {path} for details\n",
        subject_ref="file:/tmp/source.py",
    )
    return PagerDocument(
        sections=(section,), title="source.py", origin=PagerOrigin.FILE
    )


def searchable_link_source_document(path: Path) -> PagerDocument:
    section = PagerSection(
        identity="file:/tmp/source.py",
        title="source.py",
        kind="file",
        body=(
            f"top\n{lines('spacer', 40)}needle target line\nsee {path} for details\n"
        ),
        subject_ref="file:/tmp/source.py",
    )
    return PagerDocument(
        sections=(section,), title="source.py", origin=PagerOrigin.FILE
    )


def attached_target_document(*, kind: str = "commit") -> PagerDocument:
    section = PagerSection(
        identity="pager-commits",
        title="Selected commits",
        kind="commit",
        body="abc1234  a commit subject\n",
        targets=(AttachedTarget(kind=kind, target="commit-object", start=0, end=7),),
    )
    return PagerDocument(sections=(section,), title="1 file", origin=PagerOrigin.FILE)


def pager_screen(app: SasePager) -> PagerScreen:
    screen = app.screen
    assert isinstance(screen, PagerScreen)
    return screen


def body_scroll(app: SasePager) -> VerticalScroll:
    return pager_screen(app).query_one("#pager-body-scroll", VerticalScroll)
