"""Shared helpers for AMD initialization modules."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

import yaml  # type: ignore[import-untyped]

from sase._yaml_safe import yaml_safe_load
from sase.config import core as config_core
from sase.main.init_plan import InitAction

from ._agents_doc import is_managed_agents_document
from .constants import (
    AGENTS_FILENAME,
    AGENTS_SOURCE_FILENAMES,
    AGENTS_TEMPLATE_FILENAME,
    CHEZMOI_PROVIDER_SHIM_TEMPLATE_CONTENT,
    HOME_PROVIDER_SHIM_CONTENT,
    PROVIDER_SHIM_CONTENT,
    PROVIDER_SHIM_FILES,
)

# Legacy ``@``-import provider shim texts. Provider files are now full copies of
# ``AGENTS.md``; these strings are retained only so existing legacy shims are
# recognized and migrated to full copies (or deleted) by ``provider_shim_plan``.
_PROVIDER_SHIM_TEXTS = frozenset(
    {
        PROVIDER_SHIM_CONTENT.strip(),
        HOME_PROVIDER_SHIM_CONTENT.strip(),
        CHEZMOI_PROVIDER_SHIM_TEMPLATE_CONTENT.strip(),
    }
)
_ABSOLUTE_AGENTS_IMPORT_RE = re.compile(r"^@/.+/AGENTS\.md$")
_CHEZMOI_GENERATED_TITLE_RE = re.compile(
    r"^\{\{.*\.chezmoi\.hostname.*\}\}# .+\{\{ end \}\}$"
)


@dataclass(frozen=True)
class _PlannedWrite:
    path: Path
    content: str
    action: InitAction


@dataclass(frozen=True)
class _PlannedDelete:
    path: Path
    action: InitAction
    expected_content: str | None = None
    allow_custom: bool = False


@dataclass(frozen=True)
class _ProviderShimSpec:
    """Preferred and legacy source paths for one provider instruction shim."""

    filename: str
    path: Path
    content: str
    legacy_paths: tuple[Path, ...] = ()


@dataclass(frozen=True)
class ProviderShimPlan:
    writes: tuple[_PlannedWrite, ...]
    deletes: tuple[_PlannedDelete, ...]
    blockers: tuple[str, ...] = ()
    source_path: Path | None = None

    @property
    def actions(self) -> tuple[InitAction, ...]:
        return tuple(write.action for write in self.writes) + tuple(
            delete.action for delete in self.deletes
        )


@dataclass(frozen=True)
class AmdMemoryFrontmatterUpdate:
    """Planned frontmatter update for a memory note."""

    path: Path
    content: str


@dataclass(frozen=True)
class AmdMemorySyncPlan:
    """Files needed to keep AMD-managed memory blocks synchronized."""

    title: str | None
    agents_content: str | None
    frontmatter_updates: tuple[AmdMemoryFrontmatterUpdate, ...]
    blockers: tuple[str, ...] = ()
    fallback_agents_content: str | None = None


def read_text(path: Path) -> tuple[str | None, str | None]:
    try:
        return path.read_text(encoding="utf-8"), None
    except OSError as exc:
        return None, f"{path}: failed to read file: {exc}"
    except UnicodeDecodeError as exc:
        return None, f"{path}: failed to decode as UTF-8: {exc}"


def load_yaml_mapping(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    text, read_error = read_text(path)
    if read_error is not None or text is None:
        return None, read_error
    try:
        data = yaml_safe_load(text or "")
    except yaml.YAMLError as exc:
        return None, f"{path}: failed to parse YAML: {exc}"
    if data is None:
        return None, None
    if not isinstance(data, dict):
        return None, f"{path}: expected a YAML mapping at the top level"
    return data, None


def _resolved(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def is_chezmoi_home_root(
    root: Path,
    *,
    chezmoi_home_roots: Iterable[Path] = (),
) -> bool:
    root_resolved = _resolved(root)
    for candidate in (config_core.CHEZMOI_HOME, *chezmoi_home_roots):
        if root_resolved == _resolved(candidate):
            return True
    return False


def existing_agents_path(root: Path) -> Path | None:
    """Return the on-disk agents source, preferring a chezmoi ``.tmpl`` file."""
    template_path = root / AGENTS_TEMPLATE_FILENAME
    if template_path.exists():
        return template_path
    agents_path = root / AGENTS_FILENAME
    if agents_path.exists():
        return agents_path
    return None


def is_root_agents_filename(name: str) -> bool:
    """Return whether *name* is a root ``AGENTS.md`` or ``AGENTS.md.tmpl`` file."""
    return name in AGENTS_SOURCE_FILENAMES


def provider_shim_specs(
    root: Path,
    *,
    agents_content: str,
    chezmoi_home_roots: Iterable[Path] = (),
    prefer_templates: bool = False,
) -> tuple[_ProviderShimSpec, ...]:
    """Return provider instruction specs that copy the root's ``AGENTS.md``.

    Each provider file (``CLAUDE.md`` etc.) is a byte-for-byte copy of
    *agents_content*, the root's final ``AGENTS.md`` content. Chezmoi home
    roots without machine-specific titles use a **static** preferred file
    (``CLAUDE.md``, not ``CLAUDE.md.tmpl``) and list the old ``.tmpl`` source
    as a legacy path to migrate away from. When *prefer_templates* is true,
    that preference flips so chezmoi evaluates the H1 hostname switch.
    Legacy ``@AGENTS.md``-style shims are still recognized (see
    ``_is_provider_shim_text``) so existing files migrate cleanly.
    """
    if prefer_templates:
        return tuple(
            _ProviderShimSpec(
                filename=filename,
                path=root / f"{filename}.tmpl",
                content=agents_content,
                legacy_paths=(root / filename,),
            )
            for filename in PROVIDER_SHIM_FILES
        )

    if is_chezmoi_home_root(root, chezmoi_home_roots=chezmoi_home_roots):
        return tuple(
            _ProviderShimSpec(
                filename=filename,
                path=root / filename,
                content=agents_content,
                legacy_paths=(root / f"{filename}.tmpl",),
            )
            for filename in PROVIDER_SHIM_FILES
        )

    return tuple(
        _ProviderShimSpec(
            filename=filename,
            path=root / filename,
            content=agents_content,
        )
        for filename in PROVIDER_SHIM_FILES
    )


def _is_provider_shim_text(text: str) -> bool:
    normalized = text.strip()
    return normalized in _PROVIDER_SHIM_TEXTS or bool(
        _ABSOLUTE_AGENTS_IMPORT_RE.fullmatch(normalized)
    )


def _is_legacy_generated_chezmoi_copy(text: str, *, expected_content: str) -> bool:
    title, separator, body = text.partition("\n")
    expected_title, expected_separator, expected_body = expected_content.partition("\n")
    if not separator or not expected_separator or body != expected_body:
        return False
    if not expected_title.startswith("# "):
        return False
    return bool(_CHEZMOI_GENERATED_TITLE_RE.fullmatch(title))


def _provider_state_for_text(
    text: str,
    *,
    expected_content: str,
    preferred: bool,
) -> str:
    if preferred and text == expected_content:
        return "exact_shim"
    if _is_provider_shim_text(text):
        return "shim"
    if not preferred and _is_legacy_generated_chezmoi_copy(
        text, expected_content=expected_content
    ):
        return "shim"
    return "custom"


def _provider_path_status(
    path: Path,
    *,
    expected_content: str,
    preferred: bool,
) -> tuple[str, str | None]:
    if not path.exists():
        return "missing", None
    text, error = read_text(path)
    if error is not None or text is None:
        return "custom", error or f"{path}: failed to read file"
    return (
        _provider_state_for_text(
            text,
            expected_content=expected_content,
            preferred=preferred,
        ),
        None,
    )


def provider_status_for_spec(spec: _ProviderShimSpec) -> tuple[str, str | None]:
    preferred_state, preferred_error = _provider_path_status(
        spec.path,
        expected_content=spec.content,
        preferred=True,
    )
    if preferred_state != "missing" or preferred_error is not None:
        return preferred_state, preferred_error
    for legacy_path in spec.legacy_paths:
        legacy_state, legacy_error = _provider_path_status(
            legacy_path,
            expected_content=spec.content,
            preferred=False,
        )
        if legacy_state != "missing" or legacy_error is not None:
            return legacy_state, legacy_error
    return "missing", None


def _action_for_write(path: Path, content: str, *, detail: str) -> InitAction | None:
    if not path.exists():
        return InitAction(path=path, operation="create", detail=detail)
    current, _error = read_text(path)
    if current == content:
        return None
    return InitAction(path=path, operation="overwrite", detail=detail)


def _planned_write(path: Path, content: str, *, detail: str) -> _PlannedWrite | None:
    action = _action_for_write(path, content, detail=detail)
    if action is None:
        return None
    return _PlannedWrite(path=path, content=content, action=action)


def _planned_delete(
    path: Path,
    *,
    detail: str,
    expected_content: str | None = None,
    allow_custom: bool = False,
) -> _PlannedDelete | None:
    if not path.exists():
        return None
    return _PlannedDelete(
        path=path,
        action=InitAction(path=path, operation="delete", detail=detail),
        expected_content=expected_content,
        allow_custom=allow_custom,
    )


def apply_planned_delete(delete: _PlannedDelete) -> tuple[bool, str | None]:
    if not delete.path.exists():
        return False, None
    current, error = read_text(delete.path)
    if error is not None or current is None:
        return False, error or f"{delete.path}: failed to read file before delete"

    if delete.allow_custom:
        can_delete = current == delete.expected_content or _is_provider_shim_text(
            current
        )
    else:
        can_delete = _is_provider_shim_text(current)
    if not can_delete:
        return (
            False,
            f"{delete.path}: refusing to delete custom provider instruction content",
        )

    try:
        delete.path.unlink()
    except OSError as exc:
        return False, f"{delete.path}: failed to delete file: {exc}"
    return True, None


def _shim_plan_conflict(
    spec: _ProviderShimSpec,
    *,
    migrated_paths: set[Path],
) -> str | None:
    preferred_resolved = _resolved(spec.path)
    if preferred_resolved in migrated_paths:
        return None
    preferred_state, _error = _provider_path_status(
        spec.path,
        expected_content=spec.content,
        preferred=True,
    )
    if preferred_state != "custom":
        return None
    existing_legacy = tuple(path for path in spec.legacy_paths if path.exists())
    if not existing_legacy:
        return None
    legacy_names = ", ".join(path.name for path in existing_legacy)
    return (
        f"{spec.path}: custom provider instruction file conflicts with "
        f"legacy provider shim source {legacy_names}"
    )


def provider_shim_plan(
    root: Path,
    *,
    agents_content: str,
    chezmoi_home_roots: Iterable[Path] = (),
    migrated_paths: Iterable[Path] = (),
    prefer_templates: bool = False,
) -> ProviderShimPlan:
    writes: list[_PlannedWrite] = []
    deletes: list[_PlannedDelete] = []
    blockers: list[str] = []
    migrated_resolved = {_resolved(path) for path in migrated_paths}
    source_path = (
        root / AGENTS_TEMPLATE_FILENAME if prefer_templates else root / AGENTS_FILENAME
    )

    for spec in provider_shim_specs(
        root,
        agents_content=agents_content,
        chezmoi_home_roots=chezmoi_home_roots,
        prefer_templates=prefer_templates,
    ):
        conflict = _shim_plan_conflict(spec, migrated_paths=migrated_resolved)
        if conflict is not None:
            blockers.append(conflict)

        write = _planned_write(
            spec.path,
            spec.content,
            detail="provider instruction shim",
        )
        if write is not None:
            writes.append(write)

        for legacy_path in spec.legacy_paths:
            if not legacy_path.exists():
                continue
            legacy_text, legacy_error = read_text(legacy_path)
            if legacy_error is not None or legacy_text is None:
                blockers.append(
                    legacy_error or f"{legacy_path}: failed to read legacy shim"
                )
                continue

            legacy_resolved = _resolved(legacy_path)
            if legacy_resolved in migrated_resolved:
                delete = _planned_delete(
                    legacy_path,
                    detail="migrated provider instruction source",
                    expected_content=legacy_text,
                    allow_custom=True,
                )
                if delete is not None:
                    deletes.append(delete)
                continue

            managed = is_managed_agents_document(legacy_text)
            legacy_generated = _is_legacy_generated_chezmoi_copy(
                legacy_text,
                expected_content=spec.content,
            )
            if _is_provider_shim_text(legacy_text) or managed or legacy_generated:
                delete = _planned_delete(
                    legacy_path,
                    detail="legacy provider instruction shim",
                    expected_content=(
                        legacy_text if managed or legacy_generated else None
                    ),
                    allow_custom=managed or legacy_generated,
                )
                if delete is not None:
                    deletes.append(delete)
            else:
                blockers.append(
                    f"{legacy_path}: custom legacy provider instruction file "
                    f"must be migrated or removed before managing {spec.path.name}"
                )

    if blockers:
        return ProviderShimPlan(
            writes=(),
            deletes=(),
            blockers=tuple(blockers),
            source_path=source_path,
        )
    return ProviderShimPlan(
        writes=tuple(writes),
        deletes=tuple(deletes),
        source_path=source_path,
    )


def legacy_agents_template_plan(
    root: Path,
    *,
    agents_content: str,
    chezmoi_home_roots: Iterable[Path] = (),
) -> ProviderShimPlan:
    """Return a guarded delete plan for old generated chezmoi ``AGENTS.md.tmpl``."""
    if not is_chezmoi_home_root(root, chezmoi_home_roots=chezmoi_home_roots):
        return ProviderShimPlan(writes=(), deletes=(), source_path=root / "AGENTS.md")

    legacy_path = root / "AGENTS.md.tmpl"
    if not legacy_path.exists():
        return ProviderShimPlan(writes=(), deletes=(), source_path=root / "AGENTS.md")

    legacy_text, legacy_error = read_text(legacy_path)
    if legacy_error is not None or legacy_text is None:
        return ProviderShimPlan(
            writes=(),
            deletes=(),
            blockers=(legacy_error or f"{legacy_path}: failed to read legacy source",),
            source_path=root / "AGENTS.md",
        )

    if legacy_text == agents_content or _is_legacy_generated_chezmoi_copy(
        legacy_text,
        expected_content=agents_content,
    ):
        delete = _planned_delete(
            legacy_path,
            detail="legacy managed AGENTS.md source",
            expected_content=legacy_text,
            allow_custom=True,
        )
        return ProviderShimPlan(
            writes=(),
            deletes=() if delete is None else (delete,),
            source_path=root / "AGENTS.md",
        )

    return ProviderShimPlan(
        writes=(),
        deletes=(),
        blockers=(
            f"{legacy_path}: custom legacy AGENTS.md template must be migrated "
            "or removed before managing AGENTS.md",
        ),
        source_path=root / "AGENTS.md",
    )
