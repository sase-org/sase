"""Option-list construction for the capacity inspector modal."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rich.text import Text
from textual.widgets.option_list import Option

from sase.core.runner_slots import format_capacity_duration

from ._capacity_inspector_render import (
    empty_charged_message,
    format_capacity_number,
    render_capacity_row,
    render_section_header,
)
from ._capacity_inspector_shared import OptionAction


@dataclass(frozen=True, slots=True)
class _GroupMember:
    name: str
    artifact_dir: str


def build_capacity_options(
    view: Any | None,
    *,
    expanded_groups: set[str],
    width: int,
) -> tuple[
    list[Option],
    dict[str, OptionAction],
    dict[str, tuple[str, int]],
    dict[str, list[str]],
]:
    """Build inspector options and the action/position indexes for *view*."""
    option_actions: dict[str, OptionAction] = {}
    option_positions: dict[str, tuple[str, int]] = {}
    section_option_ids: dict[str, list[str]] = {}
    if view is None:
        return (
            [Option("Waiting for the first authoritative report…", disabled=True)],
            option_actions,
            option_positions,
            section_option_ids,
        )

    options: list[Option] = []
    if view.accounting_unavailable:
        _add_header(options, "Accounting", "unavailable", width)
        _add_disabled(options, "This sase-core build reports totals only.")
        return options, option_actions, option_positions, section_option_ids

    attention_count = sum(group.count for group in view.attention_groups)
    if attention_count or view.diagnostics:
        _add_header(
            options,
            "Needs attention",
            f"{attention_count + len(view.diagnostics)} issues",
            width,
        )
        for group in view.attention_groups:
            for name, artifact_dir in zip(
                group.members,
                group.member_artifact_dirs,
                strict=False,
            ):
                member = _GroupMember(name, artifact_dir)
                _add_agent(
                    options,
                    option_actions,
                    option_positions,
                    section_option_ids,
                    section="attention",
                    option_id=f"agent:{artifact_dir}",
                    row=member,
                    detail_kind="member",
                    group=group,
                    mark="▱?",
                    name=name,
                    kind="attention",
                    note=group.reason_label,
                    width=width,
                    mark_style="yellow",
                    name_style="yellow",
                )
        for diagnostic in view.diagnostics:
            _add_disabled(options, f"! {diagnostic}", style="yellow")

    charged = tuple(view.charged)
    _add_header(
        options,
        "Using capacity",
        f"{format_capacity_number(view.total_charged)} units · {len(charged)} agents",
        width,
    )
    if not charged:
        _add_disabled(options, empty_charged_message(view))
    for row in charged:
        note_parts = []
        if row.weight_source == "explicit":
            note_parts.append("explicit weight")
        elif row.weight_source == "inherited":
            note_parts.append("inherited")
        if row.authored_budget is not None:
            note_parts.append(f"budget {row.authored_budget}")
        if row.rider_names:
            noun = "rider" if len(row.rider_names) == 1 else "riders"
            note_parts.append(f"+{len(row.rider_names)} {noun}")
        _add_agent(
            options,
            option_actions,
            option_positions,
            section_option_ids,
            section="using",
            option_id=f"agent:{row.artifact_dir}",
            row=row,
            detail_kind="holder",
            mark=f"▰{format_capacity_number(row.charged_weight)}",
            name=row.name,
            kind=row.kind,
            note=" · ".join(note_parts),
            age=format_capacity_duration(row.running_seconds),
            width=width,
        )

    _add_header(options, "Queued", f"{len(view.queued)} waiting", width)
    if not view.queued:
        _add_disabled(options, "Nobody is queued")
    tone_styles = {
        "ready": "green",
        "capacity": "yellow",
        "held": "magenta",
        "never_fits": "red",
        "deferred": "dim",
        "other": "yellow",
    }
    for row in view.queued:
        _add_agent(
            options,
            option_actions,
            option_positions,
            section_option_ids,
            section="queued",
            option_id=f"agent:{row.artifact_dir}",
            row=row,
            detail_kind="queued",
            mark=f"#{row.queue_position}",
            name=row.name,
            kind="waiter",
            note=row.blocker,
            age=format_capacity_duration(row.waiting_seconds),
            width=width,
            mark_style=tone_styles.get(row.tone, "yellow"),
            note_style=tone_styles.get(row.tone, "yellow"),
        )

    zero_rows = tuple(view.zero_weight)
    riders = tuple(view.riders)
    if zero_rows or riders:
        _add_header(
            options,
            "Running at zero weight",
            f"{len(zero_rows) + len(riders)} agents",
            width,
        )
        for row in zero_rows:
            _add_agent(
                options,
                option_actions,
                option_positions,
                section_option_ids,
                section="zero",
                option_id=f"agent:{row.artifact_dir}",
                row=row,
                detail_kind="zero",
                mark="▰0",
                name=row.name,
                kind=row.kind,
                note="explicit zero weight",
                age=format_capacity_duration(row.running_seconds),
                width=width,
                mark_style="dim",
            )
        for row in riders:
            _add_agent(
                options,
                option_actions,
                option_positions,
                section_option_ids,
                section="zero",
                option_id=f"agent:{row.artifact_dir}",
                row=row,
                detail_kind="rider",
                mark="⇢",
                name=row.name,
                kind="rider",
                note=f"shares {row.holder_name}'s claim",
                age=format_capacity_duration(row.running_seconds),
                width=width,
            )

    waiting_groups = tuple(view.waiting_groups)
    inactive_groups = tuple(view.inactive_groups)
    if waiting_groups or inactive_groups:
        live_count = sum(group.count for group in waiting_groups)
        inactive_count = sum(group.count for group in inactive_groups)
        _add_header(
            options,
            "Not running",
            f"holds nothing · {live_count} live · {inactive_count} inactive",
            width,
        )
        for group in (*waiting_groups, *inactive_groups):
            _add_group(
                options,
                option_actions,
                option_positions,
                section_option_ids,
                group,
                expanded_groups=expanded_groups,
                width=width,
            )
    return options, option_actions, option_positions, section_option_ids


def _add_header(
    options: list[Option],
    label: str,
    summary: str,
    width: int,
) -> None:
    options.append(
        Option(
            render_section_header(label, summary, width=width),
            disabled=True,
        )
    )


def _add_disabled(
    options: list[Option],
    label: str,
    *,
    style: str = "dim",
) -> None:
    options.append(Option(Text(f"  {label}", style=style), disabled=True))


def _add_agent(
    options: list[Option],
    option_actions: dict[str, OptionAction],
    option_positions: dict[str, tuple[str, int]],
    section_option_ids: dict[str, list[str]],
    *,
    section: str,
    option_id: str,
    row: Any,
    detail_kind: str,
    mark: str,
    name: str,
    kind: str,
    note: str,
    width: int,
    age: str = "",
    mark_style: str = "bold",
    name_style: str = "bold",
    note_style: str = "dim",
    group: Any | None = None,
    group_code: str | None = None,
) -> None:
    prompt = render_capacity_row(
        mark=mark,
        name=name,
        kind=kind,
        note=note,
        age=age,
        width=width,
        mark_style=mark_style,
        name_style=name_style,
        note_style=note_style,
    )
    options.append(Option(prompt, id=option_id))
    section_ids = section_option_ids.setdefault(section, [])
    option_positions[option_id] = (section, len(section_ids))
    section_ids.append(option_id)
    option_actions[option_id] = OptionAction(
        kind="jump",
        detail_kind=detail_kind,
        row=row,
        group=group,
        group_code=group_code,
    )


def _add_group(
    options: list[Option],
    option_actions: dict[str, OptionAction],
    option_positions: dict[str, tuple[str, int]],
    section_option_ids: dict[str, list[str]],
    group: Any,
    *,
    expanded_groups: set[str],
    width: int,
) -> None:
    expanded = group.reason_code in expanded_groups
    preview = ", ".join(group.members)
    option_id = f"group:{group.reason_code}"
    prompt = render_capacity_row(
        mark="▾" if expanded else "▸",
        name=f"{group.count} {group.reason_label}",
        kind="",
        note=preview,
        width=width,
        mark_style="dim" if group.tier == "inactive" else "bold",
        name_style="dim" if group.tier == "inactive" else "bold",
    )
    options.append(Option(prompt, id=option_id))
    section_ids = section_option_ids.setdefault("not_running", [])
    option_positions[option_id] = ("not_running", len(section_ids))
    section_ids.append(option_id)
    option_actions[option_id] = OptionAction(
        kind="toggle_group",
        detail_kind="group",
        group=group,
        group_code=group.reason_code,
    )
    if not expanded:
        return
    for name, artifact_dir in zip(
        group.members,
        group.member_artifact_dirs,
        strict=False,
    ):
        member = _GroupMember(name, artifact_dir)
        _add_agent(
            options,
            option_actions,
            option_positions,
            section_option_ids,
            section="not_running",
            option_id=f"member:{group.reason_code}:{artifact_dir}",
            row=member,
            detail_kind="member",
            mark="↳",
            name=name,
            kind="",
            note="",
            width=width,
            mark_style="dim" if group.tier == "inactive" else "",
            name_style="dim" if group.tier == "inactive" else "bold",
            group=group,
            group_code=group.reason_code,
        )


__all__ = ["build_capacity_options"]
