"""Measure database checkout/query latency for the configured DATABASE_URL.

Run with:
    UV_CACHE_DIR=/tmp/uv-cache uv run python scripts/check_postgres_pool.py
"""

from __future__ import annotations

import statistics
import time

from utils.db_connection import get_conn


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, round((len(ordered) - 1) * percentile))
    return ordered[index]


def main() -> None:
    samples = 10
    timings: list[float] = []
    print(f"Running {samples} database checkout + SELECT 1 samples...")
    for i in range(samples):
        started = time.perf_counter()
        with get_conn() as conn:
            conn.execute("SELECT 1").fetchone()
        elapsed_ms = (time.perf_counter() - started) * 1000
        timings.append(elapsed_ms)
        print(f"sample={i + 1} duration_ms={elapsed_ms:.2f}")

    print(
        "summary "
        f"min_ms={min(timings):.2f} "
        f"avg_ms={statistics.mean(timings):.2f} "
        f"p95_ms={_percentile(timings, 0.95):.2f} "
        f"max_ms={max(timings):.2f}"
    )


if __name__ == "__main__":
    main()
