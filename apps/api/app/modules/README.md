# 模块清单与占位规则

空 `__init__.py` 表示该模块尚未开工。开工时只在自己的目录里加文件，
跨模块能力通过 `contracts/openapi.yaml` 与领域服务函数交接，不调用对方 HTTP 接口。

| 目录 | 负责人 | 当前状态 | 下一步 |
| --- | --- | --- | --- |
| identity | A | 已可用：模拟统一登录、会话轮换、多角色切换 | 真实 OIDC/CAS 替换 adapters/mock_accounts.py |
| authorization | A | 已可用：动作权限、数据范围、代班缓存。B 的目录关系落地前，辅导员/宿管/园区范围返回 403 `SCOPE_UNRESOLVED` | 接入 B 的目录负责关系 |
| reservation | A | 已可用：当夜唯一、自动通过、无限改期、取消恢复、版本冲突 409、只追加修订历史 | B 的返宿写入后调 `service.mark_fulfilled`；接 23:30 快照 |
| verification | A | 空 | M3 现场核验 ±30 分钟与签码原子协调 |
| risk | A | 已可用：版本化规则引擎 `rules.py` 与申请弹窗事实 `service.notice_for_create`（`/reservations` POST 的 `risk_notice`）；`/risk-events` 仍是占位 | 风险事件落库与跟进待 B 的负责/值班关系；周期风险提示邮件复用同一 `rules.evaluate` |
| reports | A | 占位 | M4 日报周报与订阅 |
| notification | A | 已可用：四类模板入队、投递与模拟收件箱，`NOTIFICATION_SEND` 处理器由 worker 消费；阈值口径改由 `risk.rules` 计算 | M4 接 23:30/08:30/周一 09:00 的周期入队与 outbox 消费 |
| directory | B | 空 | M1 目录适配、住宿、负责关系、迁移 |
| access | B | 占位 | M3 签码撤销核销、设备认证、回执对账 |
| returns | B | 占位 | M3 唯一返宿写入、补录、纠错 |
| building_list | B | 占位 | M2 当晚名单与 23:30 快照 |
| statistics | B | 空 | M4 全校统计口径 |
| exports | B | 空 | M4 受控导出 |
| duty | B | 占位 | M1 代班生效范围 |

占位接口返回 501 `NOT_IMPLEMENTED`，列表类返回 `{"items": [], "next_cursor": null}`，
以便前端在没有业务逻辑时也能渲染。
