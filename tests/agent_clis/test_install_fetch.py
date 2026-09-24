"""Fetch tests for provider-declared agent-CLI install scripts."""

from __future__ import annotations

import pytest

from sase.agent_clis.install import (
    AgentCliInstallError,
    fetch_install_script,
)

from .install_helpers import (
    SCRIPT_BODY,
    SCRIPT_DIGEST,
    SCRIPT_URL,
    _FakeResponse,
    _urlopen,
)


def test_fetch_writes_a_private_file_and_reports_its_digest() -> None:
    script = fetch_install_script(SCRIPT_URL, urlopen_fn=_urlopen())

    try:
        assert script.digest == SCRIPT_DIGEST
        assert script.size_bytes == len(SCRIPT_BODY)
        assert script.path.read_bytes() == SCRIPT_BODY
        assert script.path.stat().st_mode & 0o777 == 0o600
    finally:
        script.remove()


def test_fetch_rejects_plain_http_before_any_request() -> None:
    def opener(*_args: object, **_kwargs: object) -> _FakeResponse:
        raise AssertionError("must not request a non-HTTPS URL")

    with pytest.raises(AgentCliInstallError, match="not HTTPS"):
        fetch_install_script("http://dev.example.test/install.sh", urlopen_fn=opener)


def test_fetch_rejects_a_redirect_that_leaves_https() -> None:
    with pytest.raises(AgentCliInstallError, match="redirected off HTTPS"):
        fetch_install_script(
            SCRIPT_URL,
            urlopen_fn=_urlopen(served_url="http://dev.example.test/install.sh"),
        )


def test_fetch_enforces_a_size_cap() -> None:
    with pytest.raises(AgentCliInstallError, match="byte limit"):
        fetch_install_script(SCRIPT_URL, urlopen_fn=_urlopen(b"x" * 100), max_bytes=10)


def test_fetch_reports_a_transport_failure_as_an_install_error() -> None:
    def opener(*_args: object, **_kwargs: object) -> _FakeResponse:
        raise OSError("connection reset")

    with pytest.raises(AgentCliInstallError, match="could not fetch install script"):
        fetch_install_script(SCRIPT_URL, urlopen_fn=opener)
