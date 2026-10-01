"""Memory history pager provider backed by ``HistoryService``.

Recognizes canonical and legacy project memory, web descriptors and
strands, root/subdirectory AGENTS.md and shims, chezmoi source templates,
and deployed home files from subject/owner provenance rather than title
alone. All git, lineage, selector, and diff semantics stay in
``sase-core``; this module only normalizes wire results into pager
presentation records.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from sase.artifact_ref_target_models import ArtifactRefDocumentOwner
from sase.feature_flags import current_flags
from sase.feature_flags.registry import FeatureFlag
from sase.memory.history.scopes import HistoryScopeError, git_repo_root
from sase.memory.history.service import HistoryService
from sase.memory.history.vocabulary import is_hidden_by_default, label_for
from sase.pager.document import PagerDocument, PagerOrigin, PagerSection
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


def _history_enabled() -> bool:
    try:
        return bool(current_flags().enabled(FeatureFlag.memory_history))
    except Exception:
        return False


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


def visible_ordinals_for_timeline(timeline: dict[str, Any]) -> tuple[int, ...]:
    """Return committed ordinals visible without ``-a/--all`` (pager/CLI shared)."""
    versions = timeline.get("versions", ())
    visible: list[int] = []
    for row in versions:  # type: ignore[union-attr]
        if not isinstance(row, dict):
            continue
        ordinal = int(row.get("ordinal", 0) or 0)
        if ordinal <= 0:
            continue
        hidden = bool(row.get("hidden", False))
        class_name = str(row.get("class", "") or "")
        if hidden or is_hidden_by_default(class_name):
            continue
        visible.append(ordinal)
    return tuple(sorted(visible))


def newest_committed_row(timeline: dict[str, Any]) -> dict[str, Any] | None:
    """Return the newest committed timeline row, if any."""
    best: dict[str, Any] | None = None
    for row in timeline.get("versions", ()):  # type: ignore[union-attr]
        if not isinstance(row, dict):
            continue
        ordinal = int(row.get("ordinal", 0) or 0)
        if ordinal <= 0:
            continue
        if best is None or ordinal > int(best.get("ordinal", 0) or 0):
            best = row
    return best


def is_deleted_row(row: dict[str, Any]) -> bool:
    """Return whether a timeline row is a deletion tombstone."""
    return str(row.get("class", "") or "") == "deleted"


def dirty_now_from_timeline(timeline: dict[str, Any]) -> bool:
    for row in timeline.get("versions", ()):  # type: ignore[union-attr]
        if not isinstance(row, dict):
            continue
        if int(row.get("ordinal", 0) or 0) != 0:
            continue
        status = row.get("status", row.get("state", ""))
        if isinstance(status, dict):
            worktree = str(status.get("worktree", "") or "").lower()
            index = str(status.get("index", "") or "").lower()
            head = str(status.get("head", "") or "").lower()
            if any(
                token in ("dirty", "modified", "added", "deleted", "untracked")
                for token in (worktree, index, head)
            ):
                return True
            # Fall back to explicit dirty markers.
            if bool(status.get("dirty", False)):
                return True
            return False
        text = str(status or "").lower()
        return text not in ("", "clean", "tracked", "notracked")
    return False


class MemoryHistoryProvider:
    """Pager history provider for memory and instruction files."""

    provider_key = "memory-history"

    def __init__(self, service: HistoryService | None = None) -> None:
        self._service = service

    def _require_service(self) -> HistoryService:
        if self._service is None:
            self._service = HistoryService()
        return self._service

    def recognizes(self, section: PagerSection) -> bool:
        if not _history_enabled():
            return False
        try:
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
            return dict(service.timeline(scope, selector, include_hidden=True))
        except Exception as exc:
            return {"versions": [], "error": str(exc)}

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
    commit = version.get("commit") if isinstance(version, dict) else None
    blob_oid = version.get("blob_oid") if isinstance(version, dict) else None
    class_name = (
        str(version.get("class", "") or "") if isinstance(version, dict) else ""
    )
    subject = response.get("subject", {})
    subject_id = str(
        subject.get("id", selector) if isinstance(subject, dict) else selector
    )
    paths = list(subject.get("paths", ()) if isinstance(subject, dict) else ())
    historical_path = paths[0] if paths else selector
    if class_name == "deleted":
        author = str(version.get("author", "") or "unknown").strip() or "unknown"
        epoch = version.get("committer_time", version.get("author_time", ""))
        label = label_for(class_name)
        body = f"✖ {label} by {author} at {epoch} — last content shown\n\n{body}"
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
    subject = resolved.get("subject", {})
    subject_id = str(subject.get("id", ref) if isinstance(subject, dict) else ref)
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


def memory_history_provider_factory() -> MemoryHistoryProvider | None:
    """Entry-point factory: no registration when the beta is off."""
    if not _history_enabled():
        return None
    try:
        service = HistoryService()
    except Exception:
        return None
    return MemoryHistoryProvider(service=service)


def build_history_document(
    *,
    scope: Any,
    subject: str,
    initial_revision: str | None = None,
    view: str = "read",
    compare_base: str | None = None,
    service: HistoryService | None = None,
    title: str | None = None,
) -> PagerDocument:
    """Build a selector-based pager document for later panel/feed phases."""
    active = service or HistoryService()
    selector = subject
    revision = initial_revision or "now"
    try:
        response = active.version(scope, selector, revision, include_body=True)
    except Exception as exc:
        raise HistoryScopeError(f"cannot build history document: {exc}") from exc
    if not response.get("existed", True):
        raise HistoryScopeError(f"history subject {selector!r} does not exist")
    body = str(response.get("body", "") or "")
    if response.get("body_missing"):
        body = f"(unavailable: historical body for {selector} is not stored)"
    version = response.get("version", {})
    ordinal = int(version.get("ordinal", 0) or 0) if isinstance(version, dict) else 0
    owner: ArtifactRefDocumentOwner | None = None
    try:
        repo_root = Path(str(getattr(scope, "repo_root", ".")))
        owner = ArtifactRefDocumentOwner(
            source_reference=selector,
            source_directory=str(repo_root),
            checkout_candidates=(repo_root,),
            revision=version.get("commit")
            if isinstance(version, dict) and isinstance(version.get("commit"), str)
            else None,
        )
    except Exception:
        owner = None
    from sase.pager.history.models import live_pin_for_subject

    if ordinal == 0:
        pin: VersionPin = live_pin_for_subject(subject)
    else:
        pin = committed_pin_for_ordinal(
            subject,
            ordinal,
            commit=version.get("commit") if isinstance(version, dict) else None,
            blob_oid=version.get("blob_oid") if isinstance(version, dict) else None,
            view="read",  # type: ignore[arg-type]
        )
        del view, compare_base
    section = PagerSection(
        identity=f"history:{subject}:{revision}",
        title=title or subject.rsplit("/", 1)[-1],
        kind="file",
        body=body,
        subject_ref=subject,
        raw_source=classify_source(
            category="raw_file", logical_filename="note.md", source=body
        ),
        origin=PagerOrigin.FILE,
        owner=owner,
        version_pin=pin,  # type: ignore[call-arg]
    )
    return PagerDocument(
        sections=(section,),
        title=title or subject,
        origin=PagerOrigin.FILE,
    )


def history_marks_from_comparison(
    comparison: dict[str, Any] | None,
) -> tuple[dict[int, str], set[int]]:
    """Derive read-view gutter marks from a parent comparison.

    ``line_marks`` (1-based) become ``added`` marks unless the line also
    carries word-deletion ops (then ``changed``); ``removal_anchors``
    become red anchor rows. Old-to-new comparisons anchor steps that skip
    hidden versions; parent comparisons feed this gutter — never confuse
    the two purposes.
    """
    if not comparison:
        return {}, set()
    marks: dict[int, str] = {}
    for line in comparison.get("line_marks", ()):  # type: ignore[union-attr]
        try:
            lineno = (
                int(line)
                if not isinstance(line, dict)
                else int(line.get("target_line", 0) or 0)
            )
        except (TypeError, ValueError):
            continue
        if lineno > 0:
            marks[lineno] = "added"
    for entry in comparison.get("word_ops", ()):  # type: ignore[union-attr]
        if not isinstance(entry, dict):
            continue
        try:
            lineno = int(entry.get("target_line", 0) or 0)
        except (TypeError, ValueError):
            continue
        if lineno <= 0:
            continue
        ops = entry.get("ops", ())
        kinds = {
            str(op.get("kind", "") or "").lower() for op in ops if isinstance(op, dict)
        }  # type: ignore[union-attr]
        if "delete" in kinds or "remove" in kinds or "replace" in kinds:
            marks[lineno] = "changed"
        else:
            marks.setdefault(lineno, "added")
    anchors: set[int] = set()
    for anchor in comparison.get("removal_anchors", ()):  # type: ignore[union-attr]
        if isinstance(anchor, dict):
            try:
                after = int(anchor.get("after_target_line", 0) or 0)
            except (TypeError, ValueError):
                continue
            anchors.add(max(after, 0))
        else:
            try:
                anchors.add(max(int(anchor), 0))  # type: ignore[arg-type]
            except (TypeError, ValueError):
                continue
    return marks, anchors


def selector_to_core_selector(raw: str, repo_root: Path) -> str:
    """Share selector conversion with the CLI instead of duplicating parsing."""
    from sase.memory.history.cli_history import translate_history_selector

    return translate_history_selector(raw, repo_root)


__all__ = [
    "MemoryHistoryProvider",
    "build_history_document",
    "dirty_now_from_timeline",
    "history_marks_from_comparison",
    "is_deleted_row",
    "memory_history_provider_factory",
    "newest_committed_row",
    "selector_to_core_selector",
    "visible_ordinals_for_timeline",
]
