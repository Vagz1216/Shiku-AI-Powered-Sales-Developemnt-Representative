# Dockerfile for the FastAPI API service.
FROM python:3.12-slim AS builder

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/

WORKDIR /app

# Copy and install dependencies
COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --frozen

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
CMD ["./start.sh"]
