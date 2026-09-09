"""Activation helpers for machine initialization."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sase.dispatch._machine_init_types import ApplyChezmoiFn


@dataclass(frozen=True)
class ActivationOutcome:
    ok: bool
    errors: tuple[str, ...] = ()
    recovery_message: str = ""
    proc_id: str = ""
    in_progress: bool = False


@dataclass(frozen=True)
class ChezmoiApplyOutcome:
    """Non-raising result of a scoped, tracked chezmoi apply."""

    returncode: int = 0
    stdout: str = ""
    stderr: str = ""
    proc_id: str = ""
    submitted: bool = False
    observed: bool = True
    in_progress: bool = False
    error: str = ""

    @property
    def failed(self) -> bool:
        return bool(
            self.error
            or self.returncode != 0
            or self.in_progress
            or (self.submitted and not self.observed)
        )


def run_scoped_chezmoi_apply(
    target: Path | str,
    *,
    apply_fn: ApplyChezmoiFn | None = None,
) -> ChezmoiApplyOutcome:
    """Run the scoped ``apply_chezmoi`` operation from a durable tracked proc.

    The argv matches :func:`sase.config.targets.apply_chezmoi` so the supervisor
    performs the same scoped, forced apply. Callers inject ``apply_fn`` in tests.
    A non-zero exit is returned, not raised. Submit or wait failures never start
    a second untracked apply.
    """
    if apply_fn is not None:
        result = apply_fn(target)
        detail = (result.stderr or result.stdout or "").strip()
        error = ""
        if result.returncode != 0:
            error = f"chezmoi apply failed: {detail or f'exit {result.returncode}'}"
        return ChezmoiApplyOutcome(
            returncode=result.returncode,
            stdout=result.stdout or "",
            stderr=result.stderr or "",
            submitted=True,
            observed=True,
            error=error,
        )
    from sase.procs import submit_proc, wait_for_proc

    expanded = str(Path(target).expanduser())
    argv = ["chezmoi", "apply", "--force", expanded]
    try:
        proc = submit_proc(
            argv,
            label=f"chezmoi apply {expanded}",
            cwd=Path.home(),
            origin="machine-init",
            tags=("machine-init", "chezmoi-apply"),
            timeout_seconds=900,
        )
    except Exception as exc:  # noqa: BLE001 - report submit failure without applying.
        return ChezmoiApplyOutcome(
            returncode=1,
            submitted=False,
            observed=False,
            error=f"could not submit chezmoi apply: {exc}",
        )
    try:
        finished = wait_for_proc(proc.proc_id, timeout=900)
    except Exception as exc:  # noqa: BLE001 - retain the submitted proc identity.
        return ChezmoiApplyOutcome(
            returncode=1,
            proc_id=proc.proc_id,
            submitted=True,
            observed=False,
            in_progress=True,
            error=(
                f"chezmoi apply was submitted as proc {proc.proc_id} but its "
                f"outcome could not be observed: {exc}"
            ),
        )
    returncode = 0 if finished.status == "success" else (finished.exit_code or 1)
    log_text = ""
    if finished.log_path:
        try:
            log_text = Path(finished.log_path).read_text(encoding="utf-8")
        except OSError:
            log_text = ""
    detail = (finished.message or log_text).strip()
    error = ""
    if returncode != 0:
        error = f"chezmoi apply failed: {detail or f'exit {returncode}'}"
    return ChezmoiApplyOutcome(
        returncode=returncode,
        stdout=log_text,
        stderr=finished.message or "",
        proc_id=proc.proc_id,
        submitted=True,
        observed=True,
        error=error,
    )
