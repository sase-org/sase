#!/bin/sh
set -eu
EVIDENCE_DIR=.sase-evidence
HOST=apollo
BACKUP=/home/bryan/.sase/recovery-backups/sase-1nv.5/apollo-sase-20261024T193918Z/agents-publication-outbox.json
EXPECTED=684b2214e41e72ac71ca20c0404d618bc2521d167d29a9bfe09226258e187db7
SOURCE=/home/bryan/.sase/projects/gh_sase-org__sase/agents-publication-outbox.json
started_local=$(date -u +%Y-%m-%dT%H:%M:%SZ)
set +e
ssh -T "$HOST" 'zsh -lic "bash -s"' > "$EVIDENCE_DIR/apply_apollo_sase.json" 2> "$EVIDENCE_DIR/apply_apollo_sase.stderr" <<REMOTE
set -euo pipefail
source='$SOURCE'
backup='$BACKUP'
expected='$EXPECTED'
actual_source=\$(sha256sum "\$source" | awk '{print \$1}')
actual_backup=\$(sha256sum "\$backup" | awk '{print \$1}')
printf 'host=apollo\\nproject=sase\\nsource=%s\\nbackup=%s\\nexpected_sha256=%s\\nsource_pre_sha256=%s\\nbackup_pre_sha256=%s\\n' "\$source" "\$backup" "\$expected" "\$actual_source" "\$actual_backup" >&2
if [ "\$actual_source" != "\$expected" ] || [ "\$actual_backup" != "\$expected" ]; then
  printf 'preflight=FAILED\\n' >&2
  exit 44
fi
printf 'preflight=PASSED\\n' >&2
apply_started=\$(date -u +%Y-%m-%dT%H:%M:%SZ)
set +e
sase agent sync --repair-revisions --apply --project sase --json
apply_rc=\$?
set -e
apply_finished=\$(date -u +%Y-%m-%dT%H:%M:%SZ)
post_sha=\$(sha256sum "\$source" | awk '{print \$1}')
audit="\$(dirname "\$source")/agents-publication-repair-audit.jsonl"
audit_sha=missing
audit_lines=0
if [ -f "\$audit" ]; then
  audit_sha=\$(sha256sum "\$audit" | awk '{print \$1}')
  audit_lines=\$(wc -l < "\$audit" | tr -d ' ')
fi
printf 'apply_started_utc=%s\\napply_finished_utc=%s\\napply_exit_code=%s\\nsource_post_sha256=%s\\naudit_path=%s\\naudit_sha256=%s\\naudit_lines=%s\\n' "\$apply_started" "\$apply_finished" "\$apply_rc" "\$post_sha" "\$audit" "\$audit_sha" "\$audit_lines" >&2
exit "\$apply_rc"
REMOTE
rc=$?
set -e
finished_local=$(date -u +%Y-%m-%dT%H:%M:%SZ)
{
  printf 'host=%s\nproject=sase\ncommand=sase agent sync --repair-revisions --apply --project sase --json\nlocal_started_utc=%s\nlocal_finished_utc=%s\nssh_exit_code=%s\n' "$HOST" "$started_local" "$finished_local" "$rc"
  cat "$EVIDENCE_DIR/apply_apollo_sase.stderr"
  sha256sum "$EVIDENCE_DIR/apply_apollo_sase.json" "$EVIDENCE_DIR/apply_apollo_sase.stderr"
} > "$EVIDENCE_DIR/apply_apollo_sase.meta"
if [ "$rc" -ne 0 ]; then exit "$rc"; fi
ssh -T "$HOST" 'zsh -lic "cat ~/.sase/projects/gh_sase-org__sase/agents-publication-repair-audit.jsonl"' > "$EVIDENCE_DIR/audit_apollo_sase.jsonl" 2> "$EVIDENCE_DIR/audit_apollo_sase.stderr"
sha256sum "$EVIDENCE_DIR/audit_apollo_sase.jsonl" > "$EVIDENCE_DIR/audit_apollo_sase.sha256"
wc -l "$EVIDENCE_DIR/audit_apollo_sase.jsonl" > "$EVIDENCE_DIR/audit_apollo_sase.lines"
