"""石灰熟化池业务规则。"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from app.extensions import db
from app.models import Pond, SlakeBatch, utcnow

MIN_PEAK_TEMP_FOR_DRAWN = 60.0
COOLDOWN_HOURS = 4


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


def cooldown_until(pond: Pond) -> datetime | None:
    """冷却钟结束时刻（UTC，aware）；未在冷却中返回 None。"""
    if pond.status != Pond.STATUS_DRAWN or pond.drawn_at is None:
        return None
    drawn_at = pond.drawn_at
    if drawn_at.tzinfo is None:
        # SQLite 等后端返回 naive 值时按 UTC 解释
        drawn_at = drawn_at.replace(tzinfo=timezone.utc)
    return drawn_at + timedelta(hours=COOLDOWN_HOURS)


def cooldown_remaining(pond: Pond, now: datetime | None = None) -> timedelta | None:
    """剩余冷却时长；冷却已满或不在冷却中返回 None。"""
    until = cooldown_until(pond)
    if until is None:
        return None
    now = now or utcnow()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    delta = until - now
    return delta if delta.total_seconds() > 0 else None


def remaining_minutes(pond: Pond, now: datetime | None = None) -> int:
    """剩余冷却分钟数（向上取整，至少显示 1 分钟）；已满返回 0。"""
    delta = cooldown_remaining(pond, now)
    if delta is None:
        return 0
    return max(1, math.ceil(delta.total_seconds() / 60))


def assert_cooldown_finished(pond: Pond, action: str = "改回注水中") -> None:
    minutes = remaining_minutes(pond)
    if minutes > 0:
        raise RuleError(
            f"{pond.code} 已出灰，处于 {COOLDOWN_HOURS} 小时冷却期，"
            f"剩余约 {minutes} 分钟，冷却未满不能{action}"
        )


def assert_can_set_pond_status(pond: Pond, new_status: str) -> None:
    if new_status not in Pond.STATUS_CHOICES:
        raise RuleError(f"无效状态：{new_status}")
    if new_status == Pond.STATUS_DRAWN:
        ok, msg = can_mark_pond_drawn(pond)
        if not ok:
            raise RuleError(msg)
    elif new_status == Pond.STATUS_FILLING and pond.status == Pond.STATUS_DRAWN:
        # 已出灰 → 注水中：冷却钟未满一律拒绝
        assert_cooldown_finished(pond)


def assert_can_register_batch(pond: Pond) -> None:
    """冷却期内禁止给该池登记新班。"""
    if pond.status == Pond.STATUS_DRAWN:
        assert_cooldown_finished(pond, action="登记新班")


def apply_pond_status(pond: Pond, new_status: str) -> None:
    """
    统一的池状态迁移入口（须在事务/行锁内调用）：
    - drawn → filling：冷却未满由 assert 拒绝；放行后清空 drawn_at；
    - 其它状态 → drawn：峰值门槛照旧，冷却不挡出灰；打点 drawn_at；
      已经是 drawn 时重复保存（只改备注/峰值）不重打点，避免冷却钟被重置；
    - 其它迁移：drawn_at 保持不变。
    """
    assert_can_set_pond_status(pond, new_status)
    old_status = pond.status
    if new_status == Pond.STATUS_DRAWN and (
        old_status != Pond.STATUS_DRAWN or pond.drawn_at is None
    ):
        pond.drawn_at = utcnow()
    elif old_status == Pond.STATUS_DRAWN and new_status == Pond.STATUS_FILLING:
        pond.drawn_at = None
    pond.status = new_status


class PondStateConflict(RuleError):
    """池状态在读取后已被他人抢先修改（并发冲突）。"""


def locked_pond(pond_id: int) -> Pond:
    """SELECT ... FOR UPDATE 取池，配合 from_status 保证并发改态只有一笔成功。"""
    pond = db.session.query(Pond).filter_by(id=pond_id).with_for_update().first()
    if pond is None:
        from flask import abort

        abort(404)
    return pond


def transition_pond_status(
    pond: Pond, new_status: str, expected_status: str | None = None
) -> None:
    """
    持锁状态迁移：expected_status 给定时若池态已被他人改走，抛冲突错误，
    使冷却刚满时的两人抢改只许一笔成功。

    FOR UPDATE 在 PostgreSQL 上让后来的事务等待并读到最新版本；
    再补一条以旧状态为条件的原子 UPDATE（CAS），保证其它后端/隔离级别下
    也只有一笔事务能匹配到旧状态。
    """
    if expected_status is not None and pond.status != expected_status:
        raise PondStateConflict(
            f"{pond.code} 状态刚被他人更新为「{pond.status}」，请刷新后重试"
        )
    if expected_status is not None:
        from sqlalchemy import update
        from sqlalchemy.sql import func

        result = db.session.execute(
            update(Pond)
            .where(Pond.id == pond.id, Pond.status == expected_status)
            .values(updated_at=func.current_timestamp())
        )
        if result.rowcount == 0:
            raise PondStateConflict(
                f"{pond.code} 状态刚被他人更新，请刷新后重试"
            )
    apply_pond_status(pond, new_status)
