# 校级与学院职责边界 Implementation Plan

**Goal:** 校级只任免学院负责人，从全校教师选择人选，可查看全校晚归日报周报；学院配置思政、辅导员和班级学生范围。
**Architecture:** A 的授权管理服务校验校级可写角色，读记录过滤学院负责人；SessionContext.scope 通过目录领域服务解析全校学生；复用报告只读页面与接口。
**Tech Stack:** Vue 3 / FastAPI / PostgreSQL。
**Spec:** 用户 2026-11-19 新确认，替代基线旧校级默认。

## Global Constraints

- 只修改 A 主责文件；不改 B 目录、统计和返宿模块。
- 不新增通知、订阅或风险权限，不引入依赖或迁移。

### Task 1: 契约与权限

- [x] 更新基线、OpenAPI 和合成样例，登记校级只任免 COLLEGE_ADMIN 及 report:read。
- [x] 添加越权测试：校级不能授予或取消 COUNSELOR/IDEOLOGY/CAMPUS、不能混入 student_ids，职责列表仅学院负责人。
- [x] 校级 scope 通过目录服务解析全校学生，日报周报走 require(report:read) 与 scope，其他写操作保持拒绝。

### Task 2: 页面与验证

- [x] 校级职责页面仅学院负责人，全校教师搜索选择，不显示学院教师筛选和学生分配。
- [x] 校级导航改为查看学院负责人，增加查看晚归情况入口与日报周报路由。
- [x] 更新文档，真实 PostgreSQL 全量 pytest、前端 build、契约自检及 diff 自审。

验证：新增校级边界测试先确认旧实现返回 201（预期 403），实现后新增 5 项通过。最终真实 PostgreSQL 全量 255 passed（16 项既有弃用警告），前端类型检查及生产构建通过，契约 59 路径 / 88 组件 / 59 样例自检通过，git diff --check 通过。无表结构变更，不需迁移；无 make，已执行其三项等价检查。
