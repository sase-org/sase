"""Recovery-panel view models and actions for hijacked agent rows."""

from __future__ import annotations

import asyncio
import logging
import subprocess
import threading
from collections import OrderedDict
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

log = logging.getLogger(__name__)

_KEEP_STYLE = "bold #FF5FAF"
_RELEASE_STYLE = "#8787AF"
_RESULT_PREFIX = "hijack:"
_PREVIEW_CACHE_MAX = 64
_preview_lock = threading.Lock()
_preview_cache: OrderedDict[tuple[str, int], Any] = OrderedDict()


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
        f"{_RESULT_PREFIX}escalate"
        if any(choice.result == f"{_RESULT_PREFIX}escalate" for choice in choices)
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
        current = _agent_by_identity(app, identity) or agent
        choice = next((item for item in modal.choices if item.result == result), None)
        if choice is not None and choice.section == "patch":
            patch_name = choice.action_target
            if not patch_name:
                app.notify("No Patch for this agent", severity="warning")
                return
            from ._notification_navigation import navigate_to_patch_tab

            navigate_to_patch_tab(app, patch_name, current.project_file or "")
            return
        if result == f"{_RESULT_PREFIX}instruct":
            from ._hijack_prompt_bar import open_hijack_instruct_bar

            open_hijack_instruct_bar(app, current, dict(record))
            return
        if result == f"{_RESULT_PREFIX}edit":
            from ._hijack_prompt_bar import open_hijack_edit_bar

            open_hijack_edit_bar(app, current, dict(record))
            return
        if result == f"{_RESULT_PREFIX}view":
            _open_recovery_diff(app, current, record)
            return
        if result == f"{_RESULT_PREFIX}shell":
            opener = getattr(app, "_open_agent_tmux_window", None)
            if callable(opener):
                opener(use_primary=False)
            else:
                app.notify("Workspace shell is unavailable", severity="warning")
            return
        action = result.removeprefix(_RESULT_PREFIX)
        if action not in {"escalate", "continue", "restart", "dismiss"}:
            return
        target = _target_from_choice(choice)
        _submit_recovery_action(
            app,
            current,
            record,
            action=action,
            model=target if action in {"escalate", "continue"} else None,
        )

    app.push_screen(modal, _on_choice)
    _schedule_preview(app, modal, record)


def dismiss_hijacked_agent(app: Any, agent: Agent) -> bool:
    """Dismiss a HIJACKED row through its snapshot-gated durable proc."""
    record = getattr(agent, "hijack_record", None)
    if not isinstance(record, Mapping):
        app.notify(
            "Recovery details are unavailable; refresh the Agents tab",
            severity="warning",
        )
        return False
    return _submit_recovery_action(app, agent, dict(record), action="dismiss")


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
        result=f"{_RESULT_PREFIX}{action}",
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
    provider = _text_value(record.get("provider"))
    model = _text_value(record.get("model"))
    effort = _text_value(record.get("effort"))
    model_display = (
        "/".join(item for item in (provider, model) if item) or "unknown model"
    )
    if effort:
        model_display += f"@{effort}"
    alias = _text_value(record.get("model_alias"))
    if alias:
        try:
            from sase.agent.hijack.core import normalize_hijack_rung

            alias = normalize_hijack_rung(alias)
        except Exception:
            pass
    run_duration = _duration(record.get("run_duration_seconds"))
    hijacked_age = _age(record.get("hijacked_at"))
    first_parts = [model_display]
    if alias:
        first_parts.append(f"via {alias}")
    if run_duration:
        first_parts.append(f"ran {run_duration}")
    if hijacked_age:
        first_parts.append(f"hijacked {hijacked_age}")
    header = Text(" · ".join(first_parts) + "\n")
    files, insertions, deletions = _diff_totals(record)
    second_parts = []
    if files:
        second_parts.append(f"{files} files +{insertions} −{deletions}")
    repo_diffs = record.get("repo_diffs")
    linked_repos = (
        {
            _text_value(item.get("repo"))
            for item in repo_diffs
            if isinstance(item, Mapping) and item.get("repo")
        }
        if isinstance(repo_diffs, list)
        else set()
    )
    if linked_repos:
        second_parts.append(f"{len(linked_repos)} linked repo")
    last_tool = _text_value(record.get("last_tool"))
    last_tool_age = _duration(record.get("last_tool_age_seconds"))
    if last_tool:
        second_parts.append(
            f"last tool: {last_tool}" + (f" ({last_tool_age})" if last_tool_age else "")
        )
    header.append(" · ".join(second_parts) or "Recovery snapshot is held", style="dim")
    return header


def _preview_header(
    header: Mapping[str, Any], record: Mapping[str, Any] | None = None
) -> Text:
    model = _text_value(header.get("model_display")) or "unknown model"
    parts = [model]
    alias = _text_value((record or {}).get("model_alias"))
    if alias:
        try:
            from sase.agent.hijack.core import normalize_hijack_rung

            alias = normalize_hijack_rung(alias)
        except Exception:
            pass
        parts.append(f"via {alias}")
    run_duration = _text_value(header.get("run_duration_display"))
    age = _text_value(header.get("hijacked_ago"))
    if run_duration:
        parts.append(f"ran {run_duration}")
    if age:
        parts.append(f"hijacked {age}")
    result = Text(" · ".join(parts) + "\n")
    files = _int_value(header.get("files_changed"))
    insertions = _int_value(header.get("insertions"))
    deletions = _int_value(header.get("deletions"))
    details = []
    if files:
        details.append(f"{files} files +{insertions} −{deletions}")
    tool = _text_value(header.get("last_tool"))
    tool_age = _text_value(header.get("last_tool_age"))
    if tool:
        details.append(f"last tool: {tool}" + (f" ({tool_age})" if tool_age else ""))
    result.append(" · ".join(details) or "Recovery snapshot is held", style="dim")
    return result


def _schedule_preview(
    app: Any,
    modal: AgentActionChooserModal,
    record: Mapping[str, Any],
) -> None:
    async def _load() -> None:
        try:
            preview = await asyncio.to_thread(_cached_preview_for_record, dict(record))
            error: str | None = None
        except Exception as exc:  # noqa: BLE001 - preview refusal is a disabled-row reason.
            preview = None
            error = str(exc) or "Could not compute recovery preview"
        if not modal.is_mounted:
            return
        if preview is None:
            choices = tuple(
                AgentActionChoice(
                    **{
                        **choice.__dict__,
                        "pending": False,
                        "disabled_reason": error,
                        "detail": None,
                    }
                )
                if choice.pending
                else choice
                for choice in modal.choices
            )
            modal.update_choices(choices, primary_result="")
            return
        choices = _apply_preview(modal.choices, preview)
        primary = None
        for action_name in ("escalate", "continue"):
            action = preview.action(action_name)
            if preview.state == "held" and action is not None and action.available:
                primary = f"{_RESULT_PREFIX}{action_name}"
                break
        if primary is None:
            primary = ""
        selected = None
        if modal.choices and modal.selected_index == 0:
            selected = primary
        modal.update_choices(
            choices,
            primary_result=primary,
            selected_result=selected,
        )
        modal.update_header(_preview_header(preview.header, record))

    from ...util.pump_tasks import spawn_pump_free_task

    task = spawn_pump_free_task(
        app,
        _load(),
        name="sase-hijack-recovery-preview",
        registry_attr="_agent_enter_async_tasks",
    )
    if task is None:
        modal.update_choices(
            tuple(
                AgentActionChoice(
                    **{
                        **choice.__dict__,
                        "pending": False,
                        "disabled_reason": "Recovery preview is unavailable",
                        "detail": None,
                    }
                )
                if choice.pending
                else choice
                for choice in modal.choices
            ),
            primary_result="",
        )


def _cached_preview_for_record(record: dict[str, Any]) -> Any:
    from sase.agent.hijack.preview import hijack_recovery_preview

    hijack_id = str(record.get("hijack_id") or "")
    revision = _int_value(record.get("revision"))
    key = (hijack_id, revision)
    with _preview_lock:
        cached = _preview_cache.get(key)
        if cached is not None:
            _preview_cache.move_to_end(key)
            return cached
    preview = hijack_recovery_preview(record)
    with _preview_lock:
        _preview_cache[key] = preview
        _preview_cache.move_to_end(key)
        while len(_preview_cache) > _PREVIEW_CACHE_MAX:
            _preview_cache.popitem(last=False)
    return preview


def _apply_preview(
    choices: tuple[AgentActionChoice, ...], preview: Any
) -> tuple[AgentActionChoice, ...]:
    action_names = {
        "escalate": "escalate",
        "continue": "continue",
        "restart": "restart",
        "edit": "edit",
    }
    updated: list[AgentActionChoice] = []
    for choice in choices:
        action_name = next(
            (
                name
                for suffix, name in action_names.items()
                if choice.result == f"{_RESULT_PREFIX}{suffix}"
            ),
            None,
        )
        if action_name is None:
            updated.append(choice)
            continue
        action = preview.action(action_name)
        if action is None:
            updated.append(
                AgentActionChoice(
                    **{
                        **choice.__dict__,
                        "pending": False,
                        "disabled_reason": "not available",
                        "detail": None,
                    }
                )
            )
            continue
        detail = _text_value(action.detail)
        target = _text_value(action.target)
        if target and target not in detail:
            detail = f"{detail} · {target}" if detail else target
        glyph = (
            "↔"
            if action_name == "escalate" and "switch" in action.label.lower()
            else choice.glyph
        )
        updated.append(
            AgentActionChoice(
                **{
                    **choice.__dict__,
                    "label": action.label or choice.label,
                    "detail": detail or None,
                    "glyph": glyph,
                    "action_target": target or None,
                    "pending": False,
                    "disabled_reason": None
                    if action.available
                    else (action.reason or "unavailable"),
                }
            )
        )
    return tuple(updated)


def _submit_recovery_action(
    app: Any,
    agent: Agent,
    record: Mapping[str, Any],
    *,
    action: str,
    model: str | None = None,
) -> bool:
    name = str(record.get("agent_name") or agent.agent_name or "")
    hijack_id = str(record.get("hijack_id") or "")
    revision = _int_value(record.get("revision"))
    if not name or not hijack_id:
        app.notify("Recovery record is incomplete", severity="error")
        return False
    if getattr(agent, "hijack_overlay", None) == "recovering":
        app.notify("Recovery is already running for this agent", severity="warning")
        return False

    from ..agent_durable import submit_agent_recovery

    agent.hijack_overlay = "recovering"
    _refresh_hijack_row(app, agent)

    def _complete(completion: Any) -> None:
        current = _agent_by_identity(app, tuple(agent.identity)) or agent
        current.hijack_overlay = None
        current.hijack_record = None
        _refresh_hijack_row(app, current)
        payload = completion.payload if isinstance(completion.payload, Mapping) else {}
        severity = payload.get("severity")
        if severity not in {"information", "warning", "error"}:
            severity = "information" if completion.success else "error"
        message = completion.message or (
            f"Recovery {action} completed"
            if completion.success
            else f"Recovery {action} failed"
        )
        app.notify(message, severity=severity)
        refresh_source = payload.get("schedule_agents_refresh_source")
        refresh = getattr(app, "_schedule_agents_async_refresh", None)
        if isinstance(refresh_source, str) and callable(refresh):
            refresh(source=refresh_source)

    submitted = submit_agent_recovery(
        app,
        name=name,
        hijack_id=hijack_id,
        expected_revision=revision,
        action=action,
        model=model,
        cl_name=agent.cl_name,
        project_file=agent.project_file,
        display_name=f"Recover {agent.display_name or name}",
        on_complete=_complete,
    )
    if not submitted:
        agent.hijack_overlay = None
        _refresh_hijack_row(app, agent)
        app.notify("Could not queue recovery", severity="error")
    return submitted


def _target_from_choice(choice: AgentActionChoice | None) -> str | None:
    if choice is None:
        return None
    if choice.action_target:
        return choice.action_target
    return _text_value(choice.detail).split(" · ")[-1] or None


def _refresh_hijack_row(app: Any, agent: Agent) -> None:
    from ._roster_generation import notify_roster_status_mutation

    notify_roster_status_mutation(app)
    refresh = getattr(app, "_refresh_agents_display", None)
    if callable(refresh):
        refresh(list_changed=False, defer_detail=True)


def _agent_by_identity(app: Any, identity: tuple[object, ...]) -> Agent | None:
    resolver = getattr(app, "_agent_by_identity", None)
    if callable(resolver):
        try:
            found = resolver(identity)
        except Exception:
            found = None
        if isinstance(found, Agent):
            return found
    for row in getattr(app, "_agents_with_children", ()):
        if getattr(row, "identity", None) == identity:
            return row
    return None


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
        current = _agent_by_identity(app, identity)
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


def _diff_totals(record: Mapping[str, Any]) -> tuple[int, int, int]:
    files = insertions = deletions = 0
    diffs = record.get("repo_diffs")
    if isinstance(diffs, list):
        for entry in diffs:
            if not isinstance(entry, Mapping):
                continue
            files += _int_value(entry.get("files_changed"))
            insertions += _int_value(entry.get("insertions"))
            deletions += _int_value(entry.get("deletions"))
    return files, insertions, deletions


def _duration(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return ""
    try:
        seconds = max(0, int(float(value)))
    except (TypeError, ValueError, OverflowError):
        return ""
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m"
    return f"{seconds}s"


def _age(value: object) -> str:
    from datetime import UTC, datetime

    if not isinstance(value, str):
        return ""
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        seconds = max(
            0, int((datetime.now(UTC) - stamp.astimezone(UTC)).total_seconds())
        )
    except (TypeError, ValueError, OverflowError):
        return ""
    return f"{max(1, seconds // 60)}m ago" if seconds >= 60 else "just now"


def _text_value(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _int_value(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return 0


__all__ = ["dismiss_hijacked_agent", "open_hijack_recovery_panel"]
