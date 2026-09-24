"""Unit coverage for the lenient service proc description split."""

from __future__ import annotations

from sase.service.description import split_service_description


def test_none_blank_and_whitespace_give_empty() -> None:
    assert split_service_description(None) == ("", "")
    assert split_service_description("") == ("", "")
    assert split_service_description("   \n  ") == ("", "")


def test_single_line_gives_summary_only() -> None:
    assert split_service_description("Run checks") == ("Run checks", "")


def test_summary_blank_body_split_normally() -> None:
    summary, body = split_service_description("Summary line\n\nBody here.\n")
    assert summary == "Summary line"
    assert body == "Body here."


def test_non_blank_line_two_keeps_every_line() -> None:
    assert split_service_description("a\nb\nc") == ("a", "b\nc")
    assert split_service_description("a\nb") == ("a", "b")


def test_crlf_splits_like_lf() -> None:
    assert split_service_description("a\r\n\r\nb") == ("a", "b")
    assert split_service_description("a\r\nb\r\nc") == ("a", "b\nc")


def test_memoization_skips_binding_on_repeat(monkeypatch) -> None:
    from sase.service import description as desc_module

    calls = 0
    real = desc_module.split_axe_description

    def _counting(value: str) -> tuple[str, str]:
        nonlocal calls
        calls += 1
        return real(value)

    monkeypatch.setattr(desc_module, "split_axe_description", _counting)
    desc_module.split_service_description.cache_clear()
    try:
        first = desc_module.split_service_description("Summary\n\nBody")
        second = desc_module.split_service_description("Summary\n\nBody")
        assert first == second
        assert calls == 1
    finally:
        desc_module.split_service_description.cache_clear()
