from __future__ import annotations

import base64

import pytest

from sase.ace.tui.graphics import (
    KITTY_PLACEHOLDER,
    build_delete_sequence,
    build_place_sequence,
    build_png_upload_sequences,
    generate_image_id,
    is_supported_image_path,
    placeholder_grid,
    tmux_passthrough_wrap,
)


def test_image_extension_detection() -> None:
    assert is_supported_image_path("plot.PNG")
    assert is_supported_image_path("photo.jpeg")
    assert is_supported_image_path("anim.gif")
    assert not is_supported_image_path("notes.md")


def test_generate_image_id_is_stable_24_bit_and_nonzero() -> None:
    first = generate_image_id("path/to/image.png")
    second = generate_image_id("path/to/image.png")

    assert first == second
    assert 1 <= first <= 0xFFFFFF


def test_png_upload_sequences_are_chunked() -> None:
    png = b"0123456789"
    sequences = build_png_upload_sequences(png, 42, chunk_size=8)

    assert len(sequences) == 2
    assert sequences[0].startswith("\x1b_Ga=t,f=100,t=d,i=42,q=2,m=1;")
    assert sequences[1].startswith("\x1b_Gm=0;")
    encoded_payload = "".join(
        seq.split(";", 1)[1].removesuffix("\x1b\\") for seq in sequences
    )
    assert base64.b64decode(encoded_payload) == png


def test_tmux_passthrough_doubles_embedded_escapes() -> None:
    wrapped = tmux_passthrough_wrap("\x1b_Ga=d;\x1b\\")

    assert wrapped == "\x1bPtmux;\x1b\x1b_Ga=d;\x1b\x1b\\\x1b\\"


def test_place_and_delete_sequences() -> None:
    place = build_place_sequence(7, 9, columns=3, rows=2)
    delete = build_delete_sequence(7)

    assert place == "\x1b_Ga=p,i=7,p=9,U=1,c=3,r=2,q=2;\x1b\\"
    assert delete == "\x1b_Ga=d,d=I,i=7,q=2;\x1b\\"


def test_placeholder_grid_coordinates() -> None:
    grid = placeholder_grid(2, 2)

    assert grid == [
        f"{KITTY_PLACEHOLDER}\u0305\u0305{KITTY_PLACEHOLDER}\u0305\u030d",
        f"{KITTY_PLACEHOLDER}\u030d\u0305{KITTY_PLACEHOLDER}\u030d\u030d",
    ]


def test_placeholder_grid_accepts_last_v1_coordinate() -> None:
    grid = placeholder_grid(297, 1)

    assert grid[0].endswith(f"{KITTY_PLACEHOLDER}\u0305\U0001d244")


def test_placeholder_grid_rejects_v1_coordinate_overflow() -> None:
    with pytest.raises(ValueError, match="coordinate"):
        placeholder_grid(298, 1)
