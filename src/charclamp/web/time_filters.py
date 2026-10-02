"""模板用时间过滤器：库存 UTC 带时区，展示/回填一律转窑场本地钟面。"""

from __future__ import annotations

from datetime import datetime, timezone

from charclamp.domain.models import app_timezone


def to_local(dt: datetime) -> datetime:
    # SQLite 等不保留时区的后端读回的是朴素 UTC，统一按 UTC 解释。
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(app_timezone())


def dt_display(dt: datetime, fmt: str = "%Y-%m-%d %H:%M") -> str:
    return to_local(dt).strftime(fmt)


def dt_input_value(dt: datetime) -> str:
    # datetime-local 输入框要求的墙钟格式（本地时区，无时区后缀）。
    return to_local(dt).strftime("%Y-%m-%dT%H:%M")


def dt_iso(dt: datetime) -> str:
    # <time datetime> 机器值：归一 UTC 并带时区后缀。
    return to_local(dt).astimezone(timezone.utc).isoformat()
