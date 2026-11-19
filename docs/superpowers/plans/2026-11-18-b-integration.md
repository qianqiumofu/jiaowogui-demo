# B 交付整合 Implementation Plan

**Goal:** 消除当前合并冲突，补齐已交付模块接缝，验收并登记原规划缺口。
**Architecture:** 单 FastAPI、单 PostgreSQL、单 Vue 工程；领域服务跨模块协作，B 的模型作为共同表结构。
**Tech Stack:** Python 3.13 / FastAPI / SQLAlchemy / PostgreSQL 17 / Vue 3。
**Spec:** 业务规则基线.md、双人协作分工.md、docs/15-B侧交付整合交接.md。

## Global Constraints
- R15 禁止超时/未确认返宿提醒；风险只投负责辅导员及当班宿管。
- 已应用迁移不重写；真实 PostgreSQL 才算数据库验收。
- 不修改独立未开发功能的状态来冒充完成，不跳过或放宽失败测试。

### Task 1: 合并契约、类型、文档和迁移历史
- [x] 保留 ReservationList、双方新增路径及错误码，R18 身份/R19 账号保留、通行展示登记 R20。
- [x] 公共 UI 保留 A 登录恢复修复、补入 B 业务类型并由契约生成。
- [x] 恢复 HEAD 的三个历史迁移原文，B 迁移以独立编号后接，吸收账号迁移追加末尾。
- [x] 运行 alembic heads、契约检查及前端 build。

### Task 2: 预约/名单/通知接缝
Files: reservation/service.py, building_list/source.py, notification/service.py, tests/test_integration.py。
- [x] 添加 list_for_building(building_id, service_date)，只返回同夜且包含取消，字段用业务时区。
- [x] 首次申请按 summary_moment 截止；改期与撤销保留。
- [x] 通过 A 通知服务适配 B 的消息负载、去重键、当班收件人和工号站内渠道。
- [x] 测试零点前/上/后、异动推送幂等、非收件人不可见。

### Task 3: 返宿事务与统计
Files: access/service.py, returns/service.py, reservation/service.py, reports/readmodel.py, statistics/service.py。
- [x] 共享学生业务夜锁；改期/取消同事务撤码，返宿同事务履行预约。
- [x] 门禁再次检查状态/时间/预约版本；同夜补录与扫码竞争不重复放行。
- [x] 统计预约分母经 reports.readmodel 获取，保持取消不计、未确认仅查询。
- [x] 真实 PG 测试并发、回滚及统计/导出一致。

### Task 4: 验收与原规划盘点
- [x] PostgreSQL 新建库和 A 旧迁移升级路径验证；测试显式准备种子，配置了库时失败必须报错。
- [x] 跑 make check 或等价命令，检查所有冲突标记与 Git 未解决索引。
- [x] 更新交接，逐项列出 M0—M5 已有/部分/未实现及代码证据；不提交压缩包和运行态文件。

执行说明：本轮不创建合并提交，保留双方按 docs/04 评审；缺失独立功能登记在 docs/16。Windows 未安装 make，运行了其三项等价检查。
