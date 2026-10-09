"""Completion-phase coverage for plugin-mounted top-level commands.

Uses the shared fake-distribution harness
(:mod:`tests._plugin_commands_fake`); the hermetic
``SASE_DISABLE_PLUGIN_COMMANDS`` guard from ``tests/conftest.py`` stays on
unless the ``fake_plugin_commands`` fixture unsets it.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.completion.build import build_plugin_command, build_spec
from sase.completion.model import CompletionSpec
from sase.completion.plugin_runtime import (
    PluginCommandOmission,
    build_runtime_spec,
)
from sase.completion.runtime_cache_identity import (
    runtime_identity,
    runtime_identity_key,
    source_fingerprint,
)
from tests._plugin_commands_fake import FakeCommandSpec

_FAKE_PARSER_SOURCE = """def build_parser(prog='sase CMD'):
    parser = argparse.ArgumentParser(prog=prog)
    parser.add_argument('--mode', choices=['fast', 'slow'], default='fast')
    cover = parser.add_argument('--cover', help='cover file')
    cover.sase_completion = 'path'
    out_dir = parser.add_argument('--out-dir', help='output directory')
    out_dir.sase_completion = 'dir'
    parser.add_argument('--bead', help='a bead-ish flag')
    source = parser.add_argument('source', help='source file')
    source.sase_completion = 'path'
    subs = parser.add_subparsers(dest='command')
    sub_list = subs.add_parser('list', help='list things')
    sub_list.add_argument('--limit', help='cap rows')
    subs.add_parser('render', help='render things')
    return parser"""


def _root_names(spec: CompletionSpec) -> set[str]:
    return {command.name for command in spec.root.subcommands}


def _child_by_name(spec: CompletionSpec, name: str):
    return next(command for command in spec.root.subcommands if command.name == name)


def test_runtime_spec_merges_fake_subtree(fake_plugin_commands) -> None:
    fake_plugin_commands(
        commands={
            "listen": FakeCommandSpec(parser_source=_FAKE_PARSER_SOURCE),
        }
    )

    runtime = build_runtime_spec()

    assert runtime.omissions == ()
    child = _child_by_name(runtime.spec, "listen")
    assert child.path == ("listen",)
    assert child.summary == "Fake command for tests · fake-listen"
    assert child.aliases == ()
    # No default_child inference even though a "list" child exists.
    assert child.default_child is None
    assert [sub.name for sub in child.subcommands] == ["list", "render"]

    by_dest = {option.dest: option for option in child.options}
    assert by_dest["mode"].choices == ("fast", "slow")
    assert by_dest["mode"].kind is None
    assert by_dest["cover"].kind is not None
    assert by_dest["cover"].kind.value == "path"
    assert by_dest["cover"].value_hint == "path"
    assert by_dest["out_dir"].kind is not None
    assert by_dest["out_dir"].kind.value == "dir"
    # The sase-specific NAME_TABLE heuristic must not apply: dest "bead"
    # would resolve to the bead kind on a builtin command.
    assert by_dest["bead"].kind is None
    assert by_dest["bead"].value_hint is None

    source = next(
        positional for positional in child.positionals if positional.dest == "source"
    )
    assert source.kind is not None
    assert source.kind.value == "path"

    nested = next(sub for sub in child.subcommands if sub.name == "list")
    assert nested.default_child is None
    limit = next(option for option in nested.options if option.dest == "limit")
    # The builtin int-hint table must not apply inside plugin subtrees.
    assert limit.kind is None
    assert limit.value_hint is None


def test_builtin_spec_unchanged_with_fake_plugin(fake_plugin_commands) -> None:
    fake_plugin_commands(
        commands={
            "listen": FakeCommandSpec(parser_source=_FAKE_PARSER_SOURCE),
        }
    )

    assert "listen" not in _root_names(build_spec())
    assert "listen" in _root_names(build_runtime_spec().spec)


def test_build_plugin_command_mounts_at_root() -> None:
    import argparse

    parser = argparse.ArgumentParser(prog="sase aaa")
    parser.add_argument("--mode", choices=["fast"])

    command = build_plugin_command(parser, name="aaa", summary="Aaa fake")
    assert command.path == ("aaa",)
    assert command.summary == "Aaa fake"
    assert command.subcommands == ()


def test_identity_key_changes_on_install_uninstall_version_and_switch(
    fake_plugin_commands, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty_key = runtime_identity_key()

    dist = fake_plugin_commands(commands={"listen": FakeCommandSpec()})
    installed_key = runtime_identity_key()
    assert installed_key != empty_key
    assert any(
        entry["name"] == "listen"
        for entry in runtime_identity()["plugin_commands"]["commands"]
    )

    monkeypatch.setenv("SASE_DISABLE_PLUGIN_COMMANDS", "1")
    assert runtime_identity_key() != installed_key
    monkeypatch.delenv("SASE_DISABLE_PLUGIN_COMMANDS")

    metadata = dist.dist_info_dir / "METADATA"
    text = metadata.read_text(encoding="utf-8")
    metadata.write_text(
        text.replace("Version: 0.1.2", "Version: 0.2.0"), encoding="utf-8"
    )
    importlib.invalidate_caches()
    assert runtime_identity_key() != installed_key

    metadata.write_text(text, encoding="utf-8")
    shutil.rmtree(dist.dist_info_dir)
    importlib.invalidate_caches()
    assert runtime_identity_key() == empty_key


def test_fingerprint_changes_on_editable_source_edit(fake_plugin_commands) -> None:
    dist = fake_plugin_commands(commands={"listen": FakeCommandSpec()}, editable=True)
    # Mirror the layout the identity walk resolves: the editable source
    # root plus the adapter's top-level module name.
    source_root = dist.site_dir / "src" / dist.dist_name.replace("-", "_")
    target_dir = source_root / dist.adapter_modules[0]
    target_dir.mkdir(parents=True, exist_ok=True)
    init = target_dir / "__init__.py"
    init.write_text("# fake editable source\n", encoding="utf-8")
    importlib.invalidate_caches()

    before = source_fingerprint()
    with init.open("a", encoding="utf-8") as handle:
        handle.write("# touched\n")
    importlib.invalidate_caches()
    assert source_fingerprint() != before


def _warm_env(home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["SASE_HOME"] = str(home)
    env.pop("SASE_SDD_BEADS_DIR", None)
    env.pop("SASE_SDD_PLANS_DIR", None)
    return env


_WARM_PROBE = """
import sys
from sase.main.entry import main

sys.argv = ["sase", "completion", "ensure", "bash"]
try:
    main()
except SystemExit as exc:
    assert exc.code in (0, None), exc.code
forbidden = [
    name
    for name in sys.modules
    if name == "sase.main.parser"
    or name == "sase.main.parser_registry"
    or name == "sase.completion.build"
    or name == "sase.completion.plugin_runtime"
    or name.startswith("sase.ace")
    or name == "textual"
    or name.startswith("textual.")
    or name == "rich"
    or name.startswith("rich.")
    or name.startswith("fake_plugin_cmd_adapter")
]
assert not forbidden, forbidden
"""


def test_warm_ensure_imports_neither_plugin_nor_parser_modules(
    fake_plugin_commands, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.completion.runtime_cache_support import (
        grammar_filename,
        shell_cache_dir,
    )

    dist = fake_plugin_commands(
        commands={"listen": FakeCommandSpec(parser_source=_FAKE_PARSER_SOURCE)}
    )
    home = tmp_path / "sase-home"
    monkeypatch.setenv("SASE_HOME", str(home))
    env = _warm_env(home)
    python_path = str(dist.site_dir)
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        f"{python_path}{os.pathsep}{existing}" if existing else python_path
    )
    env.pop("SASE_DISABLE_PLUGIN_COMMANDS", None)

    def _run(argv: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            argv,
            cwd=home.parent,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    # Cold run: real generation, which must succeed with the plugin installed.
    cold = _run([sys.executable, "-m", "sase", "completion", "ensure", "bash"])
    assert cold.returncode == 0, cold.stderr + cold.stdout
    grammar = Path(cold.stdout.strip())
    assert grammar.name == grammar_filename("bash")
    before = grammar.stat().st_mtime_ns

    # Warm runs: cache hits that import neither the plugin nor the parser.
    for _ in range(2):
        result = _run([sys.executable, "-c", textwrap.dedent(_WARM_PROBE)])
        assert result.returncode == 0, result.stderr + result.stdout
    assert grammar.stat().st_mtime_ns == before
    assert grammar.parent == shell_cache_dir(runtime_identity_key(), "bash").resolve(
        strict=False
    )


def test_omission_recorded_once_and_not_retried(
    fake_plugin_commands, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.completion.runtime_cache import ensure_cached_grammar
    from sase.completion.runtime_cache_identity import runtime_identity_key
    from sase.completion.runtime_cache_support import shell_cache_dir

    home = tmp_path / "sase-home"
    monkeypatch.setenv("SASE_HOME", str(home))
    fake_plugin_commands(commands={"broken": FakeCommandSpec(broken_import=True)})

    runtime = build_runtime_spec()
    assert [omission.name for omission in runtime.omissions] == ["broken"]
    assert "broken" not in _root_names(runtime.spec)

    grammar = ensure_cached_grammar("bash")
    manifest = json.loads(
        (grammar.parent / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["plugin_omissions"] == [
        {
            "name": "broken",
            "distribution": "fake-listen",
            "version": "0.1.2",
            "reason": runtime.omissions[0].reason,
        }
    ]
    # The key is unchanged by the omission, so the second ensure is a hit:
    # no rebuild, no re-import of the broken plugin.
    before = grammar.stat().st_mtime_ns
    assert ensure_cached_grammar("bash") == grammar.resolve(strict=False)
    assert grammar.stat().st_mtime_ns == before
    assert (
        shell_cache_dir(runtime_identity_key(), "bash").resolve(strict=False)
        == grammar.resolve(strict=False).parent
    )


def test_emitters_include_plugin_subtree(fake_plugin_commands) -> None:
    from sase.completion.emit_bash import emit_bash
    from sase.completion.emit_fish import emit_fish
    from sase.completion.emit_zsh import emit_zsh

    fake_plugin_commands(
        commands={"listen": FakeCommandSpec(parser_source=_FAKE_PARSER_SOURCE)}
    )
    spec = build_runtime_spec().spec
    assert "listen" in emit_bash(spec)
    assert "listen" in emit_zsh(spec)
    assert "listen" in emit_fish(spec)


def test_doctor_plugin_omissions_warn_and_ok() -> None:
    from sase.doctor.checks_completion import _check_completion_plugin_omissions

    calm = _check_completion_plugin_omissions(omissions=[])
    assert calm.status == "OK"

    flagged = _check_completion_plugin_omissions(
        omissions=[
            {
                "name": "broken",
                "distribution": "fake-listen",
                "version": "0.1.2",
                "reason": "could not import 'x': nope",
            }
        ]
    )
    assert flagged.status == "WARN"
    assert "sase broken" in flagged.summary
    assert any("fake-listen" in step for step in flagged.next_steps)


def test_cached_plugin_omissions_read_manifests(
    fake_plugin_commands, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.completion.runtime_cache_identity import runtime_identity_key
    from sase.completion.runtime_cache_support import shell_cache_dir
    from sase.doctor.checks_completion import _cached_plugin_omissions

    home = tmp_path / "sase-home"
    monkeypatch.setenv("SASE_HOME", str(home))
    fake_plugin_commands(commands={"broken": FakeCommandSpec(broken_import=True)})

    assert _cached_plugin_omissions() == ()

    entry = PluginCommandOmission(
        name="broken",
        distribution="fake-listen",
        version="0.1.2",
        reason="could not import 'x': nope",
    ).to_json()
    manifest_dir = shell_cache_dir(runtime_identity_key(), "bash")
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / "manifest.json").write_text(
        json.dumps({"plugin_omissions": [entry, dict(entry)]}),
        encoding="utf-8",
    )
    # The same omission recorded for two shells is reported once.
    other = shell_cache_dir(runtime_identity_key(), "fish")
    other.mkdir(parents=True, exist_ok=True)
    (other / "manifest.json").write_text(
        json.dumps({"plugin_omissions": [entry]}), encoding="utf-8"
    )

    assert _cached_plugin_omissions() == (entry,)


def _fake_app(monkeypatch: pytest.MonkeyPatch, **stubs) -> SimpleNamespace:
    import sase.ace.tui.command_line.grammar as grammar_module

    for attr, value in stubs.items():
        monkeypatch.setattr(grammar_module, attr, value)
    app = SimpleNamespace(
        run_worker=lambda coro, exclusive=False: asyncio.run(coro),
    )
    return app


def test_tui_grammar_first_load_stores_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.ace.tui.command_line.grammar as grammar_module

    events: list[str] = []
    app = _fake_app(
        monkeypatch,
        current_command_line_spec_key=lambda: "key-1",
        _load_command_line_grammar_sync=lambda: (
            events.append("sync-load") or "handle-1"
        ),
    )

    ready: list[str] = []
    assert (
        grammar_module.ensure_command_line_grammar_loaded(
            app, on_ready=lambda: ready.append("ready")
        )
        is False
    )
    assert grammar_module.command_line_grammar_for(app) == "handle-1"
    assert grammar_module._command_line_grammar_spec_key_for(app) == "key-1"
    assert ready == ["ready"]
    assert events == ["sync-load"]


def test_tui_grammar_recheck_reloads_only_on_key_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.ace.tui.command_line.grammar as grammar_module

    keys = ["key-1", "key-1", "key-2"]
    events: list[str] = []

    def _sync_load():
        events.append("sync-load")
        return f"handle-{len(events)}"

    app = _fake_app(
        monkeypatch,
        current_command_line_spec_key=lambda: keys.pop(0),
        _load_command_line_grammar_sync=_sync_load,
    )

    assert grammar_module.ensure_command_line_grammar_loaded(app) is False
    first = grammar_module.command_line_grammar_for(app)
    assert first == "handle-1"
    assert events == ["sync-load"]

    # Same key: ready immediately, no rebuild.
    assert grammar_module.ensure_command_line_grammar_loaded(app) is True
    assert grammar_module.command_line_grammar_for(app) is first
    assert events == ["sync-load"]

    # Changed key: the background recheck reloads and records the new key.
    assert grammar_module.ensure_command_line_grammar_loaded(app) is True
    assert grammar_module.command_line_grammar_for(app) == "handle-2"
    assert grammar_module._command_line_grammar_spec_key_for(app) == "key-2"
    assert events == ["sync-load", "sync-load"]
    assert not grammar_module.is_command_line_grammar_pending(app)


def test_tui_grammar_recheck_adopts_key_for_unkeyed_handle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.ace.tui.command_line.grammar as grammar_module

    keys = ["key-1", "key-2"]
    events: list[str] = []

    def _sync_load():
        events.append("sync-load")
        return f"handle-{len(events)}"

    app = _fake_app(
        monkeypatch,
        current_command_line_spec_key=lambda: keys[0],
        _load_command_line_grammar_sync=_sync_load,
    )
    app._command_line_grammar = "handle-injected"

    ready: list[str] = []
    assert (
        grammar_module.ensure_command_line_grammar_loaded(
            app, on_ready=lambda: ready.append("ready")
        )
        is True
    )
    assert grammar_module.command_line_grammar_for(app) == "handle-injected"
    assert events == []
    assert grammar_module._command_line_grammar_spec_key_for(app) == "key-1"
    assert ready == []
    assert not grammar_module.is_command_line_grammar_pending(app)

    keys[0] = "key-2"
    assert grammar_module.ensure_command_line_grammar_loaded(app) is True
    assert grammar_module.command_line_grammar_for(app) == "handle-1"
    assert grammar_module._command_line_grammar_spec_key_for(app) == "key-2"
    assert events == ["sync-load"]


def test_omission_round_trip() -> None:
    omission = PluginCommandOmission(
        name="broken",
        distribution="fake-listen",
        version="0.1.2",
        reason="boom",
    )
    assert PluginCommandOmission.from_json(omission.to_json()) == omission


def test_runtime_structural_view_includes_plugin(fake_plugin_commands) -> None:
    fake_plugin_commands(commands={"listen": FakeCommandSpec()})
    view = build_runtime_spec().structural_view()
    names = {child["name"] for child in view["root"]["subcommands"]}
    assert "listen" in names


def test_spec_json_round_trip_with_plugin(fake_plugin_commands) -> None:
    fake_plugin_commands(commands={"listen": FakeCommandSpec()})
    spec = build_runtime_spec().spec
    assert CompletionSpec.from_json(json.loads(json.dumps(spec.to_json()))) == spec
