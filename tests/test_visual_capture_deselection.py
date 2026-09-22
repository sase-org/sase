"""Marker-based deselection must not block full inventories for goldens-less nodes.

The capture plugin ignores deselected items that carry no ``visual`` marker
and request neither PNG fixture: such items cannot produce a golden, so their
exclusion is expected, not incomplete inventory. Deselected items that are
marked visual or use a PNG fixture are still recorded, so a mis-marked
snapshot test blocks pruning instead of getting its golden deleted.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from tests._visual_capture_helpers import _session
from tests._visual_capture_plugin import VisualCapturePlugin


class _StubItem:
    """Minimal stand-in for a collected pytest item."""

    def __init__(
        self,
        nodeid: str,
        *,
        marked_visual: bool = False,
        fixturenames: tuple[str, ...] = (),
    ) -> None:
        self.nodeid = nodeid
        self._marked_visual = marked_visual
        self.fixturenames = list(fixturenames)

    def get_closest_marker(self, name: str) -> Any:
        if name == "visual" and self._marked_visual:
            return SimpleNamespace(name="visual")
        return None


def _plugin(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> VisualCapturePlugin:
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    config = SimpleNamespace(option=SimpleNamespace(numprocesses=None))
    return VisualCapturePlugin(
        _session(tmp_path),
        config=config,  # type: ignore[arg-type]
        requested_scope="targeted",
    )


def test_unmarked_fixture_free_deselection_is_ignored(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin = _plugin(tmp_path, monkeypatch)
    plugin.pytest_deselected(
        [_StubItem("tests/ace/tui/visual/test_startup.py::test_plain")],
    )
    assert plugin._deselected == []


def test_marked_deselection_is_still_recorded(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin = _plugin(tmp_path, monkeypatch)
    plugin.pytest_deselected(
        [_StubItem("tests/ace/tui/visual/test_a.py::test_a", marked_visual=True)],
    )
    assert plugin._deselected == ["tests/ace/tui/visual/test_a.py::test_a"]


@pytest.mark.parametrize("fixture", ["ace_png_visual", "pager_png_visual"])
def test_png_fixture_deselection_is_still_recorded(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch, fixture: str
) -> None:
    plugin = _plugin(tmp_path, monkeypatch)
    plugin.pytest_deselected(
        [_StubItem("tests/ace/tui/visual/test_a.py::test_a", fixturenames=(fixture,))],
    )
    assert plugin._deselected == ["tests/ace/tui/visual/test_a.py::test_a"]


def test_mixed_deselection_records_only_visual_nodes(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin = _plugin(tmp_path, monkeypatch)
    plugin.pytest_deselected(
        [
            _StubItem("tests/ace/tui/visual/test_startup.py::test_plain"),
            _StubItem("tests/ace/tui/visual/test_a.py::test_a", marked_visual=True),
            _StubItem(
                "tests/pager/visual/test_b.py::test_b",
                fixturenames=("pager_png_visual",),
            ),
        ],
    )
    assert plugin._deselected == [
        "tests/ace/tui/visual/test_a.py::test_a",
        "tests/pager/visual/test_b.py::test_b",
    ]


def test_unmarked_deselection_leaves_no_inventory_blocker(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.test_visual_capture_e2e import _capture_args, _capture_pytest_env

    _capture_pytest_env(monkeypatch)
    pytester.makeini("[pytest]\naddopts =\n")
    pytester.makepyfile(
        test_marked=(
            "import pytest\n"
            "pytestmark = pytest.mark.visual\n"
            "def test_marked_ok():\n"
            "    assert True\n"
        ),
        test_plain=("def test_plain_ok():\n    assert True\n"),
    )
    capture_dir = pytester.path / "capture"

    result = pytester.runpytest_subprocess(
        *_capture_args(capture_dir, scope="targeted", extra=("-m", "visual")),
        timeout=60,
    )

    result.assert_outcomes(passed=1)
    inventory = json.loads((capture_dir / "inventory.json").read_text())
    assert inventory["deselected_visual_node_ids"] == []
    assert not [
        reason
        for reason in inventory["reasons"]
        if reason.startswith("deselected_visual_node:")
    ]
