"""Tests for shipped ``sase init-skills`` source discovery."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.main import init_skills_handler
from sase.main.init_skills_handler import _get_target_path, handle_init_skills_command
from sase.xprompt.loader import get_sase_package_xprompts_dir
from sase.xprompt.loader_parsing import parse_yaml_front_matter
from tests.main.init_skills_handler_helpers import make_args


@pytest.mark.parametrize(
    ("skill_name", "expected_phrases"),
    [
        ("sase_artifact", ("sase artifact create -p", "--kind")),
        (
            "sase_agents_status",
            (
                "sase agents status -j",
                "artifacts_dir",
                "cite the artifact paths",
            ),
        ),
        (
            "sase_chats",
            (
                "sase chats list -j",
                "sase chats show",
                "/sase_agents_status",
                "draft/live",
            ),
        ),
        ("sase_notify", ("sase notify list -j", "sase notify show --id")),
    ],
)
def test_shipped_skill_source_is_discoverable_for_all_providers(
    skill_name: str,
    expected_phrases: tuple[str, ...],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Shipped skill sources with `skill: true` render to every provider."""
    src = get_sase_package_xprompts_dir() / "skills" / f"{skill_name}.md"
    assert src.is_file(), f"missing skill source: {src}"

    front_matter, body = parse_yaml_front_matter(src.read_text(encoding="utf-8"))
    assert front_matter is not None
    assert front_matter.get("name") == skill_name
    assert front_matter.get("skill") is True
    assert front_matter.get("description")
    assert body.strip(), "skill body must not be empty"
    for phrase in expected_phrases:
        assert phrase in body

    monkeypatch.setattr(init_skills_handler, "get_use_chezmoi", lambda: False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")

    with pytest.raises(SystemExit) as exc:
        handle_init_skills_command(make_args())
    assert exc.value.code == 0

    providers = [
        name
        for name, _ in __import__(
            "sase.llm_provider.registry", fromlist=["iter_plugins"]
        ).iter_plugins()
    ]
    assert providers, "expected at least one registered llm provider"

    for provider in providers:
        target = _get_target_path(provider, skill_name, use_chezmoi=False)
        assert target.exists(), f"{skill_name} not generated for provider {provider}"
        rendered = target.read_text(encoding="utf-8")
        for phrase in expected_phrases:
            assert phrase in rendered


@pytest.mark.parametrize("skill_name", ["sase_git_commit", "sase_hg_commit"])
def test_commit_skill_sources_do_not_reference_legacy_bead_flag(
    skill_name: str,
) -> None:
    """Commit skills should rely on SASE_BEAD_ID rather than a commit flag."""
    src = get_sase_package_xprompts_dir() / "skills" / f"{skill_name}.md"
    body = src.read_text(encoding="utf-8")
    assert "--bead-id" not in body
    assert "sase bead list --status=in_progress" not in body
