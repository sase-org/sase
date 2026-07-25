"""Guard against host-dependent path literals in the visual fixture tree.

PNG goldens are compared byte-exactly, so any fixture string that lies under the
generating host's home directory renders differently elsewhere: some panes
abbreviate ``$HOME`` to ``~`` while others paint the full path including the
username. Both shapes turn a golden into a host-specific artifact that only
passes on the machine that produced it.

Fixtures that need a home-like path must derive it from the same import-time
``$HOME`` snapshot the renderer uses (see ``_HOME`` in
``axe_entry_editor_rendering``) so every host abbreviates identically, or use a
synthetic home such as ``/home/visual`` that belongs to no real user.

The check has two prongs, because either alone leaves a gap:

* The running host's home prefix, which catches homes that do not live under
  ``/home`` at all (``/Users/<name>``, ``/root``).
* Any ``/home/<owner>`` whose owner is not in ``_SYNTHETIC_HOME_OWNERS``. The
  host-prefix prong only fires on the machine whose home leaked, so it would
  pass in CI while ``/home/<someone-else>`` sat in the fixtures; this prong
  flags a foreign account's home from anywhere.

Two placement details matter:

* This check lives outside ``tests/ace/tui/visual/`` so it runs in the default
  (non-visual) lane without pulling in the pinned-renderer session fixtures.
* It compares against ``_HOME`` rather than ``Path.home()`` because the autouse
  ``_isolate_sase_home`` fixture points ``$HOME`` at a tmpdir during tests,
  which would make a live lookup vacuous.
"""

from __future__ import annotations

import re
from pathlib import Path

from sase.ace.tui.modals.axe_entry_editor_rendering import _HOME

_VISUAL_ROOT = Path(__file__).parent / "visual"
_FIXTURE_SUFFIXES = {".py", ".json", ".yml", ".yaml", ".diff", ".md", ".txt"}

# Synthetic home owners the visual fixtures are allowed to name. Each belongs to
# no real account, so every host renders them identically.
_SYNTHETIC_HOME_OWNERS = frozenset({"visual", "user", "operator"})
# The lookbehind keeps ``/home`` anchored to a path root so an interior segment
# such as ``chezmoi/home/dot_config`` is not read as owner ``dot_config``.
_HOME_DIR_RE = re.compile(r"(?<![A-Za-z0-9._-])/home/([A-Za-z0-9._-]+)")


def _visual_sources() -> list[Path]:
    """Return the fixture-bearing files of the visual suite."""
    return sorted(
        path
        for path in _VISUAL_ROOT.rglob("*")
        if path.is_file()
        and path.suffix in _FIXTURE_SUFFIXES
        and "snapshots" not in path.relative_to(_VISUAL_ROOT).parts
        and "__pycache__" not in path.parts
    )


def _offending_owners(line: str) -> set[str]:
    """Return the real-account home owners this line names, if any."""
    return {
        owner
        for owner in _HOME_DIR_RE.findall(line)
        if owner not in _SYNTHETIC_HOME_OWNERS
    }


def test_visual_fixtures_embed_no_host_home_paths() -> None:
    host_home = _HOME.rstrip("/")
    assert host_home, "the host home directory must be resolvable"

    sources = _visual_sources()
    assert sources, f"no visual fixture sources found under {_VISUAL_ROOT}"

    offenders = [
        f"{path.relative_to(_VISUAL_ROOT)}:{lineno}: {line.strip()}"
        for path in sources
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
        )
        if host_home in line or _offending_owners(line)
    ]

    assert not offenders, (
        "visual fixtures must not embed a real account's home directory "
        f"(host home {host_home}; allowed synthetic owners "
        f"{sorted(_SYNTHETIC_HOME_OWNERS)}); derive the path from the renderer's "
        "_HOME snapshot or use a synthetic home like /home/visual:\n"
        + "\n".join(offenders)
    )
