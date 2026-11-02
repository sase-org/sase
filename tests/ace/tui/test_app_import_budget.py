"""Import-budget guard for the TUI startup-critical app module."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests._tui_import_fixtures import (
    MONOLITH_FILES,
    SPLIT_FILES,
    footprint,
    implementation,
    measure_package,
    with_eager_import,
    write_files,
)


_MAX_ELAPSED_SECONDS = 5.0
# Ratchet policy: the guard measures the normalized source footprint of the
# first-party modules (``sase`` and ``sase.*``) that ``import sase.ace.tui.app``
# loads in a fresh interpreter: the UTF-8 bytes of significant Python tokens in
# their unique source files, excluding import statements, docstrings, literal
# ``__all__`` lists, comments, and whitespace (``tools/_tui_import_footprint.py``,
# metric version 1). A mechanical module split (a facade plus helper files
# holding the same code) leaves it unchanged, so split/re-export boilerplate
# does not consume the budget, while additional imported implementation does.
# The old strict first-party module-count cap (2861) failed on every such
# split (sase-1ic).
#
# Calibration (Python 3.14.7, metric version 1): the clean tree at 078e3da1d6
# measured 12,158,388 bytes, and the cap is that baseline plus a fixed
# 4,096-byte allowance with a strict ``<``. The allowance is an absolute
# number, not a percentage of the ~23 MB raw source tree: it covers the small
# source changes that accompany real splits and, like the previous guard's
# module headroom, admits small code growth. Replays under this same cap,
# measured with the same helper over isolated ``git archive`` source snapshots
# and the same installed dependencies:
#   eef22a0124^ -> eef22a0124  (filesystem enrichment split)
#     2,860 -> 2,863 modules; 12,160,347 -> 12,160,635 bytes (+288)
#   bffbc8effd^ -> bffbc8effd  (artifact loader split)
#     2,855 -> 2,860 modules; 12,153,966 -> 12,154,025 bytes (+59)
#   362fcb2e7f^ -> 362fcb2e7f  (prompt artifact staging split)
#     2,856 -> 2,860 modules; 12,138,357 -> 12,138,426 bytes (+69)
#   d3d26a5b55 (the tree that failed the old cap) measures 2,863 modules and
#   12,160,635 bytes, 1,849 under the cap.
#
# Raising the cap requires a named first-party source that is genuinely
# needed on the first-paint path with deferral considered and impossible: the
# comment must name that source and its commit, and the raise covers only the
# attributed bytes. Never redefine success as ``<=``, never recalibrate the
# baseline automatically from HEAD or the merge-base, never adjust the cap
# inside a test, and never grow the allowance to absorb unattributed drift or a
# failing replay: attribute the discrepancy. Third-party and stdlib growth do
# not fail this cap, and the deferred-module list below stays absolute
# regardless of size. When this guard fails, attribute the growth with
# ``tools/tui_import_closure --diff $(git merge-base HEAD origin/master)``
# (it lists the sources behind a footprint change, including edits inside
# modules already imported) and defer the new edges with use-site or
# ``TYPE_CHECKING`` imports.
_FOOTPRINT_METRIC_VERSION = 1
_FOOTPRINT_BASELINE_BYTES = 12_158_388
_FOOTPRINT_ALLOWANCE_BYTES = 4_096
_MAX_SASE_SOURCE_FOOTPRINT_BYTES = (
    _FOOTPRINT_BASELINE_BYTES + _FOOTPRINT_ALLOWANCE_BYTES
)
# Loose total-module bound: measured 3549 on 2026-10-29 plus 10%, strict
# ``<``. Only a large dependency regression trips this.
_MAX_TOTAL_MODULE_COUNT = 3904
_DEFERRED_MODULES = (
    "sase.agent.multi_prompt",
    "sase.agent.multi_prompt_launcher",
    "sase.agent.scope_sweep",
    "sase.artifact_cli.create",
    "sase.artifact_links.projection._agent_created_epic",
    "sase.core.wait_dependency_resolution",
    "sase.core.wait_epic_follow_view",
    "sase.finalizers.commit_memory_guard",
    "sase.service.status",
    "sase.service.control",
    "sase.dev_update",
    "sase.dev_update.execute",
    "sase.update_progress",
    "sase.agents_sync.git",
    "sase.agents_sync.git_sync",
    "sase.agents_sync.git_sync_transaction",
    "sase.agents_sync.publication",
    "sase.agents_sync.publication_cleanup",
)


def _assert_footprint_budget(
    measurement: footprint.ImportMeasurement,
    *,
    cap: int = _MAX_SASE_SOURCE_FOOTPRINT_BYTES,
) -> None:
    assert measurement.footprint_bytes < cap, (
        f"TUI app import loads {measurement.footprint_bytes:,} normalized source "
        f"bytes from {measurement.first_party_count} sase.* modules against the "
        f"{cap:,} cap; attribute the growth with `tools/tui_import_closure --diff "
        f"$(git merge-base HEAD origin/master)` and defer the new edges"
    )


def _assert_total_module_budget(
    module_count: int, *, cap: int = _MAX_TOTAL_MODULE_COUNT
) -> None:
    assert module_count < cap, (
        f"TUI app import loads {module_count} total modules against the loose {cap} cap"
    )


def _assert_no_deferred_modules(deferred_modules: tuple[str, ...]) -> None:
    assert deferred_modules == (), (
        f"TUI startup eagerly imports deferred modules: {list(deferred_modules)!r}"
    )


def _synthetic(footprint_bytes: int) -> footprint.ImportMeasurement:
    """A measurement for strict-comparison checks only (no import involved)."""
    return footprint.ImportMeasurement(
        elapsed_seconds=0.0,
        module_count=0,
        first_party_modules=("sase",),
        deferred_modules=(),
        footprint=footprint.SourceFootprint(
            total_bytes=footprint_bytes, module_bytes={"sase": footprint_bytes}
        ),
    )


def _footprint_cache(config: pytest.Config) -> footprint.FootprintCache:
    """Per-checkout content-addressed cache; 10-20s cold, ~1s warm for the app."""
    cache = getattr(config, "cache", None)
    if cache is None:
        return footprint.FootprintCache()
    return footprint.FootprintCache(Path(str(cache.mkdir("sase_tui_import_footprint"))))


def _measure_tui_app_import(
    cache: footprint.FootprintCache,
) -> footprint.ImportMeasurement:
    measurement = footprint.measure_import(
        deferred_modules=_DEFERRED_MODULES, cache=cache
    )
    _assert_no_deferred_modules(measurement.deferred_modules)
    _assert_footprint_budget(measurement)
    _assert_total_module_budget(measurement.module_count)
    return measurement


def test_footprint_cap_is_the_measured_baseline_plus_the_fixed_allowance() -> None:
    assert footprint.FOOTPRINT_METRIC_VERSION == _FOOTPRINT_METRIC_VERSION
    assert _FOOTPRINT_ALLOWANCE_BYTES == 4_096
    assert _MAX_SASE_SOURCE_FOOTPRINT_BYTES == 12_162_484


def test_first_party_membership_is_the_sase_package_and_submodules() -> None:
    names = [
        "sase",
        "sase.ace.tui.app",
        "sase_core",
        "sase_core_rs",
        "textual",
        "sys",
        "json",
    ]
    assert [name for name in names if footprint.is_first_party_module(name)] == [
        "sase",
        "sase.ace.tui.app",
    ]


def test_footprint_cap_uses_strict_less_than() -> None:
    _assert_footprint_budget(_synthetic(_MAX_SASE_SOURCE_FOOTPRINT_BYTES - 1))
    with pytest.raises(AssertionError, match="against the 12,162,484 cap"):
        _assert_footprint_budget(_synthetic(_MAX_SASE_SOURCE_FOOTPRINT_BYTES))


def test_equal_footprint_fails_a_real_measurement_cap(tmp_path: Path) -> None:
    write_files(tmp_path, MONOLITH_FILES)
    measurement = measure_package(tmp_path)
    _assert_footprint_budget(measurement, cap=measurement.footprint_bytes + 1)
    with pytest.raises(AssertionError, match=r"against the \d"):
        _assert_footprint_budget(measurement, cap=measurement.footprint_bytes)


def test_mechanical_split_keeps_the_footprint_under_an_unchanged_cap(
    tmp_path: Path,
) -> None:
    """Facade + helper files with repeated boilerplate cost nothing extra."""
    monolith_root = tmp_path / "monolith"
    split_root = tmp_path / "split"
    write_files(monolith_root, MONOLITH_FILES)
    write_files(split_root, SPLIT_FILES)
    before = measure_package(monolith_root)
    after = measure_package(split_root)

    assert after.first_party_count == before.first_party_count + 2
    assert after.footprint_bytes == before.footprint_bytes > 0
    # A cap with room for exactly zero growth: the split must still pass it.
    _assert_footprint_budget(before, cap=before.footprint_bytes + 1)
    _assert_footprint_budget(after, cap=before.footprint_bytes + 1)


def test_new_eager_source_import_trips_an_unchanged_fixture_cap(
    tmp_path: Path,
) -> None:
    baseline_root = tmp_path / "baseline"
    grown_root = tmp_path / "grown"
    write_files(baseline_root, MONOLITH_FILES)
    extra = {"budgetpkg/extra.py": "def extra() -> int:\n    return 41 + 1\n"}
    write_files(grown_root, {**with_eager_import(MONOLITH_FILES, "extra"), **extra})
    baseline = measure_package(baseline_root)
    grown = measure_package(grown_root)

    # The unrelated module's real source is counted, token by token.
    added = len("defextra()->int:return41+1")
    assert grown.footprint.module_bytes["budgetpkg.extra"] == added
    assert grown.footprint_bytes == baseline.footprint_bytes + added
    cap = baseline.footprint_bytes + 1
    _assert_footprint_budget(baseline, cap=cap)
    with pytest.raises(AssertionError, match=r"against the \d"):
        _assert_footprint_budget(grown, cap=cap)


def test_growth_beyond_the_production_allowance_trips_the_production_allowance(
    tmp_path: Path,
) -> None:
    """Control: the 4,096-byte allowance cannot turn a large growth green."""
    baseline_root = tmp_path / "baseline"
    grown_root = tmp_path / "grown"
    write_files(baseline_root, MONOLITH_FILES)
    big = {"budgetpkg/extra.py": implementation(150)}
    write_files(grown_root, {**with_eager_import(MONOLITH_FILES, "extra"), **big})
    baseline = measure_package(baseline_root)
    grown = measure_package(grown_root)
    cap = baseline.footprint_bytes + _FOOTPRINT_ALLOWANCE_BYTES

    growth = grown.footprint_bytes - baseline.footprint_bytes
    assert growth > _FOOTPRINT_ALLOWANCE_BYTES
    _assert_footprint_budget(baseline, cap=cap)
    with pytest.raises(AssertionError, match=r"against the \d"):
        _assert_footprint_budget(grown, cap=cap)


def test_small_growth_stays_inside_the_allowance(tmp_path: Path) -> None:
    """The allowance admits small code growth, by design."""
    baseline_root = tmp_path / "baseline"
    grown_root = tmp_path / "grown"
    write_files(baseline_root, MONOLITH_FILES)
    small = {"budgetpkg/extra.py": implementation(10)}
    write_files(grown_root, {**with_eager_import(MONOLITH_FILES, "extra"), **small})
    baseline = measure_package(baseline_root)
    grown = measure_package(grown_root)

    growth = grown.footprint_bytes - baseline.footprint_bytes
    assert 0 < growth < _FOOTPRINT_ALLOWANCE_BYTES
    _assert_footprint_budget(
        grown, cap=baseline.footprint_bytes + _FOOTPRINT_ALLOWANCE_BYTES
    )


def test_previously_deferred_module_fails_regardless_of_size(tmp_path: Path) -> None:
    deferred = ("budgetpkg.heavy",)
    heavy = {"budgetpkg/heavy.py": "VALUE = 1\n"}
    lazy_app = MONOLITH_FILES["budgetpkg/app.py"] + (
        "\n\ndef lazy() -> int:\n    from . import heavy\n\n    return heavy.VALUE\n"
    )
    lazy_root = tmp_path / "lazy"
    eager_root = tmp_path / "eager"
    write_files(lazy_root, {**MONOLITH_FILES, "budgetpkg/app.py": lazy_app, **heavy})
    write_files(eager_root, {**with_eager_import(MONOLITH_FILES, "heavy"), **heavy})

    lazy = measure_package(lazy_root, deferred_modules=deferred)
    eager = measure_package(eager_root, deferred_modules=deferred)

    _assert_no_deferred_modules(lazy.deferred_modules)
    assert "budgetpkg.heavy" not in lazy.first_party_modules
    # The eager variant is tiny and well within the footprint allowance ...
    assert eager.footprint_bytes < lazy.footprint_bytes + _FOOTPRINT_ALLOWANCE_BYTES
    _assert_footprint_budget(
        eager, cap=lazy.footprint_bytes + _FOOTPRINT_ALLOWANCE_BYTES
    )
    # ... yet still fails, naming the deferred module.
    with pytest.raises(
        AssertionError, match=r"deferred modules: \['budgetpkg.heavy'\]"
    ):
        _assert_no_deferred_modules(eager.deferred_modules)


def test_third_party_growth_stays_outside_the_first_party_footprint(
    tmp_path: Path,
) -> None:
    baseline_root = tmp_path / "baseline"
    grown_root = tmp_path / "grown"
    write_files(baseline_root, MONOLITH_FILES)
    vendor = {
        "vendorpkg/__init__.py": implementation(200, prefix="vendor"),
        "vendorpkg/more.py": implementation(200, prefix="more"),
    }
    grown_app = MONOLITH_FILES["budgetpkg/app.py"] + "\nimport vendorpkg.more\n"
    write_files(grown_root, {**MONOLITH_FILES, "budgetpkg/app.py": grown_app, **vendor})
    baseline = measure_package(baseline_root)
    grown = measure_package(grown_root)

    assert grown.module_count == baseline.module_count + 2
    assert grown.first_party_modules == baseline.first_party_modules
    assert grown.footprint_bytes == baseline.footprint_bytes
    _assert_footprint_budget(grown, cap=baseline.footprint_bytes + 1)


def test_tui_app_import_stays_under_startup_budget(
    request: pytest.FixtureRequest,
) -> None:
    """Importing the app should not pull known heavy deferred profile edges."""

    cache = _footprint_cache(request.config)
    last_elapsed = 0.0
    last_footprint = 0
    last_count = 0
    for _ in range(2):
        measurement = _measure_tui_app_import(cache)
        last_elapsed = measurement.elapsed_seconds
        last_footprint = measurement.footprint_bytes
        last_count = measurement.module_count
        if last_elapsed < _MAX_ELAPSED_SECONDS:
            return

    raise AssertionError(
        f"TUI app import stayed over the {_MAX_ELAPSED_SECONDS}s CPU budget "
        f"after 2 attempts (elapsed={last_elapsed!r}, "
        f"footprint_bytes={last_footprint!r}, module_count={last_count!r})"
    )
