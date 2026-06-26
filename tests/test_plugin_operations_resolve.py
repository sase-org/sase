from __future__ import annotations

from sase.plugins.operations import resolve_install_spec

from ._plugin_operations_helpers import _catalog


def test_resolve_install_spec_catalog() -> None:
    spec = resolve_install_spec(_catalog(), "github")
    assert spec is not None
    assert spec.source == "catalog"
    assert spec.display_name == "github"
    assert spec.requirement.requirement_argument() == "sase-github"
    assert spec.normalized_name == "sase-github"


def test_resolve_install_spec_git_forces_repo_url() -> None:
    spec = resolve_install_spec(_catalog(), "github", git=True)
    assert spec is not None
    assert spec.source == "git"
    assert (
        spec.requirement.requirement_argument()
        == "git+https://github.com/sase-org/sase-github"
    )


def test_resolve_install_spec_passthrough_and_unknown() -> None:
    passthrough = resolve_install_spec(_catalog(), "sase-foo==1.2")
    assert passthrough is not None
    assert passthrough.source == "passthrough"
    assert resolve_install_spec(_catalog(), "nope") is None
