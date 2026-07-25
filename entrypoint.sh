#!/bin/sh
set -eu

# Seed only on the database file actually configured for the app.
FIRST_RUN="$(python -m src.db.startup)"

alembic upgrade head

if [ "$FIRST_RUN" = "1" ]; then
  python scripts/seed.py
fi

if [ "$#" -gt 0 ]; then
  exec "$@"
fi

exec python -m src.main
