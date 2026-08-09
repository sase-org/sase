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


def _pyproject_text(specifier: str = ">=0.21.3,<0.22.0") -> str:
    return f"""
[project]
dependencies = [
    "jinja2",
    "sase-core-rs{specifier}",
    "schedule",
]
""".lstrip()


def _lock_text(version: str = "0.21.3", specifier: str = ">=0.21.3,<0.22.0") -> str:
    wheel_lines = "\n".join(
        f'    {{ url = "https://files.example/sase_core_rs-{version}-cp312-abi3-{platform}.whl", hash = "sha256:{index}", size = {index} }},'
        for index, platform in enumerate(PLATFORMS, start=1)
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


def _write_project(
    root: Path,
    *,
    specifier: str = ">=0.21.3,<0.22.0",
    lock_version: str = "0.21.3",
) -> tuple[Path, Path]:
    pyproject = root / "pyproject.toml"
    uv_lock = root / "uv.lock"
    pyproject.write_text(_pyproject_text(specifier), encoding="utf-8")
    uv_lock.write_text(_lock_text(lock_version, specifier), encoding="utf-8")
    (root / "README.md").write_text("# fixture\n", encoding="utf-8")
    return pyproject, uv_lock


def _successful_lock_runner(tool: ModuleType):
    def _runner(project_dir: Path, target: object) -> subprocess.CompletedProcess[str]:
        specifier = tool.dependency_specifier_for_floor(target)
        (project_dir / "uv.lock").write_text(
            _lock_text(target.raw, specifier),
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


def test_unexpected_lock_diff_restores_files(
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
    assert "uv.lock changed 8 line(s)" in capsys.readouterr().err


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
