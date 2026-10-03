"""出灰冷却钟专页：按厂列出冷却中的池位与剩余分钟，并放行冷却满后的改回注水。"""

from flask import Blueprint, flash, redirect, render_template, url_for
from flask_login import login_required

from app.extensions import db
from app.models import Plant, Pond, utcnow
from app.services.rules import (
    RuleError,
    apply_pond_status,
    cooldown_remaining_minutes,
    cooldown_until,
)

bp = Blueprint("cooldowns", __name__, url_prefix="/cooldowns")


def _cooldown_rows():
    """
    按厂区分组列出「已出灰且冷却钟在走/刚走完」的池位，时刻一律以服务器 utcnow 为准。
    冷却中：剩余分钟 > 0；冷却已满但尚未改回注水：remaining_minutes 为 None，专页直接放行。
    """
    plants = Plant.query.order_by(Plant.name).all()
    groups = []
    total_cooling = 0
    for plant in plants:
        rows = []
        for pond in sorted(plant.ponds, key=lambda p: p.code):
            if pond.status != Pond.STATUS_DRAWN or pond.drawn_at is None:
                continue
            remaining = cooldown_remaining_minutes(pond)
            if remaining is not None:
                total_cooling += 1
            rows.append(
                {
                    "pond": pond,
                    "cooling": remaining is not None,
                    "remaining_minutes": remaining or 0,
                    "cooldown_until": cooldown_until(pond),
                }
            )
        if rows:
            groups.append({"plant": plant, "rows": rows})
    return groups, total_cooling


@bp.route("/")
@login_required
def list_cooldowns():
    groups, total_cooling = _cooldown_rows()
    return render_template(
        "cooldowns/list.html",
        groups=groups,
        total_cooling=total_cooling,
        server_now_iso=utcnow().isoformat(),
    )


@bp.route("/ponds/<int:pond_id>/refill", methods=["POST"])
@login_required
def refill_pond(pond_id: int):
    # 与抽屉改态共用同一规则与行锁：冷却未满必失败，刚满抢改只许一笔成功。
    pond = (
        db.session.query(Pond)
        .filter(Pond.id == pond_id)
        .with_for_update()
        .first()
    )
    if pond is None:
        flash("池位不存在", "error")
        return redirect(url_for("cooldowns.list_cooldowns"))
    # 冷却刚满两人抢改：第一个提交把状态改成注水中并提交；后者拿到锁时
    # 状态已不是 drawn，在这里被明确拒绝，保证只许一笔成功。
    if pond.status != Pond.STATUS_DRAWN:
        db.session.rollback()
        flash(f"{pond.code} 已被他人改回注水中，本笔未生效", "error")
        return redirect(url_for("cooldowns.list_cooldowns"))
    try:
        changed = apply_pond_status(pond, Pond.STATUS_FILLING)
        db.session.commit()
        if changed:
            flash(f"{pond.code} 冷却已满，已放行改回注水中", "ok")
        else:
            flash(f"{pond.code} 当前已是注水中", "ok")
    except RuleError as exc:
        db.session.rollback()
        flash(str(exc), "error")
    return redirect(url_for("cooldowns.list_cooldowns"))
