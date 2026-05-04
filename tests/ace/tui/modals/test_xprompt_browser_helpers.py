from pathlib import Path
from unittest.mock import patch

from sase.ace.tui.modals.xprompt_browser_helpers import classify_source


def test_classify_source_default_xprompts_builtin(tmp_path: Path) -> None:
    pkg_dir = tmp_path / "xprompts"
    default_dir = tmp_path / "default_xprompts"
    default_dir.mkdir()
    source = default_dir / "research_swarm.md"
    source.write_text("x")

    with (
        patch(
            "sase.ace.tui.modals.xprompt_browser_helpers.get_sase_package_xprompts_dir",
            return_value=pkg_dir,
        ),
        patch(
            "sase.ace.tui.modals.xprompt_browser_helpers."
            "get_sase_package_default_xprompts_dir",
            return_value=default_dir,
        ),
    ):
        category, display_path, is_editable = classify_source(str(source))

    assert category == "Built-in"
    assert display_path.endswith("default_xprompts/research_swarm.md")
    assert is_editable is True
