from datetime import datetime

from app.utils.timezone import to_config_tz


def test_mongodb_naive_task_time_is_converted_from_utc_to_beijing():
    stored = datetime(2026, 5, 12, 10, 58, 45)

    display = to_config_tz(stored)

    assert display.isoformat() == "2026-05-12T18:58:45+08:00"
