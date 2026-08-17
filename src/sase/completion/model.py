"""JSON-serializable structural model for the sase CLI completion spec."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from sase.completion.kinds import ValueKind


def _kind_to_json(kind: ValueKind | None) -> str | None:
    return None if kind is None else str(kind)


def _kind_from_json(value: object) -> ValueKind | None:
    return None if value is None else ValueKind(str(value))


def _choices_to_json(choices: tuple[str, ...] | None) -> list[str] | None:
    return None if choices is None else list(choices)


def _choices_from_json(value: object) -> tuple[str, ...] | None:
    return None if value is None else tuple(value)  # type: ignore[arg-type]


def _digest(*parts: str) -> str:
    hasher = hashlib.sha256()
    for part in parts:
        hasher.update(part.encode("utf-8"))
        hasher.update(b"\x00")
    return hasher.hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class OptionSpec:
    """A single completable option (``-x``/``--xyz``) on a command."""

    strings: tuple[str, ...]
    dest: str
    summary: str
    takes_value: bool
    repeatable: bool
    choices: tuple[str, ...] | None
    kind: ValueKind | None
    hidden: bool

    def to_json(self) -> dict[str, Any]:
        return {
            "strings": list(self.strings),
            "dest": self.dest,
            "summary": self.summary,
            "takes_value": self.takes_value,
            "repeatable": self.repeatable,
            "choices": _choices_to_json(self.choices),
            "kind": _kind_to_json(self.kind),
            "hidden": self.hidden,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> OptionSpec:
        return cls(
            strings=tuple(data["strings"]),
            dest=data["dest"],
            summary=data["summary"],
            takes_value=data["takes_value"],
            repeatable=data["repeatable"],
            choices=_choices_from_json(data.get("choices")),
            kind=_kind_from_json(data.get("kind")),
            hidden=data["hidden"],
        )


@dataclass(frozen=True, slots=True)
class PositionalSpec:
    """A single completable positional argument on a command."""

    metavar: str
    dest: str
    summary: str
    nargs: str | int | None
    choices: tuple[str, ...] | None
    kind: ValueKind | None
    is_remainder: bool

    def to_json(self) -> dict[str, Any]:
        return {
            "metavar": self.metavar,
            "dest": self.dest,
            "summary": self.summary,
            "nargs": self.nargs,
            "choices": _choices_to_json(self.choices),
            "kind": _kind_to_json(self.kind),
            "is_remainder": self.is_remainder,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> PositionalSpec:
        return cls(
            metavar=data["metavar"],
            dest=data["dest"],
            summary=data["summary"],
            nargs=data["nargs"],
            choices=_choices_from_json(data.get("choices")),
            kind=_kind_from_json(data.get("kind")),
            is_remainder=data["is_remainder"],
        )


@dataclass(frozen=True, slots=True)
class CommandSpec:
    """One node (root, group, or leaf) in the completion command tree."""

    name: str
    path: tuple[str, ...]
    aliases: tuple[str, ...]
    hidden: bool
    summary: str
    options: tuple[OptionSpec, ...]
    positionals: tuple[PositionalSpec, ...]
    subcommands: tuple[CommandSpec, ...]
    default_child: str | None
    mutex_groups: tuple[tuple[str, ...], ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": list(self.path),
            "aliases": list(self.aliases),
            "hidden": self.hidden,
            "summary": self.summary,
            "options": [option.to_json() for option in self.options],
            "positionals": [positional.to_json() for positional in self.positionals],
            "subcommands": [child.to_json() for child in self.subcommands],
            "default_child": self.default_child,
            "mutex_groups": [list(group) for group in self.mutex_groups],
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> CommandSpec:
        return cls(
            name=data["name"],
            path=tuple(data["path"]),
            aliases=tuple(data["aliases"]),
            hidden=data["hidden"],
            summary=data["summary"],
            options=tuple(OptionSpec.from_json(item) for item in data["options"]),
            positionals=tuple(
                PositionalSpec.from_json(item) for item in data["positionals"]
            ),
            subcommands=tuple(cls.from_json(item) for item in data["subcommands"]),
            default_child=data["default_child"],
            mutex_groups=tuple(tuple(group) for group in data["mutex_groups"]),
        )

    def description_digest(self) -> str:
        """Return a short digest of this command's own help text.

        Covers only this command's summary and its direct options'/
        positionals' summaries, not descendants, so a wording change shows up
        as a one-line diff on exactly the command that changed.
        """
        parts = [
            self.summary,
            *(option.summary for option in self.options),
            *(positional.summary for positional in self.positionals),
        ]
        return _digest(*parts)

    def structural_view(self) -> dict[str, Any]:
        """Return the checked-in drift-snapshot view of this command.

        Excludes summary text, which churns with wording, in favor of a
        digest that still turns a wording-only change into a one-line diff.
        """
        return {
            "name": self.name,
            "path": list(self.path),
            "aliases": list(self.aliases),
            "hidden": self.hidden,
            "description_digest": self.description_digest(),
            "options": [
                {
                    "strings": list(option.strings),
                    "dest": option.dest,
                    "takes_value": option.takes_value,
                    "repeatable": option.repeatable,
                    "choices": _choices_to_json(option.choices),
                    "kind": _kind_to_json(option.kind),
                    "hidden": option.hidden,
                }
                for option in self.options
            ],
            "positionals": [
                {
                    "metavar": positional.metavar,
                    "dest": positional.dest,
                    "nargs": positional.nargs,
                    "choices": _choices_to_json(positional.choices),
                    "kind": _kind_to_json(positional.kind),
                    "is_remainder": positional.is_remainder,
                }
                for positional in self.positionals
            ],
            "subcommands": [child.structural_view() for child in self.subcommands],
            "default_child": self.default_child,
            "mutex_groups": [list(group) for group in self.mutex_groups],
        }


@dataclass(frozen=True, slots=True)
class CompletionSpec:
    """The whole sase CLI completion spec: a program name and its root command."""

    prog: str
    version: str
    root: CommandSpec

    def to_json(self) -> dict[str, Any]:
        return {
            "prog": self.prog,
            "version": self.version,
            "root": self.root.to_json(),
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> CompletionSpec:
        return cls(
            prog=data["prog"],
            version=data["version"],
            root=CommandSpec.from_json(data["root"]),
        )

    def structural_view(self) -> dict[str, Any]:
        """Return the checked-in drift-snapshot view of this spec.

        Excludes ``version``, which changes on every release and carries no
        grammar information.
        """
        return {
            "prog": self.prog,
            "root": self.root.structural_view(),
        }

    def structural_digest(self) -> str:
        """Return a single digest over the whole structural view."""
        return _digest(json.dumps(self.structural_view(), sort_keys=True))


__all__ = [
    "CommandSpec",
    "CompletionSpec",
    "OptionSpec",
    "PositionalSpec",
]
