#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: scripts/restore_prod.sh <db-backup-path> [env-backup-path]" >&2
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

DB_BACKUP="$1"
ENV_BACKUP="${2:-}"
TS="$(date -u +%Y-%m-%dT%H%M%SZ)"

docker compose -f docker-compose.prod.yml stop bot

cp "$DB_BACKUP" data/bot.db
if [[ -n "$ENV_BACKUP" ]]; then
  cp "$ENV_BACKUP" .env
fi

python3 - "$ROOT_DIR/data/bot.db" "$TS" <<'PY'
import sqlite3
import sys

db_path = sys.argv[1]
timestamp = sys.argv[2]
conn = sqlite3.connect(db_path)
try:
    conn.execute(
        """
        INSERT INTO setting(key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """,
        ("system.last_restore_at", timestamp),
    )
    conn.commit()
finally:
    conn.close()
PY

docker compose -f docker-compose.prod.yml up -d bot

echo "Restore completed at ${TS}"
