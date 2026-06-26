"""Tests for uv-receipt parsing, the Requirement model, and reconstruction."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.uv_tool.errors import ReceiptError
from sase.uv_tool.receipt import (
    Requirement,
    ToolReceipt,
    load_receipt,
    parse_receipt,
)

# A real-world dev receipt: editable primary + plugins, plus bare index dups of
# two plugins (exactly what `uv tool install sase` records for a dev checkout).
_DEV_RECEIPT = """
[tool]
requirements = [
    { name = "sase", editable = "/home/u/sase" },
    { name = "sase-core-rs", editable = "/home/u/sase-core/py" },
    { name = "sase-github", editable = "/home/u/sase-github" },
    { name = "sase-telegram", editable = "/home/u/sase-telegram" },
    { name = "sase-github" },
    { name = "sase-telegram" },
]
entrypoints = [{ name = "sase", install-path = "/home/u/.local/bin/sase", from = "sase" }]
"""

# A plain PyPI install with specifiers, extras, and a git source.
_PYPI_RECEIPT = """
[tool]
requirements = [
    { name = "sase" },
    { name = "sase-github", specifier = "==0.4.0" },
    { name = "sase-extras", extras = ["socks", "fast"], specifier = ">=2,<3" },
    { name = "sase-edge", git = "https://github.com/acme/sase-edge", rev = "abc123" },
]
"""


# --- parsing -------------------------------------------------------------------


def test_parse_dev_receipt_identifies_primary_and_injected() -> None:
    receipt = parse_receipt(_DEV_RECEIPT)
    assert receipt.primary.name == "sase"
    assert receipt.primary.editable == "/home/u/sase"
    # injected preserves order and keeps the raw duplicates.
    assert [p.name for p in receipt.injected_plugins()] == [
        "sase-core-rs",
        "sase-github",
        "sase-telegram",
        "sase-github",
        "sase-telegram",
    ]


def test_deduped_injected_plugins_collapses_raw_duplicates() -> None:
    receipt = parse_receipt(_DEV_RECEIPT)
    # The raw set still preserves the duplicate entries uv wrote...
    assert [p.name for p in receipt.injected_plugins()] == [
        "sase-core-rs",
        "sase-github",
        "sase-telegram",
        "sase-github",
        "sase-telegram",
    ]
    # ...while the deduped view collapses them in receipt order (first wins).
    deduped = receipt.deduped_injected_plugins()
    assert [p.name for p in deduped] == [
        "sase-core-rs",
        "sase-github",
        "sase-telegram",
    ]
    assert all(p.editable is not None for p in deduped)


def test_parse_pypi_receipt_fields() -> None:
    receipt = parse_receipt(_PYPI_RECEIPT)
    by_name = {p.name: p for p in receipt.injected_plugins()}

    assert by_name["sase-github"].specifier == "==0.4.0"

    extras_req = by_name["sase-extras"]
    assert extras_req.extras == ("socks", "fast")
    assert extras_req.specifier == ">=2,<3"

    git_req = by_name["sase-edge"]
    assert git_req.git == "https://github.com/acme/sase-edge"
    assert git_req.git_ref == "abc123"


def test_parse_editable_true_with_path_field() -> None:
    text = """
    [tool]
    requirements = [
        { name = "sase" },
        { name = "sase-x", editable = true, path = "/p/x" },
    ]
    """
    plugin = parse_receipt(text).injected_plugins()[0]
    assert plugin.editable == "/p/x"


def test_parse_non_editable_path_becomes_url_passthrough() -> None:
    text = """
    [tool]
    requirements = [
        { name = "sase" },
        { name = "sase-x", path = "/wheels/sase_x.whl" },
    ]
    """
    plugin = parse_receipt(text).injected_plugins()[0]
    assert plugin.editable is None
    assert plugin.url == "/wheels/sase_x.whl"


def test_parse_git_ref_precedence_rev_over_tag_over_branch() -> None:
    text = """
    [tool]
    requirements = [
        { name = "sase" },
        { name = "sase-x", git = "https://g/x", tag = "v1", branch = "main" },
    ]
    """
    plugin = parse_receipt(text).injected_plugins()[0]
    assert plugin.git_ref == "v1"


def test_parse_skips_non_dict_requirement_entries() -> None:
    text = """
    [tool]
    requirements = [
        { name = "sase" },
        "junk",
        { name = "sase-x" },
    ]
    """
    receipt = parse_receipt(text)
    assert [p.name for p in receipt.injected_plugins()] == ["sase-x"]


def test_parse_receipt_with_only_primary_has_no_plugins() -> None:
    receipt = parse_receipt('[tool]\nrequirements = [{ name = "sase" }]\n')
    assert receipt.injected_plugins() == ()


@pytest.mark.parametrize(
    "text",
    [
        "{ not valid toml",
        "[other]\nx = 1\n",  # missing [tool]
        "[tool]\nx = 1\n",  # missing requirements
        "[tool]\nrequirements = []\n",  # empty requirements
        '[tool]\nrequirements = [{ specifier = "==1" }]\n',  # entry missing name
        '[tool]\nrequirements = [{ name = "other" }]\n',  # no primary
    ],
)
def test_parse_receipt_raises_receipt_error(text: str) -> None:
    with pytest.raises(ReceiptError):
        parse_receipt(text)


def test_parse_receipt_custom_primary_name() -> None:
    text = '[tool]\nrequirements = [{ name = "cowsay" }, { name = "extra" }]\n'
    receipt = parse_receipt(text, primary_name="cowsay")
    assert receipt.primary.name == "cowsay"
    assert [p.name for p in receipt.injected_plugins()] == ["extra"]


def test_load_receipt_reads_file(tmp_path: Path) -> None:
    path = tmp_path / "uv-receipt.toml"
    path.write_text(_DEV_RECEIPT)
    assert load_receipt(path).primary.name == "sase"


def test_load_receipt_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ReceiptError):
        load_receipt(tmp_path / "does-not-exist.toml")


# --- Requirement model ---------------------------------------------------------


def test_normalized_name_is_pep503() -> None:
    assert Requirement(name="Sase_GitHub").normalized_name == "sase-github"


def test_as_spec_renders_extras_and_specifier() -> None:
    req = Requirement(name="pkg", extras=("a", "b"), specifier=">=1,<2")
    assert req.as_spec() == "pkg[a,b]>=1,<2"


def test_requirement_argument_for_git_with_ref() -> None:
    req = Requirement(name="pkg", git="https://g/pkg", git_ref="v1")
    assert req.requirement_argument() == "git+https://g/pkg@v1"


def test_requirement_argument_for_git_without_ref() -> None:
    req = Requirement(name="pkg", git="https://g/pkg")
    assert req.requirement_argument() == "git+https://g/pkg"


def test_with_args_variants() -> None:
    assert Requirement(name="pkg", editable="/p").with_args() == [
        "--with-editable",
        "/p",
    ]
    assert Requirement(name="pkg").with_args() == ["--with", "pkg"]
    assert Requirement(name="pkg", url="/w.whl").with_args() == ["--with", "/w.whl"]


def test_primary_args_variants() -> None:
    assert Requirement(name="sase", editable="/p").primary_args() == [
        "--editable",
        "/p",
    ]
    assert Requirement(name="sase", specifier="==1.0").primary_args() == ["sase==1.0"]


def test_describe_summaries() -> None:
    assert Requirement(name="p", editable="/e").describe() == "editable /e"
    assert Requirement(name="p", git="https://g").describe() == "git https://g"
    assert Requirement(name="p", url="/u").describe() == "url /u"
    assert Requirement(name="p", specifier="==1").describe() == "p ==1"
    assert Requirement(name="p").describe() == "p (from the index)"


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ("sase-github", Requirement(name="sase-github")),
        ("sase-github==0.4.0", Requirement(name="sase-github", specifier="==0.4.0")),
        ("pkg>=1,<2", Requirement(name="pkg", specifier=">=1,<2")),
        ("pkg[a,b]", Requirement(name="pkg", extras=("a", "b"))),
        (
            "pkg[a]>=1",
            Requirement(name="pkg", extras=("a",), specifier=">=1"),
        ),
    ],
)
def test_from_spec_parses_index_requirements(spec: str, expected: Requirement) -> None:
    assert Requirement.from_spec(spec) == expected


def test_from_spec_git_is_passthrough_url() -> None:
    req = Requirement.from_spec("git+https://github.com/acme/sase-edge@main")
    assert req.url == "git+https://github.com/acme/sase-edge@main"
    assert req.name == "sase-edge"
    # Round-trips verbatim back onto --with.
    assert req.requirement_argument() == "git+https://github.com/acme/sase-edge@main"


def test_from_spec_url_is_passthrough() -> None:
    req = Requirement.from_spec("https://example.com/sase_x-1.0.whl")
    assert req.url == "https://example.com/sase_x-1.0.whl"


def test_from_spec_path_is_passthrough() -> None:
    assert Requirement.from_spec("./local/plugin").url == "./local/plugin"


def test_from_spec_empty_raises() -> None:
    with pytest.raises(ValueError):
        Requirement.from_spec("   ")


# --- reconstruction ------------------------------------------------------------


def test_reconstruct_dedupes_and_warns_on_conflict() -> None:
    recon = parse_receipt(_DEV_RECEIPT).reconstruct()
    names = [p.name for p in recon.plugins]
    # Duplicates collapsed; editable entries kept (first occurrence wins).
    assert names == ["sase-core-rs", "sase-github", "sase-telegram"]
    assert all(p.editable is not None for p in recon.plugins)
    assert len(recon.warnings) == 2
    assert "sase-github" in recon.warnings[0]
    assert "editable" in recon.warnings[0]


def test_reconstruct_identical_duplicate_is_silent() -> None:
    text = """
    [tool]
    requirements = [
        { name = "sase" },
        { name = "sase-x" },
        { name = "sase-x" },
    ]
    """
    recon = parse_receipt(text).reconstruct()
    assert [p.name for p in recon.plugins] == ["sase-x"]
    assert recon.warnings == ()


def test_with_added_appends_new_plugin() -> None:
    recon = parse_receipt(_PYPI_RECEIPT).with_added("sase-amd")
    assert recon.added == Requirement(name="sase-amd")
    assert "sase-amd" in [p.name for p in recon.plugins]


def test_with_added_existing_name_dedupes() -> None:
    # Adding an index spec when an editable already exists warns, keeps editable.
    recon = parse_receipt(_DEV_RECEIPT).with_added("sase-github==9.9")
    github = [p for p in recon.plugins if p.name == "sase-github"]
    assert len(github) == 1
    assert github[0].editable is not None


def test_with_added_accepts_requirement_object() -> None:
    req = Requirement(name="sase-amd", specifier=">=1")
    recon = parse_receipt(_PYPI_RECEIPT).with_added(req)
    assert recon.added is req


def test_with_upgraded_records_target_without_changing_membership() -> None:
    receipt = parse_receipt(_PYPI_RECEIPT)
    recon = receipt.with_upgraded("sase-github")
    assert recon.upgrade_targets == ("sase-github",)
    assert [p.name for p in recon.plugins] == [
        p.name for p in receipt.reconstruct().plugins
    ]


def test_is_injected_normalizes() -> None:
    receipt = parse_receipt(_PYPI_RECEIPT)
    assert receipt.is_injected("Sase_GitHub")
    assert not receipt.is_injected("nope")


def test_tool_receipt_is_frozen() -> None:
    receipt = ToolReceipt(primary=Requirement(name="sase"))
    with pytest.raises(AttributeError):
        receipt.primary = Requirement(name="other")  # type: ignore[misc]
