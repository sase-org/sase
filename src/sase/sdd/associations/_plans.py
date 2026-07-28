"""Plan-tree discovery and cycle-safe epic descendant roll-up."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
import re

from sase.sdd.frontmatter import parse_frontmatter

from ._history import HistoricalCommit
from ._normalization import PlanReferenceNormalizer

_PARENT_BULLET_RE = re.compile(r"^- \*\*PARENT:\*\*(?:\s+(.*))?$")
_TOP_BULLET_RE = re.compile(r"^- \*\*[A-Z]+:\*\*")
_MARKDOWN_LINK_RE = re.compile(r"^\[([^\]]+)\]\([^)]*\)$")


@dataclass(frozen=True, slots=True)
class _PlanNode:
    """The plan-tree fields needed by association roll-up."""

    reference: str
    tier: str
    parent: str | None


def scan_plan_tree(normalizer: PlanReferenceNormalizer) -> dict[str, _PlanNode]:
    """Read each plan document once and return its parent relationship."""

    result: dict[str, _PlanNode] = {}
    root = normalizer.store.kind_root("plans")
    for path in sorted(root.rglob("*.md")):
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        frontmatter, body, had_frontmatter = parse_frontmatter(content)
        tier = str(frontmatter.get("tier") or "").casefold()
        if not had_frontmatter or tier not in {"tale", "epic"}:
            continue
        reference = normalizer.normalize(path)
        if reference is None:
            continue
        parent_value = _parent_bullet_reference(body)
        if parent_value is None:
            legacy_parent = frontmatter.get("parent")
            parent_value = legacy_parent if isinstance(legacy_parent, str) else None
        result[reference] = _PlanNode(
            reference,
            tier,
            normalizer.normalize(parent_value),
        )
    return result


def roll_up_epics(
    agents: dict[str, set[str]],
    commits: dict[str, dict[str, HistoricalCommit]],
    nodes: dict[str, _PlanNode],
) -> None:
    """Union every descendant's direct associations into each epic."""

    children: defaultdict[str, set[str]] = defaultdict(set)
    for node in nodes.values():
        if node.parent is not None:
            children[node.parent].add(node.reference)
    for reference, node in nodes.items():
        if node.tier != "epic":
            continue
        for descendant in _descendants(reference, children):
            agents.setdefault(reference, set()).update(agents.get(descendant, ()))
            target_commits = commits.setdefault(reference, {})
            target_commits.update(commits.get(descendant, {}))


def _descendants(
    root: str,
    children: dict[str, set[str]],
) -> tuple[str, ...]:
    visited = {root}
    pending = sorted(children.get(root, ()), reverse=True)
    result: list[str] = []
    while pending:
        reference = pending.pop()
        if reference in visited:
            continue
        visited.add(reference)
        result.append(reference)
        pending.extend(sorted(children.get(reference, ()), reverse=True))
    return tuple(result)


def _parent_bullet_reference(body: str) -> str | None:
    lines = body.splitlines()
    index = 0
    while index < len(lines) and not lines[index].strip():
        index += 1
    while index < len(lines):
        match = _PARENT_BULLET_RE.match(lines[index])
        if match is not None:
            payload = (match.group(1) or "").strip()
            index += 1
            continuations: list[str] = []
            while index < len(lines):
                line = lines[index]
                if _TOP_BULLET_RE.match(line) or (line and not line[0].isspace()):
                    break
                if line.startswith("  - "):
                    break
                if line.strip():
                    continuations.append(line.strip())
                index += 1
            logical = " ".join((payload, *continuations)).strip()
            link = _MARKDOWN_LINK_RE.match(logical)
            return _unescape_markdown(link.group(1) if link is not None else logical)
        if not _TOP_BULLET_RE.match(lines[index]):
            break
        index += 1
        while index < len(lines) and (
            not lines[index].strip() or lines[index][0].isspace()
        ):
            index += 1
    return None


def _unescape_markdown(value: str) -> str:
    return re.sub(r"\\([\\`*{}\[\]()#+\-.!_>])", r"\1", value).strip()


__all__ = ["roll_up_epics", "scan_plan_tree"]
