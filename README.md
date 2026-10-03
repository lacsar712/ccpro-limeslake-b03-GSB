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

- **熟化池平面图**（`/board/`）：CSS 网格池位瓦片，按状态着色（注水中 / 熟化中 / 已出灰），冷却中的池位显示红色剩余分钟角标
- 顶部厂区切换芯片（多厂时切换）
- 点击瓦片 → 右侧抽屉展示最近 `SlakeBatch`，可登记峰值温度并变更池状态；冷却未满时「注水中」选项禁用，强提交通告中文错误
- **出灰冷却钟**（`/cooldowns/`）：顶栏入口（带冷却中池位数量角标），按厂区列出冷却中池位与剩余分钟，倒计时以服务器时刻对时；冷却满后按钮自动解禁、可一键改回注水中
- 主导航不再挂「熟化池列表 / 批次列表」；旧 `/ponds/`、`/batches/` 路由仍保留但不作为作业入口

## 业务规则

1. 熟化池状态不可设为「已出灰」（`drawn`），除非该池**最近一条** `SlakeBatch` 的 `peakTempC` 已记录且 **≥ 60℃**。
2. 池位进入「已出灰」即启动**冷却钟**，默认 **4 小时**（可用环境变量 `POND_COOLDOWN_HOURS` 调整）：
   - 冷却未满禁止改回「注水中」，抽屉与冷却钟专页提交都会被服务端拒绝并返回中文说明（含剩余分钟）；
   - 冷却未满禁止登记新班（`/batches/new`）；
   - 冷却不挡出灰：出灰峰值门槛照旧，冷却中的池仍可登记/修正峰值。
   - 冷却满后，抽屉与专页均放行；冷却起点 `Pond.drawn_at` 在出灰时写入、改回注水时清空。
3. 冷却刚满时两人同时抢改回注水中：改态事务对池位行加 `FOR UPDATE` 行锁并校验 `from_status`，**只许一笔成功**，后者收到「状态已被他人更新」提示。

规则实现：`app/services/rules.py`；冷却钟页：`app/blueprints/cooldowns.py`。

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
│   ├── __init__.py          # 工厂 + ensure_schema + seed
│   ├── models.py
│   ├── services/rules.py    # 出灰门槛 + 冷却钟规则
│   └── blueprints/{auth,board,ponds,batches,cooldowns}
├── templates/
│   ├── board/floor.html     # 平面图 + 抽屉
│   └── cooldowns/list.html  # 冷却钟专页
└── static/
```
