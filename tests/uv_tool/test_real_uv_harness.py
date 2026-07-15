"""Behavioral harness: exercise the engine against the *real* ``uv`` binary.

The unit suites verify every pure piece of :mod:`sase.uv_tool` in isolation, but
the whole design rests on three empirical assumptions about how ``uv tool``
actually behaves (see the epic's "uv investigation"). Those assumptions cannot
be checked by mocking uv — only by running it. This module does exactly that,
using a **disposable stand-in tool** (``cowsay``) with a **stand-in plugin**
(``six``) so it never touches the real ``sase`` install:

* (a) ``--with`` *replaces* the injected set, so reconstructing the full set from
  the receipt and re-installing must **preserve** a previously-injected plugin
  (guards finding #2 / decision *D2*).
* (b) ``--upgrade-package`` upgrades **exactly one** injected package, leaving the
  primary and the other plugins pinned (the invariant behind ``sase plugin
  update`` / its *D3*-complement: updating a plugin never bumps core).
* (c) ``uv tool upgrade <tool>`` re-resolves the **whole** environment — the
  primary *and* every ``--with`` plugin — in one shot (guards finding #3, the
  basis of ``sase update``).
* (d) targeting a stale transitive dependency while reconstructing editable
  primary/plugin requirements upgrades that dependency without losing either
  editable source (the mixed comprehensive-update invariant).

The harness is hermetic: ``UV_TOOL_DIR`` / ``UV_TOOL_BIN_DIR`` point at a
``tmp_path`` so installs land in a throwaway directory, never the user's real uv
tool environment. It is marked ``slow`` (it shells out to uv and hits the
package index) so the fast ``just check`` run skips it, and it skips cleanly when
``uv`` is absent (CI parity) or the index is unreachable.
"""

from __future__ import annotations

import functools
import os
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest

from sase.uv_tool.commands import build_install, build_upgrade_packages
from sase.uv_tool.errors import UvCommandFailedError
from sase.uv_tool.overrides import write_editable_overrides
from sase.uv_tool.receipt import load_receipt
from sase.uv_tool.runner import ChangeKind, UvChangeSet, run_uv

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(shutil.which("uv") is None, reason="uv binary not on PATH"),
]

# --- Disposable stand-ins ------------------------------------------------------
#
# ``cowsay`` stands in for the primary ``sase`` package: a real tool with a
# console script (so uv writes a receipt) and several published versions.
# ``six`` / ``pyfiglet`` stand in for injected plugins: tiny, pure-Python, and
# old enough that a low resolution leaves clear headroom to upgrade.
PRIMARY = "cowsay"
PRIMARY_FLOOR = "cowsay>=6"  # 6.0 is the lowest version that still ships the CLI.
PLUGIN = "six"
OTHER_PLUGIN = "pyfiglet"
OTHER_PLUGIN_PINNED = "pyfiglet==0.8.post1"
SECOND_ADD = "iniconfig"  # a fresh plugin to inject in the preserve test.
EDITABLE_PRIMARY = "editable-update-primary"
EDITABLE_PLUGIN = "editable-update-plugin"


@dataclass(frozen=True)
class UvToolEnv:
    """A hermetic uv tool environment rooted under ``tmp_path``."""

    env: dict[str, str]
    tool_dir: Path

    @property
    def receipt_path(self) -> Path:
        """Path to the stand-in tool's ``uv-receipt.toml``."""
        return self.tool_dir / PRIMARY / "uv-receipt.toml"

    def receipt_path_for(self, name: str) -> Path:
        return self.tool_dir / name / "uv-receipt.toml"

    def run(self, argv: Sequence[str]) -> UvChangeSet:
        """Run a ``uv`` *argv* inside this isolated environment."""
        return run_uv(argv, run_fn=_runner(self.env))

    def installed_versions(self, tool_name: str = PRIMARY) -> dict[str, str]:
        """Map each requirement in the current receipt to its resolved version.

        Reads the version actually on disk from the tool venv's
        ``*.dist-info`` directories, so assertions compare against ground truth
        rather than re-parsing uv's log.
        """
        site = self.tool_dir / tool_name / "lib"
        versions: dict[str, str] = {}
        for dist_info in site.glob("python*/site-packages/*.dist-info"):
            name, _, version = dist_info.name.removesuffix(".dist-info").rpartition("-")
            if name:
                versions[name.replace("_", "-").lower()] = version
        return versions


def _runner(env: dict[str, str]) -> functools.partial[subprocess.CompletedProcess[str]]:
    """A ``run_uv`` runner that shells out inside the isolated *env*."""
    return functools.partial(subprocess.run, env=env)


@pytest.fixture
def uv_env(tmp_path: Path) -> UvToolEnv:
    """Provide a throwaway uv tool environment isolated from the real install."""
    tool_dir = tmp_path / "tools"
    bin_dir = tmp_path / "bin"
    tool_dir.mkdir()
    bin_dir.mkdir()
    env = dict(os.environ)
    env["UV_TOOL_DIR"] = str(tool_dir)
    env["UV_TOOL_BIN_DIR"] = str(bin_dir)
    # tmp_path and the uv cache are often on different filesystems; copy instead
    # of hardlink so installs are silent and reliable.
    env["UV_LINK_MODE"] = "copy"
    return UvToolEnv(env=env, tool_dir=tool_dir)


def _install_base(uv_env: UvToolEnv, argv_tail: Sequence[str]) -> UvChangeSet:
    """Install the stand-in tool, skipping the test if the index is unreachable.

    The harness guards *uv behavior*, not sase logic (the unit suites cover the
    logic), so an offline/index failure during setup is infrastructure noise:
    skip rather than fail.
    """
    argv = ["uv", "tool", "install", *argv_tail, "--color", "never"]
    try:
        return uv_env.run(argv)
    except UvCommandFailedError as exc:  # pragma: no cover - network dependent
        pytest.skip(f"uv could not install the throwaway tool (offline?): {exc}")


def test_reconstruct_install_preserves_injected_plugin(uv_env: UvToolEnv) -> None:
    """(a) Reconstruct-then-install preserves a previously-injected plugin.

    Finding #2: ``--with X`` *replaces* the injected set. A naive
    ``uv tool install <primary> --with <new>`` therefore drops the existing
    plugin — we demonstrate that — whereas the engine reconstructs the **full**
    ``--with`` set from the receipt, so the old plugin survives and the new one
    joins it.
    """
    _install_base(uv_env, [PRIMARY, "--with", PLUGIN])
    receipt = load_receipt(uv_env.receipt_path, primary_name=PRIMARY)
    assert receipt.is_injected(PLUGIN)

    # A naive `--with <new>` (what a hand-rolled command would do) drops six.
    uv_env.run(
        ["uv", "tool", "install", PRIMARY, "--with", SECOND_ADD, "--color", "never"]
    )
    assert PLUGIN not in uv_env.installed_versions()

    # The engine rebuilds the whole set from the *original* receipt, restoring
    # six and adding the new plugin in one install.
    uv_env.run(build_install(receipt, add=SECOND_ADD, color="never"))
    installed = uv_env.installed_versions()
    assert PLUGIN in installed, (
        "reconstruct must preserve the previously-injected plugin"
    )
    assert SECOND_ADD in installed, "the newly-added plugin must be injected too"
    assert PRIMARY in installed


def test_upgrade_package_upgrades_exactly_one_plugin(uv_env: UvToolEnv) -> None:
    """(b) ``--upgrade-package`` moves exactly one plugin; siblings stay pinned.

    The stand-in is seeded with an intentionally old, *unpinned* ``six`` (via
    ``--resolution lowest-direct``) alongside an exactly-pinned ``pyfiglet`` and
    a pinned primary. The engine's ``sase plugin update six`` command then
    upgrades only ``six`` — ``--upgrade-package`` overrides the seeded low
    resolution for its target while everything else is held at the reconstructed
    spec.
    """
    _install_base(
        uv_env,
        [
            f"{PRIMARY}==6.1",
            "--with",
            PLUGIN,
            "--with",
            OTHER_PLUGIN_PINNED,
            "--resolution",
            "lowest-direct",
        ],
    )
    before = uv_env.installed_versions()
    receipt = load_receipt(uv_env.receipt_path, primary_name=PRIMARY)

    changeset = uv_env.run(build_upgrade_packages(receipt, [PLUGIN], color="never"))

    # Exactly one package changed, and it is the upgrade of the targeted plugin.
    assert len(changeset.changes) == 1
    only = changeset.changes[0]
    assert only.name.lower() == PLUGIN
    assert only.kind is ChangeKind.UPGRADED
    assert only.old_version == before[PLUGIN]

    after = uv_env.installed_versions()
    assert after[PLUGIN] != before[PLUGIN], "the targeted plugin must move"
    assert after[OTHER_PLUGIN] == before[OTHER_PLUGIN], "an untargeted plugin must not"
    assert after[PRIMARY] == before[PRIMARY], "the primary must stay pinned"


def test_tool_upgrade_bumps_injected_plugin(uv_env: UvToolEnv) -> None:
    """(c) ``uv tool upgrade <tool>`` re-resolves the primary *and* its plugins.

    This is the assumption behind ``sase update`` (``uv tool upgrade sase``). The
    stand-in is seeded low via ``--resolution lowest-direct``, which uv *stores*
    as the tool's resolution strategy; a real ``uv tool install sase`` uses the
    default (highest) strategy, so the production ``uv tool upgrade sase`` re-
    resolves to the latest automatically. We pass ``--resolution highest`` here
    only to neutralize the test-only low seeding and reproduce that production
    behavior.
    """
    _install_base(
        uv_env,
        [PRIMARY_FLOOR, "--with", PLUGIN, "--resolution", "lowest-direct"],
    )
    before = uv_env.installed_versions()

    changeset = uv_env.run(
        [
            "uv",
            "tool",
            "upgrade",
            PRIMARY,
            "--resolution",
            "highest",
            "--color",
            "never",
        ]
    )

    bumped = {c.name.lower() for c in changeset.by_kind(ChangeKind.UPGRADED)}
    assert PLUGIN in bumped, "uv tool upgrade must re-resolve the injected plugin too"
    after = uv_env.installed_versions()
    assert after[PLUGIN] != before[PLUGIN]
    assert after[PRIMARY] != before[PRIMARY], (
        "the primary is re-resolved in the same shot"
    )


def test_editable_tool_upgrade_target_preserves_sources_and_bumps_dependency(
    uv_env: UvToolEnv,
    tmp_path: Path,
) -> None:
    """(d) A managed transitive target survives an all-editable receipt."""
    primary = tmp_path / "editable-primary"
    plugin = tmp_path / "editable-plugin"
    _write_local_package(
        primary,
        EDITABLE_PRIMARY,
        "0.1.0",
        dependencies=("six>=1,<2",),
        script_name="editable-update",
    )
    _write_local_package(plugin, EDITABLE_PLUGIN, "0.1.0")
    _install_base(
        uv_env,
        [
            "--editable",
            str(primary),
            "--with-editable",
            str(plugin),
        ],
    )
    python = uv_env.tool_dir / EDITABLE_PRIMARY / "bin" / "python"
    try:
        uv_env.run(
            [
                "uv",
                "pip",
                "install",
                "--python",
                str(python),
                "six==1.16.0",
                "--color",
                "never",
            ]
        )
        receipt = load_receipt(
            uv_env.receipt_path_for(EDITABLE_PRIMARY),
            primary_name=EDITABLE_PRIMARY,
        )
        overrides = write_editable_overrides(
            receipt.requirements,
            path=tmp_path / "editable-overrides.txt",
        )
        assert overrides is not None
        before = uv_env.installed_versions(EDITABLE_PRIMARY)
        changeset = uv_env.run(
            build_upgrade_packages(
                receipt,
                [PLUGIN],
                color="never",
                overrides=str(overrides),
            )
        )
    except UvCommandFailedError as exc:  # pragma: no cover - network dependent
        pytest.skip(f"uv could not exercise editable dependency update: {exc}")

    change = changeset.get(PLUGIN)
    assert change is not None
    assert change.kind is ChangeKind.UPGRADED
    assert change.old_version == "1.16.0"
    after = uv_env.installed_versions(EDITABLE_PRIMARY)
    assert after[PLUGIN] != before[PLUGIN]
    assert after[EDITABLE_PRIMARY] == before[EDITABLE_PRIMARY]
    assert after[EDITABLE_PLUGIN] == before[EDITABLE_PLUGIN]

    preserved = load_receipt(
        uv_env.receipt_path_for(EDITABLE_PRIMARY),
        primary_name=EDITABLE_PRIMARY,
    )
    assert preserved.primary.editable == str(primary)
    assert preserved.deduped_injected_plugins()[0].editable == str(plugin)


def test_uninstall_removes_throwaway_tool(uv_env: UvToolEnv) -> None:
    """The throwaway tool is fully removable — closes the install/upgrade loop."""
    _install_base(uv_env, [PRIMARY, "--with", PLUGIN])
    assert uv_env.receipt_path.is_file()

    uv_env.run(["uv", "tool", "uninstall", PRIMARY, "--color", "never"])
    assert not uv_env.receipt_path.exists()


def test_editable_overrides_neutralize_static_version_floor(
    tmp_path: Path,
) -> None:
    """A local editable override satisfies a dependent's too-high floor.

    This reproduces the dev-update failure mode with disposable local packages:
    the primary checkout's static pyproject version is lower than the plugin's
    declared floor, but an override containing ``-e <primary>`` makes uv resolve
    the local checkout anyway.
    """
    primary = tmp_path / "primary"
    plugin = tmp_path / "plugin"
    _write_local_package(primary, "override-primary", "0.1.0")
    _write_local_package(
        plugin,
        "override-plugin",
        "0.1.0",
        dependencies=("override-primary>=0.2.0",),
    )
    requirements = tmp_path / "requirements.in"
    requirements.write_text(f"-e {primary}\n-e {plugin}\n", encoding="utf-8")

    failed = _run_uv_pip_compile(requirements)
    assert failed.returncode != 0
    assert "override-primary" in failed.stderr

    overrides = tmp_path / "overrides.txt"
    overrides.write_text(f"-e {primary}\n", encoding="utf-8")
    succeeded = _run_uv_pip_compile(requirements, overrides=overrides)
    assert succeeded.returncode == 0, succeeded.stderr
    assert str(primary) in succeeded.stdout


def _write_local_package(
    path: Path,
    name: str,
    version: str,
    *,
    dependencies: Sequence[str] = (),
    script_name: str | None = None,
) -> None:
    path.mkdir()
    module = name.replace("-", "_")
    dependency_rows = "\n".join(f'    "{dependency}",' for dependency in dependencies)
    dependency_block = (
        f"dependencies = [\n{dependency_rows}\n]\n" if dependency_rows else ""
    )
    script_block = (
        f'\n[project.scripts]\n{script_name} = "{module}:main"\n'
        if script_name is not None
        else ""
    )
    (path / "pyproject.toml").write_text(
        f"""\
[build-system]
requires = ["hatchling>=1.27"]
build-backend = "hatchling.build"

[project]
name = "{name}"
version = "{version}"
{dependency_block}
{script_block}
""",
        encoding="utf-8",
    )
    package_dir = path / module
    package_dir.mkdir()
    body = "def main():\n    return 0\n" if script_name is not None else ""
    (package_dir / "__init__.py").write_text(body, encoding="utf-8")


def _run_uv_pip_compile(
    requirements: Path,
    *,
    overrides: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    argv = [
        "uv",
        "pip",
        "compile",
        str(requirements),
        "--color",
        "never",
    ]
    if overrides is not None:
        argv += ["--overrides", str(overrides)]
    return subprocess.run(argv, capture_output=True, text=True, check=False)
