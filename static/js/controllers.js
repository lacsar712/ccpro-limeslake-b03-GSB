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
    const filling = this.statusTarget.querySelector('option[value="filling"]')
    if (this.statusTarget.value === "drawn") {
      this.hintTarget.textContent =
        "当前选择「已出灰」：须存在最近批次，且峰值温度已记录并 ≥ 60℃。冷却不挡出灰。"
    } else if (this.statusTarget.value === "filling" && filling?.disabled) {
      this.hintTarget.textContent =
        "该池出灰冷却未满，改回注水中会被拒绝，请等待冷却钟走完。"
    } else {
      this.hintTarget.textContent =
        "出灰后默认冷却 4 小时；冷却未满不能改回注水中，也不能登记新班。"
    }
  }
}

class CountdownController extends Controller {
  // 冷却倒计时：以页面携带的服务器时刻为基准对时，客户端时钟偏差不影响结果。
  static targets = ["clock", "row", "refillOption", "untilLocal"]
  static values = { serverNow: String, until: String }

  connect() {
    this.offsetMs = this.hasServerNowValue
      ? Date.parse(this.serverNowValue) - Date.now()
      : 0
    this.untilLocalTargets.forEach((el) => {
      const d = new Date(Date.parse(el.dataset.until))
      const hh = String(d.getHours()).padStart(2, "0")
      const mm = String(d.getMinutes()).padStart(2, "0")
      el.textContent = `至 ${hh}:${mm}（本地时间）`
    })
    this.tick()
    this.timer = window.setInterval(() => this.tick(), 1000)
  }

  disconnect() {
    window.clearInterval(this.timer)
  }

  tick() {
    const serverNow = Date.now() + this.offsetMs
    this.clockTargets.forEach((el) => {
      el.textContent = this._format(Date.parse(el.dataset.until) - serverNow)
    })
    this.rowTargets.forEach((row) => {
      const remainingMs = Date.parse(row.dataset.until) - serverNow
      const cooling = remainingMs > 0
      if (row.dataset.cooling !== (cooling ? "true" : "false")) {
        row.classList.toggle("is-cooling", cooling)
        row.classList.toggle("is-ready", !cooling)
        row.dataset.cooling = cooling ? "true" : "false"
        const label = row.querySelector('[data-countdown-target="remaining"]')
        if (label) label.textContent = cooling ? this._format(remainingMs) : "冷却已满"
        const button = row.querySelector('[data-countdown-target="button"]')
        if (button) {
          button.disabled = cooling
          button.textContent = cooling ? "冷却中…" : "改回注水中"
        }
      }
    })
    this.refillOptionTargets.forEach((option) => {
      const until = option.dataset.until || this.untilValue
      const remainingMs = Date.parse(until) - serverNow
      const cooling = remainingMs > 0
      if (option.disabled !== cooling) {
        option.disabled = cooling
        option.dispatchEvent(new Event("change", { bubbles: true }))
      }
      if (cooling) {
        option.textContent = `${option.dataset.baseLabel || "注水中"}（${this._format(remainingMs)}）`
      } else if (option.textContent !== (option.dataset.baseLabel || "注水中")) {
        option.textContent = option.dataset.baseLabel || "注水中"
      }
    })
  }

  _format(remainingMs) {
    if (remainingMs <= 0) return "冷却已满"
    const totalSeconds = Math.ceil(remainingMs / 1000)
    if (totalSeconds < 60) return `剩余 ${totalSeconds} 秒`
    const minutes = Math.ceil(totalSeconds / 60)
    return `剩余 ${minutes} 分钟`
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

application.register("flash", FlashController)
application.register("form-hint", FormHintController)
application.register("board", BoardController)
application.register("countdown", CountdownController)
