"""Receipt-reading parity: the engine twin matches ``sase.uv_tool.receipt``."""

from __future__ import annotations

from pathlib import Path

import pytest

import tests._sase_install_testkit as kit
from tests._sase_install_testkit import install_state
from sase.uv_tool import receipt as sase_receipt


LIVE_SHAPED_RECEIPT = """\
[tool]
requirements = [
    { name = "sase", editable = "/durable/sase" },
    { name = "bugyi-chops", editable = "/durable/bugyi-chops" },
    { name = "sase-github", editable = "/durable/sase-github" },
]
overrides = [
    { name = "sase-core-rs" },
    { name = "sase", editable = "/durable/sase" },
]
entrypoints = [
    { name = "sase", install-path = "/bin/sase", from = "sase" },
]

[tool.options]
index = [{ url = "https://pypi.org/simple/", explicit = false, default = true }]
"""

MIXED_RECEIPT = """\
[tool]
requirements = [
    { name = "sase", specifier = "==0.17.1" },
    { name = "sase-github", specifier = ">=0.2.5" },
    { name = "sase-telegram", git = "https://github.com/sase-org/sase-telegram", rev = "abc123" },
    { name = "docs-plugin", path = "/opt/plugins/docs-plugin" },
    { name = "local-dev", editable = true, path = "/durable/local-dev" },
    { name = "sase-github", specifier = ">=0.2.5" },
]
"""

EXTRAS_RECEIPT = """\
[tool]
requirements = [
    { name = "sase", editable = "/durable/sase" },
    { name = "with-extras", extras = ["a", "b"], specifier = ">=1.0,<2.0" },
]
"""


def _fields(req: object) -> tuple[object, ...]:
    return (
        req.name,  # type: ignore[attr-defined]
        req.extras,  # type: ignore[attr-defined]
        req.specifier,  # type: ignore[attr-defined]
        req.editable,  # type: ignore[attr-defined]
        req.git,  # type: ignore[attr-defined]
        req.git_ref,  # type: ignore[attr-defined]
        req.url,  # type: ignore[attr-defined]
    )


@pytest.mark.parametrize("text", [LIVE_SHAPED_RECEIPT, MIXED_RECEIPT, EXTRAS_RECEIPT])
def test_parse_matches_sase_on_fixture_receipts(text: str) -> None:
    expected = sase_receipt.parse_receipt(text)
    observed = install_state.parse_receipt_text(text)
    assert observed.primary.normalized_name == expected.primary.normalized_name
    assert _fields(observed.primary) == _fields(expected.primary)
    assert len(observed.plugins) == len(expected.plugins)
    for got, want in zip(observed.plugins, expected.plugins, strict=True):
        assert _fields(got) == _fields(want)
        assert got.normalized_name == want.normalized_name


@pytest.mark.parametrize(
    "text",
    [
        "not toml [[",
        "[other]\nrequirements = []\n",
        "[tool]\nrequirements = []\n",
        "[tool]\nrequirements = [{ name = 'other' }]\n",
        "[tool]\nrequirements = [{ specifier = '==1.0' }]\n",
    ],
)
def test_parse_errors_match_sase(text: str) -> None:
    with pytest.raises(sase_receipt.ReceiptError):
        sase_receipt.parse_receipt(text)
    with pytest.raises(install_state.ReceiptError):
        install_state.parse_receipt_text(text)


def test_requirement_rendering_matches_sase() -> None:
    specs = [
        "sase-github>=0.2.5",
        "sase-github[extra-a,extra-b]>=0.2.5",
        "sase==0.17.1",
        "git+https://github.com/sase-org/sase-telegram@abc123",
        "/opt/plugins/docs-plugin",
        "./relative-plugin",
    ]
    for spec in specs:
        want = sase_receipt.Requirement.from_spec(spec)
        got = install_state.InstallRequirement.from_spec(spec)
        assert _fields(got) == _fields(want), spec
        assert got.with_args() == want.with_args(), spec
        assert got.primary_args() == want.primary_args(), spec
        assert got.describe() == want.describe(), spec
        assert got.as_spec() == want.as_spec(), spec


def test_state_snapshot_reads_live_shaped_env(tmp_path: Path) -> None:
    checkout = kit.make_checkout(tmp_path)
    tool_dir, bin_dir = kit.make_tool_env(
        tmp_path,
        host=("editable", str(checkout)),
        plugins=[("sase-github", "editable", str(tmp_path / "sase-github"))],
        core=("local", "0.37.0"),
        checkout=checkout,
    )
    state = install_state.read_state(tool_dir=tool_dir, bin_dir=bin_dir)
    assert state.env_exists
    assert state.mode == "dev"
    assert state.python_version == "3.14.7"
    assert state.receipt is not None
    assert state.receipt.primary.editable == str(checkout)
    assert state.lsp_exists
    host = state.find_dist("sase")
    assert host is not None and host.editable_path == str(checkout)
    core = state.find_dist("SASE-CORE-RS")
    assert core is not None and core.version == "0.37.0"


def test_state_snapshot_missing_env_is_none(tmp_path: Path) -> None:
    state = install_state.read_state(
        tool_dir=tmp_path / "nope", bin_dir=tmp_path / "nope" / "bin"
    )
    assert not state.env_exists
    assert state.mode == "none"
    assert state.receipt is None
    assert state.python_version is None
    assert state.dists == ()


def test_state_modes() -> None:
    assert (
        install_state.classify_mode(
            env_exists=False, host_editable=False, any_editable=False
        )
        == "none"
    )
    assert (
        install_state.classify_mode(
            env_exists=True, host_editable=True, any_editable=True
        )
        == "dev"
    )
    assert (
        install_state.classify_mode(
            env_exists=True, host_editable=False, any_editable=True
        )
        == "mixed"
    )
    assert (
        install_state.classify_mode(
            env_exists=True, host_editable=False, any_editable=False
        )
        == "pypi"
    )
