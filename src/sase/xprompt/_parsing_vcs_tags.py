"""VCS workflow tag parsing and segment normalization for xprompts."""

from __future__ import annotations

import re

from ._parsing_vcs_refs import (
    extract_known_project_vcs_ref,
    normalize_vcs_underscore_refs,
)

DEFAULT_VCS_WORKFLOW_PREFIX = "#git:home"

_VCS_TAG_PATTERN: re.Pattern[str] | None = None
_VCS_TAG_EMBEDDED_PATTERN: re.Pattern[str] | None = None
_VCS_REPLACE_PATTERN: re.Pattern[str] | None = None
# Keep parenthesized directive arguments together even when they contain spaces.
# This matcher is intentionally limited to the leading launch-directive prefix;
# the directive parser still owns full syntax validation.
_DIRECTIVE_PREFIX_RE = re.compile(r"(%[^\s(]+(?:\((?:[^()]|\([^()]*\))*\))?[\s]+)+")
_SEGMENT_SEPARATOR_RE = re.compile(r"^---\s*$", re.MULTILINE)


def _get_vcs_tag_pattern() -> re.Pattern[str]:
    """Lazily initialize and return the VCS tag pattern."""
    global _VCS_TAG_PATTERN  # noqa: PLW0603
    if _VCS_TAG_PATTERN is None:
        from sase.workspace_provider import get_vcs_tag_pattern

        _VCS_TAG_PATTERN = get_vcs_tag_pattern()
    return _VCS_TAG_PATTERN


def _get_embedded_vcs_tag_pattern() -> re.Pattern[str]:
    """Lazily initialize and return the embedded VCS tag pattern."""
    global _VCS_TAG_EMBEDDED_PATTERN  # noqa: PLW0603
    if _VCS_TAG_EMBEDDED_PATTERN is None:
        from sase.workspace_provider import get_embedded_vcs_tag_pattern

        _VCS_TAG_EMBEDDED_PATTERN = get_embedded_vcs_tag_pattern()
    return _VCS_TAG_EMBEDDED_PATTERN


def extract_vcs_workflow_tag(prompt: str) -> str | None:
    """Extract a leading VCS workflow tag from a prompt string.

    Skips leading ``%directive`` tokens before checking for a VCS tag.
    Handles directives on the same line as the VCS tag (e.g. from
    Telegram-originated prompts like ``%i:a #gh_sase Fix the bug``).
    Returns the matched tag (e.g., ``"#gh:sase "``) or ``None``.
    """
    m = _DIRECTIVE_PREFIX_RE.match(prompt)
    stripped = prompt[m.end() :] if m else prompt

    match = _get_vcs_tag_pattern().match(stripped)
    if match:
        return match.group(0)
    return None


def find_vcs_workflow_tag(prompt: str) -> str | None:
    """Find the first VCS workflow tag anywhere in *prompt*.

    Unlike :func:`extract_vcs_workflow_tag`, the tag does NOT need to be at
    the start of the prompt. It may appear on a later line or after some text
    on the first line, as long as it is preceded by a token boundary.
    """
    match = _get_embedded_vcs_tag_pattern().search(prompt)
    if match:
        return match.group(0)
    return None


def find_vcs_workflow_tag_span(prompt: str) -> tuple[int, int] | None:
    """Return the span of the first VCS workflow tag in *prompt*.

    The embedded VCS tag pattern requires trailing whitespace, so matching is
    done against a sentinel-space suffix. The returned span excludes that
    trailing whitespace, preserving spaces and newlines around the tag.
    Tags inside fenced/inline code or disabled regions are inert content,
    not workflow refs, and are skipped.
    """
    from sase.xprompt._literal_zones import literal_zone_ranges

    literal = literal_zone_ranges(prompt)
    for match in _get_embedded_vcs_tag_pattern().finditer(f"{prompt} "):
        start = match.start()
        if any(zone_start <= start < zone_end for zone_start, zone_end in literal):
            continue
        return start, match.end() - 1
    return None


def _prompt_segment_has_vcs_workflow_ref(segment: str) -> bool:
    """Return whether *segment* contains any registered workspace workflow ref."""
    from sase.workspace_provider import get_ref_patterns

    if "#" not in segment:
        return False

    normalized = normalize_vcs_underscore_refs(segment)
    return any(
        pattern.search(normalized) is not None
        for pattern in get_ref_patterns().values()
    )


def normalize_default_vcs_workflow_segment(
    segment: str,
    *,
    default_vcs_prefix: str = DEFAULT_VCS_WORKFLOW_PREFIX,
) -> str:
    """Prefix *segment* with the default workspace workflow when none is present.

    Leading whitespace and leading ``%directive`` tokens remain before the
    inserted workflow tag so existing directive parsing keeps working.
    """
    from sase.workspace_provider import get_ref_patterns

    default_workflow_match = re.match(r"#([a-zA-Z_][a-zA-Z0-9_]*)", default_vcs_prefix)
    if default_workflow_match is None:
        return segment

    if default_workflow_match.group(1) not in get_ref_patterns():
        return segment

    if (
        not segment.strip()
        or _prompt_segment_has_vcs_workflow_ref(segment)
        or extract_known_project_vcs_ref(segment) is not None
    ):
        return segment

    leading_ws_match = re.match(r"\s*", segment)
    assert leading_ws_match is not None
    leading_ws = leading_ws_match.group(0)
    body = segment[leading_ws_match.end() :]

    directive_match = _DIRECTIVE_PREFIX_RE.match(body)
    if directive_match is None:
        return f"{leading_ws}{default_vcs_prefix} {body}"

    directive_prefix = directive_match.group(0)
    remainder = body[directive_match.end() :]
    return f"{leading_ws}{directive_prefix}{default_vcs_prefix} {remainder}"


def _inherit_vcs_workflow_tag_segment(segment: str, inherited_vcs_tag: str) -> str:
    """Prefix *segment* with *inherited_vcs_tag* when it has no workspace ref."""
    if (
        not segment.strip()
        or _prompt_segment_has_vcs_workflow_ref(segment)
        or extract_known_project_vcs_ref(segment) is not None
    ):
        return segment

    leading_ws_match = re.match(r"\s*", segment)
    assert leading_ws_match is not None
    leading_ws = leading_ws_match.group(0)
    body = segment[leading_ws_match.end() :]

    tag = inherited_vcs_tag.strip()
    directive_match = _DIRECTIVE_PREFIX_RE.match(body)
    if directive_match is None:
        return f"{leading_ws}{tag} {body}"

    directive_prefix = directive_match.group(0)
    remainder = body[directive_match.end() :]
    return f"{leading_ws}{directive_prefix}{tag} {remainder}"


def inherit_vcs_workflow_tag(prompt: str, inherited_vcs_tag: str | None) -> str:
    """Apply an inherited workspace workflow tag to each untagged prompt segment."""
    if not inherited_vcs_tag or not inherited_vcs_tag.strip():
        return prompt

    from sase.xprompt._fenced_blocks import (
        protect_fenced_blocks,
        unprotect_fenced_blocks,
    )

    frontmatter, body = _split_frontmatter_block(prompt)
    fenced_blocks: list[str] = []
    protected = protect_fenced_blocks(body, fenced_blocks)
    pieces = _SEGMENT_SEPARATOR_RE.split(protected)
    separators = _SEGMENT_SEPARATOR_RE.findall(protected)

    normalized_pieces: list[str] = []
    for piece in pieces:
        restored = unprotect_fenced_blocks(piece, fenced_blocks)
        normalized_pieces.append(
            _inherit_vcs_workflow_tag_segment(restored, inherited_vcs_tag)
        )

    rebuilt = normalized_pieces[0] if normalized_pieces else ""
    for sep, piece in zip(separators, normalized_pieces[1:], strict=False):
        rebuilt = f"{rebuilt}{sep}{piece}"
    return f"{frontmatter}{rebuilt}"


def _split_frontmatter_block(prompt: str) -> tuple[str, str]:
    """Split raw leading YAML frontmatter from *prompt*, preserving text."""
    lines = prompt.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return "", prompt

    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return "".join(lines[: i + 1]), "".join(lines[i + 1 :])

    return "", prompt


def find_vcs_workflow_tag_prepend_offset(prompt: str) -> int:
    """Return where a leading VCS workflow tag should be inserted.

    The insertion point follows the same placement rules as VCS workflow
    normalization: after a leading YAML frontmatter block, leading horizontal
    whitespace, and leading ``%directive`` tokens.
    """
    frontmatter, body = _split_frontmatter_block(prompt)
    offset = len(frontmatter)

    leading_ws_match = re.match(r"[^\S\r\n]*", body)
    assert leading_ws_match is not None
    offset += leading_ws_match.end()
    body_after_ws = body[leading_ws_match.end() :]

    directive_match = _DIRECTIVE_PREFIX_RE.match(body_after_ws)
    if directive_match is not None:
        offset += directive_match.end()

    return offset


def normalize_default_vcs_workflow(prompt: str) -> str:
    """Normalize bare prompt segments to the default workspace workflow.

    The transformation is applied per multi-prompt segment while preserving a
    leading frontmatter block and ``---`` separators. Segments that already
    contain any registered workspace workflow ref are left unchanged.
    """
    from sase.xprompt._fenced_blocks import (
        protect_fenced_blocks,
        unprotect_fenced_blocks,
    )

    frontmatter, body = _split_frontmatter_block(prompt)
    fenced_blocks: list[str] = []
    protected = protect_fenced_blocks(body, fenced_blocks)
    pieces = _SEGMENT_SEPARATOR_RE.split(protected)
    separators = _SEGMENT_SEPARATOR_RE.findall(protected)

    normalized_pieces: list[str] = []
    for piece in pieces:
        restored = unprotect_fenced_blocks(piece, fenced_blocks)
        normalized_pieces.append(normalize_default_vcs_workflow_segment(restored))

    rebuilt = normalized_pieces[0] if normalized_pieces else ""
    for sep, piece in zip(separators, normalized_pieces[1:], strict=False):
        rebuilt = f"{rebuilt}{sep}{piece}"
    return f"{frontmatter}{rebuilt}"


def strip_vcs_workflow_tag(prompt: str) -> str:
    """Strip a leading VCS workflow tag from a prompt string.

    Removes prefixes like ``#gh:sase``, ``#git(repo)``, and plugin-provided refs.
    so the prompt can be re-wrapped with a different VCS workflow.
    """
    return _get_vcs_tag_pattern().sub("", prompt)


def _get_vcs_replace_pattern() -> re.Pattern[str]:
    """Build a regex matching VCS workflow tags at the start of any line.

    Unlike :func:`_get_vcs_tag_pattern` (which is ``^``-anchored and matches
    only at the very start of the string), this pattern uses ``re.MULTILINE``
    so ``^`` matches at every line start. Leading ``%directive`` tokens are
    captured in group 1 to be preserved during replacement.
    """
    global _VCS_REPLACE_PATTERN  # noqa: PLW0603
    if _VCS_REPLACE_PATTERN is None:
        from sase.workspace_provider import get_workflow_names

        names = "|".join(re.escape(n) for n in sorted(get_workflow_names()))
        # The boundary after a tag is whitespace OR end-of-input. ``\s`` is tried
        # first, so any actual whitespace (including a newline) is consumed and
        # replaced exactly as before; ``$`` only wins at true EOF, letting a
        # line-start tag with no trailing whitespace (e.g. ``#gh:sase`` alone)
        # still be replaced rather than treated as absent.
        _VCS_REPLACE_PATTERN = re.compile(
            rf"^((?:%\S+[\s]+)*)#(?:{names})(?:!!|\?\?)?(?:\([^)]*\)|\+|[_:][^\s]*|)(?:\s|$)",
            re.MULTILINE,
        )
    return _VCS_REPLACE_PATTERN


def replace_vcs_workflow_tags(prompt: str, new_vcs_prefix: str) -> str:
    """Replace all VCS workflow tags in *prompt* with *new_vcs_prefix*.

    Handles multi-prompt segments (``---`` separated), directives before VCS
    tags, and VCS tags that appear at the start of any line. If no VCS tags
    are found, prepends *new_vcs_prefix* to the prompt.
    """
    pattern = _get_vcs_replace_pattern()
    result, count = pattern.subn(lambda m: f"{m.group(1)}{new_vcs_prefix} ", prompt)
    if count == 0:
        return f"{new_vcs_prefix} {prompt}"
    return result


def replace_ref_in_vcs_tag(tag: str, new_ref: str) -> str:
    """Replace the ref portion of a VCS workflow tag with *new_ref*.

    Strips HITL suffixes (``!!`` / ``??``) since this is used for resume
    scenarios where HITL overrides should not carry over.
    """
    stripped = tag.rstrip()
    if not stripped.startswith("#"):
        return tag

    body = stripped[1:]

    for suffix in ("!!", "??"):
        idx = body.find(suffix)
        if idx != -1:
            body = body[:idx] + body[idx + len(suffix) :]
            break

    if "(" in body:
        paren_start = body.index("(")
        return f"#{body[:paren_start]}({new_ref}) "

    if ":" in body:
        prefix = body.split(":", 1)[0]
        return f"#{prefix}:{new_ref} "

    if "_" in body:
        prefix = body.split("_", 1)[0]
        return f"#{prefix}:{new_ref} "

    return f"#{body}:{new_ref} "


def extract_project_from_vcs_tag(tag: str) -> str | None:
    """Extract the project/ref name from a VCS workflow tag.

    Handles formats like ``#gh:sase ``, ``#gh!!:sase ``, ``#git(repo) ``.
    Returns the ref portion (e.g. ``"sase"``, ``"repo"``) or ``None`` if
    no ref is present.
    """
    tag = tag.strip()
    if not tag.startswith("#"):
        return None

    body = tag[1:]

    for suffix in ("!!", "??"):
        idx = body.find(suffix)
        if idx != -1:
            body = body[:idx] + body[idx + len(suffix) :]
            break

    if "(" in body:
        start = body.index("(")
        end = body.find(")", start)
        if end != -1:
            return body[start + 1 : end] or None
        return None

    if ":" in body:
        ref = body.split(":", 1)[1]
        return ref or None

    return None


__all__ = [
    "DEFAULT_VCS_WORKFLOW_PREFIX",
    "extract_project_from_vcs_tag",
    "extract_vcs_workflow_tag",
    "find_vcs_workflow_tag",
    "find_vcs_workflow_tag_prepend_offset",
    "find_vcs_workflow_tag_span",
    "inherit_vcs_workflow_tag",
    "normalize_default_vcs_workflow",
    "normalize_default_vcs_workflow_segment",
    "replace_ref_in_vcs_tag",
    "replace_vcs_workflow_tags",
    "strip_vcs_workflow_tag",
]
