"""Image generation using Google's Nano Banana 2 (Gemini 3.1 Flash Image)."""

import os
from datetime import datetime
from pathlib import Path

from sase.sase_utils import EASTERN_TZ

_DEFAULT_MODEL = "gemini-3.1-flash-image-preview"
_IMAGES_DIR = Path.home() / ".sase" / "images"


def generate_image(
    prompt: str,
    *,
    model: str | None = None,
    aspect_ratio: str = "1:1",
    output_path: str | None = None,
) -> Path:
    """Generate an image from a text prompt using Nano Banana 2.

    Args:
        prompt: Text description of the image to generate.
        model: Model ID to use (default: gemini-3.1-flash-image-preview).
        aspect_ratio: Aspect ratio (1:1, 4:3, 3:4, 16:9, 9:16).
        output_path: Optional explicit output file path. If not provided,
            saves to ~/.sase/images/<timestamp>.png.

    Returns:
        Path to the generated image file.

    Raises:
        RuntimeError: If no image was generated or API key is missing.
    """
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError(
            "No API key found. Set GEMINI_API_KEY or GOOGLE_API_KEY environment variable."
        )

    client = genai.Client(api_key=api_key)
    model_id = model or _DEFAULT_MODEL

    response = client.models.generate_content(
        model=model_id,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(
                aspect_ratio=aspect_ratio,
            ),
        ),
    )

    # Find the image part in the response
    candidates = response.candidates
    if not candidates:
        raise RuntimeError(
            "No image was generated. The model returned an empty response."
        )

    content = candidates[0].content
    if content is None or not content.parts:
        raise RuntimeError(
            "No image was generated. The model returned an empty response."
        )

    for part in content.parts:
        inline = part.inline_data
        if inline is None:
            continue
        mime = inline.mime_type
        if mime is None or not mime.startswith("image/"):
            continue

        data = inline.data
        if data is None:
            continue

        # Determine output path
        if output_path:
            dest = Path(output_path)
        else:
            _IMAGES_DIR.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now(EASTERN_TZ).strftime("%Y%m%d_%H%M%S")
            ext = mime.split("/")[-1]
            if ext == "jpeg":
                ext = "jpg"
            dest = _IMAGES_DIR / f"{timestamp}.{ext}"

        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return dest

    raise RuntimeError("No image data found in the model response.")
