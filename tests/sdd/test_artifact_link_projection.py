"""Tests for the artifact-link Markdown projection's origin classification."""

from __future__ import annotations

from types import SimpleNamespace

from sase.sdd._artifact_link_projection import render_artifact_link_projection


def test_derived_origin_row_renders_in_the_links_block() -> None:
    resolver = SimpleNamespace(bead_url=lambda _issue_id: None)

    rendered = render_artifact_link_projection(
        "# X\n",
        artifact_id="plan:202608/x.md",
        rows=[
            {
                "source_ref": "plan:202608/x.md",
                "relation": "implements",
                "target_ref": "bead:sase-tw",
                "description": "derived from this plan's bead_id: frontmatter",
                "origin": "derived",
                "uses": 1,
            }
        ],
        store=None,  # type: ignore[arg-type]
        resolver=resolver,
    )

    assert "## Links" in rendered
    assert "implements" in rendered
    assert "bead:sase-tw" in rendered
