"""Hand-written zsh helpers prepended to every generated compsys script."""

from __future__ import annotations

from typing import Final

from sase.completion.kinds import VOLATILE_KIND_TTL_SECONDS


def _volatile_ttl_cases() -> str:
    """Render per-kind ``sase-<kind>) ttl=N`` policy arms from Python.

    The single source is ``VOLATILE_KIND_TTL_SECONDS`` in
    ``sase.completion.kinds``, so the zsh in-shell TTLs cannot drift from
    the disk-cache and bash TTLs.
    """
    return "\n".join(
        f"    sase-{kind.value}) ttl={ttl:g} ;;"
        for kind, ttl in sorted(
            VOLATILE_KIND_TTL_SECONDS.items(), key=lambda item: item[0].value
        )
    )


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
_ZSH_PREAMBLE_TEMPLATE: Final = """\
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
# when nothing more specific is set. Volatile kinds (see
# VOLATILE_KIND_TTL_SECONDS) carry their own shorter window below.
__sase_cache_policy() {
  local ttl=${SASE_COMPLETION_CACHE_TTL:-60}
  case $1 in
__SASE_VOLATILE_TTL_CASES__
  esac
  local -a stamp
  stamp=( "$1"(Nms+$ttl) )
  (( $#stamp ))
}

__sase_candidate_lines() {
  local kind=$1 selector=${2-}
  local key="sase-$kind"
  if [[ -n $selector ]]; then
    # A scoped fetch is cached under kind plus selector, never under the
    # merged key, so one proposal's decisions cannot leak into another's.
    key+="-${selector//[^A-Za-z0-9_]/_}"
  fi
  local policy
  zstyle -s ":completion:${curcontext}:" cache-policy policy ||
    zstyle ":completion:${curcontext}:" cache-policy __sase_cache_policy
  if ! _retrieve_cache "$key"; then
    if [[ -n $selector ]]; then
      reply=( ${(f)"$(__sase_run completion candidates $kind -S "$selector" 2>/dev/null)"} )
    else
      reply=( ${(f)"$(__sase_run completion candidates $kind 2>/dev/null)"} )
    fi
    _store_cache "$key" reply
  fi
}

# Fetches candidates for $1 (a value kind) through the pre-argparse fast
# path, caching the raw value/description pairs in zsh's own completion
# cache for the shell's lifetime -- this is the layer that absorbs
# per-keystroke pressure from tools like zsh-autosuggestions. The prefix is
# never passed to the fast path: the full kind is fetched once and cached,
# and `_describe` filters locally so one cached fetch serves a whole word.
#
# These helpers run inside zsh's completion system. Do not reset shell options
# around compsys calls here: `_main_complete` establishes option state such as
# `extendedglob`, and helpers like `_describe`, `compadd`, and `_alternative`
# rely on that environment while still restoring the user's interactive state.
__sase_candidates() {
  local kind=$1 selector=${2-}
  local -a lines entries
  local line value desc
  __sase_candidate_lines "$kind" "$selector"
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

# Prints the pending-plan proposal named on the command line, if any. Scans
# the words before the current one for `plan approve|reject` and returns
# the first bare word after it (the PLAN positional), skipping the values
# of options that take them. Prints nothing when no proposal is named, and
# callers then keep the merged fallback.
__sase_plan_proposal() {
  emulate -L zsh
  local -i i armed=0 skip=0 seen_plan=0
  local w
  for (( i=2; i<CURRENT; i++ )); do
    w=${words[i]}
    if (( skip )); then skip=0; continue; fi
    [[ -z $w ]] && continue
    case $w in
      -D|--decide|-k|--kind|-m|--model|-P|--project|-p|--prompt|-w|--wait)
        skip=1 ;;
      -*)
        ;;
      plan)
        seen_plan=1 ;;
      approve|reject)
        if (( seen_plan )); then armed=1; fi
        seen_plan=0 ;;
      *)
        if (( armed )); then
          print -r -- "$w"
          return 0
        fi
        seen_plan=0 ;;
    esac
  done
  return 1
}

# Completes plan-decision ids/values for `sase plan approve|reject -D`,
# scoped to the proposal named on the command line (`-S`) with a merged
# fallback when none is named.
__sase_plan_decision_candidates() {
  emulate -L zsh
  local selector
  if selector=$(__sase_plan_proposal); then
    __sase_candidates plan_decision "$selector"
  else
    __sase_candidates plan_decision
  fi
}

__sase_run_prompt_fragment() {
  emulate -L zsh
  local text=$PREFIX
  local marker kind before fragment base
  local -i index

  for (( index=${#text}; index >= 1; --index )); do
    case ${text[index]} in
      '#') marker='#'; kind='macro'; break ;;
      '%') marker='%'; kind='directive'; break ;;
      '@') marker='@'; kind='artifact_ref'; break ;;
      '+') marker='+'; kind='project_tag'; break ;;
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

# `sase run`'s PROMPT positional: native file completion plus stored macro
# names, since `sase run` accepts either a free-form prompt (often a path an
# editor buffer was drafted in), `#name`-style macro references, and
# embedded `#macro`, `%directive`, `@artifact-reference`, or `+project-tag`
# fragments.
__sase_run_prompt() {
  if __sase_run_prompt_fragment; then
    __sase_run_prompt_embedded $reply && return
  fi
  _alternative \\
    'macros:macro name:__sase_candidates macro' \\
    'files:file:_files'
}
"""


_ZSH_PREAMBLE: Final = _ZSH_PREAMBLE_TEMPLATE.replace(
    "__SASE_VOLATILE_TTL_CASES__", _volatile_ttl_cases()
)


def zsh_preamble() -> str:
    """Return the literal helper-function block for a generated zsh script."""
    return _ZSH_PREAMBLE.strip()


__all__ = ["zsh_preamble"]
