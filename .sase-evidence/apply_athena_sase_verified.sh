#!/usr/bin/env bash
set -euo pipefail
EVIDENCE_DIR=.sase-evidence
HOST=athena
PROJECT=sase
SOURCE=/home/bryan/.sase/projects/gh_sase-org__sase/agents-publication-outbox.json
BACKUP=/home/bryan/.sase/recovery-backups/sase-1nv.5/athena-sase-20261024T200112Z/agents-publication-outbox.json
BACKUP_DIR=${BACKUP%/*}
EXPECTED=cb08ac3e41bd01e6531bdffd964bfaa12cce3e017e801cccf6150e6f5ef1112e
LOCAL_STARTED=$(date -u +%Y-%m-%dT%H:%M:%SZ)
set +e
ssh -T "$HOST" 'zsh -lic "bash -s"' > "$EVIDENCE_DIR/apply_athena_sase_verified.json" 2> "$EVIDENCE_DIR/apply_athena_sase_verified.stderr" <<REMOTE
set -euo pipefail
source='$SOURCE'
backup='$BACKUP'
backup_dir='$BACKUP_DIR'
expected='$EXPECTED'
audit="\$(dirname "\$source")/agents-publication-repair-audit.jsonl"
source_pre=\$(sha256sum "\$source" | awk '{print \$1}')
backup_pre=\$(sha256sum "\$backup" | awk '{print \$1}')
printf 'host=athena\\nproject=sase\\nsource=%s\\nbackup=%s\\nexpected_sha256=%s\\nsource_pre_sha256=%s\\nbackup_pre_sha256=%s\\n' "\$source" "\$backup" "\$expected" "\$source_pre" "\$backup_pre" >&2
if [ "\$source_pre" != "\$expected" ] || [ "\$backup_pre" != "\$expected" ]; then
  printf 'preflight=FAILED\\n' >&2
  exit 44
fi
printf 'preflight=PASSED\\n' >&2
if [ -f "\$audit" ]; then cp -- "\$audit" "\$backup_dir/repair-audit-before.jsonl"; else : > "\$backup_dir/repair-audit-before.jsonl"; fi
apply_started=\$(date -u +%Y-%m-%dT%H:%M:%SZ)
set +e
sase agent sync --repair-revisions --apply --project sase --json
apply_rc=\$?
set -e
apply_finished=\$(date -u +%Y-%m-%dT%H:%M:%SZ)
if [ -f "\$audit" ]; then cp -- "\$audit" "\$backup_dir/repair-audit-after.jsonl"; else : > "\$backup_dir/repair-audit-after.jsonl"; fi
source_post=\$(sha256sum "\$source" | awk '{print \$1}')
audit_sha=\$(sha256sum "\$audit" | awk '{print \$1}')
audit_lines=\$(wc -l < "\$audit" | tr -d ' ')
printf 'apply_started_utc=%s\\napply_finished_utc=%s\\napply_exit_code=%s\\nsource_post_sha256=%s\\naudit_path=%s\\naudit_sha256=%s\\naudit_lines=%s\\n' "\$apply_started" "\$apply_finished" "\$apply_rc" "\$source_post" "\$audit" "\$audit_sha" "\$audit_lines" >&2
exit "\$apply_rc"
REMOTE
RC=$?
set -e
LOCAL_FINISHED=$(date -u +%Y-%m-%dT%H:%M:%SZ)
{
  printf 'host=%s\nproject=%s\ncommand=sase agent sync --repair-revisions --apply --project sase --json\nlocal_started_utc=%s\nlocal_finished_utc=%s\nssh_exit_code=%s\nbackup=%s\nexpected_backup_sha256=%s\n' "$HOST" "$PROJECT" "$LOCAL_STARTED" "$LOCAL_FINISHED" "$RC" "$BACKUP" "$EXPECTED"
  cat "$EVIDENCE_DIR/apply_athena_sase_verified.stderr"
  sha256sum "$EVIDENCE_DIR/apply_athena_sase_verified.json" "$EVIDENCE_DIR/apply_athena_sase_verified.stderr"
} > "$EVIDENCE_DIR/apply_athena_sase_verified.meta"
if [ "$RC" -ne 0 ]; then exit "$RC"; fi
ssh -T "$HOST" "zsh -lic 'cat $BACKUP'" > "$EVIDENCE_DIR/athena_sase_outbox_before.json" 2> "$EVIDENCE_DIR/athena_sase_outbox_before.stderr"
ssh -T "$HOST" "zsh -lic 'cat $SOURCE'" > "$EVIDENCE_DIR/athena_sase_outbox_after.json" 2> "$EVIDENCE_DIR/athena_sase_outbox_after.stderr"
ssh -T "$HOST" "zsh -lic 'cat /home/bryan/.sase/projects/gh_sase-org__sase/agents-publication-repair-audit.jsonl'" > "$EVIDENCE_DIR/audit_athena_sase.jsonl" 2> "$EVIDENCE_DIR/audit_athena_sase.stderr"
sha256sum "$EVIDENCE_DIR/athena_sase_outbox_before.json" "$EVIDENCE_DIR/athena_sase_outbox_after.json" "$EVIDENCE_DIR/audit_athena_sase.jsonl" > "$EVIDENCE_DIR/athena_sase_snapshot_hashes.sha256"
wc -l "$EVIDENCE_DIR/audit_athena_sase.jsonl" > "$EVIDENCE_DIR/audit_athena_sase.lines"
