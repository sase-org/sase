"""Pre-install command preview for uninstalled plugins (phase sase-1if.6).

Reads an uninstalled catalog plugin's declared ``sase_commands`` from its
upstream ``pyproject.toml`` (via the ``gh`` CLI, like the catalog source),
caches the result, and flags pre-consent collisions with the ``mount`` rules:

- a declared name that is reserved or built-in "would be shadowed";
- a declared name already owned by an installed command "would conflict with
  <dist> — both would be disabled".

An installed plugin's authoritative
:attr:`sase.plugins.installed.InstalledInfo.commands` always wins over the
preview. Every failure mode — no pyproject, dynamic ``entry-points``, missing
``gh``, fetch failure, offline mode, parse error — yields status ``unknown``,
which renders nothing, so sase never makes a false claim.
"""

from __future__ import annotations

import json
import os
import time
import tomllib
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from sase.core.paths import ensure_sase_directory, sase_subdir

#: Bump when the cached envelope shape changes incompatibly.
SCHEMA_VERSION = 1

#: Subdirectory under ``sase_home()`` holding the declared-commands cache.
CACHE_SUBDIR = "plugins"

#: Cache file name under the plugins subdirectory.
CACHE_FILENAME = "declared_commands_cache.json"

#: A cached preview is invalidated after 7 days or when the catalog's
#: ``updated_at`` for the repository changes.
DECLARED_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60

#: Per-attempt subprocess timeout for the upstream ``pyproject.toml`` fetch.
GH_FETCH_TIMEOUT_SECONDS = 15.0

#: Table path inside ``pyproject.toml`` that declares plugin commands.
COMMANDS_TABLE_PATH = ("project", "entry-points", "sase_commands")

#: Source label recorded when the names came from the upstream pyproject.
PYPROJECT_SOURCE = "pyproject:project.entry-points.sase_commands"

#: Preview status for one uninstalled plugin.
DeclaredStatus = Literal["declared", "none", "unknown"]

#: Pre-consent collision kind for one declared name.
DeclaredProblemKind = Literal["shadowed", "conflict"]


@dataclass(frozen=True)
class DeclaredCommands:
    """Upstream-declared ``sase_commands`` for one uninstalled plugin."""

    status: DeclaredStatus = "unknown"
    names: tuple[str, ...] = ()
    source: str | None = None

    def to_json(self) -> dict[str, Any]:
        """Return the stable ``declared_commands`` shape minus problems."""
        return {
            "status": self.status,
            "names": list(self.names),
            "source": self.source,
        }


@dataclass(frozen=True)
class DeclaredCommandProblem:
    """One declared name that would not mount cleanly if installed now."""

    name: str
    kind: DeclaredProblemKind
    detail: str

    def to_json(self) -> dict[str, Any]:
        """Return the stable per-problem object shape."""
        return {"name": self.name, "problem": self.kind, "detail": self.detail}


@dataclass(frozen=True)
class _CachedDeclared:
    """One cached upstream preview row."""

    status: DeclaredStatus
    names: tuple[str, ...]
    source: str | None
    updated_at: str
    fetched_at: float


def _cache_path() -> Path:
    """Return the declared-commands cache file path (creates nothing)."""
    return sase_subdir(CACHE_SUBDIR) / CACHE_FILENAME


def _cache_key(full_name: str) -> str:
    """Return the casefolded cache key for a ``owner/repo`` full name."""
    return full_name.casefold()


def _read_declared_cache(path: Path | None = None) -> dict[str, _CachedDeclared]:
    """Read the declared-commands cache, returning ``{}`` on any failure."""
    cache_path = path or _cache_path()
    try:
        raw = cache_path.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        envelope = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(envelope, dict):
        return {}
    if envelope.get("schema_version") != SCHEMA_VERSION:
        return {}
    raw_entries = envelope.get("entries")
    if not isinstance(raw_entries, dict):
        return {}
    entries: dict[str, _CachedDeclared] = {}
    for raw_name, raw_entry in raw_entries.items():
        if not isinstance(raw_name, str) or not isinstance(raw_entry, dict):
            continue
        key = _cache_key(raw_name)
        if not key:
            continue
        status = raw_entry.get("status")
        if status not in ("declared", "none", "unknown"):
            continue
        raw_names = raw_entry.get("names")
        if not isinstance(raw_names, list) or not all(
            isinstance(name, str) for name in raw_names
        ):
            continue
        source = raw_entry.get("source")
        if source is not None and not isinstance(source, str):
            continue
        updated_at = raw_entry.get("updated_at")
        if not isinstance(updated_at, str):
            continue
        fetched_at = raw_entry.get("fetched_at")
        if not isinstance(fetched_at, (int, float)) or isinstance(fetched_at, bool):
            continue
        entries[key] = _CachedDeclared(
            status=status,
            names=tuple(raw_names),
            source=source,
            updated_at=updated_at,
            fetched_at=float(fetched_at),
        )
    return entries


def _write_declared_cache(
    entries: dict[str, _CachedDeclared],
    *,
    path: Path | None = None,
) -> None:
    """Atomically write *entries* to the declared-commands cache."""
    cache_path = path or _cache_path()
    if path is None:
        ensure_sase_directory(CACHE_SUBDIR)
    else:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
    envelope: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "entries": {
            key: {
                "status": cached.status,
                "names": list(cached.names),
                "source": cached.source,
                "updated_at": cached.updated_at,
                "fetched_at": cached.fetched_at,
            }
            for key, cached in sorted(entries.items())
            if key
        },
    }
    serialized = json.dumps(envelope, indent=2, sort_keys=True)
    tmp_path = cache_path.with_name(f"{cache_path.name}.{os.getpid()}.tmp")
    tmp_path.write_text(serialized, encoding="utf-8")
    os.replace(tmp_path, cache_path)


def _is_fresh(cached: _CachedDeclared, updated_at: str, now: float) -> bool:
    """Return whether *cached* is still valid for *updated_at* at *now*."""
    return (
        cached.updated_at == updated_at
        and now - cached.fetched_at < DECLARED_CACHE_TTL_SECONDS
    )


GhRunnerFn = Callable[..., Any]


def _fetch_upstream_pyproject(
    full_name: str,
    *,
    run_fn: GhRunnerFn | None = None,
    timeout: float = GH_FETCH_TIMEOUT_SECONDS,
) -> str | None:
    """Fetch the upstream ``pyproject.toml`` for *full_name*, or ``None``.

    Uses the existing ``gh`` boundary (``gh api repos/<full_name>/contents/
    pyproject.toml`` with the raw media type). Any failure — missing ``gh``,
    non-zero exit, empty body — returns ``None`` so the caller reports
    ``unknown`` instead of a false claim.
    """
    from sase.github_cli import run_gh

    endpoint = f"repos/{full_name}/contents/pyproject.toml"
    try:
        result = run_gh(
            ["api", "-H", "Accept: application/vnd.github.raw", endpoint],
            timeout=timeout,
            max_attempts=1,
            run_fn=run_fn,
            op="plugins.declared_commands.fetch_upstream_pyproject",
        )
    except Exception:  # noqa: BLE001 — every gh failure means unknown.
        return None
    if result.returncode != 0:
        return None
    text = result.stdout
    if not isinstance(text, str) or not text.strip():
        return None
    return text


def _parse_declared_commands(text: str) -> DeclaredCommands:
    """Parse declared ``sase_commands`` from ``pyproject.toml`` *text*.

    Returns status ``declared`` (with the sorted command names) or ``none``.
    Raises :class:`ValueError` when the declaration cannot be determined —
    unparsable TOML or dynamic ``entry-points`` — so the caller reports
    ``unknown``.
    """
    try:
        data = tomllib.loads(text)
    except (tomllib.TOMLDecodeError, ValueError) as exc:
        raise ValueError(f"cannot parse pyproject.toml: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("cannot parse pyproject.toml: top level is not a table")
    project = data.get("project")
    if not isinstance(project, dict):
        return DeclaredCommands(status="none", names=(), source=None)
    dynamic = project.get("dynamic")
    if isinstance(dynamic, list) and "entry-points" in dynamic:
        raise ValueError("pyproject.toml declares dynamic entry-points")
    entry_points = project.get("entry-points")
    if entry_points is None:
        return DeclaredCommands(status="none", names=(), source=None)
    if not isinstance(entry_points, dict):
        raise ValueError("pyproject.toml project.entry-points is not a table")
    commands = entry_points.get("sase_commands")
    if commands is None:
        return DeclaredCommands(status="none", names=(), source=None)
    if not isinstance(commands, dict):
        raise ValueError("pyproject.toml sase_commands entry-points is not a table")
    names = tuple(sorted(str(name) for name in commands))
    if not names:
        return DeclaredCommands(status="none", names=(), source=None)
    return DeclaredCommands(status="declared", names=names, source=PYPROJECT_SOURCE)


FetchFn = Callable[[str], str | None]
ReadCacheFn = Callable[[], dict[str, _CachedDeclared]]
WriteCacheFn = Callable[[dict[str, _CachedDeclared]], None]
ClockFn = Callable[[], float]


def _get_declared_commands(
    full_name: str,
    *,
    updated_at: str = "",
    offline: bool = False,
    fetch_fn: FetchFn = _fetch_upstream_pyproject,
    read_cache_fn: ReadCacheFn | None = None,
    write_cache_fn: WriteCacheFn | None = None,
    clock: ClockFn = time.time,
) -> DeclaredCommands:
    """Return the cached-or-fresh upstream command preview for *full_name*.

    Never raises and never touches the network when *offline* is set: every
    failure path returns status ``unknown``, which renders nothing.
    """
    now = clock()
    try:
        cached = (read_cache_fn or _read_declared_cache)().get(_cache_key(full_name))
    except Exception:  # noqa: BLE001 — cache failures must not fail the preview.
        cached = None
    if cached is not None and _is_fresh(cached, updated_at, now):
        return DeclaredCommands(
            status=cached.status, names=cached.names, source=cached.source
        )
    if offline:
        return DeclaredCommands(status="unknown", names=(), source=None)
    try:
        text = fetch_fn(full_name)
    except Exception:  # noqa: BLE001 — fetch failures mean unknown.
        text = None
    if text is None:
        declared = DeclaredCommands(status="unknown", names=(), source=None)
    else:
        try:
            declared = _parse_declared_commands(text)
        except ValueError:
            declared = DeclaredCommands(status="unknown", names=(), source=None)
    try:
        entries = (read_cache_fn or _read_declared_cache)()
        entries[_cache_key(full_name)] = _CachedDeclared(
            status=declared.status,
            names=declared.names,
            source=declared.source,
            updated_at=updated_at,
            fetched_at=now,
        )
        (write_cache_fn or _write_declared_cache)(entries)
    except Exception:  # noqa: BLE001 — cache writes are best-effort.
        pass
    return declared


def live_command_owners() -> dict[str, str]:
    """Map currently mounted command name -> owning distribution name.

    Best-effort: any discovery failure yields an empty mapping so previews
    degrade to no-conflict instead of failing.
    """
    try:
        from sase.plugin_commands.registry import discover_plugin_commands

        return {
            name: record.distribution
            for name, record in discover_plugin_commands(honor_disable=False)
            .mounted_by_name()
            .items()
        }
    except Exception:  # noqa: BLE001 — previews must never fail the command.
        return {}


def live_reserved_command_names() -> frozenset[str]:
    """Return the command names plugins may never claim (built-ins win)."""
    from sase.plugin_commands.registry import reserved_command_names

    return reserved_command_names()


def declared_problems(
    names: Sequence[str],
    *,
    command_owners: Mapping[str, str] | None = None,
    reserved_names: frozenset[str] | None = None,
) -> tuple[DeclaredCommandProblem, ...]:
    """Flag pre-consent collisions for upstream-declared *names*.

    A name that is invalid or reserved "would be shadowed"; a name already
    owned by an installed command "would conflict with <dist> — both would be
    disabled". Live discovery runs only when the mappings are not provided so
    ``list`` can share one scan across every entry.
    """
    from sase.plugin_commands.registry import COMMAND_NAME_RE

    owners = (
        dict(command_owners) if command_owners is not None else live_command_owners()
    )
    try:
        reserved = (
            reserved_names
            if reserved_names is not None
            else live_reserved_command_names()
        )
    except Exception:  # noqa: BLE001 — without reservations only conflicts apply.
        reserved = frozenset()
    problems: list[DeclaredCommandProblem] = []
    for name in names:
        if not COMMAND_NAME_RE.match(name) or name in reserved:
            problems.append(
                DeclaredCommandProblem(
                    name=name,
                    kind="shadowed",
                    detail=(
                        f"sase {name} would be shadowed: '{name}' is a built-in "
                        "sase command name and cannot be provided by a plugin"
                    ),
                )
            )
        elif name in owners:
            problems.append(
                DeclaredCommandProblem(
                    name=name,
                    kind="conflict",
                    detail=(
                        f"sase {name} would conflict with {owners[name]} — "
                        "both would be disabled"
                    ),
                )
            )
    return tuple(problems)


def declared_commands_json(
    declared: DeclaredCommands | None,
    problems: Sequence[DeclaredCommandProblem] = (),
) -> dict[str, Any]:
    """Return the stable ``declared_commands`` JSON object shape.

    A ``None`` preview reports ``unknown`` with no names, so the key is always
    present and surfaces render nothing for it.
    """
    base = (declared or DeclaredCommands()).to_json()
    base["problems"] = [problem.to_json() for problem in problems]
    return base


def attach_declared_previews(
    entries: Sequence[Any],
    *,
    offline: bool = False,
    fetch_fn: FetchFn = _fetch_upstream_pyproject,
    read_cache_fn: ReadCacheFn | None = None,
    write_cache_fn: WriteCacheFn | None = None,
    clock: ClockFn = time.time,
    max_workers: int = 8,
    deadline_seconds: float | None = 8.0,
    monotonic: ClockFn = time.monotonic,
) -> dict[str, DeclaredCommands]:
    """Fetch upstream previews for uninstalled *entries*, keyed by full name.

    Installed entries are skipped: their authoritative installed commands win
    over any preview. Fetches run on a small thread pool under one shared
    deadline; entries that miss it report ``unknown``. Never raises.
    """
    pending = [
        entry
        for entry in entries
        if not _entry_is_installed(entry)
        and isinstance(getattr(entry, "full_name", ""), str)
        and entry.full_name
    ]
    if not pending or offline:
        return {}
    started = monotonic()
    previews: dict[str, DeclaredCommands] = {}

    def _one(entry: Any) -> tuple[str, DeclaredCommands]:
        try:
            declared = _get_declared_commands(
                entry.full_name,
                updated_at=entry.updated_at or "",
                fetch_fn=fetch_fn,
                read_cache_fn=read_cache_fn,
                write_cache_fn=write_cache_fn,
                clock=clock,
            )
        except Exception:  # noqa: BLE001 — one bad entry must not fail the batch.
            declared = DeclaredCommands(status="unknown", names=(), source=None)
        return _cache_key(entry.full_name), declared

    try:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = [pool.submit(_one, entry) for entry in pending]
            for future in futures:
                if deadline_seconds is not None and monotonic() - started >= (
                    deadline_seconds
                ):
                    break
                try:
                    key, declared = future.result(
                        timeout=(
                            max(0.1, deadline_seconds - (monotonic() - started))
                            if deadline_seconds is not None
                            else None
                        )
                    )
                except Exception:  # noqa: BLE001 — timeouts degrade to unknown.
                    continue
                previews[key] = declared
    except Exception:  # noqa: BLE001 — batch enrichment never fails the command.
        pass
    for entry in pending:
        previews.setdefault(
            _cache_key(entry.full_name),
            DeclaredCommands(status="unknown", names=(), source=None),
        )
    return previews


def _entry_is_installed(entry: Any) -> bool:
    """Return whether a duck-typed catalog entry is installed."""
    try:
        return bool(entry.installed.installed)
    except AttributeError:
        return False


def get_declared_commands_for_entry(
    entry: Any,
    *,
    offline: bool = False,
    fetch_fn: FetchFn = _fetch_upstream_pyproject,
    read_cache_fn: ReadCacheFn | None = None,
    write_cache_fn: WriteCacheFn | None = None,
    clock: ClockFn = time.time,
) -> DeclaredCommands:
    """Return the upstream command preview for one catalog entry.

    Takes the entry (duck-typed: ``full_name`` and ``updated_at``) instead of
    raw strings so CLI and TUI call sites stay one-liners. Installed entries
    report ``unknown``: their authoritative installed commands win.
    """
    if _entry_is_installed(entry):
        return DeclaredCommands(status="unknown", names=(), source=None)
    return _get_declared_commands(
        entry.full_name,
        updated_at=entry.updated_at or "",
        offline=offline,
        fetch_fn=fetch_fn,
        read_cache_fn=read_cache_fn,
        write_cache_fn=write_cache_fn,
        clock=clock,
    )


__all__ = [
    "CACHE_FILENAME",
    "CACHE_SUBDIR",
    "COMMANDS_TABLE_PATH",
    "DECLARED_CACHE_TTL_SECONDS",
    "DeclaredCommandProblem",
    "DeclaredCommands",
    "DeclaredProblemKind",
    "DeclaredStatus",
    "GH_FETCH_TIMEOUT_SECONDS",
    "PYPROJECT_SOURCE",
    "attach_declared_previews",
    "declared_commands_json",
    "declared_problems",
    "get_declared_commands_for_entry",
    "live_command_owners",
    "live_reserved_command_names",
]
