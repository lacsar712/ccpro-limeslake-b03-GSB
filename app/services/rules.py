"""石灰熟化池业务规则。"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from app.models import Pond, SlakeBatch, utcnow

MIN_PEAK_TEMP_FOR_DRAWN = 60.0


def cooldown_duration() -> timedelta:
    """出灰后的强制冷却时长，默认 4 小时，可用 POND_COOLDOWN_HOURS 覆盖。"""
    raw = os.environ.get("POND_COOLDOWN_HOURS", "4")
    try:
        hours = float(raw)
    except (TypeError, ValueError):
        hours = 4.0
    return timedelta(hours=hours)


def _as_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def cooldown_until(pond: Pond) -> datetime | None:
    """冷却结束时刻（UTC，感知时区）；不在冷却中返回 None。"""
    if pond.status != Pond.STATUS_DRAWN or pond.drawn_at is None:
        return None
    return _as_aware(pond.drawn_at) + cooldown_duration()


def cooldown_remaining(pond: Pond, now: datetime | None = None) -> timedelta | None:
    """冷却剩余时长；已满或不在冷却中返回 None。"""
    until = cooldown_until(pond)
    if until is None:
        return None
    now = now or utcnow()
    remaining = until - _as_aware(now)
    return remaining if remaining.total_seconds() > 0 else None


def cooldown_remaining_minutes(pond: Pond, now: datetime | None = None) -> int | None:
    """冷却剩余整分钟（向上取整，未满 1 分钟也显示 1 分钟）；已满返回 None。"""
    remaining = cooldown_remaining(pond, now)
    if remaining is None:
        return None
    seconds = max(1, int(remaining.total_seconds() + 0.999))
    return (seconds + 59) // 60


def is_cooling_down(pond: Pond, now: datetime | None = None) -> bool:
    return cooldown_remaining(pond, now) is not None and pond.status == Pond.STATUS_DRAWN


class RuleError(ValueError):
    """业务规则校验失败。"""


def latest_batch_for_pond(pond: Pond) -> SlakeBatch | None:
    if not pond.batches:
        return None
    return max(pond.batches, key=lambda b: b.started_at)


def can_mark_pond_drawn(pond: Pond) -> tuple[bool, str]:
    """
    熟化池转为「已出灰」(drawn) 的前提：
    最近一条熟化批次的峰值温度已记录，且 >= 60℃。
    冷却不挡出灰——本规则与冷却钟互不影响。
    """
    latest = latest_batch_for_pond(pond)
    if latest is None:
        return False, "该池尚无熟化批次，不能标记为已出灰"
    if latest.peak_temp_c is None:
        return False, "最近批次尚未记录峰值温度，不能标记为已出灰"
    if latest.peak_temp_c < MIN_PEAK_TEMP_FOR_DRAWN:
        return (
            False,
            f"最近批次峰值温度 {latest.peak_temp_c}℃ 低于 {MIN_PEAK_TEMP_FOR_DRAWN:.0f}℃，不能标记为已出灰",
        )
    return True, ""


def assert_can_set_pond_status(pond: Pond, new_status: str) -> None:
    if new_status not in Pond.STATUS_CHOICES:
        raise RuleError(f"无效状态：{new_status}")
    if new_status == pond.status:
        return
    if new_status == Pond.STATUS_DRAWN:
        ok, msg = can_mark_pond_drawn(pond)
        if not ok:
            raise RuleError(msg)
        return
    if (
        pond.status == Pond.STATUS_DRAWN
        and new_status == Pond.STATUS_FILLING
        and is_cooling_down(pond)
    ):
        left = cooldown_remaining_minutes(pond)
        raise RuleError(
            f"{pond.code} 出灰后冷却中，还差约 {left} 分钟才能改回注水中"
            if left
            else f"{pond.code} 出灰后冷却未满，暂不能改回注水中"
        )


def apply_pond_status(pond: Pond, new_status: str) -> bool:
    """
    改池态的统一入口：先过规则，再落状态并维护冷却钟起点 drawn_at。
    校验失败抛 RuleError。返回状态是否真的发生变化。
    """
    assert_can_set_pond_status(pond, new_status)
    if new_status == pond.status:
        return False
    pond.status = new_status
    pond.drawn_at = utcnow() if new_status == Pond.STATUS_DRAWN else None
    return True


def assert_can_register_batch(pond: Pond, now: datetime | None = None) -> None:
    """冷却中的池禁止登记新班。"""
    if pond.status == Pond.STATUS_DRAWN and pond.drawn_at is not None:
        remaining = cooldown_remaining(pond, now)
        if remaining is not None:
            left = cooldown_remaining_minutes(pond, now)
            raise RuleError(
                f"{pond.code} 出灰后冷却中，还差约 {left} 分钟，禁止登记新班"
                if left
                else f"{pond.code} 出灰后冷却未满，禁止登记新班"
            )
