# 职责管理交互 Implementation Plan

**Goal:** 现有记录默认收起，可按状态、职责身份及学院筛选排序；明确取消负责入口；学院范围可搜索下拉多选。
**Architecture:** 仅修改 A 的职责管理视图，复用已有 grants / revokeGrant 接口及后端授权审计。无新动作、依赖、表结构或迁移。
**Tech Stack:** Vue 3、TypeScript、FastAPI、PostgreSQL。
**Spec:** 业务规则基线.md R01、R21 与学院授权确认；本次用户反馈。

## Global Constraints

- 负责关系与会话失效由现有后端服务执行。
- 不修改 B 主责目录或返宿模块。
- 学院筛选明确区分教师所属学院与职责管理学院。

### Task 1: 契约与交互

- [x] 核对 DELETE /management/grants/{grant_id} 的职责和负责关系取消语义，补契约说明与合成样例。
- [x] PermissionsView.vue 使用 details 默认收起记录；提供状态、职责、教师所属学院、管理范围学院筛选和稳定排序。
- [x] 学院管理范围使用可搜索的折叠多选，已选学院可逐个移除；取消负责提供独立确认并显示影响。
- [x] 编辑记录显式 hydrate，避免同一教师职责重复点击无法恢复；失效记录仅允许重新配置。
- [x] 更新业务基线 Demo 交互默认与操作文档。

### Task 2: 验证

- [x] 运行 npm --prefix apps/web run build。
- [x] 使用真实隔离 PostgreSQL 执行全部 pytest 与 contracts/preview.py（make check 等价命令）。
- [x] 审查 git diff，确保没有生成物或无关改动。

验证结果：前端类型检查与生产构建通过；真实 PostgreSQL 全量 pytest 250 passed（16 项既有弃用警告）；契约 59 路径 / 88 组件 / 56 样例自检通过；git diff --check 通过。Windows 无 make，已执行 Makefile check 的三项等价命令。无表结构变化，不需迁移。
