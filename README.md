# OpenKB-Eval S4 双盲标注与质量控制系统

独立研发目录：`D:\openkb-eval\liyue\s4`。系统已实现账号与对象权限、候选校验、分层抽样、固定双人、两阶段作业、原始κ、仲裁/重标、人工定稿、审计、持久任务及六文件交接。语源与旧版管线不在本工程范围内。

当前源码与本机工作台已升级到0003及REVIEW v2。S3/S5仍未与其他人员对齐；合成演练发布为`DEMO_READY`，登记实际演示交付证据后可为`HANDOFF_SENT`，不产生正式S5接收。D4/D6/SEC专项统计和D7放大规则保留明确阻塞。详细范围见[规则对齐说明](docs/requirements-alignment.md)，实测证据见[本轮补齐验收](docs/audits/2026-10-28-S4补齐验收.md)。

## 本机已启动的入口

- 容器同源入口：<http://localhost:8084>
- 可选开发模式使用5174/8004，按下文单独启动；默认使用8084容器入口。
- 容器入口连接 `s4_dev`；自动化演练连接独立 `s4_e2e`，二者账号和数据互不共享，演练辅助进程在验证后关闭。

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

Windows开发与Compose使用不同文件目录。切换到Windows开发前先停止本项目Compose的api/worker/gateway，保留db；两种模式不要同时领取同库导出任务。

```powershell
.\scripts\dev.ps1 api
.\scripts\dev.ps1 worker
.\scripts\dev.ps1 web
```

setup在没有`.env`时生成不同的随机数据库密码；已有配置保持原样。API和worker缺一不可，心跳缺失时readiness为503。数据库开发端口只绑定`127.0.0.1:55434`。

## 操作顺序

1. 管理员创建运营、两位不同实际人员的标注员，以及需要时的第三仲裁员、独立负责人、审计员和独立复验人`verifier`。
2. 运营在“候选导入”提交完整JSON或UTF-8 JSONL及契约/报告，等待持久任务完成并查看逐项错误。可先使用[12题合成材料](contracts/examples/demo-import.json)。导入者已经看过草案，会登记暴露，不能再担任这些材料的首次盲答人员。
3. 按dataset创建统计批次，选定固定A/B和随机种子。样本为`max(8,ceil(0.1N))`，按难度分层；N不足8会明确阻塞。
4. A/B分别在“我的任务”独立阅读原文、暂存并封存BLIND。此时看不到草案、另一方标签或κ。
5. 整个批次双方BLIND全部封存后，运营统一开放REVIEW，进入答案要点、证据相关度、可答性三栏。每点/每文档及题级判断分别记录理由；要点绑定原文定位，wrong确无支持时填写已核查范围。原文与本人盲答可展开参考。
6. 运营计算批次一致性。κ≥0.7仍须人工逐题确认最终内容；灰区须第三人裁决及独立负责人确认；κ<0.6保留旧轮，校准后从冻结总体重抽完整新轮。
7. 实质修订/定位变更先登记候选并指定独立verifier复验；闭环后才可封存定稿和创建交接。详情页展示N/n、摘要及受控原始复算资料；实际交付后登记发送证据。未抽中单元完整传递，不生成虚假人工标签。

标注封存不可编辑；草稿有版本冲突检查；重试有幂等键；材料和跨D1/D7同源族登记暴露。更换人员不能把已经读过草案的人重新当作首次盲答人员。详细操作及异常处理见[运行手册](docs/operations.md)。

旧v1任务保留只读，未完成的旧轮由运营登记原因后建新轮升级，避免补造历史理由。“我的任务”当前若标记BLIND，仍先独立作答；整批统一开放后才有三栏。材料问题可在任务页上报，由独立运营处理，BLIND整席位替换保留原分配与迟到历史。

## 验证与部署

```powershell
.\scripts\dev.ps1 test
docker compose --env-file .env -f deploy/compose.yml up -d --build --wait
```

开发测试只使用专用`s4_test`数据库；浏览器演练准备与启动见运行手册。锁文件包括`backend/uv.lock`、带hash的生产`requirements.lock`和两份`package-lock.json`；基础镜像固定digest。

备份/隔离恢复、日志、CI、SBOM及已知待验收项分别见[运行手册](docs/operations.md)和[验收记录](docs/acceptance.md)。正式部署还需真实20题双人演练、专项规则确认、外部联调及目标环境恢复证据；本地自动化结果不能替代这些记录。
