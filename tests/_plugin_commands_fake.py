"""Fake-distribution helper for plugin-command tests (mount phase and later).

Writes a temporary ``<dist>.dist-info`` (``METADATA``, ``entry_points.txt``,
optional ``direct_url.json``) plus one adapter module per command, and
prepends the site directory to ``sys.path`` (and to ``PYTHONPATH`` for
subprocess tests through :func:`subprocess_env`). Later phases reuse this
helper for help, completion, and lifecycle coverage.
"""

from __future__ import annotations

import importlib
import json
import os
import re
import sys
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path

import pytest

#: Counter so adapter module names stay unique across tests in one worker.
_ADAPTER_COUNTER = 0


@dataclass(frozen=True)
class FakeCommandSpec:
    """One fake ``sase_commands`` entry point and its adapter source."""

    summary: str = "Fake command for tests"
    api_version: int | None = 1
    exit_code: int | None = 0
    raise_system_exit: int | None = None
    omit: tuple[str, ...] = ()
    broken_import: bool = False
    object_target: str | None = None
    extra_source: str = ""


@dataclass
class FakeDistribution:
    """Paths and adapter names for one installed fake distribution."""

    dist_name: str
    version: str
    site_dir: Path
    dist_info_dir: Path
    adapter_modules: list[str] = field(default_factory=list)
    commands: dict[str, str] = field(default_factory=dict)


def _next_adapter_base() -> str:
    global _ADAPTER_COUNTER
    _ADAPTER_COUNTER += 1
    return f"fake_plugin_cmd_adapter_{_ADAPTER_COUNTER}"


def _adapter_source(
    *,
    module: str,
    command: str,
    spec: FakeCommandSpec,
    call_log: Path,
) -> str:
    lines = [
        "from __future__ import annotations",
        "",
        "import argparse",
        "import json",
        "",
    ]
    if spec.broken_import:
        lines.append("raise ImportError('fake adapter is broken')")
        lines.append("")
        return "\n".join(lines)
    if spec.api_version is not None:
        lines.append(f"SASE_COMMAND_API = {spec.api_version!r}")
    lines.append(f"SUMMARY = {spec.summary!r}")
    if spec.extra_source:
        lines.append(spec.extra_source)
    lines.append(f"CALL_LOG = {str(call_log)!r}")
    lines.append(f"COMMAND = {command!r}")
    if "build_parser" not in spec.omit:
        lines.extend(
            [
                "",
                "def build_parser(prog='sase CMD'):",
                "    parser = argparse.ArgumentParser(prog=prog)",
                "    parser.add_argument('--mode', choices=['fast', 'slow'], default='fast')",
                "    return parser",
            ]
        )
    if "main" not in spec.omit:
        lines.extend(
            [
                "",
                "def main(argv=None, *, prog='sase CMD'):",
                "    import sys as _sys",
                "    with open(CALL_LOG, 'a', encoding='utf-8') as _handle:",
                "        _handle.write(json.dumps({",
                "            'command': COMMAND,",
                "            'argv': list(argv) if argv is not None else None,",
                "            'prog': prog,",
                "            'sys_argv': list(_sys.argv),",
                "        }) + chr(10))",
            ]
        )
        if spec.raise_system_exit is not None:
            lines.append(f"    raise SystemExit({spec.raise_system_exit!r})")
        elif spec.exit_code is not None:
            lines.append(f"    return {spec.exit_code!r}")
        else:
            lines.append("    return None")
    if spec.object_target is not None:
        lines.extend(
            [
                "",
                "class _AdapterObject:",
                "    pass",
                "",
                f"{spec.object_target} = _AdapterObject()",
            ]
        )
        if "main" not in spec.omit:
            lines.append(f"{spec.object_target}.main = main")
        if "build_parser" not in spec.omit:
            lines.append(f"{spec.object_target}.build_parser = build_parser")
        lines.append(f"{spec.object_target}.SUMMARY = SUMMARY")
        if spec.api_version is not None:
            lines.append(f"{spec.object_target}.SASE_COMMAND_API = SASE_COMMAND_API")
    lines.append("")
    return "\n".join(lines)


def install_fake_distribution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    dist_name: str = "fake-listen",
    version: str = "0.1.2",
    commands: Mapping[str, FakeCommandSpec] | None = None,
    metadata_summary: str = "Fake distribution for plugin-command tests",
    editable: bool = False,
    track_modules: list[str] | None = None,
) -> FakeDistribution:
    """Install one fake distribution into the import system for a test.

    Writes the ``.dist-info`` and adapter modules under a fresh site
    directory, prepends it to ``sys.path``, and records adapter module names
    in *track_modules* so the caller can evict them from ``sys.modules``.
    Pass ``commands=None`` for an installed distribution that declares no
    ``sase_commands`` entry points (the "too old to declare" branch).
    """
    specs = dict(commands) if commands else {}
    site_dir = tmp_path / f"fake_site_{dist_name.replace('-', '_')}"
    site_dir.mkdir(parents=True, exist_ok=True)
    call_log = site_dir / "call_log.jsonl"
    if call_log.exists():
        call_log.unlink()

    adapter_base = _next_adapter_base()
    entry_lines: list[str] = []
    adapter_modules: list[str] = []
    command_values: dict[str, str] = {}
    for command, spec in specs.items():
        module = f"{adapter_base}_{command.replace('-', '_')}"
        (site_dir / f"{module}.py").write_text(
            _adapter_source(
                module=module, command=command, spec=spec, call_log=call_log
            ),
            encoding="utf-8",
        )
        value = (
            module if spec.object_target is None else f"{module}:{spec.object_target}"
        )
        entry_lines.append(f"{command} = {value}")
        adapter_modules.append(module)
        command_values[command] = value

    # PEP 376: the dist-info directory name normalizes runs of -_. to _.
    dist_info_name = f"{re.sub(r'[-_.]+', '_', dist_name)}-{version}.dist-info"
    dist_info_dir = site_dir / dist_info_name
    dist_info_dir.mkdir(parents=True, exist_ok=True)
    (dist_info_dir / "METADATA").write_text(
        "\n".join(
            [
                "Metadata-Version: 2.1",
                f"Name: {dist_name}",
                f"Version: {version}",
                f"Summary: {metadata_summary}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    if entry_lines:
        (dist_info_dir / "entry_points.txt").write_text(
            "[sase_commands]\n" + "\n".join(entry_lines) + "\n",
            encoding="utf-8",
        )
    if editable:
        source_root = site_dir / "src" / dist_name.replace("-", "_")
        source_root.mkdir(parents=True, exist_ok=True)
        (dist_info_dir / "direct_url.json").write_text(
            json.dumps(
                {
                    "url": f"file://{source_root}",
                    "dir_info": {"editable": True},
                }
            ),
            encoding="utf-8",
        )

    monkeypatch.syspath_prepend(str(site_dir))
    importlib.invalidate_caches()
    if track_modules is not None:
        track_modules.extend(adapter_modules)
    return FakeDistribution(
        dist_name=dist_name,
        version=version,
        site_dir=site_dir,
        dist_info_dir=dist_info_dir,
        adapter_modules=list(adapter_modules),
        commands=dict(command_values),
    )


def read_call_log(site_dir: Path) -> list[dict]:
    """Return the adapter invocation records written under *site_dir*."""
    call_log = site_dir / "call_log.jsonl"
    if not call_log.exists():
        return []
    records = []
    for line in call_log.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def subprocess_env(site_dir: Path, *, enable_commands: bool = True) -> dict[str, str]:
    """Return an env for subprocess tests with *site_dir* importable."""
    env = os.environ.copy()
    python_path = str(site_dir)
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        f"{python_path}{os.pathsep}{existing}" if existing else python_path
    )
    if enable_commands:
        env.pop("SASE_DISABLE_PLUGIN_COMMANDS", None)
    else:
        env["SASE_DISABLE_PLUGIN_COMMANDS"] = "1"
    return env


@pytest.fixture
def fake_plugin_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[object]:
    """Factory fixture installing fake distributions with module cleanup.

    Unsets the hermetic ``SASE_DISABLE_PLUGIN_COMMANDS`` guard (the feature
    under test) and evicts every adapter module the factory created from
    ``sys.modules`` on teardown, so entry-point scans stay deterministic per
    test in one worker.
    """
    monkeypatch.delenv("SASE_DISABLE_PLUGIN_COMMANDS", raising=False)
    created: list[str] = []

    def _install(**kwargs) -> FakeDistribution:
        return install_fake_distribution(
            tmp_path, monkeypatch, track_modules=created, **kwargs
        )

    yield _install

    for module in created:
        sys.modules.pop(module, None)
    importlib.invalidate_caches()
