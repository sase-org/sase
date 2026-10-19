"""Core-ensure rule: newest complete published core containing the source pin."""

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
SCRIPT = ROOT / "tools" / "_release_core.py"
PIN = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

WORKFLOW = """\
name: Release-plz
env:
  EXPECTED_DIST_SUFFIXES: |
    manylinux_2_28_x86_64.whl
    manylinux_2_28_aarch64.whl
    universal2.whl
    win_amd64.whl
    .tar.gz
"""

PLATFORMS = (
    "macosx_10_12_x86_64.macosx_11_0_arm64.macosx_10_12_universal2",
    "manylinux_2_28_aarch64",
    "manylinux_2_28_x86_64",
    "win_amd64",
)


def _load_tool() -> ModuleType:
    loader = SourceFileLoader("release_core_tool", str(SCRIPT))
    spec = importlib.util.spec_from_file_location(
        "release_core_tool",
        SCRIPT,
        loader=loader,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclasses (3.14) resolve annotations via sys.modules[cls.__module__].
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


def _metadata(releases: dict[str, list[dict[str, object]]]) -> dict[str, object]:
    return {"releases": releases}


def _ensure(
    tool: ModuleType,
    metadata: dict[str, object],
    *,
    pin: str = PIN,
    compare: dict[str, str] | None = None,
    workflow: str | Exception = WORKFLOW,
    default_status: str = "ahead",
) -> object:
    compare_map = compare or {}

    def _compare(candidate_pin: str, version: str) -> str:
        assert candidate_pin == pin
        return compare_map.get(version, default_status)

    def _workflow(version: str) -> str:
        del version
        if isinstance(workflow, Exception):
            raise workflow
        return workflow

    return tool.ensure_core(
        pin,
        pypi_metadata=metadata,
        compare_fn=_compare,
        workflow_fn=_workflow,
    )


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
    payload = _metadata({"0.21.3": _complete_files("0.21.3")})

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


def test_ensure_core_picks_newest_complete_version_containing_pin(
    tool: ModuleType,
) -> None:
    metadata = _metadata(
        {
            "0.10.0": _complete_files("0.10.0"),
            "0.11.0": _complete_files("0.11.0"),
            "0.12.0": _complete_files("0.12.0"),
        }
    )

    result = _ensure(
        tool,
        metadata,
        compare={"0.12.0": "behind", "0.11.0": "ahead", "0.10.0": "identical"},
    )

    assert isinstance(result, tool.Pinned)
    assert result.version == "0.11.0"
    assert result.typed().startswith("PINNED(0.11.0, files=")
    assert any(name.endswith(".tar.gz") for name in result.files)


def test_ensure_core_skips_incomplete_newest_version(tool: ModuleType) -> None:
    incomplete = _complete_files("0.12.0")[:-1]
    metadata = _metadata(
        {
            "0.11.0": _complete_files("0.11.0"),
            "0.12.0": incomplete,
        }
    )

    result = _ensure(tool, metadata, default_status="ahead")

    assert isinstance(result, tool.Pinned)
    assert result.version == "0.11.0"


def test_ensure_core_treats_yanked_file_as_incomplete(tool: ModuleType) -> None:
    yanked_newest = _complete_files("0.12.0")
    yanked_newest[0] = _sdist("0.12.0", yanked=True)
    metadata = _metadata(
        {
            "0.11.0": _complete_files("0.11.0"),
            "0.12.0": yanked_newest,
        }
    )

    result = _ensure(tool, metadata, default_status="ahead")

    assert isinstance(result, tool.Pinned)
    assert result.version == "0.11.0"


def test_ensure_core_skips_tags_without_suffix_block(
    tool: ModuleType,
) -> None:
    metadata = _metadata(
        {
            "0.10.0": _complete_files("0.10.0"),
            "0.11.0": _complete_files("0.11.0"),
        }
    )

    def _workflow(version: str) -> str:
        if version == "0.10.0":
            return "name: Release-plz\n"
        return WORKFLOW

    result = tool.ensure_core(
        PIN,
        pypi_metadata=metadata,
        compare_fn=lambda _pin, _version: "behind",
        workflow_fn=_workflow,
    )

    assert isinstance(result, tool.CoreLag)
    assert result.newest_complete == "0.11.0"


def test_ensure_core_returns_core_lag_when_no_containing_version(
    tool: ModuleType,
) -> None:
    metadata = _metadata(
        {
            "0.10.0": _complete_files("0.10.0"),
            "0.11.0": _complete_files("0.11.0"),
        }
    )

    result = _ensure(tool, metadata, default_status="behind")

    assert isinstance(result, tool.CoreLag)
    assert result.pin == PIN
    assert result.newest_complete == "0.11.0"
    assert result.typed() == f"CORE_LAG(pin={PIN}, newest_complete=0.11.0)"


def test_ensure_core_raises_on_unreadable_compare(tool: ModuleType) -> None:
    metadata = _metadata({"0.11.0": _complete_files("0.11.0")})

    def _compare(_pin: str, _version: str) -> str:
        raise tool.CoreEnsureError("unreadable compare boom")

    with pytest.raises(tool.CoreEnsureError, match="unreadable compare boom"):
        tool.ensure_core(
            PIN,
            pypi_metadata=metadata,
            compare_fn=_compare,
            workflow_fn=lambda _version: WORKFLOW,
        )


def test_ensure_core_raises_on_unreadable_workflow(tool: ModuleType) -> None:
    metadata = _metadata({"0.11.0": _complete_files("0.11.0")})

    def _workflow(_version: str) -> str:
        raise tool.CoreEnsureError("missing workflow")

    with pytest.raises(tool.CoreEnsureError, match="missing workflow"):
        tool.ensure_core(
            PIN,
            pypi_metadata=metadata,
            compare_fn=lambda _pin, _version: "ahead",
            workflow_fn=_workflow,
        )


def test_ensure_core_raises_on_unknown_compare_status(tool: ModuleType) -> None:
    metadata = _metadata({"0.11.0": _complete_files("0.11.0")})

    with pytest.raises(tool.CoreEnsureError, match="unknown status"):
        _ensure(tool, metadata, default_status="sideways")


def test_ensure_core_raises_on_unreadable_source_pin(tool: ModuleType) -> None:
    with pytest.raises(tool.CoreEnsureError, match="unreadable source pin"):
        tool.ensure_core(
            "not-a-sha",
            pypi_metadata=_metadata({"0.11.0": _complete_files("0.11.0")}),
        )


def test_ensure_core_falls_back_to_local_git(tool: ModuleType, tmp_path: Path) -> None:
    repo = tmp_path / "sase-core"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "SASE Test"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    tracked = repo / "README"
    tracked.write_text("one\n", encoding="utf-8")
    subprocess.run(["git", "add", "README"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "first"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    pin = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True
    ).strip()
    tracked.write_text("two\n", encoding="utf-8")
    subprocess.run(
        ["git", "commit", "-am", "second"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "tag", "v0.11.0"], cwd=repo, check=True, capture_output=True)

    def _compare(_pin: str, _version: str) -> str:
        raise tool.CoreEnsureNetworkError("github down")

    result = tool.ensure_core(
        pin,
        pypi_metadata=_metadata({"0.11.0": _complete_files("0.11.0")}),
        compare_fn=_compare,
        workflow_fn=lambda _version: WORKFLOW,
        git_dir=repo,
    )

    assert isinstance(result, tool.Pinned)
    assert result.version == "0.11.0"


def test_read_source_pin_rejects_empty_file(tool: ModuleType, tmp_path: Path) -> None:
    path = tmp_path / "sase-core-revision.txt"
    path.write_text("\n", encoding="utf-8")
    with pytest.raises(tool.CoreEnsureError, match="unreadable source pin"):
        tool.read_source_pin(path)


def test_parse_json_object_strips_ansi_color(tool: ModuleType) -> None:
    colored = '\x1b[1;37m{\x1b[m\n  \x1b[1;34m"status"\x1b[m: \x1b[32m"ahead"\x1b[m\n}'
    assert tool._parse_json_object(colored) == {"status": "ahead"}
    assert tool._parse_json_object("") is None
    assert tool._parse_json_object("[1]") is None
