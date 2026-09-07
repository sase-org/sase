from __future__ import annotations

import base64
import hashlib
from typing import Any

import pytest

import sase.dispatch.content as content


def test_content_client_validates_digest_and_reuses_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = b"hello remote"
    digest = hashlib.sha256(data).hexdigest()
    calls = {"n": 0}

    class Facade:
        def content_range_sync(
            self, request: dict[str, Any], **_kwargs: Any
        ) -> dict[str, Any]:
            calls["n"] += 1
            return {
                "hosts": [
                    {
                        "payload": {
                            "offset": request["offset"],
                            "sha256": digest,
                            "data_base64": base64.b64encode(data).decode("ascii"),
                            "eof": True,
                            "next_offset": None,
                            "supports_growth": False,
                        }
                    }
                ]
            }

    monkeypatch.setattr(content, "build_federation_facade", Facade)
    client = content.RemoteContentClient()
    handle = {"id": "ch1", "digest": digest, "kind": "output"}
    revision = {"schema_version": 1, "logical_key": "k", "revision": 1}
    first = client.open_handle(handle, row_revision=revision)
    second = client.open_handle(handle, row_revision=revision)
    assert first.data == data
    assert second.data == data
    assert calls["n"] == 1


def test_content_client_continues_growing_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chunks = [b"one", b"two"]
    calls: list[int] = []

    class Facade:
        def content_range_sync(
            self, request: dict[str, Any], **_kwargs: Any
        ) -> dict[str, Any]:
            calls.append(int(request["offset"]))
            payload = chunks[0] if request["offset"] == 0 else chunks[1]
            return {
                "hosts": [
                    {
                        "payload": {
                            "offset": request["offset"],
                            "sha256": hashlib.sha256(payload).hexdigest(),
                            "data_base64": base64.b64encode(payload).decode("ascii"),
                            "eof": request["offset"] != 0,
                            "next_offset": 3 if request["offset"] == 0 else None,
                            "supports_growth": True,
                        }
                    }
                ]
            }

    monkeypatch.setattr(content, "build_federation_facade", Facade)
    client = content.RemoteContentClient()
    handle = {"id": "ch1", "supports_growth": True}
    revision = {"schema_version": 1, "logical_key": "k", "revision": 1}
    first = client.open_handle(handle, row_revision=revision)
    second = client.continue_tail(first, handle, row_revision=revision)
    assert first.data == b"one"
    assert second.data == b"two"
    assert calls == [0, 3]


def test_content_client_rejects_digest_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = b"hello remote"

    class Facade:
        def content_range_sync(
            self, request: dict[str, Any], **_kwargs: Any
        ) -> dict[str, Any]:
            return {
                "hosts": [
                    {
                        "payload": {
                            "offset": request["offset"],
                            "sha256": hashlib.sha256(b"other").hexdigest(),
                            "data_base64": base64.b64encode(data).decode("ascii"),
                            "eof": True,
                        }
                    }
                ]
            }

    monkeypatch.setattr(content, "build_federation_facade", Facade)
    with pytest.raises(content.RemoteContentError, match="digest"):
        content.RemoteContentClient().open_handle(
            {"id": "ch1", "digest": hashlib.sha256(data).hexdigest()},
            row_revision={"schema_version": 1, "logical_key": "k", "revision": 1},
        )
