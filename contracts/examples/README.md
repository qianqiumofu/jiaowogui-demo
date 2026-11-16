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
| `error-conflict-version.json` | 乐观锁版本过期（409） | A |
| `error-not-implemented.json` | 占位能力 | 双方共用 |
