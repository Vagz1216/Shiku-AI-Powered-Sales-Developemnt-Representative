from types import SimpleNamespace

from utils.request_timing import get_timings, record_timing, timed_step


def test_record_timing_adds_safe_step_metadata():
    request = SimpleNamespace(state=SimpleNamespace())

    record_timing(
        request,
        "db.query",
        12.345,
        count=3,
        enabled=True,
        skipped=None,
        unsafe={"nested": "ignored"},
    )

    assert get_timings(request) == [
        {"name": "db.query", "duration_ms": 12.35, "count": 3, "enabled": True}
    ]


def test_timed_step_records_duration():
    request = SimpleNamespace(state=SimpleNamespace())

    with timed_step(request, "auth.verify_token", cached=False):
        pass

    steps = get_timings(request)
    assert len(steps) == 1
    assert steps[0]["name"] == "auth.verify_token"
    assert steps[0]["cached"] is False
    assert steps[0]["duration_ms"] >= 0


def test_timing_helpers_ignore_missing_request_state():
    record_timing(None, "ignored", 1)

    with timed_step(None, "ignored"):
        pass

    assert get_timings(None) == []
