#!/bin/bash
# Simple startup script for Squad 3 Outreach System

set -e

# Configuration
HOST=${HOST:-0.0.0.0}
PORT=${PORT:-8000}

echo "🚀 Starting Squad 3 Outreach System..."
echo "📍 Running on: http://$HOST:$PORT"

# Start the application
exec python -m uvicorn main:app --host $HOST --port $PORT