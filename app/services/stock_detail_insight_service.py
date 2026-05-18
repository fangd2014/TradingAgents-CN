from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional


def normalize_code6(code: str) -> str:
    text = str(code or "").strip().upper()
    if "." in text:
        text = text.split(".", 1)[0]
    return text.zfill(6) if text.isdigit() else text


def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _bar_date(bar: Dict[str, Any]) -> str:
    return str(bar.get("trade_date") or bar.get("date") or bar.get("time") or "")


def _date_sort_key(date_text: str) -> tuple:
    text = str(date_text or "").strip()
    compact_match = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", text)
    if compact_match:
        year, month, day = (int(part) for part in compact_match.groups())
        return (0, year, month, day, 0, 0, 0, text)

    separated_match = re.match(
        (
            r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})"
            r"(?:[T\s](\d{1,2})(?::(\d{1,2})(?::(\d{1,2}))?)?)?"
        ),
        text,
    )
    if separated_match:
        year = int(separated_match.group(1))
        month = int(separated_match.group(2))
        day = int(separated_match.group(3))
        hour = int(separated_match.group(4) or 0)
        minute = int(separated_match.group(5) or 0)
        second = int(separated_match.group(6) or 0)
        return (0, year, month, day, hour, minute, second, text)

    return (1, text)


def calculate_magic_nine(
    bars: List[Dict[str, Any]], lookback: int = 4, target_count: int = 9
) -> Dict[str, Any]:
    required_bars = lookback + target_count
    cleaned = [
        {"date": _bar_date(bar), "close": _safe_float(bar.get("close"))}
        for bar in bars
        if _safe_float(bar.get("close")) is not None
    ]
    cleaned.sort(key=lambda item: _date_sort_key(item["date"]))

    if len(cleaned) < required_bars:
        return {
            "status": "insufficient_data",
            "required_bars": required_bars,
            "available_bars": len(cleaned),
            "current_direction": "none",
            "current_count": 0,
            "latest_signal": None,
            "sequence": [],
        }

    up_count = 0
    down_count = 0
    sequence: List[Dict[str, Any]] = []
    latest_signal = None

    for idx, item in enumerate(cleaned):
        if idx < lookback:
            sequence.append(
                {
                    "date": item["date"],
                    "close": item["close"],
                    "direction": "none",
                    "count": 0,
                    "signal": None,
                }
            )
            continue

        prior_close = cleaned[idx - lookback]["close"]
        direction = "none"
        count = 0
        signal = None

        if item["close"] > prior_close:
            up_count += 1
            down_count = 0
            direction = "up"
            count = up_count
        elif item["close"] < prior_close:
            down_count += 1
            up_count = 0
            direction = "down"
            count = down_count
        else:
            up_count = 0
            down_count = 0

        if count >= target_count:
            signal = {"direction": direction, "count": count, "date": item["date"]}
            latest_signal = signal

        sequence.append(
            {
                "date": item["date"],
                "close": item["close"],
                "direction": direction,
                "count": count,
                "signal": signal,
            }
        )

    last = sequence[-1]
    return {
        "status": "ok",
        "required_bars": required_bars,
        "available_bars": len(cleaned),
        "current_direction": last["direction"],
        "current_count": last["count"],
        "latest_signal": latest_signal,
        "sequence": sequence[-30:],
    }
