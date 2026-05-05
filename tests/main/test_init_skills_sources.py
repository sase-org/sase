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
    ("skill_name", "expected_examples"),
    [
        ("sase_chats", ("sase chats list -j", "sase chats show")),
        ("sase_notify", ("sase notify list -j", "sase notify show --id")),
        (
            "sase_artifact",
            (
                "sase artifact list -j",
                "sase artifact show -j",
                "sase artifact graph -j",
                "sase artifact doctor -j",
            ),
        ),
    ],
)
def test_shipped_skill_source_is_discoverable_for_all_providers(
    skill_name: str,
    expected_examples: tuple[str, ...],
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
    for example in expected_examples:
        assert example in body

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
        for example in expected_examples:
            assert example in rendered
