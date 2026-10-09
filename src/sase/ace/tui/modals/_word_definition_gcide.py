"""GCIDE (Webster's 1913) markup normalization and body parsing.

Pure helpers split out from :mod:`word_definition_card` so every file stays
well under the ``toobig`` 700-line threshold. All parsing here is total and
lossless: unknown markup survives verbatim and unparseable structure falls
back to cleaned verbatim blocks.
"""

from __future__ import annotations

import re
import textwrap
import unicodedata
from dataclasses import dataclass, field

_ACUTE = {
    "a": "á",
    "e": "é",
    "i": "í",
    "o": "ó",
    "u": "ú",
    "y": "ý",
    "A": "Á",
    "E": "É",
    "I": "Í",
    "O": "Ó",
    "U": "Ú",
    "Y": "Ý",
}
_GRAVE = {
    "a": "à",
    "e": "è",
    "i": "ì",
    "o": "ò",
    "u": "ù",
    "A": "À",
    "E": "È",
    "I": "Ì",
    "O": "Ò",
    "U": "Ù",
}
_DIAERESIS = {
    "a": "ä",
    "e": "ë",
    "i": "ï",
    "o": "ö",
    "u": "ü",
    "y": "ÿ",
    "A": "Ä",
    "E": "Ë",
    "I": "Ï",
    "O": "Ö",
    "U": "Ü",
    "Y": "Ÿ",
}
_CIRCUMFLEX = {
    "a": "â",
    "e": "ê",
    "i": "î",
    "o": "ô",
    "u": "û",
    "A": "Â",
    "E": "Ê",
    "I": "Î",
    "O": "Ô",
    "U": "Û",
}
_TILDE = {"n": "ñ", "a": "ã", "o": "õ", "N": "Ñ", "A": "Ã", "O": "Õ"}
_CEDILLA = {"c": "ç", "C": "Ç"}
_LIGATURES = {"ae": "æ", "AE": "Æ", "oe": "œ", "OE": "Œ", "root": "√"}

_TOKEN_RE = re.compile(r"\[([^\[\]\r\n]+)\]")
_SENSE_RE = re.compile(r"^(\d+)\.\s")
_SUBSENSE_RE = re.compile(r"^\([a-z]\)\s")
_CITATION_RE = re.compile(r"^\[[^\[\]]+\]\s*$")
_BALANCED_PAREN_RE = re.compile(r"\((?:[^()]|\([^()]*\))*\)")
_BALANCED_BRACKET_RE = re.compile(r"\[(?:[^\[\]]|\[[^\[\]]*\])*\]")


def _replace_token(match: re.Match[str]) -> str:
    inner = match.group(1)
    if len(inner) == 2 and inner[0] == "'":
        mapped = _ACUTE.get(inner[1])
        if mapped is not None:
            return mapped
    elif len(inner) == 2 and inner[0] == "`":
        mapped = _GRAVE.get(inner[1])
        if mapped is not None:
            return mapped
    elif len(inner) == 2 and inner[0] == '"':
        mapped = _DIAERESIS.get(inner[1])
        if mapped is not None:
            return mapped
    elif len(inner) == 2 and inner[0] == "^":
        mapped = _CIRCUMFLEX.get(inner[1])
        if mapped is not None:
            return mapped
    elif len(inner) == 2 and inner[0] == "~":
        mapped = _TILDE.get(inner[1])
        if mapped is not None:
            return mapped
    elif len(inner) == 2 and inner[0] == ",":
        mapped = _CEDILLA.get(inner[1])
        if mapped is not None:
            return mapped
    elif inner in _LIGATURES:
        return _LIGATURES[inner]
    elif len(inner) == 2 and inner[0] == "=" and inner[1].isalpha():
        return unicodedata.normalize("NFC", inner[1] + "\u0304")
    elif len(inner) == 2 and inner[1] == "^" and inner[0].isalpha():
        return unicodedata.normalize("NFC", inner[0] + "\u0306")
    return match.group(0)


def normalize_gcide_markup(text: str) -> str:
    """Replace known GCIDE bracket markup, leaving unknown tokens verbatim."""
    return unicodedata.normalize("NFC", _TOKEN_RE.sub(_replace_token, text))


@dataclass
class GcideRawBlock:
    kind: str
    marker: str = ""
    label: str = ""
    text: str = ""


@dataclass
class GcideSense:
    marker: str
    gloss: str
    examples: tuple[str, ...] = ()


@dataclass
class GcideEntry:
    headword: str = ""
    syllables: str = ""
    pos: str = ""
    pos_display: str = ""
    meta: tuple[str, ...] = ()
    senses: tuple[GcideSense, ...] = ()
    blocks: tuple[GcideRawBlock, ...] = ()
    first_sense_gloss: str = ""
    first_sense_examples: tuple[str, ...] = ()


_POS_MAP = {
    "v. t.": "transitive verb",
    "v. i.": "intransitive verb",
    "v.": "verb",
    "n.": "noun",
    "n. pl.": "plural noun",
    "a.": "adjective",
    "adj.": "adjective",
    "adv.": "adverb",
    "p. a.": "participial adjective",
    "prep.": "preposition",
    "conj.": "conjunction",
    "interj.": "interjection",
    "pron.": "pronoun",
    "p. p.": "past participle",
    "p. pr.": "present participle",
}

_POS_TOKEN_RE = re.compile(r"^(?:[A-Za-z]{1,7}\.|&)\s*")


def _map_pos_display(abbrev: str) -> str:
    normalized = " ".join(abbrev.split())
    if normalized in _POS_MAP:
        return _POS_MAP[normalized]
    return abbrev


def _split_gcide_blocks(body: str) -> list[GcideRawBlock]:
    """Dedent *body* and split it into reflowed raw blocks."""
    dedented = textwrap.dedent(body)
    lines = dedented.splitlines()
    blocks: list[GcideRawBlock] = []
    current_lines: list[str] = []
    current_kind = "para"
    current_marker = ""
    current_label = ""
    current_start = 0
    last_start: int | None = None
    last_kind: str | None = None

    def flush() -> None:
        nonlocal current_lines, current_kind, current_marker, current_label
        nonlocal last_start, last_kind
        if not current_lines:
            return
        text = _reflow_lines(current_lines)
        if text:
            blocks.append(
                GcideRawBlock(
                    kind=current_kind,
                    marker=current_marker,
                    label=current_label,
                    text=text,
                )
            )
            last_start = current_start
            last_kind = current_kind
        current_lines = []
        current_kind = "para"
        current_marker = ""
        current_label = ""

    for raw in lines:
        stripped = raw.strip()
        if not stripped:
            flush()
            continue
        normalized_line = normalize_gcide_markup(raw)
        norm_stripped = normalized_line.strip()
        if _CITATION_RE.match(norm_stripped):
            flush()
            continue
        indent = len(raw) - len(raw.lstrip(" \t"))
        indent = indent + raw[:indent].count("\t") * 7
        kind, marker, label = _classify_gcide_line(norm_stripped)
        if not current_lines:
            # Fresh block: deeply indented non-starter lines after a
            # sense block are quotations, not new paragraphs.
            if kind == "para" and last_start is not None and indent - last_start >= 5:
                kind = "quote"
            current_kind, current_marker, current_label = kind, marker, label
            current_start = indent
            current_lines = [normalized_line]
            continue
        starts_new = kind in ("sense", "subsense", "labeled", "note")
        if kind == "phrase" and indent <= current_start:
            starts_new = True
        if starts_new:
            flush()
            current_kind, current_marker, current_label = kind, marker, label
            current_start = indent
            current_lines = [normalized_line]
            continue
        if indent - current_start >= 5:
            if current_kind == "quote":
                current_lines.append(normalized_line)
                continue
            flush()
            current_kind, current_marker, current_label = "quote", "", ""
            current_start = indent
            current_lines = [normalized_line]
            continue
        current_lines.append(normalized_line)
    flush()
    return blocks


def _classify_gcide_line(stripped: str) -> tuple[str, str, str]:
    sense = _SENSE_RE.match(stripped)
    if sense:
        return ("sense", sense.group(0).strip(), "")
    sub = _SUBSENSE_RE.match(stripped)
    if sub:
        return ("subsense", sub.group(0).strip(), "")
    if stripped.startswith("Syn:"):
        return ("labeled", "", "synonyms")
    if stripped.startswith("Note:"):
        return ("note", "", "Note")
    if stripped.startswith("{"):
        close = stripped.find("}")
        if 0 < close <= 60:
            return ("phrase", "", "")
    return ("para", "", "")


def _reflow_lines(lines: list[str]) -> str:
    return " ".join(" ".join(line.split()) for line in lines).strip()


def _extract_balanced(text: str, pos: int) -> tuple[str, int] | None:
    if pos >= len(text):
        return None
    opener, closer = text[pos], ")" if text[pos] == "(" else "]"
    if opener not in "([":
        return None
    depth = 0
    for end in range(pos, len(text)):
        if text[end] == opener:
            depth += 1
        elif text[end] == closer:
            depth -= 1
            if depth == 0:
                return (text[pos : end + 1], end + 1)
    return None


def _parse_gcide_header(first_block_text: str) -> dict[str, object]:
    """Parse the headword line of the first GCIDE block."""
    result: dict[str, object] = {
        "headword": "",
        "syllables": "",
        "pos": "",
        "pos_display": "",
        "meta": (),
        "rest": first_block_text,
    }
    text = first_block_text.strip()
    if not text:
        return result
    headword = ""
    syllables = ""
    rest = text
    backslash = text.find("\\")
    if backslash > 0:
        headword = text[:backslash].strip()
        closing = text.find("\\", backslash + 1)
        if closing > backslash:
            syllables = text[backslash + 1 : closing]
            rest = text[closing + 1 :].strip()
        else:
            rest = text[backslash + 1 :].strip()
    else:
        comma = text.find(",")
        if comma > 0:
            headword = text[:comma].strip()
            rest = text[comma:].strip()
        else:
            headword = text.split()[0] if text.split() else ""
            rest = text[len(headword) :].strip()
    # Optional balanced pronunciation.
    if rest.startswith("("):
        extracted = _extract_balanced(rest, 0)
        if extracted is not None:
            pronunciations: list[str] = [extracted[0]]
            rest = rest[extracted[1] :].strip()
        else:
            pronunciations = []
    else:
        pronunciations = []
    pos = ""
    if rest.startswith(","):
        rest = rest[1:].strip()
        pos_match = ""
        cursor = 0
        while cursor < len(rest):
            token = _POS_TOKEN_RE.match(rest[cursor:])
            if token is None:
                break
            pos_match += token.group(0)
            cursor += len(token.group(0))
        pos = pos_match.strip()
        rest = rest[cursor:].strip()
    metas: list[str] = list(pronunciations)
    while rest.startswith("["):
        extracted = _extract_balanced(rest, 0)
        if extracted is None:
            break
        metas.append(extracted[0])
        rest = rest[extracted[1] :].strip()
    result.update(
        {
            "headword": headword,
            "syllables": syllables,
            "pos": pos,
            "pos_display": _map_pos_display(pos) if pos else "",
            "meta": tuple(metas),
            "rest": rest,
        }
    )
    return result


def split_gloss_examples(sense_text: str) -> tuple[str, list[str]]:
    """Split GCIDE sense text into gloss and usage examples."""
    text = sense_text.strip()
    examples: list[str] = []
    gloss = text
    marker = "; as, "
    idx = text.find(marker)
    if idx >= 0:
        gloss = text[:idx].strip()
        examples = [part.strip(" ;") for part in text[idx + len(marker) :].split("; ")]
    elif text.startswith("as, "):
        gloss = ""
        examples = [part.strip(" ;") for part in text[len("as, ") :].split("; ")]
    examples = [example for example in examples if example]
    return gloss, examples


def split_quote_attribution(quote_text: str) -> tuple[str, str]:
    """Split a reflowed quotation into (quote, author) at the last ``--``."""
    idx = quote_text.rfind("--")
    if idx < 0:
        return quote_text.strip(), ""
    quote = quote_text[:idx].strip().strip('"').strip()
    author = quote_text[idx + 2 :].strip().strip(".")
    author = " ".join(author.split())
    if author.endswith("."):
        author = author[:-1]
    return quote, author


def parse_gcide_body(body: str) -> GcideEntry:
    """Parse one GCIDE section body into a structured entry."""
    blocks = _split_gcide_blocks(body)
    if not blocks:
        return GcideEntry(blocks=())
    header = _parse_gcide_header(blocks[0].text)
    headword = str(header["headword"])
    syllables = str(header["syllables"])
    pos = str(header["pos"])
    pos_display = str(header["pos_display"])
    meta_value = header["meta"]
    meta = (
        tuple(str(item) for item in meta_value) if isinstance(meta_value, tuple) else ()
    )
    rest = str(header["rest"])
    senses: list[GcideSense] = []
    structured: list[GcideRawBlock] = []
    if rest:
        gloss, examples = split_gloss_examples(rest)
        senses.append(GcideSense(marker="", gloss=gloss, examples=tuple(examples)))
        structured.append(GcideRawBlock(kind="sense", marker="", label="", text=rest))
    for block in blocks[1:]:
        if block.kind in ("sense", "subsense"):
            marker_match = re.match(r"^(\d+\.|\(.*?\))\s*", block.text)
            marker = marker_match.group(1) if marker_match else block.marker
            sense_text = block.text[len(marker) :].strip() if marker else block.text
            gloss, examples = split_gloss_examples(sense_text)
            senses.append(
                GcideSense(marker=marker, gloss=gloss, examples=tuple(examples))
            )
        structured.append(block)
    first_gloss = senses[0].gloss if senses else ""
    first_examples = senses[0].examples if senses else ()
    return GcideEntry(
        headword=headword,
        syllables=syllables,
        pos=pos,
        pos_display=pos_display,
        meta=meta,
        senses=tuple(senses),
        blocks=tuple(structured if structured else blocks),
        first_sense_gloss=first_gloss,
        first_sense_examples=first_examples,
    )


__all__ = [
    "GcideEntry",
    "GcideRawBlock",
    "GcideSense",
    "normalize_gcide_markup",
    "parse_gcide_body",
    "split_gloss_examples",
    "split_quote_attribution",
]
