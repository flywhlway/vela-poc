"""时间工具：解析、格式化、桶化。全部使用 timezone-aware UTC。"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
_BUCKETS = {"1s": 1, "10s": 10, "30s": 30, "1m": 60, "5m": 300,
            "15m": 900, "1h": 3600, "1d": 86400}

_MONTHS = {m: i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}


def utcnow() -> datetime:
    return datetime.now(UTC)


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    t = s.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def bucket_seconds(name: str) -> int:
    return _BUCKETS.get(name, 60)


def floor_to_bucket(dt: datetime, bucket: str) -> datetime:
    step = bucket_seconds(bucket)
    epoch = int(dt.replace(tzinfo=UTC).timestamp())
    return datetime.fromtimestamp(epoch - epoch % step, UTC)


def parse_bsd_month_day(s: str, year: int) -> datetime | None:
    """'Jul 20 11:22:33' -> datetime（年份由外部推断给出）。"""
    m = re.match(r"^([A-Z][a-z]{2})\s+(\d{1,2})\s+(\d{2}):(\d{2}):(\d{2})$", s.strip())
    if not m:
        return None
    mon = _MONTHS.get(m.group(1))
    if not mon:
        return None
    try:
        return datetime(year, mon, int(m.group(2)), int(m.group(3)),
                        int(m.group(4)), int(m.group(5)), tzinfo=UTC)
    except ValueError:
        return None


def add_ms(dt: datetime, ms: float) -> datetime:
    return dt + timedelta(milliseconds=ms)
