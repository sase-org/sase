"""Hand-written zsh helpers prepended to every generated compsys script."""

from __future__ import annotations

# Double-underscore names are deliberate: every generated per-command
# function is named `_sase_<path parts>` (see `_function_name` in
# emit_zsh.py), and `sase run` is a real top-level command, so a
# single-underscore `_sase_run` helper would be silently redefined -- and
# shadowed -- by the generated completer for `sase run`. No argparse path
# can ever produce a leading double underscore, so `__sase_*` is safe.
#
# Resolves `sase` from PATH and skips ephemeral workspace venvs
# (`…/sase_<N>/.venv/bin/sase`), which vanish when the workspace is reaped.
# `__sase_candidates` calls this helper for every kinded slot.
_ZSH_PREAMBLE = """\
__sase_run() {
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

# Default in-shell freshness window for a cached kind, in seconds. A user's
# own `zstyle ':completion:*:*:sase-<kind>:*' cache-policy …` still wins;
# this only supplies the fallback `_retrieve_cache`/`_store_cache` consult
# when nothing more specific is set.
__sase_cache_policy() {
  local -a stamp
  stamp=( "$1"(Nms+${SASE_COMPLETION_CACHE_TTL:-60}) )
  (( $#stamp ))
}

# Fetches candidates for $1 (a value kind) through the pre-argparse fast
# path, caching the raw value/description pairs in zsh's own completion
# cache for the shell's lifetime -- this is the layer that absorbs
# per-keystroke pressure from tools like zsh-autosuggestions. The prefix is
# never passed to the fast path: the full kind is fetched once and cached,
# and `_describe` filters locally so one cached fetch serves a whole word.
__sase_candidates() {
  emulate -L zsh
  local kind=$1
  local -a lines entries
  local policy line value desc
  zstyle -s ":completion:${curcontext}:" cache-policy policy ||
    zstyle ":completion:${curcontext}:" cache-policy __sase_cache_policy
  if ! _retrieve_cache "sase-$kind"; then
    lines=( ${(f)"$(__sase_run completion candidates $kind 2>/dev/null)"} )
    _store_cache "sase-$kind" lines
  fi
  for line in $lines; do
    value=${line%%$'\\t'*}
    if [[ $line == *$'\\t'* ]]; then
      desc=${line#*$'\\t'}
      entries+=( "${value//:/\\\\:}:${desc//:/\\\\:}" )
    else
      entries+=( "${value//:/\\\\:}" )
    fi
  done
  _describe -t "sase-$kind" "$kind" entries
}
"""


def zsh_preamble() -> str:
    """Return the literal helper-function block for a generated zsh script."""
    return _ZSH_PREAMBLE.strip()


__all__ = ["zsh_preamble"]
