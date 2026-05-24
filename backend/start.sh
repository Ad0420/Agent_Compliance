#!/bin/sh
set -eu

PORT="${PORT:-8000}"
WEB_CONCURRENCY="${WEB_CONCURRENCY:-2}"
GUNICORN_TIMEOUT="${GUNICORN_TIMEOUT:-120}"
RUN_MIGRATIONS="${RUN_MIGRATIONS:-1}"
VERA_BOOTSTRAP_LOCAL="${VERA_BOOTSTRAP_LOCAL:-0}"

if [ "$RUN_MIGRATIONS" = "1" ]; then
    alembic upgrade head
fi

# Explicit opt-in only. setup_local.py creates a default organization and
# admin key, which must never happen implicitly in production.
if [ "$VERA_BOOTSTRAP_LOCAL" = "1" ]; then
    python setup_local.py
fi

exec gunicorn app.main:app \
    --bind "0.0.0.0:${PORT}" \
    --workers "$WEB_CONCURRENCY" \
    --worker-class uvicorn.workers.UvicornWorker \
    --access-logfile - \
    --error-logfile - \
    --timeout "$GUNICORN_TIMEOUT"
