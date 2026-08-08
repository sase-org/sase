"""Plan and execute provider-declared agent-CLI install scripts.

SASE fetches the installer itself, shows its SHA-256 before running it, and
runs it through the shell-free runner.  It never pipes a URL into a shell and
never edits the user's shell startup files; when the install directory is not
on ``PATH`` it reports the exact line to add and leaves the dotfiles alone.
"""

from __future__ import annotations

import difflib
import hashlib
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from sase.core.paths import get_sase_managed_tmpdir

from .detect import probe_version, resolve_executable
from .history import RecordFn, record_agent_cli_update_run
from .models import (
    AgentCliOperation,
    AgentCliStatus,
    AgentCliUnknownName,
    AgentCliUpdateResult,
    EnvOverlay,
    UpdateResultStatus,
    UpdateTrigger,
)
from .operations import (
    RunnerFn,
    StatusFn,
    collect_agent_cli_statuses,
    command_output_tail,
    find_agent_cli_status,
    reason_with_docs,
)
from .runner import AgentCliRunnerError, run_command

INSTALL_FETCH_TIMEOUT_SECONDS = 30.0
INSTALL_SCRIPT_MAX_BYTES = 1_000_000
INSTALL_SCRIPT_INTERPRETER = "bash"
_HTTPS_SCHEME = "https://"


class _Response(Protocol):
    """The read-with-a-limit slice of an ``http.client.HTTPResponse``."""

    def __enter__(self) -> _Response: ...

    def __exit__(self, *args: object) -> None: ...

    def read(self, amt: int | None = None, /) -> bytes: ...

    def geturl(self) -> str: ...


UrlOpenFn = Callable[..., _Response]
FetchFn = Callable[..., "InstallScript"]


class AgentCliInstallError(Exception):
    """An install script could not be fetched safely."""


@dataclass(frozen=True)
class InstallScript:
    """One fetched installer, kept on disk only for the length of the run."""

    url: str
    path: Path
    digest: str
    size_bytes: int

    def remove(self) -> None:
        """Delete the downloaded script; a missing file is already the goal."""
        self.path.unlink(missing_ok=True)


@dataclass(frozen=True)
class AgentCliInstallEntry:
    """One selected CLI's exact install command, skip reason, or fetch error."""

    status: AgentCliStatus
    argv: tuple[str, ...] | None = None
    env_overlay: EnvOverlay = ()
    script: InstallScript | None = None
    install_dir: str | None = None
    skip_reason: str | None = None
    error: str | None = None

    @property
    def name(self) -> str:
        return self.status.name

    @property
    def ready(self) -> bool:
        return self.argv is not None


@dataclass(frozen=True)
class AgentCliInstallsPlanned:
    """Every selected CLI's install decision, with installers already fetched."""

    entries: tuple[AgentCliInstallEntry, ...]

    @property
    def runnable_entries(self) -> tuple[AgentCliInstallEntry, ...]:
        return tuple(entry for entry in self.entries if entry.ready)

    def cleanup(self) -> None:
        """Remove every fetched installer; callers run this in a ``finally``."""
        for entry in self.entries:
            if entry.script is not None:
                entry.script.remove()


AgentCliInstallPlan = AgentCliInstallsPlanned | AgentCliUnknownName


def fetch_install_script(
    url: str,
    *,
    urlopen_fn: UrlOpenFn = urllib.request.urlopen,
    timeout: float = INSTALL_FETCH_TIMEOUT_SECONDS,
    max_bytes: int = INSTALL_SCRIPT_MAX_BYTES,
) -> InstallScript:
    """Download *url* to a private temp file and return its digest.

    The scheme is checked before the request and again on the URL the server
    actually served, so a redirect cannot downgrade the transport.
    """
    if not url.startswith(_HTTPS_SCHEME):
        raise AgentCliInstallError(f"install script URL is not HTTPS: {url}")
    request = urllib.request.Request(
        url,
        headers={"Accept": "text/plain, */*", "User-Agent": "sase-agent-cli"},
    )
    try:
        with urlopen_fn(request, timeout=timeout) as response:  # noqa: S310
            final_url = _response_url(response, url)
            if not final_url.startswith(_HTTPS_SCHEME):
                raise AgentCliInstallError(
                    f"install script URL redirected off HTTPS: {final_url}"
                )
            payload = response.read(max_bytes + 1)
    except AgentCliInstallError:
        raise
    except (OSError, ValueError, urllib.error.URLError) as exc:
        raise AgentCliInstallError(
            f"could not fetch install script from {url}: {exc}"
        ) from exc
    if len(payload) > max_bytes:
        raise AgentCliInstallError(
            f"install script from {url} exceeds the {max_bytes} byte limit"
        )
    digest = hashlib.sha256(payload).hexdigest()
    path = Path(get_sase_managed_tmpdir("agent-clis")) / f"install-{digest[:16]}.sh"
    path.write_bytes(payload)
    path.chmod(0o600)
    return InstallScript(url=url, path=path, digest=digest, size_bytes=len(payload))


def plan_agent_cli_installs(
    names: Sequence[str],
    *,
    force: bool = False,
    offline: bool = False,
    refresh: bool = False,
    env: Mapping[str, str] | None = None,
    status_fn: StatusFn = collect_agent_cli_statuses,
    fetch_fn: FetchFn = fetch_install_script,
) -> AgentCliInstallPlan:
    """Resolve names, fetch each declared installer, and decide every skip.

    Fetching happens during planning so ``--dry-run`` can show the digest of
    the exact bytes an execution would run.
    """
    statuses = status_fn(refresh=refresh, offline=offline)
    resolved: list[AgentCliStatus] = []
    for query in names:
        status = find_agent_cli_status(statuses, query)
        if status is None:
            known = tuple(item.name for item in statuses)
            return AgentCliUnknownName(
                query=query,
                known_names=known,
                suggestions=_suggestions(query, known),
            )
        if status not in resolved:
            resolved.append(status)
    return AgentCliInstallsPlanned(
        entries=tuple(
            plan_agent_cli_install_status(
                status, force=force, env=env, fetch_fn=fetch_fn
            )
            for status in resolved
        )
    )


def plan_agent_cli_install_status(
    status: AgentCliStatus,
    *,
    force: bool = False,
    env: Mapping[str, str] | None = None,
    fetch_fn: FetchFn = fetch_install_script,
) -> AgentCliInstallEntry:
    """Project one live status into an install command or an explicit skip."""
    install_dir = _resolve_install_dir(status, env=env)
    if not status.installs_from_script:
        return AgentCliInstallEntry(
            status,
            skip_reason=(
                f"{status.display_name} declares no SASE-runnable install "
                f"script; {status.install_hint}"
            ),
        )
    if status.installed and not force:
        version = status.installed_version or "unknown version"
        location = status.executable or "an unresolved path"
        return AgentCliInstallEntry(
            status,
            install_dir=install_dir,
            skip_reason=(
                f"already installed ({version}) at {location}; pass "
                "-f|--force to reinstall"
            ),
        )
    assert status.install_script_url is not None
    try:
        script = fetch_fn(status.install_script_url)
    except AgentCliInstallError as exc:
        return AgentCliInstallEntry(status, install_dir=install_dir, error=str(exc))
    return AgentCliInstallEntry(
        status,
        argv=(INSTALL_SCRIPT_INTERPRETER, str(script.path)),
        env_overlay=status.install_env,
        script=script,
        install_dir=install_dir,
    )


def execute_agent_cli_installs(
    plan: AgentCliInstallsPlanned,
    *,
    env: Mapping[str, str] | None = None,
    run_fn: RunnerFn = run_command,
    trigger: UpdateTrigger = UpdateTrigger.UNKNOWN,
    record_fn: RecordFn | None = record_agent_cli_update_run,
) -> tuple[AgentCliUpdateResult, ...]:
    """Run each planned installer sequentially and re-probe what it produced."""
    started_at = time.monotonic()
    results = tuple(
        _execute_entry(entry, env=env, run_fn=run_fn) for entry in plan.entries
    )
    if record_fn is not None:
        record_fn(results, trigger=trigger, elapsed=time.monotonic() - started_at)
    return results


def _resolve_install_dir(
    status: AgentCliStatus, *, env: Mapping[str, str] | None = None
) -> str | None:
    """Resolve where a declared installer writes its binary, if it says."""
    environment = os.environ if env is None else env
    override = (
        environment.get(status.install_dir_env) if status.install_dir_env else None
    )
    target = (override or "").strip() or status.install_dir
    if not target:
        return None
    return os.path.expanduser(target)


def _directory_on_path(directory: str, *, env: Mapping[str, str] | None = None) -> bool:
    """Whether *directory* is one of the ``PATH`` entries, symlinks resolved."""
    environment = os.environ if env is None else env
    target = Path(directory).expanduser()
    candidates = {target, target.resolve(strict=False)}
    for raw in (environment.get("PATH") or "").split(os.pathsep):
        if not raw:
            continue
        entry = Path(raw).expanduser()
        if entry in candidates or entry.resolve(strict=False) in candidates:
            return True
    return False


def _execute_entry(
    entry: AgentCliInstallEntry,
    *,
    env: Mapping[str, str] | None,
    run_fn: RunnerFn,
) -> AgentCliUpdateResult:
    status = entry.status
    if entry.argv is None:
        reason = entry.error or entry.skip_reason
        return _result(
            entry,
            status=(
                UpdateResultStatus.FAILED if entry.error else UpdateResultStatus.SKIPPED
            ),
            reason=(
                reason_with_docs(reason, status.docs_url)
                if reason is not None
                else None
            ),
        )

    try:
        command_result = run_fn(entry.argv, env_overlay=dict(entry.env_overlay))
    except AgentCliRunnerError as exc:
        return _result(
            entry,
            status=UpdateResultStatus.FAILED,
            command=entry.argv,
            reason=reason_with_docs(str(exc), status.docs_url),
        )

    output_tail = command_output_tail(command_result.output)
    if command_result.returncode != 0:
        return _result(
            entry,
            status=UpdateResultStatus.FAILED,
            command=entry.argv,
            elapsed=command_result.elapsed,
            reason=reason_with_docs(
                f"install script failed with exit {command_result.returncode}",
                status.docs_url,
            ),
            output_tail=output_tail,
        )

    executable = _locate_installed_executable(entry, env=env)
    if executable is None:
        return _result(
            entry,
            status=UpdateResultStatus.FAILED,
            command=entry.argv,
            elapsed=command_result.elapsed,
            reason=reason_with_docs(
                f"install script succeeded but SASE could not find `{status.binary}` "
                "afterwards",
                status.docs_url,
            ),
            output_tail=output_tail,
        )

    probe = probe_version(
        executable,
        version_argv=status.version_argv,
        version_regex=status.version_regex,
        run_fn=run_fn,
    )
    location = str(Path(executable).parent)
    on_path = _directory_on_path(location, env=env)
    return _result(
        entry,
        status=UpdateResultStatus.UPDATED,
        command=entry.argv,
        new_version=probe.version,
        elapsed=command_result.elapsed,
        reason=_install_note(location, on_path=on_path, probe_error=probe.error),
        output_tail=output_tail,
        install_dir=location,
        install_dir_on_path=on_path,
    )


def _locate_installed_executable(
    entry: AgentCliInstallEntry, *, env: Mapping[str, str] | None
) -> str | None:
    """Find the freshly installed binary on ``PATH`` or in the install dir."""
    binary = entry.status.binary
    if resolved := resolve_executable(binary, env=env):
        return resolved
    if entry.install_dir is None:
        return None
    candidate = Path(entry.install_dir) / binary
    return resolve_executable(str(candidate), env=env)


def _install_note(
    location: str, *, on_path: bool, probe_error: str | None
) -> str | None:
    """Report what the user still has to do, if anything, after a good install."""
    notes: list[str] = []
    if not on_path:
        notes.append(
            f'{location} is not on PATH; add `export PATH="{location}:$PATH"` to '
            "your shell startup file. SASE did not edit any shell rc file."
        )
    if probe_error:
        notes.append(f"post-install version probe failed: {probe_error}")
    return " ".join(notes) or None


def _result(
    entry: AgentCliInstallEntry,
    *,
    status: UpdateResultStatus,
    command: tuple[str, ...] | None = None,
    new_version: str | None = None,
    elapsed: float = 0.0,
    reason: str | None = None,
    output_tail: str | None = None,
    install_dir: str | None = None,
    install_dir_on_path: bool | None = None,
) -> AgentCliUpdateResult:
    cli = entry.status
    return AgentCliUpdateResult(
        name=cli.name,
        display_name=cli.display_name,
        status=status,
        old_version=cli.installed_version,
        new_version=new_version if new_version is not None else cli.installed_version,
        command=command,
        docs_url=cli.docs_url,
        env_overlay=entry.env_overlay if command is not None else (),
        elapsed=elapsed,
        reason=reason,
        output_tail=output_tail,
        operation=AgentCliOperation.INSTALL,
        script_digest=entry.script.digest if entry.script is not None else None,
        install_dir=install_dir if install_dir is not None else entry.install_dir,
        install_dir_on_path=install_dir_on_path,
    )


def _response_url(response: object, fallback: str) -> str:
    geturl = getattr(response, "geturl", None)
    if not callable(geturl):
        return fallback
    served = geturl()
    return served if isinstance(served, str) and served else fallback


def _suggestions(query: str, known: Sequence[str]) -> tuple[str, ...]:
    return tuple(difflib.get_close_matches(query, known, n=3, cutoff=0.4))


__all__ = [
    "INSTALL_FETCH_TIMEOUT_SECONDS",
    "INSTALL_SCRIPT_INTERPRETER",
    "INSTALL_SCRIPT_MAX_BYTES",
    "AgentCliInstallEntry",
    "AgentCliInstallError",
    "AgentCliInstallPlan",
    "AgentCliInstallsPlanned",
    "InstallScript",
    "execute_agent_cli_installs",
    "fetch_install_script",
    "plan_agent_cli_install_status",
    "plan_agent_cli_installs",
]
