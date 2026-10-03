from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.extensions import db
from app.models import Plant, Pond, utcnow
from app.services.rules import (
    COOLDOWN_HOURS,
    PondStateConflict,
    RuleError,
    cooldown_until,
    latest_batch_for_pond,
    locked_pond,
    remaining_minutes,
    transition_pond_status,
)

bp = Blueprint("board", __name__, url_prefix="/board")

STATUS_LABELS = {
    Pond.STATUS_FILLING: "注水中",
    Pond.STATUS_SLAKING: "熟化中",
    Pond.STATUS_DRAWN: "已出灰",
}


def _pond_view(pond: Pond) -> dict:
    """模板用的冷却钟视图数据，时刻一律以服务器为准。"""
    until = cooldown_until(pond)
    return {
        "pond": pond,
        "cooldown_active": until is not None and remaining_minutes(pond) > 0,
        "cooldown_remaining_min": remaining_minutes(pond),
        "cooldown_until": until,
        "cooldown_until_epoch": until.timestamp() if until else None,
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
        pond_cards.append({**_pond_view(pond), "batch": batch})

    selected_id = request.args.get("pond", type=int)
    selected_view = None
    selected_batch = None
    if selected_id:
        selected_view = next(
            (c for c in pond_cards if c["pond"].id == selected_id), None
        )
        if selected_view:
            selected_batch = latest_batch_for_pond(selected_view["pond"])

    return render_template(
        "board/floor.html",
        plants=plants,
        active_plant=active_plant,
        pond_cards=pond_cards,
        selected_view=selected_view,
        selected=selected_view["pond"] if selected_view else None,
        selected_batch=selected_batch,
        status_labels=STATUS_LABELS,
        cooldown_hours=COOLDOWN_HOURS,
        server_now=utcnow(),
    )


@bp.route("/ponds/<int:pond_id>/ops", methods=["POST"])
@login_required
def pond_ops(pond_id: int):
    status = request.form.get("status")
    peak_raw = (request.form.get("peak_temp_c") or "").strip()
    notes = (request.form.get("batch_notes") or "").strip()
    # 抽屉打开时的池态：冷却刚满两人抢改时，靠它让第二笔失败
    from_status = (request.form.get("from_status") or "").strip() or None

    plant_id = None
    try:
        pond = locked_pond(pond_id)
        plant_id = pond.plant_id
        batch = latest_batch_for_pond(pond)
        if batch is None:
            flash("该池尚无熟化批次，无法登记峰值或出灰", "error")
            return redirect(
                url_for("board.floor_plan", plant_id=plant_id, pond=pond_id)
            )

        if peak_raw:
            try:
                batch.peak_temp_c = float(peak_raw)
            except ValueError:
                flash("峰值温度格式无效", "error")
                return redirect(
                    url_for("board.floor_plan", plant_id=plant_id, pond=pond_id)
                )
        batch.notes = notes

        new_status = status or pond.status
        # 持锁做状态迁移：冷却未满在此中文报错；满后抢改只有一笔能过
        transition_pond_status(pond, new_status, expected_status=from_status)
        db.session.commit()
        flash(f"{pond.code} 已更新", "ok")
    except (RuleError, PondStateConflict) as exc:
        db.session.rollback()
        flash(str(exc), "error")
        failed_pond = db.session.get(Pond, pond_id)
        plant_id = failed_pond.plant_id if failed_pond else None

    return redirect(
        url_for("board.floor_plan", plant_id=plant_id, pond=pond_id)
    )


@bp.route("/cooldown")
@login_required
def cooldown_clock():
    """冷却钟专页：按厂区列出冷却中池与剩余分钟，时刻跟服务器走。"""
    now = utcnow()
    plants = Plant.query.order_by(Plant.name).all()
    plant_rows = []
    for plant in plants:
        cooling = []
        ready = []
        for pond in plant.ponds:
            if pond.status != Pond.STATUS_DRAWN or pond.drawn_at is None:
                continue
            view = _pond_view(pond)
            if view["cooldown_active"]:
                cooling.append(view)
            else:
                ready.append(view)
        cooling.sort(key=lambda v: v["cooldown_until"])
        ready.sort(key=lambda v: v["pond"].code)
        if cooling or ready:
            plant_rows.append(
                {"plant": plant, "cooling": cooling, "ready": ready}
            )
    return render_template(
        "board/cooldown.html",
        plant_rows=plant_rows,
        status_labels=STATUS_LABELS,
        cooldown_hours=COOLDOWN_HOURS,
        server_now=now,
        server_now_epoch=now.timestamp(),
    )
