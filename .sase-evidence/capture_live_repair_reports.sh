#!/bin/sh
set -u
EVIDENCE_DIR=.sase-evidence
capture() {
  host="$1"
  label="$2"
  remote_script="$3"
  started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf 'START %s host=%s utc=%s\n' "$label" "$host" "$started"
  set +e
  ssh -T "$host" 'zsh -lic "bash -s"' < "$remote_script" > "$EVIDENCE_DIR/$label.json" 2> "$EVIDENCE_DIR/$label.stderr"
  rc=$?
  set -e
  finished="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  {
    printf 'host=%s\ncommand=sase agent sync --repair-revisions --project sase --json\nstarted_utc=%s\nfinished_utc=%s\nexit_code=%s\n' "$host" "$started" "$finished" "$rc"
    sha256sum "$EVIDENCE_DIR/$label.json"
    sha256sum "$EVIDENCE_DIR/$label.stderr"
    cat "$EVIDENCE_DIR/$label.stderr"
  } > "$EVIDENCE_DIR/$label.meta"
  printf 'DONE %s exit=%s bytes=%s\n' "$label" "$rc" "$(wc -c < "$EVIDENCE_DIR/$label.json")"
  return "$rc"
}
rc1=0
rc2=0
capture athena report_athena_sase_verified .sase-evidence/remote_capture_athena_sase.sh || rc1=$?
capture apollo report_apollo_sase_verified .sase-evidence/remote_capture_apollo_sase.sh || rc2=$?
printf 'capture_rc_athena=%s\ncapture_rc_apollo=%s\n' "$rc1" "$rc2"
sha256sum "$EVIDENCE_DIR/report_athena_sase_verified.json" "$EVIDENCE_DIR/report_apollo_sase_verified.json"
[ "$rc1" -eq 0 ] && [ "$rc2" -eq 0 ]
