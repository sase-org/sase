"""Contextual ref renderer registry for xprompt catalog consumers."""

from __future__ import annotations

import importlib.resources
import logging
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from sase._linked_repo_config import resolution_config
from sase.content_layout import (
    RefSource,
    discover_project_root,
    resolve_ref_file_sources,
)
from sase.main.plugin_discovery import discover_plugin_resources, is_plugin_disabled
from sase.sdd.plan_refs import workspace_context_for_plan_resolution
from sase.sdd.store import resolve_sdd_store
from sase.sidecar_ref_config import (
    BUILTIN_REF_INPUTS,
    DEFAULT_DOCUMENT_REF_RENDERER,
    SIDECAR_REF_CONFIG_SOURCE_PREFIX,
    SidecarRefPolicy,
    canonical_ref_input,
    effective_sidecar_ref_policies,
)
from sase.xprompt.load_issues import record_load_issue
from sase.xprompt.loader_parsing import (
    parse_yaml_front_matter_with_error,
)
from sase.xprompt.models import InputArg, InputType, XPrompt

log = logging.getLogger(__name__)

REF_LOAD_ISSUE_KIND = "ref"
GENERATED_REF_SOURCE_PREFIX = "generated_sidecar_ref:"
_REF_KIND_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True, slots=True)
class _RefCandidate:
    ref_kind: str
    content: str
    source_path: str
    description: str | None = None
    sidecar_role: str | None = None
    path_globs: tuple[str, ...] | None = None


def get_sase_package_refs_dir(package_root: Path | None = None) -> Path:
    """Return the packaged contextual ref renderer source directory."""
    candidate = (
        Path(package_root) / "xprompts" / "refs"
        if package_root is not None
        else Path(str(importlib.resources.files("sase").joinpath("xprompts", "refs")))
    )
    if candidate.is_dir():
        return candidate
    log.warning(
        "Packaged refs directory not found via "
        "importlib.resources('sase/xprompts/refs')",
    )
    return candidate


def load_ref_xprompts(
    project: str | None = None,
    *,
    project_root: Path | str | None = None,
    home_root: Path | str | None = None,
) -> dict[str, XPrompt]:
    """Load the effective contextual ``ref/<kind>`` registry.

    The returned entries are catalog metadata only; prompt expansion does not
    include them unless callers explicitly opt in.
    """
    root = _project_root(project_root)
    policies = _sidecar_policies(root)
    known_kinds = frozenset((*BUILTIN_REF_INPUTS, *(p.ref_kind for p in policies)))
    registry: dict[str, XPrompt] = {}
    inserted_config = False
    for source in resolve_ref_file_sources(
        project_root=root,
        home_root=home_root,
        project=project,
        include_resource_sources=True,
    ):
        if not inserted_config and source.scope != "project":
            _merge_candidates(
                registry, _sidecar_config_candidates(policies), known_kinds
            )
            inserted_config = True
        _merge_candidates(
            registry,
            _source_candidates(source),
            known_kinds,
        )
    if not inserted_config:
        _merge_candidates(registry, _sidecar_config_candidates(policies), known_kinds)

    _merge_candidates(registry, _generated_sidecar_candidates(policies), known_kinds)
    return registry


def reject_misplaced_ref(xprompt: XPrompt, *, source: Path | str) -> bool:
    """Return whether an ordinary source illegally declares or claims refs."""
    if xprompt.ref:
        record_load_issue(
            source,
            "ref: true definitions must live in a refs/ source directory",
            kind=REF_LOAD_ISSUE_KIND,
        )
        return True
    if xprompt.name.startswith("ref/"):
        record_load_issue(
            source,
            "ordinary xprompts cannot claim the reserved ref/ namespace",
            kind=REF_LOAD_ISSUE_KIND,
        )
        return True
    return False


def _project_root(project_root: Path | str | None) -> Path | None:
    if project_root is not None:
        return Path(project_root).expanduser().resolve(strict=False)
    discovered = discover_project_root()
    if discovered is not None:
        return discovered
    try:
        return Path.cwd().resolve(strict=False)
    except OSError:
        return None


def _sidecar_policies(root: Path | None) -> tuple[SidecarRefPolicy, ...]:
    if root is None:
        return ()
    workspace, workspace_num = workspace_context_for_plan_resolution(root)
    try:
        store = resolve_sdd_store(workspace, workspace_num)
        roles = store.split_sidecar_roles()
    except Exception:
        roles = ()
    try:
        config = resolution_config(str(workspace), None)
    except Exception:
        config = {}
    try:
        from sase.content_layout import resolve_project_config_read_path

        source_path = resolve_project_config_read_path(workspace)
    except Exception:
        source_path = None
    policies = effective_sidecar_ref_policies(
        config,
        primary_workspace_dir=workspace,
        roles=roles,
        source_path=source_path,
    )
    return tuple(policies.values())


def _source_candidates(source: RefSource) -> Iterator[_RefCandidate]:
    if source.scope == "plugin":
        yield from _plugin_ref_candidates()
        return
    if source.scope == "package":
        yield from _directory_candidates(get_sase_package_refs_dir())
        return
    if source.path is None:
        return
    yield from _directory_candidates(source.path)


def _directory_candidates(directory: Path) -> Iterator[_RefCandidate]:
    if not directory.is_dir():
        return
    for md_file in sorted(directory.glob("*.md")):
        if not md_file.is_file():
            continue
        candidate = _candidate_from_markdown(md_file, source_path=str(md_file))
        if candidate is not None:
            yield candidate


def _plugin_ref_candidates() -> Iterator[_RefCandidate]:
    if is_plugin_disabled("XPROMPTS"):
        return
    for module in discover_plugin_resources("sase_xprompts"):
        try:
            resource = importlib.resources.files(module).joinpath("refs")
        except (TypeError, AttributeError):
            continue
        try:
            entries = list(resource.iterdir())  # type: ignore[union-attr]
        except (FileNotFoundError, OSError, TypeError, NotADirectoryError):
            continue
        for entry in sorted(entries, key=lambda item: item.name):  # type: ignore[union-attr]
            if not entry.name.endswith(".md"):  # type: ignore[union-attr]
                continue
            try:
                text = entry.read_text(encoding="utf-8")  # type: ignore[union-attr]
            except (OSError, UnicodeDecodeError):
                continue
            source_path = f"plugin:{module.__name__}/refs/{entry.name}"  # type: ignore[union-attr]
            candidate = _candidate_from_text(
                text,
                ref_kind=entry.name.removesuffix(".md"),  # type: ignore[union-attr]
                source_path=source_path,
            )
            if candidate is not None:
                yield candidate


def _candidate_from_markdown(
    path: Path,
    *,
    source_path: str,
) -> _RefCandidate | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        record_load_issue(path, exc, kind=REF_LOAD_ISSUE_KIND)
        return None
    return _candidate_from_text(text, ref_kind=path.stem, source_path=source_path)


def _candidate_from_text(
    text: str,
    *,
    ref_kind: str,
    source_path: str,
) -> _RefCandidate | None:
    front_matter, body, error = parse_yaml_front_matter_with_error(text)
    if error is not None:
        record_load_issue(
            source_path,
            f"invalid YAML frontmatter: {error}",
            kind=REF_LOAD_ISSUE_KIND,
        )
        return None
    if not front_matter or not bool(front_matter.get("ref")):
        record_load_issue(
            source_path,
            "ref renderer files must declare ref: true",
            kind=REF_LOAD_ISSUE_KIND,
        )
        return None
    description = front_matter.get("description")
    return _RefCandidate(
        ref_kind=ref_kind,
        content=body,
        source_path=source_path,
        description=str(description) if description is not None else None,
    )


def _sidecar_config_candidates(
    policies: Iterable[SidecarRefPolicy],
) -> Iterator[_RefCandidate]:
    for policy in policies:
        if policy.xprompt is None:
            continue
        yield _RefCandidate(
            ref_kind=policy.ref_kind,
            content=policy.xprompt,
            source_path=policy.source_id,
            description=f"Configured renderer for {policy.role}",
            sidecar_role=policy.role,
            path_globs=policy.path_globs,
        )


def _generated_sidecar_candidates(
    policies: Iterable[SidecarRefPolicy],
) -> Iterator[_RefCandidate]:
    for policy in policies:
        if not policy.is_document:
            continue
        yield _RefCandidate(
            ref_kind=policy.ref_kind,
            content=DEFAULT_DOCUMENT_REF_RENDERER,
            source_path=f"{GENERATED_REF_SOURCE_PREFIX}{policy.role}",
            description=f"Generated document renderer for {policy.role}",
            sidecar_role=policy.role,
            path_globs=policy.path_globs,
        )


def _merge_candidates(
    registry: dict[str, XPrompt],
    candidates: Iterable[_RefCandidate],
    known_kinds: frozenset[str],
) -> None:
    for candidate in candidates:
        if not _valid_ref_kind(candidate.ref_kind, candidate.source_path, known_kinds):
            continue
        name = f"ref/{candidate.ref_kind}"
        if name in registry:
            registry[name].ref_shadowed_sources = (
                *registry[name].ref_shadowed_sources,
                candidate.source_path,
            )
            continue
        registry[name] = _candidate_xprompt(candidate, name=name)


def _valid_ref_kind(
    ref_kind: str,
    source_path: str,
    known_kinds: frozenset[str],
) -> bool:
    if not _REF_KIND_RE.fullmatch(ref_kind):
        record_load_issue(
            source_path,
            f"invalid ref kind {ref_kind!r}; use an identifier-compatible filename stem",
            kind=REF_LOAD_ISSUE_KIND,
        )
        return False
    if ref_kind not in known_kinds:
        record_load_issue(
            source_path,
            f"unknown ref kind {ref_kind!r}",
            kind=REF_LOAD_ISSUE_KIND,
        )
        return False
    return True


def _candidate_xprompt(candidate: _RefCandidate, *, name: str) -> XPrompt:
    input_name = canonical_ref_input(candidate.ref_kind)
    return XPrompt(
        name=name,
        content=candidate.content,
        inputs=[InputArg(name=input_name, type=_input_type(input_name))],
        source_path=candidate.source_path,
        description=candidate.description,
        ref=True,
        ref_kind=candidate.ref_kind,
        ref_sidecar_role=candidate.sidecar_role,
        ref_path_globs=candidate.path_globs,
    )


def _input_type(name: str) -> InputType:
    if name == "file_path":
        return InputType.PATH
    if name == "agent_name":
        return InputType.AGENT
    return InputType.WORD


__all__ = [
    "GENERATED_REF_SOURCE_PREFIX",
    "REF_LOAD_ISSUE_KIND",
    "get_sase_package_refs_dir",
    "load_ref_xprompts",
    "reject_misplaced_ref",
]
