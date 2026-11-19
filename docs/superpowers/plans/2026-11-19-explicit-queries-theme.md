# 晚归主动查询与深色控件修正 Implementation Plan

**Goal:** 各角色晚归页面初始不加载结果，点击查询后展示；修复学院与园区页面白块。
**Architecture:** 仅修改前端视图和共享基础控件样式，保留后端 require 与 scope。增加 idle 状态、筛选失效与请求序号，阻止旧结果回填。
**Tech Stack:** Vue 3 / TypeScript / CSS；无新接口、依赖或迁移。
**Spec:** 用户本轮确认；R15、R20 业务夜与通知规则保持后端执行。

## Global Constraints

- 不自动请求名单；日期、角色范围、楼栋、筛选变化后清空显示，点击查询才加载。
- 操作成功后的刷新仅延续用户主动查询；不增加轮询或通知。
- 原生控件使用项目深色主题，二维码专用白底保持。

### 实施与验证

- [x] ReportsView、RecordsView、TonightView、RiskView、QueryView 统一主动查询；学生名册也只先加载筛选选项。
- [x] 共享 button 背景、边框、disabled 与 color-scheme 修正，内置浏览器核实学院、园区实际渲染。
- [x] 文档说明无接口变更，前端构建、契约与真实 PostgreSQL 全量回归。

验证结果：内置浏览器已复现并修复学院风险页白底空白按钮；实测学院日报查询前/后与切周报清空、返宿记录初始待查询、园区全部条件主动查询与改学院清空、宿管今晚名单主动查询均符合预期。前端 build（含类型检查）通过；真实 PostgreSQL 全量 270 passed / 16 既有弃用警告；契约 62 路径 / 91 组件 / 62 样例自检通过；git diff --check 通过。无接口与迁移变更。截图保存在 docs/screenshots/2026-11-19-campus-explicit-query.jpg。
