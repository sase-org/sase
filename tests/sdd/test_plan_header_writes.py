"""Tests for frontmatter-derived plan provenance sections."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.sdd.plan_header_block import (
    PlanHeaderSectionKind,
    parse_plan_header_block,
)
from sase.sdd.plan_header_writes import refresh_bead_plan_section
from sase.sdd.store import SddStore

_BEAD_URL = (
    "https://github.com/sase-org/sase--beads/blob/main/pages/sase-ai/sase-ai.8.md"
)


class _Resolver:
    def bead_url(self, bead_id: str) -> str | None:
        assert bead_id == "sase-ai.8"
        return _BEAD_URL


def _document(frontmatter: str, header: str = "") -> str:
    separator = "\n" if header else ""
    return f"---\ntier: tale\n{frontmatter}---\n\n{header}{separator}# Plan\n"


@pytest.mark.parametrize(
    "frontmatter",
    [
        "bead_id: sase-ai.8\nbead: ignored-fallback\n",
        "bead: sase-ai.8\n",
    ],
)
def test_refresh_bead_section_prefers_bead_id_and_links_hosted_page(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    frontmatter: str,
) -> None:
    store = SddStore("sidecar_repos", tmp_path, tmp_path)
    monkeypatch.setattr(
        "sase.sdd.hosted_links.hosted_link_resolver",
        lambda *_args, **_kwargs: _Resolver(),
    )

    updated = refresh_bead_plan_section(
        _document(frontmatter),
        store=store,
        primary_root=tmp_path,
    )
    section = parse_plan_header_block(updated).sections[0]

    assert section.kind is PlanHeaderSectionKind.BEAD
    assert section.label == "sase-ai.8"
    assert section.target == _BEAD_URL
    assert frontmatter.strip() in updated
    assert (
        refresh_bead_plan_section(
            updated,
            store=store,
            primary_root=tmp_path,
        )
        == updated
    )


def test_refresh_bead_section_does_not_link_a_bead_the_store_lost(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A legacy bead ID has no page, so its bullet must stay unlinked."""

    store = SddStore("sidecar_repos", tmp_path, tmp_path)
    monkeypatch.setattr(
        "sase.sdd.hosted_links.hosted_link_resolver",
        lambda *_args, **_kwargs: _Resolver(),
    )
    monkeypatch.setattr(
        "sase.bead_pages.links.known_bead_ids_for_store",
        lambda _store: frozenset({"sase-ai.9"}),
    )

    updated = refresh_bead_plan_section(
        _document("bead_id: sase-ai.8\n"),
        store=store,
        primary_root=tmp_path,
    )
    section = parse_plan_header_block(updated).sections[0]

    assert section.label == "sase-ai.8"
    assert section.target is None
    assert "- **BEAD:** sase-ai.8" in updated


def test_refresh_bead_section_keeps_link_when_store_cannot_be_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unreadable store must not strip links off every plan in the tree."""

    store = SddStore("sidecar_repos", tmp_path, tmp_path)
    monkeypatch.setattr(
        "sase.sdd.hosted_links.hosted_link_resolver",
        lambda *_args, **_kwargs: _Resolver(),
    )
    monkeypatch.setattr(
        "sase.bead_pages.links.known_bead_ids_for_store",
        lambda _store: None,
    )

    updated = refresh_bead_plan_section(
        _document("bead_id: sase-ai.8\n"),
        store=store,
        primary_root=tmp_path,
    )

    assert parse_plan_header_block(updated).sections[0].target == _BEAD_URL


def test_refresh_bead_section_reuses_supplied_known_bead_ids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A caller-supplied ID set replaces the per-plan store read."""

    store = SddStore("sidecar_repos", tmp_path, tmp_path)
    monkeypatch.setattr(
        "sase.sdd.hosted_links.hosted_link_resolver",
        lambda *_args, **_kwargs: _Resolver(),
    )

    def _unexpected_read(_store: SddStore) -> frozenset[str] | None:
        raise AssertionError("supplied known bead IDs must be reused")

    monkeypatch.setattr(
        "sase.bead_pages.links.known_bead_ids_for_store",
        _unexpected_read,
    )

    linked = refresh_bead_plan_section(
        _document("bead_id: sase-ai.8\n"),
        store=store,
        primary_root=tmp_path,
        known_bead_ids=frozenset({"sase-ai.8"}),
    )
    unlinked = refresh_bead_plan_section(
        _document("bead_id: sase-ai.8\n"),
        store=store,
        primary_root=tmp_path,
        known_bead_ids=frozenset(),
    )

    assert parse_plan_header_block(linked).sections[0].target == _BEAD_URL
    assert parse_plan_header_block(unlinked).sections[0].target is None


def test_refresh_bead_section_degrades_to_unlinked_label() -> None:
    updated = refresh_bead_plan_section(_document("bead: sase-ai.8\n"))
    section = parse_plan_header_block(updated).sections[0]

    assert section.kind is PlanHeaderSectionKind.BEAD
    assert section.label == "sase-ai.8"
    assert section.target is None
    assert "- **BEAD:** sase-ai.8" in updated


def test_refresh_bead_section_omits_and_removes_without_frontmatter() -> None:
    plain = _document("")
    assert refresh_bead_plan_section(plain) == plain

    stale = _document("", "- **BEAD:** stale-bead")
    updated = refresh_bead_plan_section(stale)

    assert "BEAD" not in updated
    assert parse_plan_header_block(updated).sections == ()
