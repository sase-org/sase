"""Shared link-rail chip ordering and key labels."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

from .artifact_links import parse_link_ref
from .link_index import LinkChip

MAX_DIRECT_LINK_KEYS = 9

_GroupKey = tuple[str, str, str, str, bool, bool]
_OrderEntry = tuple[Literal["single"], int] | tuple[Literal["group"], _GroupKey]


@dataclass(frozen=True, slots=True)
class LinkRailItem:
    """One addressable rail entry: a single chip or collapsed projected group."""

    chip: LinkChip
    count: int = 1
    projected_group: bool = False
    neighbor_kind: str = ""


def link_rail_items(chips: tuple[LinkChip, ...]) -> tuple[LinkRailItem, ...]:
    """Return the addressable rail/key items for ordered *chips*."""

    singles: dict[int, LinkChip] = {}
    groups: dict[_GroupKey, list[LinkChip]] = {}
    order: list[_OrderEntry] = []
    for index, chip in enumerate(chips):
        group_key = _projected_group_key(chip)
        if group_key is None:
            singles[index] = chip
            order.append(("single", index))
            continue
        if group_key not in groups:
            groups[group_key] = []
            order.append(("group", group_key))
        groups[group_key].append(chip)

    items: list[LinkRailItem] = []
    for kind, key in order:
        if kind == "single":
            chip = singles[cast(int, key)]
            parsed = parse_link_ref(chip.neighbor_ref)
            items.append(
                LinkRailItem(
                    chip=chip,
                    neighbor_kind="" if parsed is None else parsed[0],
                )
            )
            continue
        grouped = groups[cast(_GroupKey, key)]
        representative = grouped[0]
        parsed = parse_link_ref(representative.neighbor_ref)
        neighbor_kind = "" if parsed is None else parsed[0]
        items.append(
            LinkRailItem(
                chip=representative,
                count=len(grouped),
                projected_group=len(grouped) > 1,
                neighbor_kind=neighbor_kind,
            )
        )
    return tuple(items)


def link_key_label(index: int, total_links: int) -> str:
    """Return the displayed shortcut for an item at 1-based *index*."""

    return "$$" if index == 1 and total_links == 1 else f"${index}"


def _projected_group_key(
    chip: LinkChip,
) -> _GroupKey | None:
    if chip.origin != "projected" or not chip.created_by.startswith("projection:"):
        return None
    parsed = parse_link_ref(chip.neighbor_ref)
    if parsed is None:
        return None
    neighbor_kind = parsed[0]
    return (
        chip.created_by,
        neighbor_kind,
        chip.relation,
        chip.label,
        chip.directed,
        chip.this_is_source,
    )


__all__ = [
    "MAX_DIRECT_LINK_KEYS",
    "LinkRailItem",
    "link_key_label",
    "link_rail_items",
]
