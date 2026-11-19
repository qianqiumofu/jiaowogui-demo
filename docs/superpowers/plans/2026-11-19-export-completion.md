# 受控导出修复路线

**目标：** 完成统计查询到后台生成、刷新、下载、重新导出的闭环，保持 R11、R14、R15 与既有字段权限。

**架构：** 单应用内复用 statistics 领域服务，EXPORT_BUILD 继续由既有 worker 消费。仅修复导出所属模块与园区页面；不改其他模块的授权规则。

## 实施与验收
- [x] 先同步 `contracts/openapi.yaml` 的幂等键约定和 `contracts/examples/exports-download-sample.csv` 的真实数据说明。
- [x] 为 `apps/api/tests/test_exports.py` 补充范围快照、培养层次、重新生成和幂等冲突的回归；先在隔离真实 PostgreSQL 上复现。
- [x] 修复尚未应用的 `0020_export_scope_snapshot.py` PostgreSQL 类型导入；保留唯一迁移头与既有迁移历史。
- [x] 修复 `apps/api/app/modules/exports/service.py` 的参数校验、幂等冲突、报表范围文案与过时数据缺口说明；只输出六项既有聚合指标。
- [x] 修复 `apps/web/src/features/campus/views/QueryView.vue` 的重新生成、轮询重启、刷新入口与过期状态；以已查询结果为导出参数来源。
- [x] 真实 PostgreSQL 导出回归、全量后端测试、前端构建、契约自检、迁移单头与差异检查；文档记录结果后交付。

本次不添加依赖，不提交仓库中其他功能的在途修改。基础统计页面数字与 CSV 一致、越权被拒、未完成 409、到期 410、模型关闭无影响。

## 验证记录（2026-11-19）

- `make check` 对应三项分别执行：隔离真实 PostgreSQL 全量后端 325 项通过；`npm --prefix apps/web run build` 通过；`contracts/preview.py` 自检通过（66 路径、95 组件、67 样例）。
- 全量收集后补充的范围变更回归与导出专项一起执行，20 项全部通过；现有统计趋势 Node 测试 4 项通过。未跳过、注释或放宽测试；旧迁移头断言改为 0020 并增加 jsonb 列检查，旧辅导员 403 断言改为负责范围 50 人、全校 1000 人的精确隔离断言，授权实现未改变。
- Alembic 唯一头 `0020`，空库与旧库升级/回退回归通过。千人体验库迁移前保存 `tmp/jwg-before-export-0020.dump`（已忽略），随后从 0019 增量升级 0020，未重置数据。
- 体验 worker 原进程已退出，恢复现有 worker 并更新本地进程记录。真实体验 API 验证创建 PENDING、后台生成 DONE、CSV 下载 HTTP 200（9 行）；入口 `http://127.0.0.1:5174`。
- `git diff --check` 通过；本次没有新增依赖。页面通过类型检查和构建，未额外声明完成手机或平板实机验收。
