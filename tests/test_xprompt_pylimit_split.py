"""Structural tests for the bundled ``#sase/pylimit_split`` xprompt workflow.

These tests pin the shape of ``xprompts/pylimit_split.yml`` after Phase 2 of
the chop-visibility plan: the workflow should consist of a single hidden
Python step that builds a multi-prompt and hands it to
``launch_agent_from_cwd()``.  They also exercise the embedded Python by
extracting and running it under monkey-patched ``subprocess`` and launcher
shims, without spawning any real agents.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sase.agent.multi_prompt import parse_multi_prompt
from sase.xprompt.workflow_loader import _load_workflow_from_file


@pytest.fixture
def pylimit_workflow_path() -> Path:
    here = Path(__file__).resolve().parent.parent
    return here / "xprompts" / "pylimit_split.yml"


def test_workflow_has_single_hidden_python_step(pylimit_workflow_path: Path) -> None:
    """The workflow is one hidden python step that captures `launched`."""
    wf = _load_workflow_from_file(pylimit_workflow_path)
    assert wf is not None
    assert len(wf.steps) == 1

    step = wf.steps[0]
    assert step.is_python_step()
    assert step.hidden is True
    assert step.for_loop is None
    assert step.python is not None

    # Sanity check the body actually drives the documented launch path.
    assert "launch_agent_from_cwd" in step.python
    assert "build_wait_chained_multi_prompt" in step.python


def _run_step_python(
    step_python: str,
    *,
    pylimit_outputs: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> list[str]:
    """Execute the workflow step body in-process with mocked side effects.

    Returns the list of prompts handed to ``launch_agent_from_cwd``.
    """
    captured: list[str] = []

    def fake_run(cmd, **_kwargs):  # type: ignore[no-untyped-def]  # noqa: ARG001
        tree = cmd[1]
        return MagicMock(stdout=pylimit_outputs.get(tree, ""), returncode=0)

    def fake_launch(prompt, *_args, **_kwargs):  # type: ignore[no-untyped-def]  # noqa: ARG001
        captured.append(prompt)
        return MagicMock()

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr("sase.agent.launcher.launch_agent_from_cwd", fake_launch)

    rendered = step_python.replace("{{ limits }}", "1000 850 700")
    exec(  # noqa: S102 - test executes its own controlled snippet
        compile(rendered, "<pylimit_split-step>", "exec"),
        {"print": lambda *_a, **_k: None},  # noqa: ARG005
    )
    return captured


def test_step_no_files_does_not_launch(
    pylimit_workflow_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When pylimit reports no offenders, the step must not launch any agent."""
    wf = _load_workflow_from_file(pylimit_workflow_path)
    assert wf is not None
    captured = _run_step_python(
        wf.steps[0].python or "",
        pylimit_outputs={"src": "", "tests": "  \n  "},
        monkeypatch=monkeypatch,
    )
    assert captured == []


def test_step_two_files_launches_chained_multi_prompt(
    pylimit_workflow_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two offenders -> single launch with a 2-segment %wait-chained prompt."""
    wf = _load_workflow_from_file(pylimit_workflow_path)
    assert wf is not None

    captured = _run_step_python(
        wf.steps[0].python or "",
        pylimit_outputs={"src": "src/foo.py\nsrc/bar.py\n", "tests": ""},
        monkeypatch=monkeypatch,
    )

    assert len(captured) == 1
    parsed = parse_multi_prompt(captured[0])
    assert len(parsed.segments) == 2

    assert "%wait" not in parsed.segments[0]
    assert parsed.segments[1].startswith("%wait")

    assert "#sase/pysplit:src/foo.py" in parsed.segments[0]
    assert "#sase/pysplit:src/bar.py" in parsed.segments[1]
    for seg in parsed.segments:
        assert "#gh:sase" in seg
        assert "%approve" in seg


def test_step_dedups_files_across_trees(
    pylimit_workflow_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A path appearing in both src/ and tests/ output produces one segment."""
    wf = _load_workflow_from_file(pylimit_workflow_path)
    assert wf is not None

    captured = _run_step_python(
        wf.steps[0].python or "",
        pylimit_outputs={
            "src": "src/dup.py\n",
            "tests": "src/dup.py\ntests/only.py\n",
        },
        monkeypatch=monkeypatch,
    )

    assert len(captured) == 1
    parsed = parse_multi_prompt(captured[0])
    assert len(parsed.segments) == 2
    assert "#sase/pysplit:src/dup.py" in parsed.segments[0]
    assert "#sase/pysplit:tests/only.py" in parsed.segments[1]
