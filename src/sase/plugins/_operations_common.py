"""Shared types and helpers for console-free plugin operations."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal

from sase.plugins.catalog import PluginCatalog, PluginCatalogEntry, find_plugin
from sase.plugins.installed import InstalledInfo
from sase.plugins.pypi_source import ProjectAvailability, probe_availability
from sase.uv_tool.detect import NotUvToolInstall, UvToolInstall
from sase.uv_tool.errors import UvToolError
from sase.uv_tool.receipt import Requirement, ToolReceipt
from sase.uv_tool.runner import UvChangeSet
from sase.version._utils import normalize_distribution_name

#: Spec source: resolved from the catalog, forced to git, or passed through.
SpecSource = Literal["catalog", "git", "passthrough"]

LoadFn = Callable[..., PluginCatalog]
ProbeFn = Callable[[], UvToolInstall | NotUvToolInstall]
RunUvFn = Callable[[list[str]], UvChangeSet]
InstalledIndexFn = Callable[[], dict[str, InstalledInfo]]
ClockFn = Callable[[], float]
#: Single-distribution public-index availability probe (see :mod:`pypi_source`).
AvailabilityProbeFn = Callable[[str], ProjectAvailability]
#: Bounded batch probe: one shared time budget for every name, not N budgets.
AvailabilityBatchFn = Callable[[Sequence[str]], dict[str, ProjectAvailability]]


@dataclass(frozen=True)
class NotUvTool:
    """A plugin mutation cannot proceed before invoking ``uv``.

    The historical name is retained for frontend compatibility. *error* carries
    the precise, already-rendered actionable message; display it verbatim.
    """

    error: UvToolError


@dataclass(frozen=True)
class ResolvedSpec:
    """A ``<plugin>`` argument resolved to a uv install spec.

    *requirement* is what gets added to the reconstructed ``--with`` set;
    *display_name* is the short, friendly name for output; *source* records how
    the name was resolved (for the dry-run preview and the JSON payload).
    """

    requirement: Requirement
    display_name: str
    source: SpecSource

    @property
    def normalized_name(self) -> str:
        """PEP 503-normalized distribution name, for receipt matching."""
        return self.requirement.normalized_name


def resolve_install_spec(
    catalog: PluginCatalog,
    query: str,
    *,
    git: bool = False,
    offline: bool = False,
    availability_fn: AvailabilityProbeFn = probe_availability,
) -> ResolvedSpec | None:
    """Resolve a ``<plugin>`` argument to a :class:`ResolvedSpec`, or ``None``.

    Resolution order:

    1. A raw requirement, git URL, or local path is passed through verbatim.
    2. ``git=True`` forces ``git+<repo url>``; no availability probe is made.
    3. Otherwise the name is looked up in the catalog: a definitive public
       PyPI 404 (``availability_fn`` returns
       :attr:`~sase.plugins.pypi_source.ProjectAvailability.MISSING`) falls
       back to ``git+<repo url>``. Every other probe result — available,
       offline, timeout, malformed — keeps the distribution name, so an
       index outage is never mistaken for a definitive absence.
    4. A catalog miss returns ``None`` so the caller can render ranked
       suggestions and exit non-zero.
    """
    stripped = query.strip()
    if not stripped:
        return None

    if _looks_like_raw_spec(stripped):
        requirement = Requirement.from_spec(stripped)
        return ResolvedSpec(
            requirement=requirement,
            display_name=requirement.name or stripped,
            source="passthrough",
        )

    entry = find_plugin(catalog, stripped)
    if entry is None:
        return None
    return _spec_from_entry(
        entry, git=git, offline=offline, availability_fn=availability_fn
    )


def load_catalog(load_fn: LoadFn, *, refresh: bool, offline: bool) -> PluginCatalog:
    """Load the catalog, forwarding ``offline`` only when it is set.

    The CLI never offered an offline install/update flag, and its long-standing
    test fakes accept only ``refresh``; forwarding ``offline`` unconditionally
    would break them. The default (online) path therefore preserves the exact
    historical ``load_fn(refresh=...)`` call, while the TUI — which passes the
    real :func:`~sase.plugins.catalog.load_plugin_catalog` — gets cache-first
    offline loads when it sets the flag.
    """
    if offline:
        return load_fn(refresh=refresh, offline=True)
    return load_fn(refresh=refresh)


def match_injected(receipt: ToolReceipt, query: str) -> Requirement | None:
    """Match *query* against injected plugin requirements in *receipt*."""
    for candidate in _name_candidates(query):
        key = normalize_distribution_name(candidate)
        if not key:
            continue
        for plugin in receipt.deduped_injected_plugins():
            if plugin.normalized_name == key:
                return plugin
    return None


def short_display_name(dist_name: str) -> str:
    """Friendly short name for output: drop a leading ``sase-`` if present."""
    if dist_name.lower().startswith("sase-") and len(dist_name) > len("sase-"):
        return dist_name[len("sase-") :]
    return dist_name


def _spec_from_entry(
    entry: PluginCatalogEntry,
    *,
    git: bool,
    offline: bool,
    availability_fn: AvailabilityProbeFn,
) -> ResolvedSpec:
    if git:
        # html_url (``https://github.com/owner/repo``) is git-cloneable as-is.
        requirement = Requirement.from_spec(f"git+{entry.url}")
        return ResolvedSpec(
            requirement=requirement, display_name=entry.name, source="git"
        )
    if not offline and availability_fn(entry.repo) is ProjectAvailability.MISSING:
        requirement = Requirement.from_spec(f"git+{entry.url}")
        return ResolvedSpec(
            requirement=requirement, display_name=entry.name, source="git"
        )
    requirement = Requirement.from_spec(entry.repo)
    return ResolvedSpec(
        requirement=requirement, display_name=entry.name, source="catalog"
    )


def _looks_like_raw_spec(query: str) -> bool:
    """Whether *query* is a raw requirement / URL / path to pass through.

    A bare ``owner/repo`` catalog full name is *not* a path (it does not start
    with a path prefix), so it still resolves through the catalog.
    """
    if query.startswith("git+") or "://" in query:
        return True
    if query.startswith(("/", "./", "../", "~")) or query == ".":
        return True
    return any(op in query for op in ("==", ">=", "<=", "~=", "!=", ">", "<"))


def _name_candidates(query: str) -> tuple[str, ...]:
    base = query.strip()
    short = base.split("/", 1)[1] if "/" in base else base
    candidates = [base, short]
    for value in (base, short):
        if value and not value.lower().startswith("sase-"):
            candidates.append(f"sase-{value}")
    return tuple(candidates)
