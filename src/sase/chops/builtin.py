"""Registry and shared runtime for builtin axe chop scripts."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sase.axe.chop_script_context import (
    ChopScriptContext,
    load_patches_from_file,
)
from sase.axe.state import AxeMetrics

from .sdk import (
    ChopLogger,
    ChopResultBuilder,
    ChopSummary,
    SummaryValue,
    emit_summary,
    load_chop_invocation,
    parse_summary,
    resolve_chop_result_file,
    write_chop_result,
)

if TYPE_CHECKING:
    from sase.ace.patch import Patch
    from sase.axe.check_cycles import CheckCycleRunner
    from sase.axe.hook_jobs import HookJobRunner


@dataclass
class BuiltinChopRuntime:
    """Shared context, logging, and runner factories for a builtin chop."""

    name: str
    context: ChopScriptContext
    log: ChopLogger
    _all_patches: list[Patch] | None = field(default=None, init=False)
    _filtered_patches: list[Patch] | None = field(default=None, init=False)
    _hook_runner: HookJobRunner | None = field(default=None, init=False)
    _check_cycle_runner: CheckCycleRunner | None = field(default=None, init=False)

    @property
    def all_patches(self) -> list[Patch]:
        if self._all_patches is None:
            self._all_patches = load_patches_from_file(self.context.all_patches_file)
        return self._all_patches

    @property
    def filtered_patches(self) -> list[Patch]:
        if self._filtered_patches is None:
            self._filtered_patches = load_patches_from_file(
                self.context.filtered_patches_file
            )
        return self._filtered_patches

    @property
    def hook_runner(self) -> HookJobRunner:
        if self._hook_runner is None:
            from sase.axe.hook_jobs import HookJobRunner

            self._hook_runner = HookJobRunner(
                AxeMetrics(),
                self.context.zombie_timeout_seconds,
                self.context.max_hook_runners,
                self.context.max_agent_runners,
                self.log,
                verbose_diagnostics=(
                    self.log.verbose or self.context.verbose_lumberjack_diagnostics
                ),
            )
        return self._hook_runner

    @property
    def check_cycle_runner(self) -> CheckCycleRunner:
        if self._check_cycle_runner is None:
            from sase.axe.check_cycles import CheckCycleRunner

            self._check_cycle_runner = CheckCycleRunner(
                self.context.query or None,
                self.log,
            )
        return self._check_cycle_runner

    def emit_summary(
        self,
        fields: Mapping[str, SummaryValue],
        *,
        reason: str | None = None,
    ) -> ChopResultBuilder:
        """Emit the builtin's summary and build its structured result."""

        line = emit_summary(self.name, fields, reason=reason, logger=self.log)
        summary = parse_summary(line)
        if summary is None:
            raise RuntimeError(f"invalid builtin chop summary: {line}")
        return ChopResultBuilder.from_summary(summary)


type BuiltinResult = ChopResultBuilder | Mapping[str, Any] | None
type BuiltinHandler = Callable[[BuiltinChopRuntime], BuiltinResult]

_BUILTIN_CHOPS: dict[str, BuiltinHandler] = {}


def builtin_chop(name: str) -> Callable[[BuiltinHandler], BuiltinHandler]:
    """Register a builtin chop handler under its configured identity."""

    def _register(handler: BuiltinHandler) -> BuiltinHandler:
        existing = _BUILTIN_CHOPS.get(name)
        if existing is not None and existing is not handler:
            raise RuntimeError(f"builtin chop already registered: {name}")
        _BUILTIN_CHOPS[name] = handler
        return handler

    return _register


def _result_from_summary(name: str, summary: ChopSummary | None) -> ChopResultBuilder:
    if summary is None or summary.name != name:
        raise RuntimeError(f"builtin chop '{name}' did not emit its summary")
    return ChopResultBuilder.from_summary(summary)


def run_builtin_chop(name: str, argv: Sequence[str] | None = None) -> None:
    """Run a registered builtin with common args, context, and result writing."""

    try:
        handler = _BUILTIN_CHOPS[name]
    except KeyError as error:
        raise RuntimeError(f"unknown builtin chop: {name}") from error

    invocation = load_chop_invocation(argv, description=f"Run the {name} axe chop")
    runtime = BuiltinChopRuntime(
        name=name,
        context=invocation.context,
        log=invocation.logger,
    )
    runtime.log.debug(f"chop={name} context={invocation.arguments.context}")
    result = handler(runtime)
    if result is None:
        result = _result_from_summary(name, runtime.log.last_summary)

    result_path = resolve_chop_result_file(runtime.context, required=False)
    if result_path is None:
        runtime.log.debug("No result path configured; structured result not written")
        return
    write_chop_result(result, result_path)


__all__ = [
    "BuiltinChopRuntime",
    "builtin_chop",
    "run_builtin_chop",
]
