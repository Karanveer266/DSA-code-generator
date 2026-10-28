#!/usr/bin/env bash
# =========================================================================
# Container entrypoint.
#
# Usage (first CMD arg selects the role):
#   web     -> run DB migrations, collect static, start Gunicorn
#   worker  -> start a Celery worker
#   beat    -> start the Celery beat scheduler (not required by default)
#   shell   -> drop into a shell (debugging)
# =========================================================================
set -euo pipefail

ROLE="${1:-web}"

# Give the DB a moment if one is configured (best-effort; harmless for sqlite).
wait_for_db() {
    if [[ "${DATABASE_URL:-}" == postgres* ]]; then
        echo "[entrypoint] Waiting for Postgres..."
        for _ in $(seq 1 30); do
            if python -c "
import os, sys
from urllib.parse import urlparse
import socket
u = urlparse(os.environ['DATABASE_URL'])
s = socket.socket()
s.settimeout(1)
try:
    s.connect((u.hostname, u.port or 5432)); s.close()
except Exception:
    sys.exit(1)
" 2>/dev/null; then
                echo "[entrypoint] Postgres is up."
                return 0
            fi
            sleep 1
        done
        echo "[entrypoint] WARNING: Postgres did not become ready in time."
    fi
}

# Pre-pull sandbox images so the first solve isn't slowed by an image pull.
prepull_sandbox_images() {
    if [[ "${SANDBOX_BACKEND:-docker}" == "docker" ]] && command -v docker >/dev/null 2>&1; then
        echo "[entrypoint] Pre-pulling sandbox images (best-effort)..."
        docker pull "${SANDBOX_CPP_IMAGE:-gcc:13}" >/dev/null 2>&1 || true
        docker pull "${SANDBOX_PYTHON_IMAGE:-python:3.11-slim}" >/dev/null 2>&1 || true
    fi
}

case "$ROLE" in
    web)
        wait_for_db
        echo "[entrypoint] Applying migrations..."
        python manage.py migrate --noinput
        echo "[entrypoint] Collecting static files..."
        python manage.py collectstatic --noinput >/dev/null 2>&1 || true
        prepull_sandbox_images
        echo "[entrypoint] Starting Gunicorn..."
        exec gunicorn config.wsgi:application \
            --bind 0.0.0.0:8000 \
            --workers "${GUNICORN_WORKERS:-3}" \
            --timeout "${GUNICORN_TIMEOUT:-120}"
        ;;
    worker)
        wait_for_db
        prepull_sandbox_images
        echo "[entrypoint] Starting Celery worker..."
        exec celery -A config worker \
            --loglevel="${CELERY_LOGLEVEL:-info}" \
            --concurrency="${CELERY_CONCURRENCY:-2}"
        ;;
    beat)
        exec celery -A config beat --loglevel=info
        ;;
    shell)
        exec /bin/bash
        ;;
    *)
        # Allow running arbitrary commands: `docker compose run web python manage.py ...`
        exec "$@"
        ;;
esac
