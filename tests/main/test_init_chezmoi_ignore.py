"""Unit coverage for chezmoi machine-overlay ignore maintenance."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from sase.main import _init_chezmoi_ignore
from sase.main._init_chezmoi_ignore import (
    chezmoi_hostname,
    chezmoi_target_entry,
    ensure_machine_ignore_entry,
)


def _completed(
    *,
    returncode: int = 0,
    stdout: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        ["chezmoi", "data", "--format=json"],
        returncode,
        stdout=stdout,
        stderr="",
    )


def test_chezmoi_target_entry_decodes_dot_parts(tmp_path: Path) -> None:
    chezmoi_home = tmp_path / "home"

    assert (
        chezmoi_target_entry(
            chezmoi_home / "dot_config" / "dot_sase" / "machine.yml",
            chezmoi_home=chezmoi_home,
        )
        == ".config/.sase/machine.yml"
    )
    assert (
        chezmoi_target_entry(
            tmp_path / "outside" / "machine.yml",
            chezmoi_home=chezmoi_home,
        )
        is None
    )


def test_chezmoi_hostname_prefers_chezmoi_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        _init_chezmoi_ignore,
        "_run_chezmoi_data",
        lambda: _completed(stdout='{"chezmoi": {"hostname": "Kellys-MBP"}}'),
    )
    monkeypatch.setattr(
        _init_chezmoi_ignore.socket,
        "gethostname",
        lambda: pytest.fail("socket fallback should not be used"),
    )

    assert chezmoi_hostname() == "Kellys-MBP"


@pytest.mark.parametrize("failure", ["missing", "failed", "invalid_json"])
def test_chezmoi_hostname_falls_back_to_short_socket_hostname(
    failure: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if failure == "missing":

        def _missing() -> subprocess.CompletedProcess[str]:
            raise FileNotFoundError

        monkeypatch.setattr(_init_chezmoi_ignore, "_run_chezmoi_data", _missing)
    elif failure == "failed":
        monkeypatch.setattr(
            _init_chezmoi_ignore,
            "_run_chezmoi_data",
            lambda: _completed(returncode=1),
        )
    else:
        monkeypatch.setattr(
            _init_chezmoi_ignore,
            "_run_chezmoi_data",
            lambda: _completed(stdout="{not-json"),
        )
    monkeypatch.setattr(
        _init_chezmoi_ignore.socket,
        "gethostname",
        lambda: "athena.example.test",
    )

    assert chezmoi_hostname() == "athena"


@pytest.mark.parametrize(
    ("chezmoi_value", "socket_value"),
    [
        ("bad\nhostname", "ignored.example.test"),
        ("", ""),
        ("", "bad hostname.example.test"),
    ],
)
def test_chezmoi_hostname_rejects_empty_or_unsafe_values(
    chezmoi_value: str,
    socket_value: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        _init_chezmoi_ignore,
        "_run_chezmoi_data",
        lambda: _completed(
            stdout=f'{{"chezmoi": {{"hostname": {chezmoi_value!r}}}}}'.replace(
                "'",
                '"',
            )
        ),
    )
    monkeypatch.setattr(
        _init_chezmoi_ignore.socket,
        "gethostname",
        lambda: socket_value,
    )

    assert chezmoi_hostname() is None


def test_ensure_machine_ignore_entry_appends_once(tmp_path: Path) -> None:
    chezmoi_home = tmp_path / "home"
    ignore_path = chezmoi_home / ".chezmoiignore"
    ignore_path.parent.mkdir(parents=True)
    ignore_path.write_text("tags", encoding="utf-8")
    entry = ".config/sase/sase_kellys_mbp.yml"

    assert (
        ensure_machine_ignore_entry(
            chezmoi_home=chezmoi_home,
            entry=entry,
            hostname="Kellys-MBP",
        )
        == ignore_path
    )
    expected = (
        "tags\n"
        '{{ if ne .chezmoi.hostname "Kellys-MBP" }}\n'
        f"{entry}\n"
        "{{ end }}\n"
    )
    assert ignore_path.read_text() == expected

    assert (
        ensure_machine_ignore_entry(
            chezmoi_home=chezmoi_home,
            entry=entry,
            hostname="different-host",
        )
        is None
    )
    assert ignore_path.read_text() == expected
