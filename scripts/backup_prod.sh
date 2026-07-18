#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

mkdir -p backups
TS="$(date -u +%Y-%m-%dT%H%M%SZ)"

cp data/bot.db "backups/bot.db.${TS}"
cp .env "backups/.env.${TS}"
if [[ -d data/template_media ]]; then
  tar -czf "backups/template_media.${TS}.tar.gz" -C data template_media
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
        ("system.last_backup_at", timestamp),
    )
    conn.commit()
finally:
    conn.close()
PY

echo "Backup created:"
echo "  backups/bot.db.${TS}"
echo "  backups/.env.${TS}"
if [[ -f "backups/template_media.${TS}.tar.gz" ]]; then
  echo "  backups/template_media.${TS}.tar.gz"
fi
