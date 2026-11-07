"""Recovery-panel entry point and choices for hijacked agent rows."""

from __future__ import annotations

import asyncio
import logging
import subprocess

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from rich.text import Text

from ...models.agent import Agent
from ...modals.agent_action_chooser_modal import (
    AgentActionChoice,
    AgentActionChooserModal,
)
from ._hijack_recovery_actions import (
    agent_by_identity,
    submit_recovery_action,
)
from ._hijack_recovery_formatting import (
    RESULT_PREFIX,
    age,
    diff_totals,
    duration,
    int_value,
    text_value,
)
from ._hijack_recovery_preview import schedule_preview

log = logging.getLogger(__name__)

_KEEP_STYLE = "bold #FF5FAF"
_RELEASE_STYLE = "#8787AF"


def open_hijack_recovery_panel(app: Any, agent: Agent) -> None:
    """Open recovery choices immediately from the row's worker-cached record."""
    record = getattr(agent, "hijack_record", None)
    if not isinstance(record, Mapping):
        app.notify(
            "Recovery details are unavailable; refresh the Agents tab",
            severity="warning",
        )
        return
    record = dict(record)
    if not isinstance(record.get("hijack_id"), str):
        app.notify("Recovery record has no hijack id", severity="error")
        return

    choices = _initial_choices(app, agent, record)
    initial_primary = (
        f"{RESULT_PREFIX}escalate"
        if any(choice.result == f"{RESULT_PREFIX}escalate" for choice in choices)
        else ""
    )
    modal = AgentActionChooserModal(
        choices,
        title=f"⏏ Recover {agent.presented_agent_name or agent.agent_name or agent.cl_name}",
        title_badge=_title_badge(agent, record),
        header=_header_from_record(record),
        section_subtitles={
            "hijack_keep": _keep_subtitle(record),
        },
        primary_result=initial_primary,
        initial_index=0,
        arm_delay_seconds=0.3,
        footer_text="j/k move · ⏎ select · Esc decide later",
    )
    identity = tuple(agent.identity)

    def _on_choice(result: str | None) -> None:
        if result is None:
            return
        current = agent_by_identity(app, identity) or agent
        choice = next((item for item in modal.choices if item.result == result), None)
        if choice is not None and choice.section == "patch":
            patch_name = choice.action_target
            if not patch_name:
                app.notify("No Patch for this agent", severity="warning")
                return
            from ._notification_navigation import navigate_to_patch_tab

            navigate_to_patch_tab(app, patch_name, current.project_file or "")
            return
        if result == f"{RESULT_PREFIX}instruct":
            from ._hijack_prompt_bar import open_hijack_instruct_bar

            open_hijack_instruct_bar(app, current, dict(record))
            return
        if result == f"{RESULT_PREFIX}edit":
            from ._hijack_prompt_bar import open_hijack_edit_bar

            open_hijack_edit_bar(app, current, dict(record))
            return
        if result == f"{RESULT_PREFIX}view":
            _open_recovery_diff(app, current, record)
            return
        if result == f"{RESULT_PREFIX}shell":
            opener = getattr(app, "_open_agent_tmux_window", None)
            if callable(opener):
                opener(use_primary=False)
            else:
                app.notify("Workspace shell is unavailable", severity="warning")
            return
        action = result.removeprefix(RESULT_PREFIX)
        if action not in {"escalate", "continue", "restart", "dismiss"}:
            return
        target = choice.action_target if choice is not None else None
        if choice is not None and not target:
            target = text_value(choice.detail).split(" · ")[-1] or None
        submit_recovery_action(
            app,
            current,
            record,
            action=action,
            model=target if action in {"escalate", "continue"} else None,
        )

    app.push_screen(modal, _on_choice)
    schedule_preview(app, modal, record)


def _initial_choices(
    app: Any, agent: Agent, record: Mapping[str, Any]
) -> tuple[AgentActionChoice, ...]:
    state = str(record.get("state") or "held")
    expired = state == "expired" or bool(getattr(agent, "hijack_expired", False))
    choices: list[AgentActionChoice] = []
    if not expired:
        choices.extend(
            (
                _choice(
                    "escalate",
                    "hijack_keep",
                    "Escalate",
                    "computing…",
                    "⇧",
                    _KEEP_STYLE,
                    "u",
                    pending=True,
                ),
                _choice(
                    "continue",
                    "hijack_keep",
                    "Continue",
                    "computing…",
                    "▶",
                    _KEEP_STYLE,
                    "c",
                    pending=True,
                ),
                _choice(
                    "instruct",
                    "hijack_keep",
                    "Instruct",
                    "add guidance, then continue",
                    "↪",
                    _KEEP_STYLE,
                    "i",
                ),
            )
        )
    choices.append(
        _choice(
            "restart",
            "hijack_fresh",
            "Restart",
            "computing…",
            "⟳",
            _RELEASE_STYLE,
            "r",
            pending=True,
        )
    )
    choices.append(
        _choice(
            "edit",
            "hijack_fresh",
            "Edit",
            "edit the prompt; nothing is released until submit",
            "⌨",
            _RELEASE_STYLE,
            "e",
        )
    )
    workspace_dir = record.get("workspace_dir")
    snapshots = record.get("snapshots")
    has_snapshot = isinstance(snapshots, list) and any(
        isinstance(item, Mapping) and item.get("reference") for item in snapshots
    )
    workspace_num = record.get("workspace_num")
    shell_detail = (
        f"tmux in workspace #{workspace_num} · stays hijacked"
        if isinstance(workspace_num, int)
        else "tmux in held workspace · stays hijacked"
    )
    choices.extend(
        (
            _choice(
                "view",
                "hijack_other",
                "View diff",
                "changes in the pager · stays hijacked",
                "±",
                _RELEASE_STYLE,
                "v",
                disabled_reason=None
                if has_snapshot or workspace_dir
                else "No recovery snapshot is available",
            ),
            _choice(
                "shell",
                "hijack_other",
                "Shell",
                shell_detail,
                "$",
                _RELEASE_STYLE,
                "t",
                disabled_reason=None
                if workspace_dir
                else "No held workspace is available",
            ),
            _choice(
                "dismiss",
                "hijack_other",
                "Dismiss",
                "snapshot first, then workspace is released",
                "⌫",
                _RELEASE_STYLE,
                "d",
                disabled_reason=(
                    "already being resolved" if state == "resolving" else None
                ),
            ),
        )
    )
    patch_choice = _patch_choice(app, agent)
    if patch_choice is not None:
        choices.append(patch_choice)
    return tuple(choices)


def _choice(
    action: str,
    section: str,
    label: str,
    detail: str | None,
    glyph: str,
    glyph_style: str,
    hotkey: str,
    *,
    pending: bool = False,
    disabled_reason: str | None = None,
) -> AgentActionChoice:
    return AgentActionChoice(
        result=f"{RESULT_PREFIX}{action}",
        section=section,  # type: ignore[arg-type]
        label=label,
        detail=detail,
        glyph=glyph,
        glyph_style=glyph_style,
        badge=None,
        badge_style=None,
        age=None,
        hotkey=hotkey,
        disabled_reason=disabled_reason,
        pending=pending,
        inline_detail=True,
    )


def _patch_choice(app: Any, agent: Agent) -> AgentActionChoice | None:
    resolver = getattr(app, "_resolve_agent_cl_name", None)
    if not callable(resolver):
        return None
    try:
        patch_name = resolver(agent)
    except Exception:
        return None
    if not patch_name:
        return None
    summary_resolver = getattr(app, "_find_agent_enter_patch_summary", None)
    try:
        summary = summary_resolver(patch_name) if callable(summary_resolver) else None
    except Exception:
        summary = None
    from ._agent_enter_builders import patch_target
    from ._agent_enter_action import choice_for_enter_target

    target = patch_target(
        patch_name=patch_name,
        project_file=getattr(agent, "project_file", None),
        summary=summary,
        scope_agent=agent,
    )
    return replace(
        choice_for_enter_target(target),
        hotkey="p",
        inline_detail=True,
        action_target=target.patch_name,
    )


def _title_badge(agent: Agent, record: Mapping[str, Any]) -> str:
    workspace_num = record.get("workspace_num") or getattr(
        agent, "effective_workspace_num", None
    )
    badge = "HIJACKED"
    if isinstance(workspace_num, int) and workspace_num > 0:
        badge += f" · ws #{workspace_num}"
    if str(record.get("state") or "") == "expired" or getattr(
        agent, "hijack_expired", False
    ):
        badge += " · released"
    return badge


def _keep_subtitle(record: Mapping[str, Any]) -> str:
    workspace_num = record.get("workspace_num")
    if isinstance(workspace_num, int) and workspace_num > 0:
        return f"next turn runs in workspace #{workspace_num}"
    return "next turn uses the held workspace"


def _header_from_record(record: Mapping[str, Any]) -> Text:
    provider = text_value(record.get("provider"))
    model = text_value(record.get("model"))
    effort = text_value(record.get("effort"))
    model_display = (
        "/".join(item for item in (provider, model) if item) or "unknown model"
    )
    if effort:
        model_display += f"@{effort}"
    alias = text_value(record.get("model_alias"))
    if alias:
        try:
            from sase.agent.hijack.core import normalize_hijack_rung

            alias = normalize_hijack_rung(alias)
        except Exception:
            pass
    run_duration = duration(record.get("run_duration_seconds"))
    hijacked_age = age(record.get("hijacked_at"))
    first_parts = [model_display]
    if alias:
        first_parts.append(f"via {alias}")
    if run_duration:
        first_parts.append(f"ran {run_duration}")
    if hijacked_age:
        first_parts.append(f"hijacked {hijacked_age}")
    header = Text(" · ".join(first_parts) + "\n")
    files, insertions, deletions = diff_totals(record)
    second_parts = []
    if files:
        second_parts.append(f"{files} files +{insertions} −{deletions}")
    repo_diffs = record.get("repo_diffs")
    linked_repos = (
        {
            text_value(item.get("repo"))
            for item in repo_diffs
            if isinstance(item, Mapping) and item.get("repo")
        }
        if isinstance(repo_diffs, list)
        else set()
    )
    if linked_repos:
        second_parts.append(f"{len(linked_repos)} linked repo")
    last_tool = text_value(record.get("last_tool"))
    last_tool_age = duration(record.get("last_tool_age_seconds"))
    if last_tool:
        second_parts.append(
            f"last tool: {last_tool}" + (f" ({last_tool_age})" if last_tool_age else "")
        )
    header.append(" · ".join(second_parts) or "Recovery snapshot is held", style="dim")
    return header


def _open_recovery_diff(app: Any, agent: Agent, record: Mapping[str, Any]) -> None:
    identity = tuple(agent.identity)

    async def _load() -> None:
        try:
            document = await asyncio.to_thread(
                _build_recovery_diff_document, agent, record
            )
        except Exception as exc:  # noqa: BLE001 - pager action reports a concise failure.
            app.notify(f"Could not build recovery diff: {exc}", severity="warning")
            return
        current = agent_by_identity(app, identity)
        if current is None:
            return
        from sase.pager.screen import PagerScreen

        app.push_screen(PagerScreen(document, links_enabled=True))

    from ...util.pump_tasks import spawn_pump_free_task

    if (
        spawn_pump_free_task(
            app,
            _load(),
            name="sase-hijack-recovery-diff",
            registry_attr="_agent_enter_async_tasks",
        )
        is None
    ):
        app.notify("Recovery diff is unavailable", severity="warning")


def _build_recovery_diff_document(agent: Agent, record: Mapping[str, Any]) -> Any:
    from sase.pager.document import PagerDocument, PagerSection
    from sase.pager.link_scan import PagerOrigin

    snapshots = record.get("snapshots")
    roots = (
        [
            (str(item.get("repo")), str(item.get("reference") or ""))
            for item in snapshots
            if isinstance(item, Mapping) and isinstance(item.get("repo"), str)
        ]
        if isinstance(snapshots, list)
        else []
    )
    sections: list[PagerSection] = []
    for repo, reference in roots:
        diff = _live_repository_diff(repo)
        if not diff:
            diff = (
                "The held workspace has no newer live diff.\n"
                f"Saved recovery snapshot: {reference or 'reference unavailable'}\n"
            )
        sections.append(
            PagerSection(
                identity=f"recovery-diff-{len(sections)}",
                title=Path(repo).name or repo,
                kind="diff",
                body=diff,
            )
        )
    if not sections:
        workspace = str(record.get("workspace_dir") or agent.workspace_dir or "")
        diff = _live_repository_diff(workspace) if workspace else ""
        sections.append(
            PagerSection(
                identity="recovery-diff",
                title="WORKSPACE DIFF",
                kind="diff",
                body=diff or "No recovery diff is available.\n",
            )
        )
    return PagerDocument(
        sections=tuple(sections),
        title=f"Recovery diff · {agent.presented_agent_name or agent.agent_name or agent.cl_name}",
        origin=PagerOrigin.DIFF,
    )


def _live_repository_diff(repo: str) -> str:
    path = Path(repo).expanduser()
    if not path.is_dir():
        return ""
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(path),
                "diff",
                "--no-ext-diff",
                "--no-color",
                "--unified=3",
                "HEAD",
                "--",
            ],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=20,
            check=False,
        )
        if result.returncode != 0:
            return ""
        diff = result.stdout
        if len(diff) > 250_000:
            diff = diff[:250_000] + "\n… diff truncated after 250 KB …\n"
        return diff
    except (OSError, subprocess.SubprocessError):
        log.debug("could not read hijack workspace diff for %s", repo, exc_info=True)
        return ""


__all__ = ["open_hijack_recovery_panel"]
