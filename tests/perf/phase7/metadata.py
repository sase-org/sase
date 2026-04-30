"""Phase 7 measurement metadata envelope and artifact-name helpers.

Every Phase 7 artifact under ``plans/202604/perf_artifacts/`` has to be
comparable across runs and across surfaces, so every benchmark — whether
it is a core-operation microbenchmark from Phase 7B or an end-to-end
measurement from Phase 7C — wraps its scenario data in the same
:func:`build_metadata` envelope.

The helper does not run any subprocesses by default; everything is
read from already-imported Python state, ``platform``, and an optional
``cwd``-aware git SHA probe. When the probe fails (no git, detached
worktree, etc.) the SHA fields are recorded as ``None`` rather than
raising — Phase 7 agents should never have a benchmark fail because the
metadata helper could not find a git directory.
"""

from __future__ import annotations

import datetime as _dt
import platform
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal


PHASE7_PHASE_TAG: Literal["7"] = "7"
"""Phase identifier embedded in every Phase 7 artifact (``"phase": "7"``)."""

PHASE7_ARTIFACT_DIR: Path = Path("plans/202604/perf_artifacts")
"""Repo-relative directory every Phase 7 JSON artifact lives under."""

_ARTIFACT_PREFIX = "rust_backend_phase7"


class BackendChoice(StrEnum):
    """Backend tag used to name a Phase 7 artifact.

    Post-Phase-8 the facades always run direct-Rust, but the historical
    Phase 7 artifact filenames still use these tags so the existing
    captures under ``plans/202604/perf_artifacts/`` remain referenceable
    by name from the Phase 7 driver.
    """

    DEFAULT_PYTHON = "default_python"
    DEFAULT_RUST = "default_rust"
    EXPLICIT_PYTHON = "explicit_python"
    EXPLICIT_RUST = "explicit_rust"
    SUMMARY = "summary"


@dataclass(frozen=True)
class Phase7Metadata:
    """Common envelope every Phase 7 artifact embeds under ``"metadata"``.

    Phase 7B/7C agents may extend the dict returned by :meth:`as_dict`
    with surface-specific keys; the fields here are the ones that must
    be present everywhere so Phase 7D/7E tooling can pivot across
    artifacts without special-casing.
    """

    tool: str
    """Benchmark harness name (e.g. ``"bench_core_parse"``)."""

    surface: str
    """User-visible surface or operation label (e.g. ``"parse_project_bytes"``,
    ``"sase_ace_cold_open"``). Phase 7D groups artifacts by this key."""

    workload: str
    """Workload label (e.g. ``"golden_myproj"``, ``"synthetic_1000_specs"``)."""

    backend: BackendChoice
    """Which backend the scenarios in this artifact were measured under."""

    runs: int
    """Timed iterations per scenario. ``0`` is allowed for summary artifacts."""

    warmup: int
    """Untimed warmup iterations per scenario."""

    timestamp: str
    """ISO-8601 UTC capture time (``YYYY-MM-DDTHH:MM:SSZ``)."""

    git_sha: str | None
    """Short git SHA of the sase repo at capture time, or ``None`` outside a git tree."""

    git_dirty: bool | None
    """``True`` if the sase worktree had uncommitted changes; ``None`` if unknown."""

    python: str
    """``sys.version.split()[0]`` (e.g. ``"3.14.3"``)."""

    system: str
    """``platform.system()`` (e.g. ``"Linux"``)."""

    machine: str
    """``platform.machine()`` (e.g. ``"x86_64"``)."""

    processor: str
    """``platform.processor()`` or ``"unknown"`` if the OS does not report one."""

    rust_available: bool
    """``True`` when ``sase_core_rs`` was importable at capture time."""

    rust_module_path: str | None
    """``sase_core_rs.__file__`` if importable, else ``None``."""

    rust_module_version: str | None
    """``sase_core_rs.__version__`` if exposed by the wheel, else ``None``."""

    extra: Mapping[str, Any] = field(default_factory=dict)
    """Surface-specific metadata that does not fit the common shape (e.g.
    a TUI trace's terminal size, an agent-scan's projects-root path)."""

    @property
    def phase(self) -> str:
        return PHASE7_PHASE_TAG

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict with ``phase`` injected.

        Use this directly as the ``"metadata"`` value in a Phase 7
        artifact, or merge it into a top-level dict as the harness
        prefers.
        """
        d = asdict(self)
        # ``BackendChoice`` is a StrEnum so json.dumps handles it, but
        # asdict() preserves the enum instance — coerce to str for
        # downstream tooling that does shallow string compares.
        d["backend"] = str(self.backend)
        d["phase"] = self.phase
        # Hide the ``extra`` mapping when empty so the artifact is
        # easier to eyeball, but always emit it when populated.
        if not self.extra:
            d.pop("extra", None)
        return d


def _probe_git(cwd: Path | None) -> tuple[str | None, bool | None]:
    """Return ``(short_sha, dirty)`` for the git tree at ``cwd``.

    Falls back to ``(None, None)`` for any git error (not a repo,
    binary missing, detached state). Phase 7 metadata never fails the
    benchmark on a git probe.
    """
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=str(cwd) if cwd is not None else None,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        ).strip()
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return None, None

    try:
        status = subprocess.check_output(
            ["git", "status", "--porcelain"],
            cwd=str(cwd) if cwd is not None else None,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        )
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        # We have a SHA but cannot tell whether the tree is dirty —
        # surface that as ``None`` rather than guessing ``False``.
        return sha or None, None

    return sha or None, bool(status.strip())


def _probe_rust_module() -> tuple[bool, str | None, str | None]:
    """Return ``(available, module_path, version)`` for ``sase_core_rs``."""
    try:
        import sase_core_rs as _rs  # type: ignore[import-not-found]
    except ImportError:
        return False, None, None

    module_path = getattr(_rs, "__file__", None)
    version = getattr(_rs, "__version__", None)
    return True, module_path, version if isinstance(version, str) else None


def build_metadata(
    *,
    tool: str,
    surface: str,
    workload: str,
    backend: BackendChoice,
    runs: int,
    warmup: int,
    repo_root: Path | None = None,
    extra: Mapping[str, Any] | None = None,
) -> Phase7Metadata:
    """Build a :class:`Phase7Metadata` envelope.

    Args:
        tool: Harness name (e.g. ``"bench_core_parse"``).
        surface: User-visible surface or operation label.
        workload: Workload label distinguishing which input was timed.
        backend: Which backend the scenarios in this artifact target.
        runs: Timed iterations per scenario.
        warmup: Untimed warmup iterations per scenario.
        repo_root: Optional override for the git probe's working
            directory. Defaults to the sase repo root inferred from this
            file's location.
        extra: Surface-specific metadata to merge into ``extra``.
    """
    if repo_root is None:
        repo_root = Path(__file__).resolve().parents[3]

    git_sha, git_dirty = _probe_git(repo_root)
    rust_available, rust_path, rust_version = _probe_rust_module()

    timestamp = _dt.datetime.now(tz=_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    return Phase7Metadata(
        tool=tool,
        surface=surface,
        workload=workload,
        backend=backend,
        runs=runs,
        warmup=warmup,
        timestamp=timestamp,
        git_sha=git_sha,
        git_dirty=git_dirty,
        python=sys.version.split()[0],
        system=platform.system(),
        machine=platform.machine(),
        processor=platform.processor() or "unknown",
        rust_available=rust_available,
        rust_module_path=rust_path,
        rust_module_version=rust_version,
        extra=dict(extra) if extra else {},
    )


def artifact_path(
    *,
    surface: str,
    backend_or_summary: BackendChoice | str,
    artifact_dir: Path | None = None,
) -> Path:
    """Return the canonical Phase 7 artifact path for one ``(surface, backend)`` pair.

    Naming convention (locked in Phase 7A):

        ``<artifact_dir>/rust_backend_phase7_<surface>_<backend_or_summary>.json``

    ``surface`` should be a stable lowercase identifier such as
    ``parse_project_bytes`` or ``sase_ace_cold_open``. ``backend_or_summary``
    is normally a :class:`BackendChoice`; pass a custom string only when
    summarising across backends (Phase 7D) and prefer
    :attr:`BackendChoice.SUMMARY` for the default summary case so future
    tooling can still parse the name.

    Args:
        surface: Stable surface/operation identifier.
        backend_or_summary: Either a :class:`BackendChoice` or a
            summary tag (e.g. ``"ratio_summary"``).
        artifact_dir: Override the default artifact directory. Defaults
            to :data:`PHASE7_ARTIFACT_DIR`.
    """
    if artifact_dir is None:
        artifact_dir = PHASE7_ARTIFACT_DIR
    tag = (
        backend_or_summary.value
        if isinstance(backend_or_summary, BackendChoice)
        else backend_or_summary
    )
    if not surface or not tag:
        raise ValueError(
            f"Phase 7 artifact name requires non-empty surface and backend "
            f"(got surface={surface!r}, backend_or_summary={tag!r})."
        )
    return artifact_dir / f"{_ARTIFACT_PREFIX}_{surface}_{tag}.json"
