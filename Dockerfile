FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# fonts-dejavu-core ships DejaVu Serif, which Pillow uses to render the
# schedule-image feature with full Cyrillic coverage.
RUN apt-get update && \
    apt-get install -y --no-install-recommends fonts-dejavu-core && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src
COPY alembic.ini ./
COPY alembic ./alembic
COPY scripts ./scripts
COPY entrypoint.sh ./entrypoint.sh
COPY assets ./assets
COPY .env.example ./

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir . && \
    chmod +x /app/entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]
