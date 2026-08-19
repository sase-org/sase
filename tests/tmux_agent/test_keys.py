"""Tests for tmux Agent menu-key assignment."""

from __future__ import annotations

from sase.tmux_agent.keys import MenuKeyCandidate, assign_menu_keys


def _candidate(
    provider: str,
    *,
    display_name: str = "",
    configured_key: str = "",
    descriptor_key: str = "",
) -> MenuKeyCandidate:
    return MenuKeyCandidate(
        provider=provider,
        display_name=display_name or provider,
        configured_key=configured_key,
        descriptor_key=descriptor_key,
    )


def test_configured_key_wins_when_free() -> None:
    candidates = [_candidate("claude", configured_key="z", descriptor_key="c")]
    assert assign_menu_keys(candidates) == {"claude": "z"}


def test_descriptor_key_used_when_no_config_override() -> None:
    candidates = [_candidate("claude", descriptor_key="c")]
    assert assign_menu_keys(candidates) == {"claude": "c"}


def test_falls_back_to_first_free_letter_of_provider_name() -> None:
    candidates = [_candidate("codex")]
    assert assign_menu_keys(candidates) == {"codex": "c"}


def test_falls_back_to_display_name_when_provider_name_letters_are_taken() -> None:
    # "aa" and "az" sort before "ba" and claim its only letters (a, b), so
    # assignment must fall through to "ba"'s display name's letters.
    candidates = [
        _candidate("aa", configured_key="a"),
        _candidate("az", configured_key="b"),
        _candidate("ba", display_name="zebra"),
    ]
    assigned = assign_menu_keys(candidates)
    assert assigned["ba"] == "z"


def test_falls_back_to_digit_when_no_letters_are_free() -> None:
    candidates = [
        _candidate("zz", configured_key="z"),
        _candidate("zzz", display_name="zzz"),
    ]
    assigned = assign_menu_keys(candidates)
    assert assigned["zzz"] == "1"


def test_falls_back_to_any_remaining_letter_after_digits_exhausted() -> None:
    digit_claimants = [_candidate(f"d{d}", configured_key=d) for d in "123456789"]
    candidates = [
        *digit_claimants,
        _candidate("z0", configured_key="z"),
        _candidate("zz", display_name="zz"),
    ]
    assigned = assign_menu_keys(candidates)
    assert assigned["zz"] == "a"


def test_stability_same_input_produces_same_assignment() -> None:
    candidates = [
        _candidate("claude", descriptor_key="c"),
        _candidate("codex", descriptor_key="x"),
        _candidate("grok", descriptor_key="g"),
    ]
    first = assign_menu_keys(candidates)
    second = assign_menu_keys(list(reversed(candidates)))
    assert first == second == {"claude": "c", "codex": "x", "grok": "g"}


def test_collision_resolved_by_registry_alphabetical_processing_order() -> None:
    # Both providers' descriptors claim "c"; alphabetically "alpha" is
    # processed before "beta", so "alpha" wins the shared key.
    candidates = [
        _candidate("beta", descriptor_key="c"),
        _candidate("alpha", descriptor_key="c"),
    ]
    assigned = assign_menu_keys(candidates)
    assert assigned["alpha"] == "c"
    assert assigned["beta"] == "b"


def test_j_and_k_are_never_auto_assigned() -> None:
    candidates = [_candidate("jk")]
    assigned = assign_menu_keys(candidates)
    assert assigned["jk"] not in {"j", "k"}


def test_explicit_config_key_may_still_claim_a_reserved_letter() -> None:
    candidates = [_candidate("qwen", configured_key="j")]
    assert assign_menu_keys(candidates) == {"qwen": "j"}


def test_explicit_descriptor_key_may_still_claim_a_reserved_letter() -> None:
    candidates = [_candidate("qwen", descriptor_key="k")]
    assert assign_menu_keys(candidates) == {"qwen": "k"}


def test_q_is_not_reserved() -> None:
    candidates = [_candidate("qwen", descriptor_key="q")]
    assert assign_menu_keys(candidates) == {"qwen": "q"}


def test_provider_with_no_free_letters_or_digits_gets_no_key() -> None:
    # Claim every non-reserved letter and every digit explicitly so the last
    # provider (whose own letters are all already claimed) has nothing left.
    used_keys = list("abcdefghilmnopqrstuvwxyz123456789")
    candidates = [
        _candidate(f"p{i}", configured_key=key) for i, key in enumerate(used_keys)
    ]
    candidates.append(_candidate("zzzzzz0", display_name="zzzzzz0"))
    assigned = assign_menu_keys(candidates)
    assert assigned["zzzzzz0"] == ""


def test_returns_empty_dict_for_no_candidates() -> None:
    assert assign_menu_keys([]) == {}
