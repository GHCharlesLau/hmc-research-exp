#!/usr/bin/env bash
# Render start script — run migrations then launch the app.
set -e

echo "Running database migrations..."
alembic upgrade head

echo "Starting ConExperiment 2.0..."
uvicorn main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 1
