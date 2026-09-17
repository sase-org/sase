"""Tests for service boot-id discovery helpers."""

from __future__ import annotations

from types import SimpleNamespace

from sase.service import boot


def test_linux_boot_id_reads_proc_file(tmp_path, monkeypatch) -> None:
    path = tmp_path / "boot_id"
    path.write_text("boot-123\n", encoding="utf-8")
    monkeypatch.setattr(boot.platform, "system", lambda: "Linux")
    monkeypatch.setattr(boot, "_LINUX_BOOT_ID_PATH", path)
    boot.current_boot_id.cache_clear()

    assert boot.current_boot_id() == "boot-123"
    boot.current_boot_id.cache_clear()


def test_macos_boot_id_uses_sysctl(monkeypatch) -> None:
    monkeypatch.setattr(boot.platform, "system", lambda: "Darwin")

    def fake_run(*_args, **_kwargs):
        return SimpleNamespace(stdout="mac-boot\n")

    monkeypatch.setattr(boot.subprocess, "run", fake_run)
    boot.current_boot_id.cache_clear()

    assert boot.current_boot_id() == "mac-boot"
    boot.current_boot_id.cache_clear()


def test_unknown_platform_returns_none(monkeypatch) -> None:
    monkeypatch.setattr(boot.platform, "system", lambda: "Plan9")
    boot.current_boot_id.cache_clear()

    assert boot.current_boot_id() is None
    boot.current_boot_id.cache_clear()
