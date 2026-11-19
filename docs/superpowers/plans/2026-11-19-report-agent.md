# 报告助手接入版实施计划

**Goal:** 在未申请模型 API 的情况下完成辅导员报告助手入口和可接入的受控工具闭环，默认不发起外部请求。

**Architecture:** 单 FastAPI 内新增 A 主责 `agent` 模块，复用 B 的 statistics 领域服务；HTTP 模型适配使用已有 httpx，无新增依赖。无会话表迁移，必要执行依据写入现有 audit_logs；上下文仅限本次请求和最近用户问题，聚合统计不携带学生身份。

**Spec:** 业务规则基线 R13、R15—R17；详细路线图 M5.5；用户本轮确认“尚未申请，先搭好可接入的助手”。该确认允许启动接入版，不代表 M5 未完成的实机和整夜验收已完成。

## 文件与接口
- `contracts/openapi.yaml`、`contracts/examples/agent-*.json`：先约定 `GET /agent/status`、`POST /agent/reports`。
- `app/modules/agent/schemas.py`：请求、工具参数、聚合来源与响应；多余字段一律拒绝。
- `app/modules/agent/provider.py`：DISABLED / OPENAI_COMPATIBLE；默认关闭，凭据为空；固定配置地址调用 `/chat/completions`，超时、大小及轮次限额。
- `app/modules/agent/service.py`：模型选择 `read_period_statistics` 读取 DAY/WEEK/MONTH 的 CURRENT/PREVIOUS 窗口；再次调用 `finish_report` 引用已查来源，由服务端填充数字和对比，不接受模型自由编造报告数字。
- `app/modules/agent/router.py`、根路由与 `policies.ACTIONS`：`agent:use` 仅辅导员/思政/学院负责人，每次工具前重新校验会话与范围；范围变化终止旧结果。
- `apps/web/src/features/counselor/views/ReportAssistantView.vue`、导航/路由/客户端：模型状态、问题建议、请求、执行依据和数据卡片；未启用明确说明，普通查询入口可用。
- `tests/test_report_agent.py`：真实 PG 范围隔离、未授权角色、关闭不外呼、受控查询及对比、未知工具/注入、虚构来源拒绝、调用限额、失败审计和会话变更。
- `tests/test_agent_provider.py`：httpx MockTransport 验证兼容协议、超时和无敏感异常回显。

## 交付步骤
- [x] 契约、样例和 Demo 默认先行。
- [x] 实现模型适配与只读工具，服务端生成有依据的数字摘要，不让模型开锁/处分/通知。
- [x] 实现前端入口和禁用状态、仅保存在当前页的追问上下文，不自动提交。
- [x] 真实 PostgreSQL 全量、前端 build、契约自检通过；实际 5174 未配置状态与原有查询均验证。
- [x] 更新接入手册、路线图和真实验证边界；未经真实模型接口验收不声称已接入“致远一号”。

## 工程默认
输入 1000 字、最近 4 个用户问题（各 1000 字）；4 次模型调用、总共 6 个工具调用、单次 20 秒且总流程 60 秒、响应上限 1 MiB、输出 token 1000。均放配置并登记基线，正式频控和学校部署约束另行核定。

周期与学校现有查询一致：当前 DAY 为前一已结束业务夜；当前 WEEK/MONTH 为该夜所在自然周/月的开头至该夜；PREVIOUS 为前一日/完整自然周/完整自然月。对比明确列出两区间与天数，不同长度不称同长增长率；不推断撒谎、未归或个人风险。

## 验证记录

- `make check` 三项分别执行通过：隔离真实 PostgreSQL 后端全量 368 项通过（25 项既有/测试校验弃用警告）；前端 build 含契约类型生成与类型检查通过；契约自检 68 路径、99 组件、71 样例通过。
- 全量收集后追加的“过期执行预算不创建客户端”用例与专项一起复核，报告助手/适配器专项 32 项通过。模拟模型覆盖真实统计来源、同周期对比、授权角色与范围、额外范围参数、未知工具、虚构来源、自由编造正文拒绝、调用限额、超时、会话撤销和执行中范围变化。
- 真实 5174 API 验证：辅导员状态 DISABLED、生成返回 503 AGENT_UNAVAILABLE、原有统计返回 200。内置浏览器使用辅导员实际验证导航、未启用提示、建议问题填充与生成按钮禁用。没有切换为真实模型，没有外部调用。
- 无新增依赖、无结构迁移，审计复用现有表；请求样例通过 Pydantic 校验，`git diff --check` 通过。未修改 B 的统计/返宿/目录模块。
- 真实 API 兼容性、模型理解质量、模型配额/正式频控和完整真实模型演示均未验收；这些仍属于 M5.5 后续工作，不因本接入版完成而勾选。
