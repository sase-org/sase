"""Collected raw directive state for prompt directive extraction."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sase.macro.code_value import CodeValue


@dataclass
class CollectedDirectives:
    """Raw directive values and source spans collected from a protected prompt."""

    seen: dict[str, str] = field(default_factory=dict)
    seen_source: dict[str, str] = field(default_factory=dict)
    seen_multi: dict[str, list[str]] = field(default_factory=dict)
    wait_unit_args: list[str] = field(default_factory=list)
    wait_proc_args: list[str] = field(default_factory=list)
    wait_bead_args: list[str] = field(default_factory=list)
    wait_hood_args: list[str] = field(default_factory=list)
    wait_time_args: list[str] = field(default_factory=list)
    wait_occurrences: list[dict[str, Any]] = field(default_factory=list)
    queue_occurrences: list[dict[str, Any]] = field(default_factory=list)
    hold_occurrences: list[dict[str, Any]] = field(default_factory=list)
    model_alias_overrides: dict[str, str] = field(default_factory=dict)
    clan_tribe_arg: str | None = None
    clan_tribe_present: bool = False
    clan_summary_arg: str | None = None
    clan_summary_present: bool = False
    clan_summary_text_block: bool = False
    clan_summary_script_arg: str | None = None
    clan_summary_script_present: bool = False
    name_clan_arg: str | None = None
    name_force_reuse: bool = False
    name_agent_session_args: tuple[str, str] | None = None
    literal_directives: set[str] = field(default_factory=set)
    regions_to_remove: list[tuple[int, int]] = field(default_factory=list)
    proc_code: CodeValue | None = None
    proc_options: dict[str, str] = field(default_factory=dict)
