import pytest

from sualw.proc import Process


@pytest.fixture
def sample_json() -> dict:
    return {
        "pid": 1234,
        "pgid": 1234,
        "command": ["/usr/bin/uvicorn", "main:app"],
        "log": "/home/user/.hush/logs/uvicorn.log",
        "started_at": "2026-01-01T10:00:00",
        "exit_code": None,
    }


def test_from_json_sets_all_fields(sample_json):
    proc = Process.from_json("uvicorn", sample_json)
    assert proc.name == "uvicorn"
    assert proc.pid == 1234
    assert proc.command == ["/usr/bin/uvicorn", "main:app"]
    assert proc.exit_code is None


def test_round_trip_is_lossless(sample_json):
    original_json = sample_json
    proc = Process.from_json("uvicorn", original_json)
    recovered_json = proc.to_json()
    assert recovered_json == original_json


def test_from_json_handles_missing_exit_code(sample_json):
    json_obj = sample_json
    del json_obj["exit_code"]
    proc = Process.from_json("uvicorn", json_obj)
    assert proc.exit_code is None


def make_proc(started_at: str) -> Process:
    return Process(
        name="test",
        pid=1,
        pgid=1,
        command=["x"],
        log="/tmp/x.log",
        started_at=started_at,
    )


def test_seconds():
    from datetime import UTC, datetime, timedelta

    ts = (datetime.now(UTC) - timedelta(seconds=30)).isoformat(timespec="seconds")
    proc = make_proc(ts)
    assert proc.uptime.endswith("s")
    assert "30" in proc.uptime or "29" in proc.uptime  # allow 1s timing slack


def test_minutes():
    from datetime import UTC, datetime, timedelta

    ts = (datetime.now(UTC) - timedelta(minutes=5, seconds=12)).isoformat(
        timespec="seconds"
    )
    proc = make_proc(ts)
    assert "5m" in proc.uptime


def test_hours():
    from datetime import UTC, datetime, timedelta

    ts = (datetime.now(UTC) - timedelta(hours=2, minutes=30)).isoformat(
        timespec="seconds"
    )
    proc = make_proc(ts)
    assert "2h" in proc.uptime


def test_bad_timestamp_returns_zero():
    proc = make_proc("not-a-date")
    # Should not raise — just return 0s
    assert proc.uptime == "0s"
