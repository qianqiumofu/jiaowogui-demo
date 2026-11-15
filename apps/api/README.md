# apps/api（FastAPI 底座）

运行时：Python 3.13.12。依赖精确锁定在 `requirements.lock.txt`，不要各自安装浮动版本。

## 启动

```bash
cd apps/api
py -3.13 -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt -r requirements.lock.txt
copy .env.example .env
.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000
```

`py -3.13` 是 Windows Python Launcher；在 Git Bash 或 CI 中改用 `python3.13`。

## 已可用能力

| 能力 | 端点 | 说明 |
| --- | --- | --- |
| 模拟统一登录 | `POST /api/v1/auth/mock-login` | 合成账号 `student/counselor/dorm/campus`，口令 `demo1234` |
| 会话上下文 | `GET /api/v1/me` | 返回 `user_id, school_id, active_role, scope, expires_at` |
| 多角色切换 | `POST /api/v1/auth/role-switch` | 轮换会话，旧令牌立即失效 |
| 退出 | `POST /api/v1/auth/logout` | 删除服务端会话 |
| 权限自省 | `GET /api/v1/authz/actions`、`GET /api/v1/authz/scope-check` | 供前端折叠入口，越权样本测试用 |
| 演示时钟 | `GET/POST /api/v1/demo/clock` | 平移业务时间，跨 23:30、00:00、06:00 |
| 健康检查 | `GET /healthz` | 报告业务时间与数据库状态 |

业务模块桩返回 501 `NOT_IMPLEMENTED`，列表桩返回 `{"items": [], "next_cursor": null}`，见 `app/modules/README.md`。

## 测试

```bash
.venv/Scripts/python -m pytest -q
```

数据库并发相关测试必须连真实 PostgreSQL，不用 SQLite 结果代替。

## 目录约定

- `app/core/` 配置、时钟、错误信封、数据库会话
- `app/api/router.py` 根路由，A 维护，B 只追加自己一行
- `app/modules/<module>/` 路由、服务、仓储、契约、适配器与测试放同一模块内
- `app/worker/` 唯一调度入口，`--once` 用于联调
- `alembic/` 迁移，单一迁移头，已应用版本不重写
