from __future__ import annotations

import argparse
import json
import os
import runpy
import subprocess
import sys
from pathlib import Path
from typing import Any


import pytest

pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools/validate_test_environment"
FORCE_ENV = "SASE_TEST_SETUP_FORCE_REVALIDATE"
DEPENDENCY_GROUP_ERROR = 4
CORE_VERSION_ERROR = 1
CORE_VERSION_BEHIND_ERROR = 16
CORE_BINDINGS_ERROR = 2


def _load_tool() -> dict[str, Any]:
    return runpy.run_path(str(SCRIPT), run_name="validate_test_environment")


def _fingerprint_environment(tmp_path: Path) -> dict[str, Path]:
    """A minimal set of real files for every identity input, under ``tmp_path``."""
    venv_dir = tmp_path / "venv"
    (venv_dir / "lib/python3.14/site-packages").mkdir(parents=True)
    (venv_dir / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
    (venv_dir / "bin").mkdir()
    (venv_dir / "bin/python").write_bytes(b"fake-interpreter")
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[project]\nname = 'demo'\n", encoding="utf-8")
    uv_lock = tmp_path / "uv.lock"
    uv_lock.write_text("version = 1\n", encoding="utf-8")
    sase_core_dir = tmp_path / "sase-core"
    (sase_core_dir).mkdir()
    (sase_core_dir / "Cargo.toml").write_text(
        "[package]\nname = 'sase_core'\n", encoding="utf-8"
    )
    return {
        "venv_dir": venv_dir,
        "pyproject": pyproject,
        "uv_lock": uv_lock,
        "sase_core_dir": sase_core_dir,
    }


def _run_validator(
    *,
    venv_dir: Path,
    uv_lock: Path,
    cache_file: Path,
    group: str,
    force: bool = False,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop(FORCE_ENV, None)
    if force:
        env[FORCE_ENV] = "1"
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--venv-dir",
            str(venv_dir),
            "--pyproject",
            str(ROOT / "pyproject.toml"),
            "--uv-lock",
            str(uv_lock),
            "--sase-core-dir",
            str(ROOT / "sase/repos/linked/sase-core"),
            "--cache-file",
            str(cache_file),
            "--group",
            group,
        ],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


def _fake_venv(tmp_path: Path) -> Path:
    venv_dir = tmp_path / "venv"
    metadata_dir = venv_dir / "lib/python3.14/site-packages/demo-1.0.dist-info"
    metadata_dir.mkdir(parents=True)
    (metadata_dir / "METADATA").write_text(
        "Name: demo\nVersion: 1.0\n",
        encoding="utf-8",
    )
    (venv_dir / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
    return venv_dir


def test_cached_verdict_skips_validator_until_lockfile_changes(tmp_path: Path) -> None:
    venv_dir = _fake_venv(tmp_path)
    uv_lock = tmp_path / "uv.lock"
    uv_lock.write_text("version = 1\n", encoding="utf-8")
    cache_file = tmp_path / "validation-cache.json"
    group = "definitely-missing-setup-cache-test-group"

    first = _run_validator(
        venv_dir=venv_dir,
        uv_lock=uv_lock,
        cache_file=cache_file,
        group=group,
    )
    payload = json.loads(cache_file.read_text(encoding="utf-8"))
    payload["verdicts"][f"dependency-group:{group}"]["stderr"] = (
        "cached dependency verdict\n"
    )
    cache_file.write_text(json.dumps(payload), encoding="utf-8")
    second = _run_validator(
        venv_dir=venv_dir,
        uv_lock=uv_lock,
        cache_file=cache_file,
        group=group,
    )
    uv_lock.write_text("version = 2\n", encoding="utf-8")
    invalidated = _run_validator(
        venv_dir=venv_dir,
        uv_lock=uv_lock,
        cache_file=cache_file,
        group=group,
    )

    assert first.returncode == DEPENDENCY_GROUP_ERROR
    assert "unknown dependency group" in first.stderr
    assert second.returncode == DEPENDENCY_GROUP_ERROR
    assert second.stderr == "cached dependency verdict\n"
    assert invalidated.returncode == DEPENDENCY_GROUP_ERROR
    assert "unknown dependency group" in invalidated.stderr


def test_venv_metadata_change_and_force_env_revalidate(tmp_path: Path) -> None:
    venv_dir = _fake_venv(tmp_path)
    metadata = next(venv_dir.glob("lib/python*/site-packages/*.dist-info/METADATA"))
    uv_lock = tmp_path / "uv.lock"
    uv_lock.write_text("version = 1\n", encoding="utf-8")
    cache_file = tmp_path / "validation-cache.json"
    group = "definitely-missing-setup-cache-test-group"

    first = _run_validator(
        venv_dir=venv_dir,
        uv_lock=uv_lock,
        cache_file=cache_file,
        group=group,
    )
    metadata.write_text("Name: demo\nVersion: 2.0\n", encoding="utf-8")
    metadata_invalidated = _run_validator(
        venv_dir=venv_dir,
        uv_lock=uv_lock,
        cache_file=cache_file,
        group=group,
    )
    cached = _run_validator(
        venv_dir=venv_dir,
        uv_lock=uv_lock,
        cache_file=cache_file,
        group=group,
    )
    forced = _run_validator(
        venv_dir=venv_dir,
        uv_lock=uv_lock,
        cache_file=cache_file,
        group=group,
        force=True,
    )

    assert first.returncode == DEPENDENCY_GROUP_ERROR
    assert "unknown dependency group" in metadata_invalidated.stderr
    assert "unknown dependency group" in cached.stderr
    assert forced.returncode == DEPENDENCY_GROUP_ERROR
    assert "unknown dependency group" in forced.stderr
    payload = json.loads(cache_file.read_text(encoding="utf-8"))
    assert (
        payload["verdicts"][f"dependency-group:{group}"]["code"]
        == DEPENDENCY_GROUP_ERROR
    )


def test_fingerprint_inputs_covers_every_escalating_bucket(tmp_path: Path) -> None:
    tool = _load_tool()
    env = _fingerprint_environment(tmp_path)

    inputs = tool["_fingerprint_inputs"](**env)

    assert {
        "pyproject",
        "uv-lock",
        "venv-config",
        "core-cargo",
        "validator:core-version",
        "validator:core-bindings",
        "validator:dependency-group",
        "validator:editable-metadata",
        "environment-metadata",
        "extension",
        "python",
    } <= set(inputs)


def test_fingerprint_inputs_are_independent_per_bucket(tmp_path: Path) -> None:
    tool = _load_tool()
    env = _fingerprint_environment(tmp_path)
    before = tool["_fingerprint_inputs"](**env)

    env["pyproject"].write_text("[project]\nname = 'demo-renamed'\n", encoding="utf-8")
    after = tool["_fingerprint_inputs"](**env)

    assert after["pyproject"] != before["pyproject"]
    for key in before:
        if key != "pyproject":
            assert after[key] == before[key]


def test_input_fingerprint_composite_still_reflects_every_bucket(
    tmp_path: Path,
) -> None:
    """The validator's own cache key must keep invalidating on any input change."""
    tool = _load_tool()
    env = _fingerprint_environment(tmp_path)
    before = tool["_input_fingerprint"](**env)

    env["uv_lock"].write_text("version = 2\n", encoding="utf-8")

    assert tool["_input_fingerprint"](**env) != before


def test_extension_fingerprint_finds_the_nested_extension(tmp_path: Path) -> None:
    """`sase_core_rs` installs to a nested package dir, not flat in site-packages."""
    tool = _load_tool()
    env = _fingerprint_environment(tmp_path)
    site_packages = env["venv_dir"] / "lib/python3.14/site-packages"
    empty = tool["_fingerprint_inputs"](**env)

    package_dir = site_packages / "sase_core_rs"
    package_dir.mkdir()
    (package_dir / "sase_core_rs.abi3.so").write_bytes(b"binary-v1")

    populated = tool["_fingerprint_inputs"](**env)

    assert populated["extension"] != empty["extension"]
    for key in empty:
        if key != "extension":
            assert populated[key] == empty[key]


def test_extension_fingerprint_follows_editable_pth_target(tmp_path: Path) -> None:
    tool = _load_tool()
    env = _fingerprint_environment(tmp_path)
    site_packages = env["venv_dir"] / "lib/python3.14/site-packages"
    editable_source = tmp_path / "editable-core" / "python"
    (editable_source / "sase_core_rs").mkdir(parents=True)
    (site_packages / "sase_core_rs.pth").write_text(
        f"{editable_source}\n",
        encoding="utf-8",
    )
    before = tool["_fingerprint_inputs"](**env)

    (editable_source / "sase_core_rs" / "sase_core_rs.abi3.so").write_bytes(
        b"editable-binary-v1"
    )
    after = tool["_fingerprint_inputs"](**env)

    assert after["extension"] != before["extension"]
    for key in before:
        if key != "extension":
            assert after[key] == before[key]


def test_extension_fingerprint_is_content_based_not_stat_based(
    tmp_path: Path,
) -> None:
    """A rebuild that reproduces identical bytes must not read as a change."""
    tool = _load_tool()
    env = _fingerprint_environment(tmp_path)
    site_packages = env["venv_dir"] / "lib/python3.14/site-packages"
    package_dir = site_packages / "sase_core_rs"
    package_dir.mkdir()
    extension = package_dir / "sase_core_rs.abi3.so"
    extension.write_bytes(b"binary-v1")
    populated = tool["_fingerprint_inputs"](**env)

    os.utime(extension, (1_700_000_000, 1_700_000_000))
    touched = tool["_fingerprint_inputs"](**env)
    assert touched["extension"] == populated["extension"]

    extension.write_bytes(b"binary-v2")
    rebuilt = tool["_fingerprint_inputs"](**env)
    assert rebuilt["extension"] != populated["extension"]


def _write_stub_validator(tmp_path: Path, name: str, exit_code: int) -> Path:
    script = tmp_path / name
    script.write_text(
        f"#!/usr/bin/env python3\nraise SystemExit({exit_code})\n",
        encoding="utf-8",
    )
    return script


def _write_core_bindings_marker_validator(tmp_path: Path, marker: Path) -> Path:
    script = tmp_path / "stub-core-bindings-marker"
    script.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "from pathlib import Path",
                f"raise SystemExit(0 if Path({str(marker)!r}).exists() else 1)",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return script


def _core_check_namespace(
    env: dict[str, Path], *, cache_file: Path
) -> argparse.Namespace:
    return argparse.Namespace(
        venv_dir=env["venv_dir"],
        pyproject=env["pyproject"],
        uv_lock=env["uv_lock"],
        sase_core_dir=env["sase_core_dir"],
        cache_file=cache_file,
        check_core=True,
        check_editable=False,
        group=[],
    )


def test_core_version_behind_verdict_sets_bit_16_not_bit_1(tmp_path: Path) -> None:
    tool = _load_tool()
    env = _fingerprint_environment(tmp_path)
    tool["VALIDATOR_PATHS"]["core-version"] = _write_stub_validator(
        tmp_path, "stub-core-version-behind", 3
    )
    tool["VALIDATOR_PATHS"]["core-bindings"] = _write_stub_validator(
        tmp_path, "stub-core-bindings-ok", 0
    )
    namespace = _core_check_namespace(env, cache_file=tmp_path / "cache.json")

    result = tool["_validate"](namespace)

    assert result & CORE_VERSION_BEHIND_ERROR
    assert not result & CORE_VERSION_ERROR


def test_core_version_ahead_verdict_sets_bit_1_not_bit_16(tmp_path: Path) -> None:
    tool = _load_tool()
    env = _fingerprint_environment(tmp_path)
    tool["VALIDATOR_PATHS"]["core-version"] = _write_stub_validator(
        tmp_path, "stub-core-version-ahead", 4
    )
    tool["VALIDATOR_PATHS"]["core-bindings"] = _write_stub_validator(
        tmp_path, "stub-core-bindings-ok", 0
    )
    namespace = _core_check_namespace(env, cache_file=tmp_path / "cache.json")

    result = tool["_validate"](namespace)

    assert result & CORE_VERSION_ERROR
    assert not result & CORE_VERSION_BEHIND_ERROR


def test_editable_extension_rebuild_invalidates_cached_core_binding_failure(
    tmp_path: Path,
) -> None:
    tool = _load_tool()
    env = _fingerprint_environment(tmp_path)
    site_packages = env["venv_dir"] / "lib/python3.14/site-packages"
    editable_source = tmp_path / "editable-core" / "python"
    (editable_source / "sase_core_rs").mkdir(parents=True)
    (site_packages / "sase_core_rs.pth").write_text(
        f"{editable_source}\n",
        encoding="utf-8",
    )
    marker = tmp_path / "binding-ok"
    tool["VALIDATOR_PATHS"]["core-version"] = _write_stub_validator(
        tmp_path, "stub-core-version-ok", 0
    )
    tool["VALIDATOR_PATHS"]["core-bindings"] = _write_core_bindings_marker_validator(
        tmp_path, marker
    )
    namespace = _core_check_namespace(env, cache_file=tmp_path / "cache.json")

    failed = tool["_validate"](namespace)
    marker.touch()
    (editable_source / "sase_core_rs" / "sase_core_rs.abi3.so").write_bytes(
        b"editable-binary-v1"
    )
    rebuilt = tool["_validate"](namespace)

    assert failed == CORE_BINDINGS_ERROR
    assert rebuilt == 0


def test_cache_written_at_old_schema_version_is_rejected(tmp_path: Path) -> None:
    tool = _load_tool()
    assert tool["CACHE_SCHEMA_VERSION"] == 2
    cache_file = tmp_path / "cache.json"
    fingerprint = "deadbeef"
    cache_file.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "fingerprint": fingerprint,
                "verdicts": {
                    "dependency-group:demo": {
                        "code": DEPENDENCY_GROUP_ERROR,
                        "stdout": "",
                        "stderr": "stale schema verdict",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    verdicts = tool["_load_verdicts"](cache_file, fingerprint)

    assert verdicts == {}
