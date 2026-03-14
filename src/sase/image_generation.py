"""Gemini image-generation helpers."""

from __future__ import annotations

import base64
import os
from datetime import datetime
from pathlib import Path

from sase.sase_utils import EASTERN_TZ

DEFAULT_IMAGE_MODEL = "gemini-3-pro-image-preview"
DEFAULT_IMAGE_DIR = Path.home() / ".sase" / "images"

_MIME_TO_EXT: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


def generate_image(
    prompt: str,
    *,
    model: str = DEFAULT_IMAGE_MODEL,
    output_dir: str | Path | None = None,
) -> tuple[Path, str]:
    """Generate an image with Gemini and write it to disk.

    Returns:
        Tuple of (image_path, mime_type).
    """
    from google import genai
    from google.genai import types

    target_dir = Path(output_dir).expanduser() if output_dir else DEFAULT_IMAGE_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    client = genai.Client(api_key=api_key) if api_key else genai.Client()

    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"]),
    )

    image_bytes: bytes | None = None
    mime_type = "image/png"

    candidates = getattr(response, "candidates", None) or []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        parts = getattr(content, "parts", None) or []
        for part in parts:
            inline_data = getattr(part, "inline_data", None)
            if not inline_data:
                continue
            data = getattr(inline_data, "data", None)
            if not data:
                continue
            mime_type = getattr(inline_data, "mime_type", None) or mime_type
            if isinstance(data, str):
                image_bytes = base64.b64decode(data)
            else:
                image_bytes = bytes(data)
            break
        if image_bytes is not None:
            break

    if image_bytes is None:
        raise RuntimeError("Gemini response did not include image data.")

    ext = _MIME_TO_EXT.get(mime_type.lower(), ".png")
    ts = datetime.now(EASTERN_TZ).strftime("%Y%m%d_%H%M%S")
    output_path = target_dir / f"gemini_image_{ts}{ext}"
    output_path.write_bytes(image_bytes)
    return output_path, mime_type
