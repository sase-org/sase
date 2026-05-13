"""Tests for the ``sase ace`` command handler."""

from pathlib import Path
from unittest.mock import patch

from sase.main import ace_handler


class _FixedDatetime:
    @classmethod
    def now(cls) -> "_FixedDatetime":
        return cls()

    def strftime(self, _fmt: str) -> str:
        return "20260513_120957"


class _FakeProfiler:
    def output_text(self, *, unicode: bool, color: bool, show_all: bool) -> str:
        assert unicode is True
        assert color is False
        assert show_all is True
        return "profile text"


def test_write_profile_output_shortens_home_and_copies_path(
    tmp_path: Path,
    capsys,
) -> None:
    home = tmp_path / "home"
    tmpdir = home / "tmp" / "sase"
    tmpdir.mkdir(parents=True)

    with (
        patch("sase.main.ace_handler.datetime", _FixedDatetime),
        patch("sase.main.ace_handler.get_sase_tmpdir", return_value=str(tmpdir)),
        patch("sase.core.paths.Path.home", return_value=home),
        patch(
            "sase.main.ace_handler.copy_to_system_clipboard", return_value=True
        ) as copy_to_clipboard,
    ):
        output_path = ace_handler._write_profile_output(_FakeProfiler(), "")

    expected_path = tmpdir / "ace_profile_20260513_120957.txt"
    assert output_path == str(expected_path)
    assert expected_path.read_text() == "profile text"
    copy_to_clipboard.assert_called_once_with(
        "~/tmp/sase/ace_profile_20260513_120957.txt"
    )
    assert (
        capsys.readouterr().err
        == "Profile written to: ~/tmp/sase/ace_profile_20260513_120957.txt\n"
        "Profile path copied to clipboard.\n"
    )


def test_profile_output_path_expands_explicit_tilde_path(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()

    with patch.dict("os.environ", {"HOME": str(home)}):
        output_path = ace_handler._profile_output_path("~/profile.txt")

    assert output_path == str(home / "profile.txt")
    assert (home / "profile.txt").parent.exists()
