#!/usr/bin/env bash
set -Eeuo pipefail

REPORT_DIR="${SASE_SMOKE_RESULTS_DIR:-/results}"
mkdir -p "$REPORT_DIR"

REPORT="$REPORT_DIR/pypi-smoke-$(date -u +%Y%m%dT%H%M%SZ).log"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

exec > >(tee "$REPORT") 2>&1

LAST_JSON=""

section() {
    printf '\n## %s\n' "$1"
}

run() {
    printf '\n+'
    printf ' %q' "$@"
    printf '\n'
    "$@"
}

capture_json() {
    local name="$1"
    shift
    local out="$TMP_DIR/$name"

    printf '\n+'
    printf ' %q' "$@"
    printf ' > %s\n' "$out"
    "$@" > "$out"
    python -m json.tool "$out" > /dev/null
    cat "$out"
    printf '\n'
    LAST_JSON="$out"
}

capture_json_lenient() {
    local name="$1"
    shift
    local out="$TMP_DIR/$name"
    local err="$TMP_DIR/$name.stderr"
    local status

    printf '\n+'
    printf ' %q' "$@"
    printf ' > %s\n' "$out"
    set +e
    "$@" > "$out" 2> "$err"
    status=$?
    set -e
    if [ -s "$err" ]; then
        cat "$err"
    fi
    if [ -s "$out" ]; then
        cat "$out"
        printf '\n'
    fi
    python -m json.tool "$out" > /dev/null
    printf 'command_exit_code=%s\n' "$status"
    LAST_JSON="$out"
}

assert_version_inventory() {
    local json_path="$1"
    local label="$2"

    python - "$json_path" "$label" <<'PY'
import json
import os
import re
import sys

path = sys.argv[1]
label = sys.argv[2]

with open(path, encoding="utf-8") as handle:
    payload = json.load(handle)

def norm(value: object) -> str:
    return str(value or "").lower().replace("_", "-")

def spec_name(spec: str, fallback: str) -> str:
    spec = spec.strip()
    if not spec:
        return fallback
    return re.split(r"[<>=!~ ;\[]", spec, maxsplit=1)[0] or fallback

def pinned(spec: str) -> tuple[str, str] | None:
    match = re.match(r"^\s*([A-Za-z0-9_.-]+)(?:\[[^\]]+\])?==([^ ;]+)\s*$", spec)
    if not match:
        return None
    return norm(match.group(1)), match.group(2)

packages = {norm(record.get("name")): record for record in payload.get("packages", [])}
errors: list[str] = []

required = ["sase", "sase-core-rs"]
for env_name, fallback in (
    ("SASE_GITHUB_SPEC", "sase-github"),
    ("SASE_TELEGRAM_SPEC", "sase-telegram"),
):
    if os.environ.get(env_name, "").strip():
        required.append(spec_name(os.environ[env_name], fallback))

for name in required:
    if norm(name) not in packages:
        errors.append(f"{label}: package {name!r} was not reported by sase version -j")

for env_name, fallback in (
    ("SASE_SPEC", "sase"),
    ("SASE_GITHUB_SPEC", "sase-github"),
    ("SASE_TELEGRAM_SPEC", "sase-telegram"),
    ("SASE_CORE_RS_SPEC", "sase-core-rs"),
):
    spec = os.environ.get(env_name, "").strip()
    parsed = pinned(spec)
    if parsed is None:
        continue
    package, expected = parsed
    record = packages.get(package)
    if record is None:
        errors.append(f"{label}: pinned package {package!r} was not reported")
        continue
    actuals = {
        str(record.get("display_version") or ""),
        str(record.get("distribution_version") or ""),
        str(record.get("source_version") or ""),
    }
    if expected not in actuals:
        errors.append(
            f"{label}: {package} expected {expected}, saw "
            f"display={record.get('display_version')!r} "
            f"dist={record.get('distribution_version')!r} "
            f"source={record.get('source_version')!r}"
        )

if errors:
    raise SystemExit("\n".join(errors))

print(f"{label}: version inventory assertions passed ({len(packages)} packages)")
PY
}

assert_chop_inventory() {
    local list_json="$1"
    local doctor_json="$2"
    local label="$3"
    local telegram_expected="$4"

    python - "$list_json" "$doctor_json" "$label" "$telegram_expected" <<'PY'
import json
import sys

list_path, doctor_path, label, telegram_expected = sys.argv[1:5]

with open(list_path, encoding="utf-8") as handle:
    list_payload = json.load(handle)
with open(doctor_path, encoding="utf-8") as handle:
    doctor_payload = json.load(handle)

def norm(value: object) -> str:
    return str(value or "").lower().replace("_", "-")

chops = list_payload.get("chops", {})
available_chops = {
    norm(chop.get("name"))
    for chop in chops.get("available", [])
    if isinstance(chop, dict)
}
errors: list[str] = []

if telegram_expected == "1":
    telegram_chops = {"tg-inbound", "tg-outbound"}
    if not telegram_chops.issubset(available_chops):
        missing = ", ".join(sorted(telegram_chops - available_chops))
        errors.append(f"{label}: missing Telegram chop script(s): {missing}")

if doctor_payload.get("status") == "ERROR":
    errors.append(f"{label}: chop doctor status is ERROR")
for check in doctor_payload.get("checks", []):
    if check.get("status") == "ERROR":
        errors.append(
            f"{label}: chop doctor check {check.get('id')} failed: "
            f"{check.get('summary')}"
        )

if errors:
    raise SystemExit("\n".join(errors))

print(
    f"{label}: chop inventory assertions passed "
    f"({len(chops.get('configured', []))} configured chop(s))"
)
PY
}

assert_no_doctor_errors() {
    local json_path="$1"
    local label="$2"

    python - "$json_path" "$label" <<'PY'
import json
import sys

path, label = sys.argv[1:3]

with open(path, encoding="utf-8") as handle:
    payload = json.load(handle)

errors: list[str] = []
if payload.get("status") == "ERROR":
    errors.append(f"{label}: doctor status is ERROR")
for check in payload.get("checks", []):
    if check.get("status") == "ERROR":
        errors.append(
            f"{label}: doctor check {check.get('id')} failed: {check.get('summary')}"
        )

if errors:
    raise SystemExit("\n".join(errors))

counts = payload.get("counts", {})
print(
    f"{label}: doctor assertions passed "
    f"(OK={counts.get('OK', 0)}, WARN={counts.get('WARN', 0)}, "
    f"SKIP={counts.get('SKIP', 0)})"
)
PY
}

assert_xprompt_catalog() {
    local json_path="$1"

    python - "$json_path" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    payload = json.load(handle)

if not isinstance(payload, list) or not payload:
    raise SystemExit("xprompt catalog is empty or not a JSON array")
if not any(item.get("name") for item in payload if isinstance(item, dict)):
    raise SystemExit("xprompt catalog has no named entries")

print(f"xprompt catalog assertions passed ({len(payload)} entries)")
PY
}

assert_config_dump() {
    local path="$1"

    python - "$path" <<'PY'
import sys
from pathlib import Path

text = Path(sys.argv[1]).read_text(encoding="utf-8")
required = ("llm_provider:", "axe:", "xprompts:")
missing = [item for item in required if item not in text]
if missing:
    raise SystemExit(f"config dump missing expected keys: {', '.join(missing)}")
print("config dump assertions passed")
PY
}

tool_python() {
    if [ -n "${SASE_TOOL_VENV:-}" ] && [ -x "$SASE_TOOL_VENV/bin/python" ]; then
        printf '%s\n' "$SASE_TOOL_VENV/bin/python"
        return
    fi
    local tool_dir
    tool_dir="$(uv tool dir)"
    printf '%s\n' "$tool_dir/sase/bin/python"
}

chop_checks_for() {
    local sase_cmd="$1"
    local label="$2"
    local telegram_expected="0"
    if [ -n "${SASE_TELEGRAM_SPEC:-}" ]; then
        telegram_expected="1"
    fi

    capture_json "${label}-chop-list.json" "$sase_cmd" axe chop list -a -j
    local list_json="$LAST_JSON"
    capture_json_lenient "${label}-chop-doctor.json" "$sase_cmd" axe chop doctor -j
    local doctor_json="$LAST_JSON"
    assert_chop_inventory "$list_json" "$doctor_json" "$label" "$telegram_expected"
}

version_and_core_checks_for() {
    local sase_cmd="$1"
    local python_cmd="$2"
    local label="$3"

    capture_json "${label}-version.json" "$sase_cmd" version -j
    assert_version_inventory "$LAST_JSON" "$label"
    run "$python_cmd" -c 'import sase_core_rs; print(sase_core_rs.__file__)'
}

section "Environment"
printf 'report=%s\n' "$REPORT"
printf 'date_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
printf 'SASE_SPEC=%s\n' "$SASE_SPEC"
printf 'SASE_GITHUB_SPEC=%s\n' "${SASE_GITHUB_SPEC:-}"
printf 'SASE_TELEGRAM_SPEC=%s\n' "${SASE_TELEGRAM_SPEC:-}"
printf 'SASE_CORE_RS_SPEC=%s\n' "${SASE_CORE_RS_SPEC:-}"
run python --version
run uv --version
run git --version
run node --version
run npm --version
run gh --version
run bash -lc 'claude --version || true'
run command -v sase

TOOL_PYTHON="$(tool_python)"

section "uv tool install flavor"
version_and_core_checks_for "sase" "$TOOL_PYTHON" "uv-tool"
chop_checks_for "sase" "uv-tool"

section "Top-level doctor"
capture_json_lenient "doctor.json" sase doctor -j
assert_no_doctor_errors "$LAST_JSON" "uv-tool"

section "Provider-independent CLI usage"
run sase --help
run sase bead --help
run sase config show
CONFIG_DUMP="$TMP_DIR/config.yml"
run bash -c 'sase config show > "$1"' _ "$CONFIG_DUMP"
assert_config_dump "$CONFIG_DUMP"
capture_json "xprompt-list.json" sase xprompt list
assert_xprompt_catalog "$LAST_JSON"

SCRATCH_REPO="$TMP_DIR/scratch-repo"
run mkdir -p "$SCRATCH_REPO"
run git -C "$SCRATCH_REPO" init
run git -C "$SCRATCH_REPO" config user.email smoke@example.invalid
run git -C "$SCRATCH_REPO" config user.name "PyPI Smoke"
run mkdir -p "$SCRATCH_REPO/sdd/tales/209901"
run bash -c 'printf "# Smoke plan\n\nProvider-independent PyPI smoke plan.\n" > "$1"' _ \
    "$SCRATCH_REPO/sdd/tales/209901/smoke.md"
run bash -c 'cd "$1" && sase bead init' _ "$SCRATCH_REPO"
run bash -c 'cd "$1" && sase bead create -t "Smoke plan" -T "plan(sdd/tales/209901/smoke.md)" --tier plan' _ \
    "$SCRATCH_REPO"
run bash -c 'cd "$1" && sase bead list | tee "$2" && grep -F "Smoke plan" "$2"' _ \
    "$SCRATCH_REPO" "$TMP_DIR/bead-list.txt"
run bash -c 'cd "$1" && sase bead stats' _ "$SCRATCH_REPO"

section "uv pip install flavor"
PIP_ENV="$TMP_DIR/pip-env"
run uv venv --python 3.12 "$PIP_ENV"
pip_specs=("$SASE_SPEC")
if [ -n "${SASE_GITHUB_SPEC:-}" ]; then
    pip_specs+=("$SASE_GITHUB_SPEC")
fi
if [ -n "${SASE_TELEGRAM_SPEC:-}" ]; then
    pip_specs+=("$SASE_TELEGRAM_SPEC")
fi
run uv pip install --python "$PIP_ENV/bin/python" --refresh "${pip_specs[@]}"
version_and_core_checks_for "$PIP_ENV/bin/sase" "$PIP_ENV/bin/python" "uv-pip"
chop_checks_for "$PIP_ENV/bin/sase" "uv-pip"

section "Result"
printf 'PASS: PyPI smoke checks completed successfully.\n'
printf 'Report: %s\n' "$REPORT"
