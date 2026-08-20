"""CLI contract coverage for examples in generated artifact memory."""

from __future__ import annotations

import shlex

import pytest

from sase.main.parser import create_parser
from sase.mdtemplates import packaged_markdown_text

_CLI_WRITABLE_RELATIONS = frozenset(
    {"related", "supersedes", "implements", "derives-from"}
)


def _artifact_examples() -> list[str]:
    source = packaged_markdown_text(
        "sase.main.init_memory",
        "templates/memory-sase-artifacts.template.md",
    )
    examples: list[str] = []
    in_bash_fence = False
    for line in source.splitlines():
        if line.strip() == "```bash":
            in_bash_fence = True
            continue
        if line.strip().startswith("```"):
            in_bash_fence = False
            continue
        if in_bash_fence and line.startswith("sase artifact "):
            examples.append(line)
    return examples


def test_generated_artifact_memory_examples_parse_against_cli_contract() -> None:
    examples = _artifact_examples()
    parser = create_parser(only="artifact")

    assert examples
    for example in examples:
        args = parser.parse_args(shlex.split(example)[1:])
        assert args.command == "artifact"


def test_artifact_memory_examples_preserve_key_command_distinctions() -> None:
    parser = create_parser(only="artifact")
    examples = _artifact_examples()

    read_args = parser.parse_args(
        shlex.split('sase artifact read plan:202608/example.md "Need context"')[1:]
    )
    assert read_args.artifact_subcommand == "read"
    assert read_args.reason == "Need context"
    with pytest.raises(SystemExit):
        parser.parse_args(shlex.split("sase artifact read plan:202608/example.md")[1:])

    create_examples = [example for example in examples if " create " in example]
    assert create_examples
    create_args = parser.parse_args(shlex.split(create_examples[0])[1:])
    assert create_args.artifact_subcommand == "create"
    assert create_args.path == "report.md"
    assert create_args.label == "Investigation report"

    link_examples = [example for example in examples if " link add " in example]
    assert link_examples
    for example in link_examples:
        link_args = parser.parse_args(shlex.split(example)[1:])
        assert link_args.artifact_subcommand == "link"
        assert link_args.link_subcommand == "add"
        assert link_args.relation in _CLI_WRITABLE_RELATIONS
