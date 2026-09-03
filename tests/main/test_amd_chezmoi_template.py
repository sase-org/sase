"""Unit coverage for chezmoi AMD H1 template emission."""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from sase.amd._chezmoi_template import (
    render_chezmoi_h1_template,
    unescape_chezmoi_literals,
)


def test_render_chezmoi_h1_template_orders_branches_and_keeps_else() -> None:
    content = "# fallback title\n\nBody with {{ braces }}.\n"
    rendered, error = render_chezmoi_h1_template(
        content,
        titles=(
            ("athena", "athena title"),
            ("apollo", "apollo title"),
        ),
        fallback_title="fallback title",
    )

    assert error is None
    assert rendered is not None
    first_line, remainder = rendered.split("\n", 1)
    assert first_line == (
        '{{ if eq .chezmoi.hostname "apollo" }}# apollo title'
        '{{ else if eq .chezmoi.hostname "athena" }}# athena title'
        "{{ else }}# fallback title{{ end }}"
    )
    assert remainder == '\nBody with {{ "{{" }} braces }}.\n'
    assert unescape_chezmoi_literals(remainder) == "\nBody with {{ braces }}.\n"
    assert rendered.count("\n") == content.count("\n")


def test_render_chezmoi_h1_template_requires_h1_and_titles() -> None:
    rendered, error = render_chezmoi_h1_template(
        "no heading\n",
        titles=(("apollo", "apollo title"),),
        fallback_title="fallback",
    )
    assert rendered is None
    assert error is not None
    assert "no H1 title line" in error

    rendered, error = render_chezmoi_h1_template(
        "# title\n",
        titles=(),
        fallback_title="fallback",
    )
    assert rendered is None
    assert error is not None
    assert "at least one hostname title" in error


@pytest.mark.skipif(shutil.which("chezmoi") is None, reason="chezmoi not installed")
def test_chezmoi_execute_template_renders_per_hostname() -> None:
    content = "# fallback title\n\nBody.\n"
    rendered, error = render_chezmoi_h1_template(
        content,
        titles=(
            ("apollo", "apollo title"),
            ("athena", "athena title"),
        ),
        fallback_title="fallback title",
    )
    assert error is None
    assert rendered is not None

    def _execute(hostname: str) -> str:
        result = subprocess.run(
            [
                "chezmoi",
                "execute-template",
                "--override-data",
                json.dumps({"chezmoi": {"hostname": hostname}}),
            ],
            input=rendered,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        return result.stdout

    assert _execute("apollo").startswith("# apollo title\n")
    assert _execute("athena").startswith("# athena title\n")
    assert _execute("other-host").startswith("# fallback title\n")
    assert _execute("apollo").endswith("Body.\n")
