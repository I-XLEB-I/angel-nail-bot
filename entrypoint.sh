#!/bin/sh
set -eu

# Seed only on a brand-new database (first deploy); never touches existing data.
DB_FILE="${DB_FILE:-./data/bot.db}"
FIRST_RUN=0
if [ ! -f "$DB_FILE" ]; then
  FIRST_RUN=1
fi
mkdir -p "$(dirname "$DB_FILE")"

alembic upgrade head

if [ "$FIRST_RUN" -eq 1 ]; then
  python scripts/seed.py
fi

if [ "$#" -gt 0 ]; then
  exec "$@"
fi

exec python -m src.main
