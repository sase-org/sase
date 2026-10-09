"""Dictionary-card model: lead selection and card assembly.

Pure helpers with no Textual/Rich imports so the model stays unit-testable.
Per-database parsing lives in :mod:`_word_definition_parsers`; rendering in
:mod:`word_definition_render`.
"""

from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass

from sase.core.word_lookup import DefinitionSection

from ._word_definition_gcide import GcideEntry, GcideSense, parse_gcide_body
from ._word_definition_parsers import (
    DictBlock,
    WordNetSense,
    apply_headword_case,
    build_wordnet_sense,
    clean_gloss_text,
    convert_gcide_syllables,
    convert_syllables,
    finalize_gloss,
    gcide_pos_family,
    infer_database,
    parse_generic_body,
    parse_moby_body,
    parse_section_blocks,
    parse_wordnet_body,
    source_display_label,
    wordnet_pos_display,
    wordnet_pos_family,
)

_CITATION_LINE_RE = re.compile(r"^\[[^\[\]]+\]\s*$")


@dataclass(frozen=True)
class DictEntry:
    database: str
    label: str
    heading: str
    blocks: tuple[DictBlock, ...] = ()


@dataclass(frozen=True)
class LeadDefinition:
    headword: str
    pos_display: str
    syllables: str
    gloss: str
    examples: tuple[str, ...] = ()
    source_label: str = ""
    sense_total: int = 0


@dataclass(frozen=True)
class DefinitionCard:
    word: str
    headword: str
    pos_display: str = ""
    syllables: str = ""
    lead: LeadDefinition | None = None
    entries: tuple[DictEntry, ...] = ()
    show_looked_up: bool = False


def _first_gcide_entry(
    sections: tuple[DefinitionSection, ...], databases: tuple[str, ...]
) -> GcideEntry | None:
    for section, database in zip(sections, databases, strict=True):
        if database == "gcide":
            try:
                return parse_gcide_body(section.body)
            except Exception:
                continue
    return None


def _wordnet_senses(
    sections: tuple[DefinitionSection, ...], databases: tuple[str, ...]
) -> tuple[tuple[str, list[WordNetSense]], ...]:
    out: list[tuple[str, list[WordNetSense]]] = []
    for section, database in zip(sections, databases, strict=True):
        if database != "wn":
            continue
        try:
            headword, senses, _ = parse_wordnet_body(section.body)
        except Exception:
            continue
        if senses:
            out.append((headword, senses))
    return tuple(out)


def _gcide_syllables_for(
    shown_headword: str,
    sections: tuple[DefinitionSection, ...],
    databases: tuple[str, ...],
    looked_up: str,
) -> str:
    for section, database in zip(sections, databases, strict=True):
        if database != "gcide":
            continue
        try:
            entry = parse_gcide_body(section.body)
        except Exception:
            continue
        if not entry.headword or not entry.syllables:
            continue
        if entry.headword.casefold() != shown_headword.casefold():
            continue
        return convert_gcide_syllables(entry.headword, entry.syllables, looked_up)
    return ""


def _lead_from_wordnet(
    *,
    looked_up: str,
    wn_headword: str,
    wn_senses: list[WordNetSense],
    first_gcide: GcideEntry | None,
    databases: tuple[str, ...],
    sections: tuple[DefinitionSection, ...],
) -> LeadDefinition | None:
    if not wn_senses:
        return None
    picked = wn_senses[0]
    if first_gcide is not None:
        family = gcide_pos_family(getattr(first_gcide, "pos_display", "") or "")
        if family:
            for sense in wn_senses:
                if wordnet_pos_family(sense.pos) == family:
                    picked = sense
                    break
    headword = wn_headword or looked_up
    syllables = _gcide_syllables_for(headword, sections, databases, looked_up)
    return LeadDefinition(
        headword=headword,
        pos_display=wordnet_pos_display(picked.pos),
        syllables=syllables,
        gloss=finalize_gloss(picked.gloss or looked_up),
        examples=tuple(picked.examples[:2]),
        source_label="WordNet",
        sense_total=len(wn_senses),
    )


def _lead_from_gcide(
    *,
    looked_up: str,
    sections: tuple[DefinitionSection, ...],
    databases: tuple[str, ...],
) -> LeadDefinition | None:
    for section, database in zip(sections, databases, strict=True):
        if database != "gcide":
            continue
        try:
            entry = parse_gcide_body(section.body)
        except Exception:
            continue
        if not entry.senses:
            continue
        headword = apply_headword_case(entry.headword or looked_up, looked_up)
        syllables = ""
        if entry.syllables:
            syllables = convert_gcide_syllables(
                entry.headword, entry.syllables, looked_up
            )
        numbered = [
            sense for sense in entry.senses if re.match(r"^\d+\.$", sense.marker)
        ]
        total = len(numbered) if numbered else 1
        first: GcideSense = entry.senses[0]
        return LeadDefinition(
            headword=headword or looked_up,
            pos_display=entry.pos_display,
            syllables=syllables,
            gloss=finalize_gloss(first.gloss or looked_up),
            examples=tuple(first.examples[:2]),
            source_label="Webster's 1913",
            sense_total=total,
        )
    return None


def _lead_from_generic(
    *,
    looked_up: str,
    sections: tuple[DefinitionSection, ...],
    databases: tuple[str, ...],
) -> LeadDefinition | None:
    for section, database in zip(sections, databases, strict=True):
        if database in ("gcide", "wn", "moby-thesaurus"):
            continue
        if not section.body.strip():
            continue
        dedented = textwrap.dedent(section.body)
        lines = dedented.splitlines()
        # Skip a lone headword line.
        start = 0
        non_blank = [line for line in lines if line.strip()]
        if non_blank and len(non_blank[0].split()) <= 2:
            try:
                start = lines.index(non_blank[0]) + 1
            except ValueError:
                start = 0
        for line in lines[start:]:
            words = line.strip().split()
            if len(words) >= 6 and not _CITATION_LINE_RE.match(line.strip()):
                return LeadDefinition(
                    headword=looked_up,
                    pos_display="",
                    syllables="",
                    gloss=finalize_gloss(line.strip()),
                    examples=(),
                    source_label=source_display_label(database, section.source),
                    sense_total=0,
                )
    return None


def _select_lead(
    word: str, sections: tuple[DefinitionSection, ...]
) -> LeadDefinition | None:
    """Select the hero lead definition using the WordNet-first priority."""
    databases = tuple(infer_database(section) for section in sections)
    wn_groups = _wordnet_senses(sections, databases)
    first_gcide = _first_gcide_entry(sections, databases)
    if wn_groups:
        headword, senses = wn_groups[0]
        lead = _lead_from_wordnet(
            looked_up=word,
            wn_headword=headword,
            wn_senses=senses,
            first_gcide=first_gcide,
            databases=databases,
            sections=sections,
        )
        if lead is not None:
            return lead
    lead = _lead_from_gcide(looked_up=word, sections=sections, databases=databases)
    if lead is not None:
        return lead
    return _lead_from_generic(looked_up=word, sections=sections, databases=databases)


def build_definition_card(
    word: str, sections: tuple[DefinitionSection, ...]
) -> DefinitionCard:
    """Build a display card from raw DICT sections; never raises."""
    try:
        return _build_definition_card(word, sections)
    except Exception:
        return DefinitionCard(word=word, headword=word, entries=())


def _build_definition_card(
    word: str, sections: tuple[DefinitionSection, ...]
) -> DefinitionCard:
    databases = tuple(infer_database(section) for section in sections)
    try:
        lead = _select_lead(word, sections)
    except Exception:
        lead = None
    if lead is not None:
        headword = lead.headword
        pos_display = lead.pos_display
        syllables = lead.syllables
    else:
        # Fall back to the looked-up word when no lead prose exists.
        headword = word
        pos_display = ""
        syllables = ""
    entries: list[DictEntry] = []
    index = 0
    while index < len(sections):
        database = databases[index]
        group: list[DefinitionSection] = [sections[index]]
        cursor = index + 1
        while cursor < len(sections) and databases[cursor] == database:
            group.append(sections[cursor])
            cursor += 1
        label = source_display_label(database, group[0].source)
        blocks: list[DictBlock] = []
        moby_total = 0
        for section in group:
            try:
                parsed = parse_section_blocks(database, section.body)
            except Exception:
                parsed = ()
            blocks.extend(parsed)
            if database == "moby-thesaurus":
                try:
                    count, _ = parse_moby_body(section.body)
                except Exception:
                    count = 0
                moby_total += count
        if database == "moby-thesaurus":
            heading = f"MOBY THESAURUS · {moby_total} words"
        else:
            heading = label.upper()
        entries.append(
            DictEntry(
                database=database, label=label, heading=heading, blocks=tuple(blocks)
            )
        )
        index = cursor
    show_looked_up = headword.casefold() != word.casefold()
    return DefinitionCard(
        word=word,
        headword=headword,
        pos_display=pos_display,
        syllables=syllables,
        lead=lead,
        entries=tuple(entries),
        show_looked_up=show_looked_up,
    )


__all__ = [
    "DefinitionCard",
    "DictBlock",
    "DictEntry",
    "LeadDefinition",
    "WordNetSense",
    "apply_headword_case",
    "build_definition_card",
    "build_wordnet_sense",
    "clean_gloss_text",
    "convert_syllables",
    "finalize_gloss",
    "infer_database",
    "parse_generic_body",
    "parse_moby_body",
    "parse_section_blocks",
    "parse_wordnet_body",
    "source_display_label",
]
