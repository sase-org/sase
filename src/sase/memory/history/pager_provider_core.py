"""Memory history pager provider backed by ``HistoryService``.

Split from :mod:`sase.memory.history.pager_provider`: this module owns the
provider class plus its recognition, scope, and version helpers. Timeline
helpers live in :mod:`sase.memory.history.pager_provider_timelines`, the
document builder lives in
:mod:`sase.memory.history.pager_provider_document`, helpers shared by more
than one of the split modules live in
:mod:`sase.memory.history._pager_provider_common`, and the original module
is now a facade re-exporting the public names.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from sase.memory.history._pager_provider_common import (
    wire_history_path,
    wire_subject_id,
)
from sase.memory.history.scopes import HistoryScopeError, git_repo_root
from sase.memory.history.service import HistoryService
from sase.pager.document import PagerSection
from sase.pager.history.models import VersionPin, committed_pin_for_ordinal
from sase.pager.syntax_policy import classify_source

_MEMORY_ROOT_MARKERS = ("sase/memory/", "memory/")
_INSTRUCTION_NAMES = (
    "AGENTS.md",
    "CLAUDE.md",
    "GEMINI.md",
    "QWEN.md",
    "OPENCODE.md",
)
_SHIM_SUFFIXES = (".md", ".yml", ".yaml", ".toml")
_HOME_TEMPLATE_SUFFIX = ".tmpl"


def _section_text_parts(section: PagerSection) -> tuple[str, ...]:
    parts = [section.identity, section.title, section.subject_ref or ""]
    owner = section.owner
    if owner is not None:
        if owner.source_reference:
            parts.append(owner.source_reference)
        if owner.source_directory:
            parts.append(owner.source_directory)
    return tuple(part for part in parts if part)


def _looks_like_memory_path(value: str) -> bool:
    normalized = value.replace("\\", "/")
    for marker in _MEMORY_ROOT_MARKERS:
        if marker in normalized:
            return True
    basename = normalized.rsplit("/", 1)[-1]
    if basename in _INSTRUCTION_NAMES:
        return True
    if normalized.endswith(_HOME_TEMPLATE_SUFFIX) and "AGENTS" in basename:
        return True
    for name in _INSTRUCTION_NAMES:
        if basename == name:
            return True
        if basename.startswith(name.removesuffix(".md")) and basename.endswith(
            _SHIM_SUFFIXES
        ):
            return True
    # Web descriptors/strands: sase/memory/<web>.md or <web>/<keyword>.md
    # already covered by the memory-root marker above.
    return False


def _pin_carries_memory_subject(section: PagerSection) -> bool:
    """Return whether the section pin names a memory-history subject.

    Sections built by ``build_history_document`` carry the wire
    subject id (``note:``, ``web:``, ``strand:``, ``instructions:``) on
    their pin whatever the selector's spelling, so short selectors like
    ``decisions`` attach even though no path text names the memory root.
    """
    from sase.pager.history.moment import MEMORY_SUBJECT_PREFIXES

    pin = section.version_pin
    if pin is None:
        return False
    subject_id = str(getattr(pin, "subject_id", "") or "")
    return subject_id.startswith(MEMORY_SUBJECT_PREFIXES)


def _recognizes_section(section: PagerSection) -> bool:
    for part in _section_text_parts(section):
        if _looks_like_memory_path(part):
            return True
    owner = section.owner
    if owner is not None and owner.source_directory:
        try:
            resolved = Path(owner.source_directory).expanduser()
        except Exception:
            return False
        text = str(resolved).replace("\\", "/")
        if _looks_like_memory_path(text):
            return True
    return False


def _owning_checkout(section: PagerSection) -> Path | None:
    owner = section.owner
    candidates: list[Path] = []
    if owner is not None:
        for checkout in owner.checkout_candidates or ():
            try:
                candidates.append(Path(checkout).expanduser())
            except Exception:
                continue
        if owner.source_directory:
            try:
                directory = Path(owner.source_directory).expanduser()
                candidates.append(directory if directory.is_dir() else directory.parent)
            except Exception:
                pass
    for candidate in candidates:
        try:
            root = git_repo_root(candidate)
        except Exception:
            continue
        if root is not None:
            return root
    return None


def _scope_for_section(service: HistoryService, section: PagerSection) -> Any | None:
    checkout = _owning_checkout(section)
    if checkout is None:
        return None
    try:
        return service.project_scope(checkout)
    except HistoryScopeError:
        return None
    except Exception:
        return None


def _instruction_file_traits(
    scope: Any, selector: str
) -> tuple[bool | None, bool | None]:
    """Return ``(template, managed)`` for an instruction-file selector.

    ``(None, None)`` means the selector is not an instruction file. Chezmoi
    ``*.tmpl`` sources are always templates; a ``managed=False`` instruction
    file is a hand-edited subdirectory ``AGENTS.md``.
    """
    normalized = selector.replace("\\", "/").strip().lstrip("./")
    candidates = [normalized, normalized.removesuffix(".tmpl")]
    instruction_files = getattr(scope, "instruction_files", ()) or ()
    for entry in instruction_files:
        agents_path = str(getattr(entry, "agents_path", "") or "").lstrip("./")
        shim_paths = [
            str(path).lstrip("./") for path in getattr(entry, "shim_paths", ())
        ]
        for candidate in candidates:
            if candidate == agents_path or candidate in shim_paths:
                is_template = bool(getattr(entry, "template", False))
                if candidate != normalized:
                    is_template = True
                return (is_template, bool(getattr(entry, "managed", False)))
    return (None, None)


def _selector_for_section(section: PagerSection) -> str | None:
    ref = section.subject_ref or section.identity
    # Subject refs are file: URIs or repo-relative paths; strip the scheme.
    for prefix in ("file:",):
        if ref.startswith(prefix):
            ref = ref[len(prefix) :]
    # Prefer a repo-relative path when the owner knows the checkout.
    checkout = _owning_checkout(section)
    if checkout is not None:
        try:
            absolute = Path(ref).expanduser()
            if absolute.is_absolute():
                try:
                    return absolute.relative_to(checkout).as_posix()
                except ValueError:
                    pass
        except Exception:
            pass
    # Fall back to basename/relative text core can resolve historically.
    text = ref.replace("\\", "/").strip()
    if not text:
        return None
    return text


class _MemoryHistoryProvider:
    """Pager history provider for memory and instruction files."""

    provider_key = "memory-history"

    def __init__(self, service: HistoryService | None = None) -> None:
        self._service = service

    def _require_service(self) -> HistoryService:
        if self._service is None:
            self._service = HistoryService()
        return self._service

    def recognizes(self, section: PagerSection) -> bool:
        try:
            if _pin_carries_memory_subject(section):
                return True
            return _recognizes_section(section)
        except Exception:
            return False

    def load_timeline(self, section: PagerSection) -> dict[str, Any]:
        service = self._require_service()
        scope = _scope_for_section(service, section)
        selector = _selector_for_section(section)
        if scope is None or selector is None:
            return {"versions": [], "error": "unsupported"}
        try:
            timeline = dict(service.timeline(scope, selector, include_hidden=True))
        except Exception as exc:
            return {"versions": [], "error": str(exc)}
        try:
            sync = service.sync(scope)
            timeline["upstream_ahead"] = sync.get("upstream_ahead")
            timeline["health"] = sync.get("health")
        except Exception:
            pass
        try:
            template, managed = _instruction_file_traits(scope, selector)
            if template is not None:
                timeline["is_template"] = template
            if managed is not None:
                timeline["managed"] = managed
        except Exception:
            pass
        return timeline

    def load_version(self, section: PagerSection, ordinal: int) -> PagerSection | None:
        service = self._require_service()
        scope = _scope_for_section(service, section)
        selector = _selector_for_section(section)
        if scope is None or selector is None:
            return None
        try:
            if ordinal == 0:
                response = service.version(scope, selector, "now", include_body=True)
            else:
                response = service.version(
                    scope, selector, f"v{ordinal}", include_body=True
                )
        except Exception:
            return None
        return _derived_section(section, scope, selector, ordinal, response)

    def compare_versions(
        self, section: PagerSection, base_ordinal: int, target_ordinal: int
    ) -> dict[str, Any] | None:
        service = self._require_service()
        scope = _scope_for_section(service, section)
        selector = _selector_for_section(section)
        if scope is None or selector is None:
            return None
        try:
            if base_ordinal <= 0:
                return _compare_against_empty(selector, target_ordinal, service, scope)
            base_arg = "now" if base_ordinal == 0 else f"v{base_ordinal}"
            target_arg = "now" if target_ordinal == 0 else f"v{target_ordinal}"
            compared = service.compare(scope, selector, base_arg, selector, target_arg)
            return dict(compared.get("comparison", compared))
        except Exception:
            return None

    def resolve_historical_link(
        self, section: PagerSection, ref: str
    ) -> PagerSection | None:
        from sase.pager.history.provider import HistoryMissingError

        pin = section.version_pin
        if pin is None or getattr(pin, "ordinal", 0) == 0:
            return None
        # Beads, agents, URLs, plans, and other-scope targets stay on
        # their normal resolvers; only same-scope file/memory refs enter
        # historical resolution.
        lowered = ref.lower()
        if lowered.startswith(
            ("bead:", "agent:", "http://", "https://", "plan:", "commit:")
        ):
            return None
        commit = getattr(pin, "commit", None)
        if not commit:
            return None
        service = self._require_service()
        scope = _scope_for_section(service, section)
        if scope is None:
            return None
        try:
            resolved = service.resolve(scope, ref, at_commit=commit)
        except Exception as exc:
            raise HistoryMissingError(f"{ref} is not present at {commit[:7]}") from exc
        version = resolved.get("version", {})
        if not isinstance(version, dict):
            raise HistoryMissingError(f"{ref} has no version at {commit[:7]}")
        if not resolved.get("existed", True):
            raise HistoryMissingError(f"{ref} did not exist at {commit[:7]}")
        derived = _derived_section_from_resolve(section, scope, ref, resolved)
        if derived is None:
            raise HistoryMissingError(f"{ref} is not present at {commit[:7]}")
        return derived

    def refresh(self, section: PagerSection) -> PagerSection | None:
        service = self._require_service()
        try:
            scope = _scope_for_section(service, section)
            if scope is not None:
                service.sync(scope)
        except Exception:
            pass
        return self.load_version(section, 0)


def _derived_section(
    section: PagerSection,
    scope: Any,
    selector: str,
    ordinal: int,
    response: dict[str, Any],
) -> PagerSection | None:
    if not response.get("existed", True):
        return None
    if response.get("body_missing"):
        body = f"(unavailable: historical body for {selector} is not stored)"
    else:
        body = str(response.get("body", "") or "")
    version = response.get("version", {})
    if not isinstance(version, dict):
        version = {}
    commit = version.get("commit")
    blob_oid = version.get("blob_oid")
    subject_id = wire_subject_id(response, selector)
    historical_path = wire_history_path(response, selector)
    # Deletions surface through band tombstone chrome (the pill and the
    # ``✖ deleted … showing last content`` row); the body stays exactly
    # the last content so line numbers, search, and copy match the file.
    pin: VersionPin = committed_pin_for_ordinal(
        subject_id,
        ordinal,
        commit=commit if isinstance(commit, str) else None,
        blob_oid=blob_oid if isinstance(blob_oid, str) else None,
    )
    if ordinal == 0:
        from sase.pager.history.models import live_pin_for_subject

        pin = live_pin_for_subject(subject_id)
    owner = section.owner
    if owner is not None:
        parent = historical_path.rsplit("/", 1)[0] or "."
        try:
            owner = replace(
                owner,
                revision=commit if isinstance(commit, str) else owner.revision,
                source_directory=str(
                    Path(str(getattr(scope, "repo_root", "."))) / parent
                ),
            )
        except Exception:
            pass
    return PagerSection(
        identity=section.identity,
        title=historical_path.rsplit("/", 1)[-1] or section.title,
        kind=section.kind,
        body=body,
        subject_ref=section.subject_ref,
        link_anchors=section.link_anchors,
        raw_source=section.raw_source,
        origin=section.origin,
        owner=owner,
        known_kinds=section.known_kinds,
        version_pin=pin,  # type: ignore[call-arg]
    )


def _derived_section_from_resolve(
    section: PagerSection, scope: Any, ref: str, resolved: dict[str, Any]
) -> PagerSection | None:
    version = resolved.get("version", {})
    if not isinstance(version, dict):
        return None
    ordinal = int(version.get("ordinal", 0) or 0)
    commit = version.get("commit")
    subject_id = wire_subject_id(resolved, ref)
    body = str(resolved.get("body", "") or "")
    pin: VersionPin = committed_pin_for_ordinal(
        subject_id,
        ordinal,
        commit=commit if isinstance(commit, str) else None,
        blob_oid=version.get("blob_oid")
        if isinstance(version.get("blob_oid"), str)
        else None,
    )
    owner = section.owner
    if owner is not None and isinstance(commit, str):
        try:
            owner = replace(owner, revision=commit)
        except Exception:
            pass
    return PagerSection(
        identity=f"history:{subject_id}:v{ordinal}",
        title=ref.rsplit("/", 1)[-1] or ref,
        kind=section.kind,
        body=body,
        subject_ref=ref,
        raw_source=classify_source(
            category="raw_file", logical_filename="note.md", source=body
        ),
        origin=section.origin,
        owner=owner,
        known_kinds=section.known_kinds,
        version_pin=pin,  # type: ignore[call-arg]
    )


def _compare_against_empty(
    selector: str, target_ordinal: int, service: HistoryService, scope: Any
) -> dict[str, Any] | None:
    try:
        from sase.core.rust import require_rust_binding

        target = service.version(
            scope, selector, f"v{target_ordinal}", include_body=True
        )
        body = str(target.get("body", "") or "")
        binding = require_rust_binding("compare_prose")
        return dict(
            binding({"base": "", "target": body, "format": "prose", "context_lines": 3})
        )
    except Exception:
        return None


def memory_history_provider_factory() -> _MemoryHistoryProvider:
    """Entry-point factory for the memory history pager provider."""
    try:
        service = HistoryService()
    except Exception:
        return _MemoryHistoryProvider(service=None)
    return _MemoryHistoryProvider(service=service)
