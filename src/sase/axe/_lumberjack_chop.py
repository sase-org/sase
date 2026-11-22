"""Chop-execution half of the lumberjack tick."""

import time

from sase.telemetry.metrics import AXE_ERRORS

from .chop_runner import (
    TRACEBACK_UNAVAILABLE,
    ChopRunOutcome,
    run_configured_chop_once,
)
from .config import ChopConfig
from .state import append_error, get_timestamp, read_chop_run_log_tail
from ._lumberjack_shared import LumberjackBase, LumberjackChopResult


class LumberjackChopMixin(LumberjackBase):
    """Runs one chop and translates its outcome for the tick aggregate."""

    def _run_single_chop(
        self, chop: ChopConfig, context_file: str
    ) -> LumberjackChopResult:
        """Execute a single chop via the shared chop-runner service.

        The runner owns context, env, timeout, and run-history persistence;
        this method translates the typed :class:`ChopRunOutcome` it returns
        into the tick-level :class:`LumberjackChopResult` (log lines for the
        aggregate log, run_every timestamp updates, agent PID tracking).
        """
        if self._stop_signal.stop_requested() or not self._running:
            return LumberjackChopResult(
                chop_name=chop.name,
                executed=False,
                success=True,
                update_timestamp=False,
                log_lines=[],
                skip_reason="shutdown",
            )
        started = time.monotonic()
        outcome = run_configured_chop_once(
            lumberjack_name=self.name,
            chop=chop,
            axe_config=self.axe_config,
            chop_timeout_default=self.config.chop_timeout,
            wait_runners_default=self.config.wait_runners,
            context_file=context_file,
            source="scheduled",
            pause_requested_fn=self._stop_signal.as_pause_fn(),
        )
        result = self._outcome_to_result(chop, outcome)
        result.duration_seconds = time.monotonic() - started
        return result

    def _outcome_to_result(
        self, chop: ChopConfig, outcome: ChopRunOutcome
    ) -> LumberjackChopResult:
        log_lines: list[str] = []

        if outcome.status in {"success", "no_op", "launched", "action_succeeded"}:
            self._append_log_tail(chop.name, outcome.run_id, log_lines)
            return LumberjackChopResult(
                chop_name=chop.name,
                executed=True,
                success=True,
                update_timestamp=chop.run_every is not None,
                log_lines=log_lines,
                no_op=outcome.status == "no_op",
            )

        if outcome.status == "skipped":
            # A coalesced repeat skip already logged its line on the first skip.
            if not outcome.skip_coalesced:
                self._append_log_tail(chop.name, outcome.run_id, log_lines)
            return LumberjackChopResult(
                chop_name=chop.name,
                executed=False,
                success=True,
                update_timestamp=(
                    chop.run_every is not None and outcome.advances_cadence
                ),
                log_lines=log_lines,
                skip_reason=outcome.skip_reason or "inhibited",
            )

        if outcome.status in {"failure", "check_error", "action_failed"}:
            # Process completed with nonzero exit; echo its tail into the
            # aggregate log to match the legacy ``capture_output=True`` shape.
            self._append_log_tail(chop.name, outcome.run_id, log_lines)
            return LumberjackChopResult(
                chop_name=chop.name,
                executed=True,
                success=False,
                update_timestamp=chop.run_every is not None,
                log_lines=log_lines,
                error=outcome.error,
                traceback=outcome.traceback,
                subprocess_diagnostic=outcome.subprocess_diagnostic,
            )

        if outcome.status == "timeout":
            return LumberjackChopResult(
                chop_name=chop.name,
                executed=True,
                success=False,
                update_timestamp=chop.run_every is not None,
                log_lines=log_lines,
                error=outcome.error,
                traceback=outcome.traceback,
                subprocess_diagnostic=outcome.subprocess_diagnostic,
            )

        if outcome.status == "missing_script":
            return LumberjackChopResult(
                chop_name=chop.name,
                executed=False,
                success=False,
                update_timestamp=False,
                log_lines=log_lines,
                error=outcome.error,
                traceback=outcome.traceback,
            )

        if outcome.status == "already_running":
            # Scheduled tick should not double-launch; treat as a quiet skip
            # so we don't increment chops_executed or error counters.
            return LumberjackChopResult(
                chop_name=chop.name,
                executed=False,
                success=False,
                update_timestamp=False,
                log_lines=log_lines,
            )

        # Unknown status: surface as an error so silent drift is loud.
        return LumberjackChopResult(
            chop_name=chop.name,
            executed=False,
            success=False,
            update_timestamp=False,
            log_lines=log_lines,
            error=RuntimeError(f"unexpected job run outcome: {outcome.status}"),
            traceback=TRACEBACK_UNAVAILABLE,
        )

    def _append_log_tail(
        self,
        chop_name: str,
        run_id: str | None,
        log_lines: list[str],
    ) -> None:
        if run_id is None:
            return
        try:
            tail = read_chop_run_log_tail(self.name, chop_name, run_id, lines=200)
        except OSError:
            tail = ""
        if tail:
            for line in tail.splitlines():
                if line:
                    log_lines.append(line)

    def _handle_error(
        self,
        job_name: str,
        error: Exception,
        tb: str | None = None,
        subprocess_diagnostic: dict[str, object] | None = None,
    ) -> None:
        self._log(f"Error in {job_name}: {error}", style="red")
        self._metrics.errors_encountered += 1
        AXE_ERRORS.labels(error_type="chop").inc()
        # Never call ``traceback.format_exc()`` here as a fallback: by the
        # time ``_handle_error`` runs we're outside the active ``except``
        # block, so it would yield the literal string ``"NoneType: None"``.
        # Every error-bearing ``LumberjackChopResult`` is responsible for
        # capturing its own traceback inside the ``except`` block (or setting
        # an explicit placeholder for non-exception failures).
        error_info: dict[str, object] = {
            "timestamp": get_timestamp(),
            "lumberjack": self.name,
            "job": job_name,
            "error": str(error),
            "traceback": tb if tb is not None else TRACEBACK_UNAVAILABLE,
        }
        if subprocess_diagnostic is not None:
            error_info["subprocess_diagnostic"] = subprocess_diagnostic
        append_error(error_info)
