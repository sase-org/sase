"""Tests for ``tools/refresh_shard_timings``.

The tool folds host-local per-file recordings into the committed
``tests/shard_timings.json`` table, and is also the comparison the Full CI
artifact ratchet runs. These tests pin that contract without touching the
committed table.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

import pytest

from tests._test_selection_timings import write_timings
from tests._test_shards import SHARD_TIMINGS_SCHEMA


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "refresh_shard_timings"


def _load_tool() -> ModuleType:
    loader = SourceFileLoader("refresh_shard_timings_tool", str(SCRIPT))
    spec = importlib.util.spec_from_file_location(
        "refresh_shard_timings_tool",
        SCRIPT,
        loader=loader,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def tool() -> ModuleType:
    return _load_tool()


def _write_test_files(root: Path, names: list[str]) -> None:
    tests_dir = root / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# test\n", encoding="utf-8")


def _payload(
    *,
    durations: dict[str, float],
    default_duration: float = 0.2,
    generated_at: str = "2026-08-28T00:00:00+00:00",
    measured_file_count: int | None = None,
) -> dict[str, object]:
    return {
        "schema": SHARD_TIMINGS_SCHEMA,
        "generated_at": generated_at,
        "host": "ci",
        "measured_file_count": (
            len(durations) if measured_file_count is None else measured_file_count
        ),
        "default_duration": default_duration,
        "durations": durations,
    }


def test_build_shard_timings_retains_the_slowest_files_and_means_the_rest(
    tool: ModuleType, tmp_path: Path
) -> None:
    files = [f"tests/test_{index:02d}.py" for index in range(6)]
    _write_test_files(tmp_path, files)
    removed_file = "tests/deleted.py"
    durations = {
        path: float(20 - index) for index, path in enumerate([removed_file, *files])
    }
    write_timings(
        tmp_path / "recordings",
        durations,
        mode="fast",
        worker_count=2,
        host="ci",
        pid=1,
    )

    payload = tool.build_shard_timings(
        limit=3,
        source_directory=tmp_path / "recordings",
        host="ci",
        repo_root=tmp_path,
        now=datetime(2026, 8, 28, tzinfo=UTC),
    )

    assert payload["schema"] == SHARD_TIMINGS_SCHEMA
    assert payload["host"] == "ci"
    assert payload["measured_file_count"] == 6
    assert set(payload["durations"]) == set(files[:3])
    assert removed_file not in payload["durations"]
    omitted_mean = sum(durations[path] for path in files[3:]) / 3
    assert payload["default_duration"] == round(omitted_mean, 4)


def test_build_shard_timings_refuses_an_empty_source(
    tool: ModuleType, tmp_path: Path
) -> None:
    with pytest.raises(tool.ShardTimingsRefreshError, match="no recorded timing data"):
        tool.build_shard_timings(source_directory=tmp_path / "missing", host="ci")


def test_check_content_ignores_generated_at_and_host(tool: ModuleType) -> None:
    durations = {"tests/test_a.py": 4.0}
    committed = _payload(durations=durations, generated_at="2026-01-01T00:00:00+00:00")
    proposed = _payload(
        durations=durations,
        generated_at="2026-08-28T00:00:00+00:00",
    )
    proposed["host"] = "other"
    assert tool.check_content(proposed, committed=committed) == 0

    proposed["durations"] = {"tests/test_a.py": 5.0}
    assert tool.check_content(proposed, committed=committed) == 1


def test_check_assignment_ignores_duration_jitter_that_keeps_the_split(
    tool: ModuleType, tmp_path: Path
) -> None:
    files = [f"tests/test_{index:02d}.py" for index in range(4)]
    _write_test_files(tmp_path, files)
    committed = _payload(
        durations={files[0]: 100.0, files[1]: 50.0, files[2]: 10.0, files[3]: 10.0}
    )
    proposed = _payload(
        durations={files[0]: 110.0, files[1]: 55.0, files[2]: 11.0, files[3]: 9.0}
    )
    assert (
        tool.check_assignment(proposed, 2, committed=committed, repo_root=tmp_path) == 0
    )

    # Make the second file the unique longest so LPT sends it to shard 1 first.
    proposed["durations"] = {
        files[0]: 10.0,
        files[1]: 100.0,
        files[2]: 10.0,
        files[3]: 10.0,
    }
    assert (
        tool.check_assignment(proposed, 2, committed=committed, repo_root=tmp_path) == 1
    )


def test_check_max_age_uses_generated_at(
    tool: ModuleType,
) -> None:
    now = datetime(2026, 8, 28, tzinfo=UTC)
    fresh = _payload(durations={"tests/test_a.py": 1.0}, generated_at=now.isoformat())
    assert tool.check_max_age(14, committed=fresh, now=now) == 0

    stale_stamp = (now - timedelta(days=15)).isoformat()
    stale = _payload(durations={"tests/test_a.py": 1.0}, generated_at=stale_stamp)
    assert tool.check_max_age(14, committed=stale, now=now) == 1

    missing = _payload(durations={"tests/test_a.py": 1.0})
    missing.pop("generated_at")
    assert tool.check_max_age(14, committed=missing, now=now) == 1


def test_main_writes_from_payload_to_output(
    tool: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "incoming.json"
    source.write_text(json.dumps(_payload(durations={"tests/test_a.py": 3.0})))
    output = tmp_path / "out" / "shard_timings.json"

    assert tool.main(["--from-payload", str(source), "--output", str(output)]) == 0
    written = json.loads(output.read_text(encoding="utf-8"))
    assert written["durations"] == {"tests/test_a.py": 3.0}
    assert "wrote 1 of" in capsys.readouterr().out


def test_main_check_assignment_from_payload(
    tool: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = [f"tests/test_{index:02d}.py" for index in range(4)]
    _write_test_files(tmp_path, files)
    committed_payload = _payload(
        durations={files[0]: 100.0, files[1]: 50.0, files[2]: 10.0, files[3]: 10.0}
    )
    committed_path = tmp_path / "tests" / "shard_timings.json"
    committed_path.write_text(json.dumps(committed_payload), encoding="utf-8")
    proposed = tmp_path / "proposed.json"
    proposed.write_text(
        json.dumps(
            _payload(
                durations={
                    files[0]: 110.0,
                    files[1]: 55.0,
                    files[2]: 11.0,
                    files[3]: 9.0,
                }
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(tool, "TIMINGS_PATH", committed_path)
    monkeypatch.setattr(tool, "REPO_ROOT", tmp_path)

    assert (
        tool.main(
            [
                "--from-payload",
                str(proposed),
                "--check",
                "--assignment",
                "--shards",
                "2",
            ]
        )
        == 0
    )


def test_main_rejects_assignment_without_check(tool: ModuleType) -> None:
    with pytest.raises(SystemExit):
        tool.main(["--assignment"])
