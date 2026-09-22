"""Worker-local candidate writes for the visual capture protocol."""

from __future__ import annotations

from dataclasses import dataclass, field
import inspect
import json
import os
from pathlib import Path
import threading

from tests.ace.tui.visual._visual_capture_paths import (
    VisualCaptureError,
    VisualCaptureRoots,
    atomic_write_bytes,
    atomic_write_text,
    capture_artifact_id,
    canonical_golden_path,
    png_dimensions,
    sha256_bytes,
    worker_directory,
)
from tests.ace.tui.visual._visual_capture_records import (
    CaptureRecord,
    ComparisonSettings,
    WorkerSessionRecord,
)


_ENV_RATIO = "SASE_VISUAL_PNG_MAX_DIFF_RATIO"
_ENV_THRESHOLD = "SASE_VISUAL_PNG_MATERIAL_DIFF_THRESHOLD"
_ENV_MATERIAL_PIXELS = "SASE_VISUAL_PNG_MAX_MATERIAL_DIFF_PIXELS"
_INTERNAL_FRAMES = frozenset(
    {
        "_visual_capture_store.py",
        "_visual_capture.py",
        "_visual_capture_paths.py",
        "_visual_capture_plugin.py",
        "_visual_capture_records.py",
        "_visual_capture_session.py",
        "_visual_capture_inventory.py",
        "png_diff.py",
    }
)


@dataclass
class VisualCaptureSession:
    """Worker-local candidate writer used by ACE and pager fixtures."""

    capture_dir: Path
    run_id: str
    worker_id: str
    repo_root: Path
    roots: VisualCaptureRoots
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _captures: list[CaptureRecord] = field(default_factory=list, repr=False)
    _owned_paths: dict[str, str] = field(default_factory=dict, repr=False)
    _sequence: int = field(default=0, repr=False)
    _node_sequence: dict[str, int] = field(default_factory=dict, repr=False)

    def owns_root(self, snapshot_root: Path) -> bool:
        """Return whether *snapshot_root* is an ACE or pager golden root."""
        return self.roots.identity_for(snapshot_root) is not None

    @property
    def captures(self) -> tuple[CaptureRecord, ...]:
        with self._lock:
            return tuple(self._captures)

    @property
    def worker_dir(self) -> Path:
        return worker_directory(self.capture_dir, self.worker_id)

    def record_capture(
        self,
        *,
        name: str,
        png_bytes: bytes,
        snapshot_root: Path,
        node_id: str,
        source_svg: str | None = None,
        test_file: str | None = None,
        test_line: int | None = None,
        max_diff_pixels: int | None = None,
        max_diff_ratio: float | None = None,
        material_diff_threshold: int | None = None,
        max_material_diff_pixels: int | None = None,
    ) -> CaptureRecord:
        """Write candidate PNG/SVG and metadata without touching goldens."""
        identity, canonical = canonical_golden_path(
            snapshot_root=snapshot_root,
            name=name,
            repo_root=self.repo_root,
            roots=self.roots,
        )
        width, height = png_dimensions(png_bytes)
        source_file, source_line = _call_location(self.repo_root)
        with self._lock:
            owner = self._owned_paths.get(canonical)
            if owner is not None:
                raise VisualCaptureError(
                    "duplicate canonical golden path "
                    f"{canonical}: owned by {owner} and {node_id}"
                )
            self._sequence += 1
            sequence = self._sequence
            node_sequence = self._node_sequence.get(node_id, 0) + 1
            self._node_sequence[node_id] = node_sequence
            artifact_id = capture_artifact_id(
                node_id=node_id,
                canonical_golden_path=canonical,
                sequence=sequence,
                worker_id=self.worker_id,
            )
            png_relpath = f"workers/{self.worker_id}/candidates/{artifact_id}.png"
            svg_relpath = (
                None
                if source_svg is None
                else f"workers/{self.worker_id}/candidates/{artifact_id}.svg"
            )
            record = CaptureRecord(
                run_id=self.run_id,
                worker_id=self.worker_id,
                sequence=sequence,
                node_sequence=node_sequence,
                artifact_id=artifact_id,
                node_id=node_id,
                snapshot_name=name,
                canonical_golden_path=canonical,
                root_identity=identity,
                test_file=_repo_relative_optional(test_file, self.repo_root),
                test_line=test_line,
                source_file=source_file,
                source_line=source_line,
                candidate_png_relpath=png_relpath,
                candidate_svg_relpath=svg_relpath,
                candidate_sha256=sha256_bytes(png_bytes),
                png_width=width,
                png_height=height,
                comparison_settings=ComparisonSettings(
                    max_diff_pixels=max_diff_pixels,
                    max_diff_ratio=max_diff_ratio,
                    material_diff_threshold=material_diff_threshold,
                    max_material_diff_pixels=max_material_diff_pixels,
                    env_max_diff_ratio=os.environ.get(_ENV_RATIO),
                    env_material_diff_threshold=os.environ.get(_ENV_THRESHOLD),
                    env_max_material_diff_pixels=os.environ.get(_ENV_MATERIAL_PIXELS),
                ),
            )
            png_path = self.capture_dir / png_relpath
            atomic_write_bytes(png_path, png_bytes)
            if source_svg is not None and svg_relpath is not None:
                atomic_write_text(self.capture_dir / svg_relpath, source_svg)
            record_path = self.worker_dir / "captures" / f"{artifact_id}.json"
            atomic_write_text(
                record_path,
                json.dumps(record.to_dict(), indent=2, sort_keys=True) + "\n",
            )
            self._owned_paths[canonical] = node_id
            self._captures.append(record)
            return record

    def write_worker_session(self, record: WorkerSessionRecord) -> Path:
        """Atomically write this worker's execution-evidence record."""
        if record.worker_id != self.worker_id or record.run_id != self.run_id:
            raise VisualCaptureError(
                "worker session record does not match this capture session"
            )
        path = self.worker_dir / "session.json"
        atomic_write_text(
            path,
            json.dumps(record.to_dict(), indent=2, sort_keys=True) + "\n",
        )
        return path


def _repo_relative_optional(value: str | None, repo_root: Path) -> str | None:
    if value is None:
        return None
    path = Path(value)
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except (OSError, ValueError):
        return path.as_posix()


def _call_location(repo_root: Path) -> tuple[str | None, int | None]:
    frame = inspect.currentframe()
    try:
        while frame is not None:
            filename = frame.f_code.co_filename
            if Path(filename).name not in _INTERNAL_FRAMES:
                return _repo_relative_optional(filename, repo_root), frame.f_lineno
            frame = frame.f_back
    finally:
        del frame
    return None, None
