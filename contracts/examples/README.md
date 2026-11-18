# 样例约定

每个样例文件名对应一个资源与状态，用于契约评审与前端占位。缺样例的接口视为契约未冻结。

| 文件 | 场景 | 负责人 |
| --- | --- | --- |
| `auth-session-success.json` | 模拟统一登录成功 | A |
| `auth-role-switch-success.json` | 一人多角色切换后的新会话 | A |
| `list-empty.json` | 任意列表接口的空结果形状 | 双方共用 |
| `error-forbidden-action.json` | 角色未被授予该动作 | A |
| `error-forbidden-duty-switch.json` | 辅导员调用代班切换被拒（duty:switch 仅宿管） | B |
| `error-scope-unresolved.json` | 负责关系或住宿归属缺失 | B 目录 / A 判定 |
| `error-out-of-scope.json` | 指定资源不在当前有效范围内（如代班未生效） | B |
| `buildings-tonight-success.json` | 24:00 汇总后含改期、撤销异动与门禁通行情况的当晚名单 | B |
| `directory-student-contact-success.json` | 当班阿姨按需取联系方式 | B |
| `directory-building-residents-success.json` | 现场补录选人的本楼栋名册（含性别，不含联系方式） | B |
| `statistics-campus-success.json` | 园区端按片区分组的人数/晚归夜数/返宿次数，预约分母为 null | B |
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
| `error-not-implemented.json` | 占位能力 | 双方共用 |
