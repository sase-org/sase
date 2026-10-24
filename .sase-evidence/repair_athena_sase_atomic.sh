#!/usr/bin/env bash
set -euo pipefail

evidence_dir=.sase-evidence
stamp=$(date -u +%Y%m%dT%H%M%SZ)
remote_dir="/home/bryan/.sase/recovery-backups/sase-1nv.5/athena-sase-$stamp"
started=$(date -u +%Y-%m-%dT%H:%M:%SZ)
set +e
{
  printf 'BACKUP_STAMP=%s\n' "$stamp"
  cat "$evidence_dir/remote_repair_athena_sase_atomic.sh"
} | ssh -T athena 'zsh -lic "bash -s"' > "$evidence_dir/repair_athena_sase_atomic.stdout" 2> "$evidence_dir/repair_athena_sase_atomic.stderr"
rc=$?
set -e
finished=$(date -u +%Y-%m-%dT%H:%M:%SZ)
{
  printf 'host=athena\nproject=sase\ncommand=backup; report-only repair; exact source=backup=expected preflight; apply; unresolved-row comparison\n'
  printf 'local_started_utc=%s\nlocal_finished_utc=%s\nssh_exit_code=%s\nremote_backup_dir=%s\n' "$started" "$finished" "$rc" "$remote_dir"
  cat "$evidence_dir/repair_athena_sase_atomic.stderr"
} > "$evidence_dir/repair_athena_sase_atomic.meta"

for pair in \
  'report.json report_athena_sase_atomic.json' \
  'report.stderr report_athena_sase_atomic.stderr' \
  'apply.json apply_athena_sase_atomic.json' \
  'apply.stderr apply_athena_sase_atomic.stderr' \
  'outbox-before.json athena_sase_outbox_before.json' \
  'outbox-after.json athena_sase_outbox_after.json' \
  'audit-before.jsonl audit_athena_sase_before.jsonl' \
  'audit-after.jsonl audit_athena_sase_after.jsonl' \
  'transaction.meta repair_athena_sase_transaction.meta' \
  'version.json version_athena_sase_atomic.json'; do
  remote_file=${pair%% *}
  local_file=${pair#* }
  if ssh -T athena "zsh -lic 'test -f $remote_dir/$remote_file'" >/dev/null 2>&1; then
    ssh -T athena "zsh -lic 'cat $remote_dir/$remote_file'" > "$evidence_dir/$local_file"
  fi
done
sha256sum "$evidence_dir"/*athena*sase*atomic* "$evidence_dir/repair_athena_sase_transaction.meta" 2>/dev/null >> "$evidence_dir/repair_athena_sase_atomic.meta" || :
exit "$rc"
