"""Cache-first, per-owner candidate discovery feeding core classification.

Discovery is effects and orchestration only: providers own remote reads,
``sase-core`` owns the grouping rules, and this module assembles the wire
request both sides already agree on. Everything that can be read from disk
is read from disk; only a live owner refresh touches the network.
"""

from __future__ import annotations

import configparser
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from dataclasses import replace as _replace
from pathlib import Path
from typing import Any

from sase import workspace_provider
from sase.config import load_merged_config
from sase.core.paths import sase_projects_dir
from sase.core.project_lifecycle_facade import list_project_records
from sase.core.project_lifecycle_wire import (
    ProjectRecordWire,
    effective_project_name,
)
from sase.core.project_onboarding_facade import classify_project_candidates
from sase.macro.vcs_repo_completion import (
    fetch_repo_candidates,
    load_vcs_repo_completion_config,
    peek_cached_repo_candidates,
)
from sase.repo_inventory import collect_repo_inventory
from sase.sdd._store_types import (
    AGENTS_SIDECAR_ROLE,
    ATTACHMENTS_PRIVATE_SIDECAR_ROLE,
    ATTACHMENTS_SIDECAR_ROLE,
    BEADS_SIDECAR_ROLE,
    PLANS_SIDECAR_ROLE,
)
from sase.project_onboarding.journal import journals_dir as owned_journals_dir
from sase.project_onboarding.journal import list_incomplete
from sase.workspace_provider._hookspec import VcsRepoEntry

SUGGEST_SCHEMA_VERSION = 1
"""Version of the ``sase project suggest`` JSON document."""

_MAX_DISCOVERY_WORKERS = 3
_GH_KEY_RE = re.compile(r"^gh_(?P<owner>.+)__(?P<repo>.+)$")
_REPO_SUFFIX_RE = re.compile(r"-\d+$")
_GITDIR_PREFIX = "gitdir:"


@dataclass
class OwnerResult:
    """One namespace fetch: status rows plus remote wire entries."""

    name: str
    kind_label: str = "org"
    status: str = "ok"
    error_kind: str = ""
    message: str = ""
    stale: bool = False
    host: str = ""
    truncated: bool = False
    remedy_argv: list[str] = field(default_factory=list)
    entries: list[dict[str, Any]] = field(default_factory=list)
    fetched_at: float = 0.0
    """Epoch seconds the owner's entries were fetched; 0 when unknown."""

    def namespace_wire(self) -> dict[str, Any]:
        """Return the core ``namespaces`` wire dict for this owner."""

        return {
            "name": self.name,
            "kind_label": self.kind_label,
            "status": self.status,
            "error_kind": self.error_kind,
            "message": self.message,
            "stale": self.stale,
            "truncated": self.truncated,
            "fetched_at": "",
        }

    def to_json_dict(self) -> dict[str, Any]:
        """Return the ``owners`` row for the suggest JSON document."""

        return {
            "name": self.name,
            "kind_label": self.kind_label,
            "status": self.status,
            "error_kind": self.error_kind,
            "message": self.message,
            "stale": self.stale,
            "host": self.host,
            "truncated": self.truncated,
            "entry_count": len(self.entries),
            "remedy_argv": list(self.remedy_argv),
        }


@dataclass
class CandidateInputs:
    """Everything ``suggest`` observed for one provider."""

    workflow_type: str
    display: str
    account: str
    owners: list[OwnerResult] = field(default_factory=list)
    remote: list[dict[str, Any]] = field(default_factory=list)
    local: list[dict[str, Any]] = field(default_factory=list)
    projects: list[dict[str, Any]] = field(default_factory=list)
    inventory: list[dict[str, Any]] = field(default_factory=list)
    journals: list[dict[str, Any]] = field(default_factory=list)
    owned_namespaces: list[str] = field(default_factory=list)
    sidecar_roles: list[str] = field(default_factory=list)
    fetched_at: float = 0.0
    """Oldest known owner fetch time; 0 when no owner carries a timestamp."""

    def core_request(self) -> dict[str, Any]:
        """Return the ``classify_project_candidates`` wire request."""

        return {
            "schema_version": 1,
            "workflow_type": self.workflow_type,
            "sidecar_roles": list(self.sidecar_roles),
            "owned_namespaces": list(self.owned_namespaces),
            "namespaces": [owner.namespace_wire() for owner in self.owners],
            "remote": [dict(entry) for entry in self.remote],
            "local": [dict(entry) for entry in self.local],
            "projects": [dict(entry) for entry in self.projects],
            "inventory": [dict(entry) for entry in self.inventory],
            "journals": [dict(entry) for entry in self.journals],
        }


def _identity_for_ref(workflow_type: str, ref: str) -> str:
    """Return the provider identity for *ref*, or ``""`` when unparseable."""

    try:
        parsed = workspace_provider.parse_repo_ref(workflow_type, ref)
    except Exception:
        return ""
    return parsed.identity_key if parsed is not None else ""


def identity_for_origin(url: str) -> str:
    """Parse an origin URL through every provider, first match wins."""

    if not url:
        return ""
    try:
        workflow_types = [
            metadata.workflow_type
            for metadata in workspace_provider.get_all_workflow_metadata()
        ]
    except Exception:
        return ""
    for workflow_type in workflow_types:
        identity = _identity_for_ref(workflow_type, url)
        if identity:
            return identity
    return ""


def resolve_git_dir(checkout: str | Path) -> Path | None:
    """Return the git directory for a checkout, including worktree gitfiles."""

    root = Path(checkout)
    git_path = root / ".git"
    try:
        if git_path.is_dir():
            return git_path
        if git_path.is_file():
            resolved = _git_dir_from_gitfile(root, git_path)
            if resolved is not None:
                return resolved
        if (root / "HEAD").is_file() and (root / "config").is_file():
            return root
    except OSError:
        return None
    return None


def read_git_origin_url(checkout: str) -> str:
    """Read the ``origin`` URL from a checkout's git config without git."""

    if not checkout:
        return ""
    for candidate in _git_config_paths(Path(checkout)):
        url = _origin_url_from_config(candidate)
        if url:
            return url
    return ""


def _git_dir_from_gitfile(checkout: Path, gitfile: Path) -> Path | None:
    try:
        text = gitfile.read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.lower().startswith(_GITDIR_PREFIX):
            continue
        raw = stripped.split(":", 1)[1].strip()
        if not raw:
            continue
        git_dir = Path(raw)
        if not git_dir.is_absolute():
            git_dir = checkout / git_dir
        return git_dir
    return None


def _git_config_paths(checkout: Path) -> list[Path]:
    git_dir = resolve_git_dir(checkout)
    if git_dir is None:
        return [checkout / ".git" / "config", checkout / "config"]
    paths = [git_dir / "config"]
    try:
        commondir = (git_dir / "commondir").read_text(encoding="utf-8").strip()
    except OSError:
        commondir = ""
    if commondir:
        common = Path(commondir)
        if not common.is_absolute():
            common = git_dir / common
        paths.append(common / "config")
    return paths


def _origin_url_from_config(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    parser = configparser.ConfigParser()
    try:
        parser.read_string(text)
    except configparser.Error:
        return ""
    for section in parser.sections():
        if section.strip().casefold() == 'remote "origin"':
            try:
                return (parser.get(section, "url") or "").strip()
            except (configparser.NoOptionError, configparser.NoSectionError):
                continue
    return ""


def _fallback_identity_for_key(project_key: str) -> str:
    """Derive a GitHub identity from a ``gh_<owner>__<repo>`` directory key."""

    match = _GH_KEY_RE.match(project_key)
    if match is None:
        return ""
    repo = _REPO_SUFFIX_RE.sub("", match.group("repo"))
    if not match.group("owner") or not repo:
        return ""
    return f"github.com/{match.group('owner')}/{repo}".casefold()


def record_identity_keys(record: ProjectRecordWire) -> list[str]:
    """Return provider identities for one project record's checkout."""

    seen: list[str] = []
    origin = read_git_origin_url(record.workspace_dir or "")
    identity = identity_for_origin(origin)
    if identity:
        seen.append(identity)
    fallback = _fallback_identity_for_key(record.project_name)
    if fallback and fallback not in seen:
        seen.append(fallback)
    return seen


def _owner_of_identity(identity_key: str) -> str:
    """Return the owner segment of a ``host/owner/repo`` identity, if any."""

    parts = identity_key.split("/")
    return parts[1] if len(parts) == 3 and parts[1] else ""


def _github_orgs() -> list[str]:
    """Return configured ``github_orgs`` as a flat name list (fail-open)."""

    try:
        config = load_merged_config()
    except Exception:
        return []
    raw = config.get("github_orgs", [])
    if isinstance(raw, str):
        return [part for part in re.split(r"[\s,]+", raw) if part]
    if isinstance(raw, list):
        return [str(item) for item in raw if str(item)]
    return []


def _owned_namespaces(account: str, projects: list[dict[str, Any]]) -> list[str]:
    """Return ``github_orgs ∪ account ∪ owners of existing projects``."""

    owned: set[str] = set()
    for name in _github_orgs():
        owned.add(name.casefold())
    if account:
        owned.add(account.casefold())
    for project in projects:
        identities = project.get("identity_keys")
        if isinstance(identities, list):
            for identity in identities:
                owner = _owner_of_identity(str(identity))
                if owner:
                    owned.add(owner.casefold())
    return sorted(owned)


def _sidecar_roles() -> list[str]:
    """Return Python's sidecar roles plus ``research`` and ``sdd`` (core owns none)."""

    return [
        PLANS_SIDECAR_ROLE,
        BEADS_SIDECAR_ROLE,
        AGENTS_SIDECAR_ROLE,
        ATTACHMENTS_SIDECAR_ROLE,
        ATTACHMENTS_PRIVATE_SIDECAR_ROLE,
        "research",
        "sdd",
    ]


def journals_dir() -> Path:
    """Return the ownership-journal directory under ``$SASE_HOME``."""

    return owned_journals_dir()


def _resolve_namespaces(
    workflow_type: str,
    *,
    only: list[str] | None,
) -> tuple[str, list[tuple[str, str, str]]]:
    """Return ``(account, [(name, kind_label, host)])`` for discovery.

    The provider's ``account`` is included as a namespace (``kind_label``
    ``"you"``) when it is not already listed, so personal repositories are
    discovered even with an empty ``github_orgs``. An explicit *only* filter
    restricts to the named owners on providers that expose namespaces or an
    account; a requested owner that matches nothing known is still attempted.
    Providers with neither namespaces nor an account ignore the filter.
    """

    try:
        response = workspace_provider.list_ref_namespaces(workflow_type)
    except Exception:
        return "", []
    account = str(getattr(response, "account", "") or "")
    seen: dict[str, tuple[str, str, str]] = {}
    for entry in getattr(response, "entries", ()) or ():
        name = str(getattr(entry, "name", "") or "")
        if not name or name.casefold() in seen:
            continue
        seen[name.casefold()] = (
            name,
            str(getattr(entry, "kind_label", "") or "org"),
            str(getattr(entry, "host", "") or ""),
        )
    if account and account.casefold() not in seen:
        seen[account.casefold()] = (account, "you", "")
    if only is not None:
        if not seen and not account:
            return account, []
        wanted = [name for name in only if name]
        resolved: list[tuple[str, str, str]] = []
        for name in wanted:
            match = seen.get(name.casefold())
            resolved.append(match if match is not None else (name, "org", ""))
        return account, resolved
    return account, [(name, kind, host) for name, kind, host in seen.values()]


def _remote_entry(
    workflow_type: str,
    namespace: str,
    entry: VcsRepoEntry,
) -> dict[str, Any]:
    """Return the core ``remote`` wire dict for one provider list row."""

    payload: dict[str, Any] = {
        "namespace": namespace,
        "identity_key": _identity_for_ref(workflow_type, entry.ref),
        "ref": entry.ref,
        "display": entry.ref,
        "name": entry.name,
        "description": entry.description,
        "visibility": entry.visibility,
        "is_fork": entry.is_fork,
        "is_archived": entry.is_archived,
        "pushed_at": entry.pushed_at or "",
        "repo_id": entry.repo_id,
        "viewer_permission": entry.viewer_permission,
    }
    if entry.is_empty is not None:
        payload["is_empty"] = entry.is_empty
    return payload


def _fetch_owner(
    workflow_type: str,
    namespace: tuple[str, str, str],
    *,
    cache_only: bool,
    refresh: bool,
) -> OwnerResult:
    """Fetch one namespace's candidates, degrading failures to error rows."""

    name, kind_label, host = namespace
    try:
        if cache_only:
            cached = peek_cached_repo_candidates(workflow_type, name, host=host)
            if cached is None:
                return OwnerResult(name=name, kind_label=kind_label, host=host)
            result: Any = cached
        else:
            config = load_vcs_repo_completion_config()
            if refresh:
                config = _replace(config, cache_ttl_seconds=0)
            result = fetch_repo_candidates(
                workflow_type, name, host=host, config=config
            )
        return OwnerResult(
            name=name,
            kind_label=kind_label,
            status=str(result.status),
            error_kind=str(result.error_kind or ""),
            message=str(result.message or ""),
            stale=bool(result.stale),
            host=str(result.host or host),
            truncated=bool(result.truncated),
            remedy_argv=[str(arg) for arg in result.remedy_argv],
            entries=[
                _remote_entry(workflow_type, name, entry) for entry in result.entries
            ],
            fetched_at=float(getattr(result, "fetched_at", 0.0) or 0.0),
        )
    except Exception as exc:
        return OwnerResult(
            name=name,
            kind_label=kind_label,
            status="error",
            error_kind="unknown",
            message=str(exc),
            host=host,
        )


def _local_entries(workflow_type: str) -> list[dict[str, Any]]:
    """Return the core ``local`` wire dicts from the provider's disk scan."""

    try:
        found = workspace_provider.list_local_repo_candidates(workflow_type)
    except Exception:
        return []
    if found is None:
        return []
    entries: list[dict[str, Any]] = []
    for candidate in found.entries:
        entries.append(
            {
                "identity_key": candidate.parsed.identity_key,
                "ref": candidate.parsed.ref,
                "display": candidate.parsed.display,
                "owner": candidate.parsed.owner,
                "name": candidate.parsed.name,
                "path": candidate.path,
                "numbered_copy": candidate.numbered_copy,
            }
        )
    return entries


def _project_entries() -> list[dict[str, Any]]:
    """Return the core ``projects`` wire dicts for every non-system record."""

    try:
        records = list_project_records(sase_projects_dir(), "all")
    except Exception:
        return []
    entries: list[dict[str, Any]] = []
    for record in records:
        if record.system_managed:
            continue
        entries.append(
            {
                "key": record.project_name,
                "name": effective_project_name(record),
                "aliases": list(record.aliases),
                "state": record.state,
                "identity_keys": record_identity_keys(record),
            }
        )
    return entries


def _inventory_entries() -> list[dict[str, Any]]:
    """Return the core ``inventory`` wire dicts for non-primary checkouts."""

    try:
        inventory = collect_repo_inventory(include_disabled=True)
    except Exception:
        return []
    entries: list[dict[str, Any]] = []
    for record in inventory.records:
        if record.kind not in ("sidecar", "linked", "external"):
            continue
        identity = identity_for_origin(read_git_origin_url(record.path))
        if not identity:
            continue
        entries.append(
            {
                "identity_key": identity,
                "kind": record.kind,
                "project_key": record.project_key,
            }
        )
    return entries


def load_candidate_inputs(
    workflow_type: str,
    *,
    cache_only: bool = False,
    refresh: bool = False,
    namespaces: list[str] | None = None,
) -> CandidateInputs:
    """Gather one provider's candidates from cache, disk, and records.

    Args:
        workflow_type: Provider workflow type such as ``"gh"`` or ``"git"``.
        cache_only: Read only fresh caches and local state; never spawn a
            subprocess or touch the network (the TUI hot path and the perf
            guard's contract).
        refresh: Bypass the repo-list cache; a failing owner still keeps its
            stale rows.
        namespaces: Optional owner filter restricting remote discovery.
    """

    try:
        display = workspace_provider.get_display_name(workflow_type) or workflow_type
    except Exception:
        display = workflow_type
    account, resolved = _resolve_namespaces(workflow_type, only=namespaces)
    owners: list[OwnerResult] = []
    if resolved:
        with ThreadPoolExecutor(max_workers=_MAX_DISCOVERY_WORKERS) as pool:
            owners = list(
                pool.map(
                    lambda item: _fetch_owner(
                        workflow_type,
                        item,
                        cache_only=cache_only,
                        refresh=refresh,
                    ),
                    resolved,
                )
            )
    remote: list[dict[str, Any]] = []
    for owner in owners:
        remote.extend(owner.entries)
    stamps = [owner.fetched_at for owner in owners if owner.fetched_at > 0]
    projects = _project_entries()
    return CandidateInputs(
        workflow_type=workflow_type,
        display=display,
        account=account,
        owners=owners,
        fetched_at=min(stamps) if stamps else 0.0,
        remote=remote,
        local=_local_entries(workflow_type),
        projects=projects,
        inventory=_inventory_entries(),
        journals=list_incomplete(),
        owned_namespaces=_owned_namespaces(account, projects),
        sidecar_roles=_sidecar_roles(),
    )


def _suggest_provider(
    workflow_type: str,
    *,
    include_hidden: bool,
    owners: list[str] | None,
    refresh: bool,
    cache_only: bool,
) -> dict[str, Any]:
    """Classify one provider's candidates into the suggest provider payload."""

    inputs = load_candidate_inputs(
        workflow_type,
        cache_only=cache_only,
        refresh=refresh,
        namespaces=owners,
    )
    classified = classify_project_candidates(inputs.core_request())
    payload: dict[str, Any] = {
        "workflow_type": workflow_type,
        "display": inputs.display,
        "account": inputs.account,
        "owners": [owner.to_json_dict() for owner in inputs.owners],
        "groups": classified.get("groups", []),
        "hidden": classified.get("hidden", []),
    }
    if include_hidden:
        payload["search_only"] = classified.get("search_only", [])
    return payload


def suggest(
    *,
    providers: list[str] | None = None,
    include_hidden: bool = False,
    owners: list[str] | None = None,
    refresh: bool = False,
    cache_only: bool = False,
) -> dict[str, Any]:
    """Return the JSON-ready ``sase project suggest`` payload for providers.

    With no *providers*, every registered workspace provider is covered.
    Agents may call this freely: it only reads caches, disk state, and the
    provider list APIs.
    """

    if providers is None:
        ordered = [
            metadata.workflow_type
            for metadata in workspace_provider.get_all_workflow_metadata()
        ]
    else:
        ordered = list(providers)
    return {
        "schema_version": SUGGEST_SCHEMA_VERSION,
        "providers": [
            _suggest_provider(
                workflow_type,
                include_hidden=include_hidden,
                owners=owners,
                refresh=refresh,
                cache_only=cache_only,
            )
            for workflow_type in ordered
        ],
    }


__all__ = [
    "CandidateInputs",
    "OwnerResult",
    "SUGGEST_SCHEMA_VERSION",
    "identity_for_origin",
    "journals_dir",
    "load_candidate_inputs",
    "read_git_origin_url",
    "record_identity_keys",
    "resolve_git_dir",
    "suggest",
]
