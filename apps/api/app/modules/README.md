# 模块清单与占位规则

空 `__init__.py` 表示该模块尚未开工。开工时只在自己的目录里加文件，
跨模块能力通过 `contracts/openapi.yaml` 与领域服务函数交接，不调用对方 HTTP 接口。

| 目录 | 负责人 | 当前状态 | 下一步 |
| --- | --- | --- | --- |
| identity | A | 已可用：模拟统一登录、会话轮换、多角色切换 | 真实 OIDC/CAS 替换 adapters/mock_accounts.py |
| authorization | A | 已可用：动作权限、数据范围、代班缓存 | 接入 B 的目录负责关系 |
| reservation | A | 占位 | M2 预约唯一性、无限改期、修订历史 |
| verification | A | 空 | M3 现场核验 ±30 分钟与签码原子协调 |
| risk | A | 占位 | M4 规则引擎、弹窗、周期邮件、跟进 |
| reports | A | 占位 | M4 日报周报与订阅 |
| notification | A | 空 | M4 worker/outbox/模拟收件箱 |
| directory | B | 空 | M1 目录适配、住宿、负责关系、迁移 |
| access | B | 占位 | M3 签码撤销核销、设备认证、回执对账 |
| returns | B | 占位 | M3 唯一返宿写入、补录、纠错 |
| building_list | B | 占位 | M2 当晚名单与 23:30 快照 |
| statistics | B | 空 | M4 全校统计口径 |
| exports | B | 空 | M4 受控导出 |
| duty | B | 占位 | M1 代班生效范围 |

占位接口返回 501 `NOT_IMPLEMENTED`，列表类返回 `{"items": [], "next_cursor": null}`，
以便前端在没有业务逻辑时也能渲染。
