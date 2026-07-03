#!/bin/bash
# Simple startup script for Squad 3 Outreach System

set -e

# Configuration
HOST=${HOST:-0.0.0.0}
PORT=${PORT:-8000}

echo "🚀 Starting Squad 3 Outreach System..."
echo "📍 Running on: http://$HOST:$PORT"

if [ "${APPLY_DB_MIGRATIONS_ON_STARTUP:-false}" = "true" ]; then
  echo "Applying PostgreSQL migrations before startup..."
  python scripts/apply_postgres_migrations.py
fi

# Start the application
exec python -m uvicorn main:app --host $HOST --port $PORT
