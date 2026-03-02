#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: scripts/migrate_db_name_to_teachersnote.sh [--force-empty-target]

Environment variables (optional):
  DB_HOST      (default: localhost)
  DB_PORT      (default: 3306)
  DB_USER      (default: root)
  DB_PASSWORD  (default: empty)
  OLD_DB_NAME  (default: lecturesummary)
  NEW_DB_NAME  (default: teachersnote)

Behavior:
  - Backs up OLD_DB_NAME to out/db_backups/<old>_<timestamp>.sql
  - Creates NEW_DB_NAME if needed
  - Imports backup into NEW_DB_NAME
  - Verifies expected tables exist and row counts match

Safety:
  - Stops if OLD_DB_NAME does not exist
  - Stops if NEW_DB_NAME already has tables unless --force-empty-target is set
USAGE
}

FORCE_EMPTY_TARGET=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --force-empty-target)
      FORCE_EMPTY_TARGET=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-3306}"
DB_USER="${DB_USER:-root}"
DB_PASSWORD="${DB_PASSWORD:-}"
OLD_DB_NAME="${OLD_DB_NAME:-lecturesummary}"
NEW_DB_NAME="${NEW_DB_NAME:-teachersnote}"

if [[ "$OLD_DB_NAME" == "$NEW_DB_NAME" ]]; then
  echo "OLD_DB_NAME and NEW_DB_NAME must differ." >&2
  exit 1
fi

for cmd in mysql mysqldump; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Missing required command: $cmd" >&2
    exit 1
  fi
done

MYSQL_BASE_ARGS=(
  --host="$DB_HOST"
  --port="$DB_PORT"
  --user="$DB_USER"
  --default-character-set=utf8mb4
)

if [[ -n "$DB_PASSWORD" ]]; then
  export MYSQL_PWD="$DB_PASSWORD"
fi

mysql_query() {
  local sql="$1"
  mysql "${MYSQL_BASE_ARGS[@]}" --batch --skip-column-names -e "$sql"
}

echo "Checking source database '$OLD_DB_NAME'..."
old_exists="$(mysql_query "SELECT COUNT(*) FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = '$OLD_DB_NAME';")"
if [[ "$old_exists" != "1" ]]; then
  echo "Source database '$OLD_DB_NAME' does not exist. Aborting." >&2
  exit 1
fi

echo "Checking target database '$NEW_DB_NAME'..."
new_table_count="$(mysql_query "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA = '$NEW_DB_NAME';")"
if [[ "$new_table_count" != "0" && "$FORCE_EMPTY_TARGET" != "1" ]]; then
  echo "Target database '$NEW_DB_NAME' already contains $new_table_count table(s)." >&2
  echo "Re-run with --force-empty-target if you want to replace it." >&2
  exit 1
fi

backup_dir="out/db_backups"
mkdir -p "$backup_dir"
timestamp="$(date +%Y%m%d_%H%M%S)"
backup_path="$backup_dir/${OLD_DB_NAME}_${timestamp}.sql"

echo "Creating backup: $backup_path"
mysqldump "${MYSQL_BASE_ARGS[@]}" \
  --single-transaction \
  --quick \
  --routines \
  --triggers \
  "$OLD_DB_NAME" > "$backup_path"

if [[ "$FORCE_EMPTY_TARGET" == "1" ]]; then
  echo "Resetting target database '$NEW_DB_NAME' (--force-empty-target enabled)..."
  mysql_query "DROP DATABASE IF EXISTS \\`$NEW_DB_NAME\\`;"
fi

echo "Creating target database '$NEW_DB_NAME' if needed..."
mysql_query "CREATE DATABASE IF NOT EXISTS \\`$NEW_DB_NAME\\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"

echo "Importing backup into '$NEW_DB_NAME'..."
mysql "${MYSQL_BASE_ARGS[@]}" "$NEW_DB_NAME" < "$backup_path"

declare -a expected_tables=(
  lectures
  slides
  transcript_segments
  alignments
  enriched_slides
  lecture_saves
  admin_users
  programs
  courses
  program_courses
  student_profiles
  student_courses
)

echo "Verifying tables and row counts..."
for table in "${expected_tables[@]}"; do
  old_table_exists="$(mysql_query "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA = '$OLD_DB_NAME' AND TABLE_NAME = '$table';")"
  new_table_exists="$(mysql_query "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA = '$NEW_DB_NAME' AND TABLE_NAME = '$table';")"

  if [[ "$old_table_exists" != "1" ]]; then
    echo "Missing table '$table' in source database '$OLD_DB_NAME'." >&2
    exit 1
  fi
  if [[ "$new_table_exists" != "1" ]]; then
    echo "Missing table '$table' in target database '$NEW_DB_NAME'." >&2
    exit 1
  fi

  old_count="$(mysql_query "SELECT COUNT(*) FROM \\`$OLD_DB_NAME\\`.\\`$table\\`;")"
  new_count="$(mysql_query "SELECT COUNT(*) FROM \\`$NEW_DB_NAME\\`.\\`$table\\`;")"

  if [[ "$old_count" != "$new_count" ]]; then
    echo "Row count mismatch for '$table': old=$old_count new=$new_count" >&2
    exit 1
  fi

  echo "  - $table: $new_count rows"
done

echo
echo "Migration complete."
echo "Backup file: $backup_path"
echo
echo "Next steps:"
echo "1) Set DB_NAME=$NEW_DB_NAME in backend/.env"
echo "2) Restart backend service"
echo "3) Run smoke checks: GET /health, /lectures, /programs, /courses, /profile"
echo "4) Keep '$OLD_DB_NAME' for rollback until signoff"
