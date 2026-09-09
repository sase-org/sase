"""Tests for resolving bead links into pager targets."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.pager.resolve import LinkTargetKind


def test_bead_link_target_enriches_the_link_neighborhood_without_exiting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A followed `bead:` link must carry the LINKS block `bead show` renders.

    `resolve_show_batch` leaves `IssueDetail.artifact_links` empty unless a
    `detail_enricher` fills it, and the CLI's own enricher calls `sys.exit` on
    failure, which a keypress handler cannot survive.
    """
    from sase.artifact_refs import parse_artifact_ref
    from sase.bead import cli_show_batch
    from sase.pager import beads
    from sase.pager.beads import bead_link_resolution

    seen: list[object] = []

    def spy(*_args: object, **kwargs: object) -> object:
        seen.append(kwargs.get("detail_enricher"))
        raise LookupError("stop after recording the enricher")

    monkeypatch.setattr(
        beads,
        "_open_contextual_store",
        lambda _stack, _context: SimpleNamespace(view=object(), workspace=None),
    )
    monkeypatch.setattr(cli_show_batch, "resolve_show_batch", spy)

    assert bead_link_resolution(parse_artifact_ref("bead:sase-uk")).target is None
    assert seen == [cli_show_batch.enrich_with_artifact_link_neighborhood]


def test_bead_link_target_resolves_foreign_bead(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.artifact_refs import parse_artifact_ref
    from sase.bead import cross_project
    from sase.bead.cross_project import BeadStoreOrigin
    from sase.bead.model import Issue, IssueType
    from sase.pager import beads
    from sase.pager.beads import bead_link_resolution

    class _View:
        def __init__(self, issues: dict[str, Issue]) -> None:
            self.issues = issues

        def __enter__(self) -> _View:
            return self

        def __exit__(self, *exc_info: object) -> None:
            del exc_info

        def show(self, issue_id: str) -> Issue:
            if issue_id in self.issues:
                return self.issues[issue_id]
            raise KeyError(issue_id)

        def get_epic_children(self, _issue_id: str) -> list[Issue]:
            return []

        def list_issues(self) -> list[Issue]:
            return list(self.issues.values())

    foreign = _View(
        {
            "bob-cli-1": Issue(
                id="bob-cli-1",
                title="Foreign",
                issue_type=IssueType.TASK,
            )
        }
    )
    origin = BeadStoreOrigin(
        project_key="gh_acme__bob-cli",
        project_label="bob-cli",
        primary_workspace=tmp_path / "bob-cli",
        beads_dir=tmp_path / "bob-cli" / "sdd" / "beads",
    )
    monkeypatch.setattr(
        beads,
        "_open_contextual_store",
        lambda _stack, _context: None,
    )
    monkeypatch.setattr(cross_project, "origin_for_bead_id", lambda _id: origin)
    monkeypatch.setattr(
        "sase.bead.cli_show_router.open_bead_project_for_beads_dir",
        lambda _path: foreign,
    )

    target = bead_link_resolution(parse_artifact_ref("bead:bob-cli-1")).target

    assert target is not None
    assert target.kind is LinkTargetKind.DOCUMENT
    assert target.document is not None
    assert "bob-cli-1 · Foreign" in target.document.sections[0].plain_text
    assert "Project: bob-cli" in target.document.sections[0].plain_text
