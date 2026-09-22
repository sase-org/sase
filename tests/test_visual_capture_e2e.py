"""End-to-end capture runs under pytest/pytest-xdist plus convergence gating."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tests._visual_capture_helpers import (
    _fixture,
    _prepare_repo,
    _session,
    make_png,
)
from tests.ace.tui.visual._visual_capture import hash_file_tree


_ROOT = Path(__file__).resolve().parents[1]


def _capture_pytest_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "PYTHONPATH",
        os.pathsep.join((str(_ROOT / "src"), str(_ROOT))),
    )
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)


def _write_capture_project(
    pytester: pytest.Pytester,
    *,
    red_hex: str,
    blue_hex: str,
) -> None:
    pytester.makeini("[pytest]\naddopts =\n")
    (pytester.path / "ace_png").mkdir()
    (pytester.path / "pager_png").mkdir()
    (pytester.path / "ace_png" / "existing.png").write_bytes(bytes.fromhex(red_hex))
    (pytester.path / "pager_png" / "existing.png").write_bytes(bytes.fromhex(red_hex))
    pytester.makeconftest(
        """
        from pathlib import Path
        import pytest
        from tests._visual_capture_plugin import capture_session_from_config
        from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

        def _fixture(request, snapshot_root):
            return AcePngSnapshotFixture(
                snapshot_root=snapshot_root,
                artifact_root=request.config.rootpath / "artifacts",
                update=False,
                node_id=request.node.nodeid,
                test_file=str(request.node.path),
                test_line=1,
                repo_root=request.config.rootpath,
                capture_session=capture_session_from_config(request.config),
            )

        @pytest.fixture
        def ace_png_visual(request):
            return _fixture(request, request.config.rootpath / "ace_png")

        @pytest.fixture
        def pager_png_visual(request):
            return _fixture(request, request.config.rootpath / "pager_png")
        """
    )
    pytester.makepyfile(
        test_ace=f"""
        RED = bytes.fromhex("{red_hex}")
        BLUE = bytes.fromhex("{blue_hex}")

        def test_ace_multi(ace_png_visual):
            ace_png_visual.assert_png("first", RED, source_svg="<svg>first</svg>")
            ace_png_visual.assert_png("second", BLUE, source_svg="<svg>second</svg>")
        """,
        test_pager=f"""
        RED = bytes.fromhex("{red_hex}")

        def test_pager_one(pager_png_visual):
            pager_png_visual.assert_png("first", RED, source_svg="<svg>pager</svg>")
        """,
    )


def _capture_args(
    capture_dir: Path,
    *,
    scope: str = "full",
    extra: tuple[str, ...] = (),
) -> list[str]:
    return [
        "-p",
        "no:randomly",
        "-p",
        "tests._visual_capture_plugin",
        "--sase-visual-capture-dir",
        str(capture_dir),
        "--sase-visual-capture-run-id",
        "run-xdist",
        "--sase-visual-capture-scope",
        scope,
        "--sase-visual-capture-ace-root",
        "ace_png",
        "--sase-visual-capture-pager-root",
        "pager_png",
        *extra,
    ]


def test_pytester_xdist_project_merges_worker_local_records(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("xdist")
    _capture_pytest_env(monkeypatch)
    red = make_png(1, 1, (255, 0, 0, 255))
    blue = make_png(1, 1, (0, 0, 255, 255))
    _write_capture_project(pytester, red_hex=red.hex(), blue_hex=blue.hex())
    capture_dir = pytester.path / "capture"
    ace_root = pytester.path / "ace_png"
    pager_root = pytester.path / "pager_png"
    before = (hash_file_tree(ace_root), hash_file_tree(pager_root))

    result = pytester.runpytest_subprocess(
        *_capture_args(
            capture_dir,
            extra=("-n", "2", "--dist=loadfile"),
        ),
        timeout=60,
    )

    result.assert_outcomes(passed=2)
    inventory = json.loads((capture_dir / "inventory.json").read_text())
    assert inventory["run_id"] == "run-xdist"
    captures = inventory["captures"]
    assert {item["snapshot_name"] for item in captures} == {"first", "second"}
    assert {item["root_identity"] for item in captures} == {"ace", "pager"}
    workers = {item["worker_id"] for item in inventory["worker_sessions"]}
    assert workers == {"gw0", "gw1"}
    assert list(capture_dir.glob("*.jsonl")) == []
    assert (hash_file_tree(ace_root), hash_file_tree(pager_root)) == before
    assert inventory["full_inventory"] is True
    assert inventory["pruning_allowed"] is True


def test_pytester_ordinary_failure_still_fails_and_keeps_goldens(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    _capture_pytest_env(monkeypatch)
    red = make_png(1, 1, (255, 0, 0, 255))
    pytester.makeini("[pytest]\naddopts =\n")
    (pytester.path / "ace_png").mkdir()
    (pytester.path / "pager_png").mkdir()
    (pytester.path / "ace_png" / "existing.png").write_bytes(red)
    before = hash_file_tree(pytester.path / "ace_png")
    pytester.makeconftest(
        """
        from pathlib import Path
        import pytest
        from tests._visual_capture_plugin import capture_session_from_config
        from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

        @pytest.fixture
        def ace_png_visual(request):
            return AcePngSnapshotFixture(
                snapshot_root=request.config.rootpath / "ace_png",
                artifact_root=request.config.rootpath / "artifacts",
                update=False,
                node_id=request.node.nodeid,
                repo_root=request.config.rootpath,
                capture_session=capture_session_from_config(request.config),
            )
        """
    )
    pytester.makepyfile(
        f"""
        RED = bytes.fromhex("{red.hex()}")

        def test_captures_then_fails(ace_png_visual):
            ace_png_visual.assert_png("ok", RED)
            raise AssertionError("ordinary failure")
        """
    )
    capture_dir = pytester.path / "capture"

    result = pytester.runpytest_subprocess(
        *_capture_args(capture_dir, scope="targeted"),
        timeout=60,
    )

    result.assert_outcomes(failed=1)
    inventory = json.loads((capture_dir / "inventory.json").read_text())
    assert inventory["captures"]
    assert inventory["complete"] is False
    assert hash_file_tree(pytester.path / "ace_png") == before


def test_assert_page_png_still_proves_convergence_before_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.ace.tui.visual import png_diff

    _, roots = _prepare_repo(tmp_path)
    session = _session(tmp_path, roots=roots)
    fixture = _fixture(tmp_path, roots.ace, session)
    png = make_png(1, 1)
    monkeypatch.setattr(png_diff, "render_svg_to_png", lambda svg: png)
    calls: list[object] = []
    monkeypatch.setattr(
        "tests.ace.tui.visual._ace_png_snapshot_waits.assert_visual_frame_converged",
        lambda captured: calls.append(captured),
    )

    class _AcePage:
        def export_svg(self, title: str | None = None, simplify: bool = True) -> str:
            del title, simplify
            return "<svg />"

    monkeypatch.setattr(png_diff, "AcePage", _AcePage)
    ace_page = _AcePage()

    fixture.assert_page_png(ace_page, "converged")

    assert calls == [ace_page]
    assert session.captures[0].snapshot_name == "converged"
