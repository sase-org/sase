"""Memoized gettext catalog lookup used during parser construction."""

from __future__ import annotations

import functools
import gettext
import os
from collections.abc import Iterable

_GETTEXT_ENV_KEYS = ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG")
_ORIGINAL_GETTEXT_FIND = gettext.find


def gettext_languages_key(languages: object) -> tuple[str, ...] | None:
    if languages is None:
        return None
    if isinstance(languages, str):
        return (languages,)
    if isinstance(languages, Iterable):
        return tuple(str(language) for language in languages)
    return (str(languages),)


@functools.lru_cache(maxsize=512)
def cached_gettext_find(
    domain: str,
    localedir: str | None,
    languages: tuple[str, ...] | None,
    locale_env: tuple[str | None, ...] | None,
    all_matches: bool,
) -> str | list[str] | None:
    del locale_env
    result = _ORIGINAL_GETTEXT_FIND(
        domain,
        localedir,
        None if languages is None else list(languages),
        all=all_matches,
    )
    if isinstance(result, list):
        return list(result)
    return result


def memoized_gettext_find(
    domain: str,
    localedir: str | None = None,
    languages: object = None,
    all: bool = False,  # noqa: A002 - mirrors gettext.find's public signature.
) -> str | list[str] | None:
    """Memoize locale catalog discovery while preserving gettext's inputs."""

    language_key = gettext_languages_key(languages)
    locale_env = (
        tuple(os.environ.get(key) for key in _GETTEXT_ENV_KEYS)
        if language_key is None
        else None
    )
    result = cached_gettext_find(
        domain,
        localedir,
        language_key,
        locale_env,
        bool(all),
    )
    if isinstance(result, list):
        return list(result)
    return result


def install_memoized_gettext_find() -> None:
    """Install the parser-time gettext catalog lookup cache."""

    gettext.find = memoized_gettext_find  # type: ignore[assignment]
