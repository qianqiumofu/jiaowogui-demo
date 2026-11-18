# 样例约定

每个样例文件名对应一个资源与状态，用于契约评审与前端占位。缺样例的接口视为契约未冻结。

| 文件 | 场景 | 负责人 |
| --- | --- | --- |
| `auth-session-success.json` | 模拟统一登录成功 | A |
| `auth-session-staff-success.json` | 园区分发的宿管工号账号登录成功（`STAFF_LOCAL`，无邮箱） | A |
| `auth-role-switch-success.json` | 一人多角色切换后的新会话 | A |
| `staff-account-create-success.json` | 园区注册工号账号并绑定固定楼栋，含一次性初始口令 | A |
| `staff-account-list-success.json` | 工号账号列表（含一个已停用） | A |
| `list-empty.json` | 任意列表接口的空结果形状 | 双方共用 |
| `reservation-active-success.json` | 当日晚归预约创建并自动通过后改期一次 | A |
| `reservation-create-risk-notice.json` | 预约创建响应带申请弹窗事实（首次跨过演示阈值，R16） | A |
| `reservation-revisions-success.json` | 同一预约的只追加修订历史（CREATE + RESCHEDULE） | A |
| `reservation-tonight-null.json` | 当夜无预约时 `/reservations/tonight` 返回 null | A |
| `demo-clock-state-success.json` | 演示时钟：服务端判定的业务时间与业务夜 | A |
| `report-daily-success.json` | 辅导员按需读取的前一晚日报事实（与 08:30 邮件同口径，A 的 `reports.readmodel` 直接渲染） | A |
| `report-weekly-success.json` | 周报区间：逐夜七行含空夜，取消不计 | A |
| `notification-inbox-success.json` | 辅导员模拟收件箱：统一身份账户只有邮件预览条目 | A |
| `notification-inbox-staff-success.json` | 宿管模拟收件箱：工号账号只有站内待办条目 | A |
| `notification-dispatch-success.json` | 园区演示投递 23:30 名单后的任务回执 | A |
| `notification-jobs-success.json` | 通知后台任务列表：含已完成与租约重试中各一条 | A |
| `error-forbidden-action.json` | 角色未被授予该动作 | A |
| `error-notification-recipient-forbidden.json` | 风险预警投向园区被拒（R16，403） | A |
| `error-notification-template-mismatch.json` | 模板与收件人角色不匹配（422） | A |
| `error-forbidden-staff-account.json` | 宿管调用账号管理接口被拒（`staff_account:*` 仅园区） | A |
| `error-account-disabled.json` | 已停用工号账号登录被拒（403） | A |
| `error-forbidden-duty-switch.json` | 辅导员调用代班切换被拒（duty:switch 仅宿管） | B |
| `error-scope-unresolved.json` | 负责关系或住宿归属缺失 | B 目录 / A 判定 |
| `error-conflict-version.json` | 乐观锁版本过期（409） | A |
| `error-reservation-cancelled.json` | 当夜已取消预约，新建被拒需走恢复（409） | A |
| `error-not-implemented.json` | 占位能力 | 双方共用 |
