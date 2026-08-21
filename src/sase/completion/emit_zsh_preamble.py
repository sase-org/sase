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

__sase_candidate_lines() {
  emulate -L zsh
  local kind=$1
  local policy
  zstyle -s ":completion:${curcontext}:" cache-policy policy ||
    zstyle ":completion:${curcontext}:" cache-policy __sase_cache_policy
  if ! _retrieve_cache "sase-$kind"; then
    reply=( ${(f)"$(__sase_run completion candidates $kind 2>/dev/null)"} )
    _store_cache "sase-$kind" reply
  fi
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
  local line value desc
  __sase_candidate_lines "$kind"
  lines=( $reply )
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

__sase_run_prompt_fragment() {
  emulate -L zsh
  local text=$PREFIX
  local marker kind before fragment base
  local -i index

  for (( index=${#text}; index >= 1; --index )); do
    case ${text[index]} in
      '#') marker='#'; kind='xprompt'; break ;;
      '%') marker='%'; kind='directive'; break ;;
      '@') marker='@'; kind='artifact_ref'; break ;;
    esac
  done
  [[ -n $marker ]] || return 1
  if (( index > 1 )); then
    before=${text[index - 1]}
    case "$before" in
      ' '|$'\\t'|'('|'"'|"'") ;;
      *) return 1 ;;
    esac
  fi
  fragment=${text[index + 1,-1]}
  case "$fragment" in
    *' '*|*$'\\t'*) return 1 ;;
  esac
  if (( index > 1 )); then
    base=${text[1,index - 1]}
  else
    base=
  fi
  reply=( "$kind" "$marker" "$fragment" "$base" )
}

__sase_run_prompt_embedded() {
  emulate -L zsh
  local kind=$1 marker=$2 fragment=$3 base=$4
  local -a lines values
  local line value
  __sase_candidate_lines "$kind"
  lines=( $reply )
  for line in $lines; do
    value=${line%%$'\\t'*}
    [[ $value == ${fragment}* ]] && values+=( "$value" )
  done
  (( $#values )) || return 1
  compadd -Q -P "$base$marker" -- $values
}

# `sase run`'s PROMPT positional: native file completion plus stored xprompt
# names, since `sase run` accepts either a free-form prompt (often a path an
# editor buffer was drafted in), `#name`-style xprompt references, and
# embedded `#xprompt`, `%directive`, or `@artifact-reference` fragments.
__sase_run_prompt() {
  emulate -L zsh
  if __sase_run_prompt_fragment; then
    __sase_run_prompt_embedded $reply && return
  fi
  _alternative \\
    'xprompts:xprompt name:__sase_candidates xprompt' \\
    'files:file:_files'
}
"""


def zsh_preamble() -> str:
    """Return the literal helper-function block for a generated zsh script."""
    return _ZSH_PREAMBLE.strip()


__all__ = ["zsh_preamble"]
