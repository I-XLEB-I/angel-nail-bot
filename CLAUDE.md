# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Setup
python3 -m venv .venv && . .venv/bin/activate
pip install -e .[dev]
alembic upgrade head
python scripts/seed.py   # first-run only: seeds services, templates, runtime settings

# Run
python -m src.main

# Test
.venv/bin/python -m pytest                                  # full suite
.venv/bin/python -m pytest tests/test_booking_flow.py       # single file
.venv/bin/python -m pytest tests/test_booking_flow.py::test_normalize_phone  # single test

# Lint / format
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .

# Migrations
alembic revision --autogenerate -m "describe_change"
alembic upgrade head

# Docker (dev)
docker compose up --build
# Docker (prod — no bind-mount of source tree)
docker compose -f docker-compose.prod.yml up --build -d
```

## Architecture

The bot is a single-process **aiogram 3 long-polling** application with an embedded APScheduler. There is no webhook and no separate worker process; everything runs inside one `python -m src.main` invocation.

### Layers

| Layer | Path | Role |
|-------|------|------|
| Entry point | `src/main.py` | Wires engine, bot, dispatcher, scheduler; runs polling |
| Config | `src/config.py` | Pydantic-settings; loaded from `.env`; cached singleton via `get_settings()` |
| Bot assembly | `src/bot/app.py` | Creates `Bot` + `Dispatcher`, registers all routers and middleware |
| Handlers | `src/bot/handlers/admin/` `src/bot/handlers/client/` | One `Router` per feature; imported and `include_router`'d in `app.py` |
| States | `src/bot/states.py` | All aiogram FSM `StatesGroup` definitions |
| FSM storage | `src/bot/fsm_storage.py` | Custom JSON file storage (`data/fsm_states.json`); survives restarts |
| Keyboards | `src/bot/keyboards/` | Inline/reply keyboard builders |
| Middleware | `src/bot/middlewares/` | `UserContextMiddleware` (upserts user, injects context); `ThrottleMiddleware` |
| DB models | `src/db/models.py` | SQLAlchemy 2 ORM; all enums are `StrEnum` backed by `SqlEnum(native_enum=False)` |
| Repositories | `src/db/repositories/` | Async query helpers, one file per model |
| Services | `src/services/` | Business logic (booking, approvals, reminders, calendar sync, image gen) |
| Scheduler | `src/scheduler.py` | APScheduler jobs: reminders (5 min), mark_completed (10 min), postvisit (15 min), gcal_pull (15 min, optional), repeat_prompt/rate_limit_alerts (1 h), winback (6 h), morning_summary (cron 08:00) |

### Middleware data injection

`UserContextMiddleware` runs on every update and injects into the handler `data` dict:
- `db_session` — open `AsyncSession`
- `user` — the `User` ORM object (upserted from Telegram identity)
- `is_admin` — bool derived from `ADMIN_TG_IDS`
- `settings` — the `Settings` singleton

Handlers declare these as typed parameters; aiogram resolves them by name.

### Router registration order

Router order in `app.py` matters. `client_fallback_router` **must be last** — it catches any text message that no earlier router claimed, and would silently swallow legitimate input if registered earlier.

### Approval flow

When a client requests an off-schedule slot or a flagged action (frequent booking, late reschedule, etc.), a `ApprovalRequest` row is created and an approval card is sent to all admins. The admin can approve/decline/offer a time slot inline. The client sees the result via `offer_confirm` handler. States and kinds live in `src/db/models.py` (`ApprovalRequestKind`, `ApprovalRequestStatus`).

### Testing conventions

Tests use in-memory SQLite (`sqlite+aiosqlite:///:memory:`) created per-test — no shared fixtures. `pytest-asyncio` runs in `asyncio_mode = "auto"`. Since `get_settings()` is `lru_cache`'d, call `get_settings.cache_clear()` in tests that need custom settings.

### Google integrations

All Google integrations (Calendar, Sheets, Drive) are optional and guarded by feature flags in `Settings`. Credentials live in `secrets/` (not committed). Calendar sync blocks slots that are busy in the external calendar (`blocked_by_gcal=True` on `Slot`).

### Image generation

`src/services/image_core.py`, `schedule_image.py`, and `price_image.py` use Pillow to render schedule/price/client-card images. Backgrounds are stored in `assets/` and can be overridden at runtime via admin panel (stored in the DB).

### Database

Default: `sqlite+aiosqlite:///./data/bot.db`. Production runtime data (admin-configured templates, button styles, premium emoji, services) lives in this file — **never overwrite `data/` during deploy**. The `entrypoint.sh` runs `alembic upgrade head` automatically on container start.

### SQLite deploy safety

- Before any prod deploy or migration, create a fresh backup of both `data/bot.db` and `.env`.
- Do **not** use `rsync --delete` against `data/` or `backups/`.
- For prod backup/restore, prefer:
  - `scripts/backup_prod.sh`
  - `scripts/restore_prod.sh <db-backup> [env-backup]`
- After any restore or migration, run a smoke check:
  - bot starts and polls successfully;
  - `alembic upgrade head` is clean;
  - `/diag` shows the expected DB path and a fresh backup/restore timestamp.

### Writing SQLite-compatible migrations

Production runs on SQLite. Two classes of Postgres-friendly DDL silently break under SQLite — both already caused production incidents.

**Forbidden (will break prod):**
- `op.alter_column(..., server_default=None)` — SQLite cannot drop a column default. Past incident: 0011.
- `sa.BigInteger() primary_key=True` for an auto-generated `id` — SQLite only autoincrements `INTEGER PRIMARY KEY` (the exact word `INTEGER`). `BIGINT PRIMARY KEY` is a regular PK with no autoincrement; inserts without an explicit id fail with `NOT NULL constraint failed`. Past incident: 0015/0016/0008. **Always use `sa.Integer()`** for auto-generated PKs in migrations. In SQLAlchemy models use the existing `BIGINT_PK = BigInteger().with_variant(Integer, "sqlite")` alias from `src/db/base.py`.
- `ALTER TABLE ... ALTER COLUMN ...` of any kind on SQLite. Use `op.batch_alter_table(name, recreate="always")` instead, which rebuilds the table via CREATE + INSERT SELECT + DROP + RENAME.

**Required before merging a migration:**

```bash
# Dry run on an empty SQLite database; CI does the same automatically.
python scripts/check_sqlite_migration.py

# Dry run on a copy of the live database to catch data-incompatible changes.
cp data/bot.db /tmp/bot-test.db
DATABASE_URL=sqlite+aiosqlite:////tmp/bot-test.db alembic upgrade head
```

`scripts/check_sqlite_migration.py` is also wired into `.github/workflows/tests.yml` and will fail CI on any new `BIGINT PRIMARY KEY` regression.

New migrations should be idempotent (`inspector.get_table_names()` / `_has_column` guards) so partial-apply re-runs after a crash don't blow up.
