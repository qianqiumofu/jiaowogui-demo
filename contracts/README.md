# contracts

这里是两人的接口交接点。约定：

- `openapi.yaml` 是共享契约的唯一文本来源；改它要在同一次提交里同步实现与前端类型。
- `examples/` 按 `资源-状态.json` 命名，覆盖成功、空列表、权限不足、冲突、服务不可用五类。
- 接口负责人在文件头注释里标明；共享条目由 A/B 共同评审。

## 生成前端类型

方案尚未定稿，第一阶段前端用手写类型 `apps/web/src/api/types.ts`。选型时二选一并在
`docs/06-契约与接口同步.md` 记录：

1. `openapi-typescript` + `openapi-fetch`：只生成类型，请求封装保持现有 `client.ts`。
2. `openapi-generator-cli`：生成完整客户端。

确定后把生成命令、产物路径和提交约定写进本目录，并让 `npm run build` 之前先跑生成。

## 修改检查

```bash
cd "F:/A_homework/交我归/apps/api"
./.venv/Scripts/python.exe -c "import yaml,sys; yaml.safe_load(open('../contracts/openapi.yaml',encoding='utf-8')); print('openapi ok')"
```

若提示缺少 `pyyaml`，先安装进虚拟环境；不要在项目外解释器里装依赖。
