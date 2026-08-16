"""Where selection-health records live, and how they are written.

Two kinds of record land in one host-local store:

``selection``
    One per ``tools/run_pytest scoped`` run: the manifest the engine produced,
    plus the duration and outcome the runner appended.
``full-run``
    One per full-lane run (``just test`` / ``just check-full`` / the coverage
    leg): the node IDs that failed, and the commit they failed at.

Correlating the two is :mod:`tests._test_selection_health`'s job; this module
only owns the bytes on disk. Both kinds carry the workspace and change set that
correlation needs, which is what schema 2 added.

The store lives under ``${SASE_HOME:-~/.sase}/test-selection/<project-key>/``
rather than in ``.pytest_cache``, because the numbered workspaces are ephemeral
and the correlation surface that matters spans them: a phase agent in
``sase_3`` and one in ``sase_11`` write manifests that a land agent in
``sase_7`` needs to read.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from tests._test_selection_graph import SelectionError, run_git


#: Bumped to 2 when the workspace identity and change set that change-scoped
#: correlation requires joined both record kinds.
HEALTH_SCHEMA = 2

STORE_SUBDIRECTORY = "test-selection"
DEFAULT_SASE_HOME = Path("~/.sase")
RETENTION_DAYS = 30

SASE_HOME_ENV = "SASE_HOME"
#: Overrides the whole store location; the tests and `--store` use it.
STORE_ENV = "SASE_TEST_SELECTION_HEALTH_DIR"
#: Overrides the per-project namespace inside the store.
PROJECT_KEY_ENV = "SASE_TEST_SELECTION_HEALTH_PROJECT_KEY"
#: JSON handed to the full-lane pytest plugin by ``tools/run_pytest``. The
#: runner resolves the store in the parent process, so the plugin never has to
#: guess at a ``SASE_HOME`` that the suite's own fixtures redirect per test.
RECORD_ENV = "SASE_TEST_SELECTION_HEALTH_RECORD"

KIND_SELECTION = "selection"
KIND_FULL_RUN = "full-run"

_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%SZ"
_RECORD_NAME_PATTERN = re.compile(
    r"^(?P<timestamp>\d{8}T\d{6}Z)-(?P<head>[0-9a-f]+|unknown)-(?P<pid>\d+)"
    r"(?:-(?P<kind>[a-z-]+))?\.json$"
)
_GITHUB_REMOTE_PATTERN = re.compile(
    r"github\.com[:/](?P<org>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$"
)
_WORKSPACE_SUFFIX_PATTERN = re.compile(r"_\d+$")
_UNSAFE_KEY_CHARACTERS = re.compile(r"[^A-Za-z0-9._-]+")


# --------------------------------------------------------------------------
# Store location
# --------------------------------------------------------------------------


def _key_from_remote_url(url: str) -> str | None:
    match = _GITHUB_REMOTE_PATTERN.search(url.strip())
    if match is None:
        return None
    return f"gh_{match['org']}__{match['repo']}"


def _key_from_root(root: Path) -> str:
    name = _WORKSPACE_SUFFIX_PATTERN.sub("", root.name)
    sanitized = _UNSAFE_KEY_CHARACTERS.sub("-", name).strip("-")
    return sanitized or "unknown"


def project_key(root: Path, environ: Mapping[str, str] | None = None) -> str:
    """Namespace the store by project, the way ProjectSpec keys do.

    The GitHub remote yields exactly SASE's ``gh_<org>__<repo>`` directory key,
    which is what makes one store shared by every numbered workspace of the
    same project. A repository with no usable remote falls back to its own
    directory name with the ``_<N>`` workspace suffix stripped, which shares
    the store across workspaces just as well.
    """
    environ = os.environ if environ is None else environ
    override = environ.get(PROJECT_KEY_ENV)
    if override:
        return override
    try:
        url = run_git(root, "remote", "get-url", "origin")
    except SelectionError:
        url = ""
    return _key_from_remote_url(url) or _key_from_root(root)


def workspace_identity(root: Path) -> str:
    """Identify the workspace a record was written from.

    The resolved repository root, not a digest of it. The store is host-local
    and already namespaced per project, so the path is exactly as stable as a
    hash would be while staying legible: ``.../sase_3`` versus ``.../sase_11``
    is the very distinction the false-negative metric turns on, and a reader
    inspecting a suspicious match needs to see which workspace produced it.
    """
    return str(root.resolve())


def store_directory(root: Path, environ: Mapping[str, str] | None = None) -> Path:
    """Resolve the host-local record store for ``root``'s project."""
    environ = os.environ if environ is None else environ
    override = environ.get(STORE_ENV)
    if override:
        return Path(override).expanduser()
    sase_home = environ.get(SASE_HOME_ENV)
    home = Path(sase_home).expanduser() if sase_home else DEFAULT_SASE_HOME.expanduser()
    return home / STORE_SUBDIRECTORY / project_key(root, environ)


# --------------------------------------------------------------------------
# Writing records
# --------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC)


def record_filename(kind: str, *, now: datetime, head: str | None, pid: int) -> str:
    stamp = now.astimezone(UTC).strftime(_TIMESTAMP_FORMAT)
    short_head = (head or "unknown")[:12]
    suffix = "" if kind == KIND_SELECTION else f"-{kind}"
    return f"{stamp}-{short_head}-{pid}{suffix}.json"


def allocate_record_path(
    store: Path,
    kind: str,
    *,
    head: str | None,
    pid: int,
    now: datetime | None = None,
) -> Path:
    """Reserve a record path, creating and pruning the store on the way.

    Allocation is separate from writing because the full-lane recorder lives in
    a pytest plugin inside an ``execv``'d child: the runner picks the path (and
    pays the pruning cost) before handing off.
    """
    now = now or _now()
    store.mkdir(parents=True, exist_ok=True)
    prune_store(store, now=now)
    return store / record_filename(kind, now=now, head=head, pid=pid)


def write_record(path: Path, record: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


def record_selection(
    store: Path,
    manifest: Mapping[str, Any],
    *,
    workspace: str | None,
    pid: int | None = None,
    now: datetime | None = None,
) -> Path:
    """Persist a completed scoped-run manifest to the durable store.

    The manifest already carries the change set; ``workspace`` is the other
    half of the correlation identity, and lives on the envelope rather than in
    the manifest because it describes where the record was written, not what
    the selector decided.
    """
    head = str((manifest.get("baseline") or {}).get("head") or "") or None
    path = allocate_record_path(
        store,
        KIND_SELECTION,
        head=head,
        pid=os.getpid() if pid is None else pid,
        now=now,
    )
    write_record(
        path,
        {
            "schema": HEALTH_SCHEMA,
            "kind": KIND_SELECTION,
            "recorded_at": (now or _now()).astimezone(UTC).isoformat(),
            "workspace": workspace,
            "manifest": dict(manifest),
        },
    )
    return path


def full_run_record(
    *,
    head: str | None,
    mode: str,
    failures: Sequence[str],
    exit_status: int,
    workspace: str | None,
    changed_files: Sequence[str] | None,
    tree_dirty: bool | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build a full-lane record, identity included.

    ``workspace`` and ``changed_files`` are written even when unresolvable, as
    explicit nulls: a schema-2 record with no identity is as uncorrelatable as
    a pre-schema one, and saying so beats leaving the reader to infer it.
    ``tree_dirty`` is the same tri-state: ``None`` means unresolvable, not
    "clean", and correlation must keep treating it that way.
    """
    return {
        "schema": HEALTH_SCHEMA,
        "kind": KIND_FULL_RUN,
        "recorded_at": (now or _now()).astimezone(UTC).isoformat(),
        "head": head,
        "mode": mode,
        "exit_status": exit_status,
        "workspace": workspace,
        "changed_files": None if changed_files is None else sorted(set(changed_files)),
        "tree_dirty": tree_dirty,
        "failures": sorted(set(failures)),
    }


def _record_timestamp(path: Path) -> datetime | None:
    match = _RECORD_NAME_PATTERN.match(path.name)
    if match is None:
        return None
    try:
        parsed = datetime.strptime(match["timestamp"], _TIMESTAMP_FORMAT)
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC)


def prune_store(
    store: Path, *, now: datetime | None = None, retention_days: int = RETENTION_DAYS
) -> list[Path]:
    """Drop records older than ``retention_days``; return what was removed.

    Records whose names the store does not recognise are left alone: this
    directory is under the user's ``~/.sase``, and a pruner that deletes
    unfamiliar files there is a liability, not a feature.
    """
    cutoff = (now or _now()) - timedelta(days=retention_days)
    removed: list[Path] = []
    try:
        entries = sorted(store.iterdir())
    except OSError:
        return removed
    for entry in entries:
        stamp = _record_timestamp(entry)
        if stamp is None or stamp >= cutoff:
            continue
        try:
            entry.unlink()
        except OSError:
            continue
        removed.append(entry)
    return removed
