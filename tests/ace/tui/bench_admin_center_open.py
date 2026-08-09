"""Admin Center ``#`` dispatch-to-home-paint benchmark.

Run explicitly with::

    pytest -s -m slow tests/ace/tui/bench_admin_center_open.py

The benchmark deliberately has no wall-clock pass/fail threshold. Its hard
assertions are structural: the generic path mounts no working pane and its
result is independent of empty versus populated config/project fixtures.
"""

from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.config import core as config_core
from sase.core.paths import sase_projects_dir

pytestmark = pytest.mark.slow

_SAMPLES = 14
_WARMUP_SAMPLES = 2


def _populate_fixture() -> None:
    config_core.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    (config_core.CONFIG_DIR / "sase.yml").write_text("# benchmark base\n")
    for index in range(100):
        (config_core.CONFIG_DIR / f"sase_bench_{index:03d}.yml").write_text(
            f"# benchmark overlay {index}\n"
        )

    projects_root = sase_projects_dir()
    for index in range(100):
        project_id = f"bench_{index:03d}"
        project_dir = projects_root / project_id
        project_dir.mkdir(parents=True, exist_ok=True)
        (project_dir / f"{project_id}.sase").write_text(
            f"PROJECT_NAME: {project_id}\nPROJECT_STATE: enabled\n"
        )


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = max(0, round(percentile * (len(ordered) - 1)))
    return ordered[index]


@pytest.mark.parametrize("fixture_name", ["empty", "populated"])
async def test_bench_admin_center_home_first_paint(
    fixture_name: str,
    tmp_path: Path,
) -> None:
    del tmp_path  # Ensures pytest has established its isolated per-test home.
    if fixture_name == "populated":
        _populate_fixture()

    samples: list[float] = []
    async with AcePage(query="!!!", patches=[]) as page:
        for _index in range(_SAMPLES):
            started = time.perf_counter()
            await page.press("number_sign")
            await page.expect_modal("ConfigCenterModal")
            modal = page.app.screen
            assert isinstance(modal, ConfigCenterModal)
            await page.wait_for(
                lambda _state, current_modal=modal: bool(
                    current_modal.query("#admin-center-home-card")
                )
            )
            await page.pause()
            samples.append((time.perf_counter() - started) * 1000.0)

            assert modal._active_tab is None
            assert modal._panes == {}
            await page.press("escape")
            await page.expect_no_modal()

    measured = samples[_WARMUP_SAMPLES:]
    p50 = statistics.median(measured)
    p95 = _percentile(measured, 0.95)
    maximum = max(measured)
    print(
        f"Admin Center home ({fixture_name}): "
        f"n={len(measured)} p50={p50:.2f}ms p95={p95:.2f}ms max={maximum:.2f}ms",
        file=sys.stderr,
    )
