# 随代码交付的千人合成数据库

`campus-1000.pgcustom` 是 PostgreSQL 17 的完整结构与数据快照，约 827 KiB，可以直接还原，不依赖重新生成。`campus-1000.manifest.json` 记录 SHA-256、迁移头、行数及服务端演示时钟。已实际还原至独立 PostgreSQL 测试库并验证 1000 学生与唯一学号。

全部为合成体验数据，包括 5 学院、40 班、10 楼栋、负责关系、宿管值班、预约修订、通行码及回执、正式返宿证据、风险跟进和模拟收件箱。保留模拟工号口令；不含 `.env`、真实凭据或真实个人数据，**已排除登录会话数据**。明文演示口令 `demo1234` 仅供此合成环境使用。

## 同学首次体验（Windows PowerShell）

先安装 Python 3.13、Node.js、Docker Desktop 和 Git；打开 Docker Desktop。克隆仓库并切到本次交付分支后，在仓库根目录执行：

```powershell
py -3.13 -m venv apps/api/.venv
apps/api/.venv/Scripts/python.exe -m pip install -r apps/api/requirements.lock.txt
npm --prefix apps/web ci
docker compose up -d postgres
# 等 PostgreSQL 显示 healthy 后继续：
docker compose ps
./scripts/restore-campus-experience.ps1
./scripts/start-campus-experience.ps1
```

打开 [千人体验入口](http://127.0.0.1:5174)。建议先体验 `auth_admin`、`college_admin_2`、`campus`，然后换 `counselor_2_1`、`dorm` 和 `student`；全部口令 `demo1234`。

恢复脚本要求本地尚不存在 `jwg_campus_experience` 库。已有库时会退出，不清空已有修改；以后启动直接运行 `start-campus-experience.ps1`。不要对恢复后的库传 `-ResetData`，该选项会放弃快照中的运行状态，重新生成初始千人样本。数据库快照内迁移头为 `0018`；启动脚本会执行后续新增迁移。

快照时钟锚在 manifest 的 `server_clock.now`，恢复后继续流逝。因此即使几天后下载，也能从样本对应的业务夜继续体验。API 与 worker 共用本地生成的时钟文件；不必提交本地 `.env` 或时钟运行文件。

完整角色范围与操作路径见 [千人校园体验指南](../../docs/19-千人校园体验.md)。原 66 人小种子仍供自动化回归使用。

## 同学修改代码

前端启动为 Vite 开发模式，修改页面立即更新；后端启动为 Uvicorn 自动重载模式，修改 `apps/api/app` 后自动生效。当前后台进程号与日志位于 `tmp/campus-experience-processes.json`、`tmp/campus-*.log`。请按项目 `AGENTS.md` 使用个人分支提交，不提交虚拟环境、依赖目录、`.env` 或生成产物。

## 非 Windows

使用同一快照，通过 `docker cp` 将文件送入容器，并用 `createdb` 新建体验库、`pg_restore --no-owner --no-privileges --exit-on-error` 恢复。后端 `DATABASE_URL` 指向该库，API 使用 8001，前端设置 `JWG_API_TARGET=http://127.0.0.1:8001` 并使用 5174，worker 与 API 指向同一时钟文件。Python 安装入口按平台使用 `python3.13`；PowerShell 脚本无需在其他平台直接运行。
