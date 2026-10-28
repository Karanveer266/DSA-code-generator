# =========================================================================
# Dockerfile for the Django web / Celery worker image.
#
# The SAME image runs both the web server and the Celery worker (the command
# differs, set in docker-compose.yml). It talks to the host Docker daemon via a
# mounted socket to spawn *sibling* sandbox containers (gcc / python) - it does
# NOT run Docker-in-Docker.
# =========================================================================
FROM python:3.11-slim AS base

# --- Python / pip hygiene ---
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# --- System deps ---
# - docker-cli lets you debug from inside the container (the Python SDK talks to
#   the socket directly, but the CLI is handy).
# - build-essential/libpq-dev support psycopg2 if Postgres is used.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# --- Python dependencies (cached layer) ---
COPY requirements.txt .
RUN pip install -r requirements.txt

# --- Application code ---
COPY . .

# --- Entrypoint handles migrations + static before launching ---
RUN chmod +x /app/entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["web"]
