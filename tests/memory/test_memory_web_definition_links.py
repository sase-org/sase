"""Tests for per-definition authored-link records used by the glossary preview."""

from __future__ import annotations

from pathlib import Path

from sase.core.glossary_facade import GlossaryCatalog, build_glossary_catalog
from sase.memory.web import discover_memory_webs
from sase.memory.web.catalog import memory_web_glossary_entries
from sase.memory.web.closure import GlossaryDefinitionLink, glossary_definition_links
from sase.memory.web.lookup import ordered_web_strands
from sase.memory.web.models import MemoryWeb


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _strand(keyword: str, body: str, *, aliases: str = "", extra: str = "") -> str:
    aliases_line = f"aliases: [{aliases}]\n" if aliases else ""
    return f"---\nkeyword: {keyword}\n{aliases_line}{extra}---\n\n{body}"


def _build_web(tmp_path: Path, strands: dict[str, str]) -> MemoryWeb:
    memory = tmp_path / "sase" / "memory"
    _write(
        memory / "glossary.md",
        "---\nweb: true\nroster: inline\n---\n\nGlossary descriptor.\n",
    )
    for slug, content in strands.items():
        _write(memory / "glossary" / f"{slug}.md", content)
    (web,) = discover_memory_webs(tmp_path).webs
    return web


def _links(
    web: MemoryWeb,
) -> tuple[dict[int, tuple[GlossaryDefinitionLink, ...]], GlossaryCatalog]:
    catalog = build_glossary_catalog(memory_web_glossary_entries(web))
    links = glossary_definition_links(web, ordered_web_strands(web), catalog.entries)
    return links, catalog


def _index(catalog: GlossaryCatalog, term: str) -> int:
    return next(entry.index for entry in catalog.entries if entry.term == term)


def _slice(entry_definition: str, link: GlossaryDefinitionLink) -> str:
    text = entry_definition.strip().encode("utf-8")
    return text[link.byte_start : link.byte_end].decode("utf-8")


def test_links_resolve_slug_web_forms_keyword_and_alias(tmp_path: Path) -> None:
    web = _build_web(
        tmp_path,
        {
            "alpha": _strand(
                "Alpha Term",
                "[[beta-term]] [[glossary:beta-term]] [[glossary/beta-term]] "
                "[[Gamma Ray]] [[gr]]\n",
            ),
            "beta-term": _strand("Beta Term", "Beta.\n"),
            "gamma-ray": _strand("Gamma Ray", "Gamma.\n", aliases="gr"),
        },
    )

    links, catalog = _links(web)

    alpha = _index(catalog, "Alpha Term")
    beta = _index(catalog, "Beta Term")
    gamma = _index(catalog, "Gamma Ray")
    assert [link.target_index for link in links[alpha]] == [
        beta,
        beta,
        beta,
        gamma,
        gamma,
    ]
    assert [link.target for link in links[alpha]] == [
        "beta-term",
        "glossary:beta-term",
        "glossary/beta-term",
        "Gamma Ray",
        "gr",
    ]
    assert set(links) == {alpha}


def test_foreign_flat_note_and_unknown_targets_have_no_index(tmp_path: Path) -> None:
    web = _build_web(
        tmp_path,
        {
            "alpha": _strand(
                "Alpha Term",
                "[[decisions/goal-ledger]] [[foo.md]] [[nope]] [[other:thing]]\n",
            ),
            "foo": _strand("Foo", "A strand whose slug matches the note stem.\n"),
        },
    )

    links, catalog = _links(web)

    alpha = _index(catalog, "Alpha Term")
    assert [link.target_index for link in links[alpha]] == [None, None, None, None]
    assert [link.target for link in links[alpha]] == [
        "decisions/goal-ledger",
        "foo.md",
        "nope",
        "other:thing",
    ]


def test_self_link_keeps_its_own_index(tmp_path: Path) -> None:
    web = _build_web(
        tmp_path,
        {"alpha": _strand("Alpha Term", "I am [[alpha]] and [[glossary:alpha]].\n")},
    )

    links, catalog = _links(web)

    alpha = _index(catalog, "Alpha Term")
    assert [link.target_index for link in links[alpha]] == [alpha, alpha]


def test_links_inside_code_are_ignored(tmp_path: Path) -> None:
    web = _build_web(
        tmp_path,
        {
            "alpha": _strand(
                "Alpha Term",
                "Live [[beta-term]] but `[[beta-term]]` and\n```\n[[beta-term]]\n```\n",
            ),
            "beta-term": _strand("Beta Term", "Beta.\n"),
        },
    )

    links, catalog = _links(web)

    alpha = _index(catalog, "Alpha Term")
    assert [link.raw for link in links[alpha]] == ["[[beta-term]]"]


def test_strand_with_link_reference_none_yields_nothing(tmp_path: Path) -> None:
    web = _build_web(
        tmp_path,
        {
            "alpha": _strand(
                "Alpha Term", "[[beta-term]]\n", extra="link_reference: none\n"
            ),
            "beta-term": _strand("Beta Term", "Beta.\n"),
        },
    )

    links, _ = _links(web)

    assert links == {}


def test_byte_offsets_survive_non_ascii_text_and_stripped_whitespace(
    tmp_path: Path,
) -> None:
    body = "\n   Goal ⌖ links to [[beta-term]] and ✓ [[glossary:gamma-ray]].\n\n"
    web = _build_web(
        tmp_path,
        {
            "alpha": _strand("Alpha Term", body),
            "beta-term": _strand("Beta Term", "Beta.\n"),
            "gamma-ray": _strand("Gamma Ray", "Gamma.\n"),
        },
    )

    links, catalog = _links(web)

    alpha_entry = next(e for e in catalog.entries if e.term == "Alpha Term")
    records = links[alpha_entry.index]
    assert [_slice(alpha_entry.definition, link) for link in records] == [
        "[[beta-term]]",
        "[[glossary:gamma-ray]]",
    ]
    assert [link.raw for link in records] == [
        "[[beta-term]]",
        "[[glossary:gamma-ray]]",
    ]


def test_repeated_link_yields_one_record_per_occurrence(tmp_path: Path) -> None:
    web = _build_web(
        tmp_path,
        {
            "alpha": _strand(
                "Alpha Term", "[[beta-term]] then ![[beta-term]] and [[beta-term]]\n"
            ),
            "beta-term": _strand("Beta Term", "Beta.\n"),
        },
    )

    links, catalog = _links(web)

    alpha_entry = next(e for e in catalog.entries if e.term == "Alpha Term")
    records = links[alpha_entry.index]
    assert [link.raw for link in records] == [
        "[[beta-term]]",
        "![[beta-term]]",
        "[[beta-term]]",
    ]
    assert len({link.byte_start for link in records}) == 3
