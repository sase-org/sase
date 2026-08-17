"""Hand-written zsh helpers prepended to every generated compsys script."""

from __future__ import annotations

# Resolves `sase` from PATH and skips ephemeral workspace venvs
# (`…/sase_<N>/.venv/bin/sase`), which vanish when the workspace is reaped.
# `_sase_candidates` is added in the wire phase and calls this helper.
_ZSH_PREAMBLE = """\
_sase_run() {
  emulate -L zsh
  local -a found
  local cmd
  found=( ${(f)"$(whence -p -a sase 2>/dev/null)"} )
  for cmd in $found; do
    if [[ ! $cmd =~ '/sase_[0-9]+/\\.venv/bin/sase$' ]]; then
      command "$cmd" "$@"
      return $?
    fi
  done
  command sase "$@"
}
"""


def zsh_preamble() -> str:
    """Return the literal helper-function block for a generated zsh script."""
    return _ZSH_PREAMBLE.strip()


__all__ = ["zsh_preamble"]
