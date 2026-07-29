from __future__ import annotations

import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]


def _load_validate_changelog() -> ModuleType:
    script = ROOT / "tools" / "validate_changelog"
    loader = SourceFileLoader("validate_changelog_tool", str(script))
    spec = importlib.util.spec_from_file_location(
        "validate_changelog_tool",
        script,
        loader=loader,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_changelog(tmp_path: Path, contents: str) -> Path:
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(contents, encoding="utf-8")
    return changelog


def test_repo_changelog_passes() -> None:
    validator = _load_validate_changelog()

    assert validator.validate_changelog()


def test_unreleased_heading_fails(tmp_path: Path) -> None:
    validator = _load_validate_changelog()
    changelog = _write_changelog(
        tmp_path,
        "# Changelog\n\n## Unreleased\n",
    )

    assert not validator.validate_changelog(changelog)


def test_stray_second_level_heading_fails(tmp_path: Path) -> None:
    validator = _load_validate_changelog()
    changelog = _write_changelog(
        tmp_path,
        "# Changelog\n\n## Some Heading\n",
    )

    assert not validator.validate_changelog(changelog)


def test_malformed_version_heading_fails(tmp_path: Path) -> None:
    validator = _load_validate_changelog()
    changelog = _write_changelog(
        tmp_path,
        "# Changelog\n\n"
        "## [1.2.3](https://github.com/sase-org/sase/compare/v1.2.2...v1.2.3)\n",
    )

    assert not validator.validate_changelog(changelog)


def test_generated_changelog_passes(tmp_path: Path) -> None:
    validator = _load_validate_changelog()
    changelog = _write_changelog(
        tmp_path,
        "# Changelog\n\n"
        "## [1.2.3](https://github.com/sase-org/sase/compare/v1.2.2...v1.2.3) (2026-07-29)\n\n"
        "### Features\n\n"
        "* add a feature\n\n"
        "## [1.2.2](https://github.com/sase-org/sase/compare/v1.2.1...v1.2.2) (2026-07-28)\n\n"
        "### Bug Fixes\n\n"
        "* fix a bug\n",
    )

    assert validator.validate_changelog(changelog)


def test_heading_inside_fenced_code_block_passes(tmp_path: Path) -> None:
    validator = _load_validate_changelog()
    changelog = _write_changelog(
        tmp_path,
        "# Changelog\n\n"
        "## [1.2.3](https://github.com/sase-org/sase/compare/v1.2.2...v1.2.3) (2026-07-29)\n\n"
        "### Documentation\n\n"
        "```markdown\n"
        "## Unreleased\n"
        "```\n",
    )

    assert validator.validate_changelog(changelog)
