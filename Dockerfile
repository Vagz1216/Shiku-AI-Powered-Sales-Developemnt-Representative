# Simple Dockerfile for Hugging Face Spaces
FROM python:3.12-slim AS builder

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/

WORKDIR /app

# Copy and install dependencies
COPY pyproject.toml ./
RUN uv sync --no-dev

# Copy source code
COPY . .

# Runtime stage
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    PORT=8000

# Create user and workspace
RUN useradd -m -u 1000 user
WORKDIR /app

# Copy from builder
COPY --from=builder --chown=user:user /app /app

# Create necessary directories with proper permissions
RUN mkdir -p logs data db && chown -R user:user /app

# Switch to user
USER user

# Expose port and run
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
