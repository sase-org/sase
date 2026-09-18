"""Tests for runtime completion grammar caching."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path

import pytest

from sase.completion import runtime_cache
from sase.completion.install_models import ExpectedCompletion
from sase.completion.install_scripts import zwc_path
from sase.completion.runtime_cache import (
    CompletionCacheError,
    assess_cached_grammar,
    ensure_cached_grammar,
)
from sase.core.paths import sase_subdir


def _expected_factory(calls: list[tuple[str, ...]], *, text: str = "# generated\n"):
    def _expected(shells: Sequence[str]):
        calls.append(tuple(shells))
        return {
            shell: ExpectedCompletion(f"{text}# {shell}\n", f"digest-{shell}")
            for shell in shells
        }

    return _expected


def _manifest(path: Path) -> dict[str, object]:
    return json.loads(path.with_name("manifest.json").read_text(encoding="utf-8"))


def test_ensure_generates_then_reuses_bash_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    calls: list[tuple[str, ...]] = []

    grammar = ensure_cached_grammar("bash", expected_fn=_expected_factory(calls))
    again = ensure_cached_grammar(
        "bash",
        expected_fn=lambda _shells: pytest.fail("warm cache built parser"),
    )

    assert again == grammar
    assert calls == [("bash",)]
    assert grammar.is_absolute()
    assert grammar.read_text(encoding="utf-8") == "# generated\n# bash\n"
    manifest = _manifest(grammar)
    assert manifest["shell"] == "bash"
    assert manifest["structural_digest"] == "digest-bash"
    assert manifest["content_checksum"]


def test_ensure_records_loader_metadata_from_target_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    calls: list[tuple[str, ...]] = []

    grammar = ensure_cached_grammar(
        "fish",
        owner="chezmoi",
        target=tmp_path / "fish-completions",
        expected_fn=_expected_factory(calls),
    )

    loader = _manifest(grammar)["loader"]
    assert isinstance(loader, dict)
    assert loader["owner"] == "chezmoi"
    assert loader["target"] == str(tmp_path / "fish-completions" / "sase.fish")


def test_corrupt_cache_file_regenerates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    calls: list[tuple[str, ...]] = []
    grammar = ensure_cached_grammar("bash", expected_fn=_expected_factory(calls))
    grammar.write_text("# corrupt\n", encoding="utf-8")

    ensure_cached_grammar(
        "bash",
        expected_fn=_expected_factory(calls, text="# regenerated\n"),
    )

    assert calls == [("bash",), ("bash",)]
    assert grammar.read_text(encoding="utf-8") == "# regenerated\n# bash\n"


def test_source_fingerprint_change_regenerates_same_version_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    calls: list[tuple[str, ...]] = []
    ensure_cached_grammar("bash", expected_fn=_expected_factory(calls))
    monkeypatch.setattr(
        "sase.completion.runtime_cache._source_fingerprint",
        lambda: "changed-source-fingerprint",
    )

    ensure_cached_grammar("bash", expected_fn=_expected_factory(calls))

    assert calls == [("bash",), ("bash",)]


def test_zsh_cache_requires_fresh_bytecode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    calls: list[tuple[str, ...]] = []

    def _zcompile(path: Path) -> None:
        zwc_path(path).write_text("bytecode\n", encoding="utf-8")

    grammar = ensure_cached_grammar(
        "zsh",
        expected_fn=_expected_factory(calls),
        zcompile_fn=_zcompile,
    )
    zwc_path(grammar).unlink()
    ensure_cached_grammar(
        "zsh",
        expected_fn=_expected_factory(calls, text="# regenerated\n"),
        zcompile_fn=_zcompile,
    )

    assert calls == [("zsh",), ("zsh",)]
    assert zwc_path(grammar).is_file()
    assert grammar.read_text(encoding="utf-8") == "# regenerated\n# zsh\n"


def _zcompile(path: Path) -> None:
    zwc_path(path).write_text("bytecode\n", encoding="utf-8")


def _ephemeral_names(directory: Path) -> list[str]:
    return sorted(
        path.name
        for path in directory.iterdir()
        if path.name.startswith(".stage.") or path.name == ".backup"
    )


def _fail_replace_when_dest_name(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    original = runtime_cache._replace_file

    def _replace(src: Path, dst: Path) -> None:
        if dst.name == name:
            raise OSError(f"refusing to publish {name}")
        original(src, dst)

    monkeypatch.setattr(runtime_cache, "_replace_file", _replace)


@pytest.mark.parametrize(
    ("shell", "fail_name"),
    [
        ("bash", "sase.bash"),
        ("bash", "manifest.json"),
        ("zsh", "_sase"),
        ("zsh", "_sase.zwc"),
        ("zsh", "manifest.json"),
    ],
)
def test_forced_refresh_publish_failure_preserves_previous_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    shell: str,
    fail_name: str,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    grammar = ensure_cached_grammar(
        shell,
        expected_fn=_expected_factory([]),
        zcompile_fn=_zcompile,
    )
    before = grammar.read_text(encoding="utf-8")
    before_manifest = _manifest(grammar)
    before_zwc = (
        zwc_path(grammar).read_text(encoding="utf-8") if shell == "zsh" else None
    )
    _fail_replace_when_dest_name(monkeypatch, fail_name)

    with pytest.raises(CompletionCacheError, match="refusing to publish"):
        ensure_cached_grammar(
            shell,
            force=True,
            expected_fn=_expected_factory([], text="# new\n"),
            zcompile_fn=_zcompile,
        )

    assert grammar.read_text(encoding="utf-8") == before
    after_manifest = _manifest(grammar)
    assert after_manifest["content_checksum"] == before_manifest["content_checksum"]
    assert after_manifest["structural_digest"] == before_manifest["structural_digest"]
    if shell == "zsh":
        assert zwc_path(grammar).read_text(encoding="utf-8") == before_zwc
    assert _ephemeral_names(grammar.parent) == []
    assert assess_cached_grammar(shell).status == "current"


def test_first_generation_publish_failure_leaves_no_current_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    _fail_replace_when_dest_name(monkeypatch, "manifest.json")

    with pytest.raises(CompletionCacheError, match="refusing to publish"):
        ensure_cached_grammar("bash", expected_fn=_expected_factory([]))

    status = assess_cached_grammar("bash")
    assert status.status == "missing"
    if status.path is not None:
        path = Path(status.path)
        assert not path.exists()
        assert not (path.parent / "manifest.json").exists()
        if path.parent.exists():
            assert _ephemeral_names(path.parent) == []


def test_generation_failure_preserves_previous_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    grammar = ensure_cached_grammar("bash", expected_fn=_expected_factory([]))
    before = grammar.read_text(encoding="utf-8")

    def _boom(_shells: Sequence[str]) -> dict[str, ExpectedCompletion]:
        raise RuntimeError("generate failed")

    with pytest.raises(CompletionCacheError, match="generate failed"):
        ensure_cached_grammar("bash", force=True, expected_fn=_boom)

    assert grammar.read_text(encoding="utf-8") == before
    assert assess_cached_grammar("bash").status == "current"
    assert _ephemeral_names(grammar.parent) == []


def test_zcompile_failure_preserves_previous_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    grammar = ensure_cached_grammar(
        "zsh",
        expected_fn=_expected_factory([]),
        zcompile_fn=_zcompile,
    )
    before = grammar.read_text(encoding="utf-8")
    before_zwc = zwc_path(grammar).read_text(encoding="utf-8")

    def _fail_zcompile(_path: Path) -> None:
        raise OSError("zcompile exploded")

    with pytest.raises(CompletionCacheError, match="zcompile exploded"):
        ensure_cached_grammar(
            "zsh",
            force=True,
            expected_fn=_expected_factory([], text="# new\n"),
            zcompile_fn=_fail_zcompile,
        )

    assert grammar.read_text(encoding="utf-8") == before
    assert zwc_path(grammar).read_text(encoding="utf-8") == before_zwc
    assert _ephemeral_names(grammar.parent) == []


def test_staged_manifest_write_failure_preserves_previous_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    grammar = ensure_cached_grammar("bash", expected_fn=_expected_factory([]))
    before = grammar.read_text(encoding="utf-8")

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("staged manifest failed")

    monkeypatch.setattr(runtime_cache, "_write_manifest", _boom)
    with pytest.raises(CompletionCacheError, match="staged manifest failed"):
        ensure_cached_grammar(
            "bash",
            force=True,
            expected_fn=_expected_factory([], text="# new\n"),
        )

    assert grammar.read_text(encoding="utf-8") == before
    assert _ephemeral_names(grammar.parent) == []


def test_interrupted_publish_restores_coherent_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    grammar = ensure_cached_grammar("bash", expected_fn=_expected_factory([]))
    before = grammar.read_text(encoding="utf-8")
    backup = grammar.parent / ".backup"
    backup.mkdir()
    shutil.copy2(grammar, backup / grammar.name)
    shutil.copy2(grammar.with_name("manifest.json"), backup / "manifest.json")
    grammar.write_text("# half-published\n", encoding="utf-8")

    restored = ensure_cached_grammar(
        "bash",
        expected_fn=lambda _shells: pytest.fail("should reuse restored generation"),
    )

    assert restored.read_text(encoding="utf-8") == before
    assert not backup.exists()
    assert assess_cached_grammar("bash").status == "current"


def test_leftover_staging_dirs_are_removed_on_next_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    grammar = ensure_cached_grammar("bash", expected_fn=_expected_factory([]))
    leftover = grammar.parent / ".stage.99999"
    leftover.mkdir()
    (leftover / "sase.bash").write_text("# stale stage\n", encoding="utf-8")

    ensure_cached_grammar(
        "bash",
        force=True,
        expected_fn=_expected_factory([], text="# regenerated\n"),
    )

    assert not leftover.exists()
    assert _ephemeral_names(grammar.parent) == []
    assert grammar.read_text(encoding="utf-8") == "# regenerated\n# bash\n"


def test_distinct_runtime_identities_share_one_sase_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(
        runtime_cache, "_runtime_identity_key", lambda identity=None: "runtime-aaa"
    )
    first = ensure_cached_grammar(
        "bash", expected_fn=_expected_factory([], text="# runtime-a\n")
    )
    monkeypatch.setattr(
        runtime_cache, "_runtime_identity_key", lambda identity=None: "runtime-bbb"
    )
    second = ensure_cached_grammar(
        "bash", expected_fn=_expected_factory([], text="# runtime-b\n")
    )

    assert first != second
    assert first.parent.parent.parent == second.parent.parent.parent
    assert first.read_text(encoding="utf-8") == "# runtime-a\n# bash\n"
    assert second.read_text(encoding="utf-8") == "# runtime-b\n# bash\n"


def test_old_runtime_identities_are_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    root = sase_subdir("completion") / "grammar"
    root.mkdir(parents=True)
    for index in range(7):
        path = root / f"old-runtime-{index:02d}"
        path.mkdir()
        os.utime(path, (1_000 + index, 1_000 + index))

    ensure_cached_grammar("bash", expected_fn=_expected_factory([]))

    remaining = sorted(path.name for path in root.iterdir() if path.is_dir())
    assert len(remaining) == 6
    assert "old-runtime-00" not in remaining
    assert "old-runtime-01" not in remaining


def test_cache_paths_containing_spaces_round_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "sase home"
    loader = tmp_path / "load ers" / "sase"
    monkeypatch.setenv("SASE_HOME", str(home))

    grammar = ensure_cached_grammar(
        "bash",
        owner="local",
        loader_path=loader,
        expected_fn=_expected_factory([]),
    )

    assert " " in str(grammar)
    assert grammar.is_file()
    recorded = _manifest(grammar)["loader"]
    assert isinstance(recorded, dict)
    assert recorded["target"] == str(loader.expanduser().resolve(strict=False))


_CONCURRENT_WORKER = """
import os
import time
from pathlib import Path

from sase.completion.install_models import ExpectedCompletion
from sase.completion.runtime_cache import ensure_cached_grammar

gate = Path(os.environ["SASE_CACHE_GATE"])
calls = Path(os.environ["SASE_CACHE_CALLS"])
while not gate.exists():
    time.sleep(0.01)  # sase-test-wait: wait for parent to release both workers

def expected(shells):
    (calls / str(os.getpid())).write_text("1", encoding="utf-8")
    time.sleep(0.2)  # sase-test-wait: hold the generate lock so the other worker queues
    return {
        shell: ExpectedCompletion(f"# generated\\n# {shell}\\n", f"digest-{shell}")
        for shell in shells
    }

print(ensure_cached_grammar("bash", expected_fn=expected))
"""


def test_simultaneous_cold_callers_build_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    gate = tmp_path / "gate"
    calls = tmp_path / "calls"
    calls.mkdir()
    env = os.environ.copy()
    env["SASE_HOME"] = str(tmp_path / "home")
    env["SASE_CACHE_GATE"] = str(gate)
    env["SASE_CACHE_CALLS"] = str(calls)
    workers = [
        subprocess.Popen(
            [sys.executable, "-c", _CONCURRENT_WORKER],
            env=env,
            cwd=tmp_path,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(2)
    ]
    time.sleep(0.05)  # sase-test-wait: let both workers reach the gate
    gate.write_text("go", encoding="utf-8")
    outputs: list[str] = []
    for worker in workers:
        stdout, stderr = worker.communicate(timeout=30)
        assert worker.returncode == 0, stderr
        outputs.append(stdout.strip())

    assert outputs[0] == outputs[1]
    assert Path(outputs[0]).is_file()
    assert len(list(calls.iterdir())) == 1
    assert _ephemeral_names(Path(outputs[0]).parent) == []
