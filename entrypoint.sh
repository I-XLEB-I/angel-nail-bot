#!/bin/sh
set -eu

alembic upgrade head

if [ "$#" -gt 0 ]; then
  exec "$@"
fi

exec python -m src.main
