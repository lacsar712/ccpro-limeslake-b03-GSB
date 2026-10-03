# LimeSlake-01 · 石灰熟化池作业板

厂区熟化池平面图作业基线（Flask + Jinja + Stimulus）。主界面是按厂区排布的池位瓦片，点选后在右侧抽屉登记峰值温度并改状态——不是侧栏双列表 CRUD。

## 技术栈

| 层 | 技术 |
| --- | --- |
| Web | Flask 3 · Blueprints · Flask-Login · Jinja2 · Stimulus CDN |
| 数据 | SQLAlchemy · PostgreSQL 15 |
| 部署 | Docker Compose · Gunicorn |

## 路径与端口

- **项目路径**：`d:\work\document\bytecode\claudeCodePro\LimeSlake\LimeSlake-01`
- **Web**：http://localhost:4730
- **PostgreSQL**：localhost:6130

## 演示账号

| 用户名 | 密码 | 角色 |
| --- | --- | --- |
| `admin` | `123456` | 管理员 |
| `worker` | `123456` | 操作工 |

登录页已预填 `admin` / `123456`。启动时 entrypoint 会建表并写入种子数据（示范厂区：**东湾石灰厂**）。

## 主界面

- **熟化池平面图**（`/board/`）：CSS 网格池位瓦片，按状态着色（注水中 / 熟化中 / 已出灰）
- 顶部厂区切换芯片（多厂时切换）
- 点击瓦片 → 右侧抽屉展示最近 `SlakeBatch`，可登记峰值温度并变更池状态
- 主导航不再挂「熟化池列表 / 批次列表」；旧 `/ponds/`、`/batches/` 路由仍保留但不作为作业入口

## 业务规则

1. 熟化池状态不可设为「已出灰」（`drawn`），除非该池**最近一条** `SlakeBatch` 的 `peakTempC` 已记录且 **≥ 60℃**。
2. 池位一旦标记为「已出灰」即进入**冷却钟**，默认 **4 小时**（`COOLDOWN_HOURS`，可在 `app/services/rules.py` 调整）：
   - 冷却未满禁止改回「注水中」（抽屉与编辑页同一链路，服务端强制拦截，中文提示剩余分钟）；
   - 冷却未满禁止给该池**登记新班**；
   - 冷却**不挡出灰**：峰值门槛照旧，冷却期内仍可再次标记已出灰。
3. 冷却满后，抽屉与「冷却钟」专页同时放行；改回注水中后出灰打点（`ponds.drawn_at`）清空。
4. 并发安全：冷却刚满时两人几乎同时抢改回注水中，经 `SELECT … FOR UPDATE` + 旧状态条件 UPDATE，**只许一笔成功**，另一笔收到中文冲突提示。

**冷却钟专页**（`/board/cooldown`，顶栏「冷却钟」入口带冷却中数量角标）：按厂区列出冷却中池位、出灰时刻与剩余分钟；倒计时以**服务器时刻**为基准（页面注入 epoch，前端只借本机时钟走秒，客户端改时间不影响判定），全部到点后自动刷新。

规则实现：`app/services/rules.py`（`assert_can_set_pond_status` / `assert_can_register_batch` / `apply_pond_status` / `transition_pond_status`）。
旧库启动时由 `ensure_schema()` 自动补 `ponds.drawn_at` 列，无需手工迁移。

## 快速启动

```bash
cd d:\work\document\bytecode\claudeCodePro\LimeSlake\LimeSlake-01
docker compose up --build
```

浏览器打开 http://localhost:4730

停止：

```bash
docker compose down
```

## 目录结构

```
LimeSlake-01/
├── docker-compose.yml
├── Dockerfile
├── entrypoint.sh
├── wsgi.py
├── app/
│   ├── __init__.py          # 工厂 + seed
│   ├── models.py
│   ├── services/rules.py
│   └── blueprints/{auth,board,ponds,batches}
├── templates/
│   └── board/floor.html     # 平面图 + 抽屉
└── static/
```
