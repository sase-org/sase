"""Content digests for prompt-panel renderable trees ignore object identity."""

from __future__ import annotations

from rich.console import Group
from rich.style import Style
from rich.text import Text

from sase.ace.tui.util.lazy_syntax import lazy_renderable
from sase.ace.tui.util.renderable_digest import (
    renderable_cheap_token,
    renderable_content_digest,
)


def test_equivalent_documents_share_a_digest() -> None:
    first = Group(Text("header\n"), lazy_renderable("# body\n", "markdown"))
    second = Group(Text("header\n"), lazy_renderable("# body\n", "markdown"))

    assert renderable_content_digest(first) == renderable_content_digest(second)


def test_content_change_changes_digest() -> None:
    first = Group(Text("header\n"), lazy_renderable("# body\n", "markdown"))
    second = Group(Text("header\n"), lazy_renderable("# changed\n", "markdown"))

    assert renderable_content_digest(first) != renderable_content_digest(second)


def test_style_metadata_changes_digest() -> None:
    first = Text("same")
    first.stylize(Style(meta={"section": "one"}), 0, 4)
    second = Text("same")
    second.stylize(Style(meta={"section": "two"}), 0, 4)

    assert renderable_content_digest(first) != renderable_content_digest(second)


def test_cheap_token_matches_digest_equality() -> None:
    first = Group(Text("header\n"), lazy_renderable("# body\n", "markdown"))
    second = Group(Text("header\n"), lazy_renderable("# body\n", "markdown"))

    assert renderable_cheap_token(first) == renderable_cheap_token(second)


def test_cheap_token_invalidated_on_real_change() -> None:
    first = Group(Text("header\n"), lazy_renderable("# body\n", "markdown"))
    second = Group(Text("header\n"), lazy_renderable("# changed\n", "markdown"))

    assert renderable_cheap_token(first) != renderable_cheap_token(second)


def test_cheap_token_honors_cached_renderable_digest() -> None:
    child = lazy_renderable("# body\n", "markdown")
    assert hasattr(child, "content_digest")
    group = Group(Text("header\n"), child)

    token = renderable_cheap_token(group)
    assert isinstance(token, tuple)
    assert token[0] == "G"
    assert child.content_digest in repr(token)
    assert renderable_cheap_token(child) == ("C", child.content_digest)
