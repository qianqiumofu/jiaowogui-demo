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
| directory | B | 已可用：学院/片区/楼栋目录、楼栋名册检索、住宿与联系方式读取 | 真实目录源接入后替换合成 seed |
| access | B | 已可用：设备身份核验、扫码核销并落正式返宿事实 | 通行码撤销/对账接口未开工，设备凭据下发方式待确认 |
| returns | B | 已可用：唯一返宿写入（扫码与补录同约束）、返宿记录查询 | 纠错流程仍按 Demo 口径 |
| building_list | B | 已实现读模型，等 A 的预约源 | M2 当晚名单与 24:00 快照 |
| statistics | B | 已可用：全校三值统计（人数/晚归夜数/返宿次数分列）、筛选器选项 | 预约与未确认两列待 A 的来源落地 |
| exports | B | 已可用：受控导出走 EXPORT_BUILD worker 处理器，CSV 落库、按保留期遗忘 | 保留期与导出字段待校方确认 |
| duty | B | 占位 | M1 代班生效范围 |

占位接口返回 501 `NOT_IMPLEMENTED`，列表类返回 `{"items": [], "next_cursor": null}`，
以便前端在没有业务逻辑时也能渲染。
