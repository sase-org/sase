"""Tests for sase.workspace_provider.occupant (guard phase of sase-q0)."""

from __future__ import annotations

from pathlib import Path

from sase.workspace_provider.occupant import (
    OccupantRecord,
    clear_occupant_record,
    new_occupant_record,
    occupant_marker_path,
    read_occupant_record,
    write_occupant_record,
)


def _record(**overrides: object) -> OccupantRecord:
    defaults: dict[str, object] = {
        "pid": 1234,
        "workflow": "ace(run)-260818_120000",
        "project": "sase",
        "workspace_num": 17,
        "artifacts_timestamp": "20260818T120000",
        "agent_name": "06e--plan",
        "cl_name": "demo",
        "claimed_at": 1_755_000_000.0,
    }
    defaults.update(overrides)
    return OccupantRecord(**defaults)  # type: ignore[arg-type]


class TestWriteAndReadOccupantRecord:
    def test_round_trip(self, tmp_path: Path) -> None:
        checkout = tmp_path / "checkout"
        checkout.mkdir()
        record = _record()

        write_occupant_record(str(checkout), record)

        assert Path(occupant_marker_path(str(checkout))).exists()
        read_back = read_occupant_record(str(checkout))
        assert read_back == record

    def test_write_creates_sase_dir(self, tmp_path: Path) -> None:
        checkout = tmp_path / "checkout"
        checkout.mkdir()
        write_occupant_record(str(checkout), _record())
        assert (checkout / ".sase" / "occupant.json").exists()

    def test_write_overwrites_existing_record(self, tmp_path: Path) -> None:
        checkout = tmp_path / "checkout"
        checkout.mkdir()
        write_occupant_record(str(checkout), _record(pid=1))
        write_occupant_record(str(checkout), _record(pid=2))

        assert read_occupant_record(str(checkout)).pid == 2  # type: ignore[union-attr]

    def test_write_is_best_effort_on_unwritable_parent(self, tmp_path: Path) -> None:
        # checkout_dir does not exist and its parent is a file, so
        # os.makedirs must fail; the write must not raise.
        blocker = tmp_path / "blocker"
        blocker.write_text("not a dir", encoding="utf-8")
        write_occupant_record(str(blocker / "checkout"), _record())

    def test_missing_marker_returns_none(self, tmp_path: Path) -> None:
        empty = tmp_path / "no-marker"
        empty.mkdir()
        assert read_occupant_record(str(empty)) is None

    def test_malformed_marker_returns_none(self, tmp_path: Path) -> None:
        checkout = tmp_path / "broken"
        (checkout / ".sase").mkdir(parents=True)
        (checkout / ".sase" / "occupant.json").write_text("not json", encoding="utf-8")
        assert read_occupant_record(str(checkout)) is None

    def test_non_dict_marker_returns_none(self, tmp_path: Path) -> None:
        checkout = tmp_path / "listy"
        (checkout / ".sase").mkdir(parents=True)
        (checkout / ".sase" / "occupant.json").write_text("[1, 2]", encoding="utf-8")
        assert read_occupant_record(str(checkout)) is None

    def test_missing_required_field_returns_none(self, tmp_path: Path) -> None:
        checkout = tmp_path / "no-pid"
        (checkout / ".sase").mkdir(parents=True)
        (checkout / ".sase" / "occupant.json").write_text("{}", encoding="utf-8")
        assert read_occupant_record(str(checkout)) is None


class TestClearOccupantRecord:
    def test_removes_existing_record(self, tmp_path: Path) -> None:
        checkout = tmp_path / "checkout"
        checkout.mkdir()
        write_occupant_record(str(checkout), _record())

        clear_occupant_record(str(checkout))

        assert read_occupant_record(str(checkout)) is None

    def test_missing_record_is_a_noop(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        clear_occupant_record(str(empty))  # must not raise


class TestNewOccupantRecord:
    def test_sets_claimed_at(self) -> None:
        record = new_occupant_record(
            pid=99,
            workflow="w",
            project="p",
            workspace_num=10,
        )
        assert record.pid == 99
        assert record.claimed_at > 0

    def test_to_wire_dict_shape(self) -> None:
        record = _record()
        wire = record.to_wire_dict()
        assert wire == {
            "pid": 1234,
            "artifacts_timestamp": "20260818T120000",
            "agent_name": "06e--plan",
            "workflow": "ace(run)-260818_120000",
            "project": "sase",
            "workspace_num": 17,
            "cl_name": "demo",
            "claimed_at": 1_755_000_000.0,
        }
