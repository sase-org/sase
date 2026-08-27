"""One-hop artifact-link inspector for the app-owned link rail."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Literal

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList, Static
from textual.widgets.option_list import Option

from sase.ace.tui.relations.artifact_links import parse_link_ref
from sase.ace.tui.relations.link_index import LinkChip

from .base import OptionListNavigationMixin

_SELECTOR_KEYS = "abcdefghijklmnopqrstuvwxyz"
_MAX_SUBJECT_LABEL_LEN = 48
_MAX_TARGET_LABEL_LEN = 34
_MAX_META_LEN = 96
_KEY_STYLE = "bold #D7AF5F"
_MISSING_STYLE = "dim #808080"
_WHY_STYLE = "dim #A8A8A8"


@dataclass(frozen=True, slots=True)
class ArtifactLinksPanelResult:
    """Action returned by :class:`ArtifactLinksPanelModal`."""

    action: Literal["follow", "add", "remove"]
    chip: LinkChip | None = None


def _artifact_links_panel_selector_keys(count: int) -> list[str]:
    """Return the direct row selectors for the panel."""

    return list(_SELECTOR_KEYS[: max(0, min(count, len(_SELECTOR_KEYS)))])


def _short_text(value: object, *, max_len: int) -> str:
    text = str(value or "")
    if len(text) <= max_len:
        return text
    if max_len <= 3:
        return text[:max_len]
    return text[: max_len - 3] + "..."


def _link_direction_glyph(chip: LinkChip) -> str:
    if not chip.directed:
        return "↔"
    return "→" if chip.this_is_source else "←"


def _target_label(chip: LinkChip) -> str:
    parsed = parse_link_ref(chip.neighbor_ref)
    if parsed is None:
        return chip.neighbor_ref or "unknown"
    kind, payload = parsed
    if kind == "stitch":
        repo, sep, sha = payload.partition("@")
        repo_label = PurePosixPath(repo).name or repo
        return f"{repo_label}@{sha[:7]}" if sep and sha else payload
    if kind == "file":
        return PurePosixPath(payload).name or payload
    return payload


def _is_missing(chip: LinkChip) -> bool:
    parsed = parse_link_ref(chip.neighbor_ref)
    neighbor_kind = "" if parsed is None else parsed[0]
    return chip.neighbor_target is None and neighbor_kind != "chop"


def _projection_rule(chip: LinkChip) -> str:
    prefix = "projection:"
    return (
        chip.created_by.removeprefix(prefix)
        if chip.created_by.startswith(prefix)
        else ""
    )


def _source_label(chip: LinkChip) -> str:
    rule = _projection_rule(chip)
    if rule:
        return f"projected:{rule}"
    if chip.writable:
        return "store"
    return chip.origin or "read-only"


def _metadata_lines(chip: LinkChip) -> tuple[str, ...]:
    first = [f"origin {chip.origin or '-'}", f"uses {chip.uses}"]
    if chip.created_at:
        first.append(f"created {chip.created_at}")
    second: list[str] = []
    if chip.created_by:
        second.append(f"by {chip.created_by}")
    rule = _projection_rule(chip)
    if rule:
        second.append(f"rule {rule}")
    second.append(_source_label(chip))
    if not chip.writable:
        second.append("rm disabled")
    lines = [_short_text("  ".join(first), max_len=_MAX_META_LEN)]
    if second:
        lines.append(_short_text("  ".join(second), max_len=_MAX_META_LEN))
    return tuple(lines)


def _artifact_link_option_text(selector: str | None, chip: LinkChip) -> Text:
    """Render one link-panel row with full why/provenance text."""

    text = Text()
    if selector is None:
        text.append("   ", style="dim")
    else:
        text.append(f"{selector}  ", style=_KEY_STYLE)
    text.append(f"{_link_direction_glyph(chip)} ", style="dim")
    text.append(chip.label, style="bold")
    text.append("  ")
    if _is_missing(chip):
        text.append("⊘ ", style=_MISSING_STYLE)
    text.append(chip.icon or "•", style=f"bold {chip.accent}")
    text.append(" ")
    target_style = _MISSING_STYLE if _is_missing(chip) else f"bold {chip.accent}"
    text.append(
        _short_text(_target_label(chip), max_len=_MAX_TARGET_LABEL_LEN),
        style=target_style,
    )
    if _is_missing(chip):
        text.append(" (missing)", style=_MISSING_STYLE)
    for metadata_line in _metadata_lines(chip):
        text.append("\n   ")
        text.append(metadata_line, style="dim")
    if chip.why:
        text.append("\n   why: ", style="dim")
        text.append(chip.why, style=_WHY_STYLE)
    return text


def _choice_index_from_option_id(option_id: str | None) -> int | None:
    if option_id is None or not option_id.startswith("choice-"):
        return None
    try:
        return int(option_id.removeprefix("choice-"))
    except ValueError:
        return None


class ArtifactLinksPanelModal(
    OptionListNavigationMixin,
    ModalScreen[ArtifactLinksPanelResult | None],
):
    """Keyboard-first inspector for the selected entity's link neighborhood."""

    _option_list_id = "artifact-links-panel-list"
    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("down", "next_option", "Next"),
        ("up", "prev_option", "Previous"),
        ("ctrl+n", "next_option", "Next"),
        ("ctrl+p", "prev_option", "Previous"),
        ("enter", "select_highlighted", "Follow"),
    ]

    def __init__(
        self,
        *,
        subject_ref: str,
        chips: Sequence[LinkChip],
        scoped_label: str | None = None,
        add_enabled: bool = False,
        staleness_notice: str = "",
    ) -> None:
        super().__init__()
        self._subject_ref = subject_ref
        self._chips = tuple(chips)
        self._scoped_label = scoped_label
        self._add_enabled = add_enabled
        self._staleness_notice = staleness_notice
        selectors = _artifact_links_panel_selector_keys(len(self._chips))
        self._selector_by_index = selectors
        self._index_by_selector = {key: index for index, key in enumerate(selectors)}

    def compose(self) -> ComposeResult:
        with Container(id="artifact-links-panel-container"):
            yield Label(self._title_text(), id="artifact-links-panel-title")
            yield Static(
                self._staleness_notice,
                id="artifact-links-panel-staleness",
                classes="notice" if self._staleness_notice else "hidden",
            )
            yield OptionList(*self._create_options(), id=self._option_list_id)
            yield Static(self._hint_text(), id="artifact-links-panel-hints")

    def _title_text(self) -> str:
        count = len(self._chips)
        plural = "" if count == 1 else "s"
        subject = _short_text(self._subject_ref, max_len=_MAX_SUBJECT_LABEL_LEN)
        scope = "" if not self._scoped_label else f" · {self._scoped_label}"
        return f"Links for {subject}{scope}  [{count} link{plural}]"

    def _hint_text(self) -> str:
        add = "  + add marked" if self._add_enabled else ""
        return f"a-z follow  enter follow  - rm writable{add}  arrows move  esc close"

    def _create_options(self) -> list[Option]:
        options: list[Option] = []
        for index, chip in enumerate(self._chips):
            selector = (
                self._selector_by_index[index]
                if index < len(self._selector_by_index)
                else None
            )
            options.append(
                Option(
                    _artifact_link_option_text(selector, chip),
                    id=f"choice-{index}",
                )
            )
        return options

    def on_mount(self) -> None:
        self.query_one(f"#{self._option_list_id}", OptionList).focus()

    def on_key(self, event: events.Key) -> None:
        char = event.character.lower() if isinstance(event.character, str) else ""
        if char in self._index_by_selector:
            self.dismiss(
                ArtifactLinksPanelResult(
                    action="follow",
                    chip=self._chips[self._index_by_selector[char]],
                )
            )
            event.prevent_default()
            event.stop()
            return
        if char == "+" or event.key == "plus":
            if self._add_enabled:
                self.dismiss(ArtifactLinksPanelResult(action="add"))
            else:
                self.notify(
                    "Add is available from an Artifacts pane with one marked row",
                    severity="warning",
                )
            event.prevent_default()
            event.stop()
            return
        if char == "-" or event.key == "minus":
            self.action_remove_highlighted()
            event.prevent_default()
            event.stop()

    def action_select_highlighted(self) -> None:
        chip = self._highlighted_chip()
        if chip is None:
            return
        self.dismiss(ArtifactLinksPanelResult(action="follow", chip=chip))

    def action_remove_highlighted(self) -> None:
        chip = self._highlighted_chip()
        if chip is None:
            return
        if not chip.writable:
            self.notify(
                f"Cannot remove {_source_label(chip)} link from the store",
                severity="warning",
            )
            return
        self.dismiss(ArtifactLinksPanelResult(action="remove", chip=chip))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        option_id = str(event.option.id) if event.option else None
        choice_idx = _choice_index_from_option_id(option_id)
        if choice_idx is not None and 0 <= choice_idx < len(self._chips):
            self.dismiss(
                ArtifactLinksPanelResult(
                    action="follow",
                    chip=self._chips[choice_idx],
                )
            )

    def update_staleness_notice(self, notice: str) -> None:
        """Update the panel's staleness row after an off-thread drift check."""

        self._staleness_notice = notice
        try:
            widget = self.query_one("#artifact-links-panel-staleness", Static)
        except Exception:
            return
        widget.update(notice)
        widget.set_class(not bool(notice), "hidden")
        widget.set_class(bool(notice), "notice")

    def _highlighted_chip(self) -> LinkChip | None:
        option_list = self.query_one(f"#{self._option_list_id}", OptionList)
        index = option_list.highlighted
        if index is None:
            return None
        choice_idx = _choice_index_from_option_id(
            str(option_list.get_option_at_index(index).id)
        )
        if choice_idx is None or not 0 <= choice_idx < len(self._chips):
            return None
        return self._chips[choice_idx]


__all__ = [
    "ArtifactLinksPanelModal",
    "ArtifactLinksPanelResult",
    "_artifact_link_option_text",
    "_artifact_links_panel_selector_keys",
]
