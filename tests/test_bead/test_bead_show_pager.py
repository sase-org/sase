"""Bead-show pager contract: production adapter, real labels, real resolve."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest

from sase.bead.cli_detail_style import DetailStyle
from sase.bead.cli_show_batch import (
    build_show_batch_document,
    default_show_render_context_resolver,
    resolve_show_batch,
)
from sase.bead.model import BeadLink, Issue, IssueType, Status
from sase.pager.app import SasePager
from sase.pager.document import section_target_spans
from sase.pager.link_scan import LinkSpanKind

from tests.pager._rendered_link_pilot import (
    follow_display,
    pager_screen,
    settle,
)


def _issues() -> dict[str, Issue]:
    return {
        "sase-zz.n0": Issue(
            id="sase-zz.n0",
            title="Fixture parent",
            issue_type=IssueType.TASK,
            status=Status.OPEN,
            links=[
                BeadLink(
                    target_ref="bead:sase-zz.n1",
                    relation="related",
                    description="child fixture",
                    origin="manual",
                )
            ],
        ),
        "sase-zz.n1": Issue(
            id="sase-zz.n1",
            title="Fixture child",
            issue_type=IssueType.TASK,
            status=Status.OPEN,
        ),
    }


@contextmanager
def _view(issues: dict[str, Issue]) -> Iterator[object]:
    class _View:
        def show(self, issue_id: str) -> Issue:
            try:
                return issues[issue_id]
            except KeyError:
                raise KeyError(issue_id) from None

        def get_epic_children(self, _issue_id: str) -> list[Issue]:
            return []

        def list_issues(self) -> list[Issue]:
            return list(issues.values())

    yield _View()


_plain_render_context = default_show_render_context_resolver(
    design_paths_are_relative_fn=lambda: False,
    plan_reference_roots_fn=lambda: (),
    artifact_reference_context_fn=lambda: None,
    resolve_bead_creator_url_fn=lambda _name: None,
    resolve_bead_page_url_fn=lambda _id: None,
)


def _parent_document() -> object:
    issues = _issues()
    with _view(issues) as view:
        batch = resolve_show_batch(
            view,
            ["sase-zz.n0"],
            format_name="full",
            include_links=True,
        )
    return build_show_batch_document(
        batch,
        style=DetailStyle.PLAIN,
        wrap=80,
        render_context_for=_plain_render_context,
    )


def test_bead_show_document_renders_the_bead_id_as_a_bare_token() -> None:
    document = _parent_document()
    spans = section_target_spans(document.sections[0], document.origin)
    assert [(span.kind, span.text) for span in spans] == [
        (LinkSpanKind.BARE_TOKEN, "sase-zz.n0"),
    ]
    assert document.origin.value == "bead"


async def test_bead_show_bare_token_follows_through_the_real_resolver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    issues = _issues()

    @contextmanager
    def fake_read_view() -> Iterator[object]:
        with _view(issues) as view:
            yield view

    monkeypatch.setattr("sase.bead.cli_common.get_read_view", fake_read_view)
    document = _parent_document()
    app = SasePager(document)
    async with app.run_test(size=(80, 24)) as pilot:
        await settle(pilot)
        await follow_display(pilot, "sase-zz.n0")
        screen = pager_screen(app)
        assert "sase-zz.n0" in screen.document.sections[0].plain_text
        assert "Fixture parent" in screen.document.sections[0].plain_text
