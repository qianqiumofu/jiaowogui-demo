# 校级晚归日周月统计 Implementation Plan

**Goal:** 日统计昨日正式晚归与今日非取消预约；周月统计正式晚归与多次晚归，名单仅主动查询加载。
**Architecture:** A reports 新增只读统计接口和校级独立页面，复用 B returns/directory 领域出口，summary 与名单分离；保留原辅导员报告与投递链路。
**Tech Stack:** Vue 3、TypeScript、FastAPI、PostgreSQL；不增加依赖或迁移。
**Spec:** 用户本轮请求；基线 R10、R15、R21 与校级只读确认。

## Global Constraints

- 晚归只认正式返宿事实，二维码未使用、预约和 FULFILLED 状态本身均不能替代事实。
- 时间区间服务端 app.core.clock 判定。昨日=前一业务夜，今日=当前业务夜；周/月=昨日所在自然周/月起点至昨日。
- 多次默认至少 2 夜，阈值配置化；学院年级取目录现值，住宿按发生夜快照。
- 名单仅查询接口返回；切换筛选/周期清空名单，不自动查询。

### Task 1: 契约与领域接口

- [x] OpenAPI 新增 /reports/overview、/reports/overview/options、/reports/overview/students 与合成样例。
- [x] 注册 report:statistics（仅校级），真实 PG 测试越权、日期边界、正式事实、筛选与分页。
- [x] reports/school_statistics.py 调用目录/返宿服务取数，summary 不含身份，名单按 scope 过滤聚合分页。

### Task 2: 页面

- [x] SchoolStatisticsView.vue 日周月仅加载数字，日两部分、周月多次晚归专栏。
- [x] StatisticsStudentList.vue 折叠名单，学院/年级/宿舍区/楼栋筛选，主动查询与分页；阻止旧请求回填。
- [x] 校级路由与导航接新页面，原教师日报周报不变。

### Task 3: 验证

- [x] 更新规则默认与操作文档，真实 PG 全量 pytest、前端 build、契约自检及 diff 自审。

验证记录：新增统计测试先确认接口 404；实现后新增 15 项通过。真实 PostgreSQL 全量 270 passed（16 项既有弃用警告），前端类型检查和生产构建通过；契约自检 62 路径 / 91 组件 / 62 样例通过；git diff --check 通过。无新表结构、迁移或依赖。Windows 无 make，已执行 Makefile check 的全部三项等价命令。
