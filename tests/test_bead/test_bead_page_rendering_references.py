"""Created-by and reference link rendering on generated bead pages."""

from __future__ import annotations

from typing import cast

from sase.bead.project import BeadProject
from sase.bead_pages.rendering import render_bead_page
from tests.test_bead.bead_page_rendering_test_helpers import (
    CREATOR,
    CREATOR_URL,
    ReferenceLinks,
    fixtures,
    render_page,
)


def test_pages_omit_the_reference_section_when_a_bead_stores_none() -> None:
    view, root, _phase, index = fixtures()

    assert "## References" not in render_page(view, root, index)


def test_created_by_renders_as_a_link_when_the_resolver_has_one() -> None:
    view, root, _phase, index = fixtures()

    rendered = render_page(view, root, index)

    assert f"**Created by:** [{CREATOR}]({CREATOR_URL})" in rendered


def test_created_by_renders_as_code_when_the_resolver_has_no_link() -> None:
    view, root, _phase, index = fixtures()

    rendered = render_bead_page(
        cast(BeadProject, view),
        root,
        index,
        link_resolver=ReferenceLinks(),
    )

    assert f"**Created by:** `{CREATOR}`" in rendered
    assert f"[{CREATOR}]" not in rendered


def test_empty_created_by_leaves_the_ownership_line_unchanged() -> None:
    view, root, _phase, index = fixtures()
    root.created_by = ""

    rendered = render_page(view, root, index)

    assert (
        "**Owner:** `owner@example.com` · **Assignee:** `alice.athena.sase-ai.land`"
        in rendered
    )
    assert "**Created by:**" not in rendered


def test_references_link_only_where_the_resolver_produces_a_url() -> None:
    view, root, _phase, index = fixtures()
    root.refs = [
        "plans:202607/bead_pages.md",
        "bead:sase-ai",
        "commit:sase@9701511abcdef",
        "agent:alice.athena.sase-ai.1",
        "research:202607/capture.md",
    ]

    rendered = render_bead_page(
        cast(BeadProject, view),
        root,
        index,
        link_resolver=ReferenceLinks(),
    )

    assert "## References" in rendered
    assert (
        "- [plans:202607/bead\\_pages.md]"
        "(https://example.test/plans/202607/bead_pages.md)" in rendered
    )
    assert "- [bead:sase-ai](https://example.test/beads/sase-ai.md)" in rendered
    assert (
        "- [commit:sase@9701511abcdef](https://example.test/commit/9701511abcdef)"
        in rendered
    )
    # The resolver declines these, so they must stay plain text, never a link.
    assert "- agent:alice.athena.sase-ai.1" in rendered
    assert "- research:202607/capture.md" in rendered


def test_an_unparseable_reference_renders_as_escaped_plain_text() -> None:
    view, root, _phase, index = fixtures()
    root.refs = ["not a reference [x](https://evil.test)"]

    rendered = render_bead_page(
        cast(BeadProject, view),
        root,
        index,
        link_resolver=ReferenceLinks(),
    )

    # The escaped brackets keep Markdown from forming a link out of the value.
    assert "- not a reference \\[x\\](https://evil.test)" in rendered
    assert "- [not a reference" not in rendered


def test_references_render_without_any_link_resolver() -> None:
    view, root, _phase, index = fixtures()
    root.refs = ["plans:202607/bead_pages.md"]

    rendered = render_bead_page(cast(BeadProject, view), root, index)

    assert "- plans:202607/bead\\_pages.md" in rendered
