"""Request-scoped timing helpers for structured route diagnostics."""

from __future__ import annotations

from contextlib import contextmanager
from time import perf_counter
from typing import Any, Iterator

_MAX_METADATA_VALUE_LEN = 120


def _safe_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """Keep timing metadata small and avoid complex or sensitive values."""
    safe: dict[str, Any] = {}
    for key, value in metadata.items():
        if value is None:
            continue
        if isinstance(value, (bool, int, float)):
            safe[key] = value
        elif isinstance(value, str):
            safe[key] = (
                value
                if len(value) <= _MAX_METADATA_VALUE_LEN
                else f"{value[:_MAX_METADATA_VALUE_LEN]}..."
            )
    return safe


def record_timing(request: Any, name: str, duration_ms: float, **metadata: Any) -> None:
    """Append a timing step to the current request state if one exists."""
    if request is None or not hasattr(request, "state"):
        return

    steps = getattr(request.state, "route_timings", None)
    if steps is None:
        steps = []
        setattr(request.state, "route_timings", steps)

    step = {"name": name, "duration_ms": round(duration_ms, 2)}
    step.update(_safe_metadata(metadata))
    steps.append(step)


@contextmanager
def timed_step(request: Any, name: str, **metadata: Any) -> Iterator[None]:
    """Measure a block and add it to the request's route timing steps."""
    started = perf_counter()
    try:
        yield
    finally:
        record_timing(request, name, (perf_counter() - started) * 1000, **metadata)


def get_timings(request: Any) -> list[dict[str, Any]]:
    """Return the route timing steps recorded for a request."""
    if request is None or not hasattr(request, "state"):
        return []
    return list(getattr(request.state, "route_timings", None) or [])
