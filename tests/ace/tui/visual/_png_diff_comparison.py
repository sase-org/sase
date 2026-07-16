"""Pixel comparison primitives for ACE PNG visual tests."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageChops

# Known macOS/Linux resvg drift stays within eight visible channel levels after
# alpha-aware compositing. Differences above this ceiling are product-visible,
# even when their total area is small enough for the cross-host ratio allowance.
DEFAULT_MATERIAL_DIFF_THRESHOLD = 8


@dataclass(frozen=True)
class PngDiffSummary:
    """Exact pixel comparison summary for two PNG images."""

    expected_size: tuple[int, int]
    actual_size: tuple[int, int]
    changed_pixels: int
    total_pixels: int
    material_diff_pixels: int
    material_diff_threshold: int

    @property
    def changed_ratio(self) -> float:
        return self.changed_pixels / self.total_pixels if self.total_pixels else 0.0

    @property
    def material_diff_ratio(self) -> float:
        return (
            self.material_diff_pixels / self.total_pixels if self.total_pixels else 0.0
        )

    def is_within(
        self,
        *,
        max_diff_pixels: int | None,
        max_diff_ratio: float | None,
        max_material_diff_pixels: int | None,
    ) -> bool:
        if max_diff_pixels is not None and self.changed_pixels > max_diff_pixels:
            return False
        if max_diff_ratio is not None and self.changed_ratio > max_diff_ratio:
            return False
        if (
            max_material_diff_pixels is not None
            and self.material_diff_pixels > max_material_diff_pixels
        ):
            return False
        return True


def diff_pngs(
    expected_png: bytes,
    actual_png: bytes,
    *,
    material_diff_threshold: int = DEFAULT_MATERIAL_DIFF_THRESHOLD,
) -> tuple[PngDiffSummary, bytes]:
    """Compare two PNG byte strings and return a red-pixel diff image."""
    material_diff_threshold = validate_material_diff_threshold(
        material_diff_threshold,
        name="material_diff_threshold",
    )
    expected = _load_png(expected_png)
    actual = _load_png(actual_png)
    size = (
        max(expected.width, actual.width),
        max(expected.height, actual.height),
    )
    expected_canvas = _place_on_canvas(expected, size)
    actual_canvas = _place_on_canvas(actual, size)

    exact_distance = _max_channel(ImageChops.difference(expected_canvas, actual_canvas))
    changed_mask = exact_distance.point([0, *([255] * 255)])
    changed_pixels = sum(exact_distance.histogram()[1:])

    material_distance = _alpha_aware_color_distance(
        expected_canvas,
        actual_canvas,
    )
    material_diff_pixels = sum(
        material_distance.histogram()[material_diff_threshold + 1 :]
    )

    diff = Image.new("RGBA", size, (255, 0, 0, 0))
    diff.putalpha(changed_mask)

    return (
        PngDiffSummary(
            expected_size=expected.size,
            actual_size=actual.size,
            changed_pixels=changed_pixels,
            total_pixels=size[0] * size[1],
            material_diff_pixels=material_diff_pixels,
            material_diff_threshold=material_diff_threshold,
        ),
        _to_png_bytes(diff),
    )


def validate_material_diff_threshold(value: int, *, name: str) -> int:
    if not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer, got {value!r}")
    if value > 255:
        raise ValueError(f"{name} must be between 0 and 255, got {value!r}")
    return value


def _load_png(value: bytes) -> Image.Image:
    with Image.open(BytesIO(value)) as image:
        return image.convert("RGBA")


def _place_on_canvas(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    canvas.paste(image, (0, 0))
    return canvas


def _max_channel(image: Image.Image) -> Image.Image:
    channels = image.split()
    maximum = channels[0]
    for channel in channels[1:]:
        maximum = ImageChops.lighter(maximum, channel)
    return maximum


def _alpha_aware_color_distance(
    expected: Image.Image,
    actual: Image.Image,
) -> Image.Image:
    """Return maximum visible channel distance over black and white canvases."""
    distance_channels: list[Image.Image] = []
    for background_color in ((0, 0, 0, 255), (255, 255, 255, 255)):
        background = Image.new("RGBA", expected.size, background_color)
        expected_composite = Image.alpha_composite(background, expected).convert("RGB")
        actual_composite = Image.alpha_composite(background, actual).convert("RGB")
        distance_channels.extend(
            ImageChops.difference(expected_composite, actual_composite).split()
        )

    maximum = distance_channels[0]
    for channel in distance_channels[1:]:
        maximum = ImageChops.lighter(maximum, channel)
    return maximum


def _to_png_bytes(image: Image.Image) -> bytes:
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()
