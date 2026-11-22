"""Refresh a long-lived runner after its dependency wait crosses code updates.

Every one-shot launch handoff consumed by the pre-wait pass must survive the
refresh re-exec in one of two ways.

- **Durable identity:** the refreshed pass recovers it from
  ``preserved_agent_metadata()`` (clan membership, batch predecessor context,
  epic work, model selection).
- **One-shot file or env resource:** this module re-materializes it before
  exec (the prompt file, local macros, the planned name).

The exec replays ``sys.argv`` verbatim. Any future argv field that names a
one-shot resource must therefore be re-materialized here before exec, just as
the temporary prompt file is today.

Already-audited inputs that need no behavior change:

- ``SASE_LAUNCH_HOLD_KEY``: ``arm_bootstrap_hold()`` returns early on a
  refreshed pass.
- Epic-work env (``epic_work_metadata_from_env()``): its fields are preserved
  metadata keys.
- ``SASE_EPIC_CLAN_SUMMARY_SCRIPT``: the resolved ``clan_summary`` is
  preserved metadata.
- ``SASE_AGENT_PREDECESSOR_CONTEXT``: already uses the preserved-metadata
  fallback.
- ``SASE_AGENT_PLANNED_NAME``: restored by
  ``refresh_runner_code_after_wait()``.
- ``SASE_AUTO_RESTART_PROVENANCE``: inherited through the environment across
  the re-exec (never popped in bootstrap) and preserved as the
  ``auto_restart`` metadata key.
- ``SASE_AGENT_GENERATED_NAME``: lost, but harmless. The refreshed claim
  targets a name already owned by the same artifacts dir, and
  ``claim_registered_name()`` accepts same-owner claims regardless of
  ``explicit``.

Anyone adding a new ``consume_*_from_env()`` / ``os.environ.pop(...)`` in the
bootstrap path must extend one of the two handoff lists above.

The temporary prompt file crosses the re-exec verbatim: the live ``%auto``
reconcile is not applied here (no ``sase.*`` import may run between the
identity check and ``os.execv``) but in the refreshed pass's bootstrap, via
``reconcile_prompt_with_live_auto_state`` in ``_load_submitted_prompt``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import os
import signal
import sys
from pathlib import Path
from typing import Any

from sase.agent.multi_prompt_macros import (
    read_local_macros_path,
    restore_local_macros_path,
    serialize_local_macros,
    set_local_macros_path,
)
from sase.axe.run_agent_directive_identity import (
    planned_name_is_reserved_for_artifacts,
)
from sase.env_contracts import SASE_RUNNER_CODE_REFRESHED_ENV
from sase.version._git import probe_git_metadata_at_ref
from sase.version._models import HOST_DISTRIBUTION_NAME
from sase.version._sources import (
    direct_url_info,
    distribution_location,
    find_distribution,
    install_type,
    resolve_import,
    source_root,
)

# Warm modules that refresh-path helpers still import lazily. Between the
# code-identity check and ``os.execv`` no new ``sase.*`` import may run (a
# torn tree can no longer satisfy them), so these must already sit in
# ``sys.modules``; the import-firewall test pins that property.
import sase.agent.names._registry_batch  # noqa: F401
import sase.agent.launch_timing  # noqa: F401
import sase.core.paths  # noqa: F401
import sase.core.managed_tmp_roots  # noqa: F401

RUNNER_CODE_REFRESHED_ENV = SASE_RUNNER_CODE_REFRESHED_ENV
_PLANNED_AGENT_NAME_ENV = "SASE_AGENT_PLANNED_NAME"


@dataclass
class _PreparedRunnerExecHandoff:
    """One-shot resources staged for a runner re-exec, with rollback data."""

    prompt_file: Path
    old_prompt: bytes | None
    old_local_macros_path: str | None
    new_local_macros_path: str | None
    old_planned_name: str | None
    planned_name_changed: bool
    old_refreshed: str | None

    def rollback(self) -> None:
        """Restore every environment and file mutation made during prep."""
        if self.planned_name_changed:
            if self.old_planned_name is None:
                os.environ.pop(_PLANNED_AGENT_NAME_ENV, None)
            else:
                os.environ[_PLANNED_AGENT_NAME_ENV] = self.old_planned_name
        if self.new_local_macros_path is not None:
            restore_local_macros_path(os.environ, self.old_local_macros_path)
            try:
                os.unlink(self.new_local_macros_path)
            except OSError:
                pass
        if self.old_refreshed is None:
            os.environ.pop(RUNNER_CODE_REFRESHED_ENV, None)
        else:
            os.environ[RUNNER_CODE_REFRESHED_ENV] = self.old_refreshed
        try:
            if self.old_prompt is None:
                self.prompt_file.unlink()
            else:
                self.prompt_file.write_bytes(self.old_prompt)
        except OSError:
            pass


def prepare_runner_exec_handoff(
    *,
    prompt_file: str,
    submitted_prompt: str,
    agent_name: str | None = None,
    artifacts_dir: str | None = None,
    local_macros: Mapping[str, Any] | None = None,
    local_macros_directory: str | None = None,
) -> _PreparedRunnerExecHandoff | None:
    """Stage prompt, macros, planned name, and refreshed guard for an exec.

    All mutations are reversible until ``execv`` succeeds. ``local_macros_directory``
    lets a long-lived lean wait keep its macro payload alongside durable run
    artifacts instead of in the expiring managed-temp handoff area.
    """
    prompt_path = Path(prompt_file)
    try:
        old_prompt = prompt_path.read_bytes()
    except FileNotFoundError:
        old_prompt = None
    except OSError as exc:
        print(
            "Warning: Skipping runner re-exec because the prior prompt file "
            f"could not be read at {prompt_file}: {exc}",
            file=sys.stderr,
            flush=True,
        )
        return None

    try:
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(submitted_prompt, encoding="utf-8")
    except OSError as exc:
        try:
            if old_prompt is None:
                prompt_path.unlink()
            else:
                prompt_path.write_bytes(old_prompt)
        except OSError:
            pass
        print(
            "Warning: Skipping runner re-exec because the temporary prompt "
            f"could not be restored at {prompt_file}: {exc}",
            file=sys.stderr,
            flush=True,
        )
        return None

    old_local_macros_path = read_local_macros_path(os.environ)
    new_local_macros_path: str | None = None
    if local_macros:
        try:
            new_local_macros_path = serialize_local_macros(
                dict(local_macros), directory=local_macros_directory
            )
            set_local_macros_path(os.environ, new_local_macros_path)
        except Exception as exc:
            if new_local_macros_path is not None:
                try:
                    os.unlink(new_local_macros_path)
                except OSError:
                    pass
            restore_local_macros_path(os.environ, old_local_macros_path)
            try:
                if old_prompt is None:
                    prompt_path.unlink()
                else:
                    prompt_path.write_bytes(old_prompt)
            except OSError:
                pass
            print(
                "Warning: Skipping runner re-exec because local macros could "
                f"not be re-materialized: {exc}",
                file=sys.stderr,
                flush=True,
            )
            return None

    old_planned_name = os.environ.get(_PLANNED_AGENT_NAME_ENV)
    planned_name_changed = agent_name is not None
    if agent_name is not None:
        continuation_planned_name = _validated_continuation_planned_name(
            agent_name,
            artifacts_dir,
        )
        if continuation_planned_name is not None:
            os.environ[_PLANNED_AGENT_NAME_ENV] = continuation_planned_name
        else:
            os.environ.pop(_PLANNED_AGENT_NAME_ENV, None)

    old_refreshed = os.environ.get(RUNNER_CODE_REFRESHED_ENV)
    os.environ[RUNNER_CODE_REFRESHED_ENV] = "1"
    return _PreparedRunnerExecHandoff(
        prompt_file=prompt_path,
        old_prompt=old_prompt,
        old_local_macros_path=old_local_macros_path,
        new_local_macros_path=new_local_macros_path,
        old_planned_name=old_planned_name,
        planned_name_changed=planned_name_changed,
        old_refreshed=old_refreshed,
    )


def execv_with_sigterm_mask(
    path: str,
    argv: list[str],
    *,
    before_exec: Callable[[], bool] | None = None,
) -> bool:
    """Keep SIGTERM pending and make one final handled-kill decision.

    The callable runs after SIGTERM is blocked, so a kill already handled by
    this interpreter can cancel the hop while a new signal stays pending for
    the exec'd program. Return ``False`` when the callable declines the exec.
    """
    blocker = getattr(signal, "pthread_sigmask", None)
    old_mask = (
        blocker(signal.SIG_BLOCK, {signal.SIGTERM}) if callable(blocker) else None
    )
    try:
        if before_exec is not None and not before_exec():
            if callable(blocker) and old_mask is not None:
                blocker(signal.SIG_SETMASK, old_mask)
            return False
        os.execv(path, argv)
    except BaseException:
        if callable(blocker) and old_mask is not None:
            blocker(signal.SIG_SETMASK, old_mask)
        raise
    # Real execv does not return. This branch keeps unit-test substitutions
    # from leaking the temporary signal mask into the test process.
    if callable(blocker) and old_mask is not None:
        blocker(signal.SIG_SETMASK, old_mask)
    return True


def _editable_sase_source_root() -> Path | None:
    """Resolve the source checkout backing an editable sase installation."""
    warnings: list[str] = []
    try:
        distribution = find_distribution(HOST_DISTRIBUTION_NAME, warnings)
        direct_url = direct_url_info(distribution, warnings)
        resolved_install_type = (
            direct_url.install_type if direct_url else install_type(distribution)
        )
        if resolved_install_type != "editable":
            return None
        return source_root(
            source_kind="python",
            direct_url=direct_url,
            install_type=resolved_install_type,
            import_resolution=resolve_import("sase"),
            distribution_location=distribution_location(distribution),
        )
    except Exception:
        return None


def _source_code_identity(source_checkout: Path | None) -> str | None:
    """Return the checkout's full HEAD SHA, or ``None`` when unavailable."""
    if source_checkout is None:
        return None
    result = probe_git_metadata_at_ref(source_checkout, "HEAD")
    return result.metadata.commit if result.metadata is not None else None


def runner_code_identity() -> str | None:
    """Return the code identity for the editable checkout used by this process."""
    return _source_code_identity(_editable_sase_source_root())


def reconcile_prompt_with_live_auto_state(
    submitted_prompt: str,
    artifacts_dir: str | None,
) -> str:
    """Rewrite *submitted_prompt*'s ``%auto`` from the live agent meta.

    The refreshed pass re-extracts directives from this prompt, so the
    live ``agent_meta.json`` auto state must win over the stale in-memory
    prompt: otherwise an ``A`` toggle-off is undone (the ``%auto`` still in
    the prompt re-enables auto) and a toggle-on is lost (no ``%auto`` in
    the prompt drops auto). Without an artifacts dir there is no live
    meta to consult and the prompt passes through unchanged.

    The replacement directive comes from the live autonomy record's
    selection, preserving ``:plan`` exactly; agents without a record fall
    back to the legacy-key translation, so a ``%auto:plan`` agent never
    widens to bare ``%auto`` and legacy values never widen either.
    """
    if not artifacts_dir:
        return submitted_prompt
    from sase.autonomy.record import (
        live_record,
        read_record,
        selection_to_prompt_prefix,
    )
    from sase.axe.agent_meta import read_live_agent_meta
    from sase.macro._directive_edit_core import set_prompt_directive

    record = live_record(artifacts_dir)
    if record is not None:
        prefix = selection_to_prompt_prefix(record.get("selection")).strip()
    else:
        live_meta = read_live_agent_meta(artifacts_dir)
        translated = read_record(live_meta)
        if translated is not None:
            prefix = selection_to_prompt_prefix(translated.get("selection")).strip()
        else:
            prefix = ""
    replacement = prefix or None
    return set_prompt_directive(submitted_prompt, {"auto"}, replacement)


def refresh_runner_code_after_wait(
    startup_identity: str | None,
    *,
    blocking_wait_occurred: bool,
    killed: bool,
    prompt_file: str,
    submitted_prompt: str,
    agent_name: str | None = None,
    artifacts_dir: str | None = None,
    local_macros: Mapping[str, Any] | None = None,
    is_killed: Callable[[], bool] | None = None,
) -> None:
    """Re-exec the runner when its editable source HEAD moved during a wait.

    The one-shot guard is removed on the refreshed pass before agent execution,
    preventing nested agents from inheriting runner-internal refresh state.

    No ``sase.*`` import may run between the identity comparison above and
    ``os.execv`` below: the new tree can be torn relative to this image, so
    every helper this path touches is imported at module scope (and the
    lazily-imported leaves warmed there too). The ``%auto`` reconcile used to
    live here; it now runs in the refreshed pass's bootstrap instead, where
    the new tree is already the running code.
    """
    already_refreshed = os.environ.pop(RUNNER_CODE_REFRESHED_ENV, None) is not None
    if already_refreshed or not blocking_wait_occurred or killed:
        return
    if startup_identity is None:
        return

    current_identity = runner_code_identity()
    if current_identity is None or current_identity == startup_identity:
        return

    print(
        "Refreshing sase runner code after dependency wait: "
        f"{startup_identity} -> {current_identity}",
        flush=True,
    )
    # The refreshed pass re-extracts directives from this file, applying the
    # live ``%auto`` reconcile during its own bootstrap (see
    # ``_load_submitted_prompt``), so the prompt is persisted verbatim here.
    prepared = prepare_runner_exec_handoff(
        prompt_file=prompt_file,
        submitted_prompt=submitted_prompt,
        agent_name=agent_name,
        artifacts_dir=artifacts_dir,
        local_macros=local_macros,
    )
    if prepared is None:
        return
    try:
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.flush()
            except (AttributeError, OSError, ValueError):
                pass
        exec_attempted = execv_with_sigterm_mask(
            sys.executable,
            [sys.executable, *sys.argv],
            before_exec=(lambda: not is_killed()) if is_killed is not None else None,
        )
        if exec_attempted is False:
            prepared.rollback()
            return
    except OSError as exc:
        prepared.rollback()
        print(
            f"Warning: Failed to refresh sase runner code; continuing: {exc}",
            file=sys.stderr,
            flush=True,
        )


def _validated_continuation_planned_name(
    agent_name: str | None,
    artifacts_dir: str | None,
) -> str | None:
    """Return the current run name only when this artifact directory owns it."""
    if not agent_name or not artifacts_dir:
        return None
    try:
        if planned_name_is_reserved_for_artifacts(agent_name, artifacts_dir):
            return agent_name
    except Exception:
        return None
    return None
