import { Application, Controller } from "https://unpkg.com/@hotwired/stimulus@3.2.2/dist/stimulus.js"

const application = Application.start()

class FlashController extends Controller {
  static targets = ["item"]
  connect() {
    window.setTimeout(() => {
      this.itemTargets.forEach((el) => {
        el.style.opacity = "0"
        el.style.transition = "opacity .4s"
      })
    }, 4000)
  }
}

class FormHintController extends Controller {
  static targets = ["status", "hint"]
  connect() {
    this.update()
    this.statusTarget?.addEventListener("change", () => this.update())
  }
  update() {
    if (!this.hasHintTarget || !this.hasStatusTarget) return
    // 冷却未满时注水选项处于 disabled 锁定，提示冷却剩余而不是出灰门槛
    const lock = this.element.querySelector('[data-countdown-target="lock"]')
    if (lock && lock.disabled && this.statusTarget.value === "drawn") {
      this.hintTarget.textContent =
        lock.dataset.hint || "已出灰冷却中，冷却未满不能改回注水中、不能登记新班。"
      return
    }
    if (this.statusTarget.value === "drawn") {
      this.hintTarget.textContent =
        "当前选择「已出灰」：须存在最近批次，且峰值温度已记录并 ≥ 60℃。"
    } else {
      this.hintTarget.textContent =
        "出灰前请确认最近熟化批次已记录峰值温度且不低于 60℃。"
    }
  }
  // 冷却钟倒计时到点后，把冷却提示换回常规提示
  onCooldownTick(event) {
    if (event.detail?.done) this.update()
  }
}

class BoardController extends Controller {
  static targets = ["drawer", "backdrop"]
  static values = { open: Boolean }

  connect() {
    if (this.openValue) this._setOpen(true)
  }

  openDrawer() {
    // Navigation still loads selected pond; keep drawer state consistent on SPA-less click
    this._setOpen(true)
  }

  closeDrawer(event) {
    if (event) event.preventDefault()
    this._setOpen(false)
    const closeLink = event?.currentTarget
    if (closeLink?.href) {
      window.location.href = closeLink.href
    } else if (this.hasBackdropTarget) {
      const base = new URL(window.location.href)
      base.searchParams.delete("pond")
      window.location.href = base.toString()
    }
  }

  _setOpen(open) {
    this.openValue = open
    if (this.hasDrawerTarget) {
      this.drawerTarget.classList.toggle("is-open", open)
      this.drawerTarget.setAttribute("aria-hidden", open ? "false" : "true")
    }
    if (this.hasBackdropTarget) {
      this.backdropTarget.classList.toggle("is-open", open)
    }
  }
}

// 冷却钟倒计时：以服务器时刻为基准（页面渲染时注入 now），
// 只借用本地时钟走秒，避免客户端改时间造成倒计时偏差。
class CountdownController extends Controller {
  static targets = ["timer", "clock", "gate", "lock"]
  static values = { now: Number, reload: Boolean }

  connect() {
    // 服务器 epoch（秒）与本机的偏差；serverNow = Date.now()/1000 + offset
    this.offset = (this.nowValue || Date.now() / 1000) - Date.now() / 1000
    this._done = new WeakSet()
    this._reloaded = false
    this.tick()
    this.timer = window.setInterval(() => this.tick(), 1000)
  }

  disconnect() {
    window.clearInterval(this.timer)
  }

  serverNow() {
    return Date.now() / 1000 + this.offset
  }

  tick() {
    const now = this.serverNow()
    if (this.hasClockTarget) {
      this.clockTarget.textContent = new Date(now * 1000).toLocaleString("zh-CN", {
        timeZone: "UTC",
        hour12: false,
      })
    }
    this.timerTargets.forEach((el) => this._updateTimer(el, now))
    this.gateTargets.forEach((el) => this._updateGate(el, now))
    this.lockTargets.forEach((el) => this._updateLock(el, now))
    // 专页上所有倒计时都满后，回服务器重取一次，让「已满待放行」分组与顶栏角标更新
    if (
      this.reloadValue &&
      !this._reloaded &&
      this.timerTargets.length > 0 &&
      this.timerTargets.every((el) => parseFloat(el.dataset.until) - now <= 0)
    ) {
      this._reloaded = true
      window.setTimeout(() => window.location.reload(), 1200)
    }
  }

  _remainText(el, remainSec) {
    const totalMin = Math.ceil(remainSec / 60)
    if (el.dataset.compact) return `冷却 ${totalMin} 分`
    const h = Math.floor(remainSec / 3600)
    const m = Math.floor((remainSec % 3600) / 60)
    const s = remainSec % 60
    if (h > 0) return `冷却中 · 剩余 ${h} 小时 ${m} 分`
    if (m > 0) return `冷却中 · 剩余 ${m} 分 ${String(s).padStart(2, "0")} 秒`
    return `冷却中 · 剩余 ${s} 秒`
  }

  _updateTimer(el, now) {
    const until = parseFloat(el.dataset.until)
    const remain = Math.ceil(until - now)
    if (remain > 0) {
      el.textContent = this._remainText(el, remain)
      el.classList.remove("is-done")
      return
    }
    el.textContent = el.dataset.done || "冷却已满，可放行"
    el.classList.add("is-done")
    const item = el.closest(".cooldown-item, .pond-tile")
    if (item) item.classList.add("cooldown-done")
    this._fireDone(el, until)
  }

  _updateGate(el, now) {
    const until = parseFloat(el.dataset.lockUntil)
    if (until - now <= 0) {
      el.classList.add("is-done")
      el.classList.remove("is-locked")
    }
    this._fireDone(el, until)
  }

  _updateLock(el, now) {
    const until = parseFloat(el.dataset.until)
    if (until - now <= 0) {
      el.removeAttribute("disabled")
      el.textContent = el.dataset.doneLabel || "注水中"
      const banner = el.closest("form")?.querySelector(".cooldown-banner")
      banner?.classList.add("is-done")
      banner?.classList.remove("is-locked")
      this._fireDone(el, until)
    }
  }

  // 每个到点元素只派发一次 countdown:tick(done=true)，供同页其他控制器接收
  _fireDone(el, until) {
    if (this._done.has(el)) return
    this._done.add(el)
    this.dispatch("tick", { detail: { done: true, until } })
  }
}

application.register("flash", FlashController)
application.register("form-hint", FormHintController)
application.register("board", BoardController)
application.register("countdown", CountdownController)
