# 交我归 高校宿舍晚归管理与受控报告助手

本包是 2026-11-21 冻结的合成数据 Demo，包含完整源码、接口契约、测试和可恢复数据库。功能保持提交前版本，整理仅涉及文档与提交材料。适合本机演示与代码审阅，不是学校生产系统。真实统一认证、人脸、门禁、邮件及大模型均未完成生产接入；报告助手默认关闭，不影响其他功能。

## 目录内容

| 路径 | 内容 |
| --- | --- |
| submission/ | 约100字作品简介（Word及可粘贴文本）、Word设计书、提交与文档整理记录 |
| apps/api/ | FastAPI后端、单一worker、PostgreSQL迁移及pytest测试 |
| apps/web/ | Vue 3、TypeScript前端与依赖锁文件 |
| contracts/ | OpenAPI契约、响应样例及契约自检脚本 |
| data/demo/ | 1000人合成数据库快照、SHA-256清单及恢复说明 |
| scripts/ | Windows启动、停止和首次恢复脚本 |
| docs/ | 操作规范、维护记录、模型接入和最近功能验收 |
| 业务规则基线.md | 业务规则唯一来源，区分确认规则与工程默认 |
| 技术路线.md、双人协作分工.md | 架构约定、事务设计与模块归属 |

## 首次环境布置

建议 Windows 10/11 64位，安装 Git for Windows、Python 3.13、Node.js 24.x（含npm）、Docker Desktop（Linux容器及WSL2）。首次安装Docker若提示需重启，重启后再打开。建议为本机演示预留8GB内存和5GB磁盘空间，这是准备建议，不是经过压测的最低配置。需要联网下载依赖和postgres:17镜像。

安装后新开PowerShell，验证 `git --version`、`py -3.13 --version`、`node -v`、`npm -v`、`docker compose version`。启动Docker Desktop并等引擎就绪。将ZIP完整解压到可写目录，在解压后的项目根目录打开PowerShell；下列命令均在该目录执行。无需复制原作者的绝对路径。

```powershell
py -3.13 -m venv apps/api/.venv
apps/api/.venv/Scripts/python.exe -m pip install -r apps/api/requirements.lock.txt
npm --prefix apps/web ci
docker compose up -d postgres
docker compose ps
```

等postgres显示healthy，再首次恢复数据库并启动：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/restore-campus-experience.ps1
powershell -ExecutionPolicy Bypass -File scripts/start-campus-experience.ps1
```

默认无需创建.env文件：脚本与Compose使用公开合成环境配置 `demo:demo`，数据库端口5432，体验库 `jwg_campus_experience`。若本机已有.env，请核对其不会覆盖这些设置。真实密钥不要写入源码。默认模型为DISABLED，首次体验不需要模型账号或API密钥。

恢复脚本验证快照SHA-256，新建体验库，恢复1000人数据，将0018迁移升级到唯一头0022，并补齐107栋目录及已知合成样本的培养层次；10栋具有住宿样本，其余目录楼栋无学生。已有同名库会退出，防止覆盖数据。恢复的服务端时钟锚在样本业务夜，随后继续流逝。

## 日常启动和停止

```powershell
docker compose up -d postgres
powershell -ExecutionPolicy Bypass -File scripts/start-campus-experience.ps1
# 演示结束后停止本项目API、网页及worker
powershell -ExecutionPolicy Bypass -File scripts/stop-campus-experience.ps1
```

网页 http://127.0.0.1:5174 ，API文档 http://127.0.0.1:8001/docs ，健康检查 http://127.0.0.1:8001/healthz 。启动脚本会检查就绪状态，同时运行唯一API、前端和worker。日志与PID在 `tmp/campus-*`。普通重启保留数据和时钟。不要重复恢复，不要传 `-ResetData`，不要另起5173/8000环境。ResetData会重建样本，不适合保留当前演示过程。

## 账号和建议体验路线

快照内合成体验口令为 `demo1234`，优先使用登录页快捷卡片。原作者本机曾重置的宿管口令不随源码打包；新恢复快照使用其自身的合成账号状态，已修改的本机账号继续使用自己的口令。

| 登录名 | 角色及建议操作 |
| --- | --- |
| student | 学生：创建当夜预约、改期、撤销恢复、核验与查看本人记录 |
| dorm_a1_day | 宿管：查询负责楼栋今晚名单、人工补录与返宿记录 |
| counselor | 辅导员：负责学生、日报周报、订阅与风险跟进 |
| ideology_2 | 思政教师：查看明确分配学生范围 |
| college_admin_2 | 学院负责人：学院统计和负责教师配置 |
| auth_admin | 校级：任免学院负责人及全校晚归统计 |
| campus | 园区：全校授权查询、聚合导出、宿管账号与楼栋值班安排 |

先用园区查看14夜统计与筛选，查看107栋目录及1000人合成样本；再看辅导员负责范围；最后走学生预约到宿管记录链路。列表通常需点击“查询”，调整筛选后需要重新查询。导出只含聚合数据，由worker生成，仅发起人可下载与删除。

学生预约目标位于业务夜次日00:00至05:30；先在设置页核对服务端演示时钟，再申请。业务夜D指D日06:00至D+1日06:00，首次申请在D日06:00至D+1日00:00开放。核验要求预约时间前后30分钟，二维码有效300秒且06:00夜间授权终止。核验与人脸检查为模拟。模拟门口终端位于 `/terminal`，按页面选择设备并使用合成凭据（详见docs/10），粘贴学生令牌核销；成功通行才形成正式返宿事实。不要用申请或领码数量当作已返宿人数。

报告助手仅向辅导员、思政和学院负责人开放。未配置时生成按钮禁用，这是预期行为。受控工具链和模拟模型测试已存在，真实模型连通性及生成质量尚待验收。后续接入见 `docs/22-报告助手接入.md`。

## 规则与能力边界

预约自动通过、允许多次改期；同一学生同一业务夜最多一条正式返宿记录。未确认返宿只能查询，不产生超时未返宿提醒，也不证明学生未归。风险推送仅给负责辅导员和当班宿管，园区可主动查询但不接收风险推送。原因文本不用于判断撒谎，模型无处分、开锁、授权或任意SQL工具。全部演示数据合成，不使用真实个人信息。系统未承诺真实设备、真实学校数据和真实邮件能力。

## 开发检查

测试会重建合成数据，只能在以_test结尾的独立PostgreSQL库执行，不得指向体验库。首次建立测试库，已存在则跳过createdb：

```powershell
docker exec jiaowogui-postgres createdb -U demo jwg_submission_test
$env:JWG_TEST_DATABASE_URL='postgresql+psycopg://demo:demo@localhost:5432/jwg_submission_test'
$env:DATABASE_URL=$env:JWG_TEST_DATABASE_URL
apps/api/.venv/Scripts/python.exe -m pytest apps/api/tests -q
npm --prefix apps/web run build
apps/api/.venv/Scripts/python.exe contracts/preview.py
node --test apps/web/tests/*.test.mjs
# 检查完成后清除本终端测试配置，避免误用
Remove-Item Env:JWG_TEST_DATABASE_URL,Env:DATABASE_URL
```

前三项等价于Windows环境的 `make check`。未配置数据库而跳过测试不算通过；SQLite不能验证并发与事务。迁移只追加，保持单一头。最近功能验收见 `docs/23-11-21融合与功能验收.md`，本次提交整理记录见 `submission/提交说明.md`。

## 常见问题

- Docker报连接失败：打开Docker Desktop，确认Linux引擎已就绪；5432占用时先确认现有PostgreSQL，不要修改生产数据库。
- 恢复提示库已存在：已有体验库直接启动；不要为了恢复而删除现有库。
- 8001或5174占用：先运行本项目停止脚本；若仍占用，核对占用者，勿直接结束无关进程。
- 页面名单空：点击查询并核对业务夜、楼栋范围和服务端演示时钟。06:00已切次夜，历史数据请到返宿记录按业务夜查。
- 导出一直等待或收件箱未更新：检查worker日志；它必须和API共用数据库及 `tmp/campus-experience-clock.json`。
- 账号登录失败：使用登录页其他合成账号；本机修改过的口令不会被启动脚本自动还原。
- PowerShell阻止脚本：按本文 `powershell -ExecutionPolicy Bypass -File ...` 命令运行，不需修改全局执行策略。
- 依赖安装失败：确认Python3.13和Node24、网络可用，并从锁文件安装，不要自行升级依赖。

## 提交方式

平台简介栏粘贴 `submission/作品简介.txt` 正文，约100字；设计书栏上传 `submission/交我归智能体设计书.docx`（Word）；其他附件栏上传本ZIP即可。截图允许设计书最多3个100MB以内文件、其他附件最多5个1GB以内文件，本次各提交1个。演示视频属可选项，本次不含视频。ZIP已排除.git、.env、密钥、依赖、构建产物、日志及历史交付包；安装时需要联网下载依赖。
