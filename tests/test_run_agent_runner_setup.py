from pathlib import Path
from unittest.mock import patch

from sase.axe.run_agent_runner_setup import (
    preprocess_prompt_xprompts,
    write_submitted_xprompt_artifact,
)


def test_write_submitted_xprompt_artifact_preserves_exact_prompt(
    tmp_path: Path,
) -> None:
    prompt = "  #alias\n\nbody\n  "

    path = write_submitted_xprompt_artifact(str(tmp_path), prompt)

    assert Path(path).name == "submitted_xprompt.md"
    assert Path(path).read_text(encoding="utf-8") == prompt


def test_submitted_xprompt_artifact_does_not_change_raw_xprompt_behavior(
    tmp_path: Path,
) -> None:
    submitted = "#alias original"
    resolved = "#real original"

    write_submitted_xprompt_artifact(str(tmp_path), submitted)
    with (
        patch("sase.xprompt.resolve_xprompt_aliases", return_value=resolved),
        patch("sase.xprompt._parsing.extract_vcs_workflow_tag", return_value=None),
        patch(
            "sase.xprompt.processor.process_xprompt_references", return_value="expanded"
        ),
    ):
        preprocess_prompt_xprompts(submitted, str(tmp_path))

    assert (tmp_path / "submitted_xprompt.md").read_text(encoding="utf-8") == submitted
    assert (tmp_path / "raw_xprompt.md").read_text(encoding="utf-8") == resolved
