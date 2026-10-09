"""Per-database DICT section parsers for the dictionary card.

Pure helpers split out from :mod:`word_definition_card` so every file stays
well under the ``toobig`` 700-line threshold.
"""

from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass

from sase.core.word_lookup import DefinitionSection

from ._word_definition_gcide import (
    GcideEntry,
    GcideRawBlock,
    normalize_gcide_markup,
    parse_gcide_body,
    split_gloss_examples,
    split_quote_attribution,
)

_SOURCE_LABELS = {
    "gcide": "Webster's 1913",
    "wn": "WordNet",
    "moby-thesaurus": "Moby Thesaurus",
    "foldoc": "FOLDOC",
    "jargon": "Jargon File",
    "devil": "Devil's Dictionary",
    "easton": "Easton's Bible Dictionary",
    "hitchcock": "Hitchcock's Bible Names",
    "bouvier": "Bouvier's Law Dictionary",
    "vera": "V.E.R.A.",
    "elements": "The Elements",
    "world02": "CIA World Factbook 2002",
}

_WORDNET_POS_DISPLAY = {"n": "noun", "v": "verb", "adj": "adjective", "adv": "adverb"}
_WORDNET_POS_FAMILY = {"n": "noun", "v": "verb", "adj": "adjective", "adv": "adverb"}

_SENSE_LINE_RE = re.compile(r"^(?:(adj|adv|n|v)\s+)?(?:(\d+)\s*)?:\s(.*)$")
_BRACKET_LIST_RE = re.compile(
    r"\[(syn|ant|also|see also)\s*:\s*([^\]]*)\]", re.IGNORECASE
)
_QUOTE_RE = re.compile(r'"([^"]+)"')
_MOBY_HEADER_RE = re.compile(r'^(\d+)\s+Moby Thesaurus words?\s+for\s+"(.+)":\s*$')


@dataclass(frozen=True)
class DictBlock:
    kind: str
    text: str = ""
    marker: str = ""
    label: str = ""
    author: str = ""
    items: tuple[str, ...] = ()
    indent: int = 0


@dataclass(frozen=True)
class WordNetSense:
    pos: str
    number: str
    gloss: str
    examples: tuple[str, ...] = ()
    synonyms: tuple[str, ...] = ()
    antonyms: tuple[str, ...] = ()
    also: tuple[str, ...] = ()
    see_also: tuple[str, ...] = ()


def infer_database(section: DefinitionSection) -> str:
    if section.database:
        return section.database.strip()
    source = section.source
    if source.startswith("The Collaborative International Dictionary"):
        return "gcide"
    if source.startswith("WordNet"):
        return "wn"
    if source.startswith("Moby Thesaurus"):
        return "moby-thesaurus"
    return ""


def source_display_label(database: str, source: str) -> str:
    if database in _SOURCE_LABELS:
        return _SOURCE_LABELS[database]
    return source


def wordnet_pos_display(pos: str) -> str:
    return _WORDNET_POS_DISPLAY.get(pos, pos)


def wordnet_pos_family(pos: str) -> str:
    return _WORDNET_POS_FAMILY.get(pos, "")


def gcide_pos_family(pos_display: str) -> str:
    lowered = pos_display.lower()
    if "noun" in lowered or "pronoun" in lowered:
        return "noun"
    if "verb" in lowered or "participle" in lowered:
        return "verb"
    if "adjective" in lowered:
        return "adjective"
    if "adverb" in lowered:
        return "adverb"
    return ""


def _strip_braces(text: str) -> str:
    return text.replace("{", "").replace("}", "")


def clean_gloss_text(text: str) -> str:
    cleaned = normalize_gcide_markup(text)
    cleaned = _strip_braces(cleaned)
    cleaned = cleaned.replace("--", "—")
    cleaned = " ".join(cleaned.split())
    return cleaned


def finalize_gloss(text: str, *, cap: int = 300) -> str:
    gloss = clean_gloss_text(text)
    if gloss and gloss[-1] not in ".!?;:":
        gloss += "."
    if len(gloss) > cap:
        cut = gloss[:cap].rsplit(" ", 1)
        gloss = (cut[0] if len(cut) == 2 else gloss[:cap]).rstrip(" ,;:") + "…"
    return gloss


def _is_title_case(word: str) -> bool:
    return len(word) >= 2 and word[0].isupper() and word[1:].islower()


def apply_headword_case(gcide_headword: str, looked_up: str) -> str:
    if _is_title_case(gcide_headword) and looked_up.islower():
        return gcide_headword.lower()
    return gcide_headword


def convert_syllables(raw: str) -> str:
    return raw.replace("*", "·").replace('"', "′").replace("`", "″")


def _has_syllable_marks(converted: str) -> bool:
    return any(mark in converted for mark in ("·", "′", "″"))


def convert_gcide_syllables(
    gcide_headword: str, raw_syllables: str, looked_up: str
) -> str:
    converted = convert_syllables(raw_syllables)
    if _is_title_case(gcide_headword) and looked_up.islower():
        converted = converted.lower()
    if not _has_syllable_marks(converted):
        return ""
    return converted


def parse_wordnet_body(body: str) -> tuple[str, list[WordNetSense], list[DictBlock]]:
    dedented = textwrap.dedent(body)
    lines = dedented.splitlines()
    headword = ""
    for line in lines:
        if line.strip():
            headword = line.strip()
            break
    senses: list[WordNetSense] = []
    blocks: list[DictBlock] = []
    current_pos = ""
    current_number = ""
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_lines, current_number
        if not current_lines:
            return
        raw = " ".join(" ".join(part.split()) for part in current_lines).strip()
        sense = build_wordnet_sense(
            headword=headword, pos=current_pos, number=current_number, raw=raw
        )
        senses.append(sense)
        blocks.append(
            DictBlock(
                kind="wn_sense",
                text=sense.gloss,
                marker=current_number,
                label=current_pos,
                items=sense.examples,
            )
        )
        current_lines = []

    def open_sense(match: re.Match[str]) -> None:
        nonlocal current_pos, current_number, current_lines
        flush()
        if match.group(1):
            current_pos = match.group(1)
            blocks.append(
                DictBlock(
                    kind="pos_heading",
                    text=wordnet_pos_display(current_pos),
                )
            )
        current_number = match.group(2) or ""
        current_lines = [match.group(3)]

    for line in lines[1:] if headword else lines:
        stripped = line.strip()
        if not stripped:
            continue
        match = _SENSE_LINE_RE.match(stripped)
        indent = len(line) - len(line.lstrip())
        if match and (indent <= 6 or not current_lines):
            open_sense(match)
        elif current_lines and (indent > 4 or not match):
            current_lines.append(stripped)
        elif match:
            open_sense(match)
        else:
            current_lines.append(stripped)
    flush()
    return headword, senses, blocks


def build_wordnet_sense(
    *, headword: str, pos: str, number: str, raw: str
) -> WordNetSense:
    synonyms: tuple[str, ...] = ()
    antonyms: tuple[str, ...] = ()
    also: tuple[str, ...] = ()
    see_also: tuple[str, ...] = ()

    def clean_items(content: str) -> tuple[str, ...]:
        items = tuple(
            _strip_braces(part).strip().strip(";") for part in content.split(",")
        )
        items = tuple(item for item in items if item)
        return tuple(item for item in items if item.casefold() != headword.casefold())

    def collect(match: re.Match[str]) -> None:
        nonlocal synonyms, antonyms, also, see_also
        label = match.group(1).lower()
        items = clean_items(match.group(2))
        if label == "syn":
            synonyms = items
        elif label == "ant":
            antonyms = items
        elif label == "also":
            also = items
        elif label == "see also":
            see_also = items

    for bracket in _BRACKET_LIST_RE.finditer(raw):
        collect(bracket)
    text = _BRACKET_LIST_RE.sub(" ", raw)
    text = " ".join(text.split())
    examples = tuple(match.group(1).strip() for match in _QUOTE_RE.finditer(text))
    examples = tuple(example for example in examples if example)
    first_quote = text.find('"')
    if first_quote < 0:
        gloss = text.strip().rstrip(";").strip()
    else:
        head = text[:first_quote].strip().rstrip(";").strip()
        rest = _QUOTE_RE.sub(" ", text[first_quote:])
        rest = " ".join(rest.split()).strip(" ;")
        gloss = f"{head} {rest}".strip() if rest else head
    gloss = _strip_braces(gloss)
    gloss = " ".join(gloss.split()).rstrip(";").strip()
    return WordNetSense(
        pos=pos,
        number=number,
        gloss=gloss,
        examples=examples,
        synonyms=synonyms,
        antonyms=antonyms,
        also=also,
        see_also=see_also,
    )


def parse_moby_body(body: str) -> tuple[int, tuple[str, ...]]:
    dedented = textwrap.dedent(body)
    count = 0
    content_lines: list[str] = []
    for line in dedented.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        header = _MOBY_HEADER_RE.match(stripped)
        if header and not content_lines and count == 0:
            count = int(header.group(1))
            continue
        content_lines.append(stripped)
    reflowed = " ".join(content_lines)
    items = tuple(item.strip() for item in reflowed.split(","))
    items = tuple(item for item in items if item)
    if count == 0:
        count = len(items)
    return count, items


def parse_generic_body(body: str) -> tuple[DictBlock, ...]:
    dedented = textwrap.dedent(body)
    paragraphs: list[str] = []
    current: list[str] = []
    for line in dedented.splitlines():
        if not line.strip():
            if current:
                paragraphs.append("\n".join(current).strip("\n"))
                current = []
            continue
        current.append(line.rstrip())
    if current:
        paragraphs.append("\n".join(current).strip("\n"))
    return tuple(
        DictBlock(kind="para", text=para) for para in paragraphs if para.strip()
    )


def _gcide_blocks_for_render(body: str) -> tuple[DictBlock, ...]:
    entry: GcideEntry = parse_gcide_body(body)
    raw_blocks: tuple[GcideRawBlock, ...] = entry.blocks
    out: list[DictBlock] = []
    header_line = ""
    if entry.headword:
        header_line = entry.headword
        if entry.pos_display:
            header_line += f"  {entry.pos_display}"
        if entry.syllables:
            header_line += f"  {convert_syllables(entry.syllables)}"
    if header_line:
        out.append(DictBlock(kind="entry", text=header_line))
    for meta in entry.meta:
        out.append(DictBlock(kind="meta", text=meta))
    for block in raw_blocks:
        if block.kind == "sense":
            sense_text = block.text
            marker = ""
            sense_match = re.match(r"^(\d+\.)\s*", sense_text)
            if sense_match:
                marker = sense_match.group(1)
                sense_text = sense_text[len(marker) :].strip()
            elif block.marker:
                marker = block.marker
            gloss, examples = split_gloss_examples(sense_text)
            out.append(
                DictBlock(
                    kind="sense", text=gloss, marker=marker, items=tuple(examples)
                )
            )
        elif block.kind == "subsense":
            sense_match = re.match(r"^(\(.*?\))\s*", block.text)
            marker = sense_match.group(1) if sense_match else block.marker
            sense_text = block.text[len(marker) :].strip() if marker else block.text
            gloss, examples = split_gloss_examples(sense_text)
            out.append(
                DictBlock(
                    kind="subsense", text=gloss, marker=marker, items=tuple(examples)
                )
            )
        elif block.kind == "labeled":
            items_text = block.text[len("Syn:") :].strip()
            out.append(DictBlock(kind="labeled", text=items_text, label="synonyms"))
        elif block.kind == "note":
            out.append(DictBlock(kind="labeled", text=block.text, label="Note"))
        elif block.kind == "quote":
            quote, author = split_quote_attribution(block.text)
            out.append(DictBlock(kind="quote", text=quote, author=author))
        elif block.kind == "phrase":
            out.append(DictBlock(kind="phrase", text=block.text))
        else:
            if block.text.strip():
                out.append(DictBlock(kind="para", text=block.text))
    return tuple(out)


def _wordnet_blocks_for_render(
    senses: list[WordNetSense], blocks: list[DictBlock]
) -> tuple[DictBlock, ...]:
    out: list[DictBlock] = []
    for block in blocks:
        if block.kind == "pos_heading":
            out.append(block)
            continue
        # Find the matching sense to expand labeled rows.
        match: WordNetSense | None = None
        for sense in senses:
            if sense.gloss == block.text and sense.number == block.marker:
                match = sense
                break
        out.append(
            DictBlock(
                kind="sense", text=block.text, marker=block.marker, items=block.items
            )
        )
        if match is not None:
            if match.synonyms:
                out.append(
                    DictBlock(
                        kind="labeled", text=", ".join(match.synonyms), label="synonyms"
                    )
                )
            if match.antonyms:
                out.append(
                    DictBlock(
                        kind="labeled", text=", ".join(match.antonyms), label="antonyms"
                    )
                )
            if match.also:
                out.append(
                    DictBlock(kind="labeled", text=", ".join(match.also), label="also")
                )
            if match.see_also:
                out.append(
                    DictBlock(
                        kind="labeled",
                        text=", ".join(match.see_also),
                        label="see also",
                    )
                )
    return tuple(out)


def _parse_section_blocks(database: str, body: str) -> tuple[DictBlock, ...]:
    if database == "gcide":
        blocks = _gcide_blocks_for_render(body)
        if blocks:
            return blocks
        raise ValueError("empty gcide parse")
    if database == "wn":
        headword, senses, raw_blocks = parse_wordnet_body(body)
        if senses or headword:
            return _wordnet_blocks_for_render(senses, raw_blocks)
        raise ValueError("empty wordnet parse")
    if database == "moby-thesaurus":
        _count, items = parse_moby_body(body)
        if items:
            return (DictBlock(kind="thesaurus", text="", items=items),)
        raise ValueError("empty moby parse")
    blocks = parse_generic_body(body)
    if blocks:
        return blocks
    if not body.strip():
        return ()
    raise ValueError("empty generic parse")


def parse_section_blocks(database: str, body: str) -> tuple[DictBlock, ...]:
    """Parse one section body, falling back to generic without losing text."""
    try:
        blocks = _parse_section_blocks(database, body)
    except Exception:
        blocks = ()
    if not blocks and body.strip():
        try:
            blocks = parse_generic_body(body)
        except Exception:
            blocks = ()
    if not blocks and body.strip():
        blocks = (DictBlock(kind="para", text=body.strip()),)
    return blocks


__all__ = [
    "DictBlock",
    "WordNetSense",
    "apply_headword_case",
    "build_wordnet_sense",
    "clean_gloss_text",
    "convert_gcide_syllables",
    "convert_syllables",
    "finalize_gloss",
    "gcide_pos_family",
    "infer_database",
    "parse_generic_body",
    "parse_moby_body",
    "parse_section_blocks",
    "parse_wordnet_body",
    "source_display_label",
    "wordnet_pos_display",
    "wordnet_pos_family",
]
