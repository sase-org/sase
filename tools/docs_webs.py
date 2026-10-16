"""Load SASE memory webs (glossary, decisions) for generated docs sources.

Phase sase-1le.8 (glossary) owns this module. ``tools/render_glossary`` and
``tools/render_design_decisions`` share it: strand parsing, first-sentence
one-liners, and the agent-internal ``[[...]]`` cross-reference rewrite.

Link syntax follows the memory-links convention (``web:keyword``,
``web/slug``, a bare token resolved against the source's own web). Like the
memory layer, references inside fenced or inline code are never rewritten.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml  # type: ignore[import-untyped]


REPO_ROOT = Path(__file__).resolve().parents[1]
GLOSSARY_DIR = REPO_ROOT / "sase" / "memory" / "glossary"
DECISIONS_DIR = REPO_ROOT / "sase" / "memory" / "decisions"

FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n?", re.DOTALL)
REF_RE = re.compile(r"(!?)\[\[([^\[\]|]+?)(?:\|([^\[\]]+?))?\]\]")
FENCE_RE = re.compile(r"^(```|~~~)")
INLINE_CODE_RE = re.compile(r"`[^`\n]+`")
ABBREVIATIONS = ("e.g.", "i.e.", "etc.", "vs.", "ex.")


@dataclass(frozen=True)
class Strand:
    """One memory-web strand with its docs-rendering metadata."""

    slug: str
    keyword: str
    aliases: tuple[str, ...] = ()
    summary: str = ""
    status: str = ""
    decided: str = ""
    superseded_by: tuple[str, ...] = ()
    body: str = ""


def _frontmatter(text: str) -> tuple[dict[str, object], str]:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    try:
        loaded = yaml.safe_load(match.group(1)) or {}
    except Exception:
        return {}, text[match.end() :]
    if not isinstance(loaded, dict):
        return {}, text[match.end() :]
    return loaded, text[match.end() :]


def _string_list(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value.strip() else ()
    if isinstance(value, (list, tuple)):
        return tuple(item for item in value if isinstance(item, str) and item.strip())
    return ()


def load_strands(directory: Path) -> list[Strand]:
    """Load every ``*.md`` strand in ``directory``, sorted by keyword."""
    strands: list[Strand] = []
    for path in sorted(directory.glob("*.md")):
        head, body = _frontmatter(path.read_text(encoding="utf-8"))
        keyword = head.get("keyword")
        if not isinstance(keyword, str) or not keyword.strip():
            keyword = path.stem.replace("-", " ").title()
        else:
            keyword = keyword.strip()
        metadata = head.get("metadata")
        status = ""
        decided = ""
        superseded_by: tuple[str, ...] = ()
        if isinstance(metadata, dict):
            raw_status = metadata.get("status")
            if isinstance(raw_status, str):
                status = raw_status.strip()
            raw_decided = metadata.get("decided")
            if isinstance(raw_decided, (str, int, datetime.date, datetime.datetime)):
                decided = str(raw_decided).strip()
            superseded_by = _string_list(metadata.get("superseded_by"))
        summary = head.get("summary")
        strands.append(
            Strand(
                slug=path.stem,
                keyword=keyword,
                aliases=_string_list(head.get("aliases")),
                summary=summary.strip() if isinstance(summary, str) else "",
                status=status,
                decided=decided,
                superseded_by=superseded_by,
                body=body.strip() + "\n",
            )
        )
    strands.sort(key=lambda strand: (strand.keyword.lower(), strand.slug))
    return strands


def strip_markdown_inline(text: str) -> str:
    """Reduce one inline Markdown span to plain words for one-line definitions."""

    def _code(match: re.Match[str]) -> str:
        return match.group(0).strip("`")

    text = INLINE_CODE_RE.sub(_code, text)
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = REF_RE.sub(lambda match: match.group(3) or match.group(2), text)
    text = re.sub(r"<[^>]*>", "", text)
    text = re.sub(r"(\*\*|__)(.*?)\1", r"\2", text)
    text = re.sub(r"(\*|_)(.*?)\1", r"\2", text)
    return " ".join(text.split())


def first_sentence(body: str) -> str:
    """Return the first paragraph's first sentence as a one-line definition."""
    paragraph = ""
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            if paragraph:
                break
            continue
        if stripped.startswith(("#", ">", "|", "-", "*", "<!--")):
            if paragraph:
                break
            continue
        paragraph += (" " if paragraph else "") + stripped
    paragraph = strip_markdown_inline(paragraph)
    guarded = paragraph
    for index, abbreviation in enumerate(ABBREVIATIONS):
        guarded = guarded.replace(abbreviation, f"\x00{index}\x00")
    match = re.search(r"[.!?](?:\s|$)", guarded)
    sentence = guarded[: match.end()].strip() if match else guarded.strip()
    for index, abbreviation in enumerate(ABBREVIATIONS):
        sentence = sentence.replace(f"\x00{index}\x00", abbreviation)
    return sentence


def _resolve(
    target: str,
    glossary: dict[str, Strand],
    decisions: dict[str, Strand],
) -> tuple[str, str] | None:
    """Map a ``[[...]]`` target to (web, slug); None means leave it literal."""
    target = target.strip()
    for prefix in ("glossary:", "glossary/"):
        if target.startswith(prefix):
            slug = target[len(prefix) :].strip()
            return ("glossary", slug) if slug in glossary else None
    for prefix in ("decisions:", "decisions/"):
        if target.startswith(prefix):
            slug = target[len(prefix) :].strip()
            return ("decisions", slug) if slug in decisions else None
    if target in glossary:
        return ("glossary", target)
    if target in decisions:
        return ("decisions", target)
    return None


def rewrite_refs(
    text: str,
    *,
    page: str,
    glossary: dict[str, Strand],
    decisions: dict[str, Strand],
) -> str:
    """Rewrite memory-web ``[[...]]`` refs as plain Markdown links.

    ``page`` is ``"glossary"`` (rendering ``glossary.md``) or
    ``"design-decisions"`` (rendering ``design-decisions.md``); same-page
    targets become ``#slug`` anchors and cross-page targets become relative
    ``.md`` links that MkDocs validates. References inside fenced or inline
    code are never scanned.
    """

    def _replace(match: re.Match[str]) -> str:
        resolved = _resolve(match.group(2), glossary, decisions)
        if resolved is None:
            return match.group(0)
        web, slug = resolved
        strand = (glossary if web == "glossary" else decisions)[slug]
        label = match.group(3) or strand.keyword
        if (page == "glossary" and web == "glossary") or (
            page == "design-decisions" and web == "decisions"
        ):
            destination = f"#{slug}"
        elif web == "glossary":
            destination = f"glossary.md#{slug}"
        else:
            destination = f"design-decisions.md#{slug}"
        return f"[{label}]({destination})"

    lines = text.splitlines(keepends=True)
    in_fence = False
    for index, line in enumerate(lines):
        if FENCE_RE.match(line.lstrip()):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        segments = re.split(r"(`[^`\n]+`)", line)
        for position in range(0, len(segments), 2):
            segments[position] = REF_RE.sub(_replace, segments[position])
        lines[index] = "".join(segments)
    return "".join(lines)


def github_url(web: str, slug: str) -> str:
    """Return the GitHub source URL for one memory-web strand."""
    return (
        "https://github.com/sase-org/sase/blob/master/sase/memory/"
        f"{web}/{slug}.md"
    )


@dataclass
class Webs:
    """Both memory webs, keyed by slug for cross-reference resolution."""

    glossary: dict[str, Strand] = field(default_factory=dict)
    decisions: dict[str, Strand] = field(default_factory=dict)

    @classmethod
    def load(
        cls,
        glossary_dir: Path = GLOSSARY_DIR,
        decisions_dir: Path = DECISIONS_DIR,
    ) -> "Webs":
        glossary = {strand.slug: strand for strand in load_strands(glossary_dir)}
        decisions = {strand.slug: strand for strand in load_strands(decisions_dir)}
        return cls(glossary=glossary, decisions=decisions)
