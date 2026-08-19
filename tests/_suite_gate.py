"""Host-global worker-token budget for parallel pytest suite runs.

Several agents run this suite on one machine at once, and each one wants
every core. The gate makes that demand explicit: a run that asks for xdist
workers must first hold that many *tokens* from a host-wide pool, and it waits
until they are free. Nothing here bounds a serial run — a run of width one
takes no tokens.

This module is the pytest-facing edge of the family. It decides whether this
process owes the pool anything at all, and it wires the answer into the root
conftest's hooks. Its neighbours hold the parts that stand on their own:

* :mod:`tests._suite_gate_lease` — the lease state machine and its registry.
* :mod:`tests._suite_gate_pool` — the token lock files and pool capacity.
* :mod:`tests._suite_gate_holders` — reading, judging, and reclaiming grants.
* :mod:`tests._suite_gate_progress` — the heartbeat sidecar that proves life.
* :mod:`tests._suite_gate_budget` — how wide this host and this run may go.
* :mod:`tests._suite_gate_env` — the environment variables all of it reads.
* :mod:`tests._suite_gate_messages` — what a waiting run tells its reader.
"""

from __future__ import annotations

import os
import time
from typing import IO

import pytest

from tests._suite_gate_budget import configured_token_budget
from tests._suite_gate_env import (
    DISABLED_ENV,
    FDS_ENV,
    GOVERNED_ENV,
    LEASE_ID_ENV,
    LEASE_PID_ENV,
    gate_directory,
    gate_timeout,
)
from tests._suite_gate_lease import WorkerTokenLease, lease_by_id
from tests._suite_gate_pool import release_token_files, started_from_token_files
from tests._suite_gate_progress import should_record_progress, write_progress_sidecar


_CONFIG_ATTRIBUTE = "_sase_worker_token_lease"


def configure_suite_gate(config: pytest.Config) -> None:
    """Acquire exact worker capacity for an ungoverned xdist controller."""
    if _is_gate_exempt():
        _adopt_inherited_lease(config)
        return

    requested_workers = _xdist_worker_count(config)
    if requested_workers is None:
        return
    budget, capacity_is_explicit = configured_token_budget()
    lease = WorkerTokenLease(
        directory=gate_directory(),
        budget=budget,
        timeout=gate_timeout(),
        capacity_is_explicit=capacity_is_explicit,
    )
    lease.acquire(requested_workers, requested_workers, exact=True)
    setattr(config, _CONFIG_ATTRIBUTE, lease)


def unconfigure_suite_gate(config: pytest.Config) -> None:
    """Release worker capacity previously acquired for ``config``."""
    lease = getattr(config, _CONFIG_ATTRIBUTE, None)
    if not isinstance(lease, WorkerTokenLease):
        return
    lease.release()
    delattr(config, _CONFIG_ATTRIBUTE)


def _adopt_inherited_lease(config: pytest.Config) -> None:
    """Re-wrap exec-surviving token FDs so this process can watchdog and release.

    ``tools/run_pytest`` acquires, marks the descriptors inheritable, and
    ``execv``s into pytest. The lease object dies with the runner; the flocks
    do not. Only the same PID that acquired may adopt — xdist workers and
    nested pytest children inherit the FDs but have a different pid, so they
    must not unlock the controller's grant on exit.
    """
    if "PYTEST_XDIST_WORKER" in os.environ:
        return
    raw_pid = os.environ.get(LEASE_PID_ENV)
    raw_fds = os.environ.get(FDS_ENV)
    lease_id = os.environ.get(LEASE_ID_ENV)
    if not raw_pid or not raw_fds or not lease_id:
        return
    try:
        if int(raw_pid) != os.getpid():
            return
        fds = [int(part) for part in raw_fds.split(",") if part]
    except ValueError:
        return
    if not fds:
        return
    token_files: list[IO[str]] = []
    try:
        token_files = [os.fdopen(fd, "r+", encoding="utf-8") for fd in fds]
    except OSError:
        release_token_files(token_files)
        return
    lease = WorkerTokenLease(
        directory=gate_directory(),
        budget=max(len(token_files), 1),
        timeout=0.0,
    )
    started = started_from_token_files(token_files)
    lease.adopt(
        token_files,
        lease_id=lease_id,
        started=started if started is not None else time.time(),
    )
    setattr(config, _CONFIG_ATTRIBUTE, lease)


def _is_gate_exempt() -> bool:
    # The bare disable flag counts here, uncorroborated or not: this is the
    # in-pytest safety net, and a caller who deliberately disabled the gate must
    # not have it re-acquire underneath them. Bounding the *width* of such a run
    # is `tools/run_pytest`'s job, because that is the only place that chooses
    # one.
    return descendant_exemption() or os.environ.get(DISABLED_ENV) == "1"


def _xdist_worker_count(config: pytest.Config) -> int | None:
    option = config.option
    tx = getattr(option, "tx", None)
    if tx:
        worker_count = len(tx)
    else:
        raw_count = getattr(option, "numprocesses", None)
        if raw_count in (None, 0, 1, "0", "1"):
            return None
        if raw_count in ("auto", "logical"):
            hook = getattr(config, "hook", None)
            if hook is None:
                raise pytest.UsageError(
                    f"Cannot resolve pytest-xdist -n {raw_count} safely; use a "
                    "positive numeric worker count."
                )
            worker_count = hook.pytest_xdist_auto_num_workers(config=config)
        else:
            try:
                worker_count = int(raw_count)
            except (TypeError, ValueError) as error:
                raise pytest.UsageError(
                    f"Cannot resolve pytest-xdist worker request {raw_count!r}; "
                    "use a positive numeric count, auto, or logical."
                ) from error

        max_processes = getattr(option, "maxprocesses", None)
        if max_processes:
            worker_count = min(worker_count, int(max_processes))

    if worker_count <= 1:
        return None
    return worker_count


def descendant_exemption() -> bool:
    """Report whether an ancestor's lease already accounts for this demand.

    The distinction the pool depends on. Every held lease marks its descendants
    with ``GOVERNED_ENV``, and xdist marks its own workers, so either signal
    means the tokens for this width have already been taken by somebody above
    us — asking again would double-count the same demand. A bare
    ``DISABLED_ENV`` is deliberately *not* corroboration: anyone can export it,
    and one that did is exactly how a ``-n 64`` run took a 64-worker share of a
    62 GiB host while holding zero tokens.
    """
    return os.environ.get(GOVERNED_ENV) == "1" or "PYTEST_XDIST_WORKER" in os.environ


def record_lease_progress(event: str) -> None:
    """Record suite progress for the inherited or locally held worker-token grant.

    xdist workers skip this: the controller sees their forwarded reports and is
    the process whose pid matches the lease. Nested pytest subprocesses still
    write the sidecar — a child that is running tests *is* progress — but they
    cannot adopt the parent's flock.
    """
    if "PYTEST_XDIST_WORKER" in os.environ:
        return
    lease_id = os.environ.get(LEASE_ID_ENV)
    if not lease_id:
        return
    now = time.time()
    progress = should_record_progress(lease_id, event, now)
    if progress is None:
        return
    directory = gate_directory()
    write_progress_sidecar(
        directory, lease_id, heartbeat=now, progress=progress, event=event
    )
    lease = lease_by_id(lease_id)
    if lease is not None:
        lease.refresh_heartbeat(now, progress)
