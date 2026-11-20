"""Deep-only ``instructions.bundle_size`` doctor check.

Compiles every enabled project's root instruction bundle for each provider
whose explicit root slot declares ``max_bytes``, the way a launch (and
``sase instructions render``) does, and reports whether the delivered text
fits: ERROR when it still exceeds the cap after compaction (that launch falls
back to native delivery), WARN when it fits only after compaction, OK
otherwise.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.diagnostics import CheckStatus, DiagnosticCheck

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext

CHECK_ID = "instructions.bundle_size"
CHECK_TITLE = "Provider root bundles fit their byte caps"

_GROUP = "instructions"
_ERROR_DETAIL_LIMIT = 300


@dataclass(frozen=True)
class _BundleSizeProject:
    """One enabled project the check compiles, with its checkout root.

    ``name`` is the human label (``PROJECT_NAME``); ``key`` is the project
    directory key, reported only as a machine-readable identity field.
    """

    name: str
    root: Path | None
    key: str | None = None


@dataclass(frozen=True)
class _BundleSizeRow:
    project: str
    project_key: str | None
    provider: str
    max_bytes: int
    delivered_bytes: int | None = None
    compaction_step: str | None = None
    uncompacted_bytes: int | None = None
    error: str | None = None

    @property
    def state(self) -> str:
        if self.error is not None:
            return "error"
        if self.delivered_bytes is not None and self.delivered_bytes > self.max_bytes:
            return "oversize"
        if self.compaction_step is not None:
            return "compacted"
        return "ok"

    @property
    def label(self) -> str:
        return f"{self.project}/{self.provider}"

    def describe(self) -> str:
        if self.error is not None:
            return f"{self.label}: render failed: {self.error}"
        size = f"{self.delivered_bytes or 0:,}/{self.max_bytes:,} bytes"
        if self.compaction_step is None:
            return f"{self.label}: {size}"
        uncompacted = (
            f", uncompacted {self.uncompacted_bytes:,} bytes"
            if self.uncompacted_bytes is not None
            else ""
        )
        return f"{self.label}: {size} after {self.compaction_step}{uncompacted}"

    def to_data(self) -> dict[str, Any]:
        return {
            "project": self.project,
            "project_key": self.project_key,
            "provider": self.provider,
            "state": self.state,
            "max_bytes": self.max_bytes,
            "delivered_bytes": self.delivered_bytes,
            "compaction_step": self.compaction_step,
            "uncompacted_bytes": self.uncompacted_bytes,
            "error": self.error,
        }


def check_instructions_bundle_size(
    context: DoctorContext,
    *,
    projects: Sequence[_BundleSizeProject] | None = None,
    provider_caps: Mapping[str, int] | None = None,
    home_root: Path | None = None,
) -> DiagnosticCheck:
    """Report whether each enabled project's capped root bundles fit."""
    caps = dict(_provider_caps() if provider_caps is None else provider_caps)
    if not caps:
        return _check(
            "SKIP",
            "no provider declares a root byte cap with explicit delivery enabled",
        )
    targets = tuple(_enabled_projects(context) if projects is None else projects)
    checkout_missing = [project.name for project in targets if not _has_root(project)]
    compilable = [project for project in targets if _has_root(project)]
    if not compilable:
        summary = "no enabled project checkouts to compile"
        if checkout_missing:
            summary += f" (missing: {', '.join(checkout_missing)})"
        return _check("SKIP", summary)

    home = Path.home() if home_root is None else home_root
    rows = [
        _measure(project, provider, cap, home_root=home)
        for project in compilable
        for provider, cap in sorted(caps.items())
    ]
    oversize = [row for row in rows if row.state == "oversize"]
    compacted = [row for row in rows if row.state == "compacted"]
    failed = [row for row in rows if row.state == "error"]

    status: CheckStatus
    if oversize:
        status = "ERROR"
        summary = (
            f"{len(oversize)} root bundle(s) exceed their cap after compaction "
            "and fall back to native delivery: "
            + "; ".join(row.describe() for row in oversize)
        )
    elif compacted or failed:
        status = "WARN"
        parts: list[str] = []
        if compacted:
            parts.append(
                f"{len(compacted)} root bundle(s) fit only after compaction: "
                + "; ".join(row.describe() for row in compacted)
            )
        if failed:
            parts.append(
                f"{len(failed)} root bundle(s) failed to render: "
                + ", ".join(row.label for row in failed)
            )
        summary = "; ".join(parts)
    else:
        status = "OK"
        largest = max(rows, key=lambda row: (row.delivered_bytes or 0) / row.max_bytes)
        summary = (
            f"{len(rows)} root bundle(s) across {len(compilable)} project(s) fit "
            f"without compaction; closest to its cap: {largest.describe()}"
        )
    details = [row.describe() for row in _problem_first(rows)]
    if checkout_missing:
        details.append(f"skipped (checkout missing): {', '.join(checkout_missing)}")
    return _check(
        status,
        summary,
        details=tuple(details),
        next_steps=_next_steps(oversize, compacted, failed),
        data={
            "provider_caps": dict(sorted(caps.items())),
            "projects_checked": len(compilable),
            "projects_missing_checkout": checkout_missing,
            "rows": [row.to_data() for row in rows],
        },
    )


def _check(
    status: CheckStatus,
    summary: str,
    *,
    details: tuple[str, ...] = (),
    next_steps: tuple[str, ...] = (),
    data: dict[str, Any] | None = None,
) -> DiagnosticCheck:
    return DiagnosticCheck(
        id=CHECK_ID,
        group=_GROUP,
        status=status,
        title=CHECK_TITLE,
        summary=summary,
        details=details,
        next_steps=next_steps,
        data=data or {},
    )


def _provider_caps() -> dict[str, int]:
    from sase.llm_provider.instruction_delivery import capped_root_providers

    return capped_root_providers()


def _enabled_projects(context: DoctorContext) -> tuple[_BundleSizeProject, ...]:
    try:
        from sase.core.project_lifecycle_facade import list_project_records

        records = list_project_records(
            context.sase_home / "projects",
            "enabled",
            include_home=False,
            projects_only=True,
        )
    except Exception:  # noqa: BLE001 - doctor isolates project listing
        return ()
    return tuple(
        _BundleSizeProject(
            name=record.display_name or record.project_name,
            root=Path(record.workspace_dir) if record.workspace_dir else None,
            key=record.project_name,
        )
        for record in records
        if record.is_project
    )


def _has_root(project: _BundleSizeProject) -> bool:
    return project.root is not None and project.root.is_dir()


def _measure(
    project: _BundleSizeProject,
    provider: str,
    cap: int,
    *,
    home_root: Path,
) -> _BundleSizeRow:
    from sase.instructions.compaction import delivered_bytes
    from sase.instructions.compile import compile_bundle
    from sase.instructions.facts import default_facts

    assert project.root is not None
    try:
        compiled = compile_bundle(
            default_facts(project.root, provider=provider),
            project_root=project.root,
            home_root=home_root,
            max_bytes=cap,
        )
    except Exception as exc:  # noqa: BLE001 - one project never fails the check
        message = " ".join(str(exc).split()) or type(exc).__name__
        return _BundleSizeRow(
            project=project.name,
            project_key=project.key,
            provider=provider,
            max_bytes=cap,
            error=message[:_ERROR_DETAIL_LIMIT],
        )
    compaction = compiled.compaction or {}
    uncompacted = compaction.get("uncompacted_bytes")
    step = compaction.get("step")
    return _BundleSizeRow(
        project=project.name,
        project_key=project.key,
        provider=provider,
        max_bytes=cap,
        delivered_bytes=delivered_bytes(compiled.text),
        compaction_step=str(step) if step else None,
        uncompacted_bytes=int(uncompacted) if uncompacted is not None else None,
    )


def _problem_first(rows: Sequence[_BundleSizeRow]) -> list[_BundleSizeRow]:
    order = {"oversize": 0, "error": 1, "compacted": 2, "ok": 3}
    return sorted(rows, key=lambda row: (order[row.state], row.project, row.provider))


def _next_steps(
    oversize: Sequence[_BundleSizeRow],
    compacted: Sequence[_BundleSizeRow],
    failed: Sequence[_BundleSizeRow],
) -> tuple[str, ...]:
    steps: list[str] = []
    for row in (*oversize, *compacted):
        steps.append(
            f"In the {row.project} checkout, run `sase instructions render -f "
            f"provider={row.provider} -s` and shrink the largest always-inlined "
            "sections (core notes, memory web rosters)"
        )
    for row in failed:
        steps.append(
            f"In the {row.project} checkout, run `sase instructions render -f "
            f"provider={row.provider}` to see the render error"
        )
    return tuple(dict.fromkeys(steps))


__all__ = [
    "CHECK_ID",
    "CHECK_TITLE",
    "check_instructions_bundle_size",
]
