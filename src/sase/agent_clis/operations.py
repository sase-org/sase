"""Shared, presentation-free plan/execute pipeline for agent-CLI updates."""

from __future__ import annotations

import difflib
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from typing import Any

from sase.llm_provider import registry as llm_registry
from sase.plugins.latest import is_newer

from .detect import detect_agent_cli_statuses, probe_version
from .history import RecordFn, record_agent_cli_update_run
from .latest import DEFAULT_JSON_FIELD, LatestQuery, LatestVersion, get_latest_versions
from .models import (
    AgentCliNothingToUpdate,
    AgentCliStatus,
    AgentCliUnknownName,
    AgentCliUpdateEntry,
    AgentCliUpdatePlan,
    AgentCliUpdateResult,
    AgentCliUpdatesReady,
    InstallMethod,
    UpdateResultStatus,
    UpdateStrategy,
    UpdateTrigger,
    VersionCompare,
)
from .runner import AgentCliRunnerError, CommandResult, run_command

RunnerFn = Callable[..., CommandResult]
LatestFn = Callable[..., dict[str, LatestVersion]]
StatusFn = Callable[..., tuple[AgentCliStatus, ...]]


def collect_agent_cli_statuses(
    *,
    refresh: bool = False,
    offline: bool = False,
    env: Mapping[str, str] | None = None,
    metadata_payload: Mapping[str, Any] | None = None,
    run_fn: RunnerFn = run_command,
    latest_fn: LatestFn = get_latest_versions,
) -> tuple[AgentCliStatus, ...]:
    """Return detected CLIs enriched with cached/remote latest versions."""
    providers = _provider_metadata(metadata_payload)
    detected = detect_agent_cli_statuses(providers, env=env, run_fn=run_fn)
    queries = {
        status.name: query
        for status in detected
        if (query := _latest_query(status)) is not None
    }
    latest = latest_fn(tuple(queries.values()), offline=offline, refresh=refresh)
    enriched: list[AgentCliStatus] = []
    for status in detected:
        query = queries.get(status.name)
        info = latest.get(query.key) if query is not None else None
        latest_version = info.version if info is not None else None
        enriched.append(
            replace(
                status,
                latest_version=latest_version,
                update_available=_update_available(status, latest_version),
                latest_error=info.error if info is not None else None,
            )
        )
    return tuple(enriched)


def _latest_query(status: AgentCliStatus) -> LatestQuery | None:
    """Build the latest-version lookup a status declares, if any.

    A declared JSON endpoint wins over an npm package: a CLI distributed by a
    version channel is not meaningfully described by its npm mirror.
    """
    if status.latest_version_url:
        return LatestQuery.for_url(
            status.latest_version_url,
            field=status.latest_version_json_field or DEFAULT_JSON_FIELD,
        )
    if status.latest_version_package:
        return LatestQuery.for_npm(status.latest_version_package)
    return None


def _update_available(status: AgentCliStatus, latest_version: str | None) -> bool:
    """Compare versions with the comparator the provider declared.

    ``exact`` exists for channel-pinned distributions whose release ids are not
    valid PEP 440 versions — ``is_newer`` silently answers ``False`` for those,
    which would report "no known updates" forever.
    """
    if status.version_compare is VersionCompare.EXACT:
        return (
            latest_version is not None
            and status.installed_version is not None
            and latest_version != status.installed_version
        )
    return is_newer(latest_version, status.installed_version)


def detect_agent_cli_statuses_for_names(
    names: Sequence[str],
    *,
    env: Mapping[str, str] | None = None,
    metadata_payload: Mapping[str, Any] | None = None,
    run_fn: RunnerFn = run_command,
) -> tuple[AgentCliStatus, ...]:
    """Locally detect only the named providers, without latest-version work.

    The empty-name fast path intentionally precedes registry inspection.  This
    is the bounded detector used to revalidate durable update candidates.
    """
    wanted = frozenset(name for name in names if name)
    if not wanted:
        return ()
    providers = {
        name: metadata
        for name, metadata in _provider_metadata(metadata_payload).items()
        if name in wanted
    }
    return detect_agent_cli_statuses(providers, env=env, run_fn=run_fn)


def _provider_metadata(
    metadata_payload: Mapping[str, Any] | None,
) -> dict[str, Mapping[str, Any]]:
    payload = (
        llm_registry.get_llm_metadata_payload()
        if metadata_payload is None
        else metadata_payload
    )
    raw_providers = payload.get("providers")
    if not isinstance(raw_providers, Mapping):
        return {}
    return {
        str(name): metadata
        for name, metadata in raw_providers.items()
        if isinstance(metadata, Mapping)
        and metadata.get("hidden_from_agent_cli_management") is not True
    }


def plan_agent_cli_updates(
    names: Sequence[str] | None = None,
    *,
    all_clis: bool = False,
    refresh: bool = False,
    offline: bool = False,
    status_fn: StatusFn = collect_agent_cli_statuses,
) -> AgentCliUpdatePlan:
    """Plan exact commands and skips without mutating any agent CLI."""
    statuses = status_fn(refresh=refresh, offline=offline)
    if all_clis:
        selected = statuses
    else:
        resolved: list[AgentCliStatus] = []
        for query in names or ():
            status = find_agent_cli_status(statuses, query)
            if status is None:
                known = tuple(item.name for item in statuses)
                return AgentCliUnknownName(
                    query=query,
                    known_names=known,
                    suggestions=tuple(
                        difflib.get_close_matches(query, known, n=3, cutoff=0.4)
                    ),
                )
            if status not in resolved:
                resolved.append(status)
        selected = tuple(resolved)

    entries = tuple(plan_agent_cli_status(status) for status in selected)
    if any(entry.ready for entry in entries):
        return AgentCliUpdatesReady(entries=entries, all_clis=all_clis)
    return AgentCliNothingToUpdate(entries=entries, all_clis=all_clis)


def execute_agent_cli_updates(
    plan: AgentCliUpdatesReady | AgentCliNothingToUpdate,
    *,
    run_fn: RunnerFn = run_command,
    trigger: UpdateTrigger = UpdateTrigger.UNKNOWN,
    record_fn: RecordFn | None = record_agent_cli_update_run,
) -> tuple[AgentCliUpdateResult, ...]:
    """Execute a plan sequentially and re-probe versions after successes."""
    started_at = time.monotonic()
    results: list[AgentCliUpdateResult] = []
    for entry in plan.entries:
        status = entry.status
        if entry.argv is None:
            result_status = (
                UpdateResultStatus.ALREADY_CURRENT
                if _already_current(entry)
                else UpdateResultStatus.SKIPPED
            )
            results.append(
                AgentCliUpdateResult(
                    name=status.name,
                    display_name=status.display_name,
                    status=result_status,
                    old_version=status.installed_version,
                    new_version=status.installed_version,
                    command=None,
                    docs_url=status.docs_url,
                    suggested_command=entry.manual_argv,
                    reason=entry.skip_reason,
                )
            )
            continue

        try:
            command_result = run_fn(entry.argv, env_overlay=dict(entry.env_overlay))
        except AgentCliRunnerError as exc:
            results.append(
                AgentCliUpdateResult(
                    name=status.name,
                    display_name=status.display_name,
                    status=UpdateResultStatus.FAILED,
                    old_version=status.installed_version,
                    new_version=status.installed_version,
                    command=entry.argv,
                    docs_url=status.docs_url,
                    env_overlay=entry.env_overlay,
                    reason=reason_with_docs(str(exc), status.docs_url),
                )
            )
            continue

        output_tail = command_output_tail(command_result.output)
        if command_result.returncode != 0:
            results.append(
                AgentCliUpdateResult(
                    name=status.name,
                    display_name=status.display_name,
                    status=UpdateResultStatus.FAILED,
                    old_version=status.installed_version,
                    new_version=status.installed_version,
                    command=entry.argv,
                    docs_url=status.docs_url,
                    env_overlay=entry.env_overlay,
                    elapsed=command_result.elapsed,
                    reason=reason_with_docs(
                        f"command failed with exit {command_result.returncode}",
                        status.docs_url,
                    ),
                    output_tail=output_tail,
                )
            )
            continue

        reprobe = (
            probe_version(
                status.executable,
                version_argv=status.version_argv,
                version_regex=status.version_regex,
                run_fn=run_fn,
            )
            if status.executable
            else None
        )
        new_version = reprobe.version if reprobe is not None else None
        unchanged = (
            status.installed_version is not None
            and new_version == status.installed_version
        )
        result_status = (
            UpdateResultStatus.ALREADY_CURRENT
            if unchanged
            else UpdateResultStatus.UPDATED
        )
        reason = (
            reason_with_docs(
                f"post-update version probe failed: {reprobe.error}",
                status.docs_url,
            )
            if reprobe is not None and reprobe.error
            else None
        )
        results.append(
            AgentCliUpdateResult(
                name=status.name,
                display_name=status.display_name,
                status=result_status,
                old_version=status.installed_version,
                new_version=new_version,
                command=entry.argv,
                docs_url=status.docs_url,
                env_overlay=entry.env_overlay,
                elapsed=command_result.elapsed,
                reason=reason,
                output_tail=output_tail,
            )
        )
    completed_results = tuple(results)
    if record_fn is not None:
        record_fn(
            completed_results,
            trigger=trigger,
            elapsed=time.monotonic() - started_at,
        )
    return completed_results


def plan_agent_cli_status(status: AgentCliStatus) -> AgentCliUpdateEntry:
    """Project one live status into the shared safe/manual update plan."""
    docs_url = status.docs_url
    if status.install_method is InstallMethod.NOT_INSTALLED:
        return AgentCliUpdateEntry(
            status,
            UpdateStrategy.NONE,
            None,
            reason_with_docs(f"not installed; {status.install_hint}", docs_url),
        )
    if status.install_method is InstallMethod.BUNDLED:
        return AgentCliUpdateEntry(
            status,
            UpdateStrategy.NONE,
            None,
            "bundled with SASE; update it with `sase update`",
        )
    if (
        status.latest_version is not None
        and status.installed_version is not None
        and not status.update_available
    ):
        return AgentCliUpdateEntry(
            status,
            UpdateStrategy.NONE,
            None,
            reason_with_docs("already up to date", docs_url),
        )
    if status.install_method is InstallMethod.NPM and status.package:
        argv = ("npm", "install", "-g", f"{status.package}@latest")
        if status.npm_root_writable is False:
            command = " ".join(argv)
            return AgentCliUpdateEntry(
                status,
                UpdateStrategy.MANUAL,
                None,
                reason_with_docs(
                    f"npm global root is not writable; run `{command}` manually "
                    "with an npm setup owned by your user (SASE never uses sudo)",
                    docs_url,
                ),
                manual_argv=argv,
            )
        return AgentCliUpdateEntry(status, UpdateStrategy.NPM, argv)
    if status.install_method is InstallMethod.HOMEBREW:
        manual = (
            ("brew", "upgrade", status.brew_package) if status.brew_package else None
        )
        detail = "Homebrew installs require a manual upgrade"
        if manual:
            detail += f": `{' '.join(manual)}`"
        return AgentCliUpdateEntry(
            status,
            UpdateStrategy.MANUAL,
            None,
            reason_with_docs(detail, docs_url),
            manual_argv=manual,
        )
    if (
        status.install_method is InstallMethod.SELF_MANAGED
        and status.executable
        and status.self_update_argv
    ):
        return AgentCliUpdateEntry(
            status,
            UpdateStrategy.SELF_UPDATE,
            (status.executable, *status.self_update_argv),
            env_overlay=status.self_update_env,
        )
    return AgentCliUpdateEntry(
        status,
        UpdateStrategy.MANUAL,
        None,
        reason_with_docs(
            "install method is unknown; SASE will not guess an update command",
            docs_url,
        ),
    )


def find_agent_cli_status(
    statuses: Sequence[AgentCliStatus], query: str
) -> AgentCliStatus | None:
    """Resolve one user-supplied name against provider, binary, or display name."""
    key = _name_key(query)
    for status in statuses:
        if key in {
            _name_key(status.name),
            _name_key(status.binary),
            _name_key(status.display_name),
        }:
            return status
    return None


def _name_key(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _already_current(entry: AgentCliUpdateEntry) -> bool:
    return bool(entry.skip_reason and "already up to date" in entry.skip_reason)


def reason_with_docs(reason: str, docs_url: str | None) -> str:
    """Append a provider's canonical docs URL to a reason exactly once."""
    if not docs_url or docs_url in reason:
        return reason
    return f"{reason}. See {docs_url}"


def command_output_tail(
    output: str, *, lines: int = 20, chars: int = 2000
) -> str | None:
    """Return the tail of a command's combined output, or ``None`` if empty."""
    if not output.strip():
        return None
    tail = "\n".join(output.strip().splitlines()[-lines:])
    return tail[-chars:]


# ``list`` is intentionally an alias over the same shared detection path used
# by planning; CLI and TUI callers should not build their own status inventory.
list_agent_clis = collect_agent_cli_statuses


__all__ = [
    "collect_agent_cli_statuses",
    "command_output_tail",
    "detect_agent_cli_statuses_for_names",
    "execute_agent_cli_updates",
    "find_agent_cli_status",
    "list_agent_clis",
    "plan_agent_cli_status",
    "plan_agent_cli_updates",
    "reason_with_docs",
]
