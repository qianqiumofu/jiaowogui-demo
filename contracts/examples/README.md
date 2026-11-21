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
| `error-forbidden-duty-switch.json` | 辅导员调用代班切换被拒（duty:switch 仅园区） | B |
| `duty-roster-list-success.json` | 园区端楼栋固定值班名册：同一栋并排夜班与白班两位，`on_duty_now` 只有夜班那位为真 | B |
| `duty-roster-request.json` | 给某栋登记/更换固定值班负责人（缺省生效日即当前业务夜，窗口是每晚重复的时刻） | B |
| `duty-roster-set-success.json` | 写入后回读的那一行固定班 | B |
| `duty-roster-revoke-success.json` | 卸任某栋某位固定负责人，返回被卸掉的那一行 | B |
| `error-duty-roster-not-found.json` | 卸任时该楼栋没有这位固定负责人（404，必须指到人） | B |
| `error-scope-unresolved.json` | 负责关系或住宿归属缺失 | B 目录 / A 判定 |
| `error-out-of-scope.json` | 指定资源不在当前有效范围内（如代班未生效） | B |
| `buildings-tonight-success.json` | 24:00 汇总后含改期、撤销异动与门禁通行情况的当晚名单 | B |
| `directory-student-contact-success.json` | 当班阿姨按需取联系方式 | B |
| `directory-building-residents-success.json` | 现场补录选人的本楼栋名册（含性别，不含联系方式） | B |
| `statistics-campus-success.json` | 园区端按片区分组的人数/晚归夜数/返宿次数，预约分母已接通，样例区间无预约时为 0 | B |
| `statistics-campus-empty.json` | 园区端筛选到无楼栋的片区时的空结果形状 | B |
| `statistics-filters-success.json` | 园区统计筛选器选项（学院/片区/楼栋/年级/性别/来源） | B |
| `return-records-success.json` | 当夜二维码使用情况：已核销/已过期/已作废加一条无码人工补录 | B |
| `return-records-manual-success.json` | 宿管现场补录后的正式返宿记录 | B |
| `exports-created-success.json` | 园区发起受控导出：只登记任务，状态 PENDING | B |
| `exports-done-success.json` | worker 渲染完成，带文件名、数据行数与保留期 | B |
| `exports-list-success.json` | 本人导出列表：新的在前，一条 PENDING 一条 DONE | B |
| `exports-download-sample.csv` | 导出 CSV 的实际形状：口径说明 + 分组三值 + 合计行 | B |
| `error-export-not-ready.json` | 任务仍在生成时下载（409） | B |
| `error-export-expired.json` | 超过保留期，内容已清空（410） | B |
| `device-scan-success.json` | 终端扫码核销成功，同时产生正式返宿记录 | B |
| `error-pass-expired.json` | 二维码超过 300 秒有效期（410） | B |
| `error-return-exists.json` | 当夜已有返宿事实，扫码不再放行（409） | B |
| `error-conflict-version.json` | 乐观锁版本过期（409） | A |
| `error-reservation-cancelled.json` | 当夜已取消预约，新建被拒需走恢复（409） | A |
| `error-not-implemented.json` | 占位能力 | 双方共用 |

| `error-reservation-creation-closed.json` | 业务夜 24:00 首次申请截止（409），既有预约仍可改期撤销 | A |


## 完整 Demo 新增样例

教师基础身份与职责、学生筛选名册、分层授权、报告订阅、风险版本及跟进历史、代班指派、只追加更正，以及学院越权错误样例均为合成数据。
