"""Survive a ``sase dev update`` that swaps editable source under a live runner.

An agent runner can stay alive for hours while ``~/.local/bin/sase`` resolves to
an editable install whose ``.pth`` points at a working checkout. When that
checkout fast-forwards mid-run, every module already in ``sys.modules`` stays at
the old revision while every *deferred* import reads the new source, so a lazy
``from sase.x import y`` can fail against a stale cached module.

Two halves live here:

*Prevention* -- :func:`preload_post_gate_modules` imports the post-gate surface
once, while the agent CLI is still booting, so the later path has nothing left
to import lazily.

*Honesty* -- :func:`snapshot_source_revision` records the revision the process
booted against and :func:`code_swap_explanation` labels an import failure that
followed a swap as exactly that, instead of blaming the SDD store.

Preloading cannot cover everything: plugin distributions are separate editable
checkouts that ``sase dev update`` swaps too. That is why the classifier exists.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import logging
import os
import pkgutil
import time
from pathlib import Path

logger = logging.getLogger(__name__)

DISABLE_IMPORT_PRELOAD_ENV = "SASE_DISABLE_IMPORT_PRELOAD"

# Packages walked in full. Walking beats an allowlist here: there is no list to
# keep in sync, and the deferred SDD/bead imports that the accepted-plan and
# commit paths reach are covered by construction.
_PRELOAD_PACKAGES = ("sase.sdd", "sase.bead")

# Modules outside those packages that post-gate paths import lazily.
_PRELOAD_MODULES = (
    "sase.agents_sync.prompt_archive",
    "sase.notifications.senders",
    "sase.vcs_provider.plugins._git_commit_dispatch",
)

# Plugin entry-point groups whose distributions are loaded lazily on first use.
_PRELOAD_ENTRY_POINT_GROUPS = ("sase_workspace", "sase_vcs", "sase_llm")

_startup_revision: str | None = None
_startup_revision_taken = False


def _source_checkout() -> Path | None:
    """Return the git checkout ``sase`` was imported from, if it is one."""
    import sase

    source_file = getattr(sase, "__file__", None)
    if not source_file:
        return None
    try:
        root = Path(source_file).resolve().parents[2]
    except IndexError:
        return None
    return root if (root / ".git").exists() else None


def _revision_at(checkout: Path) -> str | None:
    """Return *checkout*'s current HEAD SHA, or ``None`` when unavailable."""
    from sase.version._git import probe_git_metadata_at_ref

    try:
        result = probe_git_metadata_at_ref(checkout, "HEAD")
    except Exception:
        return None
    return result.metadata.commit if result.metadata is not None else None


def snapshot_source_revision() -> str | None:
    """Record the source revision this process booted against, once.

    Returns the snapshotted revision, or ``None`` when ``sase`` was not imported
    from a git checkout. Repeat calls return the first snapshot so a later swap
    can never overwrite the boot-time value.
    """
    global _startup_revision, _startup_revision_taken  # noqa: PLW0603

    if _startup_revision_taken:
        return _startup_revision
    checkout = _source_checkout()
    _startup_revision = None if checkout is None else _revision_at(checkout)
    _startup_revision_taken = True
    return _startup_revision


def _source_revision_changed() -> tuple[str, str] | None:
    """Return ``(startup_revision, current_revision)`` when the source moved."""
    startup = snapshot_source_revision()
    if startup is None:
        return None
    checkout = _source_checkout()
    if checkout is None:
        return None
    current = _revision_at(checkout)
    if current is None or current == startup:
        return None
    return startup, current


def _describe_source_swap(checkout: Path | None, startup: str, current: str) -> str:
    """Render a human description of a mid-run editable source swap."""
    where = f" at {checkout}" if checkout is not None else ""
    return (
        f"the sase source checkout{where} moved from {startup} to {current} "
        "while this runner was live (`sase dev update`), so a deferred import "
        "resolved new source against modules cached from the old revision"
    )


def _has_import_error_cause(exc: BaseException) -> bool:
    """Whether *exc* or anything it chains from is an import/attribute error."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, (ImportError, AttributeError)):
            return True
        current = current.__cause__ or current.__context__
    return False


def code_swap_explanation(exc: BaseException) -> str | None:
    """Describe *exc* as a mid-run code swap, or ``None`` when it is not one.

    Both signals must hold: the failure chain bottoms out in an
    ``ImportError``/``AttributeError``, and the editable source revision moved
    since this process started. Either one alone is ordinary breakage.
    """
    if not _has_import_error_cause(exc):
        return None
    revisions = _source_revision_changed()
    if revisions is None:
        return None
    startup, current = revisions
    return _describe_source_swap(_source_checkout(), startup, current)


def _import_best_effort(module_name: str) -> bool:
    """Import *module_name*, swallowing any failure. Returns success."""
    try:
        importlib.import_module(module_name)
    except Exception as exc:  # noqa: BLE001 - one bad module must not fail a run
        logger.debug("Import preload skipped %s: %s", module_name, exc)
        return False
    return True


def _walk_package(package_name: str) -> list[str]:
    """Return every importable module name under *package_name*."""
    if not _import_best_effort(package_name):
        return []
    package = importlib.import_module(package_name)
    package_path = getattr(package, "__path__", None)
    if package_path is None:
        return [package_name]
    names = [package_name]
    try:
        for module in pkgutil.walk_packages(
            package_path,
            prefix=f"{package_name}.",
            onerror=lambda _: None,
        ):
            names.append(module.name)
    except Exception as exc:  # noqa: BLE001 - discovery is best-effort too
        logger.debug("Import preload could not walk %s: %s", package_name, exc)
    return names


def _preload_entry_point_groups() -> int:
    """Import every plugin distribution reachable from the preload groups."""
    loaded = 0
    for group in _PRELOAD_ENTRY_POINT_GROUPS:
        try:
            entry_points = list(importlib.metadata.entry_points(group=group))
        except Exception as exc:  # noqa: BLE001
            logger.debug("Import preload could not list group %s: %s", group, exc)
            continue
        for entry_point in entry_points:
            if _import_best_effort(entry_point.module):
                loaded += 1
    return loaded


def preload_post_gate_modules() -> int:
    """Import the post-gate surface up front so no later import is deferred.

    Best-effort per module: a broken import is logged at debug level and never
    raised. Set ``SASE_DISABLE_IMPORT_PRELOAD=1`` to skip the preload entirely.
    Returns the number of modules successfully imported.
    """
    if os.environ.get(DISABLE_IMPORT_PRELOAD_ENV) == "1":
        logger.debug("Import preload disabled by %s", DISABLE_IMPORT_PRELOAD_ENV)
        return 0

    started = time.monotonic()
    names: list[str] = []
    for package_name in _PRELOAD_PACKAGES:
        names.extend(_walk_package(package_name))
    names.extend(_PRELOAD_MODULES)

    loaded = sum(1 for name in names if _import_best_effort(name))
    loaded += _preload_entry_point_groups()

    elapsed_ms = (time.monotonic() - started) * 1000
    logger.debug(
        "Import preload imported %d/%d modules in %.0fms",
        loaded,
        len(names),
        elapsed_ms,
    )
    return loaded
