"""Read-only resolution and loading for locally available plan documents."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sase.core.commit_footer_facade import LinkedCommitTagValue, parse_commit_footer


PlanDocumentStatus = Literal[
    "success",
    "missing_tag",
    "invalid_reference",
    "missing_file",
    "not_file",
    "unreadable",
]


@dataclass(frozen=True)
class PlanWorkspace:
    """One project workspace that may own a commit's plan document."""

    workspace_dir: str
    workspace_num: int = 1
    plans_root: str | None = None
    project: str | None = None


@dataclass(frozen=True)
class _PlanPathResolution:
    """Typed outcome from resolving one stable plan reference."""

    status: Literal["success", "invalid_reference", "missing_file", "not_file"]
    reference: str
    path: str | None


@dataclass(frozen=True)
class PlanDocument:
    """Typed local plan payload or a precise load failure."""

    status: PlanDocumentStatus
    reference: str = ""
    destination: str | None = None
    path: str | None = None
    content: str | None = None
    detail: str | None = None

    @property
    def available(self) -> bool:
        return self.status == "success"


def resolve_plan_path(
    reference: str,
    *,
    repo_dir: str | None = None,
    workspaces: Sequence[PlanWorkspace] = (),
) -> _PlanPathResolution:
    """Resolve a stable plan reference without materializing any stores."""
    reference = reference.strip()
    if not reference:
        return _PlanPathResolution("invalid_reference", reference, None)

    try:
        raw_path = Path(reference).expanduser()
        candidates: list[Path] = []
        if raw_path.is_absolute():
            candidates.append(raw_path)
        else:
            if repo_dir:
                candidates.append(Path(repo_dir).expanduser() / raw_path)
            relative = _plan_root_relative_path(raw_path)
            for workspace in workspaces:
                if workspace.workspace_dir:
                    candidates.append(
                        Path(workspace.workspace_dir).expanduser() / raw_path
                    )
                plans_root = _effective_plans_root(workspace.plans_root)
                if plans_root is not None:
                    candidates.append(plans_root / relative)
            if not candidates:
                return _PlanPathResolution("invalid_reference", reference, None)
        normalized = tuple(
            dict.fromkeys(candidate.resolve(strict=False) for candidate in candidates)
        )
    except (OSError, RuntimeError, ValueError):
        return _PlanPathResolution("invalid_reference", reference, None)

    first_non_file: Path | None = None
    for candidate in normalized:
        try:
            if candidate.is_file():
                return _PlanPathResolution("success", reference, str(candidate))
            if first_non_file is None and candidate.exists():
                first_non_file = candidate
        except (OSError, ValueError):
            continue
    if first_non_file is not None:
        return _PlanPathResolution("not_file", reference, str(first_non_file))
    missing = normalized[-1] if normalized else None
    return _PlanPathResolution(
        "missing_file",
        reference,
        None if missing is None else str(missing),
    )


def _read_plan_document(
    reference: str,
    *,
    repo_dir: str | None = None,
    workspaces: Sequence[PlanWorkspace] = (),
    destination: str | None = None,
    read_text: Callable[[Path], str] | None = None,
) -> PlanDocument:
    """Resolve and read one local UTF-8 Markdown plan without raising."""
    resolved = resolve_plan_path(
        reference,
        repo_dir=repo_dir,
        workspaces=workspaces,
    )
    if resolved.status != "success":
        return PlanDocument(
            resolved.status,
            reference=reference,
            destination=destination,
            path=resolved.path,
        )

    assert resolved.path is not None
    path = Path(resolved.path)
    reader = read_text or _read_utf8
    try:
        content = reader(path)
    except UnicodeError as exc:
        return PlanDocument(
            "unreadable",
            reference=reference,
            destination=destination,
            path=resolved.path,
            detail=f"not valid UTF-8: {exc}",
        )
    except (OSError, RuntimeError, ValueError) as exc:
        return PlanDocument(
            "unreadable",
            reference=reference,
            destination=destination,
            path=resolved.path,
            detail=str(exc).strip() or type(exc).__name__,
        )
    return PlanDocument(
        "success",
        reference=reference,
        destination=destination,
        path=resolved.path,
        content=content,
    )


def load_commit_plan_document(
    message: str,
    *,
    repo_dir: str | None,
    workspaces: Sequence[PlanWorkspace],
    read_text: Callable[[Path], str] | None = None,
) -> PlanDocument:
    """Load the terminal structured ``SASE_PLAN`` attached to a commit."""
    try:
        footer = parse_commit_footer(message)
    except Exception as exc:
        return PlanDocument(
            "invalid_reference",
            detail=f"commit footer could not be parsed: {exc}",
        )

    tag = next(
        (tag for tag in reversed(footer.tags) if tag.raw_key == "SASE_PLAN"),
        None,
    )
    if tag is None:
        return PlanDocument("missing_tag")

    destination = (
        tag.value.destination if isinstance(tag.value, LinkedCommitTagValue) else None
    )
    resolved_workspaces = tuple(_with_resolved_plans_root(item) for item in workspaces)
    return _read_plan_document(
        tag.label,
        repo_dir=repo_dir,
        workspaces=resolved_workspaces,
        destination=destination,
        read_text=read_text,
    )


def _with_resolved_plans_root(workspace: PlanWorkspace) -> PlanWorkspace:
    if workspace.plans_root is not None or not workspace.workspace_dir:
        return workspace
    try:
        from sase.sdd.store import resolve_sdd_kind_dir

        root = resolve_sdd_kind_dir(
            workspace.workspace_dir,
            workspace.workspace_num,
            "plans",
        )
    except Exception:
        return workspace
    return PlanWorkspace(
        workspace_dir=workspace.workspace_dir,
        workspace_num=workspace.workspace_num,
        plans_root=str(root),
        project=workspace.project,
    )


def _plan_root_relative_path(reference: Path) -> Path:
    parts = reference.parts
    for prefix in (
        (".sase", "sdd", "plans"),
        ("sdd", "plans"),
        ("plans",),
    ):
        if parts[: len(prefix)] == prefix:
            return Path(*parts[len(prefix) :])
    return reference


def _effective_plans_root(value: str | None) -> Path | None:
    if not value:
        return None
    root = Path(value).expanduser().resolve(strict=False)
    nested = root / "plans"
    return nested if nested.is_dir() or root.name == "sdd" else root


def _read_utf8(path: Path) -> str:
    return path.read_text(encoding="utf-8")


__all__ = [
    "PlanDocument",
    "PlanDocumentStatus",
    "PlanWorkspace",
    "load_commit_plan_document",
    "resolve_plan_path",
]
