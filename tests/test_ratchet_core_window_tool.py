from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import urllib.error
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

import pytest


pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "ratchet_core_window"
PLATFORMS = (
    "macosx_10_12_x86_64.macosx_11_0_arm64.macosx_10_12_universal2",
    "manylinux_2_28_aarch64",
    "manylinux_2_28_x86_64",
    "win_amd64",
)


def _load_tool() -> ModuleType:
    loader = SourceFileLoader("ratchet_core_window_tool", str(SCRIPT))
    spec = importlib.util.spec_from_file_location(
        "ratchet_core_window_tool",
        SCRIPT,
        loader=loader,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def tool() -> ModuleType:
    return _load_tool()


def _sdist(version: str, *, yanked: bool = False) -> dict[str, object]:
    return {
        "filename": f"sase_core_rs-{version}.tar.gz",
        "packagetype": "sdist",
        "yanked": yanked,
    }


def _wheel(version: str, platform: str, *, yanked: bool = False) -> dict[str, object]:
    return {
        "filename": f"sase_core_rs-{version}-cp312-abi3-{platform}.whl",
        "packagetype": "bdist_wheel",
        "yanked": yanked,
    }


def _complete_files(version: str, *, yanked: bool = False) -> list[dict[str, object]]:
    return [_sdist(version, yanked=yanked)] + [
        _wheel(version, platform, yanked=yanked) for platform in PLATFORMS
    ]


def _metadata(*versions: str) -> dict[str, object]:
    return {"releases": {version: _complete_files(version) for version in versions}}


def _pyproject_text(
    specifier: str = ">=0.21.3,<0.22.0",
    *,
    version: str | None = None,
) -> str:
    version_line = f'version = "{version}"\n' if version is not None else ""
    return f"""
[project]
{version_line}dependencies = [
    "jinja2",
    "sase-core-rs{specifier}",
    "schedule",
]
""".lstrip()


def _lock_text(version: str = "0.21.3", specifier: str = ">=0.21.3,<0.22.0") -> str:
    return _lock_text_for_platforms(version, specifier, platforms=PLATFORMS)


def _lock_text_for_platforms(
    version: str,
    specifier: str,
    *,
    platforms: tuple[str, ...],
) -> str:
    wheel_lines = "\n".join(
        f'    {{ url = "https://files.example/sase_core_rs-{version}-cp312-abi3-{platform}.whl", hash = "sha256:{index}", size = {index} }},'
        for index, platform in enumerate(platforms, start=1)
    )
    return f"""
version = 1

[[package]]
name = "sase"
version = "0.16.0"
dependencies = [
    {{ name = "sase-core-rs" }},
]

[package.metadata]
requires-dist = [
    {{ name = "sase-core-rs", specifier = "{specifier}" }},
]

[[package]]
name = "sase-core-rs"
version = "{version}"
source = {{ registry = "https://pypi.org/simple/" }}
sdist = {{ url = "https://files.example/sase_core_rs-{version}.tar.gz", hash = "sha256:sdist", size = 100 }}
wheels = [
{wheel_lines}
]
""".lstrip()


# Live Publish failure (run 32532695440) refused asttokens because uv rewrote a
# top-level lock-format key outside version/sdist/wheels. asttokens 3.0.1 on
# master omits `dependencies`; uv may emit an empty list (or other lock-format
# keys in the same family) while bumping sase-core-rs.
_ASTTOKENS_DEPENDENCIES_FIELD = """\
dependencies = []
"""


def _asttokens_package(
    version: str,
    digest: str,
    *,
    extra_lines: str = "",
) -> str:
    extra = extra_lines
    if extra and not extra.endswith("\n"):
        extra += "\n"
    return f"""
[[package]]
name = "asttokens"
version = "{version}"
source = {{ registry = "https://pypi.org/simple/" }}
{extra}sdist = {{ url = "https://files.example/asttokens-{version}.tar.gz", hash = "sha256:{digest}-sdist", size = 10 }}
wheels = [
    {{ url = "https://files.example/asttokens-{version}-py3-none-any.whl", hash = "sha256:{digest}-wheel", size = 10 }},
]
""".lstrip()


def _lock_text_with_asttokens(
    version: str,
    specifier: str,
    *,
    asttokens_version: str = "3.0.0",
    asttokens_digest: str = "old",
    asttokens_direct: bool = False,
    asttokens_extra_lines: str = "",
    project_version: str = "0.16.0",
) -> str:
    header, rest = _lock_text(version, specifier).split("\n\n", 1)
    if project_version != "0.16.0":
        rest = rest.replace(
            'version = "0.16.0"',
            f'version = "{project_version}"',
            1,
        )
    if asttokens_direct:
        rest = rest.replace(
            '    { name = "sase-core-rs" },',
            '    { name = "asttokens" },\n    { name = "sase-core-rs" },',
            1,
        )
    return (
        f"{header}\n\n"
        f"{_asttokens_package(asttokens_version, asttokens_digest, extra_lines=asttokens_extra_lines)}\n"
        f"{rest}"
    )


def _write_project(
    root: Path,
    *,
    specifier: str = ">=0.21.3,<0.22.0",
    lock_version: str = "0.21.3",
    project_version: str | None = None,
) -> tuple[Path, Path]:
    pyproject = root / "pyproject.toml"
    uv_lock = root / "uv.lock"
    pyproject.write_text(
        _pyproject_text(specifier, version=project_version),
        encoding="utf-8",
    )
    uv_lock.write_text(_lock_text(lock_version, specifier), encoding="utf-8")
    (root / "README.md").write_text("# fixture\n", encoding="utf-8")
    return pyproject, uv_lock


def _write_project_with_asttokens(
    root: Path,
    *,
    asttokens_direct: bool = False,
    asttokens_version: str = "3.0.0",
    asttokens_extra_lines: str = "",
) -> tuple[Path, Path]:
    pyproject = root / "pyproject.toml"
    uv_lock = root / "uv.lock"
    specifier = ">=0.21.3,<0.22.0"
    pyproject.write_text(_pyproject_text(specifier), encoding="utf-8")
    uv_lock.write_text(
        _lock_text_with_asttokens(
            "0.21.3",
            specifier,
            asttokens_direct=asttokens_direct,
            asttokens_version=asttokens_version,
            asttokens_extra_lines=asttokens_extra_lines,
        ),
        encoding="utf-8",
    )
    (root / "README.md").write_text("# fixture\n", encoding="utf-8")
    return pyproject, uv_lock


def _successful_lock_runner(
    tool: ModuleType,
    *,
    platforms: tuple[str, ...] = PLATFORMS,
):
    def _runner(project_dir: Path, target: object) -> subprocess.CompletedProcess[str]:
        specifier = tool.dependency_specifier_for_floor(target)
        (project_dir / "uv.lock").write_text(
            _lock_text_for_platforms(target.raw, specifier, platforms=platforms),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(["uv", "lock"], 0, "", "")

    return _runner


def _asttokens_refresh_lock_runner(
    tool: ModuleType,
    *,
    asttokens_version: str = "3.0.1",
    asttokens_digest: str = "new",
    asttokens_direct: bool = False,
    asttokens_extra_lines: str = "",
    project_version: str = "0.16.0",
):
    def _runner(project_dir: Path, target: object) -> subprocess.CompletedProcess[str]:
        specifier = tool.dependency_specifier_for_floor(target)
        (project_dir / "uv.lock").write_text(
            _lock_text_with_asttokens(
                target.raw,
                specifier,
                asttokens_direct=asttokens_direct,
                asttokens_digest=asttokens_digest,
                asttokens_version=asttokens_version,
                asttokens_extra_lines=asttokens_extra_lines,
                project_version=project_version,
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(["uv", "lock"], 0, "", "")

    return _runner


def test_ceiling_policy_is_single_function(tool: ModuleType) -> None:
    assert tool.ceiling_specifier_for_floor(tool.parse_version("0.21.3")) == "<0.22.0"
    assert tool.ceiling_specifier_for_floor(tool.parse_version("1.4.5")) == "<2.0.0"


def test_select_target_uses_version_order_and_skips_incomplete_releases(
    tool: ModuleType,
) -> None:
    metadata = {
        "releases": {
            "0.9.2": _complete_files("0.9.2"),
            "0.10.0": _complete_files("0.10.0"),
            "0.11.0rc1": _complete_files("0.11.0rc1"),
            "0.11.0": _complete_files("0.11.0")[:-1],
            "0.12.0": _complete_files("0.12.0", yanked=True),
        }
    }

    target = tool.select_target_version(metadata, tool.parse_version("0.9.2"))

    assert target.raw == "0.10.0"


def test_report_only_prints_exact_diff_without_writing(
    tool: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pyproject, uv_lock = _write_project(tmp_path)
    before_pyproject = pyproject.read_text(encoding="utf-8")
    before_uv_lock = uv_lock.read_text(encoding="utf-8")
    monkeypatch.setattr(
        tool, "fetch_pypi_metadata", lambda: _metadata("0.21.3", "0.22.0")
    )
    monkeypatch.setattr(tool, "_run_uv_lock", _successful_lock_runner(tool))

    code = tool.main(
        [
            "--pyproject",
            str(pyproject),
            "--uv-lock",
            str(uv_lock),
            "--report-only",
        ]
    )

    assert code == tool.EXIT_RATCHET
    assert pyproject.read_text(encoding="utf-8") == before_pyproject
    assert uv_lock.read_text(encoding="utf-8") == before_uv_lock
    out = capsys.readouterr().out
    assert "sase-core-rs ratchet 0.21.3 -> 0.22.0" in out
    assert "--- a/pyproject.toml" in out
    assert "--- a/uv.lock" in out
    assert '+    "sase-core-rs>=0.22.0,<0.23.0",' in out
    assert '+version = "0.22.0"' in out


def test_check_reports_pending_without_running_uv_lock(
    tool: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pyproject, uv_lock = _write_project(tmp_path)
    monkeypatch.setattr(
        tool, "fetch_pypi_metadata", lambda: _metadata("0.21.3", "0.22.0")
    )

    def _unexpected_lock_runner(
        _project_dir: Path,
        _target: object,
    ) -> subprocess.CompletedProcess[str]:
        raise AssertionError("check mode must not refresh uv.lock")

    monkeypatch.setattr(tool, "_run_uv_lock", _unexpected_lock_runner)

    code = tool.main(
        ["--pyproject", str(pyproject), "--uv-lock", str(uv_lock), "--check"]
    )

    assert code == tool.EXIT_RATCHET
    assert "pending" in capsys.readouterr().out


def test_default_mode_applies_pyproject_and_guarded_lock_update(
    tool: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pyproject, uv_lock = _write_project(tmp_path)
    monkeypatch.setattr(
        tool, "fetch_pypi_metadata", lambda: _metadata("0.21.3", "0.22.0")
    )
    monkeypatch.setattr(tool, "_run_uv_lock", _successful_lock_runner(tool))

    code = tool.main(["--pyproject", str(pyproject), "--uv-lock", str(uv_lock)])

    assert code == tool.EXIT_RATCHET
    assert '    "sase-core-rs>=0.22.0,<0.23.0",' in pyproject.read_text(
        encoding="utf-8"
    )
    assert 'version = "0.22.0"' in uv_lock.read_text(encoding="utf-8")
    assert "applied" in capsys.readouterr().out


def test_default_mode_accepts_expanded_core_artifact_set(
    tool: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyproject, uv_lock = _write_project(tmp_path)
    monkeypatch.setattr(
        tool, "fetch_pypi_metadata", lambda: _metadata("0.21.3", "0.22.0")
    )
    expanded_platforms = PLATFORMS + ("manylinux_2_28_ppc64le",)
    monkeypatch.setattr(
        tool,
        "_run_uv_lock",
        _successful_lock_runner(tool, platforms=expanded_platforms),
    )

    code = tool.main(["--pyproject", str(pyproject), "--uv-lock", str(uv_lock)])

    assert code == tool.EXIT_RATCHET
    assert "sase_core_rs-0.22.0-cp312-abi3-manylinux_2_28_ppc64le.whl" in (
        uv_lock.read_text(encoding="utf-8")
    )


def test_default_mode_rejects_transitive_lock_refresh_and_restores_files(
    tool: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pyproject, uv_lock = _write_project_with_asttokens(tmp_path)
    before_pyproject = pyproject.read_text(encoding="utf-8")
    before_uv_lock = uv_lock.read_text(encoding="utf-8")
    monkeypatch.setattr(
        tool, "fetch_pypi_metadata", lambda: _metadata("0.21.3", "0.22.0")
    )
    monkeypatch.setattr(tool, "_run_uv_lock", _asttokens_refresh_lock_runner(tool))

    code = tool.main(["--pyproject", str(pyproject), "--uv-lock", str(uv_lock)])

    assert code == tool.EXIT_COULD_NOT_DETERMINE
    assert pyproject.read_text(encoding="utf-8") == before_pyproject
    assert uv_lock.read_text(encoding="utf-8") == before_uv_lock
    assert "uv.lock changed unrelated package asttokens" in capsys.readouterr().err


def test_reconciliation_mode_allows_transitive_lock_refresh(
    tool: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pyproject, uv_lock = _write_project_with_asttokens(tmp_path)
    monkeypatch.setattr(
        tool, "fetch_pypi_metadata", lambda: _metadata("0.21.3", "0.22.0")
    )
    monkeypatch.setattr(tool, "_run_uv_lock", _asttokens_refresh_lock_runner(tool))

    code = tool.main(
        [
            "--allow-transitive-lock-refresh",
            "--pyproject",
            str(pyproject),
            "--uv-lock",
            str(uv_lock),
        ]
    )

    assert code == tool.EXIT_RATCHET
    assert '    "sase-core-rs>=0.22.0,<0.23.0",' in pyproject.read_text(
        encoding="utf-8"
    )
    lock_text = uv_lock.read_text(encoding="utf-8")
    assert 'name = "asttokens"\nversion = "3.0.1"' in lock_text
    assert "sha256:new-sdist" in lock_text
    out = capsys.readouterr().out
    assert "allowed transitive uv.lock refresh: asttokens 3.0.0 -> 3.0.1" in out
    assert "applied" in out


def test_default_mode_rejects_asttokens_lock_format_field_refresh(
    tool: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pyproject, uv_lock = _write_project_with_asttokens(tmp_path)
    before_pyproject = pyproject.read_text(encoding="utf-8")
    before_uv_lock = uv_lock.read_text(encoding="utf-8")
    monkeypatch.setattr(
        tool, "fetch_pypi_metadata", lambda: _metadata("0.21.3", "0.22.0")
    )
    monkeypatch.setattr(
        tool,
        "_run_uv_lock",
        _asttokens_refresh_lock_runner(
            tool,
            asttokens_extra_lines=_ASTTOKENS_DEPENDENCIES_FIELD,
        ),
    )

    code = tool.main(["--pyproject", str(pyproject), "--uv-lock", str(uv_lock)])

    assert code == tool.EXIT_COULD_NOT_DETERMINE
    assert pyproject.read_text(encoding="utf-8") == before_pyproject
    assert uv_lock.read_text(encoding="utf-8") == before_uv_lock
    assert "uv.lock changed unrelated package asttokens" in capsys.readouterr().err


def test_reconciliation_mode_allows_asttokens_lock_format_field_refresh(
    tool: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pyproject, uv_lock = _write_project_with_asttokens(tmp_path)
    monkeypatch.setattr(
        tool, "fetch_pypi_metadata", lambda: _metadata("0.21.3", "0.22.0")
    )
    monkeypatch.setattr(
        tool,
        "_run_uv_lock",
        _asttokens_refresh_lock_runner(
            tool,
            asttokens_extra_lines=_ASTTOKENS_DEPENDENCIES_FIELD,
        ),
    )

    code = tool.main(
        [
            "--allow-transitive-lock-refresh",
            "--pyproject",
            str(pyproject),
            "--uv-lock",
            str(uv_lock),
        ]
    )

    assert code == tool.EXIT_RATCHET
    lock_text = uv_lock.read_text(encoding="utf-8")
    assert "dependencies = []" in lock_text
    assert 'name = "asttokens"\nversion = "3.0.1"' in lock_text
    out = capsys.readouterr().out
    assert "allowed transitive uv.lock refresh: asttokens 3.0.0 -> 3.0.1" in out
    assert "applied" in out


def test_reconciliation_mode_allows_project_lock_version_to_follow_pyproject(
    tool: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyproject, uv_lock = _write_project(tmp_path, project_version="0.17.0")
    monkeypatch.setattr(
        tool, "fetch_pypi_metadata", lambda: _metadata("0.21.3", "0.22.0")
    )

    def _runner(project_dir: Path, target: object) -> subprocess.CompletedProcess[str]:
        specifier = tool.dependency_specifier_for_floor(target)
        lock_text = _lock_text_for_platforms(target.raw, specifier, platforms=PLATFORMS)
        lock_text = lock_text.replace('version = "0.16.0"', 'version = "0.17.0"', 1)
        (project_dir / "uv.lock").write_text(lock_text, encoding="utf-8")
        return subprocess.CompletedProcess(["uv", "lock"], 0, "", "")

    monkeypatch.setattr(tool, "_run_uv_lock", _runner)

    code = tool.main(["--pyproject", str(pyproject), "--uv-lock", str(uv_lock)])

    assert code == tool.EXIT_RATCHET
    lock_text = uv_lock.read_text(encoding="utf-8")
    assert 'name = "sase"\nversion = "0.17.0"' in lock_text
    assert 'specifier = ">=0.22.0,<0.23.0"' in lock_text


def test_reconciliation_mode_rejects_non_pypi_source_rewrite(
    tool: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pyproject, uv_lock = _write_project_with_asttokens(tmp_path)
    before_pyproject = pyproject.read_text(encoding="utf-8")
    before_uv_lock = uv_lock.read_text(encoding="utf-8")
    monkeypatch.setattr(
        tool, "fetch_pypi_metadata", lambda: _metadata("0.21.3", "0.22.0")
    )

    def _runner(project_dir: Path, target: object) -> subprocess.CompletedProcess[str]:
        specifier = tool.dependency_specifier_for_floor(target)
        lock_text = _lock_text_with_asttokens(target.raw, specifier).replace(
            'source = { registry = "https://pypi.org/simple/" }',
            'source = { path = "vendor/asttokens" }',
            1,
        )
        (project_dir / "uv.lock").write_text(lock_text, encoding="utf-8")
        return subprocess.CompletedProcess(["uv", "lock"], 0, "", "")

    monkeypatch.setattr(tool, "_run_uv_lock", _runner)

    code = tool.main(
        [
            "--allow-transitive-lock-refresh",
            "--pyproject",
            str(pyproject),
            "--uv-lock",
            str(uv_lock),
        ]
    )

    assert code == tool.EXIT_COULD_NOT_DETERMINE
    assert pyproject.read_text(encoding="utf-8") == before_pyproject
    assert uv_lock.read_text(encoding="utf-8") == before_uv_lock
    assert "is not a PyPI registry package" in capsys.readouterr().err


def test_reconciliation_mode_rejects_unexpected_transitive_metadata_field(
    tool: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pyproject, uv_lock = _write_project_with_asttokens(tmp_path)
    before_pyproject = pyproject.read_text(encoding="utf-8")
    before_uv_lock = uv_lock.read_text(encoding="utf-8")
    monkeypatch.setattr(
        tool, "fetch_pypi_metadata", lambda: _metadata("0.21.3", "0.22.0")
    )
    monkeypatch.setattr(
        tool,
        "_run_uv_lock",
        _asttokens_refresh_lock_runner(
            tool,
            asttokens_extra_lines="metadata = { requires-dist = [] }\n",
        ),
    )

    code = tool.main(
        [
            "--allow-transitive-lock-refresh",
            "--pyproject",
            str(pyproject),
            "--uv-lock",
            str(uv_lock),
        ]
    )

    assert code == tool.EXIT_COULD_NOT_DETERMINE
    assert pyproject.read_text(encoding="utf-8") == before_pyproject
    assert uv_lock.read_text(encoding="utf-8") == before_uv_lock
    err = capsys.readouterr().err
    assert "changed fields outside" in err
    assert "metadata" in err


def test_idempotent_when_declared_floor_is_newest(
    tool: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pyproject, uv_lock = _write_project(tmp_path)
    monkeypatch.setattr(tool, "fetch_pypi_metadata", lambda: _metadata("0.21.3"))

    def _unexpected_lock_runner(
        _project_dir: Path,
        _target: object,
    ) -> subprocess.CompletedProcess[str]:
        raise AssertionError("idempotent mode must not refresh uv.lock")

    monkeypatch.setattr(tool, "_run_uv_lock", _unexpected_lock_runner)

    code = tool.main(["--pyproject", str(pyproject), "--uv-lock", str(uv_lock)])

    assert code == tool.EXIT_OK
    assert "already matches" in capsys.readouterr().out


def test_downgrade_is_refused_without_writing(
    tool: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pyproject, uv_lock = _write_project(tmp_path)
    before_pyproject = pyproject.read_text(encoding="utf-8")
    before_uv_lock = uv_lock.read_text(encoding="utf-8")
    monkeypatch.setattr(tool, "fetch_pypi_metadata", lambda: _metadata("0.21.3"))
    monkeypatch.setattr(
        tool,
        "select_target_version",
        lambda _metadata, _current_floor: tool.parse_version("0.20.0"),
    )

    code = tool.main(["--pyproject", str(pyproject), "--uv-lock", str(uv_lock)])

    assert code == tool.EXIT_COULD_NOT_DETERMINE
    assert pyproject.read_text(encoding="utf-8") == before_pyproject
    assert uv_lock.read_text(encoding="utf-8") == before_uv_lock
    assert "refusing to lower" in capsys.readouterr().err


def test_network_failure_is_distinguishable_and_non_destructive(
    tool: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pyproject, uv_lock = _write_project(tmp_path)
    before_pyproject = pyproject.read_text(encoding="utf-8")
    before_uv_lock = uv_lock.read_text(encoding="utf-8")

    def _fetch() -> dict[str, object]:
        raise tool.PyPIError("network unavailable")

    monkeypatch.setattr(tool, "fetch_pypi_metadata", _fetch)

    code = tool.main(["--pyproject", str(pyproject), "--uv-lock", str(uv_lock)])

    assert code == tool.EXIT_COULD_NOT_DETERMINE
    assert pyproject.read_text(encoding="utf-8") == before_pyproject
    assert uv_lock.read_text(encoding="utf-8") == before_uv_lock
    assert "network unavailable" in capsys.readouterr().err


def test_unrelated_package_movement_restores_files(
    tool: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pyproject, uv_lock = _write_project(tmp_path)
    before_pyproject = pyproject.read_text(encoding="utf-8")
    before_uv_lock = uv_lock.read_text(encoding="utf-8")
    monkeypatch.setattr(
        tool, "fetch_pypi_metadata", lambda: _metadata("0.21.3", "0.22.0")
    )

    def _bad_lock_runner(
        project_dir: Path,
        target: object,
    ) -> subprocess.CompletedProcess[str]:
        specifier = tool.dependency_specifier_for_floor(target)
        bad_lock = _lock_text(target.raw, specifier).replace(
            'name = "sase"',
            'name = "sase-renamed"',
            1,
        )
        (project_dir / "uv.lock").write_text(bad_lock, encoding="utf-8")
        return subprocess.CompletedProcess(["uv", "lock"], 0, "", "")

    monkeypatch.setattr(tool, "_run_uv_lock", _bad_lock_runner)

    code = tool.main(["--pyproject", str(pyproject), "--uv-lock", str(uv_lock)])

    assert code == tool.EXIT_COULD_NOT_DETERMINE
    assert pyproject.read_text(encoding="utf-8") == before_pyproject
    assert uv_lock.read_text(encoding="utf-8") == before_uv_lock
    assert (
        "package order or package set changed unexpectedly" in capsys.readouterr().err
    )


def test_reconciliation_mode_rejects_package_set_changes(
    tool: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pyproject, uv_lock = _write_project_with_asttokens(tmp_path)
    before_pyproject = pyproject.read_text(encoding="utf-8")
    before_uv_lock = uv_lock.read_text(encoding="utf-8")
    monkeypatch.setattr(
        tool, "fetch_pypi_metadata", lambda: _metadata("0.21.3", "0.22.0")
    )

    def _bad_lock_runner(
        project_dir: Path,
        target: object,
    ) -> subprocess.CompletedProcess[str]:
        specifier = tool.dependency_specifier_for_floor(target)
        bad_lock = _lock_text_with_asttokens(target.raw, specifier).replace(
            'name = "asttokens"',
            'name = "asttokens-renamed"',
            1,
        )
        (project_dir / "uv.lock").write_text(bad_lock, encoding="utf-8")
        return subprocess.CompletedProcess(["uv", "lock"], 0, "", "")

    monkeypatch.setattr(tool, "_run_uv_lock", _bad_lock_runner)

    code = tool.main(
        [
            "--allow-transitive-lock-refresh",
            "--pyproject",
            str(pyproject),
            "--uv-lock",
            str(uv_lock),
        ]
    )

    assert code == tool.EXIT_COULD_NOT_DETERMINE
    assert pyproject.read_text(encoding="utf-8") == before_pyproject
    assert uv_lock.read_text(encoding="utf-8") == before_uv_lock
    assert (
        "package order or package set changed unexpectedly" in capsys.readouterr().err
    )


def test_reconciliation_mode_rejects_direct_dependency_package_refresh(
    tool: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pyproject, uv_lock = _write_project_with_asttokens(
        tmp_path,
        asttokens_direct=True,
    )
    before_pyproject = pyproject.read_text(encoding="utf-8")
    before_uv_lock = uv_lock.read_text(encoding="utf-8")
    monkeypatch.setattr(
        tool, "fetch_pypi_metadata", lambda: _metadata("0.21.3", "0.22.0")
    )
    monkeypatch.setattr(
        tool,
        "_run_uv_lock",
        _asttokens_refresh_lock_runner(tool, asttokens_direct=True),
    )

    code = tool.main(
        [
            "--allow-transitive-lock-refresh",
            "--pyproject",
            str(pyproject),
            "--uv-lock",
            str(uv_lock),
        ]
    )

    assert code == tool.EXIT_COULD_NOT_DETERMINE
    assert pyproject.read_text(encoding="utf-8") == before_pyproject
    assert uv_lock.read_text(encoding="utf-8") == before_uv_lock
    assert "direct dependency package asttokens" in capsys.readouterr().err


def test_reconciliation_mode_rejects_direct_dependency_diff_restores_files(
    tool: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pyproject, uv_lock = _write_project(tmp_path)
    before_pyproject = pyproject.read_text(encoding="utf-8")
    before_uv_lock = uv_lock.read_text(encoding="utf-8")
    monkeypatch.setattr(
        tool, "fetch_pypi_metadata", lambda: _metadata("0.21.3", "0.22.0")
    )

    def _bad_lock_runner(
        project_dir: Path,
        target: object,
    ) -> subprocess.CompletedProcess[str]:
        specifier = tool.dependency_specifier_for_floor(target)
        bad_lock = _lock_text(target.raw, specifier).replace(
            '{ name = "sase-core-rs" },',
            '{ name = "sase-core-rs", specifier = ">=999" },',
            1,
        )
        (project_dir / "uv.lock").write_text(bad_lock, encoding="utf-8")
        return subprocess.CompletedProcess(["uv", "lock"], 0, "", "")

    monkeypatch.setattr(tool, "_run_uv_lock", _bad_lock_runner)

    code = tool.main(
        [
            "--allow-transitive-lock-refresh",
            "--pyproject",
            str(pyproject),
            "--uv-lock",
            str(uv_lock),
        ]
    )

    assert code == tool.EXIT_COULD_NOT_DETERMINE
    assert pyproject.read_text(encoding="utf-8") == before_pyproject
    assert uv_lock.read_text(encoding="utf-8") == before_uv_lock
    assert "package sase changed outside" in capsys.readouterr().err


def test_core_package_still_refuses_extra_lock_format_fields(
    tool: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pyproject, uv_lock = _write_project(tmp_path)
    before_pyproject = pyproject.read_text(encoding="utf-8")
    before_uv_lock = uv_lock.read_text(encoding="utf-8")
    monkeypatch.setattr(
        tool, "fetch_pypi_metadata", lambda: _metadata("0.21.3", "0.22.0")
    )

    def _runner(project_dir: Path, target: object) -> subprocess.CompletedProcess[str]:
        specifier = tool.dependency_specifier_for_floor(target)
        lock_text = _lock_text_for_platforms(target.raw, specifier, platforms=PLATFORMS)
        lock_text = lock_text.replace(
            f'version = "{target.raw}"\nsource = {{ registry = "https://pypi.org/simple/" }}',
            f'version = "{target.raw}"\nsource = {{ registry = "https://pypi.org/simple/" }}\ndependencies = []',
            1,
        )
        (project_dir / "uv.lock").write_text(lock_text, encoding="utf-8")
        return subprocess.CompletedProcess(["uv", "lock"], 0, "", "")

    monkeypatch.setattr(tool, "_run_uv_lock", _runner)

    code = tool.main(
        [
            "--allow-transitive-lock-refresh",
            "--pyproject",
            str(pyproject),
            "--uv-lock",
            str(uv_lock),
        ]
    )

    assert code == tool.EXIT_COULD_NOT_DETERMINE
    assert pyproject.read_text(encoding="utf-8") == before_pyproject
    assert uv_lock.read_text(encoding="utf-8") == before_uv_lock
    err = capsys.readouterr().err
    assert "sase-core-rs package changed fields other than" in err
    assert "dependencies" in err


class _Response:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def test_pypi_fetch_retries_transient_failures(tool: ModuleType) -> None:
    seen: list[tuple[str, float]] = []
    sleeps: list[float] = []
    payload = _metadata("0.21.3")

    def _urlopen(url: str, *, timeout: float) -> _Response:
        seen.append((url, timeout))
        if len(seen) < 3:
            raise urllib.error.URLError("temporary failure")
        return _Response(payload)

    assert (
        tool.fetch_pypi_metadata(
            urlopen_fn=_urlopen,
            sleep_fn=sleeps.append,
            attempts=3,
        )
        == payload
    )
    assert seen == [
        (tool.PYPI_URL, tool.PYPI_TIMEOUT_SECONDS),
        (tool.PYPI_URL, tool.PYPI_TIMEOUT_SECONDS),
        (tool.PYPI_URL, tool.PYPI_TIMEOUT_SECONDS),
    ]
    assert sleeps == [0.5, 1.0]
