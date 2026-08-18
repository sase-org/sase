"""Build the operator-facing preview for ``sase agent restart``.

Everything here is read-only: it turns a named agent's stored markers into the
display rows, warnings, and deletion labels the CLI prints before asking for
confirmation.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from sase.agent._restart_reads import optional_str, read_json_dict, resolved_path
from sase.agent._restart_types import (
    AgentRestartPlan,
    AgentRestartPreview,
    NameReuseSource,
)
from sase.agent.names import AgentNameWipePreview, NamedAgent
from sase.core.time import get_timezone

_PROMPT_EXCERPT_CHARS = 160
_LIVE_WARNING = "Restarting a running agent discards its in-flight work."
_CHANGES_WARNING = (
    "This run produced file changes; the restart starts from the current "
    "workspace state."
)
_HOME_WARNING = (
    "The stored prompt has no VCS tag; the restart will run as a home agent."
)
_DELETION_NOTE = (
    "The previous run's artifacts are deleted; the chat transcript under "
    "~/.sase/chats is kept."
)


def build_restart_preview(
    *,
    agent: NamedAgent,
    artifacts_dir: Path,
    project: str,
    timestamp: str,
    meta: dict[str, Any],
    done: dict[str, Any],
    raw_prompt: str,
    vcs_tag: str | None,
    presented_name: str,
    name_reuse_source: NameReuseSource,
    model_override: str | None,
    wipe_preview: AgentNameWipePreview,
) -> AgentRestartPreview:
    """Collect the display facts a planned restart shows before applying."""
    from sase.project_display_names import (
        humanize_cl_name,
        humanize_vcs_refs_in_text,
        project_display_name_for,
    )

    is_live = not agent.is_done
    has_file_changes = bool(
        optional_str(done.get("diff_path"))
        or optional_str(meta.get("commit_diff_path"))
    )
    warnings = _preview_warnings(
        is_live=is_live,
        has_file_changes=has_file_changes,
        project=project,
        vcs_tag=vcs_tag,
    )
    related_warning = related_wipe_warning(presented_name, artifacts_dir, wipe_preview)
    if related_warning:
        warnings = (*warnings, related_warning)
    reuse_label = "injected" if name_reuse_source == "injected" else "from prompt"
    original_model = optional_str(meta.get("model"))
    override_label = None
    if model_override:
        old = original_model or "(none)"
        override_label = f"{old} → {model_override}"

    return AgentRestartPreview(
        status=_preview_status(agent, artifacts_dir),
        project_display=project_display_name_for(project),
        patch=_preview_patch(meta, done, humanize_cl_name),
        workspace_num=_workspace_num(project, artifacts_dir, timestamp),
        pid=_display_pid(meta, artifacts_dir),
        model=original_model,
        provider=optional_str(meta.get("llm_provider")),
        reasoning_effort=optional_str(meta.get("reasoning_effort")),
        model_alias=optional_str(meta.get("model_alias")),
        started=_started_label(timestamp, meta),
        elapsed=_elapsed_label(timestamp, meta, done),
        family=optional_str(meta.get("agent_family")),
        bead=(
            optional_str(meta.get("phase_bead_id")) or optional_str(meta.get("bead_id"))
        ),
        prompt_excerpt=_prompt_excerpt(
            humanize_vcs_refs_in_text(raw_prompt),
            _PROMPT_EXCERPT_CHARS,
        ),
        target=(
            humanize_vcs_refs_in_text(vcs_tag)
            if vcs_tag
            else "home (prompt has no VCS tag)"
        ),
        name_reuse=f"forced (%id(!{presented_name})) · {reuse_label}",
        model_override_label=override_label,
        warnings=warnings,
        is_live=is_live,
        has_file_changes=has_file_changes,
    )


def restart_needs_confirmation(plan: AgentRestartPlan) -> bool:
    """Return True when a restart is live or the wipe reaches related agents."""
    return plan.preview.is_live or bool(_related_wipe_artifact_dirs(plan))


def related_wipe_warning(
    presented_name: str,
    artifacts_dir: Path,
    wipe_preview: AgentNameWipePreview,
) -> str | None:
    """Describe a wipe that also deletes related agents' artifacts."""
    own = resolved_path(artifacts_dir)
    related = tuple(
        raw for raw in wipe_preview.artifact_dirs if resolved_path(raw) != own
    )
    if not related:
        return None
    count = len(related)
    noun = "agent's" if count == 1 else "agents'"
    return (
        f"Releasing '{presented_name}' also deletes {count} related "
        f"{noun} artifacts: {', '.join(related)}."
    )


def deletion_note() -> str:
    """Standing note that artifacts go away and the chat transcript stays."""
    return _DELETION_NOTE


def wipe_deletes_label(wipe_preview: AgentNameWipePreview) -> str:
    """Return the preview ``Deletes`` row value for *wipe_preview*."""
    dir_count = len(wipe_preview.artifact_dirs)
    bundle_count = len(wipe_preview.bundle_paths)
    dir_word = "dir" if dir_count == 1 else "dirs"
    bundle_word = "bundle" if bundle_count == 1 else "bundles"
    summary = f"{dir_count} artifact {dir_word} · {bundle_count} {bundle_word}"
    paths = [*wipe_preview.artifact_dirs, *wipe_preview.bundle_paths]
    if not paths:
        return summary
    shown = paths[:3]
    extra = len(paths) - 3
    listed = ", ".join(shown)
    if extra > 0:
        listed = f"{listed} +{extra} more"
    return f"{summary} · {listed}"


def _related_wipe_artifact_dirs(plan: AgentRestartPlan) -> tuple[str, ...]:
    """Return wipe artifact dirs that are not the target's own artifacts dir."""
    own = resolved_path(plan.artifacts_dir)
    return tuple(
        raw for raw in plan.wipe_preview.artifact_dirs if resolved_path(raw) != own
    )


def _preview_warnings(
    *,
    is_live: bool,
    has_file_changes: bool,
    project: str,
    vcs_tag: str | None,
) -> tuple[str, ...]:
    warnings: list[str] = []
    if is_live:
        warnings.append(_LIVE_WARNING)
    if has_file_changes:
        warnings.append(_CHANGES_WARNING)
    if project != "home" and not vcs_tag:
        warnings.append(_HOME_WARNING)
    return tuple(warnings)


def _preview_status(agent: NamedAgent, artifacts_dir: Path) -> str:
    if agent.is_done:
        return "FAILED" if agent.outcome == "failed" else "DONE"
    if (artifacts_dir / "waiting.json").exists():
        return "WAITING"
    return "RUNNING"


def _preview_patch(
    meta: dict[str, Any],
    done: dict[str, Any],
    humanize: Callable[[str], str],
) -> str | None:
    raw = (
        optional_str(meta.get("patch_name"))
        or optional_str(meta.get("cl_name"))
        or optional_str(meta.get("changespec_name"))
        or optional_str(done.get("patch_name"))
        or optional_str(done.get("cl_name"))
    )
    return humanize(raw) if raw else None


def _workspace_num(
    project: str,
    artifacts_dir: Path,
    timestamp: str,
) -> int | None:
    if project == "home":
        return None
    from sase.ace.patch.project_spec_path import preferred_project_spec_path
    from sase.running_field import get_claimed_workspaces

    project_dir = artifacts_dir
    while project_dir.name != project and project_dir.parent != project_dir:
        project_dir = project_dir.parent
    project_file = preferred_project_spec_path(str(project_dir), project)
    try:
        for claim in get_claimed_workspaces(project_file):
            if claim.artifacts_timestamp == timestamp:
                return claim.workspace_num
    except Exception:
        return None
    return None


def _display_pid(meta: dict[str, Any], artifacts_dir: Path) -> int | None:
    pid = _valid_pid(meta.get("pid"))
    if pid is not None:
        return pid
    running = read_json_dict(artifacts_dir / "running.json")
    return _valid_pid(running.get("pid"))


def _valid_pid(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value > 1 else None


def _started_label(timestamp: str, meta: dict[str, Any]) -> str | None:
    from sase.notifications.models import format_relative_time

    started = _parse_started(timestamp, meta)
    if started is None:
        return timestamp or None
    return format_relative_time(started.isoformat())


def _elapsed_label(
    timestamp: str,
    meta: dict[str, Any],
    done: dict[str, Any],
) -> str | None:
    started = _parse_started(timestamp, meta)
    if started is None:
        return None
    finished = _parse_iso(optional_str(done.get("finished_at")))
    end = finished or datetime.now(get_timezone())
    seconds = int(max(0.0, (end - started).total_seconds()))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}h{minutes}m"
    if minutes > 0:
        return f"{minutes}m{secs}s"
    return f"{secs}s"


def _parse_started(timestamp: str, meta: dict[str, Any]) -> datetime | None:
    iso = optional_str(meta.get("run_started_at")) or optional_str(
        meta.get("started_at")
    )
    parsed = _parse_iso(iso)
    if parsed is not None:
        return parsed
    try:
        return datetime.strptime(timestamp, "%Y%m%d%H%M%S").replace(
            tzinfo=get_timezone()
        )
    except ValueError:
        return None


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=get_timezone())
    return parsed


def _prompt_excerpt(text: str, limit: int) -> str:
    single_line = text.replace("\n", " ").strip()
    if len(single_line) <= limit:
        return single_line
    return single_line[: max(limit - 1, 1)] + "…"
