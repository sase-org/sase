"""Validated access to the docs page-move map."""

from __future__ import annotations

from dataclasses import dataclass
import posixpath
from pathlib import Path, PurePosixPath
import re
from urllib.parse import quote, unquote, urlsplit, urlunsplit

import yaml  # type: ignore[import-untyped]


REPO_ROOT = Path(__file__).resolve().parents[1]
MOVES_PATH = Path("docs/_meta/moves.yml")

INLINE_LINK_RE = re.compile(r"(?P<prefix>\]\()(?P<target><[^>]+>|[^)\s]+)")
REFERENCE_LINK_RE = re.compile(
    r"(?P<prefix>^\s*\[[^\]]+\]:\s*)(?P<target><[^>]+>|[^\s]+)", re.MULTILINE
)
HTML_LINK_RE = re.compile(
    r"(?P<prefix>\b(?:href|src)\s*=\s*)"
    r"(?:(?P<quote>[\"'])(?P<target>.*?)\2|(?P<unquoted>[^\s>]+))",
    re.IGNORECASE,
)
HTML_ID_RE = re.compile(r"\bid\s*=\s*([\"'])(.*?)\1", re.IGNORECASE)
GENERATED_BLOCK_RE = re.compile(
    r"<!--\s*BEGIN GENERATED\b.*?<!--\s*END GENERATED\b[^>]*-->",
    re.IGNORECASE | re.DOTALL,
)
GENERATED_FILE_RE = re.compile(r"generated,?\s+do not edit", re.IGNORECASE)
HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
EXPLICIT_ANCHOR_RE = re.compile(r"\s*\{\s*#([^}]+?)\s*\}\s*$")


@dataclass(frozen=True)
class PageMove:
    from_path: str
    to_path: str
    kind: str
    anchors: dict[str, str]
    title: str | None = None


def _doc_relative(value: object, *, field: str, source: Path) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(
            f"{source}: move {field} must be a non-empty docs-relative path"
        )
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.suffix.lower() != ".md":
        raise ValueError(f"{source}: move {field} must be a safe .md path: {value!r}")
    return path.as_posix()


def load_moves(root: Path = REPO_ROOT) -> list[PageMove]:
    """Load and validate docs/_meta/moves.yml."""
    source = root / MOVES_PATH
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("moves"), list):
        raise ValueError(f"{source} must contain a moves list")
    moves: list[PageMove] = []
    seen: set[str] = set()
    for index, item in enumerate(payload["moves"], 1):
        if not isinstance(item, dict):
            raise ValueError(f"{source}: moves[{index}] must be a mapping")
        from_path = _doc_relative(item.get("from"), field="from", source=source)
        to_path = _doc_relative(item.get("to"), field="to", source=source)
        kind = item.get("kind", "redirect")
        if kind not in {"redirect", "stub"}:
            raise ValueError(f"{source}: moves[{index}] kind must be redirect or stub")
        if from_path in seen:
            raise ValueError(f"{source}: duplicate move from {from_path}")
        seen.add(from_path)
        anchors_value = item.get("anchors", {})
        if not isinstance(anchors_value, dict):
            raise ValueError(f"{source}: moves[{index}] anchors must be a mapping")
        anchors: dict[str, str] = {}
        for old_anchor, target in anchors_value.items():
            if not isinstance(old_anchor, str) or not old_anchor:
                raise ValueError(f"{source}: moves[{index}] has an empty old anchor")
            if not isinstance(target, str) or not target:
                raise ValueError(
                    f"{source}: moves[{index}] anchor {old_anchor!r} has no target"
                )
            target_path, separator, target_anchor = target.partition("#")
            checked_path = _doc_relative(
                target_path, field=f"anchors.{old_anchor}", source=source
            )
            if separator and not target_anchor:
                raise ValueError(f"{source}: moves[{index}] anchor target is empty")
            anchors[old_anchor] = (
                f"{checked_path}#{target_anchor}" if separator else checked_path
            )
        title_value = item.get("title")
        if title_value is not None and (
            not isinstance(title_value, str) or not title_value.strip()
        ):
            raise ValueError(
                f"{source}: moves[{index}] title must be a non-empty string"
            )
        moves.append(PageMove(from_path, to_path, kind, anchors, title_value))
    return moves


def site_url(path: str) -> str:
    """Map a docs-relative Markdown file to MkDocs' directory URL."""
    page = PurePosixPath(path)
    if page.name == "index.md":
        stem = page.parent.as_posix()
        return "/" if stem == "." else f"/{quote(stem, safe='/-')}/"
    stem = page.with_suffix("").as_posix()
    return f"/{quote(stem, safe='/-')}/"


def markdown_link(source_path: str, target_path: str, anchor: str | None = None) -> str:
    """Return a relative Markdown destination from one docs page to another."""
    source_parent = PurePosixPath(source_path).parent
    if source_parent.as_posix() == ".":
        source_parent = PurePosixPath("")
    relative = PurePosixPath(target_path)
    if source_parent.parts:
        import posixpath

        target = posixpath.relpath(relative.as_posix(), source_parent.as_posix())
    else:
        target = relative.as_posix()
    if anchor:
        target += f"#{anchor}"
    return target


def slugify_heading(value: str) -> str:
    """Return the heading anchor spelling used by the section splitter."""
    explicit = EXPLICIT_ANCHOR_RE.search(value)
    if explicit:
        return explicit.group(1)
    title = EXPLICIT_ANCHOR_RE.sub("", value).strip()
    # Keep placeholder words in inline code, e.g. `<id>` in a CLI heading.
    # Markdown renders the angle brackets as text there, not as an HTML tag.
    title = re.sub(
        r"`+([^`]+?)`+",
        lambda match: match.group(1).replace("<", " ").replace(">", " "),
        title,
    )
    title = re.sub(r"[*_~]", "", title)
    title = re.sub(r"<[^>]+>", "", title)
    title = re.sub(r"[^\w\-\s]", "", title.lower(), flags=re.UNICODE)
    return re.sub(r"\s+", "-", title).strip("-")


def page_anchors(text: str) -> list[str]:
    """Return Markdown heading and HTML id anchors in document order."""
    anchors: list[str] = []
    slug_counts: dict[str, int] = {}
    fence: str | None = None
    for line in text.splitlines():
        fence_match = re.match(r"^\s*(`{3,}|~{3,})", line)
        if fence_match:
            marker = fence_match.group(1)[0]
            if fence is None:
                fence = marker
            elif marker == fence:
                fence = None
            continue
        if fence is not None:
            continue
        match = HEADING_RE.match(line)
        if not match:
            continue
        title = match.group(2).strip()
        slug = slugify_heading(title)
        count = slug_counts.get(slug, 0)
        slug_counts[slug] = count + 1
        anchors.append(slug if count == 0 else f"{slug}-{count}")
    anchors.extend(match.group(2) for match in HTML_ID_RE.finditer(text))
    return list(dict.fromkeys(anchor for anchor in anchors if anchor))


def _resolve_local_target(href: str, origin: str) -> tuple[str, str, str, bool] | None:
    target = href[1:-1] if href.startswith("<") and href.endswith(">") else href
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc or not parsed.path and not parsed.fragment:
        return None
    path = unquote(parsed.path)
    root_relative = path.startswith("/")
    if root_relative:
        resolved = posixpath.normpath(path.lstrip("/"))
    elif path:
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(origin), path))
    else:
        resolved = origin
    return resolved, parsed.query, unquote(parsed.fragment), root_relative


def _href_for(
    *, origin: str, target: str, query: str, anchor: str, root_relative: bool
) -> str:
    if root_relative:
        path = f"/{target}"
    elif target == origin:
        path = ""
    else:
        path = posixpath.relpath(target, posixpath.dirname(origin) or ".")
    return urlunsplit(("", "", path, query, anchor))


def _rewrite_route_href(
    href: str, *, origin: str, source: str, target: str
) -> str | None:
    """Rewrite a directory-style docs URL such as ``../old-page/``."""
    angle = href.startswith("<") and href.endswith(">")
    bare = href[1:-1] if angle else href
    parsed = urlsplit(bare)
    absolute_url = bool(parsed.scheme or parsed.netloc)
    if absolute_url and parsed.netloc.lower() not in {"sase.sh", "www.sase.sh"}:
        return None
    path = unquote(parsed.path)
    if not path or PurePosixPath(path).suffix:
        return None
    root_relative = path.startswith("/") or absolute_url
    if path.startswith("/"):
        resolved = posixpath.normpath(path.lstrip("/"))
    else:
        base = site_url(origin).lstrip("/")
        resolved = posixpath.normpath(posixpath.join(base, path))
    source_route = PurePosixPath(source).with_suffix("").as_posix()
    if resolved != source_route:
        return None

    target_route = PurePosixPath(target).with_suffix("").as_posix()
    if root_relative:
        new_path = f"/{target_route}"
    else:
        base = site_url(origin).lstrip("/").rstrip("/") or "."
        new_path = posixpath.relpath(target_route, base)
    if path.endswith("/"):
        new_path += "/"
    rewritten = urlunsplit(
        (parsed.scheme, parsed.netloc, new_path, parsed.query, parsed.fragment)
    )
    return f"<{rewritten}>" if angle else rewritten


def _rewrite_href(
    href: str,
    *,
    origin: str,
    destination: str,
    source: str,
    moved_anchors: dict[str, tuple[str, str]],
    rewrite_source: bool = False,
    source_destination: str | None = None,
) -> str:
    angle = href.startswith("<") and href.endswith(">")
    bare = href[1:-1] if angle else href
    if rewrite_source and source_destination is not None:
        route_rewrite = _rewrite_route_href(
            href, origin=origin, source=source, target=source_destination
        )
        if route_rewrite is not None:
            return route_rewrite
    resolved = _resolve_local_target(bare, origin)
    if resolved is None:
        return href
    target_path, query, anchor, root_relative = resolved
    if target_path == source:
        mapped = moved_anchors.get(anchor)
        if mapped is not None:
            target_path, anchor = mapped
        elif rewrite_source and source_destination is not None:
            target_path = source_destination
    elif origin == destination:
        return href
    new_href = _href_for(
        origin=destination,
        target=target_path,
        query=query,
        anchor=anchor,
        root_relative=root_relative,
    )
    return f"<{new_href}>" if angle else new_href


def _rewrite_links(
    text: str,
    *,
    origin: str,
    destination: str,
    source: str,
    moved_anchors: dict[str, tuple[str, str]],
    rewrite_source: bool = False,
    source_destination: str | None = None,
) -> str:
    def replace(match: re.Match[str]) -> str:
        return match.group("prefix") + _rewrite_href(
            match.group("target"),
            origin=origin,
            destination=destination,
            source=source,
            moved_anchors=moved_anchors,
            rewrite_source=rewrite_source,
            source_destination=source_destination,
        )

    def replace_html(match: re.Match[str]) -> str:
        quote = match.group("quote") or ""
        target = match.group("target") or match.group("unquoted")
        return (
            match.group("prefix")
            + quote
            + _rewrite_href(
                target,
                origin=origin,
                destination=destination,
                source=source,
                moved_anchors=moved_anchors,
                rewrite_source=rewrite_source,
                source_destination=source_destination,
            )
            + quote
        )

    text = INLINE_LINK_RE.sub(replace, text)
    text = REFERENCE_LINK_RE.sub(replace, text)
    return HTML_LINK_RE.sub(replace_html, text)


def _rewrite_handwritten(
    text: str,
    *,
    origin: str,
    destination: str,
    source: str,
    moved_anchors: dict[str, tuple[str, str]],
    rewrite_source: bool = False,
    source_destination: str | None = None,
) -> tuple[str, bool]:
    """Rewrite authored links and flag generated content that needs a renderer edit."""
    if GENERATED_FILE_RE.search(text):
        rewritten = _rewrite_links(
            text,
            origin=origin,
            destination=destination,
            source=source,
            moved_anchors=moved_anchors,
            rewrite_source=rewrite_source,
            source_destination=source_destination,
        )
        return text, rewritten != text
    warnings = False
    result: list[str] = []
    offset = 0
    for match in GENERATED_BLOCK_RE.finditer(text):
        result.append(
            _rewrite_links(
                text[offset : match.start()],
                origin=origin,
                destination=destination,
                source=source,
                moved_anchors=moved_anchors,
                rewrite_source=rewrite_source,
                source_destination=source_destination,
            )
        )
        block = match.group(0)
        rewritten_block = _rewrite_links(
            block,
            origin=origin,
            destination=destination,
            source=source,
            moved_anchors=moved_anchors,
            rewrite_source=rewrite_source,
            source_destination=source_destination,
        )
        warnings = warnings or rewritten_block != block
        result.append(block)
        offset = match.end()
    result.append(
        _rewrite_links(
            text[offset:],
            origin=origin,
            destination=destination,
            source=source,
            moved_anchors=moved_anchors,
            rewrite_source=rewrite_source,
            source_destination=source_destination,
        )
    )
    return "".join(result), warnings
