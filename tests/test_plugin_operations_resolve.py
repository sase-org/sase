from __future__ import annotations

from sase.plugins.operations import resolve_install_spec
from sase.plugins.pypi_source import ProjectAvailability

from ._plugin_operations_helpers import _all_available, _all_missing, _catalog


def test_resolve_install_spec_catalog() -> None:
    spec = resolve_install_spec(_catalog(), "github", availability_fn=_all_available)
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


def test_resolve_install_spec_git_never_probes_availability() -> None:
    def _explode(_dist_name: str) -> ProjectAvailability:
        raise AssertionError("forced --git must not probe PyPI")

    spec = resolve_install_spec(
        _catalog(), "github", git=True, availability_fn=_explode
    )
    assert spec is not None
    assert spec.source == "git"


def test_resolve_install_spec_passthrough_and_unknown() -> None:
    passthrough = resolve_install_spec(_catalog(), "sase-foo==1.2")
    assert passthrough is not None
    assert passthrough.source == "passthrough"
    assert resolve_install_spec(_catalog(), "nope") is None


def test_resolve_install_spec_falls_back_to_git_on_definitive_missing() -> None:
    spec = resolve_install_spec(_catalog(), "github", availability_fn=_all_missing)
    assert spec is not None
    assert spec.source == "git"
    assert (
        spec.requirement.requirement_argument()
        == "git+https://github.com/sase-org/sase-github"
    )


def test_resolve_install_spec_keeps_index_on_unavailable_probe() -> None:
    def _unavailable(_dist_name: str) -> ProjectAvailability:
        return ProjectAvailability.UNAVAILABLE

    spec = resolve_install_spec(_catalog(), "github", availability_fn=_unavailable)
    assert spec is not None
    assert spec.source == "catalog"


def test_resolve_install_spec_offline_never_probes_and_keeps_index() -> None:
    def _explode(_dist_name: str) -> ProjectAvailability:
        raise AssertionError("--offline must never probe PyPI")

    spec = resolve_install_spec(
        _catalog(), "github", offline=True, availability_fn=_explode
    )
    assert spec is not None
    assert spec.source == "catalog"
