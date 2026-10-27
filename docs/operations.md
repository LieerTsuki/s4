# 启动、权限及运维手册

## 服务与配置

开发：PowerShell 7运行`./scripts/dev.ps1 setup`、`migrate`、`api`、`worker`、`web`。API8004、Web5174。容器：`docker compose --env-file .env -f deploy/compose.yml up -d --build --wait`，同源入口8084。首次管理员创建见README；不存在预置账号或注册接口。

容器迁移使用owner，API/worker使用`s4_app`。应用账号没有审计、封存结果、统计、最终决策、原输入和暴露表的UPDATE/DELETE/TRUNCATE权限。禁止用owner代替运行账号；独立测试和恢复演练允许使用专用数据库owner。

迁移版本目前为`0002_s4`。开发数据库执行`./scripts/dev.ps1 migrate`；容器由migrate服务在API/worker启动前执行Alembic。回滚前先备份，不能通过删除表清除封存历史。

主要设置见`.env.example`：数据库URL、受控data_dir、Cookie Secure、会话时长、允许Origin、导入大小及回执token。`.env`不提交；首次setup自动生成随机数据库密码，现存数据库不会因修改.env自动改密码。

本地HTTP演示使用`S4_COOKIE_SECURE=false`。目标环境通过TLS入口部署后改为true，明确配置`S4_PUBLIC_ORIGIN=https://实际域名`；API保持同源，数据库不公开。Nginx只监听本机8084，外部TLS/身份目录接入不在本次未对齐接口内。

## 角色与常见冲突

| 角色 | 主要能力 |
|---|---|
| admin | 建立/停用账号、配置角色；默认无题目和业务结果读取权 |
| lead | 导入、批次配置、统一开放复核、统计、人工定稿和交接 |
| annotator | 本人分配的BLIND/REVIEW，不能读取另一席位 |
| arbitrator | 第三人仲裁；不能裁决本人参标题 |
| auditor | 审计及获准业务记录读取；敏感读取登记暴露 |

角色不是对象权限豁免。运营本人参加批次时权限收缩；导入材料、获准查看完整批次或下载快照均留下暴露。同源D1/D7关系也参与检查。新人员必须与两席位及历史暴露条件相容。

- 409 `DRAFT_VERSION_CONFLICT`：另一窗口已更新，先复制未保存内容，点手动刷新载入最新草稿后重新修改。
- 本人已封存但仍BLIND：整批尚未完成或运营尚未释放，不能单题提前看草案。
- κ未定义/专项未确认：显示阻塞，不按1处理；先解决配对、统计范围或规则问题。
- 灰区：第三人按题提交裁决，独立负责人确认；最终定稿必须保持已确认裁决，仍保留原κ。
- 低κ/换人：写明原因、选新固定人员对及seed，创建完整新轮。旧轮SUPERSEDED保留，不允许出口。
- 摘要/manifest不匹配：拒绝下载或接受，不手工改清单“修复”；对账原始冻结版本。
- 任务FAILED：详情查看安全错误码；排除原因后重新提交原导入、统计或交接请求，业务键命中原任务并显式重试，不修改封存记录。输入本身错误时应修正输入并作为新请求提交。

## 健康、持久任务和日志

`GET /api/s4/v1/health/live`只确认进程存活；`health/ready`检查DB、Alembic版本及90秒内worker心跳。缺任何一项返回503。外部NOT_ALIGNED不是服务宕机。

worker从PostgreSQL竞争领取任务，`SKIP LOCKED`、2分钟租约、最多3次自动尝试；过期租约有上限，失败可显式重试。导出先写`.partial`、fsync数据、核对摘要/集合/数量，再发布；重启可从冻结输入对账，不能只依赖Web进程内任务。

查看容器日志：`docker compose --env-file .env -f deploy/compose.yml logs --tail 100 api worker`。错误响应携带request_id和安全错误码；普通日志不输出题目、密码、Cookie、token或异常中的敏感内容。审计通过auditor账号查看，封存表和审计表由数据库权限保护追加。

## 自动化验证

`./scripts/dev.ps1 test`运行真实PostgreSQL后端测试、≥80%覆盖率、Ruff、严格mypy及前端测试/构建/lint。只对专用`s4_test`执行清理，不能把生产连接放入`S4_TEST_DATABASE_URL`。

独立浏览器演练（全部合成、非真人）：

```powershell
.\.venv\Scripts\python.exe tests\e2e\prepare.py
# 三个独立终端；它们只读取忽略的.env.e2e
.\scripts\e2e-services.ps1 api
.\scripts\e2e-services.ps1 worker
.\scripts\e2e-services.ps1 web
# 另一个终端
npm.cmd ci --prefix tests/e2e
npm.cmd test --prefix tests/e2e
```

Windows默认使用已安装Edge；其他环境设置`S4_E2E_BROWSER=chromium`并在`tests/e2e`运行`npx playwright install --with-deps chromium`。演练会创建独立`s4_e2e`和随机账号，凭据仅保存在忽略文件；不会删除开发数据。若8004/5174已被开发进程占用，先在对应终端停止，再启动演练进程。

证据写到`var/evidence`：JSON报告、浏览器截图、全量/抽检核对。CI定义在`.github/workflows/verify.yml`，使用临时随机密码和专用PostgreSQL；远端CI尚未运行时不能宣称其已通过。

契约元Schema及真实导出逐行验证：

```powershell
uv run --no-project --with jsonschema python scripts/check_contracts.py --exports var/e2e/exports
```

`scripts/dependency_audit.py`导出Python与npm锁文件许可元数据；后端生产SBOM用`uv export --format cyclonedx1.5 --no-dev --no-emit-project`生成，前端在frontend目录用`npm sbom --sbom-format cyclonedx`生成完整构建依赖清单（包含开发依赖）。本次npm的`--omit dev`结果遗漏被测试工具共享的React等生产组件，故交付完整清单并核对全部直接生产依赖均在其中。元数据审计不替代法律许可意见或二进制镜像漏洞审计。

## 备份与隔离恢复

先进入维护窗口，停止写入端API/worker，保证数据库dump、行数和文件属于同一稳定状态；备份同时包含PostgreSQL custom dump及不可变exports。`.env`和数据库角色密码由运维另行受控备份，不打入工程包。

本机开发文件：

```powershell
.\.venv\Scripts\python.exe scripts\backup_restore.py backup --output backups\YOUR-BACKUP-ID
```

Compose文件卷：

```powershell
.\.venv\Scripts\python.exe scripts\backup_restore.py backup --api-container openkb-s4-api-1 --output backups\YOUR-BACKUP-ID
```

若API容器已停止而不能复制，可在关闭写入前先完成文件卷复制，并保证维护窗口期间没有发布新快照；`docker cp`支持停止的容器。数据库容器保持运行以执行pg_dump。示例默认访问本机数据库端口；只有使用compose.dev.yml时该端口开放，生产备份需在受控运维主机提供正确owner连接。

隔离恢复：

```powershell
.\.venv\Scripts\python.exe scripts\backup_restore.py restore --backup backups\YOUR-BACKUP-ID
```

脚本先校验备份SHA256，然后创建随机新`s4_restore_*`数据库和`var/s4_restore_*`文件目录，从不drop或覆盖现有数据库/目录。核对全部业务表行数、每个快照文件摘要/manifest/全量抽检集合，写`restore-verification.json`。保留恢复环境供人工复查；不自动切换线上API连接。目标PG实例须提前具备原有`s4_owner/s4_app`角色；密码不存储在dump包中。

本次合成恢复证据见`docs/acceptance.md`。生产目标的RPO/RTO、加密异地备份、切换权限及真实恢复仍需部署负责人确认并演练。
