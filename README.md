# OpenKB-Eval S4 双盲标注与质量控制系统

独立研发目录：`D:\openkb-eval\liyue\s4`。系统已实现账号与对象权限、候选校验、分层抽样、固定双人、两阶段作业、原始κ、仲裁/重标、人工定稿、审计、持久任务及六文件交接。语源与旧版管线不在本工程范围内。

当前为本地工程交付，S3/S5仍未与其他人员对齐。合成演练只能产生 `DEMO_READY`；D4/D6/SEC专项统计和D7放大规则保留明确阻塞。详细范围见[规则对齐说明](docs/requirements-alignment.md)，实测证据见[验收记录](docs/acceptance.md)。

## 本机已启动的入口

- 容器同源入口：<http://localhost:8084>
- 开发工作台：<http://localhost:5174>，开发API：<http://127.0.0.1:8004/api/s4/v1/docs>
- 容器入口连接 `s4_dev`；自动化演练连接独立 `s4_e2e`，二者账号和数据互不共享。

没有通用默认账号或密码。首次使用容器入口，请在PowerShell中执行下方bootstrap，密码由终端隐藏输入。管理员只管理账号，随后创建独立运营和两位标注员；管理员不会自动取得业务读取权限。

```powershell
Set-Location D:\openkb-eval\liyue\s4
docker compose --env-file .env -f deploy/compose.yml exec api python -m openkb_s4.cli bootstrap --username admin --display-name 系统管理员 --person-id YOUR-ACTUAL-PERSON-ID
```

`person_id`应标识真实人员，同一人不能靠多个账号占据A/B席位。bootstrap只允许在没有账号时执行，不覆盖既有管理员。

## 开发启动

需要PowerShell 7、Docker Desktop（Linux containers）、Node.js 24及uv。运行产物、凭据、数据库及工具缓存均被Git忽略。

```powershell
Set-Location D:\openkb-eval\liyue\s4
.\scripts\dev.ps1 setup
.\scripts\dev.ps1 migrate
.\scripts\dev.ps1 bootstrap -Username admin -DisplayName 系统管理员 -PersonId YOUR-ACTUAL-PERSON-ID
```

再用三个终端分别启动：

```powershell
.\scripts\dev.ps1 api
.\scripts\dev.ps1 worker
.\scripts\dev.ps1 web
```

setup在没有`.env`时生成不同的随机数据库密码；已有配置保持原样。API和worker缺一不可，心跳缺失时readiness为503。数据库开发端口只绑定`127.0.0.1:55434`。

## 操作顺序

1. 管理员创建运营、两位不同实际人员的标注员，以及需要时的第三仲裁员、独立负责人、审计员。
2. 运营在“候选导入”提交本地契约JSON，等待持久任务完成。可先使用[12题合成材料](contracts/examples/demo-import.json)。导入者已经看过草案，会登记暴露，不能再担任这些材料的首次盲答人员。
3. 按dataset创建统计批次，选定固定A/B和随机种子。样本为`max(8,ceil(0.1N))`，按难度分层；N不足8会明确阻塞。
4. A/B分别在“我的任务”独立阅读原文、暂存并封存BLIND。此时看不到草案、另一方标签或κ。
5. 整个批次双方BLIND全部封存后，运营统一开放REVIEW。每人只看本人盲答、草案和授权原文，逐点/逐文档/逐可答性复核并封存。
6. 运营计算批次一致性。κ≥0.7仍须人工逐题确认最终内容；灰区须第三人裁决及独立负责人确认；κ<0.6保留旧轮，校准后从冻结总体重抽完整新轮。
7. 全部应完成子批次通过且人工定稿齐备后，创建交接快照。详情页展示全量N、抽检n、文件行数与摘要，下载时再次校验。未抽中单元完整传递，不生成虚假人工标签。

标注封存不可编辑；草稿有版本冲突检查；重试有幂等键；材料和跨D1/D7同源族登记暴露。更换人员不能把已经读过草案的人重新当作首次盲答人员。详细操作及异常处理见[运行手册](docs/operations.md)。

## 验证与部署

```powershell
.\scripts\dev.ps1 test
docker compose --env-file .env -f deploy/compose.yml up -d --build --wait
```

开发测试只使用专用`s4_test`数据库；浏览器演练准备与启动见运行手册。锁文件包括`backend/uv.lock`、带hash的生产`requirements.lock`和两份`package-lock.json`；基础镜像固定digest。

备份/隔离恢复、日志、CI、SBOM及已知待验收项分别见[运行手册](docs/operations.md)和[验收记录](docs/acceptance.md)。正式部署还需真实20题双人演练、专项规则确认、外部联调及目标环境恢复证据；本地自动化结果不能替代这些记录。
