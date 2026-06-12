#!/usr/bin/env bash
set -Eeuo pipefail

export PATH="$HOME/.local/bin:/usr/local/bin:$PATH"

mode="${1:-check}"
if [ "$#" -gt 0 ]; then
    shift
fi

: "${SASE_SPEC:=sase}"
: "${SASE_GITHUB_SPEC:=sase-github}"
: "${SASE_TELEGRAM_SPEC:=sase-telegram}"
: "${SASE_CORE_RS_SPEC:=}"

wipe_sase_state() {
    rm -rf "$HOME/.sase" "$HOME/.config/sase"

    local tool_dir
    tool_dir="$(uv tool dir)"
    rm -rf "$tool_dir/sase"
}

install_sase_tool() {
    mkdir -p "$HOME/.config" "$HOME/.local/bin"

    local cmd
    cmd=(uv tool install --force --refresh "$SASE_SPEC" --python 3.12)
    if [ -n "${SASE_GITHUB_SPEC:-}" ]; then
        cmd+=(--with "$SASE_GITHUB_SPEC")
    fi
    if [ -n "${SASE_TELEGRAM_SPEC:-}" ]; then
        cmd+=(--with "$SASE_TELEGRAM_SPEC")
    fi

    printf 'Installing PyPI tool:'
    printf ' %q' "${cmd[@]}"
    printf '\n'
    "${cmd[@]}"

    export SASE_TOOL_DIR
    export SASE_TOOL_VENV
    SASE_TOOL_DIR="$(uv tool dir)"
    SASE_TOOL_VENV="$SASE_TOOL_DIR/sase"

    command -v sase
}

wipe_sase_state
install_sase_tool

case "$mode" in
    check)
        exec /usr/local/bin/pypi-smoke-check "$@"
        ;;
    shell)
        cd /work
        exec bash -l
        ;;
    *)
        exec "$mode" "$@"
        ;;
esac
