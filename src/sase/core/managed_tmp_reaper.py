"""Thin, schema-checked adapter over the Rust managed-temp-root reaper.

:func:`sase.core.paths.get_sase_managed_tmpdir` documents its root as reapable,
and :mod:`sase_core_rs` (``sase-core``'s ``managed_tmp`` crate) owns the actual
age/pressure retention decision, so every frontend gets the same safety rules.
This module resolves the configured horizons and pressure thresholds, calls
the Rust binding, and translates its wire result back into the Python result
shape this repo's callers already depend on — including de-indexing a reaped
directory that may have been an agent's ``artifacts_dir``.

Horizons are per subdirectory rather than global, because the lifetimes differ
by two orders of magnitude: an editor's scratch file dies with the editor, while
``workflow-artifacts/`` holds the artifact directory the ACE Agents tab reads
back for as long as the run is worth looking at. The bucket-to-horizon-category
table below is structural and not user-configurable; the horizon durations and
pressure thresholds themselves are (``managed_tmp`` in ``sase.yml``).
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.config import (
    DEFAULT_MANAGED_TMP_BUILD_SCRATCH_HORIZON_SECONDS as BUILD_SCRATCH_HORIZON_SECONDS,
)
from sase.config import (
    DEFAULT_MANAGED_TMP_COMMAND_SCRATCH_HORIZON_SECONDS as COMMAND_SCRATCH_HORIZON_SECONDS,
)
from sase.config import (
    DEFAULT_MANAGED_TMP_HANDOFF_HORIZON_SECONDS as HANDOFF_HORIZON_SECONDS,
)
from sase.config import (
    DEFAULT_MANAGED_TMP_MAX_REMOVALS as DEFAULT_MAX_REMOVALS,
)
from sase.config import (
    DEFAULT_MANAGED_TMP_PRESSURE_MAX_BYTES as DEFAULT_PRESSURE_MAX_BYTES,
)
from sase.config import (
    DEFAULT_MANAGED_TMP_PRESSURE_LOW_FREE_SPACE_MIN_AGE_SECONDS,
)
from sase.config import (
    DEFAULT_MANAGED_TMP_PRESSURE_MIN_AGE_SECONDS as DEFAULT_PRESSURE_MIN_AGE_SECONDS,
)
from sase.config import (
    DEFAULT_MANAGED_TMP_PRESSURE_MIN_AVAILABLE_BYTES as DEFAULT_PRESSURE_MIN_AVAILABLE_BYTES,
)
from sase.config import (
    DEFAULT_MANAGED_TMP_PRESSURE_MIN_ENTRY_BYTES as DEFAULT_PRESSURE_MIN_ENTRY_BYTES,
)
from sase.config import (
    DEFAULT_MANAGED_TMP_PRESSURE_RECOVERY_AVAILABLE_BYTES as DEFAULT_PRESSURE_RECOVERY_AVAILABLE_BYTES,
)
from sase.config import (
    DEFAULT_MANAGED_TMP_PRESSURE_TARGET_BYTES as DEFAULT_PRESSURE_TARGET_BYTES,
)
from sase.config import (
    DEFAULT_MANAGED_TMP_RUN_ARTIFACT_HORIZON_SECONDS as RUN_ARTIFACT_HORIZON_SECONDS,
)
from sase.config import (
    get_managed_tmp_build_scratch_horizon_seconds,
    get_managed_tmp_command_scratch_horizon_seconds,
    get_managed_tmp_handoff_horizon_seconds,
    get_managed_tmp_max_removals,
    get_managed_tmp_pressure_low_free_space_min_age_seconds,
    get_managed_tmp_pressure_max_bytes,
    get_managed_tmp_pressure_min_age_seconds,
    get_managed_tmp_pressure_min_available_bytes,
    get_managed_tmp_pressure_min_entry_bytes,
    get_managed_tmp_pressure_recovery_available_bytes,
    get_managed_tmp_pressure_target_bytes,
    get_managed_tmp_run_artifact_horizon_seconds,
)
from sase.core.paths import managed_tmpdir_root
from sase.core.rust import require_rust_binding

DEFAULT_PRESSURE_LOW_FREE_SPACE_MIN_AGE_SECONDS = (
    DEFAULT_MANAGED_TMP_PRESSURE_LOW_FREE_SPACE_MIN_AGE_SECONDS
)

DEFAULT_HORIZON_SECONDS = HANDOFF_HORIZON_SECONDS
"""Horizon for unrecognized subdirectories and stray top-level entries.

Nothing writes directly into the bare root any more, so anything found there is
either pre-``sase-96`` residue or a subdirectory added after this table. Both
are safe to bound at the handoff horizon, but stable top-level directories are
still pruned by child so a fresh handoff file cannot be lost with its parent.
"""

_COMMAND_SCRATCH_BUCKETS = (
    # Scratch whose reader is the command that wrote it.
    "ace-profiles",
    "agent-clis",
    "artifact-pages",
    "chezmoi-deploy-locks",
    "commit-messages",
    "editors",
    "embedded-artifacts",
    "sdd-remote-clone-pool",
    "viewers",
    "workflow-loader",
    "wrappers",
    "xprompts_catalog",
    # Per-agent scratch exported through the child process environment.
    "agent-tmp",
)
_HANDOFF_BUCKETS = (
    # Handoff files a launched process owns for the length of its run.
    "gh-diffs",
    "handoff",
    # A provider re-reads this mid-run (llm_provider/muse.py).
    "muse-prompts",
)
_BUILD_SCRATCH_BUCKETS = (
    "build-targets",
    "cargo-targets",
)
_RUN_ARTIFACT_BUCKETS = (
    # Read back by the ACE Agents tab well after the run itself ended.
    "launch-prompts",
    "workflow-artifacts",
)

MANAGED_TMPDIR_HORIZONS: Mapping[str, float] = {
    **dict.fromkeys(_COMMAND_SCRATCH_BUCKETS, COMMAND_SCRATCH_HORIZON_SECONDS),
    **dict.fromkeys(_HANDOFF_BUCKETS, HANDOFF_HORIZON_SECONDS),
    **dict.fromkeys(_BUILD_SCRATCH_BUCKETS, BUILD_SCRATCH_HORIZON_SECONDS),
    **dict.fromkeys(_RUN_ARTIFACT_BUCKETS, RUN_ARTIFACT_HORIZON_SECONDS),
}
"""Per-subdirectory horizons, keyed by the ``get_sase_managed_tmpdir`` part.

These are the shipped defaults; :func:`reap_managed_tmpdir` resolves the live,
possibly user-overridden values through ``sase.config`` unless the caller
passes an explicit ``horizons`` override.
"""

PRESSURE_REAP_BUCKETS = frozenset({"build-targets", "cargo-targets"})
"""Build-output buckets whose aged large children may be pruned under pressure."""

MANAGED_TMP_REAP_WIRE_SCHEMA_VERSION = 2
"""Must match ``sase_core::managed_tmp::MANAGED_TMP_REAP_WIRE_SCHEMA_VERSION``."""


@dataclass(frozen=True)
class _ManagedTmpReapResult:
    """What one reaper invocation looked at and reclaimed."""

    root: Path
    apply: bool
    scanned: int
    selected: int
    removed: int
    selected_by_subdir: Mapping[str, int]
    removed_by_subdir: Mapping[str, int]
    deindexed: int
    capped: bool
    pressure_selected: int
    pressure_removed: int
    pressure_reclaimable_bytes: int
    pressure_reclaimed_bytes: int
    pressure_trigger: str | None
    pressure_root_size_bytes: int
    pressure_available_bytes: int | None
    pressure_recovery_available_bytes: int
    pressure_effective_min_age_seconds: float | None

    def describe(self) -> str:
        """Return a one-line human summary of the largest buckets pruned."""
        count = self.removed if self.apply else self.selected
        if not count:
            return f"nothing stale under {self.root}"
        busiest = sorted(
            (self.removed_by_subdir if self.apply else self.selected_by_subdir).items(),
            key=lambda item: (-item[1], item[0]),
        )
        detail = ", ".join(f"{name}={count}" for name, count in busiest)
        if self.deindexed:
            detail += f"; {self.deindexed} artifact-index rows dropped"
        pressure_count = self.pressure_removed if self.apply else self.pressure_selected
        if pressure_count:
            trigger = f" via {self.pressure_trigger}" if self.pressure_trigger else ""
            pressure_bytes = (
                self.pressure_reclaimed_bytes
                if self.apply
                else self.pressure_reclaimable_bytes
            )
            detail += (
                f"; pressure={pressure_count}"
                f" ({_format_bytes(pressure_bytes)}{trigger})"
            )
        suffix = " (removal budget reached)" if self.capped else ""
        verb = "reclaimed" if self.apply else "would reclaim"
        return f"{verb} {count} entries under {self.root}: {detail}{suffix}"


def _default_horizons() -> dict[str, float]:
    command_scratch = get_managed_tmp_command_scratch_horizon_seconds()
    handoff = get_managed_tmp_handoff_horizon_seconds()
    build_scratch = get_managed_tmp_build_scratch_horizon_seconds()
    run_artifact = get_managed_tmp_run_artifact_horizon_seconds()
    return {
        **dict.fromkeys(_COMMAND_SCRATCH_BUCKETS, command_scratch),
        **dict.fromkeys(_HANDOFF_BUCKETS, handoff),
        **dict.fromkeys(_BUILD_SCRATCH_BUCKETS, build_scratch),
        **dict.fromkeys(_RUN_ARTIFACT_BUCKETS, run_artifact),
    }


def reap_managed_tmpdir(
    root: Path | None = None,
    *,
    now: float | None = None,
    horizons: Mapping[str, float] | None = None,
    default_horizon_seconds: float | None = None,
    max_removals: int | None = None,
    pressure_max_bytes: int | None = None,
    pressure_target_bytes: int | None = None,
    pressure_min_available_bytes: int | None = None,
    pressure_recovery_available_bytes: int | None = None,
    pressure_min_age_seconds: float | None = None,
    pressure_low_free_space_min_age_seconds: float | None = None,
    pressure_min_entry_bytes: int | None = None,
    filesystem_available_bytes: int | None = None,
    apply: bool = True,
) -> _ManagedTmpReapResult:
    """Prune stale entries under the managed SASE temp *root* through Rust.

    Every tunable defaults to the live ``managed_tmp`` config
    (``sase.config.get_managed_tmp_*``) when omitted; passing a value
    overrides it for this call only, which is what the pressure-reaping tests
    do. *now* and *filesystem_available_bytes* are test hooks; production
    calls read the clock and available bytes for real.

    Known and future subdirectories are descended into and pruned against their
    horizon; the subdirectory itself always survives. Anything else at the top
    level is pruned against the resolved default horizon. After the age pass,
    the pressure pass can reclaim aged, large build-output entries before their
    full age horizon when the managed root is too large or the filesystem is
    low on free space.
    """
    reap_root = managed_tmpdir_root() if root is None else root
    clock = time.time() if now is None else now
    resolved_horizons = _default_horizons() if horizons is None else horizons
    resolved_default_horizon = (
        get_managed_tmp_handoff_horizon_seconds()
        if default_horizon_seconds is None
        else default_horizon_seconds
    )
    resolved_max_removals = (
        get_managed_tmp_max_removals() if max_removals is None else max_removals
    )
    resolved_pressure_max_bytes = (
        get_managed_tmp_pressure_max_bytes()
        if pressure_max_bytes is None
        else pressure_max_bytes
    )
    resolved_pressure_target_bytes = (
        get_managed_tmp_pressure_target_bytes()
        if pressure_target_bytes is None
        else pressure_target_bytes
    )
    resolved_pressure_min_available_bytes = (
        get_managed_tmp_pressure_min_available_bytes()
        if pressure_min_available_bytes is None
        else pressure_min_available_bytes
    )
    resolved_pressure_recovery_available_bytes = (
        get_managed_tmp_pressure_recovery_available_bytes()
        if pressure_recovery_available_bytes is None
        else pressure_recovery_available_bytes
    )
    resolved_pressure_min_age_seconds = (
        get_managed_tmp_pressure_min_age_seconds()
        if pressure_min_age_seconds is None
        else pressure_min_age_seconds
    )
    resolved_pressure_low_free_space_min_age_seconds = (
        get_managed_tmp_pressure_low_free_space_min_age_seconds()
        if pressure_low_free_space_min_age_seconds is None
        else pressure_low_free_space_min_age_seconds
    )
    resolved_pressure_min_entry_bytes = (
        get_managed_tmp_pressure_min_entry_bytes()
        if pressure_min_entry_bytes is None
        else pressure_min_entry_bytes
    )

    _require_reap_wire_schema()
    request = {
        "schema_version": MANAGED_TMP_REAP_WIRE_SCHEMA_VERSION,
        "root": str(reap_root),
        "apply": apply,
        "now_epoch_seconds": float(clock),
        "horizons": {name: float(value) for name, value in resolved_horizons.items()},
        "default_horizon_seconds": float(resolved_default_horizon),
        "max_removals": resolved_max_removals,
        "pressure_max_bytes": resolved_pressure_max_bytes,
        "pressure_target_bytes": resolved_pressure_target_bytes,
        "pressure_min_available_bytes": resolved_pressure_min_available_bytes,
        "pressure_recovery_available_bytes": resolved_pressure_recovery_available_bytes,
        "pressure_min_age_seconds": float(resolved_pressure_min_age_seconds),
        "pressure_low_free_space_min_age_seconds": float(
            resolved_pressure_low_free_space_min_age_seconds
        ),
        "pressure_min_entry_bytes": resolved_pressure_min_entry_bytes,
        "pressure_reap_buckets": sorted(PRESSURE_REAP_BUCKETS),
        "filesystem_available_bytes": filesystem_available_bytes,
    }
    binding = require_rust_binding("reap_managed_tmpdir")
    raw = binding(request)
    return _result_from_wire(raw)


def _require_reap_wire_schema() -> None:
    binding = require_rust_binding("managed_tmp_reap_wire_schema_version")
    version = int(binding())
    if version != MANAGED_TMP_REAP_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            "sase_core_rs managed-temp-reap wire is stale: expected "
            f"{MANAGED_TMP_REAP_WIRE_SCHEMA_VERSION}, got {version}"
        )


def _result_from_wire(raw: Mapping[str, Any]) -> _ManagedTmpReapResult:
    if raw["schema_version"] != MANAGED_TMP_REAP_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            "sase_core_rs returned an incompatible managed-temp-reap result: "
            f"schema_version must be {MANAGED_TMP_REAP_WIRE_SCHEMA_VERSION}"
        )
    removed_directories = tuple(Path(entry) for entry in raw["removed_directories"])
    deindexed = 0
    if removed_directories:
        # A reaped directory may have been an agent's artifacts_dir: workflows
        # launched without an explicit one land in ``workflow-artifacts/``.
        from sase.core.agent_artifact_index_lifecycle_mutations import (
            delete_agent_artifact_index_artifacts,
        )

        deindexed = delete_agent_artifact_index_artifacts(removed_directories)

    return _ManagedTmpReapResult(
        root=Path(raw["root"]),
        apply=bool(raw["apply"]),
        scanned=raw["scanned"],
        selected=raw["selected"],
        removed=raw["removed"],
        selected_by_subdir=dict(raw["selected_by_subdir"]),
        removed_by_subdir=dict(raw["removed_by_subdir"]),
        deindexed=deindexed,
        capped=raw["capped"],
        pressure_selected=raw["pressure_selected"],
        pressure_removed=raw["pressure_removed"],
        pressure_reclaimable_bytes=raw["pressure_reclaimable_bytes"],
        pressure_reclaimed_bytes=raw["pressure_reclaimed_bytes"],
        pressure_trigger=raw["pressure_trigger"],
        pressure_root_size_bytes=raw["pressure_root_size_bytes"],
        pressure_available_bytes=raw["pressure_available_bytes"],
        pressure_recovery_available_bytes=raw["pressure_recovery_available_bytes"],
        pressure_effective_min_age_seconds=raw.get(
            "pressure_effective_min_age_seconds"
        ),
    )


def _format_bytes(value: int) -> str:
    gib = 1024**3
    if value >= gib:
        return f"{value / gib:.1f} GiB"
    mib = 1024**2
    if value >= mib:
        return f"{value / mib:.1f} MiB"
    kib = 1024
    if value >= kib:
        return f"{value / kib:.1f} KiB"
    return f"{value} B"


__all__ = [
    "BUILD_SCRATCH_HORIZON_SECONDS",
    "COMMAND_SCRATCH_HORIZON_SECONDS",
    "DEFAULT_HORIZON_SECONDS",
    "DEFAULT_MAX_REMOVALS",
    "DEFAULT_PRESSURE_LOW_FREE_SPACE_MIN_AGE_SECONDS",
    "DEFAULT_PRESSURE_MAX_BYTES",
    "DEFAULT_PRESSURE_MIN_AGE_SECONDS",
    "DEFAULT_PRESSURE_MIN_AVAILABLE_BYTES",
    "DEFAULT_PRESSURE_MIN_ENTRY_BYTES",
    "DEFAULT_PRESSURE_RECOVERY_AVAILABLE_BYTES",
    "DEFAULT_PRESSURE_TARGET_BYTES",
    "HANDOFF_HORIZON_SECONDS",
    "MANAGED_TMPDIR_HORIZONS",
    "PRESSURE_REAP_BUCKETS",
    "RUN_ARTIFACT_HORIZON_SECONDS",
    "reap_managed_tmpdir",
]
