from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.extensions import db
from app.models import Plant, Pond, utcnow
from app.services.rules import (
    RuleError,
    apply_pond_status,
    cooldown_remaining_minutes,
    cooldown_until,
    latest_batch_for_pond,
)

bp = Blueprint("board", __name__, url_prefix="/board")

STATUS_LABELS = {
    Pond.STATUS_FILLING: "注水中",
    Pond.STATUS_SLAKING: "熟化中",
    Pond.STATUS_DRAWN: "已出灰",
}


def _pond_view(pond: Pond) -> dict:
    """模板用的池位视图数据：冷却状态与服务器时刻口径的剩余分钟。"""
    remaining = cooldown_remaining_minutes(pond)
    return {
        "pond": pond,
        "cooldown": remaining is not None,
        "remaining_minutes": remaining or 0,
        "cooldown_until_iso": cooldown_until(pond).isoformat() if remaining is not None else "",
    }


@bp.route("/")
@login_required
def floor_plan():
    plants = Plant.query.order_by(Plant.name).all()
    plant_id_raw = request.args.get("plant_id", "").strip()
    active_plant = None
    if plant_id_raw.isdigit():
        active_plant = db.session.get(Plant, int(plant_id_raw))
    if active_plant is None and plants:
        active_plant = plants[0]

    ponds = []
    if active_plant:
        ponds = (
            Pond.query.filter_by(plant_id=active_plant.id)
            .order_by(Pond.code)
            .all()
        )

    pond_cards = []
    for pond in ponds:
        batch = latest_batch_for_pond(pond)
        card = _pond_view(pond)
        card["batch"] = batch
        pond_cards.append(card)

    selected_id = request.args.get("pond", type=int)
    selected = None
    selected_batch = None
    selected_view = None
    if selected_id:
        selected = next((c["pond"] for c in pond_cards if c["pond"].id == selected_id), None)
        if selected:
            selected_batch = latest_batch_for_pond(selected)
            selected_view = next(c for c in pond_cards if c["pond"].id == selected_id)

    return render_template(
        "board/floor.html",
        plants=plants,
        active_plant=active_plant,
        pond_cards=pond_cards,
        selected=selected,
        selected_batch=selected_batch,
        selected_view=selected_view,
        status_labels=STATUS_LABELS,
        server_now_iso=utcnow().isoformat(),
    )


@bp.route("/ponds/<int:pond_id>/ops", methods=["POST"])
@login_required
def pond_ops(pond_id: int):
    # 行锁串行化同一池位的改态：冷却刚满时两人抢改回注水中，只许一笔成功。
    pond = (
        db.session.query(Pond)
        .filter(Pond.id == pond_id)
        .with_for_update()
        .first()
    )
    if pond is None:
        return redirect(url_for("board.floor_plan"))
    status = request.form.get("status") or pond.status
    from_status = (request.form.get("from_status") or "").strip()

    batch = latest_batch_for_pond(pond)
    if batch is None:
        db.session.rollback()
        flash("该池尚无熟化批次，无法登记峰值或出灰", "error")
        return redirect(
            url_for("board.floor_plan", plant_id=pond.plant_id, pond=pond.id)
        )

    # 乐观并发：页面渲染时的状态必须与行锁拿到的当前状态一致。
    # 冷却刚满两人抢改回注水中时，后者会在这里被明确拦下（只许一笔成功）。
    if from_status and from_status != pond.status:
        db.session.rollback()
        flash(f"{pond.code} 状态已被他人更新，请刷新页面后重试", "error")
        return redirect(
            url_for("board.floor_plan", plant_id=pond.plant_id, pond=pond.id)
        )

    peak_raw = (request.form.get("peak_temp_c") or "").strip()
    notes = (request.form.get("batch_notes") or "").strip()

    if peak_raw:
        try:
            batch.peak_temp_c = float(peak_raw)
        except ValueError:
            db.session.rollback()
            flash("峰值温度格式无效", "error")
            return redirect(
                url_for("board.floor_plan", plant_id=pond.plant_id, pond=pond.id)
            )

    batch.notes = notes

    try:
        changed = apply_pond_status(pond, status)
        db.session.commit()
        if changed:
            flash(f"{pond.code} 已更新为{STATUS_LABELS.get(status, status)}", "ok")
        else:
            flash(f"{pond.code} 作业记录已保存", "ok")
    except RuleError as exc:
        db.session.rollback()
        flash(str(exc), "error")

    return redirect(url_for("board.floor_plan", plant_id=pond.plant_id, pond=pond.id))
