#!/usr/bin/env bash
set -euo pipefail

source=/home/bryan/.sase/projects/gh_sase-org__sase/agents-publication-outbox.json
project_root=/home/bryan/.sase/projects/gh_sase-org__sase
backup_root=/home/bryan/.sase/recovery-backups/sase-1nv.5
backup_dir="$backup_root/athena-sase-$BACKUP_STAMP"
backup="$backup_dir/agents-publication-outbox.json"
report="$backup_dir/report.json"
apply="$backup_dir/apply.json"
meta="$backup_dir/transaction.meta"
audit="$project_root/agents-publication-repair-audit.jsonl"

mkdir -p "$backup_dir"
cp -p -- "$source" "$backup"
expected=$(sha256sum "$backup" | awk '{print $1}')
source_before=$(sha256sum "$source" | awk '{print $1}')
cp -p -- "$source" "$backup_dir/outbox-before.json"
cp -p -- "$project_root"/agents-publication-repair-audit.jsonl "$backup_dir/audit-before.jsonl" 2>/dev/null || : > "$backup_dir/audit-before.jsonl"
sase version --json > "$backup_dir/version.json"

{
  printf 'host=athena\nproject=sase\nsource=%s\nbackup=%s\nbackup_stamp=%s\n' "$source" "$backup" "$BACKUP_STAMP"
  printf 'source_before_sha256=%s\nbackup_sha256=%s\n' "$source_before" "$expected"
  jq -r '.packages[] | select(.name=="sase" or .name=="sase-core-rs") | "revision_\(.name)=\(.git.commit) version=\(.display_version)"' "$backup_dir/version.json"
} > "$meta"

if [ "$source_before" != "$expected" ]; then
  printf 'backup_preflight=FAILED\n' >> "$meta"
  exit 43
fi
printf 'backup_preflight=PASSED\nreport_started_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$meta"
set +e
sase agent sync --repair-revisions --project sase --json > "$report" 2> "$backup_dir/report.stderr"
report_rc=$?
set -e
printf 'report_finished_utc=%s\nreport_exit_code=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$report_rc" >> "$meta"
if [ "$report_rc" -ne 0 ]; then
  printf 'apply=SKIPPED report_failed\n' >> "$meta"
  exit "$report_rc"
fi
if ! jq -e '.projects | length == 1 and .[0].project == "sase" and .[0].error == null' "$report" >/dev/null; then
  printf 'apply=SKIPPED report_classification_invalid\n' >> "$meta"
  exit 44
fi

report_hash=$(sha256sum "$source" | awk '{print $1}')
if [ "$report_hash" != "$expected" ]; then
  printf 'post_report_source_sha256=%s\nreport_matches_backup=no\napply=SKIPPED source_changed\n' "$report_hash" >> "$meta"
  exit 45
fi
printf 'post_report_source_sha256=%s\nreport_matches_backup=yes\n' "$report_hash" >> "$meta"
jq -r '[.projects[0].diagnostics[]? | select(contains("unresolved, kept as is"))] | "unresolved=" + (length|tostring)' "$report" >> "$meta"
jq -r '[.projects[0].diagnostics[]? | select(contains("repaired to"))] | "repaired=" + (length|tostring)' "$report" >> "$meta"
jq -r '[.projects[0].diagnostics[]? | select(contains("takes linked scope"))] | "linked=" + (length|tostring)' "$report" >> "$meta"
jq -r '[.projects[0].diagnostics[]? | select(contains("unchanged"))] | "unchanged=" + (length|tostring)' "$report" >> "$meta"

# Recheck the exact report-approved input immediately before the mutating CLI call.
apply_pre=$(sha256sum "$source" | awk '{print $1}')
backup_pre=$(sha256sum "$backup" | awk '{print $1}')
if [ "$apply_pre" != "$expected" ] || [ "$backup_pre" != "$expected" ]; then
  printf 'apply_pre_source_sha256=%s\napply_pre_backup_sha256=%s\napply_preflight=FAILED\napply=SKIPPED source_changed\n' "$apply_pre" "$backup_pre" >> "$meta"
  exit 46
fi
printf 'apply_pre_source_sha256=%s\napply_pre_backup_sha256=%s\napply_preflight=PASSED\napply_started_utc=%s\n' "$apply_pre" "$backup_pre" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$meta"
set +e
sase agent sync --repair-revisions --apply --project sase --json > "$apply" 2> "$backup_dir/apply.stderr"
apply_rc=$?
set -e
printf 'apply_finished_utc=%s\napply_exit_code=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$apply_rc" >> "$meta"
cp -p -- "$source" "$backup_dir/outbox-after.json"
cp -p -- "$audit" "$backup_dir/audit-after.jsonl" 2>/dev/null || : > "$backup_dir/audit-after.jsonl"
source_after=$(sha256sum "$source" | awk '{print $1}')
printf 'source_after_sha256=%s\naudit_after_sha256=%s\naudit_after_lines=%s\n' "$source_after" "$(sha256sum "$backup_dir/audit-after.jsonl" | awk '{print $1}')" "$(wc -l < "$backup_dir/audit-after.jsonl" | tr -d ' ')" >> "$meta"
if [ "$apply_rc" -ne 0 ]; then exit "$apply_rc"; fi
if ! jq -e '.projects | length == 1 and .[0].project == "sase" and .[0].error == null' "$apply" >/dev/null; then
  printf 'apply_result=FAILED classification_error\n' >> "$meta"
  exit 47
fi

# Every row the report classified unresolved must remain byte-for-byte equivalent.
unresolved=$(jq -c '[.projects[0].diagnostics[]? | select(contains("unresolved, kept as is")) | capture("^(?<agent>[^@]+)@(?<rev>[0-9a-f]+): unresolved, kept as is")]' "$report")
for snapshot in outbox-before.json outbox-after.json; do
  jq -S --argjson unresolved "$unresolved" '[.items[] as $row | select(any($unresolved[] as $u; $u.agent == $row.global_agent and ($u.rev == $row.primary_revision or ($row.primary_revision | startswith($u.rev))))) | $row] | sort_by(.id)' "$backup_dir/$snapshot" > "$backup_dir/unresolved-$snapshot"
done
if ! cmp -s "$backup_dir/unresolved-outbox-before.json" "$backup_dir/unresolved-outbox-after.json"; then
  printf 'unresolved_rows_unchanged=no\n' >> "$meta"
  exit 48
fi
printf 'unresolved_rows_unchanged=yes\n' >> "$meta"
jq -r '.projects[0].diagnostics[]? | select(contains("applied "))' "$apply" >> "$meta"
sha256sum "$report" "$apply" "$backup_dir/outbox-before.json" "$backup_dir/outbox-after.json" "$backup_dir/audit-after.jsonl" >> "$meta"
cat "$meta"
