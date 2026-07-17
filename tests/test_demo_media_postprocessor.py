from __future__ import annotations

import importlib.util
import json
import sys
from fractions import Fraction
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _load_postprocessor() -> ModuleType:
    script = ROOT / "demos" / "scripts" / ("postprocess_demo_" + "media")
    loader = SourceFileLoader("demo_media_postprocessor", str(script))
    spec = importlib.util.spec_from_file_location(
        "demo_media_postprocessor", script, loader=loader
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def postprocessor() -> ModuleType:
    return _load_postprocessor()


def _write_sidecar(path: Path, *, cues: str) -> None:
    path.write_text(
        """\
version: 1
defaults:
  font: Fira Code
  size: 40
  position: lower-third
  margin_x: 80
  margin_y: 90
  fade_ms: 250
  box_color: \"#000000\"
  box_opacity: 0.70
  text_color: \"#ffffff\"
cues:
"""
        + cues,
        encoding="utf-8",
    )


def test_loads_valid_absolute_cues(postprocessor: ModuleType, tmp_path: Path) -> None:
    sidecar = tmp_path / "demo.captions.yml"
    _write_sidecar(
        sidecar,
        cues="""\
  - at: 2.0s
    until: 4.5s
    text: Recall prior prompts instantly
  - at: 12.0s
    until: 15.0s
    position: top-right
    text: One prompt becomes a launch preview
""",
    )

    result = postprocessor.load_caption_spec(sidecar, duration=16.0)

    assert result.defaults.font == "Fira Code"
    assert result.cues[0].at == 2.0
    assert result.cues[0].position == "lower-third"
    assert result.cues[1].position == "top-right"


@pytest.mark.parametrize(
    ("cues", "message"),
    [
        (
            """\
  - at: 2.0s
    until: 4.0s
    text: First
  - at: 3.5s
    until: 5.0s
    text: Overlap
""",
            "previous cue ends",
        ),
        (
            """\
  - at: 2.0s
    until: 17.0s
    text: Too late
""",
            "exceeds media duration",
        ),
        (
            """\
  - at: 2.0s
    until: 4.0s
    text: \"  \"
""",
            "text must be non-empty",
        ),
        (
            """\
  - at: 4.0s
    until: 4.0s
    text: No duration
""",
            "until must be later",
        ),
    ],
)
def test_rejects_invalid_cues(
    postprocessor: ModuleType,
    tmp_path: Path,
    cues: str,
    message: str,
) -> None:
    sidecar = tmp_path / "demo.captions.yml"
    _write_sidecar(sidecar, cues=cues)

    with pytest.raises(ValueError, match=message):
        postprocessor.load_caption_spec(sidecar, duration=16.0)


def test_rejects_unknown_schema_version(
    postprocessor: ModuleType, tmp_path: Path
) -> None:
    sidecar = tmp_path / "demo.captions.yml"
    sidecar.write_text("version: 2\ndefaults: {}\ncues: []\n", encoding="utf-8")

    with pytest.raises(ValueError, match="version must be 1"):
        postprocessor.load_caption_spec(sidecar, duration=16.0)


def test_rejects_non_finite_timestamp(postprocessor: ModuleType) -> None:
    with pytest.raises(ValueError, match="finite"):
        postprocessor.parse_timestamp("nans", field="cue.at")


def test_renders_ass_styles_fades_and_escaped_text(
    postprocessor: ModuleType, tmp_path: Path
) -> None:
    sidecar = tmp_path / "demo.captions.yml"
    _write_sidecar(
        sidecar,
        cues="""\
  - at: 2.0s
    until: 4.5s
    position: top-right
    text: |-
      Literal {tag} and \\N
      Next line
""",
    )
    spec = postprocessor.load_caption_spec(sidecar, duration=5.0)
    media = postprocessor.MediaInfo(
        fps=Fraction(25, 1), duration=5.0, width=1920, height=1080
    )

    result = postprocessor.render_ass(spec, media)

    assert "PlayResX: 1920" in result
    assert "Style: TopRight,Fira Code,40" in result
    assert ",9,80,80,90,1" in result
    assert "&H4D000000" in result
    assert "Dialogue: 0,0:00:02.00,0:00:04.50,TopRight" in result
    assert r"{\fad(250,250)}Literal \{tag\} and \\N\NNext line" in result


def test_probe_uses_measured_average_fps(
    postprocessor: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = {
        "streams": [
            {
                "avg_frame_rate": "30000/1001",
                "r_frame_rate": "30/1",
                "width": 1920,
                "height": 1080,
            }
        ],
        "format": {"duration": "28.840000"},
    }
    run = Mock(return_value=SimpleNamespace(stdout=json.dumps(payload), returncode=0))
    monkeypatch.setattr(postprocessor.subprocess, "run", run)

    result = postprocessor.probe_media(Path("rendered.mp4"))

    assert result.fps == Fraction(30000, 1001)
    assert result.duration == 28.84
    command = run.call_args.args[0]
    assert command[0] == "ffprobe"
    assert command[-1] == "rendered.mp4"


def test_probe_falls_back_to_rendered_fps(
    postprocessor: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = {
        "streams": [
            {
                "avg_frame_rate": "0/0",
                "r_frame_rate": "25/1",
                "width": 1920,
                "height": 1080,
            }
        ],
        "format": {"duration": "28.84"},
    }
    monkeypatch.setattr(
        postprocessor,
        "_run",
        Mock(return_value=SimpleNamespace(stdout=json.dumps(payload))),
    )

    assert postprocessor.probe_media(Path("rendered.mp4")).fps == Fraction(25, 1)


def test_gif_filter_uses_measured_fps_and_optimized_settings(
    postprocessor: ModuleType,
) -> None:
    result = postprocessor.gif_filter(
        fps=Fraction(30000, 1001), scale=(1280, 720), colors=128
    )

    assert "fps=30000/1001" in result
    assert "scale=1280:720:flags=lanczos" in result
    assert "palettegen=stats_mode=diff:max_colors=128" in result
    assert "paletteuse=dither=bayer:bayer_scale=3" in result


def test_font_check_rejects_fontconfig_substitution(
    postprocessor: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = Mock(return_value=SimpleNamespace(stdout="DejaVu Sans Mono\n"))
    monkeypatch.setattr(postprocessor, "_run", run)

    with pytest.raises(RuntimeError, match="cannot resolve"):
        postprocessor.ensure_font_available("Fira Code")
