"""Synthetic prompt-search corpus used by the fresh-process benchmark."""

from __future__ import annotations

import hashlib
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"

COMMON_QUERY = "promptbench-common"
RARE_TAIL_QUERY = "promptbench-tail-rare-7999"
NO_MATCH_QUERY = "promptbench-no-such-token"
METADATA_QUERY = "promptbench-meta-only"

DEFAULT_MONTH = "202609"
DEFAULT_ARCHIVE_COUNT = 5_000
DEFAULT_LOCAL_COUNT = 8_000
DEFAULT_DUPLICATE_COUNT = 200

_MULTILINGUAL = (
    "cafe\u0301 resume\u0301 naive facade jalapeno "
    "東京 Καλημερα Здравствуйте مرحبا שלום नमस्ते 🙂"
)


@dataclass(frozen=True)
class _CorpusPaths:
    root: Path
    archive_root: Path
    sase_home: Path


def _insert_repo_paths() -> None:
    for path in (str(SRC_ROOT), str(REPO_ROOT)):
        if path not in sys.path:
            sys.path.insert(0, path)


def _timestamp(index: int) -> str:
    return (datetime(2026, 9, 1, 0, 0, 0) + timedelta(seconds=index)).strftime(
        "%y%m%d_%H%M%S"
    )


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _fence(index: int, fence_index: int) -> str:
    return (
        "```python\n"
        f"# synthetic fence {index}:{fence_index} {_MULTILINGUAL}\n"
        f"value_{index}_{fence_index} = '{COMMON_QUERY}:{index}:{fence_index}'\n"
        "```\n"
    )


def _body(
    *,
    index: int,
    source: str,
    include_common: bool = True,
    rare_tail: bool = False,
    metadata_ref: bool = False,
) -> str:
    head_parts = [f"Promptbench {source} prompt {index:05d}"]
    if include_common:
        head_parts.append(COMMON_QUERY)
    if metadata_ref:
        head_parts.append(f"@{METADATA_QUERY}")
    lines = [
        " ".join(head_parts),
        f"Review {_MULTILINGUAL} and inline `{COMMON_QUERY}-{source}-{index}`.",
        "Keep literal-zone handling represented without executing any prompt refs.",
    ]

    fence_count = 3 + (index % 4)
    if index % 257 == 0:
        fence_count += 8
    for fence_index in range(fence_count):
        lines.append(_fence(index, fence_index))

    if rare_tail:
        lines.append(("tail filler " + _MULTILINGUAL + " ") * 80 + RARE_TAIL_QUERY)
    return "\n".join(lines) + "\n"


def _archive_header(index: int) -> str:
    artifact_count = 12 if index % 101 == 0 else 1
    artifacts = "\n".join(
        "  - "
        f"[artifact-{index:05d}-{artifact_index:02d}.txt]"
        f"(../../artifacts/{DEFAULT_MONTH}/artifact-{index:05d}-{artifact_index:02d}.txt)"
        for artifact_index in range(artifact_count)
    )
    return (
        "- **PLAN:** "
        f"[{DEFAULT_MONTH}/prompt_search_performance.md]"
        "(https://example.invalid/plans/202609/prompt_search_performance.md)\n"
        "- **ARTIFACTS:**\n"
        f"{artifacts}\n"
    )


def _archive_document(index: int, body: str) -> str:
    tags = ["archive", f"bucket-{index % 17}"]
    if index % 499 == 0:
        tags.append(METADATA_QUERY)
    tag_lines = "\n".join(f"  - {tag}" for tag in tags)
    body_text = body.strip()
    return (
        "---\n"
        f"sha256: {_sha256(body_text)}\n"
        f"timestamp: {_timestamp(index)}\n"
        "prompt_tags:\n"
        f"{tag_lines}\n"
        "---\n"
        f"{_archive_header(index)}\n"
        f"{body}"
    )


def _seed_archive(
    archive_root: Path,
    *,
    archive_count: int,
) -> list[str]:
    archive_texts: list[str] = []
    prompts_dir = archive_root / "prompts" / DEFAULT_MONTH
    prompts_dir.mkdir(parents=True, exist_ok=True)
    for index in range(archive_count):
        body = _body(
            index=index,
            source="archive",
            rare_tail=index == archive_count - 1 and archive_count > 0,
            metadata_ref=index % 613 == 0,
        )
        archive_texts.append(body.strip())
        path = prompts_dir / f"prompt_{index:05d}.md"
        path.write_text(_archive_document(index, body), encoding="utf-8")

    return archive_texts


def _seed_local_history(
    sase_home: Path,
    *,
    archive_texts: Sequence[str],
    local_count: int,
    duplicate_count: int,
) -> None:
    _insert_repo_paths()
    from sase.history.prompt_store import PromptEntry, save_prompt_history

    previous_home = os.environ.get("SASE_HOME")
    os.environ["SASE_HOME"] = str(sase_home)
    try:
        entries: list[PromptEntry] = []
        duplicates = min(duplicate_count, len(archive_texts), local_count)
        for index in range(local_count):
            if index < duplicates:
                text = archive_texts[index]
            else:
                text = _body(
                    index=index,
                    source="local",
                    rare_tail=index == local_count - 1 and local_count > 0,
                    metadata_ref=index % 787 == 0,
                ).strip()
            ts = _timestamp(len(archive_texts) + index)
            entries.append(
                PromptEntry(
                    text=text,
                    timestamp=ts,
                    last_used=ts,
                    cancelled=index % 997 == 0,
                )
            )
        if not save_prompt_history(entries):
            raise RuntimeError("failed to seed prompt-history shards")
    finally:
        if previous_home is None:
            os.environ.pop("SASE_HOME", None)
        else:
            os.environ["SASE_HOME"] = previous_home


def _seed_corpus(
    root: Path,
    *,
    archive_count: int,
    local_count: int,
    duplicate_count: int,
) -> _CorpusPaths:
    archive_root = root / "archive"
    sase_home = root / "home" / ".sase"
    archive_texts = _seed_archive(
        archive_root,
        archive_count=archive_count,
    )
    _seed_local_history(
        sase_home,
        archive_texts=archive_texts,
        local_count=local_count,
        duplicate_count=duplicate_count,
    )
    return _CorpusPaths(root=root, archive_root=archive_root, sase_home=sase_home)
