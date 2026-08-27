"""Unit tests for the master gate's whole-suite pytest sharding.

Partition/disjointness and determinism of the assignment algorithm, strict
`SASE_TEST_SHARD` spec parsing, the discovery walk's hidden/`__pycache__`
skip, and contracts pinning the *committed* `tests/shard_timings.json`
against this repository's live state -- so a table that has drifted too far
from reality fails loudly, naming the fix, rather than quietly degrading
shard balance forever.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

import pytest

from tests._test_shards import (
    DEFAULT_TIMINGS_PATH,
    FALLBACK_DURATION,
    ShardError,
    ShardSpec,
    ShardTimingTable,
    assign_shards,
    discover_test_files,
    format_shard_summary,
    load_shard_timings,
    parse_shard_spec,
    shard_files,
)


REPO_ROOT = Path(__file__).resolve().parent.parent


def _table(**durations: float) -> ShardTimingTable:
    return ShardTimingTable(default_duration=1.0, durations=dict(durations))


# --------------------------------------------------------------------------
# Spec parsing
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1/1", ShardSpec(index=1, count=1)),
        ("1/6", ShardSpec(index=1, count=6)),
        ("6/6", ShardSpec(index=6, count=6)),
        ("3/6", ShardSpec(index=3, count=6)),
    ],
)
def test_parse_shard_spec_accepts_1_based_index_and_count(
    value: str, expected: ShardSpec
) -> None:
    assert parse_shard_spec(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "",
        "1",
        "1/6/2",
        "0/6",
        "7/6",
        "1/0",
        "-1/6",
        "1/-6",
        "a/6",
        "1/a",
        "1.0/6",
        " 1/6",
        "1/6 ",
    ],
)
def test_parse_shard_spec_rejects_malformed_or_out_of_range_specs(value: str) -> None:
    with pytest.raises(ShardError, match="SASE_TEST_SHARD"):
        parse_shard_spec(value)


# --------------------------------------------------------------------------
# Discovery
# --------------------------------------------------------------------------


def test_discover_test_files_skips_hidden_components_and_pycache(
    tmp_path: Path,
) -> None:
    tests_dir = tmp_path / "tests"
    (tests_dir / "sub").mkdir(parents=True)
    (tests_dir / "sub" / "test_visible.py").write_text("", encoding="utf-8")
    (tests_dir / "sub" / "__pycache__").mkdir()
    (tests_dir / "sub" / "__pycache__" / "test_cached.py").write_text(
        "", encoding="utf-8"
    )
    (tests_dir / ".hidden").mkdir()
    (tests_dir / ".hidden" / "test_hidden.py").write_text("", encoding="utf-8")
    (tests_dir / "sub" / "not_a_test.py").write_text("", encoding="utf-8")

    assert discover_test_files(tmp_path) == ["tests/sub/test_visible.py"]


def test_discovery_matches_pytest_python_files_convention() -> None:
    """Pin the assumption that ``test_*.py`` is the only convention in use.

    ``pyproject.toml`` does not override pytest's default ``python_files``,
    which also matches ``*_test.py``. This walk only looks for the
    ``test_*.py`` half of that default, so it stays complete only as long as
    no file in ``tests/`` uses the other suffix convention.
    """
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'testpaths = ["tests"]' in pyproject
    assert "python_files" not in pyproject

    suffix_style = list((REPO_ROOT / "tests").rglob("*_test.py"))
    assert suffix_style == []

    discovered = discover_test_files(REPO_ROOT)
    assert discovered
    assert discovered == sorted(discovered)
    for path in discovered:
        assert path.startswith("tests/")
        assert path.endswith(".py")
        assert Path(path).name.startswith("test_")
        assert (REPO_ROOT / path).is_file()


# --------------------------------------------------------------------------
# Assignment
# --------------------------------------------------------------------------


def test_assign_shards_partitions_every_file_exactly_once() -> None:
    files = [f"tests/test_{index:03d}.py" for index in range(37)]
    table = _table(**{files[0]: 40.0, files[1]: 25.0, files[2]: 10.0})

    for count in (1, 2, 3, 7, 37):
        bins = assign_shards(files, count, table)
        assert len(bins) == count
        seen: list[str] = []
        for shard_bin in bins:
            assert shard_bin.files, "LPT must never leave a bin empty"
            seen.extend(shard_bin.files)
        assert sorted(seen) == sorted(files)
        assert len(seen) == len(files)


def test_assign_shards_is_deterministic_regardless_of_input_order() -> None:
    files = [f"tests/test_{index:03d}.py" for index in range(41)]
    table = _table(**{path: float(hash(path) % 97) for path in files})

    baseline = assign_shards(files, 6, table)
    shuffled = list(files)
    random.Random(0).shuffle(shuffled)
    reshuffled = assign_shards(shuffled, 6, table)

    assert [shard_bin.files for shard_bin in baseline] == [
        shard_bin.files for shard_bin in reshuffled
    ]


def test_assign_shards_breaks_exact_ties_deterministically() -> None:
    """Every file the table has never seen costs the same, exercising the tiebreak."""
    files = [f"tests/test_tied_{index:03d}.py" for index in range(11)]
    table = ShardTimingTable()

    first = assign_shards(files, 4, table)
    second = assign_shards(list(reversed(files)), 4, table)

    assert [shard_bin.files for shard_bin in first] == [
        shard_bin.files for shard_bin in second
    ]


@pytest.mark.parametrize(
    ("files", "count"),
    [
        ([], 1),
        (["tests/test_a.py", "tests/test_b.py"], 3),
        (["tests/test_a.py"], 2),
    ],
)
def test_assign_shards_refuses_more_shards_than_files(
    files: list[str], count: int
) -> None:
    with pytest.raises(ShardError, match="more shards than files"):
        assign_shards(files, count, ShardTimingTable())


def test_assign_shards_rejects_a_non_positive_count() -> None:
    with pytest.raises(ShardError):
        assign_shards(["tests/test_a.py"], 0, ShardTimingTable())


def test_shard_files_returns_the_one_bin_the_spec_names() -> None:
    files = [f"tests/test_{index:03d}.py" for index in range(9)]
    table = ShardTimingTable()

    whole = assign_shards(files, 3, table)
    for index in range(1, 4):
        assert (
            shard_files(files, ShardSpec(index=index, count=3), table)
            == whole[index - 1]
        )


def test_unknown_files_fall_back_through_table_then_default_then_fallback() -> None:
    table = ShardTimingTable(default_duration=5.0, durations={"tests/test_a.py": 2.0})
    assert table.estimate("tests/test_a.py") == 2.0
    assert table.estimate("tests/test_unknown.py") == 5.0
    assert ShardTimingTable().estimate("tests/test_unknown.py") == FALLBACK_DURATION


def test_format_shard_summary_is_concise_and_names_the_shard() -> None:
    shard_bin = shard_files(
        [f"tests/test_{index:03d}.py" for index in range(4)],
        ShardSpec(index=2, count=2),
        ShardTimingTable(),
    )
    line = format_shard_summary(ShardSpec(index=2, count=2), shard_bin, total_files=4)
    assert line.startswith("shard 2/2: ")
    assert f"{len(shard_bin.files)} of 4" in line


# --------------------------------------------------------------------------
# The committed table
# --------------------------------------------------------------------------


def _load_committed_payload() -> dict[str, Any]:
    return json.loads((REPO_ROOT / DEFAULT_TIMINGS_PATH).read_text(encoding="utf-8"))


def test_committed_table_loads_and_is_nonempty() -> None:
    table = load_shard_timings(REPO_ROOT / DEFAULT_TIMINGS_PATH)
    assert not table.empty


def test_committed_table_balances_six_shards_within_ten_percent() -> None:
    files = discover_test_files(REPO_ROOT)
    table = load_shard_timings(REPO_ROOT / DEFAULT_TIMINGS_PATH)
    bins = assign_shards(files, 6, table)
    totals = [shard_bin.estimated_seconds for shard_bin in bins]
    mean = sum(totals) / len(totals)
    spread = max(totals) - min(totals)
    assert spread <= 0.10 * mean, (
        f"six shards are unbalanced by {spread:.1f}s against a {mean:.1f}s mean "
        "(run `just refresh-shard-timings`)"
    )


def test_committed_table_paths_still_mostly_exist() -> None:
    payload = _load_committed_payload()
    durations = payload["durations"]
    assert isinstance(durations, dict)
    files = set(discover_test_files(REPO_ROOT))
    existing = sum(1 for path in durations if path in files)
    coverage = existing / len(durations)
    assert coverage >= 0.90, (
        f"only {coverage:.0%} of tests/shard_timings.json's retained files "
        "still exist (run `just refresh-shard-timings`)"
    )


def test_committed_table_measured_count_has_not_drifted_too_far() -> None:
    payload = _load_committed_payload()
    measured = int(payload["measured_file_count"])
    current = len(discover_test_files(REPO_ROOT))
    drift = abs(current - measured) / measured
    assert drift <= 0.20, (
        f"discovered file count {current} has drifted {drift:.0%} from the "
        f"table's measured {measured} (run `just refresh-shard-timings`)"
    )
