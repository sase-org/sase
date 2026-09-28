"""Tests for the managed-temp-roots registry writers feed and reapers follow."""

from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest

from sase.core import paths as _paths
from sase.core.managed_tmp_roots import (
    effective_managed_tmp_roots,
    _registered_managed_tmp_roots,
    _register_managed_tmp_root,
)
from sase.core.paths import get_sase_managed_tmpdir, managed_tmpdir_root, sase_home
from tests._managed_tmp_reaper_helpers import DAY, NOW, reap_managed_tmpdir


def _production_paths(
    monkeypatch: pytest.MonkeyPatch,
    home: Path,
    tmpdir: Path | None,
) -> None:
    """Resolve managed tmp roots from the environment, not the pytest sandbox."""
    monkeypatch.setenv("SASE_HOME", str(home))
    if tmpdir is None:
        monkeypatch.delenv("SASE_TMPDIR", raising=False)
    else:
        monkeypatch.setenv("SASE_TMPDIR", str(tmpdir))
    monkeypatch.setattr(
        "sase.core.paths.require_pytest_sandbox_root", lambda **_kwargs: None
    )
    _paths._REGISTERED_MANAGED_TMP_ROOTS.clear()


def test_writer_root_is_reaped_from_a_foreign_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The incident shape: writer uses SASE_TMPDIR=X, reaper has no SASE_TMPDIR."""
    home = tmp_path / "home"
    writer_root = tmp_path / "writer-tmp"
    _production_paths(monkeypatch, home, writer_root)

    key_dir = Path(get_sase_managed_tmpdir("cargo-targets", "launch-key"))
    payload = key_dir / "payload.bin"
    payload.write_bytes(b"x" * 1024)
    stamp = NOW - 400 * DAY
    os.utime(payload, (stamp, stamp))
    os.utime(key_dir, (stamp, stamp))

    assert (home / "managed_tmp" / "roots.json").is_file()

    monkeypatch.delenv("SASE_TMPDIR")
    _paths._REGISTERED_MANAGED_TMP_ROOTS.clear()
    roots = effective_managed_tmp_roots(
        effective_root=managed_tmpdir_root(), sase_home=home
    )

    assert writer_root.resolve() in [root.resolve() for root in roots]

    result = reap_managed_tmpdir(root=writer_root, now=NOW)

    assert not key_dir.exists()
    assert result.removed == 1


def test_unsafe_roots_are_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("SASE_HOME", str(home))

    with pytest.raises(ValueError, match="dedicated directory|absolute"):
        _register_managed_tmp_root(Path("/tmp"), sase_home=home, now=NOW)


def test_fail_open_writer_never_breaks_a_launch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    writer_root = tmp_path / "writer-tmp"
    _production_paths(monkeypatch, home, writer_root)
    monkeypatch.setattr(
        "sase.core.managed_tmp_roots.require_rust_binding",
        lambda _name: (_ for _ in ()).throw(AttributeError("stale wheel")),
    )

    created = Path(get_sase_managed_tmpdir("editors"))

    assert created.is_dir()
    assert not (home / "managed_tmp" / "roots.json").exists()


def test_concurrent_registrations_merge(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("SASE_HOME", str(home))
    first = tmp_path / "root-a"
    second = tmp_path / "root-b"
    first.mkdir()
    second.mkdir()

    threads = [
        threading.Thread(
            target=_register_managed_tmp_root,
            args=(root,),
            kwargs={"sase_home": home, "now": NOW},
        )
        for root in (first, second)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert {
        root.resolve() for root in _registered_managed_tmp_roots(sase_home=home)
    } == {
        first.resolve(),
        second.resolve(),
    }


def test_missing_roots_are_pruned_on_next_write(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("SASE_HOME", str(home))
    gone = tmp_path / "gone"
    kept = tmp_path / "kept"
    gone.mkdir()
    kept.mkdir()
    _register_managed_tmp_root(gone, sase_home=home, now=NOW)
    _register_managed_tmp_root(kept, sase_home=home, now=NOW)

    gone.rmdir()
    snapshot = _register_managed_tmp_root(kept, sase_home=home, now=NOW + 7200.0)

    assert [entry["path"] for entry in snapshot["roots"]] == [str(kept.resolve())]


def test_nested_registered_root_is_folded_into_outer_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A per-launch root registered inside an already-covered root is folded."""
    home = tmp_path / "home"
    monkeypatch.setenv("SASE_HOME", str(home))
    outer = tmp_path / "outer"
    nested = outer / "agent-tmp" / "launch-key" / "tmpXXXX" / "managed"
    outer.mkdir()
    nested.mkdir(parents=True)
    _register_managed_tmp_root(outer, sase_home=home, now=NOW)
    _register_managed_tmp_root(nested, sase_home=home, now=NOW)

    roots = effective_managed_tmp_roots(effective_root=outer, sase_home=home)

    assert [root.resolve() for root in roots] == [outer.resolve()]


def test_sibling_roots_are_both_kept(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("SASE_HOME", str(home))
    first = tmp_path / "root-a"
    second = tmp_path / "root-b"
    first.mkdir()
    second.mkdir()
    _register_managed_tmp_root(first, sase_home=home, now=NOW)
    _register_managed_tmp_root(second, sase_home=home, now=NOW)

    roots = effective_managed_tmp_roots(effective_root=first, sase_home=home)

    assert {root.resolve() for root in roots} == {first.resolve(), second.resolve()}


def test_sibling_with_shared_string_prefix_is_not_folded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`/a/tmp2` is a sibling of `/a/tmp`, not a nested root, despite the prefix."""
    home = tmp_path / "home"
    monkeypatch.setenv("SASE_HOME", str(home))
    base = tmp_path / "a"
    base.mkdir()
    tmp_dir = base / "tmp"
    tmp2_dir = base / "tmp2"
    tmp_dir.mkdir()
    tmp2_dir.mkdir()
    _register_managed_tmp_root(tmp_dir, sase_home=home, now=NOW)
    _register_managed_tmp_root(tmp2_dir, sase_home=home, now=NOW)

    roots = effective_managed_tmp_roots(effective_root=tmp_dir, sase_home=home)

    assert {root.resolve() for root in roots} == {
        tmp_dir.resolve(),
        tmp2_dir.resolve(),
    }


def test_sandbox_root_is_never_registered(tmp_path: Path) -> None:
    """Under pytest the sandbox root stays out of the real registry."""
    created = Path(get_sase_managed_tmpdir("editors"))

    assert created.is_dir()
    assert not (sase_home() / "managed_tmp" / "roots.json").exists()


def test_writer_registers_once_per_process_per_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    writer_root = tmp_path / "writer-tmp"
    _production_paths(monkeypatch, home, writer_root)
    calls: list[str] = []

    def counting_register(root: Path | str, *, sase_home: Path | str) -> None:
        calls.append(str(root))
        _register_managed_tmp_root(root, sase_home=sase_home)

    monkeypatch.setattr(
        "sase.core.managed_tmp_roots.try_register_managed_tmp_root",
        counting_register,
    )
    # try_register is imported locally in paths; patch the source module attr
    # the local import resolves to.
    get_sase_managed_tmpdir("editors")
    get_sase_managed_tmpdir("wrappers")

    assert calls == [str(writer_root)]
