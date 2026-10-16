"""Validated access to the docs page-move map."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import quote

import yaml  # type: ignore[import-untyped]


REPO_ROOT = Path(__file__).resolve().parents[1]
MOVES_PATH = Path("docs/_meta/moves.yml")


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
