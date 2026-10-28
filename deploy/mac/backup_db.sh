#!/bin/zsh
# SQLite DB를 서비스 중에도 안전하게(.backup) 복사하고, 오래된 백업은 정리한다.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO"

DB_PATH="$(grep -E '^ANNUAL_STATISTICS_DB_PATH=' .env 2>/dev/null | cut -d= -f2- || true)"
DB_PATH="${DB_PATH:-backend/app/db/annual_statistics.sqlite}"
BACKUP_DIR="${STATYEARBOOK_BACKUP_DIR:-$REPO/backups}"
KEEP_DAYS="${STATYEARBOOK_BACKUP_KEEP_DAYS:-30}"

mkdir -p "$BACKUP_DIR"
target="$BACKUP_DIR/$(basename "$DB_PATH" .sqlite)_$(date +%Y%m%d_%H%M%S).sqlite"
/usr/bin/sqlite3 "$DB_PATH" ".backup '$target'"
/usr/bin/sqlite3 "$target" "PRAGMA integrity_check;" | grep -qx ok
echo "$(date '+%F %T') 백업 완료: $target"

find "$BACKUP_DIR" -name '*.sqlite' -type f -mtime "+$KEEP_DAYS" -print -delete
