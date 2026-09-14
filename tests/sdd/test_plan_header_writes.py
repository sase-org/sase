"""Tests for frontmatter-derived plan provenance sections."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.sdd.associations import (
    PlanAgentAssociation,
    PlanAssociations,
    PlanCommitAssociation,
)
from sase.sdd.plan_header_block import (
    PlanHeaderEntry,
    PlanHeaderSection,
    PlanHeaderSectionKind,
    parse_plan_header_block,
    render_plan_header_block,
)
from sase.sdd.plan_header_writes import (
    project_plan_header_sections,
    refresh_association_sections,
    refresh_bead_plan_section,
)
from sase.sdd.store import SddStore

_BEAD_URL = (
    "https://github.com/sase-org/sase--beads/blob/main/pages/sase-ai/sase-ai.8.md"
)
_PROMPT_URL = (
    "https://github.com/sase-org/sase--agents/blob/main/prompts/202607/child.md"
)


class _Resolver:
    def bead_url(self, bead_id: str) -> str | None:
        assert bead_id == "sase-ai.8"
        return _BEAD_URL

    def prompt_url(self, prompt_ref: str) -> str | None:
        assert prompt_ref == "prompts/202607/child.md"
        return _PROMPT_URL


def _document(frontmatter: str, header: str = "") -> str:
    separator = "\n" if header else ""
    return f"---\ntier: tale\n{frontmatter}---\n\n{header}{separator}# Plan\n"


def _entries(document: str, kind: PlanHeaderSectionKind) -> tuple[PlanHeaderEntry, ...]:
    parsed = parse_plan_header_block(document)
    section = next(section for section in parsed.sections if section.kind is kind)
    return section.entries


def _commit(sha: str, subject: str, order: int = 1) -> PlanCommitAssociation:
    return PlanCommitAssociation(
        label=sha[:7],
        target=f"https://example.test/commit/{sha}",
        trailing_text=subject,
        sort_key=(order, sha),
        sha=sha,
    )


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


def test_project_plan_header_sections_skips_absent_prompt_path(
    tmp_path: Path,
) -> None:
    plans_root = tmp_path / "repo--plans"
    plan_path = plans_root / "202607" / "child.md"
    document = (
        "- **PROMPT:** [202607/prompts/existing.md](prompts/existing.md)\n\n# Plan\n"
    )

    unchanged = project_plan_header_sections(
        document,
        sdd_dir=plans_root,
        plan_path=plan_path,
        plans_root=plans_root,
        prompt_path=None,
    )

    link = parse_plan_header_block(unchanged).sections[0]
    assert link.kind is PlanHeaderSectionKind.PROMPT
    assert link.label == "202607/prompts/existing.md"
    assert link.target == "prompts/existing.md"


def test_project_plan_header_sections_installs_supplied_prompt_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plans_root = tmp_path / "repo--plans"
    plan_path = plans_root / "202607" / "child.md"
    prompt_path = plans_root / "202607" / "prompts" / "child.md"
    store = SddStore("sidecar_repos", plans_root, plans_root)
    monkeypatch.setattr(
        "sase.sdd.hosted_links.hosted_link_resolver",
        lambda *_args, **_kwargs: _Resolver(),
    )

    updated = project_plan_header_sections(
        "# Plan\n",
        sdd_dir=plans_root,
        plan_path=plan_path,
        plans_root=plans_root,
        prompt_path=prompt_path,
        store=store,
        primary_root=tmp_path,
    )

    link = parse_plan_header_block(updated).sections[0]
    assert link.kind is PlanHeaderSectionKind.PROMPT
    assert link.label == "prompts/202607/child.md"
    assert link.target == _PROMPT_URL


def test_refresh_association_sections_empty_derived_keeps_existing_text() -> None:
    header = render_plan_header_block(
        (
            PlanHeaderSection(
                kind=PlanHeaderSectionKind.AGENTS,
                entries=(
                    PlanHeaderEntry(label="zeta.agent"),
                    PlanHeaderEntry(label="alpha.agent"),
                ),
            ),
            PlanHeaderSection(
                kind=PlanHeaderSectionKind.COMMITS,
                entries=(
                    PlanHeaderEntry(
                        label="bbbbbbb",
                        target="https://example.test/commit/" + "b" * 40,
                        trailing_text="outside view",
                    ),
                ),
            ),
        )
    )
    document = _document("", header)

    assert refresh_association_sections(document, PlanAssociations()) == document


def test_refresh_association_sections_merges_and_prefers_derived_metadata() -> None:
    shared_sha = "b" * 40
    local_sha = "a" * 40
    header = render_plan_header_block(
        (
            PlanHeaderSection(
                kind=PlanHeaderSectionKind.AGENTS,
                entries=(
                    PlanHeaderEntry(
                        label="stale.agent",
                        target="https://example.test/stale",
                    ),
                    PlanHeaderEntry(
                        label="shared.agent",
                        target="https://example.test/old-agent",
                    ),
                ),
            ),
            PlanHeaderSection(
                kind=PlanHeaderSectionKind.COMMITS,
                entries=(
                    PlanHeaderEntry(
                        label=shared_sha[:7],
                        target=f"https://example.test/old/commit/{shared_sha}",
                        trailing_text="old subject",
                    ),
                    PlanHeaderEntry(
                        label="ccccccc",
                        trailing_text="retained from another writer",
                    ),
                ),
            ),
        )
    )
    document = _document("", header)
    associations = PlanAssociations(
        agents=(
            PlanAgentAssociation(
                "shared.agent",
                "https://example.test/new-agent",
                "shared.agent",
                "fresh run",
            ),
            PlanAgentAssociation("local.agent", None, "local.agent"),
        ),
        commits=(
            _commit(shared_sha, "new subject", order=2),
            _commit(local_sha, "local subject", order=1),
        ),
    )

    updated = refresh_association_sections(document, associations)

    agents = _entries(updated, PlanHeaderSectionKind.AGENTS)
    assert [entry.label for entry in agents] == [
        "local.agent",
        "shared.agent",
        "stale.agent",
    ]
    assert agents[1].target == "https://example.test/new-agent"
    assert agents[1].trailing_text == "fresh run"

    commits = _entries(updated, PlanHeaderSectionKind.COMMITS)
    assert [entry.label for entry in commits] == [
        local_sha[:7],
        shared_sha[:7],
        "ccccccc",
    ]
    assert commits[1].target == f"https://example.test/commit/{shared_sha}"
    assert commits[1].trailing_text == "new subject"
    assert refresh_association_sections(updated, associations) == updated


def test_refresh_association_sections_two_writer_order_converges() -> None:
    document = _document("")
    first_sha = "1" * 40
    second_sha = "2" * 40
    first = PlanAssociations(
        agents=(PlanAgentAssociation("first.agent", None, "first.agent"),),
        commits=(_commit(first_sha, "feat: first", order=1),),
    )
    second = PlanAssociations(
        agents=(PlanAgentAssociation("second.agent", None, "second.agent"),),
        commits=(_commit(second_sha, "feat: second", order=2),),
    )

    first_then_second = refresh_association_sections(
        refresh_association_sections(document, first),
        second,
    )
    second_then_first = refresh_association_sections(
        refresh_association_sections(document, second),
        first,
    )

    assert first_then_second == second_then_first
    assert [
        entry.label
        for entry in _entries(first_then_second, PlanHeaderSectionKind.AGENTS)
    ] == [
        "first.agent",
        "second.agent",
    ]
    assert [
        entry.label
        for entry in _entries(first_then_second, PlanHeaderSectionKind.COMMITS)
    ] == [
        first_sha[:7],
        second_sha[:7],
    ]
