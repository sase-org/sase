"""Tests for boot-aware process identity helpers."""

from __future__ import annotations

from pathlib import Path

from sase.core import process_identity


def _write_proc_entry(
    root: Path,
    pid: int,
    *,
    boot_id: str = "boot-a",
    start_ticks: int = 123,
    tgid: int | None = None,
) -> None:
    (root / "sys/kernel/random").mkdir(parents=True, exist_ok=True)
    (root / "sys/kernel/random/boot_id").write_text(boot_id, encoding="utf-8")
    proc_dir = root / str(pid)
    proc_dir.mkdir(parents=True, exist_ok=True)
    stat_tail = ["S", *["0"] * 18, str(start_ticks)]
    (proc_dir / "stat").write_text(
        f"{pid} (python) {' '.join(stat_tail)}\n",
        encoding="utf-8",
    )
    (proc_dir / "status").write_text(
        "\n".join(
            (
                "Name:\tdconf worker",
                f"Tgid:\t{pid if tgid is None else tgid}",
                f"Pid:\t{pid}",
            )
        ),
        encoding="utf-8",
    )


def test_pid_is_thread_detects_observed_thread_shape(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "proc"
    _write_proc_entry(root, 17549, tgid=17441)
    monkeypatch.setattr(process_identity, "_PROC_ROOT", root)

    assert process_identity.pid_is_thread(17549)


def test_process_identity_matches_rejects_different_live_token(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "proc"
    _write_proc_entry(root, 1234, boot_id="boot-b", start_ticks=222)
    monkeypatch.setattr(process_identity, "_PROC_ROOT", root)

    assert not process_identity.process_identity_matches(1234, "boot-a:111")


def test_process_identity_matches_accepts_matching_live_token(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "proc"
    _write_proc_entry(root, 1234, boot_id="boot-a", start_ticks=111)
    monkeypatch.setattr(process_identity, "_PROC_ROOT", root)

    assert process_identity.process_identity_matches(1234, "boot-a:111")


def test_absent_proc_keeps_legacy_process_identity_match(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(process_identity, "_PROC_ROOT", tmp_path / "missing-proc")

    assert process_identity.process_identity_token(1234) == ""
    assert process_identity.process_identity_matches(1234, "boot-a:111")
    assert not process_identity.pid_is_thread(1234)


def test_identity_from_previous_boot_compares_recorded_boot_id(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "proc"
    _write_proc_entry(root, 1234, boot_id="boot-b")
    monkeypatch.setattr(process_identity, "_PROC_ROOT", root)

    assert process_identity.identity_from_previous_boot("boot-a:111")
    assert not process_identity.identity_from_previous_boot("boot-b:111")
