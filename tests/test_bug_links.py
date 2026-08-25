"""Tests for external bug reference normalization."""

from sase.bug_links import normalize_external_ref


def test_normalize_external_ref_accepts_aliases_urls_and_shorthand(monkeypatch) -> None:
    alias_map = {
        "sase-display": "gh_sase-org__sase",
        "sase": "gh_sase-org__sase",
        "linked-github": "sase-github",
    }
    monkeypatch.setattr(
        "sase.project_aliases.resolve_project_alias_ref",
        lambda ref: alias_map.get(ref, ref),
    )

    assert normalize_external_ref(42, project="sase-display") == (
        "bug:gh_sase-org__sase#42"
    )
    assert normalize_external_ref("#42", project="sase") == ("bug:gh_sase-org__sase#42")
    assert normalize_external_ref("bug:linked-github#42", project="sase") == (
        "bug:sase-github#42"
    )
    assert (
        normalize_external_ref(
            "https://github.com/sase-org/sase/issues/42?view=1",
            project="linked-github",
        )
        == "bug:gh_sase-org__sase#42"
    )


def test_normalize_external_ref_rejects_blank_and_malformed_inputs() -> None:
    assert normalize_external_ref("", project="sase") == ""
    assert normalize_external_ref("42", project="") == ""
    assert normalize_external_ref("bug:sase#", project="sase") == ""
    assert normalize_external_ref("bug:sase org#42", project="sase") == ""
    assert normalize_external_ref("sase#not/a/number", project="sase") == ""
