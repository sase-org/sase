"""Plan and apply ``sase agent restart`` without touching ACE/TUI code.

Planning is read-only: every refusal is discovered before anything is killed.
Execution then stops the old row, wipes the reserved name, and launches the
rewritten prompt from the home directory so an untagged prompt cannot inherit
the operator's current workspace.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from sase.agent.force_reuse_launch import ForceReuseLaunchPlan
from sase.agent.names import AgentNameWipePreview, NamedAgent
from sase.agent.running import KillResult
from sase.core.time import get_timezone

NameReuseSource = Literal["prompt", "injected"]

ProgressFn = Callable[[str, str, str], None]

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


class AgentRestartError(Exception):
    """A restart that was refused before any mutation."""

    def __init__(self, *, reason: str, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message
        self.hint = hint


@dataclass(frozen=True)
class AgentRestartPreview:
    """Display facts collected while planning a restart."""

    status: str
    project_display: str
    patch: str | None
    workspace_num: int | None
    pid: int | None
    model: str | None
    provider: str | None
    reasoning_effort: str | None
    model_alias: str | None
    started: str | None
    elapsed: str | None
    family: str | None
    bead: str | None
    prompt_excerpt: str
    target: str
    name_reuse: str
    model_override_label: str | None
    warnings: tuple[str, ...]
    is_live: bool
    has_file_changes: bool


@dataclass(frozen=True)
class AgentRestartPlan:
    """A validated, not-yet-applied named-agent restart."""

    name: str
    lookup_name: str
    presented_name: str
    agent: NamedAgent
    artifacts_dir: Path
    project: str
    meta: dict[str, Any]
    done: dict[str, Any]
    original_prompt: str
    rewritten_prompt: str
    force_reuse_plan: ForceReuseLaunchPlan
    model_override: str | None
    preview: AgentRestartPreview
    name_reuse_source: NameReuseSource
    wipe_preview: AgentNameWipePreview


@dataclass(frozen=True)
class AgentRestartOutcome:
    """Result of applying a restart plan."""

    status: str
    name: str
    stop_action: str
    stop_result: KillResult
    launched_pid: int | None = None
    launched_workspace_num: int | None = None
    launched_artifacts_dir: str | None = None
    error: str | None = None
    recovery_command: str | None = None
    recovery_dir: str | None = None
    recovery_prompt: str | None = None
    renamed_to: str | None = None


def plan_agent_restart(
    name: str,
    *,
    model_override: str | None = None,
) -> AgentRestartPlan:
    """Read the named agent and build a restart plan, or raise."""
    from sase.agent.force_reuse_launch import plan_force_reuse_launch
    from sase.agent.multi_prompt import parse_multi_prompt
    from sase.agent.names import (
        find_named_agent,
        lookup_registered_name,
        preview_agent_name_wipe,
    )
    from sase.agent.relaunch_prompt import (
        KillAndEditPromptError,
        ensure_forced_name_reuse,
        prepare_kill_and_edit_prompt,
    )
    from sase.core.agent_artifact_paths import parse_agent_artifact_path
    from sase.core.agent_identity_facade import present_agent_name
    from sase.project_display_names import (
        humanize_cl_name,
        humanize_vcs_refs_in_text,
        project_display_name_for,
    )
    from sase.xprompt import extract_vcs_workflow_tag, find_vcs_workflow_tag

    agent = find_named_agent(name)
    if agent is None:
        raise AgentRestartError(
            reason="not_found",
            message=f"No agent found with name '{name}'.",
            hint="List agents with `sase agent list -a`.",
        )

    artifacts_dir = Path(agent.artifacts_dir)
    meta = _read_json_dict(artifacts_dir / "agent_meta.json")
    done = _read_json_dict(artifacts_dir / "done.json")
    path_info = parse_agent_artifact_path(artifacts_dir)
    if path_info is None:
        project = artifacts_dir.parent.parent.parent.name
        timestamp = artifacts_dir.name
    else:
        project = path_info.project_name
        timestamp = path_info.timestamp

    raw_path = artifacts_dir / "raw_xprompt.md"
    raw_prompt = _read_raw_prompt(raw_path)
    if raw_prompt is None:
        raise AgentRestartError(
            reason="no_prompt",
            message=(
                f"Agent '{name}' has no raw_xprompt.md, so the CLI cannot "
                "rebuild its launch prompt."
            ),
            hint=(
                "ACE's ,x (kill-and-edit) can still reconstruct a prompt for "
                "historical rows that only have *_prompt.md."
            ),
        )

    segments = parse_multi_prompt(raw_prompt).segments
    if len(segments) > 1:
        raise AgentRestartError(
            reason="multi_segment",
            message=(
                f"Agent '{name}' stored a multi-segment prompt; refusing to "
                "relaunch a fan-out under one name."
            ),
            hint="Relaunch the segments separately, or use ACE's ,x.",
        )

    meta_name = _optional_str(meta.get("name")) or agent.name
    presented_name = present_agent_name(meta_name)
    _refuse_container_name(meta_name, presented_name, lookup_registered_name)
    family_name, role_suffix, is_family_root = _family_rewrite_args(meta)
    try:
        rewritten = prepare_kill_and_edit_prompt(
            raw_prompt,
            meta_name,
            family_name=family_name,
            role_suffix=role_suffix,
            phase_bead_id=_optional_str(meta.get("phase_bead_id")),
            is_family_root=is_family_root,
        )
    except KillAndEditPromptError as exc:
        raise AgentRestartError(
            reason="identity",
            message=str(exc),
            hint=(
                "Fix the stored prompt identity, or relaunch under a new "
                "name with `sase run`."
            ),
        ) from exc
    if model_override:
        from sase.xprompt.directive_edit import set_prompt_model

        rewritten = set_prompt_model(rewritten, model_override)

    force_reuse_plan, rewritten, name_reuse_source = _plan_name_reuse(
        rewritten,
        meta_name=meta_name,
        presented_name=presented_name,
        plan_force_reuse_launch=plan_force_reuse_launch,
        ensure_forced_name_reuse=ensure_forced_name_reuse,
    )
    wipe_preview = preview_agent_name_wipe(meta_name)

    vcs_tag = extract_vcs_workflow_tag(raw_prompt) or find_vcs_workflow_tag(raw_prompt)
    is_live = not agent.is_done
    has_file_changes = bool(
        _optional_str(done.get("diff_path"))
        or _optional_str(meta.get("commit_diff_path"))
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
    original_model = _optional_str(meta.get("model"))
    override_label = None
    if model_override:
        old = original_model or "(none)"
        override_label = f"{old} → {model_override}"

    preview = AgentRestartPreview(
        status=_preview_status(agent, artifacts_dir),
        project_display=project_display_name_for(project),
        patch=_preview_patch(meta, done, humanize_cl_name),
        workspace_num=_workspace_num(project, artifacts_dir, timestamp),
        pid=_display_pid(meta, artifacts_dir),
        model=original_model,
        provider=_optional_str(meta.get("llm_provider")),
        reasoning_effort=_optional_str(meta.get("reasoning_effort")),
        model_alias=_optional_str(meta.get("model_alias")),
        started=_started_label(timestamp, meta),
        elapsed=_elapsed_label(timestamp, meta, done),
        family=_optional_str(meta.get("agent_family")),
        bead=(
            _optional_str(meta.get("phase_bead_id"))
            or _optional_str(meta.get("bead_id"))
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
    return AgentRestartPlan(
        name=meta_name,
        lookup_name=name,
        presented_name=presented_name,
        agent=agent,
        artifacts_dir=artifacts_dir,
        project=project,
        meta=meta,
        done=done,
        original_prompt=raw_prompt,
        rewritten_prompt=rewritten,
        force_reuse_plan=force_reuse_plan,
        model_override=model_override,
        preview=preview,
        name_reuse_source=name_reuse_source,
        wipe_preview=wipe_preview,
    )


def execute_agent_restart(
    plan: AgentRestartPlan,
    *,
    progress: ProgressFn | None = None,
) -> AgentRestartOutcome:
    """Stop the old agent, wipe its name, and relaunch the rewritten prompt."""
    from sase.agent.force_reuse_launch import apply_force_reuse_launch
    from sase.agent.launch_cwd import launch_agents_from_cwd
    from sase.agent.running import dismiss_named_agent, kill_named_agent

    emit = progress or (lambda _step, _status, _detail: None)
    recovery_dir, recovery_command, recovery_prompt = _prepare_recovery(plan, emit)

    if not plan.agent.is_done:
        stop = kill_named_agent(plan.name, exact_name=True)
        stop_action = "killed"
        killed = True
    else:
        stop = dismiss_named_agent(plan.name, exact_name=True)
        stop_action = "dismissed"
        killed = False
    if not stop.success:
        emit("stopped", "fail", stop.message)
        return AgentRestartOutcome(
            status="kill_failed",
            name=plan.name,
            stop_action=stop_action,
            stop_result=stop,
            error=stop.message,
            recovery_command=recovery_command,
            recovery_dir=recovery_dir,
            recovery_prompt=recovery_prompt,
        )
    emit("stopped", "ok", _stopped_detail(stop, plan, killed=killed))

    try:
        apply_force_reuse_launch(plan.force_reuse_plan)
    except Exception as exc:
        emit("name", "fail", str(exc))
        return AgentRestartOutcome(
            status="wipe_failed",
            name=plan.name,
            stop_action=stop_action,
            stop_result=stop,
            error=str(exc),
            recovery_command=recovery_command,
            recovery_dir=recovery_dir,
            recovery_prompt=recovery_prompt,
        )
    emit("name", "ok", f"released '{plan.presented_name}' for reuse")

    try:
        with contextlib.chdir(Path.home()):
            results = launch_agents_from_cwd(
                plan.rewritten_prompt,
                segment_extra_env=plan.force_reuse_plan.segment_envs,
            )
    except Exception as exc:
        emit("launched", "fail", str(exc))
        return _partial_outcome(
            plan,
            stop_action=stop_action,
            stop=stop,
            error=str(exc),
            recovery_command=recovery_command,
            recovery_dir=recovery_dir,
            recovery_prompt=recovery_prompt,
        )
    if not results:
        emit("launched", "fail", "agent launch produced no results")
        return _partial_outcome(
            plan,
            stop_action=stop_action,
            stop=stop,
            error="agent launch produced no results",
            recovery_command=recovery_command,
            recovery_dir=recovery_dir,
            recovery_prompt=recovery_prompt,
        )

    launched = results[0]
    emit("launched", "ok", _launched_detail(launched.pid, launched.workspace_num))
    renamed_to = _renamed_to(plan.name, getattr(launched, "agent_name", None))
    if renamed_to is not None:
        emit("name", "warn", f"launched as '{renamed_to}', not '{plan.name}'")
    return AgentRestartOutcome(
        status="ok",
        name=plan.name,
        stop_action=stop_action,
        stop_result=stop,
        launched_pid=launched.pid,
        launched_workspace_num=launched.workspace_num,
        launched_artifacts_dir=launched.artifacts_dir or None,
        recovery_command=recovery_command,
        recovery_dir=recovery_dir,
        recovery_prompt=recovery_prompt,
        renamed_to=renamed_to,
    )


def restart_needs_confirmation(plan: AgentRestartPlan) -> bool:
    """Return True when a restart is live or the wipe reaches related agents."""
    return plan.preview.is_live or bool(_related_wipe_artifact_dirs(plan))


def _related_wipe_artifact_dirs(plan: AgentRestartPlan) -> tuple[str, ...]:
    """Return wipe artifact dirs that are not the target's own artifacts dir."""
    own = _resolved_path(plan.artifacts_dir)
    return tuple(
        raw for raw in plan.wipe_preview.artifact_dirs if _resolved_path(raw) != own
    )


def related_wipe_warning(
    presented_name: str,
    artifacts_dir: Path,
    wipe_preview: AgentNameWipePreview,
) -> str | None:
    """Describe a wipe that also deletes related agents' artifacts."""
    own = _resolved_path(artifacts_dir)
    related = tuple(
        raw for raw in wipe_preview.artifact_dirs if _resolved_path(raw) != own
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


def _refuse_container_name(
    meta_name: str,
    presented_name: str,
    lookup: Callable[[str], dict[str, Any] | None],
) -> None:
    record = lookup(meta_name)
    if record is None:
        return
    kind = record.get("container_kind")
    if not isinstance(kind, str) or not kind:
        return
    raise AgentRestartError(
        reason="container",
        message=(
            f"'{presented_name}' is a {kind} container; only concrete "
            "members can be restarted."
        ),
        hint=f"Restart a member of the {kind}, not the container name.",
    )


def _plan_name_reuse(
    rewritten: str,
    *,
    meta_name: str,
    presented_name: str,
    plan_force_reuse_launch: Callable[[str], ForceReuseLaunchPlan | None],
    ensure_forced_name_reuse: Callable[[str, str], str],
) -> tuple[ForceReuseLaunchPlan, str, NameReuseSource]:
    force_reuse_plan = _plan_force_reuse(plan_force_reuse_launch, rewritten)
    if force_reuse_plan is not None:
        return force_reuse_plan, rewritten, "prompt"
    if _prompt_fans_out(rewritten):
        raise AgentRestartError(
            reason="fanout",
            message=(
                f"Agent '{presented_name}' stored a fan-out prompt; it has "
                "no single agent to restart."
            ),
            hint="Relaunch the variants separately, or use ACE's ,x.",
        )
    injected = ensure_forced_name_reuse(rewritten, meta_name)
    force_reuse_plan = _plan_force_reuse(plan_force_reuse_launch, injected)
    if force_reuse_plan is None:
        raise AgentRestartError(
            reason="name_not_reusable",
            message=(
                f"Could not establish forced name reuse for agent "
                f"'{presented_name}' after injecting %id."
            ),
            hint="This is an internal restart invariant; retry or use `sase run`.",
        )
    return force_reuse_plan, injected, "injected"


def _plan_force_reuse(
    plan_force_reuse_launch: Callable[[str], ForceReuseLaunchPlan | None],
    prompt: str,
) -> ForceReuseLaunchPlan | None:
    try:
        return plan_force_reuse_launch(prompt)
    except Exception as exc:
        raise AgentRestartError(
            reason="preflight",
            message=str(exc),
            hint="Fix the stored prompt and retry.",
        ) from exc


def _prompt_fans_out(prompt: str) -> bool:
    from sase.xprompt.directives import plan_prompt_fanout_variants

    return plan_prompt_fanout_variants(prompt) is not None


def _prepare_recovery(
    plan: AgentRestartPlan,
    emit: ProgressFn,
) -> tuple[str | None, str | None, str | None]:
    dest = _persist_recovery_bundle(plan)
    if dest is None:
        emit("recovery", "warn", "could not persist a recovery bundle")
        return None, None, plan.rewritten_prompt
    rewritten = dest / "rewritten.md"
    command = f'sase run "$(cat {rewritten})"'
    return str(dest), command, None


def _persist_recovery_bundle(plan: AgentRestartPlan) -> Path | None:
    from sase.core.paths import sase_subdir

    try:
        dest = _new_recovery_dir(plan, sase_subdir("restarts"))
        dest.mkdir(parents=True, exist_ok=True)
        _write_recovery_files(plan, dest)
    except Exception:
        return None
    if not (dest / "rewritten.md").is_file():
        return None
    return dest


def _new_recovery_dir(plan: AgentRestartPlan, root: Path) -> Path:
    stamp = datetime.now(get_timezone()).strftime("%Y%m%d%H%M%S")
    safe = plan.presented_name.replace("/", "-").replace(os.sep, "-")
    dest = root / f"{stamp}-{safe}"
    if dest.exists():
        dest = root / f"{stamp}-{safe}-{os.getpid()}"
    return dest


def _write_recovery_files(plan: AgentRestartPlan, dest: Path) -> None:
    raw_src = plan.artifacts_dir / "raw_xprompt.md"
    if raw_src.is_file():
        shutil.copy2(raw_src, dest / "raw_xprompt.md")
    else:
        (dest / "raw_xprompt.md").write_text(plan.original_prompt, encoding="utf-8")
    (dest / "rewritten.md").write_text(plan.rewritten_prompt, encoding="utf-8")
    meta_src = plan.artifacts_dir / "agent_meta.json"
    if meta_src.is_file():
        shutil.copy2(meta_src, dest / "agent_meta.json")
    else:
        (dest / "agent_meta.json").write_text(
            json.dumps(plan.meta, indent=2) + "\n", encoding="utf-8"
        )
    restarted_at = datetime.now(get_timezone()).isoformat()
    payload = {
        "name": plan.name,
        "project": plan.project,
        "artifacts_dir": str(plan.artifacts_dir),
        "timestamps": {
            "restarted_at": restarted_at,
            "source": plan.artifacts_dir.name,
        },
    }
    (dest / "restart.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )


def _partial_outcome(
    plan: AgentRestartPlan,
    *,
    stop_action: str,
    stop: KillResult,
    error: str,
    recovery_command: str | None,
    recovery_dir: str | None,
    recovery_prompt: str | None,
) -> AgentRestartOutcome:
    return AgentRestartOutcome(
        status="partial",
        name=plan.name,
        stop_action=stop_action,
        stop_result=stop,
        error=error,
        recovery_command=recovery_command,
        recovery_dir=recovery_dir,
        recovery_prompt=recovery_prompt,
    )


def _renamed_to(expected: str, launched_name: object) -> str | None:
    if not isinstance(launched_name, str) or not launched_name:
        return None
    return launched_name if launched_name != expected else None


def _resolved_path(path: Path | str) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def _family_rewrite_args(
    meta: dict[str, Any],
) -> tuple[str | None, str | None, bool]:
    agent_family = _optional_str(meta.get("agent_family"))
    role_suffix = _optional_str(meta.get("role_suffix"))
    is_family_root = (
        meta.get("plan_chain_root") is True or meta.get("agent_family_role") == "root"
    )
    if agent_family and meta.get("agent_family_parallel") is not True and role_suffix:
        return agent_family, role_suffix, is_family_root
    if is_family_root:
        return agent_family, role_suffix, True
    return None, None, False


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
        _optional_str(meta.get("patch_name"))
        or _optional_str(meta.get("cl_name"))
        or _optional_str(meta.get("changespec_name"))
        or _optional_str(done.get("patch_name"))
        or _optional_str(done.get("cl_name"))
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
    running = _read_json_dict(artifacts_dir / "running.json")
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
    finished = _parse_iso(_optional_str(done.get("finished_at")))
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
    iso = _optional_str(meta.get("run_started_at")) or _optional_str(
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


def _stopped_detail(stop: KillResult, plan: AgentRestartPlan, *, killed: bool) -> str:
    bits: list[str] = []
    if killed and stop.pid is not None:
        bits.append(f"killed PID {stop.pid}")
    elif killed:
        bits.append(stop.message)
    else:
        bits.append("dismissed completed row")
    if plan.preview.workspace_num is not None:
        bits.append(f"workspace #{plan.preview.workspace_num} released")
    return " · ".join(bits)


def _launched_detail(pid: int, workspace_num: int) -> str:
    if workspace_num:
        return f"PID {pid} · workspace #{workspace_num}"
    return f"PID {pid}"


def _read_raw_prompt(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    return text if text.strip() else None


def _read_json_dict(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            loaded = json.load(handle)
    except (json.JSONDecodeError, OSError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
