"""Post-restart update confirmation toast for the ace TUI."""

from __future__ import annotations

import logging
import shlex

from textual.markup import escape

from sase.ace.update_receipt import (
    UpdateToastReceipt,
    UpdateVersionTransition,
    read_and_clear_pending_update_toast,
)
from sase.dev_update.models import RepoDiffStat

from ..modals.config_center_modal import center_tab_accent
from . import update_toast

log = logging.getLogger(__name__)

_SUCCESS_GLYPH = "✓"
_TOAST_TIMEOUT_SECONDS = 10.0
_DIFFSTAT_RED = "#D75F5F"
_NAME_COLUMN_MAX = 28
_COMMIT_SUBJECT_MAX = 58


class PostUpdateToastMixin:
    """Mixin that renders a one-shot update confirmation after ACE restarts."""

    _update_toast_shown: bool

    def _maybe_show_post_update_toast(self) -> None:
        """Consume and render the pending post-update toast receipt, if present."""
        try:
            receipt = read_and_clear_pending_update_toast()
        except Exception:
            log.debug("Failed to consume pending update toast", exc_info=True)
            return
        if receipt is None:
            return

        try:
            config = update_toast._load_update_toast_config()
        except Exception:
            log.debug("Failed to load post-update toast config", exc_info=True)
            config = update_toast._UpdateToastConfig()
        if not config.post_update_toast:
            return

        self._update_toast_shown = True
        try:
            severity = (
                "warning"
                if any(result.status == "failed" for result in receipt.provider_results)
                else "information"
            )
            self.notify(  # type: ignore[attr-defined]
                _format_post_update_toast_message(
                    receipt,
                    show_diffstat=config.post_update_toast_diffstat,
                    show_commits=config.post_update_toast_commits,
                    max_commits_per_repo=config.post_update_toast_max_commits,
                ),
                title=_format_post_update_toast_title(receipt),
                severity=severity,
                timeout=_TOAST_TIMEOUT_SECONDS,
                markup=True,
            )
        except Exception:
            log.debug("Failed to show post-update toast", exc_info=True)


def _format_post_update_toast_title(receipt: UpdateToastReceipt) -> str:
    if any(result.status == "failed" for result in receipt.provider_results):
        return "⚠ SASE updated with Agent CLI issues"
    if receipt.kind == "mode_switch_dev":
        return f"{_SUCCESS_GLYPH} Switched to Dev (editable)"
    if receipt.kind == "mode_switch_pypi":
        return f"{_SUCCESS_GLYPH} Switched to PyPI (managed)"
    primary = receipt.primary
    if primary is not None and primary.new:
        return f"{_SUCCESS_GLYPH} Updated to sase {primary.new}"
    if primary is None and len(receipt.plugins) == 1 and receipt.plugin_overflow == 0:
        plugin = receipt.plugins[0]
        operation = _transition_operation(plugin)
        if operation == "install":
            return f"{_SUCCESS_GLYPH} Installed {plugin.name}"
        if operation == "uninstall":
            return f"{_SUCCESS_GLYPH} Uninstalled {plugin.name}"
        return f"{_SUCCESS_GLYPH} Updated {plugin.name}"
    if primary is None and receipt.plugins:
        operations = {_transition_operation(plugin) for plugin in receipt.plugins}
        if operations == {"install"}:
            return f"{_SUCCESS_GLYPH} Installed plugins"
        if operations == {"uninstall"}:
            return f"{_SUCCESS_GLYPH} Uninstalled plugins"
        return f"{_SUCCESS_GLYPH} Updated plugins"
    return f"{_SUCCESS_GLYPH} SASE updated"


def _format_post_update_toast_message(
    receipt: UpdateToastReceipt,
    *,
    show_diffstat: bool = True,
    show_commits: bool = True,
    max_commits_per_repo: int = 5,
) -> str:
    accent = center_tab_accent("updates") or "#AF87FF"
    commits = (
        _commit_group_lines(receipt, max_per_repo=max_commits_per_repo)
        if show_commits
        else ""
    )
    if not show_diffstat or not _receipt_has_diffstat(receipt):
        summary = _format_legacy_post_update_toast_message(
            receipt,
            accent,
            show_commits=bool(commits),
        )
    else:
        summary = _format_diffstat_post_update_toast_message(
            receipt,
            accent,
            show_commits=bool(commits),
        )
    provider_lines = _provider_result_lines(receipt)
    return "\n\n".join(part for part in (summary, commits, provider_lines) if part)


def _commit_group_lines(
    receipt: UpdateToastReceipt,
    *,
    max_per_repo: int,
) -> str:
    if not receipt.commit_groups:
        return ""
    capped_max = max(0, max_per_repo)
    groups: list[str] = []
    for group in receipt.commit_groups:
        total = group.commits.total
        noun = "commit" if total == 1 else "commits"
        lines = [f"[bold cyan]↑ {escape(group.label)}[/] [cyan]— {total} {noun}[/]"]
        shown = group.commits.commits[:capped_max]
        for commit in shown:
            subject = _truncate_commit_subject(commit.subject)
            lines.append(f"  [dim]{escape(commit.short_sha)}[/]  {escape(subject)}")
        extra = max(0, total - len(shown))
        if extra > 0:
            lines.append(f"  [dim]+{extra} more…[/]")
        groups.append("\n".join(lines))
    if receipt.commit_group_overflow > 0:
        noun = "repository" if receipt.commit_group_overflow == 1 else "repositories"
        groups.append(f"[dim]…and {receipt.commit_group_overflow} more {noun}[/]")
    return "\n\n".join(groups)


def _truncate_commit_subject(subject: str) -> str:
    if len(subject) <= _COMMIT_SUBJECT_MAX:
        return subject
    return f"{subject[: _COMMIT_SUBJECT_MAX - 1]}…"


def _provider_result_lines(receipt: UpdateToastReceipt) -> str:
    if not receipt.provider_results and receipt.provider_overflow <= 0:
        return ""
    lines = ["[bold]Agent CLIs[/]"]
    for result in receipt.provider_results:
        name = escape(result.display_name)
        if result.status == "updated":
            old = escape(result.old_version or "unknown")
            new = escape(result.new_version or "unknown")
            line = f"• {name}: [dim]{old} →[/] [green]{new}[/]"
            if result.reason:
                line += f" — [yellow]{escape(result.reason)}[/]"
            lines.append(line)
            continue
        if result.status == "already_current":
            lines.append(f"• {name}: [dim]already current[/]")
            continue
        reason = escape(result.reason or "skipped")
        if result.status == "failed":
            lines.append(f"• {name}: [red]failed[/] — {reason}")
            continue
        if result.suggested_command:
            command = escape(shlex.join(result.suggested_command))
            lines.append(f"• {name}: [yellow]manual[/] — {reason}")
            lines.append(f"  [dim]{command}[/]")
        else:
            lines.append(f"• {name}: [yellow]skipped[/] — {reason}")
    if receipt.provider_overflow:
        lines.append(f"…and {receipt.provider_overflow} more provider results")
    return "\n".join(lines)


def _format_legacy_post_update_toast_message(
    receipt: UpdateToastReceipt,
    accent: str,
    *,
    show_commits: bool = False,
) -> str:
    lines: list[str] = []
    if receipt.primary is not None:
        lines.append(_primary_line(receipt.primary, accent))
    for plugin in receipt.plugins:
        lines.append(_plugin_line(plugin))
    if receipt.plugin_overflow > 0:
        lines.append(f"…and {receipt.plugin_overflow} more")
    tail = _tail_line(receipt, show_commits=show_commits)
    if tail:
        if lines:
            lines.append("")
        lines.append(tail)
    return "\n".join(lines)


def _format_diffstat_post_update_toast_message(
    receipt: UpdateToastReceipt,
    accent: str,
    *,
    show_commits: bool = False,
) -> str:
    transitions: list[tuple[UpdateVersionTransition, bool]] = []
    if receipt.primary is not None:
        transitions.append((receipt.primary, True))
    transitions.extend((plugin, False) for plugin in receipt.plugins)

    display_names = [
        _transition_display_name(transition, primary=is_primary)
        for transition, is_primary in transitions
    ]
    overflow_label = _overflow_label(receipt)
    if overflow_label is not None:
        display_names.append(overflow_label)
    name_width = max((len(name) for name in display_names), default=0)
    old_width = max(
        (
            len(_version_text(transition.old))
            for transition, is_primary in transitions
            if not is_primary
        ),
        default=0,
    )
    new_width = max(
        (
            len(_version_text(transition.new))
            for transition, is_primary in transitions
            if not is_primary
        ),
        default=0,
    )
    transition_prefix_width = name_width + 2 + old_width + 3 + new_width + 3

    lines: list[str] = []
    for transition, is_primary in transitions:
        lines.append(
            _diffstat_transition_line(
                transition,
                primary=is_primary,
                accent=accent,
                name_width=name_width,
                old_width=old_width,
                new_width=new_width,
            )
        )
        if is_primary:
            churn_line = _primary_diffstat_line(
                transition.diffstat,
                name_width=name_width,
            )
            if churn_line:
                lines.append(churn_line)
    if overflow_label is not None:
        lines.append(
            _diffstat_overflow_line(
                overflow_label,
                receipt.plugin_overflow_diffstat,
                transition_prefix_width,
            )
        )
    tail = _tail_line(
        receipt,
        show_diffstat=True,
        show_commits=show_commits,
    )
    if tail:
        if lines:
            lines.append("")
        lines.append(tail)
    return "\n".join(lines)


def _primary_line(transition: UpdateVersionTransition, accent: str) -> str:
    old = escape(transition.old or "unknown")
    new = escape(transition.new or "unknown")
    name = escape(transition.name)
    return f"[bold {accent}]{name}[/]  [dim]{old}[/] [dim]→[/] [bold green]{new}[/]"


def _plugin_line(transition: UpdateVersionTransition) -> str:
    name = escape(transition.name)
    operation = _transition_operation(transition)
    if operation == "install":
        suffix = f" v{escape(transition.new)}" if transition.new else ""
        return f"• {name}  [green]installed{suffix}[/]"
    if operation == "uninstall":
        suffix = f" [dim](was v{escape(transition.old)})[/]" if transition.old else ""
        return f"• {name}  [yellow]uninstalled[/]{suffix}"
    old = escape(transition.old or "unknown")
    new = escape(transition.new or "unknown")
    return f"• {name}  [dim]{old} →[/] [green]{new}[/]"


def _tail_line(
    receipt: UpdateToastReceipt,
    *,
    show_diffstat: bool = False,
    show_commits: bool = False,
) -> str:
    parts: list[str] = []
    if show_commits:
        commit_count = sum(group.commits.total for group in receipt.commit_groups)
        if commit_count > 0:
            noun = "commit" if commit_count == 1 else "commits"
            parts.append(f"{commit_count:,} {noun}")
    if show_diffstat:
        files_changed = _total_files_changed(receipt)
        if files_changed > 0:
            noun = "file" if files_changed == 1 else "files"
            parts.append(f"{files_changed:,} {noun} changed")
    if receipt.dependency_count > 0:
        noun = "dependency" if receipt.dependency_count == 1 else "dependencies"
        parts.append(f"+{receipt.dependency_count} {noun}")
    parts.append(_reload_tail_text(receipt))
    return f"[dim]{' · '.join(parts)}[/]"


def _reload_tail_text(receipt: UpdateToastReceipt) -> str:
    if receipt.kind.startswith("mode_switch_"):
        return "Reloaded into the switched install mode."
    if receipt.primary is not None:
        return "Reloaded into the new version."
    plugin_count = len(receipt.plugins) + receipt.plugin_overflow
    if plugin_count <= 0:
        return "Reloaded into the new version."
    operations = {_transition_operation(plugin) for plugin in receipt.plugins}
    if operations == {"install"}:
        noun = "plugin" if plugin_count == 1 else "plugins"
        return f"Reloaded to load the new {noun}."
    if operations == {"uninstall"}:
        noun = "plugin" if plugin_count == 1 else "plugins"
        return f"Reloaded after removing the {noun}."
    return "Reloaded into the new plugin version."


def _diffstat_transition_line(
    transition: UpdateVersionTransition,
    *,
    primary: bool,
    accent: str,
    name_width: int,
    old_width: int,
    new_width: int,
) -> str:
    display_name = _transition_display_name(transition, primary=primary)
    name_pad = " " * (name_width - len(display_name))
    old_text = _version_text(transition.old)
    new_text = _version_text(transition.new)
    old_pad = " " * (old_width - len(old_text))
    new_pad = " " * (new_width - len(new_text))
    diffstat = _diffstat_markup(transition.diffstat)
    if primary:
        name = _truncated_transition_name(transition.name)
        return (
            f"[bold {accent}]{escape(name)}[/]{name_pad}  "
            f"[dim]{escape(old_text)}[/]{old_pad} [dim]→[/] "
            f"[bold green]{escape(new_text)}[/]{new_pad}"
        )
    suffix = f"   {diffstat}" if diffstat else ""
    name = _truncated_transition_name(transition.name)
    return (
        f"• {escape(name)}{name_pad}  "
        f"[dim]{escape(old_text)}{old_pad} →[/] "
        f"[green]{escape(new_text)}[/]{new_pad}{suffix}"
    )


def _primary_diffstat_line(
    diffstat: RepoDiffStat | None,
    *,
    name_width: int,
) -> str:
    diffstat_markup = _diffstat_markup(diffstat)
    if not diffstat_markup:
        return ""
    return f"{' ' * (name_width + 2)}{diffstat_markup}"


def _diffstat_overflow_line(
    label: str,
    diffstat: RepoDiffStat | None,
    transition_prefix_width: int,
) -> str:
    diffstat_markup = _diffstat_markup(diffstat)
    if not diffstat_markup:
        return label
    padding = " " * max(1, transition_prefix_width - len(label))
    return f"{label}{padding}{diffstat_markup}"


def _transition_display_name(
    transition: UpdateVersionTransition,
    *,
    primary: bool,
) -> str:
    name = _truncated_transition_name(transition.name)
    return name if primary else f"• {name}"


def _transition_operation(transition: UpdateVersionTransition) -> str:
    if transition.old is None and transition.new is not None:
        return "install"
    if transition.old is not None and transition.new is None:
        return "uninstall"
    return "update"


def _truncated_transition_name(name: str) -> str:
    if len(name) <= _NAME_COLUMN_MAX:
        return name
    return f"{name[: _NAME_COLUMN_MAX - 1]}…"


def _version_text(value: str | None) -> str:
    return value or "unknown"


def _overflow_label(receipt: UpdateToastReceipt) -> str | None:
    if receipt.plugin_overflow <= 0:
        return None
    return f"…and {receipt.plugin_overflow} more"


def _diffstat_markup(diffstat: RepoDiffStat | None) -> str:
    if diffstat is None or diffstat.is_empty:
        return ""
    if not diffstat.has_line_changes:
        noun = "file" if diffstat.files_changed == 1 else "files"
        return f"[dim]{diffstat.files_changed:,} {noun}[/]"
    return (
        f"[bold green]+{diffstat.insertions:,}[/] "
        f"[{_DIFFSTAT_RED}]−{diffstat.deletions:,}[/]"
    )


def _receipt_has_diffstat(receipt: UpdateToastReceipt) -> bool:
    return any(not stat.is_empty for stat in _receipt_diffstats(receipt))


def _total_files_changed(receipt: UpdateToastReceipt) -> int:
    return sum(stat.files_changed for stat in _receipt_diffstats(receipt))


def _receipt_diffstats(receipt: UpdateToastReceipt) -> tuple[RepoDiffStat, ...]:
    stats: list[RepoDiffStat] = []
    if receipt.primary is not None and receipt.primary.diffstat is not None:
        stats.append(receipt.primary.diffstat)
    stats.extend(
        plugin.diffstat for plugin in receipt.plugins if plugin.diffstat is not None
    )
    if receipt.plugin_overflow_diffstat is not None:
        stats.append(receipt.plugin_overflow_diffstat)
    return tuple(stats)


__all__ = ["PostUpdateToastMixin"]
