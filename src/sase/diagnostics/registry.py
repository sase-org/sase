"""Registry and safe execution helpers for diagnostic checks."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from sase.diagnostics.models import DiagnosticCheck, redact_string

type CheckRunResult = DiagnosticCheck | Iterable[DiagnosticCheck]
type CheckRunner = Callable[[], CheckRunResult]


@dataclass(frozen=True)
class CheckSpec:
    """Registered diagnostic check metadata and runner."""

    id: str
    group: str
    title: str
    runner: CheckRunner
    deep: bool = False

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("CheckSpec.id must be non-empty")
        if not self.group:
            raise ValueError("CheckSpec.group must be non-empty")
        if not self.title:
            raise ValueError("CheckSpec.title must be non-empty")


class UnknownCheckSelection(ValueError):
    """Raised when a requested check ID or group is not registered."""

    def __init__(self, selections: Sequence[str]) -> None:
        self.selections = tuple(selections)
        joined = ", ".join(self.selections)
        super().__init__(f"unknown diagnostic check or group: {joined}")


class DiagnosticRegistry:
    """Stable-order collection of diagnostic check specs."""

    def __init__(self, specs: Sequence[CheckSpec] = ()) -> None:
        self._specs = tuple(specs)
        ids: set[str] = set()
        for spec in self._specs:
            if spec.id in ids:
                raise ValueError(f"duplicate diagnostic check id: {spec.id}")
            ids.add(spec.id)

    def list_default_checks(self) -> tuple[CheckSpec, ...]:
        """Return non-deep checks in registration order."""
        return tuple(spec for spec in self._specs if not spec.deep)

    def list_deep_checks(self) -> tuple[CheckSpec, ...]:
        """Return deep checks in registration order."""
        return tuple(spec for spec in self._specs if spec.deep)

    def list_checks(self, *, include_deep: bool = False) -> tuple[CheckSpec, ...]:
        """Return visible checks in registration order."""
        if include_deep:
            return self._specs
        return self.list_default_checks()

    def select(
        self,
        selections: Sequence[str] = (),
        *,
        include_deep: bool = False,
    ) -> tuple[CheckSpec, ...]:
        """Select checks by ID or group while preserving registry order."""
        visible = self.list_checks(include_deep=include_deep)
        if not selections:
            return visible

        wanted = tuple(dict.fromkeys(selections))
        visible_ids = {spec.id for spec in visible}
        visible_groups = {spec.group for spec in visible}
        unknown = [
            item
            for item in wanted
            if item not in visible_ids and item not in visible_groups
        ]
        if unknown:
            raise UnknownCheckSelection(unknown)

        selected: list[CheckSpec] = []
        for spec in visible:
            if spec.id in wanted or spec.group in wanted:
                selected.append(spec)
        return tuple(selected)

    def run(
        self,
        selections: Sequence[str] = (),
        *,
        include_deep: bool = False,
    ) -> tuple[DiagnosticCheck, ...]:
        """Run selected specs and keep going after individual failures."""
        checks: list[DiagnosticCheck] = []
        for spec in self.select(selections, include_deep=include_deep):
            checks.extend(run_check_spec_safely(spec))
        return tuple(checks)


def run_check_spec_safely(spec: CheckSpec) -> tuple[DiagnosticCheck, ...]:
    """Run one spec, converting unexpected exceptions into one ERROR check."""
    started = time.perf_counter()
    try:
        raw = spec.runner()
        elapsed_ms = _elapsed_ms(started)
        return tuple(
            _with_duration(check, elapsed_ms) for check in _normalize_result(raw)
        )
    except Exception as exc:  # noqa: BLE001 - doctor must continue after check bugs.
        elapsed_ms = _elapsed_ms(started)
        return (
            DiagnosticCheck(
                id=spec.id,
                group=spec.group,
                status="ERROR",
                title=spec.title,
                summary=f"{spec.title} failed unexpectedly.",
                details=(redact_string(f"{type(exc).__name__}: {exc}"),),
                next_steps=(
                    "Run this check again with `sase doctor -v` and inspect logs if the failure persists.",
                ),
                duration_ms=elapsed_ms,
            ),
        )


def _normalize_result(raw: CheckRunResult) -> tuple[DiagnosticCheck, ...]:
    if isinstance(raw, DiagnosticCheck):
        return (raw,)

    checks = tuple(raw)
    for check in checks:
        if not isinstance(check, DiagnosticCheck):
            raise TypeError(
                "diagnostic check runner must return DiagnosticCheck objects"
            )
    return checks


def _with_duration(check: DiagnosticCheck, duration_ms: int) -> DiagnosticCheck:
    if check.duration_ms:
        return check
    return check.with_duration(duration_ms)


def _elapsed_ms(started: float) -> int:
    return max(int((time.perf_counter() - started) * 1000), 0)
